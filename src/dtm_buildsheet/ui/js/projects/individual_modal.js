// ── Projects module: individual unit edit modal ────────────────────────────────

function _ptFillIndModal(vm, ind, title) {
  $("ind-edit-modal-title").textContent = title;
  $("ind-edit-unit-number").value   = ind.unit_number          || "";
  $("ind-edit-year").value          = ind.year                 || "";
  $("ind-edit-make").value          = vm.make  || ind.make     || "";
  $("ind-edit-model").value         = vm.model || ind.model    || "";
  $("ind-edit-color").value         = ind.color                || "";
  $("ind-edit-vin").value           = ind.vin                  || "";
  $("ind-edit-existing-unit").value = ind.existing_unit_number || "";
  $("ind-edit-existing-vin").value  = ind.existing_vin         || "";
  $("ind-edit-notes").value         = ind.notes                || "";
}

// Opened from wizard Review tab
window.PT_openIndModal = function (uid, indIdx) {
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
  const vm = _PT.vehicleMap[u.vehicle_model] || {};
  _ptFillIndModal(vm, ind, `Edit: ${_ptUnitLabel(u, ind, indIdx)}`);
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
  const vm     = _PT.vehicleMap[unit.vehicle_model] || {};
  _ptFillIndModal(vm, ind, `${_ptUnitLabel(unit, ind, indIdx)}`);
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.style.display = "";
  $("ind-edit-modal").classList.add("open");
};

window.PT_closeIndModal = function () {
  $("ind-edit-modal").classList.remove("open");
  _PT.indModalFromDetail = false;
  const setupSec = $("ind-modal-setup-section");
  if (setupSec) setupSec.style.display = "none";
};

window.PT_saveIndModal = function () {
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
  const vm = _PT.vehicleMap[u.vehicle_model] || {};
  ind.unit_number          = $("ind-edit-unit-number").value.trim();
  ind.year                 = $("ind-edit-year").value.trim();
  ind.make                 = vm.make  || "";
  ind.model                = vm.model || "";
  ind.color                = $("ind-edit-color").value.trim();
  ind.vin                  = $("ind-edit-vin").value.trim();
  ind.existing_unit_number = $("ind-edit-existing-unit").value.trim();
  ind.existing_vin         = $("ind-edit-existing-vin").value.trim();
  ind.notes                = $("ind-edit-notes").value.trim();
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

  const vm = _PT.vehicleMap[unit.vehicle_model] || {};
  ind.unit_number          = $("ind-edit-unit-number").value.trim();
  ind.year                 = $("ind-edit-year").value.trim();
  ind.make                 = vm.make  || "";
  ind.model                = vm.model || "";
  ind.color                = $("ind-edit-color").value.trim();
  ind.vin                  = $("ind-edit-vin").value.trim();
  ind.existing_unit_number = $("ind-edit-existing-unit").value.trim();
  ind.existing_vin         = $("ind-edit-existing-vin").value.trim();
  ind.notes                = $("ind-edit-notes").value.trim();

  PT_closeIndModal();

  try {
    const res = await api("/api/project/save", { ...project });
    if (res.ok) {
      toast("Unit details saved", "success");
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
