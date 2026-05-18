"""Utilities for computing and creating project-specific output directories.

Project builds export into:
    <project_output_root>/<agency_slug> - <build_year>/

The root is stored in app_settings.json as ``project_output_root``.  When it is
empty the caller should fall back to the legacy global output_save_dir.
"""
from __future__ import annotations

import re
from pathlib import Path


def _slugify(value: str) -> str:
    """Convert a display string to a safe directory-name fragment."""
    value = value.strip()
    # Collapse any characters that are unsafe in directory names
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:80]


def project_subdir_name(agency: str, build_year: str) -> str:
    """Return the subdirectory name for a project: '<agency> - <year>' or just '<agency>'."""
    agency_slug = _slugify(agency) or "Unknown Agency"
    year = build_year.strip()
    if year:
        return f"{agency_slug} - {year}"
    return agency_slug


def resolve_project_output_dir(
    project_output_root: str,
    agency: str,
    build_year: str,
) -> Path | None:
    """Return the resolved project output Path, or None if root is not configured.

    Does NOT create the directory — call ``ensure_project_output_dir`` for that.
    """
    root = project_output_root.strip()
    if not root:
        return None
    return Path(root) / project_subdir_name(agency, build_year)


def ensure_project_output_dir(
    project_output_root: str,
    agency: str,
    build_year: str,
) -> Path | None:
    """Compute and create the project output directory.

    Returns the created Path, or None when ``project_output_root`` is not set.
    """
    target = resolve_project_output_dir(project_output_root, agency, build_year)
    if target is None:
        return None
    target.mkdir(parents=True, exist_ok=True)
    return target
