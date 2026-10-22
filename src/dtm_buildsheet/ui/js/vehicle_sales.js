// ── Vehicle Buyback / Sale workspace ─────────────────────────────────────────

let _vehicleSaleRecords = [];
let _vehicleSaleActive = null;
let _vehicleSaleSaveTimer = null;
let _vehicleSaleSaveQueue = Promise.resolve();
let _vehicleSalesWired = false;
let _vehicleSaleMatchTimer = null;
let _vehicleSaleMatchRevision = 0;
let _vehicleSaleMatches = [];

function _vehicleSaleCloseDeleteModal() {
  $("vehicle-sales-delete-modal")?.classList.remove("open");
  const status = $("vehicle-sales-delete-status");
  if (status) status.textContent = "";
}

function _vehicleSaleOpenDeleteModal() {
  if (!_vehicleSaleActive) return;
  $("vehicle-sales-delete-summary").textContent = _vehicleSaleSummary(_vehicleSaleActive);
  $("vehicle-sales-delete-confirm").disabled = false;
  $("vehicle-sales-delete-status").textContent = "";
  $("vehicle-sales-delete-modal").classList.add("open");
  setTimeout(() => $("vehicle-sales-delete-cancel").focus(), 0);
}

async function _vehicleSaleDeleteConfirmed() {
  if (!_vehicleSaleActive) return;
  const button = $("vehicle-sales-delete-confirm");
  const status = $("vehicle-sales-delete-status");
  button.disabled = true;
  status.textContent = "Deleting record and PDF…";
  try {
    await _vehicleSaleEnsureSaved();
    const result = await api("/api/vehicle-sales/delete", {
      record_id: _vehicleSaleActive.record_id,
      confirmation: "DELETE RECORD",
    });
    if (!result?.ok) throw new Error(result?.error || "Record could not be deleted");
    _vehicleSaleRecords = _vehicleSaleRecords.filter(item => item.record_id !== result.record_id);
    _vehicleSaleActive = null;
    $("vehicle-sales-editor").hidden = true;
    $("vehicle-sales-list").hidden = false;
    _vehicleSaleRenderList();
    _vehicleSaleCloseDeleteModal();
    toast("Vehicle record and PDF deleted", "success");
  } catch (error) {
    status.textContent = error?.message || "Record could not be deleted";
    button.disabled = false;
  }
}

function _vehicleSaleSummary(record) {
  const vehicle = [record.vehicle_year, record.vehicle_make, record.vehicle_model]
    .filter(Boolean).join(" ") || "Vehicle not entered";
  const unit = record.vehicle_unit_number ? ` · Unit ${record.vehicle_unit_number}` : "";
  return `${vehicle}${unit}`;
}

function _vehicleSaleSearchText(record) {
  return [
    record.purchased_from, record.buyer_name, record.vin, record.project_agency,
    record.vehicle_unit_number, record.vehicle_year, record.vehicle_make,
    record.vehicle_model, record.quote_number, record.order_invoice_number,
  ].join(" ").toLowerCase();
}

function _vehicleSaleRenderList() {
  const host = $("vehicle-sales-years");
  const message = $("vehicle-sales-message");
  if (!host || !message) return;
  const query = String($("vehicle-sales-search")?.value || "").trim().toLowerCase();
  const visible = _vehicleSaleRecords.filter(record => !query || _vehicleSaleSearchText(record).includes(query));
  if (!visible.length) {
    host.innerHTML = "";
    message.hidden = false;
    message.textContent = query
      ? "No vehicle records match this search."
      : "No buyback or sale records yet. Create one here or from an existing vehicle in a project.";
    return;
  }
  message.hidden = true;
  const byYear = new Map();
  visible.forEach(record => {
    const year = record.record_year || "Unassigned";
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year).push(record);
  });
  host.innerHTML = [...byYear.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([year, records]) => `<section class="vehicle-sales-year">
      <h2>${esc(year)} <span>${records.length}</span></h2>
      <div class="vehicle-sales-records">${records.map(record => {
        const status = record.date_sold ? `Sold ${esc(record.date_sold)}` : "Held for resale";
        const people = record.buyer_name
          ? `Buyer: ${esc(record.buyer_name)}`
          : record.purchased_from ? `Purchased from: ${esc(record.purchased_from)}` : "Purchase details not entered";
        return `<button type="button" class="vehicle-sales-record" data-vehicle-sale-id="${esc(record.record_id)}">
          <span class="vehicle-sales-record-main">
            <strong>${esc(_vehicleSaleSummary(record))}</strong>
            <small>${people}</small>
          </span>
          <span class="vehicle-sales-record-meta">
            <b>${status}</b>
            <small>${record.project_id ? `Linked to ${esc(record.project_agency || "a Builder vehicle")}` : "Standalone record"}</small>
          </span>
          <span aria-hidden="true">›</span>
        </button>`;
      }).join("")}</div>
    </section>`).join("");
  host.querySelectorAll("[data-vehicle-sale-id]").forEach(button => {
    button.addEventListener("click", () => {
      const record = _vehicleSaleRecords.find(item => item.record_id === button.dataset.vehicleSaleId);
      if (record) _vehicleSaleOpenEditor(record);
    });
  });
}

function _vehicleSaleOpenEditor(record) {
  _vehicleSaleActive = { ...record };
  document.querySelectorAll("#vehicle-sales-form [data-sale-field]").forEach(control => {
    const field = control.dataset.saleField;
    if (field === "purchase_via" && control.type === "radio") {
      control.checked = control.value === String(record.purchase_via || "");
    } else if (control.type === "checkbox") {
      control.checked = Boolean(record[field]);
    } else {
      control.value = record[field] || "";
    }
  });
  if ($("vehicle-sales-purchased-from-agency-id")) $("vehicle-sales-purchased-from-agency-id").value = "";
  if ($("vehicle-sales-purchased-from-suggestions")) $("vehicle-sales-purchased-from-suggestions").style.display = "none";
  $("vehicle-sales-list").hidden = true;
  $("vehicle-sales-editor").hidden = false;
  $("vehicle-sales-editor-subtitle").textContent = _vehicleSaleSummary(record);
  const linked = Boolean(record.project_id && record.individual_id);
  $("vehicle-sales-link").hidden = !linked;
  $("vehicle-sales-link-label").textContent = [record.project_agency, record.vehicle_unit_number ? `Unit ${record.vehicle_unit_number}` : ""].filter(Boolean).join(" · ") || "Existing vehicle";
  _vehicleSaleSetSaveState("Saved", "saved");
  _vehicleSaleRefreshPurchaseState();
  _vehicleSaleScheduleMatch({immediate: true});
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function _vehicleSaleCollect() {
  const record = { ...(_vehicleSaleActive || {}) };
  document.querySelectorAll("#vehicle-sales-form [data-sale-field]").forEach(control => {
    const field = control.dataset.saleField;
    if (field === "purchase_via" && control.type === "radio") {
      if (control.checked) record[field] = control.value;
    } else if (control.type === "checkbox") {
      record[field] = control.checked;
    } else {
      record[field] = control.value.trim();
    }
  });
  if (!document.querySelector("input[name='vehicle-sales-purchase-via']:checked")) {
    record.purchase_via = "";
  }
  return record;
}

function _vehicleSaleSetSaveState(text, state = "") {
  const status = $("vehicle-sales-save-state");
  if (!status) return;
  status.textContent = text;
  status.dataset.state = state;
}

function _vehicleSaleRefreshPurchaseState() {
  const via = document.querySelector("input[name='vehicle-sales-purchase-via']:checked")?.value || "";
  const invoiceNumber = document.querySelector("[data-sale-field='quote_number']")?.value.trim() || "";
  $("vehicle-sales-credit-note")?.closest(".vehicle-sales-credit-row")
    ?.classList.toggle("is-required", via === "account_credit" && !invoiceNumber);
}

function _vehicleSaleField(name) {
  return document.querySelector(`#vehicle-sales-form [data-sale-field='${name}']`);
}

function _vehicleSaleHideMatches() {
  clearTimeout(_vehicleSaleMatchTimer);
  _vehicleSaleMatchRevision += 1;
  _vehicleSaleMatches = [];
  const assistant = $("vehicle-sales-match-assistant");
  if (assistant) assistant.hidden = true;
  $("vehicle-sales-match-results")?.replaceChildren();
}

function _vehicleSaleRenderMatches(matches) {
  const assistant = $("vehicle-sales-match-assistant");
  const status = $("vehicle-sales-match-status");
  const results = $("vehicle-sales-match-results");
  if (!assistant || !status || !results) return;
  assistant.hidden = false;
  _vehicleSaleMatches = matches;
  if (!matches.length) {
    status.textContent = "No previous build matched this VIN or agency and unit number.";
    results.replaceChildren();
    return;
  }
  status.textContent = `${matches.length} possible ${matches.length === 1 ? "match" : "matches"}. Review before using one.`;
  results.innerHTML = matches.map((match, index) => {
    const vehicle = [match.vehicle_year, match.vehicle_make, match.vehicle_model].filter(Boolean).join(" ") || "Vehicle details not recorded";
    const identifiers = [
      match.vehicle_unit_number ? `Unit ${match.vehicle_unit_number}` : "",
      match.vin ? `VIN ${match.vin}` : "",
    ].filter(Boolean).join(" · ");
    const project = [match.project_agency || "Agency not recorded", match.build_type || "", match.project_status || ""].filter(Boolean).join(" · ");
    return `<article class="vehicle-sales-match-card">
      <div class="vehicle-sales-match-copy">
        <div class="vehicle-sales-match-reasons">${(match.match_reasons || []).map(reason => `<span>${esc(reason)}</span>`).join("")}</div>
        <strong>${esc(vehicle)}</strong>
        <span>${esc(identifiers || "No unit number or VIN recorded")}</span>
        <small>${esc(project)}</small>
      </div>
      <button type="button" class="btn btn-primary btn-sm" data-vehicle-sale-match-index="${index}">Use this vehicle</button>
    </article>`;
  }).join("");
  results.querySelectorAll("[data-vehicle-sale-match-index]").forEach(button => {
    button.addEventListener("click", () => _vehicleSaleUseMatch(Number(button.dataset.vehicleSaleMatchIndex)));
  });
}

function _vehicleSaleScheduleMatch({immediate = false} = {}) {
  clearTimeout(_vehicleSaleMatchTimer);
  const vin = String(_vehicleSaleField("vin")?.value || "").trim();
  const agency = String(_vehicleSaleField("purchased_from")?.value || "").trim();
  const unitNumber = String(_vehicleSaleField("vehicle_unit_number")?.value || "").trim();
  const vinKey = vin.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (vinKey.length < 8 && !(agency && unitNumber)) {
    _vehicleSaleHideMatches();
    return;
  }
  const revision = ++_vehicleSaleMatchRevision;
  const run = async () => {
    const assistant = $("vehicle-sales-match-assistant");
    const status = $("vehicle-sales-match-status");
    if (assistant && status) {
      assistant.hidden = false;
      status.textContent = "Checking previous builds…";
    }
    try {
      const result = await api("/api/vehicle-sales/matches", {
        vin,
        agency,
        unit_number: unitNumber,
        exclude_project_id: _vehicleSaleActive?.project_id || "",
      });
      if (revision !== _vehicleSaleMatchRevision) return;
      if (!result?.ok) throw new Error(result?.error || "Vehicle matching failed");
      _vehicleSaleRenderMatches(result.matches || []);
    } catch (_) {
      if (revision !== _vehicleSaleMatchRevision || !assistant || !status) return;
      assistant.hidden = false;
      status.textContent = "Previous builds could not be checked right now.";
      $("vehicle-sales-match-results")?.replaceChildren();
    }
  };
  if (immediate) run();
  else _vehicleSaleMatchTimer = setTimeout(run, 450);
}

function _vehicleSaleUseMatch(index) {
  const match = _vehicleSaleMatches[index];
  if (!match) return;
  const values = {
    purchased_from: match.project_agency,
    vehicle_unit_number: match.vehicle_unit_number,
    vehicle_year: match.vehicle_year,
    vehicle_make: match.vehicle_make,
    vehicle_model: match.vehicle_model,
    vehicle_color: match.vehicle_color,
    vin: match.vin,
  };
  Object.entries(values).forEach(([field, value]) => {
    const control = _vehicleSaleField(field);
    if (control && value) control.value = value;
  });
  _vehicleSaleHideMatches();
  $("vehicle-sales-editor-subtitle").textContent = _vehicleSaleSummary(_vehicleSaleCollect());
  _vehicleSaleQueueSave({immediate: true});
  toast("Vehicle details filled from the previous build", "success");
}

function _vehicleSaleQueueSave({ immediate = false } = {}) {
  clearTimeout(_vehicleSaleSaveTimer);
  _vehicleSaleSetSaveState("Unsaved changes", "pending");
  const enqueue = () => {
    const snapshot = _vehicleSaleCollect();
    _vehicleSaleSetSaveState("Saving & updating PDF…", "saving");
    _vehicleSaleSaveQueue = _vehicleSaleSaveQueue.catch(() => {}).then(async () => {
      const result = await api("/api/vehicle-sales/save", snapshot);
      if (!result?.ok) throw new Error(result?.error || "Vehicle record could not be saved");
      _vehicleSaleActive = result.record;
      const index = _vehicleSaleRecords.findIndex(item => item.record_id === result.record.record_id);
      if (index >= 0) _vehicleSaleRecords[index] = result.record;
      else _vehicleSaleRecords.unshift(result.record);
      _vehicleSaleSetSaveState(result.sync_started ? "Saved · SharePoint syncing" : "Saved locally", "saved");
      return result;
    }).catch(error => {
      console.error("Vehicle sale save failed", error);
      _vehicleSaleSetSaveState("Save failed", "error");
      toast(error?.message || "Vehicle record could not be saved", "error");
      throw error;
    });
    return _vehicleSaleSaveQueue;
  };
  if (immediate) return enqueue();
  _vehicleSaleSaveTimer = setTimeout(enqueue, 650);
  return _vehicleSaleSaveQueue;
}

async function _vehicleSaleEnsureSaved() {
  clearTimeout(_vehicleSaleSaveTimer);
  if ($("vehicle-sales-save-state")?.dataset.state === "pending") {
    await _vehicleSaleQueueSave({ immediate: true });
  } else {
    await _vehicleSaleSaveQueue;
  }
}

async function _vehicleSaleLoad() {
  const message = $("vehicle-sales-message");
  const years = $("vehicle-sales-years");
  if (years) years.setAttribute("aria-busy", "true");
  if (message) {
    message.hidden = false;
    message.textContent = "Loading vehicle records…";
  }
  try {
    const result = await api("/api/vehicle-sales");
    _vehicleSaleRecords = result?.records || [];
    _vehicleSaleRenderList();
  } catch (error) {
    if (message) {
      message.hidden = false;
      message.textContent = error?.message || "Vehicle records could not be loaded.";
    }
  } finally {
    if (years) years.removeAttribute("aria-busy");
  }
}

async function _vehicleSaleNew() {
  try {
    const result = await api("/api/vehicle-sales/new", {});
    if (!result?.ok) throw new Error(result?.error || "Record could not be created");
    _vehicleSaleRecords.unshift(result.record);
    _vehicleSaleOpenEditor(result.record);
  } catch (error) {
    toast(error?.message || "Record could not be created", "error");
  }
}

async function _vehicleSaleFinishEditing() {
  clearTimeout(_vehicleSaleSaveTimer);
  if ($("vehicle-sales-save-state")?.dataset.state === "pending") {
    try { await _vehicleSaleQueueSave({ immediate: true }); } catch (_) { return; }
  } else {
    try { await _vehicleSaleSaveQueue; } catch (_) { return; }
  }
  $("vehicle-sales-editor").hidden = true;
  $("vehicle-sales-list").hidden = false;
  _vehicleSaleActive = null;
  _vehicleSaleRenderList();
}

function _vehicleSaleWire() {
  if (_vehicleSalesWired) return;
  _vehicleSalesWired = true;
  $("vehicle-sales-new")?.addEventListener("click", _vehicleSaleNew);
  $("vehicle-sales-refresh")?.addEventListener("click", _vehicleSaleLoad);
  $("vehicle-sales-search")?.addEventListener("input", _vehicleSaleRenderList);
  $("vehicle-sales-done")?.addEventListener("click", _vehicleSaleFinishEditing);
  $("vehicle-sales-form")?.addEventListener("input", event => {
    _vehicleSaleRefreshPurchaseState();
    _vehicleSaleQueueSave();
    if (["vin", "purchased_from", "vehicle_unit_number"].includes(event.target.dataset.saleField)) {
      _vehicleSaleScheduleMatch();
    }
  });
  $("vehicle-sales-form")?.addEventListener("change", event => {
    _vehicleSaleRefreshPurchaseState();
    _vehicleSaleQueueSave();
    if (["vin", "purchased_from", "vehicle_unit_number"].includes(event.target.dataset.saleField)) {
      _vehicleSaleScheduleMatch();
    }
  });
  const purchasedFrom = $("vehicle-sales-purchased-from");
  const purchasedFromSuggestions = $("vehicle-sales-purchased-from-suggestions");
  if (purchasedFrom && purchasedFromSuggestions) {
    _ptWireAgencySearch(
      purchasedFrom,
      $("vehicle-sales-purchased-from-agency-id"),
      purchasedFromSuggestions,
      () => {
        _vehicleSaleQueueSave();
        _vehicleSaleScheduleMatch();
      },
    );
    document.addEventListener("click", event => {
      if (!event.target.closest("#vehicle-sales-purchased-from") && !event.target.closest("#vehicle-sales-purchased-from-suggestions")) {
        purchasedFromSuggestions.style.display = "none";
      }
    });
  }
  $("vehicle-sales-open-pdf")?.addEventListener("click", async () => {
    if (!_vehicleSaleActive) return;
    try {
      await _vehicleSaleEnsureSaved();
      const result = await api("/api/vehicle-sales/open-pdf", { record_id: _vehicleSaleActive.record_id });
      if (!result?.ok) toast(result?.error || "PDF could not be opened", "error");
    } catch (error) {
      toast(error?.message || "PDF could not be opened", "error");
    }
  });
  $("vehicle-sales-print-pdf")?.addEventListener("click", async event => {
    if (!_vehicleSaleActive) return;
    if (!window.confirm("Print the current Vehicle Buyback / Sale PDF to this computer's default printer?")) return;
    const button = event.currentTarget;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Printing…";
    try {
      await _vehicleSaleEnsureSaved();
      const result = await api("/api/vehicle-sales/print-pdf", { record_id: _vehicleSaleActive.record_id });
      if (!result?.ok) throw new Error(result?.error || "PDF could not be printed");
      toast(result.message || "PDF sent to the default printer", "success");
    } catch (error) {
      toast(error?.message || "PDF could not be printed", "error");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });
  $("vehicle-sales-open-folder")?.addEventListener("click", async () => {
    if (!_vehicleSaleActive) return;
    const year = _vehicleSaleActive.record_year || String(new Date().getFullYear());
    try {
      const result = await api("/api/build/show-folder", {
        library_target: "company",
        folder_path: `Vehicle Buyback Sales/${year}`,
      });
      if (!result?.ok) toast(result?.error || "SharePoint folder could not be opened", "error");
    } catch (error) {
      toast(error?.message || "SharePoint folder could not be opened", "error");
    }
  });
  $("vehicle-sales-delete")?.addEventListener("click", _vehicleSaleOpenDeleteModal);
  $("vehicle-sales-delete-cancel")?.addEventListener("click", _vehicleSaleCloseDeleteModal);
  $("vehicle-sales-delete-confirm")?.addEventListener("click", _vehicleSaleDeleteConfirmed);
  $("vehicle-sales-delete-modal")?.addEventListener("click", event => {
    if (event.target === event.currentTarget) _vehicleSaleCloseDeleteModal();
  });
}

window.initVehicleSalesTab = async function () {
  _vehicleSaleWire();
  // Preserve an editor that was prepared by a vehicle-card action before the
  // tab switch. Resetting it here caused a visible list-to-form resize flash.
  if (!_vehicleSaleActive) {
    $("vehicle-sales-editor").hidden = true;
    $("vehicle-sales-list").hidden = false;
  }
  await _vehicleSaleLoad();
};

window.PT_openVehicleSale = async function (projectId, unitId, individualId) {
  if (!appHasCapability("projects.edit")) {
    appPermissionDenied("manage vehicle buyback and sale records");
    return;
  }
  try {
    const result = await api("/api/vehicle-sales/from-vehicle", {
      project_id: projectId,
      unit_id: unitId,
      individual_id: individualId,
    });
    if (!result?.ok) throw new Error(result?.error || "Vehicle record could not be opened");
    const index = _vehicleSaleRecords.findIndex(item => item.record_id === result.record.record_id);
    if (index >= 0) _vehicleSaleRecords[index] = result.record;
    else _vehicleSaleRecords.unshift(result.record);
    _vehicleSaleOpenEditor(result.record);
    switchTab("vehicle-sales");
  } catch (error) {
    toast(error?.message || "Vehicle record could not be opened", "error");
  }
};

