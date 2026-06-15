// ═══════════════════════════════════════════════════════
// BUILD MANIFEST EDITOR
// ═══════════════════════════════════════════════════════

let _meDraftId    = null;
let _meDraft      = null;
let _meEditLineId = null;   // null = add mode
let _meSections   = [];     // [{id, label, parts: Set<lowerName>}]

// ── public API ───────────────────────────────────────────

async function loadDraftManifest(draftId) {
  _meDraftId = draftId;
  if (!draftId) { meHide(); return; }
  const res = await api("/api/draft/" + encodeURIComponent(draftId));
  if (!res.ok) return;
  _meDraft = res.draft;
  // Workbook rules drive the section→parts grouping. Without them every part
  // falls into "Other". They normally load when the user opens the add/edit
  // modal — but the initial render happens before that, so the manifest
  // appeared uncategorized until a part was added. Load up-front instead.
  if (!_workbookRules?.template_sections) {
    const wr = await api("/api/workbook-rules");
    if (wr?.template_sections) _workbookRules = wr;
  }
  _meRebuildSections();
  _meRender();
  show("card-manifest");
}

function meHide() {
  _meDraftId = null;
  _meDraft   = null;
  hide("card-manifest");
}

// ── rendering ────────────────────────────────────────────

function _meRebuildSections() {
  _meSections = (_workbookRules?.template_sections || []).map(s => ({
    id:    s.label,
    label: s.label,
    parts: new Set((s.parts || []).map(p => (p.name || "").toLowerCase())),
  }));
}

function _meSectionFor(partName) {
  const lower = (partName || "").toLowerCase();
  const sec = _meSections.find(s => s.parts.has(lower));
  return sec?.id || "_other";
}

function _meStatusRowStyle(status) {
  if (status === "New")    return ' style="background:#eaf4fd"';
  if (status === "Used" || status === "Reused") return ' style="background:#fff3e0"';
  return "";
}

function _meMakeRows(parts) {
  return parts.map(p => {
    const mfgModel = [p.manufacturer, p.part_number].filter(Boolean).join(" / ") || "—";
    const statusLabel = p.new_or_used
      ? (p.new_or_used === "Reused" && p.source ? `Reused (${esc(p.source)})` : esc(p.new_or_used))
      : "—";
    return `<tr${_meStatusRowStyle(p.new_or_used)}>
      <td style="font-weight:500;max-width:160px;word-break:break-word">${esc(p.name)}</td>
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
  }).join("");
}

const _meThead = `<thead><tr>
  <th>Part</th><th>Location</th><th>Color</th><th style="text-align:center">Qty</th>
  <th>Mfg / Model #</th><th>Status</th><th>Incl.</th><th></th>
</tr></thead>`;

function _meRender() {
  const parts = _meDraft?.parts || [];
  $("me-parts-count").textContent = parts.length;

  const container = $("me-tbody-container");
  if (!container) return;

  // Group parts by section
  const grouped = new Map();
  for (const p of parts) {
    const sid = _meSectionFor(p.name);
    if (!grouped.has(sid)) grouped.set(sid, []);
    grouped.get(sid).push(p);
  }

  // Build HTML: one block per section that has parts, "Other" last
  let html = "";
  for (const sec of _meSections) {
    const secParts = grouped.get(sec.id);
    if (!secParts?.length) continue;
    html += `<div class="me-cat-section">
      <div class="me-cat-header">
        <span class="me-cat-label">${esc(sec.label)}</span>
        <span class="me-cat-count">(${secParts.length})</span>
        <button class="btn btn-secondary btn-sm me-cat-add-btn" data-section="${esc(sec.id)}">+ Add</button>
      </div>
      <table class="parts-tbl">${_meThead}<tbody>${_meMakeRows(secParts)}</tbody></table>
    </div>`;
  }
  const otherParts = grouped.get("_other");
  if (otherParts?.length) {
    html += `<div class="me-cat-section">
      <div class="me-cat-header">
        <span class="me-cat-label">Other</span>
        <span class="me-cat-count">(${otherParts.length})</span>
        <button class="btn btn-secondary btn-sm me-cat-add-btn" data-section="_other">+ Add</button>
      </div>
      <table class="parts-tbl">${_meThead}<tbody>${_meMakeRows(otherParts)}</tbody></table>
    </div>`;
  }
  html += `<div class="me-add-bottom">
    <button class="btn btn-primary btn-sm" onclick="addPart()">+ Add Part</button>
  </div>`;

  container.innerHTML = html;

  // Wire edit/delete buttons
  container.querySelectorAll(".me-edit-btn").forEach(b =>
    b.addEventListener("click", () => openPartEditModal(b.dataset.lid))
  );
  container.querySelectorAll(".me-del-btn").forEach(b =>
    b.addEventListener("click", () => deletePart(b.dataset.lid))
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
  _meEditLineId = null;
  $("me-modal-title").textContent = "Add Part";
  $("me-name").value      = "";
  $("me-include").checked = true;
  _meSetStatus("");
  $("me-location").value  = "";
  $("me-color").value     = "";
  $("me-qty").value       = 1;
  $("me-mfg").value       = "";
  $("me-pn").value        = "";
  $("me-notes").value     = "";
  await _mePopulateDataLists();
  _meUpdateLocations("");
  _meModalSetColorVisibility("");
  $("me-modal").classList.add("open");
  setTimeout(() => $("me-name").focus(), 50);
}

async function openPartEditModal(lineId) {
  const part = (_meDraft?.parts || []).find(p => p.line_id === lineId);
  if (!part) return;
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
  if (!confirm("Remove this part from the build?")) return;

  const res = await api("/api/draft/" + _meDraftId + "/part/" + lineId + "/delete", {});
  if (!res.ok) { toast(res.error || "Delete failed", "error"); return; }

  toast("Part removed", "success");
  if (typeof _pbeMarkDirty === "function") _pbeMarkDirty();
  await loadDraftManifest(_meDraftId);
  if ($("card-preview") && !$("card-preview").hidden) pvLoad(_meDraftId);
}

// ── datalist population ───────────────────────────────────

async function _mePopulateDataLists() {
  if (!_catalog?.parts) {
    const res = await api("/api/catalog");
    if (res?.parts) _catalog = res;
  }
  if (!_workbookRules?.part_rules) {
    const res = await api("/api/workbook-rules");
    if (res?.part_rules) _workbookRules = res;
  }
  _meRebuildSections();

  const nameList = $("me-name-list");
  if (nameList && _catalog?.parts) {
    nameList.innerHTML = (_catalog.parts)
      .map(p => p.display_name || p.part_id)
      .map(n => `<option value="${esc(n)}">`)
      .join("");
  }

  // Populate mfg and pn based on currently selected part type
  _meUpdateManufacturers($("me-name")?.value || "");
}

function _meUpdateManufacturers(partName) {
  const rule = (_workbookRules?.part_rules || {})[partName];
  const mfgs = rule?.manufacturer || [];
  const mfgList = $("me-mfg-list");
  if (mfgList) mfgList.innerHTML = mfgs.map(m => `<option value="${esc(m)}">`).join("");
  _meUpdatePartNumbers(partName, $("me-mfg")?.value || "");
}

function _meUpdatePartNumbers(partName, mfgFilter) {
  const rule   = (_workbookRules?.part_rules || {})[partName];
  const models = rule?.models || [];
  const pnList = $("me-pn-list");
  if (pnList) pnList.innerHTML = models.map(m => `<option value="${esc(m)}">`).join("");
}

function _meUpdateLocations(partName) {
  const rule = (_workbookRules?.part_rules || {})[partName];
  let locs = (rule?.locations || [])
    .filter(l => !/^specify\s+loc/i.test(l));

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

async function addPartInSection(sectionId) {
  await addPart();
  const sec = _meSections.find(s => s.id === sectionId);
  if (!sec) return;
  const all = _catalog?.parts || [];
  const inSec  = all.filter(p => sec.parts.has((p.display_name || "").toLowerCase()));
  const outSec = all.filter(p => !sec.parts.has((p.display_name || "").toLowerCase()));
  const nameList = $("me-name-list");
  if (!nameList) return;
  nameList.innerHTML = [
    ...inSec.map(p => `<option value="${esc(p.display_name || p.part_id)}">`),
    ...outSec.map(p => {
      const sid = _meSectionFor(p.display_name || "");
      const meta = _meSections.find(x => x.id === sid);
      const suffix = meta ? ` [${meta.label}]` : "";
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
      _meUpdatePartNumbers($("me-name")?.value || "", mfgInput.value);
    });
  }
})();
