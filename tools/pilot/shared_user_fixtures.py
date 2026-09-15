"""Synthetic Stage 2 adapters. Not in the wheel or container build context."""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from pathlib import Path

from dtm_buildsheet.app.hosted.auth import Denied, digest
from dtm_buildsheet.app.hosted.metadata import Conflict, Versioned, scan_bounds
from dtm_buildsheet.app.request_context import hosted_process


class SqliteProofStore:
    """Local durability/CAS proof only; never a production storage fallback."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        if hosted_process() or not any(self.path.is_relative_to(root.resolve()) for root in (
            Path(tempfile.gettempdir()), Path("/tmp"),
        )):
            raise ValueError("Synthetic store requires an undeployed temporary directory")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (p TEXT, k TEXT, v TEXT, rev INTEGER, PRIMARY KEY(p,k))")

    def read(self, partition, key):
        with sqlite3.connect(self.path, timeout=5) as db:
            row = db.execute("SELECT v,rev FROM metadata WHERE p=? AND k=?", (partition, key)).fetchone()
        return Versioned(json.loads(row[0]), str(row[1])) if row else None

    def write(self, partition, key, value, *, expected):
        payload = json.dumps(value, allow_nan=False)
        if len(payload.encode("utf-16-le")) > 60000:
            raise ValueError("Metadata entity capacity exceeded")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT rev FROM metadata WHERE p=? AND k=?", (partition, key)).fetchone()
            actual = str(row[0]) if row else None
            if actual != expected or expected == "*":
                raise Conflict("Metadata changed")
            revision = int(actual or "0") + 1
            if row:
                db.execute("UPDATE metadata SET v=?,rev=? WHERE p=? AND k=?", (payload, revision, partition, key))
            else:
                db.execute("INSERT INTO metadata VALUES (?,?,?,?)", (partition, key, payload, revision))
        return str(revision)

    def scan(self, partition, prefix, *, after="", limit=100):
        upper = scan_bounds(prefix, after, limit)
        with sqlite3.connect(self.path, timeout=5) as db:
            rows = db.execute("SELECT k,v,rev FROM metadata WHERE p=? AND k>=? AND k<? AND k>? ORDER BY k LIMIT ?",
                              (partition, prefix, upper, after, limit)).fetchall()
        return [(key, Versioned(json.loads(value), str(rev))) for key, value, rev in rows]

    def delete(self, partition, key, *, expected):
        if not expected or expected == "*":
            raise ValueError("An exact ETag is required")
        with sqlite3.connect(self.path, timeout=5) as db:
            cursor = db.execute("DELETE FROM metadata WHERE p=? AND k=? AND rev=?", (partition, key, expected))
            if cursor.rowcount != 1:
                raise Conflict("Metadata changed")


class SyntheticDocuments:
    """One notes-only synthetic record, with explicit per-record staff ACLs."""
    def __init__(self, store):
        self.store = store

    def seed(self, tenant, resource, users):
        return self.store.write(tenant, "document-" + resource, {
            "notes": "Synthetic shared build", "members": list(users), "updated_by": "fixture",
        }, expected=None)

    def _read(self, principal, resource):
        if not isinstance(resource, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", resource):
            raise Denied(404, "document_not_found")
        row = self.store.read(principal.tenant, "document-" + resource)
        if row is None or principal.user.user_id not in row.value["members"]:
            raise Denied(404, "document_not_found")
        return row

    def read(self, principal, resource):
        row = self._read(principal, resource)
        return Versioned({"notes": row.value["notes"], "updated_by": row.value["updated_by"]}, row.etag)

    def write(self, principal, resource, value, expected):
        row = self._read(principal, resource)
        if set(value) != {"notes"} or not isinstance(value["notes"], str) or len(value["notes"]) > 2000:
            raise ValueError("Synthetic notes required")
        if expected != row.etag:
            raise Conflict("Document changed")
        return self.store.write(principal.tenant, "document-" + resource,
                                {**row.value, **value, "updated_by": principal.user.user_id}, expected=expected)

    def review(self, principal, kind, resource, expected):
        row = self._read(principal, resource)
        if row.etag != expected:
            raise Conflict("Review is stale")
        return digest(json.dumps(row.value, sort_keys=True))
