// ── Projects module: Project Details tab ─────────────────────────────────────

function _ptProjectBuildSummary(project) {
  const groups = new Map();
  for (const unit of (project.build_units || [])) {
    const vm = _ptVehicleConfig(unit.vehicle_model);
    const vehicle = vm.make ? `${vm.make} ${vm.model}` : (unit.vehicle_model || "—");
    const buildType = unit.build_type || "—";
    const key = `${vehicle}\u0000${buildType}`;
    const count = (unit.individuals || []).length || unit.quantity || 1;
    groups.set(key, {
      vehicle,
      buildType,
      count: (groups.get(key)?.count || 0) + count,
    });
  }

  if (!groups.size) return `<p class="proj-empty-msg">No builds defined yet.</p>`;
  const rows = [...groups.values()].map(group => `
    <tr><td>${esc(group.vehicle)}</td><td>${esc(group.buildType)}</td><td>${group.count}</td></tr>`).join("");
  return `<table class="proj-build-summary-table">
    <thead><tr><th>Vehicle</th><th>Build type</th><th>Builds</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function _ptRenderEditTab(project, editable) {
  _PT.editTabEditable = editable;
  const panel = $("proj-ptab-edit");
  if (!panel) return;

  const c  = project.customer    || {};
  const pr = project.preferences || {};
  const projectNotes = project.project_notes || "";

  if (!editable) {
    // ── Read-only mode ──
    const custPairs = [
      ["Agency",     c.agency],
      ["Build Year", c.build_year],
      ["Sales Rep",  c.sales_rep],
    ].filter(([, v]) => v);

    const prefPairs = [
      ["Camera",      pr.camera_brand],
      ["Lighting",    (pr.lighting_brands || []).join(", ")],
      ["Lighting Setup", pr.lighting_mode === "trio" ? "TRIO" : "DUO"],
      ["Push Bumper", pr.push_bumper_brand],
      ["Cage",        pr.cage_brand],
      ["Console",     pr.console_brand],
      ["Slick Top",   pr.slick_top ? "Yes" : null],
      ["Notes",       pr.notes],
    ].filter(([, v]) => v);

    panel.innerHTML = `
      <div class="proj-edit-toolbar">
        <button class="btn btn-primary btn-sm" onclick="PT_enterEditMode()">✏️ Edit</button>
      </div>
      <div class="proj-section-label">Customer Info</div>
      ${custPairs.length
        ? custPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
        : `<p class="proj-empty-msg">No customer info saved.</p>`}
      <section class="proj-project-notes-card">
        <div>
          <h3>Project notes</h3>
          <p>Included on the build-notes page of every unit in this project.</p>
        </div>
        <button class="btn btn-primary btn-sm" type="button" onclick="PT_editProjectNotes()">${projectNotes ? "Edit shared notes" : "+ Add shared notes"}</button>
      </section>
      ${projectNotes
        ? _ptInfoRow("Shared across every build", projectNotes)
        : `<p class="proj-empty-msg">No project notes saved.</p>`}
      <div class="proj-section-label">Equipment Preferences</div>
      ${prefPairs.length
        ? prefPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
        : `<p class="proj-empty-msg">No preferences saved.</p>`}
      <div class="proj-section-label">Build Summary</div>
      ${_ptProjectBuildSummary(project)}`;
  } else {
    // ── Edit mode ──
    _PT.editTabUnits = (project.build_units || []).map(u => ({
      uid:           u.unit_id,
      vehicle_model: u.vehicle_model || "",
      build_type:    u.build_type    || "Patrol",
      quantity:      u.quantity      || 1,
      preset_id:     u.preset_id     || "",
      draft_id:      u.draft_id      || null,
      output_path:   u.output_path   || "",
      individuals:   (u.individuals  || []).map(ind => ({ ...ind })),
      _indOpen:      false,
      _customBuildTypeOpen: _ptIsCustomBuildType(u.build_type || ""),
    }));

    panel.innerHTML = `
      <div class="proj-edit-toolbar">
        <button class="btn btn-gold btn-sm" onclick="PT_saveEditForm()">💾 Save Changes</button>
        <button class="btn btn-secondary btn-sm" onclick="PT_cancelEditMode()">✕ Cancel</button>
      </div>
      <div id="proj-edit-form-status" class="proj-form-status" style="display:none"></div>

      <div class="proj-section-label">Customer Info</div>
      <div class="form-row">
        <div class="form-group proj-agency-group">
          <label>Agency <span class="req">*</span></label>
          <input type="text" id="et-agency" value="${esc(c.agency || "")}" autocomplete="off">
          <input type="hidden" id="et-agency-id" value="${esc(c.agency_id || "")}">
          <div id="et-agency-suggestions" class="sug-dropdown" style="display:none"></div>
        </div>
        <div class="form-group proj-year-group">
          <label>Build Year</label>
          <input type="number" id="et-build-year" value="${esc(c.build_year || "")}" min="2020" max="2040">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group proj-rep-group">
          <label>Sales Rep <span class="req">*</span></label>
          <input type="text" id="et-salesrep" value="${esc(c.sales_rep || "")}" autocomplete="off">
          <input type="hidden" id="et-salesrep-id" value="${esc(c.sales_rep_id || "")}">
          <div id="et-salesrep-suggestions" class="sug-dropdown" style="display:none"></div>
        </div>
      </div>

      <div class="proj-section-label">Project-specific equipment preferences</div>
      <p class="proj-form-hint">These are this project's choices. Use the option below only when they should become the agency standard for future projects.</p>
      <div class="form-row">
        <div class="form-group">
          <label>Camera System</label>
          <select id="et-camera-brand">${_ptPreferenceSelectOptions("camera_brand", pr.camera_brand || "")}</select>
        </div>
        <div class="form-group">
          <label>Push Bumper Brand</label>
          <select id="et-push-bumper-brand">${_ptPreferenceSelectOptions("push_bumper_brand", pr.push_bumper_brand || "")}</select>
        </div>
        <div class="form-group">
          <label>Cage / Partition Brand</label>
          <select id="et-cage-brand">${_ptPreferenceSelectOptions("cage_brand", pr.cage_brand || "")}</select>
        </div>
        <div class="form-group">
          <label>Console Brand</label>
          <select id="et-console-brand">${_ptPreferenceSelectOptions("console_brand", pr.console_brand || "")}</select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Lighting Brand</label>
          <select id="et-lighting">${_ptPreferenceSelectOptions("lighting", _ptPrimaryLightingBrand(pr))}</select>
        </div>
        <div class="form-group">
          <label>Default Lightheads</label>
          <select id="et-lighting-mode"><option value="duo"${pr.lighting_mode === "trio" ? "" : " selected"}>DUO</option><option value="trio"${pr.lighting_mode === "trio" ? " selected" : ""}>TRIO</option></select>
        </div>
      </div>
      <div class="form-group">
        <label>Preferences Notes</label>
        <textarea id="et-pref-notes" rows="2" class="proj-textarea-full">${esc(pr.notes || "")}</textarea>
      </div>
      <div class="proj-preferences-default-action">
        <button class="btn btn-secondary btn-sm" type="button"
          onclick="PT_setPreferencesAsAgencyDefault('et', 'et-agency-id', this)">Set selected choices as agency defaults</button>
        <p>This sets the starting choices for future projects only. Click Save Changes separately to apply them to this project. This does not update QuickBooks.</p>
      </div>

      <div class="proj-section-label">Project-wide final-page note</div>
      <p class="proj-form-hint">This appears on the final page of every build sheet in this project. Use the build editor for notes that apply to only one unit.</p>
      <div class="form-group">
        <label for="et-project-notes">Shared build instruction</label>
        <textarea id="et-project-notes" rows="3" class="proj-textarea-full" placeholder="Example: Confirm graphics package with the customer before final inspection.">${esc(projectNotes)}</textarea>
      </div>

      <div class="proj-section-label">Fleet Units</div>
      <div id="proj-edit-units-list"></div>
      <div class="proj-add-unit-row">
        <button class="btn btn-secondary btn-sm" onclick="PT_addEditUnit()">+ Add Unit Group</button>
      </div>

      `;

    _ptRenderEditUnits();
    _ptWireEditTabSearch();
  }
}

function _ptRenderEditUnits() {
  const listEl = $("proj-edit-units-list");
  if (!listEl) return;
  const currentAgency = $("et-agency")?.value?.trim() || "Agency";

  const btVals = _PT.projectOptions?.build_types || ["Patrol", "Admin", "Unmarked", "K-9", "Fire"];

  listEl.innerHTML = _PT.editTabUnits.map((u, i) => {
    const btOpts = _ptBuildTypeOptions(u.build_type, u._customBuildTypeOpen);

    const vpsts  = _ptVisiblePresets();
    const selPst = _ptVisiblePresets().find(p => p.preset_id === u.preset_id);
    const pstChip = selPst
      ? `<span class="proj-preset-chip">${esc(selPst.label)} <span class="proj-preset-chip-x" onclick="PT_clearEditPreset('${esc(u.uid)}')">×</span></span>`
      : `<span class="proj-preset-none">No preset selected</span>`;

    const hasInds = u.individuals.some(ind =>
      ind.unit_number || ind.vin || ind.year || ind.color
    );
    const indBtnLabel = `Add Individual Unit Details (×${u.quantity})`;
    let indBodyHtml = "";
    if (u._indOpen) {
      _ptEnsureIndividuals(u);
      indBodyHtml = u.individuals.slice(0, u.quantity).map((ind, n) =>
        `<div class="proj-ind-section-item">
          <div class="proj-ind-sub-label">${esc(_ptUnitLabel(u, ind, n))}</div>
          ${_ptIndRowHtml(ind)}
        </div>`
      ).join("");
    }

    return `<div class="proj-edit-unit-row" data-et-uid="${esc(u.uid)}">
      <div class="proj-edit-unit-hdr">
        <span class="proj-unit-label">Unit Group ${i + 1}</span>
        ${_PT.editTabUnits.length > 1
          ? `<button class="btn btn-danger btn-sm" onclick="PT_rmEditUnit('${esc(u.uid)}')">Remove</button>`
          : ""}
      </div>
      <div class="form-row">
        <div class="form-group proj-vehicle-group">
          <label>Vehicle Model</label>
          <select class="et-u-vehicle">${_ptVehicleOptionsMarkup(u.vehicle_model)}</select>
        </div>
        <div class="form-group proj-buildtype-group">
          <label>Build Type</label>
          <select class="et-u-buildtype">${btOpts}</select>
        </div>
        <div class="form-group proj-qty-group">
          <label>Qty</label>
          <input type="number" class="et-u-qty" min="1" value="${u.quantity}">
        </div>
      </div>
      ${_ptCustomBuildTypeInput(u.build_type, "et-u-buildtype-custom", u._customBuildTypeOpen)}
      <div class="proj-et-preset-row">
        <div class="proj-preset-hdr">
          <span class="proj-preset-hdr-label">Preset</span>
          <div class="proj-preset-btns-sm">
            <button class="btn btn-secondary btn-sm" onclick="PT_etAgencyPresets('${esc(u.uid)}')">
              ${esc(currentAgency)} Presets
            </button>
            <button class="btn btn-secondary btn-sm" onclick="PT_toggleEtPresetDD('${esc(u.uid)}')">All ▾</button>
          </div>
        </div>
        <div class="proj-preset-selected">${pstChip}</div>
        <div class="proj-et-preset-dd" id="et-preset-dd-${esc(u.uid)}" style="display:none">
          ${vpsts.length
            ? vpsts.map(p =>
                `<div class="proj-preset-option" onclick="PT_selectEditPreset('${esc(u.uid)}','${esc(p.preset_id)}')">
                  <strong>${esc(p.label)}</strong>
                </div>`
              ).join("")
            : `<div class="proj-preset-empty">No presets available</div>`
          }
        </div>
      </div>
      <div class="proj-ind-section">
        <button class="btn btn-secondary btn-sm proj-ind-toggle-btn"
          onclick="PT_toggleEtIndividuals('${esc(u.uid)}')">
          ${esc(indBtnLabel)}
        </button>
        <p class="proj-ind-hint">If you don't set these details now, you can add them later.</p>
        ${hasInds ? `<span class="proj-ind-configured">✓ ${u.individuals.filter(ind=>ind.unit_number||ind.vin).length} unit${u.individuals.filter(ind=>ind.unit_number||ind.vin).length!==1?"s":""} configured</span>` : ""}
        <div class="proj-ind-panel" style="${u._indOpen ? "" : "display:none"}">
          ${indBodyHtml}
        </div>
      </div>
    </div>`;
  }).join("");

  // Set vehicle select values and wire live qty listener after innerHTML is set
  _PT.editTabUnits.forEach(u => {
    const row = listEl.querySelector(`.proj-edit-unit-row[data-et-uid="${u.uid}"]`);
    if (!row) return;
    row.querySelector(".et-u-vehicle").value = _ptCanonicalVehicleType(u.vehicle_model);
    const qtyInput  = row.querySelector(".et-u-qty");
    const indBtn    = row.querySelector(".proj-ind-toggle-btn");
    const vehSelect = row.querySelector(".et-u-vehicle");
    const btSelect  = row.querySelector(".et-u-buildtype");

    // Vehicle / build-type changes invalidate the compatible-preset list. Commit
    // the change to in-memory edit state, clear the chip if the selection no
    // longer matches, then re-render so the dropdown reflects the new context.
    const onUnitContextChange = () => {
      _ptCollectEditUnits();
      const live = _PT.editTabUnits.find(x => x.uid === u.uid);
      if (live && btSelect?.value === _PT_CUSTOM_BUILD_TYPE) {
        live._customBuildTypeOpen = true;
        if (!_ptIsCustomBuildType(live.build_type)) live.build_type = "";
      }
      if (live && live.preset_id) {
        const stillCompatible = _ptCompatiblePresets(live).some(p => p.preset_id === live.preset_id);
        if (!stillCompatible) live.preset_id = "";
      }
      _ptRenderEditUnits();
      if (btSelect?.value === _PT_CUSTOM_BUILD_TYPE) {
        listEl.querySelector(`.proj-edit-unit-row[data-et-uid="${u.uid}"] .et-u-buildtype-custom`)?.focus();
      }
    };
    vehSelect?.addEventListener("change", onUnitContextChange);
    btSelect?.addEventListener("change", onUnitContextChange);

    qtyInput?.addEventListener("input", () => {
      const qty = Math.max(1, parseInt(qtyInput.value, 10) || 1);
      if (indBtn) indBtn.textContent = `Add Individual Unit Details (×${qty})`;
      if (u._indOpen) {
        u.quantity = qty;
        _ptEnsureIndividuals(u);
        _ptRenderEditUnits();
      }
    });
  });
}

function _ptCollectEditUnits() {
  const listEl = $("proj-edit-units-list");
  if (!listEl) return;
  _PT.editTabUnits.forEach(u => {
    const row = listEl.querySelector(`.proj-edit-unit-row[data-et-uid="${u.uid}"]`);
    if (!row) return;
    u.vehicle_model = row.querySelector(".et-u-vehicle").value;
    const buildType = row.querySelector(".et-u-buildtype");
    if (buildType?.value === _PT_CUSTOM_BUILD_TYPE) {
      u._customBuildTypeOpen = true;
      u.build_type = row.querySelector(".et-u-buildtype-custom")?.value.trim() || u.build_type || "";
    } else {
      u._customBuildTypeOpen = false;
      u.build_type = buildType?.value || "";
    }
    u.quantity      = Math.max(1, parseInt(row.querySelector(".et-u-qty").value, 10) || 1);
    const indRows = row.querySelectorAll(".proj-ind-row");
    if (indRows.length) {
      const vm = _ptVehicleConfig(u.vehicle_model);
      u.individuals = Array.from(indRows).map(ir => {
        const iid      = ir.dataset.iid;
        const existing = u.individuals.find(i => i.individual_id === iid) || {};
        return {
          ...existing,
          individual_id:        iid,
          unit_number:          ir.querySelector(".ind-unit-number")?.value.trim()    || "",
          year:                 ir.querySelector(".ind-year")?.value.trim()           || "",
          make:                 vm.make  || existing.make  || "",
          model:                vm.model || existing.model || "",
          color:                ir.querySelector(".ind-color")?.value.trim()          || "",
          vin:                  ir.querySelector(".ind-vin")?.value.trim()            || "",
          existing_year:        ir.querySelector(".ind-existing-year")?.value.trim() || "",
          existing_make:        ir.querySelector(".ind-existing-make")?.value.trim() || "",
          existing_model:       ir.querySelector(".ind-existing-model")?.value.trim() || "",
          existing_build_type:  ir.querySelector(".ind-existing-build-type")?.value.trim() || "",
          existing_unit_number: ir.querySelector(".ind-existing-unit-number")?.value.trim() || "",
          existing_vin:         ir.querySelector(".ind-existing-vin")?.value.trim() || "",
          notes:                ir.querySelector(".ind-notes")?.value.trim()         || "",
          draft_id:             ir.dataset.draftId || null,
        };
      });
    }
  });
}

function _ptCollectEditForm() {
  _ptCollectEditUnits();
  _PT.editTabUnits.forEach(u => _ptEnsureIndividuals(u));
  return {
    project_id: _PT.viewProject?.project_id,
    customer: {
      agency:       ($("et-agency")?.value    || "").trim(),
      agency_id:    ($("et-agency-id")?.value  || "").trim(),
      build_year:   ($("et-build-year")?.value || "").trim(),
      sales_rep:    ($("et-salesrep")?.value   || "").trim(),
      sales_rep_id: ($("et-salesrep-id")?.value || "").trim(),
    },
    preferences: _ptPreferencePayload("et"),
    project_notes: ($("et-project-notes")?.value || "").trim(),
    build_units: _PT.editTabUnits.map(u => ({
      unit_id:       u.uid,
      vehicle_model: u.vehicle_model,
      build_type:    u.build_type,
      quantity:      u.quantity,
      preset_id:     u.preset_id,
      draft_id:      u.draft_id     || null,
      output_path:   u.output_path  || "",
      individuals:   u.individuals.map(ind => ({ ...ind })),
    })),
  };
}

function _ptWireEditTabSearch() {
  const etAgency = $("et-agency");
  if (etAgency) {
    _ptWireAgencySearch(
      etAgency,
      $("et-agency-id"),
      $("et-agency-suggestions"),
      () => _ptRenderEditUnits(),
    );
  }
  const etRep = $("et-salesrep");
  if (etRep) {
    _ptWireSalesRepSearch(etRep, $("et-salesrep-id"), $("et-salesrep-suggestions"));
  }
}

// ── Public actions ─────────────────────────────────────────────────────────────

window.PT_enterEditMode = function (focusProjectNotes = false) {
  if (!_PT.viewProject) return;
  _ptLoadPrefsOptions().then(() => {
    _ptRenderEditTab(_PT.viewProject, true);
    if (focusProjectNotes) requestAnimationFrame(() => $("et-project-notes")?.focus());
  });
};

window.PT_editProjectNotes = function () {
  window.PT_enterEditMode(true);
};

window.PT_cancelEditMode = function () {
  _ptRenderEditTab(_PT.viewProject, false);
};

window.PT_saveEditForm = async function () {
  const statusEl = $("proj-edit-form-status");
  const savBtn   = document.querySelector("#proj-ptab-edit .btn-gold");
  if (savBtn) savBtn.disabled = true;
  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.style.background = "#f0f4ff";
    statusEl.style.color = "var(--navy)";
    statusEl.textContent = "Saving…";
  }
  try {
    const payload = _ptCollectEditForm();
    if (!payload.customer.agency.trim()) {
      toast("Agency name is required", "error");
      if (statusEl) statusEl.style.display = "none";
      if (savBtn) savBtn.disabled = false;
      return;
    }
    // Snapshot which units had their preset changed before saving
    const presetSnapshot = {};
    (_PT.viewProject?.build_units || []).forEach(u => {
      presetSnapshot[u.unit_id] = { preset_id: u.preset_id, draft_id: u.draft_id, individuals: u.individuals || [] };
    });

    const res = await api("/api/project/save", payload);
    if (res.ok) {
      const projectId = res.project_id;

      // Recreate drafts for any unit whose preset changed and already had a draft
      const presetChangedUnits = payload.build_units.filter(newU => {
        const prev = presetSnapshot[newU.unit_id];
        return prev && prev.preset_id !== newU.preset_id;
      });

      for (const newU of presetChangedUnits) {
        const prev = presetSnapshot[newU.unit_id];
        const inds = prev.individuals.filter(ind => ind.draft_id);
        if (inds.length) {
          // Recreate each individual draft
          for (const ind of inds) {
            await api(
              `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(newU.unit_id)}/individual/${encodeURIComponent(ind.individual_id)}/create-draft`,
              {}
            );
          }
        } else if (prev.draft_id) {
          // Recreate the unit-level draft
          await api(
            `/api/project/${encodeURIComponent(projectId)}/unit/${encodeURIComponent(newU.unit_id)}/create-draft`,
            {}
          );
        }
      }

      await _ptLoadAll();
      const updated = _PT.projects.find(p => p.project_id === projectId) || _PT.viewProject;
      _PT.viewProject = updated;
      if (presetChangedUnits.length) {
        toast("Project saved — builds reset to new preset", "success");
      } else {
        toast("Project saved", "success");
      }
      _ptRenderOverview(updated);
      _ptRenderEditTab(updated, false);
      _ptRenderBuildsTab(updated);
      $("proj-detail-agency").textContent = _ptProjName(updated);
    } else {
      const msg = res.error || "Save failed";
      toast(msg, "error");
      if (statusEl) {
        statusEl.style.background = "#fdecea";
        statusEl.style.color = "var(--red)";
        statusEl.textContent = "❌ " + msg;
      }
      if (savBtn) savBtn.disabled = false;
    }
  } catch (e) {
    const msg = e.message || "Unexpected error";
    toast(msg, "error");
    if (statusEl) {
      statusEl.style.background = "#fdecea";
      statusEl.style.color = "var(--red)";
      statusEl.textContent = "❌ " + msg;
    }
    if (savBtn) savBtn.disabled = false;
  }
};

window.PT_addEditUnit = function () {
  _ptCollectEditUnits();
  _PT.editTabUnits.push({
    uid:           _ptUuid(),
    vehicle_model: _PT.vehicles[0] || "",
    build_type:    "Patrol",
    quantity:      1,
    preset_id:     "",
    draft_id:      null,
    output_path:   "",
    individuals:   [],
    _indOpen:      false,
  });
  _ptRenderEditUnits();
};

window.PT_rmEditUnit = function (uid) {
  _ptCollectEditUnits();
  _PT.editTabUnits = _PT.editTabUnits.filter(u => u.uid !== uid);
  if (!_PT.editTabUnits.length) PT_addEditUnit();
  else _ptRenderEditUnits();
};

window.PT_toggleEtPresetDD = function (uid) {
  document.querySelectorAll(".proj-et-preset-dd").forEach(dd => {
    if (dd.id !== `et-preset-dd-${uid}`) dd.style.display = "none";
  });
  const dd = $(`et-preset-dd-${uid}`);
  if (!dd) return;
  if (dd.style.display !== "none") {
    dd.style.display = "none";
    return;
  }
  // Rebuild the unfiltered list every time. The agency shortcut replaces the
  // same dropdown contents, so merely reopening the element would otherwise
  // keep showing the previous filtered agency subset under the "All" label.
  dd.innerHTML = _ptVisiblePresets().map(p =>
    `<div class="proj-preset-option" onclick="PT_selectEditPreset('${esc(uid)}','${esc(p.preset_id)}')">
      <strong>${esc(p.label)}</strong>
    </div>`
  ).join("") || `<div class="proj-preset-empty">No presets available</div>`;
  dd.style.display = "";
};

window.PT_etAgencyPresets = function (uid) {
  const agencyId = ($("et-agency-id")?.value || "").trim();
  if (!agencyId) { toast("No agency selected", "info"); return; }
  const unit = _PT.editTabUnits.find(x => x.uid === uid);
  const agencyPresets = _ptCompatiblePresets(unit).filter(p =>
    (p.agency_ids || []).includes(agencyId)
  );
  document.querySelectorAll(".proj-et-preset-dd").forEach(dd => {
    if (dd.id !== `et-preset-dd-${uid}`) dd.style.display = "none";
  });
  const dd = $(`et-preset-dd-${uid}`);
  if (!dd) return;
  if (!agencyPresets.length) { toast("No presets for this agency yet", "info"); return; }
  dd.innerHTML = agencyPresets.map(p =>
    `<div class="proj-preset-option" onclick="PT_selectEditPreset('${esc(uid)}','${esc(p.preset_id)}')">
      <strong>${esc(p.label)}</strong>
    </div>`
  ).join("");
  dd.style.display = "";
};

window.PT_selectEditPreset = function (uid, presetId) {
  _ptCollectEditUnits();
  const u = _PT.editTabUnits.find(x => x.uid === uid);
  if (u) u.preset_id = presetId;
  const dd = $(`et-preset-dd-${uid}`);
  if (dd) dd.style.display = "none";
  _ptRenderEditUnits();
};

window.PT_clearEditPreset = function (uid) {
  const u = _PT.editTabUnits.find(x => x.uid === uid);
  if (u) u.preset_id = "";
  _ptRenderEditUnits();
};

window.PT_toggleEtIndividuals = function (uid) {
  _ptCollectEditUnits();
  const u = _PT.editTabUnits.find(x => x.uid === uid);
  if (!u) return;
  u._indOpen = !u._indOpen;
  _ptRenderEditUnits();
};
