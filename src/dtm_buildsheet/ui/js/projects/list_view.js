// ── Projects module: project list view ────────────────────────────────────────

function _ptRenderList() {
  const activeProjects = _PT.projects.filter(p => p.project_status !== "completed");
  const archiveCount = _PT.projects.length - activeProjects.length;
  $("proj-archive-count").textContent = archiveCount
    ? `${archiveCount} completed project${archiveCount === 1 ? "" : "s"}`
    : "";
  if (!activeProjects.length) {
    show("proj-list-empty");
    hide("proj-list-rows");
    return;
  }
  hide("proj-list-empty");
  show("proj-list-rows");
  $("proj-list-rows").innerHTML = activeProjects.map(p => {
    const name = esc(_ptProjName(p));
    const n    = (p.build_units || []).reduce((s, u) => s + (u.quantity || 1), 0);
    const pid  = esc(p.project_id);
    return `<div class="proj-row proj-row-clickable" onclick="PT_open('${pid}')">
      <div class="proj-row-main">
        <div class="proj-row-agency">${name}</div>
        <div class="proj-row-meta">${n} unit${n !== 1 ? "s" : ""}</div>
      </div>
      <div class="proj-row-actions" onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="PT_open('${pid}')">Open</button>
        <button class="btn btn-danger btn-sm"  onclick="PT_del('${pid}')">Delete</button>
      </div>
    </div>`;
  }).join("");
}

function _ptRenderArchive() {
  const projects = _PT.projects.filter(p => p.project_status === "completed");
  $("proj-archive-empty").hidden = projects.length > 0;
  if (!projects.length) {
    $("proj-archive-tree").innerHTML = "";
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
        return `<details class="proj-archive-year">
          <summary><span>${esc(year)}</span><span>${entries.length} project${entries.length === 1 ? "" : "s"}</span></summary>
          <div class="proj-archive-year-projects">${projectRows}</div>
        </details>`;
      }).join("");
    return `<details class="proj-archive-agency">
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
  _PT.listMode = "archive";
  PT_open(pid);
};

window.PT_setProjectCompleted = async function (pid, completed) {
  if (completed) {
    const project = (_PT.projects || []).find(item => item.project_id === pid) || _PT.viewProject;
    const label = project
      ? `${project.customer?.agency || "this project"}${project.customer?.build_year ? ` ${project.customer.build_year}` : ""}`
      : "this project";
    if (!confirm(`Mark ${label} completed?\n\nIt will move to Project Archives. Completed photos will remain available, and the project can be reopened later.`)) return;
  }
  try {
    const result = await api(`/api/project/${encodeURIComponent(pid)}/completion`, {
      completed: !!completed,
    });
    if (!result.ok) {
      toast(result.error || "Project status could not be changed", "error");
      return;
    }
    await _ptLoadAll();
    _PT.viewProject = null;
    toast(completed ? "Project moved to Project Archives" : "Project returned to Active Projects", "success");
    _ptShowList(completed ? "archive" : "active");
  } catch (error) {
    toast(error.message || "Project status could not be changed", "error");
  }
};

// ── Delete project modal ───────────────────────────────────────────────────────
(function () {
  let _delPid = null;

  async function _doDelete(deleteFiles) {
    try {
      const res = await api(`/api/project/${encodeURIComponent(_delPid)}/delete`, { delete_files: deleteFiles });
      if (res.ok) {
        toast(deleteFiles ? "Project and output files deleted" : "Project deleted", "success");
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
      `"${name}" — choose what to delete. Output files are the build sheets in the project output folder.`;
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
