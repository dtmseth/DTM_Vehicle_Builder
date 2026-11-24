"""Saved, batch-printable temporary yard vehicle tags.

The JSON batch is the editable source of truth.  The supplied PDF template is
kept unchanged in application resources; generated batch PDFs are flattened so
duplicate AcroForm field names cannot leak values between vehicle pages.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from ...inputs.project_entry import list_projects
from ...paths import AppPaths
from ..adapters import wiring
from . import used_vehicle_service, vehicle_sale_service


logger = logging.getLogger(__name__)

LOCAL_RECORD_FOLDER = "temporary_vehicle_tags"
OUTPUT_FOLDER = "Forms/Temporary Vehicle Tags"
TEMPLATE_RELATIVE_PATH = Path("forms/lot_vehicle_tag_letter_sheet_trim.pdf")
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("agency", "Agency"),
    ("vin", "VIN"),
    ("quote_number", "Quote number"),
    ("date_received", "Date received"),
)
CUPS_TAG_PRINT_OPTIONS: tuple[str, ...] = (
    "media=Letter",
    "orientation-requested=4",
    "fit-to-page",
)
# The physical yard-tag stock already supplies these holes and perforation.
# Removing the duplicate PDF guides keeps normal printer feed variation invisible.
SHEET_HOLE_GUIDE_RECTS: tuple[tuple[float, float, float, float], ...] = (
    (126.72, 28.8, 161.28, 43.2),
    (630.72, 28.8, 665.28, 43.2),
    (126.72, 388.8, 161.28, 403.2),
    (630.72, 388.8, 665.28, 403.2),
)

_save_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: Any, *, label: str) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", raw):
        raise ValueError(f"{label} is invalid")
    return raw


def _normalized_vin(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:17]


def _clean(value: Any, *, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _input_date(value: Any) -> str:
    raw = str(value or "").strip()
    for pattern in (
        "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m%d%Y",
        "%m/%d/%y", "%m-%d-%y", "%m%d%y",
    ):
        try:
            return datetime.strptime(raw, pattern).strftime("%m/%d/%y")
        except ValueError:
            pass
    return raw[:8]


def _valid_input_date(value: Any) -> bool:
    normalized = _input_date(value)
    if not re.fullmatch(r"\d{2}/\d{2}/\d{2}", normalized):
        return False
    try:
        datetime.strptime(normalized, "%m/%d/%y")
        return True
    except ValueError:
        return False


def _record_dir(paths: AppPaths) -> Path:
    target = paths.workspace_dir / LOCAL_RECORD_FOLDER
    target.mkdir(parents=True, exist_ok=True)
    return target


def _record_path(paths: AppPaths, batch_id: str) -> Path:
    return _record_dir(paths) / f"{_safe_id(batch_id, label='Temporary tag batch ID')}.json"


def _pdf_filename(batch: dict[str, Any]) -> str:
    saved = str(batch.get("pdf_filename") or "").strip()
    if saved and Path(saved).name == saved and saved.casefold().endswith(".pdf"):
        return saved
    created = str(batch.get("created_at") or _now())[:10].replace("-", "")
    suffix = str(batch["batch_id"]).replace("-", "")[-6:].upper()
    return f"Temporary Vehicle Tags - {created} - {suffix}.pdf"


def _pdf_path(paths: AppPaths, batch: dict[str, Any]) -> Path:
    year = str(batch.get("created_at") or _now())[:4]
    if not re.fullmatch(r"20\d{2}", year):
        year = str(datetime.now().year)
    target = paths.workspace_output_dir / OUTPUT_FOLDER / year / _pdf_filename(batch)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _normalize_item(payload: dict[str, Any]) -> dict[str, str]:
    item_id = _safe_id(
        payload.get("item_id") or str(uuid.uuid4()), label="Temporary tag item ID",
    )
    return {
        "item_id": item_id,
        "source_type": _clean(payload.get("source_type"), limit=40),
        "source_id": _clean(payload.get("source_id"), limit=300),
        "source_label": _clean(payload.get("source_label"), limit=200),
        "agency": _clean(payload.get("agency"), limit=200),
        "vin": _normalized_vin(payload.get("vin")),
        "quote_number": _clean(payload.get("quote_number"), limit=80),
        "date_received": _input_date(payload.get("date_received")),
        "vehicle_summary": _clean(payload.get("vehicle_summary"), limit=240),
        "unit_number": _clean(payload.get("unit_number"), limit=120),
    }


def _normalize_batch(
    payload: dict[str, Any], *, existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = dict(existing or {})
    batch_id = _safe_id(
        payload.get("batch_id") or current.get("batch_id") or str(uuid.uuid4()),
        label="Temporary tag batch ID",
    )
    created_at = str(current.get("created_at") or payload.get("created_at") or _now())
    raw_items = payload.get("items", current.get("items", []))
    if not isinstance(raw_items, list):
        raise ValueError("Temporary tag items must be a list")
    batch: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_id,
        "name": _clean(
            payload.get("name", current.get("name", "")), limit=160,
        ) or f"Temporary Tags - {created_at[:10]}",
        "created_at": created_at,
        "updated_at": _now(),
        "items": [_normalize_item(item) for item in raw_items if isinstance(item, dict)],
    }
    batch["pdf_filename"] = _pdf_filename({**current, **batch})
    batch["pdf_path"] = str(current.get("pdf_path") or "")
    return batch


def _write_record(paths: AppPaths, batch: dict[str, Any]) -> None:
    target = _record_path(paths, batch["batch_id"])
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(batch, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def _load_records(paths: AppPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(_record_dir(paths).glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                records.append(value)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read temporary tag batch %s", path.name)
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return records


def list_batches(paths: AppPaths) -> dict[str, Any]:
    return {"ok": True, "records": _load_records(paths)}


def new_batch() -> dict[str, Any]:
    return _normalize_batch({})


def get_batch(batch_id: str, paths: AppPaths) -> dict[str, Any]:
    path = _record_path(paths, batch_id)
    if not path.is_file():
        raise FileNotFoundError("Temporary tag batch was not found")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Temporary tag batch is invalid")
    return _normalize_batch(value, existing=value)


def validate_batch(batch: dict[str, Any]) -> dict[str, Any]:
    items = batch.get("items") if isinstance(batch.get("items"), list) else []
    item_warnings: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        missing = [label for field, label in REQUIRED_FIELDS if not str(item.get(field) or "").strip()]
        if item.get("vin") and len(_normalized_vin(item.get("vin"))) < 4:
            missing.append("VIN (at least four characters)")
        if item.get("date_received") and not _valid_input_date(item.get("date_received")):
            missing.append("Date received (MM/DD/YY)")
        if missing:
            item_warnings.append({
                "item_id": item.get("item_id", ""),
                "index": index,
                "label": _item_label(item, index),
                "missing_fields": missing,
            })
    return {
        "complete": bool(items) and not item_warnings,
        "empty": not items,
        "item_warnings": item_warnings,
        "warning_count": sum(len(item["missing_fields"]) for item in item_warnings),
    }


def _item_label(item: dict[str, Any], index: int) -> str:
    return (
        str(item.get("vehicle_summary") or "").strip()
        or str(item.get("agency") or "").strip()
        or f"Tag {index + 1}"
    )


def _display_date(value: Any) -> str:
    return _input_date(value)


def _template_values(item: dict[str, Any]) -> dict[str, str]:
    return {
        "agency": str(item.get("agency") or "").strip(),
        "vin_last_4": _normalized_vin(item.get("vin"))[-4:],
        "quote_number": str(item.get("quote_number") or "").strip(),
        "date_received": _display_date(item.get("date_received")),
    }


def _largest_text_layout(value: str, rect: fitz.Rect, *, max_lines: int) -> tuple[list[str], float]:
    """Choose the largest centered one- or two-line layout that fits ``rect``."""
    words = value.split()
    candidates = [[value]]
    if max_lines > 1 and len(words) > 1:
        candidates.extend([
            [" ".join(words[:split]), " ".join(words[split:])]
            for split in range(1, len(words))
        ])
    available_width = max(1.0, rect.width - 14.0)
    available_height = max(1.0, rect.height - 12.0)
    layouts: list[tuple[list[str], float, float]] = []
    for lines in candidates:
        widths = [fitz.get_text_length(line, fontname="hebo", fontsize=1) for line in lines]
        widest_at_one_point = max(widths)
        width_size = available_width / max(widest_at_one_point, 0.01)
        height_size = available_height / (len(lines) * 1.08)
        size = min(width_size, height_size)
        balance = min(widths) / max(widths) if len(widths) > 1 else 1.0
        layouts.append((lines, max(9.0, size), balance))
    single = layouts[0]
    if len(layouts) == 1:
        return single[0], single[1]
    best_wrapped = max(layouts[1:], key=lambda item: item[1] * (0.75 + 0.25 * item[2]))
    if best_wrapped[1] >= single[1] * 1.1:
        return best_wrapped[0], best_wrapped[1]
    return single[0], single[1]


def _single_line_fitted_size(
    value: str,
    rect: fitz.Rect,
    *,
    preferred_size: float,
    maximum_growth: float = 1.1,
) -> float:
    """Fit one line, allowing modest growth while always preventing clipping."""
    available_width = max(1.0, rect.width - 14.0)
    available_height = max(1.0, rect.height - 12.0)
    width_at_one_point = fitz.get_text_length(value, fontname="hebo", fontsize=1)
    width_size = available_width / max(width_at_one_point, 0.01)
    height_size = available_height / 1.08
    return max(9.0, min(width_size, height_size, preferred_size * maximum_growth))


def _draw_widget_value(page: fitz.Page, widget: fitz.Widget, value: str) -> None:
    if not value:
        return
    rect = widget.rect
    if widget.field_name == "agency":
        lines, size = _largest_text_layout(value, rect, max_lines=2)
    elif widget.field_name in {"vin_last_4", "date_received"}:
        lines = [value]
        size = _single_line_fitted_size(
            value,
            rect,
            preferred_size=float(widget.text_fontsize or 12),
        )
    else:
        lines = [value]
        base_size = float(widget.text_fontsize or 12)
        available = max(1.0, rect.width - 12.0)
        width = fitz.get_text_length(value, fontname="hebo", fontsize=base_size)
        size = base_size if width <= available else max(9.0, base_size * available / width)
    line_height = size * 1.08
    top = rect.y0 + max(0.0, (rect.height - line_height * len(lines)) / 2)
    for index, line in enumerate(lines):
        width = fitz.get_text_length(line, fontname="hebo", fontsize=size)
        x = rect.x0 + max(0.0, (rect.width - width) / 2)
        baseline = top + size + index * line_height
        page.insert_text((x, baseline), line, fontsize=size, fontname="hebo", color=(0, 0, 0))


def _remove_redundant_sheet_guides(page: fitz.Page) -> None:
    """Hide guides already supplied by the pre-punched and perforated stock."""
    white = (1.0, 1.0, 1.0)
    for coords in SHEET_HOLE_GUIDE_RECTS:
        old_rect = fitz.Rect(coords)
        page.draw_rect(
            fitz.Rect(old_rect.x0 - 2, old_rect.y0 - 2, old_rect.x1 + 2, old_rect.y1 + 2),
            color=None,
            fill=white,
            overlay=True,
        )

    page.draw_rect(
        fitz.Rect(10.0, 427.0, 782.0, 437.0),
        color=None,
        fill=white,
        overlay=True,
    )


def render_batch_pdf(batch: dict[str, Any], target: Path, paths: AppPaths) -> None:
    template = paths.resources_dir / TEMPLATE_RELATIVE_PATH
    if not template.is_file():
        raise FileNotFoundError("Temporary vehicle tag PDF template is missing")
    items = batch.get("items") if isinstance(batch.get("items"), list) else []
    if not items:
        raise ValueError("Add at least one vehicle before creating a tag PDF")

    output = fitz.open()
    source = fitz.open(template)
    try:
        template_page = source[0]
        widgets = list(template_page.widgets() or [])
        found = {widget.field_name for widget in widgets}
        expected = {"agency", "vin_last_4", "quote_number", "date_received"}
        missing = expected - found
        if missing:
            raise ValueError(
                f"Temporary tag template fields are missing: {', '.join(sorted(missing))}"
            )
        for item in items:
            values = _template_values(item)
            output.insert_pdf(source, from_page=0, to_page=0, annots=False, widgets=False)
            page = output[-1]
            _remove_redundant_sheet_guides(page)
            for widget in widgets:
                if widget.field_name in values:
                    _draw_widget_value(page, widget, values[widget.field_name])
        output.set_metadata({
            "title": str(batch.get("name") or "Temporary Vehicle Tags"),
            "subject": "DTM temporary yard vehicle tags",
            "author": "DTM Fleet Service",
        })
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp.pdf")
        output.save(temporary, garbage=4, deflate=True)
        temporary.replace(target)
    finally:
        source.close()
        output.close()

    check = fitz.open(target)
    try:
        if check.page_count != len(items):
            raise ValueError("Temporary tag PDF page count did not match the saved batch")
        if any(list(page.widgets() or []) for page in check):
            raise ValueError("Temporary tag batch PDF was not flattened correctly")
    finally:
        check.close()


def save_batch(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    requested_id = str(payload.get("batch_id") or "").strip()
    existing = None
    if requested_id:
        path = _record_path(paths, requested_id)
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            existing = value if isinstance(value, dict) else None
    with _save_lock:
        batch = _normalize_batch(payload, existing=existing)
        target = _pdf_path(paths, batch)
        batch["pdf_path"] = str(target)
        render_batch_pdf(batch, target, paths)
        _write_record(paths, batch)
    return {"ok": True, "record": batch, "validation": validate_batch(batch)}


def _require_print_confirmation(batch: dict[str, Any], allow_incomplete: bool) -> dict[str, Any]:
    validation = validate_batch(batch)
    if validation["empty"]:
        raise ValueError("Add at least one vehicle before creating tags")
    if not validation["complete"] and not allow_incomplete:
        raise ValueError("Some temporary tags are missing data; confirm before continuing")
    return validation


def open_batch_pdf(
    batch_id: str, paths: AppPaths, *, allow_incomplete: bool = False,
) -> dict[str, Any]:
    batch = get_batch(batch_id, paths)
    validation = _require_print_confirmation(batch, allow_incomplete)
    target = _pdf_path(paths, batch)
    render_batch_pdf(batch, target, paths)
    from .export_service import open_file

    result = open_file({"path": str(target)}, paths)
    return {**result, "validation": validation}


def print_batch_pdf(
    batch_id: str, paths: AppPaths, *, allow_incomplete: bool = False,
) -> dict[str, Any]:
    batch = get_batch(batch_id, paths)
    validation = _require_print_confirmation(batch, allow_incomplete)
    target = _pdf_path(paths, batch)
    render_batch_pdf(batch, target, paths)

    if sys.platform in {"darwin", "linux"}:
        try:
            printer_check = subprocess.run(
                ["lpstat", "-d"], capture_output=True, text=True, timeout=10, check=False,
            )
            if printer_check.returncode != 0:
                return {
                    "ok": False,
                    "error": "No default printer is configured. Open the PDF to choose a printer.",
                    "validation": validation,
                }
            printer_name = printer_check.stdout.strip().split(":", 1)[-1].strip() or "default printer"
            print_command = ["lp"]
            for option in CUPS_TAG_PRINT_OPTIONS:
                print_command.extend(["-o", option])
            print_command.append(str(target))
            submitted = subprocess.run(
                print_command, capture_output=True, text=True, timeout=20, check=False,
            )
            if submitted.returncode != 0:
                return {
                    "ok": False,
                    "error": submitted.stderr.strip() or "The default printer did not accept the PDF.",
                    "validation": validation,
                }
            return {
                "ok": True,
                "path": str(target),
                "printer_name": printer_name,
                "message": f"Sent {len(batch['items'])} tag sheet(s) to {printer_name}",
                "validation": validation,
            }
        except Exception as exc:
            logger.exception("Could not print temporary vehicle tags")
            return {"ok": False, "error": str(exc), "validation": validation}

    if sys.platform == "win32":
        try:
            printer_name = vehicle_sale_service._print_pdf_windows(target)  # noqa: SLF001
            return {
                "ok": True,
                "path": str(target),
                "printer_name": printer_name,
                "message": f"Sent {len(batch['items'])} tag sheet(s) to {printer_name}",
                "validation": validation,
            }
        except Exception as exc:
            logger.exception("Could not print temporary vehicle tags")
            return {"ok": False, "error": str(exc), "validation": validation}

    return {
        "ok": False,
        "error": "Direct printing is unavailable on this platform. Open the PDF to print it.",
        "validation": validation,
    }


def _quote_number(project, individual) -> str:
    for reference in getattr(individual, "quote_references", []) or []:
        if str(getattr(reference, "state", "current") or "current") == "current":
            value = str(getattr(reference, "quote_number", "") or "").strip()
            if value:
                return value
    direct = str(getattr(project.customer, "quote_number", "") or "").strip()
    if direct:
        return direct
    return next((str(value).strip() for value in project.quote_numbers if str(value).strip()), "")


def _operations_received_dates() -> dict[tuple[str, str], str]:
    try:
        repository = wiring.get_active_bundle().operations
        if repository is None:
            return {}
        return {
            (str(record.project_id), str(record.vehicle_id)): str(record.vehicle_at_dtm_date or "")[:10]
            for record in repository.list_vehicles()
            if str(record.vehicle_at_dtm_date or "").strip()
        }
    except Exception:
        logger.info("Operations receiving dates are unavailable for temporary tags")
        return {}


def _vehicle_summary(*values: Any) -> str:
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def list_vehicle_candidates(paths: AppPaths) -> dict[str, Any]:
    received_dates = _operations_received_dates()
    candidates: list[dict[str, str]] = []
    for project in list_projects(paths):
        for unit in project.build_units:
            for individual in unit.individuals:
                candidates.append({
                    "source_type": "project",
                    "source_id": f"{project.project_id}|{unit.unit_id}|{individual.individual_id}",
                    "source_label": "Builder project",
                    "agency": str(project.customer.agency or "").strip(),
                    "vin": _normalized_vin(individual.vin),
                    "quote_number": _quote_number(project, individual),
                    "date_received": received_dates.get(
                        (project.project_id, individual.individual_id), "",
                    ),
                    "vehicle_summary": _vehicle_summary(
                        individual.year, individual.make,
                        individual.model or unit.vehicle_model,
                    ),
                    "unit_number": str(individual.unit_number or "").strip(),
                    "project_status": str(project.project_status or "active"),
                })

    for record in vehicle_sale_service.list_records(paths, sync_cloud=False)["records"]:
        candidates.append({
            "source_type": "buyback",
            "source_id": str(record.get("record_id") or ""),
            "source_label": "Buyback / sale record",
            "agency": str(record.get("purchased_from") or record.get("project_agency") or "").strip(),
            "vin": _normalized_vin(record.get("vin")),
            "quote_number": str(record.get("quote_number") or "").strip(),
            "date_received": _input_date(record.get("date_received")),
            "vehicle_summary": _vehicle_summary(
                record.get("vehicle_year"), record.get("vehicle_make"), record.get("vehicle_model"),
            ),
            "unit_number": str(record.get("vehicle_unit_number") or "").strip(),
            "project_status": "",
        })

    for record in used_vehicle_service.list_records(paths, sync_cloud=False)["records"]:
        candidates.append({
            "source_type": "used_vehicle",
            "source_id": str(record.get("used_vehicle_id") or ""),
            "source_label": "Used vehicle record",
            "agency": str(record.get("agency_name") or "").strip(),
            "vin": _normalized_vin(record.get("vin")),
            "quote_number": "",
            "date_received": "",
            "vehicle_summary": _vehicle_summary(
                record.get("vehicle_year"), record.get("vehicle_make"), record.get("vehicle_model"),
            ),
            "unit_number": str(record.get("unit_number") or "").strip(),
            "project_status": "",
        })

    merged: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        vin = _normalized_vin(candidate.get("vin"))
        key = f"vin:{vin}" if len(vin) == 17 else f"{candidate['source_type']}:{candidate['source_id']}"
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        for field in ("agency", "vin", "quote_number", "date_received", "vehicle_summary", "unit_number"):
            if not existing.get(field) and candidate.get(field):
                existing[field] = candidate[field]
        labels = [part.strip() for part in existing["source_label"].split(" + ") if part.strip()]
        if candidate["source_label"] not in labels:
            labels.append(candidate["source_label"])
            existing["source_label"] = " + ".join(labels)

    records = list(merged.values())
    records.sort(key=lambda item: (
        str(item.get("agency") or "").casefold(),
        str(item.get("vehicle_summary") or "").casefold(),
        str(item.get("unit_number") or "").casefold(),
        str(item.get("vin") or ""),
    ))
    return {"ok": True, "records": records}
