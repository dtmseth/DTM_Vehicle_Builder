from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

from ...domain.project_codec import build_unit_from_dict, customer_from_dict, preferences_from_dict
from ...config.loader import resolve_vehicle_type
from ...config.store import load_bundled_config, load_config
from ...domain.project_models import BuildUnit, CustomerInfo, EquipmentPreferences
from ...domain.vehicle_naming import (
    refresh_individual_vehicle_info,
    vehicle_display_name,
)
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


_BUILD_UNIT_OPERATIONAL_FIELDS = (
    "draft_id", "output_path", "last_rendered_at", "last_rendered_by",
    "pdf_path", "last_exported_at", "last_exported_by", "status",
    "finalized_at", "finalized_by", "finalized_draft_fingerprint",
    "final_check_version", "finalization_acknowledgements", "reopened_at",
    "reopened_by", "reopen_reason", "company_group_folder_id",
    "company_group_folder_path", "shop_group_folder_id", "shop_group_folder_path",
)

_INDIVIDUAL_OPERATIONAL_FIELDS = (
    "draft_id", "output_path", "confirmed", "confirmed_at", "status",
    "finalized_at", "finalized_by", "finalized_draft_fingerprint",
    "final_check_version", "finalization_acknowledgements", "reopened_at",
    "reopened_by", "reopen_reason", "last_rendered_at", "last_rendered_by",
    "pdf_path", "last_exported_at", "last_exported_by", "qb_job_id",
    "qb_project_id", "qb_project_name", "qb_estimate_id",
    "qb_estimate_snapshot", "qb_estimate_snapshot_at", "qb_invoice_id",
    "company_vehicle_folder_id", "company_vehicle_folder_name",
    "company_vehicle_folder_path", "company_folder_status",
    "company_folder_error", "company_pdf_item_id", "company_pdf_path",
    "company_publication_fingerprint", "company_publication_status",
    "company_publication_error", "shop_vehicle_folder_id",
    "shop_vehicle_folder_name", "shop_vehicle_folder_path", "shop_folder_status",
    "shop_folder_error", "shop_pdf_item_id", "shop_pdf_path",
    "shop_publication_fingerprint", "shop_published_at",
    "shop_publication_status", "shop_publication_error", "shop_reference_items",
)


_OPTIONAL_EXISTING_VEHICLE_FIELDS = (
    "existing_year", "existing_make", "existing_model", "existing_build_type",
    "existing_unit_number", "existing_vin",
)


def _preserve_server_owned_build_state(
    existing_units,
    incoming_units,
    raw_units=None,
) -> None:
    """Keep durable operational identity across ordinary project edits.

    Browser payloads own editable vehicle facts, not SharePoint item IDs,
    QBO links, generated artifacts, or finalization state. Matching by stable
    IDs here prevents a partial/older client from dropping those fields and
    causing folder provisioning to create a second subtree.
    """
    old_units = {unit.unit_id: unit for unit in existing_units}
    old_individuals = {
        individual.individual_id: individual
        for unit in existing_units
        for individual in unit.individuals
    }
    raw_individuals = {
        str(individual.get("individual_id") or ""): individual
        for unit in (raw_units or [])
        if isinstance(unit, dict)
        for individual in (unit.get("individuals") or [])
        if isinstance(individual, dict) and individual.get("individual_id")
    }
    for incoming_unit in incoming_units:
        old_unit = old_units.get(incoming_unit.unit_id)
        if old_unit is not None:
            for field in _BUILD_UNIT_OPERATIONAL_FIELDS:
                setattr(incoming_unit, field, getattr(old_unit, field))
        for incoming_individual in incoming_unit.individuals:
            old_individual = old_individuals.get(incoming_individual.individual_id)
            if old_individual is None:
                continue
            # Older/partial clients do not know the optional replaced-vehicle
            # fields. Preserve a saved value only when the key was omitted;
            # an explicit empty value remains a valid user-requested clear.
            raw_individual = raw_individuals.get(incoming_individual.individual_id, {})
            for field in _OPTIONAL_EXISTING_VEHICLE_FIELDS:
                if field not in raw_individual:
                    setattr(incoming_individual, field, getattr(old_individual, field))
            for field in _INDIVIDUAL_OPERATIONAL_FIELDS:
                setattr(incoming_individual, field, getattr(old_individual, field))


def _load_preset_draft_parts(preset_id: str, paths: AppPaths) -> tuple[list[DraftPart], dict]:
    """Load a preset without dropping picker, renderer, or SKU metadata."""
    try:
        preset = load_preset_dict(preset_id, paths)
    except FileNotFoundError:
        preset = load_preset_dict("blank_custom", paths)
    parts = [draft_part_from_payload(raw, paths) for raw in preset.get("parts") or []]
    overrides = preset.get("placement_overrides")
    return parts, dict(overrides) if isinstance(overrides, dict) else {}


def _canonical_vehicle_type(value: str, paths: AppPaths) -> str:
    try:
        layouts = load_config("vehicle_layouts.json", paths)
    except FileNotFoundError:
        # Draft creation historically did not require a materialized workspace
        # config. Keep partial/older workspaces working while still resolving
        # against the validated definitions packaged with the app.
        layouts = load_bundled_config("vehicle_layouts.json", paths)
    return resolve_vehicle_type(value, layouts)


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


def handle_set_project_completion(project_id: str, body: dict, paths: AppPaths) -> dict:
    """Move one project between the active list and Project Archives."""
    if not isinstance(body.get("completed"), bool):
        return {"ok": False, "error": "completed must be true or false"}
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    completed = body["completed"]
    target_status = "completed" if completed else "active"
    if project.project_status == target_status:
        return {"ok": True, "unchanged": True, "project": asdict(project)}

    now = datetime.now(timezone.utc).isoformat()
    actor = str(body.get("actor") or "").strip()
    project.project_status = target_status
    if completed:
        project.completed_at = now
        project.completed_by = actor
    else:
        project.reactivated_at = now
        project.reactivated_by = actor
        project.completed_at = ""
        project.completed_by = ""
    path = save_project(project, paths)
    return {
        "ok": True,
        "unchanged": False,
        "project": asdict(project),
        "path": str(path),
    }


def _normalized_agency_year(customer: CustomerInfo) -> tuple[str, str] | None:
    """Return the unique project key, with a legacy name fallback."""

    year = str(customer.build_year or "").strip()
    agency_id = str(customer.agency_id or "").strip().casefold()
    agency_name = " ".join(str(customer.agency or "").split()).casefold()
    agency_key = f"id:{agency_id}" if agency_id else (f"name:{agency_name}" if agency_name else "")
    if not agency_key or not year:
        return None
    return agency_key, year


def _repair_customer_agency_id(customer: CustomerInfo, paths: AppPaths) -> None:
    """Resolve and refresh exact agency identity without changing fuzzy matches."""

    from .agency_service import load_agency_choices
    choices = load_agency_choices(paths)
    match = None
    if customer.agency_id:
        match = next(
            (item for item in choices if item["agency_id"] == customer.agency_id),
            None,
        )
    elif customer.agency:
        wanted = customer.agency.strip().casefold()
        matches = [
            item for item in choices
            if item["name"].strip().casefold() == wanted
        ]
        if len(matches) == 1:
            match = matches[0]
    if match is not None:
        customer.agency_id = match["agency_id"]
        customer.agency = match["name"]
        customer.agency_abbreviation = match["abbreviation"]


def _agency_year_conflict(
    customer: CustomerInfo,
    paths: AppPaths,
    *,
    exclude_project_id: str = "",
):
    wanted = _normalized_agency_year(customer)
    if wanted is None:
        return None
    return next(
        (
            candidate for candidate in list_projects(paths)
            if candidate.project_id != exclude_project_id
            and _normalized_agency_year(candidate.customer) == wanted
        ),
        None,
    )


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
            candidate_customer = customer_from_dict(body["customer"])
            # The search box permits free typing. If the user types the exact
            # name of one saved agency without clicking its suggestion, repair
            # the missing ID before enforcing agency/year uniqueness.
            _repair_customer_agency_id(candidate_customer, paths)
            if is_new_project and not candidate_customer.build_year.strip():
                return {
                    "ok": False,
                    "error_code": "build_year_required",
                    "error": "Build year is required for a new project.",
                }
            conflict = _agency_year_conflict(
                candidate_customer,
                paths,
                exclude_project_id=project.project_id,
            )
            if conflict is not None:
                return {
                    "ok": False,
                    "error_code": "project_exists_for_agency_year",
                    "error": (
                        f"A {candidate_customer.build_year.strip()} project already exists for "
                        f"{candidate_customer.agency.strip() or 'this agency'}. Open that project "
                        "and add the new builds there."
                    ),
                    "existing_project_id": conflict.project_id,
                }
            project.customer = candidate_customer

        if project.customer.quote_number:
            quote = project.customer.quote_number.strip()
            if quote and quote not in project.quote_numbers:
                project.quote_numbers.append(quote)

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
            incoming_units = [build_unit_from_dict(u) for u in body["build_units"]]
            if not is_new_project:
                _preserve_server_owned_build_state(
                    project.build_units, incoming_units, body["build_units"],
                )
            project.build_units = incoming_units

        if "project_notes" in body:
            project.project_notes = str(body.get("project_notes") or "").strip()

        from .vehicle_folder_provisioning_service import (
            mark_project_folder_provisioning_pending,
        )
        mark_project_folder_provisioning_pending(project)
        path = save_project(project, paths)

        # Existing drafts need the new shared instruction immediately too.  We
        # keep it as a separate draft field so a project edit never overwrites
        # build-specific installation and delivery notes.
        draft_contexts = {
            individual.draft_id: (unit, individual, ordinal)
            for unit in project.build_units
            for ordinal, individual in enumerate(unit.individuals, start=1)
            if individual.draft_id
        }
        draft_ids = {
            draft_id
            for unit in project.build_units
            for draft_id in [unit.draft_id, *(ind.draft_id for ind in unit.individuals)]
            if draft_id
        }
        for draft_id in draft_ids:
            try:
                draft = load_draft_for_request(draft_id, paths)
                changed = False
                if draft.project_notes != project.project_notes:
                    draft.project_notes = project.project_notes
                    changed = True
                context = draft_contexts.get(draft_id)
                if context is not None:
                    unit, individual, ordinal = context
                    vehicle_info = refresh_individual_vehicle_info(
                        draft.vehicle_info,
                        project,
                        unit,
                        individual,
                        ordinal=ordinal,
                    )
                    vehicle_info.update({
                        "Agency": project.customer.agency,
                        "AgencyAbbreviation": project.customer.agency_abbreviation,
                        "SalesRep": project.customer.sales_rep,
                        "project_total_units": sum(u.quantity for u in project.build_units),
                    })
                    if vehicle_info != draft.vehicle_info:
                        draft.vehicle_info = vehicle_info
                        changed = True
                if changed:
                    save_draft(draft, paths.workspace_drafts_dir)
            except FileNotFoundError:
                # A draft can be cleared/recreated while its project record is
                # being edited. The fresh draft receives this value below.
                continue

        from .vehicle_folder_provisioning_service import schedule_project_folder_provisioning
        folder_provisioning_scheduled = schedule_project_folder_provisioning(
            project.project_id, paths,
        )

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

        return {
            "ok": True,
            "project_id": project.project_id,
            "path": str(path),
            "folder_provisioning_scheduled": folder_provisioning_scheduled,
        }
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
        "VehicleType": _canonical_vehicle_type(unit.vehicle_model, paths),
        "Agency": project.customer.agency,
        "AgencyAbbreviation": project.customer.agency_abbreviation,
        "BuildYear": project.customer.build_year,
        "SalesRep": project.customer.sales_rep,
        "ProjectID": project_id_val,
        "BuildType": unit.build_type,
        "project_total_units": project_total_units,
        "CanonicalVehicleName": vehicle_display_name(project, unit, None),
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
    vehicle_info: dict = {
        "VehicleType": _canonical_vehicle_type(unit.vehicle_model, paths),
        "Agency": project.customer.agency,
        "AgencyAbbreviation": project.customer.agency_abbreviation,
        "BuildYear": project.customer.build_year,
        "SalesRep": project.customer.sales_rep,
        "ProjectID": project_id_val,
        "BuildType": unit.build_type,
        "project_total_units": project_total_units,
    }
    vehicle_info = refresh_individual_vehicle_info(
        vehicle_info,
        project,
        unit,
        individual,
        ordinal=ind_idx + 1,
    )

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
