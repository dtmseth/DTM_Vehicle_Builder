# Company per-unit reference folders

Implementation date: 2026-09-14. Desktop changes are local and unreleased.

**Follow-up:** The owner reported Wright County photos remaining unassigned and proposed restoring a group-level reference folder. The tracked-inbox-photo move bug is fixed, and 16 Park Ranger photos were assigned through the running dev app and read back successfully. See [PHOTO_GROUP_FOLDER_PROPOSAL.md](PHOTO_GROUP_FOLDER_PROPOSAL.md) for the proposed group layout, migration dependencies and repair evidence. No live regrouping has occurred.

## Staff workflow

Each physical vehicle has a Company folder under **Vehicle Project Database / Agency / Build Year / Vehicle**. Project provisioning now creates **Build Reference Photos** inside that vehicle folder, including vehicles added later. Its **Folder options → Open Company reference folder** action opens this exact location.

Drop JPG/JPEG/PNG files there through OneDrive or SharePoint. Opening Project Photos or a unit's Build Reference Photos gallery starts background discovery. Newly discovered files in a vehicle folder attach to that vehicle's **unit group**, so all applicable vehicles in that group receive the reference. Subfolders inside the reference folder are included. The year-level **Reference Photos & Videos** folder remains an optional unassigned inbox.

Source drive/item identity and the actual source path are retained. Renames and repeat scans do not duplicate attachments. Different files with the same filename remain separate. Explicit unassignment remains intact on subsequent scans; deleting reference metadata records a source exclusion without deleting the SharePoint file. Add it explicitly through the existing picker to reuse an excluded source.

New assigned references or changed source versions make the build output stale. Finalized vehicles show **Reference changes need review · Shop package unchanged**. Their publication state becomes `reference_review_required`; automatic retries and previously queued publication calls cannot publish this changed reference set. Review the references, regenerate/export the PDF, then approve the existing explicit Shop-package replacement flow. Reopening a finalized build still withdraws its app-owned Shop package. Discovery itself never uploads or deletes a Shop file.

Discovery resolves registered folder IDs before scanning, and rejects a result if the project's folder/group membership changed during the scan. An incomplete or inaccessible scan retains all existing metadata and shows a retry warning. A missing registered vehicle ID now stops provisioning instead of recreating a stale vehicle path.

## Existing-folder backfill

`tools/backfill_company_reference_folders.py` reads the shared project JSON records directly. It does not run desktop cloud sync or write local/shared project records. It also identifies JPG/JPEG/PNG files loose at an exact vehicle-folder root and, only after plan review, moves them into that vehicle's exact `Build Reference Photos` folder. PDFs, videos, folders, and other files are left untouched.

1. `plan --plan /absolute/path/plan.json` resolves each registered Company vehicle folder by ID and records the exact missing child folder, source project revision, current location, and eligible loose photos. `--exclude-project ID` explicitly records an omitted project.
2. Review every blocker and target. A file collision, unresolved parent, duplicate vehicle parent ID, conflicting library, or duplicate loose-photo name blocks application.
3. `apply --plan /absolute/path/plan.json --report /absolute/path/report.json` rechecks source revisions, parents, and each photo identity; creates only the named child under the exact parent ID; moves only planned supported image files; and reads each result back. Progress checkpoints make interruption reviewable. Existing child IDs remain intact. A changed source/parent/file stops the run for a fresh plan.

Recovery is additive: retain already-created folders and regenerate/reapply the plan. No deletion rollback is needed. This tool has no file-copy, rename, ancestor-creation, project-write, schedule-write, or Shop-write operation.

The September 14 audit read 57 shared projects. There are 102 valid Company vehicle parents across 56 projects, including the six vehicles in **Rice County Sheriff / Rice – 2027**. A separate 2026 Rice County project (`59975c01-15ac-4a41-a18e-134396fcf4f9`) still refers to an unavailable 2026 year and six unavailable vehicle IDs/paths. The current 2027 project is `41b7faa8-71a6-4b4c-958b-95909d1e94b8` and is included. Do not confuse these records, recreate the 2026 tree, rebind it by similar vehicle names, or delete it as part of this backfill.

Live execution completed: **102 folders created and 102 read-back verifications passed**, with no failures. A repeated live child-folder provision also preserved the existing folder ID. The current Rice 2027 units are included; only the older Rice 2026 project was excluded. The operation did not write project records, schedules, PDFs, photos, or Shop packages.

Evidence on this workstation:

- [Initial audit](/Users/skreev/.codex/visualizations/2026/09/14/01a0a09b-2b5d-7723-999e-e70d1bca693e/company-reference-folders/initial-audit.json)
- [Reviewed exact-ID plan](/Users/skreev/.codex/visualizations/2026/09/14/01a0a09b-2b5d-7723-999e-e70d1bca693e/company-reference-folders/reviewed-plan.json)
- [Verified backfill](/Users/skreev/.codex/visualizations/2026/09/14/01a0a09b-2b5d-7723-999e-e70d1bca693e/company-reference-folders/verified-backfill.json)

## Scope and verification

This finishes the Company per-unit **reference-folder** workflow. It does not implement automatic Shop-completed-photo copying to Company, HEIC decoding, capture-time ordering, direct uploads in Builder, always-on background scanning, or independent Company-only/Shop-only thumbnail access. Those remain separate batches in POST_MEETING_FEATURE_PLAN.md.

Focused regressions cover new/later-added vehicle folders, durable-ID relocation, deleted IDs, group assignment, manual unassignment, source exclusions, duplicate filenames, repeat scans, stale/failed scans, finalized publication gating, and exact-ID additive backfill/retry/collision handling. All **77 photo/folder/reference/publication/finalization tests pass** after the final hardening changes. The first changed gate passed 745 tests, one skip and eight selected browser flows. The later gate, while the parallel Calendar revamp was being edited, passed 739 tests and one skip, with seven of eight browser flows passing. Its sole failure was the Calendar cancellation review in `tab_load`, whose new explanation requirement was still being wired into the smoke flow by the scheduling session. That session was notified; the photo batch does not own or change that Calendar flow.

Scheduling work is separate; see SCHEDULING_REVAMP_SESSION_PROMPT.md. No Calendar, Operations or Azure implementation files were changed by this photo-folder batch.
