// ── Projects module: data loading ─────────────────────────────────────────────

async function _ptLoadAll() {
  const [pr, lr, pjr, opts] = await Promise.all([
    api("/api/presets").catch(e  => { console.error("Projects: presets load failed", e);  return null; }),
    api("/api/layouts").catch(e  => { console.error("Projects: layouts load failed", e);  return null; }),
    api("/api/projects").catch(e => { console.error("Projects: projects load failed", e); return null; }),
    api("/api/project-options").catch(e => { console.error("Projects: options load failed", e); return null; }),
  ]);
  if (pr)   { _PT.presets         = pr.presets   || []; }
  if (lr)   { _PT.vehicleMap      = lr.vehicles  || {}; _PT.vehicles = Object.keys(_PT.vehicleMap).sort(); }
  if (pjr)  { _PT.projects        = pjr.projects || []; }
  if (opts?.ok) { _PT.projectOptions = opts.options || _PT.projectOptions; }
}

// Load prefs dropdowns lazily (catalog + workbook rules for lighting/bumper/cage brands)
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

// Derive lighting brand options from catalog + workbook rules
function _ptLightingBrandsFromConfig() {
  // Try config-driven list first
  const fromOpts = (_PT.projectOptions?.lighting_brands || []);
  if (fromOpts.length) return ["Multiple Brands", ...fromOpts];

  // Fall back to catalog/workbook derivation
  const catParts = _PT.catalog?.parts || [];
  const lightNames = new Set(
    catParts
      .filter(p => p.render_kind === "light" || p.render_kind === "bar")
      .map(p => (p.display_name || "").toLowerCase())
  );
  const mfgs  = new Set(["Multiple Brands"]);
  const rules = _PT.workbookRules?.part_rules || {};
  Object.entries(rules).forEach(([name, rule]) => {
    if (lightNames.has(name.toLowerCase())) {
      (rule.manufacturer || []).forEach(m => mfgs.add(m));
    }
  });
  return Array.from(mfgs);
}
