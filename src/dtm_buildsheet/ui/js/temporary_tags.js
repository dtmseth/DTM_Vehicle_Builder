// ── PDF Forms: temporary yard vehicle tags ─────────────────────────────────

let _temporaryTagsInitialized = false;
let _temporaryTagsWired = false;
let _temporaryTagCandidates = [];
let _temporaryTagBatches = [];
let _temporaryTagActive = null;
let _temporaryTagSelectedCandidates = new Set();
let _temporaryTagPendingAction = null;

function _temporaryTagId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, character => {
    const value = Math.random() * 16 | 0;
    return (character === "x" ? value : (value & 3 | 8)).toString(16);
  });
}

function _temporaryTagCandidateKey(record) {
  return `${record.source_type || "record"}:${record.source_id || ""}`;
}

function _temporaryTagAttr(value) {
  return esc(value).replace(/"/g, "&quot;");
}

function _temporaryTagFormatDate(value) {
  const raw = String(value || "").trim();
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return `${iso[2]}/${iso[3]}/${iso[1].slice(-2)}`;
  const digits = raw.replace(/\D/g, "");
  if (digits.length >= 8 && /^(?:19|20)/.test(digits)) {
    return `${digits.slice(4, 6)}/${digits.slice(6, 8)}/${digits.slice(2, 4)}`;
  }
  if (digits.length >= 8) return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(6, 8)}`;
  const short = digits.slice(0, 6);
  if (short.length <= 2) return short;
  if (short.length <= 4) return `${short.slice(0, 2)}/${short.slice(2)}`;
  return `${short.slice(0, 2)}/${short.slice(2, 4)}/${short.slice(4)}`;
}

function _temporaryTagDateIsValid(value) {
  const match = String(value || "").match(/^(\d{2})\/(\d{2})\/(\d{2})$/);
  if (!match) return false;
  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = 2000 + Number(match[3]);
  const parsed = new Date(year, month - 1, day);
  return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day;
}

function _temporaryTagsResizeAgencyField(control) {
  if (!control) return;
  control.style.height = "auto";
  const height = Math.min(Math.max(control.scrollHeight, 34), 92);
  control.style.height = `${height}px`;
  control.style.overflowY = control.scrollHeight > 92 ? "auto" : "hidden";
}

function _temporaryTagLabel(record, fallback = "Vehicle") {
  const vehicle = record.vehicle_summary || fallback;
  const unit = record.unit_number ? ` · Unit ${record.unit_number}` : "";
  const vin = record.vin ? ` · VIN …${String(record.vin).slice(-4)}` : "";
  return `${vehicle}${unit}${vin}`;
}

function _temporaryTagsSetStatus(text, state = "") {
  const host = $("temporary-tags-save-state");
  if (!host) return;
  host.textContent = text;
  host.dataset.state = state;
}

function _temporaryTagsValidation() {
  const warnings = [];
  (_temporaryTagActive?.items || []).forEach((item, index) => {
    const missing = [];
    if (!String(item.agency || "").trim()) missing.push("agency");
    const vin = String(item.vin || "").replace(/[^A-Za-z0-9]/g, "");
    if (!vin || vin.length < 4) missing.push("vin");
    if (!String(item.quote_number || "").trim()) missing.push("quote_number");
    if (!_temporaryTagDateIsValid(item.date_received)) missing.push("date_received");
    if (missing.length) warnings.push({
      item_id: item.item_id,
      label: _temporaryTagLabel(item, `Tag ${index + 1}`),
      missing,
    });
  });
  return {complete: Boolean(_temporaryTagActive?.items?.length) && !warnings.length, warnings};
}

function _temporaryTagsApplyValidation() {
  const validation = _temporaryTagsValidation();
  const banner = $("temporary-tags-warning");
  const labelByField = {
    agency: "Agency",
    vin: "VIN",
    quote_number: "Quote number",
    date_received: "Date received",
  };
  document.querySelectorAll("[data-temporary-tag-item]").forEach(row => {
    const warning = validation.warnings.find(item => item.item_id === row.dataset.temporaryTagItem);
    row.classList.toggle("temporary-tags-item--warning", Boolean(warning));
    row.querySelectorAll("[data-temporary-tag-field]").forEach(input => {
      input.classList.toggle("field-missing", Boolean(warning?.missing.includes(input.dataset.temporaryTagField)));
    });
    const chip = row.querySelector("[data-temporary-tag-missing]");
    if (chip) {
      chip.hidden = !warning;
      chip.textContent = warning
        ? `Missing: ${warning.missing.map(field => labelByField[field]).join(", ")}`
        : "";
    }
  });
  if (!_temporaryTagActive?.items?.length) {
    banner.hidden = true;
  } else if (validation.warnings.length) {
    const fieldCount = validation.warnings.reduce((total, warning) => total + warning.missing.length, 0);
    banner.hidden = false;
    banner.innerHTML = `<strong>${validation.warnings.length} tag${validation.warnings.length === 1 ? "" : "s"} need attention.</strong> ${fieldCount} required field${fieldCount === 1 ? " is" : "s are"} missing. You can save now; opening or printing will ask for confirmation.`;
  } else {
    banner.hidden = true;
  }
  return validation;
}

function _temporaryTagsRenderCandidates() {
  const host = $("temporary-tags-candidates");
  if (!host) return;
  const query = String($("temporary-tags-search")?.value || "").trim().toLowerCase();
  const visible = _temporaryTagCandidates.filter(record => {
    if (!query) return true;
    return [
      record.agency, record.vin, record.quote_number, record.date_received,
      record.vehicle_summary, record.unit_number, record.source_label,
    ].join(" ").toLowerCase().includes(query);
  });
  if (!visible.length) {
    host.innerHTML = `<p class="temporary-tags-candidate-empty">${query ? "No vehicles match this search." : "No saved vehicles are available yet."}</p>`;
    return;
  }
  host.innerHTML = visible.map(record => {
    const key = _temporaryTagCandidateKey(record);
    const details = [
      record.agency || "Agency missing",
      record.quote_number ? `Quote ${record.quote_number}` : "Quote missing",
      record.date_received || "Received date missing",
    ].join(" · ");
    return `<label class="temporary-tags-candidate">
      <input type="checkbox" data-temporary-tag-candidate="${_temporaryTagAttr(key)}"${_temporaryTagSelectedCandidates.has(key) ? " checked" : ""}>
      <span><strong>${esc(_temporaryTagLabel(record))}</strong><small>${esc(details)}</small></span>
      <em>${esc(record.source_label || "Saved vehicle")}</em>
    </label>`;
  }).join("");
}

function _temporaryTagsRenderBatches() {
  const select = $("temporary-tags-saved");
  if (!select) return;
  select.innerHTML = [
    `<option value="">New unsaved batch</option>`,
    ..._temporaryTagBatches.map(batch => {
      const count = batch.items?.length || 0;
      return `<option value="${_temporaryTagAttr(batch.batch_id)}">${esc(batch.name || "Temporary Tags")} · ${count} sheet${count === 1 ? "" : "s"}</option>`;
    }),
  ].join("");
  select.value = _temporaryTagActive?.batch_id && _temporaryTagBatches.some(
    batch => batch.batch_id === _temporaryTagActive.batch_id,
  ) ? _temporaryTagActive.batch_id : "";
}

function _temporaryTagsRenderItems() {
  const host = $("temporary-tags-items");
  const empty = $("temporary-tags-empty");
  const count = _temporaryTagActive?.items?.length || 0;
  if ($("temporary-tags-count")) $("temporary-tags-count").textContent = `${count} sheet${count === 1 ? "" : "s"}`;
  if ($("temporary-tags-name")) $("temporary-tags-name").value = _temporaryTagActive?.name || "";
  if (empty) empty.hidden = count > 0;
  if (!host) return;
  host.innerHTML = (_temporaryTagActive?.items || []).map((item, index) => `<article class="temporary-tags-item" data-temporary-tag-item="${_temporaryTagAttr(item.item_id)}">
    <div class="temporary-tags-item-heading">
      <div><strong>Sheet ${index + 1}</strong><span>${esc(_temporaryTagLabel(item, item.source_type === "manual" ? "Manual tag" : "Vehicle tag"))}</span></div>
      <button class="btn btn-secondary btn-sm" type="button" data-temporary-tag-remove="${_temporaryTagAttr(item.item_id)}">Remove</button>
    </div>
    <div class="temporary-tags-item-grid">
      <label>Agency<textarea data-temporary-tag-field="agency" maxlength="200" rows="1" placeholder="Agency name">${esc(item.agency || "")}</textarea></label>
      <label>VIN<input data-temporary-tag-field="vin" maxlength="17" value="${_temporaryTagAttr(item.vin || "")}" placeholder="Full VIN or at least last 4"></label>
      <label>Quote #<input data-temporary-tag-field="quote_number" maxlength="80" value="${_temporaryTagAttr(item.quote_number || "")}" placeholder="Quote number"></label>
      <label>Date received<input data-temporary-tag-field="date_received" type="text" inputmode="numeric" maxlength="8" value="${_temporaryTagAttr(_temporaryTagFormatDate(item.date_received))}" placeholder="MM/DD/YY" aria-label="Date received in MM/DD/YY format"></label>
    </div>
    <div class="temporary-tags-item-footer"><small>${esc(item.source_label || "Manual entry")}</small><span data-temporary-tag-missing hidden></span></div>
  </article>`).join("");
  host.querySelectorAll('textarea[data-temporary-tag-field="agency"]').forEach(_temporaryTagsResizeAgencyField);
  _temporaryTagsApplyValidation();
}

function _temporaryTagsUseBatch(record) {
  _temporaryTagActive = JSON.parse(JSON.stringify(record));
  _temporaryTagsRenderBatches();
  _temporaryTagsRenderItems();
  _temporaryTagsSetStatus(_temporaryTagBatches.some(batch => batch.batch_id === record.batch_id) ? "Saved" : "Not saved");
}

async function _temporaryTagsNew() {
  try {
    const result = await api("/api/temporary-tags/new", {});
    if (!result?.ok) throw new Error(result?.error || "A new batch could not be created");
    _temporaryTagSelectedCandidates.clear();
    _temporaryTagsRenderCandidates();
    _temporaryTagsUseBatch(result.record);
  } catch (error) {
    toast(error?.message || "A new tag batch could not be created", "error");
  }
}

function _temporaryTagsAddSelected() {
  if (!_temporaryTagActive) return;
  const alreadyAdded = new Set((_temporaryTagActive.items || []).map(item => _temporaryTagCandidateKey(item)));
  let added = 0;
  _temporaryTagCandidates.forEach(candidate => {
    const key = _temporaryTagCandidateKey(candidate);
    if (!_temporaryTagSelectedCandidates.has(key) || alreadyAdded.has(key)) return;
    _temporaryTagActive.items.push({...candidate, item_id: _temporaryTagId()});
    added += 1;
  });
  _temporaryTagSelectedCandidates.clear();
  _temporaryTagsRenderCandidates();
  _temporaryTagsRenderItems();
  if (!added) toast("Select at least one vehicle that is not already in this batch", "info");
  else _temporaryTagsSetStatus("Unsaved changes", "pending");
}

function _temporaryTagsAddManual() {
  if (!_temporaryTagActive) return;
  _temporaryTagActive.items.push({
    item_id: _temporaryTagId(), source_type: "manual", source_id: "",
    source_label: "Manual entry", agency: "", vin: "", quote_number: "",
    date_received: "", vehicle_summary: "", unit_number: "",
  });
  _temporaryTagsRenderItems();
  _temporaryTagsSetStatus("Unsaved changes", "pending");
  const rows = document.querySelectorAll("[data-temporary-tag-item]");
  rows[rows.length - 1]?.querySelector("input")?.focus();
}

async function _temporaryTagsSave() {
  if (!_temporaryTagActive) return null;
  if (!(_temporaryTagActive.items || []).length) {
    toast("Add at least one vehicle before saving this batch", "error");
    return null;
  }
  _temporaryTagActive.name = String($("temporary-tags-name")?.value || "").trim();
  _temporaryTagsSetStatus("Saving…", "pending");
  const result = await api("/api/temporary-tags/save", _temporaryTagActive);
  if (!result?.ok) throw new Error(result?.error || "The tag batch could not be saved");
  _temporaryTagActive = result.record;
  const index = _temporaryTagBatches.findIndex(batch => batch.batch_id === result.record.batch_id);
  if (index >= 0) _temporaryTagBatches[index] = result.record;
  else _temporaryTagBatches.unshift(result.record);
  _temporaryTagsRenderBatches();
  _temporaryTagsRenderItems();
  _temporaryTagsSetStatus("Saved", "saved");
  return result;
}

function _temporaryTagsShowWarning(action, validation) {
  _temporaryTagPendingAction = action;
  const labels = {agency: "Agency", vin: "VIN", quote_number: "Quote number", date_received: "Date received"};
  $("temporary-tags-warning-list").innerHTML = validation.warnings.map(warning =>
    `<li><strong>${esc(warning.label)}</strong><span>${esc(warning.missing.map(field => labels[field]).join(", "))}</span></li>`,
  ).join("");
  $("temporary-tags-warning-continue").textContent = action === "print" ? "Print anyway" : "Open anyway";
  $("temporary-tags-warning-modal").classList.add("open");
}

async function _temporaryTagsRunOutput(action, allowIncomplete = false) {
  const button = action === "print" ? $("temporary-tags-print") : $("temporary-tags-open-pdf");
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = action === "print" ? "Printing…" : "Opening…";
  }
  try {
    const saved = await _temporaryTagsSave();
    if (!saved) return;
    const validation = _temporaryTagsValidation();
    if (!validation.complete && !allowIncomplete) {
      _temporaryTagsShowWarning(action, validation);
      return;
    }
    if (action === "print" && !allowIncomplete) {
      const count = _temporaryTagActive.items.length;
      if (!window.confirm(`Print ${count} temporary tag sheet${count === 1 ? "" : "s"} to this computer's default printer?`)) return;
    }
    const result = await api(`/api/temporary-tags/${action === "print" ? "print-pdf" : "open-pdf"}`, {
      batch_id: _temporaryTagActive.batch_id,
      allow_incomplete: allowIncomplete,
    });
    if (!result?.ok) throw new Error(result?.error || `The tag PDF could not be ${action === "print" ? "printed" : "opened"}`);
    if (action === "print") toast(result.message || "Temporary tags sent to the default printer", "success");
  } catch (error) {
    toast(error?.message || "The temporary tag PDF could not be prepared", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function _temporaryTagsLoad({refreshCandidates = true} = {}) {
  try {
    const requests = [api("/api/temporary-tags")];
    if (refreshCandidates) requests.push(api("/api/temporary-tags/candidates"));
    const [batches, candidates] = await Promise.all(requests);
    if (!batches?.ok) throw new Error(batches?.error || "Saved tag batches could not be loaded");
    _temporaryTagBatches = batches.records || [];
    if (candidates) {
      if (!candidates?.ok) throw new Error(candidates?.error || "Vehicle choices could not be loaded");
      _temporaryTagCandidates = candidates.records || [];
    }
    _temporaryTagsRenderCandidates();
    if (!_temporaryTagActive) await _temporaryTagsNew();
    else _temporaryTagsRenderBatches();
  } catch (error) {
    toast(error?.message || "Temporary tag forms could not be loaded", "error");
  }
}

function _temporaryTagsWire() {
  if (_temporaryTagsWired) return;
  _temporaryTagsWired = true;
  $("temporary-tags-new")?.addEventListener("click", _temporaryTagsNew);
  $("temporary-tags-refresh")?.addEventListener("click", async event => {
    event.currentTarget.disabled = true;
    try { await _temporaryTagsLoad({refreshCandidates: true}); }
    finally { event.currentTarget.disabled = false; }
  });
  $("temporary-tags-search")?.addEventListener("input", _temporaryTagsRenderCandidates);
  $("temporary-tags-candidates")?.addEventListener("change", event => {
    const key = event.target.dataset.temporaryTagCandidate;
    if (!key) return;
    if (event.target.checked) _temporaryTagSelectedCandidates.add(key);
    else _temporaryTagSelectedCandidates.delete(key);
  });
  $("temporary-tags-add-selected")?.addEventListener("click", _temporaryTagsAddSelected);
  $("temporary-tags-add-manual")?.addEventListener("click", _temporaryTagsAddManual);
  $("temporary-tags-saved")?.addEventListener("change", async event => {
    const record = _temporaryTagBatches.find(batch => batch.batch_id === event.target.value);
    if (record) _temporaryTagsUseBatch(record);
    else await _temporaryTagsNew();
  });
  $("temporary-tags-name")?.addEventListener("input", event => {
    if (!_temporaryTagActive) return;
    _temporaryTagActive.name = event.target.value;
    _temporaryTagsSetStatus("Unsaved changes", "pending");
  });
  $("temporary-tags-items")?.addEventListener("input", event => {
    const field = event.target.dataset.temporaryTagField;
    const row = event.target.closest("[data-temporary-tag-item]");
    if (!field || !row || !_temporaryTagActive) return;
    const item = _temporaryTagActive.items.find(record => record.item_id === row.dataset.temporaryTagItem);
    if (!item) return;
    item[field] = field === "vin"
      ? String(event.target.value || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 17)
      : field === "date_received" ? _temporaryTagFormatDate(event.target.value) : event.target.value;
    if (field === "vin" || field === "date_received") event.target.value = item[field];
    if (field === "agency") _temporaryTagsResizeAgencyField(event.target);
    _temporaryTagsApplyValidation();
    _temporaryTagsSetStatus("Unsaved changes", "pending");
  });
  $("temporary-tags-items")?.addEventListener("click", event => {
    const itemId = event.target.dataset.temporaryTagRemove;
    if (!itemId || !_temporaryTagActive) return;
    _temporaryTagActive.items = _temporaryTagActive.items.filter(item => item.item_id !== itemId);
    _temporaryTagsRenderItems();
    _temporaryTagsSetStatus("Unsaved changes", "pending");
  });
  $("temporary-tags-save")?.addEventListener("click", async () => {
    try { if (await _temporaryTagsSave()) toast("Temporary tag batch saved", "success"); }
    catch (error) { toast(error?.message || "The tag batch could not be saved", "error"); }
  });
  $("temporary-tags-open-pdf")?.addEventListener("click", () => _temporaryTagsRunOutput("open"));
  $("temporary-tags-print")?.addEventListener("click", () => _temporaryTagsRunOutput("print"));
  $("temporary-tags-warning-cancel")?.addEventListener("click", () => {
    $("temporary-tags-warning-modal").classList.remove("open");
    _temporaryTagPendingAction = null;
  });
  $("temporary-tags-warning-continue")?.addEventListener("click", () => {
    const action = _temporaryTagPendingAction;
    $("temporary-tags-warning-modal").classList.remove("open");
    _temporaryTagPendingAction = null;
    if (action) _temporaryTagsRunOutput(action, true);
  });
}

async function initTemporaryTagsTab() {
  _temporaryTagsWire();
  if (_temporaryTagsInitialized) return;
  _temporaryTagsInitialized = true;
  await _temporaryTagsLoad({refreshCandidates: true});
}

window.initTemporaryTagsTab = initTemporaryTagsTab;
