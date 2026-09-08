// ── Role-gated Operations workspace + one-vehicle creation pilot ────────────

const _OPERATIONS = {
  session: null,
  payload: null,
  projectionPreview: null,
  filter: "active",
  loading: false,
  editVehicles: [],
  editScopeLabel: "",
  statusSaving: false,
  historyRequest: 0,
  scheduleVehicles: [],
  scheduleInitial: {},
  scheduleDirty: new Set(),
  scheduleSaving: false,
};

const _OPERATIONS_STATUS_DEFS = [
  {
    key: "acceptance",
    label: "Acceptance",
    capability: "estimates.manage",
    field: "acceptance_status",
    values: [["not_accepted", "Not accepted"], ["accepted", "Accepted"]],
  },
  {
    key: "availability",
    label: "Vehicle availability",
    capability: "operations.availability.update",
    field: "vehicle_availability_status",
    values: [
      ["awaiting_details", "Awaiting details"],
      ["waiting_on_dealer", "Waiting on dealer"],
      ["waiting_on_agency", "Waiting on agency"],
      ["ready_for_pickup", "Ready for pickup"],
      ["at_dtm", "At DTM"],
    ],
  },
  {
    key: "parts",
    label: "Parts",
    capability: "operations.parts.update",
    field: "parts_status",
    values: [
      ["", "Not started"],
      ["ordered", "Ordered"],
      ["partially_received", "Partially received"],
      ["received", "Received"],
      ["parts_ready", "Parts ready"],
    ],
    normal: {
      "": ["ordered", "partially_received", "received"],
      ordered: ["partially_received", "received"],
      partially_received: ["received"],
      received: ["parts_ready"],
      parts_ready: [],
    },
  },
  {
    key: "shop",
    label: "Build / Shop",
    capability: "operations.shop.update",
    field: "shop_status",
    values: [["", "Not started"], ["in_progress", "In progress"], ["complete", "Complete"]],
    normal: { "": ["in_progress"], in_progress: ["complete"], complete: [] },
  },
  {
    key: "tray",
    label: "Tray",
    capability: "operations.tray.update",
    field: "tray_status",
    values: [["not_ready", "Not ready"], ["ready", "Ready"], ["complete", "Complete"]],
    normal: { not_ready: ["ready"], ready: ["complete"], complete: [] },
  },
  {
    key: "programming_qc",
    label: "Programming & QC",
    capability: "operations.programming_qc.update",
    field: "programming_qc_status",
    values: [["not_ready", "Not ready"], ["ready", "Ready"], ["complete", "Complete"]],
    normal: { not_ready: ["ready"], ready: ["complete"], complete: [] },
  },
  {
    key: "final_finish",
    label: "Final Finish",
    capability: "operations.final_finish.update",
    field: "final_finish_status",
    values: [
      ["not_ready", "Not ready"],
      ["ready_for_wash_clean_photos", "Ready for wash, clean & photos"],
      ["ready_for_delivery", "Ready for delivery"],
      ["delivered", "Delivered"],
    ],
    normal: {
      not_ready: ["ready_for_wash_clean_photos"],
      ready_for_wash_clean_photos: ["ready_for_delivery"],
      ready_for_delivery: ["delivered"],
      delivered: [],
    },
  },
];

const _OPERATIONS_FINISHED_STATUS = {
  acceptance: new Set(["accepted"]),
  availability: new Set(["at_dtm", "delivered"]),
  parts: new Set(["parts_ready"]),
  shop: new Set(["complete"]),
  tray: new Set(["complete"]),
  programming_qc: new Set(["complete"]),
  final_finish: new Set(["delivered"]),
};

const _OPERATIONS_UNSTARTED_STATUS = {
  acceptance: new Set(["not_accepted"]),
  availability: new Set(["awaiting_details"]),
  parts: new Set(["", "not_started"]),
  shop: new Set(["", "not_started"]),
  tray: new Set(["not_ready"]),
  programming_qc: new Set(["not_ready"]),
  final_finish: new Set(["not_ready"]),
};

function _operationsStatusTone(key, value) {
  if (value === "mixed") return "intermediate";
  if (_OPERATIONS_FINISHED_STATUS[key]?.has(value)) return "complete";
  if (_OPERATIONS_UNSTARTED_STATUS[key]?.has(value)) return "unstarted";
  return "intermediate";
}

function _operationsEscAttr(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _operationsEditableWorkstreams() {
  const capabilities = new Set(_OPERATIONS.session?.capabilities || []);
  if (!_OPERATIONS.session?.operations_write_ready) return [];
  return _OPERATIONS_STATUS_DEFS.filter(item => capabilities.has(item.capability));
}

function _operationsCanSchedule() {
  return !!_OPERATIONS.session?.operations_write_ready &&
    (_OPERATIONS.session?.capabilities || []).includes("operations.schedule.update");
}

function _operationsCanView(session) {
  return !!session?.authenticated &&
    (session.capabilities || []).includes("operations.view") &&
    !!session.operations_ready;
}

function _operationsCanAddBuilderVehicle(session) {
  return _operationsCanView(session) &&
    (session.capabilities || []).includes("projects.edit") &&
    !!session.operations_write_ready;
}

async function initOperationsAccess() {
  const button = $("operations-header-tab");
  if (!button) return null;
  try {
    const session = await api("/api/operations/session");
    _OPERATIONS.session = session;
    button.hidden = !_operationsCanView(session);
    const addButton = $("operations-add-builder");
    if (addButton) addButton.hidden = !_operationsCanAddBuilderVehicle(session);
    return session;
  } catch (error) {
    console.warn("Operations access check failed", error);
    button.hidden = true;
    const addButton = $("operations-add-builder");
    if (addButton) addButton.hidden = true;
    return null;
  }
}

async function initOperationsTab() {
  if (_OPERATIONS.loading) return;
  _OPERATIONS.loading = true;
  _operationsShowMessage("Loading the shared production backlog…");
  try {
    const session = await initOperationsAccess();
    if (!_operationsCanView(session)) {
      _operationsShowMessage(_operationsAccessMessage(session), "warning");
      return;
    }
    const payload = await api("/api/operations/vehicles");
    if (!payload?.ok) {
      _operationsShowMessage(payload?.error || "Operations data is unavailable", "error");
      return;
    }
    _OPERATIONS.payload = payload;
    _OPERATIONS.projectionPreview = null;
    _operationsRender();
    if (!(payload.vehicles || []).length && _operationsCanAddBuilderVehicle(session)) {
      await _operationsLoadProjectionPreview({ open: true, quiet: true });
    }
  } catch (error) {
    console.error("Operations load failed", error);
    _operationsShowMessage("Operations data is temporarily unavailable", "error");
  } finally {
    _OPERATIONS.loading = false;
  }
}

function _operationsAccessMessage(session) {
  if (!session?.authenticated) return "Sign in with Microsoft 365 to view Operations.";
  if (!(session.capabilities || []).includes("operations.view")) {
    return "Your Microsoft account has not been assigned an Operations role yet.";
  }
  if (!session.operations_ready) return "The Operations data connection is not configured.";
  return "Operations access is unavailable.";
}

function _operationsShowMessage(message, kind = "info") {
  const box = $("operations-message");
  box.textContent = message;
  box.className = `operations-message operations-message-${kind}`;
  box.hidden = false;
  $("operations-content").hidden = true;
}

function _operationsRender() {
  const payload = _OPERATIONS.payload || { vehicles: [], counts: {} };
  const counts = payload.counts || {};
  $("operations-message").hidden = true;
  $("operations-content").hidden = false;
  $("operations-metrics").innerHTML = [
    ["Active", counts.active || 0],
    ["Unscheduled", counts.unscheduled || 0],
    ["Scheduled", counts.scheduled || 0],
    ["Must deliver", (payload.vehicles || []).filter(item => item.project_state === "active" && item.must_deliver_by_date).length],
  ].map(([label, value]) => `<div class="operations-metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
  _operationsRenderProjectionPanel();
  _operationsRenderRows();
}

async function _operationsLoadProjectionPreview({ open = false, quiet = false } = {}) {
  const button = $("operations-add-builder");
  if (button) button.disabled = true;
  try {
    const preview = await api("/api/operations/projection-preview");
    if (!preview?.ok) {
      if (!quiet) toast(preview?.error || "Builder vehicles could not be loaded", "error");
      return;
    }
    _OPERATIONS.projectionPreview = preview;
    _operationsRenderProjectionPanel({ open });
    _operationsRenderRows();
  } catch (error) {
    console.error("Operations projection preview unavailable", error);
    if (!quiet) toast("Builder vehicles could not be loaded", "error");
  } finally {
    if (button) button.disabled = false;
  }
}

function _operationsRenderProjectionPanel({ open = false } = {}) {
  const panel = $("operations-projection-panel");
  if (!panel) return;
  const preview = _OPERATIONS.projectionPreview;
  if (!preview) {
    panel.innerHTML = "";
    panel.hidden = true;
    return;
  }
  const pending = (preview.vehicles || [])
    .filter(item => item.projection_state === "new" && item.project_state !== "inactive");
  const hasRecords = !!(_OPERATIONS.payload?.vehicles || []).length;
  const wasOpen = !!panel.querySelector("details")?.open;
  panel.classList.toggle("operations-projection-panel-empty", !hasRecords);
  if (hasRecords) {
    panel.innerHTML = `<details class="operations-projection-disclosure"${open || wasOpen ? " open" : ""}>
      <summary>
        <strong>Add Builder vehicle</strong>
        <span>${pending.length} available</span>
      </summary>
      <div class="operations-projection-body">${_operationsProjectionPreviewMarkup(preview)}</div>
    </details>`;
  } else {
    panel.innerHTML = _operationsProjectionPreviewMarkup(preview);
  }
  panel.hidden = false;
  _operationsBindProjectionPreview();
}

function _operationsRenderRows() {
  const needle = String($("operations-search")?.value || "").trim().toLowerCase();
  const openProjectIds = new Set(
    [...document.querySelectorAll(".operations-project-group[open]")]
      .map(item => item.dataset.operationsProjectId)
  );
  const vehicles = (_OPERATIONS.payload?.vehicles || []).filter(vehicle => {
    const filter = _OPERATIONS.filter;
    return filter === "active"
      ? vehicle.project_state === "active"
      : filter === "completed"
        ? vehicle.project_state === "completed"
        : vehicle.project_state === "active" && vehicle.schedule_bucket === filter;
  });

  const grouped = new Map();
  vehicles.forEach(vehicle => {
    const key = vehicle.project_id || `vehicle:${vehicle.vehicle_id}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(vehicle);
  });
  const projects = [...grouped.entries()]
    .map(([projectId, projectVehicles]) => ({ projectId, vehicles: projectVehicles }))
    .filter(project => !needle || project.vehicles.some(vehicle => [
      vehicle.vehicle_label,
      vehicle.title,
      vehicle.agency_name,
      vehicle.build_year,
      vehicle.unit_number,
      vehicle.vin,
      vehicle.qbo_estimate_number,
    ].some(value => String(value || "").toLowerCase().includes(needle))));

  document.querySelectorAll(".operations-filter").forEach(button => {
    button.classList.toggle("active", button.dataset.operationsFilter === _OPERATIONS.filter);
  });

  const empty = $("operations-empty");
  const rows = $("operations-rows");
  if (!projects.length) {
    rows.innerHTML = "";
    if ((_OPERATIONS.payload?.vehicles || []).length) {
      empty.textContent = "No vehicles match this view.";
    } else {
      empty.textContent = "No Operations records exist yet.";
    }
    empty.hidden = !(_OPERATIONS.payload?.vehicles || []).length &&
      !!_OPERATIONS.projectionPreview;
    return;
  }
  empty.hidden = true;
  rows.innerHTML = projects.map(project => _operationsProjectGroupMarkup(
    project,
    !!needle || openProjectIds.has(project.projectId),
  )).join("");
  _operationsBindRowActions();
}

function _operationsCommonValue(vehicles, field, fallback = "") {
  const values = new Set(vehicles.map(vehicle => String(vehicle[field] ?? fallback)));
  return values.size === 1 ? [...values][0] : "mixed";
}

function _operationsProjectAcceptance(vehicles) {
  const accepted = vehicles.filter(vehicle => vehicle.acceptance_status === "accepted").length;
  if (!accepted) return "not_accepted";
  return accepted === vehicles.length ? "accepted" : "partially_accepted";
}

function _operationsProjectGroupMarkup(project, open) {
  const vehicles = project.vehicles;
  const first = vehicles[0] || {};
  const projectName = [first.build_year, first.agency_name || "Unnamed project"]
    .filter(Boolean).join(" · ");
  const acceptance = _operationsProjectAcceptance(vehicles);
  const acceptanceBadge = first.project_state === "active"
    ? `<span class="operations-pill operations-pill-${esc(acceptance)}">${esc(_operationsLabel(acceptance))}</span>`
    : "";
  const schedule = _operationsCommonValue(vehicles, "schedule_bucket", "prospective");
  const canEdit = _operationsEditableWorkstreams().length > 0;
  const canSchedule = _operationsCanSchedule() && first.project_state === "active";
  const summaryStatuses = [
    ["availability", "Vehicle", _operationsCommonValue(vehicles, "vehicle_availability_status", "awaiting_details")],
    ["parts", "Parts", _operationsCommonValue(vehicles, "parts_status", "not_started") || "not_started"],
    ["shop", "Build", _operationsCommonValue(vehicles, "shop_status", "not_started") || "not_started"],
    ["tray", "Tray", _operationsCommonValue(vehicles, "tray_status", "not_ready")],
    ["programming_qc", "Programming & QC", _operationsCommonValue(vehicles, "programming_qc_status", "not_ready")],
    ["final_finish", "Final", _operationsCommonValue(vehicles, "final_finish_status", "not_ready")],
  ].map(([key, label, value]) => `<span class="operations-status-tone-${_operationsStatusTone(key, value)}"><b>${esc(label)}</b>${esc(_operationsLabel(value))}</span>`).join("");
  return `<details class="operations-project-group" data-operations-project-id="${_operationsEscAttr(project.projectId)}"${open ? " open" : ""}>
    <summary>
      <div class="operations-project-identity">
        <strong>${esc(projectName)}</strong>
        <span>${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"} · ${esc(_operationsLabel(schedule))}</span>
      </div>
      <span class="operations-project-acceptance">${acceptanceBadge}</span>
      <div class="operations-project-statuses">${summaryStatuses}</div>
      <span class="operations-project-chevron" aria-hidden="true">⌄</span>
    </summary>
    <div class="operations-project-body">
      ${canEdit ? `<div class="operations-quick-panel">
        <div class="operations-quick-heading">
          <strong>Project status</strong>
          <span>Click a status to apply it to all ${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"}</span>
        </div>
        ${_operationsQuickStatusMarkup(vehicles, "project", project.projectId)}
      </div>` : ""}
      <div class="operations-project-actions">
        <span>Vehicle details and exceptions</span>
        <div>
          ${canSchedule ? `<button class="btn btn-secondary btn-sm" type="button" data-operations-schedule-project="${_operationsEscAttr(project.projectId)}">Edit project schedule</button>` : ""}
        </div>
      </div>
      <div class="operations-project-vehicles">${vehicles.map(_operationsVehicleMarkup).join("")}</div>
    </div>
  </details>`;
}

function _operationsBindRowActions() {
  document.querySelectorAll("[data-operations-quick-status]").forEach(button => {
    button.addEventListener("click", () => _operationsApplyQuickStatus(button));
  });
  document.querySelectorAll("[data-operations-status-date-editor]").forEach(button => {
    button.addEventListener("click", () => {
      const vehicles = _operationsQuickVehicles(button);
      const first = vehicles[0] || {};
      const label = button.dataset.operationsStatusScope === "project"
        ? `${[first.build_year, first.agency_name || "Project"].filter(Boolean).join(" · ")} — ${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"}`
        : first.vehicle_label || first.title || "Vehicle";
      _operationsOpenStatusEditor(vehicles, label, { workstream: "availability" });
    });
  });
  document.querySelectorAll("[data-operations-history-vehicle]").forEach(button => {
    button.addEventListener("click", () => {
      const vehicle = (_OPERATIONS.payload?.vehicles || [])
        .find(item => item.vehicle_id === button.dataset.operationsHistoryVehicle);
      if (vehicle) _operationsOpenHistory(vehicle);
    });
  });
  document.querySelectorAll("[data-operations-schedule-project]").forEach(button => {
    button.addEventListener("click", () => {
      const projectId = button.dataset.operationsScheduleProject;
      const vehicles = (_OPERATIONS.payload?.vehicles || [])
        .filter(vehicle => vehicle.project_id === projectId);
      const first = vehicles[0] || {};
      const label = [first.build_year, first.agency_name || "Project"].filter(Boolean).join(" · ");
      _operationsOpenScheduleEditor(vehicles, `${label} — ${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"}`);
    });
  });
  document.querySelectorAll("[data-operations-schedule-vehicle]").forEach(button => {
    button.addEventListener("click", () => {
      const vehicle = (_OPERATIONS.payload?.vehicles || [])
        .find(item => item.vehicle_id === button.dataset.operationsScheduleVehicle);
      if (vehicle) _operationsOpenScheduleEditor(
        [vehicle],
        vehicle.vehicle_label || vehicle.title || "Vehicle",
      );
    });
  });
}

function _operationsProjectionPreviewMarkup(preview) {
  const all = preview?.vehicles || [];
  const pending = all.filter(item =>
    item.projection_state === "new" && item.project_state !== "inactive"
  );
  const bulk = pending.filter(item => ["active", "completed"].includes(item.project_state));
  const activeCount = bulk.filter(item => item.project_state === "active").length;
  const completedCount = bulk.filter(item => item.project_state === "completed").length;
  if (!all.length) {
    return `<div class="operations-projection-preview">
      <strong>No Operations records exist yet.</strong>
      <span>No individual Builder vehicles were found. Nothing has been written.</span>
    </div>`;
  }
  if (!pending.length) {
    return `<div class="operations-projection-preview">
      <strong>No new Builder vehicles are available.</strong>
      <span>Existing Operations records cannot be changed through this pilot.</span>
    </div>`;
  }
  const options = pending.map((vehicle, index) =>
    `<option value="${index}">${esc(vehicle.vehicle_label || vehicle.vehicle_id)}</option>`
  ).join("");
  return `<div class="operations-projection-preview">
    <div class="operations-projection-heading">
      <div>
        <strong>${pending.length} Builder vehicle${pending.length === 1 ? " is" : "s are"} ready to add</strong>
        <span>Select and confirm one vehicle at a time</span>
      </div>
      <span class="operations-pill operations-pill-preview">Preview</span>
    </div>
    <label class="operations-projection-picker">
      <span>Vehicle to review</span>
      <select id="operations-projection-select">${options}</select>
    </label>
    <div id="operations-projection-detail"></div>
    <div class="operations-projection-actions">
      <button class="btn btn-primary btn-sm" id="operations-projection-add" type="button"${preview?.writes_enabled ? "" : " disabled"}>Add selected vehicle</button>
      ${bulk.length > 1 ? `<button class="btn btn-secondary btn-sm" id="operations-projection-add-all" type="button"${preview?.writes_enabled ? "" : " disabled"}>Add all ${bulk.length} vehicles</button>` : ""}
      <span>Creates one shared record and its first timeline event.</span>
    </div>
    <div id="operations-projection-progress" class="operations-projection-progress" role="status" hidden></div>
    ${bulk.length > 1 ? `<span class="operations-projection-bulk-summary">Bulk set: ${activeCount} Active · ${completedCount} Completed</span>` : ""}
  </div>`;
}

function _operationsRequestId() {
  return globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : `operations-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function _operationsCreateProjection(vehicle, requestId = _operationsRequestId()) {
  return api("/api/operations/projection-pilot", {
    vehicle_id: vehicle.vehicle_id,
    confirmation: `add:${vehicle.vehicle_id}`,
    request_id: requestId,
  });
}

function _operationsBindProjectionPreview() {
  const select = $("operations-projection-select");
  if (!select) return;
  const render = () => {
    const pending = (_OPERATIONS.projectionPreview?.vehicles || [])
      .filter(item => item.projection_state === "new" && item.project_state !== "inactive");
    const vehicle = pending[Number(select.value) || 0];
    const detail = $("operations-projection-detail");
    if (!detail || !vehicle) return;
    const changeText = vehicle.projection_state === "new"
      ? "New Operations record"
      : `Refresh: ${(vehicle.changed_fields || []).join(", ") || "Builder details"}`;
    detail.innerHTML = `<div class="operations-projection-detail">
      <div><span>Agency</span><strong>${esc(vehicle.agency_name || "—")}</strong></div>
      <div><span>Unit</span><strong>${esc(vehicle.unit_number || "—")}</strong></div>
      <div><span>Full VIN</span><strong>${esc(vehicle.vin || "—")}</strong></div>
      <div><span>Project</span><strong>${esc(_operationsLabel(vehicle.project_state))}</strong></div>
      <div><span>Build sheet</span><strong>${vehicle.build_finalized ? "Finalized" : "Not finalized"}</strong></div>
      <div><span>Action</span><strong>${esc(changeText)}</strong></div>
    </div>`;
  };
  select.addEventListener("change", render);
  $("operations-projection-add")?.addEventListener("click", async event => {
    const pending = (_OPERATIONS.projectionPreview?.vehicles || [])
      .filter(item => item.projection_state === "new" && item.project_state !== "inactive");
    const vehicle = pending[Number(select.value) || 0];
    if (!vehicle) return;
    const label = vehicle.vehicle_label || vehicle.vehicle_id;
    const approved = confirm(
      `Add this vehicle to shared Operations?\n\n${label}\nFull VIN: ${vehicle.vin || "Not entered"}\n\nThis creates one Operations record. It does not change the Builder project.`
    );
    if (!approved) return;

    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Adding…";
    try {
      const result = await _operationsCreateProjection(vehicle);
      if (!result?.ok) {
        toast(result?.error || "Vehicle could not be added to Operations", "error");
        button.disabled = false;
        button.textContent = "Add selected vehicle";
        return;
      }
      toast(`${label} added to Operations`, "success");
      if (["active", "completed"].includes(result.project_state)) {
        _OPERATIONS.filter = result.project_state;
      }
      await initOperationsTab();
    } catch (error) {
      console.error("Operations pilot creation failed", error);
      toast("Vehicle could not be added to Operations", "error");
      button.disabled = false;
      button.textContent = "Add selected vehicle";
    }
  });
  $("operations-projection-add-all")?.addEventListener("click", async event => {
    const pending = (_OPERATIONS.projectionPreview?.vehicles || [])
      .filter(item => item.projection_state === "new" &&
        ["active", "completed"].includes(item.project_state));
    if (!pending.length) return;
    const activeCount = pending.filter(item => item.project_state === "active").length;
    const completedCount = pending.filter(item => item.project_state === "completed").length;
    const approved = confirm(
      `Add all ${pending.length} vehicles to shared Operations?\n\n${activeCount} Active\n${completedCount} Completed\n\nCompleted vehicles will appear in the Completed tab. Historical workflow dates will remain unset instead of being invented. The import stops safely if any vehicle fails.`
    );
    if (!approved) return;

    const button = event.currentTarget;
    const singleButton = $("operations-projection-add");
    const select = $("operations-projection-select");
    const progress = $("operations-projection-progress");
    button.disabled = true;
    if (singleButton) singleButton.disabled = true;
    if (select) select.disabled = true;
    if (progress) progress.hidden = false;
    let created = 0;
    let failure = "";
    for (const [index, vehicle] of pending.entries()) {
      button.textContent = `Adding ${index + 1} of ${pending.length}…`;
      if (progress) {
        progress.textContent = `${created} added · now adding ${vehicle.vehicle_label || vehicle.vehicle_id}`;
      }
      try {
        const result = await _operationsCreateProjection(vehicle);
        if (!result?.ok) {
          failure = result?.error || "Vehicle could not be added";
          break;
        }
        created += 1;
      } catch (error) {
        console.error("Operations bulk creation stopped", error);
        failure = "The connection was interrupted";
        break;
      }
    }

    if (failure) {
      toast(`${created} of ${pending.length} added. Stopped: ${failure}`, "error");
    } else {
      toast(`${created} vehicles added to Operations`, "success");
    }
    await initOperationsTab();
    if (failure) await _operationsLoadProjectionPreview({ open: true });
  });
  render();
}

function _operationsVehicleMarkup(vehicle) {
  const label = vehicle.vehicle_label || vehicle.title || "Unnamed vehicle";
  const identity = [
    vehicle.unit_number ? `Unit ${vehicle.unit_number}` : "",
    vehicle.vin ? `VIN ${vehicle.vin}` : "",
  ].filter(Boolean).join(" · ") || "Identifiers pending";
  const schedule = vehicle.schedule_bucket === "prospective"
    ? "Not accepted"
    : vehicle.schedule_bucket === "unscheduled"
      ? "Unscheduled"
      : `Week of ${_operationsDate(vehicle.scheduled_week_of)}`;
  const qbo = vehicle.qbo_estimate_number
    ? `Estimate ${vehicle.qbo_estimate_number}${vehicle.qbo_observation_stale ? " · data may be stale" : ""}`
    : "No linked estimate";
  const canEdit = _operationsEditableWorkstreams().length > 0;
  return `<article class="operations-vehicle">
    <div class="operations-vehicle-heading">
      <div>
        <h3>${esc(label)}</h3>
        <p>${esc(identity)}</p>
      </div>
      <div class="operations-badges">
        <span class="operations-pill operations-pill-${esc(vehicle.acceptance_status)}">${esc(_operationsLabel(vehicle.acceptance_status))}</span>
        <span class="operations-pill operations-pill-schedule">${esc(schedule)}</span>
      </div>
    </div>
    <div class="operations-status-grid">
      ${_operationsStatus("availability", "Vehicle", vehicle.vehicle_availability_status)}
      ${_operationsStatus("parts", "Parts", vehicle.parts_status || "not_started")}
      ${_operationsStatus("shop", "Build / Shop", vehicle.shop_status || "not_started")}
      ${_operationsStatus("tray", "Tray", vehicle.tray_status)}
      ${_operationsStatus("programming_qc", "Programming & QC", vehicle.programming_qc_status)}
      ${_operationsStatus("final_finish", "Final Finish", vehicle.final_finish_status)}
    </div>
    <div class="operations-dates">
      <span><b>Planned start</b>${esc(_operationsDate(vehicle.planned_start_date))}</span>
      <span><b>Target finish</b>${esc(_operationsDate(vehicle.target_finish_date))}</span>
      <span class="operations-must-deliver"><b>Must Deliver On${vehicle.must_deliver_override_date ? " · Manual" : ""}</b>${esc(_operationsDate(vehicle.must_deliver_by_date))}</span>
      <span><b>QuickBooks</b>${esc(qbo)}</span>
    </div>
    ${canEdit ? `<details class="operations-vehicle-quick">
      <summary>Individual status override</summary>
      ${_operationsQuickStatusMarkup([vehicle], "vehicle", vehicle.vehicle_id)}
    </details>` : ""}
    <div class="operations-vehicle-actions">
      <span>Last updated ${esc(_operationsDate(vehicle.updated_at))}${vehicle.updated_by_name ? ` by ${esc(vehicle.updated_by_name)}` : ""}</span>
      <div>
        <button class="btn btn-secondary btn-sm" type="button" data-operations-history-vehicle="${_operationsEscAttr(vehicle.vehicle_id)}">View history</button>
        ${_operationsCanSchedule() && vehicle.project_state === "active" ? `<button class="btn btn-secondary btn-sm" type="button" data-operations-schedule-vehicle="${_operationsEscAttr(vehicle.vehicle_id)}">Edit schedule</button>` : ""}
      </div>
    </div>
  </article>`;
}

function _operationsStatus(key, label, value) {
  return `<div class="operations-status operations-status-tone-${_operationsStatusTone(key, value)}"><span>${esc(label)}</span><strong>${esc(_operationsLabel(value))}</strong></div>`;
}

function _operationsQuickStatusMarkup(vehicles, scope, id) {
  return `<div class="operations-quick-statuses">${_operationsEditableWorkstreams().map(definition => {
    const current = _operationsCommonValue(vehicles, definition.field);
    const buttons = definition.values.map(([value, label]) => {
      const active = current === value;
      const tone = active ? ` operations-status-tone-${_operationsStatusTone(definition.key, value)}` : "";
      return `<button type="button" class="operations-quick-status${active ? " active" : ""}${tone}"
        data-operations-quick-status data-operations-status-scope="${_operationsEscAttr(scope)}"
        data-operations-status-id="${_operationsEscAttr(id)}"
        data-operations-status-workstream="${_operationsEscAttr(definition.key)}"
        data-operations-status-value="${_operationsEscAttr(value)}"${active ? " disabled" : ""}>${esc(label)}</button>`;
    }).join("");
    const dateEditor = definition.key === "availability"
      ? `<button type="button" class="operations-quick-date" data-operations-status-date-editor
          data-operations-status-scope="${_operationsEscAttr(scope)}"
          data-operations-status-id="${_operationsEscAttr(id)}">Set date…</button>`
      : "";
    return `<div class="operations-quick-row">
      <b>${esc(definition.label)}</b>
      <div role="group" aria-label="${_operationsEscAttr(definition.label)} status">${buttons}${dateEditor}</div>
    </div>`;
  }).join("")}</div>`;
}

function _operationsQuickVehicles(button) {
  const id = button.dataset.operationsStatusId;
  return button.dataset.operationsStatusScope === "project"
    ? (_OPERATIONS.payload?.vehicles || []).filter(vehicle => vehicle.project_id === id)
    : (_OPERATIONS.payload?.vehicles || []).filter(vehicle => vehicle.vehicle_id === id);
}

async function _operationsApplyQuickStatus(button) {
  if (_OPERATIONS.statusSaving) return;
  const definition = _operationsStatusDef(button.dataset.operationsStatusWorkstream);
  const target = String(button.dataset.operationsStatusValue ?? "");
  if (!definition) return;
  const vehicles = _operationsQuickVehicles(button);
  const targets = vehicles.filter(vehicle => _operationsStatusValue(vehicle, definition) !== target);
  if (!targets.length) return;
  const needsCorrection = targets.some(vehicle => _operationsTransitionNeedsCorrection(
    definition,
    _operationsStatusValue(vehicle, definition),
    target,
  ));
  const first = vehicles[0] || {};
  const label = button.dataset.operationsStatusScope === "project"
    ? `${[first.build_year, first.agency_name || "Project"].filter(Boolean).join(" · ")} — ${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"}`
    : first.vehicle_label || first.title || "Vehicle";
  if (needsCorrection) {
    _operationsOpenStatusEditor(vehicles, label, {
      workstream: definition.key,
      target,
    });
    return;
  }

  _OPERATIONS.statusSaving = true;
  document.querySelectorAll("[data-operations-quick-status]").forEach(item => {
    item.disabled = true;
  });
  button.classList.add("saving");
  let changed = 0;
  let failure = "";
  let autoCompleted = false;
  for (const vehicle of targets) {
    try {
      const result = await api("/api/operations/status", {
        vehicle_id: vehicle.vehicle_id,
        workstream: definition.key,
        new_status: target,
        expected_revision: vehicle.revision,
        request_id: _operationsRequestId(),
      });
      if (!result?.ok) {
        failure = result?.error || "The status could not be saved";
        break;
      }
      vehicle[definition.field] = target;
      vehicle.revision = result.revision;
      if (result.changed) changed += 1;
      if (result.project_auto_completed) autoCompleted = true;
    } catch (error) {
      console.error("Operations quick status update stopped", error);
      failure = "The connection was interrupted";
      break;
    }
  }
  _OPERATIONS.statusSaving = false;
  if (failure) toast(`${changed} of ${targets.length} saved. Stopped: ${failure}`, "error");
  else toast(autoCompleted
    ? "Delivered saved — project moved to Completed"
    : `${_operationsStatusValueLabel(definition, target)} saved`, "success");
  await initOperationsTab();
}

function _operationsStatusDef(key) {
  return _OPERATIONS_STATUS_DEFS.find(item => item.key === key);
}

function _operationsStatusValue(vehicle, definition) {
  return String(vehicle?.[definition.field] ?? "");
}

function _operationsStatusValueLabel(definition, value) {
  return definition.values.find(item => item[0] === value)?.[1] || _operationsLabel(value);
}

function _operationsStatusTargets(definition, target) {
  const vehicles = _OPERATIONS.editVehicles || [];
  const effectiveDate = String($("operations-status-date")?.value || "");
  return vehicles.filter(vehicle => {
    const current = _operationsStatusValue(vehicle, definition);
    if (current !== target) return true;
    return definition.key === "availability" && vehicles.length === 1 && !!effectiveDate;
  });
}

function _operationsTransitionNeedsCorrection(definition, current, target) {
  if (current === target) return definition.key === "availability";
  if (definition.key === "acceptance") {
    return current === "accepted" && target === "not_accepted";
  }
  if (definition.key === "availability") return current === "delivered";
  return !((definition.normal?.[current] || []).includes(target));
}

function _operationsRenderStatusEditor() {
  const workstream = $("operations-status-workstream")?.value;
  const definition = _operationsStatusDef(workstream);
  const valueSelect = $("operations-status-value");
  if (!definition || !valueSelect) return;

  valueSelect.innerHTML = [
    '<option value="__choose__">Choose a status…</option>',
    ...definition.values.map(([value, label]) =>
      `<option value="${_operationsEscAttr(value)}">${esc(label)}</option>`),
  ].join("");
  const values = new Set((_OPERATIONS.editVehicles || [])
    .map(vehicle => _operationsStatusValue(vehicle, definition)));
  const current = values.size === 1 ? [...values][0] : "mixed";
  $("operations-status-current").textContent = `Current: ${current === "mixed" ? "Mixed" : _operationsStatusValueLabel(definition, current)}`;
  $("operations-status-date").value = "";
  _operationsUpdateStatusGuidance();
}

function _operationsUpdateStatusGuidance() {
  const definition = _operationsStatusDef($("operations-status-workstream")?.value);
  const target = $("operations-status-value")?.value;
  const apply = $("operations-status-apply");
  const guidance = $("operations-status-guidance");
  const reasonWrap = $("operations-status-reason-wrap");
  const dateWrap = $("operations-status-date-wrap");
  if (!definition || !apply || !guidance || !reasonWrap || !dateWrap) return;

  const showDate = definition.key === "availability" &&
    ["ready_for_pickup", "at_dtm", "delivered"].includes(target);
  dateWrap.hidden = !showDate;
  if (!showDate) $("operations-status-date").value = "";

  if (target === "__choose__") {
    reasonWrap.hidden = true;
    guidance.textContent = "Choose one status to update.";
    guidance.className = "operations-status-guidance";
    apply.textContent = "Apply status";
    apply.disabled = true;
    return;
  }

  const targets = _operationsStatusTargets(definition, target);
  const needsCorrection = targets.some(vehicle => _operationsTransitionNeedsCorrection(
    definition,
    _operationsStatusValue(vehicle, definition),
    target,
  ));
  const canCorrect = (_OPERATIONS.session?.capabilities || []).includes("operations.correct");
  const correctionReason = String($("operations-status-reason")?.value || "").trim();
  reasonWrap.hidden = !needsCorrection;
  apply.textContent = targets.length > 1
    ? `Update ${targets.length} vehicles`
    : targets.length === 1
      ? "Update vehicle"
      : "No change needed";

  if (!targets.length) {
    guidance.textContent = "Every vehicle in this selection already has that status.";
    guidance.className = "operations-status-guidance";
    apply.disabled = true;
  } else if (needsCorrection && !canCorrect) {
    guidance.textContent = "This change reverses or skips a normal step and requires a manager.";
    guidance.className = "operations-status-guidance operations-status-guidance-warning";
    apply.disabled = true;
  } else if (needsCorrection) {
    guidance.textContent = "This change reverses or skips a normal step. Add a correction note to continue.";
    guidance.className = "operations-status-guidance operations-status-guidance-warning";
    apply.disabled = !correctionReason;
  } else {
    guidance.textContent = `A dated history entry will be recorded for ${targets.length} vehicle${targets.length === 1 ? "" : "s"}.`;
    guidance.className = "operations-status-guidance";
    apply.disabled = false;
  }
}

function _operationsOpenStatusEditor(vehicles, scopeLabel, selection = null) {
  const editable = _operationsEditableWorkstreams();
  if (!vehicles?.length || !editable.length) {
    toast("Your role cannot update Operations statuses", "error");
    return;
  }
  _OPERATIONS.editVehicles = vehicles;
  _OPERATIONS.editScopeLabel = scopeLabel;
  $("operations-status-title").textContent = vehicles.length > 1
    ? "Update project status"
    : "Update vehicle status";
  $("operations-status-scope").textContent = scopeLabel;
  $("operations-status-workstream").innerHTML = editable.map(item =>
    `<option value="${_operationsEscAttr(item.key)}">${esc(item.label)}</option>`
  ).join("");
  $("operations-status-reason").value = "";
  $("operations-status-progress").hidden = true;
  if (selection?.workstream && editable.some(item => item.key === selection.workstream)) {
    $("operations-status-workstream").value = selection.workstream;
  }
  _operationsRenderStatusEditor();
  if (selection?.target != null) {
    $("operations-status-value").value = selection.target;
    _operationsUpdateStatusGuidance();
  }
  const modal = $("operations-status-modal");
  modal.removeAttribute("hidden");
  modal.classList.add("open");
}

function _operationsCloseStatusEditor(force = false) {
  if (_OPERATIONS.statusSaving && !force) return;
  const modal = $("operations-status-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  _OPERATIONS.editVehicles = [];
  _OPERATIONS.editScopeLabel = "";
}

async function _operationsApplyStatus(event) {
  event.preventDefault();
  if (_OPERATIONS.statusSaving) return;
  const definition = _operationsStatusDef($("operations-status-workstream")?.value);
  const target = $("operations-status-value")?.value;
  if (!definition || target === "__choose__") return;
  const targets = _operationsStatusTargets(definition, target);
  if (!targets.length) return;
  const correctionReason = String($("operations-status-reason")?.value || "").trim();
  const effectiveDate = String($("operations-status-date")?.value || "");
  const approved = targets.length === 1 || confirm(
    `Set ${definition.label} to ${_operationsStatusValueLabel(definition, target)} for ${targets.length} vehicles?\n\nEach vehicle will receive its own dated history entry.`
  );
  if (!approved) return;

  const apply = $("operations-status-apply");
  const cancel = $("operations-status-cancel");
  const close = $("operations-status-close");
  const progress = $("operations-status-progress");
  _OPERATIONS.statusSaving = true;
  apply.disabled = true;
  cancel.disabled = true;
  close.disabled = true;
  progress.hidden = false;
  let changed = 0;
  let failure = "";
  let autoCompleted = false;
  for (const [index, vehicle] of targets.entries()) {
    progress.textContent = `${changed} saved · updating ${index + 1} of ${targets.length}`;
    try {
      const result = await api("/api/operations/status", {
        vehicle_id: vehicle.vehicle_id,
        workstream: definition.key,
        new_status: target,
        expected_revision: vehicle.revision,
        request_id: _operationsRequestId(),
        correction_reason: correctionReason,
        effective_date: definition.key === "availability" ? effectiveDate : "",
      });
      if (!result?.ok) {
        failure = result?.error || "The status could not be saved";
        break;
      }
      vehicle[definition.field] = target;
      vehicle.revision = result.revision;
      if (result.changed) changed += 1;
      if (result.project_auto_completed) autoCompleted = true;
    } catch (error) {
      console.error("Operations status update stopped", error);
      failure = "The connection was interrupted";
      break;
    }
  }
  _OPERATIONS.statusSaving = false;
  apply.disabled = false;
  cancel.disabled = false;
  close.disabled = false;
  _operationsCloseStatusEditor(true);
  if (failure) {
    toast(`${changed} of ${targets.length} saved. Stopped: ${failure}`, "error");
  } else {
    toast(autoCompleted
      ? "Delivered saved — project moved to Completed"
      : `${changed} vehicle${changed === 1 ? "" : "s"} updated`, "success");
  }
  await initOperationsTab();
}

function _operationsSchedulePatch() {
  const patch = {};
  if ($("operations-schedule-clear")?.checked) {
    patch.scheduled_week_of = "";
    patch.planned_start_date = "";
    patch.target_finish_date = "";
  }
  document.querySelectorAll("[data-operations-schedule-field]").forEach(input => {
    const field = input.dataset.operationsScheduleField;
    if (_OPERATIONS.scheduleDirty.has(field) && !(field in patch)) {
      patch[field] = String(input.value || "");
    }
  });
  return patch;
}

function _operationsScheduleTargets(patch) {
  return (_OPERATIONS.scheduleVehicles || []).filter(vehicle =>
    Object.entries(patch).some(([field, value]) => String(vehicle[field] || "") !== value)
  );
}

function _operationsMarkScheduleDirty(event) {
  const field = event.currentTarget?.dataset?.operationsScheduleField;
  if (!field) return;
  const value = String(event.currentTarget.value || "");
  const initial = _OPERATIONS.scheduleInitial[field];
  if (initial !== "mixed" && value === initial) _OPERATIONS.scheduleDirty.delete(field);
  else _OPERATIONS.scheduleDirty.add(field);
  _operationsUpdateScheduleGuidance();
}

function _operationsUpdateScheduleGuidance() {
  const clear = !!$("operations-schedule-clear")?.checked;
  const week = $("operations-scheduled-week");
  const planned = $("operations-planned-start");
  const finish = $("operations-target-finish");
  const mustDeliver = $("operations-must-deliver");
  const guidance = $("operations-schedule-guidance");
  const apply = $("operations-schedule-apply");
  if (!week || !planned || !finish || !mustDeliver || !guidance || !apply) return;
  [week, planned, finish].forEach(input => { input.disabled = clear; });
  const patch = _operationsSchedulePatch();
  const targets = _operationsScheduleTargets(patch);
  apply.textContent = targets.length > 1
    ? `Save for ${targets.length} vehicles`
    : targets.length === 1
      ? "Save schedule"
      : "No change needed";
  guidance.className = "operations-status-guidance";

  if (!Object.keys(patch).length) {
    guidance.textContent = "Change any one date to enable Save. Unedited dates stay as they are.";
    apply.disabled = true;
    return;
  }
  if (!targets.length) {
    guidance.textContent = "Every selected vehicle already has this schedule.";
    apply.disabled = true;
    return;
  }
  guidance.textContent = `${Object.keys(patch).length} field${Object.keys(patch).length === 1 ? "" : "s"} will change for ${targets.length} vehicle${targets.length === 1 ? "" : "s"}. Unedited dates stay as they are.`;
  apply.disabled = false;
}

function _operationsOpenScheduleEditor(vehicles, scopeLabel) {
  if (!vehicles?.length || !_operationsCanSchedule()) {
    toast("Your role cannot update Operations schedules", "error");
    return;
  }
  _OPERATIONS.scheduleVehicles = vehicles;
  $("operations-schedule-title").textContent = vehicles.length > 1
    ? "Edit project schedule"
    : "Edit vehicle schedule";
  $("operations-schedule-scope").textContent = scopeLabel;
  const week = _operationsCommonValue(vehicles, "scheduled_week_of");
  const planned = _operationsCommonValue(vehicles, "planned_start_date");
  const finish = _operationsCommonValue(vehicles, "target_finish_date");
  const deadlineOverride = _operationsCommonValue(vehicles, "must_deliver_override_date");
  const bucket = _operationsCommonValue(vehicles, "schedule_bucket", "prospective");
  const mustDeliver = _operationsCommonValue(vehicles, "must_deliver_by_date");
  $("operations-scheduled-week").value = week === "mixed" ? "" : week;
  $("operations-planned-start").value = planned === "mixed" ? "" : planned;
  $("operations-target-finish").value = finish === "mixed" ? "" : finish;
  $("operations-must-deliver").value = deadlineOverride === "mixed" ? "" : deadlineOverride;
  _OPERATIONS.scheduleInitial = {
    scheduled_week_of: week,
    planned_start_date: planned,
    target_finish_date: finish,
    must_deliver_override_date: deadlineOverride,
  };
  _OPERATIONS.scheduleDirty = new Set();
  $("operations-schedule-clear").checked = false;
  $("operations-schedule-current").innerHTML = [
    ["Current schedule", _operationsLabel(bucket)],
    ["Scheduled week", week === "mixed" ? "Mixed" : _operationsDate(week)],
    ["Must Deliver On", mustDeliver === "mixed" ? "Mixed" : `${_operationsDate(mustDeliver)}${deadlineOverride && deadlineOverride !== "mixed" ? " · Manual" : " · Automatic"}`],
  ].map(([label, value]) => `<span><b>${esc(label)}</b><strong>${esc(value)}</strong></span>`).join("");
  $("operations-schedule-progress").hidden = true;
  _operationsUpdateScheduleGuidance();
  const modal = $("operations-schedule-modal");
  modal.removeAttribute("hidden");
  modal.classList.add("open");
}

function _operationsCloseScheduleEditor(force = false) {
  if (_OPERATIONS.scheduleSaving && !force) return;
  const modal = $("operations-schedule-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  _OPERATIONS.scheduleVehicles = [];
  _OPERATIONS.scheduleInitial = {};
  _OPERATIONS.scheduleDirty = new Set();
}

async function _operationsApplySchedule(event) {
  event.preventDefault();
  if (_OPERATIONS.scheduleSaving) return;
  const patch = _operationsSchedulePatch();
  const targets = _operationsScheduleTargets(patch);
  if (!targets.length || $("operations-schedule-apply")?.disabled) return;
  const approved = targets.length === 1 || confirm(
    `Apply these date changes to ${targets.length} vehicles?\n\nUnedited dates will stay as they are. Each vehicle will receive its own dated history entry.`
  );
  if (!approved) return;

  const apply = $("operations-schedule-apply");
  const cancel = $("operations-schedule-cancel");
  const close = $("operations-schedule-close");
  const progress = $("operations-schedule-progress");
  _OPERATIONS.scheduleSaving = true;
  apply.disabled = true;
  cancel.disabled = true;
  close.disabled = true;
  progress.hidden = false;
  let changed = 0;
  let failure = "";
  for (const [index, vehicle] of targets.entries()) {
    progress.textContent = `${changed} saved · updating ${index + 1} of ${targets.length}`;
    try {
      const result = await api("/api/operations/schedule", {
        vehicle_id: vehicle.vehicle_id,
        ...patch,
        expected_revision: vehicle.revision,
        request_id: _operationsRequestId(),
      });
      if (!result?.ok) {
        failure = result?.error || "The schedule could not be saved";
        break;
      }
      vehicle.scheduled_week_of = result.scheduled_week_of;
      vehicle.planned_start_date = result.planned_start_date;
      vehicle.target_finish_date = result.target_finish_date;
      vehicle.must_deliver_override_date = result.must_deliver_override_date;
      vehicle.must_deliver_by_date = result.must_deliver_by_date;
      vehicle.schedule_bucket = result.schedule_bucket;
      vehicle.revision = result.revision;
      if (result.changed) changed += 1;
    } catch (error) {
      console.error("Operations schedule update stopped", error);
      failure = "The connection was interrupted";
      break;
    }
  }
  _OPERATIONS.scheduleSaving = false;
  apply.disabled = false;
  cancel.disabled = false;
  close.disabled = false;
  _operationsCloseScheduleEditor(true);
  if (failure) {
    toast(`${changed} of ${targets.length} saved. Stopped: ${failure}`, "error");
  } else {
    toast(`${changed} vehicle${changed === 1 ? "" : "s"} scheduled`, "success");
  }
  await initOperationsTab();
}

function _operationsHistoryEventTitle(event) {
  const fixed = {
    record_created: "Added to Operations",
    projection_refreshed: "Builder details refreshed",
    qbo_observed: "QuickBooks status observed",
  };
  if (fixed[event.event_type]) return fixed[event.event_type];
  const definition = _operationsStatusDef(event.workstream);
  const labels = {
    schedule: "Schedule",
    delivery: "Delivery",
    qbo: "QuickBooks",
    record: "Vehicle record",
  };
  return `${definition?.label || labels[event.workstream] || _operationsLabel(event.workstream)} changed`;
}

function _operationsHistoryValue(event, value) {
  const text = String(value || "");
  if (!text) {
    return ["parts", "shop"].includes(event.workstream) ? "Not started" : "—";
  }
  if (text.startsWith("{") || text.startsWith("[")) return "Details updated";
  return _operationsLabel(text);
}

function _operationsHistoryChangeMarkup(event) {
  if (["record_created", "projection_refreshed", "qbo_observed"].includes(event.event_type)) {
    return "";
  }
  if (event.event_type === "schedule_changed") {
    try {
      const previous = JSON.parse(event.previous_value || "{}");
      const changed = JSON.parse(event.new_value || "{}");
      const rows = [
        ["Scheduled week", "scheduled_week_of"],
        ["Planned start", "planned_start_date"],
        ["Target finish", "target_finish_date"],
        ["Must Deliver On", "must_deliver_override_date"],
      ].filter(([, field]) => String(previous[field] || "") !== String(changed[field] || ""))
        .map(([label, field]) => `<div>
          <b>${esc(label)}</b>
          <span>${esc(_operationsDate(previous[field]))}</span>
          <i aria-hidden="true">→</i>
          <strong>${esc(_operationsDate(changed[field]))}</strong>
        </div>`).join("");
      return rows ? `<div class="operations-timeline-schedule">${rows}</div>` : "";
    } catch (_) {
      return '<div class="operations-timeline-change"><span>Prior schedule</span><b aria-hidden="true">→</b><strong>Schedule updated</strong></div>';
    }
  }
  return `<div class="operations-timeline-change">
    <span>${esc(_operationsHistoryValue(event, event.previous_value))}</span>
    <b aria-hidden="true">→</b>
    <strong>${esc(_operationsHistoryValue(event, event.new_value))}</strong>
  </div>`;
}

function _operationsHistoryMarkup(events) {
  if (!events.length) {
    return '<div class="operations-history-empty">No history has been recorded.</div>';
  }
  return `<ol class="operations-timeline">${events.map(event => {
    const actor = event.performed_by_name
      ? `${event.actor_display_name || "Unknown user"} · performed by ${event.performed_by_name}`
      : event.actor_display_name || "Unknown user";
    return `<li class="operations-timeline-event">
      <span class="operations-timeline-marker" aria-hidden="true"></span>
      <div class="operations-timeline-card">
        <div class="operations-timeline-heading">
          <strong>${esc(_operationsHistoryEventTitle(event))}</strong>
          <time>${esc(_operationsDateTime(event.occurred_at))}</time>
        </div>
        ${_operationsHistoryChangeMarkup(event)}
        ${event.effective_date ? `<div class="operations-timeline-effective">Effective date: ${esc(_operationsDate(event.effective_date))}</div>` : ""}
        ${event.reason ? `<div class="operations-timeline-reason"><b>Correction note</b>${esc(event.reason)}</div>` : ""}
        <div class="operations-timeline-meta">
          <span>${esc(actor)}</span>
          <span>Revision ${esc(event.revision)}</span>
        </div>
      </div>
    </li>`;
  }).join("")}</ol>`;
}

async function _operationsOpenHistory(vehicle) {
  const modal = $("operations-history-modal");
  const body = $("operations-history-body");
  const request = ++_OPERATIONS.historyRequest;
  $("operations-history-scope").textContent = vehicle.vehicle_label || vehicle.title || "Vehicle";
  body.innerHTML = '<div class="operations-history-loading">Loading complete history…</div>';
  modal.removeAttribute("hidden");
  modal.classList.add("open");
  try {
    const payload = await api(
      `/api/operations/history?vehicle_id=${encodeURIComponent(vehicle.vehicle_id)}`
    );
    if (request !== _OPERATIONS.historyRequest) return;
    if (!payload?.ok) {
      body.innerHTML = `<div class="operations-history-error">
        <span>${esc(payload?.error || "Vehicle history could not be loaded")}</span>
        <button class="btn btn-secondary btn-sm" id="operations-history-retry" type="button">Try again</button>
      </div>`;
      $("operations-history-retry")?.addEventListener("click", () => _operationsOpenHistory(vehicle));
      return;
    }
    body.innerHTML = _operationsHistoryMarkup(payload.events || []);
  } catch (error) {
    console.error("Operations history load failed", error);
    if (request !== _OPERATIONS.historyRequest) return;
    body.innerHTML = `<div class="operations-history-error">
      <span>Vehicle history is temporarily unavailable.</span>
      <button class="btn btn-secondary btn-sm" id="operations-history-retry" type="button">Try again</button>
    </div>`;
    $("operations-history-retry")?.addEventListener("click", () => _operationsOpenHistory(vehicle));
  }
}

function _operationsCloseHistory() {
  _OPERATIONS.historyRequest += 1;
  const modal = $("operations-history-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
}

function _operationsLabel(value) {
  const labels = {
    not_accepted: "Not accepted",
    accepted: "Accepted",
    partially_accepted: "Partially accepted",
    prospective: "Not accepted",
    unscheduled: "Unscheduled",
    scheduled: "Scheduled",
    mixed: "Mixed",
    active: "Active",
    inactive: "Inactive",
    completed: "Completed",
    awaiting_details: "Awaiting details",
    waiting_on_dealer: "Waiting on dealer",
    waiting_on_agency: "Waiting on agency",
    ready_for_pickup: "Ready for pickup",
    at_dtm: "At DTM",
    delivered: "Delivered",
    not_started: "Not started",
    ordered: "Ordered",
    partially_received: "Partially received",
    received: "Received",
    parts_ready: "Parts ready",
    in_progress: "In progress",
    complete: "Complete",
    not_ready: "Not ready",
    ready: "Ready",
    ready_for_wash_clean_photos: "Ready for wash, clean & photos",
    ready_for_delivery: "Ready for delivery",
  };
  return labels[value] || String(value || "—").replaceAll("_", " ");
}

function _operationsDate(value) {
  const text = String(value || "").trim();
  if (!text) return "—";
  const dateOnly = text.slice(0, 10);
  const parsed = new Date(`${dateOnly}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return text;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function _operationsDateTime(value) {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) return String(value || "—");
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("operations-refresh")?.addEventListener("click", () => initOperationsTab());
  $("operations-add-builder")?.addEventListener("click", () => {
    _operationsLoadProjectionPreview({ open: true });
  });
  $("operations-search")?.addEventListener("input", () => _operationsRenderRows());
  document.querySelectorAll(".operations-filter").forEach(button => {
    button.addEventListener("click", () => {
      _OPERATIONS.filter = button.dataset.operationsFilter || "active";
      _operationsRenderRows();
    });
  });
  $("operations-status-workstream")?.addEventListener("change", _operationsRenderStatusEditor);
  $("operations-status-value")?.addEventListener("change", _operationsUpdateStatusGuidance);
  $("operations-status-date")?.addEventListener("change", _operationsUpdateStatusGuidance);
  $("operations-status-reason")?.addEventListener("input", _operationsUpdateStatusGuidance);
  $("operations-status-form")?.addEventListener("submit", _operationsApplyStatus);
  $("operations-status-close")?.addEventListener("click", () => _operationsCloseStatusEditor());
  $("operations-status-cancel")?.addEventListener("click", () => _operationsCloseStatusEditor());
  $("operations-status-modal")?.addEventListener("click", event => {
    if (event.target === $("operations-status-modal")) _operationsCloseStatusEditor();
  });
  ["operations-scheduled-week", "operations-planned-start", "operations-target-finish", "operations-must-deliver"]
    .forEach(id => {
      $(id)?.addEventListener("input", _operationsMarkScheduleDirty);
      $(id)?.addEventListener("change", _operationsMarkScheduleDirty);
    });
  $("operations-schedule-clear")?.addEventListener("change", event => {
    ["scheduled_week_of", "planned_start_date", "target_finish_date"].forEach(field => {
      if (event.currentTarget.checked) {
        _OPERATIONS.scheduleDirty.add(field);
      } else {
        const input = document.querySelector(`[data-operations-schedule-field="${field}"]`);
        const value = String(input?.value || "");
        if (
          (_OPERATIONS.scheduleInitial[field] !== "mixed" &&
            value === _OPERATIONS.scheduleInitial[field]) ||
          (_OPERATIONS.scheduleInitial[field] === "mixed" && !value)
        ) {
          _OPERATIONS.scheduleDirty.delete(field);
        }
      }
    });
    _operationsUpdateScheduleGuidance();
  });
  $("operations-schedule-form")?.addEventListener("submit", _operationsApplySchedule);
  $("operations-schedule-close")?.addEventListener("click", () => _operationsCloseScheduleEditor());
  $("operations-schedule-cancel")?.addEventListener("click", () => _operationsCloseScheduleEditor());
  $("operations-schedule-modal")?.addEventListener("click", event => {
    if (event.target === $("operations-schedule-modal")) _operationsCloseScheduleEditor();
  });
  $("operations-history-close")?.addEventListener("click", _operationsCloseHistory);
  $("operations-history-done")?.addEventListener("click", _operationsCloseHistory);
  $("operations-history-modal")?.addEventListener("click", event => {
    if (event.target === $("operations-history-modal")) _operationsCloseHistory();
  });
});
