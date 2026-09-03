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

from ...domain.agency_models import (
    CUSTOMER_FIELD_LABELS,
    CUSTOMER_PROFILE_FIELDS,
    REQUIRED_ESTIMATE_CUSTOMER_FIELDS,
    AgencyRecord,
)
from ...domain.agency_naming import (
    clean_agency_abbreviation,
    effective_agency_abbreviation,
)
from ...domain.project_codec import preferences_from_dict
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

_AGENCY_EDITABLE_FIELDS = ("abbreviation",) + tuple(
    field for field in CUSTOMER_PROFILE_FIELDS if field != "name"
) + (
    "customer_since",
    "default_preferences",
    "pricing_overrides",
)


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

    taxable = rec.get("taxable")
    if isinstance(taxable, str):
        normalized_taxable = taxable.strip().lower()
        taxable = normalized_taxable in {"true", "yes", "1"} if normalized_taxable else False
    elif not isinstance(taxable, bool):
        taxable = False

    return AgencyRecord(
        agency_id=str(rec.get("agency_id", "")),
        name=str(rec.get("name", "")),
        abbreviation=clean_agency_abbreviation(rec.get("abbreviation", "")),
        contact_name=str(rec.get("contact_name", "")),
        contact_title=str(rec.get("contact_title", "")),
        contact_phone=contact_phone,
        contact_email=contact_email,
        mobile_phone=str(rec.get("mobile_phone", "")),
        fax=str(rec.get("fax", "")),
        website=str(rec.get("website", "")),
        bill_address_line1=str(rec.get("bill_address_line1", "")),
        bill_address_line2=str(rec.get("bill_address_line2", "")),
        bill_address_line3=str(rec.get("bill_address_line3", "")),
        bill_city=str(rec.get("bill_city", "")),
        bill_state=str(rec.get("bill_state", "")),
        bill_postal_code=str(rec.get("bill_postal_code", "")),
        bill_country=str(rec.get("bill_country", "")),
        ship_address_line1=str(rec.get("ship_address_line1", "")),
        ship_address_line2=str(rec.get("ship_address_line2", "")),
        ship_address_line3=str(rec.get("ship_address_line3", "")),
        ship_city=str(rec.get("ship_city", "")),
        ship_state=str(rec.get("ship_state", "")),
        ship_postal_code=str(rec.get("ship_postal_code", "")),
        ship_country=str(rec.get("ship_country", "")),
        notes=str(rec.get("notes", "")),
        taxable=taxable,
        customer_since=str(rec.get("customer_since", "")),
        default_preferences=preferences_from_dict(rec.get("default_preferences", {})),
        pricing_overrides=_clean_pricing_overrides(rec.get("pricing_overrides", {})),
        qb_customer_id=str(rec.get("qb_customer_id", "")),
        company_folder_id=str(rec.get("company_folder_id", "")),
        company_folder_path=str(rec.get("company_folder_path", "")),
        company_folder_status=str(rec.get("company_folder_status", "not_provisioned")),
        company_folder_error=str(rec.get("company_folder_error", "")),
        shop_folder_id=str(rec.get("shop_folder_id", "")),
        shop_folder_path=str(rec.get("shop_folder_path", "")),
        shop_folder_status=str(rec.get("shop_folder_status", "not_provisioned")),
        shop_folder_error=str(rec.get("shop_folder_error", "")),
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


def _clean_agency_field(field: str, value: object) -> object:
    """Normalize a UI/API field without treating a missing value as an erase."""
    if field == "default_preferences":
        return preferences_from_dict(value)
    if field == "abbreviation":
        return clean_agency_abbreviation(value)
    if field == "pricing_overrides":
        return _clean_pricing_overrides(value)
    if field == "taxable":
        if value is None or value == "":
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1"}
        return bool(value)
    return str(value or "").strip()


def _clean_pricing_overrides(value: object) -> dict[str, float]:
    from .customer_pricing_service import normalize_overrides
    return normalize_overrides(value)


def customer_profile_fields(record: AgencyRecord) -> dict:
    """Return the customer fields that can be synced to/from QuickBooks."""
    return {field: getattr(record, field) for field in CUSTOMER_PROFILE_FIELDS}


def missing_estimate_customer_fields(record_or_fields: AgencyRecord | dict) -> list[str]:
    """Return friendly labels for profile fields required before an estimate."""
    if isinstance(record_or_fields, AgencyRecord):
        fields = customer_profile_fields(record_or_fields)
    else:
        fields = record_or_fields
    missing: list[str] = []
    for field in REQUIRED_ESTIMATE_CUSTOMER_FIELDS:
        value = fields.get(field)
        if value is None or not str(value).strip():
            missing.append(CUSTOMER_FIELD_LABELS[field])
    return missing


def merge_missing_customer_profile(record: AgencyRecord, customer: dict) -> list[str]:
    """Fill only blank local profile fields from a QBO customer.

    Down-sync must be additive: an omitted value in QBO can never erase a
    locally-entered value, and a populated local value remains the user's
    explicit choice. Agency names are likewise left alone after creation.
    """
    changed: list[str] = []
    for field in CUSTOMER_PROFILE_FIELDS:
        if field == "name":
            continue
        current = getattr(record, field)
        incoming = customer.get(field)
        current_missing = current is None or not str(current).strip()
        incoming_present = incoming is not None and bool(str(incoming).strip())
        if current_missing and incoming_present:
            setattr(record, field, _clean_agency_field(field, incoming))
            changed.append(field)
    return changed


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


def _project_agency_snapshots(paths: AppPaths) -> dict[str, dict]:
    """Recover the minimal agency identity retained by project records."""
    snapshots: dict[str, dict] = {}
    projects_dir = paths.workspace_projects_dir
    if not projects_dir.exists():
        return snapshots
    for project_path in projects_dir.glob("*/project.json"):
        try:
            project = json.loads(project_path.read_text("utf-8"))
            customer = project.get("customer") or {}
            agency_id = str(customer.get("agency_id", "")).strip()
            name = str(customer.get("agency") or customer.get("name") or "").strip()
            if not agency_id or not name:
                continue
            row = snapshots.setdefault(agency_id, {
                "agency_id": agency_id,
                "name": name,
                "abbreviation": str(customer.get("agency_abbreviation", "") or "").strip(),
                "contact_name": "",
                "contact_phone": "",
                "contact_email": "",
            })
            # Prefer the newest nonblank profile fragments without ever
            # combining different durable agency IDs by name.
            for target, source in (
                ("contact_name", "contact"),
                ("contact_phone", "phone"),
                ("contact_email", "email"),
            ):
                if not row[target] and customer.get(source):
                    row[target] = str(customer[source]).strip()
        except Exception:
            _log.exception("Skipping project agency snapshot from %s", project_path)
    return snapshots


def _agency_response_row(record: AgencyRecord, *, source: str = "agency") -> dict:
    row = asdict(record)
    row["effective_abbreviation"] = effective_agency_abbreviation(
        record.abbreviation, record.name,
    )
    row["record_source"] = source
    return row


def load_agency_rows(paths: AppPaths) -> list[dict]:
    """List persisted agencies plus editable recovery rows from projects."""
    rows = {
        record.agency_id: _agency_response_row(record)
        for record in load_agencies(paths)
        if record.agency_id and record.name.strip()
    }
    for agency_id, snapshot in _project_agency_snapshots(paths).items():
        if agency_id in rows:
            continue
        recovered = AgencyRecord(
            agency_id=agency_id,
            name=snapshot["name"],
            abbreviation=effective_agency_abbreviation(
                snapshot["abbreviation"], snapshot["name"],
            ),
            contact_name=snapshot["contact_name"],
            contact_phone=snapshot["contact_phone"],
            contact_email=snapshot["contact_email"],
        )
        rows[agency_id] = _agency_response_row(recovered, source="project")
    return sorted(rows.values(), key=lambda row: row["name"].casefold())


def _propagate_agency_identity_to_projects(
    record: AgencyRecord,
    paths: AppPaths,
    *,
    schedule_folders: bool = True,
) -> list[str]:
    """Refresh mutable name/abbreviation snapshots on linked projects."""
    from ...inputs.project_entry import list_projects, save_project
    from .vehicle_folder_provisioning_service import (
        mark_project_folder_provisioning_pending,
        schedule_project_folder_provisioning,
    )

    abbreviation = effective_agency_abbreviation(record.abbreviation, record.name)
    updated: list[str] = []
    for project in list_projects(paths):
        if project.customer.agency_id != record.agency_id:
            continue
        if (
            project.customer.agency == record.name
            and project.customer.agency_abbreviation == abbreviation
        ):
            continue
        project.customer.agency = record.name
        project.customer.agency_abbreviation = abbreviation
        mark_project_folder_provisioning_pending(project)
        save_project(project, paths)
        updated.append(project.project_id)
        if schedule_folders:
            schedule_project_folder_provisioning(project.project_id, paths)
    return updated


def restore_project_agency_records(
    paths: AppPaths,
    *,
    agency_ids: set[str] | None = None,
    mirror_to_cloud: bool = False,
) -> dict:
    """Materialize missing agency records from their durable project IDs.

    This explicit repair path does not call QuickBooks and never merges by
    name. It is intended for reviewed recovery when a project survived but its
    per-record agency file did not.
    """
    wanted = {str(value).strip() for value in agency_ids or set() if str(value).strip()}
    snapshots = _project_agency_snapshots(paths)
    records = _records(paths)
    now = _utcnow()
    restored: list[str] = []
    mirrored: list[str] = []
    failed: list[dict] = []
    from .shared_work_service import save_setting_to_cloud

    for agency_id, snapshot in snapshots.items():
        if wanted and agency_id not in wanted:
            continue
        if agency_id in records:
            if mirror_to_cloud and wanted:
                existing = records[agency_id]
                payload = json.dumps(asdict(existing), indent=2) + "\n"
                if save_setting_to_cloud(f"agencies/{agency_id}.json", payload):
                    mirrored.append(agency_id)
                else:
                    failed.append({"agency_id": agency_id, "error": "SharePoint mirror failed"})
            continue
        record = AgencyRecord(
            agency_id=agency_id,
            name=snapshot["name"],
            abbreviation=effective_agency_abbreviation(
                snapshot["abbreviation"], snapshot["name"],
            ),
            contact_name=snapshot["contact_name"],
            contact_phone=snapshot["contact_phone"],
            contact_email=snapshot["contact_email"],
            created_at=now,
            updated_at=now,
        )
        try:
            _write_record(record, paths)
            records[agency_id] = record
            if mirror_to_cloud:
                payload = json.dumps(asdict(record), indent=2) + "\n"
                if not save_setting_to_cloud(f"agencies/{agency_id}.json", payload):
                    raise RuntimeError("SharePoint mirror failed")
                mirrored.append(agency_id)
            _propagate_agency_identity_to_projects(
                record, paths, schedule_folders=False,
            )
            restored.append(agency_id)
        except Exception as exc:
            _log.exception("Could not restore project-backed agency %s", agency_id)
            failed.append({"agency_id": agency_id, "error": str(exc)})
    return {
        "ok": not failed,
        "restored": restored,
        "restored_count": len(restored),
        "mirrored": mirrored,
        "failed": failed,
    }


def load_agency_choices(paths: AppPaths) -> list[dict]:
    """Return every stable agency identity that can own a preset.

    The Agency database is primary, but older/current projects can retain a
    valid ``customer.agency_id`` after the corresponding per-record agency file
    is absent locally (for example after a migration or a delayed cloud pull).
    Those project identities must remain selectable for presets; otherwise the
    preset creator silently omits agencies that are visibly in active work.

    Project-derived entries are read-only choices. Saving an agency with that
    ID later naturally materializes the normal per-record Agency record.
    """
    return [
        {
            "agency_id": row["agency_id"],
            "name": row["name"],
            "abbreviation": row["effective_abbreviation"],
            "choice_source": row["record_source"],
        }
        for row in load_agency_rows(paths)
    ]


def handle_list_agencies(paths: AppPaths) -> dict:
    return {"ok": True, "agencies": load_agency_rows(paths)}


def handle_list_agency_choices(paths: AppPaths) -> dict:
    choices = load_agency_choices(paths)
    return {"ok": True, "agencies": choices, "total": len(choices)}


def get_agency(paths: AppPaths, agency_id: str) -> AgencyRecord | None:
    """Return a single agency record from the cache, or None if absent."""
    return _records(paths).get(agency_id)


_AGENCY_FOLDER_STATE_FIELDS = {
    "company_folder_id", "company_folder_path", "company_folder_status", "company_folder_error",
    "shop_folder_id", "shop_folder_path", "shop_folder_status", "shop_folder_error",
}


def save_agency_folder_state(paths: AppPaths, agency_id: str, values: dict) -> AgencyRecord | None:
    """Persist only operational folder identity/status fields.

    Folder provisioning runs asynchronously. Reloading from the cache and
    applying this narrow whitelist prevents its eventual Graph response from
    overwriting agency profile edits made while the request was in flight.
    """
    record = _records(paths).get(agency_id)
    if record is None:
        return None
    for field, value in values.items():
        if field in _AGENCY_FOLDER_STATE_FIELDS:
            setattr(record, field, str(value or ""))
    _write_record(record, paths)
    serialized = json.dumps(asdict(record), indent=2) + "\n"
    from .shared_work_service import save_setting_to_cloud_in_background
    save_setting_to_cloud_in_background(f"agencies/{record.agency_id}.json", serialized)
    return record


def set_qb_customer_id(paths: AppPaths, agency_id: str, qb_customer_id: str) -> bool:
    """Stamp the QB Customer link onto an agency and persist + cloud-mirror it.

    Used by the QuickBooks up-sync to write back the Id of a Customer it just
    created. Deliberately does NOT go through ``handle_save_agency`` — that
    would re-trigger the up-sync and loop. Returns False (no write) when the
    agency is missing or the id is already what we'd set.
    """
    rec = _records(paths).get(agency_id)
    if rec is None:
        return False
    qb_id = (qb_customer_id or "").strip()
    if rec.qb_customer_id == qb_id:
        return False
    rec.qb_customer_id = qb_id
    rec.updated_at = _utcnow()
    _write_record(rec, paths)
    serialized = json.dumps(asdict(rec), indent=2) + "\n"
    from .shared_work_service import save_setting_to_cloud_in_background
    save_setting_to_cloud_in_background(f"agencies/{rec.agency_id}.json", serialized)
    return True


def update_agency_customer_profile(
    paths: AppPaths,
    agency_id: str,
    fields: dict,
) -> AgencyRecord | None:
    """Persist explicitly confirmed customer-profile values without up-syncing.

    Estimate confirmation may collect missing fields immediately before the
    Customer/Estimate API calls.  It must save those fields locally, but it
    must not call ``handle_save_agency`` because that would schedule a second,
    racing customer write in the background.
    """
    rec = _records(paths).get(agency_id)
    if rec is None:
        return None

    changed = False
    for field in CUSTOMER_PROFILE_FIELDS:
        if field not in fields:
            continue
        value = _clean_agency_field(field, fields[field])
        if getattr(rec, field) != value:
            setattr(rec, field, value)
            changed = True
    if not changed:
        return rec

    rec.updated_at = _utcnow()
    _write_record(rec, paths)
    serialized = json.dumps(asdict(rec), indent=2) + "\n"
    from .shared_work_service import save_setting_to_cloud_in_background
    save_setting_to_cloud_in_background(f"agencies/{rec.agency_id}.json", serialized)
    return rec


def handle_save_agency_default_preferences(body: dict, paths: AppPaths) -> dict:
    """Save an agency's standard equipment choices without touching QuickBooks.

    Project users can promote an outlier project's current selections to the
    agency standard.  These preferences are app-only defaults for future
    projects, so this intentionally mirrors to shared storage but does not
    schedule a QuickBooks Customer update.
    """
    try:
        agency_id = str(body.get("agency_id", "")).strip()
        if not agency_id:
            return {"ok": False, "error": "Select a saved agency first"}
        validate_safe_id(agency_id, label="agency_id")
        if "default_preferences" not in body:
            return {"ok": False, "error": "Default preferences are required"}

        record = _records(paths).get(agency_id)
        if record is None:
            return {"ok": False, "error": "Agency not found"}

        record.default_preferences = preferences_from_dict(body["default_preferences"])
        record.updated_at = _utcnow()
        _write_record(record, paths)
        serialized = json.dumps(asdict(record), indent=2) + "\n"
        from .shared_work_service import save_setting_to_cloud_in_background
        save_setting_to_cloud_in_background(f"agencies/{record.agency_id}.json", serialized)
        # Agencies are live per-record settings whose authoritative cloud path
        # is the direct SharePoint mirror.  This narrow action must not depend
        # on the settings-repository proposal pipeline to report a successful
        # local/default save to project users.
        return {"ok": True, "agency": asdict(record)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to save agency default preferences")
        return {"ok": False, "error": str(exc)}


def handle_search_agencies(query: str, paths: AppPaths) -> dict:
    query = query.strip()
    if not query:
        return {"ok": True, "matches": []}
    records = load_agency_choices(paths)
    if not records:
        return {"ok": True, "matches": []}

    norm_query = _normalize(query)
    norm_names = [_normalize(r["name"]) for r in records]
    norm_abbreviations = [_normalize(r["abbreviation"]) for r in records]

    seen: set[str] = set()
    matches: list[dict] = []

    def add_where(predicate) -> None:
        for i, record in enumerate(records):
            agency_id = record["agency_id"]
            if agency_id not in seen and predicate(i):
                seen.add(agency_id)
                matches.append(record)

    # Exact abbreviation/name hits must win before broad name substrings.
    # Otherwise searching ICE fills the eight-result cap with agencies whose
    # names contain "Police" before the actual ICE record is reached.
    add_where(lambda i: norm_abbreviations[i] == norm_query)
    add_where(lambda i: norm_names[i] == norm_query)
    add_where(lambda i: norm_query in norm_abbreviations[i])
    add_where(lambda i: norm_query in norm_names[i])

    if len(matches) < 8:
        close = difflib.get_close_matches(norm_query, norm_names, n=8, cutoff=0.5)
        for match_norm in close:
            for i, nn in enumerate(norm_names):
                agency_id = records[i]["agency_id"]
                if nn == match_norm and agency_id not in seen:
                    seen.add(agency_id)
                    matches.append(records[i])
                    break

    return {"ok": True, "matches": matches[:8]}


def handle_save_agency(body: dict, paths: AppPaths) -> dict:
    try:
        name = str(body.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "Agency name is required"}

        agency_id = str(body.get("agency_id", "")).strip() or str(uuid.uuid4())
        now = _utcnow()

        records = _records(paths)
        existing = records.get(agency_id)
        if existing:
            existing.name = name
            # Only fields explicitly present in the request are changed. This
            # keeps older callers from accidentally blanking the expanded
            # customer profile when they edit just one field.
            for field in _AGENCY_EDITABLE_FIELDS:
                if field in body:
                    setattr(existing, field, _clean_agency_field(field, body[field]))
            existing.updated_at = now
            record = existing
        else:
            new_fields = {
                field: _clean_agency_field(field, body.get(field))
                for field in _AGENCY_EDITABLE_FIELDS
                if field in body
            }
            record = AgencyRecord(
                agency_id=agency_id,
                name=name,
                created_at=now,
                updated_at=now,
                **new_fields,
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
        affected_projects = _propagate_agency_identity_to_projects(record, paths)
        # Mirror the agency to QuickBooks before returning so a rejected
        # Customer create/update is visible to the user instead of disappearing
        # inside a daemon thread. The local agency remains saved either way.
        from . import qb_sync_service
        qb_sync = qb_sync_service.push_agency_after_save(paths, record.agency_id)
        # Folder trees are project-scoped. Agency Manager also contains every
        # imported QBO Customer, many of which are vendors or non-build
        # customers. Linked project identity changes were already scheduled by
        # _propagate_agency_identity_to_projects above; a standalone agency save
        # must never create Company/Shop roots.
        folder_provisioning_scheduled = bool(affected_projects)
        # A successful create stamps qb_customer_id back onto the cached record.
        saved_record = _records(paths).get(record.agency_id) or record
        return {
            "ok": True,
            "agency": asdict(saved_record),
            "qb_sync": qb_sync,
            "folder_provisioning_scheduled": folder_provisioning_scheduled,
            "updated_project_ids": affected_projects,
            **proposal_result,
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to save agency")
        return {"ok": False, "error": str(exc)}


# ── QuickBooks customer import (down-sync) ──────────────────────────────────────
#
# Pulls QB Customers into agencies. Match precedence: existing qb_customer_id,
# then normalized-name. New customers create agencies; matched ones are linked
# (qb_customer_id stamped) and have empty profile fields filled from QB —
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
            merge_missing_customer_profile(existing, cust)
            existing.updated_at = now
            record = existing
            updated += 1
        else:
            imported_fields = {
                field: _clean_agency_field(field, cust.get(field))
                for field in CUSTOMER_PROFILE_FIELDS
                if field != "name" and field in cust
            }
            record = AgencyRecord(
                agency_id=str(uuid.uuid4()),
                name=name,
                qb_customer_id=qb_id,
                created_at=now,
                updated_at=now,
                **imported_fields,
            )
            records[record.agency_id] = record
            created += 1
        if qb_id:
            by_qb[qb_id] = record
        by_name.setdefault(_normalize(record.name), record)

        try:
            _write_record(record, paths)
            # Pass the local path (not the serialized content) so the batch
            # mirror re-reads at upload time and skips any record deleted in
            # the meantime — prevents an import from resurrecting a deletion.
            to_mirror.append(
                (f"agencies/{record.agency_id}.json", str(_record_path(record.agency_id, paths)))
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
        referenced = [
            snapshot for snapshot in _project_agency_snapshots(paths).values()
            if snapshot["agency_id"] == agency_id
        ]
        if referenced:
            return {
                "ok": False,
                "error": (
                    "This agency is still used by one or more projects. "
                    "Projects must be reassigned or removed before the agency can be deleted."
                ),
            }
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
        cloud_ok = delete_setting_from_cloud(f"agencies/{agency_id}.json")
        result = {"ok": True, **proposal_result}
        if cloud_ok is False:
            # Local + proposal delete succeeded, but the direct cloud removal
            # failed — without surfacing this the record silently resyncs and
            # looks "undeletable." Tell the caller so the UI can warn + retry.
            result["cloud_warning"] = (
                "Removed locally, but the cloud copy could not be deleted "
                "(it may reappear on the next sync). Try deleting it again."
            )
        return result
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        _log.exception("Failed to delete agency %s", agency_id)
        return {"ok": False, "error": str(exc)}
