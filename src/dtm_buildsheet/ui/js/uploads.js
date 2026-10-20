// Durable project-media upload queue. Local staging progress comes from XHR;
// cloud progress is polled from the backend-owned job manifests.
(function () {
  const token = document.querySelector('meta[name="dtm-upload-token"]')?.content || "";
  const state = {
    jobs: [],
    activeCount: 0,
    unacknowledgedCompleteCount: 0,
    staging: new Map(),
    pollTimer: null,
    progressSamples: new Map(),
  };

  function capability(name) {
    return typeof appHasCapability === "function" && appHasCapability(name);
  }

  async function request(path, body) {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      cache: "no-store",
      headers: body === undefined ? {} : {
        "Content-Type": "application/json",
        "X-DTM-Upload-Token": token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.error || `Upload request failed (${response.status})`);
    }
    return payload;
  }

  function bytes(value) {
    const amount = Number(value) || 0;
    if (amount < 1024) return `${amount} B`;
    if (amount < 1024 * 1024) return `${(amount / 1024).toFixed(1)} KB`;
    if (amount < 1024 * 1024 * 1024) return `${(amount / 1024 / 1024).toFixed(1)} MB`;
    return `${(amount / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  function acknowledgeCompleteNotice() {
    if (!state.unacknowledgedCompleteCount) {
      schedulePoll(0);
      return Promise.resolve();
    }
    state.unacknowledgedCompleteCount = 0;
    const acknowledgedAt = new Date().toISOString();
    state.jobs = state.jobs.map(job =>
      job.status === "complete" && !job.acknowledged_at
        ? {...job, acknowledged_at: acknowledgedAt}
        : job
    );
    render();
    return request("/api/uploads/acknowledge", {})
      .catch(() => {})
      .finally(() => schedulePoll(0));
  }

  function openManager({acknowledgeComplete = false} = {}) {
    const modal = $("upload-manager-modal");
    modal?.removeAttribute("hidden");
    modal?.classList.add("open");
    render();
    if (acknowledgeComplete) acknowledgeCompleteNotice();
    else schedulePoll(0);
  }

  function closeManager() {
    const modal = $("upload-manager-modal");
    modal?.classList.remove("open");
    if (modal) modal.hidden = true;
  }

  function jobDetail(job) {
    const local = state.staging.get(job.job_id);
    if (local) return `Copying locally · ${bytes(local.loaded)} of ${bytes(local.total)}`;
    if (job.status === "uploading") {
      const now = Date.now();
      const uploaded = Number(job.bytes_uploaded) || 0;
      const previous = state.progressSamples.get(job.job_id);
      let speed = previous?.speed || 0;
      if (previous && uploaded >= previous.uploaded && now > previous.time) {
        const currentSpeed = (uploaded - previous.uploaded) / ((now - previous.time) / 1000);
        if (currentSpeed > 0) speed = previous.speed ? previous.speed * 0.65 + currentSpeed * 0.35 : currentSpeed;
      }
      state.progressSamples.set(job.job_id, {uploaded, time: now, speed});
      const remaining = Math.max(0, (Number(job.upload_size) || 0) - uploaded);
      const seconds = speed > 0 ? Math.ceil(remaining / speed) : 0;
      const eta = seconds > 0 ? ` · ${seconds < 60 ? `${seconds}s` : `${Math.ceil(seconds / 60)}m`} remaining` : "";
      return `${job.phase} · ${bytes(uploaded)} of ${bytes(job.upload_size)}${speed > 0 ? ` · ${bytes(speed)}/s` : ""}${eta}`;
    }
    if (job.converted_from) return `${job.phase} · converted from ${job.converted_from} to JPG`;
    return job.phase || job.status || "Waiting";
  }

  function render() {
    const button = $("upload-status");
    const text = $("upload-status-text");
    const attention = state.jobs.filter(job => job.status === "failed").length;
    const complete = state.unacknowledgedCompleteCount;
    if (button) {
      button.hidden = !state.activeCount && !attention && !complete && state.staging.size === 0;
      button.classList.toggle("needs-attention", attention > 0);
      button.classList.toggle("complete", !state.activeCount && !attention && complete > 0);
    }
    if (text) {
      text.textContent = attention
        ? `${attention} upload${attention === 1 ? "" : "s"} need attention`
        : state.activeCount
          ? `Uploading ${state.activeCount}`
          : complete ? "Uploads complete" : "Uploads";
    }
    const summary = $("upload-manager-summary");
    if (summary) {
      summary.textContent = attention
        ? `${attention} file${attention === 1 ? "" : "s"} need attention. Other uploads continue in the background.`
        : state.activeCount
          ? `${state.activeCount} file${state.activeCount === 1 ? " is" : "s are"} still being prepared or uploaded.`
          : state.jobs.length ? "All uploads are finished." : "No uploads yet.";
    }
    const list = $("upload-manager-list");
    if (!list) return;
    if (!state.jobs.length) {
      list.innerHTML = `<div class="photo-gallery-empty"><strong>No uploads yet.</strong></div>`;
      return;
    }
    list.innerHTML = state.jobs.map(job => {
      const local = state.staging.get(job.job_id);
      const percent = local
        ? Math.min(100, local.total ? local.loaded * 100 / local.total : 0)
        : Number(job.progress_percent) || (job.status === "complete" ? 100 : 0);
      const canRetry = ["failed", "waiting"].includes(job.status) && job.can_retry !== false;
      const canCancel = !["complete", "canceled"].includes(job.status);
      return `<article class="upload-job ${esc(job.status || "")}">
        <div class="upload-job-main">
          <strong class="upload-job-name">${esc(job.stored_name || job.original_name || "File")}</strong>
          <span class="upload-job-detail">${esc(jobDetail(job))}</span>
        </div>
        <div class="upload-job-actions">
          ${canRetry ? `<button class="btn btn-secondary btn-sm" type="button" data-upload-retry="${esc(job.job_id)}" data-upload-kind="${esc(job.destination_kind)}">Retry</button>` : ""}
          ${canCancel ? `<button class="btn btn-danger btn-sm" type="button" data-upload-cancel="${esc(job.job_id)}" data-upload-kind="${esc(job.destination_kind)}">Cancel</button>` : ""}
        </div>
        <div class="upload-job-progress" role="progressbar" aria-label="Upload progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(percent)}"><span style="width:${percent}%"></span></div>
        ${job.error ? `<div class="upload-job-error">${esc(job.error)}</div>` : ""}
      </article>`;
    }).join("");
  }

  async function refresh() {
    try {
      const result = await request("/api/uploads/status");
      const previouslyActive = state.activeCount > 0;
      state.jobs = result.jobs || [];
      state.activeCount = Number(result.active_count) || 0;
      state.unacknowledgedCompleteCount = Number(result.unacknowledged_complete_count) || 0;
      render();
      if (previouslyActive && state.activeCount === 0) {
        const context = window._PT?.photoGalleryContext;
        const gallery = $("photo-gallery-modal");
        const reload = context?.projectId
          ? refreshUploadedProject(context.projectId).catch(() => null)
          : typeof _ptLoadAll === "function" ? _ptLoadAll().catch(() => {}) : Promise.resolve();
        if (context?.projectId && gallery?.classList.contains("open") && typeof PT_openPhotoGallery === "function") {
          reload.then(() => PT_openPhotoGallery(
            context.projectId, context.kind, context.unitId || "", context.individualId || "",
          ));
        }
      }
    } catch (_) {
      // The local server may be stopping. Keep the last useful state visible.
    }
    schedulePoll(state.activeCount || $("upload-manager-modal")?.classList.contains("open") ? 1000 : 5000);
  }

  function schedulePoll(delay) {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(refresh, delay);
  }

  async function refreshUploadedProject(projectId) {
    if (!projectId || typeof api !== "function" || !window._PT) return null;
    const response = await api(`/api/project/${encodeURIComponent(projectId)}`);
    if (!response?.ok || !response.project) return null;
    const project = response.project;
    const index = (_PT.projects || []).findIndex(item => item.project_id === projectId);
    if (index >= 0) _PT.projects.splice(index, 1, project);
    else _PT.projects.unshift(project);
    if (_PT.viewProject?.project_id === projectId) {
      _PT.viewProject = project;
      if (typeof _ptRenderOverview === "function") _ptRenderOverview(project);
    }
    if (_PT.pbeProject?.project_id === projectId) {
      _PT.pbeProject = project;
      if (typeof _pbeRenderReferenceSummary === "function") _pbeRenderReferenceSummary();
    }
    return project;
  }

  function stage(job, file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/uploads/${encodeURIComponent(job.destination_kind)}/${encodeURIComponent(job.job_id)}/content`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("X-DTM-Upload-Token", token);
      xhr.upload.onprogress = event => {
        if (!event.lengthComputable) return;
        state.staging.set(job.job_id, {loaded: event.loaded, total: event.total});
        render();
      };
      xhr.onload = () => {
        state.staging.delete(job.job_id);
        let payload = {};
        try { payload = JSON.parse(xhr.responseText || "{}"); } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300 && payload?.ok) resolve(payload.job);
        else reject(new Error(payload?.error || `Could not stage ${file.name}`));
      };
      xhr.onerror = () => {
        state.staging.delete(job.job_id);
        reject(new Error(`Could not stage ${file.name}`));
      };
      xhr.send(file);
    });
  }

  async function uploadFiles(files, context) {
    const destination = context.kind === "completed" ? "completed" : "project";
    openManager();
    for (const file of files) {
      try {
        const created = await request(`/api/uploads/${destination}/create`, {
          project_id: context.projectId,
          unit_id: context.unitId || "",
          individual_id: context.individualId || "",
          file_name: file.name,
          file_size: file.size,
          content_type: file.type || "application/octet-stream",
        });
        state.jobs.unshift(created.job);
        state.activeCount += 1;
        render();
        await stage(created.job, file);
      } catch (error) {
        toast(error.message || `Could not upload ${file.name}`, "error");
      }
      await refresh();
    }
  }

  function choose(context) {
    const completed = context.kind === "completed";
    if (completed && !capability("completed_media.upload")) return;
    if (!completed && !capability("project_media.upload")) return;
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = completed
      ? ".jpg,.jpeg,.png,.heic,.heif,.webp,.mp4,.mov,.m4v,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip"
      : ".jpg,.jpeg,.png,.heic,.heif,.webp,.mp4,.mov,.m4v,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip";
    input.addEventListener("change", () => {
      if (input.files?.length) uploadFiles([...input.files], context);
    }, {once: true});
    input.click();
  }

  async function action(kind, jobId, actionName) {
    try {
      await request(`/api/uploads/${encodeURIComponent(kind)}/${encodeURIComponent(jobId)}/${actionName}`, {});
      await refresh();
    } catch (error) {
      toast(error.message || `Could not ${actionName} upload`, "error");
    }
  }

  function requestCloseFromNative() {
    const count = state.activeCount || state.jobs.filter(job => !["complete", "failed", "canceled"].includes(job.status)).length;
    const copy = $("upload-close-warning-copy");
    if (copy) copy.textContent = `${count || "One or more"} file${count === 1 ? " is" : "s are"} still uploading. Closing will cancel the active SharePoint transfer. Files already staged locally will resume next time.`;
    const modal = $("upload-close-warning");
    modal?.removeAttribute("hidden");
    modal?.classList.add("open");
  }

  window.DTMUploads = {
    choose,
    openManager,
    requestCloseFromNative,
    chooseFromGallery() {
      const context = window._PT?.photoGalleryContext;
      if (context?.projectId) choose(context);
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    $("upload-status")?.addEventListener("click", () => openManager({acknowledgeComplete: true}));
    $("upload-manager-close")?.addEventListener("click", closeManager);
    $("upload-manager-done")?.addEventListener("click", closeManager);
    $("upload-manager-list")?.addEventListener("click", event => {
      const retry = event.target.closest("[data-upload-retry]");
      const cancel = event.target.closest("[data-upload-cancel]");
      if (retry) action(retry.dataset.uploadKind, retry.dataset.uploadRetry, "retry");
      if (cancel) action(cancel.dataset.uploadKind, cancel.dataset.uploadCancel, "cancel");
    });
    $("upload-close-view")?.addEventListener("click", () => {
      const warning = $("upload-close-warning");
      warning?.classList.remove("open");
      if (warning) warning.hidden = true;
      openManager();
    });
    $("upload-close-anyway")?.addEventListener("click", async () => {
      if (window.pywebview?.api?.close_anyway) await window.pywebview.api.close_anyway();
      else window.close();
    });
    refresh();
  });

  window.addEventListener("beforeunload", event => {
    if (!state.activeCount || window.pywebview?.api) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
