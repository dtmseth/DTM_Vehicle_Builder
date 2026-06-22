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

21. **`parts_db.json` is populated but not wired into production reads** (Phase 3). The build sheet
    generator, planner, manifest editor, rule engine, and excel reader still drive off
    `workbook_rules.json` / `parts_library.json` / `vehicle_layouts.json` / `part_catalog.json`.
22. **`agencies.json` / `sales_reps.json` flat files** are legacy migration sources only.
    Current storage is per-record (`workspace/agencies/{id}.json`, `workspace/sales_reps/{id}.json`)
    with SharePoint direct-mirror.
