// Settings → Agencies tab
// Also owns the agency create/edit modal used from the project wizard.
(function () {
  let _agencies = [];
  let _editingId = null;
  let _pendingOnSuccess = null;

  function _renderTable(list) {
    const container = $("agency-list-container");
    if (!container) return;
    if (!list.length) {
      container.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0">No agencies yet. Add your first agency above.</p>`;
      return;
    }
    container.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:6px 8px">Name</th>
            <th style="text-align:left;padding:6px 8px">Contact</th>
            <th style="text-align:left;padding:6px 8px">Phone</th>
            <th style="text-align:left;padding:6px 8px">Email</th>
            <th style="text-align:left;padding:6px 8px">Since</th>
            <th style="padding:6px 8px"></th>
          </tr>
        </thead>
        <tbody>
          ${list.map(a => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:7px 8px;font-weight:600">${esc(a.name)}</td>
              <td style="padding:7px 8px">${esc(a.contact_name)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(a.contact_phone)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(a.contact_email)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(a.customer_since)}</td>
              <td style="padding:7px 8px;white-space:nowrap;text-align:right">
                <button class="btn btn-secondary btn-sm" onclick="agencyEdit('${esc(a.agency_id)}')">Edit</button>
                <button class="btn btn-secondary btn-sm" style="margin-left:4px;color:var(--red)" onclick="agencyDelete('${esc(a.agency_id)}','${esc(a.name)}')">Delete</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  }

  async function _load() {
    const res = await api("/api/agencies");
    _agencies = res?.agencies || [];
    _filterAndRender();
  }

  function _filterAndRender() {
    const q = ($("agency-search")?.value || "").toLowerCase();
    const filtered = q
      ? _agencies.filter(a =>
          a.name.toLowerCase().includes(q) ||
          (a.contact_name || "").toLowerCase().includes(q))
      : _agencies;
    _renderTable(filtered);
  }

  // ── public API ────────────────────────────────────────────────────────────────
  window.openAgencyModal = function (options = {}) {
    _pendingOnSuccess = options.onSuccess || null;
    _editingId = options.agencyId || null;
    const agency = _editingId ? _agencies.find(a => a.agency_id === _editingId) : null;

    $("ac-name").value          = agency?.name           || options.prefill || "";
    $("ac-contact-name").value  = agency?.contact_name   || "";
    $("ac-contact-phone").value = agency?.contact_phone  || "";
    $("ac-contact-email").value = agency?.contact_email  || "";
    $("ac-since").value         = agency?.customer_since || "";
    $("agency-create-modal").classList.add("open");
    setTimeout(() => $("ac-name").focus(), 50);
  };

  window.agencyEdit = function (agencyId) {
    openAgencyModal({ agencyId });
  };

  window.agencyDelete = async function (agencyId, name) {
    if (!confirm(`Delete agency "${name}"? This cannot be undone.`)) return;
    const res = await fetch(`/api/agency/${encodeURIComponent(agencyId)}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (data?.ok) {
      if (data.cloud_warning) toast(data.cloud_warning, "error");
      else toast(`Agency "${name}" deleted`, "success");
      await _load();
    } else {
      toast(data?.error || "Delete failed", "error");
    }
  };

  window.initAgenciesTab = async function () {
    await _load();
    $("btn-add-agency")?.addEventListener("click", () => openAgencyModal({}));
    $("agency-search")?.addEventListener("input", _filterAndRender);
  };
  // Called by the post-sync refresher so a teammate's deletion or save
  // becomes visible without restarting the app.
  window.refreshAgenciesTab = _load;

  // ── modal wiring — attached once at script load, before initAgenciesTab ──────
  function _closeModal() {
    $("agency-create-modal").classList.remove("open");
    _pendingOnSuccess = null;
    _editingId = null;
  }

  $("agency-create-close")?.addEventListener("click", _closeModal);
  $("ac-cancel")?.addEventListener("click", _closeModal);

  $("ac-save")?.addEventListener("click", async () => {
    const name        = $("ac-name").value.trim();
    const contactName = $("ac-contact-name").value.trim();
    if (!name) { toast("Agency name is required", "error"); return; }
    if (!contactName) { toast("Contact name is required", "error"); return; }

    const payload = {
      name,
      contact_name:  contactName,
      contact_phone: $("ac-contact-phone").value.trim(),
      contact_email: $("ac-contact-email").value.trim(),
      customer_since: $("ac-since").value.trim(),
    };
    if (_editingId) payload.agency_id = _editingId;

    // apiSave so the Phase 2-β proposal toast fires when cloud mode is on.
    const res = await apiSave("/api/agency/save", payload);
    if (res?.ok) {
      _closeModal();
      // Suppress the local-only "Agency updated" toast when a proposal toast
      // already fired — two stacked toasts are noisy.
      if (!res.proposed) {
        toast(_editingId ? "Agency updated" : `Agency "${res.agency.name}" created`, "success");
      }
      if (_pendingOnSuccess) { _pendingOnSuccess(res.agency); _pendingOnSuccess = null; }
      await _load();
    } else {
      toast(res?.error || "Save failed", "error");
    }
  });
})();
