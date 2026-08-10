// ── Projects module: data loading ─────────────────────────────────────────────

async function _ptLoadAll() {
  const [pr, lr, pjr, opts, agencies] = await Promise.all([
    api("/api/presets").catch(e  => { console.error("Projects: presets load failed", e);  return null; }),
    api("/api/layouts").catch(e  => { console.error("Projects: layouts load failed", e);  return null; }),
    api("/api/projects").catch(e => { console.error("Projects: projects load failed", e); return null; }),
    api("/api/project-options").catch(e => { console.error("Projects: options load failed", e); return null; }),
    api("/api/agencies").catch(e => { console.error("Projects: agencies load failed", e); return null; }),
  ]);
  if (pr)   { _PT.presets         = pr.presets   || []; }
  if (lr)   { _PT.vehicleMap      = lr.vehicles  || {}; _PT.vehicles = Object.keys(_PT.vehicleMap).sort(); }
  if (pjr)  { _PT.projects        = pjr.projects || []; }
  if (opts && !opts.error) { _PT.projectOptions = opts; }
  if (agencies?.ok) { _PT.agencies = agencies.agencies || []; }
}

// Load preference option sources lazily.  The source lists are shared by the
// agency defaults screen and the project-level exception controls.
async function _ptLoadPrefsOptions() {
  if (!_PT.workbookRules?.part_rules) {
    const res = await api("/api/workbook-rules");
    if (res?.part_rules) _PT.workbookRules = res;
  }
  if (!_PT.catalog?.parts) {
    const res = await api("/api/catalog");
    if (res?.parts) _PT.catalog = res;
  }
}

function _ptPreferenceOptions(field) {
  const configured = {
    camera_brand: _PT.projectOptions?.camera_brands,
    lighting: _PT.projectOptions?.lighting_brands,
    push_bumper_brand: _PT.projectOptions?.bumper_brands,
    cage_brand: _PT.projectOptions?.cage_brands,
    console_brand: _PT.projectOptions?.console_brands,
  }[field];
  if (configured?.length) return configured;

  if (field === "lighting") {
    const catParts = _PT.catalog?.parts || [];
    const lightNames = new Set(
      catParts
        .filter(p => p.render_kind === "light" || p.render_kind === "bar")
        .map(p => (p.display_name || "").toLowerCase())
    );
    const mfgs = new Set();
    const rules = _PT.workbookRules?.part_rules || {};
    Object.entries(rules).forEach(([name, rule]) => {
      if (lightNames.has(name.toLowerCase())) {
        (rule.manufacturer || []).forEach(m => mfgs.add(m));
      }
    });
    return Array.from(mfgs);
  }

  const fallbacks = {
    push_bumper_brand: ["Setina", "Westin", "Go Rhino", "Gamber Johnson", "Troy", "Pro-Gard"],
    cage_brand: ["Setina", "Pro-Gard", "Troy", "Gamber Johnson"],
    console_brand: ["Gamber Johnson", "Havis"],
  };
  return fallbacks[field] || [];
}

function _ptPrimaryLightingBrand(preferences) {
  const brands = Array.isArray(preferences?.lighting_brands)
    ? preferences.lighting_brands
    : [];
  // "Multiple Brands" was a synthetic UI choice, never a real manufacturer.
  return brands.find(brand => brand && brand !== "Multiple Brands") || "";
}

function _ptPreferenceSelectOptions(field, selected) {
  const values = [..._ptPreferenceOptions(field)];
  // Preferences are now controlled selects.  Do not recreate an obsolete
  // free-text value just because an older project or agency still has it saved.
  const validSelection = values.includes(selected) ? selected : "";
  return [
    `<option value=""${validSelection ? "" : " selected"}>No preference</option>`,
    ...values.map(value =>
      `<option value="${esc(value)}"${value === validSelection ? " selected" : ""}>${esc(value)}</option>`),
  ].join("");
}

function _ptSetPreferenceForm(prefix, preferences = {}) {
  const values = {
    camera_brand: preferences.camera_brand || "",
    lighting: _ptPrimaryLightingBrand(preferences),
    push_bumper_brand: preferences.push_bumper_brand || "",
    cage_brand: preferences.cage_brand || "",
    console_brand: preferences.console_brand || "",
  };
  Object.entries(values).forEach(([field, value]) => {
    const el = $(`${prefix}-${field === "lighting" ? "lighting" : field.replaceAll("_", "-")}`);
    if (el) el.innerHTML = _ptPreferenceSelectOptions(field, value);
  });
  const notes = $(`${prefix}-pref-notes`);
  if (notes) notes.value = preferences.notes || "";
}

function _ptPreferencePayload(prefix) {
  const lighting = $(`${prefix}-lighting`)?.value || "";
  return {
    camera_brand: $(`${prefix}-camera-brand`)?.value || "",
    push_bumper_brand: $(`${prefix}-push-bumper-brand`)?.value || "",
    cage_brand: $(`${prefix}-cage-brand`)?.value || "",
    console_brand: $(`${prefix}-console-brand`)?.value || "",
    lighting_brands: lighting ? [lighting] : [],
    notes: ($(`${prefix}-pref-notes`)?.value || "").trim(),
  };
}

// Promote the choices currently selected on a project form to the agency's
// defaults for future projects. This intentionally calls the narrowly scoped
// endpoint rather than the ordinary agency save, so it never updates QB.
window.PT_setPreferencesAsAgencyDefault = async function(prefix, agencyIdControlId, button) {
  const agencyId = $(`${agencyIdControlId}`)?.value.trim() || "";
  const agency = (_PT.agencies || []).find(item => item.agency_id === agencyId);
  if (!agency) {
    toast("Choose a saved agency before setting its defaults", "info");
    return;
  }

  const originalLabel = button?.textContent;
  if (button) { button.disabled = true; button.textContent = "Saving defaults…"; }
  try {
    const res = await apiSave("/api/agency/default-preferences", {
      agency_id: agencyId,
      default_preferences: _ptPreferencePayload(prefix),
    });
    if (!res?.ok) {
      toast(res?.error || "Could not save agency defaults", "error");
      return;
    }
    _PT.agencies = (_PT.agencies || []).map(item =>
      item.agency_id === agencyId ? res.agency : item
    );
    window.refreshAgenciesTab?.();
    toast(`Saved as ${agency.name}'s defaults for future projects`, "success");
  } catch (error) {
    console.error("Project preferences: agency default save failed", error);
    toast("Could not save agency defaults", "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = originalLabel; }
  }
};

// Compatibility helper used by old callers. It deliberately no longer injects
// a fake "Multiple Brands" choice.
function _ptLightingBrandsFromConfig() {
  return _ptPreferenceOptions("lighting");
}
