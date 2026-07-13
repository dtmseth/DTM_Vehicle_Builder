// ── Projects module: wizard / editor (new project form + unit CRUD + review) ───

function _ptLoadForm(project) {
  const c  = project?.customer    || {};
  const pr = project?.preferences || {};

  $("proj-agency").value      = c.agency       || "";
  $("proj-agency-id").value   = c.agency_id    || "";
  $("proj-build-year").value  = c.build_year   || new Date().getFullYear().toString();
  $("proj-quote").value       = c.quote_number || "";
  $("proj-salesrep").value    = c.sales_rep    || "";
  $("proj-salesrep-id").value = c.sales_rep_id || "";

  // Populate camera select from config (single source of truth)
  const cameraEl = $("proj-camera");
  if (cameraEl) {
    const cameraBrands = _PT.projectOptions?.camera_brands || [];
    cameraEl.innerHTML = `<option value="">— Not specified —</option>` +
      cameraBrands.map(b => `<option value="${esc(b)}"${pr.camera_brand === b ? " selected" : ""}>${esc(b)}</option>`).join("");
    if (pr.camera_brand) cameraEl.value = pr.camera_brand;
  }

  // Populate bumper and cage datalists from config
  const bumperList = $("proj-bumper-list");
  if (bumperList) {
    const bumperBrands = _PT.projectOptions?.bumper_brands || [];
    bumperList.innerHTML = bumperBrands.map(m => `<option value="${esc(m)}">`).join("");
  }
  const cageList = $("proj-cage-list");
  if (cageList) {
    const cageBrands = _PT.projectOptions?.cage_brands || [];
    cageList.innerHTML = cageBrands.map(m => `<option value="${esc(m)}">`).join("");
  }
  // No console_brands key in project_options.json — static fallback of the
  // DB's known console manufacturers, same pattern as detail_edit.js.
  const consoleList = $("proj-console-list");
  if (consoleList) {
    const consoleBrands = _PT.projectOptions?.console_brands?.length
      ? _PT.projectOptions.console_brands
      : ["Gamber Johnson", "Havis", "Tiger Tough"];
    consoleList.innerHTML = consoleBrands.map(m => `<option value="${esc(m)}">`).join("");
  }

  $("proj-bumper-brand").value  = pr.push_bumper_brand || "";
  $("proj-cage-brand").value    = pr.cage_brand        || "";
  $("proj-console-brand").value = pr.console_brand     || "";
  $("proj-pref-notes").value    = pr.notes             || "";

  const lightingContainer = $("proj-lighting-checkboxes");
  if (lightingContainer) {
    const lightOptions  = _ptLightingBrandsFromConfig();
    const selectedBrands = new Set(pr.lighting_brands || []);
    lightingContainer.innerHTML = lightOptions.map(m =>
      `<label class="proj-brand-check-label">
        <input type="checkbox" class="proj-lighting-brand-cb" value="${esc(m)}"${selectedBrands.has(m) ? " checked" : ""}> ${esc(m)}
      </label>`
    ).join("");
  }

  _PT.units = (project?.build_units || []).map(u => ({
    uid:           u.unit_id       || _ptUuid(),
    vehicle_model: u.vehicle_model || "",
    build_type:    u.build_type    || "Patrol",
    quantity:      u.quantity      || 1,
    preset_id:     u.preset_id     || "",
    draft_id:      u.draft_id      || null,
    individuals:   (u.individuals  || []).map(ind => ({ ...ind })),
    _indOpen:      false,
  }));
  if (!_PT.units.length) _ptAddUnit();
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
  });
}

function _ptCollectUnits() {
  _PT.units.forEach(u => {
    const row = document.querySelector(`.proj-unit-row[data-uid="${u.uid}"]`);
    if (!row) return;
    u.vehicle_model = row.querySelector(".proj-u-vehicle").value;
    u.build_type    = row.querySelector(".proj-u-buildtype").value;
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
    const localBtVals = [...btVals];
    if (u.build_type && !localBtVals.includes(u.build_type)) localBtVals.push(u.build_type);
    const btOpts = localBtVals.map(t =>
      `<option${t === u.build_type ? " selected" : ""}>${esc(t)}</option>`
    ).join("");

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
    : `<div class="proj-preset-empty">No compatible presets — use the Presets tab to create one.</div>`;
}

window.PT_togglePresetDD = function (uid) {
  document.querySelectorAll(".proj-preset-dropdown").forEach(dd => {
    if (dd.id !== `preset-dd-${uid}`) dd.style.display = "none";
  });
  const dd = $(`preset-dd-${uid}`);
  if (!dd) return;
  if (dd.style.display !== "none") { dd.style.display = "none"; return; }
  dd.innerHTML = _ptPresetDDHtml(_ptCurrentCompatiblePresets(uid), uid);
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
  const quote   = $("proj-quote").value.trim();
  const rep     = $("proj-salesrep").value.trim();
  const nameStr = year ? `${agency} — ${year}` : agency;
  const cLine   = [nameStr, quote, rep].filter(Boolean).join(" · ");

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
  const lightingBrands = Array.from(
    document.querySelectorAll(".proj-lighting-brand-cb:checked")
  ).map(cb => cb.value);

  const p = {
    customer: {
      agency:       $("proj-agency").value.trim(),
      agency_id:    $("proj-agency-id")?.value?.trim()    || "",
      build_year:   $("proj-build-year")?.value?.trim()   || "",
      quote_number: $("proj-quote").value.trim(),
      sales_rep:    $("proj-salesrep").value.trim(),
      sales_rep_id: $("proj-salesrep-id")?.value?.trim()  || "",
    },
    preferences: {
      camera_brand:      $("proj-camera")?.value            || "",
      push_bumper_brand: $("proj-bumper-brand")?.value.trim() || "",
      cage_brand:        $("proj-cage-brand")?.value.trim()   || "",
      console_brand:     $("proj-console-brand")?.value.trim() || "",
      lighting_brands:   lightingBrands,
      notes:             $("proj-pref-notes")?.value.trim()   || "",
    },
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
