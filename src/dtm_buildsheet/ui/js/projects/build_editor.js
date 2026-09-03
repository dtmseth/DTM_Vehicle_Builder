// ── Projects module: build editor panel ───────────────────────────────────────
// Manages showing/hiding the embedded build editor (#proj-build-editor).
// Save & Return flushes pending preview overrides before returning to the project.

// Fields compared when deciding whether draft parts match a preset's parts.
const _PBE_COMPARE_FIELDS = [
  "name", "include", "location", "raw_color", "quantity",
  "manufacturer", "part_number", "lens", "notes",
  "explicit_color_profile", "driver_color", "passenger_color", "center_color",
];

const _PBE_NOTE_CATEGORIES = [
  "INSTALLATION NOTES",
  "DELIVERY REQUIREMENTS",
];
let _pbeNotesSaveTimer = null;
let _pbeNotesDraftId = "";
let _pbeLoadPresetSelection = "";

function _pbeNotesMarkup(notes, projectNotes) {
  const shared = (projectNotes || "").trim();
  const fields = _PBE_NOTE_CATEGORIES.map(category => {
    const value = Array.isArray(notes?.[category]) ? notes[category].join("\n") : "";
    return `<div class="form-group" style="margin:0 0 10px">
      <label for="pbe-note-${category}">${esc(category.replace(/\b\w/g, c => c.toUpperCase()).toLowerCase().replace(/\b\w/g, c => c.toUpperCase()))}</label>
      <textarea id="pbe-note-${category}" data-pbe-note-category="${esc(category)}" rows="2" class="proj-textarea-full" placeholder="One note per line">${esc(value)}</textarea>
    </div>`;
  }).join("");
  return `${shared ? `<div class="proj-form-hint" style="margin:0 0 12px"><strong>Project-wide note:</strong> ${esc(shared)}</div>` : ""}${fields}`;
}

function _pbeNotesPayload() {
  const notes = {};
  document.querySelectorAll("[data-pbe-note-category]").forEach(field => {
    const rows = field.value.split("\n").map(value => value.trim()).filter(Boolean);
    if (rows.length) notes[field.dataset.pbeNoteCategory] = rows;
  });
  return notes;
}

function _pbeSetNotesStatus(text, isError = false) {
  const status = $("pbe-final-notes-status");
  if (!status) return;
  status.style.display = text ? "block" : "none";
  status.style.background = isError ? "#fdecea" : "#f0f4ff";
  status.style.color = isError ? "var(--red)" : "var(--navy)";
  status.textContent = text;
}

async function _pbeSaveNotes(flush = false) {
  if (_pbeNotesSaveTimer) {
    clearTimeout(_pbeNotesSaveTimer);
    _pbeNotesSaveTimer = null;
  }
  const draftId = _pbeNotesDraftId;
  if (!draftId) return true;
  _pbeSetNotesStatus("Saving notes…");
  try {
    const result = await api("/api/draft/save", { draft_id: draftId, notes: _pbeNotesPayload() });
    if (!result?.ok) throw new Error(result?.error || "Could not save notes");
    _pbeSetNotesStatus("Notes saved");
    if (!flush) setTimeout(() => _pbeSetNotesStatus(""), 1600);
    return true;
  } catch (error) {
    _pbeSetNotesStatus(error.message || "Could not save notes", true);
    toast("Could not save build notes", "error");
    return false;
  }
}

async function _pbeLoadNotes(draftId) {
  _pbeNotesDraftId = draftId || "";
  const content = $("pbe-final-notes-content");
  if (!content || !draftId) return;
  content.innerHTML = `<p class="proj-empty-msg">Loading notes…</p>`;
  _pbeSetNotesStatus("");
  try {
    const result = await api(`/api/draft/${encodeURIComponent(draftId)}`);
    if (!result?.ok) throw new Error(result?.error || "Could not load notes");
    if (_pbeNotesDraftId !== draftId) return;
    content.innerHTML = _pbeNotesMarkup(result.draft?.notes || {}, result.draft?.project_notes || "");
    if (typeof _pbeRenderReferenceSummary === "function") _pbeRenderReferenceSummary();
    content.querySelectorAll("[data-pbe-note-category]").forEach(field => field.addEventListener("input", () => {
      if (_pbeNotesSaveTimer) clearTimeout(_pbeNotesSaveTimer);
      _pbeSetNotesStatus("Saving notes…");
      _pbeNotesSaveTimer = setTimeout(() => _pbeSaveNotes(), 450);
    }));
  } catch (error) {
    content.innerHTML = `<p class="proj-empty-msg">Could not load notes for this build.</p>`;
  }
}

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
  const footerPreset = $("pbe-create-preset-btn");
  if (footerPreset) footerPreset.style.display = "";
  const footerGroup = $("pbe-apply-group-btn");
  if (footerGroup) footerGroup.style.display = "";
  const topPreset = $("pbe-create-preset-top");
  if (topPreset) topPreset.style.display = "";
  const topGroup = $("pbe-apply-group-top");
  if (topGroup) topGroup.style.display = "";
}

function _pbeSetActionRowVisible(visible) {
  const actionRow = $("pbe-action-row");
  // Load Preset is always available. Only the dirty-build actions disappear
  // when the current draft exactly matches its assigned preset.
  if (actionRow) actionRow.style.display = "flex";
  const footerPreset = $("pbe-create-preset-btn");
  if (footerPreset) footerPreset.style.display = visible ? "" : "none";
  const footerGroup = $("pbe-apply-group-btn");
  if (footerGroup) footerGroup.style.display = visible ? "" : "none";
  const topPreset = $("pbe-create-preset-top");
  if (topPreset) topPreset.style.display = visible ? "" : "none";
  const topGroup = $("pbe-apply-group-top");
  if (topGroup) topGroup.style.display = visible ? "" : "none";
}

function _pbePresetScopeLabel(preset) {
  const agencyIds = preset.agency_ids || [];
  const currentAgencyId = _PT.pbeProject?.customer?.agency_id || "";
  if (!agencyIds.length) return "General preset";
  if (currentAgencyId && agencyIds.includes(currentAgencyId)) {
    return `${_PT.pbeProject?.customer?.agency || "Current agency"} preset`;
  }
  return "Other agency preset";
}

function _pbeRenderLoadPresetOptions() {
  const container = $("pbe-load-preset-options");
  if (!container) return;
  const query = ($("pbe-load-preset-search")?.value || "").trim().toLocaleLowerCase();
  const compatible = _ptCompatiblePresets(_PT.pbeUnit)
    .filter(preset => {
      const haystack = [preset.label, preset.description, _pbePresetScopeLabel(preset)]
        .filter(Boolean).join(" ").toLocaleLowerCase();
      return !query || haystack.includes(query);
    })
    .sort((a, b) => {
      const rank = preset => {
        const ids = preset.agency_ids || [];
        const currentAgencyId = _PT.pbeProject?.customer?.agency_id || "";
        if (currentAgencyId && ids.includes(currentAgencyId)) return 0;
        if (!ids.length) return 1;
        return 2;
      };
      return rank(a) - rank(b) || (a.label || "").localeCompare(b.label || "");
    });
  const total = _ptCompatiblePresets(_PT.pbeUnit).length;
  const count = $("pbe-load-preset-count");
  if (count) count.textContent = query ? `${compatible.length} of ${total}` : `${total} preset${total === 1 ? "" : "s"}`;

  if (!compatible.length) {
    container.innerHTML = `<p class="pbe-load-preset-empty">${query
      ? `No compatible presets match “${esc(query)}”.`
      : "No presets are compatible with this vehicle and build type."}</p>`;
    return;
  }
  container.innerHTML = compatible.map(preset => `
    <label class="pbe-load-preset-option">
      <input type="radio" name="pbe-load-preset-choice" value="${esc(preset.preset_id)}"
        ${preset.preset_id === _pbeLoadPresetSelection ? "checked" : ""}>
      <strong>${esc(preset.label || preset.preset_id)}</strong>
      <span>${esc([_pbePresetScopeLabel(preset), preset.description || ""].filter(Boolean).join(" · "))}</span>
    </label>`).join("");
}

function _pbeCloseLoadPreset() {
  $("pbe-load-preset-modal")?.classList.remove("open");
}

async function _ptOpenLoadPresetFromBuild() {
  const modal = $("pbe-load-preset-modal");
  if (!modal || !_PT.pbeDraftId || !_PT.pbeUnit) {
    toast("No active build available", "error");
    return;
  }
  try {
    const response = await api("/api/presets");
    if (!response?.ok || !Array.isArray(response.presets)) {
      throw new Error(response?.error || "Could not load presets");
    }
    _PT.presets = response.presets;
  } catch (error) {
    toast(error.message || "Could not refresh presets", "error");
    return;
  }

  _pbeLoadPresetSelection = "";
  const search = $("pbe-load-preset-search");
  if (search) search.value = "";
  const confirmBtn = $("pbe-load-preset-confirm");
  if (confirmBtn) confirmBtn.disabled = true;
  _pbeRenderLoadPresetOptions();
  modal.classList.add("open");
  search?.focus();
}

async function _pbeApplySelectedPreset() {
  const presetId = _pbeLoadPresetSelection;
  const draftId = _PT.pbeDraftId;
  const confirmBtn = $("pbe-load-preset-confirm");
  if (!presetId || !draftId || !confirmBtn) return;
  confirmBtn.disabled = true;
  confirmBtn.textContent = "Loading…";
  try {
    if (typeof pvApplyChanges === "function") {
      const saved = await pvApplyChanges();
      if (saved === false) return;
    }
    const result = await api(`/api/draft/${encodeURIComponent(draftId)}/apply-preset`, {
      preset_id: presetId,
    });
    if (!result?.ok) {
      throw new Error(result?.message || result?.error || "Could not load preset");
    }
    _pbeCloseLoadPreset();
    await Promise.all([
      Promise.resolve(loadDraftManifest(draftId)),
      Promise.resolve(pvLoad(draftId)),
    ]);
    // Compare against the preset just loaded for this screen. Loading is a
    // copy operation; it intentionally does not change the unit-group preset
    // assignment or silently alter sibling vehicles.
    await _pbeCheckPresetButton(draftId, { ..._PT.pbeUnit, preset_id: presetId });
    toast(`Loaded preset: ${result.preset_label}`, "success");
  } catch (error) {
    toast(error.message || "Could not load preset", "error");
  } finally {
    confirmBtn.textContent = "Load and Replace Build";
    confirmBtn.disabled = !_pbeLoadPresetSelection;
  }
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
  _PT.pbeReturnTab     = returnTab || "overview";
  _PT.pbeUnit          = unit;
  _PT.pbeProject       = project;
  _PT.pbeDraftId       = draftId;
  _PT.pbeIndividual    = individual || null;

  hide("proj-list-view");
  hide("proj-detail-view");
  hide("proj-editor");
  show("proj-build-editor");
  _pbeSetActionRowVisible(false);

  const vm      = _ptVehicleConfig(unit.vehicle_model);
  const vmLabel = vm.make ? `${vm.make} ${vm.model}` : (unit.vehicle_model || "Vehicle");
  const agency  = project?.customer?.agency || "";
  const unitNum = individual?.unit_number?.trim();
  const parts   = [agency, vmLabel, unit.build_type, unitNum ? `Unit ${unitNum}` : null].filter(Boolean).join(" · ");
  $("pbe-unit-info").textContent = parts;

  show("card-preview");
  pvLoad(draftId);
  loadDraftManifest(draftId);
  _pbeLoadNotes(draftId);
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

  if (!confirm(`Apply this build configuration to all ${siblings.length} other unit(s) in this group?\n\nThis will copy all parts, quantities, colors, placement overrides, and supply status (New / Customer supplied, including condition and source) to every other unit — overwriting any existing build changes and setting up any units that haven't been configured yet.`)) return;

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
  const vehicleTypes = unit?.vehicle_model ? [_ptCanonicalVehicleType(unit.vehicle_model)] : [];
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
  const tab     = _PT.pbeReturnTab === "edit" ? "edit" : "overview";
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
    _ptSetDetailTab(tab);
  } else {
    _ptShowList();
  }
}

// Wire the Return to Project and Create Preset buttons.
// Called once from index.js _ptBind().
function _ptBindBuildEditor() {
  async function _pbeReturnToProject(btnEl) {
    if (btnEl) btnEl.disabled = true;
    let placementSaveSucceeded = true;
    try {
      const notesSaved = await _pbeSaveNotes(true);
      if (!notesSaved) return;
      if (typeof pvApplyChanges === "function") placementSaveSucceeded = await pvApplyChanges() !== false;
    } catch (e) {
      console.warn("pbe return: pvApplyChanges failed", e);
      placementSaveSucceeded = false;
    } finally {
      if (btnEl) btnEl.disabled = false;
    }
    if (!placementSaveSucceeded) return;
    _ptHideBuildEditor();
  }

  $("pbe-back-btn").addEventListener("click", () =>
    _pbeReturnToProject($("pbe-back-btn"))
  );

  $("pbe-save-return").addEventListener("click", () =>
    _pbeReturnToProject($("pbe-save-return"))
  );

  const createPresetBtn = $("pbe-create-preset-btn");
  if (createPresetBtn) {
    createPresetBtn.addEventListener("click", _ptOpenCreatePresetFromBuild);
  }

  const createPresetTop = $("pbe-create-preset-top");
  if (createPresetTop) {
    createPresetTop.addEventListener("click", _ptOpenCreatePresetFromBuild);
  }

  [$("pbe-load-preset-btn"), $("pbe-load-preset-top")].forEach(button => {
    if (button) button.addEventListener("click", _ptOpenLoadPresetFromBuild);
  });

  $("pbe-load-preset-close")?.addEventListener("click", _pbeCloseLoadPreset);
  $("pbe-load-preset-cancel")?.addEventListener("click", _pbeCloseLoadPreset);
  $("pbe-load-preset-search")?.addEventListener("input", _pbeRenderLoadPresetOptions);
  $("pbe-load-preset-options")?.addEventListener("change", event => {
    const input = event.target.closest("input[name='pbe-load-preset-choice']");
    if (!input) return;
    _pbeLoadPresetSelection = input.value;
    const confirmBtn = $("pbe-load-preset-confirm");
    if (confirmBtn) confirmBtn.disabled = false;
  });
  $("pbe-load-preset-confirm")?.addEventListener("click", _pbeApplySelectedPreset);

  const applyGroupBtn = $("pbe-apply-group-btn");
  if (applyGroupBtn) {
    applyGroupBtn.addEventListener("click", _ptApplyToUnitGroup);
  }

  const applyGroupTop = $("pbe-apply-group-top");
  if (applyGroupTop) {
    applyGroupTop.addEventListener("click", _ptApplyToUnitGroup);
  }
}
