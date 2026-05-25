// Settings → Presets tab
(function () {
  let _presets   = [];
  let _agencies  = [];
  let _vehicles  = [];  // [{key, make, model}, ...]
  let _editId    = null;  // preset_id being edited; null = new
  let _importParts = null;              // parts array from workbook import, held while modal is open
  let _importPlacementOverrides = {};   // placement_overrides from build editor draft
  let _contextProject = null;           // project passed from build editor for post-save update prompt

  let _BT_OPTIONS = ["Patrol", "Unmarked", "Admin", "K-9", "Fire"];  // overwritten from API

  // ── helpers ───────────────────────────────────────────────────────────────

  function _agencyName(id) {
    const a = _agencies.find(x => x.agency_id === id);
    return a ? a.name : id;
  }

  function _autoName(agencyIds, buildTypes, vehicleTypes, tag) {
    const prefix = (agencyIds && agencyIds.length)
      ? _agencyName(agencyIds[0])
      : "General";
    const parts = [prefix];
    if (buildTypes && buildTypes.length === 1) parts.push(buildTypes[0]);
    if (vehicleTypes && vehicleTypes.length) parts.push(vehicleTypes.join("/"));
    let name = parts.join(" ");
    if ((!agencyIds || !agencyIds.length) && tag) name += ` — ${tag}`;
    return name;
  }

  function _agencyLabels(agencyIds) {
    if (!agencyIds || !agencyIds.length) return "(any)";
    return agencyIds.map(id => _agencyName(id)).join(", ");
  }

  function _vehicleLabels(keys) {
    if (!keys || !keys.length) return "(any)";
    return keys.map(k => {
      const v = _vehicles.find(x => x.key === k);
      return v ? `${v.make} ${v.model}` : k;
    }).join(", ");
  }

  function _findDuplicate(agencyIds, buildTypes, vehicleTypes, excludeId) {
    return _presets.find(p => {
      if (p.preset_id === excludeId) return false;
      if (p.source !== "workspace") return false;
      const sameAgency = JSON.stringify((p.agency_ids || []).sort()) === JSON.stringify((agencyIds || []).sort());
      const sameBuilds = JSON.stringify((p.build_types || []).sort()) === JSON.stringify((buildTypes || []).sort());
      const sameVehicles = JSON.stringify((p.vehicle_types || []).sort()) === JSON.stringify((vehicleTypes || []).sort());
      return sameAgency && sameBuilds && sameVehicles;
    });
  }

  // ── table rendering ───────────────────────────────────────────────────────

  function _renderTable(list) {
    const container = $("pm-list-container");
    if (!container) return;
    if (!list.length) {
      container.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0">No presets yet. Import a workbook or clone a bundled preset to get started.</p>`;
      return;
    }
    container.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:6px 8px">Name</th>
            <th style="text-align:left;padding:6px 8px">Vehicles</th>
            <th style="text-align:left;padding:6px 8px">Agencies</th>
            <th style="text-align:left;padding:6px 8px">Source</th>
            <th style="padding:6px 8px"></th>
          </tr>
        </thead>
        <tbody>
          ${list.map(p => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:7px 8px;font-weight:600">${esc(p.label)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(_vehicleLabels(p.vehicle_types))}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(_agencyLabels(p.agency_ids))}</td>
              <td style="padding:7px 8px">
                <span style="font-size:11px;padding:2px 6px;border-radius:3px;background:${p.source === 'bundled' ? 'var(--gold-bg,#fdf6e3)' : 'var(--active-bg)'};color:${p.source === 'bundled' ? 'var(--gold,#b8860b)' : 'var(--primary)'}">
                  ${p.source === 'bundled' ? 'bundled' : 'custom'}
                </span>
              </td>
              <td style="padding:7px 8px;white-space:nowrap;text-align:right">
                <button class="btn btn-secondary btn-sm" onclick="pmEdit('${esc(p.preset_id)}')">Edit</button>
                <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="pmExport('${esc(p.preset_id)}','${esc(p.label)}')">Export ↓</button>
                <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="pmClone('${esc(p.preset_id)}')">Clone</button>
                ${p.source !== 'bundled'
                  ? `<button class="btn btn-secondary btn-sm" style="margin-left:4px;color:var(--red)" onclick="pmDelete('${esc(p.preset_id)}','${esc(p.label)}')">Delete</button>`
                  : ""}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  }

  function _filterAndRender() {
    const q = ($("pm-search")?.value || "").toLowerCase();
    const filtered = q
      ? _presets.filter(p =>
          p.label.toLowerCase().includes(q) ||
          (p.vehicle_types || []).some(v => v.toLowerCase().includes(q)) ||
          _agencyLabels(p.agency_ids).toLowerCase().includes(q))
      : _presets;
    _renderTable(filtered);
  }

  // ── load data ─────────────────────────────────────────────────────────────

  async function _load() {
    const [pr, ar, opts] = await Promise.all([
      api("/api/presets").catch(() => null),
      api("/api/agencies").catch(() => null),
      api("/api/project-options").catch(() => null),
    ]);
    _presets  = pr?.presets  || [];
    _agencies = ar?.agencies || [];
    if (opts && (opts.build_types || []).length) {
      _BT_OPTIONS = opts.build_types;
    }
    _filterAndRender();
  }

  async function _loadVehicles() {
    if (_vehicles.length) return;
    try {
      const res = await api("/api/layouts");
      const rawVehicles = res?.vehicles || {};
      _vehicles = Object.entries(rawVehicles).map(([key, v]) => ({
        key,
        make: v.make || key,
        model: v.model || "",
      }));
    } catch (_) {
      _vehicles = [];
    }
  }

  // ── edit modal ────────────────────────────────────────────────────────────

  function _openModal(preset) {
    _editId = preset?.preset_id || null;

    // Populate agency radio buttons (single selection, or None for general preset)
    const agContainer = $("pem-agency-checks");
    if (agContainer) {
      const selectedId = (preset?.agency_ids || [])[0] || "";
      agContainer.innerHTML =
        `<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:13px;cursor:pointer">
          <input type="radio" name="pem-agency-radio" value="" ${!selectedId ? "checked" : ""}>
          <em style="color:var(--muted)">None (General preset)</em>
        </label>` +
        (_agencies.map(a => `
          <label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:13px;cursor:pointer">
            <input type="radio" name="pem-agency-radio" value="${esc(a.agency_id)}"
              ${selectedId === a.agency_id ? "checked" : ""}>
            ${esc(a.name)}
          </label>`).join("") || "");
    }

    // Populate vehicle multi-select
    const vContainer = $("pem-vehicle-checks");
    if (vContainer) {
      vContainer.innerHTML = _vehicles.map(v => `
        <label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:13px;cursor:pointer">
          <input type="checkbox" value="${esc(v.key)}"
            ${(preset?.vehicle_types || []).includes(v.key) ? "checked" : ""}>
          ${esc(v.make)} ${esc(v.model)}
        </label>`).join("") || "";
    }

    // Populate build type checkboxes
    const btContainer = $("pem-bt-checks");
    if (btContainer) {
      btContainer.innerHTML = _BT_OPTIONS.map(bt => `
        <label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:13px;cursor:pointer">
          <input type="checkbox" value="${esc(bt)}"
            ${(preset?.build_types || []).includes(bt) ? "checked" : ""}>
          ${esc(bt)}
        </label>`).join("");
    }

    const descEl = $("pem-description");
    if (descEl) descEl.value = preset?.description || "";

    const tagEl = $("pem-tag");
    if (tagEl) tagEl.value = preset?.tag || "";

    const partCountEl = $("pem-part-count");
    if (partCountEl && preset?.preset_id) {
      partCountEl.textContent = "Loading…";
      api(`/api/presets/${encodeURIComponent(preset.preset_id)}`).then(r => {
        if (partCountEl) partCountEl.textContent = `${(r?.parts || []).length} parts`;
      }).catch(() => { if (partCountEl) partCountEl.textContent = "—"; });
    } else if (partCountEl) {
      partCountEl.textContent = _importParts ? `${_importParts.length} parts (imported)` : "New preset — no parts yet";
    }

    const exportBtn = $("pem-export-btn");
    if (exportBtn) exportBtn.style.display = _editId ? "" : "none";

    _updateNamePreview();
    $("preset-edit-modal").classList.add("open");
  }

  function _closeModal() {
    $("preset-edit-modal").classList.remove("open");
    _editId = null;
    _importParts = null;
    _importPlacementOverrides = {};
    _contextProject = null;
  }

  function _getSelectedValues(containerId) {
    const el = $(containerId);
    if (!el) return [];
    return [...el.querySelectorAll("input:checked")].map(cb => cb.value);
  }

  function _getSelectedAgency() {
    const el = $("pem-agency-checks");
    if (!el) return [];
    const checked = el.querySelector("input[name='pem-agency-radio']:checked");
    return checked && checked.value ? [checked.value] : [];
  }

  function _updateNamePreview() {
    const agencyIds   = _getSelectedAgency();
    const buildTypes  = _getSelectedValues("pem-bt-checks");
    const vehicleKeys = _getSelectedValues("pem-vehicle-checks");
    const tag         = ($("pem-tag")?.value || "").trim();

    const tagRow = $("pem-tag-row");
    if (tagRow) tagRow.style.display = (!agencyIds.length) ? "" : "none";

    const name = _autoName(agencyIds, buildTypes, vehicleKeys, tag);
    const preview = $("pem-name-preview");
    if (preview) preview.textContent = name || "(auto-generated)";
  }

  async function _offerUpdateBuilds(presetId) {
    if (!_contextProject || !presetId) return;
    const affectedUnits = (_contextProject.build_units || [])
      .filter(u => u.preset_id === presetId);
    if (!affectedUnits.length) return;
    const agency = _contextProject.customer?.agency || "this project";
    const names  = affectedUnits.map(u =>
      [u.build_type, u.vehicle_model].filter(Boolean).join(" ")
    ).join(", ");
    if (!confirm(`${affectedUnits.length} build group(s) in "${agency}" use this preset (${names}).\n\nUpdate those builds with the new preset parts?`)) return;
    let updated = 0;
    for (const unit of affectedUnits) {
      for (const ind of (unit.individuals || [])) {
        if (!ind.draft_id) continue;
        try {
          const r = await api("/api/draft/save", {
            draft_id:            ind.draft_id,
            parts:               _importParts || [],
            placement_overrides: _importPlacementOverrides || {},
          });
          if (r.ok) updated++;
        } catch (_) {}
      }
    }
    if (updated) toast(`Updated ${updated} build(s) with new preset`, "success");
  }

  async function _saveModal() {
    const agencyIds   = _getSelectedAgency();
    const buildTypes  = _getSelectedValues("pem-bt-checks");
    const vehicleKeys = _getSelectedValues("pem-vehicle-checks");
    const tag         = ($("pem-tag")?.value || "").trim();
    const description = ($("pem-description")?.value || "").trim();

    // Client-side duplicate check (fast path — avoids round-trip in common case)
    const dup = _findDuplicate(agencyIds, buildTypes, vehicleKeys, _editId);
    if (dup) {
      if (!confirm(`A preset for this combination already exists:\n"${dup.label}"\n\nOverwrite it?`)) return;
      _editId = dup.preset_id;
    }

    const payload = {
      preset_id:           _editId || "",
      description,
      vehicle_types:       vehicleKeys,
      agency_ids:          agencyIds,
      build_types:         buildTypes,
      tag,
      parts:               _importParts || [],
      placement_overrides: _importPlacementOverrides || {},
    };

    // apiSave so the Phase 2-β proposal toast fires when cloud mode is on.
    const res = await apiSave("/api/presets/save", payload);

    // Backend conflict safety-net (race condition or client-side miss)
    if (res?.conflict) {
      if (!confirm(`A preset for this combination already exists:\n"${res.duplicate_label}"\n\nOverwrite it?`)) return;
      const r2 = await apiSave("/api/presets/save", {
        ...payload,
        overwrite:  true,
        preset_id:  res.duplicate_preset_id,
      });
      if (!r2?.ok) { toast(r2?.error || "Save failed", "error"); return; }
      if (!r2.proposed) toast(`Preset saved: ${r2.label}`, "success");
      await _offerUpdateBuilds(r2.preset_id);
      _closeModal();
      await _load();
      return;
    }

    if (!res?.ok) { toast(res?.error || "Save failed", "error"); return; }
    if (!res.proposed) toast(`Preset saved: ${res.label}`, "success");
    await _offerUpdateBuilds(res.preset_id);

    _closeModal();
    await _load();
  }

  // ── public actions (called from table buttons + HTML) ─────────────────────

  window.pmEdit = async function (presetId) {
    await _loadVehicles();
    const preset = _presets.find(p => p.preset_id === presetId);
    _openModal(preset || { preset_id: presetId });
  };

  window.pmClone = async function (presetId) {
    const res = await api(`/api/presets/${encodeURIComponent(presetId)}/clone`, {});
    if (!res?.ok) { toast(res?.error || "Clone failed", "error"); return; }
    toast(`Cloned: ${res.label}`, "success");
    await _load();
  };

  window.pmDelete = async function (presetId, label) {
    if (!confirm(`Delete preset "${label}"?`)) return;
    const r = await fetch(`/api/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" });
    const res = await r.json();
    if (!res?.ok) { toast(res?.error || "Delete failed", "error"); return; }
    toast("Preset deleted", "success");
    await _load();
  };

  window.pmExport = function (presetId, label) {
    // Trigger download of filled xlsx
    const url = `/api/presets/${encodeURIComponent(presetId)}/export-workbook`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${presetId}_preset.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // ── public entry point ────────────────────────────────────────────────────

  /**
   * Open the preset modal pre-filled from a build editor draft.
   * Called by build_editor.js when the user clicks "Create Preset from this Setup".
   *
   * @param {Array}  parts              - DraftPart objects from the current draft
   * @param {Object} placementOverrides - draft.placement_overrides dict
   * @param {Object} defaults           - { agencyIds, vehicleTypes, buildTypes }
   */
  window.pmOpenFromDraft = async function (parts, placementOverrides, defaults, project) {
    await Promise.all([_load(), _loadVehicles()]);
    _importParts              = parts || [];
    _importPlacementOverrides = placementOverrides || {};
    _contextProject           = project || null;
    _editId                 = null;
    const scaffold = {
      preset_id:     null,
      vehicle_types: defaults?.vehicleTypes || [],
      build_types:   defaults?.buildTypes   || [],
      agency_ids:    defaults?.agencyIds    || [],
      tag:           "",
      description:   "",
    };
    _openModal(scaffold);
  };

  window.initPresetsTab = async function () {
    await _load();
    await _loadVehicles();

    // Search input
    const searchEl = $("pm-search");
    if (searchEl) {
      searchEl.oninput = _filterAndRender;
    }

    // Import workbook
    const importBtn = $("pm-import-btn");
    const importInput = $("pm-import-input");
    if (importBtn && importInput) {
      importBtn.onclick = () => importInput.click();
      importInput.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        importInput.value = "";
        const b64 = await _fileToBase64(file);
        const res = await api("/api/presets/import-workbook", { data: b64, filename: file.name });
        if (!res?.ok) { toast(res?.error || "Import failed", "error"); return; }
        _importParts = res.parts || [];
        const scaffold = {
          preset_id: null,
          vehicle_types: res.vehicle_types || [],
          build_types: res.build_types || [],
          agency_ids: res.agency_ids || [],
          tag: "",
          description: "",
        };
        await _loadVehicles();
        _openModal(scaffold);
      };
    }

    // Export blank template
    const exportTplBtn = $("pm-export-template-btn");
    if (exportTplBtn) {
      exportTplBtn.onclick = () => {
        const a = document.createElement("a");
        a.href = "/api/template/export";
        a.download = "build_sheet_template.xlsx";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      };
    }

    // Add new preset
    const addBtn = $("pm-add-btn");
    if (addBtn) {
      addBtn.onclick = async () => {
        await _loadVehicles();
        _importParts = null;
        _openModal(null);
      };
    }

    // Modal wiring — idempotent, safe to call again
    _wireModalButtons();
  };

  // ── modal button wiring (runs once at load, safe to call from any context) ──

  function _wireModalButtons() {
    const saveBtn = $("pem-save");
    if (saveBtn && !saveBtn._pmWired) {
      saveBtn._pmWired = true;
      saveBtn.onclick = _saveModal;
    }
    const cancelBtn = $("pem-cancel");
    if (cancelBtn && !cancelBtn._pmWired) {
      cancelBtn._pmWired = true;
      cancelBtn.onclick = _closeModal;
    }
    const closeBtn = $("pem-close");
    if (closeBtn && !closeBtn._pmWired) {
      closeBtn._pmWired = true;
      closeBtn.onclick = _closeModal;
    }
    const exportBtn = $("pem-export-btn");
    if (exportBtn && !exportBtn._pmWired) {
      exportBtn._pmWired = true;
      exportBtn.onclick = () => { if (_editId) pmExport(_editId, _editId); };
    }
    ["pem-agency-checks", "pem-vehicle-checks", "pem-bt-checks"].forEach(id => {
      const el = $(id);
      if (el && !el._pmWired) {
        el._pmWired = true;
        el.addEventListener("change", _updateNamePreview);
      }
    });
    const tagEl = $("pem-tag");
    if (tagEl && !tagEl._pmWired) {
      tagEl._pmWired = true;
      tagEl.oninput = _updateNamePreview;
    }
  }

  // Wire immediately so the modal works even if Settings tab is never visited
  _wireModalButtons();

  // ── util ──────────────────────────────────────────────────────────────────

  function _fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => {
        const b64 = btoa(String.fromCharCode(...new Uint8Array(e.target.result)));
        resolve(b64);
      };
      reader.onerror = reject;
      reader.readAsArrayBuffer(file);
    });
  }
})();
