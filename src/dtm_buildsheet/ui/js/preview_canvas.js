// ═══════════════════════════════════════════════════════
// PREVIEW CANVAS  — Visual build preview with overrides
// ═══════════════════════════════════════════════════════

// ── state ────────────────────────────────────────────────
let _pvDraftId          = null;   // draft UUID from parse response
let _pvPlan             = null;   // last response from /api/preview/plan
let _pvView             = "front";// active view tab
let _pvInspKey          = null;   // override_key currently open in inspector
let _pvInspPl           = null;   // placement object open in inspector
let _pvInspPp           = null;   // part object open in inspector
let _pvDrag             = null;   // active drag state (see pvDragStart)
let _pvPendingOverrides = {};     // {override_key: overrideDict} — not yet sent to server

// ── public API ───────────────────────────────────────────

async function pvLoad(draftId) {
  _pvDraftId          = draftId;
  _pvPlan             = null;
  _pvPendingOverrides = {};
  _pvInspKey          = null;
  _pvInspPl           = null;
  _pvInspPp           = null;

  pvShowSpinner(true);
  pvHideInspector();
  pvUpdateBadge();

  const res = await api("/api/preview/plan", { draft_id: draftId });

  pvShowSpinner(false);

  if (!res.ok) {
    pvShowError(res.error || "Preview failed");
    return;
  }

  _pvPlan = res;
  pvBuildViewTabs(res.views);
  pvSelectView(_pvView in res.views ? _pvView : Object.keys(res.views)[0]);
}

function pvSelectView(viewName) {
  _pvView = viewName;
  document.querySelectorAll(".pv-view-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === viewName)
  );
  pvRenderView(viewName);
}

// ── render ───────────────────────────────────────────────

function pvBuildViewTabs(views) {
  const bar = $("pv-view-tabs");
  bar.innerHTML = Object.entries(views).map(([key, v]) =>
    `<button class="pv-view-tab${key === _pvView ? " active" : ""}" data-view="${esc(key)}">${esc(v.label)}</button>`
  ).join("");
  bar.querySelectorAll(".pv-view-tab").forEach(t =>
    t.addEventListener("click", () => pvSelectView(t.dataset.view))
  );
}

function pvRenderView(viewName) {
  const container = $("pv-canvas-wrap");
  container.innerHTML = "";

  if (!_pvPlan) return;

  const viewMeta = _pvPlan.views[viewName];
  if (!viewMeta) return;

  const frame = document.createElement("div");
  frame.className = "pv-frame";

  const bg = document.createElement("img");
  bg.className = "pv-bg";
  bg.alt = viewMeta.label;
  bg.draggable = false;
  bg.onerror = () => { bg.style.display = "none"; frame.style.background = "#dde0ec"; };
  bg.src = viewMeta.bg_url;
  frame.appendChild(bg);

  const partsForView = (_pvPlan.planned_parts || []).filter(pp =>
    pp.placements.some(pl => pl.view === viewName)
  );

  for (const pp of partsForView) {
    for (const pl of pp.placements) {
      if (pl.view !== viewName) continue;

      const pendingOv = _pvPendingOverrides[pl.override_key];
      if (pendingOv) {
        if (pendingOv.visible === false) continue;
        pvRenderPlacement(frame, pp, pvMergeOverride(pl, pendingOv));
      } else {
        pvRenderPlacement(frame, pp, pl);
      }
    }
  }

  container.appendChild(frame);
}

// ── slot positioning ─────────────────────────────────────

function pvSlotPositions(pl) {
  // Returns [{xPct, yPct}] — percentages of frame dimensions, one per instance slot.
  const anchor = pl.anchor || {};
  const baseCx = (anchor.x || 0) * 100;
  const baseCy = (anchor.y || 0) * 100;
  const pattern = pl.pattern || "single";
  const count   = pl.slot_count || 1;

  // h_spacing: "icon_width" means multiples of icon width; "relative_image" means fraction of container.
  const rawSpacing = pl.h_spacing;
  let spacingPct;
  if (pl.h_spacing_units === "icon_width") {
    const iconWPct = (pl.icon_w_pct || 0.04) * 100;
    spacingPct = (rawSpacing != null && rawSpacing > 0) ? iconWPct * rawSpacing : iconWPct;
  } else {
    spacingPct = (rawSpacing != null && rawSpacing > 0) ? rawSpacing * 100 : 6;
  }

  function computeAll(n) {
    if (n <= 1 || pattern === "single") return [{ xPct: baseCx, yPct: baseCy }];

    if (pattern === "horizontal") {
      const totalW = spacingPct * (n - 1);
      const startX = baseCx - totalW / 2;
      return Array.from({ length: n }, (_, i) => ({ xPct: startX + i * spacingPct, yPct: baseCy }));
    }

    if (pattern === "mirror") {
      const centerX   = 50;
      const rawOffset = Math.abs(baseCx - centerX);
      // When the anchor sits exactly at center (e.g. co_part_rule forced pattern=mirror
      // on a location whose x=0.5), fall back to h_spacing/2 so slots don't overlap.
      const offsetX   = rawOffset > 0.1 ? rawOffset : spacingPct / 2;
      if (n === 2) return [
        { xPct: centerX - offsetX, yPct: baseCy },
        { xPct: centerX + offsetX, yPct: baseCy },
      ];
      const half = Math.floor(n / 2);
      const positions = [];
      for (let i = 0; i < half; i++) {
        const off = offsetX + i * spacingPct;
        positions.push({ xPct: centerX - off, yPct: baseCy });
        positions.push({ xPct: centerX + off, yPct: baseCy });
      }
      return positions;
    }

    return [{ xPct: baseCx, yPct: baseCy }];
  }

  // slot_indices: compute the full position_slot_count grid, then pick only the indexed slots.
  if (pl.position_slot_count && pl.slot_indices && pl.slot_indices.length > 0) {
    const all = computeAll(pl.position_slot_count);
    return pl.slot_indices.map(i => all[i] || { xPct: baseCx, yPct: baseCy });
  }

  return computeAll(count);
}

// ── icon sizing ───────────────────────────────────────────

function pvIconSize(pl) {
  if (pl.icon_w_pct != null && pl.icon_h_pct != null) {
    return { wPct: pl.icon_w_pct * 100, hPct: pl.icon_h_pct * 100 };
  }
  return { wPct: 4.5, hPct: 2.2 };
}

// ── placement rendering ───────────────────────────────────

function pvRenderPlacement(frame, pp, pl) {
  const positions = pvSlotPositions(pl);
  const { wPct, hPct } = pvIconSize(pl);

  positions.forEach(({ xPct, yPct }, slotIdx) => {
    const inst      = (pl.instances || [])[slotIdx];
    const slotRole  = inst ? (inst.slot_role || "") : "";
    const assetUrl  = inst ? (inst.asset_url || "") : "";

    // Equipment/bar parts with no image asset are invisible in the PPTX;
    // skip the dot placeholder so they don't pollute the preview canvas.
    if (!assetUrl && (pp.render_kind === "equipment" || pp.render_kind === "bar")) return;

    // Rotation/flip mirroring applies to the right-side slot of both "mirror" and
    // "horizontal" symmetric placements — matching render_ppt.py exactly.
    const isSymPattern   = pl.pattern === "mirror" || pl.pattern === "horizontal";
    const isMirroredSlot = isSymPattern && (slotRole === "driver" || slotRole === "positive_x");
    const instFlipH = (pl.flip_h || false) !== (isMirroredSlot && (pl.flip_mirrored_h || false));
    const instFlipV = pl.flip_v || false;

    const baseRot = pl.rotation || 0;
    const instRot = (isMirroredSlot && baseRot !== 0) ? (360 - baseRot) % 360 : baseRot;

    const transformParts = ["translate(-50%, -50%)"];
    if (instRot) transformParts.push(`rotate(${instRot}deg)`);
    const scaleX = instFlipH ? -1 : 1;
    const scaleY = instFlipV ? -1 : 1;
    if (scaleX !== 1 || scaleY !== 1) transformParts.push(`scale(${scaleX},${scaleY})`);

    const icon = document.createElement("div");
    icon.className = "pv-icon";
    icon.title = `${pp.part_name} — ${pl.location_key}`;
    icon.dataset.overrideKey = pl.override_key;
    const layerVal = pl.layer || 0;
    const cssParts = [
      `left:${xPct.toFixed(3)}%`,
      `top:${yPct.toFixed(3)}%`,
      `width:${wPct.toFixed(3)}%`,
      `height:${hPct.toFixed(3)}%`,
      `transform:${transformParts.join(" ")}`,
    ];
    if (layerVal !== 0) cssParts.push(`z-index:${layerVal + 10}`);
    icon.style.cssText = cssParts.join(";");

    if (assetUrl) {
      const img = document.createElement("img");
      img.src = assetUrl;
      img.alt = pp.part_name;
      img.draggable = false;
      icon.appendChild(img);
    } else {
      icon.classList.add("pv-icon-dot");
      const dot = document.createElement("div");
      dot.className = "pv-dot pv-dot-" + (pp.render_kind || "light");
      icon.appendChild(dot);
    }

    icon.addEventListener("mousedown", e => {
      if (e.button !== 0) return;
      pvDragStart(e, pl, pp, xPct, yPct);
    });

    frame.appendChild(icon);
  });
}

// ── override merging ──────────────────────────────────────

function pvMergeOverride(pl, ov) {
  // Un-apply the server-baked anchor_dx/dy from pl.anchor, then re-apply the
  // provided override values for client-side rendering without a round-trip.
  const savedOv    = pl.override || {};
  const savedDx    = savedOv.anchor_dx      || 0;
  const savedDy    = savedOv.anchor_dy      || 0;
  const savedScale = savedOv.size_scale     || 1;
  const savedHDelta = savedOv.h_spacing_delta || 0;

  const liveDx     = ov.anchor_dx      ?? 0;
  const liveDy     = ov.anchor_dy      ?? 0;
  const liveRot    = ov.rotation    != null ? ov.rotation   : (pl.rotation  ?? 0);
  const liveFlipH  = ov.flip_h      != null ? ov.flip_h     : (pl.flip_h    ?? false);
  const liveFlipV  = ov.flip_v      != null ? ov.flip_v     : (pl.flip_v    ?? false);
  const liveScale  = ov.size_scale     ?? 1;
  const liveHDelta = ov.h_spacing_delta ?? 0;

  const base = pl.anchor || {};
  const baseW = (pl.icon_w_pct || 0.04) / savedScale;
  const baseH = (pl.icon_h_pct || 0.02) / savedScale;

  // Un-bake the server-applied h_spacing_delta and re-apply the live one.
  const rawHSpacing  = (pl.h_spacing != null ? pl.h_spacing : 0) - savedHDelta;
  const liveHSpacing = Math.max(rawHSpacing + liveHDelta, 0.001);

  const liveLayer = ov.layer != null ? ov.layer : (pl.layer ?? 0);

  return {
    ...pl,
    anchor:     { x: (base.x || 0) - savedDx + liveDx, y: (base.y || 0) - savedDy + liveDy },
    h_spacing:  liveHSpacing,
    rotation:   liveRot,
    flip_h:     liveFlipH,
    flip_v:     liveFlipV,
    icon_w_pct: baseW * liveScale,
    icon_h_pct: baseH * liveScale,
    layer:      liveLayer,
  };
}

// ── live inspector preview ────────────────────────────────

function pvLivePreview() {
  if (!_pvInspPl || !_pvInspPp || !_pvInspKey) return;

  // Preserve fields (e.g. h_spacing_delta) that the inspector panel doesn't expose.
  const existing = _pvPendingOverrides[_pvInspKey] || {};
  _pvPendingOverrides[_pvInspKey] = {
    ...existing,
    visible:    $("pv-insp-visible").checked,
    rotation:   parseFloat($("pv-insp-rot-num").value)   || 0,
    flip_h:     $("pv-insp-flip-h").checked,
    flip_v:     $("pv-insp-flip-v").checked,
    anchor_dx:  parseFloat($("pv-insp-dx-num").value)    || 0,
    anchor_dy:  parseFloat($("pv-insp-dy-num").value)    || 0,
    size_scale: parseFloat($("pv-insp-scale-num").value) || 1,
    layer:      parseInt($("pv-insp-layer").value)       || 0,
  };

  pvUpdateInspTitle();
  pvUpdateBadge();
  pvRenderView(_pvView);
}

// ── drag and drop ─────────────────────────────────────────

function pvDragStart(e, pl, pp, grabbedXPct, _grabbedYPct) {
  e.preventDefault();

  const frame = e.currentTarget.closest(".pv-frame");
  if (!frame) return;

  // Use pending override as the drag baseline if one exists, else server-saved.
  const serverDx  = pl.override?.anchor_dx || 0;
  const serverDy  = pl.override?.anchor_dy || 0;
  const pendingOv = _pvPendingOverrides[pl.override_key] || {};
  const savedDx   = pendingOv.anchor_dx != null ? pendingOv.anchor_dx : serverDx;
  const savedDy   = pendingOv.anchor_dy != null ? pendingOv.anchor_dy : serverDy;

  // Invert dx when the grabbed slot and the anchor are on opposite sides of center,
  // so the grabbed mirror icon always follows the mouse naturally.
  const anchorIsRight  = (pl.anchor?.x || 0) > 0.5;
  const grabbedIsRight = grabbedXPct > 50;
  const invertDx = pl.pattern === "mirror" && (grabbedIsRight !== anchorIsRight);

  // Detect a symmetric spread placement: any horizontal multi-slot layout with
  // driver/passenger roles spreads symmetrically around its anchor rather than
  // translating as a rigid group. Covers 2-slot pairs, 4-slot top-tube grids,
  // and partial selections (qty-2 outer pair of a 4-slot location).
  const effectiveSlotCount = pl.slot_count || (pl.instances || []).length || 1;
  const hasDriverPassenger  = (pl.instances || []).some(
    i => i.slot_role === "driver" || i.slot_role === "passenger"
  );
  const isSymmetric = (
    pl.pattern === "horizontal" &&
    effectiveSlotCount >= 2 &&
    hasDriverPassenger
  );

  // Baseline h_spacing for symmetric drag (un-bake any already-applied delta).
  const serverHDelta = pl.override?.h_spacing_delta || 0;
  const savedHDelta  = pendingOv.h_spacing_delta != null ? pendingOv.h_spacing_delta : serverHDelta;
  const baseHSpacing = (pl.h_spacing != null ? pl.h_spacing : 0) - savedHDelta;

  // Convert baseHSpacing to percent and compute the grabbed slot's coefficient
  // (how many h_spacing units from center it sits). The coefficient lets us
  // correctly scale drag for any slot in an n-slot symmetric grid: inner slots
  // of a 4-slot placement have coeff ≈ ±0.5, outer slots have coeff ≈ ±1.5.
  let baseSpacingPct;
  if (pl.h_spacing_units === "icon_width") {
    const iconWPct = (pl.icon_w_pct || 0.04) * 100;
    baseSpacingPct = baseHSpacing > 0 ? iconWPct * baseHSpacing : iconWPct;
  } else {
    baseSpacingPct = baseHSpacing > 0 ? baseHSpacing * 100 : 6;
  }
  const grabCenterPct = ((pl.anchor?.x || 0) - savedDx) * 100;
  const grabbedCoeff  = baseSpacingPct > 0.001
    ? (grabbedXPct - grabCenterPct) / baseSpacingPct
    : (grabbedXPct >= grabCenterPct ? 0.5 : -0.5);

  // pl.anchor.x is the MERGED anchor (rawBase + savedDx) when a pending override
  // exists, so stripping savedDx always recovers the true raw base regardless of
  // whether the pending override was already applied or not.
  _pvDrag = {
    pl, pp, frame,
    frameRect:   frame.getBoundingClientRect(),
    startX:      e.clientX,
    startY:      e.clientY,
    savedDx,
    savedDy,
    invertDx,
    baseAnchorX: (pl.anchor?.x || 0) - savedDx,
    baseAnchorY: (pl.anchor?.y || 0) - savedDy,
    dxPct: 0,
    dyPct: 0,
    isSymmetric,
    grabbedXPct,
    savedHDelta,
    baseHSpacing,
    baseSpacingPct,
    grabbedCoeff,
  };

  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`)
    .forEach(el => el.classList.add("pv-icon-dragging"));

  document.addEventListener("mousemove", pvDragMove);
  document.addEventListener("mouseup",   pvDragEnd);
}

function pvDragMove(e) {
  if (!_pvDrag) return;
  const { frameRect, startX, startY, pl, pp, frame,
          savedDx, savedDy, invertDx, baseAnchorX, baseAnchorY,
          isSymmetric, grabbedXPct, baseHSpacing, baseSpacingPct, grabbedCoeff } = _pvDrag;

  const rawDxPct = (e.clientX - startX) / frameRect.width  * 100;
  const rawDyPct = (e.clientY - startY) / frameRect.height * 100;

  _pvDrag.dxPct = rawDxPct;
  _pvDrag.dyPct = rawDyPct;

  let livePl;

  if (isSymmetric) {
    // Symmetric spread in X: grabbed slot moves, its mirror moves equally in
    // the opposite direction; anchor.x stays fixed, only h_spacing changes.
    // Standard translation in Y: all slots move together.
    //
    // The coefficient (how many h_spacing units the grabbed slot is from center)
    // scales the spread correctly for both inner (±0.5) and outer (±1.5) slots
    // of a 4-slot top-tube grid, as well as standard 2-slot pairs (±0.5).
    const centerPct      = baseAnchorX * 100;
    const newGrabbedXPct = grabbedXPct + rawDxPct;
    const absCoeff       = Math.max(Math.abs(grabbedCoeff), 0.1);
    const newSpacingPct  = Math.max(Math.abs(newGrabbedXPct - centerPct) / absCoeff, 0.5);

    let newHSpacing;
    if (pl.h_spacing_units === "icon_width") {
      const iconWPct = (pl.icon_w_pct || 0.04) * 100;
      newHSpacing = newSpacingPct / iconWPct;
    } else {
      newHSpacing = newSpacingPct / 100;
    }
    newHSpacing = Math.max(newHSpacing, 0.001);

    const effectiveDy = savedDy + (rawDyPct / 100);
    livePl = {
      ...pl,
      h_spacing: newHSpacing,
      anchor: { ...(pl.anchor || {}), y: baseAnchorY + effectiveDy },
    };
  } else {
    // Standard translation drag: anchor shifts, mirror pairs recompute naturally.
    const effectiveDx = savedDx + ((invertDx ? -rawDxPct : rawDxPct) / 100);
    const effectiveDy = savedDy + (rawDyPct / 100);
    livePl = {
      ...pl,
      anchor: { x: baseAnchorX + effectiveDx, y: baseAnchorY + effectiveDy },
    };
  }

  // Remove existing icons and re-render with the live placement.
  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`)
    .forEach(el => el.remove());
  pvRenderPlacement(frame, pp, livePl);
  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`)
    .forEach(el => el.classList.add("pv-icon-dragging"));
}

function pvDragEnd(e) {
  if (!_pvDrag) return;

  document.removeEventListener("mousemove", pvDragMove);
  document.removeEventListener("mouseup",   pvDragEnd);

  const drag = _pvDrag;
  _pvDrag = null;

  drag.frame.querySelectorAll(`[data-override-key="${drag.pl.override_key}"]`)
    .forEach(el => el.classList.remove("pv-icon-dragging"));

  const dxPct = drag.dxPct || 0;
  const dyPct = drag.dyPct || 0;

  // < 0.5% movement in both axes = treat as click, open inspector.
  if (Math.abs(dxPct) < 0.5 && Math.abs(dyPct) < 0.5) {
    pvOpenInspector(drag.pl.override_key, drag.pl, drag.pp);
    return;
  }

  const existingPending = _pvPendingOverrides[drag.pl.override_key] || {};

  if (drag.isSymmetric) {
    // Recompute final h_spacing using the same coefficient formula as pvDragMove.
    const centerPct      = drag.baseAnchorX * 100;
    const newGrabbedXPct = drag.grabbedXPct + dxPct;
    const absCoeff       = Math.max(Math.abs(drag.grabbedCoeff), 0.1);
    const newSpacingPct  = Math.max(Math.abs(newGrabbedXPct - centerPct) / absCoeff, 0.5);

    let newHSpacing;
    if (drag.pl.h_spacing_units === "icon_width") {
      const iconWPct = (drag.pl.icon_w_pct || 0.04) * 100;
      newHSpacing = newSpacingPct / iconWPct;
    } else {
      newHSpacing = newSpacingPct / 100;
    }
    newHSpacing = Math.max(newHSpacing, 0.001);

    const newHDelta = +(newHSpacing - drag.baseHSpacing).toFixed(6);
    const newDy     = +(drag.savedDy + dyPct / 100).toFixed(6);
    _pvPendingOverrides[drag.pl.override_key] = {
      ...existingPending,
      h_spacing_delta: newHDelta,
      anchor_dy:       newDy,
    };
  } else {
    const effectiveDxFrac = (drag.invertDx ? -dxPct : dxPct) / 100;
    const newDx = +(drag.savedDx + effectiveDxFrac).toFixed(6);
    const newDy = +(drag.savedDy + dyPct / 100).toFixed(6);
    _pvPendingOverrides[drag.pl.override_key] = { ...existingPending, anchor_dx: newDx, anchor_dy: newDy };
  }

  pvUpdateBadge();
  pvRenderView(_pvView);
}

// ── inspector ────────────────────────────────────────────

function pvOpenInspector(overrideKey, pl, pp) {
  _pvInspKey = overrideKey;
  _pvInspPl  = pl;
  _pvInspPp  = pp;

  // Prefer pending override values, fall back to server-saved override.
  const pendingOv = _pvPendingOverrides[overrideKey];
  const ov = pendingOv || pl.override || {};

  pvUpdateInspTitle();

  // Meta info (model, location)
  const modelEl = $("pv-insp-model");
  if (modelEl) {
    const mfr = pp.manufacturer || "";
    const pn  = pp.part_number  || "";
    modelEl.textContent = [mfr, pn].filter(Boolean).join(" · ") || "—";
  }
  const locEl = $("pv-insp-location");
  if (locEl) locEl.textContent = pl.location_key || "—";

  $("pv-insp-visible").checked  = ov.visible  !== false;
  $("pv-insp-rotation").value   = ov.rotation  ?? pl.rotation  ?? 0;
  $("pv-insp-rot-num").value    = ov.rotation  ?? pl.rotation  ?? 0;
  $("pv-insp-flip-h").checked   = ov.flip_h    ?? pl.flip_h    ?? false;
  $("pv-insp-flip-v").checked   = ov.flip_v    ?? pl.flip_v    ?? false;
  $("pv-insp-dx").value         = ov.anchor_dx ?? 0;
  $("pv-insp-dx-num").value     = ov.anchor_dx ?? 0;
  $("pv-insp-dy").value         = ov.anchor_dy ?? 0;
  $("pv-insp-dy-num").value     = ov.anchor_dy ?? 0;
  $("pv-insp-scale").value      = ov.size_scale ?? 1;
  $("pv-insp-scale-num").value  = ov.size_scale ?? 1;
  $("pv-insp-layer").value      = ov.layer ?? pl.layer ?? 0;

  show("pv-inspector");
}

function pvUpdateInspTitle() {
  if (!_pvInspKey || !_pvInspPl || !_pvInspPp) return;
  const hasPending = !!_pvPendingOverrides[_pvInspKey];
  $("pv-insp-title").textContent =
    `${_pvInspPp.part_name} — ${_pvInspPl.view}${hasPending ? " ●" : ""}`;
}

function pvHideInspector() {
  _pvInspKey = null;
  _pvInspPl  = null;
  _pvInspPp  = null;
  hide("pv-inspector");
}

async function pvResetThisPart() {
  if (!_pvInspKey) return;
  const key = _pvInspKey;
  const pl  = _pvInspPl;
  const pp  = _pvInspPp;

  delete _pvPendingOverrides[key];
  pvUpdateBadge();

  // If the server has a saved override for this key, wipe it so we return
  // to the original load state (not just the last-applied state).
  const hasServerOverride = pl?.override && Object.keys(pl.override).length > 0;
  if (_pvDraftId && hasServerOverride) {
    const res = await api(`/api/draft/${_pvDraftId}/overrides/batch`, { overrides: { [key]: {} } });
    if (res.ok) {
      await pvLoad(_pvDraftId);
    } else {
      alert("Failed to reset override: " + (res.error || "unknown error"));
    }
  } else {
    // Nothing saved on server — just re-open inspector with base values.
    if (pl && pp) pvOpenInspector(key, pl, pp);
    pvRenderView(_pvView);
  }
}

// ── toolbar actions ──────────────────────────────────────

async function pvApplyChanges() {
  if (!_pvDraftId || Object.keys(_pvPendingOverrides).length === 0) return;

  const res = await api(`/api/draft/${_pvDraftId}/overrides/batch`, {
    overrides: _pvPendingOverrides,
  });

  if (res.ok) {
    await pvLoad(_pvDraftId);
  } else {
    alert("Failed to apply changes: " + (res.error || "unknown error"));
  }
}

async function pvResetThisView() {
  const suffix = `:${_pvView}`;

  // Clear pending overrides for this view.
  Object.keys(_pvPendingOverrides).forEach(key => {
    if (key.endsWith(suffix)) delete _pvPendingOverrides[key];
  });
  pvUpdateBadge();

  // Find server-saved overrides for this view and wipe them so we return
  // to the original load state (not just the last-applied state).
  const keysToReset = [];
  for (const pp of (_pvPlan?.planned_parts || [])) {
    for (const pl of pp.placements) {
      if (pl.view === _pvView && pl.override && Object.keys(pl.override).length > 0) {
        keysToReset.push(pl.override_key);
      }
    }
  }

  if (_pvDraftId && keysToReset.length > 0) {
    const emptyOverrides = {};
    keysToReset.forEach(k => { emptyOverrides[k] = {}; });
    const res = await api(`/api/draft/${_pvDraftId}/overrides/batch`, { overrides: emptyOverrides });
    if (res.ok) {
      await pvLoad(_pvDraftId);
    } else {
      alert("Failed to reset view overrides: " + (res.error || "unknown error"));
    }
  } else {
    pvRenderView(_pvView);
  }
}

async function pvResetAllViews() {
  _pvPendingOverrides = {};
  pvUpdateBadge();

  if (!_pvDraftId) {
    pvRenderView(_pvView);
    return;
  }

  // Collect all keys that have server-saved overrides and wipe them.
  const keysToReset = [];
  for (const pp of (_pvPlan?.planned_parts || [])) {
    for (const pl of pp.placements) {
      if (pl.override && Object.keys(pl.override).length > 0) {
        keysToReset.push(pl.override_key);
      }
    }
  }

  if (keysToReset.length > 0) {
    const emptyOverrides = {};
    keysToReset.forEach(k => { emptyOverrides[k] = {}; });
    const res = await api(`/api/draft/${_pvDraftId}/overrides/batch`, { overrides: emptyOverrides });
    if (res.ok) {
      await pvLoad(_pvDraftId);
    } else {
      alert("Failed to reset overrides: " + (res.error || "unknown error"));
    }
  } else {
    pvRenderView(_pvView);
  }
}

// ── badge / indicator ────────────────────────────────────

function pvUpdateBadge() {
  const count    = Object.keys(_pvPendingOverrides).length;
  const applyBtn = $("btn-pv-apply");
  const badge    = $("pv-pending-count");
  if (applyBtn) applyBtn.disabled = count === 0;
  if (badge) {
    badge.textContent = count;
    badge.style.display = count > 0 ? "inline" : "none";
  }
}

// ── spinner / error helpers ──────────────────────────────

function pvShowSpinner(on) {
  const el = $("pv-spinner");
  if (el) el.style.display = on ? "block" : "none";
}

function pvShowError(msg) {
  const wrap = $("pv-canvas-wrap");
  wrap.innerHTML = `<div class="pv-error">⚠️ ${esc(msg)}</div>`;
}

// ── slider ↔ number sync ─────────────────────────────────

function pvSyncSlider(sliderId, numId) {
  const s = $(sliderId), n = $(numId);
  if (!s || !n) return;
  s.addEventListener("input", () => { n.value = s.value; });
  n.addEventListener("input", () => { s.value = n.value; });
}

// ── init ─────────────────────────────────────────────────

(function pvInit() {
  const btnClose     = $("pv-insp-close");
  const btnResetPart = $("pv-insp-reset-part");
  const btnApply     = $("btn-pv-apply");
  const btnResetView = $("btn-pv-reset-view");
  const btnResetAll  = $("btn-pv-reset-all");

  if (btnClose)     btnClose.addEventListener("click",     pvHideInspector);
  if (btnResetPart) btnResetPart.addEventListener("click", pvResetThisPart);
  if (btnApply)     btnApply.addEventListener("click",     pvApplyChanges);
  if (btnResetView) btnResetView.addEventListener("click", pvResetThisView);
  if (btnResetAll)  btnResetAll.addEventListener("click",  pvResetAllViews);

  // Only hide inspector when clicking the canvas background, not on an icon.
  const wrap = $("pv-canvas-wrap");
  if (wrap) wrap.addEventListener("click", e => {
    if (!e.target.closest(".pv-icon")) pvHideInspector();
  });

  pvSyncSlider("pv-insp-rotation", "pv-insp-rot-num");
  pvSyncSlider("pv-insp-dx",       "pv-insp-dx-num");
  pvSyncSlider("pv-insp-dy",       "pv-insp-dy-num");
  pvSyncSlider("pv-insp-scale",    "pv-insp-scale-num");

  // Wire every inspector control to trigger a real-time canvas re-render.
  [
    "pv-insp-visible",
    "pv-insp-rotation", "pv-insp-rot-num",
    "pv-insp-flip-h",   "pv-insp-flip-v",
    "pv-insp-dx",       "pv-insp-dx-num",
    "pv-insp-dy",       "pv-insp-dy-num",
    "pv-insp-scale",    "pv-insp-scale-num",
    "pv-insp-layer",
  ].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener("input", pvLivePreview);
  });
})();
