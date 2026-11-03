// ── Used vehicle strip documentation ────────────────────────────────────────

const _STRIP_CHECKLIST = [
  ["emergency_lights", "Emergency lights"],
  ["sirens", "Sirens, speakers, and control equipment"],
  ["amber_warning_lights", "Amber warning lights"],
  ["spotlights", "Spotlights"],
  ["grille_lights", "Grille lights"],
  ["antennas", "Antennas"],
  ["emblems", "Emblems, decals, and identifying graphics"],
  ["emblem_outlines", "Emblem outlines, adhesive shadows, and ghosting"],
  ["other_identifying_equipment", "Other emergency vehicle equipment or identifying insignia"],
];

let _stripRecord = null;
let _stripWired = false;
let _stripActiveTab = "sales";
let _stripRelationshipRevision = 0;

function _stripCanDocument() {
  return typeof appHasCapability === "function" && appHasCapability("completed_media.upload");
}

function _stripCanEditSales() {
  return typeof appHasCapability === "function" && appHasCapability("projects.edit");
}

function _stripStatus(text, state = "") {
  const host = $("strip-documentation-status");
  if (!host) return;
  host.textContent = text;
  host.dataset.state = state;
}

function _stripRenderChecklist(checklist = {}) {
  const host = $("strip-documentation-checklist");
  if (!host) return;
  host.innerHTML = _STRIP_CHECKLIST.map(([id, label]) => {
    const item = checklist[id] || {};
    return `<div class="strip-documentation-checklist-row" data-strip-checklist="${esc(id)}">
      <strong>${esc(label)}</strong>
      <select aria-label="${esc(label)} status">
        <option value=""${!item.status ? " selected" : ""}>Not checked</option>
        <option value="removed"${item.status === "removed" ? " selected" : ""}>Removed</option>
        <option value="not_present"${item.status === "not_present" ? " selected" : ""}>Not present</option>
        <option value="needs_attention"${item.status === "needs_attention" ? " selected" : ""}>Needs attention</option>
      </select>
      <input type="text" value="${esc(item.note || "")}" aria-label="${esc(label)} note" placeholder="Optional note">
    </div>`;
  }).join("");
}

function _stripSelectTab(tabName) {
  const nextTab = tabName === "technician" ? "technician" : "sales";
  _stripActiveTab = nextTab;
  document.querySelectorAll("[data-strip-tab]").forEach(button => {
    const active = button.dataset.stripTab === nextTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  const salesPanel = $("strip-documentation-sales-panel");
  const technicianPanel = $("strip-documentation-technician-section");
  if (salesPanel) salesPanel.hidden = nextTab !== "sales";
  if (technicianPanel) technicianPanel.hidden = nextTab !== "technician";
  const save = $("strip-documentation-save");
  if (save) {
    save.textContent = nextTab === "technician" ? "Save technician documentation" : "Save sales intake";
    save.disabled = nextTab === "technician" ? !_stripCanDocument() : !_stripCanEditSales();
  }
}

function _stripRender(record) {
  _stripRecord = {...record};
  document.querySelectorAll("#strip-documentation-form [data-strip-field]").forEach(control => {
    control.value = record[control.dataset.stripField] || "";
  });
  document.querySelectorAll("#strip-documentation-form [data-strip-check]").forEach(control => {
    control.checked = Boolean(record[control.dataset.stripCheck]);
  });
  _stripRenderChecklist(record.checklist || {});
  const vehicle = [record.vehicle_year, record.vehicle_make, record.vehicle_model].filter(Boolean).join(" ") || "Vehicle strip record";
  $("strip-documentation-vehicle-summary").textContent = record.unit_number ? `${vehicle} · Unit ${record.unit_number}` : vehicle;
  $("strip-documentation-vin-summary").textContent = record.vin ? `VIN ${record.vin}` : "VIN not entered";
  const canDocument = _stripCanDocument();
  const canEditSales = _stripCanEditSales();
  const salesPanel = $("strip-documentation-sales-panel");
  const technicianSection = $("strip-documentation-technician-section");
  const openPdf = $("strip-documentation-open-pdf");
  if (salesPanel) {
    salesPanel.querySelectorAll("input, textarea, select").forEach(control => {
      control.disabled = !canEditSales;
    });
  }
  const salesReadOnly = $("strip-documentation-sales-read-only");
  if (salesReadOnly) salesReadOnly.hidden = canEditSales;
  if (technicianSection) {
    technicianSection.querySelectorAll("input, textarea, select").forEach(control => {
      control.disabled = !canDocument;
    });
  }
  if (openPdf) openPdf.hidden = false;
  _stripSelectTab(_stripActiveTab);
  const statusLabels = {
    intake_draft: "Sales intake draft",
    intake_complete: "Sales intake saved - waiting for vehicle arrival",
    technician_draft: "Technician documentation in progress",
    form_ready: "Documentation complete",
  };
  _stripStatus(statusLabels[record.form_status] || "Sales intake draft", record.form_status || "intake_draft");
  _stripLoadTransferRelationship(record);
}

function _stripBuildOptionValue(build) {
  return [build.project_id, build.unit_id, build.individual_id].join("|");
}

async function _stripLoadTransferRelationship(record) {
  const select = $("strip-documentation-transfer-build");
  if (!select || !record.used_vehicle_id) return;
  const revision = ++_stripRelationshipRevision;
  select.disabled = true;
  try {
    const [usedResult, buildsResult] = await Promise.all([
      api("/api/used-vehicles"),
      api("/api/used-vehicles/build-suggestions", {agency_name: record.agency_name || ""}),
    ]);
    if (revision !== _stripRelationshipRevision) return;
    const usedVehicle = (usedResult?.records || []).find(item => item.used_vehicle_id === record.used_vehicle_id);
    const builds = buildsResult?.builds || [];
    select.innerHTML = [
      `<option value="">Not answered yet</option>`,
      `<option value="__not_linked__">No equipment transfer</option>`,
      ...builds.map(build => {
        const label = [
          `${build.project_agency || "Agency"} ${build.project_year || ""}`.trim(),
          build.build_type || "Build",
          build.unit_number ? `Unit ${build.unit_number}` : build.vin ? `VIN …${String(build.vin).slice(-6)}` : "Vehicle",
        ].join(" · ");
        return `<option value="${esc(_stripBuildOptionValue(build))}">${esc(label)}</option>`;
      }),
    ].join("");
    const current = usedVehicle?.transfer_links?.[0];
    if (current) select.value = _stripBuildOptionValue(current);
    else if (usedVehicle?.equipment_transfer_status === "not_linked") select.value = "__not_linked__";
    else select.value = "";
  } catch (_) {
    select.innerHTML = `<option value="">Relationship unavailable</option>`;
  } finally {
    if (revision === _stripRelationshipRevision) select.disabled = !_stripCanEditSales();
  }
}

function _stripCollect() {
  const record = {...(_stripRecord || {})};
  document.querySelectorAll("#strip-documentation-form [data-strip-field]").forEach(control => {
    record[control.dataset.stripField] = String(control.value || "").trim();
  });
  document.querySelectorAll("#strip-documentation-form [data-strip-check]").forEach(control => {
    record[control.dataset.stripCheck] = Boolean(control.checked);
  });
  record.performed_by = record.technician_signature || "";
  record.reviewed_by = record.reviewer_signature || "";
  record.checklist = {};
  document.querySelectorAll("[data-strip-checklist]").forEach(row => {
    const id = row.dataset.stripChecklist;
    record.checklist[id] = {
      status: row.querySelector("select")?.value || "",
      note: String(row.querySelector("input")?.value || "").trim(),
    };
  });
  return record;
}

async function _stripSave() {
  if (!_stripRecord) return null;
  _stripStatus("Saving…", "pending");
  const endpoint = _stripActiveTab === "technician"
    ? "/api/strip-documentation/save-technician"
    : "/api/strip-documentation/save-intake";
  const result = await api(endpoint, _stripCollect());
  if (!result?.ok) throw new Error(result?.error || "Strip documentation could not be saved");
  _stripRender(result.record);
  _stripStatus(result.sync_started ? "Saved · syncing" : "Saved", "saved");
  return result.record;
}

function _stripOpenModal(record) {
  _stripWire();
  _stripActiveTab = record.workflow_stage === "technician" || !_stripCanEditSales()
    ? "technician"
    : "sales";
  _stripRender(record);
  $("strip-documentation-modal")?.classList.add("open");
  const focusField = _stripActiveTab === "technician" ? "strip_date" : "agency_name";
  setTimeout(() => document.querySelector(`#strip-documentation-form [data-strip-field='${focusField}']`)?.focus(), 0);
}

function _stripCloseModal() {
  $("strip-documentation-modal")?.classList.remove("open");
  _stripRecord = null;
}

async function _stripFrom(endpoint, payload) {
  try {
    const result = await api(endpoint, payload);
    if (!result?.ok || !result.record) throw new Error(result?.error || "Strip documentation could not be created");
    _stripOpenModal(result.record);
  } catch (error) {
    toast(error?.message || "Strip documentation could not be opened", "error");
  }
}

function _stripWire() {
  if (_stripWired) return;
  _stripWired = true;
  $("strip-documentation-close")?.addEventListener("click", _stripCloseModal);
  $("strip-documentation-cancel")?.addEventListener("click", _stripCloseModal);
  $("strip-documentation-modal")?.addEventListener("click", event => {
    if (event.target === event.currentTarget) _stripCloseModal();
  });
  document.querySelectorAll("[data-strip-tab]").forEach(button => {
    button.addEventListener("click", () => _stripSelectTab(button.dataset.stripTab));
  });
  $("strip-documentation-transfer-build")?.addEventListener("change", async event => {
    if (!_stripRecord?.used_vehicle_id || !_stripCanEditSales()) return;
    const value = event.currentTarget.value;
    try {
      if (!value || value === "__not_linked__") {
        const result = await api("/api/used-vehicles/relationships", {
          used_vehicle_id: _stripRecord.used_vehicle_id,
          equipment_transfer_status: value === "__not_linked__" ? "not_linked" : "unknown",
        });
        if (!result?.ok) throw new Error(result?.error || "Relationship could not be saved");
        return;
      }
      const [projectId, unitId, individualId] = value.split("|");
      const result = await api("/api/used-vehicles/link-build", {
        used_vehicle_id: _stripRecord.used_vehicle_id,
        project_id: projectId,
        unit_id: unitId,
        individual_id: individualId,
      });
      if (!result?.ok) throw new Error(result?.error || "Build could not be linked");
      toast("Used vehicle linked to the selected build", "success");
    } catch (error) {
      toast(error?.message || "Relationship could not be saved", "error");
    }
  });
  $("strip-documentation-save")?.addEventListener("click", async () => {
    try {
      await _stripSave();
      toast("Strip documentation saved", "success");
    } catch (error) {
      _stripStatus(error?.message || "Save failed", "error");
      toast(error?.message || "Strip documentation could not be saved", "error");
    }
  });
  $("strip-documentation-open-pdf")?.addEventListener("click", async () => {
    try {
      const record = await _stripSave();
      if (!record) return;
      const result = await api("/api/strip-documentation/open-pdf", {record_id: record.record_id});
      if (!result?.ok) throw new Error(result?.error || "PDF could not be opened");
    } catch (error) {
      toast(error?.message || "PDF could not be opened", "error");
    }
  });
}

window.DTMStripDocumentation = {
  fromProject(projectId, unitId, individualId) {
    return _stripFrom("/api/strip-documentation/from-project", {
      project_id: projectId,
      unit_id: unitId,
      individual_id: individualId,
    });
  },
  fromSale(recordId) {
    return _stripFrom("/api/strip-documentation/from-sale", {record_id: recordId});
  },
};

_stripWire();
