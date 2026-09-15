"""Fresh-process pilot boundaries plus desktop export compatibility."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


def child(code, *args):
    env = {key: value for key, value in os.environ.items()
           if key not in {"DTM_LOCAL_PILOT", "DTM_WORKSPACE_DIR", "DTM_ALLOW_CLOUD_IN_TESTS"}}
    return subprocess.run([sys.executable, "-c", code, *map(str, args)],
                          env=env, capture_output=True, text=True, timeout=30)


def test_paths_selected_before_import_and_reject_nonempty(tmp_path):
    result = child('''
import sys
from pathlib import Path
from dtm_buildsheet.headless import prepare_environment
assert "dtm_buildsheet.paths" not in sys.modules
workspace = prepare_environment(Path(sys.argv[1]))
from dtm_buildsheet.paths import AppPaths, WORKSPACE_DIR
p = AppPaths()
assert WORKSPACE_DIR == workspace
for name in ("workspace_dir", "workspace_config_dir", "workspace_assets_dir",
             "workspace_presets_dir", "workspace_output_dir", "workspace_projects_dir"):
    assert getattr(p, name).is_relative_to(workspace), name
''', tmp_path / "pilot")
    assert result.returncode == 0, result.stderr
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("unchanged")
    result = child('''
import sys
from pathlib import Path
from dtm_buildsheet.headless import prepare_environment
prepare_environment(Path(sys.argv[1]))
''', occupied)
    assert result.returncode != 0 and "Refusing a nonempty workspace" in result.stderr
    assert (occupied / "keep").read_text() == "unchanged"


def test_desktop_paths_still_use_source_resources():
    result = child('''
from dtm_buildsheet.paths import AppPaths, DEFAULT_CONFIG_DIR, ASSETS_DIR, BUNDLED_PRESETS_DIR
p = AppPaths()
assert p.workspace_config_dir == DEFAULT_CONFIG_DIR
assert p.workspace_assets_dir == ASSETS_DIR
assert p.workspace_presets_dir == BUNDLED_PRESETS_DIR
''')
    assert result.returncode == 0, result.stderr


def test_real_generation_does_not_reseed_desktop_data(tmp_path):
    result = child('''
import sys, json
from pathlib import Path
from dtm_buildsheet.headless import prepare_environment, install_egress_guard
workspace = prepare_environment(Path(sys.argv[1]))
violations = install_egress_guard()
from dtm_buildsheet.paths import AppPaths, ensure_workspace
from dtm_buildsheet.pilot_fixtures import initialize_workspace
paths = AppPaths()
initialize_workspace(paths, seed=True)
from dtm_buildsheet.config.store import load_config
assert load_config("parts_db.json", paths)["part_types"]
from dtm_buildsheet.app.services.draft_service import handle_generate_from_draft
result = handle_generate_from_draft({"draft_id": "pilot-typical-draft", "project_id": "pilot-typical"}, paths)
assert result["ok"], result
assert result["placements_count"] > 0, result
assert not any("Unmapped part" in message for message in result["all_warnings"]), result
for name in ("cloud_config.json", "agencies.json", "sales_reps.json", "config/.settings_etags.json"):
    assert not (workspace / name).exists(), name
assert not violations, violations
draft = paths.workspace_drafts_dir / "pilot-typical-draft.json"
before = draft.read_bytes()
initialize_workspace(paths, seed=True)
ensure_workspace()
assert draft.read_bytes() == before
''', tmp_path / "pilot")
    assert result.returncode == 0, result.stderr


def test_egress_and_credentials_fail_before_any_provider_access(tmp_path):
    result = child('''
import sys, socket, subprocess
from pathlib import Path
from dtm_buildsheet.headless import prepare_environment, install_egress_guard
prepare_environment(Path(sys.argv[1]))
violations = install_egress_guard()
for action in (lambda: socket.getaddrinfo("graph.microsoft.com", 443),
               lambda: socket.socket().connect(("1.1.1.1", 443)),
               lambda: subprocess.run(["open", "/tmp"])):
    try: action()
    except PermissionError: pass
    else: raise AssertionError("egress/native action allowed")
from dtm_buildsheet.app.adapters.quickbooks.credential_store import QuickBooksCredentialStore
try: QuickBooksCredentialStore()
except RuntimeError: pass
else: raise AssertionError("desktop credentials available")
assert len(violations) == 3
''', tmp_path / "pilot")
    assert result.returncode == 0, result.stderr


@pytest.fixture
def pilot_http(tmp_path):
    from dtm_buildsheet.headless import make_handler
    from dtm_buildsheet.paths import AppPaths
    from dtm_buildsheet.app.server import create_http_server
    output = tmp_path / "output"
    output.mkdir()
    paths = AppPaths(workspace_dir=tmp_path, workspace_output_dir=output)
    server = create_http_server(paths, port=0, handler_class=make_handler([]))
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", output
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()


def test_download_is_bounded_and_does_not_accept_paths(pilot_http, tmp_path):
    url, output = pilot_http
    (output / "fixture.pdf").write_bytes(b"%PDF-synthetic")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private")
    (output / "escape.pdf").symlink_to(outside)
    with urlopen(url + "/api/pilot/artifacts") as response:
        files = json.load(response)["artifacts"]
    assert [file["name"] for file in files] == ["fixture.pdf"]
    with urlopen(url + files[0]["url"]) as response:
        assert response.read() == b"%PDF-synthetic"
        assert response.headers["Content-Disposition"].startswith("attachment;")
    with pytest.raises(HTTPError) as exc:
        urlopen(url + "/api/pilot/download/outside.pdf")
    assert exc.value.code == 404


def test_native_and_provider_routes_are_inert(pilot_http):
    url, _ = pilot_http
    for path in ("/open", "/api/cloud/signin", "/api/cloud/sync", "/api/quickbooks/connect",
                 "/api/build/show-folder", "/api/template/pick-folder", "/api/update/install"):
        with urlopen(Request(url + path, data=b"{}", headers={"Content-Type": "application/json"})) as response:
            assert json.load(response)["ok"] is False
    with pytest.raises(HTTPError) as exc:
        urlopen(Request(url + "/api/pilot/artifacts", headers={"Origin": "https://external.example"}))
    assert exc.value.code == 403


def test_pilot_export_rejects_arbitrary_paths_and_native_fallback(tmp_path, monkeypatch):
    from dtm_buildsheet.app.services import export_service
    from dtm_buildsheet.paths import AppPaths
    monkeypatch.setenv("DTM_LOCAL_PILOT", "1")
    paths = AppPaths(workspace_output_dir=tmp_path / "output")
    outside = tmp_path / "private.pptx"
    outside.write_bytes(b"synthetic")
    assert "Access denied" in export_service.export_to_pdf({"output_path": str(outside)}, paths)["error"]
    paths.workspace_output_dir.mkdir()
    inside = paths.workspace_output_dir / "test.pptx"
    inside.write_bytes(b"synthetic")
    monkeypatch.setattr(export_service, "_find_soffice", lambda: None)
    monkeypatch.setattr(export_service, "_export_via_applescript", lambda *_: pytest.fail("native fallback"))
    assert "native fallback is disabled" in export_service.export_to_pdf({"output_path": str(inside)}, paths)["error"]


def test_libreoffice_conversions_use_distinct_disposable_profiles(tmp_path, monkeypatch):
    from dtm_buildsheet.app.services import export_service
    from dtm_buildsheet.paths import AppPaths
    from urllib.parse import unquote, urlparse
    source = tmp_path / "build.pptx"
    source.write_bytes(b"synthetic")
    profiles = []

    def convert(command, **kwargs):
        profile = Path(unquote(urlparse(command[1].split("=", 1)[1]).path))
        assert profile.is_dir()
        profiles.append(profile)
        source.with_suffix(".pdf").write_bytes(b"%PDF")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(export_service, "_find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(export_service.subprocess, "run", convert)
    monkeypatch.setattr(export_service, "_finish_pdf_export", lambda result, *_: result)
    for _ in range(2):
        assert export_service.export_to_pdf({"output_path": str(source)}, AppPaths(workspace_output_dir=tmp_path))["ok"]
    assert profiles[0] != profiles[1]
    assert all(not profile.exists() for profile in profiles)
