// ═══════════════════════════════════════════════════════
// PART PICKER — two-pane (filters | live product list) + dot-picker location
// Tabs: Part / Location. Same UI for Add and Edit. No typing except search.
// ═══════════════════════════════════════════════════════

let _pickerState = {
  open: false,
  editLineId: null,
  editPart: null,
  tab: "part",
  types: [],
  filters: { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", brand: "", lens: "" },
  config: { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false },
  availAll: new Set(),
  search: "",
  products: [],            // [{product_id, model, manufacturer_label, skus:[...]}]
  expanded: new Set(),     // product_ids whose SKU list is open
  sel: null,               // { product_id, model, mfr, sku? }  current selection
  loc: { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, name_pattern: "", base_label: "" },
  accessories: [],         // resolved [{category,label,required,options:[...]}] for current product
  accessoryChoices: {},    // category_id → select value ("" | "none" | "<product_id>::<sku>")
  accLoadedFor: null,      // product_id accessories were loaded for
  tracer: { active: false, mode: "trio", secondary: "white", preview: null, loading: false },
  vehicleOnly: true,       // hide parts/accessories not compatible with the draft's vehicle
  footerHandler: null,
  _footerWired: false,
};

const _PICKER_COLORS = {
  red:    { label: "Red",    hex: "#e53935" },
  blue:   { label: "Blue",   hex: "#1e88e5" },
  amber:  { label: "Amber",  hex: "#fb8c00" },
  white:  { label: "White",  hex: "#fafafa", border: "#c2c2c2" },
  green:  { label: "Green",  hex: "#43a047" },
  purple: { label: "Purple", hex: "#8e24aa" },
};
const _PICKER_COLOR_ORDER = ["red", "blue", "amber", "white", "green", "purple"];
const _COLORS_PER_HEAD = { single: 1, duo: 2, trio: 3 };
const _LIGHT_CATEGORIES = [
  { id: "warning",      label: "Warning",      icon: "🚨" },
  { id: "scene",        label: "Scene",        icon: "💡" },
  { id: "interior",     label: "Interior",     icon: "🏠" },
  { id: "interior_bar", label: "Interior Bar", icon: "🪟" },
  { id: "roof_bar",     label: "Roof Bar",     icon: "🚙" },
  { id: "spotlight",    label: "Spotlight",    icon: "🔦" },
];
const _TYPE_ICONS = { lights: "💡", equipment: "🔧", structural: "🏗️", k9: "🐕", extras: "⚡" };
// Categories whose parts are color-configured (lights). Others pick a SKU directly.
const _COLOR_CATEGORIES = new Set(["warning", "scene", "interior", "interior_bar", "roof_bar", "spotlight"]);

function _ionRank(pn) {
  if (!pn) return 1;
  if (pn.startsWith("I2")) return 0;
  if (pn.startsWith("IOND") || pn.startsWith("IONE")) return 2;
  return 1;
}

// ── Public entry points ────────────────────────────────

async function openPicker() {
  _pickerResetState();
  _pickerOpenPanel("Add Part");
  await _pickerLoadTypes();
  await _pickerFetchProducts();
  _pickerSwitchTab("part");
}

function pickerClose() {
  _pickerState.open = false;
  _pickerState.editLineId = null;
  _pickerState.editPart = null;
  const panel = $("picker-panel");
  if (panel) panel.classList.remove("open");
}

async function _pickerOpenEdit(part) {
  if (!part) return;
  _pickerResetState();
  _pickerState.editLineId = part.line_id;
  _pickerState.editPart = part;
  _pickerOpenPanel("Edit Part");
  await _pickerLoadTypes();
  // Best-effort prefill from the stored part.
  _pickerState.filters.type_id = "lights";
  await _pickerFetchProducts();
  // Try to preselect the product by matching a component/part_number.
  const pn = (part.components && part.components[0] && part.components[0].part_number) || part.part_number;
  const prod = _pickerState.products.find(p => p.skus.some(s => s.part_number === pn));
  if (prod) {
    _pickerState.sel = { product_id: prod.product_id, model: prod.model, mfr: prod.manufacturer_label };
    _pickerState.expanded.add(prod.product_id);
  }
  _pickerState.loc.preName = part.name;
  _pickerState.loc.preLoc = part.location;
  _pickerSwitchTab("part");
}

// ── Shell ──────────────────────────────────────────────

function _pickerResetState() {
  _pickerState.open = true;
  _pickerState.editLineId = null;
  _pickerState.editPart = null;
  _pickerState.tab = "part";
  _pickerState.step = 0;          // current left-pane wizard step
  _pickerState.filters = { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", brand: "", lens: "" };
  _pickerState.config = { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false };
  _pickerState.search = "";
  _pickerState.products = [];
  _pickerState.expanded = new Set();
  _pickerState.sel = null;
  _pickerState.skuChoices = {};   // color-combo label → chosen part_number (override)
  _pickerState.loc = { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, name_pattern: "", base_label: "" };
  _pickerState.accessories = [];
  _pickerState.accessoryChoices = {};
  _pickerState.accLoadedFor = null;
  _pickerState.tracer = { active: false, mode: "trio", secondary: "white", preview: null, loading: false };
  try {                            // persisted toggle; default ON
    const v = localStorage.getItem("pp_vehicle_only");
    _pickerState.vehicleOnly = v === null ? true : v === "1";
  } catch { _pickerState.vehicleOnly = true; }
}

// ── Vehicle compatibility ──────────────────────────────
// The draft's VehicleType string is the same vocabulary as a SKU's
// vehicle_tags. A SKU is compatible when it carries no tags, an "any" tag,
// or the selected vehicle's tag. Empty vehicle (none selected) = show all.
function _pickerVehicle() {
  return (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "";
}
function _skuCompatible(s, veh) {
  if (!veh) return true;
  const tags = (s.vehicle_tags || []).map(t => String(t).toUpperCase());
  return !tags.length || tags.includes("ANY") || tags.includes(String(veh).toUpperCase());
}

function _pickerOpenPanel(title) {
  const t = $("picker-title"); if (t) t.textContent = title;
  const panel = $("picker-panel");
  if (panel) panel.classList.add("open");
  if (!_pickerState._footerWired) {
    $("picker-add-btn")?.addEventListener("click", () => { if (_pickerState.footerHandler) _pickerState.footerHandler(); });
    $("picker-tab-btn-part")?.addEventListener("click", () => _pickerSwitchTab("part"));
    $("picker-tab-btn-location")?.addEventListener("click", () => _pickerSwitchTab("location"));
    _pickerState._footerWired = true;
  }
}

function _pickerSwitchTab(tab) {
  _pickerState.tab = tab;
  $("picker-tab-btn-part")?.classList.toggle("active", tab === "part");
  $("picker-tab-btn-location")?.classList.toggle("active", tab === "location");
  const pp = $("picker-pane-part"), pl = $("picker-pane-location");
  if (pp) pp.hidden = tab !== "part";
  if (pl) pl.hidden = tab !== "location";
  if (tab === "part") {
    _pickerRenderFilters();
    _pickerRenderProducts();
  } else {
    _pickerRenderLocation();
  }
  _pickerRenderAccessories();
  _pickerUpdateFooter();
}

async function _pickerLoadTypes() {
  try {
    const res = await api("/api/parts-db/types");
    _pickerState.types = res?.types || [];
  } catch (e) { console.error("Picker: types failed:", e); _pickerState.types = []; }
}

// ── Data ───────────────────────────────────────────────

async function _pickerFetchProducts() {
  const f = _pickerState.filters;
  try {
    const url = `/api/parts-db/category-skus?type=${encodeURIComponent(f.type_id)}&category=${encodeURIComponent(f.category_id || "")}`;
    const res = await api(url);
    _pickerState.products = res?.products || [];
  } catch (e) {
    console.error("Picker: category-skus failed:", e);
    _pickerState.products = [];
  }
  // Available colors across the loaded set (drives swatch availability).
  const avail = new Set();
  for (const p of _pickerState.products)
    for (const s of p.skus) {
      if (s.color) avail.add(s.color);
      if (s.secondary_color) avail.add(s.secondary_color);
      if (s.tertiary_color) avail.add(s.tertiary_color);
    }
  _pickerState.availAll = avail;
  _pickerNormalizeConfig();
  // Auto-select preferred brand if not already chosen.
  if (!f.brand) {
    const allBrands = [...new Set(_pickerState.products.map(p => p.manufacturer_label).filter(Boolean))];
    if (allBrands.length > 1) {
      const prefLighting = window._PT?.viewProject?.preferences?.lighting;
      const prefBrands = (window._PT?.viewProject?.preferences?.lighting_brands || []).map(b => String(b).toLowerCase());
      const match = allBrands.find(b => {
        const bl = b.toLowerCase();
        return (prefLighting && bl === String(prefLighting).toLowerCase()) || prefBrands.includes(bl);
      });
      if (match) f.brand = match;
    }
  }
  // Auto-expand when only one product remains.
  if (_pickerState.products.length === 1) _pickerState.expanded.add(_pickerState.products[0].product_id);
}

// ── Filters pane (left) ────────────────────────────────

// The left pane is a click-through wizard: one filter group per page, with the
// product list narrowing live on the right. Steps depend on the type/category.
function _pickerUsesColor() {
  const f = _pickerState.filters;
  return f.type_id === "lights" && f.category_id !== "" && _COLOR_CATEGORIES.has(f.category_id);
}
function _pickerSteps() {
  const f = _pickerState.filters;
  const steps = [{ id: "type", label: "Part type" }];
  if (f.type_id === "lights") steps.push({ id: "category", label: "Light type" });
  if (_pickerUsesColor()) steps.push({ id: "colors", label: "Colors & options" });
  return steps;
}

function _pickerRenderFilters() {
  const el = $("picker-filters");
  if (!el) return;
  const f = _pickerState.filters;
  const steps = _pickerSteps();
  _pickerState.step = Math.max(0, Math.min(_pickerState.step, steps.length - 1));
  const cur = steps[_pickerState.step];

  const crumbs = steps.map((s, i) =>
    `<button class="pf-crumb${i === _pickerState.step ? " active" : ""}${i < _pickerState.step ? " done" : ""}" data-step="${i}">${esc(s.label)}</button>`
  ).join(`<span class="pf-crumb-sep">›</span>`);

  let content = "";
  if (cur.id === "type") {
    const _TYPE_ORDER = ["lights", "structural", "equipment", "k9", "extras"];
    const _buildType = (window._PT?.viewProject?.info?.BuildType || window._PT?.viewProject?.vehicle_info?.BuildType || "").toLowerCase();
    const _isK9Build = _buildType.includes("k-9") || _buildType.includes("k9");
    const _sortedTypes = [..._pickerState.types]
      .filter(t => t.type_id !== "k9" || _isK9Build)
      .sort((a, b) => {
        const ai = _TYPE_ORDER.indexOf(a.type_id), bi = _TYPE_ORDER.indexOf(b.type_id);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
      });
    content = `<div class="pf-pills pf-stack">` + _sortedTypes.map(t =>
      `<button class="pf-pill pf-big${f.type_id === t.type_id ? " active" : ""}" data-k="type" data-v="${esc(t.type_id)}" data-l="${esc(t.label)}">${_TYPE_ICONS[t.type_id] || "📦"} ${esc(t.label)}</button>`).join("") + `</div>`;
  } else if (cur.id === "category") {
    content = `<div class="pf-pills pf-stack">` + _LIGHT_CATEGORIES.map(c =>
      `<button class="pf-pill pf-big${f.category_id === c.id ? " active" : ""}" data-k="cat" data-v="${esc(c.id)}" data-l="${esc(c.label)}">${c.icon} ${esc(c.label)}</button>`).join("") + `</div>`;
  } else if (cur.id === "colors") {
    content = _pickerColorConfigHtml();
  }

  el.innerHTML = `<div class="pf-group pf-search"><input type="text" id="pf-search" placeholder="🔍 Search products / SKUs" value="${esc(_pickerState.search)}"></div>
    <div class="pf-crumbs">${crumbs}</div>
    ${_pickerState.step > 0 ? `<button class="pf-back" id="pf-back">← Back</button>` : ""}
    <div class="pf-stepbody">${content}</div>`;
  _pickerWireFilters();
}

function _pickerColorConfigHtml() {
  const c = _pickerState.config;
  const f = _pickerState.filters;
  const cat = f.category_id;
  const isSceneInterior = cat === "scene" || cat === "interior";
  const isBar = cat === "interior_bar" || cat === "roof_bar";
  const slots = _COLORS_PER_HEAD[c.colorsPerHead];
  const seg = (k, v, label, active, disabled) =>
    `<button class="pf-pill${active ? " active" : ""}" data-k="${k}" data-v="${v}"${disabled ? " disabled" : ""}>${esc(label)}</button>`;

  const countHtml = `<div class="pf-group"><span class="pf-label">Lightheads</span>
      <div class="pf-pills"><button class="pf-pill" data-k="count" data-v="-1">−</button>
      <span style="font-weight:700;padding:5px 4px">${c.count}</span>
      <button class="pf-pill" data-k="count" data-v="1">+</button></div></div>`;

  const lensHtml = `<div class="pf-group"><span class="pf-label">Lens</span><div class="pf-pills">
      ${seg("lens", "", "All", (f.lens || "") === "")}
      ${seg("lens", "clear", "Clear", (f.lens || "") === "clear")}
      ${seg("lens", "smoked", "Smoked", (f.lens || "") === "smoked")}</div></div>`;

  if (isBar) {
    return countHtml + `<div class="pf-group"><span class="pf-label">Colors per head</span><div class="pf-pills">
        ${seg("cph", "duo", "Duo", c.colorsPerHead !== "trio")}
        ${seg("cph", "trio", "Trio", c.colorsPerHead === "trio")}</div></div>` + lensHtml;
  }

  const cphHtml = `<div class="pf-group"><span class="pf-label">Colors per head</span><div class="pf-pills">
      ${seg("cph", "single", "Solo", c.colorsPerHead === "single")}
      ${seg("cph", "duo", "Duo", c.colorsPerHead === "duo")}
      ${seg("cph", "trio", "Trio", c.colorsPerHead === "trio")}</div></div>`;

  if (isSceneInterior) {
    const noColor = c._noColor === true;
    const whiteSwatches = _PICKER_COLOR_ORDER.map(col => {
      const d = _PICKER_COLORS[col];
      const isWhite = col === "white";
      const isSel = !noColor && c.uniform[0] === col;
      return `<button class="picker-swatch${isSel ? " sel" : (isWhite ? "" : " dim")}" data-color="${col}" ${isWhite ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("");
    const noneBtn = `<button class="picker-swatch${noColor ? " sel" : ""}" data-color="" title="No color (unlabeled)" style="background:#888;border-color:#666;font-size:9px;line-height:28px">—</button>`;
    return countHtml + cphHtml +
      `<div class="pf-group"><span class="pf-label">Color</span>` +
      `<div class="picker-swatches" data-kind="uniform" data-slot="0">${whiteSwatches}${noneBtn}</div></div>` + lensHtml;
  }

  const modeHtml = `<div class="pf-group"><span class="pf-label">Mode</span><div class="pf-pills">
      ${seg("mode", "uniform", "Uniform", c.mode === "uniform")}
      ${seg("mode", "split", "Split", c.mode === "split", !c.splitAllowed)}
      ${seg("mode", "custom", "Custom", c.mode === "custom")}</div></div>`;

  let sel = "";
  if (c.mode === "uniform") {
    sel = c.uniform.map((s, i) => `<div class="pf-group"><span class="pf-label">${slots > 1 ? "Color " + (i + 1) : "Color"}</span>${_pickerSwatchRow("uniform", i, s)}</div>`).join("");
  } else if (c.mode === "split") {
    sel = `<div class="pf-group"><span class="pf-label">Primary</span><span style="font-size:11px;color:var(--muted)">🔴 Red driver · 🔵 Blue passenger</span></div>`;
    sel += c.splitSecondary.map((s, i) => `<div class="pf-group"><span class="pf-label">${c.splitSecondary.length > 1 ? "Secondary " + (i + 1) : "Secondary"}</span>${_pickerSwatchRow("split", i, s)}</div>`).join("");
  } else {
    sel = c.custom.map((arr, h) => `<div class="pf-group"><span class="pf-label">Head ${h + 1}</span>${_pickerSwatchMulti(h, arr, slots)}</div>`).join("");
  }

  return countHtml + cphHtml + modeHtml + sel + lensHtml;
}

function _pickerSwatchRow(kind, slot, selected) {
  const c = _pickerState.config;
  return `<div class="picker-swatches" data-kind="${kind}" data-slot="${slot}">` +
    _PICKER_COLOR_ORDER.map(col => {
      const avail = c.__allowAll || _pickerState.availAll.has(col);
      const d = _PICKER_COLORS[col];
      return `<button class="picker-swatch${selected === col ? " sel" : ""}${avail ? "" : " dim"}" data-color="${col}" ${avail ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("") + `</div>`;
}

function _pickerSwatchMulti(head, arr, max) {
  return `<div class="picker-swatches" data-kind="custom" data-head="${head}">` +
    _PICKER_COLOR_ORDER.map(col => {
      const avail = _pickerState.availAll.has(col);
      const d = _PICKER_COLORS[col];
      return `<button class="picker-swatch${arr.includes(col) ? " sel" : ""}${avail ? "" : " dim"}" data-color="${col}" ${avail ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("") + `<span style="font-size:11px;color:var(--muted)">${arr.length}/${max}</span></div>`;
}

function _pickerWireFilters() {
  const el = $("picker-filters");
  if (!el) return;
  $("pf-search")?.addEventListener("input", e => { _pickerState.search = e.target.value; _pickerRenderProducts(); });
  $("pf-back")?.addEventListener("click", () => { _pickerState.step = Math.max(0, _pickerState.step - 1); _pickerRenderFilters(); });
  el.querySelectorAll(".pf-crumb").forEach(b => b.addEventListener("click", () => {
    const i = parseInt(b.dataset.step, 10);
    if (i <= _pickerState.step) { _pickerState.step = i; _pickerRenderFilters(); }
  }));

  el.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", async () => {
    if (b.disabled) return;
    const k = b.dataset.k, v = b.dataset.v;
    const f = _pickerState.filters, c = _pickerState.config;
    if (k === "type") {
      f.type_id = v; f.type_label = b.dataset.l; f.category_id = ""; f.category_label = "";
      _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
      await _pickerFetchProducts();
      const steps = _pickerSteps();
      _pickerState.step = Math.min(1, steps.length - 1);   // advance to next step
      _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return;
    }
    if (k === "cat") {
      f.category_id = v; f.category_label = b.dataset.l;
      _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
      await _pickerFetchProducts();
      const steps = _pickerSteps();
      const ci = steps.findIndex(s => s.id === "colors");
      _pickerState.step = ci >= 0 ? ci : _pickerState.step;  // advance to colors if present
      _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return;
    }
    if (k === "lens") { f.lens = v; _pickerRenderFilters(); _pickerRenderProducts(); return; }
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "cph") { c.colorsPerHead = v; _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "mode") { c.mode = v; _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
  }));

  el.querySelectorAll(".picker-swatch").forEach(b => b.addEventListener("click", () => {
    if (b.disabled) return;
    const wrap = b.closest(".picker-swatches"), c = _pickerState.config, color = b.dataset.color, kind = wrap.dataset.kind;
    if (color === "") {
      c._noColor = true;
    } else {
      c._noColor = false;
      if (kind === "uniform") c.uniform[parseInt(wrap.dataset.slot, 10)] = color;
      else if (kind === "split") c.splitSecondary[parseInt(wrap.dataset.slot, 10)] = color;
      else if (kind === "custom") {
        const arr = c.custom[parseInt(wrap.dataset.head, 10)], max = _COLORS_PER_HEAD[c.colorsPerHead], i = arr.indexOf(color);
        if (i >= 0) { if (arr.length > 1) arr.splice(i, 1); } else if (arr.length < max) arr.push(color);
      }
    }
    _pickerState.skuChoices = {};   // colors changed → drop SKU overrides
    _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter();
  }));
}

// ── Color config helpers (ported) ──────────────────────

function _pickerNormalizeConfig() {
  const c = _pickerState.config;
  const cat = _pickerState.filters.category_id;
  const isBar = cat === "interior_bar" || cat === "roof_bar";
  const isSceneInterior = cat === "scene" || cat === "interior";
  // Bar categories: enforce duo minimum (no single)
  if (isBar && c.colorsPerHead === "single") c.colorsPerHead = "duo";
  const slots = _COLORS_PER_HEAD[c.colorsPerHead];
  const catDefault = isSceneInterior ? "white" : "red";
  const firstAvail = _PICKER_COLOR_ORDER.find(x => _pickerState.availAll.has(x)) || catDefault;
  c.splitAllowed = (c.count % 2 === 0) && slots <= 2;
  if (c.mode === "split" && !c.splitAllowed) c.mode = "uniform";
  c.uniform = Array.from({ length: slots }, (_, i) => c.uniform[i] || firstAvail);
  c.splitSecondary = Array.from({ length: Math.max(0, slots - 1) }, (_, i) => c.splitSecondary[i] || (_pickerState.availAll.has("white") ? "white" : firstAvail));
  c.custom = Array.from({ length: c.count }, (_, h) => {
    const cur = (c.custom[h] || []).slice(0, slots);
    return cur.length ? cur : [firstAvail];
  });
}

function _pickerResolveHeads() {
  const c = _pickerState.config;
  if (c._noColor) return [[]];
  if (c.mode === "uniform") return Array.from({ length: c.count }, () => [...c.uniform]);
  if (c.mode === "split") {
    const half = c.count / 2;
    return Array.from({ length: c.count }, (_, h) => [h < half ? "red" : "blue", ...c.splitSecondary]);
  }
  return c.custom.map(a => [...a]);
}

// ── Product list (right) ───────────────────────────────

function _skuSet(s) { return [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).map(x => x.toLowerCase()).sort(); }
function _headSet(h) { return [...new Set(h.map(x => x.toLowerCase()).filter(Boolean))].sort(); }
function _eqSet(a, b) { return a.length === b.length && a.every((v, i) => v === b[i]); }

function _skuMatchesAny(sku, headSets) {
  const s = _skuSet(sku);
  // "No color" selection matches any SKU
  return headSets.some(hs => hs.length === 0 || _eqSet(s, hs));
}

function _pickerComboLabel(hs) { return hs.map(x => x[0].toUpperCase() + x.slice(1)).join("/"); }

// A product is color-configured only if at least one SKU carries a color.
// Programmable (WeCanX) bars have none → picked directly by SKU.
function _pickerProductHasColor(p) {
  return (p.skus || []).some(s => s.color || s.secondary_color || s.tertiary_color);
}

function _pickerRenderProducts() {
  const el = $("picker-products");
  if (!el) return;
  const f = _pickerState.filters;
  const usesColor = _pickerUsesColor();
  const headSets = usesColor ? [...new Map(_pickerResolveHeads().map(h => [_headSet(h).join(","), _headSet(h)])).values()] : [];
  const q = _pickerState.search.trim().toLowerCase();

  // Brand refine bar (lets the user switch between matched alternatives by brand).
  const brands = [...new Set(_pickerState.products.map(p => p.manufacturer_label).filter(Boolean))].sort();
  const pref = new Set((window._PT?.viewProject?.preferences?.lighting_brands || []).map(b => String(b).toLowerCase()));
  // Auto-select preferred brand on first render only
  if (!_pickerState._brandAutoSet && !f.brand && brands.length > 0) {
    const prefBrand = brands.find(b => pref.has(b.toLowerCase()));
    if (prefBrand) { f.brand = prefBrand; _pickerState._brandAutoSet = true; }
  }
  // When user explicitly picks "All", clear the auto-set flag so it sticks
  if (f.brand && !_pickerState._brandAutoSet) _pickerState._brandAutoSet = true;
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  let header = "";
  if (brands.length > 1) {
    header = `<div class="pp-brandbar"><span class="pf-label">Brand</span>` +
      `<button class="pf-pill${!f.brand ? " active" : ""}" data-brand="">All</button>` +
      brands.map(b => `<button class="pf-pill${f.brand === b ? " active" : ""}" data-brand="${esc(b)}">${pref.has(b.toLowerCase()) ? "★ " : ""}${esc(b)}</button>`).join("") + `</div>`;
  }
  if (veh) {
    header += `<label class="pp-vehtoggle"><input type="checkbox" id="pp-veh-only"${_pickerState.vehicleOnly ? " checked" : ""}>`
      + `<span>Only show ${esc(veh)}-compatible parts</span></label>`;
  }
  // A product matches when every chosen color combo has a matching SKU.
  const isMatch = p => !usesColor || (headSets.length > 0 && headSets.every(hs => p.skus.some(s => _skuMatchesAny(s, [hs]))));

  let list = _pickerState.products;
  if (f.brand) list = list.filter(p => p.manufacturer_label === f.brand);
  if (q) list = list.filter(p => p.model.toLowerCase().includes(q) || p.skus.some(s => (s.part_number || "").toLowerCase().includes(q)));
  // Vehicle-compat: drop products with no SKU that fits the selected vehicle.
  if (vehFiltering) list = list.filter(p => p.skus.some(s => _skuCompatible(s, veh)));
  list = [...list].sort((a, b) => {
    const am = isMatch(a), bm = isMatch(b);            // matching products first
    if (am !== bm) return am ? -1 : 1;
    const ap = pref.has((a.manufacturer_label || "").toLowerCase()), bp = pref.has((b.manufacturer_label || "").toLowerCase());
    if (ap !== bp) return ap ? -1 : 1;                  // then preferred brand
    return a.model.localeCompare(b.model);
  });

  if (!list.length) { el.innerHTML = header + `<div style="color:var(--muted);text-align:center;padding:40px">No products match these filters.</div>`; _pickerWireBrand(el); return; }
  if (list.length === 1) _pickerState.expanded.add(list[0].product_id);

  el.innerHTML = header + list.map(p => {
    const open = _pickerState.expanded.has(p.product_id);
    const selected = _pickerState.sel && _pickerState.sel.product_id === p.product_id;
    // SKUs shown for this product, narrowed to the selected vehicle when filtering.
    const skus = vehFiltering ? p.skus.filter(s => _skuCompatible(s, veh)) : p.skus;
    const prices = skus.map(s => s.price).filter(v => v != null);
    const priceStr = prices.length ? `from $${Math.min(...prices)}` : "";
    const qb = skus.some(s => s.qb) ? `<span class="pp-match ok">QB</span>` : "";
    // Programmable bars (WeCanX) carry no per-SKU colors → fall back to direct
    // SKU selection even inside a color category, so they stay pickable.
    const pColor = usesColor && _pickerProductHasColor(p);
    let matchBadge = "";
    if (pColor && headSets.length) {
      const allMatch = headSets.every(hs => p.skus.some(s => _skuMatchesAny(s, [hs])));
      matchBadge = allMatch ? `<span class="pp-match ok">match</span>` : `<span class="pp-match no">no exact</span>`;
    }

    // Body: color categories → per-combo SKU dropdown (override); else → SKU pick list.
    let bodyHtml = "";
    if (open) {
      if (pColor && selected) {
        bodyHtml = `<div class="pp-skus">` + headSets.map(hs => {
          const label = _pickerComboLabel(hs);
          const ordered = [...skus].sort((a, b) => {
            const am = _skuMatchesAny(a, [hs]), bm = _skuMatchesAny(b, [hs]);
            if (am !== bm) return am ? -1 : 1;
            const ar = _ionRank(a.part_number), br = _ionRank(b.part_number);
            if (ar !== br) return ar - br;
            return (a.price ?? 9e9) - (b.price ?? 9e9);
          });
          const hasMatch = ordered.some(s => _skuMatchesAny(s, [hs]));
          const key = hs.join(",");
          const chosen = _pickerState.skuChoices[key] || (ordered[0] && ordered[0].part_number) || "";
          const opts = ordered.map(s => {
            const cs = [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).join("/");
            const m = (cs && !_skuMatchesAny(s, [hs])) ? "  (other)" : "";
            return `<option value="${esc(s.part_number)}"${s.part_number === chosen ? " selected" : ""}>${esc(s.part_number)}${cs ? " · " + esc(cs) : ""}${s.lens_type ? " · " + esc(s.lens_type) : ""}${s.price != null ? " · $" + s.price : ""}${m}</option>`;
          }).join("");
          return `<div class="pp-sku"><span class="pp-sku-pn">${esc(label)}</span><select class="pp-override" data-combo="${esc(key)}">${opts}</select>${hasMatch ? "" : `<span class="pp-match no">no exact</span>`}</div>`;
        }).join("") + `</div>`;
      } else {
        bodyHtml = `<div class="pp-skus">` + skus.map(s => {
          const matched = pColor ? _skuMatchesAny(s, headSets) : true;
          const cls = pColor ? (matched ? "match" : "nomatch") : "";
          // Friendly name leads the description (clarifies non-light parts); falls
          // back to color/lens, which is description enough for lightheads.
          const colorBits = [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).map(x => x[0].toUpperCase() + x.slice(1)).join("/");
          const desc = [s.friendly_name, colorBits].filter(Boolean).join(" · ") || "—";
          const pr = s.price != null ? `$${s.price}` : "";
          const pickSel = _pickerState.sel && _pickerState.sel.sku === s.part_number && _pickerState.sel.product_id === p.product_id;
          const pick = !pColor ? `<button class="pf-pill${pickSel ? " active" : ""}" data-pick="${esc(s.part_number)}" data-pid="${esc(p.product_id)}">${pickSel ? "✓ Selected" : "Select"}</button>` : "";
          const pend = s.qb_pending ? `<span class="pp-pending" title="Not in QuickBooks yet — usable now, flagged on the estimate">pending QB</span>` : "";
          return `<div class="pp-sku ${cls}"><span class="pp-sku-pn">${esc(s.part_number)}</span><span class="pp-sku-c">${esc(desc)}${s.lens_type ? " · " + esc(s.lens_type) : ""}</span><span class="pp-mfr">${pr}</span>${pend}${pick}</div>`;
        }).join("") + `</div>`;
      }
    }

    return `<div class="pp-row${selected ? " sel" : ""}" data-pid="${esc(p.product_id)}">
      <div class="pp-head" data-pid="${esc(p.product_id)}">
        <span class="pp-caret">${open ? "▾" : "▸"}</span>
        <span class="pp-name">${esc(p.model)}</span>
        <span class="pp-mfr">${esc(p.manufacturer_label)}</span>
        <span class="pp-meta">${skus.length} SKU${skus.length !== 1 ? "s" : ""}${priceStr ? " · " + priceStr : ""}</span>
        ${matchBadge}${qb}
      </div>${bodyHtml}
    </div>`;
  }).join("");

  _pickerWireBrand(el);
  const vt = el.querySelector("#pp-veh-only");
  if (vt) vt.addEventListener("change", () => {
    _pickerState.vehicleOnly = vt.checked;
    try { localStorage.setItem("pp_vehicle_only", vt.checked ? "1" : "0"); } catch {}
    _pickerRenderProducts();
    _pickerRenderAccessories();
  });
  el.querySelectorAll(".pp-head").forEach(h => h.addEventListener("click", () => {
    const pid = h.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    const wasOpen = _pickerState.expanded.has(pid);
    if (wasOpen && (!usesColor || (_pickerState.sel && _pickerState.sel.product_id === pid))) _pickerState.expanded.delete(pid);
    else _pickerState.expanded.add(pid);
    // Color products select on head-click; no-color (programmable) products
    // select via the per-SKU "Select" pill instead.
    const pColor = usesColor && _pickerProductHasColor(p);
    if (pColor) { _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label }; _pickerState.skuChoices = {}; }
    _pickerRenderProducts(); _pickerUpdateFooter();
    if (pColor) { _pickerLoadAccessories(pid); _pickerLoadTracer(pid); }
  }));
  el.querySelectorAll("[data-pick]").forEach(btn => btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const pid = btn.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label, sku: btn.dataset.pick };
    _pickerRenderProducts(); _pickerUpdateFooter();
    _pickerLoadAccessories(pid);
    _pickerLoadTracer(pid);
  }));
  el.querySelectorAll(".pp-override").forEach(sel => sel.addEventListener("change", () => {
    _pickerState.skuChoices[sel.dataset.combo] = sel.value;
    _pickerUpdateFooter();
  }));
}

function _pickerWireBrand(el) {
  el.querySelectorAll("[data-brand]").forEach(b => b.addEventListener("click", () => {
    _pickerState.filters.brand = b.dataset.brand;
    _pickerRenderProducts();
  }));
}

// ── Location tab (vehicle diagram + dots) ──────────────

// Only the dash/headliner "interior" zone uses the synthetic Interior view.
// rear_interior placements (cargo/rear windows, rear interior light bar) have
// real coordinates in the exterior side/rear/top views, so they render there as
// normal dots — classifying them as interior hid them entirely.
const _INTERIOR_PZ = new Set(["interior"]);

async function _pickerRenderLocation() {
  const f = _pickerState.filters;
  const loc = _pickerState.loc;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  if (!loc.layouts) {
    try { loc.layouts = await api("/api/layouts"); } catch (e) { console.error("Picker: layouts failed:", e); loc.layouts = {}; }
  }
  try {
    // Product- AND vehicle-scoped: only placements this product can take that
    // also render in the planner's views for this vehicle (so they all load).
    const pid = _pickerState.sel ? _pickerState.sel.product_id : "";
    const res = await api(`/api/parts-db/category-locations?type=${encodeURIComponent(f.type_id)}&category=${encodeURIComponent(f.category_id || "")}&product=${encodeURIComponent(pid)}&vehicle=${encodeURIComponent(loc.vehicle)}`);
    loc.locByName = {};
    for (const l of (res?.locations || [])) loc.locByName[l.location.toUpperCase()] = l;
  } catch (e) { console.error("Picker: category-locations failed:", e); loc.locByName = {}; }
  _pickerDrawLocation();
}

function _pickerDrawLocation() {
  const loc = _pickerState.loc;
  const layoutViews = loc.layouts?.vehicles?.[loc.vehicle]?.views || {};
  // Interior placements for this category (drives whether internal view shows).
  const interiorLocs = Object.values(loc.locByName).filter(l => _INTERIOR_PZ.has(l.placement_zone));
  // Exterior views that actually have a category-relevant dot.
  const extViews = Object.keys(layoutViews).filter(vk => {
    if (vk.startsWith("internal")) return false;
    const locs = layoutViews[vk].locations || {};
    return Object.keys(locs).some(n => loc.locByName[n.toUpperCase()] && !_INTERIOR_PZ.has(loc.locByName[n.toUpperCase()].placement_zone));
  });
  const viewList = [...extViews];
  if (interiorLocs.length) viewList.push("interior");
  if (!viewList.includes(loc.view)) loc.view = viewList[0] || "front";

  const bar = $("picker-loc-views");
  if (bar) {
    bar.innerHTML = viewList.map(v => {
      const label = v === "interior" ? "Interior" : ((layoutViews[v]?.label) || v);
      return `<button class="pf-pill${loc.view === v ? " active" : ""}" data-view="${esc(v)}">${esc(label)}</button>`;
    }).join("");
    bar.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", () => { loc.view = b.dataset.view; _pickerDrawLocation(); }));
  }

  const img = $("picker-loc-img"), dots = $("picker-loc-dots"), btns = $("picker-loc-btns");
  if (loc.view === "interior") {
    if (img) img.style.display = "none";
    if (dots) dots.hidden = true;
    if (btns) {
      btns.hidden = false;
      btns.innerHTML = interiorLocs.map(l =>
        `<button class="pf-pill pf-big${loc.selected === l.location ? " active" : ""}" data-iloc="${esc(l.location)}">${esc(_pickerTitleCase(l.location))}</button>`).join("");
      btns.querySelectorAll("[data-iloc]").forEach(b => b.addEventListener("click", () => {
        loc.selected = b.dataset.iloc;
        const e = loc.locByName[b.dataset.iloc.toUpperCase()] || {};
        loc.name_pattern = e.name_pattern || ""; loc.base_label = e.base_label || "";
        loc.catalog_names = e.catalog_names || [];
        _pickerDrawLocation(); _pickerUpdateFooter();
      }));
    }
    _pickerUpdateFooter();
    return;
  }
  // Exterior: image + dots
  if (btns) btns.hidden = true;
  if (dots) dots.hidden = false;
  if (img) {
    img.style.display = "";
    img.onload = () => _pickerPlaceDots();
    img.src = `/assets/vehicles/${loc.vehicle}_${loc.view}.png`;
    if (img.complete) _pickerPlaceDots();
  }
}

// Fractional (0–1) slot positions for a location — ported verbatim from
// canvas.js getSlotPositions with box=[0,0,1,1] so mirror/horizontal spreads
// render identically to the placement settings preview.
function _pickerSlotPositions(loc, locationName) {
  const baseCx = loc.x, baseCy = loc.y;
  const pattern = loc.pattern || "single";
  let slotCount = loc.slot_count || 1;
  let slotIndices = null;

  // For TOP TUBE, apply quantity_rules from the location to determine which
  // dots are visible (mirrors the planner's per-location quantity_rules logic).
  if (locationName && locationName.toUpperCase() === "TOP TUBE") {
    const lightheadCount = _pickerState.config.count || 0;
    const rules = loc.quantity_rules || [];
    const match = rules.find(r => r.qty === lightheadCount);
    if (match) {
      if (match.slot_count) slotCount = match.slot_count;
      if (match.slot_indices) slotIndices = match.slot_indices;
    }
  }

  if (slotCount <= 1 || pattern === "single") return [[baseCx, baseCy]];
  const rawSpacing = loc.h_spacing ?? loc.spacing;
  const spacing = (rawSpacing && rawSpacing > 0) ? rawSpacing : 0.06;
  let positions;
  if (pattern === "horizontal") {
    const totalW = spacing * (slotCount - 1), startX = baseCx - totalW / 2;
    positions = Array.from({ length: slotCount }, (_, i) => [startX + i * spacing, baseCy]);
  } else if (pattern === "mirror") {
    const centerX = 0.5, offsetX = Math.abs(baseCx - centerX);
    if (slotCount === 2) {
      positions = [[centerX - offsetX, baseCy], [centerX + offsetX, baseCy]];
    } else {
      const half = Math.floor(slotCount / 2);
      positions = [];
      for (let i = 0; i < half; i++) {
        const off = offsetX + i * spacing;
        positions.push([centerX - off, baseCy]); positions.push([centerX + off, baseCy]);
      }
    }
  } else {
    return [[baseCx, baseCy]];
  }
  if (slotIndices) return slotIndices.filter(i => i < positions.length).map(i => positions[i]);
  return positions;
}

function _pickerPlaceDots() {
  const loc = _pickerState.loc;
  const stage = $("picker-loc-stage"), img = $("picker-loc-img"), dots = $("picker-loc-dots");
  if (!stage || !img || !dots) return;
  // Position the dot overlay onto the ACTUAL rendered image box (same idea as
  // placement settings' getImageBox/contain). getBoundingClientRect reflects
  // exactly what the browser drew, so dots line up regardless of letterboxing.
  const sr = stage.getBoundingClientRect(), ir = img.getBoundingClientRect();
  const w = ir.width, h = ir.height;
  if (!w || !h) return;   // image not laid out yet
  dots.style.left = (ir.left - sr.left) + "px";
  dots.style.top = (ir.top - sr.top) + "px";
  dots.style.right = "auto"; dots.style.bottom = "auto";  // override inset:0
  dots.style.width = w + "px";
  dots.style.height = h + "px";

  const locs = loc.layouts?.vehicles?.[loc.vehicle]?.views?.[loc.view]?.locations || {};
  const names = Object.keys(locs).filter(n => {
    const e = loc.locByName[n.toUpperCase()];
    return e && !_INTERIOR_PZ.has(e.placement_zone);
  });
  if (!names.length) {
    dots.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted)">No mapped locations for this view.</div>`;
    return;
  }
  // Draw every slot for each location (mirror/horizontal spreads), mirroring
  // placement settings exactly — a location with pattern:mirror shows its
  // driver+passenger dots, not one centered dot. Clicking any selects it.
  dots.innerHTML = names.map(n => {
    const c = locs[n];
    const selected = loc.selected === n;
    return _pickerSlotPositions(c, n).map(([fx, fy]) =>
      `<button class="picker-dot${selected ? " sel" : ""}" data-name="${esc(n)}" style="left:${(fx * 100).toFixed(2)}%;top:${(fy * 100).toFixed(2)}%"></button>`
    ).join("");
  }).join("") + `<div class="picker-dot-tip" id="picker-dot-tip" hidden></div>`;

  const tip = $("picker-dot-tip");
  const allDots = [...dots.querySelectorAll(".picker-dot")];
  allDots.forEach(d => {
    // Instant custom tooltip + highlight ALL slots of this location (mirror pair).
    d.addEventListener("mouseenter", () => {
      allDots.forEach(o => { if (o.dataset.name === d.dataset.name) o.classList.add("hover"); });
      if (tip) {
        tip.textContent = _pickerTitleCase(d.dataset.name);
        tip.style.left = d.style.left;
        tip.style.top = d.style.top;
        tip.hidden = false;
      }
    });
    d.addEventListener("mouseleave", () => {
      allDots.forEach(o => o.classList.remove("hover"));
      if (tip) tip.hidden = true;
    });
    d.addEventListener("click", () => {
      loc.selected = d.dataset.name;
      const entry = loc.locByName[d.dataset.name.toUpperCase()] || {};
      loc.name_pattern = entry.name_pattern || "";
      loc.base_label = entry.base_label || "";
      loc.catalog_names = entry.catalog_names || [];
      _pickerPlaceDots();
      _pickerUpdateFooter();
    });
  });
}

function _pickerTitleCase(s) {
  const small = new Set(["of", "and", "the", "a", "in", "on"]);
  return String(s).toLowerCase().split(/\s+/).map((w, i) => (small.has(w) && i > 0) ? w : w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// ── Footer (context-dependent primary action) ──────────

// A row of lighthead swatches showing exactly what's about to be added —
// one head per lighthead, in the chosen order, stacked by its colors.
function _pickerHeadsPreviewHtml() {
  if (!_pickerUsesColor()) return "";
  const heads = _pickerResolveHeads();
  return `<span class="picker-foot-heads">` + heads.map(h => {
    const segs = h.map(col => { const d = _PICKER_COLORS[col] || { hex: "#999" }; return `<span style="background:${d.hex};border:1px solid ${d.border || "rgba(0,0,0,.18)"}"></span>`; }).join("");
    return `<span class="picker-foot-head" title="${esc(h.map(c => c[0].toUpperCase() + c.slice(1)).join("/"))}">${segs}</span>`;
  }).join("") + `</span>`;
}

// ── Accessories (Phase 5) ──────────────────────────────

// Fetch + render the accessories for the selected product. Edit mode is not
// handled yet, so the section stays hidden there.
async function _pickerLoadAccessories(productId) {
  if (!productId || _pickerState.editLineId) {
    _pickerState.accessories = []; _pickerState.accessoryChoices = {};
    _pickerState.accLoadedFor = productId || null;
    _pickerRenderAccessories(); _pickerUpdateFooter(); return;
  }
  if (_pickerState.accLoadedFor === productId) return;   // already loaded
  _pickerState.accLoadedFor = productId;
  try {
    const res = await api(`/api/parts-db/accessories?product_id=${encodeURIComponent(productId)}`);
    _pickerState.accessories = (res && res.accessories) || [];
  } catch (e) { console.error("accessories load failed:", e); _pickerState.accessories = []; }
  // Reset to unset so every category demands an explicit decision.
  _pickerState.accessoryChoices = {};
  for (const g of _pickerState.accessories) _pickerState.accessoryChoices[g.category] = "";
  _pickerRenderAccessories();
  _pickerUpdateFooter();
}

function _pickerAccLabel(opt, sku) {
  const colors = [sku.color, sku.secondary_color].filter(Boolean).map(c => c[0].toUpperCase() + c.slice(1)).join("/");
  const price = sku.price != null ? ` · $${sku.price}` : "";
  // Prefer a curated short description (friendly_name) so installers don't have
  // to decipher part numbers; fall back to the product model. SKU + price always
  // shown so the orderable number stays visible.
  const lead = sku.friendly_name || opt.model;
  const pend = sku.qb_pending ? " · ⧗ pending QB" : "";
  return `${lead} · ${sku.part_number}${colors ? " · " + colors : ""}${price}${pend}`;
}

function _pickerRenderAccessories() {
  const el = $("picker-accessories");
  if (!el) return;
  const groups = _pickerVisibleAccessoryGroups();
  if (!groups.length) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  const rows = groups.map(g => {
    const val = _pickerState.accessoryChoices[g.category] || "";
    let opts = `<option value=""${val === "" ? " selected" : ""} disabled>— Choose —</option>`;
    if (!g.required) opts += `<option value="none"${val === "none" ? " selected" : ""}>— None needed —</option>`;
    for (const o of g.options) for (const s of (o.skus || [])) {
      // Vehicle-compat: hide accessory SKUs that don't fit the selected vehicle,
      // unless it's the currently-chosen one (never hide a live selection).
      const v = `${o.product_id}::${s.part_number}`;
      if (vehFiltering && val !== v && !_skuCompatible(s, veh)) continue;
      opts += `<option value="${esc(v)}"${val === v ? " selected" : ""}>${esc(_pickerAccLabel(o, s))}</option>`;
    }
    return `<div class="pa-row"><label>${esc(g.label)}${g.required ? '<span class="pa-req">*</span>' : ""}</label>`
         + `<select class="${val ? "pa-chosen" : "pa-unset"}" data-cat="${esc(g.category)}">${opts}</select></div>`;
  }).join("");
  const pending = !_accessoriesSatisfied();
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">${groups.length}</span>`
    + `${pending ? "This part has accessories — choose each one to continue" : "Accessories set ✓"}</div>`
    + `<div class="pa-rows">${rows}</div>`;
  el.querySelectorAll("select[data-cat]").forEach(sel => sel.addEventListener("change", () => {
    _pickerState.accessoryChoices[sel.dataset.cat] = sel.value;
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
}

// Accessory groups the picker actually shows. The tracer panel owns lighthead
// selection, so for tracers the (redundant, required) lighthead dropdown is
// hidden — brackets/cables/etc. still show.
function _pickerVisibleAccessoryGroups() {
  const groups = _pickerState.accessories || [];
  if (_pickerState.tracer && _pickerState.tracer.active)
    return groups.filter(g => g.category !== "lighthead");
  return groups;
}

function _accessoriesSatisfied() {
  for (const g of _pickerVisibleAccessoryGroups()) {
    const v = _pickerState.accessoryChoices[g.category];
    if (!v) return false;                        // not yet addressed
    if (g.required && v === "none") return false;
  }
  return true;
}

// ── Tracer / head-parent config ────────────────────────
// Tracers (and bars with child lightheads) replace the color matrix with a
// simple Standard Duo / Standard Trio + White/Amber choice; the server resolves
// the exact housings + head SKUs. See docs/TRACER_LIGHTHEAD_SELECTION.md.
const _TRACER_LAMP_RE = /\b\d+\s*-?\s*lamp\b/i;

function _pickerIsTracer(product) {
  return !!product && _TRACER_LAMP_RE.test(product.model || "");
}

async function _pickerLoadTracer(productId) {
  const t = _pickerState.tracer;
  const product = _pickerState.products.find(p => p.product_id === productId);
  if (!productId || _pickerState.editLineId || !_pickerIsTracer(product)) {
    _pickerState.tracer = { active: false, mode: t.mode, secondary: t.secondary, preview: null, loading: false };
    _pickerRenderTracer(); return;
  }
  _pickerState.tracer = { ...t, active: true, preview: null, loading: true };
  _pickerRenderTracer();
  await _pickerFetchTracerPreview();
}

async function _pickerFetchTracerPreview() {
  const t = _pickerState.tracer, sel = _pickerState.sel;
  if (!t.active || !sel) return;
  const lens = (_pickerState.filters.lens === "smoked") ? "smoked" : "clear";
  t.loading = true; _pickerRenderTracer();
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&mode=${t.mode}&secondary=${t.secondary}&lens=${lens}`;
    t.preview = await api(`/api/parts-db/tracer-heads?${qs}`);
  } catch (e) {
    console.error("tracer resolve failed:", e);
    t.preview = { ok: false, error: "request_failed", lines: [], problems: [] };
  }
  t.loading = false;
  _pickerRenderTracer(); _pickerUpdateFooter();
}

function _pickerRenderTracer() {
  const el = $("picker-tracer"); if (!el) return;
  const t = _pickerState.tracer;
  if (!t.active) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const lens = (_pickerState.filters.lens === "smoked") ? "smoked" : "clear";
  const pill = (k, v, label, on) =>
    `<button class="pf-pill${on ? " active" : ""}" data-tk="${k}" data-tv="${v}">${esc(label)}</button>`;
  const p = t.preview;
  let body = "";
  if (t.loading) body = `<div class="pt-preview muted">Resolving…</div>`;
  else if (p && p.ok) {
    body = `<div class="pt-preview">` + (p.lines || []).map(l => {
      const pend = l.pending ? ` <span class="pp-pending">pending QB</span>` : "";
      const role = l.role ? " · " + l.role : "";
      return `<div class="pt-line"><span class="pt-qty">${l.qty}×</span> <span class="pt-sku">${esc(l.sku)}</span> <span class="pt-role">${esc(l.kind)}${esc(role)}</span>${pend}</div>`;
    }).join("") + `</div>`;
  } else if (p) {
    const probs = (p.problems || []).map(pr =>
      pr.reason === "missing_head_sku"
        ? `Need a ${esc((pr.colors || []).join("/"))} ${esc(pr.lens)} ${esc(pr.role)} head — not in the catalog yet.`
        : esc(pr.detail || pr.reason)).join("<br>");
    body = `<div class="pt-preview err">⚠ Can't build this combo yet:<br>${probs}</div>`;
  }
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">⚡</span>Tracer lightheads — choose a configuration</div>
    <div class="pt-rows">
      <div class="pf-group"><span class="pf-label">Heads</span><div class="pf-pills">
        ${pill("mode", "duo", "Standard Duo", t.mode === "duo")}
        ${pill("mode", "trio", "Standard Trio", t.mode === "trio")}</div></div>
      <div class="pf-group"><span class="pf-label">Secondary color</span><div class="pf-pills">
        ${pill("secondary", "white", "White", t.secondary === "white")}
        ${pill("secondary", "amber", "Amber", t.secondary === "amber")}</div></div>
      <div class="pf-group"><span class="pf-label">Lens</span><span class="pt-lens">${esc(lens)} · from filter</span></div>
    </div>${body}`;
  el.querySelectorAll("[data-tk]").forEach(b => b.addEventListener("click", () => {
    _pickerState.tracer[b.dataset.tk] = b.dataset.tv;
    _pickerFetchTracerPreview();
  }));
}

function _pickerTracerSatisfied() {
  const t = _pickerState.tracer;
  if (!t.active) return true;
  return !!(t.preview && t.preview.ok);
}

// Build the accessory part rows chosen for the current selection.
function _pickerChosenAccessoryRows(parentName, locName, parentLineId) {
  const rows = [];
  const parentProduct = _pickerState.sel ? _pickerState.sel.product_id : "";
  for (const g of _pickerVisibleAccessoryGroups()) {
    const v = _pickerState.accessoryChoices[g.category];
    if (!v || v === "none") continue;
    const [pidPart, sku] = v.split("::");
    const opt = g.options.find(o => o.product_id === pidPart);
    if (!opt) continue;
    rows.push({
      name: `${parentName} · ${opt.model}`,
      location: locName, manufacturer: opt.manufacturer_label || "",
      part_number: sku, quantity: 1, new_or_used: "New", source: "",
      parent_line_id: parentLineId || "",
      accessory_category: g.category,
      accessory_parent_product: parentProduct,
    });
  }
  return rows;
}

function _pickerUpdateFooter() {
  const text = $("picker-footer-text"), btn = $("picker-add-btn");
  if (!text || !btn) return;
  const sel = _pickerState.sel, loc = _pickerState.loc;
  const usesColor = _pickerUsesColor();
  const accOk = _accessoriesSatisfied();
  const tracerOk = _pickerTracerSatisfied();
  const ready = accOk && tracerOk;            // all required sub-choices addressed
  const hasAcc = _pickerVisibleAccessoryGroups().length > 0;
  const selName = sel ? (sel.model + (sel.sku ? " · " + sel.sku : "")) : "";
  const preview = (sel && usesColor) ? _pickerHeadsPreviewHtml() : "";
  let hint = (sel && hasAcc && !accOk) ? ' <span class="picker-foot-acc">· choose accessories</span>' : "";
  if (sel && _pickerState.tracer.active && !tracerOk)
    hint += ' <span class="picker-foot-acc">· configure lightheads</span>';
  if (_pickerState.tab === "part") {
    text.innerHTML = sel ? `${preview}<span class="picker-foot-label">${esc(selName)}</span>${hint}` : `<span class="picker-foot-label">Pick a product</span>`;
    if (_pickerState.editLineId) {
      // Editing: save the part change directly (location keeps its current value
      // unless the user visits the Location tab to change it).
      btn.textContent = "Save edits";
      btn.disabled = !(sel && ready);
      _pickerState.footerHandler = (sel && ready) ? _pickerDoAdd : null;
    } else {
      btn.textContent = "Choose location →";
      btn.disabled = !(sel && ready);
      _pickerState.footerHandler = (sel && ready) ? () => _pickerSwitchTab("location") : null;
    }
  } else {
    const where = loc.selected ? _pickerTitleCase(loc.selected) : "";
    text.innerHTML = sel ? `${preview}<span class="picker-foot-label">${esc(selName)}${where ? " → " + esc(where) : ""}</span>${hint}` : `<span class="picker-foot-label">Pick a product first</span>`;
    btn.textContent = "Add Part";
    btn.disabled = !(sel && loc.selected && ready);
    _pickerState.footerHandler = (sel && loc.selected && ready) ? _pickerDoAdd : null;
  }
}

// ── Resolve + add ──────────────────────────────────────

function _pickerColorFields() {
  const c = _pickerState.config;
  const cap = arr => arr.map(x => x.charAt(0).toUpperCase() + x.slice(1)).join("/");
  if (c.mode === "uniform") return { raw_color: cap(c.uniform) };
  if (c.mode === "split") {
    const d = cap(["red", ...c.splitSecondary]), p = cap(["blue", ...c.splitSecondary]);
    return { raw_color: `${d} / ${p}`, driver_color: d, passenger_color: p };
  }
  const labels = [...new Set(_pickerResolveHeads().map(h => cap(h)))];
  return { raw_color: labels.join(", ") };
}

// Pick the next auto-sequenced name by counting existing draft parts with the
// same base name (e.g. 2 existing "Forward Warning *" → "Forward Warning 3").
function _pickerChooseName(loc) {
  return _pickerSequencedName(loc.name_pattern, loc.base_label);
}

function _pickerSequencedName(pattern, base) {
  pattern = pattern || "";
  if (pattern.includes("{n}")) {
    const prefix = pattern.split("{n}")[0].trim().toLowerCase();
    let max = 0;
    for (const p of (typeof _meDraft !== "undefined" && _meDraft ? _meDraft.parts || [] : [])) {
      const nm = (p.name || "").trim().toLowerCase();
      if (prefix && nm.startsWith(prefix)) { const n = parseInt(nm.slice(prefix.length).trim(), 10); if (!isNaN(n)) max = Math.max(max, n); }
    }
    return pattern.replace("{n}", String(max + 1));
  }
  return pattern || base || "Part";
}

async function _pickerDoAdd() {
  const sel = _pickerState.sel, loc = _pickerState.loc, f = _pickerState.filters;
  // When editing, fall back to the part's existing location if the user didn't
  // open the Location tab to change it (so "Save edits" works from the Part tab).
  if (!loc.selected && _pickerState.editLineId && _pickerState.editPart) {
    loc.selected = _pickerState.editPart.location;
  }
  if (!sel || !loc.selected) return;
  const draftId = (typeof _meDraftId !== "undefined") ? _meDraftId : null;
  if (!draftId) { toast("No active build", "error"); return; }

  // Tracer path: the resolver gives housings + per-side heads; add each housing
  // as a parent line, its heads nested beneath, with a Duo/Trio tag.
  if (_pickerState.tracer.active) { await _pickerAddTracer(draftId); return; }

  const product = _pickerState.products.find(p => p.product_id === sel.product_id);
  // Color path only for color-configured products; a direct SKU pick (sel.sku,
  // e.g. a programmable bar) always uses the simple single-SKU path.
  const usesColor = f.type_id === "lights" && _COLOR_CATEGORIES.has(f.category_id)
    && !sel.sku && _pickerProductHasColor(product || { skus: [] });
  const locName = loc.selected;   // raw layout key (planner upper-cases to match)
  const baseName = _pickerChooseName(loc) || sel.model;

  let combos, colorFields = {}, totalHeads = 0;
  if (usesColor) {
    // match heads → combos (server, for correctness)
    const heads = _pickerResolveHeads();
    totalHeads = heads.length;
    let m;
    try { m = await api("/api/parts-db/match-skus", { product_id: sel.product_id, heads, lens: f.lens || "" }); }
    catch (e) { console.error(e); toast("Match failed", "error"); return; }
    const skuById = {};
    (product?.skus || []).forEach(s => { skuById[s.part_number] = s; });
    combos = (m.combos || []).map(cb => {
      const key = (cb.colors || []).map(c => c.toLowerCase()).sort().join(",");
      const override = _pickerState.skuChoices[key];
      const pn = override || cb.default_sku;
      if (!pn) return null;   // no match and no override for this combo
      const price = (skuById[pn] && skuById[pn].price) ?? (cb.skus[0] && cb.skus[0].price) ?? null;
      return { colors: cb.colors, part_number: pn, quantity: cb.count, price };
    }).filter(Boolean);
    if (!combos.length) { toast("No SKU chosen for those colors — pick one on the right, or adjust colors/lens", "error"); return; }
    colorFields = _pickerColorFields();
  } else {
    const sku = sel.sku || (product && product.skus[0] && product.skus[0].part_number);
    if (!sku) { toast("Pick a SKU", "error"); return; }
    const skuObj = product.skus.find(s => s.part_number === sku) || {};
    combos = [{ colors: [], part_number: sku, quantity: 1, price: skuObj.price || null }];
    totalHeads = 1;
  }

  const btn = $("picker-add-btn"); if (btn) btn.disabled = true;
  let resolved;
  try {
    resolved = await api("/api/parts-db/resolve-selection", {
      product_model: sel.model, manufacturer_label: sel.mfr || "",
      location: locName, base_name: baseName, lens: f.lens || "",
      combos, color_fields: colorFields, total_heads: totalHeads,
    });
  } catch (e) { console.error("resolve failed:", e); toast("Resolve failed", "error"); if (btn) btn.disabled = false; return; }

  const rows = resolved.rows || [];
  if (!rows.length) { toast("Nothing to add", "error"); if (btn) btn.disabled = false; return; }

  let ok = 0, parentLineId = "";
  for (const row of rows) {
    try {
      const endpoint = _pickerState.editLineId
        ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
        : `/api/draft/${draftId}/part`;
      const r = await api(endpoint, row);
      if (r?.ok) { ok++; if (!parentLineId && r.line_id) parentLineId = r.line_id; }
    } catch (e) { console.error("add row failed:", e); }
  }
  if (!ok) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }

  // Accessories → their own child lines under the parent (new adds only).
  if (!_pickerState.editLineId) {
    const accRows = _pickerChosenAccessoryRows(baseName, locName, parentLineId);
    for (const arow of accRows) {
      try { await api(`/api/draft/${draftId}/part`, arow); }
      catch (e) { console.error("add accessory failed:", e); }
    }
  }
  toast(_pickerState.editLineId ? "Part updated" : "Part added", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  pickerClose();
  if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
  if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") pvLoad(draftId);
}

// Add a resolved tracer: each housing → a parent line tagged Duo/Trio, its
// heads nested beneath as lighthead children. Re-resolves server-side so the
// add matches the latest choice (mode/secondary/lens).
async function _pickerAddTracer(draftId) {
  const sel = _pickerState.sel, loc = _pickerState.loc, t = _pickerState.tracer;
  const locName = loc.selected;
  const baseName = _pickerChooseName(loc) || sel.model;
  const lens = (_pickerState.filters.lens === "smoked") ? "smoked" : "clear";
  const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  const btn = $("picker-add-btn"); if (btn) btn.disabled = true;

  let res;
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&mode=${t.mode}&secondary=${t.secondary}&lens=${lens}`;
    res = await api(`/api/parts-db/tracer-heads?${qs}`);
  } catch (e) { console.error("tracer resolve failed:", e); toast("Resolve failed", "error"); if (btn) btn.disabled = false; return; }
  if (!res || !res.ok) { toast("Can't build this tracer config yet", "error"); if (btn) btn.disabled = false; return; }

  const modeLabel = (t.mode === "trio" ? "Trio" : "Duo") + " · " + cap(t.secondary);
  let added = 0;
  for (const h of res.housings || []) {
    const sideTag = h.side === "front" ? "" : ` (${cap(h.side)})`;
    let parentLineId = "";
    try {
      const r = await api(`/api/draft/${draftId}/part`, {
        name: `${baseName}${sideTag} · ${modeLabel}`, location: locName,
        manufacturer: sel.mfr || "", part_number: h.sku, quantity: h.qty || 1,
        new_or_used: "New", source: "",
      });
      if (r?.ok) { added++; parentLineId = r.line_id || ""; }
    } catch (e) { console.error("tracer housing add failed:", e); }
    for (const hd of (h.heads || [])) {
      if (hd.missing || !hd.sku) continue;
      const colors = (hd.colors || []).map(cap).join("/");
      try {
        await api(`/api/draft/${draftId}/part`, {
          name: `${baseName} · ${cap(hd.role)} ${colors}`, location: locName,
          manufacturer: sel.mfr || "", part_number: hd.sku, quantity: hd.qty || 1,
          new_or_used: "New", source: "", parent_line_id: parentLineId,
          accessory_category: "lighthead", accessory_parent_product: sel.product_id,
        });
      } catch (e) { console.error("tracer head add failed:", e); }
    }
  }
  if (!added) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }
  toast("Tracer added", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  pickerClose();
  if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
  if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") pvLoad(draftId);
}
