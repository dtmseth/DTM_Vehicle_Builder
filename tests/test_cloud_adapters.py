from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dtm_buildsheet.app.adapters.cloud.config import (
    CloudConfig,
    CloudConfigMissing,
    load_cloud_config_from_env,
)
from dtm_buildsheet.app.adapters.cloud.sharepoint_graph_provider import (
    SMALL_UPLOAD_LIMIT_BYTES,
    SharePointGraphProvider,
    SharePointRequestError,
)
from dtm_buildsheet.app.adapters.cloud.graph_drive_gateway import (
    GraphDriveError,
    GraphDriveGateway,
)
from dtm_buildsheet.app.adapters.wiring import (
    CLOUD_ENV_FLAG,
    build_local_bundle,
    get_active_bundle,
    set_active_bundle,
)
from dtm_buildsheet.app.services.shared_settings_service import (
    SharedSettingsService,
    SyncReport,
)
from dtm_buildsheet.storage.base import StorageProvider


# ── Test fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def cloud_config() -> CloudConfig:
    return CloudConfig(
        tenant_id="tenant-id-xyz",
        client_id="client-id-xyz",
        sharepoint_site_id="site-id-xyz",
        sharepoint_drive_id="drive-id-xyz",
    )


def _mock_response(status_code: int = 200, *, content: bytes = b"", json: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json or {}
    if status_code >= 400:
        from requests import HTTPError

        err = HTTPError(f"{status_code}")
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_graph_drive_gateway_get_item_uses_durable_id_and_handles_missing():
    session = MagicMock()
    session.get.side_effect = [
        _mock_response(200, json={"id": "item/id", "name": "Vehicle"}),
        _mock_response(404),
    ]
    gateway = GraphDriveGateway(token="TOK", drive_id="drive-1", session=session)

    assert gateway.get_item("item/id") == {"id": "item/id", "name": "Vehicle"}
    assert gateway.get_item("missing") is None
    assert session.get.call_args_list[0].args[0].endswith(
        "/drives/drive-1/items/item%2Fid"
    )


# ── CloudConfig env loading ──────────────────────────────────────────────────


def test_load_cloud_config_from_env_happy(monkeypatch):
    monkeypatch.setenv("DTM_AZURE_TENANT_ID", "t")
    monkeypatch.setenv("DTM_AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("DTM_SHAREPOINT_SITE_ID", "s")
    monkeypatch.setenv("DTM_SHAREPOINT_DRIVE_ID", "d")
    cfg = load_cloud_config_from_env()
    assert cfg.tenant_id == "t"
    assert cfg.authority == "https://login.microsoftonline.com/t"


def test_vehicle_folder_targets_require_explicit_cutover_flags(monkeypatch):
    monkeypatch.setenv("DTM_AZURE_TENANT_ID", "t")
    monkeypatch.setenv("DTM_AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("DTM_SHAREPOINT_SITE_ID", "s")
    monkeypatch.setenv("DTM_SHAREPOINT_DRIVE_ID", "d")
    monkeypatch.setenv("DTM_COMPANY_LIBRARY_NAME", "Company Files")
    monkeypatch.setenv("DTM_SHOP_LIBRARY_NAME", "Shop Documents")
    monkeypatch.setenv("DTM_COMPANY_VEHICLE_FOLDERS_ENABLED", "false")
    monkeypatch.setenv("DTM_SHOP_PUBLICATION_ENABLED", "false")

    disabled = load_cloud_config_from_env()
    assert disabled.company_target_configured is False
    assert disabled.shop_target_configured is False

    monkeypatch.setenv("DTM_COMPANY_VEHICLE_FOLDERS_ENABLED", "true")
    monkeypatch.setenv("DTM_SHOP_PUBLICATION_ENABLED", "1")
    enabled = load_cloud_config_from_env()
    assert enabled.company_target_configured is True
    assert enabled.shop_target_configured is True


def test_load_cloud_config_from_env_reports_all_missing(monkeypatch, tmp_path):
    for name in (
        "DTM_AZURE_TENANT_ID",
        "DTM_AZURE_CLIENT_ID",
        "DTM_SHAREPOINT_SITE_ID",
        "DTM_SHAREPOINT_DRIVE_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    # Redirect the on-disk fallback at a tmp path so a real
    # workspace/cloud_config.json doesn't accidentally satisfy the lookup.
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.cloud_config_path",
        lambda: tmp_path / "cloud_config.json",
    )
    with pytest.raises(CloudConfigMissing) as exc:
        load_cloud_config_from_env()
    msg = str(exc.value)
    for name in (
        "DTM_AZURE_TENANT_ID",
        "DTM_AZURE_CLIENT_ID",
        "DTM_SHAREPOINT_SITE_ID",
        "DTM_SHAREPOINT_DRIVE_ID",
    ):
        assert name in msg


def test_graph_drive_gateway_resolves_library_by_display_or_internal_name():
    session = MagicMock()
    session.get.return_value = _mock_response(200, json={"value": [
        {
            "id": "drive-1",
            "name": "Documents",
            "webUrl": "https://tenant.sharepoint.com/sites/DTM/Documents",
        },
        {"id": "drive-2", "name": "Shop Documents"},
    ]})

    drive_id = GraphDriveGateway.resolve_drive_id(
        token="TOK",
        site_id="site-id",
        library_names=("Renamed Company Files", "Documents"),
        session=session,
        timeout_seconds=7,
    )

    assert drive_id == "drive-1"
    assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer TOK"
    assert session.get.call_args.kwargs["timeout"] == 7
    assert GraphDriveGateway.resolve_drive_web_url(
        token="TOK",
        site_id="site-id",
        library_names=("Company Files", "Documents"),
        session=session,
    ) == "https://tenant.sharepoint.com/sites/DTM/Documents"


def test_graph_drive_gateway_downloads_exact_item_without_exposing_redirect_url():
    session = MagicMock()
    session.get.return_value = _mock_response(200, content=b"photo bytes")
    gateway = GraphDriveGateway(token="TOK", drive_id="drive-1", session=session)

    assert gateway.download_item("item-1", timeout_seconds=17) == b"photo bytes"
    assert session.get.call_args.args[0].endswith("/drives/drive-1/items/item-1/content")
    assert session.get.call_args.kwargs["timeout"] == 17

    temporary_url = "https://download.invalid/photo?tempauth=do-not-leak"
    failed = _mock_response(500)
    from requests import HTTPError
    failed.raise_for_status.side_effect = HTTPError(
        f"500 for url: {temporary_url}", response=failed,
    )
    session.get.return_value = failed
    with pytest.raises(GraphDriveError) as exc:
        gateway.download_item("item-1")
    assert "tempauth" not in str(exc.value)


def test_graph_drive_gateway_downloads_large_thumbnail_bytes():
    session = MagicMock()
    session.get.return_value = _mock_response(200, content=b"thumbnail bytes")
    gateway = GraphDriveGateway(token="TOK", drive_id="drive-1", session=session)

    assert gateway.download_thumbnail("item-1", timeout_seconds=9) == b"thumbnail bytes"
    assert session.get.call_args.args[0].endswith(
        "/drives/drive-1/items/item-1/thumbnails/0/large/content"
    )
    assert session.get.call_args.kwargs["allow_redirects"] is True
    assert session.get.call_args.kwargs["timeout"] == 9


def test_graph_drive_gateway_copies_folder_and_verifies_destination(monkeypatch):
    accepted = _mock_response(202)
    accepted.headers = {"Location": "https://graph.microsoft.com/monitor/copy-1"}
    progress = _mock_response(202, json={"status": "inProgress"})
    progress.headers = {"Retry-After": "0"}
    complete = _mock_response(200, json={"status": "completed"})
    complete.content = b"{}"
    destination = _mock_response(200, json={
        "id": "copied-folder",
        "name": "Completed Build Photos",
        "folder": {"childCount": 3},
    })
    session = MagicMock()
    session.post.return_value = accepted
    session.get.side_effect = [progress, complete, destination]
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.graph_drive_gateway.time.sleep",
        lambda _delay: None,
    )
    gateway = GraphDriveGateway(token="TOK", drive_id="drive-1", session=session)

    result = gateway.copy_item(
        "source-folder",
        parent_id="vehicle-folder",
        new_name="Completed Build Photos",
        destination_path="Shop Project Database/Agency/Year/Vehicle/Completed Build Photos",
    )

    assert result["id"] == "copied-folder"
    assert session.post.call_args.args[0].endswith(
        "/drives/drive-1/items/source-folder/copy"
    )
    assert session.post.call_args.kwargs["json"] == {
        "parentReference": {"driveId": "drive-1", "id": "vehicle-folder"},
        "name": "Completed Build Photos",
    }
    assert "headers" not in session.get.call_args_list[0].kwargs


def test_load_cloud_config_from_file_fallback(monkeypatch, tmp_path):
    """When env is unset, the JSON file fills in every field."""
    for name in (
        "DTM_AZURE_TENANT_ID",
        "DTM_AZURE_CLIENT_ID",
        "DTM_SHAREPOINT_SITE_ID",
        "DTM_SHAREPOINT_DRIVE_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    config_file = tmp_path / "cloud_config.json"
    config_file.write_text(
        '{"tenant_id":"t","client_id":"c","sharepoint_site_id":"s","sharepoint_drive_id":"d"}'
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.cloud_config_path",
        lambda: config_file,
    )
    cfg = load_cloud_config_from_env()
    assert cfg.tenant_id == "t"
    assert cfg.client_id == "c"
    assert cfg.sharepoint_site_id == "s"
    assert cfg.sharepoint_drive_id == "d"


def test_cloud_enabled_reads_file_when_env_unset(monkeypatch, tmp_path):
    from dtm_buildsheet.app.adapters.cloud.config import cloud_enabled

    monkeypatch.delenv("DTM_CLOUD", raising=False)
    config_file = tmp_path / "cloud_config.json"
    config_file.write_text('{"enabled": true}')
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.cloud_config_path",
        lambda: config_file,
    )
    assert cloud_enabled() is True

    config_file.write_text('{"enabled": false}')
    assert cloud_enabled() is False


# ── SharePointGraphProvider ──────────────────────────────────────────────────


def test_sharepoint_provider_is_a_storage_provider(cloud_config):
    session = MagicMock()
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "tkn", session=session
    )
    assert isinstance(provider, StorageProvider)


def test_read_bytes_hits_graph_content_endpoint(cloud_config):
    session = MagicMock()
    session.get.return_value = _mock_response(200, content=b"hello bytes")
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )

    assert provider.read_bytes("Settings/parts_db.json") == b"hello bytes"

    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    assert url.endswith("/Settings/parts_db.json:/content")
    assert "/sites/site-id-xyz/drives/drive-id-xyz/root:" in url
    headers = session.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer TOK"


def test_read_text_decodes_utf8(cloud_config):
    session = MagicMock()
    session.get.return_value = _mock_response(
        200, content="café".encode("utf-8")
    )
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    assert provider.read_text("notes.txt") == "café"


def test_read_bytes_404_raises_filenotfound(cloud_config):
    session = MagicMock()
    session.get.return_value = _mock_response(404)
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    with pytest.raises(FileNotFoundError):
        provider.read_bytes("Settings/missing.json")


def test_graph_failure_never_exposes_temporary_redirect_url(cloud_config):
    """Graph download errors may contain a signed redirect URL from requests."""
    temporary_url = "https://download.example.invalid/file?tempauth=should-not-leak"
    response = _mock_response(429)
    response.url = temporary_url
    from requests import HTTPError
    response.raise_for_status.side_effect = HTTPError(
        f"429 Client Error for url: {temporary_url}", response=response,
    )
    session = MagicMock()
    session.get.return_value = response
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session,
    )

    with pytest.raises(SharePointRequestError) as raised:
        provider.read_bytes("Drafts/build-1.json")

    assert "tempauth" not in str(raised.value)
    assert temporary_url not in str(raised.value)
    assert raised.value.__cause__ is None


def test_write_bytes_puts_octet_stream(cloud_config):
    session = MagicMock()
    session.put.return_value = _mock_response(201)
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    provider.write_bytes("Settings/foo.json", b"{}")
    session.put.assert_called_once()
    kwargs = session.put.call_args.kwargs
    assert kwargs["data"] == b"{}"
    assert kwargs["headers"]["Content-Type"] == "application/octet-stream"
    assert kwargs["headers"]["Authorization"] == "Bearer TOK"


def test_write_bytes_rejects_oversize(cloud_config):
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=MagicMock()
    )
    oversize = b"\x00" * (SMALL_UPLOAD_LIMIT_BYTES + 1)
    with pytest.raises(NotImplementedError):
        provider.write_bytes("Exports/big.pptx", oversize)


def test_delete_calls_delete(cloud_config):
    session = MagicMock()
    session.delete.return_value = _mock_response(204)
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    provider.delete("PendingChanges/proposal.json")
    session.delete.assert_called_once()
    url = session.delete.call_args.args[0]
    assert url.endswith("/PendingChanges/proposal.json")
    # No :/content suffix on the delete URL.
    assert ":/content" not in url


def test_delete_404_raises_filenotfound(cloud_config):
    session = MagicMock()
    session.delete.return_value = _mock_response(404)
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    with pytest.raises(FileNotFoundError):
        provider.delete("PendingChanges/gone.json")


def test_list_files_paginates_and_skips_folders(cloud_config):
    page1 = _mock_response(
        200,
        json={
            "value": [
                {"name": "a.json"},
                {"name": "subfolder", "folder": {"childCount": 0}},
                {"name": "b.json"},
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page",
        },
    )
    page2 = _mock_response(
        200,
        json={"value": [{"name": "c.json"}]},
    )
    session = MagicMock()
    session.get.side_effect = [page1, page2]
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )

    files = provider.list_files("Settings")
    assert files == ["Settings/a.json", "Settings/b.json", "Settings/c.json"]
    assert session.get.call_count == 2


def test_list_files_404_raises_filenotfound(cloud_config):
    session = MagicMock()
    session.get.return_value = _mock_response(404)
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    with pytest.raises(FileNotFoundError):
        provider.list_files("DoesNotExist")


def test_path_normalization_strips_leading_slash(cloud_config):
    session = MagicMock()
    session.get.return_value = _mock_response(200, content=b"ok")
    provider = SharePointGraphProvider(
        cloud_config, token_provider=lambda: "TOK", session=session
    )
    provider.read_bytes("/Settings/parts.json")
    url = session.get.call_args.args[0]
    # No double-slash or leading colon issues.
    assert "root:/Settings/parts.json:/content" in url


# ── SharedSettingsService ────────────────────────────────────────────────────


class _FakeRemote(StorageProvider):
    """Minimal in-memory StorageProvider for service-level tests."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = dict(files)
        self.read_count = 0

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self._files[path] = data.encode("utf-8")

    def read_bytes(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        self.read_count += 1
        return self._files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self._files[path] = data

    def delete(self, path: str) -> None:
        self._files.pop(path, None)

    def list_files(self, directory: str) -> list[str]:
        directory = directory.strip("/")
        prefix = f"{directory}/" if directory else ""
        return [p for p in self._files if p.startswith(prefix) and p != directory]


def test_shared_settings_sync_writes_files(tmp_path: Path):
    remote = _FakeRemote({
        "Settings/parts_library.json": b'{"manufacturers": []}',
        "Settings/build_rules.json": b'{"rules": []}',
    })
    service = SharedSettingsService(remote, cache_dir=tmp_path / "config")
    report = service.sync_all()

    assert report.ok
    assert sorted(report.updated) == ["build_rules.json", "parts_library.json"]
    assert not report.unchanged
    assert (tmp_path / "config" / "parts_library.json").read_bytes() == b'{"manufacturers": []}'
    assert (tmp_path / "config" / "build_rules.json").read_bytes() == b'{"rules": []}'


def test_shared_settings_sync_skips_unchanged(tmp_path: Path):
    remote = _FakeRemote({"Settings/foo.json": b"v1"})
    service = SharedSettingsService(remote, cache_dir=tmp_path / "config")
    service.sync_all()
    first_count = remote.read_count

    report = service.sync_all()
    assert report.unchanged == ["foo.json"]
    assert not report.updated
    # We still re-fetch to compare; that's expected for the simple sync.
    assert remote.read_count > first_count


def test_shared_settings_sync_handles_missing_remote_folder(tmp_path: Path):
    remote = _FakeRemote({})  # list_files returns []; folder absence is benign
    service = SharedSettingsService(remote, cache_dir=tmp_path / "config")
    report = service.sync_all()
    assert report.ok
    assert report.updated == []
    assert report.unchanged == []


# ── Wiring + feature flag ────────────────────────────────────────────────────


def _redirect_cloud_config_file_to_tmp(monkeypatch, tmp_path):
    """Point the on-disk cloud_config.json lookup at an empty tmp dir.

    Without this, a real ``workspace/cloud_config.json`` on the dev machine
    leaks into tests that intend to exercise the no-config path.
    """
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.cloud_config_path",
        lambda: tmp_path / "cloud_config.json",
    )


def test_cloud_flag_off_uses_local_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv(CLOUD_ENV_FLAG, raising=False)
    _redirect_cloud_config_file_to_tmp(monkeypatch, tmp_path)
    set_active_bundle(None)  # type: ignore[arg-type]
    try:
        from dtm_buildsheet.app.adapters.noop import LocalIdentityProvider

        bundle = get_active_bundle()
        assert isinstance(bundle.identity, LocalIdentityProvider)
    finally:
        set_active_bundle(build_local_bundle())


def test_cloud_flag_on_without_config_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv(CLOUD_ENV_FLAG, "1")
    for name in (
        "DTM_AZURE_TENANT_ID",
        "DTM_AZURE_CLIENT_ID",
        "DTM_SHAREPOINT_SITE_ID",
        "DTM_SHAREPOINT_DRIVE_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    _redirect_cloud_config_file_to_tmp(monkeypatch, tmp_path)
    set_active_bundle(None)  # type: ignore[arg-type]
    try:
        from dtm_buildsheet.app.adapters.noop import LocalIdentityProvider

        # Missing cloud env should not blow up the process — wiring logs and
        # falls back to local so the app still starts.
        bundle = get_active_bundle()
        assert isinstance(bundle.identity, LocalIdentityProvider)
    finally:
        set_active_bundle(build_local_bundle())
