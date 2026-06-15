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
from ..adapters.wiring import delete_via_proposal, save_via_proposal

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
        qb_customer_id=str(rec.get("qb_customer_id", "")),
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
            if path.name.startswith("."):  # skip shared-settings eTag cache
                continue
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


def warmup_cache(paths: AppPaths, *, force: bool = False) -> None:
    """Force the cache to load now (drives the one-shot legacy migration on launch).

    Pass ``force=True`` to invalidate first — used by the periodic sync loop
    so newly-synced agency files from teammates become visible without
    needing an app restart.
    """
    if force:
        _invalidate_cache(paths)
    _records(paths)


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
        serialized = json.dumps(asdict(record), indent=2) + "\n"
        proposal_result = save_via_proposal(
            target_file=f"agencies/{record.agency_id}.json",
            serialized_content=serialized,
            summary=f"{'Update' if existing else 'Add'} agency: {record.name}",
            category="general",
        )
        # Direct SP mirror so other devices see the new/updated record
        # within their next 60s sync, not whenever the dtm-shared-settings
        # publish workflow happens to wake up.
        from .shared_work_service import save_setting_to_cloud_in_background
        save_setting_to_cloud_in_background(
            f"agencies/{record.agency_id}.json", serialized,
        )
        return {"ok": True, "agency": asdict(record), **proposal_result}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to save agency")
        return {"ok": False, "error": str(exc)}


# ── QuickBooks customer import (down-sync) ──────────────────────────────────────
#
# Pulls QB Customers into agencies. Match precedence: existing qb_customer_id,
# then normalized-name. New customers create agencies; matched ones are linked
# (qb_customer_id stamped) and have empty contact fields filled from QB —
# existing non-empty values and the agency name are never clobbered.


def _match_existing_for_qb(
    cust: dict,
    by_qb: dict[str, AgencyRecord],
    by_name: dict[str, AgencyRecord],
) -> AgencyRecord | None:
    hit = by_qb.get(cust.get("qb_customer_id", ""))
    if hit:
        return hit
    return by_name.get(_normalize(cust.get("name", "")))


def preview_qb_customer_import(customers: list[dict], paths: AppPaths) -> dict:
    """Dry run: how many agencies a QB customer import would create vs update.

    Writes nothing. Used by the reviewed-import flow.
    """
    records = _records(paths)
    by_qb = {r.qb_customer_id: r for r in records.values() if r.qb_customer_id}
    by_name: dict[str, AgencyRecord] = {}
    for r in records.values():
        by_name.setdefault(_normalize(r.name), r)

    would_create = would_update = 0
    for cust in customers:
        if _match_existing_for_qb(cust, by_qb, by_name) is None:
            would_create += 1
        else:
            would_update += 1
    return {
        "ok": True,
        "total": len(customers),
        "would_create": would_create,
        "would_update": would_update,
    }


def upsert_agencies_from_qb(customers: list[dict], paths: AppPaths) -> dict:
    """Create/link agency records from QB customers. Returns {created, updated}.

    Cloud propagation is batched into a single background thread (direct SP
    mirror) rather than one thread + one audit proposal per record — a first
    import can be hundreds of customers, and flooding the audit repo / spawning
    a thread each would be abusive. The direct mirror is the canonical write
    path (the dtm-shared-settings repo is audit-only).
    """
    records = _records(paths)
    by_qb = {r.qb_customer_id: r for r in records.values() if r.qb_customer_id}
    by_name: dict[str, AgencyRecord] = {}
    for r in records.values():
        by_name.setdefault(_normalize(r.name), r)

    now = _utcnow()
    created = updated = 0
    to_mirror: list[tuple[str, str]] = []

    for cust in customers:
        name = str(cust.get("name", "")).strip()
        if not name:
            continue
        qb_id = str(cust.get("qb_customer_id", "")).strip()
        existing = _match_existing_for_qb(cust, by_qb, by_name)
        if existing:
            existing.qb_customer_id = qb_id or existing.qb_customer_id
            # Fill only empty contact fields; never clobber the user's data.
            if not existing.contact_email and cust.get("contact_email"):
                existing.contact_email = str(cust["contact_email"]).strip()
            if not existing.contact_phone and cust.get("contact_phone"):
                existing.contact_phone = str(cust["contact_phone"]).strip()
            if not existing.contact_name and cust.get("contact_name"):
                existing.contact_name = str(cust["contact_name"]).strip()
            existing.updated_at = now
            record = existing
            updated += 1
        else:
            record = AgencyRecord(
                agency_id=str(uuid.uuid4()),
                name=name,
                contact_name=str(cust.get("contact_name", "")).strip(),
                contact_phone=str(cust.get("contact_phone", "")).strip(),
                contact_email=str(cust.get("contact_email", "")).strip(),
                qb_customer_id=qb_id,
                created_at=now,
                updated_at=now,
            )
            records[record.agency_id] = record
            created += 1
        if qb_id:
            by_qb[qb_id] = record
        by_name.setdefault(_normalize(record.name), record)

        try:
            _write_record(record, paths)
            to_mirror.append(
                (f"agencies/{record.agency_id}.json", json.dumps(asdict(record), indent=2) + "\n")
            )
        except Exception:
            _log.exception("Failed to write imported agency %s", record.agency_id)

    if to_mirror:
        from .shared_work_service import save_settings_to_cloud_batch_in_background
        save_settings_to_cloud_batch_in_background(to_mirror)

    return {"ok": True, "created": created, "updated": updated, "total": created + updated}


def handle_delete_agency(agency_id: str, paths: AppPaths) -> dict:
    try:
        records = _records(paths)
        if agency_id not in records:
            return {"ok": False, "error": f"Agency not found: {agency_id}"}
        agency_name = records[agency_id].name
        _delete_record_file(agency_id, paths)
        records.pop(agency_id, None)
        # Propagate to cloud via the proposal pipeline (schema v3 action=delete).
        # No-op outside cloud mode; otherwise the pickup workflow git-rms the
        # file from dtm-shared-settings, the publish workflow drops it from
        # SharePoint /Settings/agencies/, and other devices' next sync
        # propagates the deletion to their local workspaces.
        proposal_result = delete_via_proposal(
            target_file=f"agencies/{agency_id}.json",
            summary=f"Delete agency: {agency_name}",
            category="general",
        )
        # Belt-and-suspenders: also drop the cloud copy directly so the
        # delete sticks even if the publish workflow is delayed by the
        # GitHub Actions cron throttle (was resurrecting deleted entries
        # on the next sync).
        from .shared_work_service import delete_setting_from_cloud
        delete_setting_from_cloud(f"agencies/{agency_id}.json")
        return {"ok": True, **proposal_result}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to delete agency %s", agency_id)
        return {"ok": False, "error": str(exc)}
