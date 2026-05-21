from __future__ import annotations

from pathlib import Path

from dtm_buildsheet.paths import (
    _copy_missing_tree,
    relativize_output_path,
    resolve_output_path,
)


def test_copy_missing_tree_adds_and_updates_files(tmp_path: Path):
    source = tmp_path / "bundled"
    dest = tmp_path / "workspace"

    (source / "lights").mkdir(parents=True)
    (source / "equipment").mkdir(parents=True)
    (dest / "lights").mkdir(parents=True)

    (source / "lights" / "same.png").write_text("identical", "utf-8")
    (source / "lights" / "updated.png").write_text("bundled v2", "utf-8")
    (source / "equipment" / "new.png").write_text("new asset", "utf-8")
    (source / ".DS_Store").write_text("ignored", "utf-8")
    (dest / "lights" / "same.png").write_text("identical", "utf-8")
    (dest / "lights" / "updated.png").write_text("old version", "utf-8")

    written = _copy_missing_tree(source, dest)

    # new file is added
    assert (dest / "equipment" / "new.png").read_text("utf-8") == "new asset"
    # unchanged file is left alone
    assert (dest / "lights" / "same.png").read_text("utf-8") == "identical"
    # changed file is updated to match bundle
    assert (dest / "lights" / "updated.png").read_text("utf-8") == "bundled v2"
    # hidden files are skipped
    assert not (dest / ".DS_Store").exists()
    # count reflects actual writes (new + updated = 2)
    assert written == 2


# ── output path portability helpers ────────────────────────────────────────────


def test_resolve_output_path_returns_empty_for_empty(tmp_path: Path):
    assert resolve_output_path("", tmp_path) == ""


def test_resolve_output_path_passes_absolute_through(tmp_path: Path):
    abs_path = "/some/absolute/path/file.pptx"
    assert resolve_output_path(abs_path, tmp_path) == abs_path


def test_resolve_output_path_joins_relative_with_workspace(tmp_path: Path):
    result = resolve_output_path("output/foo.pptx", tmp_path)
    assert result == str(tmp_path / "output" / "foo.pptx")


def test_relativize_output_path_returns_empty_for_empty(tmp_path: Path):
    assert relativize_output_path("", tmp_path) == ""


def test_relativize_output_path_passes_relative_through(tmp_path: Path):
    assert relativize_output_path("output/foo.pptx", tmp_path) == "output/foo.pptx"


def test_relativize_output_path_relativizes_inside_workspace(tmp_path: Path):
    inside = tmp_path / "output" / "foo.pptx"
    inside.parent.mkdir(parents=True)
    inside.touch()
    assert relativize_output_path(str(inside), tmp_path) == "output/foo.pptx"


def test_relativize_output_path_keeps_outside_paths_absolute(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere" / "foo.pptx"
    result = relativize_output_path(str(outside), tmp_path)
    assert result == str(outside)


def test_resolve_then_relativize_round_trips(tmp_path: Path):
    inside = tmp_path / "output" / "foo.pptx"
    inside.parent.mkdir(parents=True)
    inside.touch()
    rel = relativize_output_path(str(inside), tmp_path)
    abs_again = resolve_output_path(rel, tmp_path)
    assert Path(abs_again) == inside
