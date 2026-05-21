from __future__ import annotations

import difflib
import json
import logging
import re
import string
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ...domain.agency_models import AgencyRecord
from ...paths import AppPaths
from ...storage.local import LocalStorageProvider
from ...storage.safety import validate_safe_id

_log = logging.getLogger(__name__)

_ABBREV: list[tuple[str, str]] = [
    (r"\bst\.?\s", "saint "),
    (r"\bpd\b", "police department"),
    (r"\bso\b", "sheriffs office"),
    (r"\bsheriff'?s?\s+dept\b", "sheriffs office"),
    (r"\bsheriff'?s?\s+department\b", "sheriffs office"),
    (r"\bpolice\s+dept\b", "police department"),
    (r"\bdept\b", "department"),
    (r"\bcnty\b", "county"),
    (r"\bcty\b", "county"),
]


# ── paths ──────────────────────────────────────────────────────────────────────

def _agencies_dir(paths: AppPaths) -> Path:
    return paths.workspace_dir / "agencies"


def _legacy_agencies_file(paths: AppPaths) -> Path:
    return paths.workspace_dir / "agencies.json"


def _record_path(agency_id: str, paths: AppPaths) -> Path:
    return _agencies_dir(paths) / f"{agency_id}.json"


# ── in-memory cache ────────────────────────────────────────────────────────────
#
# Live fuzzy search fires every 220ms on keystroke. With monolithic JSON this was
# one file read per request (cheap); with per-record JSON it would be one stat +
# open + parse per record per keystroke. The cache loads the directory once on
# first access and is updated per-record on save/delete.
#
# Keyed by str(agencies_dir) so tests with multiple AppPaths don't collide.

_cache: dict[str, dict[str, AgencyRecord]] = {}


def _cache_key(paths: AppPaths) -> str:
    return str(_agencies_dir(paths))


def _record_from_dict(rec: dict) -> AgencyRecord:
    # Old records may have a single contact_info field instead of phone/email.
    old_info = str(rec.get("contact_info", ""))
    contact_phone = str(rec.get("contact_phone", ""))
    contact_email = str(rec.get("contact_email", ""))
    if old_info and not contact_phone and not contact_email:
        if "@" in old_info:
            contact_email = old_info
        else:
            contact_phone = old_info
    return AgencyRecord(
        agency_id=str(rec.get("agency_id", "")),
        name=str(rec.get("name", "")),
        contact_name=str(rec.get("contact_name", "")),
        contact_phone=contact_phone,
        contact_email=contact_email,
        customer_since=str(rec.get("customer_since", "")),
        created_at=str(rec.get("created_at", "")),
        updated_at=str(rec.get("updated_at", "")),
    )


def _load_records_from_disk(paths: AppPaths) -> dict[str, AgencyRecord]:
    """Build the cache from disk.

    Per-record dir wins. If it doesn't exist but the legacy monolithic
    `agencies.json` does, one-shot migrate every record into the per-record dir
    so future saves don't orphan the other entries. The legacy file is left in
    place as a backup; future loads see the per-record dir and ignore it.
    """
    records: dict[str, AgencyRecord] = {}
    per_record_dir = _agencies_dir(paths)
    if per_record_dir.exists():
        for path in per_record_dir.glob("*.json"):
            try:
                rec = _record_from_dict(json.loads(path.read_text("utf-8")))
                if rec.agency_id:
                    records[rec.agency_id] = rec
            except Exception:
                _log.exception("Skipping corrupt agency file: %s", path)
        return records

    legacy = _legacy_agencies_file(paths)
    if not legacy.exists():
        return records
    try:
        data = json.loads(legacy.read_text("utf-8"))
        for rec in data.get("agencies", []):
            record = _record_from_dict(rec)
            if record.agency_id:
                records[record.agency_id] = record
    except Exception:
        _log.exception("Unexpected error loading legacy agencies from %s", legacy)
        return records

    # One-shot migration: write every legacy record to the per-record dir so
    # future saves treat that dir as the source of truth.
    storage = LocalStorageProvider()
    for record in records.values():
        try:
            validate_safe_id(record.agency_id, label="agency_id")
            storage.write_text(
                str(_record_path(record.agency_id, paths)),
                json.dumps(asdict(record), indent=2) + "\n",
            )
        except Exception:
            _log.exception("Failed to migrate agency %s to per-record file", record.agency_id)
    _log.info("Migrated %d agencies from %s to %s", len(records), legacy, per_record_dir)
    return records


def _records(paths: AppPaths) -> dict[str, AgencyRecord]:
    key = _cache_key(paths)
    if key not in _cache:
        _cache[key] = _load_records_from_disk(paths)
    return _cache[key]


def _invalidate_cache(paths: AppPaths) -> None:
    _cache.pop(_cache_key(paths), None)


# ── persistence ────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    for pattern, replacement in _ABBREV:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _write_record(record: AgencyRecord, paths: AppPaths) -> None:
    validate_safe_id(record.agency_id, label="agency_id")
    LocalStorageProvider().write_text(
        str(_record_path(record.agency_id, paths)),
        json.dumps(asdict(record), indent=2) + "\n",
    )


def _delete_record_file(agency_id: str, paths: AppPaths) -> bool:
    validate_safe_id(agency_id, label="agency_id")
    path = _record_path(agency_id, paths)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── public API ─────────────────────────────────────────────────────────────────

def load_agencies(paths: AppPaths) -> list[AgencyRecord]:
    """Return all agencies as a list (sorted by name for stable display).

    Compatibility shim for callers that expect the pre-cache list shape. Reads
    from the cache, never directly from disk.
    """
    return sorted(_records(paths).values(), key=lambda r: r.name.lower())


def handle_list_agencies(paths: AppPaths) -> dict:
    return {"ok": True, "agencies": [asdict(r) for r in load_agencies(paths)]}


def handle_search_agencies(query: str, paths: AppPaths) -> dict:
    query = query.strip()
    if not query:
        return {"ok": True, "matches": []}
    records = load_agencies(paths)
    if not records:
        return {"ok": True, "matches": []}

    norm_query = _normalize(query)
    norm_names = [_normalize(r.name) for r in records]

    seen: set[str] = set()
    matches: list[dict] = []

    for i, nn in enumerate(norm_names):
        if norm_query in nn and records[i].agency_id not in seen:
            seen.add(records[i].agency_id)
            matches.append({"agency_id": records[i].agency_id, "name": records[i].name})

    if len(matches) < 8:
        close = difflib.get_close_matches(norm_query, norm_names, n=8, cutoff=0.5)
        for match_norm in close:
            for i, nn in enumerate(norm_names):
                if nn == match_norm and records[i].agency_id not in seen:
                    seen.add(records[i].agency_id)
                    matches.append({"agency_id": records[i].agency_id, "name": records[i].name})
                    break

    return {"ok": True, "matches": matches[:8]}


def handle_save_agency(body: dict, paths: AppPaths) -> dict:
    try:
        name = str(body.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "Agency name is required"}

        agency_id = str(body.get("agency_id", "")).strip() or str(uuid.uuid4())
        contact_name = str(body.get("contact_name", "")).strip()
        contact_phone = str(body.get("contact_phone", "")).strip()
        contact_email = str(body.get("contact_email", "")).strip()
        customer_since = str(body.get("customer_since", "")).strip()
        now = _utcnow()

        records = _records(paths)
        existing = records.get(agency_id)
        if existing:
            existing.name = name
            existing.contact_name = contact_name
            existing.contact_phone = contact_phone
            existing.contact_email = contact_email
            existing.customer_since = customer_since
            existing.updated_at = now
            record = existing
        else:
            record = AgencyRecord(
                agency_id=agency_id,
                name=name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                customer_since=customer_since,
                created_at=now,
                updated_at=now,
            )
            records[agency_id] = record

        _write_record(record, paths)
        return {"ok": True, "agency": asdict(record)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to save agency")
        return {"ok": False, "error": str(exc)}


def handle_delete_agency(agency_id: str, paths: AppPaths) -> dict:
    try:
        records = _records(paths)
        if agency_id not in records:
            return {"ok": False, "error": f"Agency not found: {agency_id}"}
        _delete_record_file(agency_id, paths)
        records.pop(agency_id, None)
        return {"ok": True}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to delete agency %s", agency_id)
        return {"ok": False, "error": str(exc)}
