"""Resolve configurable lighthead products into concrete QB line items.

The user picks only **Standard Duo / Standard Trio** and a **White/Amber**
secondary color; this turns that into the exact housing SKUs and per-slot head
SKUs with quantities, following the locked rules in
``docs/PARTS_DB_AND_PICKER.md``:

- slot count = housing lamp count; slot 1 = a **primary** head, slots 2..N
  **secondary** (cheaper, no lamp driver);
- **Duo** head = one warning color (red=driver / blue=passenger) + secondary;
  **Trio** head = red + blue + secondary (same every slot);
- **2-lamp** → one front housing, slot 1 driver(red) / slot 2 passenger(blue);
- **3/5/6-lamp** → a driver+passenger **pair** of housings (doubled heads).

Pure: takes the parts_db doc + choices, returns a structured plan. A missing
head SKU becomes a ``problem`` rather than an exception, so the UI can show
"can't build this combo yet" instead of breaking.
"""

from __future__ import annotations

import re

_LAMP_RE = re.compile(r"(\d+)\s*[- ]?\s*lamp", re.IGNORECASE)
_INNER_EDGE_LAMP_RE = re.compile(r"\b(\d+)\s*-?\s*(?:lt|lamp)\b", re.IGNORECASE)


def _lamp_count(housing: dict) -> int:
    """Lamp/slot count parsed from the housing model (e.g. 'Tracer 5-Lamp')."""
    m = _LAMP_RE.search(str(housing.get("model", "")))
    return int(m.group(1)) if m else 0


def _sku_colors(pn: dict) -> set[str]:
    """The non-empty color set a head SKU emits (order-independent)."""
    return {c for c in (pn.get("color"), pn.get("secondary_color"),
                        pn.get("tertiary_color")) if c}


def _classify_role(product: dict, pid: str) -> str:
    """primary | secondary | '' — from the head product's model or id."""
    hay = f"{product.get('model', '')} {pid}".lower()
    if "primary" in hay:
        return "primary"
    if "secondary" in hay:
        return "secondary"
    return ""


def _head_products(db: dict, housing: dict) -> dict[str, tuple[str, dict]]:
    """Return {role: (product_id, product)} for the housing's lighthead accessories."""
    products = db.get("products") or {}
    out: dict[str, tuple[str, dict]] = {}
    for acc in housing.get("accessories") or []:
        if acc.get("category") != "lighthead":
            continue
        pid = acc.get("product_id")
        prod = products.get(pid)
        if not prod:
            continue
        role = _classify_role(prod, pid)
        if role:
            out[role] = (pid, prod)
    return out


def _desired_colors(mode: str, side: str, secondary_color: str) -> set[str]:
    """Colors a head must emit for this mode/side/secondary choice."""
    if mode == "trio":
        return {"red", "blue", secondary_color}
    warn = "red" if side == "driver" else "blue"          # duo split
    return {warn, secondary_color}


def _find_head(product: dict, desired: set[str], lens: str) -> dict | None:
    """First part_number in ``product`` whose color set + lens match (prefer
    a real QB SKU over a pending one)."""
    matches = [pn for pn in (product.get("part_numbers") or [])
               if _sku_colors(pn) == desired and (pn.get("lens_type") or "clear") == lens]
    if not matches:
        return None
    matches.sort(key=lambda pn: bool(pn.get("qb_pending")))   # real first, pending last
    return matches[0]


def _part_number(product: dict, sku: str) -> dict | None:
    """Return the exact selected product SKU (case-insensitive)."""
    wanted = (sku or "").strip().upper()
    return next(
        (pn for pn in (product.get("part_numbers") or [])
         if str(pn.get("part_number", "")).strip().upper() == wanted),
        None,
    )


def _inner_edge_lamp_count(housing_sku: dict) -> int:
    """Read an Inner Edge's physical head count from its sales description.

    FST/RST models are deliberately generic (``Inner Edge FST`` / ``RST``),
    while the exact QB SKU tells us whether this is a 4-, 5-, 8-, 10-, or
    12-light assembly.  QB's imported descriptions use both ``10-LT`` and
    ``10 LAMP``, so inspect every user-facing source in priority order.
    """
    for field in ("qb_sales_description", "friendly_name", "description", "part_number"):
        match = _INNER_EDGE_LAMP_RE.search(str(housing_sku.get(field, "")))
        if match:
            return int(match.group(1))
    return 0


def _inner_edge_head_product(db: dict, housing: dict) -> tuple[str, dict] | None:
    """Return the one non-primary/non-secondary Inner Edge head product."""
    products = db.get("products") or {}
    for accessory in housing.get("accessories") or []:
        if accessory.get("category") != "lighthead":
            continue
        product_id = accessory.get("product_id")
        product = products.get(product_id)
        if product:
            return product_id, product
    return None


def resolve_tracer(db: dict, housing_id: str, *, mode: str,
                   secondary_color: str = "white", lens: str = "clear") -> dict:
    """Resolve a tracer housing + Duo/Trio + secondary color into a build plan.

    Returns ``{ok, mode, secondary_color, lens, lamp_count, housings:[...],
    lines:[...], problems:[...]}``. ``lines`` is the flat housing+head list (qty
    rolled up) for the estimate/manifest; ``housings`` keeps the per-side,
    per-slot structure for display.
    """
    products = db.get("products") or {}
    housing = products.get(housing_id)
    if housing is None:
        return {"ok": False, "error": "unknown_housing", "housings": [], "lines": [], "problems": []}

    mode = (mode or "").lower()
    if mode not in ("duo", "trio"):
        return {"ok": False, "error": "bad_mode", "housings": [], "lines": [], "problems": []}
    secondary_color = (secondary_color or "white").lower()
    lens = (lens or "clear").lower()

    n = _lamp_count(housing)
    if n < 1:
        return {"ok": False, "error": "no_lamp_count", "housings": [], "lines": [], "problems": []}
    housing_sku = next((pn.get("part_number") for pn in (housing.get("part_numbers") or [])
                        if pn.get("part_number")), "")

    roles = _head_products(db, housing)
    problems: list[dict] = []
    if "primary" not in roles or "secondary" not in roles:
        problems.append({"reason": "missing_head_products",
                         "detail": f"housing {housing_id} needs both primary and secondary lighthead accessories"})

    def _slot(role: str, side: str) -> dict:
        """Resolve one head slot to a SKU (or a problem placeholder)."""
        desired = _desired_colors(mode, side, secondary_color)
        entry = roles.get(role)
        sku_pn = _find_head(entry[1], desired, lens) if entry else None
        if sku_pn is None:
            problems.append({"reason": "missing_head_sku", "role": role, "side": side,
                             "colors": sorted(desired), "lens": lens})
            return {"role": role, "side": side, "product_id": entry[0] if entry else "",
                    "sku": "", "colors": sorted(desired), "lens": lens, "missing": True}
        return {"role": role, "side": side, "product_id": entry[0],
                "sku": sku_pn.get("part_number", ""), "colors": sorted(desired), "lens": lens,
                "pending": bool(sku_pn.get("qb_pending"))}

    housings: list[dict] = []
    if n == 2:
        # Single front housing: slot 1 driver(primary), slot 2 passenger(secondary).
        housings.append({
            "side": "front", "product_id": housing_id, "sku": housing_sku, "qty": 1,
            "heads": [_slot("primary", "driver"), _slot("secondary", "passenger")],
        })
    else:
        # Running-board pair: one housing per side, 1 primary + (N-1) secondary.
        for side in ("driver", "passenger"):
            heads = [_slot("primary", side)]
            sec = _slot("secondary", side)
            sec = {**sec, "qty": n - 1}
            heads.append(sec)
            housings.append({"side": side, "product_id": housing_id, "sku": housing_sku,
                             "qty": 1, "heads": heads})

    # Flatten to estimate/manifest lines with rolled-up quantities.
    counts: dict[tuple, dict] = {}
    for h in housings:
        key = ("housing", h["product_id"], h["sku"])
        counts.setdefault(key, {"kind": "housing", "product_id": h["product_id"],
                                "sku": h["sku"], "qty": 0})["qty"] += h["qty"]
        for hd in h["heads"]:
            if hd.get("missing"):
                continue
            qty = hd.get("qty", 1)
            key = ("head", hd["product_id"], hd["sku"])
            counts.setdefault(key, {"kind": "head", "product_id": hd["product_id"],
                                    "sku": hd["sku"], "role": hd["role"],
                                    "colors": hd["colors"], "lens": hd["lens"],
                                    "pending": hd.get("pending", False), "qty": 0})["qty"] += qty
    lines = list(counts.values())

    return {
        "ok": not problems,
        "mode": mode, "secondary_color": secondary_color, "lens": lens,
        "lamp_count": n, "housings": housings, "lines": lines, "problems": problems,
    }


def resolve_inner_edge(
    db: dict,
    housing_id: str,
    *,
    housing_part_number: str,
    mode: str,
    secondary_color: str = "white",
) -> dict:
    """Resolve one FST/RST Inner Edge SKU into its concrete QB head lines.

    Inner Edges differ from Tracers in two important ways: the selected
    FST/RST SKU itself determines the *total* head count, and every head is the
    same Inner Edge head product (there are no primary/secondary roles).  Duo
    configurations remain red/secondary on the driver half and blue/secondary
    on the passenger half; Trio uses one red/blue/secondary SKU throughout.

    The result intentionally has no opinion on an FST's visual coverage (both,
    driver-only, passenger-only).  That is a rendering choice; the selected
    QB SKU remains the authoritative billed head count.
    """
    products = db.get("products") or {}
    housing = products.get(housing_id)
    if housing is None:
        return {"ok": False, "error": "unknown_housing", "housings": [], "lines": [], "problems": []}
    if housing_id not in {"whelen_fst", "whelen_rst"}:
        return {"ok": False, "error": "not_inner_edge", "housings": [], "lines": [], "problems": []}

    mode = (mode or "").lower()
    if mode not in ("duo", "trio"):
        return {"ok": False, "error": "bad_mode", "housings": [], "lines": [], "problems": []}
    secondary_color = (secondary_color or "white").lower()

    housing_sku = _part_number(housing, housing_part_number)
    if housing_sku is None:
        return {"ok": False, "error": "unknown_housing_sku", "housings": [], "lines": [], "problems": []}
    lamp_count = _inner_edge_lamp_count(housing_sku)
    if lamp_count < 1:
        return {"ok": False, "error": "no_lamp_count", "housings": [], "lines": [], "problems": []}

    head_entry = _inner_edge_head_product(db, housing)
    problems: list[dict] = []
    if head_entry is None:
        problems.append({"reason": "missing_head_product", "detail": f"housing {housing_id} has no Inner Edge lighthead accessory"})
        head_product_id, head_product = "", {}
    else:
        head_product_id, head_product = head_entry

    # Preserve an odd SKU's full selected count: the extra Duo head goes on
    # the driver half, matching the visual layout's right-hand group.
    desired_groups: list[tuple[str, set[str], int]]
    if mode == "duo":
        passenger_count = lamp_count // 2
        desired_groups = [
            ("driver", {"red", secondary_color}, lamp_count - passenger_count),
            ("passenger", {"blue", secondary_color}, passenger_count),
        ]
    else:
        desired_groups = [("all", {"red", "blue", secondary_color}, lamp_count)]

    heads: list[dict] = []
    for side, colors, qty in desired_groups:
        if qty < 1:
            continue
        sku = _find_head(head_product, colors, "clear") if head_entry else None
        if sku is None:
            problems.append({
                "reason": "missing_head_sku", "side": side,
                "colors": sorted(colors), "lens": "clear",
            })
            heads.append({
                "side": side, "product_id": head_product_id, "sku": "",
                "colors": sorted(colors), "qty": qty, "lens": "clear", "missing": True,
            })
            continue
        heads.append({
            "side": side, "product_id": head_product_id,
            "sku": sku.get("part_number", ""), "colors": sorted(colors), "qty": qty,
            "lens": "clear", "pending": bool(sku.get("qb_pending")),
        })

    housing_line = {
        "kind": "housing", "product_id": housing_id,
        "sku": housing_sku.get("part_number", ""), "qty": 1,
    }
    lines: list[dict] = [housing_line]
    for head in heads:
        if head.get("missing"):
            continue
        lines.append({
            "kind": "head", "product_id": head["product_id"], "sku": head["sku"],
            "side": head["side"], "colors": head["colors"], "lens": head["lens"],
            "pending": head.get("pending", False), "qty": head["qty"],
        })

    return {
        "ok": not problems,
        "mode": mode, "secondary_color": secondary_color, "lamp_count": lamp_count,
        "housings": [{
            "product_id": housing_id, "sku": housing_line["sku"], "qty": 1, "heads": heads,
        }],
        "lines": lines, "problems": problems,
    }


def _outer_edge_pillar_mode(housing_sku: dict) -> str:
    """Read the fixed Duo/Trio construction from an Outer Edge pillar SKU."""
    for field in ("qb_sales_description", "friendly_name", "description", "part_number"):
        text = str(housing_sku.get(field, "")).lower()
        if "trio" in text:
            return "trio"
        if "duo" in text:
            return "duo"
    return ""


def _outer_edge_pillar_head_product(db: dict, housing: dict) -> tuple[str, dict] | None:
    """Return the explicit included-ION product for an Outer Edge pillar."""
    products = db.get("products") or {}
    for accessory in housing.get("accessories") or []:
        if accessory.get("category") != "lighthead":
            continue
        product_id = str(accessory.get("product_id") or "")
        product = products.get(product_id)
        if product:
            return product_id, product
    return None


def resolve_outer_edge_pillar(
    db: dict,
    housing_id: str,
    *,
    housing_part_number: str,
    secondary_color: str = "white",
) -> dict:
    """Resolve an Outer Edge rear-pillar housing to its six included IONs.

    The selected housing determines whether it is a Duo or Trio.  Duo is the
    standard, balanced rear-pillar split: three red/secondary IONs and three
    blue/secondary IONs. Trio is fixed by Whelen's assembly definition to six
    identical red/blue/amber IONs.  The ION rows are separate nested QB lines,
    while the housing itself remains a single billed row.
    """
    products = db.get("products") or {}
    housing = products.get(housing_id)
    if housing is None:
        return {"ok": False, "error": "unknown_housing", "housings": [], "lines": [], "problems": []}
    if housing_id != "whelen_ion_rear_pillar":
        return {"ok": False, "error": "not_outer_edge_pillar", "housings": [], "lines": [], "problems": []}

    housing_sku = _part_number(housing, housing_part_number)
    if housing_sku is None:
        return {"ok": False, "error": "unknown_housing_sku", "housings": [], "lines": [], "problems": []}
    mode = _outer_edge_pillar_mode(housing_sku)
    if mode not in {"duo", "trio"}:
        return {"ok": False, "error": "unknown_housing_mode", "housings": [], "lines": [], "problems": []}

    # Trio is a fixed R/B/A housing. Duo may use the normal white or amber
    # secondary color, both of which have real included-ION SKUs in the DB.
    secondary_color = "amber" if mode == "trio" else (secondary_color or "white").lower()
    if secondary_color not in {"white", "amber"}:
        return {"ok": False, "error": "bad_secondary_color", "housings": [], "lines": [], "problems": []}

    head_entry = _outer_edge_pillar_head_product(db, housing)
    problems: list[dict] = []
    if head_entry is None:
        problems.append({
            "reason": "missing_head_product",
            "detail": f"housing {housing_id} has no included Outer Edge ION accessory",
        })
        head_product_id, head_product = "", {}
    else:
        head_product_id, head_product = head_entry

    desired_groups = (
        [("driver", {"red", secondary_color}, 3), ("passenger", {"blue", secondary_color}, 3)]
        if mode == "duo"
        else [("all", {"red", "blue", "amber"}, 6)]
    )
    heads: list[dict] = []
    for side, colors, qty in desired_groups:
        sku = _find_head(head_product, colors, "clear") if head_entry else None
        if sku is None:
            problems.append({
                "reason": "missing_head_sku", "side": side,
                "colors": sorted(colors), "lens": "clear",
            })
            heads.append({
                "side": side, "product_id": head_product_id, "sku": "",
                "colors": sorted(colors), "qty": qty, "lens": "clear", "missing": True,
            })
            continue
        heads.append({
            "side": side, "product_id": head_product_id,
            "sku": sku.get("part_number", ""), "colors": sorted(colors), "qty": qty,
            "lens": "clear", "pending": bool(sku.get("qb_pending")),
        })

    housing_line = {
        "kind": "housing", "product_id": housing_id,
        "sku": housing_sku.get("part_number", ""), "qty": 1,
    }
    lines: list[dict] = [housing_line]
    lines.extend({
        "kind": "head", "product_id": head["product_id"], "sku": head["sku"],
        "side": head["side"], "colors": head["colors"], "lens": head["lens"],
        "pending": head.get("pending", False), "qty": head["qty"],
    } for head in heads if not head.get("missing"))
    return {
        "ok": not problems,
        "mode": mode, "secondary_color": secondary_color, "lamp_count": 6,
        "housings": [{
            "product_id": housing_id, "sku": housing_line["sku"], "qty": 1, "heads": heads,
        }],
        "lines": lines, "problems": problems,
    }
