# Project Workflow

How data flows from a project record to a generated build sheet.

---

## Data model hierarchy

```
ProjectRecord                        workspace/projects/{project_id}/project.json
  ├── reference_assets[]             portable Company/Shop identity + unit-group assignment notes
  └── BuildUnit[]                    vehicle model + build type + preset + quantity
        └── IndividualUnit[]         one unit per vehicle (VIN, year, color, unit #)
              └── draft_id ──────►  BuildDraft    workspace/drafts/{draft_id}.json
                                    (parts list + vehicle info + unit notes + shared project note + overrides)
              ├── output_path ───►  local .pptx conversion artifact / exported .pdf
              └── folder item IDs ► durable Company/Shop physical-vehicle package identity
```

A **Preset** is a reusable parts template that seeds a new BuildDraft. Applying a preset copies its parts into the draft; subsequent edits to the draft do not affect the preset.

---

## File ownership

| Data | Canonical location | Owner |
|---|---|---|
| Project records | `workspace/projects/{project_id}/project.json` | `inputs/project_entry.py`, `app/services/project_service.py` |
| Build drafts | `workspace/drafts/{draft_id}.json` | `inputs/project_drafts.py`, `app/services/draft_service.py` |
| Presets | `workspace/presets/*.json` (bundled app) or `resources/presets/` (dev) — synced from SharePoint `/Settings/presets/` | `app/services/preset_service.py` |
| Agencies (per-record) | `workspace/agencies/{agency_id}.json` — synced from SharePoint `/Settings/agencies/` | `app/services/agency_service.py` |
| Sales reps (per-record) | `workspace/sales_reps/{rep_id}.json` — synced from SharePoint `/Settings/sales_reps/` | `app/services/sales_rep_service.py` |
| Generated outputs | Timestamped local files in `workspace/output/`; PDF-only cloud distribution | `generation_service.py`, `export_service.py`, `company_vehicle_folder_service.py`, `shop_publication_service.py` |

---

## API ownership

| Operation | Route | Service |
|---|---|---|
| List / get / save / delete project | `GET/POST/DELETE /api/project/*` | `project_service.py` |
| Create draft for a unit | `POST /api/project/{id}/unit/{uid}/create-draft` | `project_service.py` → `draft_service.py` |
| Load / save / update draft | `GET/POST /api/draft/*` | `draft_service.py` |
| List / get / save / clone / delete preset | `GET/POST/DELETE /api/presets/*` | `preset_service.py` |
| Generate build sheet | `POST /generate` | `generation_service.py` → `generator.py` |
| Export PDF | `POST /api/export/pdf` | `export_service.py` |
| List/save/discover/import/remove references | `GET/POST /api/project/{id}/references/*` | `reference_photo_service.py`, `reference_library_service.py` |
| Reconcile direct project-folder photo uploads | `POST /api/project/{id}/photo-gallery` with `discover_folder` | `project_photo_folder_service.py`, `photo_gallery_service.py` |
| Finalize/reopen vehicle | `GET/POST /api/project/{id}/unit/{uid}/individual/{iid}/finalization/*` | `finalization_service.py` → `shop_publication_service.py` |

---

## Workflow: new project to generated sheet

1. **Create project** — user fills 4-step wizard (`#proj-editor`). API: `POST /api/project/save`.
   Project record written to `workspace/projects/{project_id}.json`.

2. **Add fleet units** — each `BuildUnit` specifies a vehicle model, build type, and optional preset.
   `IndividualUnit` entries are created within each `BuildUnit` (one per physical vehicle).

3. **Setup Build** — clicking "Setup Build" on a unit calls:
   `POST /api/project/{id}/unit/{uid}/individual/{iid}/create-draft`
   This creates a `BuildDraft` seeded from the unit's preset (if any) and stores the `draft_id` on the `IndividualUnit`.

4. **Edit draft** — the embedded build editor (`#proj-build-editor`) loads the draft into the preview canvas
   and manifest editor. Part and placement changes persist immediately; installation notes and
   delivery requirements save as they are typed.
   Project Details owns one shared note that is carried into every build draft without replacing unit-specific notes.

5. **Assign references** — the project-photo gallery adds organized media as assigned or unassigned;
   the unit-group thumbnail gallery assigns multiple project/reusable photos to every vehicle in that
   group, edits shop notes inline, and stores only portable drive/item identity plus the note. New project-wide and individual assignments are
   not created, though the shared UI/renderer/finalization/publisher resolver continues honoring
   legacy records at those scopes. The exact year-level Company **Reference Photos & Videos** folder
   is the unassigned-photo inbox: opening the project reconciles direct OneDrive/SharePoint JPG/PNG
   uploads into project metadata. Videos remain Company-only design context.

6. **Export PDF** — **PDF Options → Export / update PDF** checks whether the local conversion source
   is fresh, regenerates internally when needed, places adaptive reference-photo pages immediately
   after the vehicle visuals and before the parts manifest, converts to PDF, and adds sanitized
   relative links to full-resolution copied photos. There is no user-facing PowerPoint action.
   Generation/export stamps paths, actor, and timestamps server-side. If the vehicle is already
   finalized and owns a published Shop PDF, the completed export prompts before explicitly
   replacing that Shop package; declining keeps the prior Shop copy.

7. **Finalize design** — individual vehicles require a unit number or VIN, current PDF, available
   assigned references, and acknowledgement of advisory equipment warnings. Design finalization locks the
   draft and, only when the Shop cutover is explicitly enabled, publishes the PDF and effective
   photos. Reopening records actor/reason and withdraws exact app-owned Shop item IDs without touching
   Completed Build Photos.

8. **View PDF / Open folder** — View PDF opens/hydrates the current PDF. Once a Shop package exists,
   the folder action uses the stored Shop PDF path to open the exact vehicle folder through a local
   OneDrive sync or its SharePoint URL; otherwise it retains the legacy agency/year fallback.

9. **Past-photo project and archive** — old completed-build photos map to an ordinary project for
   their actual agency/build year, with only known model/build-type/unit data. No historical marker,
   label, draft, PDF, finalization, or QBO data is invented. After the copied photos are verified,
   mark the project completed; it moves from Active Projects to the Agency → Build Year Project
   Archives tree and can be reopened later.

---

## Export Location

Generated `.pptx` and `.pdf` files are written with timestamps to the local app output folder
(`workspace/output/`). PPTX is a conversion artifact and new cloud upload/queue entry points reject
it. The legacy pre-v3.5.0 PDF path was:

```text
{exports_base_folder}/{agency}/{year}/{stable vehicle name}.pdf
```

The two independent v3.5.0 production paths are:

```text
Company Files/Vehicle Project Database/{agency}/{agency abbreviation} - {year}/
  Reference Photos & Videos/
  {canonical vehicle}/{canonical vehicle}.pdf

Shop Documents/Shop Project Database/{agency}/{agency abbreviation} - {year}/{canonical vehicle}/
  {canonical vehicle}.pdf
  Build Reference Photos/
  Completed Build Photos/
```

The canonical vehicle label is `{year} {agency abbreviation} {short model} - {build type} - Unit {number} - VIN {last
six}` with unavailable identifier segments omitted. The make is not included; Police Interceptor
Utility is `PIU`, while other vehicles use recognizable model names such as `Durango`, `F-150`, and
`Traverse`. Unit number and VIN always mean the actual/new vehicle identifiers. Existing or trade-in
identifiers are shown only as optional metadata in the dedicated **Existing Vehicle** fields/card;
they are never current card identity or folder, filename, export, or QBO naming fallbacks. The cover
uses separate **Build Type** and **Unit #** rows for both vehicles rather than combining them into an
ambiguous `Patrol #1`-style value. Stored folder item IDs, not the mutable current-vehicle label, own
the physical vehicle. A naming change moves/renames the existing folder by ID so completed photos
remain attached.

Agency Abbreviation is editable in Agency Manager. It defaults to initials of meaningful words,
the county name for a county sheriff, or a short explicit acronym; the saved override wins. `&` is
supported and preserved in visible names. Agency Manager and project search also recover identities
retained by projects when an agency file is absent, and prevent deletion of in-use agencies.

Folder pre-creation is independently gated from PDF publication. The provisioning flags are enabled
in the current working-tree configuration after the approved live skeleton run. Project save
creates/reconciles agency/year/reference folders, and every known individual creates the
applicable vehicle/photo folders. Standalone Agency Manager and imported QBO Customer records never
create roots. Existing records without a
unit number or VIN use a stable `Pending ID` suffix derived from `individual_id`; saved folder item
IDs drive the later rename when real identity arrives, while periodic cloud sync retries durable
pending/error states. Ordinary project edits preserve these server-owned folder IDs, publication
state, output metadata, and QBO links even when an older/partial browser payload omits them.

The `project_id` is passed with every `/api/draft/generate` call so the backend can refresh unit labels and agency/year metadata from the current project record before rendering. Custom per-project output folders and the old standalone export-folder picker are no longer used.

Before replacing an existing local export, the UI still permits Replace or Keep both for backward
compatibility. A separate post-export confirmation controls replacement of an existing finalized
Shop PDF. Cloud per-vehicle publication is deterministic and item-ID based. The migration dry
run reports legacy outputs/folders, missing identifiers, and same-agency/year duplicate
projects; it never moves or merges them automatically. Existing Shop photos must be copied and
verified before app cutover; source-location deletion is a separate final approval.

---

## Preset seeding vs. preset linking

Presets are **applied once at draft-creation time**, not linked live. After a draft is created:
- Editing the preset does not change existing drafts.
- Changing `BuildUnit.preset_id` does not update existing drafts — the user must re-create the draft
  (or edit the manifest manually) to apply a different preset.
- `blank_custom` is hardcoded in `preset_service` (not a file) and is always available as the zero-parts preset. Every other preset comes from the cloud — synced down from SharePoint `/Settings/presets/` into `workspace_presets_dir`. Bundled presets (the old `resources/presets/*.json` files) were removed in v2.2.10; cloud is the single source.

---

## Dev vs. bundled paths

In dev mode (`pyproject.toml` present), several paths collapse back into the source tree so changes are git-trackable:

| Path alias | Dev points to | Bundled app points to |
|---|---|---|
| `workspace_config_dir` | `resources/config/` | `~/Library/Application Support/.../config/` |
| `workspace_assets_dir` | `resources/assets/` | `~/Library/Application Support/.../assets/` |
| `workspace_presets_dir` | `resources/presets/` | `~/Library/Application Support/.../presets/` |
| `workspace_dir` | `{repo}/workspace/` | `~/Library/Application Support/DTM Vehicle Builder/` |

`workspace/agencies.json` and `workspace/sales_reps.json` are legacy flat-file fallbacks. The live data lives in per-record directories (`workspace/agencies/{id}.json`, etc.) and is synced from `/Settings/agencies/` and `/Settings/sales_reps/` on SharePoint. The legacy seeds in `resources/default_data/` only run if a fresh install has nothing local yet AND no cloud is reachable.

Saves go directly to SharePoint via `save_setting_to_cloud_in_background` (added in v2.2.9 alongside `save_via_proposal`). Deletes go through `delete_setting_from_cloud` (v2.2.6). Both routes make SP authoritative within seconds of the local write, independent of the dtm-shared-settings publish workflow's cron cadence.
