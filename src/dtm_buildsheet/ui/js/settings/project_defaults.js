let _estimateDefaults = null;
let _estimateDefaultsWired = false;

function _estimateDefaultsMoney(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number >= 0 ? number.toFixed(2) : "0.00";
}

function _renderEstimateDefaults(data) {
  const grid = $("estimate-defaults-grid");
  const status = $("estimate-defaults-status");
  const items = $("estimate-defaults-qb-items");
  if (!grid || !status || !items) return;
  const order = ["patrol", "undercover", "admin", "custom"];
  grid.innerHTML = `<div class="estimate-defaults-head"><span>Build type</span><span>Labor total</span><span>Install supplies</span></div>${order.map(id => {
    const preset = data.presets?.[id] || { label: id };
    return `<div class="estimate-defaults-row" data-estimate-preset="${_ptEscAttr(id)}">
      <strong>${esc(preset.label || id)}</strong>
      <label><span class="estimate-money-prefix">$</span><input aria-label="${_ptEscAttr(preset.label || id)} labor total" type="number" min="0" step="0.01" data-estimate-default="labor" value="${_estimateDefaultsMoney(preset.labor_amount)}"></label>
      <label><span class="estimate-money-prefix">$</span><input aria-label="${_ptEscAttr(preset.label || id)} install supplies" type="number" min="0" step="0.01" data-estimate-default="supplies" value="${_estimateDefaultsMoney(preset.install_supplies_amount)}"></label>
    </div>`;
  }).join("")}`;
  const service = data.service_items || {};
  items.innerHTML = `<strong>QuickBooks service items</strong><span>Labor: ${esc(service.labor || "LABOR INSTALL")}</span><span>Supplies: ${esc(service.install_supplies || "INSTALL SUPPLIES")}</span><span>Card fee: ${esc(service.card_fee || "Convenience Fee")}</span><span>Delivery: ${esc(service.delivery || "TRAVEL")}</span><small>The ${Number(data.card_fee_percent || 4).toFixed(2).replace(/\.00$/, "")}% credit card fee is calculated automatically on parts, labor, supplies, and delivery. Delivery remains optional per estimate.</small>`;
  status.textContent = "Enter a labor value above $0 for every preset you plan to estimate.";
  status.className = "estimate-defaults-status";
  grid.hidden = false;
  items.hidden = false;
}

async function _saveEstimateDefaults() {
  if (!_estimateDefaults) return;
  const next = JSON.parse(JSON.stringify(_estimateDefaults));
  let valid = true;
  document.querySelectorAll("[data-estimate-preset]").forEach(row => {
    const preset = next.presets?.[row.dataset.estimatePreset];
    if (!preset) return;
    const labor = Number(row.querySelector('[data-estimate-default="labor"]')?.value);
    const supplies = Number(row.querySelector('[data-estimate-default="supplies"]')?.value);
    if (!Number.isFinite(labor) || labor < 0 || !Number.isFinite(supplies) || supplies < 0) valid = false;
    preset.labor_amount = labor;
    preset.install_supplies_amount = supplies;
  });
  if (!valid) {
    toast("Labor and install supplies must be valid non-negative amounts", "error");
    return;
  }
  const button = $("estimate-defaults-save");
  const status = $("estimate-defaults-status");
  if (button) { button.disabled = true; button.textContent = "Saving…"; }
  try {
    const result = await api("/api/estimate-charges/save", next);
    if (!result?.ok) throw new Error(result?.error || "Save failed");
    _estimateDefaults = next;
    if (status) {
      status.textContent = "✓ Estimate defaults saved and shared with the team.";
      status.className = "estimate-defaults-status estimate-defaults-status--saved";
    }
    toast("Estimate defaults saved", "success");
  } catch (error) {
    if (status) {
      status.textContent = "Could not save estimate defaults: " + (error?.message || "unknown error");
      status.className = "estimate-defaults-status estimate-defaults-status--error";
    }
    toast("Could not save estimate defaults", "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = "Save defaults"; }
  }
}

async function initProjectDefaultsTab() {
  if (!_estimateDefaultsWired) {
    _estimateDefaultsWired = true;
    $("estimate-defaults-save")?.addEventListener("click", _saveEstimateDefaults);
  }
  const status = $("estimate-defaults-status");
  try {
    _estimateDefaults = await api("/api/estimate-charges");
    _renderEstimateDefaults(_estimateDefaults);
  } catch (error) {
    if (status) {
      status.textContent = "Could not load estimate defaults: " + (error?.message || "unknown error");
      status.className = "estimate-defaults-status estimate-defaults-status--error";
    }
  }
}
