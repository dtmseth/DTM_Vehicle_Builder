from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from ...storage.base import StorageProvider

logger = logging.getLogger(__name__)


# Folder on the SharePoint drive that holds installer artifacts. Populated by
# the release CI workflow. Files use the versioned-filename convention:
#   DTM_Vehicle_Builder-{version}.dmg            (macOS)
#   DTM_Vehicle_Builder_Setup-{version}.exe      (Windows)
RELEASES_REMOTE_FOLDER = "Releases"

# Filenames the update checker recognises. Anything else in /Releases/ is
# ignored — the folder may legitimately contain release notes, sidecars, or
# legacy files we don't want to mistake for installers.
_PLATFORM_FILENAME_RE: dict[str, re.Pattern[str]] = {
    "mac": re.compile(r"^DTM_Vehicle_Builder-(\d+\.\d+\.\d+(?:[-+].+)?)\.dmg$"),
    "windows": re.compile(
        r"^DTM_Vehicle_Builder_Setup-(\d+\.\d+\.\d+(?:[-+].+)?)\.exe$"
    ),
}


@dataclass(frozen=True)
class UpdateInfo:
    """Description of a newer installer available on the shared drive."""

    version: str
    remote_path: str
    filename: str
    platform: str


def get_embedded_version() -> str:
    """Return the version baked into the installed package, or "0.0.0" in dev."""
    try:
        return _pkg_version("dtm-buildsheet")
    except PackageNotFoundError:
        return "0.0.0"


def current_platform() -> str:
    """Return ``"mac"``, ``"windows"``, or ``"unknown"`` for the running OS."""
    if sys.platform.startswith("darwin"):
        return "mac"
    if sys.platform.startswith("win"):
        return "windows"
    return "unknown"


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse ``major.minor.patch`` into a comparable tuple; (0,0,0) on failure.

    Pre-release/build suffixes after `-` or `+` are dropped before comparison
    — good enough for the team's use of plain MAJOR.MINOR.PATCH from
    bump-my-version. If we ever ship `1.3.0-rc1`-style tags, this is the
    function to revisit.
    """
    head = re.split(r"[-+]", value, maxsplit=1)[0]
    parts = head.split(".")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return (0, 0, 0)


def parse_release_filename(filename: str) -> tuple[str, str] | None:
    """Decode ``DTM_Vehicle_Builder-1.2.3.dmg`` → ``("mac", "1.2.3")``.

    Returns None for any filename that doesn't match a known platform pattern.
    """
    for platform, pattern in _PLATFORM_FILENAME_RE.items():
        m = pattern.match(filename)
        if m:
            return (platform, m.group(1))
    return None


def check_for_update(
    storage: StorageProvider,
    *,
    current_version: str | None = None,
    platform: str | None = None,
    dismissed_versions: list[str] | None = None,
    remote_folder: str = RELEASES_REMOTE_FOLDER,
) -> UpdateInfo | None:
    """Return an ``UpdateInfo`` if a newer installer is available, else None.

    The current version and platform default to the running app's environment
    so production code only needs to pass the storage provider plus the
    user's dismissal list. Tests pin the values to make assertions stable.
    """
    current_version = current_version or get_embedded_version()
    platform = platform or current_platform()
    dismissed = set(dismissed_versions or [])

    if platform == "unknown":
        logger.info("update-check: unknown platform %s — skipping", sys.platform)
        return None

    try:
        entries = storage.list_files(remote_folder)
    except FileNotFoundError:
        logger.info("update-check: %s folder missing on remote", remote_folder)
        return None
    except Exception:  # noqa: BLE001 — cloud adapter surfaces many error shapes
        logger.exception("update-check: failed to list %s", remote_folder)
        return None

    current_tuple = parse_semver(current_version)
    best: UpdateInfo | None = None
    best_tuple = current_tuple

    for remote_path in entries:
        filename = remote_path.rsplit("/", 1)[-1]
        parsed = parse_release_filename(filename)
        if parsed is None:
            continue
        file_platform, file_version = parsed
        if file_platform != platform:
            continue
        if file_version in dismissed:
            continue
        file_tuple = parse_semver(file_version)
        if file_tuple <= best_tuple:
            continue
        best = UpdateInfo(
            version=file_version,
            remote_path=remote_path,
            filename=filename,
            platform=platform,
        )
        best_tuple = file_tuple

    return best


def download_update(
    storage: StorageProvider,
    info: UpdateInfo,
    *,
    destination_dir: Path | None = None,
) -> Path:
    """Pull the installer bytes from the shared drive into a local file.

    Default destination is the user's Downloads folder so the installer
    lands somewhere the OS already considers safe to launch. Returns the
    local path the caller can hand to the reveal helper.
    """
    destination_dir = destination_dir or (Path.home() / "Downloads")
    destination_dir.mkdir(parents=True, exist_ok=True)
    data = storage.read_bytes(info.remote_path)
    local_path = destination_dir / info.filename
    local_path.write_bytes(data)
    return local_path


def reveal_in_file_manager(path: Path) -> None:
    """Open the user's file manager focused on *path*.

    macOS: Finder, with the file selected (``open -R``).
    Windows: Explorer, with the file selected.
    Linux / other: open the parent directory; selection isn't standardized.
    Errors are logged and swallowed — failing to reveal is non-fatal.
    """
    try:
        if sys.platform.startswith("darwin"):
            subprocess.run(["open", "-R", str(path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(
                ["explorer.exe", f"/select,{path}"],
                check=False,
            )
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except Exception:
        logger.exception("reveal_in_file_manager failed for %s", path)
