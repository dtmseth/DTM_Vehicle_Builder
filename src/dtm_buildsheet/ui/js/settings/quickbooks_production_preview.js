// ═══════════════════════════════════════════════════════
// QUICKBOOKS — PRODUCTION CATALOG PREVIEW
//
// A deliberately narrow owner tool.  It uses only the isolated preview API:
// snapshot selection, production OAuth, a read-only Item pull, and a mapping
// report.  There is no customer, estimate, link, or catalog-write control.
// ═══════════════════════════════════════════════════════

(() => {
  "use strict";

  const BASE = "/api/quickbooks/production-preview";
  let _status = null;
  let _report = null;
  let _wired = false;

  const safe = (value) => (typeof esc === "function" ? esc(value == null ? "" : String(value)) : "");
  const fmt = (value) => Number(value || 0).toLocaleString();

  function _snapshotText(snapshot) {
    if (!snapshot) return "No baseline selected";
    const catalog = snapshot.catalog || {};
    return `${snapshot.name} · ${fmt(catalog.part_numbers)} part numbers · ${fmt(catalog.linked_part_numbers)} currently linked`;
  }

  function _renderStatus() {
    const s = _status || {};
    const button = $("qbpp-stab-button");
    const snapshots = s.snapshots || [];
    if (button) button.hidden = !snapshots.length;

    const select = $("qbpp-snapshot");
    if (select) {
      const selected = s.selected_snapshot?.name || "";
      select.innerHTML = ["<option value=\"\">Choose a saved baseline…</option>"]
        .concat(snapshots.map((snapshot) => {
          const catalog = snapshot.catalog || {};
          const label = `${snapshot.label || snapshot.name} — ${fmt(catalog.part_numbers)} part numbers`;
          return `<option value="${safe(snapshot.name)}"${snapshot.name === selected ? " selected" : ""}>${safe(label)}</option>`;
        }))
        .join("");
    }

    const status = $("qbpp-status");
    const connection = s.connection || {};
    if (status) {
      if (!s.selected_snapshot) status.textContent = "Choose a saved catalog baseline before production credentials can be used.";
      else if (!connection.configured) status.textContent = "Baseline protected. Add the separate production preview credentials when the relay is ready.";
      else if (!connection.connected) status.textContent = "Production preview is configured but not connected.";
      else status.textContent = `Connected to production preview · ${fmt(s.production_active_item_count)} active + ${fmt(s.production_inactive_item_count)} inactive items pulled · normal sync remains off`;
    }

    const detail = $("qbpp-snapshot-details");
    if (detail) detail.textContent = _snapshotText(s.selected_snapshot);
    if ($("qbpp-client-id")) $("qbpp-client-id").value = connection.client_id || "";
    if ($("qbpp-redirect-uri")) $("qbpp-redirect-uri").value = connection.redirect_uri || "";
    if ($("qbpp-client-secret")) {
      $("qbpp-client-secret").placeholder = connection.has_client_secret
        ? "•••••••• saved separately — leave blank to keep"
        : "Paste production client secret";
    }

    if ($("qbpp-connect")) $("qbpp-connect").disabled = !s.selected_snapshot || !connection.configured || connection.connected;
    if ($("qbpp-disconnect")) $("qbpp-disconnect").hidden = !connection.connected;
    if ($("qbpp-pull")) $("qbpp-pull").disabled = !s.selected_snapshot || !connection.connected;
    if ($("qbpp-mapping-field")) {
      $("qbpp-mapping-field").value = s.mapping_field || "";
      $("qbpp-mapping-field").disabled = !s.production_item_count;
    }
  }

  function _metric(label, value) {
    return `<div class="qbpp-metric"><span class="qbpp-metric-label">${safe(label)}</span><span class="qbpp-metric-value">${fmt(value)}</span></div>`;
  }

  function _exceptionText(item) {
    const kind = item.kind || "exception";
    if (kind === "ambiguous") return `Ambiguous: ${item.key} (${fmt(item.builder_count)} Builder entries, ${fmt(item.production_count)} production entries)`;
    if (kind === "builder_only") return `Builder only: ${item.builder_examples?.[0]?.part_number || item.key || "item"}`;
    if (kind === "pending_builder_item") return `Pending QB item not found in production: ${item.builder_examples?.[0]?.part_number || item.key || "item"}`;
    if (kind === "production_only") return `Production only: ${item.name || item.sku || item.qb_item_id || "unnamed item"}`;
    if (kind === "production_key_blank") return `No value in the selected QuickBooks column: ${item.name || item.qb_item_id || "unnamed item"}`;
    return kind;
  }

  function _renderReport() {
    const box = $("qbpp-report");
    const exceptions = $("qbpp-exceptions");
    const planRow = $("qbpp-plan-row");
    const report = _report?.report;
    if (!report) {
      if (box) box.innerHTML = "";
      if (exceptions) exceptions.innerHTML = "";
      if (planRow) planRow.hidden = true;
      return;
    }

    const fields = report.field_analysis || {};
    const name = fields.name || {};
    const sku = fields.sku || {};
    const selected = report.selected_summary || {};
    const historical = report.historical_link_summary || {};
    const selectedField = report.selected_mapping_field || "";
    if (box) {
      box.innerHTML = [
        _metric("Active production items", report.production_item_count),
        _metric("Inactive historical items", report.production_inactive_item_count),
        _metric("Name: exact matches", name.catalog_exact),
        _metric("SKU: exact matches", sku.catalog_exact),
        _metric("Known intentional exclusions", selected.intentionally_excluded || 0),
        historical.previously_linked_rows ? _metric("Prior links confidently matched", `${historical.matched_rows}/${historical.previously_linked_rows}`) : "",
        historical.inactive_matches ? _metric("Matched but inactive", historical.inactive_matches) : "",
        selectedField ? _metric("Selected-column blockers", report.selected_blocker_count) : "",
      ].join("");
    }
    const rows = report.selected_exceptions || [];
    if (exceptions) {
      if (!selectedField) {
        exceptions.textContent = "Choose the QuickBooks column after comparing the Name and SKU exact-match totals.";
      } else if (!rows.length) {
        exceptions.textContent = "No exceptions in the selected column. You can prepare an automatic mapping plan; it will still not make changes.";
      } else {
        const omitted = Math.max(0, Number(report.selected_exception_count || 0) - rows.length);
        exceptions.innerHTML = rows.map((item) => `<div class="qbpp-exception">${safe(_exceptionText(item))}</div>`).join("")
          + (omitted ? `<div class="qbpp-exception">${fmt(omitted)} more exceptions are retained in the local report.</div>` : "");
      }
    }
    if (planRow) planRow.hidden = !selectedField;
  }

  async function _refresh({ report = true } = {}) {
    try {
      _status = await api(`${BASE}/status`);
    } catch (_) {
      _status = null;
    }
    _renderStatus();
    if (report && _status?.production_item_count) {
      try {
        _report = await api(`${BASE}/report`);
      } catch (_) {
        _report = null;
      }
    } else {
      _report = null;
    }
    _renderReport();
  }

  async function _selectSnapshot() {
    const snapshotName = $("qbpp-snapshot")?.value || "";
    if (!snapshotName) { toast("Choose a saved catalog baseline first", "error"); return; }
    const result = await api(`${BASE}/select-snapshot`, { snapshot_name: snapshotName });
    if (!result?.ok) { toast("Could not select that catalog baseline", "error"); return; }
    toast("Catalog baseline selected", "success");
    await _refresh();
  }

  async function _createSnapshot() {
    const button = $("qbpp-create-snapshot");
    if (button) button.disabled = true;
    try {
      const label = $("qbpp-snapshot-label")?.value.trim() || "catalog-review";
      const result = await api(`${BASE}/create-snapshot`, { label });
      if (!result?.ok) { toast(result?.error || "Could not create catalog baseline", "error"); return; }
      if ($("qbpp-snapshot-label")) $("qbpp-snapshot-label").value = "";
      toast("New immutable catalog baseline created and selected", "success");
      await _refresh();
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function _saveSettings() {
    const payload = {
      client_id: $("qbpp-client-id")?.value.trim() || "",
      client_secret: $("qbpp-client-secret")?.value || "",
      redirect_uri: $("qbpp-redirect-uri")?.value.trim() || "",
    };
    if (!payload.client_id || !payload.redirect_uri) {
      toast("Production Client ID and HTTPS Redirect URI are required", "error");
      return;
    }
    const result = await api(`${BASE}/settings`, payload);
    if (!result?.ok) { toast(result?.error || "Could not save production preview settings", "error"); return; }
    if ($("qbpp-client-secret")) $("qbpp-client-secret").value = "";
    toast("Production preview settings saved separately", "success");
    await _refresh({ report: false });
  }

  async function _connect() {
    const result = await api(`${BASE}/auth-url`, {});
    if (!result?.ok || !result.url) { toast(result?.error || "Could not start production authorization", "error"); return; }
    window.location.href = result.url;
  }

  async function _disconnect() {
    if (!confirm("Disconnect the separate production preview? This does not affect sandbox QuickBooks.")) return;
    const result = await api(`${BASE}/disconnect`, {});
    if (!result?.ok) { toast(result?.error || "Could not disconnect production preview", "error"); return; }
    toast("Production preview disconnected", "success");
    await _refresh({ report: false });
  }

  async function _pull() {
    const button = $("qbpp-pull");
    if (button) button.disabled = true;
    try {
      const result = await api(`${BASE}/pull`, {});
      if (!result?.ok) { toast(result?.error || "Production catalog pull failed", "error"); return; }
      toast(`Pulled ${fmt(result.item_count)} production items into a separate comparison cache`, "success");
      await _refresh();
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function _selectMappingField() {
    const field = $("qbpp-mapping-field")?.value || "";
    if (!field) { _renderReport(); return; }
    const result = await api(`${BASE}/mapping-field`, { field });
    if (!result?.ok) { toast(result?.error || "Could not compare that column", "error"); return; }
    _report = result;
    _renderReport();
  }

  async function _preparePlan() {
    const result = await api(`${BASE}/prepare-plan`, {});
    if (!result?.ok) {
      toast(result?.error || "Could not prepare mapping plan", "error");
      return;
    }
    const exceptions = fmt(result.unresolved_exception_count);
    toast(`Prepared ${fmt(result.exact_match_count)} exact matches for later owner approval; ${exceptions} exceptions remain untouched`, "success");
  }

  function _wire() {
    if (_wired) return;
    _wired = true;
    $("qbpp-use-snapshot")?.addEventListener("click", _selectSnapshot);
    $("qbpp-create-snapshot")?.addEventListener("click", _createSnapshot);
    $("qbpp-save-settings")?.addEventListener("click", _saveSettings);
    $("qbpp-connect")?.addEventListener("click", _connect);
    $("qbpp-disconnect")?.addEventListener("click", _disconnect);
    $("qbpp-pull")?.addEventListener("click", _pull);
    $("qbpp-mapping-field")?.addEventListener("change", _selectMappingField);
    $("qbpp-prepare-plan")?.addEventListener("click", _preparePlan);
  }

  window.initQuickBooksProductionPreview = async function () {
    _wire();
    await _refresh();
  };

  window.qbProductionPreviewConsumeReturn = function () {
    const params = new URLSearchParams(window.location.search);
    if (params.get("qb") !== "production-preview-connected") return false;
    params.delete("qb");
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? `?${params}` : ""));
    toast("Production catalog preview connected", "success");
    if (typeof switchTab === "function") {
      switchTab("advanced-settings");
      setTimeout(() => $("qbpp-stab-button")?.click(), 0);
    }
    return true;
  };

  window.addEventListener("DOMContentLoaded", async () => {
    await _refresh({ report: false });
    window.qbProductionPreviewConsumeReturn();
  });
})();
