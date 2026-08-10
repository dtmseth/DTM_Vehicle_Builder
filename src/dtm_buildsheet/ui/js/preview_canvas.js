// ═══════════════════════════════════════════════════════
// PREVIEW CANVAS  — Visual build preview with overrides
// ═══════════════════════════════════════════════════════
//
// Slot positioning and override math here parallel domain/geometry.py
// (slot_relative_positions). The server bakes per-instance slot_coeff values
// the inspector reads, and this file applies drag-derived deltas
// (anchor_dx/anchor_dy, h_spacing_delta) on top. Any change to pattern
// semantics — single/horizontal/vertical/mirror — must land in both
// domain/geometry.py and canvas.js (getSlotPositions) so the preview and the
// generated PowerPoint stay in sync.

// ── state ────────────────────────────────────────────────
let _pvDraftId          = null;   // draft UUID from parse response
let _pvPlan             = null;   // last response from /api/preview/plan
let _pvView             = "front";// active view tab
let _pvInspKey          = null;   // override_key currently open in inspector
let _pvInspPl           = null;   // placement object open in inspector
let _pvInspPp           = null;   // part object open in inspector
let _pvInspAr           = 0;      // W/H aspect ratio captured when the inspector opened
let _pvDrag             = null;   // active drag state (see pvDragStart)
let _pvPendingOverrides = {};     // {override_key: overrideDict} — short-lived autosave queue
let _pvInFlightOverrides = {};    // batch currently on its way to the server
let _pvConfirmedOverrides = {};   // saved locally until the next full plan reload
let _pvAutosaveTimer    = null;
let _pvAutosaveInFlight = false;
let _pvAutosavePromise  = null;

// ── public API ───────────────────────────────────────────

async function pvLoad(draftId) {
  if (_pvDraftId && pvHasPendingChanges()) {
    const saved = await pvApplyChanges();
    if (!saved) return;
  }
  if (_pvAutosaveTimer) clearTimeout(_pvAutosaveTimer);
  _pvAutosaveTimer = null;
  _pvDraftId          = draftId;
  _pvPlan             = null;
  _pvPendingOverrides = {};
  _pvInFlightOverrides = {};
  _pvConfirmedOverrides = {};
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

function pvReload() {
  if (_pvDraftId) pvLoad(_pvDraftId);
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
      const effectiveOv = pvEffectiveOverride(pl);
      if (effectiveOv.visible === false) continue;
      pvRenderPlacement(frame, pp, pvMergeOverride(pl, effectiveOv), pl);
    }
  }

  container.appendChild(frame);
}

// ── placement rendering ───────────────────────────────────

function pvCombineOverrideMaps(...maps) {
  const combined = {};
  for (const map of maps) {
    for (const [key, value] of Object.entries(map || {})) {
      if (!value) continue;
      combined[key] = { ...(combined[key] || {}), ...value };
    }
  }
  return combined;
}

function pvEffectiveOverride(pl) {
  const key = pl.override_key;
  return {
    ...(pl.override || {}),
    ...(_pvConfirmedOverrides[key] || {}),
    ...(_pvInFlightOverrides[key] || {}),
    ...(_pvPendingOverrides[key] || {}),
  };
}

function pvVerticalMirrorSlotIsReflected(pl, slotIdx) {
  if (pl.pattern !== "vertical_mirror" || (pl.instances || []).length <= 1) return false;
  const anchorY = pl.anchor?.y ?? 0.5;
  const isTopSlot = slotIdx % 2 === 0;
  // The anchor-side icon keeps its configured rotation. Its vertically mirrored
  // counterpart gets the reflected rotation. Centered pairs use top as the base.
  if (Math.abs(anchorY - 0.5) < 0.001) return !isTopSlot;
  return isTopSlot !== (anchorY < 0.5);
}

function pvRenderPlacement(frame, pp, pl, basePl = pl) {
  (pl.instances || []).forEach((inst, slotIdx) => {
    const xPct     = (inst.x_pct ?? 0) * 100;
    const yPct     = (inst.y_pct ?? 0) * 100;
    const wPct     = (inst.w_pct ?? pl.icon_w_pct ?? 0.04) * 100;
    const hPct     = (inst.h_pct ?? pl.icon_h_pct ?? 0.02) * 100;
    const slotRole = inst.slot_role || "";
    const assetUrl = inst.asset_url || "";

    // Equipment/bar parts with no image asset are invisible in the PPTX;
    // skip the dot placeholder so they don't pollute the preview canvas.
    if (!assetUrl && (pp.render_kind === "equipment" || pp.render_kind === "bar")) return;

    // Rotation/flip mirroring normally follows the semantic right-side role.
    // Outer Edge is a rear-view pillar layout, whose physical right column is
    // positional because rear driver/passenger roles are not screen direction.
    const isOuterEdge = pl.pattern === "outer_edge_pillars";
    const isSymPattern = pl.pattern === "mirror" || pl.pattern === "horizontal" || isOuterEdge;
    const isMirroredSlot = isOuterEdge
      ? slotIdx >= Math.floor((pl.instances || []).length / 2)
      : isSymPattern && (slotRole === "driver" || slotRole === "positive_x");
    const instFlipH = (pl.flip_h || false) !== (isMirroredSlot && (pl.flip_mirrored_h || false));
    const instFlipV = pl.flip_v || false;

    const baseRot = pl.rotation || 0;
    const rotationMirrored = isMirroredSlot || pvVerticalMirrorSlotIsReflected(pl, slotIdx);
    const instRot = (rotationMirrored && baseRot !== 0) ? (360 - baseRot) % 360 : baseRot;

    const transformParts = ["translate(-50%, -50%)"];
    if (instRot) transformParts.push(`rotate(${instRot}deg)`);
    const scaleX = instFlipH ? -1 : 1;
    const scaleY = instFlipV ? -1 : 1;
    if (scaleX !== 1 || scaleY !== 1) transformParts.push(`scale(${scaleX},${scaleY})`);

    const icon = document.createElement("div");
    icon.className = "pv-icon";
    icon.title = `${pp.part_name} — ${pl.location_key}`;
    icon.dataset.overrideKey = pl.override_key;
    icon.dataset.groupKey = pl.group_key || "";
    const layerVal = pl.layer || 0;
    const cssParts = [
      `left:${xPct.toFixed(3)}%`,
      `top:${yPct.toFixed(3)}%`,
      `width:${wPct.toFixed(3)}%`,
      `height:${hPct.toFixed(3)}%`,
      `transform:${transformParts.join(" ")}`,
    ];
    // Every icon gets an explicit z-index so a dragged element being appended
    // back into the frame cannot accidentally leap above a higher layer.
    cssParts.push(`z-index:${layerVal + 100}`);
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
      pvDragStart(e, basePl, pp, slotIdx);
    });

    frame.appendChild(icon);
  });
}

// ── override merging ──────────────────────────────────────

function pvMergeOverride(pl, ov) {
  const savedOv     = pl.override || {};
  const savedDx     = savedOv.anchor_dx      || 0;
  const savedDy     = savedOv.anchor_dy      || 0;
  const savedTx     = savedOv.translate_dx   || 0;
  const savedTy     = savedOv.translate_dy   || 0;
  const savedHDelta = savedOv.h_spacing_delta || 0;  // server-saved delta (== serverHDelta)

  const liveDx     = ov.anchor_dx       ?? 0;
  const liveDy     = ov.anchor_dy       ?? 0;
  const liveTx     = ov.translate_dx    ?? savedTx;
  const liveTy     = ov.translate_dy    ?? savedTy;
  const liveHDelta = ov.h_spacing_delta ?? savedHDelta;
  const liveRot    = ov.rotation   != null ? ov.rotation  : (pl.rotation ?? 0);
  const liveFlipH  = ov.flip_h     != null ? ov.flip_h    : (pl.flip_h   ?? false);
  const liveFlipV  = ov.flip_v     != null ? ov.flip_v    : (pl.flip_v   ?? false);
  const liveLayer  = ov.layer      != null ? ov.layer     : (pl.layer    ?? 0);

  // Width/height factors vs the saved baseline (icon_w_in/icon_h_in already
  // reflects any server-saved size override). Two paths:
  //   • New per-axis: ov.size_w / ov.size_h are absolute inches.
  //   • Legacy size_scale: multiply both axes by liveScale / savedScale.
  let wFactor = 1, hFactor = 1;
  if (ov.size_w != null || ov.size_h != null) {
    if (ov.size_w != null && pl.icon_w_in) wFactor = ov.size_w / pl.icon_w_in;
    if (ov.size_h != null && pl.icon_h_in) hFactor = ov.size_h / pl.icon_h_in;
  } else if (ov.size_scale != null || savedOv.size_scale != null) {
    const savedScale = savedOv.size_scale || 1;
    const liveScale  = ov.size_scale ?? savedScale;
    const scaleFactor = savedScale !== 0 ? liveScale / savedScale : liveScale;
    wFactor = scaleFactor;
    hFactor = scaleFactor;
  }

  const dxDelta     = liveDx - savedDx;
  const dyDelta     = liveDy - savedDy;
  const txDelta     = liveTx - savedTx;
  const tyDelta     = liveTy - savedTy;
  // Change in effective h_spacing vs what the server baked (server used pl.h_spacing).
  const hDeltaDelta = liveHDelta - savedHDelta;

  // For mirror patterns the anchor tracks one side of center. A positive dxDelta
  // moves the anchor-side icon by +dxDelta and the opposite-side icon by -dxDelta.
  // Strip the baked-in savedDx to find the raw anchor side.
  const isMirror   = pl.pattern === "mirror";
  const isVerticalMirror = pl.pattern === "vertical_mirror";
  const rawAnchorX = (pl.anchor?.x || 0) - savedDx;
  const rawAnchorY = (pl.anchor?.y || 0) - savedDy;
  const anchorLeft = rawAnchorX <= 0.5;
  const anchorTop = rawAnchorY <= 0.5;

  // hDeltaFrac: change in effective h_spacing in fraction units, for the horizontal path.
  // slot_coeff is baked by the server as (x - anchor) / eff_h_spacing — no client derivation needed.
  const iconWPct = pl.icon_w_pct || 0.04;
  const hDeltaFrac = (pl.h_spacing_units === "icon_width")
    ? hDeltaDelta * iconWPct
    : hDeltaDelta;

  return {
    ...pl,
    rotation: liveRot,
    flip_h:   liveFlipH,
    flip_v:   liveFlipV,
    layer:    liveLayer,
    instances: (pl.instances || []).map(inst => {
      const instLeft = (inst.x_pct ?? 0) < 0.5;
      const instTop = (inst.y_pct ?? 0) < 0.5;
      // Mirror: anchor-side icon moves +dxDelta, opposite side moves -dxDelta.
      // Non-mirror (inspector dx slider): all icons translate uniformly.
      const xDelta = isMirror
        ? (instLeft === anchorLeft ? dxDelta : -dxDelta)
        : dxDelta;
      const yDelta = isVerticalMirror
        ? (instTop === anchorTop ? dyDelta : -dyDelta)
        : dyDelta;
      // Symmetric-horizontal: each slot moves by its server-baked coefficient × Δeff.
      const hSpacingXDelta = (hDeltaDelta !== 0 && pl.pattern === "horizontal")
        ? (inst.slot_coeff ?? 0) * hDeltaFrac
        : 0;
      return {
        ...inst,
        x_pct: (inst.x_pct ?? 0) + xDelta + txDelta + hSpacingXDelta,
        y_pct: (inst.y_pct ?? 0) + yDelta + tyDelta,
        w_pct: (inst.w_pct ?? pl.icon_w_pct ?? 0.04) * wFactor,
        h_pct: (inst.h_pct ?? pl.icon_h_pct ?? 0.02) * hFactor,
      };
    }),
  };
}

// ── live inspector preview ────────────────────────────────

function pvLivePreview() {
  if (!_pvInspPl || !_pvInspPp || !_pvInspKey) return;

  // Preserve fields (e.g. h_spacing_delta) that the inspector panel doesn't expose.
  const existing = {
    ...pvEffectiveOverride(_pvInspPl),
    ...(_pvPendingOverrides[_pvInspKey] || {}),
  };
  const sizeW = parseFloat($("pv-insp-size-w").value);
  const sizeH = parseFloat($("pv-insp-size-h").value);
  const merged = {
    ...existing,
    visible:    $("pv-insp-visible").checked,
    rotation:   parseFloat($("pv-insp-rot-num").value)   || 0,
    flip_h:     $("pv-insp-flip-h").checked,
    flip_v:     $("pv-insp-flip-v").checked,
    anchor_dx:  parseFloat($("pv-insp-dx-num").value)    || 0,
    anchor_dy:  parseFloat($("pv-insp-dy-num").value)    || 0,
    layer:      parseInt($("pv-insp-layer").value)       || 0,
  };
  if (sizeW > 0) merged.size_w = sizeW;
  if (sizeH > 0) merged.size_h = sizeH;
  // Once the user has set per-axis sizes, drop the legacy scale field so the
  // server doesn't double-apply it.
  delete merged.size_scale;
  _pvPendingOverrides[_pvInspKey] = merged;

  pvUpdateInspTitle();
  pvUpdateBadge();
  pvRenderView(_pvView);
  pvScheduleAutosave();
}

// ── drag and drop ─────────────────────────────────────────
//
// Visual rule: the grabbed icon follows the mouse exactly (+dx); every icon on
// the OPPOSITE side of center mirrors it (-dx); icons on the SAME side move
// with it (+dx). This is pattern-agnostic and covers single, mirror, and
// symmetric-horizontal placements uniformly.
//
// Override encoding (pvDragEnd) is pattern-specific so the server can
// reconstruct positions correctly on round-trip:
//   mirror              → anchor_dx  (shifts anchor, server recomputes symmetry)
//   horizontal symmetric→ h_spacing_delta + anchor_dy  (changes spread, not group offset)
//   everything else     → anchor_dx + anchor_dy  (simple translation)

function pvCurrentPlacement(pl) {
  return pvMergeOverride(pl, pvEffectiveOverride(pl));
}

function pvOverrideState(pl) {
  const serverDx     = pl.override?.anchor_dx       || 0;
  const serverDy     = pl.override?.anchor_dy       || 0;
  const serverTx     = pl.override?.translate_dx    || 0;
  const serverTy     = pl.override?.translate_dy    || 0;
  const serverHDelta = pl.override?.h_spacing_delta || 0;
  const effectiveOv  = pvEffectiveOverride(pl);
  return {
    serverDx,
    serverDy,
    serverTx,
    serverTy,
    serverHDelta,
    effectiveOv,
    savedDx:     effectiveOv.anchor_dx       != null ? effectiveOv.anchor_dx       : serverDx,
    savedDy:     effectiveOv.anchor_dy       != null ? effectiveOv.anchor_dy       : serverDy,
    savedTx:     effectiveOv.translate_dx    != null ? effectiveOv.translate_dx    : serverTx,
    savedTy:     effectiveOv.translate_dy    != null ? effectiveOv.translate_dy    : serverTy,
    savedHDelta: effectiveOv.h_spacing_delta != null ? effectiveOv.h_spacing_delta : serverHDelta,
  };
}

function pvGroupItemsFor(pl) {
  const groupKey = pl.group_key || "";
  if (!groupKey) return [];

  const items = [];
  for (const pp of (_pvPlan?.planned_parts || [])) {
    for (const basePl of (pp.placements || [])) {
      if (basePl.view !== _pvView || basePl.group_key !== groupKey) continue;
      const state = pvOverrideState(basePl);
      items.push({ pp, basePl, pl: pvCurrentPlacement(basePl), state });
    }
  }
  return items;
}

function pvDataSelector(attr, value) {
  const safe = String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `[data-${attr}="${safe}"]`;
}

function pvGroupDragOverride(item, rawDxFrac, rawDyFrac) {
  return {
    ...pvEffectiveOverride(item.basePl),
    translate_dx: +(item.state.savedTx + rawDxFrac).toFixed(6),
    translate_dy: +(item.state.savedTy + rawDyFrac).toFixed(6),
  };
}

function pvDragOverride(drag, rawDxFrac, rawDyFrac) {
  const existing = pvEffectiveOverride(drag.basePl);
  const newDy = +(drag.savedDy + rawDyFrac).toFixed(6);

  if (drag.isSymmetric) {
    // A horizontal symmetric pattern changes its spread around the current
    // center. The same calculation is used during the drag and on drop, so the
    // rendered result cannot jump to a different layout after release.
    const grabbedInst = (drag.displayPl.instances || [])[drag.grabbedInstIndex] || {};
    const rawCenterXPct = ((drag.basePl.anchor?.x || 0) - drag.state.serverDx) * 100;
    const centerXPct = rawCenterXPct + drag.savedDx * 100;
    const newGrabbedXPct = (grabbedInst.x_pct ?? 0) * 100 + rawDxFrac * 100;
    const absCoeff = Math.max(Math.abs(drag.grabbedCoeff), 0.1);
    const newSpacingPct = Math.max(
      Math.abs(newGrabbedXPct - centerXPct) / absCoeff,
      0.5,
    );

    let newHSpacing;
    if (drag.basePl.h_spacing_units === "icon_width") {
      newHSpacing = newSpacingPct / ((drag.basePl.icon_w_pct || 0.04) * 100);
    } else {
      newHSpacing = newSpacingPct / 100;
    }
    newHSpacing = Math.max(newHSpacing, 0.001);

    return {
      ...existing,
      h_spacing_delta: +(newHSpacing - drag.baseHSpacing).toFixed(6),
      anchor_dy: newDy,
    };
  }

  if (drag.basePl.pattern === "mirror") {
    const grabbedInst = (drag.displayPl.instances || [])[drag.grabbedInstIndex] || {};
    const rawAnchorX = (drag.basePl.anchor?.x || 0) - drag.state.serverDx;
    const anchorLeft = rawAnchorX + drag.savedDx <= 0.5;
    const grabbedLeft = (grabbedInst.x_pct ?? 0) < 0.5;
    const anchorDelta = grabbedLeft === anchorLeft ? rawDxFrac : -rawDxFrac;
    return {
      ...existing,
      anchor_dx: +(drag.savedDx + anchorDelta).toFixed(6),
      anchor_dy: newDy,
    };
  }

  if (drag.basePl.pattern === "vertical_mirror") {
    const grabbedInst = (drag.displayPl.instances || [])[drag.grabbedInstIndex] || {};
    const rawAnchorY = (drag.basePl.anchor?.y || 0) - drag.state.serverDy;
    const anchorTop = rawAnchorY + drag.savedDy <= 0.5;
    const grabbedTop = (grabbedInst.y_pct ?? 0) < 0.5;
    const anchorDelta = grabbedTop === anchorTop ? rawDyFrac : -rawDyFrac;
    return {
      ...existing,
      anchor_dx: +(drag.savedDx + rawDxFrac).toFixed(6),
      anchor_dy: +(drag.savedDy + anchorDelta).toFixed(6),
    };
  }

  return {
    ...existing,
    anchor_dx: +(drag.savedDx + rawDxFrac).toFixed(6),
    anchor_dy: newDy,
  };
}

function pvDragStart(e, basePl, pp, grabbedInstIndex) {
  e.preventDefault();
  e.stopPropagation();

  const frame = e.currentTarget.closest(".pv-frame");
  if (!frame) return;

  const state = pvOverrideState(basePl);
  const displayPl = pvCurrentPlacement(basePl);
  const serverHDelta = state.serverHDelta;
  const savedDx      = state.savedDx;
  const savedDy      = state.savedDy;
  const savedHDelta  = state.savedHDelta;

  // Detect symmetric-horizontal: driver/passenger pairs that change spread, not offset.
  const instances = displayPl.instances || [];
  const effectiveSlotCount = basePl.slot_count || instances.length || 1;
  const hasDriverPassenger  = instances.some(
    inst => inst.slot_role === "driver" || inst.slot_role === "passenger"
  );
  const isSymmetric = (
    basePl.pattern === "horizontal" &&
    effectiveSlotCount >= 2 &&
    hasDriverPassenger
  );

  // baseHSpacing = config base (strips server delta so h_spacing_delta is always relative to config).
  const baseHSpacing  = (basePl.h_spacing != null ? basePl.h_spacing : 0) - serverHDelta;
  // Unmodified anchor center (strip the server-baked override).
  const rawAnchorXPct = ((basePl.anchor?.x || 0) - state.serverDx) * 100;
  // grabbedCoeff comes directly from the server-baked slot_coeff — no client spacing math needed.
  const grabbedCoeff  = instances[grabbedInstIndex]?.slot_coeff
    ?? ((instances[grabbedInstIndex]?.x_pct ?? 0) * 100 >= rawAnchorXPct ? 0.5 : -0.5);

  const groupItems = pvGroupItemsFor(basePl);
  const isGroupDrag = groupItems.length > 1;

  _pvDrag = {
    basePl, displayPl, pp, frame, state,
    frameRect: frame.getBoundingClientRect(),
    startX:    e.clientX,
    startY:    e.clientY,
    savedDx, savedDy, savedHDelta,
    grabbedInstIndex,
    isSymmetric: isGroupDrag ? false : isSymmetric,
    isGroupDrag,
    groupItems,
    baseHSpacing, grabbedCoeff,
    dxPct: 0,
    dyPct: 0,
  };

  const dragSelector = isGroupDrag
    ? pvDataSelector("group-key", basePl.group_key || "")
    : pvDataSelector("override-key", basePl.override_key);
  frame.querySelectorAll(dragSelector).forEach(el => el.classList.add("pv-icon-dragging"));

  document.addEventListener("mousemove", pvDragMove);
  document.addEventListener("mouseup",   pvDragEnd);
}

function pvDragMove(e) {
  if (!_pvDrag) return;
  const { frameRect, startX, startY, basePl, pp, frame } = _pvDrag;

  const rawDxPct = (e.clientX - startX) / frameRect.width  * 100;
  const rawDyPct = (e.clientY - startY) / frameRect.height * 100;

  _pvDrag.dxPct = rawDxPct;
  _pvDrag.dyPct = rawDyPct;

  const rawDxFrac = rawDxPct / 100;
  const rawDyFrac = rawDyPct / 100;

  if (_pvDrag.isGroupDrag) {
    const groupKey = basePl.group_key || "";
    frame.querySelectorAll(pvDataSelector("group-key", groupKey)).forEach(el => el.remove());
    for (const item of _pvDrag.groupItems) {
      pvRenderPlacement(
        frame,
        item.pp,
        pvMergeOverride(item.basePl, pvGroupDragOverride(item, rawDxFrac, rawDyFrac)),
        item.basePl,
      );
    }
    frame.querySelectorAll(pvDataSelector("group-key", groupKey))
      .forEach(el => el.classList.add("pv-icon-dragging"));
    return;
  }

  // Render the exact override that will be saved on release. This keeps both
  // sides of every mirrored pair visible and makes the drop position identical
  // to the last drag frame.
  const liveOverride = pvDragOverride(_pvDrag, rawDxFrac, rawDyFrac);
  frame.querySelectorAll(pvDataSelector("override-key", basePl.override_key)).forEach(el => el.remove());
  pvRenderPlacement(frame, pp, pvMergeOverride(basePl, liveOverride), basePl);
  frame.querySelectorAll(pvDataSelector("override-key", basePl.override_key))
    .forEach(el => el.classList.add("pv-icon-dragging"));
}

function pvDragEnd(e) {
  if (!_pvDrag) return;

  document.removeEventListener("mousemove", pvDragMove);
  document.removeEventListener("mouseup",   pvDragEnd);

  const drag = _pvDrag;
  _pvDrag = null;

  const dragSelector = drag.isGroupDrag
    ? pvDataSelector("group-key", drag.basePl.group_key || "")
    : pvDataSelector("override-key", drag.basePl.override_key);
  drag.frame.querySelectorAll(dragSelector).forEach(el => el.classList.remove("pv-icon-dragging"));

  const dxPct = drag.dxPct || 0;
  const dyPct = drag.dyPct || 0;

  // < 0.5% movement in both axes → treat as click, open inspector.
  if (Math.abs(dxPct) < 0.5 && Math.abs(dyPct) < 0.5) {
    pvOpenInspector(drag.basePl.override_key, drag.basePl, drag.pp);
    return;
  }

  const rawDxFrac = dxPct / 100;
  const rawDyFrac = dyPct / 100;

  if (drag.isGroupDrag) {
    for (const item of drag.groupItems) {
      _pvPendingOverrides[item.basePl.override_key] = pvGroupDragOverride(
        item, rawDxFrac, rawDyFrac,
      );
    }
    pvUpdateBadge();
    pvRenderView(_pvView);
    pvScheduleAutosave();
    return;
  }

  _pvPendingOverrides[drag.basePl.override_key] = pvDragOverride(
    drag, rawDxFrac, rawDyFrac,
  );

  pvUpdateBadge();
  pvRenderView(_pvView);
  pvScheduleAutosave();
}

// ── inspector ────────────────────────────────────────────

function pvOpenInspector(overrideKey, pl, pp) {
  _pvInspKey = overrideKey;
  _pvInspPl  = pl;
  _pvInspPp  = pp;

  const ov = pvEffectiveOverride(pl);

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
  // Width / height in inches. Prefer explicit per-axis override; fall back to
  // legacy size_scale × catalog baseline so older drafts still display sensibly.
  const baseW = pl.icon_w_in || 0;
  const baseH = pl.icon_h_in || 0;
  const legacyScale = ov.size_scale ?? 1;
  const effW = ov.size_w != null ? ov.size_w : (baseW ? baseW * legacyScale : 0);
  const effH = ov.size_h != null ? ov.size_h : (baseH ? baseH * legacyScale : 0);
  $("pv-insp-size-w").value = effW > 0 ? effW.toFixed(2) : "";
  $("pv-insp-size-h").value = effH > 0 ? effH.toFixed(2) : "";
  // Lock starts engaged each time the inspector opens — matches user request
  // ("locked by default, but can be unlocked"). Capture current ratio so
  // AR-linked typing has something to work with even before they edit.
  const lockBtn = $("pv-insp-ar-lock");
  if (lockBtn) {
    lockBtn.dataset.locked = "true";
    lockBtn.textContent = "🔒";
  }
  _pvInspAr = (effW > 0 && effH > 0) ? effW / effH : (baseW > 0 && baseH > 0 ? baseW / baseH : 0);
  $("pv-insp-layer").value      = ov.layer ?? pl.layer ?? 0;

  show("pv-inspector");
}

function pvUpdateInspTitle() {
  if (!_pvInspKey || !_pvInspPl || !_pvInspPp) return;
  const hasPending = !!(
    _pvPendingOverrides[_pvInspKey] || _pvInFlightOverrides[_pvInspKey]
  );
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

  if (pvHasPendingChanges() && !(await pvApplyChanges())) return;

  // If the server has a saved override for this key, wipe it so we return
  // to the original load state (not just the last-applied state).
  const hasServerOverride = Object.keys(pvEffectiveOverride(pl)).length > 0;
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

async function pvEditCurrentPart() {
  const key = _pvInspKey || "";
  const separator = key.lastIndexOf(":");
  const lineId = separator > 0 ? key.slice(0, separator) : "";
  if (!lineId || typeof openPartEditModal !== "function") {
    toast("This part is not available to edit", "error");
    return;
  }
  pvHideInspector();
  await openPartEditModal(lineId);
}

async function pvCommentCurrentPart() {
  const key = _pvInspKey || "";
  const separator = key.lastIndexOf(":");
  const lineId = separator > 0 ? key.slice(0, separator) : "";
  if (!lineId || typeof openPartEditModal !== "function") {
    toast("This part is not available to comment on", "error");
    return;
  }
  pvHideInspector();
  await openPartEditModal(lineId);
  if (typeof pickerOpenCommentStep === "function") {
    pickerOpenCommentStep();
  } else {
    requestAnimationFrame(() => $("me-comment")?.focus());
  }
}

async function pvDeleteCurrentPart() {
  const key = _pvInspKey || "";
  const separator = key.lastIndexOf(":");
  const lineId = separator > 0 ? key.slice(0, separator) : "";
  if (!lineId || typeof deletePart !== "function") {
    toast("This part is not available to delete", "error");
    return;
  }
  pvHideInspector();
  await deletePart(lineId);
}

// ── automatic placement saves ───────────────────────────

function pvHasPendingChanges() {
  return Object.keys(_pvPendingOverrides).length > 0
    || Object.keys(_pvInFlightOverrides).length > 0
    || _pvAutosaveInFlight;
}

function pvScheduleAutosave() {
  if (_pvAutosaveTimer) clearTimeout(_pvAutosaveTimer);
  _pvAutosaveTimer = setTimeout(() => {
    _pvAutosaveTimer = null;
    pvApplyChanges().catch(error => {
      console.error("Preview autosave failed", error);
    });
  }, 300);
}

async function pvApplyChanges() {
  if (_pvAutosaveTimer) clearTimeout(_pvAutosaveTimer);
  _pvAutosaveTimer = null;
  if (!_pvDraftId) return true;
  if (_pvAutosaveInFlight) {
    await _pvAutosavePromise;
    return pvApplyChanges();
  }
  if (Object.keys(_pvPendingOverrides).length === 0) return true;

  const draftId = _pvDraftId;
  const overrides = _pvPendingOverrides;
  _pvPendingOverrides = {};
  _pvInFlightOverrides = pvCombineOverrideMaps(_pvInFlightOverrides, overrides);
  _pvAutosaveInFlight = true;
  _pvAutosavePromise = api(`/api/draft/${draftId}/overrides/batch`, { overrides });

  let res;
  try {
    res = await _pvAutosavePromise;
  } catch (error) {
    for (const key of Object.keys(overrides)) delete _pvInFlightOverrides[key];
    _pvPendingOverrides = pvCombineOverrideMaps(overrides, _pvPendingOverrides);
    pvUpdateBadge();
    toast("Could not save the placement change. Please try again.", "error");
    console.error("Preview autosave request failed", error);
    return false;
  } finally {
    _pvAutosaveInFlight = false;
    _pvAutosavePromise = null;
  }

  if (!res?.ok) {
    for (const key of Object.keys(overrides)) delete _pvInFlightOverrides[key];
    _pvPendingOverrides = pvCombineOverrideMaps(overrides, _pvPendingOverrides);
    pvUpdateBadge();
    toast("Could not save the placement change. Please try again.", "error");
    return false;
  }

  // Keep the original plan immutable until the next full reload. The server
  // response was rendered from geometry with its saved override already baked
  // in; changing only pl.override here used to make that metadata disagree with
  // its coordinates, which is what caused quick consecutive drags to jump.
  _pvConfirmedOverrides = pvCombineOverrideMaps(_pvConfirmedOverrides, overrides);
  for (const key of Object.keys(overrides)) delete _pvInFlightOverrides[key];
  if (_pvDraftId === draftId) pvRenderView(_pvView);
  pvUpdateBadge();
  return true;
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

// ── dirty-state bridge ───────────────────────────────────

function pvUpdateBadge() {
  if (pvHasPendingChanges() && typeof _pbeMarkDirty === "function") _pbeMarkDirty();
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
  const btnEditPart  = $("pv-insp-edit-part");
  const btnComment   = $("pv-insp-comment-part");
  const btnResetPart = $("pv-insp-reset-part");
  const btnDeletePart = $("pv-insp-delete-part");

  if (btnClose)     btnClose.addEventListener("click",     pvHideInspector);
  if (btnEditPart)  btnEditPart.addEventListener("click",  pvEditCurrentPart);
  if (btnComment)   btnComment.addEventListener("click",   pvCommentCurrentPart);
  if (btnResetPart) btnResetPart.addEventListener("click", pvResetThisPart);
  if (btnDeletePart) btnDeletePart.addEventListener("click", pvDeleteCurrentPart);

  // Only hide inspector when clicking the canvas background, not on an icon.
  const wrap = $("pv-canvas-wrap");
  if (wrap) wrap.addEventListener("click", e => {
    if (!e.target.closest(".pv-icon")) pvHideInspector();
  });

  pvSyncSlider("pv-insp-rotation", "pv-insp-rot-num");
  pvSyncSlider("pv-insp-dx",       "pv-insp-dx-num");
  pvSyncSlider("pv-insp-dy",       "pv-insp-dy-num");

  // AR lock — when engaged, editing one of W/H drives the other to preserve ratio.
  const arBtn = $("pv-insp-ar-lock");
  if (arBtn) {
    arBtn.addEventListener("click", () => {
      const wasLocked = arBtn.dataset.locked === "true";
      arBtn.dataset.locked = (!wasLocked).toString();
      arBtn.textContent = wasLocked ? "🔓" : "🔒";
      // Capture the current ratio when re-locking so the new ratio is the one
      // the user just settled on, not the one from when the inspector opened.
      if (!wasLocked) {
        const w = parseFloat($("pv-insp-size-w").value) || 0;
        const h = parseFloat($("pv-insp-size-h").value) || 0;
        if (w > 0 && h > 0) _pvInspAr = w / h;
      }
    });
  }
  const sizeW = $("pv-insp-size-w");
  const sizeH = $("pv-insp-size-h");
  if (sizeW) sizeW.addEventListener("input", () => {
    if (arBtn?.dataset.locked === "true" && _pvInspAr > 0) {
      const w = parseFloat(sizeW.value);
      if (w > 0) sizeH.value = (w / _pvInspAr).toFixed(2);
    }
    pvLivePreview();
  });
  if (sizeH) sizeH.addEventListener("input", () => {
    if (arBtn?.dataset.locked === "true" && _pvInspAr > 0) {
      const h = parseFloat(sizeH.value);
      if (h > 0) sizeW.value = (h * _pvInspAr).toFixed(2);
    }
    pvLivePreview();
  });

  // Wire every other inspector control to trigger a real-time canvas re-render.
  [
    "pv-insp-visible",
    "pv-insp-rotation", "pv-insp-rot-num",
    "pv-insp-flip-h",   "pv-insp-flip-v",
    "pv-insp-dx",       "pv-insp-dx-num",
    "pv-insp-dy",       "pv-insp-dy-num",
    "pv-insp-layer",
  ].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener("input", pvLivePreview);
  });
})();
