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
  filters: { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", family_id: "", family_label: "", part_type_id: "", part_type_label: "", brand: "", lens: "" },
  config: { count: 2, colorsPerHead: "single", mode: "uniform", uniform: ["red"], splitSecondary: [], custom: [], _noColor: false },
  availAll: new Set(),
  search: "",
  searchGlobal: true,
  allProducts: null,
  products: [],            // [{product_id, model, manufacturer_label, skus:[...]}]
  expanded: new Set(),     // product_ids whose SKU list is open
  sel: null,               // { product_id, model, mfr, sku? }  current selection
  loc: { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, textCustom: false, name_pattern: "", base_label: "" },
  partDetails: { paMicLocation: "", paMicLocationCustom: "", paMicClip: "" },
  accessories: [],         // resolved [{category,label,required,options:[...]}] for current product
  accessoryChoices: {},    // category_id → select value ("" | "none" | "<product_id>::<sku>")
  accLoadedFor: null,      // product_id accessories were loaded for
  tracer: { active: false, mode: "trio", secondary: "white", custom: {}, preview: null, loading: false },
  lightbar: { active: false, setup: "standard", edition: "clear", notes: "" },
  // `radio` is the shared guided-system state.  The name is retained for
  // backwards-compatible smoke hooks while the picker now serves radio,
  // radar, and camera system families through the same question engine.
  radio: { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 },
  systemSetup: { active: false, kind: "", product: null },
  // Center consoles are a parent SKU plus a curated, ordered set of real
  // child SKUs. Keep that setup separate from the radio/radar/camera kit
  // engine: its faceplate order is edited directly rather than as questions.
  consoleSetup: { active: false, loading: false, catalog: {}, choices: {}, faceplateSearch: "", showAllFaceplates: false, openComponent: "" },
  vehicleOnly: true,       // hide parts/accessories not compatible with the draft's vehicle
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
  } else if (_PREF_CAGE_PART_TYPES.has(f.part_type_id)) {
    want = prefs.cage_brand || "";
  } else if (_PREF_CAMERA_PART_TYPES.has(f.part_type_id)) {
    want = prefs.camera_brand || "";
  } else if (_PREF_CONSOLE_PART_TYPES.has(f.part_type_id)) {
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
    const systemKind = { radio_comms: "radio", radar: "radar", camera_system: "camera" }[target.family_id];
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
  c._noColor = target.flow === "scene" || target.flow === "interior";
  _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerBrowseExpanded.types.add(target.type_id);
  if (target.family_id) _pickerBrowseExpanded.families.add(target.family_id);
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
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = { active: false, wire: "", channel: "" };
  _pickerRenderTracer(); _pickerRenderLightbar(); _pickerRenderRadio();
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
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = { active: false, wire: "", channel: "" };
  _pickerState.accessories = []; _pickerState.accessoryChoices = {}; _pickerState.accLoadedFor = null;
  _pickerResetLocation();
  _pickerRenderProducts();
  _pickerRenderTracer(); _pickerRenderLightbar(); _pickerRenderRadio(); _pickerRenderAccessories();
  _pickerUpdateFooter();
}

// PICKER_REDESIGN.md Step 6: full pre-fill + type-lock replacing the F-005 stopgap.
// Opens the picker with every filter, product box, and option already set to
// exactly the state the user left when they added/last-saved this part.
async function _pickerOpenEdit(part) {
  if (!part) return;
  _pickerResetState();
  _pickerState.editLineId = part.line_id;
  _pickerState.editPart = part;
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
  _pickerState.filters.part_type_id = partTypeId;
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
    // scene/interior default to _noColor
    c._noColor = (foundCategoryId === "scene" || foundCategoryId === "interior");
  }
  _pickerState.partDetails = {
    paMicLocation: pc.details?.paMicLocation || "",
    paMicLocationCustom: pc.details?.paMicLocationCustom || "",
    paMicClip: pc.details?.paMicClip || "",
  };

  // ── 3. Pre-set location so Save from the Part tab works without touching Location ──
  _pickerState.loc.selected = part.location || null;

  // ── 4. Fetch products and pre-select ──────────────────────────────────────
  await _pickerFetchProducts();
  const pn = (part.components && part.components[0] && part.components[0].part_number) || part.part_number;
  const prod = _pickerState.products.find(p => p.skus.some(s => s.part_number === pn));
  if (prod) {
    // For color products (warning/interior lights) sel.sku must NOT be set —
    // `usesColor` in _pickerDoAdd is gated on `!sel.sku`, and skuChoices carries
    // the per-head overrides. For non-color products (equipment, programmable
    // bars) sel.sku identifies the exact chosen SKU.
    const pColor = _pickerUsesColor() && _pickerProductHasColor(prod);
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
  }
  if (_pickerHasFixedPartLocation() && pc.console_setup) {
    await _pickerBeginConsoleSetup(pc.console_setup);
    return;
  }
  _pickerSwitchTab("part");
}

// ── Shell ──────────────────────────────────────────────

function _pickerResetState() {
  _pickerState.open = true;
  _pickerState.editLineId = null;
  _pickerState.editPart = null;
  _pickerState.tab = "part";
  _pickerState.step = 0;          // current left-pane wizard step
  _pickerState.filters = { type_id: "lights", type_label: "Lights", category_id: "", category_label: "", family_id: "", family_label: "", part_type_id: "", part_type_label: "", brand: "", lens: "" };
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
  _pickerState.loc = { layouts: null, vehicle: "", view: "front", locByName: {}, dotNames: [], selected: null, textCustom: false, name_pattern: "", base_label: "" };
  _pickerState.partDetails = { paMicLocation: "", paMicLocationCustom: "", paMicClip: "" };
  _pickerState.accessories = [];
  _pickerState.accessoryChoices = {};
  _pickerState.accLoadedFor = null;
  _pickerState.tracer = { active: false, mode: "trio", secondary: "white", custom: {}, preview: null, loading: false };
  _pickerState.lightbar = { active: false, setup: "standard", edition: "clear", notes: "" };
  _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.consoleSetup = _pickerNewConsoleSetup();
  _pickerState.westin = { active: false, wire: "", channel: "" };
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
      const ptParam = f.part_type_id ? `&part_type=${encodeURIComponent(f.part_type_id)}` : "";
      const familyParam = (!f.part_type_id && f.family_id) ? `&family=${encodeURIComponent(f.family_id)}` : "";
      const url = `/api/parts-db/category-skus?type=${encodeURIComponent(f.type_id)}&category=${encodeURIComponent(f.category_id || "")}${familyParam}${ptParam}`;
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
  // Auto-expand when only one product remains.
  if (_pickerState.products.length === 1) _pickerState.expanded.add(_pickerState.products[0].product_id);
}

function _pickerUseGlobalSearch() {
  return !!(_pickerState.search && _pickerState.search.trim() && _pickerState.searchGlobal);
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

  el.innerHTML = `<div class="pf-group pf-search"><input type="text" id="pf-search" placeholder="🔍 Search products / SKUs" value="${esc(_pickerState.search)}">
      <label class="pf-search-scope"><input type="checkbox" id="pf-search-current"${_pickerState.searchGlobal ? "" : " checked"}> Current filters only</label></div>
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

  const editPT = _pickerState.editLineId ? _pickerState.editPart?.part_type : null;

  const leafHtml = (pt, cat, pickerFlow, family = null) => {
    const isFilled = filled.has(pt.part_type_id);
    const active = _pickerState.filters.part_type_id === pt.part_type_id && _pickerState.filters.type_id === cat.type_id;
    // Type-lock (Step 6): in edit mode, dim leaves that are NOT the locked part_type.
    const locked = !!editPT && pt.part_type_id !== editPT;
    return `<button class="pbt-leaf${isFilled ? " filled" : ""}${active ? " active" : ""}${locked ? " locked" : ""}"
      data-type="${esc(cat.type_id)}" data-type-label="${esc(cat.label)}"
      data-family="${esc(family?.family_id || "")}" data-family-label="${esc(family?.label || "")}"
      data-pt="${esc(pt.part_type_id)}" data-pt-label="${esc(pt.label)}"
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

    if (child.browse_collapsed) {
      return `<div class="pbt-fam pbt-fam-collapsed">${famSelectHtml(child, cat)}</div>`;
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

  if (isSceneInterior) {
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
  $("pf-search")?.addEventListener("input", async e => {
    _pickerState.search = e.target.value;
    await _pickerFetchProducts();
    _pickerRenderProducts();
    _pickerUpdateFooter();
  });
  $("pf-search-current")?.addEventListener("change", async e => {
    _pickerState.searchGlobal = !e.target.checked;
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
    f.part_type_id = ""; f.part_type_label = "";
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
    if (_pickerState.editLineId && _pickerState.editPart?.part_type && b.dataset.pt && b.dataset.pt !== _pickerState.editPart.part_type) return;
    const familyId = b.dataset.family || "";
    const partTypeId = b.dataset.pt || "";
    const wasSelected = !!familyId && !partTypeId
      && f.type_id === b.dataset.type && f.family_id === familyId && !f.part_type_id;
    const wasOpen = !!familyId && _pickerBrowseExpanded.families.has(familyId);
    f.type_id = b.dataset.type; f.type_label = b.dataset.typeLabel;
    f.family_id = familyId; f.family_label = b.dataset.familyLabel || "";
    f.part_type_id = partTypeId; f.part_type_label = b.dataset.ptLabel;
    if (familyId && !partTypeId) {
      if (wasSelected && wasOpen) _pickerBrowseExpanded.families.delete(familyId);
      else _pickerBrowseExpanded.families.add(familyId);
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
    // Scene/interior lights are white — default to NO color filter (all SKUs
    // match); the user opts into a color only if they want one. Other light
    // categories keep the normal per-color selection.
    c._noColor = (flow === "scene" || flow === "interior");
    _pickerState.sel = null; _pickerState.expanded = new Set(); _pickerState.skuChoices = {};
    _pickerState.radio = { active: false, kind: "", loading: false, products: {}, choices: {}, step: 0 };
    _pickerState.systemSetup = { active: false, kind: "", product: null };
    _pickerState.consoleSetup = _pickerNewConsoleSetup();
    await _pickerFetchProducts();
    if (["radio_comms", "radar", "camera_system"].includes(familyId) && !partTypeId && !_pickerState.editLineId) {
      const systemKind = { radio_comms: "radio", radar: "radar", camera_system: "camera" }[familyId];
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

function _pickerComboLabel(hs) { return hs.length ? hs.map(x => x[0].toUpperCase() + x.slice(1)).join("/") : "Any color"; }

// A product is color-configured only if at least one SKU carries a color.
// Programmable (WeCanX) bars have none → picked directly by SKU.
function _pickerProductHasColor(p) {
  return (p.skus || []).some(s => s.color || s.secondary_color || s.tertiary_color);
}

function _pickerIsSirenSpeakerContext() {
  return _pickerResolvedPartTypeId(_pickerState.filters) === "siren_speaker";
}

function _pickerSirenQtyHtml() {
  const q = Math.min(2, Math.max(1, _pickerState.config.count || 1));
  return `<div class="pp-prod-options pp-siren-options">
    <div class="pf-group"><span class="pf-label">Speakers</span><div class="pf-pills">
      <button class="pf-pill${q === 1 ? " active" : ""}" data-siren-qty="1">1</button>
      <button class="pf-pill${q === 2 ? " active" : ""}" data-siren-qty="2">2</button>
    </div></div>
  </div>`;
}

function _pickerIsWestinBasePushBumper(product) {
  if (!product || !(product.fits_part_types || []).includes("push_bumper")) return false;
  const brand = String(product.manufacturer_label || product.manufacturer_id || "").toLowerCase();
  const model = String(product.model || "");
  return brand.includes("westin")
    && /push bumper/i.test(model)
    && !/light channel|wire cover/i.test(model);
}

function _pickerWestinOptionProducts(kind) {
  const veh = _pickerVehicle();
  const vehFiltering = _pickerState.vehicleOnly && !!veh;
  const re = kind === "wire" ? /wire cover/i : /light channel/i;
  return (_pickerState.products || []).filter(p => {
    const brand = String(p.manufacturer_label || p.manufacturer_id || "").toLowerCase();
    if (!brand.includes("westin") || !re.test(p.model || "")) return false;
    if (_pickerState.sel && p.product_id === _pickerState.sel.product_id) return false;
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
        const price = sku.price != null ? ` · $${sku.price}` : "";
        return `<option value="${esc(value)}"${_pickerState.westin[kind] === value ? " selected" : ""}>${esc(p.model)} · ${esc(sku.part_number || "")}${price}</option>`;
      })
      .join("");
    return `<div class="pf-group"><span class="pf-label">${esc(label)}</span><select class="pp-westin-select" data-westin="${esc(kind)}">
      <option value="">None</option>${opts}</select></div>`;
  };
  return `<div class="pp-prod-options pp-westin-options">
    ${optHtml("wire", "Wire covers")}
    ${optHtml("channel", "Light channel")}
  </div>`;
}

function _pickerActivateWestinBumper(product) {
  const active = _pickerIsWestinBasePushBumper(product);
  if (!active) {
    _pickerState.westin = { active: false, wire: "", channel: "" };
    return;
  }
  if (!_pickerState.westin.active) _pickerState.westin = { active: true, wire: "", channel: "" };
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
    header = `<div class="pp-search-global">Searching all categories, brands, and vehicle tags</div>`;
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
  if (!globalSearch && vehFiltering) list = list.filter(p => p.skus.some(s => _skuCompatible(s, veh)));
  // Step 2: grid is no longer pre-sorted by color match — options live in the
  // product box and are configured per-product after selection, not before.
  list = [...list].sort((a, b) => {
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
    // Step 5: scene products (even no-color ones) also select on head-click and render
    // the qty+SKU box, so they share the selectsOnClick gate with color products.
    const selectsOnClick = pColor || (usesColor && f.category_id === "scene");
    let bodyHtml = "";
    if (open) {
      if (selectsOnClick && selected) {
        // Step 5: branch on scene (category == "scene" covers all scene_lights family
        // members — front_scene/rear_scene/side_scene/spotlight share picker_flow "scene").
        if (f.category_id === "scene") {
          // Scene box: qty control only (no mode/lens/color/cph/remove-options) +
          // per-head SKU dropdowns (all SKUs, unfiltered) + plain uncolored viz.
          bodyHtml = `<div class="pp-prod-options">${_pickerColorConfigHtml()}</div>`;
          const sceneCount = _pickerState.config.count;
          const sceneSorted = [...skus].sort((a, b) => (a.price ?? 9e9) - (b.price ?? 9e9));
          bodyHtml += `<div class="pp-skus">` + Array.from({ length: sceneCount }, (_, h) => {
            const headKey = "head_" + h;
            const chosen = _pickerState.skuChoices[headKey] || (sceneSorted[0] && sceneSorted[0].part_number) || "";
            const headTitle = `Head ${h + 1}: ${chosen || "—"}`;
            const opts = sceneSorted.map(s => `<option value="${esc(s.part_number)}"${s.part_number === chosen ? " selected" : ""}>${esc(s.part_number)}${s.price != null ? " · $" + s.price : ""}</option>`).join("");
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
          // Step 4: light visualization below SKU dropdowns in the selected product box.
          bodyHtml += `<div class="pp-viz"><span class="pp-viz-label">Preview</span>${_pickerHeadsPreviewHtml()}</div>`;
        }
      } else {
        if (selected && _pickerIsSirenSpeakerContext()) bodyHtml += _pickerSirenQtyHtml();
        if (selected) bodyHtml += _pickerWestinBumperHtml(p);
        bodyHtml += `<div class="pp-skus">` + skus.map(s => {
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
        <span class="pp-brandchip">${esc(p.manufacturer_label)}</span>
        <span class="pp-name">${esc(p.model)}</span>
        <span class="pp-meta">${skus.length} SKU${skus.length !== 1 ? "s" : ""}${priceStr ? " · " + priceStr : ""}</span>
        ${qb}
      </div>${bodyHtml}
    </div>`;
  }).join("");

  _pickerWireBrand(el);
  _pickerWireProductOptions(el);
  el.querySelectorAll(".pp-westin-select").forEach(sel => sel.addEventListener("change", () => {
    const k = sel.dataset.westin;
    if (k) _pickerState.westin[k] = sel.value;
    _pickerUpdateFooter();
  }));
  el.querySelectorAll("[data-siren-qty]").forEach(btn => btn.addEventListener("click", () => {
    _pickerState.config.count = Math.min(2, Math.max(1, parseInt(btn.dataset.sirenQty || "1", 10)));
    _pickerPlaceDots();
    _pickerRenderProducts();
    _pickerRenderAccessories();
    _pickerUpdateFooter();
  }));
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
    if (wasOpen && (!usesColor || (_pickerState.sel && _pickerState.sel.product_id === pid))) _pickerState.expanded.delete(pid);
    else _pickerState.expanded = new Set([pid]);
    // Color products select on head-click; no-color (programmable) products
    // select via the per-SKU "Select" pill instead.
    // Step 5: scene products select on head-click even when SKUs carry no color
    // (e.g. Unity spotlights) — they use the qty+SKU-dropdown path, not a pill.
    const nowUsesColor = _pickerUsesColor();
    const pColor = nowUsesColor && _pickerProductHasColor(p);
    const selectsOnClick = pColor || (nowUsesColor && f.category_id === "scene");
    if (selectsOnClick && (!_pickerState.sel || _pickerState.sel.product_id !== pid)) _pickerResetLocation();
    if (selectsOnClick) {
      _pickerState.sel = { product_id: pid, model: p.model, mfr: p.manufacturer_label }; _pickerState.skuChoices = {}; _pickerState.optionsRemoved = false;
      _pickerActivateWestinBumper(p);
    }
    if (contextChanged) _pickerRenderFilters();
    _pickerRenderProducts(); _pickerUpdateFooter();
    if (selectsOnClick) { _pickerLoadAccessories(pid); _pickerLoadTracer(pid); _pickerLoadLightbar(pid); _pickerLoadFixture(pid); _pickerApplyFixedPartLocation(); }
  }));
  el.querySelectorAll("[data-pick]").forEach(btn => btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const pid = btn.dataset.pid, p = _pickerState.products.find(x => x.product_id === pid);
    const contextChanged = _pickerApplyProductContext(p);
    if (!_pickerState.sel || _pickerState.sel.product_id !== pid) _pickerResetLocation();
    _pickerState.expanded = new Set([pid]);   // keep only this product expanded
    const nowUsesColor = _pickerUsesColor();
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
    if (k === "count") { c.count = Math.min(12, Math.max(1, c.count + parseInt(v, 10))); _pickerNormalizeConfig(); _pickerState.skuChoices = {}; _pickerRenderProducts(); _pickerUpdateFooter(); return; }
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

function _pickerPartDetailsSatisfied() {
  if (_pickerResolvedPartTypeId(_pickerState.filters) !== "control_head") return true;
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
  if (_pickerResolvedPartTypeId(_pickerState.filters) !== "control_head") return "";
  const location = _pickerPaMicLocation();
  const clip = _pickerPaMicClip();
  return location && clip ? `PA mic: ${location} · ${clip}` : "";
}

// Components are display-only manifest rows carried by the parent line. This
// makes the PA-mic placement visible to the shop without creating a second
// billable or renderable part in the build plan.
function _pickerPartDetailsComponent() {
  if (_pickerResolvedPartTypeId(_pickerState.filters) !== "control_head") return null;
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

function _pickerMagneticMicRow(parentLineId, parentName, location, selection) {
  const item = _MAGNETIC_MIC_ITEMS[selection];
  if (!item || !parentLineId) return null;
  return {
    name: `${parentName} · ${item.model}`,
    location: location || "", manufacturer: item.manufacturer, part_number: item.part_number,
    quantity: 1, new_or_used: "New", source: "", parent_line_id: parentLineId,
    accessory_category: "magnetic_mic", accessory_parent_product: "", part_type: "radio_mic_clip",
  };
}

async function _pickerReplaceMagneticMicChild(draftId, parentLineId, parentName, location, selection) {
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId && part.accessory_category === "magnetic_mic"
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace the magnetic mic line");
  }
  const row = _pickerMagneticMicRow(parentLineId, parentName, location, selection);
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
  if (_pickerResolvedPartTypeId(_pickerState.filters) !== "control_head") {
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
      const locationCopy = isControlHead ? {
        kicker: "Control head setup",
        question: "Where will the control head be mounted?",
        help: "Choose the control head location before setting up the PA microphone below.",
      } : {
        kicker: "Mounting location",
        question: "Where will this part be mounted?",
        help: "Choose a standard location or enter a shop-specific location.",
      };
      const setTextLocation = (value, entry = null, custom = false) => {
        loc.selected = value;
        loc.textCustom = custom;
        if (entry) {
          loc.name_pattern = entry.name_pattern || "";
          loc.base_label = entry.base_label || "";
          loc.catalog_names = entry.catalog_names || [];
          return;
        }
        // Custom/no-preset text locations still need a real, sequenceable
        // name so the planner can match the selected part type.
        const ptLabel = _pickerFreeTextPartTypeLabel(f);
        const single = _pickerFreeTextPartTypeMax(f) === 1;
        loc.name_pattern = ptLabel ? (single ? ptLabel : `${ptLabel} {n}`) : "";
        loc.base_label = ptLabel;
        loc.catalog_names = [];
      };
      if (dropdownLocs.length) {
        const sorted = [...dropdownLocs].sort((a, b) => a.location.localeCompare(b.location));
        const presetNames = new Set(sorted.map(l => l.location.toUpperCase()));
        const customActive = !!loc.textCustom || (!!loc.selected && !presetNames.has(loc.selected.toUpperCase()));
        const cards = sorted.map(l => {
          const selected = !customActive && loc.selected === l.location;
          return `<button type="button" class="picker-location-card${selected ? " is-selected" : ""}" data-text-location="${esc(l.location)}" aria-pressed="${selected ? "true" : "false"}">`
            + `<span class="picker-location-card-check">${selected ? "✓" : ""}</span><span>${esc(_pickerTitleCase(l.location))}</span></button>`;
        }).join("");
        btns.innerHTML = `<section class="picker-location-chooser"><div class="picker-location-kicker">${esc(locationCopy.kicker)}</div>`
          + `<h3>${esc(locationCopy.question)}</h3><p>${esc(locationCopy.help)}</p>`
          + `<div class="picker-location-grid">${cards}<button type="button" class="picker-location-card picker-location-card--custom${customActive ? " is-selected" : ""}" data-text-location-custom aria-pressed="${customActive ? "true" : "false"}">`
          + `<span class="picker-location-card-check">${customActive ? "✓" : ""}</span><span>Custom location<small>Enter a specific shop reference</small></span></button></div>`
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
        // No preset locations for this part type: keep a generous free-text
        // field, but give it the same deliberate presentation as card choices.
        setTextLocation(loc.selected || "", null, true);
        btns.innerHTML = `<section class="picker-location-chooser picker-location-chooser--custom"><div class="picker-location-kicker">${esc(locationCopy.kicker)}</div>`
          + `<h3>${esc(locationCopy.question)}</h3><p>Enter the shop-specific mounting location.</p>`
          + `<label class="picker-location-custom-field"><span>Custom shop location</span><input id="picker-loc-text" class="picker-location-custom-input" placeholder="Type the mount location" value="${esc(loc.selected || "")}"></label></section>`;
        const txt = $("picker-loc-text");
        if (txt) txt.addEventListener("input", () => {
          setTextLocation(txt.value.trim(), null, true);
          _pickerUpdateFooter();
        });
      }
    }
    _pickerRenderPartDetails();
    _pickerUpdateFooter();
    return;
  }
  // Exterior: image + dots
  if (stage) stage.classList.remove("picker-loc-stage--text");
  if (btns) btns.hidden = true;
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
  const pattern = loc.pattern || "single";
  let slotCount = loc.slot_count || 1;
  let slotIndices = null;
  const partTypeId = _pickerResolvedPartTypeId(_pickerState.filters);

  if (partTypeId === "siren_speaker") {
    const qty = Math.min(2, Math.max(1, _pickerState.config.count || 1));
    if (qty === 1 && (loc.slot_count || 1) > 1) return [[0.5, baseCy]];
    if (qty === 2) slotCount = 2;
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
    return e && (e.has_coords === true || (e.has_coords === undefined && !_INTERIOR_PZ.has(e.placement_zone)));
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
      loc.textCustom = false;
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
  const rows = groups.map(g => {
    const multi = _pickerIsSirenSpeakerContext() && g.category === "bracket_mount";
    if (multi) {
      const count = Math.min(2, Math.max(1, _pickerState.config.count || 1));
      const vals = Array.isArray(_pickerState.accessoryChoices[g.category])
        ? _pickerState.accessoryChoices[g.category]
        : Array(count).fill(_pickerState.accessoryChoices[g.category] || "");
      _pickerState.accessoryChoices[g.category] = vals.slice(0, count);
      while (_pickerState.accessoryChoices[g.category].length < count) _pickerState.accessoryChoices[g.category].push("");
      const selects = _pickerState.accessoryChoices[g.category].map((val, idx) =>
        `<div class="pa-subrow"><span class="pa-sub-label">Speaker ${idx + 1}</span>`
        + `<select class="${val ? "pa-chosen" : "pa-unset"}" data-cat="${esc(g.category)}" data-idx="${idx}">${_optionsHtml(g, val)}</select></div>`
      ).join("");
      return `<div class="pa-row pa-row-stack"><label>${esc(g.label)}${g.required ? '<span class="pa-req">*</span>' : ""}</label><div class="pa-subrows">${selects}</div></div>`;
    }
    const val = _pickerState.accessoryChoices[g.category] || "";
    return `<div class="pa-row"><label>${esc(g.label)}${g.required ? '<span class="pa-req">*</span>' : ""}</label>`
         + `<select class="${val ? "pa-chosen" : "pa-unset"}" data-cat="${esc(g.category)}">${_optionsHtml(g, val)}</select></div>`;
  }).join("");
  const pending = !_accessoriesSatisfied();
  el.innerHTML = `<div class="pa-banner"><span class="pa-chip">${groups.length}</span>`
    + `${pending ? "This part has accessories — choose each one to continue" : "Accessories set ✓"}`
    + `<button class="pa-close" onclick="_pickerClearSelection()" title="Close">✕</button></div>`
    + `<div class="pa-rows">${rows}</div>`;
  el.querySelectorAll("select[data-cat]").forEach(sel => sel.addEventListener("change", () => {
    if (sel.dataset.idx !== undefined) {
      const arr = Array.isArray(_pickerState.accessoryChoices[sel.dataset.cat])
        ? _pickerState.accessoryChoices[sel.dataset.cat]
        : [];
      arr[parseInt(sel.dataset.idx, 10)] = sel.value;
      _pickerState.accessoryChoices[sel.dataset.cat] = arr;
    } else {
      _pickerState.accessoryChoices[sel.dataset.cat] = sel.value;
    }
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
    if (Array.isArray(v)) {
      if (v.some(x => !x)) return false;
      if (g.required && v.some(x => x === "none")) return false;
      continue;
    }
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
  loc.selected = null; loc.textCustom = false; loc.name_pattern = ""; loc.base_label = ""; loc.catalog_names = [];
  _pickerState.partDetails = { paMicLocation: "", paMicLocationCustom: "", paMicClip: "" };
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

function _pickerHasFixedPartLocation() {
  return _pickerResolvedPartTypeId(_pickerState.filters) === "console";
}

function _pickerApplyFixedPartLocation() {
  const loc = _pickerState.loc;
  if (_pickerState.editLineId || loc.selected || !_pickerHasFixedPartLocation()) return;
  loc.selected = "IN CENTER CONSOLE";
  loc.name_pattern = "Center Console";
  loc.base_label = "Center Console";
  loc.catalog_names = ["Center Console"];
  loc.textCustom = false;
  _pickerUpdateFooter();
}

// ── Center-console setup ────────────────────────────────
// The legacy workbook treated the console as a body plus seven named
// faceplate rows. Keep that useful structure, but attach real selected SKUs
// beneath one console parent so the manifest and QB estimate stay in sync.
const _CONSOLE_CATALOG_PART_TYPES = {
  faceplates: "special_face_plate",
  armRest: "arm_rest",
  motionAttachment: "motion_attachment",
  dockingStation: "docking_station",
};

function _pickerNewConsoleSetup(saved = null) {
  const source = saved?.choices || saved || {};
  const copyChoice = value => value && typeof value === "object" ? { ...value } : null;
  return {
    active: false, loading: false, catalog: {}, error: "",
    choices: {
      faceplates: Array.isArray(source.faceplates) ? source.faceplates.map(item => ({ ...item })) : [],
      armRest: copyChoice(source.armRest),
      motionAttachment: copyChoice(source.motionAttachment),
      motionLocation: source.motionLocation || "mounted_to_console",
      dockingStation: copyChoice(source.dockingStation),
    },
    faceplateSearch: "", showAllFaceplates: false, openComponent: "",
  };
}

function _pickerConsoleChoiceFromProduct(product, autoFor = "") {
  if (!product) return null;
  const skus = product.skus || [];
  const sku = skus.find(item => _skuCompatible(item, _pickerVehicle())) || skus[0];
  if (!sku?.part_number) return null;
  return {
    product_id: product.product_id,
    model: product.model || product.product_id,
    manufacturer_label: product.manufacturer_label || "",
    part_number: sku.part_number,
    price: sku.price ?? null,
    ...(autoFor ? { auto_for: autoFor } : {}),
  };
}

function _pickerConsoleIsInConsole(location) {
  return /center console|console position|in console/i.test(String(location || ""));
}

function _pickerConsoleBuildEntries() {
  const entries = [];
  for (const part of ((typeof _meDraft !== "undefined" && _meDraft?.parts) || [])) {
    entries.push(part);
    for (const component of (part.components || [])) entries.push(component);
  }
  return entries;
}

function _pickerApplyConsoleAutoFaceplates() {
  const setup = _pickerState.consoleSetup;
  if (!setup?.active) return;
  const entries = _pickerConsoleBuildEntries();
  const inConsole = entry => _pickerConsoleIsInConsole(entry.location);
  const specs = [
    ["havis_c_eb40_ccs_1p", "Light control head", entries.some(entry => entry.part_type === "control_head" && inConsole(entry))],
    ["gamber_johnson_7160_0321", "Radio head", entries.some(entry => entry.part_type === "radio_head" && inConsole(entry))],
    ["gamber_johnson_19865", "K-9 controller", entries.some(entry => entry.part_type === "k9_control_head" && inConsole(entry))],
  ];
  const faceplates = setup.choices.faceplates;
  for (const [productId, autoFor, present] of specs) {
    if (!present || faceplates.some(item => item.product_id === productId)) continue;
    const product = (setup.catalog.faceplates || []).find(item => item.product_id === productId);
    const choice = _pickerConsoleChoiceFromProduct(product, autoFor);
    if (choice) faceplates.push(choice);
  }
}

async function _pickerBeginConsoleSetup(saved = null) {
  if (!_pickerHasFixedPartLocation() || !_pickerState.sel) return;
  const setup = _pickerNewConsoleSetup(saved || _pickerState.editPart?.picker_config?.console_setup);
  setup.active = true;
  setup.loading = true;
  _pickerState.consoleSetup = setup;
  _pickerSwitchTab("location");
  try {
    const loaded = await Promise.all(Object.entries(_CONSOLE_CATALOG_PART_TYPES).map(async ([key, partType]) => {
      const response = await api(`/api/parts-db/category-skus?type=equipment&part_type=${encodeURIComponent(partType)}`);
      return [key, response?.products || []];
    }));
    setup.catalog = Object.fromEntries(loaded);
    _pickerApplyConsoleAutoFaceplates();
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
  const all = [...(setup.catalog.faceplates || [])].sort((a, b) => String(a.model || "").localeCompare(String(b.model || "")));
  const matching = query
    ? all.filter(product => [product.model, product.manufacturer_label, ...(product.skus || []).map(sku => sku.part_number)].join(" ").toLowerCase().includes(query))
    : all;
  const visible = (query || setup.showAllFaceplates) ? matching : matching.slice(0, 12);
  const selected = new Set((setup.choices.faceplates || []).map(item => item.product_id));
  const cards = visible.map(product => {
    const choice = _pickerConsoleChoiceFromProduct(product);
    if (!choice) return "";
    const isAdded = selected.has(product.product_id);
    const price = choice.price != null ? ` · $${choice.price}` : "";
    return `<button type="button" class="console-catalog-card${isAdded ? " is-added" : ""}" data-console-faceplate-add="${esc(product.product_id)}"${isAdded ? " disabled" : ""}>`
      + `<span class="console-catalog-card-brand">${esc(product.manufacturer_label || "Faceplate")}</span><strong>${esc(product.model || "Faceplate")}</strong>`
      + `<small>${esc(choice.part_number)}${price}${isAdded ? " · added" : ""}</small></button>`;
  }).join("");
  const more = !query && !setup.showAllFaceplates && matching.length > visible.length
    ? `<button type="button" class="console-show-more" data-console-faceplate-show-all>Show all ${matching.length} faceplates</button>` : "";
  return `<div class="console-faceplate-catalog">${cards || `<div class="console-empty">No matching faceplates are available.</div>`}</div>${more}`;
}

function _pickerConsoleOrderCards(setup) {
  const faceplates = setup.choices.faceplates || [];
  if (!faceplates.length) return `<div class="console-order-empty">Add the faceplates the console needs, then drag them into shop order.</div>`;
  return faceplates.map((choice, index) => `<article class="console-faceplate-order-card" draggable="true" data-console-faceplate-index="${index}">
    <span class="console-drag-handle" title="Drag to reorder">⠿</span><span class="console-faceplate-number">${index + 1}</span>
    <div class="console-faceplate-copy"><strong>Face Plate ${index + 1} · ${esc(choice.model || choice.part_number)}</strong><small>${esc(choice.manufacturer_label || "")} · ${esc(choice.part_number || "")}${choice.auto_for ? ` · auto-added for ${esc(choice.auto_for)}` : ""}</small></div>
    <div class="console-faceplate-actions"><button type="button" class="console-order-move" data-console-faceplate-move="-1" data-console-faceplate-index="${index}" title="Move up"${index === 0 ? " disabled" : ""}>↑</button><button type="button" class="console-order-move" data-console-faceplate-move="1" data-console-faceplate-index="${index}" title="Move down"${index === faceplates.length - 1 ? " disabled" : ""}>↓</button><button type="button" class="console-order-remove" data-console-faceplate-remove="${index}" title="Remove faceplate">×</button></div>
  </article>`).join("");
}

function _pickerConsoleComponentSection(setup, key, label, help) {
  const choice = setup.choices[key];
  const isOpen = setup.openComponent === key;
  const products = [...(setup.catalog[key] || [])].sort((a, b) => String(a.model || "").localeCompare(String(b.model || "")));
  const picker = !isOpen ? "" : `<div class="console-component-picker"><button type="button" class="console-catalog-card console-catalog-card--none${!choice ? " is-added" : ""}" data-console-component-choice="" data-console-component-key="${esc(key)}"><strong>None</strong><small>Do not include this console component</small></button>${products.map(product => {
    const item = _pickerConsoleChoiceFromProduct(product);
    if (!item) return "";
    const selected = choice?.product_id === product.product_id && choice?.part_number === item.part_number;
    return `<button type="button" class="console-catalog-card${selected ? " is-added" : ""}" data-console-component-choice="${esc(product.product_id)}" data-console-component-key="${esc(key)}"><span class="console-catalog-card-brand">${esc(product.manufacturer_label || label)}</span><strong>${esc(product.model || product.product_id)}</strong><small>${esc(item.part_number)}${item.price != null ? ` · $${item.price}` : ""}</small></button>`;
  }).join("")}</div>`;
  const motionLocation = key === "motionAttachment" && choice ? `<div class="console-motion-location"><span>Mounting location</span><div><button type="button" class="console-location-choice${setup.choices.motionLocation === "mounted_to_console" ? " is-selected" : ""}" data-console-motion-location="mounted_to_console">Mounted to console</button><button type="button" class="console-location-choice${setup.choices.motionLocation === "mounted_to_pedestal" ? " is-selected" : ""}" data-console-motion-location="mounted_to_pedestal">Mounted to pedestal</button></div></div>` : "";
  return `<section class="console-component-section"><div class="console-component-summary"><div><div class="console-section-kicker">Optional console component</div><h3>${esc(label)}</h3><p>${esc(help)}</p></div><button type="button" class="console-component-current" data-console-component-open="${esc(key)}"><strong>${esc(_pickerConsoleChoiceLabel(choice))}</strong><span>${isOpen ? "Close choices" : choice ? "Change" : "Choose"}</span></button></div>${picker}${motionLocation}</section>`;
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
  details.innerHTML = `<section class="console-setup" data-console-setup>
    <header class="console-setup-header"><div><span class="guided-chip">CONSOLE</span><h2>Configure the Center Console</h2><p>Pick the actual faceplates and console components, then put faceplates in their physical order for the shop.</p></div><button class="guided-close" type="button" onclick="_pickerClearSelection()" title="Close">✕</button></header>${error}
    <section class="console-faceplate-section"><div class="console-section-heading"><div><div class="console-section-kicker">1 · Pick faceplates</div><h3>Add every faceplate the console needs</h3><p>Light-control, radio, and K-9 faceplates are suggested when their equipment is already mounted in the console. Add items such as cupholders here too.</p></div><label class="console-faceplate-search"><span>Search catalog</span><input id="picker-console-faceplate-search" value="${esc(setup.faceplateSearch || "")}" placeholder="Search faceplates, pockets, cupholders…"></label></div>${_pickerConsoleFaceplateCards(setup)}</section>
    <section class="console-faceplate-section console-faceplate-section--order"><div class="console-section-heading"><div><div class="console-section-kicker">2 · Arrange faceplates</div><h3>Drag into the order they appear on the console</h3><p>The manifest numbers these faceplates in exactly this order.</p></div></div><div class="console-faceplate-order" id="picker-console-faceplate-order">${_pickerConsoleOrderCards(setup)}</div></section>
    <section class="console-components-section"><div class="console-section-heading"><div><div class="console-section-kicker">3 · Complete the console</div><h3>Choose the remaining console hardware</h3><p>Only the components you select become billed, nested lines under the Center Console.</p></div></div>${_pickerConsoleComponentSection(setup, "armRest", "Armrest", "Choose the armrest that belongs with this console.")}${_pickerConsoleComponentSection(setup, "motionAttachment", "Motion attachment", "Choose a motion device and record whether it mounts to the console or pedestal.")}${_pickerConsoleComponentSection(setup, "dockingStation", "Docking station", "Choose the computer dock or cradle that belongs on this console.")}</section>
  </section>`;

  details.querySelector("#picker-console-faceplate-search")?.addEventListener("input", event => {
    setup.faceplateSearch = event.target.value;
    _pickerRenderConsoleSetup();
  });
  details.querySelector("[data-console-faceplate-show-all]")?.addEventListener("click", () => {
    setup.showAllFaceplates = true;
    _pickerRenderConsoleSetup();
  });
  details.querySelectorAll("[data-console-faceplate-add]").forEach(button => button.addEventListener("click", () => {
    const product = (setup.catalog.faceplates || []).find(item => item.product_id === button.dataset.consoleFaceplateAdd);
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
    const product = (setup.catalog[key] || []).find(item => item.product_id === button.dataset.consoleComponentChoice);
    setup.choices[key] = _pickerConsoleChoiceFromProduct(product);
    setup.openComponent = "";
    _pickerRenderConsoleSetup();
  }));
  details.querySelectorAll("[data-console-motion-location]").forEach(button => button.addEventListener("click", () => {
    setup.choices.motionLocation = button.dataset.consoleMotionLocation;
    _pickerRenderConsoleSetup();
  }));
}

function _pickerConsoleSetupSnapshot() {
  const choices = _pickerState.consoleSetup?.choices || {};
  const copy = value => value ? { ...value } : null;
  return {
    faceplates: (choices.faceplates || []).map(item => ({ ...item })),
    armRest: copy(choices.armRest),
    motionAttachment: copy(choices.motionAttachment),
    motionLocation: choices.motionLocation || "mounted_to_console",
    dockingStation: copy(choices.dockingStation),
  };
}

function _pickerConsoleChildRows(parentLineId, parentName) {
  const choices = _pickerState.consoleSetup?.choices || {};
  const rows = [];
  const add = (name, choice, partType, location, category) => {
    if (!choice?.part_number) return;
    rows.push({ name, location, manufacturer: choice.manufacturer_label || "", part_number: choice.part_number,
      quantity: 1, new_or_used: "New", source: "", parent_line_id: parentLineId,
      // These are selected build parts, not catalog accessories. Keep the
      // relationship for manifest nesting, but let their normal edit path
      // open the Part Picker instead of an accessory-only chooser.
      accessory_category: category, accessory_parent_product: "", part_type: partType });
  };
  (choices.faceplates || []).forEach((choice, index) => add(`${parentName} · Face Plate ${index + 1} · ${choice.model || choice.part_number}`, choice, "special_face_plate", "IN CENTER CONSOLE", "console_faceplate"));
  add(`${parentName} · Armrest · ${choices.armRest?.model || ""}`.replace(/ · $/, ""), choices.armRest, "arm_rest", "IN CENTER CONSOLE", "console_component");
  const motionLocation = choices.motionLocation === "mounted_to_pedestal" ? "MOUNTED TO PEDESTAL" : "MOUNTED TO CONSOLE";
  add(`${parentName} · Motion Attachment · ${choices.motionAttachment?.model || ""}`.replace(/ · $/, ""), choices.motionAttachment, "motion_attachment", motionLocation, "console_component");
  add(`${parentName} · Docking Station · ${choices.dockingStation?.model || ""}`.replace(/ · $/, ""), choices.dockingStation, "docking_station", "IN CENTER CONSOLE", "console_component");
  return rows;
}

async function _pickerReplaceConsoleChildren(draftId, parentLineId, parentName) {
  const existing = ((typeof _meDraft !== "undefined" && _meDraft?.parts) || []).filter(part =>
    part.parent_line_id === parentLineId && ["console_faceplate", "console_component"].includes(part.accessory_category)
  );
  for (const child of existing) {
    const result = await api(`/api/draft/${draftId}/part/${child.line_id}/delete`, {});
    if (!result?.ok) throw new Error(result?.error || "could not replace a console component");
  }
  for (const row of _pickerConsoleChildRows(parentLineId, parentName)) {
    const result = await api(`/api/draft/${draftId}/part`, row);
    if (!result?.ok) throw new Error(result?.error || "could not add a console component");
  }
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
  radioHead: [
    { value: "console_position_1", label: "Console position 1 (top)" },
    { value: "console_position_2", label: "Console position 2" },
    { value: "console_position_3", label: "Console position 3" },
    { value: "console_position_4", label: "Console position 4" },
    { value: "secondary_radio", label: "Rear storage area (secondary radio)" },
  ],
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

const _SYSTEM_CABLES = {
  radio: ["Antenna cable", "Power cable", "Blue communication cable"],
  radar: ["Front antenna cable", "Rear antenna cable", "Display / counting-unit cable", "VSS / speed cable", "Power cable"],
  camera: ["Power cable", "Camera signal / data cable", "DVR / display cable", "GPS / antenna cable"],
};

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
      systemProduct: null, condition: "", provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "",
      format: "split", headLoc: "", brickLoc: "",
      antennaStyle: "", antennaLoc: "", speakerLoc: "",
      micMount: "", micLoc: "",
    },
    steps(c) {
      return [
        _systemStep("condition", "choice", "Is this a new or reused radio system?", "This controls whether we ask about cable refresh work.", [
          ["new", "New system", "A new kit is being purchased"], ["reused", "Reused system", "The existing radio hardware stays in service"],
        ]),
        ...(c.condition === "reused" ? [
          _systemStep("refresh", "choice", "Will the radio cables be refreshed?", "Choose No when the existing cable set can stay.", [["no", "No cable refresh", "Keep the existing cable set"], ["yes", "Yes, refresh cables", "Replace only the cable runs selected next"]]),
          ...(c.refresh === "yes" ? [_systemStep("refreshCables", "multi", "Which radio cables should be refreshed?", "Select every cable run the shop should replace.", _SYSTEM_CABLES.radio.map(x => [x.toLowerCase().replace(/[^a-z]+/g, "_"), x]))] : []),
        ] : [
          _systemStep("provider", "choice", "Who is providing the new radio system?", "Customer supplied is the normal path. Choose DTM only when we are purchasing the kit.", [["customer", "Customer supplied", "Hardware arrives with the vehicle or customer"], ["dtm", "DTM purchasing", "Sales needs the purchase description below"]]),
          ...(c.provider === "dtm" ? [_systemStep("purchaseDetails", "textarea", "What should Sales purchase?", "Enter model, quantity, accessories, vendor notes, or any other purchasing detail.", [])] : []),
        ]),
        _systemStep("format", "choice", "What radio layout is being installed?", "This determines whether the radio brick gets its own location.", [["all_in_one", "All-in-one radio", "No separate brick location"], ["split", "Split radio", "Control head and brick are separate"]]),
        _systemLocationStep("headLoc", "Where will the radio control head go?", "Pick the console position the shop should use.", _SYSTEM_LOC.radioHead),
        ...(c.format === "split" ? [_systemLocationStep("brickLoc", "Where will the radio brick go?", "The brick is the remote electronics module behind the control head.", _SYSTEM_LOC.radioBrick)] : []),
        _systemStep("antennaStyle", "choice", "What antenna style is expected?", "This is an install note; it does not create a purchase order.", [["cylinder", "Cylinder style", "Common roof-mounted radio antenna"], ["whip", "Whip style", "Flexible whip antenna"], ["covert", "Covert / window style", "Low-profile or window-mounted antenna"], ["customer_specified", "Customer specified", "Use the customer hardware as supplied"]]),
        _systemLocationStep("antennaLoc", "Where will the radio antenna go?", c.antennaStyle === "cylinder" || c.antennaStyle === "whip" ? "Cylinder and whip antennas normally use the rear left roof." : "Choose the roof or cargo-window location.", c.antennaStyle === "cylinder" || c.antennaStyle === "whip" ? [_SYSTEM_LOC.radioAntenna[0]] : _SYSTEM_LOC.radioAntenna),
        _systemLocationStep("speakerLoc", "Where will the radio speaker go?", "Pick the location the shop should mount the speaker.", _SYSTEM_LOC.radioSpeaker),
        _systemStep("micMount", "choice", "What microphone mount should the shop use?", "Choose the mounting style that matches the supplied radio kit.", [["manufacturer_clip", "Manufacturer clip", "Clip supplied by the radio manufacturer"], ["magnetic_no_bracket", "Magnetic Mic without bracket", "Magnetic Mic mount without its bracket"], ["magnetic_with_bracket", "Magnetic Mic with bracket", "Magnetic Mic mount with its bracket"]]),
        _systemLocationStep("micLoc", "Where will the radio microphone mount?", "Top plate is the standard location; use Custom for a shop-specific location.", _SYSTEM_LOC.radioMic),
      ];
    },
  },
  radar: {
    family: "radar", label: "Radar System", chip: "RADAR",
    primaryName: "Radar Display Unit", primaryPartType: "radar_display_unit",
    intro: "Capture the radar’s ownership, cable work, and exact antenna/counting-unit locations for the shop.",
    defaults: {
      systemProduct: null, condition: "", provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "", split: "",
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
        _systemStep("condition", "choice", "Is this a new or reused radar system?", "This controls whether cable refresh questions appear.", [["new", "New system", "A new radar kit is being purchased"], ["reused", "Reused system", "The existing radar hardware stays in service"]]),
        ...(c.condition === "reused" ? [
          _systemStep("refresh", "choice", "Will the radar cables be refreshed?", "Choose No when the current cable set can stay.", [["no", "No cable refresh", "Keep the existing cable set"], ["yes", "Yes, refresh cables", "Replace only the cable runs selected next"]]),
          ...(c.refresh === "yes" ? [_systemStep("refreshCables", "multi", "Which radar cables should be refreshed?", "Select every cable run the shop should replace.", _SYSTEM_CABLES.radar.map(x => [x.toLowerCase().replace(/[^a-z]+/g, "_"), x]))] : []),
        ] : [
          _systemStep("provider", "choice", "Who is providing the new radar system?", "Customer supplied is the default. Choose DTM only when we are purchasing it.", [["customer", "Customer supplied", "Hardware arrives with the vehicle or customer"], ["dtm", "DTM purchasing", "Sales needs the purchase description below"]]),
          ...(c.provider === "dtm" ? [_systemStep("purchaseDetails", "textarea", "What should Sales purchase?", "Enter the radar model, kit contents, vendor, or any other purchasing detail.", [])] : []),
        ]),
        _systemStep("split", "choice", "Will the counting unit be split from the display unit?", "Choose whether the counting unit needs its own mounting location.", [["no", "No — integrated unit", "Display and counting unit stay together"], ["yes", "Yes — split unit", "The counting unit gets its own location next"]]),
        ...(c.split === "yes" ? [_systemLocationStep("countingLoc", "Where will the split counting unit go?", "Pick the final location for the separate counting unit.", _SYSTEM_LOC.radarCounting)] : []),
        _systemLocationStep("frontLoc", "Where will the front antenna be mounted?", "Choose the mounting location first; the bracket is selected on the next screen.", [["dash", "On dash", "Dash-mounted front antenna"], ["a_pillar", "On A-pillar", "A-pillar mounted front antenna"]]),
        _systemStep("frontBracket", "choice", "What bracket will mount the front antenna?", "Short A-bracket is the normal front choice; change it when this installation needs a different mount.", _RADAR_BRACKETS),
        _systemLocationStep("rearLoc", "Where will the rear antenna be mounted?", "Choose the mounting location first; the bracket is selected on the next screen.", rearLocations),
        _systemStep("rearBracket", "choice", "What bracket will mount the rear antenna?", "Tall A-bracket is the normal rear choice; change it when this installation needs a different mount.", _RADAR_BRACKETS),
      ];
    },
  },
  camera: {
    family: "camera_system", label: "Camera System", chip: "CAMERA",
    primaryName: "Camera DVR", primaryPartType: "camera_dvr",
    intro: "Record the kit ownership and the camera/DVR locations the shop needs. Only DTM purchases need ordering text.",
    defaults: {
      systemProduct: null, condition: "", provider: "customer", refresh: "", refreshCables: [], purchaseDetails: "", cameraBrand: "", dvrLoc: "",
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
        _systemStep("condition", "choice", "Is this a new or reused camera system?", "This controls whether cable refresh questions appear.", [["new", "New system", "A new camera kit is being purchased"], ["reused", "Reused system", "The existing camera hardware stays in service"]]),
        ...(c.condition === "reused" ? [
          _systemStep("refresh", "choice", "Will the camera cables be refreshed?", "Choose No when the current cable set can stay.", [["no", "No cable refresh", "Keep the existing cable set"], ["yes", "Yes, refresh cables", "Replace only the cable runs selected next"]]),
          ...(c.refresh === "yes" ? [_systemStep("refreshCables", "multi", "Which camera cables should be refreshed?", "Select every cable run the shop should replace.", _SYSTEM_CABLES.camera.map(x => [x.toLowerCase().replace(/[^a-z]+/g, "_"), x]))] : []),
        ] : [
          _systemStep("provider", "choice", "Who is providing the new camera system?", "Customer supplied is the default. Choose DTM only when we are purchasing it.", [["customer", "Customer supplied", "Hardware arrives with the vehicle or customer"], ["dtm", "DTM purchasing", "Sales needs the purchase description below"]]),
          ...(c.provider === "dtm" ? [_systemStep("purchaseDetails", "textarea", "What should Sales purchase?", "Enter the camera platform, kit contents, vendor, or any other purchasing detail.", [])] : []),
        ]),
        _systemLocationStep("dvrLoc", "Where will the camera DVR / recorder go?", "Pick the location the shop should use for the recorder.", _SYSTEM_LOC.cameraDvr),
        _systemStep("cameraParts", "multi", "Which camera components are included?", "Select every component the shop should install. Location questions will follow for each selection.", cameraOptions),
        ...(c.cameraParts || []).includes("rear_seat") ? [_systemLocationStep("rearSeatLoc", "Where will the prisoner / rear-seat camera go?", "Pick the final cabin-camera location.", _SYSTEM_LOC.rearSeatCamera)] : [],
        ...(c.cameraParts || []).includes("body_dock") ? [_systemLocationStep("bodyDockLoc", "Where will the body-camera dock go?", "Pick the location for the body-camera dock.", _SYSTEM_LOC.visorOrConsole)] : [],
        ...(c.cameraParts || []).includes("wireless_mic") ? [_systemLocationStep("wirelessMicLoc", "Where will the wireless microphone charger go?", "Pick the final charger location.", _SYSTEM_LOC.visorOrConsole)] : [],
      ];
    },
  },
};

function _systemStep(key, type, title, help, options, required = true) {
  return { key, type, title, help, options: (options || []).map(o => Array.isArray(o) ? { value: o[0], label: o[1], help: o[2] || "" } : o), required };
}

// These locations are shop-reference notes, not render-placement coordinates.
// A controlled list keeps common installs consistent, while Custom preserves
// the exact instruction when a vehicle/setup calls for something unusual.
function _systemLocationStep(key, title, help, options, required = true) {
  return { ..._systemStep(key, "choice", title, help, options, required), allowCustom: true, customKey: `${key}Custom` };
}

function _systemOptions(step) {
  const options = [...(step.options || [])];
  if (step.allowCustom) options.push({ value: "__custom__", label: "Custom location", help: "Enter a shop-specific location" });
  return options;
}

const _CAMERA_EXTENDED_BRANDS = new Set(["watchguard_4re", "watchguard_m500"]);
function _cameraSupportsExtendedComponents(brand) { return _CAMERA_EXTENDED_BRANDS.has(brand); }

function _systemProductLabel(choices) {
  const product = choices?.systemProduct || {};
  return [product.manufacturer_label, product.model].filter(Boolean).join(" · ");
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
    base[key] = Array.isArray(value) ? [...value] : value;
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
  return base;
}

function _systemSteps() {
  const def = _systemDef(), c = _pickerState.radio?.choices || {};
  return def ? def.steps(c) : [];
}

function _systemOption(step, value) {
  return _systemOptions(step).find(o => o.value === value);
}

function _systemAnswerLabel(step, value, choices = _pickerState.radio?.choices || {}) {
  if (step.type === "textarea") return String(value || "").trim();
  if (step.type === "multi") {
    return (Array.isArray(value) ? value : []).map(v => _systemOption(step, v)?.label || v).join(", ");
  }
  if (step.allowCustom && value === "__custom__") {
    return String(choices[step.customKey] || "").trim() || "Custom location";
  }
  return _systemOption(step, value)?.label || String(value || "");
}

function _systemStepSatisfied(step) {
  const choices = _pickerState.radio?.choices || {}, value = choices[step.key];
  if (!step.required) return true;
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
  _pickerState.systemSetup = { active: false, kind: "", product: null };
  _pickerState.radio = {
    active: true, kind, loading: false, products: prior.products || {},
    choices: _systemDefaults(kind, existingChoices || prior.choices || {}), step: Number(step) || 0,
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
  // Camera accessories can share the DVR part type in legacy catalog data;
  // only actual camera platforms belong in the system-identification step.
  if (kind !== "camera") return products;
  const platforms = new Set(["axon_fleet_3", "axon_fleet_2", "watchguard_4re", "watchguard_m500", "qb_unassigned_md_6200"]);
  return products.filter(product => platforms.has(product.product_id));
}

function _pickerSystemProductRecord(product) {
  return product ? {
    product_id: product.product_id,
    manufacturer_label: product.manufacturer_label || "",
    model: product.model || "",
  } : null;
}

function _pickerRenderSystemSelectionIn(el) {
  const setup = _pickerState.systemSetup || {}, def = _SYSTEM_DEFS[setup.kind];
  if (!el || !setup.active || !def) return;
  const choices = _pickerSystemProducts(setup.kind);
  const selectedId = setup.product?.product_id || "";
  const cards = choices.map(product => {
    const selected = product.product_id === selectedId;
    return `<button type="button" class="system-product-choice${selected ? " is-selected" : ""}" data-system-product-id="${esc(product.product_id)}" aria-pressed="${selected ? "true" : "false"}">`
      + `<span class="system-product-choice-check">${selected ? "✓" : ""}</span><span class="system-product-choice-copy"><small>${esc(product.manufacturer_label || "System")}</small><strong>${esc(product.model || product.product_id)}</strong></span></button>`;
  }).join("");
  el.innerHTML = `<section class="system-product-picker system-product-picker--${esc(setup.kind)}" data-system-select-kind="${esc(setup.kind)}">`
    + `<div class="system-product-picker-kicker">${esc(def.chip)} · system identification</div><h2>Which ${esc(def.label)} is this?</h2>`
    + `<p>Select the brand and platform first. The next tab will collect the install and shop details.</p>`
    + `<div class="system-product-choice-grid">${cards || `<div class="system-product-empty">No system platforms are available for this selection yet.</div>`}</div></section>`;
  el.querySelectorAll("[data-system-product-id]").forEach(button => button.addEventListener("click", () => {
    const product = choices.find(item => item.product_id === button.dataset.systemProductId);
    _pickerState.systemSetup.product = _pickerSystemProductRecord(product);
    _pickerRenderProducts();
    _pickerUpdateFooter();
  }));
}

async function _pickerBeginSystemSetup() {
  const setup = _pickerState.systemSetup || {}, def = _SYSTEM_DEFS[setup.kind];
  if (!def || !setup.product) return;
  const choices = { systemProduct: { ...setup.product } };
  if (setup.kind === "camera") choices.cameraBrand = _systemCameraPlatform(choices);
  if (setup.kind === "radio") {
    if (setup.product.product_id === "motorola_all_in_one_unit") choices.format = "all_in_one";
    if (setup.product.product_id === "motorola_split_unit") choices.format = "split";
  }
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
  const rows = [], add = (label, partType, location, detail) => rows.push({ label, part_type: partType, location: location || "", detail: detail || "", quantity: 1 });
  const stepFor = key => _systemSteps().find(s => s.key === key) || { options: [] };
  const answer = key => _systemAnswerLabel(stepFor(key), c[key], c);
  if (kind === "radio") {
    add("Radio control head", "radio_head", answer("headLoc"), c.format === "split" ? "Split radio layout" : "All-in-one radio");
    if (c.format === "split") add("Radio brick", "radio_brick", answer("brickLoc"), "Separate electronics module");
    add("Radio antenna", "radio_antenna_top", answer("antennaLoc"), answer("antennaStyle"));
    add("Radio speaker", "radio_speaker", answer("speakerLoc"), "Shop mounting location");
    add("Radio microphone", "radio_mic_clip", answer("micLoc"), answer("micMount"));
    add("Radio cables", "radio_cable", "", c.condition === "reused" ? (c.refresh === "yes" ? `Refresh: ${answer("refreshCables")}` : "Reuse existing cable set") : "New kit cables supplied with system");
  } else if (kind === "radar") {
    if (c.split === "yes") {
      add("Radar display unit", "radar_display_unit", "", "Separate display unit");
      add("Radar counting unit", "radar_counting_unit", answer("countingLoc"), "Separate counting unit");
    } else {
      add("Radar display / counting unit", "radar_display_unit", "Integrated display unit", "Integrated unit");
    }
    add("Front radar antenna", "front_radar_antenna_mount", answer("frontLoc"), answer("frontBracket"));
    add("Rear radar antenna", "rear_radar_antenna_mount", answer("rearLoc"), answer("rearBracket"));
    if (c.condition === "reused" && c.refresh === "yes") add("Radar cable refresh", "radar_cable", "", `Refresh: ${answer("refreshCables")}`);
  } else if (kind === "camera") {
    add("Camera DVR / recorder", "camera_dvr", answer("dvrLoc"), `Platform: ${_systemProductLabel(c) || _systemCameraPlatform(c)}`);
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
      add(item[0], item[1], location, item[3] || "Selected camera component");
    }
    if (c.condition === "reused" && c.refresh === "yes") add("Camera cable refresh", "camera_dvr", "", `Refresh: ${answer("refreshCables")}`);
  }
  return rows;
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
  const nextOk = _systemStepSatisfied(step);
  const customLocation = step.allowCustom && value === "__custom__"
    ? `<label class="guided-custom-field"><span>Custom shop location</span><input class="guided-text-input" data-system-custom="${esc(step.customKey)}" value="${esc(state.choices?.[step.customKey] || "")}" placeholder="Enter the exact shop-reference location"></label>`
    : "";
  const stepBody = step.type === "textarea"
    ? `<textarea class="guided-textarea" data-system-text="${esc(step.key)}" rows="6" placeholder="Enter purchasing details for Sales…">${esc(value || "")}</textarea><div class="guided-field-note">This note is saved with the system line for purchasing.</div>`
    : _systemOptionGrid(step, value) + customLocation;
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
    } else {
      target[key] = selected;
      if (key === "condition") { target.refresh = ""; target.refreshCables = []; target.provider = "customer"; target.purchaseDetails = ""; }
      if (key === "provider" && selected === "customer") target.purchaseDetails = "";
      if (key === "antennaStyle" && ["cylinder", "whip"].includes(selected) && target.antennaLoc && !["rear_left_roof", "__custom__"].includes(target.antennaLoc)) target.antennaLoc = "";
      if (key === "cameraBrand" && !_cameraSupportsExtendedComponents(selected)) {
        target.cameraParts = (target.cameraParts || []).filter(part => ["front", "rear_seat"].includes(part));
        target.bodyDockLoc = ""; target.wirelessMicLoc = "";
      }
    }
    _systemClampStep(); _pickerRefreshSystemView();
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
  if (kind === "radio") return _systemAnswerLabel(_systemSteps().find(s => s.key === "headLoc") || { options: [] }, choices.headLoc, choices);
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
  const row = {
    name: editing ? (existing?.name || def.primaryName) : def.primaryName,
    location: _pickerSystemPrimaryLocation(state.kind, c), manufacturer: c.systemProduct?.manufacturer_label || "",
    part_number: c.provider === "dtm" ? "DTM PURCHASE — SEE DETAILS" : "CUSTOMER SUPPLIED KIT",
    quantity: 1, new_or_used: c.condition === "reused" ? "Reused" : "New",
    source: c.provider === "dtm" ? "DTM purchasing" : "Customer supplied",
    part_type: def.primaryPartType,
    notes: systemNotes || `${def.label} — guided system details`, components,
    picker_config: { system_type: state.kind, system_label: def.label, choices: c, details, step: state.step || 0 },
  };
  const btn = $("picker-add-btn"); if (btn) btn.disabled = true;
  try {
    const endpoint = editing ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update` : `/api/draft/${draftId}/part`;
    const result = await api(endpoint, row);
    if (!result?.ok) throw new Error(result?.error || "system add failed");
    if (state.kind === "radio") {
      const micStep = _systemSteps().find(step => step.key === "micLoc") || { options: [] };
      const micLocation = _systemAnswerLabel(micStep, c.micLoc, c);
      await _pickerReplaceMagneticMicChild(
        draftId, result.line_id || _pickerState.editLineId, row.name, micLocation, c.micMount,
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
    const counts = {};
    for (const pick of picks) {
      if (!pick || pick === "none") continue;
      counts[pick] = (counts[pick] || 0) + 1;
    }
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
      });
    }
  }
  return rows;
}

function _pickerChosenWestinRows(parentName, locName, parentLineId) {
  if (!_pickerState.westin || !_pickerState.westin.active || !_pickerState.sel) return [];
  const rows = [];
  const addChoice = (value, category) => {
    if (!value) return;
    const [pid, sku] = value.split("::");
    const product = (_pickerState.products || []).find(p => p.product_id === pid);
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
  addChoice(_pickerState.westin.wire, "other");
  addChoice(_pickerState.westin.channel, "bracket_mount");
  return rows;
}

function _pickerUpdateFooter() {
  const text = $("picker-footer-text"), btn = $("picker-add-btn"), btnAnother = $("picker-add-another-btn");
  if (!text || !btn) return;
  const sel = _pickerState.sel, loc = _pickerState.loc;
  const detailsTab = $("picker-tab-btn-location");
  if (detailsTab) detailsTab.hidden = _pickerHasFixedPartLocation()
    && !_pickerState.radio?.active && !_pickerState.systemSetup?.active && !_pickerState.consoleSetup?.active;
  const accOk = _accessoriesSatisfied();
  const tracerOk = _pickerTracerSatisfied();
  const lightbarOk = _pickerLightbarSatisfied();
  const radioOk = _pickerRadioSatisfied();
  const detailsOk = _pickerPartDetailsSatisfied();
  const ready = accOk && tracerOk && lightbarOk && radioOk && detailsOk;
  // A required detail belongs on the next screen. It must not prevent the
  // user from reaching that screen after selecting the part.
  const detailsEntryReady = accOk && tracerOk && lightbarOk;
  const hasAcc = _pickerVisibleAccessoryGroups().length > 0;
  const selName = sel ? (sel.model + (sel.sku ? " · " + sel.sku : "")) : "";
  let hint = (sel && hasAcc && !accOk) ? ' <span class="picker-foot-acc">· choose accessories</span>' : "";
  if (sel && _pickerState.tracer.active && !tracerOk)
    hint += ' <span class="picker-foot-acc">· configure lightheads</span>';
  if (sel && _pickerState.lightbar.active && !lightbarOk)
    hint += ' <span class="picker-foot-acc">· add order notes</span>';
  if (sel && !detailsOk)
    hint += ' <span class="picker-foot-acc">· complete shop details</span>';
  if (_pickerState.radio.active && !radioOk)
    hint += ` <span class="picker-foot-acc">· complete ${esc(_systemDef()?.label || "system")} workflow</span>`;

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
    text.innerHTML = `<span class="picker-foot-label">${esc(consoleLabel)}</span>`;
    if (_pickerState.tab === "part") {
      btn.textContent = "Continue in Details →";
      btn.disabled = !sel || _pickerState.consoleSetup.loading;
      _pickerState.footerHandler = sel && !_pickerState.consoleSetup.loading ? () => _pickerSwitchTab("location") : null;
      _showTwoButtons(false, null);
    } else {
      btn.textContent = "Add and Finish";
      btn.disabled = !sel || _pickerState.consoleSetup.loading;
      _pickerState.footerHandler = sel && !_pickerState.consoleSetup.loading ? () => _pickerDoAdd(false) : null;
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
    } else if (sel && loc.selected && _pickerHasFixedPartLocation()) {
      text.innerHTML = `<span class="picker-foot-label">${esc(selName)}</span>`;
      btn.textContent = "Set up Center Console →";
      btn.disabled = false;
      _pickerState.footerHandler = () => _pickerBeginConsoleSetup();
      _showTwoButtons(false, null);
    } else if (loc.selected && (_pickerState.tracer.active || _pickerSelIsFixture() || _pickerHasFixedPartLocation())) {
      // Auto-located tracer/fixture: part has one resolved location
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
    const canAdd = !!(sel && loc.selected && ready);
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
  if (_pickerState.lightbar.active) { await _pickerAddLightbar(draftId, addAndContinue); return; }

  const product = _pickerState.products.find(p => p.product_id === sel.product_id);
  // Color path only for color-configured products; a direct SKU pick (sel.sku,
  // e.g. a programmable bar) always uses the simple single-SKU path.
  const usesColor = f.type_id === "lights" && _COLOR_CATEGORIES.has(f.category_id)
    && !sel.sku && _pickerProductHasColor(product || { skus: [] });
  const locName = loc.selected;   // raw layout key (planner upper-cases to match)

  // In edit mode preserve the original part name (never re-sequence — the
  // user edited "Forward Warning 1", it must stay "Forward Warning 1").
  // Pre-fill (Step 6) ensures the picker is already in the right state, so
  // recomputing name/color from picker state gives the stored values back.
  const editing = !!_pickerState.editLineId;
  const ep = _pickerState.editPart;
  const baseName = editing ? ep.name : (_pickerChooseName(loc) || sel.model);

  // Picker config snapshot to persist on the saved part (Step 6).
  const c = _pickerState.config;
  const pickerConfig = {
    mode: c.mode, colorsPerHead: c.colorsPerHead,
    uniform: [...c.uniform], splitSecondary: [...c.splitSecondary],
    custom: c.custom.map(a => [...a]), _noColor: c._noColor || false,
    count: c.count, lens: f.lens || "",
    skuChoices: { ..._pickerState.skuChoices },
    details: { ..._pickerState.partDetails },
  };
  if (_pickerState.consoleSetup?.active) pickerConfig.console_setup = _pickerConsoleSetupSnapshot();

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
    colorFields = _pickerColorFields();
  } else {
    const sku = sel.sku || (product && product.skus[0] && product.skus[0].part_number);
    if (!sku) { toast("Pick a SKU", "error"); return; }
    const skuObj = product.skus.find(s => s.part_number === sku) || {};
    const qty = _pickerIsSirenSpeakerContext()
      ? Math.min(2, Math.max(1, _pickerState.config.count || 1))
      : 1;
    combos = [{ colors: [], part_number: sku, quantity: qty, price: skuObj.price || null }];
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
  for (const row of rows) {
    try {
      const endpoint = _pickerState.editLineId
        ? `/api/draft/${draftId}/part/${_pickerState.editLineId}/update`
        : `/api/draft/${draftId}/part`;
      // Include picker_config so Edit can pre-fill exactly (Step 6).
      const detailNote = _pickerPartDetailsNote();
      const detailComponent = _pickerPartDetailsComponent();
      const payload = {
        ...row,
        ...(detailNote ? { notes: detailNote } : {}),
        ...(detailComponent ? { components: [...(row.components || []), detailComponent] } : {}),
        picker_config: pickerConfig,
        ...(partTypeId ? { part_type: partTypeId } : {}),
      };
      const r = await api(endpoint, payload);
      if (r?.ok) { ok++; if (!parentLineId && r.line_id) parentLineId = r.line_id; }
    } catch (e) { console.error("add row failed:", e); }
  }
  if (!ok) { toast("Add failed", "error"); if (btn) btn.disabled = false; return; }

  if (_pickerState.consoleSetup?.active) {
    try {
      await _pickerReplaceConsoleChildren(draftId, parentLineId, baseName);
    } catch (error) {
      console.error("console component save failed:", error);
      toast("Console saved, but its component lines could not be updated", "error");
      if (btn) btn.disabled = false;
      return;
    }
  }

  if (partTypeId === "control_head") {
    try {
      await _pickerReplaceMagneticMicChild(
        draftId, parentLineId, baseName, _pickerPaMicLocation(), _pickerState.partDetails?.paMicClip,
      );
    } catch (error) {
      console.error("PA magnetic mic save failed:", error);
      toast("Control head saved, but its magnetic mic line could not be updated", "error");
      if (btn) btn.disabled = false;
      return;
    }
  }

  // Accessories → their own child lines under the parent (new adds only).
  if (!_pickerState.editLineId) {
    const accRows = _pickerChosenAccessoryRows(baseName, locName, parentLineId);
    for (const arow of accRows) {
      try { await api(`/api/draft/${draftId}/part`, arow); }
      catch (e) { console.error("add accessory failed:", e); }
    }
    for (const wrow of _pickerChosenWestinRows(baseName, locName, parentLineId)) {
      try { await api(`/api/draft/${draftId}/part`, wrow); }
      catch (e) { console.error("add Westin bumper option failed:", e); }
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
  await _pickerFinalize(draftId, addAndContinue);
}
