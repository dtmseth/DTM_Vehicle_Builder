"""Guard runtime resources required by the frozen desktop application."""

from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def test_windows_zoneinfo_fallback_is_declared_and_bundled():
    """Windows needs tzdata because it has no system IANA zoneinfo database."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    spec = (ROOT / "packaging" / "pyinstaller" / "DTM_VehicleBuilder.spec").read_text(
        encoding="utf-8"
    )

    assert any(dependency.startswith("tzdata") for dependency in dependencies)
    assert 'collect_data_files("tzdata")' in spec
    assert '"tzdata.zoneinfo"' in spec


def test_windows_bootloader_splash_is_bundled_and_runtime_controlled():
    spec = (ROOT / "packaging" / "pyinstaller" / "DTM_VehicleBuilder.spec").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "packaging" / "pyinstaller" / "launch_gui.py").read_text(
        encoding="utf-8"
    )
    server = (ROOT / "src" / "dtm_buildsheet" / "app" / "server.py").read_text(
        encoding="utf-8"
    )

    assert (ROOT / "packaging" / "icons" / "splash.png").is_file()
    assert 'if _sys.platform == "win32"' in spec
    assert "splash = Splash(" in spec
    assert 'center="active"' in spec
    assert 'update_startup_status("Loading DTM components...")' in launcher
    assert "window.events.loaded += _finish_startup_splash" in server


def test_startup_splash_updates_closes_and_refocuses_window(monkeypatch):
    from dtm_buildsheet import startup_splash

    calls = []
    fake_splash = SimpleNamespace(
        is_alive=lambda: True,
        update_text=lambda message: calls.append(("update", message)),
        close=lambda: calls.append(("close", None)),
    )
    fake_window = SimpleNamespace(show=lambda: calls.append(("show", None)))
    monkeypatch.setitem(sys.modules, "pyi_splash", fake_splash)

    startup_splash.update_startup_status("Opening DTM Vehicle Builder...")
    startup_splash.close_startup_splash(fake_window)

    assert calls == [
        ("update", "Opening DTM Vehicle Builder..."),
        ("close", None),
        ("show", None),
    ]
