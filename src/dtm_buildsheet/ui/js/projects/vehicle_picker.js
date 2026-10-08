// Guided vehicle identity picker. The hidden layout input preserves compatibility
// with the existing assignment, preset, and artwork systems.

const _PT_VEHICLE_CATEGORIES = [
  ["snowmobile", "Snowmobile"], ["atv_utv", "ATV / UTV"],
  ["trailer", "Trailer"], ["boat", "Boat / watercraft"], ["other", "Other"],
];

function _ptVehicleIdentity(unit) {
  const raw = unit?.vehicle_identity && typeof unit.vehicle_identity === "object"
    ? unit.vehicle_identity : {};
  const layoutId = raw.layout_id || unit?.vehicle_model || "";
  const layout = _ptVehicleConfig(layoutId);
  const source = raw.source || (raw.make || raw.model ? "catalog" : "legacy");
  const identity = {
    source,
    model_year: String(raw.model_year || ""),
    make: String(raw.make || layout.make || ""),
    model: String(raw.model || layout.model || (source === "legacy" ? layoutId : "")),
    package: String(raw.package || ""),
    category: String(raw.category || "automobile"),
    catalog_source: String(raw.catalog_source || (source === "catalog" ? "NHTSA vPIC" : "")),
    catalog_make_id: String(raw.catalog_make_id || ""),
    catalog_model_id: String(raw.catalog_model_id || ""),
    layout_id: String(layoutId),
    display_name: String(raw.display_name || ""),
  };
  if (!identity.display_name) identity.display_name = _ptVehicleIdentityLabel(identity, layoutId);
  return identity;
}

function _ptNewVehicleIdentity(layoutId, defaultYear = "") {
  const identity = _ptVehicleIdentity({vehicle_model: layoutId});
  identity.model_year = String(defaultYear || "");
  if (identity.make && identity.model) {
    identity.source = "catalog";
    identity.catalog_source = "NHTSA vPIC";
  }
  identity.display_name = _ptVehicleIdentityLabel(identity, layoutId);
  return identity;
}

function _ptVehicleIdentityLabel(identity, fallback = "") {
  if (!identity) return fallback || "Choose vehicle";
  if (identity.source === "unknown") return "Unknown vehicle";
  if (identity.source === "custom") return identity.display_name || identity.model || fallback || "Custom vehicle";
  const parts = [identity.model_year, identity.make, identity.model, identity.package].filter(Boolean);
  return parts.join(" ") || identity.display_name || fallback || "Choose vehicle";
}

function _ptVehicleDisplayName(unit) {
  return _ptVehicleIdentityLabel(_ptVehicleIdentity(unit), unit?.vehicle_model || "Vehicle");
}

function _ptVehiclePickerMarkup(unit, prefix) {
  const identity = _ptVehicleIdentity(unit, prefix === "proj" ? $("proj-build-year")?.value : $("et-build-year")?.value);
  const custom = identity.source === "custom";
  const unknown = identity.source === "unknown";
  const categories = _PT_VEHICLE_CATEGORIES.map(([value, label]) =>
    `<option value="${value}"${value === identity.category ? " selected" : ""}>${label}</option>`
  ).join("");
  return `<div class="vehicle-guided-picker" data-picker-prefix="${esc(prefix)}">
    <input type="hidden" class="${prefix === "proj" ? "proj-u-vehicle" : "et-u-vehicle"}" value="${esc(identity.layout_id)}">
    <div class="vehicle-picker-tabs" role="tablist">
      <button type="button" class="vehicle-picker-tab${!custom && !unknown ? " active" : ""}" data-vehicle-mode="catalog">Year / Make / Model</button>
      <button type="button" class="vehicle-picker-tab${custom ? " active" : ""}" data-vehicle-mode="custom">Custom vehicle</button>
      <button type="button" class="vehicle-picker-tab${unknown ? " active" : ""}" data-vehicle-mode="unknown">Unknown for now</button>
    </div>
    <div class="vehicle-picker-catalog"${custom || unknown ? " hidden" : ""}>
      <div class="vehicle-quick-row">
        <span>Quick choices</span>
        <button type="button" data-police-quick="Ford|Police Interceptor Utility|">Ford PIU</button>
        <button type="button" data-police-quick="Dodge|Durango|Pursuit">Durango Pursuit</button>
        <button type="button" data-police-quick="Chevrolet|Tahoe|PPV">Tahoe PPV</button>
        <button type="button" data-police-quick="Dodge|Charger|PPV">Charger PPV <span class="vehicle-quick-status">Upcoming</span></button>
      </div>
      <div class="vehicle-guided-grid">
        <label><span>1 · Year</span><div class="vehicle-search-select" data-vehicle-search="year">
          <input type="search" inputmode="numeric" class="vehicle-search-input vehicle-year-input" value="${esc(identity.model_year)}" placeholder="Choose year" autocomplete="off" aria-label="Search model years">
          <button type="button" class="vehicle-search-toggle" aria-label="Open year choices"></button>
          <select class="vehicle-year" hidden><option value="${esc(identity.model_year)}">${esc(identity.model_year)}</option></select>
          <div class="vehicle-search-menu vehicle-search-menu-year" hidden></div>
        </div></label>
        <label><span>2 · Make</span><div class="vehicle-search-select" data-vehicle-search="make">
          <input type="search" class="vehicle-search-input vehicle-make-input" value="${esc(identity.make)}" placeholder="Search or choose a make" autocomplete="off" aria-label="Search vehicle makes">
          <button type="button" class="vehicle-search-toggle" aria-label="Open make choices"></button>
          <select class="vehicle-make" hidden><option value="${esc(identity.make)}">${esc(identity.make)}</option></select>
          <div class="vehicle-search-menu" hidden></div>
        </div></label>
        <label><span>3 · Model</span><div class="vehicle-search-select" data-vehicle-search="model">
          <input type="search" class="vehicle-search-input vehicle-model-input" value="${esc(identity.model)}" placeholder="Search or choose a model" autocomplete="off" aria-label="Search vehicle models">
          <button type="button" class="vehicle-search-toggle" aria-label="Open model choices"></button>
          <select class="vehicle-model" hidden><option value="${esc(identity.model)}">${esc(identity.model)}</option></select>
          <div class="vehicle-search-menu" hidden></div>
        </div></label>
        <label class="vehicle-package-field" hidden><span>4 · Package</span><div class="vehicle-search-select" data-vehicle-search="package">
          <input type="search" class="vehicle-search-input vehicle-package-input" value="${esc(identity.package || "Standard / none")}" placeholder="Choose package" autocomplete="off" aria-label="Search police packages">
          <button type="button" class="vehicle-search-toggle" aria-label="Open police package choices"></button>
          <select class="vehicle-package" hidden><option value="${esc(identity.package)}">${esc(identity.package)}</option></select>
          <div class="vehicle-search-menu" hidden></div>
        </div></label>
      </div>
      <p class="vehicle-catalog-note">The year menu shows next year and earlier. Type any future year through 2040 to use it. Future years use the newest available model list.</p>
    </div>
    <div class="vehicle-picker-custom"${custom ? "" : " hidden"}>
      <div class="vehicle-custom-grid">
        <label><span>Vehicle type</span><select class="vehicle-category">${categories}</select></label>
        <label><span>Name or description</span><input class="vehicle-custom-name" maxlength="80" value="${esc(custom ? (identity.display_name || identity.model) : "")}" placeholder="Example: Polaris Ranger XP 1000"></label>
      </div>
      <p class="vehicle-catalog-note">Use this for snowmobiles, ATVs/UTVs, trailers, boats, and specialty equipment.</p>
    </div>
    <div class="vehicle-picker-unknown"${unknown ? "" : " hidden"}>
      <p class="vehicle-catalog-note"><strong>Make and model are not known yet.</strong> The project can be saved now and the vehicle can be identified later. This is especially useful for service visits.</p>
    </div>
    <div class="vehicle-layout-status" aria-live="polite"></div>
  </div>`;
}

function _ptSetSafeOptions(select, items, selected, placeholder) {
  if (!select) return;
  select.replaceChildren();
  select.append(new Option(placeholder, ""));
  for (const item of items) select.append(new Option(item.name, item.name));
  if (selected && !items.some(item => item.name === selected)) select.append(new Option(selected, selected));
  select.value = selected || "";
}

function _ptRenderVehicleSearchMenu(container, items, emptyText = "No matches") {
  const menu = container?.querySelector(".vehicle-search-menu");
  if (!menu) return;
  menu.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "vehicle-search-empty";
    empty.textContent = emptyText;
    menu.append(empty);
    return;
  }
  for (const item of items) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "vehicle-search-option" + (item.is_specialty ? " specialty" : "");
    const name = document.createElement("span");
    name.className = "vehicle-search-option-name";
    name.textContent = item.name;
    const tags = document.createElement("span");
    tags.className = "vehicle-search-option-tags";
    for (const label of (item.vehicle_types || []).slice(0, 3)) {
      const tag = document.createElement("span");
      tag.className = "vehicle-type-tag" + (item.is_specialty ? " specialty" : "");
      tag.textContent = label;
      tags.append(tag);
    }
    option.append(name, tags);
    option.addEventListener("mousedown", event => event.preventDefault());
    option.addEventListener("click", () => {
      const select = container.querySelector("select");
      const input = container.querySelector(".vehicle-search-input");
      const value = Object.prototype.hasOwnProperty.call(item, "value") ? item.value : item.name;
      select.replaceChildren(new Option(item.name, value, true, true));
      select.selectedOptions[0].dataset.id = item.id || "";
      select.selectedOptions[0].dataset.types = JSON.stringify(item.vehicle_types || []);
      input.value = item.name;
      container.dataset.selectedValue = item.name;
      menu.hidden = true;
      select.dispatchEvent(new Event("change", {bubbles: true}));
    });
    menu.append(option);
  }
}

function _ptSetVehicleSearchValue(picker, kind, item) {
  const container = picker.querySelector(`[data-vehicle-search="${kind}"]`);
  if (!container) return;
  const select = container.querySelector("select");
  const input = container.querySelector(".vehicle-search-input");
  const value = item && Object.prototype.hasOwnProperty.call(item, "value") ? item.value : (item?.name || "");
  select.replaceChildren(new Option(item?.name || "", value, true, true));
  if (select.selectedOptions[0]) {
    select.selectedOptions[0].dataset.id = item?.id || "";
    select.selectedOptions[0].dataset.types = JSON.stringify(item?.vehicle_types || []);
  }
  input.value = item?.name || "";
  container.dataset.selectedValue = item?.name || "";
}

function _ptClearVehicleSearchSelection(container) {
  container.querySelector("select").replaceChildren(new Option("", ""));
  container.dataset.selectedValue = "";
}

function _ptWireVehicleSearch(container, loadItems, onClear) {
  const input = container.querySelector(".vehicle-search-input");
  const menu = container.querySelector(".vehicle-search-menu");
  const toggle = container.querySelector(".vehicle-search-toggle");
  let timer = null;
  const show = async query => {
    menu.hidden = false;
    menu.replaceChildren();
    const loading = document.createElement("div");
    loading.className = "vehicle-search-empty";
    loading.textContent = "Loading choices…";
    menu.append(loading);
    try {
      const items = await loadItems(query);
      _ptRenderVehicleSearchMenu(container, items);
    } catch (_) {
      _ptRenderVehicleSearchMenu(container, [], "Choices are temporarily unavailable");
    }
  };
  input.addEventListener("focus", () => show(input.value === container.dataset.selectedValue ? "" : input.value));
  input.addEventListener("input", () => {
    clearTimeout(timer);
    if (input.value !== container.dataset.selectedValue) onClear();
    timer = setTimeout(() => show(input.value.trim()), 220);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") menu.hidden = true;
    if (event.key === "ArrowDown") menu.querySelector("button")?.focus();
  });
  toggle.addEventListener("click", () => {
    if (!menu.hidden) { menu.hidden = true; return; }
    input.focus();
    show("");
  });
  container.addEventListener("focusout", () => setTimeout(() => {
    if (!container.contains(document.activeElement)) menu.hidden = true;
  }, 0));
}

async function _ptVehicleCatalog(path) {
  const response = await fetch(path, {cache: "no-store"});
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "Vehicle catalog unavailable");
  return Array.isArray(data.items) ? data.items : [];
}

async function _ptCachedVehicleCatalog(cache, key, path) {
  if (!cache[key]) {
    cache[key] = _ptVehicleCatalog(path).catch(error => {
      delete cache[key];
      throw error;
    });
  }
  return cache[key];
}

function _ptFindVehicleLayout(make, model) {
  const foldedMake = String(make || "").trim().toLowerCase();
  const foldedModel = String(model || "").trim().toLowerCase();
  return _PT.vehicles.find(vehicleId => {
    const vehicle = _PT.vehicleMap[vehicleId] || {};
    return String(vehicle.make || "").trim().toLowerCase() === foldedMake &&
      String(vehicle.model || "").trim().toLowerCase() === foldedModel;
  }) || "";
}

async function _ptResolveVehicleLayout(row, unit) {
  const identity = unit.vehicle_identity;
  const picker = row.querySelector(".vehicle-guided-picker");
  const hidden = row.querySelector(".proj-u-vehicle, .et-u-vehicle");
  const status = row.querySelector(".vehicle-layout-status");
  if (identity.source === "unknown") {
    unit.vehicle_model = "";
    unit.preset_id = "";
    identity.layout_id = "";
    identity.display_name = "Unknown vehicle";
    if (hidden) hidden.value = "";
    const selected = row.querySelector(".proj-preset-selected");
    if (selected) {
      const empty = document.createElement("span");
      empty.className = "proj-preset-none";
      empty.textContent = "No preset selected";
      selected.replaceChildren(empty);
    }
    if (status) {
      status.className = "vehicle-layout-status ready";
      status.textContent = "Vehicle details can be added later";
    }
    row.querySelector(".proj-unit-vehicle-summary")?.replaceChildren(document.createTextNode(identity.display_name));
    return;
  }
  const identityMissing = identity.source === "custom"
    ? !(identity.display_name || identity.model)
    : identity.source === "catalog" && (!identity.model_year || !identity.make || !identity.model);
  if (identityMissing) {
    unit.vehicle_model = "";
    identity.layout_id = "";
    if (hidden) hidden.value = "";
    if (status) {
      status.className = "vehicle-layout-status warning";
      status.textContent = identity.source === "custom"
        ? "Enter a name for the custom vehicle"
        : "Choose a year, make, and model";
    }
    return;
  }
  const untouchedLegacy = identity.source === "legacy" && picker?.dataset.vehicleDirty !== "true";
  let layoutId = untouchedLegacy
    ? (identity.layout_id || unit.vehicle_model)
    : _ptFindVehicleLayout(identity.make, identity.model);
  if (!untouchedLegacy && !layoutId && (identity.model || identity.display_name)) {
    unit.vehicle_model = "";
    identity.layout_id = "";
    if (hidden) hidden.value = "";
    if (status) { status.className = "vehicle-layout-status pending"; status.textContent = "Preparing vehicle layout…"; }
    try {
      const response = await fetch("/api/layouts/vehicles/create", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(identity),
      });
      const result = await response.json();
      if (!result.ok) throw new Error(result.error || "Could not create vehicle layout");
      layoutId = result.vehicle_id;
      _PT.vehicleMap[layoutId] = result.vehicle || {};
      if (!_PT.vehicles.includes(layoutId)) _PT.vehicles.push(layoutId);
    } catch (error) {
      if (status) { status.className = "vehicle-layout-status warning"; status.textContent = error.message || "Vehicle layout will need attention"; }
      return;
    }
  }
  unit.vehicle_model = layoutId;
  identity.layout_id = layoutId;
  identity.display_name = _ptVehicleIdentityLabel(identity, layoutId);
  if (hidden) hidden.value = layoutId;
  if (unit.preset_id && !_ptCompatiblePresets(unit).some(preset => preset.preset_id === unit.preset_id)) {
    unit.preset_id = "";
    const selected = row.querySelector(".proj-preset-selected");
    if (selected) {
      const empty = document.createElement("span");
      empty.className = "proj-preset-none";
      empty.textContent = "No preset selected";
      selected.replaceChildren(empty);
    }
  }
  const layout = _PT.vehicleMap[layoutId] || {};
  if (status) {
    status.className = `vehicle-layout-status ${layout.placeholder ? "warning" : "ready"}`;
    status.textContent = layout.placeholder ? "Vehicle layout needed" : "Vehicle layout available";
  }
  row.querySelector(".proj-unit-vehicle-summary")?.replaceChildren(document.createTextNode(identity.display_name));
}

function _ptReadVehiclePicker(row, unit) {
  const picker = row?.querySelector(".vehicle-guided-picker");
  if (!picker) return;
  const isCustom = !picker.querySelector(".vehicle-picker-custom")?.hidden;
  const isUnknown = !picker.querySelector(".vehicle-picker-unknown")?.hidden;
  const current = _ptVehicleIdentity(unit);
  if (current.source === "legacy" && picker.dataset.vehicleDirty !== "true") return;
  if (isUnknown) {
    unit.vehicle_model = "";
    unit.vehicle_identity = {
      ...current, source: "unknown", model_year: "", make: "Unknown", model: "Unknown",
      package: "", category: "automobile", catalog_source: "", catalog_make_id: "",
      catalog_model_id: "", layout_id: "", display_name: "Unknown vehicle",
    };
  } else if (isCustom) {
    const name = picker.querySelector(".vehicle-custom-name")?.value.trim() || "";
    unit.vehicle_identity = {
      ...current, source: "custom", model_year: "", make: "", model: name,
      package: "", category: picker.querySelector(".vehicle-category")?.value || "other",
      catalog_source: "", catalog_make_id: "", catalog_model_id: "", display_name: name,
    };
  } else {
    const makeSelect = picker.querySelector(".vehicle-make");
    const modelSelect = picker.querySelector(".vehicle-model");
    unit.vehicle_identity = {
      ...current, source: "catalog",
      model_year: picker.querySelector(".vehicle-year")?.value || "",
      make: makeSelect?.value || "", model: modelSelect?.value || "",
      package: picker.querySelector(".vehicle-package")?.value || "",
      category: "automobile", catalog_source: "NHTSA vPIC",
      catalog_make_id: makeSelect?.selectedOptions?.[0]?.dataset?.id || "",
      catalog_model_id: modelSelect?.selectedOptions?.[0]?.dataset?.id || "",
    };
  }
  unit.vehicle_identity.display_name = _ptVehicleIdentityLabel(unit.vehicle_identity, unit.vehicle_model);
}

function _ptVehicleIdentityError(unit) {
  const identity = _ptVehicleIdentity(unit);
  if (identity.source === "unknown") return "";
  if (identity.source === "custom" && !(identity.display_name || identity.model)) return "Enter a name for the custom vehicle.";
  if (identity.source === "catalog" && (!identity.model_year || !identity.make || !identity.model)) return "Choose a year, make, and model for every unit group.";
  if (!unit.vehicle_model && !identity.layout_id) return "Wait for the vehicle layout to finish preparing before saving.";
  return "";
}

function _ptPoliceVehicleAvailable(item, year) {
  const modelYear = Number(year || 0);
  const fromYear = Number(item.from_year);
  const toYear = Number(item.to_year || item.from_year);
  return Boolean(modelYear) && modelYear >= fromYear && (
    modelYear <= toYear || item.future_selectable === true
  );
}

async function _ptWireVehiclePicker(row, unit) {
  const picker = row?.querySelector(".vehicle-guided-picker");
  if (!picker) return;
  unit.vehicle_identity = _ptVehicleIdentity(unit);
  const year = picker.querySelector(".vehicle-year");
  const make = picker.querySelector(".vehicle-make");
  const model = picker.querySelector(".vehicle-model");
  const yearSearch = picker.querySelector('[data-vehicle-search="year"]');
  const makeSearch = picker.querySelector('[data-vehicle-search="make"]');
  const modelSearch = picker.querySelector('[data-vehicle-search="model"]');
  const packageSearch = picker.querySelector('[data-vehicle-search="package"]');
  const packageField = picker.querySelector(".vehicle-package-field");
  const packageSelect = picker.querySelector(".vehicle-package");
  const status = picker.querySelector(".vehicle-layout-status");
  let modelItems = [];
  let packageItems = [];
  const minYear = 1995;
  const maxYear = 2040;
  const latestMenuYear = Math.min(maxYear, new Date().getFullYear() + 1);
  const yearOption = value => {
    const text = String(value || "").trim();
    const numeric = Number(text);
    return /^\d{4}$/.test(text) && numeric >= minYear && numeric <= maxYear
      ? {name: text, value: text, vehicle_types: []}
      : null;
  };
  const yearItems = Array.from({length: latestMenuYear - minYear + 1}, (_, index) => ({
    name: String(latestMenuYear - index), value: String(latestMenuYear - index), vehicle_types: [],
  }));
  _ptSetVehicleSearchValue(picker, "year", yearOption(unit.vehicle_identity.model_year));

  const renderPackages = () => {
    const matches = (_PT.vehiclePoliceCatalog || []).filter(item =>
      item.make.toLowerCase() === make.value.toLowerCase() &&
      item.model.toLowerCase() === model.value.toLowerCase() &&
      Boolean(item.package) &&
      _ptPoliceVehicleAvailable(item, year.value)
    );
    packageItems = matches.length ? [
      {name: "Standard / none", value: "", vehicle_types: []},
      ...matches.map(item => ({
        name: item.availability === "upcoming" ? `${item.package} · Upcoming` : item.package,
        value: item.package,
        vehicle_types: item.availability === "upcoming" ? ["Police package", "Upcoming"] : ["Police package"],
      })),
    ] : [];
    packageField.hidden = !packageItems.length;
    packageField.closest(".vehicle-guided-grid")?.classList.toggle("has-police-package", Boolean(packageItems.length));
    if (!packageItems.length) {
      unit.vehicle_identity.package = "";
      _ptSetVehicleSearchValue(picker, "package", null);
      return;
    }
    const selected = packageItems.find(item => item.value === unit.vehicle_identity.package) || packageItems[0];
    _ptSetVehicleSearchValue(picker, "package", selected);
    _ptRenderVehicleSearchMenu(packageSearch, packageItems);
  };

  const loadModels = async () => {
    _ptReadVehiclePicker(row, unit);
    if (!year.value || !make.value) {
      modelItems = [];
      _ptRenderVehicleSearchMenu(modelSearch, [], "Choose a year and make first");
      return [];
    }
    try {
      const modelKey = `${year.value}\u0000${make.value.toLowerCase()}`;
      const items = await _ptCachedVehicleCatalog(
        _PT.vehicleModelRequests,
        modelKey,
        `/api/vehicle-catalog/models?year=${encodeURIComponent(year.value)}&make=${encodeURIComponent(make.value)}`,
      );
      const police = (_PT.vehiclePoliceCatalog || [])
        .filter(item => item.make.toLowerCase() === make.value.toLowerCase() && _ptPoliceVehicleAvailable(item, year.value))
        .map(item => ({
          name: item.model, id: "", is_specialty: false,
          vehicle_types: /f-?150|silverado|ram/i.test(item.model) ? ["Truck"] : ["SUV / MPV"],
        }));
      // Put maintained police entries first so their canonical model name wins
      // when vPIC returns the same model with all-uppercase display text.
      modelItems = [...police, ...items].filter((item, index, all) =>
        all.findIndex(other => other.name.toLowerCase() === item.name.toLowerCase()) === index
      );
      const selected = modelItems.find(item => item.name.toLowerCase() === unit.vehicle_identity.model.toLowerCase()) ||
        (picker.dataset.vehicleDirty !== "true" && unit.vehicle_identity.model ? {
          name: unit.vehicle_identity.model,
          id: unit.vehicle_identity.catalog_model_id || "",
          vehicle_types: [],
        } : null);
      _ptSetVehicleSearchValue(picker, "model", selected);
      _ptRenderVehicleSearchMenu(modelSearch, modelItems);
      renderPackages();
      return modelItems;
    } catch (_) {
      status.className = "vehicle-layout-status warning";
      status.textContent = "Online model list unavailable — try again or use a custom vehicle";
      return [];
    }
  };

  const fetchMakes = async (query = "") => {
    if (!year.value) return [];
    const suffix = query ? `&query=${encodeURIComponent(query)}` : "";
    const makeKey = `${year.value}\u0000${String(query || "").toLowerCase()}`;
    return _ptCachedVehicleCatalog(
      _PT.vehicleMakeRequests,
      makeKey,
      `/api/vehicle-catalog/makes?year=${encodeURIComponent(year.value)}${suffix}`,
    );
  };

  const loadMakes = async () => {
    if (!year.value) return [];
    try {
      const items = await fetchMakes("");
      const selected = items.find(item => item.name.toLowerCase() === unit.vehicle_identity.make.toLowerCase()) ||
        (picker.dataset.vehicleDirty !== "true" && unit.vehicle_identity.make ? {
          name: unit.vehicle_identity.make,
          id: unit.vehicle_identity.catalog_make_id || "",
          vehicle_types: [],
        } : null);
      _ptSetVehicleSearchValue(picker, "make", selected);
      if (!selected) {
        unit.vehicle_identity.make = "";
        unit.vehicle_identity.model = "";
        unit.vehicle_identity.package = "";
        _ptSetVehicleSearchValue(picker, "model", null);
      }
      _ptRenderVehicleSearchMenu(makeSearch, items);
      await loadModels();
      return items;
    } catch (_) {
      status.className = "vehicle-layout-status warning";
      status.textContent = "Online make list unavailable — try again or use a custom vehicle";
      return [];
    }
  };

  try {
    if (!_PT.vehiclePoliceCatalog) _PT.vehiclePoliceCatalog = await _ptVehicleCatalog("/api/vehicle-catalog/police");
  } catch (_) { _PT.vehiclePoliceCatalog = []; }

  _ptWireVehicleSearch(yearSearch, async query => {
    const folded = String(query || "").trim();
    if (!folded) return yearItems;
    const matches = yearItems.filter(item => item.name.includes(folded));
    const typedYear = yearOption(folded);
    return typedYear && !matches.some(item => item.value === typedYear.value)
      ? [typedYear, ...matches]
      : matches;
  }, () => _ptClearVehicleSearchSelection(yearSearch));

  _ptWireVehicleSearch(makeSearch, fetchMakes, () => {
    _ptClearVehicleSearchSelection(makeSearch);
    _ptClearVehicleSearchSelection(modelSearch);
    modelSearch.querySelector(".vehicle-search-input").value = "";
  });
  _ptWireVehicleSearch(modelSearch, async query => {
    const folded = String(query || "").trim().toLowerCase();
    return folded ? modelItems.filter(item => item.name.toLowerCase().includes(folded)) : modelItems;
  }, () => {
    _ptClearVehicleSearchSelection(modelSearch);
  });
  _ptWireVehicleSearch(packageSearch, async query => {
    const folded = String(query || "").trim().toLowerCase();
    return folded ? packageItems.filter(item => item.name.toLowerCase().includes(folded)) : packageItems;
  }, () => _ptClearVehicleSearchSelection(packageSearch));

  picker.querySelectorAll("[data-vehicle-mode]").forEach(button => button.addEventListener("click", async () => {
    picker.dataset.vehicleDirty = "true";
    const mode = button.dataset.vehicleMode;
    const custom = mode === "custom";
    const unknown = mode === "unknown";
    const previousSource = unit.vehicle_identity.source;
    picker.querySelectorAll("[data-vehicle-mode]").forEach(tab => tab.classList.toggle("active", tab === button));
    picker.querySelector(".vehicle-picker-catalog").hidden = custom || unknown;
    picker.querySelector(".vehicle-picker-custom").hidden = !custom;
    picker.querySelector(".vehicle-picker-unknown").hidden = !unknown;
    _ptReadVehiclePicker(row, unit);
    if (custom) await _ptResolveVehicleLayout(row, unit);
    else if (unknown) await _ptResolveVehicleLayout(row, unit);
    else if (mode === "catalog") {
      if (previousSource === "unknown") {
        unit.vehicle_identity = {
          ...unit.vehicle_identity, source: "catalog", model_year: "", make: "", model: "",
          package: "", catalog_source: "NHTSA vPIC", catalog_make_id: "",
          catalog_model_id: "", layout_id: "", display_name: "",
        };
        _ptSetVehicleSearchValue(picker, "year", null);
        _ptSetVehicleSearchValue(picker, "make", null);
        _ptSetVehicleSearchValue(picker, "model", null);
      }
      await _ptResolveVehicleLayout(row, unit);
    }
  }));

  picker.querySelectorAll("[data-police-quick]").forEach(button => button.addEventListener("click", async () => {
    picker.dataset.vehicleDirty = "true";
    const [selectedMake, selectedModel, selectedPackage] = button.dataset.policeQuick.split("|");
    const quickEntry = (_PT.vehiclePoliceCatalog || []).find(item =>
      item.make === selectedMake && item.model === selectedModel && item.package === selectedPackage
    );
    if (!quickEntry) return;
    try {
      let quickYear = year.value;
      if (!_ptPoliceVehicleAvailable(quickEntry, quickYear)) {
        const currentYear = new Date().getFullYear();
        quickYear = String(Math.min(
          Math.max(currentYear, Number(quickEntry.from_year)),
          Number(quickEntry.to_year || quickEntry.from_year),
        ));
      }
      const selectedYearOption = yearOption(quickYear);
      if (!selectedYearOption) throw new Error("Enter a model year from 1995 through 2040");
      if (!_ptPoliceVehicleAvailable(quickEntry, selectedYearOption.value)) {
        throw new Error(`${quickEntry.model} is not available for ${quickYear}`);
      }
      const quickType = /f-?150|silverado|ram/i.test(quickEntry.model) ? "Truck" : "SUV / MPV";
      const makeOption = {name: quickEntry.make, id: "", vehicle_types: [quickType]};
      const modelOption = {name: quickEntry.model, id: "", vehicle_types: [quickType]};

      // Quick choices are entries from the already-loaded police
      // catalog. Applying those option objects is immediate and requires no
      // external catalog request.
      _ptSetVehicleSearchValue(picker, "year", selectedYearOption);
      _ptSetVehicleSearchValue(picker, "make", makeOption);
      _ptSetVehicleSearchValue(picker, "model", modelOption);
      unit.vehicle_identity = {
        ...unit.vehicle_identity, source: "catalog", model_year: selectedYearOption.value,
        make: makeOption.name, model: modelOption.name, package: "",
        category: "automobile", catalog_source: "NHTSA vPIC",
        catalog_make_id: "", catalog_model_id: "",
      };
      renderPackages();

      if (selectedPackage) {
        const packageOption = packageItems.find(item => item.value === selectedPackage);
        if (!packageOption) throw new Error(`${selectedPackage} is not available for ${quickYear}`);
        _ptSetVehicleSearchValue(picker, "package", packageOption);
        unit.vehicle_identity.package = packageOption.value;
      }
      _ptReadVehiclePicker(row, unit);
      await _ptResolveVehicleLayout(row, unit);
    } catch (error) {
      status.className = "vehicle-layout-status warning";
      status.textContent = error?.message || "That quick choice is temporarily unavailable";
    }
  }));
  year.addEventListener("change", () => {
    picker.dataset.vehicleDirty = "true";
    loadMakes();
  });
  make.addEventListener("change", () => {
    picker.dataset.vehicleDirty = "true";
    unit.vehicle_identity.make = make.value;
    unit.vehicle_identity.model = "";
    unit.vehicle_identity.package = "";
    _ptSetVehicleSearchValue(picker, "model", null);
    loadModels();
  });
  model.addEventListener("change", async () => {
    picker.dataset.vehicleDirty = "true";
    renderPackages();
    _ptReadVehiclePicker(row, unit);
    await _ptResolveVehicleLayout(row, unit);
  });
  packageSelect.addEventListener("change", async () => {
    picker.dataset.vehicleDirty = "true";
    _ptReadVehiclePicker(row, unit);
    await _ptResolveVehicleLayout(row, unit);
  });
  picker.querySelector(".vehicle-category")?.addEventListener("change", () => {
    picker.dataset.vehicleDirty = "true";
    _ptReadVehiclePicker(row, unit);
  });
  picker.querySelector(".vehicle-custom-name")?.addEventListener("change", async () => {
    picker.dataset.vehicleDirty = "true";
    _ptReadVehiclePicker(row, unit);
    await _ptResolveVehicleLayout(row, unit);
  });
  if (unit.vehicle_identity.source !== "unknown") await loadMakes();
  await _ptResolveVehicleLayout(row, unit);
}
