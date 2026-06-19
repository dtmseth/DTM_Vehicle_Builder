"""Save/resume build drafts for GUI-first build entry.

A BuildDraft is richer than ProjectInput: it carries per-build placement
overrides, validation messages, and an audit trail so a user can come back to
an in-progress build, see what changed, and generate from the current state.

Draft files live in workspace/drafts/{draft_id}.json.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain.input_models import PartInput, ProjectInput
from ..naming import canonical_name, safe_id, safe_project_id
from ..paths import AppPaths
from ..storage.local import LocalStorageProvider

_log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _bool(v: Any, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    text = _s(v).lower()
    if not text:
        return default
    return text not in {"n", "no", "false", "0", "off"}


@dataclass
class DraftPart:
    """One part entry in a build draft, mirroring PartInput with an extra
    placement_overrides dict for per-build layout adjustments."""
    name: str
    include: bool = True
    new_or_used: str = "New"
    source: str = ""
    manufacturer: str = ""
    part_number: str = ""
    location: str = ""
    raw_color: str = ""
    quantity: int = 0
    lens: str = ""
    notes: str = ""
    explicit_color_profile: str = ""
    driver_color: str = ""
    passenger_color: str = ""
    center_color: str = ""
    placement_overrides: dict[str, Any] = field(default_factory=dict)
    # UI-only breakdown of the concrete SKUs this line represents (set by the
    # part picker). Shown as expandable children in the manifest, but NOT passed
    # to the planner/renderer — the build sheet sees only the simple parent line.
    components: list[dict[str, Any]] = field(default_factory=list)
    line_id: str = ""


@dataclass
class BuildDraft:
    """A saveable/resumable build entry created through the GUI."""
    draft_id: str
    created_at: str
    updated_at: str
    vehicle_info: dict[str, Any]
    parts: list[DraftPart] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)
    placement_overrides: dict[str, Any] = field(default_factory=dict)
    validation_messages: list[str] = field(default_factory=list)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)
    user_modified: bool = False


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def new_draft(
    vehicle_info: dict[str, Any] | None = None,
    parts: list[DraftPart] | None = None,
    notes: dict[str, list[str]] | None = None,
) -> BuildDraft:
    now = _utcnow()
    draft = BuildDraft(
        draft_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        vehicle_info=vehicle_info or {},
        parts=parts or [],
        notes=notes or {},
    )
    _ensure_line_ids(draft)
    return draft


def _ensure_line_ids(draft: BuildDraft) -> None:
    """Assign stable line IDs to any parts that lack one (e.g. loaded from old JSON)."""
    for part in draft.parts:
        if not part.line_id:
            part.line_id = str(uuid.uuid4())


def draft_from_project_input(project: ProjectInput, draft_id: str | None = None) -> BuildDraft:
    """Wrap an existing ProjectInput in a BuildDraft (e.g. after Excel upload)."""
    now = _utcnow()
    draft_parts = [
        DraftPart(
            name=p.name,
            include=p.include,
            new_or_used=p.new_or_used,
            source=p.source,
            manufacturer=p.manufacturer,
            part_number=p.part_number,
            location=p.location,
            raw_color=p.raw_color,
            quantity=p.quantity,
            lens=p.lens,
            notes=p.notes,
            explicit_color_profile=p.explicit_color_profile,
            driver_color=p.driver_color,
            passenger_color=p.passenger_color,
            center_color=p.center_color,
            line_id=str(uuid.uuid4()),
        )
        for p in project.parts
    ]
    return BuildDraft(
        draft_id=draft_id or str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        vehicle_info=dict(project.info),
        parts=draft_parts,
        notes=dict(project.notes),
    )


def find_part_by_line_id(draft: BuildDraft, line_id: str) -> tuple[int, DraftPart] | None:
    """Return (index, part) for the first part matching line_id, or None."""
    for i, part in enumerate(draft.parts):
        if part.line_id == line_id:
            return i, part
    return None


def draft_part_from_payload(body: dict, paths: AppPaths) -> DraftPart:  # noqa: ARG001
    """Build a DraftPart from an API request body; coerces field types."""
    name = _s(body.get("name", ""))
    include = _bool(body.get("include", True))
    quantity = max(0, _int(body.get("quantity", 0)))
    line_id = _s(body.get("line_id", ""))

    return DraftPart(
        name=name,
        include=include,
        new_or_used=_s(body.get("new_or_used", "")),
        source=_s(body.get("source", "")),
        manufacturer=_s(body.get("manufacturer", "")),
        part_number=_s(body.get("part_number", "")),
        location=_s(body.get("location", "")),
        raw_color=_s(body.get("raw_color", "")),
        quantity=quantity,
        lens=_s(body.get("lens", "")),
        notes=_s(body.get("notes", "")),
        explicit_color_profile=_s(body.get("explicit_color_profile", "")),
        driver_color=_s(body.get("driver_color", "")),
        passenger_color=_s(body.get("passenger_color", "")),
        center_color=_s(body.get("center_color", "")),
        placement_overrides=body.get("placement_overrides") if isinstance(body.get("placement_overrides"), dict) else {},
        components=body.get("components") if isinstance(body.get("components"), list) else [],
        line_id=line_id or str(uuid.uuid4()),
    )


def draft_to_project_input(draft: BuildDraft) -> ProjectInput:
    """Convert a BuildDraft into a ProjectInput suitable for the planner.

    Per-part placement_overrides are not passed to ProjectInput — the planner
    will receive them separately via the placement_overrides field on the draft
    when that feature is wired up in the renderer.
    """
    info = dict(draft.vehicle_info)
    # Ensure ProjectID and VehicleType are always present
    if "VehicleType" not in info or not info["VehicleType"]:
        info["VehicleType"] = "UNKNOWN"
    if "ProjectID" not in info or not info["ProjectID"]:
        raw_id = _s(info.get("QuoteNumber", "")) or _s(info.get("Agency", "Project"))
        info["ProjectID"] = safe_project_id(raw_id, fallback="PROJECT")

    parts = [
        PartInput(
            name=dp.name,
            include=dp.include,
            new_or_used=dp.new_or_used,
            source=dp.source,
            manufacturer=dp.manufacturer,
            part_number=dp.part_number,
            location=canonical_name(dp.location),
            raw_color=dp.raw_color,
            quantity=dp.quantity,
            lens=dp.lens,
            notes=dp.notes,
            explicit_color_profile=dp.explicit_color_profile,
            driver_color=dp.driver_color,
            passenger_color=dp.passenger_color,
            center_color=dp.center_color,
        )
        for dp in draft.parts
    ]
    return ProjectInput(info=info, parts=parts, notes=dict(draft.notes))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _draft_path(draft_id: str, drafts_dir: Path) -> Path:
    return drafts_dir / f"{draft_id}.json"


def save_draft(draft: BuildDraft, drafts_dir: Path) -> Path:
    """Persist draft to disk; updates updated_at timestamp.

    In cloud mode also mirrors the JSON to SharePoint /Drafts/ so other
    teammates' next sync pass picks it up. Mirror failure is logged but
    doesn't fail the save — the periodic sync loop retries.
    """
    _ensure_line_ids(draft)
    draft.updated_at = _utcnow()
    path = _draft_path(draft.draft_id, drafts_dir)
    LocalStorageProvider().write_text(str(path), json.dumps(asdict(draft), indent=2))
    # Fire-and-forget so the local save returns instantly. sync_work_data's
    # 60s timer is the safety net for any mirror that fails in the background.
    from ..app.services.shared_work_service import mirror_draft_to_cloud_in_background
    mirror_draft_to_cloud_in_background(draft.draft_id, path)
    return path


def _coerce_notes(raw) -> dict[str, list[str]]:
    """Migrate old list-of-str notes to the new dict[category, list[str]] format."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        items = [str(n).strip() for n in raw if n and str(n).strip()]
        return {"INSTALLATION NOTES": items} if items else {}
    return {}


def load_draft(draft_id: str, drafts_dir: Path) -> BuildDraft:
    """Load a draft by ID; raises FileNotFoundError if not found."""
    path = _draft_path(draft_id, drafts_dir)
    data = json.loads(LocalStorageProvider().read_text(str(path)))
    parts = [DraftPart(**p) for p in data.pop("parts", [])]
    data["notes"] = _coerce_notes(data.get("notes", {}))
    draft = BuildDraft(parts=parts, **data)
    _ensure_line_ids(draft)
    return draft


def delete_draft(draft_id: str, drafts_dir: Path) -> None:
    """Remove a draft file; raises FileNotFoundError if not found.

    Also removes the cloud mirror in cloud mode so teammates' next sync
    drops the draft from their workspace too.
    """
    LocalStorageProvider().delete(str(_draft_path(draft_id, drafts_dir)))
    from ..app.services.shared_work_service import delete_draft_from_cloud
    delete_draft_from_cloud(draft_id)


def list_drafts(drafts_dir: Path) -> list[BuildDraft]:
    """Return all drafts sorted newest-first by updated_at; silently skips corrupt files."""
    drafts = []
    for path in drafts_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            parts = [DraftPart(**p) for p in data.pop("parts", [])]
            data["notes"] = _coerce_notes(data.get("notes", {}))
            draft = BuildDraft(parts=parts, **data)
            _ensure_line_ids(draft)
            drafts.append(draft)
        except Exception:
            _log.exception("Skipping corrupt draft file: %s", path)
    drafts.sort(key=lambda d: d.updated_at, reverse=True)
    return drafts


def draft_summary(draft: BuildDraft) -> dict[str, Any]:
    """Lightweight dict suitable for a list-drafts API response."""
    info = draft.vehicle_info
    return {
        "draft_id": draft.draft_id,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "vehicle_type": info.get("VehicleType", ""),
        "agency": info.get("Agency", ""),
        "quote_number": info.get("QuoteNumber", ""),
        "parts_count": len(draft.parts),
        "validation_messages": draft.validation_messages,
    }
