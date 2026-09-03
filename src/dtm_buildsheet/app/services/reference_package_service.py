"""Build the exact render/publication reference-photo package for a vehicle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...domain.project_models import BuildReferenceAsset, BuildReferenceAssignment, ProjectRecord
from ...domain.reference_photos import (
    publication_file_names,
    resolve_build_reference_photos,
)
from ...paths import AppPaths
from .reference_media_service import resolve_reference_media


@dataclass(frozen=True)
class ReferencePackageEntry:
    asset: BuildReferenceAsset
    assignment: BuildReferenceAssignment
    origin: str
    published_file_name: str
    local_path: Path


@dataclass(frozen=True)
class ReferencePackage:
    entries: tuple[ReferencePackageEntry, ...]
    errors: tuple[str, ...]


def resolve_reference_package(
    project: ProjectRecord,
    *,
    unit_id: str,
    individual_id: str = "",
    paths: AppPaths,
) -> ReferencePackage:
    resolved = resolve_build_reference_photos(
        project,
        unit_id=unit_id,
        individual_id=individual_id,
    )
    names = publication_file_names(resolved)
    entries: list[ReferencePackageEntry] = []
    errors: list[str] = []
    for item, published_name in zip(resolved, names):
        media = resolve_reference_media(item.asset, paths)
        if media.path is None:
            errors.append(f"{item.asset.file_name}: {media.error}")
            continue
        entries.append(ReferencePackageEntry(
            asset=item.asset,
            assignment=item.assignment,
            origin=item.origin,
            published_file_name=published_name,
            local_path=media.path,
        ))
    return ReferencePackage(tuple(entries), tuple(errors))
