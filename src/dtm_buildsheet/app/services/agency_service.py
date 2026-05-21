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


def _agencies_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / "agencies.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    text = text.lower().strip()
    # strip punctuation except letters, digits, spaces
    text = re.sub(r"[^\w\s]", " ", text)
    for pattern, replacement in _ABBREV:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_agencies(paths: AppPaths) -> list[AgencyRecord]:
    p = _agencies_path(paths)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
        results = []
        for rec in data.get("agencies", []):
            # backward compat: old records may have contact_info instead of phone/email
            old_info = str(rec.get("contact_info", ""))
            contact_phone = str(rec.get("contact_phone", ""))
            contact_email = str(rec.get("contact_email", ""))
            if old_info and not contact_phone and not contact_email:
                if "@" in old_info:
                    contact_email = old_info
                else:
                    contact_phone = old_info
            results.append(AgencyRecord(
                agency_id=str(rec.get("agency_id", "")),
                name=str(rec.get("name", "")),
                contact_name=str(rec.get("contact_name", "")),
                contact_phone=contact_phone,
                contact_email=contact_email,
                customer_since=str(rec.get("customer_since", "")),
                created_at=str(rec.get("created_at", "")),
                updated_at=str(rec.get("updated_at", "")),
            ))
        return results
    except Exception:
        _log.exception("Unexpected error loading agencies from %s", p)
        return []


def _save_agencies(records: list[AgencyRecord], paths: AppPaths) -> None:
    p = _agencies_path(paths)
    LocalStorageProvider().write_text(
        str(p),
        json.dumps({"schema_version": 1, "agencies": [asdict(r) for r in records]}, indent=2) + "\n",
    )


def handle_list_agencies(paths: AppPaths) -> dict:
    records = load_agencies(paths)
    return {"ok": True, "agencies": [asdict(r) for r in records]}


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

    # substring match first (catches partial typing like "cloud" → "St. Cloud PD")
    for i, nn in enumerate(norm_names):
        if norm_query in nn and records[i].agency_id not in seen:
            seen.add(records[i].agency_id)
            matches.append({"agency_id": records[i].agency_id, "name": records[i].name})

    # fuzzy fallback for typos / abbreviation differences
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
        records = load_agencies(paths)
        agency_id = str(body.get("agency_id", "")).strip()
        name = str(body.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "Agency name is required"}
        contact_name = str(body.get("contact_name", "")).strip()
        contact_phone = str(body.get("contact_phone", "")).strip()
        contact_email = str(body.get("contact_email", "")).strip()
        customer_since = str(body.get("customer_since", "")).strip()
        now = _utcnow()
        existing = next((r for r in records if r.agency_id == agency_id), None)
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
                agency_id=agency_id or str(uuid.uuid4()),
                name=name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                customer_since=customer_since,
                created_at=now,
                updated_at=now,
            )
            records.append(record)
        _save_agencies(records, paths)
        return {"ok": True, "agency": asdict(record)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_agency(agency_id: str, paths: AppPaths) -> dict:
    try:
        records = load_agencies(paths)
        before = len(records)
        records = [r for r in records if r.agency_id != agency_id]
        if len(records) == before:
            return {"ok": False, "error": f"Agency not found: {agency_id}"}
        _save_agencies(records, paths)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
