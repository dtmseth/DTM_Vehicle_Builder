// ═══════════════════════════════════════════════════════
// TAB ROUTING
// ═══════════════════════════════════════════════════════
//
// Top-level workspaces are capability-gated after the session endpoint
// resolves the signed-in user's Entra roles:
//   - projects           → #tab-projects (project manager)
//   - forms              → #tab-forms (operational PDF forms)
//   - vehicle-sales      → #tab-vehicle-sales (buyback / sale records)
//   - calendar           → #tab-calendar (production scheduling)
//   - operations         → #tab-operations (shared production backlog)
//   - pricing            → #tab-pricing (vendor pricing imports and exports)
//   - settings           → #tab-settings (General + Advanced groups)
//
// Settings has one icon-only header action beside the profile badge. General
// and Advanced stab groups are shown together when the user can access them;
// the stab content blocks live as siblings inside #tab-settings.
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
  "stab-calendar-teams",
  "stab-navigation",
  "stab-placements",
  "stab-fixtures",
  "stab-sizes",
  "stab-sku-grid",
  "stab-qb-inbox",
  "stab-catalog",
  "stab-parts",
  "stab-parts-db",
  "stab-vehicles",
  "stab-agencies",
  "stab-sales-reps",
  "stab-presets",
  "stab-shopmonkey",
  "stab-quickbooks",
  "stab-quickbooks-production-preview",
  "stab-workbook-tools",
];

// Outer stabs whose visual identity covers two real content blocks.
// First entry in `stabs` is the default pane when the outer stab activates.
const INNER_STAB_GROUPS = {
  "placements":   { bar: "inner-stab-bar-placements",    stabs: ["placements", "fixtures"] },
  "part-manager": { bar: "inner-stab-bar-part-manager",  stabs: ["sku-grid", "qb-inbox", "parts-db", "catalog", "parts"] },
};

const QUICKBOOKS_UI_ENABLED = window.DTM_QUICKBOOKS_UI_ENABLED === true;
const _quickBooksStabButton = document.querySelector(".stab[data-stab='quickbooks']");
if (_quickBooksStabButton) _quickBooksStabButton.hidden = !QUICKBOOKS_UI_ENABLED;

let _activeHeaderTab = null;
let _activeSettingsStab = null;

window.DTM_ACCESS_SESSION = null;

const APP_NAVIGATION_TABS = [
  "projects", "forms", "vehicle-sales", "calendar", "operations", "pricing",
];
let _navigationSettings = {schema_version: 1, hidden_tabs: []};

function _appTabConfiguredVisible(tab) {
  return tab === "settings" || !_navigationSettings.hidden_tabs.includes(tab);
}

function appHasCapability(capability) {
  return (window.DTM_ACCESS_SESSION?.capabilities || []).includes(capability);
}

function appPermissionDenied(action) {
  const detail = `You don't have permission to ${String(action || "perform this action").trim()}. Contact an administrator.`;
  toast(detail, "error");
  return detail;
}

function _appCanOpenHeader(tab) {
  if (!_appTabConfiguredVisible(tab)) return false;
  if (tab === "projects") return appHasCapability("projects.view");
  if (tab === "forms") return appHasCapability("projects.view") || appHasCapability("operations.view");
  if (tab === "vehicle-sales") return appHasCapability("projects.edit");
  if (tab === "calendar") return appHasCapability("operations.view");
  if (tab === "operations") return appHasCapability("operations.view");
  if (tab === "pricing") return appHasCapability("pricing.view");
  if (tab === "settings") {
    return appHasCapability("settings.general.manage") || appHasCapability("operations.schedule.update") ||
      (QUICKBOOKS_UI_ENABLED && appHasCapability("estimates.manage")) ||
      appHasCapability("settings.advanced.manage");
  }
  return false;
}

function _appFirstWorkspace() {
  const preferred = window.DTM_ACCESS_SESSION?.default_workspace || "";
  if (preferred && _appCanOpenHeader(preferred)) return preferred;
  return ["projects", "forms", "vehicle-sales", "calendar", "operations", "pricing", "settings"]
    .find(_appCanOpenHeader) || "";
}

window.applyNavigationSettings = function (settings) {
  const hidden = Array.isArray(settings?.hidden_tabs)
    ? settings.hidden_tabs.filter(tab => APP_NAVIGATION_TABS.includes(tab))
    : [];
  _navigationSettings = {
    schema_version: Number.isInteger(settings?.schema_version) ? settings.schema_version : 1,
    hidden_tabs: [...new Set(hidden)],
  };
  if (window.DTM_ACCESS_SESSION) window.applyAppAccessSession(window.DTM_ACCESS_SESSION);
  if (_activeHeaderTab && !_appCanOpenHeader(_activeHeaderTab)) {
    const fallback = _appFirstWorkspace();
    if (fallback) switchTab(fallback);
  }
  return _navigationSettings;
};

window.loadNavigationSettings = async function () {
  try {
    return window.applyNavigationSettings(await api("/api/navigation-settings"));
  } catch (_) {
    return window.applyNavigationSettings({schema_version: 1, hidden_tabs: []});
  }
};

let _navigationSettingsWired = false;

function _renderNavigationSettings(settings) {
  const hidden = new Set(settings?.hidden_tabs || []);
  document.querySelectorAll("[data-navigation-tab]").forEach(input => {
    input.checked = !hidden.has(input.dataset.navigationTab);
  });
}

async function _saveNavigationSettings() {
  const button = $("navigation-settings-save");
  const status = $("navigation-settings-status");
  const hiddenTabs = [...document.querySelectorAll("[data-navigation-tab]")]
    .filter(input => !input.checked)
    .map(input => input.dataset.navigationTab);
  if (button) {
    button.disabled = true;
    button.textContent = "Saving…";
  }
  if (status) {
    status.textContent = "Saving navigation for everyone…";
    status.className = "navigation-settings-status";
  }
  try {
    const next = {schema_version: 1, hidden_tabs: hiddenTabs};
    const result = await apiSave("/api/navigation-settings/save", next);
    if (!result?.ok) throw new Error(result?.error || "Save failed");
    window.applyNavigationSettings(next);
    if (status) {
      status.textContent = hiddenTabs.length
        ? `Saved. ${hiddenTabs.length} workspace${hiddenTabs.length === 1 ? " is" : "s are"} now hidden for everyone.`
        : "Saved. All workspaces are visible to users who have access.";
      status.className = "navigation-settings-status is-saved";
    }
    toast("Navigation visibility saved", "success");
  } catch (error) {
    if (status) {
      status.textContent = "Could not save navigation: " + (error?.message || "unknown error");
      status.className = "navigation-settings-status is-error";
    }
    toast("Could not save navigation visibility", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Save navigation";
    }
  }
}

async function initNavigationSettings() {
  if (!_navigationSettingsWired) {
    _navigationSettingsWired = true;
    $("navigation-settings-save")?.addEventListener("click", _saveNavigationSettings);
  }
  const status = $("navigation-settings-status");
  try {
    const settings = await api("/api/navigation-settings");
    window.applyNavigationSettings(settings);
    _renderNavigationSettings(settings);
    if (status) status.textContent = "Checked workspaces are shown in navigation.";
  } catch (error) {
    if (status) {
      status.textContent = "Could not load navigation settings: " + (error?.message || "unknown error");
      status.className = "navigation-settings-status is-error";
    }
  }
}

function _firstAvailableSettingsStab() {
  if (appHasCapability("settings.general.manage")) return "projects-defaults";
  if (appHasCapability("operations.schedule.update")) return "calendar-teams";
  if (QUICKBOOKS_UI_ENABLED && appHasCapability("estimates.manage")) return "quickbooks";
  if (appHasCapability("settings.advanced.manage")) return "placements";
  return "";
}

function _settingsStabAvailable(stab) {
  if (!stab) return false;
  const button = document.querySelector(`.stab[data-stab="${stab}"]`);
  const group = button?.closest(".settings-nav-group");
  return !!button && !button.hidden && !!group && !group.hidden;
}

window.applyAppAccessSession = function (session) {
  window.DTM_ACCESS_SESSION = session || { capabilities: [] };
  const headerIds = {
    projects: "projects-header-tab",
    forms: "forms-header-tab",
    "vehicle-sales": "vehicle-sales-header-tab",
    operations: "operations-header-tab",
    calendar: "calendar-header-tab",
    pricing: "pricing-header-tab",
    settings: "settings-header-tab",
  };
  Object.entries(headerIds).forEach(([tab, id]) => {
    const button = $(id);
    if (button) button.hidden = !_appCanOpenHeader(tab);
  });

  const canEditProjects = appHasCapability("projects.edit");
  const newProject = $("btn-new-project");
  if (newProject) newProject.hidden = !canEditProjects;
  const readonlyBadge = $("projects-readonly-badge");
  if (readonlyBadge) readonlyBadge.hidden = canEditProjects;

  const canManageGeneral = appHasCapability("settings.general.manage");
  const canSchedule = appHasCapability("operations.schedule.update");
  const canManageEstimates = appHasCapability("estimates.manage");
  document.querySelectorAll("#stab-bar-general .stab").forEach(button => {
    if (button.dataset.stab === "calendar-teams") {button.hidden = !canSchedule; return;}
    button.hidden = canManageGeneral
      ? (button.dataset.stab === "quickbooks" && !QUICKBOOKS_UI_ENABLED)
      : !(canManageEstimates && QUICKBOOKS_UI_ENABLED && button.dataset.stab === "quickbooks");
  });
  const generalGroup = $("settings-nav-general");
  if (generalGroup) generalGroup.hidden = !(canManageGeneral || canSchedule || (canManageEstimates && QUICKBOOKS_UI_ENABLED));
  const canManageAdvanced = appHasCapability("settings.advanced.manage");
  const advancedGroup = $("settings-nav-advanced");
  if (advancedGroup) advancedGroup.hidden = !canManageAdvanced;
  const qbPricing = $("qb-pricing-panel");
  if (qbPricing) qbPricing.hidden = !canManageAdvanced;
  const qbCredentials = $("qb-creds-card");
  if (qbCredentials) qbCredentials.hidden = !canManageAdvanced;
  if (!_settingsStabAvailable(_activeSettingsStab)) _activeSettingsStab = _firstAvailableSettingsStab();
};

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
  if (stab === "quickbooks" && !QUICKBOOKS_UI_ENABLED) stab = "projects-defaults";
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
  if (stab === "projects-defaults" && typeof initProjectDefaultsTab === "function") initProjectDefaultsTab();
  if (stab === "calendar-teams" && typeof initCalendarSettings === "function") initCalendarSettings();
  if (stab === "agencies" && typeof refreshAgenciesTab === "function") refreshAgenciesTab();
  if (stab === "workbook-tools" && typeof loadTemplateInfo === "function") loadTemplateInfo();
  if (stab === "fixtures" && typeof initFixtures === "function") initFixtures();
  if (stab === "sales-reps" && typeof initSalesRepsTab === "function") initSalesRepsTab();
  if (stab === "sku-grid" && typeof initSkuGridTab === "function") {
    initSkuGridTab();
    if (typeof refreshQbInboxCount === "function") refreshQbInboxCount();
  }
  if (stab === "qb-inbox" && typeof initQbInboxTab === "function") initQbInboxTab();
  if (stab === "parts-db" && typeof initPartsDbTab === "function") initPartsDbTab();
  if (stab === "shopmonkey" && typeof initShopmonkeyTab === "function") initShopmonkeyTab();
  if (stab === "navigation" && typeof initNavigationSettings === "function") initNavigationSettings();
  if (stab === "quickbooks" && QUICKBOOKS_UI_ENABLED && typeof initQuickBooksTab === "function") initQuickBooksTab();
  if (stab === "quickbooks-production-preview" && typeof initQuickBooksProductionPreview === "function") initQuickBooksProductionPreview();
}

function switchTab(t) {
  // Keep old in-app links and saved integrations working after the two legacy
  // Settings header routes were consolidated.
  if (t === "general-settings" || t === "advanced-settings") {
    if (t === "advanced-settings" && appHasCapability("settings.advanced.manage")) {
      _activeSettingsStab = "placements";
    }
    t = "settings";
  }
  if (!_appCanOpenHeader(t)) {
    const fallback = _appFirstWorkspace();
    if (!fallback || fallback === t) return;
    t = fallback;
  }
  _activeHeaderTab = t;
  document.querySelectorAll(".htab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === t);
  });

  $("tab-projects").hidden = t !== "projects";
  $("tab-forms").hidden = t !== "forms";
  $("tab-vehicle-sales").hidden = t !== "vehicle-sales";
  $("tab-operations").hidden = t !== "operations";
  $("tab-calendar").hidden = t !== "calendar";
  $("tab-pricing").hidden = t !== "pricing";
  $("tab-settings").hidden = t !== "settings";

  if (t === "projects") {
    initProjectsTab();
    return;
  }
  if (t === "calendar") {
    if (typeof initCalendarTab === "function") initCalendarTab();
    return;
  }
  if (t === "forms") {
    if (typeof initTemporaryTagsTab === "function") initTemporaryTagsTab();
    return;
  }
  if (t === "vehicle-sales") {
    if (typeof initVehicleSalesTab === "function") initVehicleSalesTab();
    return;
  }
  if (t === "operations") {
    if (typeof initOperationsTab === "function") initOperationsTab();
    return;
  }
  if (t === "pricing") {
    if (typeof initPricingCenterTab === "function") initPricingCenterTab();
    return;
  }

  // Combined Settings workspace — both accessible groups stay visible.
  if (typeof initSettings === "function") initSettings();

  const targetStab = _settingsStabAvailable(_activeSettingsStab)
    ? _activeSettingsStab
    : _firstAvailableSettingsStab();
  if (!targetStab) return;
  _activeSettingsStab = targetStab;
  _showOuterStab(targetStab);
}

document.querySelectorAll(".htab").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.querySelectorAll(".stab").forEach(btn => {
  btn.addEventListener("click", () => {
    const stab = btn.dataset.stab;
    _activeSettingsStab = stab;
    _showOuterStab(stab);
  });
});

document.querySelectorAll(".inner-stab").forEach(btn => {
  btn.addEventListener("click", () => {
    _showInnerStab(btn.dataset.innerGroup, btn.dataset.innerStab);
  });
});
