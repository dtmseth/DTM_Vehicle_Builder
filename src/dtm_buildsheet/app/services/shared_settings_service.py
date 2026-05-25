from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ...paths import AppPaths
from ...storage.base import StorageProvider
from ...storage.local import LocalStorageProvider

logger = logging.getLogger(__name__)


# Folder name in the shared backend (SharePoint drive root) that holds the
# review-gated settings JSONs. The trailing slash is omitted by convention to
# match the rest of the codebase.
SETTINGS_REMOTE_FOLDER = "Settings"


@dataclass
class SyncReport:
    """Outcome of a settings-sync pass; useful for surfacing in the UI/log."""

    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (filename, error)

    @property
    def ok(self) -> bool:
        return not self.failed


class SharedSettingsService:
    """Read-only mirror of the cloud `/Settings/` folder into a local cache.

    Phase 2a wires this against ``SharePointGraphProvider``. The contract is
    deliberately narrow: pull the latest contents into a cache directory and
    let existing config-loading code keep reading files off disk. Phase 2e
    will route ``paths.WORKSPACE_CONFIG_DIR`` here.
    """

    def __init__(
        self,
        remote: StorageProvider,
        cache_dir: Path,
        *,
        remote_folder: str = SETTINGS_REMOTE_FOLDER,
        local_storage: StorageProvider | None = None,
    ) -> None:
        self._remote = remote
        self._cache_dir = Path(cache_dir)
        self._remote_folder = remote_folder.strip("/")
        self._local = local_storage or LocalStorageProvider()

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def sync_all(self) -> SyncReport:
        """Copy every file in the remote settings folder into the local cache.

        Files are written via the atomic temp-and-rename helper on the local
        side, so a crash mid-sync leaves the existing cache intact. Files that
        exist locally but not remotely are *not* removed — that's a deliberate
        guard against an empty/partial remote nuking a working cache.
        """
        report = SyncReport()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            remote_files = self._remote.list_files(self._remote_folder)
        except FileNotFoundError:
            logger.warning("Remote settings folder %r is missing", self._remote_folder)
            return report

        for remote_path in remote_files:
            name = remote_path.rsplit("/", 1)[-1]
            try:
                payload = self._remote.read_bytes(remote_path)
            except Exception as exc:  # noqa: BLE001 — adapter surfaces many error shapes
                logger.exception("Failed to fetch %s from remote settings", name)
                report.failed.append((name, str(exc)))
                continue

            local_path = self._cache_dir / name
            if local_path.exists() and local_path.read_bytes() == payload:
                report.unchanged.append(name)
                continue
            self._local.write_bytes(str(local_path), payload)
            report.updated.append(name)

        return report

    def read_cached_text(self, filename: str) -> str:
        return (self._cache_dir / filename).read_text(encoding="utf-8")


def sync_shared_settings_at_startup(paths: AppPaths) -> SyncReport | None:
    """Pull the latest team settings into the local workspace config dir.

    Phase 2e entrypoint — called from ``app/server.py:main()`` after workspace
    bootstrap, before the HTTP server starts serving the UI. Errors are
    logged and swallowed: startup must succeed even if the network is down or
    the user isn't signed in yet. The toast UI in PR #3 surfaces any failure
    later when the user actually tries to save.

    Returns ``None`` when cloud mode is disabled, when no user is signed in,
    or when the sync raised. Returns a ``SyncReport`` otherwise.

    Scope note: this syncs the flat ``/Settings/`` folder only. Per-record
    entities (agencies, sales_reps, presets) live in subfolders and need a
    publish-workflow update before they can flow back to teammates. The
    proposal pipeline already routes their saves correctly — sync of the
    canonical reverse-direction lands in a follow-up.
    """
    # Deferred import — wiring imports nothing from app.services and we want
    # to keep the dependency direction services → adapters.
    from ..adapters import wiring

    if not wiring._cloud_flag_enabled():  # noqa: SLF001 — intentional helper reuse
        return None

    try:
        bundle = wiring.get_active_bundle()
    except Exception:
        logger.exception("Could not build cloud bundle for startup sync")
        return None

    try:
        signed_in = bundle.identity.is_signed_in()
    except Exception:
        logger.exception("Identity check failed during startup sync")
        return None

    if not signed_in:
        logger.info("Skipping shared-settings sync: user not signed in")
        return None

    try:
        service = SharedSettingsService(
            remote=bundle.storage,
            cache_dir=paths.workspace_config_dir,
        )
        report = service.sync_all()
    except Exception:
        logger.exception("Shared-settings sync raised; continuing startup")
        return None

    if report.updated:
        logger.info(
            "Synced %d shared settings file(s): %s",
            len(report.updated),
            ", ".join(report.updated),
        )
    if report.failed:
        logger.warning(
            "Shared-settings sync had %d failure(s): %s",
            len(report.failed),
            report.failed,
        )
    return report
