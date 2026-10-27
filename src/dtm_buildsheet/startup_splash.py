"""Status bridge for the borderless Windows startup launcher."""

from __future__ import annotations

import os
import time
from pathlib import Path


_STATUS_ENV = "DTM_STARTUP_SPLASH_STATUS_FILE"
_READY_SIGNAL = "__DTM_READY__"


def startup_splash_active() -> bool:
    """Return whether this process was opened by the Windows launcher."""
    return _status_path() is not None


def _status_path() -> Path | None:
    raw = os.environ.get(_STATUS_ENV, "").strip()
    return Path(raw) if raw else None


def _write_status(message: str) -> bool:
    path = _status_path()
    if path is None:
        return False
    try:
        path.write_text(message, encoding="utf-8")
        return True
    except OSError:
        return False


def update_startup_status(message: str) -> None:
    """Update launcher text; remain a no-op outside a shortcut launch."""
    _write_status(message)


def close_startup_splash(window=None) -> None:
    """Dismiss the launcher, then return the real window to the foreground."""
    launcher_active = _write_status(_READY_SIGNAL)
    os.environ.pop(_STATUS_ENV, None)
    if launcher_active:
        # The launcher polls at 100 ms. Let its always-on-top window disappear
        # before pywebview activates the fully loaded application window.
        time.sleep(0.15)
    if window is not None:
        try:
            window.show()
        except Exception:
            pass
