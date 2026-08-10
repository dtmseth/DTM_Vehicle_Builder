# Continuation prompt — picker find-and-fix pass

Continue the owner-led DTM Vehicle Builder picker find-and-fix session in
`/Users/skreev/Desktop/DTM_BuildSheet_POC_v7`.

Read these fully before changing anything:

1. `AGENTS.md`
2. `docs/GOTCHAS.md`
3. `docs/audit/SESSION_HANDOFF_2026-07-13.md` (start at the 2026-08-05 update)
4. `docs/audit/LEDGER.md`
5. `docs/PARTS_DB_AND_PICKER.md`

Important safety rules: this tree is intentionally dirty from owner and prior-session work. Preserve
unrelated diffs; do not use reset/checkout, do not stage or commit, and run cloud-off
(`DTM_CLOUD=0`) so SharePoint sync cannot overwrite `parts_db.json`.

The most recent completed slice did all of the following:

- T-Series and Mega T-Series now use the warning-light configurator even when selected from the
  broad Lights leaf. The semantic mapping is `picker_primary_part_type` in `parts_db.json` and is
  applied by `src/dtm_buildsheet/app/routes/parts_db.py` and `ui/js/part_picker.js`.
- Center Plate of PB is available alongside Top of Push Bumper for all Front Scene products,
  including Pioneer SlimLine; Pioneer SlimLine also retains Under Tailgate for Rear Scene. Scene
  quantity drives normal picker dots and the renderer: one head is centered, while two or more
  use the location pattern or spread from a single-dot anchor.
- Custom-location placement supports all exterior views, normal placement + fixture dots, and a
  **Set your own** multi-point mode. Free points persist under
  `picker_config.custom_location.placements` and render through
  `planning/location_resolver.py` and `planning/planner.py`.
- Tracer lighthead setup now has independent Clear/Smoked lens pills.

The focused tests are green: 203 picker/planner/preview/config tests, 51 schema/service tests, and
44 parts-db contract tests. The contract snapshots were intentionally re-recorded in this slice. Do
not run the UI smoke suite without authorization. Then continue with the user's next concrete picker
defect, keeping the same find-cause → narrow fix → regression-test workflow.
