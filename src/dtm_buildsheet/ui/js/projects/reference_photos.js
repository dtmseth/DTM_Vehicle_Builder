// Build-reference assignment, inheritance, and same-agency source browser.

const _PT_REFERENCE_SCOPE_RANK = { project: 0, unit_group: 1, individual: 2 };

function _ptEffectiveReferencePhotos(project, unitId = "", individualId = "") {
  const result = [];
  for (const asset of (project?.reference_assets || [])) {
    if (asset.media_type !== "photo") continue;
    const matches = (asset.assignments || []).map((assignment, index) => ({ assignment, index }))
      .filter(({ assignment }) =>
        assignment.scope === "project" ||
        (assignment.scope === "unit_group" && unitId && assignment.target_id === unitId) ||
        (assignment.scope === "individual" && individualId && assignment.target_id === individualId)
      );
    if (!matches.length) continue;
    matches.sort((a, b) =>
      (_PT_REFERENCE_SCOPE_RANK[b.assignment.scope] ?? -1) - (_PT_REFERENCE_SCOPE_RANK[a.assignment.scope] ?? -1) ||
      b.index - a.index
    );
    result.push({ asset, assignment: matches[0].assignment, origin: matches[0].assignment.scope });
  }
  result.sort((a, b) =>
    (Number(a.assignment.sort_order) || 0) - (Number(b.assignment.sort_order) || 0) ||
    String(a.asset.file_name || "").localeCompare(String(b.asset.file_name || ""))
  );
  return result;
}

function _ptUnassignedProjectPhotos(project) {
  return (project?.reference_assets || []).filter(asset => !(asset.assignments || []).length);
}

function _ptReferenceOriginLabel(origin) {
  if (origin === "individual") return "Legacy unit-only reference";
  if (origin === "unit_group") return "Unit group";
  return "Legacy project-wide reference";
}

function _ptReferenceSourceLabel(asset) {
  if (asset.source_kind === "shop_completed") return "Completed build photo";
  return asset.media_type === "video" ? "Company reference video" : "Company reference photo";
}

function _ptGalleryTargetProjects(sourceProject) {
  const active = (_PT.projects || []).filter(project => project.project_status !== "completed");
  return active.sort((a, b) => {
    const aSame = String(a.customer?.agency || "").toLowerCase() === String(sourceProject?.customer?.agency || "").toLowerCase();
    const bSame = String(b.customer?.agency || "").toLowerCase() === String(sourceProject?.customer?.agency || "").toLowerCase();
    return Number(bSame) - Number(aSame) || String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
  });
}

function _ptGalleryActionMarkup(kind, sourceProject) {
  if (kind === "completed" && _ptGalleryTargetProjects(sourceProject).length) {
    return `<div class="photo-gallery-selection-bar">
      <button type="button" class="btn btn-primary btn-sm" id="photo-gallery-use-selected" onclick="PT_chooseGalleryDestination()" disabled>Use as Reference Photo(s)</button>
      <span id="photo-gallery-selected-count">0 selected</span>
    </div>`;
  }
  if (kind === "reference" && sourceProject?.project_status !== "completed") {
    const groupScoped = Boolean(_PT.photoGalleryContext?.unitId);
    return `<div class="photo-gallery-selection-bar">
      ${groupScoped ? `<button type="button" class="btn btn-secondary btn-sm" onclick="PT_addGroupPhotos()">Add photos</button>` : `<button type="button" class="btn btn-secondary btn-sm" onclick="PT_addProjectPhotos()">Add photos</button>
      <button type="button" class="btn btn-primary btn-sm" id="photo-gallery-assign-selected" onclick="PT_assignSelectedProjectPhotos()" disabled>Assign to unit group</button>`}
      <button type="button" class="btn btn-danger btn-sm" id="photo-gallery-remove-selected" onclick="PT_removeSelectedReferencePhotos()" disabled>${groupScoped ? "Remove from unit group" : "Remove from project"}</button>
      <span id="photo-gallery-selected-count">0 selected</span>
    </div>`;
  }
  return "";
}

function _ptGalleryEmptyMarkup(kind, warnings = [], context = {}, sourceProject = null) {
  const title = kind === "completed"
    ? "No completed build photos."
    : context.unitId ? "No build reference photos." : "No project photos.";
  const addAction = context.unitId ? "PT_addGroupPhotos()" : "PT_addProjectPhotos()";
  return `<div class="photo-gallery-empty"><strong>${esc(title)}</strong>
    ${kind === "reference" && sourceProject?.project_status !== "completed" ? `<button type="button" class="btn btn-primary" onclick="${addAction}">Add photos</button>` : ""}
    ${warnings.map(message => `<small>${esc(message)}</small>`).join("")}</div>`;
}

function _ptGalleryMarkup(kind, photos, warnings = [], sourceProject = null) {
  if (!photos.length) return _ptGalleryEmptyMarkup(kind, warnings, _PT.photoGalleryContext || {}, sourceProject);
  const groupScoped = kind === "reference" && Boolean(_PT.photoGalleryContext?.unitId);
  const selectable = kind === "completed"
    ? Boolean(_ptGalleryTargetProjects(sourceProject).length)
    : sourceProject?.project_status !== "completed";
  return `<div class="photo-gallery-summary"><strong>${photos.length} photo${photos.length === 1 ? "" : "s"}</strong></div>
    ${warnings.map(message => `<div class="photo-gallery-warning">${esc(message)}</div>`).join("")}
    ${_ptGalleryActionMarkup(kind, sourceProject)}
    <div class="photo-gallery-grid">${photos.map((photo, index) => {
      const canEditGroupNote = groupScoped && photo.assignment_state === "assigned";
      const sourceTag = photo.source_kind === "shop_completed" ? "Completed build" : "Company photo";
      return `
      <article class="photo-gallery-card${groupScoped ? " photo-gallery-card--group-reference" : ""}" data-gallery-index="${index}">
        ${selectable ? `<label class="photo-gallery-select"><input type="checkbox" onchange="PT_toggleGalleryPhoto(${index},this.checked)"><span>Select</span></label>` : ""}
        <button type="button" class="photo-gallery-open" onclick="PT_openGalleryPhoto(${index})" aria-label="Open ${esc(photo.file_name || "photo")}">
          <span class="photo-gallery-thumb"><span class="photo-gallery-thumb-loading"><span class="dtm-loading-spinner"></span><span data-thumbnail-loading-text>Loading thumbnail…</span><span class="photo-thumbnail-retry" data-thumbnail-retry role="button" tabindex="0" hidden>Retry</span></span><img data-thumbnail-url="${esc(photo.thumbnail_url || "")}" alt="">
            ${kind === "completed" ? `<span class="photo-gallery-state-badge photo-gallery-state-badge--completed">✓ Completed</span>`
              : `<span class="photo-gallery-state-badge${photo.assignment_state === "assigned" ? " photo-gallery-state-badge--assigned" : ""}">${esc(photo.assignment_state === "assigned" ? "Assigned" : photo.assignment_state === "legacy" ? "Legacy" : "Unassigned")}</span>`}
          </span>
          <strong>${esc(kind === "completed" ? (photo.label || "Completed build") : (photo.file_name || "Project photo"))}</strong>
          ${kind === "completed" ? `<span class="photo-gallery-file-name">${esc(photo.file_name || "Photo")}</span>` : photo.label ? `<span>${esc(photo.label)}</span>` : ""}
          ${groupScoped ? `<span class="photo-gallery-card-tags"><span>${esc(sourceTag)}</span></span>` : ""}
          ${photo.note ? `<small data-gallery-note-display>${esc(photo.note)}</small>` : groupScoped ? `<small class="photo-gallery-note-empty" data-gallery-note-display>No shop note</small>` : ""}
        </button>
        ${canEditGroupNote ? `<div class="photo-gallery-card-actions">
          <button type="button" class="btn btn-secondary btn-sm" onclick="PT_editGroupReferenceNote(${index})">Edit note</button>
        </div>
        <div class="photo-gallery-note-editor" data-gallery-note-editor="${index}" hidden>
          <label><span>Shop note</span><textarea rows="3" data-gallery-note-input placeholder="What should the shop copy or notice?">${esc(photo.note || "")}</textarea></label>
          <div><button type="button" class="btn btn-primary btn-sm" onclick="PT_saveGroupReferenceNote(${index},this)">Save note</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="PT_cancelGroupReferenceNote(${index})">Cancel</button></div>
        </div>` : ""}
      </article>`;
    }).join("")}</div>
    <div class="photo-gallery-viewer" id="photo-gallery-viewer" hidden>
      <div class="photo-gallery-viewer-bar">
        <button type="button" class="btn btn-secondary btn-sm" onclick="PT_stepGalleryPhoto(-1)">← Previous</button>
        <span id="photo-gallery-viewer-count"></span>
        <button type="button" class="btn btn-secondary btn-sm" onclick="PT_stepGalleryPhoto(1)">Next →</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="PT_closeGalleryPhoto()">Back to thumbnails</button>
      </div>
      <div class="photo-gallery-full-wrap"><div class="photo-gallery-full-loading"><span class="dtm-loading-spinner"></span><span data-full-photo-loading-text>Loading full-resolution image…</span><button type="button" class="btn btn-secondary btn-sm" id="photo-gallery-full-retry" onclick="PT_retryGalleryPhoto()" hidden>Retry</button></div><img id="photo-gallery-full" alt=""></div>
      <strong id="photo-gallery-full-name"></strong><p id="photo-gallery-full-note"></p>
    </div>`;
}

function _ptThumbnailLoadingMarkup() {
  return `<span class="photo-gallery-thumb-loading"><span class="dtm-loading-spinner"></span><span data-thumbnail-loading-text>Loading thumbnail…</span><span class="photo-thumbnail-retry" data-thumbnail-retry role="button" tabindex="0" hidden>Retry</span></span>`;
}

function _ptReleaseThumbnailLoading() {
  _PT.fullPhotoRequest = (_PT.fullPhotoRequest || 0) + 1;
  _PT.fullPhotoController?.abort();
  _PT.fullPhotoController = null;
  _PT.thumbnailObserver?.disconnect();
  _PT.thumbnailObserver = null;
  for (const controller of (_PT.thumbnailControllers || [])) controller.abort();
  _PT.thumbnailControllers = new Set();
  for (const url of (_PT.thumbnailObjectUrls || [])) URL.revokeObjectURL(url);
  _PT.thumbnailObjectUrls = new Set();
  _PT.fullPhotoObjectUrl = "";
}

function _ptThumbnailTerminal(image, message, retryable = true) {
  const holder = image.closest(".photo-gallery-thumb,.proj-reference-browser-thumb,.proj-reference-file-icon");
  const loading = holder?.querySelector(".photo-gallery-thumb-loading");
  if (!holder || !loading) return;
  image.hidden = true;
  image.dataset.thumbnailState = "failed";
  holder.classList.add("unavailable");
  loading.hidden = false;
  loading.querySelector(".dtm-loading-spinner")?.setAttribute("hidden", "");
  const text = loading.querySelector("[data-thumbnail-loading-text]");
  if (text) text.textContent = message;
  const retry = loading.querySelector("[data-thumbnail-retry]");
  if (retry) retry.hidden = !retryable;
}

async function _ptLoadThumbnail(image) {
  const source = String(image?.dataset.thumbnailUrl || "");
  const upgrading = image?.dataset.thumbnailState === "preview";
  if (!source || !image?.isConnected || ["loading", "upgrading", "loaded"].includes(image.dataset.thumbnailState)) return;
  const holder = image.closest(".photo-gallery-thumb,.proj-reference-browser-thumb,.proj-reference-file-icon");
  const loading = holder?.querySelector(".photo-gallery-thumb-loading");
  if (!holder || !loading) return;
  image.dataset.thumbnailState = upgrading ? "upgrading" : "loading";
  image.hidden = false;
  holder.classList.remove("unavailable");
  loading.hidden = upgrading;
  if (!upgrading) loading.querySelector(".dtm-loading-spinner")?.removeAttribute("hidden");
  const text = loading.querySelector("[data-thumbnail-loading-text]");
  const retry = loading.querySelector("[data-thumbnail-retry]");
  if (retry) retry.hidden = true;

  const scheduleUpgrade = () => {
    const attempts = Number(image.dataset.thumbnailUpgradeAttempts || 0) + 1;
    image.dataset.thumbnailUpgradeAttempts = String(attempts);
    if (attempts > 6) return;
    setTimeout(() => {
      if (image.isConnected && image.dataset.thumbnailState === "preview") {
        _ptLoadThumbnail(image);
      }
    }, Math.min(3_000 + attempts * 1_500, 10_000));
  };

  let lastPreparing = false;
  for (let attempt = 0; attempt < 4 && image.isConnected; attempt += 1) {
    const controller = new AbortController();
    if (!(_PT.thumbnailControllers instanceof Set)) _PT.thumbnailControllers = new Set();
    _PT.thumbnailControllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 12_000);
    try {
      if (text) text.textContent = lastPreparing ? "Preparing thumbnail…" : attempt ? "Retrying thumbnail…" : "Loading thumbnail…";
      const response = await fetch(source, {
        cache: upgrading ? "reload" : "force-cache",
        headers: { "X-DTM-Thumbnail-Priority": "foreground" },
        signal: controller.signal,
      });
      if (response.status === 202) {
        lastPreparing = true;
        if (text) text.textContent = "Preparing thumbnail…";
        const retrySeconds = Math.max(1, Math.min(Number(response.headers.get("Retry-After")) || 2, 5));
        await new Promise(resolve => setTimeout(resolve, retrySeconds * 1000));
        continue;
      }
      if (!response.ok) throw new Error(`thumbnail ${response.status}`);
      const cacheState = response.headers.get("X-DTM-Thumbnail-State") || "ready";
      if (upgrading && cacheState === "preview" && image.src) {
        image.dataset.thumbnailState = "preview";
        scheduleUpgrade();
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      if (!(_PT.thumbnailObjectUrls instanceof Set)) _PT.thumbnailObjectUrls = new Set();
      _PT.thumbnailObjectUrls.add(objectUrl);
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
        image.src = objectUrl;
        image.hidden = false;
      });
      image.dataset.thumbnailState = cacheState === "preview" ? "preview" : "loaded";
      loading.hidden = true;
      holder.classList.remove("unavailable");
      if (cacheState === "preview") scheduleUpgrade();
      return;
    } catch (error) {
      if (!image.isConnected) return;
      if (attempt === 3) {
        if (upgrading && image.src) {
          image.dataset.thumbnailState = "preview";
          scheduleUpgrade();
          return;
        }
        _ptThumbnailTerminal(image, lastPreparing ? "Preview still preparing" : "Preview unavailable");
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 900 * (attempt + 1)));
    } finally {
      clearTimeout(timeout);
      _PT.thumbnailControllers?.delete(controller);
    }
  }
}

function _ptBindThumbnailLoading(root) {
  const images = [...(root || document).querySelectorAll("img[data-thumbnail-url]")];
  if (!images.length) return;
  _PT.thumbnailObserver?.disconnect();
  _PT.thumbnailObserver = null;
  let immediate = 0;
  const deferred = [];
  for (const image of images) {
    image.dataset.thumbnailState = "queued";
    image.dataset.thumbnailUpgradeAttempts = "0";
    const retry = image.closest(".photo-gallery-thumb,.proj-reference-browser-thumb,.proj-reference-file-icon")
      ?.querySelector("[data-thumbnail-retry]");
    const retryLoad = event => {
      event.stopPropagation();
      image.dataset.thumbnailState = "";
      _ptLoadThumbnail(image);
    };
    retry?.addEventListener("click", retryLoad);
    retry?.addEventListener("keydown", event => {
      if (!["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      retryLoad(event);
    });
    const holder = image.closest(".photo-gallery-thumb,.proj-reference-browser-thumb,.proj-reference-file-icon");
    if (!holder) continue;
    if (immediate < 12) {
      immediate += 1;
      setTimeout(() => _ptLoadThumbnail(image), 0);
    } else {
      deferred.push(holder);
    }
  }
  if (deferred.length && typeof IntersectionObserver === "function") {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const image = entry.target.querySelector("img[data-thumbnail-url]");
        if (image) _ptLoadThumbnail(image);
      }
    }, { rootMargin: "320px" });
    _PT.thumbnailObserver = observer;
    for (const holder of deferred) observer.observe(holder);
  } else {
    // Older embedded webviews do not expose IntersectionObserver. Keep the
    // same bounded behavior and stagger the non-visible remainder instead of
    // leaving permanent spinners.
    deferred.forEach((holder, index) => setTimeout(() => {
      const image = holder.querySelector("img[data-thumbnail-url]");
      if (image) _ptLoadThumbnail(image);
    }, Math.floor(index / 4) * 250));
  }
  if (typeof refreshCloudStatus === "function") refreshCloudStatus();
}

function _ptBindGalleryThumbnailLoading() {
  _ptBindThumbnailLoading($("photo-gallery-body"));
}

function _ptClosePhotoGallery() {
  _PT.photoGalleryRequest = (_PT.photoGalleryRequest || 0) + 1;
  _ptReleaseThumbnailLoading();
  const modal = $("photo-gallery-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
}

async function _ptRefreshProjectPhotoState(projectId) {
  await _ptLoadAll();
  const project = (_PT.projects || []).find(item => item.project_id === projectId);
  if (!project) return null;
  if (_PT.viewProject?.project_id === projectId) {
    _PT.viewProject = project;
    _ptRenderOverview(project);
  }
  if (_PT.pbeProject?.project_id === projectId) {
    _PT.pbeProject = project;
    _pbeRenderReferenceSummary();
  }
  return project;
}

function _ptOpenGalleryPhotoPicker(unitId = "") {
  const context = { ...(_PT.photoGalleryContext || {}) };
  if (!context.projectId) return;
  _PT.referenceReturnGallery = {
    projectId: context.projectId,
    kind: "reference",
    unitId: unitId || "",
  };
  _ptClosePhotoGallery();
  PT_openReferencePhotos(
    context.projectId || "",
    unitId || "",
    "",
    unitId ? "unit_group" : "project",
    true,
  );
}

window.PT_addProjectPhotos = function () {
  _ptOpenGalleryPhotoPicker("");
};

window.PT_addGroupPhotos = function () {
  _ptOpenGalleryPhotoPicker(_PT.photoGalleryContext?.unitId || "");
};

window.PT_openPhotoGallery = async function (projectId, kind, unitId = "", individualId = "") {
  _ptReleaseThumbnailLoading();
  const request = (_PT.photoGalleryRequest || 0) + 1;
  _PT.photoGalleryRequest = request;
  _PT.photoGalleryPhotos = [];
  _PT.photoGalleryIndex = -1;
  _PT.photoGallerySelected = new Set();
  _PT.photoGalleryContext = { projectId, kind, unitId: unitId || "", individualId: individualId || "" };
  let sourceProject = (_PT.projects || []).find(project => project.project_id === projectId) || _PT.viewProject;
  const modal = $("photo-gallery-modal");
  const body = $("photo-gallery-body");
  const title = kind === "completed"
    ? "Completed Build Photos"
    : unitId ? "Build Reference Photos" : "Project Photos";
  $("photo-gallery-title").textContent = title;
  body.innerHTML = `<div class="photo-gallery-loading"><span class="dtm-loading-spinner"></span><strong>Loading ${esc(title.toLowerCase())}…</strong></div>`;
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");

  try {
    let result = null;
    for (let attempt = 0; attempt < 90; attempt += 1) {
      result = await api(`/api/project/${encodeURIComponent(projectId)}/photo-gallery`, {
        kind, unit_id: unitId || "", individual_id: individualId || "",
        discover_folder: kind === "reference" && !unitId,
      });
      if (_PT.photoGalleryRequest !== request) return;
      if (!result?.ok) throw new Error(result?.error || "Could not load photos");
      if (!result.loading) break;
      if ((result.photos || []).length) {
        body.innerHTML = _ptGalleryMarkup(
          kind,
          result.photos,
          [...(result.warnings || []), "Checking the project photo folder…"],
          sourceProject,
        );
        _ptBindGalleryThumbnailLoading();
      } else if (kind === "reference" && !unitId) {
        body.innerHTML = `<div class="photo-gallery-loading"><span class="dtm-loading-spinner"></span><strong>Checking the project photo folder…</strong></div>`;
      }
      await new Promise(resolve => setTimeout(resolve, 600));
    }
    if (_PT.photoGalleryRequest !== request) return;
    if (result?.loading) throw new Error("Photo loading is taking longer than expected. Close and try again.");
    if (Number(result?.project_changed || 0)) {
      sourceProject = await _ptRefreshProjectPhotoState(projectId) || sourceProject;
    }
    _PT.photoGalleryPhotos = result?.photos || [];
    body.innerHTML = _ptGalleryMarkup(kind, _PT.photoGalleryPhotos, result?.warnings || [], sourceProject);
    _ptBindGalleryThumbnailLoading();
  } catch (error) {
    body.innerHTML = `<div class="photo-gallery-empty"><strong>Could not load photos.</strong><p>${esc(error.message || "Try again after cloud sign-in.")}</p></div>`;
  }
};

function _ptUpdateGallerySelection() {
  const count = _PT.photoGallerySelected?.size || 0;
  const label = $("photo-gallery-selected-count");
  if (label) label.textContent = `${count} selected`;
  for (const id of ["photo-gallery-use-selected", "photo-gallery-assign-selected", "photo-gallery-remove-selected"]) {
    const button = $(id);
    if (button) button.disabled = count === 0;
  }
}

window.PT_toggleGalleryPhoto = function (index, selected) {
  const photo = (_PT.photoGalleryPhotos || [])[Number(index)];
  if (!photo?.photo_token) return;
  if (!(_PT.photoGallerySelected instanceof Set)) _PT.photoGallerySelected = new Set();
  if (selected) _PT.photoGallerySelected.add(photo.photo_token);
  else _PT.photoGallerySelected.delete(photo.photo_token);
  document.querySelector(`[data-gallery-index="${Number(index)}"]`)?.classList.toggle("selected", Boolean(selected));
  _ptUpdateGallerySelection();
};

function _ptGroupGalleryReference(index) {
  const context = _PT.photoGalleryContext || {};
  if (!context.projectId || !context.unitId) return null;
  const project = (_PT.projects || []).find(item => item.project_id === context.projectId) || _PT.viewProject;
  const photo = (_PT.photoGalleryPhotos || [])[Number(index)];
  if (!project || !photo?.source_key) return null;
  const asset = (project.reference_assets || []).find(item => _ptReferenceKey(item) === photo.source_key);
  const assignment = asset && (asset.assignments || []).find(item =>
    item.scope === "unit_group" && String(item.target_id || "") === String(context.unitId)
  );
  return asset && assignment ? { project, asset, assignment, photo, context } : null;
}

window.PT_editGroupReferenceNote = function (index) {
  const editor = document.querySelector(`[data-gallery-note-editor="${Number(index)}"]`);
  if (!editor) return;
  editor.hidden = false;
  editor.querySelector("[data-gallery-note-input]")?.focus();
};

window.PT_cancelGroupReferenceNote = function (index) {
  const record = _ptGroupGalleryReference(index);
  const editor = document.querySelector(`[data-gallery-note-editor="${Number(index)}"]`);
  if (!editor) return;
  const input = editor.querySelector("[data-gallery-note-input]");
  if (input) input.value = record?.assignment?.note || "";
  editor.hidden = true;
};

window.PT_saveGroupReferenceNote = async function (index, button) {
  const record = _ptGroupGalleryReference(index);
  const editor = document.querySelector(`[data-gallery-note-editor="${Number(index)}"]`);
  const input = editor?.querySelector("[data-gallery-note-input]");
  if (!record || !input) return;
  const asset = JSON.parse(JSON.stringify(record.asset));
  const assignment = (asset.assignments || []).find(item =>
    item.scope === "unit_group" && String(item.target_id || "") === String(record.context.unitId)
  );
  if (!assignment) return;
  assignment.note = input.value.trim();
  if (button) {
    button.disabled = true;
    button.textContent = "Saving…";
  }
  try {
    await _ptSaveReferenceAsset(record.project.project_id, asset);
    await _ptRefreshProjectPhotoState(record.project.project_id);
    toast("Photo note saved", "success");
    PT_openPhotoGallery(record.project.project_id, "reference", record.context.unitId);
  } catch (error) {
    toast(error.message || "Could not save the photo note", "error");
    if (button) {
      button.disabled = false;
      button.textContent = "Save note";
    }
  }
};

async function _ptImportGalleryPhotos(tokens, targetProjectId, targetUnitId = "") {
  const context = _PT.photoGalleryContext;
  if (!context?.projectId || !targetProjectId || !tokens.length) return;
  try {
    const response = await api(`/api/project/${encodeURIComponent(targetProjectId)}/references/import-gallery`, {
      source_project_id: context.projectId,
      photo_tokens: tokens,
      target_unit_id: targetUnitId || "",
    });
    if (!response?.ok) throw new Error(response?.error || "Could not add the selected photos");
    await _ptRefreshProjectPhotoState(targetProjectId);
    const added = Number(response.added) || 0;
    const already = Number(response.already_in_project ?? response.already_assigned) || 0;
    const destination = targetUnitId ? "the selected unit group" : "the project";
    toast(added
      ? `${added} photo${added === 1 ? "" : "s"} added to ${destination}`
      : already ? `The selected photo${already === 1 ? " is" : "s are"} already in that project` : "No photos were added", added ? "success" : "info");
    _PT.photoGallerySelected = new Set();
    document.querySelectorAll(".photo-gallery-select input").forEach(input => { input.checked = false; });
    document.querySelectorAll(".photo-gallery-card.selected").forEach(card => card.classList.remove("selected"));
    _ptUpdateGallerySelection();
  } catch (error) {
    toast(error.message || "Could not add the selected photos", "error");
  }
}

window.PT_chooseGalleryDestination = function () {
  const tokens = [...(_PT.photoGallerySelected || [])];
  if (!tokens.length) return;
  _PT.photoGalleryPendingTokens = tokens;
  _PT.photoUseMode = "reuse";
  const source = (_PT.projects || []).find(project => project.project_id === _PT.photoGalleryContext?.projectId) || _PT.viewProject;
  const projects = _ptGalleryTargetProjects(source);
  const select = $("photo-use-project");
  if (!select || !projects.length) return;
  select.innerHTML = projects.map(project => `<option value="${esc(project.project_id)}">${esc(`${project.customer?.agency || "Agency"} · ${project.customer?.build_year || "No year"}`)}</option>`).join("");
  const sameAgency = projects.find(project => String(project.customer?.agency || "").toLowerCase() === String(source?.customer?.agency || "").toLowerCase());
  select.value = sameAgency?.project_id || projects[0].project_id;
  $("photo-use-title").textContent = "Use as Reference Photos";
  $("photo-use-intro").textContent = "Choose a project and, if needed, a unit group.";
  $("photo-use-project-group").hidden = false;
  $("photo-use-unit-group-label").textContent = "Unit group (optional)";
  $("photo-use-confirm").textContent = "Add photos";
  _ptUpdatePhotoUseGroups();
  const modal = $("photo-use-modal");
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");
  select.focus();
};

function _ptUpdatePhotoUseGroups() {
  const project = (_PT.projects || []).find(item => item.project_id === $("photo-use-project")?.value);
  const select = $("photo-use-unit-group");
  if (!select) return;
  const assigning = _PT.photoUseMode === "assign";
  select.innerHTML = `<option value="">${assigning ? "Choose a unit group" : "Project only (assign later)"}</option>${(project?.build_units || []).map(unit =>
    `<option value="${esc(unit.unit_id)}">${esc([_ptVehicleModelLabel(unit), unit.build_type].filter(Boolean).join(" · ") || "Unit group")}</option>`
  ).join("")}`;
  $("photo-use-confirm").disabled = assigning;
}

function _ptClosePhotoUseModal() {
  const modal = $("photo-use-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
}

async function _ptConfirmPhotoUse() {
  const projectId = $("photo-use-project")?.value || "";
  const unitId = $("photo-use-unit-group")?.value || "";
  const tokens = _PT.photoGalleryPendingTokens || [];
  const mode = _PT.photoUseMode || "reuse";
  if (mode === "assign" && !unitId) return;
  _ptClosePhotoUseModal();
  await _ptImportGalleryPhotos(tokens, projectId, unitId);
  if (mode === "assign") PT_openPhotoGallery(projectId, "reference");
}

window.PT_assignSelectedProjectPhotos = function () {
  const context = _PT.photoGalleryContext || {};
  const tokens = [...(_PT.photoGallerySelected || [])];
  const project = (_PT.projects || []).find(item => item.project_id === context.projectId);
  if (!project || !tokens.length || !(project.build_units || []).length) return;
  _PT.photoGalleryPendingTokens = tokens;
  _PT.photoUseMode = "assign";
  const projectSelect = $("photo-use-project");
  projectSelect.innerHTML = `<option value="${esc(project.project_id)}">${esc(`${project.customer?.agency || "Agency"} · ${project.customer?.build_year || "No year"}`)}</option>`;
  projectSelect.value = project.project_id;
  $("photo-use-title").textContent = "Assign Project Photos";
  $("photo-use-intro").textContent = "Choose a unit group.";
  $("photo-use-project-group").hidden = true;
  $("photo-use-unit-group-label").textContent = "Unit group";
  $("photo-use-confirm").textContent = "Assign photos";
  _ptUpdatePhotoUseGroups();
  const modal = $("photo-use-modal");
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");
  $("photo-use-unit-group")?.focus();
};

window.PT_removeSelectedReferencePhotos = async function () {
  const context = _PT.photoGalleryContext;
  const tokens = [...(_PT.photoGallerySelected || [])];
  if (!context?.projectId || !tokens.length) return;
  const destination = context.unitId ? "this unit group" : "this project";
  if (!confirm(`Remove ${tokens.length} selected reference photo${tokens.length === 1 ? "" : "s"} from ${destination}?\n\nThe original photo files will not be deleted.`)) return;
  try {
    const response = await api(`/api/project/${encodeURIComponent(context.projectId)}/references/remove-gallery`, {
      photo_tokens: tokens,
      target_unit_id: context.unitId || "",
    });
    if (!response?.ok) throw new Error(response?.error || "Could not remove the selected references");
    toast(`${Number(response.removed) || 0} reference photo${Number(response.removed) === 1 ? "" : "s"} removed`, "success");
    await _ptRefreshProjectPhotoState(context.projectId);
    PT_openPhotoGallery(context.projectId, "reference", context.unitId, context.individualId);
  } catch (error) {
    toast(error.message || "Could not remove the selected references", "error");
  }
};

window.PT_openGalleryPhoto = function (index) {
  const photos = _PT.photoGalleryPhotos || [];
  if (!photos.length) return;
  const normalized = ((Number(index) || 0) + photos.length) % photos.length;
  const photo = photos[normalized];
  _PT.photoGalleryIndex = normalized;
  const viewer = $("photo-gallery-viewer");
  const grid = document.querySelector("#photo-gallery-body .photo-gallery-grid");
  if (grid) grid.hidden = true;
  viewer.hidden = false;
  $("photo-gallery-viewer-count").textContent = `${normalized + 1} of ${photos.length}`;
  $("photo-gallery-full-name").textContent = photo.file_name || "Photo";
  $("photo-gallery-full-note").textContent = photo.note || photo.label || "";
  _ptLoadFullGalleryPhoto(photo);
  viewer.scrollIntoView({ behavior: "smooth", block: "start" });
};

async function _ptLoadFullGalleryPhoto(photo) {
  const image = $("photo-gallery-full");
  const loading = document.querySelector(".photo-gallery-full-loading");
  const loadingText = loading?.querySelector("[data-full-photo-loading-text]");
  const retry = $("photo-gallery-full-retry");
  if (!image || !loading || !photo?.content_url) return;
  const request = (_PT.fullPhotoRequest || 0) + 1;
  _PT.fullPhotoRequest = request;
  _PT.fullPhotoController?.abort();
  image.removeAttribute("src");
  image.style.opacity = "0";
  loading.hidden = false;
  loading.querySelector(".dtm-loading-spinner")?.removeAttribute("hidden");
  if (loadingText) loadingText.textContent = "Loading full-resolution image…";
  if (retry) retry.hidden = true;
  const controller = new AbortController();
  _PT.fullPhotoController = controller;
  if (!(_PT.thumbnailControllers instanceof Set)) _PT.thumbnailControllers = new Set();
  _PT.thumbnailControllers.add(controller);
  const timeout = setTimeout(() => controller.abort(), 24_000);
  const deadline = Date.now() + 22_000;
  let downloading = false;
  try {
    let blob = null;
    while (Date.now() < deadline && _PT.fullPhotoRequest === request) {
      const response = await fetch(photo.content_url, {
        cache: "force-cache",
        signal: controller.signal,
      });
      if (response.status === 202) {
        const firstDownloadNotice = !downloading;
        downloading = true;
        if (loadingText) {
          loadingText.textContent = "Downloading full-resolution photo… Saving it locally for next time.";
        }
        if (firstDownloadNotice && typeof refreshCloudStatus === "function") refreshCloudStatus();
        const retrySeconds = Math.max(0.5, Math.min(Number(response.headers.get("Retry-After")) || 1, 2));
        await new Promise(resolve => setTimeout(resolve, retrySeconds * 1000));
        continue;
      }
      if (!response.ok) throw new Error(`photo ${response.status}`);
      blob = await response.blob();
      break;
    }
    if (!blob) throw new Error("full-resolution download timed out");
    if (_PT.fullPhotoRequest !== request || !image.isConnected) return;
    if (_PT.fullPhotoObjectUrl) {
      URL.revokeObjectURL(_PT.fullPhotoObjectUrl);
      _PT.thumbnailObjectUrls?.delete(_PT.fullPhotoObjectUrl);
    }
    const objectUrl = URL.createObjectURL(blob);
    _PT.fullPhotoObjectUrl = objectUrl;
    if (!(_PT.thumbnailObjectUrls instanceof Set)) _PT.thumbnailObjectUrls = new Set();
    _PT.thumbnailObjectUrls.add(objectUrl);
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = objectUrl;
    });
    if (_PT.fullPhotoRequest !== request) return;
    image.style.opacity = "1";
    loading.hidden = true;
  } catch (_) {
    if (_PT.fullPhotoRequest !== request || !image.isConnected) return;
    image.removeAttribute("src");
    image.alt = "Full-resolution photo could not be loaded";
    image.style.opacity = "1";
    loading.querySelector(".dtm-loading-spinner")?.setAttribute("hidden", "");
    if (loadingText) loadingText.textContent = "Full-resolution photo could not be loaded.";
    if (retry) retry.hidden = false;
  } finally {
    clearTimeout(timeout);
    if (_PT.fullPhotoController === controller) _PT.fullPhotoController = null;
    _PT.thumbnailControllers?.delete(controller);
    if (downloading && typeof refreshCloudStatus === "function") refreshCloudStatus();
  }
}

window.PT_retryGalleryPhoto = function () {
  const photo = (_PT.photoGalleryPhotos || [])[Number(_PT.photoGalleryIndex)];
  if (photo) _ptLoadFullGalleryPhoto(photo);
};

window.PT_stepGalleryPhoto = function (direction) {
  PT_openGalleryPhoto((_PT.photoGalleryIndex || 0) + Number(direction || 0));
};

window.PT_closeGalleryPhoto = function () {
  _PT.fullPhotoRequest = (_PT.fullPhotoRequest || 0) + 1;
  _PT.fullPhotoController?.abort();
  _PT.fullPhotoController = null;
  const viewer = $("photo-gallery-viewer");
  const grid = document.querySelector("#photo-gallery-body .photo-gallery-grid");
  if (viewer) viewer.hidden = true;
  if (grid) grid.hidden = false;
  const image = $("photo-gallery-full");
  if (image) image.removeAttribute("src");
};

function _ptCompletedPhotoButtonMarkup(projectId, unitId = "", individualId = "") {
  return `<button class="btn btn-primary btn-sm" type="button" hidden
    data-completed-photo-action data-project-id="${esc(projectId)}"
    data-unit-id="${esc(unitId)}" data-individual-id="${esc(individualId)}"
    onclick="PT_openPhotoGallery('${esc(projectId)}','completed','${esc(unitId)}','${esc(individualId)}')">View completed photos</button>`;
}

async function _ptRefreshCompletedPhotoActions(projectId, root = document) {
  const actions = [...(root || document).querySelectorAll("[data-completed-photo-action]")]
    .filter(button => button.dataset.projectId === projectId);
  if (!actions.length) return;
  const applyPresence = presence => {
    const targets = presence?.targets || {};
    for (const button of actions) {
      if (!button.isConnected) continue;
      const unitId = button.dataset.unitId || "";
      const individualId = button.dataset.individualId || "";
      button.hidden = unitId
        ? !Number(targets[`${unitId}::${individualId}`] || 0)
        : !presence?.project;
    }
  };
  let result = null;
  try {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      result = await api(`/api/project/${encodeURIComponent(projectId)}/photo-gallery`, {
        kind: "completed", presence_only: true,
      });
      if (result?.ok) applyPresence(result.presence || {});
      if (!result?.ok || !result.loading) break;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } catch (_) {
    return;
  }
}

async function _ptRefreshProjectFolderPhotos(projectId) {
  if (!projectId) return;
  if (!(_PT.projectPhotoSyncing instanceof Set)) _PT.projectPhotoSyncing = new Set();
  if (_PT.projectPhotoSyncing.has(projectId)) return;
  _PT.projectPhotoSyncing.add(projectId);
  try {
    let result = null;
    for (let attempt = 0; attempt < 45; attempt += 1) {
      result = await api(`/api/project/${encodeURIComponent(projectId)}/photo-gallery`, {
        kind: "reference", presence_only: true, discover_folder: true,
      });
      if (!result?.ok || !result.loading) break;
      await new Promise(resolve => setTimeout(resolve, 600));
    }
    if (result?.ok && !result.loading && Number(result.project_changed || 0)) {
      await _ptRefreshProjectPhotoState(projectId);
    }
  } catch (_) {
    // The saved project-photo metadata remains available if SharePoint is offline.
  } finally {
    _PT.projectPhotoSyncing.delete(projectId);
  }
}

function _ptReferenceSummaryMarkup(project) {
  const unassigned = _ptUnassignedProjectPhotos(project).filter(asset => asset.media_type === "photo");
  const groupAssigned = (project?.reference_assets || []).filter(asset =>
    asset.media_type === "photo" &&
    (asset.assignments || []).some(assignment => assignment.scope === "unit_group")
  );
  const legacy = (project?.reference_assets || []).filter(asset =>
    (asset.assignments || []).some(assignment => assignment.scope === "project" || assignment.scope === "individual")
  );
  const photoCount = (project?.reference_assets || []).filter(asset => asset.media_type === "photo").length;
  const counts = [`${photoCount} photo${photoCount === 1 ? "" : "s"}`];
  if (groupAssigned.length) counts.push(`${groupAssigned.length} assigned`);
  if (unassigned.length) counts.push(`${unassigned.length} unassigned`);
  if (legacy.length) counts.push(`${legacy.length} legacy`);
  return `<section class="proj-reference-overview-card" aria-label="Project Photos">
    <div>
      <h3>Project Photos</h3>
      <p>${esc(counts.join(" · "))}</p>
    </div>
    <div class="proj-reference-overview-actions">
      ${_ptCompletedPhotoButtonMarkup(project.project_id)}
      <button class="btn btn-secondary btn-sm" type="button"
        onclick="PT_openPhotoGallery('${esc(project.project_id)}','reference')">Project photos</button>
    </div>
  </section>`;
}

function _ptProjectFolderActionsMarkup(project) {
  const companyYearPath = String(project?.company_year_folder_path || "").trim();
  const shopYearPath = String(project?.shop_year_folder_path || "").trim();
  if (!companyYearPath && !shopYearPath) return "";
  return `<div class="proj-overview-folder-actions" aria-label="Project folders">
    ${companyYearPath ? `<button class="btn btn-secondary btn-sm" type="button"
      data-library-target="company" data-folder-path="${esc(companyYearPath)}"
      onclick="PT_openCloudFolder(this)">Open Company folder</button>` : ""}
    ${companyYearPath ? `<button class="btn btn-secondary btn-sm" type="button"
      data-library-target="company" data-folder-path="${esc(`${companyYearPath}/Reference Photos & Videos`)}"
      onclick="PT_openCloudFolder(this)">Open project photos folder</button>` : ""}
    ${shopYearPath ? `<button class="btn btn-secondary btn-sm" type="button"
      data-library-target="shop" data-folder-path="${esc(shopYearPath)}"
      onclick="PT_openCloudFolder(this)">Open Shop folder</button>` : ""}
  </div>`;
}

function _ptGroupReferenceButton(project, unit) {
  const count = _ptEffectiveReferencePhotos(project, unit.unit_id, "").length;
  return `<button class="btn btn-secondary btn-sm proj-group-reference-btn" type="button"
    onclick="PT_openPhotoGallery('${esc(project.project_id)}','reference','${esc(unit.unit_id)}')">
    Build Reference Photos (${count})
  </button>`;
}

function _ptReferenceContext(projectId, unitId, individualId, scope) {
  const normalizedScope = unitId && scope !== "project" ? "unit_group" : "project";
  return {
    projectId,
    unitId: unitId || "",
    individualId: "",
    scope: normalizedScope,
  };
}

function _ptReferenceTarget(context) {
  if (context.scope === "unit_group") return context.unitId;
  return "";
}

function _ptCurrentReferenceAssignment(asset, context) {
  const target = _ptReferenceTarget(context);
  return (asset.assignments || []).find(assignment =>
    assignment.scope === context.scope && String(assignment.target_id || "") === target
  );
}

function _ptReferenceModalItems(project, context) {
  if (context.scope === "project") {
    return _ptUnassignedProjectPhotos(project).map(asset => ({ asset, assignment: null, origin: "unassigned" }))
      .sort((a, b) => String(a.asset.file_name || "").localeCompare(String(b.asset.file_name || "")));
  }
  return _ptEffectiveReferencePhotos(project, context.unitId, "");
}

function _ptReferenceRowsMarkup(items, context) {
  if (!items.length) {
    const title = context.scope === "project" ? "No project photos." : "No photos are assigned to this unit group.";
    const help = context.scope === "project"
      ? "Choose existing photos."
      : "Choose project photos or completed-build photos.";
    return `<div class="proj-reference-empty"><strong>${esc(title)}</strong>
      <p>${esc(help)}</p>
      <button type="button" class="btn btn-primary btn-sm" data-reference-empty-browse>Select existing photos</button></div>`;
  }
  return `<div class="proj-reference-list">${items.map(item => {
    const current = item.origin === context.scope &&
      item.assignment === _ptCurrentReferenceAssignment(item.asset, context);
    const unassigned = item.origin === "unassigned";
    const mediaLabel = item.asset.media_type === "video" ? "VIDEO" : "PHOTO";
    return `<article class="proj-reference-row" data-reference-id="${esc(item.asset.reference_id)}" data-reference-key="${esc(_ptReferenceKey(item.asset))}" data-current="${current ? "true" : "false"}">
      <div class="proj-reference-file-icon" aria-hidden="true">${mediaLabel}</div>
      <div class="proj-reference-row-main">
        <strong>${esc(item.asset.file_name || `Reference ${item.asset.media_type || "photo"}`)}</strong>
        <span>${esc(unassigned ? "Unassigned project photo" : _ptReferenceOriginLabel(item.origin))} · ${esc(_ptReferenceSourceLabel(item.asset))}</span>
        ${current ? `<label class="proj-reference-note"><span>Shop note</span>
          <textarea data-reference-note rows="2" placeholder="What should the shop copy or notice?">${esc(item.assignment.note || "")}</textarea></label>
          <button type="button" class="btn btn-secondary btn-sm" data-reference-remove>Unassign from group</button>`
        : unassigned ? `<p class="proj-reference-inherited">Not assigned to a unit group.</p>
          <button type="button" class="btn btn-danger btn-sm" data-reference-remove>Remove from project</button>`
        : `<p class="proj-reference-inherited">${esc(_ptReferenceOriginLabel(item.origin))} preserved for compatibility. New references are assigned only to unit groups.</p>
          ${item.assignment?.note ? `<p>${esc(item.assignment.note)}</p>` : ""}`}
      </div>
    </article>`;
  }).join("")}</div>`;
}

function _ptReferenceModalMarkup(project, context) {
  const items = _ptReferenceModalItems(project, context);
  const scopeHelp = context.scope === "project"
    ? "Add photos to this project."
    : "Photos assigned here apply to every vehicle in this unit group.";
  const hasEditable = items.some(item => item.origin === context.scope);
  return `<div class="proj-reference-toolbar">
      <p>${esc(scopeHelp)}</p>
      ${items.length ? `<button type="button" class="btn btn-secondary btn-sm" id="reference-photo-browse">Select existing photos</button>` : ""}
    </div>
    <div id="reference-photo-assigned">${_ptReferenceRowsMarkup(items, context)}</div>
    <div id="reference-photo-browser" hidden></div>
    <div id="reference-photo-status" class="proj-action-status" style="display:none"></div>
    ${hasEditable ? `<p class="proj-reference-save-hint">Save changes after editing shop notes.</p>` : ""}`;
}

function _ptReferenceKey(asset) {
  return `${String(asset.source_drive_id || "")}::${String(asset.source_item_id || asset.source_path || "")}`;
}

function _ptReferenceDefaultFilters(project, context) {
  let unit = (project.build_units || []).find(item => item.unit_id === context.unitId);
  if (!unit && (project.build_units || []).length === 1) unit = project.build_units[0];
  let individual = unit?.individuals?.find(item => item.individual_id === context.individualId);
  if (!individual && (unit?.individuals || []).length === 1) individual = unit.individuals[0];
  return {
    agency: String(project.customer?.agency || ""),
    make: String(individual?.make || ""),
    model: unit ? _ptVehicleModelLabel(unit, individual) : String(individual?.model || ""),
    buildType: String(unit?.build_type || ""),
    query: "",
  };
}

function _ptReferenceFilterOptions(items, field, selected, allLabel) {
  const values = [...new Set(items.map(item => String(item[field] || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  if (selected && !values.some(value => value.toLowerCase() === selected.toLowerCase())) values.unshift(selected);
  return `<option value="">${esc(allLabel)}</option>${values.map(value =>
    `<option value="${esc(value)}" ${value.toLowerCase() === String(selected || "").toLowerCase() ? "selected" : ""}>${esc(value)}</option>`
  ).join("")}`;
}

function _ptReferenceBrowserMarkup(project, context, discovered, warnings = [], agency = "") {
  const byKey = new Map(discovered
    .filter(asset => asset.media_type !== "video" || context.scope === "project")
    .map(asset => [_ptReferenceKey(asset), asset]));
  if (context.scope === "unit_group") {
    for (const asset of _ptUnassignedProjectPhotos(project).filter(item => item.media_type === "photo")) {
      const key = _ptReferenceKey(asset);
      if (!byKey.has(key)) {
        const galleryItem = _PT.referenceThumbnailByKey?.get(key) || {};
        byKey.set(key, {
          ...asset,
          ...galleryItem,
          media_type: asset.media_type,
        });
      }
    }
  }
  const available = [...byKey.values()];
  _PT.referenceBrowserAssets = available;
  const filters = _PT.referenceBrowserFilters || _ptReferenceDefaultFilters(project, context);
  const agencies = [...new Set((_PT.projects || []).map(item => String(item.customer?.agency || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  if (!available.length) {
    return `<div class="proj-reference-browser-panel">
      <label class="proj-reference-empty-agency"><span>Agency</span><select id="reference-photo-agency">${agencies.map(value => `<option value="${esc(value)}" ${value.toLowerCase() === String(agency || filters.agency).toLowerCase() ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></label>
      <strong>No photos found for this agency.</strong>
      ${warnings.map(message => `<small>${esc(message)}</small>`).join("")}</div>`;
  }
  if (!(_PT.referenceBrowserSelected instanceof Set)) _PT.referenceBrowserSelected = new Set();
  const selectedCount = _PT.referenceBrowserSelected.size;
  const addLabel = context.scope === "project" ? "Add selected photos" : "Assign selected photos";
  return `<div class="proj-reference-browser-panel">
    <div class="proj-reference-browser-head"><strong>Choose existing photos</strong>
      <button type="button" class="btn btn-secondary btn-sm" id="reference-photo-clear-filters">Clear filters</button></div>
    <div class="proj-reference-browser-filters">
      <label><span>Agency</span><select id="reference-photo-agency">${agencies.map(value => `<option value="${esc(value)}" ${value.toLowerCase() === String(agency || filters.agency).toLowerCase() ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></label>
      <label><span>Make</span><select id="reference-photo-make">${_ptReferenceFilterOptions(available, "source_vehicle_make", filters.make, "All makes")}</select></label>
      <label><span>Model</span><select id="reference-photo-model">${_ptReferenceFilterOptions(available, "source_vehicle_model", filters.model, "All models")}</select></label>
      <label><span>Build type</span><select id="reference-photo-build-type">${_ptReferenceFilterOptions(available, "source_build_type", filters.buildType, "All build types")}</select></label>
      <label class="proj-reference-browser-search"><span>Filename or folder</span><input id="reference-photo-filter" type="search" value="${esc(filters.query || "")}" placeholder="Search year, unit, or filename"></label>
    </div>
    ${warnings.map(message => `<small>${esc(message)}</small>`).join("")}
    <div class="photo-gallery-selection-bar proj-reference-browser-selection">
      <button type="button" class="btn btn-primary btn-sm" id="reference-photo-add-selected" ${selectedCount ? "" : "disabled"}>${esc(addLabel)}</button>
      <span id="reference-photo-selected-count">${selectedCount} selected</span>
    </div>
    <div class="proj-reference-browser-results">${available.map((asset, index) => {
      const projectAsset = (project.reference_assets || []).find(item => _ptReferenceKey(item) === _ptReferenceKey(asset));
      const assigned = context.scope === "project"
        ? Boolean(projectAsset)
        : projectAsset ? Boolean(_ptCurrentReferenceAssignment(projectAsset, context)) : false;
      const companyOnlyVideo = asset.media_type === "video";
      const selectable = !assigned && !companyOnlyVideo && Boolean(asset.photo_token);
      const selected = selectable && _PT.referenceBrowserSelected.has(asset.photo_token);
      const stateLabel = companyOnlyVideo ? "Company only"
        : assigned ? (context.scope === "project" ? "In project" : "Assigned")
          : asset.photo_token ? "" : "Unavailable";
      const sourceTag = asset.source_kind === "shop_completed"
        ? "Completed build" : asset.media_type === "video" ? "Company video" : "Company photo";
      const title = asset.source_vehicle_name || [
        asset.source_build_year, asset.source_vehicle_model, asset.source_build_type,
      ].filter(Boolean).join(" ") || [asset.source_agency, asset.source_build_year].filter(Boolean).join(" ") || "Project photo";
      const notes = (projectAsset?.assignments || []).map(assignment => String(assignment.note || "").trim()).filter(Boolean);
      return `<article class="proj-reference-browser-row${selected ? " selected" : ""}" data-reference-browser-index="${index}"
        data-reference-filter="${esc(`${asset.source_path || ""} ${asset.file_name || ""} ${asset.source_build_year || ""}`.toLowerCase())}"
        data-reference-make="${esc(String(asset.source_vehicle_make || "").toLowerCase())}"
        data-reference-model="${esc(String(asset.source_vehicle_model || "").toLowerCase())}"
        data-reference-build-type="${esc(String(asset.source_build_type || "").toLowerCase())}">
        ${selectable ? `<label class="photo-gallery-select"><input type="checkbox" data-reference-select value="${esc(asset.photo_token)}" ${selected ? "checked" : ""}><span>Select</span></label>`
          : `<span class="proj-reference-browser-state">${esc(stateLabel)}</span>`}
        <div class="proj-reference-browser-thumb">${asset.media_type === "photo" && asset.thumbnail_url
          ? `${_ptThumbnailLoadingMarkup()}<img data-thumbnail-url="${esc(asset.thumbnail_url)}" alt="">`
          : `<span>${asset.media_type === "video" ? "VIDEO" : "PHOTO"}</span>`}
          ${asset.source_kind === "shop_completed" ? `<span class="photo-gallery-state-badge photo-gallery-state-badge--completed">✓ Completed</span>` : ""}</div>
        <div class="proj-reference-browser-copy"><strong>${esc(title)}</strong>
          <span class="proj-reference-browser-tags"><span>${esc(sourceTag)}</span></span>
          <small>${esc(asset.file_name || "Photo")}</small>${notes.length ? `<p>${esc(notes.join(" · "))}</p>` : ""}</div>
      </article>`;
    }).join("")}</div>
  </div>`;
}

async function _ptRefreshReferenceModal() {
  const context = _PT.referenceModalContext;
  if (!context) return;
  const project = await _ptRefreshProjectPhotoState(context.projectId);
  if (!project) return;
  PT_openReferencePhotos(
    context.projectId, context.unitId, context.individualId, context.scope,
    context.scope === "project",
  );
}

async function _ptSaveReferenceAsset(projectId, asset) {
  const response = await api(`/api/project/${encodeURIComponent(projectId)}/references/save`, { reference: asset });
  if (!response?.ok) throw new Error(response?.error || "Could not save reference assignment");
  return response.reference;
}

async function _ptSaveReferenceEdits() {
  const context = _PT.referenceModalContext;
  const project = _PT.projects.find(item => item.project_id === context?.projectId) || _PT.viewProject;
  if (!context || !project) return;
  const rows = [...document.querySelectorAll("#reference-photo-assigned .proj-reference-row[data-current='true']")];
  const status = $("reference-photo-status");
  try {
    if (status) _ptSetStatus(status, "Saving reference notes…", "loading");
    for (const row of rows) {
      const asset = (project.reference_assets || []).find(item => item.reference_id === row.dataset.referenceId);
      const assignment = asset && _ptCurrentReferenceAssignment(asset, context);
      if (!assignment) continue;
      assignment.note = row.querySelector("[data-reference-note]")?.value.trim() || "";
      await _ptSaveReferenceAsset(project.project_id, asset);
    }
    toast("Reference notes saved", "success");
    await _ptRefreshReferenceModal();
  } catch (error) {
    if (status) _ptSetStatus(status, error.message || "Could not save references", "err");
  }
}

async function _ptRemoveReference(referenceId) {
  const context = _PT.referenceModalContext;
  const project = _PT.projects.find(item => item.project_id === context?.projectId) || _PT.viewProject;
  const asset = (project?.reference_assets || []).find(item => item.reference_id === referenceId);
  if (!context || !project || !asset) return;
  const target = _ptReferenceTarget(context);
  try {
    if (context.scope === "project") {
      if (!confirm("Remove this photo from the project?\n\nThe original photo file will not be deleted.")) return;
      const response = await api(`/api/project/${encodeURIComponent(project.project_id)}/references/${encodeURIComponent(referenceId)}/delete`, {});
      if (!response?.ok) throw new Error(response?.error || "Could not remove reference assignment");
      toast("Reference removed from the project", "success");
    } else {
      asset.assignments = (asset.assignments || []).filter(assignment => !(
        assignment.scope === "unit_group" && String(assignment.target_id || "") === target
      ));
      await _ptSaveReferenceAsset(project.project_id, asset);
      toast(asset.assignments.length ? "Photo removed from this unit group" : "Photo is now unassigned", "success");
    }
    await _ptRefreshReferenceModal();
  } catch (error) {
    toast(error.message || "Could not remove reference", "error");
  }
}

function _ptUpdateReferenceBrowserSelection() {
  const count = _PT.referenceBrowserSelected?.size || 0;
  const label = $("reference-photo-selected-count");
  const button = $("reference-photo-add-selected");
  if (label) label.textContent = `${count} selected`;
  if (button) button.disabled = count === 0;
}

async function _ptAddSelectedReferences() {
  const context = _PT.referenceModalContext;
  const project = _PT.projects.find(item => item.project_id === context?.projectId) || _PT.viewProject;
  const tokens = [...(_PT.referenceBrowserSelected || [])];
  if (!context || !project || !tokens.length) return;
  const status = $("reference-photo-status");
  const button = $("reference-photo-add-selected");
  if (button) button.disabled = true;
  try {
    if (status) _ptSetStatus(status, context.scope === "project" ? "Adding photos…" : "Assigning photos…", "loading");
    const response = await api(`/api/project/${encodeURIComponent(project.project_id)}/references/import-gallery`, {
      source_project_id: project.project_id,
      photo_tokens: tokens,
      target_unit_id: context.scope === "unit_group" ? context.unitId : "",
    });
    if (!response?.ok) throw new Error(response?.error || "Could not add the selected photos");
    const added = Number(response.added) || 0;
    const already = Number(response.already_in_project ?? response.already_assigned) || 0;
    await _ptRefreshProjectPhotoState(project.project_id);
    toast(added
      ? `${added} photo${added === 1 ? "" : "s"} ${context.scope === "project" ? "added" : "assigned"}`
      : already ? "Those photos are already assigned" : "No photos were added", added ? "success" : "info");
    _PT.referenceBrowserSelected = new Set();
    PT_openReferencePhotos(project.project_id, context.unitId, "", context.scope, true);
  } catch (error) {
    if (status) _ptSetStatus(status, error.message || "Could not add the selected photos", "err");
    if (button) button.disabled = false;
  }
}

async function _ptBrowseAgencyReferences() {
  const context = _PT.referenceModalContext;
  const project = _PT.projects.find(item => item.project_id === context?.projectId) || _PT.viewProject;
  const browser = $("reference-photo-browser");
  if (!context || !project || !browser) return;
  _PT.referenceBrowserFilters = _ptReferenceDefaultFilters(project, context);
  _PT.referenceBrowserSelected = new Set();
  try {
    const gallery = await api(`/api/project/${encodeURIComponent(project.project_id)}/photo-gallery`, { kind: "reference" });
    _PT.referenceThumbnailByKey = new Map((gallery?.photos || []).map(item => [item.source_key, item]));
  } catch (_) {
    _PT.referenceThumbnailByKey = new Map();
  }
  await _ptLoadReferenceAgency();
}

async function _ptLoadReferenceAgency() {
  const context = _PT.referenceModalContext;
  const project = _PT.projects.find(item => item.project_id === context?.projectId) || _PT.viewProject;
  const browser = $("reference-photo-browser");
  if (!context || !project || !browser) return;
  const agency = String(_PT.referenceBrowserFilters?.agency || project.customer?.agency || "");
  browser.hidden = false;
  browser.innerHTML = `<div class="proj-reference-browser-panel dtm-loading"><span class="dtm-loading-spinner"></span><strong>Loading ${esc(agency || "this agency")}'s organized media…</strong></div>`;
  try {
    let response = null;
    for (let attempt = 0; attempt < 90; attempt += 1) {
      response = await api(`/api/project/${encodeURIComponent(project.project_id)}/references/discover`, { agency });
      if (!response?.ok) throw new Error(response?.error || "Could not browse agency photos");
      if (!response.loading) break;
      browser.innerHTML = `<div class="proj-reference-browser-panel dtm-loading"><span class="dtm-loading-spinner"></span><strong>Scanning ${esc(agency)}…</strong></div>`;
      await new Promise(resolve => setTimeout(resolve, 600));
    }
    if (response?.loading) throw new Error("The agency photo scan is taking longer than expected.");
    browser.innerHTML = _ptReferenceBrowserMarkup(
      project, context, response.references || [], response.warnings || [], response.agency || agency,
    );
    _ptBindReferenceBrowserActions();
    _ptBindThumbnailLoading(browser);
  } catch (error) {
    browser.innerHTML = `<div class="proj-reference-browser-panel"><strong>Could not browse agency media.</strong><p>${esc(error.message || "Try again after cloud sign-in.")}</p></div>`;
  }
}

function _ptBindReferenceBrowserActions() {
  const applyFilters = () => {
    const filters = _PT.referenceBrowserFilters || {};
    const query = String(filters.query || "").trim().toLowerCase();
    const matchesField = (candidate, wanted) => {
      if (!wanted) return true;
      candidate = String(candidate || "").toLowerCase();
      wanted = String(wanted || "").toLowerCase();
      return candidate.includes(wanted) || wanted.includes(candidate);
    };
    document.querySelectorAll("[data-reference-filter]").forEach(row => {
      row.hidden = (Boolean(query) && !String(row.dataset.referenceFilter || "").includes(query)) ||
        !matchesField(row.dataset.referenceMake, filters.make) ||
        !matchesField(row.dataset.referenceModel, filters.model) ||
        !matchesField(row.dataset.referenceBuildType, filters.buildType);
    });
  };
  $("reference-photo-filter")?.addEventListener("input", event => {
    _PT.referenceBrowserFilters.query = String(event.target.value || "");
    applyFilters();
  });
  for (const [id, key] of [
    ["reference-photo-make", "make"],
    ["reference-photo-model", "model"],
    ["reference-photo-build-type", "buildType"],
  ]) {
    $(id)?.addEventListener("change", event => {
      _PT.referenceBrowserFilters[key] = String(event.target.value || "");
      applyFilters();
    });
  }
  $("reference-photo-agency")?.addEventListener("change", event => {
    _PT.referenceBrowserFilters.agency = String(event.target.value || "");
    _PT.referenceBrowserSelected = new Set();
    _ptLoadReferenceAgency();
  });
  $("reference-photo-clear-filters")?.addEventListener("click", () => {
    Object.assign(_PT.referenceBrowserFilters, { make: "", model: "", buildType: "", query: "" });
    for (const id of ["reference-photo-make", "reference-photo-model", "reference-photo-build-type", "reference-photo-filter"]) {
      const input = $(id);
      if (input) input.value = "";
    }
    applyFilters();
  });
  document.querySelectorAll("[data-reference-select]").forEach(input => {
    input.addEventListener("change", () => {
      if (!(_PT.referenceBrowserSelected instanceof Set)) _PT.referenceBrowserSelected = new Set();
      if (input.checked) _PT.referenceBrowserSelected.add(input.value);
      else _PT.referenceBrowserSelected.delete(input.value);
      input.closest("[data-reference-browser-index]")?.classList.toggle("selected", input.checked);
      _ptUpdateReferenceBrowserSelection();
    });
  });
  $("reference-photo-add-selected")?.addEventListener("click", _ptAddSelectedReferences);
  _ptUpdateReferenceBrowserSelection();
  applyFilters();
}

window.PT_openReferencePhotos = function (projectId, unitId = "", individualId = "", scope = "project", browseNow = false) {
  const project = _PT.projects.find(item => item.project_id === projectId) || _PT.viewProject;
  if (!project) return;
  const context = _ptReferenceContext(projectId, unitId, individualId, scope);
  _PT.referenceModalContext = context;
  _PT.referenceBrowserAssets = [];
  const pickerOnly = browseNow || context.scope === "project";
  const title = context.scope === "unit_group" ? "Add Build Reference Photos" : "Add Project Photos";
  const modal = $("reference-photo-modal");
  $("reference-photo-modal-title").textContent = title;
  $("reference-photo-modal-body").innerHTML = pickerOnly
    ? `<div id="reference-photo-browser"></div><div id="reference-photo-status" class="proj-action-status" style="display:none"></div>`
    : _ptReferenceModalMarkup(project, context);
  $("reference-photo-browse")?.addEventListener("click", _ptBrowseAgencyReferences);
  $("reference-photo-assigned")?.querySelector("[data-reference-empty-browse]")?.addEventListener("click", _ptBrowseAgencyReferences);
  if (context.scope === "unit_group") _ptHydrateAssignedReferenceThumbnails(projectId, context.unitId, "");
  document.querySelectorAll("#reference-photo-assigned [data-reference-remove]").forEach(button => {
    button.addEventListener("click", () => {
      const row = button.closest("[data-reference-id]");
      if (row) _ptRemoveReference(row.dataset.referenceId);
    });
  });
  const save = $("reference-photo-modal-save");
  if (save) {
    save.style.display = context.scope === "unit_group" && document.querySelector("#reference-photo-assigned [data-current='true']") ? "" : "none";
    save.onclick = _ptSaveReferenceEdits;
  }
  modal?.removeAttribute("hidden");
  modal?.classList.add("open");
  $("reference-photo-modal-close")?.focus();
  if (pickerOnly) _ptBrowseAgencyReferences();
};

function _ptCloseReferencePhotos() {
  _ptReleaseThumbnailLoading();
  const modal = $("reference-photo-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  const returnGallery = _PT.referenceReturnGallery;
  _PT.referenceReturnGallery = null;
  if (returnGallery?.projectId) {
    PT_openPhotoGallery(
      returnGallery.projectId,
      returnGallery.kind || "reference",
      returnGallery.unitId || "",
    );
  }
}

async function _ptHydrateAssignedReferenceThumbnails(projectId, unitId, individualId) {
  try {
    const response = await api(`/api/project/${encodeURIComponent(projectId)}/photo-gallery`, {
      kind: "reference", unit_id: unitId || "", individual_id: individualId || "",
    });
    if (!response?.ok) return;
    const byKey = new Map((response.photos || []).map(item => [item.source_key, item]));
    document.querySelectorAll("#reference-photo-assigned [data-reference-key]").forEach(row => {
      const item = byKey.get(row.dataset.referenceKey || "");
      const holder = row.querySelector(".proj-reference-file-icon");
      if (!item?.thumbnail_url || !holder) return;
      holder.innerHTML = `${_ptThumbnailLoadingMarkup()}<img data-thumbnail-url="${esc(item.thumbnail_url)}" alt="">`;
    });
    _ptBindThumbnailLoading($("reference-photo-assigned"));
  } catch (_) {}
}

function _pbeRenderReferenceSummary() {
  const holder = $("pbe-reference-photos-content");
  if (!holder) return;
  const project = _PT.pbeProject;
  const unit = _PT.pbeUnit;
  const individual = _PT.pbeIndividual;
  if (!project || !unit) {
    holder.innerHTML = "";
    return;
  }
  const items = _ptEffectiveReferencePhotos(project, unit.unit_id, individual?.individual_id || "");
  holder.innerHTML = `<div class="pbe-reference-summary">
    <div><strong>Build Reference Photos</strong><span>${items.length} assigned to this unit group</span></div>
    <button class="btn btn-secondary btn-sm" type="button"
      onclick="PT_openPhotoGallery('${esc(project.project_id)}','reference','${esc(unit.unit_id)}')">Manage references</button>
  </div>`;
}

function _ptBindReferencePhotoModal() {
  const modal = $("reference-photo-modal");
  if (!modal || modal.dataset.wired === "true") return;
  modal.dataset.wired = "true";
  $("reference-photo-modal-close")?.addEventListener("click", _ptCloseReferencePhotos);
  $("reference-photo-modal-done")?.addEventListener("click", _ptCloseReferencePhotos);
  modal.addEventListener("click", event => {
    if (event.target === modal) _ptCloseReferencePhotos();
  });
  const gallery = $("photo-gallery-modal");
  if (gallery && gallery.dataset.wired !== "true") {
    gallery.dataset.wired = "true";
    $("photo-gallery-close")?.addEventListener("click", _ptClosePhotoGallery);
    $("photo-gallery-done")?.addEventListener("click", _ptClosePhotoGallery);
    gallery.addEventListener("click", event => {
      if (event.target === gallery) _ptClosePhotoGallery();
    });
  }
  const useModal = $("photo-use-modal");
  if (useModal && useModal.dataset.wired !== "true") {
    useModal.dataset.wired = "true";
    $("photo-use-close")?.addEventListener("click", _ptClosePhotoUseModal);
    $("photo-use-cancel")?.addEventListener("click", _ptClosePhotoUseModal);
    $("photo-use-confirm")?.addEventListener("click", _ptConfirmPhotoUse);
    $("photo-use-project")?.addEventListener("change", _ptUpdatePhotoUseGroups);
    $("photo-use-unit-group")?.addEventListener("change", event => {
      if (_PT.photoUseMode === "assign") {
        $("photo-use-confirm").disabled = !String(event.target.value || "");
      }
    });
    useModal.addEventListener("click", event => {
      if (event.target === useModal) _ptClosePhotoUseModal();
    });
  }
}
