"""Tests for the outbound retry queue.

The queue catches cloud writes that failed at save time (offline, stale
token, transient SharePoint hiccup) and retries them on every sync.
These tests verify the enqueue / drain contract without involving real
cloud — the autouse conftest fixture blocks that, and we monkeypatch
the drain's submit/upload functions to simulate success and failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dtm_buildsheet.app.services import outbound_queue
from dtm_buildsheet.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Hermetic workspace for queue files."""
    return AppPaths(workspace_dir=tmp_path)


# ── Enqueue ─────────────────────────────────────────────────────────────────


def test_enqueue_proposal_writes_a_json_payload(paths):
    assert outbound_queue.enqueue_proposal(
        paths,
        target_file="agencies/abc.json",
        serialized_content='{"name": "Test"}',
        summary="Add Test PD",
        category="general",
        action="upsert",
    )
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    files = list(queue_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text("utf-8"))
    assert data["type"] == "proposal"
    assert data["target_file"] == "agencies/abc.json"
    assert data["summary"] == "Add Test PD"
    assert data["category"] == "general"
    assert data["action"] == "upsert"


def test_enqueue_export_writes_a_json_payload(paths, tmp_path):
    pdf = tmp_path / "build_sheet.pdf"
    pdf.write_bytes(b"%PDF")
    assert outbound_queue.enqueue_export(
        paths,
        local_path=pdf,
        agency="Stearns County Sheriff",
        year="2026",
    )
    queue_dir = paths.workspace_dir / ".pending_outbound" / "exports"
    files = list(queue_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text("utf-8"))
    assert data["type"] == "export"
    assert data["local_path"] == str(pdf)
    assert data["agency"] == "Stearns County Sheriff"
    assert data["year"] == "2026"


def test_queue_depth_counts_each_kind(paths, tmp_path):
    pdf = tmp_path / "x.pdf"; pdf.write_bytes(b"%PDF")
    outbound_queue.enqueue_proposal(
        paths, target_file="agencies/a.json", serialized_content='{"name":"x"}',
        summary="s", category="general",
    )
    outbound_queue.enqueue_proposal(
        paths, target_file="agencies/b.json", serialized_content='{"name":"x"}',
        summary="s", category="general",
    )
    outbound_queue.enqueue_export(paths, local_path=pdf, agency="A", year="2026")
    depth = outbound_queue.queue_depth(paths)
    assert depth == {"proposals": 2, "exports": 1}


def test_queue_depth_for_empty_workspace(paths):
    assert outbound_queue.queue_depth(paths) == {"proposals": 0, "exports": 0}


# ── Drain ───────────────────────────────────────────────────────────────────


def test_drain_proposal_success_removes_queue_file(paths, monkeypatch):
    """When the retry submits successfully, the queue file gets cleaned up."""
    outbound_queue.enqueue_proposal(
        paths, target_file="agencies/x.json", serialized_content='{"name":"x"}',
        summary="s", category="general",
    )
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    assert len(list(queue_dir.glob("*.json"))) == 1

    from dtm_buildsheet.app.adapters import wiring
    monkeypatch.setattr(
        wiring, "_submit_proposal_to_cloud",
        lambda **kw: {"proposed": True, "proposal_id": "p1"},
    )
    report = outbound_queue.drain_queue(paths)
    assert report["proposals_retried"] == 1
    assert report["proposals_succeeded"] == 1
    assert len(list(queue_dir.glob("*.json"))) == 0


def test_drain_proposal_failure_leaves_queue_file(paths, monkeypatch):
    """A still-failing retry must leave the queue entry for the next pass."""
    outbound_queue.enqueue_proposal(
        paths, target_file="agencies/x.json", serialized_content='{"name":"x"}',
        summary="s", category="general",
    )
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    from dtm_buildsheet.app.adapters import wiring
    monkeypatch.setattr(
        wiring, "_submit_proposal_to_cloud",
        lambda **kw: {"proposed": False, "reason": "submit failed"},
    )
    report = outbound_queue.drain_queue(paths)
    assert report["proposals_retried"] == 1
    assert report["proposals_succeeded"] == 0
    assert len(list(queue_dir.glob("*.json"))) == 1


def test_drain_export_success_removes_queue_file(paths, monkeypatch, tmp_path):
    pdf = tmp_path / "build.pdf"; pdf.write_bytes(b"%PDF")
    outbound_queue.enqueue_export(
        paths, local_path=pdf, agency="Stearns", year="2026",
    )
    from dtm_buildsheet.app.services import exports_upload_service
    monkeypatch.setattr(
        exports_upload_service, "upload_export",
        lambda local_pptx, **kw: True,
    )
    report = outbound_queue.drain_queue(paths)
    assert report["exports_retried"] == 1
    assert report["exports_succeeded"] == 1
    queue_dir = paths.workspace_dir / ".pending_outbound" / "exports"
    assert len(list(queue_dir.glob("*.json"))) == 0


def test_drain_export_discards_when_local_file_gone(paths):
    """User moved or deleted the source PDF — no point retrying forever."""
    ghost_path = paths.workspace_dir / "deleted-after-queue.pdf"
    # Write then immediately delete to simulate "queued then user deleted".
    ghost_path.write_bytes(b"x")
    outbound_queue.enqueue_export(
        paths, local_path=ghost_path, agency="A", year="2026",
    )
    ghost_path.unlink()
    report = outbound_queue.drain_queue(paths)
    # We don't bump succeeded — but we DID remove the queue file.
    queue_dir = paths.workspace_dir / ".pending_outbound" / "exports"
    assert len(list(queue_dir.glob("*.json"))) == 0


def test_enqueue_and_drain_retire_powerpoint_exports(paths, tmp_path):
    pptx = tmp_path / "retired.pptx"
    pptx.write_bytes(b"PPTX")
    assert outbound_queue.enqueue_export(
        paths, local_path=pptx, agency="A", year="2026",
    ) is False

    queue_dir = paths.workspace_dir / ".pending_outbound" / "exports"
    queue_dir.mkdir(parents=True, exist_ok=True)
    legacy = queue_dir / "legacy.json"
    legacy.write_text(json.dumps({
        "type": "export",
        "local_path": str(pptx),
        "agency": "A",
        "year": "2026",
    }), encoding="utf-8")

    report = outbound_queue.drain_queue(paths)
    assert report["exports_retried"] == 1
    assert report["exports_succeeded"] == 0
    assert not legacy.exists()


def test_drain_handles_corrupt_queue_file(paths):
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("not json", encoding="utf-8")
    # Must not raise.
    outbound_queue.drain_queue(paths)
    # The bad file gets discarded so it doesn't poll forever.
    assert list(queue_dir.glob("*.json")) == []


def test_drain_caps_work_per_cycle(paths, monkeypatch):
    """A massive backlog shouldn't stall the 60s sync forever."""
    for i in range(60):
        outbound_queue.enqueue_proposal(
            paths, target_file=f"agencies/{i}.json", serialized_content='{"name":"x"}',
            summary="s", category="general",
        )
    from dtm_buildsheet.app.adapters import wiring
    # Keep failing so retries don't delete files; we only care about
    # how many we attempted in this cycle.
    monkeypatch.setattr(
        wiring, "_submit_proposal_to_cloud",
        lambda **kw: {"proposed": False, "reason": "submit failed"},
    )
    report = outbound_queue.drain_queue(paths)
    # Implementation caps drain at 25 per cycle.
    assert report["proposals_retried"] == 25


def test_enqueue_refuses_empty_upsert(paths):
    """Regression: empty agencies/abc.json upserts were time-bombing —
    every drain submitted one to /PendingChanges/ and the workflow
    eventually republished an empty record under /Settings/."""
    assert outbound_queue.enqueue_proposal(
        paths, target_file="agencies/abc.json",
        serialized_content="{}",  # empty upsert
        summary="empty test", category="general",
    ) is False
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    assert not queue_dir.exists() or not list(queue_dir.glob("*.json"))


def test_enqueue_allows_delete_with_no_content(paths):
    """Delete proposals legitimately have no payload."""
    assert outbound_queue.enqueue_proposal(
        paths, target_file="agencies/x.json", serialized_content="",
        summary="del", category="general", action="delete",
    ) is True


def test_drain_discards_junk_without_submitting(paths, monkeypatch, tmp_path):
    """If a junk proposal somehow lands in the queue (e.g., legacy file
    from before the enqueue guard), drain must NOT submit it."""
    # Write a junk queue file directly to bypass the enqueue guard.
    queue_dir = paths.workspace_dir / ".pending_outbound" / "proposals"
    queue_dir.mkdir(parents=True, exist_ok=True)
    import json as _json
    junk = queue_dir / "stale.json"
    junk.write_text(_json.dumps({
        "type": "proposal", "queued_at": "x",
        "target_file": "agencies/abc.json",
        "serialized_content": "{}",
        "summary": "empty", "category": "general", "action": "upsert",
    }))
    submitted = []
    from dtm_buildsheet.app.adapters import wiring
    monkeypatch.setattr(
        wiring, "_submit_proposal_to_cloud",
        lambda **kw: submitted.append(kw) or {"proposed": True},
    )
    outbound_queue.drain_queue(paths)
    assert submitted == []        # nothing was submitted
    assert not junk.exists()      # file was discarded
