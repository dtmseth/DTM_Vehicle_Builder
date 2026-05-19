from __future__ import annotations

from dataclasses import asdict

from ...config.store import load_config
from ...domain.project_codec import build_unit_from_dict, customer_from_dict, preferences_from_dict
from ...domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences, IndividualUnit
from ...inputs.project_dirs import ensure_project_output_dir
from ...inputs.project_drafts import DraftPart, new_draft, save_draft
from ...inputs.project_entry import (
    delete_project,
    list_projects,
    load_project,
    new_project,
    save_project,
)
from ...naming import safe_project_id
from ...paths import AppPaths
from .preset_service import load_preset


def _project_output_root(paths: AppPaths) -> str:
    """Return the configured project_output_root, or empty string if not set."""
    settings = load_config("app_settings.json", paths) or {}
    return settings.get("project_output_root", "").strip()


def _ensure_project_folder(paths: AppPaths, agency: str, build_year: str) -> None:
    """Create the per-project output folder if project_output_root is configured."""
    root = _project_output_root(paths)
    if root:
        ensure_project_output_dir(root, agency, build_year)


def handle_list_projects(paths: AppPaths) -> dict:
    projects = list_projects(paths)
    # Ensure output folders exist for all known projects (handles existing projects
    # retroactively and is a no-op when folders already exist).
    root = _project_output_root(paths)
    if root:
        for project in projects:
            try:
                ensure_project_output_dir(
                    root,
                    project.customer.agency,
                    project.customer.build_year,
                )
            except Exception:
                pass
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
        if project_id:
            try:
                project = load_project(project_id, paths)
            except FileNotFoundError:
                project = new_project(project_id=project_id)
        else:
            project = new_project()

        if "customer" in body:
            project.customer = customer_from_dict(body["customer"])

        if "preferences" in body:
            project.preferences = preferences_from_dict(body["preferences"])

        if "export_dir" in body:
            project.export_dir = str(body.get("export_dir", ""))

        if "build_units" in body:
            project.build_units = [build_unit_from_dict(u) for u in body["build_units"]]

        path = save_project(project, paths)

        # Create the per-project output folder immediately so the directory is
        # ready before generation, and so the user can see it was created.
        try:
            _ensure_project_folder(
                paths,
                project.customer.agency,
                project.customer.build_year,
            )
        except Exception:
            pass

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
        if delete_files:
            try:
                import shutil as _shutil
                from ...inputs.project_dirs import resolve_project_output_dir
                project = load_project(project_id, paths)
                root = _project_output_root(paths)
                folder = resolve_project_output_dir(
                    root,
                    project.customer.agency or "",
                    project.customer.build_year or "",
                )
                if folder and folder.exists() and folder.is_dir():
                    _shutil.rmtree(folder)
            except Exception:
                pass
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

    try:
        part_inputs = load_preset(preset_id, paths)
    except FileNotFoundError:
        try:
            part_inputs = load_preset("blank_custom", paths)
        except FileNotFoundError:
            part_inputs = []

    draft_parts = [
        DraftPart(
            name=p.name,
            include=p.include,
            new_or_used=p.new_or_used,
            source=p.source,
            manufacturer=p.manufacturer,
            part_number=p.part_number,
            location=p.location,
            raw_color=p.raw_color,
            quantity=p.quantity,
            lens=p.lens,
            notes=p.notes,
            explicit_color_profile=p.explicit_color_profile,
            driver_color=p.driver_color,
            passenger_color=p.passenger_color,
            center_color=p.center_color,
        )
        for p in part_inputs
    ]

    raw_id = project.customer.quote_number.strip() or project.project_id
    project_id_val = safe_project_id(raw_id, fallback=project.project_id)
    project_total_units = sum(u.quantity for u in project.build_units)

    vehicle_info: dict = {
        "VehicleType": unit.vehicle_model,
        "Agency": project.customer.agency,
        "QuoteNumber": project.customer.quote_number,
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
    if prefs.camera_brand:
        pref_notes.append(f"Camera brand: {prefs.camera_brand}")
    if prefs.push_bumper_brand:
        pref_notes.append(f"Push bumper brand: {prefs.push_bumper_brand}")
    if prefs.cage_brand:
        pref_notes.append(f"Cage brand: {prefs.cage_brand}")
    if prefs.slick_top:
        pref_notes.append("Slick top: Yes")
    if prefs.mixed_brands:
        pref_notes.append("Mixed brands: Yes")
    if prefs.notes:
        pref_notes.append(prefs.notes)

    notes: dict[str, list[str]] = {}
    if pref_notes:
        notes["EQUIPMENT PREFERENCES"] = pref_notes

    draft = new_draft(vehicle_info=vehicle_info, parts=draft_parts, notes=notes)
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
    try:
        part_inputs = load_preset(preset_id, paths)
    except FileNotFoundError:
        try:
            part_inputs = load_preset("blank_custom", paths)
        except FileNotFoundError:
            part_inputs = []

    draft_parts = [
        DraftPart(
            name=p.name,
            include=p.include,
            new_or_used=p.new_or_used,
            source=p.source,
            manufacturer=p.manufacturer,
            part_number=p.part_number,
            location=p.location,
            raw_color=p.raw_color,
            quantity=p.quantity,
            lens=p.lens,
            notes=p.notes,
            explicit_color_profile=p.explicit_color_profile,
            driver_color=p.driver_color,
            passenger_color=p.passenger_color,
            center_color=p.center_color,
        )
        for p in part_inputs
    ]

    raw_id = project.customer.quote_number.strip() or project.project_id
    project_id_val = safe_project_id(raw_id, fallback=project.project_id)
    project_total_units = sum(u.quantity for u in project.build_units)

    ind_idx = next(
        (i for i, x in enumerate(unit.individuals) if x.individual_id == individual_id), 0
    )
    unit_label = individual.unit_number or f"Unit-{ind_idx + 1}"
    ind_year = individual.year or project.customer.build_year or ""

    vehicle_model = individual.make or unit.vehicle_model
    if ind_year:
        vehicle_model = f"{ind_year} {vehicle_model}".strip()
    if individual.model:
        vehicle_model = f"{vehicle_model} {individual.model}".strip()

    vehicle_info: dict = {
        "VehicleType": unit.vehicle_model,
        "Agency": project.customer.agency,
        "QuoteNumber": project.customer.quote_number,
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
    if prefs.camera_brand:
        pref_notes.append(f"Camera brand: {prefs.camera_brand}")
    if prefs.push_bumper_brand:
        pref_notes.append(f"Push bumper brand: {prefs.push_bumper_brand}")
    if prefs.cage_brand:
        pref_notes.append(f"Cage brand: {prefs.cage_brand}")
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

    draft = new_draft(vehicle_info=vehicle_info, parts=draft_parts, notes=notes)
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
