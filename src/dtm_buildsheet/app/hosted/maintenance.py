"""Explicit operator functions; no HTTP routes, timers, provider calls or secrets.

Cleanup defaults to dry-run and one bounded page. Job snapshots/restores require
all writers stopped. Restore stays fenced pending provider reconciliation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from uuid import UUID

from .jobs import KINDS, TERMINAL
from .metadata import Conflict

MAX_BACKUP_BYTES = 16 * 1024 * 1024


def _tenant(value):
    if str(UUID(value)) != value:
        raise ValueError("Canonical tenant required")


def cleanup_page(store, artifacts, tenant, kind, *, after="", limit=100, apply=False, now=None):
    """Return counts/cursor, never row values. Advance the cursor even on skips.

    Artifact metadata retains a cleanup marker until its file is removed; a crash
    between steps is retryable on the next complete scan. Job keys are never scanned.
    """
    _tenant(tenant)
    if kind not in {"session", "artifact"}:
        raise ValueError("Only expiring sessions/artifacts can be cleaned")
    now = int(time.time() if now is None else now)
    rows = store.scan(tenant, kind + "-", after=after, limit=limit)
    result = dict(scanned=len(rows), eligible=0, deleted=0, conflicts=0, invalid=0,
                  file_errors=0, after=rows[-1][0] if rows else "", apply=apply)
    for key, row in rows:
        value = row.value
        size = 64 if kind == "session" else 48
        if (not re.fullmatch(kind + rf"-[0-9a-f]{{{size}}}", key)
                or not isinstance(value, dict) or type(value.get("expires")) is not int
                or not str(value.get("owner", "")).startswith(tenant + ":")
                or (kind == "artifact" and value.get("extension") not in {"pdf", "pptx"})):
            result["invalid"] += 1
            continue
        if value["expires"] > now:
            continue
        result["eligible"] += 1
        if not apply:
            continue
        try:
            expected = row.etag
            if kind == "artifact":
                expected = store.write(tenant, key, {**value, "cleanup_pending": True}, expected=expected)
                try:
                    artifacts.discard(key.removeprefix("artifact-"), value["extension"])
                except (OSError, ValueError):
                    result["file_errors"] += 1
                    continue
            store.delete(tenant, key, expected=expected)
            result["deleted"] += 1
        except Conflict:
            result["conflicts"] += 1
    return result


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _validate_job(job, tenant):
    fields = {"owner", "intent", "state", "created", "deadline", "step", "lease", "lease_until", "audit"}
    if not isinstance(job, dict) or set(job) != fields:
        raise ValueError("Invalid recovery job")
    owner = job["owner"]
    if not isinstance(owner, str) or not owner.startswith(tenant + ":"):
        raise ValueError("Wrong recovery owner")
    UUID(owner[len(tenant) + 1:])
    intent = job["intent"]
    if (not isinstance(intent, dict) or set(intent) != {"kind", "resource", "revision", "snapshot"}
            or intent["kind"] not in KINDS
            or any(not isinstance(v, str) or not 1 <= len(v) <= 160 for v in intent.values())
            or job["state"] not in TERMINAL | {"queued", "running"}
            or any(type(job[k]) is not int or job[k] < 0 for k in ("created", "deadline", "step", "lease_until"))
            or job["step"] > 64 or not isinstance(job["lease"], str) or len(job["lease"]) > 128
            or not isinstance(job["audit"], list) or len(job["audit"]) > 70):
        raise ValueError("Invalid recovery job")
    for event in job["audit"]:
        if (not isinstance(event, dict) or not {"event", "at"} <= event.keys()
                or not event.keys() <= {"event", "at", "step"}
                or event["event"] not in TERMINAL | {"queued", "running"}
                or type(event["at"]) is not int
                or ("step" in event and type(event["step"]) is not int)):
            raise ValueError("Invalid recovery audit")


def _validate_rows(rows, tenant):
    if not isinstance(rows, dict) or len(rows) > 2001:
        raise ValueError("Backup row limit exceeded")
    queue = rows.get("jobs", {"jobs": {}})
    if not isinstance(queue, dict) or set(queue) != {"jobs"} or not isinstance(queue["jobs"], dict):
        raise ValueError("Invalid recovery queue")
    if len(queue["jobs"]) > 4:
        raise ValueError("Recovery queue capacity exceeded")
    for key, job in queue["jobs"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid recovery key")
        _validate_job(job, tenant)
        if "job-" + key in rows and rows["job-" + key] != job:
            raise ValueError("Conflicting queue/archive")
    for key, job in rows.items():
        if key == "jobs":
            continue
        if not re.fullmatch(r"job-[0-9a-f]{64}", key):
            raise ValueError("Only job recovery rows are allowed")
        _validate_job(job, tenant)
        if job["state"] not in TERMINAL:
            raise ValueError("Archive must be terminal")


def snapshot_jobs(store, tenant, *, writers_stopped=False, now=None):
    """Logical job recovery snapshot; excludes sessions, files, credentials and records.

    A checksum detects damage, not malicious replacement. Protect the snapshot
    with separate storage permissions/encryption and an independently retained hash.
    """
    _tenant(tenant)
    if not writers_stopped:
        raise ValueError("Stop all metadata writers before snapshot")
    if store.read(tenant, "recovery") is not None:
        raise ValueError("Resolve existing recovery before taking a new snapshot")
    queue = store.read(tenant, "jobs")
    rows = {"jobs": queue.value} if queue else {}
    after = ""
    while True:
        page = store.scan(tenant, "job-", after=after, limit=100)
        if not page:
            break
        rows.update({key: row.value for key, row in page})
        if len(rows) > 2001 or len(_encoded(rows)) > MAX_BACKUP_BYTES:
            raise ValueError("Backup capacity exceeded; no partial snapshot")
        after = page[-1][0]
    _validate_rows(rows, tenant)
    payload = dict(version=1, tenant=tenant, created=int(time.time() if now is None else now), rows=rows)
    return {**payload, "sha256": hashlib.sha256(_encoded(payload)).hexdigest()}


def restore_jobs(store, snapshot, tenant, *, writers_stopped=False):
    """Create-only restore into an empty tenant partition, resumable after a crash.

    All restored active jobs become interrupted. A durable recovery fence denies
    ALL job enqueues/claims/steps, including keys absent from an older snapshot.
    Never automatically remove it: reconcile the backup gap against providers first.
    """
    _tenant(tenant)
    if not writers_stopped:
        raise ValueError("Stop all writers and isolate the destination before restore")
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "tenant", "created", "rows", "sha256"}:
        raise ValueError("Invalid snapshot")
    if len(_encoded(snapshot)) > MAX_BACKUP_BYTES:
        raise ValueError("Backup capacity exceeded")
    payload = {k: v for k, v in snapshot.items() if k != "sha256"}
    if (snapshot["version"] != 1 or snapshot["tenant"] != tenant or type(snapshot["created"]) is not int
            or hashlib.sha256(_encoded(payload)).hexdigest() != snapshot["sha256"]):
        raise ValueError("Snapshot integrity/tenant mismatch")
    rows = copy.deepcopy(snapshot["rows"])
    _validate_rows(rows, tenant)
    for job in rows.get("jobs", {"jobs": {}})["jobs"].values():
        if job["state"] not in TERMINAL:
            job.update(state="interrupted", lease="", lease_until=0, deadline=0)
            job["audit"].append({"event": "interrupted", "at": snapshot["created"], "step": job["step"]})
    marker = {"state": "reconciliation_required", "snapshot_sha256": snapshot["sha256"]}
    existing = store.read(tenant, "recovery")
    if existing is None:
        if store.scan(tenant, "", limit=1):
            raise Conflict("Restore requires an empty tenant partition")
        store.write(tenant, "recovery", marker, expected=None)
    elif existing.value != marker:
        raise Conflict("Another recovery is present")
    # Archive first; queue last. The fence survives any partial restore.
    for key in sorted(rows, key=lambda key: (key == "jobs", key)):
        existing = store.read(tenant, key)
        if existing is None:
            store.write(tenant, key, rows[key], expected=None)
        elif existing.value != rows[key]:
            raise Conflict("Recovery destination differs")
    return {"restored_rows": len(rows), "jobs_fenced": True, "sessions_restored": 0}
