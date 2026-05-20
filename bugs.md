# Bug Fix Plan

Planning notes from the May 19, 2026 investigation. This file is intentionally written as a durable repair guide: prefer preserving the intended behavior and adding regression coverage over following any exact implementation detail if the code moves later.

## 1. Preset setup can create empty builds

Priority: highest

Observed behavior:
- Selecting a preset for a unit group can lead to an empty build editor: no manifest rows and no preview visuals.
- The backend draft creation path does copy preset parts into drafts when the selected preset has parts.
- The committed versions of both `patrol_piu_standard` and `stearns_county_sheriff_patrol_piu_090b8e` have empty `parts` arrays. The existing regression test for transferring preset parts fails because of that.
- The local working tree currently contains an uncommitted edit that adds parts back to the Stearns preset. Direct service calls using that dirty file can create a populated draft, but that does not represent the committed repo state.
- Existing project drafts do not automatically repopulate when preset JSON changes. The saved Stearns project in `workspace/projects/` points at the Stearns preset, but its linked individual drafts are already empty or near-empty, so opening Edit Build reuses those drafts as-is.

Likely cause:
- Shipped/default preset data was lost for more than one visible preset. This makes the UI look broken even though the draft-creation code path can work when valid preset data is present.
- Existing empty drafts created from empty/damaged presets are treated as configured builds and are reused rather than refreshed from the current preset.
- There is no strong enough guard preventing user-visible, non-blank presets from being saved or shipped with no parts.

Desired behavior:
- Any visible, selectable build preset should create a populated draft unless it is explicitly the blank/custom preset.
- If a preset is intentionally empty, the UI should name it and treat it as blank/custom so users do not mistake it for a real build.
- Importing a known-good spreadsheet should be a valid way to repopulate a damaged preset, but the app should also prevent this class of silent data loss from coming back.

Fix guidance:
- Restore the intended parts for all visible presets that are meant to be real build presets, including `patrol_piu_standard` and `stearns_county_sheriff_patrol_piu_090b8e`, from the best available source, likely the project spreadsheet or a known-good preset export.
- Add a way to rebuild an existing draft from its assigned preset, or detect empty/near-empty drafts created from non-empty presets and prompt the user to reload from preset. Be careful not to overwrite real user edits without confirmation.
- Add validation or tests that fail when a visible bundled preset has no parts unless it is explicitly blank/custom.
- Keep the existing draft-creation flow, but make failures more visible: if a selected preset is missing or empty unexpectedly, surface a clear warning instead of silently creating an empty build.

Verification:
- Creating a project with the restored general patrol preset produces a draft with parts.
- Creating a project with the restored Stearns preset produces a draft with parts from a clean checkout, not only from a dirty local file.
- An existing empty draft linked to a restored preset can be safely rebuilt or refreshed from that preset.
- Opening Setup/Edit Build shows manifest rows and preview visuals for parts that have renderable placements.
- Existing tests around preset-to-draft transfer pass, and a new bundled-preset sanity test covers this regression.

## 2. Equipment preference options do not match workbook options

Priority: high

Observed behavior:
- Project wizard/edit equipment preference options for bumper and cage are served from `project_options.json`.
- The workbook template rules have the more complete manufacturer lists for the related equipment, for example push bumper and partition/cage-adjacent rows.
- Current `project_options.json` contains simplified or hallucinated values that do not match the workbook-driven options.

Likely cause:
- Project preference dropdown data was duplicated instead of derived from the workbook/template source of truth.

Desired behavior:
- Project preference options should match the manufacturer choices used by the workbook template.
- Avoid maintaining two independent manufacturer lists for the same concept.

Fix guidance:
- Prefer deriving bumper options from the workbook rule for `Push Bumper`.
- Prefer deriving cage/prisoner-area options from the relevant workbook rules, such as `Front Partition`, `Rear Partition`, and closely related cage/prisoner equipment rows, after confirming the exact user-facing meaning of "cage".
- If `project_options.json` remains as a curated UI config, document it as an override/curation layer and keep tests that compare it against the canonical workbook rules.

Verification:
- Wizard and edit-mode datalists show the same expected manufacturers as the workbook template.
- Saving/reloading a project preserves selected preferences.
- Tests cover project options loading and the canonical option source.

## 3. Project output folders/settings are not wired through generation

Priority: high

Observed behavior:
- Settings has a `project_output_root` picker and `app_settings.json` contains `project_output_root`.
- `inputs/project_dirs.py` already defines per-project folder naming and creation helpers.
- Generation currently ignores `project_output_root`.
- Draft generation only uses `ProjectRecord.export_dir` when it already exists; if the directory does not exist, it silently falls back to the global output folder.
- Global `output_save_dir` is still used by standalone generation/finalization, but it does not create the professional per-project folder structure.
- Export All PDF generates/export PDFs but does not appear to persist generated `output_path` values back onto the project units the way single Generate does.

Likely cause:
- The project-output-root feature was partially added but not integrated into the generation/export services.
- There are competing concepts: global standalone output directory, project-level manual export directory, and project-output-root derived folders.

Desired behavior:
- Project builds should resolve a single effective output directory in a predictable order.
- A good default order would be: explicit project export directory if set, otherwise derived folder under `project_output_root`, otherwise legacy global output directory, otherwise workspace output.
- Missing derived/project directories should be created automatically.
- Generated PPTX, generated PDF, summaries, and plan artifacts should land in the same project-appropriate location unless there is a deliberate reason to keep internal artifacts in workspace output.
- Single Generate, Generate All, Export PDF, and Export All PDF should agree on paths and persist output paths back to the project record.

Fix guidance:
- Create one backend resolver for effective project output destinations and use it from generation and export flows.
- Use `project_dirs.py` rather than duplicating path construction.
- Avoid silently falling back when a configured path is invalid; return a useful error or create the intended directory when safe.
- Remove user-specific absolute defaults from bundled app settings unless they are dev-only.

Verification:
- Setting a project output root creates `<agency> - <year>` folders and places generated/exported files there.
- Setting an explicit project export directory overrides the root-derived folder.
- Single Generate, Generate All, Export PDF, and Export All PDF produce consistent paths and update the project record.
- Tests cover missing directories, invalid paths, and fallback behavior.

## 4. Unit identifiers leak internal IDs into user-facing output

Priority: high

Observed behavior:
- For group-level drafts, `NewVehicle["UNIT ID"]` is currently set from the internal build `unit_id`.
- For individual drafts, `NewVehicle["UNIT ID"]` falls back to `individual_id` when no real unit number exists.
- Generated filenames and PowerPoint labels therefore show internal IDs/UUIDs when real unit numbers are blank.
- Existing tests currently assert the internal `unit_id` fallback, so tests encode the undesired behavior.

Desired behavior:
- User-facing unit number fields should show the real unit number when provided.
- If no real unit number exists, show `Not Specified`.
- Internal IDs should remain available for storage/routing only and should not appear in generated PowerPoint content, filenames, or visible build-editor context.
- The build editor should show a clear working label, such as the real unit number or a generated display label like `Patrol 4`, so the user always knows which build is open.

Fix guidance:
- Separate display unit labels from internal IDs in project/draft creation and rendering.
- Update individual and group draft creation to store a user-facing unit display value.
- Pass enough individual context into the build editor to render the same label used on the Builds tab.
- Update tests that currently expect internal IDs in `UNIT ID`.

Verification:
- Blank unit numbers render as `Not Specified` in PPTX metadata and filenames.
- Real unit numbers still render normally.
- Build editor header identifies the current build, including individual unit position when there is no explicit unit number.
- No UUID/internal unit IDs appear in generated user-facing output unless the user typed them as real values.

## 5. Build editor back/save behavior is too coarse

Priority: medium

Observed behavior:
- The Back to Project button always shows a confirmation warning about unsaved position overrides.
- Manifest edits are saved immediately, while preview placement changes are pending until Apply/Save Return.
- There is only one Save & Return button at the bottom of the build editor, below the manifest.

Desired behavior:
- Back to Project should return immediately when there are no unsaved preview changes.
- If there are unsaved preview changes, Back to Project should ask whether to save and go back or discard and go back.
- A second Save & Return control should appear below the preview area and behave exactly like the bottom Save & Return control.

Fix guidance:
- Centralize build-editor exit behavior so header Back, preview Save & Return, and footer Save & Return use the same save/discard logic.
- Use the preview module's pending override state as the dirty signal, or expose a small helper from the preview module rather than duplicating state checks.
- Keep manifest edits out of the unsaved-dialog flow unless manifest editing later becomes batched.

Verification:
- With no pending placement changes, Back to Project shows no dialog.
- With pending placement changes, the user can save-and-return or discard-and-return.
- Both Save & Return buttons apply pending placement changes before returning.

## 6. "Modified from preset" misses placement-only changes

Priority: medium

Observed behavior:
- Adding, removing, or editing manifest parts sets `draft.user_modified`.
- Saving placement overrides does not set `draft.user_modified`.
- Builds that only move/rotate/resize/hide a placement do not show `modified from preset`.
- Resetting overrides stores empty override objects in some flows, which can leave noise in `placement_overrides`.

Desired behavior:
- A build based on a preset should show `modified from preset` when either the manifest differs from the preset or placement overrides differ from the preset.
- Resetting an override back to the preset/default should remove or normalize that override so the modified indicator can clear correctly.
- Custom/no-preset builds should continue to show as custom when user-edited.

Fix guidance:
- Do not rely only on `user_modified` for preset drift. Compute or store a normalized "differs from preset" signal based on manifest fields and placement overrides.
- Normalize override dictionaries before comparison so empty objects and default-equivalent values do not count as changes.
- Consider adding a backend summary endpoint or extending draft summaries so the UI does not need to duplicate preset comparison logic in multiple places.

Verification:
- Move a preset part in the preview, apply changes, return to project: the build card shows `modified from preset`.
- Reset that placement to default and return: the modified indicator clears if there are no other differences.
- Add/remove/edit a part still marks the build as modified.

## 7. Related cleanup and regression coverage

Priority: medium

Observed behavior:
- Some docs and tests describe older paths or expected behaviors, such as flat project files or internal IDs as unit IDs.
- The current project storage uses `workspace/projects/{project_id}/project.json`, while some brief/docs still mention flat `{project_id}.json` files.
- Tests exist for `project_dirs.py`, but the helper is not wired into generation.

Desired behavior:
- Documentation, tests, and behavior should describe the same project/draft/output lifecycle.
- Tests should catch the specific user-visible regressions above without being coupled to fragile UI implementation details.

Fix guidance:
- Update docs after behavior fixes, especially project workflow/output-path sections.
- Add service-level tests for data flow and one or two focused UI tests if a browser test harness is already available.
- Keep tests centered on outcomes: populated drafts, correct options, correct output location, clean unit labels, correct dirty indicator.

Verification:
- Full relevant test subset passes.
- Manual smoke flow: create project, choose preset, setup build, adjust placement, save/return, generate PPTX, export PDF, verify output folder and labels.
