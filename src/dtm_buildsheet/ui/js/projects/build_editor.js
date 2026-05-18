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

async function _pbeCheckPresetButton(draftId, unit) {
  const btn = $("pbe-create-preset-btn");
  if (!btn) return;
  btn.style.display = "";  // show optimistically

  const presetId = unit?.preset_id;
  if (!presetId) return;  // no assigned preset → always show

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
      if (partsMatch && overridesMatch) {
        btn.style.display = "none";  // exact match — nothing new to save
      }
    }
  } catch (_) {
    // On any error keep the button visible (safe default)
  }
}

async function _ptShowBuildEditor(draftId, unit, project, returnTab) {
  _PT.pbeReturnProject = project;
  _PT.pbeReturnTab     = returnTab || "builds";
  _PT.pbeUnit          = unit;
  _PT.pbeProject       = project;
  _PT.pbeDraftId       = draftId;

  hide("proj-list-view");
  hide("proj-detail-view");
  hide("proj-editor");
  show("proj-build-editor");

  const vm      = _PT.vehicleMap[unit.vehicle_model] || {};
  const vmLabel = vm.make ? `${vm.make} ${vm.model}` : (unit.vehicle_model || "Vehicle");
  const agency  = project?.customer?.agency || "";
  const parts   = [agency, vmLabel, unit.build_type].filter(Boolean).join(" · ");
  $("pbe-unit-info").textContent = parts;

  show("card-preview");
  pvLoad(draftId);
  loadDraftManifest(draftId);
  _pbeCheckPresetButton(draftId, unit);  // async; updates button visibility after load
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
    await pmOpenFromDraft(parts, placementOverrides, { agencyIds, vehicleTypes, buildTypes });
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
  $("pbe-back-btn").addEventListener("click", () => {
    if (confirm("Leave the Build Editor? Any unsaved position overrides will be lost.")) {
      _ptHideBuildEditor();
    }
  });

  $("pbe-save-return").addEventListener("click", async () => {
    const btn = $("pbe-save-return");
    if (btn) btn.disabled = true;
    try {
      // Flush any pending drag/inspector overrides to the server
      if (typeof pvApplyChanges === "function") {
        await pvApplyChanges();
      }
    } catch (e) {
      console.warn("pbe-save-return: pvApplyChanges failed", e);
    } finally {
      if (btn) btn.disabled = false;
    }
    _ptHideBuildEditor();
  });

  const createPresetBtn = $("pbe-create-preset-btn");
  if (createPresetBtn) {
    createPresetBtn.addEventListener("click", _ptOpenCreatePresetFromBuild);
  }
}
