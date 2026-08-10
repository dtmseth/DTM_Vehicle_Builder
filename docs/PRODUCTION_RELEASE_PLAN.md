# Production Release Plan

## Purpose

This was the working checklist for moving the Part Picker / project-workflow update to public
`main` and publishing it as a desktop release. That release is complete; this document is now the
short record of what shipped, the safety correction made during installer testing, and the separate
QuickBooks gate that remains.

## Release decision

- **Release goal:** Ship the rebuilt Part Picker, completed legacy-project rebuilds, and the project
  workflow/UI improvements as the next public app update.
- **QuickBooks decision:** Do **not** block this release on connecting the app to production
  QuickBooks Online. Hide all public QB controls for this release; retain the catalog foundation
  and backend for a separate, explicit production launch.
- **Release type:** **Major — v3.0.0.** Owner chose the major-version transition for this complete
  Part Picker and project-workflow release.

## Release outcome — 2026-08-10

- **Published:** [v3.0.0](https://github.com/dtmseth/DTM_Vehicle_Builder/releases/tag/v3.0.0) is a
  public, non-prerelease GitHub release. Its tag points to `main` at
  `4e271b4636ee33fdc844ec8241103971aacc470f`.
- **Release path:** [PR #8](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/8) brought the
  main feature set to `main`; [PR #9](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/9)
  supplied the installer-discovered SharePoint startup correction before publish.
- **Installers:** the Mac DMG and Windows installer were rebuilt from that final `main` commit and
  uploaded to the public release and the SharePoint releases library.
- **Validation:** full cloud-off suite **1,928 passed, 1 skipped**; UI smoke **15/15**; contract,
  golden, package, design-signature, post-merge checks, and hosted Mac/Windows builds passed.
- **Current watch:** corrected installers are rolling out through the automatic updater. Owner has
  confirmed the corrected app works; complete the ordinary over-install confirmation on the
  previously installed devices before treating the rollout as fully settled.

## Release baseline

- The two targeted legacy projects have been rebuilt with the new Part Picker.
- The approved release candidate and its follow-up were merged to `main` through
  [PR #8](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/8) and
  [PR #9](https://github.com/dtmseth/DTM_Vehicle_Builder/pull/9).
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
  This code is included in v3.0.0, but production QuickBooks remains disabled until its separate gate is
  complete.
- **Support work:** contracts, smoke coverage, docs, configuration/schema updates, and CI/release
  infrastructure needed by the new picker model.

### Branch and verification status

| Item | Current result | Release disposition |
| --- | --- | --- |
| Branch position | PRs #8 and #9 are merged to `main`; the post-merge checks and Mac/Windows builds passed | Published |
| Working tree | Source and reference changes are committed; local `.hermes/` scratch notes remain intentionally untracked and excluded | Ready |
| Contract suite | 54/54 passed after reviewing and recording the intended pit-bar/wing-wrap and rendered-antenna data changes | Ready |
| Golden masters | 6/6 passed after visual review and deliberate post-integration re-recording | Ready; the accepted output includes the compact manifests, corrected rendering/legend behavior, nested child parts, build-card quantities, and the current image-sizing behavior |
| UI smoke suite | 15/15 passed after integration with no browser errors, external requests, or cloud access | Ready |
| Full cloud-off test suite | 1,928 passed, 1 skipped after the final v3.0.0 release-check fixes | Passed |
| Production dependency audit | Fresh Python 3.13 environment resolves cleanly with no known vulnerabilities | Ready; hosted audit also updates its installer before scanning |

### Completed release gates

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
archive on first launch. That could hit SharePoint throttling, make the shell appear unresponsive,
and delay the project list. This was corrected and verified before the public release.

- Startup and periodic sync now retrieve project records only, so the project list does not wait on
  every historical build.
- Opening a build retrieves only that requested draft when needed, while preserving a locally newer
  unsynced edit.
- SharePoint HTTP/transport failures now become safe status-only errors; temporary redirect URLs
  and authorization query parameters cannot reach logs or local API responses.
- Corrected installers were rebuilt and the release workflow completed successfully. The remaining
  rollout task is the normal automatic-update confirmation on older installed versions.

## Historical release sequence — completed

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
- **Complete:** the startup/cloud-safety correction merged through PR #9, the installer checks
  passed, and the public v3.0.0 release was tagged and published.

### 6. Publish and validate

- **Complete:** ran the manual release workflow with the approved version.
- **Complete:** confirmed the version/tag and both installers match final `main`.
- **Complete:** validated the release build and confirmed project/draft access through the
  corrected, project-first cloud sync.

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

Until those steps are complete, public QB controls remain hidden. Do not imply that production QB
is ready.

## Next owner decision

Choose the next development stream after the auto-update rollout settles:

1. **QuickBooks safety first:** build the isolated production-catalog preview and mapping report;
   do not connect routine production synchronization yet.
2. **Catalog/product work:** continue data curation and scope Kit SKUs, after confirming the
   `parts_db` repository seam needed for that feature.
3. **Foundational migration:** move the remaining legacy consumers from workbook rules to
   `parts_db`; valuable, but not the next user-facing priority.

## Related references

- `docs/ROADMAP.md`
- `docs/audit/SESSION_HANDOFF_2026-07-13.md`
- `docs/audit/LEDGER.md`
- `docs/QUICKBOOKS.md`
- `docs/VERSIONING.md`
