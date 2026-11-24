"""Best-effort SharePoint durability for Pricing Center files.

The local SQLite database remains the working copy. In cloud-enabled Builder
sessions this module mirrors a transactionally copied database plus source and
export artifacts into the existing SharePoint-backed StorageProvider. A new
device can hydrate the working database before it is initialized.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from pathlib import Path

from .shared_work_service import _cloud_storage

logger = logging.getLogger(__name__)

REMOTE_ROOT = "Pricing Center"
REMOTE_DATABASE = f"{REMOTE_ROOT}/pricing_center.sqlite3"

_queue_lock = threading.Lock()
_pending: dict[str, tuple[Path, str, bool]] = {}
_running = False


def hydrate_database_if_missing(database: Path) -> bool:
    """Restore the shared working database only when no local copy exists."""
    if database.exists():
        return False
    storage = _cloud_storage()
    if storage is None:
        return False
    try:
        content = storage.read_bytes(REMOTE_DATABASE)
        if not content.startswith(b"SQLite format 3\x00"):
            logger.warning("Pricing Center cloud database did not have a SQLite header")
            return False
        database.parent.mkdir(parents=True, exist_ok=True)
        temporary = database.with_name(f".{database.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(database)
        return True
    except Exception:
        # A missing remote database is expected on first use. Local creation
        # proceeds and the next committed change will seed SharePoint.
        return False


def mirror_database_in_background(database: Path) -> None:
    _queue(database, REMOTE_DATABASE, sqlite_snapshot=True)


def mirror_file_in_background(local_path: Path, remote_relative_path: str) -> None:
    safe_relative = "/".join(
        segment for segment in str(remote_relative_path).replace("\\", "/").split("/")
        if segment not in {"", ".", ".."}
    )
    if not safe_relative:
        return
    _queue(local_path, f"{REMOTE_ROOT}/{safe_relative}", sqlite_snapshot=False)


def _queue(local_path: Path, remote_path: str, *, sqlite_snapshot: bool) -> None:
    global _running
    with _queue_lock:
        _pending[remote_path] = (Path(local_path), remote_path, sqlite_snapshot)
        if _running:
            return
        _running = True
    threading.Thread(target=_drain, daemon=True, name="pricing-sharepoint-mirror").start()


def _drain() -> None:
    global _running
    while True:
        with _queue_lock:
            if not _pending:
                _running = False
                return
            _remote_key, work = _pending.popitem()
        local_path, remote_path, sqlite_snapshot = work
        storage = _cloud_storage()
        if storage is None:
            continue
        try:
            content = _sqlite_bytes(local_path) if sqlite_snapshot else local_path.read_bytes()
            storage.write_bytes(remote_path, content)
        except Exception:
            logger.warning("Pricing Center SharePoint mirror failed for %s", remote_path)


def _sqlite_bytes(database: Path) -> bytes:
    temporary = database.with_name(f".{database.name}.{uuid.uuid4().hex}.backup")
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(temporary) as destination:
            source.backup(destination)
        return temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)
