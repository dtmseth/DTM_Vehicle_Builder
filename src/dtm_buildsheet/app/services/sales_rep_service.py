from __future__ import annotations

import difflib
import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ...domain.sales_rep_models import SalesRepRecord
from ...paths import AppPaths
from ...storage.local import LocalStorageProvider

_log = logging.getLogger(__name__)


def _reps_path(paths: AppPaths) -> Path:
    return paths.workspace_dir / "sales_reps.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_reps(paths: AppPaths) -> list[SalesRepRecord]:
    p = _reps_path(paths)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
        return [
            SalesRepRecord(
                rep_id=str(rec.get("rep_id", "")),
                name=str(rec.get("name", "")),
                phone=str(rec.get("phone", "")),
                email=str(rec.get("email", "")),
                created_at=str(rec.get("created_at", "")),
                updated_at=str(rec.get("updated_at", "")),
            )
            for rec in data.get("sales_reps", [])
        ]
    except Exception:
        _log.exception("Unexpected error loading sales reps from %s", p)
        return []


def _save_reps(records: list[SalesRepRecord], paths: AppPaths) -> None:
    p = _reps_path(paths)
    LocalStorageProvider().write_text(
        str(p),
        json.dumps({"schema_version": 1, "sales_reps": [asdict(r) for r in records]}, indent=2) + "\n",
    )


def handle_list_reps(paths: AppPaths) -> dict:
    return {"ok": True, "sales_reps": [asdict(r) for r in load_reps(paths)]}


def handle_search_reps(query: str, paths: AppPaths) -> dict:
    query = query.strip()
    if not query:
        return {"ok": True, "matches": []}
    records = load_reps(paths)
    if not records:
        return {"ok": True, "matches": []}

    norm_q = query.lower()
    names_lower = [r.name.lower() for r in records]

    seen: set[str] = set()
    matches: list[dict] = []

    for i, nl in enumerate(names_lower):
        if norm_q in nl and records[i].rep_id not in seen:
            seen.add(records[i].rep_id)
            matches.append({"rep_id": records[i].rep_id, "name": records[i].name})

    if len(matches) < 8:
        close = difflib.get_close_matches(norm_q, names_lower, n=8, cutoff=0.5)
        for cn in close:
            for i, nl in enumerate(names_lower):
                if nl == cn and records[i].rep_id not in seen:
                    seen.add(records[i].rep_id)
                    matches.append({"rep_id": records[i].rep_id, "name": records[i].name})
                    break

    return {"ok": True, "matches": matches[:8]}


def handle_save_rep(body: dict, paths: AppPaths) -> dict:
    try:
        records = load_reps(paths)
        rep_id = str(body.get("rep_id", "")).strip()
        name = str(body.get("name", "")).strip()
        phone = str(body.get("phone", "")).strip()
        email = str(body.get("email", "")).strip()
        if not name:
            return {"ok": False, "error": "Name is required"}
        if not phone:
            return {"ok": False, "error": "Phone is required"}
        if not email:
            return {"ok": False, "error": "Email is required"}
        now = _utcnow()
        existing = next((r for r in records if r.rep_id == rep_id), None)
        if existing:
            existing.name = name
            existing.phone = phone
            existing.email = email
            existing.updated_at = now
            record = existing
        else:
            record = SalesRepRecord(
                rep_id=rep_id or str(uuid.uuid4()),
                name=name,
                phone=phone,
                email=email,
                created_at=now,
                updated_at=now,
            )
            records.append(record)
        _save_reps(records, paths)
        return {"ok": True, "rep": asdict(record)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_delete_rep(rep_id: str, paths: AppPaths) -> dict:
    try:
        records = load_reps(paths)
        before = len(records)
        records = [r for r in records if r.rep_id != rep_id]
        if len(records) == before:
            return {"ok": False, "error": f"Rep not found: {rep_id}"}
        _save_reps(records, paths)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
