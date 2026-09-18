// ── Projects module: individual unit edit modal ────────────────────────────────

let _ptQuoteEditorRefs = [];
let _ptQuoteSearchTimer = null;
let _ptQuoteSearchRevision = 0;
let _ptQuoteEditorReadOnly = false;
let _ptQuoteEditorNeedsReconcile = false;

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
    list.innerHTML = `<span class="proj-unit-quote-meta">No quote numbers recorded for this unit.</span>`;
  } else {
    list.innerHTML = _ptQuoteEditorRefs.map(ref => `
      <div class="proj-unit-quote${ref.state === "obsolete" ? " proj-unit-quote--obsolete" : ""}">
        <div class="proj-unit-quote-copy">
          <strong class="proj-unit-quote-number">${esc(ref.quote_number)}</strong>
          <span class="proj-unit-quote-meta">${esc(ref.state === "obsolete" ? `Obsolete · ${_ptQuoteMatchLabel(ref)}` : _ptQuoteMatchLabel(ref))}</span>
        </div>
        ${_ptQuoteEditorReadOnly ? "" : `<div class="proj-unit-quote-actions">
          <button type="button" class="btn btn-secondary btn-sm" onclick="PT_toggleQuoteReference('${esc(ref.reference_id)}')">${ref.state === "obsolete" ? "Restore" : "Mark obsolete"}</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="PT_removeQuoteReference('${esc(ref.reference_id)}')">Remove</button>
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
  _ptRenderQuoteEditor();
}

window.PT_toggleQuoteReference = function (referenceId) {
  const ref = _ptQuoteEditorRefs.find(item => item.reference_id === referenceId);
  if (!ref || _ptQuoteEditorReadOnly) return;
  ref.state = ref.state === "obsolete" ? "current" : "obsolete";
  if (ref.state === "current" && ref.match_status !== "linked") {
    _ptQuoteEditorNeedsReconcile = true;
  }
  _ptRenderQuoteEditor();
};

window.PT_removeQuoteReference = function (referenceId) {
  if (_ptQuoteEditorReadOnly) return;
  _ptQuoteEditorRefs = _ptQuoteEditorRefs.filter(item => item.reference_id !== referenceId);
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
      const label = `${row.number || row.id} · ${row.customer || "Customer not recorded"} · ${row.date || "Undated"}${row.status ? ` · ${row.status}` : ""}${unavailable ? " · Linked to another build" : ""}`;
      const encoded = encodeURIComponent(JSON.stringify(row)).replace(/'/g, "%27");
      return `<button type="button" class="btn btn-secondary btn-sm" ${unavailable ? "disabled" : ""} onclick="PT_selectQuoteSearchResult('${encoded}')">${esc(label)}</button>`;
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

function _ptFillIndModal(vm, ind, title) {
  $("ind-edit-modal-title").textContent = title;
  $("ind-edit-unit-number").value   = ind.unit_number          || "";
  $("ind-edit-year").value          = ind.year                 || "";
  $("ind-edit-make").value          = vm.make  || ind.make     || "";
  $("ind-edit-model").value         = vm.model || ind.model    || "";
  $("ind-edit-color").value         = ind.color                || "";
  $("ind-edit-vin").value           = ind.vin                  || "";
  $("ind-edit-existing-year").value = ind.existing_year        || "";
  $("ind-edit-existing-make").value = ind.existing_make        || "";
  $("ind-edit-existing-model").value = ind.existing_model      || "";
  $("ind-edit-existing-build-type").value = ind.existing_build_type || "";
  $("ind-edit-existing-unit-number").value = ind.existing_unit_number || "";
  $("ind-edit-existing-vin").value  = ind.existing_vin         || "";
  $("ind-edit-notes").value         = ind.notes                || "";
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
  const vm = _ptVehicleConfig(u.vehicle_model);
  _ptFillIndModal(vm, ind, `Edit: ${_ptUnitLabel(u, ind, indIdx)}`);
  _ptSetIndividualModalReadOnly(false);
  _ptPrepareQuoteEditor(ind, false);
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.style.display = "none";
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
  _PT.indModalUid        = null;
  _PT.indModalIdx        = null;
  _PT.viewProject        = project;
  const indIdx = unit.individuals.indexOf(ind);
  const vm     = _ptVehicleConfig(unit.vehicle_model);
  _ptFillIndModal(vm, ind, `${_ptUnitLabel(unit, ind, indIdx)}`);
  const readOnly = !_ptCanEditProjects();
  _ptSetIndividualModalReadOnly(readOnly);
  _ptPrepareQuoteEditor(ind, readOnly);
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.style.display = _ptCanEditProjects() ? "" : "none";
  $("ind-edit-modal").classList.add("open");
};

window.PT_closeIndModal = function () {
  $("ind-edit-modal").classList.remove("open");
  _PT.indModalFromDetail = false;
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.style.display = "none";
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
  const vm = _ptVehicleConfig(u.vehicle_model);
  ind.unit_number          = $("ind-edit-unit-number").value.trim();
  ind.year                 = $("ind-edit-year").value.trim();
  ind.make                 = vm.make  || "";
  ind.model                = vm.model || "";
  ind.color                = $("ind-edit-color").value.trim();
  ind.vin                  = $("ind-edit-vin").value.trim();
  ind.existing_year        = $("ind-edit-existing-year").value.trim();
  ind.existing_make        = $("ind-edit-existing-make").value.trim();
  ind.existing_model       = $("ind-edit-existing-model").value.trim();
  ind.existing_build_type  = $("ind-edit-existing-build-type").value.trim();
  ind.existing_unit_number = $("ind-edit-existing-unit-number").value.trim();
  ind.existing_vin         = $("ind-edit-existing-vin").value.trim();
  ind.notes                = $("ind-edit-notes").value.trim();
  ind.quote_references     = _ptQuoteEditorRefs.map(ref => ({...ref}));
  PT_closeIndModal();
  _ptRenderReview();
};

async function _ptSaveDetailIndModal(thenBuild) {
  const project = _PT.projects.find(p => p.project_id === _PT.viewProject?.project_id);
  if (!project) { PT_closeIndModal(); return; }
  const unit = project.build_units.find(u => u.unit_id === _PT.indModalUnitId);
  if (!unit) { PT_closeIndModal(); return; }
  const ind = unit.individuals.find(i => i.individual_id === _PT.indModalIndId);
  if (!ind) { PT_closeIndModal(); return; }

  const vm = _ptVehicleConfig(unit.vehicle_model);
  ind.unit_number          = $("ind-edit-unit-number").value.trim();
  ind.year                 = $("ind-edit-year").value.trim();
  ind.make                 = vm.make  || "";
  ind.model                = vm.model || "";
  ind.color                = $("ind-edit-color").value.trim();
  ind.vin                  = $("ind-edit-vin").value.trim();
  ind.existing_year        = $("ind-edit-existing-year").value.trim();
  ind.existing_make        = $("ind-edit-existing-make").value.trim();
  ind.existing_model       = $("ind-edit-existing-model").value.trim();
  ind.existing_build_type  = $("ind-edit-existing-build-type").value.trim();
  ind.existing_unit_number = $("ind-edit-existing-unit-number").value.trim();
  ind.existing_vin         = $("ind-edit-existing-vin").value.trim();
  ind.notes                = $("ind-edit-notes").value.trim();
  ind.quote_references     = _ptQuoteEditorRefs.map(ref => ({...ref}));

  PT_closeIndModal();

  try {
    const res = await api("/api/project/save", { ...project });
    if (res.ok) {
      toast("Unit details saved", "success");
      if (_ptQuoteEditorNeedsReconcile) await window.PT_reconcileQuoteReferences();
      await _ptLoadAll();
      _PT.viewProject = _PT.projects.find(p => p.project_id === res.project_id) || _PT.viewProject;
      _ptRenderOverview(_PT.viewProject);
      _ptRenderEditTab(_PT.viewProject, false);
      _ptRenderBuildsTab(_PT.viewProject);
    } else {
      toast(res.error || "Save failed", "error");
    }
  } catch (e) {
    toast(e.message || "Save failed", "error");
  }

  if (thenBuild) {
    const proj = _PT.projects.find(p => p.project_id === _PT.viewProject?.project_id);
    if (!proj) return;
    const unitIdx = proj.build_units.findIndex(u => u.unit_id === _PT.indModalUnitId);
    if (unitIdx === -1) return;
    const theUnit = proj.build_units[unitIdx];
    const theInd  = theUnit.individuals.find(i => i.individual_id === _PT.indModalIndId);
    if (theInd?.draft_id) {
      await _ptShowBuildEditor(theInd.draft_id, theUnit, proj, "overview", theInd);
    } else {
      PT_startBuildIndividual(proj.project_id, unitIdx, _PT.indModalIndId);
    }
  }
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
    const res = await api("/api/project/save", project);
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
