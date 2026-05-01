from __future__ import annotations

from pathlib import Path

from dtm_buildsheet.paths import _copy_missing_tree


def test_copy_missing_tree_adds_missing_files_without_overwriting(tmp_path: Path):
    source = tmp_path / "bundled"
    dest = tmp_path / "workspace"

    (source / "lights").mkdir(parents=True)
    (source / "equipment").mkdir(parents=True)
    (dest / "lights").mkdir(parents=True)

    (source / "lights" / "existing.png").write_text("bundled", "utf-8")
    (source / "equipment" / "new.png").write_text("new asset", "utf-8")
    (source / ".DS_Store").write_text("ignored", "utf-8")
    (dest / "lights" / "existing.png").write_text("user edited", "utf-8")

    _copy_missing_tree(source, dest)

    assert (dest / "equipment" / "new.png").read_text("utf-8") == "new asset"
    assert (dest / "lights" / "existing.png").read_text("utf-8") == "user edited"
    assert not (dest / ".DS_Store").exists()
