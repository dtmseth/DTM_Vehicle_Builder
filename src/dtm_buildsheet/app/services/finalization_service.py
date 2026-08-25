from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

from ...inputs.project_entry import list_projects, load_project, save_project
from ...paths import AppPaths
from .draft_service import _current_user_display_name, load_draft_for_request


CHECK_VERSION = "3"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _target(project, unit_id: str, individual_id: str):
    unit = next((candidate for candidate in project.build_units if candidate.unit_id == unit_id), None)
    if unit is None:
        return None, None, "Build unit not found"
    if individual_id:
        individual = next(
            (candidate for candidate in unit.individuals if candidate.individual_id == individual_id),
            None,
        )
        if individual is None:
            return unit, None, "Individual unit not found"
        return unit, individual, ""
    return unit, unit, ""


def _draft_fingerprint(draft) -> str:
    data = asdict(draft)
    for key in ("created_at", "updated_at", "audit_trail", "user_modified", "validation_messages"):
        data.pop(key, None)
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _equipment_facts(draft) -> list[dict[str, str]]:
    """Flatten installed rows and their SKU components for final checks."""
    facts: list[dict[str, str]] = []
    for part in draft.parts:
        if not part.include:
            continue
        picker = part.picker_config if isinstance(part.picker_config, dict) else {}
        facts.append({
            "name": str(part.name or "").strip().lower(),
            "part_type": str(part.part_type or "").strip().lower(),
            "part_number": str(part.part_number or "").strip().lower(),
            "location": str(part.location or "").strip().lower(),
            "product_id": str(picker.get("product_id") or "").strip().lower(),
            "system_type": str(picker.get("system_type") or "").strip().lower(),
        })
        for component in part.components or []:
            if not isinstance(component, dict):
                continue
            facts.append({
                "name": str(component.get("name") or component.get("description") or "").strip().lower(),
                "part_type": str(component.get("part_type") or part.part_type or "").strip().lower(),
                "part_number": str(component.get("part_number") or component.get("sku") or "").strip().lower(),
                "location": str(component.get("location") or part.location or "").strip().lower(),
                "product_id": str(component.get("product_id") or "").strip().lower(),
                "system_type": str(component.get("system_type") or picker.get("system_type") or "").strip().lower(),
            })
    return facts


def _fact_has(facts: list[dict[str, str]], *, types=(), products=(), numbers=(), terms=()) -> bool:
    wanted_types = {str(value).lower() for value in types}
    wanted_products = {str(value).lower() for value in products}
    wanted_numbers = {str(value).lower() for value in numbers}
    wanted_terms = tuple(str(value).lower() for value in terms)
    for fact in facts:
        if wanted_types and fact["part_type"] in wanted_types:
            return True
        if wanted_products and fact["product_id"] in wanted_products:
            return True
        if wanted_numbers and fact["part_number"] in wanted_numbers:
            return True
        haystack = " ".join(fact.values())
        if wanted_terms and any(term in haystack for term in wanted_terms):
            return True
    return False


def _warning_regions(facts: list[dict[str, str]]) -> set[str]:
    regions: set[str] = set()
    for fact in facts:
        part_type = fact["part_type"]
        haystack = " ".join((fact["name"], fact["location"], part_type))
        if part_type == "roof_light_bar":
            regions.update(("front", "side", "rear"))
        if part_type in {"front_warning", "front_side_warning", "front_interior_light_bar"}:
            regions.add("front")
        if part_type in {"side_warning", "front_side_warning", "mirror_warning", "pit_bar_warning"}:
            regions.add("side")
        if part_type in {"rear_warning", "lower_lift_gate_warning", "rear_interior_light_bar"}:
            regions.add("rear")
        if any(term in haystack for term in ("front", "forward", "grill", "grille", "headlight", "windshield")):
            regions.add("front")
        if any(term in haystack for term in (" side", "side ", "mirror", "rocker", "running board", "b-pillar", "fender")):
            regions.add("side")
        if any(term in haystack for term in ("rear", "liftgate", "lift gate", "tail")):
            regions.add("rear")
    return regions


def _presence_check(check_id: str, label: str, present: bool, missing_message: str) -> dict:
    return {
        "id": check_id,
        "title": label if present else f"No {label.lower()}",
        "status": "passed" if present else "warning",
        "message": f"{label} is present." if present else missing_message,
    }


def _equipment_checks(draft, build_unit) -> list[dict]:
    # Guided systems store several real installed items as child rows. They
    # still satisfy final-build presence checks even though the manifest nests
    # them beneath the system parent.
    facts = _equipment_facts(draft)
    build_type = str(getattr(build_unit, "build_type", "") or "").strip().lower()
    is_patrol = "patrol" in build_type
    has_roof_bar = _fact_has(facts, types=("roof_light_bar",), terms=("roof light bar",))
    has_interior_bar = _fact_has(
        facts,
        types=("front_interior_light_bar", "rear_interior_light_bar"),
        terms=("interior light bar", "inner edge"),
    )
    has_warning = _fact_has(facts, types={
        "warning_light", "front_warning", "side_warning", "rear_warning",
        "front_side_warning", "mirror_warning", "pit_bar_warning",
        "lower_lift_gate_warning", "roof_light_bar", "front_interior_light_bar",
        "rear_interior_light_bar",
    }, terms=("warning", "light bar"))
    has_speaker = _fact_has(facts, types=("siren_speaker",), terms=("siren speaker",))
    has_controller = _fact_has(facts, types=("light_controller",), terms=("light controller", "cencom core"))
    has_control_head = _fact_has(facts, types=("control_head",), terms=("control head",))
    has_core = _fact_has(
        facts, products=("whelen_core",), numbers=("c399",), terms=("cencom core",),
    )
    has_vehicle_interface = _fact_has(
        facts,
        products=("whelen_core_canport_cable",),
        terms=("canport", "can port", "scanport", "scan port"),
    ) or any(
        fact["part_number"].startswith("c399k") or fact["part_number"] == "c399sp"
        for fact in facts
    )
    has_photo_eye = _fact_has(facts, types=("photo_eye",), numbers=("lcphoto",), terms=("photo eye",))
    has_dock = _fact_has(facts, types=("docking_station",), terms=("docking station",))
    has_motion = _fact_has(facts, types=("motion_attachment",), terms=("motion attachment", "motion adapter", "motion arm"))
    has_radio = _fact_has(facts, types=("radio_system", "radio_head", "radio_brick"), terms=("radio system",)) or any(
        fact["system_type"] == "radio" for fact in facts
    )
    has_radar = _fact_has(facts, types=("radar_system", "radar_display_unit"), terms=("radar system",)) or any(
        fact["system_type"] == "radar" for fact in facts
    )
    has_camera = _fact_has(
        facts,
        types=("camera_system", "camera_dvr", "front_camera", "rear_camera", "rear_seat_camera", "body_camera_dock"),
        terms=("camera system", "camera dvr", "body camera dock"),
    ) or any(fact["system_type"] == "camera" for fact in facts)
    has_front_partition = _fact_has(facts, types=("front_partition",), terms=("front partition",))
    has_rear_partition = _fact_has(facts, types=("rear_partition",), terms=("rear partition",))
    has_expansion = _fact_has(
        facts, types=("expansion_module",), numbers=("cem8", "cem16", "cem24"), terms=("expansion module",),
    )
    regions = _warning_regions(facts)
    checks = [
        _presence_check(
            f"{region}_warning_coverage",
            f"{region.title()} warning coverage",
            region in regions,
            f"No {region} warning-light coverage is listed. Confirm the build has adequate {region} warning.",
        )
        for region in ("front", "side", "rear")
    ]
    checks.extend([
        {
            "id": "no_siren_speaker",
            "title": "Siren speaker" if has_speaker else "No siren speaker",
            "status": "passed" if has_speaker else "warning",
            "message": (
                "A siren speaker line is present."
                if has_speaker else "This build has no siren speaker line."
            ),
        },
        {
            "id": "lights_without_controller",
            "title": "Lights and controller",
            "status": "warning" if has_warning and not has_controller else "passed",
            "message": (
                "Warning lights are present, but no light controller is listed."
                if has_warning and not has_controller
                else "No missing light-controller relationship was found."
            ),
        },
        {
            "id": "controller_without_control_head",
            "title": "Controller and control head",
            "status": "warning" if has_controller and not has_control_head else "passed",
            "message": (
                "A light controller is present, but no control head is listed."
                if has_controller and not has_control_head
                else "No missing control-head relationship was found."
            ),
        },
        {
            "id": "core_vehicle_interface",
            "title": "Core vehicle interface",
            "status": "warning" if has_core and not has_vehicle_interface else "passed",
            "message": (
                "A CenCom Core is present, but no ScanPort or CANPORT vehicle interface is listed."
                if has_core and not has_vehicle_interface
                else "No missing CenCom Core vehicle interface was found."
            ),
        },
        {
            "id": "photo_eye_without_roof_bar",
            "title": "Photo eye for slick-top lighting",
            "status": "warning" if not has_roof_bar and not has_photo_eye else "passed",
            "message": (
                "No roof light bar is present, but no photo eye is listed."
                if not has_roof_bar and not has_photo_eye
                else "The roof-light-bar and photo-eye relationship is complete."
            ),
        },
        {
            "id": "no_primary_light_bar",
            "title": "Primary light bar",
            "status": "warning" if not has_roof_bar and not has_interior_bar else "passed",
            "message": (
                "No roof light bar or interior light bar is listed. Confirm that this is intentional."
                if not has_roof_bar and not has_interior_bar
                else "A roof or interior light bar is present."
            ),
        },
        {
            "id": "docking_without_motion",
            "title": "Docking station motion attachment",
            "status": "warning" if has_dock and not has_motion else "passed",
            "message": (
                "A docking station is present, but no motion attachment is listed."
                if has_dock and not has_motion
                else "No missing docking-station motion attachment was found."
            ),
        },
        _presence_check("no_radio", "Radio", has_radio, "No radio system is listed. Confirm whether a radio is required."),
        {
            "id": "patrol_without_radar",
            "title": "Patrol radar",
            "status": "warning" if is_patrol and not has_radar else "passed",
            "message": (
                "This is a Patrol build, but no radar system is listed."
                if is_patrol and not has_radar
                else "No missing Patrol radar system was found."
            ),
        },
        _presence_check(
            "no_camera", "Camera system", has_camera,
            "No camera system is listed. Confirm whether this agency intentionally has no camera.",
        ),
        {
            "id": "patrol_front_partition",
            "title": "Patrol front partition",
            "status": "warning" if is_patrol and not has_front_partition else "passed",
            "message": (
                "This is a Patrol build, but no front partition is listed."
                if is_patrol and not has_front_partition
                else "No missing Patrol front partition was found."
            ),
        },
        {
            "id": "patrol_rear_partition",
            "title": "Patrol rear partition",
            "status": "warning" if is_patrol and not has_rear_partition else "passed",
            "message": (
                "This is a Patrol build, but no rear partition is listed."
                if is_patrol and not has_rear_partition
                else "No missing Patrol rear partition was found."
            ),
        },
        _presence_check(
            "no_expansion_module", "Expansion module", has_expansion,
            "No expansion module is listed. Confirm that the controller has enough outputs for this build.",
        ),
    ])
    return checks


def _warning_checks(checks: list[dict]) -> list[dict]:
    return [
        {"id": check["id"], "title": check["title"], "message": check["message"]}
        for check in checks if check["status"] == "warning"
    ]


def _check(project_id: str, unit_id: str, individual_id: str, paths: AppPaths) -> dict:
    project = load_project(project_id, paths)
    unit, holder, error = _target(project, unit_id, individual_id)
    if error:
        return {"ok": False, "error": error}
    if not holder.draft_id:
        return {"ok": False, "error": "Configure this build before finalizing"}
    draft = load_draft_for_request(holder.draft_id, paths)
    blocking = []
    if not str(holder.pdf_path or "").strip():
        blocking.append({"id": "pdf_required", "message": "Export a PDF before finalizing."})
    else:
        exported_at = _iso_moment(holder.last_exported_at)
        draft_updated_at = _iso_moment(draft.updated_at)
        if exported_at is None or draft_updated_at is None or exported_at < draft_updated_at:
            blocking.append({"id": "pdf_stale", "message": "The build changed after its PDF export. Export a fresh PDF."})
    equipment_checks = _equipment_checks(draft, unit)
    pdf_check = {
        "id": "current_pdf",
        "title": "Current PDF export",
        "status": "blocked" if blocking else "passed",
        "message": blocking[0]["message"] if blocking else "The exported PDF matches the latest build changes.",
    }
    checks = [pdf_check, *equipment_checks]
    fingerprint = _draft_fingerprint(draft)
    return {
        "ok": True,
        "project": project,
        "unit": unit,
        "holder": holder,
        "draft": draft,
        "fingerprint": fingerprint,
        "blocking": blocking,
        "warnings": _warning_checks(equipment_checks),
        "checks": checks,
    }


def handle_finalization_check(project_id: str, unit_id: str, individual_id: str, paths: AppPaths) -> dict:
    try:
        result = _check(project_id, unit_id, individual_id, paths)
        if not result.get("ok"):
            return result
        holder = result["holder"]
        return {
            "ok": True,
            "status": holder.status,
            "finalized_at": holder.finalized_at,
            "finalized_by": holder.finalized_by,
            "reopened_at": holder.reopened_at,
            "reopened_by": holder.reopened_by,
            "reopen_reason": holder.reopen_reason,
            "blocking": result["blocking"],
            "warnings": result["warnings"],
            "checks": result["checks"],
            "fingerprint": result["fingerprint"],
            "check_version": CHECK_VERSION,
        }
    except FileNotFoundError:
        return {"ok": False, "error": "Project or draft not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_finalize_build(project_id: str, unit_id: str, individual_id: str, body: dict, paths: AppPaths) -> dict:
    try:
        result = _check(project_id, unit_id, individual_id, paths)
        if not result.get("ok"):
            return result
        if result["blocking"]:
            return {"ok": False, "error": "finalization_blocked", "blocking": result["blocking"]}
        if str(body.get("fingerprint") or "") != result["fingerprint"]:
            return {"ok": False, "error": "build_changed", "message": "The build changed. Review the final checks again."}
        supplied = body.get("acknowledgements") or []
        notes = {
            str(item.get("id") or ""): str(item.get("note") or "").strip()
            for item in supplied if isinstance(item, dict)
        }
        missing = [warning["id"] for warning in result["warnings"] if len(notes.get(warning["id"], "")) < 3]
        if missing:
            return {"ok": False, "error": "acknowledgement_required", "warning_ids": missing}
        now = _utcnow()
        holder = result["holder"]
        holder.status = "finalized"
        holder.finalized_at = now
        holder.finalized_by = _current_user_display_name() or "Local User"
        holder.finalized_draft_fingerprint = result["fingerprint"]
        holder.final_check_version = CHECK_VERSION
        holder.finalization_acknowledgements = [
            {"id": warning["id"], "note": notes[warning["id"]], "at": now}
            for warning in result["warnings"]
        ]
        save_project(result["project"], paths)
        return {"ok": True, "status": holder.status, "finalized_at": now, "finalized_by": holder.finalized_by}
    except FileNotFoundError:
        return {"ok": False, "error": "Project or draft not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_reopen_build(project_id: str, unit_id: str, individual_id: str, body: dict, paths: AppPaths) -> dict:
    try:
        reason = str(body.get("reason") or "").strip()
        if len(reason) < 3:
            return {"ok": False, "error": "A brief reopen reason is required"}
        project = load_project(project_id, paths)
        _, holder, error = _target(project, unit_id, individual_id)
        if error:
            return {"ok": False, "error": error}
        now = _utcnow()
        holder.status = "reopened"
        holder.reopened_at = now
        holder.reopened_by = _current_user_display_name() or "Local User"
        holder.reopen_reason = reason
        save_project(project, paths)
        return {"ok": True, "status": holder.status, "reopened_at": now, "reopened_by": holder.reopened_by}
    except FileNotFoundError:
        return {"ok": False, "error": "Project not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def finalized_owner_for_draft(draft_id: str, paths: AppPaths) -> dict | None:
    """Return the finalized project target owning a draft, if any."""
    for project in list_projects(paths):
        for unit in project.build_units:
            if not unit.individuals and unit.draft_id == draft_id and unit.status == "finalized":
                return {"project_id": project.project_id, "unit_id": unit.unit_id, "individual_id": ""}
            for individual in unit.individuals:
                if individual.draft_id == draft_id and individual.status == "finalized":
                    return {
                        "project_id": project.project_id,
                        "unit_id": unit.unit_id,
                        "individual_id": individual.individual_id,
                    }
    return None
