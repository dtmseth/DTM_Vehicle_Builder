// Settings → General → QuickBooks
//
// Connection card + collapsible app-registration form. Talks to the
// /api/quickbooks/* routes. Secrets are never rendered back into fields —
// the Client Secret shows only a "saved" placeholder once stored.
//
// OAuth round-trip: clicking Connect navigates the app window to Intuit's
// consent page; the callback redirects back to /?qb=connected|error, which
// main.js hands to qbConsumeReturnTab() on load.
(function () {
  let _wired = false;
  let _status = null;
  let _catalogLoaded = false;
  let _productLabelById = {};
  let _products = [];          // [{id, label, search}]
  let _linkingItemId = null;   // qb_item_id currently being linked
  let _lastItems = [];         // last rendered item list (for the link button)

  function _fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function _render() {
    const s = _status || {};

    const badge = $("qb-status-badge");
    if (badge) {
      if (s.connected) {
        badge.textContent = "● Connected";
        badge.style.color = "var(--green,#166534)";
      } else if (s.configured) {
        badge.textContent = "● Not connected";
        badge.style.color = "var(--orange,#b45309)";
      } else {
        badge.textContent = "● Not configured";
        badge.style.color = "var(--muted)";
      }
    }

    // App-registration form (never echo the secret).
    if ($("qb-client-id")) $("qb-client-id").value = s.client_id || "";
    if ($("qb-environment")) $("qb-environment").value = s.environment || "production";
    if ($("qb-redirect-uri")) $("qb-redirect-uri").value = s.redirect_uri || "";
    const secretInput = $("qb-client-secret");
    if (secretInput) {
      secretInput.placeholder = s.has_client_secret
        ? "•••••••• saved — leave blank to keep"
        : "Paste client secret";
    }

    // Connection panels.
    if ($("qb-connected-panel")) $("qb-connected-panel").hidden = !s.connected;
    if ($("qb-connect-row")) $("qb-connect-row").hidden = !!s.connected;
    if ($("qb-connect-btn")) $("qb-connect-btn").disabled = !s.configured;
    if ($("qb-connect-hint")) $("qb-connect-hint").hidden = !!s.configured;
    if ($("qb-sync-panel")) $("qb-sync-panel").hidden = !s.connected;
    if ($("qb-customers-panel")) $("qb-customers-panel").hidden = !s.connected;

    if (s.connected) {
      if ($("qb-token-renews")) $("qb-token-renews").textContent = _fmtDate(s.refresh_expiry_utc);
      if ($("qb-hard-expiry")) $("qb-hard-expiry").textContent = _fmtDate(s.hard_expiry_utc);
      if ($("qb-environment-label")) $("qb-environment-label").textContent = s.environment || "production";
    }
  }

  function _fmtDateTime(iso) {
    if (!iso) return "never";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "never";
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function _money(n) {
    if (n === null || n === undefined || n === "") return "";
    const v = Number(n);
    if (isNaN(v)) return "";
    return "$" + v.toFixed(2);
  }

  function _renderItems(data) {
    const d = data || {};
    if ($("qb-last-sync")) $("qb-last-sync").textContent = _fmtDateTime(d.last_sync_utc);
    if ($("qb-item-count")) $("qb-item-count").textContent = d.item_count || 0;
    if ($("qb-linked-count")) $("qb-linked-count").textContent = d.linked || 0;
    if ($("qb-unlinked-count")) $("qb-unlinked-count").textContent = d.unlinked || 0;

    const list = $("qb-items-list");
    if (!list) return;
    const items = d.items || [];
    _lastItems = items;
    if (!items.length) {
      list.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--muted);text-align:center">No items pulled yet. Click "Pull items from QuickBooks".</div>';
      return;
    }
    // Unlinked first so the review queue is obvious. All QB-sourced strings
    // pass through esc() — QB data is never inserted as raw HTML.
    const sorted = items.slice().sort((a, b) => (a.linked === b.linked ? 0 : a.linked ? 1 : -1));
    list.innerHTML = sorted.map((it) => {
      const id = esc(it.qb_item_id || "");
      const sku = it.sku ? `<span style="color:var(--muted)">SKU ${esc(it.sku)}</span> · ` : "";
      const price = _money(it.unit_price);
      const priceHtml = price ? ` · <span style="color:var(--muted)">${esc(price)}</span>` : "";
      // QBO items are named by part number, so lead with the Sales Description
      // (when present) and demote the part number to the detail line.
      const desc = (it.description || "").trim();
      const partNo = esc(it.name || "(unnamed)");
      const primary = desc ? esc(desc) : partNo;
      const partNoHtml = desc ? `<span style="color:var(--muted)">${partNo}</span> · ` : "";
      let action;
      if (it.linked) {
        const partLabel = _productLabelById[it.linked_product_id] || it.linked_product_id || "part";
        action =
          `<span style="font-size:10px;font-weight:700;color:var(--green,#166534)">● ${esc(partLabel)}</span>` +
          `<button class="btn btn-secondary btn-sm" data-qb-unlink="${id}" style="margin-left:8px">Unlink</button>`;
      } else {
        action = `<button class="btn btn-secondary btn-sm" data-qb-link="${id}">🔗 Link</button>`;
      }
      return (
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-bottom:1px solid var(--border);font-size:12px">' +
          '<div style="min-width:0">' +
            `<div style="font-weight:600;color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${primary}</div>` +
            `<div style="font-size:11px">${partNoHtml}${sku}${esc(it.type || "")}${priceHtml}</div>` +
          "</div>" +
          `<div style="flex:none;display:flex;align-items:center;white-space:nowrap">${action}</div>` +
        "</div>"
      );
    }).join("");
  }

  async function _ensureCatalog() {
    if (_catalogLoaded) return;
    try {
      const [prodRes, mfgRes] = await Promise.all([
        api("/api/parts-db/products"),
        api("/api/parts-db/manufacturers"),
      ]);
      const mfgLabel = {};
      (mfgRes?.manufacturers || []).forEach((m) => { mfgLabel[m.manufacturer_id] = m.label; });
      _products = (prodRes?.products || []).map((p) => {
        const mfg = mfgLabel[p.manufacturer_id] || p.manufacturer_id || "";
        const label = [mfg, p.model].filter(Boolean).join(" ") || p.product_id;
        return { id: p.product_id, label, search: (label + " " + p.product_id).toLowerCase() };
      });
      _productLabelById = {};
      _products.forEach((p) => { _productLabelById[p.id] = p.label; });
      _catalogLoaded = true;
    } catch (e) {
      _products = [];
    }
  }

  async function _loadItems() {
    await _ensureCatalog();
    let data = null;
    try {
      data = await api("/api/quickbooks/items");
    } catch (e) {
      data = null;
    }
    _renderItems(data);
  }

  // ── link picker modal ──────────────────────────────────────────────────

  function _openLinkModal(qbItemId, itemName) {
    _linkingItemId = qbItemId;
    if ($("qb-link-item-name")) $("qb-link-item-name").textContent = itemName || qbItemId;
    if ($("qb-link-search")) $("qb-link-search").value = "";
    _renderLinkResults("");
    $("qb-link-modal")?.classList.add("open");
    setTimeout(() => $("qb-link-search")?.focus(), 0);
  }

  function _closeLinkModal() {
    _linkingItemId = null;
    $("qb-link-modal")?.classList.remove("open");
  }

  function _renderLinkResults(filter) {
    const box = $("qb-link-results");
    if (!box) return;
    const q = (filter || "").trim().toLowerCase();
    const matches = (q ? _products.filter((p) => p.search.includes(q)) : _products).slice(0, 100);
    if (!matches.length) {
      box.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--muted);text-align:center">No matching parts.</div>';
      return;
    }
    box.innerHTML = matches.map((p) =>
      '<div class="qb-link-row" data-qb-pick="' + esc(p.id) + '" ' +
        'style="padding:8px 10px;border-bottom:1px solid var(--border);font-size:12px;cursor:pointer">' +
        `<span style="font-weight:600;color:var(--navy)">${esc(p.label)}</span>` +
        `<span style="color:var(--muted);margin-left:6px;font-size:11px">${esc(p.id)}</span>` +
      "</div>"
    ).join("");
  }

  async function _doLink(productId) {
    if (!_linkingItemId || !productId) return;
    const res = await api("/api/quickbooks/link-item", { qb_item_id: _linkingItemId, product_id: productId });
    if (res?.ok) {
      toast("Linked to " + (_productLabelById[productId] || productId), "success");
      _closeLinkModal();
      await _loadItems();
    } else {
      toast(_linkError(res?.error), "error");
    }
  }

  async function _doUnlink(qbItemId) {
    const res = await api("/api/quickbooks/unlink-item", { qb_item_id: qbItemId });
    if (res?.ok) {
      toast("Unlinked", "success");
      await _loadItems();
    } else {
      toast(res?.error || "Unlink failed", "error");
    }
  }

  function _linkError(code) {
    if (code === "item_already_linked") return "That QuickBooks item is already linked to another part";
    if (code === "product_already_linked") return "That part is already linked to a different QuickBooks item";
    if (code === "unknown_product") return "Part not found";
    if (code === "unknown_item") return "Item not found — re-pull from QuickBooks";
    return "Link failed: " + (code || "unknown error");
  }

  async function _sync() {
    const btn = $("qb-sync-btn");
    const spinner = $("qb-sync-spinner");
    const label = $("qb-sync-label");
    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline-block";
    if (label) label.textContent = "Pulling…";
    try {
      const res = await api("/api/quickbooks/sync", {});
      if (res?.ok) {
        let msg = `Pulled ${res.item_count} item${res.item_count === 1 ? "" : "s"} (${res.unlinked} unlinked)`;
        const r = res.reconciled;
        if (r && (r.updated || r.flagged_inactive)) {
          const bits = [];
          if (r.updated) bits.push(`${r.updated} part${r.updated === 1 ? "" : "s"} updated`);
          if (r.flagged_inactive) bits.push(`${r.flagged_inactive} flagged inactive`);
          msg += " · " + bits.join(", ");
        }
        toast(msg, "success");
        await _loadItems();
      } else {
        toast(_syncError(res?.error), "error");
      }
    } catch (e) {
      toast("Sync failed", "error");
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.style.display = "none";
      if (label) label.textContent = "🔄 Pull items from QuickBooks";
    }
  }

  function _syncError(code) {
    if (code === "not_connected") return "Not connected to QuickBooks";
    if (code === "no_realm_id") return "No company linked — reconnect to QuickBooks";
    return "Sync failed: " + (code || "unknown error");
  }

  async function _pullCustomers() {
    const btn = $("qb-customers-btn");
    const spinner = $("qb-customers-spinner");
    const label = $("qb-customers-label");
    const busy = (on) => {
      if (btn) btn.disabled = on;
      if (spinner) spinner.style.display = on ? "inline-block" : "none";
      if (label) label.textContent = on ? "Checking…" : "⬇️ Pull customers from QuickBooks";
    };
    busy(true);
    try {
      const pre = await api("/api/quickbooks/customers/preview");
      if (!pre?.ok) { toast(_syncError(pre?.error), "error"); return; }
      if (!pre.total) { toast("No customers found in QuickBooks", "success"); return; }
      const ok = confirm(
        `QuickBooks has ${pre.total} customer${pre.total === 1 ? "" : "s"}.\n\n` +
        `${pre.would_create} new agenc${pre.would_create === 1 ? "y" : "ies"} will be created, ` +
        `${pre.would_update} will be updated/linked.\n\n` +
        `This only pulls customer profiles into the app; it does not create estimates, invoices, or customer messages.\n\nImport now?`
      );
      if (!ok) return;
      if (label) label.textContent = "Importing…";
      const res = await api("/api/quickbooks/customers/import", {});
      if (res?.ok) {
        toast(`Imported: ${res.created} created, ${res.updated} updated`, "success");
        // Refresh the agencies tab if it's loaded so the new records show.
        if (typeof initAgenciesTab === "function") { try { initAgenciesTab(); } catch (e) {} }
      } else {
        toast(_syncError(res?.error), "error");
      }
    } catch (e) {
      toast("Customer import failed", "error");
    } finally {
      busy(false);
    }
  }

  async function _load() {
    try {
      _status = await api("/api/quickbooks/status");
    } catch (e) {
      _status = null;
    }
    _render();
    if (_status?.connected) await _loadItems();
  }

  async function _saveSettings() {
    const payload = {
      client_id: $("qb-client-id").value.trim(),
      client_secret: $("qb-client-secret").value, // blank = keep existing
      environment: $("qb-environment").value,
      redirect_uri: $("qb-redirect-uri").value.trim(),
    };
    if (!payload.client_id) { toast("Client ID is required", "error"); return; }
    if (!payload.redirect_uri) { toast("Redirect URI is required", "error"); return; }

    const res = await api("/api/quickbooks/settings", payload);
    if (res?.ok) {
      $("qb-client-secret").value = ""; // never retain the secret in the field
      _status = res;
      _render();
      toast("QuickBooks settings saved", "success");
    } else {
      toast(res?.error || "Save failed", "error");
    }
  }

  async function _connect() {
    const res = await api("/api/quickbooks/auth-url");
    if (res?.ok && res.url) {
      // Navigate the app window to Intuit's consent page. The OAuth redirect
      // chain returns to /api/quickbooks/callback which 302s back to /?qb=…
      window.location.href = res.url;
    } else {
      toast(res?.error || "Could not start authorization", "error");
    }
  }

  async function _disconnect() {
    if (!confirm("Disconnect from QuickBooks? You'll need to reconnect to sync again.")) return;
    const res = await api("/api/quickbooks/disconnect", {});
    if (res?.ok) {
      toast("Disconnected from QuickBooks", "success");
      await _load();
    } else {
      toast(res?.error || "Disconnect failed", "error");
    }
  }

  function _wire() {
    if (_wired) return;
    _wired = true;
    $("qb-save-settings")?.addEventListener("click", _saveSettings);
    $("qb-connect-btn")?.addEventListener("click", _connect);
    $("qb-disconnect-btn")?.addEventListener("click", _disconnect);
    $("qb-sync-btn")?.addEventListener("click", _sync);
    $("qb-customers-btn")?.addEventListener("click", _pullCustomers);

    // Delegated link/unlink buttons on the item list.
    $("qb-items-list")?.addEventListener("click", (e) => {
      const linkBtn = e.target.closest("[data-qb-link]");
      if (linkBtn) {
        const id = linkBtn.getAttribute("data-qb-link");
        const item = (_lastItems || []).find((it) => it.qb_item_id === id);
        _openLinkModal(id, item?.name);
        return;
      }
      const unlinkBtn = e.target.closest("[data-qb-unlink]");
      if (unlinkBtn) _doUnlink(unlinkBtn.getAttribute("data-qb-unlink"));
    });

    // Link picker modal.
    $("qb-link-close")?.addEventListener("click", _closeLinkModal);
    $("qb-link-cancel")?.addEventListener("click", _closeLinkModal);
    $("qb-link-search")?.addEventListener("input", (e) => _renderLinkResults(e.target.value));
    $("qb-link-results")?.addEventListener("click", (e) => {
      const row = e.target.closest("[data-qb-pick]");
      if (row) _doLink(row.getAttribute("data-qb-pick"));
    });
    $("qb-link-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "qb-link-modal") _closeLinkModal();
    });
  }

  // Called by tabs.js when the QuickBooks stab is shown.
  window.initQuickBooksTab = async function () {
    _wire();
    await _load();
  };

  // Called by main.js at startup. Returns true if we handled an OAuth
  // return (so startup skips the default Projects tab and lands here).
  window.qbConsumeReturnTab = function () {
    const params = new URLSearchParams(window.location.search);
    const qb = params.get("qb");
    if (!qb) return false;

    if (qb === "connected") toast("QuickBooks connected", "success");
    else toast("QuickBooks authorization failed", "error");

    // Strip the param so a manual refresh doesn't re-toast.
    params.delete("qb");
    const clean = window.location.pathname + (params.toString() ? "?" + params.toString() : "");
    window.history.replaceState({}, "", clean);

    if (typeof switchTab === "function") {
      switchTab("general-settings");
      setTimeout(() => document.querySelector('.stab[data-stab="quickbooks"]')?.click(), 0);
    }
    return true;
  };
})();
