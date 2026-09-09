// ── Projects module: coordinator / init ───────────────────────────────────────
// Public entry: initProjectsTab() — called by main.js when the Projects tab is shown.

// ── View switching ─────────────────────────────────────────────────────────────

function _ptShowList(mode = _PT.listMode || "active") {
  if (mode === "archive") mode = "completed";
  _PT.listMode = ["started", "active", "inactive", "completed"].includes(mode) ? mode : "active";
  show("proj-list-view");
  hide("proj-detail-view");
  hide("proj-editor");
  hide("proj-build-editor");
  _ptRenderList();
}

function _ptShowDetail(project) {
  _PT.viewProject      = project;
  _PT.editTabEditable  = false;
  hide("proj-list-view");
  show("proj-detail-view");
  hide("proj-editor");
  hide("proj-build-editor");

  $("proj-detail-agency").textContent = _ptProjName(project);
  const n = (project.build_units || []).reduce((s, u) => s + (u.quantity || 1), 0);
  $("proj-detail-meta").textContent = n + " unit" + (n !== 1 ? "s" : "");
  const completed = project.project_status === "completed";
  const inactive = project.project_status === "inactive";
  const inactiveBtn = $("btn-proj-inactive");
  inactiveBtn.hidden = completed || !_ptCanUpdateProjectLifecycle();
  inactiveBtn.textContent = inactive ? "Reactivate Project" : "Mark Project Inactive";
  const completionBtn = $("btn-proj-complete");
  completionBtn.hidden = !_ptCanUpdateProjectLifecycle();
  completionBtn.textContent = completed ? "Reopen Project" : "Mark Project Completed";
  completionBtn.className = `btn btn-sm ${completed ? "btn-primary" : "btn-secondary"}`;

  _ptRenderOverview(project);
  _ptRenderEditTab(project, false);
  _ptSetDetailTab("overview");
}

function _ptShowEditor(project, activeTab) {
  if (!_ptCanEditProjects()) {
    toast("This project is read only for your role", "error");
    return;
  }
  _PT.fromDetail = !!(project && _PT.viewProject);
  _PT.isWizard   = !project;
  _PT.editId     = project?.project_id || null;
  hide("proj-list-view");
  hide("proj-detail-view");
  show("proj-editor");
  hide("proj-build-editor");
  $("proj-editor-title").textContent = _PT.editId ? "Edit Project" : "New Project";
  _ptLoadPrefsOptions().then(() => {
    _ptLoadForm(project);
    _ptSetEditorTab(activeTab || "customer");
    _ptUpdateEditorButtons();
  });
  $("proj-op-status").style.display = "none";
}

// ── Detail tabs ────────────────────────────────────────────────────────────────

function _ptSetDetailTab(tab) {
  document.querySelectorAll(".proj-dtab").forEach(b =>
    b.classList.toggle("active", b.dataset.ptab === tab)
  );
  ["overview", "edit"].forEach(t => {
    const el = $("proj-ptab-" + t);
    if (el) el.classList.toggle("active", t === tab);
  });
}

// ── Editor (wizard) tabs ───────────────────────────────────────────────────────

function _ptSetEditorTab(tab) {
  document.querySelectorAll(".proj-etab").forEach(b =>
    b.classList.toggle("active", b.dataset.etab === tab)
  );
  _PT.WIZARD_TABS.forEach(t => {
    const el = $("proj-etab-" + t);
    if (el) el.classList.toggle("active", t === tab);
  });
  if (tab === "review") _ptRenderReview();
  _ptUpdateEditorButtons();
}

function _ptUpdateEditorButtons() {
  const current = document.querySelector(".proj-etab.active")?.dataset.etab || "customer";
  const idx     = _PT.WIZARD_TABS.indexOf(current);
  const isFirst = idx === 0;
  const isLast  = current === "review";

  $("proj-btn-save").style.display = _PT.isWizard ? "none" : "";

  const footer = $("proj-wizard-footer");
  if (footer) footer.style.display = _PT.isWizard ? "" : "none";

  const backBtn   = $("proj-btn-back");
  const nextBtn   = $("proj-btn-next");
  const finishBtn = $("proj-btn-finish");
  if (backBtn)   backBtn.style.display   = _PT.isWizard && !isFirst ? "" : "none";
  if (nextBtn)   nextBtn.style.display   = _PT.isWizard && !isLast  ? "" : "none";
  if (finishBtn) finishBtn.style.display = _PT.isWizard && isLast   ? "" : "none";

  const wizStep = $("proj-wizard-step");
  if (_PT.isWizard && wizStep) {
    wizStep.textContent = `Step ${idx + 1} of ${_PT.WIZARD_TABS.length}`;
    wizStep.style.display = "";
  } else if (wizStep) {
    wizStep.style.display = "none";
  }

  document.querySelectorAll(".proj-etab").forEach(btn => {
    btn.disabled = _PT.isWizard;
  });
}

function _ptWizardBack() {
  const current = document.querySelector(".proj-etab.active")?.dataset.etab || "customer";
  if (current === "fleet") _ptCollectUnits();
  const idx = _PT.WIZARD_TABS.indexOf(current);
  if (idx > 0) _ptSetEditorTab(_PT.WIZARD_TABS[idx - 1]);
}

function _ptWizardNext() {
  const current = document.querySelector(".proj-etab.active")?.dataset.etab || "customer";
  if (current === "customer" && !_ptOkCustomer()) return;
  if (current === "fleet") _ptCollectUnits();
  const idx = _PT.WIZARD_TABS.indexOf(current);
  if (idx >= 0 && idx < _PT.WIZARD_TABS.length - 1) {
    _ptSetEditorTab(_PT.WIZARD_TABS[idx + 1]);
  }
}

// ── One-time event binding ─────────────────────────────────────────────────────

function _ptBind() {
  if (typeof _ptBindReferencePhotoModal === "function") _ptBindReferencePhotoModal();
  document.addEventListener("click", event => {
    const openMenus = [...document.querySelectorAll(
      ".proj-build-action-menu[open], .proj-row-menu[open]"
    )];
    if (!openMenus.length) return;
    const target = event.target instanceof Element ? event.target : null;
    const targetMenu = target?.closest(".proj-build-action-menu, .proj-row-menu") || null;
    const insideOpenMenu = !!targetMenu && openMenus.includes(targetMenu);
    openMenus.forEach(menu => {
      if (menu !== targetMenu) menu.removeAttribute("open");
    });
    if (insideOpenMenu && target?.closest(
      ".proj-build-action-menu-items button, .proj-row-menu-items button"
    )) {
      targetMenu.removeAttribute("open");
    }
    if (!insideOpenMenu) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  $("btn-new-project").addEventListener("click", () => _ptShowEditor(null));
  document.querySelectorAll("[data-project-list-status]").forEach(button => {
    button.addEventListener("click", () => _ptShowList(button.dataset.projectListStatus));
  });
  $("proj-list-search").addEventListener("input", event => {
    _PT.listSearch[_PT.listMode] = event.target.value;
    _ptRenderList();
  });
  $("project-inactive-form").addEventListener("submit", event => {
    event.preventDefault();
    PT_confirmProjectInactive();
  });
  $("project-inactive-close").addEventListener("click", _ptCloseInactiveProjectModal);
  $("project-inactive-cancel").addEventListener("click", _ptCloseInactiveProjectModal);
  $("project-inactive-modal").addEventListener("click", event => {
    if (event.target === $("project-inactive-modal")) _ptCloseInactiveProjectModal();
  });
  document.querySelectorAll('input[name="project-completion-resolution"]').forEach(input => {
    input.addEventListener("change", _ptRefreshCompletionConflictChoice);
  });
  $("project-completion-overwrite-text").addEventListener("input", _ptRefreshCompletionConflictChoice);
  $("project-completion-conflict-close").addEventListener("click", _ptCloseCompletionConflictModal);
  $("project-completion-conflict-cancel").addEventListener("click", _ptCloseCompletionConflictModal);
  $("project-completion-conflict-apply").addEventListener("click", PT_applyCompletionConflict);
  $("project-completion-conflict-modal").addEventListener("click", event => {
    if (event.target === $("project-completion-conflict-modal")) {
      _ptCloseCompletionConflictModal();
    }
  });
  $("btn-proj-inactive").addEventListener("click", () => {
    if (_PT.viewProject) {
      PT_setProjectLifecycle(
        _PT.viewProject.project_id,
        _PT.viewProject.project_status === "inactive" ? "active" : "inactive",
      );
    }
  });
  $("btn-proj-complete").addEventListener("click", () => {
    if (_PT.viewProject) {
      PT_setProjectCompleted(
        _PT.viewProject.project_id,
        _PT.viewProject.project_status !== "completed",
      );
    }
  });

  // Build editor wiring (Return to Project)
  _ptBindBuildEditor();

  $("btn-proj-cancel").addEventListener("click", async () => {
    await _ptLoadAll();
    if (_PT.fromDetail && _PT.viewProject) {
      const updated = _PT.projects.find(p => p.project_id === _PT.viewProject.project_id);
      _ptShowDetail(updated || _PT.viewProject);
    } else {
      _ptShowList();
    }
  });

  $("btn-proj-detail-back").addEventListener("click", async () => {
    await _ptLoadAll();
    _ptShowList();
  });

  $("proj-btn-save").addEventListener("click", () => {
    if (!_ptOkCustomer()) { _ptSetEditorTab("customer"); return; }
    _ptSaveProject();
  });

  $("proj-btn-back").addEventListener("click",   () => _ptWizardBack());
  $("proj-btn-next").addEventListener("click",   () => _ptWizardNext());

  $("proj-btn-finish").addEventListener("click", () => {
    if (!_ptOkCustomer()) { _ptSetEditorTab("customer"); return; }
    _ptSaveProject();
  });

  document.querySelectorAll(".proj-dtab").forEach(btn =>
    btn.addEventListener("click", () => {
      if (_PT.editTabEditable && btn.dataset.ptab !== "edit") {
        _ptRenderEditTab(_PT.viewProject, false);
      }
      _ptSetDetailTab(btn.dataset.ptab);
    })
  );

  document.querySelectorAll(".proj-etab").forEach(btn =>
    btn.addEventListener("click", () => {
      if (_PT.isWizard) return;
      _ptCollectUnits();
      _ptSetEditorTab(btn.dataset.etab);
    })
  );

  $("btn-proj-add-unit").addEventListener("click", () => {
    _ptCollectUnits();
    _ptAddUnit();
    _ptRenderUnits();
  });

  // Close dropdowns / suggestions when clicking outside
  document.addEventListener("click", e => {
    if (!e.target.closest(".proj-preset-row")) {
      document.querySelectorAll(".proj-preset-dropdown").forEach(dd => dd.style.display = "none");
    }
    if (!e.target.closest(".proj-et-preset-row")) {
      document.querySelectorAll(".proj-et-preset-dd").forEach(dd => dd.style.display = "none");
    }
    const agencySugg = $("proj-agency-suggestions");
    if (agencySugg && !e.target.closest("#proj-agency") && !e.target.closest("#proj-agency-suggestions")) {
      agencySugg.style.display = "none";
    }
    const repSugg = $("proj-salesrep-suggestions");
    if (repSugg && !e.target.closest("#proj-salesrep") && !e.target.closest("#proj-salesrep-suggestions")) {
      repSugg.style.display = "none";
    }
    const etAgencySugg = $("et-agency-suggestions");
    if (etAgencySugg && !e.target.closest("#et-agency") && !e.target.closest("#et-agency-suggestions")) {
      etAgencySugg.style.display = "none";
    }
    const etRepSugg = $("et-salesrep-suggestions");
    if (etRepSugg && !e.target.closest("#et-salesrep") && !e.target.closest("#et-salesrep-suggestions")) {
      etRepSugg.style.display = "none";
    }
  });

  // Wizard customer tab — agency and sales rep live search
  const agencyInput = $("proj-agency");
  if (agencyInput) {
    _ptWireAgencySearch(
      agencyInput,
      $("proj-agency-id"),
      $("proj-agency-suggestions"),
      agency => _ptApplyAgencyDefaults(agency),
    );
  }
  const repInput = $("proj-salesrep");
  if (repInput) {
    _ptWireSalesRepSearch(repInput, $("proj-salesrep-id"), $("proj-salesrep-suggestions"));
  }
}

// ── Public entry point ─────────────────────────────────────────────────────────

window.initProjectsTab = async function () {
  if (!_PT.inited) { _ptBind(); _PT.inited = true; }
  await _ptLoadAll();
  _ptShowList(_PT.listMode);
};
