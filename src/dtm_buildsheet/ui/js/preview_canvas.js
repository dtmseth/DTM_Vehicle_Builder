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

// ── placement rendering ───────────────────────────────────

function pvRenderPlacement(frame, pp, pl) {
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
  const savedOv     = pl.override || {};
  const savedDx     = savedOv.anchor_dx      || 0;
  const savedDy     = savedOv.anchor_dy      || 0;
  const savedHDelta = savedOv.h_spacing_delta || 0;  // server-saved delta (== serverHDelta)
  const savedScale  = savedOv.size_scale || 1;

  const liveDx     = ov.anchor_dx       ?? 0;
  const liveDy     = ov.anchor_dy       ?? 0;
  const liveHDelta = ov.h_spacing_delta ?? savedHDelta;
  const liveRot    = ov.rotation   != null ? ov.rotation  : (pl.rotation ?? 0);
  const liveFlipH  = ov.flip_h     != null ? ov.flip_h    : (pl.flip_h   ?? false);
  const liveFlipV  = ov.flip_v     != null ? ov.flip_v    : (pl.flip_v   ?? false);
  const liveScale  = ov.size_scale ?? 1;
  const liveLayer  = ov.layer      != null ? ov.layer     : (pl.layer    ?? 0);

  const dxDelta     = liveDx - savedDx;
  const dyDelta     = liveDy - savedDy;
  // Change in effective h_spacing vs what the server baked (server used pl.h_spacing).
  const hDeltaDelta = liveHDelta - savedHDelta;
  const scaleFactor = savedScale !== 0 ? liveScale / savedScale : liveScale;

  // For mirror patterns the anchor tracks one side of center. A positive dxDelta
  // moves the anchor-side icon by +dxDelta and the opposite-side icon by -dxDelta.
  // Strip the baked-in savedDx to find the raw anchor side.
  const isMirror   = pl.pattern === "mirror";
  const rawAnchorX = (pl.anchor?.x || 0) - savedDx;
  const anchorLeft = rawAnchorX <= 0.5;

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
      // Mirror: anchor-side icon moves +dxDelta, opposite side moves -dxDelta.
      // Non-mirror (inspector dx slider): all icons translate uniformly.
      const xDelta = isMirror
        ? (instLeft === anchorLeft ? dxDelta : -dxDelta)
        : dxDelta;
      // Symmetric-horizontal: each slot moves by its server-baked coefficient × Δeff.
      const hSpacingXDelta = (hDeltaDelta !== 0 && pl.pattern === "horizontal")
        ? (inst.slot_coeff ?? 0) * hDeltaFrac
        : 0;
      return {
        ...inst,
        x_pct: (inst.x_pct ?? 0) + xDelta + hSpacingXDelta,
        y_pct: (inst.y_pct ?? 0) + dyDelta,
        w_pct: (inst.w_pct ?? pl.icon_w_pct ?? 0.04) * scaleFactor,
        h_pct: (inst.h_pct ?? pl.icon_h_pct ?? 0.02) * scaleFactor,
      };
    }),
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

function pvDragStart(e, pl, pp, grabbedXPct, _grabbedYPct) {
  e.preventDefault();

  const frame = e.currentTarget.closest(".pv-frame");
  if (!frame) return;

  const serverDx     = pl.override?.anchor_dx       || 0;
  const serverDy     = pl.override?.anchor_dy       || 0;
  const serverHDelta = pl.override?.h_spacing_delta || 0;
  const pendingOv    = _pvPendingOverrides[pl.override_key] || {};
  const savedDx      = pendingOv.anchor_dx       != null ? pendingOv.anchor_dx       : serverDx;
  const savedDy      = pendingOv.anchor_dy       != null ? pendingOv.anchor_dy       : serverDy;
  const savedHDelta  = pendingOv.h_spacing_delta != null ? pendingOv.h_spacing_delta : serverHDelta;

  // Identify grabbed instance by closest x_pct to the click position.
  const instances = pl.instances || [];
  const grabbedInstIndex = instances.reduce((best, inst, i) => {
    const dist = Math.abs((inst.x_pct ?? 0) * 100 - grabbedXPct);
    return dist < best.dist ? { i, dist } : best;
  }, { i: 0, dist: Infinity }).i;

  // Detect symmetric-horizontal: driver/passenger pairs that change spread, not offset.
  const effectiveSlotCount = pl.slot_count || instances.length || 1;
  const hasDriverPassenger  = instances.some(
    inst => inst.slot_role === "driver" || inst.slot_role === "passenger"
  );
  const isSymmetric = (
    pl.pattern === "horizontal" &&
    effectiveSlotCount >= 2 &&
    hasDriverPassenger
  );

  // baseHSpacing = config base (strips server delta so h_spacing_delta is always relative to config).
  const baseHSpacing  = (pl.h_spacing != null ? pl.h_spacing : 0) - serverHDelta;
  // Unmodified anchor center (strip already-saved override).
  const rawAnchorXPct = ((pl.anchor?.x || 0) - savedDx) * 100;
  // grabbedCoeff comes directly from the server-baked slot_coeff — no client spacing math needed.
  const grabbedCoeff  = instances[grabbedInstIndex]?.slot_coeff
    ?? (grabbedXPct >= rawAnchorXPct ? 0.5 : -0.5);

  _pvDrag = {
    pl, pp, frame,
    frameRect: frame.getBoundingClientRect(),
    startX:    e.clientX,
    startY:    e.clientY,
    savedDx, savedDy, savedHDelta,
    grabbedInstIndex,
    isSymmetric,
    baseHSpacing, grabbedCoeff,
    dxPct: 0,
    dyPct: 0,
  };

  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`)
    .forEach(el => el.classList.add("pv-icon-dragging"));

  document.addEventListener("mousemove", pvDragMove);
  document.addEventListener("mouseup",   pvDragEnd);
}

function pvDragMove(e) {
  if (!_pvDrag) return;
  const { frameRect, startX, startY, pl, pp, frame, grabbedInstIndex } = _pvDrag;

  const rawDxPct = (e.clientX - startX) / frameRect.width  * 100;
  const rawDyPct = (e.clientY - startY) / frameRect.height * 100;

  _pvDrag.dxPct = rawDxPct;
  _pvDrag.dyPct = rawDyPct;

  const rawDxFrac = rawDxPct / 100;
  const rawDyFrac = rawDyPct / 100;

  // Grabbed icon's side moves with the mouse; the opposite side mirrors in X.
  const grabbedInst  = (pl.instances || [])[grabbedInstIndex];
  const grabbedLeft  = (grabbedInst?.x_pct ?? 0.5) < 0.5;

  const livePl = {
    ...pl,
    instances: (pl.instances || []).map(inst => {
      const instLeft = (inst.x_pct ?? 0) < 0.5;
      return {
        ...inst,
        x_pct: (inst.x_pct ?? 0) + (instLeft === grabbedLeft ? +rawDxFrac : -rawDxFrac),
        y_pct: (inst.y_pct ?? 0) + rawDyFrac,
      };
    }),
  };

  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`).forEach(el => el.remove());
  pvRenderPlacement(frame, pp, livePl);
  frame.querySelectorAll(`[data-override-key="${pl.override_key}"]`).forEach(el => el.classList.add("pv-icon-dragging"));
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

  // < 0.5% movement in both axes → treat as click, open inspector.
  if (Math.abs(dxPct) < 0.5 && Math.abs(dyPct) < 0.5) {
    pvOpenInspector(drag.pl.override_key, drag.pl, drag.pp);
    return;
  }

  const existingPending = _pvPendingOverrides[drag.pl.override_key] || {};
  const rawDxFrac = dxPct / 100;
  const rawDyFrac = dyPct / 100;
  const newDy     = +(drag.savedDy + rawDyFrac).toFixed(6);

  if (drag.isSymmetric) {
    // Symmetric horizontal: the spread (h_spacing) changes, not the group offset.
    // Use grabbedCoeff so outer slots of a 4-slot grid compute the same h_spacing
    // as inner slots would — coeff ≈ 0.5 for inner, ≈ 1.5 for outer.
    const grabbedInst    = (drag.pl.instances || [])[drag.grabbedInstIndex] || {};
    const centerPct      = ((drag.pl.anchor?.x || 0) - drag.savedDx) * 100;
    const newGrabbedXPct = (grabbedInst.x_pct ?? 0) * 100 + dxPct;
    const absCoeff       = Math.max(Math.abs(drag.grabbedCoeff), 0.1);
    const newSpacingPct  = Math.max(Math.abs(newGrabbedXPct - centerPct) / absCoeff, 0.5);

    let newHSpacing;
    if (drag.pl.h_spacing_units === "icon_width") {
      newHSpacing = newSpacingPct / ((drag.pl.icon_w_pct || 0.04) * 100);
    } else {
      newHSpacing = newSpacingPct / 100;
    }
    newHSpacing = Math.max(newHSpacing, 0.001);

    _pvPendingOverrides[drag.pl.override_key] = {
      ...existingPending,
      h_spacing_delta: +(newHSpacing - drag.baseHSpacing).toFixed(6),
      anchor_dy:       newDy,
    };

  } else if (drag.pl.pattern === "mirror") {
    // Mirror: anchor tracks the icon on its same side of center.
    // If the grabbed icon is on the anchor's side, anchor moves with it (+).
    // If on the opposite side, the anchor icon mirrored the drag, so anchor moves opposite (−).
    const grabbedInst  = (drag.pl.instances || [])[drag.grabbedInstIndex] || {};
    const anchorLeft   = (drag.pl.anchor?.x || 0) - drag.savedDx <= 0.5;
    const grabbedLeft  = (grabbedInst.x_pct ?? 0) < 0.5;
    const anchorDelta  = (grabbedLeft === anchorLeft) ? +rawDxFrac : -rawDxFrac;

    _pvPendingOverrides[drag.pl.override_key] = {
      ...existingPending,
      anchor_dx: +(drag.savedDx + anchorDelta).toFixed(6),
      anchor_dy: newDy,
    };

  } else {
    // Single icon or non-symmetric: anchor translates directly with the drag.
    _pvPendingOverrides[drag.pl.override_key] = {
      ...existingPending,
      anchor_dx: +(drag.savedDx + rawDxFrac).toFixed(6),
      anchor_dy: newDy,
    };
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
