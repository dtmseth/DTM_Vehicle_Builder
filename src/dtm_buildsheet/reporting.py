from __future__ import annotations

from collections import Counter
from pathlib import Path

from .domain import BuildPlan, PlannedPart


def _basename(path_str: str) -> str:
    return Path(path_str).name if path_str else ""


def _part_warning_count(part: PlannedPart) -> int:
    count = len(part.warnings)
    for placement in part.placements:
        count += len(placement.warnings)
        for instance in placement.instances:
            count += len(instance.warnings)
    return count


def render_markdown_summary(plan: BuildPlan) -> str:
    lines: list[str] = []
    mapped_parts = [part for part in plan.planned_parts if part.part_id != "unmapped"]
    unmapped_parts = [part for part in plan.planned_parts if part.part_id == "unmapped"]
    renderable_parts = [part for part in plan.planned_parts if part.render_kind != "none"]
    placed_parts = [part for part in renderable_parts if part.placements]
    placement_count = sum(len(part.placements) for part in plan.planned_parts)
    instance_count = sum(len(placement.instances) for part in plan.planned_parts for placement in part.placements)
    warning_count = len(plan.warnings) + sum(_part_warning_count(part) for part in plan.planned_parts)

    lines.extend(
        [
            f"# Build Plan Summary: {plan.project.get('ProjectID', 'UNKNOWN')}",
            "",
            "## Overview",
            "",
            f"- Agency: {plan.project.get('Agency', '—')}",
            f"- Vehicle: {plan.project.get('VehicleType', '—')}",
            f"- Quote: {plan.project.get('QuoteNumber', '—')}",
            f"- Parts in workbook: {len(plan.planned_parts)}",
            f"- Catalog-mapped parts: {len(mapped_parts)}",
            f"- Unmapped parts: {len(unmapped_parts)}",
            f"- Render-capable parts: {len(renderable_parts)}",
            f"- Diagram parts with placements: {len(placed_parts)}",
            f"- Planned placements: {placement_count}",
            f"- Planned render instances: {instance_count}",
            f"- Total warnings: {warning_count}",
            "",
        ]
    )

    if placed_parts:
        lines.extend(["## Planned Diagram Parts", ""])
        for part in placed_parts:
            lines.append(f"### {part.part_name}")
            lines.append("")
            lines.append(f"- Part ID: `{part.part_id}`")
            lines.append(f"- Category: `{part.category}`")
            lines.append(f"- Workbook Qty: `{part.raw.quantity}`")
            lines.append("")
            lines.append("| View | Location | Pattern | Profile | Assets | Warnings |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for placement in part.placements:
                assets = ", ".join(_basename(instance.asset_path) or "none" for instance in placement.instances) or "—"
                warnings = "; ".join(placement.warnings + [warning for instance in placement.instances for warning in instance.warnings]) or "—"
                lines.append(f"| {placement.view} | {placement.location_key} | {placement.pattern} | {placement.color_profile} | {assets} | {warnings} |")
            lines.append("")

    unresolved_diagram_parts = [part for part in renderable_parts if not part.placements]
    if unresolved_diagram_parts:
        lines.extend(["## Diagram Parts Needing Attention", "", "| Part | Reason |", "| --- | --- |"])
        for part in unresolved_diagram_parts:
            lines.append(f"| {part.part_name} | {'; '.join(part.warnings) or 'No placements generated'} |")
        lines.append("")

    warnings_by_text = Counter()
    for warning in plan.warnings:
        warnings_by_text[warning] += 1
    for part in plan.planned_parts:
        for warning in part.warnings:
            warnings_by_text[warning] += 1
        for placement in part.placements:
            for warning in placement.warnings:
                warnings_by_text[warning] += 1
            for instance in placement.instances:
                for warning in instance.warnings:
                    warnings_by_text[warning] += 1

    if warnings_by_text:
        lines.extend(["## Warning Rollup", "", "| Warning | Count |", "| --- | ---: |"])
        for warning, count in warnings_by_text.most_common():
            lines.append(f"| {warning} | {count} |")
        lines.append("")

    return "\n".join(lines)


def render_terminal_summary(plan: BuildPlan) -> str:
    mapped_parts = [part for part in plan.planned_parts if part.part_id != "unmapped"]
    unmapped_parts = [part for part in plan.planned_parts if part.part_id == "unmapped"]
    renderable_parts = [part for part in plan.planned_parts if part.render_kind != "none"]
    placed_parts = [part for part in renderable_parts if part.placements]
    warning_count = len(plan.warnings) + sum(_part_warning_count(part) for part in plan.planned_parts)

    lines = [
        f"Project: {plan.project.get('ProjectID', 'UNKNOWN')}",
        f"Mapped parts: {len(mapped_parts)}  |  Unmapped: {len(unmapped_parts)}",
        f"Diagram parts placed: {len(placed_parts)}/{len(renderable_parts)}",
        f"Warnings: {warning_count}",
    ]
    top_unresolved = []
    for part in plan.planned_parts:
        if part.warnings:
            top_unresolved.append((part.part_name, '; '.join(part.warnings)))
    if top_unresolved:
        lines.append("Top unresolved:")
        for part_name, reason in top_unresolved[:5]:
            lines.append(f"  - {part_name}: {reason}")
    return "\n".join(lines)
