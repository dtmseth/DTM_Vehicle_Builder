"""Baseline tests: render_ppt produces a valid, openable .pptx file."""
from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from dtm_buildsheet.paths import AppPaths
from dtm_buildsheet.planner import build_plan
from dtm_buildsheet.render_ppt import render_plan_to_ppt


@pytest.fixture(scope="module")
def rendered_pptx(tmp_path_factory, stearns_input, config):
    out_dir = tmp_path_factory.mktemp("output")
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=out_dir,
        samples_dir=config.paths.samples_dir,
    )
    plan = build_plan(stearns_input, config)
    ppt_path = render_plan_to_ppt(plan, paths)
    return ppt_path


def test_render_produces_file(rendered_pptx):
    assert rendered_pptx.exists(), f"Expected output file at {rendered_pptx}"


def test_render_file_has_reasonable_size(rendered_pptx):
    size = rendered_pptx.stat().st_size
    assert size > 10_000, f"Output file is suspiciously small: {size} bytes"


def test_render_file_has_pptx_extension(rendered_pptx):
    assert rendered_pptx.suffix == ".pptx"


def test_render_output_is_openable_by_pptx(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    assert prs is not None


def test_render_has_slides(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    assert len(prs.slides) > 0


def test_render_has_multiple_slides(rendered_pptx):
    prs = Presentation(str(rendered_pptx))
    # Expect at least a cover + one vehicle view + manifest
    assert len(prs.slides) >= 3


def test_render_second_sample(tmp_path_factory, test_build_input, config):
    out_dir = tmp_path_factory.mktemp("output2")
    paths = AppPaths(
        project_root=config.paths.project_root,
        package_dir=config.paths.package_dir,
        resources_dir=config.paths.resources_dir,
        assets_dir=config.paths.assets_dir,
        templates_dir=config.paths.templates_dir,
        workspace_dir=config.paths.workspace_dir,
        workspace_config_dir=config.paths.workspace_config_dir,
        workspace_assets_dir=config.paths.workspace_assets_dir,
        workspace_input_dir=config.paths.workspace_input_dir,
        workspace_output_dir=out_dir,
        samples_dir=config.paths.samples_dir,
    )
    plan = build_plan(test_build_input, config)
    ppt_path = render_plan_to_ppt(plan, paths)
    assert ppt_path.exists()
    prs = Presentation(str(ppt_path))
    assert len(prs.slides) > 0
