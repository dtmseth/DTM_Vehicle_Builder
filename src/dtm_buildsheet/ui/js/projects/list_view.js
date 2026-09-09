// ── Projects module: project list view ────────────────────────────────────────

function _ptProjectMatchesSearch(project, query) {
  if (!query) return true;
  const customer = project.customer || {};
  const values = [
    project.project_id,
    project.project_notes,
    project.inactive_reason,
    ...(project.quote_numbers || []),
    customer.name,
    customer.agency,
    customer.agency_abbreviation,
    customer.build_year,
    customer.sales_rep,
    customer.quote_number,
    customer.contact,
    customer.phone,
    customer.email,
  ];
  (project.build_units || []).forEach(unit => {
    values.push(unit.vehicle_model, unit.build_type);
    (unit.individuals || []).forEach(vehicle => {
      values.push(
        vehicle.unit_number,
        vehicle.vin,
        vehicle.year,
        vehicle.make,
        vehicle.model,
        vehicle.color,
        vehicle.notes,
      );
    });
  });
  return values.some(value => String(value || "").toLowerCase().includes(query));
}

function _ptProjectOperations(project) {
  const allOperations = _PT.operationsByProject?.[project.project_id] || [];
  const individualIds = new Set((project.build_units || []).flatMap(unit =>
    (unit.individuals || []).map(individual => individual.individual_id).filter(Boolean)
  ));
  return individualIds.size
    ? allOperations.filter(vehicle => individualIds.has(vehicle.vehicle_id))
    : allOperations;
}

function _ptProjectIsAccepted(project) {
  const vehicles = _ptProjectOperations(project);
  return vehicles.length > 0 && vehicles.every(vehicle =>
    String(vehicle.acceptance_status || "") === "accepted"
  );
}

function _ptProjectListStatus(project) {
  const storedStatus = String(project.project_status || "active");
  if (storedStatus === "inactive" || storedStatus === "completed") return storedStatus;
  return _ptProjectIsAccepted(project) ? "active" : "started";
}

function _ptProjectActiveSort(project) {
  const vehicles = _ptProjectOperations(project);
  const arrived = vehicles.length > 0 && vehicles.every(vehicle =>
    ["received", "parts_ready"].includes(String(vehicle.parts_status || "")) &&
    String(vehicle.vehicle_availability_status || "") === "at_dtm"
  );
  const deliveryDates = vehicles
    .map(vehicle => String(vehicle.must_deliver_by_date || "").trim())
    .filter(value => /^\d{4}-\d{2}-\d{2}$/.test(value))
    .sort();
  return {
    arrived,
    mustDeliverBy: deliveryDates[0] || "9999-12-31",
  };
}

function _ptSortActiveProjects(left, right) {
  const a = _ptProjectActiveSort(left);
  const b = _ptProjectActiveSort(right);
  if (a.arrived !== b.arrived) return a.arrived ? -1 : 1;
  const byDelivery = a.mustDeliverBy.localeCompare(b.mustDeliverBy);
  if (byDelivery) return byDelivery;
  return _ptProjName(left).localeCompare(_ptProjName(right), undefined, { numeric: true });
}

function _ptProjectDateLabel(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).toLocaleDateString(
    undefined,
    { month: "short", day: "numeric", year: "numeric" },
  );
}

function _ptProjectProgress(project) {
  const vehicles = _ptProjectOperations(project);
  if (!vehicles.length) return { key: "estimate-sent", label: "Estimate Sent" };

  const all = (field, values) => vehicles.every(vehicle => values.includes(String(vehicle[field] || "")));
  const any = (field, values) => vehicles.some(vehicle => values.includes(String(vehicle[field] || "")));
  if (all("final_finish_status", ["delivered"])) {
    return { key: "delivered", label: "Delivered" };
  }
  if (all("final_finish_status", ["ready_for_delivery", "delivered"])) {
    return { key: "ready-deliver", label: "Ready to Deliver" };
  }
  if (any("shop_status", ["in_progress", "complete"]) ||
      any("final_finish_status", ["ready_for_wash_clean_photos", "ready_for_delivery", "delivered"])) {
    return { key: "building", label: "Build in Progress" };
  }
  if (all("parts_status", ["parts_ready"]) &&
      all("vehicle_availability_status", ["at_dtm", "delivered"])) {
    return { key: "ready-build", label: "Ready to Build" };
  }

  const accepted = all("acceptance_status", ["accepted"]);
  const logisticsStarted = any("parts_status", ["ordered", "partially_received", "received", "parts_ready"]) ||
    any("vehicle_availability_status", ["waiting_on_dealer", "waiting_on_agency", "ready_for_pickup", "at_dtm", "delivered"]);
  if (accepted && logisticsStarted) {
    const common = (field, fallback) => {
      const values = new Set(vehicles.map(vehicle => String(vehicle[field] || fallback)));
      return values.size === 1 ? [...values][0] : "mixed";
    };
    const labels = {
      mixed: "Mixed",
      not_started: "Not started",
      ordered: "Ordered",
      partially_received: "Partially received",
      received: "Received",
      parts_ready: "Parts ready",
      awaiting_details: "Awaiting details",
      waiting_on_dealer: "Waiting on dealer",
      waiting_on_agency: "Waiting on agency",
      ready_for_pickup: "Ready for pickup",
      at_dtm: "At DTM",
      delivered: "Delivered",
    };
    const parts = common("parts_status", "not_started") || "not_started";
    const vehicle = common("vehicle_availability_status", "awaiting_details");
    return {
      key: "logistics",
      label: `Parts: ${labels[parts] || parts} · Vehicle: ${labels[vehicle] || vehicle}`,
    };
  }
  return accepted
    ? { key: "estimate-accepted", label: "Estimate Accepted" }
    : { key: "estimate-sent", label: "Estimate Sent" };
}

function _ptRenderList() {
  const statuses = ["started", "active", "inactive", "completed"];
  const mode = statuses.includes(_PT.listMode) ? _PT.listMode : "started";
  const query = String(_PT.listSearch?.[mode] || "").trim().toLowerCase();
  const counts = Object.fromEntries(statuses.map(status => [
    status,
    _PT.projects.filter(project => _ptProjectListStatus(project) === status).length,
  ]));
  statuses.forEach(status => {
    const count = $(`proj-${status}-count`);
    if (count) count.textContent = counts[status];
  });
  document.querySelectorAll("[data-project-list-status]").forEach(button => {
    const selected = button.dataset.projectListStatus === mode;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  const search = $("proj-list-search");
  if (search) {
    search.placeholder = `Search ${mode} projects…`;
    if (search.value !== (_PT.listSearch?.[mode] || "")) {
      search.value = _PT.listSearch?.[mode] || "";
    }
  }

  const completed = mode === "completed";
  $("proj-standard-panel").hidden = completed;
  $("proj-completed-panel").hidden = !completed;
  if (completed) {
    _ptRenderArchive(query);
    return;
  }

  const projects = _PT.projects.filter(project =>
    _ptProjectListStatus(project) === mode && _ptProjectMatchesSearch(project, query)
  );
  if (mode === "active") projects.sort(_ptSortActiveProjects);
  if (!projects.length) {
    $("proj-list-empty").textContent = query
      ? `No ${mode} projects match this search.`
      : mode === "inactive"
        ? "No inactive projects."
        : mode === "started"
          ? "No started projects. Click + New Project to get started."
          : "No active projects.";
    show("proj-list-empty");
    hide("proj-list-rows");
    return;
  }
  hide("proj-list-empty");
  show("proj-list-rows");
  $("proj-list-rows").innerHTML = projects.map(p => {
    const name = esc(_ptProjName(p));
    const n    = (p.build_units || []).reduce((s, u) => s + (u.quantity || 1), 0);
    const pid  = esc(p.project_id);
    const progress = ["started", "active"].includes(mode) ? _ptProjectProgress(p) : null;
    const activeSort = mode === "active" ? _ptProjectActiveSort(p) : null;
    const deliveryLabel = activeSort && activeSort.mustDeliverBy !== "9999-12-31"
      ? _ptProjectDateLabel(activeSort.mustDeliverBy)
      : "";
    return `<div class="proj-row proj-row-clickable" onclick="PT_open('${pid}')">
      <div class="proj-row-main">
        <div class="proj-row-heading">
          <div class="proj-row-agency">${name}</div>
          ${progress ? `<span class="proj-progress-badge proj-progress-badge-${progress.key}">${esc(progress.label)}</span>` : ""}
        </div>
        <div class="proj-row-meta">${n} unit${n !== 1 ? "s" : ""}${deliveryLabel ? ` · Must Deliver On ${esc(deliveryLabel)}` : ""}${mode === "inactive" && p.inactive_reason ? ` · ${esc(p.inactive_reason)}` : ""}</div>
      </div>
      <div class="proj-row-actions" onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="PT_open('${pid}')">Open</button>
        <details class="proj-row-menu">
          <summary aria-label="More actions for ${name}" title="More actions">⋯</summary>
          <div class="proj-row-menu-items">
            ${["started", "active"].includes(mode)
              ? `<button type="button" onclick="PT_setProjectLifecycle('${pid}','inactive')">Mark inactive</button>`
              : `<button type="button" onclick="PT_setProjectLifecycle('${pid}','active')">Reactivate</button>`}
            <button type="button" class="proj-row-menu-danger" onclick="PT_del('${pid}')">Delete project</button>
          </div>
        </details>
      </div>
    </div>`;
  }).join("");
}

function _ptRenderArchive(query = "") {
  const projects = _PT.projects.filter(project =>
    project.project_status === "completed" && _ptProjectMatchesSearch(project, query)
  );
  $("proj-archive-empty").hidden = projects.length > 0;
  if (!projects.length) {
    $("proj-archive-tree").innerHTML = "";
    $("proj-archive-empty").textContent = query
      ? "No completed projects match this search."
      : "No completed projects yet.";
    return;
  }

  const agencies = new Map();
  projects.forEach(project => {
    const agency = String(project.customer?.agency || "Unassigned Agency").trim() || "Unassigned Agency";
    const year = String(project.customer?.build_year || "Unassigned Year").trim() || "Unassigned Year";
    if (!agencies.has(agency)) agencies.set(agency, new Map());
    const years = agencies.get(agency);
    if (!years.has(year)) years.set(year, []);
    years.get(year).push(project);
  });

  const agencyEntries = Array.from(agencies.entries()).sort(([a], [b]) => a.localeCompare(b));
  $("proj-archive-tree").innerHTML = agencyEntries.map(([agency, years]) => {
    const count = Array.from(years.values()).reduce((total, entries) => total + entries.length, 0);
    const yearRows = Array.from(years.entries())
      .sort(([a], [b]) => b.localeCompare(a, undefined, { numeric: true }))
      .map(([year, entries]) => {
        const projectRows = entries
          .sort((a, b) => String(b.completed_at || b.updated_at || "").localeCompare(String(a.completed_at || a.updated_at || "")))
          .map(project => {
            const pid = esc(project.project_id);
            const unitCount = (project.build_units || []).reduce((sum, unit) => sum + (unit.quantity || 1), 0);
            const builds = (project.build_units || []).map(unit => {
              return [_ptVehicleModelLabel(unit), unit.build_type].filter(Boolean).join(" — ");
            }).filter(Boolean).join("; ");
            return `<div class="proj-archive-project" data-archive-project-id="${pid}">
              <div>
                <div class="proj-archive-project-title">${esc(year)} project</div>
                <div class="proj-row-meta">${unitCount} unit${unitCount === 1 ? "" : "s"}${builds ? ` · ${esc(builds)}` : ""}</div>
              </div>
              <div class="proj-row-actions">
                ${_ptCompletedPhotoButtonMarkup(project.project_id)}
                <button class="btn btn-secondary btn-sm" onclick="PT_openPhotoGallery('${pid}','reference')">Project photos</button>
                ${project.shop_year_folder_path ? `<button class="btn btn-secondary btn-sm" data-library-target="shop" data-folder-path="${esc(project.shop_year_folder_path)}" onclick="PT_openCloudFolder(this)">Open Shop folder</button>` : ""}
                <button class="btn btn-primary btn-sm" onclick="PT_openArchived('${pid}')">Open</button>
                <button class="btn btn-secondary btn-sm" onclick="PT_setProjectCompleted('${pid}', false)">Reopen</button>
              </div>
            </div>`;
          }).join("");
        return `<details class="proj-archive-year"${query ? " open" : ""}>
          <summary><span>${esc(year)}</span><span>${entries.length} project${entries.length === 1 ? "" : "s"}</span></summary>
          <div class="proj-archive-year-projects">${projectRows}</div>
        </details>`;
      }).join("");
    return `<details class="proj-archive-agency"${query ? " open" : ""}>
      <summary><span>${esc(agency)}</span><span>${count} project${count === 1 ? "" : "s"}</span></summary>
      <div class="proj-archive-years">${yearRows}</div>
    </details>`;
  }).join("");
  $("proj-archive-tree").querySelectorAll("details.proj-archive-year").forEach(year => {
    year.addEventListener("toggle", () => {
      if (!year.open || typeof _ptRefreshCompletedPhotoActions !== "function") return;
      year.querySelectorAll("[data-archive-project-id]").forEach(row => {
        _ptRefreshCompletedPhotoActions(row.dataset.archiveProjectId || "", row);
      });
    });
  });
}

// Public entry: open project from list
window.PT_open = function (pid) {
  const p = _PT.projects.find(x => x.project_id === pid);
  if (p) _ptShowDetail(p);
};

window.PT_openArchived = function (pid) {
  _PT.listMode = "completed";
  PT_open(pid);
};

function _ptCloseInactiveProjectModal() {
  const modal = $("project-inactive-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  _PT.inactiveProjectId = null;
}

function _ptOpenInactiveProjectModal(pid) {
  const project = (_PT.projects || []).find(item => item.project_id === pid) ||
    (_PT.viewProject?.project_id === pid ? _PT.viewProject : null);
  if (!project) return;
  _PT.inactiveProjectId = pid;
  $("project-inactive-project").textContent = _ptProjName(project);
  $("project-inactive-reason").value = project.inactive_reason || "";
  $("project-inactive-status").hidden = true;
  const modal = $("project-inactive-modal");
  modal.hidden = false;
  modal.classList.add("open");
  requestAnimationFrame(() => $("project-inactive-reason")?.focus());
}

async function _ptApplyProjectLifecycle(pid, status, reason = "") {
  const button = $("project-inactive-save");
  const statusMessage = $("project-inactive-status");
  if (status === "inactive") {
    button.disabled = true;
    button.textContent = "Saving…";
    statusMessage.textContent = "Updating project…";
    statusMessage.hidden = false;
  }
  try {
    const result = await api(`/api/project/${encodeURIComponent(pid)}/lifecycle`, {
      status,
      reason,
    });
    if (!result.ok) {
      toast(result.error || "Project status could not be changed", "error");
      if (status === "inactive") {
        statusMessage.textContent = result.error || "Project status could not be changed.";
      }
      return;
    }
    if (status === "inactive") _ptCloseInactiveProjectModal();
    await _ptLoadAll();
    _PT.viewProject = null;
    const updatedProject = _PT.projects.find(project => project.project_id === pid);
    const destination = updatedProject ? _ptProjectListStatus(updatedProject) : status;
    toast(
      status === "inactive"
        ? "Project moved to Inactive"
        : `Project returned to ${destination === "started" ? "Started" : "Active"}`,
      "success",
    );
    _ptShowList(destination);
  } catch (error) {
    toast(error.message || "Project status could not be changed", "error");
    if (status === "inactive") {
      statusMessage.textContent = error.message || "Project status could not be changed.";
    }
  } finally {
    if (status === "inactive") {
      button.disabled = false;
      button.textContent = "Mark Inactive";
    }
  }
}

window.PT_setProjectLifecycle = function (pid, status) {
  if (status === "inactive") {
    _ptOpenInactiveProjectModal(pid);
    return;
  }
  _ptApplyProjectLifecycle(pid, status);
};

window.PT_confirmProjectInactive = function () {
  if (!_PT.inactiveProjectId) return;
  _ptApplyProjectLifecycle(
    _PT.inactiveProjectId,
    "inactive",
    $("project-inactive-reason").value.trim(),
  );
};

function _ptCloseCompletionConflictModal() {
  const modal = $("project-completion-conflict-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  _PT.completionConflict = null;
}

function _ptCompletionSideHtml(title, project) {
  const vehicles = project?.vehicles || [];
  const rows = vehicles.length
    ? vehicles.map(vehicle => {
        const facts = [
          vehicle.unit_number ? `Unit ${vehicle.unit_number}` : "",
          vehicle.vin ? `VIN ${vehicle.vin}` : "",
          vehicle.build_type || "",
        ].filter(Boolean).join(" · ");
        return `<li><strong>${esc(vehicle.label || vehicle.vehicle_model || "Vehicle")}</strong>${facts ? `<small>${esc(facts)}</small>` : ""}</li>`;
      }).join("")
    : "<li>No individual vehicle details are saved.</li>";
  const quotes = (project?.quote_numbers || []).filter(Boolean).join(", ") || "No quote numbers";
  return `<section class="project-completion-side">
    <h3>${esc(title)}</h3>
    <small>${Number(project?.vehicle_count || 0)} vehicle${Number(project?.vehicle_count || 0) === 1 ? "" : "s"} · ${esc(quotes)}</small>
    <ul class="project-completion-vehicles">${rows}</ul>
  </section>`;
}

function _ptRefreshCompletionConflictChoice() {
  const choice = document.querySelector('input[name="project-completion-resolution"]:checked')?.value || "";
  const confirmBox = $("project-completion-overwrite-confirm");
  const confirmation = $("project-completion-overwrite-text");
  const apply = $("project-completion-conflict-apply");
  if (confirmBox) confirmBox.hidden = choice !== "overwrite";
  if (apply) {
    apply.disabled = !choice || (choice === "overwrite" && confirmation?.value.trim() !== "OVERWRITE");
    apply.textContent = choice === "merge" ? "Merge & Complete" :
      choice === "overwrite" ? "Overwrite & Complete" : "Complete Project";
    apply.className = `btn ${choice === "overwrite" ? "btn-danger" : "btn-primary"}`;
  }
}

function _ptOpenCompletionConflictModal(pid, result) {
  _PT.completionConflict = { pid, result };
  $("project-completion-conflict-comparison").innerHTML =
    _ptCompletionSideHtml("Already completed", result.completed_project) +
    _ptCompletionSideHtml("Active project", result.active_project);
  document.querySelectorAll('input[name="project-completion-resolution"]').forEach(input => {
    input.checked = false;
  });
  $("project-completion-overwrite-text").value = "";
  $("project-completion-conflict-status").hidden = true;
  _ptRefreshCompletionConflictChoice();
  const modal = $("project-completion-conflict-modal");
  modal.hidden = false;
  modal.classList.add("open");
}

async function _ptRequestProjectCompletion(pid, completed, extra = {}) {
  try {
    const result = await api(`/api/project/${encodeURIComponent(pid)}/completion`, {
      completed: !!completed,
      ...extra,
    });
    if (!result.ok) {
      if (result.error_code === "completed_project_exists_for_agency_year") {
        _ptOpenCompletionConflictModal(pid, result);
        return;
      }
      toast(result.error || "Project status could not be changed", "error");
      return;
    }
    _ptCloseCompletionConflictModal();
    await _ptLoadAll();
    _PT.viewProject = null;
    const completionMessage = result.resolution === "merge"
      ? "Projects merged and moved to Completed"
      : result.resolution === "overwrite"
        ? "Completed project replaced with the active project"
        : completed ? "Project moved to Completed" : "Project reopened";
    toast(completionMessage, "success");
    const updatedProject = _PT.projects.find(project => project.project_id === pid);
    _ptShowList(completed
      ? "completed"
      : updatedProject ? _ptProjectListStatus(updatedProject) : "started");
  } catch (error) {
    toast(error.message || "Project status could not be changed", "error");
  }
}

window.PT_applyCompletionConflict = async function () {
  const context = _PT.completionConflict;
  if (!context) return;
  const resolution = document.querySelector('input[name="project-completion-resolution"]:checked')?.value || "";
  if (!resolution) return;
  const confirmation = $("project-completion-overwrite-text").value.trim();
  if (resolution === "overwrite" && confirmation !== "OVERWRITE") return;
  const apply = $("project-completion-conflict-apply");
  const status = $("project-completion-conflict-status");
  apply.disabled = true;
  apply.textContent = resolution === "overwrite" ? "Overwriting…" : "Merging…";
  status.hidden = false;
  status.textContent = "Updating the project and Operations records…";
  await _ptRequestProjectCompletion(context.pid, true, {
    conflict_resolution: resolution,
    overwrite_confirmation: confirmation,
  });
  if (_PT.completionConflict) {
    status.textContent = "The projects could not be combined. Nothing else will be attempted.";
    _ptRefreshCompletionConflictChoice();
  }
};

window.PT_setProjectCompleted = async function (pid, completed) {
  if (completed) {
    const project = (_PT.projects || []).find(item => item.project_id === pid) || _PT.viewProject;
    const label = project
      ? `${project.customer?.agency || "this project"}${project.customer?.build_year ? ` ${project.customer.build_year}` : ""}`
      : "this project";
    if (!confirm(`Mark ${label} completed?\n\nIt will move to the Completed tab. Completed photos will remain available, and the project can be reopened later.`)) return;
  }
  await _ptRequestProjectCompletion(pid, completed);
};

// ── Delete project modal ───────────────────────────────────────────────────────
(function () {
  let _delPid = null;

  async function _doDelete(deleteFiles) {
    try {
      const res = await api(`/api/project/${encodeURIComponent(_delPid)}/delete`, { delete_files: deleteFiles });
      if (res.ok) {
        toast(deleteFiles ? "Project, Operations history, and output files deleted" : "Project and Operations history deleted", "success");
        if (_PT.viewProject?.project_id === _delPid) _PT.viewProject = null;
        await _ptLoadAll();
        _ptShowList();
      } else {
        toast(res.error || "Delete failed", "error");
      }
    } catch (e) {
      toast("Delete failed", "error");
    } finally {
      $("del-project-modal").classList.remove("open");
      _delPid = null;
    }
  }

  window.PT_del = function (pid) {
    _delPid = pid;
    const p = _PT.projects.find(x => x.project_id === pid);
    const name = p ? _ptProjName(p) : pid;
    $("del-project-modal-msg").textContent =
      `"${name}" — deleting the project also permanently deletes its Operations records and status history. Choose whether to delete its output files too.`;
    $("del-project-modal").classList.add("open");
  };

  document.addEventListener("DOMContentLoaded", () => {
    const overlay = $("del-project-modal");
    $("del-with-files-btn").addEventListener("click",  () => _doDelete(true));
    $("del-proj-only-btn").addEventListener("click",   () => _doDelete(false));
    $("del-cancel-btn").addEventListener("click",      () => {
      overlay.classList.remove("open");
      _delPid = null;
    });
    overlay.addEventListener("click", e => {
      if (e.target === overlay) { overlay.classList.remove("open"); _delPid = null; }
    });
  });
})();
