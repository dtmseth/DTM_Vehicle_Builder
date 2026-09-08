// ── Projects module: create an artwork-pending vehicle while selecting ───────

function _ptCloseProjectVehicleCreate() {
  const modal = $("project-vehicle-create-modal");
  modal?.classList.remove("open");
  if (modal) modal.hidden = true;
  _PT.vehicleCreateTarget = null;
}

function _ptSelectCreatedVehicle(vehicleId) {
  const target = _PT.vehicleCreateTarget;
  if (!target) return;
  const units = target.editor === "detail" ? _PT.editTabUnits : _PT.units;
  const unit = units.find(item => item.uid === target.uid);
  if (!unit) return;
  unit.vehicle_model = vehicleId;
  if (unit.preset_id && !_ptCompatiblePresets(unit).some(preset => preset.preset_id === unit.preset_id)) {
    unit.preset_id = "";
  }
  if (target.editor === "detail") _ptRenderEditUnits();
  else _ptRenderUnits();
}

window.PT_openProjectVehicleCreate = function (uid, editor) {
  if (editor === "detail") _ptCollectEditUnits();
  else _ptCollectUnits();
  _PT.vehicleCreateTarget = { uid, editor: editor === "detail" ? "detail" : "wizard" };
  $("project-vehicle-create-make").value = "";
  $("project-vehicle-create-model").value = "";
  $("project-vehicle-create-status").hidden = true;
  const modal = $("project-vehicle-create-modal");
  modal.hidden = false;
  modal.classList.add("open");
  requestAnimationFrame(() => $("project-vehicle-create-make")?.focus());
};

async function _ptCreateProjectVehicle() {
  const make = $("project-vehicle-create-make").value.trim();
  const model = $("project-vehicle-create-model").value.trim();
  const status = $("project-vehicle-create-status");
  const button = $("project-vehicle-create-save");
  if (!make || !model) {
    status.textContent = "Enter both a make and model.";
    status.hidden = false;
    return;
  }

  button.disabled = true;
  button.textContent = "Adding…";
  status.textContent = "Creating the vehicle…";
  status.hidden = false;
  try {
    const result = await api("/api/layouts/vehicles/create", { make, model });
    if (!result?.ok) {
      status.textContent = result?.error || "The vehicle could not be added.";
      return;
    }
    const vehicleId = result.vehicle_id;
    _PT.vehicleMap[vehicleId] = result.vehicle || { make, model, placeholder: true };
    _PT.vehicles = Object.keys(_PT.vehicleMap).sort();
    if (typeof _layouts !== "undefined" && _layouts?.vehicles) {
      _layouts.vehicles[vehicleId] = result.vehicle || { make, model, placeholder: true };
    }
    _ptSelectCreatedVehicle(vehicleId);
    toast(
      result.created ? `${make} ${model} added with artwork pending` : `${make} ${model} already existed and was selected`,
      "success",
    );
    _ptCloseProjectVehicleCreate();
  } catch (error) {
    console.error("Project vehicle creation failed", error);
    status.textContent = error?.message || "The vehicle could not be added.";
  } finally {
    button.disabled = false;
    button.textContent = "Add Vehicle";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const modal = $("project-vehicle-create-modal");
  $("project-vehicle-create-form")?.addEventListener("submit", event => {
    event.preventDefault();
    _ptCreateProjectVehicle();
  });
  $("project-vehicle-create-close")?.addEventListener("click", _ptCloseProjectVehicleCreate);
  $("project-vehicle-create-cancel")?.addEventListener("click", _ptCloseProjectVehicleCreate);
  modal?.addEventListener("click", event => {
    if (event.target === modal) _ptCloseProjectVehicleCreate();
  });
});
