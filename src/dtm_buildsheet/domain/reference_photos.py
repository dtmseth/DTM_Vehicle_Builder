"""Pure reference-photo assignment and resolution rules.

Cloud adapters resolve/download source items; this module only decides which
portable project references apply to a build. Keeping the rule here prevents
the Project Overview, renderer, finalization, and Shop publisher from growing
different interpretations of project/group/individual scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    ProjectRecord,
)


_SCOPE_SPECIFICITY = {"project": 0, "unit_group": 1, "individual": 2}


@dataclass(frozen=True)
class ResolvedBuildReference:
    asset: BuildReferenceAsset
    assignment: BuildReferenceAssignment

    @property
    def origin(self) -> str:
        return self.assignment.scope


def _matches(
    assignment: BuildReferenceAssignment,
    *,
    unit_id: str,
    individual_id: str,
) -> bool:
    if assignment.scope == "project":
        return True
    if assignment.scope == "unit_group":
        return bool(unit_id) and assignment.target_id == unit_id
    if assignment.scope == "individual":
        return bool(individual_id) and assignment.target_id == individual_id
    return False


def resolve_build_reference_photos(
    project: ProjectRecord,
    *,
    unit_id: str,
    individual_id: str = "",
) -> list[ResolvedBuildReference]:
    """Return the effective, de-duplicated photo set for one build.

    A reused asset may carry overlapping assignments. The most-specific
    matching assignment supplies its note/order; a later duplicate at the same
    specificity wins deterministically, matching the last explicit edit.
    Videos are intentionally excluded from every generated/shop consumer.
    """

    resolved: list[ResolvedBuildReference] = []
    for asset in project.reference_assets:
        if asset.media_type != "photo":
            continue
        candidates = [
            (index, assignment)
            for index, assignment in enumerate(asset.assignments)
            if _matches(assignment, unit_id=unit_id, individual_id=individual_id)
        ]
        if not candidates:
            continue
        _, assignment = max(
            candidates,
            key=lambda pair: (_SCOPE_SPECIFICITY.get(pair[1].scope, -1), pair[0]),
        )
        resolved.append(ResolvedBuildReference(asset=asset, assignment=assignment))

    resolved.sort(
        key=lambda item: (
            item.assignment.sort_order,
            item.asset.file_name.casefold(),
            item.asset.reference_id,
        )
    )
    return resolved


def invalid_reference_targets(project: ProjectRecord) -> list[str]:
    """Return stable error strings for assignments pointing outside project."""

    group_ids = {unit.unit_id for unit in project.build_units}
    individual_ids = {
        individual.individual_id
        for unit in project.build_units
        for individual in unit.individuals
    }
    errors: list[str] = []
    for asset in project.reference_assets:
        for assignment in asset.assignments:
            if assignment.scope == "unit_group" and assignment.target_id not in group_ids:
                errors.append(f"{asset.reference_id}: unknown unit group {assignment.target_id}")
            elif assignment.scope == "individual" and assignment.target_id not in individual_ids:
                errors.append(f"{asset.reference_id}: unknown individual unit {assignment.target_id}")
    return errors


def publication_file_names(items: list[ResolvedBuildReference]) -> list[str]:
    """Return deterministic, folder-safe, case-insensitively unique names."""
    used: set[str] = set()
    result: list[str] = []
    for item in items:
        raw = PurePosixPath(str(item.asset.file_name or "").replace("\\", "/")).name
        suffix = PurePosixPath(raw).suffix.casefold()
        stem = raw[:-len(suffix)] if suffix else raw
        stem = re.sub(r"[^A-Za-z0-9 _.-]+", "_", stem).strip(" ._") or "Reference Photo"
        suffix = suffix if suffix in {".jpg", ".jpeg", ".png"} else ".jpg"
        candidate = f"{stem}{suffix}"
        if candidate.casefold() in used:
            token = re.sub(r"[^A-Za-z0-9]+", "", item.asset.reference_id)[:8] or "copy"
            candidate = f"{stem}-{token}{suffix}"
            serial = 2
            while candidate.casefold() in used:
                candidate = f"{stem}-{token}-{serial}{suffix}"
                serial += 1
        used.add(candidate.casefold())
        result.append(candidate)
    return result
