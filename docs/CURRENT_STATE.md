# DTM Vehicle Builder — Current State

**Last updated:** 2026-08-26

**Current release:** [v3.4.0](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/tag/v3.4.0)

This is the short operational handoff for the repository. It replaces dated session handoffs and
release checklists. Long-lived design and behavior remain documented in `ROADMAP.md`,
`FEATURE_INVENTORY.md`, `PARTS_DB_AND_PICKER.md`, and `QUICKBOOKS.md`.

## What is live

- **Desktop distribution:** signed-in team use on macOS and Windows, with CI-built installers,
  GitHub releases, SharePoint release staging, and in-app update detection/download/restart flow.
  Startup and status polling are concurrent and do not freeze the UI behind Microsoft or installer
  network timeouts.
- **Shared team workspace:** SharePoint is the source of truth for agencies, sales reps, presets,
  projects, and drafts. Generated PPTX/PDF files are uploaded by agency/year and can be hydrated on
  another workstation. Export detects prior files for the same vehicle and defaults to replacing
  them after user confirmation.
- **Part Picker and rendering:** the SKU-level Part Picker, guided radio/radar/camera/console flows,
  siren/Howler behavior, custom locations, rich preset round-tripping, manifest grouping, preview,
  PowerPoint, and PDF output are in production use.
- **Parts catalog:** `parts_db.json` currently contains 773 products, 1,339 SKUs, 1,224 QB-linked
  SKUs, 120 part types, and 63 manufacturers. Forty-three products still have no part-type home and
  remain an explicit curation queue.
- **QuickBooks production:** managed OAuth uses the Netlify token broker; the shared Intuit secret
  stays on Netlify and each user's company tokens stay in the OS keychain. Production catalog
  reconciliation runs at startup and every 30 minutes when connected. All 214 Builder agencies were
  migrated to reviewed production Customers.
- **Estimates:** per-vehicle and batch non-posting Estimate creation is live. Creation refreshes
  current Item prices, applies Retail pricing by default, supports temporary Custom pricing,
  allocates Estimate numbers, prevents accidental duplicates, requires or creates the current build
  PDF before attachment, and surfaces actionable failures. Vehicles without unit numbers use a
  stable per-build fallback label such as `Patrol #1`. True QBO Projects are still created manually
  and linked by URL/ID; the batch checklist returns from each setup and revalidates readiness before
  creation.

## Changes shipped after v3.3.2

- **v3.3.3 — build configuration and Estimate workflows:** repaired agency-default preference
  saving; added the second-control-head/microphone and Gamber-Johnson bracket choice behavior;
  automatically adds `LCPHOTO` with an interior light bar instead of offering it on CenCom Core;
  added the Estimate PDF readiness/export flow; and made missing unit numbers non-blocking through
  deterministic, vehicle-stable fallback labels.
- **v3.3.3 — picker search:** a child SKU can make its parent product match, but search results stay
  collapsed. Opening a matched product shows its complete SKU list rather than a filtered fragment.
- **v3.3.4 — guided conditions and light rendering:** guided components can carry their own
  New/Used/Reused status; Used/Reused lines are excluded from Estimates; reused console components
  do not affect the ordered console kit; `UCVDMLTAL00` is a direct single-SKU product without the
  warning-color matcher; DUO RST rear roles render red on the driver/left and blue on the
  passenger/right; and custom-location asset resolution was hardened.
- **v3.3.5 — split assets at custom points:** a neutral custom anchor now falls back to an available
  driver/passenger asset instead of rendering only a red placement dot.

## v3.4.0 release scope

- Quantity-aware custom placement lets the Details tab expose spacing for a
  selected light-head count, and one preview click places or moves the whole horizontal group. A
  four-head group can instead be arranged as two mirrored pairs. Head index and pair identity are
  persisted, so equal-row and paired DUO lights keep the correct driver/passenger asset sequence.
  Older single-point custom locations remain compatible.
- The current picker/output polish set ensures editing a parent no longer lets an
  automatic recommendation replace its restored accessory; 3-inch round lights allocate quantity
  across several locations in one atomic edit, with an independent manifest note for every location;
  Window Tint selects multiple windows and a percentage
  without a vehicle placement and quotes at $65 per window through MISC PART; Gamber-Johnson Core
  and Motorola specialty faceplates quote at $0, OEM plates are omitted, and later faceplates bill
  normally. Picker-facing prices are labeled and calculated as Retail rather than exposing raw QBO
  list values. Agency/project lighting setup defaults can be DUO or TRIO without restricting picker
  choices. DUO component rows combine only in the shop manifest, preserving separate QBO line items;
  color/lens details and row spacing are compacted. Long agency titles and dense manifests now
  paginate safely in PDF output, while concealed speakers render faded with a red mounting callout.
  Export order is cover, vehicle views, manifest, then build notes. Customer output omits internal
  QB-import provenance, tint pricing, stale allocation recipes, Install Type, and Other Orders.
  Build notes contain only project notes, installation notes, and delivery requirements.
- The first vehicle-finalization slice includes a focused review modal, current-PDF
  requirement, an expandable passed/warning/blocked checklist, equipment relationship/coverage
  warnings (including Core interface, photo eye, docking motion, radio/camera/expansion, Patrol
  radar/partitions, and front/side/rear warning) and acknowledgement notes, durable
  collaborator-visible status/audit fields, server-side edit locks,
  and reasoned reopening. Shop Documents publication / withdrawal, retry state, and stale
  concurrent-finalization rejection remain Phase 5 follow-up.
- Existing linked QBO Estimates now store a narrow post-write baseline. A changed QBO form raises a
  loud pre-write conflict with readable differences and requires an explicit overwrite-or-create-new
  choice; the service repeats the gate immediately before update so the UI cannot bypass it.
- QuickBooks estimate review now has **Additional charges** after materials: shared
  Patrol/Undercover/Admin/Custom labor and install-supplies presets, per-vehicle overrides, optional
  delivery, and an automatic non-compounding 4% card fee. Exact active QBO Service items are
  resolved from the refreshed cache; missing items or unset required amounts block before write.
- Project Overview cards now surface each individual unit's notes in a prominent shop-note panel;
  notes are clamped to two rendered lines, and only visually overflowing notes become clickable with
  a **Read more** action that opens the complete note in a focused modal. The manual QuickBooks Project setup/link
  walkthrough is available before the unit has a configured draft, while Estimate actions remain
  correctly disabled until configuration. Final review is always the last card action and changes
  from light green to solid green after finalization. Generated/copied QBO Project names omit the
  redundant agency and use `Unit {number} | Build {year}` (or the stable build label first when the
  unit number is unknown).
- The build editor now exposes **Load Preset** directly beside **Save as New Preset** in both action
  areas. Its searchable picker refreshes current compatible presets and atomically replaces only the
  active build's parts and placements, preserving vehicle identity and build/project notes.
- Project Manager **All Presets** menus are now literal, unfiltered lists in both new-project and
  Project Details flows; vehicle/build compatibility no longer silently hides choices there.
- Guided-system optionality now covers the relationship that was actually
  over-constrained. A front-only radar can explicitly save its rear antenna as **Not included**;
  this removes the dependent rear-bracket question and rear component while preserving edit
  round-trip. Core radio choices remain required, camera keeps its explicit component selection,
  and console's existing None/dependency behavior is unchanged.
- Guided radio Custom antenna locations now reuse the normal optional vehicle-placement flow, so
  the shop-facing location label remains independent from a saved vehicle dot or free point and
  the synthesized antenna renders on the build sheet. Shared exports now keep customer PDFs in the
  visible agency/year tree while moving editable PPTX sources under
  `_DTM Internal PowerPoint Sources`; the build card opens only the PDF folder. Normal Replace
  exports use deterministic SharePoint filenames, legacy timestamp/folder variants remain
  readable and cleanable, and upload/delete serialization prevents a delayed retry from restoring
  an obsolete ICE-style duplicate. Explicit Keep both exports remain timestamped.
- The canonical part-supply model is included. Drafts, presets, Excel input, picker and
  guided-system components now normalize to **New** or **Customer supplied**, with customer-supplied
  condition New/Used and a required source for newly edited Used records. Legacy New/Used/Reused
  data remains readable; source-less legacy records are visibly flagged until their next edit.
  Customer-supplied lines are excluded from Estimates, console bundle resolution excludes both
  customer-supplied conditions, and manifest/build-sheet comments and used-source callouts are red.
  Intentional PowerPoint golden-image changes are recorded and pass with focused renderer coverage.
- Centralized QuickBooks remains deferred and is excluded from this release. The existing
  per-user OS-keychain connection and stateless OAuth broker remain the only production path; no
  central service is deployed and no production token is moved.

## Current verification baseline

- The v3.4.0 Python suite passes **2,077 passed, 1 skipped, 1 sandbox-only deselected**. The deselected
  macOS updater test writes to Downloads, which this verification sandbox cannot access. Contract
  snapshots and all six PowerPoint render goldens pass.
- The hermetic browser smoke suite passes **28/28**, including tint/round-light allocation, custom
  DUO grouping, accessory quantity and dual-shroud rendering, Overview notes/pre-configuration
  QuickBooks Project setup, finalization, and Estimate review workflows. Round-light coverage includes
  deleting one allocated manifest row and editing the survivor without resurrecting removed lights.
  It reports no console
  errors, external browser requests, or network-guard violations.
- PR checks: import boundaries, dependency audit, high-severity security scan, and test/coverage
  floor are enforced.
- Release v3.4.0 is the current published version.

## Roadmap position

| Area | Status | What remains |
|---|---|---|
| Phase 0 — foundation | Complete | Preserve the guardrails while retiring remaining shims deliberately. |
| Phase 1 — cloud readiness | Complete | No new foundation work required. |
| Phase 2/2.5 — cloud collaboration/distribution | Complete and live | Operational hardening only; monitor cross-instance sync/export behavior. |
| Phase 3 — canonical parts DB + intelligent picker | Substantially complete and live | Curate the 43 unhomed products, finish low-priority picker polish, and add a reviewed queue for future QBO catalog changes. |
| QuickBooks production track | Complete and live | Manual QBO Project creation remains; bank-transfer fee remains a documented QBO follow-up because the Accounting API cannot set it. |
| Phase 4 — remaining consumer migration | Next architectural milestone | Move the remaining workbook-era domain consumers to `parts_db`, then reduce `workbook_rules.json` to layout-only data. |
| Kit/component modeling | Partly expressed by guided builds, not generalized | After the parts-DB repository seam, define generic SKU-kit storage and Estimate expansion/billing behavior. |
| Phase 5 — generalized light model | Partially delivered through picker-specific flows | Consolidate remaining legacy light naming/color assumptions into canonical domain rules. |
| Phase 6 — arbitrary views | Open | Remove remaining four-view assumptions before adding more interior/top-down views. |
| Phase 6.5 — interior light bars | Open/high user value | Model driver/passenger halves and render configured lightheads instead of static bar images. |
| Phase 7 — free-form vehicle wizard | Partially realized by the current Part Picker | Complete only after canonical consumer/light/view work removes legacy dependencies. |
| Phase 8 — Parts Manager | Editing MVP live | Finish hierarchy/curation polish; decide a separate high-frequency inventory store before quantity tracking. |
| Phase 9 — serial tracking | Open | Add per-project serial numbers for parts marked serialized. |

## Recommended next sequence

1. **Finish the finalization cloud boundary:** Shop Documents PDF publication/withdrawal, retry
   states, and explicit concurrent stale-finalization rejection.
2. **Continue the remaining non-backend identity/cloud workflow work** with an owner-reviewed
   vehicle-folder migration dry run, collision report, and cutover plan. The new generated/copied
   QBO Project naming convention already shipped in v3.4.0; stored legacy names still require an
   audit and manual QBO rename checklist rather than an automatic destructive rename.
3. **Keep centralized QuickBooks Phase 3A deferred and out of production.** No cloud registration,
   deployment, authorization, or token migration is currently planned. The complete but excluded
   experiment is preserved only on local branch `codex/central-qb-backend-wip` at `f5ac223`; do not
   merge or delete it unless the owner explicitly resumes that design.
4. Preserve the longer-term parts-DB consumer migration, catalog governance, visible curation queue,
   interior-light-bar work, and generalized kit/light/view roadmap behind the approved feature plan.

## Safety rules that remain active

- Run development cloud-off unless deliberately testing SharePoint. Cloud sync can replace local
  configuration, including `parts_db.json`.
- Never store QuickBooks tokens or the Intuit client secret in the repository or SharePoint.
- Keep QuickBooks Estimate creation and later PDF attachment as separate writes; never retry an
  Estimate automatically because attachment failed.
- Do not move golden outputs merely to make tests green. Intentional renderer changes need focused
  behavioral coverage plus a representative export check; reserve owner review for ambiguous or
  high-impact visual redesigns rather than every digest update.
- Preserve `.hermes/` as unrelated local scratch data; it is intentionally untracked.
