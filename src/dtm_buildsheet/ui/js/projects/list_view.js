// ── Projects module: project list view ────────────────────────────────────────

function _ptRenderList() {
  if (!_PT.projects.length) {
    show("proj-list-empty");
    hide("proj-list-rows");
    return;
  }
  hide("proj-list-empty");
  show("proj-list-rows");
  $("proj-list-rows").innerHTML = _PT.projects.map(p => {
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

// Public entry: open project from list
window.PT_open = function (pid) {
  const p = _PT.projects.find(x => x.project_id === pid);
  if (p) _ptShowDetail(p);
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
