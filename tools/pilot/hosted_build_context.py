#!/usr/bin/env python3
"""Stage Python-only hosted boundary inputs outside the checkout; no real records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def build_context(target):
    target = Path(target).resolve()
    if target.is_relative_to(ROOT) or target.exists():
        raise ValueError("Use a new directory outside the checkout")
    target.mkdir(parents=True)
    package = ROOT / "src/dtm_buildsheet"
    for source in sorted(package.rglob("*.py")):
        relative = source.relative_to(package)
        if ("resources" in relative.parts or "__pycache__" in relative.parts
                or relative.as_posix() in {"headless.py", "pilot_fixtures.py"}):
            continue
        if source.is_symlink():
            raise ValueError("No symlink build inputs")
        dest = target / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    for name in ("Dockerfile", "requirements.lock", ".dockerignore"):
        shutil.copyfile(ROOT / "packaging/hosted" / name, target / name)
    shutil.copyfile(ROOT / "pyproject.toml", target / "pyproject.toml")
    (target / "README.md").write_text("# DTM hosted boundary\nProvider/UI integration disabled.\n")
    manifest = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(target.rglob("*")) if p.is_file()}
    (target / "context-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"files": len(manifest), "context": str(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    build_context(parser.parse_args().target)
