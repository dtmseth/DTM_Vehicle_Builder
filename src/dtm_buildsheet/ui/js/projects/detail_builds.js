// ── Projects module: detail Builds tab ───────────────────────────────────────

const _PT_QUICKBOOKS_UI_ENABLED = window.DTM_QUICKBOOKS_UI_ENABLED === true;

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

function _ptBuildCardsMarkup(p) {
  const units = p.build_units || [];
  const pid   = esc(p.project_id);

  if (!units.length) {
    return `
      <p class="proj-empty-msg">No builds yet. Add fleet units in Project Details.</p>
      <div id="proj-action-status" class="proj-action-status" style="display:none"></div>`;
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
        const confirmed = !!ind.confirmed;

        const hasPdf    = !!(ind.pdf_path || "").trim();
        const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";

        const draftIdEsc  = hasDraft  ? esc(ind.draft_id) : "";
        return `<div class="proj-build-card proj-build-card--openable" id="build-card-${iid}" tabindex="0"
          role="button" aria-label="${hasDraft ? "Open" : "Set up"} ${esc(label)}"
          data-build-kind="ind" data-project-id="${pid}" data-unit-id="${uid}"
          data-individual-id="${iid}" data-draft-id="${draftIdEsc}" data-unit-index="${uIdx}">
          <div class="proj-build-card-top">
            <div class="proj-build-card-label">${esc(label)}</div>
            <button class="btn btn-secondary btn-sm proj-build-details-btn"
              onclick="PT_openDetailIndModal('${pid}','${uid}','${iid}')">Details</button>
          </div>
          <div class="proj-ind-card-badges">
            ${hasDraft  ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
            ${_PT_QUICKBOOKS_UI_ENABLED ? ((ind.qb_project_id || "").trim() ? `<span class="proj-confirmed-badge">◆ QB project</span>` : `<span class="proj-ind-not-setup">QB project needed</span>`) : ""}
            ${_PT_QUICKBOOKS_UI_ENABLED && (ind.qb_estimate_id || "").trim() ? `<span class="proj-confirmed-badge">📋 estimate</span>` : ""}
          </div>
          ${_ptRenderTimelineRow(ind)}
          <div class="proj-build-card-stats" id="build-stats-${iid}">
            ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
          </div>
          <div class="proj-build-actions">
            <button class="btn btn-secondary btn-sm"${buildDis}
              onclick="PT_buildOpenPptx('${pid}','${uid}','${iid}','ind')">
              📊 Preview / Edit in PowerPoint
            </button>
            <button class="btn btn-secondary btn-sm"${buildDis}
              onclick="PT_buildExportPdf('${pid}','${uid}','${iid}','ind')">
              📄 Export PDF
            </button>
            ${hasPdf ? `<button class="btn btn-secondary btn-sm"
              onclick="PT_buildOpenPdf('${pid}','${uid}','${iid}','ind')">📑 View PDF</button>` : ""}
            ${_PT_QUICKBOOKS_UI_ENABLED ? `<button class="btn btn-secondary btn-sm"${buildDis}
              onclick="PT_buildCreateEstimate('${pid}','${uid}','${iid}')">
              📋 ${(ind.qb_estimate_id || "").trim() ? "Re-estimate" : "QB Estimate"}
            </button>` : ""}
            <button class="btn btn-secondary btn-sm"
              onclick="PT_buildShowFolder('${pid}','${uid}','${iid}','ind')">📂 Show in folder</button>
          </div>
        </div>`;
      }).join("");
    } else {
      const hasDraft  = !!u.draft_id;
      const hasPdf    = !!(u.pdf_path || "").trim();
      const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";
      const draftIdEsc = hasDraft  ? esc(u.draft_id) : "";

      cards = `<div class="proj-build-card proj-build-card--openable" id="build-card-unit-${uid}" tabindex="0"
        role="button" aria-label="${hasDraft ? "Open" : "Set up"} ${esc(u.build_type || "Unit")}" data-build-kind="unit" data-project-id="${pid}" data-unit-id="${uid}"
        data-draft-id="${draftIdEsc}" data-unit-index="${uIdx}">
        <div class="proj-build-card-label">${esc(u.build_type || "Unit")} ×${u.quantity}</div>
        <div class="proj-ind-card-badges">
          ${hasDraft ? `<span class="proj-draft-badge">configured</span>` : `<span class="proj-ind-not-setup">not set up</span>`}
        </div>
        ${_ptRenderTimelineRow(u)}
        <div class="proj-build-card-stats" id="build-stats-unit-${uid}">
          ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
        </div>
        <div class="proj-build-actions">
          <button class="btn btn-secondary btn-sm"${buildDis}
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

  return `
    ${groups}
    <div class="proj-builds-footer">
      <button class="btn btn-primary btn-sm" onclick="PT_generateAll()">⚡ Generate All</button>
      <button class="btn btn-secondary btn-sm" onclick="PT_exportAllPdf()">📄 Export All PDFs</button>
      ${_PT_QUICKBOOKS_UI_ENABLED ? `<button class="btn btn-secondary btn-sm" onclick="PT_createEstimatesBatch()">📋 Prepare QB Estimates</button>` : ""}
    </div>
    <div id="proj-action-status" class="proj-action-status" style="display:none"></div>`;
}

function _ptOpenBuildCard(card) {
  const projectId = card.dataset.projectId;
  const unitId = card.dataset.unitId;
  const draftId = card.dataset.draftId || "";
  const unitIndex = Number(card.dataset.unitIndex);
  if (card.dataset.buildKind === "ind") {
    PT_setupOrEditBuildInd(projectId, unitId, card.dataset.individualId, draftId, unitIndex);
  } else {
    PT_setupOrEditBuildUnit(projectId, unitId, draftId, unitIndex);
  }
}

function _ptBindBuildCardOpeners(container) {
  container.querySelectorAll(".proj-build-card--openable").forEach(card => {
    card.addEventListener("click", event => {
      if (event.target.closest("button, a, input, select, textarea")) return;
      _ptOpenBuildCard(card);
    });
    card.addEventListener("keydown", event => {
      if (event.target !== card || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      _ptOpenBuildCard(card);
    });
  });
}

function _ptRenderBuildsTab(p) {
  // Kept as a compatibility entry point for project actions that refresh the
  // former Builds tab. Build cards now live on Overview.
  _ptRenderOverview(p);
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
    await _ptShowBuildEditor(existingDraftId, unit, project, "overview");
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
      await _ptShowBuildEditor(res.draft_id, unit, updated, "overview");
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
    await _ptShowBuildEditor(existingDraftId, unit, project, "overview", individual);
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
      await _ptShowBuildEditor(res.draft_id, updatedUnit, updated, "overview", updatedInd);
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
    await _ptShowBuildEditor(res.draft_id, unit, updated, "overview");
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
    await _ptShowBuildEditor(res.draft_id, updatedUnit, updated, "overview", updatedInd);
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
  custom_item_unavailable: "The active MISC PART item was not found in QuickBooks",
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
    customer_required: "Confirm the customer information before creating the estimate",
    customer_incomplete: "Complete the required customer and billing information before creating the estimate",
    customer_is_sub: "The linked QuickBooks customer is a sub-customer; relink the agency to a top-level customer",
    customer_create_failed: "QuickBooks did not return the new customer id",
    project_not_linked: "Set up this vehicle's QuickBooks Project before creating the estimate",
    project_identity_required: "Add a unit number before setting up the QuickBooks Project",
    invalid_project_id: "Paste the QuickBooks Project web address or project number",
    invalid_qb_project_ref: "QuickBooks rejected the saved Project link — set it up again below",
    validation_failed: "Some parts aren't linked to QuickBooks",
    validation_unavailable: "Could not check this vehicle right now",
    pricing_refresh_failed: "Could not refresh current QuickBooks Item prices — the estimate was not created",
    project_tax_sync_failed: "QuickBooks could not apply this agency's tax status to the vehicle Project",
    retail_customer_type_not_found: "QuickBooks does not have an active Retail customer type",
    duplicate_estimate_confirmation_required: "Choose whether to update the existing estimate or create a new one",
    existing_estimate_not_found: "The saved QuickBooks estimate no longer exists — choose Create new estimate",
    build_pdf_missing: "Export the build PDF before attaching it to QuickBooks",
    build_pdf_invalid: "The selected build attachment is not a valid PDF",
    build_pdf_outside_output: "The build PDF is outside the app's approved output folder",
    attachment_file_unreadable: "The build PDF could not be read",
    attachment_upload_failed: "QuickBooks rejected the build PDF attachment",
  };
  return m[code] || ("Estimate failed: " + (code || "unknown error"));
}

function _ptEstimateProblemText(problem) {
  const p = problem || {};
  const name = p.name || p.part_number || "Unnamed part";
  const reason = _QB_EST_REASON[p.reason] || p.reason || "Needs QuickBooks attention";
  return `${name}: ${reason}`;
}

function _ptToastEstimateBlockers(validation) {
  const v = validation || {};
  const blockers = [];
  if (!v.project?.ready) {
    blockers.push(v.project?.identity_ready
      ? "link this vehicle to its QuickBooks Project"
      : "add a unit number, then link the vehicle to its QuickBooks Project");
  }
  const problems = v.problems || [];
  if (problems.length === 1) {
    blockers.push(_ptEstimateProblemText(problems[0]));
  } else if (problems.length > 1) {
    blockers.push(`${problems.length} parts need QuickBooks attention (first: ${_ptEstimateProblemText(problems[0])})`);
  }
  toast(`Estimate not created — ${blockers.join(". ") || "the build needs attention"}`, "error");
}

function _ptProjectProblemNotice(validation) {
  const problems = validation?.problems || [];
  if (!problems.length) return "";
  const first = _ptEstimateProblemText(problems[0]);
  const more = problems.length > 1 ? `, plus ${problems.length - 1} more` : "";
  return `<div class="qb-setup-warning"><strong>There is another estimate blocker.</strong> ${esc(first + more)}. Finish the Project steps here, then resolve the part in <strong>Settings → QuickBooks</strong> before trying again.</div>`;
}

function _ptMoney2(n) {
  const v = Number(n);
  return isNaN(v) ? "$0.00" : "$" + v.toFixed(2);
}

function _ptEstimatePricingSummary(pricing) {
  const p = pricing || {};
  if (!p.rule_name) return "";
  const applied = (p.applied_discounts || []).map((row) =>
    `${esc(row.manufacturer)} ${Number(row.discount_percent).toFixed(1).replace(/\.0$/, "")}%${row.override ? " (customer)" : ""}`
  ).join(" · ");
  const source = p.source === "customer_override" ? "Default + customer override" : "Default";
  return `<div class="qb-est-pricing-summary">
    <div class="qb-est-pricing-title"><strong>${esc(source)} pricing</strong><span>${esc(p.rule_name)}</span></div>
    ${applied ? `<div class="qb-est-pricing-discounts">${applied}</div>` : ""}
    <div class="qb-est-pricing-totals">
      <span>List <strong>${_ptMoney2(p.list_total)}</strong></span>
      <span>Savings <strong>${_ptMoney2(p.savings)}</strong></span>
      <span>Customer <strong>${_ptMoney2(p.customer_total)}</strong></span>
    </div>
  </div>`;
}

function _ptBankTransferEstimateNote() {
  return `<div class="qb-est-bank-note"><strong>QuickBooks follow-up:</strong> After creating this estimate, open <strong>Discounts and fees</strong> in QuickBooks and turn on <strong>Bank transfer — 1% per transaction, max $20</strong>. QuickBooks does not expose this Estimate-form switch through the Accounting API, so Vehicle Builder cannot set or verify it automatically.</div>`;
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
  if (e.body) {
    e.body.innerHTML = bodyHtml;
    e.body.onclick = null;
  }
  if (e.create) {
    e.create.style.display = createLabel ? "" : "none";
    e.create.disabled = false;
    e.create.onclick = null;
    if (createLabel) e.create.textContent = createLabel;
  }
  e.modal?.removeAttribute("hidden");
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

function _ptCustomerEditor(customer, linked, missingFields = []) {
  const c = customer || {};
  if (linked && !missingFields.length) {
    return `<div style="padding:10px 12px;background:var(--surface-2);border-radius:6px;margin-top:8px;font-size:12px">
      <strong>${esc(c.name || "Customer")}</strong><br>
      <span style="color:var(--muted)">${esc(c.contact_name || "No contact name")}${c.contact_phone ? " · " + esc(c.contact_phone) : ""}${c.contact_email ? " · " + esc(c.contact_email) : ""}</span>
      <div style="color:var(--green);margin-top:4px">✓ Uses the existing top-level QuickBooks customer</div>
    </div>`;
  }
  const missing = missingFields.length
    ? `<div style="font-size:12px;color:var(--red);margin-bottom:8px">Required before this estimate: ${esc(missingFields.join(", "))}</div>`
    : "";
  const editorMessage = linked
    ? "This existing QuickBooks customer needs the information below before an estimate can be created. Confirming only updates the customer profile; it does not send an invoice or customer message."
    : "This agency is not linked to a top-level QuickBooks customer yet. Confirm these details before the app creates or links one. This does not send an invoice or customer message.";
  return `<div style="margin-top:8px;padding:10px 12px;border:1px solid var(--border);border-radius:6px">
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px">${editorMessage}</div>
    ${missing}
    <label style="font-size:12px;font-weight:600;color:var(--navy)">Customer name</label>
    <input type="text" id="qb-est-customer-name" value="${esc(c.name || "")}" autocomplete="organization" style="width:100%;box-sizing:border-box;margin:4px 0 7px" />
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Contact name</label><input type="text" id="qb-est-customer-contact" value="${esc(c.contact_name || "")}" autocomplete="name" style="width:100%;box-sizing:border-box;margin:4px 0 7px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Title</label><input type="text" id="qb-est-customer-title" value="${esc(c.contact_title || "")}" style="width:100%;box-sizing:border-box;margin:4px 0 7px" /></div>
    </div>
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Phone</label><input type="text" id="qb-est-customer-phone" value="${esc(c.contact_phone || "")}" autocomplete="tel" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Email</label><input type="email" id="qb-est-customer-email" value="${esc(c.contact_email || "")}" autocomplete="email" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Mobile</label><input type="text" id="qb-est-customer-mobile" value="${esc(c.mobile_phone || "")}" autocomplete="tel" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Fax</label><input type="text" id="qb-est-customer-fax" value="${esc(c.fax || "")}" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Website</label><input type="url" id="qb-est-customer-website" value="${esc(c.website || "")}" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="font-size:12px;font-weight:700;color:var(--navy);margin-top:12px">Billing address</div>
    <label style="font-size:12px;font-weight:600;color:var(--navy)">Street address</label>
    <input type="text" id="qb-est-customer-bill-line1" value="${esc(c.bill_address_line1 || "")}" autocomplete="address-line1" style="width:100%;box-sizing:border-box;margin:4px 0 7px" />
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Address line 2</label><input type="text" id="qb-est-customer-bill-line2" value="${esc(c.bill_address_line2 || "")}" autocomplete="address-line2" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Address line 3</label><input type="text" id="qb-est-customer-bill-line3" value="${esc(c.bill_address_line3 || "")}" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">City</label><input type="text" id="qb-est-customer-bill-city" value="${esc(c.bill_city || "")}" autocomplete="address-level2" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">State / Province</label><input type="text" id="qb-est-customer-bill-state" value="${esc(c.bill_state || "")}" autocomplete="address-level1" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Postal code</label><input type="text" id="qb-est-customer-bill-postal" value="${esc(c.bill_postal_code || "")}" autocomplete="postal-code" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Country</label><input type="text" id="qb-est-customer-bill-country" value="${esc(c.bill_country || "")}" autocomplete="country-name" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="font-size:12px;font-weight:700;color:var(--navy);margin-top:12px">Shipping address <span style="font-weight:400;color:var(--muted)">(optional)</span></div>
    <label style="display:flex;gap:7px;align-items:center;margin:5px 0;font-size:12px;color:var(--navy)"><input type="checkbox" id="qb-est-customer-ship-same" /> Same as billing address</label>
    <label style="font-size:12px;font-weight:600;color:var(--navy)">Street address</label>
    <input type="text" id="qb-est-customer-ship-line1" value="${esc(c.ship_address_line1 || "")}" autocomplete="shipping address-line1" style="width:100%;box-sizing:border-box;margin:4px 0 7px" />
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Address line 2</label><input type="text" id="qb-est-customer-ship-line2" value="${esc(c.ship_address_line2 || "")}" autocomplete="shipping address-line2" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Address line 3</label><input type="text" id="qb-est-customer-ship-line3" value="${esc(c.ship_address_line3 || "")}" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">City</label><input type="text" id="qb-est-customer-ship-city" value="${esc(c.ship_city || "")}" autocomplete="shipping address-level2" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">State / Province</label><input type="text" id="qb-est-customer-ship-state" value="${esc(c.ship_state || "")}" autocomplete="shipping address-level1" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Postal code</label><input type="text" id="qb-est-customer-ship-postal" value="${esc(c.ship_postal_code || "")}" autocomplete="shipping postal-code" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Country</label><input type="text" id="qb-est-customer-ship-country" value="${esc(c.ship_country || "")}" autocomplete="shipping country-name" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks taxable</label><select id="qb-est-customer-taxable" style="width:100%;box-sizing:border-box;margin-top:4px"><option value="false" ${c.taxable !== true ? "selected" : ""}>Not taxable</option><option value="true" ${c.taxable === true ? "selected" : ""}>Taxable</option></select></div>
      <div style="flex:2"><label style="font-size:12px;font-weight:600;color:var(--navy)">Customer notes</label><input type="text" id="qb-est-customer-notes" value="${esc(c.notes || "")}" style="width:100%;box-sizing:border-box;margin-top:4px" /></div>
    </div>
    <label style="display:flex;gap:7px;align-items:center;margin-top:10px;font-size:12px;color:var(--navy)"><input type="checkbox" id="qb-est-customer-confirm" /> Confirm customer details and allow customer creation or profile update</label>
  </div>`;
}

function _ptCustomerFieldsFromEditor() {
  const customerName = $("qb-est-customer-name");
  if (!customerName) return null;
  const value = id => $(id)?.value || "";
  const fields = {
    name: customerName.value || "",
    contact_name: value("qb-est-customer-contact"),
    contact_title: value("qb-est-customer-title"),
    contact_phone: value("qb-est-customer-phone"),
    contact_email: value("qb-est-customer-email"),
    mobile_phone: value("qb-est-customer-mobile"),
    fax: value("qb-est-customer-fax"),
    website: value("qb-est-customer-website"),
    bill_address_line1: value("qb-est-customer-bill-line1"),
    bill_address_line2: value("qb-est-customer-bill-line2"),
    bill_address_line3: value("qb-est-customer-bill-line3"),
    bill_city: value("qb-est-customer-bill-city"),
    bill_state: value("qb-est-customer-bill-state"),
    bill_postal_code: value("qb-est-customer-bill-postal"),
    bill_country: value("qb-est-customer-bill-country"),
    ship_address_line1: value("qb-est-customer-ship-line1"),
    ship_address_line2: value("qb-est-customer-ship-line2"),
    ship_address_line3: value("qb-est-customer-ship-line3"),
    ship_city: value("qb-est-customer-ship-city"),
    ship_state: value("qb-est-customer-ship-state"),
    ship_postal_code: value("qb-est-customer-ship-postal"),
    ship_country: value("qb-est-customer-ship-country"),
    notes: value("qb-est-customer-notes"),
  };
  if ($("qb-est-customer-ship-same")?.checked) {
    for (const suffix of ["line1", "line2", "line3", "city", "state", "postal_code", "country"]) {
      const billKey = `bill_address_${suffix}`;
      const shipKey = `ship_address_${suffix}`;
      fields[shipKey] = fields[billKey];
    }
  }
  const taxable = value("qb-est-customer-taxable");
  fields.taxable = taxable === "true";
  return fields;
}

async function _ptCopyProjectName(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    // pywebview/older browser fallback: select an off-screen temporary field.
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}

function _ptOpenProjectBindingModal(projectId, individualId, binding, onLinked = null, validation = null) {
  const b = binding || {};
  const projectName = b.project_name || "Vehicle project";
  const customerName = b.customer_name || "the correct customer";
  const identityReady = !!b.identity_ready;
  const projectRefInvalid = !!b.project_ref_invalid;
  const identityHint = (b.identity_labels || []).length
    ? `This project is for ${esc((b.identity_labels || []).join(" · "))}.`
    : "Add a unit number in the vehicle details first, then come back here.";
  const rejectedRefNotice = projectRefInvalid
    ? `<div class="qb-setup-warning"><strong>QuickBooks rejected the saved Project link.</strong> The Project may have been deleted, or it may belong to a different customer. Re-open or create the Project under <strong>${esc(customerName)}</strong>, then paste its Project page address here.</div>`
    : "";
  const instructions = identityReady
    ? `<ol class="qb-setup-steps">
         <li>In QuickBooks, open <strong>Projects</strong> and find this Project. If it does not exist, choose <strong>New project</strong>.</li>
         <li>Make sure it belongs to <strong>${esc(customerName)}</strong>.</li>
         <li>Use this exact project name:<button type="button" id="qb-project-name-copy" class="qb-project-name-copy" title="Click to copy this name"><span>${esc(projectName)}</span><span id="qb-project-name-copy-label">📋 Click to copy</span></button></li>
         <li>Open that Project, copy the web address from your browser's address bar, and paste it below. Do not use a customer page address or customer number.</li>
       </ol>
       <label class="qb-setup-label">QuickBooks project link</label>
       <input id="qb-project-id" class="qb-setup-input" autocomplete="off" placeholder="Paste the web address here" />
       <p class="qb-setup-hint">If you have the project number instead, you can paste that too.</p>`
    : `<div class="qb-setup-first">
         <strong>First, identify this vehicle.</strong>
         <ol class="qb-setup-steps">
           <li>Choose <strong>Open vehicle details</strong> below.</li>
           <li>Enter the vehicle's <strong>Unit number</strong>, then save.</li>
           <li>Choose <strong>QB Estimate</strong> again. This walkthrough will give you the exact QuickBooks Project name and ask for its Project page link.</li>
         </ol>
         <button type="button" class="btn btn-primary" id="qb-project-open-details">Open vehicle details</button>
       </div>`;

  _ptOpenEstModal("Set up the QuickBooks Project",
    `<p class="qb-setup-intro">Do this once for this vehicle. It only connects the vehicle to the Project you create in QuickBooks; it does not create an estimate or send anything to the customer.</p>
     <p class="qb-setup-identity">${identityHint}</p>${rejectedRefNotice}${_ptProjectProblemNotice(validation)}${instructions}`,
    identityReady ? "Save project link" : "");
  const e = _ptEstModalEls();
  $("qb-project-open-details")?.addEventListener("click", () => {
    const project = _PT.projects.find(p => p.project_id === projectId);
    const unit = (project?.build_units || []).find(u =>
      (u.individuals || []).some(i => i.individual_id === individualId));
    if (!unit) {
      toast("Could not find this vehicle's details", "error");
      return;
    }
    e.modal?.classList.remove("open");
    window.PT_openDetailIndModal(projectId, unit.unit_id, individualId);
  });
  $("qb-project-name-copy")?.addEventListener("click", async () => {
    const copied = await _ptCopyProjectName(projectName);
    const label = $("qb-project-name-copy-label");
    if (label) label.textContent = copied ? "✓ Copied" : "Copy failed";
    if (copied) toast("Project name copied", "success");
  });
  if (identityReady && e.create) {
    e.create.onclick = async () => {
      const qbProjectId = $("qb-project-id")?.value.trim() || "";
      e.create.disabled = true;
      e.create.textContent = "Saving…";
      try {
        const res = await api("/api/quickbooks/projects/bind", {
          project_id: projectId,
          individual_id: individualId,
          qb_project_id: qbProjectId,
        });
        if (!res?.ok) {
          toast(_ptEstError(res?.error), "error");
          e.create.disabled = false;
          e.create.textContent = "Save project link";
          return;
        }
        e.modal?.classList.remove("open");
        toast("QuickBooks Project saved", "success");
        if (onLinked) await onLinked();
        else await window.PT_buildCreateEstimate(projectId, "", individualId);
      } catch (_) {
        toast("Could not link the QuickBooks Project", "error");
        e.create.disabled = false;
        e.create.textContent = "Save project link";
      }
    };
  }
}

window.PT_buildCreateEstimate = async function (projectId, unitId, individualId) {
  if (!individualId) { toast("Estimates are created per individual unit", "error"); return; }
  if (!(await _ptQbConnected())) {
    toast("Connect QuickBooks first (Settings → QuickBooks)", "error");
    return;
  }
  const statusEl = $("proj-action-status");
  if (statusEl) _ptSetStatus(statusEl, "Refreshing prices and checking parts against QuickBooks…", "ok");
  let v;
  try {
    v = await api("/api/quickbooks/estimates/validate",
      { project_id: projectId, individual_id: individualId });
  } catch (e) { toast("Estimate not created — QuickBooks validation could not be completed", "error"); return; }
  if (statusEl) statusEl.style.display = "none";
  if (!v?.ok) { toast(_ptEstError(v?.error), "error"); return; }

  if (!v.project?.ready) {
    _ptToastEstimateBlockers(v);
    _ptOpenProjectBindingModal(projectId, individualId, v.project, null, v);
    return;
  }

  if (!v.can_create) {
    const probs = v.problems || [];
    if (!probs.length) { toast("No billable parts in this build", "error"); return; }
    _ptToastEstimateBlockers(v);
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

  let customer = v.customer;
  let customerLinked = !!v.customer_linked;
  let customerMissing = [];
  try {
    customer = await api("/api/quickbooks/estimates/customer-preview", { project_id: projectId });
    if (customer?.ok) {
      customerLinked = !!customer.customer_linked;
      customerMissing = customer.missing_fields || [];
      customer = customer.customer;
    }
  } catch (_) {}
  if (!customerLinked || customerMissing.length) {
    const detail = customerMissing.length
      ? `complete customer fields: ${customerMissing.join(", ")}`
      : "confirm or create the QuickBooks customer";
    toast(`Estimate not created yet — ${detail}`, "error");
  }

  _ptOpenEstModal("Create QuickBooks estimate",
    `<p style="font-size:13px;margin:0 0 14px">Drafts a <strong>non-posting estimate</strong> under the agency's top-level customer and this vehicle's real QuickBooks Project. No sub-customer is created.</p>
     ${_ptEstimatePricingSummary(v.pricing)}
     ${_ptBankTransferEstimateNote()}
     <div style="display:flex;gap:24px;font-size:13px;margin-bottom:14px">
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Line items</div><div style="font-weight:700;color:var(--navy);font-size:18px">${v.line_count}</div></div>
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Estimated total</div><div style="font-weight:700;color:var(--navy);font-size:18px">${_ptMoney2(v.total)}</div></div>
     </div>
     ${v.existing_estimate_id ? `<div class="qb-est-bank-note"><strong>An estimate already exists for this vehicle.</strong><br>
       <label><input type="radio" name="qb-est-existing-action" value="update" checked> Update existing estimate ${esc(v.existing_estimate_id)}</label><br>
       <label><input type="radio" name="qb-est-existing-action" value="create_new"> Create a separate new estimate</label></div>` : ""}
     ${v.pdf_available
       ? `<label class="qb-est-pdf-option"><input type="checkbox" id="qb-est-attach-pdf" checked> Attach build PDF: <strong>${esc(v.pdf_name || "build.pdf")}</strong></label>`
       : `<div class="qb-est-bank-note"><strong>Build PDF:</strong> Export the PDF first if you want it attached to this estimate.</div>`}
     <label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks customer</label>
     ${_ptCustomerEditor(customer, customerLinked, customerMissing)}
     <label style="font-size:12px;font-weight:600;color:var(--navy)">Memo (optional)</label>
     <input type="text" id="qb-est-memo" placeholder="Appears on the estimate" autocomplete="off" style="width:100%;box-sizing:border-box;margin-top:5px" />`,
    customerLinked && !customerMissing.length
      ? (v.existing_estimate_id ? "Continue" : "Create estimate")
      : customerLinked ? "Update customer & estimate" : "Create customer & estimate");
  const e = _ptEstModalEls();
  if (e.create) e.create.onclick = () => _ptDoCreateEstimate(projectId, individualId);
};

async function _ptDoCreateEstimate(projectId, individualId, chosenAction = null, chosenAttachPdf = null) {
  const e = _ptEstModalEls();
  const memo = $("qb-est-memo")?.value || "";
  const customerFields = _ptCustomerFieldsFromEditor();
  const customerConfirmed = !!$("qb-est-customer-confirm")?.checked;
  const existingAction = chosenAction ?? document.querySelector('input[name="qb-est-existing-action"]:checked')?.value ?? "";
  const attachPdf = chosenAttachPdf ?? !!$("qb-est-attach-pdf")?.checked;
  if (e.create) { e.create.disabled = true; e.create.textContent = "Creating…"; }
  try {
    const res = await api("/api/quickbooks/estimates/create",
      { project_id: projectId, individual_id: individualId, memo,
        customer_confirmed: customerConfirmed, customer_fields: customerFields,
        existing_action: existingAction, attach_pdf: attachPdf });
    if (res?.ok) {
      e.modal?.classList.remove("open");
      const verb = res.action === "updated" ? "updated" : "created";
      const attachment = res.attachment;
      if (attachment?.ok === false) {
        toast(`Estimate ${verb}${res.doc_number ? " #" + res.doc_number : ""}, but the build PDF could not be attached: ${_ptEstError(attachment.error)}`, "error");
      } else {
        const attached = attachment?.skipped === "already_attached" ? " · PDF already attached" : attachment?.ok ? " · PDF attached" : "";
        toast(`Estimate ${verb}${res.doc_number ? " #" + res.doc_number : ""} · ${_ptMoney2(res.total)}${attached}`, "success");
      }
      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId);
      if (updated) { _PT.viewProject = updated; _ptRenderBuildsTab(updated); }
    } else {
      if (res?.error === "customer_required" || res?.error === "customer_incomplete") {
        const missing = res?.missing_fields || [];
        const detail = missing.length ? `: ${missing.join(", ")}` : "";
        toast(`${_ptEstError(res.error)}${detail}`, "error");
        e.body.innerHTML = `<p style="font-size:13px;margin:0 0 10px">Before this estimate is created, confirm the customer information below. The app will reuse an exact top-level QB customer when one exists, or create a new top-level customer.</p>
          <label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks customer</label>
          ${_ptCustomerEditor(res.customer, false, missing)}
          <label style="font-size:12px;font-weight:600;color:var(--navy)">Memo (optional)</label>
          <input type="text" id="qb-est-memo" placeholder="Appears on the estimate" autocomplete="off" style="width:100%;box-sizing:border-box;margin-top:5px" />`;
        e.create.disabled = false;
        e.create.textContent = "Create customer & estimate";
        e.create.onclick = () => _ptDoCreateEstimate(projectId, individualId, existingAction, attachPdf);
      } else if (res?.error === "invalid_qb_project_ref") {
        toast(_ptEstError(res.error), "error");
        _ptOpenProjectBindingModal(projectId, individualId, res.project);
      } else {
        toast(_ptEstError(res?.error), "error");
        if (e.create) { e.create.disabled = false; e.create.textContent = "Try again"; }
      }
    }
  } catch (err) {
    toast("Estimate creation failed — QuickBooks did not complete the request", "error");
    if (e.create) { e.create.disabled = false; e.create.textContent = "Try again"; }
  }
}

function _ptBatchEstimateTargets(project) {
  const targets = [];
  for (const unit of (project.build_units || [])) {
    for (const individual of (unit.individuals || [])) {
      if (!individual.draft_id) continue;
      targets.push({ individualId: individual.individual_id, label: _ptLabelForInd(project, individual.individual_id) });
    }
  }
  return targets;
}

function _ptBatchIssue(check) {
  const v = check.validation || {};
  if (!v.ok) return _ptEstError(v.error);
  if (!v.project?.ready) return "QuickBooks Project still needs to be set up";
  if (!v.can_create) {
    const count = (v.problems || []).length;
    return count ? `${count} part${count === 1 ? "" : "s"} need attention` : "Build needs attention";
  }
  return "Needs attention";
}

async function _ptOpenBatchEstimateSetup(project) {
  const targets = _ptBatchEstimateTargets(project);
  if (!targets.length) { toast("No configured individual vehicles to estimate", "error"); return; }

  _ptOpenEstModal("Prepare batch QuickBooks estimates",
    `<p style="font-size:13px;margin:0">Checking ${targets.length} vehicle${targets.length === 1 ? "" : "s"} before anything is created…</p>`);
  let checks, customer;
  try {
    [checks, customer] = await Promise.all([
      Promise.all(targets.map(async (target) => {
        try {
          const validation = await api("/api/quickbooks/estimates/validate", {
            project_id: project.project_id, individual_id: target.individualId,
          });
          return { ...target, validation };
        } catch (_) {
          return { ...target, validation: { ok: false, error: "validation_unavailable" } };
        }
      })),
      api("/api/quickbooks/estimates/customer-preview", { project_id: project.project_id }),
    ]);
  } catch (_) {
    toast("Could not check the batch", "error");
    return;
  }

  const customerReady = !!(customer?.ok && customer.customer_linked && customer.customer_complete);
  const ready = checks.filter((check) => {
    const v = check.validation || {};
    return v.ok && v.can_create && v.project?.ready;
  });
  const attention = checks.filter((check) => !ready.includes(check));
  const readyRows = ready.length
    ? ready.map((check) => `<div style="padding:7px 10px;border-bottom:1px solid var(--border);font-size:12px"><strong style="color:var(--navy)">${esc(check.label)}</strong><span style="color:var(--green);margin-left:7px">✓ Ready</span></div>`).join("")
    : `<div style="padding:10px;font-size:12px;color:var(--muted)">No vehicles are ready yet.</div>`;
  const attentionRows = attention.length
    ? attention.map((check, index) => {
      const needsProject = check.validation?.ok && !check.validation?.project?.ready;
      const action = needsProject ? `<button class="btn btn-secondary btn-sm" data-qb-batch-link="${index}">Set up Project</button>` : "";
      return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;border-bottom:1px solid var(--border);font-size:12px"><div><strong style="color:var(--navy)">${esc(check.label)}</strong><br><span style="color:var(--red)">${esc(_ptBatchIssue(check))}</span></div>${action}</div>`;
    }).join("")
    : `<div style="padding:10px;font-size:12px;color:var(--green)">Every configured vehicle is ready.</div>`;
  const customerStatus = customerReady
    ? `<div style="padding:8px 10px;margin-bottom:12px;border:1px solid #86c99a;border-radius:6px;background:#f0fbf3;font-size:12px;color:var(--green)">✓ Customer is ready in QuickBooks.</div>`
    : `<div style="padding:9px 11px;margin-bottom:12px;border:1px solid #f0c36d;border-radius:6px;background:#fff7e6;font-size:12px;line-height:1.45"><strong>Customer setup needed first.</strong> Create an estimate for one vehicle first to review and confirm the customer details. Then return here to create the rest as a batch.</div>`;
  const batchListTotal = ready.reduce((sum, check) => sum + Number(check.validation?.pricing?.list_total || 0), 0);
  const batchCustomerTotal = ready.reduce((sum, check) => sum + Number(check.validation?.pricing?.customer_total || 0), 0);
  const batchPricing = ready.length ? {
    rule_name: "Default",
    source: ready.some((check) => check.validation?.pricing?.source === "customer_override") ? "customer_override" : "default",
    list_total: batchListTotal,
    customer_total: batchCustomerTotal,
    savings: batchListTotal - batchCustomerTotal,
    applied_discounts: [],
  } : null;

  _ptOpenEstModal("Prepare batch QuickBooks estimates",
    `<p style="font-size:13px;margin:0 0 12px">Each vehicle gets its own non-posting QuickBooks estimate. Nothing is created until you choose <strong>Create estimates</strong>.</p>${customerStatus}${_ptEstimatePricingSummary(batchPricing)}${_ptBankTransferEstimateNote()}
     <div style="display:flex;gap:12px;margin-bottom:12px"><div style="flex:1;padding:10px;border:1px solid #86c99a;border-radius:6px"><div style="font-size:11px;color:var(--muted);text-transform:uppercase">Ready to create</div><strong style="font-size:20px;color:var(--green)">${ready.length}</strong></div><div style="flex:1;padding:10px;border:1px solid var(--border);border-radius:6px"><div style="font-size:11px;color:var(--muted);text-transform:uppercase">Still needs setup</div><strong style="font-size:20px;color:var(--navy)">${attention.length}</strong></div></div>
     <div style="font-size:12px;font-weight:700;color:var(--navy);margin:0 0 4px">Ready vehicles</div><div style="max-height:140px;overflow:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:12px">${readyRows}</div>
     <div style="font-size:12px;font-weight:700;color:var(--navy);margin:0 0 4px">Vehicles needing attention</div><div style="max-height:220px;overflow:auto;border:1px solid var(--border);border-radius:6px">${attentionRows}</div>`,
    customerReady && ready.length ? `Create ${ready.length} estimate${ready.length === 1 ? "" : "s"}` : "");
  const e = _ptEstModalEls();
  if (e.body) {
    e.body.onclick = (event) => {
      const button = event.target.closest("[data-qb-batch-link]");
      if (!button) return;
      const check = attention[Number(button.getAttribute("data-qb-batch-link"))];
      if (!check?.validation?.project) return;
      _ptOpenProjectBindingModal(project.project_id, check.individualId, check.validation.project, async () => {
        await _ptLoadAll();
        const updated = _PT.projects.find((p) => p.project_id === project.project_id) || project;
        _PT.viewProject = updated;
        await _ptOpenBatchEstimateSetup(updated);
      });
    };
  }
  if (e.create && customerReady && ready.length) {
    e.create.onclick = () => _ptRunBatchEstimates(project, ready.map((check) => check.individualId));
  }
}

async function _ptRunBatchEstimates(project, individualIds) {
  const e = _ptEstModalEls();
  e.modal?.classList.remove("open");
  const statusEl = $("proj-action-status");
  const footerBtns = document.querySelectorAll(".proj-builds-footer .btn");
  footerBtns.forEach((button) => { button.disabled = true; });
  if (statusEl) _ptSetStatus(statusEl, "Creating estimates…", "ok");
  let res;
  try {
    res = await api("/api/quickbooks/estimates/create-batch", {
      project_id: project.project_id, individual_ids: individualIds,
    });
  } catch (_) {
    toast("Batch estimate failed", "error");
    footerBtns.forEach((button) => { button.disabled = false; });
    if (statusEl) statusEl.style.display = "none";
    return;
  }
  footerBtns.forEach((button) => { button.disabled = false; });
  if (!res?.ok) {
    toast(_ptEstError(res?.error), "error");
    if (statusEl) statusEl.style.display = "none";
    return;
  }
  await _ptLoadAll();
  const updated = _PT.projects.find((p) => p.project_id === project.project_id);
  if (updated) { _PT.viewProject = updated; _ptRenderBuildsTab(updated); }
  if (statusEl) _ptSetStatus(statusEl, `✅ ${res.created} created · ${res.blocked} blocked`, res.blocked ? "err" : "good");
  const blocked = (res.results || []).filter((result) => !result.ok);
  if (!blocked.length) {
    toast(`${res.created} estimate${res.created === 1 ? "" : "s"} created`, "success");
    return;
  }
  const rows = blocked.map((result) => {
    const count = (result.problems || []).length;
    const label = _ptLabelForInd(updated || project, result.individual_id);
    return `<div style="padding:7px 10px;border-bottom:1px solid var(--border);font-size:12px"><span style="font-weight:600;color:var(--navy)">${esc(label)}</span><span style="color:var(--red);margin-left:8px">${esc(_ptEstError(result.error))}${count ? ` (${count} part${count === 1 ? "" : "s"})` : ""}</span></div>`;
  }).join("");
  _ptOpenEstModal("Estimate results",
    `<p style="font-size:13px;margin:0 0 12px"><strong>${res.created}</strong> estimate${res.created === 1 ? "" : "s"} created. <strong>${res.blocked}</strong> still need attention:</p><div style="max-height:320px;overflow:auto;border:1px solid var(--border);border-radius:6px">${rows}</div>`);
}

window.PT_createEstimatesBatch = async function () {
  if (!_PT.viewProject) return;
  if (!(await _ptQbConnected())) {
    toast("Connect QuickBooks first (Settings → QuickBooks)", "error");
    return;
  }
  await _ptOpenBatchEstimateSetup(_PT.viewProject);
};
