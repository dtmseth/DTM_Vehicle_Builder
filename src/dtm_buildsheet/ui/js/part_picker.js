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
  filters: { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", family_id: "", family_label: "", part_type_id: "", part_type_ids: [], part_type_label: "", brand: "", lens: "" },
  config: { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false },
  availAll: new Set(),
  search: "",
  searchGlobal: true,
  allProducts: null,
  products: [],            // [{product_id, model, manufacturer_label, skus:[...]}]
  expanded: new Set(),     // product_ids whose SKU list is open
  sel: null,               // { product_id, model, mfr, sku? }  current selection
  loc: { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, textCustom: false, renderLocation: "", customStage: "", customPlacementMode: "vehicle", customPlacementLayout: "even", customPlacements: {}, customPlacementAnchors: {}, customHeadSpacing: 0.06, autoLocation: "", name_pattern: "", base_label: "" },
  partDetails: { paMicLocation: "", paMicLocationCustom: "", paMicClip: "", handheldMagMic: null },
  tint: { windows: [], percentage: 20 },
  locationAllocation: { quantities: {}, comments: {}, batchId: "" },
  roundLightColor: "red",
  sirenDualTones: false,  // qty-2 Whelen speaker option; adds CEXAMP as a billed component
  comment: "",             // user-authored text shown in the build manifest
  accessories: [],         // resolved [{category,label,required,options:[...]}] for current product
  accessoryChoices: {},    // category_id → select value ("" | "none" | "<product_id>::<sku>")
  accessoryQuantities: {}, // category_id → quantity, or quantities aligned with multi-choice rows
  accessoryQuantityManual: {}, // category_id → whether each quantity was explicitly overridden
  accLoadedFor: null,      // product_id accessories were loaded for
  tracer: { active: false, mode: "trio", secondary: "white", lens: "clear", custom: {}, preview: null, loading: false },
  innerEdge: { active: false, mode: "duo", secondary: "white", coverage: "both", preview: null, loading: false },
  outerEdge: { active: false, mode: "duo", secondary: "white", preview: null, loading: false },
  lightbar: { active: false, setup: "standard", edition: "clear", notes: "" },
  // `radio` is the shared guided-system state.  The name is retained for
  // backwards-compatible smoke hooks while the picker now serves radio,
  // radar, and camera system families through the same question engine.
  radio: { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 },
  systemSetup: { active: false, kind: "", product: null },
  // Center consoles are a parent SKU plus a curated, ordered set of real
  // child SKUs. Keep that setup separate from the radio/radar/camera kit
  // engine: its faceplate order is edited directly rather than as questions.
  consoleSetup: { active: false, loading: false, catalog: {}, choices: {}, faceplateSearch: "", openComponent: "" },
  westin: { active: false, wire: "", channel: "", channelInfo: null, lightProduct: null, loading: false, error: "", lights: { mode: "duo", secondary: "white", lens: "clear" } },
  vehicleOnly: true,       // hide parts/accessories not compatible with the draft's vehicle
  partStatus: "New",      // legacy compatibility value derived from `supply`
  supply: { supplyType: "new", customerCondition: "", customerSource: "" },
  footerHandler: null,
  footerHandlerAnother: null,  // Step 7: "Add another part" action (null in edit mode)
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

function _pickerMoney(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? `$${amount.toFixed(2)}` : "";
}

function _pickerRetailPrice(value) {
  const amount = _pickerMoney(value);
  return amount ? `Retail ${amount}` : "";
}

// ── Brand-preference scopes (owner flaw #5) ────────────────────────────
// Mirror the `preference_filters` block in parts_db.json (~line 31630),
// which authors which part_type_ids each agency brand preference applies
// to. That block's `filter_scope_kind`/`filter_scope_values` are currently
// unread by any code path — these consts are the concrete, client-side
// instantiation of the same scopes so _pickerPreferredBrand() can resolve a
// preferred brand for any part_type, not just lighting.
//   bumper_brand scope (parts_db.json preference_filters.bumper_brand):
const _PREF_BUMPER_PART_TYPES = new Set(["push_bumper", "pit_bar", "wing_wraps"]);
const _PREF_BUMPER_FAMILIES = new Set(["push_bumper_system"]);
//   cage_brand scope (parts_db.json preference_filters.cage_brand):
const _PREF_CAGE_PART_TYPES = new Set([
  "cage", "front_partition", "rear_partition", "rear_seat_divider",
  "floor_pan", "replacement_rear_seat", "k9_kennel",
]);
const _PREF_CAGE_FAMILIES = new Set(["cage_prisoner_containment"]);
//   camera_brand scope (parts_db.json preference_filters.camera_brand uses
//   filter_scope_kind:"tag_ids" → ["camera"]; these are the part_type_ids
//   that currently carry that tag_id, listed directly since the picker's
//   filter context only has part_type_id, not tag membership, at this point):
const _PREF_CAMERA_PART_TYPES = new Set([
  "camera_dvr", "front_camera", "body_camera_dock", "rear_seat_camera", "rear_camera",
]);
//   lighting_brands scope extension (owner follow-up): siren speakers are a
//   lighting/Whelen-brand item, not their own agency preference — they should
//   follow the same lighting_brands pref as `lights` type_id parts.
const _PREF_LIGHTING_EXTRA_PART_TYPES = new Set(["siren_speaker"]);
const _PREF_LIGHTING_FAMILIES = new Set(["light_control_system"]);
//   console_brand scope (owner follow-up): center console manufacturer,
//   mirrors cage_brand/push_bumper_brand's text+datalist shape.
const _PREF_CONSOLE_PART_TYPES = new Set(["console"]);
// The Console family label is itself selectable before the user drills into
// its Console leaf. Treat that family as the console-brand scope too, so the
// preference applies consistently at either picker entry point.
const _PREF_CONSOLE_FAMILIES = new Set(["console_system"]);

// Returns the preferred brand STRING for the current picker filter context
// (f = _pickerState.filters), or "" when no preference applies OR the
// preferred brand doesn't actually appear among the currently loaded
// products (_pickerState.products must already be fetched). Case-insensitive
// match against each product's manufacturer_label, returning the label's
// real casing so it can be used directly as a filter/display value.
function _pickerPreferredBrand(f) {
  const prefs = (window._PT && window._PT.viewProject && window._PT.viewProject.preferences) || {};
  let want = "";
  if (f.type_id === "lights" || _PREF_LIGHTING_EXTRA_PART_TYPES.has(f.part_type_id) || _PREF_LIGHTING_FAMILIES.has(f.family_id)) {
    want = (prefs.lighting_brands && prefs.lighting_brands[0]) || prefs.lighting || "";
  } else if (_PREF_BUMPER_PART_TYPES.has(f.part_type_id) || _PREF_BUMPER_FAMILIES.has(f.family_id)) {
    want = prefs.push_bumper_brand || "";
  } else if (_PREF_CAGE_PART_TYPES.has(f.part_type_id) || _PREF_CAGE_FAMILIES.has(f.family_id)) {
    want = prefs.cage_brand || "";
  } else if (_PREF_CAMERA_PART_TYPES.has(f.part_type_id)) {
    want = prefs.camera_brand || "";
  } else if (_PREF_CONSOLE_PART_TYPES.has(f.part_type_id) || _PREF_CONSOLE_FAMILIES.has(f.family_id)) {
    want = prefs.console_brand || "";
  }
  if (!want) return "";
  const wantLower = String(want).toLowerCase();
  const match = _pickerState.products.find(
    p => p.manufacturer_label && String(p.manufacturer_label).toLowerCase() === wantLower
  );
  return match ? match.manufacturer_label : "";
}

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

// Opens the picker from one of the manifest's subgroup Add buttons. The
// manifest is sales-oriented, while the picker is a browse tree, so resolve
// the subgroup back to its matching family or leaf before showing the panel.
async function openPickerInSection(scope = {}) {
  _pickerResetState();
  _pickerOpenPanel(scope.label ? `Add ${scope.label}` : "Add Part");
  await _pickerLoadTypes();

  const target = _pickerFindBrowseTarget(scope);
  if (target) _pickerApplyBrowseTarget(target);
  await _pickerFetchProducts();

  // System-family headers first let the user identify the system on the Part
  // tab. The guided shop questions begin only after they enter Details.
  if (target?.family_id && !target.part_type_id) {
    const systemKind = _pickerGuidedSystemKind(target.family_id);
    if (systemKind) _pickerStartSystemSelection(systemKind);
  }
  _pickerSwitchTab("part");
}

function _pickerFindBrowseTarget(scope) {
  const refId = String(scope?.refId || "");
  const partTypeIds = new Set((scope?.partTypeIds || []).filter(Boolean));
  let directFamily = null, directLeaf = null, containedFamily = null, fallbackType = null;

  for (const category of (_pickerState.browseTree || [])) {
    for (const child of (category.children || [])) {
      if (child.kind === "family") {
        const members = child.members || [];
        const memberIds = new Set(members.map(member => member.part_type_id));
        if (child.family_id === refId) directFamily = { category, family: child, partType: null, flow: child.picker_flow || "" };
        const directMember = members.find(member => member.part_type_id === refId);
        if (directMember) directLeaf = { category, family: child, partType: directMember, flow: directMember.picker_flow || child.picker_flow || "" };
        if (!containedFamily && partTypeIds.size > 1 && [...partTypeIds].every(id => memberIds.has(id))) {
          containedFamily = { category, family: child, partType: null, flow: child.picker_flow || "" };
        }
        if (!fallbackType && [...partTypeIds].some(id => memberIds.has(id))) fallbackType = category;
      } else {
        if (child.part_type_id === refId) directLeaf = { category, family: null, partType: child, flow: child.picker_flow || "" };
        if (!fallbackType && partTypeIds.has(child.part_type_id)) fallbackType = category;
      }
    }
  }

  const found = directFamily || directLeaf || containedFamily;
  if (found) {
    return {
      type_id: found.category.type_id, type_label: found.category.label,
      family_id: found.family?.family_id || "", family_label: found.family?.label || "",
      part_type_id: found.partType?.part_type_id || "", part_type_label: found.partType?.label || "",
      flow: found.flow,
    };
  }
  return fallbackType ? {
    type_id: fallbackType.type_id, type_label: fallbackType.label,
    family_id: "", family_label: "", part_type_id: "", part_type_label: "", flow: "",
  } : null;
}

function _pickerApplyBrowseTarget(target) {
  const f = _pickerState.filters, c = _pickerState.config;
  f.type_id = target.type_id; f.type_label = target.type_label;
  f.family_id = target.family_id; f.family_label = target.family_label;
  f.part_type_id = target.part_type_id; f.part_type_label = target.part_type_label;
  f.category_id = target.flow || "";
  f.category_label = target.flow ? ((_LIGHT_CATEGORIES.find(x => x.id === target.flow) || {}).label || target.flow) : "";
  f.brand = ""; _pickerState._brandAutoSet = false;
  c._noColor = target.flow === "scene";
  _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
  _pickerState.tracer.active = false;
  _pickerState.innerEdge.active = false;
  _pickerState.outerEdge.active = false;
  _pickerState.lightbar.active = false;
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerBrowseExpanded.types.add(target.type_id);
  if (target.family_id) _pickerBrowseExpanded.families.add(target.family_id);
  _pickerRenderTracer(); _pickerRenderInnerEdge(); _pickerRenderOuterEdge(); _pickerRenderLightbar();
}

function pickerClose() {
  pickerCustomPartClose();
  _pickerState.open = false;
  _pickerState.editLineId = null;
  _pickerState.editPart = null;
  // Clear the tracer + accessory panels so they don't persist into the next open.
  _pickerState.tracer = { active: false, mode: _pickerState.tracer.mode,
                          secondary: _pickerState.tracer.secondary, lens: _pickerState.tracer.lens || "clear", preview: null, loading: false };
  _pickerState.accessories = []; _pickerState.accLoadedFor = null;
  _pickerState.tracer.active = false; _pickerState.innerEdge.active = false; _pickerState.outerEdge.active = false; _pickerState.lightbar.active = false;
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = _pickerNewWestinState();
  _pickerRenderTracer(); _pickerRenderInnerEdge(); _pickerRenderOuterEdge(); _pickerRenderLightbar(); _pickerRenderRadio();
  const acc = $("picker-accessories"); if (acc) { acc.hidden = true; acc.innerHTML = ""; }
  const panel = $("picker-panel");
  if (panel) panel.classList.remove("open");
}

// ── One-off billable custom parts ──────────────────────
// These remain draft-local billable rows.  The small recent list is only a
// convenience for this app installation; it never turns into QB inventory.
const _pickerCustomPartState = { wired: false, conflict: null, recent: [], editLineId: "", categoriesLoaded: false, returnToPicker: false };

function _pickerCustomPartInputs() {
  return {
    sku: $("picker-custom-part-sku"),
    description: $("picker-custom-part-description"),
    price: $("picker-custom-part-price"),
    quantity: $("picker-custom-part-qty"),
    category: $("picker-custom-part-category"),
  };
}

function _pickerCustomClearConflict() {
  _pickerCustomPartState.conflict = null;
  const el = $("picker-custom-part-conflict");
  if (!el) return;
  el.hidden = true;
  el.innerHTML = "";
}

function _pickerCustomShowConflict(part) {
  _pickerCustomPartState.conflict = part || null;
  const el = $("picker-custom-part-conflict");
  if (!el || !part) { _pickerCustomClearConflict(); return; }
  const label = [part.manufacturer_label, part.model].filter(Boolean).join(" · ") || "an existing catalog part";
  el.hidden = false;
  el.innerHTML = `<strong>This SKU already exists in the catalog.</strong><br>${esc(part.part_number)} is ${esc(label)}. Use the catalog part so its normal setup, placement, and QB linkage stay intact.
    <div class="picker-custom-part-conflict-actions">
      <button type="button" data-custom-use-existing>Use existing SKU</button>
      <button type="button" data-custom-keep>Keep as custom part</button>
    </div>`;
  el.querySelector("[data-custom-use-existing]")?.addEventListener("click", _pickerCustomUseExisting);
  el.querySelector("[data-custom-keep]")?.addEventListener("click", () => _pickerCustomSubmit(true));
}

function _pickerCustomRenderRecent() {
  const wrap = $("picker-custom-part-recent-wrap");
  const list = $("picker-custom-part-recent-list");
  if (!wrap || !list) return;
  const entries = _pickerCustomPartState.recent || [];
  wrap.hidden = !entries.length;
  list.innerHTML = entries.map((part, index) =>
    `<button type="button" data-custom-recent="${index}" title="Use this information again">${esc(part.sku)} · ${esc(part.description)} · $${Number(part.unit_price).toFixed(2)}</button>`
  ).join("");
  list.querySelectorAll("[data-custom-recent]").forEach(button => button.addEventListener("click", () => {
    const part = entries[parseInt(button.dataset.customRecent || "-1", 10)];
    if (!part) return;
    const inputs = _pickerCustomPartInputs();
    inputs.sku.value = part.sku || "";
    inputs.description.value = part.description || "";
    inputs.price.value = Number(part.unit_price).toFixed(2);
    _pickerCustomClearConflict();
  }));
}

async function _pickerCustomLoadRecent() {
  try {
    const result = await api("/api/draft/custom-parts");
    _pickerCustomPartState.recent = Array.isArray(result?.parts) ? result.parts : [];
  } catch (error) {
    console.warn("Custom parts history failed to load", error);
    _pickerCustomPartState.recent = [];
  }
  _pickerCustomRenderRecent();
}

async function _pickerCustomLoadCategories() {
  if (_pickerCustomPartState.categoriesLoaded) return;
  const select = $("picker-custom-part-category");
  if (!select) return;
  try {
    const result = await api("/api/parts-db/manifest-groups");
    const options = [`<option value="">Other / Custom Parts</option>`];
    for (const group of (result?.groups || [])) {
      const rows = (group.subgroups || []).filter(row => (row.part_types || []).length);
      if (!rows.length) continue;
      options.push(`<optgroup label="${esc(group.label || group.group_id)}">`);
      for (const row of rows) {
        options.push(`<option value="${esc(row.part_types[0])}">${esc(row.label || row.subgroup_id)}</option>`);
      }
      options.push(`</optgroup>`);
    }
    select.innerHTML = options.join("");
    _pickerCustomPartState.categoriesLoaded = true;
  } catch (error) {
    console.warn("Custom part categories failed to load", error);
  }
}

async function _pickerCustomCheckSku() {
  const sku = _pickerCustomPartInputs().sku?.value.trim() || "";
  if (!sku) { _pickerCustomClearConflict(); return; }
  try {
    const result = await api(`/api/parts-db/sku-lookup?sku=${encodeURIComponent(sku)}`);
    // Ignore a slow response for a SKU the user has since changed.
    if ((_pickerCustomPartInputs().sku?.value.trim() || "") !== sku) return;
    _pickerCustomShowConflict(result?.found ? result.part : null);
  } catch (error) {
    console.warn("SKU lookup failed", error);
  }
}

function _pickerCustomWire() {
  if (_pickerCustomPartState.wired) return;
  const form = $("picker-custom-part-form");
  form?.addEventListener("submit", event => {
    event.preventDefault();
    _pickerCustomSubmit(false);
  });
  $("picker-custom-part-close")?.addEventListener("click", pickerCustomPartClose);
  $("picker-custom-part-cancel")?.addEventListener("click", pickerCustomPartClose);
  const inputs = _pickerCustomPartInputs();
  inputs.sku?.addEventListener("input", _pickerCustomClearConflict);
  inputs.sku?.addEventListener("blur", _pickerCustomCheckSku);
  _pickerCustomPartState.wired = true;
}

async function pickerCustomPartOpen(part = null) {
  const draftId = (typeof _meDraftId !== "undefined") ? _meDraftId : null;
  if (!draftId) { toast("No active build", "error"); return; }
  _pickerCustomWire();
  _pickerCustomClearConflict();
  _pickerCustomPartState.editLineId = part?.line_id || "";
  const pickerPanel = $("picker-panel");
  _pickerCustomPartState.returnToPicker = !!pickerPanel?.classList.contains("open");
  if (_pickerCustomPartState.returnToPicker) pickerPanel.classList.remove("open");
  const form = $("picker-custom-part-form");
  form?.reset();
  await _pickerCustomLoadCategories();
  const inputs = _pickerCustomPartInputs();
  const custom = part?.picker_config?.custom_part || {};
  inputs.sku.value = custom.sku || part?.part_number || "";
  inputs.description.value = custom.description || part?.name || "";
  inputs.price.value = custom.unit_price ?? "";
  inputs.quantity.value = part?.quantity || 1;
  inputs.category.value = part?.part_type && part.part_type !== "custom_part" ? part.part_type : "";
  const editing = !!_pickerCustomPartState.editLineId;
  const title = $("picker-custom-part-title");
  const save = $("picker-custom-part-save");
  if (title) title.textContent = editing ? "Edit Custom Part" : "Add Custom Part";
  if (save) save.textContent = editing ? "Save custom part" : "Add billable custom part";
  $("picker-custom-part-modal")?.classList.add("open");
  $("picker-custom-part-sku")?.focus();
  await _pickerCustomLoadRecent();
}

function pickerCustomPartClose(options = {}) {
  const reopenPicker = options?.reopen !== false;
  $("picker-custom-part-modal")?.classList.remove("open");
  _pickerCustomClearConflict();
  _pickerCustomPartState.editLineId = "";
  if (reopenPicker && _pickerCustomPartState.returnToPicker) $("picker-panel")?.classList.add("open");
  _pickerCustomPartState.returnToPicker = false;
}

async function _pickerCustomUseExisting() {
  const match = _pickerCustomPartState.conflict;
  if (!match?.product_id || !match?.part_number) return;
  pickerCustomPartClose();
  _pickerState.search = match.part_number;
  _pickerState.searchGlobal = true;
  _pickerState.sel = null;
  _pickerState.expanded = new Set();
  _pickerState.skuChoices = {};
  await _pickerFetchProducts();
  const product = (_pickerState.products || []).find(item => item.product_id === match.product_id);
  const sku = product?.skus?.find(item => item.part_number === match.part_number);
  if (!product || !sku) { toast("Could not open the existing catalog SKU", "error"); return; }

  const contextChanged = _pickerApplyProductContext(product);
  _pickerResetLocation();
  _pickerState.expanded = new Set([product.product_id]);
  const usesColor = _pickerUsesColor(product) && _pickerProductHasColor(product);
  if (usesColor) {
    _pickerState.sel = { product_id: product.product_id, model: product.model, mfr: product.manufacturer_label };
    _pickerApplyProductColorDefaults(product);
    const colors = [sku.color, sku.secondary_color, sku.tertiary_color]
      .filter(Boolean).map(color => String(color).toLowerCase());
    if (colors.length) {
      const c = _pickerState.config;
      c.colorsPerHead = colors.length === 1 ? "single" : colors.length === 2 ? "duo" : "trio";
      c.mode = "uniform";
      c.uniform = colors;
      c._noColor = false;
      c.count = 1;
      _pickerState.skuChoices = { head_0: sku.part_number };
    }
    if (sku.lens_type) _pickerState.filters.lens = sku.lens_type;
  } else {
    _pickerState.sel = { product_id: product.product_id, model: product.model, mfr: product.manufacturer_label, sku: sku.part_number };
  }
  _pickerActivateWestinBumper(product);
  if (contextChanged) _pickerRenderFilters();
  _pickerRenderProducts(); _pickerUpdateFooter();
  _pickerLoadAccessories(product.product_id);
  _pickerLoadTracer(product.product_id);
  _pickerLoadInnerEdge(product.product_id);
  _pickerLoadOuterEdge(product.product_id);
  _pickerLoadLightbar(product.product_id);
  _pickerLoadFixture(product.product_id);
  _pickerApplyFixedPartLocation();
  toast("Opened the existing SKU — finish its normal setup", "info");
}

async function _pickerCustomSubmit(allowExistingDuplicate) {
  const form = $("picker-custom-part-form");
  if (form && !form.reportValidity()) return;
  const draftId = (typeof _meDraftId !== "undefined") ? _meDraftId : null;
  if (!draftId) { toast("No active build", "error"); return; }
  const inputs = _pickerCustomPartInputs();
  const save = $("picker-custom-part-save");
  if (save) save.disabled = true;
  try {
    const editLineId = _pickerCustomPartState.editLineId;
    const endpoint = editLineId
      ? `/api/draft/${draftId}/custom-part/${editLineId}/update`
      : `/api/draft/${draftId}/custom-part`;
    const result = await api(endpoint, {
      sku: inputs.sku.value.trim(),
      description: inputs.description.value.trim(),
      unit_price: inputs.price.value,
      quantity: inputs.quantity.value,
      part_type: inputs.category.value,
      allow_existing_duplicate: !!allowExistingDuplicate,
    });
    if (result?.error === "catalog_sku_exists") {
      _pickerCustomShowConflict(result.catalog_part);
      return;
    }
    if (!result?.ok) {
      toast(result?.error || "Could not add custom part", "error");
      return;
    }
    pickerCustomPartClose({ reopen: false });
    toast(editLineId ? "Custom part updated" : "Billable custom part added", "success");
    await _pickerFinalize(draftId, false);
  } catch (error) {
    console.error("Custom part save failed", error);
    toast("Could not add custom part", "error");
  } finally {
    if (save) save.disabled = false;
  }
}

// Cancel the current product selection and close the bottom config panels
// (tracer / lightbar / accessories) so they stop blocking the product list.
function _pickerClearSelection() {
  _pickerState.sel = null;
  _pickerState.tracer.active = false;
  _pickerState.innerEdge.active = false;
  _pickerState.outerEdge.active = false;
  _pickerState.lightbar.active = false;
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = _pickerNewWestinState();
  _pickerState.sirenDualTones = false;
  _pickerState.accessories = []; _pickerState.accessoryChoices = {};
  _pickerState.accessoryQuantities = {}; _pickerState.accessoryQuantityManual = {};
  _pickerState.accLoadedFor = null;
  _pickerResetLocation();
  _pickerRenderProducts();
  _pickerRenderTracer(); _pickerRenderInnerEdge(); _pickerRenderOuterEdge(); _pickerRenderLightbar(); _pickerRenderRadio(); _pickerRenderAccessories();
  _pickerUpdateFooter();
}

// PICKER_REDESIGN.md Step 6: full pre-fill + type-lock replacing the F-005 stopgap.
// Opens the picker with every filter, product box, and option already set to
// exactly the state the user left when they added/last-saved this part.
async function _pickerOpenEdit(part) {
  if (!part) return;
  // Every console-owned row routes back to the one setup that owns the
  // combined choices, whether it is nested below the console or (for the
  // separately manifested printer) remains a top-level parent.
  const ownerLineId = part.picker_config?.console_setup_owner_line_id;
  if (ownerLineId && typeof _meDraft !== "undefined") {
    const owner = (_meDraft?.parts || []).find(candidate => candidate.line_id === ownerLineId);
    if (owner) part = owner;
  }
  _pickerResetState();
  _pickerState.editLineId = part.line_id;
  _pickerState.editPart = part;
  _pickerSetSupplyFromRecord(part);
  _pickerState.comment = part.comment || "";
  _pickerOpenPanel("Edit Part");
  await _pickerLoadTypes();

  // Guided systems always restart at their first question for review, while
  // preserving every saved answer. They intentionally bypass the ordinary
  // SKU editor.
  const systemType = part.picker_config?.system_type || "";
  if (systemType && _SYSTEM_DEFS[systemType]) {
    _pickerSetSystemFilters(systemType);
    await _pickerLoadSystemWorkflow(systemType, part.picker_config?.choices || {}, 0);
    _pickerState.loc.selected = part.location || null;
    _pickerSwitchTab("location");
    return;
  }

  // ── 1. Determine type_id / category_id / part_type_id from the browse tree ──
  const partTypeId = part.part_type || "";
  let foundTypeId = "lights", foundCategoryId = "", foundPartTypeLabel = "", foundFamilyId = "", foundFamilyLabel = "";
  if (partTypeId) {
    outer: for (const cat of (_pickerState.browseTree || [])) {
      for (const child of (cat.children || [])) {
        if (child.kind === "part_type" && child.part_type_id === partTypeId) {
          foundTypeId = cat.type_id; foundPartTypeLabel = child.label; break outer;
        }
        if (child.kind === "family") {
          for (const m of (child.members || [])) {
            if (m.part_type_id === partTypeId) {
              foundTypeId = cat.type_id; foundCategoryId = child.picker_flow || "";
              foundPartTypeLabel = m.label; foundFamilyId = child.family_id; foundFamilyLabel = child.label; break outer;
            }
          }
        }
      }
    }
  }
  _pickerState.filters.type_id = foundTypeId;
  _pickerState.filters.family_id = foundFamilyId;
  _pickerState.filters.family_label = foundFamilyLabel;
  // A visible leaf may represent a small set of physical part types (the
  // Interior Light Bar leaf combines front/rear bars).  Reopen an existing
  // rear-bar selection through that visible leaf, while retaining its actual
  // product-specific type when it is saved.
  const visibleMember = foundFamilyId
    ? (_pickerState.browseTree || [])
      .flatMap(cat => cat.children || [])
      .find(child => child.kind === "family" && child.family_id === foundFamilyId)
      ?.members?.find(member => !member.browse_hidden
        && (member.part_type_id === partTypeId
          || (member.browse_part_type_ids || []).includes(partTypeId)))
    : null;
  _pickerState.filters.part_type_id = visibleMember?.part_type_id || partTypeId;
  _pickerState.filters.part_type_ids = visibleMember?.browse_part_type_ids || [];
  _pickerState.filters.part_type_label = foundPartTypeLabel;
  _pickerState.filters.category_id = foundCategoryId;
  _pickerState.filters.category_label = foundCategoryId
    ? ((_LIGHT_CATEGORIES.find(x => x.id === foundCategoryId) || {}).label || foundCategoryId) : "";

  // Expand tree to the correct path so the user sees where they are.
  if (foundTypeId) _pickerBrowseExpanded.types.add(foundTypeId);
  if (foundFamilyId) _pickerBrowseExpanded.families.add(foundFamilyId);

  // ── 2. Restore picker config from persisted snapshot or derive ─────────────
  const pc = part.picker_config || {};
  const c = _pickerState.config;
  if (Object.keys(pc).length) {
    // Full restore from saved snapshot — exact round-trip.
    c.mode            = pc.mode            || "uniform";
    c.colorsPerHead   = pc.colorsPerHead   || "single";
    c.uniform         = pc.uniform         ? [...pc.uniform]         : c.uniform;
    c.splitSecondary  = pc.splitSecondary  ? [...pc.splitSecondary]  : c.splitSecondary;
    c.custom          = pc.custom          ? pc.custom.map(a => [...a]) : c.custom;
    c._noColor        = pc._noColor        || false;
    c.count           = pc.count           || 1;
    if (pc.lens) _pickerState.filters.lens = pc.lens;
    _pickerState.skuChoices = pc.skuChoices ? { ...pc.skuChoices } : {};
  } else {
    // Legacy part (no picker_config): derive best-effort from stored fields.
    c.count = part.quantity || 1;
    // Derive color from raw_color: "Red" → uniform:["red"], "Red/White" → cph=duo
    if (part.raw_color && foundCategoryId && _COLOR_CATEGORIES.has(foundCategoryId)) {
      const colors = part.raw_color.split(/[\s,/]+/).map(x => x.trim().toLowerCase()).filter(x => _PICKER_COLORS[x]);
      if (colors.length === 1) { c.uniform = [colors[0]]; c.colorsPerHead = "single"; }
      else if (colors.length === 2) { c.uniform = colors; c.colorsPerHead = "duo"; }
      else if (colors.length >= 3) { c.uniform = colors.slice(0, 3); c.colorsPerHead = "trio"; }
    }
    if (part.lens) _pickerState.filters.lens = part.lens;
    // Scene products have no color filter. Interior lights retain their saved
    // red/blue/white selection, like warning lights.
    c._noColor = foundCategoryId === "scene";
  }
  _pickerState.partDetails = {
    paMicLocation: pc.details?.paMicLocation || "",
    paMicLocationCustom: pc.details?.paMicLocationCustom || "",
    paMicClip: pc.details?.paMicClip || "",
    handheldMagMic: typeof pc.details?.handheldMagMic === "boolean" ? pc.details.handheldMagMic : null,
  };
  _pickerState.tint = {
    windows: Array.isArray(pc.window_tint?.windows) ? [...pc.window_tint.windows] : [],
    percentage: Math.min(100, Math.max(1, Number(pc.window_tint?.percentage) || 20)),
  };
  _pickerState.locationAllocation = {
    quantities: { ...(pc.location_allocation?.quantities || {}) },
    comments: { ...(pc.location_allocation?.comments || {}) },
    batchId: String(pc.location_batch_id || pc.location_allocation?.batch_id || ""),
  };
  _pickerState.roundLightColor = pc.round_light?.warning_color === "blue"
    || (!pc.round_light && String(part.raw_color || "").toLowerCase().includes("blue"))
    ? "blue" : "red";
  if (_pickerState.locationAllocation.batchId && typeof _meDraft !== "undefined") {
    const siblings = (_meDraft?.parts || []).filter(candidate =>
      String(candidate.picker_config?.location_batch_id || "") === _pickerState.locationAllocation.batchId
    );
    for (const sibling of siblings) {
      if (sibling.location) _pickerState.locationAllocation.quantities[sibling.location] = Number(sibling.quantity) || 1;
      if (sibling.location) _pickerState.locationAllocation.comments[sibling.location] = String(sibling.comment || "");
    }
    c.count = Math.max(1, Object.values(_pickerState.locationAllocation.quantities).reduce((sum, value) => sum + (Number(value) || 0), 0));
    _pickerNormalizeConfig();
  }
  _pickerState.sirenDualTones = pc.siren_dual_tones === true;
  if (pc.westin) {
    _pickerState.westin = {
      ..._pickerNewWestinState(), active: true,
      wire: pc.westin.wire || "", channel: pc.westin.channel || "",
      lights: { ..._pickerNewWestinState().lights, ...(pc.westin.lights || {}) },
    };
  }

  // ── 3. Pre-set location so Save from the Part tab works without touching Location ──
  _pickerState.loc.selected = part.location || null;
  if (pc.custom_location?.label) {
    _pickerState.loc.textCustom = true;
    _pickerState.loc.renderLocation = pc.custom_location.render_location || "";
    _pickerState.loc.customPlacements = _pickerNormalizeCustomPlacements(pc.custom_location.placements);
    _pickerState.loc.customPlacementAnchors = _pickerNormalizeCustomAnchors(pc.custom_location.anchors);
    _pickerState.loc.customHeadSpacing = _pickerNormalizeCustomSpacing(pc.custom_location.spacing);
    _pickerState.loc.customPlacementLayout = pc.custom_location.layout === "mirrored_pairs" ? "mirrored_pairs" : "even";
    _pickerState.loc.customPlacementMode = _pickerCustomPlacementCount() ? "free" : "vehicle";
    _pickerState.loc.customStage = (_pickerState.loc.renderLocation || _pickerCustomPlacementCount()) ? "placement" : "name";
  }

  // ── 4. Fetch products and pre-select ──────────────────────────────────────
  await _pickerFetchProducts();
  const pn = (part.components && part.components[0] && part.components[0].part_number) || part.part_number;
  const prod = _pickerState.products.find(p => p.skus.some(s => s.part_number === pn));
  if (prod) {
    // For color products (warning/interior lights) sel.sku must NOT be set —
    // `usesColor` in _pickerDoAdd is gated on `!sel.sku`, and skuChoices carries
    // the per-head overrides. For non-color products (equipment, programmable
    // bars) sel.sku identifies the exact chosen SKU.
    const pColor = _pickerUsesColor(prod) && _pickerProductHasColor(prod);
    _pickerState.sel = pColor
      ? { product_id: prod.product_id, model: prod.model, mfr: prod.manufacturer_label }
      : { product_id: prod.product_id, model: prod.model, mfr: prod.manufacturer_label, sku: pn };
    _pickerState.expanded.add(prod.product_id);
    // Owner flaw #5 / requirement D: the part's own already-chosen brand
    // must win over any brand preference — _pickerFetchProducts already
    // skipped auto-select above (editLineId was set before that call), so
    // this is the only place f.brand gets set in edit mode.
    _pickerState.filters.brand = prod.manufacturer_label || "";
    _pickerState._brandAutoSet = true;
    if (pc.westin && _pickerIsWestinBasePushBumper(prod)) {
      _pickerState.westin.parentProductId = prod.product_id;
    }
    await _pickerLoadAccessories(prod.product_id, { restoreFromDraft: true });
    await _pickerLoadInnerEdge(prod.product_id, { restoreFromDraft: true });
    await _pickerLoadOuterEdge(prod.product_id, { restoreFromDraft: true });
    if (pc.westin?.channel) await _pickerSetWestinChannel(pc.westin.channel);
  }
  if (_pickerIsConsoleContext() && pc.console_setup) {
    await _pickerBeginConsoleSetup(pc.console_setup);
    return;
  }
  _pickerSwitchTab("part");
  // An edit can restore a valid product far down a long catalog. Keep the
  // expanded product in view so it is obvious that its SKU/options were found.
  requestAnimationFrame(_pickerScrollSelectedProductIntoView);
}

// ── Shell ──────────────────────────────────────────────

function _pickerResetState() {
  _pickerState.open = true;
  _pickerState.editLineId = null;
  _pickerState.editPart = null;
  _pickerState.tab = "part";
  _pickerState.step = 0;          // current left-pane wizard step
  _pickerState.filters = { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", family_id: "", family_label: "", part_type_id: "", part_type_ids: [], part_type_label: "", brand: "", lens: "" };
  // FINDING-011: this was never reset between picker opens, so the auto-set
  // latch from a prior open (or a stale re-open of the same session) could
  // silently suppress preferred-brand auto-select on the next open.
  _pickerState._brandAutoSet = false;
  _pickerState.config = { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false };
  _pickerState.search = "";
  _pickerState.searchGlobal = true;
  _pickerState.allProducts = null;
  _pickerState.products = [];
  _pickerState.expanded = new Set();
  _pickerState.sel = null;
  _pickerState.skuChoices = {};   // "head_N" → chosen part_number (per-head override, Step 3)
  _pickerState.optionsRemoved = false;
  _pickerState.loc = { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, textCustom: false, renderLocation: "", customStage: "", customPlacementMode: "vehicle", customPlacementLayout: "even", customPlacements: {}, customPlacementAnchors: {}, customHeadSpacing: 0.06, autoLocation: "", name_pattern: "", base_label: "" };
  _pickerState.partDetails = { paMicLocation: "", paMicLocationCustom: "", paMicClip: "", handheldMagMic: null };
  _pickerState.tint = { windows: [], percentage: 20 };
  _pickerState.locationAllocation = { quantities: {}, comments: {}, batchId: "" };
  _pickerState.roundLightColor = "red";
  _pickerState.sirenDualTones = false;
  _pickerState.comment = "";
  _pickerState.accessories = [];
  _pickerState.accessoryChoices = {};
  _pickerState.accessoryQuantities = {};
  _pickerState.accessoryQuantityManual = {};
  _pickerState.accLoadedFor = null;
  _pickerState.tracer = { active: false, mode: "trio", secondary: "white", lens: "clear", custom: {}, preview: null, loading: false };
  _pickerState.innerEdge = { active: false, mode: "duo", secondary: "white", coverage: "both", preview: null, loading: false };
  _pickerState.outerEdge = { active: false, mode: "duo", secondary: "white", preview: null, loading: false };
  _pickerState.lightbar = { active: false, setup: "standard", edition: "clear", notes: "" };
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = _pickerNewWestinState();
  _pickerState.partStatus = "New";
  _pickerState.supply = { supplyType: "new", customerCondition: "", customerSource: "" };
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
    $("picker-add-another-btn")?.addEventListener("click", () => { if (_pickerState.footerHandlerAnother) _pickerState.footerHandlerAnother(); });
    $("picker-tab-btn-part")?.addEventListener("click", () => _pickerSwitchTab("part"));
    $("picker-tab-btn-location")?.addEventListener("click", () => _pickerSwitchTab("location"));
    document.querySelectorAll("[data-picker-supply-type]").forEach(btn => {
      btn.addEventListener("click", () => _pickerSetSupplyType(btn.dataset.pickerSupplyType));
    });
    document.querySelectorAll("[data-picker-customer-condition]").forEach(btn => {
      btn.addEventListener("click", () => _pickerSetCustomerCondition(btn.dataset.pickerCustomerCondition));
    });
    $("picker-customer-source")?.addEventListener("input", event => {
      _pickerState.supply.customerSource = event.target.value;
      _pickerRenderPartStatus(); _pickerUpdateFooter();
    });
    $("picker-part-comment")?.addEventListener("input", event => {
      _pickerState.comment = event.target.value;
    });
    $("picker-comment-toggle")?.addEventListener("click", () => {
      _pickerOpenCommentStep();
    });
    _pickerState._footerWired = true;
  }
  _pickerRenderPartStatus();
  const comment = $("picker-part-comment");
  if (comment) comment.value = _pickerState.comment || "";
  _pickerSyncCommentStep();
}

function _pickerSyncCommentStep() {
  const step = $("picker-comment-step");
  const entry = $("picker-comment-entry");
  const toggle = $("picker-comment-toggle");
  const comment = $("picker-part-comment");
  if (!step || !entry || !toggle) return;

  // Multi-location round lights expose one note field per manifest row in the
  // allocation grid. Hiding the shared footer note prevents one value from
  // being misleadingly copied to every selected location.
  const available = !!_pickerState.sel && !_pickerUsesLocationAllocation();
  step.hidden = !available;
  if (!available) {
    entry.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    return;
  }

  // Preserve an intentionally opened field while options render, and reopen it
  // for an existing part that already has a saved manifest comment.
  const open = !entry.hidden || !!String(_pickerState.comment || "").trim();
  entry.hidden = !open;
  toggle.textContent = open ? "Hide part notes" : "+ Add part notes";
  toggle.setAttribute("aria-expanded", String(open));
  if (comment && comment.value !== (_pickerState.comment || "")) comment.value = _pickerState.comment || "";
}

function _pickerOpenCommentStep() {
  const step = $("picker-comment-step");
  const entry = $("picker-comment-entry");
  const toggle = $("picker-comment-toggle");
  const comment = $("picker-part-comment");
  if (!step || !entry || !toggle || step.hidden) return;
  const open = entry.hidden;
  entry.hidden = !open;
  toggle.textContent = open ? "Hide part notes" : "+ Add part notes";
  toggle.setAttribute("aria-expanded", String(open));
  if (open) requestAnimationFrame(() => comment?.focus());
}

window.pickerOpenCommentStep = _pickerOpenCommentStep;

function _pickerNormalPartStatus(value) {
  const found = ["New", "Used", "Reused"].find(status =>
    status.toLowerCase() === String(value || "").trim().toLowerCase());
  return found || "New";
}

function _pickerSupplyFromRecord(record = {}) {
  const legacy = String(record.new_or_used || "").trim().toLowerCase();
  const explicit = String(record.supply_type || "").trim().toLowerCase();
  const customer = explicit === "customer_supplied" || (!explicit && ["used", "reused", "u", "r", "transfer", "transferred"].includes(legacy));
  return {
    supplyType: customer ? "customer_supplied" : "new",
    customerCondition: customer
      ? (["new", "used"].includes(String(record.customer_condition || "").trim().toLowerCase())
        ? String(record.customer_condition).trim().toLowerCase() : "used")
      : "",
    customerSource: customer ? String(record.customer_source || record.source || "").trim() : "",
  };
}

function _pickerSetSupplyFromRecord(record = {}) {
  _pickerState.supply = _pickerSupplyFromRecord(record);
  _pickerState.partStatus = _pickerState.supply.supplyType === "new" ? "New" : "Used";
}

function _pickerSupplyPayload(supply = _pickerState.supply) {
  const customer = supply?.supplyType === "customer_supplied";
  const customerCondition = customer && ["new", "used"].includes(supply.customerCondition)
    ? supply.customerCondition : "";
  const customerSource = customer ? String(supply.customerSource || "").trim() : "";
  return {
    supply_type: customer ? "customer_supplied" : "new",
    customer_condition: customerCondition,
    customer_source: customerSource,
    new_or_used: customer ? "Used" : "New",
    source: customerSource,
  };
}

function _pickerSupplySatisfied(supply = _pickerState.supply) {
  if (supply?.supplyType !== "customer_supplied") return true;
  if (!["new", "used"].includes(supply.customerCondition)) return false;
  return supply.customerCondition !== "used" || Boolean(String(supply.customerSource || "").trim());
}

function _pickerSetSupplyType(value) {
  const customer = value === "customer_supplied";
  _pickerState.supply.supplyType = customer ? "customer_supplied" : "new";
  if (!customer) {
    _pickerState.supply.customerCondition = "";
    _pickerState.supply.customerSource = "";
  }
  _pickerState.partStatus = customer ? "Used" : "New";
  _pickerRenderPartStatus(); _pickerUpdateFooter();
}

function _pickerSetCustomerCondition(value) {
  _pickerState.supply.customerCondition = ["new", "used"].includes(value) ? value : "";
  if (value !== "used") _pickerState.supply.customerSource = "";
  _pickerRenderPartStatus(); _pickerUpdateFooter();
}

function _pickerSetPartStatus(value) {
  const status = _pickerNormalPartStatus(value);
  _pickerSetSupplyFromRecord({ new_or_used: status });
  _pickerRenderPartStatus(); _pickerUpdateFooter();
}

function _pickerRenderPartStatus() {
  const control = $("picker-part-status");
  if (!control) return;
  // Guided radio/radar/camera flows have their own condition question because
  // it changes the rest of their install workflow (for example cable refresh).
  control.hidden = !!(_pickerState.radio?.active || _pickerState.systemSetup?.active || _pickerState.consoleSetup?.active);
  document.querySelectorAll("[data-picker-supply-type]").forEach(btn => {
    const active = btn.dataset.pickerSupplyType === _pickerState.supply.supplyType;
    btn.classList.toggle("picker-part-status-btn--active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
  const condition = $("picker-customer-condition");
  if (condition) condition.hidden = _pickerState.supply.supplyType !== "customer_supplied";
  document.querySelectorAll("[data-picker-customer-condition]").forEach(btn => {
    const active = btn.dataset.pickerCustomerCondition === _pickerState.supply.customerCondition;
    btn.classList.toggle("picker-part-status-btn--active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
  const sourceWrap = $("picker-customer-source-wrap"), source = $("picker-customer-source");
  const sourceNeeded = _pickerState.supply.supplyType === "customer_supplied" && _pickerState.supply.customerCondition === "used";
  if (sourceWrap) {
    sourceWrap.hidden = !sourceNeeded;
    sourceWrap.classList.toggle("source-needed", sourceNeeded && !String(_pickerState.supply.customerSource || "").trim());
  }
  if (source) {
    if (source.value !== (_pickerState.supply.customerSource || "")) source.value = _pickerState.supply.customerSource || "";
    source.required = sourceNeeded;
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
    _pickerRenderRadio();
  } else if (_pickerState.radio?.active || _pickerState.consoleSetup?.active) {
    _pickerRenderRadio();
  } else {
    _pickerRenderRadio();
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
    if (_pickerUseGlobalSearch()) {
      if (!_pickerState.allProducts) {
        const res = await api("/api/parts-db/category-skus?all=1");
        _pickerState.allProducts = res?.products || [];
      }
      _pickerState.products = _pickerState.allProducts;
    } else {
      const browsePartTypeIds = (f.part_type_ids || []).filter(Boolean);
      const ptParam = f.part_type_id ? `&part_type=${encodeURIComponent(f.part_type_id)}` : "";
      const ptParams = browsePartTypeIds.length > 1
        ? `&part_types=${encodeURIComponent(browsePartTypeIds.join(","))}` : "";
      const familyParam = (!f.part_type_id && f.family_id) ? `&family=${encodeURIComponent(f.family_id)}` : "";
      const url = `/api/parts-db/category-skus?type=${encodeURIComponent(f.type_id)}&category=${encodeURIComponent(f.category_id || "")}${familyParam}${ptParam}${ptParams}`;
      const res = await api(url);
      _pickerState.products = res?.products || [];
    }
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
  // Auto-select the preferred brand for this context (lighting/bumper/cage/
  // camera — FINDING-011: this used to run twice, lighting-only, here AND in
  // _pickerRenderProducts). Skipped in edit mode — _pickerOpenEdit sets
  // f.brand explicitly from the part being edited so an explicit prior
  // selection is never silently overridden by a preference.
  if (!_pickerUseGlobalSearch() && !f.brand && !_pickerState.editLineId) {
    const preferred = _pickerPreferredBrand(f);
    if (preferred) { f.brand = preferred; _pickerState._brandAutoSet = true; }
  }
  // A search result is a product-level result list, even when only one card
  // matches through a child SKU.  Leave it collapsed until the user chooses
  // to inspect the product; normal filtered browsing keeps its convenience
  // auto-expand behavior.
  if (!_pickerState.search.trim() && _pickerState.products.length === 1) {
    _pickerState.expanded.add(_pickerState.products[0].product_id);
  }
}

function _pickerUseGlobalSearch() {
  return !!(_pickerState.search && _pickerState.search.trim() && _pickerState.searchGlobal);
}

// ── Filters pane (left) ────────────────────────────────

// The left pane is a click-through wizard: one filter group per page, with the
// product list narrowing live on the right. Steps depend on the type/category.
function _pickerSelectedProduct() {
  const productId = _pickerState.sel?.product_id;
  return productId ? (_pickerState.products || []).find(p => p.product_id === productId) || null : null;
}

function _pickerProductType(product = null) {
  return product?.primary_type_id || _pickerSelectedProduct()?.primary_type_id
    || _pickerState.filters.type_id || "";
}

function _pickerProductCategory(product = null) {
  return product?.primary_category_id || _pickerSelectedProduct()?.primary_category_id
    || _pickerState.filters.category_id || "";
}

function _pickerUsesColor(product = null) {
  return _pickerProductType(product) === "lights"
    && _COLOR_CATEGORIES.has(_pickerProductCategory(product));
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

  el.innerHTML = `<div class="pf-group pf-search"><input type="text" id="pf-search" placeholder="🔍 Search products / SKUs" value="${esc(_pickerState.search)}">
      <label class="pf-search-scope"><input type="checkbox" id="pf-search-current"${_pickerState.searchGlobal ? "" : " checked"}> Current filters only</label></div>
    <div class="pf-crumbs">${crumbs}</div>
    <div class="pf-stepbody">${content}</div>
    <div class="picker-custom-part-action"><button type="button" class="picker-custom-part-btn" data-picker-custom-part>＋ Add custom part<small>One-off SKU · billable on the QB quote</small></button></div>`;
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

function _pickerGuidedSystemKind(familyId) {
  return { radio_comms: "radio", radar: "radar", camera_system: "camera" }[familyId] || "";
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

  const editPT = _pickerState.editLineId ? _pickerState.editPart?.part_type : null;

  const leafHtml = (pt, cat, pickerFlow, family = null) => {
    const browsePartTypeIds = pt.browse_part_type_ids || [pt.part_type_id];
    const isFilled = browsePartTypeIds.some(partTypeId => filled.has(partTypeId));
    const active = _pickerState.filters.part_type_id === pt.part_type_id && _pickerState.filters.type_id === cat.type_id;
    // Type-lock (Step 6): a combined visible leaf stays available for either
    // of its physical part types when reopening an existing selection.
    const locked = !!editPT && !browsePartTypeIds.includes(editPT);
    return `<button class="pbt-leaf${isFilled ? " filled" : ""}${active ? " active" : ""}${locked ? " locked" : ""}"
      data-type="${esc(cat.type_id)}" data-type-label="${esc(cat.label)}"
      data-family="${esc(family?.family_id || "")}" data-family-label="${esc(family?.label || "")}"
      data-pt="${esc(pt.part_type_id)}" data-pt-label="${esc(pt.label)}"
      data-pt-ids="${esc(browsePartTypeIds.join(","))}"
      data-flow="${esc(pickerFlow || "")}">${esc(pt.label)}${isFilled ? ` <span class="pbt-dot" title="Already in this build"></span>` : ""}</button>`;
  };

  // Every family label is selectable. If the family has a picker_flow it also
  // activates that light flow; otherwise it filters by family member union.
  // `browse_collapsed` families (Scene, Spotlight) render as one selectable
  // row with no caret and no members — the collapse happens at the browse
  // level only (front/side/rear_scene stay in the data, just hidden).
  const famSelectHtml = (fam, cat, extraClass) => {
    const anyFilled = fam.members.some(m => filled.has(m.part_type_id));
    const active = _pickerState.filters.family_id === fam.family_id
      && _pickerState.filters.type_id === cat.type_id && _pickerState.filters.part_type_id === "";
    const locked = !!editPT && !fam.members.some(m => m.part_type_id === editPT);
    return `<button class="pbt-fam-select${active ? " active" : ""}${anyFilled ? " filled" : ""}${locked ? " locked" : ""}${extraClass ? " " + extraClass : ""}"
      data-type="${esc(cat.type_id)}" data-type-label="${esc(cat.label)}"
      data-family="${esc(fam.family_id)}" data-family-label="${esc(fam.label)}"
      data-pt="" data-pt-label="${esc(fam.label)}"
      data-flow="${esc(fam.picker_flow || "")}">${esc(fam.label)}${anyFilled ? ` <span class="pbt-dot" title="Already in this build"></span>` : ""}</button>`;
  };

  const childHtml = (child, cat) => {
    if (child.kind === "part_type") return leafHtml(child, cat, "");

    // Guided systems own one coherent setup flow. Their member leaves are
    // individual system pieces (antennas, mounts, cables, etc.), not the
    // normal way to start a complete radio/radar/camera install. Keep those
    // pieces behind the explicit "Choose SKUs manually" escape hatch.
    if (child.browse_collapsed || _pickerGuidedSystemKind(child.family_id)) {
      return `<div class="pbt-fam pbt-fam-collapsed pbt-fam-guided-system">${famSelectHtml(child, cat)}</div>`;
    }

    const open = _pickerBrowseExpanded.families.has(child.family_id);
    // anyFilled/lock checks use the FULL member list (including browse_hidden
    // ones like warning_light) — only rendering excludes them.
    const anyFilled = child.members.some(m => filled.has(m.part_type_id));
    // Each member carries its own flow (mixed-flow families like Light Bars
    // have members with different flows — interior_bar vs roof_bar).
    const members = open
      ? child.members.filter(m => !m.browse_hidden).map(m => leafHtml(m, cat, m.picker_flow || child.picker_flow, child)).join("")
      : "";

    return `<div class="pbt-fam">
      <div class="pbt-fam-row">
        ${famSelectHtml(child, cat)}
        <button class="pbt-fam-caret-btn${open ? " open" : ""}" data-fam="${esc(child.family_id)}" title="Expand"><span class="pbt-caret">${open ? "▾" : "▸"}</span></button>
      </div>
      <div class="pbt-fam-body">${members}</div>
    </div>`;
  };

  return cats.map(cat => {
    const open = _pickerBrowseExpanded.types.has(cat.type_id);
    const anyFilled = (cat.children || []).some(c =>
      c.kind === "part_type" ? filled.has(c.part_type_id) : c.members.some(m => filled.has(m.part_type_id)));
    const active = _pickerState.filters.type_id === cat.type_id
      && !_pickerState.filters.category_id && !_pickerState.filters.family_id && !_pickerState.filters.part_type_id;
    const body = open ? (cat.children || []).map(c => childHtml(c, cat)).join("") : "";
    return `<div class="pbt-cat">
      <div class="pbt-cat-row">
        <button class="pbt-cat-head${open ? " open" : ""}${active ? " active" : ""}" data-cat="${esc(cat.type_id)}" data-cat-label="${esc(cat.label)}">
          ${_TYPE_ICONS[cat.type_id] || "📦"} ${esc(cat.label)}${anyFilled ? ` <span class="pbt-dot" title="Has parts in this build"></span>` : ""}
        </button>
        <button class="pbt-cat-caret-btn${open ? " open" : ""}" data-cat="${esc(cat.type_id)}" title="Expand"><span class="pbt-caret">${open ? "▾" : "▸"}</span></button>
      </div>
      <div class="pbt-cat-body">${body}</div>
    </div>`;
  }).join("");
}

// Prepend the "Remove options" toggle. When filter is off, hide filter controls
// entirely (qty stays); clicking the button is the only re-engage path (Step 3).
function _pickerOptionsHtml(countHtml, filterHtml) {
  const off = _pickerState.optionsRemoved || false;
  const btn = `<div class="pf-group pp-opts-ctrl"><button class="pp-opts-toggle-btn${off ? " active" : ""}" data-opts-remove="1">${off ? "⊘ Filter off" : "Remove options"}</button></div>`;
  return btn + countHtml + (off ? "" : filterHtml);
}

function _pickerAllowedColors(product = null) {
  return _pickerProductCategory(product) === "interior"
    ? ["red", "blue", "white"]
    : _PICKER_COLOR_ORDER;
}

function _pickerColorConfigHtml(product = null) {
  const c = _pickerState.config;
  const f = _pickerState.filters;
  const cat = _pickerProductCategory(product);
  const isScene = cat === "scene";
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

  // Step 5: scene lights (category == "scene", which covers all scene_lights family
  // members including spotlight) show quantity only — no mode/lens/color/cph/
  // remove-options toggle. No filter options exist to remove for scene.
  if (cat === "scene") return countHtml;

  if (isBar) {
    return _pickerOptionsHtml(countHtml, `<div class="pf-group"><span class="pf-label">Colors per head</span><div class="pf-pills">
        ${seg("cph", "duo", "Duo", c.colorsPerHead !== "trio")}
        ${seg("cph", "trio", "Trio", c.colorsPerHead === "trio")}</div></div>` + lensHtml);
  }

  const cphHtml = `<div class="pf-group"><span class="pf-label">Colors per head</span><div class="pf-pills">
      ${seg("cph", "single", "Solo", c.colorsPerHead === "single")}
      ${seg("cph", "duo", "Duo", c.colorsPerHead === "duo")}
      ${seg("cph", "trio", "Trio", c.colorsPerHead === "trio")}</div></div>`;

  if (isScene) {
    const noColor = c._noColor === true;
    const whiteSwatches = _PICKER_COLOR_ORDER.map(col => {
      const d = _PICKER_COLORS[col];
      const isWhite = col === "white";
      const isSel = !noColor && c.uniform[0] === col;
      return `<button class="picker-swatch${isSel ? " sel" : (isWhite ? "" : " dim")}" data-color="${col}" ${isWhite ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("");
    const noneBtn = `<button class="picker-swatch${noColor ? " sel" : ""}" data-color="" title="No color (unlabeled)" style="background:#888;border-color:#666;font-size:9px;line-height:28px">—</button>`;
    return _pickerOptionsHtml(countHtml, cphHtml +
      `<div class="pf-group"><span class="pf-label">Color</span>` +
      `<div class="picker-swatches" data-kind="uniform" data-slot="0">${whiteSwatches}${noneBtn}</div></div>` + lensHtml);
  }

  const modeHtml = `<div class="pf-group"><span class="pf-label">Mode</span><div class="pf-pills">
      ${seg("mode", "uniform", "Identical", c.mode === "uniform")}
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

  return _pickerOptionsHtml(countHtml, cphHtml + modeHtml + sel + lensHtml);
}

function _pickerSwatchRow(kind, slot, selected) {
  const c = _pickerState.config;
  return `<div class="picker-swatches" data-kind="${kind}" data-slot="${slot}">` +
    _pickerAllowedColors().map(col => {
      const avail = c.__allowAll || _pickerState.availAll.has(col);
      const d = _PICKER_COLORS[col];
      return `<button class="picker-swatch${selected === col ? " sel" : ""}${avail ? "" : " dim"}" data-color="${col}" ${avail ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("") + `</div>`;
}

function _pickerSwatchMulti(head, arr, max) {
  return `<div class="picker-swatches" data-kind="custom" data-head="${head}">` +
    _pickerAllowedColors().map(col => {
      const avail = _pickerState.availAll.has(col);
      const d = _PICKER_COLORS[col];
      return `<button class="picker-swatch${arr.includes(col) ? " sel" : ""}${avail ? "" : " dim"}" data-color="${col}" ${avail ? "" : "disabled"} title="${esc(d.label)}" style="background:${d.hex};border-color:${d.border || d.hex}"></button>`;
    }).join("") + `<span style="font-size:11px;color:var(--muted)">${arr.length}/${max}</span></div>`;
}

function _pickerWireFilters() {
  const el = $("picker-filters");
  if (!el) return;
  $("pf-search")?.addEventListener("input", async e => {
    _pickerState.search = e.target.value;
    // Search changes which product cards are relevant, not which SKU rows are
    // visible inside them.  Start every new result set collapsed; a subsequent
    // product click may expand it and show that product's complete SKU list.
    _pickerState.expanded = new Set();
    await _pickerFetchProducts();
    _pickerRenderProducts();
    _pickerUpdateFooter();
  });
  $("pf-search-current")?.addEventListener("change", async e => {
    _pickerState.searchGlobal = !e.target.checked;
    _pickerState.expanded = new Set();
    await _pickerFetchProducts();
    _pickerRenderProducts();
    _pickerUpdateFooter();
  });
  $("pf-back")?.addEventListener("click", () => { _pickerState.step = Math.max(0, _pickerState.step - 1); _pickerRenderFilters(); });
  el.querySelectorAll(".pf-crumb").forEach(b => b.addEventListener("click", () => {
    const i = parseInt(b.dataset.step, 10);
    if (i <= _pickerState.step) { _pickerState.step = i; _pickerRenderFilters(); }
  }));

  // Browse-tree accordion: category/family caret buttons toggle expansion in
  // place; labels select filters and fetch products.
  el.querySelectorAll(".pbt-cat-caret-btn").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.cat;
    if (_pickerBrowseExpanded.types.has(id)) _pickerBrowseExpanded.types.delete(id);
    else _pickerBrowseExpanded.types.add(id);
    _pickerRenderFilters();
  }));
  el.querySelectorAll(".pbt-fam-caret-btn").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.fam;
    if (_pickerBrowseExpanded.families.has(id)) _pickerBrowseExpanded.families.delete(id);
    else _pickerBrowseExpanded.families.add(id);
    _pickerRenderFilters();
  }));
  el.querySelectorAll(".pbt-cat-head").forEach(b => b.addEventListener("click", async () => {
    const f = _pickerState.filters, c = _pickerState.config;
    const catId = b.dataset.cat;
    const wasSelected = f.type_id === catId && !f.category_id && !f.family_id && !f.part_type_id;
    const wasOpen = _pickerBrowseExpanded.types.has(catId);
    f.type_id = b.dataset.cat; f.type_label = b.dataset.catLabel;
    f.category_id = ""; f.category_label = "";
    f.family_id = ""; f.family_label = "";
    f.part_type_id = ""; f.part_type_ids = []; f.part_type_label = "";
    if (wasSelected && wasOpen) _pickerBrowseExpanded.types.delete(catId);
    else _pickerBrowseExpanded.types.add(catId);
    if (!_pickerState.editLineId) { f.brand = ""; _pickerState._brandAutoSet = false; }
    c._noColor = false;
    _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
    _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
    _pickerState.systemSetup = { active: false, kind: "", product: null };
    _pickerState.consoleSetup = _pickerNewConsoleSetup();
    await _pickerFetchProducts();
    _pickerRenderFilters(); _pickerRenderProducts(); _pickerRenderRadio(); _pickerUpdateFooter();
  }));
  // Leaf part_types and family labels share one handoff: set the filters and
  // fetch. A family label carries data-pt="" and data-family="<family_id>".
  el.querySelectorAll(".pbt-leaf, .pbt-fam-select").forEach(b => b.addEventListener("click", async () => {
    if (b.classList.contains("locked")) return;
    const f = _pickerState.filters, c = _pickerState.config;
    // Type-lock (Step 6): in edit mode, block navigation to a different part_type.
    const leafPartTypeIds = (b.dataset.ptIds || b.dataset.pt || "").split(",").filter(Boolean);
    if (_pickerState.editLineId && _pickerState.editPart?.part_type && b.dataset.pt
        && !leafPartTypeIds.includes(_pickerState.editPart.part_type)) return;
    const familyId = b.dataset.family || "";
    const partTypeId = b.dataset.pt || "";
    const wasSelected = !!familyId && !partTypeId
      && f.type_id === b.dataset.type && f.family_id === familyId && !f.part_type_id;
    const wasOpen = !!familyId && _pickerBrowseExpanded.families.has(familyId);
    f.type_id = b.dataset.type; f.type_label = b.dataset.typeLabel;
    f.family_id = familyId; f.family_label = b.dataset.familyLabel || "";
    f.part_type_id = partTypeId; f.part_type_ids = partTypeId ? leafPartTypeIds : []; f.part_type_label = b.dataset.ptLabel;
    const systemKind = _pickerGuidedSystemKind(familyId);
    if (familyId && !partTypeId && !systemKind) {
      if (wasSelected && wasOpen) _pickerBrowseExpanded.families.delete(familyId);
      else _pickerBrowseExpanded.families.add(familyId);
    } else if (systemKind) {
      _pickerBrowseExpanded.families.delete(familyId);
    }
    const flow = b.dataset.flow || "";
    f.category_id = flow; f.category_label = flow ? (_LIGHT_CATEGORIES.find(x => x.id === flow) || {}).label || flow : "";
    // Navigating to a different part_type moves into a different brand-
    // preference scope (e.g. lighting → cage) — drop the old brand filter so
    // _pickerFetchProducts re-resolves the preferred brand for the new
    // context instead of carrying a stale one forward. Not in edit mode:
    // type-lock already confines leaf clicks there to the locked part_type,
    // and the pre-filled edit brand must survive a re-click of that leaf.
    if (!_pickerState.editLineId) { f.brand = ""; _pickerState._brandAutoSet = false; }
    // Scene products have no color filter. Interior lights use the same
    // configurable flow as warning lights, restricted to red, blue, and white.
    c._noColor = flow === "scene";
    _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
    _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
    _pickerState.systemSetup = { active: false, kind: "", product: null };
    _pickerState.consoleSetup = _pickerNewConsoleSetup();
    await _pickerFetchProducts();
    if (systemKind && !partTypeId && !_pickerState.editLineId) {
      _pickerStartSystemSelection(systemKind);
    }
    // Step 2: always stay on browse — options are now in the product box.
    _pickerRenderFilters(); _pickerRenderProducts(); _pickerRenderRadio(); _pickerUpdateFooter();
  }));

  el.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", async () => {
    if (b.disabled) return;
    const k = b.dataset.k, v = b.dataset.v;
    const f = _pickerState.filters, c = _pickerState.config;
    if (k === "lens") { f.lens = v; _pickerRenderFilters(); _pickerRenderProducts(); return; }
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerRenderFilters(); _pickerRenderProducts(); _pickerRenderAccessories(); _pickerUpdateFooter(); return; }
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
  el.querySelector("[data-picker-custom-part]")?.addEventListener("click", pickerCustomPartOpen);
}

// ── Color config helpers (ported) ──────────────────────

function _pickerNormalizeConfig(product = null) {
  const c = _pickerState.config;
  const cat = _pickerProductCategory(product);
  const isBar = cat === "interior_bar" || cat === "roof_bar";
  const isScene = cat === "scene";
  // Bar categories: enforce duo minimum (no single)
  if (isBar && c.colorsPerHead === "single") c.colorsPerHead = "duo";
  const slots = _COLORS_PER_HEAD[c.colorsPerHead];
  const catDefault = isScene ? "white" : "red";
  const firstAvail = _pickerAllowedColors(product).find(x => _pickerState.availAll.has(x)) || catDefault;
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
// Preserve every requested color. A two- or three-color head cannot contain
// the same color twice: Red/Red must not select a single-red SKU, and
// Red/Blue/Blue must not select a red/blue SKU.
function _headSet(h) { return h.map(x => x.toLowerCase()).filter(Boolean).sort(); }
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
  if (p?.picker_direct_sku === true) return false;
  return (p.skus || []).some(s => s.color || s.secondary_color || s.tertiary_color);
}

function _pickerSkuAllowedForCurrentFlow(sku, product = null) {
  if (_pickerProductCategory(product) !== "interior") return true;
  const colors = [sku.color, sku.secondary_color, sku.tertiary_color].filter(Boolean);
  return colors.every(color => _pickerAllowedColors(product).includes(color));
}

function _pickerIsSirenSpeakerContext() {
  return _pickerResolvedPartTypeId(_pickerState.filters) === "siren_speaker";
}

function _pickerSirenSupportsDualTones() {
  return _pickerIsSirenSpeakerContext();
}

function _pickerSirenQtyHtml() {
  const q = Math.min(2, Math.max(1, _pickerState.config.count || 1));
  const dualTone = q === 2 && _pickerState.sirenDualTones && _pickerSirenSupportsDualTones();
  const toneChoice = q === 2 && _pickerSirenSupportsDualTones()
    ? `<div class="pf-group pp-siren-tone"><span class="pf-label">Dual siren tones?</span><div class="pf-pills">
         <button class="pf-pill${dualTone ? "" : " active"}" data-siren-dual-tone="no">No</button>
         <button class="pf-pill${dualTone ? " active" : ""}" data-siren-dual-tone="yes">Yes — add CEXAMP</button>
       </div><span class="pp-siren-note">Adds one WeCanX® External Amplifier so the two speakers can run dual siren tones.</span></div>`
    : "";
  return `<div class="pp-prod-options pp-siren-options">
    <div class="pf-group"><span class="pf-label">Speakers</span><div class="pf-pills">
      <button class="pf-pill${q === 1 ? " active" : ""}" data-siren-qty="1">1</button>
      <button class="pf-pill${q === 2 ? " active" : ""}" data-siren-qty="2">2</button>
    </div></div>${toneChoice}
  </div>`;
}

function _pickerSirenDualToneComponent() {
  if (_pickerState.config.count !== 2
      || !_pickerState.sirenDualTones
      || !_pickerSirenSupportsDualTones()) return null;
  return {
    label: "WeCanX External Amplifier",
    part_number: "CEXAMP",
    part_type: "external_amp",
    color: "",
    quantity: 1,
    price: null,
  };
}

function _pickerHowlerVehicleSkus(product, skus, vehicle) {
  if (product?.product_id !== "whelen_wcx_howler" || !vehicle) return skus;
  const vehicleKey = String(vehicle).toUpperCase();
  const preferredPartNumber = vehicleKey === "DURANGO"
    ? "CHWLDD36"
    : vehicleKey === "PIU" ? "CHWLFE29" : "CHWLUNI";
  const productSkus = product.skus || skus;
  const preferred = productSkus.find(sku => sku.part_number === preferredPartNumber);
  if (!preferred) return skus;
  // Preserve a historical saved choice while editing so it can be reviewed
  // and intentionally changed to the recommended current vehicle SKU.
  const savedPartNumber = _pickerState.editLineId && _pickerState.sel?.product_id === product.product_id
    ? _pickerState.sel.sku : "";
  const saved = savedPartNumber && savedPartNumber !== preferredPartNumber
    ? productSkus.find(sku => sku.part_number === savedPartNumber) : null;
  return saved ? [preferred, saved] : [preferred];
}

function _pickerIsWestinBasePushBumper(product) {
  if (!product || !(product.fits_part_types || []).includes("push_bumper")) return false;
  const brand = String(product.manufacturer_label || product.manufacturer_id || "").toLowerCase();
  const model = String(product.model || "");
  return brand.includes("westin")
    && /push bumper/i.test(model)
    && !/light channel|wire cover/i.test(model);
}

function _pickerNewWestinState() {
  return {
    active: false, parentProductId: "", wire: "", channel: "", channelInfo: null,
    lightProduct: null, loading: false, error: "",
    lights: { mode: "duo", secondary: "white", lens: "clear" },
  };
}

const _WESTIN_CHANNEL_LIGHT_TYPES = [
  { pattern: /whelen\s+ion/i, productId: "whelen_ion", label: "Whelen ION" },
  { pattern: /soundoff\s+nforce|\bnforce\b/i, productId: "soundoff_nforce_deck_grille", label: "SoundOff NForce" },
  { pattern: /mpower/i, productId: "soundoff_mpower_4_fascia", label: "SoundOff mPower 4\" Fascia" },
];

function _pickerWestinChannelInfo() {
  const value = _pickerState.westin?.channel || "";
  if (!value) return null;
  const [productId, partNumber] = value.split("::");
  const channel = _pickerWestinOptionProducts("channel")
    .find(product => product.product_id === productId);
  const sku = (channel?.skus || []).find(item => item.part_number === partNumber) || {};
  const description = [channel?.model, sku.friendly_name, sku.part_number].filter(Boolean).join(" ");
  const countMatch = description.match(/\b(\d+)\s*(?:[- ]?(?:hole|light))\b/i);
  const type = _WESTIN_CHANNEL_LIGHT_TYPES.find(candidate => candidate.pattern.test(description));
  if (!channel) return null;
  // Westin's solid-channel SKUs are valid bumper options, but have no holes
  // and therefore no included lightheads to configure.
  if (/solid channel/i.test(description)) {
    return {
      channelProductId: productId,
      channelModel: channel.model,
      channelPartNumber: partNumber,
      count: 0,
      noLights: true,
    };
  }
  if (!countMatch || !type) return null;
  return {
    channelProductId: productId,
    channelModel: channel.model,
    channelPartNumber: partNumber,
    count: Number(countMatch[1]),
    lightProductId: type.productId,
    lightLabel: type.label,
  };
}

function _pickerWestinChannelSecondaryOptions(product, mode, lens = "") {
  // Westin channel lightheads use only the shop's meaningful secondary
  // choices. Do not derive this from every catalog color: set-based matching
  // would make a single red/blue SKU look like Red/Red or Red/Blue/Blue.
  const channelSecondaries = ["white", "amber"];
  const skuHas = colors => (product?.skus || []).some(sku =>
    (!lens || (sku.lens_type || "clear") === lens)
    && _eqSet(_skuSet(sku), _headSet(colors))
  );
  return channelSecondaries.filter(color => {
    if (mode === "trio") return skuHas(["red", "blue", color]);
    return skuHas(["red", color]) && skuHas(["blue", color]);
  });
}

function _pickerWestinChannelConfigHtml() {
  const westin = _pickerState.westin || {};
  if (!westin.channel) return "";
  if (westin.loading) return `<div class="pp-westin-channel-setup">Loading the channel's included lights…</div>`;
  if (westin.channelInfo?.noLights) {
    return `<div class="pp-westin-channel-setup">Solid channel selected — no lightheads are included.</div>`;
  }
  if (!westin.channelInfo || !westin.lightProduct) {
    return `<div class="pp-westin-channel-setup">${esc(westin.error || "This light channel needs a supported lighthead configuration before it can be added.")}</div>`;
  }
  const info = westin.channelInfo, product = westin.lightProduct, lights = westin.lights;
  const allLenses = [...new Set((product.skus || []).map(sku => sku.lens_type || "clear"))];
  const availableModes = ["duo", "trio"].filter(mode =>
    allLenses.some(lens => _pickerWestinChannelSecondaryOptions(product, mode, lens).length)
  );
  if (!availableModes.includes(lights.mode)) lights.mode = availableModes[0] || "duo";
  const lenses = allLenses.filter(lens => _pickerWestinChannelSecondaryOptions(product, lights.mode, lens).length);
  if (!lenses.includes(lights.lens)) lights.lens = lenses[0] || "clear";
  const secondaryOptions = _pickerWestinChannelSecondaryOptions(product, lights.mode, lights.lens);
  if (!secondaryOptions.includes(lights.secondary)) lights.secondary = secondaryOptions[0] || "white";
  const secondaryLabel = lights.secondary.charAt(0).toUpperCase() + lights.secondary.slice(1);
  const setupLabel = lights.mode === "trio"
    ? `Uniform trio: every light is Red / Blue / ${secondaryLabel}`
    : `Standard split: driver lights are Red / ${secondaryLabel}; passenger lights are Blue / ${secondaryLabel}`;
  return `<div class="pp-prod-options pp-westin-channel-setup"><div class="pf-group"><span class="pf-label">Included channel lights</span><strong>${esc(info.lightLabel)} · ${info.count}</strong><small>${esc(setupLabel)}</small></div>`
    + `<div class="pf-group"><span class="pf-label">Color setup</span><div class="pf-pills">${availableModes.map(mode => `<button type="button" class="pf-pill${lights.mode === mode ? " active" : ""}" data-westin-light-mode="${mode}">${mode === "duo" ? "Duo · Standard split" : "Trio · Uniform"}</button>`).join("")}</div></div>`
    + `<div class="pf-group"><span class="pf-label">Secondary color</span><div class="pf-pills">${secondaryOptions.map(color => `<button type="button" class="pf-pill${lights.secondary === color ? " active" : ""}" data-westin-light-secondary="${esc(color)}">${esc(color.charAt(0).toUpperCase() + color.slice(1))}</button>`).join("")}</div></div>`
    + `<div class="pf-group"><span class="pf-label">Lens</span><div class="pf-pills">${lenses.map(lens => `<button type="button" class="pf-pill${lights.lens === lens ? " active" : ""}" data-westin-light-lens="${esc(lens)}">${esc(lens.charAt(0).toUpperCase() + lens.slice(1))}</button>`).join("")}</div></div></div>`;
}

async function _pickerSetWestinChannel(value) {
  const westin = _pickerState.westin;
  westin.channel = value;
  westin.channelInfo = _pickerWestinChannelInfo();
  westin.lightProduct = null;
  westin.error = "";
  if (!value) { westin.loading = false; return; }
  if (!westin.channelInfo) {
    westin.loading = false;
    westin.error = "The sales description does not identify a supported light type and quantity.";
    return;
  }
  if (westin.channelInfo.noLights) {
    westin.loading = false;
    return;
  }
  westin.loading = true;
  try {
    if (!westin.lightCatalog) {
      const result = await api("/api/parts-db/category-skus?type=lights&part_type=warning_light");
      westin.lightCatalog = result?.products || [];
    }
    westin.lightProduct = westin.lightCatalog.find(product =>
      product.product_id === westin.channelInfo.lightProductId
    ) || null;
    if (!westin.lightProduct) westin.error = `${westin.channelInfo.lightLabel} is not available in the warning-light catalog.`;
  } catch (error) {
    console.error("Westin channel light load failed:", error);
    westin.error = "Couldn't load the channel's light options.";
  } finally {
    westin.loading = false;
  }
}

function _pickerWestinChannelSatisfied() {
  const westin = _pickerState.westin || {};
  if (!westin.active || !westin.channel) return true;
  if (westin.channelInfo?.noLights) return true;
  return Boolean(westin.channelInfo && westin.lightProduct && !westin.loading && !westin.error);
}

function _pickerWestinOptionProducts(kind) {
  const category = kind === "wire" ? "westin_wire_cover" : "westin_light_channel";
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  const options = (_pickerState.accessories || [])
    .find(group => group.category === category)?.options || [];
  return options.filter(p => {
    const skus = p.skus || [];
    return !vehFiltering || skus.some(s => _skuCompatible(s, veh));
  });
}

function _pickerWestinOptValue(product) {
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  const sku = ((product.skus || []).find(s => !vehFiltering || _skuCompatible(s, veh)) || (product.skus || [])[0] || {}).part_number || "";
  return sku ? `${product.product_id}::${sku}` : "";
}

function _pickerWestinBumperHtml(product) {
  if (!_pickerState.sel || !_pickerIsWestinBasePushBumper(product)) return "";
  const optHtml = (kind, label) => {
    const opts = _pickerWestinOptionProducts(kind)
      .map(p => {
        const value = _pickerWestinOptValue(p);
        if (!value) return "";
        const sku = (p.skus || []).find(s => `${p.product_id}::${s.part_number}` === value) || {};
        const price = sku.price != null ? ` · ${_pickerRetailPrice(sku.price)}` : "";
        return `<option value="${esc(value)}"${_pickerState.westin[kind] === value ? " selected" : ""}>${esc(p.model)} · ${esc(sku.part_number || "")}${price}</option>`;
      })
      .join("");
    return `<div class="pf-group"><span class="pf-label">${esc(label)}</span><select class="pp-westin-select" data-westin="${esc(kind)}">
      <option value="">None</option>${opts}</select></div>`;
  };
  return `<div class="pp-prod-options pp-westin-options">
    ${optHtml("wire", "Wire covers")}
    ${optHtml("channel", "Light channel")}
    ${_pickerWestinChannelConfigHtml()}
  </div>`;
}

function _pickerActivateWestinBumper(product) {
  const active = _pickerIsWestinBasePushBumper(product);
  if (!active) {
    _pickerState.westin = _pickerNewWestinState();
    return;
  }
  if (!_pickerState.westin.active || _pickerState.westin.parentProductId !== product.product_id) {
    _pickerState.westin = {
      ..._pickerNewWestinState(), active: true, parentProductId: product.product_id,
    };
  }
}

// Product-level color defaults are for a fresh selection only. An edited line
// always retains its saved picker_config, even if the catalog's default changes.
function _pickerApplyProductColorDefaults(product) {
  const defaultColors = (product?.default_colors || [])
    .map(color => String(color).toLowerCase())
    .filter(color => _pickerAllowedColors(product).includes(color));
  const c = _pickerState.config;
  const productCategory = _pickerProductCategory(product);
  const isSpecialFlow = productCategory === "scene" || _pickerUsesLocationAllocation(product);
  const preference = (window._PT?.viewProject?.preferences?.lighting_mode === "trio") ? "trio" : "duo";
  const skuColors = (product?.skus || []).map(sku => ({
    sku,
    colors: [sku.color, sku.secondary_color, sku.tertiary_color]
      .filter(Boolean).map(color => String(color).toLowerCase()),
  }));

  if (!isSpecialFlow && preference === "trio") {
    const trio = skuColors
      .filter(item => item.colors.length === 3)
      .sort((a, b) => {
        const rank = item => item.colors.includes("red") && item.colors.includes("blue")
          ? (item.colors.includes("white") ? 0 : 1) : 2;
        return rank(a) - rank(b) || (a.sku.price ?? 9e9) - (b.sku.price ?? 9e9);
      })[0];
    if (trio) {
      c.colorsPerHead = "trio";
      c.mode = "uniform";
      c.uniform = [...trio.colors];
      c.splitSecondary = [];
      c.custom = [];
      c._noColor = false;
      _pickerNormalizeConfig(product);
      return;
    }
  }

  if (!isSpecialFlow && preference === "duo") {
    const duo = skuColors.filter(item => item.colors.length === 2);
    const driver = duo.find(item => item.colors.includes("red") && !item.colors.includes("blue"));
    const passenger = duo.find(item => item.colors.includes("blue") && !item.colors.includes("red"));
    const sharedSecondary = driver?.colors.find(color => color !== "red"
      && passenger?.colors.includes(color));
    if (driver && passenger && sharedSecondary) {
      c.colorsPerHead = "duo";
      c.mode = "split";
      c.uniform = ["red", sharedSecondary];
      c.splitSecondary = [sharedSecondary];
      c.custom = [];
      c._noColor = false;
      if (c.count % 2) c.count = Math.max(2, c.count + 1);
      _pickerNormalizeConfig(product);
      return;
    }
    const uniformDuo = duo[0];
    if (uniformDuo) {
      c.colorsPerHead = "duo";
      c.mode = "uniform";
      c.uniform = [...uniformDuo.colors];
      c.splitSecondary = [];
      c.custom = [];
      c._noColor = false;
      _pickerNormalizeConfig(product);
      return;
    }
  }

  const fallbackColors = defaultColors.length ? defaultColors : (skuColors[0]?.colors || []);
  if (!fallbackColors.length) return;
  c.colorsPerHead = fallbackColors.length === 1 ? "single" : fallbackColors.length === 2 ? "duo" : "trio";
  c.mode = "uniform";
  c.uniform = fallbackColors.slice(0, 3);
  c.splitSecondary = [];
  c.custom = [];
  c._noColor = false;
  _pickerNormalizeConfig(product);
}

function _pickerApplyProductContext(product) {
  if (!product || !_pickerUseGlobalSearch()) return false;
  const f = _pickerState.filters;
  const nextType = product.primary_type_id || f.type_id;
  const nextPt = product.primary_part_type_id || "";
  const changed = f.type_id !== nextType
    || f.category_id !== (product.primary_category_id || "")
    || f.family_id !== (product.primary_family_id || "")
    || f.part_type_id !== nextPt;
  f.type_id = nextType;
  f.type_label = product.primary_type_label || f.type_label || nextType;
  f.category_id = product.primary_category_id || "";
  f.category_label = f.category_id
    ? ((_LIGHT_CATEGORIES.find(x => x.id === f.category_id) || {}).label || f.category_id)
    : "";
  f.family_id = product.primary_family_id || "";
  f.family_label = product.primary_family_label || "";
  f.part_type_id = nextPt;
  f.part_type_label = product.primary_part_type_label || "";
  f.brand = "";
  if (f.type_id) _pickerBrowseExpanded.types.add(f.type_id);
  if (f.family_id) _pickerBrowseExpanded.families.add(f.family_id);
  return changed;
}

const _PICKER_TINT_WINDOWS = [
  ["windshield", "Windshield"],
  ["windshield_brow", "Windshield brow"],
  ["driver_front", "Driver front window"],
  ["passenger_front", "Passenger front window"],
  ["driver_rear", "Driver rear window"],
  ["passenger_rear", "Passenger rear window"],
  ["driver_quarter", "Driver quarter / cargo window"],
  ["passenger_quarter", "Passenger quarter / cargo window"],
  ["rear_window", "Rear window"],
];

function _pickerIsWindowTint(product = null) {
  return (product || _pickerSelectedProduct())?.picker_form === "window_tint";
}

function _pickerTintLabel(id) {
  return _PICKER_TINT_WINDOWS.find(([key]) => key === id)?.[1] || id;
}

function _pickerTintReady() {
  const percentage = Number(_pickerState.tint?.percentage);
  return !_pickerIsWindowTint()
    || (_pickerState.tint.windows.length > 0 && Number.isFinite(percentage) && percentage >= 1 && percentage <= 100);
}

function _pickerTintHtml() {
  const selected = new Set(_pickerState.tint.windows || []);
  const count = selected.size;
  return `<section class="pp-prod-options pp-tint-options"><div class="pp-tint-heading"><div><span class="pf-label">Tint service</span><strong>Choose every window that needs tint</strong></div><span class="pp-tint-price">Retail $65.00 × ${count} = ${_pickerMoney(count * 65)}</span></div>`
    + `<div class="pp-tint-window-grid">${_PICKER_TINT_WINDOWS.map(([id, label]) => `<button type="button" class="pp-tint-window${selected.has(id) ? " is-selected" : ""}" data-tint-window="${id}"><span class="pp-tint-window-mark">${selected.has(id) ? "✓" : "+"}</span><span class="pp-tint-window-label">${esc(label)}</span></button>`).join("")}</div>`
    + `<label class="pp-tint-percent"><span>Tint percentage</span><span><input type="number" data-tint-percentage min="1" max="100" step="1" value="${esc(_pickerState.tint.percentage)}">%</span></label>`
    + `<small>Each selected window is quoted as a $65 tint service line quantity. No vehicle placement is required.</small></section>`;
}

function _pickerUsesLocationAllocation(product = null) {
  return (product || _pickerSelectedProduct())?.picker_location_allocation === true;
}

function _pickerLocationAllocationTotal() {
  return Object.values(_pickerState.locationAllocation?.quantities || {})
    .reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0);
}

function _pickerLocationAllocationReady() {
  return !_pickerUsesLocationAllocation() || _pickerLocationAllocationTotal() > 0;
}

function _pickerLocationAllocationHtml(product) {
  const quantities = _pickerState.locationAllocation.quantities || {};
  const comments = _pickerState.locationAllocation.comments || {};
  const options = product.location_options || [];
  const total = _pickerLocationAllocationTotal();
  return `<section class="pp-prod-options pp-location-allocation"><div class="pp-tint-heading"><div><span class="pf-label">Install locations</span><strong>Split the round lights across the vehicle</strong></div><span class="pp-tint-price">${total} light${total === 1 ? "" : "s"}</span></div>`
    + `<div class="pp-allocation-grid">${options.map(location => {
      const quantity = Math.max(0, Number(quantities[location]) || 0);
      return `<div class="pp-allocation-row"><div><strong>${esc(location)}</strong><small>${quantity ? `${quantity} selected` : "None"}</small><input type="text" data-allocation-comment="${esc(location)}" aria-label="${esc(location)} line notes" placeholder="Notes for this line (optional)" value="${esc(comments[location] || "")}"${quantity ? "" : " disabled"}></div><div class="pp-allocation-stepper"><button type="button" data-allocation-location="${esc(location)}" data-allocation-delta="-1"${quantity ? "" : " disabled"}>−</button><span>${quantity}</span><button type="button" data-allocation-location="${esc(location)}" data-allocation-delta="1"${total >= 12 ? " disabled" : ""}>+</button></div></div>`;
    }).join("")}</div><small>Each selected location becomes its own editable manifest row with its own optional notes; all rows stay linked as one allocation.</small></section>`;
}

function _pickerRoundLightSku(product, color = _pickerState.roundLightColor) {
  const normalized = color === "blue" ? "blue" : "red";
  return (product?.skus || []).find(sku =>
    String(sku.color || "").toLowerCase() === normalized
    && String(sku.secondary_color || "").toLowerCase() === "white"
  ) || null;
}

function _pickerRoundLightHtml(product) {
  const color = _pickerState.roundLightColor === "blue" ? "blue" : "red";
  const chosenSku = _pickerRoundLightSku(product, color);
  return `<div class="pp-round-options">${_pickerLocationAllocationHtml(product)}`
    + `<section class="pp-prod-options pp-round-color"><div><span class="pf-label">Secondary warning color</span><strong>White is included automatically</strong></div>`
    + `<div class="pp-round-color-buttons">${["red", "blue"].map(value => {
      const sku = _pickerRoundLightSku(product, value);
      return `<button type="button" class="pf-pill${color === value ? " active" : ""}" data-round-light-color="${value}"${sku ? "" : " disabled"}>${value === "red" ? "Red" : "Blue"}${sku?.price != null ? ` · ${_pickerRetailPrice(sku.price)}` : ""}</button>`;
    }).join("")}</div>`
    + `<small>${chosenSku ? `${esc(chosenSku.part_number)} · ${esc(color === "red" ? "Red/White" : "Blue/White")}` : "No matching Red/White or Blue/White SKU is available."}</small></section></div>`;
}

function _pickerRenderProducts() {
  const el = $("picker-products");
  if (!el) return;
  if (_pickerState.systemSetup?.active) {
    _pickerRenderSystemSelectionIn(el);
    return;
  }
  if (_pickerState.radio && _pickerState.radio.active) {
    _pickerRenderSystemReviewIn(el);
    return;
  }
  const f = _pickerState.filters;
  const usesColor = _pickerUsesColor();
  const globalSearch = _pickerUseGlobalSearch();
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
  // Recomputed every render (not cached on _pickerState) so it always reflects
  // the current context and, in edit mode, the part's own already-chosen
  // brand rather than silently re-asserting the preference (owner flaw #5 /
  // FINDING-011: auto-select used to run twice here AND in
  // _pickerFetchProducts, lighting-only both times — see there for the
  // single source of truth this reads).
  const brands = [...new Set(_pickerState.products.map(p => p.manufacturer_label).filter(Boolean))].sort();
  const preferredBrand = _pickerPreferredBrand(f);
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  let header = "";
  if (globalSearch) {
    header = `<div class="pp-search-global">Searching all categories and brands${vehFiltering ? ` · ${esc(veh)}-compatible parts only` : ""}</div>`;
  } else if (brands.length > 1) {
    if (preferredBrand) {
      // Preferred brand renders first as its own selected-by-default chip,
      // clearly notated so it's obvious why it's pre-selected; every other
      // brand (+ "All brands") collapses into a compact dropdown that's
      // closed by default.
      const otherBrands = brands.filter(b => b !== preferredBrand);
      const prefActive = f.brand === preferredBrand;
      const selectValue = prefActive ? "__PREF__" : (f.brand || "");
      header = `<div class="pp-brandbar pp-brandbar-pref"><span class="pf-label">Brand</span>` +
        `<button class="pf-pill pp-pref-chip${prefActive ? " active" : ""}" data-brand="${esc(preferredBrand)}">` +
        `${esc(preferredBrand)} <span class="pp-pref-badge">preferred</span></button>` +
        `<select class="pp-brand-more" aria-label="Other brands">` +
        `<option value="__PREF__"${selectValue === "__PREF__" ? " selected" : ""}>Other brands…</option>` +
        `<option value=""${selectValue === "" ? " selected" : ""}>All brands</option>` +
        otherBrands.map(b => `<option value="${esc(b)}"${selectValue === b ? " selected" : ""}>${esc(b)}</option>`).join("") +
        `</select></div>`;
    } else {
      header = `<div class="pp-brandbar"><span class="pf-label">Brand</span>` +
        `<button class="pf-pill${!f.brand ? " active" : ""}" data-brand="">All</button>` +
        brands.map(b => `<button class="pf-pill${f.brand === b ? " active" : ""}" data-brand="${esc(b)}">${esc(b)}</button>`).join("") + `</div>`;
    }
  }
  if (!globalSearch && veh) {
    header += `<label class="pp-vehtoggle"><input type="checkbox" id="pp-veh-only"${_pickerState.vehicleOnly ? " checked" : ""}>`
      + `<span>Only show ${esc(veh)}-compatible parts</span></label>`;
  }
  let list = _pickerState.products;
  if (!globalSearch && f.brand) list = list.filter(p => p.manufacturer_label === f.brand);
  if (q) list = list.filter(p => {
    const productText = [
      p.search_text,
      p.model,
      p.manufacturer_label,
      p.description,
      ...(p.skus || []).flatMap(s => [s.part_number, s.friendly_name, ...(s.vehicle_tags || [])]),
    ].filter(Boolean).join(" ").toLowerCase();
    return productText.includes(q);
  });
  // Vehicle-compat: drop products with no SKU that fits the selected vehicle.
  if (vehFiltering) list = list.filter(p => p.skus.some(s => _skuCompatible(s, veh)));
  // Interior-light choices are intentionally restricted to red, blue, and
  // white. Keep unsupported colors out even when the user removes the other
  // option filters, so an amber warning-light SKU cannot slip into this flow.
  if (f.category_id === "interior") {
    list = list.filter(p => p.skus.some(s => _pickerSkuAllowedForCurrentFlow(s, p)));
  }
  // Step 2: grid is no longer pre-sorted by color match — options live in the
  // product box and are configured per-product after selection, not before.
  list = [...list].sort((a, b) => {
    return a.model.localeCompare(b.model);
  });

  if (!list.length) { el.innerHTML = header + `<div style="color:var(--muted);text-align:center;padding:40px">No products match these filters.</div>`; _pickerWireBrand(el); return; }
  if (!q && list.length === 1) _pickerState.expanded.add(list[0].product_id);

  el.innerHTML = header + list.map(p => {
    const open = _pickerState.expanded.has(p.product_id);
    const selected = _pickerState.sel && _pickerState.sel.product_id === p.product_id;
    // SKUs shown for this product, narrowed to the selected vehicle when filtering.
    let skus = (vehFiltering ? p.skus.filter(s => _skuCompatible(s, veh)) : p.skus)
      .filter(s => _pickerSkuAllowedForCurrentFlow(s, p));
    if (vehFiltering) skus = _pickerHowlerVehicleSkus(p, skus, veh);
    if (_pickerUsesLocationAllocation(p)) {
      skus = skus.filter(s => ["red", "blue"].includes(String(s.color || "").toLowerCase())
        && String(s.secondary_color || "").toLowerCase() === "white");
    }
    const prices = skus.map(s => s.price).filter(v => v != null);
    const priceStr = prices.length ? `from ${_pickerRetailPrice(Math.min(...prices))}` : "";
    const qb = skus.some(s => s.qb) ? `<span class="pp-match ok">QB</span>` : "";
    // Programmable bars (WeCanX) carry no per-SKU colors → fall back to direct
    // SKU selection even inside a color category, so they stay pickable.
    const productCategory = _pickerProductCategory(p);
    const productUsesColor = _pickerUsesColor(p);
    const pColor = productUsesColor && _pickerProductHasColor(p);

    // Body: color products show options + per-combo SKU dropdown; else → SKU pick list.
    // Step 5: scene products (even no-color ones) also select on head-click and render
    // the qty+SKU box, so they share the selectsOnClick gate with color products.
    const selectsOnClick = pColor || (productUsesColor && productCategory === "scene");
    let bodyHtml = "";
    if (open) {
      if (selectsOnClick && selected) {
        if (_pickerUsesLocationAllocation(p)) {
          bodyHtml = _pickerRoundLightHtml(p);
        // Step 5: branch on scene (category == "scene" covers all scene_lights family
        // members — front_scene/rear_scene/side_scene/spotlight share picker_flow "scene").
        } else if (productCategory === "scene") {
          // Scene box: qty control only (no mode/lens/color/cph/remove-options) +
          // per-head SKU dropdowns (all SKUs, unfiltered) + plain uncolored viz.
          bodyHtml = `<div class="pp-prod-options">${_pickerColorConfigHtml(p)}</div>`;
          const sceneCount = _pickerState.config.count;
          const sceneSorted = [...skus].sort((a, b) => (a.price ?? 9e9) - (b.price ?? 9e9));
          bodyHtml += `<div class="pp-skus">` + Array.from({ length: sceneCount }, (_, h) => {
            const headKey = "head_" + h;
            const chosen = _pickerState.skuChoices[headKey] || (sceneSorted[0] && sceneSorted[0].part_number) || "";
            const headTitle = `Head ${h + 1}: ${chosen || "—"}`;
            const opts = sceneSorted.map(s => `<option value="${esc(s.part_number)}"${s.part_number === chosen ? " selected" : ""}>${esc(s.part_number)}${s.price != null ? " · " + _pickerRetailPrice(s.price) : ""}</option>`).join("");
            return `<div class="pp-sku"><span class="pp-sku-pn">${esc(headTitle)}</span><select class="pp-override" data-head="${h}">${opts}</select></div>`;
          }).join("") + `</div>`;
          // Plain uncolored heads — scene heads carry no color, just quantity.
          const plainHead = `<span class="picker-foot-head" title="Scene head"><span style="background:#888;border:1px solid rgba(0,0,0,.18)"></span></span>`;
          bodyHtml += `<div class="pp-viz"><span class="pp-viz-label">Preview</span><span class="picker-foot-heads">${Array(sceneCount).fill(plainHead).join("")}</span></div>`;
        } else {
          // Non-scene: full option set (Steps 2/3/4 — mode/lens/color/cph + filtered
          // per-head dropdowns + colored viz, unchanged).
          // Step 2: option controls (mode/lens/color/cph/qty) in the product box,
          // above the SKU dropdown.  _pickerWireProductOptions wires them after render.
          bodyHtml = `<div class="pp-prod-options">${_pickerColorConfigHtml(p)}</div>`;
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
              return `<option value="${esc(s.part_number)}"${s.part_number === chosen ? " selected" : ""}>${esc(s.part_number)}${cs ? " · " + esc(cs) : ""}${s.lens_type ? " · " + esc(s.lens_type) : ""}${s.price != null ? " · " + _pickerRetailPrice(s.price) : ""}</option>`;
            }).join("");
            return `<div class="pp-sku"><span class="pp-sku-pn">${esc(headTitle)}</span><select class="pp-override" data-head="${h}">${opts}</select>${(!hasMatch && !optRemoved) ? `<span class="pp-match no">no exact</span>` : ""}</div>`;
          }).join("") + `</div>`;
          // Step 4: light visualization below SKU dropdowns in the selected product box.
          bodyHtml += `<div class="pp-viz"><span class="pp-viz-label">Preview</span>${_pickerHeadsPreviewHtml()}</div>`;
        }
      } else {
        if (selected && _pickerIsSirenSpeakerContext()) bodyHtml += _pickerSirenQtyHtml();
        if (selected) bodyHtml += _pickerWestinBumperHtml(p);
        if (selected && _pickerIsWindowTint(p)) bodyHtml += _pickerTintHtml();
        bodyHtml += `<div class="pp-skus">` + skus.map(s => {
          const matched = pColor ? _skuMatchesAny(s, headSets) : true;
          const cls = pColor ? (matched ? "match" : "nomatch") : "";
          // Friendly name leads the description (clarifies non-light parts); falls
          // back to color/lens, which is description enough for lightheads.
          const colorBits = [s.color, s.secondary_color, s.tertiary_color].filter(Boolean).map(x => x[0].toUpperCase() + x.slice(1)).join("/");
          const desc = [s.friendly_name, colorBits].filter(Boolean).join(" · ") || "—";
          const pr = s.price != null ? _pickerRetailPrice(s.price) : "";
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
        <span class="pp-brandchip">${esc(p.manufacturer_label)}</span>
        <span class="pp-name">${esc(p.model)}</span>
        <span class="pp-meta">${skus.length} SKU${skus.length !== 1 ? "s" : ""}${priceStr ? " · " + priceStr : ""}</span>
        ${qb}
      </div>${bodyHtml}
    </div>`;
  }).join("");

  _pickerWireBrand(el);
  _pickerWireProductOptions(el);
  el.querySelectorAll(".pp-westin-select").forEach(sel => sel.addEventListener("change", async () => {
    const k = sel.dataset.westin;
    if (k === "channel") await _pickerSetWestinChannel(sel.value);
    else if (k) _pickerState.westin[k] = sel.value;
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-westin-light-mode]").forEach(button => button.addEventListener("click", () => {
    _pickerState.westin.lights.mode = button.dataset.westinLightMode;
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-westin-light-secondary]").forEach(button => button.addEventListener("click", () => {
    _pickerState.westin.lights.secondary = button.dataset.westinLightSecondary;
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-westin-light-lens]").forEach(button => button.addEventListener("click", () => {
    _pickerState.westin.lights.lens = button.dataset.westinLightLens;
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-siren-qty]").forEach(btn => btn.addEventListener("click", () => {
    _pickerState.config.count = Math.min(2, Math.max(1, parseInt(btn.dataset.sirenQty || "1", 10)));
    if (_pickerState.config.count !== 2) _pickerState.sirenDualTones = false;
    _pickerPlaceDots();
    _pickerRenderProducts();
    _pickerRenderAccessories();
    _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-siren-dual-tone]").forEach(btn => btn.addEventListener("click", () => {
    _pickerState.sirenDualTones = btn.dataset.sirenDualTone === "yes";
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-tint-window]").forEach(button => button.addEventListener("click", () => {
    const id = button.dataset.tintWindow;
    const windows = _pickerState.tint.windows || [];
    const index = windows.indexOf(id);
    if (index >= 0) windows.splice(index, 1);
    else windows.push(id);
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-allocation-location]").forEach(button => button.addEventListener("click", () => {
    const location = button.dataset.allocationLocation;
    const delta = Number(button.dataset.allocationDelta) || 0;
    const quantities = _pickerState.locationAllocation.quantities;
    quantities[location] = Math.min(12, Math.max(0, (Number(quantities[location]) || 0) + delta));
    if (!quantities[location]) delete quantities[location];
    _pickerState.config.count = Math.max(1, _pickerLocationAllocationTotal());
    _pickerNormalizeConfig(_pickerSelectedProduct());
    _pickerState.skuChoices = {};
    _pickerRenderProducts(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-allocation-comment]").forEach(input => input.addEventListener("input", () => {
    const location = input.dataset.allocationComment;
    _pickerState.locationAllocation.comments[location] = input.value;
  }));
  el.querySelectorAll("[data-round-light-color]").forEach(button => button.addEventListener("click", () => {
    _pickerState.roundLightColor = button.dataset.roundLightColor === "blue" ? "blue" : "red";
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
  el.querySelector("[data-tint-percentage]")?.addEventListener("input", event => {
    _pickerState.tint.percentage = Math.min(100, Math.max(1, Number(event.target.value) || 0));
    _pickerUpdateFooter();
  });
  const vt = el.querySelector("#pp-veh-only");
  if (vt) vt.addEventListener("change", () => {
    _pickerState.vehicleOnly = vt.checked;
    try { localStorage.setItem("pp_vehicle_only", vt.checked ? "1" : "0"); } catch {}
    _pickerRenderProducts();
    _pickerRenderAccessories();
  });
  el.querySelectorAll(".pp-head").forEach(h => h.addEventListener("click", () => {
    const pid = h.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    const contextChanged = _pickerApplyProductContext(p);
    const wasOpen = _pickerState.expanded.has(pid);
    // Single-expansion: opening a product collapses any other expanded one, so a
    // previously-selected product can't linger with a stale SKU list.
    if (wasOpen && (!_pickerUsesColor(p) || (_pickerState.sel && _pickerState.sel.product_id === pid))) _pickerState.expanded.delete(pid);
    else _pickerState.expanded = new Set([pid]);
    // Color products select on head-click; no-color (programmable) products
    // select via the per-SKU "Select" pill instead.
    // Step 5: scene products select on head-click even when SKUs carry no color
    // (e.g. Unity spotlights) — they use the qty+SKU-dropdown path, not a pill.
    const nowUsesColor = _pickerUsesColor(p);
    const pColor = nowUsesColor && _pickerProductHasColor(p);
    const selectsOnClick = pColor || (nowUsesColor && _pickerProductCategory(p) === "scene");
    const selectingNewProduct = selectsOnClick && (!_pickerState.sel || _pickerState.sel.product_id !== pid);
    if (selectingNewProduct) {
      _pickerResetLocation();
      _pickerApplyProductColorDefaults(p);
    }
    if (selectsOnClick) {
      _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label }; _pickerState.skuChoices = {}; _pickerState.optionsRemoved = false;
      _pickerActivateWestinBumper(p);
    }
    if (contextChanged) _pickerRenderFilters();
    _pickerRenderProducts(); _pickerUpdateFooter();
    if (selectsOnClick) { _pickerLoadAccessories(pid); _pickerLoadTracer(pid); _pickerLoadInnerEdge(pid); _pickerLoadOuterEdge(pid); _pickerLoadLightbar(pid); _pickerLoadFixture(pid); _pickerApplyFixedPartLocation(); }
  }));
  el.querySelectorAll("[data-pick]").forEach(btn => btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const pid = btn.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    const contextChanged = _pickerApplyProductContext(p);
    if (!_pickerState.sel || _pickerState.sel.product_id !== pid) _pickerResetLocation();
    _pickerState.expanded = new Set([pid]);   // keep only this product expanded
    const nowUsesColor = _pickerUsesColor(p);
    if (nowUsesColor && _pickerProductHasColor(p)) {
      _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label };
      _pickerState.skuChoices = {};
      _pickerState.optionsRemoved = false;
    } else {
      _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label, sku: btn.dataset.pick };
    }
    _pickerActivateWestinBumper(p);
    if (contextChanged) _pickerRenderFilters();
    _pickerRenderProducts(); _pickerUpdateFooter();
    _pickerLoadAccessories(pid);
    _pickerLoadTracer(pid);
    _pickerLoadInnerEdge(pid);
    _pickerLoadOuterEdge(pid);
    _pickerLoadLightbar(pid);
    _pickerLoadFixture(pid);
    _pickerApplyFixedPartLocation();
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
  // Collapsed "other brands" dropdown (rendered instead of a full pill row
  // when a preferred brand exists — see _pickerRenderProducts). "__PREF__"
  // is the closed/placeholder state: it means "back to the preferred chip",
  // not a real brand value.
  const moreSel = el.querySelector(".pp-brand-more");
  if (moreSel) moreSel.addEventListener("change", () => {
    const v = moreSel.value;
    _pickerState.filters.brand = v === "__PREF__" ? _pickerPreferredBrand(_pickerState.filters) : v;
    _pickerRenderProducts();
  });
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
    // Qty changes leave the filter state alone; all other option changes re-apply it (Step 3).
    if (k !== "count") _pickerState.optionsRemoved = false;
    if (k === "lens") { f.lens = v; _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerRenderAccessories(); _pickerUpdateFooter(); return; }
    if (k === "cph") { c.colorsPerHead = v; _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
    if (k === "mode") { c.mode = v; _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
  }));
  opts.querySelectorAll(".picker-swatch").forEach(b => b.addEventListener("click", () => {
    if (b.disabled) return;
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

async function _pickerLoadLocationChoices() {
  const f = _pickerState.filters;
  const loc = _pickerState.loc;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  try {
    const pid = _pickerState.sel ? _pickerState.sel.product_id : "";
    const product = _pickerSelectedProduct();
    const typeId = _pickerProductType(product) || f.type_id;
    const categoryId = _pickerProductCategory(product);
    const res = await api(`/api/parts-db/category-locations?type=${encodeURIComponent(typeId)}&category=${encodeURIComponent(categoryId)}&product=${encodeURIComponent(pid)}&vehicle=${encodeURIComponent(loc.vehicle)}`);
    loc.locByName = {};
    for (const entry of (res?.locations || [])) loc.locByName[entry.location.toUpperCase()] = entry;
  } catch (e) { console.error("Picker: category-locations failed:", e); loc.locByName = {}; }
}

function _pickerSetStandardLocation(location, entry = {}, autoLocation = "") {
  const loc = _pickerState.loc;
  loc.selected = location;
  loc.textCustom = false;
  loc.renderLocation = "";
  loc.customStage = "";
  loc.customPlacementMode = "vehicle";
  loc.customPlacementLayout = "even";
  loc.customPlacements = {};
  loc.customPlacementAnchors = {};
  loc.autoLocation = autoLocation;
  loc.name_pattern = entry.name_pattern || "";
  loc.base_label = entry.base_label || "";
  loc.catalog_names = entry.catalog_names || [];
}

function _pickerLocationAllowsCustom() {
  const loc = _pickerState.loc;
  const product = _pickerSelectedProduct();
  return !_pickerSelIsFixture()
    && !_pickerHasFixedPartLocation()
    // Some single-location products, such as the hand-held CCTL5, also need
    // a shop-specific placement alongside their default console location.
    && (product?.allow_custom_location === true
    // A single curated location is already the right shop instruction, so
    // don't make the user name another version of it.  Zero locations still
    // need the custom path; it is the only way to record a sensible install
    // reference for those parts.
    || Object.keys(loc.locByName || {}).length !== 1);
}

function _pickerLocationOffersVehiclePlacement() {
  return _pickerProductType() === "lights"
    || Object.values(_pickerState.loc.locByName || {}).some(entry => entry.has_coords === true);
}

function _pickerNormalizeCustomPlacements(raw) {
  const out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [view, points] of Object.entries(raw)) {
    if (!Array.isArray(points)) continue;
    const clean = points.filter(point => {
      const x = Number(point?.x), y = Number(point?.y);
      return Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1;
    }).map((point, fallbackIndex) => {
      const clean = { x: Number(point.x), y: Number(point.y) };
      const headIndex = Number(point.head_index);
      clean.head_index = Number.isInteger(headIndex) && headIndex >= 0 ? headIndex : fallbackIndex;
      if (typeof point.group_id === "string" && point.group_id.trim()) clean.group_id = point.group_id.trim().slice(0, 40);
      return clean;
    });
    if (clean.length) out[String(view).toLowerCase()] = clean;
  }
  return out;
}

function _pickerNormalizeCustomAnchors(raw) {
  const out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [view, point] of Object.entries(raw)) {
    const x = Number(point?.x), y = Number(point?.y);
    if (Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1) {
      out[String(view).toLowerCase()] = { x, y };
    }
  }
  return out;
}

function _pickerNormalizeCustomSpacing(value) {
  const spacing = Number(value);
  return Number.isFinite(spacing) ? Math.min(0.2, Math.max(0.01, spacing)) : 0.06;
}

function _pickerCustomPlacementHeadCount() {
  const product = _pickerSelectedProduct();
  const category = _pickerProductCategory(product);
  const quantityDriven = _pickerUsesColor(product)
    && (_pickerProductHasColor(product) || category === "scene");
  return quantityDriven ? Math.min(12, Math.max(1, Number(_pickerState.config.count) || 1)) : 1;
}

function _pickerCustomSpacingMax(count = _pickerCustomPlacementHeadCount()) {
  return count > 1 ? Math.min(0.2, 0.9 / (count - 1)) : 0.2;
}

function _pickerCustomGroupPoints(anchor, count = _pickerCustomPlacementHeadCount(), spacing = _pickerState.loc.customHeadSpacing) {
  const safeCount = Math.min(12, Math.max(1, Number(count) || 1));
  const safeSpacing = Math.min(_pickerCustomSpacingMax(safeCount), _pickerNormalizeCustomSpacing(spacing));
  const halfWidth = safeSpacing * (safeCount - 1) / 2;
  const centerX = Math.min(1 - halfWidth, Math.max(halfWidth, Number(anchor?.x) || 0));
  const centerY = Math.min(1, Math.max(0, Number(anchor?.y) || 0));
  return Array.from({ length: safeCount }, (_, index) => ({
    x: centerX + (index - (safeCount - 1) / 2) * safeSpacing,
    y: centerY,
    head_index: index,
    group_id: "row",
  }));
}

function _pickerCustomMirroredPairPoints(anchor, spacing = _pickerState.loc.customHeadSpacing) {
  const pairSpacing = Math.min(0.2, _pickerNormalizeCustomSpacing(spacing));
  const halfPair = pairSpacing / 2;
  const requestedOffset = Math.abs((Number(anchor?.x) || 0.72) - 0.5);
  const pairOffset = Math.min(0.45 - halfPair, Math.max(halfPair + 0.025, requestedOffset));
  const y = Math.min(1, Math.max(0, Number(anchor?.y) || 0));
  const leftCenter = 0.5 - pairOffset;
  const rightCenter = 0.5 + pairOffset;
  return [
    { x: leftCenter - halfPair, y, head_index: 0, group_id: "left_pair" },
    { x: leftCenter + halfPair, y, head_index: 1, group_id: "left_pair" },
    { x: rightCenter - halfPair, y, head_index: 2, group_id: "right_pair" },
    { x: rightCenter + halfPair, y, head_index: 3, group_id: "right_pair" },
  ];
}

function _pickerSetCustomPlacementGroup(view, anchor) {
  const loc = _pickerState.loc;
  const key = String(view || "").toLowerCase();
  if (!key) return;
  loc.customHeadSpacing = Math.min(_pickerCustomSpacingMax(), _pickerNormalizeCustomSpacing(loc.customHeadSpacing));
  const pairMode = loc.customPlacementLayout === "mirrored_pairs" && _pickerCustomPlacementHeadCount() === 4;
  const points = pairMode ? _pickerCustomMirroredPairPoints(anchor) : _pickerCustomGroupPoints(anchor);
  const center = points.reduce((memo, point) => ({ x: memo.x + point.x, y: memo.y + point.y }), { x: 0, y: 0 });
  // In pair mode the click identifies one pair's distance from center. The
  // rendered four-head group is necessarily centered at 0.5, so saving its
  // arithmetic center would discard that distance on the next redraw.
  loc.customPlacementAnchors[key] = pairMode
    ? {
        x: Math.min(1, Math.max(0, Number(anchor?.x) || 0.72)),
        y: Math.min(1, Math.max(0, Number(anchor?.y) || 0)),
      }
    : { x: center.x / points.length, y: center.y / points.length };
  loc.customPlacements[key] = points;
}

function _pickerEnsureCustomPlacementAnchor(view) {
  const loc = _pickerState.loc;
  const key = String(view || "").toLowerCase();
  if (loc.customPlacementAnchors?.[key]) return loc.customPlacementAnchors[key];
  const points = loc.customPlacements?.[key] || [];
  if (!points.length) return null;
  if (loc.customPlacementLayout === "mirrored_pairs" && points.length === 4) {
    const oneSide = points.filter(point => point.group_id === "right_pair" || Number(point.x) > 0.5);
    if (oneSide.length) {
      const sideSum = oneSide.reduce((memo, point) => ({ x: memo.x + point.x, y: memo.y + point.y }), { x: 0, y: 0 });
      const anchor = { x: sideSum.x / oneSide.length, y: sideSum.y / oneSide.length };
      loc.customPlacementAnchors[key] = anchor;
      return anchor;
    }
  }
  const sum = points.reduce((memo, point) => ({ x: memo.x + point.x, y: memo.y + point.y }), { x: 0, y: 0 });
  const anchor = { x: sum.x / points.length, y: sum.y / points.length };
  loc.customPlacementAnchors[key] = anchor;
  return anchor;
}

function _pickerRefreshCustomPlacementGroups() {
  const loc = _pickerState.loc;
  for (const [view, anchor] of Object.entries(loc.customPlacementAnchors || {})) {
    _pickerSetCustomPlacementGroup(view, anchor);
  }
}

function _pickerCustomPlacementCount() {
  return Object.values(_pickerState.loc.customPlacements || {}).reduce((count, points) => count + points.length, 0);
}

function _pickerCustomPlacementSnapshot() {
  return _pickerNormalizeCustomPlacements(_pickerState.loc.customPlacements);
}

function _pickerCustomLocationReady() {
  const loc = _pickerState.loc;
  return !loc.textCustom || Boolean(String(loc.selected || "").trim());
}

function _pickerStartCustomLocation() {
  const loc = _pickerState.loc;
  if (!_pickerLocationAllowsCustom()) return;
  if (!loc.textCustom) loc.selected = "";
  loc.textCustom = true;
  loc.renderLocation = "";
  loc.customStage = "name";
  loc.customPlacementMode = "vehicle";
  loc.customPlacementLayout = "even";
  loc.customPlacements = {};
  loc.customPlacementAnchors = {};
  loc.customHeadSpacing = 0.06;
  loc.autoLocation = "";
  loc.name_pattern = "";
  loc.base_label = "";
  loc.catalog_names = [];
  _pickerDrawLocation();
}

function _pickerSetCustomLocationName(value) {
  const loc = _pickerState.loc;
  loc.selected = String(value || "").trim();
  loc.textCustom = true;
  loc.autoLocation = "";
  // A custom location can be manifest-only.  Give it the ordinary part-type
  // name until an optional vehicle dot supplies a more specific label.
  const ptLabel = _pickerFreeTextPartTypeLabel(_pickerState.filters);
  const single = _pickerFreeTextPartTypeMax(_pickerState.filters) === 1;
  loc.name_pattern = ptLabel ? (single ? ptLabel : `${ptLabel} {n}`) : "";
  loc.base_label = ptLabel;
  loc.catalog_names = [];
}

function _pickerApplySingleLocation() {
  const loc = _pickerState.loc;
  const entries = Object.values(loc.locByName || {});
  if (_pickerState.editLineId || loc.selected || entries.length !== 1) return;
  _pickerSetStandardLocation(entries[0].location, entries[0], "single_location");
}

function _pickerHasLicensePlateBracket() {
  if (_pickerState.filters.type_id !== "lights") return false;
  const isLicensePlateBracket = text => /license[\s-]*plate/i.test(text || "");
  for (const group of _pickerVisibleAccessoryGroups()) {
    if (group.category !== "bracket_mount") continue;
    const saved = _pickerState.accessoryChoices[group.category];
    const picks = Array.isArray(saved) ? saved : [saved];
    for (const pick of picks) {
      if (!pick || pick === "none") continue;
      const [productId, partNumber] = pick.split("::");
      const option = (group.options || []).find(item => item.product_id === productId);
      const sku = (option?.skus || []).find(item => item.part_number === partNumber);
      const label = [option?.product_id, option?.model, sku?.friendly_name, sku?.part_number].filter(Boolean).join(" ");
      if (isLicensePlateBracket(label) || partNumber === "IONBKT1") return true;
    }
  }
  return false;
}

// License-plate brackets have one physical mounting point.  Treating that
// point as a normal picker question led to incompatible drawings, so choosing
// the accessory deliberately owns both the saved location and diagram dot.
async function _pickerApplyLicensePlateLocation({ force = false } = {}) {
  const loc = _pickerState.loc;
  if (!_pickerHasLicensePlateBracket()) {
    if (loc.autoLocation === "license_plate") _pickerResetLocation();
    return false;
  }
  if (!Object.keys(loc.locByName || {}).length) await _pickerLoadLocationChoices();
  const entry = loc.locByName["LICENSE PLATE BRACKET"];
  if (!entry) return false;
  // A saved legacy part may carry this bracket while intentionally retaining a
  // different shop-facing location. Restoring it for edit must be lossless;
  // only a new accessory choice is allowed to move the part automatically.
  if (_pickerState.editLineId && loc.selected && loc.selected !== entry.location && !force) return false;
  _pickerSetStandardLocation(entry.location, entry, "license_plate");
  return true;
}

async function _pickerRenderLocation() {
  const loc = _pickerState.loc;
  loc.vehicle = (typeof _meDraft !== "undefined" && _meDraft?.vehicle_info?.VehicleType) || "PIU";
  if (!loc.layouts) {
    try { loc.layouts = await api("/api/layouts"); } catch (e) { console.error("Picker: layouts failed:", e); loc.layouts = {}; }
  }
  await _pickerEnsurePartTypeMeta();
  await _pickerLoadLocationChoices();
  _pickerApplySingleLocation();
  await _pickerApplyLicensePlateLocation();
  _pickerDrawLocation();
}

function _pickerControlHeadRequiresPaMic() {
  return _pickerResolvedPartTypeId(_pickerState.filters) === "control_head"
    && _pickerSelectedProduct()?.pa_mic_required !== false;
}

function _pickerIsSecondaryWhelenControlHead() {
  if (_pickerResolvedPartTypeId(_pickerState.filters) !== "control_head") return false;
  const product = _pickerSelectedProduct();
  if (String(product?.manufacturer_id || "").toLowerCase() !== "whelen") return false;
  const parts = (typeof _meDraft !== "undefined" && _meDraft?.parts) || [];
  const count = parts.filter(part => !part.parent_line_id && part.part_type === "control_head").length;
  return _pickerState.editLineId ? count >= 2 : count >= 1;
}

function _pickerControlHeadOffersHandheldMagMic() {
  return _pickerResolvedPartTypeId(_pickerState.filters) === "control_head"
    && (_pickerSelectedProduct()?.handheld_mag_mic_prompt === true
      || _pickerIsSecondaryWhelenControlHead());
}

function _pickerPartDetailsSatisfied() {
  if (_pickerControlHeadOffersHandheldMagMic()) {
    return typeof (_pickerState.partDetails || {}).handheldMagMic === "boolean";
  }
  if (!_pickerControlHeadRequiresPaMic()) return true;
  const details = _pickerState.partDetails || {};
  const hasLocation = details.paMicLocation === "drivers_door"
    || (details.paMicLocation === "__custom__" && Boolean(String(details.paMicLocationCustom || "").trim()));
  return hasLocation && ["magnetic_mic", "manufacturer_clip"].includes(details.paMicClip);
}

function _pickerPaMicLocation() {
  const details = _pickerState.partDetails || {};
  if (details.paMicLocation === "drivers_door") return "Driver's door";
  if (details.paMicLocation === "__custom__") return String(details.paMicLocationCustom || "").trim();
  return "";
}

function _pickerPaMicClip() {
  const clip = (_pickerState.partDetails || {}).paMicClip;
  return {
    magnetic_mic: "Magnetic mic",
    manufacturer_clip: "Manufacturer clip",
  }[clip] || "";
}

function _pickerPartDetailsNote() {
  if (!_pickerControlHeadRequiresPaMic()) return "";
  const location = _pickerPaMicLocation();
  const clip = _pickerPaMicClip();
  return location && clip ? `PA mic: ${location} · ${clip}` : "";
}

// Components are display-only manifest rows carried by the parent line. This
// makes the PA-mic placement visible to the shop without creating a second
// billable or renderable part in the build plan.
function _pickerPartDetailsComponent() {
  if (!_pickerControlHeadRequiresPaMic()) return null;
  const location = _pickerPaMicLocation();
  const clip = _pickerPaMicClip();
  return location && clip ? { label: "PA Mic", location, detail: clip } : null;
}

// Magnetic Mic products are QB-linked parts. A guided choice must therefore
// create a real child line, not only leave a shop-install note on its parent.
const _MAGNETIC_MIC_ITEMS = {
  magnetic_mic: { part_number: "MMSU-1", model: "Mag Mic", manufacturer: "Magnetic Mic" },
  magnetic_no_bracket: { part_number: "MMSU-1", model: "Mag Mic", manufacturer: "Magnetic Mic" },
  magnetic_with_bracket: { part_number: "MMSU-1B", model: "Mag Mic with Bracket", manufacturer: "Magnetic Mic" },
};

function _pickerMagneticMicRow(parentLineId, parentName, location, selection, supplyRecord = { new_or_used: "New" }) {
  const item = _MAGNETIC_MIC_ITEMS[selection];
  if (!item || !parentLineId) return null;
  const record = typeof supplyRecord === "string" ? { new_or_used: supplyRecord } : (supplyRecord || {});
  return {
    name: `${parentName} · ${item.model}`,
    location: location || "", manufacturer: item.manufacturer, part_number: item.part_number,
    quantity: 1, ..._pickerSupplyPayload(_pickerSupplyFromRecord(record)), parent_line_id: parentLineId,
    accessory_category: "magnetic_mic", accessory_parent_product: "", part_type: "radio_mic_clip",
  };
}

async function _pickerReplaceMagneticMicChild(draftId, parentLineId, parentName, location, selection, supplyRecord = { new_or_used: "New" }) {
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId && part.accessory_category === "magnetic_mic"
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace the magnetic mic line");
  }
  const row = _pickerMagneticMicRow(parentLineId, parentName, location, selection, supplyRecord);
  if (!row) return;
  const result = await api(`/api/draft/${draftId}/part`, row);
  if (!result?.ok) throw new Error(result?.error || "could not add the magnetic mic line");
}

function _pickerRenderPartDetails() {
  const panel = $("picker-part-details");
  if (!panel) return;
  // A manifest subgroup opens the whole Light Control System family. In that
  // path the filter has no leaf yet, so derive the concrete type from the
  // selected product just as resolve/add does. Edit mode already has a leaf.
  if (_pickerControlHeadOffersHandheldMagMic()) {
    const details = _pickerState.partDetails || {};
    const secondary = _pickerIsSecondaryWhelenControlHead();
    panel.hidden = false;
    panel.innerHTML = `<section class="picker-location-chooser picker-part-details"><div class="picker-location-kicker">${secondary ? "Secondary Whelen control head" : "Hand-held control head"}</div>`
      + `<h3>Add a Mag Mic?</h3><p>${secondary ? "Choose whether this second control head needs its own" : "The hand-held control head does not need a separate bracket accessory. Choosing Yes adds one"} MMSU-1 Mag Mic.</p>`
      + `<div class="picker-location-grid picker-detail-choice-grid">`
      + `<button type="button" class="picker-location-card${details.handheldMagMic === true ? " is-selected" : ""}" data-handheld-mag-mic="true" aria-pressed="${details.handheldMagMic === true ? "true" : "false"}"><span class="picker-location-card-check">${details.handheldMagMic === true ? "✓" : ""}</span><span>Yes, add Mag Mic</span></button>`
      + `<button type="button" class="picker-location-card${details.handheldMagMic === false ? " is-selected" : ""}" data-handheld-mag-mic="false" aria-pressed="${details.handheldMagMic === false ? "true" : "false"}"><span class="picker-location-card-check">${details.handheldMagMic === false ? "✓" : ""}</span><span>No Mag Mic</span></button></div></section>`;
    panel.querySelectorAll("[data-handheld-mag-mic]").forEach(button => button.addEventListener("click", () => {
      _pickerState.partDetails.handheldMagMic = button.dataset.handheldMagMic === "true";
      _pickerRenderPartDetails();
      _pickerUpdateFooter();
    }));
    return;
  }
  if (!_pickerControlHeadRequiresPaMic()) {
    panel.hidden = true; panel.innerHTML = "";
    return;
  }
  const details = _pickerState.partDetails || {};
  const custom = details.paMicLocation === "__custom__";
  panel.hidden = false;
  panel.innerHTML = `<section class="picker-location-chooser picker-part-details"><div class="picker-location-kicker">PA microphone setup</div>`
    + `<h3>How will the PA microphone be installed?</h3><p>Choose the microphone location and clip type for the shop.</p>`
    + `<div class="picker-detail-section"><div class="picker-detail-label">PA microphone location</div><div class="picker-location-grid picker-detail-choice-grid">`
    + `<button type="button" class="picker-location-card${details.paMicLocation === "drivers_door" ? " is-selected" : ""}" data-pa-mic-location="drivers_door" aria-pressed="${details.paMicLocation === "drivers_door" ? "true" : "false"}"><span class="picker-location-card-check">${details.paMicLocation === "drivers_door" ? "✓" : ""}</span><span>Driver's door</span></button>`
    + `<button type="button" class="picker-location-card picker-location-card--custom${custom ? " is-selected" : ""}" data-pa-mic-location="__custom__" aria-pressed="${custom ? "true" : "false"}"><span class="picker-location-card-check">${custom ? "✓" : ""}</span><span>Custom location<small>Enter a specific shop reference</small></span></button></div>`
    + (custom ? `<label class="picker-location-custom-field"><span>Custom PA microphone location</span><input id="picker-pa-mic-custom" class="picker-location-custom-input" placeholder="Enter the PA microphone location" value="${esc(details.paMicLocationCustom || "")}"></label>` : "")
    + `</div><div class="picker-detail-section"><div class="picker-detail-label">PA microphone clip</div><div class="picker-location-grid picker-detail-choice-grid">`
    + `<button type="button" class="picker-location-card${details.paMicClip === "magnetic_mic" ? " is-selected" : ""}" data-pa-mic-clip="magnetic_mic" aria-pressed="${details.paMicClip === "magnetic_mic" ? "true" : "false"}"><span class="picker-location-card-check">${details.paMicClip === "magnetic_mic" ? "✓" : ""}</span><span>Magnetic mic</span></button>`
    + `<button type="button" class="picker-location-card${details.paMicClip === "manufacturer_clip" ? " is-selected" : ""}" data-pa-mic-clip="manufacturer_clip" aria-pressed="${details.paMicClip === "manufacturer_clip" ? "true" : "false"}"><span class="picker-location-card-check">${details.paMicClip === "manufacturer_clip" ? "✓" : ""}</span><span>Manufacturer clip</span></button></div></div>`
    + `</section>`;
  panel.querySelectorAll("[data-pa-mic-location]").forEach(button => button.addEventListener("click", () => {
    _pickerState.partDetails.paMicLocation = button.dataset.paMicLocation;
    if (button.dataset.paMicLocation !== "__custom__") _pickerState.partDetails.paMicLocationCustom = "";
    _pickerRenderPartDetails();
    _pickerUpdateFooter();
  }));
  panel.querySelectorAll("[data-pa-mic-clip]").forEach(button => button.addEventListener("click", () => {
    _pickerState.partDetails.paMicClip = button.dataset.paMicClip;
    _pickerRenderPartDetails();
    _pickerUpdateFooter();
  }));
  panel.querySelector("#picker-pa-mic-custom")?.addEventListener("input", event => {
    _pickerState.partDetails.paMicLocationCustom = event.target.value;
    _pickerUpdateFooter();
  });
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
  // A custom placement can be anywhere on an exterior drawing, not only on
  // the dots that fit the currently selected part type.
  const allExteriorViews = Object.keys(layoutViews).filter(vk => !vk.startsWith("internal"));
  const canCustom = _pickerLocationAllowsCustom();
  const customCanUseVehiclePlacement = loc.textCustom && _pickerLocationOffersVehiclePlacement();

  // A custom name is enough to save the part.  The vehicle drawing is an
  // optional second step for parts that should appear in the preview/PPT.
  if (loc.textCustom && (!customCanUseVehiclePlacement || loc.customStage !== "placement")) {
    loc.view = "custom";
    const bar = $("picker-loc-views");
    if (bar) bar.innerHTML = `<button class="pf-pill active" data-view="custom">Custom location</button>`;
    const img = $("picker-loc-img"), dots = $("picker-loc-dots"), btns = $("picker-loc-btns"), stage = $("picker-loc-stage");
    if (stage) stage.classList.add("picker-loc-stage--text");
    if (img) img.style.display = "none";
    if (dots) dots.hidden = true;
    if (btns) {
      btns.hidden = false;
      const hasName = Boolean(String(loc.selected || "").trim());
      const placementHelp = customCanUseVehiclePlacement
        ? "Optionally choose where it should appear on the vehicle drawing. Leave it unplaced when this part has no render spot."
        : "Enter the exact shop reference for this installation."
      const placementAction = customCanUseVehiclePlacement
        ? `<button type="button" class="pf-pill${hasName ? " active" : ""}" data-custom-location-placement${hasName ? "" : " disabled"}>Optional vehicle placement →</button>`
        : "";
      btns.innerHTML = `<section class="picker-location-chooser picker-location-chooser--custom"><div class="picker-location-kicker">Custom location</div>`
        + `<h3>What should the shop call this location?</h3><p>${placementHelp}</p>`
        + `<label class="picker-location-custom-field"><span>Custom location name</span><input id="picker-loc-custom-name" class="picker-location-custom-input" placeholder="For example: Rear cargo-window trim" value="${esc(loc.selected || "")}"></label>`
        + `${placementAction}</section>`;
      btns.querySelector("#picker-loc-custom-name")?.addEventListener("input", event => {
        _pickerSetCustomLocationName(event.target.value);
        _pickerUpdateFooter();
        const next = btns.querySelector("[data-custom-location-placement]");
        if (next) next.disabled = !String(_pickerState.loc.selected || "").trim();
      });
      btns.querySelector("[data-custom-location-placement]")?.addEventListener("click", () => {
        if (!String(loc.selected || "").trim()) return;
        loc.customStage = "placement";
        loc.view = allExteriorViews[0] || "location";
        _pickerDrawLocation();
      });
    }
    _pickerRenderPartDetails();
    _pickerUpdateFooter();
    return;
  }
  // Non-diagram parts get a "Location" step: a dropdown of their options, or —
  // when the part_type has no preset locations at all — a free-text field, so the
  // user can always specify a mount point (never a blank vehicle view).
  const customPlacementActive = loc.textCustom && customCanUseVehiclePlacement && loc.customStage === "placement";
  const noPreset = !extViews.length && !dropdownLocs.length;
  const viewList = customPlacementActive ? [...allExteriorViews] : [...extViews];
  if (!customPlacementActive && (dropdownLocs.length || noPreset)) viewList.push("location");
  if (canCustom && !customPlacementActive) viewList.push("custom");
  if (!viewList.includes(loc.view)) loc.view = viewList[0] || "location";

  const bar = $("picker-loc-views");
  if (bar) {
    bar.innerHTML = viewList.map(v => {
      const label = v === "location" ? "Location" : ((layoutViews[v]?.label) || v);
      return `<button class="pf-pill${loc.view === v ? " active" : ""}" data-view="${esc(v)}">${esc(label)}</button>`;
    }).join("");
    bar.querySelectorAll(".pf-pill").forEach(b => b.addEventListener("click", () => {
      if (b.dataset.view === "custom") _pickerStartCustomLocation();
      else { loc.view = b.dataset.view; _pickerDrawLocation(); }
    }));
  }

  const img = $("picker-loc-img"), dots = $("picker-loc-dots"), btns = $("picker-loc-btns");
  const stage = $("picker-loc-stage");
  if (loc.view === "location") {
    // No-diagram locations (equipment mounts, interior lights, console/partition)
    // are shop-reference choices. Render their options as clear selection cards,
    // never a stranded native dropdown.
    if (stage) stage.classList.add("picker-loc-stage--text");
    if (img) img.style.display = "none";
    if (dots) dots.hidden = true;
    if (btns) {
      btns.hidden = false;
      const isControlHead = _pickerResolvedPartTypeId(f) === "control_head";
      const controlHeadNeedsPaMic = _pickerControlHeadRequiresPaMic();
      const locationCopy = isControlHead ? {
        kicker: "Control head setup",
        question: "Where will the control head be mounted?",
        help: controlHeadNeedsPaMic
          ? "Choose the control head location before setting up the PA microphone below."
          : "Choose the control head location for the shop.",
      } : {
        kicker: "Mounting location",
        question: "Where will this part be mounted?",
        help: "Choose a standard location or, when available, enter a shop-specific location.",
      };
      const setTextLocation = (value, entry = null, custom = false) => {
        if (entry) {
          _pickerSetStandardLocation(value, entry);
          return;
        }
        if (custom) _pickerSetCustomLocationName(value);
      };
      if (dropdownLocs.length) {
        const sorted = [...dropdownLocs].sort((a, b) => a.location.localeCompare(b.location));
        const presetNames = new Set(sorted.map(l => l.location.toUpperCase()));
        // Keep an already-saved custom location editable, but do not offer a
        // new custom choice when this part has exactly one fixed location.
        const showCustom = canCustom || !!loc.textCustom;
        const customActive = showCustom && (!!loc.textCustom || (!!loc.selected && !presetNames.has(loc.selected.toUpperCase())));
        const cards = sorted.map(l => {
          const selected = !customActive && loc.selected === l.location;
          return `<button type="button" class="picker-location-card${selected ? " is-selected" : ""}" data-text-location="${esc(l.location)}" aria-pressed="${selected ? "true" : "false"}">`
            + `<span class="picker-location-card-check">${selected ? "✓" : ""}</span><span>${esc(_pickerTitleCase(l.location))}</span></button>`;
        }).join("");
        btns.innerHTML = `<section class="picker-location-chooser"><div class="picker-location-kicker">${esc(locationCopy.kicker)}</div>`
          + `<h3>${esc(locationCopy.question)}</h3><p>${esc(locationCopy.help)}</p>`
          + `<div class="picker-location-grid">${cards}${showCustom ? `<button type="button" class="picker-location-card picker-location-card--custom${customActive ? " is-selected" : ""}" data-text-location-custom aria-pressed="${customActive ? "true" : "false"}">`
          + `<span class="picker-location-card-check">${customActive ? "✓" : ""}</span><span>Custom location<small>Enter a specific shop reference</small></span></button>` : ""}</div>`
          + (customActive ? `<label class="picker-location-custom-field"><span>Custom shop location</span><input id="picker-loc-custom-text" class="picker-location-custom-input" placeholder="Type the exact mount location" value="${esc(loc.selected || "")}"></label>` : "")
          + `</section>`;
        btns.querySelectorAll("[data-text-location]").forEach(button => button.addEventListener("click", () => {
          const value = button.dataset.textLocation;
          setTextLocation(value, loc.locByName[value.toUpperCase()] || null, false);
          _pickerUpdateFooter();
          _pickerDrawLocation();
        }));
        btns.querySelector("[data-text-location-custom]")?.addEventListener("click", () => {
          if (presetNames.has(String(loc.selected || "").toUpperCase())) loc.selected = "";
          setTextLocation(loc.selected || "", null, true);
          _pickerUpdateFooter();
          _pickerDrawLocation();
        });
        const customInput = $("picker-loc-custom-text");
        if (customInput) customInput.addEventListener("input", () => {
          setTextLocation(customInput.value.trim(), null, true);
          _pickerUpdateFooter();
        });
      } else {
        // No curated choices still follows the same explicit custom-location
        // path as every other selectable part; it just has no vehicle dot to
        // choose afterward.
        btns.innerHTML = `<section class="picker-location-chooser"><div class="picker-location-kicker">${esc(locationCopy.kicker)}</div>`
          + `<h3>${esc(locationCopy.question)}</h3><p>This part needs a shop-specific mounting reference.</p>`
          + `<div class="picker-location-grid"><button type="button" class="picker-location-card picker-location-card--custom" data-text-location-custom>`
          + `<span class="picker-location-card-check"></span><span>Custom location<small>Enter a specific shop reference</small></span></button></div></section>`;
        btns.querySelector("[data-text-location-custom]")?.addEventListener("click", () => _pickerStartCustomLocation());
      }
    }
    _pickerRenderPartDetails();
    _pickerUpdateFooter();
    return;
  }
  // Exterior: image + dots
  if (stage) stage.classList.remove("picker-loc-stage--text");
  if (btns) {
    btns.hidden = !customPlacementActive;
    if (customPlacementActive) {
      const free = loc.customPlacementMode === "free";
      if (free && loc.customPlacementAnchors?.[loc.view]) _pickerSetCustomPlacementGroup(loc.view, loc.customPlacementAnchors[loc.view]);
      const viewPointCount = (loc.customPlacements?.[loc.view] || []).length;
      const totalPointCount = _pickerCustomPlacementCount();
      const headCount = _pickerCustomPlacementHeadCount();
      if (headCount !== 4 && loc.customPlacementLayout === "mirrored_pairs") loc.customPlacementLayout = "even";
      const pairLayout = loc.customPlacementLayout === "mirrored_pairs";
      const spacingMax = _pickerCustomSpacingMax(headCount);
      const spacing = Math.min(spacingMax, _pickerNormalizeCustomSpacing(loc.customHeadSpacing));
      loc.customHeadSpacing = spacing;
      btns.innerHTML = `<section class="picker-location-chooser picker-location-chooser--custom picker-location-placement-controls">`
        + `<div class="picker-location-kicker">Vehicle placement</div><h3>Where should this appear?</h3>`
        + `<p>${free ? (pairLayout ? "Click one side to place a two-head pair. The matching pair mirrors automatically on the other side." : `Click anywhere on the vehicle to place all ${headCount} light head${headCount === 1 ? "" : "s"} as one group. Click again to move the group.`) : "Choose any saved vehicle or fixture dot, or set your own exact point."}</p>`
        + `<div class="pf-pills"><button type="button" class="pf-pill${free ? "" : " active"}" data-custom-placement-mode="vehicle">Vehicle dots</button>`
        + `<button type="button" class="pf-pill${free ? " active" : ""}" data-custom-placement-mode="free">Set your own</button></div>`
        + (free && headCount === 4 ? `<div class="pf-pills picker-custom-layout"><button type="button" class="pf-pill${pairLayout ? "" : " active"}" data-custom-placement-layout="even">Equal row</button><button type="button" class="pf-pill${pairLayout ? " active" : ""}" data-custom-placement-layout="mirrored_pairs">Two per side (mirrored)</button></div>` : "")
        + (free && headCount > 1 ? `<label class="picker-custom-spacing"><span>Head spacing <strong data-custom-spacing-value>${Math.round(spacing * 100)}%</strong></span><input type="range" data-custom-spacing min="0.01" max="${spacingMax.toFixed(4)}" step="0.005" value="${spacing.toFixed(4)}"></label>` : "")
        + (free ? `<div class="picker-custom-placement-actions"><span>${viewPointCount ? `${viewPointCount} of ${headCount} heads placed on this view` : `Place ${headCount} head${headCount === 1 ? "" : "s"} on this view`} · ${totalPointCount} points total</span><button type="button" class="pf-pill" data-custom-placement-clear-view${viewPointCount ? "" : " disabled"}>Clear this view</button><button type="button" class="pf-pill" data-custom-placement-clear-all${totalPointCount ? "" : " disabled"}>Clear all</button></div>` : "")
        + `</section>`;
      btns.querySelectorAll("[data-custom-placement-mode]").forEach(button => button.addEventListener("click", () => {
        loc.customPlacementMode = button.dataset.customPlacementMode;
        if (loc.customPlacementMode === "free") loc.renderLocation = "";
        _pickerDrawLocation();
      }));
      btns.querySelectorAll("[data-custom-placement-layout]").forEach(button => button.addEventListener("click", () => {
        loc.customPlacementLayout = button.dataset.customPlacementLayout;
        const anchor = _pickerEnsureCustomPlacementAnchor(loc.view);
        if (anchor) _pickerSetCustomPlacementGroup(loc.view, anchor);
        _pickerDrawLocation(); _pickerUpdateFooter();
      }));
      btns.querySelector("[data-custom-spacing]")?.addEventListener("input", event => {
        loc.customHeadSpacing = _pickerNormalizeCustomSpacing(event.target.value);
        const label = btns.querySelector("[data-custom-spacing-value]");
        if (label) label.textContent = `${Math.round(loc.customHeadSpacing * 100)}%`;
        const anchor = _pickerEnsureCustomPlacementAnchor(loc.view);
        if (anchor) _pickerSetCustomPlacementGroup(loc.view, anchor);
        _pickerPlaceDots(); _pickerUpdateFooter();
      });
      btns.querySelector("[data-custom-placement-clear-view]")?.addEventListener("click", () => {
        delete loc.customPlacements[loc.view]; delete loc.customPlacementAnchors[loc.view]; _pickerDrawLocation(); _pickerUpdateFooter();
      });
      btns.querySelector("[data-custom-placement-clear-all]")?.addEventListener("click", () => {
        loc.customPlacements = {}; loc.customPlacementAnchors = {}; _pickerDrawLocation(); _pickerUpdateFooter();
      });
    }
  }
  if (dots) dots.hidden = false;
  if (img) {
    img.style.display = "";
    img.onload = () => _pickerPlaceDots();
    img.src = `/assets/vehicles/${loc.vehicle}_${loc.view}.png`;
    if (img.complete) _pickerPlaceDots();
  }
  _pickerRenderPartDetails();
}

// Fractional (0–1) slot positions for a location — ported verbatim from
// canvas.js getSlotPositions with box=[0,0,1,1] so mirror/horizontal spreads
// render identically to the placement settings preview.
function _pickerSlotPositions(loc, locationName) {
  const baseCx = loc.x, baseCy = loc.y;
  let pattern = loc.pattern || "single";
  let slotCount = loc.slot_count || 1;
  let slotIndices = null;
  const partTypeId = _pickerResolvedPartTypeId(_pickerState.filters);
  const isScene = ["front_scene", "side_scene", "rear_scene", "spotlight"].includes(partTypeId)
    || _pickerProductCategory(_pickerSelectedProduct()) === "scene";

  if (partTypeId === "siren_speaker") {
    const qty = Math.min(2, Math.max(1, _pickerState.config.count || 1));
    if (qty === 1 && (loc.slot_count || 1) > 1) return [[0.5, baseCy]];
    if (qty === 2) slotCount = 2;
  }

  if (isScene) {
    const qty = Math.max(1, _pickerState.config.count || 1);
    if (qty === 1 && (loc.slot_count || 1) > 1) return [[0.5, baseCy]];
    // A scene-light count is the number of actual heads, not a request to
    // fill this location's historical slot count. Single-dot locations are
    // anchors: one head stays centered; two or more spread horizontally.
    slotCount = qty;
    if (slotCount > 1 && pattern === "single") pattern = "horizontal";
  }

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
  } else if (pattern === "vertical") {
    const rawVSpacing = loc.v_spacing;
    const vSpacing = (rawVSpacing && rawVSpacing > 0) ? rawVSpacing : spacing;
    const totalH = vSpacing * (slotCount - 1), startY = baseCy - totalH / 2;
    positions = Array.from({ length: slotCount }, (_, i) => [baseCx, startY + i * vSpacing]);
  } else if (pattern === "vertical_mirror") {
    const rawVSpacing = loc.v_spacing;
    const vSpacing = (rawVSpacing && rawVSpacing > 0) ? rawVSpacing : spacing;
    const centerY = 0.5, offsetY = Math.abs(baseCy - centerY);
    const resolvedOffset = offsetY < 0.001 ? vSpacing / 2 : offsetY;
    if (slotCount === 2) {
      positions = [[baseCx, centerY - resolvedOffset], [baseCx, centerY + resolvedOffset]];
    } else {
      const half = Math.floor(slotCount / 2);
      positions = [];
      for (let i = 0; i < half; i++) {
        const off = resolvedOffset + i * vSpacing;
        positions.push([baseCx, centerY - off]); positions.push([baseCx, centerY + off]);
      }
    }
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
  const customPlacement = loc.textCustom && loc.customStage === "placement";
  const freePlacement = customPlacement && loc.customPlacementMode === "free";
  dots.style.pointerEvents = freePlacement ? "auto" : "none";
  let dotsHtml = "";

  if (freePlacement) {
    const points = loc.customPlacements?.[loc.view] || [];
    dotsHtml = points.map((point, index) =>
      `<span class="picker-dot picker-custom-dot" data-custom-point="${index}" title="Click the vehicle to move this group" style="left:${(point.x * 100).toFixed(2)}%;top:${(point.y * 100).toFixed(2)}%"></span>`
    ).join("");
  } else {
    const names = Object.keys(locs).filter(n => customPlacement || (() => {
      const e = loc.locByName[n.toUpperCase()];
      return e && (e.has_coords === true || (e.has_coords === undefined && !_INTERIOR_PZ.has(e.placement_zone)));
    })());
    // Draw every slot for each location (mirror/horizontal spreads), mirroring
    // placement settings exactly — a location with pattern:mirror shows its
    // driver+passenger dots, not one centered dot. Clicking any selects it.
    dotsHtml = names.map(n => {
      const c = locs[n];
      const selected = loc.textCustom ? loc.renderLocation === n : loc.selected === n;
      return _pickerSlotPositions(c, n).map(([fx, fy]) =>
        `<button class="picker-dot${selected ? " sel" : ""}" data-name="${esc(n)}" style="left:${(fx * 100).toFixed(2)}%;top:${(fy * 100).toFixed(2)}%"></button>`
      ).join("");
    }).join("");
    if (customPlacement) {
      const fixtures = loc.layouts?.vehicles?.[loc.vehicle]?.fixtures || {};
      dotsHtml += Object.entries(fixtures).flatMap(([fixtureId, fixture]) => {
        const point = fixture?.[loc.view];
        return point && Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y))
          ? [`<button class="picker-dot picker-fixture-dot" data-fixture="${esc(fixtureId)}" style="left:${(Number(point.x) * 100).toFixed(2)}%;top:${(Number(point.y) * 100).toFixed(2)}%"></button>`]
          : [];
      }).join("");
    }
  }
  if (!dotsHtml && !freePlacement) {
    dots.innerHTML = `<div class="picker-dot-empty">No mapped locations for this view.</div>`;
    return;
  }
  dots.innerHTML = dotsHtml + `<div class="picker-dot-tip" id="picker-dot-tip" hidden></div>`;

  const tip = $("picker-dot-tip");
  const allDots = [...dots.querySelectorAll(".picker-dot")];
  if (freePlacement) {
    dots.onclick = event => {
      const rect = dots.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
      _pickerSetCustomPlacementGroup(loc.view, { x, y });
      _pickerPlaceDots(); _pickerUpdateFooter();
    };
    return;
  }
  dots.onclick = null;
  allDots.forEach(d => {
    // Instant custom tooltip + highlight ALL slots of this location (mirror pair).
    d.addEventListener("mouseenter", () => {
      allDots.forEach(o => { if (o.dataset.name === d.dataset.name) o.classList.add("hover"); });
      if (tip) {
        tip.textContent = d.dataset.fixture
          ? `Fixture: ${_pickerTitleCase(d.dataset.fixture.replaceAll("_", " "))}`
          : _pickerTitleCase(d.dataset.name);
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
      const entry = d.dataset.name ? (loc.locByName[d.dataset.name.toUpperCase()] || {}) : {};
      if (loc.textCustom) {
        if (d.dataset.fixture) {
          const fixture = loc.layouts?.vehicles?.[loc.vehicle]?.fixtures?.[d.dataset.fixture]?.[loc.view];
          if (fixture) {
            loc.customPlacementMode = "free";
            loc.renderLocation = "";
            _pickerSetCustomPlacementGroup(loc.view, { x: Number(fixture.x), y: Number(fixture.y) });
          }
        } else {
          loc.customPlacementMode = "vehicle";
          loc.customPlacements = {};
          loc.customPlacementAnchors = {};
          loc.renderLocation = d.dataset.name;
          loc.customStage = "placement";
          loc.name_pattern = entry.name_pattern || "";
          loc.base_label = entry.base_label || "";
          loc.catalog_names = entry.catalog_names || [];
        }
      } else {
        _pickerSetStandardLocation(d.dataset.name, entry);
      }
      if (loc.textCustom && d.dataset.fixture) _pickerDrawLocation();
      else _pickerPlaceDots();
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

// max_count of the resolved free-text part_type (1 → single-instance: name is
// the bare label with no sequence number). Mirrors the label resolution above.
function _pickerFreeTextPartTypeMax(f) {
  const sel = _pickerState.sel;
  const product = sel && _pickerState.products.find(p => p.product_id === sel.product_id);
  const fits = (product && product.fits_part_types) || [];
  const meta = _pickerPartTypeMeta || new Map();
  const pt = fits.map(id => meta.get(id)).find(p => p && p.type_id === f.type_id) || meta.get(fits[0]);
  return pt && pt.max_count;
}

// The part_type_id to tag onto an added line (Step 1b manifest highlight).
// Prefers the tree leaf the user actually picked; falls back to the selected
// product's fits_part_types (same derivation as the free-text label above)
// for edit mode / any path that never touched the browse tree.
function _pickerResolvedPartTypeId(f) {
  const sel = _pickerState.sel;
  const product = sel && _pickerState.products.find(p => p.product_id === sel.product_id);
  // A center-console product can be reached from a family header, a broad
  // structural search, or any leaf that surfaced it. Its product identity is
  // authoritative: it must still be saved as a Console, never as that entry
  // leaf's unrelated part type.
  if ((product?.fits_part_types || []).includes("console")
      || product?.primary_part_type_id === "console") {
    return "console";
  }
  // A combined browse leaf can show the front and rear Interior Light Bar
  // products in one place.  The response records which physical type supplied
  // each product, so persist that type instead of flattening a rear bar into
  // the leaf's front-bar identifier.
  if ((f.part_type_ids || []).length > 1 && product?.primary_part_type_id) {
    return product.primary_part_type_id;
  }
  // A product may have multiple physical homes but a declared semantic picker
  // home (for example T-Series is configured as a Warning Light). Persist that
  // type regardless of the broad browse leaf that exposed the product.
  if (product?.primary_part_type_id && product?.primary_category_id) {
    return product.primary_part_type_id;
  }
  if (f.part_type_id) return f.part_type_id;
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

// Fetch + render the accessories for the selected product.  During a parent
// edit, rebuild the choices from the saved child rows so the selector is a
// true round-trip rather than silently dropping accessories on Save.
function _pickerRecommendationForGroup(group) {
  // A recommendation is an add-time prompt.  During an edit, only retain a
  // saved choice; do not infer a new accessory from the rest of the draft.
  if (_pickerState.editLineId) return null;
  const parts = (typeof _meDraft !== "undefined" && _meDraft?.parts) || [];
  return (group.recommendations || []).find(recommendation => {
    const partTypeId = String(recommendation.when_existing_part_type || "");
    const minimum = Math.max(1, Number(recommendation.minimum_existing_count) || 1);
    if (!partTypeId) return false;
    const count = parts.filter(part => !part.parent_line_id && part.part_type === partTypeId).length;
    return count >= minimum;
  }) || null;
}

function _pickerRecommendationHasSavedChoice(group) {
  const choice = _pickerState.accessoryChoices[group.category];
  return Array.isArray(choice) ? choice.some(Boolean) : Boolean(choice);
}

function _pickerAccessorySkuForPick(group, pick) {
  if (!pick || pick === "none") return null;
  const [productId, partNumber] = String(pick).split("::");
  const option = (group?.options || []).find(item => item.product_id === productId);
  const sku = (option?.skus || []).find(item => item.part_number === partNumber);
  return sku ? { option, sku } : null;
}

function _pickerAccessoryParentQuantity() {
  const product = _pickerSelectedProduct();
  if (!product) return Math.max(1, Number(_pickerState.config.count) || 1);
  if (_pickerUsesLocationAllocation(product)) return Math.max(1, _pickerLocationAllocationTotal());
  if (_pickerIsWindowTint(product)) return Math.max(1, _pickerState.tint.windows.length || 1);
  if (_pickerIsSirenSpeakerContext() || _pickerProductCategory(product) === "scene") {
    return Math.max(1, Number(_pickerState.config.count) || 1);
  }
  const colorConfigured = _pickerUsesColor(product)
    && !_pickerState.sel?.sku
    && _pickerProductHasColor(product || { skus: [] });
  return colorConfigured ? Math.max(1, Number(_pickerState.config.count) || 1) : 1;
}

function _pickerAccessoryQuantityRule(group, pick) {
  return _pickerAccessorySkuForPick(group, pick)?.sku?.accessory_quantity || {};
}

function _pickerAccessoryRecommendedQuantity(group, pick) {
  const rule = _pickerAccessoryQuantityRule(group, pick);
  if (rule.mode !== "cover_parent_quantity") return 1;
  const coverage = Math.max(1, Number(rule.parent_units_per_item) || 1);
  return Math.max(1, Math.ceil(_pickerAccessoryParentQuantity() / coverage));
}

function _pickerAccessoryCoverageError(group, pick) {
  const rule = _pickerAccessoryQuantityRule(group, pick);
  if (!rule.requires_complete_groups) return "";
  const coverage = Math.max(1, Number(rule.parent_units_per_item) || 1);
  const parentQty = _pickerAccessoryParentQuantity();
  if (parentQty % coverage === 0) return "";
  return `${_pickerAccessorySkuForPick(group, pick)?.sku?.part_number || "This accessory"} requires complete groups of ${coverage}; ${parentQty} lights cannot be fully paired.`;
}

function _pickerAccessoryStateList(store, category, count, fallback) {
  const current = store[category];
  const values = Array.isArray(current) ? [...current] : [current ?? fallback];
  while (values.length < count) values.push(fallback);
  return values.slice(0, count);
}

function _pickerStoreAccessoryState(store, category, values, forceArray = false) {
  store[category] = forceArray || values.length > 1 ? [...values] : values[0];
}

function _pickerSyncAccessoryQuantityDefaults() {
  for (const group of (_pickerState.accessories || [])) {
    const saved = _pickerState.accessoryChoices[group.category];
    const picks = Array.isArray(saved) ? saved : [saved || ""];
    const quantities = _pickerAccessoryStateList(
      _pickerState.accessoryQuantities, group.category, picks.length, 1,
    );
    const manual = _pickerAccessoryStateList(
      _pickerState.accessoryQuantityManual, group.category, picks.length, false,
    );
    picks.forEach((pick, index) => {
      if (!manual[index]) quantities[index] = _pickerAccessoryRecommendedQuantity(group, pick);
    });
    _pickerStoreAccessoryState(_pickerState.accessoryQuantities, group.category, quantities, Array.isArray(saved));
    _pickerStoreAccessoryState(_pickerState.accessoryQuantityManual, group.category, manual, Array.isArray(saved));
  }
}

function _pickerApplyAccessoryRecommendations() {
  if (_pickerState.editLineId) return;
  const vehicle = _pickerVehicle();
  const useVehicleFilter = _pickerState.vehicleOnly && !!vehicle;
  for (const group of (_pickerState.accessories || [])) {
    const recommendation = _pickerRecommendationForGroup(group);
    if (!recommendation || _pickerState.accessoryChoices[group.category]) continue;
    const option = (group.options || []).find(item => item.product_id === recommendation.product_id);
    const sku = (option?.skus || []).find(item => !useVehicleFilter || _skuCompatible(item, vehicle));
    if (option && sku) _pickerState.accessoryChoices[group.category] = `${option.product_id}::${sku.part_number}`;
  }
}

function _pickerApplyAutomaticAccessories() {
  const vehicle = _pickerVehicle();
  const useVehicleFilter = _pickerState.vehicleOnly && !!vehicle;
  for (const group of (_pickerState.accessories || [])) {
    if (_pickerRecommendationHasSavedChoice(group)) continue;
    const automaticIds = new Set(group.automatic_option_ids || []);
    if (!automaticIds.size) continue;
    const option = (group.options || []).find(item => automaticIds.has(item.product_id));
    const sku = (option?.skus || []).find(item => !useVehicleFilter || _skuCompatible(item, vehicle));
    if (option && sku) {
      _pickerState.accessoryChoices[group.category] = `${option.product_id}::${sku.part_number}`;
    }
  }
}

async function _pickerLoadAccessories(productId, { restoreFromDraft = false } = {}) {
  if (!productId) {
    _pickerState.accessories = []; _pickerState.accessoryChoices = {};
    _pickerState.accessoryQuantities = {}; _pickerState.accessoryQuantityManual = {};
    _pickerState.accLoadedFor = productId || null;
    _pickerRenderAccessories(); _pickerUpdateFooter(); return;
  }
  if (_pickerState.accLoadedFor === productId && !restoreFromDraft) return;   // already loaded
  _pickerState.accLoadedFor = productId;
  try {
    const res = await api(`/api/parts-db/accessories?product_id=${encodeURIComponent(productId)}`);
    _pickerState.accessories = (res && res.accessories) || [];
  } catch (e) { console.error("accessories load failed:", e); _pickerState.accessories = []; }
  if (restoreFromDraft) _pickerMergeManifestAccessories(_pickerState.accessories);
  const restored = restoreFromDraft
    ? _pickerRestoreAccessoryState(productId, _pickerState.accessories)
    : null;
  _pickerState.accessoryChoices = restored?.choices
    || Object.fromEntries(_pickerState.accessories.map(g => [g.category, ""]));
  _pickerState.accessoryQuantities = restored?.quantities
    || Object.fromEntries(_pickerState.accessories.map(g => [g.category, 1]));
  _pickerState.accessoryQuantityManual = restored?.manual
    || Object.fromEntries(_pickerState.accessories.map(g => [g.category, false]));
  _pickerApplyAutomaticAccessories();
  _pickerApplyAccessoryRecommendations();
  _pickerSyncAccessoryQuantityDefaults();
  await _pickerApplyLicensePlateLocation();
  _pickerRenderAccessories();
  // Westin options live in the product-specific accessory response rather
  // than the base-bumper browse list. Refresh the selected card once that
  // response arrives so its two selectors appear without another click.
  const selected = _pickerState.sel && _pickerState.products.find(product => product.product_id === productId);
  if (_pickerIsWestinBasePushBumper(selected)) _pickerRenderProducts();
  // Custom tracer mode reads its head list from the lighthead accessory group;
  // refresh the panel now that it's loaded.
  if (_pickerState.tracer.active && _pickerState.tracer.mode === "custom") _pickerRenderTracer();
  _pickerUpdateFooter();
}

function _pickerAccessoryPickForChild(group, child) {
  for (const option of (group.options || [])) {
    if ((option.skus || []).some(sku => sku.part_number === child.part_number)) {
      return `${option.product_id}::${child.part_number}`;
    }
  }
  return "";
}

function _pickerSavedAccessoryModel(child, parent) {
  const prefix = parent?.name ? `${parent.name} · ` : "";
  const name = child.name || "";
  return prefix && name.startsWith(prefix) ? name.slice(prefix.length) : (name || child.part_number || "Saved accessory");
}

const _PICKER_NONSTANDARD_ACCESSORY_CHILDREN = new Set([
  "magnetic_mic", "console_faceplate", "console_component", "console_wings", "system_cable_refresh",
  "westin_wire_cover", "westin_light_channel", "westin_channel_light",
]);

// Old builds may carry an accessory child whose SKU is no longer linked to the
// parent in today's parts database. Retain that saved choice in the same picker
// instead of making a user re-enter it manually. It is intentionally draft-only:
// saving the parent writes the current accessory metadata back to the child.
function _pickerMergeManifestAccessories(groups) {
  const parentLineId = _pickerState.editLineId;
  const productId = _pickerState.sel?.product_id || "";
  const parts = (typeof _meDraft !== "undefined" && _meDraft?.parts) || [];
  const parent = parts.find(part => part.line_id === parentLineId);
  for (const child of parts.filter(part =>
    part.parent_line_id === parentLineId
    && part.part_number
    && !_PICKER_NONSTANDARD_ACCESSORY_CHILDREN.has(part.accessory_category)
    && (!part.accessory_parent_product || part.accessory_parent_product === productId)
  )) {
    const inCatalog = (groups || []).some(group => _pickerAccessoryPickForChild(group, child));
    if (inCatalog) continue;
    let group = (groups || []).find(candidate => candidate.category === child.accessory_category);
    if (!group) {
      const category = child.accessory_category || "other";
      group = {
        category,
        label: category === "bracket_mount" ? "Bracket / Mount" : "Saved accessory",
        required: false,
        options: [],
      };
      groups.push(group);
    }
    if (_pickerAccessoryPickForChild(group, child)) continue;
    group.options.push({
      product_id: `saved_${child.line_id}`,
      model: _pickerSavedAccessoryModel(child, parent),
      manufacturer_label: child.manufacturer || "",
      skus: [{
        part_number: child.part_number,
        friendly_name: _pickerSavedAccessoryModel(child, parent),
        price: null,
        color: "", secondary_color: "", tertiary_color: "", lens_type: "",
        vehicle_tags: [], qb_pending: false,
      }],
    });
  }
}

// Resolve a saved child against the groups currently offered for its parent.
// Older drafts did not store accessory metadata (and printer roles later split
// from generic Cable), so the actual parent relationship + SKU is the durable
// source of truth. Prefer a matching saved category, then fall back to the
// SKU's current group.
function _pickerAccessoryChoiceForChild(groups, child) {
  const allGroups = groups || [];
  const preferred = allGroups.find(group => group.category === child.accessory_category);
  const candidates = preferred
    ? [preferred, ...allGroups.filter(group => group !== preferred)]
    : allGroups;
  for (const group of candidates) {
    const pick = _pickerAccessoryPickForChild(group, child);
    if (pick) return { category: group.category, pick };
  }
  return null;
}

function _pickerRestoreAccessoryState(productId, groups) {
  const choices = Object.fromEntries((groups || []).map(group => [group.category, ""]));
  const quantities = Object.fromEntries((groups || []).map(group => [group.category, 1]));
  const manual = Object.fromEntries((groups || []).map(group => [group.category, false]));
  const parentLineId = _pickerState.editLineId;
  const saved = {};
  for (const child of ((typeof _meDraft !== "undefined" && _meDraft?.parts) || [])) {
    if (child.parent_line_id !== parentLineId) continue;
    const match = _pickerAccessoryChoiceForChild(groups, child);
    if (!match) continue;
    (saved[match.category] ||= []).push({
      pick: match.pick,
      quantity: Math.max(1, Number(child.quantity) || 1),
      manual: child.picker_config?.accessory_quantity?.manual_quantity === true,
    });
  }
  for (const group of (groups || [])) {
    const rows = saved[group.category] || [];
    const picks = rows.map(row => row.pick);
    const qtys = rows.map(row => row.quantity);
    const flags = rows.map(row => row.manual);
    choices[group.category] = picks.length > 1 ? picks : (picks[0] || "");
    quantities[group.category] = qtys.length > 1 ? qtys : (qtys[0] || 1);
    manual[group.category] = flags.length > 1 ? flags : (flags[0] || false);
  }
  return { choices, quantities, manual };
}

function _pickerScrollSelectedProductIntoView() {
  const productId = _pickerState.editLineId && _pickerState.sel?.product_id;
  if (!productId) return;
  const row = Array.from(document.querySelectorAll("#picker-products .pp-row"))
    .find(candidate => candidate.dataset.pid === productId);
  // An expanded product can be taller than the product-list viewport once its
  // options and accessories are restored.  Center the stable product header,
  // not the entire row, so edit mode always reveals what was selected.
  (row?.querySelector(".pp-head") || row)?.scrollIntoView({ block: "center", inline: "nearest" });
}

function _pickerAccLabel(opt, sku) {
  const colors = [sku.color, sku.secondary_color, sku.tertiary_color].filter(Boolean).map(c => c[0].toUpperCase() + c.slice(1)).join("/");
  const price = sku.price != null ? ` · ${_pickerRetailPrice(sku.price)}` : "";
  // Put the orderable SKU first. Native selects truncate from the right, and
  // accessories frequently have nearly identical friendly descriptions, so the
  // part number must be the first thing a purchaser can identify.
  const lead = sku.friendly_name || opt.model;
  const pend = sku.qb_pending ? " · ⧗ pending QB" : "";
  const skuPrefix = sku.part_number ? `${sku.part_number}${lead ? " · " : ""}` : "";
  return `${skuPrefix}${lead}${colors ? " · " + colors : ""}${price}${pend}`;
}

function _pickerRenderAccessories() {
  const el = $("picker-accessories");
  if (!el) return;
  const groups = _pickerVisibleAccessoryGroups();
  if (!groups.length) { el.hidden = true; el.innerHTML = ""; return; }
  _pickerSyncAccessoryQuantityDefaults();
  el.hidden = false;
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  const _optionsHtml = (g, val) => {
    let opts = `<option value=""${val === "" ? " selected" : ""} disabled>— Choose —</option>`;
    if (!g.required) opts += `<option value="none"${val === "none" ? " selected" : ""}>— None needed —</option>`;
    for (const o of g.options) for (const s of (o.skus || [])) {
      const v = `${o.product_id}::${s.part_number}`;
      if (vehFiltering && val !== v && !_skuCompatible(s, veh)) continue;
      opts += `<option value="${esc(v)}"${val === v ? " selected" : ""}>${esc(_pickerAccLabel(o, s))}</option>`;
    }
    return opts;
  };
  const _quantityHtml = (g, val, qty, idx, indexed) => {
    if (!val || val === "none") return "";
    const recommendation = _pickerAccessoryRecommendedQuantity(g, val);
    const rule = _pickerAccessoryQuantityRule(g, val);
    const coverage = Math.max(1, Number(rule.parent_units_per_item) || 1);
    const parentQty = _pickerAccessoryParentQuantity();
    const coverageNote = rule.mode === "cover_parent_quantity"
      ? `Recommended ${recommendation} for ${parentQty} light${parentQty === 1 ? "" : "s"} · 1 covers ${coverage}`
      : `Recommended ${recommendation}`;
    const coverageError = _pickerAccessoryCoverageError(g, val);
    return `<span class="pa-accessory-qty"><span>Qty</span><input type="number" min="1" max="999" step="1" value="${Math.max(1, Number(qty) || 1)}" data-accessory-qty="${esc(g.category)}"${indexed ? ` data-idx="${idx}"` : ""} aria-label="${esc(g.label)} quantity"></span>`
      + `<span class="${coverageError ? "pa-coverage-note pa-coverage-error" : "pa-coverage-note"}">${esc(coverageError || coverageNote)}</span>`;
  };
  const rows = groups.map(g => {
    const automatic = (g.automatic_option_ids || []).length > 0;
    const recommendation = _pickerRecommendationForGroup(g);
    const recommendationNote = recommendation
      ? `<span class="pa-recommendation">${esc(recommendation.message || "Recommended accessory")}</span>`
      : "";
    const multi = _pickerIsSirenSpeakerContext() && g.category === "bracket_mount";
    if (multi) {
      const count = Math.min(2, Math.max(1, _pickerState.config.count || 1));
      const vals = Array.isArray(_pickerState.accessoryChoices[g.category])
        ? _pickerState.accessoryChoices[g.category]
        : Array(count).fill(_pickerState.accessoryChoices[g.category] || "");
      _pickerState.accessoryChoices[g.category] = vals.slice(0, count);
      while (_pickerState.accessoryChoices[g.category].length < count) _pickerState.accessoryChoices[g.category].push("");
      const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, g.category, count, 1);
      const manual = _pickerAccessoryStateList(_pickerState.accessoryQuantityManual, g.category, count, false);
      _pickerStoreAccessoryState(_pickerState.accessoryQuantities, g.category, quantities, true);
      _pickerStoreAccessoryState(_pickerState.accessoryQuantityManual, g.category, manual, true);
      const selects = _pickerState.accessoryChoices[g.category].map((val, idx) =>
        `<div class="pa-subrow"><span class="pa-sub-label">Speaker ${idx + 1}</span>`
        + `<select class="${val ? "pa-chosen" : "pa-unset"}" data-cat="${esc(g.category)}" data-idx="${idx}">${_optionsHtml(g, val)}</select>`
        + `${_quantityHtml(g, val, quantities[idx], idx, true)}</div>`
      ).join("");
      return `<div class="pa-row pa-row-stack"><label>${esc(g.label)}${recommendationNote}${g.required ? '<span class="pa-req">*</span>' : ""}</label><div class="pa-subrows">${selects}</div></div>`;
    }
    const saved = _pickerState.accessoryChoices[g.category];
    const vals = Array.isArray(saved) ? saved : [saved || ""];
    const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, g.category, vals.length, 1);
    const canAdd = vals.length > 0 && vals.every(value => value && value !== "none");
    const selects = vals.map((val, idx) => {
      const indexed = Array.isArray(saved);
      const remove = indexed && vals.length > 1
        ? `<button type="button" class="pa-accessory-remove" data-accessory-remove="${esc(g.category)}" data-idx="${idx}" title="Remove this accessory">×</button>`
        : "";
      return `<div class="pa-subrow"><select class="${val ? "pa-chosen" : "pa-unset"}" data-cat="${esc(g.category)}"${indexed ? ` data-idx="${idx}"` : ""}${automatic ? " disabled" : ""}>${_optionsHtml(g, val)}</select>`
        + `${_quantityHtml(g, val, quantities[idx], idx, indexed)}`
        + `${automatic ? '<span class="pa-recommendation">Automatically included</span>' : remove}</div>`;
    }).join("");
    const add = automatic ? "" : `<button type="button" class="pa-accessory-add" data-accessory-add="${esc(g.category)}"${canAdd ? "" : " disabled"}>+ Add another ${esc(g.label)}</button>`;
    return `<div class="pa-row pa-row-stack"><label>${esc(g.label)}${recommendationNote}${g.required ? '<span class="pa-req">*</span>' : ""}</label><div class="pa-subrows">${selects}</div>${add}</div>`;
  }).join("");
  const pending = !_accessoriesSatisfied();
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">${groups.length}</span>`
    + `${pending ? "This part has accessories — choose each one to continue" : "Accessories set ✓"}`
    + `<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>`
    + `<div class="pa-rows">${rows}</div>`;
  el.querySelectorAll("select[data-cat]").forEach(sel => sel.addEventListener("change", async () => {
    const category = sel.dataset.cat;
    const group = groups.find(item => item.category === category);
    const indexed = sel.dataset.idx !== undefined;
    const index = indexed ? parseInt(sel.dataset.idx, 10) : 0;
    if (indexed) {
      const arr = Array.isArray(_pickerState.accessoryChoices[category])
        ? [..._pickerState.accessoryChoices[category]]
        : [];
      arr[index] = sel.value;
      _pickerState.accessoryChoices[category] = arr;
    } else {
      _pickerState.accessoryChoices[category] = sel.value;
    }
    const rowCount = Array.isArray(_pickerState.accessoryChoices[category])
      ? _pickerState.accessoryChoices[category].length : 1;
    const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, category, rowCount, 1);
    const manual = _pickerAccessoryStateList(_pickerState.accessoryQuantityManual, category, rowCount, false);
    manual[index] = false;
    quantities[index] = _pickerAccessoryRecommendedQuantity(group, sel.value);
    _pickerStoreAccessoryState(_pickerState.accessoryQuantities, category, quantities, indexed);
    _pickerStoreAccessoryState(_pickerState.accessoryQuantityManual, category, manual, indexed);
    await _pickerApplyLicensePlateLocation({ force: true });
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("input[data-accessory-qty]").forEach(input => input.addEventListener("change", () => {
    const category = input.dataset.accessoryQty;
    const indexed = input.dataset.idx !== undefined;
    const index = indexed ? parseInt(input.dataset.idx, 10) : 0;
    const rowCount = Array.isArray(_pickerState.accessoryChoices[category])
      ? _pickerState.accessoryChoices[category].length : 1;
    const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, category, rowCount, 1);
    const manual = _pickerAccessoryStateList(_pickerState.accessoryQuantityManual, category, rowCount, false);
    quantities[index] = Math.min(999, Math.max(1, Math.round(Number(input.value) || 1)));
    manual[index] = true;
    _pickerStoreAccessoryState(_pickerState.accessoryQuantities, category, quantities, indexed);
    _pickerStoreAccessoryState(_pickerState.accessoryQuantityManual, category, manual, indexed);
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-accessory-add]").forEach(button => button.addEventListener("click", () => {
    const category = button.dataset.accessoryAdd;
    const current = _pickerState.accessoryChoices[category];
    const values = Array.isArray(current) ? [...current] : [current || ""];
    if (!values.every(value => value && value !== "none")) return;
    _pickerState.accessoryChoices[category] = [...values, ""];
    const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, category, values.length, 1);
    const manual = _pickerAccessoryStateList(_pickerState.accessoryQuantityManual, category, values.length, false);
    _pickerState.accessoryQuantities[category] = [...quantities, 1];
    _pickerState.accessoryQuantityManual[category] = [...manual, false];
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-accessory-remove]").forEach(button => button.addEventListener("click", async () => {
    const category = button.dataset.accessoryRemove;
    const values = Array.isArray(_pickerState.accessoryChoices[category])
      ? [..._pickerState.accessoryChoices[category]] : [];
    const index = Number(button.dataset.idx);
    const quantities = _pickerAccessoryStateList(_pickerState.accessoryQuantities, category, values.length, 1);
    const manual = _pickerAccessoryStateList(_pickerState.accessoryQuantityManual, category, values.length, false);
    values.splice(index, 1); quantities.splice(index, 1); manual.splice(index, 1);
    _pickerState.accessoryChoices[category] = values.length <= 1 ? (values[0] || "") : values;
    _pickerState.accessoryQuantities[category] = quantities.length <= 1 ? (quantities[0] || 1) : quantities;
    _pickerState.accessoryQuantityManual[category] = manual.length <= 1 ? (manual[0] || false) : manual;
    await _pickerApplyLicensePlateLocation({ force: true });
    _pickerRenderAccessories(); _pickerUpdateFooter();
  }));
}

// Accessory groups the picker actually shows. Tracer and Inner Edge panels own
// their lighthead choices, so the generic lighthead dropdown must stay hidden.
// Tracer's bracket dropdown is additionally narrowed to the tracer-specific
// mounting products (the L-brackets + vehicle kits).
function _pickerVisibleAccessoryGroups() {
  let groups = _pickerState.accessories || [];
  groups = groups.filter(group => !(group.recommendations || []).length
    || _pickerRecommendationForGroup(group) || _pickerRecommendationHasSavedChoice(group));
  const selected = _pickerState.sel && _pickerState.products.find(product => product.product_id === _pickerState.sel.product_id);
  const integratedHowlerAssembly = selected?.product_id === "whelen_wcx_howler"
    && ["CHWLDD36", "CHWLFE29", "CHWLUNI"].includes(_pickerState.sel?.sku || "");
  if (integratedHowlerAssembly) {
    // These current Howler assemblies include their vehicle-specific or
    // universal bracket. The legacy inactive CHOWLER item did not, so retain
    // its historical optional mount prompt when reviewing an old build.
    groups = groups.filter(group => group.category !== "bracket_mount");
  }
  if (_pickerIsWestinBasePushBumper(selected)) {
    // The Westin controls beside the bumper own both specific Westin
    // accessory categories; never duplicate them in the generic panel.
    groups = groups.filter(group => !["westin_wire_cover", "westin_light_channel"].includes(group.category));
  }
  if (_pickerState.outerEdge?.active) return [];
  if (_pickerState.innerEdge?.active) return groups.filter(g => g.category !== "lighthead");
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
    if (Array.isArray(v)) {
      if (v.some(x => !x)) return false;
      if (g.required && v.some(x => x === "none")) return false;
      if (v.some(x => _pickerAccessoryCoverageError(g, x))) return false;
      continue;
    }
    if (!v) return false;                        // not yet addressed
    if (g.required && v === "none") return false;
    if (_pickerAccessoryCoverageError(g, v)) return false;
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

// Tracers are vehicle fixtures, not manually placed warning heads. Keep their
// logical fixture location on the saved line for manifest clarity; the planner
// resolves the actual coordinates from the selected housing SKU.
async function _pickerTracerAutoLocation() {
  const sel = _pickerState.sel, loc = _pickerState.loc;
  const product = _pickerState.products.find(p => p.product_id === (sel || {}).product_id);
  if (!sel || !product || loc.selected) return;
  const lamps = _pickerTracerLamps(product);
  const fixtureId = { 2: "tracer_2lamp", 3: "tracer_3lamp", 5: "tracer_5lamp", 6: "tracer_6lamp" }[lamps];
  if (!fixtureId) return;
  const label = `${lamps}-Lamp Tracer`;
  loc.selected = `FIXTURE:${fixtureId.toUpperCase()}`;
  loc.name_pattern = label;
  loc.base_label = label;
  loc.catalog_names = [label];
  loc.textCustom = false;
  _pickerUpdateFooter();
}

async function _pickerLoadTracer(productId) {
  const t = _pickerState.tracer;
  const product = _pickerState.products.find(p => p.product_id === productId);
  if (!productId || _pickerState.editLineId || !_pickerIsTracer(product)) {
    _pickerState.tracer = { active: false, mode: t.mode, secondary: t.secondary, lens: t.lens || "clear", custom: {}, preview: null, loading: false };
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
  const lens = t.lens === "smoked" ? "smoked" : "clear";
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
  const lens = t.lens === "smoked" ? "smoked" : "clear";
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
      <div class="pf-group"><span class="pf-label">Lens</span><div class="pf-pills">
        ${pill("lens", "clear", "Clear", lens === "clear")}
        ${pill("lens", "smoked", "Smoked", lens === "smoked")}</div></div>
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

// ── Inner Edge FST / RST ──────────────────────────────
// Inner Edges use their selected housing SKU (not the generic product model)
// to determine the physical head count. They share Duo/Trio choices with a
// Tracer, but all head rows are the same Inner Edge head product — no primary
// and secondary head roles exist here.
const _INNER_EDGE_PRODUCTS = new Set(["whelen_fst", "whelen_rst"]);

function _pickerIsInnerEdge(product) {
  return !!product && _INNER_EDGE_PRODUCTS.has(product.product_id);
}

function _pickerInnerEdgeDefaultCoverage(product, sku) {
  if (product?.product_id !== "whelen_fst") return "both";
  const text = `${sku?.friendly_name || ""} ${sku?.part_number || ""}`.toLowerCase();
  if (/passenger\s+side(?:\s+unit)?\s+only/.test(text)) return "passenger";
  if (/driver\s+side(?:\s+unit)?\s+only/.test(text)) return "driver";
  return "both";
}

function _pickerInnerEdgeDefaultMode(sku) {
  return /\btrio\b/i.test(sku?.friendly_name || "") ? "trio" : "duo";
}

async function _pickerLoadInnerEdge(productId, { restoreFromDraft = false } = {}) {
  const previous = _pickerState.innerEdge;
  const product = _pickerState.products.find(p => p.product_id === productId);
  const sel = _pickerState.sel;
  if (!productId || !sel?.sku || !_pickerIsInnerEdge(product)) {
    _pickerState.innerEdge = {
      active: false, mode: previous.mode, secondary: previous.secondary,
      coverage: previous.coverage, preview: null, loading: false,
    };
    _pickerRenderInnerEdge(); _pickerRenderAccessories(); _pickerUpdateFooter();
    return;
  }
  const selectedSku = (product.skus || []).find(s => s.part_number === sel.sku) || {};
  const saved = restoreFromDraft ? _pickerState.editPart?.picker_config?.inner_edge : null;
  const useSaved = saved && saved.product_id === productId;
  const mode = useSaved && ["duo", "trio"].includes(saved.mode)
    ? saved.mode : _pickerInnerEdgeDefaultMode(selectedSku);
  const secondary = useSaved && ["white", "amber"].includes(saved.secondary)
    ? saved.secondary : (mode === "trio" ? "amber" : previous.secondary || "white");
  const coverage = useSaved && ["both", "driver", "passenger"].includes(saved.coverage)
    ? saved.coverage : _pickerInnerEdgeDefaultCoverage(product, selectedSku);
  _pickerState.innerEdge = { active: true, mode, secondary, coverage, preview: null, loading: true };
  _pickerRenderInnerEdge(); _pickerRenderAccessories();
  await _pickerFetchInnerEdgePreview();
}

async function _pickerFetchInnerEdgePreview() {
  const ie = _pickerState.innerEdge, sel = _pickerState.sel;
  if (!ie.active || !sel?.sku) return;
  ie.loading = true; _pickerRenderInnerEdge();
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&part_number=${encodeURIComponent(sel.sku)}`
      + `&mode=${encodeURIComponent(ie.mode)}&secondary=${encodeURIComponent(ie.secondary)}`;
    ie.preview = await api(`/api/parts-db/inner-edge-heads?${qs}`);
  } catch (error) {
    console.error("Inner Edge resolve failed:", error);
    ie.preview = { ok: false, error: "request_failed", lines: [], problems: [] };
  }
  ie.loading = false;
  _pickerRenderInnerEdge(); _pickerUpdateFooter();
}

function _pickerRenderInnerEdge() {
  const el = $("picker-inner-edge"); if (!el) return;
  const ie = _pickerState.innerEdge;
  if (!ie.active) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const product = _pickerState.products.find(p => p.product_id === (_pickerState.sel || {}).product_id);
  const isFst = product?.product_id === "whelen_fst";
  const pill = (key, value, label, selected) =>
    `<button class="pf-pill${selected ? " active" : ""}" data-iek="${key}" data-iev="${value}">${esc(label)}</button>`;
  let previewHtml = "";
  if (ie.loading) {
    previewHtml = `<div class="pt-preview muted">Reading the selected SKU's head count…</div>`;
  } else if (ie.preview?.ok) {
    previewHtml = `<div class="pt-preview">${(ie.preview.lines || []).map(line => {
      const pending = line.pending ? ` <span class="pp-pending">pending QB</span>` : "";
      const side = line.side ? ` · ${line.side}` : "";
      return `<div class="pt-line"><span class="pt-qty">${line.qty}×</span> <span class="pt-sku">${esc(line.sku)}</span> <span class="pt-role">${esc(line.kind)}${esc(side)}</span>${pending}</div>`;
    }).join("")}</div>`;
  } else if (ie.preview) {
    const problems = (ie.preview.problems || []).map(problem =>
      problem.reason === "missing_head_sku"
        ? `Need a ${esc((problem.colors || []).join("/"))} Inner Edge head — it is not in the catalog yet.`
        : esc(problem.detail || problem.reason || "Unable to resolve this configuration")
    ).join("<br>");
    previewHtml = `<div class="pt-preview err">⚠ Can't build this combination yet:<br>${problems}</div>`;
  }
  const lampCount = ie.preview?.lamp_count;
  const countNote = lampCount ? `${lampCount} heads from the selected QB SKU` : "Head count comes from the selected QB SKU";
  const coverageRow = isFst ? `<div class="pf-group"><span class="pf-label">Front modules</span><div class="pf-pills">
      ${pill("coverage", "both", "Driver + passenger", ie.coverage === "both")}
      ${pill("coverage", "driver", "Driver only", ie.coverage === "driver")}
      ${pill("coverage", "passenger", "Passenger only", ie.coverage === "passenger")}
    </div><span class="pt-lens">Layout only — this never changes the selected SKU or its billed count.</span></div>`
    : `<div class="pf-group"><span class="pf-label">Rear module</span><span class="pt-lens">Full-width connected rear-window row</span></div>`;
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">⚡</span>Inner Edge lightheads — choose a configuration<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>
    <div class="pt-rows">
      <div class="pf-group"><span class="pf-label">Heads</span><div class="pf-pills">
        ${pill("mode", "duo", "Standard Duo", ie.mode === "duo")}
        ${pill("mode", "trio", "Standard Trio", ie.mode === "trio")}</div></div>
      <div class="pf-group"><span class="pf-label">Secondary color</span><div class="pf-pills">
        ${pill("secondary", "white", "White", ie.secondary === "white")}
        ${pill("secondary", "amber", "Amber", ie.secondary === "amber")}</div></div>
      ${coverageRow}
      <div class="pf-group"><span class="pf-label">Count</span><span class="pt-lens">${esc(countNote)}</span></div>
    </div>${previewHtml}`;
  el.querySelectorAll("[data-iek]").forEach(button => button.addEventListener("click", () => {
    _pickerState.innerEdge[button.dataset.iek] = button.dataset.iev;
    _pickerFetchInnerEdgePreview();
  }));
}

function _pickerInnerEdgeSatisfied() {
  const ie = _pickerState.innerEdge;
  return !ie.active || !!(ie.preview && ie.preview.ok);
}

// ── Outer Edge rear pillars ─────────────────────────────
// These are six-lamp, two-piece rear-pillar assemblies. The housing's exact
// QB SKU fixes Duo versus Trio; we add its six included IONs as nested rows
// rather than leaving an ambiguous generic lighthead accessory dropdown.
const _OUTER_EDGE_PILLAR_PRODUCT = "whelen_ion_rear_pillar";
const _OUTER_EDGE_PILLAR_LOCATION = "PILLARS";

function _pickerIsOuterEdgePillar(product) {
  return !!product && product.product_id === _OUTER_EDGE_PILLAR_PRODUCT;
}

function _pickerOuterEdgeMode(sku) {
  return /\btrio\b/i.test(sku?.friendly_name || "") ? "trio" : "duo";
}

// Outer Edge is a vehicle-specific rear-pillar assembly. It always uses the
// two PILLARS anchors, so bypass the generic warning-light placement step.
function _pickerOuterEdgeAutoLocation() {
  if (!_pickerState.outerEdge.active) return;
  if (_pickerState.editLineId) {
    // Keep an existing draft's saved location intact, but recognize newly
    // authored pillar rows as automatic when reopening them for an edit.
    if (_pickerState.loc.selected === _OUTER_EDGE_PILLAR_LOCATION) {
      _pickerState.loc.autoLocation = "outer_edge_pillars";
    }
    return;
  }
  _pickerSetStandardLocation(_OUTER_EDGE_PILLAR_LOCATION, {
    name_pattern: "Rear Warning {n}", base_label: "Rear Warning", catalog_names: [],
  }, "outer_edge_pillars");
}

async function _pickerLoadOuterEdge(productId, { restoreFromDraft = false } = {}) {
  const previous = _pickerState.outerEdge;
  const product = _pickerState.products.find(item => item.product_id === productId);
  const sel = _pickerState.sel;
  if (!productId || !sel?.sku || !_pickerIsOuterEdgePillar(product)) {
    _pickerState.outerEdge = {
      active: false, mode: previous.mode, secondary: previous.secondary,
      preview: null, loading: false,
    };
    _pickerRenderOuterEdge(); _pickerRenderAccessories(); _pickerUpdateFooter();
    return;
  }
  const selectedSku = (product.skus || []).find(sku => sku.part_number === sel.sku) || {};
  const mode = _pickerOuterEdgeMode(selectedSku);
  const saved = restoreFromDraft ? _pickerState.editPart?.picker_config?.outer_edge_pillar : null;
  const secondary = mode === "trio" ? "amber"
    : (saved?.product_id === productId && ["white", "amber"].includes(saved.secondary)
      ? saved.secondary : previous.secondary || "white");
  _pickerState.outerEdge = { active: true, mode, secondary, preview: null, loading: true };
  _pickerOuterEdgeAutoLocation();
  _pickerRenderOuterEdge(); _pickerRenderAccessories();
  await _pickerFetchOuterEdgePreview();
}

async function _pickerFetchOuterEdgePreview() {
  const oe = _pickerState.outerEdge, sel = _pickerState.sel;
  if (!oe.active || !sel?.sku) return;
  oe.loading = true; _pickerRenderOuterEdge();
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&part_number=${encodeURIComponent(sel.sku)}`
      + `&secondary=${encodeURIComponent(oe.secondary)}`;
    oe.preview = await api(`/api/parts-db/outer-edge-pillar-heads?${qs}`);
  } catch (error) {
    console.error("Outer Edge pillar resolve failed:", error);
    oe.preview = { ok: false, error: "request_failed", lines: [], problems: [] };
  }
  oe.loading = false;
  _pickerRenderOuterEdge(); _pickerUpdateFooter();
}

function _pickerRenderOuterEdge() {
  const el = $("picker-outer-edge"); if (!el) return;
  const oe = _pickerState.outerEdge;
  if (!oe.active) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const pill = (value, label) =>
    `<button class="pf-pill${oe.secondary === value ? " active" : ""}" data-oek="secondary" data-oev="${value}">${esc(label)}</button>`;
  let previewHtml = "";
  if (oe.loading) {
    previewHtml = `<div class="pt-preview muted">Resolving the six included IONs…</div>`;
  } else if (oe.preview?.ok) {
    previewHtml = `<div class="pt-preview">${(oe.preview.lines || []).filter(line => line.kind === "head").map(line => {
      const pending = line.pending ? ` <span class="pp-pending">pending QB</span>` : "";
      return `<div class="pt-line"><span class="pt-qty">${line.qty}×</span> <span class="pt-sku">${esc(line.sku)}</span> <span class="pt-role">${esc((line.colors || []).map(color => color.charAt(0).toUpperCase() + color.slice(1)).join("/"))}</span>${pending}</div>`;
    }).join("")}</div>`;
  } else if (oe.preview) {
    const problems = (oe.preview.problems || []).map(problem =>
      problem.reason === "missing_head_sku"
        ? `Need ${esc((problem.colors || []).join("/"))} IONs — that QB SKU is not in the catalog yet.`
        : esc(problem.detail || problem.reason || "Unable to resolve the included IONs")
    ).join("<br>");
    previewHtml = `<div class="pt-preview err">⚠ Can't build this pillar configuration yet:<br>${problems}</div>`;
  }
  const colorChoice = oe.mode === "trio"
    ? `<div class="pf-group"><span class="pf-label">Included ION color</span><span class="pt-lens">Red / Blue / Amber — fixed by the Trio housing</span></div>`
    : `<div class="pf-group"><span class="pf-label">Duo secondary color</span><div class="pf-pills">
        ${pill("white", "White")}${pill("amber", "Amber")}</div>
        <span class="pt-lens">Typical split: 3 Red/${esc(oe.secondary)} + 3 Blue/${esc(oe.secondary)}</span></div>`;
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">⚡</span>Outer Edge pillar IONs<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>
    <div class="pt-rows">
      <div class="pf-group"><span class="pf-label">Assembly</span><span class="pt-lens">${oe.mode === "trio" ? "Trio" : "Duo"} housing · 6 included IONs</span></div>
      ${colorChoice}
    </div>${previewHtml}`;
  el.querySelectorAll("[data-oek]").forEach(button => button.addEventListener("click", () => {
    _pickerState.outerEdge[button.dataset.oek] = button.dataset.oev;
    _pickerFetchOuterEdgePreview();
  }));
}

function _pickerOuterEdgeSatisfied() {
  const oe = _pickerState.outerEdge;
  return !oe.active || !!(oe.preview && oe.preview.ok);
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
  loc.selected = null; loc.textCustom = false; loc.renderLocation = ""; loc.customStage = ""; loc.autoLocation = "";
  loc.customPlacementMode = "vehicle"; loc.customPlacementLayout = "even"; loc.customPlacements = {}; loc.customPlacementAnchors = {}; loc.customHeadSpacing = 0.06;
  loc.name_pattern = ""; loc.base_label = ""; loc.catalog_names = [];
  _pickerState.partDetails = { paMicLocation: "", paMicLocationCustom: "", paMicClip: "", handheldMagMic: null };
  _pickerState.tint = { windows: [], percentage: 20 };
}

function _pickerSelIsFixture() {
  const sel = _pickerState.sel;
  const p = sel && _pickerState.products.find(x => x.product_id === sel.product_id);
  return !!p && !!p.is_fixture;
}

function _pickerFixtureAutoLocation(product) {
  const loc = _pickerState.loc;
  if (!product || _pickerState.editLineId || loc.selected) return;
  // Roof bars keep their dedicated path because they need a sequenced "Light
  // Bar N" render name even though the workbook label is "Roof Light Bar".
  if ((product.fits_part_types || []).includes("roof_light_bar")) return;
  if (!product.is_fixture) return;
  const fixtureLabel = product.fixture_label || product.default_location || "Fixture";
  loc.selected = product.default_location || fixtureLabel;
  loc.name_pattern = product.fixture_name_pattern || fixtureLabel;
  loc.base_label = product.fixture_base_label || fixtureLabel;
  loc.catalog_names = [];
  _pickerUpdateFooter();
}

function _pickerIsConsoleContext() {
  const product = _pickerSelectedProduct();
  // Console setup belongs to the selected product, not the browse path. A
  // Havis/Gamber console can be surfaced by a family header, a broad category,
  // global search, or a visible subleaf and must always bypass placement.
  return !!product && (
    (product.fits_part_types || []).includes("console")
    || product.primary_part_type_id === "console"
  );
}

function _pickerFixedPartLocation() {
  if (_pickerIsConsoleContext()) {
    return {
      location: "IN CENTER CONSOLE",
      namePattern: "Center Console",
      baseLabel: "Center Console",
      catalogNames: ["Center Console"],
    };
  }
  const sel = _pickerState.sel;
  const product = sel && _pickerState.products.find(item => item.product_id === sel.product_id);
  if (!product?.fixed_location) return null;
  return {
    location: product.fixed_location,
    namePattern: product.primary_part_type_label || product.model || "Part",
    baseLabel: product.primary_part_type_label || product.model || "Part",
    catalogNames: [],
  };
}

function _pickerHasFixedPartLocation() {
  return !!_pickerFixedPartLocation();
}

function _pickerApplyFixedPartLocation() {
  const loc = _pickerState.loc;
  const fixed = _pickerFixedPartLocation();
  if (_pickerState.editLineId || loc.selected || !fixed) return;
  loc.selected = fixed.location;
  loc.name_pattern = fixed.namePattern;
  loc.base_label = fixed.baseLabel;
  loc.catalog_names = fixed.catalogNames;
  loc.textCustom = false;
  _pickerUpdateFooter();
}

// ── Center-console setup ────────────────────────────────
// The legacy workbook treated the console as a body plus seven named
// faceplate rows. Keep that useful structure for the physical console layout.
// Armrests, motion attachments, and docks are selected here for convenience,
// but are their own build parts (and therefore their own estimate lines).
const _CONSOLE_CATALOG_PART_TYPES = {
  faceplates: "special_face_plate",
  armRest: "arm_rest",
  motionAttachment: "motion_attachment",
  pedestalMount: "pedestal_mount",
  dockingStation: "docking_station",
  radioMicClip: "radio_mic_clip",
  printer: "printer",
  printerPower: "printer_power",
  printerUsb: "printer_usb",
};

const _CONSOLE_STANDARD_FACEPLATES = {
  "gamber johnson": {
    core: "gamber_johnson_7160_0339", radio: "gamber_johnson_7160_0321",
    cup_holder: "gamber_johnson_7160_0846", oem_relocation_plate: "gamber_johnson_15250",
  },
  havis: {
    core: "havis_c_eb40_ccs_1p", radio: "havis_c_eb25_xtl_1p",
    cup_holder: "havis_cup2_1001", oem_relocation_plate: "havis_factory_component_relocation_plate",
  },
};
const _CONSOLE_STYLE_LABELS = {
  low_profile: "Low-profile", standard_width: "Standard width", wide_body: "Wide body",
  standard: "Standard", short: "Short", angled: "Angled", flat: "Flat", enclosed: "Enclosed",
};

function _pickerNewConsoleSetup(saved = null) {
  const source = saved?.choices || saved || {};
  const copyChoice = value => value && typeof value === "object"
    ? { ...value, ..._pickerSupplyPayload(_pickerSupplyFromRecord(value)) }
    : null;
  const magMicSupply = _pickerSupplyPayload(_pickerSupplyFromRecord(
    source.magMicSupply || { new_or_used: source.magMicCondition || "New" },
  ));
  return {
    active: false, loading: false, catalog: {}, error: "",
    choices: {
      style: source.style || "",
      consoleChoice: copyChoice(source.consoleChoice),
      faceplates: Array.isArray(source.faceplates) ? source.faceplates.map(copyChoice).filter(Boolean) : [],
      armRest: copyChoice(source.armRest),
      motionAttachment: copyChoice(source.motionAttachment),
      motionLocation: source.motionLocation || "mounted_to_console",
      pedestalMount: copyChoice(source.pedestalMount),
      dockingStation: copyChoice(source.dockingStation),
      radioMicClip: copyChoice(source.radioMicClip),
      radioMicClipRelation: source.radioMicClipRelation || "",
      // Without a selected bracket, a saved true value means the user chose a
      // standalone Mag Mic (the Gamber-Johnson flow). Havis retains its
      // bracket-plus-Mag-Mic behavior after a bracket is selected.
      addMagMic: source.radioMicClip ? source.addMagMic !== false : source.addMagMic === true,
      magMicSupply,
      magMicCondition: magMicSupply.new_or_used,
      // A printer armrest is designed around a PocketJet.  Ask explicitly so
      // a shop can still record an armrest-only build, but start from the
      // usual installation: include the printer and then choose its cables.
      addPrinter: source.addPrinter !== false,
      printer: copyChoice(source.printer),
      printerPower: copyChoice(source.printerPower),
      printerUsb: copyChoice(source.printerUsb),
      wings: copyChoice(source.wings),
    },
    faceplateSearch: "", openComponent: "",
  };
}

function _pickerConsoleChoiceFromProduct(product, autoFor = "") {
  if (!product) return null;
  const skus = product.skus || [];
  const vehicle = _pickerVehicle();
  const sku = skus.find(item => _skuCompatible(item, vehicle)) || (!vehicle ? skus[0] : null);
  if (!sku?.part_number) return null;
  return {
    product_id: product.product_id,
    model: product.model || product.product_id,
    manufacturer_label: product.manufacturer_label || "",
    part_number: sku.part_number,
    price: sku.price ?? null,
    ..._pickerSupplyPayload({ supplyType: "new", customerCondition: "", customerSource: "" }),
    ...(autoFor ? { auto_for: autoFor } : {}),
  };
}

function _pickerConsoleBrand() {
  const selected = _pickerState.sel;
  if (selected?.mfr) return selected.mfr;
  const configured = _pickerState.consoleSetup?.choices?.consoleChoice;
  if (configured?.manufacturer_label) return configured.manufacturer_label;
  if (_pickerState.filters.brand) return _pickerState.filters.brand;
  return (_pickerState.products || []).find(product => product.product_id === selected?.product_id)?.manufacturer_label || "";
}

function _pickerConsoleStyleForProduct(product) {
  const configured = product?.console_kit?.style;
  if (configured) return configured;
  const model = String(product?.model || "").toLowerCase();
  if (/low[ -]?profile/.test(model)) return "low_profile";
  if (/wide.?body|wide.?width|\bvsw\b|\bvsx\b/.test(model)) return "wide_body";
  if (/standard/.test(model)) return "standard";
  if (/short/.test(model)) return "short";
  if (/angled/.test(model)) return "angled";
  if (/flat/.test(model)) return "flat";
  if (/enclosed/.test(model)) return "enclosed";
  return product?.product_id || "other";
}

function _pickerConsoleStyleLabel(style) {
  return _CONSOLE_STYLE_LABELS[style] || String(style || "Other console").replace(/_/g, " ");
}

function _pickerConsoleCatalogProducts(setup) {
  const brand = _pickerConsoleBrand().toLowerCase();
  return (setup.catalog.consoles || []).filter(product =>
    _pickerConsoleHasCompatibleSku(product)
    && (!brand || String(product.manufacturer_label || "").toLowerCase() === brand)
  );
}

function _pickerConsoleProductById(setup, productId) {
  return [...(setup.catalog.consoles || []), ...(setup.catalog.faceplates || [])]
    .find(product => product.product_id === productId) || null;
}

function _pickerConsoleIncludedFeatures(setup) {
  const choice = setup.choices.consoleChoice;
  const product = _pickerConsoleProductById(setup, choice?.product_id);
  return product?.console_kit?.included || {};
}

function _pickerConsoleFeatureRole(choice, kind) {
  if (!choice) return "";
  const model = String(choice.model || "").toLowerCase();
  if (kind === "armrest") {
    if (/printer/.test(model)) return "printer";
    if (/rear/.test(model)) return "rear";
    if (/side/.test(model)) return "side";
    return "standard";
  }
  return /mongoose|slide/.test(model) ? "mongoose" : "motion";
}

function _pickerConsoleKitMatchesFeature(included, wanted) {
  if (!included || !wanted) return false;
  return included === wanted || included === "any";
}

function _pickerResolveConsoleKit(setup) {
  const style = setup.choices.style;
  if (!style) return null;
  // Gamber-Johnson's current console_kit fields describe bundled order
  // contents, not cutout geometry. Neither customer-supplied condition may
  // therefore select a kit that bills another copy of that accessory.
  const armSupply = _pickerSupplyFromRecord(setup.choices.armRest || {});
  const motionSupply = _pickerSupplyFromRecord(setup.choices.motionAttachment || {});
  const wantedArmrest = armSupply.supplyType === "customer_supplied"
    ? "" : _pickerConsoleFeatureRole(setup.choices.armRest, "armrest");
  const wantedMotion = motionSupply.supplyType === "customer_supplied"
    ? "" : _pickerConsoleFeatureRole(setup.choices.motionAttachment, "motion");
  const candidates = _pickerConsoleCatalogProducts(setup).filter(product => _pickerConsoleStyleForProduct(product) === style);
  const eligible = candidates.filter(product => {
    const included = product.console_kit?.included || {};
    return !(included.armrest && !_pickerConsoleKitMatchesFeature(included.armrest, wantedArmrest))
      && !(included.motion_attachment && !_pickerConsoleKitMatchesFeature(included.motion_attachment, wantedMotion));
  });
  const rank = product => {
    const included = product.console_kit?.included || {};
    let score = 0;
    if (included.armrest && _pickerConsoleKitMatchesFeature(included.armrest, wantedArmrest)) score += 4;
    if (included.motion_attachment && _pickerConsoleKitMatchesFeature(included.motion_attachment, wantedMotion)) score += 4;
    if (product.console_kit) score += 1;
    if (/discontinued/i.test(String(product.model || ""))) score -= 10;
    return score;
  };
  const product = [...eligible].sort((a, b) => rank(b) - rank(a) || String(a.model || "").localeCompare(String(b.model || "")))[0] || null;
  const choice = _pickerConsoleChoiceFromProduct(product);
  if (!choice) return null;
  // Resolving a better-fitting kit swaps only the catalog identity. Supply is
  // a user decision and must survive a kit re-resolution unchanged.
  Object.assign(choice, _pickerSupplyPayload(_pickerSupplyFromRecord(setup.choices.consoleChoice || {})));
  setup.choices.consoleChoice = choice;
  _pickerState.sel = { product_id: choice.product_id, model: choice.model, mfr: choice.manufacturer_label, sku: choice.part_number };
  return choice;
}

function _pickerConsoleFaceplateChoice(setup, kind, { included = false, required = false } = {}) {
  const brand = _pickerConsoleBrand().toLowerCase();
  const productId = _CONSOLE_STANDARD_FACEPLATES[brand]?.[kind] || "";
  const choice = _pickerConsoleChoiceFromProduct(_pickerConsoleProductById(setup, productId));
  if (!choice) return null;
  const labels = {
    core: "Core Control Head Faceplate", radio: "Radio Faceplate",
    cup_holder: "Cup Holder Faceplate", oem_relocation_plate: "OEM Relocation Plate",
  };
  const noCharge = brand === "gamber johnson" && ["core", "radio"].includes(kind);
  return { ...choice, model: labels[kind] || choice.model, auto_kind: kind, kit_included: included, required,
    no_charge_faceplate: noCharge };
}

function _pickerConsoleSyncFaceplates(setup) {
  if (!setup.choices.consoleChoice) return;
  const included = _pickerConsoleIncludedFeatures(setup);
  const automatic = [
    _pickerConsoleFaceplateChoice(setup, "core", { required: true }),
    _pickerConsoleFaceplateChoice(setup, "radio", { required: true }),
    ...(included.cup_holder ? [_pickerConsoleFaceplateChoice(setup, "cup_holder", { included: true, required: true })] : []),
    ...(included.oem_relocation_plate ? [_pickerConsoleFaceplateChoice(setup, "oem_relocation_plate", { included: true, required: true })] : []),
  ].filter(Boolean);
  const automaticIds = new Set(automatic.map(choice => choice.product_id));
  const extras = (setup.choices.faceplates || []).filter(choice => !choice.auto_kind && !automaticIds.has(choice.product_id));
  const priorSupply = new Map((setup.choices.faceplates || []).map(choice => [choice.product_id, _pickerSupplyPayload(_pickerSupplyFromRecord(choice))]));
  setup.choices.faceplates = [...automatic, ...extras].map(choice => ({
    ...choice,
    ...(priorSupply.get(choice.product_id) || _pickerSupplyPayload(_pickerSupplyFromRecord(choice))),
  }));
}

function _pickerConsoleHasCompatibleSku(product) {
  return !!_pickerConsoleChoiceFromProduct(product);
}

function _pickerConsoleHasLiveCompatibleSku(product) {
  const vehicle = _pickerVehicle();
  return (product?.skus || []).some(sku =>
    !!sku.part_number && !!sku.qb && _skuCompatible(sku, vehicle)
  );
}

function _pickerConsoleFaceplateProducts(setup) {
  const brand = _pickerConsoleBrand().toLowerCase();
  return (setup.catalog.faceplates || []).filter(product =>
    _pickerConsoleHasCompatibleSku(product)
    && (!brand || String(product.manufacturer_label || "").toLowerCase() === brand)
    // Havis's legacy migration contains generic placeholder "part numbers"
    // alongside real inventory. The console faceplate chooser must offer only
    // genuine Havis, QB-linked SKUs — not a text stand-in or another maker's
    // equipment bracket.
    && (brand !== "havis" || (
      String(product.manufacturer_id || "").toLowerCase() === "havis"
      && _pickerConsoleHasLiveCompatibleSku(product)
    ))
  );
}

function _pickerConsoleWingProducts(setup) {
  return _pickerConsoleFaceplateProducts(setup).filter(product => /\bwings?\b/i.test(String(product.model || "")));
}

function _pickerConsoleProductsForKey(setup, key) {
  if (key === "wings") return _pickerConsoleWingProducts(setup);
  const products = (setup.catalog[key] || []).filter(_pickerConsoleHasCompatibleSku);
  // Printers and their cables are Brother catalog parts, not Havis/Gamber
  // console parts.  Cables remain tied to the selected printer through the
  // catalog's explicit accessory relationship rather than a fragile name or
  // manufacturer match.
  if (key === "printer") return products;
  if (["printerPower", "printerUsb"].includes(key)) {
    const printerId = setup.choices.printer?.product_id;
    return printerId
      ? products.filter(product => (product.accessory_of_products || []).includes(printerId))
      : [];
  }
  const brand = _pickerConsoleBrand().toLowerCase();
  return products.filter(product =>
    !brand || String(product.manufacturer_label || "").toLowerCase() === brand
  );
}

async function _pickerBeginConsoleSetup(saved = null) {
  if (!_pickerIsConsoleContext()) return;
  _pickerApplyFixedPartLocation();
  const setup = _pickerNewConsoleSetup(saved || _pickerState.editPart?.picker_config?.console_setup);
  setup.active = true;
  setup.loading = true;
  _pickerState.consoleSetup = setup;
  _pickerSwitchTab("location");
  try {
    const [loaded, consoles] = await Promise.all([
      Promise.all(Object.entries(_CONSOLE_CATALOG_PART_TYPES).map(async ([key, partType]) => {
        const accessoryLinks = ["printerPower", "printerUsb"].includes(key)
          ? "&include_accessory_links=1"
          : "";
        const response = await api(`/api/parts-db/category-skus?type=equipment&part_type=${encodeURIComponent(partType)}${accessoryLinks}`);
        return [key, response?.products || []];
      })),
      api("/api/parts-db/category-skus?type=structural&part_type=console"),
    ]);
    setup.catalog = { ...Object.fromEntries(loaded), consoles: consoles?.products || [] };
    const selectedProduct = _pickerState.sel
      ? _pickerConsoleProductById(setup, _pickerState.sel.product_id) : null;
    if (!setup.choices.consoleChoice && selectedProduct) {
      setup.choices.consoleChoice = _pickerConsoleChoiceFromProduct(selectedProduct);
    }
    if (!setup.choices.style && setup.choices.consoleChoice) {
      setup.choices.style = _pickerConsoleStyleForProduct(
        _pickerConsoleProductById(setup, setup.choices.consoleChoice.product_id),
      );
    }
    if (setup.choices.style) _pickerResolveConsoleKit(setup);
    _pickerConsoleSyncFaceplates(setup);
  } catch (error) {
    console.error("console setup catalog load failed:", error);
    setup.error = "Could not load the console component catalog.";
  }
  setup.loading = false;
  _pickerRenderConsoleSetup();
  _pickerUpdateFooter();
}

function _pickerConsoleChoiceLabel(choice) {
  if (!choice) return "Not included";
  return [choice.manufacturer_label, choice.model].filter(Boolean).join(" · ") || choice.part_number || "Selected";
}

function _pickerConsoleFaceplateCards(setup) {
  const query = String(setup.faceplateSearch || "").trim().toLowerCase();
  const all = _pickerConsoleFaceplateProducts(setup)
    .filter(product => !/\bwings?\b/i.test(String(product.model || "")))
    .sort((a, b) => String(a.model || "").localeCompare(String(b.model || "")));
  const matching = query
    ? all.filter(product => [product.model, product.manufacturer_label, ...(product.skus || []).map(sku => sku.part_number)].join(" ").toLowerCase().includes(query))
    : all;
  const selected = new Set((setup.choices.faceplates || []).map(item => item.product_id));
  const cards = matching.map(product => {
    const choice = _pickerConsoleChoiceFromProduct(product);
    if (!choice) return "";
    const isAdded = selected.has(product.product_id);
    const price = choice.price != null ? ` · ${_pickerRetailPrice(choice.price)}` : "";
    return `<button type="button" class="console-catalog-card${isAdded ? " is-added" : ""}" data-console-faceplate-add="${esc(product.product_id)}"${isAdded ? " disabled" : ""}>`
      + `<span class="console-catalog-card-brand">${esc(choice.manufacturer_label || "Faceplate")}</span><strong>${esc(product.model || "Faceplate")}</strong>`
      + `<small>${esc(choice.part_number)}${price}${isAdded ? " · added" : ""}</small></button>`;
  }).join("");
  return `<div class="console-faceplate-catalog">${cards || `<div class="console-empty">No matching faceplates are available.</div>`}</div>`;
}

function _pickerConsoleStyleCards(setup) {
  const byStyle = new Map();
  for (const product of _pickerConsoleCatalogProducts(setup)) {
    const style = _pickerConsoleStyleForProduct(product);
    const list = byStyle.get(style) || [];
    list.push(product);
    byStyle.set(style, list);
  }
  return [...byStyle.entries()].sort(([a], [b]) => _pickerConsoleStyleLabel(a).localeCompare(_pickerConsoleStyleLabel(b)))
    .map(([style, products]) => {
      const selected = setup.choices.style === style;
      const kitCount = products.filter(product => product.console_kit).length;
      return `<button type="button" class="console-catalog-card console-style-card${selected ? " is-added" : ""}" data-console-style="${esc(style)}">
        <span class="console-catalog-card-brand">${kitCount ? `${kitCount} compatible kit${kitCount === 1 ? "" : "s"}` : "Compatible console"}</span>
        <strong>${esc(_pickerConsoleStyleLabel(style))}</strong>
        <small>${esc(products.length === 1 ? products[0].model : `${products.length} compatible console kits`)}</small>
      </button>`;
    }).join("") || `<div class="console-empty">No compatible console kits are available for this vehicle and preferred brand.</div>`;
}

function _pickerConsoleOrderCards(setup) {
  const faceplates = setup.choices.faceplates || [];
  if (!faceplates.length) return `<div class="console-order-empty">Add the faceplates the console needs, then drag them into shop order.</div>`;
  return faceplates.map((choice, index) => `<article class="console-faceplate-order-card" draggable="true" data-console-faceplate-index="${index}">
    <span class="console-drag-handle" title="Drag to reorder">⠿</span><span class="console-faceplate-number">${index + 1}</span>
    <div class="console-faceplate-copy"><strong>Face Plate ${index + 1} · ${esc(choice.model || choice.part_number)}</strong><small>${esc(choice.manufacturer_label || "")} · ${esc(choice.part_number || "")}${choice.no_charge_faceplate ? " · included at no charge" : ""}${choice.auto_for ? ` · auto-added for ${esc(choice.auto_for)}` : ""}</small>${_pickerConsoleConditionHtml(choice, { faceplateIndex: index })}</div>
    <div class="console-faceplate-actions"><button type="button" class="console-order-move" data-console-faceplate-move="-1" data-console-faceplate-index="${index}" title="Move up"${index === 0 ? " disabled" : ""}>↑</button><button type="button" class="console-order-move" data-console-faceplate-move="1" data-console-faceplate-index="${index}" title="Move down"${index === faceplates.length - 1 ? " disabled" : ""}>↓</button>${choice.required ? `<span class="console-order-included">Required</span>` : `<button type="button" class="console-order-remove" data-console-faceplate-remove="${index}" title="Remove faceplate">×</button>`}</div>
  </article>`).join("");
}

function _pickerConsoleConditionHtml(choice, { key = "", faceplateIndex = null, magMic = false } = {}) {
  if (!choice && !magMic) return "";
  const record = magMic ? _pickerState.consoleSetup?.choices?.magMicSupply : choice;
  const supply = _pickerSupplyFromRecord(record || { new_or_used: _pickerState.consoleSetup?.choices?.magMicCondition || "New" });
  const current = supply.supplyType === "new" ? "new" : `customer_${supply.customerCondition || "used"}`;
  const attrs = faceplateIndex !== null
    ? `data-console-condition-faceplate="${faceplateIndex}"`
    : magMic ? "data-console-condition-mag-mic" : `data-console-condition-key="${esc(key)}"`;
  const options = [["new", "New"], ["customer_new", "Customer supplied / New"], ["customer_used", "Customer supplied / Used"]];
  return `<div class="console-part-condition"><span>Supply</span>${options.map(([value, label]) =>
    `<button type="button" class="console-location-choice${current === value ? " is-selected" : ""}" ${attrs} data-console-condition-value="${value}">${label}</button>`
  ).join("")}${current === "customer_used" ? `<label class="console-used-source"><span>Used-part source <b>*</b></span><input type="text" ${attrs} data-console-condition-source value="${esc(supply.customerSource || "")}" placeholder="Agency, old vehicle, customer stock…"></label>` : ""}</div>`;
}

function _pickerConsoleComponentSection(
  setup, key, label, help, catalogProducts = null,
  { required = false, requiredKicker = "", requiredPlaceholder = "" } = {},
) {
  const choice = setup.choices[key];
  const isOpen = setup.openComponent === key;
  const products = [...(catalogProducts || _pickerConsoleProductsForKey(setup, key))]
    .sort((a, b) => String(a.model || "").localeCompare(String(b.model || "")));
  const noneCard = required ? "" : `<button type="button" class="console-catalog-card console-catalog-card--none${!choice ? " is-added" : ""}" data-console-component-choice="" data-console-component-key="${esc(key)}"><strong>None</strong><small>Do not include this console component</small></button>`;
  const picker = !isOpen ? "" : `<div class="console-component-picker">${noneCard}${products.map(product => {
    const item = _pickerConsoleChoiceFromProduct(product);
    if (!item) return "";
    const selected = choice?.product_id === product.product_id && choice?.part_number === item.part_number;
    return `<button type="button" class="console-catalog-card${selected ? " is-added" : ""}" data-console-component-choice="${esc(product.product_id)}" data-console-component-key="${esc(key)}"><span class="console-catalog-card-brand">${esc(item.manufacturer_label || label)}</span><strong>${esc(product.model || product.product_id)}</strong><small>${esc(item.part_number)}${item.price != null ? ` · ${_pickerRetailPrice(item.price)}` : ""}</small></button>`;
  }).join("")}</div>`;
  const motionLocation = key === "motionAttachment" && choice ? `<div class="console-motion-location"><span>Mounting location</span><div><button type="button" class="console-location-choice${setup.choices.motionLocation === "mounted_to_console" ? " is-selected" : ""}" data-console-motion-location="mounted_to_console">Mounted to console</button><button type="button" class="console-location-choice${setup.choices.motionLocation === "mounted_to_pedestal" ? " is-selected" : ""}" data-console-motion-location="mounted_to_pedestal">Mounted to pedestal</button></div></div>` : "";
  const selectedLabel = choice ? _pickerConsoleChoiceLabel(choice)
    : required ? (requiredPlaceholder || `Choose ${String(label || "component").toLowerCase()}`) : "Not included";
  const sectionKicker = required
    ? (requiredKicker || "Required console component")
    : "Optional console component";
  return `<section class="console-component-section"><div class="console-component-summary"><div><div class="console-section-kicker">${esc(sectionKicker)}</div><h3>${esc(label)}</h3><p>${esc(help)}</p></div><button type="button" class="console-component-current" data-console-component-open="${esc(key)}"><strong>${esc(selectedLabel)}</strong><span>${isOpen ? "Close choices" : choice ? "Change" : "Choose"}</span></button></div>${picker}${choice ? _pickerConsoleConditionHtml(choice, { key }) : ""}${motionLocation}</section>`;
}

function _pickerConsolePedestalRequired(setup = _pickerState.consoleSetup) {
  const choices = setup?.choices || {};
  return !!choices.motionAttachment && choices.motionLocation === "mounted_to_pedestal";
}

function _pickerConsoleSupplySatisfied(setup = _pickerState.consoleSetup) {
  const choices = setup?.choices || {};
  const records = [
    choices.consoleChoice, ...(choices.faceplates || []), choices.armRest,
    choices.motionAttachment, choices.pedestalMount, choices.dockingStation,
    choices.radioMicClip, choices.printer, choices.printerPower, choices.printerUsb,
    choices.wings,
    ...(choices.addMagMic === true ? [choices.magMicSupply || { new_or_used: choices.magMicCondition }] : []),
  ].filter(Boolean);
  return records.every(record => _pickerSupplySatisfied(_pickerSupplyFromRecord(record)));
}

function _pickerConsolePedestalLocation(choice) {
  const model = String(choice?.model || "").toLowerCase();
  if (model.includes("tunnel")) return "TUNNEL MOUNT";
  if (model.includes("side mount")) return "SIDE OF CONSOLE";
  return "FLOOR PEDESTAL";
}

function _pickerExistingConsoleRadioMicClip() {
  const parts = (typeof _meDraft !== "undefined" && _meDraft?.parts) || [];
  return parts.find(part =>
    part.part_type === "radio_mic_clip"
    && part.picker_config?.console_component_key === "radioMicClip"
  ) || null;
}

function _pickerExistingRadioSystem() {
  const parts = (typeof _meDraft !== "undefined" && _meDraft?.parts) || [];
  return parts.find(part => part.picker_config?.system_type === "radio") || null;
}

function _pickerConsoleRadioMicRelationRequired(setup = _pickerState.consoleSetup) {
  return !!setup?.choices?.radioMicClip && !!_pickerExistingRadioSystem();
}

function _pickerConsoleRadioMicReconciliationQuestion(setup) {
  if (!_pickerConsoleRadioMicRelationRequired(setup)) return "";
  const relation = setup.choices.radioMicClipRelation;
  return `<div class="console-motion-location"><span>A radio setup already includes a microphone mount. Is this the same clip?</span><div><button type="button" class="console-location-choice${relation === "use_for_existing_radio" ? " is-selected" : ""}" data-console-radio-mic-relation="use_for_existing_radio">Yes — use this console clip for that radio</button><button type="button" class="console-location-choice${relation === "additional_console_clip" ? " is-selected" : ""}" data-console-radio-mic-relation="additional_console_clip">No — this is an additional mic clip</button></div></div>`;
}

function _pickerConsoleMagMicQuestion(setup) {
  const gamber = _pickerConsoleBrand().toLowerCase() === "gamber johnson";
  if (gamber) {
    const bracket = !!setup?.choices?.radioMicClip;
    const magMic = !bracket && setup?.choices?.addMagMic === true;
    return `<div class="console-motion-location"><span>Choose one microphone mount option</span><div>`
      + `<button type="button" class="console-location-choice${bracket ? " is-selected" : ""}" data-console-mic-hardware="bracket"${bracket ? "" : " disabled"}>${bracket ? "Use selected mic clip bracket" : "Choose a bracket above"}</button>`
      + `<button type="button" class="console-location-choice${magMic ? " is-selected" : ""}" data-console-mic-hardware="mag_mic">Use Mag Mic instead</button>`
      + `<button type="button" class="console-location-choice${!bracket && !magMic ? " is-selected" : ""}" data-console-mic-hardware="none">No mic hardware</button>`
      + `</div><small>The available Gamber-Johnson bracket does not support a Mag Mic, so the bracket and Mag Mic cannot be added together.</small>${magMic ? _pickerConsoleConditionHtml(null, { magMic: true }) : ""}</div>`;
  }
  if (!setup?.choices?.radioMicClip) return "";
  const addMagMic = setup.choices.addMagMic !== false;
  return `<div class="console-motion-location"><span>Add a Mag Mic with this clip?</span><div><button type="button" class="console-location-choice${addMagMic ? " is-selected" : ""}" data-console-add-mag-mic="yes">Yes — add Mag Mic</button><button type="button" class="console-location-choice${!addMagMic ? " is-selected" : ""}" data-console-add-mag-mic="no">No Mag Mic</button></div>${addMagMic ? _pickerConsoleConditionHtml(null, { magMic: true }) : ""}</div>`;
}

function _pickerConsoleHasPrinterArmrest(setup) {
  return _pickerConsoleFeatureRole(setup?.choices?.armRest, "armrest") === "printer";
}

function _pickerConsolePrinterRequired(setup = _pickerState.consoleSetup) {
  return _pickerConsoleHasPrinterArmrest(setup) && setup?.choices?.addPrinter !== false;
}

function _pickerConsoleClearPrinterChoices(setup) {
  setup.choices.printer = null;
  setup.choices.printerPower = null;
  setup.choices.printerUsb = null;
}

function _pickerConsolePrinterFlow(setup) {
  if (!_pickerConsoleHasPrinterArmrest(setup)) return "";
  const addPrinter = setup.choices.addPrinter !== false;
  const printerSection = addPrinter
    ? _pickerConsoleComponentSection(
      setup, "printer", "Printer",
      "Choose the PocketJet printer that mounts in this armrest.", null,
      { required: true, requiredKicker: "Required when adding a printer", requiredPlaceholder: "Choose a printer" },
    )
    : "";
  const accessorySection = addPrinter && setup.choices.printer
    ? `<div class="console-printer-accessories"><div class="console-section-kicker">Optional printer accessories</div><h3>Printer cables</h3><p>Choose the cables needed for this printer installation.</p></div>${_pickerConsoleComponentSection(setup, "printerPower", "Printer power cable", "Optional power cable matched to the selected printer.")}${_pickerConsoleComponentSection(setup, "printerUsb", "Printer USB cable", "Optional USB cable matched to the selected printer.")}`
    : "";
  return `<section class="console-printer-prompt"><div><div class="console-section-kicker">Printer armrest selected</div><h3>Add a printer with this armrest?</h3><p>The armrest can be listed by itself, or with its PocketJet printer and any needed cables.</p></div><div class="console-motion-location"><div><button type="button" class="console-location-choice${addPrinter ? " is-selected" : ""}" data-console-add-printer="yes">Yes — add printer</button><button type="button" class="console-location-choice${!addPrinter ? " is-selected" : ""}" data-console-add-printer="no">No printer</button></div></div></section>${printerSection}${accessorySection}`;
}

function _pickerConsoleMagMicChoice() {
  const item = _MAGNETIC_MIC_ITEMS.magnetic_mic;
  return item ? {
    product_id: "magnetic_mic_mmsu_1",
    model: item.model,
    manufacturer_label: item.manufacturer,
    part_number: item.part_number,
  } : null;
}

function _pickerRenderConsoleSetup() {
  const setup = _pickerState.consoleSetup || {};
  if (!setup.active) return;
  const locationContent = $("picker-location-content");
  const details = $("picker-system-details");
  if (_pickerState.tab !== "location") {
    if (details) { details.hidden = true; details.innerHTML = ""; }
    if (locationContent) locationContent.hidden = false;
    return;
  }
  if (locationContent) locationContent.hidden = true;
  if (!details) return;
  details.hidden = false;
  if (setup.loading) {
    details.innerHTML = `<section class="console-setup"><div class="console-setup-header"><span class="guided-chip">CONSOLE</span><h2>Loading Center Console setup…</h2></div></section>`;
    return;
  }
  const error = setup.error ? `<div class="console-setup-error">${esc(setup.error)}</div>` : "";
  const consoleBrand = _pickerConsoleBrand();
  const faceplateBrandNote = consoleBrand
    ? `<p>Showing only ${esc(consoleBrand)} faceplates so they match the selected console.</p>`
    : "";
  const wingProducts = _pickerConsoleWingProducts(setup);
  const wingSection = wingProducts.length
    ? _pickerConsoleComponentSection(
      setup, "wings", "Console wings",
      "Optional side wings matched to this console brand and vehicle.", wingProducts,
    )
    : "";
  const pedestalSection = _pickerConsolePedestalRequired(setup)
    ? _pickerConsoleComponentSection(
      setup, "pedestalMount", "Pedestal / mount base",
      "Choose the Havis pedestal or vehicle-specific mount that supports this motion attachment.",
      null, {
        required: true,
        requiredKicker: "Required for pedestal-mounted motion attachment",
        requiredPlaceholder: "Choose a pedestal / mount base",
      },
    )
    : "";
  const micClipSection = _pickerConsoleComponentSection(
    setup, "radioMicClip", "Radio mic clip bracket",
    "Choose a mic clip bracket matched to this console's manufacturer, if needed.",
  );
  const printerFlow = _pickerConsolePrinterFlow(setup);
  const selectedKit = setup.choices.consoleChoice;
  const included = _pickerConsoleIncludedFeatures(setup);
  const kitSummary = selectedKit
    ? `<div class="console-kit-summary"><strong>Selected kit: ${esc(_pickerConsoleChoiceLabel(selectedKit))}</strong><span>${Object.keys(included).length ? `Includes ${esc(Object.keys(included).map(key => ({ cup_holder: "cup holder faceplate", oem_relocation_plate: "OEM relocation plate", armrest: "armrest", motion_attachment: "motion attachment" }[key] || key.replace(/_/g, " "))).join(", "))}. Included items stay on the shop manifest but are not billed separately.` : "This kit has no recorded included add-ons."}</span>${_pickerConsoleConditionHtml(selectedKit, { key: "consoleChoice" })}</div>`
    : `<div class="console-kit-summary console-kit-summary--empty">Choose a console style to match a compatible kit from QuickBooks.</div>`;
  details.innerHTML = `<section class="console-setup" data-console-setup>
    <header class="console-setup-header"><div><span class="guided-chip">CONSOLE</span><h2>Build a Center Console Kit</h2><p>Choose the console style and needed features. The picker selects the matching kit and bills only hardware that is not already included with it.</p></div><button class="guided-close" type="button" onclick="_pickerClearSelection()" title="Close">✕</button></header>${error}
    <section class="console-faceplate-section"><div class="console-section-heading"><div><div class="console-section-kicker">1 · Choose a style</div><h3>Which style of console fits this build?</h3><p>Only vehicle-compatible ${esc(consoleBrand || "preferred-brand")} console kits are shown.</p></div></div><div class="console-faceplate-catalog console-style-catalog">${_pickerConsoleStyleCards(setup)}</div>${kitSummary}</section>
    <section class="console-components-section"><div class="console-section-heading"><div><div class="console-section-kicker">2 · Choose features</div><h3>What should the kit include?</h3><p>We select the kit that already contains these pieces when possible. A dock or other hardware that is not part of a kit is added and billed separately.</p></div></div>${_pickerConsoleComponentSection(setup, "armRest", "Armrest", "Choose an armrest, if this console needs one.")}${printerFlow}${_pickerConsoleComponentSection(setup, "motionAttachment", "Motion attachment", "Choose a motion device, if this console needs one.")}${pedestalSection}${_pickerConsoleComponentSection(setup, "dockingStation", "Docking station", "Choose the computer dock or cradle that belongs on this console.")}${micClipSection}${_pickerConsoleRadioMicReconciliationQuestion(setup)}${_pickerConsoleMagMicQuestion(setup)}</section>
    <section class="console-faceplate-section console-faceplate-section--order"><div class="console-section-heading"><div><div class="console-section-kicker">3 · Plan the faceplate lineup</div><h3>Core and radio faceplates are always stocked</h3><p>Every console receives a Core and radio faceplate. Vehicle-specific kits also include their OEM relocation plate and, when listed, a cupholder faceplate. Drag rows to give the shop the install order.</p>${faceplateBrandNote}</div><label class="console-faceplate-search"><span>Add another faceplate</span><input id="picker-console-faceplate-search" value="${esc(setup.faceplateSearch || "")}" placeholder="Search optional faceplates, pockets…"></label></div><div class="console-faceplate-order" id="picker-console-faceplate-order">${_pickerConsoleOrderCards(setup)}</div><div class="console-extra-faceplates">${_pickerConsoleFaceplateCards(setup)}</div></section>
    ${wingSection ? `<section class="console-components-section"><div class="console-section-heading"><div><div class="console-section-kicker">Optional vehicle fitment</div><h3>Console wings</h3><p>Choose vehicle-specific side wings only when the build needs them.</p></div></div>${wingSection}</section>` : ""}
  </section>`;

  details.querySelectorAll("[data-console-style]").forEach(button => button.addEventListener("click", () => {
    setup.choices.style = button.dataset.consoleStyle;
    _pickerResolveConsoleKit(setup);
    _pickerConsoleSyncFaceplates(setup);
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));

  details.querySelector("#picker-console-faceplate-search")?.addEventListener("input", event => {
    setup.faceplateSearch = event.target.value;
    _pickerRenderConsoleSetup();
  });
  details.querySelectorAll("[data-console-faceplate-add]").forEach(button => button.addEventListener("click", () => {
    const product = _pickerConsoleFaceplateProducts(setup).find(item => item.product_id === button.dataset.consoleFaceplateAdd);
    const choice = _pickerConsoleChoiceFromProduct(product);
    if (choice && !setup.choices.faceplates.some(item => item.product_id === choice.product_id)) setup.choices.faceplates.push(choice);
    _pickerRenderConsoleSetup();
  }));
  details.querySelectorAll("[data-console-faceplate-remove]").forEach(button => button.addEventListener("click", () => {
    setup.choices.faceplates.splice(Number(button.dataset.consoleFaceplateRemove), 1);
    _pickerRenderConsoleSetup();
  }));
  details.querySelectorAll("[data-console-faceplate-move]").forEach(button => button.addEventListener("click", () => {
    const from = Number(button.dataset.consoleFaceplateIndex), to = from + Number(button.dataset.consoleFaceplateMove);
    if (to < 0 || to >= setup.choices.faceplates.length) return;
    const [choice] = setup.choices.faceplates.splice(from, 1);
    setup.choices.faceplates.splice(to, 0, choice);
    _pickerRenderConsoleSetup();
  }));
  details.querySelectorAll("[data-console-faceplate-index]").forEach(card => {
    card.addEventListener("dragstart", event => {
      event.dataTransfer?.setData("text/plain", card.dataset.consoleFaceplateIndex || "");
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
      card.classList.add("is-dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("is-dragging"));
    card.addEventListener("dragover", event => { event.preventDefault(); card.classList.add("is-drag-target"); });
    card.addEventListener("dragleave", () => card.classList.remove("is-drag-target"));
    card.addEventListener("drop", event => {
      event.preventDefault();
      const from = Number(event.dataTransfer?.getData("text/plain"));
      const to = Number(card.dataset.consoleFaceplateIndex);
      card.classList.remove("is-drag-target");
      if (!Number.isInteger(from) || from === to || from < 0 || from >= setup.choices.faceplates.length) return;
      const [choice] = setup.choices.faceplates.splice(from, 1);
      setup.choices.faceplates.splice(to, 0, choice);
      _pickerRenderConsoleSetup();
    });
  });
  details.querySelectorAll("[data-console-component-open]").forEach(button => button.addEventListener("click", () => {
    setup.openComponent = setup.openComponent === button.dataset.consoleComponentOpen ? "" : button.dataset.consoleComponentOpen;
    _pickerRenderConsoleSetup();
  }));
  details.querySelectorAll("[data-console-component-choice]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.consoleComponentKey;
    const product = _pickerConsoleProductsForKey(setup, key).find(item => item.product_id === button.dataset.consoleComponentChoice);
    setup.choices[key] = _pickerConsoleChoiceFromProduct(product);
    if (key === "motionAttachment" && !setup.choices.motionAttachment) {
      setup.choices.motionLocation = "mounted_to_console";
      setup.choices.pedestalMount = null;
    }
    if (key === "radioMicClip") {
      setup.choices.radioMicClipRelation = "";
      if (setup.choices.radioMicClip) {
        setup.choices.addMagMic = _pickerConsoleBrand().toLowerCase() !== "gamber johnson";
      }
    }
    if (key === "armRest" && !_pickerConsoleHasPrinterArmrest(setup)) {
      setup.choices.addPrinter = true;
      _pickerConsoleClearPrinterChoices(setup);
    }
    if (key === "printer" && !setup.choices.printer) _pickerConsoleClearPrinterChoices(setup);
    if (["armRest", "motionAttachment"].includes(key)) {
      _pickerResolveConsoleKit(setup);
      _pickerConsoleSyncFaceplates(setup);
    }
    setup.openComponent = "";
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-condition-value]").forEach(button => button.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    const value = button.dataset.consoleConditionValue;
    const supply = value === "new"
      ? { supplyType: "new", customerCondition: "", customerSource: "" }
      : { supplyType: "customer_supplied", customerCondition: value === "customer_new" ? "new" : "used", customerSource: "" };
    const payload = _pickerSupplyPayload(supply);
    if (button.hasAttribute("data-console-condition-faceplate")) {
      const choice = setup.choices.faceplates[Number(button.dataset.consoleConditionFaceplate)];
      if (choice) Object.assign(choice, payload);
    } else if (button.hasAttribute("data-console-condition-mag-mic")) {
      setup.choices.magMicSupply = payload;
      setup.choices.magMicCondition = payload.new_or_used;
    } else {
      const key = button.dataset.consoleConditionKey;
      if (setup.choices[key]) Object.assign(setup.choices[key], payload);
      if (["armRest", "motionAttachment"].includes(key)) {
        _pickerResolveConsoleKit(setup);
        _pickerConsoleSyncFaceplates(setup);
      }
    }
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-condition-source]").forEach(input => input.addEventListener("input", () => {
    const source = input.value;
    let target = null;
    if (input.hasAttribute("data-console-condition-faceplate")) {
      target = setup.choices.faceplates[Number(input.dataset.consoleConditionFaceplate)];
    } else if (input.hasAttribute("data-console-condition-mag-mic")) {
      target = setup.choices.magMicSupply;
    } else {
      target = setup.choices[input.dataset.consoleConditionKey];
    }
    if (target) { target.customer_source = source; target.source = source; }
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-motion-location]").forEach(button => button.addEventListener("click", () => {
    setup.choices.motionLocation = button.dataset.consoleMotionLocation;
    if (setup.choices.motionLocation !== "mounted_to_pedestal") setup.choices.pedestalMount = null;
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-add-mag-mic]").forEach(button => button.addEventListener("click", () => {
    setup.choices.addMagMic = button.dataset.consoleAddMagMic === "yes";
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-mic-hardware]").forEach(button => button.addEventListener("click", () => {
    const choice = button.dataset.consoleMicHardware;
    if (choice === "mag_mic") {
      setup.choices.radioMicClip = null;
      setup.choices.radioMicClipRelation = "";
      setup.choices.addMagMic = true;
    } else if (choice === "none") {
      setup.choices.radioMicClip = null;
      setup.choices.radioMicClipRelation = "";
      setup.choices.addMagMic = false;
    } else if (choice === "bracket" && setup.choices.radioMicClip) {
      setup.choices.addMagMic = false;
    }
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-radio-mic-relation]").forEach(button => button.addEventListener("click", () => {
    setup.choices.radioMicClipRelation = button.dataset.consoleRadioMicRelation;
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
  details.querySelectorAll("[data-console-add-printer]").forEach(button => button.addEventListener("click", () => {
    setup.choices.addPrinter = button.dataset.consoleAddPrinter === "yes";
    if (!setup.choices.addPrinter) _pickerConsoleClearPrinterChoices(setup);
    _pickerRenderConsoleSetup();
    _pickerUpdateFooter();
  }));
}

function _pickerConsoleSetupSnapshot() {
  const choices = _pickerState.consoleSetup?.choices || {};
  const copy = value => value ? { ...value } : null;
  return {
    style: choices.style || "",
    consoleChoice: copy(choices.consoleChoice),
    faceplates: (choices.faceplates || []).map(item => ({ ...item })),
    armRest: copy(choices.armRest),
    motionAttachment: copy(choices.motionAttachment),
    motionLocation: choices.motionLocation || "mounted_to_console",
    pedestalMount: copy(choices.pedestalMount),
    dockingStation: copy(choices.dockingStation),
    radioMicClip: copy(choices.radioMicClip),
    radioMicClipRelation: choices.radioMicClipRelation || "",
    addMagMic: choices.addMagMic !== false,
    magMicSupply: choices.magMicSupply ? { ...choices.magMicSupply } : _pickerSupplyPayload({ supplyType: "new", customerCondition: "", customerSource: "" }),
    magMicCondition: choices.magMicSupply?.new_or_used || _pickerNormalPartStatus(choices.magMicCondition),
    addPrinter: choices.addPrinter !== false,
    printer: copy(choices.printer),
    printerPower: copy(choices.printerPower),
    printerUsb: copy(choices.printerUsb),
    wings: copy(choices.wings),
  };
}

function _pickerConsoleChildRows(parentLineId, parentName) {
  const choices = _pickerState.consoleSetup?.choices || {};
  const rows = [];
  const add = (name, choice, partType, location, category) => {
    if (!choice?.part_number) return;
    rows.push({ name, location, manufacturer: choice.manufacturer_label || "", part_number: choice.part_number,
      quantity: 1, ..._pickerSupplyPayload(_pickerSupplyFromRecord(choice)), parent_line_id: parentLineId,
      // These are selected build parts, not catalog accessories. Keep the
      // relationship for manifest nesting, but let their normal edit path
      // open the Part Picker instead of an accessory-only chooser.
      accessory_category: category, accessory_parent_product: "", part_type: partType,
      notes: choice.kit_included ? "Included with selected console kit — do not bill separately."
        : choice.no_charge_faceplate ? "Included specialty faceplate — quote at $0.00." : "",
      picker_config: {
        ...(choice.kit_included ? { console_kit_included: true } : {}),
        ...(choice.no_charge_faceplate ? { quote_unit_price_override: 0, quote_note: "Included specialty faceplate — no charge" } : {}),
        console_setup_owner_line_id: parentLineId,
        console_component_key: category,
      } });
  };
  (choices.faceplates || []).forEach((choice, index) => add(`${parentName} · Face Plate ${index + 1} · ${choice.model || choice.part_number}`, choice, "special_face_plate", "IN CENTER CONSOLE", "console_faceplate"));
  add(`${parentName} · Console Wings · ${choices.wings?.model || ""}`.replace(/ · $/, ""), choices.wings, "special_face_plate", "IN CENTER CONSOLE", "console_wings");
  return rows;
}

function _pickerConsoleComponentRows(ownerLineId, ownerName) {
  const choices = _pickerState.consoleSetup?.choices || {};
  const included = _pickerConsoleIncludedFeatures(_pickerState.consoleSetup || { choices, catalog: {} });
  const rows = [];
  const add = (name, choice, partType, location, componentKey) => {
    if (!choice?.part_number) return;
    rows.push({ name: `${ownerName} · ${name}`, location, manufacturer: choice.manufacturer_label || "", part_number: choice.part_number,
      quantity: 1, ..._pickerSupplyPayload(_pickerSupplyFromRecord(choice)), parent_line_id: ownerLineId,
      // These are real, billed console components. Keep them under the
      // console in the manifest while preserving one owner marker so any
      // component edit returns to the unified console setup.
      accessory_category: "console_component", accessory_parent_product: "", part_type: partType,
      picker_config: { console_setup_owner_line_id: ownerLineId, console_component_key: componentKey } });
  };
  if (!_pickerConsoleKitMatchesFeature(included.armrest, _pickerConsoleFeatureRole(choices.armRest, "armrest"))) {
    add("Armrest", choices.armRest, "arm_rest", "IN CENTER CONSOLE", "armRest");
  }
  const motionLocation = choices.motionLocation === "mounted_to_pedestal" ? "MOUNTED TO PEDESTAL" : "MOUNTED TO CONSOLE";
  if (_pickerConsolePedestalRequired()) {
    add("Computer Pedestal / Mount Base", choices.pedestalMount, "pedestal_mount", _pickerConsolePedestalLocation(choices.pedestalMount), "pedestalMount");
  }
  if (!_pickerConsoleKitMatchesFeature(included.motion_attachment, _pickerConsoleFeatureRole(choices.motionAttachment, "motion"))) {
    add("Motion Attachment", choices.motionAttachment, "motion_attachment", motionLocation, "motionAttachment");
  }
  add("Docking Station", choices.dockingStation, "docking_station", "IN CENTER CONSOLE", "dockingStation");
  add("Radio Mic Clip", choices.radioMicClip, "radio_mic_clip", "ON CENTER CONSOLE", "radioMicClip");
  if (choices.addMagMic === true && (
    choices.radioMicClip || _pickerConsoleBrand().toLowerCase() === "gamber johnson"
  )) {
    add("Mag Mic", { ..._pickerConsoleMagMicChoice(), ...(choices.magMicSupply || { new_or_used: choices.magMicCondition }) }, "radio_mic_clip", "ON CENTER CONSOLE", "magneticMic");
  }
  return rows;
}

function _pickerConsolePrinterRow(ownerLineId) {
  const choices = _pickerState.consoleSetup?.choices || {};
  if (_pickerConsolePrinterRequired()) {
    const choice = choices.printer;
    if (choice?.part_number) {
      // A printer has meaningful accessories of its own, so it remains a
      // separate manifest parent instead of becoming a second-level console
      // child (the manifest deliberately has a clear one-level expansion).
      return {
        name: "Printer", location: "PRINTER ARMREST MOUNT", manufacturer: choice.manufacturer_label || "",
        part_number: choice.part_number, quantity: 1, ..._pickerSupplyPayload(_pickerSupplyFromRecord(choice)), part_type: "printer",
        picker_config: { console_setup_owner_line_id: ownerLineId, console_component_key: "printer" },
      };
    }
  }
  return null;
}

function _pickerConsolePrinterCableRows(printerLineId, printerName) {
  const choices = _pickerState.consoleSetup?.choices || {};
  if (!_pickerConsolePrinterRequired()) return [];
  const rows = [];
  const add = (name, choice, partType, category, componentKey) => {
    if (!choice?.part_number) return;
    rows.push({
      name: `${printerName} · ${name}`, location: "PRINTER ARMREST MOUNT",
      manufacturer: choice.manufacturer_label || "", part_number: choice.part_number,
      quantity: 1, ..._pickerSupplyPayload(_pickerSupplyFromRecord(choice)), parent_line_id: printerLineId,
      accessory_category: category, accessory_parent_product: choices.printer?.product_id || "",
      part_type: partType, picker_config: { console_component_key: componentKey },
    });
  };
  add("Power Cable", choices.printerPower, "printer_power", "printer_power_cable", "printerPower");
  add("USB Cable", choices.printerUsb, "printer_usb", "printer_usb_cable", "printerUsb");
  return rows;
}

async function _pickerReplaceConsoleSetupParts(draftId, parentLineId, parentName) {
  const printer = _pickerConsolePrinterRow(parentLineId);
  const existingRadio = _pickerExistingRadioSystem();
  const reusesExistingRadioMicClip = _pickerState.consoleSetup?.choices?.radioMicClipRelation === "use_for_existing_radio";
  const result = await api(`/api/draft/${draftId}/console-setup`, {
    parent_line_id: parentLineId,
    rows: [
      ..._pickerConsoleChildRows(parentLineId, parentName),
      ..._pickerConsoleComponentRows(parentLineId, parentName),
    ],
    printer,
    // The server assigns the printer's fresh line ID before persisting these
    // child rows, so all console-generated entries land in one draft write.
    printer_cables: printer ? _pickerConsolePrinterCableRows("", printer.name) : [],
    ...(reusesExistingRadioMicClip && existingRadio ? {
      radio_reconciliation: { radio_line_id: existingRadio.line_id, use_console_clip: true },
    } : {}),
  });
  if (!result?.ok) throw new Error(result?.error || "could not save console components");
}

function _pickerLoadFixture(productId) {
  const product = _pickerState.products.find(p => p.product_id === productId);
  _pickerFixtureAutoLocation(product);
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

// ── Guided system flows ─────────────────────────────────────────────
// Radio, radar, and camera are normally customer-supplied kits.  The picker
// therefore asks for the shop-tech decisions in sequence and writes one
// expandable manifest line instead of pretending every kit component is a
// separate purchase.
const _SYSTEM_LOC = {
  radioBrick: [
    { value: "equipment_tray", label: "On equipment tray" },
    { value: "front_partition", label: "Front of partition" },
  ],
  radioAntenna: [
    { value: "rear_left_roof", label: "Rear left roof" },
    { value: "left_cargo_window", label: "Left cargo window" },
    { value: "right_cargo_window", label: "Right cargo window" },
  ],
  radioSpeaker: [
    { value: "back_center_console", label: "Back of center console" },
    { value: "cage_center", label: "Top of cage — center" },
    { value: "cage_driver", label: "Top of cage — driver side" },
    { value: "cage_passenger", label: "Top of cage — passenger side" },
    { value: "under_dash", label: "Under dash" },
    { value: "front_console", label: "Front of console" },
  ],
  radioMic: [
    { value: "top_console", label: "Top plate of console" },
  ],
  radarCounting: [
    { value: "under_driver_seat", label: "Under driver seat" },
    { value: "behind_dash", label: "Behind dash" },
    { value: "center_console", label: "In center console" },
  ],
  cameraDvr: [
    { value: "equipment_tray", label: "On equipment tray" },
    { value: "behind_passenger_seat", label: "Behind passenger seat" },
  ],
  frontCamera: [
    { value: "rearview_mirror", label: "Behind rearview mirror" },
    { value: "upper_windshield", label: "Upper windshield" },
    { value: "dash", label: "On dash" },
  ],
  rearSeatCamera: [
    { value: "upper_cage_bar", label: "On upper cage bar" },
    { value: "driver_headliner", label: "On driver-side headliner" },
    { value: "passenger_headliner", label: "On passenger-side headliner" },
  ],
  rearCamera: [
    { value: "above_license_plate", label: "Above license plate" },
    { value: "tailgate", label: "On tailgate / liftgate" },
    { value: "upper_rear_window", label: "Upper rear window" },
  ],
  visorOrConsole: [
    { value: "passenger_visor", label: "Passenger-side visor" },
    { value: "center_console", label: "On center console" },
    { value: "gunlock_pocket", label: "In gunlock pocket" },
  ],
};

// Cable refresh choices are read from parts_db via /system-cable-refreshes.
// That route only returns live QB-linked SKUs, so each option this workflow
// offers is safe to bill on the estimate.
function _systemCableRefreshes(kind) {
  const state = _pickerState.radio || {};
  return state.kind === kind ? (state.cableRefreshes || []) : [];
}

function _systemCableOptionValue(option) {
  return `${option.product_id || ""}::${option.part_number || ""}`;
}

function _systemCableRefreshMultiStep(kind) {
  const label = { radio: "radio", radar: "radar", camera: "camera" }[kind] || "system";
  return _systemStep(
    "refreshCables", "multi", `Which ${label} cables should be refreshed?`,
    "Select every cable run the shop should replace. The exact QB item is selected next when more than one length is available.",
    _systemCableRefreshes(kind).map(cable => [cable.id, cable.label, cable.help || ""]),
  );
}

function _systemCableSkuSteps(kind, choices) {
  const byId = new Map(_systemCableRefreshes(kind).map(cable => [cable.id, cable]));
  return (choices.refreshCables || []).flatMap(id => {
    const cable = byId.get(id);
    const options = cable?.billing_options || [];
    if (!cable || options.length <= 1) return [];
    return [_systemStep(
      `refreshSku_${id}`, "choice", `Which ${cable.label} should be billed?`,
      "Choose the exact replacement SKU for this cable run.",
      options.map(option => [
        _systemCableOptionValue(option),
        option.friendly_name || option.part_number,
        `${option.part_number}${option.price != null ? ` · ${_pickerRetailPrice(option.price)}` : ""}`,
      ]),
    )];
  });
}

function _systemClearCableRefreshSelections(choices) {
  choices.refreshCables = [];
  for (const key of Object.keys(choices)) {
    if (key.startsWith("refreshSku_")) delete choices[key];
  }
}

function _systemKeepAvailableCableRefreshSelections(choices, cableRefreshes) {
  const available = new Set((cableRefreshes || []).map(cable => cable.id));
  choices.refreshCables = (choices.refreshCables || []).filter(id => available.has(id));
  for (const key of Object.keys(choices)) {
    if (key.startsWith("refreshSku_") && !available.has(key.slice("refreshSku_".length))) delete choices[key];
  }
  return choices;
}

function _systemSupplySteps(kind, noun, choices) {
  const label = { radio: "radio", radar: "radar", camera: "camera" }[kind] || "system";
  return [
    _systemStep(
      "supplyType", "choice", `Who is supplying this ${noun}?`,
      "New means DTM supplies and bills the system. Customer supplied means the hardware is installed but not quoted.",
      [["new", "New", "DTM supplies and bills this system"], ["customer_supplied", "Customer supplied", "Do not include the supplied hardware on the Estimate"]],
    ),
    ...(choices.supplyType === "customer_supplied" ? [
      _systemStep(
        "customerCondition", "choice", "What condition is the customer-supplied system in?",
        "This records the physical condition without changing its non-billable status.",
        [["new", "New", "Customer-supplied new hardware"], ["used", "Used", "Customer-supplied used or transferred hardware"]],
      ),
      ...(choices.customerCondition === "used" ? [
        _systemStep("customerSource", "textarea", "Where will the used system come from?", "Required for shop handoff—for example, the agency, an old vehicle, or customer stock.", []),
        _systemStep("refresh", "choice", `Will the ${label} cables be refreshed?`, "Choose No when the current cable set can stay.", [["no", "No cable refresh", "Keep the existing cable set"], ["yes", "Yes, refresh cables", "Replace only the cable runs selected next"]]),
        ...(choices.refresh === "yes" ? [_systemCableRefreshMultiStep(kind), ..._systemCableSkuSteps(kind, choices)] : []),
      ] : []),
    ] : [
      ...(choices.supplyType === "new" ? [_systemStep("purchaseDetails", "textarea", "What should Sales purchase?", "Confirm the model, kit contents, vendor notes, or any other purchasing detail.", [])] : []),
    ]),
  ];
}

const _RADAR_BRACKETS = [
  ["short_a_bracket", "Short A-bracket", "Standard low-profile radar antenna mount"],
  ["tall_a_bracket", "Tall A-bracket", "Standard taller radar antenna mount"],
  ["swivel_arm", "Swivel arm mount", "Adjustable radar antenna mounting arm"],
];

const _SYSTEM_DEFS = {
  radio: {
    family: "radio_comms", label: "Radio Communications", chip: "RADIO",
    primaryName: "Radio Control Head", primaryPartType: "radio_head",
    intro: "Answer one install question at a time. Customer-supplied hardware only needs the decisions the shop must build around.",
    defaults: {
      systemProduct: null, supplyType: "", customerCondition: "", customerSource: "", componentSupply: {}, condition: "", componentConditions: {}, provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "",
      format: "split", brickLoc: "",
      antennaStyle: "", antennaLoc: "", speakerLoc: "",
      micClipRelation: "", micMount: "", micLoc: "",
    },
    steps(c) {
      return [
        ..._systemSupplySteps("radio", "radio system", c),
        ...(c.format === "split" ? [_systemLocationStep("brickLoc", "Where will the radio brick go?", "The brick is the remote electronics module behind the control head.", _SYSTEM_LOC.radioBrick)] : []),
        _systemStep("antennaStyle", "choice", "What antenna style is expected?", "This is an install note; it does not create a purchase order.", [["cylinder", "Cylinder style", "Common roof-mounted radio antenna"], ["whip", "Whip style", "Flexible whip antenna"], ["covert", "Covert / window style", "Low-profile or window-mounted antenna"], ["customer_specified", "Customer specified", "Use the customer hardware as supplied"]]),
        _systemLocationStep("antennaLoc", "Where will the radio antenna go?", c.antennaStyle === "cylinder" || c.antennaStyle === "whip" ? "Cylinder and whip antennas normally use the rear left roof." : "Choose the roof or cargo-window location.", c.antennaStyle === "cylinder" || c.antennaStyle === "whip" ? [_SYSTEM_LOC.radioAntenna[0]] : _SYSTEM_LOC.radioAntenna),
        _systemLocationStep("speakerLoc", "Where will the radio speaker go?", "Pick the location the shop should mount the speaker.", _SYSTEM_LOC.radioSpeaker),
        ...(() => {
          const consoleClip = _pickerExistingConsoleRadioMicClip();
          const useConsoleClip = !!consoleClip && c.micClipRelation === "use_console_clip";
          return [
            ...(consoleClip ? [_systemStep("micClipRelation", "choice", "A console radio mic clip is already selected. Is it for this radio?", "Confirm whether the console-mounted clip is the radio microphone mount or whether this radio needs an additional clip.", [["use_console_clip", "Use the console mic clip for this radio", "Keep one shared clip and avoid a duplicate mic mount"], ["additional_radio_clip", "Add an additional radio mic clip", "Continue to choose this radio's separate mount and location"]])] : []),
            ...(useConsoleClip ? [] : [
              _systemStep("micMount", "choice", "What microphone mount should the shop use?", "Choose the mounting style that matches the supplied radio kit.", [["manufacturer_clip", "Manufacturer clip", "Clip supplied by the radio manufacturer"], ["magnetic_no_bracket", "Magnetic Mic without bracket", "Magnetic Mic mount without its bracket"], ["magnetic_with_bracket", "Magnetic Mic with bracket", "Magnetic Mic mount with its bracket"]]),
              _systemLocationStep("micLoc", "Where will the radio microphone mount?", "Top plate is the standard location; use Custom for a shop-specific location.", _SYSTEM_LOC.radioMic),
            ]),
          ];
        })(),
      ];
    },
  },
  radar: {
    family: "radar", label: "Radar System", chip: "RADAR",
    primaryName: "Radar Display Unit", primaryPartType: "radar_display_unit",
    intro: "Capture the radar’s ownership, cable work, and exact antenna/counting-unit locations for the shop.",
    defaults: {
      systemProduct: null, supplyType: "", customerCondition: "", customerSource: "", componentSupply: {}, condition: "", componentConditions: {}, provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "", split: "",
      frontLoc: "", frontBracket: "short_a_bracket", rearLoc: "", rearBracket: "tall_a_bracket", countingLoc: "",
    },
    steps(c) {
      const isTahoe = _systemIsTahoeBuild();
      const rearLocations = [
        ["d_pillar", "On D-pillar", "D-pillar mounted rear antenna"],
        ["headliner", "On headliner", "Headliner mounted rear antenna"],
        ...(isTahoe ? [["seatbelt_slot", "Blank rear seatbelt slot (Tahoe only)", "Uses the blank rear seatbelt opening"]] : []),
      ];
      return [
        ..._systemSupplySteps("radar", "radar system", c),
        _systemStep("split", "choice", "Will the counting unit be split from the display unit?", "Choose whether the counting unit needs its own mounting location.", [["no", "No — integrated unit", "Display and counting unit stay together"], ["yes", "Yes — split unit", "The counting unit gets its own location next"]]),
        ...(c.split === "yes" ? [_systemLocationStep("countingLoc", "Where will the split counting unit go?", "Pick the final location for the separate counting unit.", _SYSTEM_LOC.radarCounting)] : []),
        _systemLocationStep("frontLoc", "Where will the front antenna be mounted?", "Choose the mounting location first; the bracket is selected on the next screen.", [["dash", "On dash", "Dash-mounted front antenna"], ["a_pillar", "On A-pillar", "A-pillar mounted front antenna"]]),
        _systemStep("frontBracket", "choice", "What bracket will mount the front antenna?", "Short A-bracket is the normal front choice; change it when this installation needs a different mount.", _RADAR_BRACKETS),
        _systemLocationStep(
          "rearLoc", "Where will the rear antenna be mounted?",
          "Choose a mounting location, or choose Not included for a front-only radar system.",
          rearLocations, { required: false },
        ),
        _systemStep(
          "rearBracket", "choice", "What bracket will mount the rear antenna?",
          "Tall A-bracket is the normal rear choice; change it when this installation needs a different mount.",
          _RADAR_BRACKETS,
          { required_when: { key: "rearLoc", excludes: ["", "__none__"] } },
        ),
      ];
    },
  },
  camera: {
    family: "camera_system", label: "Camera System", chip: "CAMERA",
    primaryName: "Camera DVR", primaryPartType: "camera_dvr",
    intro: "Record the kit ownership and the camera/DVR locations the shop needs. Only DTM purchases need ordering text.",
    defaults: {
      systemProduct: null, supplyType: "", customerCondition: "", customerSource: "", componentSupply: {}, condition: "", componentConditions: {}, provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "", cameraBrand: "", dvrLoc: "",
      cameraParts: [], rearSeatLoc: "",
      bodyDockLoc: "", wirelessMicLoc: "",
    },
    steps(c) {
      const extendedCamera = _cameraSupportsExtendedComponents(_systemCameraPlatform(c));
      const cameraOptions = [
        ["front", "Front-facing camera", "Forward road view"], ["rear_seat", "Prisoner / rear-seat camera", "Cabin or prisoner-area view"],
        ...(extendedCamera ? [["rear", "Rear / backup camera", "Rear exterior view"], ["body_dock", "Body-camera dock", "Dock for a body-worn camera"], ["wireless_mic", "Wireless microphone charger", "Charger for a wireless mic"]] : []),
      ];
      return [
        ..._systemSupplySteps("camera", "camera system", c),
        _systemLocationStep("dvrLoc", "Where will the camera DVR / recorder go?", "Pick the location the shop should use for the recorder.", _SYSTEM_LOC.cameraDvr),
        _systemStep("cameraParts", "multi", "Which camera components are included?", "Select every component the shop should install. Location questions will follow for each selection.", cameraOptions),
        ...(c.cameraParts || []).includes("rear_seat") ? [_systemLocationStep("rearSeatLoc", "Where will the prisoner / rear-seat camera go?", "Pick the final cabin-camera location.", _SYSTEM_LOC.rearSeatCamera)] : [],
        ...(c.cameraParts || []).includes("body_dock") ? [_systemLocationStep("bodyDockLoc", "Where will the body-camera dock go?", "Pick the location for the body-camera dock.", _SYSTEM_LOC.visorOrConsole)] : [],
        ...(c.cameraParts || []).includes("wireless_mic") ? [_systemLocationStep("wirelessMicLoc", "Where will the wireless microphone charger go?", "Pick the final charger location.", _SYSTEM_LOC.visorOrConsole)] : [],
      ];
    },
  },
};

function _systemStep(key, type, title, help, options, contract = {}) {
  // ``required:false`` is still an explicit question: the user must choose
  // either a real value or the generated Not included option.  ``required_when``
  // is for dependency-driven steps whose answer is mandatory only while the
  // referenced choice is active.
  if (typeof contract === "boolean") contract = { required: contract };
  return {
    key, type, title, help,
    options: (options || []).map(o => Array.isArray(o) ? { value: o[0], label: o[1], help: o[2] || "" } : o),
    required: contract.required !== false,
    required_when: contract.required_when || null,
  };
}

// These locations are shop-reference notes, not render-placement coordinates.
// A controlled list keeps common installs consistent, while Custom preserves
// the exact instruction when a vehicle/setup calls for something unusual.
function _systemLocationStep(key, title, help, options, contract = {}) {
  return { ..._systemStep(key, "choice", title, help, options, contract), allowCustom: true, customKey: `${key}Custom` };
}

function _systemOptions(step) {
  const options = [...(step.options || [])];
  if (!step.required) options.unshift({
    value: "__none__", label: "Not included", help: "Do not include this component in the build",
  });
  if (step.allowCustom) options.push({ value: "__custom__", label: "Custom location", help: "Enter a shop-specific location" });
  return options;
}

function _systemStepApplies(step, choices = _pickerState.radio?.choices || {}) {
  const rule = step.required_when;
  if (!rule) return true;
  const value = choices[rule.key];
  if (Array.isArray(rule.includes) && !rule.includes(value)) return false;
  if (Array.isArray(rule.excludes) && rule.excludes.includes(value)) return false;
  if (Object.prototype.hasOwnProperty.call(rule, "equals") && value !== rule.equals) return false;
  return true;
}

const _CAMERA_EXTENDED_BRANDS = new Set(["watchguard_4re", "watchguard_m500"]);
function _cameraSupportsExtendedComponents(brand) { return _CAMERA_EXTENDED_BRANDS.has(brand); }

function _systemProductLabel(choices) {
  const product = choices?.systemProduct || {};
  return [product.manufacturer_label, product.model, product.part_number].filter(Boolean).join(" · ");
}

function _systemCameraPlatform(choices) {
  const productId = choices?.systemProduct?.product_id || "";
  if (["axon_fleet_3", "axon_fleet_2", "watchguard_4re", "watchguard_m500"].includes(productId)) return productId;
  return choices?.cameraBrand || "other"; // preserves existing saved camera kits
}

function _systemIsTahoeBuild() {
  const draft = (typeof _meDraft !== "undefined") ? _meDraft : null;
  const vehicle = [
    _pickerVehicle(),
    draft?.vehicle_info?.NewVehicle?.MODEL,
    draft?.vehicle_info?.VehicleModel,
  ].filter(Boolean).join(" ");
  return /\bTAHOE\b/i.test(vehicle);
}

function _systemDef() { return _SYSTEM_DEFS[_pickerState.radio?.kind] || null; }

function _systemDefaults(kind, existing = {}) {
  const def = _SYSTEM_DEFS[kind];
  const base = { ...(def?.defaults || {}) };
  for (const [key, value] of Object.entries(existing || {})) {
    base[key] = Array.isArray(value) ? [...value]
      : value && typeof value === "object" ? { ...value } : value;
  }
  // Migrate the first guided-system vocabulary without rewriting the saved
  // draft until the user saves. An explicit legacy provider is useful here:
  // old "New + Customer supplied" systems were ownership-new but not billed.
  if (!base.supplyType && base.condition) {
    if (["used", "reused"].includes(base.condition)) {
      base.supplyType = "customer_supplied";
      base.customerCondition = "used";
    } else if (base.condition === "new" && base.provider === "customer") {
      base.supplyType = "customer_supplied";
      base.customerCondition = "new";
    } else if (base.condition === "new") {
      base.supplyType = "new";
    }
  }
  if (!base.customerSource && base.supplyType === "customer_supplied") {
    base.customerSource = String(existing.customer_source || existing.source || "").trim();
  }
  if (!base.componentSupply || typeof base.componentSupply !== "object" || Array.isArray(base.componentSupply)) {
    base.componentSupply = {};
  }
  for (const [key, status] of Object.entries(base.componentConditions || {})) {
    if (!base.componentSupply[key]) base.componentSupply[key] = _pickerSupplyPayload(_pickerSupplyFromRecord({ new_or_used: status }));
  }
  // Saved guided systems from the first pass used bracket names as radar
  // locations and shorter mic-mount values. Keep them editable after the
  // clearer split between location and bracket hardware.
  if (kind === "radar") {
    if (!base.frontLoc && base.frontMount) {
      if (["dash", "a_pillar"].includes(base.frontMount)) base.frontLoc = base.frontMount;
      else { base.frontLoc = "__custom__"; base.frontLocCustom = `Legacy selection: ${base.frontMount}`; }
    }
    if (!base.rearLoc && base.rearMount) base.rearLoc = base.rearMount;
    if (base.rearLoc === "seatbelt_slot" && !_systemIsTahoeBuild()) {
      base.rearLoc = "__custom__"; base.rearLocCustom = "Blank rear seatbelt slot (legacy Tahoe selection)";
    }
  }
  if (kind === "radio") {
    const legacyMicMounts = { standard: "manufacturer_clip", magnetic: "magnetic_no_bracket", bracket: "magnetic_with_bracket" };
    if (legacyMicMounts[base.micMount]) base.micMount = legacyMicMounts[base.micMount];
  }
  if (kind === "camera") {
    // The original camera refresh label became the more concise
    // signal_data_cable ID once the choice was linked to its QB SKU.
    base.refreshCables = (base.refreshCables || []).map(id =>
      id === "camera_signal_data_cable" ? "signal_data_cable" : id
    );
  }
  return base;
}

function _systemSteps() {
  const def = _systemDef(), c = _pickerState.radio?.choices || {};
  if (!def) return [];
  return [...def.steps(c).filter(step => _systemStepApplies(step, c)), {
    key: "componentConditions", type: "component_conditions",
    title: "What is the condition of each individual part?",
    help: "Used and reused parts stay on the build but are excluded from the estimate.",
    options: [], required: true,
  }];
}

function _systemOption(step, value) {
  return _systemOptions(step).find(o => o.value === value);
}

function _systemAnswerLabel(step, value, choices = _pickerState.radio?.choices || {}) {
  if (step.type === "component_conditions") return "Each component condition recorded";
  if (step.type === "textarea") return String(value || "").trim();
  if (step.type === "multi") {
    return (Array.isArray(value) ? value : []).map(v => _systemOption(step, v)?.label || v).join(", ");
  }
  if (step.allowCustom && value === "__custom__") {
    return String(choices[step.customKey] || "").trim() || "Custom location";
  }
  if (value === "__none__") return "Not included";
  return _systemOption(step, value)?.label || String(value || "");
}

function _systemStepSatisfied(step) {
  const choices = _pickerState.radio?.choices || {};
  if (!_systemStepApplies(step, choices)) return true;
  if (step.type === "component_conditions") {
    const rows = _systemComponentRows(_pickerState.radio?.kind, choices);
    return rows.length > 0 && rows.every(row =>
      row.supply_type === "new"
      || (row.supply_type === "customer_supplied"
        && ["new", "used"].includes(row.customer_condition)
        && (row.customer_condition !== "used" || Boolean(String(row.customer_source || "").trim())))
    );
  }
  const value = choices[step.key];
  if (step.type === "multi") return Array.isArray(value) && value.length > 0;
  if (step.allowCustom && value === "__custom__") return Boolean(String(choices[step.customKey] || "").trim());
  return String(value || "").trim().length > 0;
}

function _systemSatisfied() {
  const state = _pickerState.radio || {};
  if (!state.active || state.loading) return !state.active;
  return _systemSteps().every(_systemStepSatisfied);
}

function _systemClampStep() {
  const steps = _systemSteps();
  _pickerState.radio.step = Math.max(0, Math.min(_pickerState.radio.step || 0, Math.max(0, steps.length - 1)));
}

function _pickerRadioSatisfied() { return _systemSatisfied(); }

function _pickerSetSystemFilters(kind) {
  const def = _SYSTEM_DEFS[kind];
  if (!def) return;
  let familyLabel = def.label;
  for (const cat of (_pickerState.browseTree || [])) {
    const family = (cat.children || []).find(child => child.kind === "family" && child.family_id === def.family);
    if (family) { familyLabel = family.label || familyLabel; break; }
  }
  _pickerState.filters.type_id = "equipment";
  _pickerState.filters.type_label = "Equipment";
  _pickerState.filters.category_id = "";
  _pickerState.filters.category_label = "";
  _pickerState.filters.family_id = def.family;
  _pickerState.filters.family_label = familyLabel;
  _pickerState.filters.part_type_id = "";
  _pickerState.filters.part_type_label = "";
  _pickerBrowseExpanded.types.add("equipment");
  _pickerBrowseExpanded.families.add(def.family);
}

async function _pickerLoadSystemWorkflow(kind, existingChoices = null, step = 0) {
  if (!_SYSTEM_DEFS[kind]) return;
  const prior = _pickerState.radio || {};
  let cableRefreshes = prior.kind === kind ? (prior.cableRefreshes || []) : [];
  try {
    const vehicle = _pickerVehicle();
    const query = vehicle ? `&vehicle=${encodeURIComponent(vehicle)}` : "";
    const res = await api(`/api/parts-db/system-cable-refreshes?system=${encodeURIComponent(kind)}${query}`);
    cableRefreshes = res?.refreshes || [];
  } catch (e) {
    console.error("Picker: system cable refreshes failed:", e);
  }
  const choices = _systemKeepAvailableCableRefreshSelections(
    _systemDefaults(kind, existingChoices || prior.choices || {}), cableRefreshes,
  );
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.radio = {
    active: true, kind, loading: false, products: prior.products || {},
    cableRefreshes, choices, step: Number(step) || 0,
  };
  _systemClampStep();
  _pickerRenderProducts();
  _pickerRenderRadio();
  _pickerUpdateFooter();
}

function _pickerStartSystemSelection(kind, selectedProduct = null) {
  const def = _SYSTEM_DEFS[kind];
  if (!def) return;
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: true, kind, product: selectedProduct };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerRenderProducts();
  _pickerUpdateFooter();
}

function _pickerSystemProducts(kind) {
  const products = [...(_pickerState.products || [])];
  if (kind === "radio") {
    return products.filter(product =>
      product.primary_part_type_id === "radio_head"
      || (product.fits_part_types || []).includes("radio_head")
    );
  }
  if (kind === "radar") {
    return products.filter(product =>
      product.primary_part_type_id === "radar_display_unit"
      || (product.fits_part_types || []).includes("radar_display_unit")
    );
  }
  // Camera accessories can share the DVR part type in legacy catalog data;
  // only actual camera platforms belong in the system-identification step.
  if (kind !== "camera") return products;
  const platforms = new Set(["axon_fleet_3", "axon_fleet_2", "watchguard_4re", "watchguard_m500", "qb_unassigned_md_6200"]);
  return products.filter(product => platforms.has(product.product_id));
}

function _pickerSystemProductRecord(product, sku = null) {
  return product ? {
    product_id: product.product_id,
    manufacturer_label: product.manufacturer_label || "",
    model: product.model || "",
    part_number: sku?.part_number || "",
    friendly_name: sku?.friendly_name || "",
  } : null;
}

function _pickerRadioFormatForSelectedProduct(product) {
  const identity = [
    product?.product_id, product?.model, product?.friendly_name, product?.part_number,
  ].filter(Boolean).join(" ");
  return /all[\s-]?in[\s-]?one/i.test(identity) ? "all_in_one" : "split";
}

function _pickerChooseSystemSkusManually(kind) {
  const def = _SYSTEM_DEFS[kind];
  if (!def) return;
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.sel = null;
  _pickerRenderProducts();
  _pickerRenderRadio();
  _pickerUpdateFooter();
}

function _pickerRenderSystemSelectionIn(el) {
  const setup = _pickerState.systemSetup || {}, def = _SYSTEM_DEFS[setup.kind];
  if (!el || !setup.active || !def) return;
  const choices = _pickerSystemProducts(setup.kind);
  const selectedId = setup.product?.product_id || "";
  const selectedSku = setup.product?.part_number || "";
  const radioSkuChoices = setup.kind === "radio"
    ? choices.flatMap(product => (product.skus || []).map(sku => ({ product, sku })))
    : [];
  const cards = setup.kind === "radio"
    ? radioSkuChoices.map(({ product, sku }) => {
      const selected = product.product_id === selectedId && sku.part_number === selectedSku;
      return `<button type="button" class="system-product-choice${selected ? " is-selected" : ""}" data-system-product-id="${esc(product.product_id)}" data-system-sku="${esc(sku.part_number || "")}" aria-pressed="${selected ? "true" : "false"}">`
        + `<span class="system-product-choice-check">${selected ? "✓" : ""}</span><span class="system-product-choice-copy"><small>${esc(product.manufacturer_label || "Radio")} · ${esc(sku.part_number || "SKU pending")}</small><strong>${esc(sku.friendly_name || product.model || product.product_id)}</strong></span></button>`;
    }).join("")
    : choices.map(product => {
      const selected = product.product_id === selectedId;
      return `<button type="button" class="system-product-choice${selected ? " is-selected" : ""}" data-system-product-id="${esc(product.product_id)}" aria-pressed="${selected ? "true" : "false"}">`
        + `<span class="system-product-choice-check">${selected ? "✓" : ""}</span><span class="system-product-choice-copy"><small>${esc(product.manufacturer_label || "System")}</small><strong>${esc(product.model || product.product_id)}</strong></span></button>`;
    }).join("");
  const radioSelection = setup.kind === "radio";
  el.innerHTML = `<section class="system-product-picker system-product-picker--${esc(setup.kind)}" data-system-select-kind="${esc(setup.kind)}">`
    + `<div class="system-product-picker-kicker">${esc(def.chip)} · system identification</div><h2>${radioSelection ? "Which radio unit is being installed?" : `Which ${esc(def.label)} is this?`}</h2>`
    + `<p>${radioSelection ? "Select the radio SKU. Setup details open immediately after selection." : "Select the brand and platform first. The next tab will collect the install and shop details."}</p>`
    + `<div class="system-product-choice-grid">${cards || `<div class="system-product-empty">No system platforms are available for this selection yet.</div>`}</div>`
    + `<div class="system-review-actions"><button type="button" class="btn btn-secondary" data-system-manual-skus>Choose SKUs manually</button></div></section>`;
  el.querySelectorAll("[data-system-product-id]").forEach(button => button.addEventListener("click", async () => {
    const product = choices.find(item => item.product_id === button.dataset.systemProductId);
    const sku = (product?.skus || []).find(item => item.part_number === button.dataset.systemSku) || null;
    _pickerState.systemSetup.product = _pickerSystemProductRecord(product, sku);
    if (setup.kind === "radio") {
      await _pickerBeginSystemSetup();
      return;
    }
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
  el.querySelector("[data-system-manual-skus]")?.addEventListener("click", () => _pickerChooseSystemSkusManually(setup.kind));
}

async function _pickerBeginSystemSetup() {
  const setup = _pickerState.systemSetup || {}, def = _SYSTEM_DEFS[setup.kind];
  if (!def || !setup.product) return;
  const choices = { systemProduct: { ...setup.product } };
  if (setup.kind === "camera") choices.cameraBrand = _systemCameraPlatform(choices);
  if (setup.kind === "radio") choices.format = _pickerRadioFormatForSelectedProduct(setup.product);
  await _pickerLoadSystemWorkflow(setup.kind, choices, 0);
  _pickerSwitchTab("location");
}

function _pickerRenderSystemReviewIn(el) {
  const state = _pickerState.radio || {}, def = _systemDef();
  if (!el || !state.active || !def) return;
  const selected = _systemProductLabel(state.choices) || "System selected";
  const complete = _systemSatisfied();
  el.innerHTML = `<section class="system-product-picker system-product-picker--review" data-system-review-kind="${esc(state.kind)}">`
    + `<div class="system-product-picker-kicker">${esc(def.chip)} · selected system</div><h2>${esc(selected)}</h2>`
    + `<p>${complete ? "All shop details are complete." : "Continue on the Details tab to answer the shop-install questions."}</p>`
    + `<div class="system-review-actions"><button type="button" class="btn btn-primary" data-system-open-details>${complete ? "Review details" : "Continue setup"} →</button><button type="button" class="btn btn-secondary" data-system-change>Change system</button></div></section>`;
  el.querySelector("[data-system-open-details]")?.addEventListener("click", () => _pickerSwitchTab("location"));
  el.querySelector("[data-system-change]")?.addEventListener("click", () => _pickerStartSystemSelection(state.kind, state.choices?.systemProduct || null));
}

function _pickerRefreshSystemView() {
  if (_pickerState.tab === "location") _pickerRenderRadio();
  else _pickerRenderProducts();
  _pickerUpdateFooter();
}

// Compatibility entry point for older smoke helpers and any saved browser code.
async function _pickerLoadRadioWorkflow() { return _pickerLoadSystemWorkflow("radio"); }

function _systemOptionGrid(step, value) {
  const current = step.type === "multi" && Array.isArray(value) ? value : [value];
  return `<div class="guided-choice-grid${step.type === "multi" ? " guided-choice-grid--multi" : ""}">`
    + _systemOptions(step).map(o => {
      const selected = current.includes(o.value);
      return `<button type="button" class="guided-option${selected ? " is-selected" : ""}" data-system-choice="${esc(step.key)}" data-system-value="${esc(o.value)}" aria-pressed="${selected ? "true" : "false"}">
        <span class="guided-option-check">${selected ? "✓" : ""}</span><span class="guided-option-copy"><strong>${esc(o.label)}</strong>${o.help ? `<small>${esc(o.help)}</small>` : ""}</span></button>`;
    }).join("") + `</div>`;
}

function _systemComponentConditionsHtml() {
  const state = _pickerState.radio || {}, choices = state.choices || {};
  const rows = _systemComponentRows(state.kind, choices);
  return `<div class="guided-component-conditions">${rows.map(row => {
    const current = row.supply_type === "new" ? "new" : `customer_${row.customer_condition || "used"}`;
    const sourceNeeded = current === "customer_used";
    const options = [
      ["new", "New"], ["customer_new", "Customer supplied / New"], ["customer_used", "Customer supplied / Used"],
    ];
    return `<section class="guided-component-condition"><div><strong>${esc(row.label)}</strong><small>${esc(row.location || row.detail || "System component")}</small></div><div class="guided-component-supply">${options.map(([value, label]) =>
      `<button type="button" class="console-location-choice${current === value ? " is-selected" : ""}" data-system-component-supply="${esc(row.key)}" data-system-supply-value="${value}">${label}</button>`
    ).join("")}</div>${sourceNeeded ? `<label class="guided-component-source"><span>Used-part source <b>*</b></span><input type="text" data-system-component-source="${esc(row.key)}" value="${esc(row.customer_source || "")}" placeholder="Agency, old vehicle, customer stock…"></label>` : ""}</section>`;
  }).join("")}</div>`;
}

function _systemSummaryHtml(steps, currentKey) {
  const c = _pickerState.radio?.choices || {};
  const rows = steps.filter(s => s.key !== currentKey && _systemStepSatisfied(s)).map(s =>
    `<div class="guided-summary-row"><span>${esc(s.title.replace(/[?]$/, ""))}</span><strong>${esc(_systemAnswerLabel(s, c[s.key], c))}</strong></div>`
  ).join("");
  return rows || `<div class="guided-summary-empty">Your completed answers will appear here.</div>`;
}

function _systemDetails(def, choices) {
  const selection = _systemProductLabel(choices);
  return [
    ...(selection ? [{ label: "Selected system", value: selection, key: "systemProduct" }] : []),
    ..._systemSteps().filter(s => _systemStepSatisfied(s)).map(s => ({
    label: s.title.replace(/[?]$/, ""), value: _systemAnswerLabel(s, choices[s.key], choices), key: s.key,
    })),
  ];
}

function _systemComponentRows(kind, c) {
  if (!c.componentSupply || typeof c.componentSupply !== "object" || Array.isArray(c.componentSupply)) c.componentSupply = {};
  if (!c.componentConditions || typeof c.componentConditions !== "object" || Array.isArray(c.componentConditions)) c.componentConditions = {};
  const defaultSupply = _pickerSupplyPayload({
    supplyType: c.supplyType || "new",
    customerCondition: c.customerCondition || "",
    customerSource: c.customerSource || "",
  });
  const rows = [], add = (key, label, partType, location, detail) => rows.push({
    key, label, part_type: partType, location: location || "", detail: detail || "", quantity: 1,
    ...(() => {
      const explicitLegacy = c.componentConditions[key]
        ? { new_or_used: c.componentConditions[key] } : null;
      const existing = c.componentSupply[key] || explicitLegacy;
      const inheritsParent = !existing || existing.inherits_parent_supply === true;
      const payload = inheritsParent
        ? { ...defaultSupply }
        : _pickerSupplyPayload(_pickerSupplyFromRecord(existing));
      c.componentSupply[key] = { ...payload, ...(inheritsParent ? { inherits_parent_supply: true } : {}) };
      c.componentConditions[key] = payload.new_or_used;
      return payload;
    })(),
  });
  const baseSteps = _SYSTEM_DEFS[kind]?.steps(c) || [];
  const stepFor = key => baseSteps.find(s => s.key === key) || { options: [] };
  const answer = key => _systemAnswerLabel(stepFor(key), c[key], c);
  if (kind === "radio") {
    add("radio_control_head", "Radio control head", "radio_head", "", c.format === "split" ? "Split radio layout — console position is set with the center console." : "All-in-one radio — console position is set with the center console.");
    if (c.format === "split") add("radio_brick", "Radio brick", "radio_brick", answer("brickLoc"), "Separate electronics module");
    add("radio_antenna", "Radio antenna", "radio_antenna_top", answer("antennaLoc"), answer("antennaStyle"));
    add("radio_speaker", "Radio speaker", "radio_speaker", answer("speakerLoc"), "Shop mounting location");
    const usesConsoleClip = c.micClipRelation === "use_console_clip" && !!_pickerExistingConsoleRadioMicClip();
    add(
      "radio_microphone", "Radio microphone", "radio_mic_clip",
      usesConsoleClip ? "ON CENTER CONSOLE" : answer("micLoc"),
      usesConsoleClip ? "Uses the selected center-console mic clip" : answer("micMount"),
    );
  } else if (kind === "radar") {
    if (c.split === "yes") {
      add("radar_display", "Radar display unit", "radar_display_unit", "", "Separate display unit");
      add("radar_counting", "Radar counting unit", "radar_counting_unit", answer("countingLoc"), "Separate counting unit");
    } else {
      add("radar_display", "Radar display / counting unit", "radar_display_unit", "Integrated display unit", "Integrated unit");
    }
    add("radar_front_antenna", "Front radar antenna", "front_radar_antenna_mount", answer("frontLoc"), answer("frontBracket"));
    if (c.rearLoc !== "__none__") {
      add("radar_rear_antenna", "Rear radar antenna", "rear_radar_antenna_mount", answer("rearLoc"), answer("rearBracket"));
    }
  } else if (kind === "camera") {
    add("camera_dvr", "Camera DVR / recorder", "camera_dvr", answer("dvrLoc"), `Platform: ${_systemProductLabel(c) || _systemCameraPlatform(c)}`);
    const map = {
      front: ["Front-facing camera", "front_camera", "Upper windshield", "Fixed location"],
      rear_seat: ["Prisoner / rear-seat camera", "rear_seat_camera", answer("rearSeatLoc"), "Selected camera component"],
      rear: ["Rear / backup camera", "rear_camera", "Upper rear window", "Fixed location"],
      body_dock: ["Body-camera dock", "body_camera_dock", answer("bodyDockLoc"), "Selected camera component"],
      wireless_mic: ["Wireless microphone charger", "wireless_mic_charger", "wirelessMicLoc"],
    };
    for (const key of (c.cameraParts || [])) {
      const item = map[key]; if (!item) continue;
      const location = key === "wireless_mic" ? answer("wirelessMicLoc") : item[2];
      add(`camera_${key}`, item[0], item[1], location, item[3] || "Selected camera component");
    }
  }
  return rows;
}

// Unlike the other guided-system details, refreshed cables are actual parts we
// sell.  Keep them as nested draft children so the manifest shows the precise
// billable SKU and QuickBooks sees a normal, linked part line.
function _pickerSystemCableRefreshRows(parentLineId, parentName, kind, choices) {
  if (choices.supplyType !== "customer_supplied" || choices.customerCondition !== "used" || choices.refresh !== "yes" || !parentLineId) return [];
  const byId = new Map(_systemCableRefreshes(kind).map(cable => [cable.id, cable]));
  const grouped = new Map();
  for (const cableId of (choices.refreshCables || [])) {
    const cable = byId.get(cableId);
    if (!cable) continue;
    const options = cable.billing_options || [];
    const selected = options.length === 1
      ? options[0]
      : options.find(option => _systemCableOptionValue(option) === choices[`refreshSku_${cableId}`]);
    if (!selected?.part_number) continue;
    const key = `${selected.product_id}::${selected.part_number}`;
    const prior = grouped.get(key);
    if (prior) {
      prior.labels.push(cable.label);
      if (!cable.billing_once) prior.quantity += 1;
      continue;
    }
    grouped.set(key, {
      ...selected,
      partType: cable.part_type || "cable",
      labels: [cable.label],
      quantity: 1,
    });
  }
  return [...grouped.values()].map(item => ({
    name: `${parentName} · ${item.model || item.friendly_name || item.part_number}`,
    location: "", manufacturer: item.manufacturer_label || "", part_number: item.part_number,
    quantity: item.quantity, new_or_used: "New", source: "", parent_line_id: parentLineId,
    accessory_category: "system_cable_refresh", accessory_parent_product: "", part_type: item.partType,
    notes: `Cable refresh: ${item.labels.join(", ")}`,
  }));
}

async function _pickerReplaceSystemCableRefreshChildren(draftId, parentLineId, parentName, kind, choices) {
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId && part.accessory_category === "system_cable_refresh"
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace a system cable refresh line");
  }
  for (const row of _pickerSystemCableRefreshRows(parentLineId, parentName, kind, choices)) {
    const result = await api(`/api/draft/${draftId}/part`, row);
    if (!result?.ok) throw new Error(result?.error || "could not add a system cable refresh line");
  }
}

function _pickerRenderRadio() {
  if (_pickerState.consoleSetup?.active) {
    _pickerRenderConsoleSetup();
    return;
  }
  const panel = $("picker-radio");
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
  const state = _pickerState.radio || {};
  const locationContent = $("picker-location-content");
  const details = $("picker-system-details");
  if (!state.active) {
    if (details) { details.hidden = true; details.innerHTML = ""; }
    if (locationContent) locationContent.hidden = false;
    return;
  }
  if (_pickerState.tab === "location") {
    if (locationContent) locationContent.hidden = true;
    if (details) { details.hidden = false; _pickerRenderSystemIn(details); }
    return;
  }
  if (details) { details.hidden = true; details.innerHTML = ""; }
  if (locationContent) locationContent.hidden = false;
}

function _pickerRenderRadioIn(el) { return _pickerRenderSystemReviewIn(el); }

function _pickerRenderSystemIn(el) {
  const state = _pickerState.radio || {}, def = _systemDef();
  if (!el || !state.active || !def) return;
  const steps = _systemSteps(); _systemClampStep();
  const index = state.step || 0, step = steps[index];
  const value = state.choices?.[step.key];
  const complete = _systemSatisfied();
  const progress = steps.length ? Math.round(((index + 1) / steps.length) * 100) : 0;
  let nextOk = _systemStepSatisfied(step);
  const customLocation = step.allowCustom && value === "__custom__"
    ? `<label class="guided-custom-field"><span>Custom shop location</span><input class="guided-text-input" data-system-custom="${esc(step.customKey)}" value="${esc(state.choices?.[step.customKey] || "")}" placeholder="Enter the exact shop-reference location"></label>`
    : "";
  const stepBody = step.type === "component_conditions"
    ? _systemComponentConditionsHtml()
    : step.type === "textarea"
    ? `<textarea class="guided-textarea" data-system-text="${esc(step.key)}" rows="6" placeholder="Enter purchasing details for Sales…">${esc(value || "")}</textarea><div class="guided-field-note">This note is saved with the system line for purchasing.</div>`
    : _systemOptionGrid(step, value) + customLocation;
  nextOk = _systemStepSatisfied(step);
  el.innerHTML = `<section class="guided-system guided-system--${esc(state.kind)}" data-system-kind="${esc(state.kind)}">
    <div class="guided-system-header"><div><span class="guided-chip">${esc(def.chip)}</span><span class="guided-system-title">${esc(def.label)}</span><p>${esc(def.intro)}</p></div><button class="guided-close" type="button" onclick="_pickerClearSelection()" title="Close">✕</button></div>
    <div class="guided-progress-head"><span>Step ${index + 1} of ${steps.length}</span><strong>${progress}%</strong></div><div class="guided-progress"><span style="width:${progress}%"></span></div>
    <div class="guided-system-layout"><div class="guided-question"><div class="guided-kicker">${esc(step.type === "multi" ? "Select all that apply" : step.type === "textarea" ? "Purchasing note" : "System setup")}</div><h2>${esc(step.title)}</h2><p class="guided-help">${esc(step.help || "")}</p>${stepBody}<div class="guided-nav"><button type="button" class="btn btn-secondary guided-back" data-system-nav="back"${index === 0 ? " disabled" : ""}>← Back</button><button type="button" class="btn btn-primary guided-next" data-system-nav="next"${nextOk ? "" : " disabled"}>${index === steps.length - 1 ? (complete ? "Ready to add" : "Finish this answer") : "Next question →"}</button></div></div>
      <aside class="guided-summary"><div class="guided-summary-title">Your system so far</div>${_systemSummaryHtml(steps, step.key)}${complete ? `<div class="guided-ready">✓ All shop-tech details complete</div>` : ""}</aside></div>
  </section>`;
  el.querySelectorAll("[data-system-choice]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.systemChoice, selected = button.dataset.systemValue;
    const target = _pickerState.radio.choices;
    if (step.type === "multi") {
      const list = Array.isArray(target[key]) ? [...target[key]] : [];
      const pos = list.indexOf(selected); if (pos >= 0) list.splice(pos, 1); else list.push(selected); target[key] = list;
      if (key === "refreshCables") {
        for (const choiceKey of Object.keys(target)) {
          if (choiceKey.startsWith("refreshSku_") && !list.includes(choiceKey.slice("refreshSku_".length))) delete target[choiceKey];
        }
      }
    } else {
      target[key] = selected;
      if (key === "supplyType") {
        target.condition = selected === "new" ? "new" : "used";
        target.provider = selected === "new" ? "dtm" : "customer";
        target.customerCondition = ""; target.customerSource = "";
        target.purchaseDetails = ""; target.refresh = "";
        target.componentSupply = {}; target.componentConditions = {};
        _systemClearCableRefreshSelections(target);
      }
      if (key === "customerCondition") {
        target.condition = selected === "used" ? "used" : "new";
        if (selected !== "used") {
          target.customerSource = ""; target.refresh = "";
          _systemClearCableRefreshSelections(target);
        }
        target.componentSupply = {}; target.componentConditions = {};
      }
      if (key === "condition") { target.componentConditions = {}; target.refresh = ""; _systemClearCableRefreshSelections(target); target.provider = "customer"; target.purchaseDetails = ""; }
      if (key === "refresh" && selected !== "yes") _systemClearCableRefreshSelections(target);
      if (key === "provider" && selected === "customer") target.purchaseDetails = "";
      if (key === "micClipRelation" && selected === "use_console_clip") {
        target.micMount = "";
        target.micLoc = "";
        delete target.micLocCustom;
      }
      if (key === "rearLoc" && selected === "__none__") {
        target.rearBracket = "";
        delete target.rearLocCustom;
        if (target.componentConditions && typeof target.componentConditions === "object") {
          delete target.componentConditions.radar_rear_antenna;
        }
        if (target.componentSupply && typeof target.componentSupply === "object") {
          delete target.componentSupply.radar_rear_antenna;
        }
      }
      if (key === "antennaStyle" && ["cylinder", "whip"].includes(selected) && target.antennaLoc && !["rear_left_roof", "__custom__"].includes(target.antennaLoc)) target.antennaLoc = "";
      if (key === "cameraBrand" && !_cameraSupportsExtendedComponents(selected)) {
        target.cameraParts = (target.cameraParts || []).filter(part => ["front", "rear_seat"].includes(part));
        target.bodyDockLoc = ""; target.wirelessMicLoc = "";
      }
    }
    _systemClampStep(); _pickerRefreshSystemView();
  }));
  el.querySelectorAll("[data-system-component-supply]").forEach(button => button.addEventListener("click", () => {
    const target = _pickerState.radio.choices;
    if (!target.componentSupply || typeof target.componentSupply !== "object") target.componentSupply = {};
    if (!target.componentConditions || typeof target.componentConditions !== "object") target.componentConditions = {};
    const value = button.dataset.systemSupplyValue;
    const supply = value === "new"
      ? { supplyType: "new", customerCondition: "", customerSource: "" }
      : { supplyType: "customer_supplied", customerCondition: value === "customer_new" ? "new" : "used", customerSource: "" };
    const payload = _pickerSupplyPayload(supply);
    target.componentSupply[button.dataset.systemComponentSupply] = payload;
    target.componentConditions[button.dataset.systemComponentSupply] = payload.new_or_used;
    _pickerRefreshSystemView();
  }));
  el.querySelectorAll("[data-system-component-source]").forEach(input => input.addEventListener("input", () => {
    const target = _pickerState.radio.choices;
    const key = input.dataset.systemComponentSource;
    if (!target.componentSupply || typeof target.componentSupply !== "object") target.componentSupply = {};
    const current = target.componentSupply[key] || _pickerSupplyPayload({ supplyType: "customer_supplied", customerCondition: "used", customerSource: "" });
    current.customer_source = input.value;
    current.source = input.value;
    target.componentSupply[key] = current;
    _pickerUpdateFooter();
    const next = el.querySelector(".guided-next"); if (next) next.disabled = !_systemStepSatisfied(step);
  }));
  el.querySelectorAll("[data-system-text]").forEach(input => input.addEventListener("input", () => {
    _pickerState.radio.choices[input.dataset.systemText] = input.value;
    _pickerUpdateFooter();
    const next = el.querySelector(".guided-next"); if (next) next.disabled = !_systemStepSatisfied(step);
  }));
  el.querySelectorAll("[data-system-custom]").forEach(input => input.addEventListener("input", () => {
    _pickerState.radio.choices[input.dataset.systemCustom] = input.value;
    _pickerUpdateFooter();
    const next = el.querySelector(".guided-next"); if (next) next.disabled = !_systemStepSatisfied(step);
  }));
  el.querySelectorAll("[data-system-nav]").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.systemNav === "back") _pickerState.radio.step = Math.max(0, (state.step || 0) - 1);
    else if (_systemStepSatisfied(step)) _pickerState.radio.step = Math.min(steps.length - 1, (state.step || 0) + 1);
    _pickerRefreshSystemView();
  }));
}

function _pickerSystemPrimaryLocation(kind, choices) {
  if (kind === "radio") return "";
  if (kind === "camera") return _systemAnswerLabel(_systemSteps().find(s => s.key === "dvrLoc") || { options: [] }, choices.dvrLoc, choices);
  return choices.split === "yes" ? _systemAnswerLabel(_systemSteps().find(s => s.key === "countingLoc") || { options: [] }, choices.countingLoc, choices) : "Integrated display unit";
}

async function _pickerAddSystem(addAndContinue) {
  if (!_pickerRadioSatisfied()) return;
  const draftId = (typeof _meDraftId !== "undefined") ? _meDraftId : null;
  if (!draftId) { toast("No active build", "error"); return; }
  const state = _pickerState.radio, def = _systemDef(), c = _systemDefaults(state.kind, state.choices);
  const details = _systemDetails(def, c);
  const components = _systemComponentRows(state.kind, c);
  // Purchase text remains saved with the kit for Sales, while shop decisions
  // appear only on the concrete component rows in the expandable manifest.
  const systemNotes = String(c.purchaseDetails || "").trim();
  const editing = !!_pickerState.editLineId, existing = _pickerState.editPart;
  const parentSupply = _pickerSupplyPayload({
    supplyType: c.supplyType,
    customerCondition: c.customerCondition,
    customerSource: c.customerSource,
  });
  const row = {
    name: editing ? (existing?.name || def.primaryName) : def.primaryName,
    location: _pickerSystemPrimaryLocation(state.kind, c), manufacturer: c.systemProduct?.manufacturer_label || "",
    part_number: c.supplyType === "new" ? "DTM PURCHASE — SEE DETAILS" : "CUSTOMER SUPPLIED KIT",
    quantity: 1, ...parentSupply,
    part_type: def.primaryPartType,
    notes: systemNotes || `${def.label} — guided system details`, components,
    comment: _pickerState.comment || "",
    picker_config: { system_type: state.kind, system_label: def.label, choices: c, details, step: state.step || 0 },
  };
  const btn = $("picker-add-btn"); if (btn) btn.disabled = true;
  try {
    const endpoint = editing ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update` : `/api/draft/${draftId}/part`;
    const result = await api(endpoint, row);
    if (!result?.ok) throw new Error(result?.error || "system add failed");
    const parentLineId = result.line_id || _pickerState.editLineId;
    await _pickerReplaceSystemCableRefreshChildren(draftId, parentLineId, row.name, state.kind, c);
    if (state.kind === "radio") {
      const micStep = _systemSteps().find(step => step.key === "micLoc") || { options: [] };
      const micLocation = _systemAnswerLabel(micStep, c.micLoc, c);
      await _pickerReplaceMagneticMicChild(
        draftId, parentLineId, row.name, micLocation,
        c.micClipRelation === "use_console_clip" ? "" : c.micMount,
        c.componentSupply?.radio_microphone || components.find(item => item.key === "radio_microphone") || parentSupply,
      );
    }
    toast(editing ? `${def.label} updated` : `${def.label} added`, "success");
    await _pickerFinalize(draftId, addAndContinue);
  } catch (e) {
    console.error("guided system add failed:", e); toast(`${def.label} could not be saved`, "error"); if (btn) btn.disabled = false;
  }
}

// Build the accessory part rows chosen for the current selection.
function _pickerChosenAccessoryRows(parentName, locName, parentLineId) {
  const rows = [];
  const parentProduct = _pickerState.sel ? _pickerState.sel.product_id : "";
  for (const g of _pickerVisibleAccessoryGroups()) {
    const v = _pickerState.accessoryChoices[g.category];
    const picks = Array.isArray(v) ? v : [v];
    const quantities = _pickerAccessoryStateList(
      _pickerState.accessoryQuantities, g.category, picks.length, 1,
    );
    const manual = _pickerAccessoryStateList(
      _pickerState.accessoryQuantityManual, g.category, picks.length, false,
    );
    const counts = {};
    const rules = {};
    picks.forEach((pick, index) => {
      if (!pick || pick === "none") return;
      counts[pick] = (counts[pick] || 0) + Math.max(1, Number(quantities[index]) || 1);
      rules[pick] = {
        ..._pickerAccessoryQuantityRule(g, pick),
        manual_quantity: Boolean((rules[pick] || {}).manual_quantity || manual[index]),
      };
    });
    for (const [pick, qty] of Object.entries(counts)) {
      const [pidPart, sku] = pick.split("::");
      const opt = g.options.find(o => o.product_id === pidPart);
      if (!opt) continue;
      rows.push({
        name: `${parentName} · ${opt.model}`,
        location: locName, manufacturer: opt.manufacturer_label || "",
        part_number: sku, quantity: qty, new_or_used: "New", source: "",
        parent_line_id: parentLineId || "",
        accessory_category: g.category,
        accessory_parent_product: parentProduct,
        picker_config: Object.keys(rules[pick] || {}).length
          ? { accessory_quantity: { ...rules[pick] } }
          : {},
      });
    }
  }
  return rows;
}

async function _pickerReplaceAccessoryChildren(draftId, parentLineId, parentName, locName, removeCategories = []) {
  const productId = _pickerState.sel?.product_id || "";
  const groups = _pickerVisibleAccessoryGroups();
  const categoriesToRemove = new Set(removeCategories);
  if (!productId || (!groups.length && !categoriesToRemove.size)) return;
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part => {
    if (part.parent_line_id !== parentLineId) return false;
    return categoriesToRemove.has(part.accessory_category)
      || !!_pickerAccessoryChoiceForChild(groups, part);
  });
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace an accessory");
  }
  for (const row of _pickerChosenAccessoryRows(parentName, locName, parentLineId)) {
    const result = await api(`/api/draft/${draftId}/part`, row);
    if (!result?.ok) throw new Error(result?.error || "could not add an accessory");
  }
}

function _pickerChosenWestinRows(parentName, locName, parentLineId) {
  if (!_pickerState.westin || !_pickerState.westin.active || !_pickerState.sel) return [];
  const rows = [];
  const addChoice = (value, category) => {
    if (!value) return;
    const [pid, sku] = value.split("::");
    const product = [..._pickerWestinOptionProducts("wire"), ..._pickerWestinOptionProducts("channel")]
      .find(p => p.product_id === pid);
    if (!product || !sku) return;
    rows.push({
      name: `${parentName} · ${product.model}`,
      location: locName,
      manufacturer: product.manufacturer_label || "",
      part_number: sku,
      quantity: 1,
      new_or_used: "New",
      source: "",
      parent_line_id: parentLineId || "",
      accessory_category: category,
      accessory_parent_product: _pickerState.sel.product_id,
    });
  };
  addChoice(_pickerState.westin.wire, "westin_wire_cover");
  addChoice(_pickerState.westin.channel, "westin_light_channel");
  return rows;
}

function _pickerWestinChannelHeads() {
  const westin = _pickerState.westin;
  const info = westin?.channelInfo;
  if (!info) return [];
  const secondary = westin.lights.secondary;
  if (westin.lights.mode === "trio") {
    return Array.from({ length: info.count }, () => ["red", "blue", secondary]);
  }
  return Array.from({ length: info.count }, (_, index) => [index < Math.ceil(info.count / 2) ? "red" : "blue", secondary]);
}

async function _pickerAddWestinChannelLights(draftId, bumperLineId) {
  const westin = _pickerState.westin;
  const product = westin?.lightProduct, info = westin?.channelInfo;
  if (!product || !info || !bumperLineId) return;
  const heads = _pickerWestinChannelHeads();
  const matched = await api("/api/parts-db/match-skus", {
    product_id: product.product_id, heads, lens: westin.lights.lens,
  });
  if (!matched?.all_matched) throw new Error("No matching QB SKU for the selected channel-light configuration");
  const priceBySku = Object.fromEntries((product.skus || []).map(sku => [sku.part_number, sku.price]));
  const combos = (matched.combos || []).filter(combo => combo.default_sku && combo.count).map(combo => ({
    colors: combo.colors || [], part_number: combo.default_sku, quantity: combo.count,
    price: priceBySku[combo.default_sku] ?? null,
  }));
  if (!combos.length) throw new Error("No matching QB SKU for the selected channel-light configuration");

  const secondary = westin.lights.secondary.charAt(0).toUpperCase() + westin.lights.secondary.slice(1);
  const isTrio = westin.lights.mode === "trio";
  const driverColor = `Red/${secondary}`, passengerColor = `Blue/${secondary}`;
  const colorFields = isTrio
    ? { raw_color: `Red/Blue/${secondary}` }
    : { raw_color: `${driverColor} / ${passengerColor}`, driver_color: driverColor, passenger_color: passengerColor };

  // Resolve the concrete ION SKUs into one ordinary Forward Warning line.
  // It uses TOP TUBE so it follows the same rendering and quantity rules as
  // a manually added top-tube warning-light set, rather than behaving as a
  // bumper accessory in the manifest.
  const resolved = await api("/api/parts-db/resolve-selection", {
    product_model: product.model, manufacturer_label: product.manufacturer_label || "",
    location: "TOP TUBE", base_name: _pickerSequencedName("Forward Warning {n}", "Forward Warning"),
    lens: westin.lights.lens, combos, color_fields: colorFields, total_heads: info.count,
  });
  const row = resolved?.rows?.[0];
  if (!row) throw new Error("could not resolve the channel lights");
  const result = await api(`/api/draft/${draftId}/part`, {
    ...row,
    ..._pickerSupplyPayload(),
    linked_parent_line_id: bumperLineId,
    part_type: "warning_light",
    picker_config: {
      mode: isTrio ? "uniform" : "split",
      colorsPerHead: isTrio ? 3 : 2,
      uniform: isTrio ? ["red", "blue", westin.lights.secondary] : [],
      splitSecondary: isTrio ? [] : [westin.lights.secondary],
      custom: [], _noColor: false, count: info.count, lens: westin.lights.lens,
      westin_channel_light: {
        product_id: product.product_id, channel_product_id: info.channelProductId,
        mode: westin.lights.mode, secondary: westin.lights.secondary,
      },
    },
  });
  if (!result?.ok) throw new Error(result?.error || "could not add the channel lights");
}

function _pickerUpdateFooter() {
  const text = $("picker-footer-text"), btn = $("picker-add-btn"), btnAnother = $("picker-add-another-btn");
  if (!text || !btn) return;
  _pickerRenderPartStatus();
  const sel = _pickerState.sel, loc = _pickerState.loc;
  _pickerSyncCommentStep();
  const detailsTab = $("picker-tab-btn-location");
  const hasAutomaticLocation = _pickerHasFixedPartLocation()
    || ["license_plate", "outer_edge_pillars"].includes(loc.autoLocation);
  if (detailsTab) detailsTab.hidden = hasAutomaticLocation
    && !_pickerState.radio?.active && !_pickerState.systemSetup?.active && !_pickerState.consoleSetup?.active;
  const accOk = _accessoriesSatisfied();
  const tracerOk = _pickerTracerSatisfied();
  const innerEdgeOk = _pickerInnerEdgeSatisfied();
  const outerEdgeOk = _pickerOuterEdgeSatisfied();
  const lightbarOk = _pickerLightbarSatisfied();
  const radioOk = _pickerRadioSatisfied();
  const detailsOk = _pickerPartDetailsSatisfied();
  const westinOk = _pickerWestinChannelSatisfied();
  const tintOk = _pickerTintReady();
  const allocationOk = _pickerLocationAllocationReady();
  const supplyOk = _pickerState.radio?.active || _pickerState.systemSetup?.active || _pickerState.consoleSetup?.active
    ? true : _pickerSupplySatisfied();
  const ready = accOk && tracerOk && innerEdgeOk && outerEdgeOk && lightbarOk && radioOk && detailsOk && westinOk && tintOk && allocationOk && supplyOk;
  // A required detail belongs on the next screen. It must not prevent the
  // user from reaching that screen after selecting the part.
  const detailsEntryReady = accOk && tracerOk && innerEdgeOk && outerEdgeOk && lightbarOk && westinOk;
  const hasAcc = _pickerVisibleAccessoryGroups().length > 0;
  const selName = sel ? (sel.model + (sel.sku ? " · " + sel.sku : "")) : "";
  let hint = (sel && hasAcc && !accOk) ? ' <span class="picker-foot-acc">· choose accessories</span>' : "";
  if (sel && _pickerState.tracer.active && !tracerOk)
    hint += ' <span class="picker-foot-acc">· configure lightheads</span>';
  if (sel && _pickerState.innerEdge.active && !innerEdgeOk)
    hint += ' <span class="picker-foot-acc">· configure Inner Edge heads</span>';
  if (sel && _pickerState.outerEdge.active && !outerEdgeOk)
    hint += ' <span class="picker-foot-acc">· configure Outer Edge IONs</span>';
  if (sel && _pickerState.lightbar.active && !lightbarOk)
    hint += ' <span class="picker-foot-acc">· add order notes</span>';
  if (sel && !detailsOk)
    hint += ' <span class="picker-foot-acc">· complete shop details</span>';
  if (sel && !westinOk)
    hint += ' <span class="picker-foot-acc">· configure channel lights</span>';
  if (sel && !tintOk)
    hint += ' <span class="picker-foot-acc">· choose windows and tint percentage</span>';
  if (sel && !allocationOk)
    hint += ' <span class="picker-foot-acc">· assign at least one install location</span>';
  if (_pickerState.radio.active && !radioOk)
    hint += ` <span class="picker-foot-acc">· complete ${esc(_systemDef()?.label || "system")} workflow</span>`;
  if (!supplyOk)
    hint += ` <span class="picker-foot-acc">· ${_pickerState.supply.customerCondition === "used" ? "enter the customer-used source" : "choose the customer-supplied condition"}</span>`;

  // Step 7: show "Add another part" alongside "Add and Finish" when the action
  // is "add" (not navigate-to-location, not edit-save). Multi-add is build-only
  // — edit mode stays single-shot.
  const _showTwoButtons = (enabled, doAddFn) => {
    if (!btnAnother) return;
    const show = enabled && !_pickerState.editLineId;
    btnAnother.hidden = !show;
    _pickerState.footerHandlerAnother = show ? () => doAddFn(true) : null;
  };

  const setup = _pickerState.systemSetup || {};
  if (setup.active) {
    const def = _SYSTEM_DEFS[setup.kind];
    const selected = _systemProductLabel({ systemProduct: setup.product });
    text.innerHTML = `<span class="picker-foot-label">${selected ? esc(selected) : `Choose a ${esc(def?.label || "system")}`}</span>`;
    btn.textContent = `Set up ${def?.label || "system"} →`;
    btn.disabled = !setup.product;
    _pickerState.footerHandler = setup.product ? _pickerBeginSystemSetup : null;
    _showTwoButtons(false, null);
    return;
  }

  if (_pickerState.radio.active) {
    if (_pickerState.tab === "part") {
      text.innerHTML = `<span class="picker-foot-label">${esc(_systemProductLabel(_pickerState.radio.choices) || _systemDef()?.label || "Guided system")}</span>`;
      btn.textContent = "Continue in Details →";
      btn.disabled = false;
      _pickerState.footerHandler = () => _pickerSwitchTab("location");
      _showTwoButtons(false, null);
      return;
    }
    text.innerHTML = `<span class="picker-foot-label">${esc(_systemDef()?.label || "Guided system")}</span>${hint}`;
    btn.textContent = "Add and Finish";
    btn.disabled = !radioOk;
    _pickerState.footerHandler = radioOk ? () => _pickerAddSystem(false) : null;
    _showTwoButtons(radioOk, _pickerAddSystem);
  } else if (_pickerState.consoleSetup?.active) {
    const consoleLabel = sel ? `${sel.model}${sel.sku ? " · " + sel.sku : ""}` : "Center Console";
    const pedestalRequired = _pickerConsolePedestalRequired();
    const pedestalReady = !pedestalRequired || !!_pickerState.consoleSetup.choices?.pedestalMount;
    const printerRequired = _pickerConsolePrinterRequired();
    const printerReady = !printerRequired || !!_pickerState.consoleSetup.choices?.printer;
    const radioMicRelationRequired = _pickerConsoleRadioMicRelationRequired();
    const radioMicRelationReady = !radioMicRelationRequired || ["use_for_existing_radio", "additional_console_clip"].includes(_pickerState.consoleSetup.choices?.radioMicClipRelation);
    const consoleSupplyReady = _pickerConsoleSupplySatisfied();
    const consoleReady = !!sel && !_pickerState.consoleSetup.loading && pedestalReady && printerReady && radioMicRelationReady && consoleSupplyReady;
    const missing = [
      !pedestalReady ? "Choose a pedestal / mount base to continue." : "",
      !printerReady ? "Choose a printer to continue." : "",
      !radioMicRelationReady ? "Confirm whether the console mic clip is for the existing radio." : "",
      !consoleSupplyReady ? "Enter a source for every customer-supplied used console component." : "",
    ].filter(Boolean);
    text.innerHTML = `<span class="picker-foot-label">${esc(consoleLabel)}</span>${missing.length ? `<span class="picker-foot-note">${esc(missing.join(" "))}</span>` : ""}`;
    if (_pickerState.tab === "part") {
      btn.textContent = "Continue in Details →";
      btn.disabled = !consoleReady;
      _pickerState.footerHandler = consoleReady ? () => _pickerSwitchTab("location") : null;
      _showTwoButtons(false, null);
    } else {
      btn.textContent = "Add and Finish";
      btn.disabled = !consoleReady;
      _pickerState.footerHandler = consoleReady ? () => _pickerDoAdd(false) : null;
      _showTwoButtons(false, null);
    }
    return;
  } else if (_pickerState.tab === "part") {
    text.innerHTML = sel ? `<span class="picker-foot-label">${esc(selName)}</span>${hint}` : `<span class="picker-foot-label">Pick a product</span>`;
    if (_pickerState.editLineId) {
      // Edit mode: single "Save edits" button, no "Add another".
      btn.textContent = "Save edits";
      btn.disabled = !(sel && ready);
      _pickerState.footerHandler = (sel && ready) ? _pickerDoAdd : null;
      _showTwoButtons(false, null);
    } else if (_pickerIsConsoleContext()) {
      _pickerApplyFixedPartLocation();
      text.innerHTML = `<span class="picker-foot-label">${esc(selName || "Choose console style and features")}</span>`;
      btn.textContent = "Set up Center Console →";
      btn.disabled = false;
      _pickerState.footerHandler = () => _pickerBeginConsoleSetup();
      _showTwoButtons(false, null);
    } else if (loc.selected && (_pickerState.tracer.active || _pickerState.innerEdge.active || _pickerState.outerEdge.active || _pickerSelIsFixture() || hasAutomaticLocation)) {
      // Auto-located tracer/fixture/license-plate bracket: part has one
      // resolved location → show both finish buttons on the part tab.
      // → show both finish buttons here on the part tab (skip-location path).
      btn.textContent = "Add and Finish";
      btn.disabled = !(sel && ready);
      _pickerState.footerHandler = (sel && ready) ? () => _pickerDoAdd(false) : null;
      _showTwoButtons(sel && ready, _pickerDoAdd);
    } else {
      btn.textContent = "Add details →";
      btn.disabled = !(sel && detailsEntryReady);
      _pickerState.footerHandler = (sel && detailsEntryReady) ? () => _pickerSwitchTab("location") : null;
      _showTwoButtons(false, null);
    }
  } else {
    const where = loc.selected ? _pickerTitleCase(loc.selected) : "";
    text.innerHTML = sel ? `<span class="picker-foot-label">${esc(selName)}${where ? " → " + esc(where) : ""}</span>${hint}` : `<span class="picker-foot-label">Pick a product first</span>`;
    const canAdd = !!(sel && loc.selected && ready && _pickerCustomLocationReady());
    // Location tab is the normal final screen — always show two buttons here
    // (spec §3 Step 7 "on the location step normally").
    btn.textContent = "Add and Finish";
    btn.disabled = !canAdd;
    _pickerState.footerHandler = canAdd ? () => _pickerDoAdd(false) : null;
    _showTwoButtons(canAdd, _pickerDoAdd);
  }
}

// ── Resolve + add ──────────────────────────────────────

// Step 7: shared post-add finalization.
// addAndContinue=false → close picker (today's behavior).
// addAndContinue=true  → load manifest so green dots refresh, then reset picker
//   state and re-render the browse tree at the preserved expansion position.
async function _pickerFinalize(draftId, addAndContinue) {
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  if (addAndContinue) {
    // Load manifest before resetting so _meDraft is updated when the browse tree
    // re-renders (ensures the just-added part type shows green immediately).
    if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
    _pickerResetState();
    _pickerOpenPanel("Add Part");
    _pickerSwitchTab("part");
  } else {
    pickerClose();
    if (typeof loadDraftManifest === "function") await loadDraftManifest(draftId);
    if ($("card-preview") && !$("card-preview").hidden && typeof pvLoad === "function") pvLoad(draftId);
  }
}

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

// A family may use one shared manifest name even though its individual
// part_types remain distinct for grouping, editing, and catalog matching.
function _pickerFamilyPartLabel(filters = _pickerState.filters) {
  const familyId = filters?.family_id || "";
  if (!familyId) return "";
  for (const category of (_pickerState.browseTree || [])) {
    const family = (category.children || []).find(child => child.kind === "family" && child.family_id === familyId);
    if (family?.picker_part_label) return family.picker_part_label;
  }
  return "";
}

// Pick the next auto-sequenced name by counting existing draft parts with the
// same base name (e.g. 2 existing "Forward Warning *" → "Forward Warning 3").
function _pickerChooseName(loc) {
  return _pickerFamilyPartLabel() || _pickerSequencedName(loc.name_pattern, loc.base_label);
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

// The draft service merges a second matching single speaker into the existing
// parent line.  Rebuild its bracket choices as a pair before child lines are
// written, otherwise the second speaker's bracket would replace the first.
function _pickerPrepareMergedSpeakerAccessories(parentLineId, quantity) {
  if (!_pickerIsSirenSpeakerContext() || quantity !== 2 || !parentLineId) return;
  const group = _pickerVisibleAccessoryGroups().find(item => item.category === "bracket_mount");
  if (!group) return;
  const previousChild = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).find(part =>
    part.parent_line_id === parentLineId && part.accessory_category === "bracket_mount"
  );
  const previousPick = previousChild ? _pickerAccessoryChoiceForChild([group], previousChild)?.pick : "";
  const current = _pickerState.accessoryChoices[group.category];
  const currentPick = (Array.isArray(current) ? current : [current]).find(value => value) || "";
  _pickerState.config.count = 2;
  _pickerState.accessoryChoices[group.category] = [previousPick || "none", currentPick || "none"];
}

async function _pickerDoAdd(addAndContinue) {
  const sel = _pickerState.sel, loc = _pickerState.loc, f = _pickerState.filters;
  if (_pickerState.radio && _pickerState.radio.active) {
    await _pickerAddSystem(addAndContinue);
    return;
  }
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
  if (_pickerState.tracer.active) { await _pickerAddTracer(draftId, addAndContinue); return; }
  if (_pickerState.innerEdge.active) { await _pickerAddInnerEdge(draftId, addAndContinue); return; }
  if (_pickerState.outerEdge.active) { await _pickerAddOuterEdge(draftId, addAndContinue); return; }
  if (_pickerState.lightbar.active) { await _pickerAddLightbar(draftId, addAndContinue); return; }

  const product = _pickerState.products.find(p => p.product_id === sel.product_id);
  const isWindowTint = _pickerIsWindowTint(product);
  const isScene = _pickerProductCategory(product) === "scene";
  // Color path only for color-configured products; a direct SKU pick (sel.sku,
  // e.g. a programmable bar) always uses the simple single-SKU path.
  const usesColor = !isScene && _pickerUsesColor(product)
    && !sel.sku && _pickerProductHasColor(product || { skus: [] });
  const locName = loc.selected;   // raw layout key (planner upper-cases to match)

  // In edit mode preserve the original part name (never re-sequence — the
  // user edited "Forward Warning 1", it must stay "Forward Warning 1").
  // Pre-fill (Step 6) ensures the picker is already in the right state, so
  // recomputing name/color from picker state gives the stored values back.
  const editing = !!_pickerState.editLineId;
  const ep = _pickerState.editPart;
  let baseName = editing ? ep.name : (_pickerChooseName(loc) || sel.model);

  // Picker config snapshot to persist on the saved part (Step 6).
  const c = _pickerState.config;
  const pickerConfig = {
    mode: c.mode, colorsPerHead: c.colorsPerHead,
    uniform: [...c.uniform], splitSecondary: [...c.splitSecondary],
    custom: c.custom.map(a => [...a]), _noColor: c._noColor || false,
    count: c.count, lens: f.lens || "",
    skuChoices: { ..._pickerState.skuChoices },
    details: (_pickerControlHeadRequiresPaMic() || _pickerControlHeadOffersHandheldMagMic())
      ? { ..._pickerState.partDetails } : {},
  };
  if (isWindowTint) {
    pickerConfig.window_tint = {
      windows: [..._pickerState.tint.windows],
      percentage: Number(_pickerState.tint.percentage),
      unit_price: 65,
    };
  }
  if (_pickerUsesLocationAllocation(product)) {
    const activeComments = {};
    for (const [location, quantity] of Object.entries(_pickerState.locationAllocation.quantities || {})) {
      if (Number(quantity) > 0) activeComments[location] = String(_pickerState.locationAllocation.comments?.[location] || "");
    }
    pickerConfig.location_batch_id = _pickerState.locationAllocation.batchId || "";
    pickerConfig.location_allocation = {
      quantities: { ..._pickerState.locationAllocation.quantities },
      comments: activeComments,
      batch_id: _pickerState.locationAllocation.batchId || "",
    };
    pickerConfig.round_light = { warning_color: _pickerState.roundLightColor === "blue" ? "blue" : "red" };
  }
  if (_pickerIsSirenSpeakerContext()) pickerConfig.siren_dual_tones = _pickerState.sirenDualTones === true;
  if (_pickerState.westin?.active) {
    pickerConfig.westin = {
      wire: _pickerState.westin.wire,
      channel: _pickerState.westin.channel,
      channel_info: _pickerState.westin.channelInfo,
      lights: { ..._pickerState.westin.lights },
    };
  }
  if (loc.textCustom) {
    _pickerRefreshCustomPlacementGroups();
    pickerConfig.custom_location = {
      label: String(loc.selected || "").trim(),
      render_location: loc.renderLocation || "",
      placements: _pickerCustomPlacementSnapshot(),
      anchors: _pickerNormalizeCustomAnchors(loc.customPlacementAnchors),
      spacing: _pickerNormalizeCustomSpacing(loc.customHeadSpacing),
      layout: loc.customPlacementLayout === "mirrored_pairs" ? "mirrored_pairs" : "even",
    };
  }
  if (_pickerState.consoleSetup?.active) pickerConfig.console_setup = _pickerConsoleSetupSnapshot();

  let combos, colorFields = {}, totalHeads = 0;
  if (_pickerUsesLocationAllocation(product)) {
    const warningColor = _pickerState.roundLightColor === "blue" ? "blue" : "red";
    const sku = _pickerRoundLightSku(product, warningColor);
    const quantity = _pickerLocationAllocationTotal();
    if (!sku || !quantity) { toast("Choose at least one install location and a Red or Blue round light", "error"); return; }
    const colors = [warningColor, "white"];
    combos = [{ colors, part_number: sku.part_number, quantity, price: sku.price ?? null }];
    totalHeads = quantity;
    colorFields = { raw_color: warningColor === "blue" ? "Blue/White" : "Red/White" };
    pickerConfig.mode = "uniform";
    pickerConfig.colorsPerHead = "duo";
    pickerConfig.uniform = [...colors];
    pickerConfig.splitSecondary = [];
    pickerConfig.custom = [];
    pickerConfig.count = quantity;
    pickerConfig.lens = "clear";
    pickerConfig.skuChoices = {};
  } else if (isScene) {
    // Scene products are physically white and the no-color filter is deliberate,
    // but their selected quantity still represents the number of modules to
    // bill and render.  Preserve each per-head SKU override while grouping
    // identical modules into one components entry.
    const sceneQty = Math.max(1, Math.min(12, c.count || 1));
    const sceneSorted = [...(product?.skus || [])].sort((a, b) => (a.price ?? 9e9) - (b.price ?? 9e9));
    const defaultSku = sceneSorted[0]?.part_number || "";
    const grouped = {};
    for (let h = 0; h < sceneQty; h++) {
      const partNumber = _pickerState.skuChoices["head_" + h] || defaultSku;
      if (!partNumber) { toast("Pick a scene light SKU", "error"); return; }
      const key = partNumber;
      if (!grouped[key]) {
        const sku = (product?.skus || []).find(item => item.part_number === partNumber) || {};
        grouped[key] = { colors: [], part_number: partNumber, quantity: 0, price: sku.price ?? null };
      }
      grouped[key].quantity++;
    }
    combos = Object.values(grouped);
    totalHeads = sceneQty;
  } else if (usesColor) {
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
    colorFields = _pickerColorFields();
  } else {
    const sku = sel.sku || (product && product.skus[0] && product.skus[0].part_number);
    if (!sku) { toast("Pick a SKU", "error"); return; }
    const skuObj = product.skus.find(s => s.part_number === sku) || {};
    const skuColors = [skuObj.color, skuObj.secondary_color, skuObj.tertiary_color].filter(Boolean);
    const qty = isWindowTint
      ? _pickerState.tint.windows.length
      : _pickerIsSirenSpeakerContext()
      ? Math.min(2, Math.max(1, _pickerState.config.count || 1))
      : 1;
    // Concrete SKUs can still have fixed colors. Preserve them so direct SKU
    // picks resolve the same preview asset as the color-guided path.
    combos = [{ colors: skuColors, part_number: sku, quantity: qty, price: skuObj.price || null }];
    if (skuColors.length) {
      const cap = value => value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
      const renderColors = [...skuColors].sort((a, b) => {
        const ai = _PICKER_COLOR_ORDER.indexOf(String(a).toLowerCase());
        const bi = _PICKER_COLOR_ORDER.indexOf(String(b).toLowerCase());
        return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
      });
      colorFields = { raw_color: renderColors.map(cap).join("/") };
    }
    totalHeads = qty;
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
  if (_pickerUsesLocationAllocation(product)) {
    const template = rows[0];
    const expandedComponents = [];
    for (const component of (template.components || [])) {
      const quantity = Math.max(1, Number(component.quantity) || 1);
      for (let index = 0; index < quantity; index++) expandedComponents.push({ ...component, quantity: 1 });
    }
    let componentIndex = 0;
    const allocations = (product.location_options || [])
      .map(location => [location, Math.max(0, Number(_pickerState.locationAllocation.quantities[location]) || 0)])
      .filter(([, quantity]) => quantity > 0);
    const supplyPayload = _pickerSupplyPayload();
    const allocationRows = allocations.map(([location, quantity]) => {
      const slice = expandedComponents.slice(componentIndex, componentIndex + quantity);
      componentIndex += quantity;
      const grouped = new Map();
      for (const component of slice) {
        const key = [component.part_number, JSON.stringify(component.colors || []), component.price].join("|");
        const existing = grouped.get(key);
        if (existing) existing.quantity += 1;
        else grouped.set(key, { ...component, quantity: 1 });
      }
      return {
        ...template,
        ...supplyPayload,
        quantity,
        location,
        components: [...grouped.values()],
        comment: String(_pickerState.locationAllocation.comments?.[location] || "").trim(),
        picker_config: pickerConfig,
        ...(partTypeId ? { part_type: partTypeId } : {}),
      };
    });
    try {
      const result = await api(`/api/draft/${draftId}/location-allocation`, {
        batch_id: _pickerState.locationAllocation.batchId || "",
        edit_line_id: _pickerState.editLineId || "",
        rows: allocationRows,
      });
      if (result?.ok) {
        ok = allocationRows.length;
        parentLineId = result.line_id || "";
        _pickerState.locationAllocation.batchId = result.batch_id || "";
      }
    } catch (error) {
      console.error("location allocation save failed:", error);
    }
  } else for (const row of rows) {
    try {
      const endpoint = _pickerState.editLineId
        ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
        : `/api/draft/${draftId}/part`;
      // Include picker_config so Edit can pre-fill exactly (Step 6).
      const detailNote = _pickerPartDetailsNote();
      const detailComponent = _pickerPartDetailsComponent();
      const sirenDualToneComponent = _pickerSirenDualToneComponent();
      const supplyPayload = _pickerState.consoleSetup?.active
        ? _pickerSupplyPayload(_pickerSupplyFromRecord(_pickerState.consoleSetup.choices?.consoleChoice || {}))
        : _pickerSupplyPayload();
      const payload = {
        ...row,
        ...supplyPayload,
        comment: _pickerState.comment || "",
        ...(detailNote ? { notes: detailNote } : {}),
        components: [
          ...(row.components || []),
          ...(detailComponent ? [detailComponent] : []),
          ...(sirenDualToneComponent ? [sirenDualToneComponent] : []),
        ],
        picker_config: pickerConfig,
        ...(partTypeId ? { part_type: partTypeId } : {}),
      };
      if (isWindowTint) {
        payload.name = "Window Tint";
        payload.quantity = _pickerState.tint.windows.length;
        payload.location = _pickerState.tint.windows.map(_pickerTintLabel).join(", ");
        payload.notes = `${Number(_pickerState.tint.percentage)}% tint`;
        payload.components = [];
      }
      const r = await api(endpoint, payload);
      if (r?.ok) {
        ok++;
        if (!parentLineId && r.line_id) parentLineId = r.line_id;
        // The draft service may normalize a cardinality-aware parent name
        // (one Control Head → two Control Head 1/2 rows). Use its final name
        // for any accessory child created immediately afterward.
        if (r.name) baseName = r.name;
        if (r.merged) {
          _pickerPrepareMergedSpeakerAccessories(parentLineId, r.quantity);
        }
      }
    } catch (e) { console.error("add row failed:", e); }
  }
  if (!ok) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }

  if (_pickerState.consoleSetup?.active) {
    try {
      await _pickerReplaceConsoleSetupParts(draftId, parentLineId, baseName);
    } catch (error) {
      console.error("console component save failed:", error);
      toast("Console saved, but its component lines could not be updated", "error");
      if (btn) btn.disabled = false;
      return;
    }
  }

  if (partTypeId === "control_head") {
    try {
      const magMicSelection = _pickerControlHeadOffersHandheldMagMic()
        ? (_pickerState.partDetails?.handheldMagMic === true ? "magnetic_mic" : "")
        : (_pickerControlHeadRequiresPaMic() ? _pickerState.partDetails?.paMicClip : "");
      await _pickerReplaceMagneticMicChild(
        draftId, parentLineId, baseName,
        _pickerControlHeadRequiresPaMic() ? _pickerPaMicLocation() : locName,
        magMicSelection,
        _pickerSupplyPayload(),
      );
    } catch (error) {
      console.error("PA magnetic mic save failed:", error);
      toast("Control head saved, but its magnetic mic line could not be updated", "error");
      if (btn) btn.disabled = false;
      return;
    }
  }

  // Accessories are real child lines. Recreate the selected set on parent
  // edits so the picker remains the authoritative editor, while individual
  // child edits still work as their own manifest actions.
  try {
    await _pickerReplaceAccessoryChildren(draftId, parentLineId, baseName, locName);
  } catch (error) {
    console.error("accessory save failed:", error);
    toast("Part saved, but its accessories could not be updated", "error");
    if (btn) btn.disabled = false;
    return;
  }
  if (!_pickerState.editLineId) {
    try {
      for (const wrow of _pickerChosenWestinRows(baseName, locName, parentLineId)) {
        const result = await api(`/api/draft/${draftId}/part`, wrow);
        if (!result?.ok) throw new Error(result?.error || "could not add Westin bumper option");
        if (wrow.accessory_category === "westin_light_channel") {
          await _pickerAddWestinChannelLights(draftId, parentLineId);
        }
      }
    } catch (error) {
      console.error("add Westin bumper option failed:", error);
      toast("Bumper saved, but its Westin options could not be added", "error");
      if (btn) btn.disabled = false;
      return;
    }
  }
  toast(_pickerState.editLineId ? "Part updated" : "Part added", "success");
  await _pickerFinalize(draftId, addAndContinue);
}

// Add a resolved tracer: each housing → a parent line tagged Duo/Trio, its
// heads nested beneath as lighthead children. Re-resolves server-side so the
// add matches the latest choice (mode/secondary/lens).
async function _pickerAddTracer(draftId, addAndContinue) {
  const sel = _pickerState.sel, loc = _pickerState.loc, t = _pickerState.tracer;
  const locName = loc.selected;
  const baseName = _pickerChooseName(loc) || sel.model;
  const lens = t.lens === "smoked" ? "smoked" : "clear";
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
      ..._pickerSupplyPayload(), lens, notes, comment: _pickerState.comment || "",
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
  await _pickerFinalize(draftId, addAndContinue);
}

function _pickerInnerEdgeColorFields(ie) {
  const secondary = ie.secondary === "amber" ? "Amber" : "White";
  if (ie.mode === "trio") {
    return {
      raw_color: `Red/Blue/${secondary}`,
      explicit_color_profile: ie.secondary === "amber" ? "std_tri_rba" : "std_tri_rbw",
    };
  }
  return ie.secondary === "amber"
    ? { raw_color: "Red/Amber Blue/Amber" }
    : { raw_color: "Red/White Blue/White" };
}

async function _pickerReplaceInnerEdgeHeadChildren(draftId, parentLineId) {
  if (!_pickerState.editLineId) return;
  const productId = _pickerState.sel?.product_id || "";
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId
    && part.accessory_category === "lighthead"
    && (!part.accessory_parent_product || part.accessory_parent_product === productId)
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace an Inner Edge head line");
  }
}

// Add or update one configured Inner Edge housing. The selected housing SKU
// remains qty 1; its concrete QB head lines are separate nested children.
async function _pickerAddInnerEdge(draftId, addAndContinue) {
  const sel = _pickerState.sel, loc = _pickerState.loc, ie = _pickerState.innerEdge;
  const baseName = _pickerChooseName(loc) || sel.model;
  const button = $("picker-add-btn"); if (button) button.disabled = true;
  let resolved;
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&part_number=${encodeURIComponent(sel.sku)}`
      + `&mode=${encodeURIComponent(ie.mode)}&secondary=${encodeURIComponent(ie.secondary)}`;
    resolved = await api(`/api/parts-db/inner-edge-heads?${qs}`);
  } catch (error) {
    console.error("Inner Edge resolve failed:", error);
    toast("Resolve failed", "error"); if (button) button.disabled = false; return;
  }
  if (!resolved?.ok) { toast("Can't build this Inner Edge configuration yet", "error"); if (button) button.disabled = false; return; }
  const housing = (resolved.lines || []).find(line => line.kind === "housing");
  if (!housing?.sku) { toast("Nothing to add", "error"); if (button) button.disabled = false; return; }

  const secondary = ie.secondary === "amber" ? "Amber" : "White";
  const productName = sel.product_id === "whelen_fst" ? "FST" : "RST";
  const coverageLabel = sel.product_id === "whelen_fst"
    ? ({ both: "driver + passenger modules", driver: "driver module only", passenger: "passenger module only" }[ie.coverage] || "driver + passenger modules")
    : "full-width rear module";
  const notes = [
    `Inner Edge ${productName}`, `${resolved.lamp_count} heads`,
    ie.mode === "trio" ? `Standard Trio · Red/Blue/${secondary}` : `Standard Duo · driver Red/${secondary} / passenger Blue/${secondary}`,
    coverageLabel,
  ].join(" · ");
  const pickerConfig = {
    inner_edge: {
      product_id: sel.product_id, lamp_count: resolved.lamp_count,
      mode: ie.mode, secondary: ie.secondary, coverage: ie.coverage,
    },
  };
  const parentRow = {
    name: baseName, location: loc.selected, manufacturer: sel.mfr || "",
    part_number: housing.sku, quantity: 1, ..._pickerSupplyPayload(),
    notes, comment: _pickerState.comment || "", part_type: _pickerResolvedPartTypeId(_pickerState.filters),
    picker_config: pickerConfig, ..._pickerInnerEdgeColorFields(ie),
  };
  let parentLineId = "";
  try {
    const endpoint = _pickerState.editLineId
      ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
      : `/api/draft/${draftId}/part`;
    const result = await api(endpoint, parentRow);
    if (!result?.ok) throw new Error(result?.error || "could not save Inner Edge housing");
    parentLineId = result.line_id || _pickerState.editLineId || "";
    await _pickerReplaceInnerEdgeHeadChildren(draftId, parentLineId);
  } catch (error) {
    console.error("Inner Edge housing save failed:", error);
    toast("Inner Edge could not be saved", "error"); if (button) button.disabled = false; return;
  }

  const cap = value => value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
  for (const head of (resolved.lines || []).filter(line => line.kind === "head" && line.sku)) {
    const label = [cap(head.side), (head.colors || []).map(cap).join("/")].filter(Boolean).join(" ");
    try {
      const result = await api(`/api/draft/${draftId}/part`, {
        name: `${baseName} · Inner Edge ${label}`, location: loc.selected,
        manufacturer: sel.mfr || "", part_number: head.sku, quantity: head.qty || 1,
        new_or_used: "New", source: "", parent_line_id: parentLineId,
        accessory_category: "lighthead", accessory_parent_product: sel.product_id,
      });
      if (!result?.ok) throw new Error(result?.error || "could not save an Inner Edge head");
    } catch (error) {
      console.error("Inner Edge head save failed:", error);
      toast("Inner Edge saved, but one or more head lines could not be added", "error");
      if (button) button.disabled = false;
      return;
    }
  }
  try {
    // Shrouds were previously offered for Inner Edge in error. Drop any old
    // nested shroud when this bar is saved so the manifest remains correct.
    await _pickerReplaceAccessoryChildren(
      draftId, parentLineId, baseName, loc.selected, ["shroud"],
    );
  } catch (error) {
    console.error("Inner Edge accessory save failed:", error);
    toast("Inner Edge saved, but its accessories could not be updated", "error");
    if (button) button.disabled = false;
    return;
  }
  toast(_pickerState.editLineId ? "Inner Edge updated" : "Inner Edge added", "success");
  await _pickerFinalize(draftId, addAndContinue);
}

function _pickerOuterEdgeColorFields(oe) {
  if (oe.mode === "trio") {
    return { raw_color: "Red/Blue/Amber", explicit_color_profile: "std_tri_rba" };
  }
  return oe.secondary === "amber"
    ? { raw_color: "Red/Amber Blue/Amber" }
    : { raw_color: "Red/White Blue/White" };
}

async function _pickerReplaceOuterEdgeHeadChildren(draftId, parentLineId) {
  if (!_pickerState.editLineId) return;
  const productId = _pickerState.sel?.product_id || "";
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId
    && part.accessory_category === "lighthead"
    && (!part.accessory_parent_product || part.accessory_parent_product === productId)
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace an Outer Edge ION line");
  }
}

// Add or update the selected rear-pillar housing plus its six included IONs.
// The IONs are real QB rows (normally no-charge when ordered with the housing),
// not a display-only color choice, so estimates and manifests stay complete.
async function _pickerAddOuterEdge(draftId, addAndContinue) {
  const sel = _pickerState.sel, loc = _pickerState.loc, oe = _pickerState.outerEdge;
  const baseName = _pickerState.editLineId && _pickerState.editPart
    ? _pickerState.editPart.name : (_pickerChooseName(loc) || sel.model);
  const button = $("picker-add-btn"); if (button) button.disabled = true;
  let resolved;
  try {
    const qs = `product_id=${encodeURIComponent(sel.product_id)}&part_number=${encodeURIComponent(sel.sku)}`
      + `&secondary=${encodeURIComponent(oe.secondary)}`;
    resolved = await api(`/api/parts-db/outer-edge-pillar-heads?${qs}`);
  } catch (error) {
    console.error("Outer Edge pillar resolve failed:", error);
    toast("Resolve failed", "error"); if (button) button.disabled = false; return;
  }
  if (!resolved?.ok) { toast("Can't build this Outer Edge pillar configuration yet", "error"); if (button) button.disabled = false; return; }
  const housing = (resolved.lines || []).find(line => line.kind === "housing");
  if (!housing?.sku) { toast("Nothing to add", "error"); if (button) button.disabled = false; return; }

  const colorLabel = oe.mode === "trio"
    ? "six Red/Blue/Amber IONs"
    : `three Red/${oe.secondary === "amber" ? "Amber" : "White"} + three Blue/${oe.secondary === "amber" ? "Amber" : "White"} IONs`;
  const parentRow = {
    name: baseName, location: loc.selected, manufacturer: sel.mfr || "",
    part_number: housing.sku, quantity: 1, ..._pickerSupplyPayload(),
    notes: `Outer Edge rear pillar · ${colorLabel}`, comment: _pickerState.comment || "",
    // Warning light remains the canonical data home; the automatic rear
    // location above supplies the manifest-facing "Rear Warning" name.
    part_type: "warning_light",
    picker_config: {
      outer_edge_pillar: {
        product_id: sel.product_id, housing_part_number: housing.sku,
        mode: oe.mode, secondary: oe.secondary, head_count: 6,
      },
    },
    ..._pickerOuterEdgeColorFields(oe),
  };
  let parentLineId = "";
  try {
    const endpoint = _pickerState.editLineId
      ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
      : `/api/draft/${draftId}/part`;
    const result = await api(endpoint, parentRow);
    if (!result?.ok) throw new Error(result?.error || "could not save Outer Edge pillar housing");
    parentLineId = result.line_id || _pickerState.editLineId || "";
    await _pickerReplaceOuterEdgeHeadChildren(draftId, parentLineId);
  } catch (error) {
    console.error("Outer Edge pillar housing save failed:", error);
    toast("Outer Edge pillar could not be saved", "error"); if (button) button.disabled = false; return;
  }

  const cap = value => value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
  for (const head of (resolved.lines || []).filter(line => line.kind === "head" && line.sku)) {
    const label = (head.colors || []).map(cap).join("/");
    try {
      const result = await api(`/api/draft/${draftId}/part`, {
        name: `${baseName} · Outer Edge ION ${label}`, location: loc.selected,
        manufacturer: sel.mfr || "", part_number: head.sku, quantity: head.qty || 1,
        new_or_used: "New", source: "", parent_line_id: parentLineId,
        accessory_category: "lighthead", accessory_parent_product: sel.product_id,
      });
      if (!result?.ok) throw new Error(result?.error || "could not save an Outer Edge ION");
    } catch (error) {
      console.error("Outer Edge ION save failed:", error);
      toast("Outer Edge pillar saved, but one or more included IONs could not be added", "error");
      if (button) button.disabled = false;
      return;
    }
  }
  toast(_pickerState.editLineId ? "Outer Edge pillar updated" : "Outer Edge pillar added", "success");
  await _pickerFinalize(draftId, addAndContinue);
}

// Add a roof lightbar: the chosen configured SKU plus the setup/edition tags.
// The Standard/Custom + edition + order notes ride on the part's lens/notes so
// the build sheet and estimate carry them for ordering.
async function _pickerAddLightbar(draftId, addAndContinue) {
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
      part_number: sel.sku, quantity: 1, ..._pickerSupplyPayload(), lens, notes, comment: _pickerState.comment || "",
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
  await _pickerFinalize(draftId, addAndContinue);
}
