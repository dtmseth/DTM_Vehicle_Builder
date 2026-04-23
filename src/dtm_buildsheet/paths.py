from __future__ import annotations

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


PROJECT_ROOT = DEV_PROJECT_ROOT if _is_dev_checkout() else _user_workspace_root()
WORKSPACE_DIR = (DEV_PROJECT_ROOT / "workspace") if _is_dev_checkout() else PROJECT_ROOT
WORKSPACE_CONFIG_DIR = WORKSPACE_DIR / "config"
WORKSPACE_ASSETS_DIR = WORKSPACE_DIR / "assets"
WORKSPACE_INPUT_DIR = WORKSPACE_DIR / "input"
WORKSPACE_OUTPUT_DIR = WORKSPACE_DIR / "output"


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
    samples_dir: Path = SAMPLES_DIR


def ensure_workspace() -> AppPaths:
    paths = AppPaths()
    for d in (paths.workspace_dir, paths.workspace_config_dir, paths.workspace_assets_dir,
              paths.workspace_input_dir, paths.workspace_output_dir):
        d.mkdir(parents=True, exist_ok=True)

    if not DEFAULT_CONFIG_DIR.exists():
        _log.error("Bundled config directory not found: %s", DEFAULT_CONFIG_DIR)
    else:
        for source in sorted(DEFAULT_CONFIG_DIR.glob("*.json")):
            dest = paths.workspace_config_dir / source.name
            if not dest.exists():
                try:
                    shutil.copyfile(source, dest)
                except Exception:
                    _log.exception("Failed to copy config %s", source.name)

    if not any(paths.workspace_assets_dir.iterdir()):
        if not ASSETS_DIR.exists():
            _log.error("Bundled assets directory not found: %s", ASSETS_DIR)
        else:
            for source in sorted(ASSETS_DIR.rglob("*")):
                if source.is_dir() or source.name.startswith("."):
                    continue
                rel = source.relative_to(ASSETS_DIR)
                dest = paths.workspace_assets_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(source, dest)
                except Exception:
                    _log.exception("Failed to copy asset %s", rel)

    return paths
