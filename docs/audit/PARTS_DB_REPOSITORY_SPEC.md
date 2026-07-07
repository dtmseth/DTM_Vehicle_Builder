# Parts-DB Repository — Interface + Migration Spec (§8.1 Step 4, design)

> **Status**: DESIGN — no production code changes in this session.
> **Executes**: in the Step 4 extraction session, which per §8.1 ordering runs **after the
> picker + placement cluster (Step 3) ships** and on top of the Step-1 pins.
> **Companion docs**: [AUDIT_REFACTOR_ROADMAP.md](../AUDIT_REFACTOR_ROADMAP.md) §4/§7/§8.1,
> [PARTS_DB_AND_PICKER.md](../PARTS_DB_AND_PICKER.md) (schema + three-axis model),
> [DATA_MODELS.md](../DATA_MODELS.md), ROADMAP.md decision log 2026-07-06 (workbook demotion).

**The one-sentence goal**: one repository module below `app/` owns all `parts_db.json`
read/write/query, consumable by `planning/` and `app/services` without upward imports,
importable without the GUI app (the parts-manager-app seam), replacing the baselined
planning→app violation at `planning/planner.py:152`.

---

## 1. Inventory — how parts_db is accessed today (verified against the repo, 2026-07-07)

### 1.1 The read path and its cache

`app/services/parts_db_service.py` (497 LOC) is the single read service:

- **`PartsDbService`** — lazy dict cache of `load_config("parts_db.json", paths)`
  (config.store: migrate → validate → return), ~23 typed queries hydrating
  `domain/parts_db_models.py` dataclasses, `validate_placement()` (the intersection rule),
  and `raw_doc()` — the escape hatch that returns the cached dict itself.
- **Singleton**: module-global `_instance`, keyed by `paths` object identity via
  `get_parts_db_service(paths)`; `reset_for_testing()` for pytest.
- **Two legacy fallback readers** (the 3-tier shim for name-keyed workbook-era queries):
  `LegacyWorkbookIndex` (own dict cache of `legacy_workbook_index.json`) and
  `LegacyFallbackReader` (uncached reads of `workbook_rules.json.part_rules`). Consumed via
  `products_for_legacy_part_type_label` / `product_for_legacy_model_string` /
  `manufacturers_by_legacy_name` / `models_by_legacy_name` / `locations_by_legacy_name`.
- **`invalidate()`** clears all three caches. Called from exactly two places: the routes'
  mutation helper and `qb_sync_service` after its writes.

**Caches held**: the service dict cache + legacy index cache (both in the singleton). Routes
hold none. The planner holds a per-call lazy reference. The UI holds JS state but talks only
HTTP. `qb_sync_service` keeps a separate QB-items file cache (not parts_db).

### 1.2 Consumers (who reads, who writes, who leaks)

| Consumer | Access | Notes |
|---|---|---|
| `app/routes/parts_db.py` (1,239 LOC) | reads via typed queries **and** `raw_doc()`; writes via `_mutate_parts_db` → `save_config_file` → `svc.invalidate()`; also a whole-doc `POST /api/parts-db` | The big one — see §1.3 for the leaked logic |
| `planning/planner.py:152–160` | **lazy upward import** `from ..app.services.parts_db_service import get_parts_db_service` on catalog miss; uses **only `list_part_types()`** (via `_find_part_type_by_name`) to synthesize render specs for picker-created parts | The baselined layering violation Step 4 retires |
| `planning/sku_resolver.py` | **pure** — takes `list[PartNumber]` as arguments, no I/O | Already the target pattern; no change needed |
| `planning/part_type_resolver.py` | **pure** — takes the parts_db doc as a constructor argument | Same |
| `app/services/qb_estimate_service.py` | reads `raw_doc()` (2 sites): QB-linkage index per part_number, `unbilled`-tag key set | Read-only; billing semantics (pending-QB DescriptionOnly, unbilled skip) live here |
| `app/services/qb_sync_service.py` | `raw_doc()` + deep-copy + `save_config_file` + `invalidate()` (3 sites): `reconcile_linked_parts` (fills pending-QB linkage), `link_item`, `unlink_item` | A **writer** outside the routes |
| `app/services/lighthead_resolver.py` | **pure** — `resolve_tracer(doc, …)` takes the doc; routes pass `svc.raw_doc()` | Target pattern |
| `config/schemas.py::_validate_parts_db` | validation registered in the config-store pipeline | Schema knowledge living in `config/` |
| `config/migrations.py` | `"parts_db.json": []` (no migrations yet) | Same |
| `tools/` (curate, qb_import_all, qb_apply_links, qb_inventory_import*, triage_products, seed_part_type_locations, populate_colors, phase5a, migrate_warning_lights, migrate_workbook_to_parts_db) | read the dev config JSON directly (`resources/config/parts_db.json` — the dev-mode config dir per GOTCHAS #6); write via `save_config_file` under `--write` / `--push-to-cloud` | Library-mode consumers that already exist — proof the seam is needed |
| UI JS (`sku_grid.js`, `part_picker.js`, `manifest_editor.js`, `part_manager.js`) | HTTP only (`/api/parts-db/*`) | Correct boundary; pinned by 1b/1c |
| Tests | `test_parts_db_service/dual_read/edit_routes/routes/schema_validation/compatibility_rules`, `test_qb_estimate_*`, `test_qb_sync_service` — all import the `app.services.parts_db_service` module path | Migrate per §2.2 test-migration discipline |

### 1.3 Placement/category/product logic leaked into the route layer

`app/routes/parts_db.py` carries substantial **judgment logic** that is not HTTP plumbing:

- **Module-level mapping tables** (all judgment, none data-driven):
  `_CATEGORY_PLACEMENT_ZONES`, `_PLACEMENT_ZONE_TO_TREE`, `_ZONE_TO_PLACEMENT_ZONES`,
  `_CATEGORY_TO_PLACEMENT_ZONES`, `_CATEGORY_KEYWORDS`, `_WARNING_ZONE_NAME`,
  `_ZONE_PRIMARY_KEYWORD` (+ its duplicate `_TREE_PRIMARY_KEYWORD`). The file itself flags
  `_ZONE_TO_PLACEMENT_ZONES` as a candidate to move into `parts_db.json`.
- **Category/part_type resolution**: `_pt_matches_category`, `_pt_in_category`,
  `_primary_part_type`, `_warning_home` (the warning-light single-home rule, in a route file).
- **Placement resolution**: `_resolve_category_locations`, `_resolve_product_locations`
  (which also loads `part_catalog.json` + `vehicle_layouts.json` — cross-config planning
  logic), `_catalog_parts_for_label`, `_default_views_for_label`.
- **Accessory resolution**: `_resolve_accessories` (3-source union: product-level,
  part_type-level, child-side accessory role).
- **The edit-command layer** (~350 LOC): `_handle_edit` with 15 actions, field whitelists
  (`_PRODUCT_EDIT_FIELDS`, `_SKU_EDIT_FIELDS`, `_PART_TYPE_EDIT_FIELDS`), `_mutate_parts_db`
  (deep-copy → mutate → metadata stamp → `save_config_file` → invalidate), plus
  `seed-light-tags` / `backfill-descriptions` batch conventions.
- **Response assembly that dips into `raw_doc()`** for data the dataclasses don't carry
  (manufacturer labels, placements doc, `location_options`, accessory fields).

### 1.4 Findings the design must answer (not fix in this session)

1. **F-1 · Stale cache after cloud sync.** The 60s sync loop (`app/server.py::_run_sync_cycle`
   → `sync_shared_settings_at_startup`) pulls `/Settings/parts_db.json` straight into the
   workspace config dir and bumps `data_version`, but **nothing invalidates the
   `PartsDbService` singleton cache**. A teammate's edit is invisible to this device's picker,
   SKU grid, and estimates until a local mutation or restart happens to call `invalidate()`.
   The repository must own invalidation as a first-class concern (§3.6); the fix itself is a
   flagged behavior improvement (§4, C4).
2. **F-2 · Hydration gap vs shipped conventions.** `domain/parts_db_models.py` predates the
   SKU-grid conventions: `PartType` lacks `location_mode`/`location_options`; `Product` lacks
   `reviewed`, `accessory_category`, `accessory_of_products`, `accessory_required`,
   product-level `accessories[]` and product-level `qb_*` fields. Routes compensate by dipping
   into `raw_doc()`. Any migration must preserve these fields *byte-for-byte* even though no
   dataclass carries them (§3.4 round-trip invariant); closing the gap is Stage C1.
3. **F-3 · `_empty_parts_db_doc()` omits `accessory_categories`** (and `naming_rules` is
   present but `accessory_categories` — consumed by `_resolve_accessories` — is not). Benign
   today because real docs carry it; the repository's empty-doc factory should include the
   full key set.
4. **F-4 · Doc drift**: GOTCHAS #21 still claims "`parts_db.json` is populated but not wired
   into production reads" — false since the planner fallback, picker, estimates, and SKU grid
   shipped. Reconcile when the extraction lands (three-way rule, roadmap §7).
5. **F-5 · Duplicate keyword tables** (`_ZONE_PRIMARY_KEYWORD` ≡ `_TREE_PRIMARY_KEYWORD`, and
   a third inline copy `_zone_keyword` inside `_resolve_category_locations`) — one concept,
   three homes; consolidation target when the placement logic moves (C3).

---

## 2. Where the repository lives

### 2.1 Home and name

**`src/dtm_buildsheet/parts_db/`** — a small package (not one file: schema knowledge,
queries, legacy shims, and persistence ports are distinct concerns, mirroring the
resolver-per-concern convention in `planning/`):

```
src/dtm_buildsheet/parts_db/
    __init__.py       # public surface: get_repository, PartsDbRepository, reset_for_testing
    repository.py     # PartsDbRepository: cache, invalidate, typed queries, hydrators,
                      #   validate_placement, raw_doc (transitional), save/mutate (Stage C)
    schema.py         # _validate_parts_db (moved from config/schemas.py), empty-doc factory,
                      #   parts_db migration list (re-exported into config/migrations registry)
    legacy.py         # LegacyWorkbookIndex, LegacyFallbackReader, *_by_legacy_name queries —
                      #   QUARANTINED transition shims, retire with Phase 4 consumer migration
    writer.py         # (Stage C) PartsDbWriter protocol + LocalPartsDbWriter
```

The name matches what everything else calls this store (`parts_db.json`, the docs, the seam
register). Dataclasses **stay in `domain/parts_db_models.py`** — they are the domain
vocabulary, `planning/` already may import domain, and moving them would churn every import
for no boundary gain.

### 2.2 Import-linter layer position

Revised `layers` contract (a pyproject-only edit, verified feasible against the real graph —
nothing below the new positions imports upward):

```
app → inputs → config → planning → parts_db → storage → rules → domain → naming:paths
```

Changes from today (`app, inputs, config, storage, planning, rules, domain, naming:paths`):

- **`parts_db` inserted below `planning`** — so `planning/` imports it *downward* (the
  roadmap explicitly blesses planning consuming the repository; the §4 "planning imports
  domain only" target is amended to "domain + the parts_db repository").
- **`storage` moves below `parts_db`** — so the repository can use `storage.local`
  atomic-write primitives. Verified: `storage/` imports only stdlib + `paths`;
  nothing in `planning`/`rules`/`domain` imports `storage` today, so the reorder
  legalizes nothing that exists and forbids nothing that exists.
- `config` stays **above** `parts_db`: `config/schemas.py` imports the parts_db validator
  *downward* from `parts_db.schema`, keeping `load_config`/`save_config("parts_db.json")`
  behavior byte-identical for every existing caller during the transition.

What the repository may import: `domain`, `storage`, `naming`, `paths` — **nothing in
`app/`, `config/`, `inputs/`** (this is what makes it the parts-manager-app seam: a bare
`import dtm_buildsheet.parts_db` must not pull in pywebview, HTTP, Graph, or config-store
machinery).

Read path consequence: the repository owns its own tiny loader (workspace config path from
`AppPaths`, `json.loads`, apply parts_db migrations, validate via `schema.py`) instead of
calling `config.store.load_config` (which is above it). ~15 lines, single-sourced validation
because config.store's registry points at the same `parts_db.schema` functions.

---

## 3. The repository interface

### 3.1 Construction and lifecycle

```python
class PartsDbRepository:
    def __init__(self, paths: AppPaths, writer: PartsDbWriter | None = None): ...
    def invalidate(self) -> None: ...           # clears doc + legacy caches
    def raw_doc(self) -> dict: ...              # TRANSITIONAL escape hatch — see §3.4

def get_repository(paths: AppPaths) -> PartsDbRepository: ...   # module singleton, keyed by paths
def reset_for_testing() -> None: ...
```

- **One singleton, two accessors during transition**: `app/services/parts_db_service.py`
  becomes a thin shim whose `get_parts_db_service(paths)` returns the *same* instance as
  `parts_db.get_repository(paths)` (cache coherence: route mutations must invalidate the
  object the planner reads).
- **At extraction time the API is exactly today's `PartsDbService` surface** — all ~23 typed
  queries, `validate_placement`, `raw_doc`, `invalidate` — moved verbatim (mechanical move,
  reviewable as a move). No speculative new queries; new surface is added on demand by the
  consumers that migrate off `raw_doc()` (REPOSITORY_PRINCIPLES: an abstraction needs two
  real call sites or a documented future feature).

### 3.2 Reads and queries

Moved as-is: taxonomy lists (`list_types/sections/zones/sub_zones/build_attributes/tags/
manufacturers/colors/services/preference_filters`), part-type queries (`list_part_types`,
`list_part_types_at`, `list_part_types_with_tag`, `list_accessories_of`, `get_part_type`),
product queries (`list_products`, `list_products_for_part_type`, `list_products_with_tag`,
`get_product`, `list_part_numbers`), placement queries (`get_placement`,
`list_placement_zones`), and `validate_placement` (the one intersection rule).

**Three-axis invariant (seam register)**: the query surface keeps the axes orthogonal —
`part_type.category` (what it is), zone-via-placement (where on the vehicle), section (how it
groups). No query may take one axis and silently filter by another; reviewers check new
queries against this rule.

### 3.3 Legacy queries — quarantined, not blessed

`legacy.py` keeps the 3-tier fallback (`parts_db + legacy_workbook_index` →
`workbook_rules.part_rules`) exactly as shipped, because `/manifest-data` and
`_resolve_product_locations` still depend on it. Two rules:

- **No new consumers.** These are workbook-shape transition shims (pipeline inversion:
  nothing workbook-shaped belongs in the interface). New code uses the typed queries.
- **Retirement is scheduled**: they die with the Phase 4 consumer migration
  (`workbook_rules.json` domain-data strip), via the §2.2 parity protocol.

### 3.4 Writes, round-trip fidelity, and curation state

**The invariants that must survive any migration untouched** (§7 seam register):
three-axis model · `location_mode` + `location_options` on part_types · accessory roles
(`accessory_category` / `accessory_of_products` / `accessory_required`, plus part_type
`accessory_of` and product `accessories[]`) · pending-QB (`qb_pending` + reconciliation) ·
`light`/`unbilled` tags · warning-light single-home (`warning_light` + zone-as-name) ·
**curation state** (`product.reviewed`, readiness-relevant fields) — ~673 unhomed products
are mid-curation and must not be stranded or reset.

Mechanism, not exhortation:

1. **Writes never pass through dataclass hydration.** The write path operates on the raw
   dict doc (whole-doc save or field-whitelisted patches, exactly as `_mutate_parts_db` does
   today). Because hydration is read-only, fields the dataclasses don't yet carry (F-2)
   round-trip untouched by construction. This stays true even after C1 closes the hydration
   gap — it is the permanent rule that makes schema growth safe.
2. **The validator moves verbatim** (`schema.py`) — it is required-key/type checking,
   deliberately permissive to unknown keys, which is what lets curation fields and future
   kit fields coexist.
3. **The SKU-grid save path is untouchable while curation is in flight**: Stage A/B do not
   touch `_mutate_parts_db`, `_handle_edit`, or `POST /api/parts-db/edit/*` at all. The
   command layer moves only in Stage C, under the 1b/1c pins (§4).

**Writer port** (`writer.py`, lands Stage C):

```python
class PartsDbWriter(Protocol):
    def save(self, doc: dict, paths: AppPaths) -> dict: ...   # returns {ok, path?, error?}

class LocalPartsDbWriter:      # library mode: migrate → validate → backup → atomic write
class AppConfigWriter:         # lives in app/ wiring: delegates to save_config_file
                               # (proposal + SharePoint direct-mirror + template hooks)
```

- `repo.save_doc(doc)` / `repo.mutate(fn)` **raise `WriterNotConfigured` when no writer is
  wired** — deliberately loud, because the #1 parts_db footgun is a silent local write being
  reverted by the 60s SharePoint sync. There is no silent local default inside the app.
- The GUI app wires `AppConfigWriter` at the shim/boot level, preserving the write invariant
  (all writes reach `save_config_file` → validation + proposal + mirror).
- `LocalPartsDbWriter` exists for the sibling parts-manager app and offline tools — callers
  that today already run `--write` without `--push-to-cloud` and own that trade-off. It
  reproduces `config.store.save_config` semantics (migrate, validate, history backup, atomic
  rename via `storage.local`).

### 3.5 Kit SKUs — where composability attaches (room reserved, nothing implemented)

Per PARTS_DB_AND_PICKER §7, a kit is a **SKU-level** concept: `part_numbers[]` entries gain
`is_kit: bool` + `kit_skus: [part_number…]`. The reserved seams, in order of layer:

- **Data/validation**: `parts_db/schema.py` is where the kit fields' validation lands
  (including the referential check: every `kit_skus` member resolves to an existing SKU, and
  cycle rejection). Co-located with the rest of the schema knowledge — not in routes.
- **Domain**: `PartNumber` gains the two fields (additive dataclass change + hydrator).
- **Repository**: kit expansion is a repository query (reserved name:
  `expand_kit(part_number) -> list[PartNumber]`), because it is a catalog-integrity concern,
  not a route or estimate concern. Nothing else in the interface changes shape — which is the
  point of doing Step 4 before Step 5.
- **Estimate behavior** (one line vs. expanded components) is a Step 5 owner decision (§5);
  it consumes the expansion query either way.

### 3.6 Cache invalidation as interface obligation

`invalidate()` stays, and gains a third caller class: the **sync loop**. Design obligation:
when `_run_sync_cycle` detects `settings_changed` (a flat-`/Settings/` file updated — which
includes `parts_db.json`), it must call `get_repository(paths).invalidate()` alongside the
existing `data_version` bump (fixes F-1). Implementation note: invalidating on any settings
change is acceptable (cheap lazy reload); a per-file check is optional polish.

### 3.7 What the interface is NOT

- Not a home for picker/placement resolution (`_resolve_category_locations`,
  `_resolve_product_locations`, `_resolve_accessories`, the zone/category mapping tables) —
  that is planning/service logic that *consumes* the repository (C3 moves it to
  `app/services/`, per the Step 3 boy-scout rule; its long-term home is `planning/` once the
  `part_catalog.json` dependency dissolves in Phase 4).
- Not a workbook adapter: nothing workbook-shaped enters or leaves except the quarantined
  `legacy.py` shims with their scheduled death.
- Not the QB estimate/billing brain: `qb_estimate_service` keeps its semantics and merely
  reads through the repository.

---

## 4. Migration path — mechanical moves, pins, and baseline deletions

**Prerequisites (hard, per §8.1)**: Step 3 (picker cluster) shipped · 1a golden corpus
**recorded** (must include project-path cases with picker-created parts, so the planner's
part_type-fallback path is inside the pin) · 1b contract snapshots recorded for every
`/api/parts-db/*` route (the `tests/contract/` suite does not exist yet — recording it is
part of the Step 1 implementation session, and Stage A may not start without it) · 1c smoke
flows including "SKU grid edit + save round-trip" and the picker flow · 1d CI pytest job.

Each step is one commit (or one tight commit pair), full pytest + golden masters green
before merge, refactor commits never mixed with behavior changes.

### Stage A — repository extraction (this is §8.1 Step 4 proper; gates Step 5)

| # | Move | Pins that cover it | Lint effect |
|---|---|---|---|
| A1 | Create `parts_db/` package; **move** `PartsDbService` → `repository.PartsDbRepository` (methods verbatim), legacy readers → `legacy.py`, `_validate_parts_db` + empty-doc → `schema.py` (config/schemas + config/migrations re-import downward); `app/services/parts_db_service.py` becomes a delegating shim (`PartsDbService = PartsDbRepository`, `get_parts_db_service` → `get_repository`, `reset_for_testing` forwarded) | full pytest (all existing `test_parts_db_*` still pass against the shim), 1b contract snapshots, golden masters | `layers` list rewritten per §2.2 (parts_db inserted, storage lowered); no baseline deletion yet |
| A2 | **Planner cutover**: replace the lazy import at `planning/planner.py:152–160` with `from ..parts_db import get_repository` (plain import — no cycle remains) | golden masters **bit-identical** (workbook + project-path cases), full pytest | **delete baseline entry** `planning.planner -> app.services.parts_db_service` — the Step 4 done-condition |
| A3 | **Test migration** (§2.2 discipline): `test_parts_db_service/dual_read/compatibility_rules` re-target `dtm_buildsheet.parts_db`; route/edit tests keep exercising routes (their subject didn't move) | the tests are the pin — green before/after re-target | — |
| A4 | **Seam proof**: add a test asserting `import dtm_buildsheet.parts_db` succeeds with `dtm_buildsheet.app` absent from `sys.modules` (the parts-manager-app / library seam, §7) | itself | — |

*Stage A done-when* (= Step 4 done-when): planning→app baseline entry deleted; golden
masters unchanged; curation state untouched (no write-path file modified — verifiable by
`git diff --stat` showing zero changes under `app/routes/` and to `_mutate_parts_db`).

### Stage B — app consumers repoint (interstitial, after A settles)

| # | Move | Pins | Lint effect |
|---|---|---|---|
| B1 | `qb_estimate_service`, `qb_sync_service` read-accessor swap to `parts_db.get_repository` (their writes keep calling `save_config_file` — unchanged) | `test_qb_estimate_*`, `test_qb_sync_service`, contract snapshots for QB routes | — |
| B2 | `routes/parts_db.py`: `svc = get_repository(paths)`; `tools/seed_part_type_locations.py` import swap | 1b snapshots (byte-identical responses), `test_parts_db_routes/edit_routes`, 1c SKU-grid + picker smoke flows | — |
| B3 | Delete the `app/services/parts_db_service.py` shim once `grep` shows no importer (one release cycle after B2, per the §2.2 shim window) | full pytest | — |

### Stage C — command layer + convention hardening (positions Step 5; touches the guarded save path — see §5 Q3)

| # | Move | Pins | Notes |
|---|---|---|---|
| C1 | Close the hydration gap (F-2): add `location_mode`/`location_options` to `PartType`, `reviewed`/accessory-role fields (+ product-level `accessories`, `qb_*`) to `Product`; hydrators + `schema.py` accordingly; route handlers drop the corresponding `raw_doc()` dips | contract snapshots **intentionally re-recorded** (additive response fields — a §3.2 opt-in diff with its own commit + decision-log line), full pytest | UI unaffected (JS reads named fields) |
| C2 | Writer port lands: `writer.py` + `AppConfigWriter`; `_mutate_parts_db` moves into `repository.mutate()` (deep-copy → mutate → metadata stamp → writer → invalidate); `_handle_edit` actions and field whitelists move to the repository as commands; routes become thin dispatch | `test_parts_db_edit_routes`, 1b edit-route snapshots, 1c SKU-grid save round-trip smoke flow — all three green before and after | **This is the first commit allowed to touch the SKU-grid save path**; schedule per §5 Q3 |
| C3 | Placement/judgment logic out of routes: mapping tables + `_pt_in_category`/`_warning_home`/`_resolve_*` → `app/services/picker_placement_service.py` (mechanical move; consolidate the three duplicate zone-keyword tables, F-5) | 1b snapshots for `category-locations`/`placements`/`accessories`/`category-skus`/`zone-products`, picker smoke flow | Long-term home is `planning/` post-Phase 4; don't force it early |
| C4 | Sync-loop invalidation (F-1): `_run_sync_cycle` calls `get_repository(paths).invalidate()` on `settings_changed` | behavior **improvement** — own commit + ROADMAP decision-log entry per §3.2 | multi-device freshness fix |

**Baseline entries NOT taken by this seam** (explicit non-goals, so the extraction session
doesn't scope-creep): `planning.planner -> config.loader` (ConfigBundle/model_lookup_keys —
the baseline comment already routes this to Phase E via the Step 7 ledger if Step 4 doesn't
take it; this design **defers it**: kit SKUs don't depend on it, and moving ConfigBundle is a
planner-signature change, not a mechanical move) · `planning.planner -> config_loader` shim
(Step 6) · `inputs.* -> app.services.shared_work_service` (Phase E).

---

## 5. Open questions — owner decision list (do not resolve by fiat)

1. **Q1 · Kit estimate behavior** (already flagged in PARTS_DB_AND_PICKER §7, restated
   because the reserved interface depends on it): does a kit bill as **one line** (kit SKU,
   kit price) or **expand to component lines** on the QB estimate? Both consume
   `expand_kit()`; the DescriptionOnly/pending-QB interaction differs. Needed before Step 5
   *implementation*, not before Step 4.
2. **Q2 · Sibling parts-manager app write mode**: is the future parts-manager app
   **read-only at first** (browse/report against the shared DB) or **read-write** (its own
   cloud wiring feeding the same SharePoint mirror)? Read-write means the writer port needs
   a Graph-capable adapter outside this GUI app — worth knowing before Stage C freezes the
   port shape, though the Protocol as specified accommodates both.
3. **Q3 · Stage C2 timing vs curation**: C2 is the first commit that touches the SKU-grid
   save path. The 1b/1c pins are the designed safety net, but the standing rule says nothing
   touches that path "outside the pins while curation is in flight." Owner call: run C2
   under the pins whenever it's ready, or wait for a natural curation pause / full backup
   checkpoint first?

*(Not owner questions, decided here: package name `parts_db` — matches every doc and the
seam register; no silent local-write default inside the app — the SP-revert footgun rules it
out; ConfigBundle move deferred to Phase E — see §4.)*

### Answers (owner, 2026-07-07 — recorded in ROADMAP.md decision log)

- **Q1 — mirror QuickBooks.** A kit bills exactly as QB bills it: one QB item → one estimate
  line; QB bundle/group of components → component lines. The app invents no kit billing
  semantics of its own. This also right-sizes Step 5's scope: kit support exists *only to
  represent kits that exist in QB inventory* — model QB's structure, don't design a general
  kit system. `expand_kit()` stays; its estimate behavior is driven by the QB item type.
- **Q2 — deferred; the app is not being built now.** The Step 4 repository (importable
  without the GUI) is the only seam the sibling app needs, and it lands regardless — so
  deferring the app costs nothing later. When it happens, it starts **read-only**. The Stage
  C writer port therefore does not need a Graph-capable adapter for a second app; don't
  build one speculatively.
- **Q3 — wait for curation to complete.** C2 does not touch the SKU-grid save path until all
  ~673 unhomed products are dispositioned and the owner declares the curation queue done (a
  full backup checkpoint precedes C2 regardless). Stages C3/C4 items that don't touch the
  save path may proceed independently of this gate.

---

## 6. Handoff list for the extraction session

Ordering reminder: **runs after the picker cluster (Step 3) ships**, per §8.1. Design
allocation says the extraction itself is Sonnet-grade mechanical work against this spec.

1. **Verify prerequisites** (do not start otherwise): Step 3 merged; `tests/golden/` corpus
   recorded and green twice consecutively; `tests/contract/` snapshots exist for every
   `/api/parts-db/*` route; `tools/ui_smoke/` flows for picker + SKU-grid green; CI pytest
   job live.
2. Re-read this spec §2–§4, PARTS_DB_AND_PICKER §1/§2.5/§8, GOTCHAS (config + cloud
   sections), and the import-linter block in `pyproject.toml`.
3. Execute Stage A as four commits (A1–A4), running full pytest + golden masters between
   each. Stage A alone satisfies the Step 4 done-condition; **stop and ship** there if time
   is short — B and C are separately schedulable.
4. Update after Stage A: `pyproject.toml` layers + baseline (A1/A2), `docs/ARCHITECTURE.md`
   (new package in the layer diagram), `docs/PARTS_DB_AND_PICKER.md` §1 (service pointer →
   `parts_db/repository.py`), GOTCHAS #21 (F-4 drift), AUDIT_REFACTOR_ROADMAP §8.1 Step 4
   (mark shipped + absorb findings), ROADMAP decision log if any behavior allowance was used.
5. Stage B/C: schedule as interstitial work; C2 blocked on §5 Q3; C1's contract re-record is
   its own flagged commit; C4 carries a decision-log entry.
6. Leave `raw_doc()` in place until the last Stage C consumer is migrated — it is the
   transition valve, and deleting it early forces big-bang rewrites this plan exists to avoid.

---

*Authored 2026-07-07 (§8.1 Step 4 design session). Zero production code changed; full pytest
green on an untouched tree. Inventory verified against commit `2777086`.*
