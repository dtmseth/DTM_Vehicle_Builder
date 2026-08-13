# Project Workflow

How data flows from a project record to a generated build sheet.

---

## Data model hierarchy

```
ProjectRecord                        workspace/projects/{project_id}/project.json
  └── BuildUnit[]                    vehicle model + build type + preset + quantity
        └── IndividualUnit[]         one unit per vehicle (VIN, year, color, unit #)
              └── draft_id ──────►  BuildDraft    workspace/drafts/{draft_id}.json
                                    (parts list + vehicle info + unit notes + shared project note + overrides)
              └── output_path ───►  generated .pptx / exported .pdf
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
| Generated outputs | `workspace/output/`, then SharePoint export library by agency/year | `app/services/generation_service.py`, `export_service.py`, `exports_upload_service.py` |

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
   and manifest editor. Part and placement changes persist immediately; final-page notes save as they are typed.
   Project Details owns one shared note that is carried into every build draft without replacing unit-specific notes.

5. **Preview / Edit in PowerPoint** — the per-build action is "📊 Preview / Edit in PowerPoint", not a separate Generate step. Behind the scenes:
   - `POST /api/build/render-status` decides whether the existing PPTX is fresh, stale (source changed), or manually edited in PowerPoint since the last render.
   - Stale + not edited → silent re-render via `POST /api/draft/generate`.
   - Stale + edited → modal asks whether to discard the manual edits or open the existing file as-is.
   - Fresh → just open.

   Generation stamps `IndividualUnit.output_path`, `last_rendered_at`, and `last_rendered_by` (display name of the signed-in M365 user) on the project record server-side; no follow-up `/api/project/save` from the UI is needed.

6. **Export PDF** — "📄 Export PDF" runs the same staleness check, regenerates if needed, then exports the PDF and uploads it to the SharePoint exports library. Updates `pdf_path`, `last_exported_at`, `last_exported_by` on the project record.

7. **View PDF / Show in folder** — visible once the corresponding artifact exists. If a shared
   project contains an absolute export path from another computer, View PDF / Preview downloads the
   matching agency/year/filename from the SharePoint exports library into this install's approved
   output folder before opening it. "Show in folder" tries an OneDrive-synced path first, falling
   back to the SharePoint web URL via Graph's `drives/{id}.webUrl`.

---

## Export Location

Generated `.pptx` and `.pdf` files are written to the local app output folder (`workspace/output/`).
When cloud mode and the export library are configured, successful exports are also uploaded to SharePoint:

```text
{exports_base_folder}/{agency}/{year}/{filename}
```

The `project_id` is passed with every `/api/draft/generate` call so the backend can refresh unit labels and agency/year metadata from the current project record before rendering. Custom per-project output folders and the old standalone export-folder picker are no longer used.

Before replacing an existing vehicle export, the Builds UI asks whether to replace the prior
PPTX/PDF pair or keep both and create a version. Replace is the default. Cleanup runs only after the
new PPTX and project record save succeed, and removes every older timestamped PPTX/PDF sharing that
vehicle's stable filename prefix, both locally and in the SharePoint exports library.

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
