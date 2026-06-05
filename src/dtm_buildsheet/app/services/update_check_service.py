from __future__ import annotations

import logging
import os
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


# ── Silent auto-update: queue / consume / install ──────────────────────────


def _queued_installer_dir(paths) -> Path:
    return paths.workspace_dir / ".queued_installer"


def queue_installer_for_next_launch(local_path: Path, paths) -> Path:
    """Move a freshly-downloaded installer into the queue dir so the next
    app launch (or an explicit Restart-now click) can run it silently.

    A single installer is queued at a time — any older queued file with a
    different name is removed first. Returns the queued path.
    """
    queue_dir = _queued_installer_dir(paths)
    queue_dir.mkdir(parents=True, exist_ok=True)
    # Drop older queued installers; only the newest should be present.
    for stale in queue_dir.iterdir():
        if stale.name == local_path.name:
            continue
        try:
            stale.unlink()
        except OSError:
            logger.exception("could not remove older queued installer %s", stale)
    target = queue_dir / local_path.name
    try:
        if target.exists():
            target.unlink()
        local_path.replace(target)
    except OSError:
        # Cross-device fallback (Downloads vs workspace on different drives)
        target.write_bytes(local_path.read_bytes())
        try:
            local_path.unlink()
        except OSError:
            pass
    logger.info("Queued installer for next launch: %s", target)
    return target


def get_queued_installer(paths) -> Path | None:
    """Return the queued installer path if one is present, else None.

    On non-Windows platforms returns None — silent install isn't supported
    elsewhere and the Mac DMG flow stays manual."""
    if not sys.platform.startswith("win"):
        return None
    queue_dir = _queued_installer_dir(paths)
    if not queue_dir.exists():
        return None
    for entry in queue_dir.iterdir():
        if entry.suffix.lower() == ".exe" and entry.is_file():
            return entry
    return None


def get_pending_update_info(paths) -> dict | None:
    """Status-endpoint helper: describe the queued installer (if any).

    Returns ``{"version": "...", "filename": "..."}`` so the UI can show a
    "Update v2.2.4 ready — Restart now" banner. None when no installer
    is queued or the platform is unsupported.
    """
    queued = get_queued_installer(paths)
    if queued is None:
        return None
    parsed = parse_release_filename(queued.name)
    version = parsed[1] if parsed else ""
    return {"version": version, "filename": queued.name}


def _spawn_installer_silent(installer: Path) -> bool:
    """Launch the Inno Setup installer in silent mode.

    Returns True if subprocess.Popen returned without raising. The
    installer itself handles uninstaller-wait + close-current-app via the
    InitializeSetup hook in installer.iss.
    """
    try:
        subprocess.Popen([
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
        ])
        return True
    except Exception:
        logger.exception("Could not launch queued installer %s", installer)
        return False


def consume_queued_installer(paths) -> bool:
    """Boot-time hook: if a queued installer is present, launch it silently
    and return True. The caller is responsible for sys.exit'ing so the
    installer's CloseApplications/InitializeSetup poll has a clean target.

    No-op on Mac and when nothing is queued; safe to call unconditionally
    at startup."""
    installer = get_queued_installer(paths)
    if installer is None:
        return False
    logger.info("Consuming queued installer: %s", installer.name)
    return _spawn_installer_silent(installer)


def install_now(paths) -> dict:
    """User-triggered install: launches the queued installer silently and
    returns a status dict for the route layer. The route handler exits the
    server process after a short delay so the installer's wait-for-close
    actually succeeds."""
    installer = get_queued_installer(paths)
    if installer is None:
        return {"ok": False, "error": "No update queued"}
    ok = _spawn_installer_silent(installer)
    if not ok:
        return {"ok": False, "error": "Could not launch installer"}
    # Schedule a graceful exit shortly after the installer starts. We can
    # rely on the installer's uninstall-poll to wait for the old version
    # to fully close.
    import threading
    threading.Timer(1.5, lambda: os._exit(0)).start()  # type: ignore[name-defined]
    return {"ok": True, "filename": installer.name}


def download_pending_update_if_any(storage, paths, dismissed_versions: list[str] | None = None) -> dict:
    """Periodic-sync hook: check for a newer release and, if one is
    available and not already queued at the same-or-newer version,
    download it into the queue dir.

    Returns a small dict the sync log uses; never raises.
    """
    if not sys.platform.startswith("win"):
        return {"skipped": "not windows"}
    try:
        info = check_for_update(storage, dismissed_versions=dismissed_versions or [])
    except Exception:
        logger.exception("update-poll: check_for_update raised")
        return {"error": "check failed"}
    if info is None:
        return {"newer": False}

    # Don't re-download if the queued installer is already this version or
    # newer.
    existing = get_queued_installer(paths)
    if existing is not None:
        parsed = parse_release_filename(existing.name)
        if parsed and parse_semver(parsed[1]) >= parse_semver(info.version):
            return {"already_queued": parsed[1]}

    try:
        local = download_update(storage, info)
    except Exception:
        logger.exception("update-poll: download_update raised")
        return {"error": "download failed"}
    try:
        queue_installer_for_next_launch(local, paths)
    except Exception:
        logger.exception("update-poll: queue raised")
        return {"error": "queue failed"}
    return {"queued": info.version}


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
