# Stage 1 local pilot results

**2026-09-10 — native, ARM64 Linux and emulated AMD64 Linux proofs passed.** No Azure trial,
subscription, deployment, production connection or Power Automate activation occurred.
All existing uncommitted Calendar/Operations work remains in place. Repository `output/`
and `tmp/` were not used or modified. No release, commit or push was made.

## Implemented

- `python -m dtm_buildsheet.headless` selects a disposable workspace before application
  imports, forces cloud off, reuses the existing HTTP routes/UI/generator, and starts no
  desktop/cloud/QBO/acceptance workers. SIGINT/SIGTERM stops accepting requests and drains
  in-flight requests. Desktop launch, packaging dependencies and default paths are retained.
- The local pilot blocks provider/native routes, desktop QBO credential-store construction,
  unexpected Python socket connections/DNS and native process launches. Only headless
  LibreOffice conversion subprocesses are permitted. Health reports mode and blocked-attempt
  count without identity or workspace details. Basic Host/Origin checks protect the local
  browser surface; they are **not multi-user authentication**.
- Two synthetic agency/project/draft fixtures: typical (12 parts) and dense (92 parts,
  12 deterministic 1600×2400 / 2400×1600 reference images). Both have actual vehicle IDs,
  equipment placements and project-linked drafts. Cached reference media follows the normal
  photo-resolution path. Seeds run once and preserve later edits.
- Pilot PDFs can only convert PPTX files within pilot output. Each LibreOffice job uses a
  disposable profile. Native PDF fallback is disabled. A pilot-only Downloads panel lists
  PPTX/PDF artifacts by server-derived IDs; paths and symlinks outside output cannot download.
- An allowlisted build-context tool copies current code/UI, sanitized rendering configuration,
  equipment/vehicle art and the blank PPTX template. It excludes default agency/rep/cloud data,
  live presets, QBO links, credential files, config history, Git metadata and user directories.
  Every staged input has a SHA-256 manifest. The Python base image digest and dated Debian
  snapshot are pinned and were verified with the registry/snapshot providers. Docker/Compose files define a non-root runtime,
  LibreOffice/fonts, read-only root filesystem, isolated volume, local port publication,
  internal network, resource limits and health check. Desktop dependencies remain unchanged.

## Actual proof and measurements

Native Apple Silicon **arm64, macOS 26.5.2, Python 3.14.2**, using the bundled headless
LibreOfficeDev **26.8.0.0.alpha0** executable (build `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`).
Linux target is Python 3.11; its separate measurements appear below.
These figures **do not establish Azure sizing or cost**.

| Measurement | Actual native result |
|---|---:|
| Fresh-workspace startup, including fixtures | 1.204 s |
| Same-workspace restart to health | 0.277 s |
| Idle process-tree RSS after 5 s | 64.66 MiB |
| OS-reported idle process-tree CPU sample | 0.0% |
| Graceful shutdown | 0.606–0.611 s |
| Typical: PPTX / PDF conversion | 0.246 s / 1.651 s |
| Typical: sampled peak process-tree RSS | 288.98 MiB |
| Typical: output | 8 pages; 4,889,091-byte PPTX; 481,866-byte PDF |
| Dense: PPTX / PDF conversion | 4.304 s / 4.858 s |
| Dense: sampled peak process-tree RSS | 567.34 MiB |
| Dense: output | 20 pages; 56,640,072-byte PPTX; 7,054,583-byte PDF |
| Final staged context | 370 files; 53,940,842 bytes including manifest |
| Application wheel (not container image) | 48,873,158 bytes; built successfully offline |
| Container image size / Linux limits | See separate Linux results below |

Startup uses a fresh workspace, not a cold OS filesystem cache. RSS is sampled every 200 ms
with `ps`, summing the server and descendants including LibreOffice, excluding the browser.
It can miss brief peaks and double-count shared pages; it is not cgroup memory accounting.
The idle CPU figure is one OS-reported sample, not a sustained utilization benchmark.

The real browser opened Projects and a configured build, edited installation notes and verified
the saved draft. Both fixtures generated through the existing draft/PDF endpoints. All four
browser downloads matched server bytes by SHA-256; both PPTX ZIPs passed integrity checks.
Both builds have 15 placements. Server blocked-egress count, browser errors and external
browser requests were all **zero**. The runner stopped its servers after the proof.

Poppler rendered all 28 PDF pages. Contact sheets and full-size representative vehicle,
photo and manifest pages were inspected: vehicle/part art present, all 12 reference images
present on four appendix pages, aspect ratios preserved, comments readable, repeated manifest
headers and pagination intact, no observed clipping. PDF fonts include Carlito, DejaVu Math
TeX Gyre and Linux Libertine. The Linux rendered review is recorded separately below.
PyMuPDF emitted structure-tree warnings when rasterizing the initial PDF; Poppler rendered
cleanly. PDF accessibility/tag structure is not certified by this visual proof.

Known fixture warnings are retained: electronics at text-only equipment-tray/console locations
have no diagram coordinates, and harness rows have no location (1 typical / 81 dense). They
remain visible in the manifest. There are no unmapped parts or missing-reference warnings.
This stage does not change those existing renderer rules or golden masters.

Evidence: `/private/tmp/dtm-pilot-results-stage1-final/results.json`, `server.log`,
`editor.png`, `typical.pptx`, `typical.pdf`, `dense.pptx`, `dense.pdf`, and Poppler page PNGs.
Disposable workspace: `/private/tmp/dtm-local-pilot-stage1-final`.
The initial failed workspace was removed after fixing the renderer's nested desktop-seeding
call and sanitizing the QBO-dependent refresh-kit menu; regression coverage now exercises real
generation and asserts that desktop default files never appear in the pilot workspace.

Verification: `DTM_CLOUD=0 .venv/bin/python tools/verify.py changed` passed **517 tests,
1 skipped, 4/4 selected browser flows**. Import boundaries: **3 kept, 0 broken**.
`git diff --check` passed. The later `--ui-only` proof also passed edit/save with zero egress
or browser errors; the final pinned build context was regenerated and syntax checked.
No full release gate was warranted for this local prototype.

## Linux container gate — local ARM64 run, 2026-09-10

Installed the local Colima/Docker runtime for the authorized proof in a dedicated profile with no host
directory mounts and no SSH-agent forwarding. Built the staged context at
`/private/tmp/dtm-pilot-linux-context-relay3-unique`; the checkout, `output/` and `tmp/` were not
used as container inputs. The final image is Linux **arm64**, 396,900,402 bytes. Azure Container
Apps currently requires Linux `amd64`, so these timings and memory figures are Linux behavior
evidence only, not Azure performance claims.

The relay fix was required because Docker accepted a published port but did not expose it from an
internal-only network. A fixed-destination loopback relay now joins the ingress network; Builder
remains only on the internal network. The image runs as UID 10001, read-only root, dropped
capabilities, no-new-privileges, 0.5 CPU/1 GiB and 1 CPU/2 GiB test profiles. Python requirements
were clean; LibreOffice 7.4.7.2 and Carlito font resolution were present.

Results: start with an existing synthetic volume 6.887s; idle 51.47 MiB and 1.29% of one CPU;
0.5 CPU/1 GiB interactive
peak cgroup memory 68.54 MiB; UI load 1.195s, editor open 0.307s, save 0.493s. Restart took
1.717s and preserved edited draft hashes. At 1 CPU/2 GiB, typical export was 8 pages,
15 placements, PPTX 0.244s / PDF 1.200s / 4,889,091B / 335,058B.
Dense export was 20 pages, 15 placements, PPTX 5.804s / PDF 5.485s / 56,640,089B /
6,740,227B. Across the combined export run, sampled peak cgroup memory was 491.87 MiB;
the kernel-recorded peak was 522,620,928 bytes (498.41 MiB). These are not per-fixture peaks.
Both completed without OOM; fonts and page layout
were visually reviewed from all 28 Poppler-rendered pages. The internal network blocked
Graph, QuickBooks and public-IP connection attempts. Browser errors and HTTP errors were zero.

Evidence: `/private/tmp/dtm-pilot-linux-arm64-final2/container-results.json`, `container.log`,
`interactive/`, `exports/`, `typical-contact.png`, `dense-contact.png`; the final staged context
and relay build logs are `/private/tmp/dtm-pilot-linux-context-relay3-unique` and
`/private/tmp/dtm-linux-build-relay3.log`. Colima profile `dtm-pilot` is stopped. An isolated
AMD64 profile download was interrupted before completion; that attempt established no AMD64
result. The later Rosetta run uses the existing local VM instead.

## AMD64 Linux compatibility proof — 2026-09-10

The existing `dtm-pilot` ARM64 VM ran AMD64 userspace through already-installed Rosetta.
No second VM download or new runtime installation was needed. Both the Docker image metadata
and running Builder/relay image IDs were verified. The final Linux AMD64 image is
`sha256:a6837aa9eeb05cc80b1081500c13c8270f2295e6e826c836f8d1511f6ff821b7`,
400,900,598 bytes as reported by Docker. It uses Python 3.11.16, LibreOffice 7.4.7.2 and Carlito,
runs as UID 10001 with no broken Python requirements, and retains the isolated network,
read-only root, dropped capabilities, resource limits and synthetic volume.

These are emulated local compatibility measurements, **not Azure performance or cost forecasts**.
The browser client is macOS ARM64; its nested report describes the client. The outer report's
`image`, `requested_platform` and `runtime` identify the Linux AMD64 server.

| Measurement | AMD64 through Rosetta |
|---|---:|
| Start to reachable health, existing synthetic volume | 15.542 s |
| Idle cgroup memory / CPU over a 5 s window | 71.09 MiB / 3.83% of one core |
| 0.5 CPU / 1 GiB: UI load / editor / save | 2.864 / 1.107 / 0.514 s |
| Interactive sampled / kernel peak memory | 94.81 / 106.02 MiB |
| Restart to health, edited draft hashes preserved | 2.883 s |
| Typical PPTX / PDF conversion | 0.508 / 3.687 s |
| Typical output | 8 pages; 4,889,091-byte PPTX; 335,058-byte PDF |
| Dense PPTX / PDF conversion | 6.782 / 10.527 s |
| Dense output | 20 pages; 56,640,092-byte PPTX; 6,740,228-byte PDF |
| Combined export sampled / kernel peak memory at 1 CPU / 2 GiB | 595.75 / 602.19 MiB |

All four browser downloads matched the server bytes. Both exports had 15 placements; their
known text-only location warnings were unchanged. Browser/HTTP errors, unexpected browser
requests and application blocked-egress counts were zero. Separate network probes to Graph,
QuickBooks and a public IP were blocked. No OOM occurred. Poppler rendered all 28 pages;
contact sheets plus representative manifest/photo pages showed expected fonts, images,
aspect ratios, repeated headers and pagination without observed clipping. No golden changed.

The initial AMD64 attempts exposed an existing UI race: `initProjectsTab()` selected the list
after awaiting its refresh and could dismiss a draft opened during that wait. Navigation now
selects the list immediately and refresh completion only renders list content. The browser
regression holds a refresh pending, opens a draft, then verifies the editor survives completion.
The pilot client now saves a failure screenshot/HTML if the notes editor cannot be reached.
The successful proof uses this fix with no artificial navigation delay.

Evidence: `/private/tmp/dtm-pilot-linux-amd64-final/container-results.json`, `interactive/`,
`exports/`, `rendered/`, `typical-contact.png`, `dense-contact.png`; input manifest under
`/private/tmp/dtm-pilot-linux-amd64-context-final`. Build/proof logs:
`/private/tmp/dtm-pilot-amd64-build-final.log`, `/private/tmp/dtm-pilot-amd64-proof-final.log`.
Focused verification after the navigation fix: **654 passed, 1 skipped, 4/4 browser flows**
(`/private/tmp/dtm-amd64-focused-navigation.log`). `git diff --check` passed. The runner stopped
all proof containers and Colima profile `dtm-pilot` is stopped; synthetic volume/image caches
remain available. Stage 1's local compatibility gate is complete.

## Stage 2 — local shared-user boundary, 2026-09-10

The owner explicitly requested the next stage while the Linux gate remained open. Implemented
the request-scoped adapter seam and separate fail-closed WSGI boundary, tenant-specific signed
identity checks, durable expiring/revocable sessions, CSRF/origin checks, resource revision and
ACL ports, owner-bound opaque downloads, and bounded job leases/checkpoints/immutable archival.
Azure Tables is the selected durable metadata adapter; local proof uses synthetic SQLite outside
the shipped package. Existing role policy is reused; hosted requests never inherit local AppAdmin.

The proof uses synthetic signed users and a real loopback Waitress listener. No Azure auth,
Graph/QBO, keychain, trial or deployed service is used. Review files are under `packaging/hosted/`.
The original desktop/Stage 1 UI remains intact. All legacy hosted routes are closed, including
Operations/Calendar/cloud/QBO routes with their own desktop guards. Production document/worker
adapters and central provider polling are deliberately disabled for their later isolated tests.
See [HOSTED_BOUNDARY.md](HOSTED_BOUNDARY.md) for supported endpoints, route audit and open gates.

Local dependencies installed in `.venv`: Azure Tables 12.7.0, Azure Identity 1.25.3, Azure Core
1.41.0 and Waitress 3.0.2 (PyJWT 2.13.0 already present). They are an optional `hosted` extra;
CI tests/audits include it, desktop packaging does not. Reproduce with
`.venv/bin/pip install -e '.[dev,hosted]'`, then `DTM_CLOUD=0 .venv/bin/python tools/verify.py changed`.
Final focused result: **561 passed, 1 skipped, 4/4 selected browser flows**, including **44 hosted
boundary cases**. The route inventory tests all **127 legacy path patterns** against three HTTP
methods; none dispatches through the hosted boundary. The archival crash test preserves a
completed job's idempotency key across copy/removal interruption, and the maximum four-job,
64-step queue fits the Table payload ceiling. Import contracts: **3 kept, 0 broken**;
`git diff --check` passed. Review JSON parses locally; ARM/cloud validation has not run.
Evidence logs: `/private/tmp/dtm-stage2-changed-final.log`,
`/private/tmp/dtm-stage2-boundary.log`, `/private/tmp/dtm-stage2-imports-final.log`.
No release gate or golden updates. All temporary test HTTP listeners were stopped.

## Next step

Stage 1's local runtime/export gate is complete, including AMD64 compatibility. Stage 2's local
security/storage and operational preparation are implemented. The concrete resource/cost review
and sole-user/alert selection are now recorded in [AZURE_RESOURCE_REVIEW.md](AZURE_RESOURCE_REVIEW.md).
The owner confirmed no current subscription and a $200 trial offer and will handle activation.
Deployment templates are now prepared locally; do not repeat offer/account discovery. Actual platform auth, metadata permissions,
provider integration and full hosted parity remain unverified. No mobile UI design exists yet;
the shared responsive UI remains planned. All Azure actions remain unstarted.

Architecture requirement checked against [Microsoft's container documentation](https://learn.microsoft.com/en-us/azure/container-apps/containers).
Local emulation follows [Colima's Rosetta support](https://github.com/abiosoft/colima).

## Hosted operational preparation — 2026-09-10

Built the separate Python-only Linux AMD64 boundary image using the pinned base and its own
dependency lock. The context contains 175 allowlisted inputs, with no UI/resources, real records,
headless fixture launcher or test adapters. Image ID:
`sha256:d25f109179fd0a62f0e607546934611ad7128ac85aa0944f442c556ca1a5bdf8`;
Docker-reported size **103,678,174 bytes**. Python 3.11.16; dependency check clean.

The real hosted factory passed with synthetic configuration, **Docker networking disabled**,
no mounts or published ports, UID 10001, read-only root, 0.5 CPU / 512 MiB and bounded temporary
storage. Missing configuration exited 1 with only fixed lifecycle events. Minimal health was
200; unauthenticated/root/forged-header/malformed-token requests returned 401 and no-store.
Restart repeated these checks. Startup plus negative HTTP checks took 5.478 s; one cgroup memory
observation was 81.90 MiB. These are local emulated smoke measurements, not sizing forecasts.
The container was removed and the dedicated Colima profile stopped afterward.

Added bounded exact-ETag cleanup for expired sessions and artifacts, defaulting to dry-run.
Artifact cleanup retains a retry marker until safe file removal completes. Job archives/retry
keys are never removed. Logical snapshots exclude sessions, credentials, files and business
records. Create-only restore targets an empty partition, interrupts active jobs and writes a
durable fence that blocks all enqueue/claim/advance operations until provider reconciliation.
Synthetic tests cover conflict races, symlinks, file failure, corrupted snapshots, wrong tenant,
existing targets, partial restore/restart and retry keys absent from an older backup.

Hosted stdout telemetry uses fixed schemas only. Tests and the real container prove sensitive
sentinels, malformed tokens and provider exceptions do not reach logs. Successful health events
are omitted. Reviewed retention/backup/monitoring procedures and an unsubmitted aggregate KQL
query are documented in [HOSTED_OPERATIONS.md](HOSTED_OPERATIONS.md). No schedules, backups,
alerts or cloud identities were provisioned; real Table access and protected backup recovery
still need the isolated platform tests. The full Builder UI and provider workers remain closed.

Focused verification: **663 passed, 1 skipped, 4/4 browser flows**, including **53 boundary tests**.
Import contracts: **3 kept, 0 broken**. `git diff --check` and review JSON parsing passed.
Evidence: `/private/tmp/dtm-hosted-image-proof-20260910/results.json` and `container.log`,
`/private/tmp/dtm-hosted-context-20260910/context-manifest.json`,
`/private/tmp/dtm-hosted-build.log`, `/private/tmp/dtm-hosted-readiness-changed.log`,
`/private/tmp/dtm-hosted-readiness-imports.log`. No release gate or golden updates.

## Resource/cost review — 2026-09-10

The owner confirmed **only seth@dtmfleet.com** for access and cost/error notifications. Prepared
Central US resource candidates, least-privilege assignments, proposed maintenance/rotation owner,
alert thresholds and a nondeployable input inventory. No account IDs were guessed from email.
Public Retail Prices API responses were retrieved read-only; selected meters and reproducible
formulas are in `packaging/hosted/cost-review.json`. Raw source responses are external evidence
under `/private/tmp/dtm-azure-cost-review-20260910/`.

Boundary-only sizing: 0.5 vCPU / 1 GiB, scale 0–1, 40 active hours and 100,000 requests per
730-hour month. Estimated **$13.15 before grants**, **$10.95 with full compute/request grants**;
logs conservatively ignore their free allowance. Proposed $15 budget alerts are notifications,
not a spending cap. Later warm/full app scenarios and assumptions are explicitly separate.
No Azure account was accessed, CLI installed, trial activated, resource created or message sent.
Local app behavior is unchanged; Docker remains stopped. Focused verification passed **663 tests,
1 skipped and 4/4 selected browser flows**, with Python/JS syntax checks. All review JSON parsed;
an independent Decimal calculation reproduced all four cost scenarios and checked sole-user and
no-deployment flags. `git diff --check` passed. Evidence:
`/private/tmp/dtm-resource-review-changed.log`. No full release gate or golden changes.


## Deployment template preparation — 2026-09-10

Accepted the owner's confirmed subscription/offer status without accessing Azure. Added three
Bicep templates for foundation resources, internal-first app/auth and opt-in monitoring/budget.
The app uses a registry manifest digest, required secure parameters, sole-employee object-ID
restriction, signed-token boundary, cloud-off configuration and a 0–1 replica limit. Foundation
roles target only the registry and exact metadata table; token/backup containers are separate.
No Entra registration, image publication, cloud validation, deployment or notifications occurred.

`tools/pilot/verify_azure_templates.py` compiles in memory and checks security/cost constraints.
Bicep 0.47.16 passed all three templates without warnings; eight deliberately unsafe template
mutations were rejected (public default, plain-text secret parameter, anonymous-route expansion,
extra replicas, anonymous registry, leaked secret output, missing employee restriction and
unbound alert query). Compiler download hash matched the official GitHub release asset.
Focused gate: **663 passed, 1 skipped, 4/4 browser flows**; syntax and `git diff --check` passed.
Evidence: `/private/tmp/dtm-pilot-iac-20260910/template-checks.log` and `changed.log`.

Execution order and remaining live validation are in `packaging/hosted/azure/README.md`.
The templates do not automate app registration, signing, operator backups/cleanup or expiry
reminders. Local Docker isolation flags are not claimed as Azure platform capabilities. Existing
uncommitted work is preserved and repository `output/`/`tmp/` remain untouched.
