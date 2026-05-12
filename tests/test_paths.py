from __future__ import annotations

from pathlib import Path

from dtm_buildsheet.paths import _copy_missing_tree


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
