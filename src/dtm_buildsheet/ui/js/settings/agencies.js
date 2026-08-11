// Settings → Agencies tab
// Also owns the agency create/edit modal used from the project wizard.
(function () {
  let _agencies = [];
  let _editingId = null;
  let _pendingOnSuccess = null;
  let _listWired = false;
  let _preferenceLoadToken = 0;
  let _pricingRule = null;

  const _profileFields = [
    "contact_name", "contact_title", "contact_phone", "contact_email",
    "mobile_phone", "fax", "website",
    "bill_address_line1", "bill_address_line2", "bill_address_line3",
    "bill_city", "bill_state", "bill_postal_code", "bill_country",
    "ship_address_line1", "ship_address_line2", "ship_address_line3",
    "ship_city", "ship_state", "ship_postal_code", "ship_country",
    "notes",
  ];
  const _addressFields = ["address_line1", "address_line2", "address_line3", "city", "state", "postal_code", "country"];

  function _inputFor(field) {
    return $(`ac-${field.replaceAll("_", "-")}`);
  }

  function _shippingMatchesBilling(agency) {
    return _addressFields.some(field => agency?.[`bill_${field}`]) &&
      _addressFields.every(field => (agency?.[`bill_${field}`] || "") === (agency?.[`ship_${field}`] || ""));
  }

  function _copyBillingToShipping() {
    for (const field of _addressFields) {
      const bill = _inputFor(`bill_${field}`);
      const ship = _inputFor(`ship_${field}`);
      if (bill && ship) ship.value = bill.value;
    }
  }

  async function _populateDefaultPreferences(agency) {
    const token = ++_preferenceLoadToken;
    const options = await api("/api/project-options").catch(() => null);
    if (options && !options.error && window._PT) _PT.projectOptions = options;
    if (token !== _preferenceLoadToken || typeof _ptSetPreferenceForm !== "function") return;
    _ptSetPreferenceForm("ac", agency?.default_preferences || {});
  }

  async function _loadPricingRule() {
    if (_pricingRule?.discounts?.length) return _pricingRule;
    _pricingRule = await api("/api/quickbooks/customer-pricing").catch(() => null);
    return _pricingRule;
  }

  async function _populateAgencyPricing(agency) {
    const rule = await _loadPricingRule();
    const rows = rule?.discounts || [];
    const overrides = agency?.pricing_overrides || {};
    const useDefault = Object.keys(overrides).length === 0;
    const toggle = $("ac-pricing-use-default");
    const panel = $("ac-pricing-overrides");
    const box = $("ac-pricing-rows");
    if (toggle) toggle.checked = useDefault;
    if (panel) panel.hidden = useDefault;
    if (!box) return;
    box.innerHTML = rows.map((row) => {
      const value = Object.prototype.hasOwnProperty.call(overrides, row.manufacturer_id)
        ? overrides[row.manufacturer_id]
        : row.discount_percent;
      return `<div class="qb-pricing-row">
        <label for="ac-pricing-${escAttr(row.manufacturer_id)}">${esc(row.manufacturer)}</label>
        <input id="ac-pricing-${escAttr(row.manufacturer_id)}" type="number" min="0" max="100" step="0.1"
          value="${escAttr(value)}" data-agency-pricing="${escAttr(row.manufacturer_id)}"
          data-default-discount="${escAttr(row.discount_percent)}" />
        <span class="qb-pricing-percent">% off</span>
      </div>`;
    }).join("");
  }

  // Attribute-safe escape (also handles quotes, which the shared esc() does
  // not). Used for data-* attribute values rendered into HTML.
  const escAttr = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function _wireList() {
    if (_listWired) return;
    const container = $("agency-list-container");
    if (!container) return;
    _listWired = true;
    // Delegated so it survives innerHTML re-renders, and so agency names with
    // apostrophes/quotes can never break a handler (the old inline-onclick
    // string interpolation did — Sheriff's Office etc. became undeletable).
    container.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (!btn) return;
      const id = btn.getAttribute("data-id");
      if (btn.dataset.act === "edit") {
        agencyEdit(id);
      } else if (btn.dataset.act === "del") {
        const ag = _agencies.find(a => a.agency_id === id);
        agencyDelete(id, ag ? ag.name : "");
      }
    });
  }

  function _renderTable(list) {
    const container = $("agency-list-container");
    if (!container) return;
    _wireList();
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
                <button class="btn btn-secondary btn-sm" data-act="edit" data-id="${escAttr(a.agency_id)}">Edit</button>
                <button class="btn btn-secondary btn-sm" style="margin-left:4px;color:var(--red)" data-act="del" data-id="${escAttr(a.agency_id)}">Delete</button>
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
    for (const field of _profileFields) {
      const input = _inputFor(field);
      if (input) input.value = agency?.[field] || "";
    }
    $("ac-taxable").value       = agency?.taxable === true ? "true" : agency?.taxable === false ? "false" : "";
    $("ac-ship-same").checked   = _shippingMatchesBilling(agency);
    $("ac-since").value         = agency?.customer_since || "";
    _populateDefaultPreferences(agency);
    _populateAgencyPricing(agency);
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
  $("ac-ship-same")?.addEventListener("change", (event) => {
    if (event.target.checked) _copyBillingToShipping();
  });
  $("ac-pricing-use-default")?.addEventListener("change", (event) => {
    const panel = $("ac-pricing-overrides");
    if (panel) panel.hidden = event.target.checked;
  });

  $("ac-save")?.addEventListener("click", async () => {
    const name        = $("ac-name").value.trim();
    const contactName = $("ac-contact-name").value.trim();
    if (!name) { toast("Agency name is required", "error"); return; }
    if (!contactName) { toast("Contact name is required", "error"); return; }

    if ($("ac-ship-same")?.checked) _copyBillingToShipping();
    const payload = {
      name,
      contact_name:  contactName,
      contact_phone: $("ac-contact-phone").value.trim(),
      contact_email: $("ac-contact-email").value.trim(),
      customer_since: $("ac-since").value.trim(),
      taxable: $("ac-taxable").value === "" ? null : $("ac-taxable").value === "true",
      default_preferences: _ptPreferencePayload("ac"),
      pricing_overrides: {},
    };
    if (!$("ac-pricing-use-default")?.checked) {
      for (const input of document.querySelectorAll("[data-agency-pricing]")) {
        const value = Number(input.value);
        if (!Number.isFinite(value) || value < 0 || value > 100) {
          toast("Every customer discount must be from 0% through 100%", "error");
          input.focus();
          return;
        }
        const defaultValue = Number(input.getAttribute("data-default-discount"));
        if (value !== defaultValue) {
          payload.pricing_overrides[input.getAttribute("data-agency-pricing")] = value;
        }
      }
    }
    for (const field of _profileFields) {
      const input = _inputFor(field);
      if (input) payload[field] = input.value.trim();
    }
    if (_editingId) payload.agency_id = _editingId;
    const wasEditing = !!_editingId;

    // apiSave so the Phase 2-β proposal toast fires when cloud mode is on.
    const res = await apiSave("/api/agency/save", payload);
    if (res?.ok) {
      _closeModal();
      // Suppress the local-only "Agency updated" toast when a proposal toast
      // already fired — two stacked toasts are noisy.
      if (!res.proposed) {
        toast(wasEditing ? "Agency updated" : `Agency "${res.agency.name}" created`, "success");
      }
      if (_pendingOnSuccess) { _pendingOnSuccess(res.agency); _pendingOnSuccess = null; }
      await _load();
    } else {
      toast(res?.error || "Save failed", "error");
    }
  });
})();
