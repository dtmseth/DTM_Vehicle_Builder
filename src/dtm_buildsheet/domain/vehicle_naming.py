"""Canonical human-readable identity for one physical vehicle build."""
from __future__ import annotations

import re

from .agency_naming import effective_agency_abbreviation
from .project_models import BuildUnit, IndividualUnit, ProjectRecord


def vin_last_six(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()
    return normalized[-6:]


def _without_leading_year(value: str) -> str:
    return re.sub(r"^\s*(?:19|20)\d{2}\s+", "", str(value or "")).strip()


def _short_model_value(value: str, make: str = "") -> str:
    raw = _without_leading_year(value)
    folded = raw.casefold().replace("_", " ")
    known_models = (
        ("PIU", ("piu", "pi utility", "police interceptor utility")),
        ("Lightning", ("f-150 lightning", "f150 lightning", "lightning")),
        ("F-150", ("f-150", "f150")),
        ("Durango", ("durango",)),
        ("Traverse", ("traverse",)),
        ("Tahoe", ("tahoe",)),
    )
    for label, aliases in known_models:
        if any(alias in folded for alias in aliases):
            return label
    normalized_make = _without_leading_year(make)
    makes = tuple(filter(None, (
        normalized_make, "Chevrolet", "Chevy", "Dodge", "Ford", "GMC", "Ram",
    )))
    for make_name in makes:
        if raw.casefold().startswith(make_name.casefold() + " "):
            raw = raw[len(make_name):].strip()
            break
    return raw.title() if raw.isupper() else raw


def vehicle_model_label(build_unit: BuildUnit, individual: IndividualUnit | None = None) -> str:
    make = getattr(individual, "make", "") if individual else ""
    configured_model = _short_model_value(build_unit.vehicle_model)
    individual_model = _short_model_value(
        getattr(individual, "model", "") if individual else "", make,
    )
    return configured_model or individual_model or "Vehicle"


def project_agency_abbreviation(project: ProjectRecord) -> str:
    customer = getattr(project, "customer", None)
    return effective_agency_abbreviation(
        getattr(customer, "agency_abbreviation", ""),
        getattr(customer, "agency", ""),
    )


def project_year_folder_name(project: ProjectRecord) -> str:
    return safe_vehicle_folder_name(" - ".join(filter(None, (
        project_agency_abbreviation(project),
        str(project.customer.build_year or "").strip(),
    ))))


def unit_group_name(project: ProjectRecord, build_unit: BuildUnit) -> str:
    """Readable folder label for one model/build-type group."""
    prefix = " ".join(filter(None, (
        str(project.customer.build_year or "").strip(),
        project_agency_abbreviation(project),
        vehicle_model_label(build_unit),
    )))
    build_type = str(build_unit.build_type or "").strip()
    suffix = f"{build_type} Build(s)" if build_type else "Build(s)"
    return safe_vehicle_folder_name(" - ".join(filter(None, (prefix, suffix))))


def vehicle_identifier_parts(individual: IndividualUnit | None) -> list[str]:
    if individual is None:
        return []
    # Existing/trade-in identifiers describe source history, not the vehicle
    # being built. They must never become card, folder, filename, or QBO
    # identity, even when the actual identifier is not known yet.
    unit_number = str(getattr(individual, "unit_number", "") or "").strip()
    vin = vin_last_six(getattr(individual, "vin", ""))
    parts = []
    if unit_number:
        parts.append(f"Unit {unit_number}")
    if vin:
        parts.append(f"VIN {vin}")
    return parts


def vehicle_placeholder_identifier(
    individual: IndividualUnit | None,
    *,
    ordinal: int = 1,
) -> str:
    """Stable readable identity for a legacy vehicle missing unit/VIN data.

    The token is derived from ``individual_id``, which is already the durable
    vehicle association. If a VIN arrives later, folder reconciliation moves
    this same stored SharePoint item to the real canonical name.
    """
    raw_id = str(getattr(individual, "individual_id", "") or "")
    token = re.sub(r"[^A-Za-z0-9]+", "", raw_id).upper()[:8]
    return f"Pending ID {token or f'{ordinal:04d}'}"


def vehicle_identity_ready(individual: IndividualUnit | None) -> bool:
    return bool(individual is not None and vehicle_identifier_parts(individual))


def vehicle_name_parts(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit | None,
    *,
    ordinal: int = 1,
) -> list[str]:
    year = str(project.customer.build_year or getattr(individual, "year", "") or "").strip()
    head = " ".join(filter(None, [
        year,
        project_agency_abbreviation(project),
        vehicle_model_label(build_unit, individual),
    ]))
    build_type = str(getattr(build_unit, "build_type", "") or "").strip()
    identifiers = vehicle_identifier_parts(individual)
    if not identifiers and individual is None:
        identifiers = ["Group Build"]
    elif not identifiers:
        identifiers = [vehicle_placeholder_identifier(individual, ordinal=ordinal)]
    return [part for part in [head or "Vehicle", build_type, *identifiers] if part]


def vehicle_display_name(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit | None,
    *,
    ordinal: int = 1,
) -> str:
    return " - ".join(vehicle_name_parts(project, build_unit, individual, ordinal=ordinal))


def individual_new_vehicle_block(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
) -> dict[str, str]:
    """Return current-build metadata for generated customer output.

    The project build year remains authoritative for the new vehicle. Existing
    or replaced-vehicle fields are deliberately handled by the separate helper
    below so they can never leak into current identity or naming.
    """
    build_year = str(project.customer.build_year or individual.year or "").strip()
    return {
        "YEAR": build_year,
        "MAKE": str(individual.make or "").strip(),
        "MODEL": str(individual.model or build_unit.vehicle_model or "").strip(),
        "COLOR": str(individual.color or "").strip(),
        "UNIT ID": str(individual.unit_number or "").strip(),
        "VIN": str(individual.vin or "").strip(),
    }


def individual_existing_vehicle_block(individual: IndividualUnit) -> dict[str, str]:
    """Return optional display metadata for the vehicle being replaced.

    These fields may appear in the dedicated Existing Vehicle card, but no
    caller may use them for folders, filenames, export stems, or QBO identity.
    """
    values = {
        "YEAR": str(individual.existing_year or "").strip(),
        "MAKE": str(individual.existing_make or "").strip(),
        "MODEL": str(individual.existing_model or "").strip(),
        "BUILD TYPE": str(individual.existing_build_type or "").strip(),
        "UNIT ID": str(individual.existing_unit_number or "").strip(),
        "VIN": str(individual.existing_vin or "").strip(),
    }
    return {key: value for key, value in values.items() if value}


def refresh_individual_vehicle_info(
    info: dict,
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
    *,
    ordinal: int = 1,
) -> dict:
    """Refresh project-owned vehicle facts in a draft/output info mapping."""
    refreshed = dict(info or {})
    refreshed["BuildYear"] = str(project.customer.build_year or "").strip()
    refreshed["BuildType"] = str(build_unit.build_type or "").strip()
    refreshed["UnitNotes"] = str(individual.notes or "").strip()
    refreshed["CanonicalVehicleName"] = vehicle_display_name(
        project, build_unit, individual, ordinal=ordinal,
    )
    refreshed["NewVehicle"] = individual_new_vehicle_block(
        project, build_unit, individual,
    )
    refreshed["ExistingVehicle"] = individual_existing_vehicle_block(individual)
    return refreshed


def qb_project_name(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
    *,
    ordinal: int = 1,
) -> str:
    # Keep the agency abbreviation even though QBO also shows the parent
    # Customer: copied names and search results must remain self-identifying.
    return " | ".join(vehicle_name_parts(project, build_unit, individual, ordinal=ordinal))


def safe_vehicle_folder_name(value: str) -> str:
    # Ampersands are valid on Windows, macOS, OneDrive, and SharePoint. Keep
    # them readable; only actual cross-target path/reserved characters fold.
    cleaned = re.sub(r"[~\"#%*:<>?/\\{|}]+", " ", str(value or ""))
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned[:120] or "Unidentified Vehicle"


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[\s/\\]+", "_", str(value or "").strip())
    cleaned = re.sub(r"[^\w-]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    return cleaned or "Unknown"


def vehicle_folder_name(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
    *,
    ordinal: int = 1,
) -> str:
    return safe_vehicle_folder_name(
        vehicle_display_name(project, build_unit, individual, ordinal=ordinal)
    )


def vehicle_label_from_project_info(project: dict) -> str:
    explicit = str(project.get("CanonicalVehicleName") or "").strip()
    if explicit:
        return explicit
    new_vehicle = project.get("NewVehicle") or {}
    old_vehicle = project.get("ExistingVehicle") or {}
    year = str(project.get("BuildYear") or new_vehicle.get("YEAR") or old_vehicle.get("YEAR") or "").strip()
    model = _short_model_value(
        project.get("VehicleType") or new_vehicle.get("MODEL") or old_vehicle.get("MODEL") or "Vehicle"
    )
    unit_number = str(
        new_vehicle.get("UNIT ID") or new_vehicle.get("UNIT") or ""
    ).strip()
    vin = vin_last_six(new_vehicle.get("VIN") or "")
    identifiers = []
    if unit_number and unit_number.casefold() != "group build":
        identifiers.append(f"Unit {unit_number}")
    if vin:
        identifiers.append(f"VIN {vin}")
    if not identifiers:
        identifiers.append(unit_number or "Group Build")
    agency = str(project.get("Agency") or "").strip()
    abbreviation = effective_agency_abbreviation(
        project.get("AgencyAbbreviation") or "", agency,
    )
    build_type = str(project.get("BuildType") or "").strip()
    return " - ".join(filter(None, [
        " ".join(filter(None, [year, abbreviation, model])) or "Vehicle",
        build_type,
        *identifiers,
    ]))


def project_info_export_stem(project: dict) -> str:
    vehicle = safe_filename_part(vehicle_label_from_project_info(project).replace(" - ", " "))
    return vehicle


def vehicle_export_stem(
    project: ProjectRecord,
    build_unit: BuildUnit,
    individual: IndividualUnit,
    *,
    ordinal: int = 1,
) -> str:
    return safe_filename_part(
        vehicle_display_name(project, build_unit, individual, ordinal=ordinal).replace(" - ", " ")
    )
