// Settings → Shopmonkey: secure key setup, guarded catalog writes, and cleanup review.
(function () {
  let _wired = false;
  let _customers = [];
  let _inventory = [];
  let _pricingConfig = null;
  let _pricingLoaded = false;
  let _pricingReferences = { customer_labels: [], brands: [] };

  const _vendorGuideRules = {
    "Gamber Johnson": [["retail", "discount", 30], ["retail", "discount", 40]],
    "Kussmaul": [["retail", "discount", 10], ["retail", "discount", 10]],
    "NightRide": [["cost", "markup", 25], ["cost", "markup", 25]],
    "PAC Tool Mounts": [["retail", "discount", 5], ["retail", "discount", 5]],
    "Patrol PC": [["retail", "discount", 26], ["retail", "discount", 26]],
    "REDARC": [["retail", "discount", 10], ["retail", "discount", 10]],
    "Santa Cruz Gunlocks": [["retail", "discount", 25], ["retail", "discount", 25]],
    "Setina": [["retail", "discount", 20], ["retail", "discount", 30]],
    "SoundOff Signal": [["retail", "discount", 45], ["retail", "discount", 45]],
    "TigerTough": [["retail", "discount", 10], ["retail", "discount", 10]],
    "TruckVault": [["retail", "discount", 10], ["retail", "discount", 10]],
    "Whelen": [["retail", "discount", 36], ["retail", "discount", 43]],
  };
  const _westinBrands = new Set([
    "Brute", "Fey", "Superwinch", "SW Military", "Westin", "Westin Public Safety",
  ]);

  const attr = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function _canManageCredential() {
    return typeof appHasCapability === "function" && appHasCapability("settings.advanced.manage");
  }

  function _setBusy(button, busy, busyLabel) {
    if (!button) return;
    if (busy) button.dataset.originalLabel = button.textContent;
    button.disabled = busy;
    button.textContent = busy ? busyLabel : (button.dataset.originalLabel || button.textContent);
  }

  function _formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
  }

  function _renderStatus(status) {
    const connected = !!status?.connected;
    const badge = $("shopmonkey-status-badge");
    if (badge) {
      badge.textContent = connected ? "● Connected" : "● Not connected";
      badge.classList.toggle("is-connected", connected);
    }
    if ($("shopmonkey-connected-panel")) $("shopmonkey-connected-panel").hidden = !connected;
    if ($("shopmonkey-cleanup-card")) $("shopmonkey-cleanup-card").hidden = !connected;
    if ($("shopmonkey-pricing-card")) $("shopmonkey-pricing-card").hidden = !connected;

    const canManage = _canManageCredential();
    if ($("shopmonkey-inventory-card")) {
      $("shopmonkey-inventory-card").hidden = !connected || !canManage;
    }
    if ($("shopmonkey-line-break-card")) {
      $("shopmonkey-line-break-card").hidden = !connected || !canManage;
    }
    if ($("shopmonkey-credentials-panel")) {
      $("shopmonkey-credentials-panel").hidden = !canManage || connected;
    }
    if ($("shopmonkey-admin-hint")) {
      $("shopmonkey-admin-hint").hidden = canManage || connected;
    }
    if ($("shopmonkey-disconnect-btn")) $("shopmonkey-disconnect-btn").hidden = !canManage;
    if ($("shopmonkey-pricing-save")) $("shopmonkey-pricing-save").hidden = !canManage;
    if ($("shopmonkey-add-customer-type")) $("shopmonkey-add-customer-type").hidden = !canManage;
    if ($("shopmonkey-load-vendor-guide")) $("shopmonkey-load-vendor-guide").hidden = !canManage;
    const verified = _formatDate(status?.verified_at);
    if ($("shopmonkey-verified-at")) {
      $("shopmonkey-verified-at").textContent = verified ? `Last verified ${verified}` : "";
    }
  }

  async function _loadStatus() {
    const status = await api("/api/shopmonkey/status");
    _renderStatus(status);
    if (status?.connected && !_pricingLoaded) await _loadPricing();
    return status;
  }

  function _rowId(prefix) {
    if (globalThis.crypto?.randomUUID) return `${prefix}-${globalThis.crypto.randomUUID()}`;
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function _starterPricingConfig() {
    return {
      schema_version: 2, revision: "", updated_at: "", enabled: false, mode: "test",
      test_order_id: "", max_line_age_seconds: 600, preserve_custom_prices: true,
      customer_types: [
        { id: "retail", name: "Retail", label: "$ Retail $", label_id: "", enabled: true },
        { id: "wholesale", name: "Wholesale", label: "$ Wholesale $", label_id: "", enabled: true },
      ],
      rules: [
        { id: "whelen-retail", brand: "Whelen", brand_id: "", customer_type_id: "retail", basis: "retail", operation: "discount", percent: 36, enabled: true },
        { id: "whelen-wholesale", brand: "Whelen", brand_id: "", customer_type_id: "wholesale", basis: "retail", operation: "discount", percent: 43, enabled: true },
      ],
    };
  }

  function _referenceRows(kind) {
    return kind === "label" ? _pricingReferences.customer_labels : _pricingReferences.brands;
  }

  function _resolveReference(kind, name, preferredId = "") {
    const rows = _referenceRows(kind);
    const byId = rows.find(row => row.id === preferredId);
    if (byId) return byId;
    const normalized = String(name || "").trim().toLocaleLowerCase();
    return rows.find(row => String(row.name || "").trim().toLocaleLowerCase() === normalized) || null;
  }

  function _renderReferenceChoices() {
    if ($("shopmonkey-pricing-choice-count")) {
      $("shopmonkey-pricing-choice-count").textContent =
        `${_pricingReferences.customer_labels.length} customer labels · ${_pricingReferences.brands.length} part brands`;
    }
  }

  function _tagColor(value) {
    const allowed = new Set(["aqua", "black", "blue", "brown", "gray", "green", "orange", "purple", "red", "yellow"]);
    const color = String(value || "").toLocaleLowerCase();
    return allowed.has(color) ? color : "gray";
  }

  function _referenceDisplay(kind, row) {
    if (!row) return `<span class="shopmonkey-picker-placeholder">Select from Shopmonkey</span>`;
    if (kind === "label") {
      return `<span class="shopmonkey-provider-tag shopmonkey-provider-tag--${_tagColor(row.color)}"><span></span>${esc(row.name)}</span>`;
    }
    return `<span class="shopmonkey-brand-choice"><span class="shopmonkey-brand-mark">${esc(String(row.name || "?").slice(0, 1).toUpperCase())}</span><span><strong>${esc(row.name)}</strong><small>Part brand</small></span></span>`;
  }

  function _referenceOptions(kind, selectedId, query = "") {
    const normalizedQuery = String(query || "").trim().toLocaleLowerCase();
    const rows = _referenceRows(kind).filter(row => (
      !normalizedQuery || row.name.toLocaleLowerCase().includes(normalizedQuery)
    ));
    if (!rows.length) return `<div class="shopmonkey-picker-empty">No matching Shopmonkey ${kind === "label" ? "labels" : "brands"}</div>`;
    return rows.map(row => `<button class="shopmonkey-picker-option${row.id === selectedId ? " is-selected" : ""}" type="button" data-reference-option="${attr(row.id)}">${_referenceDisplay(kind, row)}<span class="shopmonkey-picker-check">✓</span></button>`).join("");
  }

  function _referencePicker(kind, field, value, referenceId, label) {
    const resolved = _resolveReference(kind, value, referenceId);
    return `<div class="shopmonkey-reference-picker${resolved ? "" : " is-invalid"}" data-reference-picker="${kind}">` +
      `<input type="hidden" data-field="${field}" value="${attr(resolved?.id || "")}">` +
      `<button class="shopmonkey-picker-trigger" type="button" data-reference-trigger aria-label="${attr(label)}" aria-expanded="false">${_referenceDisplay(kind, resolved)}<span class="shopmonkey-picker-chevron">⌄</span></button>` +
      `<div class="shopmonkey-picker-menu" data-reference-menu hidden>` +
      `<div class="shopmonkey-picker-search"><span>⌕</span><input type="search" data-reference-search placeholder="Search ${kind === "label" ? `${_referenceRows(kind).length} customer labels` : `${_referenceRows(kind).length} part brands`}…" aria-label="Search ${attr(label)}"></div>` +
      `<div class="shopmonkey-picker-meta">${_referenceRows(kind).length} Shopmonkey ${kind === "label" ? "Customer labels" : "Part brands"}</div>` +
      `<div class="shopmonkey-picker-options" data-reference-options>${_referenceOptions(kind, resolved?.id || "")}</div>` +
      `</div></div>`;
  }

  function _guideRuleValues(brandName) {
    if (_westinBrands.has(brandName)) {
      return [["retail", "discount", 15], ["cost", "markup", 25]];
    }
    return _vendorGuideRules[brandName] || null;
  }

  function _guideRuleId(brandName, customerTypeId) {
    const slug = String(brandName || "brand").toLocaleLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return `${slug}-${customerTypeId}`;
  }

  function _loadVendorGuideRules() {
    if (!_pricingConfig) return;
    const retailLabel = _resolveReference("label", "$ Retail $");
    const wholesaleLabel = _resolveReference("label", "$ Wholesale $");
    if (!retailLabel || !wholesaleLabel) {
      _showPricingErrors(["Create the $ Retail $ and $ Wholesale $ Customer labels in Shopmonkey, then refresh choices."]);
      return;
    }
    const candidate = _readPricingFromDom();
    const existingTypes = candidate.customer_types || [];
    const findType = (id, labelName) => existingTypes.find(row => (
      row.id === id || row.label === labelName || row.name?.toLocaleLowerCase() === id
    ));
    const retailType = findType("retail", "$ Retail $") || { id: "retail" };
    const wholesaleType = findType("wholesale", "$ Wholesale $") || { id: "wholesale" };
    Object.assign(retailType, {
      name: "Retail", label: retailLabel.name, label_id: retailLabel.id, enabled: true,
    });
    Object.assign(wholesaleType, {
      name: "Wholesale", label: wholesaleLabel.name, label_id: wholesaleLabel.id, enabled: true,
    });
    const replacedTypeIds = new Set([retailType.id, wholesaleType.id]);
    const preservedTypes = existingTypes.filter(row => !replacedTypeIds.has(row.id));
    const preservedRules = (candidate.rules || []).filter(row => !replacedTypeIds.has(row.customer_type_id));
    const rules = [];
    let pending = 0;
    _pricingReferences.brands.forEach(brand => {
      const values = _guideRuleValues(brand.name);
      if (!values) pending += 1;
      [[retailType.id, values?.[0]], [wholesaleType.id, values?.[1]]].forEach(([customerTypeId, rule]) => {
        rules.push({
          id: _guideRuleId(brand.name, customerTypeId),
          brand_id: brand.id,
          brand: brand.name,
          customer_type_id: customerTypeId,
          basis: rule?.[0] || "retail",
          operation: rule?.[1] || "discount",
          percent: rule?.[2] || 0,
          enabled: !!rule,
        });
      });
    });
    _pricingConfig = {
      ...candidate,
      mode: "test",
      customer_types: [retailType, wholesaleType, ...preservedTypes],
      rules: [...rules, ...preservedRules],
    };
    _showPricingErrors([]);
    _renderPricing();
    toast(
      `Loaded ${rules.length} test-mode rules from the DTM guide${pending ? `; ${pending} brands need review and remain disabled` : ""}. Review, then save.`,
      "success",
    );
  }

  function _closeReferencePickers(except = null) {
    document.querySelectorAll("[data-reference-picker]").forEach(picker => {
      if (picker === except) return;
      const menu = picker.querySelector("[data-reference-menu]");
      const trigger = picker.querySelector("[data-reference-trigger]");
      if (menu) menu.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function _filterReferencePicker(input) {
    const picker = input.closest("[data-reference-picker]");
    const options = picker?.querySelector("[data-reference-options]");
    const selectedId = picker?.querySelector("input[data-field]")?.value || "";
    if (picker && options) {
      options.innerHTML = _referenceOptions(picker.dataset.referencePicker, selectedId, input.value);
    }
  }

  function _renderPricingHealth(health, persisted) {
    const badge = $("shopmonkey-pricing-health");
    if (!badge) return;
    let label = "● Setup required";
    let connected = false;
    if (health?.ok) {
      label = _pricingConfig?.mode === "production" ? "● Production healthy" : "● Test mode healthy";
      connected = true;
    } else if (persisted && _pricingConfig?.enabled === false) {
      label = "● Disabled";
    } else if (persisted) {
      label = "● Hosted check pending";
    }
    badge.textContent = label;
    badge.classList.toggle("is-connected", connected);
    badge.classList.toggle("is-warning", !connected && !!persisted);
  }

  function _renderPriceRule(row) {
    return `<div class="shopmonkey-brand-rule" data-pricing-rule="${attr(row.id)}">` +
      `<div class="shopmonkey-brand-rule-head">` +
      `<label class="shopmonkey-toggle"><input data-field="enabled" type="checkbox"${row.enabled !== false ? " checked" : ""}><span></span><em>Rule enabled</em></label>` +
      `<button class="shopmonkey-icon-button" type="button" data-remove-price-rule="${attr(row.id)}" aria-label="Remove price rule">×</button></div>` +
      `<div class="shopmonkey-brand-rule-grid">` +
      `<label class="shopmonkey-field shopmonkey-field--brand"><span>Shopmonkey brand</span>${_referencePicker("brand", "brand_id", row.brand, row.brand_id, "Shopmonkey Part brand")}</label>` +
      `<label class="shopmonkey-field"><span>Price basis</span><select data-field="basis" aria-label="Price basis"><option value="retail"${row.basis !== "cost" ? " selected" : ""}>Inventory Retail (MSRP)</option><option value="cost"${row.basis === "cost" ? " selected" : ""}>Inventory Cost</option></select></label>` +
      `<label class="shopmonkey-field"><span>Adjustment</span><select data-field="operation" aria-label="Adjustment"><option value="discount"${row.operation !== "markup" ? " selected" : ""}>Discount</option><option value="markup"${row.operation === "markup" ? " selected" : ""}>Markup</option></select></label>` +
      `<label class="shopmonkey-field"><span>Percent</span><div class="shopmonkey-percent-input"><input data-field="percent" type="number" min="0" max="500" step="0.001" value="${attr(row.percent)}" aria-label="Percent"><span>%</span></div></label>` +
      `</div></div>`;
  }

  function _renderCustomerTypeCard(row) {
    const rules = (_pricingConfig.rules || []).filter(rule => rule.customer_type_id === row.id);
    return `<section class="shopmonkey-customer-rule-card${row.enabled === false ? " is-disabled" : ""}" data-pricing-customer-type="${attr(row.id)}">` +
      `<div class="shopmonkey-customer-rule-head">` +
      `<div><span class="shopmonkey-card-kicker">Customer type</span><strong>${esc(row.name || "New customer type")}</strong></div>` +
      `<div class="shopmonkey-customer-rule-actions"><label class="shopmonkey-toggle"><input data-field="enabled" type="checkbox"${row.enabled !== false ? " checked" : ""}><span></span><em>Enabled</em></label><button class="shopmonkey-icon-button" type="button" data-remove-customer-type="${attr(row.id)}" aria-label="Remove customer type">×</button></div>` +
      `</div>` +
      `<div class="shopmonkey-customer-rule-identity">` +
      `<label class="shopmonkey-field"><span>Display name</span><input data-field="name" value="${attr(row.name)}" maxlength="80" aria-label="Customer type name"></label>` +
      `<label class="shopmonkey-field"><span>Shopmonkey Customer label</span>${_referencePicker("label", "label_id", row.label, row.label_id, "Shopmonkey Customer label")}</label>` +
      `</div>` +
      `<div class="shopmonkey-card-divider"></div>` +
      `<div class="shopmonkey-brand-rules-head"><div><strong>Brand pricing rules</strong><span>${rules.length} ${rules.length === 1 ? "brand" : "brands"} configured for ${esc(row.name || "this customer type")}</span></div><button class="shopmonkey-add-rule-button" type="button" data-add-price-rule="${attr(row.id)}">+ Add brand rule</button></div>` +
      `<div class="shopmonkey-brand-rules">${rules.length ? rules.map(_renderPriceRule).join("") : `<div class="shopmonkey-empty-rules">No brand rules yet. Add a Shopmonkey brand to define this customer type’s price.</div>`}</div>` +
      `</section>`;
  }

  function _renderPricing() {
    if (!_pricingConfig) return;
    if ($("shopmonkey-pricing-enabled")) $("shopmonkey-pricing-enabled").checked = _pricingConfig.enabled !== false;
    if ($("shopmonkey-pricing-mode")) $("shopmonkey-pricing-mode").value = _pricingConfig.mode || "test";
    if ($("shopmonkey-test-order-id")) $("shopmonkey-test-order-id").value = _pricingConfig.test_order_id || "";
    if ($("shopmonkey-line-age")) $("shopmonkey-line-age").value = String(_pricingConfig.max_line_age_seconds || 600);
    if ($("shopmonkey-test-order-shell")) $("shopmonkey-test-order-shell").hidden = _pricingConfig.mode === "production";

    const customerBody = $("shopmonkey-customer-types");
    if (customerBody) customerBody.innerHTML = (_pricingConfig.customer_types || []).map(_renderCustomerTypeCard).join("");

    const canManage = _canManageCredential();
    $("shopmonkey-pricing-workspace")?.querySelectorAll(
      "#shopmonkey-pricing-enabled, #shopmonkey-pricing-mode, #shopmonkey-test-order-id, " +
      "#shopmonkey-line-age, #shopmonkey-customer-types input, #shopmonkey-customer-types select, " +
      "#shopmonkey-customer-types button"
    ).forEach(control => {
      control.disabled = !canManage;
    });
    const updated = _formatDate(_pricingConfig.updated_at);
    if ($("shopmonkey-pricing-updated")) {
      $("shopmonkey-pricing-updated").textContent = updated ? `Hosted settings updated ${updated}` : "Defaults not saved yet";
    }
  }

  function _readPricingFromDom() {
    const customerCards = [...document.querySelectorAll("#shopmonkey-customer-types [data-pricing-customer-type]")];
    const customerTypes = customerCards.map(card => {
      const referenceId = card.querySelector(':scope > .shopmonkey-customer-rule-identity [data-field="label_id"]')?.value || "";
      const reference = _resolveReference("label", "", referenceId);
      return {
        id: card.dataset.pricingCustomerType || "",
        enabled: !!card.querySelector(':scope > .shopmonkey-customer-rule-head [data-field="enabled"]')?.checked,
        name: card.querySelector(':scope > .shopmonkey-customer-rule-identity [data-field="name"]')?.value?.trim() || "",
        label_id: reference?.id || "",
        label: reference?.name || "",
      };
    });
    const rules = customerCards.flatMap(card => (
      [...card.querySelectorAll("[data-pricing-rule]")].map(row => {
        const referenceId = row.querySelector('[data-field="brand_id"]')?.value || "";
        const reference = _resolveReference("brand", "", referenceId);
        return {
          id: row.dataset.pricingRule || "",
          enabled: !!row.querySelector('[data-field="enabled"]')?.checked,
          brand_id: reference?.id || "",
          brand: reference?.name || "",
          customer_type_id: card.dataset.pricingCustomerType || "",
          basis: row.querySelector('[data-field="basis"]')?.value || "retail",
          operation: row.querySelector('[data-field="operation"]')?.value || "discount",
          percent: Number(row.querySelector('[data-field="percent"]')?.value),
        };
      })
    ));
    return {
      ..._pricingConfig,
      schema_version: 2,
      enabled: !!$("shopmonkey-pricing-enabled")?.checked,
      mode: $("shopmonkey-pricing-mode")?.value || "test",
      test_order_id: $("shopmonkey-test-order-id")?.value?.trim() || "",
      max_line_age_seconds: Number($("shopmonkey-line-age")?.value || 600),
      preserve_custom_prices: true,
      customer_types: customerTypes,
      rules,
    };
  }

  function _showPricingErrors(errors) {
    const box = $("shopmonkey-pricing-errors");
    if (!box) return;
    const rows = (errors || []).filter(Boolean);
    box.hidden = !rows.length;
    box.innerHTML = rows.map(error => `<span>${esc(error)}</span>`).join("");
  }

  async function _loadPricing(force = false) {
    if (_pricingLoaded && !force) return;
    const button = $("shopmonkey-pricing-reload");
    _setBusy(button, true, "Loading…");
    try {
      const [result, references] = await Promise.all([
        api("/api/shopmonkey/pricing"),
        api("/api/shopmonkey/pricing/references"),
      ]);
      if (!references?.ok) {
        _showPricingErrors([references?.detail || "Could not load Shopmonkey labels and brands."]);
        _renderPricingHealth(result.hosted_health, result.persisted);
        return;
      }
      _pricingReferences = {
        customer_labels: references.customer_labels || [],
        brands: references.brands || [],
      };
      _renderReferenceChoices();
      if (!result?.ok) {
        _showPricingErrors([result?.detail || "Could not load hosted pricing settings."]);
        if (!_pricingConfig) _pricingConfig = _starterPricingConfig();
        _renderPricing();
        _renderPricingHealth(null, false);
        return;
      }
      _pricingConfig = result.config;
      _pricingLoaded = true;
      _showPricingErrors([]);
      _renderPricing();
      _renderPricingHealth(result.hosted_health, result.persisted);
    } finally {
      _setBusy(button, false);
    }
  }

  async function _savePricing() {
    if (!_canManageCredential()) {
      appPermissionDenied("change hosted Shopmonkey pricing");
      return;
    }
    const candidate = _readPricingFromDom();
    if (candidate.mode === "production" && !confirm(
      "Enable these rules for every Shopmonkey order whose customer has exactly one matching pricing label? Custom prices remain protected."
    )) return;
    const button = $("shopmonkey-pricing-save");
    _setBusy(button, true, "Saving…");
    try {
      const result = await api("/api/shopmonkey/pricing/save", {
        config: candidate,
        expected_revision: _pricingConfig?.revision || "",
      });
      if (!result?.ok) {
        if (result?.error === "pricing_config_conflict" && result?.config) {
          _pricingConfig = result.config;
          _renderPricing();
        }
        _showPricingErrors(result?.errors?.length ? result.errors : [result?.detail || "Could not save hosted pricing settings."]);
        toast(result?.detail || "Hosted pricing settings were not saved", "error");
        return;
      }
      _pricingConfig = result.config;
      _pricingLoaded = true;
      _showPricingErrors([]);
      _renderPricing();
      toast(candidate.mode === "production" ? "Production pricing rules saved" : "Test pricing rules saved", "success");
      await _loadPricing(true);
    } finally {
      _setBusy(button, false);
    }
  }

  function _addCustomerType() {
    _pricingConfig = _readPricingFromDom();
    _pricingConfig.customer_types.push({ id: _rowId("customer-type"), name: "", label_id: "", label: "", enabled: true });
    _renderPricing();
    $("shopmonkey-customer-types")?.querySelector("section:last-child input[data-field='name']")?.focus();
  }

  function _addPriceRule(customerTypeId) {
    _pricingConfig = _readPricingFromDom();
    const customerType = _pricingConfig.customer_types.find(row => row.id === customerTypeId);
    if (!customerType) return;
    _pricingConfig.rules.push({
      id: _rowId("rule"), brand_id: "", brand: "", customer_type_id: customerType.id,
      basis: "retail", operation: "discount", percent: 0, enabled: true,
    });
    _renderPricing();
    const card = document.querySelector(`[data-pricing-customer-type="${CSS.escape(customerType.id)}"]`);
    card?.querySelector("[data-pricing-rule]:last-child [data-reference-trigger]")?.focus();
  }

  async function _connect() {
    const input = $("shopmonkey-api-key");
    const key = input?.value?.trim() || "";
    if (!key) {
      toast("Paste a Shopmonkey API key", "error");
      input?.focus();
      return;
    }
    const button = $("shopmonkey-connect-btn");
    _setBusy(button, true, "Testing…");
    try {
      const result = await api("/api/shopmonkey/connect", { api_key: key });
      if (!result?.ok) {
        toast(result?.detail || "Could not connect Shopmonkey", "error");
        return;
      }
      input.value = "";
      _renderStatus(result);
      _pricingLoaded = false;
      await _loadPricing(true);
      toast("Shopmonkey connected securely", "success");
    } finally {
      _setBusy(button, false);
    }
  }

  async function _test() {
    const button = $("shopmonkey-test-btn");
    _setBusy(button, true, "Testing…");
    try {
      const result = await api("/api/shopmonkey/test", {});
      if (!result?.ok) {
        toast(result?.detail || "Shopmonkey connection failed", "error");
        return;
      }
      _renderStatus(result);
      toast("Shopmonkey connection is working", "success");
    } finally {
      _setBusy(button, false);
    }
  }

  async function _disconnect() {
    if (!confirm("Disconnect Shopmonkey on this computer? The API key will be removed from the keychain.")) return;
    const result = await api("/api/shopmonkey/disconnect", {});
    if (!result?.ok) {
      toast(result?.detail || "Could not disconnect Shopmonkey", "error");
      return;
    }
    _customers = [];
    _pricingConfig = null;
    _pricingLoaded = false;
    _renderStatus(result);
    if ($("shopmonkey-vehicles-card")) $("shopmonkey-vehicles-card").hidden = true;
    toast("Shopmonkey disconnected", "success");
  }

  function _issueMarkup(issues) {
    if (!issues?.length) return '<span class="shopmonkey-clean">Ready</span>';
    return issues.map(issue => `<span class="shopmonkey-issue">${esc(issue)}</span>`).join("");
  }

  function _taxLabel(customer) {
    const values = [customer.tax_exempt ? "US exempt" : "US taxable"];
    if (customer.gst_exempt) values.push("GST exempt");
    if (customer.hst_exempt) values.push("HST exempt");
    if (customer.pst_exempt) values.push("PST exempt");
    return values.join(" · ");
  }

  function _renderSummary(summary) {
    const box = $("shopmonkey-summary");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = [
      [summary.total || 0, "records"],
      [summary.fleets || 0, "fleets"],
      [summary.records_with_issues || 0, "need review"],
      [summary.duplicate_groups || 0, "duplicate groups"],
      [summary.tax_mismatches || 0, "tax mismatches"],
    ].map(([value, label]) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  }

  function _renderCustomers() {
    const box = $("shopmonkey-results");
    if (!box) return;
    const query = ($("shopmonkey-filter")?.value || "").trim().toLowerCase();
    const rows = query ? _customers.filter(customer => [
      customer.name, customer.customer_type, customer.contact_name, customer.email,
      customer.phone, customer.address, _taxLabel(customer), ...(customer.issues || []),
    ].join(" ").toLowerCase().includes(query)) : _customers;
    if (!rows.length) {
      box.innerHTML = '<p class="shopmonkey-empty">No Shopmonkey records match this filter.</p>';
      return;
    }
    box.innerHTML = `<table class="shopmonkey-table">
      <thead><tr><th>Customer / Fleet</th><th>Contact</th><th>Tax</th><th>Vehicles</th><th>Cleanup review</th></tr></thead>
      <tbody>${rows.map(customer => `<tr>
        <td><strong>${esc(customer.name)}</strong><span>${esc(customer.customer_type)}${customer.dtm_agency ? ` · DTM: ${esc(customer.dtm_agency.name)}` : " · Not matched to DTM"}</span></td>
        <td><span>${esc(customer.email || "No email")}</span><span>${esc(customer.phone || "No phone")}</span><span>${esc(customer.address || "No address")}</span></td>
        <td><span>${esc(_taxLabel(customer))}</span></td>
        <td><button class="btn btn-secondary btn-sm" type="button" data-shopmonkey-vehicles="${attr(customer.shopmonkey_customer_id)}" data-shopmonkey-customer-name="${attr(customer.name)}">${esc(customer.vehicle_count || 0)} · Review</button></td>
        <td><div class="shopmonkey-issues">${_issueMarkup(customer.issues)}</div></td>
      </tr>`).join("")}</tbody>
    </table>`;
  }

  async function _scan() {
    const button = $("shopmonkey-scan-btn");
    _setBusy(button, true, "Scanning…");
    try {
      const result = await api("/api/shopmonkey/cleanup");
      if (!result?.ok) {
        toast(result?.detail || "Could not scan Shopmonkey", "error");
        return;
      }
      _customers = result.customers || [];
      _renderSummary(result.summary || {});
      if ($("shopmonkey-filter")) $("shopmonkey-filter").hidden = false;
      _renderCustomers();
      toast(`Reviewed ${_customers.length} Shopmonkey records`, "success");
    } finally {
      _setBusy(button, false);
    }
  }

  function _formatMoney(cents) {
    const value = Number(cents || 0) / 100;
    return value.toLocaleString(undefined, { style: "currency", currency: "USD" });
  }

  function _formatQuantity(value) {
    const number = Number(value || 0);
    return Number.isInteger(number) ? String(number) : number.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function _renderInventorySummary(summary) {
    const box = $("shopmonkey-inventory-summary");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = [
      [summary.parts || 0, "parts"],
      [summary.tires || 0, "tires"],
      [summary.categories || 0, "categories"],
      [_formatQuantity(summary.quantity), "on-hand quantity"],
      [_formatMoney(summary.retail_value_cents), "retail value"],
      [summary.missing_sku || 0, "missing SKU"],
      [summary.missing_part_number || 0, "missing part number"],
      [summary.missing_price || 0, "missing price"],
      [summary.negative_quantity || 0, "negative quantity"],
      [summary.duplicate_name_groups || 0, "duplicate name groups"],
      [summary.missing_photo || 0, "missing photo"],
    ].map(([value, label]) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  }

  function _renderInventory() {
    const box = $("shopmonkey-inventory-results");
    if (!box) return;
    const query = ($("shopmonkey-inventory-filter")?.value || "").trim().toLowerCase();
    const rows = query ? _inventory.filter(item => [
      item.kind, item.name, item.sku, item.part_number, item.brand,
      item.vendor, item.category, item.bin_location,
    ].join(" ").toLowerCase().includes(query)) : _inventory;
    if (!rows.length) {
      box.innerHTML = '<p class="shopmonkey-empty">No active inventory matches this filter.</p>';
      return;
    }
    box.innerHTML = `<table class="shopmonkey-table shopmonkey-inventory-table">
      <thead><tr><th>Type</th><th>SKU / Part number</th><th>Inventory item</th><th>Category / Vendor</th><th>Quantity</th><th>Cost / Retail</th><th>Review</th></tr></thead>
      <tbody>${rows.map(item => {
        const issues = [];
        if (!item.sku) issues.push("Missing SKU");
        if (item.retail_cost_cents === null || item.retail_cost_cents === undefined) issues.push("Missing retail price");
        if (!item.has_photo) issues.push("No photo");
        return `<tr>
          <td><span class="shopmonkey-kind">${esc(item.kind)}</span></td>
          <td><strong>${esc(item.sku || "—")}</strong><span>${esc(item.part_number || "No part number")}</span></td>
          <td><strong>${esc(item.name)}</strong><span>${esc(item.brand || "No brand")}</span></td>
          <td><span>${esc(item.category || "No category")}</span><span>${esc(item.vendor || "No vendor")}</span></td>
          <td><strong>${esc(_formatQuantity(item.quantity))}</strong><span>${esc(item.bin_location || "No bin")}</span></td>
          <td><span>Cost ${item.wholesale_cost_cents == null ? "—" : esc(_formatMoney(item.wholesale_cost_cents))}</span><span>Retail ${item.retail_cost_cents == null ? "—" : esc(_formatMoney(item.retail_cost_cents))}</span></td>
          <td><div class="shopmonkey-issues">${_issueMarkup(issues)}</div></td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
  }

  async function _snapshotInventory() {
    const button = $("shopmonkey-inventory-snapshot-btn");
    _setBusy(button, true, "Reading inventory…");
    try {
      const result = await api("/api/shopmonkey/inventory/snapshot", {});
      if (!result?.ok) {
        toast(result?.detail || "Could not create the Shopmonkey inventory snapshot", "error");
        return;
      }
      _inventory = result.items || [];
      _renderInventorySummary(result.summary || {});
      if ($("shopmonkey-inventory-filter")) $("shopmonkey-inventory-filter").hidden = false;
      const detail = $("shopmonkey-inventory-snapshot-detail");
      if (detail) {
        detail.hidden = false;
        detail.innerHTML = `<strong>Recovery snapshot saved</strong><span>${esc(result.snapshot_file || "")}</span><small>SHA-256 ${esc(result.sha256 || "")}</small>`;
      }
      const lock = $("shopmonkey-reset-lock");
      if (lock) lock.hidden = false;
      if ($("shopmonkey-reset-lock-reason")) {
        $("shopmonkey-reset-lock-reason").textContent = result.reset_preview?.blocked_reason || "Stage replacement price lists before enabling deletion.";
      }
      _renderInventory();
      toast(`Saved a recovery snapshot of ${result.summary?.total_items || 0} inventory items`, "success");
    } finally {
      _setBusy(button, false);
    }
  }

  async function _ensureEstimateLineBreaks() {
    if (!confirm("Create or verify the seven estimate line-break parts in Shopmonkey? Existing exact matches will be left unchanged.")) return;
    const button = $("shopmonkey-line-break-create-btn");
    _setBusy(button, true, "Creating…");
    try {
      const result = await api("/api/shopmonkey/inventory/estimate-line-breaks", {});
      if (!result?.ok) {
        toast(result?.detail || "Could not create the Shopmonkey line breaks", "error");
        return;
      }
      const box = $("shopmonkey-line-break-result");
      if (box) {
        box.hidden = false;
        box.innerHTML = `<strong>${esc(result.category?.name || "Estimate Line Breaks")}</strong><span>${esc(result.created?.length || 0)} created · ${esc(result.existing?.length || 0)} already present · ${esc(result.total || 0)} total</span>`;
      }
      toast(`Shopmonkey estimate line breaks are ready (${result.total || 0})`, "success");
    } finally {
      _setBusy(button, false);
    }
  }

  function _renderVehicles(customerName, result) {
    const card = $("shopmonkey-vehicles-card");
    const box = $("shopmonkey-vehicles-results");
    if (!card || !box) return;
    card.hidden = false;
    if ($("shopmonkey-vehicles-title")) $("shopmonkey-vehicles-title").textContent = `${customerName} Vehicles`;
    if ($("shopmonkey-vehicles-summary")) {
      $("shopmonkey-vehicles-summary").textContent = `${result.summary?.total || 0} vehicles · ${result.summary?.with_issues || 0} need review · ${result.summary?.missing_photos || 0} without custom photos`;
    }
    const vehicles = result.vehicles || [];
    box.innerHTML = vehicles.length ? `<table class="shopmonkey-table">
      <thead><tr><th>Vehicle</th><th>Unit / VIN</th><th>Photo</th><th>Cleanup review</th></tr></thead>
      <tbody>${vehicles.map(vehicle => `<tr>
        <td><strong>${esc(vehicle.name)}</strong><span>${esc([vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(" "))}</span></td>
        <td><span>Unit ${esc(vehicle.unit || "—")}</span><span>VIN ${esc(vehicle.vin || "—")}</span></td>
        <td><span class="${vehicle.has_custom_photo ? "shopmonkey-clean" : "shopmonkey-issue"}">${vehicle.has_custom_photo ? "Custom photo" : "Missing"}</span></td>
        <td><div class="shopmonkey-issues">${_issueMarkup(vehicle.issues)}</div></td>
      </tr>`).join("")}</tbody>
    </table>` : '<p class="shopmonkey-empty">No active vehicles were returned for this customer.</p>';
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function _loadVehicles(customerId, customerName, button) {
    _setBusy(button, true, "Loading…");
    try {
      const result = await api(`/api/shopmonkey/customers/${encodeURIComponent(customerId)}/vehicles`);
      if (!result?.ok) {
        toast(result?.detail || "Could not load Shopmonkey vehicles", "error");
        return;
      }
      _renderVehicles(customerName, result);
    } finally {
      _setBusy(button, false);
    }
  }

  function _wire() {
    if (_wired) return;
    _wired = true;
    $("shopmonkey-connect-btn")?.addEventListener("click", _connect);
    $("shopmonkey-test-btn")?.addEventListener("click", _test);
    $("shopmonkey-disconnect-btn")?.addEventListener("click", _disconnect);
    $("shopmonkey-scan-btn")?.addEventListener("click", _scan);
    $("shopmonkey-inventory-snapshot-btn")?.addEventListener("click", _snapshotInventory);
    $("shopmonkey-line-break-create-btn")?.addEventListener("click", _ensureEstimateLineBreaks);
    $("shopmonkey-pricing-reload")?.addEventListener("click", () => _loadPricing(true));
    $("shopmonkey-pricing-refresh-choices")?.addEventListener("click", () => _loadPricing(true));
    $("shopmonkey-load-vendor-guide")?.addEventListener("click", _loadVendorGuideRules);
    $("shopmonkey-pricing-save")?.addEventListener("click", _savePricing);
    $("shopmonkey-add-customer-type")?.addEventListener("click", _addCustomerType);
    $("shopmonkey-pricing-mode")?.addEventListener("change", event => {
      if ($("shopmonkey-test-order-shell")) $("shopmonkey-test-order-shell").hidden = event.target.value === "production";
    });
    $("shopmonkey-pricing-card")?.addEventListener("input", event => {
      const input = event.target.closest("input[data-reference-search]");
      if (input) _filterReferencePicker(input);
    });
    $("shopmonkey-pricing-card")?.addEventListener("change", event => {
      const enabled = event.target.closest(".shopmonkey-customer-rule-head input[data-field='enabled']");
      if (enabled) enabled.closest("[data-pricing-customer-type]")?.classList.toggle("is-disabled", !enabled.checked);
    });
    $("shopmonkey-customer-types")?.addEventListener("click", event => {
      const trigger = event.target.closest("button[data-reference-trigger]");
      if (trigger) {
        const picker = trigger.closest("[data-reference-picker]");
        const menu = picker?.querySelector("[data-reference-menu]");
        if (!picker || !menu) return;
        const opening = menu.hidden;
        _closeReferencePickers(picker);
        menu.hidden = !opening;
        trigger.setAttribute("aria-expanded", opening ? "true" : "false");
        if (opening) {
          const search = menu.querySelector("[data-reference-search]");
          if (search) {
            search.value = "";
            _filterReferencePicker(search);
            setTimeout(() => search.focus(), 0);
          }
        }
        return;
      }
      const option = event.target.closest("button[data-reference-option]");
      if (option) {
        const picker = option.closest("[data-reference-picker]");
        const kind = picker?.dataset.referencePicker;
        const reference = _resolveReference(kind, "", option.dataset.referenceOption);
        const value = picker?.querySelector("input[data-field]");
        const button = picker?.querySelector("button[data-reference-trigger]");
        if (!picker || !reference || !value || !button) return;
        value.value = reference.id;
        button.innerHTML = `${_referenceDisplay(kind, reference)}<span class="shopmonkey-picker-chevron">⌄</span>`;
        picker.classList.remove("is-invalid");
        _closeReferencePickers();
        return;
      }
      const addRule = event.target.closest("button[data-add-price-rule]");
      if (addRule) {
        _addPriceRule(addRule.dataset.addPriceRule);
        return;
      }
      const removeType = event.target.closest("button[data-remove-customer-type]");
      if (removeType) {
        const id = removeType.dataset.removeCustomerType;
        _pricingConfig = _readPricingFromDom();
        _pricingConfig.customer_types = _pricingConfig.customer_types.filter(row => row.id !== id);
        _pricingConfig.rules = _pricingConfig.rules.filter(row => row.customer_type_id !== id);
        _renderPricing();
        return;
      }
      const removeRule = event.target.closest("button[data-remove-price-rule]");
      if (removeRule) {
        _pricingConfig = _readPricingFromDom();
        _pricingConfig.rules = _pricingConfig.rules.filter(row => row.id !== removeRule.dataset.removePriceRule);
        _renderPricing();
      }
    });
    document.addEventListener("click", event => {
      if (!event.target.closest("[data-reference-picker]")) _closeReferencePickers();
    });
    $("shopmonkey-inventory-filter")?.addEventListener("input", _renderInventory);
    $("shopmonkey-filter")?.addEventListener("input", _renderCustomers);
    $("shopmonkey-vehicles-close")?.addEventListener("click", () => {
      if ($("shopmonkey-vehicles-card")) $("shopmonkey-vehicles-card").hidden = true;
    });
    $("shopmonkey-results")?.addEventListener("click", event => {
      const button = event.target.closest("button[data-shopmonkey-vehicles]");
      if (!button) return;
      _loadVehicles(
        button.dataset.shopmonkeyVehicles,
        button.dataset.shopmonkeyCustomerName || "Shopmonkey",
        button,
      );
    });
    $("shopmonkey-api-key")?.addEventListener("keydown", event => {
      if (event.key === "Enter") _connect();
    });
  }

  window.initShopmonkeyTab = function () {
    _wire();
    _loadStatus().catch(() => toast("Could not check Shopmonkey status", "error"));
  };
})();
