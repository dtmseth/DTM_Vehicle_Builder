// ── Projects module: shared state ─────────────────────────────────────────────
// All ui/js/projects/*.js files read/write _PT.* for shared mutable state.
// window.PT_* globals provide onclick= handlers in dynamically generated HTML.

window._PT = {
  // loaded data
  presets:        [],
  vehicles:       [],
  vehicleMap:     {},
  projects:       [],
  projectOptions: {
    build_types:     ["Patrol", "Admin", "Unmarked", "K-9", "Fire"],
    camera_brands:   [],
    lighting_brands: [],
    bumper_brands:   [],
    cage_brands:     [],
  },
  workbookRules:  null,
  catalog:        null,

  // view / wizard state
  saving:         false,
  editId:         null,
  units:          [],       // fleet units being edited in the wizard
  inited:         false,
  viewProject:    null,     // project open in detail view
  fromDetail:     false,    // editor opened from detail (not list)
  isWizard:       false,    // true when creating a new project

  // individual unit modal context
  indModalUid:        null,
  indModalIdx:        null,
  indModalUnitId:     null,
  indModalIndId:      null,
  indModalFromDetail: false,

  // edit tab
  editTabEditable: false,
  editTabUnits:    [],

  // build editor return target + current context
  pbeReturnProject: null,
  pbeReturnTab:     "builds",
  pbeUnit:          null,   // unit object open in the build editor
  pbeProject:       null,   // project object open in the build editor
  pbeDraftId:       null,   // draft_id currently loaded

  // wizard step list
  WIZARD_TABS: ["customer", "preferences", "fleet", "review"],
};

// ── Shared utilities ──────────────────────────────────────────────────────────

function _ptUuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

function _ptProjName(p) {
  const agency = p.customer?.agency || "—";
  const year   = p.customer?.build_year;
  return year ? `${agency} — ${year}` : agency;
}

function _ptUnitLabel(unit, ind, idx) {
  const bt  = (unit.build_type || "Unit").trim();
  const num = ind?.unit_number?.trim();
  return num ? `${bt} #${num}` : `${bt} #${idx + 1}`;
}

function _ptVisiblePresets() {
  return _PT.presets.filter(p =>
    p.preset_id !== "blank_custom" &&
    (p.label || "").toLowerCase() !== "blank"
  );
}

// Return presets compatible with a given unit's vehicle_model and build_type.
// Empty vehicle_types / build_types on a preset mean "any" (universal).
function _ptCompatiblePresets(unit) {
  const vm = unit?.vehicle_model || "";
  const bt = unit?.build_type    || "";
  return _ptVisiblePresets().filter(p => {
    const vOk = !p.vehicle_types?.length || p.vehicle_types.includes(vm);
    const bOk = !p.build_types?.length   || p.build_types.includes(bt);
    return vOk && bOk;
  });
}

function _ptPresetLabel(u) {
  if (!u.preset_id) return "No Preset";
  const match = _ptVisiblePresets().find(p => p.preset_id === u.preset_id);
  return match ? match.label : "No Preset";
}

function _ptSetStatus(el, msg, mood) {
  el.style.display    = "block";
  el.style.background = mood === "good" ? "#e6f9f1" : mood === "err" ? "#fdecea" : "#f0f4ff";
  el.style.color      = mood === "good" ? "var(--green)" : mood === "err" ? "var(--red)" : "var(--navy)";
  el.textContent      = msg;
}

function _ptCurrentBuildYear() {
  return ($("proj-build-year")?.value || $("et-build-year")?.value || "").trim();
}

function _ptEnsureIndividuals(u) {
  while (u.individuals.length < u.quantity) {
    const vm = _PT.vehicleMap[u.vehicle_model] || {};
    u.individuals.push({
      individual_id: _ptUuid(), unit_number: "", year: _ptCurrentBuildYear(),
      make: vm.make || "", model: vm.model || "",
      color: "", vin: "", existing_unit_number: "", existing_vin: "",
      notes: "", draft_id: null,
    });
  }
}

function _ptIndRowHtml(ind) {
  const did = esc(ind.draft_id || "");
  return `<div class="proj-ind-row" data-iid="${esc(ind.individual_id)}" data-draft-id="${did}">
    <div class="form-row proj-ind-row-fields">
      <div class="form-group proj-ind-field-sm">
        <label class="proj-ind-label">Unit #</label>
        <input class="ind-unit-number" type="text" value="${esc(ind.unit_number || "")}" placeholder="101">
      </div>
      <div class="form-group proj-ind-field-xs">
        <label class="proj-ind-label">Vehicle Year</label>
        <input class="ind-year" type="text" value="${esc(ind.year || "")}" placeholder="2026">
      </div>
      <div class="form-group proj-ind-field-sm">
        <label class="proj-ind-label">Color</label>
        <input class="ind-color" type="text" value="${esc(ind.color || "")}" placeholder="White">
      </div>
      <div class="form-group proj-ind-field-lg">
        <label class="proj-ind-label">VIN</label>
        <input class="ind-vin" type="text" value="${esc(ind.vin || "")}" placeholder="1FMCU0GX…">
      </div>
      <div class="form-group proj-ind-field-sm">
        <label class="proj-ind-label">Existing Unit #</label>
        <input class="ind-existing-unit" type="text" value="${esc(ind.existing_unit_number || "")}">
      </div>
      <div class="form-group proj-ind-field-lg">
        <label class="proj-ind-label">Existing VIN</label>
        <input class="ind-existing-vin" type="text" value="${esc(ind.existing_vin || "")}">
      </div>
      <div class="form-group proj-ind-field-xl">
        <label class="proj-ind-label">Notes</label>
        <input class="ind-notes" type="text" value="${esc(ind.notes || "")}">
      </div>
    </div>
  </div>`;
}

function _ptInfoRow(lbl, val) {
  return `<div class="proj-info-row"><span class="proj-info-lbl">${esc(lbl)}</span><span>${esc(val)}</span></div>`;
}

function _ptUnitFleetSummaryCards(units) {
  if (!units.length) {
    return `<p class="proj-empty-msg">No units defined yet.</p>`;
  }
  return units.map(u => {
    const vm     = _PT.vehicleMap[u.vehicle_model] || {};
    const vmLbl  = vm.make ? `${vm.make} ${vm.model}` : (u.vehicle_model || "—");
    const pLabel = _ptPresetLabel(u);
    const inds   = u.individuals || [];
    let cards;
    if (inds.length) {
      cards = inds.map((ind, j) => {
        const lbl       = _ptUnitLabel(u, ind, j);
        const hasDraft  = !!ind.draft_id;
        const confirmed = !!ind.confirmed;
        return `<div class="proj-ind-card">
          <div class="proj-ind-card-label">${esc(lbl)}</div>
          <div class="proj-ind-card-badges">
            ${hasDraft ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
          </div>
        </div>`;
      }).join("");
    } else {
      const hasDraft = !!u.draft_id;
      cards = `<div class="proj-ind-card">
        <div class="proj-ind-card-label">${esc(u.build_type || "Unit")} ×${u.quantity}</div>
        <div class="proj-ind-card-badges">
          ${hasDraft ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
        </div>
      </div>`;
    }
    return `<div class="proj-unit-group">
      <div class="proj-unit-group-hdr">
        <span class="proj-unit-group-vehicle">${esc(vmLbl)}</span>
        <span class="proj-unit-group-meta">${esc(u.build_type || "—")} · ${u.quantity}× · ${esc(pLabel)}</span>
      </div>
      <div class="proj-ind-grid">${cards}</div>
    </div>`;
  }).join("");
}
