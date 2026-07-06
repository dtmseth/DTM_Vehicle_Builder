# Golden-Master Digest Specification (§8.1 Step 1a — design)

> **Status**: design + validated prototype (this session). Implementation (full corpus
> recording, pytest wiring, CI) is the follow-up Sonnet session — see §7.
>
> **What this pins**: the terminal outputs of the generation pipeline — the rendered
> `.pptx` build sheet and the `BuildPlan_*.json` plan file — so that any refactor of
> planner/renderer code (roadmap Phases D/E) can be proven behavior-preserving.
> The normalizer prototype lives at `tests/golden/digest.py`.

---

## 1. Empirical method (how this spec was grounded)

Two independent CLI runs (`python -m dtm_buildsheet.generator_cli
samples/input/Test_Build_Tuesday.xlsx`), 3 seconds apart, in separate processes (so
per-process hash randomization differed). All three outputs of each run were captured and
compared: byte-compare of the JSON plan and markdown summary; zip-entry listing, per-entry
extraction diff, and `zipinfo` metadata diff of the `.pptx`. Sensitivity was validated by
perturbing one rendered value (`_LEGEND_LEFT` in `render_ppt.py`, 5.80″ → 5.90″),
regenerating, and diffing digests; the perturbation was then reverted and a fourth run
confirmed the digest returned to baseline byte-for-byte.

## 2. Nondeterminism catalog (empirical, not guessed)

What actually varies between two identical-input runs:

| # | Artifact | Varies | Source |
|---|---|---|---|
| N1 | `.pptx` **filename** | wall-clock timestamp segment (`…_Updated_Jul06_2026_2-50-10PM.pptx`) | `build_output_filename()` (`render_ppt.py`, uses `datetime.now()`) |
| N2 | `.pptx` **zip entry mtimes** | every local-file header + central-directory entry (all 75) carries save-time wall clock | `zipfile` behavior under python-pptx `prs.save()` |
| N3 | — nothing else — | all entry **contents** (every XML part incl. rIds/shape ids/element order, all media bytes), entry **names**, and entry **order** were byte-identical across runs | |

JSON plan file and markdown summary: **byte-identical across runs**; no absolute paths,
usernames, or timestamps present. (The plan filename embeds `ProjectID`, which is stable
input data, not run state.)

Deterministic today but excluded from the digest anyway, because they are
identity/environment noise with no visual meaning — a mechanical refactor or a
python-pptx upgrade could churn them without changing what the user sees:

| # | Item | Why excluded despite being stable |
|---|---|---|
| E1 | `docProps/core.xml` / `app.xml` package metadata | fixed python-pptx boilerplate (2013 dates, "Steve Canny"); would drift on library upgrade or if code ever starts setting core props |
| E2 | Relationship ids (`rId*`) and media part names (`image1.png`, …) | assignment-order artifacts; pictures are identified by **content hash** instead |
| E3 | Numeric shape ids and auto-name suffixes ("Picture **12**", "Group **5**") | insertion-order counters; z-order (list position in the digest) already pins ordering |
| E4 | Zip compression details (deflate output, entry order) | zlib/OS-version coupled; the digest parses XML, never compares compressed bytes |

## 3. What the digest includes / excludes

`tests/golden/digest.py` produces **normalized JSON, not just a hash** — a golden-master
failure shows *what* changed (e.g. `top_emu: 1743487 → 1707194` on a named shape), not
merely that something changed. `canonical_dumps()` (sorted keys, 2-space indent, trailing
newline) is the single serialization used for storage and comparison; sorted keys make the
stored digest insensitive to cosmetic dict-ordering changes in the digest code itself,
while **list order is preserved because it is semantic** (slide order, z-order, paragraph
order, table rows).

**`pptx_digest(path)` includes** — everything a human would call "the build sheet":

- presentation: slide dimensions (EMU); per slide: layout name;
- shape tree in z-order, recursing into groups: shape kind, normalized name,
  left/top/width/height (EMU), rotation, flipH/flipV (read from raw `a:xfrm`, since
  `render_ppt._apply_shape_transforms` writes them directly);
- full text content as paragraphs → runs with formatting (bold/italic/size/font/color);
- table contents: dimensions, column widths, row heights, per-cell text + runs;
- pictures: SHA-256 of the image **bytes** + extension + crop, so an asset swap is caught
  even at identical geometry;
- fill type/color and line color (best-effort; absent when python-pptx can't resolve).

**Excludes**: N1/N2 (never sees filename or zip metadata — it parses package contents) and
E1–E4 above.

**`json_digest(path)`**: parse + canonical re-dump of the plan JSON. The plan is already
byte-deterministic, but going through the parser means byte-level noise (key order, float
formatting) can never produce a false failure. The markdown summary is derived from the
same plan and is cheap to pin as a raw text snapshot; implementation may include it.

**Known blind spots (accepted for v1, documented so nobody assumes otherwise):**
slide-master/layout internals (template-owned, pinned indirectly by the template file),
speaker notes (renderer never writes them), autofit/word-wrap runtime behavior (a
PowerPoint display property, not in the file), and exotic fill types (gradient/pattern
detail beyond type+fore-color). If a refactor touches any of these, extend the digest
first, in its own commit.

## 4. Validation results (this session)

- **Determinism**: two independent CLI runs → `pptx_digest` outputs byte-identical
  (7,930-line canonical JSON; 181 shapes: 135 text boxes, 41 pictures, 3 tables, 2 groups —
  all captured, all 41 pictures content-hashed). Plan-JSON digests likewise identical.
- **Sensitivity**: the `_LEGEND_LEFT` 0.10″ perturbation changed the digest in 668 diff
  lines — the vehicle image box and every icon anchored to it moved, exactly the real
  visual consequence — then reverted cleanly to the baseline digest.

## 5. Corpus selection

Criteria: cover every **input adapter** (Excel upload, GUI-draft/project path), every
**vehicle type** with a distinct layout (`vehicle_layouts.json`: PIU, TRAVERSE, TAHOE,
DURANGO, F-150), and the renderer's edge behaviors (legend overflow → grid layout,
unplaced-part warnings, specify-palette, accessories, manifest slides).

1. **All four `samples/` workbooks** — `input/Test_Build_Tuesday.xlsx` (realistic,
   warnings present) and `generated/mock_realistic_piu.xlsx`, `generated/piu_full_build.xlsx`,
   `generated/piu_location_sweep.xlsx` (breadth: full-build and location-sweep stress the
   placement/legend paths).
2. **One real project per vehicle type** (per §8.1 Step 1a), exported from the live
   workspace and committed as fixture inputs. Real projects exercise the GUI-draft →
   `ProjectInput` adapter that the samples (Excel path) do not. Today only PIU layouts have
   real coverage in `workspace/projects/` (3 records); the recording session takes what
   exists and tracks missing vehicle types as corpus TODOs rather than blocking.
3. **Config snapshot**: generation output depends on `workspace/config/*.json` (which in
   dev mode is `resources/config/`). Each recorded digest must state the config it was
   recorded against; the harness generates under a **hermetic `AppPaths`** (frozen
   dataclass — `dataclasses.replace()` onto a tmp workspace seeded from
   `resources/config/`), never the developer's live workspace, so a config edit can't
   silently invalidate the corpus.

## 6. Storage layout & update protocol

```
tests/golden/
  digest.py                     # normalizer (this session)
  __init__.py
  inputs/                      # committed corpus inputs (real-project exports; samples/ referenced in place)
  expected/
    <case_name>/
      pptx_digest.json         # canonical_dumps(pptx_digest(...))
      plan_digest.json         # canonical_dumps(json_digest(...))
      meta.json                # input path, config source, recorded date, recorder commit
  test_golden_master.py        # pytest: generate → digest → compare (implementation session)
```

Digests are committed as plain JSON so a failure is a reviewable `git diff`, and stay
under pytest so they inherit the cloud-isolation guards (§3.1 preserve-invariant).

**Update protocol (per roadmap §3.2 — behavior changes are opt-in only):**

1. A golden-master failure is first treated as a regression. The diff of normalized JSON
   says what changed; the burden of proof is on the change being intentional.
2. An **intentional** behavior change re-records the affected digests via a re-record
   helper (one command, implementation session) in **its own commit** — never mixed with
   refactor commits — with a `ROADMAP.md` decision-log entry naming the change and why.
3. Digest-schema changes (extending the normalizer) re-record the whole corpus, also in
   their own commit, with the normalizer change and re-recording separated from any
   production change.
4. New corpus cases may be added any time; removing or weakening a case requires a
   decision-log entry.

## 7. Remaining for the implementation session (Sonnet, per §8.2)

1. **Hermetic harness**: pytest fixture building the tmp-workspace `AppPaths` (seed config
   from `resources/config/`, assets from `resources/assets/`), calling
   `generate_build_sheet()` directly (not the CLI subprocess), digesting all three outputs.
2. **Full corpus recording** per §5 (this session validated the design on one input only,
   per the Step 1a constraint), including real-project exports into `tests/golden/inputs/`
   and `meta.json` provenance.
3. **Re-record helper** (`python -m tests.golden.record` or pytest flag) implementing §6.
4. **Pytest wiring**: `test_golden_master.py`, parametrized over `expected/*/`, asserting
   `canonical_dumps(digest) == stored bytes`, with a readable-diff assertion message.
5. **CI**: runs under the Step 1d pytest job (no separate workflow needed).
6. Markdown-summary snapshot decision (include or drop, §3) made concrete.
