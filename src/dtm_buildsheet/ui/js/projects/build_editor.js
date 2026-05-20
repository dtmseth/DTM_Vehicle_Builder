// ── Projects module: build editor panel ───────────────────────────────────────
// Manages showing/hiding the embedded build editor (#proj-build-editor).
// Save & Return flushes pending preview overrides before returning to the project.

// Fields compared when deciding whether draft parts match a preset's parts.
const _PBE_COMPARE_FIELDS = [
  "name", "include", "location", "raw_color", "quantity",
  "manufacturer", "part_number", "lens", "notes",
  "explicit_color_profile", "driver_color", "passenger_color", "center_color",
];

function _pbePartsMatchPreset(draftParts, presetParts) {
  const norm = parts => [...parts]
    .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
    .map(p => _PBE_COMPARE_FIELDS.map(f => String(p[f] ?? "")).join("|"));
  const da = norm(draftParts);
  const pa = norm(presetParts);
  if (da.length !== pa.length) return false;
  return da.every((v, i) => v === pa[i]);
}

function _pbeMarkDirty() {
  const actionRow = $("pbe-action-row");
  if (actionRow) actionRow.style.display = "flex";
  const topPreset = $("pbe-create-preset-top");
  if (topPreset) topPreset.style.display = "";
  const topGroup = $("pbe-apply-group-top");
  if (topGroup) topGroup.style.display = "";
}

function _pbeSetActionRowVisible(visible) {
  const actionRow = $("pbe-action-row");
  if (actionRow) actionRow.style.display = visible ? "flex" : "none";
  const topPreset = $("pbe-create-preset-top");
  if (topPreset) topPreset.style.display = visible ? "" : "none";
  const topGroup = $("pbe-apply-group-top");
  if (topGroup) topGroup.style.display = visible ? "" : "none";
}

async function _pbeCheckPresetButton(draftId, unit) {
  // No preset assigned → always show (build has never been saved as a preset)
  const presetId = unit?.preset_id;
  if (!presetId) { _pbeMarkDirty(); return; }

  try {
    const [presetRes, draftRes] = await Promise.all([
      api(`/api/presets/${encodeURIComponent(presetId)}`),
      api(`/api/draft/${encodeURIComponent(draftId)}`),
    ]);
    if (presetRes?.ok && draftRes?.ok) {
      const draftOverrides = draftRes.draft?.placement_overrides || {};
      const presetOverrides = presetRes.placement_overrides || {};
      const partsMatch = _pbePartsMatchPreset(
        draftRes.draft?.parts   || [],
        presetRes.parts         || [],
      );
      const overridesMatch =
        JSON.stringify(draftOverrides) === JSON.stringify(presetOverrides);
      // Exact match → nothing new to save; hide action buttons
      _pbeSetActionRowVisible(!(partsMatch && overridesMatch));
    }
  } catch (_) {
    // On any error keep buttons visible (safe default)
    _pbeMarkDirty();
  }
}

async function _ptShowBuildEditor(draftId, unit, project, returnTab, individual) {
  _PT.pbeReturnProject = project;
  _PT.pbeReturnTab     = returnTab || "builds";
  _PT.pbeUnit          = unit;
  _PT.pbeProject       = project;
  _PT.pbeDraftId       = draftId;
  _PT.pbeIndividual    = individual || null;

  hide("proj-list-view");
  hide("proj-detail-view");
  hide("proj-editor");
  show("proj-build-editor");

  const vm      = _PT.vehicleMap[unit.vehicle_model] || {};
  const vmLabel = vm.make ? `${vm.make} ${vm.model}` : (unit.vehicle_model || "Vehicle");
  const agency  = project?.customer?.agency || "";
  const unitNum = individual?.unit_number?.trim();
  const parts   = [agency, vmLabel, unit.build_type, unitNum ? `Unit ${unitNum}` : null].filter(Boolean).join(" · ");
  $("pbe-unit-info").textContent = parts;

  show("card-preview");
  pvLoad(draftId);
  loadDraftManifest(draftId);
  _pbeCheckPresetButton(draftId, unit);  // async; updates button visibility after load
}

async function _ptApplyToUnitGroup() {
  const unit    = _PT.pbeUnit;
  const currentDraftId = _PT.pbeDraftId;
  const currentInd     = _PT.pbeIndividual;

  if (!unit || !currentDraftId) {
    toast("No active build to apply", "error");
    return;
  }

  const siblings = (unit.individuals || []).filter(
    ind => ind.individual_id !== currentInd?.individual_id
  );

  if (!siblings.length) {
    toast("This is the only unit in the group — nothing to apply to", "info");
    return;
  }

  if (!confirm(`Apply this build configuration to all ${siblings.length} other unit(s) in this group?\n\nThis will copy all parts, quantities, colors, placement overrides, and part status (New / Used / Reused) to every other unit — overwriting any existing build changes and setting up any units that haven't been configured yet.`)) return;

  const draftRes = await api(`/api/draft/${encodeURIComponent(currentDraftId)}`);
  if (!draftRes?.ok) { toast("Could not load current draft", "error"); return; }

  const parts     = draftRes.draft?.parts               || [];
  const overrides = draftRes.draft?.placement_overrides  || {};
  const projectId = _PT.pbeProject?.project_id;
  const unitId    = unit.unit_id;

  let successCount = 0;
  let failCount    = 0;

  for (const ind of siblings) {
    try {
      let draftId = ind.draft_id;

      // Create a draft for this individual if one doesn't exist yet
      if (!draftId) {
        const createRes = await api(
          `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unitId)}/individual/${encodeURIComponent(ind.individual_id)}/create-draft`,
          {}
        );
        if (!createRes?.ok) { failCount++; continue; }
        draftId = createRes.draft_id;
      }

      const res = await api("/api/draft/save", {
        draft_id:            draftId,
        parts,
        placement_overrides: overrides,
      });
      if (res.ok) successCount++;
      else        failCount++;
    } catch (_) {
      failCount++;
    }
  }

  if (failCount > 0) {
    toast(`Applied to ${successCount} unit(s); ${failCount} failed`, "error");
  } else {
    toast(`Applied to ${successCount} unit(s)`, "success");
  }
}

async function _ptOpenCreatePresetFromBuild() {
  const unit    = _PT.pbeUnit;
  const project = _PT.pbeProject;

  if (!_meDraft) {
    toast("Build manifest not loaded yet — please wait a moment", "error");
    return;
  }

  const parts            = (_meDraft.parts || []).map(p => ({ ...p }));
  const placementOverrides = _meDraft.placement_overrides || {};

  const agencyIds    = project?.customer?.agency_id ? [project.customer.agency_id] : [];
  const vehicleTypes = unit?.vehicle_model ? [unit.vehicle_model] : [];
  const buildTypes   = unit?.build_type    ? [unit.build_type]    : [];

  if (typeof pmOpenFromDraft === "function") {
    await pmOpenFromDraft(parts, placementOverrides, { agencyIds, vehicleTypes, buildTypes }, project);
  } else {
    toast("Preset manager not available", "error");
  }
}

async function _ptHideBuildEditor() {
  hide("proj-build-editor");
  meHide();
  pvHideInspector();

  const project = _PT.pbeReturnProject;
  const tab     = _PT.pbeReturnTab || "builds";
  _PT.pbeReturnProject = null;

  if (project) {
    await _ptLoadAll();
    const updated = _PT.projects.find(p => p.project_id === project.project_id) || project;
    _PT.viewProject = updated;
    hide("proj-list-view");
    show("proj-detail-view");
    $("proj-detail-agency").textContent = _ptProjName(updated);
    const n = (updated.build_units || []).reduce((s, u) => s + (u.quantity || 1), 0);
    $("proj-detail-meta").textContent = n + " unit" + (n !== 1 ? "s" : "");
    _ptRenderOverview(updated);
    _ptRenderEditTab(updated, false);
    _ptRenderBuildsTab(updated);
    _ptSetDetailTab(tab);
  } else {
    _ptShowList();
  }
}

// Wire the Save & Return and Create Preset buttons.
// Called once from index.js _ptBind().
function _ptBindBuildEditor() {
  $("pbe-back-btn").addEventListener("click", async () => {
    const hasPending = typeof pvHasPendingChanges === "function" && pvHasPendingChanges();
    if (hasPending) {
      const choice = confirm(
        "You have unsaved position overrides.\n\nOK = Save changes and return\nCancel = Discard changes and return"
      );
      if (choice) {
        try {
          if (typeof pvApplyChanges === "function") await pvApplyChanges();
        } catch (e) {
          console.warn("pbe-back-btn: pvApplyChanges failed", e);
        }
      }
    }
    _ptHideBuildEditor();
  });

  async function _pbeSaveAndReturn(btnEl) {
    if (btnEl) btnEl.disabled = true;
    try {
      if (typeof pvApplyChanges === "function") await pvApplyChanges();
    } catch (e) {
      console.warn("pbe save-return: pvApplyChanges failed", e);
    } finally {
      if (btnEl) btnEl.disabled = false;
    }
    _ptHideBuildEditor();
  }

  $("pbe-save-return").addEventListener("click", () =>
    _pbeSaveAndReturn($("pbe-save-return"))
  );

  const previewSaveReturn = $("pbe-save-return-preview");
  if (previewSaveReturn) {
    previewSaveReturn.addEventListener("click", () =>
      _pbeSaveAndReturn(previewSaveReturn)
    );
  }

  const createPresetBtn = $("pbe-create-preset-btn");
  if (createPresetBtn) {
    createPresetBtn.addEventListener("click", _ptOpenCreatePresetFromBuild);
  }

  const createPresetTop = $("pbe-create-preset-top");
  if (createPresetTop) {
    createPresetTop.addEventListener("click", _ptOpenCreatePresetFromBuild);
  }

  const applyGroupBtn = $("pbe-apply-group-btn");
  if (applyGroupBtn) {
    applyGroupBtn.addEventListener("click", _ptApplyToUnitGroup);
  }

  const applyGroupTop = $("pbe-apply-group-top");
  if (applyGroupTop) {
    applyGroupTop.addEventListener("click", _ptApplyToUnitGroup);
  }
}
