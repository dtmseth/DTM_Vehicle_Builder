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

window.PT_del = async function (pid) {
  if (!confirm("Delete this project? This cannot be undone.")) return;
  try {
    const res = await fetch(`/api/project/${encodeURIComponent(pid)}`, { method: "DELETE" }).then(r => r.json());
    if (res.ok) {
      toast("Project deleted", "success");
      if (_PT.viewProject?.project_id === pid) _PT.viewProject = null;
      await _ptLoadAll();
      _ptShowList();
    } else {
      toast(res.error || "Delete failed", "error");
    }
  } catch (e) {
    toast("Delete failed", "error");
  }
};
