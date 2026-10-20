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

function _ptFinalizationBadge(holder) {
  const status = holder.status || "draft";
  if (status === "finalized") {
    if (holder.shop_publication_status === "reference_review_required") {
      return `<span class="proj-final-badge proj-final-badge--reopened">Reference changes need review · Shop package unchanged</span>`;
    }
    const who = _ptFirstName(holder.finalized_by);
    const when = _ptShortAgo(holder.finalized_at);
    return `<span class="proj-final-badge proj-final-badge--final">✓ Design finalized${who ? ` by ${esc(who)}` : ""}${when ? ` · ${when}` : ""}</span>`;
  }
  if (status === "reopened") {
    return `<span class="proj-final-badge proj-final-badge--reopened">Reopened for changes</span>`;
  }
  return `<span class="proj-final-badge">Draft</span>`;
}

function _ptPdfOptionsMarkup(projectId, unitId, individualId, type, holder, disabledAttrs) {
  const hasPdf = !!String(holder.pdf_path || "").trim();
  const shopVehiclePath = String(holder.shop_vehicle_folder_path || "").trim();
  const hasShopFolder = !!(shopVehiclePath || String(holder.shop_pdf_path || "").trim());
  return `<details class="proj-build-action-menu">
    <summary class="btn btn-secondary btn-sm">PDF Options</summary>
    <div class="proj-build-action-menu-items">
      ${_ptCanEditProjects() ? `<button type="button"${disabledAttrs}
        onclick="PT_buildExportPdf('${projectId}','${unitId}','${individualId}','${type}')">Export / update PDF</button>` : ""}
      ${hasPdf ? `<button type="button"
        onclick="PT_buildOpenPdf('${projectId}','${unitId}','${individualId}','${type}')">View PDF</button>` : ""}
      ${shopVehiclePath ? `<button type="button" data-library-target="shop" data-folder-path="${esc(shopVehiclePath)}"
        onclick="PT_openCloudFolder(this)">Open Shop folder</button>` : `<button type="button"
        onclick="PT_buildShowFolder('${projectId}','${unitId}','${individualId}','${type}')">${hasShopFolder ? "Open Shop folder" : "Open PDF folder"}</button>`}
    </div>
  </details>`;
}

function _ptQuickBooksOptionsMarkup(projectId, unitId, individualId, holder, disabledAttrs) {
  if (!_PT_QUICKBOOKS_UI_ENABLED || !individualId || !_ptCanManageEstimates()) return "";
  return `<details class="proj-build-action-menu">
    <summary class="btn btn-secondary btn-sm">QuickBooks</summary>
    <div class="proj-build-action-menu-items">
      <button type="button"
        onclick="PT_setupQbProject('${projectId}','${individualId}')">${String(holder.qb_project_id || "").trim() ? "Manage QB project" : "Set up QB project"}</button>
      <button type="button"
        onclick="PT_linkQbEstimate('${projectId}','${individualId}')">${String(holder.qb_estimate_id || "").trim() ? "Manage estimate connection" : "Connect existing estimate"}</button>
      ${String(holder.qb_estimate_id || "").trim() && String(holder.draft_id || "").trim() ? `<button type="button"${disabledAttrs}
        onclick="PT_previewQbEstimateImport('${projectId}','${individualId}')">Import Parts From QB</button>` : ""}
      <button type="button"${disabledAttrs}
        onclick="PT_buildCreateEstimate('${projectId}','${unitId}','${individualId}')">${String(holder.qb_estimate_id || "").trim() ? "Update connected estimate" : "Create new estimate"}</button>
    </div>
  </details>`;
}

function _ptPhotoOptionsMarkup(project, projectId, unitId, individualId) {
  const unit = (project.build_units || []).find(item => item.unit_id === unitId);
  const holder = individualId
    ? (unit?.individuals || []).find(item => item.individual_id === individualId)
    : unit;
  const publication = String(holder?.shop_publication_status || "not_published");
  const companyVehiclePath = String(holder?.company_vehicle_folder_path || "").trim();
  const companyReferencePath = companyVehiclePath ? `${companyVehiclePath}/Build Reference Photos` : "";
  const companyCompletedPath = companyVehiclePath ? `${companyVehiclePath}/Completed Build Photos` : "";
  const shopVehiclePath = String(holder?.shop_vehicle_folder_path || "").trim();
  const publicationNote = publication === "reference_review_required" ? "Reference photos changed. Review them and export/update the PDF before approving an updated Shop package."
    : publication === "published" ? "Final PDF and references are published to the Shop folder."
    : ["pending", "publishing"].includes(publication) ? "Shop publication is pending."
      : ["error", "withdrawal_error"].includes(publication) ? "Shop publication needs a cloud-sync retry."
        : "Completed Build Photos are mirrored from Shop Documents to Company Files.";
  return `${_ptHasCapability("completed_media.upload") ? `<button class="btn btn-primary btn-sm" type="button"
    onclick="DTMUploads.choose({projectId:'${esc(projectId)}',kind:'completed',unitId:'${esc(unitId)}',individualId:'${esc(individualId)}'})">Upload media / files</button>` : ""}
    ${_ptCompletedPhotoButtonMarkup(projectId, unitId, individualId)}
    <details class="proj-build-action-menu proj-build-folder-menu">
    <summary class="btn btn-secondary btn-sm">Folder options</summary>
    <div class="proj-build-action-menu-items">
      ${companyReferencePath ? `<button type="button" data-library-target="company" data-folder-path="${esc(companyReferencePath)}"
        onclick="PT_openCloudFolder(this)">Open Company reference folder</button>
      <button type="button" data-library-target="company" data-folder-path="${esc(companyCompletedPath)}"
        onclick="PT_openCloudFolder(this)">Open Company completed photos</button>` : ""}
      ${shopVehiclePath ? `<button type="button" data-library-target="shop" data-folder-path="${esc(`${shopVehiclePath}/Build Reference Photos`)}"
        onclick="PT_openCloudFolder(this)">Open reference photos folder</button>
      <button type="button" data-library-target="shop" data-folder-path="${esc(`${shopVehiclePath}/Completed Build Photos`)}"
        onclick="PT_openCloudFolder(this)">Open Shop completed photos</button>` :
        `<span class="proj-build-action-menu-note">Photo-folder locations will appear after folder provisioning.</span>`}
      <span class="proj-build-action-menu-note">${esc(publicationNote)}</span>
    </div>
  </details>`;
}

function _ptUnitNotesMarkup(notes, individualId) {
  const text = String(notes || "").trim();
  if (!text) return "";
  return `<div class="proj-unit-notes" data-unit-notes-card data-individual-id="${esc(individualId)}" aria-label="Unit notes">
    <strong>Unit notes</strong>
    <p class="proj-unit-notes-preview">${esc(text)}</p>
    <button type="button" class="proj-unit-notes-more" data-unit-notes-more hidden>Read more</button>
  </div>`;
}

function _ptQuoteReferencesMarkup(references) {
  const refs = (references || []).filter(ref => String(ref.quote_number || "").trim());
  if (!refs.length) return "";
  return `<div class="proj-card-quotes"><strong>Quotes:</strong> ${refs.map(ref => {
    const status = ref.match_status === "linked" ? " ✓" : "";
    const klass = ref.state === "obsolete" ? "proj-card-quote--obsolete" : "";
    return `<span class="${klass}" title="${ref.state === "obsolete" ? "Obsolete quote" : "Current quote"}">${esc(ref.quote_number)}${status}</span>`;
  }).join(" · ")}</div>`;
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
    const vmLabel = _ptVehicleModelLabel(u);
    const inds    = u.individuals || [];
    const uid     = esc(u.unit_id);

    let cards;
    if (inds.length > 0) {
      cards = inds.map((ind, j) => {
        const label     = _ptUnitLabel(u, ind, j);
        const iid       = esc(ind.individual_id);
        const hasDraft  = !!ind.draft_id;
        const confirmed = !!ind.confirmed;

        const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";

        const draftIdEsc  = hasDraft  ? esc(ind.draft_id) : "";
        const canOpen = _ptCanEditProjects() || hasDraft || ind.status === "finalized";
        return `<div class="proj-build-card${canOpen ? " proj-build-card--openable" : ""}" id="build-card-${iid}"
          ${canOpen ? `tabindex="0" role="button" aria-label="${hasDraft ? "Open" : "Set up"} ${esc(label)}"` : ""}
          data-build-kind="ind" data-project-id="${pid}" data-unit-id="${uid}"
          data-individual-id="${iid}" data-draft-id="${draftIdEsc}" data-unit-index="${uIdx}"
          data-build-label="${esc(label)}" data-final-status="${esc(ind.status || "draft")}">
          <div class="proj-build-card-top">
            <div class="proj-build-card-label">${esc(label)}</div>
            <button class="btn btn-secondary btn-sm proj-build-details-btn"
              onclick="PT_openDetailIndModal('${pid}','${uid}','${iid}')">Details</button>
          </div>
          <div class="proj-ind-card-badges">
            ${confirmed ? `<span class="proj-confirmed-badge">✓ confirmed</span>` : ""}
            ${_ptFinalizationBadge(ind)}
          </div>
          ${_ptUnitNotesMarkup(ind.notes, ind.individual_id)}
          ${_ptQuoteReferencesMarkup(ind.quote_references)}
          <div class="proj-build-card-stats" id="build-stats-${iid}">
            ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
          </div>
          <div class="proj-build-actions">
            ${_ptPdfOptionsMarkup(pid, uid, iid, "ind", ind, buildDis)}
            ${_ptQuickBooksOptionsMarkup(pid, uid, iid, ind, buildDis)}
            ${_ptPhotoOptionsMarkup(p, pid, uid, iid)}
            ${(p.project_type||'build')!=='build'?`${ind.previous_build?.project_id?`<button class="btn btn-secondary btn-sm" type="button" onclick="PT_previousBuild('${pid}','${uid}','${iid}')">Previous Build Design</button>`:''}${_ptCanEditProjects()?`<button class="btn btn-secondary btn-sm" type="button" onclick="PT_linkPreviousBuild('${pid}','${uid}','${iid}')">${ind.previous_build?.project_id?'Change previous build':'Link previous build'}</button>`:''}`:''}
            ${_ptCanEditProjects() ? `<button class="btn btn-sm proj-final-review-btn${ind.status === "finalized" ? " proj-final-review-btn--finalized" : ""}"${buildDis}
              onclick="PT_reviewFinalization('${pid}','${uid}','${iid}','ind')">${ind.status === "finalized" ? "✓ Design finalized" : "Finalize design"}</button>` : ""}
          </div>
        </div>`;
      }).join("");
    } else {
      const hasDraft  = !!u.draft_id;
      const buildDis  = !hasDraft ? ` disabled title="Configure build first"` : "";
      const draftIdEsc = hasDraft  ? esc(u.draft_id) : "";
      const groupLabel = _ptUnitLabel(u, null, uIdx);
      const canOpen = _ptCanEditProjects() || hasDraft || u.status === "finalized";

      cards = `<div class="proj-build-card${canOpen ? " proj-build-card--openable" : ""}" id="build-card-unit-${uid}"
        ${canOpen ? `tabindex="0" role="button" aria-label="${hasDraft ? "Open" : "Set up"} ${esc(groupLabel)}"` : ""}
        data-build-kind="unit" data-project-id="${pid}" data-unit-id="${uid}"
        data-draft-id="${draftIdEsc}" data-unit-index="${uIdx}"
        data-build-label="${esc(groupLabel)}" data-final-status="${esc(u.status || "draft")}">
        <div class="proj-build-card-label">${esc(groupLabel)} ×${u.quantity}</div>
        <div class="proj-ind-card-badges">
          ${_ptFinalizationBadge(u)}
        </div>
        <div class="proj-build-card-stats" id="build-stats-unit-${uid}">
          ${hasDraft ? `<span class="proj-stats-loading">Loading…</span>` : ""}
        </div>
        <div class="proj-build-actions">
          ${_ptPdfOptionsMarkup(pid, uid, "", "unit", u, buildDis)}
          ${_ptPhotoOptionsMarkup(p, pid, uid, "")}
          ${_ptCanEditProjects() ? `<button class="btn btn-sm proj-final-review-btn${u.status === "finalized" ? " proj-final-review-btn--finalized" : ""}"${buildDis}
            onclick="PT_reviewFinalization('${pid}','${uid}','','unit')">${u.status === "finalized" ? "✓ Design finalized" : "Finalize design"}</button>` : ""}
        </div>
      </div>`;
    }

    return `<div class="proj-unit-group">
      <div class="proj-unit-group-hdr">
        <span class="proj-unit-group-vehicle">${esc(vmLabel)}</span>
        <span class="proj-unit-group-meta">${esc(u.build_type || "—")} · ${u.quantity}× · ${esc(pLabel)}</span>
        ${_ptGroupReferenceButton(p, u)}
      </div>
      <div class="proj-build-btn-row">${cards}</div>
    </div>`;
  }).join("");

  return `
    ${groups}
    ${_ptCanEditProjects() ? `<div class="proj-builds-footer">
      <button class="btn btn-primary btn-sm" onclick="PT_exportAllPdf()">Export / update all PDFs</button>
      ${_PT_QUICKBOOKS_UI_ENABLED ? `<button class="btn btn-secondary btn-sm" onclick="PT_createEstimatesBatch()">QuickBooks options</button>` : ""}
    </div>` : ""}
    <div id="proj-action-status" class="proj-action-status" style="display:none"></div>`;
}

function _ptCloseUnitNotesModal() {
  $("unit-notes-modal")?.classList.remove("open");
}

window.PT_openUnitNotes = function (individualId) {
  let selected = null;
  let selectedUnit = null;
  let label = "Unit";
  for (const buildUnit of (_PT.viewProject?.build_units || [])) {
    const index = (buildUnit.individuals || []).findIndex(
      individual => individual.individual_id === individualId
    );
    if (index >= 0) {
      selected = buildUnit.individuals[index];
      selectedUnit = buildUnit;
      label = _ptUnitLabel(buildUnit, selected, index);
      break;
    }
  }
  const notes = String(selected?.notes || "").trim();
  if (!notes) return;

  const modal = $("unit-notes-modal");
  if (!_PT._unitNotesModalWired) {
    _PT._unitNotesModalWired = true;
    $("unit-notes-modal-close")?.addEventListener("click", _ptCloseUnitNotesModal);
    $("unit-notes-modal-done")?.addEventListener("click", _ptCloseUnitNotesModal);
    $("unit-notes-modal-edit")?.addEventListener("click", () => {
      const context = _PT._unitNotesContext;
      if (!context) return;
      _ptCloseUnitNotesModal();
      if (context.finalized) {
        PT_reviewFinalization(
          context.projectId, context.unitId, context.individualId, "ind", true,
        );
      } else {
        PT_openDetailIndModal(context.projectId, context.unitId, context.individualId);
      }
    });
    modal?.addEventListener("click", event => {
      if (event.target === modal) _ptCloseUnitNotesModal();
    });
  }
  if ($("unit-notes-modal-title")) $("unit-notes-modal-title").textContent = `${label} — Unit notes`;
  if ($("unit-notes-modal-body")) $("unit-notes-modal-body").textContent = notes;
  _PT._unitNotesContext = {
    projectId: _PT.viewProject?.project_id || "",
    unitId: selectedUnit?.unit_id || "",
    individualId,
    finalized: selected?.status === "finalized",
  };
  const editButton = $("unit-notes-modal-edit");
  if (editButton) {
    editButton.hidden = !_ptCanEditProjects();
    editButton.textContent = selected?.status === "finalized" ? "Reopen to edit" : "Edit notes";
  }
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");
  $("unit-notes-modal-close")?.focus();
};

function _ptBindUnitNoteCards(container) {
  requestAnimationFrame(() => {
    container.querySelectorAll("[data-unit-notes-card]").forEach(card => {
      const preview = card.querySelector(".proj-unit-notes-preview");
      const readMore = card.querySelector("[data-unit-notes-more]");
      if (!preview || !readMore) return;
      const overflowing = preview.scrollHeight > preview.clientHeight + 1;
      readMore.hidden = !overflowing;
      if (!overflowing) return;

      card.classList.add("proj-unit-notes--overflowing");
      const open = () => window.PT_openUnitNotes(card.dataset.individualId || "");
      card.addEventListener("click", open);
    });
  });
}

function _ptOpenBuildCard(card) {
  const projectId = card.dataset.projectId;
  const unitId = card.dataset.unitId;
  const draftId = card.dataset.draftId || "";
  const unitIndex = Number(card.dataset.unitIndex);
  if (draftId && card.dataset.buildKind !== "historical" &&
      (card.dataset.finalStatus === "finalized" || !_ptCanEditProjects())) {
    const project = _PT.projects.find(item => item.project_id === projectId) || _PT.viewProject;
    const unit = (project?.build_units || []).find(item => item.unit_id === unitId);
    const individual = (unit?.individuals || []).find(
      item => item.individual_id === (card.dataset.individualId || "")
    );
    if (project && unit) _ptShowBuildEditor(draftId, unit, project, "overview", individual);
  } else if (card.dataset.finalStatus === "finalized") {
    PT_reviewFinalization(
      projectId,
      unitId,
      card.dataset.individualId || "",
      card.dataset.buildKind || "unit",
      false,
    );
  } else if (card.dataset.buildKind === "historical") {
    PT_openDetailIndModal(projectId, unitId, card.dataset.individualId || "");
  } else if (card.dataset.buildKind === "ind") {
    PT_setupOrEditBuildInd(projectId, unitId, card.dataset.individualId, draftId, unitIndex);
  } else {
    PT_setupOrEditBuildUnit(projectId, unitId, draftId, unitIndex);
  }
}

$("pbe-reopen-btn")?.addEventListener("click", () => {
  const projectId = _PT.pbeProject?.project_id || "";
  const unitId = _PT.pbeUnit?.unit_id || "";
  const individualId = _PT.pbeIndividual?.individual_id || "";
  if (!projectId || !unitId) return;
  PT_reviewFinalization(projectId, unitId, individualId, individualId ? "ind" : "unit", true);
});

function _ptCloseReadOnlyBuildModal() {
  const modal = $("build-readonly-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
}

function _ptReadOnlyBuildNotes(notes) {
  const entries = Object.entries(notes || {}).filter(([, value]) =>
    Array.isArray(value) ? value.length : String(value || "").trim()
  );
  if (!entries.length) return `<p class="build-readonly-empty">No build notes.</p>`;
  return entries.map(([heading, value]) => {
    const lines = Array.isArray(value) ? value : [value];
    return `<div class="build-readonly-note"><strong>${esc(heading)}</strong>${lines.map(line =>
      `<span>${esc(String(line || ""))}</span>`
    ).join("")}</div>`;
  }).join("");
}

function _ptReadOnlyPartDetails(part) {
  const details = [];
  const colors = [part.raw_color, part.lens, part.driver_color, part.passenger_color, part.center_color]
    .map(value => String(value || "").trim()).filter(Boolean);
  if (part.manufacturer) details.push(String(part.manufacturer));
  if (colors.length) details.push(colors.join(" / "));
  return details.join(" · ");
}

window.PT_openReadOnlyBuild = async function (draftId, label, finalStatus = "draft") {
  const modal = $("build-readonly-modal");
  const body = $("build-readonly-body");
  if (!_PT._readOnlyBuildWired) {
    _PT._readOnlyBuildWired = true;
    $("build-readonly-close")?.addEventListener("click", _ptCloseReadOnlyBuildModal);
    $("build-readonly-done")?.addEventListener("click", _ptCloseReadOnlyBuildModal);
    modal?.addEventListener("click", event => {
      if (event.target === modal) _ptCloseReadOnlyBuildModal();
    });
  }
  if ($("build-readonly-title")) $("build-readonly-title").textContent = label || "Build details";
  if (body) body.innerHTML = `<p class="build-readonly-loading">Loading build details…</p>`;
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");

  try {
    const response = draftId ? await api(`/api/draft/${encodeURIComponent(draftId)}`) : {ok:true,draft:{parts:[],notes:{}}};
    if (!response?.ok || !response.draft) throw new Error(response?.error || "Build details are unavailable");
    const draft = response.draft;
    const parts = Array.isArray(draft.parts) ? draft.parts : [];
    const included = parts.filter(part => part.include !== false);
    const excluded = parts.filter(part => part.include === false);
    const rows = parts.map(part => {
      const supply = [part.new_or_used, part.source].map(value => String(value || "").trim()).filter(Boolean).join(" · ");
      return `<tr class="${part.include === false ? "build-readonly-part--excluded" : ""}">
        <td>${esc(String(part.quantity ?? ""))}</td>
        <td><strong>${esc(part.name || "Unnamed part")}</strong><small>${esc(_ptReadOnlyPartDetails(part))}</small></td>
        <td>${esc(part.part_number || "—")}</td>
        <td>${esc(part.location || "—")}</td>
        <td>${esc(supply || "—")}</td>
        <td>${esc(part.notes || "")}</td>
      </tr>`;
    }).join("");
    if (body) body.innerHTML = `
      <div class="build-readonly-summary">
        <span>${esc(finalStatus === "finalized" ? "Finalized design" : "Draft design")}</span>
        <strong>${included.length} included part${included.length === 1 ? "" : "s"}</strong>
        ${excluded.length ? `<small>${excluded.length} excluded</small>` : ""}
      </div>
      <section class="build-readonly-section">
        <h3>Equipment</h3>
        ${parts.length ? `<div class="build-readonly-table-wrap"><table class="build-readonly-table">
          <thead><tr><th>Qty</th><th>Part</th><th>Part #</th><th>Location</th><th>Supply</th><th>Notes</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>` : `<p class="build-readonly-empty">No equipment has been added.</p>`}
      </section>
      <section class="build-readonly-section"><h3>Build notes</h3>${_ptReadOnlyBuildNotes(draft.notes)}</section>`;
  } catch (error) {
    if (body) body.innerHTML = `<p class="build-readonly-error">${esc(error.message || "Build details are unavailable")}</p>`;
  }
};

function _ptBindBuildCardOpeners(container) {
  _ptBindUnitNoteCards(container);
  container.querySelectorAll(".proj-build-card--openable").forEach(card => {
    card.addEventListener("click", event => {
      if (event.target.closest("button, a, details, summary, input, select, textarea, [data-unit-notes-card]")) return;
      _ptOpenBuildCard(card);
    });
    card.addEventListener("keydown", event => {
      if (event.target !== card || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      _ptOpenBuildCard(card);
    });
  });
}

function _ptFinalizationUrl(projectId, unitId, individualId, action) {
  const individual = individualId ? `/individual/${encodeURIComponent(individualId)}` : "";
  return `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(unitId)}${individual}/finalization/${action}`;
}

function _ptShopRepublishUrl(target) {
  return `/api/project/${encodeURIComponent(target.project_id)}/unit/${encodeURIComponent(target.unit_id)}/individual/${encodeURIComponent(target.individual_id)}/shop-publication/republish`;
}

async function _ptOfferShopRepublish(targets, statusEl) {
  const pending = (Array.isArray(targets) ? targets : [targets]).filter(target =>
    target?.required && target.project_id && target.unit_id && target.individual_id
  );
  if (!pending.length) return { accepted: false, updated: 0, failed: 0 };
  const plural = pending.length !== 1;
  const accepted = confirm(
    plural
      ? `${pending.length} finalized designs already have PDFs in Shop Documents.\n\nReplace them with these new exports?`
      : "This finalized design already has a PDF in Shop Documents.\n\nReplace it with this new export?"
  );
  if (!accepted) return { accepted: false, updated: 0, failed: 0 };

  if (statusEl) _ptSetStatus(
    statusEl,
    plural ? "Updating Shop PDFs…" : "Updating Shop PDF…",
    "loading",
  );
  let updated = 0;
  let failed = 0;
  for (const target of pending) {
    try {
      const result = await api(_ptShopRepublishUrl(target), {});
      if (result?.ok) updated += 1;
      else failed += 1;
    } catch (_) {
      failed += 1;
    }
  }
  if (updated) toast(
    plural ? `${updated} Shop PDF${updated === 1 ? "" : "s"} updated` : "Shop PDF updated",
    failed ? "error" : "success",
  );
  if (failed) toast(
    `${failed} Shop PDF${failed === 1 ? "" : "s"} could not be updated`,
    "error",
  );
  return { accepted: true, updated, failed };
}

function _ptCloseFinalizationModal() {
  const modal = $("build-finalization-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
}

function _ptOpenFinalizationModal(title, bodyHtml, saveLabel, onSave) {
  const modal = $("build-finalization-modal");
  const titleEl = $("build-finalization-title");
  const body = $("build-finalization-body");
  const save = $("build-finalization-save");
  if (!_PT._finalizationWired) {
    _PT._finalizationWired = true;
    $("build-finalization-close")?.addEventListener("click", _ptCloseFinalizationModal);
    $("build-finalization-cancel")?.addEventListener("click", _ptCloseFinalizationModal);
    modal?.addEventListener("click", event => { if (event.target === modal) _ptCloseFinalizationModal(); });
  }
  if (titleEl) titleEl.textContent = title;
  if (body) body.innerHTML = bodyHtml;
  if (save) {
    save.style.display = saveLabel ? "" : "none";
    save.textContent = saveLabel || "";
    save.disabled = false;
    save.onclick = onSave || null;
  }
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");
}

function _ptShowFinalizationError(message, invalidFields = []) {
  const body = $("build-finalization-body");
  if (!body) return;
  let alert = body.querySelector(".build-finalization-error");
  if (!alert) {
    alert = document.createElement("div");
    alert.className = "build-finalization-error";
    alert.setAttribute("role", "alert");
    body.prepend(alert);
  }
  alert.textContent = message;
  body.querySelectorAll("[data-final-warning]").forEach(textarea => {
    const invalid = invalidFields.includes(textarea);
    textarea.classList.toggle("is-invalid", invalid);
    textarea.setAttribute("aria-invalid", invalid ? "true" : "false");
  });
  invalidFields[0]?.focus();
}

function _ptFinalizationChecksHtml(checks) {
  const items = Array.isArray(checks) ? checks : [];
  if (!items.length) return "";
  const passed = items.filter(item => item.status === "passed").length;
  const applicable = items.filter(item=>item.status!=="not_applicable").length;
  const allPassed = passed === applicable;
  const rows = items.map(item => {
    const status = ["passed", "warning", "blocked", "not_applicable"].includes(item.status) ? item.status : "warning";
    const mark = status === "not_applicable" ? "—" : status === "passed" ? "✓" : "!";
    return `<div class="build-final-check build-final-check--${status}"><span class="build-final-check-mark" aria-hidden="true">${mark}</span><span><strong>${esc(item.title || "Final check")}</strong><small>${esc(item.message || "")}</small></span></div>`;
  }).join("");
  return `<details class="build-final-checks${allPassed ? " build-final-checks--clear" : ""}"><summary><span class="build-final-check-summary-mark" aria-hidden="true">${allPassed ? "✓" : "!"}</span><span><strong>${passed} of ${applicable}${applicable<items.length?" applicable":""} final checks passed</strong><small>Show checks run</small></span><span class="build-final-check-chevron" aria-hidden="true">⌄</span></summary><div class="build-final-check-list">${rows}</div></details>`;
}

async function _ptOpenBuildAfterReopen(projectId, unitId, individualId, type) {
  await _ptLoadAll();
  const project = _PT.projects.find(item => item.project_id === projectId);
  const unit = (project?.build_units || []).find(item => item.unit_id === unitId);
  if (!project || !unit) return;
  if (type === "ind") {
    const individual = (unit.individuals || []).find(item => item.individual_id === individualId);
    if (individual?.draft_id) await _ptShowBuildEditor(individual.draft_id, unit, project, "overview", individual);
  } else if (unit.draft_id) {
    await _ptShowBuildEditor(unit.draft_id, unit, project, "overview");
  }
}

window.PT_reviewFinalization = async function (projectId, unitId, individualId, type, openAfterReopen = false) {
  let check;
  try {
    check = await api(_ptFinalizationUrl(projectId, unitId, individualId, "check"));
  } catch (error) {
    toast(error.message || "Could not run final checks", "error");
    return;
  }
  if (!check?.ok) { toast(check?.error || "Could not run final checks", "error"); return; }

  if (check.status === "finalized") {
    const finalizedBy = check.finalized_by ? ` by ${esc(check.finalized_by)}` : "";
    const finalizedAt = check.finalized_at ? new Date(check.finalized_at).toLocaleString() : "";
    const canEdit = _ptCanEditProjects();
    const reopen = canEdit ? `<label class="build-reopen-reason"><span>Reason for reopening</span><textarea id="build-reopen-reason" rows="3" placeholder="What needs to change?"></textarea></label>` : "";
    _ptOpenFinalizationModal("Design finalized", `<section class="build-final-summary"><div class="build-final-seal">✓</div><div><h3>Design sign-off complete</h3><p>Signed off${finalizedBy}${finalizedAt ? ` on ${esc(finalizedAt)}` : ""}. The design is locked against accidental edits.</p></div></section>${_ptFinalizationChecksHtml(check.checks)}${reopen}`, canEdit ? "Reopen for changes" : "", async () => {
      const reason = $("build-reopen-reason")?.value.trim() || "";
      if (reason.length < 3) { toast("Enter a brief reason for reopening", "error"); return; }
      const result = await api(_ptFinalizationUrl(projectId, unitId, individualId, "reopen"), { reason });
      if (!result?.ok) { toast(result?.error || "Could not reopen build", "error"); return; }
      _ptCloseFinalizationModal();
      toast("Design reopened for changes", "success");
      if (openAfterReopen) await _ptOpenBuildAfterReopen(projectId, unitId, individualId, type);
      else {
        await _ptLoadAll();
        const updated = _PT.projects.find(item => item.project_id === projectId);
        if (updated) { _PT.viewProject = updated; _ptRenderOverview(updated); }
      }
    });
    return;
  }

  if (!_ptCanEditProjects()) {
    toast("This design has not been finalized yet", "info");
    return;
  }

  if ((check.blocking || []).length) {
    const blockingHtml = check.blocking.map(item => `<div class="build-final-block"><strong>PDF required</strong><span>${esc(item.message)}</span></div>`).join("");
    _ptOpenFinalizationModal("Finalize design", `<div class="build-final-intro"><span class="build-final-step">1</span><div><h3>Export the final PDF</h3><p>The signed-off PDF must match the current design.</p></div></div>${blockingHtml}${_ptFinalizationChecksHtml(check.checks)}`, "Export PDF now", async () => {
      const exported = await PT_buildExportPdf(projectId, unitId, individualId, type, { openAfter: false });
      if (exported) {
        _ptCloseFinalizationModal();
        await PT_reviewFinalization(projectId, unitId, individualId, type);
      }
    });
    return;
  }

  const warnings = check.warnings || [];
  const warningHtml = warnings.length
    ? warnings.map(warning => `<label class="build-final-warning"><span><strong>${esc(warning.title)}</strong><small>${esc(warning.message)}</small></span><textarea data-final-warning="${esc(warning.id)}" rows="2" placeholder="Acknowledge why this is correct for this build…"></textarea></label>`).join("")
    : `<div class="build-final-clear"><strong>✓ Equipment checks clear</strong><span>No review warnings were found.</span></div>`;
  _ptOpenFinalizationModal("Finalize design", `<div class="build-final-intro"><span class="build-final-step">2</span><div><h3>Review and lock this design</h3><p>The PDF is current. Resolve each warning with a short note, then finalize the design.</p></div></div>${warningHtml}${_ptFinalizationChecksHtml(check.checks)}<div class="build-final-lock-note">Finalizing records the signed-in user and time, then locks design edits until someone reopens it with a reason.</div>`, "Finalize design", async () => {
    const fields = [...document.querySelectorAll("[data-final-warning]")];
    const invalidFields = fields.filter(textarea => textarea.value.trim().length < 3);
    const acknowledgements = fields.map(textarea => ({ id: textarea.dataset.finalWarning, note: textarea.value.trim() }));
    if (invalidFields.length) {
      const message = "Add a short acknowledgement for every warning before finalizing.";
      _ptShowFinalizationError(message, invalidFields);
      toast(message, "error");
      return;
    }
    const save = $("build-finalization-save");
    if (save) save.disabled = true;
    try {
      const result = await api(_ptFinalizationUrl(projectId, unitId, individualId, "finalize"), { fingerprint: check.fingerprint, acknowledgements });
      if (!result?.ok) {
        const message = result?.message || result?.error || "Could not finalize design";
        _ptShowFinalizationError(message);
        toast(message, "error");
        return;
      }
      _ptCloseFinalizationModal();
      toast("Design finalized and locked", "success");
      await _ptLoadAll();
      const updated = _PT.projects.find(item => item.project_id === projectId);
      if (updated) { _PT.viewProject = updated; _ptRenderOverview(updated); }
    } catch (error) {
      const message = error?.message || "Could not finalize design";
      _ptShowFinalizationError(message);
      toast(message, "error");
    } finally {
      if (save && $("build-finalization-modal")?.classList.contains("open")) save.disabled = false;
    }
  });
};

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
  if (!_ptCanEditProjects()) return;
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;

  if (existingDraftId) {
    await _ptShowBuildEditor(existingDraftId, unit, project, "overview");
  } else {
    const statusEl = $("proj-action-status");
    if (statusEl) _ptSetStatus(statusEl, "Setting up build…", "loading");
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
  if (!_ptCanEditProjects()) return;
  const project = _PT.projects.find(p => p.project_id === projectId);
  if (!project) return;
  const unit = project.build_units[unitIndex];
  if (!unit) return;
  const individual = (unit.individuals || []).find(i => i.individual_id === individualId);

  if (existingDraftId) {
    await _ptShowBuildEditor(existingDraftId, unit, project, "overview", individual);
  } else {
    const statusEl = $("proj-action-status");
    if (statusEl) _ptSetStatus(statusEl, "Setting up build…", "loading");
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
// Preview/Edit, Export PDF, View PDF, and Open PDF folder all go through here.
// The "Generate" button is gone — both Preview and Export auto-regenerate
// when the source has changed since the last render. Manual PowerPoint
// edits are detected and the user is asked whether to keep them.

function _ptResolveBuildContext(projectId, unitId, individualId, type) {
  const project = _PT.projects.find(p => p.project_id === projectId) || _PT.viewProject;
  if (!project) return null;
  const unit = (project.build_units || []).find(u => u.unit_id === unitId);
  if (!unit) return null;
  let draftId = "", outputPath = "", pdfPath = "", lastRenderedAt = "", shopPdfPath = "";
  let holder = unit;
  if (type === "ind") {
    const ind = (unit.individuals || []).find(i => i.individual_id === individualId);
    if (!ind) return null;
    holder = ind;
    draftId = ind.draft_id || "";
    outputPath = ind.output_path || "";
    pdfPath = ind.pdf_path || "";
    lastRenderedAt = ind.last_rendered_at || "";
    shopPdfPath = ind.shop_pdf_path || "";
  } else {
    draftId = unit.draft_id || "";
    outputPath = unit.output_path || "";
    pdfPath = unit.pdf_path || "";
    lastRenderedAt = unit.last_rendered_at || "";
  }
  return { project, unit, holder, draftId, outputPath, pdfPath, lastRenderedAt, shopPdfPath };
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
  // PPTX files are workstation-local conversion sources. A shared project can
  // retain another computer's path, so regenerate locally instead of trying
  // the retired shared-PPTX download path.
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
  if (statusEl) _ptSetStatus(statusEl, "Preparing build sheet…", "loading");
  if (ctx._replacePreviousExports === undefined && (ctx.outputPath || ctx.pdfPath)) {
    ctx._replacePreviousExports = confirm(
      "This vehicle already has an exported build sheet.\n\n" +
      "OK (default) = Replace the prior PowerPoint and PDF\n" +
      "Cancel = Keep the prior files and create another version"
    );
  }
  const res = await api("/api/draft/generate", {
    draft_id: ctx.draftId,
    project_id: ctx.project.project_id,
    existing_output_path: ctx.outputPath,
    replace_previous_exports: ctx._replacePreviousExports === true,
    preserve_sharepoint_version: ctx._replacePreviousExports === false,
    previous_export_paths: [ctx.outputPath, ctx.pdfPath].filter(Boolean),
  });
  if (!res?.ok) {
    const msg = res?.error || "Generation failed";
    toast(msg, "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
    return null;
  }
  if (res.cleanup?.errors?.length) {
    toast("The new export was saved, but some prior files could not be removed", "error");
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
  if (statusEl) _ptSetStatus(statusEl, "Opening in PowerPoint…", "loading");
  try {
    const customer = ctx.project?.customer || {};
    const res = await api("/open", {
      path: target,
      agency: customer.agency || "",
      year: customer.build_year || "",
    });
    if (res?.ok) {
      if (statusEl) statusEl.style.display = "none";
    } else {
      toast(res?.error || "Could not open file", "error");
    }
  } catch (e) {
    toast(e.message || "Open failed", "error");
  }
};

window.PT_buildExportPdf = async function (projectId, unitId, individualId, type, options = {}) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return false;
  ctx.individualId = individualId || "";
  let statusEl = options.statusEl || $("proj-action-status");
  const plan = await _ptDecidePlan(ctx, statusEl);
  if (!plan) return false;
  let pptxPath = ctx.outputPath;
  if (plan === "open" && ctx.pdfPath) {
    ctx._replacePreviousExports = confirm(
      "This vehicle already has an exported PDF.\n\n" +
      "OK (default) = Replace the prior PDF\n" +
      "Cancel = Keep it and create another PowerPoint/PDF version"
    );
    if (!ctx._replacePreviousExports) {
      const result = await _ptGenerateAndPersist(ctx, statusEl);
      if (!result) return false;
      pptxPath = result;
    }
  }
  if (plan === "regen") {
    const result = await _ptGenerateAndPersist(ctx, statusEl);
    if (!result) return false;
    pptxPath = result;
  }
  // Generation reloads and re-renders the project, replacing the normal
  // status node. Rebind it before conversion so the visible spinner remains
  // active until the same completed response that triggers the success toast.
  statusEl = options.statusEl || $("proj-action-status");
  if (!pptxPath) { toast("No build sheet available", "error"); return false; }
  const customer = ctx.project?.customer || {};
  if (statusEl) _ptSetStatus(statusEl, "Exporting PDF…", "loading");
  try {
    const res = await api("/api/export/pdf", {
      output_path: pptxPath,
      agency: customer.agency || "",
      year: customer.build_year || "",
      project_id: ctx.project.project_id,
      unit_id: unitId,
      individual_id: individualId || "",
      replace_previous_exports: ctx._replacePreviousExports === true,
      preserve_sharepoint_version: ctx._replacePreviousExports === false && Boolean(ctx.outputPath || ctx.pdfPath),
      previous_export_paths: [ctx.outputPath, ctx.pdfPath].filter(Boolean),
    });
    if (!res?.ok) {
      const msg = res?.error || "Export failed";
      toast(msg, "error");
      if (statusEl) _ptSetStatus(statusEl, "❌ " + msg, "err");
      return false;
    }
    toast("PDF exported", "success");
    if (res.cleanup?.errors?.length) {
      toast("PDF saved, but some prior files could not be removed", "error");
    }
    const shopUpdate = await _ptOfferShopRepublish(res.shop_republish, statusEl);
    // Backend stamped pdf_path + last_exported_at/by on the project
    // record itself, so just reload to refresh the UI.
    await _ptLoadAll();
    const updated = _PT.projects.find(p => p.project_id === ctx.project.project_id);
    if (updated) {
      _PT.viewProject = updated;
      _ptRenderBuildsTab(updated);
    }
    statusEl = options.statusEl || $("proj-action-status");
    if (statusEl) _ptSetStatus(
      statusEl,
      shopUpdate.updated ? "✅ PDF exported · Shop PDF updated" : "✅ PDF exported",
      shopUpdate.failed ? "err" : "good",
    );
    // Ordinary exports open for review. Estimate preparation stays in the
    // modal and attaches the file immediately afterward.
    if (options.openAfter !== false) {
      try { await api("/open", { path: res.pdf_path }); } catch (_) {}
    }
    return true;
  } catch (e) {
    toast(e.message || "Export failed", "error");
    if (statusEl) _ptSetStatus(statusEl, "❌ " + (e.message || "Error"), "err");
    return false;
  }
};

window.PT_buildOpenPdf = async function (projectId, unitId, individualId, type) {
  const ctx = _ptResolveBuildContext(projectId, unitId, individualId, type);
  if (!ctx) return;
  if (!ctx.pdfPath) { toast("Export the PDF first", "error"); return; }
  try {
    const customer = ctx.project?.customer || {};
    const res = await api("/open", {
      path: ctx.pdfPath,
      agency: customer.agency || "",
      year: customer.build_year || "",
      project_id: projectId,
      unit_id: unitId,
      individual_id: individualId || "",
    });
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
      shop_pdf_path: ctx.shopPdfPath || "",
    });
    if (!res?.ok) toast(res?.error || "Could not open folder", "error");
  } catch (e) {
    toast(e.message || "Open failed", "error");
  }
};

window.PT_openCloudFolder = async function (source, explicitTarget = "", explicitPath = "") {
  const libraryTarget = explicitTarget || source?.dataset?.libraryTarget || "";
  const folderPath = explicitPath || source?.dataset?.folderPath || "";
  if (!libraryTarget || !folderPath) {
    toast("This folder has not been created yet", "error");
    return;
  }
  try {
    const res = await api("/api/build/show-folder", {
      library_target: libraryTarget,
      folder_path: folderPath,
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
      `Generating ${i + 1}/${configuredItems.length}: ${item.label}…`, "loading");

    const draftId = item.type === "ind" ? item.ind.draft_id : item.unit.draft_id;
    try {
      const res = await api("/api/draft/generate", { draft_id: draftId, project_id: project.project_id });
      if (res.ok) {
        generated++;
        // Persist output_path back to project
        const currentProject = _PT.projects.find(p => p.project_id === project.project_id) || project;
        const outputPath   = res.output_path || "";
        const updatedUnits = currentProject.build_units.map(u => {
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
        const saveResult = await api("/api/project/save", {
          project_id: project.project_id,
          expected_updated_at: currentProject.updated_at,
          expected_record_revision: currentProject.record_revision,
          build_units: updatedUnits,
        });
        if (!saveResult?.ok) throw new Error(saveResult?.error || "Project changed before output could be recorded");
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
    (u.individuals || []).some(ind => !ind.unit_number?.trim() && !ind.vin?.trim())
  );
  if (missingNum) {
    toast("Some units are missing both a unit number and VIN. Add one identifier via Details / Setup Build before exporting.", "error");
    return;
  }

  const statusEl = $("proj-action-status");
  const allBtns  = document.querySelectorAll(".proj-builds-footer .btn");
  allBtns.forEach(b => b.disabled = true);
  if (statusEl) _ptSetStatus(statusEl, "Generating and exporting PDFs…", "loading");
  try {
    const res = await api(`/api/project/${encodeURIComponent(_PT.viewProject.project_id)}/export-all-pdf`, {});
    if (res.ok) {
      const n = (res.exported || []).length;
      const e = (res.errors  || []).length;
      const shopUpdate = await _ptOfferShopRepublish(
        (res.exported || []).map(item => item.shop_republish).filter(Boolean),
        statusEl,
      );
      toast(`${n} PDF${n !== 1 ? "s" : ""} exported`, e ? "error" : "success");
      if (statusEl) _ptSetStatus(
        statusEl,
        `✅ ${n} exported${shopUpdate.updated ? ` · ${shopUpdate.updated} Shop updated` : ""}${e ? ` · ${e} error${e !== 1 ? "s" : ""}` : ""}`,
        e || shopUpdate.failed ? "err" : "good",
      );
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
  if (statusEl) _ptSetStatus(statusEl, "Creating draft…", "loading");
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
  if (statusEl) _ptSetStatus(statusEl, "Creating draft…", "loading");
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
  labor_amount_required: "Enter an installation labor amount below",
  install_supplies_amount_required: "Enter an install supplies amount below",
  additional_charge_item_missing: "Required Additional charges item is missing or inactive in QuickBooks",
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
    project_identity_required: "Enter a unit number or accept the automatic build name before setting up the QuickBooks Project",
    invalid_project_id: "Paste the QuickBooks Project web address or project number",
    invalid_qb_project_ref: "QuickBooks rejected the saved Project link — set it up again below",
    validation_failed: "Some parts aren't linked to QuickBooks",
    validation_unavailable: "Could not check this vehicle right now",
    pricing_refresh_failed: "Could not refresh current QuickBooks Item prices — the estimate was not created",
    invalid_pricing: "Custom pricing must use discounts from 0% through 100%",
    estimate_number_unavailable: "QuickBooks could not determine the next estimate number — no estimate was created",
    project_tax_sync_failed: "QuickBooks could not apply this agency's tax status to the vehicle Project",
    retail_customer_type_not_found: "QuickBooks does not have an active Retail customer type",
    duplicate_estimate_confirmation_required: "Choose whether to update the existing estimate or create a new one",
    invalid_estimate_id: "Enter a numeric Estimate ID or paste a QuickBooks Estimate page address",
    estimate_already_linked_elsewhere: "That Estimate is already connected to another project or vehicle",
    estimate_not_linked: "That Estimate is not connected to this project",
    existing_estimate_modified: "QuickBooks changed this estimate after Vehicle Builder last wrote it",
    existing_estimate_change_unverified: "Vehicle Builder could not verify the saved QuickBooks estimate against a prior baseline",
    existing_estimate_not_found: "The saved QuickBooks estimate no longer exists — choose Create new estimate",
    build_pdf_missing: "Export the build PDF before attaching it to QuickBooks",
    build_pdf_shared_unavailable: "The shared build PDF could not be downloaded from Microsoft 365",
    build_pdf_invalid: "The selected build attachment is not a valid PDF",
    build_pdf_outside_output: "The build PDF is outside the app's approved output folder",
    attachment_file_unreadable: "The build PDF could not be read",
    attachment_upload_failed: "QuickBooks rejected the build PDF attachment",
    quickbooks_rejected_estimate: "QuickBooks rejected the estimate",
    estimate_request_failed: "The app could not complete the QuickBooks estimate request",
  };
  return m[code] || ("Estimate failed: " + (code || "unknown error"));
}

function _ptEstimateFailureText(res) {
  const base = _ptEstError(res?.error);
  const detail = String(res?.detail || "").trim();
  const reference = String(res?.reference || "").trim();
  return `${base}${detail ? ": " + detail : ""}${reference ? " (reference " + reference + ")" : ""}`;
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
      : "enter a unit number or accept its automatic build name, then link the vehicle to its QuickBooks Project");
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

function _ptEscAttr(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _ptEstimatePricingSummary(pricing) {
  const p = pricing || {};
  if (!p.rule_name) return "";
  const applied = (p.applied_discounts || []).map((row) =>
    `${esc(row.manufacturer)} ${Number(row.discount_percent).toFixed(1).replace(/\.0$/, "")}%${row.override ? " (customer)" : ""}`
  ).join(" · ");
  const source = p.source === "custom" ? "Custom" : "Retail";
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

function _ptEstimatePricingControls(pricing) {
  const rows = pricing?.editable_discounts || [];
  const inputs = rows.map((row) => `<label class="qb-pricing-row">
    <span>${esc(row.manufacturer)}</span>
    <input type="number" min="0" max="100" step="0.1"
      value="${_ptEscAttr(row.custom_discount_percent)}"
      data-qb-est-custom-price="${_ptEscAttr(row.manufacturer_id)}" />
    <span class="qb-pricing-percent">% off</span>
  </label>`).join("");
  return `<div class="qb-est-bank-note" style="margin-bottom:14px">
    <strong>Customer pricing</strong><br>
    <label><input type="radio" name="qb-est-pricing-mode" value="retail" checked> Retail pricing</label><br>
    <label><input type="radio" name="qb-est-pricing-mode" value="custom"> Custom pricing for this estimate</label>
    <div id="qb-est-custom-pricing" class="qb-pricing-grid" hidden style="margin-top:10px">${inputs}</div>
  </div>`;
}

function _ptReadEstimatePricing() {
  const mode = document.querySelector('input[name="qb-est-pricing-mode"]:checked')?.value || "retail";
  const custom = {};
  for (const input of document.querySelectorAll("[data-qb-est-custom-price]")) {
    custom[input.getAttribute("data-qb-est-custom-price")] = Number(input.value);
  }
  return { mode, custom };
}

function _ptAdditionalChargesHtml(charges) {
  const c = charges || {};
  if (!c.enabled) return "";
  const options = Object.entries(c.presets || {}).map(([id, preset]) =>
    `<option value="${_ptEscAttr(id)}"${id === c.preset_id ? " selected" : ""}>${esc(preset.label || id)}</option>`
  ).join("");
  const deliveryEnabled = Number(c.delivery_amount || 0) > 0;
  return `<section class="qb-est-additional" aria-labelledby="qb-est-additional-title">
    <div class="qb-est-additional-heading">
      <div><strong id="qb-est-additional-title">Additional charges</strong><span>Confirm these before exporting to QuickBooks.</span></div>
      <label>Build preset<select id="qb-est-charge-preset">${options}</select></label>
    </div>
    <div class="qb-est-charge-grid">
      <label><span>Installation labor</span><input id="qb-est-labor-amount" type="number" min="0" step="0.01" value="${_ptEscAttr(c.labor_amount)}"><small>QB item: ${esc(c.service_items?.labor || "LABOR INSTALL")}</small></label>
      <label><span>DTM install supplies</span><input id="qb-est-supplies-amount" type="number" min="0" step="0.01" value="${_ptEscAttr(c.install_supplies_amount)}"><small>QB item: ${esc(c.service_items?.install_supplies || "INSTALL SUPPLIES")}</small></label>
      <label class="qb-est-delivery-toggle"><span><input id="qb-est-delivery-enabled" type="checkbox"${deliveryEnabled ? " checked" : ""}> Add delivery fee</span><input id="qb-est-delivery-amount" type="number" min="0" step="0.01" value="${_ptEscAttr(c.delivery_amount || 0)}"${deliveryEnabled ? "" : " hidden"}><small>QB item: ${esc(c.service_items?.delivery || "TRAVEL")}</small></label>
      <div class="qb-est-auto-fee"><span>${Number(c.card_fee_percent || 4).toFixed(2).replace(/\.00$/, "")}% credit card fee</span><strong id="qb-est-card-fee-amount">${_ptMoney2(c.card_fee_amount)}</strong><small>Calculated from parts and all charges; never compounded.</small></div>
    </div>
    <div class="qb-est-charge-totals"><span>Materials <strong id="qb-est-materials-total">${_ptMoney2(c.materials_total)}</strong></span><span>Additional charges <strong id="qb-est-additional-total">${_ptMoney2(c.additional_total)}</strong></span></div>
  </section>`;
}

function _ptReadAdditionalCharges() {
  const preset = $("qb-est-charge-preset");
  if (!preset) return null;
  return {
    preset_id: preset.value,
    labor_amount: Number($("qb-est-labor-amount")?.value || 0),
    install_supplies_amount: Number($("qb-est-supplies-amount")?.value || 0),
    delivery_amount: $("qb-est-delivery-enabled")?.checked
      ? Number($("qb-est-delivery-amount")?.value || 0) : 0,
  };
}

function _ptWireEstimatePricing(pricing, charges, materialLineCount = 0) {
  const moneyRound = value => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
  const update = () => {
    const chosen = _ptReadEstimatePricing();
    const customBox = $("qb-est-custom-pricing");
    if (customBox) customBox.hidden = chosen.mode !== "custom";
    let total = 0;
    for (const line of (pricing?.pricing_basis || [])) {
      const list = Number(line.list_unit_price || 0);
      const qty = Number(line.qty || 1);
      const retail = (pricing?.editable_discounts || []).find(
        row => row.manufacturer_id === line.manufacturer_id)?.retail_discount_percent || 0;
      const discount = line.discountable
        ? (chosen.mode === "custom" ? Number(chosen.custom[line.manufacturer_id] ?? retail) : Number(retail))
        : 0;
      total += Math.round((list * (1 - discount / 100) + Number.EPSILON) * 100) / 100 * qty;
    }
    const materialsTotal = moneyRound(total);
    const chosenCharges = _ptReadAdditionalCharges();
    const labor = moneyRound(chosenCharges?.labor_amount || 0);
    const supplies = moneyRound(chosenCharges?.install_supplies_amount || 0);
    const delivery = moneyRound(chosenCharges?.delivery_amount || 0);
    const feePercent = Number(charges?.card_fee_percent || 4);
    const fee = moneyRound((materialsTotal + labor + supplies + delivery) * feePercent / 100);
    const additional = moneyRound(labor + supplies + delivery + fee);
    const estimate = moneyRound(materialsTotal + additional);
    if ($("qb-est-materials-total")) $("qb-est-materials-total").textContent = _ptMoney2(materialsTotal);
    if ($("qb-est-card-fee-amount")) $("qb-est-card-fee-amount").textContent = _ptMoney2(fee);
    if ($("qb-est-additional-total")) $("qb-est-additional-total").textContent = _ptMoney2(additional);
    if ($("qb-est-estimated-total")) $("qb-est-estimated-total").textContent = _ptMoney2(estimate);
    if ($("qb-est-line-count")) {
      const chargeLines = (labor > 0 ? 1 : 0) + (supplies > 0 ? 1 : 0)
        + (delivery > 0 ? 1 : 0) + (fee > 0 ? 1 : 0);
      $("qb-est-line-count").textContent = String(Number(materialLineCount || 0) + chargeLines);
    }
  };
  document.querySelectorAll('input[name="qb-est-pricing-mode"], [data-qb-est-custom-price], #qb-est-labor-amount, #qb-est-supplies-amount, #qb-est-delivery-amount').forEach(
    input => input.addEventListener("input", update)
  );
  $("qb-est-delivery-enabled")?.addEventListener("change", event => {
    const amount = $("qb-est-delivery-amount");
    if (amount) amount.hidden = !event.currentTarget.checked;
    update();
  });
  $("qb-est-charge-preset")?.addEventListener("change", event => {
    const preset = charges?.presets?.[event.currentTarget.value] || {};
    if ($("qb-est-labor-amount")) $("qb-est-labor-amount").value = Number(preset.labor_amount || 0).toFixed(2);
    if ($("qb-est-supplies-amount")) $("qb-est-supplies-amount").value = Number(preset.install_supplies_amount || 0).toFixed(2);
    update();
  });
  update();
}

function _ptBankTransferEstimateNote() {
  return `<div class="qb-est-bank-note"><strong>QuickBooks follow-up:</strong> After creating this estimate, open <strong>Discounts and fees</strong> in QuickBooks and turn on <strong>Bank transfer — 1% per transaction, max $20</strong>. QuickBooks does not expose this Estimate-form switch through the Accounting API, so Vehicle Builder cannot set or verify it automatically.</div>`;
}

function _ptEstimateChangeHtml(estimateId, change) {
  const status = change?.status || "untracked";
  const modified = status === "modified";
  const unavailable = ["untracked", "check_failed"].includes(status);
  const missing = status === "missing";
  // Updating is always an explicit choice, even when the last-known snapshot
  // still matches. Connecting an Estimate is a separate read-only action.
  const needsChoice = true;
  const differences = change?.differences || [];
  const diffRows = differences.map(item => `<div class="qb-est-diff-row"><strong>${esc(item.field || "Change")}</strong><span><small>Vehicle Builder last wrote</small>${esc(item.before || "—")}</span><span><small>QuickBooks now has</small>${esc(item.after || "—")}</span></div>`).join("");
  let alert = "";
  if (modified) {
    alert = `<div class="qb-est-change-alert qb-est-change-alert--danger" role="alert"><strong>⚠ QuickBooks estimate ${esc(estimateId)} was changed outside Vehicle Builder</strong><p>Nothing will be overwritten until you choose what to do.</p>${differences.length ? `<details><summary>View ${differences.length} difference${differences.length === 1 ? "" : "s"}</summary><div class="qb-est-diff-list">${diffRows}</div></details>` : ""}</div>`;
  } else if (unavailable) {
    alert = `<div class="qb-est-change-alert" role="alert"><strong>⚠ QuickBooks change history is unavailable</strong><p>${esc(change?.message || "The app could not verify whether this existing estimate was edited in QuickBooks.")}</p></div>`;
  } else if (missing) {
    alert = `<div class="qb-est-change-alert qb-est-change-alert--danger" role="alert"><strong>⚠ The linked QuickBooks estimate was not found</strong><p>Create a separate new estimate; the saved link will be replaced only after creation succeeds.</p></div>`;
  }
  return `<div class="qb-est-existing-choice${modified ? " qb-est-change-conflict" : ""}" data-needs-choice="true" data-modified="${modified ? "true" : "false"}">${alert}<div class="qb-est-action-choices"><strong>Choose the QuickBooks write deliberately.</strong>${missing ? "" : `<label><input type="radio" name="qb-est-existing-action" value="update"> ${modified ? "Overwrite the QuickBooks changes and update this connected estimate" : unavailable ? "Update the connected estimate even though changes could not be verified" : `Update connected estimate ${esc(estimateId)}`}</label>`}<label><input type="radio" name="qb-est-existing-action" value="create_new"> Create a separate new estimate <small>(not recommended)</small></label></div></div>`;
}

function _ptWireEstimateChangeChoice(createButton) {
  const box = document.querySelector(".qb-est-existing-choice[data-needs-choice='true']");
  if (!box || !createButton) return;
  const refresh = () => {
    const action = document.querySelector('input[name="qb-est-existing-action"]:checked')?.value || "";
    createButton.disabled = !action;
    const modified = box.dataset.modified === "true";
    createButton.textContent = !action ? "Choose an action above"
      : action === "update"
        ? (modified ? "Overwrite QuickBooks changes" : "Update estimate in QuickBooks")
        : "Create separate estimate";
  };
  box.querySelectorAll('input[name="qb-est-existing-action"]').forEach(input => input.addEventListener("change", refresh));
  refresh();
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
    back:   $("qb-est-back"),
    cancel: $("qb-est-cancel"),
  };
}

function _ptOpenEstModal(title, bodyHtml, createLabel) {
  _PT.qbEstCloseHandler = null;
  _PT.qbEstCancelHandler = null;
  if (!_PT._qbEstWired) {
    _PT._qbEstWired = true;
    const close = (event) => {
      if (event?.currentTarget?.id === "qb-est-cancel"
          && typeof _PT.qbEstCancelHandler === "function") {
        _PT.qbEstCancelHandler();
        return;
      }
      if (typeof _PT.qbEstCloseHandler === "function") {
        _PT.qbEstCloseHandler();
        return;
      }
      $("qb-est-modal")?.classList.remove("open");
    };
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
  if (e.back) {
    e.back.style.display = "none";
    e.back.disabled = false;
    e.back.onclick = null;
    e.back.textContent = "Back";
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
  if (linked && missingFields.length) {
    return `<div style="padding:10px 12px;background:var(--surface-2);border-radius:6px;margin-top:8px;font-size:12px">
      <strong>QuickBooks customer needs: ${esc(missingFields.join(", "))}</strong><br>
      Update the customer in QuickBooks or use Settings → Agencies to review exact changes, then refresh this estimate.
    </div>`;
  }
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
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks tax status</label><select id="qb-est-customer-taxable" style="width:100%;box-sizing:border-box;margin-top:4px"><option value="false" ${c.taxable !== true ? "selected" : ""}>Tax exempt</option><option value="true" ${c.taxable === true ? "selected" : ""}>Taxable</option></select></div>
      <div style="flex:1"><label style="font-size:12px;font-weight:600;color:var(--navy)">Exemption reason</label><select id="qb-est-customer-tax-exemption-reason" style="width:100%;box-sizing:border-box;margin-top:4px" ${c.taxable === true ? "disabled" : ""}>
        <option value="1" ${c.tax_exemption_reason_id === "1" ? "selected" : ""}>Federal government</option>
        <option value="2" ${c.tax_exemption_reason_id === "2" ? "selected" : ""}>State government</option>
        <option value="3" ${!c.tax_exemption_reason_id || c.tax_exemption_reason_id === "3" ? "selected" : ""}>Local government</option>
        <option value="4" ${c.tax_exemption_reason_id === "4" ? "selected" : ""}>Tribal government</option>
        <option value="5" ${c.tax_exemption_reason_id === "5" ? "selected" : ""}>Charitable organization</option>
        <option value="6" ${c.tax_exemption_reason_id === "6" ? "selected" : ""}>Religious organization</option>
        <option value="7" ${c.tax_exemption_reason_id === "7" ? "selected" : ""}>Educational organization</option>
        <option value="8" ${c.tax_exemption_reason_id === "8" ? "selected" : ""}>Hospital</option>
        <option value="9" ${c.tax_exemption_reason_id === "9" ? "selected" : ""}>Resale</option>
        <option value="10" ${c.tax_exemption_reason_id === "10" ? "selected" : ""}>Direct pay permit</option>
        <option value="11" ${c.tax_exemption_reason_id === "11" ? "selected" : ""}>Multiple points of use</option>
        <option value="12" ${c.tax_exemption_reason_id === "12" ? "selected" : ""}>Direct mail</option>
        <option value="13" ${c.tax_exemption_reason_id === "13" ? "selected" : ""}>Agricultural production</option>
        <option value="14" ${c.tax_exemption_reason_id === "14" ? "selected" : ""}>Industrial production / manufacturing</option>
        <option value="15" ${c.tax_exemption_reason_id === "15" ? "selected" : ""}>Foreign diplomat</option>
      </select></div>
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
  fields.tax_exemption_reason_id = value("qb-est-customer-tax-exemption-reason") || "3";
  return fields;
}

function _ptWireCustomerTaxStatus() {
  const status = $("qb-est-customer-taxable");
  const reason = $("qb-est-customer-tax-exemption-reason");
  if (!status || !reason) return;
  const sync = () => { reason.disabled = status.value === "true"; };
  status.addEventListener("change", sync);
  sync();
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

function _ptOpenProjectBindingModal(
  projectId, individualId, binding, onLinked = null, validation = null, onBack = null,
  acceptAutoName = false
) {
  const b = binding || {};
  const projectName = b.project_name || "Vehicle project";
  const customerName = b.customer_name || "the correct customer";
  const identityReady = !!b.identity_ready;
  const alreadyLinked = !!b.ready;
  const saveLabel = alreadyLinked ? "Update project link" : "Save project link";
  const projectRefInvalid = !!b.project_ref_invalid;
  const identityHint = (b.identity_labels || []).length
    ? `This project is for ${esc((b.identity_labels || []).join(" · "))}.`
    : `No unit number is recorded yet. You can enter one, or use ${esc(b.auto_label || "the automatic build name")} for now.`;
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
       <input id="qb-project-id" class="qb-setup-input" autocomplete="off" placeholder="Paste the web address here" value="${_ptEscAttr(b.qb_project_id || "")}" />
       <p class="qb-setup-hint">If you have the project number instead, you can paste that too.</p>`
    : `<div class="qb-setup-first">
         <strong>Choose how to name this build.</strong>
         <ol class="qb-setup-steps">
           <li>Enter the vehicle's <strong>Unit number</strong> if it is known, or</li>
           <li>accept <strong>${esc(b.auto_label || "the automatic build name")}</strong> for now.</li>
         </ol>
         <div class="qb-setup-name-actions"><button type="button" class="btn btn-primary" id="qb-project-open-details">Enter unit number</button>
         <button type="button" class="btn btn-secondary" id="qb-project-use-auto-name">Use ${esc(b.auto_label || "automatic name")}</button></div>
         <p class="qb-setup-hint">The build stays linked by its internal vehicle ID. Adding a unit number later will not lose its files, draft, or Estimate association.</p>
       </div>`;

  _ptOpenEstModal(alreadyLinked ? "Manage the QuickBooks Project" : "Set up the QuickBooks Project",
    `<p class="qb-setup-intro">Do this once for this vehicle. It only connects the vehicle to the Project you create in QuickBooks; it does not create an estimate or send anything to the customer.</p>
     <p class="qb-setup-identity">${identityHint}</p>${rejectedRefNotice}${_ptProjectProblemNotice(validation)}${instructions}`,
    identityReady ? saveLabel : "");
  const e = _ptEstModalEls();
  if (onBack && e.back) {
    e.back.style.display = "";
    e.back.textContent = "← Back to vehicle checklist";
    e.back.onclick = async () => {
      e.back.disabled = true;
      e.back.textContent = "Checking…";
      try {
        await onBack();
      } catch (_) {
        toast("Could not refresh the vehicle checklist", "error");
        e.back.disabled = false;
        e.back.textContent = "← Back to vehicle checklist";
      }
    };
  }
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
  $("qb-project-use-auto-name")?.addEventListener("click", () => {
    _ptOpenProjectBindingModal(
      projectId,
      individualId,
      {
        ...b,
        identity_ready: true,
        identity_labels: [b.auto_label || "Automatic build name"],
        project_name: b.auto_project_name || b.project_name,
      },
      onLinked,
      validation,
      onBack,
      true,
    );
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
          accept_auto_name: acceptAutoName,
        });
        if (!res?.ok) {
          toast(_ptEstError(res?.error), "error");
          e.create.disabled = false;
          e.create.textContent = saveLabel;
          return;
        }
        e.modal?.classList.remove("open");
        toast("QuickBooks Project saved", "success");
        if (onLinked) await onLinked();
        else await window.PT_buildCreateEstimate(projectId, "", individualId);
      } catch (_) {
        toast("Could not link the QuickBooks Project", "error");
        e.create.disabled = false;
        e.create.textContent = saveLabel;
      }
    };
  }
}

window.PT_setupQbProject = async function (projectId, individualId) {
  if (!individualId) {
    toast("QuickBooks Projects are linked to individual units", "error");
    return;
  }
  let preview;
  try {
    preview = await api("/api/quickbooks/projects/preview", {
      project_id: projectId,
      individual_id: individualId,
    });
  } catch (_) {
    toast("Could not load the QuickBooks Project setup", "error");
    return;
  }
  if (!preview?.ok) {
    toast(_ptEstError(preview?.error), "error");
    return;
  }
  _ptOpenProjectBindingModal(projectId, individualId, preview.project, async () => {
    await _ptLoadAll();
    const updated = _PT.projects.find(project => project.project_id === projectId);
    if (updated) {
      _PT.viewProject = updated;
      _ptRenderOverview(updated);
    }
  });
};

window.PT_linkQbEstimate = function (projectId, individualId, onChanged = null) {
  const project = _PT.projects.find(item => item.project_id === projectId) || _PT.viewProject;
  let vehicle = null;
  for (const buildUnit of (project?.build_units || [])) {
    vehicle = (buildUnit.individuals || []).find(item => item.individual_id === individualId);
    if (vehicle) break;
  }
  if (!vehicle) {
    toast("Could not find this vehicle", "error");
    return;
  }
  const existingId = String(vehicle.qb_estimate_id || "").trim();
  const existingNumber = String(vehicle.qb_estimate_snapshot?.doc_number || existingId).trim();
  _ptOpenEstModal(
    existingId ? "Manage estimate connection" : "Connect an estimate",
    `<div class="qb-estimate-connector">
      ${existingId ? `<div class="qb-estimate-current"><div><span>Current connection</span><strong>Quote ${esc(existingNumber)}</strong></div><button type="button" id="qb-estimate-disconnect" class="btn btn-secondary btn-sm">Disconnect</button></div>` : ""}
      <label class="qb-estimate-search" for="qb-estimate-list-search">
        <span>Search QuickBooks estimates</span>
        <input id="qb-estimate-list-search" type="search" autocomplete="off" placeholder="Search by agency, quote number, vehicle, VIN, or memo">
        <small>Suggested estimates match this vehicle's agency and build year and are not connected elsewhere.</small>
      </label>
      <div id="qb-estimate-list-message" class="qb-estimate-list-message" role="status">Loading recent estimates…</div>
      <div id="qb-estimate-list" class="qb-estimate-list"></div>
    </div>`,
    "",
  );
  const controls = _ptEstModalEls();
  const searchInput = $("qb-estimate-list-search");
  const message = $("qb-estimate-list-message");
  const listHost = $("qb-estimate-list");
  const picker = { rows: [], next: 1, busy: false, complete: false };
  const searchTerms = () => String(searchInput?.value || "").trim().toLowerCase()
    .split(/\s+/).filter(Boolean);
  const resultContext = row => {
    const details = [];
    if (row.project_name) details.push(["Vehicle / project", row.project_name]);
    (row.vehicle_fields || []).forEach(field => details.push([field.label || "Vehicle", field.value]));
    if (row.customer_memo) details.push(["Memo", row.customer_memo]);
    if (row.private_note) details.push(["Internal note", row.private_note]);
    return details.length
      ? `<dl class="qb-estimate-result-context">${details.slice(0, 4).map(([label, value]) =>
          `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`
      : `<p class="qb-estimate-result-empty">No vehicle, VIN, or memo details are recorded on this estimate.</p>`;
  };
  const finish = async (result, messageText) => {
    controls.modal?.classList.remove("open");
    await _ptLoadAll();
    const updated = _PT.projects.find(item => item.project_id === projectId);
    if (updated) {
      _PT.viewProject = updated;
      _ptRenderOverview(updated);
    }
    toast(messageText, "success");
    if (typeof onChanged === "function") await onChanged(result);
  };
  let drawEstimates = () => {};
  const connect = async row => {
    if (row.linked_elsewhere || row.linked_here) return;
    const replacing = !!existingId && row.id !== existingId;
    if (replacing && !confirm(`Replace the connection to Quote ${existingNumber}?\n\nThis only changes which estimate this vehicle tracks. It will not edit either estimate in QuickBooks.`)) return;
    listHost.querySelectorAll("button").forEach(button => { button.disabled = true; });
    message.textContent = `Checking Quote ${row.number || row.id}…`;
    try {
      const result = await api("/api/quickbooks/estimates/bind", {
        project_id: projectId, individual_id: individualId,
        qb_estimate_id: row.id, replace_existing: replacing,
      });
      if (!result?.ok) {
        toast(result?.error === "existing_estimate_not_found"
          ? "That estimate was not found in the connected QuickBooks company"
          : result?.error === "estimate_already_linked_to_another_vehicle"
            ? "That estimate is already connected to another vehicle"
            : result?.error || "Estimate connection could not be saved", "error");
        drawEstimates();
        return;
      }
      if (result.operations_sync?.ok === false) {
        toast(result.operations_sync.error || "Estimate connected, but its shared status was not updated", "error");
      }
      const status = result.estimate_status ? ` · ${result.estimate_status}` : "";
      await finish(result, `Quote ${result.estimate_number || result.qb_estimate_id} connected${status}`);
    } catch (_) {
      toast("Estimate connection could not be saved", "error");
      drawEstimates();
    }
  };
  drawEstimates = () => {
    listHost.replaceChildren();
    const terms = searchTerms();
    const rows = picker.rows.filter(row => terms.every(term =>
      String(row.search_text || [row.customer, row.number, row.id, row.date, row.status,
        row.project_name, row.customer_memo, row.private_note].join(" ")).toLowerCase().includes(term)
    )).sort((a, b) =>
      Number(b.linked_here) - Number(a.linked_here)
      || Number(b.suggested) - Number(a.suggested)
      || Number(a.linked_elsewhere) - Number(b.linked_elsewhere)
      || String(b.date || "").localeCompare(String(a.date || ""))
    ).slice(0, 40);
    rows.forEach(row => {
      const card = document.createElement("article");
      card.className = `qb-estimate-result${row.suggested ? " qb-estimate-result--suggested" : ""}${row.linked_elsewhere ? " qb-estimate-result--unavailable" : ""}`;
      const connection = row.linked_here ? "Current connection" : row.linked_elsewhere ? "Connected elsewhere" : "";
      card.innerHTML = `<div class="qb-estimate-result-heading">
          <div><strong>Quote ${esc(row.number || row.id)}</strong><span>${esc(row.customer || "Customer not recorded")}</span></div>
          <div class="qb-estimate-result-badges">${row.suggested ? `<span class="qb-estimate-suggested">Suggested</span>` : ""}${connection ? `<span>${esc(connection)}</span>` : ""}</div>
        </div>
        <div class="qb-estimate-result-meta">${esc([row.date || "Undated", row.status || "Status unknown"].join(" · "))}</div>
        ${row.suggested_reason ? `<p class="qb-estimate-suggestion-reason">${esc(row.suggested_reason)}</p>` : ""}
        ${resultContext(row)}
        <div class="qb-estimate-result-action"><button type="button" class="btn ${row.linked_here ? "btn-secondary" : "btn-primary"} btn-sm"${row.linked_elsewhere || row.linked_here ? " disabled" : ""}>${row.linked_here ? "Connected" : row.linked_elsewhere ? "Unavailable" : existingId ? "Use this estimate" : "Connect estimate"}</button></div>`;
      card.querySelector("button").onclick = () => connect(row);
      listHost.append(card);
    });
    if (!rows.length && picker.complete) {
      listHost.innerHTML = `<div class="qb-estimate-list-empty">No estimates match that search.</div>`;
    }
    const suffix = picker.complete ? "" : " More recent estimates are still loading…";
    message.textContent = terms.length
      ? `${rows.length} matching estimate${rows.length === 1 ? "" : "s"}.${suffix}`
      : `${picker.rows.filter(row => row.suggested).length} suggested · ${picker.rows.length} recent estimates loaded.${suffix}`;
  };
  searchInput.oninput = drawEstimates;
  const loadEstimates = async () => {
    if (picker.busy) return;
    picker.busy = true;
    try {
      while (picker.next && picker.rows.length < 200) {
        const result = await api("/api/quickbooks/estimates/list", {
          project_id: projectId, individual_id: individualId, start_position: picker.next,
        });
        if (!listHost.isConnected) return;
        if (!result?.ok) throw new Error(_ptEstError(result?.error));
        const known = new Set(picker.rows.map(row => row.id));
        picker.rows.push(...(result.estimates || []).filter(row => !known.has(row.id)));
        picker.next = result.next_position;
        drawEstimates();
      }
      picker.complete = !picker.next || picker.rows.length >= 200;
      drawEstimates();
      searchInput?.focus();
    } catch (error) {
      picker.complete = true;
      message.textContent = error.message || "Could not read estimates. Connect QuickBooks and try again.";
      if (!picker.rows.length) listHost.innerHTML = `<div class="qb-estimate-list-empty">Estimates are unavailable.</div>`;
    } finally {
      picker.busy = false;
    }
  };
  $("qb-estimate-disconnect")?.addEventListener("click", async event => {
    if (!confirm(`Disconnect Quote ${existingNumber}?\n\nThis will not edit or delete anything in QuickBooks.`)) return;
    event.currentTarget.disabled = true;
    try {
      const result = await api("/api/quickbooks/estimates/bind", {
        project_id: projectId, individual_id: individualId, qb_estimate_id: "",
      });
      if (!result?.ok) throw new Error(result?.error || "Estimate connection could not be removed");
      await finish(result, "Estimate connection removed");
    } catch (error) {
      toast(error.message || "Estimate connection could not be removed", "error");
      event.currentTarget.disabled = false;
    }
  });
  loadEstimates();
};

const _QB_IMPORT_LABELS = {
  catalog_part: ["Ready for placement", "ready"],
  accessory: ["Accessory relationship", "accessory"],
  guided_system: ["Guided setup required", "guided"],
  custom: ["One-off custom part", "custom"],
  unknown_item: ["Needs a decision", "unknown"],
  pending_part: ["Pending QuickBooks item", "unknown"],
  section_header: ["Section header — ignored", "ignored"],
  additional_charge: ["Additional charge — ignored", "ignored"],
  calculated_or_unsupported: ["Calculated line — ignored", "ignored"],
};

const _ptQbImportSessions = new Map();

function _ptQbCloseLeavePrompt() {
  $("qb-import-leave-modal")?.classList.remove("open");
}

function _ptQbOpenLeavePrompt({ readyCount, importBlockedReason = "", onDiscard, onSave, onImport }) {
  let modal = $("qb-import-leave-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "qb-import-leave-modal";
    modal.className = "modal-overlay qb-import-leave-overlay";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `<div class="modal qb-import-leave-dialog">
      <div class="modal-title"><span>Leave Estimate review?</span><button type="button" class="modal-close" data-qb-leave-cancel aria-label="Keep reviewing">×</button></div>
      <p>Your current import decisions have not been applied to the build.</p>
      <div class="modal-actions qb-import-leave-actions">
        <button type="button" class="btn btn-secondary" data-qb-leave-discard>Leave without saving</button>
        <button type="button" class="btn btn-secondary" data-qb-leave-save>Save for later</button>
        <button type="button" class="btn btn-primary" data-qb-leave-import>Import ready parts</button>
      </div>
    </div>`;
    document.body.appendChild(modal);
  }
  normalizeModalOverlay(modal);
  modal.querySelector("[data-qb-leave-cancel]").onclick = _ptQbCloseLeavePrompt;
  const message = modal.querySelector(".qb-import-leave-dialog > p");
  if (message) {
    message.textContent = importBlockedReason
      ? `${importBlockedReason} You can save this review and finish it later.`
      : "Your current import decisions have not been applied to the build.";
  }
  const importButton = modal.querySelector("[data-qb-leave-import]");
  if (importButton) {
    importButton.disabled = readyCount < 1 || Boolean(importBlockedReason);
    importButton.textContent = importBlockedReason
      ? "Finish split before importing"
      : readyCount > 0
      ? `Import ${readyCount} ready part${readyCount === 1 ? "" : "s"}` : "No ready parts";
  }
  modal.querySelector("[data-qb-leave-discard]").onclick = onDiscard;
  modal.querySelector("[data-qb-leave-save]").onclick = onSave;
  if (importButton) importButton.onclick = onImport;
  modal.onclick = event => {
    if (event.target === modal) _ptQbCloseLeavePrompt();
  };
  modal.classList.add("open");
}

function _ptQbReservedLineId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `qb-stage-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function _ptQbImportSessionId(projectId, individualId, estimateId) {
  return `${projectId}:${individualId}:${estimateId}`;
}

async function _ptQbStageAutomaticLocations(lines, session, estimate) {
  const automaticParts = lines.filter(line => {
    const match = (line.catalog_matches || [])[0];
    return Boolean(match?.is_fixture || match?.fixed_location)
      && !match.picker_location_allocation
      && !match.has_configured_accessories
      && !line.ambiguous_match && !line.covered_by_guided_line_id
      && !line.already_imported && line.comparison?.status !== "matched"
      && !line.converted_from_custom && !line.grouped_under_line_id
      && !(line.grouped_line_ids || []).length
      && !session.resolved.has(line.line_id) && !session.skipped.has(line.line_id)
      && !session.splitPlans?.has(line.line_id)
      && line.classification === "catalog_part";
  });
  for (const line of automaticParts) {
    const match = line.catalog_matches[0];
    const quantity = Math.max(1, Number(line.quantity) || 1);
    const fixedLocation = match.fixed_location
      || match.default_location || match.fixture_label || match.fixture_base_label || "";
    const baseName = match.is_fixture
      ? (match.fixture_base_label || match.fixture_label || match.model || match.part_number)
      : (match.primary_part_type_label || match.model || match.part_number);
    const colors = [match.color, match.secondary_color, match.tertiary_color]
      .filter(Boolean).map(value => String(value).toLowerCase());
    const colorLabel = colors.map(value => value.charAt(0).toUpperCase() + value.slice(1)).join("/");
    const resolved = await api("/api/parts-db/resolve-selection", {
      product_model: match.model || match.part_number,
      manufacturer_label: match.manufacturer || "",
      location: fixedLocation,
      base_name: baseName,
      lens: match.lens_type || "",
      combos: [{
        colors, part_number: match.part_number, quantity,
        price: line.unit_price == null ? null : Number(line.unit_price),
      }],
      color_fields: colorLabel ? { raw_color: colorLabel } : {},
      total_heads: quantity,
    });
    const rows = resolved?.rows || [];
    if (!rows.length) throw new Error(`Could not prepare automatic location for ${match.part_number}`);
    const reserved = session.stagedParents.get(line.line_id);
    _ptQbClearStagedLine(session, line.line_id, { preserveReservedDependents: true });
    if (["quantity_changed", "supply_changed"].includes(line.comparison?.status)) {
      session.replacements.set(
        line.line_id, new Set(line.comparison.matching_manifest_line_ids || []),
      );
    }
    rows.forEach((row, index) => {
      const lineId = index === 0 ? (reserved?.line_id || _ptQbReservedLineId()) : _ptQbReservedLineId();
      const pickerConfig = {
        mode: "uniform",
        colorsPerHead: colors.length === 1 ? "single" : colors.length === 2 ? "duo" : colors.length >= 3 ? "trio" : "single",
        uniform: colors,
        splitSecondary: [], custom: [], _noColor: !colors.length,
        count: quantity, lens: match.lens_type || "", skuChoices: {}, details: {},
        qb_import: {
          estimate_id: estimate.id, estimate_number: estimate.number,
          line_id: line.line_id, item_id: line.item_id,
          description: line.description, amount: line.amount, related_line_ids: [],
        },
      };
      const importedPrice = Number(line.unit_price);
      if (line.unit_price != null && Number.isFinite(importedPrice) && importedPrice >= 0) {
        pickerConfig.quote_unit_price_override = importedPrice;
      }
      const body = {
        ...row, line_id: lineId, supply_type: "new", customer_condition: "",
        customer_source: "", new_or_used: "New", source: "",
        picker_config: pickerConfig,
        ...(match.primary_part_type_id ? { part_type: match.primary_part_type_id } : {}),
      };
      session.operations.push({
        path: `/api/draft/${session.draftId}/part`, sourceLineId: line.line_id, body,
      });
      if (index === 0) {
        session.stagedParents.set(line.line_id, {
          line_id: lineId, source_line_id: line.line_id,
          name: body.name || match.model || match.part_number,
          location: body.location || "", part_number: body.part_number || "",
          product_ids: [match.product_id].filter(Boolean), reserved: false,
        });
      }
    });
    session.resolved.add(line.line_id);
    session.skipped.delete(line.line_id);
    for (const manifestLineId of (session.replacements.get(line.line_id) || [])) {
      session.removals.add(manifestLineId);
    }
  }
}

function _ptQbStageMatchedAccessory(session, line, match, relation, estimate) {
  _ptQbClearStagedLine(session, line.line_id);
  if (["quantity_changed", "supply_changed"].includes(line.comparison?.status)) {
    session.replacements.set(
      line.line_id, new Set(line.comparison.matching_manifest_line_ids || []),
    );
  }
  const importedPrice = Number(line.unit_price);
  const pickerConfig = {
    qb_import: {
      estimate_id: estimate.id, estimate_number: estimate.number,
      line_id: line.line_id, item_id: line.item_id,
      description: line.description, amount: line.amount, related_line_ids: [],
    },
  };
  if (line.unit_price != null && Number.isFinite(importedPrice) && importedPrice >= 0) {
    pickerConfig.quote_unit_price_override = importedPrice;
  }
  const parentLocation = /^(?:will be imported|automatic fixture)$/i.test(
    String(relation.parent_location || "").trim(),
  ) ? "" : String(relation.parent_location || "").trim();
  session.operations.push({
    path: `/api/draft/${session.draftId}/part`, sourceLineId: line.line_id,
    body: {
      line_id: _ptQbReservedLineId(),
      name: relation.parent_line_id
        ? `${relation.parent_name} · ${match.model || match.part_number}`
        : (match.model || match.part_number),
      location: parentLocation,
      manufacturer: match.manufacturer || "",
      part_number: match.part_number,
      quantity: Math.max(1, Number(line.quantity) || 1),
      supply_type: "new", customer_condition: "", customer_source: "",
      new_or_used: "New", source: "",
      parent_line_id: relation.parent_line_id,
      accessory_category: relation.parent_line_id
        ? (relation.accessory_category || match.accessory_category || "other") : "",
      accessory_parent_product: relation.parent_line_id ? (relation.parent_product_id || "") : "",
      picker_config: pickerConfig,
      ...(match.primary_part_type_id ? { part_type: match.primary_part_type_id } : {}),
    },
  });
  session.resolved.add(line.line_id);
  session.skipped.delete(line.line_id);
  for (const manifestLineId of (session.replacements.get(line.line_id) || [])) {
    session.removals.add(manifestLineId);
  }
}

window.PT_getQbEstimateImportSession = function (sessionId) {
  return _ptQbImportSessions.get(sessionId) || null;
};

window.PT_stageQbEstimateLineResolved = function (sessionId, lineId, partialPlacement = null) {
  const session = _ptQbImportSessions.get(sessionId);
  if (!session || !lineId) return;
  if (partialPlacement) {
    const total = Math.max(1, Number(partialPlacement.totalQuantity) || 1);
    const quantity = Math.max(1, Number(partialPlacement.quantity) || 1);
    const plan = session.splitPlans.get(lineId) || { total, placed: 0 };
    plan.total = total;
    plan.placed = Math.min(total, plan.placed + quantity);
    session.splitPlans.set(lineId, plan);
    if (plan.placed >= total) session.resolved.add(lineId);
    else session.resolved.delete(lineId);
  } else {
    session.resolved.add(lineId);
  }
  session.skipped.delete(lineId);
  for (const [memberLineId, ownerLineId] of session.groupOwners || []) {
    if (ownerLineId !== lineId) continue;
    session.resolved.add(memberLineId);
    session.skipped.delete(memberLineId);
  }
  for (const manifestLineId of (session.replacements.get(lineId) || [])) {
    session.removals.add(manifestLineId);
  }
};

function _ptQbClearStagedLine(session, lineId, { preserveReservedDependents = false } = {}) {
  const ownerLineId = session.groupOwners?.get(lineId) || lineId;
  const groupLineIds = new Set([ownerLineId]);
  for (const [memberLineId, owner] of session.groupOwners || []) {
    if (owner === ownerLineId) groupLineIds.add(memberLineId);
  }
  const stagedParentLineId = session.stagedParents.get(ownerLineId)?.line_id || "";
  const parentWasStaged = session.operations.some(operation => operation.sourceLineId === ownerLineId);
  const dependentSources = new Set();
  // A quoted parent gets a reserved ID before it is configured so accessories
  // can safely target it on a blank build. Opening that parent for the first
  // time must preserve those accessory decisions; only changing/removing an
  // already-staged parent invalidates its children.
  if (stagedParentLineId && (parentWasStaged || !preserveReservedDependents)) {
    for (const operation of session.operations) {
      const rows = operation.body?.rows || [];
      if (operation.body?.parent_line_id === stagedParentLineId
          || rows.some(row => row?.parent_line_id === stagedParentLineId)) {
        dependentSources.add(operation.sourceLineId);
      }
    }
  }
  session.operations = session.operations.filter(operation =>
    operation.sourceLineId !== ownerLineId && !dependentSources.has(operation.sourceLineId)
  );
  for (const groupedLineId of groupLineIds) {
    session.resolved.delete(groupedLineId);
    session.skipped.delete(groupedLineId);
    session.stagedParents.delete(groupedLineId);
    session.groupOwners?.delete(groupedLineId);
    session.splitPlans?.delete(groupedLineId);
  }
  for (const sourceLineId of dependentSources) {
    session.resolved.delete(sourceLineId);
    session.stagedParents.delete(sourceLineId);
    session.parentAccessoryRestoredSkips?.delete(sourceLineId);
    for (const manifestLineId of (session.replacements.get(sourceLineId) || [])) {
      session.removals.delete(manifestLineId);
    }
    session.replacements.delete(sourceLineId);
  }
  for (const manifestLineId of (session.replacements.get(ownerLineId) || [])) {
    session.removals.delete(manifestLineId);
  }
  session.replacements.delete(ownerLineId);
  session.parentAccessoryRestoredSkips?.delete(ownerLineId);
}

const _ptQbAccessoryCatalogCache = new Map();

async function _ptQbLoadParentAccessoryCatalog(lines) {
  const productIds = new Set();
  for (const line of (lines || [])) {
    if (line.ambiguous_match || line.classification === "accessory"
        || line.classification === "guided_system") continue;
    const match = (line.catalog_matches || [])[0];
    if (match?.product_id && !match.is_accessory) productIds.add(match.product_id);
  }
  await Promise.all([...productIds].map(async productId => {
    if (!_ptQbAccessoryCatalogCache.has(productId)) {
      _ptQbAccessoryCatalogCache.set(productId, api(
        `/api/parts-db/accessories?product_id=${encodeURIComponent(productId)}`,
      ).then(result => result?.accessories || []).catch(() => []));
    }
    await _ptQbAccessoryCatalogCache.get(productId);
  }));
  return new Map(await Promise.all([...productIds].map(async productId => [
    productId, await _ptQbAccessoryCatalogCache.get(productId),
  ])));
}

function _ptQbStagedOperationRows(session) {
  const rows = [];
  for (const operation of (session?.operations || [])) {
    const add = row => {
      if (row && typeof row === "object" && row.part_number) {
        rows.push({ ...row, _sourceLineId: operation.sourceLineId });
      }
    };
    if (/\/part$/.test(operation.path || "")) add(operation.body);
    (operation.body?.rows || []).forEach(add);
    add(operation.body?.printer);
    (operation.body?.printer_cables || []).forEach(add);
  }
  return rows;
}

function _ptQbReconcileQuotedAccessoriesWithStagedChildren(lines, session, estimate) {
  const stagedRows = _ptQbStagedOperationRows(session);
  for (const line of (lines || [])) {
    if (line.classification !== "accessory" || line.ambiguous_match
        || line.already_imported || line.covered_by_guided_line_id
        || session.resolved.has(line.line_id) || session.skipped.has(line.line_id)) continue;
    const match = (line.catalog_matches || [])[0];
    const sku = String(match?.part_number || "").trim().toLowerCase();
    if (!sku) continue;
    const staged = stagedRows.find(row => (
      row.parent_line_id
      && row._sourceLineId !== line.line_id
      && String(row.part_number || "").trim().toLowerCase() === sku
    ));
    if (!staged) continue;
    const provenance = {
      estimate_id: estimate.id, estimate_number: estimate.number,
      line_id: line.line_id, item_id: line.item_id,
      description: line.description, amount: line.amount, related_line_ids: [],
    };
    staged.picker_config = { ...(staged.picker_config || {}), qb_import: provenance };
    const operation = session.operations.find(item => item.sourceLineId === staged._sourceLineId);
    const candidates = [operation?.body, ...(operation?.body?.rows || []), operation?.body?.printer,
      ...(operation?.body?.printer_cables || [])].filter(Boolean);
    const original = candidates.find(row => (
      row.parent_line_id
      && String(row.part_number || "").trim().toLowerCase() === sku
    ));
    if (original) {
      original.picker_config = { ...(original.picker_config || {}), qb_import: provenance };
      const importedPrice = Number(line.unit_price);
      if (line.unit_price != null && Number.isFinite(importedPrice) && importedPrice >= 0) {
        original.picker_config.quote_unit_price_override = importedPrice;
      }
    }
    session.resolved.add(line.line_id);
  }
}

function _ptQbParentAccessoryTarget(line, session, context) {
  const staged = session.stagedParents.get(line.line_id);
  if (session.resolved.has(line.line_id) && staged && !staged.reserved) return staged;
  if (line.already_imported || line.comparison?.status === "matched") {
    const matching = new Set(line.comparison?.matching_manifest_line_ids || []);
    const existing = (context.manifestParents || []).find(row => matching.has(row.line_id));
    if (existing) return existing;
  }
  return null;
}

function _ptQbAccessoryQuotedLines(option, context) {
  const sku = String(option.part_number || "").trim().toLowerCase();
  return (context.activeLines || []).filter(line => {
    if (line.ignored || line.line_id === option.parentSourceLineId) return false;
    const match = !line.ambiguous_match ? (line.catalog_matches || [])[0] : null;
    if (!match) return false;
    return sku
      ? String(match.part_number || "").trim().toLowerCase() === sku
      : Boolean(option.product_id && match.product_id === option.product_id);
  });
}

function _ptQbAccessoryRecommendedQuantity(sku, parentQuantity) {
  const rule = sku?.accessory_quantity || {};
  if (rule.mode !== "cover_parent_quantity") return 1;
  const coverage = Math.max(1, Number(rule.parent_units_per_item) || 1);
  return Math.max(1, Math.ceil(Math.max(1, Number(parentQuantity) || 1) / coverage));
}

function _ptQbParentAccessoryStatus(option, target, session, context) {
  const sku = String(option.part_number || "").trim().toLowerCase();
  const sameSku = row => String(row.part_number || "").trim().toLowerCase() === sku;
  const existing = (context.manifestAccessories || []).filter(sameSku);
  const staged = _ptQbStagedOperationRows(session).filter(sameSku);
  const attached = existing.find(row => row.parent_line_id === target?.line_id);
  const stagedHere = staged.find(row => row.parent_line_id === target?.line_id);
  const elsewhere = existing.find(row => row.parent_line_id !== target?.line_id)
    || staged.find(row => row.parent_line_id !== target?.line_id);
  const quoted = _ptQbAccessoryQuotedLines(option, context);
  const skipped = quoted.find(line => session.skipped.has(line.line_id));
  const quotedReady = quoted.find(line => session.resolved.has(line.line_id));
  const quotedImported = quoted.find(line => line.already_imported || line.comparison?.status === "matched");
  const guided = quoted.find(line => line.covered_by_guided_line_id);

  if (attached) return {
    label: quoted.length
      ? "Already on build under this part" : "Already on build under this part · not on Estimate",
    disabled: true, satisfiesGroup: true, quotedLine: quoted[0] || null,
  };
  if (stagedHere) return {
    label: quoted.length ? "Ready under this part" : "Ready under this part · not on Estimate",
    disabled: true, satisfiesGroup: true,
    stagedSourceLineId: stagedHere._sourceLineId, quotedLine: quoted[0] || null,
  };
  if (elsewhere) return {
    label: quoted.length
      ? "Already on build or staged elsewhere" : "On build or staged elsewhere · not on Estimate",
    disabled: true, quotedLine: quoted[0] || null,
  };
  if (guided) return { label: "Included by guided setup", disabled: true, quotedLine: guided };
  if (quotedReady) return { label: "On Estimate — already staged", disabled: true, quotedLine: quotedReady };
  if (quotedImported) return { label: "On Estimate — already imported", disabled: true, quotedLine: quotedImported };
  if (quoted.length && !skipped) {
    return { label: "On Estimate — resolve its listed line first", disabled: true, quotedLine: quoted[0] };
  }
  if (skipped) {
    return {
      label: "On Estimate — left out; select to attach here",
      disabled: !target, quotedLine: skipped,
    };
  }
  return { label: "Not on Estimate — add to build", disabled: !target };
}

function _ptQbMissingRequiredParentAccessories(context, session) {
  return [...(context?.menus?.values() || [])].filter(menu => {
    if (!menu.target || !menu.group?.required) return false;
    // Do not make an older, otherwise-matched manifest row block unrelated
    // Estimate decisions. Enforce the relationship when this review is
    // actually adding or replacing the parent.
    const parentIsStaged = (session?.operations || []).some(operation =>
      operation.sourceLineId === menu.line?.line_id
    );
    return parentIsStaged
      && !menu.options.some(option => option.status?.satisfiesGroup);
  });
}

function _ptQbParentAccessoriesHtml(line, actionIndex, session, context) {
  if (actionIndex === null || line.ambiguous_match || line.classification === "accessory"
      || line.classification === "guided_system") return "";
  const match = (line.catalog_matches || [])[0];
  const groups = context.catalogByProductId.get(match?.product_id) || [];
  if (!match || !groups.length) return "";
  const target = _ptQbParentAccessoryTarget(line, session, context);
  const rendered = [];
  groups.forEach((group, groupIndex) => {
    const menuId = `${actionIndex}:${groupIndex}`;
    const options = [];
    for (const product of (group.options || [])) {
      for (const sku of (product.skus || [])) {
        if (!sku.part_number) continue;
        const option = {
          parentSourceLineId: line.line_id,
          parentMatch: match,
          parentTarget: target,
          category: group.category || "other",
          product_id: product.product_id || "",
          model: product.model || sku.friendly_name || sku.part_number,
          manufacturer: product.manufacturer_label || "",
          part_number: sku.part_number,
          price: sku.price,
          quantity: _ptQbAccessoryRecommendedQuantity(sku, line.quantity),
          part_type: product.part_type || "",
        };
        option.status = _ptQbParentAccessoryStatus(option, target, session, context);
        if (option.status.quotedLine) option.quantity = Math.max(1, Number(option.status.quotedLine.quantity) || 1);
        options.push(option);
      }
    }
    if (!options.length) return;
    context.menus.set(menuId, { line, match, group, target, options });
    const staged = options.filter(option => option.status.stagedSourceLineId);
    const optionHtml = options.map((option, optionIndex) => {
      const price = option.price != null ? ` · ${_ptMoney2(option.price)}` : "";
      const qbDescription = option.status.quotedLine?.description
        ? ` · QB: ${option.status.quotedLine.description}` : "";
      const label = `${option.part_number} · ${option.model}${price} — ${option.status.label}${qbDescription}`;
      return `<option value="${optionIndex}"${option.status.disabled ? " disabled" : ""}>${esc(label)}</option>`;
    }).join("");
    rendered.push(`<div class="qb-import-parent-accessory-row">
      <label><span>${esc(group.label || group.category || "Accessory")}${group.required ? " · required" : ""}</span>
        <select data-qb-parent-accessory-select="${esc(menuId)}"${target ? "" : " disabled"}>
          <option value="" selected>${target ? "Choose an accessory…" : "Resolve the parent part first"}</option>${optionHtml}
        </select>
      </label>
      <label class="qb-import-parent-accessory-qty">Qty<input type="number" min="1" max="999" step="1" value="1" data-qb-parent-accessory-qty="${esc(menuId)}"${target ? "" : " disabled"}></label>
      <label>Supply<select data-qb-parent-accessory-supply="${esc(menuId)}"${target ? "" : " disabled"}><option value="new">DTM supplied / New</option><option value="customer_new">Customer supplied / New</option><option value="customer_used">Customer supplied / Used</option></select></label>
      <label class="qb-import-parent-accessory-source" data-qb-parent-accessory-source-wrap="${esc(menuId)}" hidden>Used-part source<input type="text" data-qb-parent-accessory-source="${esc(menuId)}" placeholder="Agency, old vehicle, customer stock…"></label>
      <button type="button" class="btn btn-secondary btn-sm" data-qb-parent-accessory-add="${esc(menuId)}" disabled>Add under part</button>
      ${staged.map(option => `<span class="qb-import-parent-accessory-ready">✓ ${esc(option.part_number)} ready${option.status.stagedSourceLineId !== line.line_id ? ` <button type="button" data-qb-parent-accessory-remove="${esc(option.status.stagedSourceLineId)}">Undo</button>` : ""}</span>`).join("")}
    </div>`);
  });
  return rendered.length ? `<details class="qb-import-parent-accessories"><summary>Accessories for this part</summary><p>Add compatible child parts here. Options already represented by the Estimate or build are marked and protected from duplicate selection.</p>${rendered.join("")}</details>` : "";
}

function _ptQbStageMissingParentAccessory(session, menu, option, quantity, estimate, supplyValue, customerSource) {
  const sourceLineId = `extra-accessory:${menu.line.line_id}:${option.category}:${option.part_number}:${_ptQbReservedLineId()}`;
  const parentLocation = /^(?:will be imported|automatic fixture)$/i.test(
    String(menu.target.location || "").trim(),
  ) ? "" : String(menu.target.location || "").trim();
  const customerSupplied = supplyValue === "customer_new" || supplyValue === "customer_used";
  const customerCondition = supplyValue === "customer_used" ? "used" : supplyValue === "customer_new" ? "new" : "";
  session.operations.push({
    path: `/api/draft/${session.draftId}/part`,
    sourceLineId,
    body: {
      line_id: _ptQbReservedLineId(),
      name: `${menu.target.name} · ${option.model || option.part_number}`,
      location: parentLocation,
      manufacturer: option.manufacturer || "",
      part_number: option.part_number,
      quantity,
      supply_type: customerSupplied ? "customer_supplied" : "new",
      customer_condition: customerCondition,
      customer_source: customerSupplied ? customerSource : "",
      new_or_used: customerSupplied ? "Used" : "New",
      source: customerSupplied ? customerSource : "",
      parent_line_id: menu.target.line_id,
      accessory_category: option.category || "other",
      accessory_parent_product: menu.match.product_id || "",
      ...(option.part_type ? { part_type: option.part_type } : {}),
      picker_config: {
        added_during_estimate_review: {
          estimate_id: estimate.id,
          estimate_number: estimate.number,
          parent_estimate_line_id: menu.line.line_id,
          absent_from_estimate: true,
        },
      },
    },
  });
  session.resolved.add(sourceLineId);
}

function _ptQbAccessoryControlHtml(line, match, actionIndex, parentOptions) {
  if (actionIndex === null || line.ambiguous_match || !match) return "";
  const suggestedRows = [];
  const suggestedLineIds = new Set();
  for (const candidate of (match.accessory_parent_candidates || [])) {
    for (const row of (candidate.manifest_options || [])) {
      if (!row.line_id || suggestedLineIds.has(row.line_id)) continue;
      suggestedLineIds.add(row.line_id);
      suggestedRows.push({ ...row, suggested_product_id: candidate.product_id });
    }
    for (const row of (parentOptions || [])) {
      if (!row.line_id || suggestedLineIds.has(row.line_id)) continue;
      if (!(row.product_ids || []).includes(candidate.product_id)) continue;
      suggestedLineIds.add(row.line_id);
      suggestedRows.push({ ...row, suggested_product_id: candidate.product_id });
    }
  }
  const otherRows = (parentOptions || []).filter(row =>
    row.line_id && !suggestedLineIds.has(row.line_id)
  );
  const option = (row, selected = false) => {
    const detail = [row.location, row.part_number].filter(Boolean).join(" · ");
    return `<option value="${esc(row.line_id)}"${selected ? " selected" : ""}>${esc(row.name)}${detail ? ` — ${esc(detail)}` : ""}</option>`;
  };
  return `<div class="qb-import-accessory-control">
    <label>Accessory of
      <select data-qb-accessory-parent="${actionIndex}">
        ${suggestedRows.length ? `<optgroup label="Suggested">${suggestedRows.map((row, index) => option(row, index === 0)).join("")}</optgroup>` : `<option value="" selected>Choose a manifest parent…</option>`}
        ${otherRows.length ? `<optgroup label="Other manifest parts">${otherRows.map(row => option(row)).join("")}</optgroup>` : ""}
        <option value="standalone">Not an accessory — keep standalone</option>
      </select>
    </label>
    <label data-qb-accessory-standalone-location="${actionIndex}" hidden>Standalone location
      <input data-qb-accessory-location="${actionIndex}" placeholder="Where it goes">
    </label>
    <button type="button" class="btn btn-primary btn-sm" data-qb-accessory-add="${actionIndex}"${suggestedRows.length ? "" : " disabled"}>Resolve for import</button>
  </div>`;
}

function _ptQbCustomLineDefaults(line) {
  const quotedQuantity = Number(line?.quantity);
  const quantity = Number.isInteger(quotedQuantity) && quotedQuantity >= 1 && quotedQuantity <= 999
    ? quotedQuantity : 1;
  const quotedPrice = Number(line?.unit_price);
  const quotedAmount = Number(line?.amount);
  const unitPrice = line?.unit_price != null && Number.isFinite(quotedPrice) && quotedPrice >= 0
    ? quotedPrice
    : Number.isFinite(quotedAmount) && quotedAmount >= 0
      ? quotedAmount / quantity : 0;
  const itemName = String(line?.item_name || "").trim();
  return {
    sku: String(line?.suggested_sku || (
      itemName && itemName.toLowerCase() !== "misc part" ? itemName : ""
    )).trim(),
    description: String(line?.description || itemName || "Custom part").trim() || "Custom part",
    location: "",
    quantity,
    unitPrice,
    formPrice: line?.unit_price == null ? "" : String(line.unit_price),
  };
}

function _ptQbStageCustomEstimateLine(session, line, estimate, values = null) {
  const custom = values || _ptQbCustomLineDefaults(line);
  _ptQbClearStagedLine(session, line.line_id);
  session.operations.push({
    path: `/api/draft/${session.draftId}/custom-part`,
    sourceLineId: line.line_id,
    body: {
      sku: String(custom.sku || "").trim(),
      description: String(custom.description || "Custom part").trim() || "Custom part",
      location: String(custom.location || "").trim(),
      unit_price: Number(custom.unitPrice),
      quantity: Number(custom.quantity),
      qb_import: {
        estimate_id: estimate.id, estimate_number: estimate.number,
        line_id: line.line_id, item_id: line.item_id,
        description: line.description, amount: line.amount,
      },
    },
  });
  session.resolved.add(line.line_id);
  session.skipped.delete(line.line_id);
}

function _ptQbGroupCandidates(line, context, session) {
  const match = !line.ambiguous_match ? (line.catalog_matches || [])[0] : null;
  if (!match?.product_id || line.classification !== "catalog_part") return [];
  return (context?.activeLines || []).flatMap(candidate => {
    if (candidate === line || candidate.ignored || candidate.ambiguous_match
        || candidate.already_imported || session?.groupOwners?.has(candidate.line_id)
        || candidate.covered_by_guided_line_id || session?.resolved.has(candidate.line_id)
        || session?.skipped.has(candidate.line_id)) return [];
    let candidateMatch = candidate.classification === "catalog_part"
      ? (candidate.catalog_matches || [])[0] : null;
    let convertsCustom = false;
    if (!candidateMatch && ["custom", "unknown_item", "pending_part"].includes(candidate.classification)) {
      candidateMatch = (candidate.catalog_suggestions || []).find(
        suggestion => suggestion.product_id === match.product_id,
      );
      convertsCustom = Boolean(candidateMatch);
    }
    if (candidateMatch?.product_id !== match.product_id) return [];
    const colors = [candidateMatch.color, candidateMatch.secondary_color, candidateMatch.tertiary_color]
      .filter(Boolean);
    return colors.length ? [{ line: candidate, match: candidateMatch, convertsCustom }] : [];
  });
}

function _ptQbCatalogSuggestionDetails(suggestion) {
  const colors = [suggestion.color, suggestion.secondary_color, suggestion.tertiary_color]
    .filter(Boolean).join("/");
  const partPrice = suggestion.price == null ? "" : _ptMoney2(suggestion.price);
  const configuration = [
    colors ? `Color ${colors}` : "",
    suggestion.lens_type ? `${suggestion.lens_type} lens` : "",
  ].filter(Boolean).join(" · ");
  const rows = [
    ["Manufacturer", suggestion.manufacturer],
    ["Model", suggestion.model],
    ["Friendly name", suggestion.friendly_name],
    ["Catalog description", suggestion.description || "No catalog description available"],
    ["Part price", partPrice],
    ["Configuration", configuration],
    ["Part type", suggestion.primary_part_type_label],
    ["Why suggested", `${suggestion.match_reason || "Close catalog match"}${suggestion.match_score != null ? ` (${suggestion.match_score}%)` : ""}`],
  ].filter(([, value]) => String(value || "").trim());
  return `<details class="qb-import-catalog-details"><summary>View part details</summary><dl>${rows.map(
    ([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`,
  ).join("")}</dl></details>`;
}

function _ptQbImportLineHtml(line, actionIndex = null, parentOptions = [], session = null, accessoryContext = null) {
  const comparisonStatus = line.comparison?.status || "not_comparable";
  const staged = !!session?.resolved.has(line.line_id);
  const skipped = !!session?.skipped.has(line.line_id);
  const matched = comparisonStatus === "matched" && !line.already_imported;
  let [label, tone] = _QB_IMPORT_LABELS[line.classification] || [line.classification || "Review", "unknown"];
  if (matched) [label, tone] = ["Matches build", "matched"];
  else if (comparisonStatus === "quantity_changed") [label, tone] = ["Quantity changed", "changed"];
  else if (comparisonStatus === "supply_changed") [label, tone] = ["New vs. reused", "changed"];
  else if (comparisonStatus === "new" && (line.comparison?.different_from || []).length) [label, tone] = ["Different from build", "changed"];
  else if (comparisonStatus === "new") [label, tone] = ["New on Estimate", tone];
  if (line.covered_by_guided_line_id) [label, tone] = [`Included in ${line.covered_by_guided_kind} setup`, "guided"];
  if (staged) [label, tone] = ["Ready to import", "staged"];
  if (skipped) [label, tone] = ["Leaving out", "ignored"];
  const convertedTag = line.converted_from_custom
    ? `<div class="qb-import-converted-tag">Converted from custom part</div>` : "";
  const groupedTag = (line.grouped_line_ids || []).length
    ? `<div class="qb-import-converted-tag">${line.grouped_line_ids.length + 1} QB lines combined for one placement</div>`
    : "";
  const match = (line.catalog_matches || [])[0];
  const automaticLocation = Boolean(
    (match?.is_fixture || match?.fixed_location)
    && !match?.picker_location_allocation
    && !match?.has_configured_accessories
  );
  const stagedOperation = session?.operations?.find(operation => operation.sourceLineId === line.line_id);
  const incompleteCustomFields = stagedOperation && /\/custom-part$/.test(stagedOperation.path)
    ? [
        !String(stagedOperation.body?.sku || "").trim() ? "SKU" : "",
        !String(stagedOperation.body?.location || "").trim() ? "location" : "",
      ].filter(Boolean)
    : [];
  const incompleteCustomWarning = incompleteCustomFields.length
    ? `<div class="qb-import-suggestion qb-import-suggestion--warning">⚠ Missing ${esc(incompleteCustomFields.join(" and "))}. Import is allowed, but the build cannot be finalized until this is completed.</div>`
    : "";
  const identity = match
    ? `${match.part_number || match.model}${match.model && match.model !== match.part_number ? ` · ${match.model}` : ""}`
    : line.item_name || line.description || "QuickBooks line";
  const colors = match
    ? [match.color, match.secondary_color, match.tertiary_color].filter(Boolean).join("/")
    : "";
  const details = [
    Number(line.quantity) > 0 ? `Qty ${line.quantity}` : "",
    comparisonStatus === "quantity_changed" ? `Build has ${line.comparison.current_quantity}` : "",
    comparisonStatus === "supply_changed" ? `Build has ${line.comparison.physical_quantity} customer-supplied/reused` : "",
    colors ? `Color ${colors}` : "",
    match?.lens_type ? `${match.lens_type} lens` : "",
    line.unit_price != null ? _ptMoney2(line.unit_price) : "",
  ].filter(Boolean).join(" · ");
  const parent = match?.accessory_parent_candidates?.[0];
  const relationship = parent
    ? `<div class="qb-import-suggestion">Suggested parent: <strong>${esc(parent.model)}</strong> · ${esc(parent.reason)}${(parent.manifest_options || []).length ? "" : " · the quoted parent can be configured before or after this accessory"}</div>`
    : "";
  const guided = (line.guided_kinds || []).length
    ? `<div class="qb-import-suggestion">Run complete ${esc(line.guided_kinds.join(" / "))} setup</div>`
    : "";
  const different = (line.comparison?.different_from || []).length
    ? `<div class="qb-import-suggestion">Possible replacement for ${esc(line.comparison.different_from.map(item => item.name).join(", "))}. The existing build part remains unless you mark it for removal below.</div>`
    : "";
  const catalogSuggestions = line.catalog_suggestions || [];
  const catalogSuggestion = catalogSuggestions.length && !staged && !skipped && !line.already_imported
    ? `<div class="qb-import-catalog-suggestion"><strong>This custom quote line may now be a connected catalog part.</strong>
        <p>Convert it to the connected catalog part now, then choose its setup or placement when you are ready. You can still create a custom entry below.</p>
        <div class="qb-import-catalog-options">${catalogSuggestions.map((suggestion, suggestionIndex) => `<div class="qb-import-catalog-option"><button type="button" class="btn btn-secondary btn-sm" data-qb-use-catalog-suggestion="${actionIndex}:${suggestionIndex}">Convert to ${esc(suggestion.part_number)} · ${esc(suggestion.model || suggestion.friendly_name || "catalog part")} (${esc(suggestion.match_score)}%)</button><span>${esc(suggestion.match_reason || "Close catalog match")}</span>${_ptQbCatalogSuggestionDetails(suggestion)}</div>`).join("")}</div>
      </div>`
    : "";
  const quantity = Number(line.quantity);
  const placementIssue = !Number.isInteger(quantity) || quantity < 1
    ? "This physical-part quantity needs manual review before placement."
    : colors && quantity > 12
      ? "This line exceeds the 12-head placement limit and will need to be split."
      : "";
  const groupCandidates = _ptQbGroupCandidates(line, accessoryContext, session);
  const splitPlan = session?.splitPlans?.get(line.line_id) || null;
  const splitRemaining = splitPlan ? Math.max(0, splitPlan.total - splitPlan.placed) : 0;
  const splitChunkMax = colors ? Math.min(12, splitRemaining) : splitRemaining;
  const groupControl = actionIndex !== null && groupCandidates.length
    && !(line.grouped_line_ids || []).length && !staged && !skipped
    ? `<details class="qb-import-placement-tool"><summary>Group with another QB line at one location</summary>
        <p>Use this when color/configuration variants belong to the same physical placement. The original QB descriptions stay attached.</p>
        <div class="qb-import-group-options">${groupCandidates.map(candidateInfo => {
          const candidate = candidateInfo.line;
          const candidateMatch = candidateInfo.match;
          const candidateColors = [candidateMatch.color, candidateMatch.secondary_color, candidateMatch.tertiary_color].filter(Boolean).join("/");
          return `<label><input type="checkbox" data-qb-group-choice="${actionIndex}" value="${_ptEscAttr(candidate.line_id)}"><span><strong>${esc(candidateMatch.part_number)} · Qty ${esc(candidate.quantity || 1)}${candidateColors ? ` · ${esc(candidateColors)}` : ""}${candidateInfo.convertsCustom ? " · Custom match" : ""}</strong><small>${esc(candidate.description || "No QB description")}</small></span></label>`;
        }).join("")}</div>
        <button type="button" class="btn btn-primary btn-sm" data-qb-group-place="${actionIndex}" disabled>Combine selected QB lines</button>
      </details>`
    : "";
  const splitControl = actionIndex !== null && splitPlan && !staged && !skipped
    ? `<div class="qb-import-split-control"><div><strong>Split across locations</strong><span>${splitPlan.placed} of ${splitPlan.total} placed · ${splitRemaining} remaining</span></div>
        <label>Next location qty<input type="number" min="1" max="${splitChunkMax}" step="1" value="1" data-qb-split-qty="${actionIndex}"></label>
        <button type="button" class="btn btn-primary btn-sm" data-qb-split-place="${actionIndex}">Choose next location</button>
        <button type="button" class="btn btn-secondary btn-sm" data-qb-split-cancel="${actionIndex}">Cancel split</button>
      </div>`
    : "";
  const canSplit = actionIndex !== null && line.classification === "catalog_part"
    && !line.ambiguous_match && match && Number.isInteger(quantity) && quantity > 1
    && !(line.grouped_line_ids || []).length
    && !line.already_imported && !line.covered_by_guided_line_id && !staged && !skipped;
  const splitStart = canSplit && !splitPlan
    ? `<button type="button" class="btn btn-secondary btn-sm" data-qb-split-start="${actionIndex}">Split quantity across locations</button>`
    : "";
  const canPlace = actionIndex !== null
    && ["catalog_part", "guided_system"].includes(line.classification)
    && !line.ambiguous_match
    && match
    && !placementIssue
    && !line.already_imported
    && !line.covered_by_guided_line_id;
  const accessoryControl = line.classification === "accessory" && !placementIssue && !staged && !skipped && !matched
    ? _ptQbAccessoryControlHtml(line, match, actionIndex, parentOptions)
    : "";
  const customDecision = ["custom", "unknown_item", "pending_part"].includes(line.classification)
    && !staged && !skipped && !matched && actionIndex !== null
    ? `<div class="qb-import-custom-grid">
        <label>SKU<input data-qb-custom-sku="${actionIndex}" value="${_ptEscAttr(_ptQbCustomLineDefaults(line).sku)}" placeholder="Required SKU"></label>
        <label>Description<input data-qb-custom-description="${actionIndex}" value="${_ptEscAttr(line.description || line.item_name || "Custom part")}"></label>
        <label>Location<input data-qb-custom-location="${actionIndex}" placeholder="Where it goes"></label>
        <label>Qty<input data-qb-custom-quantity="${actionIndex}" type="number" min="1" max="999" step="1" value="${Math.max(1, Number(line.quantity) || 1)}"></label>
        <label>Unit price<input data-qb-custom-price="${actionIndex}" type="number" min="0" step="0.01" value="${line.unit_price == null ? "" : esc(line.unit_price)}"></label>
        <label class="qb-import-custom-render"><input data-qb-custom-render-light="${actionIndex}" type="checkbox"> Render as light head</label>
        <button type="button" class="btn btn-primary btn-sm" data-qb-custom-stage="${actionIndex}">Create custom entry</button>
        <p class="qb-import-custom-warning">SKU and location may be left blank for now, but the build cannot be finalized until both are completed.</p>
      </div>`
    : "";
  const conversionUndo = line.converted_from_custom && actionIndex !== null
    ? `<button type="button" class="btn btn-secondary btn-sm" data-qb-conversion-undo="${actionIndex}">Use custom entry instead</button>`
    : "";
  const groupUndo = (line.grouped_line_ids || []).length && actionIndex !== null
    ? `<button type="button" class="btn btn-secondary btn-sm" data-qb-group-undo="${actionIndex}">Separate QB lines</button>`
    : "";
  const decisionButtons = !line.already_imported && !matched && actionIndex !== null
    ? `${groupUndo}${conversionUndo}<button type="button" class="btn btn-secondary btn-sm" data-qb-import-skip="${actionIndex}">${skipped ? "Include after all" : "Leave out"}</button>`
    : "";
  const action = line.grouped_under_line_id
    ? `<div class="qb-import-line-action"><span class="qb-import-complete">Grouped with another QB line · placement pending</span></div>`
    : line.covered_by_guided_line_id
    ? `<div class="qb-import-line-action"><span class="qb-import-complete">✓ Configured with the related ${esc(line.covered_by_guided_kind)} system</span></div>`
    : line.already_imported
    ? `<div class="qb-import-line-action"><span class="qb-import-complete">✓ Already added from this Estimate line</span></div>`
    : matched
      ? `<div class="qb-import-line-action"><span class="qb-import-complete">✓ No action required</span></div>`
    : staged
      ? `<div class="qb-import-line-action"><span class="qb-import-complete">✓ Ready for final import</span><button type="button" class="btn btn-secondary btn-sm" ${automaticLocation ? `data-qb-import-skip="${actionIndex}">Leave out` : `data-qb-import-undo="${actionIndex}">Change decision`}</button></div>`
    : skipped
      ? `<div class="qb-import-line-action">${decisionButtons}</div>`
    : splitControl
      ? `${splitControl}<div class="qb-import-line-action">${decisionButtons}</div>`
    : canPlace
      ? `${groupControl}<div class="qb-import-line-action"><button type="button" class="btn btn-primary btn-sm" data-qb-import-index="${actionIndex}">${line.classification === "guided_system" ? "Complete guided setup" : match?.picker_location_allocation ? "Assign round light locations" : match?.is_fixture ? (match.has_configured_accessories ? "Review fixture options" : `Automatic location: ${esc(match.default_location || match.fixture_label || "fixture")}`) : match?.fixed_location ? `Automatic location: ${esc(match.fixed_location)}` : comparisonStatus === "quantity_changed" ? "Use Estimate quantity" : comparisonStatus === "supply_changed" ? "Use Estimate as New" : "Set one location"}</button>${splitStart}${decisionButtons}</div>`
      : canSplit
        ? `<div class="qb-import-suggestion">${esc(placementIssue)}</div><div class="qb-import-line-action">${splitStart}${decisionButtons}</div>`
      : accessoryControl
        ? `${accessoryControl}<div class="qb-import-line-action">${decisionButtons}</div>`
      : customDecision
        ? `${customDecision}<div class="qb-import-line-action">${decisionButtons}</div>`
      : placementIssue && !line.already_imported
        ? `<div class="qb-import-suggestion">${esc(placementIssue)}</div><div class="qb-import-line-action">${decisionButtons}</div>`
        : decisionButtons ? `<div class="qb-import-line-action">${decisionButtons}</div>` : "";
  const parentAccessories = session && accessoryContext && !line.grouped_under_line_id
    ? _ptQbParentAccessoriesHtml(line, actionIndex, session, accessoryContext) : "";
  return `<article class="qb-import-line qb-import-line--${tone}">
    <div class="qb-import-line-main"><div><strong>${esc(identity)}</strong>${line.description && line.description !== identity ? `<p>${esc(line.description)}</p>` : ""}</div>
      <span class="qb-import-chip">${esc(label)}</span></div>
    ${convertedTag}${groupedTag}${details ? `<div class="qb-import-meta">${esc(details)}</div>` : ""}${relationship}${guided}${different}${catalogSuggestion}${incompleteCustomWarning}${action}${parentAccessories}
  </article>`;
}

window.PT_previewQbEstimateImport = async function (projectId, individualId, options = {}) {
  let controls = _ptEstModalEls();
  const preservingReview = Boolean(
    controls.modal?.classList.contains("open")
    && controls.title?.textContent === "Import Parts From QB"
    && controls.body?.querySelector(".qb-import-summary"),
  );
  const priorScrollTop = controls.modal?.scrollTop || 0;
  if (!preservingReview) {
    _ptOpenEstModal(
      "Import Parts From QB",
      `<div class="qb-import-loading"><span class="dtm-loading-spinner" aria-hidden="true"></span><div><strong>Parsing QB Estimate…</strong><span>Reading line details and matching them to the Parts DB.</span></div></div>`,
    );
    controls = _ptEstModalEls();
  } else {
    controls.modal?.classList.add("qb-import-refreshing");
  }
  if (!options.resultOverride && !(await _ptQbConnected())) {
    controls.modal?.classList.remove("qb-import-refreshing");
    if (!preservingReview) controls.modal?.classList.remove("open");
    toast("Connect QuickBooks before importing an Estimate", "error");
    return;
  }
  try {
    const result = options.resultOverride || await api("/api/quickbooks/estimates/import-preview", {
        project_id: projectId,
        individual_id: individualId,
      });
    if (!result?.ok) {
      const messages = {
        estimate_not_connected: "Connect an Estimate to this vehicle before importing its parts.",
        existing_estimate_not_found: "The connected Estimate no longer exists in this QuickBooks company.",
        unknown_individual: "This vehicle could not be found.",
      };
      throw new Error(messages[result?.error] || _ptEstError(result?.error));
    }
    const estimate = result.estimate || {};
    const sessionId = _ptQbImportSessionId(projectId, individualId, estimate.id);
    let session = _ptQbImportSessions.get(sessionId);
    if (!session) {
      session = {
        id: sessionId, projectId, individualId, estimateId: estimate.id,
        draftId: result.draft_id, operations: [], resolved: new Set(), skipped: new Set(),
        removals: new Set(), replacements: new Map(), stagedParents: new Map(),
        parentAccessoryRestoredSkips: new Set(), groupOwners: new Map(), splitPlans: new Map(),
        catalogConversions: new Map(),
      };
      _ptQbImportSessions.set(sessionId, session);
    }
    session.draftId = result.draft_id;
    if (!session.parentAccessoryRestoredSkips) session.parentAccessoryRestoredSkips = new Set();
    if (!session.groupOwners) session.groupOwners = new Map();
    if (!session.splitPlans) session.splitPlans = new Map();
    if (!session.catalogConversions) session.catalogConversions = new Map();
    let activeLines = (result.lines || []).filter(line => !line.ignored).map(line => {
      const conversion = session.catalogConversions.get(line.line_id);
      if (!conversion) return line;
      return {
        ...line,
        classification: "catalog_part",
        catalog_matches: [conversion],
        catalog_suggestions: [],
        ambiguous_match: false,
        converted_from_custom: true,
        original_classification: line.classification,
      };
    });
    const lineById = new Map(activeLines.map(line => [line.line_id, line]));
    activeLines = activeLines.map(line => {
      const groupOwnerId = session.groupOwners.get(line.line_id);
      if (groupOwnerId) return { ...line, grouped_under_line_id: groupOwnerId };
      const groupedLineIds = [...session.groupOwners.entries()]
        .filter(([, ownerId]) => ownerId === line.line_id)
        .map(([memberLineId]) => memberLineId)
        .filter(memberLineId => lineById.has(memberLineId));
      return groupedLineIds.length ? { ...line, grouped_line_ids: groupedLineIds } : line;
    });
    // Reserve future parent IDs up front. Accessories can therefore point at
    // quoted parents on a blank build before either line has been staged.
    for (const line of activeLines) {
      const match = (line.catalog_matches || [])[0];
      if (!match || line.ambiguous_match || line.classification === "accessory"
          || line.grouped_under_line_id
          || line.covered_by_guided_line_id || line.already_imported
          || session.skipped.has(line.line_id)) continue;
      if (!session.stagedParents.has(line.line_id)) {
        session.stagedParents.set(line.line_id, {
          line_id: _ptQbReservedLineId(), source_line_id: line.line_id,
          name: match.model || match.part_number || "Quoted part",
          location: match.fixed_location
            || (match.is_fixture ? (match.default_location || match.fixture_label || "Automatic fixture") : "Will be imported"),
          part_number: match.part_number || "", product_ids: [match.product_id].filter(Boolean),
          reserved: true,
        });
      }
    }
    await _ptQbStageAutomaticLocations(activeLines, session, estimate);
    _ptQbReconcileQuotedAccessoriesWithStagedChildren(activeLines, session, estimate);
    const outstandingLines = activeLines.filter(line =>
      !line.already_imported && !line.covered_by_guided_line_id && line.comparison?.status !== "matched"
    );
    const ignoredLines = (result.lines || []).filter(line => line.ignored);
    const parentOptions = [
      ...(result.manifest_parent_options || []),
      ...session.stagedParents.values(),
    ];
    const accessoryContext = {
      activeLines,
      manifestParents: result.manifest_parent_options || [],
      manifestAccessories: result.manifest_accessory_rows || [],
      catalogByProductId: await _ptQbLoadParentAccessoryCatalog(activeLines),
      menus: new Map(),
    };
    const reuse = (result.memo_reuse_suggestions || []).filter(item => !item.also_quoted);
    const unresolvedLines = outstandingLines.filter(line =>
      !session.resolved.has(line.line_id) && !session.skipped.has(line.line_id)
    );
    const bulkCustomLines = unresolvedLines.filter(line =>
      ["custom", "unknown_item", "pending_part"].includes(line.classification)
      && !(line.catalog_suggestions || []).length
    );
    const summary = [
      result.build_is_blank ? "Blank build" : "Existing build comparison",
      `${outstandingLines.length} difference${outstandingLines.length === 1 ? "" : "s"}`,
      `${activeLines.filter(line => line.comparison?.status === "matched" || line.already_imported).length} match${activeLines.filter(line => line.comparison?.status === "matched" || line.already_imported).length === 1 ? "" : "es"}`,
      session.resolved.size ? `${session.resolved.size} ready` : "",
      ignoredLines.length ? `${ignoredLines.length} header/charge line${ignoredLines.length === 1 ? "" : "s"} ignored` : "",
    ].filter(Boolean).join(" · ");
    controls.body.innerHTML = `<div class="qb-import-summary">
        <strong>Estimate ${esc(estimate.number || estimate.id)}</strong>
        <span>${esc([estimate.customer, estimate.date, estimate.status].filter(Boolean).join(" · "))}</span>
        <p>${esc(summary)}</p>
      </div>
      <div class="qb-import-notice"><strong>${result.build_is_blank ? "Resolve first, import once" : "Choose only the changes you want"}</strong><p>${result.build_is_blank
        ? "Work through locations, accessory relationships, guided systems, and custom entries here. The build stays blank until every line is resolved or intentionally left out, then one Import button applies the ready parts."
        : "Exact matches need no action. New and changed Estimate parts can be staged, while build-only parts stay unless you explicitly mark them for removal. Nothing changes until you press Apply decisions."}</p>${bulkCustomLines.length ? `<div class="qb-import-bulk-custom"><button type="button" class="btn btn-secondary btn-sm" data-qb-custom-stage-all>Add all ${bulkCustomLines.length} custom part${bulkCustomLines.length === 1 ? "" : "s"}</button><span>Uses the Estimate description, quantity, and price. Blank SKU/location remain finalization warnings.</span></div>` : ""}</div>
      <section class="qb-import-section"><h3>Parts to reconcile</h3>
        ${activeLines.length ? activeLines.map((line, index) => _ptQbImportLineHtml(line, index, parentOptions, session, accessoryContext)).join("") : `<p class="qb-import-empty">No material lines were found.</p>`}
      </section>
      ${!result.build_is_blank && (result.build_only_parts || []).length ? `<section class="qb-import-section"><h3>On build, not on Estimate</h3>
        <p class="qb-import-section-note">These stay on the build unless you explicitly remove them.</p>
        ${(result.build_only_parts || []).map(part => `<article class="qb-import-line qb-import-line--missing">
          <div class="qb-import-line-main"><div><strong>${esc(part.name)}</strong><p>${esc([part.part_number, part.location, `Qty ${part.quantity}`, part.supply_label].filter(Boolean).join(" · "))}</p></div><span class="qb-import-chip">Missing from Estimate</span></div>
          <div class="qb-import-line-action"><button type="button" class="btn btn-secondary btn-sm" data-qb-build-remove="${esc(part.line_id)}">${session.removals.has(part.line_id) ? "Keep on build" : "Remove when applying"}</button></div>
        </article>`).join("")}
      </section>` : ""}
      ${reuse.length || estimate.customer_memo || estimate.private_note ? `<section class="qb-import-section"><h3>Estimate memo / possible reused parts</h3>
        ${estimate.customer_memo ? `<div class="qb-import-memo"><strong>Customer memo</strong><p>${esc(estimate.customer_memo)}</p></div>` : ""}
        ${estimate.private_note ? `<div class="qb-import-memo"><strong>Private note</strong><p>${esc(estimate.private_note)}</p></div>` : ""}
        ${reuse.length ? `<div class="qb-import-reuse"><strong>Exact catalog SKUs mentioned but not quoted</strong>${reuse.map(item => `<span>${esc(item.part_number)} · ${esc(item.model || item.description)}</span>`).join("")}</div>` : ""}
      </section>` : ""}
      ${ignoredLines.length ? `<details class="qb-import-ignored"><summary>${ignoredLines.length} ignored Estimate line${ignoredLines.length === 1 ? "" : "s"}</summary>${ignoredLines.map(_ptQbImportLineHtml).join("")}</details>` : ""}`;
    const missingRequiredAccessories = _ptQbMissingRequiredParentAccessories(
      accessoryContext, session,
    );
    if (missingRequiredAccessories.length) {
      controls.body.querySelector(".qb-import-notice")?.insertAdjacentHTML(
        "afterend",
        `<div class="qb-est-change-alert"><strong>Required accessories still need a choice</strong><p>${missingRequiredAccessories.length} required accessory group${missingRequiredAccessories.length === 1 ? "" : "s"} must be attached before these parent parts can be imported.</p></div>`,
      );
    }
    controls.modal?.classList.remove("qb-import-refreshing");
    if (preservingReview && controls.modal) controls.modal.scrollTop = priorScrollTop;
    const pendingChangeCount = session.resolved.size + session.removals.size;
    const incompleteSplitPlans = [...session.splitPlans.entries()].filter(
      ([, plan]) => Number(plan?.placed) < Number(plan?.total),
    );
    const splitBlockedReason = incompleteSplitPlans.length
      ? `Finish assigning all locations for ${incompleteSplitPlans.length} split QB line${incompleteSplitPlans.length === 1 ? "" : "s"} before importing.`
      : "";
    controls.cancel.textContent = pendingChangeCount && !splitBlockedReason
      ? "Import ready parts & leave" : "Leave review…";
    const readyToApply = pendingChangeCount > 0
      && missingRequiredAccessories.length === 0
      && incompleteSplitPlans.length === 0
      && (!result.build_is_blank || unresolvedLines.length === 0);
    controls.create.style.display = pendingChangeCount ? "" : "none";
    controls.create.textContent = result.build_is_blank
      ? `Import ${session.resolved.size} ready part${session.resolved.size === 1 ? "" : "s"}`
      : `Apply ${pendingChangeCount} decision${pendingChangeCount === 1 ? "" : "s"}`;
    controls.create.disabled = !readyToApply;
    controls.create.title = missingRequiredAccessories.length
      ? `Choose ${missingRequiredAccessories.length} required accessory group${missingRequiredAccessories.length === 1 ? "" : "s"}`
      : splitBlockedReason
        ? splitBlockedReason
      : result.build_is_blank && unresolvedLines.length
        ? `Resolve or leave out ${unresolvedLines.length} remaining line${unresolvedLines.length === 1 ? "" : "s"}` : "";
    const openEstimateLine = async (
      button, index, accessoryRelation = null, matchOverride = null, options = {},
    ) => {
        const line = activeLines[index];
        const match = matchOverride || line?.catalog_matches?.[0];
        const groupedLines = options.groupedLines || [];
        const project = _PT.projects.find(item => item.project_id === projectId) || _PT.viewProject;
        const unit = (project?.build_units || []).find(item =>
          (item.individuals || []).some(individual => individual.individual_id === individualId)
        );
        const individual = (unit?.individuals || []).find(item => item.individual_id === individualId);
        if (!line || !match || !unit || !individual?.draft_id) {
          toast("This vehicle build is no longer available", "error");
          return;
        }
        button.disabled = true;
        try {
          if (!options.preserveExisting) {
            const reservedParent = session.stagedParents.get(line.line_id);
            _ptQbClearStagedLine(session, line.line_id, { preserveReservedDependents: true });
            if (reservedParent?.reserved) session.stagedParents.set(line.line_id, reservedParent);
            for (const groupedLine of groupedLines) {
              _ptQbClearStagedLine(session, groupedLine.line_id, { preserveReservedDependents: true });
              session.groupOwners.set(groupedLine.line_id, line.line_id);
            }
          } else {
            session.stagedParents.set(line.line_id, {
              line_id: _ptQbReservedLineId(), source_line_id: line.line_id,
              name: match.model || match.part_number || "Quoted part",
              location: "Will be imported", part_number: match.part_number || "",
              product_ids: [match.product_id].filter(Boolean), reserved: true,
            });
          }
          if (["quantity_changed", "supply_changed"].includes(line.comparison?.status)) {
            const replacements = new Set(line.comparison.matching_manifest_line_ids || []);
            session.replacements.set(line.line_id, replacements);
          }
          await _ptShowBuildEditor(individual.draft_id, unit, project, "overview", individual);
          await window.pickerOpenEstimateLine({
            ...line,
            quantity: options.quantityOverride || line.quantity,
            catalog_match: match,
            guided_kinds: match.guided_kinds || line.guided_kinds || [],
            estimate_id: estimate.id,
            estimate_number: estimate.number,
            stage_session_id: sessionId,
            guided_estimate_components: line.guided_estimate_components || [],
            grouped_estimate_lines: groupedLines.map(groupedLine => ({
              ...groupedLine,
              catalog_match: (groupedLine.catalog_matches || [])[0],
            })),
            partial_placement: options.partialPlacement || null,
            accessory_relation: accessoryRelation,
            return_to_import: { project_id: projectId, individual_id: individualId },
          });
        } catch (error) {
          button.disabled = false;
          toast(error?.message || "The Part Picker could not be opened", "error");
        }
    };
    controls.body.querySelectorAll("[data-qb-import-index]").forEach(button => {
      button.addEventListener("click", async () => {
        const index = Number(button.dataset.qbImportIndex);
        const line = activeLines[index];
        const groupedLines = (line?.grouped_line_ids || [])
          .map(lineId => activeLines.find(candidate => candidate.line_id === lineId))
          .filter(Boolean);
        await openEstimateLine(button, index, null, null, { groupedLines });
      });
    });
    controls.body.querySelectorAll("[data-qb-group-place]").forEach(button => {
      const index = Number(button.dataset.qbGroupPlace);
      const choices = [...controls.body.querySelectorAll(`[data-qb-group-choice="${index}"]`)];
      const refresh = () => {
        button.disabled = !choices.some(choice => choice.checked);
      };
      choices.forEach(choice => choice.addEventListener("change", refresh));
      refresh();
      button.addEventListener("click", async () => {
        const selectedLines = choices
          .filter(choice => choice.checked)
          .map(choice => activeLines.find(line => line.line_id === choice.value))
          .filter(Boolean);
        if (!selectedLines.length) return;
        const primary = activeLines[index];
        const primaryMatch = (primary?.catalog_matches || [])[0];
        const preparedLines = selectedLines.map(line => {
          if (line.classification === "catalog_part") return { line, conversion: null };
          const conversion = (line.catalog_suggestions || []).find(
            suggestion => suggestion.product_id === primaryMatch?.product_id,
          );
          if (!conversion) return null;
          return { line, conversion };
        }).filter(Boolean);
        if (preparedLines.length !== selectedLines.length) {
          toast("One of those QB lines no longer has a compatible catalog match", "error");
          return;
        }
        const groupedLines = preparedLines.map(({ line, conversion }) => conversion ? {
          ...line,
          classification: "catalog_part",
          catalog_matches: [conversion],
          catalog_suggestions: [],
          ambiguous_match: false,
          converted_from_custom: true,
          original_classification: line.classification,
        } : line);
        const totalQuantity = [primary, ...groupedLines]
          .reduce((sum, line) => sum + Math.max(1, Number(line?.quantity) || 1), 0);
        if (totalQuantity > 12) {
          toast("A grouped light placement is limited to 12 heads; group fewer QB lines or split them first", "error");
          return;
        }
        for (const { line, conversion } of preparedLines) {
          if (conversion) session.catalogConversions.set(line.line_id, conversion);
        }
        button.disabled = true;
        button.innerHTML = `<span class="qb-import-inline-spinner" aria-hidden="true"></span>Combining…`;
        _ptQbClearStagedLine(session, primary.line_id, { preserveReservedDependents: true });
        for (const groupedLine of groupedLines) {
          _ptQbClearStagedLine(session, groupedLine.line_id, { preserveReservedDependents: true });
          session.groupOwners.set(groupedLine.line_id, primary.line_id);
        }
        await window.PT_previewQbEstimateImport(projectId, individualId, {
          resultOverride: result,
        });
        toast("QB lines combined; choose their shared placement when ready", "success");
      });
    });
    controls.body.querySelectorAll("[data-qb-group-undo]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbGroupUndo)];
        if (!line) return;
        _ptQbClearStagedLine(session, line.line_id);
        await window.PT_previewQbEstimateImport(projectId, individualId, {
          resultOverride: result,
        });
      });
    });
    controls.body.querySelectorAll("[data-qb-split-start]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbSplitStart)];
        const total = Number(line?.quantity);
        if (!line || !Number.isInteger(total) || total < 2) return;
        session.splitPlans.set(line.line_id, { total, placed: 0 });
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-split-place]").forEach(button => {
      button.addEventListener("click", async () => {
        const index = Number(button.dataset.qbSplitPlace);
        const line = activeLines[index];
        const plan = line ? session.splitPlans.get(line.line_id) : null;
        const remaining = plan ? Math.max(0, plan.total - plan.placed) : 0;
        const quantityInput = controls.body.querySelector(`[data-qb-split-qty="${index}"]`);
        const quantity = Number(quantityInput?.value);
        const maximum = Math.max(1, Number(quantityInput?.max) || remaining);
        if (!plan || !Number.isInteger(quantity) || quantity < 1 || quantity > maximum) {
          toast(`Enter a whole quantity from 1 to ${maximum}`, "error");
          return;
        }
        await openEstimateLine(button, index, null, null, {
          preserveExisting: true,
          quantityOverride: quantity,
          partialPlacement: { quantity, totalQuantity: plan.total },
        });
      });
    });
    controls.body.querySelectorAll("[data-qb-split-cancel]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbSplitCancel)];
        if (!line) return;
        _ptQbClearStagedLine(session, line.line_id);
        session.splitPlans.delete(line.line_id);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-use-catalog-suggestion]").forEach(button => {
      button.addEventListener("click", async () => {
        const [lineIndexText, suggestionIndexText] = String(
          button.dataset.qbUseCatalogSuggestion || "",
        ).split(":");
        const lineIndex = Number(lineIndexText);
        const suggestionIndex = Number(suggestionIndexText);
        const line = activeLines[lineIndex];
        const suggestion = line?.catalog_suggestions?.[suggestionIndex];
        if (!suggestion) {
          toast("That catalog suggestion is no longer available", "error");
          return;
        }
        button.disabled = true;
        button.innerHTML = `<span class="qb-import-inline-spinner" aria-hidden="true"></span>Converting…`;
        session.catalogConversions.set(line.line_id, suggestion);
        session.skipped.delete(line.line_id);
        await window.PT_previewQbEstimateImport(projectId, individualId, {
          resultOverride: result,
        });
        toast(`${suggestion.part_number} is now a connected part; choose its placement when ready`, "success");
      });
    });
    controls.body.querySelectorAll("[data-qb-conversion-undo]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbConversionUndo)];
        if (!line) return;
        _ptQbClearStagedLine(session, line.line_id);
        session.catalogConversions.delete(line.line_id);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-import-skip]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbImportSkip)];
        if (!line) return;
        const restoring = session.skipped.has(line.line_id);
        button.disabled = true;
        button.innerHTML = `<span class="qb-import-inline-spinner" aria-hidden="true"></span>${restoring ? "Restoring…" : "Leaving out…"}`;
        if (restoring) session.skipped.delete(line.line_id);
        else {
          _ptQbClearStagedLine(session, line.line_id);
          session.skipped.add(line.line_id);
        }
        await window.PT_previewQbEstimateImport(projectId, individualId, {
          resultOverride: result,
        });
      });
    });
    controls.body.querySelectorAll("[data-qb-import-undo]").forEach(button => {
      button.addEventListener("click", async () => {
        const line = activeLines[Number(button.dataset.qbImportUndo)];
        if (!line) return;
        _ptQbClearStagedLine(session, line.line_id);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-parent-accessory-select]").forEach(select => {
      const menuId = select.dataset.qbParentAccessorySelect;
      const quantityInput = [...controls.body.querySelectorAll("[data-qb-parent-accessory-qty]")]
        .find(item => item.dataset.qbParentAccessoryQty === menuId);
      const supplySelect = [...controls.body.querySelectorAll("[data-qb-parent-accessory-supply]")]
        .find(item => item.dataset.qbParentAccessorySupply === menuId);
      const sourceWrap = [...controls.body.querySelectorAll("[data-qb-parent-accessory-source-wrap]")]
        .find(item => item.dataset.qbParentAccessorySourceWrap === menuId);
      const addButton = [...controls.body.querySelectorAll("[data-qb-parent-accessory-add]")]
        .find(item => item.dataset.qbParentAccessoryAdd === menuId);
      const refresh = (resetQuantity = false) => {
        const menu = accessoryContext.menus.get(menuId);
        const option = select.value === "" ? null : menu?.options?.[Number(select.value)];
        if (option && quantityInput && resetQuantity) quantityInput.value = String(option.quantity || 1);
        if (quantityInput) quantityInput.disabled = !option || Boolean(option?.status?.quotedLine);
        if (supplySelect) {
          if (option?.status?.quotedLine) supplySelect.value = "new";
          supplySelect.disabled = !option || Boolean(option?.status?.quotedLine);
        }
        if (sourceWrap) sourceWrap.hidden = !option || supplySelect?.value !== "customer_used";
        if (addButton) addButton.disabled = !option || option.status.disabled || !menu?.target;
      };
      select.addEventListener("change", () => refresh(true));
      supplySelect?.addEventListener("change", () => refresh(false));
      refresh();
    });
    controls.body.querySelectorAll("[data-qb-parent-accessory-add]").forEach(button => {
      button.addEventListener("click", async () => {
        const menuId = button.dataset.qbParentAccessoryAdd;
        const menu = accessoryContext.menus.get(menuId);
        const select = [...controls.body.querySelectorAll("[data-qb-parent-accessory-select]")]
          .find(item => item.dataset.qbParentAccessorySelect === menuId);
        const quantityInput = [...controls.body.querySelectorAll("[data-qb-parent-accessory-qty]")]
          .find(item => item.dataset.qbParentAccessoryQty === menuId);
        const supplySelect = [...controls.body.querySelectorAll("[data-qb-parent-accessory-supply]")]
          .find(item => item.dataset.qbParentAccessorySupply === menuId);
        const sourceInput = [...controls.body.querySelectorAll("[data-qb-parent-accessory-source]")]
          .find(item => item.dataset.qbParentAccessorySource === menuId);
        const option = !select || select.value === "" ? null : menu?.options?.[Number(select.value)];
        const quantity = Number(quantityInput?.value);
        if (!menu?.target || !option || option.status.disabled) return;
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > 999) {
          toast("Accessory quantity must be a whole number from 1 to 999", "error");
          return;
        }
        if (supplySelect?.value === "customer_used" && !sourceInput?.value.trim()) {
          toast("Enter where the customer-supplied used accessory will come from", "error");
          sourceInput?.focus();
          return;
        }
        button.disabled = true;
        if (option.status.quotedLine) {
          const quotedLine = option.status.quotedLine;
          const quotedMatch = (quotedLine.catalog_matches || [])[0];
          _ptQbStageMatchedAccessory(session, quotedLine, quotedMatch, {
            parent_line_id: menu.target.line_id,
            parent_name: menu.target.name,
            parent_location: menu.target.location || "",
            parent_product_id: menu.match.product_id || "",
            accessory_category: option.category || quotedMatch?.accessory_category || "other",
          }, estimate);
          session.parentAccessoryRestoredSkips.add(quotedLine.line_id);
        } else {
          _ptQbStageMissingParentAccessory(
            session, menu, option, quantity, estimate,
            supplySelect?.value || "new", sourceInput?.value.trim() || "",
          );
        }
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-parent-accessory-remove]").forEach(button => {
      button.addEventListener("click", async () => {
        const sourceLineId = button.dataset.qbParentAccessoryRemove;
        const restoreSkip = session.parentAccessoryRestoredSkips.has(sourceLineId);
        _ptQbClearStagedLine(session, sourceLineId);
        session.parentAccessoryRestoredSkips.delete(sourceLineId);
        if (restoreSkip) session.skipped.add(sourceLineId);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelector("[data-qb-custom-stage-all]")?.addEventListener("click", async event => {
      const button = event.currentTarget;
      button.disabled = true;
      let stagedCount = 0;
      let editedCount = 0;
      for (const line of bulkCustomLines) {
        const index = activeLines.indexOf(line);
        const defaults = _ptQbCustomLineDefaults(line);
        const sku = controls.body.querySelector(`[data-qb-custom-sku="${index}"]`)?.value.trim() ?? defaults.sku;
        const description = controls.body.querySelector(`[data-qb-custom-description="${index}"]`)?.value.trim() ?? defaults.description;
        const location = controls.body.querySelector(`[data-qb-custom-location="${index}"]`)?.value.trim() ?? "";
        const quantityValue = controls.body.querySelector(`[data-qb-custom-quantity="${index}"]`)?.value ?? String(defaults.quantity);
        const priceValue = controls.body.querySelector(`[data-qb-custom-price="${index}"]`)?.value.trim() ?? defaults.formPrice;
        const renderAsLight = controls.body.querySelector(`[data-qb-custom-render-light="${index}"]`)?.checked === true;
        const wasEdited = sku !== defaults.sku
          || description !== defaults.description
          || location !== ""
          || quantityValue !== String(defaults.quantity)
          || priceValue !== defaults.formPrice
          || renderAsLight;
        if (wasEdited) {
          editedCount += 1;
          continue;
        }
        _ptQbStageCustomEstimateLine(session, line, estimate, defaults);
        stagedCount += 1;
      }
      if (!stagedCount) {
        button.disabled = false;
        toast(editedCount
          ? "No untouched custom parts remain; finish the edited entries individually"
          : "No custom parts are ready for bulk addition", "info");
        return;
      }
      await window.PT_previewQbEstimateImport(projectId, individualId);
      toast(`${stagedCount} custom part${stagedCount === 1 ? "" : "s"} ready for import${editedCount ? ` · ${editedCount} edited entr${editedCount === 1 ? "y was" : "ies were"} left for individual review` : ""}`, "success");
    });
    controls.body.querySelectorAll("[data-qb-custom-stage]").forEach(button => {
      button.addEventListener("click", async () => {
        const index = Number(button.dataset.qbCustomStage);
        const line = activeLines[index];
        const sku = controls.body.querySelector(`[data-qb-custom-sku="${index}"]`)?.value.trim();
        const description = controls.body.querySelector(`[data-qb-custom-description="${index}"]`)?.value.trim();
        const location = controls.body.querySelector(`[data-qb-custom-location="${index}"]`)?.value.trim();
        const quantity = Number(controls.body.querySelector(`[data-qb-custom-quantity="${index}"]`)?.value);
        const rawPrice = controls.body.querySelector(`[data-qb-custom-price="${index}"]`)?.value.trim() || "";
        const unitPrice = Number(rawPrice);
        if (!description || !Number.isInteger(quantity) || quantity < 1 || quantity > 999
            || !rawPrice || !Number.isFinite(unitPrice) || unitPrice < 0) {
          toast("Enter a description, quantity from 1 to 999, and valid unit price", "error");
          return;
        }
        const renderAsLight = controls.body.querySelector(
          `[data-qb-custom-render-light="${index}"]`,
        )?.checked === true;
        if (renderAsLight) {
          if (quantity > 12) {
            toast("Rendered custom lights are limited to 12 heads per line", "error");
            return;
          }
          if (typeof window.pickerOpenCustomEstimateLine !== "function") {
            toast("The custom light editor is unavailable", "error");
            return;
          }
          button.disabled = true;
          await window.pickerOpenCustomEstimateLine({
            values: { sku, description, location, unitPrice, quantity },
            estimate_id: estimate.id,
            estimate_number: estimate.number,
            line_id: line.line_id,
            item_id: line.item_id,
            description: line.description,
            amount: line.amount,
            stage_session_id: sessionId,
            return_to_import: { project_id: projectId, individual_id: individualId },
          });
          return;
        }
        if (!sku || !location) {
          toast("This custom part will import with a warning and must be completed before finalizing", "warn");
        }
        _ptQbStageCustomEstimateLine(session, line, estimate, {
          sku, description, location, unitPrice, quantity,
        });
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-build-remove]").forEach(button => {
      button.addEventListener("click", async () => {
        const lineId = button.dataset.qbBuildRemove;
        if (session.removals.has(lineId)) session.removals.delete(lineId);
        else session.removals.add(lineId);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    controls.body.querySelectorAll("[data-qb-accessory-parent]").forEach(select => {
      const index = Number(select.dataset.qbAccessoryParent);
      const button = controls.body.querySelector(`[data-qb-accessory-add="${index}"]`);
      const locationLabel = controls.body.querySelector(`[data-qb-accessory-standalone-location="${index}"]`);
      const locationInput = controls.body.querySelector(`[data-qb-accessory-location="${index}"]`);
      const refresh = () => {
        const standalone = select.value === "standalone";
        if (locationLabel) locationLabel.hidden = !standalone;
        if (button) button.disabled = !select.value || (standalone && !locationInput?.value.trim());
      };
      select.addEventListener("change", refresh);
      locationInput?.addEventListener("input", refresh);
      refresh();
    });
    controls.body.querySelectorAll("[data-qb-accessory-add]").forEach(button => {
      button.addEventListener("click", async () => {
        const index = Number(button.dataset.qbAccessoryAdd);
        const select = controls.body.querySelector(`[data-qb-accessory-parent="${index}"]`);
        const choice = select?.value || "";
        if (!choice) return;
        const line = activeLines[index];
        const match = line?.catalog_matches?.[0];
        let relation = null;
        if (choice !== "standalone") {
          const parent = parentOptions.find(row => row.line_id === choice);
          if (!parent) {
            toast("That parent is no longer available", "error");
            return;
          }
          const candidate = (match?.accessory_parent_candidates || []).find(item =>
            (item.manifest_options || []).some(row => row.line_id === choice)
          );
          relation = {
            parent_line_id: parent.line_id,
            parent_name: parent.name,
            parent_location: parent.location || "",
            parent_product_id: candidate?.product_id || parent.product_ids?.[0] || "",
            accessory_category: match?.accessory_category || "other",
          };
        } else {
          const location = controls.body.querySelector(`[data-qb-accessory-location="${index}"]`)?.value.trim() || "";
          if (!location) {
            toast("Enter where the standalone part goes", "error");
            return;
          }
          relation = {
            parent_line_id: "", parent_name: "", parent_location: location,
            parent_product_id: "", accessory_category: "",
          };
        }
        button.disabled = true;
        _ptQbStageMatchedAccessory(session, line, match, relation, estimate);
        await window.PT_previewQbEstimateImport(projectId, individualId);
      });
    });
    const applyReadyParts = async ({ closeAfter = false } = {}) => {
      if (incompleteSplitPlans.length) {
        toast(splitBlockedReason, "error");
        return false;
      }
      if (missingRequiredAccessories.length) {
        toast("Choose the required accessories before importing these parent parts", "error");
        return false;
      }
      if (!session.operations.length && !session.removals.size) {
        toast("No ready Estimate parts have been selected", "info");
        return false;
      }
      controls.create.disabled = true;
      controls.create.textContent = result.build_is_blank ? "Importing…" : "Applying…";
      try {
        for (const lineId of [...session.removals]) {
          const response = await api(`/api/draft/${session.draftId}/part/${lineId}/delete`, {});
          if (!response?.ok) throw new Error(response?.error || "A selected build part could not be removed");
          session.removals.delete(lineId);
        }
        const orderedOperations = [...session.operations].sort((left, right) => {
          const leftIsChild = Boolean(left.body?.parent_line_id);
          const rightIsChild = Boolean(right.body?.parent_line_id);
          return Number(leftIsChild) - Number(rightIsChild);
        });
        for (const operation of orderedOperations) {
          const response = await api(operation.path, operation.body);
          if (!response?.ok) throw new Error(response?.error || "A staged Estimate part could not be imported");
          session.operations.splice(session.operations.indexOf(operation), 1);
        }
        _ptQbImportSessions.delete(sessionId);
        if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
        if (typeof loadDraftManifest === "function") await loadDraftManifest(session.draftId);
        if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") {
          await pvLoad(session.draftId);
        }
        toast(result.build_is_blank ? "Estimate parts imported" : "Estimate decisions applied", "success");
        _ptQbCloseLeavePrompt();
        if (closeAfter) {
          controls.modal?.classList.remove("open");
          _PT.qbEstCloseHandler = null;
          _PT.qbEstCancelHandler = null;
        } else {
          await window.PT_previewQbEstimateImport(projectId, individualId);
        }
        return true;
      } catch (error) {
        controls.create.disabled = false;
        controls.create.textContent = result.build_is_blank ? "Continue import" : "Continue applying";
        toast(error?.message || "The Estimate decisions could not be applied", "error");
        return false;
      }
    };
    controls.create.onclick = async () => {
      if (controls.create.disabled) return;
      await applyReadyParts();
    };
    const closeReview = () => {
      controls.modal?.classList.remove("open");
      _ptQbCloseLeavePrompt();
      _PT.qbEstCloseHandler = null;
      _PT.qbEstCancelHandler = null;
    };
    const showLeaveWarning = () => {
      _ptQbOpenLeavePrompt({
        readyCount: pendingChangeCount,
        importBlockedReason: splitBlockedReason,
        onDiscard: () => {
          _ptQbImportSessions.delete(sessionId);
          closeReview();
          toast("Estimate import decisions discarded", "info");
        },
        onSave: () => {
          closeReview();
          toast("Estimate import decisions saved for later", "info");
        },
        onImport: async () => { await applyReadyParts({ closeAfter: true }); },
      });
    };
    const hasUnappliedReview = Boolean(
      outstandingLines.length || session.operations.length
      || session.removals.size || session.skipped.size,
    );
    _PT.qbEstCloseHandler = hasUnappliedReview ? showLeaveWarning : closeReview;
    _PT.qbEstCancelHandler = async () => {
      if ((session.operations.length || session.removals.size) && !splitBlockedReason) {
        await applyReadyParts({ closeAfter: true });
      } else if (!hasUnappliedReview) {
        closeReview();
      } else {
        showLeaveWarning();
      }
    };
  } catch (error) {
    controls.modal?.classList.remove("qb-import-refreshing");
    if (preservingReview) {
      toast(error?.message || "The Estimate could not be refreshed", "error");
    } else {
      controls.body.innerHTML = `<div class="qb-est-change-alert"><strong>Could not prepare the import</strong><p>${esc(error?.message || "The Estimate could not be read.")}</p></div>`;
    }
  }
};

window.PT_buildCreateEstimate = async function (projectId, unitId, individualId) {
  if (!individualId) { toast("Estimates are created per individual unit", "error"); return; }
  if (!unitId) {
    const project = _PT.projects.find(p => p.project_id === projectId) || _PT.viewProject;
    unitId = (project?.build_units || []).find(unit =>
      (unit.individuals || []).some(individual => individual.individual_id === individualId)
    )?.unit_id || "";
  }
  if (!(await _ptQbConnected())) {
    toast("Connect QuickBooks first (Settings → QuickBooks)", "error");
    return;
  }
  toast("Refreshing prices and checking parts against QuickBooks…");
  let v;
  try {
    v = await api("/api/quickbooks/estimates/validate",
      { project_id: projectId, individual_id: individualId });
  } catch (e) { toast("Estimate not created — QuickBooks validation could not be completed", "error"); return; }
  if (!v?.ok) { toast(_ptEstError(v?.error), "error"); return; }

  if (!v.project?.ready) {
    _ptToastEstimateBlockers(v);
    _ptOpenProjectBindingModal(projectId, individualId, v.project, null, v);
    return;
  }

  if (!v.can_create) {
    const editableChargeReasons = new Set(["labor_amount_required", "install_supplies_amount_required"]);
    const probs = (v.problems || []).filter(problem => !editableChargeReasons.has(problem.reason));
    if (!probs.length && Number(v.material_line_count || 0) > 0) {
      // Labor and supplies are intentionally editable in the review below.
    } else {
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

  try {
    const isUpdate = !!v.existing_estimate_id;
    _ptOpenEstModal(isUpdate ? "Update connected QuickBooks estimate" : "Create new QuickBooks estimate",
      `<p style="font-size:13px;margin:0 0 14px">${isUpdate
        ? `This is a QuickBooks write: Vehicle Builder will replace the reviewed fields and lines on connected Estimate <strong>${esc(v.existing_estimate_id)}</strong> only after you explicitly choose Update below.`
        : "Creates a <strong>non-posting estimate</strong> under the agency's top-level customer and this vehicle's real QuickBooks Project. No sub-customer is created."}</p>
     ${_ptEstimatePricingSummary(v.pricing)}
     ${_ptEstimatePricingControls(v.pricing)}
     ${_ptAdditionalChargesHtml(v.additional_charges)}
     ${_ptBankTransferEstimateNote()}
     <div style="display:flex;gap:24px;font-size:13px;margin-bottom:14px">
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Line items</div><div id="qb-est-line-count" style="font-weight:700;color:var(--navy);font-size:18px">${v.line_count}</div></div>
       <div><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Estimated total</div><div id="qb-est-estimated-total" style="font-weight:700;color:var(--navy);font-size:18px">${_ptMoney2(v.total)}</div></div>
     </div>
     ${v.existing_estimate_id ? _ptEstimateChangeHtml(v.existing_estimate_id, v.estimate_change) : ""}
     ${v.pdf_available
       ? `<label class="qb-est-pdf-option"><input type="checkbox" id="qb-est-attach-pdf" checked disabled> Build PDF will be attached: <strong>${esc(v.pdf_name || "build.pdf")}</strong></label>`
       : `<div class="qb-est-pdf-required"><strong>A build PDF is required.</strong><p>Create it now so Vehicle Builder can attach it to the Estimate. Exporting may take several seconds.</p><button type="button" class="btn btn-primary" id="qb-est-export-pdf">Create build PDF</button><div id="qb-est-pdf-progress" class="qb-est-pdf-progress" hidden></div></div>`}
     <label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks customer</label>
     ${_ptCustomerEditor(customer, customerLinked, customerMissing)}
     <label style="font-size:12px;font-weight:600;color:var(--navy)">Memo (optional)</label>
       <input type="text" id="qb-est-memo" placeholder="Appears on the estimate" autocomplete="off" style="width:100%;box-sizing:border-box;margin-top:5px" />`,
      v.pdf_available && customerLinked && !customerMissing.length
        ? (v.existing_estimate_id ? "Continue" : "Create estimate")
        : v.pdf_available ? (customerLinked ? "Update customer & estimate" : "Create customer & estimate") : "");
    const e = _ptEstModalEls();
    _ptWireCustomerTaxStatus();
    _ptWireEstimatePricing(v.pricing, v.additional_charges, v.material_line_count);
    _ptWireEstimateChangeChoice(e.create);
    if (e.create) e.create.onclick = () => _ptDoCreateEstimate(projectId, individualId);
    $("qb-est-export-pdf")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const progress = $("qb-est-pdf-progress");
      button.disabled = true;
      button.textContent = "Creating PDF…";
      if (progress) {
        progress.hidden = false;
        _ptSetStatus(progress, "Creating the PowerPoint and PDF… please wait", "loading");
      }
      const exported = await window.PT_buildExportPdf(
        projectId, unitId, individualId, "ind", { openAfter: false, statusEl: progress }
      );
      if (!exported) {
        button.disabled = false;
        button.textContent = "Try creating the build PDF again";
        return;
      }
      if (progress) _ptSetStatus(progress, "✅ PDF ready — refreshing estimate review…", "good");
      await window.PT_buildCreateEstimate(projectId, unitId, individualId);
    });
  } catch (error) {
    console.error("Could not render QuickBooks estimate review", error);
    toast("Could not open the estimate review: " + (error?.message || "unknown display error"), "error");
  }
};

async function _ptDoCreateEstimate(projectId, individualId, chosenAction = null, chosenAttachPdf = null, chosenPricing = null, chosenOverwrite = null, chosenAdditionalCharges = null) {
  const e = _ptEstModalEls();
  const memo = $("qb-est-memo")?.value || "";
  const customerFields = _ptCustomerFieldsFromEditor();
  const customerConfirmed = !!$("qb-est-customer-confirm")?.checked;
  const existingAction = chosenAction ?? document.querySelector('input[name="qb-est-existing-action"]:checked')?.value ?? "";
  if (document.querySelector(".qb-est-existing-choice") && !existingAction) {
    toast("Choose whether to overwrite the existing QuickBooks estimate or create a separate one", "error");
    return;
  }
  const overwriteQbChanges = chosenOverwrite ?? (
    existingAction === "update"
    && document.querySelector(".qb-est-existing-choice")?.dataset.needsChoice === "true"
  );
  const attachPdf = chosenAttachPdf ?? !!$("qb-est-attach-pdf")?.checked;
  const estimatePricing = chosenPricing || _ptReadEstimatePricing();
  const estimateCharges = chosenAdditionalCharges || _ptReadAdditionalCharges();
  if (estimatePricing.mode === "custom" && Object.values(estimatePricing.custom).some(
    value => !Number.isFinite(value) || value < 0 || value > 100
  )) {
    toast("Every custom discount must be from 0% through 100%", "error");
    return;
  }
  if (estimateCharges && (!Number.isFinite(estimateCharges.labor_amount) || estimateCharges.labor_amount <= 0)) {
    toast("Enter the total installation labor charge before creating the estimate", "error");
    $("qb-est-labor-amount")?.focus();
    return;
  }
  if (estimateCharges && (!Number.isFinite(estimateCharges.install_supplies_amount) || estimateCharges.install_supplies_amount <= 0)) {
    toast("Enter the DTM install supplies charge before creating the estimate", "error");
    $("qb-est-supplies-amount")?.focus();
    return;
  }
  if (estimateCharges && (!Number.isFinite(estimateCharges.delivery_amount) || estimateCharges.delivery_amount < 0)) {
    toast("Enter a valid delivery fee", "error");
    $("qb-est-delivery-amount")?.focus();
    return;
  }
  if (e.create) { e.create.disabled = true; e.create.textContent = "Creating…"; }
  try {
    const res = await api("/api/quickbooks/estimates/create",
      { project_id: projectId, individual_id: individualId, memo,
        customer_confirmed: customerConfirmed, customer_fields: customerFields,
        existing_action: existingAction, attach_pdf: attachPdf,
        overwrite_qb_changes: overwriteQbChanges,
        pricing_mode: estimatePricing.mode, custom_pricing: estimatePricing.custom,
        additional_charges: estimateCharges });
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
        e.body.innerHTML = `<p style="font-size:13px;margin:0 0 10px">${res.customer_linked ? "This QuickBooks customer needs an update before the estimate can be created." : "Before this estimate is created, confirm the customer information below. The app will reuse an exact top-level QB customer when one exists, or create a new top-level customer."}</p>
          <label style="font-size:12px;font-weight:600;color:var(--navy)">QuickBooks customer</label>
          ${_ptCustomerEditor(res.customer, !!res.customer_linked, missing)}
          <label style="font-size:12px;font-weight:600;color:var(--navy)">Memo (optional)</label>
          <input type="text" id="qb-est-memo" placeholder="Appears on the estimate" autocomplete="off" style="width:100%;box-sizing:border-box;margin-top:5px" />`;
        _ptWireCustomerTaxStatus();
        e.create.disabled = false;
        e.create.textContent = "Create customer & estimate";
        e.create.onclick = () => _ptDoCreateEstimate(
          projectId, individualId, existingAction, attachPdf, estimatePricing, overwriteQbChanges,
          estimateCharges
        );
      } else if (res?.error === "invalid_qb_project_ref") {
        toast(_ptEstError(res.error), "error");
        _ptOpenProjectBindingModal(projectId, individualId, res.project);
      } else if (["existing_estimate_modified", "existing_estimate_change_unverified"].includes(res?.error)) {
        toast(_ptEstError(res.error) + " — review the differences before continuing", "error");
        e.body.querySelector(".qb-est-existing-choice")?.remove();
        e.body.insertAdjacentHTML("afterbegin", _ptEstimateChangeHtml(
          res.existing_estimate_id || "", res.estimate_change || { status: "modified" }
        ));
        if (e.create) {
          e.create.disabled = false;
          e.create.onclick = () => _ptDoCreateEstimate(
            projectId, individualId, null, attachPdf, estimatePricing, true,
            estimateCharges
          );
          _ptWireEstimateChangeChoice(e.create);
        }
      } else {
        toast(_ptEstimateFailureText(res), "error");
        if (e.create) { e.create.disabled = false; e.create.textContent = "Try again"; }
      }
    }
  } catch (err) {
    toast("Estimate creation failed: " + (err?.message || "the request did not complete"), "error");
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
    const problems = v.problems || [];
    if (problems.some(problem => ["labor_amount_required", "install_supplies_amount_required"].includes(problem.reason))) {
      return "Set this build preset's labor and supplies in Settings → Projects";
    }
    if (problems.some(problem => problem.reason === "additional_charge_item_missing")) {
      return "A required QuickBooks Additional charges item is missing";
    }
    const count = problems.length;
    return count ? `${count} part${count === 1 ? "" : "s"} need attention` : "Build needs attention";
  }
  if (!v.pdf_available) return "Build PDF must be created and attached";
  return "Needs attention";
}

async function _ptOpenBatchEstimateSetup(project) {
  const targets = _ptBatchEstimateTargets(project);
  if (!targets.length) { toast("No configured individual vehicles to estimate", "error"); return; }

  _ptOpenEstModal("Checking batch QuickBooks estimates",
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
    return v.ok && v.can_create && v.project?.ready && v.pdf_available;
  });
  const attention = checks.filter((check) => !ready.includes(check));
  const missingPdfs = checks.filter((check) => {
    const v = check.validation || {};
    return v.ok && v.can_create && v.project?.ready && !v.pdf_available;
  });
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
  const pdfStatus = missingPdfs.length
    ? `<div class="qb-est-pdf-required"><strong>${missingPdfs.length} build PDF${missingPdfs.length === 1 ? " is" : "s are"} required.</strong><p>Create ${missingPdfs.length === 1 ? "it" : "them"} now so every Estimate can include its build attachment. This can take several seconds per build.</p><button type="button" class="btn btn-primary" data-qb-batch-export-pdfs>Create missing PDF${missingPdfs.length === 1 ? "" : "s"}</button><div id="qb-est-batch-pdf-progress" class="qb-est-pdf-progress" hidden></div></div>`
    : `<div class="qb-est-pdf-ready">✓ Every ready build has a PDF attachment.</div>`;
  const batchListTotal = ready.reduce((sum, check) => sum + Number(check.validation?.pricing?.list_total || 0), 0);
  const batchCustomerTotal = ready.reduce((sum, check) => sum + Number(check.validation?.pricing?.customer_total || 0), 0);
  const batchAdditionalTotal = ready.reduce((sum, check) => sum + Number(check.validation?.additional_charges?.additional_total || 0), 0);
  const batchEstimateTotal = ready.reduce((sum, check) => sum + Number(check.validation?.total || 0), 0);
  const batchPricing = ready.length ? {
    rule_name: "Retail",
    source: "retail",
    list_total: batchListTotal,
    customer_total: batchCustomerTotal,
    savings: batchListTotal - batchCustomerTotal,
    applied_discounts: [],
  } : null;

  _ptOpenEstModal("Prepare batch QuickBooks estimates",
    `<p style="font-size:13px;margin:0 0 12px">Each vehicle gets its own non-posting QuickBooks estimate with its build PDF attached. Nothing is created until you choose <strong>Create estimates</strong>.</p>${customerStatus}${pdfStatus}${_ptEstimatePricingSummary(batchPricing)}${ready.length ? `<div class="qb-est-charge-totals"><span>Additional charges <strong>${_ptMoney2(batchAdditionalTotal)}</strong></span><span>Batch estimate total <strong>${_ptMoney2(batchEstimateTotal)}</strong></span></div>` : ""}${_ptBankTransferEstimateNote()}
     <div style="display:flex;gap:12px;margin-bottom:12px"><div style="flex:1;padding:10px;border:1px solid #86c99a;border-radius:6px"><div style="font-size:11px;color:var(--muted);text-transform:uppercase">Ready to create</div><strong style="font-size:20px;color:var(--green)">${ready.length}</strong></div><div style="flex:1;padding:10px;border:1px solid var(--border);border-radius:6px"><div style="font-size:11px;color:var(--muted);text-transform:uppercase">Still needs setup</div><strong style="font-size:20px;color:var(--navy)">${attention.length}</strong></div></div>
     <div style="font-size:12px;font-weight:700;color:var(--navy);margin:0 0 4px">Ready vehicles</div><div style="max-height:140px;overflow:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:12px">${readyRows}</div>
     <div style="font-size:12px;font-weight:700;color:var(--navy);margin:0 0 4px">Vehicles needing attention</div><div style="max-height:220px;overflow:auto;border:1px solid var(--border);border-radius:6px">${attentionRows}</div>`,
    customerReady && ready.length ? `Create ${ready.length} estimate${ready.length === 1 ? "" : "s"}` : "");
  const e = _ptEstModalEls();
  if (e.body) {
    e.body.onclick = (event) => {
      const exportButton = event.target.closest("[data-qb-batch-export-pdfs]");
      if (exportButton) {
        void (async () => {
          const progress = $("qb-est-batch-pdf-progress");
          exportButton.disabled = true;
          for (let index = 0; index < missingPdfs.length; index++) {
            const target = missingPdfs[index];
            const unit = (project.build_units || []).find(item =>
              (item.individuals || []).some(individual => individual.individual_id === target.individualId)
            );
            if (progress) {
              progress.hidden = false;
              _ptSetStatus(progress, `Creating PDF ${index + 1} of ${missingPdfs.length}: ${target.label}…`, "loading");
            }
            const ok = unit && await window.PT_buildExportPdf(
              project.project_id, unit.unit_id, target.individualId, "ind",
              { openAfter: false, statusEl: progress },
            );
            if (!ok) {
              exportButton.disabled = false;
              exportButton.textContent = "Try missing PDFs again";
              return;
            }
          }
          if (progress) _ptSetStatus(progress, "✅ PDFs ready — refreshing checklist…", "good");
          await _ptLoadAll();
          const updated = _PT.projects.find(p => p.project_id === project.project_id) || project;
          await _ptOpenBatchEstimateSetup(updated);
        })();
        return;
      }
      const button = event.target.closest("[data-qb-batch-link]");
      if (!button) return;
      const check = attention[Number(button.getAttribute("data-qb-batch-link"))];
      if (!check?.validation?.project) return;
      const returnToChecklist = async () => {
        await _ptLoadAll();
        const updated = _PT.projects.find((p) => p.project_id === project.project_id) || project;
        _PT.viewProject = updated;
        await _ptOpenBatchEstimateSetup(updated);
      };
      _ptOpenProjectBindingModal(
        project.project_id, check.individualId, check.validation.project,
        returnToChecklist, check.validation, returnToChecklist
      );
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
  if (statusEl) _ptSetStatus(statusEl, "Creating estimates…", "loading");
  let res;
  try {
    res = await api("/api/quickbooks/estimates/create-batch", {
      project_id: project.project_id, individual_ids: individualIds, attach_pdf: true,
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


// Service references contain IDs only: existing equipment never enters the service manifest.
window.PT_linkPreviousBuild = function(pid,uid,iid){
  let selected=null;
  const candidates=_PT.projects.filter(p=>(p.project_type||'build')==='build'&&p.project_id!==pid).flatMap(p=>(p.build_units||[]).flatMap(u=>(u.individuals||[]).map(i=>({p,u,i}))));
  _ptOpenFinalizationModal('Link previous build', '<p>Find a previous build by VIN or unit number. This adds a reference only; service parts stay separate.</p><label>VIN or unit number<input id="previous-build-search" type="search" autocomplete="off"></label><div id="previous-build-results"></div>', 'Link selected build', async()=>{
    if(!selected){toast('Choose a previous build first','info');return;}
    $('build-finalization-save').disabled=true;
    try{await _ptSavePreviousBuild(pid,uid,iid,{project_id:selected.p.project_id,unit_id:selected.u.unit_id,individual_id:selected.i.individual_id});}
    catch(error){toast(error.message||'Could not link previous build','error');}
    finally{$('build-finalization-save').disabled=false;}
  });
  const search=$('previous-build-search'),results=$('previous-build-results');
  search.oninput=()=>{
    selected=null;results.replaceChildren();const q=search.value.trim().toLowerCase();if(!q)return;
    const matches=candidates.filter(({i})=>[i.vin,i.unit_number].some(v=>v&&v.toLowerCase().includes(q))).slice(0,20);
    if(!matches.length){results.textContent='No previous build found. Continue with this service project normally.';return;}
    matches.forEach(match=>{const label=document.createElement('label');label.className='previous-build-match';const radio=document.createElement('input');radio.type='radio';radio.name='previous-build';radio.onchange=()=>selected=match;label.append(radio,document.createTextNode(`${match.p.customer.agency} · ${match.p.customer.build_year} · Unit ${match.i.unit_number||'—'} · VIN ${match.i.vin||'—'}`));results.append(label);});
  };search.focus();
};
async function _ptSavePreviousBuild(pid,uid,iid,link){
  const loaded=await api(`/api/project/${encodeURIComponent(pid)}`);if(!loaded.ok)throw new Error(loaded.error);
  const project=loaded.project,unit=project.build_units.find(u=>u.unit_id===uid),individual=unit?.individuals.find(i=>i.individual_id===iid);
  if(!individual)throw new Error('Service vehicle is no longer available');
  individual.previous_build=link;
  const saved=await api('/api/project/save',{project_id:pid,expected_updated_at:project.updated_at,expected_record_revision:project.record_revision,build_units:project.build_units});if(!saved.ok)throw new Error(saved.error);
  _ptCloseFinalizationModal();await _ptLoadAll();_ptShowDetail(_PT.projects.find(p=>p.project_id===pid));
}
window.PT_previousBuild = async function(pid,uid,iid){
  const project=_PT.projects.find(p=>p.project_id===pid),link=project?.build_units.find(u=>u.unit_id===uid)?.individuals.find(i=>i.individual_id===iid)?.previous_build;
  if(!link)return;
  const loaded=await api(`/api/project/${encodeURIComponent(link.project_id)}`),source=loaded.project;
  const unit=source?.build_units.find(u=>u.unit_id===link.unit_id),individual=unit?.individuals.find(i=>i.individual_id===link.individual_id);
  if(!individual){toast('The previous build is no longer available','error');return;}
  const title='Previous Build Design · '+(source.customer.agency||'')+' · Unit '+(individual.unit_number||'—');
  if(individual.draft_id)await PT_openReadOnlyBuild(individual.draft_id,title,individual.status);
  else {await PT_openReadOnlyBuild('',title);$('build-readonly-body').textContent='This previous build has no saved design.';}
  const body=$('build-readonly-body');
  const note=document.createElement('p');note.textContent='Reference to the saved build design. Service parts and changes belong to this service project.';body.prepend(note);
  if(individual.pdf_path){const button=document.createElement('button');button.className='btn btn-secondary btn-sm';button.textContent='View previous design PDF';button.onclick=()=>api('/open',{path:individual.pdf_path,agency:source.customer.agency||'',year:source.customer.build_year||''});body.prepend(button);}
  if(_ptCanEditProjects()){const unlink=document.createElement('button');unlink.className='btn btn-secondary btn-sm';unlink.textContent='Remove reference';unlink.onclick=async()=>{await _ptSavePreviousBuild(pid,uid,iid,{});_ptCloseReadOnlyBuildModal();};body.append(unlink);}
};
