from __future__ import annotations

import logging
import uuid
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
    "existing_unit_number", "existing_vin", "previous_build",
    "quote_references",
)

_QUOTE_REFERENCE_QB_FIELDS = (
    "match_status", "qb_estimate_id", "estimate_status", "customer",
    "txn_date", "checked_at",
)


def _unit_notes_rows(notes: str) -> list[str]:
    """Store unit/build notes as one value so embedded line breaks survive."""
    value = str(notes or "").strip()
    return [value] if value else []


def _recover_unit_note_breaks(notes: str, draft_rows: object) -> str:
    """Recover paragraph boundaries retained by older draft note arrays."""
    value = str(notes or "").strip()
    rows = [str(row).strip() for row in (draft_rows or []) if str(row).strip()]
    if "\n" in value:
        return value
    if not value and rows:
        return "\n\n".join(rows)
    if len(rows) < 2:
        return value
    recovered = "\n\n".join(rows)
    if not value:
        return recovered
    flattened = lambda text: " ".join(str(text).split()).casefold()
    return recovered if flattened(value) == flattened(" ".join(rows)) else value


def _clear_quote_reference_qb_fields(reference) -> None:
    reference.match_status = "pending"
    reference.qb_estimate_id = ""
    reference.estimate_status = ""
    reference.customer = ""
    reference.txn_date = ""
    reference.checked_at = ""


def _align_primary_estimate_reference(individual) -> None:
    """Keep the writable Estimate on a current, matched quote reference."""
    refs = list(getattr(individual, "quote_references", []) or [])
    current = [
        ref for ref in refs
        if ref.state == "current" and ref.match_status == "linked" and ref.qb_estimate_id
    ]
    primary = str(individual.qb_estimate_id or "").strip()
    if not primary:
        return
    primary_reference = next((ref for ref in refs if ref.qb_estimate_id == primary), None)
    # Legacy projects can have the singular Estimate connection without a
    # quote-reference row. Preserve it until a verified QB read backfills the
    # human-facing quote number.
    if primary_reference is None:
        return
    if primary_reference in current:
        return
    individual.qb_estimate_id = current[0].qb_estimate_id if current else ""
    if not individual.qb_estimate_id:
        individual.qb_estimate_snapshot = {}
        individual.qb_estimate_snapshot_at = ""


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
            old_references = {
                reference.reference_id: reference
                for reference in old_individual.quote_references
            }
            for reference in incoming_individual.quote_references:
                old_reference = old_references.get(reference.reference_id)
                if (
                    old_reference is None
                    or old_reference.quote_number.casefold() != reference.quote_number.casefold()
                ):
                    _clear_quote_reference_qb_fields(reference)
                    continue
                for field in _QUOTE_REFERENCE_QB_FIELDS:
                    setattr(reference, field, getattr(old_reference, field))
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
    # Older builds stored each entered line as a separate draft row while the
    # project-side unit note could be empty or flattened. Restore only the
    # unambiguous cases, then persist once so subsequent reads use one value.
    for project in projects:
        changed = False
        for unit in project.build_units:
            for individual in unit.individuals:
                if not individual.draft_id:
                    continue
                try:
                    draft = load_draft_for_request(individual.draft_id, paths)
                except FileNotFoundError:
                    continue
                recovered = _recover_unit_note_breaks(
                    individual.notes,
                    draft.notes.get("INSTALLATION NOTES", []),
                )
                if recovered != individual.notes:
                    individual.notes = recovered
                    changed = True
        if changed:
            save_project(project, paths)
    return {"ok": True, "projects": [asdict(p) for p in projects]}


def handle_get_project(project_id: str, paths: AppPaths) -> dict:
    try:
        project = load_project(project_id, paths)
        return {"ok": True, "project": asdict(project)}
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_save_individual_notes(
    project_id: str,
    unit_id: str,
    individual_id: str,
    body: dict,
    paths: AppPaths,
) -> dict:
    """Atomically update the one unit/build-notes value and its draft mirror."""
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    unit = next((item for item in project.build_units if item.unit_id == unit_id), None)
    individual = next(
        (item for item in (unit.individuals if unit else []) if item.individual_id == individual_id),
        None,
    )
    if unit is None or individual is None:
        return {"ok": False, "error": "Unit not found"}
    if individual.status == "finalized":
        return {"ok": False, "error": "Reopen this finalized build before editing its notes"}
    notes = str(body.get("notes") or "").strip()
    individual.notes = notes
    save_project(project, paths)
    if individual.draft_id:
        try:
            draft = load_draft_for_request(individual.draft_id, paths)
            if notes:
                draft.notes["INSTALLATION NOTES"] = _unit_notes_rows(notes)
            else:
                draft.notes.pop("INSTALLATION NOTES", None)
            save_draft(draft, paths.workspace_drafts_dir)
        except FileNotFoundError:
            pass
    return {
        "ok": True,
        "project_id": project_id,
        "unit_id": unit_id,
        "individual_id": individual_id,
        "notes": notes,
    }


def handle_set_project_lifecycle(project_id: str, body: dict, paths: AppPaths) -> dict:
    """Move one project among Active, Inactive, and Completed."""
    target_status = str(body.get("status") or "").strip().lower()
    if target_status not in {"active", "inactive", "completed"}:
        return {
            "ok": False,
            "error": "status must be active, inactive, or completed",
        }
    try:
        project = load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": f"Project not found: {project_id}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if project.project_status == target_status:
        return {"ok": True, "unchanged": True, "project": asdict(project)}

    if target_status == "completed":
        conflict = _agency_year_conflict(
            project.customer,
            paths,
            exclude_project_id=project.project_id,
            statuses={"completed"},
            work_type=project.project_type,
        )
        if conflict is not None:
            resolution = str(body.get("conflict_resolution") or "").strip().lower()
            if not resolution:
                return _completion_conflict_result(project, conflict)
            if resolution not in {"merge", "overwrite"}:
                return {
                    "ok": False,
                    "error_code": "invalid_completion_resolution",
                    "error": "Choose merge, overwrite, or cancel.",
                }
            if resolution == "overwrite" and str(
                body.get("overwrite_confirmation") or ""
            ).strip() != "OVERWRITE":
                return {
                    "ok": False,
                    "error_code": "overwrite_confirmation_required",
                    "error": "Type OVERWRITE to confirm replacing the completed project.",
                }
            return _resolve_completed_project_conflict(
                project,
                conflict,
                resolution=resolution,
                actor=str(body.get("actor") or "").strip(),
                paths=paths,
            )

    now = datetime.now(timezone.utc).isoformat()
    actor = str(body.get("actor") or "").strip()
    reason = str(body.get("reason") or "").strip()
    previous_status = project.project_status
    project.project_status = target_status
    if target_status == "inactive":
        project.inactive_at = now
        project.inactive_by = actor
        project.inactive_reason = reason
        project.completed_at = ""
        project.completed_by = ""
    elif target_status == "completed":
        project.completed_at = now
        project.completed_by = actor
        project.inactive_at = ""
        project.inactive_by = ""
        project.inactive_reason = ""
    else:
        project.reactivated_at = now
        project.reactivated_by = actor
        project.inactive_at = ""
        project.inactive_by = ""
        project.inactive_reason = ""
        project.completed_at = ""
        project.completed_by = ""
    project.project_lifecycle_history.append({
        "event_id": str(uuid.uuid4()),
        "from_status": previous_status,
        "to_status": target_status,
        "occurred_at": now,
        "actor": actor,
        "reason": reason,
    })
    path = save_project(project, paths)
    return {
        "ok": True,
        "unchanged": False,
        "project": asdict(project),
        "path": str(path),
    }


def handle_set_project_completion(project_id: str, body: dict, paths: AppPaths) -> dict:
    """Backward-compatible Active/Completed wrapper for the existing UI."""
    if not isinstance(body.get("completed"), bool):
        return {"ok": False, "error": "completed must be true or false"}
    return handle_set_project_lifecycle(
        project_id,
        {
            **body,
            "status": "completed" if body["completed"] else "active",
        },
        paths,
    )


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


def _canonicalize_customer_identities(
    customer: CustomerInfo, paths: AppPaths, *, required: bool,
) -> dict | None:
    """Require stable selections; typed labels alone are never identities."""
    from .agency_service import load_agency_choices
    from .sales_rep_service import load_reps

    agency_id = str(customer.agency_id or "").strip()
    agency = next((
        item for item in load_agency_choices(paths)
        if item["agency_id"] == agency_id
    ), None)
    if agency is None and (required or agency_id):
        return {
            "ok": False,
            "error_code": "agency_selection_required",
            "error": "Select an existing agency from the results or create it in the agency form.",
        }
    rep_id = str(customer.sales_rep_id or "").strip()
    rep = next((
        item for item in load_reps(paths)
        if item.rep_id == rep_id
    ), None)
    if rep is None and (required or rep_id):
        return {
            "ok": False,
            "error_code": "sales_rep_selection_required",
            "error": "Select an existing sales rep from the results or create one in the sales rep form.",
        }
    if agency is not None:
        customer.agency_id = agency["agency_id"]
        customer.agency = agency["name"]
        customer.agency_abbreviation = agency["abbreviation"]
    if rep is not None:
        customer.sales_rep_id = rep.rep_id
        customer.sales_rep = rep.name
    return None


def _agency_year_conflict(
    customer: CustomerInfo,
    paths: AppPaths,
    *,
    exclude_project_id: str = "",
    statuses: set[str] | None = None,
    work_type: str = "build",
):
    # Separate service visits retain independent project and vehicle identities.
    if work_type != "build":
        return None
    wanted = _normalized_agency_year(customer)
    if wanted is None:
        return None
    return next(
        (
            candidate for candidate in list_projects(paths)
            if candidate.project_type == work_type
            and candidate.project_id != exclude_project_id
            and _normalized_agency_year(candidate.customer) == wanted
            and (statuses is None or candidate.project_status in statuses)
        ),
        None,
    )


def _project_vehicle_comparison(project) -> dict:
    vehicles = []
    for build_unit in project.build_units:
        if build_unit.individuals:
            for ordinal, individual in enumerate(build_unit.individuals, start=1):
                vehicles.append({
                    "individual_id": individual.individual_id,
                    "label": vehicle_display_name(
                        project, build_unit, individual, ordinal=ordinal,
                    ),
                    "unit_number": individual.unit_number,
                    "vin": individual.vin,
                    "vehicle_model": build_unit.vehicle_model,
                    "build_type": build_unit.build_type,
                })
        else:
            vehicles.append({
                "individual_id": "",
                "label": vehicle_display_name(project, build_unit, None),
                "unit_number": "",
                "vin": "",
                "vehicle_model": build_unit.vehicle_model,
                "build_type": build_unit.build_type,
            })
    return {
        "project_id": project.project_id,
        "project_status": project.project_status,
        "agency": project.customer.agency,
        "build_year": project.customer.build_year,
        "quote_numbers": list(project.quote_numbers),
        "project_notes": project.project_notes,
        "build_group_count": len(project.build_units),
        "vehicle_count": sum(unit.quantity for unit in project.build_units),
        "vehicles": vehicles,
    }


def _completion_conflict_result(source, completed) -> dict:
    return {
        "ok": False,
        "error_code": "completed_project_exists_for_agency_year",
        "error": (
            f"A completed {source.customer.build_year.strip()} project already exists for "
            f"{source.customer.agency.strip() or 'this agency'}. Compare the projects before "
            "merging or overwriting anything."
        ),
        "active_project": _project_vehicle_comparison(source),
        "completed_project": _project_vehicle_comparison(completed),
    }


def _unique_strings(*groups) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in (item for group in groups for item in group):
        cleaned = str(value or "").strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result


def _merged_notes(first: str, second: str) -> str:
    return "\n\n".join(_unique_strings([first], [second]))


def _resolve_completed_project_conflict(
    source,
    completed,
    *,
    resolution: str,
    actor: str,
    paths: AppPaths,
) -> dict:
    source_unit_ids = {unit.unit_id for unit in source.build_units}
    completed_unit_ids = {unit.unit_id for unit in completed.build_units}
    source_vehicle_ids = {
        individual.individual_id
        for unit in source.build_units
        for individual in unit.individuals
    }
    completed_vehicle_ids = {
        individual.individual_id
        for unit in completed.build_units
        for individual in unit.individuals
    }
    if resolution == "merge" and (
        source_unit_ids.intersection(completed_unit_ids)
        or source_vehicle_ids.intersection(completed_vehicle_ids)
    ):
        return {
            "ok": False,
            "error_code": "project_merge_identity_conflict",
            "error": (
                "These projects reuse an internal build or vehicle ID, so they cannot be "
                "merged safely. Cancel and review the projects instead."
            ),
        }

    now = datetime.now(timezone.utc).isoformat()
    old_vehicle_ids = sorted(completed_vehicle_ids)
    if resolution == "merge":
        completed.build_units.extend(source.build_units)
        completed.project_notes = _merged_notes(
            completed.project_notes, source.project_notes,
        )
        completed.reference_assets.extend(
            asset for asset in source.reference_assets
            if asset.reference_id not in {
                existing.reference_id for existing in completed.reference_assets
            }
        )
        completed.reference_source_exclusions = _unique_strings(
            completed.reference_source_exclusions,
            source.reference_source_exclusions,
        )
        completed.quote_numbers = _unique_strings(
            completed.quote_numbers,
            source.quote_numbers,
            [completed.customer.quote_number, source.customer.quote_number],
        )
        existing_project_estimates = {
            reference.qb_estimate_id or reference.quote_number.casefold()
            for reference in completed.project_quote_references
        }
        completed.project_quote_references.extend(
            reference for reference in source.project_quote_references
            if (reference.qb_estimate_id or reference.quote_number.casefold())
            not in existing_project_estimates
        )
        # The active project contains the most recently entered agency/contact
        # facts and preferences. Builds retain their own drafts and stable IDs.
        completed.customer = source.customer
        completed.preferences = source.preferences
    else:
        completed.customer = source.customer
        completed.preferences = source.preferences
        completed.build_units = source.build_units
        completed.project_notes = source.project_notes
        completed.quote_numbers = _unique_strings(
            source.quote_numbers, [source.customer.quote_number],
        )
        completed.project_quote_references = source.project_quote_references
        completed.reference_assets = source.reference_assets
        completed.reference_source_exclusions = source.reference_source_exclusions

    completed.project_status = "completed"
    completed.completed_at = now
    completed.completed_by = actor
    completed.inactive_at = ""
    completed.inactive_by = ""
    completed.inactive_reason = ""
    completed.project_lifecycle_history.extend(source.project_lifecycle_history)
    completed.project_lifecycle_history.append({
        "event_id": str(uuid.uuid4()),
        "from_status": source.project_status,
        "to_status": "completed",
        "occurred_at": now,
        "actor": actor,
        "reason": (
            f"{resolution.title()}d project {source.project_id} into completed "
            f"project {completed.project_id}"
        ),
    })
    save_project(completed, paths)
    delete_project(source.project_id, paths)
    return {
        "ok": True,
        "unchanged": False,
        "resolution": resolution,
        "project": asdict(completed),
        "project_id": completed.project_id,
        "removed_project_id": source.project_id,
        "old_completed_vehicle_ids": old_vehicle_ids,
        "moved_vehicle_ids": sorted(source_vehicle_ids),
    }


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

        from ...domain.project_types import project_type, service_details
        old_type = project.project_type
        old_details = project.service_details
        previous_links = {i.individual_id: i.previous_build for u in project.build_units for i in u.individuals}
        project.project_type = project_type(body.get('project_type', old_type))
        if project.project_type != old_type and any(
            holder.status == 'finalized' for unit in project.build_units
            for holder in (unit, *unit.individuals)
        ):
            raise ValueError('Reopen finalized work before changing the project type')
        if 'service_details' in body:
            project.service_details = service_details(body['service_details'])
            if project.service_details != old_details and any(h.status == 'finalized' for u in project.build_units for h in (u, *u.individuals)):
                raise ValueError('Reopen finalized work before changing service requirements')
        if project.project_type == 'offsite' and not all(project.service_details.get(k) for k in ('location', 'contact')):
            raise ValueError('Enter the off-site service location and contact')
        if project.project_type == 'build' and old_type != 'build':
            conflict = _agency_year_conflict(project.customer, paths, exclude_project_id=project.project_id)
            if conflict is not None:
                raise ValueError('A Build project already exists for this agency and year')

        if "customer" in body:
            candidate_customer = customer_from_dict(body["customer"])
            identity_error = _canonicalize_customer_identities(
                candidate_customer,
                paths,
                required=body.get("require_selected_identities") is True,
            )
            if identity_error is not None:
                return identity_error
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
                statuses={"active"},
                work_type=project.project_type,
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
            else:
                for incoming_unit in incoming_units:
                    for incoming_individual in incoming_unit.individuals:
                        for reference in incoming_individual.quote_references:
                            _clear_quote_reference_qb_fields(reference)
            project.build_units = incoming_units

        for unit in project.build_units:
            for individual in unit.individuals:
                _align_primary_estimate_reference(individual)
                for reference in individual.quote_references:
                    quote = reference.quote_number.strip()
                    if quote and quote.casefold() not in {
                        item.casefold() for item in project.quote_numbers
                    }:
                        project.quote_numbers.append(quote)

        for unit in project.build_units:
            for individual in unit.individuals:
                link = individual.previous_build
                if not link or link == previous_links.get(individual.individual_id):
                    continue
                if project.project_type == 'build' or set(link) != {'project_id', 'unit_id', 'individual_id'} or link['project_id'] == project.project_id:
                    raise ValueError('Previous build must reference a vehicle in a different Build project')
                source = load_project(link['project_id'], paths)
                if source.project_type != 'build' or not any(u.unit_id == link['unit_id'] and any(i.individual_id == link['individual_id'] for i in u.individuals) for u in source.build_units):
                    raise ValueError('The selected previous build vehicle is unavailable')

        if "project_notes" in body:
            project.project_notes = str(body.get("project_notes") or "").strip()

        from .vehicle_folder_provisioning_service import (
            mark_project_folder_provisioning_pending,
        )
        mark_project_folder_provisioning_pending(project)
        path = save_project(project, paths)

        # Existing drafts need project instructions and the canonical unit
        # notes immediately. Unit notes remain one user-facing value; the
        # draft mirror exists only for build-sheet generation.
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
        recovered_project_notes = False
        for draft_id in draft_ids:
            try:
                draft = load_draft_for_request(draft_id, paths)
                changed = False
                work_info = {'ProjectType': project.project_type, 'ServiceDetails': project.service_details}
                if any(draft.vehicle_info.get(k) != v for k, v in work_info.items()) and (project.project_type != 'build' or 'ProjectType' in draft.vehicle_info):
                    draft.vehicle_info.update(work_info)
                    changed = True
                if draft.project_notes != project.project_notes:
                    draft.project_notes = project.project_notes
                    changed = True
                context = draft_contexts.get(draft_id)
                if context is not None:
                    unit, individual, ordinal = context
                    recovered = _recover_unit_note_breaks(
                        individual.notes,
                        draft.notes.get("INSTALLATION NOTES", []),
                    )
                    if recovered != individual.notes:
                        individual.notes = recovered
                        recovered_project_notes = True
                    desired_unit_notes = _unit_notes_rows(individual.notes)
                    if desired_unit_notes:
                        if draft.notes.get("INSTALLATION NOTES") != desired_unit_notes:
                            draft.notes["INSTALLATION NOTES"] = desired_unit_notes
                            changed = True
                    elif "INSTALLATION NOTES" in draft.notes:
                        draft.notes.pop("INSTALLATION NOTES", None)
                        changed = True
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
        if recovered_project_notes:
            save_project(project, paths)

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
        "ProjectType": project.project_type,
        "ServiceDetails": project.service_details,
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
    if prefs.laptop_make:
        pref_notes.append(f"Laptop make: {prefs.laptop_make}")
    if prefs.laptop_model:
        pref_notes.append(f"Laptop model: {prefs.laptop_model}")
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
        "ProjectType": project.project_type,
        "ServiceDetails": project.service_details,
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
    if prefs.laptop_make:
        pref_notes.append(f"Laptop make: {prefs.laptop_make}")
    if prefs.laptop_model:
        pref_notes.append(f"Laptop model: {prefs.laptop_model}")
    if prefs.slick_top:
        pref_notes.append("Slick top: Yes")
    if prefs.mixed_brands:
        pref_notes.append("Mixed brands: Yes")
    if prefs.notes:
        pref_notes.append(prefs.notes)
    notes: dict[str, list[str]] = {}
    if pref_notes:
        notes["EQUIPMENT PREFERENCES"] = pref_notes
    if individual.notes:
        notes["INSTALLATION NOTES"] = _unit_notes_rows(individual.notes)

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
