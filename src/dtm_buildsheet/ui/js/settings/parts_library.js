// ═══════════════════════════════════════════════════════
// PARTS LIBRARY
// ═══════════════════════════════════════════════════════
let _partsLib=null, _editingPartLibId=null;
const _pmUploadedImages={};
const _pmDeletedViews=new Set();  // views marked for deletion from parts_library images
const _pmAspectRatios={};         // view → w/h ratio for parts lib AR lock

async function loadPartsLibrary(){
  _partsLib=await api("/api/parts-library");
  renderPartsLibrary($("lib-search").value);
}

function getPartsCategories(){
  const cats=[];
  (_partsLib?.parts||[]).forEach(p=>{if(p.category&&!cats.includes(p.category))cats.push(p.category);});
  return cats;
}

function populatePmCategory(selected){
  const cats=getPartsCategories();
  $("pm-category").innerHTML=cats.map(c=>`<option value="${esc(c)}" ${c===selected?"selected":""}>${esc(c)}</option>`).join("");
  if(selected) $("pm-category").value=selected;
}

function populatePmSizeRule(){
  const defs=_manifest?.size_rule_definitions||{};
  $("pm-size-rule").innerHTML='<option value="">— none —</option>'+
    Object.entries(defs).map(([id,d])=>`<option value="${esc(id)}">${esc(d.label||id)}</option>`).join("");
}

function populatePmCompatTypes(selectedTypes){
  const types=(_catalog?.parts||[]).map(p=>p.display_name||p.part_id).sort();
  $("pm-compat-types").innerHTML=types.map(t=>{
    const checked=(selectedTypes||[]).includes(t);
    return `<label class="compat-chip ${checked?"checked":""}"><input type="checkbox" value="${esc(t)}" ${checked?"checked":""}> ${esc(t)}</label>`;
  }).join("");
  $("pm-compat-types").querySelectorAll(".compat-chip").forEach(label=>{
    label.addEventListener("click",()=>{
      const cb=label.querySelector("input"); cb.checked=!cb.checked;
      label.classList.toggle("checked",cb.checked);
    });
  });
}

function renderPartsLibrary(filter=""){
  const lc=filter.toLowerCase();
  const parts=(_partsLib?.parts||[]).filter(p=>
    !filter||
    (p.display_name||"").toLowerCase().includes(lc)||
    (p.manufacturer||"").toLowerCase().includes(lc)||
    (p.model_number||"").toLowerCase().includes(lc)||
    (p.category||"").toLowerCase().includes(lc)
  );
  const defs=_manifest?.size_rule_definitions||{};
  if(!parts.length){
    $("lib-tbody").innerHTML=`<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">No parts found.</td></tr>`;
    return;
  }
  // Group by category, preserving order
  const groups=[];
  const seen=new Map();
  parts.forEach(p=>{
    const cat=p.category||"OTHER";
    if(!seen.has(cat)){seen.set(cat,[]);groups.push(cat);}
    seen.get(cat).push(p);
  });
  const rows=[];
  groups.forEach(cat=>{
    rows.push(`<tr><td colspan="7" style="background:var(--navy);color:#fff;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;padding:5px 10px">${esc(cat)}</td></tr>`);
    seen.get(cat).forEach(p=>{
      const szViews=Object.keys(p.size_per_view||{});
      const sizeLabel=szViews.length
        ?szViews.map(v=>{const s=p.size_per_view[v];return `${v}:${s.w}"×${s.h}"`}).join(", ")
        :p.size_rule_id?(defs[p.size_rule_id]?.label||p.size_rule_id):"—";
      const imgCount=Object.keys(p.images||{}).length;
      const compat=(p.compatible_types||[]).slice(0,2).map(t=>`<span class="chip">${esc(t)}</span>`).join("");
      const more=(p.compatible_types||[]).length>2?`<span class="chip">+${(p.compatible_types||[]).length-2}</span>`:"";
      const mfg=p.manufacturer?`<span style="font-weight:600">${esc(p.manufacturer)}</span> `:"";
      rows.push(`<tr>
        <td>${mfg}${esc(p.display_name||"")}</td>
        <td style="color:var(--muted);font-size:11px">${esc(p.model_number||"—")}</td>
        <td><div class="view-chips">${compat}${more}</div></td>
        <td>${esc(sizeLabel)}</td>
        <td>${imgCount>0?`<span class="badge badge-on">${imgCount} view${imgCount!==1?"s":""}</span>`:`<span style="color:var(--muted)">—</span>`}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="openPartsModal('${esc(p.part_id)}')">Edit</button></td>
      </tr>`);
    });
  });
  $("lib-tbody").innerHTML=rows.join("");
}

$("lib-search").addEventListener("input",e=>renderPartsLibrary(e.target.value));
$("btn-reload-parts").addEventListener("click",async()=>{await loadPartsLibrary();toast("Reloaded","success");});
$("btn-add-part-lib").addEventListener("click",()=>openPartsModal(null));

function openPartsModal(partId){
  _editingPartLibId=partId;
  Object.keys(_pmUploadedImages).forEach(k=>delete _pmUploadedImages[k]);
  _pmDeletedViews.clear();
  const p=partId?(_partsLib?.parts||[]).find(x=>x.part_id===partId):null;
  $("parts-modal-title").textContent=p?"Edit Part":"Add Part";
  $("pm-delete").style.display=p?"inline-flex":"none";
  $("pm-name").value=p?.display_name||"";
  $("pm-id").value=p?.part_id||"";
  $("pm-manufacturer").value=p?.manufacturer||"";
  $("pm-model").value=p?.model_number||"";
  $("pm-notes").value=p?.notes||"";
  populatePmCategory(p?.category||"");
  populatePmSizeRule();
  $("pm-size-rule").value=p?.size_rule_id||"";
  populatePmCompatTypes(p?.compatible_types||[]);
  buildPmImageGrid(p);
  $("parts-modal").classList.add("open");
}

// Scale factor: 50px per inch for the car preview overlay
const PM_PREVIEW_SCALE = 50;
// Default anchor positions (center %) for placing the part overlay on the car preview
const PM_PREVIEW_ANCHORS = {
  front:{cx:50,cy:68}, rear:{cx:50,cy:55}, side:{cx:38,cy:50}, top:{cx:50,cy:50}
};

function buildPmImageGrid(p){
  const views=["front","side","top","rear"];
  const existingSizes=p?.size_per_view||{};
  $("pm-images-grid").innerHTML=views.map(view=>{
    const existing=p?.images?.[view];
    const imgUrl=existing?"/assets/"+existing:null;
    const upld=_pmUploadedImages[view];
    const hasImg=!!(imgUrl||upld);
    const sz=existingSizes[view]||{};
    const carSrc=`/assets/vehicles/PIU_${view}.png`;
    const partSrc=upld?.dataUrl||(imgUrl||"");
    return `<div class="pm-view-row" data-view="${view}">
      <!-- thumbnail / upload trigger -->
      <div class="pm-view-thumb ${hasImg?"has-file":""}" id="pmuz-${view}" title="Click to upload ${view} image">
        <input type="file" accept="image/*" data-view="${view}" class="pmuz-input" />
        <img id="pmuz-prev-${view}" ${upld?`src="${upld.dataUrl}"`:imgUrl?`src="${imgUrl}" onerror="this.removeAttribute('src')"`:""} />
        ${!hasImg?"<span>🖼️</span>":""}
        <div class="pm-view-label">${view}</div>
      </div>
      <!-- size inputs — only visible when image present -->
      <div class="pm-size-panel" id="pmvs-${view}" ${hasImg?"":"style='display:none'"}>
        <label>Render size (inches)</label>
        <div class="pm-size-row">
          <span>W</span>
          <input type="number" id="pmvw-${view}" class="pmvw" data-view="${view}"
            value="${sz.w||""}" step="0.01" min="0.01" max="8" placeholder="—" />
          <span style="margin:0 2px">×</span>
          <span>H</span>
          <input type="number" id="pmvh-${view}" class="pmvh" data-view="${view}"
            value="${sz.h||""}" step="0.01" min="0.01" max="6" placeholder="—" />
          <button type="button" class="pm-ar-lock-btn" id="pm-ar-lock-${view}" data-view="${view}" data-locked="false" title="Lock aspect ratio" style="background:none;border:1px solid var(--border);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:13px;line-height:1.4;margin-left:2px">🔓</button>
        </div>
        <div class="pm-size-row" style="margin-top:4px">
          <span title="Rotate the source image before any placement rotation. Use for photos uploaded sideways.">↻ Rotate</span>
          <select id="pmvr-${view}" class="pmvr" data-view="${view}" style="font-size:11px;padding:1px 4px;border:1px solid var(--border);border-radius:4px">
            ${[0,90,180,270].map(d=>`<option value="${d}" ${(sz.rotation||0)==d?"selected":""}>${d}°</option>`).join("")}
          </select>
        </div>
        <button class="btn btn-danger btn-sm pm-del-view" data-view="${view}" style="margin-top:6px;width:fit-content">🗑 Remove image</button>
      </div>
      <!-- car preview overlay — visible when image + size both present -->
      <div class="pm-car-preview ${hasImg&&sz.w&&sz.h?"visible":""}" id="pmpreview-${view}">
        <img class="car-bg" src="${carSrc}" onerror="this.src=''" />
        <div class="part-overlay" id="pmpov-${view}" style="${buildOverlayStyle(sz.w||0,sz.h||0,PM_PREVIEW_ANCHORS[view]||PM_PREVIEW_ANCHORS.front)}"></div>
        <span class="scale-note">~${PM_PREVIEW_SCALE}px/in</span>
      </div>
    </div>`;
  }).join("");

  // Probe existing images: detect AR + seed W/H when blank.
  ["front","side","top","rear"].forEach(view=>{
    const existing=p?.images?.[view];
    if(!existing||_pmAspectRatios[view]) return;
    const probe=new Image();
    probe.onload=()=>{
      if(probe.naturalWidth&&probe.naturalHeight){
        _pmAspectRatios[view]=probe.naturalWidth/probe.naturalHeight;
        applyArToSizeInputs(view, _pmAspectRatios[view],
          `pmvw-${view}`, `pmvh-${view}`, `pm-ar-lock-${view}`);
        updateCarPreview(view);
      }
    };
    probe.src="/assets/"+existing;
  });

  // Wire upload inputs
  $("pm-images-grid").querySelectorAll(".pmuz-input").forEach(inp=>{
    inp.addEventListener("change",e=>{
      const file=e.target.files[0]; if(!file) return;
      const view=e.target.dataset.view;
      const mfg=($("pm-manufacturer").value||"part").toLowerCase().replace(/\s+/g,"_");
      const mdl=($("pm-model").value||"unknown").toLowerCase().replace(/\s+/g,"_");
      const reader=new FileReader();
      reader.onload=ev=>{
        const b64=ev.target.result.split(",")[1];
        _pmUploadedImages[view]={filename:`${mfg}_${mdl}_${view}.png`,b64,dataUrl:ev.target.result};
        const prevImg=$(`pmuz-prev-${view}`);
        prevImg.src=ev.target.result;
        $(`pmuz-${view}`).classList.add("has-file");
        $(`pmvs-${view}`).style.display="";
        // Detect aspect ratio from uploaded image, auto-populate W/H if blank
        const probe=new Image();
        probe.onload=()=>{
          if(probe.naturalWidth&&probe.naturalHeight){
            _pmAspectRatios[view]=probe.naturalWidth/probe.naturalHeight;
            applyArToSizeInputs(view, _pmAspectRatios[view], `pmvw-${view}`, `pmvh-${view}`, `pm-ar-lock-${view}`);
            updateCarPreview(view);
          }
        };
        probe.src=ev.target.result;
        updateCarPreview(view);
      };
      reader.readAsDataURL(file);
    });
  });

  // AR lock toggle buttons
  $("pm-images-grid").querySelectorAll(".pm-ar-lock-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const wasLocked=btn.dataset.locked==="true";
      btn.dataset.locked=(!wasLocked).toString();
      btn.textContent=wasLocked?"🔓":"🔒";
      if(!wasLocked){
        const v=btn.dataset.view;
        const w=parseFloat($(`pmvw-${v}`)?.value)||0, h=parseFloat($(`pmvh-${v}`)?.value)||0;
        if(w>0&&h>0) _pmAspectRatios[v]=w/h;
      }
    });
  });

  // Wire size inputs → live preview + AR linking when locked
  $("pm-images-grid").querySelectorAll(".pmvw,.pmvh").forEach(inp=>{
    inp.addEventListener("input",e=>{
      const view=e.target.dataset.view;
      const lockBtn=$(`pm-ar-lock-${view}`);
      if(lockBtn?.dataset.locked==="true"&&_pmAspectRatios[view]){
        const ratio=_pmAspectRatios[view];
        if(e.target.classList.contains("pmvw")){
          const w=parseFloat(e.target.value);
          if(w>0) $(`pmvh-${view}`).value=(w/ratio).toFixed(2);
        } else {
          const h=parseFloat(e.target.value);
          if(h>0) $(`pmvw-${view}`).value=(h*ratio).toFixed(2);
        }
      }
      updateCarPreview(view);
    });
  });

  // Wire delete buttons
  $("pm-images-grid").querySelectorAll(".pm-del-view").forEach(btn=>{
    btn.addEventListener("click",e=>{
      const view=e.target.dataset.view;
      _pmDeletedViews.add(view);
      delete _pmUploadedImages[view];
      const thumb=$(`pmuz-${view}`);
      thumb.classList.remove("has-file");
      // Clear src + remove .has-file; don't set inline display:none
      // (it would persist and hide a re-uploaded image — see CSS specificity).
      const img=$(`pmuz-prev-${view}`); if(img) img.removeAttribute("src");
      const sp=$(`pmvs-${view}`); if(sp) sp.style.display="none";
      const pv=$(`pmpreview-${view}`); if(pv) pv.classList.remove("visible");
    });
  });
}

function buildOverlayStyle(w,h,anchor){
  if(!w||!h) return "display:none";
  const wpx=Math.round(w*PM_PREVIEW_SCALE);
  const hpx=Math.round(h*PM_PREVIEW_SCALE);
  return `width:${wpx}px;height:${hpx}px;left:${anchor.cx}%;top:${anchor.cy}%`;
}

function updateCarPreview(view){
  const w=parseFloat($(`pmvw-${view}`)?.value)||0;
  const h=parseFloat($(`pmvh-${view}`)?.value)||0;
  const preview=$(`pmpreview-${view}`);
  const overlay=$(`pmpov-${view}`);
  if(!preview||!overlay) return;
  const anchor=PM_PREVIEW_ANCHORS[view]||PM_PREVIEW_ANCHORS.front;
  if(w&&h){
    preview.classList.add("visible");
    overlay.style.cssText=buildOverlayStyle(w,h,anchor);
  } else {
    overlay.style.display="none";
  }
}

$("pm-name").addEventListener("input",e=>{
  if(!_editingPartLibId) $("pm-id").value=slugify(e.target.value).replace(/-/g,"_");
});

$("parts-modal-close").addEventListener("click",()=>$("parts-modal").classList.remove("open"));
$("pm-cancel").addEventListener("click",()=>$("parts-modal").classList.remove("open"));
$("parts-modal").addEventListener("click",e=>{if(e.target===$("parts-modal"))$("parts-modal").classList.remove("open");});

$("pm-save").addEventListener("click",async()=>{
  const btn=$("pm-save"); btn.disabled=true; btn.textContent="Saving…";
  try{
    const name=$("pm-name").value.trim();
    if(!name) throw new Error("Display Name is required");
    const partId=$("pm-id").value.trim()||slugify(name).replace(/-/g,"_");
    const sizeRuleId=$("pm-size-rule").value||null;
    const compatTypes=[...$("pm-compat-types").querySelectorAll("input:checked")].map(cb=>cb.value);
    const images=_editingPartLibId
      ?{...((_partsLib?.parts||[]).find(p=>p.part_id===_editingPartLibId)?.images||{})}
      :{};
    // Apply deletions
    _pmDeletedViews.forEach(v=>delete images[v]);
    // Upload new images
    for(const [view,img] of Object.entries(_pmUploadedImages)){
      const res=await api("/api/assets/upload",{folder:"lights",filename:img.filename,data:img.b64});
      if(!res.ok) throw new Error("Image upload failed: "+res.error);
      images[view]="lights/"+img.filename;
    }
    // Collect per-view render sizes (only where both W and H are filled).
    // Optional default image rotation per view (0/90/180/270) is added on top.
    const size_per_view={};
    ["front","side","top","rear"].forEach(v=>{
      const w=parseFloat($(`pmvw-${v}`)?.value)||0;
      const h=parseFloat($(`pmvh-${v}`)?.value)||0;
      const rot=parseInt($(`pmvr-${v}`)?.value)||0;
      if(w&&h){
        size_per_view[v]={w,h};
        if(rot) size_per_view[v].rotation=rot;
      }
    });
    const entry={part_id:partId,display_name:name,
      category:$("pm-category").value||"OTHER",
      manufacturer:$("pm-manufacturer").value.trim(),
      model_number:$("pm-model").value.trim(),
      compatible_types:compatTypes,images};
    if(sizeRuleId) entry.size_rule_id=sizeRuleId;
    if(Object.keys(size_per_view).length) entry.size_per_view=size_per_view;
    const notes=$("pm-notes").value.trim();
    if(notes) entry.notes=notes;
    if(!_partsLib) _partsLib={version:"1.0",parts:[]};
    _partsLib.parts=(_partsLib.parts||[]).filter(p=>p.part_id!==partId);
    _partsLib.parts.push(entry);
    const res=await apiSave("/api/parts-library/save",_partsLib);
    if(!res.ok) throw new Error(res.error);
    refreshSharedUi();
    toast("Part saved!","success");
    $("parts-modal").classList.remove("open");
  }catch(err){toast("Save failed: "+err,"error");}
  btn.disabled=false; btn.textContent="Save Part";
});

$("pm-delete").addEventListener("click",async()=>{
  if(!_editingPartLibId||!confirm("Delete this part from the library?"))return;
  _partsLib.parts=(_partsLib.parts||[]).filter(p=>p.part_id!==_editingPartLibId);
  const res=await apiSave("/api/parts-library/save",_partsLib);
  if(res.ok){refreshSharedUi();toast("Deleted","success");$("parts-modal").classList.remove("open");}
  else toast("Delete failed: "+res.error,"error");
});
