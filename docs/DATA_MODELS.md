# Data Models

All dataclasses live in `src/dtm_buildsheet/domain/`.

## CustomerInfo

```python
@dataclass
class CustomerInfo:
    name: str = ""
    agency: str = ""          # display name
    agency_id: str = ""       # FK → agencies/{id}.json
    sales_rep_id: str = ""    # FK → sales_reps/{id}.json
    quote_number: str = ""
    build_year: str = ""        # canonical project year used in generated outputs
    notes: str = ""
```

## EquipmentPreferences

```python
@dataclass
class EquipmentPreferences:
    lighting_brands: list[str] = field(default_factory=list)  # one choice in the current UI
    camera_brand: str = ""
    push_bumper_brand: str = ""
    cage_brand: str = ""
    console_brand: str = ""
    slick_top: bool = False
    notes: str = ""
```

## BuildUnit

```python
@dataclass
class BuildUnit:
    vehicle_model: str = ""
    build_type: str = ""
    quantity: int = 1
    preset_id: str = ""
    individuals: list = field(default_factory=list)
```

## IndividualUnit

```python
@dataclass
class IndividualUnit:
    unit_number: str = ""
    vin: str = ""
    year: str = ""             # per-vehicle/model year; fallback metadata, not project build year
    color: str = ""
    draft_id: str = ""
    output_path: str = ""     # set when build sheet is generated
```

## ProjectRecord

```python
@dataclass
class ProjectRecord:
    project_id: str = ""
    customer: CustomerInfo = field(default_factory=CustomerInfo)
    preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    build_units: list[BuildUnit] = field(default_factory=list)
    project_notes: str = ""   # shown on every build's final PowerPoint page
    export_dir: str = ""      # empty = default output location
    created_at: str = ""
    updated_at: str = ""
```

Projects are stored in `workspace/projects/{project_id}/project.json` (one subdirectory per
project). The subdirectory layout lets future artifacts (generated PPTX, draft snapshots) sit
alongside the record without polluting a flat list.

## AgencyRecord

Lives in `workspace/agencies/{agency_id}.json`. Mirrored to SharePoint.
Carries optional `qb_customer_id` (FK → QuickBooks `Customer.Id`).
Contact info comes from the agency record — no separate contact field on the project.
`default_preferences` stores the agency's normal equipment choices. They are copied to a new
project once; editing a project never changes the agency defaults or another project's choices.
`pricing_overrides` is a sparse `manufacturer_id → percent off list` map. An empty map inherits
the shared Default customer-pricing rule; only values that differ from Default are stored.

## SalesRepRecord

Lives in `workspace/sales_reps/{rep_id}.json`. Mirrored to SharePoint.

## Core domain models

| File | Contents |
|------|----------|
| `domain/input_models.py` | `ProjectInput`, `PartInput` |
| `domain/plan_models.py` | `BuildPlan`, `PlannedPart`, `PlannedPlacement`, `PlannedInstance` |
| `domain/project_models.py` | `ProjectRecord`, `CustomerInfo`, `EquipmentPreferences`, `BuildUnit`, `IndividualUnit` |
| `domain/agency_models.py` | `AgencyRecord` |
| `domain/sales_rep_models.py` | `SalesRepRecord` |
| `domain/geometry.py` | Shared placement math (single source of truth) |
| `domain/rules.py` | Rule dataclasses |

## Agency & Sales Rep storage

Per-record JSON files under workspace subdirectories, each mirroring a SharePoint `/Settings/` folder:
- `workspace/agencies/{agency_id}.json` ↔ `Settings/agencies/{agency_id}.json`
- `workspace/sales_reps/{rep_id}.json` ↔ `Settings/sales_reps/{rep_id}.json`

The legacy flat-file form (`workspace/agencies.json`, `workspace/sales_reps.json`) exists only
as a one-shot migration source for older installs; on first read, services rewrite each entry
into the per-record dir and forget the flat file.

Agency search uses `difflib.get_close_matches` after normalizing common abbreviations
(PD→police department, SO→sheriff's office, St.→saint, etc.).

The project wizard has live-search combos for agency and sales rep fields. Saves and deletes
hit SharePoint directly via `save_setting_to_cloud_in_background` and
`delete_setting_from_cloud`.
