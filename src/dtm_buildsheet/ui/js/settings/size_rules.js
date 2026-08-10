// ════════════════════════════════════════════════════════════════════════════
// LIGHT SIZE RULES
//
// The manifest owns reusable profiles. Parts-db assignments are the source of
// truth: explicit SKU → product → part type → Small default profile.
// ════════════════════════════════════════════════════════════════════════════
const SIZE_VIEWS = ["front", "rear", "side", "top"];
let _sizePartsDb = null;
let _sizePartsDbDirty = false;
let _sizeExpandedTargets = new Set();
let _sizeRulesInitialized = false;

const srAttr = value => esc(value == null ? "" : value).replace(/"/g, "&quot;");
function srProfileDefs(){
  const list = $("size-defs-tbody");
  if(!list || list.dataset.rendered !== "1") return _manifest?.size_rule_definitions || {};
  const defs = {};
  for(const card of list.querySelectorAll(".sr-profile-card")){
    const id = card.querySelector(".sr-def-id")?.value.trim();
    if(!id) continue;
    const views = {};
    for(const view of SIZE_VIEWS){
      const w = Number(card.querySelector(`.sr-def-w[data-view="${view}"]`)?.value);
      const h = Number(card.querySelector(`.sr-def-h[data-view="${view}"]`)?.value);
      if(Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0) views[view] = {w, h};
    }
    defs[id] = {
      label:card.querySelector(".sr-def-label")?.value.trim() || id,
      maintain_aspect_ratio:!!card.querySelector(".sr-def-ar")?.checked,
      views,
    };
  }
  return defs;
}

function initSizeRules(){
  if(_sizeRulesInitialized) return;
  _sizeRulesInitialized = true;
  renderSizeDefs();
  bindSizeRuleEvents();
  loadSizePartsDb();
}

function markSizeRulesDirty(){
  const status = $("sr-db-status");
  if(status) status.textContent = "Unsaved changes";
}

async function loadSizePartsDb(){
  const status = $("sr-db-status");
  try {
    _sizePartsDb = await api("/api/parts-db");
    _sizePartsDbDirty = false;
    if(status) status.textContent = "Parts database loaded";
    renderSizeAssignments();
  } catch(error){
    _sizePartsDb = null;
    if(status) status.textContent = "Parts database unavailable";
    const list = $("size-assignments-list");
    if(list) list.innerHTML = `<div class="sr-empty">Could not load the parts database.</div>`;
    console.error("size rules parts-db load failed", error);
  }
}

function sizeProfileOptions(selected=""){
  const defs = srProfileDefs();
  const options = Object.entries(defs).map(([id, def]) =>
    `<option value="${srAttr(id)}" ${id === selected ? "selected" : ""}>${esc(def.label || id)} (${esc(id)})</option>`
  );
  if(selected && !defs[selected]){
    options.unshift(`<option value="${srAttr(selected)}" selected>Missing profile: ${esc(selected)}</option>`);
  }
  return `<option value="">Inherit / default profile</option>${options.join("")}`;
}

function profilePreview(w, h){
  const width = Math.max(8, Math.min(Math.round((Number(w) || 0.1) * 100), 180));
  const height = Math.max(8, Math.min(Math.round((Number(h) || 0.1) * 100), 72));
  return `width:${width}px;height:${height}px`;
}

function sizeDefCard(id, def){
  const views = def.views || {};
  const front = views.front || {w:def.width_in || 0.3, h:def.height_in || 0.15};
  return `<article class="sr-profile-card" data-original-id="${srAttr(id)}">
    <div class="sr-profile-topline">
      <div class="sr-profile-identity">
        <input class="sr-def-id" value="${srAttr(id)}" aria-label="Profile ID" spellcheck="false">
        <input class="sr-def-label" value="${srAttr(def.label || id)}" aria-label="Profile label" placeholder="Profile label">
      </div>
      <label class="sr-check"><input class="sr-def-ar" type="checkbox" ${def.maintain_aspect_ratio ? "checked" : ""}> Lock aspect</label>
      <button class="btn btn-danger btn-sm sr-def-delete" type="button">Remove</button>
    </div>
    <div class="sr-profile-views">
      ${SIZE_VIEWS.map(view => {
        const value = views[view] || (view === "front" ? front : {w:front.w, h:front.h});
        return `<label class="sr-view-field"><span>${view}</span>
          <span class="sr-dimension"><b>W</b><input class="sr-def-w" data-view="${view}" type="number" min="0.01" max="8" step="0.001" value="${srAttr(value.w)}"></span>
          <span class="sr-dimension"><b>H</b><input class="sr-def-h" data-view="${view}" type="number" min="0.01" max="6" step="0.001" value="${srAttr(value.h)}"></span>
        </label>`;
      }).join("")}
    </div>
    <div class="sr-profile-preview-row"><span>Front preview</span><div class="sp-rect sr-profile-preview" style="${profilePreview(front.w, front.h)}"></div><span class="sr-profile-hint">inches · vertical artwork swaps W/H</span></div>
  </article>`;
}

function renderSizeDefs(){
  const list = $("size-defs-tbody");
  if(!list) return;
  const defs = srProfileDefs();
  const rows = Object.entries(defs).map(([id, def]) => sizeDefCard(id, def));
  list.innerHTML = rows.join("") || `<div class="sr-empty">No size profiles yet. Add one to begin.</div>`;
  list.dataset.rendered = "1";
}

function bindSizeRuleEvents(){
  const defs = $("size-defs-tbody");
  const assignments = $("size-assignments-list");
  if(defs && !defs.dataset.bound){
    defs.dataset.bound = "1";
    defs.addEventListener("focusin", event => {
      const input = event.target.closest(".sr-def-w,.sr-def-h");
      if(!input) return;
      const card = input.closest(".sr-profile-card");
      const view = input.dataset.view;
      const w = card?.querySelector(`.sr-def-w[data-view="${view}"]`);
      const h = card?.querySelector(`.sr-def-h[data-view="${view}"]`);
      if(w && h){ w.dataset.previous = w.value; h.dataset.previous = h.value; }
    });
    defs.addEventListener("input", event => {
      if(event.target.matches(".sr-def-id,.sr-def-label")){
        markSizeRulesDirty();
        renderSizeAssignments();
        return;
      }
      if(!event.target.matches(".sr-def-w,.sr-def-h")) return;
      const card = event.target.closest(".sr-profile-card");
      const view = event.target.dataset.view;
      const w = card?.querySelector(`.sr-def-w[data-view="${view}"]`);
      const h = card?.querySelector(`.sr-def-h[data-view="${view}"]`);
      if(card?.querySelector(".sr-def-ar")?.checked && w && h){
        const previousW = Number(w.dataset.previous || w.value);
        const previousH = Number(h.dataset.previous || h.value);
        const current = Number(event.target.value);
        if(event.target === w && current > 0 && previousW > 0 && previousH > 0){
          h.value = (current * previousH / previousW).toFixed(3);
        } else if(event.target === h && current > 0 && previousW > 0 && previousH > 0){
          w.value = (current * previousW / previousH).toFixed(3);
        }
      }
      const frontW = card?.querySelector('.sr-def-w[data-view="front"]')?.value;
      const frontH = card?.querySelector('.sr-def-h[data-view="front"]')?.value;
      const preview = card?.querySelector(".sr-profile-preview");
      if(preview) preview.setAttribute("style", profilePreview(frontW, frontH));
      markSizeRulesDirty();
    });
    defs.addEventListener("click", event => {
      const button = event.target.closest(".sr-def-delete");
      if(button){ button.closest(".sr-profile-card")?.remove(); markSizeRulesDirty(); renderSizeAssignments(); }
    });
  }
  if(assignments && !assignments.dataset.bound){
    assignments.dataset.bound = "1";
    assignments.addEventListener("change", event => {
      const select = event.target.closest(".sr-target-profile");
      if(!select) return;
      setTargetSizeRule(select.dataset.kind, select.dataset.id, select.value);
      renderSizeAssignments();
    });
    assignments.addEventListener("input", event => {
      const input = event.target.closest(".sr-target-dim");
      if(!input) return;
        setTargetDimension(input.dataset.kind, input.dataset.id, input.dataset.view, input.dataset.axis, input.value);
    });
    assignments.addEventListener("click", event => {
      const toggle = event.target.closest(".sr-dims-toggle");
      if(toggle){
        const key = `${toggle.dataset.kind}:${toggle.dataset.id}`;
        if(_sizeExpandedTargets.has(key)) _sizeExpandedTargets.delete(key); else _sizeExpandedTargets.add(key);
        renderSizeAssignments();
        return;
      }
      const clear = event.target.closest(".sr-clear-dims");
      if(clear){
        clearTargetDimensions(clear.dataset.kind, clear.dataset.id);
        renderSizeAssignments();
      }
    });
  }
  $("size-target-search")?.addEventListener("input", () => renderSizeAssignments());
  $("size-target-filter")?.addEventListener("change", () => renderSizeAssignments());
  $("btn-add-size-def")?.addEventListener("click", () => {
    const defs = srProfileDefs();
    let id = "new_profile", i = 2;
    while(defs[id]) id = `new_profile_${i++}`;
    const newDef = {
      label:"New profile", maintain_aspect_ratio:false,
      views:{front:{w:0.3,h:0.15},rear:{w:0.3,h:0.15},side:{w:0.2,h:0.1},top:{w:0.2,h:0.1}},
    };
    $("size-defs-tbody")?.querySelector(".sr-empty")?.remove();
    $("size-defs-tbody")?.insertAdjacentHTML("beforeend", sizeDefCard(id, newDef));
    renderSizeAssignments();
    markSizeRulesDirty();
  });
  $("btn-reload-sizes")?.addEventListener("click", async () => {
    await loadSizePartsDb();
    renderSizeDefs();
    toast("Size rules reloaded", "success");
  });
  $("btn-save-sizes")?.addEventListener("click", saveSizeRules);
}

function sizePartTypeEntries(){
  const partTypes = _sizePartsDb?.part_types || {};
  return Object.entries(partTypes).filter(([, pt]) => {
    const render = pt.render || {};
    return pt.type_id === "lights" || pt.category || render.size_per_view || render.images;
  });
}

function sizeProductEntries(){
  const eligible = new Set(sizePartTypeEntries().map(([id]) => id));
  return Object.entries(_sizePartsDb?.products || {}).filter(([, product]) =>
    (product.fits_part_types || []).some(id => eligible.has(id))
  );
}

function sizeTargetEntries(){
  const partTypes = Object.fromEntries(sizePartTypeEntries());
  const products = sizeProductEntries();
  const targets = [];
  for(const [id, pt] of Object.entries(partTypes)){
    targets.push({kind:"part_type", id, label:pt.label || id, sublabel:`${pt.type_id || "part"}${pt.category ? ` · ${pt.category}` : ""}`, data:pt});
  }
  for(const [id, product] of products){
    const fits = (product.fits_part_types || []).filter(ptId => partTypes[ptId]).map(ptId => partTypes[ptId].label || ptId);
    targets.push({kind:"product", id, label:product.model || id, sublabel:`${product.manufacturer_id || ""}${fits.length ? ` · ${fits.join(", ")}` : ""}`, data:product});
    for(const pn of product.part_numbers || []){
      targets.push({kind:"sku", id:pn.part_number, productId:id, label:pn.part_number, sublabel:`${product.model || id}${pn.friendly_name ? ` · ${pn.friendly_name}` : ""}`, data:pn, product});
    }
  }
  return targets;
}

function targetRender(target){
  if(target.kind === "part_type"){
    const bucket = _sizePartsDb.part_types || {};
    bucket[target.id] = bucket[target.id] || {};
    bucket[target.id].render = bucket[target.id].render || {};
    return bucket[target.id].render;
  }
  if(target.kind === "product"){
    const bucket = _sizePartsDb.products || {};
    bucket[target.id] = bucket[target.id] || {};
    bucket[target.id].render = bucket[target.id].render || {};
    return bucket[target.id].render;
  }
  return target.data;
}

function findSizeTarget(kind, id){
  return sizeTargetEntries().find(target => target.kind === kind && target.id === id);
}

function targetExplicitSizeRule(target){
  if(!target) return "";
  if(target.kind === "sku") return target.data.size_rule_id || "";
  return target.data.render?.size_rule_id || "";
}

function targetEffectiveProfile(target){
  const explicit = targetExplicitSizeRule(target);
  if(explicit) return {id:explicit, source:"Explicit assignment"};
  if(target.kind === "sku"){
    const product = findSizeTarget("product", target.productId);
    const productExplicit = targetExplicitSizeRule(product);
    if(productExplicit) return {id:productExplicit, source:`Product: ${product.label}`};
    const productTypes = (product?.data?.fits_part_types || []).map(id => findSizeTarget("part_type", id)).filter(Boolean);
    const typeExplicit = productTypes.map(targetExplicitSizeRule).find(Boolean);
    if(typeExplicit) return {id:typeExplicit, source:"Part type assignment"};
  }
  if(target.kind === "product"){
    const typeExplicit = (target.data.fits_part_types || []).map(id => findSizeTarget("part_type", id)).filter(Boolean).map(targetExplicitSizeRule).find(Boolean);
    if(typeExplicit) return {id:typeExplicit, source:"Part type assignment"};
  }
  return {id:"sm", source:"Default profile"};
}

function targetDimensions(target){
  if(!target || target.kind === "sku") return {};
  return target.data.render?.size_per_view || {};
}

function dimensionsEditor(target){
  if(target.kind === "sku") return "";
  const dims = targetDimensions(target);
  return `<div class="sr-dimensions-editor">
    <div class="sr-dimensions-head"><span>Exact dimensions (inches)</span><button class="btn btn-danger btn-sm sr-clear-dims" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}" type="button">Clear exact sizes</button></div>
    <div class="sr-dimension-grid">${SIZE_VIEWS.map(view => {
      const value = dims[view] || {};
      return `<label><span>${view}</span><input class="sr-target-dim" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}" data-view="${view}" data-axis="w" type="number" min="0.01" max="8" step="0.001" value="${srAttr(value.w)}" placeholder="W"></label><label><span class="sr-visually-hidden">${view} height</span><input class="sr-target-dim" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}" data-view="${view}" data-axis="h" type="number" min="0.01" max="6" step="0.001" value="${srAttr(value.h)}" placeholder="H"></label>`;
    }).join("")}</div>
    <div class="sr-field-note">These values override the profile for this target. Use this for artwork with a physical size that is not shared by the rest of its family.</div>
  </div>`;
}

function assignmentCard(target){
  const effective = targetEffectiveProfile(target);
  const explicit = targetExplicitSizeRule(target);
  const key = `${target.kind}:${target.id}`;
  const expanded = _sizeExpandedTargets.has(key);
  const hasDims = Object.keys(targetDimensions(target)).length > 0;
  const targetKindLabel = target.kind === "part_type" ? "PART TYPE" : target.kind === "product" ? "PRODUCT" : "SKU";
  return `<article class="sr-assignment-card" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}">
    <div class="sr-assignment-main">
      <div class="sr-target-icon">${target.kind === "part_type" ? "P" : target.kind === "product" ? "M" : "#"}</div>
      <div class="sr-target-copy"><div class="sr-target-title">${esc(target.label)}</div><div class="sr-target-subtitle">${esc(target.sublabel || target.id)}</div></div>
      <span class="sr-kind-badge">${targetKindLabel}</span>
      <div class="sr-target-choice"><label>Profile</label><select class="sr-target-profile" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}">${sizeProfileOptions(explicit)}</select><span class="sr-inherited">${effective.source}: <b>${esc(effective.id || "sm")}</b></span></div>
      ${target.kind !== "sku" ? `<button class="btn btn-secondary btn-sm sr-dims-toggle" data-kind="${srAttr(target.kind)}" data-id="${srAttr(target.id)}" type="button">${expanded ? "Hide sizes" : hasDims ? "Edit exact sizes" : "Add exact sizes"}</button>` : ""}
    </div>
    ${expanded ? dimensionsEditor(target) : ""}
  </article>`;
}

function renderSizeAssignments(){
  const list = $("size-assignments-list");
  if(!list || !_sizePartsDb) return;
  const search = ($("size-target-search")?.value || "").trim().toLowerCase();
  const filter = $("size-target-filter")?.value || "all";
  let targets = sizeTargetEntries().filter(target => {
    if(filter === "part_type" && target.kind !== "part_type") return false;
    if(filter === "product" && target.kind !== "product") return false;
    if(filter === "sku" && target.kind !== "sku") return false;
    // SKU rows are available through the SKU filter, but do not make the
    // default all-target view thousands of rows tall.
    if(filter === "all" && target.kind === "sku") return false;
    const text = `${target.label} ${target.sublabel} ${target.id}`.toLowerCase();
    return !search || text.includes(search);
  });
  targets.sort((a,b) => `${a.kind}:${a.label}`.localeCompare(`${b.kind}:${b.label}`));
  list.innerHTML = targets.length ? targets.map(assignmentCard).join("") : `<div class="sr-empty">No matching parts. Try the SKU filter or clear the search.</div>`;
}

function setTargetSizeRule(kind, id, value){
  const target = findSizeTarget(kind, id);
  if(!target) return;
  const render = targetRender(target);
  if(kind === "sku"){
    if(value) target.data.size_rule_id = value; else delete target.data.size_rule_id;
  } else if(value) render.size_rule_id = value; else delete render.size_rule_id;
  _sizePartsDbDirty = true;
  markSizeRulesDirty();
}

function setTargetDimension(kind, id, view, axis, rawValue){
  const target = findSizeTarget(kind, id);
  if(!target || kind === "sku") return;
  const value = Number(rawValue);
  const render = targetRender(target);
  render.size_per_view = render.size_per_view || {};
  render.size_per_view[view] = render.size_per_view[view] || {};
  if(Number.isFinite(value) && value > 0) render.size_per_view[view][axis] = value;
  else delete render.size_per_view[view][axis];
  if(!render.size_per_view[view].w && !render.size_per_view[view].h) delete render.size_per_view[view];
  _sizePartsDbDirty = true;
  markSizeRulesDirty();
}

function clearTargetDimensions(kind, id){
  const target = findSizeTarget(kind, id);
  if(!target || kind === "sku") return;
  delete targetRender(target).size_per_view;
  _sizePartsDbDirty = true;
  markSizeRulesDirty();
}

function collectSizeDefinitions(){
  const defs = {};
  const remap = {};
  const seen = new Set();
  for(const card of $("size-defs-tbody")?.querySelectorAll(".sr-profile-card") || []){
    const original = card.dataset.originalId || "";
    const id = card.querySelector(".sr-def-id")?.value.trim();
    if(!id) throw new Error("Every size profile needs an ID.");
    if(seen.has(id)) throw new Error(`Duplicate size profile ID: ${id}`);
    seen.add(id);
    if(original && original !== id) remap[original] = id;
    const views = {};
    for(const view of SIZE_VIEWS){
      const w = Number(card.querySelector(`.sr-def-w[data-view="${view}"]`)?.value);
      const h = Number(card.querySelector(`.sr-def-h[data-view="${view}"]`)?.value);
      if(Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0) views[view] = {w, h};
    }
    defs[id] = {label:card.querySelector(".sr-def-label")?.value.trim() || id, maintain_aspect_ratio:!!card.querySelector(".sr-def-ar")?.checked, views};
  }
  return {defs, remap};
}

function applySizeProfileRemap(remap){
  if(!Object.keys(remap).length) return;
  for(const target of sizeTargetEntries()){
    const current = targetExplicitSizeRule(target);
    if(!remap[current]) continue;
    if(target.kind === "sku") target.data.size_rule_id = remap[current];
    else targetRender(target).size_rule_id = remap[current];
  }
  _sizePartsDbDirty = true;
}

function referencedSizeProfiles(defs){
  const missing = new Set();
  const check = value => { if(value && !defs[value]) missing.add(value); };
  for(const target of sizeTargetEntries()) check(targetExplicitSizeRule(target));
  return [...missing];
}

async function saveSizeRules(){
  if(!_manifest) return;
  const button = $("btn-save-sizes");
  if(button) { button.disabled = true; button.textContent = "Saving…"; }
  try {
    const {defs, remap} = collectSizeDefinitions();
    applySizeProfileRemap(remap);
    const missing = referencedSizeProfiles(defs);
    if(missing.length) throw new Error(`These assignments refer to missing profiles: ${missing.join(", ")}`);
    _manifest.size_rule_definitions = defs;
    _manifest.part_number_size_rules = {};
    const manifestResult = await apiSave("/api/manifest/save", _manifest);
    if(!manifestResult?.ok) throw new Error(manifestResult?.error || "Manifest save failed");
    if(_sizePartsDbDirty && _sizePartsDb){
      _sizePartsDb.metadata = _sizePartsDb.metadata || {};
      _sizePartsDb.metadata.last_updated = new Date().toISOString();
      _sizePartsDb.metadata.updated_by = "size-rules-ui";
      const dbResult = await apiSave("/api/parts-db", _sizePartsDb);
      if(!dbResult?.ok) throw new Error(`Profiles saved, but parts database save failed: ${dbResult?.error || "unknown error"}`);
      _sizePartsDbDirty = false;
    }
    if($("sr-db-status")) $("sr-db-status").textContent = "All changes saved";
    renderSizeDefs();
    renderSizeAssignments();
    toast("Size rules saved", "success");
  } catch(error){
    toast("Save failed: " + (error.message || error), "error");
  } finally {
    if(button) { button.disabled = false; button.textContent = "Save Changes"; }
  }
}
