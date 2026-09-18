# Data Models

All dataclasses live in `src/dtm_buildsheet/domain/`.

## CustomerInfo

```python
@dataclass
class CustomerInfo:
    name: str = ""
    agency: str = ""          # display name
    agency_id: str = ""       # FK → agencies/{id}.json
    agency_abbreviation: str = ""  # editable agency identity used in paths/names
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
    laptop_make: str = ""
    laptop_model: str = ""
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
    company_group_folder_id: str = ""
    company_group_folder_path: str = ""
    shop_group_folder_id: str = ""
    shop_group_folder_path: str = ""
```

## IndividualUnit

```python
@dataclass
class IndividualUnit:
    individual_id: str         # durable identity; never derive associations from unit number
    unit_number: str = ""
    vin: str = ""              # actual VIN; sole VIN used for current identity/naming
    existing_year: str = ""    # optional replaced-vehicle display metadata
    existing_make: str = ""
    existing_model: str = ""
    existing_build_type: str = ""
    existing_unit_number: str = ""
    existing_vin: str = ""
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
    quote_references: list[QuoteReference] = field(default_factory=list)
    qb_estimate_id: str = ""
    qb_estimate_snapshot: dict = field(default_factory=dict)  # Builder-owned QBO fields at last write
    qb_estimate_snapshot_at: str = ""
    qb_invoice_id: str = ""  # legacy inert compatibility field; no current UI/API
    company_vehicle_folder_id: str = ""
    company_vehicle_folder_path: str = ""
    company_folder_status: str = "not_provisioned"
    shop_vehicle_folder_id: str = ""
    shop_vehicle_folder_path: str = ""
    shop_folder_status: str = "not_provisioned"
```

`BuildUnit` carries the same additive finalization fields for projects whose build is represented by
the unit itself rather than an `IndividualUnit`. Finalized draft mutations are rejected in the draft
service until the owning build is explicitly reopened with an actor and reason.
The Estimate snapshot is deliberately narrower than the raw QBO object: it tracks the customer /
project references, document number, memo fields, and material line IDs, descriptions, quantities,
prices, and amounts. Provider metadata such as `SyncToken` and update timestamps is excluded so it
does not create false conflicts.
`qb_invoice_id` remains readable only so the post-v3.6.0 removal of Invoice linking does not make an
older project file malformed. Current UI and routes neither create nor edit it. Existing Estimate
connections use `qb_estimate_id`; verified snapshots/check times mirror with the project while the
narrow status observation is also copied to the SharePoint Operations record.

`quote_references` is the per-vehicle, multi-quote history shown in Unit Details. Each reference has
a stable `reference_id`, human `quote_number`, user-owned `state` (`current` or `obsolete`), and
optional QBO match metadata (`qb_estimate_id`, `match_status`, status/customer/date/check time).
Unmatched current numbers remain readable without a QBO connection and are retried by automatic
QuickBooks sync. Obsolete references remain visible but are not automatically matched. The singular
`qb_estimate_id` remains the one Estimate selected for Builder-driven update/conflict tracking; it
does not replace the broader quote history.

`ProjectRecord.project_quote_references` uses the same `QuoteReference` shape for the advanced case
where one existing QBO Estimate bills the whole project. Those links are read-only from Builder and
can provide acceptance evidence to every current vehicle in the project.

Past photo records use the same `IndividualUnit` fields as current work. `vin` always means the
actual vehicle being built and is the only VIN eligible for current card identity, folders,
filenames, or QBO names. The `existing_*` fields are editable, round-trip-safe metadata for the
vehicle being replaced; generated output may show them only in the dedicated **Existing Vehicle**
card. Older clients that omit those optional keys preserve stored values, while an explicit empty
value clears one. Folder item IDs remain the stable identity when readable fields change. A current
vehicle without an actual unit number or VIN uses a display/folder-only `Pending ID` derived from
`individual_id`; the placeholder is not separately persisted and disappears when a real identifier
is added.

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
    reference_assets: list[BuildReferenceAsset] = field(default_factory=list)
    reference_source_exclusions: list[str] = field(default_factory=list)
    project_status: str = "active"  # active | inactive | completed
    inactive_at: str = ""
    inactive_by: str = ""
    inactive_reason: str = ""
    completed_at: str = ""
    completed_by: str = ""
    reactivated_at: str = ""
    reactivated_by: str = ""
    project_lifecycle_history: list[dict[str, str]] = field(default_factory=list)
    project_notes: str = ""   # shown on every build's final PowerPoint page
    company_year_folder_id: str = ""
    company_year_folder_path: str = ""
    company_folder_status: str = "not_provisioned"
    shop_year_folder_id: str = ""
    shop_year_folder_path: str = ""
    shop_folder_status: str = "not_provisioned"
```

Projects are stored in `workspace/projects/{project_id}/project.json` (one subdirectory per
project) and mirrored to SharePoint. Drafts remain durable records keyed by `draft_id`. Generated
customer PDFs and internal PPTX sources use the configured output trees; record-side output paths
are compatibility locators, not a per-project `export_dir` setting.

Legacy projects default to `active`. Inactive and completed projects use the same data model and
remain fully browseable; `project_status` controls Active / Inactive / Completed placement and can
be reversed. Every lifecycle change is appended to `project_lifecycle_history`; current inactive,
completion, and reactivation fields remain convenient projections.

## VehicleOperations and OperationsEvent

The production-operations extension deliberately uses separate domain records instead of growing
`ProjectRecord` into a shared workflow database. `VehicleOperations` is the query-friendly current
projection for one `IndividualUnit.individual_id`; `OperationsEvent` is its immutable timeline.
`BuilderVehicleProjection` is the intentionally narrow transfer object for vehicle identity,
agency/year, salesperson, lifecycle, and design-finalization facts. It contains no scheduling,
production, delivery, acceptance, or QBO-observation fields, so a Builder refresh cannot erase
those independently owned values.
Status values, automatic milestone dates, availability, the derived 60-day Must Deliver On date,
its separate optional manual override, patch-based scheduling,
QBO sending evidence is stored independently as `qbo_estimate_sent_status` and optional
`qbo_estimate_sent_at`; replacing the Estimate link resets it.
QBO observation, roles, and SharePoint field names are defined in
[OPERATIONS.md](OPERATIONS.md).

The SharePoint adapter uses each event as a short-lived commit journal because Graph cannot make a
cross-list transaction. A pending event stores the complete intended `VehicleOperations` snapshot;
the adapter applies that snapshot with the current item's eTag and revision, then marks the event
applied. Retrying the same request resumes the pending write instead of creating another event.
Conflicted attempts are retained for administration but excluded from the accepted vehicle
timeline. Applied event content is never rewritten by normal workflows.

`UserIdentity.roles` contains only known app-role values taken from MSAL-validated ID-token claims.
The role claim is recovered from MSAL's encrypted token cache on a normal access-token cache hit;
the application does not decode the Microsoft Graph access token or persist a second role file.
Unknown values are discarded before capabilities are calculated. Cloud-off development uses the
synthetic `AppAdmin` identity, while a cloud-enabled fallback to a local identity fails closed for
Operations.

`BuildReferenceAsset` stores portable source identity plus assignments, not image bytes. Zero
assignments means an unassigned project photo; current writes assign photos only to unit groups.
Legacy project-wide and individual assignments remain readable and publishable. JPG/PNG files found
in the exact year-level Company **Reference Photos & Videos** folder are reconciled into this list as
unassigned photos. `reference_source_exclusions` stores stable item/path identities for folder photos
that a user removed from the app without deleting the SharePoint source; explicitly adding one again
clears its exclusion. Videos are not auto-attached.

`BuildUnit.company_group_folder_*` and `BuildUnit.shop_group_folder_*` remain codec fields only for
backward compatibility with pre-flattening records. Current provisioning clears them and places each
`IndividualUnit` vehicle folder directly under the agency/year folder. Durable vehicle, PDF, and
published-reference item IDs/paths remain authoritative and are rewritten together when that folder
moves.

## AgencyRecord

Lives in `workspace/agencies/{agency_id}.json`. Mirrored to SharePoint.
Carries editable `abbreviation` plus optional `qb_customer_id` (FK → QuickBooks `Customer.Id`).
The abbreviation defaults to name initials, a county-only sheriff label, or a short explicit
acronym, but the stored override wins. Project snapshots retain the effective value for backward
compatibility and offline naming.
Contact info comes from the agency record — no separate contact field on the project.
`default_preferences` stores the agency's normal equipment choices. They are copied to a new
project once; editing a project never changes the agency defaults or another project's choices.
`pricing_overrides` is a sparse `manufacturer_id → percent off list` map. An empty map inherits
the shared Retail customer-pricing rule; only values that differ from Retail are stored.
Agency records also carry Company/Shop root folder IDs, portable paths, statuses, and retry-safe
errors. Those operational fields are persisted narrowly so an asynchronous Graph response cannot
overwrite customer-profile edits.

Agency list/search also exposes recovery rows synthesized from projects whose durable `agency_id`
no longer has a standalone record. Editing a recovery row materializes the ordinary record without
changing the ID; deletion is rejected while any project references the agency.

## SalesRepRecord

Lives in `workspace/sales_reps/{rep_id}.json`. Mirrored to SharePoint.

## Core domain models

| File | Contents |
|------|----------|
| `domain/input_models.py` | `ProjectInput`, `PartInput` |
| `domain/plan_models.py` | `BuildPlan`, `PlannedPart`, `PlannedPlacement`, `PlannedInstance` |
| `domain/project_models.py` | `ProjectRecord`, `CustomerInfo`, `EquipmentPreferences`, `BuildUnit`, `IndividualUnit` |
| `domain/operations_models.py` | `VehicleOperations`, `OperationsEvent`, stable workflow enums and derived-date rules |
| `domain/operations_policy.py` | Entra app roles mapped to backend capabilities |
| `domain/agency_models.py` | `AgencyRecord` |
| `domain/sales_rep_models.py` | `SalesRepRecord` |
| `domain/geometry.py` | Shared placement math (single source of truth) |
| `domain/rules.py` | Rule dataclasses |
| `domain/supply.py` | Canonical supply normalization, legacy mapping, validation, and labels |

`PlannedPlacement` carries normalized concealed-mount presentation state (`mount_visibility`,
`callout_label`) plus optional `callout_dx` / `callout_dy` relative-image offsets. Those offsets are
ordinary placement overrides: old plans default to zero without serialized churn, while manually
moved labels persist through drafts/presets and are consumed identically by preview and PDF output.

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
(PD→police department, SO→sheriff's office, punctuation, etc.). Agency-name review
accepts official `St.` styling, corrects bare `St` to `St.`, recognizes `Saint Paul`
as the regional exception, and asks the user to verify an official source before
using another `Saint …` legal name.

The project wizard has live-search combos for agency and sales rep fields. Saves and deletes
hit SharePoint directly via `save_setting_to_cloud_in_background` and
`delete_setting_from_cloud`.

## Project work types

`ProjectRecord.project_type` is `build` (legacy default), `service`, or `offsite`; it is independent
of `BuildUnit.build_type` and project lifecycle. `service_details` stores optional work requirements,
off-site location/contact/travel and the optional diagram toggle. Builder metadata is authoritative;
read-time Operations records attach these two fields for presentation and Calendar planning, while
the SharePoint current-record field map remains unchanged.

`IndividualUnit.previous_build` optionally references one Build vehicle by `project_id`, `unit_id`,
and `individual_id`. It is a reference only; parts, overrides, acceptance, Estimate and folder IDs
remain owned by their original records. Service visits do not participate in agency/year merging.
