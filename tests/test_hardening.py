"""Tests for Phase-1 hardening: path safety, atomic writes, config backup."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dtm_buildsheet.storage.safety import assert_within_root, validate_safe_id


# ── validate_safe_id ───────────────────────────────────────────────────────────

class TestValidateSafeId:
    def test_plain_uuid_accepted(self):
        v = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_safe_id(v) == v

    def test_simple_word_accepted(self):
        assert validate_safe_id("my-project") == "my-project"

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_safe_id("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_safe_id("   ")

    def test_forward_slash_rejected(self):
        with pytest.raises(ValueError, match="path separator"):
            validate_safe_id("foo/bar")

    def test_backslash_rejected(self):
        with pytest.raises(ValueError, match="path separator"):
            validate_safe_id("foo\\bar")

    def test_double_dot_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_safe_id("..")

    def test_single_dot_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_safe_id(".")

    def test_absolute_unix_path_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_safe_id("/etc/passwd")

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="path separator|forbidden"):
            validate_safe_id("foo\x00bar")

    def test_colon_rejected(self):
        with pytest.raises(ValueError, match="path separator|forbidden"):
            validate_safe_id("foo:bar")

    def test_windows_reserved_name_rejected(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_safe_id("CON")

    def test_windows_reserved_name_case_insensitive(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_safe_id("nul")

    def test_label_appears_in_error(self):
        with pytest.raises(ValueError, match="draft_id"):
            validate_safe_id("", label="draft_id")


# ── assert_within_root ─────────────────────────────────────────────────────────

class TestAssertWithinRoot:
    def test_direct_child_accepted(self, tmp_path):
        child = tmp_path / "file.json"
        result = assert_within_root(child, tmp_path)
        assert result == child.resolve()

    def test_nested_child_accepted(self, tmp_path):
        nested = tmp_path / "a" / "b" / "file.json"
        assert_within_root(nested, tmp_path)

    def test_sibling_dir_rejected(self, tmp_path):
        sibling = tmp_path.parent / "other"
        with pytest.raises(ValueError, match="outside"):
            assert_within_root(sibling, tmp_path)

    def test_traversal_sequence_rejected(self, tmp_path):
        traversal = tmp_path / ".." / "escape"
        with pytest.raises(ValueError, match="outside"):
            assert_within_root(traversal, tmp_path)

    def test_returns_resolved_path(self, tmp_path):
        sub = tmp_path / "sub"
        result = assert_within_root(sub, tmp_path)
        assert result == sub.resolve()


# ── LocalStorageProvider.write_bytes (atomic) ──────────────────────────────────

class TestWriteBytes:
    def test_write_creates_file(self, tmp_path):
        from dtm_buildsheet.storage.local import LocalStorageProvider
        dest = tmp_path / "out.bin"
        LocalStorageProvider().write_bytes(str(dest), b"\x00\x01\x02")
        assert dest.read_bytes() == b"\x00\x01\x02"

    def test_write_creates_parent_dirs(self, tmp_path):
        from dtm_buildsheet.storage.local import LocalStorageProvider
        dest = tmp_path / "a" / "b" / "out.bin"
        LocalStorageProvider().write_bytes(str(dest), b"hello")
        assert dest.exists()

    def test_write_overwrites_existing(self, tmp_path):
        from dtm_buildsheet.storage.local import LocalStorageProvider
        dest = tmp_path / "out.bin"
        dest.write_bytes(b"old")
        LocalStorageProvider().write_bytes(str(dest), b"new")
        assert dest.read_bytes() == b"new"

    def test_no_temp_file_left_on_success(self, tmp_path):
        from dtm_buildsheet.storage.local import LocalStorageProvider
        LocalStorageProvider().write_bytes(str(tmp_path / "f.bin"), b"data")
        assert len(list(tmp_path.iterdir())) == 1


# ── save_xlsx_bytes — basename enforcement ─────────────────────────────────────

class TestSaveXlsxBytes:
    def test_basename_used(self, tmp_path):
        """A filename with path components is reduced to its basename."""
        import base64
        from dtm_buildsheet.app.services.generation_service import save_xlsx_bytes
        from dtm_buildsheet.paths import AppPaths

        paths = AppPaths(
            workspace_input_dir=tmp_path / "input",
            workspace_output_dir=tmp_path / "output",
            workspace_config_dir=tmp_path / "config",
            workspace_assets_dir=tmp_path / "assets",
            workspace_drafts_dir=tmp_path / "drafts",
            workspace_dir=tmp_path,
        )
        (tmp_path / "input").mkdir()
        payload = base64.b64encode(b"PK fake xlsx").decode()
        body = {"data": payload, "filename": "../../evil.xlsx"}
        result = save_xlsx_bytes(body, paths)
        # Must land inside workspace_input_dir, not above it
        assert result.parent == paths.workspace_input_dir
        assert result.name == "evil.xlsx"

    def test_normal_filename_preserved(self, tmp_path):
        import base64
        from dtm_buildsheet.app.services.generation_service import save_xlsx_bytes
        from dtm_buildsheet.paths import AppPaths

        paths = AppPaths(
            workspace_input_dir=tmp_path / "input",
            workspace_output_dir=tmp_path / "output",
            workspace_config_dir=tmp_path / "config",
            workspace_assets_dir=tmp_path / "assets",
            workspace_drafts_dir=tmp_path / "drafts",
            workspace_dir=tmp_path,
        )
        (tmp_path / "input").mkdir()
        payload = base64.b64encode(b"PK fake xlsx").decode()
        body = {"data": payload, "filename": "myfile.xlsx"}
        result = save_xlsx_bytes(body, paths)
        assert result.name == "myfile.xlsx"
        assert result.parent == paths.workspace_input_dir


# ── Config backup / history ────────────────────────────────────────────────────

class TestConfigBackup:
    def _make_paths(self, tmp_path: Path):
        """Minimal AppPaths pointing into tmp_path."""
        from dtm_buildsheet.paths import AppPaths
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        return AppPaths(
            workspace_config_dir=cfg_dir,
            workspace_dir=tmp_path,
            workspace_input_dir=tmp_path / "input",
            workspace_output_dir=tmp_path / "output",
            workspace_assets_dir=tmp_path / "assets",
            workspace_drafts_dir=tmp_path / "drafts",
        )

    def test_backup_created_on_save(self, tmp_path):
        from dtm_buildsheet.config.store import save_config

        paths = self._make_paths(tmp_path)
        # Seed the config file with initial content
        cfg_file = paths.workspace_config_dir / "app_settings.json"
        cfg_file.write_text(json.dumps({"schema_version": 1, "template_save_dir": "", "output_save_dir": ""}), "utf-8")

        save_config("app_settings.json", {"template_save_dir": "", "output_save_dir": ""}, paths)

        history_dir = paths.workspace_config_dir / "history"
        backups = list(history_dir.glob("app_settings.json.*.bak"))
        assert len(backups) == 1

    def test_no_backup_when_file_missing(self, tmp_path):
        """save_config on a brand-new path must not error — no backup if file absent."""
        from dtm_buildsheet.config.store import save_config

        paths = self._make_paths(tmp_path)
        # Don't pre-create the file; save_config should create it without error
        save_config("app_settings.json", {"template_save_dir": "", "output_save_dir": ""}, paths)
        history_dir = paths.workspace_config_dir / "history"
        # Either directory doesn't exist or is empty
        assert not history_dir.exists() or not list(history_dir.glob("*.bak"))

    def test_backups_capped_at_20(self, tmp_path):
        from dtm_buildsheet.config.store import _backup_config, _BACKUP_LIMIT

        cfg_file = tmp_path / "app_settings.json"
        cfg_file.write_text("{}", "utf-8")
        history_dir = tmp_path / "history"
        history_dir.mkdir()

        # Pre-create 25 fake backup files with distinct timestamps
        for i in range(25):
            bak = history_dir / f"app_settings.json.2024010{i % 10}T{i:06d}Z.bak"
            bak.write_text(f"old-{i}", "utf-8")

        _backup_config(cfg_file)

        remaining = sorted(history_dir.glob("app_settings.json.*.bak"))
        assert len(remaining) <= _BACKUP_LIMIT

    def test_multiple_saves_accumulate_backups(self, tmp_path):
        from dtm_buildsheet.config.store import save_config

        paths = self._make_paths(tmp_path)
        cfg_file = paths.workspace_config_dir / "app_settings.json"
        cfg_file.write_text(json.dumps({"schema_version": 1, "template_save_dir": "", "output_save_dir": ""}), "utf-8")

        for _ in range(3):
            save_config("app_settings.json", {"template_save_dir": "", "output_save_dir": ""}, paths)
            time.sleep(0.01)  # ensure distinct timestamps

        history_dir = paths.workspace_config_dir / "history"
        backups = list(history_dir.glob("app_settings.json.*.bak"))
        assert len(backups) == 3
