"""Single runtime source for the displayed and updater app version."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path


_BUILD_VERSION_FILE = Path(__file__).with_name("_build_version.txt")
_NUMERIC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def get_app_version(*, default: str = "dev") -> str:
    """Return the frozen-build override, then installed package metadata.

    Local updater acceptance builds reuse one PyInstaller output to create two
    installers.  Their small bundled version marker is intentionally mutable
    between those installers; production builds write the ordinary project
    version to the same marker.
    """
    try:
        built_version = _BUILD_VERSION_FILE.read_text(encoding="utf-8").strip()
        if _NUMERIC_VERSION.fullmatch(built_version):
            return built_version
    except OSError:
        pass

    try:
        return package_version("dtm-buildsheet")
    except PackageNotFoundError:
        return default
