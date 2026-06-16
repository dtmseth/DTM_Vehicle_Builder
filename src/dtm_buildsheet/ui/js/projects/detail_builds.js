// ── Projects module: detail Builds tab ───────────────────────────────────────

function _ptFirstName(s) {
  s = (s || "").trim();
  if (!s) return "";
  // Handle "Last, First" — common in some M365 tenants.
  if (s.includes(",")) return s.split(",")[1]?.trim().split(/\s+/)[0] || s;
  return s.split(/\s+/)[0];
}

function _ptShortAgo(iso) {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const sec = Math.max(0, (Date.now() - t) / 1000);
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return min + "m ago";
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr + "h ago";
  const day = Math.floor(hr / 24);
  if (day < 30) return day + "d ago";
  const mo = Math.floor(day / 30);
  if (mo < 12) return mo + "mo ago";
  return Math.floor(mo / 12) + "y ago";
}

function _ptRenderTimelineRow(holder) {
  // holder has last_rendered_at/by, last_exported_at/by — render a small
  // dim line so teammates can see who built each artifact at a glance.
  const pptxBy   = _ptFirstName(holder.last_rendered_by);
  const pptxWhen = _ptShortAgo(holder.last_rendered_at);
  const pdfBy    = _ptFirstName(holder.last_exported_by);
  const pdfWhen  = _ptShortAgo(holder.last_exported_at);
  const lines = [];
  if (pptxWhen) {
    const who = pptxBy ? `${esc(pptxBy)} · ` : "";
    lines.push(`<span class="proj-build-card-author">📊 ${who}${pptxWhen}</span>`);
  }
  if (pdfWhen) {
    const who = pdfBy ? `${esc(pdfBy)} · ` : "";
    lines.push(`<span class="proj-build-card-author">📄 ${who}${pdfWhen}</span>`);
  }
  if (!lines.length) return "";
  return `<div class="proj-build-card-timeline">${lines.join(" ")}</div>`;
}

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

        const hasPdf    = !!(ind.pdf_path || "").trim();
        const setupLbl  = hasDraft ? "Edit Build" : "Setup Build";
        const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";

        const draftIdEsc  = hasDraft  ? esc(ind.draft_id) : "";
        return `<div class="proj-build-card" id="build-card-${iid}">
          <div class="proj-build-card-top">
            <div class="proj-build-card-label">${esc(label)}</div>
            <button class="btn btn-secondary btn-sm proj-build-details-btn"
              onclick="PT_openDetailIndModal('${pid}','${uid}','${iid}')">Details</button>
          </div>
          <div class="proj-ind-card-badges">
            ${hasDraft  ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
            ${(ind.qb_estimate_id || "").trim() ? `<span class="proj-confirmed-badge">📋 estimate</span>` : ""}
          </div>
          ${_ptRenderTimelineRow(ind)}
          <div class="proj-build-card-stats" id="build-stats-${iid}">
            ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
          </div>
          <div class="proj-build-actions">
            <button class="btn btn-secondary btn-sm proj-start-btn"
              onclick="PT_setupOrEditBuildInd('${pid}','${uid}','${iid}','${draftIdEsc}',${uIdx})">
              ${esc(setupLbl)}
            </button>
            <button class="btn btn-primary btn-sm"${buildDis}
              onclick="PT_buildOpenPptx('${pid}','${uid}','${iid}','ind')">
              📊 Preview / Edit in PowerPoint
            </button>
            <button class="btn btn-secondary btn-sm"${buildDis}
              onclick="PT_buildExportPdf('${pid}','${uid}','${iid}','ind')">
              📄 Export PDF
            </button>
            ${hasPdf ? `<button class="btn btn-secondary btn-sm"
              onclick="PT_buildOpenPdf('${pid}','${uid}','${iid}','ind')">📑 View PDF</button>` : ""}
            <button class="btn btn-secondary btn-sm"${buildDis}
              onclick="PT_buildCreateEstimate('${pid}','${uid}','${iid}')">
              📋 ${(ind.qb_estimate_id || "").trim() ? "Re-estimate" : "QB Estimate"}
            </button>
            <button class="btn btn-secondary btn-sm"
              onclick="PT_buildShowFolder('${pid}','${uid}','${iid}','ind')">📂 Show in folder</button>
          </div>
        </div>`;
      }).join("");
    } else {
      const hasDraft  = !!u.draft_id;
      const hasPdf    = !!(u.pdf_path || "").trim();
      const setupLbl  = hasDraft ? "Edit Build" : "Setup Build";
      const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";
      const draftIdEsc = hasDraft  ? esc(u.draft_id) : "";

      cards = `<div class="proj-build-card" id="build-card-unit-${uid}">
        <div class="proj-build-card-label">${esc(u.build_type || "Unit")} ×${u.quantity}</div>
        <div class="proj-ind-card-badges">
          ${hasDraft ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
        </div>
        ${_ptRenderTimelineRow(u)}
        <div class="proj-build-card-stats" id="build-stats-unit-${uid}">
          ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
        </div>
        <div class="proj-build-actions">
          <button class="btn btn-secondary btn-sm proj-start-btn"
            onclick="PT_setupOrEditBuildUnit('${pid}','${uid}','${draftIdEsc}',${uIdx})">
            ${esc(setupLbl)}
          </button>
          <button class="btn btn-primary btn-sm"${buildDis}
            onclick="PT_buildOpenPptx('${pid}','${uid}','','unit')">
            📊 Preview / Edit in PowerPoint
          </button>
          <button class="btn btn-secondary btn-sm"${buildDis}
            onclick="PT_buildExportPdf('${pid}','${uid}','','unit')">
            📄 Export PDF
          </button>
          ${hasPdf ? `<button class="btn btn-secondary btn-sm"
            onclick="PT_buildOpenPdf('${pid}','${uid}','','unit')">📑 View PDF</button>` : ""}
          <button class="btn btn-secondary btn-sm"
            onclick="PT_buildShowFolder('${pid}','${uid}','','unit')">📂 Show in folder</button>
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
      <button class="btn btn-secondary btn-sm" onclick="PT_createEstimatesBatch()">📋 Create QB Estimates</button>
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

// ── Smart build buttons ────────────────────────────────────────────────
// Preview/Edit, Export PDF, View PDF, Show in folder all go through here.
// The "Generate" button is gone — both Preview and Export auto-regenerate
// when the source has changed since the last render. Manual PowerPoint
// edits are detected and the user is asked whether to keep them.

function _ptResolveBuildContext(projectId, unitId, individualId, type) {
  const project = _PT.projects.find(p => p.project_id === projectId) || _PT.viewProject;
  if (!project) return null;
  const unit = (project.build_units || []).find(u => u.unit_id === unitId);
  if (!unit) return null;
  let draftId = "", outputPath = "", pdfPath = "", lastRenderedAt = "";
  if (type === "ind") {
    const ind = (unit.individuals || []).find(i => i.individual_id === individualId);
    if (!ind) return null;
    draftId = ind.draft_id || "";
    outputPath = ind.output_path || "";
    pdfPath = ind.pdf_path || "";
    lastRenderedAt = ind.last_rendered_at || "";
  } else {
    draftId = unit.draft_id || "";
    outputPath = unit.output_path || "";
    pdfPath = unit.pdf_path || "";
    lastRenderedAt = unit.last_rendered_at || "";
  }
  return { project, unit, draftId, outputPath, pdfPath, lastRenderedAt };
}

// Returns "open" (use existing), "regen" (rebuild), or null (user cancelled).
async function _ptDecidePlan(ctx, statusEl) {
  // No file yet → must regen
  if (!ctx.outputPath) return "regen";
  let status;
  try {
    status = await api("/api/build/render-status", {
      project_id: ctx.project.project_id,
      unit_id: ctx.unit.unit_id,
      individual_id: ctx.individualId || "",
      output_path: ctx.outputPath,
      last_rendered_at: ctx.lastRenderedAt,
    });
  } catch (e) {
    // Network/error — fall back to regen to be safe
    return "regen";
  }
  ctx._status = status;
  if (!status?.pptx_exists) return "regen";
  if (!status.is_stale && !status.manually_edited) return "open";
  if (status.is_stale && !status.manually_edited) return "regen";
  // Stale AND manually edited → ask user
  const choice = confirm(
    "Build settings changed since you last rendered this PowerPoint, but " +
    "you've also edited the file directly in PowerPoint.\n\n" +
    "OK = Re-render from the build settings (discards your PowerPoint edits)\n" +
    "Cancel = Open the edited PowerPoint as-is (build setting changes are ignored)"
  );
  return choice ? "regen" : "open";
}

async function _ptGenerateAndPersist(ctx, statusEl) {
  if (!ctx.draftId) {
    toast("No build configured for this unit", "error");
    return null;
  }
  if (statusEl) _ptSetStatus(statusEl, "Preparing build sheet…", "ok");
  const res = await api("/api/draft/generate", {
    draft_id: ctx.draftId,
    project_id: ctx.project.project_id,
    existing_output_path: ctx.outputPath,
  });
  if (!res?.ok) {
    const msg = res?.error || "Generation failed";
    toast(msg, "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    return null;
  }
  if (res.name_changed) {
    const nc = res.name_changed;
    const drop = confirm(
      `Unit details changed, so the new build sheet has a different name.\n\n` +
      `Old: ${nc.old_name}\nNew: ${nc.new_name}\n\n` +
      `OK = Delete the old file · Cancel = Keep both`
    );
    if (drop) {
      try { await api("/api/generate/delete-old", { paths: [nc.old_path] }); } catch (_) {}
    }
  }
  // Backend stamped output_path + last_rendered_at on the project record
  // itself, so just reload to refresh the UI state.
  await _ptLoadAll();
  const updated = _PT.projects.find(p => p.project_id === ctx.project.project_id);
  if (updated) {
    _PT.viewProject = updated;
    _ptRenderBuildsTab(updated);
    _ptRenderOverview(updated);
  }
  return res.output_path || ctx.outputPath;
}

window.PT_buildOpenPptx = async function (projectId, unitId, individualId, type) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return;
  ctx.individualId = individualId || "";
  const statusEl = $("proj-action-status");
  const plan = await _ptDecidePlan(ctx, statusEl);
  if (!plan) return;
  let target = ctx.outputPath;
  if (plan === "regen") {
    const result = await _ptGenerateAndPersist(ctx, statusEl);
    if (!result) return;
    target = result;
  }
  if (!target) { toast("No build sheet available", "error"); return; }
  if (statusEl) _ptSetStatus(statusEl, "Opening in PowerPoint…", "ok");
  try {
    const res = await api("/open", { path: target });
    if (res?.ok) {
      if (statusEl) statusEl.style.display = "none";
    } else {
      toast(res?.error || "Could not open file", "error");
    }
  } catch (e) {
    toast(e.message || "Open failed", "error");
  }
};

window.PT_buildExportPdf = async function (projectId, unitId, individualId, type) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return;
  ctx.individualId = individualId || "";
  const statusEl = $("proj-action-status");
  const plan = await _ptDecidePlan(ctx, statusEl);
  if (!plan) return;
  let pptxPath = ctx.outputPath;
  if (plan === "regen") {
    const result = await _ptGenerateAndPersist(ctx, statusEl);
    if (!result) return;
    pptxPath = result;
  }
  if (!pptxPath) { toast("No build sheet available", "error"); return; }
  const customer = ctx.project?.customer || {};
  if (statusEl) _ptSetStatus(statusEl, "Exporting PDF…", "ok");
  try {
    const res = await api("/api/export/pdf", {
      output_path: pptxPath,
      agency: customer.agency || "",
      year: customer.build_year || "",
      project_id: ctx.project.project_id,
      unit_id: unitId,
      individual_id: individualId || "",
    });
    if (!res?.ok) {
      const msg = res?.error || "Export failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
      return;
    }
    toast("PDF exported", "success");
    // Backend stamped pdf_path + last_exported_at/by on the project
    // record itself, so just reload to refresh the UI.
    await _ptLoadAll();
    const updated = _PT.projects.find(p => p.project_id === ctx.project.project_id);
    if (updated) {
      _PT.viewProject = updated;
      _ptRenderBuildsTab(updated);
    }
    if (statusEl) _ptSetStatus(statusEl, "✅ PDF exported", "good");
    // Open the PDF after export so the user sees it immediately
    try { await api("/open", { path: res.pdf_path }); } catch (_) {}
  } catch (e) {
    toast(e.message || "Export failed", "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Error"), "err");
  }
};

window.PT_buildOpenPdf = async function (projectId, unitId, individualId, type) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return;
  if (!ctx.pdfPath) { toast("Export the PDF first", "error"); return; }
  try {
    const res = await api("/open", { path: ctx.pdfPath });
    if (!res?.ok) toast(res?.error || "Could not open PDF", "error");
  } catch (e) {
    toast(e.message || "Open failed", "error");
  }
};

window.PT_buildShowFolder = async function (projectId, unitId, individualId, type) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return;
  const customer = ctx.project?.customer || {};
  try {
    const res = await api("/api/build/show-folder", {
      agency: customer.agency || "",
      year: customer.build_year || "",
    });
    if (!res?.ok) toast(res?.error || "Could not open folder", "error");
  } catch (e) {
    toast(e.message || "Open failed", "error");
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

// ── QuickBooks estimate (per-vehicle) ──────────────────────────────────────
// Validate the build's parts against QuickBooks, then draft a NON-POSTING
// estimate. The backend blocks creation unless every part is linked to an
// active, priced QuickBooks item, so the "blocked" path lists exactly what
// needs attention. Estimates never post to the books.

const _QB_EST_REASON = {
  no_catalog_match: "No matching catalog product",
  not_linked: "Not linked to a QuickBooks item",
  qb_inactive: "Inactive in QuickBooks",
  no_price: "No price in QuickBooks",
};

function _ptEstError(code) {
  const m = {
    not_connected: "Not connected to QuickBooks",
    no_realm_id: "No company linked — reconnect to QuickBooks",
    unknown_project: "Project not found",
    unknown_unit: "Unit not found",
    no_build: "Set up the build first",
    no_billable_parts: "No billable parts in this build",
    no_agency: "Assign an agency to this project first",
    agency_not_in_qb: "The agency isn't in QuickBooks yet",
    validation_failed: "Some parts aren't linked to QuickBooks",
  };
  return m[code] || ("Estimate failed: " + (code || "unknown error"));
}

function _ptMoney2(n) {
  const v = Number(n);
  return isNaN(v) ? "$0.00" : "$" + v.toFixed(2);
}

async function _ptQbConnected() {
  try { const s = await api("/api/quickbooks/status"); return !!s?.connected; }
  catch (_) { return false; }
}

function _ptEstModalEls() {
  return {
    modal:  $("qb-est-modal"),
    title:  $("qb-est-title"),
    body:   $("qb-est-body"),
    create: $("qb-est-create"),
    cancel: $("qb-est-cancel"),
  };
}

function _ptOpenEstModal(title, bodyHtml, createLabel) {
  if (!_PT._qbEstWired) {
    _PT._qbEstWired = true;
    const close = () => $("qb-est-modal")?.classList.remove("open");
    $("qb-est-close")?.addEventListener("click", close);
    $("qb-est-cancel")?.addEventListener("click", close);
    $("qb-est-modal")?.addEventListener("click", (ev) => {
      if (ev.target.id === "qb-est-modal") close();
    });
  }
  const e = _ptEstModalEls();
  if (e.title) e.title.textContent = title;
  if (e.body)  e.body.innerHTML = bodyHtml;
  if (e.create) {
    e.create.style.display = createLabel ? "" : "none";
    e.create.disabled = false;
    e.create.onclick = null;
    if (createLabel) e.create.textContent = createLabel;
  }
  e.modal?.classList.add("open");
}

function _ptLabelForInd(project, individualId) {
  for (const u of (project.build_units || [])) {
    const inds = u.individuals || [];
    const idx = inds.findIndex(i => i.individual_id === individualId);
    if (idx >= 0) return _ptUnitLabel(u, inds[idx], idx);
  }
  return individualId;
}

window.PT_buildCreateEstimate = async function (projectId, unitId, individualId) {
  if (!individualId) { toast("Estimates are created per individual unit", "error"); return; }
  if (!(await _ptQbConnected())) {
    toast("Connect QuickBooks first (Settings → QuickBooks)", "error");
    return;
  }
  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Checking parts against QuickBooks…", "ok");
  let v;
  try {
    v = await api("/api/quickbooks/estimates/validate",
      { project_id: projectId, individual_id: individualId });
  } catch (e) { toast("Validation failed", "error"); return; }
  if (statusEl) statusEl.style.display = "none";
  if (!v?.ok) { toast(_ptEstError(v?.error), "error"); return; }

  if (!v.can_create) {
    const probs = v.problems || [];
    if (!probs.length) { toast("No billable parts in this build", "error"); return; }
    const rows = probs.map(p =>
      `<div style="display:flex;justify-content:space-between;gap:10px;padding:7px 10px;border-bottom:1px solid var(--border);font-size:12px">
        <span style="font-weight:600;color:var(--navy);min-width:0;overflow:hidden;text-overflow:ellipsis">${esc(p.name || "(unnamed)")}${p.part_number ? ` <span style="color:var(--muted);font-weight:400">${esc(p.part_number)}</span>` : ""}</span>
        <span style="color:var(--red);white-space:nowrap">${esc(_QB_EST_REASON[p.reason] || p.reason)}</span>
      </div>`).join("");
    _ptOpenEstModal("Estimate blocked",
      `<p style="font-size:13px;margin:0 0 12px">This build can't be turned into an estimate yet — ${probs.length} part${probs.length === 1 ? "" : "s"} need attention. Link them to QuickBooks items in <strong>Settings → QuickBooks</strong>, re-pull, then try again.</p>
       <div style="max-height:320px;overflow:auto;border:1px solid var(--border);border-radius:6px">${rows}</div>`);
    return;
  }

  _ptOpenEstModal("Create QuickBooks estimate",
    `<p style="font-size:13px;margin:0 0 14px">Drafts a <strong>non-posting estimate</strong> in QuickBooks. It won't touch your books — turning it into an invoice is a separate step you take in QuickBooks.</p>
     <div style="display:flex;gap:24px;font-size:13px;margin-bottom:14px">
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Line items</div><div style="font-weight:700;color:var(--navy);font-size:18px">${v.line_count}</div></div>
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Estimated total</div><div style="font-weight:700;color:var(--navy);font-size:18px">${_ptMoney2(v.total)}</div></div>
     </div>
     <label style="font-size:12px;font-weight:600;color:var(--navy)">Memo (optional)</label>
     <input type="text" id="qb-est-memo" placeholder="Appears on the estimate" autocomplete="off" style="width:100%;box-sizing:border-box;margin-top:5px" />`,
    "Create estimate");
  const e = _ptEstModalEls();
  if (e.create) e.create.onclick = () => _ptDoCreateEstimate(projectId, individualId);
};

async function _ptDoCreateEstimate(projectId, individualId) {
  const e = _ptEstModalEls();
  const memo = $("qb-est-memo")?.value || "";
  if (e.create) { e.create.disabled = true; e.create.textContent = "Creating…"; }
  try {
    const res = await api("/api/quickbooks/estimates/create",
      { project_id: projectId, individual_id: individualId, memo });
    if (res?.ok) {
      e.modal?.classList.remove("open");
      toast(`Estimate created${res.doc_number ? " #" + res.doc_number : ""} · ${_ptMoney2(res.total)}`, "success");
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId);
      if (updated) { _PT.viewProject = updated; _ptRenderBuildsTab(updated); }
    } else {
      toast(_ptEstError(res?.error), "error");
      if (e.create) { e.create.disabled = false; e.create.textContent = "Create estimate"; }
    }
  } catch (err) {
    toast("Estimate creation failed", "error");
    if (e.create) { e.create.disabled = false; e.create.textContent = "Create estimate"; }
  }
}

window.PT_createEstimatesBatch = async function () {
  if (!_PT.viewProject) return;
  const project = _PT.viewProject;
  if (!(await _ptQbConnected())) {
    toast("Connect QuickBooks first (Settings → QuickBooks)", "error");
    return;
  }
  const inds = [];
  for (const u of (project.build_units || []))
    for (const ind of (u.individuals || []))
      if (ind.draft_id) inds.push(ind);
  if (!inds.length) { toast("No configured individual units to estimate", "error"); return; }
  if (!confirm(
    `Create QuickBooks estimates for ${inds.length} unit${inds.length === 1 ? "" : "s"}?\n\n` +
    `Each becomes a non-posting draft estimate. Units with unlinked parts are skipped and reported.`
  )) return;

  const statusEl = $("proj-action-status");
  const footerBtns = document.querySelectorAll(".proj-builds-footer .btn");
  footerBtns.forEach(b => b.disabled = true);
  if (statusEl) _ptSetStatus(statusEl, "Creating estimates…", "ok");
  let res;
  try {
    res = await api("/api/quickbooks/estimates/create-batch", { project_id: project.project_id });
  } catch (e) {
    toast("Batch estimate failed", "error");
    footerBtns.forEach(b => b.disabled = false);
    if (statusEl) statusEl.style.display = "none";
    return;
  }
  footerBtns.forEach(b => b.disabled = false);
  if (!res?.ok) {
    toast(_ptEstError(res?.error), "error");
    if (statusEl) statusEl.style.display = "none";
    return;
  }

  await _ptLoadAll();
  const updated = _PT.projects.find(p => p.project_id === project.project_id);
  if (updated) { _PT.viewProject = updated; _ptRenderBuildsTab(updated); }
  if (statusEl) _ptSetStatus(statusEl,
    `✅ ${res.created} created · ${res.blocked} blocked`, res.blocked ? "err" : "good");

  const blocked = (res.results || []).filter(r => !r.ok);
  if (blocked.length) {
    const rows = blocked.map(r => {
      const probCount = (r.problems || []).length;
      const lbl = _ptLabelForInd(updated || project, r.individual_id);
      return `<div style="padding:7px 10px;border-bottom:1px solid var(--border);font-size:12px">
        <span style="font-weight:600;color:var(--navy)">${esc(lbl)}</span>
        <span style="color:var(--red);margin-left:8px">${esc(_ptEstError(r.error))}${probCount ? ` (${probCount} part${probCount === 1 ? "" : "s"})` : ""}</span>
      </div>`;
    }).join("");
    _ptOpenEstModal("Estimate results",
      `<p style="font-size:13px;margin:0 0 12px"><strong>${res.created}</strong> estimate${res.created === 1 ? "" : "s"} created. <strong>${res.blocked}</strong> blocked — these units have parts not yet linked to QuickBooks:</p>
       <div style="max-height:320px;overflow:auto;border:1px solid var(--border);border-radius:6px">${rows}</div>`);
  } else {
    toast(`${res.created} estimate${res.created === 1 ? "" : "s"} created`, "success");
  }
};
