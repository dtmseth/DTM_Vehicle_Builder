"""Draft QuickBooks Estimates from a vehicle's chosen parts.

This is the "create estimate" half of the QuickBooks bridge. An **Estimate**
is a non-posting QBO document — it does NOT hit the books, which is exactly
what makes it the right object for a reviewable draft ("draft without sending").
Converting an accepted estimate into an Invoice is a separate, explicit step.

Flow per vehicle (one IndividualUnit):
  1. Resolve the build draft's parts to QuickBooks line items. Each part must
     map to a catalog product that is QB-linked (carries qb_item_id), active,
     and priced. Anything that doesn't is a *problem*.
  2. If there are ANY problems, refuse to create the document and report them
     (the owner chose "block until all linked"). Nothing is sent to QBO.
  3. Otherwise ensure the per-vehicle job exists (qb_sync_service.push_vehicle_job
     creates the sub-customer under the agency Customer), build the Estimate
     payload, create it, and write qb_estimate_id back onto the unit.

``validate_estimate`` runs steps 1–2 only and touches no network, so the UI can
show exactly what's blocking before the owner ever connects or commits.

Like the rest of the integration, no item names, prices, customer data, or QB
response bodies are logged.
"""

from __future__ import annotations

import logging

from ...paths import AppPaths
from ..adapters.quickbooks.api_client import QuickBooksApiError
from . import qb_sync_service
from .parts_db_service import get_parts_db_service

logger = logging.getLogger(__name__)


# ── part → QuickBooks line resolution ────────────────────────────────────────


def _qb_fields(spec: dict) -> dict:
    """Pull the QB-owned fields off a product or part_number spec."""
    return {
        "qb_item_id": str(spec.get("qb_item_id", "")).strip(),
        "qb_sku": str(spec.get("qb_sku", "")),
        "qb_unit_price": spec.get("qb_unit_price"),
        "qb_inactive": bool(spec.get("qb_inactive")),
    }


def _resolution_index(paths: AppPaths) -> tuple[dict, dict, dict]:
    """Build (by_part_number, by_model, prod_qb) lookups from parts_db.

    QB linkage is resolved **per part number** — each ``part_numbers[]`` entry
    can carry its own ``qb_item_id`` / ``qb_unit_price`` (the SKU's price), which
    is what an estimate must bill. A part_number entry that lacks its own QB
    fields falls back to the product-level fields (the legacy one-to-one link
    the Settings → QuickBooks "Link" button writes), so both models work.

    - by_part_number: norm part number → resolved entry {product_id + qb fields}
    - by_model:       norm model string → product_id (last-resort match)
    - prod_qb:        product_id → product-level qb fields (for the model path)
    """
    doc = get_parts_db_service(paths).raw_doc()
    products = doc.get("products") or {}
    by_part_number: dict[str, dict] = {}
    by_model: dict[str, str] = {}
    prod_qb: dict[str, dict] = {}
    for pid, spec in products.items():
        spec = spec or {}
        prod_fields = _qb_fields(spec)
        prod_qb[pid] = prod_fields
        model = str(spec.get("model", "")).strip().lower()
        if model:
            by_model.setdefault(model, pid)
        for pn in spec.get("part_numbers") or []:
            num = str((pn or {}).get("part_number", "")).strip().lower()
            if not num:
                continue
            pn_fields = _qb_fields(pn or {})
            # part_number fields win; fall back to product-level where empty.
            entry = {
                "product_id": pid,
                "qb_item_id": pn_fields["qb_item_id"] or prod_fields["qb_item_id"],
                "qb_sku": pn_fields["qb_sku"] or prod_fields["qb_sku"],
                "qb_unit_price": (pn_fields["qb_unit_price"]
                                  if pn_fields["qb_unit_price"] is not None
                                  else prod_fields["qb_unit_price"]),
                "qb_inactive": (pn_fields["qb_inactive"] if "qb_inactive" in (pn or {})
                                else prod_fields["qb_inactive"]),
            }
            by_part_number.setdefault(num, entry)
    return by_part_number, by_model, prod_qb


def _resolve_part(draft_part, by_part_number, by_model, prod_qb) -> tuple[dict | None, str]:
    """Resolve one DraftPart to a billable line, or return (None, reason).

    reason is one of: no_catalog_match, not_linked, qb_inactive, no_price.
    """
    pn = (draft_part.part_number or "").strip().lower()
    entry = by_part_number.get(pn) if pn else None
    if entry is None:
        key = pn or (draft_part.name or "").strip().lower()
        pid = by_model.get(key)
        if pid:
            entry = {"product_id": pid, **prod_qb[pid]}
    if entry is None:
        return None, "no_catalog_match"

    if not entry["qb_item_id"]:
        return None, "not_linked"
    if entry["qb_inactive"]:
        return None, "qb_inactive"
    if entry["qb_unit_price"] is None:
        return None, "no_price"

    return {
        "product_id": entry["product_id"],
        "qb_item_id": entry["qb_item_id"],
        "qb_sku": entry["qb_sku"],
        "unit_price": float(entry["qb_unit_price"]),
    }, ""


def resolve_build_lines(paths: AppPaths, draft) -> tuple[list[dict], list[dict]]:
    """Split a build draft into (billable_lines, problems).

    Only included parts are considered. A part with quantity <= 0 bills as 1
    (these are physical parts installed on the vehicle — at least one each).
    """
    by_part_number, by_model, prod_qb = _resolution_index(paths)
    lines: list[dict] = []
    problems: list[dict] = []
    for dp in draft.parts:
        if not dp.include:
            continue
        resolved, reason = _resolve_part(dp, by_part_number, by_model, prod_qb)
        if reason:
            problems.append({
                "name": dp.name,
                "part_number": dp.part_number,
                "reason": reason,
            })
            continue
        qty = dp.quantity if (dp.quantity and dp.quantity > 0) else 1
        lines.append({
            **resolved,
            "name": dp.name,
            "qty": qty,
            "amount": round(resolved["unit_price"] * qty, 2),
        })
    return lines, problems


def _build_estimate_payload(customer_ref: str, lines: list[dict], *, memo: str = "") -> dict:
    """Assemble the QBO Estimate request body from resolved lines."""
    qb_lines = [
        {
            "DetailType": "SalesItemLineDetail",
            "Amount": ln["amount"],
            "Description": ln["name"],
            "SalesItemLineDetail": {
                "ItemRef": {"value": ln["qb_item_id"]},
                "Qty": ln["qty"],
                "UnitPrice": ln["unit_price"],
            },
        }
        for ln in lines
    ]
    payload: dict = {"CustomerRef": {"value": str(customer_ref)}, "Line": qb_lines}
    if memo:
        payload["CustomerMemo"] = {"value": memo}
    return payload


# ── load helper ───────────────────────────────────────────────────────────────


def _load_unit_draft(paths: AppPaths, project_id: str, individual_id: str):
    """Return (project, build_unit, unit, draft) or ({"error": ...},)-style dict.

    On success returns a 4-tuple; on failure returns a dict with ``error``.
    """
    from ...inputs import project_entry
    from ...inputs.project_drafts import load_draft

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}
    build_unit, unit = qb_sync_service._find_individual(project, individual_id)
    if unit is None:
        return {"ok": False, "error": "unknown_unit"}
    if not unit.draft_id:
        return {"ok": False, "error": "no_build"}
    try:
        draft = load_draft(unit.draft_id, paths.workspace_drafts_dir)
    except FileNotFoundError:
        return {"ok": False, "error": "no_build"}
    return project, build_unit, unit, draft


# ── public API ────────────────────────────────────────────────────────────────


def validate_estimate(paths: AppPaths, *, project_id: str, individual_id: str) -> dict:
    """Dry run: resolve the build and report whether an estimate can be created.

    No network, no writes. ``can_create`` is True only when there are billable
    lines and zero problems.
    """
    loaded = _load_unit_draft(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    _project, _build_unit, _unit, draft = loaded

    lines, problems = resolve_build_lines(paths, draft)
    total = round(sum(ln["amount"] for ln in lines), 2)
    return {
        "ok": True,
        "can_create": not problems and bool(lines),
        "line_count": len(lines),
        "total": total,
        "problems": problems,
    }


def create_estimate(paths: AppPaths, *, project_id: str, individual_id: str, memo: str = "") -> dict:
    """Create a QBO Estimate for one vehicle. Blocks if any part is unbillable.

    Ensures the vehicle's job exists first, then writes qb_estimate_id back.
    """
    loaded = _load_unit_draft(paths, project_id, individual_id)
    if isinstance(loaded, dict):
        return loaded
    project, _build_unit, unit, draft = loaded

    lines, problems = resolve_build_lines(paths, draft)
    if problems:
        return {"ok": False, "error": "validation_failed",
                "problems": problems, "line_count": len(lines)}
    if not lines:
        return {"ok": False, "error": "no_billable_parts"}

    # Ensure the per-vehicle job (sub-customer) exists to attach the estimate to.
    job_id = unit.qb_job_id
    if not job_id:
        jr = qb_sync_service.push_vehicle_job(paths, project_id, individual_id)
        if not jr.get("ok"):
            return jr
        job_id = jr["qb_job_id"]
        # Reload so we save onto the record that already carries qb_job_id.
        from ...inputs import project_entry
        project = project_entry.load_project(project_id, paths)
        _build_unit, unit = qb_sync_service._find_individual(project, individual_id)

    client, err = qb_sync_service._build_client(paths)
    if err:
        return err

    payload = _build_estimate_payload(job_id, lines, memo=memo)
    try:
        result = client.create_estimate(payload)
    except QuickBooksApiError as exc:
        logger.warning("QuickBooks estimate create failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    estimate_id = result.get("qb_estimate_id", "")
    unit.qb_estimate_id = estimate_id
    from ...inputs import project_entry
    project_entry.save_project(project, paths)
    total = round(sum(ln["amount"] for ln in lines), 2)
    logger.info("QB estimate created: %d lines", len(lines))
    return {
        "ok": True,
        "qb_estimate_id": estimate_id,
        "doc_number": result.get("doc_number", ""),
        "line_count": len(lines),
        "total": total,
    }


def create_estimates_batch(
    paths: AppPaths, *, project_id: str, individual_ids: list[str] | None = None, memo: str = ""
) -> dict:
    """Create estimates for several vehicles. Each is validated independently.

    Per the "block until all linked" rule, a vehicle with unbillable parts is
    skipped (reported under its result), not silently partial-billed; clean
    vehicles still go through. Returns per-unit results plus created/blocked
    counts.
    """
    from ...inputs import project_entry

    try:
        project = project_entry.load_project(project_id, paths)
    except FileNotFoundError:
        return {"ok": False, "error": "unknown_project"}

    wanted = set(individual_ids) if individual_ids else None
    targets = [
        ind.individual_id
        for bu in project.build_units
        for ind in bu.individuals
        if wanted is None or ind.individual_id in wanted
    ]

    results = []
    created = 0
    for ind_id in targets:
        res = create_estimate(paths, project_id=project_id, individual_id=ind_id, memo=memo)
        if res.get("ok"):
            created += 1
        results.append({"individual_id": ind_id, **res})

    return {
        "ok": True,
        "created": created,
        "blocked": len(results) - created,
        "results": results,
    }
