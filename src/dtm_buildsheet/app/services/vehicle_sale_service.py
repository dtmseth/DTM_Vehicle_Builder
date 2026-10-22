"""Vehicle buyback / sale records and their one-page fillable PDFs.

The record is independent from Builder projects.  A project/individual link is
optional and exists only to pre-fill the used vehicle and keep the record easy
to reach from the vehicle card.  JSON is the editable source of truth; the PDF
is regenerated at one stable path after every save.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from ...inputs.project_entry import list_projects, load_project
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway


logger = logging.getLogger(__name__)

LOCAL_RECORD_FOLDER = "vehicle_buyback_sales"
SHAREPOINT_ROOT = "Vehicle Buyback Sales"
SHAREPOINT_DATA_FOLDER = f"{SHAREPOINT_ROOT}/Record Data"
_save_lock = threading.RLock()
_publish_lock = threading.RLock()
_deleted_record_ids: set[str] = set()

_STRING_FIELDS = (
    "record_year", "prepared_by", "project_agency", "project_id", "unit_id",
    "individual_id", "existing_vehicle_link", "vehicle_unit_number", "date_received", "purchased_from",
    "vehicle_year", "vehicle_make", "vehicle_model", "vehicle_color", "vin",
    "odometer", "purchase_amount", "purchase_via", "purchase_via_other",
    "quote_number", "dvs_flagged_resale_date", "title_vin_notes", "date_sold",
    "buyer_name", "dealer_license_number", "sale_amount", "order_invoice_number",
    "sale_notes",
)
_BOOL_FIELDS = ("title_signed_dtm", "mn_dvs_complete")
_PURCHASE_VIA = {"", "account_credit", "check_issued", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_year() -> str:
    return str(datetime.now().year)


def _safe_year(value: Any) -> str:
    raw = str(value or "").strip()
    return raw if re.fullmatch(r"(?:19|20)\d{2}", raw) else _current_year()


def _year_from_date(value: Any) -> str:
    raw = str(value or "").strip()
    match = re.match(r"^((?:19|20)\d{2})[-/]", raw)
    if match:
        return match.group(1)
    match = re.match(r"^\d{1,2}/\d{1,2}/((?:19|20)\d{2})$", raw)
    return match.group(1) if match else ""


def _safe_record_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", raw):
        raise ValueError("Vehicle sale record ID is invalid")
    return raw


def _normalized_vin(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _normalized_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _legacy_unit_number(value: Any) -> str:
    match = re.search(r"(?:^|·)\s*Unit\s+(.+?)\s*$", str(value or ""), re.IGNORECASE)
    return match.group(1).strip()[:120] if match else ""


def _record_dir(paths: AppPaths) -> Path:
    target = paths.workspace_dir / LOCAL_RECORD_FOLDER
    target.mkdir(parents=True, exist_ok=True)
    return target


def _record_path(paths: AppPaths, record_id: str) -> Path:
    return _record_dir(paths) / f"{_safe_record_id(record_id)}.json"


def _pdf_filename(record: dict[str, Any]) -> str:
    saved = str(record.get("pdf_filename") or "").strip()
    if saved and Path(saved).name == saved and saved.casefold().endswith(".pdf"):
        return saved
    received = re.sub(r"[^0-9]", "", str(record.get("date_received") or ""))
    date_label = received[:8] if len(received) >= 8 else datetime.now().strftime("%Y%m%d")
    suffix = str(record["record_id"]).replace("-", "")[-6:].upper()
    return f"Vehicle Buyback Sale - {date_label} - {suffix}.pdf"


def _pdf_path(paths: AppPaths, record: dict[str, Any]) -> Path:
    year = _safe_year(record.get("record_year"))
    folder = paths.workspace_output_dir / SHAREPOINT_ROOT / year
    folder.mkdir(parents=True, exist_ok=True)
    return folder / _pdf_filename(record)


def _actor_name() -> str:
    try:
        user = wiring.get_active_bundle().identity.current_user()
        return str(user.display_name or "").strip() if user else ""
    except Exception:
        return ""


def _normalize_record(payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(existing or {})
    record_id = _safe_record_id(payload.get("record_id") or current.get("record_id") or str(uuid.uuid4()))
    created_at = str(current.get("created_at") or payload.get("created_at") or _now())
    record: dict[str, Any] = {
        "schema_version": 1,
        "record_id": record_id,
        "created_at": created_at,
        "updated_at": _now(),
    }
    for name in _STRING_FIELDS:
        value = payload.get(name, current.get(name, ""))
        record[name] = str(value or "").strip()[:4000]
    if not record["vehicle_unit_number"] and record["existing_vehicle_link"]:
        record["vehicle_unit_number"] = _legacy_unit_number(record["existing_vehicle_link"])
    record["record_year"] = _year_from_date(record["date_received"]) or _safe_year(record["record_year"])
    if record["purchase_via"] not in _PURCHASE_VIA:
        record["purchase_via"] = ""
    for name in _BOOL_FIELDS:
        record[name] = bool(payload.get(name, current.get(name, False)))
    record["pdf_filename"] = _pdf_filename({**current, **record})
    record["pdf_path"] = str(current.get("pdf_path") or "")
    record["sharepoint_pdf_path"] = (
        f"{SHAREPOINT_ROOT}/{record['record_year']}/{record['pdf_filename']}"
    )
    return record


def _write_record(paths: AppPaths, record: dict[str, Any]) -> None:
    target = _record_path(paths, record["record_id"])
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def _load_local_records(paths: AppPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(_record_dir(paths).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                records.append(payload)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read vehicle sale record %s", path.name)
    return records


def _cloud_gateway() -> GraphDriveGateway | None:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return None
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return None
    try:
        from ..adapters.cloud.config import load_cloud_config_from_env

        config = load_cloud_config_from_env()
        names = (
            config.company_library_name,
            config.company_library_internal_name,
            config.exports_library_name,
            config.exports_library_internal_name,
        )
        if not any(str(name or "").strip() for name in names):
            return None
        return GraphDriveGateway.from_active_cloud(config, library_names=names)
    except Exception:
        logger.warning("Vehicle sale SharePoint library is unavailable")
        return None


def _sync_from_cloud(paths: AppPaths) -> None:
    gateway = _cloud_gateway()
    if gateway is None:
        return
    try:
        children = gateway.list_children(SHAREPOINT_DATA_FOLDER)
    except FileNotFoundError:
        return
    except Exception:
        logger.warning("Could not list shared vehicle sale records")
        return
    for item in children:
        name = str(item.get("name") or "")
        item_id = str(item.get("id") or "")
        if not name.casefold().endswith(".json") or not item_id:
            continue
        try:
            remote = json.loads(gateway.download_item(item_id).decode("utf-8"))
            if not isinstance(remote, dict):
                continue
            record_id = _safe_record_id(remote.get("record_id"))
            if record_id in _deleted_record_ids:
                continue
            local_path = _record_path(paths, record_id)
            local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else {}
            if str(local.get("updated_at") or "") >= str(remote.get("updated_at") or ""):
                continue
            normalized = _normalize_record(remote, existing=remote)
            normalized["updated_at"] = str(remote.get("updated_at") or normalized["updated_at"])
            normalized["created_at"] = str(remote.get("created_at") or normalized["created_at"])
            normalized["pdf_path"] = str(_pdf_path(paths, normalized))
            _write_record(paths, normalized)
            render_vehicle_sale_pdf(normalized, Path(normalized["pdf_path"]), paths)
        except Exception:
            logger.warning("Could not hydrate shared vehicle sale record %s", name)


def list_records(paths: AppPaths, *, sync_cloud: bool = True) -> dict[str, Any]:
    if sync_cloud:
        _sync_from_cloud(paths)
    records = _load_local_records(paths)
    for record in records:
        if not str(record.get("vehicle_unit_number") or "").strip():
            record["vehicle_unit_number"] = _legacy_unit_number(record.get("existing_vehicle_link"))
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"ok": True, "records": records, "sharepoint_root": SHAREPOINT_ROOT}


def get_record(record_id: str, paths: AppPaths) -> dict[str, Any]:
    try:
        payload = json.loads(_record_path(paths, record_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        raise FileNotFoundError("Vehicle sale record not found") from None
    if not isinstance(payload, dict):
        raise FileNotFoundError("Vehicle sale record not found")
    return payload


def find_record_for_vehicle(
    project_id: str,
    individual_id: str,
    paths: AppPaths,
    *,
    sync_cloud: bool = True,
) -> dict[str, Any] | None:
    """Return an existing linked record without creating one as a side effect."""
    if sync_cloud:
        _sync_from_cloud(paths)
    project_key = str(project_id or "").strip()
    individual_key = str(individual_id or "").strip()
    if not project_key or not individual_key:
        return None
    return next(
        (
            record for record in _load_local_records(paths)
            if record.get("project_id") == project_key
            and record.get("individual_id") == individual_key
        ),
        None,
    )


def find_build_vehicle_matches(
    *,
    vin: str,
    agency: str,
    unit_number: str,
    exclude_project_id: str,
    paths: AppPaths,
) -> dict[str, Any]:
    """Find prior build vehicles by exact VIN or exact agency/unit identity."""
    vin_key = _normalized_vin(vin)
    agency_key = _normalized_match_text(agency)
    unit_key = _normalized_match_text(unit_number)
    allow_vin = len(vin_key) >= 8
    allow_unit = bool(agency_key and unit_key)
    if not allow_vin and not allow_unit:
        return {"ok": True, "matches": []}

    matches: list[dict[str, Any]] = []
    for project in list_projects(paths):
        if project.project_id == str(exclude_project_id or "").strip():
            continue
        if str(project.project_type or "build") != "build":
            continue
        project_agency = str(project.customer.agency or "").strip()
        project_agency_key = _normalized_match_text(project_agency)
        for unit in project.build_units:
            identity = unit.vehicle_identity
            for individual in unit.individuals:
                reasons: list[str] = []
                if allow_vin and _normalized_vin(individual.vin) == vin_key:
                    reasons.append("Exact VIN")
                if (
                    allow_unit
                    and project_agency_key == agency_key
                    and _normalized_match_text(individual.unit_number) == unit_key
                ):
                    reasons.append("Agency + unit number")
                if not reasons:
                    continue
                matches.append({
                    "project_id": project.project_id,
                    "project_agency": project_agency,
                    "project_status": project.project_status,
                    "project_updated_at": project.updated_at,
                    "unit_id": unit.unit_id,
                    "individual_id": individual.individual_id,
                    "build_type": unit.build_type,
                    "vehicle_year": individual.year or identity.model_year or project.customer.build_year,
                    "vehicle_make": individual.make or identity.make,
                    "vehicle_model": individual.model or identity.model or identity.display_name,
                    "vehicle_color": individual.color,
                    "vehicle_unit_number": individual.unit_number,
                    "vin": individual.vin,
                    "match_reasons": reasons,
                })
    matches.sort(
        key=lambda item: (
            "Exact VIN" in item["match_reasons"],
            len(item["match_reasons"]),
            item["project_updated_at"],
        ),
        reverse=True,
    )
    return {"ok": True, "matches": matches[:8]}


def new_record(paths: AppPaths, *, prepared_by: str = "") -> dict[str, Any]:
    record = _normalize_record({
        "record_id": str(uuid.uuid4()),
        "record_year": _current_year(),
        "prepared_by": prepared_by or _actor_name(),
    })
    return save_record(record, paths)


def record_for_vehicle(project_id: str, unit_id: str, individual_id: str, paths: AppPaths) -> dict[str, Any]:
    existing = find_record_for_vehicle(project_id, individual_id, paths)
    project = load_project(project_id, paths)
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    individual = next(
        (item for item in (unit.individuals if unit else []) if item.individual_id == individual_id),
        None,
    )
    if unit is None or individual is None:
        raise ValueError("Existing vehicle could not be found")
    quote = next(
        (ref.quote_number for ref in individual.quote_references if ref.state == "current" and ref.quote_number),
        project.customer.quote_number,
    )
    linked_values = {
        "project_agency": project.customer.agency,
        "project_id": project_id,
        "unit_id": unit_id,
        "individual_id": individual_id,
        "vehicle_unit_number": individual.existing_unit_number,
        "purchased_from": project.customer.agency,
        "vehicle_year": individual.existing_year,
        "vehicle_make": individual.existing_make,
        "vehicle_model": individual.existing_model,
        "vehicle_color": individual.existing_color,
        "vin": individual.existing_vin,
        "quote_number": quote,
    }
    if existing is not None:
        refreshed = dict(existing)
        changed = False
        for field, value in linked_values.items():
            if value and not str(refreshed.get(field) or "").strip():
                refreshed[field] = value
                changed = True
        if not str(refreshed.get("prepared_by") or "").strip():
            actor = _actor_name()
            if actor:
                refreshed["prepared_by"] = actor
                changed = True
        return save_record(refreshed, paths)["record"] if changed else existing
    record = _normalize_record({
        "record_id": str(uuid.uuid4()),
        "record_year": _current_year(),
        "prepared_by": _actor_name(),
        **linked_values,
    })
    return save_record(record, paths)["record"]


def save_record(payload: dict[str, Any], paths: AppPaths, *, publish: bool = True) -> dict[str, Any]:
    with _save_lock:
        record_id = str(payload.get("record_id") or "")
        try:
            existing = get_record(record_id, paths) if record_id else None
        except FileNotFoundError:
            existing = None
        record = _normalize_record(payload, existing=existing)
        target = _pdf_path(paths, record)
        record["pdf_path"] = str(target)
        record["sharepoint_pdf_path"] = (
            f"{SHAREPOINT_ROOT}/{record['record_year']}/{record['pdf_filename']}"
        )
        render_vehicle_sale_pdf(record, target, paths)
        old_pdf_raw = str(existing.get("pdf_path") or "") if existing else ""
        old_pdf_path = Path(old_pdf_raw) if old_pdf_raw else None
        old_remote_path = str(existing.get("sharepoint_pdf_path") or "") if existing else ""
        if old_pdf_path and old_pdf_path != target:
            try:
                old_pdf_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove the prior local vehicle sale PDF")
        _write_record(paths, record)
    try:
        sync_started = bool(publish and wiring._cloud_flag_enabled())  # noqa: SLF001
    except Exception:
        sync_started = False
    if sync_started:
        threading.Thread(
            target=_publish_record,
            args=(record, paths, old_remote_path),
            name=f"vehicle-sale-{record['record_id'][-6:]}",
            daemon=True,
        ).start()
    return {"ok": True, "record": record, "pdf_path": str(target), "sync_started": sync_started}


def delete_record(
    record_id: str,
    confirmation: str,
    paths: AppPaths,
    *,
    publish: bool = True,
) -> dict[str, Any]:
    """Permanently remove one record and its generated PDF."""
    safe_id = _safe_record_id(record_id)
    if str(confirmation or "").strip() != "DELETE RECORD":
        raise ValueError('Type "DELETE RECORD" exactly to permanently delete this record')
    record = get_record(safe_id, paths)
    record_path = _record_path(paths, safe_id)
    pdf_path = Path(str(record.get("pdf_path") or _pdf_path(paths, record)))

    try:
        cloud_enabled = bool(publish and wiring._cloud_flag_enabled())  # noqa: SLF001
    except Exception:
        cloud_enabled = False

    with _publish_lock:
        _deleted_record_ids.add(safe_id)
        if cloud_enabled:
            gateway = _cloud_gateway()
            if gateway is None:
                _deleted_record_ids.discard(safe_id)
                return {
                    "ok": False,
                    "error": "SharePoint is unavailable, so the record was not deleted. Try again when connected.",
                }
            try:
                for remote_path in (
                    f"{SHAREPOINT_DATA_FOLDER}/{safe_id}.json",
                    str(record.get("sharepoint_pdf_path") or ""),
                ):
                    if not remote_path:
                        continue
                    item = gateway.get_item_by_path(remote_path)
                    if item and item.get("id"):
                        gateway.delete_item(str(item["id"]))
            except Exception:
                _deleted_record_ids.discard(safe_id)
                logger.exception("Could not delete vehicle sale record %s from SharePoint", safe_id)
                return {
                    "ok": False,
                    "error": "SharePoint could not delete the record. Nothing was removed locally.",
                }
        try:
            record_path.unlink(missing_ok=True)
            pdf_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.exception("Could not delete local vehicle sale record %s", safe_id)
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "record_id": safe_id, "deleted_pdf": str(pdf_path)}


def _publish_record(record: dict[str, Any], paths: AppPaths, old_remote_path: str = "") -> None:
    with _publish_lock:
        if str(record.get("record_id") or "") in _deleted_record_ids:
            return
        gateway = _cloud_gateway()
        if gateway is None:
            return
        try:
            gateway.ensure_folder(SHAREPOINT_DATA_FOLDER)
            gateway.ensure_folder(f"{SHAREPOINT_ROOT}/{record['record_year']}")
            payload = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
            gateway.upload_file(f"{SHAREPOINT_DATA_FOLDER}/{record['record_id']}.json", payload)
            pdf_path = Path(str(record.get("pdf_path") or ""))
            if pdf_path.is_file():
                gateway.upload_file(record["sharepoint_pdf_path"], pdf_path.read_bytes())
            if old_remote_path and old_remote_path != record["sharepoint_pdf_path"]:
                old_item = gateway.get_item_by_path(old_remote_path)
                if old_item and old_item.get("id"):
                    gateway.delete_item(str(old_item["id"]))
        except Exception:
            logger.exception("Could not publish vehicle sale record %s", record.get("record_id"))


def _rgb(value: int) -> tuple[float, float, float]:
    return tuple(((value >> shift) & 255) / 255 for shift in (16, 8, 0))


def _label(page: fitz.Page, text: str, x: float, y: float, *, size: float = 8.2,
           color: int = 0x000000, bold: bool = True) -> None:
    page.insert_text(
        (x, y), text, fontsize=size, fontname="hebo" if bold else "helv", color=_rgb(color),
    )


def _section(page: fitz.Page, number: str, title: str, y: float) -> float:
    # Avoid ``radius`` here. Older PyMuPDF builds interpret it differently
    # and can reject otherwise valid values while a record is first created.
    page.draw_rect(fitz.Rect(36, y, 576, y + 22), color=_rgb(0x000000), fill=_rgb(0x000000), width=1)
    page.insert_text((47, y + 15), number, fontsize=9, fontname="hebo", color=_rgb(0xFFFFFF))
    page.insert_text((72, y + 15), title, fontsize=9.5, fontname="hebo", color=_rgb(0xFFFFFF))
    return y + 30


def _text_widget(page: fitz.Page, record: dict[str, Any], name: str, rect: fitz.Rect,
                 *, multiline: bool = False) -> None:
    widget = fitz.Widget()
    widget.field_name = name
    widget.field_label = name.replace("_", " ").title()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = rect
    value = str(record.get(name) or "")
    if name in {"date_received", "dvs_flagged_resale_date", "date_sold"} and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value,
    ):
        year, month, day = value.split("-")
        value = f"{month}/{day}/{year}"
    widget.field_value = value
    widget.text_font = "Helv"
    widget.text_fontsize = 10
    widget.text_color = _rgb(0x000000)
    widget.fill_color = _rgb(0xFFFFFF)
    widget.border_color = _rgb(0x000000)
    widget.border_width = 1.2
    if multiline:
        widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    page.add_widget(widget)


def _checkbox(page: fitz.Page, record: dict[str, Any], name: str, x: float, y: float) -> None:
    widget = fitz.Widget()
    widget.field_name = name
    widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    widget.rect = fitz.Rect(x, y, x + 15, y + 15)
    widget.field_value = "Yes" if bool(record.get(name)) else "Off"
    widget.fill_color = _rgb(0xFFFFFF)
    widget.border_color = _rgb(0x000000)
    widget.border_width = 1.2
    page.add_widget(widget)


def render_vehicle_sale_pdf(record: dict[str, Any], target: Path, paths: AppPaths) -> None:
    """Render a high-contrast, fillable one-page US Letter record."""
    target.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=612, height=792)

    # Keep every element inside a half-inch printable margin. The prior header
    # touched the paper edge and could be clipped by ordinary office printers.
    logo_path = paths.resources_dir / "assets" / "dtm_form_logo.webp"
    if logo_path.is_file():
        with Image.open(logo_path) as logo:
            logo = logo.convert("RGBA")
            monochrome = Image.new("RGBA", logo.size, (0, 0, 0, 0))
            monochrome.putalpha(logo.getchannel("A"))
            logo_bytes = io.BytesIO()
            monochrome.save(logo_bytes, format="PNG", optimize=True)
        page.insert_image(
            fitz.Rect(36, 25, 150, 69), stream=logo_bytes.getvalue(), keep_proportion=True,
        )
    page.insert_text((168, 49), "VEHICLE BUYBACK / SALE", fontsize=18, fontname="hebo", color=_rgb(0x000000))
    page.insert_text((168, 65), "USED / EXISTING VEHICLE RECORD", fontsize=9, fontname="hebo", color=_rgb(0x000000))
    page.draw_line((36, 79), (576, 79), color=_rgb(0x000000), width=2)
    page.draw_rect(fitz.Rect(36, 87, 576, 104), color=_rgb(0x000000), fill=_rgb(0xFFFFFF), width=0.9)
    page.insert_text((43, 99), "Complete electronically or print and write by hand.", fontsize=8.2, fontname="helv", color=_rgb(0x000000))
    page.insert_text((488, 99), "LETTER  |  1 PAGE", fontsize=8.2, fontname="hebo", color=_rgb(0x000000))

    y = _section(page, "01", "RECORD DETAILS", 112)
    _label(page, "PREPARED BY", 36, y)
    _label(page, "DATE RECEIVED", 408, y)
    _label(page, "MM/DD/YYYY", 523, y, size=6.8, bold=False)
    _text_widget(page, record, "prepared_by", fitz.Rect(36, y + 5, 397, y + 35))
    _text_widget(page, record, "date_received", fitz.Rect(408, y + 5, 576, y + 35))

    y = _section(page, "02", "VEHICLE & PURCHASE", y + 43)
    _label(page, "PURCHASED FROM", 36, y)
    _text_widget(page, record, "purchased_from", fitz.Rect(36, y + 5, 576, y + 35))
    y += 43
    for text, x in (("YEAR", 36), ("MAKE", 121), ("MODEL", 278), ("COLOR", 480)):
        _label(page, text, x, y)
    _text_widget(page, record, "vehicle_year", fitz.Rect(36, y + 5, 109, y + 35))
    _text_widget(page, record, "vehicle_make", fitz.Rect(121, y + 5, 267, y + 35))
    _text_widget(page, record, "vehicle_model", fitz.Rect(278, y + 5, 468, y + 35))
    _text_widget(page, record, "vehicle_color", fitz.Rect(480, y + 5, 576, y + 35))
    y += 43
    _label(page, "UNIT NUMBER", 36, y)
    _label(page, "OPTIONAL", 129, y, size=6.8, bold=False)
    _label(page, "VIN", 157, y)
    _label(page, "ODOMETER / MILES", 420, y)
    _text_widget(page, record, "vehicle_unit_number", fitz.Rect(36, y + 5, 145, y + 35))
    _text_widget(page, record, "vin", fitz.Rect(157, y + 5, 408, y + 35))
    _text_widget(page, record, "odometer", fitz.Rect(420, y + 5, 576, y + 35))
    y += 43
    _label(page, "PURCHASE AMOUNT", 36, y)
    _label(page, "PURCHASED VIA", 191, y)
    _label(page, "OTHER METHOD", 445, y)
    _text_widget(page, record, "purchase_amount", fitz.Rect(36, y + 5, 178, y + 35))
    via = str(record.get("purchase_via") or "")
    for name, text, x in (
        ("purchase_account_credit", "Account credit", 191),
        ("purchase_check_issued", "Check issued", 300),
        ("purchase_other", "Other", 398),
    ):
        _checkbox(page, {name: via == name.removeprefix("purchase_")}, name, x, y + 12)
        _label(page, text, x + 20, y + 24, size=8.4, bold=False)
    _text_widget(page, record, "purchase_via_other", fitz.Rect(445, y + 5, 576, y + 35))
    y += 45
    _label(page, "INVOICE NUMBER", 36, y)
    _label(page, "REQUIRED FOR ACCOUNT CREDIT", 157, y, size=6.8, bold=False)
    _text_widget(page, record, "quote_number", fitz.Rect(36, y + 5, 266, y + 35))
    page.draw_rect(fitz.Rect(278, y + 5, 576, y + 35), color=_rgb(0x000000), fill=_rgb(0xFFFFFF), width=1.1)
    page.insert_text((288, y + 18), "ACCOUNT CREDIT", fontsize=8.2, fontname="hebo", color=_rgb(0x000000))
    page.insert_text((288, y + 30), "Enter the related invoice number before printing.", fontsize=7.8, fontname="helv", color=_rgb(0x000000))

    y = _section(page, "03", "TITLE, DTM & DVS", y + 43)
    _checkbox(page, record, "title_signed_dtm", 37, y + 9)
    _label(page, "Title signed / DTM information complete", 58, y + 21, size=8.4, bold=False)
    _checkbox(page, record, "mn_dvs_complete", 278, y + 9)
    _label(page, "MN DVS complete", 299, y + 21, size=8.4, bold=False)
    _label(page, "DVS DATE FLAGGED HELD FOR RESALE", 396, y)
    _text_widget(page, record, "dvs_flagged_resale_date", fitz.Rect(396, y + 5, 576, y + 35))
    y += 43
    _label(page, "TITLE / VIN NOTES", 36, y)
    _text_widget(page, record, "title_vin_notes", fitz.Rect(36, y + 5, 576, y + 40), multiline=True)

    y = _section(page, "04", "SALE", y + 48)
    _label(page, "DATE SOLD", 36, y)
    _label(page, "MM/DD/YYYY", 113, y, size=6.8, bold=False)
    _label(page, "BUYER NAME", 170, y)
    _label(page, "PRIVATE BUYER OR DEALER", 316, y, size=6.8, bold=False)
    _label(page, "DEALER LICENSE #", 431, y)
    _label(page, "IF APPLICABLE", 526, y, size=6.8, bold=False)
    _text_widget(page, record, "date_sold", fitz.Rect(36, y + 5, 159, y + 35))
    _text_widget(page, record, "buyer_name", fitz.Rect(170, y + 5, 420, y + 35))
    _text_widget(page, record, "dealer_license_number", fitz.Rect(431, y + 5, 576, y + 35))
    y += 43
    _label(page, "SALE AMOUNT", 36, y)
    _label(page, "ORDER / INVOICE #", 199, y)
    _label(page, "SALE NOTES", 395, y)
    _text_widget(page, record, "sale_amount", fitz.Rect(36, y + 5, 188, y + 35))
    _text_widget(page, record, "order_invoice_number", fitz.Rect(199, y + 5, 384, y + 35))
    _text_widget(page, record, "sale_notes", fitz.Rect(395, y + 5, 576, y + 35), multiline=True)

    page.draw_line((36, 744), (576, 744), color=_rgb(0x000000), width=1)
    page.insert_text((36, 758), "DTM Fleet Service  |  Vehicle Buyback / Sale", fontsize=7.2, fontname="hebo", color=_rgb(0x000000))
    page.insert_text((508, 758), "FILLABLE PDF", fontsize=7.2, fontname="hebo", color=_rgb(0x000000))
    document.set_metadata({"title": "DTM Fleet Service - Vehicle Buyback / Sale"})
    temporary = target.with_name(target.name + ".tmp.pdf")
    document.save(str(temporary), garbage=4, deflate=True)
    document.close()
    temporary.replace(target)


def open_record_pdf(record_id: str, paths: AppPaths) -> dict[str, Any]:
    record = get_record(record_id, paths)
    target = _pdf_path(paths, record)
    # Always refresh from the editable JSON so existing records immediately
    # receive the latest form design when opened after an app update.
    render_vehicle_sale_pdf(record, target, paths)
    from .export_service import open_file

    return open_file({"path": str(target)}, paths)


def _flattened_print_copy(source: Path, record_id: str) -> Path:
    """Bake form widgets into ordinary page content for reliable printing."""
    print_dir = Path(tempfile.gettempdir()) / "dtm_vehicle_sale_print"
    print_dir.mkdir(parents=True, exist_ok=True)
    target = print_dir / f"{_safe_record_id(record_id)}-{uuid.uuid4().hex[:8]}.pdf"
    document = fitz.open(source)
    try:
        document.bake(annots=True, widgets=True)
        document.save(target, garbage=4, deflate=True)
    finally:
        document.close()
    return target


def _windows_default_printer_name() -> str:
    """Return the Windows default printer without relying on file associations."""
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    get_default_printer = winspool.GetDefaultPrinterW
    get_default_printer.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_default_printer.restype = wintypes.BOOL

    required = wintypes.DWORD(0)
    get_default_printer(None, ctypes.byref(required))
    if not required.value:
        raise OSError("No default printer is configured. Open the PDF to choose a printer.")
    buffer = ctypes.create_unicode_buffer(required.value)
    if not get_default_printer(buffer, ctypes.byref(required)):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows could not read the default printer")
    return buffer.value


def _print_pdf_windows(source: Path) -> str:
    """Rasterize a PDF and print it through Windows GDI.

    ShellExecute's ``print`` verb requires an installed PDF application to own
    the file association.  Printing page images to the printer device context
    works on stock Windows even when no PDF application is registered.
    """
    import ctypes
    from ctypes import wintypes
    from PIL import ImageWin

    class DOCINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_int),
            ("lpszDocName", wintypes.LPCWSTR),
            ("lpszOutput", wintypes.LPCWSTR),
            ("lpszDatatype", wintypes.LPCWSTR),
            ("fwType", wintypes.DWORD),
        ]

    printer_name = _windows_default_printer_name()
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.CreateDCW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
    ]
    gdi32.CreateDCW.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
    gdi32.StartDocW.restype = ctypes.c_int
    gdi32.StartPage.argtypes = [wintypes.HDC]
    gdi32.StartPage.restype = ctypes.c_int
    gdi32.EndPage.argtypes = [wintypes.HDC]
    gdi32.EndPage.restype = ctypes.c_int
    gdi32.EndDoc.argtypes = [wintypes.HDC]
    gdi32.EndDoc.restype = ctypes.c_int
    gdi32.AbortDoc.argtypes = [wintypes.HDC]
    gdi32.AbortDoc.restype = ctypes.c_int

    printer_dc = gdi32.CreateDCW("WINSPOOL", printer_name, None, None)
    if not printer_dc:
        error = ctypes.get_last_error()
        raise OSError(error, f"Windows could not connect to {printer_name}")

    # HORZRES and VERTRES are the printable area's dimensions in device pixels.
    printable_width = gdi32.GetDeviceCaps(printer_dc, 8)
    printable_height = gdi32.GetDeviceCaps(printer_dc, 10)
    document_started = False
    document = None
    try:
        if printable_width <= 0 or printable_height <= 0:
            raise OSError(f"{printer_name} did not report a printable page size")
        info = DOCINFOW(
            ctypes.sizeof(DOCINFOW),
            "DTM Vehicle Buyback Sale",
            None,
            None,
            0,
        )
        if gdi32.StartDocW(printer_dc, ctypes.byref(info)) <= 0:
            error = ctypes.get_last_error()
            raise OSError(error, f"Windows could not start a print job on {printer_name}")
        document_started = True
        document = fitz.open(source)
        for page in document:
            if gdi32.StartPage(printer_dc) <= 0:
                error = ctypes.get_last_error()
                raise OSError(error, f"Windows could not start a page on {printer_name}")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            scale = min(printable_width / image.width, printable_height / image.height)
            width = max(1, round(image.width * scale))
            height = max(1, round(image.height * scale))
            left = (printable_width - width) // 2
            top = (printable_height - height) // 2
            ImageWin.Dib(image).draw(
                printer_dc,
                (left, top, left + width, top + height),
            )
            image.close()
            if gdi32.EndPage(printer_dc) <= 0:
                error = ctypes.get_last_error()
                raise OSError(error, f"Windows could not finish a page on {printer_name}")
        if gdi32.EndDoc(printer_dc) <= 0:
            error = ctypes.get_last_error()
            raise OSError(error, f"Windows could not submit the print job to {printer_name}")
        document_started = False
        return printer_name
    except Exception:
        if document_started:
            gdi32.AbortDoc(printer_dc)
        raise
    finally:
        if document is not None:
            document.close()
        gdi32.DeleteDC(printer_dc)


def print_record_pdf(record_id: str, paths: AppPaths) -> dict[str, Any]:
    """Send a flattened copy of the current PDF to the default printer."""
    record = get_record(record_id, paths)
    target = _pdf_path(paths, record)
    render_vehicle_sale_pdf(record, target, paths)
    print_target = _flattened_print_copy(target, record_id)

    if sys.platform in {"darwin", "linux"}:
        try:
            printer_check = subprocess.run(
                ["lpstat", "-d"], capture_output=True, text=True, timeout=10, check=False,
            )
            if printer_check.returncode != 0:
                return {
                    "ok": False,
                    "error": "No default printer is configured. Open the PDF to choose a printer.",
                }
            printer_text = printer_check.stdout.strip()
            printer_name = printer_text.split(":", 1)[-1].strip() or "default printer"
            submitted = subprocess.run(
                ["lp", str(print_target)], capture_output=True, text=True, timeout=15, check=False,
            )
            if submitted.returncode != 0:
                detail = submitted.stderr.strip() or "The default printer did not accept the PDF."
                return {"ok": False, "error": detail}
            return {
                "ok": True,
                "path": str(target),
                "spool_path": str(print_target),
                "printer_name": printer_name,
                "message": f"Sent to {printer_name}",
            }
        except Exception as exc:
            logger.exception("Could not print the vehicle sale PDF")
            return {"ok": False, "error": str(exc)}

    if sys.platform == "win32":
        try:
            printer_name = _print_pdf_windows(print_target)
            return {
                "ok": True,
                "path": str(target),
                "spool_path": str(print_target),
                "printer_name": printer_name,
                "message": f"Sent to {printer_name}",
            }
        except Exception as exc:
            logger.exception("Could not print the vehicle sale PDF")
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": "Direct printing is not supported on this computer."}

