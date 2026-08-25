// ═══════════════════════════════════════════════════════
// PART MANAGER — visual editor for parts_db.json (schema v2)
//
// Lives under Settings → Advanced → Part Manager → Database (v2).
// MVP scope: read-only tree view + edit modals for part_types, products,
// manufacturers, and tags. Saves the FULL document via POST /api/parts-db.
// ═══════════════════════════════════════════════════════

let _pdb = null;              // full parts_db.json document
let _pdbSelected = null;      // {kind, id} of the currently-shown node
let _pdbModalDraft = null;    // editing scratchpad — committed only on Save

async function initPartsDbTab(){
  if(!_pdb) await _pdbLoad();
  _pdbRender();
}

async function _pdbLoad(){
  try{
    _pdb = await api("/api/parts-db");
  }catch(e){
    _pdb = null;
    toast("Failed to load parts_db.json: " + (e?.message||e), "error");
  }
}

function _pdbIsEmpty(){
  if(!_pdb) return true;
  const pt = _pdb.part_types || {};
  const pr = _pdb.products || {};
  return Object.keys(pt).length === 0 && Object.keys(pr).length === 0;
}

function _pdbRender(){
  const meta = $("pdb-meta");
  if(meta){
    if(_pdb?.metadata?.last_updated){
      meta.textContent = "Updated " + _pdb.metadata.last_updated +
        (_pdb.metadata.updated_by ? " · " + _pdb.metadata.updated_by : "");
    } else {
      meta.textContent = "";
    }
  }
  const empty = _pdbIsEmpty();
  $("pdb-empty-state").hidden = !empty;
  $("pdb-main").hidden = empty;
  if(empty) return;
  _pdbRenderTree($("pdb-search")?.value || "");
  if(_pdbSelected) _pdbRenderDetail(_pdbSelected.kind, _pdbSelected.id);
  else $("pdb-detail").innerHTML = `<div style="color:var(--muted);font-size:13px;padding:20px;text-align:center">Select a node from the tree to view details.</div>`;
}

// ─── Tree ──────────────────────────────────────────────────────────────────

function _pdbBuildTree(){
  // Walk part_types[*].tree_positions[] and bucket them into nested groups.
  // A part_type with multiple tree_positions appears in each.
  // Returns: { typeId: { typeLabel, sections: { sectionId: { sectionLabel,
  //   zones: { zoneId: { zoneLabel, subZones: { subId: { subLabel,
  //   partTypes: [partTypeId] } }, partTypes: [...] (no sub-zone) } },
  //   partTypes: [...] (no zone) } }, orphanPartTypes: [...] (no position) } }
  const types = _pdb.types || {};
  const sections = _pdb.sections || {};
  const zones = _pdb.zones || {};
  const subZones = _pdb.sub_zones || {};
  const partTypes = _pdb.part_types || {};
  const tree = {};
  const typeIds = Object.keys(types);
  // Add "uncategorized" bucket for part_types whose type_id is missing.
  const ensureType = (typeId) => {
    if(!tree[typeId]) tree[typeId] = {
      typeLabel: types[typeId]?.label || typeId || "(no type)",
      sections: {},
      orphanPartTypes: [],
    };
    return tree[typeId];
  };
  typeIds.forEach(ensureType);
  Object.entries(partTypes).forEach(([ptId, pt]) => {
    const tNode = ensureType(pt.type_id || "");
    const positions = pt.tree_positions || [];
    if(!positions.length){ tNode.orphanPartTypes.push(ptId); return; }
    positions.forEach(pos => {
      const secId = pos.section || "";
      const zoneId = pos.zone || "";
      const subId = pos.sub_zone || "";
      if(!tNode.sections[secId]){
        tNode.sections[secId] = {
          sectionLabel: sections[secId]?.label || secId || "(no section)",
          zones: {},
        };
      }
      const sNode = tNode.sections[secId];
      if(!sNode.zones[zoneId]){
        sNode.zones[zoneId] = {
          zoneLabel: zones[zoneId]?.label || zoneId || "(no zone)",
          subZones: {},
          partTypes: [],
        };
      }
      const zNode = sNode.zones[zoneId];
      if(subId){
        if(!zNode.subZones[subId]){
          zNode.subZones[subId] = {
            subLabel: subZones[subId]?.label || subId,
            partTypes: [],
          };
        }
        zNode.subZones[subId].partTypes.push(ptId);
      } else {
        zNode.partTypes.push(ptId);
      }
    });
  });
  return tree;
}

function _pdbMatchesFilter(label, filter){
  if(!filter) return true;
  return String(label||"").toLowerCase().includes(filter.toLowerCase());
}

function _pdbRenderTree(filter){
  const tree = _pdbBuildTree();
  const partTypes = _pdb.part_types || {};
  const products = _pdb.products || {};
  const lc = (filter||"").toLowerCase();
  const matches = (s) => !lc || String(s||"").toLowerCase().includes(lc);

  const rows = [];
  // Top-level: Types
  const typeOrder = Object.keys(tree).sort((a,b)=>tree[a].typeLabel.localeCompare(tree[b].typeLabel));
  typeOrder.forEach(typeId => {
    const tNode = tree[typeId];
    rows.push(`<div class="pdb-tree-group">
      <div class="pdb-tree-header" data-kind="type" data-id="${esc(typeId)}">📂 ${esc(tNode.typeLabel)}</div>`);
    const sectionOrder = Object.keys(tNode.sections).sort();
    sectionOrder.forEach(secId => {
      const sNode = tNode.sections[secId];
      rows.push(`<div class="pdb-tree-section">
        <div class="pdb-tree-sub-header">${esc(sNode.sectionLabel)}</div>`);
      const zoneOrder = Object.keys(sNode.zones).sort();
      zoneOrder.forEach(zoneId => {
        const zNode = sNode.zones[zoneId];
        rows.push(`<div class="pdb-tree-zone">
          <div class="pdb-tree-zone-header">${esc(zNode.zoneLabel)}</div>`);
        zNode.partTypes.forEach(ptId => {
          const pt = partTypes[ptId];
          if(!pt || !matches(pt.label) && !matches(ptId)) return;
          rows.push(_pdbPartTypeLeaf(ptId, pt));
        });
        Object.keys(zNode.subZones).sort().forEach(subId => {
          const subNode = zNode.subZones[subId];
          rows.push(`<div class="pdb-tree-sub">
            <div class="pdb-tree-sub-zone-header">↳ ${esc(subNode.subLabel)}</div>`);
          subNode.partTypes.forEach(ptId => {
            const pt = partTypes[ptId];
            if(!pt || !matches(pt.label) && !matches(ptId)) return;
            rows.push(_pdbPartTypeLeaf(ptId, pt));
          });
          rows.push(`</div>`);
        });
        rows.push(`</div>`);
      });
      rows.push(`</div>`);
    });
    if(tNode.orphanPartTypes.length){
      rows.push(`<div class="pdb-tree-section"><div class="pdb-tree-sub-header" style="color:var(--yellow)">⚠ Unplaced (no tree_position)</div>`);
      tNode.orphanPartTypes.forEach(ptId => {
        const pt = partTypes[ptId];
        if(!pt || !matches(pt.label) && !matches(ptId)) return;
        rows.push(_pdbPartTypeLeaf(ptId, pt));
      });
      rows.push(`</div>`);
    }
    rows.push(`</div>`);
  });

  // Catalog buckets — always show even when filter is empty so the owner
  // can reach Manufacturers / Tags / Products without first picking a tree node.
  const catalogRows = [];
  const productEntries = Object.entries(products).filter(([id,p]) =>
    !lc || matches(p.model) || matches(id) || matches(_pdb.manufacturers?.[p.manufacturer_id]?.label)
  ).sort((a,b)=>(a[1].model||a[0]).localeCompare(b[1].model||b[0]));
  if(productEntries.length){
    catalogRows.push(`<div class="pdb-tree-group">
      <div class="pdb-tree-header">🧾 Products (${productEntries.length})</div>`);
    productEntries.forEach(([id,p]) => {
      const mfg = _pdb.manufacturers?.[p.manufacturer_id]?.label || p.manufacturer_id || "?";
      catalogRows.push(`<div class="pdb-tree-leaf" data-kind="product" data-id="${esc(id)}">
        <span class="pdb-leaf-label">${esc(p.model || id)}</span>
        <span class="pdb-leaf-meta">${esc(mfg)}</span>
      </div>`);
    });
    catalogRows.push(`</div>`);
  }
  const mfgs = Object.entries(_pdb.manufacturers||{}).filter(([id,m])=>matches(m.label)||matches(id));
  if(mfgs.length){
    catalogRows.push(`<div class="pdb-tree-group">
      <div class="pdb-tree-header">🏭 Manufacturers (${mfgs.length})</div>`);
    mfgs.sort((a,b)=>(a[1].label||a[0]).localeCompare(b[1].label||b[0])).forEach(([id,m]) => {
      catalogRows.push(`<div class="pdb-tree-leaf" data-kind="manufacturer" data-id="${esc(id)}">
        <span class="pdb-leaf-label">${esc(m.label || id)}</span>
      </div>`);
    });
    catalogRows.push(`</div>`);
  }
  const tags = Object.entries(_pdb.tags||{}).filter(([id,t])=>matches(t.label)||matches(id));
  if(tags.length){
    catalogRows.push(`<div class="pdb-tree-group">
      <div class="pdb-tree-header">🏷 Tags (${tags.length})</div>`);
    tags.sort((a,b)=>(a[1].label||a[0]).localeCompare(b[1].label||b[0])).forEach(([id,t]) => {
      catalogRows.push(`<div class="pdb-tree-leaf" data-kind="tag" data-id="${esc(id)}">
        <span class="pdb-leaf-label">${esc(t.label || id)}</span>
      </div>`);
    });
    catalogRows.push(`</div>`);
  }

  $("pdb-tree").innerHTML = rows.join("") + catalogRows.join("");

  // Wire clicks. Single delegated listener on the tree root would also
  // work; per-element is fine here because the tree re-renders on every
  // change and we don't have to track listener cleanup.
  $("pdb-tree").querySelectorAll(".pdb-tree-leaf").forEach(el => {
    el.addEventListener("click", () => {
      _pdbSelected = { kind: el.dataset.kind, id: el.dataset.id };
      $("pdb-tree").querySelectorAll(".pdb-tree-leaf.active").forEach(n => n.classList.remove("active"));
      el.classList.add("active");
      _pdbRenderDetail(_pdbSelected.kind, _pdbSelected.id);
    });
  });
}

function _pdbPartTypeLeaf(ptId, pt){
  return `<div class="pdb-tree-leaf" data-kind="part_type" data-id="${esc(ptId)}">
    <span class="pdb-leaf-label">${esc(pt.label || ptId)}</span>
    ${pt.max_count ? `<span class="pdb-leaf-meta">max ${pt.max_count}</span>` : ""}
  </div>`;
}

// ─── Detail pane ───────────────────────────────────────────────────────────

function _pdbRenderDetail(kind, id){
  if(kind === "part_type")    return _pdbRenderPartTypeDetail(id);
  if(kind === "product")      return _pdbRenderProductDetail(id);
  if(kind === "manufacturer") return _pdbRenderManufacturerDetail(id);
  if(kind === "tag")          return _pdbRenderTagDetail(id);
  $("pdb-detail").innerHTML = `<div style="color:var(--muted);font-size:13px;padding:20px">Detail view not implemented for ${esc(kind)}.</div>`;
}

function _pdbDetailHeader(title, kind, id){
  return `<div class="pdb-detail-header">
    <div>
      <div class="pdb-detail-title">${esc(title)}</div>
      <div class="pdb-detail-id">${esc(id)}</div>
    </div>
    <button class="btn btn-primary btn-sm" onclick="_pdbOpenModal('${esc(kind)}','${esc(id)}')">✏️ Edit</button>
  </div>`;
}

function _pdbField(label, value){
  const v = value==null||value===""?'<span style="color:var(--muted)">—</span>':esc(value);
  return `<div class="pdb-field"><div class="pdb-field-label">${esc(label)}</div><div class="pdb-field-value">${v}</div></div>`;
}

function _pdbChips(labels){
  if(!labels?.length) return '<span style="color:var(--muted)">—</span>';
  return labels.map(l => `<span class="chip">${esc(l)}</span>`).join(" ");
}

function _pdbRenderPartTypeDetail(id){
  const pt = _pdb.part_types?.[id];
  if(!pt){ $("pdb-detail").innerHTML = `<div style="padding:20px;color:var(--red)">Part type "${esc(id)}" not found.</div>`; return; }
  const tags = _pdb.tags || {}, types = _pdb.types || {};
  const products = _pdb.products || {};
  const compatProducts = Object.entries(products)
    .filter(([pid,p]) => {
      const ptWl = pt.allowed_products || [];
      const fits = p.fits_part_types || [];
      const ptOk = ptWl.length === 0 || ptWl.includes(pid);
      const productOk = fits.length === 0 || fits.includes(id);
      return ptOk && productOk;
    });
  const treePos = (pt.tree_positions || []).map(p => {
    const parts = [p.section, p.zone, p.sub_zone].filter(Boolean);
    return parts.join(" › ");
  });
  $("pdb-detail").innerHTML = `
    ${_pdbDetailHeader(pt.label || id, "part_type", id)}
    <div class="pdb-detail-grid">
      ${_pdbField("Label", pt.label)}
      ${_pdbField("Type", types[pt.type_id]?.label || pt.type_id)}
      ${_pdbField("Max count", pt.max_count)}
      ${_pdbField("Accessory of", pt.accessory_of)}
      ${_pdbField("Workbook label", pt.workbook_label_pattern)}
      ${_pdbField("Sequence scope", pt.sequence_scope)}
    </div>
    <div class="pdb-section-title">Location</div>
    <div>${(pt.location_mode || "text") === "placement"
      ? '<span class="chip">Placement — drawn on the build preview</span>'
      : '<span class="chip">Text — pick-list</span> ' + ((pt.location_options||[]).length
          ? _pdbChips(pt.location_options)
          : '<span style="color:var(--muted)">no options yet</span>')}</div>
    <div class="pdb-section-title">Tree positions</div>
    <div>${treePos.length ? treePos.map(t=>`<span class="chip">${esc(t)}</span>`).join(" ") : '<span style="color:var(--muted)">none</span>'}</div>
    <div class="pdb-section-title">Tags</div>
    <div>${_pdbChips((pt.tag_ids||[]).map(t=>tags[t]?.label||t))}</div>
    <div class="pdb-section-title">Allowed products whitelist</div>
    <div>${(pt.allowed_products||[]).length ? _pdbChips(pt.allowed_products) : '<span style="color:var(--muted)">unrestricted</span>'}</div>
    <div class="pdb-section-title">Allowed placements whitelist</div>
    <div>${(pt.allowed_placements||[]).length ? _pdbChips(pt.allowed_placements) : '<span style="color:var(--muted)">unrestricted</span>'}</div>
    <div class="pdb-section-title">Accessories</div>
    <div>${_pdbChips(pt.accessories||[])}</div>
    <div class="pdb-section-title">Compatible products (${compatProducts.length})</div>
    <div class="pdb-compat-list">
      ${compatProducts.length ? compatProducts.map(([pid,p]) => {
        const mfg = _pdb.manufacturers?.[p.manufacturer_id]?.label || p.manufacturer_id || "";
        return `<div class="pdb-compat-row"><strong>${esc(mfg)}</strong> · ${esc(p.model||pid)}</div>`;
      }).join("") : '<span style="color:var(--muted)">none match the compatibility rule</span>'}
    </div>
  `;
}

function _pdbRenderProductDetail(id){
  const p = _pdb.products?.[id];
  if(!p){ $("pdb-detail").innerHTML = `<div style="padding:20px;color:var(--red)">Product "${esc(id)}" not found.</div>`; return; }
  const mfg = _pdb.manufacturers?.[p.manufacturer_id];
  const partTypes = _pdb.part_types || {};
  const tags = _pdb.tags || {};
  const pns = p.part_numbers || [];
  $("pdb-detail").innerHTML = `
    ${_pdbDetailHeader(p.model || id, "product", id)}
    <div class="pdb-detail-grid">
      ${_pdbField("Model", p.model)}
      ${_pdbField("Manufacturer", mfg?.label || p.manufacturer_id)}
      ${_pdbField("Description", p.description)}
    </div>
    <div class="pdb-section-title">Fits part types</div>
    <div>${(p.fits_part_types||[]).length ? _pdbChips((p.fits_part_types||[]).map(t=>partTypes[t]?.label||t)) : '<span style="color:var(--muted)">unrestricted</span>'}</div>
    <div class="pdb-section-title">Tags</div>
    <div>${_pdbChips((p.tag_ids||[]).map(t=>tags[t]?.label||t))}</div>
    <div class="pdb-section-title">Part numbers (${pns.length})</div>
    <div class="pdb-compat-list">
      ${pns.length ? pns.map(pn => {
        const parts = [`<strong>${esc(pn.part_number)}</strong>`];
        if(pn.color) {
          let colorStr = pn.color;
          if(pn.secondary_color) colorStr += `/${pn.secondary_color}`;
          parts.push(`<span style="color:var(--muted)">${colorStr}</span>`);
        }
        if(pn.lens_type) parts.push(`<span class="chip">${esc(pn.lens_type)}</span>`);
        const price = pn.qb_unit_price || pn.price_usd;
        if(price) parts.push(`<span style="color:var(--accent);font-weight:500">QBO list $${esc(price)}</span>`);
        if(pn.qb_item_id) parts.push('<span class="chip" style="background:var(--green);color:#fff">QB</span>');
        if(pn.vehicle_tags?.length && !(pn.vehicle_tags.length===1&&pn.vehicle_tags[0]==="any")) {
          parts.push(`<span class="chip">${esc(pn.vehicle_tags.join(", "))}</span>`);
        }
        return `<div class="pdb-compat-row">${parts.join(" · ")}</div>`;
      }).join("") : '<span style="color:var(--muted)">none</span>'}
    </div>
  `;
}

function _pdbRenderManufacturerDetail(id){
  const m = _pdb.manufacturers?.[id];
  if(!m){ $("pdb-detail").innerHTML = `<div style="padding:20px;color:var(--red)">Manufacturer "${esc(id)}" not found.</div>`; return; }
  const products = Object.entries(_pdb.products||{}).filter(([_,p]) => p.manufacturer_id === id);
  $("pdb-detail").innerHTML = `
    ${_pdbDetailHeader(m.label || id, "manufacturer", id)}
    <div class="pdb-detail-grid">
      ${_pdbField("Label", m.label)}
      ${_pdbField("Website", m.website)}
    </div>
    <div class="pdb-section-title">Products (${products.length})</div>
    <div class="pdb-compat-list">
      ${products.length ? products.map(([pid,p]) => `<div class="pdb-compat-row">${esc(p.model||pid)}</div>`).join("") : '<span style="color:var(--muted)">none</span>'}
    </div>
  `;
}

function _pdbRenderTagDetail(id){
  const t = _pdb.tags?.[id];
  if(!t){ $("pdb-detail").innerHTML = `<div style="padding:20px;color:var(--red)">Tag "${esc(id)}" not found.</div>`; return; }
  const partTypes = Object.entries(_pdb.part_types||{}).filter(([_,pt]) => (pt.tag_ids||[]).includes(id));
  const products = Object.entries(_pdb.products||{}).filter(([_,p]) => (p.tag_ids||[]).includes(id));
  $("pdb-detail").innerHTML = `
    ${_pdbDetailHeader(t.label || id, "tag", id)}
    <div class="pdb-detail-grid">${_pdbField("Label", t.label)}</div>
    <div class="pdb-section-title">Part types with this tag (${partTypes.length})</div>
    <div>${partTypes.length ? _pdbChips(partTypes.map(([_,pt])=>pt.label||"")) : '<span style="color:var(--muted)">none</span>'}</div>
    <div class="pdb-section-title">Products with this tag (${products.length})</div>
    <div>${products.length ? _pdbChips(products.map(([_,p])=>p.model||"")) : '<span style="color:var(--muted)">none</span>'}</div>
  `;
}

// ─── Edit modals ───────────────────────────────────────────────────────────

function _pdbOpenModal(kind, id){
  // Deep clone so we can cancel without mutating the live doc.
  const live = _pdbEntityFor(kind, id);
  if(!live){ toast("Entity not found", "error"); return; }
  _pdbModalDraft = { kind, id, data: JSON.parse(JSON.stringify(live)) };
  $("pdb-modal-title").textContent = `Edit ${kind.replace("_"," ")} · ${id}`;
  $("pdb-modal-body").innerHTML = _pdbModalBody(kind, _pdbModalDraft.data);
  _pdbWireModalBody(kind);
  $("pdb-modal").classList.add("open");
}

function _pdbEntityFor(kind, id){
  if(kind === "part_type")    return _pdb.part_types?.[id];
  if(kind === "product")      return _pdb.products?.[id];
  if(kind === "manufacturer") return _pdb.manufacturers?.[id];
  if(kind === "tag")          return _pdb.tags?.[id];
  return null;
}

function _pdbModalBody(kind, d){
  if(kind === "part_type")    return _pdbPartTypeForm(d);
  if(kind === "product")      return _pdbProductForm(d);
  if(kind === "manufacturer") return _pdbManufacturerForm(d);
  if(kind === "tag")          return _pdbTagForm(d);
  return "";
}

function _pdbOptionList(map, selected){
  const opts = Object.entries(map||{}).sort((a,b)=>(a[1].label||a[0]).localeCompare(b[1].label||b[0]));
  return `<option value="">— none —</option>` + opts.map(([id,v]) =>
    `<option value="${esc(id)}" ${id===selected?"selected":""}>${esc(v.label||id)}</option>`
  ).join("");
}

function _pdbCheckboxList(name, map, selected){
  // Returns checkbox chips for multi-select fields.
  const sel = new Set(selected || []);
  return Object.entries(map||{}).sort((a,b)=>(a[1].label||a[0]).localeCompare(b[1].label||b[0])).map(([id,v]) => {
    const checked = sel.has(id);
    return `<label class="compat-chip ${checked?"checked":""}">
      <input type="checkbox" name="${esc(name)}" value="${esc(id)}" ${checked?"checked":""}> ${esc(v.label||id)}
    </label>`;
  }).join("");
}

function _pdbPartTypeForm(pt){
  const sections = _pdb.sections || {}, zones = _pdb.zones || {}, subZones = _pdb.sub_zones || {};
  const treePositionsHtml = (pt.tree_positions || []).map((pos, i) => _pdbTreePosRow(pos, i)).join("");
  return `
    <div class="form-row">
      <div class="form-group"><label>Label</label><input type="text" id="pdbf-label" value="${esc(pt.label||"")}" /></div>
      <div class="form-group" style="max-width:200px"><label>Type</label>
        <select id="pdbf-type">${_pdbOptionList(_pdb.types, pt.type_id)}</select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="max-width:120px"><label>Max count</label><input type="number" id="pdbf-max" value="${pt.max_count ?? ""}" min="0" /></div>
      <div class="form-group" style="max-width:200px"><label>Accessory of</label>
        <select id="pdbf-accessory-of">${_pdbOptionList(_pdb.part_types, pt.accessory_of)}</select>
      </div>
      <div class="form-group"><label>Sequence scope</label><input type="text" id="pdbf-seq" value="${esc(pt.sequence_scope||"")}" /></div>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label>Workbook label pattern</label>
      <input type="text" id="pdbf-wbpat" value="${esc(pt.workbook_label_pattern||"")}" placeholder="e.g. Forward Warning {n}" />
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Location</div>
      <div class="form-group" style="max-width:340px">
        <label>Location mode</label>
        <select id="pdbf-locmode">
          <option value="placement"${(pt.location_mode||"")==="placement"?" selected":""}>Placement — visual, drawn on the build preview</option>
          <option value="text"${(pt.location_mode||"")!=="placement"?" selected":""}>Text — pick-list printed on the sheet</option>
        </select>
      </div>
      <div id="pdbf-locopts-wrap">
        <label>Location options <span style="font-weight:400;color:var(--muted)">(text mode — the mount options a builder can pick)</span></label>
        <div id="pdbf-locopts">${(pt.location_options||[]).map(_pdbLocOptRow).join("")}</div>
        <button type="button" class="btn btn-secondary btn-sm" id="pdbf-add-locopt">+ Add location</button>
      </div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Tree positions</div>
      <div id="pdbf-tree-positions">${treePositionsHtml}</div>
      <button type="button" class="btn btn-secondary btn-sm" id="pdbf-add-pos">+ Add position</button>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Tags</div>
      <div class="compat-chips" id="pdbf-tags">${_pdbCheckboxList("tag", _pdb.tags, pt.tag_ids)}</div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Allowed products whitelist <span style="font-weight:400;color:var(--muted)">(none = unrestricted)</span></div>
      <div class="compat-chips" id="pdbf-allowed-products">${_pdbCheckboxList("ap", _pdb.products, pt.allowed_products)}</div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Allowed placements whitelist <span style="font-weight:400;color:var(--muted)">(none = unrestricted)</span></div>
      <div class="compat-chips" id="pdbf-allowed-placements">${_pdbCheckboxList("apl", _pdb.placements, pt.allowed_placements)}</div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Suggested accessories</div>
      <div class="compat-chips" id="pdbf-accessories">${_pdbCheckboxList("acc", _pdb.part_types, pt.accessories)}</div>
    </div>
  `;
}

function _pdbLocOptRow(val){
  return `<div class="pdb-locopt-row" style="display:flex;gap:6px;margin-bottom:5px">
    <input type="text" data-locopt value="${esc(val||"")}" placeholder="e.g. IN CENTER CONSOLE" style="flex:1" />
    <button type="button" class="btn btn-danger btn-sm pdbf-locopt-del">✕</button>
  </div>`;
}

function _pdbTreePosRow(pos, idx){
  return `<div class="pdb-tree-pos-row" data-idx="${idx}">
    <select data-pos-field="section" class="pdbf-sec">${_pdbOptionList(_pdb.sections, pos.section||"")}</select>
    <select data-pos-field="zone" class="pdbf-zone">${_pdbOptionList(_pdb.zones, pos.zone||"")}</select>
    <select data-pos-field="sub_zone" class="pdbf-sub">${_pdbOptionList(_pdb.sub_zones, pos.sub_zone||"")}</select>
    <button type="button" class="btn btn-danger btn-sm pdbf-pos-del">✕</button>
  </div>`;
}

function _pdbProductForm(p){
  return `
    <div class="form-row">
      <div class="form-group"><label>Model</label><input type="text" id="pdbf-model" value="${esc(p.model||"")}" /></div>
      <div class="form-group" style="max-width:240px"><label>Manufacturer</label>
        <select id="pdbf-mfg">${_pdbOptionList(_pdb.manufacturers, p.manufacturer_id)}</select>
      </div>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label>Description</label>
      <textarea id="pdbf-desc">${esc(p.description||"")}</textarea>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Fits part types <span style="font-weight:400;color:var(--muted)">(none = unrestricted)</span></div>
      <div class="compat-chips" id="pdbf-fits">${_pdbCheckboxList("fpt", _pdb.part_types, p.fits_part_types)}</div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Tags</div>
      <div class="compat-chips" id="pdbf-tags">${_pdbCheckboxList("tag", _pdb.tags, p.tag_ids)}</div>
    </div>
    <div class="modal-section">
      <div class="modal-section-title">Part numbers</div>
      <div id="pdbf-part-numbers">${(p.part_numbers||[]).map((pn,i)=>_pdbPartNumberRow(pn,i)).join("")}</div>
      <button type="button" class="btn btn-secondary btn-sm" id="pdbf-add-pn">+ Add part number</button>
    </div>
  `;
}

function _pdbPartNumberRow(pn, idx){
  pn = pn || {};
  const linked = !!pn.qb_item_id;
  // Stash the full original SKU so save preserves fields the form doesn't expose
  // (qb_item_id, color, vehicle_tags, lens, …). encodeURIComponent keeps it
  // attribute-safe (friendly names contain quotes/apostrophes).
  const preserve = encodeURIComponent(JSON.stringify(pn));
  return `<div class="pdb-pn-row" data-idx="${idx}" data-pn-preserve="${preserve}">
    <input type="text" data-pn-field="part_number" placeholder="Part #" value="${esc(pn.part_number||"")}" />
    <input type="text" data-pn-field="friendly_name" placeholder="Friendly name" value="${esc(pn.friendly_name||"")}" />
    <input type="number" data-pn-field="price_usd" placeholder="QBO list price" step="0.01"
      value="${(pn.qb_unit_price ?? pn.price_usd) ?? ""}" style="max-width:90px"
      ${linked?'readonly title="QBO list price synced from QuickBooks (qb_unit_price)"':''} />
    <label class="pdb-pn-pending" title="Pre-added before it exists in QuickBooks — usable now, flagged on the estimate until the QB item is created">
      <input type="checkbox" data-pn-field="qb_pending" ${pn.qb_pending?"checked":""} ${linked?"disabled":""} /> Pending QB
    </label>
    ${linked?'<span class="chip" style="background:var(--green);color:#fff">QB</span>':""}
    <button type="button" class="btn btn-danger btn-sm pdbf-pn-del">✕</button>
  </div>`;
}

function _pdbManufacturerForm(m){
  return `
    <div class="form-group" style="margin-bottom:12px"><label>Label</label><input type="text" id="pdbf-label" value="${esc(m.label||"")}" /></div>
    <div class="form-group" style="margin-bottom:12px"><label>Website</label><input type="text" id="pdbf-website" value="${esc(m.website||"")}" placeholder="https://…" /></div>
  `;
}

function _pdbTagForm(t){
  return `<div class="form-group" style="margin-bottom:12px"><label>Label</label><input type="text" id="pdbf-label" value="${esc(t.label||"")}" /></div>`;
}

function _pdbWireModalBody(kind){
  // Chip checkbox toggle behavior (mirrors the parts library pattern).
  $("pdb-modal-body").querySelectorAll(".compat-chip").forEach(label => {
    label.addEventListener("click", e => {
      if(e.target.tagName === "INPUT") return;
      const cb = label.querySelector("input");
      cb.checked = !cb.checked;
      label.classList.toggle("checked", cb.checked);
    });
    label.querySelector("input").addEventListener("change", e => {
      label.classList.toggle("checked", e.target.checked);
    });
  });

  if(kind === "part_type"){
    $("pdbf-add-pos")?.addEventListener("click", () => {
      const container = $("pdbf-tree-positions");
      const idx = container.querySelectorAll(".pdb-tree-pos-row").length;
      container.insertAdjacentHTML("beforeend", _pdbTreePosRow({}, idx));
      _pdbWirePosRow(container.lastElementChild);
    });
    $("pdbf-tree-positions").querySelectorAll(".pdb-tree-pos-row").forEach(_pdbWirePosRow);

    // Location options: show only in text mode; add/remove rows.
    const locWrap = $("pdbf-locopts-wrap"), locMode = $("pdbf-locmode");
    const syncLocMode = () => { if(locWrap) locWrap.style.display = locMode.value === "text" ? "" : "none"; };
    locMode?.addEventListener("change", syncLocMode);
    syncLocMode();
    $("pdbf-add-locopt")?.addEventListener("click", () => {
      const c = $("pdbf-locopts");
      c.insertAdjacentHTML("beforeend", _pdbLocOptRow(""));
      _pdbWireLocOptRow(c.lastElementChild);
    });
    $("pdbf-locopts").querySelectorAll(".pdb-locopt-row").forEach(_pdbWireLocOptRow);
  }

  if(kind === "product"){
    $("pdbf-add-pn")?.addEventListener("click", () => {
      const container = $("pdbf-part-numbers");
      const idx = container.querySelectorAll(".pdb-pn-row").length;
      container.insertAdjacentHTML("beforeend", _pdbPartNumberRow({}, idx));
      _pdbWirePnRow(container.lastElementChild);
    });
    $("pdbf-part-numbers").querySelectorAll(".pdb-pn-row").forEach(_pdbWirePnRow);
  }
}

function _pdbWirePosRow(row){
  row.querySelector(".pdbf-pos-del").addEventListener("click", () => row.remove());
}

function _pdbWireLocOptRow(row){
  row.querySelector(".pdbf-locopt-del").addEventListener("click", () => row.remove());
}

function _pdbWirePnRow(row){
  row.querySelector(".pdbf-pn-del").addEventListener("click", () => row.remove());
}

// ─── Save flow ─────────────────────────────────────────────────────────────

function _pdbCollectChecked(containerId, name){
  return [...$(containerId).querySelectorAll(`input[name="${name}"]:checked`)].map(cb => cb.value);
}

function _pdbCollectFormData(kind){
  if(kind === "part_type"){
    const positions = [...$("pdbf-tree-positions").querySelectorAll(".pdb-tree-pos-row")].map(row => {
      const section = row.querySelector('[data-pos-field="section"]').value;
      const zone = row.querySelector('[data-pos-field="zone"]').value;
      const sub_zone = row.querySelector('[data-pos-field="sub_zone"]').value;
      // Validator (_validate_parts_db) requires both 'section' and 'zone'
      // keys to be present on every tree_position; empty string is fine,
      // missing key is not. Drop rows that are entirely blank, but
      // otherwise always include both keys.
      if(!section && !zone && !sub_zone) return null;
      const out = { section, zone };
      if(sub_zone) out.sub_zone = sub_zone;
      return out;
    }).filter(p => p !== null);
    const max = $("pdbf-max").value.trim();
    return {
      label: $("pdbf-label").value.trim(),
      type_id: $("pdbf-type").value || "",
      tree_positions: positions,
      tag_ids: _pdbCollectChecked("pdbf-tags", "tag"),
      max_count: max === "" ? null : Number(max),
      accessory_of: $("pdbf-accessory-of").value || "",
      accessories: _pdbCollectChecked("pdbf-accessories", "acc"),
      allowed_products: _pdbCollectChecked("pdbf-allowed-products", "ap"),
      allowed_placements: _pdbCollectChecked("pdbf-allowed-placements", "apl"),
      workbook_label_pattern: $("pdbf-wbpat").value.trim(),
      sequence_scope: $("pdbf-seq").value.trim() || "global",
      location_mode: $("pdbf-locmode").value || "text",
      location_options: $("pdbf-locmode").value === "text"
        ? [...$("pdbf-locopts").querySelectorAll("[data-locopt]")].map(i => i.value.trim()).filter(Boolean)
        : [],
    };
  }
  if(kind === "product"){
    const pns = [...$("pdbf-part-numbers").querySelectorAll(".pdb-pn-row")].map(row => {
      let orig = {};
      try { orig = JSON.parse(decodeURIComponent(row.dataset.pnPreserve || "")) || {}; } catch {}
      const pn = row.querySelector('[data-pn-field="part_number"]').value.trim();
      const fn = row.querySelector('[data-pn-field="friendly_name"]').value.trim();
      const price = row.querySelector('[data-pn-field="price_usd"]').value.trim();
      const pending = row.querySelector('[data-pn-field="qb_pending"]').checked;
      // Preserve all original fields; override only what the form edits.
      const linked = !!orig.qb_item_id;
      const out = { ...orig, part_number: pn };
      if(fn) out.friendly_name = fn; else delete out.friendly_name;
      // Price is hand-set only for non-QB parts; QB-linked prices are owned by
      // qb_unit_price (synced) and the field is read-only, so leave it untouched.
      if(!linked){
        if(price !== "") out.price_usd = Number(price); else delete out.price_usd;
      }
      if(pending) out.qb_pending = true; else delete out.qb_pending;
      return out;
    }).filter(pn => pn.part_number);
    return {
      manufacturer_id: $("pdbf-mfg").value || "",
      model: $("pdbf-model").value.trim(),
      description: $("pdbf-desc").value.trim(),
      fits_part_types: _pdbCollectChecked("pdbf-fits", "fpt"),
      tag_ids: _pdbCollectChecked("pdbf-tags", "tag"),
      part_numbers: pns,
    };
  }
  if(kind === "manufacturer"){
    return {
      label: $("pdbf-label").value.trim(),
      website: $("pdbf-website").value.trim(),
    };
  }
  if(kind === "tag"){
    return { label: $("pdbf-label").value.trim() };
  }
  return {};
}

async function _pdbSaveModal(){
  if(!_pdbModalDraft) return;
  const btn = $("pdb-modal-save");
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = "Saving…";
  try {
    const { kind, id } = _pdbModalDraft;
    const formData = _pdbCollectFormData(kind);
    const bucket = _pdbBucketFor(kind);
    if(!_pdb[bucket]) _pdb[bucket] = {};
    // Merge: preserve fields we don't expose in the form (images, etc.).
    _pdb[bucket][id] = { ..._pdb[bucket][id], ...formData };
    _pdb.metadata = _pdb.metadata || {};
    _pdb.metadata.last_updated = new Date().toISOString();
    _pdb.metadata.updated_by = "part-manager-ui";

    const res = await apiSave("/api/parts-db", _pdb);
    if(!res?.ok) throw new Error(res?.error || "Save failed");
    toast("Saved", "success");
    $("pdb-modal").classList.remove("open");
    // Reload from server so we render whatever the validator normalized.
    await _pdbLoad();
    _pdbRender();
  } catch(err){
    toast("Save failed: " + (err.message || err), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

function _pdbBucketFor(kind){
  return ({
    part_type:    "part_types",
    product:      "products",
    manufacturer: "manufacturers",
    tag:          "tags",
  })[kind];
}

// ─── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  $("btn-pdb-reload")?.addEventListener("click", async () => {
    await _pdbLoad();
    _pdbRender();
    toast("Reloaded", "success");
  });
  $("pdb-search")?.addEventListener("input", e => _pdbRenderTree(e.target.value));
  $("pdb-modal-close")?.addEventListener("click", () => $("pdb-modal").classList.remove("open"));
  $("pdb-modal-cancel")?.addEventListener("click", () => $("pdb-modal").classList.remove("open"));
  $("pdb-modal")?.addEventListener("click", e => {
    if(e.target.id === "pdb-modal") $("pdb-modal").classList.remove("open");
  });
  $("pdb-modal-save")?.addEventListener("click", _pdbSaveModal);
});
