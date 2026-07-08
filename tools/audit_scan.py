"""Generate docs/audit/MANIFEST.md: a module manifest for the AUDIT_REFACTOR_ROADMAP.

AST-walks every `.py` file under `src/dtm_buildsheet` (imports in/out, resolved to
internal modules only), and lists every `.js` file under `src/dtm_buildsheet/ui/js`
(classic scripts — no import statements to walk; load order is script-tag order in
the HTML, not analyzable here). Output is deterministic and re-runnable: one command
regenerates the manifest from scratch (roadmap §8.1 Step 0 "done when").

Usage:
  python tools/audit_scan.py            # print + write docs/audit/MANIFEST.md
  python tools/audit_scan.py --check    # exit 1 if the file would change (CI use)
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "dtm_buildsheet"
UI_JS = SRC / "ui" / "js"
OUT = REPO / "docs" / "audit" / "MANIFEST.md"
PACKAGE = "dtm_buildsheet"

# Legacy modules per AUDIT_REFACTOR_ROADMAP.md §0 / §2.1 table.
LEGACY_MODULES = {
    "dtm_buildsheet.planner",
    "dtm_buildsheet.config_loader",
    "dtm_buildsheet.config_store",
    "dtm_buildsheet.config_validation",
    "dtm_buildsheet.models",
    "dtm_buildsheet.input_reader",
    "dtm_buildsheet.gui_server",
}

# Layer assignment: longest matching dotted prefix wins. Mirrors the import-linter
# layering in pyproject.toml (§4) plus the modules deliberately left outside it.
LAYER_PREFIXES = [
    ("dtm_buildsheet.app", "app"),
    ("dtm_buildsheet.inputs", "inputs"),
    ("dtm_buildsheet.config", "config"),
    ("dtm_buildsheet.storage", "storage"),
    ("dtm_buildsheet.planning", "planning"),
    ("dtm_buildsheet.rules", "rules"),
    ("dtm_buildsheet.domain", "domain"),
    ("dtm_buildsheet.naming", "naming/paths"),
    ("dtm_buildsheet.paths", "naming/paths"),
    ("dtm_buildsheet.parts_db", "parts_db"),
]
LEGACY_LAYER = "legacy-shim"
RENDERER_MODULES = {
    "dtm_buildsheet.ppt_helpers",
    "dtm_buildsheet.render_ppt",
    "dtm_buildsheet.template_builder",
    "dtm_buildsheet.reporting",
}
ENTRY_MODULES = {
    "dtm_buildsheet.__main__",
    "dtm_buildsheet.__init__",
    "dtm_buildsheet.generator",
    "dtm_buildsheet.generator_cli",
}


def module_name(py_file: Path) -> str:
    rel = py_file.relative_to(SRC.parent)  # dtm_buildsheet/...
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def layer_for(mod: str) -> str:
    if mod in LEGACY_MODULES:
        return LEGACY_LAYER
    if mod in RENDERER_MODULES:
        return "rendering"
    if mod in ENTRY_MODULES:
        return "entry"
    for prefix, layer in LAYER_PREFIXES:
        if mod == prefix or mod.startswith(prefix + "."):
            return layer
    return "other"


def _base_package(mod: str, level: int) -> list[str]:
    """The package `from . import x` (level=1) etc. is relative to, as dotted parts."""
    parts = mod.split(".")
    pkg_parts = parts[:-1] if not mod.endswith("__init__") else parts
    # level=1 -> current package; each extra level walks up one more parent.
    return pkg_parts[: len(pkg_parts) - (level - 1)] if level > 1 else pkg_parts


def resolve_import(mod: str, node_module: str | None, level: int, alias_name: str,
                    known: set[str]) -> str | None:
    """Resolve an import to a dotted dtm_buildsheet module, or None if external/unresolvable.

    `alias_name` may name a submodule (`from pkg import submodule`) or an attribute
    (`from pkg.mod import ClassName`) — AST can't tell them apart, so prefer whichever
    candidate is a real module in `known`; fall back to the module-only candidate.
    """
    if level > 0:
        base = _base_package(mod, level)
        module_only = base + node_module.split(".") if node_module else base
    else:
        if not node_module or not node_module.startswith(PACKAGE):
            return None
        module_only = node_module.split(".")

    module_candidate = ".".join(module_only)
    if alias_name and alias_name != "*":
        with_alias = ".".join(module_only + [alias_name])
        if with_alias in known:
            return with_alias
    if module_candidate in known:
        return module_candidate
    return module_candidate if module_candidate.startswith(PACKAGE) else None


def imports_of(py_file: Path, mod: str, known: set[str]) -> set[str]:
    try:
        tree = ast.parse(py_file.read_text("utf-8"), filename=str(py_file))
    except SyntaxError as exc:
        print(f"WARN: could not parse {py_file}: {exc}", file=sys.stderr)
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PACKAGE):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                resolved = resolve_import(mod, node.module, node.level or 0, alias.name, known)
                if resolved:
                    found.add(resolved)
    found.discard(mod)
    return found


def collect_py() -> dict[str, dict]:
    modules: dict[str, dict] = {}
    for py_file in sorted(SRC.rglob("*.py")):
        if "__pycache__" in py_file.parts or UI_JS in py_file.parents:
            continue
        mod = module_name(py_file)
        loc = sum(1 for _ in py_file.read_text("utf-8").splitlines())
        modules[mod] = {
            "path": py_file.relative_to(REPO).as_posix(),
            "loc": loc,
            "layer": layer_for(mod),
            "legacy": mod in LEGACY_MODULES,
            "imports_out": set(),
        }
    known = set(modules)
    for mod, info in modules.items():
        py_file = REPO / info["path"]
        info["imports_out"] = {m for m in imports_of(py_file, mod, known) if m in modules}
    for mod, info in modules.items():
        info["imports_in"] = sorted(
            other for other, oinfo in modules.items() if mod in oinfo["imports_out"]
        )
        info["imports_out"] = sorted(info["imports_out"])
    return modules


def collect_js() -> list[dict]:
    rows = []
    for js_file in sorted(UI_JS.rglob("*.js")):
        loc = sum(1 for _ in js_file.read_text("utf-8").splitlines())
        rows.append({
            "path": js_file.relative_to(REPO).as_posix(),
            "loc": loc,
        })
    return rows


def render(modules: dict[str, dict], js_rows: list[dict]) -> str:
    lines = []
    lines.append("# Module Manifest")
    lines.append("")
    lines.append(
        "Generated by `tools/audit_scan.py` (AST import walk) — "
        "AUDIT_REFACTOR_ROADMAP.md §8.1 Step 0. Regenerate with "
        "`python tools/audit_scan.py`; do not hand-edit."
    )
    lines.append("")
    lines.append(
        "Audit status (Pass 1, §1.2: which modules have been classified into "
        "LEDGER.md) is tracked in LEDGER.md itself, not here — this file is pure "
        "structure (path/LOC/layer/imports), regenerated from the import graph on "
        "every run, so it never goes stale relative to the code."
    )
    lines.append("")

    lines.append("## Python (`src/dtm_buildsheet`)")
    lines.append("")
    lines.append(
        f"{len(modules)} modules, "
        f"{sum(m['loc'] for m in modules.values())} LOC total."
    )
    lines.append("")
    lines.append("| Module | Path | LOC | Layer | Legacy | Imports in | Imports out |")
    lines.append("|---|---|---:|---|---|---:|---:|")
    for mod in sorted(modules):
        info = modules[mod]
        legacy = "yes" if info["legacy"] else ""
        lines.append(
            f"| `{mod}` | {info['path']} | {info['loc']} | {info['layer']} | {legacy} | "
            f"{len(info['imports_in'])} | {len(info['imports_out'])} |"
        )
    lines.append("")

    lines.append("## JavaScript (`src/dtm_buildsheet/ui/js`)")
    lines.append("")
    lines.append(
        f"{len(js_rows)} files, {sum(r['loc'] for r in js_rows)} LOC total. "
        "Classic scripts (no ES modules) — load order is the `<script>` tag order in "
        "the served HTML, not statically resolvable here; see `docs/UI_STRUCTURE.md`."
    )
    lines.append("")
    lines.append("| File | Path | LOC |")
    lines.append("|---|---|---:|")
    for row in js_rows:
        lines.append(f"| `{Path(row['path']).name}` | {row['path']} | {row['loc']} |")
    lines.append("")

    lines.append("## Entry points (§1.1 census)")
    lines.append("")
    lines.append("| Root | Location |")
    lines.append("|---|---|")
    lines.append("| GUI (`__main__`) | `src/dtm_buildsheet/__main__.py` -> `gui_server.main` |")
    lines.append("| `generator_cli` | `src/dtm_buildsheet/generator_cli.py` |")
    lines.append("| HTTP route table | `src/dtm_buildsheet/app/server.py` |")
    lines.append("| JS event handlers per tab | `src/dtm_buildsheet/ui/js/*.js` |")
    lines.append("| relay functions | `relay/` |")
    lines.append("| scripts / tools | `scripts/`, `tools/` |")
    lines.append(
        "| packaging: `[project.scripts]` | `pyproject.toml` "
        "(`gui_server:main`, `generator_cli:main`) |"
    )
    lines.append(
        "| packaging: PyInstaller launcher | `packaging/pyinstaller/launch_gui.py` "
        "(imports `gui_server` directly) |"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if MANIFEST.md would change")
    args = ap.parse_args()

    modules = collect_py()
    js_rows = collect_js()
    content = render(modules, js_rows)

    if args.check:
        current = OUT.read_text("utf-8") if OUT.exists() else ""
        if current != content:
            print("MANIFEST.md is stale — run `python tools/audit_scan.py`", file=sys.stderr)
            return 1
        print("MANIFEST.md up to date")
        return 0

    OUT.write_text(content, "utf-8")
    print(f"Wrote {OUT.relative_to(REPO)} ({len(modules)} py modules, {len(js_rows)} js files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
