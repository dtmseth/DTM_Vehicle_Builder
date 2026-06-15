// ═══════════════════════════════════════════════════════
// TAB ROUTING
// ═══════════════════════════════════════════════════════
//
// Three top-level header tabs:
//   - projects           → #tab-projects (project manager)
//   - general-settings   → #tab-settings + #stab-bar-general
//   - advanced-settings  → #tab-settings + #stab-bar-advanced
//
// Each settings header tab has its own set of stab buttons. The
// per-group stab-bar is shown/hidden as the header tab switches; the stab
// content blocks (stab-placements, stab-fixtures, etc.) live as siblings
// inside #tab-settings and are toggled individually.
//
// Two "outer stabs" group two inner content blocks:
//   - placements   → toggles between #stab-placements and #stab-fixtures
//   - part-manager → toggles between #stab-catalog and #stab-parts
// An inner-stab-bar above the active content block lets the user flip
// between the two panes.

// Content-block ids that exist as siblings inside #tab-settings. Listed
// once here so the show/hide loop doesn't have to know whether they're
// "outer" stabs or "inner" panes.
const ALL_STAB_CONTENTS = [
  "stab-projects-defaults",
  "stab-placements",
  "stab-fixtures",
  "stab-sizes",
  "stab-catalog",
  "stab-parts",
  "stab-parts-db",
  "stab-vehicles",
  "stab-agencies",
  "stab-sales-reps",
  "stab-presets",
  "stab-quickbooks",
  "stab-workbook-tools",
];

// Outer stabs whose visual identity covers two real content blocks.
// First entry in `stabs` is the default pane when the outer stab activates.
const INNER_STAB_GROUPS = {
  "placements":   { bar: "inner-stab-bar-placements",    stabs: ["placements", "fixtures"] },
  "part-manager": { bar: "inner-stab-bar-part-manager",  stabs: ["catalog", "parts", "parts-db"] },
};

// Default stab selected when each header tab activates for the first time.
const HEADER_DEFAULT_STAB = {
  "general-settings": "projects-defaults",
  "advanced-settings": "placements",
};

let _activeHeaderTab = null;
const _stabPerHeader = { "general-settings": null, "advanced-settings": null };

function _hideAllStabContents() {
  for (const id of ALL_STAB_CONTENTS) {
    const el = $(id);
    if (el) el.hidden = true;
  }
  for (const group of Object.values(INNER_STAB_GROUPS)) {
    const bar = $(group.bar);
    if (bar) bar.hidden = true;
  }
}

function _showOuterStab(stab) {
  _hideAllStabContents();
  if (INNER_STAB_GROUPS[stab]) {
    const group = INNER_STAB_GROUPS[stab];
    const bar = $(group.bar);
    if (bar) bar.hidden = false;
    // Default to first inner pane and mark its button active.
    _showInnerStab(stab, group.stabs[0]);
  } else {
    const el = $("stab-" + stab);
    if (el) el.hidden = false;
  }
  // Toggle "active" on the corresponding outer-stab button across both bars.
  document.querySelectorAll(".stab").forEach(b => {
    b.classList.toggle("active", b.dataset.stab === stab);
  });
  _runStabSideEffects(stab);
}

function _showInnerStab(outerStab, innerStab) {
  const group = INNER_STAB_GROUPS[outerStab];
  if (!group) return;
  for (const inner of group.stabs) {
    const el = $("stab-" + inner);
    if (el) el.hidden = (inner !== innerStab);
  }
  document.querySelectorAll(`#${group.bar} .inner-stab`).forEach(b => {
    b.classList.toggle("active", b.dataset.innerStab === innerStab);
  });
  _runStabSideEffects(innerStab);
}

function _runStabSideEffects(stab) {
  // Per-stab initialization hooks the legacy code already exposes.
  if (stab === "workbook-tools" && typeof loadTemplateInfo === "function") loadTemplateInfo();
  if (stab === "fixtures" && typeof initFixtures === "function") initFixtures();
  if (stab === "sales-reps" && typeof initSalesRepsTab === "function") initSalesRepsTab();
  if (stab === "parts-db" && typeof initPartsDbTab === "function") initPartsDbTab();
  if (stab === "quickbooks" && typeof initQuickBooksTab === "function") initQuickBooksTab();
}

function switchTab(t) {
  _activeHeaderTab = t;
  document.querySelectorAll(".htab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === t);
  });

  $("tab-projects").hidden = t !== "projects";
  $("tab-settings").hidden = (t !== "general-settings" && t !== "advanced-settings");

  if (t === "projects") {
    initProjectsTab();
    return;
  }

  // Settings family — show the right stab-bar and a default stab.
  $("stab-bar-general").hidden = t !== "general-settings";
  $("stab-bar-advanced").hidden = t !== "advanced-settings";
  if (typeof initSettings === "function") initSettings();

  const previous = _stabPerHeader[t];
  const targetStab = previous || HEADER_DEFAULT_STAB[t];
  _stabPerHeader[t] = targetStab;
  _showOuterStab(targetStab);
}

document.querySelectorAll(".htab").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.querySelectorAll(".stab").forEach(btn => {
  btn.addEventListener("click", () => {
    const stab = btn.dataset.stab;
    if (_activeHeaderTab) _stabPerHeader[_activeHeaderTab] = stab;
    _showOuterStab(stab);
  });
});

document.querySelectorAll(".inner-stab").forEach(btn => {
  btn.addEventListener("click", () => {
    _showInnerStab(btn.dataset.innerGroup, btn.dataset.innerStab);
  });
});
