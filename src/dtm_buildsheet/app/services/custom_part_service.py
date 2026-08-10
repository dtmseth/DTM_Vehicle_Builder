"""Local, reusable history for one-off billable custom parts.

These entries are deliberately *not* products in ``parts_db.json`` and are
never synchronized to QuickBooks inventory.  A selected custom part is stored
with the draft (and therefore travels with its normal shared draft record);
this small local history only makes it convenient to reuse the information in
a later build on the same app installation.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone

from ...paths import AppPaths
from ...storage.local import LocalStorageProvider


_FILENAME = "custom_parts.json"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(paths: AppPaths):
    return paths.workspace_dir / _FILENAME


def _load(paths: AppPaths) -> list[dict]:
    try:
        doc = json.loads(LocalStorageProvider().read_text(str(_path(paths))))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    entries = doc.get("parts") if isinstance(doc, dict) else None
    return [entry for entry in entries or [] if isinstance(entry, dict)]


def list_custom_parts(paths: AppPaths, *, limit: int = 12) -> list[dict]:
    """Return recently used one-off parts, newest first.

    Bad historical entries are skipped rather than breaking the picker.
    """
    with _LOCK:
        entries = []
        for entry in _load(paths):
            sku = str(entry.get("sku", "")).strip()
            description = str(entry.get("description", "")).strip()
            try:
                unit_price = float(entry.get("unit_price"))
            except (TypeError, ValueError):
                continue
            if not sku or not description or not math.isfinite(unit_price) or unit_price < 0:
                continue
            entries.append({
                "sku": sku,
                "description": description,
                "unit_price": unit_price,
                "last_used_at": str(entry.get("last_used_at", "")),
            })
        entries.sort(key=lambda entry: entry["last_used_at"], reverse=True)
        return entries[:max(0, limit)]


def remember_custom_part(paths: AppPaths, *, sku: str, description: str, unit_price: float) -> dict:
    """Upsert a local reuse entry after the authoritative draft has saved."""
    with _LOCK:
        entries = _load(paths)
        now = _now()
        key = sku.casefold()
        saved: dict | None = None
        cleaned: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            existing_sku = str(entry.get("sku", "")).strip()
            if existing_sku.casefold() == key:
                if saved is None:
                    saved = {
                        "sku": sku,
                        "description": description,
                        "unit_price": unit_price,
                        "created_at": str(entry.get("created_at", "")) or now,
                        "last_used_at": now,
                    }
                    cleaned.append(saved)
                # Collapse accidental historical duplicates.
                continue
            cleaned.append(entry)
        if saved is None:
            saved = {
                "sku": sku,
                "description": description,
                "unit_price": unit_price,
                "created_at": now,
                "last_used_at": now,
            }
            cleaned.append(saved)
        LocalStorageProvider().write_text(
            str(_path(paths)),
            json.dumps({"schema_version": 1, "parts": cleaned}, indent=2) + "\n",
        )
        return dict(saved)
