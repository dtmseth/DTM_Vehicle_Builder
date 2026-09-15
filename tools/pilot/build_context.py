#!/usr/bin/env python3
"""Assemble an allowlisted container context outside the checkout.

Usage: .venv/bin/python tools/pilot/build_context.py /private/tmp/dtm-pilot-context
Reads current working files, including unreleased code; never copies Git or records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from dtm_buildsheet.pilot_fixtures import copy_render_resources


def build_context(target: Path):
    target = target.resolve()
    if target.is_relative_to(ROOT) or target == ROOT:
        raise ValueError("Build context must be outside the checkout")
    if target.exists() and any(target.iterdir()):
        raise ValueError("Use a new empty build-context directory")
    target.mkdir(parents=True, exist_ok=True)

    def copy(source, relative):
        if source.is_symlink():
            raise ValueError(f"Symlink is not a build input: {relative}")
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)

    package = ROOT / "src" / "dtm_buildsheet"
    for file in sorted(package.rglob("*.py")):
        if "resources" not in file.relative_to(package).parts:
            copy(file, file.relative_to(ROOT))
    for file in sorted((package / "ui").rglob("*")):
        if file.is_file() and file.suffix in {".html", ".css", ".js", ".png", ".svg", ".ico"}:
            copy(file, file.relative_to(ROOT))
    copy_render_resources(package / "resources", target / "src/dtm_buildsheet/resources")
    copy(package / "resources/templates/build_sheet_template.pptx",
         Path("src/dtm_buildsheet/resources/templates/build_sheet_template.pptx"))
    copy(ROOT / "pyproject.toml", Path("pyproject.toml"))
    (target / "README.md").write_text("# DTM local pilot\nSynthetic local runtime only.\n")
    for name in ("Dockerfile", "requirements.lock", "debian.sources", "compose.yaml", ".dockerignore", "relay.py"):
        copy(ROOT / "packaging/pilot" / name, Path(name))
    manifest = {str(file.relative_to(target)): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in sorted(target.rglob("*")) if file.is_file()}
    (target / "context-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"context": str(target), "files": len(manifest),
                      "bytes": sum(file.stat().st_size for file in target.rglob("*") if file.is_file())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    build_context(parser.parse_args().target)
