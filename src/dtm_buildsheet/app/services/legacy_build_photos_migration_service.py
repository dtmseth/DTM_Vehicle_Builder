"""Reviewed, resumable migration for the legacy Shop Build Photos tree.

This module contains the explicit owner-reviewed aliases and sparse build
translations for the one-time production migration.  It never deletes or
moves a source item.  Deterministic project/unit IDs make project creation
idempotent without adding migration-only fields to the normal project schema.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from ...domain.agency_models import AgencyRecord
from ...domain.agency_naming import effective_agency_abbreviation
from ...domain.project_models import BuildUnit, CustomerInfo, IndividualUnit
from ...inputs.project_entry import list_projects, new_project, save_project
from ...paths import AppPaths
from . import agency_service
from .shared_work_service import mirror_project_to_cloud, save_setting_to_cloud


_MIGRATION_NAMESPACE = uuid.UUID("a824fdd8-f22f-4d6e-9aaa-845a74d884f8")
JOINT_AGENCY_NAME = "Benton-Stearns Negotiator Van"
JOINT_AGENCY_ABBREVIATION = "BSNV"
JOINT_AGENCY_ID = str(uuid.uuid5(_MIGRATION_NAMESPACE, f"agency:{JOINT_AGENCY_NAME}"))
MIGRATION_ACTOR = "Legacy Build Photos migration"


@dataclass(frozen=True)
class LegacyPhotoGroup:
    source_path: str
    source_agency: str
    agency_name: str
    build_year: str
    vehicle_model: str
    build_type: str = ""


def _group(
    category: str,
    source_agency: str,
    folder: str,
    agency_name: str,
    year: str,
    model: str,
    build_type: str = "",
) -> LegacyPhotoGroup:
    return LegacyPhotoGroup(
        source_path=f"Build Photos/{category}/{source_agency}/{folder}",
        source_agency=source_agency,
        agency_name=agency_name,
        build_year=year,
        vehicle_model=model,
        build_type=build_type,
    )


LEGACY_PHOTO_GROUPS: tuple[LegacyPhotoGroup, ...] = (
    _group("Fire Builds", "Cohasset FD", "'26 CFD Truck", "Cohasset Fire Department", "2026", "Vehicle", "Truck"),
    _group("Fire Builds", "Foley FD", "'25 Foley Grass Rig", "Foley Fire Department", "2025", "Vehicle", "Grass Rig"),
    _group("Fire Builds", "Grand Rapids FD", "'26 GRFD Chevy 3500", "Grand Rapids Fire Department", "2026", "3500"),
    _group("Fire Builds", "Little Falls FD", "'25 LFFD F-150 Chief Truck", "Little Falls Fire Department", "2025", "F-150", "Chief Truck"),
    _group("Fire Builds", "Little Falls FD", "'25 LFFD GMC Grass Rig", "Little Falls Fire Department", "2025", "Vehicle", "Grass Rig"),
    _group("Fire Builds", "Pequot Lakes FD", "'25 PLFD F-550 Rescue Truck", "Pequot Lakes Fire Department", "2025", "F-550", "Rescue Truck"),
    _group("Fire Builds", "Pequot Lakes FD", "'25 PLFD Grass Rig", "Pequot Lakes Fire Department", "2025", "Vehicle", "Grass Rig"),
    _group("Fire Builds", "Sartell FD", "'25 SFD Expedition Command", "Sartell Fire Department", "2025", "Expedition", "Command"),
    _group("Fire Builds", "Sartell FD", "'25 SFD Lightnings", "Sartell Fire Department", "2025", "F-150 Lightning"),
    _group("Fire Builds", "Sartell FD", "'26 SFD Chief Truck", "Sartell Fire Department", "2026", "Vehicle", "Chief Truck"),
    _group("Other Builds", "City of Otsego", "'26 Otsego Truck Rack", "City of Otsego", "2026", "Vehicle", "Truck Rack"),
    LegacyPhotoGroup(
        source_path="Build Photos/Police Builds/Benton-Stearns Negotiator Van",
        source_agency="Benton-Stearns Negotiator Van",
        agency_name=JOINT_AGENCY_NAME,
        build_year="2025",
        vehicle_model="Van",
        build_type="Negotiator",
    ),
    _group("Police Builds", "Brainerd PD", "'25 BPD Utility", "Brainerd Police Department", "2025", "PIU"),
    _group("Police Builds", "Brainerd PD", "'26 BPD Tahoes", "Brainerd Police Department", "2026", "Tahoe"),
    _group("Police Builds", "City of Blaine", "'25 Blaine Utility", "City of Blaine", "2025", "PIU"),
    _group("Police Builds", "Cottage Grove PD", "'25 CGPD Durangos", "Cottage Grove Police Department", "2025", "Durango"),
    _group("Police Builds", "Cottage Grove PD", "'26 CGPD Jeep", "Cottage Grove Police Department", "2026", "Jeep"),
    _group("Police Builds", "Edina PD", "'25 EPD Blazer EVs", "Edina Police Department", "2025", "Blazer EV"),
    _group("Police Builds", "Edina PD", "'25 EPD K-9", "Edina Police Department", "2025", "Vehicle", "K-9"),
    _group("Police Builds", "Edina PD", "'25 EPD Lightning", "Edina Police Department", "2025", "F-150 Lightning"),
    _group("Police Builds", "Grand Rapids PD", "'25 GRPD Durangos", "Grand Rapids Police Department", "2025", "Durango"),
    _group("Police Builds", "Grand Rapids PD", "'26 GRPD Durango", "Grand Rapids Police Department", "2026", "Durango"),
    _group("Police Builds", "Kandiyohi County Sheriff", "'25 Kandi Durangos", "Kandiyohi County Sheriff's Office", "2025", "Durango"),
    _group("Police Builds", "Melrose PD", "'26 MPD Durango", "City of Melrose", "2026", "Durango"),
    _group("Police Builds", "Melrose PD", "'26 MPD F-150", "City of Melrose", "2026", "F-150"),
    _group("Police Builds", "Mille Lacs County Sheriff", "'26 Silverado", "Mille Lacs County Sheriff", "2026", "Silverado"),
    _group("Police Builds", "Minneapolis PD", "'25 MPD Harley's", "Minneapolis Police Department", "2025", "Harley"),
    _group("Police Builds", "Nisswa PD", "'26 NPD Utility", "Nisswa Police Department", "2026", "PIU"),
    _group("Police Builds", "Prairie County Sheriff", "'25 Prairie Co Ram 1500", "Prairie County Sheriff", "2025", "Ram 1500"),
    _group("Police Builds", "Prairie County Sheriff", "'26 Prairie Co Durangos", "Prairie County Sheriff", "2026", "Durango"),
    _group("Police Builds", "Proctor PD", "'26 PPD PIU", "Proctor Police Department", "2026", "PIU"),
    _group("Police Builds", "Royalton PD", "'25 RPD Tahoe", "Royalton Police Department", "2025", "Tahoe"),
    _group("Police Builds", "Sartell PD", "'25 Sartell Blazer EVs", "Sartell Police Department", "2025", "Blazer EV"),
    _group("Police Builds", "Sartell PD", "'25 Sartell Mach-E", "Sartell Police Department", "2025", "Mach-E"),
    _group("Police Builds", "Sauk Rapids PD", "'25 SRPD F-150", "Sauk Rapids Police Department", "2025", "F-150"),
    _group("Police Builds", "Sauk Rapids PD", "'25 SRPD Utility '25", "Sauk Rapids Police Department", "2025", "PIU"),
    _group("Police Builds", "St. Cloud PD", "'26 SCPD Chevy Traverse", "St. Cloud Police Department", "2026", "Traverse"),
    _group("Police Builds", "St. Cloud PD", "'26 SCPD PIU Full Cage", "St. Cloud Police Department", "2026", "PIU", "Full Cage"),
    _group("Police Builds", "St. Cloud PD", "'26 SCPD PIU Half Cage (Troy)", "St. Cloud Police Department", "2026", "PIU", "Half Cage (Troy)"),
    _group("Police Builds", "St. Joe PD", "'25 SJPD Tahoe", "St. Joseph Police Department", "2025", "Tahoe"),
    _group("Police Builds", "St. Joe PD", "'26 SJPD Explorer", "St. Joseph Police Department", "2026", "PIU"),
    _group("Police Builds", "Stearns County Sheriff", "'25 Stearns K-9", "Stearns County Sheriff", "2025", "Vehicle", "K-9"),
    _group("Police Builds", "Stearns County Sheriff", "'25 Stearns Utility", "Stearns County Sheriff", "2025", "PIU"),
    _group("Police Builds", "Walsh County Sheriff", "'25 Walsh Tahoe & Silverado", "Walsh County Sheriff", "2025", "Tahoe & Silverado"),
    _group("Police Builds", "Yellow Medicine County", "'25 YMC Tahoes", "Yellow Medicine County Sheriff's Office", "2025", "Tahoe"),
    _group("Police Builds", "Yellow Medicine County", "'26 YMC Durangos", "Yellow Medicine County Sheriff's Office", "2026", "Durango"),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(_MIGRATION_NAMESPACE, f"{kind}:{value}"))


def resolve_agencies(paths: AppPaths) -> dict[str, AgencyRecord]:
    """Resolve every reviewed target name to exactly one durable agency."""
    by_name: dict[str, list[AgencyRecord]] = {}
    for agency in agency_service.load_agencies(paths):
        by_name.setdefault(agency.name.strip().casefold(), []).append(agency)
    resolved: dict[str, AgencyRecord] = {}
    for group in LEGACY_PHOTO_GROUPS:
        matches = by_name.get(group.agency_name.casefold(), [])
        if len(matches) != 1:
            raise ValueError(
                f"Expected one saved agency named {group.agency_name!r}; found {len(matches)}"
            )
        resolved[group.agency_name] = matches[0]
    return resolved


def ensure_joint_agency(paths: AppPaths, *, mirror_to_cloud: bool) -> tuple[AgencyRecord, bool]:
    """Create the approved joint agency without touching QuickBooks."""
    records = agency_service._records(paths)  # noqa: SLF001
    matches = [
        agency for agency in records.values()
        if agency.name.strip().casefold() == JOINT_AGENCY_NAME.casefold()
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple agencies already use {JOINT_AGENCY_NAME!r}")
    created = not matches
    if matches:
        agency = matches[0]
        if agency.agency_id != JOINT_AGENCY_ID:
            # A user-created durable identity wins; deterministic IDs are only
            # used when the reviewed migration creates the record itself.
            pass
        if agency.abbreviation and agency.abbreviation != JOINT_AGENCY_ABBREVIATION:
            raise ValueError("The existing joint agency has a different abbreviation")
        if not agency.abbreviation:
            agency.abbreviation = JOINT_AGENCY_ABBREVIATION
            agency.updated_at = _utcnow()
            agency_service._write_record(agency, paths)  # noqa: SLF001
    else:
        now = _utcnow()
        agency = AgencyRecord(
            agency_id=JOINT_AGENCY_ID,
            name=JOINT_AGENCY_NAME,
            abbreviation=JOINT_AGENCY_ABBREVIATION,
            created_at=now,
            updated_at=now,
        )
        records[agency.agency_id] = agency
        agency_service._write_record(agency, paths)  # noqa: SLF001
    if mirror_to_cloud:
        import json
        payload = json.dumps(asdict(agency), indent=2) + "\n"
        if not save_setting_to_cloud(f"agencies/{agency.agency_id}.json", payload):
            raise RuntimeError("The joint agency could not be mirrored to SharePoint")
    return agency, created


def desired_agency_names(paths: AppPaths) -> set[str]:
    """Names whose Company/Shop roots must survive mistaken-root cleanup."""
    names = {
        project.customer.agency.strip()
        for project in list_projects(paths)
        if project.customer.agency.strip()
    }
    names.update(group.agency_name for group in LEGACY_PHOTO_GROUPS)
    return names


def create_completed_projects(
    paths: AppPaths,
    *,
    completed_at: str | None = None,
    mirror_to_cloud: bool = False,
) -> dict:
    """Create/reuse ordinary agency-year projects and sparse build units."""
    agencies = resolve_agencies(paths)
    existing_by_key: dict[tuple[str, str], list] = {}
    for project in list_projects(paths):
        key = (project.customer.agency_id, str(project.customer.build_year).strip())
        if all(key):
            existing_by_key.setdefault(key, []).append(project)
    duplicates = {key: rows for key, rows in existing_by_key.items() if len(rows) > 1}
    if duplicates:
        raise ValueError(f"Duplicate agency/year projects block migration: {sorted(duplicates)}")

    timestamp = completed_at or _utcnow()
    groups_by_key: dict[tuple[str, str], list[LegacyPhotoGroup]] = {}
    for group in LEGACY_PHOTO_GROUPS:
        agency = agencies[group.agency_name]
        groups_by_key.setdefault((agency.agency_id, group.build_year), []).append(group)

    created: list[str] = []
    updated: list[str] = []
    targets: dict[str, dict[str, str]] = {}
    for key, groups in sorted(groups_by_key.items()):
        agency = agencies[groups[0].agency_name]
        existing = existing_by_key.get(key, [])
        if existing:
            project = existing[0]
            if project.project_status != "completed":
                raise ValueError(
                    f"Active project {project.project_id} already owns {agency.name} {key[1]}"
                )
        else:
            project_id = _stable_id("project", f"{agency.agency_id}:{key[1]}")
            project = new_project(
                project_id=project_id,
                customer=CustomerInfo(
                    name=agency.name,
                    agency=agency.name,
                    agency_id=agency.agency_id,
                    agency_abbreviation=effective_agency_abbreviation(
                        agency.abbreviation, agency.name,
                    ),
                    build_year=key[1],
                ),
                preferences=copy.deepcopy(agency.default_preferences),
            )
            project.project_status = "completed"
            project.completed_at = timestamp
            project.completed_by = MIGRATION_ACTOR
            created.append(project.project_id)

        changed = not existing
        unit_ids = {unit.unit_id for unit in project.build_units}
        for group in groups:
            unit_id = _stable_id("unit", group.source_path)
            individual_id = _stable_id("individual", group.source_path)
            if unit_id not in unit_ids:
                project.build_units.append(BuildUnit(
                    unit_id=unit_id,
                    vehicle_model=group.vehicle_model,
                    build_type=group.build_type,
                    quantity=1,
                    individuals=[IndividualUnit(
                        individual_id=individual_id,
                        year=group.build_year,
                        model=group.vehicle_model,
                    )],
                ))
                unit_ids.add(unit_id)
                changed = True
            unit = next(item for item in project.build_units if item.unit_id == unit_id)
            if (
                unit.vehicle_model != group.vehicle_model
                or unit.build_type != group.build_type
                or len(unit.individuals) != 1
                or unit.individuals[0].individual_id != individual_id
            ):
                raise ValueError(f"Existing sparse build conflicts with {group.source_path}")
            targets[group.source_path] = {
                "project_id": project.project_id,
                "unit_id": unit_id,
                "individual_id": individual_id,
            }

        if changed:
            save_path = save_project(project, paths)
            if project.project_id not in created:
                updated.append(project.project_id)
            if mirror_to_cloud and not mirror_project_to_cloud(project.project_id, save_path):
                raise RuntimeError(f"Project {project.project_id} could not be mirrored")

    return {
        "created": created,
        "updated": updated,
        "targets": targets,
        "project_count": len(groups_by_key),
        "group_count": len(LEGACY_PHOTO_GROUPS),
    }
