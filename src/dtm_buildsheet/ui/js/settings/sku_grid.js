// ═══════════════════════════════════════════════════════
// SKU REVIEW GRID — brand-sorted spreadsheet editor for parts_db.json
//
// View 1 of the revamped Part Manager (Settings → Advanced → Part Manager →
// Review). Surfaces, per product/SKU:
//   1. QB backing   — In QB / Pending / Not in QB / Unbilled, with the raw QB
//      data shown READ-ONLY (sales description, price, type) from the QB cache.
//   2. App-readiness — home (fits_part_types) + (lights:color).
//   3. Reviewed     — a manual "Complete" flag → green product highlight.
// Light/Unbilled are user-managed tags (trackable, correctable). Accessories
// are designated in their own section (category + which products they belong to).
// Edits persist through the granular /api/parts-db/edit/* endpoints.
// ═══════════════════════════════════════════════════════

let _skg = null;                       // full parts_db.json document
let _skgQb = {};                       // qb_item_id → raw QB cache item (read-only truth)
const _skgExpanded = new Set();        // product_ids currently expanded
const _skgSel = new Set();             // selected SKUs, keyed "pid idx"
let _skgWired = false;
let _skgModalSave = null;
let _skgSearchTimer = null;

const _SKG_LENS = ["clear", "colored", "smoked"];
const _SKG_DEFAULT_COLORS = ["red", "blue", "white", "amber", "green", "purple"];
const _SKG_LIGHT_CATS = new Set(["warning", "scene", "interior", "interior_bar", "roof_bar", "spotlight"]);

async function initSkuGridTab() {
  if (!_skg) await _skgLoad();
  await _skgLoadQb();
  _skgWireOnce();
  _skgPopulateBrandFilter();
  _skgPopulateTreeFilters();
  _skgRender();
}

async function _skgLoad() {
  try { _skg = await api("/api/parts-db"); }
  catch (e) { _skg = null; toast("Failed to load parts_db.json: " + (e?.message || e), "error"); }
}

async function _skgLoadQb() {
  _skgQb = {};
  try {
    const res = await api("/api/quickbooks/items");   // local cache, no network
    for (const it of (res?.items || [])) _skgQb[String(it.qb_item_id)] = it;
  } catch (_) { /* cache may be absent — pending/DB-only rows still render */ }
}

// ─── vocab + status helpers ──────────────────────────────────────────────────

function _skgMfrLabel(mid) { return (_skg?.manufacturers?.[mid]?.label) || mid || "—"; }
function _skgTagLabel(tid) { return (_skg?.tags?.[tid]?.label) || tid; }
function _skgPtLabel(ptid) { return (_skg?.part_types?.[ptid]?.label) || ptid; }

function _skgColors() {
  const pal = Object.keys(_skg?.color_palette || {});
  return pal.length ? pal : _SKG_DEFAULT_COLORS;
}

function _skgNamedTagId(name) {
  for (const [tid, t] of Object.entries(_skg?.tags || {}))
    if (tid === name || (t.label || "").trim().toLowerCase() === name) return tid;
  return null;
}
function _skgLightTagId() { return _skgNamedTagId("light"); }
function _skgUnbilledTagId() { return _skgNamedTagId("unbilled"); }
function _skgIsUnbilled(p) { const id = _skgUnbilledTagId(); return !!id && (p.tag_ids || []).includes(id); }

// A product is a "light" iff it carries the user-managed "light" tag. Until any
// light tag exists, fall back to the legacy type heuristic so the tab still
// shows color fields — clicking "Seed light tags" switches to pure tag-based.
function _skgIsLight(p) {
  const lid = _skgLightTagId();
  if (lid) return (p.tag_ids || []).includes(lid);
  return (p.fits_part_types || []).some(ptid => (_skg?.part_types?.[ptid]?.type_id) === "lights");
}

// Light bars (roof / interior bar) are ordered as whole configured SKUs with the
// color baked into the part number (e.g. Legacy EB2DEDE) — they carry no per-SKU
// color tag, so the readiness check must NOT require a color for them.
const _SKG_BAR_CATS = new Set(["roof_bar", "interior_bar", "visor_bar"]);
function _skgIsBar(p) {
  return (p.fits_part_types || []).some(ptid => _SKG_BAR_CATS.has(_skg?.part_types?.[ptid]?.category));
}

// Accessory part_types (brackets/flanges/etc.) — kept OUT of the placement
// selector; product→product accessory links live in the Accessory Role section.
function _skgIsAccessoryPt(ptid) {
  const pt = _skg?.part_types?.[ptid];
  return !!pt && (!!pt.accessory_of || !!pt.accessory_category);
}
function _skgAccessoryCats() {
  const cats = Object.entries(_skg?.accessory_categories || {});
  if (cats.length) return cats.map(([id, c]) => [id, c.label || id]);
  return [["bracket_mount", "Bracket / Mount"], ["flange", "Flange"], ["cable", "Cable"],
          ["shroud", "Shroud"], ["lighthead", "Lighthead"], ["flasher_power", "Flasher / Power"],
          ["takedown", "Take-Down"], ["other", "Other"]];
}
function _skgAccLabel(catId) {
  return (_skg?.accessory_categories?.[catId]?.label) ||
    (_skgAccessoryCats().find(([id]) => id === catId)?.[1]) || catId;
}
function _skgIsAccessory(p) { return !!(p.accessory_category && (p.accessory_of_products || []).length); }

function _skgSkuQbState(pn) {
  if (pn.qb_item_id) return "in_qb";
  if (pn.qb_pending) return "pending";
  return "none";
}

// App-readiness rollup: home + (lights) every SKU has a color. Description is
// NOT required (a descriptive SKU/model is enough) and neither is price.
// An accessory's "home" is its PARENT product, not a part-type placement —
// so an accessory needs no fits_part_types; it's selectable only as an
// accessory of its parent (a future picker may also add accessories on their own).
function _skgReady(p) {
  const pns = p.part_numbers || [];
  const missing = [];
  if (_skgIsAccessory(p)) {
    /* placed via accessory_of_products — no part-type home required */
  } else if (p.accessory_category) {
    missing.push("parent");            // declared an accessory but no parent assigned yet
  } else if (!(p.fits_part_types || []).length) {
    missing.push("home");
  }
  if (!pns.length) missing.push("SKUs");
  // Lights need a color per SKU — except light bars, whose color is baked into
  // the configured part number (no per-SKU color tag to require).
  if (_skgIsLight(p) && !_skgIsBar(p) && pns.some(pn => !(pn.color || "").trim())) missing.push("color");
  return { ready: missing.length === 0, missing };
}

function _skgVehTagVocab() {
  const s = new Set();
  for (const p of Object.values(_skg?.products || {}))
    for (const pn of (p.part_numbers || []))
      for (const t of (pn.vehicle_tags || [])) s.add(t);
  return [...s].sort();
}

function _skgMfrsSorted() {
  return Object.entries(_skg?.manufacturers || {}).sort((a, b) => (a[1].label || a[0]).localeCompare(b[1].label || b[0]));
}
function _skgTagsSorted() {
  return Object.entries(_skg?.tags || {}).sort((a, b) => (a[1].label || a[0]).localeCompare(b[1].label || b[0]));
}
function _skgPtsSorted() {
  return Object.entries(_skg?.part_types || {}).sort((a, b) => (a[1].label || a[0]).localeCompare(b[1].label || b[0]));
}
function _skgProductsSorted() {
  return Object.entries(_skg?.products || {}).sort((a, b) =>
    _skgMfrLabel(a[1].manufacturer_id).localeCompare(_skgMfrLabel(b[1].manufacturer_id)) ||
    (a[1].model || a[0]).localeCompare(b[1].model || b[0]));
}

function _skgOpts(pairs, selected, placeholder) {
  return `<option value="">${esc(placeholder)}</option>` +
    pairs.map(([v, l]) => `<option value="${esc(v)}" ${v === selected ? "selected" : ""}>${esc(l)}</option>`).join("");
}
function _skgColorOpts(sel) {
  return `<option value="">—</option>` + _skgColors().map(c => `<option value="${esc(c)}" ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
}
function _skgLensOpts(sel) {
  return `<option value="">—</option>` + _SKG_LENS.map(c => `<option value="${esc(c)}" ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
}

// ─── filtering ───────────────────────────────────────────────────────────────

function _skgPopulateBrandFilter() {
  const sel = $("skg-brand");
  if (!sel) return;
  const used = new Set(Object.values(_skg?.products || {}).map(p => p.manufacturer_id).filter(Boolean));
  const prev = sel.value;
  sel.innerHTML = `<option value="">All brands</option>` +
    _skgMfrsSorted().filter(([id]) => used.has(id)).map(([id, m]) => `<option value="${esc(id)}">${esc(m.label || id)}</option>`).join("");
  sel.value = prev;
}

// Tree membership of a product, derived from its part-types (fits_part_types):
// which Type / Section / Zone / Part-type it belongs to. Products with no
// part-type home (e.g. freshly-imported QB items) have empty sets.
const _SKG_TYPE_ORDER = ["lights", "structural", "equipment", "k9", "extras"];

function _skgProductTree(p) {
  const fits = p.fits_part_types || [];
  const types = new Set(), sections = new Set(), zones = new Set();
  for (const ptid of fits) {
    const pt = _skg?.part_types?.[ptid];
    if (!pt) continue;
    if (pt.type_id) types.add(pt.type_id);
    for (const pos of (pt.tree_positions || [])) {
      if (pos.section) sections.add(pos.section);
      if (pos.zone) zones.add(pos.zone);
    }
  }
  return { types, sections, zones, pts: new Set(fits), hasHome: fits.length > 0 };
}

// Populate the Type/Section/Zone/Part-type selects. Section/Zone/Part-type
// options cascade off the chosen Type (like the part picker); current
// selections are preserved when still valid.
function _skgPopulateTreeFilters() {
  const typeSel = $("skg-type"), secSel = $("skg-section"), zoneSel = $("skg-zone"), ptSel = $("skg-pt");
  if (!typeSel) return;
  const pts = _skg?.part_types || {};
  const curType = typeSel.value, curSec = secSel.value, curZone = zoneSel.value, curPt = ptSel.value;

  const typesPresent = new Set(Object.values(pts).map(pt => pt.type_id).filter(Boolean));
  const typeOpts = _SKG_TYPE_ORDER.filter(t => typesPresent.has(t))
    .concat([...typesPresent].filter(t => !_SKG_TYPE_ORDER.includes(t)));
  typeSel.innerHTML = `<option value="">All types</option>` +
    typeOpts.map(t => `<option value="${esc(t)}">${esc(_skg?.types?.[t]?.label || t)}</option>`).join("") +
    `<option value="__none__">— No part-type —</option>`;
  typeSel.value = curType;

  const scoped = Object.entries(pts).filter(([, pt]) =>
    !curType || curType === "__none__" || pt.type_id === curType);
  const secSet = new Set(), zoneSet = new Set();
  for (const [, pt] of scoped) for (const pos of (pt.tree_positions || [])) {
    if (pos.section) secSet.add(pos.section);
    if (pos.zone) zoneSet.add(pos.zone);
  }
  const fill = (sel, ids, labelOf, cur, allLabel, none) => {
    const sorted = [...ids].sort((a, b) => labelOf(a).localeCompare(labelOf(b)));
    sel.innerHTML = `<option value="">${allLabel}</option>` +
      sorted.map(id => `<option value="${esc(id)}">${esc(labelOf(id))}</option>`).join("") +
      (none ? `<option value="__none__">${none}</option>` : "");
    sel.value = (cur === "__none__" && none) || ids.has(cur) ? cur : "";
  };
  fill(secSel, secSet, s => _skg?.sections?.[s]?.label || s, curSec, "All sections", "");
  fill(zoneSel, zoneSet, z => _skg?.zones?.[z]?.label || z, curZone, "All zones", "");
  const ptIds = new Set(scoped.map(([id]) => id));
  fill(ptSel, ptIds, id => _skg?.part_types?.[id]?.label || id, curPt, "All part-types", "— No part-type —");
}

function _skgFiltered() {
  const brand = $("skg-brand")?.value || "";
  const q = ($("skg-search")?.value || "").trim().toLowerCase();
  const qb = $("skg-qb")?.value || "";
  const readiness = $("skg-readiness")?.value || "";
  const review = $("skg-review")?.value || "";
  const ftype = $("skg-type")?.value || "", fsec = $("skg-section")?.value || "";
  const fzone = $("skg-zone")?.value || "", fpt = $("skg-pt")?.value || "";
  const out = [];
  for (const [pid, p] of Object.entries(_skg?.products || {})) {
    if (brand && p.manufacturer_id !== brand) continue;
    if (ftype || fsec || fzone || fpt) {
      const tr = _skgProductTree(p);
      if (ftype === "__none__") { if (tr.hasHome) continue; }
      else if (ftype && !tr.types.has(ftype)) continue;
      if (fsec && !tr.sections.has(fsec)) continue;
      if (fzone && !tr.zones.has(fzone)) continue;
      if (fpt === "__none__") { if (tr.hasHome) continue; }
      else if (fpt && !tr.pts.has(fpt)) continue;
    }
    if (review === "complete" && !p.reviewed) continue;
    if (review === "incomplete" && p.reviewed) continue;
    if (readiness) {
      const rd = _skgReady(p);
      if (readiness === "ready" && !rd.ready) continue;
      if (readiness === "needs" && rd.ready) continue;
    }
    const pns = p.part_numbers || [];
    if (qb && !pns.some(pn => _skgSkuQbState(pn) === qb)) continue;
    if (q) {
      const hay = (p.model || "") + " " + _skgMfrLabel(p.manufacturer_id) + " " + pid + " " +
        pns.map(pn => (pn.part_number || "") + " " + (pn.friendly_name || "")).join(" ");
      if (!hay.toLowerCase().includes(q)) continue;
    }
    out.push([pid, p]);
  }
  out.sort((a, b) =>
    _skgMfrLabel(a[1].manufacturer_id).localeCompare(_skgMfrLabel(b[1].manufacturer_id)) ||
    (a[1].model || a[0]).localeCompare(b[1].model || b[0]));
  return out;
}

// ─── render ──────────────────────────────────────────────────────────────────

function _skgRender() {
  const meta = $("skg-meta");
  if (meta && _skg?.metadata?.last_updated) meta.textContent = "Updated " + _skg.metadata.last_updated.slice(0, 10);
  const body = $("skg-body");
  if (!body) return;
  const rows = _skgFiltered();
  const skuTotal = rows.reduce((n, [, p]) => n + (p.part_numbers || []).length, 0);
  const reviewed = rows.filter(([, p]) => p.reviewed).length;
  const cnt = $("skg-count");
  if (cnt) cnt.textContent = `${rows.length} product${rows.length === 1 ? "" : "s"} · ${skuTotal} SKUs · ${reviewed} complete`;
  $("skg-empty").hidden = rows.length > 0;
  body.innerHTML = rows.map(([pid, p]) => _skgProductCard(pid, p)).join("");
  _skgRenderBulk();
}

function _skgProductCard(pid, p) {
  const open = _skgExpanded.has(pid);
  const pns = p.part_numbers || [];
  let inq = 0, pend = 0, none = 0;
  for (const pn of pns) { const s = _skgSkuQbState(pn); if (s === "in_qb") inq++; else if (s === "pending") pend++; else none++; }
  const qbRoll = pns.length
    ? [inq ? `${inq} in QB` : "", pend ? `${pend} pending` : "", none ? `${none} not in QB` : ""].filter(Boolean).join(" · ")
    : "no SKUs";
  const rd = _skgReady(p);
  const readiness = rd.ready
    ? `<span class="skg-badge skg-ready">Ready</span>`
    : `<span class="skg-badge skg-needs">Needs: ${esc(rd.missing.join(", "))}</span>`;
  const accBadge = _skgIsAccessory(p) ? `<span class="skg-badge skg-acc">${esc(_skgAccLabel(p.accessory_category))} accessory</span>` : "";
  const unbBadge = _skgIsUnbilled(p) ? `<span class="skg-badge skg-unbilled">Unbilled</span>` : "";
  const reviewed = !!p.reviewed;
  return `<div class="skg-prod ${open ? "open" : ""} ${reviewed ? "skg-reviewed" : ""}" data-pid="${esc(pid)}">
    <div class="skg-prod-head" data-skg="toggle" data-pid="${esc(pid)}">
      <span class="skg-caret">${open ? "▾" : "▸"}</span>
      <span class="skg-prod-model">${esc(p.model || pid)}</span>
      <span class="skg-prod-mfr">${esc(_skgMfrLabel(p.manufacturer_id))}</span>
      ${readiness}${accBadge}${unbBadge}
      <span class="skg-prod-badges">${esc(qbRoll)}</span>
      <label class="skg-complete" title="Mark this product reviewed / complete">
        <input type="checkbox" data-skg="reviewed" data-pid="${esc(pid)}" ${reviewed ? "checked" : ""}> Complete
      </label>
    </div>
    ${open ? _skgProductBody(pid, p) : ""}
  </div>`;
}

function _skgProductBody(pid, p) {
  const isLight = _skgIsLight(p);
  const isUnbilled = _skgIsUnbilled(p);
  const lid = _skgLightTagId(), uid = _skgUnbilledTagId();
  const hidden = new Set([lid, uid].filter(Boolean));   // shown via their own toggles
  const visibleTags = (p.tag_ids || []).filter(t => !hidden.has(t));
  const fitsChips = (p.fits_part_types || []).map(t =>
    `<span class="skg-chip">${esc(_skgPtLabel(t))}<button data-skg="chip-del" data-kind="fits" data-pid="${esc(pid)}" data-val="${esc(t)}">×</button></span>`).join("");
  const tagChips = visibleTags.map(t =>
    `<span class="skg-chip">${esc(_skgTagLabel(t))}<button data-skg="chip-del" data-kind="ptag" data-pid="${esc(pid)}" data-val="${esc(t)}">×</button></span>`).join("");
  const fitOpts = _skgPtsSorted().filter(([id]) => !(p.fits_part_types || []).includes(id) && !_skgIsAccessoryPt(id)).map(([id, v]) => [id, v.label || id]);
  const tagOpts = _skgTagsSorted().filter(([id]) => !(p.tag_ids || []).includes(id) && !hidden.has(id)).map(([id, v]) => [id, v.label || id]);

  // Accessory role (child → parent products).
  const accCat = p.accessory_category || "";
  const accParents = (p.accessory_of_products || []);
  const parentChips = accParents.map(par => {
    const pp = _skg.products?.[par];
    const lbl = pp ? `${_skgMfrLabel(pp.manufacturer_id)} · ${pp.model || par}` : par;
    return `<span class="skg-chip">${esc(lbl)}<button data-skg="chip-del" data-kind="accparent" data-pid="${esc(pid)}" data-val="${esc(par)}">×</button></span>`;
  }).join("");
  const parentOpts = _skgProductsSorted().filter(([id]) => id !== pid && !accParents.includes(id))
    .map(([id, pp]) => [id, `${_skgMfrLabel(pp.manufacturer_id)} · ${pp.model || id}`]);

  const head = isLight
    ? `<div class="skg-sku-head"><span></span><span>Part #</span><span>Sales Description</span><span>Color</span><span>2nd</span><span>3rd</span><span>Lens</span><span>Price</span><span>Pend</span><span></span></div>`
    : `<div class="skg-sku-head"><span></span><span>Part #</span><span>Sales Description</span><span>Price</span><span>Pend</span><span></span></div>`;
  const skuRows = (p.part_numbers || []).map((pn, i) => _skgSkuRow(pid, i, pn, isLight, isUnbilled)).join("");

  return `<div class="skg-prod-body">
    <div class="skg-prod-fields">
      <label class="skg-fl">Model<input class="skg-in" data-skg="pfield" data-pid="${esc(pid)}" data-field="model" value="${esc(p.model || "")}"></label>
      <label class="skg-fl">Brand
        <select class="skg-in" data-skg="pmfr" data-pid="${esc(pid)}">
          ${_skgOpts(_skgMfrsSorted().map(([id, m]) => [id, m.label || id]), p.manufacturer_id || "", "—")}
          <option value="__create__">＋ Create new…</option>
        </select>
      </label>
      <label class="skg-fl skg-toggle" title="Show color/lens fields & require color for this product (the 'light' tag)">
        <input type="checkbox" data-skg="lighttoggle" data-pid="${esc(pid)}" ${isLight ? "checked" : ""}> Light
      </label>
      <label class="skg-fl skg-toggle" title="Agency-supplied — never quoted, skipped on estimates, needs no QB id (the 'unbilled' tag)">
        <input type="checkbox" data-skg="unbilledtoggle" data-pid="${esc(pid)}" ${isUnbilled ? "checked" : ""}> Unbilled
      </label>
      <label class="skg-fl skg-fl-wide">Notes<input class="skg-in" data-skg="pfield" data-pid="${esc(pid)}" data-field="description" value="${esc(p.description || "")}"></label>
    </div>
    <div class="skg-prod-rels">
      <div class="skg-rel">
        <span class="skg-rel-label">Part types (picker placement)</span>
        <div class="skg-chips">${fitsChips || '<span class="skg-muted">none — catalog-only, invisible to the picker</span>'}
          <select class="skg-add" data-skg="add-fits" data-pid="${esc(pid)}">${_skgOpts(fitOpts, "", "+ add part type…")}<option value="__create__">＋ Create new…</option></select>
        </div>
      </div>
      <div class="skg-rel">
        <span class="skg-rel-label">Tags</span>
        <div class="skg-chips">${tagChips || '<span class="skg-muted">none</span>'}
          <select class="skg-add" data-skg="add-ptag" data-pid="${esc(pid)}">${_skgOpts(tagOpts, "", "+ add tag…")}<option value="__create__">＋ Create new…</option></select>
        </div>
      </div>
    </div>
    <div class="skg-prod-rels">
      <div class="skg-rel">
        <span class="skg-rel-label">Accessory role <span class="skg-muted">(makes this product a child of another)</span></span>
        <div class="skg-acc-row">
          <select class="skg-in" data-skg="acccat" data-pid="${esc(pid)}">
            <option value="">Not an accessory</option>
            ${_skgAccessoryCats().map(([id, l]) => `<option value="${esc(id)}" ${id === accCat ? "selected" : ""}>${esc(l)}</option>`).join("")}
          </select>
          <label class="skg-pend" title="Block adding the parent until this accessory is chosen"><input type="checkbox" data-skg="accreq" data-pid="${esc(pid)}" ${p.accessory_required ? "checked" : ""} ${accCat ? "" : "disabled"}> required</label>
        </div>
        ${accCat ? `<div class="skg-chips" style="margin-top:6px">${parentChips || '<span class="skg-muted">belongs to: pick a product →</span>'}
          <select class="skg-add" data-skg="add-accparent" data-pid="${esc(pid)}">${_skgOpts(parentOpts, "", "+ belongs to…")}</select>
        </div>` : ""}
      </div>
    </div>
    <div class="skg-sku-table ${isLight ? "skg-light" : "skg-plain"}">
      ${head}
      ${skuRows || '<div class="skg-muted" style="padding:6px 4px">No SKUs yet.</div>'}
    </div>
    <div class="skg-prod-actions">
      <button class="btn btn-secondary btn-sm" data-skg="add-sku" data-pid="${esc(pid)}">+ SKU</button>
      <button class="btn btn-danger btn-sm" data-skg="del-product" data-pid="${esc(pid)}">Delete product</button>
    </div>
  </div>`;
}

// Read-only QB-source line: the real QuickBooks data for this SKU, or a clear note.
function _skgQbLine(pn, isUnbilled) {
  const st = _skgSkuQbState(pn);
  if (st === "in_qb") {
    const it = _skgQb[String(pn.qb_item_id)];
    if (it) {
      const bits = [it.sku ? "sku " + it.sku : "", it.description ? `“${it.description}”` : "",
        it.unit_price != null ? "QBO list $" + it.unit_price : "", it.type || ""].filter(Boolean).join(" · ");
      return `<span class="skg-pill skg-pill-qb">In QB</span><span class="skg-qbtxt">${esc(it.name || "")}${bits ? " · " + esc(bits) : ""}</span>`;
    }
    return `<span class="skg-pill skg-pill-qb">In QB</span><span class="skg-qbtxt">item ${esc(pn.qb_item_id)} — sync to load its QB data</span>`;
  }
  if (st === "pending")
    return `<span class="skg-pill skg-pill-pend">Pending QB</span><span class="skg-qbtxt">pre-added — not yet in QuickBooks (price hand-set; reconciles on sync)</span>`;
  if (isUnbilled)
    return `<span class="skg-pill skg-pill-unbilled">Unbilled</span><span class="skg-qbtxt">agency-supplied — tracked on the build, never quoted (no QB id needed)</span>`;
  return `<span class="skg-pill skg-pill-none">Not in QB</span><span class="skg-qbtxt">DB-only — won't bill on a QB estimate until matched</span>`;
}

function _skgSkuRow(pid, i, pn, isLight, isUnbilled) {
  const linked = !!pn.qb_item_id;
  const key = pid + " " + i;
  const price = (pn.qb_unit_price != null ? pn.qb_unit_price : pn.price_usd);
  const vt = (pn.vehicle_tags || []).filter(t => t && t !== "any");
  const vtChips = vt.map(t =>
    `<span class="skg-chip skg-chip-sm">${esc(t)}<button data-skg="chip-del" data-kind="vehtag" data-pid="${esc(pid)}" data-idx="${i}" data-val="${esc(t)}">×</button></span>`).join("");
  const vtOpts = _skgVehTagVocab().filter(t => !vt.includes(t) && t !== "any").map(t => [t, t]);
  const colorCells = isLight ? `
    <select class="skg-in" data-skg="sfield" data-field="color" data-pid="${esc(pid)}" data-idx="${i}">${_skgColorOpts(pn.color || "")}</select>
    <select class="skg-in" data-skg="sfield" data-field="secondary_color" data-pid="${esc(pid)}" data-idx="${i}">${_skgColorOpts(pn.secondary_color || "")}</select>
    <select class="skg-in" data-skg="sfield" data-field="tertiary_color" data-pid="${esc(pid)}" data-idx="${i}">${_skgColorOpts(pn.tertiary_color || "")}</select>
    <select class="skg-in" data-skg="sfield" data-field="lens_type" data-pid="${esc(pid)}" data-idx="${i}">${_skgLensOpts(pn.lens_type || "")}</select>` : "";
  return `<div class="skg-sku" data-idx="${i}">
    <input type="checkbox" data-skg="sel" data-pid="${esc(pid)}" data-idx="${i}" ${_skgSel.has(key) ? "checked" : ""}>
    <input class="skg-in" data-skg="sfield" data-field="part_number" data-pid="${esc(pid)}" data-idx="${i}" value="${esc(pn.part_number || "")}">
    <input class="skg-in" data-skg="sfield" data-field="friendly_name" data-pid="${esc(pid)}" data-idx="${i}" value="${esc(pn.friendly_name || "")}" placeholder="sales description (optional)">
    ${colorCells}
    <input type="number" step="0.01" class="skg-in skg-price" data-skg="sfield" data-field="price_usd" data-pid="${esc(pid)}" data-idx="${i}" value="${price != null ? price : ""}" ${linked ? 'readonly title="QBO list price synced from QuickBooks"' : ""}>
    <label class="skg-pend" title="Pre-added before it exists in QuickBooks"><input type="checkbox" data-skg="sfield" data-field="qb_pending" data-pid="${esc(pid)}" data-idx="${i}" ${pn.qb_pending ? "checked" : ""} ${linked ? "disabled" : ""}></label>
    <span class="skg-sku-btns">
      <button data-skg="move-sku" data-pid="${esc(pid)}" data-idx="${i}" title="Move to another product">→</button>
      <button data-skg="del-sku" data-pid="${esc(pid)}" data-idx="${i}" title="Delete SKU">✕</button>
    </span>
    <div class="skg-qbsrc">${_skgQbLine(pn, isUnbilled)}</div>
    <div class="skg-vehtags">
      <span class="skg-vt-label">Vehicles:</span> ${vtChips || '<span class="skg-muted">any</span>'}
      <select class="skg-add skg-add-sm" data-skg="add-vehtag" data-pid="${esc(pid)}" data-idx="${i}">${_skgOpts(vtOpts, "", "+ vehicle…")}<option value="__new__">＋ New…</option></select>
    </div>
  </div>`;
}

// ─── helpers shared by handlers ──────────────────────────────────────────────

function _skgRowExpect(el) {
  const row = el.closest(".skg-sku");
  const pnInput = row?.querySelector('input[data-field="part_number"]');
  return pnInput ? pnInput.value : "";
}
function _skgSavedFlash() {
  const meta = $("skg-meta");
  if (!meta) return;
  const prev = meta._base ?? meta.textContent;
  meta._base = prev;
  meta.textContent = "Saved ✓";
  clearTimeout(meta._t);
  meta._t = setTimeout(() => { meta.textContent = meta._base; }, 1400);
}

async function _skgEdit(action, payload) {
  let res;
  try { res = await api("/api/parts-db/edit/" + action, payload); }
  catch (e) { toast("Save failed: " + (e?.message || e), "error"); return null; }
  if (!res?.ok) { toast("Save failed: " + (res?.error || "unknown"), "error"); return null; }
  _skgSavedFlash();
  return res;
}

function _skgLocalSku(pid, idx, field, val) {
  const pn = _skg?.products?.[pid]?.part_numbers?.[idx];
  if (!pn) return;
  if (field === "price_usd") pn.price_usd = (val === "" || val == null) ? null : Number(val);
  else if (field === "qb_pending") { if (val) pn.qb_pending = true; else delete pn.qb_pending; }
  else pn[field] = val;
}

async function _skgToggleTag(pid, on, name, label) {
  let tid = _skgNamedTagId(name);
  if (on && !tid) {
    const tr = await _skgEdit("tag-create", { label });
    if (!tr) return;
    await _skgLoad();
    tid = _skgNamedTagId(name);
  }
  if (!tid) return;
  const cur = (_skg.products[pid].tag_ids || []).slice();
  const next = on ? (cur.includes(tid) ? cur : [...cur, tid]) : cur.filter(x => x !== tid);
  const res = await _skgEdit("product-update", { product_id: pid, fields: { tag_ids: next } });
  if (res) { _skg.products[pid].tag_ids = next; _skgRerenderProduct(pid); }
}

async function _skgAddRel(pid, kind, val) {
  const cur = (_skg.products[pid][kind] || []).slice();
  if (cur.includes(val)) return;
  cur.push(val);
  const res = await _skgEdit("product-update", { product_id: pid, fields: { [kind]: cur } });
  if (res) { _skg.products[pid][kind] = cur; _skgRerenderProduct(pid); }
}

// ─── wiring (delegated, once) ────────────────────────────────────────────────

function _skgWireOnce() {
  if (_skgWired) return;
  _skgWired = true;

  $("skg-reload")?.addEventListener("click", async () => { await _skgLoad(); await _skgLoadQb(); _skgPopulateBrandFilter(); _skgPopulateTreeFilters(); _skgRender(); toast("Reloaded", "success"); });
  $("skg-brand")?.addEventListener("change", _skgRender);
  $("skg-type")?.addEventListener("change", () => { _skgPopulateTreeFilters(); _skgRender(); });
  $("skg-section")?.addEventListener("change", _skgRender);
  $("skg-zone")?.addEventListener("change", _skgRender);
  $("skg-pt")?.addEventListener("change", _skgRender);
  $("skg-qb")?.addEventListener("change", _skgRender);
  $("skg-readiness")?.addEventListener("change", _skgRender);
  $("skg-review")?.addEventListener("change", _skgRender);
  $("skg-search")?.addEventListener("input", () => { clearTimeout(_skgSearchTimer); _skgSearchTimer = setTimeout(_skgRender, 150); });
  $("skg-add-product")?.addEventListener("click", _skgCreateProduct);
  $("skg-backfill")?.addEventListener("click", async () => {
    if (!confirm("Fill empty Sales Descriptions from QuickBooks for all linked SKUs?")) return;
    const res = await _skgEdit("backfill-descriptions", {});
    if (res) { toast(`Filled ${res.count} description${res.count === 1 ? "" : "s"}`, "success"); await _skgLoad(); _skgRender(); }
  });
  $("skg-seed-lights")?.addEventListener("click", async () => {
    if (!confirm("Tag products as 'Light' where a SKU has a color or it fits a light part type? You can correct individual products afterward with the Light checkbox.")) return;
    const res = await _skgEdit("seed-light-tags", {});
    if (res) { toast(`Tagged ${res.count} product${res.count === 1 ? "" : "s"} as Light`, "success"); await _skgLoad(); _skgRender(); }
  });

  $("skg-modal-close")?.addEventListener("click", _skgCloseModal);
  $("skg-modal-cancel")?.addEventListener("click", _skgCloseModal);
  $("skg-modal")?.addEventListener("click", e => { if (e.target.id === "skg-modal") _skgCloseModal(); });
  $("skg-modal-save")?.addEventListener("click", () => { if (_skgModalSave) _skgModalSave(); });

  const body = $("skg-body");
  body?.addEventListener("change", _skgOnChange);
  body?.addEventListener("click", _skgOnClick);
  $("skg-bulk")?.addEventListener("click", _skgOnBulkClick);
  $("skg-bulk")?.addEventListener("change", _skgOnBulkChange);
}

async function _skgOnChange(e) {
  const t = e.target;
  const act = t.dataset.skg;
  if (!act) return;
  const pid = t.dataset.pid;

  if (act === "sel") {
    const key = pid + " " + t.dataset.idx;
    if (t.checked) _skgSel.add(key); else _skgSel.delete(key);
    _skgRenderBulk();
    return;
  }
  if (act === "reviewed") {
    const res = await _skgEdit("product-update", { product_id: pid, fields: { reviewed: t.checked } });
    if (res) { _skg.products[pid].reviewed = t.checked; _skgRerenderProduct(pid); }
    return;
  }
  if (act === "lighttoggle") { await _skgToggleTag(pid, t.checked, "light", "Light"); return; }
  if (act === "unbilledtoggle") { await _skgToggleTag(pid, t.checked, "unbilled", "Unbilled"); return; }

  if (act === "sfield") {
    const idx = Number(t.dataset.idx);
    const field = t.dataset.field;
    const val = (t.type === "checkbox") ? t.checked : t.value;
    const expect = field === "part_number" ? "" : _skgRowExpect(t);
    const res = await _skgEdit("sku-update", { product_id: pid, index: idx, expect_part_number: expect, fields: { [field]: val } });
    if (res) _skgLocalSku(pid, idx, field, val);
    return;
  }
  if (act === "pfield") {
    const field = t.dataset.field;
    const res = await _skgEdit("product-update", { product_id: pid, fields: { [field]: t.value } });
    if (res && _skg.products[pid]) _skg.products[pid][field] = t.value;
    return;
  }
  if (act === "pmfr") {
    if (t.value === "__create__") {
      t.value = _skg.products[pid].manufacturer_id || "";
      _skgCreateManufacturer(mid => _skgEdit("product-update", { product_id: pid, fields: { manufacturer_id: mid } }).then(r => { if (r) { _skg.products[pid].manufacturer_id = mid; _skgPopulateBrandFilter(); _skgRender(); } }));
      return;
    }
    const res = await _skgEdit("product-update", { product_id: pid, fields: { manufacturer_id: t.value } });
    if (res) { _skg.products[pid].manufacturer_id = t.value; _skgPopulateBrandFilter(); _skgRender(); }
    return;
  }

  if (act === "add-fits" || act === "add-ptag") {
    const kind = act === "add-fits" ? "fits_part_types" : "tag_ids";
    const val = t.value; t.value = "";
    if (!val) return;
    if (val === "__create__") {
      if (act === "add-fits") _skgCreatePartType(ptid => _skgAddRel(pid, kind, ptid));
      else _skgCreateTag(tid => _skgAddRel(pid, kind, tid));
      return;
    }
    _skgAddRel(pid, kind, val);
    return;
  }

  if (act === "acccat") {
    const cat = t.value;
    const fields = { accessory_category: cat };
    if (!cat) { fields.accessory_of_products = []; fields.accessory_required = false; }
    const res = await _skgEdit("product-update", { product_id: pid, fields });
    if (res) { Object.assign(_skg.products[pid], fields); _skgRerenderProduct(pid); }
    return;
  }
  if (act === "accreq") {
    const res = await _skgEdit("product-update", { product_id: pid, fields: { accessory_required: t.checked } });
    if (res) _skg.products[pid].accessory_required = t.checked;
    return;
  }
  if (act === "add-accparent") {
    const val = t.value; t.value = "";
    if (!val) return;
    const cur = (_skg.products[pid].accessory_of_products || []).slice();
    if (cur.includes(val)) return;
    cur.push(val);
    const res = await _skgEdit("product-update", { product_id: pid, fields: { accessory_of_products: cur } });
    if (res) { _skg.products[pid].accessory_of_products = cur; _skgRerenderProduct(pid); }
    return;
  }

  if (act === "add-vehtag") {
    const idx = Number(t.dataset.idx);
    let val = t.value; t.value = "";
    if (val === "__new__") val = (prompt("New vehicle tag:") || "").trim();
    if (!val) return;
    const pn = _skg.products[pid].part_numbers[idx];
    const tags = (pn.vehicle_tags || []).filter(x => x !== "any");
    if (tags.includes(val)) return;
    tags.push(val);
    const res = await _skgEdit("sku-update", { product_id: pid, index: idx, expect_part_number: pn.part_number || "", fields: { vehicle_tags: tags } });
    if (res) { pn.vehicle_tags = tags; _skgRerenderProduct(pid); }
    return;
  }
}

async function _skgOnClick(e) {
  const btn = e.target.closest("[data-skg]");
  if (!btn) return;
  const act = btn.dataset.skg;
  const pid = btn.dataset.pid;

  if (act === "toggle") {
    if (e.target.closest(".skg-complete")) return;
    if (_skgExpanded.has(pid)) _skgExpanded.delete(pid); else _skgExpanded.add(pid);
    _skgRerenderProduct(pid);
    return;
  }

  if (act === "chip-del") {
    const kind = btn.dataset.kind, val = btn.dataset.val;
    if (kind === "vehtag") {
      const idx = Number(btn.dataset.idx);
      const pn = _skg.products[pid].part_numbers[idx];
      const tags = (pn.vehicle_tags || []).filter(x => x !== val);
      const res = await _skgEdit("sku-update", { product_id: pid, index: idx, expect_part_number: pn.part_number || "", fields: { vehicle_tags: tags } });
      if (res) { pn.vehicle_tags = tags; _skgRerenderProduct(pid); }
      return;
    }
    if (kind === "accparent") {
      const cur = (_skg.products[pid].accessory_of_products || []).filter(x => x !== val);
      const res = await _skgEdit("product-update", { product_id: pid, fields: { accessory_of_products: cur } });
      if (res) { _skg.products[pid].accessory_of_products = cur; _skgRerenderProduct(pid); }
      return;
    }
    const field = kind === "fits" ? "fits_part_types" : "tag_ids";
    const cur = (_skg.products[pid][field] || []).filter(x => x !== val);
    const res = await _skgEdit("product-update", { product_id: pid, fields: { [field]: cur } });
    if (res) { _skg.products[pid][field] = cur; _skgRerenderProduct(pid); }
    return;
  }

  if (act === "add-sku") {
    const res = await _skgEdit("sku-add", { product_id: pid, sku: {} });
    if (res) { await _skgLoad(); _skgRerenderProduct(pid); }
    return;
  }
  if (act === "del-sku") {
    const idx = Number(btn.dataset.idx);
    const expect = _skgRowExpect(btn);
    if (!confirm(`Delete SKU "${expect || "(blank)"}"?`)) return;
    const res = await _skgEdit("sku-delete", { product_id: pid, index: idx, expect_part_number: expect });
    if (res) { await _skgLoad(); _skgRerenderProduct(pid); }
    return;
  }
  if (act === "move-sku") {
    _skgOpenMove(pid, Number(btn.dataset.idx), _skgRowExpect(btn));
    return;
  }
  if (act === "del-product") {
    const p = _skg.products[pid];
    if (!confirm(`Delete product "${p?.model || pid}" and its ${(p?.part_numbers || []).length} SKUs?`)) return;
    const res = await _skgEdit("product-delete", { product_id: pid });
    if (res) { _skgExpanded.delete(pid); await _skgLoad(); _skgPopulateBrandFilter(); _skgRender(); }
    return;
  }
}

function _skgRerenderProduct(pid) {
  const node = $("skg-body")?.querySelector(`.skg-prod[data-pid="${CSS.escape(pid)}"]`);
  const p = _skg?.products?.[pid];
  if (!node) { _skgRender(); return; }
  if (!p) { node.remove(); return; }
  const tmp = document.createElement("div");
  tmp.innerHTML = _skgProductCard(pid, p);
  node.replaceWith(tmp.firstElementChild);
  _skgRenderBulk();
}

// ─── bulk bar ────────────────────────────────────────────────────────────────

function _skgRenderBulk() {
  const bar = $("skg-bulk");
  if (!bar) return;
  for (const key of [..._skgSel]) {
    const [pid, idx] = key.split(" ");
    if (!_skg?.products?.[pid]?.part_numbers?.[Number(idx)]) _skgSel.delete(key);
  }
  if (!_skgSel.size) { bar.hidden = true; bar.innerHTML = ""; return; }
  bar.hidden = false;
  bar.innerHTML = `
    <span class="skg-bulk-count">${_skgSel.size} selected</span>
    <select class="skg-in" data-skg-bulk="lens"><option value="">Set lens…</option>${_SKG_LENS.map(l => `<option value="${l}">${l}</option>`).join("")}</select>
    <button class="btn btn-secondary btn-sm" data-skg-bulk="clear-pending">Clear pending</button>
    <button class="btn btn-danger btn-sm" data-skg-bulk="delete">Delete selected</button>
    <button class="btn btn-secondary btn-sm" data-skg-bulk="clear">Clear selection</button>`;
}

function _skgSelTargets() {
  return [..._skgSel].map(k => { const [pid, idx] = k.split(" "); return { product_id: pid, index: Number(idx) }; });
}

async function _skgOnBulkChange(e) {
  if (e.target.dataset.skgBulk === "lens" && e.target.value) {
    await _skgEdit("sku-bulk", { targets: _skgSelTargets(), op: "set", fields: { lens_type: e.target.value } });
    await _skgLoad(); _skgRender();
  }
}
async function _skgOnBulkClick(e) {
  const act = e.target.dataset?.skgBulk;
  if (!act) return;
  if (act === "clear") { _skgSel.clear(); _skgRenderBulk(); _skgRender(); return; }
  if (act === "clear-pending") {
    await _skgEdit("sku-bulk", { targets: _skgSelTargets(), op: "set", fields: { qb_pending: false } });
    await _skgLoad(); _skgRender(); return;
  }
  if (act === "delete") {
    if (!confirm(`Delete ${_skgSel.size} selected SKU(s)?`)) return;
    await _skgEdit("sku-bulk", { targets: _skgSelTargets(), op: "delete" });
    _skgSel.clear(); await _skgLoad(); _skgRender();
  }
}

// ─── modal (create-new entities + move) ──────────────────────────────────────

function _skgOpenModal(title, bodyHtml, onSave, saveLabel) {
  $("skg-modal-title").textContent = title;
  $("skg-modal-body").innerHTML = bodyHtml;
  const saveBtn = $("skg-modal-save");
  saveBtn.textContent = saveLabel || "Create";
  saveBtn.hidden = !onSave;
  _skgModalSave = onSave;
  $("skg-modal").classList.add("open");
  $("skg-modal-body").querySelector("input,select,textarea")?.focus();
}
function _skgCloseModal() { $("skg-modal").classList.remove("open"); _skgModalSave = null; }

function _skgCreateManufacturer(onCreated) {
  _skgOpenModal("Create manufacturer", `
    <label class="skg-fl">Name<input id="skg-m-label" class="skg-in" placeholder="e.g. SoundOff Signal"></label>
    <label class="skg-fl">Website (optional)<input id="skg-m-web" class="skg-in" placeholder="https://…"></label>`,
    async () => {
      const label = $("skg-m-label").value.trim();
      if (!label) { toast("Name is required", "error"); return; }
      const res = await _skgEdit("manufacturer-create", { label, website: $("skg-m-web").value.trim() });
      if (!res) return;
      await _skgLoad(); _skgCloseModal(); onCreated && onCreated(res.manufacturer_id);
    });
}
function _skgCreateTag(onCreated) {
  _skgOpenModal("Create tag", `<label class="skg-fl">Tag name<input id="skg-t-label" class="skg-in" placeholder="e.g. siren"></label>`,
    async () => {
      const label = $("skg-t-label").value.trim();
      if (!label) { toast("Name is required", "error"); return; }
      const res = await _skgEdit("tag-create", { label });
      if (!res) return;
      await _skgLoad(); _skgCloseModal(); onCreated && onCreated(res.tag_id);
    });
}
function _skgCreatePartType(onCreated) {
  const typeOpts = Object.entries(_skg?.types || {}).map(([id, t]) => [id, t.label || id]);
  _skgOpenModal("Create part type", `
    <label class="skg-fl">Label<input id="skg-pt-label" class="skg-in" placeholder="e.g. Forward Warning"></label>
    <label class="skg-fl">Type<select id="skg-pt-type" class="skg-in">${_skgOpts(typeOpts, "lights", "—")}</select></label>
    <label class="skg-fl">Category (optional)<input id="skg-pt-cat" class="skg-in" placeholder="warning / scene / interior…"></label>
    <p class="skg-muted" style="margin:6px 0 0">Tree position (where it sorts in the picker) can be set in the Hierarchy tab.</p>`,
    async () => {
      const label = $("skg-pt-label").value.trim();
      const type_id = $("skg-pt-type").value;
      if (!label || !type_id) { toast("Label and type are required", "error"); return; }
      const res = await _skgEdit("part-type-create", { label, type_id, category: $("skg-pt-cat").value.trim() });
      if (!res) return;
      await _skgLoad(); _skgCloseModal(); onCreated && onCreated(res.part_type_id);
    });
}
// `onCreated(product_id)` (optional) lets callers chain off a fresh product —
// e.g. the SKU-move flow creating a new destination. Guarded with typeof so the
// click-handler's event object isn't mistaken for a callback.
function _skgCreateProduct(onCreated) {
  const cb = typeof onCreated === "function" ? onCreated : null;
  const mfrOpts = _skgMfrsSorted().map(([id, m]) => [id, m.label || id]);
  _skgOpenModal("Create product", `
    <label class="skg-fl">Model<input id="skg-np-model" class="skg-in" placeholder="e.g. ION"></label>
    <label class="skg-fl">Brand<select id="skg-np-mfr" class="skg-in">${_skgOpts(mfrOpts, "", "—")}</select></label>
    <label class="skg-fl">Notes (optional)<input id="skg-np-desc" class="skg-in"></label>`,
    async () => {
      const model = $("skg-np-model").value.trim();
      if (!model) { toast("Model is required", "error"); return; }
      const res = await _skgEdit("product-create", { model, manufacturer_id: $("skg-np-mfr").value, description: $("skg-np-desc").value.trim() });
      if (!res) return;
      await _skgLoad(); _skgPopulateBrandFilter(); _skgCloseModal();
      if (cb) { cb(res.product_id); return; }
      _skgExpanded.add(res.product_id);
      _skgRender();
      $("skg-body")?.querySelector(`.skg-prod[data-pid="${CSS.escape(res.product_id)}"]`)?.scrollIntoView({ block: "center" });
    }, "Create");
}
function _skgOpenMove(pid, idx, expect) {
  const others = _skgProductsSorted().filter(([id]) => id !== pid);
  const moveTo = async dst => {
    const res = await _skgEdit("sku-move", { from_product_id: pid, to_product_id: dst, index: idx, expect_part_number: expect });
    if (res) { _skgExpanded.add(dst); await _skgLoad(); _skgCloseModal(); _skgRender(); }
  };
  const createOpt = `<button class="skg-move-opt skg-move-new" data-create="1">➕ Create new product…</button>`;
  const list = others.map(([id, p]) =>
    `<button class="skg-move-opt" data-target="${esc(id)}">${esc(_skgMfrLabel(p.manufacturer_id))} · ${esc(p.model || id)}</button>`).join("");
  _skgOpenModal(`Move "${expect || "SKU"}" to…`, `
    <input id="skg-move-search" class="skg-in" placeholder="Search product…" style="margin-bottom:8px">
    <div id="skg-move-list" class="skg-move-list">${createOpt}${list}</div>`, null, "");
  const search = $("skg-move-search");
  const listEl = $("skg-move-list");
  search?.addEventListener("input", () => {
    const q = search.value.toLowerCase();
    // Keep the create option visible while filtering existing products.
    listEl.querySelectorAll(".skg-move-opt").forEach(b => {
      if (b.dataset.create) return;
      b.hidden = q && !b.textContent.toLowerCase().includes(q);
    });
  });
  listEl?.addEventListener("click", async e => {
    const opt = e.target.closest(".skg-move-opt");
    if (!opt) return;
    if (opt.dataset.create) { _skgCreateProduct(newPid => moveTo(newPid)); return; }
    moveTo(opt.dataset.target);
  });
}
