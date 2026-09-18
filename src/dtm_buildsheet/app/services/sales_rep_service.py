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
from ..adapters.wiring import delete_via_proposal, save_via_proposal

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
            if path.name.startswith("."):  # skip shared-settings eTag cache
                continue
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


def _invalidate_cache(paths: AppPaths) -> None:
    _cache.pop(_cache_key(paths), None)


def warmup_cache(paths: AppPaths, *, force: bool = False) -> None:
    """Force the cache to load now (drives the one-shot legacy migration on launch).

    Pass ``force=True`` to invalidate first — used by the periodic sync loop
    so newly-synced rep files from teammates become visible without an app
    restart.
    """
    if force:
        _invalidate_cache(paths)
    _records(paths)


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


def resolve_rep_selection(
    rep_id: str,
    rep_name: str,
    paths: AppPaths,
) -> SalesRepRecord | None:
    """Resolve a saved rep ID, repairing a deleted duplicate by exact name.

    Historical projects can retain the ID of a duplicate record after that
    duplicate is deleted.  The displayed name is safe to use only when it
    exactly identifies one current rep; fuzzy matches must remain a user
    decision.
    """
    records = load_reps(paths)
    wanted_id = str(rep_id or "").strip()
    if not wanted_id:
        return None
    current = next((record for record in records if record.rep_id == wanted_id), None)
    if current is not None:
        return current

    wanted_name = " ".join(str(rep_name or "").split()).casefold()
    if not wanted_name:
        return None
    matches = [
        record for record in records
        if " ".join(record.name.split()).casefold() == wanted_name
    ]
    return matches[0] if len(matches) == 1 else None


def reconcile_project_rep_links(paths: AppPaths) -> dict:
    """Repair project links to deleted duplicate reps when the match is exact."""
    from ...inputs.project_entry import list_projects, save_project

    current_ids = {record.rep_id for record in load_reps(paths)}
    repaired: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for project in list_projects(paths):
        old_id = str(project.customer.sales_rep_id or "").strip()
        old_name = str(project.customer.sales_rep or "").strip()
        if not old_id or old_id in current_ids:
            continue
        replacement = resolve_rep_selection(old_id, old_name, paths)
        item = {
            "project_id": project.project_id,
            "agency": project.customer.agency,
            "build_year": project.customer.build_year,
            "old_rep_id": old_id,
            "old_rep_name": old_name,
        }
        if replacement is None:
            unresolved.append(item)
            continue
        project.customer.sales_rep_id = replacement.rep_id
        project.customer.sales_rep = replacement.name
        save_project(project, paths)
        repaired.append({
            **item,
            "new_rep_id": replacement.rep_id,
            "new_rep_name": replacement.name,
        })
    return {"ok": not unresolved, "repaired": repaired, "unresolved": unresolved}


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
        duplicate = next((
            record for record in records.values()
            if record.rep_id != rep_id and record.name.strip().casefold() == name.casefold()
        ), None)
        if duplicate is not None:
            return {
                "ok": False,
                "error_code": "sales_rep_already_exists",
                "error": f"Sales rep already exists: {duplicate.name}",
                "existing_rep_id": duplicate.rep_id,
            }
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
        serialized = json.dumps(asdict(record), indent=2) + "\n"
        proposal_result = save_via_proposal(
            target_file=f"sales_reps/{record.rep_id}.json",
            serialized_content=serialized,
            summary=f"{'Update' if existing else 'Add'} sales rep: {record.name}",
            category="general",
        )
        # Direct SP mirror — see agency_service comment.
        from .shared_work_service import save_setting_to_cloud_in_background
        save_setting_to_cloud_in_background(
            f"sales_reps/{record.rep_id}.json", serialized,
        )
        return {"ok": True, "rep": asdict(record), **proposal_result}
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
        rep_name = records[rep_id].name
        _delete_record_file(rep_id, paths)
        records.pop(rep_id, None)
        # Propagate to cloud via the proposal pipeline (action=delete).
        proposal_result = delete_via_proposal(
            target_file=f"sales_reps/{rep_id}.json",
            summary=f"Delete sales rep: {rep_name}",
            category="general",
        )
        # Belt-and-suspenders direct delete (see agency_service comment).
        from .shared_work_service import delete_setting_from_cloud
        delete_setting_from_cloud(f"sales_reps/{rep_id}.json")
        return {"ok": True, **proposal_result}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to delete sales rep %s", rep_id)
        return {"ok": False, "error": str(exc)}
