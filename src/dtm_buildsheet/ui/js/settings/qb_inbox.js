// QuickBooks Catalog Inbox — review unlinked QBO Items before they enter the
// vehicle-parts catalog. The cache supplies read-only accounting data; user
// decisions persist through the parts_db granular edit routes.
(function () {
  let inbox = {items: [], open_count: 0, ignored_count: 0};
  let catalog = {manufacturers: {}, part_types: {}, products: {}, types: {}};
  let activeItem = null;
  let activeMode = "";
  let wired = false;

  const money = value => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString(undefined, {style: "currency", currency: "USD"}) : "—";
  };

  const syncDate = value => {
    if (!value) return "never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  };

  const partNumber = item => String(item?.sku || item?.name || "").trim();

  async function edit(action, payload) {
    try {
      const result = await api(`/api/parts-db/edit/${action}`, payload);
      if (!result?.ok) throw new Error(result?.error || "Save failed");
      return result;
    } catch (error) {
      toast(error?.message || String(error), "error");
      return null;
    }
  }

  async function load({catalogToo = true} = {}) {
    try {
      const requests = [api("/api/parts-db/qb-inbox")];
      if (catalogToo) requests.push(api("/api/parts-db"));
      const results = await Promise.all(requests);
      inbox = results[0] || inbox;
      if (catalogToo) catalog = results[1] || catalog;
      updateBadge();
      render();
    } catch (error) {
      toast("Could not load the QBO Inbox: " + (error?.message || error), "error");
    }
  }

  function updateBadge() {
    const badge = $("qbi-tab-count");
    if (!badge) return;
    const count = Number(inbox.open_count || 0);
    badge.textContent = String(count);
    badge.hidden = count === 0;
  }

  function filteredItems() {
    const status = $("qbi-status")?.value || "open";
    const query = ($("qbi-search")?.value || "").trim().toLowerCase();
    return (inbox.items || []).filter(item => {
      if (status === "open" && item.ignored) return false;
      if (status === "ignored" && !item.ignored) return false;
      if (!query) return true;
      return [item.name, item.sku, item.description, item.type]
        .some(value => String(value || "").toLowerCase().includes(query));
    });
  }

  function render() {
    if (!$("qbi-list")) return;
    $("qbi-meta").textContent = `Last QBO pull: ${syncDate(inbox.last_sync_utc)}`;
    const items = filteredItems();
    $("qbi-count").textContent = `${inbox.open_count || 0} need review · ${inbox.ignored_count || 0} ignored · ${items.length} shown`;
    $("qbi-empty").hidden = items.length > 0;
    $("qbi-list").innerHTML = items.map(item => {
      const id = esc(String(item.qb_item_id || ""));
      const number = esc(partNumber(item) || "(unnamed item)");
      const description = esc(String(item.description || "").trim() || "No sales description");
      const skuDetail = item.sku ? ` · QBO SKU ${esc(item.sku)}` : "";
      const match = (item.catalog_matches || [])[0];
      const matchHtml = match
        ? `<div class="qbi-match">Exact catalog SKU found under <strong>${esc(match.manufacturer_label || "")}` +
          ` ${esc(match.product_model || match.product_id)}</strong>. “Add to product” will link that row.</div>`
        : "";
      const actions = item.ignored
        ? `<button class="btn btn-secondary btn-sm" data-qbi-action="restore" data-qbi-id="${id}">Restore</button>`
        : `<button class="btn btn-primary btn-sm" data-qbi-action="new" data-qbi-id="${id}">Create product</button>` +
          `<button class="btn btn-secondary btn-sm" data-qbi-action="existing" data-qbi-id="${id}">Add to product</button>` +
          `<button class="btn btn-secondary btn-sm qbi-ignore" data-qbi-action="ignore" data-qbi-id="${id}">Ignore</button>`;
      return `<article class="qbi-item${item.ignored ? " qbi-item-ignored" : ""}">
        <div class="qbi-item-main">
          <div class="qbi-item-description">${description}</div>
          <div class="qbi-item-detail"><strong>${number}</strong>${skuDetail} · ${esc(item.type || "Unknown type")} · ${esc(money(item.unit_price))} · QBO item ${id}</div>
          ${matchHtml}
        </div>
        <div class="qbi-actions">${actions}</div>
      </article>`;
    }).join("");
  }

  function manufacturerOptions(selected) {
    const rows = Object.entries(catalog.manufacturers || {})
      .sort((a, b) => String(a[1]?.label || a[0]).localeCompare(String(b[1]?.label || b[0])));
    return `<option value="">— Unassigned —</option>` + rows.map(([id, spec]) =>
      `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(spec.label || id)}</option>`
    ).join("");
  }

  function partTypeOptions() {
    const rows = Object.entries(catalog.part_types || {})
      .sort((a, b) => String(a[1]?.label || a[0]).localeCompare(String(b[1]?.label || b[0])));
    return `<option value="">— No part-type (categorize later) —</option>` + rows.map(([id, spec]) => {
      const typeLabel = catalog.types?.[spec.type_id]?.label || spec.type_id || "Other";
      return `<option value="${esc(id)}">${esc(typeLabel)} · ${esc(spec.label || id)}</option>`;
    }).join("");
  }

  function productRows(query = "") {
    const folded = query.trim().toLowerCase();
    return Object.entries(catalog.products || {})
      .map(([id, product]) => {
        const manufacturer = catalog.manufacturers?.[product.manufacturer_id]?.label || product.manufacturer_id || "Unassigned";
        return {id, label: `${manufacturer} · ${product.model || id}`};
      })
      .filter(row => !folded || row.label.toLowerCase().includes(folded))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  function populateProducts(query = "", preferred = "") {
    const select = $("qbi-product");
    if (!select) return;
    const previous = preferred || select.value;
    const rows = productRows(query);
    select.innerHTML = rows.map(row =>
      `<option value="${esc(row.id)}"${row.id === previous ? " selected" : ""}>${esc(row.label)}</option>`
    ).join("");
    if (previous && rows.some(row => row.id === previous)) select.value = previous;
  }

  function openModal(item, mode) {
    activeItem = item;
    activeMode = mode;
    const isNew = mode === "new";
    $("qbi-modal-title").textContent = isNew ? "Create product from QBO" : "Add QBO SKU to product";
    $("qbi-modal-item").textContent = `${partNumber(item)} — ${String(item.description || "No sales description").trim()}`;
    $("qbi-new-fields").hidden = !isNew;
    $("qbi-existing-fields").hidden = isNew;
    $("qbi-modal-save").textContent = isNew ? "Create product" : "Add SKU";
    if (isNew) {
      $("qbi-model").value = partNumber(item);
      $("qbi-manufacturer").innerHTML = manufacturerOptions(item.suggested_manufacturer_id || "");
      $("qbi-part-type").innerHTML = partTypeOptions();
    } else {
      $("qbi-product-search").value = "";
      populateProducts("", item.catalog_matches?.[0]?.product_id || "");
    }
    $("qbi-modal").classList.add("open");
    (isNew ? $("qbi-model") : $("qbi-product-search"))?.focus();
  }

  function closeModal() {
    $("qbi-modal")?.classList.remove("open");
    activeItem = null;
    activeMode = "";
  }

  async function saveModal() {
    if (!activeItem) return;
    const button = $("qbi-modal-save");
    button.disabled = true;
    try {
      let result;
      if (activeMode === "new") {
        const model = $("qbi-model").value.trim();
        if (!model) { toast("Product model is required", "error"); return; }
        result = await edit("qb-inbox-import-new", {
          qb_item_id: activeItem.qb_item_id,
          model,
          manufacturer_id: $("qbi-manufacturer").value,
          part_type_id: $("qbi-part-type").value,
        });
      } else {
        const productId = $("qbi-product").value;
        if (!productId) { toast("Choose an existing product", "error"); return; }
        result = await edit("qb-inbox-add-to-product", {
          qb_item_id: activeItem.qb_item_id,
          product_id: productId,
        });
      }
      if (!result) return;
      closeModal();
      toast(result.created_product ? "QBO item created in the catalog" : "QBO SKU linked to the product", "success");
      await load();
    } finally {
      button.disabled = false;
    }
  }

  function wireOnce() {
    if (wired) return;
    wired = true;
    $("qbi-reload")?.addEventListener("click", () => load());
    $("qbi-search")?.addEventListener("input", render);
    $("qbi-status")?.addEventListener("change", render);
    $("qbi-sync")?.addEventListener("click", async () => {
      const button = $("qbi-sync");
      button.disabled = true;
      try {
        const result = await api("/api/quickbooks/sync", {});
        if (!result?.ok) throw new Error(result?.error || "QuickBooks pull failed");
        toast(`Pulled ${result.item_count || 0} active QuickBooks items`, "success");
        await load();
      } catch (error) {
        toast(error?.message || String(error), "error");
      } finally {
        button.disabled = false;
      }
    });
    $("qbi-list")?.addEventListener("click", async event => {
      const button = event.target.closest("[data-qbi-action]");
      if (!button) return;
      const item = (inbox.items || []).find(entry => String(entry.qb_item_id) === button.dataset.qbiId);
      if (!item) return;
      const action = button.dataset.qbiAction;
      if (action === "new" || action === "existing") { openModal(item, action); return; }
      if (action === "ignore" && !confirm(`Ignore ${partNumber(item)} in the QBO Inbox?`)) return;
      const result = await edit(action === "ignore" ? "qb-inbox-ignore" : "qb-inbox-restore", {qb_item_id: item.qb_item_id});
      if (result) await load({catalogToo: false});
    });
    $("qbi-product-search")?.addEventListener("input", event => populateProducts(event.target.value));
    $("qbi-modal-save")?.addEventListener("click", saveModal);
    $("qbi-modal-close")?.addEventListener("click", closeModal);
    $("qbi-modal-cancel")?.addEventListener("click", closeModal);
    $("qbi-modal")?.addEventListener("click", event => { if (event.target.id === "qbi-modal") closeModal(); });
  }

  window.initQbInboxTab = async function () {
    wireOnce();
    await load();
  };

  window.refreshQbInboxCount = async function () {
    try {
      inbox = await api("/api/parts-db/qb-inbox");
      updateBadge();
    } catch (_) { /* No cache yet: leave the badge quiet. */ }
  };
})();
