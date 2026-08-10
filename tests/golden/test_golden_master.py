"""Golden-master pins for the generation pipeline (§8.1 Step 1a).

Corpus (GOLDEN_MASTER_SPEC.md §5): every ``samples/`` workbook (Excel-upload
adapter) plus one real, anonymized PIU project per available build type
(GUI-draft adapter — TRAVERSE/TAHOE/DURANGO/F-150 real-project coverage is a
corpus TODO, see the module docstring below). Each case generates under a
hermetic, throwaway workspace and compares the normalized digest
(``digest.py``) of the rendered ``.pptx`` and the plan JSON against the
committed ``expected/<case>/`` files.

Recording / re-recording (GOLDEN_MASTER_SPEC.md §6 update protocol — an
intentional behavior change re-records in its own commit, never mixed with a
refactor):

    pytest tests/golden/test_golden_master.py --golden-record

Corpus TODOs (§5.2 — only PIU has real-project coverage in the workspace
today; tracked here rather than blocking Step 1a):
- TRAVERSE, TAHOE, DURANGO, F-150 real-project golden cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.golden import harness
from tests.golden.digest import canonical_dumps, json_digest, pptx_digest

GOLDEN_DIR = Path(__file__).resolve().parent
EXPECTED_DIR = GOLDEN_DIR / "expected"
INPUTS_DIR = GOLDEN_DIR / "inputs"
SAMPLES_DIR = harness.REPO_ROOT / "samples"

WORKBOOK_CASES = {
    "workbook_test_build_tuesday": SAMPLES_DIR / "input" / "Test_Build_Tuesday.xlsx",
    "workbook_mock_realistic_piu": SAMPLES_DIR / "generated" / "mock_realistic_piu.xlsx",
    "workbook_piu_full_build": SAMPLES_DIR / "generated" / "piu_full_build.xlsx",
    "workbook_piu_location_sweep": SAMPLES_DIR / "generated" / "piu_location_sweep.xlsx",
}

DRAFT_CASES = {
    "draft_piu_patrol": INPUTS_DIR / "draft_piu_patrol.json",
    "draft_piu_admin": INPUTS_DIR / "draft_piu_admin.json",
}

ALL_CASES = {**WORKBOOK_CASES, **DRAFT_CASES}


def _digests_for_case(case_name: str, source: Path, tmp_path: Path) -> tuple[dict, dict]:
    paths = harness.hermetic_paths(tmp_path)
    if case_name in WORKBOOK_CASES:
        result = harness.generate_from_workbook(source, paths)
        ppt_path, plan_path = result.ppt_path, result.plan_path
    else:
        ppt_path, plan_path = harness.generate_from_draft_file(source, paths)
    return pptx_digest(ppt_path), json_digest(plan_path)


@pytest.mark.parametrize("case_name", sorted(ALL_CASES))
def test_golden_master(case_name, tmp_path, request):
    source = ALL_CASES[case_name]
    assert source.exists(), f"golden-master input missing: {source}"

    pptx_dig, plan_dig = _digests_for_case(case_name, source, tmp_path)

    case_dir = EXPECTED_DIR / case_name
    pptx_expected_path = case_dir / "pptx_digest.json"
    plan_expected_path = case_dir / "plan_digest.json"

    if request.config.getoption("--golden-record"):
        case_dir.mkdir(parents=True, exist_ok=True)
        pptx_expected_path.write_text(canonical_dumps(pptx_dig), "utf-8")
        plan_expected_path.write_text(canonical_dumps(plan_dig), "utf-8")
        meta_path = case_dir / "meta.json"
        meta_path.write_text(
            canonical_dumps({
                "case_name": case_name,
                "input_path": str(source.relative_to(harness.REPO_ROOT)),
                "adapter": "workbook" if case_name in WORKBOOK_CASES else "draft",
            }),
            "utf-8",
        )
        pytest.skip(f"recorded {case_name}")

    assert pptx_expected_path.exists(), (
        f"no recorded digest for {case_name} — run with --golden-record first"
    )
    assert plan_expected_path.exists(), (
        f"no recorded plan digest for {case_name} — run with --golden-record first"
    )

    assert canonical_dumps(pptx_dig) == pptx_expected_path.read_text("utf-8"), (
        f"{case_name}: rendered .pptx digest changed — see the diff above for what moved"
    )
    assert canonical_dumps(plan_dig) == plan_expected_path.read_text("utf-8"), (
        f"{case_name}: plan JSON digest changed — see the diff above for what changed"
    )
