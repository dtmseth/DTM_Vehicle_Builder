// ═══════════════════════════════════════════════════════
// PLACEMENTS
// ═══════════════════════════════════════════════════════
const CW=700, CH=460;  // canvas logical pixels

function populateVehicleSelector(){
  const sel=$("vehicle-selector");
  const vehicles=Object.keys(_layouts?.vehicles||{});
  if(!_activeVehicle || !vehicles.includes(_activeVehicle)) _activeVehicle=vehicles[0]||"";
  sel.innerHTML=vehicles.map(v=>`<option value="${esc(v)}" ${v===_activeVehicle?"selected":""}>${esc(v)}</option>`).join("");
  sel.onchange=e=>{_activeVehicle=e.target.value; _selectedLocKey=null; hide("loc-edit-panel"); show("loc-empty-hint"); renderLocationList(); loadVehicleCanvas();};
}

function getViewLocations(){
  return _layouts?.vehicles?.[_activeVehicle]?.views?.[_activeView]?.locations || {};
}
function setViewLocations(locs){
  if(!_layouts.vehicles[_activeVehicle]?.views?.[_activeView]) return;
  _layouts.vehicles[_activeVehicle].views[_activeView].locations=locs;
  _locsDirty=true; $("placements-dirty-dot").style.display="inline-block";
}

function allKnownLocationNames(){
  const all=new Set();
  Object.values(_layouts?.vehicles||{}).forEach(v=>
    Object.values(v.views||{}).forEach(view=>
      Object.keys(view.locations||{}).forEach(loc=>all.add(loc))
    )
  );
  Object.values(_workbookRules?.part_rules||{}).forEach(rule=>
    (rule.locations||[]).forEach(loc=>all.add(loc))
  );
  return [...all].sort();
}

function allWorkbookPartTypeNames(){
  const names=[];
  const seen=new Set();
  (_workbookRules?.template_sections||[]).forEach(section=>{
    (section.parts||[]).forEach(part=>{
      const name=(part?.name||"").trim();
      if(name&&!seen.has(name)){
        seen.add(name);
        names.push(name);
      }
    });
  });
  return names;
}

function initPlacements(){
  document.querySelectorAll(".view-pill").forEach(p=>{
    p.addEventListener("click",()=>{
      document.querySelectorAll(".view-pill").forEach(x=>x.classList.remove("active"));
      p.classList.add("active"); _activeView=p.dataset.view;
      _selectedLocKey=null; hide("loc-edit-panel"); show("loc-empty-hint");
      renderLocationList(); loadVehicleCanvas();
    });
  });
  renderLocationList();
  loadVehicleCanvas();
}

let _vehicleImg=new Image(), _imgLoaded=false;

function loadVehicleCanvas(){
  const canvas=$("vehicle-canvas");
  const ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,CW,CH); ctx.fillStyle="#f0f2fa"; ctx.fillRect(0,0,CW,CH);
  _imgLoaded=false;
  _vehicleImg=new Image();
  _vehicleImg.onload=()=>{_imgLoaded=true; drawCanvas();};
  _vehicleImg.onerror=()=>{
    ctx.fillStyle="#eef0f6"; ctx.fillRect(0,0,CW,CH);
    ctx.fillStyle="#aab"; ctx.font="14px sans-serif"; ctx.textAlign="center";
    ctx.fillText(`No image: assets/vehicles/${_activeVehicle}_${_activeView}.png`, CW/2, CH/2);
    drawDots(ctx,[0,0,CW,CH]);
  };
  _vehicleImg.src=`/assets/vehicles/${_activeVehicle}_${_activeView}.png`;

  canvas.onclick=e=>{
    if(!_selectedLocKey)return;
    const rect=canvas.getBoundingClientRect();
    const scaleX=CW/rect.width, scaleY=CH/rect.height;
    const px=(e.clientX-rect.left)*scaleX, py=(e.clientY-rect.top)*scaleY;
    const box=getImageBox();
    const x=Math.round(((px-box[0])/box[2])*1000)/1000;
    const y=Math.round(((py-box[1])/box[3])*1000)/1000;
    updateLocCoord(_selectedLocKey,"x",Math.max(0,Math.min(1,x)));
    updateLocCoord(_selectedLocKey,"y",Math.max(0,Math.min(1,y)));
    syncEditPanel(); renderLocationList(); drawCanvas();
  };
}

function getImageBox(){
  if(!_imgLoaded||!_vehicleImg.naturalWidth) return [0,0,CW,CH];
  const iw=_vehicleImg.naturalWidth, ih=_vehicleImg.naturalHeight;
  const scale=Math.min(CW/iw, CH/ih);
  const dw=iw*scale, dh=ih*scale;
  return [(CW-dw)/2, (CH-dh)/2, dw, dh];
}

function drawCanvas(){
  const canvas=$("vehicle-canvas"), ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,CW,CH); ctx.fillStyle="#f0f2fa"; ctx.fillRect(0,0,CW,CH);
  const box=getImageBox();
  if(_imgLoaded) ctx.drawImage(_vehicleImg,box[0],box[1],box[2],box[3]);
  drawDots(ctx,box);
}

function drawDots(ctx, box){
  const locs=getViewLocations();
  Object.entries(locs).forEach(([name,loc])=>{
    const selected=(name===_selectedLocKey);
    const positions=getSlotPositions(loc, box);
    const baseRot=loc.rotation||0;
    const isMirror=(loc.pattern||"single")==="mirror";
    positions.forEach(([cx,cy],idx)=>{
      const rot=isMirror&&idx%2===1?((360-baseRot)%360):baseRot;
      const r=selected?7:4;
      ctx.beginPath();
      ctx.arc(cx,cy,r,0,Math.PI*2);
      ctx.fillStyle=selected?"#C8A951":"rgba(30,39,97,0.72)";
      ctx.fill();
      ctx.strokeStyle="#fff"; ctx.lineWidth=1.5; ctx.stroke();
      // rotation indicator: X where horizontal arm is longer
      const rad=rot*Math.PI/180;
      const longArm=r+5, shortArm=r+1;
      ctx.strokeStyle=selected?"#C8A951":"rgba(255,255,255,0.9)";
      ctx.lineWidth=selected?2:1.5;
      // horizontal arm (rotation axis)
      ctx.beginPath();
      ctx.moveTo(cx+Math.cos(rad)*longArm, cy+Math.sin(rad)*longArm);
      ctx.lineTo(cx-Math.cos(rad)*longArm, cy-Math.sin(rad)*longArm);
      ctx.stroke();
      // vertical arm (shorter, perpendicular)
      ctx.beginPath();
      ctx.moveTo(cx+Math.cos(rad+Math.PI/2)*shortArm, cy+Math.sin(rad+Math.PI/2)*shortArm);
      ctx.lineTo(cx-Math.cos(rad+Math.PI/2)*shortArm, cy-Math.sin(rad+Math.PI/2)*shortArm);
      ctx.stroke();
      // small index numbers on multi-slot
      if(positions.length>1){
        ctx.fillStyle=selected?"#1E2761":"#fff";
        ctx.font="bold 8px sans-serif"; ctx.textAlign="center";
        ctx.fillText(idx+1, cx, cy+3);
      }
    });
    if(selected && positions.length){
      const [cx,cy]=positions[Math.floor(positions.length/2)];
      ctx.fillStyle="rgba(255,255,255,0.93)";
      ctx.font="bold 10px sans-serif"; ctx.textAlign="center";
      const label=name.length>18?name.slice(0,17)+"…":name;
      ctx.fillText(label, cx, cy-12);
    }
  });
}

function renderLocationList(){
  const locs=getViewLocations();
  $("location-list").innerHTML=Object.entries(locs).map(([name,loc])=>{
    const sc=loc.slot_count||1, pat=loc.pattern||"single";
    const countHint=sc>1?` ×${sc}`:"";
    return `<div class="location-row ${name===_selectedLocKey?"selected":""}" data-key="${esc(name)}">
      <div class="loc-name" title="${esc(name)}">${esc(name)}</div>
      <div class="loc-coords">${loc.x.toFixed(2)},${loc.y.toFixed(2)}${countHint}</div>
    </div>`;
  }).join("");
  $("location-list").querySelectorAll(".location-row").forEach(row=>{
    row.addEventListener("click",()=>{
      _selectedLocKey=row.dataset.key;
      renderLocationList(); showEditPanel(_selectedLocKey);
      hide("loc-empty-hint"); show("loc-edit-panel");
      drawCanvas();
    });
  });
}

function showEditPanel(key){
  const loc=getViewLocations()[key]; if(!loc)return;
  $("loc-edit-title").textContent=key;
  $("loc-name-input").value=key;
  $("loc-x-range").value=loc.x; $("loc-x-num").value=loc.x;
  $("loc-y-range").value=loc.y; $("loc-y-num").value=loc.y;
  $("loc-orient").value=loc.orientation||"h";
  $("loc-pattern").value=loc.pattern||"single";
  $("loc-slots").value=loc.slot_count||1;
  // h_spacing with legacy spacing fallback
  const hsp=loc.h_spacing??loc.spacing??0;
  $("loc-spacing-range").value=hsp; $("loc-spacing-num").value=hsp;
  const vsp=loc.v_spacing??0;
  $("loc-vspacing-range").value=vsp; $("loc-vspacing-num").value=vsp;
  // new geometry fields
  const rot=loc.rotation??0;
  $("loc-rotation").value=rot; $("loc-rotation-preset").value="";
  $("loc-flip-h").checked=!!loc.flip_h;
  $("loc-flip-v").checked=!!loc.flip_v;
  $("loc-flip-mirrored-h").checked=!!loc.flip_mirrored_h;
  $("loc-behind-vehicle").checked=!!loc.behind_vehicle;
  $("loc-layer").value=loc.layer??0;
  updateSpacingRowVisibility(loc.pattern||"single", loc.slot_count||1);
  renderLocUsedBy(key);
}

function renderLocUsedBy(key){
  if(!key) return;
  const users=Object.entries(_workbookRules?.part_rules||{})
    .filter(([,rule])=>(rule.locations||[]).includes(key))
    .map(([name])=>name);
  const list=$("loc-used-by-list");
  if(users.length){
    list.innerHTML=users.map(n=>`<span class="loc-used-pill">
      ${esc(n)}<button type="button" class="pill-remove" data-part="${esc(n)}" title="Remove">×</button>
    </span>`).join("");
  } else {
    list.innerHTML=`<span style="color:var(--muted);font-size:12px;font-style:italic">None</span>`;
  }
  const allTypes=allWorkbookPartTypeNames();
  const available=allTypes.filter(n=>!users.includes(n));
  const addRow=$("loc-used-by-add");
  const sel=$("loc-used-by-select");
  if(available.length){
    sel.innerHTML=available.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join("");
    addRow.hidden=false;
  } else {
    addRow.hidden=true;
  }
}

$("loc-used-by-list").addEventListener("click", async e=>{
  const btn=e.target.closest(".pill-remove"); if(!btn) return;
  const partName=btn.dataset.part;
  const key=_selectedLocKey; if(!key||!partName) return;
  if(!confirm(`Remove "${key}" from "${partName}"?`)) return;
  if(!_workbookRules?.part_rules?.[partName]) return;
  _workbookRules.part_rules[partName].locations=
    (_workbookRules.part_rules[partName].locations||[]).filter(l=>l!==key);
  const res=await apiSave("/api/workbook-rules/save",_workbookRules);
  if(!res.ok){ toast("Save failed: "+res.error,"error"); return; }
  renderLocUsedBy(key);
  toast(`Removed from "${partName}"`,"success");
});

$("loc-used-by-btn-add").addEventListener("click", async()=>{
  const key=_selectedLocKey; if(!key) return;
  const partName=$("loc-used-by-select").value; if(!partName) return;
  if(!_workbookRules.part_rules) _workbookRules.part_rules={};
  if(!_workbookRules.part_rules[partName]) _workbookRules.part_rules[partName]={};
  const existing=_workbookRules.part_rules[partName].locations||[];
  if(!existing.includes(key)){
    _workbookRules.part_rules[partName].locations=[...existing,key];
    const res=await apiSave("/api/workbook-rules/save",_workbookRules);
    if(!res.ok){ toast("Save failed: "+res.error,"error"); return; }
  }
  renderLocUsedBy(key);
  toast(`Added to "${partName}"`,"success");
});

function updateSpacingRowVisibility(pattern, slots){
  const showH = pattern === "mirror" && slots > 2;
  const showV=(pattern==="vertical"&&slots>1);
  $("loc-spacing-row").hidden=!showH;
  $("loc-vspacing-row").hidden=!showV;
}

function syncEditPanel(){
  const loc=getViewLocations()[_selectedLocKey]; if(!loc)return;
  $("loc-x-range").value=loc.x; $("loc-x-num").value=loc.x;
  $("loc-y-range").value=loc.y; $("loc-y-num").value=loc.y;
}

function updateLocCoord(key,axis,value){
  const locs=getViewLocations();
  if(locs[key]){locs[key][axis]=value; setViewLocations(locs);}
}

["x","y"].forEach(axis=>{
  $(`loc-${axis}-range`).addEventListener("input",e=>{
    const v=parseFloat(e.target.value);
    $(`loc-${axis}-num`).value=v;
    updateLocCoord(_selectedLocKey,axis,v);
    renderLocationList(); drawCanvas();
  });
  $(`loc-${axis}-num`).addEventListener("input",e=>{
    const v=Math.max(0,Math.min(1,parseFloat(e.target.value)||0));
    $(`loc-${axis}-range`).value=v;
    updateLocCoord(_selectedLocKey,axis,v);
    renderLocationList(); drawCanvas();
  });
});

["orient","pattern","slots"].forEach(field=>{
  $(`loc-${field}`).addEventListener("change",e=>{
    const locs=getViewLocations();
    if(!_selectedLocKey||!locs[_selectedLocKey])return;
    const key={"orient":"orientation","pattern":"pattern","slots":"slot_count"}[field];
    locs[_selectedLocKey][key]=field==="slots"?parseInt(e.target.value):e.target.value;
    setViewLocations(locs);
    // Update spacing row visibility whenever pattern or slot count changes
    updateSpacingRowVisibility(locs[_selectedLocKey].pattern||"single", locs[_selectedLocKey].slot_count||1);
    renderLocationList(); drawCanvas();
  });
});

// Spacing slider
$("loc-spacing-range").addEventListener("input",e=>{
  const v=parseFloat(e.target.value);
  $("loc-spacing-num").value=v;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){
    locs[_selectedLocKey].h_spacing=v>0?v:null;
    delete locs[_selectedLocKey].spacing; // remove legacy key
    setViewLocations(locs);
    drawCanvas();
  }
});
$("loc-spacing-num").addEventListener("input",e=>{
  const v=Math.max(0,Math.min(0.30,parseFloat(e.target.value)||0));
  $("loc-spacing-range").value=v;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){
    locs[_selectedLocKey].h_spacing=v>0?v:null;
    delete locs[_selectedLocKey].spacing;
    setViewLocations(locs);
    drawCanvas();
  }
});
$("loc-vspacing-range").addEventListener("input",e=>{
  const v=parseFloat(e.target.value);
  $("loc-vspacing-num").value=v;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){locs[_selectedLocKey].v_spacing=v>0?v:null;setViewLocations(locs);}
});
$("loc-vspacing-num").addEventListener("input",e=>{
  const v=Math.max(0,Math.min(0.30,parseFloat(e.target.value)||0));
  $("loc-vspacing-range").value=v;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){locs[_selectedLocKey].v_spacing=v>0?v:null;setViewLocations(locs);}
});
$("loc-rotation").addEventListener("input",e=>{
  const v=parseFloat(e.target.value)||0;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){locs[_selectedLocKey].rotation=v||undefined;setViewLocations(locs);}
  drawCanvas();
});
$("loc-rotation-preset").addEventListener("change",e=>{
  if(e.target.value==="")return;
  const v=parseFloat(e.target.value);
  $("loc-rotation").value=v;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){locs[_selectedLocKey].rotation=v||undefined;setViewLocations(locs);}
  drawCanvas();
});
["flip-h","flip-v","flip-mirrored-h","behind-vehicle"].forEach(flag=>{
  $(`loc-${flag}`).addEventListener("change",e=>{
    const key=flag.replace(/-/g,"_"); // flip_h, flip_v, flip_mirrored_h, behind_vehicle
    const locs=getViewLocations();
    if(_selectedLocKey&&locs[_selectedLocKey]){
      if(e.target.checked) locs[_selectedLocKey][key]=true;
      else delete locs[_selectedLocKey][key];
      setViewLocations(locs);
    }
    drawCanvas();
  });
});
$("loc-layer").addEventListener("change",e=>{
  const v=parseInt(e.target.value)||0;
  const locs=getViewLocations();
  if(_selectedLocKey&&locs[_selectedLocKey]){
    if(v!==0) locs[_selectedLocKey].layer=v;
    else delete locs[_selectedLocKey].layer;
    setViewLocations(locs);
  }
});

$("loc-name-input").addEventListener("blur",e=>{
  const newName=e.target.value.trim().toUpperCase();
  if(!newName||newName===_selectedLocKey)return;
  const locs=getViewLocations();
  if(!locs[_selectedLocKey])return;
  const rebuilt={};
  Object.entries(locs).forEach(([k,v])=>{rebuilt[k===_selectedLocKey?newName:k]=v;});
  setViewLocations(rebuilt);
  _selectedLocKey=newName;
  renderLocationList(); $("loc-edit-title").textContent=newName;
});

$("btn-add-location").addEventListener("click",()=>{ openAddLocModal(); });

// ─── Add Location Modal ──────────────────────────────────────────────────────
let _almTab="import";

function openAddLocModal(){
  _almTab="import";
  almSwitchTab("import");
  almBuildImportList("");
  almBuildPartTypeList();
  $("alm-new-name").value="";
  $("alm-import-search").value="";
  $("add-loc-modal").classList.add("open");
}

function almSwitchTab(tab){
  _almTab=tab;
  $("alm-tab-import").classList.toggle("active", tab==="import");
  $("alm-tab-create").classList.toggle("active", tab==="create");
  $("alm-panel-import").classList.toggle("active", tab==="import");
  $("alm-panel-create").classList.toggle("active", tab==="create");
  $("alm-confirm").style.display = tab==="create" ? "" : "none";
}

function almBuildImportList(filter){
  const currentLocs=new Set(Object.keys(getViewLocations()));
  let importable=allKnownLocationNames().filter(l=>!currentLocs.has(l));
  if(filter) importable=importable.filter(l=>l.toLowerCase().includes(filter.toLowerCase()));
  const el=$("alm-import-list");
  if(!importable.length){
    el.innerHTML=`<div class="alm-empty">No importable locations found.</div>`;
    return;
  }
  el.innerHTML=importable.map(l=>
    `<div class="alm-import-item" data-loc="${esc(l)}">${esc(l)}</div>`
  ).join("");
  el.querySelectorAll(".alm-import-item").forEach(item=>{
    item.addEventListener("click",()=>almImportLocation(item.dataset.loc));
  });
}

function almFilterImport(val){ almBuildImportList(val); }

function almBuildPartTypeList(){
  const types=allWorkbookPartTypeNames();
  const el=$("alm-pt-list");
  if(!types.length){
    el.innerHTML=`<div class="alm-empty">No part types found.</div>`;
    return;
  }
  el.innerHTML=types.map((name,i)=>`
    <label class="alm-pt-item">
      <input type="checkbox" value="${esc(name)}" id="alm-pt-${i}" />
      ${esc(name)}
    </label>
  `).join("");
}

function almImportLocation(name){
  const locs=getViewLocations();
  if(locs[name]){ toast(`"${name}" already in this view`,"error"); return; }
  locs[name]={x:0.5,y:0.5,units:"relative_image",orientation:"h",slot_count:1,pattern:"single"};
  setViewLocations(locs);
  _selectedLocKey=name;
  renderLocationList(); showEditPanel(name);
  hide("loc-empty-hint"); show("loc-edit-panel"); drawCanvas();
  $("add-loc-modal").classList.remove("open");
  toast(`Imported "${name}"`,"success");
}

$("alm-confirm").addEventListener("click", async()=>{
  const name=$("alm-new-name").value.trim().toUpperCase();
  if(!name){ toast("Enter a location name","error"); return; }
  const locs=getViewLocations();
  if(locs[name]){ toast(`"${name}" already exists in this view`,"error"); return; }

  // 1. Add location to current view
  locs[name]={x:0.5,y:0.5,units:"relative_image",orientation:"h",slot_count:1,pattern:"single"};
  setViewLocations(locs);

  // 2. Assign to checked part types in workbook rules
  const checked=[...$("alm-pt-list").querySelectorAll("input[type=checkbox]:checked")].map(c=>c.value);
  if(checked.length){
    if(!_workbookRules.part_rules) _workbookRules.part_rules={};
    checked.forEach(partLabel=>{
      if(!_workbookRules.part_rules[partLabel]) _workbookRules.part_rules[partLabel]={};
      const existing=_workbookRules.part_rules[partLabel].locations||[];
      if(!existing.includes(name)){
        _workbookRules.part_rules[partLabel].locations=[...existing,name];
      }
    });
  }

  // 3. Save layouts
  const layoutRes=await apiSave("/api/layouts/save",_layouts);
  if(!layoutRes.ok){ toast("Layout save failed: "+layoutRes.error,"error"); return; }

  // 4. Save workbook rules (if any part types were checked)
  if(checked.length){
    const wrRes=await apiSave("/api/workbook-rules/save",_workbookRules);
    if(!wrRes.ok){ toast("Rules save failed: "+wrRes.error,"error"); return; }
  }

  // 5. Close modal, refresh UI, open edit panel
  $("add-loc-modal").classList.remove("open");
  _selectedLocKey=name;
  refreshSharedUi();
  renderLocationList(); showEditPanel(name);
  hide("loc-empty-hint"); show("loc-edit-panel"); drawCanvas();
  toast(`Location "${name}" created!`,"success");
});

$("alm-close").addEventListener("click",()=>$("add-loc-modal").classList.remove("open"));
$("alm-cancel").addEventListener("click",()=>$("add-loc-modal").classList.remove("open"));
$("add-loc-modal").addEventListener("click",e=>{if(e.target===$("add-loc-modal"))$("add-loc-modal").classList.remove("open");});

$("btn-delete-location").addEventListener("click",()=>{
  if(!_selectedLocKey||!confirm(`Delete "${_selectedLocKey}"?`))return;
  const locs=getViewLocations();
  delete locs[_selectedLocKey]; setViewLocations(locs);
  _selectedLocKey=null; hide("loc-edit-panel"); show("loc-empty-hint");
  renderLocationList(); drawCanvas();
  const listEl=$("location-list");
  listEl.scrollTop=Math.min(listEl.scrollTop, Math.max(0, listEl.scrollHeight-listEl.clientHeight));
});

$("btn-save-layouts").addEventListener("click", async()=>{
  const res=await apiSave("/api/layouts/save",_layouts);
  if(res.ok){_locsDirty=false; $("placements-dirty-dot").style.display="none"; refreshSharedUi(); toast("Layout saved!","success");}
  else toast("Save failed: "+res.error,"error");
});
