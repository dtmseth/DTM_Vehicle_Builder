# Project Workflow

How data flows from a project record to a generated build sheet.

---

## Data model hierarchy

```
ProjectRecord                        workspace/projects/{project_id}/project.json
  └── BuildUnit[]                    vehicle model + build type + preset + quantity
        └── IndividualUnit[]         one unit per vehicle (VIN, year, color, unit #)
              └── draft_id ──────►  BuildDraft    workspace/drafts/{draft_id}.json
                                    (parts list + vehicle info + notes + overrides)
              └── output_path ───►  generated .pptx / exported .pdf
```

A **Preset** is a reusable parts template that seeds a new BuildDraft. Applying a preset copies its parts into the draft; subsequent edits to the draft do not affect the preset.

---

## File ownership

| Data | Canonical location | Owner |
|---|---|---|
| Project records | `workspace/projects/{project_id}/project.json` | `inputs/project_entry.py`, `app/services/project_service.py` |
| Build drafts | `workspace/drafts/{draft_id}.json` | `inputs/project_drafts.py`, `app/services/draft_service.py` |
| Bundled presets | `src/dtm_buildsheet/resources/presets/*.json` | `app/services/preset_service.py` |
| User/workspace presets | `workspace/presets/*.json` (bundled app) or `resources/presets/` (dev) | same |
| Agency database | `workspace/agencies.json` | `app/services/agency_service.py` |
| Sales rep database | `workspace/sales_reps.json` | `app/services/sales_rep_service.py` |
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
   and manifest editor. Changes are persisted on "Save & Return".

5. **Generate** — clicking Generate calls `POST /generate` (or equivalent generation route).
   The draft is converted to `ProjectInput`, planned into a `BuildPlan`, and rendered to a `.pptx`.
   `IndividualUnit.output_path` is updated with the result path.

6. **Export PDF** — clicking "Export PDF" calls `POST /api/export/pdf` using the stored `output_path`.

---

## Export Location

Generated `.pptx` and `.pdf` files are written to the local app output folder (`workspace/output/`).
When cloud mode and the export library are configured, successful exports are also uploaded to SharePoint:

```text
{exports_base_folder}/{agency}/{year}/{filename}
```

The `project_id` is passed with every `/api/draft/generate` call so the backend can refresh unit labels and agency/year metadata from the current project record before rendering. Custom per-project output folders and the old standalone export-folder picker are no longer used.

---

## Preset seeding vs. preset linking

Presets are **applied once at draft-creation time**, not linked live. After a draft is created:
- Editing the preset does not change existing drafts.
- Changing `BuildUnit.preset_id` does not update existing drafts — the user must re-create the draft
  (or edit the manifest manually) to apply a different preset.
- `blank_custom` is always available as the zero-parts preset.

---

## Dev vs. bundled paths

In dev mode (`pyproject.toml` present), several paths collapse back into the source tree so changes are git-trackable:

| Path alias | Dev points to | Bundled app points to |
|---|---|---|
| `workspace_config_dir` | `resources/config/` | `~/Library/Application Support/.../config/` |
| `workspace_assets_dir` | `resources/assets/` | `~/Library/Application Support/.../assets/` |
| `workspace_presets_dir` | `resources/presets/` | `~/Library/Application Support/.../presets/` |
| `workspace_dir` | `{repo}/workspace/` | `~/Library/Application Support/DTM Vehicle Builder/` |

`workspace/agencies.json` and `workspace/sales_reps.json` are seeded on first run from
`resources/default_data/` if they do not yet exist.
