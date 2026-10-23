from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ...storage.base import StorageProvider
from ...version import get_app_version

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
    return get_app_version(default="0.0.0")


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


def _update_marker_path(paths) -> Path:
    return _queued_installer_dir(paths) / "update-in-progress.json"


def _process_is_running(pid: int) -> bool:
    """Return whether *pid* still identifies a live process.

    Windows does not provide ``kill(pid, 0)`` with Unix-compatible behavior,
    so use the process handle API there.  This is deliberately local-only:
    the marker is advisory UX state, not an authorization boundary.
    """
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                    handle, ctypes.byref(exit_code)
                ):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Could not inspect updater process %s", pid)
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _record_update_process(
    paths, installer: Path, process, *, relaunch: bool = True
) -> None:
    """Persist enough state for a second launch to explain what is happening."""
    pid = int(getattr(process, "pid", 0) or 0)
    if not sys.platform.startswith("win") or pid <= 0:
        return
    parsed = parse_release_filename(installer.name)
    version = parsed[1] if parsed else ""
    marker = _update_marker_path(paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temp = marker.with_suffix(".tmp")
    temp.write_text(
        json.dumps({
            "pid": pid,
            "version": version,
            "filename": installer.name,
            "started_at": time.time(),
            "relaunch": relaunch,
        }),
        encoding="utf-8",
    )
    temp.replace(marker)


def get_active_update(paths) -> dict | None:
    """Return an active Windows installer marker, cleaning stale state.

    The newly installed version can start from Inno Setup's ``[Run]`` section
    just before the installer process itself exits.  Version comparison lets
    that intended launch through while still blocking a user from starting the
    older executable again during the replacement window.
    """
    marker = _update_marker_path(paths)
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("update marker must be an object")
        pid = int(data.get("pid") or 0)
        version = str(data.get("version") or "")
        started_at = float(data.get("started_at") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        _delete_quietly(marker)
        return None
    if version and parse_semver(version) <= parse_semver(get_embedded_version()):
        _delete_quietly(marker)
        return None
    # Avoid a recycled Windows PID turning a long-abandoned marker into a
    # permanent startup block. Real installs should finish within minutes.
    if started_at <= 0 or time.time() - started_at > 30 * 60:
        _delete_quietly(marker)
        return None
    if not _process_is_running(pid):
        _delete_quietly(marker)
        return None
    return data


def show_update_in_progress_notice(info: dict) -> None:
    """Tell a Windows user why a second launch cannot open yet."""
    if not sys.platform.startswith("win"):
        return
    version = str(info.get("version") or "").strip()
    version_label = f"v{version}" if version else "the latest version"
    if info.get("relaunch", True):
        next_step = "DTM will start automatically when the update finishes."
    else:
        next_step = "Wait for it to finish, then open DTM again."
    message = (
        f"DTM Vehicle Builder is updating to {version_label}.\n\n"
        f"The Windows installer is still working. {next_step}"
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, message, "DTM Vehicle Builder update", 0x40
        )
    except Exception:
        logger.exception("Could not show update-in-progress notice")


def queue_installer_for_next_launch(local_path: Path, paths) -> Path:
    """Move a freshly-downloaded installer into the queue dir so the next
    app close (or an explicit Restart & Install click) can apply it.

    A single installer is queued at a time — any older queued file with a
    different name is removed first. Returns the queued path.
    """
    queue_dir = _queued_installer_dir(paths)
    queue_dir.mkdir(parents=True, exist_ok=True)
    # Drop older queued installers; only the newest should be present.
    for stale in queue_dir.iterdir():
        if stale.name == local_path.name:
            continue
        if parse_release_filename(stale.name) is None:
            # Preserve updater coordination state and the most recent Inno
            # log; only versioned installer artifacts compete for this slot.
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


def _expected_installer_suffix() -> str | None:
    """Which file extension is auto-installable on this platform.

    Windows: ".exe" (Inno Setup silent install)
    macOS:   ".dmg" (mount + .app copy)
    Other:   None — auto-update is unsupported, manual download only.
    """
    if sys.platform.startswith("win"):
        return ".exe"
    if sys.platform.startswith("darwin"):
        return ".dmg"
    return None


def get_queued_installer(paths) -> Path | None:
    """Return the queued installer path if one is present, else None.

    Looks for ``.exe`` on Windows and ``.dmg`` on macOS; returns None
    on other platforms where silent auto-install isn't implemented.
    Always returns None in dev — a queued file in dev would just nag
    the user to restart for a version that's older than what they're
    already running."""
    from ...paths import _DEV
    if _DEV:
        return None
    suffix = _expected_installer_suffix()
    if suffix is None:
        return None
    queue_dir = _queued_installer_dir(paths)
    if not queue_dir.exists():
        return None
    for entry in queue_dir.iterdir():
        if entry.suffix.lower() == suffix and entry.is_file():
            return entry
    return None


def get_pending_update_info(paths) -> dict | None:
    """Status-endpoint helper: describe the queued installer (if any).

    Returns ``{"version": "...", "filename": "..."}`` only when the
    queued installer is for a STRICTLY NEWER version than the one
    currently running. If we just finished installing this version, the
    file is still on disk but pointing at the version we already are —
    we delete it here so the next boot doesn't re-run it (the v2.2.4
    install-loop bug). None when there's nothing queued, the queue is
    stale, or the platform is unsupported.
    """
    queued = get_queued_installer(paths)
    if queued is None:
        return None
    parsed = parse_release_filename(queued.name)
    if not parsed:
        return None
    queued_version = parsed[1]
    if parse_semver(queued_version) <= parse_semver(get_embedded_version()):
        _delete_quietly(queued)
        return None
    return {"version": queued_version, "filename": queued.name}


def _delete_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        logger.exception("Could not remove stale queued installer %s", path)


def _spawn_installer_silent(
    installer: Path, *, visible: bool = True, relaunch: bool = True
) -> object | bool:
    """Platform-dispatching silent installer launcher.

    Windows: Inno Setup /SILENT for an explicit restart, or /VERYSILENT
    when applying a ready update after a normal close.
    macOS: shell script that waits for the running app to exit, mounts
    the DMG, swaps the .app in place, strips quarantine, and relaunches.

    Returns True if the install process started without raising."""
    if sys.platform.startswith("win"):
        return _spawn_installer_silent_windows(
            installer, visible=visible, relaunch=relaunch
        )
    if sys.platform.startswith("darwin"):
        return _spawn_installer_silent_mac(installer)
    logger.warning("Silent install not supported on %s", sys.platform)
    return False


def _write_windows_update_script(installer: Path) -> Path:
    """Write the detached Windows handoff that waits for this app to exit.

    Explicit restarts use one independent progress window for the complete
    handoff, silent install, and relaunch.  The app does not close until that
    window confirms it is visible.
    """
    script_path = installer.parent / "run-windows-update.ps1"
    script_path.write_text(
        r'''param(
    [Parameter(Mandatory = $true)][int]$WaitForPid,
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][ValidateSet('visible', 'background')][string]$Mode,
    [Parameter(Mandatory = $true)][ValidateSet('0', '1')][string]$Relaunch,
    [Parameter(Mandatory = $true)][string]$ReadyPath
)

$script:ProgressForm = $null
$script:StatusLabel = $null

function Write-UpdateLog([string]$Message) {
    Add-Content -LiteralPath $LogPath -Value $Message -ErrorAction SilentlyContinue
}

function Pump-ProgressWindow {
    if ($null -ne $script:ProgressForm) {
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Set-ProgressStatus([string]$Message) {
    if ($null -ne $script:StatusLabel) {
        $script:StatusLabel.Text = $Message
        $script:ProgressForm.Refresh()
        Pump-ProgressWindow
    }
}

function Close-ProgressWindow {
    if ($null -ne $script:ProgressForm) {
        $script:ProgressForm.Close()
        $script:ProgressForm.Dispose()
        $script:ProgressForm = $null
    }
}

function Test-DtmWindowVisible {
    foreach ($candidate in (Get-Process -Name 'DTM Vehicle Builder' -ErrorAction SilentlyContinue)) {
        if ($candidate.MainWindowHandle -ne 0) {
            return $true
        }
    }
    return $false
}

function Show-ProgressWindow {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        [System.Windows.Forms.Application]::EnableVisualStyles()

        $script:ProgressForm = New-Object System.Windows.Forms.Form
        $script:ProgressForm.Text = 'Updating DTM Vehicle Builder'
        $script:ProgressForm.ClientSize = New-Object System.Drawing.Size(470, 128)
        $script:ProgressForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
        $script:ProgressForm.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
        $script:ProgressForm.MaximizeBox = $false
        $script:ProgressForm.MinimizeBox = $false
        $script:ProgressForm.ControlBox = $false
        $script:ProgressForm.ShowInTaskbar = $true
        $script:ProgressForm.TopMost = $true

        $heading = New-Object System.Windows.Forms.Label
        $heading.AutoSize = $false
        $heading.Location = New-Object System.Drawing.Point(22, 18)
        $heading.Size = New-Object System.Drawing.Size(426, 24)
        $heading.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
        $heading.Text = 'Installing the DTM update'

        $script:StatusLabel = New-Object System.Windows.Forms.Label
        $script:StatusLabel.AutoSize = $false
        $script:StatusLabel.Location = New-Object System.Drawing.Point(22, 48)
        $script:StatusLabel.Size = New-Object System.Drawing.Size(426, 22)
        $script:StatusLabel.Font = New-Object System.Drawing.Font('Segoe UI', 9)
        $script:StatusLabel.Text = 'Closing DTM safely...'

        $progress = New-Object System.Windows.Forms.ProgressBar
        $progress.Location = New-Object System.Drawing.Point(22, 82)
        $progress.Size = New-Object System.Drawing.Size(426, 18)
        $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
        $progress.MarqueeAnimationSpeed = 24

        $script:ProgressForm.Controls.Add($heading)
        $script:ProgressForm.Controls.Add($script:StatusLabel)
        $script:ProgressForm.Controls.Add($progress)
        $script:ProgressForm.Show()
        $script:ProgressForm.Activate()
        Pump-ProgressWindow
    } catch {
        Write-UpdateLog 'Could not display the update handoff window.'
        $script:ProgressForm = $null
    }

}

if ($Mode -eq 'visible') {
    Show-ProgressWindow
    if (
        $null -eq $script:ProgressForm -or
        -not $script:ProgressForm.IsHandleCreated -or
        -not $script:ProgressForm.Visible
    ) {
        Write-UpdateLog 'The update progress window did not become visible.'
        exit 2
    }
    # Give Windows one paint cycle before authorizing the app to disappear.
    Start-Sleep -Milliseconds 150
    Pump-ProgressWindow
    Set-Content -LiteralPath $ReadyPath -Value 'ready' -Encoding ASCII -Force
}

$deadline = [DateTime]::UtcNow.AddMinutes(2)
while (Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue) {
    if ([DateTime]::UtcNow -ge $deadline) {
        Write-UpdateLog 'Timed out waiting for DTM to close.'
        Set-ProgressStatus 'DTM could not close automatically. Please close it and try again.'
        if ($Mode -eq 'visible') {
            [System.Windows.Forms.MessageBox]::Show(
                'DTM could not close automatically. Please close it and try the update again.',
                'DTM Vehicle Builder update'
            ) | Out-Null
        }
        Close-ProgressWindow
        Remove-Item -LiteralPath $ReadyPath -Force -ErrorAction SilentlyContinue
        exit 1460
    }
    Pump-ProgressWindow
    Start-Sleep -Milliseconds 100
}

try {
    $displayArguments = '/VERYSILENT /SUPPRESSMSGBOXES'
    if ($Mode -eq 'visible') {
        Set-ProgressStatus 'Installing the update. This can take up to a minute...'
    }
    $installerArguments = $displayArguments + ' /NORESTART /CLOSEAPPLICATIONS /RELAUNCH=' + $Relaunch + ' /LOG="' + $LogPath + '"'
    $installer = Start-Process -FilePath $InstallerPath -ArgumentList $installerArguments -PassThru
    if ($Mode -eq 'visible') {
        $installStarted = [DateTime]::UtcNow
        $installingFilesShown = $false
        $finishingShown = $false
        while (-not $installer.HasExited) {
            $elapsed = ([DateTime]::UtcNow - $installStarted).TotalSeconds
            if (-not $installingFilesShown -and $elapsed -ge 8) {
                Set-ProgressStatus 'Installing updated files...'
                $installingFilesShown = $true
            }
            if (-not $finishingShown -and $elapsed -ge 30) {
                Set-ProgressStatus 'Finishing the installation...'
                $finishingShown = $true
            }
            Pump-ProgressWindow
            Start-Sleep -Milliseconds 100
        }
    }
    $installer.WaitForExit()
    $exitCode = $installer.ExitCode
    if ($Mode -eq 'visible' -and $exitCode -eq 0 -and $Relaunch -eq '1') {
        Set-ProgressStatus 'Update installed. Starting DTM Vehicle Builder...'
        $startupDeadline = [DateTime]::UtcNow.AddMinutes(2)
        while ([DateTime]::UtcNow -lt $startupDeadline) {
            if (Test-DtmWindowVisible) {
                break
            }
            Pump-ProgressWindow
            Start-Sleep -Milliseconds 100
        }
        if (-not (Test-DtmWindowVisible)) {
            Set-ProgressStatus 'The update is installed, but DTM did not reopen automatically.'
            [System.Windows.Forms.MessageBox]::Show(
                'The update finished, but DTM did not reopen automatically. Open DTM Vehicle Builder from your shortcut.',
                'DTM Vehicle Builder update'
            ) | Out-Null
        }
    }
} catch {
    Write-UpdateLog 'Could not launch the DTM installer.'
    Set-ProgressStatus 'The Windows installer could not start.'
    if ($Mode -eq 'visible') {
        [System.Windows.Forms.MessageBox]::Show(
            'The Windows installer could not start. Reopen DTM and try the update again.',
            'DTM Vehicle Builder update'
        ) | Out-Null
    }
    $exitCode = 1
}

Close-ProgressWindow
Remove-Item -LiteralPath $ReadyPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit $exitCode
''',
        encoding="utf-8",
    )
    return script_path


def _wait_for_windows_handoff_ready(
    process: subprocess.Popen, ready_path: Path, *, timeout: float = 30.0
) -> bool:
    """Keep the app visible until the detached progress UI is on screen."""
    if not hasattr(process, "poll"):
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready_path.is_file():
            _delete_quietly(ready_path)
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _spawn_installer_silent_windows(
    installer: Path, *, visible: bool = True, relaunch: bool = True
) -> subprocess.Popen | bool:
    """Schedule Inno Setup only after the current DTM process has exited.

    Starting Inno before pywebview and Python finish shutting down leaves the
    executable locked.  The detached PowerShell handoff waits on this PID,
    then launches the requested unattended installer mode and remains alive
    through completion so the in-progress marker stays meaningful.
    """
    try:
        script_path = _write_windows_update_script(installer)
        ready_path = installer.parent / "windows-update-window-ready"
        ready_path.unlink(missing_ok=True)
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
                "-WaitForPid",
                str(os.getpid()),
                "-InstallerPath",
                str(installer),
                "-LogPath",
                str(installer.parent / "windows-update.log"),
                "-Mode",
                "visible" if visible else "background",
                "-Relaunch",
                "1" if relaunch else "0",
                "-ReadyPath",
                str(ready_path),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if visible and not _wait_for_windows_handoff_ready(process, ready_path):
            logger.error("Windows update progress window did not become ready")
            try:
                process.terminate()
            except Exception:
                logger.exception("Could not stop failed Windows updater handoff")
            return False
        return process
    except Exception:
        logger.exception("Could not schedule queued installer %s", installer)
        return False


def _spawn_installer_silent_mac(dmg: Path) -> bool:
    """Spin up a detached shell script that mount-copy-unmount-relaunches.

    Has to run as a separate process because the .app being replaced is
    the one we're running from. Caller is expected to sys.exit shortly
    after this returns so the script's pgrep wait can finish promptly.
    """
    app_path = _resolve_running_app_bundle()
    if app_path is None:
        logger.warning(
            "Mac auto-update: couldn't resolve running .app path from %s; "
            "skipping silent install",
            sys.executable,
        )
        return False
    script_path = _write_mac_update_script()
    if script_path is None:
        return False
    try:
        subprocess.Popen(
            ["/bin/bash", str(script_path), str(dmg), str(app_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach from our process group
        )
        logger.info(
            "Spawned Mac update script (dmg=%s, target=%s)",
            dmg.name, app_path,
        )
        return True
    except Exception:
        logger.exception("Could not spawn Mac update script")
        return False


def _resolve_running_app_bundle() -> Path | None:
    """Walk up from sys.executable to the enclosing .app bundle.

    PyInstaller-built bundles put the launcher at
    ``<App>.app/Contents/MacOS/<exe>``, so the .app is two parents up.
    Returns None in dev mode (python binary outside an .app)."""
    try:
        p = Path(sys.executable).resolve()
        for parent in p.parents:
            if parent.suffix == ".app":
                return parent
    except Exception:
        logger.exception("_resolve_running_app_bundle failed")
    return None


def _write_mac_update_script() -> Path | None:
    """Write the update script to /tmp and chmod +x. Returns its path."""
    script = r"""#!/bin/bash
# DTM Vehicle Builder Mac silent update.
# Args: $1 = DMG path, $2 = target .app path
set +e
DMG_PATH="$1"
APP_PATH="$2"
LOG="$HOME/Library/Logs/DTM_Vehicle_Builder_update.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo ""
echo "=== Silent update $(date) ==="
echo "DMG:    $DMG_PATH"
echo "Target: $APP_PATH"

# Let the parent process exit cleanly. Then poll for a few seconds in
# case Python is slow to release file handles.
sleep 2
for i in 1 2 3 4 5 6 7 8; do
  if ! pgrep -f "DTM Vehicle Builder.app/Contents/MacOS" >/dev/null; then
    break
  fi
  echo "Waiting for app to exit ($i)..."
  sleep 1
done

# Mount the DMG (hidden, no verify — the artifact is trusted because we
# downloaded it from our own SharePoint via an authenticated Graph call).
MOUNT_INFO=$(hdiutil attach -nobrowse -noverify -noautoopen "$DMG_PATH" 2>&1)
echo "$MOUNT_INFO"
MOUNTPOINT=$(echo "$MOUNT_INFO" | awk -F'\t' '/\/Volumes\//{print $NF; exit}')
if [ -z "$MOUNTPOINT" ]; then
  echo "Could not determine mountpoint; aborting."
  exit 1
fi
echo "Mounted at $MOUNTPOINT"

# The DMG layout is `<root>/<App>.app` plus a /Applications symlink.
# Avoid the symlink: find the real bundle.
SOURCE_APP=$(find "$MOUNTPOINT" -maxdepth 2 -name "*.app" -not -path "*/Applications/*" | head -1)
if [ -z "$SOURCE_APP" ]; then
  echo "Could not find a .app inside $MOUNTPOINT; aborting."
  hdiutil detach "$MOUNTPOINT" -force >/dev/null 2>&1
  exit 1
fi
echo "Source: $SOURCE_APP"

# Replace the old app. If the user is running from /Applications without
# admin rights, this will fail loudly — better than partially overwriting.
if [ -d "$APP_PATH" ]; then
  rm -rf "$APP_PATH" || { echo "Could not delete old .app"; hdiutil detach "$MOUNTPOINT" -force >/dev/null 2>&1; exit 1; }
fi
cp -R "$SOURCE_APP" "$APP_PATH" || { echo "Copy failed"; hdiutil detach "$MOUNTPOINT" -force >/dev/null 2>&1; exit 1; }

# Strip quarantine so Gatekeeper doesn't block the first launch with a
# "downloaded from internet" prompt (we just installed it ourselves —
# user did NOT double-click anything from a browser).
xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true

# Clean up
hdiutil detach "$MOUNTPOINT" -force >/dev/null 2>&1
rm -f "$DMG_PATH"

# Relaunch into the new version.
echo "Relaunching..."
open "$APP_PATH"
echo "=== Done $(date) ==="
"""
    try:
        import tempfile
        script_path = Path(tempfile.gettempdir()) / f"dtm_update_{os.getpid()}.sh"
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path
    except OSError:
        logger.exception("Could not write Mac update script")
        return None


def consume_queued_installer(paths) -> bool:
    """Boot-time hook: if a queued installer is present AND it's a newer
    version than the one currently running, launch it and
    return True. The caller is responsible for sys.exit'ing so the
    installer can replace the running executable cleanly.

    Critical version check: without it, every boot would re-launch the
    same installer that produced the version we just started, causing
    an unrecoverable install loop the v2.2.4 release hit. If queued <=
    current, the file is deleted in place — the install is already
    done, the artifact is just leftover.

    No-op on Mac and when nothing is queued; safe to call unconditionally
    at startup."""
    installer = get_queued_installer(paths)
    if installer is None:
        return False
    parsed = parse_release_filename(installer.name)
    if not parsed:
        # Unrecognisable filename — refuse to launch it as an installer.
        _delete_quietly(installer)
        return False
    queued_version = parsed[1]
    current = get_embedded_version()
    if parse_semver(queued_version) <= parse_semver(current):
        logger.info(
            "Discarding stale queued installer %s (current=%s, queued=%s)",
            installer.name, current, queued_version,
        )
        _delete_quietly(installer)
        return False
    logger.info(
        "Consuming queued installer: %s (current=%s -> %s)",
        installer.name, current, queued_version,
    )
    process = _spawn_installer_silent(installer)
    if not process:
        return False
    _record_update_process(paths, installer, process)
    return True


def install_now(paths, *, visible: bool = True) -> dict:
    """Launch the queued installer and return status to the caller.

    Process shutdown belongs to the desktop window owner in ``server.main``.
    Keeping it there lets the existing active-upload guard run and gives the
    server, background workers, and webview a normal cleanup path instead of
    terminating the process with ``os._exit``.
    """
    installer = get_queued_installer(paths)
    if installer is None:
        return {"ok": False, "error": "No update queued"}
    parsed = parse_release_filename(installer.name)
    if parsed:
        if parse_semver(parsed[1]) <= parse_semver(get_embedded_version()):
            _delete_quietly(installer)
            return {"ok": False, "error": "Already up to date"}
    relaunch = visible
    process = _spawn_installer_silent(
        installer, visible=visible, relaunch=relaunch
    )
    if not process:
        return {"ok": False, "error": "Could not launch installer"}
    _record_update_process(paths, installer, process, relaunch=relaunch)
    return {"ok": True, "filename": installer.name}


_download_in_progress: set[str] = set()  # version strings currently downloading
_last_known_available: dict | None = None
_last_download_failure: dict | None = None
_DOWNLOAD_RETRY_DELAY_SECONDS = 15 * 60


def is_download_in_progress() -> str | None:
    """Status helper: returns the version string currently being downloaded
    by the background sync, or None when no download is active."""
    if not _download_in_progress:
        return None
    return next(iter(_download_in_progress))


def download_pending_update_if_any(storage, paths, dismissed_versions: list[str] | None = None) -> dict:
    """Periodic-sync hook: check for a newer release and, if one is
    available and not already queued at the same-or-newer version,
    download it into the queue dir.

    Runs on Windows (queues .exe) and macOS (queues .dmg). Other
    platforms are no-op until we add an installer pattern for them.

    Dev launches (source checkout, not the bundled .app) never download:
    dev IS the most-current copy, so any "newer" tag is by definition
    older than the working tree.

    Returns a small dict the sync log uses; never raises.
    """
    from ...paths import _DEV
    if _DEV:
        return {"skipped": "dev build"}
    if _expected_installer_suffix() is None:
        return {"skipped": f"no auto-update for {sys.platform}"}
    global _last_known_available, _last_download_failure

    # A failed large-installer transfer should not restart every 60 seconds.
    # Keep ordinary cloud sync moving and retry on a modest backoff instead.
    if _last_download_failure:
        retry_at = float(_last_download_failure.get("retry_at", 0))
        if time.monotonic() < retry_at:
            return {
                "retry_scheduled": _last_download_failure.get("version", ""),
            }

    try:
        info = check_for_update(storage, dismissed_versions=dismissed_versions or [])
    except Exception:
        logger.exception("update-poll: check_for_update raised")
        return {"error": "check failed"}
    if info is None:
        _last_known_available = None
        _last_download_failure = None
        return {"newer": False}

    _last_known_available = {
        "version": info.version,
        "filename": info.filename,
    }

    # Don't re-download if the queued installer is already this version or
    # newer.
    existing = get_queued_installer(paths)
    if existing is not None:
        parsed = parse_release_filename(existing.name)
        if parsed and parse_semver(parsed[1]) >= parse_semver(info.version):
            return {"already_queued": parsed[1]}

    _download_in_progress.add(info.version)
    try:
        try:
            local = download_update(storage, info)
        except Exception:
            logger.exception("update-poll: download_update raised")
            _last_download_failure = {
                "version": info.version,
                "retry_at": time.monotonic() + _DOWNLOAD_RETRY_DELAY_SECONDS,
            }
            return {"error": "download failed"}
        try:
            queue_installer_for_next_launch(local, paths)
        except Exception:
            logger.exception("update-poll: queue raised")
            _last_download_failure = {
                "version": info.version,
                "retry_at": time.monotonic() + _DOWNLOAD_RETRY_DELAY_SECONDS,
            }
            return {"error": "queue failed"}
        _last_download_failure = None
        return {"queued": info.version}
    finally:
        _download_in_progress.discard(info.version)


def describe_update_state(paths, *, available_info: dict | None = None) -> dict:
    """Single source of truth for "what's the update situation right now?".

    Used by cloud_status_service so the UI can render a clear one-line
    state instead of guessing from a mix of /api/update/check and
    pending_update fields. Possible states:

      - "dev_build" — running from a source checkout; auto-update is
        disabled because dev IS the newest copy by definition.
      - "up_to_date" — nothing newer available, nothing queued
      - "downloading" — background sync is fetching the installer now
      - "ready" — installer is queued, restart will install it
      - "available" — newer version exists but auto-download isn't
        configured for this platform. UI offers a manual download.
      - "platform_unsupported" — Linux (no installer pattern at all)
    """
    from ...paths import _DEV
    current = get_embedded_version()
    if _DEV:
        return {"state": "dev_build", "current": current}
    pending = get_pending_update_info(paths)
    if pending:
        return {"state": "ready", "current": current, "ready_version": pending["version"]}
    in_progress = is_download_in_progress()
    if in_progress:
        return {"state": "downloading", "current": current, "downloading_version": in_progress}
    known_available = available_info or _last_known_available
    if known_available:
        return {
            "state": "available",
            "current": current,
            "available_version": known_available.get("version", ""),
            "automatic_retry_pending": bool(_last_download_failure),
        }
    if _expected_installer_suffix() is not None:
        return {"state": "up_to_date", "current": current}
    # Linux / other: no installer pattern and no cached release result.
    return {"state": "platform_unsupported", "current": current}


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
