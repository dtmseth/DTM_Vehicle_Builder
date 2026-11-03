"""Independent used-vehicle strip records and fillable documentation PDFs.

One physical used vehicle owns one opaque ``used_vehicle_id``.  A strip record
may be reached from a Builder project's existing/trade-in vehicle, a buyback
record, or both.  The record deliberately does not reuse design finalization or
the dealer held-for-resale fields; those are separate business processes.

Photo capture is not implemented here yet.  The SharePoint folder contract and
required angle vocabulary are established now so a later phone/tablet client
can upload deterministically without changing record identity.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from ...inputs.project_entry import load_project, save_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
from . import used_vehicle_service, vehicle_sale_service


logger = logging.getLogger(__name__)

LOCAL_RECORD_FOLDER = "strip_documentation"
SHAREPOINT_ROOT = "Strip Documentation"
SHAREPOINT_DATA_FOLDER = f"{SHAREPOINT_ROOT}/Record Data"
SHAREPOINT_VEHICLE_SUBFOLDERS = ("Before Photos", "After Photos", "Documents")
_save_lock = threading.RLock()
_publish_lock = threading.RLock()

CHECKLIST_ITEMS: tuple[tuple[str, str], ...] = (
    ("emergency_lights", "Emergency lights"),
    ("sirens", "Sirens, speakers, and control equipment"),
    ("amber_warning_lights", "Amber warning lights"),
    ("spotlights", "Spotlights"),
    ("grille_lights", "Grille lights"),
    ("antennas", "Antennas"),
    ("emblems", "Emblems, decals, and identifying graphics"),
    ("emblem_outlines", "Emblem outlines, adhesive shadows, and ghosting"),
    ("other_identifying_equipment", "Other emergency vehicle equipment or identifying insignia"),
)

CHECKLIST_STATUSES = {"", "removed", "not_present", "needs_attention"}
DISPOSITIONS = {"", "purchased_by_dtm", "returned_to_agency", "other"}
WORKFLOW_STAGES = {"intake", "technician"}

PHOTO_ANGLES: tuple[tuple[str, str], ...] = (
    ("vin", "VIN plate / label"),
    ("front_left", "Front-left exterior"),
    ("front_right", "Front-right exterior"),
    ("rear_left", "Rear-left exterior"),
    ("rear_right", "Rear-right exterior"),
    ("driver_side", "Full driver side"),
    ("passenger_side", "Full passenger side"),
    ("roof", "Roof"),
    ("grille", "Grille and front warning-light locations"),
    ("rear_deck", "Rear window, deck, or hatch"),
    ("interior_controls", "Dashboard, console, and control equipment"),
    ("marking_details", "Former spotlight, antenna, emblem, and marking locations"),
)

_STRING_FIELDS = (
    "agency_name", "vehicle_year", "vehicle_make", "vehicle_model", "vehicle_color",
    "unit_number", "vin", "strip_date", "performed_by",
    "technician_signature", "technician_signed_date", "reviewed_by", "reviewer_signature",
    "reviewer_signed_date", "disposition", "disposition_other", "removal_notes",
    "photo_notes", "source_project_id", "source_unit_id", "source_individual_id",
    "vehicle_sale_record_id", "technician_started_at",
)

_INTAKE_EDITABLE_FIELDS = (
    "agency_name", "vehicle_year", "vehicle_make", "vehicle_model", "vehicle_color",
    "unit_number", "vin", "disposition", "disposition_other",
)
_TECHNICIAN_EDITABLE_FIELDS = (
    "strip_date", "technician_signature", "technician_signed_date", "reviewer_signature",
    "reviewer_signed_date", "removal_notes", "photo_notes",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_year() -> str:
    return str(datetime.now().year)


def _safe_id(value: Any, *, label: str) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", raw):
        raise ValueError(f"{label} is invalid")
    return raw


def _normalized_vin(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _safe_segment(value: Any, fallback: str) -> str:
    raw = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", str(value or ""))
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    return (raw or fallback)[:120]


def _record_dir(paths: AppPaths) -> Path:
    target = paths.workspace_dir / LOCAL_RECORD_FOLDER
    target.mkdir(parents=True, exist_ok=True)
    return target


def _record_path(paths: AppPaths, record_id: str) -> Path:
    return _record_dir(paths) / f"{_safe_id(record_id, label='Strip documentation record ID')}.json"


def _vehicle_folder_name(record: dict[str, Any]) -> str:
    vehicle = " ".join(filter(None, (
        str(record.get("vehicle_year") or "").strip(),
        str(record.get("vehicle_make") or "").strip(),
        str(record.get("vehicle_model") or "").strip(),
    )))
    vin = _normalized_vin(record.get("vin"))
    identity = " - ".join(filter(None, (
        f"Unit {record['unit_number']}" if record.get("unit_number") else "",
        f"VIN {vin}" if vin else "",
    )))
    return _safe_segment(
        " - ".join(filter(None, (vehicle, identity))),
        "Vehicle - VIN Required",
    )


def _sharepoint_folder_path(record: dict[str, Any]) -> str:
    existing = str(record.get("sharepoint_folder_path") or "").strip().strip("/")
    if existing:
        return existing
    agency = _safe_segment(record.get("agency_name"), "Agency Not Entered")
    year = str(record.get("vehicle_year") or "").strip()
    if not re.fullmatch(r"(?:19|20)\d{2}", year):
        year = _current_year()
    return f"{SHAREPOINT_ROOT}/{agency}/{year}/{_vehicle_folder_name(record)}"


def _pdf_filename(record: dict[str, Any]) -> str:
    vin = _normalized_vin(record.get("vin"))
    suffix = vin or "VIN Required"
    return f"DTM Strip Documentation - {suffix}.pdf"


def _pdf_path(paths: AppPaths, record: dict[str, Any]) -> Path:
    relative = Path(*_sharepoint_folder_path(record).split("/")) / "Documents" / _pdf_filename(record)
    target = paths.workspace_output_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _actor_name() -> str:
    try:
        user = wiring.get_active_bundle().identity.current_user()
        return str(user.display_name or "").strip() if user else ""
    except Exception:
        return ""


def _normalize_record(payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(existing or {})
    record_id = _safe_id(
        payload.get("record_id") or current.get("record_id") or str(uuid.uuid4()),
        label="Strip documentation record ID",
    )
    used_vehicle_id = _safe_id(
        payload.get("used_vehicle_id") or current.get("used_vehicle_id") or str(uuid.uuid4()),
        label="Used vehicle ID",
    )
    record: dict[str, Any] = {
        "schema_version": 1,
        "record_id": record_id,
        "used_vehicle_id": used_vehicle_id,
        "created_at": str(current.get("created_at") or payload.get("created_at") or _now()),
        "updated_at": _now(),
    }
    for field in _STRING_FIELDS:
        record[field] = str(payload.get(field, current.get(field, "")) or "").strip()[:4000]
    if record["technician_signature"]:
        record["performed_by"] = record["technician_signature"]
    if record["reviewer_signature"]:
        record["reviewed_by"] = record["reviewer_signature"]
    if record["disposition"] not in DISPOSITIONS:
        record["disposition"] = ""
    workflow_stage = str(payload.get("workflow_stage", current.get("workflow_stage", "intake")) or "intake")
    record["workflow_stage"] = workflow_stage if workflow_stage in WORKFLOW_STAGES else "intake"

    raw_checklist = payload.get("checklist", current.get("checklist", {}))
    raw_checklist = raw_checklist if isinstance(raw_checklist, dict) else {}
    checklist: dict[str, dict[str, str]] = {}
    for item_id, label in CHECKLIST_ITEMS:
        source = raw_checklist.get(item_id, {})
        source = source if isinstance(source, dict) else {}
        status = str(source.get("status") or "").strip()
        checklist[item_id] = {
            "label": label,
            "status": status if status in CHECKLIST_STATUSES else "",
            "note": str(source.get("note") or "").strip()[:500],
        }
    record["checklist"] = checklist

    record["before_photos"] = list(current.get("before_photos") or [])
    record["after_photos"] = list(current.get("after_photos") or [])
    record["photo_capture_status"] = str(current.get("photo_capture_status") or "not_started")
    record["photo_proof_captured"] = bool(
        payload.get("photo_proof_captured", current.get("photo_proof_captured", False))
    )
    required_complete = all(
        item["status"] in {"removed", "not_present"} for item in checklist.values()
    )
    technician_complete = (
        required_complete
        and record["strip_date"]
        and record["photo_proof_captured"]
        and record["performed_by"]
        and record["technician_signature"]
        and record["technician_signed_date"]
        and record["reviewed_by"]
        and record["reviewer_signature"]
        and record["reviewer_signed_date"]
    )
    intake_complete = bool(
        record["agency_name"]
        and len(_normalized_vin(record["vin"])) == 17
        and record["disposition"] in {"purchased_by_dtm", "returned_to_agency"}
    )
    if record["workflow_stage"] == "technician":
        record["form_status"] = "form_ready" if technician_complete else "technician_draft"
    else:
        record["form_status"] = "intake_complete" if intake_complete else "intake_draft"
    record["sharepoint_folder_path"] = _sharepoint_folder_path({**current, **record})
    record["sharepoint_pdf_path"] = f"{record['sharepoint_folder_path']}/Documents/{_pdf_filename(record)}"
    record["pdf_path"] = str(current.get("pdf_path") or "")
    return record


def _write_record(paths: AppPaths, record: dict[str, Any]) -> None:
    target = _record_path(paths, record["record_id"])
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def get_record(record_id: str, paths: AppPaths) -> dict[str, Any]:
    try:
        payload = json.loads(_record_path(paths, record_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        raise FileNotFoundError("Strip documentation record not found") from None
    if not isinstance(payload, dict):
        raise FileNotFoundError("Strip documentation record not found")
    return payload


def _local_records(paths: AppPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(_record_dir(paths).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                records.append(payload)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read strip documentation record %s", path.name)
    return records


def _find_record(
    paths: AppPaths,
    *,
    used_vehicle_id: str = "",
    project_id: str = "",
    individual_id: str = "",
    vehicle_sale_record_id: str = "",
    vin: str = "",
) -> dict[str, Any] | None:
    vin_key = _normalized_vin(vin)
    for record in _local_records(paths):
        if used_vehicle_id and record.get("used_vehicle_id") == used_vehicle_id:
            return record
        if vehicle_sale_record_id and record.get("vehicle_sale_record_id") == vehicle_sale_record_id:
            return record
        if (
            project_id and individual_id
            and record.get("source_project_id") == project_id
            and record.get("source_individual_id") == individual_id
        ):
            return record
        if len(vin_key) == 17 and _normalized_vin(record.get("vin")) == vin_key:
            return record
    return None


def _merge_missing(record: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    for key, value in values.items():
        if str(value or "").strip() and not str(updated.get(key) or "").strip():
            updated[key] = value
    return updated


def record_from_project(project_id: str, unit_id: str, individual_id: str, paths: AppPaths) -> dict[str, Any]:
    project = load_project(project_id, paths)
    unit = next((candidate for candidate in project.build_units if candidate.unit_id == unit_id), None)
    individual = next(
        (candidate for candidate in (unit.individuals if unit else []) if candidate.individual_id == individual_id),
        None,
    )
    if unit is None or individual is None:
        raise ValueError("Project vehicle could not be found")
    prior_used_vehicle_id = individual.source_used_vehicle_id
    used_vehicle = used_vehicle_service.ensure_for_project_vehicle(
        project, unit, individual, paths,
    )
    if used_vehicle is None:
        raise ValueError("Enter the existing vehicle details before opening strip documentation")
    if individual.source_used_vehicle_id != prior_used_vehicle_id:
        save_project(project, paths)
    values = {
        "used_vehicle_id": used_vehicle["used_vehicle_id"],
        "agency_name": used_vehicle["agency_name"],
        "vehicle_year": used_vehicle["vehicle_year"],
        "vehicle_make": used_vehicle["vehicle_make"],
        "vehicle_model": used_vehicle["vehicle_model"],
        "vehicle_color": used_vehicle["vehicle_color"],
        "unit_number": used_vehicle["unit_number"],
        "vin": used_vehicle["vin"],
        "source_project_id": project_id,
        "source_unit_id": unit_id,
        "source_individual_id": individual_id,
        "performed_by": _actor_name(),
    }
    existing = _find_record(
        paths,
        used_vehicle_id=used_vehicle["used_vehicle_id"],
        project_id=project_id,
        individual_id=individual_id,
        vin=individual.existing_vin,
    )
    return save_record(_merge_missing(existing or {}, values), paths)["record"]


def record_from_sale(record_id: str, paths: AppPaths) -> dict[str, Any]:
    sale = vehicle_sale_service.get_record(record_id, paths)
    used_vehicle = used_vehicle_service.ensure_record({
        "used_vehicle_id": sale.get("used_vehicle_id"),
        "agency_name": sale.get("purchased_from") or sale.get("project_agency"),
        "vehicle_year": sale.get("vehicle_year"),
        "vehicle_make": sale.get("vehicle_make"),
        "vehicle_model": sale.get("vehicle_model"),
        "vehicle_color": sale.get("vehicle_color"),
        "unit_number": sale.get("vehicle_unit_number"),
        "vin": sale.get("vin"),
        "purchase_status": "purchased_by_dtm",
        "strip_requirement": "required",
    }, paths)
    values = {
        "used_vehicle_id": used_vehicle["used_vehicle_id"],
        "agency_name": used_vehicle["agency_name"],
        "vehicle_year": used_vehicle["vehicle_year"],
        "vehicle_make": used_vehicle["vehicle_make"],
        "vehicle_model": used_vehicle["vehicle_model"],
        "vehicle_color": used_vehicle["vehicle_color"],
        "unit_number": used_vehicle["unit_number"],
        "vin": used_vehicle["vin"],
        "source_project_id": sale.get("project_id"),
        "source_unit_id": sale.get("unit_id"),
        "source_individual_id": sale.get("individual_id"),
        "vehicle_sale_record_id": sale.get("record_id"),
        "disposition": "purchased_by_dtm",
        "performed_by": _actor_name(),
    }
    existing = _find_record(
        paths,
        used_vehicle_id=used_vehicle["used_vehicle_id"],
        project_id=str(sale.get("project_id") or ""),
        individual_id=str(sale.get("individual_id") or ""),
        vehicle_sale_record_id=record_id,
        vin=str(sale.get("vin") or ""),
    )
    return save_record(_merge_missing(existing or {}, values), paths)["record"]


def save_record(payload: dict[str, Any], paths: AppPaths, *, publish: bool = True) -> dict[str, Any]:
    with _save_lock:
        record_id = str(payload.get("record_id") or "")
        try:
            existing = get_record(record_id, paths) if record_id else None
        except FileNotFoundError:
            existing = None
        record = _normalize_record(payload, existing=existing)
        purchase_status = {
            "purchased_by_dtm": "purchased_by_dtm",
            "returned_to_agency": "returned_to_owner",
        }.get(record.get("disposition"), "unknown")
        used_vehicle = used_vehicle_service.ensure_record({
            "used_vehicle_id": record["used_vehicle_id"],
            "agency_name": record["agency_name"],
            "vehicle_year": record["vehicle_year"],
            "vehicle_make": record["vehicle_make"],
            "vehicle_model": record["vehicle_model"],
            "vehicle_color": record["vehicle_color"],
            "unit_number": record["unit_number"],
            "vin": record["vin"],
            "purchase_status": purchase_status,
            "strip_requirement": "required",
            "strip_status": "documented" if record["form_status"] == "form_ready" else "in_progress",
        }, paths, publish=publish)
        record["used_vehicle_id"] = used_vehicle["used_vehicle_id"]
        target = _pdf_path(paths, record)
        record["pdf_path"] = str(target)
        record["sharepoint_pdf_path"] = f"{record['sharepoint_folder_path']}/Documents/{_pdf_filename(record)}"
        render_strip_documentation_pdf(record, target, paths)
        _write_record(paths, record)
    try:
        sync_started = bool(publish and wiring._cloud_flag_enabled())  # noqa: SLF001
    except Exception:
        sync_started = False
    if sync_started:
        threading.Thread(
            target=_publish_record,
            args=(record, paths),
            name=f"strip-documentation-{record['record_id'][-6:]}",
            daemon=True,
        ).start()
    return {
        "ok": True,
        "record": record,
        "pdf_path": str(target),
        "sync_started": sync_started,
        "checklist_items": [{"id": item_id, "label": label} for item_id, label in CHECKLIST_ITEMS],
        "photo_angles": [{"id": angle_id, "label": label} for angle_id, label in PHOTO_ANGLES],
    }


def _record_for_scoped_update(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    record_id = str(payload.get("record_id") or "").strip()
    if not record_id:
        raise ValueError("Open strip documentation from a project or buyback record first")
    return get_record(record_id, paths)


def save_intake_record(
    payload: dict[str, Any], paths: AppPaths, *, publish: bool = True,
) -> dict[str, Any]:
    """Save only fields owned by sales, regardless of extra client payload fields."""
    existing = _record_for_scoped_update(payload, paths)
    updated = dict(existing)
    for field in _INTAKE_EDITABLE_FIELDS:
        if field in payload:
            updated[field] = payload[field]
    return save_record(updated, paths, publish=publish)


def save_technician_record(
    payload: dict[str, Any], paths: AppPaths, *, publish: bool = True,
) -> dict[str, Any]:
    """Save only shop-owned strip evidence and attestation fields."""
    existing = _record_for_scoped_update(payload, paths)
    updated = dict(existing)
    for field in _TECHNICIAN_EDITABLE_FIELDS:
        if field in payload:
            updated[field] = payload[field]
    if "checklist" in payload:
        updated["checklist"] = payload["checklist"]
    if "photo_proof_captured" in payload:
        updated["photo_proof_captured"] = payload["photo_proof_captured"]
    updated["workflow_stage"] = "technician"
    return save_record(updated, paths, publish=publish)


def begin_technician_documentation(record_id: str, paths: AppPaths) -> dict[str, Any]:
    record = get_record(record_id, paths)
    if record.get("workflow_stage") != "technician":
        record = {
            **record,
            "workflow_stage": "technician",
            "technician_started_at": _now(),
        }
    return save_record(record, paths)


def _cloud_gateway() -> GraphDriveGateway | None:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env

        config = load_cloud_config_from_env()
        return GraphDriveGateway.from_active_cloud(
            config,
            library_names=(
                config.company_library_name,
                config.company_library_internal_name,
                config.exports_library_name,
                config.exports_library_internal_name,
            ),
        )
    except Exception:
        logger.warning("Strip Documentation SharePoint library is unavailable")
        return None


def _publish_record(record: dict[str, Any], paths: AppPaths) -> None:
    del paths
    with _publish_lock:
        gateway = _cloud_gateway()
        if gateway is None:
            return
        try:
            base = str(record["sharepoint_folder_path"])
            for folder in (
                SHAREPOINT_DATA_FOLDER,
                base,
                *(f"{base}/{name}" for name in SHAREPOINT_VEHICLE_SUBFOLDERS),
            ):
                gateway.ensure_folder(folder)
            gateway.upload_file(
                f"{SHAREPOINT_DATA_FOLDER}/{record['record_id']}.json",
                json.dumps(record, indent=2, sort_keys=True).encode("utf-8"),
            )
            pdf_path = Path(str(record.get("pdf_path") or ""))
            if pdf_path.is_file():
                gateway.upload_file(record["sharepoint_pdf_path"], pdf_path.read_bytes())
        except Exception:
            logger.exception("Could not publish strip documentation %s", record.get("record_id"))


def _rgb(value: int) -> tuple[float, float, float]:
    return tuple(((value >> shift) & 255) / 255 for shift in (16, 8, 0))


def _text(page: fitz.Page, point: tuple[float, float], value: str, *, size: float = 8.5,
          bold: bool = False, color: int = 0x111827) -> None:
    page.insert_text(point, value, fontsize=size, fontname="hebo" if bold else "helv", color=_rgb(color))


def _section(page: fitz.Page, number: str, title: str, y: float) -> float:
    page.draw_rect(fitz.Rect(36, y, 576, y + 22), color=_rgb(0x0B2948), fill=_rgb(0x0B2948), width=1)
    _text(page, (47, y + 15), number, size=9, bold=True, color=0xFFFFFF)
    _text(page, (72, y + 15), title, size=9.5, bold=True, color=0xFFFFFF)
    return y + 30


def _label(page: fitz.Page, value: str, x: float, y: float, *, size: float = 7.5) -> None:
    _text(page, (x, y), value.upper(), size=size, bold=True, color=0x334155)


def _text_widget(page: fitz.Page, record: dict[str, Any], name: str, rect: fitz.Rect,
                 *, multiline: bool = False, font_size: float = 9.5) -> None:
    widget = fitz.Widget()
    widget.field_name = name
    widget.field_label = name.replace("_", " ").title()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = rect
    widget.field_value = str(record.get(name) or "")
    widget.text_font = "Helv"
    widget.text_fontsize = font_size
    widget.text_color = _rgb(0x111827)
    widget.fill_color = _rgb(0xFFFFFF)
    widget.border_color = _rgb(0x64748B)
    widget.border_width = 0.8
    if multiline:
        widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    page.add_widget(widget)


def _signature_box(
    page: fitz.Page,
    record: dict[str, Any],
    name: str,
    rect: fitz.Rect,
    paths: AppPaths,
) -> None:
    page.draw_rect(rect, color=_rgb(0x64748B), fill=_rgb(0xFFFFFF), width=0.8)
    value = str(record.get(name) or "").strip()
    if not value:
        return
    font_path = paths.resources_dir / "fonts" / "caveat" / "Caveat-Regular.ttf"
    if font_path.is_file():
        page.insert_font(fontname="Caveat", fontfile=str(font_path))
        page.insert_textbox(
            fitz.Rect(rect.x0 + 5, rect.y0 - 1, rect.x1 - 4, rect.y1 + 2),
            value,
            fontsize=15,
            fontname="Caveat",
            color=_rgb(0x102A43),
            lineheight=1,
        )
        return
    page.insert_textbox(
        fitz.Rect(rect.x0 + 5, rect.y0 + 2, rect.x1 - 4, rect.y1),
        value,
        fontsize=10,
        fontname="tiit",
        color=_rgb(0x102A43),
        lineheight=1,
    )


def _checkbox(page: fitz.Page, name: str, checked: bool, rect: fitz.Rect) -> None:
    widget = fitz.Widget()
    widget.field_name = name
    widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    widget.rect = rect
    widget.field_value = "Yes" if checked else "Off"
    widget.border_color = _rgb(0x475569)
    widget.border_width = 0.8
    page.add_widget(widget)


def _header(page: fitz.Page, record: dict[str, Any], paths: AppPaths) -> None:
    logo_path = paths.resources_dir / "assets" / "dtm_form_logo.webp"
    if logo_path.is_file():
        with Image.open(logo_path) as logo:
            logo = logo.convert("RGBA")
            logo_bytes = io.BytesIO()
            logo.save(logo_bytes, format="PNG", optimize=True)
        page.insert_image(fitz.Rect(36, 24, 150, 68), stream=logo_bytes.getvalue(), keep_proportion=True)
    _text(page, (168, 45), "VEHICLE STRIP DOCUMENTATION", size=14, bold=True, color=0x0B2948)
    _text(page, (168, 61), "LAW ENFORCEMENT EQUIPMENT & INSIGNIA REMOVAL", size=8.3, bold=True, color=0x9A6A12)
    vin_label = _normalized_vin(record.get("vin")) or "NOT ENTERED"
    page.draw_rect(fitz.Rect(420, 29, 576, 62), color=_rgb(0xC9A348), fill=_rgb(0xFFF8E6), width=0.8)
    _text(page, (431, 43), "VIN", size=6.8, bold=True, color=0x805B12)
    _text(page, (431, 56), vin_label, size=8.6, bold=True, color=0x0B2948)
    page.draw_line((36, 78), (576, 78), color=_rgb(0x0B2948), width=2)
    _text(page, (36, 769), "DTM Fleet Service  |  Strip Documentation", size=7, bold=True, color=0x334155)
    _text(page, (527, 769), "1 / 1", size=7, bold=True, color=0x334155)


def render_strip_documentation_pdf(record: dict[str, Any], target: Path, paths: AppPaths) -> None:
    """Render the editable one-page DTM strip documentation form."""
    target.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    _header(page, record, paths)

    page.draw_rect(fitz.Rect(36, 87, 576, 122), color=_rgb(0xD6DEE8), fill=_rgb(0xF6F8FB), width=0.8)
    page.insert_textbox(
        fitz.Rect(46, 94, 566, 116),
        "This DTM record documents removal work performed on the vehicle and supports the vehicle owner's separate Minnesota DVS certificate under Minn. Stat. section 169.981. It is not the state certificate of compliance.",
        fontsize=7.4, fontname="helv", color=_rgb(0x334155), lineheight=1.12,
    )

    y = _section(page, "01", "VEHICLE IDENTITY", 132)
    _label(page, "Agency / vehicle owner", 36, y)
    _text_widget(page, record, "agency_name", fitz.Rect(36, y + 4, 576, y + 29))
    y += 35
    for label, x in (("Year", 36), ("Make", 112), ("Model", 267), ("Color", 468)):
        _label(page, label, x, y)
    _text_widget(page, record, "vehicle_year", fitz.Rect(36, y + 4, 101, y + 29))
    _text_widget(page, record, "vehicle_make", fitz.Rect(112, y + 4, 256, y + 29))
    _text_widget(page, record, "vehicle_model", fitz.Rect(267, y + 4, 457, y + 29))
    _text_widget(page, record, "vehicle_color", fitz.Rect(468, y + 4, 576, y + 29))
    y += 35
    for label, x in (("Unit number", 36), ("VIN", 194)):
        _label(page, label, x, y)
    _text_widget(page, record, "unit_number", fitz.Rect(36, y + 4, 181, y + 29))
    _text_widget(page, record, "vin", fitz.Rect(194, y + 4, 576, y + 29))

    y = _section(page, "02", "STRIP DATE & BUYBACK", y + 38)
    _label(page, "Strip date", 36, y)
    _text_widget(page, record, "strip_date", fitz.Rect(36, y + 4, 163, y + 29))
    _label(page, "Is DTM buying this vehicle?", 184, y)
    disposition = str(record.get("disposition") or "")
    for value, label, x in (
        ("purchased_by_dtm", "Yes - DTM buyback", 184),
        ("returned_to_agency", "No - returning to agency", 350),
    ):
        field_name = f"disposition_{value}"
        _checkbox(page, field_name, disposition == value, fitz.Rect(x, y + 7, x + 13, y + 20))
        _text(page, (x + 18, y + 18), label, size=8.1, color=0x111827)

    y = _section(page, "03", "EQUIPMENT & INSIGNIA REMOVAL CHECKLIST", y + 38)
    checklist_height = 168
    columns = (36, 341, 397, 461, 576)
    for x in columns:
        page.draw_line((x, y), (x, y + checklist_height), color=_rgb(0xCBD5E1), width=0.6)
    for label, x in (("ITEM", 44), ("REMOVED", 345), ("NOT PRESENT", 399), ("ATTENTION", 465)):
        _label(page, label, x, y + 11, size=6.5)
    page.draw_line((36, y + 17), (576, y + 17), color=_rgb(0x94A3B8), width=0.8)
    row_y = y + 17
    for item_id, label in CHECKLIST_ITEMS:
        item = record["checklist"][item_id]
        page.insert_textbox(
            fitz.Rect(44, row_y + 2, 333, row_y + 16), label,
            fontsize=6.8, fontname="helv", color=_rgb(0x111827), lineheight=1,
        )
        status = item["status"]
        _checkbox(page, f"{item_id}_removed", status == "removed", fitz.Rect(360, row_y + 2, 371, row_y + 13))
        _checkbox(page, f"{item_id}_not_present", status == "not_present", fitz.Rect(422, row_y + 2, 433, row_y + 13))
        _checkbox(page, f"{item_id}_needs_attention", status == "needs_attention", fitz.Rect(496, row_y + 2, 507, row_y + 13))
        page.draw_line((36, row_y + 16), (576, row_y + 16), color=_rgb(0xE2E8F0), width=0.5)
        row_y += 16.5

    y += checklist_height + 8
    _label(page, "Exceptions / removal notes", 36, y)
    _text_widget(page, record, "removal_notes", fitz.Rect(36, y + 4, 576, y + 28), font_size=8)

    y = _section(page, "04", "PHOTO PROOF & SIGNATURES", y + 37)
    _checkbox(
        page, "photo_proof_captured", bool(record.get("photo_proof_captured")),
        fitz.Rect(36, y + 2, 49, y + 15),
    )
    _text(page, (56, y + 13), "Required photo proof was captured and reviewed", size=7.8, bold=True)
    _label(page, "Photo proof reference / note", 315, y + 12, size=6.5)
    _text_widget(page, record, "photo_notes", fitz.Rect(438, y - 1, 576, y + 20), font_size=7.5)
    y += 27
    page.insert_textbox(
        fitz.Rect(36, y, 576, y + 20),
        "The technician certifies the recorded removal work is accurate. The reviewer certifies the vehicle and/or photo proof was reviewed and the removal is documented.",
        fontsize=7.2, fontname="helv", color=_rgb(0x111827), lineheight=1.08,
    )
    y += 23
    _label(page, "Technician printed name", 36, y)
    _label(page, "Reviewer printed name", 310, y)
    _text_widget(page, record, "performed_by", fitz.Rect(36, y + 4, 292, y + 25), font_size=8)
    _text_widget(page, record, "reviewed_by", fitz.Rect(310, y + 4, 576, y + 25), font_size=8)
    y += 31
    _label(page, "Technician electronic signature - type full name", 36, y, size=6.5)
    _label(page, "Date", 231, y, size=6.5)
    _label(page, "Reviewer electronic signature - type full name", 310, y, size=6.5)
    _label(page, "Date", 505, y, size=6.5)
    _signature_box(page, record, "technician_signature", fitz.Rect(36, y + 4, 220, y + 25), paths)
    _text_widget(page, record, "technician_signed_date", fitz.Rect(231, y + 4, 292, y + 25), font_size=8)
    _signature_box(page, record, "reviewer_signature", fitz.Rect(310, y + 4, 494, y + 25), paths)
    _text_widget(page, record, "reviewer_signed_date", fitz.Rect(505, y + 4, 576, y + 25), font_size=8)

    document.set_metadata({
        "title": "DTM Vehicle Strip Documentation",
        "subject": "Law enforcement equipment and insignia removal documentation",
        "author": "DTM Fleet Service",
    })
    temporary = target.with_name(target.name + ".tmp.pdf")
    document.save(str(temporary), garbage=4, deflate=True)
    document.close()
    temporary.replace(target)


def open_record_pdf(record_id: str, paths: AppPaths) -> dict[str, Any]:
    record = get_record(record_id, paths)
    target = _pdf_path(paths, record)
    render_strip_documentation_pdf(record, target, paths)
    from .export_service import open_file

    return open_file({"path": str(target)}, paths)
