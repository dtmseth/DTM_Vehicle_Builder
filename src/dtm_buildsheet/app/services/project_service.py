from __future__ import annotations

import logging
from dataclasses import asdict

_log = logging.getLogger(__name__)

from ...domain.project_codec import build_unit_from_dict, customer_from_dict, preferences_from_dict
from ...domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences, IndividualUnit
from ...inputs.project_drafts import DraftPart, draft_part_from_payload, new_draft, save_draft
from ...inputs.project_entry import (
    delete_project,
    list_projects,
    load_project,
    new_project,
    save_project,
)
from ...naming import safe_project_id
from ...paths import AppPaths
from .draft_service import load_draft_for_request
from .preset_service import load_preset_dict


def _load_preset_draft_parts(preset_id: str, paths: AppPaths) -> tuple[list[DraftPart], dict]:
    """Load a preset without dropping picker, renderer, or SKU metadata."""
    try:
        preset = load_preset_dict(preset_id, paths)
    except FileNotFoundError:
        preset = load_preset_dict("blank_custom", paths)
    parts = [draft_part_from_payload(raw, paths) for raw in preset.get("parts") or []]
    overrides = preset.get("placement_overrides")
    return parts, dict(overrides) if isinstance(overrides, dict) else {}


def _project_output_root(paths: AppPaths) -> str:
    """Legacy compatibility hook; project output folders are no longer user-configured."""
    return ""


def _ensure_project_folder(paths: AppPaths, agency: str, build_year: str) -> None:
    """Legacy no-op; generated files stay in the app workspace output folder."""
    return None


def handle_list_projects(paths: AppPaths) -> dict:
    projects = list_projects(paths)
    return {"ok": True, "projects": [asdict(p) for p in projects]}


def handle_get_project(project_id: str, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
        return {"ok": True, "project": asdict(project)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_project(body: dict, paths: AppPaths) -> dict:
    try:
        project_id = body.get("project_id") or None
        is_new_project = not project_id
        if project_id:
            try:
                project = load_project(project_id, paths)
            except FileNotFoundError:
                project = new_project(project_id=project_id)
                is_new_project = True
        else:
            project = new_project()

        if "customer" in body:
            project.customer = customer_from_dict(body["customer"])
            # The search box permits free typing. If the user types the exact
            # name of one saved agency without clicking its suggestion, repair
            # the missing ID here so QuickBooks/customer-profile workflows do
            # not lose the otherwise valid association.
            if project.customer.agency and not project.customer.agency_id:
                from .agency_service import load_agencies
                wanted = project.customer.agency.strip().casefold()
                matches = [a for a in load_agencies(paths) if a.name.strip().casefold() == wanted]
                if len(matches) == 1:
                    project.customer.agency_id = matches[0].agency_id

        # Agency defaults are copied only as a project is first created.  This
        # deliberately avoids retroactively changing existing projects when an
        # agency updates its normal equipment choices.
        if is_new_project and project.customer.agency_id:
            from .agency_service import get_agency
            agency = get_agency(paths, project.customer.agency_id)
            if agency is not None:
                project.preferences = preferences_from_dict(asdict(agency.default_preferences))

        if "preferences" in body:
            project.preferences = preferences_from_dict(body["preferences"])

        if "build_units" in body:
            project.build_units = [build_unit_from_dict(u) for u in body["build_units"]]

        if "project_notes" in body:
            project.project_notes = str(body.get("project_notes") or "").strip()

        path = save_project(project, paths)

        # Existing drafts need the new shared instruction immediately too.  We
        # keep it as a separate draft field so a project edit never overwrites
        # build-specific final-page notes.
        draft_ids = {
            draft_id
            for unit in project.build_units
            for draft_id in [unit.draft_id, *(ind.draft_id for ind in unit.individuals)]
            if draft_id
        }
        for draft_id in draft_ids:
            try:
                draft = load_draft_for_request(draft_id, paths)
                if draft.project_notes != project.project_notes:
                    draft.project_notes = project.project_notes
                    save_draft(draft, paths.workspace_drafts_dir)
            except FileNotFoundError:
                # A draft can be cleared/recreated while its project record is
                # being edited. The fresh draft receives this value below.
                continue

        # Create the per-project output folder immediately so the directory is
        # ready before generation, and so the user can see it was created.
        try:
            _ensure_project_folder(
                paths,
                project.customer.agency,
                project.customer.build_year,
            )
        except Exception:
            _log.exception("Failed to create output folder for project %s", project.project_id)

        return {"ok": True, "project_id": project.project_id, "path": str(path)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_project(project_id: str, paths: AppPaths) -> dict:
    try:
        delete_project(project_id, paths)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_project_with_options(project_id: str, body: dict, paths: AppPaths) -> dict:
    """POST /api/project/{id}/delete — optionally also remove the output folder."""
    delete_files = bool(body.get("delete_files", False))
    try:
        delete_project(project_id, paths)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_create_draft(project_id: str, unit_id: str, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    unit = next((u for u in project.build_units if u.unit_id == unit_id), None)
    if unit is None:
        return {"ok": False, "error": f"Build unit not found: {unit_id}"}

    preset_id = unit.preset_id.strip() if unit.preset_id else ""
    if not preset_id:
        preset_id = "blank_custom"

    draft_parts, preset_overrides = _load_preset_draft_parts(preset_id, paths)

    # A project can contain multiple vehicle estimates, so its generated build
    # sheets must not inherit a single blanket quote number as their identity.
    project_id_val = safe_project_id(project.project_id, fallback="PROJECT")
    project_total_units = sum(u.quantity for u in project.build_units)

    vehicle_info: dict = {
        "VehicleType": unit.vehicle_model,
        "Agency": project.customer.agency,
        "BuildYear": project.customer.build_year,
        "SalesRep": project.customer.sales_rep,
        "ProjectID": project_id_val,
        "BuildType": unit.build_type,
        "project_total_units": project_total_units,
        "NewVehicle": {
            "MODEL": unit.vehicle_model,
            "UNIT ID": "Group Build",
            "YEAR": project.customer.build_year or "",
        },
        "ExistingVehicle": {},
    }

    prefs = project.preferences
    pref_notes: list[str] = []
    if prefs.lighting_brands:
        pref_notes.append("Lighting brands: " + ", ".join(prefs.lighting_brands))
    pref_notes.append(f"Default lightheads: {str(prefs.lighting_mode or 'duo').upper()}")
    if prefs.camera_brand:
        pref_notes.append(f"Camera brand: {prefs.camera_brand}")
    if prefs.push_bumper_brand:
        pref_notes.append(f"Push bumper brand: {prefs.push_bumper_brand}")
    if prefs.cage_brand:
        pref_notes.append(f"Cage brand: {prefs.cage_brand}")
    if prefs.console_brand:
        pref_notes.append(f"Console brand: {prefs.console_brand}")
    if prefs.slick_top:
        pref_notes.append("Slick top: Yes")
    if prefs.mixed_brands:
        pref_notes.append("Mixed brands: Yes")
    if prefs.notes:
        pref_notes.append(prefs.notes)

    notes: dict[str, list[str]] = {}
    if pref_notes:
        notes["EQUIPMENT PREFERENCES"] = pref_notes

    draft = new_draft(
        vehicle_info=vehicle_info,
        parts=draft_parts,
        notes=notes,
        project_notes=project.project_notes,
    )
    draft.placement_overrides = preset_overrides
    save_draft(draft, paths.workspace_drafts_dir)

    unit.draft_id = draft.draft_id
    save_project(project, paths)

    return {
        "ok": True,
        "draft_id": draft.draft_id,
        "project_id": project_id,
        "unit_id": unit_id,
    }


def handle_create_individual_draft(
    project_id: str, unit_id: str, individual_id: str, paths: AppPaths
) -> dict:
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    unit = next((u for u in project.build_units if u.unit_id == unit_id), None)
    if unit is None:
        return {"ok": False, "error": f"Build unit not found: {unit_id}"}

    individual = next((i for i in unit.individuals if i.individual_id == individual_id), None)
    if individual is None:
        return {"ok": False, "error": f"Individual unit not found: {individual_id}"}

    preset_id = unit.preset_id.strip() if unit.preset_id else "blank_custom"
    draft_parts, preset_overrides = _load_preset_draft_parts(preset_id, paths)

    project_id_val = safe_project_id(project.project_id, fallback="PROJECT")
    project_total_units = sum(u.quantity for u in project.build_units)

    ind_idx = next(
        (i for i, x in enumerate(unit.individuals) if x.individual_id == individual_id), 0
    )
    unit_label = individual.unit_number or f"Unit-{ind_idx + 1}"
    # The project build year is the canonical year for generated build sheets.
    # IndividualUnit.year is retained as legacy vehicle metadata/fallback, but
    # must not make an older vehicle year leak into a newly tagged project.
    ind_year = (project.customer.build_year or "").strip() or individual.year or ""

    vehicle_model = individual.make or unit.vehicle_model
    if ind_year:
        vehicle_model = f"{ind_year} {vehicle_model}".strip()
    if individual.model:
        vehicle_model = f"{vehicle_model} {individual.model}".strip()

    vehicle_info: dict = {
        "VehicleType": unit.vehicle_model,
        "Agency": project.customer.agency,
        "BuildYear": project.customer.build_year,
        "SalesRep": project.customer.sales_rep,
        "ProjectID": project_id_val,
        "BuildType": unit.build_type,
        "project_total_units": project_total_units,
        "NewVehicle": {
            "MODEL": vehicle_model or unit.vehicle_model,
            "UNIT ID": unit_label,
            "YEAR": ind_year,
            "COLOR": individual.color,
            "VIN": individual.vin,
        },
        "ExistingVehicle": {
            "UNIT ID": individual.existing_unit_number,
            "VIN": individual.existing_vin,
        },
    }

    prefs = project.preferences
    pref_notes: list[str] = []
    if prefs.lighting_brands:
        pref_notes.append("Lighting brands: " + ", ".join(prefs.lighting_brands))
    pref_notes.append(f"Default lightheads: {str(prefs.lighting_mode or 'duo').upper()}")
    if prefs.camera_brand:
        pref_notes.append(f"Camera brand: {prefs.camera_brand}")
    if prefs.push_bumper_brand:
        pref_notes.append(f"Push bumper brand: {prefs.push_bumper_brand}")
    if prefs.cage_brand:
        pref_notes.append(f"Cage brand: {prefs.cage_brand}")
    if prefs.console_brand:
        pref_notes.append(f"Console brand: {prefs.console_brand}")
    if prefs.slick_top:
        pref_notes.append("Slick top: Yes")
    if prefs.mixed_brands:
        pref_notes.append("Mixed brands: Yes")
    if prefs.notes:
        pref_notes.append(prefs.notes)
    if individual.notes:
        pref_notes.append(f"Unit notes: {individual.notes}")

    notes: dict[str, list[str]] = {}
    if pref_notes:
        notes["EQUIPMENT PREFERENCES"] = pref_notes

    draft = new_draft(
        vehicle_info=vehicle_info,
        parts=draft_parts,
        notes=notes,
        project_notes=project.project_notes,
    )
    draft.placement_overrides = preset_overrides
    save_draft(draft, paths.workspace_drafts_dir)

    individual.draft_id = draft.draft_id
    save_project(project, paths)

    return {
        "ok": True,
        "draft_id": draft.draft_id,
        "project_id": project_id,
        "unit_id": unit_id,
        "individual_id": individual_id,
    }
