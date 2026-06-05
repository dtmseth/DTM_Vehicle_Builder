from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


# ── Phase 1 path-scope classification ─────────────────────────────────────────
#
# Each path is tagged with how Phase 2 (SharePoint go-live) will treat it.
# Tags:
#   [bundled]         — ships inside the app package; never written at runtime.
#   [local-only]      — per-machine state; stays on the user's disk (e.g.
#                       app_settings.project_output_root, uploaded workbooks).
#   [shared-settings] — reviewed via PR through the GitHub settings repo;
#                       app reads from a local SharePoint mirror of /Settings/.
#   [shared-work]     — last-writer-wins per record on SharePoint /Projects/,
#                       /Drafts/, /Exports/, /Assets/.
#
# Phase 2 will add SETTINGS_DIR and SHARED_WORK_DIR resolvers; nothing here
# changes structurally until then. The tags exist now so any new code in
# Phase 1 lands with the right intent and a Phase 2 grep can find every site.

# ── Bundled (read-only, ships with app) ───────────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent             # [bundled]
DEV_PROJECT_ROOT = PACKAGE_DIR.parents[1]                 # [bundled] dev only
RESOURCES_DIR = PACKAGE_DIR / "resources"                 # [bundled]
DEFAULT_CONFIG_DIR = RESOURCES_DIR / "config"             # [bundled] seed → workspace/config/
DEFAULT_DATA_DIR = RESOURCES_DIR / "default_data"         # [bundled] seed → workspace root
ASSETS_DIR = RESOURCES_DIR / "assets"                     # [bundled] seed → workspace/assets/
TEMPLATES_DIR = RESOURCES_DIR / "templates"               # [bundled]
SAMPLES_DIR = DEV_PROJECT_ROOT / "samples"                # [bundled] dev only


def _is_dev_checkout() -> bool:
    return (DEV_PROJECT_ROOT / "pyproject.toml").exists() and (DEV_PROJECT_ROOT / "src" / "dtm_buildsheet").exists()


def _user_workspace_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DTM Vehicle Builder"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "DTM Vehicle Builder"
        return Path.home() / "AppData" / "Roaming" / "DTM Vehicle Builder"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "dtm-vehicle-builder"


_DEV = _is_dev_checkout()

# ── Workspace root ────────────────────────────────────────────────────────────
PROJECT_ROOT = DEV_PROJECT_ROOT if _DEV else _user_workspace_root()
WORKSPACE_DIR = (DEV_PROJECT_ROOT / "workspace") if _DEV else PROJECT_ROOT
# WORKSPACE_DIR is a mixed-scope umbrella. Phase 2 will split into a
# settings-cache root (mirrors /Settings/) and a work root (mirrors /Projects/,
# /Drafts/, etc.). Until then everything lives under this one directory.

# ── Settings (shared via PR review in Phase 2) ────────────────────────────────
# In dev mode the GUI writes directly to the source tree so every config /
# asset / preset change is immediately visible to git and ships to users on
# the next release. In the bundled app these point into the user's
# Application Support folder.
WORKSPACE_CONFIG_DIR = DEFAULT_CONFIG_DIR if _DEV else WORKSPACE_DIR / "config"   # [shared-settings] (one file is [local-only]; see config/schemas.py)
WORKSPACE_ASSETS_DIR = ASSETS_DIR         if _DEV else WORKSPACE_DIR / "assets"   # [shared-settings]
BUNDLED_PRESETS_DIR  = RESOURCES_DIR / "presets"                                  # [bundled]
WORKSPACE_PRESETS_DIR = BUNDLED_PRESETS_DIR if _DEV else WORKSPACE_DIR / "presets"  # [shared-settings]

# ── Work data (last-writer-wins per record on SharePoint in Phase 2) ──────────
WORKSPACE_INPUT_DIR    = WORKSPACE_DIR / "input"     # [local-only] uploaded workbooks, transient
WORKSPACE_OUTPUT_DIR   = WORKSPACE_DIR / "output"    # [shared-work] generated .pptx (Exports)
WORKSPACE_DRAFTS_DIR   = WORKSPACE_DIR / "drafts"    # [shared-work] per-record JSON
WORKSPACE_PROJECTS_DIR = WORKSPACE_DIR / "projects"  # [shared-work] {id}/project.json

# Top-level workspace files / dirs not exposed as AppPaths constants:
#   workspace/agencies/{id}.json    [shared-work] (per-record; see agency_service)
#   workspace/sales_reps/{id}.json  [shared-work] (per-record; see sales_rep_service)
#   workspace/dtm_buildsheet.log    [local-only]  (server log)


@dataclass(frozen=True)
class AppPaths:
    project_root: Path = PROJECT_ROOT
    package_dir: Path = PACKAGE_DIR
    resources_dir: Path = RESOURCES_DIR
    assets_dir: Path = ASSETS_DIR
    templates_dir: Path = TEMPLATES_DIR
    workspace_dir: Path = WORKSPACE_DIR
    workspace_config_dir: Path = WORKSPACE_CONFIG_DIR
    workspace_assets_dir: Path = WORKSPACE_ASSETS_DIR
    workspace_input_dir: Path = WORKSPACE_INPUT_DIR
    workspace_output_dir: Path = WORKSPACE_OUTPUT_DIR
    workspace_drafts_dir: Path = WORKSPACE_DRAFTS_DIR
    workspace_presets_dir: Path = WORKSPACE_PRESETS_DIR
    workspace_projects_dir: Path = WORKSPACE_PROJECTS_DIR
    bundled_presets_dir: Path = BUNDLED_PRESETS_DIR
    samples_dir: Path = SAMPLES_DIR


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _copy_missing_tree(source_root: Path, dest_root: Path) -> int:
    """Copy files from source_root to dest_root, updating any that have changed.

    Returns the number of files written.
    """
    written = 0
    for source in sorted(source_root.rglob("*")):
        if source.is_dir() or source.name.startswith("."):
            continue
        rel = source.relative_to(source_root)
        dest = dest_root / rel
        if dest.exists() and _md5(source) == _md5(dest):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, dest)
            _log.debug("Seeded asset: %s", rel)
            written += 1
        except Exception:
            _log.exception("Failed to copy bundled asset %s", rel)
    return written


def _log_westin_elitexd_probe(paths: AppPaths) -> None:
    rel_asset = Path("equipment") / "westin_wing_wrap_elitexd_side.png"
    legacy_rel_asset = Path("lights") / "westin_wing_wrap_elitexd_side.png"
    bundled_asset = ASSETS_DIR / rel_asset
    workspace_asset = paths.workspace_assets_dir / rel_asset
    legacy_workspace_asset = paths.workspace_assets_dir / legacy_rel_asset
    parts_library = paths.workspace_config_dir / "parts_library.json"

    try:
        config_has_entry = (
            parts_library.exists()
            and "westin_wing_wrap_elitexd_side.png" in parts_library.read_text(encoding="utf-8")
        )
    except Exception:
        _log.exception("Failed to inspect parts_library.json for Wing Wrap EliteXD entry")
        config_has_entry = False

    _log.info(
        "Wing Wrap EliteXD probe: bundled_asset=%s bundled_exists=%s "
        "workspace_asset=%s workspace_exists=%s legacy_workspace_asset=%s "
        "legacy_workspace_exists=%s parts_library=%s parts_library_has_entry=%s",
        bundled_asset,
        bundled_asset.exists(),
        workspace_asset,
        workspace_asset.exists(),
        legacy_workspace_asset,
        legacy_workspace_asset.exists(),
        parts_library,
        config_has_entry,
    )


def ensure_workspace() -> AppPaths:
    paths = AppPaths()
    for d in (paths.workspace_dir, paths.workspace_config_dir, paths.workspace_assets_dir,
              paths.workspace_input_dir, paths.workspace_output_dir, paths.workspace_drafts_dir,
              paths.workspace_presets_dir, paths.workspace_projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    # In dev mode workspace_config_dir IS DEFAULT_CONFIG_DIR — no copying needed.
    if paths.workspace_config_dir != DEFAULT_CONFIG_DIR:
        if not DEFAULT_CONFIG_DIR.exists():
            _log.error("Bundled config directory not found: %s", DEFAULT_CONFIG_DIR)
        else:
            written = 0
            for source in sorted(DEFAULT_CONFIG_DIR.glob("*.json")):
                dest = paths.workspace_config_dir / source.name
                if not dest.exists() or _md5(source) != _md5(dest):
                    try:
                        shutil.copyfile(source, dest)
                        written += 1
                        _log.info("Seeded config: %s", source.name)
                    except Exception:
                        _log.exception("Failed to copy config %s", source.name)
            _log.info(
                "Config seed summary: wrote=%d source=%s workspace=%s",
                written,
                DEFAULT_CONFIG_DIR,
                paths.workspace_config_dir,
            )

    # In dev mode workspace_assets_dir IS ASSETS_DIR — no copying needed.
    if paths.workspace_assets_dir != ASSETS_DIR:
        if not ASSETS_DIR.exists():
            _log.error("Bundled assets directory not found: %s", ASSETS_DIR)
        else:
            n = _copy_missing_tree(ASSETS_DIR, paths.workspace_assets_dir)
            _log.info(
                "Asset seed summary: wrote=%d source=%s workspace=%s",
                n,
                ASSETS_DIR,
                paths.workspace_assets_dir,
            )

    _log_westin_elitexd_probe(paths)

    # Seed workspace-root data files from packaged defaults if and only if
    # they don't exist yet. In dev mode workspace_dir is the repo workspace/
    # folder which is git-ignored; in bundled mode it's the user's Application
    # Support folder. Either way, once the file exists we leave it alone so
    # user edits are never overwritten.
    #
    # cloud_config.json is treated the same: bundling the DTM Fleet tenant
    # IDs lets a teammate's first launch enter cloud mode without manually
    # dropping a config file. The values are non-secret (tenant + app
    # registration + site IDs are all publicly discoverable during the OAuth
    # flow); shipping them removes a setup step. External-sale variants will
    # ship a different bundled cloud_config.json (or none, to default to
    # local mode).
    for data_filename in ("agencies.json", "sales_reps.json", "cloud_config.json"):
        dest = paths.workspace_dir / data_filename
        if not dest.exists():
            src = DEFAULT_DATA_DIR / data_filename
            if src.exists():
                try:
                    shutil.copyfile(src, dest)
                    _log.info("Seeded default data: %s", data_filename)
                except Exception:
                    _log.exception("Failed to seed default data %s", data_filename)

    # Forward-merge new top-level keys from the bundled cloud_config.json into
    # the workspace copy. Existing values are never touched — only absent keys
    # are filled in. This keeps users who installed pre-v2.2.1 from being
    # stuck without the exports_* keys (auto-upload silently disabled) when
    # we add new optional config in later releases.
    _merge_missing_cloud_config_keys(paths)

    return paths


def _merge_missing_cloud_config_keys(paths: AppPaths) -> None:
    """Fill in absent top-level keys in workspace cloud_config.json from the
    bundled default. Existing values are preserved. Silent no-op when either
    file is missing or unparseable — bootstrap continues normally."""
    import json

    dest = paths.workspace_dir / "cloud_config.json"
    src = DEFAULT_DATA_DIR / "cloud_config.json"
    if not dest.exists() or not src.exists():
        return

    try:
        bundled = json.loads(src.read_text(encoding="utf-8"))
        workspace = json.loads(dest.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("Could not parse cloud_config for merge; leaving as-is")
        return
    if not isinstance(bundled, dict) or not isinstance(workspace, dict):
        return

    added = [k for k in bundled if k not in workspace]
    if not added:
        return
    for k in added:
        workspace[k] = bundled[k]
    try:
        dest.write_text(json.dumps(workspace, indent=2) + "\n", encoding="utf-8")
        _log.info("Merged %d missing cloud_config key(s): %s", len(added), ", ".join(added))
    except OSError:
        _log.exception("Could not write merged cloud_config.json to %s", dest)


# ── output path portability ────────────────────────────────────────────────────
# Persisted records (ProjectRecord, BuildUnit, IndividualUnit) store output_path
# as workspace-relative when the file lives under the workspace, so a record
# authored on one machine resolves correctly on another. Paths outside the
# workspace (e.g. a user-configured project_output_root in ~/Documents) are kept
# absolute — Phase 1 tags app_settings.project_output_root as local-only.

def resolve_output_path(stored: str, workspace_dir: Path | None = None) -> str:
    """Resolve a stored output_path to an absolute filesystem path.

    Empty or already-absolute values are returned verbatim; workspace-relative
    values are joined against *workspace_dir* (defaults to the active workspace).
    """
    if not stored:
        return ""
    p = Path(stored)
    if p.is_absolute():
        return stored
    root = workspace_dir or WORKSPACE_DIR
    return str(root / p)


def relativize_output_path(absolute: str, workspace_dir: Path | None = None) -> str:
    """Convert an absolute output_path to workspace-relative POSIX if it lives under the workspace.

    Empty values pass through. Already-relative values pass through. Absolute paths
    outside the workspace also pass through unchanged (those are local-only).
    """
    if not absolute:
        return ""
    p = Path(absolute)
    if not p.is_absolute():
        return absolute
    root = (workspace_dir or WORKSPACE_DIR).resolve()
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return absolute
