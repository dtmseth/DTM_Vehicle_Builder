// Price List Converter — vendor price-list normalization and Shopmonkey reconciliation.
(function () {
  "use strict";

  const EXPORT_ROW_LIMIT = 10000;
  const FIELD_LABELS = {
    sku: "SKU / part number", description: "Description", cost: "Cost",
    msrp: "MSRP", agency_price: "Custom price column",
    retail: "Our retail", brand: "Brand",
    vendor: "Vendor", effective_date: "Effective date", unit: "Unit of measure",
    shopmonkey_id: "Shopmonkey ID",
  };
  const STEPS = ["Choose file", "Assign columns", "Rules & baseline", "Match parts", "Review & export", "Finish"];
  const state = {
    initialized: false, loading: false, tab: "lists", mode: "workspace", step: 1, reviewPage: 1,
    summary: null, rules: [], presets: [], review: null, reviewFilter: "", reviewBulkLoading: false,
    sessionId: "", runId: "", candidates: [], candidateId: "", mapping: {},
    filename: "", vendor: "", vendorAutoDetected: false, effectiveDate: "", includeNotes: true,
    sourceFile: null, parsing: false, matching: false, artifact: null, ruleEditor: false, exceptionEditor: false, editingRule: null, ruleGroup: "", exceptionGroup: "", search: "", markedImported: false,
    baselineModal: false, baselineModalReason: "", snapshotUploading: false, snapshotUploadFilename: "",
    inventoryView: "export", coverage: null, coveragePage: 1, coverageSearch: "", coverageBrand: "", coverageLoading: false,
    bulkExporting: false, bulkExportMode: "",
    rulePreview: null, rulePreviewLoading: false, ruleExampleSearch: "", ruleEditModal: false, ruleChangeModal: false,
    presetApplied: false, presetName: "", mappingChanged: false, savePreset: false, importConfirm: null,
    scopeOptions: {brands: [], vendors: [], updated_at: "", connected: false}, scopeRefreshAt: 0,
  };
  let ruleExampleSearchTimer = 0;
  let rulePreviewRequestId = 0;

  const escHtml = value => String(value ?? "").replace(/[&<>'"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[c]);
  const count = value => Number(value || 0).toLocaleString("en-US");
  const money = value => value === "" || value == null ? "—" : `$${Number(value).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const dateLabel = value => {
    if (!value) return "Not provided";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? escHtml(value) : parsed.toLocaleDateString("en-US", {year: "numeric", month: "short", day: "numeric"});
  };
  const importDateLabel = value => {
    if (!value) return "Not imported";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? escHtml(value) : parsed.toLocaleString("en-US", {year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  };
  function snapshotFreshness(snapshot, now = Date.now()) {
    const importedAt = Date.parse(snapshot?.created_at || "");
    if (!Number.isFinite(importedAt)) return "stale";
    const ageHours = Math.max(0, Number(now) - importedAt) / 3600000;
    if (ageHours > 48) return "stale";
    if (ageHours > 12) return "aging";
    return "current";
  }
  const can = capability => typeof appHasCapability !== "function" || appHasCapability(capability);

  function splitExportRows(totalRows, rowLimit = EXPORT_ROW_LIMIT) {
    const total = Number(totalRows); const limit = Number(rowLimit);
    if (!Number.isInteger(total) || total < 0) throw new Error("totalRows must be a non-negative integer");
    if (!Number.isInteger(limit) || limit < 1) throw new Error("rowLimit must be a positive integer");
    const chunks = [];
    for (let start = 1; start <= total; start += limit) {
      chunks.push({start, end: Math.min(start + limit - 1, total), rows: Math.min(limit, total - start + 1)});
    }
    return chunks;
  }

  function buildExportPackage(totalRows, exportDate = new Date().toISOString().slice(0, 10)) {
    const chunks = splitExportRows(totalRows);
    const files = chunks.map((chunk, index) => ({
      ...chunk,
      name: chunks.length > 1 ? `shopmonkey-pricing-import-${String(index + 1).padStart(2, "0")}.xlsx` : "shopmonkey-pricing-import.xlsx",
    }));
    return {isSplit: files.length > 1, name: files.length > 1 ? `shopmonkey-pricing-import-${exportDate}.zip` : (files[0]?.name || "shopmonkey-pricing-import.xlsx"), files};
  }

  function notify(message, type = "info") { if (typeof toast === "function") toast(message, type); }
  function detail(response, fallback) { return response?.detail || response?.error || fallback; }
  async function call(path, body) {
    const response = await api(path, body);
    if (!response?.ok) throw new Error(detail(response, "Price List Converter could not complete that action."));
    return response;
  }
  async function fileBase64(file) {
    if (!file) throw new Error("Choose a file first.");
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("The file could not be read."));
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.readAsDataURL(file);
    });
  }

  async function loadData() {
    state.loading = true; render();
    try {
      const [summary, rules, presets, scopeOptions] = await Promise.all([
        call("/api/pricing/summary"), call("/api/pricing/rules"), call("/api/pricing/presets"), call("/api/pricing/scope-options"),
      ]);
      state.summary = summary; state.rules = rules.rules || []; state.presets = presets.presets || []; state.scopeOptions = scopeOptions;
      if (!state.runId && summary.latest_run?.id) state.runId = summary.latest_run.id;
      if (state.runId) await loadReview();
    } catch (error) { notify(error.message, "error"); }
    finally { state.loading = false; render(); refreshScopeOptions(); }
  }
  async function refreshScopeOptions() {
    const now = Date.now(); if (now - state.scopeRefreshAt < 300000) return; state.scopeRefreshAt = now;
    try {
      state.scopeOptions = await call("/api/pricing/scope-options/refresh");
      if (!state.ruleEditor && !state.exceptionEditor && state.tab === "rules") render();
    } catch (_error) { /* Cached choices remain available when Shopmonkey is offline. */ }
  }
  async function loadReview(filter = state.reviewFilter) {
    if (!state.runId) { state.review = null; return; }
    if ((filter || "") !== state.reviewFilter) state.reviewPage = 1;
    state.reviewFilter = filter || "";
    state.review = await call("/api/pricing/review", {run_id: state.runId, status: state.reviewFilter, search: state.search, page: state.reviewPage, page_size: 20});
    state.sessionId = state.review.session_id || state.sessionId;
  }
  async function loadCoverage() {
    state.coverageLoading = true; render();
    try {
      state.coverage = await call("/api/pricing/inventory/coverage", {
        search: state.coverageSearch, brand: state.coverageBrand,
        page: state.coveragePage, page_size: 20,
      });
    } finally { state.coverageLoading = false; render(); }
  }

  function header() {
    const snapshot = state.summary?.snapshot;
    const freshness = snapshotFreshness(snapshot);
    return `<header class="pricing-main-header"><div><div class="pricing-kicker">Price List Converter</div><h2>Vendor pricing</h2><p>${snapshot ? `<span class="pricing-data-dot pricing-data-dot-${freshness}" aria-hidden="true"></span> Shopmonkey parts: Last Import - ${importDateLabel(snapshot.created_at)}` : "Upload a full Shopmonkey export before creating updates."}</p></div></header>`;
  }
  function tabs() {
    const items = [["lists", "Vendor Price Lists"], ["rules", "Pricing Rules"], ["inventory", "Shopmonkey Inventory"]];
    return `<nav class="pricing-inner-tabs" aria-label="Price List Converter sections">${items.map(([id, label]) => `<button type="button" data-pricing-tab="${id}" class="${state.tab === id ? "active" : ""}" aria-current="${state.tab === id ? "page" : "false"}">${label}</button>`).join("")}</nav>`;
  }
  function empty(title, text) { return `<div class="pricing-empty-state"><strong>${escHtml(title)}</strong><p>${escHtml(text)}</p></div>`; }

  function statusCards() {
    const counts = state.review?.counts || {}; const hasRun = Boolean(state.runId && state.review);
    const cards = [
      ["Ready to export", state.review?.selected_count || 0, "Selected price changes", "updated", "open-final-review"],
      ["Needs review", counts.needs_review || 0, "Missing rules or uncertain matches", "needs_review", "open-review"],
      ["Already current", counts.unchanged || 0, "No import needed", "unchanged", "open-review"],
    ];
    return `<div class="pricing-status-summary" aria-label="Latest pricing review">${cards.map(([label, value, note, filter, action]) => hasRun && value > 0
      ? `<button type="button" data-pricing-action="${action}" data-review-filter="${filter}"><span>${label}</span><strong>${count(value)}</strong><small>${note}</small></button>`
      : `<div><span>${label}</span><strong>${count(value)}</strong><small>${hasRun ? note : "No completed review"}</small></div>`).join("")}</div>`;
  }
  function vendorLists() {
    const sessions = state.summary?.sessions || [];
    const stats = state.summary?.price_list_stats || {};
    const exportable = sessions.filter(session => session.can_export).length;
    const exportedCount = sessions.filter(session => session.run_status === "exported").length;
    const needsRematch = sessions.filter(session => session.needs_rematch);
    const statusLabel = session => {
      if (session.needs_rematch) return "Needs rematching";
      if (session.can_export) return ({ready: "Ready to export", exported: "Exported", imported: "Imported into Shopmonkey", imported_unverified: "Imported", verified: "Verified", api_applied: "API update complete"})[session.run_status] || "Ready to export";
      if (session.run_id) return "Review in progress";
      return session.status === "mapped" ? "Ready to match" : "Assign columns";
    };
    const ruleCell = session => {
      const matched = (session.applied_rule_ids || []).map(id => state.rules.find(rule => rule.id === id)).filter(Boolean);
      if (!matched.length) return `<span class="pricing-list-rule-missing">No matching rule</span>`;
      if (matched.length > 1) return `<span class="pricing-list-rule"><strong>${count(matched.length)} applied rules</strong><small>${matched.map(rule => escHtml(rule.name)).join(", ")}</small></span>`;
      return `<span class="pricing-list-rule"><strong>${escHtml(matched[0].name)}</strong><small>${escHtml(ruleLabel(matched[0]))}</small></span>`;
    };
    const bulkReady = exportable && !needsRematch.length;
    const rematchNames = needsRematch.slice(0, 3).map(session => session.vendor || session.filename).join(", ");
    return `<section class="pricing-panel"><div class="pricing-panel-head"><div><h3>Vendor Price Lists</h3><p>Import, review, and export every vendor price list from one place.</p></div>${can("pricing.import") ? `<button class="btn btn-primary" data-pricing-action="start-import" type="button">Import price list</button>` : ""}</div>
      <div class="pricing-list-stats"><div><span>Price lists</span><strong>${count(stats.price_list_count || 0)}</strong><small>With confirmed columns</small></div><div><span>Total parts</span><strong>${count(stats.total_parts || 0)}</strong><small>Across every price list</small></div><div><span>Unique parts</span><strong>${count(stats.unique_parts || 0)}</strong><small>Vendor + SKU</small></div><div><span>Ready lists</span><strong>${count(exportable)}</strong><small>Reviewed and current</small></div></div>
      <div class="pricing-bulk-export ${needsRematch.length ? "has-rematch-warning" : ""}"><div><strong>${needsRematch.length ? `${count(needsRematch.length)} price list${needsRematch.length === 1 ? " needs" : "s need"} rematching` : state.bulkExporting ? "Preparing bulk export" : "Bulk Shopmonkey export"}</strong><small>${needsRematch.length ? `${escHtml(rematchNames)}${needsRematch.length > 3 ? ` and ${count(needsRematch.length - 3)} more` : ""} must be reviewed against the current Shopmonkey import.` : state.bulkExporting ? "Building the Shopmonkey files. Keep this window open." : "Combine all finalized price lists into one package."}</small></div><div>${needsRematch.length ? `<button class="btn btn-secondary" type="button" data-pricing-action="continue-import" data-session-id="${escHtml(needsRematch[0].id)}">Review ${escHtml(needsRematch[0].vendor || "price list")}</button>` : ""}<button class="btn btn-secondary" type="button" data-pricing-action="bulk-export" data-export-mode="all" ${bulkReady && !state.bulkExporting ? "" : "disabled"}>${state.bulkExporting && state.bulkExportMode === "all" ? `<i class="pricing-spinner pricing-spinner-small" aria-hidden="true"></i> Preparing…` : "Export all parts"}</button><button class="btn btn-primary" type="button" data-pricing-action="bulk-export" data-export-mode="changed" ${bulkReady && !state.bulkExporting ? "" : "disabled"}>${state.bulkExporting && state.bulkExportMode === "changed" ? `<i class="pricing-spinner pricing-spinner-small" aria-hidden="true"></i> Preparing…` : "Export changed parts"}</button>${exportedCount ? `<button class="btn btn-secondary" type="button" data-pricing-action="confirm-import-all-open" data-list-count="${exportedCount}">Mark all as imported</button>` : ""}</div></div>
      ${sessions.length ? `<div class="pricing-table-wrap"><table class="pricing-data-table pricing-vendor-list-table"><thead><tr><th>Vendor price list</th><th>Effective date</th><th>Imported</th><th>Source file</th><th>Applied rule</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>${sessions.map(session => `<tr><th scope="row">${escHtml(session.vendor || "Unassigned")}</th><td>${dateLabel(session.effective_date)}</td><td>${importDateLabel(session.created_at)}</td><td class="pricing-source-filename">${escHtml(session.filename)}</td><td>${ruleCell(session)}</td><td><span class="pricing-status-pill pricing-status-${session.can_export ? "mapped" : "review"}">${escHtml(statusLabel(session))}</span></td><td><details class="pricing-rule-menu pricing-list-menu"><summary aria-label="Actions for ${escHtml(session.vendor || session.filename)}">•••</summary><div>${session.can_export ? `<button type="button" data-pricing-action="export-list" data-session-id="${session.id}" data-run-id="${session.run_id}" data-download-url="${escHtml(session.download_url || "")}" data-filename="${escHtml(session.artifact_filename || "")}">Export</button>${session.run_status === "exported" ? `<button type="button" data-pricing-action="confirm-import-open" data-run-id="${session.run_id}" data-filename="${escHtml(session.artifact_filename || session.filename)}">Confirm imported</button>` : ""}<button type="button" data-pricing-action="edit-list-rule" data-rule-id="${escHtml(session.applied_rule_ids?.[0] || "")}" data-rule-group="${escHtml(session.vendor || "")}" data-session-id="${session.id}" data-run-id="${session.run_id}">Edit rule</button>` : `<button type="button" data-pricing-action="continue-import" data-session-id="${session.id}">Continue import</button>`}<button class="pricing-danger-text" type="button" data-pricing-action="delete-import" data-session-id="${session.id}" data-session-name="${escHtml(session.vendor || session.filename)}">Delete</button></div></details></td></tr>`).join("")}</tbody></table></div>` : empty("No vendor price lists yet", "Import a vendor price list to assign its columns, apply a pricing rule, and review its parts.")}
    </section>`;
  }

  function ruleLabel(rule) {
    const amount = Number(rule.amount || 0).toLocaleString("en-US", {maximumFractionDigits: 2});
    const source = {msrp: "MSRP", agency_price: "custom vendor price", cost: "cost"}[rule.source_field] || "custom vendor price";
    if (rule.method === "markup_percent_cost") return `${amount}% markup from cost`;
    if (rule.method === "margin_percent_cost") return `${amount}% margin on cost`;
    if (rule.method === "discount_percent_msrp") return `${amount}% off MSRP`;
    if (rule.method === "flat_markup_cost") return `$${amount} markup from cost`;
    if (rule.method === "flat_discount_msrp") return `$${amount} off MSRP`;
    if (rule.method === "markup_percent_source") return `${amount}% markup from ${source}`;
    if (rule.method === "flat_markup_source") return `$${amount} markup from ${source}`;
    if (rule.method === "fixed_retail") return `Fixed $${amount}`;
    if (rule.method === "imported_value") {
      return `Use ${source}`;
    }
    return "Pricing rule";
  }
  function costRuleLabel(rule) {
    if (!rule?.cost_enabled) return "Use vendor-list cost unchanged";
    const costRule = {
      method: rule.cost_method || "imported_value", amount: rule.cost_amount || "",
      source_field: rule.cost_source_field || "cost",
    };
    let label = costRule.method === "imported_value" && costRule.source_field === "cost"
      ? "Use vendor-list cost" : ruleLabel(costRule);
    if (rule.cost_discount_enabled && Number(rule.cost_discount_percent || 0) > 0) {
      label += `, then ${Number(rule.cost_discount_percent).toLocaleString("en-US", {maximumFractionDigits: 2})}% off`;
    }
    return label;
  }
  function appliedRuleTerms(preview) {
    const rules = preview?.applied_rules || [];
    const menu = rule => `<details class="pricing-rule-menu pricing-applied-rule-menu"><summary aria-label="Rule options" title="Rule options">•••</summary><div>${rule && can("pricing.rules.manage") ? `<button type="button" data-pricing-action="edit-import-rule" data-rule-id="${escHtml(rule.id)}">Edit rule</button>` : ""}<button type="button" data-pricing-action="change-import-rule">Change rule</button></div></details>`;
    if (!rules.length) return `<div class="pricing-applied-rule-list"><article class="pricing-applied-rule-card is-empty"><header><div><span>Applied rule</span><strong>No pricing rule selected</strong><small>Imported prices will not be recalculated.</small></div>${menu(null)}</header></article></div>`;
    return `<div class="pricing-applied-rule-list">${rules.map(rule => `<article class="pricing-applied-rule-card"><header><div><span>Applied rule</span><strong>${escHtml(rule.name)}</strong><small>${escHtml(rule.scope_type)} · ${escHtml(rule.scope_value)}</small></div>${menu(rule)}</header><div><span><small>Our Cost</small><strong>${escHtml(costRuleLabel(rule))}</strong></span><span><small>Our Retail (sell)</small><strong>${escHtml(ruleLabel(rule))}</strong></span></div></article>`).join("")}</div>`;
  }
  function ruleTone(rule) {
    if (rule.method === "discount_percent_msrp" || rule.method === "flat_discount_msrp") return "discount";
    if (["markup_percent_cost", "flat_markup_cost", "markup_percent_source", "flat_markup_source"].includes(rule.method)) return "markup";
    if (rule.method === "margin_percent_cost") return "margin";
    return "other";
  }
  function scopeChoices(scopeType, query = "") {
    const rows = scopeType === "vendor" ? state.scopeOptions.vendors || [] : state.scopeOptions.brands || [];
    const needle = query.trim().toLowerCase();
    return rows.filter(row => !needle || String(row.name || "").toLowerCase().includes(needle)).slice(0, 80);
  }
  function scopePicker(scopeType, value) {
    return `<div class="pricing-scope-picker"><label><span data-pricing-scope-label>Choose ${scopeType}</span><input name="scope_value" required autocomplete="off" data-pricing-scope-search data-scope-type="${scopeType}" value="${escHtml(value)}" placeholder="Search ${scopeType}s…"></label><div class="pricing-scope-menu" role="listbox" hidden></div><small>Part counts use the current Shopmonkey inventory baseline.</small></div>`;
  }
  function renderScopeMenu(input) {
    const menu = input.closest(".pricing-scope-picker")?.querySelector(".pricing-scope-menu"); if (!menu) return;
    menu.replaceChildren(); const rows = scopeChoices(input.dataset.scopeType || "brand", input.value);
    if (!rows.length) { const emptyRow = document.createElement("div"); emptyRow.className = "pricing-scope-empty"; emptyRow.textContent = `No matching ${input.dataset.scopeType === "vendor" ? "vendors" : "brands"}`; menu.append(emptyRow); }
    for (const row of rows) {
      const button = document.createElement("button"); button.type = "button"; button.setAttribute("role", "option"); button.dataset.pricingScopeChoice = String(row.name || "");
      const name = document.createElement("span"); name.textContent = String(row.name || "");
      const total = document.createElement("small"); total.textContent = `${count(row.part_count)} ${Number(row.part_count) === 1 ? "part" : "parts"}`;
      button.append(name, total); menu.append(button);
    }
    menu.hidden = false;
  }
  function calculationState(rule) {
    const result = {source: "cost", unit: "percent", amount: rule.amount ?? "0", method: rule.method || "markup_percent_cost", sourceField: rule.source_field || "cost"};
    if (rule.method === "discount_percent_msrp") Object.assign(result, {source: "msrp", unit: "percent", sourceField: "msrp"});
    else if (rule.method === "flat_discount_msrp") Object.assign(result, {source: "msrp", unit: "dollar", sourceField: "msrp"});
    else if (rule.method === "flat_markup_cost") Object.assign(result, {source: "cost", unit: "dollar", sourceField: "cost"});
    else if (rule.method === "margin_percent_cost") Object.assign(result, {source: "cost_margin", unit: "percent", sourceField: "cost"});
    else if (["markup_percent_source", "flat_markup_source"].includes(rule.method)) Object.assign(result, {source: "custom_price", sourceField: rule.source_field || "agency_price", unit: rule.method === "flat_markup_source" ? "dollar" : "percent"});
    else if (rule.method === "imported_value") Object.assign(result, {source: rule.source_field === "agency_price" ? "custom_price" : (rule.source_field || "msrp"), sourceField: rule.source_field || "msrp", unit: "percent", amount: "0"});
    else if (rule.method === "fixed_retail") Object.assign(result, {source: "fixed_retail", unit: "dollar", sourceField: "retail"});
    return result;
  }
  function targetCalculationState(rule, target) {
    if (target === "retail") return calculationState(rule);
    return calculationState({
      method: rule.cost_method || "imported_value", amount: rule.cost_amount ?? "0",
      source_field: rule.cost_source_field || "cost",
    });
  }
  function calculationHint(source, target = "retail") {
    return {
      cost: target === "cost" ? "Adjusts the cost imported from the vendor list." : "Adds markup to Our Cost.",
      msrp: "Subtracts a discount from MSRP.",
      custom_price: "Adds markup to the custom price column assigned during vendor-list import; enter 0 to use it directly.",
      cost_margin: "Calculates margin from cost; percentage only.",
      fixed_retail: target === "cost" ? "Sets Our Cost to a fixed dollar value." : "Sets Our Retail (sell) to a fixed dollar value.",
    }[source] || "";
  }
  function calculationSourceOptions(selected, target = "retail") {
    const costLabel = target === "cost" ? "Vendor-list cost" : "Our Cost";
    const options = [["cost", costLabel], ["msrp", "MSRP"], ["custom_price", "Custom column on vendor list"]];
    if (selected === "cost_margin") options.push(["cost_margin", `${costLabel} (margin)`]);
    if (selected === "fixed_retail") options.push(["fixed_retail", target === "cost" ? "Fixed cost" : "Fixed sell price"]);
    return options.map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`).join("");
  }
  function calculationCard(target, calculation, enabled = true, options = {}) {
    const cost = target === "cost"; const field = cost ? "cost_" : "";
    const title = cost ? "Our Cost" : "Our Retail (sell)";
    const description = cost ? "Optional. Turn this off to use the vendor-list cost unchanged." : "The selling price written to Shopmonkey.";
    return `<section class="pricing-rule-target-card pricing-rule-target-${target}"><header><div><span>${cost ? "Cost pricing" : "Retail pricing"}</span><h4>${title}</h4><p>${description}</p></div>${cost ? `<label class="pricing-cost-rule-toggle"><input type="checkbox" name="cost_enabled" value="1" data-pricing-cost-enabled ${enabled ? "checked" : ""}><span>${enabled ? "On" : "Off"}</span></label>` : ""}</header><div class="pricing-rule-target-controls" data-pricing-target-controls="${target}" ${cost && !enabled ? "hidden" : ""}>
      <input type="hidden" name="${field}method" value="${escHtml(calculation.method)}"><input type="hidden" name="${field}source_field" value="${escHtml(calculation.sourceField)}">
      <label>Calculate from<select name="${field}calculation_source" data-pricing-calculation-source="${target}">${calculationSourceOptions(calculation.source, target)}</select><small data-pricing-calculation-hint="${target}">${escHtml(calculationHint(calculation.source, target))}</small></label>
      <fieldset class="pricing-unit-toggle" data-pricing-adjustment-controls="${target}"><legend>Amount type</legend><label title="Percentage"><input type="radio" name="${field}amount_unit" value="percent" ${calculation.unit === "percent" ? "checked" : ""} ${calculation.source === "fixed_retail" ? "disabled" : ""}><span aria-label="Percentage">%</span></label><label title="Dollar amount"><input type="radio" name="${field}amount_unit" value="dollar" ${calculation.unit === "dollar" ? "checked" : ""} ${calculation.source === "cost_margin" ? "disabled" : ""}><span aria-label="Dollar amount">$</span></label></fieldset>
      <label data-pricing-value-field="${target}">Value<input name="${field}amount" type="number" step="0.01" min="0" value="${escHtml(calculation.amount)}"></label>${cost ? `<div class="pricing-cost-discount"><label class="pricing-secondary-toggle"><input type="checkbox" name="cost_discount_enabled" value="1" data-pricing-cost-discount-enabled ${options.discountEnabled ? "checked" : ""}><span><strong>Additional discount</strong><small>Subtract a second percentage from the calculated Our Cost.</small></span></label><label data-pricing-cost-discount-controls ${options.discountEnabled ? "" : "hidden"}>Discount off calculated cost<div class="pricing-input-suffix"><input name="cost_discount_percent" type="number" step="0.01" min="0" max="99.99" value="${escHtml(options.discountPercent ?? "0")}"><span>%</span></div></label></div>` : ""}</div></section>`;
  }
  function ruleEditor(exception = false) {
    const prefix = exception ? "exception" : "rule";
    const existing = state.editingRule || {};
    const scopeType = existing.scope_type === "vendor" ? "vendor" : "brand";
    const retailCalculation = targetCalculationState(existing, "retail"); const costCalculation = targetCalculationState(existing, "cost");
    return `<form class="pricing-rule-editor" data-pricing-form="${prefix}"><input type="hidden" name="id" value="${escHtml(existing.id || "")}"><div class="pricing-rule-editor-head"><div><strong>${existing.id ? "Edit" : "Add"} ${exception ? "SKU exception" : "pricing rule"}</strong><span>${exception ? "This overrides only the Our Retail (sell) rule." : "Set Our Cost and Our Retail (sell) for a brand or vendor."}</span></div><button type="button" data-pricing-action="close-${prefix}" aria-label="Close">×</button></div>
      <div class="pricing-rule-identity-flow"><label>Rule name<input name="name" required value="${escHtml(existing.name || "")}" placeholder="${exception ? "Special battery pricing" : "Whelen standard pricing"}"></label>
        ${exception ? `<input type="hidden" name="scope_type" value="sku"><label>Vendor or brand group<input name="group_name" required list="pricing-rule-groups" value="${escHtml(existing.group_name || state.exceptionGroup || "")}" placeholder="PAC, REDARC, Setina…"><datalist id="pricing-rule-groups">${state.rules.filter(rule => rule.scope_type !== "sku").map(rule => `<option value="${escHtml(rule.scope_value)}"></option>`).join("")}</datalist></label><label>SKU<input name="scope_value" required value="${escHtml(existing.scope_value || "")}" placeholder="Exact SKU"></label>` : `<label>Apply to<select name="scope_type" data-pricing-scope-type><option value="brand" ${scopeType === "brand" ? "selected" : ""}>Brand</option><option value="vendor" ${scopeType === "vendor" ? "selected" : ""}>Vendor</option></select></label>${scopePicker(scopeType, existing.scope_value || state.ruleGroup || "")}`}</div>
      <div class="pricing-rule-targets">${exception ? "" : calculationCard("cost", costCalculation, Boolean(existing.cost_enabled), {discountEnabled: Boolean(existing.cost_discount_enabled), discountPercent: existing.cost_discount_percent || "0"})}${calculationCard("retail", retailCalculation, true)}</div>
      <div class="pricing-inline-actions"><button class="btn btn-secondary" type="button" data-pricing-action="close-${prefix}">Cancel</button><button class="btn btn-primary" type="submit">Save ${exception ? "exception" : "rule"}</button></div></form>`;
  }
  function ruleGroups() {
    const groups = new Map();
    const key = value => String(value || "Other").toLowerCase().replace(/[^a-z0-9]+/g, "");
    for (const rule of state.rules.filter(item => item.scope_type !== "sku")) {
      const name = rule.scope_value || rule.name;
      groups.set(key(name), {name, rule, exceptions: []});
    }
    for (const exception of state.rules.filter(item => item.scope_type === "sku")) {
      const name = exception.group_name || "Other"; const id = key(name);
      if (!groups.has(id)) groups.set(id, {name, rule: null, exceptions: []});
      groups.get(id).exceptions.push(exception);
    }
    return [...groups.values()].sort((left, right) => left.name.localeCompare(right.name));
  }
  function exceptionList(exceptions) {
    if (!exceptions.length) return `<div class="pricing-no-exceptions">No SKU exceptions in this group.</div>`;
    return `<details class="pricing-edit-exceptions"><summary><span><strong>SKU exceptions</strong><small>${count(exceptions.length)} ${exceptions.length === 1 ? "part" : "parts"}</small></span><b aria-hidden="true">⌄</b></summary><div class="pricing-table-wrap"><table class="pricing-data-table"><thead><tr><th>SKU</th><th>Name</th><th>Our Retail (sell) rule</th><th></th></tr></thead><tbody>${exceptions.map(exception => `<tr><th scope="row">${escHtml(exception.scope_value)}</th><td>${escHtml(exception.name)}</td><td>${escHtml(ruleLabel(exception))}</td><td>${can("pricing.rules.manage") ? `<button class="pricing-text-button" type="button" data-pricing-action="edit-rule" data-rule-id="${exception.id}">Edit</button><button class="pricing-text-button pricing-danger-text" type="button" data-pricing-action="delete-rule" data-rule-id="${exception.id}">Delete</button>` : ""}</td></tr>`).join("")}</tbody></table></div></details>`;
  }
  function retailExceptionsCard(groupName, exceptions) {
    return `<section class="pricing-retail-exceptions-card"><header><div><span>Retail pricing</span><h4>Our Retail (sell) SKU exceptions</h4><p>These override only the retail rule for the listed SKUs.</p></div><button class="btn btn-secondary" type="button" data-pricing-action="new-exception" data-exception-group="${escHtml(groupName)}">Add SKU exception</button></header>${exceptionList(exceptions)}</section>`;
  }
  function ruleGroup(group) {
    const rule = group.rule; const exceptions = group.exceptions.sort((left, right) => left.scope_value.localeCompare(right.scope_value));
    const editingDefault = Boolean(rule && state.ruleEditor && state.editingRule?.id === rule.id);
    const addingDefault = Boolean(!rule && state.ruleEditor && !state.editingRule && state.ruleGroup.toLowerCase() === group.name.toLowerCase());
    const editingException = Boolean(state.exceptionEditor && state.exceptionGroup.toLowerCase() === group.name.toLowerCase());
    const expanded = editingDefault || addingDefault || editingException;
    return `<article class="pricing-rule-group ${expanded ? "is-editing" : ""}" data-pricing-card-rule-id="${escHtml(rule?.id || "")}" data-pricing-card-group="${escHtml(group.name)}"><header><div class="pricing-rule-card-summary"><h4 class="pricing-rule-name">${escHtml(group.name)}</h4>${rule ? `<span class="pricing-rule-pill pricing-rule-pill-${ruleTone(rule)}"><span>Our Retail (sell)</span><strong>${escHtml(ruleLabel(rule))}</strong></span>` : `<span class="pricing-rule-pill pricing-rule-pill-empty"><span>Our Retail (sell)</span><strong>Not set</strong></span>`}<span class="pricing-exception-pill"><strong>${count(exceptions.length)}</strong> retail SKU ${exceptions.length === 1 ? "exception" : "exceptions"}</span></div><details class="pricing-rule-menu"><summary aria-label="More options for ${escHtml(group.name)}" title="More options">•••</summary><div>${rule ? `<button type="button" data-pricing-action="edit-rule" data-rule-id="${rule.id}">Edit</button><button class="pricing-danger-text" type="button" data-pricing-action="delete-rule" data-rule-id="${rule.id}">Delete</button>` : `<button type="button" data-pricing-action="new-rule" data-rule-group="${escHtml(group.name)}">Add rule</button>`}</div></details></header>
      ${expanded ? `<div class="pricing-rule-card-editor">${editingDefault || addingDefault ? `${ruleEditor(false)}${retailExceptionsCard(group.name, exceptions)}` : ruleEditor(true)}</div>` : ""}</article>`;
  }
  function rulesScreen() {
    const groups = ruleGroups();
    const newRule = state.ruleEditor && (!state.editingRule || !state.editingRule.id) && !state.ruleGroup;
    return `<section class="pricing-panel"><div class="pricing-panel-head"><div><h3>Pricing Rules</h3><p>Set Our Cost and Our Retail (sell) by vendor or brand. SKU exceptions apply only to retail.</p></div><div class="pricing-panel-actions">${can("pricing.rules.manage") ? `<button class="btn btn-primary" type="button" data-pricing-action="new-rule">Add pricing rule</button>` : ""}</div></div>${newRule ? ruleEditor(false) : ""}
      <div class="pricing-rule-groups">${groups.length ? groups.map(ruleGroup).join("") : empty("No pricing rules", "Add a brand or vendor rule before reconciling its price list.")}</div>${state.sessionId ? `<div class="pricing-inline-actions pricing-panel-return"><button class="btn btn-primary" type="button" data-pricing-action="recalculate">Return to review and recalculate</button></div>` : ""}</section>`;
  }
  function inventoryScreen() {
    const snapshot = state.summary?.snapshot;
    const coverage = state.coverage; const stats = coverage?.stats || {};
    const pages = Math.max(1, Math.ceil((coverage?.total || 0) / (coverage?.page_size || 20)));
    const coverageBody = state.coverageLoading
      ? `<div class="pricing-coverage-loading"><i class="pricing-spinner" aria-hidden="true"></i><strong>Checking price-list coverage…</strong></div>`
      : `<div class="pricing-list-stats pricing-coverage-stats"><div><span>Shopmonkey parts</span><strong>${count(stats.shopmonkey_parts || 0)}</strong><small>Current inventory export</small></div><div><span>Covered by price lists</span><strong>${count(stats.matched_parts || 0)}</strong><small>Matched vendor parts</small></div><div><span>Not in price lists</span><strong>${count(stats.unmatched_parts || 0)}</strong><small>Review below</small></div></div>
        <div class="pricing-coverage-tools"><div><label class="pricing-search"><span aria-hidden="true">⌕</span><input id="pricing-coverage-search" type="search" value="${escHtml(state.coverageSearch)}" placeholder="Search SKU, name, brand, vendor, or ID" aria-label="Search Shopmonkey parts missing from price lists"></label><label class="pricing-coverage-filter"><span>Brand</span><select id="pricing-coverage-brand"><option value="">All brands</option>${(coverage?.brands || []).map(brand => `<option value="${escHtml(brand.value)}" ${state.coverageBrand === brand.value ? "selected" : ""}>${escHtml(brand.name)} (${count(brand.count)})</option>`).join("")}</select></label></div><span>${count(coverage?.total || 0)} Shopmonkey parts not in a price list</span></div>
        ${(coverage?.rows || []).length ? `<div class="pricing-table-wrap"><table class="pricing-data-table pricing-coverage-table"><thead><tr><th>Shopmonkey part</th><th>Vendor</th><th>Brand</th><th>Cost</th><th>Our Retail</th><th>Shopmonkey ID</th><th>Reason</th></tr></thead><tbody>${coverage.rows.map(row => `<tr><th class="pricing-part-identity" scope="row"><strong>${escHtml(row.sku || "No SKU")}</strong><small>${escHtml(row.description || "No description")}</small></th><td>${escHtml(row.vendor || "—")}</td><td>${escHtml(row.brand || "—")}</td><td>${money(row.cost)}</td><td>${money(row.retail)}</td><td>${escHtml(row.shopmonkey_id || "—")}</td><td><span class="pricing-status-pill pricing-status-review">${escHtml(row.reason)}</span></td></tr>`).join("")}</tbody></table></div><div class="pricing-pagination"><button class="btn btn-secondary" type="button" data-pricing-action="coverage-prev" ${state.coveragePage <= 1 ? "disabled" : ""}>Previous</button><span>Page ${state.coveragePage} of ${pages}</span><button class="btn btn-secondary" type="button" data-pricing-action="coverage-next" ${state.coveragePage >= pages ? "disabled" : ""}>Next</button></div>` : empty(state.coverageSearch ? "No missing Shopmonkey parts match this search" : "Every Shopmonkey part is covered", state.coverageSearch ? "Clear the search to see all Shopmonkey parts missing from price lists." : "Every Shopmonkey inventory part was found in an imported vendor price list.")}`;
    const exportBody = `${snapshot ? `<div class="pricing-snapshot-card"><div><span class="pricing-ready-badge"><i aria-hidden="true"></i> ${snapshot.is_stale ? "More than 24 hours old" : "Current export ready"}</span><h3>${escHtml(snapshot.filename)}</h3><p>${count(snapshot.row_count)} parts · Export generation date ${escHtml(snapshot.generation_date || "not provided")} · Uploaded ${dateLabel(snapshot.created_at)}</p></div></div>` : empty("No Shopmonkey parts export", "Export all parts from Shopmonkey, then upload the .xlsx file here.")}
      <div class="pricing-inventory-summary"><div><span>Total parts</span><strong>${count(snapshot?.row_count || 0)}</strong></div><div><span>Export state</span><strong>${snapshot ? (snapshot.is_stale ? "Update" : "Ready") : "Missing"}</strong></div></div>`;
    return `<section class="pricing-panel"><div class="pricing-panel-head"><div><h3>Shopmonkey Inventory</h3><p>Manage the inventory export and check vendor-list coverage. One export can be reused for 24 hours.</p></div>${can("pricing.import") ? `<button class="btn btn-primary" type="button" data-pricing-action="open-baseline-upload">Upload parts export</button>` : ""}</div><nav class="pricing-inventory-tabs" aria-label="Shopmonkey inventory views"><button type="button" data-pricing-inventory-view="export" class="${state.inventoryView === "export" ? "active" : ""}">Parts export</button><button type="button" data-pricing-inventory-view="coverage" class="${state.inventoryView === "coverage" ? "active" : ""}">Price-list coverage</button></nav><div class="pricing-inventory-view">${state.inventoryView === "coverage" ? coverageBody : exportBody}</div></section>`;
  }
  function workspace() {
    const content = state.tab === "rules" ? rulesScreen() : state.tab === "inventory" ? inventoryScreen() : vendorLists();
    return `${header()}${tabs()}<main class="pricing-workspace-body">${content}</main>${baselineUploadModal()}${importConfirmationModal()}`;
  }

  function progress() {
    return `<ol class="pricing-wizard-progress">${STEPS.map((label, index) => { const step = index + 1; const status = step < state.step ? "complete" : step === state.step ? "active" : "upcoming"; return `<li class="${status}"><button type="button" data-pricing-step="${step}" ${step > state.step ? "disabled" : ""} aria-current="${status === "active" ? "step" : "false"}"><span>${status === "complete" ? "✓" : step}</span><b>${label}</b></button></li>`; }).join("")}</ol>`;
  }
  function wizardHeader() {
    return `<header class="pricing-wizard-header"><div><div class="pricing-kicker">Price List Converter</div><h2>Import vendor price list</h2><p>${escHtml(state.filename || "New price list")} · Step ${state.step} of ${STEPS.length}</p></div><button class="btn btn-secondary" type="button" data-pricing-action="close-wizard">Save and close</button></header>${progress()}`;
  }
  function chooseStep() {
    const vendorStatus = state.parsing ? `<em class="pricing-field-status"><i class="pricing-spinner pricing-spinner-small" aria-hidden="true"></i> Parsing</em>` : state.vendorAutoDetected ? `<em class="pricing-field-status">Auto-detected</em>` : "";
    const dateStatus = !state.parsing && state.sessionId && state.effectiveDate ? `<em class="pricing-field-status">Detected</em>` : "";
    const ready = Boolean(state.sessionId && !state.parsing);
    return `<div class="pricing-step-heading"><span>Step 1</span><h3>Choose a price list</h3><p>Known formats fill the vendor and effective date automatically.</p></div><div class="pricing-form-grid pricing-form-grid-two"><label><span class="pricing-field-label">Vendor${vendorStatus}</span><input id="pricing-vendor" value="${escHtml(state.vendor)}" placeholder="${state.parsing ? "Detecting vendor…" : "Auto-detect or enter vendor"}" autocomplete="off" ${state.parsing ? "disabled" : ""}></label><label><span class="pricing-field-label">Effective date${dateStatus}</span><input id="pricing-effective-date" type="date" value="${escHtml(state.effectiveDate)}" ${state.parsing ? "disabled" : ""}></label></div>
      <label class="pricing-file-drop ${state.parsing ? "is-parsing" : ""} ${ready ? "is-ready" : ""}" for="pricing-source-file"><input id="pricing-source-file" type="file" accept=".xlsx,.xls,.csv,.pdf" ${state.parsing ? "disabled" : ""}><span class="pricing-file-drop-icon" aria-hidden="true">${state.parsing ? `<i class="pricing-spinner"></i>` : ready ? "✓" : "↑"}</span><span class="pricing-file-drop-copy"><strong>${escHtml(state.filename || "Choose PDF, Excel, or CSV")}</strong><small>${state.parsing ? "Parsing the price list and detecting vendor and effective date…" : ready ? "File parsed and ready for column review · Click to replace" : "The next screen always asks you to confirm the columns."}</small></span></label>`;
  }
  function candidate() { return state.candidates.find(item => item.id === state.candidateId) || state.candidates[0]; }
  function sourceSelect(field) {
    const item = candidate(); const selected = state.mapping[field] || "";
    return `<select data-map-field="${field}"><option value="">Do not import</option>${(item?.headers || []).map(header => `<option value="${escHtml(header)}" ${selected === header ? "selected" : ""}>${escHtml(header)}</option>`).join("")}</select>`;
  }
  function columnsStep() {
    const item = candidate(); if (!item) return empty("No table detected", "Go back and inspect a source file.");
    const customLabel = `Custom price column <span class="pricing-info-tooltip" tabindex="0" title="Use this when the vendor list includes a pricing value that is different from MSRP or Cost. Pricing rules can calculate from this column.">i</span>`;
    const fields = ["sku", "description", "cost", "msrp", "agency_price"];
    const presetControl = state.presetApplied
      ? `<label class="pricing-check-row ${state.mappingChanged ? "" : "is-disabled"}"><input id="pricing-save-preset" type="checkbox" ${state.savePreset ? "checked" : ""} ${state.mappingChanged ? "" : "disabled"}><span><strong>Update preset</strong><small>${state.mappingChanged ? "Save these revised assignments for the next import." : "Change an assignment to update this preset."}</small></span></label>`
      : `<label class="pricing-check-row"><input id="pricing-save-preset" type="checkbox" ${state.savePreset ? "checked" : ""}><span><strong>Save assignments as a preset</strong><small>Use these assignments automatically for future files from this vendor.</small></span></label>`;
    return `<div class="pricing-step-heading"><span>Step 2</span><h3>Confirm column assignments</h3><p>These are suggestions only. Confirm every assignment before importing.</p></div><div class="pricing-detected-vendor"><span aria-hidden="true">${state.vendorAutoDetected ? "✓" : "•"}</span><div><small>${state.vendorAutoDetected ? "Auto-detected vendor" : "Vendor"}</small><strong>${escHtml(state.vendor || "Not provided")}</strong></div><button class="pricing-text-button" type="button" data-pricing-step="1">Change</button></div><label class="pricing-candidate-select">Worksheet or PDF table<select id="pricing-candidate">${state.candidates.map(option => `<option value="${escHtml(option.id)}" ${option.id === item.id ? "selected" : ""}>${escHtml(option.label)} · ${count(option.row_count)} rows</option>`).join("")}</select></label>
      <div class="pricing-mapping-layout"><section class="pricing-source-preview"><div class="pricing-subhead"><div><h4>Source preview</h4><p>${escHtml(item.label)} · header row ${item.header_row}</p><small>Raw preview only. Repeated headers and rows without a SKU plus a numeric price are excluded from the import.</small></div></div><div class="pricing-table-wrap"><table><thead><tr>${item.headers.map(header => `<th>${escHtml(header)}</th>`).join("")}</tr></thead><tbody>${item.rows.slice(0, 10).map(row => `<tr>${row.map(cell => `<td>${escHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>
      <aside class="pricing-column-map">${state.presetApplied ? `<div class="pricing-preset-state"><span>Using preset</span><strong>${escHtml(state.presetName || "Vendor preset")}</strong></div>` : ""}<h4>Shopmonkey fields</h4><p>SKU and at least one price are required.</p>${fields.map(field => `<label>${field === "agency_price" ? customLabel : FIELD_LABELS[field]}${field === "sku" ? " <em>Required</em>" : ""}${sourceSelect(field)}</label>`).join("")}<details><summary>Optional fields</summary>${["vendor", "effective_date", "unit", "shopmonkey_id"].map(field => `<label>${FIELD_LABELS[field]}${sourceSelect(field)}</label>`).join("")}</details>${presetControl}</aside></div>`;
  }
  function ruleChoice() {
    const preview = state.rulePreview; const snapshot = preview?.snapshot || state.summary?.snapshot;
    const examples = preview?.examples || [];
    const priceChange = (source, adjustment, result) => `<span class="pricing-price-change"><small>${money(source)}</small><span><b>→</b><em>${escHtml(adjustment || "No adjustment")}</em></span><strong>${money(result)}</strong></span>`;
    return `<div class="pricing-step-heading"><span>Step 3</span><h3>Confirm pricing</h3><p>Confirm the automatically selected rule and check a few calculated prices before matching every part.</p></div>
      <section class="pricing-panel pricing-rule-confirmation"><div class="pricing-panel-head"><div><h3>Applied pricing rule</h3><p>Confirm both price terms below. SKU exceptions still apply when their part numbers match.</p></div><div class="pricing-baseline-inline pricing-rule-header-baseline"><div><span class="pricing-data-dot pricing-data-dot-${snapshotFreshness(snapshot)}" aria-hidden="true"></span><span>Shopmonkey parts import</span><strong>${snapshot ? `${count(snapshot.row_count)} parts · imported ${importDateLabel(snapshot.created_at)}` : "Not loaded"}</strong></div><button class="pricing-text-button" type="button" data-pricing-action="open-baseline-upload">${snapshot ? "Replace" : "Upload"}</button></div></div><div class="pricing-rule-confirmation-body"><div class="pricing-applied-rule-summary">${state.rulePreviewLoading ? `<div class="pricing-rule-preview-loading"><i class="pricing-spinner" aria-hidden="true"></i><span>Loading rule terms…</span></div>` : appliedRuleTerms(preview)}</div>${snapshot?.is_stale ? `<div class="pricing-action-warning"><span>!</span><p><strong>This export is more than 24 hours old.</strong> Upload a current Shopmonkey parts export.</p></div>` : ""}</div></section>
      <section class="pricing-panel pricing-rule-examples"><div class="pricing-panel-head"><div><h3>Example calculations</h3><p>${state.ruleExampleSearch ? `${count(preview?.example_total || 0)} matching price-list part${Number(preview?.example_total || 0) === 1 ? "" : "s"}.` : "Each example shows the source price, the exact adjustment, and the resulting price."}</p></div><label class="pricing-search pricing-example-search"><span aria-hidden="true">⌕</span><input id="pricing-rule-example-search" type="search" value="${escHtml(state.ruleExampleSearch)}" placeholder="Search SKU or description" aria-label="Search price-list calculation examples"></label></div>${state.rulePreviewLoading ? `<div class="pricing-rule-example-empty"><i class="pricing-spinner" aria-hidden="true"></i> Updating examples…</div>` : examples.length ? `<div class="pricing-table-wrap"><table class="pricing-data-table"><thead><tr><th>Part</th><th>Our Cost</th><th>Our Retail (sell)</th><th>Rule used</th></tr></thead><tbody>${examples.map(row => `<tr><th scope="row"><span class="pricing-example-part"><strong>${escHtml(row.sku)}</strong><small>${escHtml(row.description || (row.matched ? "Matched Shopmonkey part" : "Not currently in Shopmonkey"))}</small></span></th><td>${priceChange(row.cost_source_value, row.cost_adjustment, row.new_cost)}</td><td>${priceChange(row.retail_source_value, row.retail_adjustment, row.new_retail)}</td><td><span class="pricing-example-rule">${escHtml(row.rule_name)}</span></td></tr>`).join("")}</tbody></table></div>` : `<div class="pricing-rule-example-empty">${snapshot ? state.ruleExampleSearch ? `No price-list parts match “${escHtml(state.ruleExampleSearch)}”.` : "No example parts are available from this list." : "Upload a Shopmonkey parts export to see before-and-after examples."}</div>`}</section>${state.matching ? `<div class="pricing-matching-overlay" role="status" aria-live="polite"><i class="pricing-spinner" aria-hidden="true"></i><strong>Matching Shopmonkey parts…</strong><span>Comparing SKUs, brands, vendors, and current prices.</span></div>` : ""}`;
  }
  function baselineRequirement(snapshot = state.summary?.snapshot) {
    if (!snapshot) return "No Shopmonkey parts export is loaded.";
    const uploadedAt = Date.parse(snapshot.created_at || "");
    if (snapshot.is_stale || (Number.isFinite(uploadedAt) && Date.now() - uploadedAt >= 86400000)) return "The current Shopmonkey parts export is more than 24 hours old.";
    return "";
  }
  function baselineUploadModal() {
    if (!state.baselineModal) return "";
    const reason = state.baselineModalReason || baselineRequirement() || "Replace the current Shopmonkey parts export.";
    const uploading = state.snapshotUploading;
    const body = uploading
      ? `<div class="pricing-baseline-uploading" role="status" aria-live="polite"><i class="pricing-spinner pricing-baseline-upload-spinner" aria-hidden="true"></i><div><strong>Importing Shopmonkey parts…</strong><p>${escHtml(state.snapshotUploadFilename || "Shopmonkey parts export")}</p><small>Large exports can take a minute. Keep this window open while every part is processed.</small></div></div>`
      : `<div class="pricing-baseline-modal-layout"><div class="pricing-baseline-instructions"><ol><li>Open <strong>Inventory → Parts</strong> in Shopmonkey.</li><li>Click <strong>Export XLS</strong> above the parts table.</li><li>Upload the downloaded <strong>.xlsx</strong> file here.</li></ol><label class="btn btn-primary" for="pricing-modal-snapshot">Choose Shopmonkey export<input id="pricing-modal-snapshot" type="file" accept=".xlsx" hidden></label><small>The complete export preserves Shopmonkey IDs and existing part fields.</small></div><figure><img src="/ui/images/shopmonkey-export-parts-arrow.png" alt="Shopmonkey Parts screen with an arrow pointing to the Export XLS button"><figcaption>Use Export XLS on the Shopmonkey Parts page.</figcaption></figure></div>`;
    return `<div class="pricing-baseline-modal-backdrop" role="presentation"><section class="pricing-baseline-modal" role="dialog" aria-modal="true" aria-labelledby="pricing-baseline-modal-title" aria-busy="${uploading ? "true" : "false"}"><header><div><span>Shopmonkey parts export</span><h3 id="pricing-baseline-modal-title">${uploading ? "Importing current parts" : "Upload current parts"}</h3><p>${uploading ? "Reading and saving the complete inventory export." : escHtml(reason)}</p></div><button type="button" data-pricing-action="close-baseline-upload" aria-label="Close" ${uploading ? "disabled" : ""}>×</button></header>${body}</section></div>`;
  }
  function importRuleEditModal() {
    if (!state.ruleEditModal || !state.editingRule) return "";
    return `<div class="pricing-rule-modal-backdrop" role="presentation"><section class="pricing-rule-modal" role="dialog" aria-modal="true" aria-label="Edit selected pricing rule">${ruleEditor(false)}</section></div>`;
  }
  function importRuleChangeModal() {
    if (!state.ruleChangeModal) return "";
    const preview = state.rulePreview || {}; const choice = preview.choice || "auto";
    return `<div class="pricing-rule-modal-backdrop" role="presentation"><section class="pricing-rule-choice-modal" role="dialog" aria-modal="true" aria-labelledby="pricing-change-rule-title"><header><div><span>Applied pricing rule</span><h3 id="pricing-change-rule-title">Change rule</h3><p>Choose a rule for this price list. The rule card and examples will update after you apply it.</p></div><button type="button" data-pricing-action="close-change-import-rule" aria-label="Close">×</button></header><form data-pricing-form="change-import-rule"><label>Pricing rule<select name="choice"><option value="auto" ${choice === "auto" ? "selected" : ""}>Automatic — ${escHtml(preview.auto_label || "No matching rule")}</option><option value="none" ${choice === "none" ? "selected" : ""}>No pricing rule</option>${(preview.options || []).map(rule => `<option value="${escHtml(rule.id)}" ${choice === rule.id ? "selected" : ""}>${escHtml(rule.name)} — Cost: ${escHtml(costRuleLabel(rule))} · Retail: ${escHtml(ruleLabel(rule))}</option>`).join("")}</select><small>This choice applies only to this imported price list.</small></label><footer><button class="btn btn-secondary" type="button" data-pricing-action="close-change-import-rule">Cancel</button><button class="btn btn-primary" type="submit">Apply rule</button></footer></form></section></div>`;
  }
  function filterTabs() {
    const totals = state.review?.counts || {}; const items = [["updated", "Matched changes", totals.updated], ["needs_review", "Needs review", totals.needs_review], ["possible_new", "Possible new", totals.possible_new], ["unchanged", "Already current", totals.unchanged], ["skipped", "Skipped", totals.skipped]];
    return `<div class="pricing-match-tabs">${items.map(([id, label, total]) => `<button type="button" class="${state.reviewFilter === id ? "active" : ""}" data-review-filter="${id}"><span>${label}</span><strong>${count(total || 0)}</strong></button>`).join("")}</div>${state.review?.missing_from_price_list ? `<p class="pricing-missing-note">${count(state.review.missing_from_price_list)} Shopmonkey parts are not in this vendor price list and will not be changed.</p>` : ""}`;
  }
  function reviewRows() {
    const rows = state.review?.rows || [];
    const selectable = Number(state.review?.selectable_total || 0); const selected = Number(state.review?.selected_total || 0);
    const bulkActions = state.reviewFilter === "possible_new" && selectable
      ? `<label class="pricing-review-bulk-menu"><span class="sr-only">Bulk actions</span><select id="pricing-review-bulk-action" ${state.reviewBulkLoading ? "disabled" : ""}><option value="">Bulk actions…</option><option value="approve-new">Approve filtered as new parts</option><option value="remove-new-approval">Remove filtered new-part approvals</option></select></label>` : "";
    const selectionTools = selectable ? `<div class="pricing-review-selection-tools"><span><strong>${count(selected)}</strong> of ${count(selectable)} selected</span><button class="pricing-text-button" type="button" data-pricing-action="review-select-all" ${state.reviewBulkLoading || selected === selectable ? "disabled" : ""}>Select all</button><button class="pricing-text-button" type="button" data-pricing-action="review-select-none" ${state.reviewBulkLoading || selected === 0 ? "disabled" : ""}>Select none</button>${bulkActions}${state.reviewBulkLoading ? `<i class="pricing-spinner pricing-spinner-small" aria-label="Updating selection"></i>` : ""}</div>` : "";
    const tools = `<div class="pricing-review-tools"><label class="pricing-search"><span aria-hidden="true">⌕</span><input id="pricing-review-search" type="search" value="${escHtml(state.search)}" placeholder="Search SKU, description, brand, vendor, or ID" aria-label="Search review"></label>${selectionTools}<span>${count(state.review?.total || 0)} rows</span></div>`;
    if (!rows.length) return `${tools}${empty("Nothing in this view", "Choose another status or clear the search. No placeholder rows are shown.")}`;
    const pages = Math.max(1, Math.ceil((state.review?.total || 0) / (state.review?.page_size || 20)));
    const matchLabel = match => [match.sku, match.name, match.brand || match.vendor, match.shopmonkey_id ? `ID ${match.shopmonkey_id}` : ""].filter(Boolean).join(" · ");
    const descriptionLabel = row => row.description
      ? `${escHtml(row.description)}${row.description_source === "shopmonkey" ? `<em>Existing Shopmonkey description retained</em>` : ""}`
      : row.status === "possible_new"
        ? `No vendor description<em>New part will use the SKU as its Name</em>`
        : "No description supplied";
    return `${tools}<div class="pricing-table-wrap"><table class="pricing-data-table"><thead><tr><th>Include</th><th>Part</th><th>Brand</th><th>Current cost</th><th>New cost</th><th>Current our retail</th><th>New our retail</th><th>Result</th><th>Action</th></tr></thead><tbody>${rows.map(row => `<tr><td>${row.status === "possible_new" ? `<label class="pricing-table-check"><input type="checkbox" data-review-row="${row.id}" data-review-kind="new" ${row.approved_new ? "checked" : ""}> Approve new</label>` : row.status === "updated" ? `<input type="checkbox" data-review-row="${row.id}" data-review-kind="include" ${row.included ? "checked" : ""} aria-label="Include ${escHtml(row.sku)}">` : "—"}</td><th class="pricing-part-identity" scope="row"><strong>${escHtml(row.sku)}</strong><small>${descriptionLabel(row)}</small></th><td>${escHtml(row.brand || "—")}</td><td>${money(row.current_cost)}</td><td>${money(row.new_cost)}</td><td>${money(row.current_retail)}</td><td>${money(row.new_retail)}</td><td><span class="pricing-status-pill pricing-status-${row.status}">${escHtml(row.reason)}</span></td><td>${row.candidate_matches?.length ? `<select class="pricing-match-select" data-review-match="${row.id}"><option value="">Choose a Shopmonkey match…</option><option value="skip">Skip this part</option>${row.candidate_matches.map(match => `<option value="${match.inventory_index}">${escHtml(matchLabel(match))}</option>`).join("")}</select>` : row.status === "skipped" ? `<button class="pricing-text-button" type="button" data-pricing-action="restore-skipped-part" data-row-id="${row.id}">Restore to review</button>` : row.reason === "No applicable pricing rule" ? `<button class="pricing-text-button" type="button" data-pricing-action="manage-rules">Add rule</button>` : "—"}</td></tr>`).join("")}</tbody></table></div><div class="pricing-pagination"><button class="btn btn-secondary" type="button" data-pricing-action="review-prev" ${state.reviewPage <= 1 ? "disabled" : ""}>Previous</button><span>Page ${state.reviewPage} of ${pages}</span><button class="btn btn-secondary" type="button" data-pricing-action="review-next" ${state.reviewPage >= pages ? "disabled" : ""}>Next</button></div>`;
  }
  function matchStep() { return `<div class="pricing-step-heading"><span>Step 4</span><h3>Match Shopmonkey parts</h3><p>Only exact Shopmonkey ID, brand + SKU, or vendor + SKU matches are automatic.</p></div>${filterTabs()}${reviewRows()}`; }
  function reviewStep() {
    const totals = state.review?.counts || {}; const changes = state.review?.selected_count || 0; const packageInfo = buildExportPackage(changes);
    return `<section class="pricing-review-card"><header class="pricing-review-header"><div><span class="pricing-ready-badge"><i></i> ${changes ? "Ready to save" : "No selected changes"}</span><h3>Review export</h3><p>Confirm the totals and final note setting. Individual parts were reviewed in the previous step.</p></div></header>
      <div class="pricing-summary-grid pricing-summary-grid-four"><div><span>Selected changes</span><strong>${count(changes)}</strong></div><div><span>Existing updates</span><strong>${count(totals.updated || 0)}</strong></div><div><span>Possible new</span><strong>${count(totals.possible_new || 0)}</strong></div><div><span>Needs review</span><strong>${count(totals.needs_review || 0)}</strong></div></div>
      <div class="pricing-final-review-body"><div class="pricing-baseline-check"><span>✓</span><div><strong>Shopmonkey baseline confirmed</strong><small>${escHtml(state.review?.snapshot?.filename || "No baseline")} · full rows are preserved.</small></div></div><label class="pricing-final-notes"><input id="pricing-review-include-notes" type="checkbox" ${state.includeNotes ? "checked" : ""}><span><strong>Add MSRP and effective date to Shopmonkey notes</strong><small>Unrelated existing note text is preserved.</small></span></label><div class="pricing-final-package"><span>▣</span><div><small>${packageInfo.isSplit ? "ZIP package · split at 10,000 parts" : "Excel workbook"}</small><strong>${escHtml(packageInfo.name)}</strong></div></div></div>
      <footer class="pricing-final-actions"><button class="btn btn-secondary" type="button" data-pricing-action="close-wizard">Save and exit</button><button class="btn btn-primary" data-pricing-action="export" type="button" ${!changes || totals.needs_review || !can("pricing.export") ? "disabled" : ""}>Save and export</button></footer></section>`;
  }
  function finishStep() {
    return `<div class="pricing-finish"><span class="pricing-finish-icon">✓</span><span class="pricing-status-pill pricing-status-exported">${state.markedImported ? "Imported into Shopmonkey" : "Export created"}</span><h3>${escHtml(state.artifact?.filename || "Pricing export ready")}</h3><p>${state.markedImported ? "Import confirmed. No additional Shopmonkey export is required." : `${count(state.artifact?.row_count || 0)} parts in ${count(state.artifact?.file_count || 0)} file${state.artifact?.file_count === 1 ? "" : "s"}.`}</p><div class="pricing-finish-file"><span>▣</span><div><strong>${escHtml(state.artifact?.filename || "")}</strong><small>Import every numbered file when a ZIP is created.</small></div><button class="btn btn-primary" type="button" data-pricing-action="download-artifact" data-download-url="${escHtml(state.artifact?.download_url || "")}" data-filename="${escHtml(state.artifact?.filename || "")}">Save file</button></div><div class="pricing-finish-actions">${state.markedImported ? "" : `<button class="btn btn-primary" type="button" data-pricing-action="confirm-import-open" data-run-id="${state.runId}" data-filename="${escHtml(state.artifact?.filename || "this export")}">Confirm imported into Shopmonkey</button>`}<button class="btn btn-secondary" type="button" data-pricing-action="finish">Done</button></div></div>`;
  }
  function importConfirmationModal() {
    if (!state.importConfirm) return "";
    const all = Boolean(state.importConfirm.all);
    return `<div class="pricing-confirm-modal-backdrop" role="presentation"><section class="pricing-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="pricing-confirm-import-title"><span class="pricing-confirm-icon">✓</span><h3 id="pricing-confirm-import-title">Confirm Shopmonkey import</h3><p>${all ? `Confirm all <strong>${count(state.importConfirm.count || 0)} exported price lists</strong> were imported into Shopmonkey before marking them imported.` : `Confirm you imported <strong>${escHtml(state.importConfirm.filename || "the exported file")}</strong> into Shopmonkey before confirming this price list as imported.`}</p><div><button class="btn btn-secondary" type="button" data-pricing-action="confirm-import-close">Cancel</button><button class="btn btn-primary" type="button" data-pricing-action="confirm-import-submit">${all ? "Yes, mark all imported" : "Yes, it was imported"}</button></div></section></div>`;
  }
  function footer() {
    if (state.step >= 5) return ""; const labels = {1: "Inspect columns", 2: "Confirm assignments", 3: "Match Shopmonkey parts", 4: "Review export"};
    const nextLabel = state.step === 1 && state.sessionId ? "Review columns" : labels[state.step];
    return `<footer class="pricing-wizard-footer"><button class="btn btn-secondary" type="button" data-pricing-action="back" ${state.step === 1 || state.matching ? "disabled" : ""}>Back</button><button class="btn btn-primary" type="button" data-pricing-action="next" ${state.parsing || state.matching ? "disabled" : ""}>${state.parsing ? "Parsing…" : state.matching ? "Matching…" : nextLabel}</button></footer>`;
  }
  function wizard() { const screens = {1: chooseStep, 2: columnsStep, 3: ruleChoice, 4: matchStep, 5: reviewStep, 6: finishStep}; return `${wizardHeader()}<main class="pricing-wizard-card ${state.step === 5 ? "pricing-wizard-card-review" : ""}">${screens[state.step]()}${footer()}</main>${baselineUploadModal()}${importRuleEditModal()}${importRuleChangeModal()}${importConfirmationModal()}`; }
  function render() {
    const root = document.getElementById("pricing-center-root"); if (!root) return;
    root.setAttribute("aria-busy", state.loading || state.parsing || state.matching || state.snapshotUploading || state.reviewBulkLoading || state.coverageLoading || state.bulkExporting ? "true" : "false"); root.innerHTML = state.loading && !state.summary ? `<div class="pricing-loading">Loading Price List Converter…</div>` : (state.mode === "wizard" ? wizard() : workspace());
  }
  function syncInputs() {
    state.vendor = document.getElementById("pricing-vendor")?.value.trim() ?? state.vendor;
    state.effectiveDate = document.getElementById("pricing-effective-date")?.value ?? state.effectiveDate;
    state.includeNotes = document.getElementById("pricing-include-notes")?.checked ?? state.includeNotes;
  }
  async function inspectSource() {
    syncInputs();
    const modified = state.sourceFile?.lastModified ? new Date(state.sourceFile.lastModified) : null;
    const fileModified = modified && !Number.isNaN(modified.getTime()) ? `${modified.getFullYear()}-${String(modified.getMonth() + 1).padStart(2, "0")}-${String(modified.getDate()).padStart(2, "0")}` : "";
    const response = await call("/api/pricing/import/inspect", {filename: state.sourceFile?.name, content_base64: await fileBase64(state.sourceFile), vendor: state.vendorAutoDetected ? "" : state.vendor, effective_date: state.effectiveDate, file_last_modified: fileModified, include_notes: state.includeNotes});
    state.vendor = response.vendor || state.vendor; state.effectiveDate = response.effective_date || "";
    state.vendorAutoDetected = Boolean(response.vendor_auto_detected);
    state.sessionId = response.session_id; state.candidates = response.candidates || []; state.candidateId = state.candidates[0]?.id || ""; state.mapping = state.candidates[0]?.suggested_mapping || {};
    delete state.mapping.brand; state.presetApplied = Boolean(response.preset_applied); state.presetName = response.preset_name || ""; state.mappingChanged = false; state.savePreset = false;
    if (response.preset_applied) notify(`${response.preset_name} assignments loaded. Confirm them before continuing.`, "info");
  }
  async function confirmColumns() {
    const savePreset = document.getElementById("pricing-save-preset")?.checked ?? state.savePreset;
    const extension = (state.sourceFile?.name || state.filename || "file").split(".").pop()?.toUpperCase() || "file";
    const response = await call("/api/pricing/import/confirm", {session_id: state.sessionId, candidate_id: state.candidateId, mapping: state.mapping, vendor: state.vendor, effective_date: state.effectiveDate, include_notes: state.includeNotes, save_preset: savePreset, preset_name: savePreset ? `${state.vendor} ${extension}` : ""});
    const excluded = Number(response.excluded_rows || 0);
    notify(`${count(response.rows_ready)} price-list rows are ready.${excluded ? ` ${count(excluded)} header or non-part rows were excluded.` : ""}`, "success");
  }
  async function loadRulePreview(choice) {
    if (!state.sessionId) return;
    const requestId = ++rulePreviewRequestId;
    const keepSearchFocus = document.activeElement?.id === "pricing-rule-example-search";
    state.rulePreviewLoading = true;
    if (!keepSearchFocus) render();
    try {
      const payload = {session_id: state.sessionId};
      if (choice !== undefined) payload.choice = choice;
      if (state.ruleExampleSearch) payload.search = state.ruleExampleSearch;
      const preview = await call("/api/pricing/import/rule-preview", payload);
      if (requestId === rulePreviewRequestId) state.rulePreview = preview;
    } finally {
      if (requestId !== rulePreviewRequestId) return;
      state.rulePreviewLoading = false; render();
      if (keepSearchFocus) window.requestAnimationFrame(() => {
        const input = document.getElementById("pricing-rule-example-search");
        input?.focus(); input?.setSelectionRange(input.value.length, input.value.length);
      });
    }
  }
  async function uploadSnapshot(file) {
    const openedFromModal = state.baselineModal;
    state.baselineModal = true; state.snapshotUploading = true; state.snapshotUploadFilename = file.name; render();
    try {
      const response = await call("/api/pricing/inventory/upload", {filename: file.name, content_base64: await fileBase64(file)});
      notify(`${count(response.row_count)} Shopmonkey parts loaded.`, "success"); await loadData();
      if (state.sessionId && state.step === 3) await loadRulePreview();
      state.baselineModal = false; state.baselineModalReason = "";
      if (openedFromModal && state.step >= 4) {
        state.step = 3; state.runId = ""; state.review = null;
        notify("The current parts export is loaded. Run matching again before exporting.", "info");
      }
    }
    finally { state.snapshotUploading = false; state.snapshotUploadFilename = ""; render(); }
  }
  async function downloadArtifact(url, filename = "") {
    if (!url) return false;
    const artifactId = decodeURIComponent(String(url).split("/").filter(Boolean).pop() || "");
    if (window.pywebview?.api?.save_pricing_export && artifactId) {
      const saved = await window.pywebview.api.save_pricing_export(artifactId);
      if (!saved?.ok) throw new Error(saved?.error || "The export file could not be saved.");
      if (saved.cancelled) return false;
      return true;
    }
    const link = document.createElement("a"); link.href = url;
    if (filename) link.download = filename;
    document.body.appendChild(link); link.click(); link.remove();
    return true;
  }
  function positionListMenu(summary) {
    window.requestAnimationFrame(() => {
      const details = summary.closest(".pricing-list-menu");
      if (!details?.open) return;
      const menu = details.querySelector(":scope > div"); if (!menu) return;
      const trigger = summary.getBoundingClientRect();
      const width = menu.offsetWidth || 150; const height = menu.offsetHeight || 90; const gap = 6;
      let top = trigger.bottom + gap;
      if (top + height > window.innerHeight - 8) top = Math.max(8, trigger.top - height - gap);
      const left = Math.max(8, Math.min(trigger.right - width, window.innerWidth - width - 8));
      menu.style.setProperty("--pricing-list-menu-top", `${Math.round(top)}px`);
      menu.style.setProperty("--pricing-list-menu-left", `${Math.round(left)}px`);
    });
  }
  function scrollToOpenRule(ruleId = "") {
    window.requestAnimationFrame(() => {
      const cards = [...document.querySelectorAll("[data-pricing-card-rule-id]")];
      const target = cards.find(card => card.dataset.pricingCardRuleId === ruleId) || document.querySelector(".pricing-rule-editor");
      target?.scrollIntoView({behavior: "smooth", block: "center"});
    });
  }
  function syncCalculationTarget(form, target) {
    const field = target === "cost" ? "cost_" : "";
    const source = form.querySelector(`[data-pricing-calculation-source="${target}"]`)?.value || "cost";
    const amount = form.querySelector(`[name="${field}amount"]`);
    const percent = form.querySelector(`[name="${field}amount_unit"][value="percent"]`);
    const dollar = form.querySelector(`[name="${field}amount_unit"][value="dollar"]`);
    const controls = form.querySelector(`[data-pricing-adjustment-controls="${target}"]`); const valueField = form.querySelector(`[data-pricing-value-field="${target}"]`);
    const hint = form.querySelector(`[data-pricing-calculation-hint="${target}"]`);
    if (hint) hint.textContent = calculationHint(source, target);
    if (controls) controls.hidden = false; if (valueField) valueField.hidden = false;
    if (percent) percent.disabled = source === "fixed_retail";
    if (dollar) dollar.disabled = source === "cost_margin";
    if (source === "fixed_retail" && dollar) dollar.checked = true;
    else if (source === "cost_margin" && percent) percent.checked = true;
    else if (percent && dollar && !percent.checked && !dollar.checked) percent.checked = true;
    const unit = dollar?.checked ? "dollar" : "percent";
    let method = "markup_percent_cost"; let sourceField = source;
    if (source === "cost") method = unit === "dollar" ? "flat_markup_cost" : "markup_percent_cost";
    else if (source === "msrp") method = unit === "dollar" ? "flat_discount_msrp" : "discount_percent_msrp";
    else if (source === "cost_margin") { method = "margin_percent_cost"; sourceField = "cost"; }
    else if (source === "fixed_retail") { method = "fixed_retail"; sourceField = target === "cost" ? "cost" : "retail"; }
    else if (source === "custom_price") { sourceField = "agency_price"; method = Number(amount?.value || 0) === 0 ? "imported_value" : (unit === "dollar" ? "flat_markup_source" : "markup_percent_source"); }
    else if (Number(amount?.value || 0) === 0) method = "imported_value";
    else method = unit === "dollar" ? "flat_markup_source" : "markup_percent_source";
    const methodField = form.querySelector(`[name="${field}method"]`); const sourceFieldInput = form.querySelector(`[name="${field}source_field"]`);
    if (methodField) methodField.value = method; if (sourceFieldInput) sourceFieldInput.value = sourceField;
  }
  function syncCalculationForm(form) {
    syncCalculationTarget(form, "retail");
    if (form.querySelector('[data-pricing-calculation-source="cost"]')) syncCalculationTarget(form, "cost");
  }
  async function nextStep() {
    syncInputs(); const parsingSource = state.step === 1 && !state.sessionId;
    const matchingParts = state.step === 3;
    if (parsingSource) state.parsing = true; else if (matchingParts) state.matching = true; else state.loading = true; render();
    try {
      if (state.step === 1 && !state.sessionId) await inspectSource();
      else if (state.step === 2) { await confirmColumns(); await loadRulePreview(); }
      else if (state.step === 3) {
        const requirement = baselineRequirement();
        if (requirement) { state.baselineModal = true; state.baselineModalReason = requirement; return; }
        const result = await call("/api/pricing/reconcile", {session_id: state.sessionId, snapshot_id: state.summary.snapshot.id}); state.runId = result.run_id; state.reviewFilter = "updated"; await loadReview("updated");
      } else if (state.step === 4) {
        await call("/api/pricing/review/finalize", {run_id: state.runId});
        state.reviewFilter = "updated"; await loadReview("updated");
      }
      state.step += 1;
    } catch (error) { notify(error.message, "error"); }
    finally { state.loading = false; state.parsing = false; state.matching = false; render(); }
  }
  async function saveRule(form) {
    const editingImportRule = state.ruleEditModal;
    syncCalculationForm(form); const values = Object.fromEntries(new FormData(form)); await call("/api/pricing/rules/save", {...values, enabled: true}); notify("Pricing rule saved.", "success"); state.ruleEditor = false; state.exceptionEditor = false; state.ruleEditModal = false; state.editingRule = null; state.ruleGroup = ""; state.exceptionGroup = "";
    if (editingImportRule) {
      const response = await call("/api/pricing/rules"); state.rules = response.rules || [];
      if (state.sessionId) await loadRulePreview(); else render();
    } else await loadData();
  }
  async function changeImportRule(form) {
    const choice = String(new FormData(form).get("choice") || "auto");
    state.ruleChangeModal = false;
    await loadRulePreview(choice);
    notify("Applied pricing rule updated.", "success");
  }
  async function bulkReviewSelection(selected) {
    if (!state.runId || !["updated", "possible_new"].includes(state.reviewFilter)) return;
    state.reviewBulkLoading = true; render();
    try {
      const result = await call("/api/pricing/review/bulk", {
        run_id: state.runId, status: state.reviewFilter, search: state.search, selected,
      });
      await loadReview();
      notify(`${count(result.updated_count)} parts ${selected ? "selected" : "cleared"}.`, "success");
    } finally { state.reviewBulkLoading = false; render(); }
  }
  async function handleAction(button) {
    const action = button.dataset.pricingAction;
    if (action === "start-import") { Object.assign(state, {mode: "wizard", step: 1, sessionId: "", runId: "", candidates: [], mapping: {}, filename: "", vendor: "", vendorAutoDetected: false, effectiveDate: "", includeNotes: true, sourceFile: null, parsing: false, matching: false, artifact: null, markedImported: false, baselineModal: false, baselineModalReason: "", rulePreview: null, rulePreviewLoading: false, ruleExampleSearch: "", ruleEditModal: false, ruleChangeModal: false, presetApplied: false, presetName: "", mappingChanged: false, savePreset: false, importConfirm: null}); render(); return; }
    if (action === "close-wizard" || action === "finish") { state.ruleEditModal = false; state.ruleChangeModal = false; state.mode = "workspace"; state.tab = "lists"; await loadData(); return; }
    if (action === "back") { state.step = Math.max(1, state.step - 1); render(); return; }
    if (action === "next") { await nextStep(); return; }
    if (action === "open-baseline-upload") { state.baselineModal = true; state.baselineModalReason = baselineRequirement() || "Replace the current Shopmonkey parts export."; render(); return; }
    if (action === "close-baseline-upload") { state.baselineModal = false; state.baselineModalReason = ""; render(); return; }
    if (action === "manage-rules") { state.mode = "workspace"; state.tab = "rules"; render(); return; }
    if (action === "edit-import-rule") {
      button.closest("details")?.removeAttribute("open");
      const rule = state.rules.find(item => item.id === button.dataset.ruleId);
      if (!rule) throw new Error("That pricing rule could not be found.");
      state.editingRule = rule; state.ruleGroup = rule.scope_value || ""; state.exceptionGroup = "";
      state.ruleEditor = true; state.exceptionEditor = false; state.ruleChangeModal = false; state.ruleEditModal = true; render(); return;
    }
    if (action === "change-import-rule") { button.closest("details")?.removeAttribute("open"); state.ruleEditModal = false; state.ruleChangeModal = true; render(); return; }
    if (action === "close-change-import-rule") { state.ruleChangeModal = false; render(); return; }
    if (action === "new-rule") { state.editingRule = null; state.ruleGroup = button.dataset.ruleGroup || ""; state.exceptionGroup = ""; state.ruleEditor = true; state.exceptionEditor = false; render(); return; }
    if (action === "new-exception") { state.editingRule = null; state.ruleGroup = ""; state.exceptionGroup = button.dataset.exceptionGroup || ""; state.exceptionEditor = true; state.ruleEditor = false; render(); return; }
    if (action === "edit-rule") { state.editingRule = state.rules.find(rule => rule.id === button.dataset.ruleId) || null; state.ruleGroup = state.editingRule?.scope_type === "sku" ? "" : state.editingRule?.scope_value || ""; state.exceptionGroup = state.editingRule?.group_name || ""; state.exceptionEditor = state.editingRule?.scope_type === "sku"; state.ruleEditor = !state.exceptionEditor; render(); return; }
    if (action === "close-rule") { state.ruleEditor = false; state.ruleEditModal = false; state.editingRule = null; state.ruleGroup = ""; state.exceptionGroup = ""; render(); return; }
    if (action === "close-exception") { state.exceptionEditor = false; state.editingRule = null; state.ruleGroup = ""; state.exceptionGroup = ""; render(); return; }
    if (action === "delete-rule") { await call("/api/pricing/rules/delete", {id: button.dataset.ruleId}); await loadData(); return; }
    if (action === "continue-import") {
      state.loading = true; render();
      try {
        const saved = await call("/api/pricing/import/resume", {session_id: button.dataset.sessionId});
        Object.assign(state, {
          mode: "wizard", sessionId: saved.session.id, runId: saved.run_id || "",
          filename: saved.session.filename, vendor: saved.session.vendor,
          vendorAutoDetected: false, effectiveDate: saved.session.effective_date,
          includeNotes: saved.session.include_notes, candidates: saved.candidates || [],
          candidateId: saved.candidate_id || saved.candidates?.[0]?.id || "",
          mapping: Object.keys(saved.mapping || {}).length ? saved.mapping : saved.candidates?.[0]?.suggested_mapping || {}, sourceFile: null,
          presetApplied: Boolean(saved.preset_applied), presetName: saved.preset_name || "", mappingChanged: false, savePreset: false,
          ruleExampleSearch: "",
        });
        delete state.mapping.brand;
        if (saved.needs_rematch || saved.source_refreshed) {
          const snapshotId = state.summary?.snapshot?.id;
          if (!snapshotId) throw new Error("Upload a current Shopmonkey parts export before rematching this list.");
          const refreshed = await call("/api/pricing/reconcile", {session_id: saved.session.id, snapshot_id: snapshotId});
          state.runId = refreshed.run_id; state.reviewFilter = "needs_review"; state.reviewPage = 1;
          await loadReview("needs_review");
          const totals = state.review?.counts || {};
          state.reviewFilter = totals.needs_review ? "needs_review" : totals.possible_new ? "possible_new" : totals.updated ? "updated" : "unchanged";
          await loadReview(state.reviewFilter); state.step = 4;
          notify(`${saved.session.vendor || "Price list"} was ${saved.source_refreshed ? "reparsed and " : ""}rematched with the current Shopmonkey import. Review and finalize it again.`, "success");
        } else if (saved.run_id) {
          state.reviewFilter = "needs_review"; state.reviewPage = 1; await loadReview("needs_review");
          const totals = state.review?.counts || {};
          state.reviewFilter = totals.needs_review ? "needs_review" : totals.possible_new ? "possible_new" : totals.updated ? "updated" : "unchanged";
          await loadReview(state.reviewFilter); state.step = 4;
        } else {
          state.step = saved.session.status === "mapped" ? 3 : 2;
          if (state.step === 3) await loadRulePreview();
        }
      } finally { state.loading = false; render(); }
      return;
    }
    if (action === "delete-import") {
      if (!window.confirm(`Delete ${button.dataset.sessionName || "this vendor price list"}? Its saved review and export files will also be removed.`)) return;
      await call("/api/pricing/import/delete", {session_id: button.dataset.sessionId});
      notify("Vendor price list deleted.", "success"); await loadData(); return;
    }
    if (action === "edit-list-rule") {
      state.mode = "workspace"; state.tab = "rules";
      state.sessionId = button.dataset.sessionId || ""; state.runId = button.dataset.runId || "";
      state.editingRule = state.rules.find(rule => rule.id === button.dataset.ruleId) || {scope_type: "vendor", scope_value: button.dataset.ruleGroup || ""};
      state.ruleGroup = state.editingRule.id ? state.editingRule.scope_value || "" : "";
      state.exceptionGroup = ""; state.ruleEditor = true; state.exceptionEditor = false; render(); scrollToOpenRule(button.dataset.ruleId || ""); return;
    }
    if (action === "download-artifact") {
      if (await downloadArtifact(button.dataset.downloadUrl, button.dataset.filename)) notify("Export file saved.", "success");
      return;
    }
    if (action === "export-list") {
      if (button.dataset.downloadUrl) {
        if (await downloadArtifact(button.dataset.downloadUrl, button.dataset.filename || "")) notify("Export file saved.", "success");
        return;
      }
      state.loading = true; render();
      try {
        const artifact = await call("/api/pricing/export", {run_id: button.dataset.runId});
        if (await downloadArtifact(artifact.download_url, artifact.filename)) notify(`${count(artifact.row_count)} parts exported.`, "success");
        await loadData();
      } finally { state.loading = false; render(); }
      return;
    }
    if (action === "bulk-export") {
      state.bulkExporting = true; state.bulkExportMode = button.dataset.exportMode || "all"; render();
      try {
        const artifact = await call("/api/pricing/export/bulk", {mode: button.dataset.exportMode});
        if (await downloadArtifact(artifact.download_url, artifact.filename)) notify(`${count(artifact.row_count)} parts exported.`, "success");
        await loadData();
      } finally { state.bulkExporting = false; state.bulkExportMode = ""; render(); }
      return;
    }
    if (action === "open-run") {
      state.runId = button.dataset.runId; state.reviewFilter = ""; state.reviewPage = 1; await loadReview("");
      const totals = state.review?.counts || {};
      state.reviewFilter = totals.needs_review ? "needs_review" : totals.updated ? "updated" : totals.possible_new ? "possible_new" : "unchanged";
      await loadReview(state.reviewFilter); state.mode = "wizard"; state.step = state.reviewFilter === "updated" ? 5 : 4; render(); return;
    }
    if (action === "open-review") { state.reviewFilter = button.dataset.reviewFilter || "updated"; state.reviewPage = 1; await loadReview(state.reviewFilter); state.mode = "wizard"; state.step = state.reviewFilter === "updated" ? 5 : 4; render(); return; }
    if (action === "open-final-review") { state.reviewFilter = "updated"; state.reviewPage = 1; await loadReview("updated"); state.mode = "wizard"; state.step = 5; render(); return; }
    if (action === "review-prev" || action === "review-next") { state.reviewPage = Math.max(1, state.reviewPage + (action === "review-next" ? 1 : -1)); await loadReview(); render(); return; }
    if (action === "coverage-prev" || action === "coverage-next") { state.coveragePage = Math.max(1, state.coveragePage + (action === "coverage-next" ? 1 : -1)); await loadCoverage(); return; }
    if (action === "review-select-all") { await bulkReviewSelection(true); return; }
    if (action === "review-select-none") { await bulkReviewSelection(false); return; }
    if (action === "restore-skipped-part") { await call("/api/pricing/review/update", {run_id: state.runId, row_id: button.dataset.rowId, skipped: false}); await loadReview(); render(); return; }
    if (action === "confirm-import-open" || action === "mark-imported") { state.importConfirm = {runId: button.dataset.runId || state.runId, filename: button.dataset.filename || state.artifact?.filename || "this export"}; render(); return; }
    if (action === "confirm-import-all-open") { state.importConfirm = {all: true, count: Number(button.dataset.listCount || 0)}; render(); return; }
    if (action === "confirm-import-close") { state.importConfirm = null; render(); return; }
    if (action === "confirm-import-submit") {
      if (state.importConfirm?.all) {
        const result = await call("/api/pricing/export/mark-all-imported", {}); state.importConfirm = null;
        notify(`${count(result.imported_count)} price lists marked as imported into Shopmonkey.`, "success");
        await loadData(); return;
      }
      const runId = state.importConfirm?.runId; if (!runId) return;
      await call("/api/pricing/export/mark-imported", {run_id: runId}); state.markedImported = true; state.importConfirm = null;
      notify("Price list marked as imported into Shopmonkey.", "success");
      if (state.mode === "workspace") await loadData(); else render(); return;
    }
    if (action === "go-inventory") { state.mode = "workspace"; state.tab = "inventory"; await loadData(); return; }
    if (action === "recalculate") { const result = await call("/api/pricing/reconcile", {session_id: state.sessionId, snapshot_id: state.summary?.snapshot?.id}); state.runId = result.run_id; state.reviewFilter = "needs_review"; await loadReview("needs_review"); state.mode = "wizard"; state.step = 4; render(); return; }
    if (action === "export") {
      const requirement = baselineRequirement();
      if (requirement) { state.baselineModal = true; state.baselineModalReason = requirement; render(); return; }
      if (state.review?.snapshot?.id && state.review.snapshot.id !== state.summary?.snapshot?.id) {
        state.loading = true; render();
        try {
          const result = await call("/api/pricing/reconcile", {session_id: state.sessionId, snapshot_id: state.summary.snapshot.id});
          state.runId = result.run_id; state.reviewFilter = result.counts?.needs_review ? "needs_review" : result.counts?.possible_new ? "possible_new" : "updated";
          await loadReview(state.reviewFilter); state.step = state.reviewFilter === "updated" ? 5 : 4;
          notify("A newer parts export was already loaded, so matching was refreshed. Review the results before exporting.", "info");
        } finally { state.loading = false; render(); }
        return;
      }
      state.loading = true; render();
      try { state.artifact = await call("/api/pricing/export", {run_id: state.runId}); state.step = 6; notify("Shopmonkey import package created.", "success"); }
      catch (error) { notify(error.message, "error"); }
      finally { state.loading = false; render(); } return;
    }
    if (action === "api-plan") { state.apiPlan = await call("/api/pricing/api/plan", {run_id: state.runId}); notify(state.apiPlan.allowed ? `${count(state.apiPlan.eligible_parts)} parts qualify for the API update.` : state.apiPlan.reason, state.apiPlan.allowed ? "info" : "warn"); render(); return; }
    if (action === "api-apply") {
      const confirmation = document.getElementById("pricing-api-confirmation")?.value || "";
      state.loading = true; render();
      try { const result = await call("/api/pricing/api/apply", {run_id: state.runId, confirmation}); notify(`${count(result.completed)} Shopmonkey parts updated and verified.`, result.conflicts?.length ? "warn" : "success"); state.mode = "workspace"; state.tab = "inventory"; await loadData(); }
      catch (error) { notify(error.message, "error"); }
      finally { state.loading = false; render(); }
    }
  }
  function bind() {
    const root = document.getElementById("pricing-center-root"); if (!root) return;
    root.addEventListener("click", async event => {
      const listMenuSummary = event.target.closest(".pricing-list-menu > summary");
      if (listMenuSummary) {
        root.querySelectorAll(".pricing-list-menu[open]").forEach(menu => { if (menu !== listMenuSummary.parentElement) menu.open = false; });
        positionListMenu(listMenuSummary); return;
      }
      const scopeChoice = event.target.closest("[data-pricing-scope-choice]");
      if (scopeChoice) { const picker = scopeChoice.closest(".pricing-scope-picker"); const input = picker?.querySelector("[data-pricing-scope-search]"); if (input) input.value = scopeChoice.dataset.pricingScopeChoice || ""; const menu = picker?.querySelector(".pricing-scope-menu"); if (menu) menu.hidden = true; return; }
      const inventoryView = event.target.closest("[data-pricing-inventory-view]")?.dataset.pricingInventoryView;
      if (inventoryView) { state.inventoryView = inventoryView; if (inventoryView === "coverage") await loadCoverage(); else render(); return; }
      const tab = event.target.closest("[data-pricing-tab]")?.dataset.pricingTab; if (tab) { state.tab = tab; if (tab === "inventory" && state.inventoryView === "coverage") await loadCoverage(); else render(); return; }
      const step = Number(event.target.closest("[data-pricing-step]")?.dataset.pricingStep || 0); if (step && step <= state.step) { state.step = step; render(); return; }
      const filter = event.target.closest("[data-review-filter]")?.dataset.reviewFilter; if (filter && !event.target.closest("[data-pricing-action]")) { state.reviewFilter = filter; await loadReview(filter); render(); return; }
      const action = event.target.closest("[data-pricing-action]"); if (action) { try { await handleAction(action); } catch (error) { notify(error.message, "error"); } return; }
      const card = event.target.closest("[data-pricing-card-group]");
      const cardControl = event.target.closest(".pricing-rule-menu,.pricing-rule-card-editor,button,a,input,select,textarea,summary,label");
      if (card && !card.classList.contains("is-editing") && !cardControl) {
        const rule = state.rules.find(item => item.id === card.dataset.pricingCardRuleId) || null;
        state.editingRule = rule; state.ruleGroup = rule?.scope_value || card.dataset.pricingCardGroup || "";
        state.exceptionGroup = ""; state.ruleEditor = true; state.exceptionEditor = false; render();
      }
      if (!event.target.closest(".pricing-scope-picker")) root.querySelectorAll(".pricing-scope-menu").forEach(menu => { menu.hidden = true; });
    });
    root.addEventListener("focusin", event => { if (event.target.matches("[data-pricing-scope-search]")) renderScopeMenu(event.target); });
    root.addEventListener("scroll", () => root.querySelectorAll(".pricing-list-menu[open]").forEach(menu => { menu.open = false; }), true);
    window.addEventListener("resize", () => root.querySelectorAll(".pricing-list-menu[open]").forEach(menu => { menu.open = false; }));
    root.addEventListener("input", event => {
      if (event.target.id === "pricing-vendor") state.vendorAutoDetected = false;
      if (event.target.matches("[data-pricing-scope-search]")) renderScopeMenu(event.target);
      if (event.target.id === "pricing-rule-example-search") {
        state.ruleExampleSearch = event.target.value.trim();
        window.clearTimeout(ruleExampleSearchTimer);
        ruleExampleSearchTimer = window.setTimeout(() => {
          loadRulePreview().catch(error => notify(error.message, "error"));
        }, 250);
      }
    });
    root.addEventListener("change", async event => {
      try {
        if (event.target.id === "pricing-source-file") {
          syncInputs(); const keepManualVendor = Boolean(state.vendor && !state.vendorAutoDetected);
          state.sourceFile = event.target.files?.[0] || null; state.filename = state.sourceFile?.name || "";
          state.sessionId = ""; state.candidates = []; state.candidateId = ""; state.mapping = {};
          if (!keepManualVendor) state.vendor = ""; state.vendorAutoDetected = false; state.effectiveDate = "";
          if (!state.sourceFile) { render(); return; }
          state.parsing = true; render();
          try { await inspectSource(); }
          finally { state.parsing = false; render(); }
          return;
        }
        if (["pricing-snapshot-input", "pricing-wizard-snapshot", "pricing-modal-snapshot"].includes(event.target.id)) { const file = event.target.files?.[0]; if (file) await uploadSnapshot(file); return; }
        if (event.target.id === "pricing-candidate") { state.candidateId = event.target.value; state.mapping = candidate()?.suggested_mapping || {}; delete state.mapping.brand; state.mappingChanged = false; render(); return; }
        if (event.target.id === "pricing-save-preset") { state.savePreset = event.target.checked; return; }
        if (event.target.id === "pricing-review-include-notes") {
          state.includeNotes = event.target.checked;
          await call("/api/pricing/review/settings", {run_id: state.runId, include_notes: state.includeNotes});
          state.reviewPage = 1; await loadReview("updated"); render(); return;
        }
        if (event.target.id === "pricing-review-search") { state.search = event.target.value.trim(); state.reviewPage = 1; await loadReview(); render(); return; }
        if (event.target.id === "pricing-coverage-search") { state.coverageSearch = event.target.value.trim(); state.coveragePage = 1; await loadCoverage(); return; }
        if (event.target.id === "pricing-coverage-brand") { state.coverageBrand = event.target.value; state.coveragePage = 1; await loadCoverage(); return; }
        if (event.target.id === "pricing-review-bulk-action") {
          if (!event.target.value) return;
          await bulkReviewSelection(event.target.value === "approve-new"); return;
        }
        if (event.target.dataset.pricingScopeType !== undefined) { const form = event.target.closest("form"); const input = form?.querySelector("[data-pricing-scope-search]"); const label = form?.querySelector("[data-pricing-scope-label]"); if (input) { input.value = ""; input.dataset.scopeType = event.target.value; input.placeholder = `Search ${event.target.value}s…`; renderScopeMenu(input); } if (label) label.textContent = `Choose ${event.target.value}`; return; }
        if (event.target.dataset.pricingCostEnabled !== undefined) { const card = event.target.closest(".pricing-rule-target-card"); const controls = card?.querySelector('[data-pricing-target-controls="cost"]'); const label = event.target.closest("label")?.querySelector("span"); if (controls) controls.hidden = !event.target.checked; if (label) label.textContent = event.target.checked ? "On" : "Off"; return; }
        if (event.target.dataset.pricingCostDiscountEnabled !== undefined) { const controls = event.target.closest(".pricing-cost-discount")?.querySelector("[data-pricing-cost-discount-controls]"); if (controls) controls.hidden = !event.target.checked; return; }
        if (event.target.dataset.pricingCalculationSource !== undefined || String(event.target.name || "").endsWith("amount_unit")) { const form = event.target.closest("form"); if (form) syncCalculationForm(form); return; }
        if (event.target.dataset.mapField) { state.mapping[event.target.dataset.mapField] = event.target.value; state.mappingChanged = true; render(); return; }
        if (event.target.dataset.reviewMatch) {
          if (event.target.value === "") return;
          const payload = {run_id: state.runId, row_id: event.target.dataset.reviewMatch};
          if (event.target.value === "skip") payload.skipped = true;
          else payload.inventory_index = Number(event.target.value);
          await call("/api/pricing/review/update", payload); await loadReview(); render(); return;
        }
        if (event.target.dataset.reviewRow) { await call("/api/pricing/review/update", {run_id: state.runId, row_id: event.target.dataset.reviewRow, [event.target.dataset.reviewKind === "new" ? "approved_new" : "included"]: event.target.checked}); await loadReview(); render(); }
      } catch (error) { notify(error.message, "error"); }
    });
    root.addEventListener("submit", async event => { const form = event.target.closest("[data-pricing-form]"); if (!form) return; event.preventDefault(); try { if (form.dataset.pricingForm === "change-import-rule") await changeImportRule(form); else await saveRule(form); } catch (error) { notify(error.message, "error"); } });
  }
  window.initPricingCenterTab = function () { if (!state.initialized) { state.initialized = true; bind(); } loadData(); };
  window.PricingCenterPreview = Object.freeze({EXPORT_ROW_LIMIT, splitExportRows, buildExportPackage, snapshotFreshness});
})();
