"""Guard runtime resources required by the frozen desktop application."""

import os
from pathlib import Path
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


def test_windows_borderless_startup_launcher_is_built_and_used_by_shortcuts():
    build_script = (ROOT / "packaging" / "build_windows.ps1").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "packaging" / "windows" / "installer.iss").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "packaging" / "windows" / "startup_launcher.cs").read_text(
        encoding="utf-8"
    )
    server = (ROOT / "src" / "dtm_buildsheet" / "app" / "server.py").read_text(
        encoding="utf-8"
    )

    assert (ROOT / "packaging" / "icons" / "splash.png").is_file()
    assert "Build-StartupLauncher" in build_script
    assert 'Filename: "{app}\\{#MyLauncherExeName}"' in installer
    assert 'Filename: "{app}\\{#MyAppExeName}"' in installer
    assert "FormBorderStyle = FormBorderStyle.None" in launcher
    assert "ShowInTaskbar = false" in launcher
    assert 'EnvironmentVariables["DTM_STARTUP_SPLASH_STATUS_FILE"]' in launcher
    assert "window.events.loaded += _finish_startup_splash" in server
    assert "hidden=startup_splash_active()" in server


def test_startup_splash_updates_closes_and_refocuses_window(tmp_path, monkeypatch):
    from dtm_buildsheet import startup_splash

    calls = []
    fake_window = SimpleNamespace(show=lambda: calls.append(("show", None)))
    status_path = tmp_path / "startup.status"
    monkeypatch.setenv("DTM_STARTUP_SPLASH_STATUS_FILE", str(status_path))
    monkeypatch.setattr(
        startup_splash.time,
        "sleep",
        lambda seconds: calls.append(("sleep", seconds)),
    )

    assert startup_splash.startup_splash_active()
    startup_splash.update_startup_status("Opening DTM Vehicle Builder...")
    assert status_path.read_text(encoding="utf-8") == "Opening DTM Vehicle Builder..."
    startup_splash.close_startup_splash(fake_window)

    assert calls == [
        ("sleep", 0.15),
        ("show", None),
    ]
    assert status_path.read_text(encoding="utf-8") == "__DTM_READY__"
    assert "DTM_STARTUP_SPLASH_STATUS_FILE" not in os.environ
    assert not startup_splash.startup_splash_active()
