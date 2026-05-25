// ═══════════════════════════════════════════════════════
// FIXTURES EDITOR
// ═══════════════════════════════════════════════════════
let _fixtureVehicle="", _fixtureView="front", _selectedFixtureId=null, _fixturesDirty=false, _fixtureLoading=false;
let _fixtureVehicleImg=new Image(), _fixtureImgLoaded=false;

function getFixtureParts(){
  // Parts with is_fixture:true from catalog
  const catalogFixtures=(_catalog?.parts||[]).filter(p=>p.is_fixture);
  const catalogIds=new Set(catalogFixtures.map(p=>p.part_id));
  // Also include any parts already in the vehicle's fixtures map (even if not is_fixture)
  const fixtureMap=getVehicleFixtures();
  const extraParts=Object.keys(fixtureMap).filter(id=>!catalogIds.has(id)).map(id=>{
    const catalogPart=(_catalog?.parts||[]).find(p=>p.part_id===id);
    return {part_id:id, display_name:catalogPart?.display_name||id};
  });
  return [...catalogFixtures,...extraParts];
}

function getVehicleFixtures(){
  return _layouts?.vehicles?.[_fixtureVehicle]?.fixtures || {};
}

function getFixtureEntry(partId){
  return getVehicleFixtures()[partId]?.[_fixtureView] || null;
}

function setFixtureEntry(partId, entry){
  if(!_layouts.vehicles[_fixtureVehicle]) return;
  if(!_layouts.vehicles[_fixtureVehicle].fixtures) _layouts.vehicles[_fixtureVehicle].fixtures={};
  if(!_layouts.vehicles[_fixtureVehicle].fixtures[partId]) _layouts.vehicles[_fixtureVehicle].fixtures[partId]={};
  _layouts.vehicles[_fixtureVehicle].fixtures[partId][_fixtureView]=entry;
  _fixturesDirty=true;
  $("fixtures-dirty-dot").style.display="inline-block";
}

function populateFixtureVehicleSelector(){
  const sel=$("fixture-vehicle-selector");
  const vehicles=Object.keys(_layouts?.vehicles||{});
  if(!_fixtureVehicle||!vehicles.includes(_fixtureVehicle)) _fixtureVehicle=vehicles[0]||"";
  sel.innerHTML=vehicles.map(v=>`<option value="${esc(v)}" ${v===_fixtureVehicle?"selected":""}>${esc(v)}</option>`).join("");
  sel.onchange=e=>{_fixtureVehicle=e.target.value;_selectedFixtureId=null;renderFixtureList();hide("fixture-edit-panel");show("fixture-empty-hint");loadFixtureCanvas();};
}

function renderFixtureList(){
  const parts=getFixtureParts();
  const fixtures=getVehicleFixtures();
  $("fixture-list").innerHTML=parts.map(p=>{
    const hasEntry=!!(fixtures[p.part_id]?.[_fixtureView]);
    return `<div class="location-row ${p.part_id===_selectedFixtureId?"selected":""}" data-id="${esc(p.part_id)}">
      <div class="loc-name" title="${esc(p.display_name)}">${esc(p.display_name)}</div>
      <div class="loc-coords" style="color:${hasEntry?"var(--navy)":"var(--muted)"}">${hasEntry?"configured":"not set"}</div>
    </div>`;
  }).join("");
  $("fixture-list").querySelectorAll(".location-row").forEach(row=>{
    row.addEventListener("click",()=>{
      _selectedFixtureId=row.dataset.id;
      renderFixtureList(); showFixtureEditPanel(_selectedFixtureId);
      hide("fixture-empty-hint"); show("fixture-edit-panel");
      drawFixtureCanvas();
    });
  });
}

function updateFixtureSpacingRows(pattern, slots){
  const showH = pattern === "mirror" && slots > 2;
  const showV=pattern==="vertical"&&slots>1;
  $("fix-hspacing-row").hidden=!showH;
  $("fix-vspacing-row").hidden=!showV;
}

function showFixtureEditPanel(partId){
  const parts=getFixtureParts();
  const p=parts.find(x=>x.part_id===partId); if(!p) return;
  const entry=getFixtureEntry(partId);
  const title=`${p.display_name} — ${_fixtureView}`;
  _fixtureLoading=true;
  $("fixture-edit-title").textContent=title;
  $("fixture-edit-hint").hidden=!!entry;
  const x=entry?.x??0.5, y=entry?.y??0.5;
  $("fix-x-range").value=x; $("fix-x-num").value=x;
  $("fix-y-range").value=y; $("fix-y-num").value=y;
  $("fix-orient").value=entry?.orientation||"h";
  $("fix-pattern").value=entry?.pattern||"single";
  $("fix-slots").value=entry?.slot_count||1;
  const hsp=entry?.h_spacing??entry?.spacing??0;
  $("fix-hsp-range").value=hsp; $("fix-hsp-num").value=hsp;
  const vsp=entry?.v_spacing??0;
  $("fix-vsp-range").value=vsp; $("fix-vsp-num").value=vsp;
  $("fix-rotation").value=entry?.rotation??0;
  $("fix-rotation-preset").value="";
  $("fix-flip-h").checked=!!entry?.flip_h;
  $("fix-flip-v").checked=!!entry?.flip_v;
  $("fix-flip-mirrored-h").checked=!!entry?.flip_mirrored_h;
  $("fix-behind-vehicle").checked=!!entry?.behind_vehicle;
  updateFixtureSpacingRows(entry?.pattern||"single", entry?.slot_count||1);
  _fixtureLoading=false;
}

function _readFixtureEntry(){
  const pat=$("fix-pattern").value, slots=parseInt($("fix-slots").value)||1;
  const entry={
    x:parseFloat($("fix-x-num").value)||0,
    y:parseFloat($("fix-y-num").value)||0,
    units:"relative_image",
    orientation:$("fix-orient").value,
    slot_count:slots,
    pattern:pat,
  };
  const hsp=parseFloat($("fix-hsp-num").value)||0;
  if(hsp>0) entry.h_spacing=hsp;
  const vsp=parseFloat($("fix-vsp-num").value)||0;
  if(vsp>0) entry.v_spacing=vsp;
  const rot=parseFloat($("fix-rotation").value)||0;
  if(rot) entry.rotation=rot;
  // Always write boolean flags so that unchecking overrides any `true` carried in `existing` during the merge
  entry.flip_h=!!$("fix-flip-h").checked;
  entry.flip_v=!!$("fix-flip-v").checked;
  entry.flip_mirrored_h=!!$("fix-flip-mirrored-h").checked;
  entry.behind_vehicle=!!$("fix-behind-vehicle").checked;
  return entry;
}

function _saveCurrentFixture(){
  if(!_selectedFixtureId||_fixtureLoading) return;
  // Merge over the existing entry so fields the UI doesn't expose
  // (h_spacing_units, etc.) are preserved rather than dropped.
  const existing=getVehicleFixtures()[_selectedFixtureId]?.[_fixtureView]||{};
  setFixtureEntry(_selectedFixtureId, {...existing, ..._readFixtureEntry()});
  renderFixtureList();
}

// Fixture canvas
function loadFixtureCanvas(){
  const canvas=$("fixture-canvas"), ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,700,460); ctx.fillStyle="#f0f2fa"; ctx.fillRect(0,0,700,460);
  _fixtureImgLoaded=false;
  _fixtureVehicleImg=new Image();
  _fixtureVehicleImg.onload=()=>{_fixtureImgLoaded=true;drawFixtureCanvas();};
  _fixtureVehicleImg.onerror=()=>{
    ctx.fillStyle="#eef0f6";ctx.fillRect(0,0,700,460);
    ctx.fillStyle="#aab";ctx.font="14px sans-serif";ctx.textAlign="center";
    ctx.fillText(`No image: assets/vehicles/${_fixtureVehicle}_${_fixtureView}.png`,350,230);
    drawFixtureDots(ctx,[0,0,700,460]);
  };
  _fixtureVehicleImg.src=`/assets/vehicles/${_fixtureVehicle}_${_fixtureView}.png`;
  canvas.onclick=e=>{
    if(!_selectedFixtureId)return;
    const rect=canvas.getBoundingClientRect();
    const scaleX=700/rect.width,scaleY=460/rect.height;
    const px=(e.clientX-rect.left)*scaleX,py=(e.clientY-rect.top)*scaleY;
    const box=_getFixtureImageBox();
    const x=Math.round(((px-box[0])/box[2])*1000)/1000;
    const y=Math.round(((py-box[1])/box[3])*1000)/1000;
    $("fix-x-num").value=Math.max(-0.1,Math.min(1.1,x));
    $("fix-x-range").value=$("fix-x-num").value;
    $("fix-y-num").value=Math.max(-0.1,Math.min(1.1,y));
    $("fix-y-range").value=$("fix-y-num").value;
    _saveCurrentFixture();
    drawFixtureCanvas();
  };
}

function _getFixtureImageBox(){
  if(!_fixtureImgLoaded||!_fixtureVehicleImg.naturalWidth) return [0,0,700,460];
  const iw=_fixtureVehicleImg.naturalWidth,ih=_fixtureVehicleImg.naturalHeight;
  const scale=Math.min(700/iw,460/ih);
  const dw=iw*scale,dh=ih*scale;
  return [(700-dw)/2,(460-dh)/2,dw,dh];
}

function drawFixtureCanvas(){
  const canvas=$("fixture-canvas"),ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,700,460);ctx.fillStyle="#f0f2fa";ctx.fillRect(0,0,700,460);
  const box=_getFixtureImageBox();
  if(_fixtureImgLoaded)ctx.drawImage(_fixtureVehicleImg,box[0],box[1],box[2],box[3]);
  drawFixtureDots(ctx,box);
}

function drawFixtureDots(ctx,box){
  const parts=getFixtureParts();
  const fixtures=getVehicleFixtures();
  parts.forEach(p=>{
    const entry=fixtures[p.part_id]?.[_fixtureView];
    if(!entry)return;
    const selected=p.part_id===_selectedFixtureId;
    const positions=getSlotPositions(entry,box);
    const baseRot=entry.rotation||0;
    const isMirror=(entry.pattern||"single")==="mirror";
    positions.forEach(([cx,cy],idx)=>{
      const rot=isMirror&&idx%2===1?((360-baseRot)%360):baseRot;
      const rad=rot*Math.PI/180;
      const r=selected?7:4;
      ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);
      ctx.fillStyle=selected?"#C8A951":"rgba(30,39,97,0.72)";
      ctx.fill();ctx.strokeStyle="#fff";ctx.lineWidth=1.5;ctx.stroke();
      // rotation indicator X
      const longArm=r+5, shortArm=r+1;
      ctx.strokeStyle=selected?"#C8A951":"rgba(255,255,255,0.9)";
      ctx.lineWidth=selected?2:1.5;
      ctx.beginPath();
      ctx.moveTo(cx+Math.cos(rad)*longArm,cy+Math.sin(rad)*longArm);
      ctx.lineTo(cx-Math.cos(rad)*longArm,cy-Math.sin(rad)*longArm);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cx+Math.cos(rad+Math.PI/2)*shortArm,cy+Math.sin(rad+Math.PI/2)*shortArm);
      ctx.lineTo(cx-Math.cos(rad+Math.PI/2)*shortArm,cy-Math.sin(rad+Math.PI/2)*shortArm);
      ctx.stroke();
      if(positions.length>1){
        ctx.fillStyle=selected?"#1E2761":"#fff";
        ctx.font="bold 8px sans-serif";ctx.textAlign="center";
        ctx.fillText(idx+1,cx,cy+3);
      }
    });
    if(selected&&positions.length){
      const [cx,cy]=positions[Math.floor(positions.length/2)];
      ctx.fillStyle="rgba(255,255,255,0.93)";ctx.font="bold 10px sans-serif";ctx.textAlign="center";
      ctx.fillText(p.display_name.length>18?p.display_name.slice(0,17)+"…":p.display_name,cx,cy-12);
    }
  });
}

// Wire up fixture field inputs
["x","y"].forEach(axis=>{
  $(`fix-${axis}-range`).addEventListener("input",e=>{
    const v=parseFloat(e.target.value);
    $(`fix-${axis}-num`).value=v;
    _saveCurrentFixture();drawFixtureCanvas();
  });
  $(`fix-${axis}-num`).addEventListener("input",e=>{
    const v=parseFloat(e.target.value)||0;
    $(`fix-${axis}-range`).value=v;
    _saveCurrentFixture();drawFixtureCanvas();
  });
});
["fix-orient","fix-pattern","fix-slots"].forEach(id=>{
  $(id).addEventListener("change",()=>{
    _saveCurrentFixture();
    updateFixtureSpacingRows($("fix-pattern").value,parseInt($("fix-slots").value)||1);
    drawFixtureCanvas();
  });
});
["fix-hsp-range","fix-hsp-num","fix-vsp-range","fix-vsp-num",
 "fix-rotation","fix-flip-h","fix-flip-v","fix-flip-mirrored-h","fix-behind-vehicle"].forEach(id=>{
  $(id).addEventListener($(id).type==="checkbox"?"change":"input",()=>{_saveCurrentFixture();drawFixtureCanvas();});
});
$("fix-rotation-preset").addEventListener("change",e=>{
  if(e.target.value==="")return;
  $("fix-rotation").value=parseFloat(e.target.value);
  _saveCurrentFixture();drawFixtureCanvas();
});
document.querySelectorAll("#fixture-view-pills .view-pill").forEach(p=>{
  p.addEventListener("click",()=>{
    document.querySelectorAll("#fixture-view-pills .view-pill").forEach(x=>x.classList.remove("active"));
    p.classList.add("active");
    _fixtureView=p.dataset.view;
    renderFixtureList();loadFixtureCanvas();
    if(_selectedFixtureId){
      showFixtureEditPanel(_selectedFixtureId);
      show("fixture-edit-panel");hide("fixture-empty-hint");
      drawFixtureCanvas();
    } else {
      hide("fixture-edit-panel");show("fixture-empty-hint");
    }
  });
});
$("btn-save-fixtures").addEventListener("click",async()=>{
  const btn=$("btn-save-fixtures");btn.disabled=true;btn.textContent="Saving…";
  const res=await apiSave("/api/layouts/save",_layouts);
  btn.disabled=false;btn.textContent="Save Changes";
  if(res.ok){_fixturesDirty=false;$("fixtures-dirty-dot").style.display="none";toast("Fixtures saved","success");}
  else toast("Save failed: "+res.error,"error");
});

function initFixtures(){
  populateFixtureVehicleSelector();
  renderFixtureList();
  loadFixtureCanvas();
}

// ─── Add Fixture Modal ───────────────────────────────────────────────────────
function openAddFixtureModal(){
  $("afm-vehicle-label").textContent=_fixtureVehicle;
  afmFilter("");
  $("afm-search").value="";
  $("add-fixture-modal").classList.add("open");
}

function afmFilter(q){
  const currentIds=new Set(getFixtureParts().map(p=>p.part_id));
  let parts=(_catalog?.parts||[]).filter(p=>!currentIds.has(p.part_id));
  if(q) parts=parts.filter(p=>(p.display_name||p.part_id).toLowerCase().includes(q.toLowerCase()));
  const el=$("afm-part-list");
  if(!parts.length){ el.innerHTML=`<div class="alm-empty">No parts available to add.</div>`; return; }
  el.innerHTML=parts.map(p=>
    `<div class="alm-import-item" data-id="${esc(p.part_id)}">${esc(p.display_name||p.part_id)} <span style="font-size:10px;color:var(--muted)">${esc(p.part_id)}</span></div>`
  ).join("");
  el.querySelectorAll(".alm-import-item").forEach(item=>{
    item.addEventListener("click",()=>addFixturePart(item.dataset.id));
  });
}

async function addFixturePart(partId){
  // Mark is_fixture on the catalog part
  const part=(_catalog?.parts||[]).find(p=>p.part_id===partId);
  if(!part){ toast("Part not found in catalog","error"); return; }
  part.is_fixture=true;

  // Add empty entry to vehicle fixtures map
  if(!_layouts.vehicles[_fixtureVehicle]) return;
  if(!_layouts.vehicles[_fixtureVehicle].fixtures) _layouts.vehicles[_fixtureVehicle].fixtures={};
  if(!_layouts.vehicles[_fixtureVehicle].fixtures[partId]) _layouts.vehicles[_fixtureVehicle].fixtures[partId]={};

  // Save catalog and layouts
  const catRes=await apiSave("/api/catalog/save",_catalog);
  if(!catRes.ok){ part.is_fixture=false; toast("Catalog save failed: "+(catRes.error||""),"error"); return; }
  const layRes=await apiSave("/api/layouts/save",_layouts);
  if(!layRes.ok){ toast("Layout save failed: "+(layRes.error||""),"error"); return; }

  _selectedFixtureId=partId;
  $("add-fixture-modal").classList.remove("open");
  renderFixtureList();
  showFixtureEditPanel(partId);
  hide("fixture-empty-hint"); show("fixture-edit-panel");
  drawFixtureCanvas();
  toast(`Added "${part.display_name||partId}" as fixture`,"success");
}

// ─── Delete Fixture ──────────────────────────────────────────────────────────
async function deleteFixturePart(){
  if(!_selectedFixtureId) return;
  const part=getFixtureParts().find(p=>p.part_id===_selectedFixtureId);
  const label=part?.display_name||_selectedFixtureId;
  if(!confirm(`Remove "${label}" from fixtures for ${_fixtureVehicle}?`)) return;

  // Remove from vehicle fixtures map
  const fixtures=_layouts.vehicles[_fixtureVehicle]?.fixtures;
  if(fixtures) delete fixtures[_selectedFixtureId];

  // Clear is_fixture on catalog part (if it was set via this page)
  const catalogPart=(_catalog?.parts||[]).find(p=>p.part_id===_selectedFixtureId);
  if(catalogPart) catalogPart.is_fixture=false;

  const catRes=await apiSave("/api/catalog/save",_catalog);
  if(!catRes.ok){ toast("Catalog save failed: "+(catRes.error||""),"error"); return; }
  const layRes=await apiSave("/api/layouts/save",_layouts);
  if(!layRes.ok){ toast("Layout save failed: "+(layRes.error||""),"error"); return; }

  _selectedFixtureId=null;
  hide("fixture-edit-panel"); show("fixture-empty-hint");
  renderFixtureList(); drawFixtureCanvas();
  toast(`Removed "${label}" from fixtures`,"success");
}

$("btn-add-fixture").addEventListener("click",()=>openAddFixtureModal());
$("btn-delete-fixture").addEventListener("click",()=>deleteFixturePart());
$("afm-close").addEventListener("click",()=>$("add-fixture-modal").classList.remove("open"));
$("afm-cancel").addEventListener("click",()=>$("add-fixture-modal").classList.remove("open"));
$("add-fixture-modal").addEventListener("click",e=>{if(e.target===$("add-fixture-modal"))$("add-fixture-modal").classList.remove("open");});
