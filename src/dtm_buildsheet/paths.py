from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


PACKAGE_DIR = Path(__file__).resolve().parent
DEV_PROJECT_ROOT = PACKAGE_DIR.parents[1]
RESOURCES_DIR = PACKAGE_DIR / "resources"
DEFAULT_CONFIG_DIR = RESOURCES_DIR / "config"
ASSETS_DIR = RESOURCES_DIR / "assets"
TEMPLATES_DIR = RESOURCES_DIR / "templates"
SAMPLES_DIR = DEV_PROJECT_ROOT / "samples"


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

PROJECT_ROOT = DEV_PROJECT_ROOT if _DEV else _user_workspace_root()
WORKSPACE_DIR = (DEV_PROJECT_ROOT / "workspace") if _DEV else PROJECT_ROOT

# In dev mode the GUI writes directly to the source tree so every config
# and asset change is immediately visible to git — no manual syncing needed.
# In the bundled app these point into the user's Application Support folder.
WORKSPACE_CONFIG_DIR = DEFAULT_CONFIG_DIR if _DEV else WORKSPACE_DIR / "config"
WORKSPACE_ASSETS_DIR = ASSETS_DIR         if _DEV else WORKSPACE_DIR / "assets"

WORKSPACE_INPUT_DIR  = WORKSPACE_DIR / "input"
WORKSPACE_OUTPUT_DIR = WORKSPACE_DIR / "output"
WORKSPACE_DRAFTS_DIR = WORKSPACE_DIR / "drafts"


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
              paths.workspace_input_dir, paths.workspace_output_dir, paths.workspace_drafts_dir):
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

    return paths
