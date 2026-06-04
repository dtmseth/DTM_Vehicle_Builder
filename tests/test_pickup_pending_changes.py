"""Tests for the pickup-pending-changes script.

The script lives in dtm-shared-settings/scripts/ (a sibling repo checked out
alongside this one). We add its directory to sys.path before importing so the
pure functions (validate, resolve_category, _validate_target_file) get
covered without depending on the settings repo's own test setup.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PICKUP_PATH = (
    Path(__file__).resolve().parent.parent
    / "dtm-shared-settings"
    / "scripts"
    / "pickup_pending_changes.py"
)


def _load_pickup_module():
    spec = importlib.util.spec_from_file_location("pickup_pending_changes", _PICKUP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pickup_pending_changes"] = module
    spec.loader.exec_module(module)
    return module


pickup = _load_pickup_module()


# ── _validate_target_file ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target",
    [
        "parts_library.json",
        "agencies/agency-123.json",
        "presets/koochiching_county_durango.json",
        "sales_reps/rep-001.json",
    ],
)
def test_target_file_accepts_supported_shapes(target):
    assert pickup._validate_target_file(target) is None


@pytest.mark.parametrize(
    "target",
    [
        "",
        "/etc/passwd",
        ".hidden.json",
        "../escape.json",
        "agencies/../escape.json",
        "agencies/sub/deep.json",
        "agencies/.hidden.json",
        "agencies/foo.txt",
        "config.txt",
        "foo\\bar.json",
    ],
)
def test_target_file_rejects_unsafe_shapes(target):
    assert pickup._validate_target_file(target) is not None


# ── resolve_category ─────────────────────────────────────────────────────────


def test_resolve_category_v1_defaults_to_advanced():
    """v1 payloads have no `category` — must keep today's review-required behavior."""
    assert pickup.resolve_category({"schema_version": 1}) == "advanced"


# ── resolve_action (v3) ─────────────────────────────────────────────────────


def test_resolve_action_v1_v2_default_to_upsert():
    """Older schemas had no action — keep write-only behavior for backward compat."""
    assert pickup.resolve_action({"schema_version": 1}) == "upsert"
    assert pickup.resolve_action({"schema_version": 2}) == "upsert"


def test_resolve_action_unknown_value_defaults_to_upsert():
    """Future action the workflow doesn't know — never silently delete."""
    assert pickup.resolve_action({"action": "shred"}) == "upsert"


@pytest.mark.parametrize("value", ["upsert", "UPSERT", "delete", " DELETE "])
def test_resolve_action_normalizes_known_values(value):
    expected = value.strip().lower()
    assert pickup.resolve_action({"action": value}) == expected


def test_resolve_category_unknown_value_defaults_to_advanced():
    """Future tier the workflow doesn't recognize — safe fallback is advanced."""
    assert pickup.resolve_category({"category": "premium"}) == "advanced"


@pytest.mark.parametrize("value", ["general", "GENERAL", " advanced "])
def test_resolve_category_normalizes_known_values(value):
    expected = value.strip().lower()
    assert pickup.resolve_category({"category": value}) == expected


# ── validate ────────────────────────────────────────────────────────────────


def _base_payload(**overrides):
    payload = {
        "schema_version": 2,
        "proposal_id": "pid-123",
        "target_file": "agencies/foo.json",
        "category": "general",
        "summary": "Add Hennepin PD",
        "submitted_by": "Seth Miller",
        "new_content": "{}",
    }
    payload.update(overrides)
    return payload


def test_validate_accepts_v2_general():
    assert pickup.validate(_base_payload()) is None


def test_validate_accepts_v1_without_category():
    """v1 proposals must continue to validate after Phase 2-β ships."""
    v1 = _base_payload(schema_version=1, target_file="parts_library.json")
    v1.pop("category")
    assert pickup.validate(v1) is None


def test_validate_rejects_unknown_schema_version():
    assert pickup.validate(_base_payload(schema_version=99)) is not None


@pytest.mark.parametrize(
    "missing", ["proposal_id", "target_file", "new_content", "summary", "submitted_by"]
)
def test_validate_rejects_missing_required_fields(missing):
    payload = _base_payload()
    payload[missing] = ""
    assert pickup.validate(payload) is not None


def test_validate_rejects_path_traversal_in_target_file():
    assert pickup.validate(_base_payload(target_file="../../etc/passwd")) is not None


def test_validate_accepts_delete_action_without_new_content():
    """new_content is required for upsert but optional for delete — the
    pickup workflow only needs target_file to git-rm."""
    payload = _base_payload(schema_version=3, action="delete")
    payload["new_content"] = ""  # empty is fine for deletes
    assert pickup.validate(payload) is None


def test_validate_still_requires_new_content_for_upsert():
    payload = _base_payload(schema_version=3, action="upsert")
    payload["new_content"] = ""
    assert pickup.validate(payload) is not None
