"""Bounded durable queue with exact revisions, leases and stop-on-interruption.

Workers are invoked by a separate scheduler/command, never by HTTP requests.
An uncertain external write requires reconciliation/review, not lease-expiry replay.
"""
from __future__ import annotations

import secrets
import time

from ...domain.operations_policy import Capability, has_capability
from .auth import Denied, digest
from .metadata import Conflict


KINDS = {
    "export": Capability.PROJECTS_EDIT,
    "calendar-save": Capability.OPERATIONS_SCHEDULE_UPDATE,
    "acceptance-poll": Capability.OPERATIONS_QBO_OBSERVE,
}
TERMINAL = {"succeeded", "conflict", "interrupted", "failed", "denied"}


class Jobs:
    # Four active jobs × 64 bounded steps plus references fit a Table entity.
    # Terminal jobs move to create-only archive rows before queue removal.
    # Never delete an idempotency key silently.
    MAX_JOBS = 4

    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    def _change(self, tenant, fn):
        # Only pure metadata transitions retry CAS. Never execute providers here.
        for _ in range(8):
            self._available(tenant)
            row = self.store.read(tenant, "jobs")
            data = row.value if row else {"jobs": {}}
            result = fn(data["jobs"])
            try:
                self.store.write(tenant, "jobs", data, expected=row.etag if row else None)
                return result
            except Conflict:
                continue
        raise Conflict("Queue busy")

    def _available(self, tenant):
        if self.store.read(tenant, "recovery") is not None:
            raise Denied(503, "recovery_review_required")

    def enqueue(self, principal, *, kind, request_id, resource, revision, snapshot):
        self._available(principal.tenant)
        if kind not in KINDS or not has_capability(principal.user.roles, KINDS[kind]):
            raise Denied()
        # All values are opaque server-reviewed references, never filesystem paths
        # or provider credentials. Actual Calendar snapshot stays authoritative.
        if any(not isinstance(v, str) or not v or len(v) > 160
               for v in (request_id, resource, revision, snapshot)):
            raise ValueError("Invalid job reference")
        if principal.expires <= self.clock():
            raise Denied(401, "identity_expired")
        self.archive_terminal(principal.tenant)
        key = digest(principal.owner + ":" + request_id)
        intent = {"kind": kind, "resource": resource, "revision": revision, "snapshot": snapshot}
        now = int(self.clock())

        def change(jobs):
            # Read archive inside the CAS attempt: concurrent archival cannot
            # remove a key between this decision and an uncontended insertion.
            archived = self.store.read(principal.tenant, "job-" + key)
            existing = jobs.get(key) or (archived.value if archived else None)
            if existing:
                if existing["intent"] != intent:
                    raise Conflict("Idempotency key already has another intent")
                return key
            if len(jobs) >= self.MAX_JOBS:
                raise Denied(429, "queue_capacity")
            jobs[key] = {
                "owner": principal.owner, "intent": intent, "state": "queued",
                "created": now, "deadline": min(now + 900, principal.expires),
                "step": 0, "lease": "", "lease_until": 0,
                "audit": [{"event": "queued", "at": now}],
            }
            return key
        return self._change(principal.tenant, change)

    def read(self, principal, key):
        row = self.store.read(principal.tenant, "jobs")
        job = row.value["jobs"].get(key) if row else None
        if job is None:
            archived = self.store.read(principal.tenant, "job-" + key)
            job = archived.value if archived else None
        if job is None or job["owner"] != principal.owner:
            raise Denied(404, "job_not_found")
        return {k: job[k] for k in ("state", "created", "step", "intent", "audit")}

    def archive_terminal(self, tenant):
        """Copy before removal; a crash at either write retains the retry key.

        Archive rows are immutable and retained for the pilot's lifetime. A future
        retention policy must preserve idempotency tombstones, even if it trims
        older transition detail. No automatic deletion of audit data occurs here.
        """
        row = self.store.read(tenant, "jobs")
        if row is None:
            return
        for key, job in row.value["jobs"].items():
            if job["state"] not in TERMINAL:
                continue
            archived = self.store.read(tenant, "job-" + key)
            if archived is None:
                try:
                    self.store.write(tenant, "job-" + key, job, expected=None)
                except Conflict:
                    archived = self.store.read(tenant, "job-" + key)
                    if archived is None or archived.value != job:
                        raise Conflict("Archive differs from terminal job") from None
            elif archived.value != job:
                raise Conflict("Archive differs from terminal job")

            def remove(jobs):
                if key in jobs:
                    if jobs[key] != job:
                        raise Conflict("Job changed during archive")
                    del jobs[key]
            self._change(tenant, remove)

    @staticmethod
    def _event(job, state, now):
        job["state"] = state
        job["audit"].append({"event": state, "at": now, "step": job["step"]})

    def claim(self, tenant):
        now, lease = int(self.clock()), secrets.token_urlsafe(24)

        def change(jobs):
            for job in jobs.values():
                if job["state"] == "running" and job["lease_until"] <= now:
                    self._event(job, "interrupted", now)
                elif job["state"] == "queued" and job["deadline"] <= now:
                    self._event(job, "interrupted", now)
            # Globally one active lease per tenant; replicas still use exact CAS.
            if any(j["state"] == "running" for j in jobs.values()):
                return None
            for key, job in jobs.items():
                if job["state"] == "queued":
                    job.update(lease=lease, lease_until=min(now + 120, job["deadline"]))
                    self._event(job, "running", now)
                    return key, lease
            return None
        return self._change(tenant, change)

    def advance(self, tenant, key, lease, *, authorize, revision_matches, apply_step):
        """Execute at most one bounded step, then checkpoint with a fencing token.

        authorize(owner, kind) must recheck user assignment/revocation and resource
        ACL before *each* call. revision_matches(intent) covers the reviewed snapshot
        and each resource precondition. apply_step(job, event_id) must also enforce
        those preconditions at the provider write and be idempotent by event_id.
        Its True result means finished. Provider adapters are deliberately not wired
        in Stage 2. They must finish within the lease or renew through a future port.
        """
        self._available(tenant)
        row = self.store.read(tenant, "jobs")
        job = row.value["jobs"].get(key) if row else None
        self._lease(job, lease)
        if not authorize(job["owner"], job["intent"]["kind"]):
            state = "denied"
        elif not revision_matches(job["intent"]):
            state = "conflict"
        elif job["step"] >= 64:
            state = "failed"
        else:
            try:
                finished = apply_step(job, f"{key}-{job['step']}")
                state = "succeeded" if finished else "running"
            except Conflict:
                state = "conflict"
            except Exception:
                state = "failed"

        def change(jobs):
            current = jobs.get(key)
            self._lease(current, lease)
            if current["step"] != job["step"]:
                raise Conflict("Step already checkpointed")
            if state in {"running", "succeeded"}:
                current["step"] += 1
            current["lease_until"] = min(int(self.clock()) + 120, current["deadline"])
            self._event(current, state, int(self.clock()))
        self._change(tenant, change)
        return state

    def _lease(self, job, lease):
        if (not job or job["state"] != "running" or job["lease"] != lease
                or job["lease_until"] <= self.clock() or job["deadline"] <= self.clock()):
            raise Conflict("Lease expired or replaced; review/reconciliation required")
