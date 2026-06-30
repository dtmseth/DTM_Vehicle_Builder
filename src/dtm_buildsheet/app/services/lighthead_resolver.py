"""Resolve a tracer (and, later, lightbar) head-parent product into concrete
housings + lighthead SKUs from a simple Duo/Trio + secondary-color choice.

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
