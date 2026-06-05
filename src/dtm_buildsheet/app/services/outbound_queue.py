"""Persistent retry queue for cloud writes that fail at save time.

When a user saves something while offline (or with a stale MSAL token, or
during a transient SharePoint outage), the local write succeeds but the
cloud-side step — submitting a proposal, uploading an export — silently
fails. Without persistence, that change never reaches the cloud unless the
user happens to re-save the same record.

This module persists the failure as a JSON file under
``workspace/.pending_outbound/{kind}/{id}.json``. ``drain_queue`` walks
those files on every sync iteration and at boot, retrying each. Success
deletes the file; failure leaves it for the next drain pass.

Two kinds are queued today:

- ``proposals`` — settings-change proposals (agency / sales-rep / preset
  save+delete) that failed to land in /PendingChanges/. Retried via the
  same ChangeProposalGateway path the original save took.
- ``exports`` — auto-uploads of generated PPTX build sheets to the
  separate company SharePoint library. Retried via the exports upload
  service.

Local-only writes (cloud disabled, no cloud_config) never get queued —
there's nowhere to send them and queueing forever would be misleading.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...paths import AppPaths

logger = logging.getLogger(__name__)


_QUEUE_DIRNAME = ".pending_outbound"
_PROPOSALS_KIND = "proposals"
_EXPORTS_KIND = "exports"

# Limit on the number of queued items we drain per cycle. A backlog from a
# multi-day outage would otherwise stall the 60s sync indefinitely; better
# to make progress in chunks and let subsequent cycles finish the job.
_MAX_DRAIN_PER_CYCLE = 25


def _queue_dir(paths: AppPaths, kind: str) -> Path:
    return paths.workspace_dir / _QUEUE_DIRNAME / kind


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(stem: str) -> str:
    """Make stem safe for use as a filename across platforms."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")
    return cleaned or "queued"


# ── Enqueue ─────────────────────────────────────────────────────────────────


def enqueue_proposal(
    paths: AppPaths,
    *,
    target_file: str,
    serialized_content: str,
    summary: str,
    category: str,
    action: str = "upsert",
) -> bool:
    """Persist a failed proposal submission for later retry. Returns True
    on a successful enqueue write."""
    queue_dir = _queue_dir(paths, _PROPOSALS_KIND)
    queue_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "proposal",
        "queued_at": _utcnow(),
        "target_file": target_file,
        "serialized_content": serialized_content,
        "summary": summary,
        "category": category,
        "action": action,
    }
    queue_id = uuid.uuid4().hex
    out_path = queue_dir / f"{queue_id}.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(
            "Queued proposal for retry: %s (%s, %s)",
            target_file, category, action,
        )
        return True
    except OSError:
        logger.exception("Could not write outbound queue file %s", out_path)
        return False


def enqueue_export(
    paths: AppPaths,
    *,
    local_path: Path,
    agency: str,
    year: str,
    filename: str | None = None,
) -> bool:
    """Persist a failed export upload for later retry. ``local_path`` must
    still be on disk at retry time; if it's been deleted, drain logs and
    discards the queue entry."""
    queue_dir = _queue_dir(paths, _EXPORTS_KIND)
    queue_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(local_path.stem)
    out_path = queue_dir / f"{stem}-{uuid.uuid4().hex[:8]}.json"
    payload = {
        "type": "export",
        "queued_at": _utcnow(),
        "local_path": str(local_path),
        "agency": agency,
        "year": year,
        "filename": filename,
    }
    try:
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Queued export for retry: %s", local_path.name)
        return True
    except OSError:
        logger.exception("Could not write outbound queue file %s", out_path)
        return False


# ── Drain ───────────────────────────────────────────────────────────────────


def queue_depth(paths: AppPaths) -> dict[str, int]:
    """Return ``{"proposals": int, "exports": int}`` so the modal can show a
    pending count. Cheap to call — just a directory listing."""
    return {
        _PROPOSALS_KIND: _count_files(_queue_dir(paths, _PROPOSALS_KIND)),
        _EXPORTS_KIND: _count_files(_queue_dir(paths, _EXPORTS_KIND)),
    }


def _count_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for p in directory.glob("*.json") if p.is_file())


def drain_queue(paths: AppPaths) -> dict[str, Any]:
    """Walk the queue, retrying each entry. Success deletes the queue file;
    failure leaves it for the next drain. Returns counts the periodic loop
    surfaces in logs and the data_version bump path.

    Imports the cloud-touching helpers lazily so this module doesn't pull
    them at top-level (the import chain would otherwise loop through
    wiring → outbound_queue → wiring).
    """
    drained_proposals = _drain_proposals(paths)
    drained_exports = _drain_exports(paths)
    return {
        "proposals_retried": drained_proposals["retried"],
        "proposals_succeeded": drained_proposals["succeeded"],
        "exports_retried": drained_exports["retried"],
        "exports_succeeded": drained_exports["succeeded"],
    }


def _drain_proposals(paths: AppPaths) -> dict[str, int]:
    queue_dir = _queue_dir(paths, _PROPOSALS_KIND)
    if not queue_dir.exists():
        return {"retried": 0, "succeeded": 0}

    # Avoid circular import: wiring → outbound_queue → wiring
    from ..adapters.wiring import _submit_proposal_to_cloud

    retried = 0
    succeeded = 0
    for queue_path in sorted(queue_dir.glob("*.json")):
        if retried >= _MAX_DRAIN_PER_CYCLE:
            break
        payload = _load_queue_file(queue_path)
        if payload is None:
            continue
        retried += 1
        result = _submit_proposal_to_cloud(
            target_file=payload.get("target_file", ""),
            serialized_content=payload.get("serialized_content", ""),
            summary=payload.get("summary", ""),
            category=payload.get("category", "advanced"),
            action=payload.get("action", "upsert"),
        )
        if result.get("proposed"):
            succeeded += 1
            _safe_unlink(queue_path)
            logger.info("Drained queued proposal: %s", payload.get("target_file"))
        # Else: leave file in place for next drain.
    return {"retried": retried, "succeeded": succeeded}


def _drain_exports(paths: AppPaths) -> dict[str, int]:
    queue_dir = _queue_dir(paths, _EXPORTS_KIND)
    if not queue_dir.exists():
        return {"retried": 0, "succeeded": 0}

    from .exports_upload_service import upload_export

    retried = 0
    succeeded = 0
    for queue_path in sorted(queue_dir.glob("*.json")):
        if retried >= _MAX_DRAIN_PER_CYCLE:
            break
        payload = _load_queue_file(queue_path)
        if payload is None:
            continue
        retried += 1
        local_path = Path(payload.get("local_path", ""))
        if not local_path.exists():
            # The user moved or deleted the source file. No point holding
            # the queue entry forever — drop it.
            logger.warning(
                "Discarding stale export queue entry (local file gone): %s",
                local_path,
            )
            _safe_unlink(queue_path)
            continue
        ok = upload_export(
            local_path,
            agency=payload.get("agency", ""),
            year=payload.get("year", ""),
            filename=payload.get("filename"),
        )
        if ok:
            succeeded += 1
            _safe_unlink(queue_path)
            logger.info("Drained queued export: %s", local_path.name)
    return {"retried": retried, "succeeded": succeeded}


def _load_queue_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Discarding malformed queue file %s", path)
        _safe_unlink(path)
        return None
    if not isinstance(data, dict):
        logger.warning("Discarding non-dict queue file %s", path)
        _safe_unlink(path)
        return None
    return data


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        logger.exception("Could not remove queue file %s", path)
