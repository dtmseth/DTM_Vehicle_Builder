// ── Projects module: wizard / editor (new project form + unit CRUD + review) ───

function _ptLoadForm(project) {
  const c  = project?.customer    || {};
  const pr = project?.preferences || {};

  $("proj-agency").value      = c.agency       || "";
  $("proj-agency-id").value   = c.agency_id    || "";
  $("proj-build-year").value  = c.build_year   || new Date().getFullYear().toString();
  $("proj-salesrep").value    = c.sales_rep    || "";
  $("proj-salesrep-id").value = c.sales_rep_id || "";

  _ptSetPreferenceForm("proj", pr);
  _ptUpdateProjectPreferenceSource(c.agency_id);

  _PT.units = (project?.build_units || []).map(u => ({
    uid:           u.unit_id       || _ptUuid(),
    vehicle_model: u.vehicle_model || "",
    build_type:    u.build_type    || "Patrol",
    quantity:      u.quantity      || 1,
    preset_id:     u.preset_id     || "",
    draft_id:      u.draft_id      || null,
    individuals:   (u.individuals  || []).map(ind => ({ ...ind })),
    _indOpen:      false,
    _customBuildTypeOpen: _ptIsCustomBuildType(u.build_type || ""),
  }));
  if (!_PT.units.length) _ptAddUnit();
  _ptRenderUnits();
}

function _ptUpdateProjectPreferenceSource(agencyId, agency = null) {
  const message = $("proj-preferences-source");
  if (!message) return;
  const selected = agency || _PT.agencies.find(item => item.agency_id === agencyId);
  message.textContent = selected
    ? `Starting with ${selected.name}'s saved equipment defaults. Change any choice below only when this project is an exception.`
    : "Select a saved agency to load its normal equipment choices. Changes here apply only to this project.";
}

function _ptApplyAgencyDefaults(agency) {
  const agencyId = agency?.agency_id || $("proj-agency-id")?.value?.trim() || "";
  const selected = _PT.agencies.find(item => item.agency_id === agencyId) || agency;
  _ptUpdateProjectPreferenceSource(agencyId, selected);
  if (!selected) return;
  _ptSetPreferenceForm("proj", selected.default_preferences || {});
  _ptRenderUnits();
}

function _ptAddUnit() {
  _PT.units.push({
    uid:           _ptUuid(),
    vehicle_model: _PT.vehicles[0] || "",
    build_type:    "Patrol",
    quantity:      1,
    preset_id:     "",
    draft_id:      null,
    individuals:   [],
    _indOpen:      false,
    _customBuildTypeOpen: false,
  });
}

function _ptCollectUnits() {
  _PT.units.forEach(u => {
    const row = document.querySelector(`.proj-unit-row[data-uid="${u.uid}"]`);
    if (!row) return;
    u.vehicle_model = row.querySelector(".proj-u-vehicle").value;
    const buildType = row.querySelector(".proj-u-buildtype");
    if (buildType?.value === _PT_CUSTOM_BUILD_TYPE) {
      u._customBuildTypeOpen = true;
      u.build_type = row.querySelector(".proj-u-buildtype-custom")?.value.trim() || u.build_type || "";
    } else {
      u._customBuildTypeOpen = false;
      u.build_type = buildType?.value || "";
    }
    u.quantity      = Math.max(1, parseInt(row.querySelector(".proj-u-qty").value, 10) || 1);

    const indRows = row.querySelectorAll(".proj-ind-row");
    if (indRows.length) {
      const vm = _PT.vehicleMap[u.vehicle_model] || {};
      u.individuals = Array.from(indRows).map(ir => ({
        individual_id:        ir.dataset.iid,
        unit_number:          ir.querySelector(".ind-unit-number")?.value.trim()    || "",
        year:                 ir.querySelector(".ind-year")?.value.trim()           || "",
        make:                 vm.make  || "",
        model:                vm.model || "",
        color:                ir.querySelector(".ind-color")?.value.trim()          || "",
        vin:                  ir.querySelector(".ind-vin")?.value.trim()            || "",
        existing_unit_number: ir.querySelector(".ind-existing-unit")?.value.trim() || "",
        existing_vin:         ir.querySelector(".ind-existing-vin")?.value.trim()  || "",
        notes:                ir.querySelector(".ind-notes")?.value.trim()         || "",
        draft_id:             ir.dataset.draftId || null,
      }));
    }
  });
}

function _ptRenderUnits() {
  const vOpts = _PT.vehicles.map(v => {
    const vm    = _PT.vehicleMap[v] || {};
    const label = vm.make ? `${v} — ${vm.make} ${vm.model}` : v;
    return `<option value="${esc(v)}">${esc(label)}</option>`;
  }).join("");

  const btVals       = _PT.projectOptions?.build_types || ["Patrol", "Admin", "Unmarked", "K-9", "Fire"];
  const currentAgency = $("proj-agency")?.value?.trim() || "Agency";

  $("proj-units-list").innerHTML = _PT.units.map((u, i) => {
    const btOpts = _ptBuildTypeOptions(u.build_type, u._customBuildTypeOpen);

    const selPreset = _ptVisiblePresets().find(p => p.preset_id === u.preset_id);
    const presetChip = selPreset
      ? `<span class="proj-preset-chip">${esc(selPreset.label)} <span class="proj-preset-chip-x" onclick="PT_clearPreset('${esc(u.uid)}')">×</span></span>`
      : `<span class="proj-preset-none">No preset selected</span>`;

    const hasInds    = u.individuals.some(ind => ind.unit_number || ind.vin || ind.year || ind.color);
    const indBtnLbl  = `Add Individual Unit Details (×${u.quantity})`;
    const indBody    = u._indOpen
      ? (() => {
          _ptEnsureIndividuals(u);
          return u.individuals.slice(0, u.quantity).map((ind, n) =>
            `<div class="proj-ind-section-item">
              <div class="proj-ind-sub-label">${esc(_ptUnitLabel(u, ind, n))}</div>
              ${_ptIndRowHtml(ind)}
            </div>`
          ).join("");
        })()
      : "";

    return `<div class="proj-unit-row" data-uid="${esc(u.uid)}">
      <div class="proj-unit-header">
        <span class="proj-unit-label">Unit Group ${i + 1}</span>
        ${_PT.units.length > 1
          ? `<button class="btn btn-danger btn-sm" onclick="PT_rmUnit('${esc(u.uid)}')">Remove</button>`
          : ""}
      </div>
      <div class="form-row">
        <div class="form-group proj-vehicle-group">
          <label>Vehicle Model</label>
          <select class="proj-u-vehicle">${vOpts}</select>
        </div>
        <div class="form-group proj-buildtype-group">
          <label>Build Type</label>
          <select class="proj-u-buildtype">${btOpts}</select>
        </div>
        <div class="form-group proj-qty-group">
          <label>Qty</label>
          <input type="number" class="proj-u-qty" min="1" value="${u.quantity}">
        </div>
      </div>
      ${_ptCustomBuildTypeInput(u.build_type, "proj-u-buildtype-custom", u._customBuildTypeOpen)}
      <div class="proj-preset-row">
        <label class="proj-preset-label">Preset</label>
        <div class="proj-preset-selected">${presetChip}</div>
        <div class="proj-preset-btns">
          <button class="btn btn-secondary btn-sm"
            onclick="PT_agencyPresets('${esc(u.uid)}', '${esc(currentAgency)}')">
            ${esc(currentAgency)} Presets
          </button>
          <button class="btn btn-secondary btn-sm" onclick="PT_togglePresetDD('${esc(u.uid)}')">
            All Presets ▾
          </button>
        </div>
        <div class="proj-preset-dropdown" id="preset-dd-${esc(u.uid)}" style="display:none"></div>
      </div>
      <div class="proj-ind-section">
        <button class="btn btn-secondary btn-sm proj-ind-toggle-btn"
          onclick="PT_toggleIndividuals('${esc(u.uid)}')">
          ${esc(indBtnLbl)}
        </button>
        <p class="proj-ind-hint">If you don't set these details now, you'll have the option to add them later.</p>
        ${hasInds
          ? `<span class="proj-ind-configured">✓ ${u.individuals.filter(i=>i.unit_number||i.vin).length} unit${u.individuals.filter(i=>i.unit_number||i.vin).length!==1?"s":""} configured</span>`
          : ""}
        <div class="proj-ind-panel" style="${u._indOpen ? "" : "display:none"}">
          ${indBody}
        </div>
      </div>
    </div>`;
  }).join("");

  _PT.units.forEach(u => {
    const row = document.querySelector(`.proj-unit-row[data-uid="${u.uid}"]`);
    if (!row) return;
    row.querySelector(".proj-u-vehicle").value = u.vehicle_model;
    const qtyInput = row.querySelector(".proj-u-qty");
    const indBtn   = row.querySelector(".proj-ind-toggle-btn");
    const btSelect = row.querySelector(".proj-u-buildtype");
    btSelect?.addEventListener("change", () => {
      _ptCollectUnits();
      const live = _PT.units.find(item => item.uid === u.uid);
      if (live && btSelect.value === _PT_CUSTOM_BUILD_TYPE) {
        live._customBuildTypeOpen = true;
        if (!_ptIsCustomBuildType(live.build_type)) live.build_type = "";
      }
      if (live?.preset_id && !_ptCompatiblePresets(live).some(p => p.preset_id === live.preset_id)) {
        live.preset_id = "";
      }
      _ptRenderUnits();
      if (btSelect.value === _PT_CUSTOM_BUILD_TYPE) {
        document.querySelector(`.proj-unit-row[data-uid="${u.uid}"] .proj-u-buildtype-custom`)?.focus();
      }
    });
    qtyInput?.addEventListener("input", () => {
      const qty = Math.max(1, parseInt(qtyInput.value, 10) || 1);
      if (indBtn) indBtn.textContent = `Add Individual Unit Details (×${qty})`;
    });
  });
}

window.PT_rmUnit = function (uid) {
  _ptCollectUnits();
  _PT.units = _PT.units.filter(u => u.uid !== uid);
  if (!_PT.units.length) _ptAddUnit();
  _ptRenderUnits();
};

window.PT_toggleIndividuals = function (uid) {
  _ptCollectUnits();
  const u = _PT.units.find(x => x.uid === uid);
  if (!u) return;
  u._indOpen = !u._indOpen;
  _ptRenderUnits();
};

// ── Preset picker ──────────────────────────────────────────────────────────────

function _ptCurrentCompatiblePresets(uid) {
  const row = document.querySelector(`.proj-unit-row[data-uid="${uid}"]`);
  const vm  = row?.querySelector(".proj-u-vehicle")?.value   || "";
  const bt  = row?.querySelector(".proj-u-buildtype")?.value || "";
  return _ptVisiblePresets().filter(p => {
    const vOk = !p.vehicle_types?.length || p.vehicle_types.includes(vm);
    const bOk = !p.build_types?.length   || p.build_types.includes(bt);
    return vOk && bOk;
  });
}

function _ptPresetDDHtml(presets, uid) {
  return presets.length
    ? presets.map(p =>
        `<div class="proj-preset-option" onclick="PT_selectPreset('${esc(uid)}','${esc(p.preset_id)}')">
          <strong>${esc(p.label)}</strong>
          ${p.description ? `<span class="proj-preset-desc"> — ${esc(p.description)}</span>` : ""}
        </div>`
      ).join("")
    : `<div class="proj-preset-empty">No presets available — use the Presets tab to create one.</div>`;
}

window.PT_togglePresetDD = function (uid) {
  document.querySelectorAll(".proj-preset-dropdown").forEach(dd => {
    if (dd.id !== `preset-dd-${uid}`) dd.style.display = "none";
  });
  const dd = $(`preset-dd-${uid}`);
  if (!dd) return;
  if (dd.style.display !== "none") { dd.style.display = "none"; return; }
  // "All Presets" is intentionally literal. Vehicle/build compatibility is
  // useful for the agency shortcut, but must never hide choices from All.
  dd.innerHTML = _ptPresetDDHtml(_ptVisiblePresets(), uid);
  dd.style.display = "";
};

window.PT_selectAgency = function (agencyId, name) {
  $("proj-agency").value    = name;
  $("proj-agency-id").value = agencyId;
  $("proj-agency-suggestions").style.display = "none";
};

window.PT_agencyPresets = function (uid, agencyName) {
  const agencyId = $("proj-agency-id")?.value?.trim() || "";
  if (!agencyId) { toast("No agency selected for this project", "info"); return; }
  const agencyPresets = _ptCurrentCompatiblePresets(uid).filter(p =>
    (p.agency_ids || []).includes(agencyId)
  );
  document.querySelectorAll(".proj-preset-dropdown").forEach(dd => {
    if (dd.id !== `preset-dd-${uid}`) dd.style.display = "none";
  });
  const dd = $(`preset-dd-${uid}`);
  if (!dd) return;
  if (!agencyPresets.length) { toast(`No presets saved for ${agencyName || "this agency"} yet`, "info"); return; }
  dd.innerHTML = _ptPresetDDHtml(agencyPresets, uid);
  dd.style.display = "";
};

window.PT_selectPreset = function (uid, presetId) {
  _ptCollectUnits();
  const u = _PT.units.find(x => x.uid === uid);
  if (!u) return;
  u.preset_id = presetId;
  const dd = $(`preset-dd-${uid}`);
  if (dd) dd.style.display = "none";
  _ptRenderUnits();
};

window.PT_clearPreset = function (uid) {
  const u = _PT.units.find(x => x.uid === uid);
  if (!u) return;
  u.preset_id = "";
  _ptRenderUnits();
};

// ── Review tab ─────────────────────────────────────────────────────────────────

function _ptRenderReview() {
  _ptCollectUnits();
  const agency  = $("proj-agency").value.trim()     || "—";
  const year    = $("proj-build-year").value.trim()  || "";
  const rep     = $("proj-salesrep").value.trim();
  const nameStr = year ? `${agency} — ${year}` : agency;
  const cLine   = [nameStr, rep].filter(Boolean).join(" · ");

  const unitRows = _PT.units.map((u, i) => {
    const preset  = _PT.presets.find(p => p.preset_id === u.preset_id);
    const pLabel  = preset ? preset.label : (u.preset_id || "No Preset");
    const vm      = _PT.vehicleMap[u.vehicle_model] || {};
    const vmLabel = vm.make ? `${vm.make} ${vm.model}` : u.vehicle_model;
    _ptEnsureIndividuals(u);
    const indBtns = u.individuals.slice(0, u.quantity).map((ind, j) =>
      `<button class="btn btn-secondary btn-sm"
        onclick="PT_openIndModal('${esc(u.uid)}', ${j})">
        ✏ ${esc(_ptUnitLabel(u, ind, j))}</button>`
    ).join("");
    return `<div class="proj-unit-summary">
      <div class="proj-unit-summary-info">
        <strong>${esc(vmLabel || "—")}</strong>
        <span class="proj-unit-summary-meta"> — ${esc(u.build_type || "—")} · ${u.quantity}× · ${esc(pLabel)}</span>
      </div>
      <div class="proj-unit-summary-btns">${indBtns}</div>
    </div>`;
  }).join("");

  $("proj-review-content").innerHTML = `
    <div class="proj-review-section">
      <div class="proj-review-label">Customer</div>
      <div class="proj-review-detail">${esc(cLine)}</div>
    </div>
    <div class="proj-review-section">
      <div class="proj-review-label">Fleet Units</div>
      ${unitRows}
    </div>`;

  const hint = $("proj-review-hint");
  if (hint) {
    hint.innerHTML = _PT.isWizard
      ? `Review your project, then click <strong>Finish</strong> to save. Click any unit button to edit its details.`
      : `Review your project. Click any unit button to edit its details before saving.`;
  }
}

// ── Payload builder ────────────────────────────────────────────────────────────

function _ptBuildPayload() {
  _ptCollectUnits();

  const p = {
    customer: {
      agency:       $("proj-agency").value.trim(),
      agency_id:    $("proj-agency-id")?.value?.trim()    || "",
      build_year:   $("proj-build-year")?.value?.trim()   || "",
      sales_rep:    $("proj-salesrep").value.trim(),
      sales_rep_id: $("proj-salesrep-id")?.value?.trim()  || "",
    },
    preferences: _ptPreferencePayload("proj"),
    build_units: _PT.units.map(u => ({
      unit_id:       u.uid,
      vehicle_model: u.vehicle_model,
      build_type:    u.build_type,
      quantity:      u.quantity,
      preset_id:     u.preset_id,
      draft_id:      u.draft_id || null,
      individuals:   u.individuals.map(ind => ({
        individual_id:        ind.individual_id,
        unit_number:          ind.unit_number          || "",
        year:                 ind.year                 || "",
        make:                 ind.make                 || "",
        model:                ind.model                || "",
        color:                ind.color                || "",
        vin:                  ind.vin                  || "",
        existing_unit_number: ind.existing_unit_number || "",
        existing_vin:         ind.existing_vin         || "",
        notes:                ind.notes                || "",
        draft_id:             ind.draft_id             || null,
      })),
    })),
  };
  if (_PT.editId) p.project_id = _PT.editId;
  return p;
}

// ── Save ───────────────────────────────────────────────────────────────────────

async function _ptSaveProject() {
  if (_PT.saving) return;
  _PT.saving = true;
  const statusEl = $("proj-op-status");
  const finBtn   = $("proj-btn-finish");
  const saveBtn  = $("proj-btn-save");
  if (finBtn)  finBtn.disabled  = true;
  if (saveBtn) saveBtn.disabled = true;
  if (statusEl) _ptSetStatus(statusEl, "Saving…", "ok");

  try {
    const res = await api("/api/project/save", _ptBuildPayload());
    if (res.ok) {
      _PT.editId = res.project_id;
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === _PT.editId);
      toast("Project saved", "success");
      if (statusEl) statusEl.style.display = "none";
      setTimeout(() => {
        if (updated) _ptShowDetail(updated);
        else _ptShowList();
      }, 300);
    } else {
      const msg = res.error || "Save failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    }
  } catch (e) {
    const msg = e.message || "Unexpected error";
    toast(msg, "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
  } finally {
    if (finBtn)  finBtn.disabled  = false;
    if (saveBtn) saveBtn.disabled = false;
    _PT.saving = false;
  }
}

// ── Validation ─────────────────────────────────────────────────────────────────

function _ptOkCustomer() {
  if (!$("proj-agency").value.trim()) {
    toast("Agency name is required", "error");
    $("proj-agency").focus();
    return false;
  }
  if (!$("proj-salesrep").value.trim()) {
    toast("Sales rep is required", "error");
    $("proj-salesrep").focus();
    return false;
  }
  return true;
}
