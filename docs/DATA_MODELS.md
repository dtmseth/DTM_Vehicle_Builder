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
    sales_rep: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""
```

## EquipmentPreferences

```python
@dataclass
class EquipmentPreferences:
    lighting_brands: list[str] = field(default_factory=list)  # one choice in the current UI
    lighting_mode: str = "duo"  # duo | trio; defaults compatible picker SKUs, never limits choices
    camera_brand: str = ""
    push_bumper_brand: str = ""
    cage_brand: str = ""
    console_brand: str = ""
    slick_top: bool = False
    mixed_brands: bool = False
    notes: str = ""
    lens: str = ""              # clear | colored | smoked
```

## BuildUnit

```python
@dataclass
class BuildUnit:
    unit_id: str
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
    individual_id: str         # durable identity; never derive associations from unit number
    unit_number: str = ""
    vin: str = ""
    year: str = ""             # per-vehicle/model year; fallback metadata, not project build year
    color: str = ""
    draft_id: str = ""
    output_path: str = ""     # set when build sheet is generated
    notes: str = ""           # prominent shop note on Overview; long notes open in a modal
    pdf_path: str = ""
    status: str = "draft"     # draft | finalized | reopened
    finalized_at: str = ""
    finalized_by: str = ""
    finalized_draft_fingerprint: str = ""
    final_check_version: str = ""
    finalization_acknowledgements: list = field(default_factory=list)
    reopened_at: str = ""
    reopened_by: str = ""
    reopen_reason: str = ""
    qb_project_id: str = ""
    qb_project_name: str = ""
    qb_estimate_id: str = ""
    qb_estimate_snapshot: dict = field(default_factory=dict)  # Builder-owned QBO fields at last write
    qb_estimate_snapshot_at: str = ""
```

`BuildUnit` carries the same additive finalization fields for projects whose build is represented by
the unit itself rather than an `IndividualUnit`. Finalized draft mutations are rejected in the draft
service until the owning build is explicitly reopened with an actor and reason.
The Estimate snapshot is deliberately narrower than the raw QBO object: it tracks the customer /
project references, document number, memo fields, and material line IDs, descriptions, quantities,
prices, and amounts. Provider metadata such as `SyncToken` and update timestamps is excluded so it
does not create false conflicts.

## ProjectRecord

```python
@dataclass
class ProjectRecord:
    project_id: str
    created_at: str
    updated_at: str
    customer: CustomerInfo = field(default_factory=CustomerInfo)
    preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    build_units: list[BuildUnit] = field(default_factory=list)
    project_notes: str = ""   # shown on every build's final PowerPoint page
```

Projects are stored in `workspace/projects/{project_id}/project.json` (one subdirectory per
project) and mirrored to SharePoint. Drafts remain durable records keyed by `draft_id`. Generated
customer PDFs and internal PPTX sources use the configured output trees; record-side output paths
are compatibility locators, not a per-project `export_dir` setting.

## AgencyRecord

Lives in `workspace/agencies/{agency_id}.json`. Mirrored to SharePoint.
Carries optional `qb_customer_id` (FK → QuickBooks `Customer.Id`).
Contact info comes from the agency record — no separate contact field on the project.
`default_preferences` stores the agency's normal equipment choices. They are copied to a new
project once; editing a project never changes the agency defaults or another project's choices.
`pricing_overrides` is a sparse `manufacturer_id → percent off list` map. An empty map inherits
the shared Retail customer-pricing rule; only values that differ from Retail are stored.

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
| `domain/supply.py` | Canonical supply normalization, legacy mapping, validation, and labels |

### Part supply fields

`PartInput`, `DraftPart`, and guided component dictionaries carry these canonical fields:

| Field | Values | Meaning |
|---|---|---|
| `supply_type` | `new`, `customer_supplied` | Who supplies/bills the part |
| `customer_condition` | blank, `new`, `used` | Condition of a customer-supplied part |
| `customer_source` | string | Required source for explicitly edited customer-supplied/used data |

The legacy `new_or_used` and `source` fields remain for read/write compatibility. Normalization is
additive and does not rewrite a draft merely because it was opened. Blank/New maps to canonical New;
Used/Reused maps to customer-supplied/used. Source-less legacy used data is permitted on read and
flagged for repair, while canonical saves validate the source.

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
