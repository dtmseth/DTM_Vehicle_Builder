from __future__ import annotations

import logging
import traceback
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ...domain.supply import supply_state
from ...domain.vehicle_naming import refresh_individual_vehicle_info

_log = logging.getLogger(__name__)


def _current_user_display_name() -> str:
    """Return the signed-in M365 display name, or "" outside cloud mode.

    Used to stamp last_rendered_by / last_exported_by on build records so
    teammates can see who produced each PPTX/PDF without opening it."""
    try:
        from ..adapters import wiring
        if not wiring._cloud_flag_enabled():  # noqa: SLF001
            return ""
        bundle = wiring.get_active_bundle()
        user = bundle.identity.current_user()
        if user is None:
            return ""
        return user.display_name or user.email or ""
    except Exception:
        return ""

from ...generator import generate_build_sheet
from ...inputs.project_drafts import (
    BuildDraft,
    DraftPart,
    delete_draft,
    draft_from_project_input,
    draft_part_from_payload,
    draft_summary,
    draft_to_project_input,
    find_part_by_line_id,
    renumber_parts,
    list_drafts,
    load_draft,
    new_draft,
    save_draft,
)
from ...naming import safe_id
from ...paths import AppPaths
from .custom_part_service import list_custom_parts, remember_custom_part
from .parts_db_service import get_parts_db_service


def load_draft_for_request(
    draft_id: str,
    paths: AppPaths,
    *,
    refresh_remote: bool = False,
) -> BuildDraft:
    """Load a draft, retrieving one cloud-backed build when necessary.

    Startup sync intentionally avoids downloading the full historical draft
    archive.  Build handlers use this gateway so the selected record is
    available on a new device without treating a missing local cache as a new
    blank draft.  A refresh is used only when the user explicitly opens a
    build; edits keep their current local snapshot intact.
    """
    if refresh_remote:
        from .shared_work_service import hydrate_draft_from_cloud
        hydrate_draft_from_cloud(draft_id, paths, refresh=True)
    try:
        return load_draft(draft_id, paths.workspace_drafts_dir)
    except FileNotFoundError:
        from .shared_work_service import hydrate_draft_from_cloud
        if not hydrate_draft_from_cloud(draft_id, paths):
            raise
        return load_draft(draft_id, paths.workspace_drafts_dir)


def _finalized_edit_error(draft_id: str, paths: AppPaths) -> dict | None:
    """Block source changes until the user explicitly reopens final sign-off."""
    from .finalization_service import finalized_owner_for_draft
    owner = finalized_owner_for_draft(draft_id, paths)
    if owner is None:
        return None
    return {
        "ok": False,
        "error": "build_finalized",
        "message": "This design is finalized. Reopen it with a reason before editing.",
        "finalized_owner": owner,
    }


def _matching_single_speaker(draft: BuildDraft, part: DraftPart) -> DraftPart | None:
    """Find the one compatible speaker line that can become a pair.

    A pair is one rendered, numbered speaker line with quantity two.  Only
    merge two otherwise-identical single speakers; different SKUs, locations,
    or conditions remain independently editable lines.
    """
    if (
        part.parent_line_id
        or part.part_type != "siren_speaker"
        or part.quantity != 1
    ):
        return None
    for existing in draft.parts:
        if (
            existing.parent_line_id
            or existing.part_type != "siren_speaker"
            or existing.quantity != 1
        ):
            continue
        if (
            existing.part_number.strip().upper() == part.part_number.strip().upper()
            and existing.location.strip().upper() == part.location.strip().upper()
            and existing.manufacturer.strip().upper() == part.manufacturer.strip().upper()
            and supply_state(existing) == supply_state(part)
        ):
            return existing
    return None


def handle_list_drafts(paths: AppPaths) -> dict:
    drafts = list_drafts(paths.workspace_drafts_dir)
    return {"ok": True, "drafts": [draft_summary(d) for d in drafts]}


def handle_list_custom_parts(paths: AppPaths) -> dict:
    """Recently used custom parts, kept outside inventory and settings sync."""
    return {"ok": True, "parts": list_custom_parts(paths)}


def _custom_part_fields(body: dict) -> tuple[dict | None, str]:
    """Validate the billable fields for a one-off part before any write."""
    if not isinstance(body, dict):
        return None, "custom part must be an object"
    sku = str(body.get("sku", "")).strip()
    description = str(body.get("description", "")).strip()
    if not sku:
        return None, "SKU is required"
    if not description:
        return None, "part description is required"
    if len(sku) > 160:
        return None, "SKU must be 160 characters or fewer"
    if len(description) > 500:
        return None, "part description must be 500 characters or fewer"
    raw_price = body.get("unit_price", "")
    if raw_price is None or str(raw_price).strip() == "":
        return None, "price is required"
    try:
        price = Decimal(str(raw_price))
    except (InvalidOperation, ValueError):
        return None, "price must be a number"
    if not price.is_finite() or price < 0:
        return None, "price must be zero or greater"
    try:
        cents = price.quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, "price must be a valid currency amount"
    if price != cents:
        return None, "price must use no more than two decimal places"
    try:
        quantity = int(str(body.get("quantity", "")).strip())
    except (TypeError, ValueError):
        return None, "quantity must be a whole number"
    if quantity < 1 or quantity > 999:
        return None, "quantity must be between 1 and 999"
    return {
        "sku": sku,
        "description": description,
        "unit_price": float(cents),
        "quantity": quantity,
        "part_type": str(body.get("part_type") or "").strip(),
    }, ""


def _validated_custom_part_type(paths: AppPaths, part_type: str) -> tuple[str, str]:
    """Return a real manifest part type, or the custom fallback when omitted."""
    if not part_type or part_type == "custom_part":
        return "custom_part", ""
    if get_parts_db_service(paths).get_part_type(part_type) is None:
        return "", "unknown custom part category"
    return part_type, ""


def handle_add_custom_part_to_draft(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Append a billable non-inventory part to a draft.

    The complete pricing snapshot lives on the draft row.  The local history
    is a convenience only, never a QuickBooks inventory item or parts-db edit.
    """
    try:
        clean_id = safe_id(draft_id)
        if not clean_id or clean_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        fields, error = _custom_part_fields(body)
        if error:
            return {"ok": False, "error": error}
        assert fields is not None
        part_type, category_error = _validated_custom_part_type(paths, fields["part_type"])
        if category_error:
            return {"ok": False, "error": category_error}
        catalog_match = get_parts_db_service(paths).find_sku(fields["sku"])
        if catalog_match and not bool(body.get("allow_existing_duplicate")):
            return {
                "ok": False,
                "error": "catalog_sku_exists",
                "catalog_part": catalog_match,
            }
        draft = load_draft_for_request(draft_id, paths)
        part = draft_part_from_payload({
            "name": fields["description"],
            "new_or_used": "New",
            "manufacturer": "Custom",
            "part_number": fields["sku"],
            "quantity": fields["quantity"],
            "part_type": part_type,
            "picker_config": {
                "custom_part": {
                    "sku": fields["sku"],
                    "description": fields["description"],
                    "unit_price": fields["unit_price"],
                },
            },
        }, paths)
        draft.parts.append(part)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "custom_part_added",
            "line_id": part.line_id,
            "name": part.name,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        history_saved = True
        try:
            remember_custom_part(
                paths,
                sku=fields["sku"],
                description=fields["description"],
                unit_price=fields["unit_price"],
            )
        except Exception:
            # The actual billable draft line is already durable.  A local
            # convenience history must never make its creation look failed.
            _log.exception("Could not remember custom part %s", fields["sku"])
            history_saved = False
        return {
            "ok": True,
            "draft_id": draft_id,
            "line_id": part.line_id,
            "name": part.name,
            "history_saved": history_saved,
            "draft_summary": draft_summary(draft),
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_update_custom_part_in_draft(
    draft_id: str, line_id: str, body: dict, paths: AppPaths,
) -> dict:
    """Update one draft-local custom part without routing through the catalog picker."""
    try:
        if safe_id(draft_id) != draft_id or safe_id(line_id) != line_id:
            return {"ok": False, "error": "invalid id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        fields, error = _custom_part_fields(body)
        if error:
            return {"ok": False, "error": error}
        assert fields is not None
        part_type, category_error = _validated_custom_part_type(paths, fields["part_type"])
        if category_error:
            return {"ok": False, "error": category_error}
        catalog_match = get_parts_db_service(paths).find_sku(fields["sku"])
        if catalog_match and not bool(body.get("allow_existing_duplicate")):
            return {"ok": False, "error": "catalog_sku_exists", "catalog_part": catalog_match}
        draft = load_draft_for_request(draft_id, paths)
        found = find_part_by_line_id(draft, line_id)
        if found is None:
            return {"ok": False, "error": f"Part not found: {line_id}"}
        _idx, part = found
        if not isinstance((part.picker_config or {}).get("custom_part"), dict):
            return {"ok": False, "error": "part is not a custom part"}
        part.name = fields["description"]
        part.part_number = fields["sku"]
        part.quantity = fields["quantity"]
        part.part_type = part_type
        part.picker_config["custom_part"] = {
            "sku": fields["sku"],
            "description": fields["description"],
            "unit_price": fields["unit_price"],
        }
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "custom_part_updated", "line_id": line_id,
            "name": part.name, "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        try:
            remember_custom_part(paths, sku=fields["sku"], description=fields["description"],
                                 unit_price=fields["unit_price"])
        except Exception:
            _log.exception("Could not remember updated custom part")
        return {"ok": True, "draft_id": draft_id, "line_id": line_id,
                "name": part.name, "draft_summary": draft_summary(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_get_draft(draft_id: str, paths: AppPaths) -> dict:
    try:
        draft = load_draft_for_request(draft_id, paths, refresh_remote=True)
        from dataclasses import asdict
        return {"ok": True, "draft": asdict(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_draft(body: dict, paths: AppPaths) -> dict:
    try:
        draft_id = body.get("draft_id")
        if draft_id:
            if blocked := _finalized_edit_error(str(draft_id), paths):
                return blocked
            try:
                draft = load_draft_for_request(draft_id, paths)
            except FileNotFoundError:
                draft = new_draft()
                draft.draft_id = draft_id
        else:
            draft = new_draft()

        draft.vehicle_info = body.get("vehicle_info", draft.vehicle_info)
        draft.notes = body.get("notes", draft.notes)
        draft.placement_overrides = body.get("placement_overrides", draft.placement_overrides)
        draft.validation_messages = body.get("validation_messages", draft.validation_messages)

        if "parts" in body:
            draft.parts = [DraftPart(**p) for p in body["parts"]]

        if "audit_entry" in body:
            draft.audit_trail.append(body["audit_entry"])

        path = save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft.draft_id, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_apply_preset_to_draft(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Replace one draft's equipment and placements with a preset snapshot.

    Vehicle identity and build/project notes belong to the current unit, so a
    preset load deliberately leaves those fields untouched.  Keeping this as
    one server-side operation also prevents a partial replacement if preset
    parsing fails or the build has already been finalized.
    """
    try:
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        preset_id = str(body.get("preset_id") or "").strip()
        if not preset_id:
            return {"ok": False, "error": "preset_id required"}

        from datetime import datetime, timezone
        from .preset_service import load_preset_dict

        preset = load_preset_dict(preset_id, paths)
        raw_parts = preset.get("parts") or []
        raw_overrides = preset.get("placement_overrides") or {}
        if not isinstance(raw_parts, list):
            return {"ok": False, "error": "Preset parts must be a list"}
        if not isinstance(raw_overrides, dict):
            return {"ok": False, "error": "Preset placement overrides must be an object"}

        draft = load_draft_for_request(draft_id, paths)
        draft.parts = [draft_part_from_payload(part, paths) for part in raw_parts]
        draft.placement_overrides = dict(raw_overrides)
        draft.validation_messages = []
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "preset_loaded",
            "preset_id": preset_id,
            "preset_label": str(preset.get("label") or preset_id),
            "part_count": len(draft.parts),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {
            "ok": True,
            "draft_id": draft_id,
            "preset_id": preset_id,
            "preset_label": str(preset.get("label") or preset_id),
            "part_count": len(draft.parts),
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Preset or draft not found: {draft_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_draft(draft_id: str, paths: AppPaths) -> dict:
    try:
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        delete_draft(draft_id, paths.workspace_drafts_dir)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_override(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Merge a single placement override into draft.placement_overrides.

    Body: {"key": "{part_id}:{view}", "override": {visible, rotation, ...}}
    An empty override dict removes that key (treated as a reset).
    """
    try:
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        draft = load_draft_for_request(draft_id, paths)
        key = body.get("key", "")
        override = body.get("override", {})
        if not key:
            return {"ok": False, "error": "key required"}
        if override:
            draft.placement_overrides[key] = override
            draft.user_modified = True
        else:
            draft.placement_overrides.pop(key, None)
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "key": key}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_overrides_batch(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Save multiple placement overrides atomically.

    Body: {"overrides": {"key1": {...}, "key2": {...}}}
    Empty dict value for a key removes that override (treated as a reset).
    Sets user_modified when at least one non-empty override is written.
    """
    try:
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        draft = load_draft_for_request(draft_id, paths)
        overrides = body.get("overrides", {})
        if not isinstance(overrides, dict):
            return {"ok": False, "error": "overrides must be a dict"}
        has_real_change = False
        for key, value in overrides.items():
            if value:
                draft.placement_overrides[key] = value
                has_real_change = True
            else:
                draft.placement_overrides.pop(key, None)
        if has_real_change:
            draft.user_modified = True
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "count": len(overrides)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_CONSOLE_SETUP_CHILD_CATEGORIES = {
    "console_faceplate",
    "console_component",
    "console_wings",
}


def _console_setup_owned_part(part: DraftPart, parent_line_id: str) -> bool:
    """Whether a manifest row is generated by one console setup.

    Printers are top-level manifest parents so their power/USB cables can sit
    beneath them.  The owner marker ties that small second tree back to the
    console and lets one atomic save replace the whole generated set.
    """
    return (
        (
            part.parent_line_id == parent_line_id
            and part.accessory_category in _CONSOLE_SETUP_CHILD_CATEGORIES
        )
        or part.picker_config.get("console_setup_owner_line_id") == parent_line_id
    )


def _remove_parts_and_descendants(draft: BuildDraft, line_ids: set[str]) -> int:
    """Remove rows identified by *line_ids*, including every nested child."""
    removed_ids = set(line_ids)
    while True:
        descendants = {
            part.line_id
            for part in draft.parts
            if (
                part.parent_line_id in removed_ids
                or part.linked_parent_line_id in removed_ids
            )
        }
        new_ids = descendants - removed_ids
        if not new_ids:
            break
        removed_ids.update(new_ids)
    if not removed_ids:
        return 0
    before = len(draft.parts)
    draft.parts[:] = [part for part in draft.parts if part.line_id not in removed_ids]
    return before - len(draft.parts)


def _reuse_console_mic_clip_for_radio(radio: DraftPart) -> None:
    """Point a guided radio at the console-owned radio mic clip.

    The console owns the physical C-MCB/Mag Mic hardware when the operator
    confirms it is the same clip.  The radio kit retains its install component
    so the shop still sees a microphone instruction, but it must no longer
    describe or bill a second mount of its own.
    """
    picker_config = dict(radio.picker_config or {})
    choices = dict(picker_config.get("choices") or {})
    choices.update({
        "micClipRelation": "use_console_clip",
        "micMount": "",
        "micLoc": "",
    })
    choices.pop("micLocCustom", None)
    picker_config["choices"] = choices

    components = list(radio.components or [])
    console_component = {
        "label": "Radio microphone",
        "part_type": "radio_mic_clip",
        "location": "ON CENTER CONSOLE",
        "detail": "Uses the selected center-console mic clip",
        "quantity": 1,
    }
    replaced = False
    for index, component in enumerate(components):
        if component.get("part_type") == "radio_mic_clip":
            components[index] = console_component
            replaced = True
            break
    if not replaced:
        components.append(console_component)
    radio.components = components

    details = [
        detail for detail in (picker_config.get("details") or [])
        if isinstance(detail, dict) and detail.get("key") not in {
            "micMount", "micLoc", "micLocCustom", "micClipRelation",
        }
    ]
    details.append({
        "label": "Radio microphone mount",
        "value": "Uses the selected center-console mic clip",
        "key": "micClipRelation",
    })
    picker_config["details"] = details
    radio.picker_config = picker_config


def handle_replace_console_setup_parts(
    draft_id: str, parent_line_id: str, body: dict, paths: AppPaths,
) -> dict:
    """Atomically replace the generated manifest rows for one console setup.

    A console can yield a dozen related rows (faceplates, pedestal stack,
    dock, mic equipment, printer, and printer cables).  Saving them one HTTP
    request at a time left durable partial drafts if the app closed or cloud
    sync ran between requests.  This route makes the draft transition a
    single local write and a single cloud-mirror event.
    """
    try:
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        clean_draft_id = safe_id(draft_id)
        clean_parent_line_id = safe_id(parent_line_id)
        if not clean_draft_id or clean_draft_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        if not clean_parent_line_id or clean_parent_line_id != parent_line_id:
            return {"ok": False, "error": "invalid parent_line_id"}
        if not isinstance(body, dict):
            return {"ok": False, "error": "console setup must be an object"}

        rows = body.get("rows", [])
        printer_payload = body.get("printer")
        printer_cable_payloads = body.get("printer_cables", [])
        radio_reconciliation = body.get("radio_reconciliation")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return {"ok": False, "error": "console rows must be a list of objects"}
        if printer_payload is not None and not isinstance(printer_payload, dict):
            return {"ok": False, "error": "console printer must be an object"}
        if not isinstance(printer_cable_payloads, list) or not all(
            isinstance(row, dict) for row in printer_cable_payloads
        ):
            return {"ok": False, "error": "printer cables must be a list of objects"}
        if radio_reconciliation is not None and not isinstance(radio_reconciliation, dict):
            return {"ok": False, "error": "radio reconciliation must be an object"}
        if radio_reconciliation and not any(
            row.get("part_type") == "radio_mic_clip"
            and row.get("accessory_category") == "console_component"
            for row in rows
        ):
            return {"ok": False, "error": "radio reconciliation requires a console radio mic clip"}

        draft = load_draft_for_request(draft_id, paths)
        owner = find_part_by_line_id(draft, parent_line_id)
        if owner is None:
            return {"ok": False, "error": f"Console not found: {parent_line_id}"}

        radio_to_reconcile: DraftPart | None = None
        if radio_reconciliation:
            radio_line_id = str(radio_reconciliation.get("radio_line_id", ""))
            clean_radio_line_id = safe_id(radio_line_id)
            if not clean_radio_line_id or clean_radio_line_id != radio_line_id:
                return {"ok": False, "error": "invalid radio_line_id"}
            if radio_reconciliation.get("use_console_clip") is not True:
                return {"ok": False, "error": "radio reconciliation must use the console clip"}
            found_radio = find_part_by_line_id(draft, radio_line_id)
            if found_radio is None or found_radio[1].picker_config.get("system_type") != "radio":
                return {"ok": False, "error": f"Radio system not found: {radio_line_id}"}
            radio_to_reconcile = found_radio[1]

        generated_rows: list[DraftPart] = []
        for row in rows:
            if not row.get("name", "").strip():
                return {"ok": False, "error": "console row name is required"}
            payload = {
                **row,
                "line_id": "",
                "parent_line_id": parent_line_id,
            }
            generated_rows.append(draft_part_from_payload(payload, paths))

        printer: DraftPart | None = None
        if printer_payload is not None:
            if not printer_payload.get("name", "").strip():
                return {"ok": False, "error": "printer name is required"}
            printer = draft_part_from_payload(
                {**printer_payload, "line_id": "", "parent_line_id": ""}, paths,
            )
            generated_rows.append(printer)
            for cable in printer_cable_payloads:
                if not cable.get("name", "").strip():
                    return {"ok": False, "error": "printer cable name is required"}
                generated_rows.append(draft_part_from_payload(
                    {**cable, "line_id": "", "parent_line_id": printer.line_id}, paths,
                ))
        elif printer_cable_payloads:
            return {"ok": False, "error": "printer cables require a printer"}

        old_owner_ids = {
            part.line_id
            for part in draft.parts
            if _console_setup_owned_part(part, parent_line_id)
        }
        removed_count = _remove_parts_and_descendants(draft, old_owner_ids)
        if radio_to_reconcile is not None:
            _reuse_console_mic_clip_for_radio(radio_to_reconcile)
            removed_count += _remove_parts_and_descendants(
                draft,
                {
                    part.line_id
                    for part in draft.parts
                    if (
                        part.parent_line_id == radio_to_reconcile.line_id
                        and part.accessory_category == "magnetic_mic"
                    )
                },
            )
        draft.parts.extend(generated_rows)
        renumber_parts(draft)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "console_setup_replaced",
            "line_id": parent_line_id,
            "name": owner[1].name,
            "removed_count": removed_count,
            "added_count": len(generated_rows),
            "radio_mic_clip_reconciled": radio_to_reconcile is not None,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {
            "ok": True,
            "draft_id": draft_id,
            "parent_line_id": parent_line_id,
            "count": len(generated_rows),
            "printer_line_id": printer.line_id if printer is not None else "",
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_add_part_to_draft(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Append a new part to the draft's parts list."""
    try:
        clean_id = safe_id(draft_id)
        if not clean_id or clean_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        if not body.get("name", "").strip():
            return {"ok": False, "error": "name is required"}
        draft = load_draft_for_request(draft_id, paths)
        part = draft_part_from_payload(body, paths, require_complete_supply=True)
        matching_speaker = _matching_single_speaker(draft, part)
        if matching_speaker is not None:
            matching_speaker.quantity = 2
            draft.user_modified = True
            draft.audit_trail.append({
                "action": "part_merged",
                "line_id": matching_speaker.line_id,
                "name": matching_speaker.name,
                "at": draft.updated_at,
            })
            save_draft(draft, paths.workspace_drafts_dir)
            return {
                "ok": True,
                "draft_id": draft_id,
                "line_id": matching_speaker.line_id,
                "name": matching_speaker.name,
                "quantity": matching_speaker.quantity,
                "merged": True,
                "draft_summary": draft_summary(draft),
            }
        draft.parts.append(part)
        if not part.parent_line_id:   # accessory lines keep their parent-derived name
            renumber_parts(draft)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_added",
            "line_id": part.line_id,
            "name": part.name,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {
            "ok": True,
            "draft_id": draft_id,
            "line_id": part.line_id,
            "name": part.name,
            "draft_summary": draft_summary(draft),
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_replace_location_allocation(draft_id: str, body: dict, paths: AppPaths) -> dict:
    """Atomically replace every line in one multi-location picker batch."""
    try:
        if safe_id(draft_id) != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > 20:
            return {"ok": False, "error": "one to twenty allocated location rows are required"}
        edit_line_id = str(body.get("edit_line_id") or "").strip()
        requested_batch_id = str(body.get("batch_id") or "").strip()
        if edit_line_id and safe_id(edit_line_id) != edit_line_id:
            return {"ok": False, "error": "invalid edit_line_id"}
        batch_id = requested_batch_id or str(uuid.uuid4())
        if safe_id(batch_id) != batch_id:
            return {"ok": False, "error": "invalid batch_id"}

        prepared: list[DraftPart] = []
        for raw in rows:
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                return {"ok": False, "error": "every allocated row requires a name"}
            payload = dict(raw)
            picker_config = dict(payload.get("picker_config") or {})
            picker_config["location_batch_id"] = batch_id
            payload["picker_config"] = picker_config
            prepared.append(draft_part_from_payload(
                payload, paths, require_complete_supply=True,
            ))

        draft = load_draft_for_request(draft_id, paths)
        removed_line_ids = {
            part.line_id for part in draft.parts
            if (
                str((part.picker_config or {}).get("location_batch_id") or "") == batch_id
                or (edit_line_id and part.line_id == edit_line_id)
            )
        }
        if edit_line_id and not removed_line_ids:
            return {"ok": False, "error": f"Part not found: {edit_line_id}"}
        draft.parts = [
            part for part in draft.parts
            if part.line_id not in removed_line_ids and part.parent_line_id not in removed_line_ids
        ]
        draft.parts.extend(prepared)
        renumber_parts(draft)
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "location_allocation_replaced",
            "batch_id": batch_id,
            "removed_count": len(removed_line_ids),
            "added_count": len(prepared),
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {
            "ok": True,
            "draft_id": draft_id,
            "batch_id": batch_id,
            "line_ids": [part.line_id for part in prepared],
            "line_id": prepared[0].line_id,
            "name": prepared[0].name,
            "draft_summary": draft_summary(draft),
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_update_part_in_draft(draft_id: str, line_id: str, body: dict, paths: AppPaths) -> dict:
    """Merge updated fields onto an existing part identified by line_id."""
    try:
        clean_draft_id = safe_id(draft_id)
        if not clean_draft_id or clean_draft_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        clean_line_id = safe_id(line_id)
        if not clean_line_id or clean_line_id != line_id:
            return {"ok": False, "error": "invalid line_id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        draft = load_draft_for_request(draft_id, paths)
        result = find_part_by_line_id(draft, line_id)
        if result is None:
            return {"ok": False, "error": f"Part not found: {line_id}"}
        idx, existing = result
        # Build a merged body: existing fields, overridden by incoming body
        from dataclasses import asdict
        merged = asdict(existing)
        merged.update({k: v for k, v in body.items() if k != "line_id"})
        merged["line_id"] = line_id
        draft.parts[idx] = draft_part_from_payload(
            merged, paths, require_complete_supply=True,
        )
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_updated",
            "line_id": line_id,
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "line_id": line_id, "draft_summary": draft_summary(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_remove_part_from_draft(draft_id: str, line_id: str, paths: AppPaths) -> dict:
    """Remove the part with the given line_id from the draft."""
    try:
        clean_draft_id = safe_id(draft_id)
        if not clean_draft_id or clean_draft_id != draft_id:
            return {"ok": False, "error": "invalid draft_id"}
        clean_line_id = safe_id(line_id)
        if not clean_line_id or clean_line_id != line_id:
            return {"ok": False, "error": "invalid line_id"}
        if blocked := _finalized_edit_error(draft_id, paths):
            return blocked
        draft = load_draft_for_request(draft_id, paths)
        result = find_part_by_line_id(draft, line_id)
        if result is None:
            return {"ok": False, "error": f"Part not found: {line_id}"}
        idx, removed = result
        draft.parts.pop(idx)
        # Cascade both visual accessory children and normal manifest lines
        # whose lifecycle is tied to this part.  Walk the relationship tree so
        # deleting a bumper also clears an old channel child and any lights
        # previously nested beneath that channel.
        removed_line_ids = {line_id}
        cascaded_parts = []
        while True:
            dependents = [
                part for part in draft.parts
                if (
                    getattr(part, "parent_line_id", "") in removed_line_ids
                    or getattr(part, "linked_parent_line_id", "") in removed_line_ids
                )
            ]
            if not dependents:
                break
            for dependent in dependents:
                draft.parts.remove(dependent)
                cascaded_parts.append(dependent)
                removed_line_ids.add(dependent.line_id)
        renumber_parts(draft)   # close gaps left in numbered sequences
        draft.user_modified = True
        draft.audit_trail.append({
            "action": "part_removed",
            "line_id": line_id,
            "name": removed.name,
            "cascaded_accessories": len(cascaded_parts),
            "at": draft.updated_at,
        })
        save_draft(draft, paths.workspace_drafts_dir)
        return {"ok": True, "draft_id": draft_id, "line_id": line_id,
                "cascaded_accessories": len(cascaded_parts), "draft_summary": draft_summary(draft)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Draft not found: {draft_id}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_generate_from_draft(body: dict, paths: AppPaths) -> dict:
    import time as _time
    _t_start = _time.monotonic()
    _t_last = _t_start
    def _t_step(label: str) -> None:
        nonlocal _t_last
        now = _time.monotonic()
        _log.info("generate-from-draft %s took %.2fs (cumulative %.2fs)",
                  label, now - _t_last, now - _t_start)
        _t_last = now
    log_lines: list[str] = []
    try:
        draft_id = body.get("draft_id", "")
        draft = load_draft_for_request(draft_id, paths)
        project = draft_to_project_input(draft)
        _t_step(f"load_draft({draft_id})")
        log_lines.append(f"Draft: {draft_id}")
        log_lines.append(f"Vehicle type: {project.info.get('VehicleType', '?')}")
        log_lines.append(f"Parts: {len(project.parts)}")

        # Resolve project metadata for filename freshness and SharePoint export
        # folder layout. Local PPTX files always stay in workspace/output.
        _project_export_dir = None
        _agency = str(project.info.get("Agency", "") or "")
        _year = str(project.info.get("BuildYear", "") or "")
        _ind_year = ""
        _proj_rec = None
        _matched_unit_id = ""
        _matched_individual_id = ""
        _proj_id_param = body.get("project_id", "")
        if _proj_id_param:
            try:
                from ...inputs.project_entry import load_project
                _proj_rec = load_project(_proj_id_param, paths)
                _agency = (_proj_rec.customer.agency or "").strip() or _agency
                _year = (_proj_rec.customer.build_year or "").strip() or _year
                project.info["Agency"] = _agency
                project.info["AgencyAbbreviation"] = (
                    _proj_rec.customer.agency_abbreviation or ""
                )
                if _year:
                    project.info["BuildYear"] = _year

                # Freshen project-owned build metadata from the current project
                # so values set after draft creation are reflected in output.
                _matched_project_unit = False
                for _bu in _proj_rec.build_units:
                    for _idx, _ind in enumerate(_bu.individuals):
                        if _ind.draft_id == draft_id:
                            _matched_project_unit = True
                            _matched_unit_id = _bu.unit_id
                            _matched_individual_id = _ind.individual_id
                            _year = (_proj_rec.customer.build_year or "").strip() or _year
                            _ind_year = _year or _ind.year or ""
                            project.info = refresh_individual_vehicle_info(
                                project.info,
                                _proj_rec,
                                _bu,
                                _ind,
                                ordinal=_idx + 1,
                            )
                            break
                    if _matched_project_unit:
                        break
                    if not _bu.individuals and _bu.draft_id == draft_id:
                        _matched_project_unit = True
                        _matched_unit_id = _bu.unit_id
                        _nv = dict(project.info.get("NewVehicle") or {})
                        if _year:
                            _nv["YEAR"] = _year
                            if _bu.vehicle_model:
                                _nv["MODEL"] = f"{_year} {_bu.vehicle_model}".strip()
                        _nv["UNIT ID"] = _nv.get("UNIT ID") or "Group Build"
                        project.info["NewVehicle"] = _nv
                        project.info["BuildType"] = _bu.build_type or project.info.get("BuildType", "")
                        from ...domain.vehicle_naming import vehicle_display_name
                        project.info["CanonicalVehicleName"] = vehicle_display_name(
                            _proj_rec, _bu, None,
                        )
                        break
            except Exception:
                _log.exception("Could not resolve project metadata for draft %s", draft_id)

        # generate_build_sheet expects a Path to an xlsx — for GUI-built drafts
        # we don't have one, so we generate from the ProjectInput directly via
        # the planning + rendering pipeline.
        import json
        from ...config.loader import load_configs
        from ...planning.planner import build_plan
        from ...planning.override_applier import apply_overrides
        from ...render_ppt import render_plan_to_ppt
        from ...reporting import render_markdown_summary
        from ...storage.local import LocalStorageProvider

        config = load_configs(paths)
        _t_step("load_configs")
        plan = build_plan(project, config)
        _t_step("build_plan")

        if _proj_rec is not None and _matched_unit_id:
            from .reference_package_service import resolve_reference_package

            reference_package = resolve_reference_package(
                _proj_rec,
                unit_id=_matched_unit_id,
                individual_id=_matched_individual_id,
                paths=paths,
            )
            for missing in reference_package.errors:
                plan.warnings.append(f"Reference photo unavailable: {missing}")
            for entry in reference_package.entries:
                plan.reference_photos.append({
                    "reference_id": entry.asset.reference_id,
                    "file_name": entry.asset.file_name,
                    "published_file_name": entry.published_file_name,
                    "title": Path(entry.asset.file_name).stem,
                    "note": entry.assignment.note,
                    "sort_order": entry.assignment.sort_order,
                    "origin": entry.origin,
                    "source_relative_path": f"Build Reference Photos/{entry.published_file_name}",
                    "local_path": str(entry.local_path),
                })
            _t_step(f"resolve_reference_photos({len(plan.reference_photos)})")

        if draft.placement_overrides:
            plan = apply_overrides(plan, draft.placement_overrides)
            log_lines.append(f"Applied {len(draft.placement_overrides)} placement override(s).")

        project_id = project.info.get("ProjectID", "DRAFT")
        out_dir = paths.workspace_output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        ppt_path = render_plan_to_ppt(plan, paths)
        _t_step(f"render_plan_to_ppt({ppt_path.name})")
        plan_path = out_dir / f"BuildPlan_{project_id}.json"
        summary_path = out_dir / f"BuildSummary_{project_id}.md"

        storage = LocalStorageProvider()
        storage.write_text(str(plan_path), json.dumps(plan.to_dict(), indent=2))
        storage.write_text(str(summary_path), render_markdown_summary(plan))
        _t_step("write plan+summary")

        placements_count = sum(len(pp.placements) for pp in plan.planned_parts)
        log_lines.append(f"Wrote: {ppt_path.name}")

        all_warnings: list[str] = list(plan.warnings)
        for pp in plan.planned_parts:
            all_warnings.extend(pp.warnings)
            for pl in pp.placements:
                all_warnings.extend(pl.warnings)
                for inst in pl.instances:
                    all_warnings.extend(inst.warnings)

        from .generation_service import finalize_output
        import re as _re
        from pathlib import Path as _Path
        export = finalize_output(
            ppt_path,
            paths,
            project_export_dir=_project_export_dir,
            agency=_agency or project.info.get("Agency", ""),
            year=_year or project.info.get("BuildYear", "") or _ind_year,
            preserve_sharepoint_version=body.get("preserve_sharepoint_version") is True,
        )
        _t_step("finalize_output (keeps local conversion artifact)")

        # Detect rename: if the caller supplied the previous output path and the
        # stable filename prefix (everything before the timestamp) has changed,
        # the old file is now an orphan.  Return it so the UI can prompt the user.
        _ts_pat = _re.compile(r'_[A-Z][a-z]{2}\d+_\d{4}_\d+-\d+-\d+[AP]M$')
        _existing_path_str = body.get("existing_output_path", "")
        name_changed: dict | None = None
        if _existing_path_str and not body.get("replace_previous_exports"):
            _old = _Path(_existing_path_str)
            _new = _Path(export["output_path"])
            _old_prefix = _ts_pat.sub("", _old.stem)
            _new_prefix = _ts_pat.sub("", _new.stem)
            if _old_prefix != _new_prefix and _old.exists():
                name_changed = {
                    "old_path": str(_old),
                    "old_name": _old.name,
                    "new_path": export["output_path"],
                    "new_name": export["output_name"],
                }

        # Persist the new output_path + render timestamp into the project
        # record server-side so the UI doesn't need a follow-up
        # /api/project/save round-trip (saves ~1-2s of perceived gen time
        # and avoids a race where the UI redraws the Builds tab from a
        # stale project copy).
        last_rendered_at = ""
        last_rendered_by = _current_user_display_name()
        if _proj_id_param:
            try:
                from datetime import datetime, timezone
                from ...inputs.project_entry import load_project, save_project
                _proj = load_project(_proj_id_param, paths)
                last_rendered_at = datetime.now(timezone.utc).isoformat()
                _changed = False
                for _bu in _proj.build_units:
                    if _bu.individuals:
                        for _ind in _bu.individuals:
                            if _ind.draft_id == draft_id:
                                _ind.output_path = export["output_path"]
                                _ind.last_rendered_at = last_rendered_at
                                _ind.last_rendered_by = last_rendered_by
                                _changed = True
                                break
                    elif _bu.draft_id == draft_id:
                        _bu.output_path = export["output_path"]
                        _bu.last_rendered_at = last_rendered_at
                        _bu.last_rendered_by = last_rendered_by
                        _changed = True
                        break
                if _changed:
                    save_project(_proj, paths)
                    _t_step("save_project (record output_path)")
            except Exception:
                _log.exception("Could not update project record after generate")

        # Replacement is an explicit user choice made before generation. Only
        # clean up after the new PPTX has been written and its project record
        # saved, so a failed render can never destroy the previous exports.
        cleanup: dict | None = None
        if body.get("replace_previous_exports"):
            _old_paths = [
                str(value or "") for value in body.get("previous_export_paths", [])
                if str(value or "").strip()
            ]
            try:
                from .exports_upload_service import cleanup_previous_exports
                cleanup = cleanup_previous_exports(
                    paths,
                    agency=_agency or project.info.get("Agency", ""),
                    year=_year or project.info.get("BuildYear", "") or _ind_year,
                    filenames=_old_paths,
                    keep_filenames=[export["output_name"]],
                )
            except Exception:
                _log.exception("Could not clean up previous shared exports")
                cleanup = {"deleted_local": [], "errors": ["shared_export_delete_failed"]}

        result: dict = {
            "ok": True,
            "output_name": export["output_name"],
            "output_path": export["output_path"],
            "previous_versions": export["previous_versions"],
            "plan_path": str(plan_path),
            "summary_path": str(summary_path),
            "parts_count": len(plan.planned_parts),
            "placements_count": placements_count,
            "warnings_count": len(all_warnings),
            "all_warnings": all_warnings,
            "log": "\n".join(log_lines),
            "last_rendered_at": last_rendered_at,
            "last_rendered_by": last_rendered_by,
        }
        if name_changed:
            result["name_changed"] = name_changed
        if cleanup is not None:
            result["cleanup"] = cleanup
        return result
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
    except Exception as exc:
        log_lines.extend(["ERROR: " + str(exc), traceback.format_exc()])
        return {"ok": False, "error": str(exc), "log": "\n".join(log_lines)}
