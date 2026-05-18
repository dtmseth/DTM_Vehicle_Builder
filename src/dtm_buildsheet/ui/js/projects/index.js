// ── Projects module: coordinator / init ───────────────────────────────────────
// Public entry: initProjectsTab() — called by main.js when the Projects tab is shown.

// ── View switching ─────────────────────────────────────────────────────────────

function _ptShowList() {
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

  _ptRenderOverview(project);
  _ptRenderEditTab(project, false);
  _ptRenderBuildsTab(project);
  _ptSetDetailTab("overview");
}

function _ptShowEditor(project, activeTab) {
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
  ["overview", "edit", "builds"].forEach(t => {
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
  $("btn-new-project").addEventListener("click", () => _ptShowEditor(null));

  // Build editor wiring (Save & Return, Back)
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
    _ptWireAgencySearch(agencyInput, $("proj-agency-id"), $("proj-agency-suggestions"));
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
  _ptShowList();
};
