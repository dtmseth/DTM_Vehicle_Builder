// ═══════════════════════════════════════════════════════
// VEHICLES TAB
// ═══════════════════════════════════════════════════════
const VIEWS_ORDER=["front","side","top","rear"];
const _vehicleUploadedImages={};  // view → {filename, b64}

function initVehiclesTab(){
  buildVehiclePresetOptions();
  renderVehicleCards();
  buildVehicleImgUploadGrid();
}

function buildVehiclePresetOptions(){
  const sel=$("vehicle-preset");
  if(!sel) return;
  const vehicles=Object.keys(_layouts?.vehicles||{});
  const current=sel.value;
  sel.innerHTML=`<option value="">Start Empty</option>`+
    vehicles.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join("");
  if(current==="" || vehicles.includes(current)) sel.value=current;
  else if(vehicles.includes("PIU")) sel.value="PIU";
}

function renderVehicleCards(){
  const vehicles=_layouts?.vehicles||{};
  $("vehicle-cards").innerHTML=Object.entries(vehicles).map(([id,v])=>{
    const viewCount=Object.keys(v.views||{}).length;
    const locCount=Object.values(v.views||{}).reduce((a,view)=>a+Object.keys(view.locations||{}).length,0);
    return `<div class="vehicle-card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div class="vc-name">${esc(id)}</div>
        <button class="btn btn-danger btn-sm vehicle-delete-btn" data-vehicle="${esc(id)}">Delete</button>
      </div>
      <div class="vc-views">${viewCount} view${viewCount!==1?"s":""} · ${locCount} locations</div>
    </div>`;
  }).join("");
  $("vehicle-cards").querySelectorAll(".vehicle-delete-btn").forEach(btn=>{
    btn.addEventListener("click",()=>deleteVehicleType(btn.dataset.vehicle));
  });
}

function blankVehicleLayout(){
  return {
    views:{
      front:{coord_space:"relative_image",side_roles:{negative_x:"passenger",positive_x:"driver"},locations:{}},
      side:{coord_space:"relative_image",default_slot_role:"driver",locations:{}},
      top:{coord_space:"relative_image",locations:{}},
      rear:{coord_space:"relative_image",side_roles:{negative_x:"driver",positive_x:"passenger"},locations:{}},
    }
  };
}

function cloneVehiclePreset(presetId){
  const source=_layouts?.vehicles?.[presetId];
  return source ? JSON.parse(JSON.stringify(source)) : blankVehicleLayout();
}

async function deleteVehicleType(vehicleId){
  const vehicles=Object.keys(_layouts?.vehicles||{});
  if(vehicles.length<=1){toast("At least one vehicle type must remain","error");return;}
  if(!confirm(`Delete vehicle type "${vehicleId}"?`)) return;

  try{
    await Promise.all(
      VIEWS_ORDER.map(view=>api("/api/assets/delete",{folder:"vehicles",filename:`${vehicleId}_${view}.png`}))
    );
    delete _layouts.vehicles[vehicleId];
    const res=await apiSave("/api/layouts/save",_layouts);
    if(!res.ok) throw new Error(res.error);

    if(_activeVehicle===vehicleId){
      _activeVehicle=Object.keys(_layouts.vehicles)[0]||"";
      _selectedLocKey=null;
      hide("loc-edit-panel");
      show("loc-empty-hint");
      renderLocationList();
      loadVehicleCanvas();
    }

    if($("vehicle-preset").value===vehicleId) $("vehicle-preset").value="";
    refreshSharedUi();
    toast(`${vehicleId} deleted`,"success");
  }catch(err){
    toast("Delete failed: "+err,"error");
  }
}

function buildVehicleImgUploadGrid(){
  $("vehicle-img-grid").innerHTML=VIEWS_ORDER.map(view=>{
    return `<div class="upload-zone ${_vehicleUploadedImages[view]?"has-file":""}" id="vuz-${view}">
      <input type="file" accept="image/*" data-view="${view}" class="vuz-input" />
      <div class="uz-icon">🖼️</div>
      <div class="uz-label">${view.charAt(0).toUpperCase()+view.slice(1)}</div>
      <div class="uz-hint">PNG recommended</div>
      <img class="uz-thumb" id="vuz-prev-${view}" ${_vehicleUploadedImages[view]?`src="${_vehicleUploadedImages[view].dataUrl}" style="display:block"`:""}/>
    </div>`;
  }).join("");
  $("vehicle-img-grid").querySelectorAll(".vuz-input").forEach(inp=>{
    inp.addEventListener("change",e=>{
      const file=e.target.files[0]; if(!file)return;
      const view=e.target.dataset.view;
      const vid=$("new-vehicle-id").value.trim().toUpperCase()||"VEHICLE";
      const reader=new FileReader();
      reader.onload=ev=>{
        const b64=ev.target.result.split(",")[1];
        _vehicleUploadedImages[view]={filename:`${vid}_${view}.${file.name.split(".").pop()}`,b64,dataUrl:ev.target.result};
        const prev=$(`vuz-prev-${view}`); prev.src=ev.target.result; prev.style.display="block";
        $(`vuz-${view}`).classList.add("has-file");
      };
      reader.readAsDataURL(file);
    });
  });
}

// Auto-update filenames when the vehicle ID changes
$("new-vehicle-id").addEventListener("blur",()=>buildVehicleImgUploadGrid());

$("btn-create-vehicle").addEventListener("click", async()=>{
  const vid=$("new-vehicle-id").value.trim().toUpperCase();
  if(!vid){toast("Vehicle ID is required","error");return;}
  if(_layouts.vehicles[vid]){toast(`${vid} already exists`,"error");return;}
  const presetId=$("vehicle-preset").value.trim();

  const btn=$("btn-create-vehicle"); btn.disabled=true; btn.textContent="Creating…";
  try{
    // Upload any images
    for(const [view,img] of Object.entries(_vehicleUploadedImages)){
      const res=await api("/api/assets/upload",{folder:"vehicles",filename:`${vid}_${view}.png`,data:img.b64});
      if(!res.ok) throw new Error("Image upload failed: "+res.error);
    }
    // Add vehicle to layouts
    _layouts.vehicles[vid]=cloneVehiclePreset(presetId);
    const res=await apiSave("/api/layouts/save",_layouts);
    if(!res.ok) throw new Error(res.error);

    toast(`${vid} created!`,"success");
    $("new-vehicle-id").value="";
    $("vehicle-preset").value=Object.keys(_layouts.vehicles).includes("PIU")?"PIU":"";
    Object.keys(_vehicleUploadedImages).forEach(k=>delete _vehicleUploadedImages[k]);
    buildVehicleImgUploadGrid();
    refreshSharedUi();
  }catch(err){toast("Error: "+err,"error");}
  btn.disabled=false; btn.textContent="+ Create Vehicle Type";
});
