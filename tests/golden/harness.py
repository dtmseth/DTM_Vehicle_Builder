"""Hermetic generation harness for the golden-master corpus (§8.1 Step 1a).

Reuses the same hermetic-``AppPaths`` concept as ``tools/ui_smoke/hermetic.py``
(seed a throwaway workspace from ``resources/config`` / ``resources/assets`` /
``resources/presets``, never the developer's live workspace or
``ensure_workspace()``'s cloud_config.json seeding) so a config edit on this
machine can't silently invalidate the recorded corpus.

Two entry points, one per input adapter (GOLDEN_MASTER_SPEC.md §5):

    generate_from_workbook(xlsx_path, paths) -> GenerationResult
        The Excel-upload adapter, via ``generator.generate_build_sheet``.

    generate_from_draft_file(draft_json_path, paths) -> (ppt_path, plan_path)
        The GUI-draft adapter. Loads a committed ``BuildDraft`` JSON fixture
        directly (no ``drafts_dir`` round-trip needed) and drives the same
        planning + rendering pipeline ``draft_service.handle_generate_from_draft``
        uses in production, minus the HTTP/project-record bookkeeping.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def hermetic_paths(root: Path):
    """A throwaway ``AppPaths`` under *root*, seeded like a fresh install
    (config/assets/presets from resources/), with no cloud_config.json."""
    from dtm_buildsheet.paths import (
        ASSETS_DIR,
        BUNDLED_PRESETS_DIR,
        DEFAULT_CONFIG_DIR,
        AppPaths,
    )

    ws = root / "workspace"
    overrides = {
        "workspace_dir": ws,
        "workspace_config_dir": ws / "config",
        "workspace_assets_dir": ws / "assets",
        "workspace_input_dir": ws / "input",
        "workspace_output_dir": ws / "output",
        "workspace_drafts_dir": ws / "drafts",
        "workspace_presets_dir": ws / "presets",
        "workspace_projects_dir": ws / "projects",
    }
    for d in overrides.values():
        d.mkdir(parents=True, exist_ok=True)

    for src in sorted(DEFAULT_CONFIG_DIR.glob("*.json")):
        shutil.copyfile(src, overrides["workspace_config_dir"] / src.name)
    shutil.copytree(ASSETS_DIR, overrides["workspace_assets_dir"], dirs_exist_ok=True)
    shutil.copytree(BUNDLED_PRESETS_DIR, overrides["workspace_presets_dir"], dirs_exist_ok=True)

    assert not (ws / "cloud_config.json").exists(), "hermetic workspace must have no cloud_config.json"
    return dataclasses.replace(AppPaths(), **overrides)


def generate_from_workbook(xlsx_path: Path, paths):
    """Drive the Excel-upload adapter (``generator.generate_build_sheet``)."""
    from dtm_buildsheet.generator import generate_build_sheet

    return generate_build_sheet(input_xlsx=xlsx_path, paths=paths)


def generate_from_draft_file(draft_path: Path, paths) -> tuple[Path, Path]:
    """Drive the GUI-draft adapter from a committed ``BuildDraft`` JSON fixture.

    Mirrors ``app/services/draft_service.py::handle_generate_from_draft``'s
    core pipeline (load -> draft_to_project_input -> build_plan -> overrides
    -> render), skipping the HTTP-request/project-record bookkeeping that
    fixture doesn't need — the fixture's ``vehicle_info`` already carries
    everything the planner needs.
    """
    from dtm_buildsheet.config.loader import load_configs
    from dtm_buildsheet.inputs.project_drafts import BuildDraft, DraftPart, draft_to_project_input
    from dtm_buildsheet.planning.override_applier import apply_overrides
    from dtm_buildsheet.planning.planner import build_plan
    from dtm_buildsheet.render_ppt import render_plan_to_ppt
    from dtm_buildsheet.reporting import render_markdown_summary
    from dtm_buildsheet.storage.local import LocalStorageProvider

    data = json.loads(draft_path.read_text("utf-8"))
    parts = [DraftPart(**p) for p in data.pop("parts", [])]
    draft = BuildDraft(parts=parts, **data)

    project = draft_to_project_input(draft)
    config = load_configs(paths)
    plan = build_plan(project, config)
    if draft.placement_overrides:
        plan = apply_overrides(plan, draft.placement_overrides)

    project_id = project.info.get("ProjectID", "DRAFT")
    out_dir = paths.workspace_output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    ppt_path = render_plan_to_ppt(plan, paths)
    plan_path = out_dir / f"BuildPlan_{project_id}.json"
    summary_path = out_dir / f"BuildSummary_{project_id}.md"

    storage = LocalStorageProvider()
    storage.write_text(str(plan_path), json.dumps(plan.to_dict(), indent=2))
    storage.write_text(str(summary_path), render_markdown_summary(plan))
    return ppt_path, plan_path
