# DTM Vehicle Builder — Roadmap

Direction and active critical-path backlog. Live implementation/release status belongs in
[CURRENT_STATE.md](CURRENT_STATE.md). Past decisions, completed phase plans, early schema
sketches, and revisions 1.0–1.12 are preserved in
[ROADMAP_HISTORY.md](archive/ROADMAP_HISTORY.md).

## Vision and pillars

Two ideas drive everything below:

1. **The workbook is a renderer, not a database.** Historically the Excel "build sheet" was both the input and the source of truth for what parts/manufacturers/locations/colors exist. We are phasing this out. Domain data lives in a clean canonical database. The workbook becomes one of several outputs (alongside PowerPoint and PDF), built from the same domain data.
2. **The app is a tool, not a silo.** The desktop app now reads and writes a shared SharePoint team
   workspace, so sales, builders, and project management can see the same projects, presets,
   agencies, drafts, and exports. Users authenticate with M365 and the app talks to SharePoint via
   Microsoft Graph. GitHub remains the invisible review and release backend. The remaining work is
   to preserve this collaboration model while canonicalizing parts-domain consumers and, later,
   deciding where high-frequency inventory data should live.

Around those two ideas, five thematic pillars:

1. **One canonical parts database.** Manufacturers, models, locations, colors, brackets, inventory — all in one place, queryable from any UI or export path.
2. **Free-form, smart building.** Users add a part to a location with a visual preview, not a slot from a fixed list. The app handles naming, bracket recommendations, validation.
3. **Lights are a model, not a permutation table.** Colors are derived. Power outputs and bracket needs are data fields, not implicit knowledge.
4. **Views are extensible.** Today there are four external views per vehicle. Tomorrow there are interior views, top-down views, whatever the work needs. Nothing should hardcode "exactly four."
5. **Inventory is a first-class concept.** Parts have prices, quantities, and friendly names. Some parts get tracked by serial number on a per-project basis. The builder app and a future parts-manager app share one database.

## Current direction and critical path

The production foundation is live: SharePoint collaboration and distribution, the Part Picker,
SKU-level QuickBooks catalog and pricing, agency/customer links, Estimates, per-vehicle
Company/Shop folders, photo workflows, and finalized Shop publication. QBO is the parts
catalog's production foundation. Phase 3 is substantially complete; Phase 4 consumer migration
is the next architectural milestone.

### Current delivery dependencies

- **Hosted Builder:** carry the local runtime and security boundary into a reviewed isolated
  deployment, then integrate provider-backed services and the full shared HTML UI with
  desktop/iPhone/Android feature parity. Azure remains preferred if affordable; activation,
  concrete cost/resource review, and deployment authorization remain gates. Local proofs do
  not establish full hosted readiness. See [HOSTED_ARCHITECTURE.md](HOSTED_ARCHITECTURE.md).
- **Calendar:** complete the current unreleased team/labor scheduling work and its pilot while
  preserving reviewed per-vehicle publication and the 60-day delivery promise. Project types
  share the same Calendar. Team assignments are current work; bay tracking remains deferred.
  See [CALENDAR.md](CALENDAR.md).
- **Desktop feature follow-through:** use the live backlog in [CURRENT_STATE.md](CURRENT_STATE.md)
  for photo access/HEIC/uploads, truthful Estimate states and discovery/import, notes, project
  types, and standardized vehicle selection. Preserve completed slices while finishing the
  remaining work through the shared service boundaries.
- **Hosted QBO:** review server-side authorization and protected credential storage, then prove
  sandbox integration before any production cutover. The per-user OS-keychain connection and
  stateless Netlify broker remain live. The experimental central-QBO branch is incomplete and
  must not be merged or deployed wholesale. See [QUICKBOOKS.md](QUICKBOOKS.md).
- **Optional phone client:** the request list exists, but the processor stays Off until failure
  handling, interrupted-write recovery, and the controlled pilot are complete. No Canvas app
  exists. Its narrow request boundary is in [OPERATIONS.md](OPERATIONS.md).

### Architectural backlog (priority order)

1. **Parts-DB repository seam and Phase 4 consumer migration.** Establish one safe read/write
   boundary, inventory remaining workbook-domain reads, and migrate consumers individually,
   leaves first and `template_builder.py` last. Candidate paths include project brand derivation,
   UI state, part-type/location editing, and template dropdown generation; recheck the inventory
   before changing them. Preserve validation, cloud mirroring, and template regeneration.
   Exit when `workbook_rules.json` is layout-only and newly added part types appear in the next
   generated template. Workbook import remains a best-effort edge adapter; canonical domain
   data must not depend on workbook shapes. See
   [the repository spec](audit/PARTS_DB_REPOSITORY_SPEC.md) and
   [PARTS_DB_AND_PICKER.md](PARTS_DB_AND_PICKER.md).
2. **Reviewed QBO catalog changes and visible curation.** Require explicit review before
   recurring changes create or materially reshape Builder products. Retain durable history,
   Builder-owned metadata, and Whelen reference enrichment; resolve or intentionally exclude
   the remaining unhomed products. See the
   [reviewed change-queue contract](QUICKBOOKS.md#future-reviewed-qbo-catalog-change-queue-owner-decision).
3. **Interior light bars and light-domain consolidation.** Model driver/passenger halves and
   configured heads while retiring remaining workbook-era light assumptions. Preserve stable
   rule-facing names and derive presentation names separately.
4. **Finalization concurrency.** Reject stale concurrent requests while preserving Shop
   publish/withdraw and re-export confirmation boundaries.

Audit/refactor work stays interleaved with this order. Use the [findings ledger](audit/LEDGER.md)
and existing import boundaries; preserve regression contracts as consumers move. Verification
scope follows root [AGENTS.md](../AGENTS.md). Keep this backlog current as work ships; historical
plans and decisions belong in the archive.
