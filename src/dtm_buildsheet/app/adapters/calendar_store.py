"""Calendar document storage with optimistic revision checks.

One Calendar document makes a replan atomic across all teams. It lives outside
ordinary settings sync so a background mirror cannot replace a newer plan.
"""
from __future__ import annotations

import hashlib
import json
import threading

from ...storage.local import LocalStorageProvider
from ...domain.calendar_planning import default_calendar_settings

_LOCK = threading.RLock()
SHARED_PATH = "Settings/calendar_plan.json"


class CalendarConflictError(ValueError):
    pass


class CalendarStore:
    def __init__(self, paths, *, cloud_storage=None):
        self.path = paths.workspace_dir / "calendar" / "plan.json"
        self.cloud_storage = cloud_storage

    def read(self) -> tuple[dict, str]:
        if self.cloud_storage is not None:
            try:
                content, revision = self.cloud_storage.read_versioned_text(SHARED_PATH)
            except FileNotFoundError:
                return self._empty(), ""
        else:
            with _LOCK:
                if not self.path.exists():
                    return self._empty(), ""
                content = self.path.read_text("utf-8")
                revision = hashlib.sha256(content.encode()).hexdigest()
        data = json.loads(content)
        if not isinstance(data, dict) or data.get("schema_version") not in (1, 2):
            raise ValueError("Unsupported saved Calendar version")
        return data, revision

    def write(self, data: dict, expected: str) -> str:
        content = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if self.cloud_storage is not None:
            return self.cloud_storage.write_versioned_text(SHARED_PATH, content, expected)
        with _LOCK:
            _, revision = self.read()
            if revision != expected:
                raise CalendarConflictError("Calendar changed on another screen. Refresh and try again.")
            # A retained snapshot for every accepted edit makes team names and
            # estimate changes recoverable without overwriting earlier history.
            if self.path.exists():
                history = self.path.parent / "history" / f"{revision}.json"
                LocalStorageProvider().write_text(str(history), self.path.read_text("utf-8"))
            LocalStorageProvider().write_text(str(self.path), content)
            return hashlib.sha256(content.encode()).hexdigest()

    def current_revision(self) -> str:
        if self.cloud_storage is not None:
            try:
                return self.cloud_storage.read_revision(SHARED_PATH)
            except FileNotFoundError:
                return ''
        return self.read()[1]

    @staticmethod
    def _empty():
        return {"schema_version": 2, "settings": default_calendar_settings(), "jobs": {}, "start_date": ""}
