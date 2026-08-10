# Production Release Plan

## Purpose

This is the working checklist for moving the current Part Picker / project-workflow update from
the development branch to the public `main` branch and then publishing it as a desktop release.
Update this document as release decisions are made; it is the single short record of what remains.

## Release decision

- **Release goal:** Ship the rebuilt Part Picker, completed legacy-project rebuilds, and the project
  workflow/UI improvements as the next public app update.
- **QuickBooks decision:** Do **not** block this release on connecting the app to production
  QuickBooks Online. Hide all public QB controls for this release; retain the catalog foundation
  and backend for a separate, explicit production launch.
- **Release type:** **Major — v3.0.0.** Owner chose the major-version transition for this complete
  Part Picker and project-workflow release. After the PR merges, run the Build workflow with the
  already-set `current` version; do not bump it a second time.

## Current starting point

- The two targeted legacy projects have been rebuilt with the new Part Picker.
- The approved release candidate was merged to `main` through
  [PR #8](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/8).
- A recoverable pre-integration backup branch exists at `codex/pre-main-integration-2026-08-10`.
- The cloud-off test, contract, golden-master, visual-PPT, and browser-smoke gates have been
  rerun after integration.

## Release audit — 2026-08-06

### What this release contains

- **Part Picker and catalog:** the SKU-level `parts_db` rebuild, product-driven choices, fixtures,
  render/size ownership, locations, accessories, and guided radio/radar/camera/console workflows.
- **Completed legacy work:** the two rebuilt legacy projects and their finalized picker placements.
- **Project/build UI:** the cleaner manifest, automatic placement saving, visual **Edit Part** route,
  Overview build cards, Project Details summary, manifest-facing per-part comments, shared
  project-wide final-page notes, and the removal of redundant build controls.
- **QuickBooks foundation:** catalog linkage, customer/agency sync, and non-posting-estimate code.
  This code is in the branch, but production QuickBooks remains disabled until its separate gate is
  complete.
- **Support work:** contracts, smoke coverage, docs, configuration/schema updates, and CI/release
  infrastructure needed by the new picker model.

### Branch and verification status

| Item | Current result | Release disposition |
| --- | --- | --- |
| Branch position | [PR #8](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/8) is merged to `main`; the post-merge checks and Mac/Windows builds passed | Release follow-up below must land before tagging/publishing |
| Working tree | Source and reference changes are committed; local `.hermes/` scratch notes remain intentionally untracked and excluded | Ready |
| Contract suite | 54/54 passed after reviewing and recording the intended pit-bar/wing-wrap and rendered-antenna data changes | Ready |
| Golden masters | 6/6 passed after visual review and deliberate post-integration re-recording | Ready; the accepted output includes the compact manifests, corrected rendering/legend behavior, nested child parts, build-card quantities, and the current image-sizing behavior |
| UI smoke suite | 15/15 passed after integration with no browser errors, external requests, or cloud access | Ready |
| Full cloud-off test suite | 1,924 passed, 1 skipped after the final v3.0.0 release-check fixes | Ready |
| Production dependency audit | Fresh Python 3.13 environment resolves cleanly with no known vulnerabilities | Ready; hosted audit also updates its installer before scanning |

### Open release gates

1. **Complete:** diagram-page warnings now list only components that were expected on that view
   but failed to render (missing coordinates/assets). Intentional manifest-only or other-view
   components stay out. Small failure sets remain on the diagram; larger sets receive a compact
   count there plus a paginated Rendering Exceptions page with every affected component and its
   reason. All six rebuilt golden outputs pass the canvas-overflow check.
2. **Complete:** the Parts Manifest now uses compact, category-separated pages (Lighting,
   Structural Equipment, Equipment & Electronics, and Other / Custom) with height-aware
   pagination. The rebuilt Toppenish output was visually reviewed and has no footer overflow.
3. **Complete:** final owner approval received; all six golden outputs were deliberately
   re-recorded and now pass. The accepted differences include compact category manifests, newly
   mapped front/rear interior light bars, radar/control/preemption items, corrected bumper
   rendering, nested child parts, and build-card quantities.
4. **Complete:** the current 15-flow UI smoke suite passes locally with no browser errors,
   external requests, or cloud access.
5. **Complete:** integrated the six newer `main` commits, preserved the current app-version,
   image-sizing, manifest, rendering, and update-behavior fixes, resolved the overlap with the
   Part Picker manifest initialization, and reran every gate above.
6. **Complete:** public QuickBooks controls are hidden behind the release flag. Do not enable them
   until the separate QuickBooks production gate is complete.
7. **Complete:** raised the release dependencies past the current audit advisories, corrected the
   case-sensitive push-bumper asset reference caught by Linux CI, and updated the audit job's
   installer before scanning. The refreshed hosted PR checks all passed.

## Release stability follow-up — 2026-08-10

Installer testing revealed that the background sync tried to download the full historical Drafts
archive on first launch. That can hit SharePoint throttling, make the shell appear unresponsive,
and delay the project list. This is a **release blocker**, but no public v3 tag/release has been
published yet.

- Startup and periodic sync must retrieve project records only; the project list can then populate
  without waiting on every historical build.
- Opening a build must retrieve only that requested draft if it is absent locally. An explicit build
  open may refresh that one cached draft, while preserving a locally newer unsynced edit.
- SharePoint HTTP/transport failures must be reduced to safe status-only errors. Temporary redirect
  URLs and their authorization query parameters must not reach logs or local API responses.
- Rebuild both installers after the fix. On a clean Windows profile, sign in and confirm the 2027
  projects appear; then open a build and confirm only that build is retrieved. On the existing Mac
  profile, confirm startup remains responsive and no bulk Drafts download occurs.

Do not create the public `v3.0.0` tag or announce the release until these checks pass.

## Release sequence

### 1. Finish the user-facing scope

- Complete the agreed UI cleanup and verify that build edits still save immediately.
- Update or add focused tests for each behavior change.
- Keep cloud disabled during local work (`DTM_CLOUD=0`) so development cannot overwrite the parts
  database from SharePoint.

### 2. Establish a green release candidate

- Resolve or explicitly approve every full-suite failure.
- Review every golden-master difference visually; do not re-record snapshots just to make the suite
  pass.
- Run the focused contract/config/planner/render tests.
- Run the authorized UI smoke suite and confirm all current flows pass.
- Check the final diff for accidental workspace data, generated outputs, secrets, or unrelated files.

### 3. Create clean checkpoints

- Divide the current work into understandable commits (for example: picker/data behavior, UI,
  tests/contracts, docs). Do not mix generated workspace files with source changes.
- Make a recoverable backup branch/tag before integrating `main`.

### 4. Integrate the public branch safely

- Merge the current `main` changes into the release branch or a dedicated integration branch.
- Resolve overlapping UI, rendering, configuration, and asset changes deliberately; preserve both
  the newer `main` fixes and the completed picker work.
- Do not force-push or overwrite `main`.
- Re-run the release-candidate checks after the merge.

### 5. Review and merge to `main`

- **Complete:** [PR #8](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/8) merged normally to `main`.
- **Complete:** post-merge checks and Mac/Windows artifacts completed successfully.
- **Required follow-up:** merge the startup/cloud-safety correction and rerun the installer checks
  described above before the public release tag is made.

### 6. Publish and validate

- Run the manual release workflow with the approved semantic-version bump.
- Confirm the version/tag and both installers match the merged commit.
- Install and smoke-test the release build on macOS; validate the Windows installer from its build
  artifact before announcing the update.
- On first live launch, confirm project/draft access and cloud sync behavior without modifying the
  production parts database unexpectedly.

## QuickBooks production launch (separate gate)

The branch already contains the QB foundation: secure keychain-based OAuth storage, parts sync,
customer/agency synchronization, and estimate preparation. Before users can treat it as a live
QuickBooks Online integration, complete all of the following:

1. Deploy the HTTPS OAuth relay and register the production redirect address.
2. Perform the documented sandbox connection/disconnect/reconnect and sync test cycle.
3. Submit and complete Intuit's App Assessment.
4. Configure the production client credentials in the OS keychain and run a controlled production
   validation.
5. Run the separate, approval-required production inventory transition: preview/map production
   items against the existing Builder catalog, preserve Builder-owned metadata, and verify one
   non-posting estimate before enabling routine reconciliation or background sync.

Until those steps are complete, decide before the public release whether QB controls are hidden,
disabled, or visibly labelled as internal/sandbox-only. Do not imply that production QB is ready.

## Owner decisions still needed

- Approve the pull request's final merge to `main` and the manual release workflow/version bump.

## Related references

- `docs/ROADMAP.md`
- `docs/audit/SESSION_HANDOFF_2026-07-13.md`
- `docs/audit/LEDGER.md`
- `docs/QUICKBOOKS.md`
- `docs/VERSIONING.md`
