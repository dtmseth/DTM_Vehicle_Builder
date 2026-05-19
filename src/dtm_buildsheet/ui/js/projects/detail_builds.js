// ── Projects module: detail Builds tab ───────────────────────────────────────

function _ptRenderBuildsTab(p) {
  const buildsPanel = $("proj-ptab-builds");
  if (!buildsPanel) return;
  const units = p.build_units || [];
  const pid   = esc(p.project_id);

  if (!units.length) {
    buildsPanel.innerHTML = `
      <p class="proj-empty-msg">No units defined yet. Add fleet units on the Edit tab.</p>
      <div id="proj-action-status" class="proj-action-status" style="display:none"></div>`;
    return;
  }

  const groups = units.map((u, uIdx) => {
    const pLabel  = _ptPresetLabel(u);
    const vm      = _PT.vehicleMap[u.vehicle_model] || {};
    const vmLabel = vm.make ? `${vm.make} ${vm.model}` : (u.vehicle_model || "—");
    const inds    = u.individuals || [];
    const uid     = esc(u.unit_id);

    let cards;
    if (inds.length > 0) {
      cards = inds.map((ind, j) => {
        const label     = _ptUnitLabel(u, ind, j);
        const iid       = esc(ind.individual_id);
        const hasDraft  = !!ind.draft_id;
        const hasOutput = !!(ind.output_path || "").trim();
        const confirmed = !!ind.confirmed;

        const setupLbl  = hasDraft ? "Edit Build" : "Setup Build";
        const genLbl    = hasOutput ? "⚡ Regenerate" : "⚡ Generate";
        const genDis    = !hasDraft ? ` disabled title="Configure build first"` : "";
        const expDis    = !hasOutput ? ` disabled title="Generate build sheet first"` : "";

        const draftIdEsc  = hasDraft  ? esc(ind.draft_id) : "";
        const outputEsc   = hasOutput ? esc(ind.output_path) : "";

        return `<div class="proj-build-card" id="build-card-${iid}">
          <div class="proj-build-card-top">
            <div class="proj-build-card-label">${esc(label)}</div>
            <button class="btn btn-secondary btn-sm proj-build-details-btn"
              onclick="PT_openDetailIndModal('${pid}','${uid}','${iid}')">Details</button>
          </div>
          <div class="proj-ind-card-badges">
            ${hasDraft  ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
          </div>
          <div class="proj-build-card-stats" id="build-stats-${iid}">
            ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
          </div>
          <div class="proj-build-actions">
            <button class="btn btn-secondary btn-sm proj-start-btn"
              onclick="PT_setupOrEditBuildInd('${pid}','${uid}','${iid}','${draftIdEsc}',${uIdx})">
              ${esc(setupLbl)}
            </button>
            <button class="btn btn-primary btn-sm"${genDis}
              onclick="PT_buildGenerate('${pid}','${uid}','${iid}','ind')">
              ${genLbl}
            </button>
            <button class="btn btn-secondary btn-sm"${expDis}
              onclick="PT_buildExportPdf('${pid}','${uid}','${iid}','ind','${outputEsc}')">
              📄 Export PDF
            </button>
          </div>
        </div>`;
      }).join("");
    } else {
      const hasDraft  = !!u.draft_id;
      const hasOutput = !!(u.output_path || "").trim();
      const setupLbl  = hasDraft ? "Edit Build" : "Setup Build";
      const genLbl    = hasOutput ? "⚡ Regenerate" : "⚡ Generate";
      const genDis    = !hasDraft ? ` disabled title="Configure build first"` : "";
      const expDis    = !hasOutput ? ` disabled title="Generate build sheet first"` : "";
      const draftIdEsc = hasDraft  ? esc(u.draft_id) : "";
      const outputEsc  = hasOutput ? esc(u.output_path) : "";

      cards = `<div class="proj-build-card" id="build-card-unit-${uid}">
        <div class="proj-build-card-label">${esc(u.build_type || "Unit")} ×${u.quantity}</div>
        <div class="proj-ind-card-badges">
          ${hasDraft ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
        </div>
        <div class="proj-build-card-stats" id="build-stats-unit-${uid}">
          ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
        </div>
        <div class="proj-build-actions">
          <button class="btn btn-secondary btn-sm proj-start-btn"
            onclick="PT_setupOrEditBuildUnit('${pid}','${uid}','${draftIdEsc}',${uIdx})">
            ${esc(setupLbl)}
          </button>
          <button class="btn btn-primary btn-sm"${genDis}
            onclick="PT_buildGenerate('${pid}','${uid}','','unit')">
            ${genLbl}
          </button>
          <button class="btn btn-secondary btn-sm"${expDis}
            onclick="PT_buildExportPdf('${pid}','${uid}','','unit','${outputEsc}')">
            📄 Export PDF
          </button>
        </div>
      </div>`;
    }

    return `<div class="proj-unit-group">
      <div class="proj-unit-group-hdr">
        <span class="proj-unit-group-vehicle">${esc(vmLabel)}</span>
        <span class="proj-unit-group-meta">${esc(u.build_type || "—")} · ${u.quantity}× · ${esc(pLabel)}</span>
      </div>
      <div class="proj-build-btn-row">${cards}</div>
    </div>`;
  }).join("");

  buildsPanel.innerHTML = `
    ${groups}
    <div class="proj-builds-footer">
      <button class="btn btn-primary btn-sm" onclick="PT_generateAll()">⚡ Generate All</button>
      <button class="btn btn-secondary btn-sm" onclick="PT_exportAllPdf()">📄 Export All PDFs</button>
    </div>
    <div id="proj-action-status" class="proj-action-status" style="display:none"></div>`;

  _ptLoadBuildsStats(p);
}

async function _ptLoadBuildsStats(p) {
  if (!_PT.catalog?.parts) {
    try { const r = await api("/api/catalog"); if (r?.parts) _PT.catalog = r; } catch (_) {}
  }
  const catParts   = _PT.catalog?.parts || [];
  const lightNames = new Set(
    catParts
      .filter(q => q.render_kind === "light" || q.render_kind === "bar")
      .map(q => (q.display_name || "").toLowerCase())
  );

  for (const u of (p.build_units || [])) {
    const inds = u.individuals || [];
    if (inds.length > 0) {
      for (const ind of inds) {
        if (!ind.draft_id) continue;
        try {
          const res = await api(`/api/draft/${encodeURIComponent(ind.draft_id)}`);
          if (!res?.ok) continue;
          const parts     = res.draft.parts || [];
          const included  = parts.filter(pt => pt.include !== false);
          const lights    = included.filter(pt => lightNames.has((pt.name || "").toLowerCase()));
          const modified  = res.draft.user_modified;
          const hasPreset = u.preset_id && u.preset_id !== "blank_custom";
          const statsEl   = $(`build-stats-${ind.individual_id}`);
          if (!statsEl) continue;
          const modLine = (modified && hasPreset)
            ? `<div class="proj-ind-card-stat-line proj-ind-card-modified">✏ modified from preset</div>`
            : (!hasPreset && modified)
            ? `<div class="proj-ind-card-stat-line proj-ind-card-custom">custom build</div>`
            : "";
          statsEl.innerHTML = `
            <div class="proj-ind-card-stat-line"><strong>${included.length}</strong>&nbsp;parts</div>
            <div class="proj-ind-card-stat-line"><strong>${lights.length}</strong>&nbsp;light${lights.length !== 1 ? "s" : ""}</div>
            ${modLine}`;
        } catch (_) {}
      }
    } else if (u.draft_id) {
      try {
        const res = await api(`/api/draft/${encodeURIComponent(u.draft_id)}`);
        if (!res?.ok) continue;
        const parts     = res.draft.parts || [];
        const included  = parts.filter(pt => pt.include !== false);
        const lights    = included.filter(pt => lightNames.has((pt.name || "").toLowerCase()));
        const modified  = res.draft.user_modified;
        const hasPreset = u.preset_id && u.preset_id !== "blank_custom";
        const statsEl   = $(`build-stats-unit-${u.unit_id}`);
        if (!statsEl) continue;
        const modLine = (modified && hasPreset)
          ? `<div class="proj-ind-card-stat-line proj-ind-card-modified">✏ modified from preset</div>`
          : (!hasPreset && modified)
          ? `<div class="proj-ind-card-stat-line proj-ind-card-custom">custom build</div>`
          : "";
        statsEl.innerHTML = `
          <div class="proj-ind-card-stat-line"><strong>${included.length}</strong>&nbsp;parts</div>
          <div class="proj-ind-card-stat-line"><strong>${lights.length}</strong>&nbsp;light${lights.length !== 1 ? "s" : ""}</div>
          ${modLine}`;
      } catch (_) {}
    }
  }
}

// ── Builds tab actions ─────────────────────────────────────────────────────────

window.PT_setupOrEditBuildUnit = async function (projectId, unitId, existingDraftId, unitIndex) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;

  if (existingDraftId) {
    await _ptShowBuildEditor(existingDraftId, unit, project, "builds");
  } else {
    const statusEl = $("proj-action-status");
    if (statusEl) _ptSetStatus(statusEl, "Setting up build…", "ok");
    try {
      const res = await api(`/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unitId)}/create-draft`, {});
      if (!res.ok) {
        if (statusEl) _ptSetStatus(statusEl, "❌ " + (res.error || "Setup failed"), "err");
        return;
      }
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId) || project;
      _PT.viewProject = updated;
      await _ptShowBuildEditor(res.draft_id, unit, updated, "builds");
    } catch (e) {
      if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Error"), "err");
    }
  }
};

window.PT_setupOrEditBuildInd = async function (projectId, unitId, individualId, existingDraftId, unitIndex) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;
  const individual = (unit.individuals || []).find(i => i.individual_id === individualId);

  if (existingDraftId) {
    await _ptShowBuildEditor(existingDraftId, unit, project, "builds", individual);
  } else {
    const statusEl = $("proj-action-status");
    if (statusEl) _ptSetStatus(statusEl, "Setting up build…", "ok");
    try {
      const res = await api(
        `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unitId)}/individual/${encodeURIComponent(individualId)}/create-draft`, {}
      );
      if (!res.ok) {
        if (statusEl) _ptSetStatus(statusEl, "❌ " + (res.error || "Setup failed"), "err");
        return;
      }
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId) || project;
      _PT.viewProject = updated;
      const updatedUnit = updated.build_units.find(u => u.unit_id === unitId) || unit;
      const updatedInd  = (updatedUnit.individuals || []).find(i => i.individual_id === individualId) || individual;
      await _ptShowBuildEditor(res.draft_id, updatedUnit, updated, "builds", updatedInd);
    } catch (e) {
      if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Error"), "err");
    }
  }
};

window.PT_buildGenerate = async function (projectId, unitId, individualId, type) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units.find(u => u.unit_id === unitId);
  if (!unit) return;

  let draftId, existingOutputPath = "";
  if (type === "ind") {
    const ind = (unit.individuals || []).find(i => i.individual_id === individualId);
    draftId = ind?.draft_id;
    existingOutputPath = ind?.output_path || "";
  } else {
    draftId = unit.draft_id;
    existingOutputPath = unit.output_path || "";
  }
  if (!draftId) { toast("No build configured for this unit", "error"); return; }

  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Generating build sheet…", "ok");

  const cardEl = type === "ind"
    ? $(`build-card-${individualId}`)
    : $(`build-card-unit-${unitId}`);
  const genBtn = cardEl?.querySelector(".btn-primary");
  if (genBtn) genBtn.disabled = true;

  try {
    const res = await api("/api/draft/generate", {
      draft_id: draftId,
      project_id: projectId,
      existing_output_path: existingOutputPath,
    });
    if (res.ok) {
      const outputPath = res.output_path || "";
      const updatedUnits = project.build_units.map(u => {
        if (u.unit_id !== unitId) return { ...u };
        if (type === "unit") return { ...u, output_path: outputPath };
        return {
          ...u,
          individuals: (u.individuals || []).map(ind =>
            ind.individual_id === individualId ? { ...ind, output_path: outputPath } : ind
          ),
        };
      });
      await api("/api/project/save", { project_id: projectId, build_units: updatedUnits });
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId);
      if (updated) {
        _PT.viewProject = updated;
        _ptRenderBuildsTab(updated);
        _ptRenderOverview(updated);
      }
      toast("Build sheet generated: " + (res.output_name || ""), "success");
      if (statusEl) statusEl.style.display = "none";

      // Rename conflict: old file still exists under a different name
      if (res.name_changed) {
        const nc = res.name_changed;
        const choice = confirm(
          `The unit details changed, so the new build sheet has a different name.\n\n` +
          `Old file: ${nc.old_name}\nNew file: ${nc.new_name}\n\n` +
          `OK = Delete the old file\nCancel = Keep both`
        );
        if (choice) {
          await api("/api/generate/delete-old", { files: [nc.old_path] });
        }
      }
    } else {
      const msg = res.error || "Generation failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
      if (genBtn) genBtn.disabled = false;
    }
  } catch (e) {
    const msg = e.message || "Unexpected error";
    toast(msg, "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    if (genBtn) genBtn.disabled = false;
  }
};

window.PT_buildExportPdf = async function (projectId, unitId, individualId, type, outputPath) {
  if (!outputPath) { toast("Generate the build sheet first", "error"); return; }
  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Exporting PDF…", "ok");
  try {
    const res = await api("/api/export/pdf", { output_path: outputPath });
    if (res.ok) {
      toast("PDF exported: " + (res.pdf_name || ""), "success");
      if (statusEl) statusEl.style.display = "none";
    } else {
      const msg = res.error || "Export failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    }
  } catch (e) {
    toast(e.message || "Export failed", "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Error"), "err");
  }
};

// Generate All: sequentially generate every configured draft, persist output_path per unit
window.PT_generateAll = async function () {
  if (!_PT.viewProject) return;
  const project = _PT.viewProject;
  const units   = project.build_units || [];

  // Collect work items
  const items = [];
  for (const u of units) {
    const inds = u.individuals || [];
    if (inds.length > 0) {
      for (const ind of inds) {
        items.push({ type: "ind", unit: u, ind, label: _ptUnitLabel(u, ind, inds.indexOf(ind)) });
      }
    } else {
      items.push({ type: "unit", unit: u, label: u.build_type || "Unit" });
    }
  }

  const configuredItems = items.filter(item =>
    item.type === "ind" ? !!item.ind.draft_id : !!item.unit.draft_id
  );
  const skippedItems = items.filter(item =>
    item.type === "ind" ? !item.ind.draft_id : !item.unit.draft_id
  );

  if (!configuredItems.length) {
    toast("No configured builds to generate. Set up builds first.", "error");
    return;
  }

  const statusEl = $("proj-action-status");
  const allBtns  = document.querySelectorAll(".proj-builds-footer .btn");
  allBtns.forEach(b => b.disabled = true);

  let generated = 0;
  let errors    = [];

  for (let i = 0; i < configuredItems.length; i++) {
    const item = configuredItems[i];
    if (statusEl) _ptSetStatus(statusEl,
      `Generating ${i + 1}/${configuredItems.length}: ${item.label}…`, "ok");

    const draftId = item.type === "ind" ? item.ind.draft_id : item.unit.draft_id;
    try {
      const res = await api("/api/draft/generate", { draft_id: draftId, project_id: project.project_id });
      if (res.ok) {
        generated++;
        // Persist output_path back to project
        const outputPath   = res.output_path || "";
        const updatedUnits = project.build_units.map(u => {
          if (u.unit_id !== item.unit.unit_id) return { ...u };
          if (item.type === "unit") return { ...u, output_path: outputPath };
          return {
            ...u,
            individuals: (u.individuals || []).map(ind =>
              ind.individual_id === item.ind.individual_id
                ? { ...ind, output_path: outputPath }
                : ind
            ),
          };
        });
        await api("/api/project/save", { project_id: project.project_id, build_units: updatedUnits });
        // Update local project copy for next iteration
        await _ptLoadAll();
        const reloaded = _PT.projects.find(p => p.project_id === project.project_id);
        if (reloaded) _PT.viewProject = reloaded;
      } else {
        errors.push(`${item.label}: ${res.error || "failed"}`);
      }
    } catch (e) {
      errors.push(`${item.label}: ${e.message || "error"}`);
    }
  }

  allBtns.forEach(b => b.disabled = false);

  // Refresh UI
  const finalProject = _PT.projects.find(p => p.project_id === project.project_id) || _PT.viewProject;
  if (finalProject) {
    _PT.viewProject = finalProject;
    _ptRenderBuildsTab(finalProject);
    _ptRenderOverview(finalProject);
  }

  // Build result message
  let msg = `✅ ${generated} build sheet${generated !== 1 ? "s" : ""} generated`;
  if (skippedItems.length) msg += ` · ⏭ ${skippedItems.length} skipped (no build set up)`;
  if (errors.length)       msg += ` · ❌ ${errors.length} error${errors.length !== 1 ? "s" : ""}`;

  if (statusEl) _ptSetStatus(statusEl, msg, errors.length ? "err" : "good");

  const toastKind = errors.length ? "error" : "success";
  toast(`Generated ${generated}${skippedItems.length ? `, skipped ${skippedItems.length}` : ""}`, toastKind);
  if (errors.length) console.warn("Generate All errors:", errors);
};

window.PT_exportAllPdf = async function () {
  if (!_PT.viewProject) return;

  const units = _PT.viewProject.build_units || [];
  const allDrafts = units.every(u => {
    const inds = u.individuals || [];
    if (inds.length > 0) return inds.every(ind => !!ind.draft_id);
    return !!u.draft_id;
  });
  if (!allDrafts) {
    toast("Some units haven't been set up yet. Use Setup Build on each unit before exporting.", "error");
    return;
  }

  const missingNum = units.some(u =>
    (u.individuals || []).some(ind => !ind.unit_number?.trim())
  );
  if (missingNum) {
    toast("Some units are missing a unit number. Add unit numbers via Details / Setup Build before exporting.", "error");
    return;
  }

  const statusEl = $("proj-action-status");
  const allBtns  = document.querySelectorAll(".proj-builds-footer .btn");
  allBtns.forEach(b => b.disabled = true);
  if (statusEl) _ptSetStatus(statusEl, "Generating and exporting PDFs…", "ok");
  try {
    const res = await api(`/api/project/${encodeURIComponent(_PT.viewProject.project_id)}/export-all-pdf`, {});
    if (res.ok) {
      const n = (res.exported || []).length;
      const e = (res.errors  || []).length;
      toast(`${n} PDF${n !== 1 ? "s" : ""} exported`, e ? "error" : "success");
      if (statusEl) _ptSetStatus(statusEl, `✅ ${n} exported${e ? ` · ${e} error${e !== 1 ? "s" : ""}` : ""}`, "good");
    } else {
      const msg = res.error || "Export failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    }
  } catch (err) {
    const msg = err.message || "Unexpected error";
    toast(msg, "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
  }
  allBtns.forEach(b => b.disabled = false);
};

// Legacy start-build callers (delegate to build editor)
window.PT_startBuild = async function (projectId, unitIndex) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;
  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Creating draft…", "ok");
  try {
    const res = await api(
      `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unit.unit_id)}/create-draft`, {}
    );
    if (!res.ok) { if (statusEl) _ptSetStatus(statusEl, "❌ " + (res.error || "Draft failed"), "err"); return; }
    await _ptLoadAll();
    const updated = _PT.projects.find(p => p.project_id === projectId) || project;
    _PT.viewProject = updated;
    await _ptShowBuildEditor(res.draft_id, unit, updated, "builds");
  } catch (e) {
    if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Unexpected error"), "err");
  }
};

window.PT_startBuildIndividual = async function (projectId, unitIndex, individualId) {
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;
  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Creating draft…", "ok");
  try {
    const res = await api(
      `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unit.unit_id)}/individual/${encodeURIComponent(individualId)}/create-draft`, {}
    );
    if (!res.ok) { if (statusEl) _ptSetStatus(statusEl, "❌ " + (res.error || "Draft failed"), "err"); return; }
    await _ptLoadAll();
    const updated = _PT.projects.find(p => p.project_id === projectId) || project;
    _PT.viewProject = updated;
    const updatedUnit = updated.build_units.find(u => u.unit_id === unit.unit_id) || unit;
    const updatedInd  = (updatedUnit.individuals || []).find(i => i.individual_id === individualId);
    await _ptShowBuildEditor(res.draft_id, updatedUnit, updated, "builds", updatedInd);
  } catch (e) {
    if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Unexpected error"), "err");
  }
};
