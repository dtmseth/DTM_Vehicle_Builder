gotchas : {}}

# Gotchas

Every footgun discovered the hard way. Before editing anything, scan this list for the module
you're touching. New gotchas get appended to the bottom with a date.

---

## Package & naming

1. **Python package name is `dtm_buildsheet`** (underscore). PyPI name is `dtm-buildsheet` (hyphen).
   App name is "DTM Vehicle Builder". Don't rename `src/dtm_buildsheet/` without updating all imports.
2. **Compatibility shims** (`gui_server.py`, `config_loader.py`, `input_reader.py`, `models.py`,
   `planner.py`) are thin re-exports. New code imports from `app`, `domain`, `planning`, `inputs`
   directly.

---

## macOS / pywebview

3. **pywebview owns the main thread** on macOS — the HTTP server must run in a daemon thread. Don't
   move `webview.start()` off the main thread.
4. **ICNS must be real ICNS** — the source icon was a PNG renamed to `.icns`. It was converted
   properly via `iconutil`. Don't replace it with a raw PNG or PyInstaller silently falls back to
   the Python rocket icon.
5. **Port 7655 conflict** = old instance still running. `lsof -ti :7655 | xargs kill` clears it.

---

## Workspace & paths

6. **Workspace vs bundled**: `paths.py` detects dev mode via presence of `pyproject.toml`.
   - Dev: workspace = `{repo}/workspace/`, config/assets written to `src/dtm_buildsheet/resources/`
   - Bundled app: workspace = `~/Library/Application Support/DTM Vehicle Builder` (Mac) or
     `%APPDATA%\DTM Vehicle Builder` (Windows)
7. **Config files in `workspace/config/`** are editable JSON. Config saves go through
   `save_config_file()` which triggers template auto-regen for template-feeding files
   (`TEMPLATE_REGEN_FILES` in `config_service.py`).

---

## Template & config

8. **`template_builder.py`** reads 3 files: `workbook_rules.json`, `parts_library.json`,
   `vehicle_layouts.json`. Adding a new template-feeding config file → add its filename to
   `TEMPLATE_REGEN_FILES` in `config_service.py`.
9. **Config is a contract** — every config file must be documented in `CONFIG_SCHEMA.md`,
   validated in `config/schemas.py`, migrated in `config/migrations.py` when fields change,
   and covered by tests.

---

## Cloud & SharePoint

10. **Cloud is source of truth** for agencies, sales reps, presets, projects, and drafts (v2.2.9+).
    Saves direct-mirror to SharePoint via `save_setting_to_cloud_in_background`;
    deletes go through `delete_setting_from_cloud`. The dtm-shared-settings repo is audit-only.
11. **Migration script** (`tools/migrate_workbook_to_parts_db.py`): always use
    `--write --push-to-cloud`. Without `--push-to-cloud`, SharePoint sync silently overwrites
    the migration with its older copy on the next 60s cycle.

---

## QuickBooks

12. **QuickBooks secrets never touch disk or cloud** — keys/tokens live ONLY in the OS keychain via
    `adapters/quickbooks/credential_store.py`. `quickbooks_config.json` holds non-secret metadata
    and is deliberately NOT in any cloud-mirror set.
13. **QuickBooks OAuth callback** (`routes/quickbooks.py`) MUST stay 302-only — never echo the
    code/token as HTML. All `/api/quickbooks/*` responses set `Cache-Control: no-store`.

---

## Testing

14. **Tests must NEVER write to the real workspace queue**. `tests/conftest.py` blocks real cloud
    I/O, and `wiring.save_via_proposal` refuses to enqueue when `PYTEST_CURRENT_TEST` is set.
    Bypassing these guards reintroduces the abc.json resurrection bug.
15. **Placement math is single-source**: `domain/geometry.py`. If you change it, update the
    preview canvas JS too.

---

## CI & packaging

16. **PyInstaller cannot cross-compile** — Mac builds must run on Mac, Windows builds must run on
    Windows (CI handles both).
17. **Auto-update** uses `update_check_service._expected_installer_suffix()` — don't hard-code
    `sys.platform.startswith("win")` in update-state code. That's how the Mac
    "platform_unsupported" bug shipped.

---

## UI

18. **`#card-preview` and `#card-manifest` are singletons** — they exist only inside
    `#proj-build-editor`. The standalone workbook-upload generator does not render them.
19. **Modal ownership** — each modal's save button is owned by exactly one IIFE. Never attach a
    second listener from another file.
20. **Inline style policy** — `display:none` in initial HTML is acceptable for JS-toggled elements.
    All other inline styles (colors, spacing, fonts, layouts) belong in `styles.css` as named classes.

---

## Data migrations

21. **`parts_db.json` is no longer just seed data, but it is not the only source of truth yet.**
    The Part Picker, parts-db routes, manifest grouping, some planner hydration, and several
    render image/size rules now consume it directly. The generator/template stack still also reads
    `workbook_rules.json` / `parts_library.json` / `vehicle_layouts.json` / `part_catalog.json`.
    Before moving a rule or deleting a legacy field, trace the specific consumer path.
22. **`agencies.json` / `sales_reps.json` flat files** are legacy migration sources only.
    Current storage is per-record (`workspace/agencies/{id}.json`, `workspace/sales_reps/{id}.json`)
    with SharePoint direct-mirror.
23. **Text location options do not create render coordinates.** A part_type with
    `location_mode:"text"` and `location_options` only gives the picker/dropdown a friendly list.
    If the selected location is expected to render, the exact location key must exist in
    `vehicle_layouts.json` or be mapped through a resolver/alias.
24. **Smoke flow count is currently 16.** Older docs and ledger entries may mention 9/9, 10/10,
    or 12/12;
    the current command is still `.venv/bin/python tools/ui_smoke/run_smoke.py`, but expected
    success is 16/16.

---

## 2026-08-10 QuickBooks production-preview follow-up

25. **Production QuickBooks is preview-only until separately approved.** Use the isolated
    `production_preview` profile and its separate cache; it must never call the normal reconcile
    path or the 30-minute poller. Production comparison writes reports/plans only, never
    `parts_db.json`.
26. **Confirm the QBO identifier column before bulk mapping.** The current sandbox stores vendor
    part numbers in QBO `Name` while `Sku` is often blank. Compare both fields against Builder
    `part_number`; only an owner-confirmed, unambiguous exact-match field can prepare a mapping
    plan. Known baseline exclusions remain excluded.
27. **Cloud-off does not disable the existing sandbox QuickBooks item poll.** `DTM_CLOUD=0` prevents
    SharePoint mirroring, but the normal connected sandbox profile can still issue read-only QBO
    Item queries and reconcile its local workspace cache. The isolated production-preview profile
    is never included in that startup/polling path.
28. **Production may contain both `SKU` and `SKU (deleted)` Items.** Historical migration matching
    must prefer the literal active/raw Name before treating the deleted-name suffix as lineage.
    Description-only normalization can make the current and retired records look identical while
    their Item IDs, active state, and prices differ.
29. **A promoted OAuth refresh token must have one active profile owner.** Copying the production
    preview token into the standard profile and leaving both profiles connected creates a refresh-
    token rotation race. Promotion removes access/refresh/realm data from the preview store without
    revoking it; revocation would also invalidate the newly promoted standard connection.
30. **QuickBooks Customer IDs are company-local and can collide across sandbox/production.** Never
    carry agency `qb_customer_id` values across companies or run the normal ID-first import before a
    reviewed migration. The 2026 production transition found 108 sandbox IDs pointing at different
    production Customers. Migration matches unique normalized names first and permanently filters
    owner-rejected duplicate production Customer IDs from future imports.
31. **Saved presets must retain the rich `DraftPart` shape.** `part_type`, concrete SKU
    `components`, `picker_config`, accessory relationships, and placement metadata drive rendering,
    picker edit round-tripping, and QuickBooks estimate resolution. Reducing a saved build to the
    legacy workbook columns makes a newly created vehicle look similar in the manifest while losing
    its renderer identity and billable SKUs.
