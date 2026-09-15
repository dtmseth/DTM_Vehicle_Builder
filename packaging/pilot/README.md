# Local pilot commands and Linux verification

See [the results log](../../docs/AZURE_PILOT_RESULTS.md) for measured native and Linux results.

## Reproduce locally

Use a new directory for a fresh seed; reuse a marked pilot directory to preserve edits.
The launcher accepts directories below the OS temporary root or `/tmp`, and `/pilot-data`
inside a container. It rejects ordinary nonempty workspaces and non-loopback native binding.

```bash
DTM_CLOUD=0 .venv/bin/python -m dtm_buildsheet.headless \
  --workspace /private/tmp/dtm-pilot-manual --seed-fixtures --host 127.0.0.1 --port 7665

# Automated native proof; new results directory required. Starts/stops its own servers.
DTM_CLOUD=0 .venv/bin/python tools/pilot/exercise.py \
  --launch-workspace /private/tmp/dtm-pilot-proof \
  --results /private/tmp/dtm-pilot-proof-results

# Narrow context and offline package proof (both succeeded during implementation).
.venv/bin/python tools/pilot/build_context.py /private/tmp/dtm-pilot-context
PIP_NO_INDEX=1 .venv/bin/pip wheel --no-deps --no-build-isolation \
  /private/tmp/dtm-pilot-context --wheel-dir /private/tmp/dtm-pilot-wheels
```

Open `http://127.0.0.1:7665`. Synthetic projects appear under **Started** because no Operations
acceptance is invented. Open a vehicle to edit, use its normal PDF export action, then open the
yellow **Downloads** panel and refresh. Sign-in/Estimates/native folder buttons report unsupported.
The automated client needs the existing Playwright/Chromium and PyMuPDF test dependencies.

`DTM_WORKSPACE_DIR` is an import-time path override for all mutable `AppPaths` fields and
legacy module constants; it does not by itself disable cloud. Only the headless launcher sets
the complete pilot policy. Do not run the desktop entry point to bootstrap pilot fixtures.

## Linux proof

Colima and Docker are installed in the dedicated `dtm-pilot` profile. Use its explicit socket
and disposable Docker config, without changing the user's default Docker context. On this Mac,
Rosetta is already installed and supports AMD64 execution inside the ARM64 Linux VM.
Azure Container Apps requires Linux AMD64; native ARM64 alone cannot close that compatibility gate.

Build only from a new staged context outside the checkout. No real workspace, keychain,
OneDrive or checkout directory is mounted in the VM or containers.

```bash
export DOCKER_CONFIG=/private/tmp/dtm-pilot-docker-config
export DOCKER_HOST=unix:///Users/skreev/.colima/dtm-pilot/docker.sock
colima start dtm-pilot --vm-type vz --arch aarch64 --cpus 2 --memory 4 \
  --disk 20 --root-disk 10 --mount none --ssh-agent=false --ssh-config=false \
  --activate=false --vz-rosetta
.venv/bin/python tools/pilot/build_context.py /private/tmp/dtm-pilot-context-new
docker buildx build --platform linux/amd64 --load -t dtm-local-pilot:stage1 \
  /private/tmp/dtm-pilot-context-new
DTM_CLOUD=0 .venv/bin/python tools/pilot/container_proof.py \
  --context /private/tmp/dtm-pilot-context-new \
  --results /private/tmp/dtm-pilot-linux-results-new \
  --docker-host "$DOCKER_HOST" --platform linux/amd64
colima stop --profile dtm-pilot
```

The proof verifies the requested image architecture and actual image IDs before exercising
**0.5 CPU / 1 GiB** UI edit/save, draft persistence across restart, and **1 CPU / 2 GiB** exports.
It records cgroup memory/CPU, OOM events, image size, versions/fonts, four byte-verified downloads
and blocked outbound connections. It stops its containers even on failure and preserves the
named synthetic volume. A reused volume gives a warm-workspace start, not fresh fixture seeding.
Render/review the exported PDFs separately; the runner's successful byte checks do not prove layout.

Builder belongs only to the internal Docker network. Docker does not publish its port there;
a bounded, fixed-destination relay connects the localhost-only port to Builder. The relay cannot
select an arbitrary destination. Neither service mounts host files. Do not expose this prototype
publicly or substitute it for the separate hosted authorization boundary.

The Python dependency lock, input manifest, immutable multi-architecture Python base digest and
dated Debian snapshot make build inputs repeatable. The registry digest and both snapshot Release
files were verified against their providers on 2026-09-10. Wheel resolution,
Compose networking/health/permissions and the non-root Linux conversion are verified for the
ARM64 and emulated AMD64 runs. The proof checks the intended image architecture; native arm64 or emulated amd64
timing on this Mac must not be presented as Azure performance.

Stage 2's local request/session/job/artifact contracts are implemented and tested; see
[HOSTED_BOUNDARY.md](../../docs/HOSTED_BOUNDARY.md). Full hosted UI, real provider adapters,
hosted credential storage and platform authentication remain unverified or unimplemented.
These commands authorize no infrastructure or live provider integration. Mobile UI design and
full mobile parity remain future work.
