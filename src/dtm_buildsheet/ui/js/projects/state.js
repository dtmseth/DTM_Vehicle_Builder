// ── Projects module: shared state ─────────────────────────────────────────────
// All ui/js/projects/*.js files read/write _PT.* for shared mutable state.
// window.PT_* globals provide onclick= handlers in dynamically generated HTML.

window._PT = {
  // loaded data
  presets:        [],
  vehicles:       [],
  vehicleMap:     {},
  projects:       [],
  agencies:       [],
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
  listMode:       "active", // active | archive

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
  pbeReturnTab:     "overview",
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

function _ptVehicleModelLabel(unit, ind = null) {
  const configured = String(unit?.vehicle_model || "").replace(/^\s*(?:19|20)\d{2}\s+/, "").trim();
  const fallback = String(ind?.model || "").replace(/^\s*(?:19|20)\d{2}\s+/, "").trim();
  const raw = configured || fallback || "Vehicle";
  const folded = raw.toLowerCase().replace(/_/g, " ");
  if (folded.includes("police interceptor utility") || folded.includes("pi utility") || /(^|\W)piu($|\W)/i.test(raw)) return "PIU";
  if (folded.includes("f-150 lightning") || folded.includes("f150 lightning") || folded.includes("lightning")) return "Lightning";
  if (folded.includes("f-150") || /(^|\W)f150($|\W)/i.test(raw)) return "F-150";
  if (folded.includes("durango")) return "Durango";
  if (folded.includes("traverse")) return "Traverse";
  if (folded.includes("tahoe")) return "Tahoe";
  const modelOnly = raw.replace(/^(?:Chevrolet|Chevy|Dodge|Ford|GMC|Ram)\s+/i, "");
  return modelOnly === modelOnly.toUpperCase()
    ? modelOnly.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
    : modelOnly;
}

function _ptDefaultAgencyAbbreviation(name) {
  const value = String(name || "").trim().replace(/\s+/g, " ");
  if (!value) return "";
  const county = value.match(/^(.+?)\s+county\b.*\bsheriff(?:'s|s)?\b/i);
  if (county) return county[1].trim();
  const parenthetical = [...value.matchAll(/\(([^()]*)\)/g)];
  if (parenthetical.length) {
    const candidate = parenthetical[parenthetical.length - 1][1].trim();
    const compact = candidate.replace(/[^A-Za-z0-9]/g, "");
    if (compact.length >= 2 && compact.length <= 10 && candidate === candidate.toUpperCase()) {
      return compact.toUpperCase();
    }
  }
  const words = (value.match(/[A-Za-z0-9]+/g) || [])
    .filter(word => !["and", "of", "the"].includes(word.toLowerCase()));
  if (words.length === 1 && words[0] === words[0].toUpperCase() && words[0].length >= 2 && words[0].length <= 10) {
    return words[0];
  }
  return words
    .map(word => word[0])
    .join("")
    .toUpperCase();
}

function _ptAgencyAbbreviation(project = null) {
  const activeProject = project || _PT.viewProject || _PT.pbeProject || null;
  if (activeProject?.customer) {
    return activeProject.customer.agency_abbreviation ||
      _ptDefaultAgencyAbbreviation(activeProject.customer.agency);
  }
  const agencyId = $("proj-agency-id")?.value?.trim() || "";
  const selected = _PT.agencies.find(item => item.agency_id === agencyId);
  return selected?.effective_abbreviation || selected?.abbreviation ||
    _ptDefaultAgencyAbbreviation($("proj-agency")?.value || "");
}

function _ptUnitLabel(unit, ind, idx, project = null) {
  const activeProject = project || _PT.viewProject || _PT.pbeProject || null;
  const year = String(
    activeProject?.customer?.build_year || $("proj-build-year")?.value || ind?.year || ""
  ).trim();
  const head = [year, _ptAgencyAbbreviation(activeProject), _ptVehicleModelLabel(unit, ind)]
    .filter(Boolean).join(" ") || "Vehicle";
  // Existing/trade-in identifiers are retained only as legacy source
  // metadata. Build identity always comes from the actual vehicle.
  const unitNumber = String(ind?.unit_number || "").trim();
  const vin = String(ind?.vin || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  const identifiers = [];
  if (unitNumber) identifiers.push(`Unit ${unitNumber}`);
  if (vin) identifiers.push(`VIN ${vin.slice(-6)}`);
  if (!identifiers.length && !ind) identifiers.push("Group Build");
  if (!identifiers.length) {
    const token = String(ind?.individual_id || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 8);
    identifiers.push(`Pending ID ${token || String(idx + 1).padStart(4, "0")}`);
  }
  const buildType = String(unit?.build_type || "").trim();
  return [head, buildType, ...identifiers].filter(Boolean).join(" - ");
}

const _PT_CUSTOM_BUILD_TYPE = "__custom__";

function _ptIsCustomBuildType(buildType) {
  const standard = _PT.projectOptions?.build_types || [];
  return !!buildType && !standard.includes(buildType);
}

function _ptBuildTypeOptions(buildType, customOpen = false) {
  const standard = _PT.projectOptions?.build_types || ["Patrol", "Admin", "Unmarked", "K-9", "Fire"];
  const isCustom = customOpen || _ptIsCustomBuildType(buildType);
  return [
    ...standard.map(value => `<option value="${esc(value)}"${value === buildType ? " selected" : ""}>${esc(value)}</option>`),
    `<option value="${_PT_CUSTOM_BUILD_TYPE}"${isCustom ? " selected" : ""}>Add custom build type…</option>`,
  ].join("");
}

function _ptEscAttr(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _ptCustomBuildTypeInput(buildType, className, customOpen = false) {
  if (!customOpen && !_ptIsCustomBuildType(buildType)) return "";
  return `<div class="form-group proj-custom-buildtype-group">
    <label>Custom build type</label>
    <input class="${className}" type="text" value="${_ptEscAttr(buildType)}" placeholder="e.g. Drone Squad" maxlength="80">
    <div class="field-hint">Saved only on this project; it will not be added to the standard list.</div>
  </div>`;
}

function _ptVisiblePresets() {
  return _PT.presets.filter(p =>
    p.preset_id !== "blank_custom" &&
    (p.label || "").toLowerCase() !== "blank"
  );
}

function _ptCanonicalVehicleType(value) {
  const raw = String(value || "").trim();
  if (!raw || _PT.vehicleMap[raw]) return raw;
  const folded = raw.toLowerCase();
  return _PT.vehicles.find(vehicleId => {
    const vehicle = _PT.vehicleMap[vehicleId] || {};
    return vehicleId.toLowerCase() === folded ||
      (vehicle.aliases || []).some(alias => String(alias).trim().toLowerCase() === folded);
  }) || raw;
}

function _ptVehicleConfig(value) {
  return _PT.vehicleMap[_ptCanonicalVehicleType(value)] || {};
}

function _ptVehicleOptionsMarkup(currentValue = "") {
  const canonical = _ptCanonicalVehicleType(currentValue);
  const options = _PT.vehicles.map(vehicleId => {
    const vehicle = _PT.vehicleMap[vehicleId] || {};
    const details = [vehicle.make, vehicle.model].filter(Boolean).join(" ");
    const pending = vehicle.placeholder ? " · artwork pending" : "";
    const label = details ? `${vehicleId} — ${details}${pending}` : `${vehicleId}${pending}`;
    return `<option value="${esc(vehicleId)}"${vehicleId === canonical ? " selected" : ""}>${esc(label)}</option>`;
  });
  if (currentValue && !_PT.vehicleMap[canonical]) {
    options.unshift(`<option value="${esc(currentValue)}" selected>${esc(currentValue)} — historical value; choose a vehicle</option>`);
  }
  return options.join("");
}

// Return presets compatible with a given unit's vehicle_model and build_type.
// Empty vehicle_types / build_types on a preset mean "any" (universal).
function _ptCompatiblePresets(unit) {
  const vm = _ptCanonicalVehicleType(unit?.vehicle_model || "");
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
  const loading = mood === "loading";
  el.classList.toggle("loading", loading);
  el.style.display    = loading ? "flex" : "block";
  el.style.background = mood === "good" ? "#e6f9f1" : mood === "err" ? "#fdecea" : "#f0f4ff";
  el.style.color      = mood === "good" ? "var(--green)" : mood === "err" ? "var(--red)" : "var(--navy)";
  el.replaceChildren();
  if (loading) {
    const spinner = document.createElement("span");
    spinner.className = "dtm-loading-spinner";
    spinner.setAttribute("aria-hidden", "true");
    el.appendChild(spinner);
  }
  const text = document.createElement("span");
  text.textContent = msg;
  el.appendChild(text);
}

function _ptCurrentBuildYear() {
  return ($("proj-build-year")?.value || $("et-build-year")?.value || "").trim();
}

function _ptEnsureIndividuals(u) {
  while (u.individuals.length < u.quantity) {
    const vm = _ptVehicleConfig(u.vehicle_model);
    u.individuals.push({
      individual_id: _ptUuid(),
      unit_number: "", year: _ptCurrentBuildYear(),
      make: vm.make || "", model: vm.model || "",
      color: "", vin: "",
      existing_year: "", existing_make: "", existing_model: "",
      existing_build_type: "", existing_unit_number: "", existing_vin: "",
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
        <label class="proj-ind-label">Actual VIN</label>
        <input class="ind-vin" type="text" value="${esc(ind.vin || "")}" placeholder="1FMCU0GX…">
      </div>
      <div class="form-group proj-ind-field-xl">
        <label class="proj-ind-label">Notes</label>
        <input class="ind-notes" type="text" value="${esc(ind.notes || "")}">
      </div>
    </div>
    <details class="proj-existing-vehicle-fields" ${[
      ind.existing_year, ind.existing_make, ind.existing_model,
      ind.existing_build_type, ind.existing_unit_number, ind.existing_vin,
    ].some(Boolean) ? "open" : ""}>
      <summary>Existing / replaced vehicle (optional)</summary>
      <div class="form-row proj-ind-row-fields">
        <div class="form-group proj-ind-field-xs">
          <label class="proj-ind-label">Year</label>
          <input class="ind-existing-year" type="text" value="${esc(ind.existing_year || "")}" placeholder="Optional">
        </div>
        <div class="form-group proj-ind-field-sm">
          <label class="proj-ind-label">Make</label>
          <input class="ind-existing-make" type="text" value="${esc(ind.existing_make || "")}" placeholder="Optional">
        </div>
        <div class="form-group proj-ind-field-lg">
          <label class="proj-ind-label">Model</label>
          <input class="ind-existing-model" type="text" value="${esc(ind.existing_model || "")}" placeholder="Optional">
        </div>
        <div class="form-group proj-ind-field-sm">
          <label class="proj-ind-label">Build Type</label>
          <input class="ind-existing-build-type" type="text" value="${esc(ind.existing_build_type || "")}" placeholder="Optional">
        </div>
        <div class="form-group proj-ind-field-sm">
          <label class="proj-ind-label">Unit #</label>
          <input class="ind-existing-unit-number" type="text" value="${esc(ind.existing_unit_number || "")}" placeholder="03">
        </div>
        <div class="form-group proj-ind-field-lg">
          <label class="proj-ind-label">VIN</label>
          <input class="ind-existing-vin" type="text" value="${esc(ind.existing_vin || "")}" placeholder="17-char VIN">
        </div>
      </div>
    </details>
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
    const vmLbl  = _ptVehicleModelLabel(u);
    const pLabel = _ptPresetLabel(u);
    const inds   = u.individuals || [];
    let cards;
    if (inds.length) {
      cards = inds.map((ind, j) => {
        const lbl       = _ptUnitLabel(u, ind, j);
        const confirmed = !!ind.confirmed;
        return `<div class="proj-ind-card">
          <div class="proj-ind-card-label">${esc(lbl)}</div>
          <div class="proj-ind-card-badges">
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
          </div>
        </div>`;
      }).join("");
    } else {
      cards = `<div class="proj-ind-card">
        <div class="proj-ind-card-label">${esc(u.build_type || "Unit")} ×${u.quantity}</div>
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
