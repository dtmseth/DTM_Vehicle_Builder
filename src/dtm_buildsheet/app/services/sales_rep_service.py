from __future__ import annotations

import difflib
import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ...domain.sales_rep_models import SalesRepRecord
from ...paths import AppPaths
from ...storage.local import LocalStorageProvider
from ...storage.safety import validate_safe_id

_log = logging.getLogger(__name__)


# ── paths ──────────────────────────────────────────────────────────────────────

def _reps_dir(paths: AppPaths) -> Path:
    return paths.workspace_dir / "sales_reps"


def _legacy_reps_file(paths: AppPaths) -> Path:
    return paths.workspace_dir / "sales_reps.json"


def _record_path(rep_id: str, paths: AppPaths) -> Path:
    return _reps_dir(paths) / f"{rep_id}.json"


# ── in-memory cache ────────────────────────────────────────────────────────────
# See agency_service for the rationale. Same pattern.

_cache: dict[str, dict[str, SalesRepRecord]] = {}


def _cache_key(paths: AppPaths) -> str:
    return str(_reps_dir(paths))


def _record_from_dict(rec: dict) -> SalesRepRecord:
    return SalesRepRecord(
        rep_id=str(rec.get("rep_id", "")),
        name=str(rec.get("name", "")),
        phone=str(rec.get("phone", "")),
        email=str(rec.get("email", "")),
        created_at=str(rec.get("created_at", "")),
        updated_at=str(rec.get("updated_at", "")),
    )


def _load_records_from_disk(paths: AppPaths) -> dict[str, SalesRepRecord]:
    """Per-record dir wins; legacy monolithic file triggers one-shot migration."""
    records: dict[str, SalesRepRecord] = {}
    per_record_dir = _reps_dir(paths)
    if per_record_dir.exists():
        for path in per_record_dir.glob("*.json"):
            try:
                rec = _record_from_dict(json.loads(path.read_text("utf-8")))
                if rec.rep_id:
                    records[rec.rep_id] = rec
            except Exception:
                _log.exception("Skipping corrupt sales rep file: %s", path)
        return records

    legacy = _legacy_reps_file(paths)
    if not legacy.exists():
        return records
    try:
        data = json.loads(legacy.read_text("utf-8"))
        for rec in data.get("sales_reps", []):
            record = _record_from_dict(rec)
            if record.rep_id:
                records[record.rep_id] = record
    except Exception:
        _log.exception("Unexpected error loading legacy sales reps from %s", legacy)
        return records

    storage = LocalStorageProvider()
    for record in records.values():
        try:
            validate_safe_id(record.rep_id, label="rep_id")
            storage.write_text(
                str(_record_path(record.rep_id, paths)),
                json.dumps(asdict(record), indent=2) + "\n",
            )
        except Exception:
            _log.exception("Failed to migrate sales rep %s to per-record file", record.rep_id)
    _log.info("Migrated %d sales reps from %s to %s", len(records), legacy, per_record_dir)
    return records


def _records(paths: AppPaths) -> dict[str, SalesRepRecord]:
    key = _cache_key(paths)
    if key not in _cache:
        _cache[key] = _load_records_from_disk(paths)
    return _cache[key]


# ── persistence ────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_record(record: SalesRepRecord, paths: AppPaths) -> None:
    validate_safe_id(record.rep_id, label="rep_id")
    LocalStorageProvider().write_text(
        str(_record_path(record.rep_id, paths)),
        json.dumps(asdict(record), indent=2) + "\n",
    )


def _delete_record_file(rep_id: str, paths: AppPaths) -> bool:
    validate_safe_id(rep_id, label="rep_id")
    path = _record_path(rep_id, paths)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── public API ─────────────────────────────────────────────────────────────────

def load_reps(paths: AppPaths) -> list[SalesRepRecord]:
    """Return all sales reps as a list (sorted by name)."""
    return sorted(_records(paths).values(), key=lambda r: r.name.lower())


def handle_list_reps(paths: AppPaths) -> dict:
    return {"ok": True, "sales_reps": [asdict(r) for r in load_reps(paths)]}


def handle_search_reps(query: str, paths: AppPaths) -> dict:
    query = query.strip()
    if not query:
        return {"ok": True, "matches": []}
    records = load_reps(paths)
    if not records:
        return {"ok": True, "matches": []}

    norm_q = query.lower()
    names_lower = [r.name.lower() for r in records]

    seen: set[str] = set()
    matches: list[dict] = []

    for i, nl in enumerate(names_lower):
        if norm_q in nl and records[i].rep_id not in seen:
            seen.add(records[i].rep_id)
            matches.append({"rep_id": records[i].rep_id, "name": records[i].name})

    if len(matches) < 8:
        close = difflib.get_close_matches(norm_q, names_lower, n=8, cutoff=0.5)
        for cn in close:
            for i, nl in enumerate(names_lower):
                if nl == cn and records[i].rep_id not in seen:
                    seen.add(records[i].rep_id)
                    matches.append({"rep_id": records[i].rep_id, "name": records[i].name})
                    break

    return {"ok": True, "matches": matches[:8]}


def handle_save_rep(body: dict, paths: AppPaths) -> dict:
    try:
        name = str(body.get("name", "")).strip()
        phone = str(body.get("phone", "")).strip()
        email = str(body.get("email", "")).strip()
        if not name:
            return {"ok": False, "error": "Name is required"}
        if not phone:
            return {"ok": False, "error": "Phone is required"}
        if not email:
            return {"ok": False, "error": "Email is required"}

        rep_id = str(body.get("rep_id", "")).strip() or str(uuid.uuid4())
        now = _utcnow()

        records = _records(paths)
        existing = records.get(rep_id)
        if existing:
            existing.name = name
            existing.phone = phone
            existing.email = email
            existing.updated_at = now
            record = existing
        else:
            record = SalesRepRecord(
                rep_id=rep_id,
                name=name,
                phone=phone,
                email=email,
                created_at=now,
                updated_at=now,
            )
            records[rep_id] = record

        _write_record(record, paths)
        return {"ok": True, "rep": asdict(record)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to save sales rep")
        return {"ok": False, "error": str(exc)}


def handle_delete_rep(rep_id: str, paths: AppPaths) -> dict:
    try:
        records = _records(paths)
        if rep_id not in records:
            return {"ok": False, "error": f"Rep not found: {rep_id}"}
        _delete_record_file(rep_id, paths)
        records.pop(rep_id, None)
        return {"ok": True}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to delete sales rep %s", rep_id)
        return {"ok": False, "error": str(exc)}
