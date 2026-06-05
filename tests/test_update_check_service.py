from __future__ import annotations

from pathlib import Path

import pytest

from dtm_buildsheet.app.services.update_check_service import (
    RELEASES_REMOTE_FOLDER,
    UpdateInfo,
    check_for_update,
    download_update,
    parse_release_filename,
    parse_semver,
)
from dtm_buildsheet.storage.base import StorageProvider


# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeRemote(StorageProvider):
    """In-memory StorageProvider for update-check tests."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self.files[path] = data.encode("utf-8")

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def delete(self, path: str) -> None:
        self.files.pop(path, None)

    def list_files(self, directory: str) -> list[str]:
        directory = directory.strip("/")
        prefix = f"{directory}/" if directory else ""
        return [p for p in self.files if p.startswith(prefix)]


# ── parse_semver ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3", (1, 2, 3)),
        ("0.0.1", (0, 0, 1)),
        ("10.20.30", (10, 20, 30)),
        ("1.2.3-rc1", (1, 2, 3)),
        ("1.2.3+build4", (1, 2, 3)),
        ("garbage", (0, 0, 0)),
        ("", (0, 0, 0)),
        ("1.2", (0, 0, 0)),
    ],
)
def test_parse_semver(raw, expected):
    assert parse_semver(raw) == expected


# ── parse_release_filename ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("DTM_Vehicle_Builder-1.2.3.dmg", ("mac", "1.2.3")),
        ("DTM_Vehicle_Builder-10.0.1.dmg", ("mac", "10.0.1")),
        ("DTM_Vehicle_Builder_Setup-1.2.3.exe", ("windows", "1.2.3")),
        ("DTM_Vehicle_Builder_Setup-2.0.0-rc1.exe", ("windows", "2.0.0-rc1")),
        # Reject things that aren't installers:
        ("README.md", None),
        ("latest.json", None),
        ("DTM_Vehicle_Builder.dmg", None),  # no version
        ("DTM_Vehicle_Builder-abc.dmg", None),  # version not numeric
        ("dtm_vehicle_builder-1.2.3.dmg", None),  # wrong case prefix
    ],
)
def test_parse_release_filename(filename, expected):
    assert parse_release_filename(filename) == expected


# ── check_for_update ─────────────────────────────────────────────────────────


@pytest.fixture
def releases() -> _FakeRemote:
    """Fixture with one of each platform at multiple versions."""
    return _FakeRemote(
        {
            f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder-1.2.0.dmg": b"old",
            f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder-1.3.0.dmg": b"mid",
            f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder-1.4.0.dmg": b"latest",
            f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder_Setup-1.4.0.exe": b"win",
            f"{RELEASES_REMOTE_FOLDER}/release-notes.md": b"notes",
        }
    )


def test_returns_highest_version_for_platform(releases):
    info = check_for_update(
        releases, current_version="1.2.2", platform="mac", dismissed_versions=[]
    )
    assert info is not None
    assert info.version == "1.4.0"
    assert info.platform == "mac"
    assert info.filename == "DTM_Vehicle_Builder-1.4.0.dmg"


def test_no_update_when_already_current(releases):
    assert (
        check_for_update(
            releases, current_version="1.4.0", platform="mac", dismissed_versions=[]
        )
        is None
    )


def test_no_update_when_newer_than_anything_on_remote(releases):
    assert (
        check_for_update(
            releases, current_version="2.0.0", platform="mac", dismissed_versions=[]
        )
        is None
    )


def test_filters_by_platform(releases):
    info = check_for_update(
        releases, current_version="1.0.0", platform="windows", dismissed_versions=[]
    )
    assert info is not None
    assert info.filename == "DTM_Vehicle_Builder_Setup-1.4.0.exe"


def test_skips_dismissed_versions(releases):
    info = check_for_update(
        releases,
        current_version="1.2.2",
        platform="mac",
        dismissed_versions=["1.4.0"],
    )
    assert info is not None
    assert info.version == "1.3.0"  # next highest non-dismissed


def test_returns_none_when_all_newer_are_dismissed(releases):
    assert (
        check_for_update(
            releases,
            current_version="1.2.2",
            platform="mac",
            dismissed_versions=["1.3.0", "1.4.0"],
        )
        is None
    )


def test_ignores_non_installer_files(releases):
    info = check_for_update(
        releases, current_version="1.2.2", platform="mac", dismissed_versions=[]
    )
    # The release-notes.md should never have been considered.
    assert info is not None
    assert info.filename.endswith(".dmg")


def test_unknown_platform_returns_none(releases):
    assert (
        check_for_update(
            releases, current_version="1.2.2", platform="unknown", dismissed_versions=[]
        )
        is None
    )


def test_missing_remote_folder_returns_none():
    empty = _FakeRemote({})
    assert (
        check_for_update(
            empty, current_version="1.2.2", platform="mac", dismissed_versions=[]
        )
        is None
    )


def test_storage_list_exception_returns_none():
    class Broken(_FakeRemote):
        def list_files(self, directory: str) -> list[str]:
            raise RuntimeError("network down")

    assert (
        check_for_update(
            Broken(), current_version="1.2.2", platform="mac", dismissed_versions=[]
        )
        is None
    )


# ── download_update ──────────────────────────────────────────────────────────


def _paths_with_workspace(tmp_path: Path):
    from dtm_buildsheet.paths import AppPaths
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return AppPaths(workspace_dir=workspace)


def test_queue_installer_for_next_launch_moves_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from dtm_buildsheet.app.services.update_check_service import (
        get_queued_installer,
        queue_installer_for_next_launch,
    )
    paths = _paths_with_workspace(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    installer = downloads / "DTM_Vehicle_Builder_Setup-2.2.4.exe"
    installer.write_bytes(b"INSTALLER")
    queued = queue_installer_for_next_launch(installer, paths)
    assert queued.exists() and queued.read_bytes() == b"INSTALLER"
    assert not installer.exists()  # moved, not copied
    assert get_queued_installer(paths) == queued


def test_queue_installer_replaces_older_queued(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from dtm_buildsheet.app.services.update_check_service import (
        queue_installer_for_next_launch,
    )
    paths = _paths_with_workspace(tmp_path)
    # Pre-existing older installer
    queue_dir = paths.workspace_dir / ".queued_installer"
    queue_dir.mkdir()
    older = queue_dir / "DTM_Vehicle_Builder_Setup-2.2.3.exe"
    older.write_bytes(b"OLDER")

    newer_src = tmp_path / "DTM_Vehicle_Builder_Setup-2.2.4.exe"
    newer_src.write_bytes(b"NEWER")
    queue_installer_for_next_launch(newer_src, paths)
    assert not older.exists()
    assert (queue_dir / "DTM_Vehicle_Builder_Setup-2.2.4.exe").read_bytes() == b"NEWER"


def test_get_pending_update_info_reports_version(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from dtm_buildsheet.app.services.update_check_service import (
        get_pending_update_info,
        queue_installer_for_next_launch,
    )
    paths = _paths_with_workspace(tmp_path)
    src = tmp_path / "DTM_Vehicle_Builder_Setup-2.3.0.exe"
    src.write_bytes(b"x")
    queue_installer_for_next_launch(src, paths)
    info = get_pending_update_info(paths)
    assert info == {"version": "2.3.0", "filename": "DTM_Vehicle_Builder_Setup-2.3.0.exe"}


def test_get_pending_update_info_returns_none_when_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from dtm_buildsheet.app.services.update_check_service import get_pending_update_info
    paths = _paths_with_workspace(tmp_path)
    assert get_pending_update_info(paths) is None


def test_download_pending_update_if_any_skips_already_queued(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from dtm_buildsheet.app.services.update_check_service import (
        download_pending_update_if_any,
        queue_installer_for_next_launch,
    )
    paths = _paths_with_workspace(tmp_path)
    # Queue 2.3.0 already
    src = tmp_path / "DTM_Vehicle_Builder_Setup-2.3.0.exe"
    src.write_bytes(b"x")
    queue_installer_for_next_launch(src, paths)
    # Remote also has 2.3.0
    remote = _FakeRemote(
        {f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder_Setup-2.3.0.exe": b"y"}
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.update_check_service.get_embedded_version",
        lambda: "2.2.0",
    )
    result = download_pending_update_if_any(remote, paths, dismissed_versions=[])
    assert result.get("already_queued") == "2.3.0"


def test_download_update_writes_installer_to_destination(tmp_path: Path):
    remote = _FakeRemote(
        {f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder-1.4.0.dmg": b"FAKE_DMG_BYTES"}
    )
    info = UpdateInfo(
        version="1.4.0",
        remote_path=f"{RELEASES_REMOTE_FOLDER}/DTM_Vehicle_Builder-1.4.0.dmg",
        filename="DTM_Vehicle_Builder-1.4.0.dmg",
        platform="mac",
    )
    local_path = download_update(remote, info, destination_dir=tmp_path)
    assert local_path == tmp_path / info.filename
    assert local_path.read_bytes() == b"FAKE_DMG_BYTES"
