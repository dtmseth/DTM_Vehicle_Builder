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
    if (!items.length) {
      list.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--muted);text-align:center">No items pulled yet. Click "Pull items from QuickBooks".</div>';
      return;
    }
    // Unlinked first so the review queue is obvious. All QB-sourced strings
    // pass through esc() — QB data is never inserted as raw HTML.
    const sorted = items.slice().sort((a, b) => (a.linked === b.linked ? 0 : a.linked ? 1 : -1));
    list.innerHTML = sorted.map((it) => {
      const badge = it.linked
        ? '<span style="font-size:10px;font-weight:700;color:var(--green,#166534)">● linked</span>'
        : '<span style="font-size:10px;font-weight:700;color:var(--orange,#b45309)">● unlinked</span>';
      const sku = it.sku ? `<span style="color:var(--muted)">SKU ${esc(it.sku)}</span> · ` : "";
      const price = _money(it.unit_price);
      const priceHtml = price ? ` · <span style="color:var(--muted)">${esc(price)}</span>` : "";
      return (
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-bottom:1px solid var(--border);font-size:12px">' +
          '<div style="min-width:0">' +
            `<div style="font-weight:600;color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(it.name || "(unnamed)")}</div>` +
            `<div style="font-size:11px">${sku}${esc(it.type || "")}${priceHtml}</div>` +
          "</div>" +
          `<div style="flex:none">${badge}</div>` +
        "</div>"
      );
    }).join("");
  }

  async function _loadItems() {
    let data = null;
    try {
      data = await api("/api/quickbooks/items");
    } catch (e) {
      data = null;
    }
    _renderItems(data);
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
        toast(`Pulled ${res.item_count} item${res.item_count === 1 ? "" : "s"} (${res.unlinked} unlinked)`, "success");
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
