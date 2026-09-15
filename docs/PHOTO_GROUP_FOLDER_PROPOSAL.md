# Group reference folders — proposed follow-up

September 14 owner feedback: reference photos apply almost entirely to a unit group. A source folder under a single physical vehicle makes that ownership unclear. The owner proposed restoring a unit-group folder with shared reference photos alongside its individual vehicle folders.

## Recommended Company layout

```text
Company Files / Vehicle Project Database / Agency / Build Year /
  GMC 2500 - Park Ranger /
    Build Reference Photos /
    Unit 1 /
      Build PDF
    Unit 2 /
      Build PDF
  GMC 2500 - Water Patrol /
    Build Reference Photos /
    Unit 3 /
      Build PDF
```

Group folder identity must come from the durable BuildUnit ID. Labels above are illustrative; use the existing naming helper with collision handling for distinct groups with the same model/build type. Do not merge groups by a matching label. Even a one-vehicle group retains the same structure so adding vehicles does not change where references belong.

The shared Company reference folder assigns to the unit group. Unit-level reference handling is an explicit exception, not the primary upload workflow. Keep legacy per-unit source discovery during transition so the folders already created and the user's uploads remain usable. An optional year-level inbox stays unassigned. Existing notes, ordering, exclusions, source item IDs, and assignments survive relocation.

Shop continues to receive reviewed per-vehicle packages containing the applicable references and each vehicle's Completed Build Photos. If the visible group layer is restored in Shop too, move the entire vehicle subtree by ID so PDF-relative reference links and completed-photo ownership remain intact. A mutable group reference inbox must never silently change approved Shop instructions.

## Why this needs a coordinated change

The current lifecycle provisioner explicitly clears group-folder fields and places individual vehicles under the year. Company PDF and Shop package publishers independently compute the same flat path. Moving folders alone would leave old clients able to move them back or publish into the wrong location.

Before a live regrouping:

1. Implement one shared group-aware path contract for provisioning, Company PDF publication, Shop packages and photo/gallery folder actions. Retain existing group ID/path codec fields. Add an explicit layout version/cutover mechanism so older clients cannot undo the migration.
2. Discover group references by durable group folder ID and assign them to that group. Preserve explicit unassignment and source exclusions when files move; test already-known inbox photos as well as newly uploaded files.
3. Prepare an exact-ID migration map from project/group/vehicle records to current Company/Shop folders. Include existing reference files, same-name collisions, completed photos, published package paths and recovery steps. Preserve existing files and IDs; never infer record identity from names.
4. Validate the app and reviewed folder move on a bounded project, then roll out the compatible client behavior before expanding the migration. No live regrouping has been performed by this proposal.

## Wright County defect fixed separately

The running dev app had already discovered 16 Park Ranger reference photos, but they had no assignments. The previous scanner assigned only newly created assets; an existing unassigned inbox asset moved into a unit folder retained its item ID and therefore skipped assignment. Its path was updated, losing the opportunity on later scans.

The scanner now assigns an unassigned asset when it is first observed moving from the year inbox into a unit reference folder. Existing explicit assignments remain intact, and subsequent scans preserve unassignment. Regression coverage exercises the same-item-ID move, repeat scans, manual unassignment, and retained project-wide instructions.

Verification: all 11 scanner tests passed; `tools/verify.py changed` passed 751 Python tests with one skip. Six of eight browser flows passed on the initial run during parallel scheduling edits. The QuickBooks batch checklist passed its focused retry (1/1). The scheduling session subsequently reported its corrected `tab_load` flow passing (1/1, no console/network violations). Both initially failing flows therefore passed focused retries; a new combined changed gate remains with that session. This photo fix does not edit the Calendar flow.

The 16 existing Wright County Park Ranger photos were repaired through the running app's normal gallery assignment endpoint. Read-back confirmed 16 group/individual-gallery photos, unchanged asset count and source metadata, and unchanged vehicle records and other references. A separate read of the shared SharePoint project JSON verified all 16 group assignments were mirrored successfully. No SharePoint folders or source files were moved. Evidence is under the current task's `company-reference-folders/wright-repair/` visualization directory. The scanner code change needs a dev-app restart to load; the targeted assignment repair is already visible after reopening the gallery.
