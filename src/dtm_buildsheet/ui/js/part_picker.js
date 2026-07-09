// ═══════════════════════════════════════════════════════
// PART PICKER — two-pane (filters | live product list) + dot-picker location
// Tabs: Part / Location. Same UI for Add and Edit. No typing except search.
// ═══════════════════════════════════════════════════════

// Browse-tree accordion expansion state (PICKER_REDESIGN.md Step 1) — kept
// OUTSIDE _pickerState so it survives _pickerResetState() and persists across
// picker opens within the session (Step 7's return-to-position depends on it).
let _pickerBrowseExpanded = { types: new Set(), families: new Set() };

let _pickerState = {
  open: false,
  editLineId: null,
  editPart: null,
  tab: "part",
  types: [],
  browseTree: [],
  filters: { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", part_type_id: "", part_type_label: "", brand: "", lens: "" },
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
  tracer: { active: false, mode: "trio", secondary: "white", custom: {}, preview: null, loading: false },
  lightbar: { active: false, setup: "standard", edition: "clear", notes: "" },
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
// Roof bars are ordered as whole configured SKUs (colors baked in), so they're
// NOT a color-config category — no head-color preview/matrix, just pick the SKU.
const _COLOR_CATEGORIES = new Set(["warning", "scene", "interior", "interior_bar", "spotlight"]);

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
  // Clear the tracer + accessory panels so they don't persist into the next open.
  _pickerState.tracer = { active: false, mode: _pickerState.tracer.mode,
                          secondary: _pickerState.tracer.secondary, preview: null, loading: false };
  _pickerState.accessories = []; _pickerState.accLoadedFor = null;
  _pickerState.tracer.active = false; _pickerState.lightbar.active = false;
  _pickerRenderTracer(); _pickerRenderLightbar();
  const acc = $("picker-accessories"); if (acc) { acc.hidden = true; acc.innerHTML = ""; }
  const panel = $("picker-panel");
  if (panel) panel.classList.remove("open");
}

// Cancel the current product selection and close the bottom config panels
// (tracer / lightbar / accessories) so they stop blocking the product list.
function _pickerClearSelection() {
  _pickerState.sel = null;
  _pickerState.tracer.active = false;
  _pickerState.lightbar.active = false;
  _pickerState.accessories = []; _pickerState.accessoryChoices = {}; _pickerState.accLoadedFor = null;
  _pickerResetLocation();
  _pickerRenderProducts();
  _pickerRenderTracer(); _pickerRenderLightbar(); _pickerRenderAccessories();
  _pickerUpdateFooter();
}

// FINDING-005 (LEDGER.md): edit mode is hard-coded to `type_id="lights"` and
// only prefills a product match, category/config/accessories are never
// restored, so editing a non-light part shows the wrong product list. The
// fix here is a data-loss STOPGAP ONLY (dirty-tracking so an untouched
// control can't clobber name/quantity/raw_color) — the real prefill/contract
// redesign (type/category/config prefill, non-lights product list, accessory
// editing) is a separate NEEDS-DESIGN task; see LEDGER.md FINDING-005.
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
    // Carry the matched SKU into `sel.sku` so an untouched product falls
    // through the existing `sel.sku || product.skus[0]...` logic in
    // _pickerDoAdd instead of silently substituting the product's first SKU
    // (part of FINDING-005's "SKU/model clobber" — this keeps the stored SKU
    // whenever the user never re-picks a product).
    _pickerState.sel = { product_id: prod.product_id, model: prod.model, mfr: prod.manufacturer_label, sku: pn };
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
  _pickerState.filters = { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", part_type_id: "", part_type_label: "", brand: "", lens: "" };
  _pickerState.config = { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false };
  _pickerState.search = "";
  _pickerState.products = [];
  _pickerState.expanded = new Set();
  _pickerState.sel = null;
  _pickerState.skuChoices = {};   // "head_N" → chosen part_number (per-head override, Step 3)
  _pickerState.optionsRemoved = false;
  _pickerState.loc = { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, name_pattern: "", base_label: "" };
  _pickerState.accessories = [];
  _pickerState.accessoryChoices = {};
  _pickerState.accLoadedFor = null;
  _pickerState.tracer = { active: false, mode: "trio", secondary: "white", custom: {}, preview: null, loading: false };
  _pickerState.lightbar = { active: false, setup: "standard", edition: "clear", notes: "" };
  // Edit-mode dirty tracking (FINDING-005 stopgap): which control groups the
  // user has actually touched since ≡ Edit opened. Save stays disabled, and
  // editPart.name/quantity/raw_color stay intact, until the corresponding
  // group is touched — see _pickerDoAdd and _pickerUpdateFooter.
  _pickerState._editTouched = { product: false, color: false, location: false };
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
  try {
    const res = await api("/api/parts-db/browse-tree");
    _pickerState.browseTree = res?.categories || [];
  } catch (e) { console.error("Picker: browse-tree failed:", e); _pickerState.browseTree = []; }
}

// ── Data ───────────────────────────────────────────────

async function _pickerFetchProducts() {
  const f = _pickerState.filters;
  try {
    // The exact part_type filter only applies outside the lights category
    // flow (f.category_id set) — a light family's leaf still hands off to the
    // existing whole-category flow unchanged (PICKER_REDESIGN.md Step 1).
    const ptParam = (f.part_type_id && !f.category_id) ? `&part_type=${encodeURIComponent(f.part_type_id)}` : "";
    const url = `/api/parts-db/category-skus?type=${encodeURIComponent(f.type_id)}&category=${encodeURIComponent(f.category_id || "")}${ptParam}`;
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
// PICKER_REDESIGN.md Step 2: steps are now always just [browse]. Options
// (mode/lens/color/cph/qty) live in the selected product's box, not the
// sidebar, so there is no "Colors & options" step to push to.
function _pickerSteps() {
  return [{ id: "browse", label: "Browse" }];
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

  // Steps is always [browse] (Step 2: options live in the product box).
  const content = _pickerBrowseTreeHtml();

  el.innerHTML = `<div class="pf-group pf-search"><input type="text" id="pf-search" placeholder="🔍 Search products / SKUs" value="${esc(_pickerState.search)}"></div>
    <div class="pf-crumbs">${crumbs}</div>
    <div class="pf-stepbody">${content}</div>`;
  _pickerWireFilters();
}

// ── Browse-tree accordion (PICKER_REDESIGN.md Step 1) ──
// category (type_id) → family? → part_type. Every category expands inline;
// families expand again to their member part types. Selecting a leaf hands
// off to the existing downstream flow (colors/SKU/location) unchanged.

// Step 1b: part_type_ids with a real part already in the current draft's
// manifest (picker-created parts carry `part_type`; legacy name-based parts
// have none and are simply not highlighted — best-effort, per spec).
function _pickerManifestFilledPartTypes() {
  const parts = (typeof _meDraft !== "undefined" && _meDraft && _meDraft.parts) || [];
  return new Set(parts.map(p => p.part_type).filter(Boolean));
}

function _pickerBrowseTreeHtml() {
  const _TYPE_ORDER = ["lights", "structural", "equipment", "k9", "extras"];
  const _buildType = (window._PT?.viewProject?.info?.BuildType || window._PT?.viewProject?.vehicle_info?.BuildType || "").toLowerCase();
  const _isK9Build = _buildType.includes("k-9") || _buildType.includes("k9");
  const filled = _pickerManifestFilledPartTypes();
  const cats = [...(_pickerState.browseTree || [])]
    .filter(c => c.type_id !== "k9" || _isK9Build)
    .sort((a, b) => {
      const ai = _TYPE_ORDER.indexOf(a.type_id), bi = _TYPE_ORDER.indexOf(b.type_id);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    });

  const leafHtml = (pt, cat, pickerFlow) => {
    const isFilled = filled.has(pt.part_type_id);
    const active = _pickerState.filters.part_type_id === pt.part_type_id && _pickerState.filters.type_id === cat.type_id;
    return `<button class="pbt-leaf${isFilled ? " filled" : ""}${active ? " active" : ""}"
      data-type="${esc(cat.type_id)}" data-type-label="${esc(cat.label)}"
      data-pt="${esc(pt.part_type_id)}" data-pt-label="${esc(pt.label)}"
      data-flow="${esc(pickerFlow || "")}">${esc(pt.label)}${isFilled ? ` <span class="pbt-dot" title="Already in this build"></span>` : ""}</button>`;
  };

  const childHtml = (child, cat) => {
    if (child.kind === "part_type") return leafHtml(child, cat, "");
    const open = _pickerBrowseExpanded.families.has(child.family_id);
    const anyFilled = child.members.some(m => filled.has(m.part_type_id));
    const members = open ? child.members.map(m => leafHtml(m, cat, child.picker_flow)).join("") : "";
    return `<div class="pbt-fam">
      <button class="pbt-fam-head${open ? " open" : ""}" data-fam="${esc(child.family_id)}">
        <span class="pbt-caret">${open ? "▾" : "▸"}</span>${esc(child.label)}${anyFilled ? ` <span class="pbt-dot" title="Has parts in this build"></span>` : ""}
      </button>
      <div class="pbt-fam-body">${members}</div>
    </div>`;
  };

  return cats.map(cat => {
    const open = _pickerBrowseExpanded.types.has(cat.type_id);
    const anyFilled = (cat.children || []).some(c =>
      c.kind === "part_type" ? filled.has(c.part_type_id) : c.members.some(m => filled.has(m.part_type_id)));
    const body = open ? (cat.children || []).map(c => childHtml(c, cat)).join("") : "";
    return `<div class="pbt-cat">
      <button class="pbt-cat-head${open ? " open" : ""}" data-cat="${esc(cat.type_id)}">
        <span class="pbt-caret">${open ? "▾" : "▸"}</span>${_TYPE_ICONS[cat.type_id] || "📦"} ${esc(cat.label)}${anyFilled ? ` <span class="pbt-dot" title="Has parts in this build"></span>` : ""}
      </button>
      <div class="pbt-cat-body">${body}</div>
    </div>`;
  }).join("");
}

// Prepend the "Remove options" button and, when options are inactive, visually
// dim the controls so the user can see the filter is off (Step 3).
function _pickerOptionsHtml(inner) {
  const off = _pickerState.optionsRemoved || false;
  const btn = `<div class="pf-group pp-opts-ctrl"><button class="pf-pill${off ? " active" : ""}" data-opts-remove="1">${off ? "⊘ Filter off" : "Remove options"}</button>${off ? `<span class="pf-hint">All SKUs shown — click any option to re-apply filter</span>` : ""}</div>`;
  return btn + (off ? `<div class="pp-opts-inactive">${inner}</div>` : inner);
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
    return _pickerOptionsHtml(countHtml + `<div class="pf-group"><span class="pf-label">Colors per head</span><div class="pf-pills">
        ${seg("cph", "duo", "Duo", c.colorsPerHead !== "trio")}
        ${seg("cph", "trio", "Trio", c.colorsPerHead === "trio")}</div></div>` + lensHtml);
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
    return _pickerOptionsHtml(countHtml + cphHtml +
      `<div class="pf-group"><span class="pf-label">Color</span>` +
      `<div class="picker-swatches" data-kind="uniform" data-slot="0">${whiteSwatches}${noneBtn}</div></div>` + lensHtml);
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

  return _pickerOptionsHtml(countHtml + cphHtml + modeHtml + sel + lensHtml);
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

  // Browse-tree accordion: category/family headers toggle expansion in place
  // (no navigate-away, no re-fetch); a leaf part_type selects and hands off.
  el.querySelectorAll(".pbt-cat-head").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.cat;
    if (_pickerBrowseExpanded.types.has(id)) _pickerBrowseExpanded.types.delete(id);
    else _pickerBrowseExpanded.types.add(id);
    _pickerRenderFilters();
  }));
  el.querySelectorAll(".pbt-fam-head").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.fam;
    if (_pickerBrowseExpanded.families.has(id)) _pickerBrowseExpanded.families.delete(id);
    else _pickerBrowseExpanded.families.add(id);
    _pickerRenderFilters();
  }));
  el.querySelectorAll(".pbt-leaf").forEach(b => b.addEventListener("click", async () => {
    const f = _pickerState.filters, c = _pickerState.config;
    if (_pickerState.editLineId) _pickerState._editTouched.product = true;
    f.type_id = b.dataset.type; f.type_label = b.dataset.typeLabel;
    f.part_type_id = b.dataset.pt; f.part_type_label = b.dataset.ptLabel;
    const flow = b.dataset.flow || "";
    f.category_id = flow; f.category_label = flow ? (_LIGHT_CATEGORIES.find(x => x.id === flow) || {}).label || flow : "";
    // Scene/interior lights are white — default to NO color filter (all SKUs
    // match); the user opts into a color only if they want one. Other light
    // categories keep the normal per-color selection.
    c._noColor = (flow === "scene" || flow === "interior");
    _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
    await _pickerFetchProducts();
    // Step 2: always stay on browse — options are now in the product box.
    _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter();
  }));

  el.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", async () => {
    if (b.disabled) return;
    const k = b.dataset.k, v = b.dataset.v;
    const f = _pickerState.filters, c = _pickerState.config;
    if (_pickerState.editLineId) _pickerState._editTouched.color = true;
    if (k === "lens") { f.lens = v; _pickerRenderFilters(); _pickerRenderProducts(); return; }
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "cph") { c.colorsPerHead = v; _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "mode") { c.mode = v; _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerUpdateFooter(); return; }
  }));

  el.querySelectorAll(".picker-swatch").forEach(b => b.addEventListener("click", () => {
    if (b.disabled) return;
    if (_pickerState.editLineId) _pickerState._editTouched.color = true;
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

function _pickerComboLabel(hs) { return hs.length ? hs.map(x => x[0].toUpperCase() + x.slice(1)).join("/") : "Any color"; }

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
  // Lens preference score for per-combo SKU sort (Step 2 lens-fix): SKUs
  // whose lens_type matches f.lens sort to the front so the default chosen SKU
  // reflects the selected lens.  0 = match, 1 = unknown, 2 = mismatch.
  const _lensScore = s => {
    const lv = (f.lens || "").toLowerCase();
    if (!lv) return 0;
    if (!s.lens_type) return 1;
    return s.lens_type.toLowerCase().includes(lv) ? 0 : 2;
  };
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
  let list = _pickerState.products;
  if (f.brand) list = list.filter(p => p.manufacturer_label === f.brand);
  if (q) list = list.filter(p => p.model.toLowerCase().includes(q) || p.skus.some(s => (s.part_number || "").toLowerCase().includes(q)));
  // Vehicle-compat: drop products with no SKU that fits the selected vehicle.
  if (vehFiltering) list = list.filter(p => p.skus.some(s => _skuCompatible(s, veh)));
  // Step 2: grid is no longer pre-sorted by color match — options live in the
  // product box and are configured per-product after selection, not before.
  list = [...list].sort((a, b) => {
    const ap = pref.has((a.manufacturer_label || "").toLowerCase()), bp = pref.has((b.manufacturer_label || "").toLowerCase());
    if (ap !== bp) return ap ? -1 : 1;                  // preferred brand first
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

    // Body: color products show options + per-combo SKU dropdown; else → SKU pick list.
    let bodyHtml = "";
    if (open) {
      if (pColor && selected) {
        // Step 2: option controls (mode/lens/color/cph/qty) in the product box,
        // above the SKU dropdown.  _pickerWireProductOptions wires them after render.
        bodyHtml = `<div class="pp-prod-options">${_pickerColorConfigHtml()}</div>`;
        // Step 3: one dropdown per head (qty=N → N dropdowns), filtered to
        // option-matching SKUs unless "Remove options" is engaged.
        const optRemoved = _pickerState.optionsRemoved || false;
        const allHeads = _pickerResolveHeads();
        bodyHtml += `<div class="pp-skus">` + allHeads.map((headColors, h) => {
          const headSet = _headSet(headColors);
          const headKey = "head_" + h;
          // Sort by lens-match first, then ion rank, then price.
          const sorted = [...skus].sort((a, b) => {
            const aL = _lensScore(a), bL = _lensScore(b);
            if (aL !== bL) return aL - bL;
            const ar = _ionRank(a.part_number), br = _ionRank(b.part_number);
            if (ar !== br) return ar - br;
            return (a.price ?? 9e9) - (b.price ?? 9e9);
          });
          // When optionsRemoved: show every SKU; otherwise filter to color+lens match.
          let displaySkus, hasMatch;
          if (optRemoved) {
            displaySkus = sorted; hasMatch = false;
          } else {
            const matching = sorted.filter(s => _skuMatchesAny(s, [headSet]));
            hasMatch = matching.length > 0;
            displaySkus = hasMatch ? matching : sorted;  // fall back to all when no match
          }
          const chosen = _pickerState.skuChoices[headKey] || (displaySkus[0] && displaySkus[0].part_number) || "";
          // Live title: each head's label reflects ITS chosen SKU + lens (Step 3).
          const chosenObj = displaySkus.find(s => s.part_number === chosen) || displaySkus[0];
          const lensLabel = chosenObj?.lens_type || (f.lens || "");
          const headTitle = `Head ${h + 1}: ${chosen || "—"}${lensLabel ? " · " + lensLabel : ""}`;
          const opts = displaySkus.map(s => {
            const cs = [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).join("/");
            return `<option value="${esc(s.part_number)}"${s.part_number === chosen ? " selected" : ""}>${esc(s.part_number)}${cs ? " · " + esc(cs) : ""}${s.lens_type ? " · " + esc(s.lens_type) : ""}${s.price != null ? " · $" + s.price : ""}</option>`;
          }).join("");
          return `<div class="pp-sku"><span class="pp-sku-pn">${esc(headTitle)}</span><select class="pp-override" data-head="${h}">${opts}</select>${(!hasMatch && !optRemoved) ? `<span class="pp-match no">no exact</span>` : ""}</div>`;
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
        ${qb}
      </div>${bodyHtml}
    </div>`;
  }).join("");

  _pickerWireBrand(el);
  _pickerWireProductOptions(el);
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
    // Single-expansion: opening a product collapses any other expanded one, so a
    // previously-selected product can't linger with a stale SKU list.
    if (wasOpen && (!usesColor || (_pickerState.sel && _pickerState.sel.product_id === pid))) _pickerState.expanded.delete(pid);
    else _pickerState.expanded = new Set([pid]);
    // Color products select on head-click; no-color (programmable) products
    // select via the per-SKU "Select" pill instead.
    const pColor = usesColor && _pickerProductHasColor(p);
    if (pColor && (!_pickerState.sel || _pickerState.sel.product_id !== pid)) _pickerResetLocation();
    if (pColor) {
      if (_pickerState.editLineId && (!_pickerState.sel || _pickerState.sel.product_id !== pid)) _pickerState._editTouched.product = true;
      _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label }; _pickerState.skuChoices = {}; _pickerState.optionsRemoved = false;
    }
    _pickerRenderProducts(); _pickerUpdateFooter();
    if (pColor) { _pickerLoadAccessories(pid); _pickerLoadTracer(pid); _pickerLoadLightbar(pid); }
  }));
  el.querySelectorAll("[data-pick]").forEach(btn => btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const pid = btn.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    if (!_pickerState.sel || _pickerState.sel.product_id !== pid) _pickerResetLocation();
    if (_pickerState.editLineId && (!_pickerState.sel || _pickerState.sel.product_id !== pid || _pickerState.sel.sku !== btn.dataset.pick))
      _pickerState._editTouched.product = true;
    _pickerState.expanded = new Set([pid]);   // keep only this product expanded
    _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label, sku: btn.dataset.pick };
    _pickerRenderProducts(); _pickerUpdateFooter();
    _pickerLoadAccessories(pid);
    _pickerLoadTracer(pid);
    _pickerLoadLightbar(pid);
  }));
  el.querySelectorAll(".pp-override").forEach(sel => sel.addEventListener("change", () => {
    const h = parseInt(sel.dataset.head ?? "-1", 10);
    if (h >= 0) {
      _pickerState.skuChoices["head_" + h] = sel.value;
      // Promote non-custom modes to custom so each head's SKU can differ (Step 3).
      const c = _pickerState.config;
      if (c.mode !== "custom") {
        c.custom = _pickerResolveHeads().map(hc => [...hc]);
        c.mode = "custom";
      }
      // Sync this head's color config to match the chosen SKU so re-applying the
      // option filter shows a list that includes the manually-picked SKU.
      const allPSkus = _pickerState.products.find(pr => pr.product_id === (_pickerState.sel?.product_id))?.skus || [];
      const chosenSku = allPSkus.find(s => s.part_number === sel.value);
      if (chosenSku) {
        const newColors = [chosenSku.color, chosenSku.secondary_color, chosenSku.tertiary_color].filter(Boolean).map(x => x.toLowerCase());
        if (newColors.length) c.custom[h] = newColors;
      }
    }
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
}

function _pickerWireBrand(el) {
  el.querySelectorAll("[data-brand]").forEach(b => b.addEventListener("click", () => {
    _pickerState.filters.brand = b.dataset.brand;
    _pickerRenderProducts();
  }));
}

// Wire the per-product option controls (mode/lens/color/cph/qty) that live
// inside .pp-prod-options in the selected product's box (Step 2 relocation).
// Mirrors the handler logic that was previously in _pickerWireFilters for
// the sidebar "Colors & options" step.
function _pickerWireProductOptions(el) {
  const opts = el.querySelector(".pp-prod-options");
  if (!opts) return;
  // "Remove options" toggle (Step 3): switches dropdowns between filtered and all-SKUs.
  opts.querySelector("[data-opts-remove]")?.addEventListener("click", () => {
    _pickerState.optionsRemoved = !_pickerState.optionsRemoved;
    _pickerRenderProducts(); _pickerUpdateFooter();
  });
  opts.querySelectorAll(".pf-pill[data-k]").forEach(b => b.addEventListener("click", async () => {
    if (b.disabled) return;
    const k = b.dataset.k, v = b.dataset.v;
    const f = _pickerState.filters, c = _pickerState.config;
    if (_pickerState.editLineId) _pickerState._editTouched.color = true;
    // Any option engagement re-applies the filter (Step 3).
    _pickerState.optionsRemoved = false;
    if (k === "lens") { f.lens = v; _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "cph") { c.colorsPerHead = v; _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "mode") { c.mode = v; _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
  }));
  opts.querySelectorAll(".picker-swatch").forEach(b => b.addEventListener("click", () => {
    if (b.disabled) return;
    if (_pickerState.editLineId) _pickerState._editTouched.color = true;
    // Any option engagement re-applies the filter (Step 3).
    _pickerState.optionsRemoved = false;
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
    _pickerState.skuChoices = {};
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
}

// ── Location tab (vehicle diagram + dots) ──────────────

// Only the dash/headliner "interior" zone uses the synthetic Interior view.
// rear_interior placements (cargo/rear windows, rear interior light bar) have
// real coordinates in the exterior side/rear/top views, so they render there as
// normal dots — classifying them as interior hid them entirely.
const _INTERIOR_PZ = new Set(["interior"]);

// part_type_id → PartType (label, type_id, ...), loaded once and reused across
// picker opens — static reference data, doesn't need per-open reset. Backs the
// free-text location branch's name fallback (FINDING-004).
let _pickerPartTypeMeta = null;
async function _pickerEnsurePartTypeMeta() {
  if (_pickerPartTypeMeta) return _pickerPartTypeMeta;
  try {
    const res = await api("/api/parts-db/part-types");
    _pickerPartTypeMeta = new Map((res?.part_types || []).map(pt => [pt.part_type_id, pt]));
  } catch (e) { console.error("Picker: part-types failed:", e); _pickerPartTypeMeta = new Map(); }
  return _pickerPartTypeMeta;
}

async function _pickerRenderLocation() {
  const f = _pickerState.filters;
  const loc = _pickerState.loc;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  if (!loc.layouts) {
    try { loc.layouts = await api("/api/layouts"); } catch (e) { console.error("Picker: layouts failed:", e); loc.layouts = {}; }
  }
  await _pickerEnsurePartTypeMeta();
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
  const f = _pickerState.filters;
  const loc = _pickerState.loc;
  const layoutViews = loc.layouts?.vehicles?.[loc.vehicle]?.views || {};
  // A location shows as a diagram dot only if it has coordinates (has_coords from
  // the server; back-compat: a dash/headliner interior zone is dropdown too).
  // Everything else — equipment mounts, console/partition, interior lights — is
  // chosen from a DROPDOWN, the per-part-type option list the old build sheet had.
  const _isDot = l => l.has_coords === true ||
    (l.has_coords === undefined && !_INTERIOR_PZ.has(l.placement_zone));
  const dropdownLocs = Object.values(loc.locByName).filter(l => !_isDot(l));
  // Exterior views that actually have a category-relevant dot.
  const extViews = Object.keys(layoutViews).filter(vk => {
    if (vk.startsWith("internal")) return false;
    const locs = layoutViews[vk].locations || {};
    return Object.keys(locs).some(n => { const e = loc.locByName[n.toUpperCase()]; return e && _isDot(e); });
  });
  // Non-diagram parts get a "Location" step: a dropdown of their options, or —
  // when the part_type has no preset locations at all — a free-text field, so the
  // user can always specify a mount point (never a blank vehicle view).
  const noPreset = !extViews.length && !dropdownLocs.length;
  const viewList = [...extViews];
  if (dropdownLocs.length || noPreset) viewList.push("location");
  if (!viewList.includes(loc.view)) loc.view = viewList[0] || "location";

  const bar = $("picker-loc-views");
  if (bar) {
    bar.innerHTML = viewList.map(v => {
      const label = v === "location" ? "Location" : ((layoutViews[v]?.label) || v);
      return `<button class="pf-pill${loc.view === v ? " active" : ""}" data-view="${esc(v)}">${esc(label)}</button>`;
    }).join("");
    bar.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", () => { loc.view = b.dataset.view; _pickerDrawLocation(); }));
  }

  const img = $("picker-loc-img"), dots = $("picker-loc-dots"), btns = $("picker-loc-btns");
  if (loc.view === "location") {
    // No-diagram locations (equipment mounts, interior lights, console/partition):
    // a dropdown of the part's own location options — the lost workbook behavior.
    if (img) img.style.display = "none";
    if (dots) dots.hidden = true;
    if (btns) {
      btns.hidden = false;
      if (dropdownLocs.length) {
        const sorted = [...dropdownLocs].sort((a, b) => a.location.localeCompare(b.location));
        const opts = sorted.map(l =>
          `<option value="${esc(l.location)}"${loc.selected === l.location ? " selected" : ""}>${esc(_pickerTitleCase(l.location))}</option>`).join("");
        btns.innerHTML = `<div class="pf-group"><span class="pf-label">Location</span>` +
          `<select id="picker-loc-select" class="pf-select"><option value="">— Select location —</option>${opts}</select></div>`;
        const selEl = $("picker-loc-select");
        if (selEl) selEl.addEventListener("change", () => {
          if (_pickerState.editLineId) _pickerState._editTouched.location = true;
          loc.selected = selEl.value;
          const e = loc.locByName[(selEl.value || "").toUpperCase()] || {};
          loc.name_pattern = e.name_pattern || ""; loc.base_label = e.base_label || "";
          loc.catalog_names = e.catalog_names || [];
          _pickerUpdateFooter();
        });
      } else {
        // No preset locations for this part_type → free-text (workbook behavior).
        // The part still needs a real, sequenceable name (FINDING-004) so the
        // planner can match it to a part_type and render it — carry the
        // part_type's label as base_label/name_pattern instead of clearing them.
        const ptLabel = _pickerFreeTextPartTypeLabel(f);
        btns.innerHTML = `<div class="pf-group"><span class="pf-label">Location</span>` +
          `<input id="picker-loc-text" class="pf-select" placeholder="Type the mount location…" value="${esc(loc.selected || "")}">` +
          `<span class="pf-hint">No preset locations for this part — type where it mounts.</span></div>`;
        loc.name_pattern = ptLabel ? `${ptLabel} {n}` : "";
        loc.base_label = ptLabel;
        loc.catalog_names = [];
        const txt = $("picker-loc-text");
        if (txt) txt.addEventListener("input", () => {
          if (_pickerState.editLineId) _pickerState._editTouched.location = true;
          loc.selected = txt.value.trim();
          loc.name_pattern = ptLabel ? `${ptLabel} {n}` : "";
          loc.base_label = ptLabel;
          loc.catalog_names = [];
          _pickerUpdateFooter();
        });
      }
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
      if (_pickerState.editLineId) _pickerState._editTouched.location = true;
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

// Resolve a real part_type label for the free-text location branch (FINDING-004),
// from the selected product's `fits_part_types` (already in the category-skus
// payload) intersected with the currently-browsed type_id. Falls back to the
// product's model name, never the literal "Part".
function _pickerFreeTextPartTypeLabel(f) {
  const sel = _pickerState.sel;
  const product = sel && _pickerState.products.find(p => p.product_id === sel.product_id);
  const fits = (product && product.fits_part_types) || [];
  const meta = _pickerPartTypeMeta || new Map();
  const pt = fits.map(id => meta.get(id)).find(p => p && p.type_id === f.type_id) || meta.get(fits[0]);
  return (pt && pt.label) || (product && product.model) || "";
}

// The part_type_id to tag onto an added line (Step 1b manifest highlight).
// Prefers the tree leaf the user actually picked; falls back to the selected
// product's fits_part_types (same derivation as the free-text label above)
// for edit mode / any path that never touched the browse tree.
function _pickerResolvedPartTypeId(f) {
  if (f.part_type_id) return f.part_type_id;
  const sel = _pickerState.sel;
  const product = sel && _pickerState.products.find(p => p.product_id === sel.product_id);
  const fits = (product && product.fits_part_types) || [];
  const meta = _pickerPartTypeMeta || new Map();
  const pt = fits.map(id => meta.get(id)).find(p => p && p.type_id === f.type_id);
  return (pt && pt.part_type_id) || "";
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
  // Custom tracer mode reads its head list from the lighthead accessory group;
  // refresh the panel now that it's loaded.
  if (_pickerState.tracer.active && _pickerState.tracer.mode === "custom") _pickerRenderTracer();
  _pickerUpdateFooter();
}

function _pickerAccLabel(opt, sku) {
  const colors = [sku.color, sku.secondary_color, sku.tertiary_color].filter(Boolean).map(c => c[0].toUpperCase() + c.slice(1)).join("/");
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
    + `${pending ? "This part has accessories — choose each one to continue" : "Accessories set ✓"}`
    + `<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>`
    + `<div class="pa-rows">${rows}</div>`;
  el.querySelectorAll("select[data-cat]").forEach(sel => sel.addEventListener("change", () => {
    _pickerState.accessoryChoices[sel.dataset.cat] = sel.value;
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
}

// Accessory groups the picker actually shows. For tracers: the panel owns
// lighthead selection (hide that dropdown), and the bracket dropdown is narrowed
// to the tracer-specific mounting products (the L-brackets + vehicle kits) —
// the generic side/rear-warning brackets pulled in by part_type auto-resolve
// are noise for a tracer.
function _pickerVisibleAccessoryGroups() {
  const groups = _pickerState.accessories || [];
  if (!(_pickerState.tracer && _pickerState.tracer.active)) return groups;
  return groups
    .filter(g => g.category !== "lighthead")
    .map(g => g.category === "bracket_mount"
      ? { ...g, options: (g.options || []).filter(o => /tracer/i.test(o.product_id)) }
      : g)
    .filter(g => g.category !== "bracket_mount" || (g.options || []).length);
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
// the exact housings + head SKUs. See docs/PARTS_DB_AND_PICKER.md.
const _TRACER_LAMP_RE = /\b(\d+)\s*-?\s*lamp\b/i;

function _pickerIsTracer(product) {
  return !!product && _TRACER_LAMP_RE.test(product.model || "");
}
function _pickerTracerLamps(product) {
  const m = product ? _TRACER_LAMP_RE.exec(product.model || "") : null;
  return m ? parseInt(m[1], 10) : 0;
}

// 5/6-lamp tracers mount on the running boards — auto-select that location so
// the user doesn't have to (smaller tracers stay manual, e.g. 2-lamp = front).
async function _pickerTracerAutoLocation() {
  const sel = _pickerState.sel, loc = _pickerState.loc, f = _pickerState.filters;
  const product = _pickerState.products.find(p => p.product_id === (sel || {}).product_id);
  if (!sel || _pickerTracerLamps(product) < 5 || loc.selected) return;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  try {
    const res = await api(`/api/parts-db/category-locations?type=${encodeURIComponent(f.type_id)}`
      + `&category=${encodeURIComponent(f.category_id || "")}&product=${encodeURIComponent(sel.product_id)}`
      + `&vehicle=${encodeURIComponent(loc.vehicle)}`);
    const rb = (res?.locations || []).find(l => /run|board|rocker/i.test(l.location));
    if (rb && !loc.selected) {
      loc.selected = rb.location;
      loc.name_pattern = rb.name_pattern || ""; loc.base_label = rb.base_label || "";
      loc.catalog_names = rb.catalog_names || [];
      _pickerUpdateFooter();
    }
  } catch (e) { console.error("tracer auto-location failed:", e); }
}

async function _pickerLoadTracer(productId) {
  const t = _pickerState.tracer;
  const product = _pickerState.products.find(p => p.product_id === productId);
  if (!productId || _pickerState.editLineId || !_pickerIsTracer(product)) {
    _pickerState.tracer = { active: false, mode: t.mode, secondary: t.secondary, custom: {}, preview: null, loading: false };
    _pickerRenderTracer(); return;
  }
  // Fresh custom selection per product; keep the standard mode/secondary choice.
  _pickerState.tracer = { ...t, active: true, custom: {}, preview: null, loading: true };
  _pickerRenderTracer();
  _pickerTracerAutoLocation();
  if (t.mode === "custom") { _pickerState.tracer.loading = false; _pickerRenderTracer(); _pickerUpdateFooter(); }
  else await _pickerFetchTracerPreview();
}

// Flat list of every selectable tracer head (from the lighthead accessory group)
// for Custom mode: {sku, product_id, role, colors, lens, pending}.
function _pickerTracerHeadList() {
  const lg = (_pickerState.accessories || []).find(g => g.category === "lighthead");
  if (!lg) return [];
  const cap = c => c ? c[0].toUpperCase() + c.slice(1) : c;
  const out = [];
  for (const o of (lg.options || [])) {
    const role = /secondary/i.test((o.product_id || "") + (o.model || "")) ? "secondary" : "primary";
    for (const s of (o.skus || [])) {
      out.push({
        sku: s.part_number, product_id: o.product_id, role,
        colors: [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).map(cap).join("/"),
        lens: s.lens_type || "clear", pending: !!s.qb_pending,
      });
    }
  }
  // Primary first, then secondary; clear before smoked.
  return out.sort((a, b) => (a.role === b.role ? (a.lens > b.lens ? 1 : -1) : (a.role === "primary" ? -1 : 1)));
}

async function _pickerFetchTracerPreview() {
  const t = _pickerState.tracer, sel = _pickerState.sel;
  if (!t.active || !sel || t.mode === "custom") return;   // custom resolves locally
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
  const isCustom = t.mode === "custom";
  let body = "";
  if (isCustom) {
    const cust = t.custom || {};
    const total = Object.values(cust).reduce((a, b) => a + b, 0);
    const lampN = _pickerTracerLamps(_pickerState.products.find(x => x.product_id === (_pickerState.sel || {}).product_id));
    const pairCount = (lampN && lampN !== 2) ? 2 : 1;     // running-board pair vs 2-lamp front
    const expect = lampN * pairCount;                     // total heads for the full build
    const rows = _pickerTracerHeadList().map(h => {
      const q = cust[h.sku] || 0;
      const pend = h.pending ? ` <span class="pp-pending">pending</span>` : "";
      return `<div class="pt-cust${q ? " on" : ""}">
        <span class="pt-cust-qty"><button class="pf-pill" data-cq="${esc(h.sku)}" data-cd="-1">−</button>`
        + `<b>${q}</b><button class="pf-pill" data-cq="${esc(h.sku)}" data-cd="1">+</button></span>
        <span class="pt-sku">${esc(h.sku)}</span>
        <span class="pt-role">${esc(h.role)} · ${esc(h.colors || "—")} · ${esc(h.lens)}${pend}</span></div>`;
    }).join("");
    // Running-board tracers (anything but the 2-lamp front) auto-add both
    // housings; the user picks the full head count (lamps × 2) here.
    const pairNote = (pairCount > 1)
      ? `<div class="pt-cust-note">Running-board tracer: both housings (driver + passenger) are added automatically — pick the full ${lampN} × 2 = ${expect} heads here.</div>`
      : "";
    body = `<div class="pt-cust-hint">${total}${expect ? ` of ${expect}` : ""} head${total === 1 ? "" : "s"} selected</div>`
      + pairNote
      + `<div class="pt-preview">${rows || "No heads available"}</div>`;
  } else if (t.loading) body = `<div class="pt-preview muted">Resolving…</div>`;
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
  const secRow = isCustom ? "" : `<div class="pf-group"><span class="pf-label">Secondary color</span><div class="pf-pills">
        ${pill("secondary", "white", "White", t.secondary === "white")}
        ${pill("secondary", "amber", "Amber", t.secondary === "amber")}</div></div>`;
  // Preserve the head-list scroll position across the re-render (qty steppers).
  const _prevScroll = (el.querySelector(".pt-preview") || {}).scrollTop || 0;
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">⚡</span>Tracer lightheads — choose a configuration<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>
    <div class="pt-rows">
      <div class="pf-group"><span class="pf-label">Heads</span><div class="pf-pills">
        ${pill("mode", "duo", "Standard Duo", t.mode === "duo")}
        ${pill("mode", "trio", "Standard Trio", t.mode === "trio")}
        ${pill("mode", "custom", "Custom", isCustom)}</div></div>
      ${secRow}
      <div class="pf-group"><span class="pf-label">Lens</span><span class="pt-lens">${esc(lens)} · from filter</span></div>
    </div>${body}`;
  const _pv = el.querySelector(".pt-preview"); if (_pv) _pv.scrollTop = _prevScroll;
  el.querySelectorAll("[data-tk]").forEach(b => b.addEventListener("click", () => {
    _pickerState.tracer[b.dataset.tk] = b.dataset.tv;
    if (_pickerState.tracer.mode === "custom") { _pickerRenderTracer(); _pickerUpdateFooter(); }
    else _pickerFetchTracerPreview();
  }));
  el.querySelectorAll("[data-cq]").forEach(b => b.addEventListener("click", () => {
    const sku = b.dataset.cq, d = parseInt(b.dataset.cd, 10);
    const c = _pickerState.tracer.custom = _pickerState.tracer.custom || {};
    c[sku] = Math.max(0, (c[sku] || 0) + d);
    if (!c[sku]) delete c[sku];
    _pickerRenderTracer(); _pickerUpdateFooter();
  }));
}

function _pickerTracerSatisfied() {
  const t = _pickerState.tracer;
  if (!t.active) return true;
  if (t.mode === "custom") return Object.values(t.custom || {}).some(q => q > 0);
  return !!(t.preview && t.preview.ok);
}

// ── Roof lightbar config ───────────────────────────────
// Roof bars are ordered as whole configured SKUs (the colors are baked into the
// part number). The panel adds a Standard/Custom setup tag, a Clear/Smoked/
// Midnight edition, and a "notes for ordering" box for Custom builds — so the
// sales rep knows whether to order the normal config or read special notes.
function _pickerIsLightbar(product) {
  if (!product || !(product.fits_part_types || []).includes("roof_light_bar")) return false;
  // Mini/micro bars and the low-profile Responder LP are fixed-config single
  // SKUs (color/lens baked in, no smoked/midnight variants) — no setup or
  // lens/edition choice, so they skip the config panel.
  if (/\b(mini|micro)\b|responder\s*lp/i.test(product.model || "")) return false;
  return true;
}

// Clear the chosen location (on product switch) so a prior auto-located
// fixture/tracer spot doesn't leak onto the next product.
function _pickerResetLocation() {
  const loc = _pickerState.loc;
  loc.selected = null; loc.name_pattern = ""; loc.base_label = ""; loc.catalog_names = [];
}

function _pickerSelIsRoofBar() {
  const sel = _pickerState.sel;
  const p = sel && _pickerState.products.find(x => x.product_id === sel.product_id);
  return !!p && (p.fits_part_types || []).includes("roof_light_bar");
}

function _pickerLoadLightbar(productId) {
  const lb = _pickerState.lightbar;
  const product = _pickerState.products.find(p => p.product_id === productId);
  const showPanel = !_pickerState.editLineId && _pickerIsLightbar(product);   // full-size bars
  _pickerState.lightbar = { active: showPanel, setup: lb.setup, edition: lb.edition, notes: "" };
  _pickerRenderLightbar(); _pickerUpdateFooter();
  // Every roof bar (mini or full) is a fixture → auto-resolve its roof location.
  if (productId && !_pickerState.editLineId && product
      && (product.fits_part_types || []).includes("roof_light_bar")) _pickerLightbarAutoLocation();
}

// Roof bars are fixtures — they always go in the one roof spot, so auto-resolve
// the location instead of asking. The roof-bar location key is consistent across
// vehicles ("ROOF LIGHT BAR"); the name must be "Light Bar N" to match the
// roof_light_bar part_type for rendering.
async function _pickerLightbarAutoLocation() {
  const loc = _pickerState.loc;
  if (loc.selected) return;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  if (!loc.layouts) { try { loc.layouts = await api("/api/layouts"); } catch (e) { loc.layouts = {}; } }
  const views = loc.layouts?.vehicles?.[loc.vehicle]?.views || {};
  let key = "";
  for (const v of Object.values(views)) {
    for (const n of Object.keys(v.locations || {})) {
      if (/roof.*light.*bar|roof\s*bar/i.test(n)) { key = n; break; }
    }
    if (key) break;
  }
  if (loc.selected) return;
  loc.selected = key || "ROOF LIGHT BAR";
  loc.name_pattern = "Light Bar {n}";   // matches roof_light_bar part_type label (renders)
  loc.base_label = "Light Bar";
  loc.catalog_names = [];
  _pickerUpdateFooter();
}

function _pickerRenderLightbar() {
  const el = $("picker-lightbar"); if (!el) return;
  const lb = _pickerState.lightbar;
  if (!lb.active) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const pill = (k, v, label, on) =>
    `<button class="pf-pill${on ? " active" : ""}" data-lk="${k}" data-lv="${v}">${esc(label)}</button>`;
  const customBox = lb.setup === "custom"
    ? `<div class="pf-group" style="align-items:flex-start"><span class="pf-label">Order notes</span>`
      + `<textarea id="lb-notes" class="lb-notes" placeholder="What's different from the standard config? (goes on the estimate for ordering)">${esc(lb.notes || "")}</textarea></div>`
    : "";
  const midnightNote = lb.edition === "midnight"
    ? `<div class="pt-cust-note">Midnight Edition needs <b>black straps</b> — pick a black-strap mount in the accessories below to complete it.</div>`
    : "";
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">🚙</span>Roof lightbar — setup & edition<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>
    <div class="pt-rows">
      <div class="pf-group"><span class="pf-label">Setup</span><div class="pf-pills">
        ${pill("setup", "standard", "Standard", lb.setup === "standard")}
        ${pill("setup", "custom", "Custom", lb.setup === "custom")}</div></div>
      <div class="pf-group"><span class="pf-label">Edition</span><div class="pf-pills">
        ${pill("edition", "clear", "Clear lens", lb.edition === "clear")}
        ${pill("edition", "smoked", "Smoked lens", lb.edition === "smoked")}
        ${pill("edition", "midnight", "Midnight", lb.edition === "midnight")}</div></div>
    </div>${customBox}${midnightNote}`;
  el.querySelectorAll("[data-lk]").forEach(b => b.addEventListener("click", () => {
    _pickerState.lightbar[b.dataset.lk] = b.dataset.lv;
    _pickerRenderLightbar(); _pickerUpdateFooter();
  }));
  const ta = el.querySelector("#lb-notes");
  if (ta) ta.addEventListener("input", () => { _pickerState.lightbar.notes = ta.value; _pickerUpdateFooter(); });
}

function _pickerLightbarSatisfied() {
  const lb = _pickerState.lightbar;
  if (!lb.active) return true;
  if (lb.setup === "custom" && !(lb.notes || "").trim()) return false;   // custom needs order notes
  return true;
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
  const lightbarOk = _pickerLightbarSatisfied();
  const ready = accOk && tracerOk && lightbarOk;   // all required sub-choices addressed
  const hasAcc = _pickerVisibleAccessoryGroups().length > 0;
  const selName = sel ? (sel.model + (sel.sku ? " · " + sel.sku : "")) : "";
  const preview = (sel && usesColor) ? _pickerHeadsPreviewHtml() : "";
  let hint = (sel && hasAcc && !accOk) ? ' <span class="picker-foot-acc">· choose accessories</span>' : "";
  if (sel && _pickerState.tracer.active && !tracerOk)
    hint += ' <span class="picker-foot-acc">· configure lightheads</span>';
  if (sel && _pickerState.lightbar.active && !lightbarOk)
    hint += ' <span class="picker-foot-acc">· add order notes</span>';
  if (_pickerState.tab === "part") {
    text.innerHTML = sel ? `${preview}<span class="picker-foot-label">${esc(selName)}</span>${hint}` : `<span class="picker-foot-label">Pick a product</span>`;
    if (_pickerState.editLineId) {
      // Editing: save the part change directly (location keeps its current value
      // unless the user visits the Location tab to change it). Stopgap for
      // FINDING-005: Save stays disabled until the user actually touches a
      // control, so a no-op open+close (or a re-render) can't corrupt the line.
      const touched = _pickerState._editTouched || {};
      const dirty = touched.product || touched.color || touched.location;
      btn.textContent = "Save edits";
      btn.disabled = !(sel && ready && dirty);
      _pickerState.footerHandler = (sel && ready && dirty) ? _pickerDoAdd : null;
    } else if (loc.selected && (_pickerState.tracer.active || _pickerSelIsRoofBar())) {
      // Tracer / fixture lightbar auto-located → add directly; the user can
      // still open the Location tab to change it.
      btn.textContent = "Add Part";
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
  // No color filter: the chosen SKU carries its own color; don't force a label.
  if (c._noColor) return { raw_color: "" };
  if (c.mode === "uniform") return { raw_color: cap(c.uniform) };
  if (c.mode === "split") {
    const d = cap(["red", ...c.splitSecondary]), p = cap(["blue", ...c.splitSecondary]);
    return { raw_color: `${d} / ${p}`, driver_color: d, passenger_color: p };
  }
  const labels = [...new Set(_pickerResolveHeads().map(h => cap(h)))];
  return { raw_color: labels.join(", ") };
}

// Color for a tracer parent line. Tracer lamps render as UNIFORM slots (each
// head already carries its full combo), so raw_color must be a single combo
// that resolves to a lamphead asset — not a driver/passenger split (which the
// uniform resolver can't read, leaving the lamps as bare dots). Trio =
// red/blue/secondary; duo renders the driver combo (red/secondary) on the
// running-board side view.
function _tracerColorFields(t) {
  const sec = t.secondary === "amber" ? "Amber" : "White";
  return { raw_color: t.mode === "trio" ? `Red/Blue/${sec}` : `Red/${sec}` };
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
  if (_pickerState.lightbar.active) { await _pickerAddLightbar(draftId); return; }

  const product = _pickerState.products.find(p => p.product_id === sel.product_id);
  // Color path only for color-configured products; a direct SKU pick (sel.sku,
  // e.g. a programmable bar) always uses the simple single-SKU path.
  const usesColor = f.type_id === "lights" && _COLOR_CATEGORIES.has(f.category_id)
    && !sel.sku && _pickerProductHasColor(product || { skus: [] });
  const locName = loc.selected;   // raw layout key (planner upper-cases to match)

  // FINDING-005 stopgap: in edit mode, a control group the user never touched
  // must not clobber the stored part — carry its editPart value through
  // unchanged instead of recomputing from picker defaults.
  const editing = !!_pickerState.editLineId;
  const ep = _pickerState.editPart;
  const touched = _pickerState._editTouched || {};
  const keepName = editing && ep && !touched.product && !touched.location;
  const keepColor = editing && ep && !touched.product && !touched.color;
  const baseName = keepName ? ep.name : (_pickerChooseName(loc) || sel.model);

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
    // Step 3: build per-head SKU assignments; skuChoices["head_N"] overrides win.
    const comboDefault = {};
    (m.combos || []).forEach(cb => {
      const ck = _headSet(cb.colors || []).join(",");
      comboDefault[ck] = cb.default_sku;
    });
    const headAssignments = heads.map((hColors, h) => {
      const ov = _pickerState.skuChoices["head_" + h];
      const ck = _headSet(hColors).join(",");
      const pn = ov || comboDefault[ck] || null;
      return pn ? { colors: hColors, part_number: pn } : null;
    }).filter(Boolean);
    if (!headAssignments.length) { toast("No SKU chosen for those colors — pick one or adjust colors/lens", "error"); return; }
    // Group by (part_number, color-key) to produce combos for resolve-selection.
    const grouped = {};
    headAssignments.forEach(({ colors, part_number }) => {
      const k = part_number + "|" + _headSet(colors).join(",");
      if (!grouped[k]) grouped[k] = { colors, part_number, quantity: 0, price: skuById[part_number]?.price ?? null };
      grouped[k].quantity++;
    });
    combos = Object.values(grouped);
    if (!combos.length) { toast("No SKU chosen for those colors — pick one or adjust colors/lens", "error"); return; }
    colorFields = keepColor ? { raw_color: ep.raw_color || "" } : _pickerColorFields();
  } else {
    const sku = sel.sku || (product && product.skus[0] && product.skus[0].part_number);
    if (!sku) { toast("Pick a SKU", "error"); return; }
    const skuObj = product.skus.find(s => s.part_number === sku) || {};
    const qty = keepColor ? (ep.quantity || 1) : 1;
    combos = [{ colors: [], part_number: sku, quantity: qty, price: skuObj.price || null }];
    totalHeads = 1;
    if (keepColor && ep.raw_color) colorFields = { raw_color: ep.raw_color };
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
  const partTypeId = _pickerResolvedPartTypeId(f);

  let ok = 0, parentLineId = "";
  for (const row of rows) {
    try {
      const endpoint = _pickerState.editLineId
        ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
        : `/api/draft/${draftId}/part`;
      const r = await api(endpoint, partTypeId ? { ...row, part_type: partTypeId } : row);
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

  // Normalize to {housingSku, housingQty, headRows, lamps, numHousings,
  // colorFields, notes} from either the standard resolver or the custom picks.
  let housingSku, housingQty, headRows, lamps, numHousings, colorFields, notes;
  if (t.mode === "custom") {
    const product = _pickerState.products.find(p => p.product_id === sel.product_id);
    housingSku = sel.sku || (product && product.skus && product.skus[0] && product.skus[0].part_number);
    if (!housingSku) { toast("Pick a tracer", "error"); if (btn) btn.disabled = false; return; }
    const byId = {}; _pickerTracerHeadList().forEach(h => { byId[h.sku] = h; });
    headRows = Object.entries(t.custom || {}).filter(([, q]) => q > 0).map(([sku, qty]) => {
      const h = byId[sku] || {};
      return { sku, qty, role: h.role || "", colors: (h.colors || "").split("/").filter(Boolean) };
    });
    if (!headRows.length) { toast("Pick at least one head", "error"); if (btn) btn.disabled = false; return; }
    lamps = _pickerTracerLamps(product);
    numHousings = (lamps && lamps !== 2) ? 2 : 1;   // running-board pair auto-added, like standard
    housingQty = numHousings;
    colorFields = { raw_color: (headRows[0].colors || []).join("/") };   // tint the lamp row
    notes = "Custom heads";
  } else {
    let res;
    try {
      const qs = `product_id=${encodeURIComponent(sel.product_id)}&mode=${t.mode}&secondary=${t.secondary}&lens=${lens}`;
      res = await api(`/api/parts-db/tracer-heads?${qs}`);
    } catch (e) { console.error("tracer resolve failed:", e); toast("Resolve failed", "error"); if (btn) btn.disabled = false; return; }
    if (!res || !res.ok) { toast("Can't build this tracer config yet", "error"); if (btn) btn.disabled = false; return; }
    const housing = (res.lines || []).find(l => l.kind === "housing");
    if (!housing) { toast("Nothing to add", "error"); if (btn) btn.disabled = false; return; }
    housingSku = housing.sku; housingQty = housing.qty || 1;
    headRows = (res.lines || []).filter(l => l.kind === "head" && l.sku)
      .map(l => ({ sku: l.sku, qty: l.qty, role: l.role, colors: l.colors || [] }));
    lamps = res.lamp_count || 0;
    numHousings = (res.housings || []).length || 1;
    colorFields = _tracerColorFields(t);
    const secCap = t.secondary === "amber" ? "Amber" : "White";
    notes = t.mode === "trio"
      ? `Standard Trio · Red/Blue/${secCap}`
      : `Standard Duo · driver Red/${secCap} / passenger Blue/${secCap}`;
  }

  // Parent line: the NAME must stay a clean part-type label (e.g. "Side Warning
  // 1") so the planner matches it to a part_type and renders it. Config + colors
  // live in raw_color/lens/notes (which also color the rendered icon).
  let parentLineId = "", added = 0;
  try {
    const r = await api(`/api/draft/${draftId}/part`, {
      name: baseName, location: locName,
      manufacturer: sel.mfr || "", part_number: housingSku, quantity: housingQty,
      new_or_used: "New", source: "", lens, notes,
      part_type: _pickerResolvedPartTypeId(_pickerState.filters),
      ...colorFields,
    });
    if (r?.ok) { added++; parentLineId = r.line_id || ""; }
  } catch (e) { console.error("tracer housing add failed:", e); }
  // Heads nest beneath (descriptive names → intentionally don't match a
  // part_type, so they don't render as their own icons).
  for (const hd of headRows) {
    const colors = (hd.colors || []).map(cap).join("/");
    const label = [cap(hd.role), colors].filter(Boolean).join(" ");
    try {
      await api(`/api/draft/${draftId}/part`, {
        name: `${baseName} · ${label}`, location: locName,
        manufacturer: sel.mfr || "", part_number: hd.sku, quantity: hd.qty || 1,
        new_or_used: "New", source: "", parent_line_id: parentLineId,
        accessory_category: "lighthead", accessory_parent_product: sel.product_id,
      });
    } catch (e) { console.error("tracer head add failed:", e); }
  }
  // Chosen accessories (e.g. the mounting bracket) → nested under the housing.
  // Bracket quantity depends on the kind: an "L" bracket needs (lamps + 1) per
  // housing (Whelen: N-lamp housing → N+1 brackets); a vehicle-specific or other
  // mounting kit needs one per housing.
  for (const arow of _pickerChosenAccessoryRows(baseName, locName, parentLineId)) {
    if (arow.accessory_category === "bracket_mount") {
      const sku = (arow.part_number || "").toUpperCase();
      arow.quantity = (sku.includes("LBKT") || sku.includes("L BRACKET"))
        ? (lamps + 1) * numHousings
        : numHousings;
    }
    try { await api(`/api/draft/${draftId}/part`, arow); }
    catch (e) { console.error("tracer accessory add failed:", e); }
  }
  if (!added) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }
  toast("Tracer added", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  pickerClose();
  if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
  if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") pvLoad(draftId);
}

// Add a roof lightbar: the chosen configured SKU plus the setup/edition tags.
// The Standard/Custom + edition + order notes ride on the part's lens/notes so
// the build sheet and estimate carry them for ordering.
async function _pickerAddLightbar(draftId) {
  const sel = _pickerState.sel, loc = _pickerState.loc, lb = _pickerState.lightbar;
  const locName = loc.selected;
  if (!sel.sku) { toast("Pick a lightbar SKU", "error"); return; }
  if (!locName) { toast("Choose a location", "error"); return; }
  const baseName = _pickerChooseName(loc) || sel.model;
  const btn = $("picker-add-btn"); if (btn) btn.disabled = true;

  const editionLabel = { clear: "Clear lens", smoked: "Smoked lens", midnight: "Midnight Edition" }[lb.edition] || "";
  const lens = lb.edition === "clear" ? "clear" : "smoked";   // smoked + midnight both smoked-lens
  const noteParts = [lb.setup === "custom" ? "Custom setup" : "Standard setup", editionLabel];
  if (lb.edition === "midnight") noteParts.push("black straps required");
  if (lb.setup === "custom" && (lb.notes || "").trim()) noteParts.push("Order notes: " + lb.notes.trim());
  const notes = noteParts.filter(Boolean).join(" · ");

  let parentLineId = "", added = 0;
  try {
    const r = await api(`/api/draft/${draftId}/part`, {
      name: baseName, location: locName, manufacturer: sel.mfr || "",
      part_number: sel.sku, quantity: 1, new_or_used: "New", source: "", lens, notes,
      part_type: _pickerResolvedPartTypeId(_pickerState.filters),
    });
    if (r?.ok) { added++; parentLineId = r.line_id || ""; }
  } catch (e) { console.error("lightbar add failed:", e); }
  if (!added) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }
  // Chosen accessories (mount kit / straps) → nested under the bar.
  for (const arow of _pickerChosenAccessoryRows(baseName, locName, parentLineId)) {
    try { await api(`/api/draft/${draftId}/part`, arow); }
    catch (e) { console.error("lightbar accessory add failed:", e); }
  }
  toast("Lightbar added", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  pickerClose();
  if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
  if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") pvLoad(draftId);
}
