"""Save/resume build drafts for GUI-first build entry.

A BuildDraft is richer than ProjectInput: it carries per-build placement
overrides, validation messages, and an audit trail so a user can come back to
an in-progress build, see what changed, and generate from the current state.

Draft files live in workspace/drafts/{draft_id}.json.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain.input_models import PartInput, ProjectInput
from ..domain.supply import (
    normalize_component_supply_dict,
    normalize_supply_dict,
    normalized_supply_fields,
    supply_validation_error,
)
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
    supply_type: str = ""
    customer_condition: str = ""
    customer_source: str = ""
    manufacturer: str = ""
    part_number: str = ""
    location: str = ""
    raw_color: str = ""
    quantity: int = 0
    lens: str = ""
    notes: str = ""
    # A user-authored note that must be shown in the build manifest.  Technical
    # picker details continue to live in ``notes`` so the two do not overwrite
    # one another when a part is edited.
    comment: str = ""
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
    # Set on accessory lines (lighthead/bracket/cable) added with a primary part;
    # equals the parent part's line_id. Used to nest in the manifest and to
    # cascade-delete. Empty for ordinary top-level parts.
    parent_line_id: str = ""
    # A lifecycle-only dependency on another top-level part.  Unlike
    # parent_line_id this part remains a normal manifest/planner line, but is
    # removed when the linked parent is removed (for example, IONs included in
    # a Westin bumper light channel).
    linked_parent_line_id: str = ""
    # On accessory lines: the accessory_category and the PARENT product_id, so the
    # manifest can offer a category-scoped swap dropdown when editing one.
    accessory_category: str = ""
    accessory_parent_product: str = ""
    # part_type_id the picker resolved this line to (picker-created parts only;
    # empty for legacy/flat-modal parts). Drives the browse-tree manifest
    # highlight and allows the planner to resolve descriptive picker line
    # names without falling back to legacy workbook naming.
    part_type: str = ""
    # Full picker configuration snapshot written by _pickerDoAdd for every
    # picker-created part (PICKER_REDESIGN.md Step 6). Allows _pickerOpenEdit
    # to reconstruct the exact UI state the user left — mode, colors-per-head,
    # per-head colors, per-head SKU choices, count, lens. Parts saved before
    # this field existed (and legacy flat-modal parts) have an empty dict →
    # the editor derives what it can from components/colors as a fallback.
    # This is generally draft-local.  A configured physical product may also
    # carry a narrowly-scoped rendering directive here (currently Inner Edge
    # FST/RST coverage), so the build sheet matches its saved picker choice.
    picker_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildDraft:
    """A saveable/resumable build entry created through the GUI."""
    draft_id: str
    created_at: str
    updated_at: str
    vehicle_info: dict[str, Any]
    parts: list[DraftPart] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)
    # Copied from the containing project.  It is intentionally separate from
    # ``notes`` so changing project-wide instructions does not modify unit
    # notes, and vice versa.
    project_notes: str = ""
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
    project_notes: str = "",
) -> BuildDraft:
    now = _utcnow()
    draft = BuildDraft(
        draft_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        vehicle_info=vehicle_info or {},
        parts=parts or [],
        notes=notes or {},
        project_notes=_s(project_notes),
    )
    _ensure_line_ids(draft)
    return draft


def _ensure_line_ids(draft: BuildDraft) -> None:
    """Assign stable line IDs to any parts that lack one (e.g. loaded from old JSON)."""
    for part in draft.parts:
        if not part.line_id:
            part.line_id = str(uuid.uuid4())


_NUMBERED_NAME = re.compile(r"^(.*?)\s+(\d+)\s*$")
_CONTROL_HEAD_NAME = re.compile(r"^control head(?:\s+\d+)?$", re.IGNORECASE)


def _rename_part_and_children(draft: BuildDraft, part: DraftPart, new_name: str) -> None:
    """Rename one top-level part and retain its accessory display prefix."""
    if part.name == new_name:
        return
    old_name = part.name
    part.name = new_name
    for child in draft.parts:
        if getattr(child, "parent_line_id", "") == part.line_id and child.name.startswith(old_name + " · "):
            child.name = new_name + child.name[len(old_name):]


def _is_control_head(part: DraftPart) -> bool:
    """Recognize picker-shaped and legacy control-head draft rows."""
    return part.part_type == "control_head" or bool(_CONTROL_HEAD_NAME.fullmatch((part.name or "").strip()))


def renumber_parts(draft: BuildDraft) -> None:
    """Normalize top-level names after draft mutations.

    Ordinary numbered names run 1..n with no gaps (for example after deleting
    "Forward Warning 2", "...3" becomes "...2"). Control heads are different:
    one is the unnumbered "Control Head", while two or more are numbered in
    draft order so their manifest entries stay distinct.

    Only top-level parts (no parent_line_id) are renumbered; accessory child
    lines follow their parent's name, so when a parent is renumbered its
    children's "<parent> · <accessory>" prefix is updated to match.
    """
    groups: dict[str, list] = {}
    control_heads: list[DraftPart] = []
    for p in draft.parts:
        if getattr(p, "parent_line_id", ""):
            continue
        if _is_control_head(p):
            control_heads.append(p)
            continue
        m = _NUMBERED_NAME.match(p.name or "")
        if m:
            groups.setdefault(m.group(1).strip(), []).append(p)

    if control_heads:
        for index, part in enumerate(control_heads, 1):
            name = "Control Head" if len(control_heads) == 1 else f"Control Head {index}"
            _rename_part_and_children(draft, part, name)

    for base, plist in groups.items():
        plist.sort(key=lambda p: int(_NUMBERED_NAME.match(p.name).group(2)))
        for i, p in enumerate(plist, 1):
            new_name = f"{base} {i}"
            _rename_part_and_children(draft, p, new_name)


def draft_from_project_input(project: ProjectInput, draft_id: str | None = None) -> BuildDraft:
    """Wrap an existing ProjectInput in a BuildDraft (e.g. after Excel upload)."""
    now = _utcnow()
    draft_parts = [
        DraftPart(
            name=p.name,
            include=p.include,
            new_or_used=p.new_or_used,
            source=p.source,
            supply_type=p.supply_type,
            customer_condition=p.customer_condition,
            customer_source=p.customer_source,
            manufacturer=p.manufacturer,
            part_number=p.part_number,
            location=p.location,
            raw_color=p.raw_color,
            quantity=p.quantity,
            lens=p.lens,
            notes=p.notes,
            comment=getattr(p, "comment", ""),
            explicit_color_profile=p.explicit_color_profile,
            driver_color=p.driver_color,
            passenger_color=p.passenger_color,
            center_color=p.center_color,
            components=list(getattr(p, "components", []) or []),
            # This conversion is also used by the preview/build-sheet path.
            # Keep picker metadata, not just display fields: configured
            # assemblies (for example Outer Edge) depend on it for rendering.
            part_type=getattr(p, "part_type", ""),
            picker_config=dict(getattr(p, "picker_config", {}) or {}),
            line_id=getattr(p, "line_id", "") or str(uuid.uuid4()),
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


def draft_part_from_payload(
    body: dict, paths: AppPaths, *, require_complete_supply: bool = False,
) -> DraftPart:  # noqa: ARG001
    """Build a DraftPart from an API request body; coerces field types."""
    name = _s(body.get("name", ""))
    include = _bool(body.get("include", True))
    quantity = max(0, _int(body.get("quantity", 0)))
    line_id = _s(body.get("line_id", ""))

    if require_complete_supply and "supply_type" in body:
        error = supply_validation_error(body)
        if error:
            raise ValueError(error)
        for component in body.get("components") or []:
            if isinstance(component, dict) and "supply_type" in component:
                error = supply_validation_error(component)
                if error:
                    label = _s(component.get("label") or component.get("name")) or "System component"
                    raise ValueError(f"{label}: {error}")

    supply = normalized_supply_fields(body)
    components = body.get("components") if isinstance(body.get("components"), list) else []
    normalized_components = [
        normalize_component_supply_dict(component) if isinstance(component, dict) else component
        for component in components
    ]
    return DraftPart(
        name=name,
        include=include,
        new_or_used=supply["new_or_used"],
        source=supply["source"],
        supply_type=supply["supply_type"],
        customer_condition=supply["customer_condition"],
        customer_source=supply["customer_source"],
        manufacturer=_s(body.get("manufacturer", "")),
        part_number=_s(body.get("part_number", "")),
        location=_s(body.get("location", "")),
        raw_color=_s(body.get("raw_color", "")),
        quantity=quantity,
        lens=_s(body.get("lens", "")),
        notes=_s(body.get("notes", "")),
        comment=_s(body.get("comment", "")),
        explicit_color_profile=_s(body.get("explicit_color_profile", "")),
        driver_color=_s(body.get("driver_color", "")),
        passenger_color=_s(body.get("passenger_color", "")),
        center_color=_s(body.get("center_color", "")),
        placement_overrides=body.get("placement_overrides") if isinstance(body.get("placement_overrides"), dict) else {},
        components=normalized_components,
        line_id=line_id or str(uuid.uuid4()),
        parent_line_id=_s(body.get("parent_line_id", "")),
        linked_parent_line_id=_s(body.get("linked_parent_line_id", "")),
        accessory_category=_s(body.get("accessory_category", "")),
        accessory_parent_product=_s(body.get("accessory_parent_product", "")),
        part_type=_s(body.get("part_type", "")),
        picker_config=body.get("picker_config") if isinstance(body.get("picker_config"), dict) else {},
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

    parts: list[PartInput] = []
    for dp in draft.parts:
        supply = normalized_supply_fields(dp)
        parts.append(PartInput(
            name=dp.name,
            include=dp.include,
            new_or_used=supply["new_or_used"],
            source=supply["source"],
            supply_type=supply["supply_type"],
            customer_condition=supply["customer_condition"],
            customer_source=supply["customer_source"],
            manufacturer=dp.manufacturer,
            part_number=dp.part_number,
            location=canonical_name(dp.location),
            raw_color=dp.raw_color,
            quantity=dp.quantity,
            lens=dp.lens,
            notes=dp.notes,
            comment=dp.comment,
            explicit_color_profile=dp.explicit_color_profile,
            driver_color=dp.driver_color,
            passenger_color=dp.passenger_color,
            center_color=dp.center_color,
            line_id=dp.line_id,
            part_type=dp.part_type,
            parent_line_id=dp.parent_line_id,
            linked_parent_line_id=dp.linked_parent_line_id,
            accessory_category=dp.accessory_category,
            accessory_parent_product=dp.accessory_parent_product,
            components=list(dp.components or []),
            picker_config=dict(dp.picker_config or {}),
        ))
    notes = dict(draft.notes)
    if draft.project_notes:
        notes["PROJECT-WIDE NOTES"] = [draft.project_notes]
    return ProjectInput(info=info, parts=parts, notes=notes)


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


def _normalize_saved_part(raw: dict[str, Any]) -> dict[str, Any]:
    """Load old draft JSON into the canonical supply shape without writing it."""
    part = normalize_supply_dict(raw)
    components = part.get("components")
    if isinstance(components, list):
        part["components"] = [
            normalize_component_supply_dict(component) if isinstance(component, dict) else component
            for component in components
        ]
    return part


def load_draft(draft_id: str, drafts_dir: Path) -> BuildDraft:
    """Load a draft by ID; raises FileNotFoundError if not found."""
    path = _draft_path(draft_id, drafts_dir)
    data = json.loads(LocalStorageProvider().read_text(str(path)))
    parts = [DraftPart(**_normalize_saved_part(p)) for p in data.pop("parts", [])]
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
            parts = [DraftPart(**_normalize_saved_part(p)) for p in data.pop("parts", [])]
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
