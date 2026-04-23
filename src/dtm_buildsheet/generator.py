from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config_loader import load_configs
from .input_reader import load_input
from .paths import AppPaths, ensure_workspace
from .planner import build_plan
from .render_ppt import render_plan_to_ppt
from .reporting import render_markdown_summary, render_terminal_summary


@dataclass
class GenerationResult:
    plan_path: Path
    summary_path: Path
    ppt_path: Path
    warnings: list[str]
    parts_count: int
    placements_count: int
    project_id: str
    terminal_summary: str


def find_input_file(paths: AppPaths | None = None) -> Path | None:
    active_paths = paths or ensure_workspace()
    candidates = sorted(active_paths.workspace_input_dir.glob("*.xlsx"))
    non_templates = [path for path in candidates if "template" not in path.name.lower()]
    return non_templates[0] if non_templates else (candidates[0] if candidates else None)


def generate_build_sheet(input_xlsx: Path | None = None, paths: AppPaths | None = None) -> GenerationResult:
    active_paths = paths or ensure_workspace()
    selected_input = input_xlsx or find_input_file(active_paths)
    if selected_input is None or not selected_input.exists():
        raise FileNotFoundError(f"No input workbook found in {active_paths.workspace_input_dir}")

    project = load_input(selected_input)
    config = load_configs(active_paths)
    plan = build_plan(project, config)

    project_id = project.info.get("ProjectID", "UNKNOWN")
    plan_path = active_paths.workspace_output_dir / f"BuildPlan_{project_id}.json"
    summary_path = active_paths.workspace_output_dir / f"BuildPlan_{project_id}_summary.md"

    plan_path.write_text(json.dumps(plan.to_dict(), indent=2) + "\n", "utf-8")
    summary_path.write_text(render_markdown_summary(plan), "utf-8")
    ppt_path = render_plan_to_ppt(plan, active_paths)

    all_warnings: list[str] = list(plan.warnings)
    for planned_part in plan.planned_parts:
        all_warnings.extend(planned_part.warnings)
        for placement in planned_part.placements:
            all_warnings.extend(placement.warnings)
            for instance in placement.instances:
                all_warnings.extend(instance.warnings)

    return GenerationResult(
        plan_path=plan_path,
        summary_path=summary_path,
        ppt_path=ppt_path,
        warnings=all_warnings,
        parts_count=len(project.parts),
        placements_count=sum(len(part.placements) for part in plan.planned_parts),
        project_id=project_id,
        terminal_summary=render_terminal_summary(plan),
    )
