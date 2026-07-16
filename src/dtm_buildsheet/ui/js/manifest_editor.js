// ═══════════════════════════════════════════════════════
// BUILD MANIFEST EDITOR
// ═══════════════════════════════════════════════════════

let _meDraftId    = null;
let _meDraft      = null;
let _meEditLineId = null;   // null = add mode

// ── public API ───────────────────────────────────────────

async function loadDraftManifest(draftId) {
  _meDraftId = draftId;
  if (!draftId) { meHide(); return; }
  const res = await api("/api/draft/" + encodeURIComponent(draftId));
  if (!res.ok) return;
  _meDraft = res.draft;
  await _meBuildGroupMap();
  _meRender();
  show("card-manifest");
}

function meHide() {
  _meDraftId = null;
  _meDraft   = null;
  hide("card-manifest");
}

// ── rendering ────────────────────────────────────────────

// ── parts_db-shaped grouping (FINDING-007 / FINDING-030) ──────────────────
//
// Sections are derived from GET /api/parts-db/browse-tree — the same
// category → family → part_type taxonomy that drives the picker's sidebar
// (part_picker.js's .pbt-* accordion) — instead of the workbook's
// `template_sections`. A part groups into its family (if its part_type is a
// family member) or into its own bare part_type otherwise, mirroring the
// sidebar exactly. `order` walks the tree in the order the server returns it
// so the manifest auto-follows any future sidebar/category restructure with
// no code changes here.
//
// Built once and cached on the module (loadDraftManifest awaits it before
// the first render) rather than lazily on first legacy-modal open, which was
// the init-order half of FINDING-007 (a fresh manifest used to dump every
// part into "Other" until the fallback modal had been opened once).

let _meGroupMap        = null;  // part_type_id -> {type_id, type_label, section_key, section_label, order}
let _meSectionMeta     = null;  // section_key  -> {label, type_id, type_label, order, kind, ref_id}
let _meLegacyLabelIndex = null; // lowercased family/part_type label -> section_key (null = ambiguous)

async function _meBuildGroupMap() {
  if (_meGroupMap) return;   // cache once per module lifetime
  _meGroupMap = new Map();
  _meSectionMeta = new Map();
  _meLegacyLabelIndex = new Map();

  try {
    const res = await api("/api/parts-db/manifest-groups");
    if (res?.groups?.length && res?.part_type_map) {
      for (const group of res.groups) {
        for (const subgroup of (group.subgroups || [])) {
          _meSectionMeta.set(subgroup.section_key, {
            label: subgroup.label,
            type_id: group.group_id,
            type_label: group.label,
            order: (group.order || 999) * 1000 + (subgroup.order || 999),
            kind: "manifest_subgroup",
            ref_id: subgroup.subgroup_id,
            part_type_ids: subgroup.part_types || [],
          });
        }
      }
      for (const [ptid, info] of Object.entries(res.part_type_map || {})) {
        _meGroupMap.set(ptid, {
          type_id: info.group_id,
          type_label: info.group_label,
          section_key: info.section_key,
          section_label: info.section_label,
          order: (info.group_order || 999) * 1000 + (info.section_order || 999),
        });
      }
      for (const [label, key] of Object.entries(res.legacy_label_map || {})) {
        if (label && key) _meLegacyLabelIndex.set(label, key);
      }
      return;
    }
  } catch (e) {
    console.error("Manifest: manifest-groups failed, falling back to browse-tree grouping:", e);
  }

  let categories = [];
  try {
    const res = await api("/api/parts-db/browse-tree");
    categories = res?.categories || [];
  } catch (e) {
    console.error("Manifest: browse-tree failed, all parts will group under Other:", e);
  }

  const indexLabel = (label, key) => {
    const lower = (label || "").trim().toLowerCase();
    if (!lower) return;
    if (_meLegacyLabelIndex.has(lower) && _meLegacyLabelIndex.get(lower) !== key) {
      _meLegacyLabelIndex.set(lower, null);       // ambiguous — more than one section shares this label
    } else if (!_meLegacyLabelIndex.has(lower)) {
      _meLegacyLabelIndex.set(lower, key);
    }
  };

  let order = 0;
  for (const cat of categories) {
    const typeLabel = cat.label || cat.type_id || "";
    for (const child of (cat.children || [])) {
      if (child.kind === "family") {
        const key = "fam:" + child.family_id;
        _meSectionMeta.set(key, {
          label: child.label, type_id: cat.type_id, type_label: typeLabel,
          order: order++, kind: "family", ref_id: child.family_id,
        });
        indexLabel(child.label, key);
        for (const m of (child.members || [])) {
          _meGroupMap.set(m.part_type_id, {
            type_id: cat.type_id, type_label: typeLabel,
            section_key: key, section_label: child.label,
            order: _meSectionMeta.get(key).order,
          });
        }
      } else if (child.kind === "part_type") {
        const key = "pt:" + child.part_type_id;
        _meSectionMeta.set(key, {
          label: child.label, type_id: cat.type_id, type_label: typeLabel,
          order: order++, kind: "part_type", ref_id: child.part_type_id,
        });
        indexLabel(child.label, key);
        _meGroupMap.set(child.part_type_id, {
          type_id: cat.type_id, type_label: typeLabel,
          section_key: key, section_label: child.label,
          order: _meSectionMeta.get(key).order,
        });
      }
    }
  }
}

// Best-effort name → section match for legacy name-based parts (no
// `part_type`, per FINDING-007 these are explicitly best-effort — a unique
// label match wins, anything else (no match, or a label shared by more than
// one section) falls to "Other").
function _meSectionKeyForName(name) {
  const stripped = (name || "").replace(/\s+\d+$/, "").trim().toLowerCase();
  const key = _meLegacyLabelIndex?.get(stripped);
  return key || "_other";
}

// Section a manifest part belongs to: picker-added parts carry `part_type`
// and resolve exactly via the reverse map; legacy parts fall back to the
// best-effort name match.
function _meSectionForPart(part) {
  if (part?.part_type && _meGroupMap?.has(part.part_type)) {
    return _meGroupMap.get(part.part_type).section_key;
  }
  return _meSectionKeyForName(part?.name);
}

function _meSectionForPartWithParent(part, byLineId) {
  const parentId = part?.parent_line_id || "";
  if (parentId && byLineId?.has(parentId)) {
    return _meSectionForPart(byLineId.get(parentId));
  }
  return _meSectionForPart(part);
}

function _meTopLevelParts(parts) {
  return (parts || []).filter(p => {
    const pid = p.parent_line_id || "";
    return !pid || !(parts || []).some(x => x.line_id === pid);
  });
}

function _meStatusRowStyle(status) {
  if (status === "New")    return ' style="background:#eaf4fd"';
  if (status === "Used" || status === "Reused") return ' style="background:#fff3e0"';
  return "";
}

function _meDisplayName(part) {
  return part?.picker_config?.system_label || part?.name || "";
}

function _meMakeRows(parts) {
  // Accessory lines (parent_line_id set) nest under their parent's caret rather
  // than appearing as their own top-level rows.
  const childrenByParent = {};
  for (const p of parts) {
    const pid = p.parent_line_id || "";
    if (pid) (childrenByParent[pid] = childrenByParent[pid] || []).push(p);
  }
  const topLevel = _meTopLevelParts(parts);

  return topLevel.map(p => {
    const mfgModel = [p.manufacturer, p.part_number].filter(Boolean).join(" / ") || "—";
    const statusLabel = p.new_or_used
      ? (p.new_or_used === "Reused" && p.source ? `Reused (${esc(p.source)})` : esc(p.new_or_used))
      : "—";
    const comps = p.components || [];
    const kids = childrenByParent[p.line_id] || [];
    // Guided systems expand into their concrete shop components, not a second
    // transcript of every question already captured in picker_config.
    const childCount = comps.length + kids.length;
    const expandable = childCount > 0;
    const caret = expandable
      ? `<span class="me-expand-caret" data-lid="${esc(p.line_id)}">▸</span>`
      : `<span class="me-expand-spacer"></span>`;
    const rowAttrs = expandable ? ` class="me-parent-row" data-lid="${esc(p.line_id)}"` : "";
    let html = `<tr${rowAttrs}${_meStatusRowStyle(p.new_or_used)}>
      <td style="font-weight:500;max-width:160px;word-break:break-word">${caret}${esc(_meDisplayName(p))}${expandable ? ` <span class="me-comp-count">(${childCount})</span>` : ""}</td>
      <td style="color:var(--muted)">${esc(p.location || "—")}</td>
      <td>${esc(p.raw_color || "—")}</td>
      <td style="text-align:center">${p.quantity || "—"}</td>
      <td style="color:var(--muted);font-size:11px">${esc(mfgModel)}</td>
      <td style="font-size:11px;color:var(--muted)">${statusLabel}</td>
      <td><span class="badge ${p.include ? "badge-on" : "badge-off"}">${p.include ? "Yes" : "No"}</span></td>
      <td class="me-row-actions">
        <button class="btn btn-secondary btn-sm me-edit-btn" data-lid="${esc(p.line_id)}" title="Edit">≡</button>
        <button class="btn btn-danger btn-sm me-del-btn"  data-lid="${esc(p.line_id)}" title="Remove">✕</button>
      </td>
    </tr>`;
    // Display-only SKU breakdown (the build sheet sees just the parent).
    for (const cm of comps) {
      const price = (cm.price != null) ? ` · $${cm.price}` : "";
      const label = cm.label || cm.name || cm.part_number || "Component";
      const detail = cm.detail || cm.value || "";
      html += `<tr class="me-comp-row" data-parent="${esc(p.line_id)}" hidden>
        <td style="padding-left:30px;color:var(--muted);font-size:12px">↳ ${esc(label)}</td>
        <td style="font-size:12px;color:var(--muted)">${esc(cm.location || "—")}</td>
        <td style="font-size:12px;color:var(--muted)">${esc(cm.color || "")}</td>
        <td style="text-align:center;font-size:12px;color:var(--muted)">${cm.quantity || ""}</td>
        <td colspan="4" style="font-size:11px;color:var(--muted)">${esc(detail)}${esc(cm.part_number ? ` · ${cm.part_number}` : "")}${price}</td>
      </tr>`;
    }
    // Accessory child lines — real parts, individually editable/removable.
    for (const c of kids) {
      const cMfgModel = [c.manufacturer, c.part_number].filter(Boolean).join(" / ") || "—";
      html += `<tr class="me-comp-row me-acc-row" data-parent="${esc(p.line_id)}" hidden>
        <td style="padding-left:24px;font-size:12px"><span class="me-acc-tag">accessory</span> ${esc(c.name)}</td>
        <td style="color:var(--muted);font-size:12px">${esc(c.location || "—")}</td>
        <td></td>
        <td style="text-align:center;font-size:12px">${c.quantity || "—"}</td>
        <td style="font-size:11px;color:var(--muted)">${esc(cMfgModel)}</td>
        <td></td>
        <td><span class="badge ${c.include ? "badge-on" : "badge-off"}">${c.include ? "Yes" : "No"}</span></td>
        <td class="me-row-actions">
          <button class="btn btn-secondary btn-sm me-edit-btn" data-lid="${esc(c.line_id)}" title="Edit">≡</button>
          <button class="btn btn-danger btn-sm me-del-btn"  data-lid="${esc(c.line_id)}" title="Remove">✕</button>
        </td>
      </tr>`;
    }
    return html;
  }).join("");
}

const _meThead = `<thead><tr>
  <th>Part</th><th>Location</th><th>Color</th><th style="text-align:center">Qty</th>
  <th>Mfg / Part #</th><th>Status</th><th>Incl.</th><th></th>
</tr></thead>`;

function _meRender() {
  const parts = _meDraft?.parts || [];
  $("me-parts-count").textContent = parts.length;

  const container = $("me-tbody-container");
  if (!container) return;

  // Group parts by parts_db category + family/part-type section
  const byLineId = new Map(parts.map(p => [p.line_id, p]));
  const grouped = new Map();
  for (const p of parts) {
    const sid = _meSectionForPartWithParent(p, byLineId);
    if (!grouped.has(sid)) grouped.set(sid, []);
    grouped.get(sid).push(p);
  }

  // Build HTML: one block per section that has parts, ordered to match the
  // browse-tree (category order, then family/part-type within), "Other" last.
  // Sections sharing a main category render under one muted category-group
  // header, so "sort by main category + part-type family" is visible.
  const orderedKeys = [...(_meSectionMeta?.keys() || [])]
    .filter(k => grouped.has(k))
    .sort((a, b) => _meSectionMeta.get(a).order - _meSectionMeta.get(b).order);

  let html = "";
  let lastTypeId = null;
  for (const key of orderedKeys) {
    const secParts = grouped.get(key);
    if (!secParts?.length) continue;
    const meta = _meSectionMeta.get(key);
    if (meta.type_id !== lastTypeId) {
      html += `<div class="me-cat-group-head">${esc(meta.type_label)}</div>`;
      lastTypeId = meta.type_id;
    }
    const topLevel = _meTopLevelParts(secParts);
    const sectionHeader = `<div class="me-cat-header">
        <span class="me-cat-label">${esc(meta.label)}</span>
        <span class="me-cat-count">(${topLevel.length})</span>
        <button class="btn btn-secondary btn-sm me-cat-add-btn" data-section="${esc(key)}">+ Add</button>
      </div>`;
    html += `<div class="me-cat-section">
      ${sectionHeader}
      <table class="parts-tbl">${_meThead}<tbody>${_meMakeRows(secParts)}</tbody></table>
    </div>`;
  }
  const otherParts = grouped.get("_other");
  if (otherParts?.length) {
    const otherTopLevel = _meTopLevelParts(otherParts);
    const otherHeader = `<div class="me-cat-header">
        <span class="me-cat-label">Other</span>
        <span class="me-cat-count">(${otherTopLevel.length})</span>
        <button class="btn btn-secondary btn-sm me-cat-add-btn" data-section="_other">+ Add</button>
      </div>`;
    html += `<div class="me-cat-section">
      ${otherHeader}
      <table class="parts-tbl">${_meThead}<tbody>${_meMakeRows(otherParts)}</tbody></table>
    </div>`;
  }
  html += `<div class="me-add-bottom">
    <button class="btn btn-primary btn-sm" onclick="addPart()">+ Add Part</button>
    <a href="#" onclick="addPartManual();return false" style="font-size:11px;color:var(--muted);margin-left:10px">add manually...</a>
  </div>`;

  container.innerHTML = html;

  // Wire edit/delete buttons
  container.querySelectorAll(".me-edit-btn").forEach(b =>
    b.addEventListener("click", () => openPartEditModal(b.dataset.lid))
  );
  container.querySelectorAll(".me-del-btn").forEach(b =>
    b.addEventListener("click", () => deletePart(b.dataset.lid))
  );
  // Wire component expand/collapse — clicking anywhere on an expandable parent
  // row toggles its child SKU rows (but not when an action button was clicked).
  container.querySelectorAll("tr.me-parent-row").forEach(row =>
    row.addEventListener("click", (e) => {
      if (e.target.closest(".me-row-actions")) return;
      const lid = row.dataset.lid;
      const caret = row.querySelector(".me-expand-caret");
      const open = caret ? caret.classList.toggle("open") : false;
      if (caret) caret.textContent = open ? "▾" : "▸";
      container.querySelectorAll(`tr.me-comp-row[data-parent="${lid}"]`)
        .forEach(r => { r.hidden = !open; });
    })
  );
  container.querySelectorAll(".me-cat-add-btn").forEach(b =>
    b.addEventListener("click", () => addPartInSection(b.dataset.section))
  );

  // Keep the read-only overview table in sync
  if (typeof renderParts === "function") {
    renderParts(parts.map(p => ({
      name: p.name, location: p.location,
      color: p.raw_color, qty: p.quantity, include: p.include,
    })));
    $("parts-count").textContent = parts.length;
  }
}

// ── status radio buttons ──────────────────────────────────

function _meSetStatus(value) {
  document.querySelectorAll(".me-status-btn").forEach(btn => {
    btn.classList.toggle("me-status-btn--active", btn.dataset.value === value);
  });
  const sourceRow = $("me-reused-source-row");
  if (sourceRow) sourceRow.style.display = value === "Reused" ? "" : "none";
  if (value !== "Reused") {
    const srcEl = $("me-source");
    if (srcEl) srcEl.value = "";
  }
}

function _meGetStatus() {
  const active = document.querySelector(".me-status-btn.me-status-btn--active");
  return active?.dataset.value || "";
}

// ── modal open/close ─────────────────────────────────────

async function addPart() {
  // Open the intelligent picker (preferred path)
  if (typeof openPicker === "function") {
    try {
      await openPicker();
      return;
    } catch(e) {
      console.error("Picker failed, falling back to modal:", e);
    }
  }
  // Fallback: old modal
  _meEditLineId = null;
  $("me-modal-title").textContent = "Add Part";
  $("me-name").value      = "";
  $("me-include").checked = true;
  _meSetStatus("");
  $("me-location").value  = "";
  $("me-color").value     = "";
  $("me-qty").value       = 1;
  $("me-mfg").value       = "";
  $("me-prod").value      = "";
  $("me-pn").value        = "";
  $("me-notes").value     = "";
  await _mePopulateDataLists();
  _meUpdateLocations("");
  _meModalSetColorVisibility("");
  $("me-modal").classList.add("open");
  setTimeout(() => $("me-name").focus(), 50);
}

// Tracer bracket quantity by kind: an "L" bracket needs (lamps + 1) per housing
// (Whelen: N-lamp housing → N+1), a vehicle-specific/other kit one per housing.
// Returns null when the parent isn't a tracer housing (leave qty unchanged).
function _meTracerBracketQty(part, parent, sku) {
  if (!parent || part.accessory_category !== "bracket_mount") return null;
  const m = /TCRWX(\d+)/i.exec(parent.part_number || "");
  if (!m) return null;
  const lamps = parseInt(m[1], 10) || 0;
  const housings = parent.quantity || 1;
  const s = (sku || "").toUpperCase();
  return (s.includes("LBKT") || s.includes("L BRACKET")) ? (lamps + 1) * housings : housings;
}

// Swap an accessory line within its category — a single dropdown, no full picker.
async function _meEditAccessory(part) {
  let groups = [];
  try {
    const res = await api(`/api/parts-db/accessories?product_id=${encodeURIComponent(part.accessory_parent_product)}`);
    groups = (res && res.accessories) || [];
  } catch (e) { console.error("accessory options failed:", e); toast("Could not load accessory options", "error"); return; }
  const g = groups.find(x => x.category === part.accessory_category);
  if (!g) { toast("No options for this accessory", "error"); return; }
  const parent = (_meDraft?.parts || []).find(p => p.line_id === part.parent_line_id);
  const parentName = parent ? parent.name : (part.name.split(" · ")[0] || "Part");

  // For a tracer housing, narrow brackets to the tracer-specific kits (same as
  // the picker) so the generic side/rear-warning brackets don't clutter the swap.
  let gOptions = g.options || [];
  if (part.accessory_category === "bracket_mount" && /TCRWX\d/i.test(parent?.part_number || ""))
    gOptions = gOptions.filter(o => /tracer/i.test(o.product_id));

  const opts = [];
  for (const o of gOptions) for (const s of (o.skus || [])) {
    const colors = [s.color, s.secondary_color].filter(Boolean).map(c => c[0].toUpperCase() + c.slice(1)).join("/");
    const label = `${o.model} · ${s.part_number}${colors ? " · " + colors : ""}${s.lens_type ? " · " + s.lens_type : ""}${s.price != null ? " · $" + s.price : ""}`;
    opts.push({ value: `${o.product_id}::${s.part_number}`, label, model: o.model, mfr: o.manufacturer_label || "", sku: s.part_number });
  }
  const cur = opts.find(o => o.sku === part.part_number);

  const ov = document.createElement("div");
  ov.className = "me-acc-edit-ov";
  ov.innerHTML = `<div class="me-acc-edit">
    <div class="me-acc-edit-h">Swap ${esc(g.label)} for ${esc(parentName)}</div>
    <select id="me-acc-edit-sel">
      ${opts.map(o => `<option value="${esc(o.value)}"${cur && cur.value === o.value ? " selected" : ""}>${esc(o.label)}</option>`).join("")}
      ${g.required ? "" : `<option value="__remove__">— Remove this accessory —</option>`}
    </select>
    <div class="me-acc-edit-btns">
      <button class="btn btn-secondary btn-sm" id="me-acc-cancel">Cancel</button>
      <button class="btn btn-primary btn-sm" id="me-acc-save">Save</button>
    </div>
  </div>`;
  document.body.appendChild(ov);
  const close = () => ov.remove();
  ov.addEventListener("click", e => { if (e.target === ov) close(); });
  ov.querySelector("#me-acc-cancel").addEventListener("click", close);
  ov.querySelector("#me-acc-save").addEventListener("click", async () => {
    const val = ov.querySelector("#me-acc-edit-sel").value;
    close();
    if (val === "__remove__") { await deletePart(part.line_id); return; }
    const o = opts.find(x => x.value === val);
    if (!o || o.sku === part.part_number) return;   // unchanged
    const body = { ...part, part_number: o.sku, manufacturer: o.mfr, name: `${parentName} · ${o.model}` };
    const q = _meTracerBracketQty(part, parent, o.sku);   // recompute tracer bracket qty
    if (q != null) body.quantity = q;
    const r = await api(`/api/draft/${_meDraftId}/part/${part.line_id}/update`, body);
    if (!r?.ok) { toast(r?.error || "Update failed", "error"); return; }
    toast("Accessory updated", "success");
    if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
    await loadDraftManifest(_meDraftId);
    if ($("card-preview") && !$("card-preview").hidden) pvLoad(_meDraftId);
  });
}

// Direct-to-modal fallback (bypasses picker)
async function addPartManual() {
  // Fake a non-function openPicker to force the fallback path
  const saved = window.openPicker;
  window.openPicker = undefined;
  await addPart();
  window.openPicker = saved;
}

async function openPartEditModal(lineId) {
  const part = (_meDraft?.parts || []).find(p => p.line_id === lineId);
  if (!part) return;
  // Accessory line → focused category-scoped swap, not the full part picker.
  if (part.parent_line_id && part.accessory_parent_product && part.accessory_category) {
    return _meEditAccessory(part);
  }
  // Preferred: edit in the new picker panel.
  if (typeof _pickerOpenEdit === "function") {
    _pickerOpenEdit(part);
    return;
  }
  // Fallback: old flat modal.
  _meEditLineId = lineId;
  $("me-modal-title").textContent  = "Edit Part";
  $("me-name").value      = part.name          || "";
  $("me-include").checked = !!part.include;
  _meSetStatus(part.new_or_used || "");
  const srcEl = $("me-source");
  if (srcEl) srcEl.value = part.source || "";
  $("me-location").value  = part.location       || "";
  $("me-color").value     = part.raw_color      || "";
  $("me-qty").value       = part.quantity        ?? 0;
  $("me-mfg").value       = part.manufacturer   || "";
  $("me-prod").value      = "";
  $("me-pn").value        = part.part_number     || "";
  $("me-notes").value     = part.notes           || "";
  await _mePopulateDataLists();
  _meUpdateLocations(part.name || "");
  _meModalSetColorVisibility(part.name || "");
  _meUpdateManufacturers(part.name || "");
  $("me-modal").classList.add("open");
}

function meCancelModal() {
  $("me-modal").classList.remove("open");
}

// ── save / delete ─────────────────────────────────────────

async function savePartEdit() {
  const name = $("me-name").value.trim();
  if (!name) { toast("Part type is required", "error"); return; }

  const body = {
    name,
    include:      $("me-include").checked,
    new_or_used:  _meGetStatus(),
    source:       ($("me-source")?.value || "").trim(),
    location:     $("me-location").value.trim(),
    raw_color:    $("me-color").value.trim(),
    quantity:     parseInt($("me-qty").value, 10) || 0,
    manufacturer: $("me-mfg").value.trim(),
    part_number:  $("me-pn").value.trim(),
    notes:        $("me-notes").value.trim(),
  };

  const saveBtn = $("me-btn-save");
  saveBtn.disabled = true;
  const res = _meEditLineId
    ? await api("/api/draft/" + _meDraftId + "/part/" + _meEditLineId + "/update", body)
    : await api("/api/draft/" + _meDraftId + "/part", body);
  saveBtn.disabled = false;

  if (!res.ok) { toast(res.error || "Save failed", "error"); return; }

  meCancelModal();
  toast(_meEditLineId ? "Part updated" : "Part added", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  await loadDraftManifest(_meDraftId);
  if ($("card-preview") && !$("card-preview").hidden) pvLoad(_meDraftId);
}

async function deletePart(lineId) {
  const kids = (_meDraft?.parts || []).filter(p => p.parent_line_id === lineId);
  const prompt = kids.length
    ? `This part has ${kids.length} accessor${kids.length === 1 ? "y" : "ies"} — remove them too?`
    : "Remove this part from the build?";
  if (!confirm(prompt)) return;

  const res = await api("/api/draft/" + _meDraftId + "/part/" + lineId + "/delete", {});
  if (!res.ok) { toast(res.error || "Delete failed", "error"); return; }

  const n = res.cascaded_accessories || 0;
  toast(n ? `Part + ${n} accessor${n === 1 ? "y" : "ies"} removed` : "Part removed", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  await loadDraftManifest(_meDraftId);
  if ($("card-preview") && !$("card-preview").hidden) pvLoad(_meDraftId);
}

// ── datalist population ───────────────────────────────────

let _meManifestCache = {};  // { partTypeName: {manufacturers, part_numbers, locations} }

async function _meFetchManifestData(partName) {
  if (!partName) return;
  // Strip trailing sequence numbers to match parts_db labels
  // "Forward Warning 1" → "Forward Warning"
  const baseName = partName.replace(/\s+\d+$/, "").trim();
  const key = baseName || partName;
  if (_meManifestCache[key]) return;
  try {
    const res = await api(`/api/parts-db/manifest-data?part_type=${encodeURIComponent(key)}`);
    if (res && !res.error) {
      _meManifestCache[key] = res;
    }
  } catch(e) {
    // fall through — will use workbook_rules fallback
  }
}

async function _mePopulateDataLists() {
  // Still load catalog for render_kind lookup (name-based fallback modal)
  if (!_catalog?.parts) {
    const res = await api("/api/catalog");
    if (res?.parts) _catalog = res;
  }
  if (!_workbookRules?.part_rules) {
    const res = await api("/api/workbook-rules");
    if (res?.part_rules) _workbookRules = res;
  }
  await _meBuildGroupMap();

  // Populate part type dropdown from catalog (planner requires catalog names)
  const nameList = $("me-name-list");
  if (nameList && _catalog?.parts) {
    nameList.innerHTML = (_catalog.parts)
      .map(p => p.display_name || p.part_id)
      .map(n => `<option value="${esc(n)}">`)
      .join("");
  }

  _meUpdateManufacturers($("me-name")?.value || "");
}

async function _meUpdateManufacturers(partName) {
  const baseName = (partName || "").replace(/\s+\d+$/, "").trim();
  await _meFetchManifestData(partName);
  const md = _meManifestCache[baseName || partName];
  const mfgList = $("me-mfg-list");
  if (!mfgList) return;
  if (md?.manufacturers?.length) {
    mfgList.innerHTML = md.manufacturers
      .map(m => `<option value="${esc(m.label)}" data-mid="${esc(m.manufacturer_id||"")}">`)
      .join("");
  } else {
    // Fallback to workbook_rules
    const rule = (_workbookRules?.part_rules || {})[partName];
    const mfgs = rule?.manufacturer || [];
    mfgList.innerHTML = mfgs.map(m => `<option value="${esc(m)}">`).join("");
  }
  _meUpdatePartNumbers(partName, $("me-mfg")?.value || "", $("me-prod")?.value || "");
}

function _meUpdateProducts(partName, mfgFilter) {
const baseName = (partName || "").replace(/\s+\d+$/, "").trim();
const md = _meManifestCache[baseName || partName];
const prodList = $("me-prod-list");
if (!prodList) return;
if (md?.part_numbers?.length) {
  let pns = md.part_numbers;
  if (mfgFilter) {
    const mfgOpt = document.querySelector(`#me-mfg-list option[value="${esc(mfgFilter)}"]`);
    const mid = mfgOpt?.dataset?.mid || mfgFilter;
    pns = pns.filter(p => (p.manufacturer_id || "") === mid
                       || (p.manufacturer_id || "").toUpperCase() === mfgFilter.toUpperCase());
  }
  // Unique product models, preserving order
  const seen = new Set();
  const products = [];
  for (const p of pns) {
    const model = p.product_model || "";
    if (model && !seen.has(model)) {
      seen.add(model);
      products.push(model);
    }
  }
  prodList.innerHTML = products.map(m => `<option value="${esc(m)}">`).join("");
} else {
  prodList.innerHTML = "";
}
}

function _meUpdatePartNumbers(partName, mfgFilter, prodFilter) {
const baseName = (partName || "").replace(/\s+\d+$/, "").trim();
const md = _meManifestCache[baseName || partName];
const pnList = $("me-pn-list");
if (!pnList) return;
if (md?.part_numbers?.length) {
  let pns = md.part_numbers;
  if (mfgFilter) {
    const mfgOpt = document.querySelector(`#me-mfg-list option[value="${esc(mfgFilter)}"]`);
    const mid = mfgOpt?.dataset?.mid || mfgFilter;
    pns = pns.filter(p => (p.manufacturer_id || "") === mid
                       || (p.manufacturer_id || "").toUpperCase() === mfgFilter.toUpperCase());
  }
  if (prodFilter) {
    pns = pns.filter(p => (p.product_model || "").toLowerCase() === prodFilter.toLowerCase());
  }
  pnList.innerHTML = pns.map(p => {
    const price = p.qb_unit_price || p.price_usd;
    const priceStr = price ? `  $${price}` : "";
    const qb = p.qb_item_id ? " 🅀" : "";
    return `<option value="${esc(p.part_number)}">${esc(p.part_number)}${priceStr}${qb}</option>`;
  }).join("");
} else {
  const rule = (_workbookRules?.part_rules || {})[partName];
  const models = rule?.models || [];
  pnList.innerHTML = models.map(m => `<option value="${esc(m)}">`).join("");
}
}

function _meUpdateLocations(partName) {
  const baseName = (partName || "").replace(/\s+\d+$/, "").trim();
  const md = _meManifestCache[baseName || partName];
  let locs = [];
  if (md?.locations?.length) {
    locs = md.locations.filter(l => !/^specify\s+loc/i.test(l));
  }
  if (!locs.length) {
    const rule = (_workbookRules?.part_rules || {})[partName];
    locs = (rule?.locations || []).filter(l => !/^specify\s+loc/i.test(l));
  }
  const catalogPart = (_catalog?.parts || []).find(
    p => (p.display_name || "").toLowerCase() === (partName || "").toLowerCase()
  );
  if (!locs.length && catalogPart?.is_fixture) locs = ["Default"];
  if (typeof allKnownLocationNames === "function" && !locs.length) {
    locs = allKnownLocationNames();
  }
  locs.push("Set Manually");
  const locList = $("me-loc-list");
  if (locList) locList.innerHTML = locs.map(l => `<option value="${esc(l)}">`).join("");
}

function _meModalSetColorVisibility(partName) {
  const catalogPart = (_catalog?.parts || []).find(
    p => (p.display_name || "").toLowerCase() === (partName || "").toLowerCase()
  );
  const rk = catalogPart?.render_kind;
  const show = !catalogPart || rk === "light" || rk === "bar";
  const colorRow = $("me-color")?.closest?.(".form-group") || $("me-color")?.parentElement;
  if (colorRow) colorRow.style.display = show ? "" : "none";
}

// Manifest groups are sales-oriented, so route each subgroup's Add button
// through the picker with its resolved part-type set. The picker translates
// that back to the matching browse-tree family or leaf.
async function addPartInSection(sectionId) {
  const meta = _meSectionMeta?.get(sectionId);
  if (typeof openPickerInSection === "function") {
    try {
      await openPickerInSection({
        label: meta?.label || "",
        refId: meta?.ref_id || "",
        partTypeIds: meta?.part_type_ids || [],
      });
      return;
    } catch (e) {
      console.error("Scoped picker failed, falling back to unscoped picker:", e);
    }
  }
  await addPart();
  if (!meta) return;
  const all = _catalog?.parts || [];
  const inSec  = all.filter(p => _meSectionKeyForName(p.display_name || "") === sectionId);
  const outSec = all.filter(p => _meSectionKeyForName(p.display_name || "") !== sectionId);
  const nameList = $("me-name-list");
  if (!nameList) return;
  nameList.innerHTML = [
    ...inSec.map(p => `<option value="${esc(p.display_name || p.part_id)}">`),
    ...outSec.map(p => {
      const sid = _meSectionKeyForName(p.display_name || "");
      const sMeta = _meSectionMeta.get(sid);
      const suffix = sMeta ? ` [${sMeta.label}]` : "";
      return `<option value="${esc((p.display_name || p.part_id) + suffix)}">`;
    }),
  ].join("");
}

// ── keyboard shortcuts ────────────────────────────────────

document.addEventListener("keydown", e => {
  if (!$("me-modal").classList.contains("open")) return;
  if (e.key === "Escape") { meCancelModal(); }
  if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "SELECT") {
    e.preventDefault();
    savePartEdit();
  }
});

// Wire status radio buttons
document.querySelectorAll(".me-status-btn").forEach(btn => {
  btn.addEventListener("click", () => _meSetStatus(btn.dataset.value));
});

// Wire me-name → location list, color visibility, manufacturer list, part number list
(function() {
  const nameInput = $("me-name");
  if (nameInput) {
    nameInput.addEventListener("input", () => {
      const v = nameInput.value;
      _meUpdateLocations(v);
      _meModalSetColorVisibility(v);
      _meUpdateManufacturers(v);
    });
  }
  const mfgInput = $("me-mfg");
  if (mfgInput) {
    mfgInput.addEventListener("input", () => {
      const pn = $("me-name")?.value || "";
      _meUpdateProducts(pn, mfgInput.value);
      _meUpdatePartNumbers(pn, mfgInput.value, $("me-prod")?.value || "");
    });
  }
  const prodInput = $("me-prod");
  if (prodInput) {
    prodInput.addEventListener("input", () => {
      const pn = $("me-name")?.value || "";
      _meUpdatePartNumbers(pn, $("me-mfg")?.value || "", prodInput.value);
    });
  }
})();
