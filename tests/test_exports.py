"""Tests for PDF export service (Phase 12)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dtm_buildsheet.app.services.export_service import (
    _find_soffice,
    _stamp_export_on_project,
    export_to_pdf,
    open_file,
)
from dtm_buildsheet.domain.project_models import BuildUnit, IndividualUnit
from dtm_buildsheet.inputs.project_entry import load_project, new_project, save_project
from dtm_buildsheet.paths import AppPaths


# ── _find_soffice ──────────────────────────────────────────────────────────────

class TestFindSoffice:
    def test_returns_none_when_nothing_found(self, tmp_path):
        with patch(
            "dtm_buildsheet.app.services.export_service._SOFFICE_CANDIDATES", []
        ), patch("shutil.which", return_value=None):
            assert _find_soffice() is None

    def test_returns_candidate_when_file_exists(self, tmp_path):
        fake_soffice = tmp_path / "soffice"
        fake_soffice.touch()
        with patch(
            "dtm_buildsheet.app.services.export_service._SOFFICE_CANDIDATES",
            [str(fake_soffice)],
        ):
            assert _find_soffice() == str(fake_soffice)

    def test_skips_nonexistent_candidates(self, tmp_path):
        with patch(
            "dtm_buildsheet.app.services.export_service._SOFFICE_CANDIDATES",
            ["/nonexistent/soffice"],
        ), patch("shutil.which", return_value=None):
            assert _find_soffice() is None

    def test_falls_back_to_path_lookup(self):
        with patch(
            "dtm_buildsheet.app.services.export_service._SOFFICE_CANDIDATES", []
        ), patch("shutil.which", return_value="/usr/bin/soffice"):
            result = _find_soffice()
            assert result == "/usr/bin/soffice"


# ── export_to_pdf ──────────────────────────────────────────────────────────────

class TestExportToPdf:
    def test_finalized_reexport_requests_explicit_shop_overwrite(self, tmp_path):
        paths = AppPaths(
            workspace_dir=tmp_path,
            workspace_projects_dir=tmp_path / "projects",
            workspace_output_dir=tmp_path / "output",
        )
        pdf = tmp_path / "output" / "updated.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF updated")
        project = new_project(project_id="project-1")
        project.build_units = [BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                status="finalized",
                pdf_path="old.pdf",
                shop_pdf_item_id="shop-pdf-1",
                shop_pdf_path="Shop Project Database/vehicle/old.pdf",
            )],
        )]
        save_project(project, paths)

        prompt = _stamp_export_on_project({
            "project_id": "project-1",
            "unit_id": "group-1",
            "individual_id": "vehicle-1",
        }, pdf, paths)

        assert prompt == {
            "required": True,
            "project_id": "project-1",
            "unit_id": "group-1",
            "individual_id": "vehicle-1",
            "current_shop_pdf_path": "Shop Project Database/vehicle/old.pdf",
        }
        stored = load_project("project-1", paths).build_units[0].individuals[0]
        assert stored.pdf_path == str(pdf)
        assert stored.shop_pdf_item_id == "shop-pdf-1"
        assert stored.shop_pdf_path == "Shop Project Database/vehicle/old.pdf"

    def test_export_without_existing_shop_pdf_does_not_request_overwrite(self, tmp_path):
        paths = AppPaths(
            workspace_dir=tmp_path,
            workspace_projects_dir=tmp_path / "projects",
            workspace_output_dir=tmp_path / "output",
        )
        pdf = tmp_path / "output" / "first.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF first")
        project = new_project(project_id="project-1")
        project.build_units = [BuildUnit(
            unit_id="group-1",
            individuals=[IndividualUnit(
                individual_id="vehicle-1",
                status="finalized",
            )],
        )]
        save_project(project, paths)

        prompt = _stamp_export_on_project({
            "project_id": "project-1",
            "unit_id": "group-1",
            "individual_id": "vehicle-1",
        }, pdf, paths)

        assert prompt is None

    def test_missing_output_path_returns_error(self):
        result = export_to_pdf({})
        assert result["ok"] is False
        assert "output_path" in result["error"]

    def test_empty_output_path_returns_error(self):
        result = export_to_pdf({"output_path": ""})
        assert result["ok"] is False

    def test_nonexistent_pptx_returns_error(self, tmp_path):
        result = export_to_pdf({"output_path": str(tmp_path / "missing.pptx")})
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_foreign_pptx_is_downloaded_before_pdf_conversion(self, tmp_path):
        pptx = tmp_path / "output" / "shared.pptx"
        pptx.parent.mkdir()
        pptx.write_bytes(b"PK\x03\x04shared")
        paths = MagicMock()
        paths.workspace_output_dir = pptx.parent
        with patch(
            "dtm_buildsheet.app.services.exports_upload_service.download_export",
            return_value={"ok": True, "path": str(pptx), "downloaded": True},
        ) as download, patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value=None,
        ), patch(
            "dtm_buildsheet.app.services.export_service._export_via_applescript",
            return_value={"ok": False, "error": "Microsoft PowerPoint not installed"},
        ), patch("sys.platform", "darwin"):
            result = export_to_pdf({
                "output_path": r"C:\other\shared.pptx",
                "agency": "Test Agency",
                "year": "2026",
            }, paths)
        download.assert_called_once()
        assert result["ok"] is False
        assert "libreoffice" in result["error"].lower()

    def test_wrong_extension_returns_error(self, tmp_path):
        f = tmp_path / "file.docx"
        f.write_bytes(b"dummy")
        result = export_to_pdf({"output_path": str(f)})
        assert result["ok"] is False
        assert ".pptx" in result["error"]

    def test_no_soffice_no_win32_returns_install_hint(self, tmp_path):
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")
        # Simulate macOS with no LibreOffice and no PowerPoint installed.
        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value=None,
        ), patch(
            "dtm_buildsheet.app.services.export_service._export_via_applescript",
            return_value={"ok": False, "error": "Microsoft PowerPoint not installed: can't find application"},
        ), patch("sys.platform", "darwin"):
            result = export_to_pdf({"output_path": str(pptx)})
        assert result["ok"] is False
        assert "libreoffice" in result["error"].lower()

    def test_soffice_success(self, tmp_path):
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")
        pdf = tmp_path / "build.pdf"

        def fake_run(cmd, **kwargs):
            pdf.write_bytes(b"%PDF-1.4 fake")
            m = MagicMock()
            m.returncode = 0
            return m

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", side_effect=fake_run):
            result = export_to_pdf({"output_path": str(pptx)})

        assert result["ok"] is True
        assert result["pdf_name"] == "build.pdf"
        assert result["pdf_path"] == str(pdf)

    def test_soffice_nonzero_returncode_returns_error(self, tmp_path):
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")

        m = MagicMock()
        m.returncode = 1
        m.stderr = b"conversion failed"

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", return_value=m):
            result = export_to_pdf({"output_path": str(pptx)})

        assert result["ok"] is False
        assert "conversion failed" in result["error"].lower()

    def test_soffice_zero_return_but_pdf_missing_falls_through(self, tmp_path):
        """returncode==0 but PDF file not created — no error from stderr, falls through to next method."""
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")

        m = MagicMock()
        m.returncode = 0
        m.stderr = b""

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", return_value=m), patch(
            "sys.platform", "linux"
        ):
            result = export_to_pdf({"output_path": str(pptx)})

        # PDF was not created by the mock — should report error
        assert result["ok"] is False

    def test_soffice_timeout_returns_error(self, tmp_path):
        import subprocess as _sp

        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd="soffice", timeout=120)):
            result = export_to_pdf({"output_path": str(pptx)})

        assert result["ok"] is False
        assert "timed out" in result["error"].lower()

    def test_soffice_exception_returns_error(self, tmp_path):
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", side_effect=OSError("permission denied")):
            result = export_to_pdf({"output_path": str(pptx)})

        assert result["ok"] is False
        assert "permission denied" in result["error"].lower()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows COM path only")
    def test_windows_com_path_attempted_when_no_soffice(self, tmp_path):
        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")
        pdf = tmp_path / "build.pdf"
        pdf.write_bytes(b"%PDF")

        mock_com = MagicMock()
        mock_prs = MagicMock()
        mock_com.Presentations.Open.return_value = mock_prs

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value=None,
        ), patch(
            "dtm_buildsheet.app.services.export_service._export_via_powerpoint_com",
            return_value={"ok": True, "pdf_path": str(pdf), "pdf_name": "build.pdf"},
        ) as mock_export:
            result = export_to_pdf({"output_path": str(pptx)})

        mock_export.assert_called_once()
        assert result["ok"] is True


# ── open_file ─────────────────────────────────────────────────────────────────

class TestOpenFile:
    def test_missing_path_returns_error(self):
        result = open_file({})
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_nonexistent_file_returns_error(self, tmp_path):
        result = open_file({"path": str(tmp_path / "ghost.pptx")})
        assert result["ok"] is False

    def test_existing_file_opens_successfully(self, tmp_path):
        f = tmp_path / "out.pptx"
        f.write_bytes(b"dummy")
        with patch("subprocess.Popen") as mock_popen, patch("sys.platform", "darwin"):
            result = open_file({"path": str(f)})
        assert result["ok"] is True
        mock_popen.assert_called_once()

    def test_missing_foreign_path_downloads_shared_copy_before_opening(self, tmp_path):
        hydrated = tmp_path / "output" / "shared.pdf"
        hydrated.parent.mkdir()
        hydrated.write_bytes(b"%PDF-1.7\nshared")
        paths = MagicMock()
        paths.workspace_output_dir = hydrated.parent
        with patch(
            "dtm_buildsheet.app.services.exports_upload_service.download_export",
            return_value={"ok": True, "path": str(hydrated), "downloaded": True},
        ) as download, patch("subprocess.Popen") as popen, patch("sys.platform", "darwin"):
            result = open_file({
                "path": r"C:\other\shared.pdf",
                "agency": "Test Agency",
                "year": "2026",
            }, paths)
        assert result["ok"] is True
        download.assert_called_once()
        popen.assert_called_once()


# ── route integration ─────────────────────────────────────────────────────────

class TestExportRoute:
    def test_post_pdf_delegates_to_service(self, tmp_path):
        from dtm_buildsheet.app.routes.exports import post_pdf

        pptx = tmp_path / "build.pptx"
        pptx.write_bytes(b"dummy")
        pdf = tmp_path / "build.pdf"

        def fake_run(cmd, **kwargs):
            pdf.write_bytes(b"%PDF")
            m = MagicMock()
            m.returncode = 0
            return m

        with patch(
            "dtm_buildsheet.app.services.export_service._find_soffice",
            return_value="/usr/bin/soffice",
        ), patch("subprocess.run", side_effect=fake_run):
            result = post_pdf({"output_path": str(pptx)})

        assert result["ok"] is True
        assert result["pdf_name"] == "build.pdf"

    def test_post_open_delegates_to_service(self, tmp_path):
        from dtm_buildsheet.app.routes.exports import post_open

        f = tmp_path / "file.pptx"
        f.write_bytes(b"dummy")
        with patch("subprocess.Popen"), patch("sys.platform", "darwin"):
            result = post_open({"path": str(f)})
        assert result["ok"] is True
