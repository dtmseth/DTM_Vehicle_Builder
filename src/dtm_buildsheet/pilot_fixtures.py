"""Synthetic local-pilot seeds. No user records, presets or provider config."""
from __future__ import annotations

import json
from pathlib import Path
import random
import shutil

CONFIG_NAMES = (
    "asset_manifest.json", "build_rules.json", "estimate_charges.json",
    "legacy_workbook_index.json", "part_catalog.json", "parts_db.json",
    "parts_library.json", "project_options.json", "vehicle_layouts.json", "workbook_rules.json",
)
ASSET_GROUPS = ("bumpers", "equipment", "lights", "vehicles")


def without_provider_metadata(value):
    """Keep render/catalog structure but remove live QBO linkage and audit data."""
    if isinstance(value, dict):
        return {key: without_provider_metadata(item) for key, item in value.items()
                if not key.startswith("qb_") and key not in {"audit_trail", "updated_by", "created_by"}}
    if isinstance(value, list):
        return [without_provider_metadata(item) for item in value]
    return value


def copy_render_resources(source: Path, target: Path):
    (target / "config").mkdir(parents=True, exist_ok=True)
    for name in CONFIG_NAMES:
        destination = target / "config" / name
        if not destination.exists():
            content = without_provider_metadata(json.loads((source / "config" / name).read_text()))
            if name == "parts_db.json":
                # These menu rules require live QB-linked refresh-kit SKUs;
                # they are unrelated to the synthetic render proof.
                content["system_cable_refreshes"] = {}
            destination.write_text(json.dumps(content, indent=2) + "\n")
    settings = target / "config" / "app_settings.json"
    if not settings.exists():
        settings.write_text(json.dumps({"schema_version": 1, "project_output_root": "",
                                       "template_save_dir": "", "output_save_dir": ""}) + "\n")
    for group in ASSET_GROUPS:
        for file in sorted((source / "assets" / group).rglob("*")):
            if file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg"} or not file.is_file():
                continue
            if file.is_symlink():
                raise ValueError("Pilot resources must not contain symlinks")
            destination = target / "assets" / file.relative_to(source / "assets")
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, destination)


def initialize_workspace(paths, *, seed: bool):
    for name in ("config", "assets", "input", "output", "drafts", "presets", "projects",
                 "agencies", "sales_reps", "reference_media"):
        (paths.workspace_dir / name).mkdir(parents=True, exist_ok=True)
    copy_render_resources(paths.resources_dir, paths.workspace_dir)
    # Never invoke ensure_workspace(), whose desktop seeds include live data.
    if seed and not (paths.workspace_dir / ".fixtures-seeded").exists():
        if any(paths.workspace_projects_dir.iterdir()) or any(paths.workspace_drafts_dir.iterdir()):
            raise ValueError("Refusing to seed over existing projects or drafts")
        seed_projects(paths)
        (paths.workspace_dir / ".fixtures-seeded").write_text("v1\n")


def seed_projects(paths):
    from PIL import Image, ImageDraw
    from .domain.project_models import (
        BuildUnit, IndividualUnit, CustomerInfo, BuildReferenceAsset, BuildReferenceAssignment,
    )
    from .inputs.project_entry import new_project, save_project
    from .inputs.project_drafts import DraftPart, new_draft, save_draft

    equipment = [
        ("Push Bumper", "SETINA", "PB450L", "PUSH BUMPER", 1, ""),
        ("Forward Warning 1", "WHELEN", "ION", "TOP TUBE", 4, "Red/White Blue/White"),
        ("Siren Speaker 1", "WHELEN", "SA315P", "BEHIND GRILL (CENTER)", 1, ""),
        ("Mirror Warning 1", "WHELEN", "U-SERIES", "UNDER MIRROR", 2, "Red Blue"),
        ("Side Warning 1", "WHELEN", "MEGA T-SERIES", "LOWER CARGO WINDOW", 2, "Red Blue"),
        ("Rear Warning 2", "WHELEN", "ION", "LICENSE PLATE BRACKET", 2, "Red Blue"),
        ("Lower Lift Gate Warning", "WHELEN", "ION", "LOWER LIFTGATE LIP", 2, "Red Blue"),
        ("Light Controller", "WHELEN", "CORE", "ON EQUIPMENT TRAY", 1, ""),
        ("Control Head", "WHELEN", "CCTL6", "IN CENTER CONSOLE", 1, ""),
        ("Radio 1", "MOTOROLA", "SPLIT UNIT", "ON EQUIPMENT TRAY", 1, ""),
        ("Radio Antenna Top", "MOTOROLA", "WHIP STYLE", "REAR LEFT ROOF", 1, ""),
        ("Harness", "SYNTHETIC", "COMPLETE SQUAD HARNESS", "", 1, ""),
    ]
    for label, extra_count, photo_count in (("typical", 0, 0), ("dense", 80, 12)):
        agency = f"Synthetic {label.title()} Police Department"
        project_id = f"pilot-{label}"
        unit_id, individual_id = f"{label}-group", f"{label}-vehicle"
        parts = [DraftPart(name=name, manufacturer=brand, part_number=sku, location=location,
                           quantity=qty, raw_color=color, line_id=f"{label}-part-{index}",
                           comment="Synthetic installation example.")
                 for index, (name, brand, sku, location, qty, color) in enumerate(equipment)]
        for part, part_type in zip(parts, (
            "push_bumper", "warning_light", "siren_speaker", "warning_light", "warning_light",
            "warning_light", "warning_light", "light_controller", "control_head", "radio_brick",
            "radio_antenna_top", "harness",
        )):
            part.part_type = part_type
        for index in range(extra_count):
            parts.append(DraftPart(name="Harness", manufacturer="SYNTHETIC",
                                   part_number=f"TEST-HARNESS-{index:03}", quantity=1,
                                   line_id=f"dense-extra-{index}",
                                   comment=f"Circuit {index + 1:02}: route behind trim, label both ends, "
                                           "protect from abrasion and document the fuse position."))
        draft = new_draft(vehicle_info={
            "VehicleType": "PIU", "Agency": agency, "BuildYear": "2026",
            "ProjectID": project_id, "BuildType": "Patrol", "SalesRep": "Synthetic Rep",
            "NewVehicle": {"MODEL": "2026 Ford Police Interceptor Utility", "YEAR": "2026",
                           "UNIT ID": "TEST-01", "COLOR": "Black", "VIN": ""},
        }, parts=parts)
        draft.draft_id = f"pilot-{label}-draft"
        draft.notes = {"INSTALLATION NOTES": ["Synthetic fixture. Verify all equipment labels and mounting positions."]}
        save_draft(draft, paths.workspace_drafts_dir)
        individual = IndividualUnit(individual_id=individual_id, unit_number="TEST-01", year="2026",
                                    make="Ford", model="Police Interceptor Utility", color="Black",
                                    draft_id=draft.draft_id, notes="Local pilot test vehicle.")
        project = new_project(project_id=project_id, build_units=[BuildUnit(
            unit_id=unit_id, vehicle_model="Ford Police Interceptor Utility", build_type="Patrol",
            individuals=[individual],
        )])
        project.customer = CustomerInfo(agency=agency, agency_id=f"pilot-{label}-agency",
                                        agency_abbreviation=f"S{label[0].upper()}PD", build_year="2026")
        project.project_notes = "Synthetic export proof only. No production records or connections."
        for index in range(photo_count):
            reference_id = f"pilot-photo-{index:02}"
            filename = f"Synthetic-{index + 1:02}.jpg"
            folder = paths.workspace_reference_cache_dir / reference_id
            folder.mkdir(parents=True, exist_ok=True)
            size = (1600, 2400) if index % 3 == 0 else (2400, 1600)
            rng = random.Random(index)
            # Deterministic photographic-size noise makes compression/memory
            # experiments meaningful without using anyone's actual photographs.
            image = Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
            draw = ImageDraw.Draw(image)
            draw.rectangle((30, 30, size[0] - 30, 190), fill="white")
            draw.text((55, 65), f"SYNTHETIC REFERENCE {index + 1:02}", fill="black", font_size=60)
            image.save(folder / filename, quality=88)
            image.close()
            project.reference_assets.append(BuildReferenceAsset(
                reference_id=reference_id, file_name=filename,
                assignments=[BuildReferenceAssignment(scope="unit_group", target_id=unit_id,
                                                       note=f"Synthetic mounting example {index + 1}.",
                                                       sort_order=index)],
            ))
        save_project(project, paths)
        (paths.workspace_dir / "agencies" / f"pilot-{label}-agency.json").write_text(json.dumps({
            "agency_id": f"pilot-{label}-agency", "name": agency,
            "abbreviation": project.customer.agency_abbreviation,
        }) + "\n")
