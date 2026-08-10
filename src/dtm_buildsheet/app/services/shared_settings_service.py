from __future__ import annotations

import logging
import os
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
    """Read-only mirror of a cloud settings folder into a local cache.

    Used for both the flat ``/Settings/`` directory (bundled config files
    like ``vehicle_layouts.json``) and per-record subdirectories
    (``/Settings/agencies/``, ``/Settings/sales_reps/``, ``/Settings/presets/``).

    The contract is deliberately narrow: pull the latest cloud contents
    into a cache directory and let existing services keep reading files
    off disk. eTags from the listing response let us skip the per-file
    fetch on every poll when nothing has changed.

    Set ``propagate_deletions=True`` to also remove local files that were
    present in the prior sync's state but are absent from cloud now. Used
    for per-record entities where last-writer-wins is the contract.
    Default is False because the flat ``/Settings/`` syncs settings whose
    bundled defaults seed the workspace on first install — propagating
    a cloud-side deletion would nuke those defaults locally without a
    way to get them back.
    """

    def __init__(
        self,
        remote: StorageProvider,
        cache_dir: Path,
        *,
        remote_folder: str = SETTINGS_REMOTE_FOLDER,
        local_storage: StorageProvider | None = None,
        etag_cache_filename: str = ".settings_etags.json",
        propagate_deletions: bool = False,
    ) -> None:
        self._remote = remote
        self._cache_dir = Path(cache_dir)
        self._remote_folder = remote_folder.strip("/")
        self._local = local_storage or LocalStorageProvider()
        self._etag_cache_filename = etag_cache_filename
        self._propagate_deletions = propagate_deletions

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def sync_all(self) -> SyncReport:
        """Copy every file in the remote settings folder into the local cache.

        Uses Graph eTags to skip the per-file content fetch when the cloud
        copy hasn't changed since the last sync — the previous sync's
        eTags are stored in ``self._cache_dir / '.settings_etags.json'``
        and consulted on every iteration. Files are written via the
        atomic temp-and-rename helper on the local side, so a crash
        mid-sync leaves the existing cache intact. Files that exist
        locally but not remotely are *not* removed — that's a deliberate
        guard against an empty/partial remote nuking a working cache.
        """
        report = SyncReport()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            remote_entries = self._remote.list_files_with_metadata(self._remote_folder)
        except FileNotFoundError:
            logger.warning("Remote settings folder %r is missing", self._remote_folder)
            return report

        prior_etags = self._load_etags()
        current_etags: dict[str, str] = {}
        for entry in remote_entries:
            name = entry.path.rsplit("/", 1)[-1]
            # The publish workflow uploads a {filename}.meta.json sidecar
            # alongside each settings file for Power Automate Flow A to read.
            # Those sidecars aren't actual config; pulling them into the
            # workspace config dir pollutes it with non-loadable JSON.
            if name.endswith(".meta.json"):
                continue
            # ci-connection-test.json is a smoke-test artifact left in
            # /Settings/ from the cloud-pipeline validation. Not real config.
            if name == "ci-connection-test.json":
                continue

            local_path = self._cache_dir / name
            prior_etag = prior_etags.get(name, "")
            if entry.etag and prior_etag == entry.etag and local_path.exists():
                # Fast path: cloud hasn't changed since we last synced this
                # one. Skip the content fetch entirely.
                current_etags[name] = entry.etag
                report.unchanged.append(name)
                continue

            try:
                payload = self._remote.read_bytes(entry.path)
            except Exception as exc:  # noqa: BLE001 — adapter surfaces many error shapes
                logger.exception("Failed to fetch %s from remote settings", name)
                report.failed.append((name, str(exc)))
                if prior_etag:
                    current_etags[name] = prior_etag  # try again next time
                continue

            if local_path.exists() and local_path.read_bytes() == payload:
                report.unchanged.append(name)
            else:
                self._local.write_bytes(str(local_path), payload)
                report.updated.append(name)
            current_etags[name] = entry.etag

        # Deletion propagation: anything in the prior eTag manifest but
        # absent from current cloud was removed by some other device.
        # Delete the local copy so this device follows.
        if self._propagate_deletions:
            for name in prior_etags:
                if name in current_etags:
                    continue  # still in cloud
                local_path = self._cache_dir / name
                if not local_path.exists():
                    continue  # already gone locally
                try:
                    local_path.unlink()
                    report.updated.append(f"(deleted) {name}")
                except OSError:
                    logger.exception("Could not delete local %s", local_path)

        self._save_etags(current_etags)
        return report

    def _etag_path(self):
        return self._cache_dir / self._etag_cache_filename

    def _load_etags(self) -> dict[str, str]:
        path = self._etag_path()
        if not path.exists():
            return {}
        try:
            import json as _json
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_etags(self, etags: dict[str, str]) -> None:
        import json as _json
        try:
            self._etag_path().write_text(_json.dumps(etags, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not write settings eTag cache")

    def read_cached_text(self, filename: str) -> str:
        return (self._cache_dir / filename).read_text(encoding="utf-8")


def sync_shared_settings_at_startup(paths: AppPaths) -> SyncReport | None:
    """Pull the latest team settings into the local workspace.

    Phase 2e entrypoint — runs at startup and then on the 60s periodic
    timer. Pulls four directories independently:

      /Settings/                  → workspace_config_dir
      /Settings/agencies/         → workspace_dir / "agencies"
      /Settings/sales_reps/       → workspace_dir / "sales_reps"
      /Settings/presets/          → workspace_presets_dir

    The flat /Settings/ sync is pull-only — its files have bundled defaults
    that seed the workspace on first install, so propagating a cloud
    deletion would orphan the local copy with no way to recover. The three
    per-record subdir syncs DO propagate deletions; combined with delete
    proposals (handled by the pickup workflow when proposal action='delete')
    this is what makes "delete an agency on Device A and it disappears
    everywhere within ~minutes" work end-to-end.

    Errors are logged and swallowed: startup must succeed even if the
    network is down or the user isn't signed in. Returns the FLAT-sync
    SyncReport for backwards compat with the call sites that inspect
    .updated for the data_version bump; the subdir reports are merged in
    by aggregating their .updated lists.
    """
    # Dev escape hatch: when DTM_DEV_NO_SETTINGS_PULL is set, never pull
    # /Settings/ from the cloud, so local config edits (parts_db.json, etc.)
    # made by the offline tools aren't clobbered mid-development. Outbound
    # mirror still fires on save, so changes continue to propagate up.
    if os.environ.get("DTM_DEV_NO_SETTINGS_PULL"):
        logger.info("DTM_DEV_NO_SETTINGS_PULL set — skipping inbound shared-settings pull")
        return None

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

    aggregate_report = SyncReport()
    try:
        # 1. Flat /Settings/ — bundled config files; preserve local on
        #    cloud-side deletions.
        flat = SharedSettingsService(
            remote=bundle.storage,
            cache_dir=paths.workspace_config_dir,
        )
        flat_report = flat.sync_all()
        aggregate_report.updated.extend(flat_report.updated)
        aggregate_report.unchanged.extend(flat_report.unchanged)
        aggregate_report.failed.extend(flat_report.failed)

        # 2-4. Per-record subdirs with deletion propagation. Each gets its
        #      own eTag cache file in the destination dir so the three
        #      states stay independent.
        for remote_subfolder, local_dir in _SUBDIR_TARGETS(paths):
            local_dir.mkdir(parents=True, exist_ok=True)
            subdir_service = SharedSettingsService(
                remote=bundle.storage,
                cache_dir=local_dir,
                remote_folder=remote_subfolder,
                etag_cache_filename=".settings_etags.json",
                propagate_deletions=True,
            )
            sub_report = subdir_service.sync_all()
            # Tag the subdir's update entries so the log makes it clear
            # which records changed where.
            tag = remote_subfolder.rsplit("/", 1)[-1]
            aggregate_report.updated.extend(f"{tag}/{n}" for n in sub_report.updated)
            aggregate_report.unchanged.extend(f"{tag}/{n}" for n in sub_report.unchanged)
            aggregate_report.failed.extend(
                (f"{tag}/{name}", err) for name, err in sub_report.failed
            )
    except Exception:
        logger.exception("Shared-settings sync raised; continuing startup")
        return None

    if aggregate_report.updated:
        logger.info(
            "Synced %d shared settings file(s): %s",
            len(aggregate_report.updated),
            ", ".join(aggregate_report.updated),
        )
    if aggregate_report.failed:
        logger.warning(
            "Shared-settings sync had %d failure(s): %s",
            len(aggregate_report.failed),
            aggregate_report.failed,
        )
    return aggregate_report


def _SUBDIR_TARGETS(paths: AppPaths) -> list[tuple[str, Path]]:
    """Return [(remote_folder, local_dir), ...] for the three per-record syncs.

    Helper exists so the call site stays readable and tests can patch the
    list when exercising specific subdirs. Order is stable so log output
    is predictable.
    """
    return [
        (f"{SETTINGS_REMOTE_FOLDER}/agencies", paths.workspace_dir / "agencies"),
        (f"{SETTINGS_REMOTE_FOLDER}/sales_reps", paths.workspace_dir / "sales_reps"),
        (f"{SETTINGS_REMOTE_FOLDER}/presets", paths.workspace_presets_dir),
    ]
