"""Small optional bridge to PyInstaller's bootloader-level splash screen."""

from __future__ import annotations

from typing import Any


def _splash_module() -> Any | None:
    try:
        import pyi_splash  # type: ignore[import-not-found]
    except (ImportError, RuntimeError):
        return None
    try:
        if hasattr(pyi_splash, "is_alive") and not pyi_splash.is_alive():
            return None
    except Exception:
        return None
    return pyi_splash


def update_startup_status(message: str) -> None:
    """Update packaged startup text; remain a no-op in source launches."""
    splash = _splash_module()
    if splash is None:
        return
    try:
        splash.update_text(message)
    except Exception:
        # Startup must never fail because a purely presentational window did.
        return


def close_startup_splash(window=None) -> None:
    """Close the packaged splash, then return the real window to the front."""
    splash = _splash_module()
    if splash is not None:
        try:
            splash.close()
        except Exception:
            pass
    if window is not None:
        try:
            # PyInstaller documents a Windows focus edge case for onedir
            # splashes. pywebview's show() activates its native WinForms form.
            window.show()
        except Exception:
            pass
