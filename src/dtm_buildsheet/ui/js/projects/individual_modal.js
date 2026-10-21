// ── Projects module: individual unit edit modal ────────────────────────────────

let _ptQuoteEditorRefs = [];
let _ptQuoteSearchTimer = null;
let _ptQuoteSearchRevision = 0;
let _ptQuoteEditorReadOnly = false;
let _ptQuoteEditorNeedsReconcile = false;
let _ptIndModalDirty = false;
let _ptIndModalDirtyWired = false;
let _ptIndModalBuybackRevision = 0;

function _ptQuoteMatchLabel(ref) {
  if (ref.match_status === "linked") {
    const bits = [ref.customer, ref.txn_date, ref.estimate_status].filter(Boolean);
    return `Linked to QuickBooks${bits.length ? ` · ${bits.join(" · ")}` : ""}`;
  }
  if (ref.match_status === "not_found") return "No QuickBooks match found yet — it will be checked again on the next sync";
  if (ref.match_status === "multiple") return "Several QuickBooks matches found — select the intended Estimate below";
  if (ref.match_status === "linked_elsewhere") return "That QuickBooks Estimate is linked to another build";
  return "Saved in Builder — will check QuickBooks on the next connection";
}

function _ptRenderQuoteEditor() {
  const list = $("ind-edit-quotes-list");
  if (!list) return;
  if (!_ptQuoteEditorRefs.length) {
    list.innerHTML = `<div class="proj-unit-quotes-empty"><strong>No quotes connected</strong><span>Add a quote number below so it stays with this vehicle.</span></div>`;
  } else {
    list.innerHTML = _ptQuoteEditorRefs.map(ref => `
      <div class="proj-unit-quote${ref.state === "obsolete" ? " proj-unit-quote--obsolete" : ""}">
        <div class="proj-unit-quote-copy">
          <div class="proj-unit-quote-title"><strong class="proj-unit-quote-number">${esc(ref.quote_number)}</strong><span class="proj-unit-quote-state">${ref.state === "obsolete" ? "Obsolete" : "Current"}</span></div>
          <span class="proj-unit-quote-meta">${esc(_ptQuoteMatchLabel(ref))}</span>
        </div>
        ${_ptQuoteEditorReadOnly ? "" : `<div class="proj-unit-quote-actions">
          <button type="button" class="proj-unit-quote-action" onclick="PT_toggleQuoteReference('${esc(ref.reference_id)}')">${ref.state === "obsolete" ? "Restore" : "Mark obsolete"}</button>
          <button type="button" class="proj-unit-quote-action proj-unit-quote-action--remove" onclick="PT_removeQuoteReference('${esc(ref.reference_id)}')">Remove</button>
        </div>`}
      </div>`).join("");
  }
  const controls = $("ind-edit-quotes-controls");
  if (controls) controls.hidden = _ptQuoteEditorReadOnly;
}

function _ptAddQuoteReference(values) {
  const number = String(values?.quote_number || "").trim();
  if (!number) return;
  _ptQuoteSearchRevision += 1;
  _ptQuoteEditorNeedsReconcile = true;
  const duplicate = _ptQuoteEditorRefs.find(ref =>
    String(ref.quote_number || "").trim().toLowerCase() === number.toLowerCase()
  );
  if (duplicate) {
    Object.assign(duplicate, values, {quote_number: number, state: "current"});
  } else {
    _ptQuoteEditorRefs.push({
      reference_id: _ptUuid(), quote_number: number, state: "current",
      match_status: "pending", qb_estimate_id: "", estimate_status: "",
      customer: "", txn_date: "", checked_at: "", ...values,
    });
  }
  const input = $("ind-edit-quote-search");
  if (input) input.value = "";
  $("ind-edit-quote-search-results")?.replaceChildren();
  if ($("ind-edit-quote-search-status")) $("ind-edit-quote-search-status").textContent = "Quote added. Save Details to keep it with this unit.";
  _ptIndModalDirty = true;
  _ptRenderQuoteEditor();
}

window.PT_toggleQuoteReference = function (referenceId) {
  const ref = _ptQuoteEditorRefs.find(item => item.reference_id === referenceId);
  if (!ref || _ptQuoteEditorReadOnly) return;
  ref.state = ref.state === "obsolete" ? "current" : "obsolete";
  if (ref.state === "current" && ref.match_status !== "linked") {
    _ptQuoteEditorNeedsReconcile = true;
  }
  _ptIndModalDirty = true;
  _ptRenderQuoteEditor();
};

window.PT_removeQuoteReference = function (referenceId) {
  if (_ptQuoteEditorReadOnly) return;
  _ptQuoteEditorRefs = _ptQuoteEditorRefs.filter(item => item.reference_id !== referenceId);
  _ptIndModalDirty = true;
  _ptRenderQuoteEditor();
};

window.PT_selectQuoteSearchResult = function (encoded) {
  if (_ptQuoteEditorReadOnly) return;
  let row;
  try { row = JSON.parse(decodeURIComponent(encoded)); } catch (_) { return; }
  _ptAddQuoteReference({
    quote_number: row.number || row.id,
    match_status: "linked",
    qb_estimate_id: row.id || "",
    estimate_status: row.status || "",
    customer: row.customer || "",
    txn_date: row.date || "",
    checked_at: new Date().toISOString(),
  });
};

async function _ptSearchQuoteNumbers() {
  const input = $("ind-edit-quote-search");
  const status = $("ind-edit-quote-search-status");
  const results = $("ind-edit-quote-search-results");
  const query = String(input?.value || "").trim();
  const revision = ++_ptQuoteSearchRevision;
  results?.replaceChildren();
  if (!query) {
    if (status) status.textContent = "";
    return;
  }
  if (!_PT_QUICKBOOKS_UI_ENABLED || !_ptCanManageEstimates() || !(await _ptQbConnected())) {
    if (revision === _ptQuoteSearchRevision && status) {
      status.textContent = "QuickBooks is not connected for this user. Add the number now and Builder will match it on a future connection.";
    }
    return;
  }
  if (status) status.textContent = "Searching QuickBooks Estimates…";
  try {
    const result = await api("/api/quickbooks/estimates/search", {
      query,
      project_id: _PT.indModalFromDetail ? (_PT.viewProject?.project_id || "") : "",
      individual_id: _PT.indModalFromDetail ? (_PT.indModalIndId || "") : "",
    });
    if (revision !== _ptQuoteSearchRevision || !results?.isConnected) return;
    if (!result?.ok) throw new Error(result?.error || "Estimate search failed");
    const rows = result.estimates || [];
    if (status) status.textContent = rows.length
      ? "Select the matching Estimate, or add the typed number without a link."
      : "No matching Estimate was found. You can still add the number and Builder will check again later.";
    results.innerHTML = rows.map(row => {
      const unavailable = !!row.linked_elsewhere;
      const encoded = encodeURIComponent(JSON.stringify(row)).replace(/'/g, "%27");
      return `<button type="button" class="proj-unit-quote-result" ${unavailable ? "disabled" : ""} onclick="PT_selectQuoteSearchResult('${encoded}')"><strong>${esc(row.number || row.id)}</strong><span>${esc([row.customer || "Customer not recorded", row.date || "Undated", row.status || ""].filter(Boolean).join(" · "))}</span>${unavailable ? `<small>Already linked to another build</small>` : `<b aria-hidden="true">›</b>`}</button>`;
    }).join("");
  } catch (_) {
    if (revision === _ptQuoteSearchRevision && status) {
      status.textContent = "QuickBooks search is unavailable. Add the number now and Builder will retry it later.";
    }
  }
}

function _ptPrepareQuoteEditor(ind, readOnly) {
  _ptQuoteEditorReadOnly = !!readOnly;
  _ptQuoteEditorNeedsReconcile = false;
  _ptQuoteEditorRefs = (ind.quote_references || []).map(ref => ({...ref}));
  const input = $("ind-edit-quote-search");
  const add = $("ind-edit-quote-add");
  const status = $("ind-edit-quote-search-status");
  $("ind-edit-quote-search-results")?.replaceChildren();
  if (input) {
    input.value = "";
    input.oninput = () => {
      clearTimeout(_ptQuoteSearchTimer);
      _ptQuoteSearchTimer = setTimeout(_ptSearchQuoteNumbers, 350);
    };
  }
  if (add) add.onclick = () => {
    const number = String(input?.value || "").trim();
    if (!number) return;
    _ptAddQuoteReference({quote_number: number, match_status: "pending"});
  };
  if (status) status.textContent = "";
  _ptRenderQuoteEditor();
}

window.PT_reconcileQuoteReferences = async function () {
  if (!_PT_QUICKBOOKS_UI_ENABLED || !_ptCanManageEstimates()) return null;
  if (!(await _ptQbConnected())) return null;
  try {
    return await api("/api/quickbooks/estimates/reconcile-quotes", {});
  } catch (_) {
    return null;
  }
};

function _ptFillIndModal(unit, ind, title) {
  $("ind-edit-modal-title").textContent = title;
  $("ind-edit-group-vehicle").textContent = _ptVehicleDisplayName(unit);
  $("ind-edit-unit-number").value   = ind.unit_number          || "";
  $("ind-edit-color").value         = ind.color                || "";
  $("ind-edit-vin").value           = ind.vin                  || "";
  $("ind-edit-existing-year").value = ind.existing_year        || "";
  $("ind-edit-existing-make").value = ind.existing_make        || "";
  $("ind-edit-existing-model").value = ind.existing_model      || "";
  $("ind-edit-existing-color").value = ind.existing_color      || "";
  $("ind-edit-existing-unit-number").value = ind.existing_unit_number || "";
  $("ind-edit-existing-vin").value  = ind.existing_vin         || "";
  $("ind-edit-notes").value         = ind.notes                || "";
}

function _ptWireIndModalDirtyState() {
  if (_ptIndModalDirtyWired) return;
  const modal = $("ind-edit-modal");
  if (!modal) return;
  const markDirty = event => {
    if (_ptQuoteEditorReadOnly || !modal.classList.contains("open")) return;
    if (event.target.closest("button")) return;
    _ptIndModalDirty = true;
  };
  modal.addEventListener("input", markDirty);
  modal.addEventListener("change", markDirty);
  _ptIndModalDirtyWired = true;
}

function _ptRenderIndModalSelector(unit, activeId) {
  const shell = $("ind-edit-vehicle-selector-shell");
  const host = $("ind-edit-vehicle-selector");
  if (!shell || !host) return;
  const individuals = unit?.individuals || [];
  shell.hidden = !_PT.indModalFromDetail || individuals.length < 2;
  if (shell.hidden) {
    host.replaceChildren();
    return;
  }
  host.innerHTML = individuals.map((individual, index) => {
    const active = individual.individual_id === activeId;
    const label = _ptUnitLabel(unit, individual, index);
    const detail = individual.vin
      ? `VIN …${String(individual.vin).slice(-6)}`
      : individual.color || "Details not entered";
    return `<button type="button" role="tab" aria-selected="${active ? "true" : "false"}" class="vehicle-details-selector-option${active ? " active" : ""}" onclick="PT_selectIndModalVehicle('${esc(individual.individual_id)}')"><strong>${esc(label)}</strong><span>${esc(detail)}</span></button>`;
  }).join("");
}

function _ptBuybackAmount(record) {
  const amount = String(record?.sale_amount || "").trim();
  return amount ? `$${amount.replace(/^\$/, "")}` : "Sale amount not entered";
}

function _ptRenderIndModalBuyback(record) {
  const host = $("ind-edit-buyback-content");
  if (!host) return;
  if (!record) {
    host.innerHTML = `<div><span>Buyback / sale record</span><strong>No record created yet</strong><small>Create the legal paper record for this existing vehicle when it is purchased or sold.</small></div>${_ptCanEditProjects() ? `<button type="button" class="btn btn-secondary btn-sm" onclick="PT_openIndModalVehicleSale()">Create record</button>` : ""}`;
    return;
  }
  const vehicle = [record.vehicle_year, record.vehicle_make, record.vehicle_model].filter(Boolean).join(" ") || "Vehicle details not entered";
  const status = record.date_sold
    ? `Sold ${record.date_sold}${record.buyer_name ? ` to ${record.buyer_name}` : ""}`
    : record.dvs_flagged_resale_date ? `Held for resale since ${record.dvs_flagged_resale_date}` : "Sale is not recorded yet";
  const details = [record.quote_number ? `Quote ${record.quote_number}` : "", record.date_sold ? _ptBuybackAmount(record) : ""].filter(Boolean).join(" · ");
  host.innerHTML = `<div><span>Buyback / sale record</span><strong>${esc(vehicle)}</strong><small>${esc(status)}${details ? ` · ${esc(details)}` : ""}</small></div><button type="button" class="btn btn-secondary btn-sm" onclick="PT_openIndModalVehicleSale()">Open record</button>`;
}

async function _ptLoadIndModalBuyback(projectId, individualId) {
  const section = $("ind-edit-buyback");
  const host = $("ind-edit-buyback-content");
  if (!section || !host) return;
  section.hidden = !_PT.indModalFromDetail;
  if (section.hidden) return;
  const revision = ++_ptIndModalBuybackRevision;
  host.innerHTML = `<div><span>Buyback / sale record</span><strong>Checking for a linked record…</strong></div>`;
  try {
    const result = await api("/api/vehicle-sales/lookup", {
      project_id: projectId,
      individual_id: individualId,
    });
    if (revision !== _ptIndModalBuybackRevision || !host.isConnected) return;
    if (!result?.ok) throw new Error(result?.error || "Record lookup failed");
    _ptRenderIndModalBuyback(result.record || null);
  } catch (_) {
    if (revision === _ptIndModalBuybackRevision) {
      host.innerHTML = `<div><span>Buyback / sale record</span><strong>Record status unavailable</strong><small>You can still open the buyback / sale workspace.</small></div>${_ptCanEditProjects() ? `<button type="button" class="btn btn-secondary btn-sm" onclick="PT_openIndModalVehicleSale()">Open workspace</button>` : ""}`;
    }
  }
}

function _ptApplyIndModalFields(unit, ind) {
  const identity = _ptVehicleIdentity(unit);
  ind.unit_number          = $("ind-edit-unit-number").value.trim();
  ind.year                 = identity.model_year || ind.year || "";
  ind.make                 = identity.make || "";
  ind.model                = identity.model || "";
  ind.color                = $("ind-edit-color").value.trim();
  ind.vin                  = $("ind-edit-vin").value.trim();
  ind.existing_year        = $("ind-edit-existing-year").value.trim();
  ind.existing_make        = $("ind-edit-existing-make").value.trim();
  ind.existing_model       = $("ind-edit-existing-model").value.trim();
  ind.existing_color       = $("ind-edit-existing-color").value.trim();
  ind.existing_unit_number = $("ind-edit-existing-unit-number").value.trim();
  ind.existing_vin         = $("ind-edit-existing-vin").value.trim();
  ind.notes                = $("ind-edit-notes").value.trim();
  ind.quote_references     = _ptQuoteEditorRefs.map(ref => ({...ref}));
}

function _ptSetIndividualModalReadOnly(readOnly) {
  const modal = $("ind-edit-modal");
  if (!modal) return;
  modal.querySelectorAll("input, textarea, select").forEach(field => {
    field.disabled = !!readOnly;
  });
  const save = $("ind-edit-save");
  if (save) save.hidden = !!readOnly;
  const setup = $("ind-edit-setup-build");
  if (setup) setup.hidden = !!readOnly;
  const changeGroup = $("ind-edit-change-group-vehicle");
  if (changeGroup) changeGroup.hidden = !!readOnly || !_PT.indModalFromDetail;
}

// Opened from wizard Review tab
window.PT_openIndModal = function (uid, indIdx) {
  if (!_ptCanEditProjects()) return;
  _PT.indModalUid        = uid;
  _PT.indModalIdx        = indIdx;
  _PT.indModalFromDetail = false;
  _PT.indModalUnitId     = null;
  _PT.indModalIndId      = null;
  const u = _PT.units.find(x => x.uid === uid);
  if (!u) return;
  _ptEnsureIndividuals(u);
  const ind = u.individuals[indIdx];
  if (!ind) return;
  _ptFillIndModal(u, ind, _ptUnitLabel(u, ind, indIdx));
  _ptSetIndividualModalReadOnly(false);
  _ptPrepareQuoteEditor(ind, false);
  _ptRenderIndModalSelector(u, ind.individual_id);
  $("ind-edit-buyback").hidden = true;
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.hidden = true;
  $("ind-edit-modal-status").textContent = "";
  _ptWireIndModalDirtyState();
  _ptIndModalDirty = false;
  $("ind-edit-modal").classList.add("open");
};

// Opened from detail Builds tab
window.PT_openDetailIndModal = function (projectId, unitId, individualId) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units.find(u => u.unit_id === unitId);
  if (!unit) return;
  const ind = unit.individuals.find(i => i.individual_id === individualId);
  if (!ind) return;
  _PT.indModalFromDetail = true;
  _PT.indModalUnitId     = unitId;
  _PT.indModalIndId      = individualId;
  _PT.indModalOriginalNotes = String(ind.notes || "");
  _PT.indModalUid        = null;
  _PT.indModalIdx        = null;
  _PT.viewProject        = project;
  const indIdx = unit.individuals.indexOf(ind);
  _ptFillIndModal(unit, ind, _ptUnitLabel(unit, ind, indIdx));
  const readOnly = !_ptCanEditProjects();
  _ptSetIndividualModalReadOnly(readOnly);
  _ptPrepareQuoteEditor(ind, readOnly);
  _ptRenderIndModalSelector(unit, individualId);
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.hidden = !_ptCanEditProjects();
  $("ind-edit-modal-status").textContent = "";
  _ptWireIndModalDirtyState();
  _ptIndModalDirty = false;
  $("ind-edit-modal").classList.add("open");
  _ptLoadIndModalBuyback(projectId, individualId);
};

window.PT_closeIndModal = function () {
  $("ind-edit-modal").classList.remove("open");
  _PT.indModalFromDetail = false;
  _ptIndModalDirty = false;
  _ptIndModalBuybackRevision += 1;
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.hidden = true;
};

window.PT_selectIndModalVehicle = async function (individualId) {
  if (!_PT.indModalFromDetail || individualId === _PT.indModalIndId) return;
  const projectId = _PT.viewProject?.project_id;
  const unitId = _PT.indModalUnitId;
  if (!projectId || !unitId) return;
  if (_ptIndModalDirty && _ptCanEditProjects()) {
    await _ptSaveDetailIndModal(false, individualId);
    return;
  }
  PT_openDetailIndModal(projectId, unitId, individualId);
};

window.PT_editIndUnitGroupVehicle = async function () {
  if (!_PT.indModalFromDetail || !_ptCanEditProjects()) return;
  const unitId = _PT.indModalUnitId;
  if (_ptIndModalDirty && !(await _ptSaveDetailIndModal(false))) return;
  else if ($("ind-edit-modal")?.classList.contains("open")) PT_closeIndModal();
  _ptSetDetailTab("edit");
  PT_enterEditMode(false, unitId);
};

window.PT_openIndModalVehicleSale = async function () {
  if (!_PT.indModalFromDetail || !_ptCanEditProjects()) return;
  const projectId = _PT.viewProject?.project_id;
  const unitId = _PT.indModalUnitId;
  const individualId = _PT.indModalIndId;
  if (!projectId || !unitId || !individualId) return;
  if (_ptIndModalDirty && !(await _ptSaveDetailIndModal(false))) return;
  else if ($("ind-edit-modal")?.classList.contains("open")) PT_closeIndModal();
  await PT_openVehicleSale(projectId, unitId, individualId);
};

window.PT_saveIndModal = function () {
  if (!_ptCanEditProjects()) return;
  if (_PT.indModalFromDetail) {
    _ptSaveDetailIndModal(false);
    return;
  }
  // Wizard context: update _PT.units array
  const u = _PT.units.find(x => x.uid === _PT.indModalUid);
  if (!u) return;
  _ptEnsureIndividuals(u);
  const ind = u.individuals[_PT.indModalIdx];
  if (!ind) return;
  _ptApplyIndModalFields(u, ind);
  PT_closeIndModal();
  _ptRenderReview();
};

async function _ptSaveDetailIndModal(thenBuild, nextIndividualId = "") {
  const project = _PT.projects.find(p => p.project_id === _PT.viewProject?.project_id);
  if (!project) return false;
  const unit = project.build_units.find(u => u.unit_id === _PT.indModalUnitId);
  if (!unit) return false;
  const ind = unit.individuals.find(i => i.individual_id === _PT.indModalIndId);
  if (!ind) return false;

  const projectId = project.project_id;
  const unitId = unit.unit_id;
  const individualId = ind.individual_id;
  _ptApplyIndModalFields(unit, ind);
  ind.notes_expected       = _PT.indModalOriginalNotes;
  const status = $("ind-edit-modal-status");
  const saveButton = $("ind-edit-save");
  if (status) status.textContent = nextIndividualId ? "Saving before switching vehicles…" : "Saving vehicle details…";
  if (saveButton) saveButton.disabled = true;

  try {
    const res = await api("/api/project/save", {
      ...project,
      expected_updated_at: project.updated_at,
      expected_record_revision: project.record_revision,
    });
    if (res.ok) {
      toast("Unit details saved", "success");
      if (_ptQuoteEditorNeedsReconcile) await window.PT_reconcileQuoteReferences();
      await _ptLoadAll();
      _PT.viewProject = _PT.projects.find(p => p.project_id === res.project_id) || _PT.viewProject;
      _ptRenderOverview(_PT.viewProject);
      _ptRenderEditTab(_PT.viewProject, false);
      _ptRenderBuildsTab(_PT.viewProject);
      PT_closeIndModal();
      if (nextIndividualId) {
        PT_openDetailIndModal(projectId, unitId, nextIndividualId);
        return true;
      }
    } else {
      toast(res.error || "Save failed", "error");
      if (status) status.textContent = res.error || "Vehicle details could not be saved.";
      _ptIndModalDirty = true;
      return false;
    }
  } catch (e) {
    toast(e.message || "Save failed", "error");
    if (status) status.textContent = e.message || "Vehicle details could not be saved.";
    _ptIndModalDirty = true;
    return false;
  } finally {
    if (saveButton) saveButton.disabled = false;
  }

  if (thenBuild) {
    const proj = _PT.projects.find(p => p.project_id === projectId);
    if (!proj) return true;
    const unitIdx = proj.build_units.findIndex(u => u.unit_id === unitId);
    if (unitIdx === -1) return true;
    const theUnit = proj.build_units[unitIdx];
    const theInd  = theUnit.individuals.find(i => i.individual_id === individualId);
    if (theInd?.draft_id) {
      await _ptShowBuildEditor(theInd.draft_id, theUnit, proj, "overview", theInd);
    } else {
      PT_startBuildIndividual(proj.project_id, unitIdx, individualId);
    }
  }
  return true;
}

window.PT_setupBuildFromModal = function () {
  if (!_ptCanEditProjects()) return;
  if (!_PT.indModalFromDetail) return;
  _ptSaveDetailIndModal(true);
};

window.PT_confirmIndividualDialog = function (projectId, unitId, individualId, label) {
  const ok = confirm(
    `Confirm this build as correct?\n\n` +
    `"${label || "This unit"}" will be marked as reviewed and approved for production.\n\n` +
    `This is a sign-off that means: the parts list, quantities, locations, and vehicle ` +
    `details have been verified and are ready to go. The card will show a "✓ confirmed" badge.\n\n` +
    `You can remove the confirmation at any time by editing the project.`
  );
  if (ok) PT_confirmIndividual(projectId, unitId, individualId);
};

window.PT_confirmIndividual = async function (projectId, unitId, individualId) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units.find(u => u.unit_id === unitId);
  if (!unit) return;
  const ind = unit.individuals.find(i => i.individual_id === individualId);
  if (!ind) return;
  ind.confirmed    = true;
  ind.confirmed_at = new Date().toISOString();
  try {
    const res = await api("/api/project/save", {
      ...project,
      expected_updated_at: project.updated_at,
      expected_record_revision: project.record_revision,
    });
    if (res.ok) {
      toast("Unit confirmed ✓", "success");
      await _ptLoadAll();
      _PT.viewProject = _PT.projects.find(p => p.project_id === projectId) || _PT.viewProject;
      _ptRenderOverview(_PT.viewProject);
      _ptRenderEditTab(_PT.viewProject, false);
      _ptRenderBuildsTab(_PT.viewProject);
    } else {
      toast(res.error || "Confirm failed", "error");
    }
  } catch (e) {
    toast(e.message || "Confirm failed", "error");
  }
};
