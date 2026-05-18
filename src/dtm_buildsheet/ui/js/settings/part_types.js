// ═══════════════════════════════════════════════════════
// ADD PART WIZARD
// ═══════════════════════════════════════════════════════
let _wizardStep=1, _renderKind="light", _wizardViews=["front"];

function openAddPartModal(){
  setWizardStep(1);
  $("wp-display-name").value=""; $("wp-part-id").value=""; $("wp-asset-key").value="";
  document.querySelectorAll(".rk-card").forEach(c=>c.classList.remove("selected"));
  document.querySelector('.rk-card[data-rk="light"]').classList.add("selected");
  _renderKind="light"; _wizardViews=["front"];
  syncWizardDiagramUi();
  Object.keys(_uploadedImages).forEach(k=>delete _uploadedImages[k]);
  hide("wizard-result");
  $("addpart-modal").classList.add("open");
}

$("btn-add-part-type").addEventListener("click", openAddPartModal);
$("addpart-modal-close").addEventListener("click", ()=>$("addpart-modal").classList.remove("open"));
$("addpart-modal").addEventListener("click", e=>{if(e.target===$("addpart-modal"))$("addpart-modal").classList.remove("open");});

function setWizardStep(n){
  _wizardStep=n;
  document.querySelectorAll(".wstep").forEach(s=>{
    const sn=parseInt(s.dataset.step);
    s.classList.toggle("active",sn===n); s.classList.toggle("done",sn<n);
  });
  document.querySelectorAll(".wizard-panel").forEach(p=>p.classList.toggle("active",p.id===`wstep-${n}`));
}

function syncWizardDiagramUi(){
  const enabled=_renderKind!=="none";
  const diag=isDiagramConfigured(_renderKind, _wizardViews);
  $("diagram-options").hidden=!enabled;
  $("diagram-options-empty").hidden=enabled;
  $("wp-diagram-status").textContent=diag?"Yes":"No";
}

document.querySelectorAll(".rk-card").forEach(card=>{
  card.addEventListener("click",()=>{
    document.querySelectorAll(".rk-card").forEach(c=>c.classList.remove("selected"));
    card.classList.add("selected"); _renderKind=card.dataset.rk;
    syncWizardDiagramUi();
  });
});

$("wp-display-name").addEventListener("input",e=>{
  const id=slugify(e.target.value).replace(/-/g,"_");
  $("wp-part-id").value=id; $("wp-asset-key").value=id;
});

document.querySelectorAll(".view-check-label").forEach(label=>{
  label.addEventListener("click",()=>{
    const cb=label.querySelector("input"); cb.checked=!cb.checked;
    label.classList.toggle("checked",cb.checked);
    _wizardViews=[...document.querySelectorAll(".view-check-label.checked")].map(l=>l.dataset.view);
    syncWizardDiagramUi();
  });
});

$("wbtn-1-next").addEventListener("click",()=>{
  if(!$("wp-display-name").value.trim()){toast("Part name is required","error");return;}
  $("asset-key-row").hidden=!["equipment","bar"].includes(_renderKind);
  $("wp-color-profile").closest(".form-group").hidden=(_renderKind!=="light");
  syncWizardDiagramUi();
  setWizardStep(2);
});
$("wbtn-2-next").addEventListener("click",()=>{
  if(["equipment","bar"].includes(_renderKind)&&_renderKind!=="none"&&_wizardViews.length){buildUploadGrid();setWizardStep(3);}
  else{buildReview();setWizardStep(4);}
});
$("wbtn-2-back").addEventListener("click",()=>setWizardStep(1));
$("wbtn-3-next").addEventListener("click",()=>{buildReview();setWizardStep(4);});
$("wbtn-3-back").addEventListener("click",()=>setWizardStep(2));
$("wbtn-4-back").addEventListener("click",()=>["equipment","bar"].includes(_renderKind)?setWizardStep(3):setWizardStep(2));

function buildUploadGrid(){
  const views=_wizardViews.length?_wizardViews:["front","side","top","rear"];
  const assetKey=$("wp-asset-key").value.trim()||slugify($("wp-display-name").value);
  $("upload-grid").innerHTML=views.map(view=>{
    const fname=`${assetKey}_${view}.png`;
    return `<div class="upload-zone ${_uploadedImages[view]?"has-file":""}" id="uz-${view}">
      <input type="file" accept="image/*" data-view="${view}" class="uz-input" />
      <div class="uz-icon">🖼️</div>
      <div class="uz-label">${view.charAt(0).toUpperCase()+view.slice(1)} View</div>
      <div class="uz-hint"><code>${fname}</code></div>
      <img class="uz-thumb" id="uz-prev-${view}" ${_uploadedImages[view]?`src="${_uploadedImages[view].dataUrl}" style="display:block"`:""}/>
    </div>`;
  }).join("");
  $("upload-grid").querySelectorAll(".uz-input").forEach(inp=>{
    inp.addEventListener("change",e=>{
      const file=e.target.files[0]; if(!file)return;
      const view=e.target.dataset.view;
      const assetKey2=$("wp-asset-key").value.trim()||slugify($("wp-display-name").value);
      const reader=new FileReader();
      reader.onload=ev=>{
        const b64=ev.target.result.split(",")[1];
        _uploadedImages[view]={filename:`${assetKey2}_${view}.png`,b64,dataUrl:ev.target.result};
        const prev=$(`uz-prev-${view}`); prev.src=ev.target.result; prev.style.display="block";
        $(`uz-${view}`).classList.add("has-file");
      };
      reader.readAsDataURL(file);
    });
  });
  $("step3-naming-hint").textContent=views.map(v=>`equipment/${assetKey}_${v}.png`).join("\n");
}

function buildReview(){
  const name=$("wp-display-name").value.trim();
  const partId=$("wp-part-id").value.trim()||slugify(name).replace(/-/g,"_");
  const rows=[
    ["Display Name",esc(name)],["Part ID",esc(partId)],
    ["Category",esc($("wp-category").value)],["Render Kind",esc(_renderKind)],
    ["On Diagram",isDiagramConfigured(_renderKind,_wizardViews)?"Yes":"No"],
    _wizardViews.length?["Views",_wizardViews.join(", ")]:null,
    $("wp-location-key").value?["Default Location",esc($("wp-location-key").value)]:null,
    $("wp-asset-key").value?["Asset Key",esc($("wp-asset-key").value)]:null,
    $("wp-color-profile").value?["Color Profile",esc($("wp-color-profile").value)]:null,
    Object.keys(_uploadedImages).length?["Images",Object.entries(_uploadedImages).map(([v,d])=>`<span class="review-file">📎 ${esc(d.filename)}</span>`).join(" ")]:null,
  ].filter(Boolean);
  $("review-grid").innerHTML=rows.map(([k,v])=>
    `<div class="review-row"><div class="review-key">${k}</div><div class="review-val">${v}</div></div>`
  ).join("");
}

$("wbtn-4-save").addEventListener("click", async()=>{
  const btn=$("wbtn-4-save"); btn.disabled=true; btn.textContent="Saving…";
  const resultDiv=$("wizard-result");
  try{
    const name=$("wp-display-name").value.trim();
    const partId=$("wp-part-id").value.trim()||slugify(name).replace(/-/g,"_");
    const assetKey=$("wp-asset-key").value.trim()||partId;
    const rk=_renderKind;
    const views=rk==="none"?[]:[..._wizardViews];
    const diag=isDiagramConfigured(rk, views);
    const assetFolder=partTypeUploadFolder(rk);
    for(const [view,img] of Object.entries(_uploadedImages)){
      const res=await api("/api/assets/upload",{folder:assetFolder,filename:img.filename,data:img.b64});
      if(!res.ok) throw new Error("Image upload failed: "+res.error);
    }
    if(["equipment","bar"].includes(rk)&&Object.keys(_uploadedImages).length){
      const assetMap=getPartTypeAssetMap(rk);
      const viewMap={};
      Object.entries(_uploadedImages).forEach(([view,img])=>{viewMap[view]=`${assetFolder}/${img.filename}`;});
      assetMap[assetKey]=viewMap;
      const mRes=await api("/api/manifest/save",_manifest);
      if(!mRes.ok) throw new Error("Manifest save failed: "+mRes.error);
    }
    const newPart={part_id:partId,display_name:name,category:$("wp-category").value,render_kind:rk,diagram:diag,default_views:views};
    if(rk!=="none"){
      newPart.render_quantity_policy=$("wp-qty-policy").value;
      if($("wp-location-key").value) newPart.default_location_key=$("wp-location-key").value;
      if(assetKey&&["equipment","bar"].includes(rk)) newPart.asset_key=assetKey;
      if($("wp-color-profile").value&&rk==="light") newPart.default_color_profile=$("wp-color-profile").value;
    }
    _catalog.parts=(_catalog.parts||[]).filter(p=>p.part_id!==partId);
    _catalog.parts.push(newPart);
    const cRes=await api("/api/catalog/save",_catalog);
    if(!cRes.ok) throw new Error("Catalog save failed: "+cRes.error);

    // Add to workbook_rules template_sections so it appears in the generated template
    const targetSection=$("wp-template-section").value;
    if(targetSection&&_workbookRules?.template_sections){
      const sec=_workbookRules.template_sections.find(s=>s.label===targetSection);
      if(sec){
        // Only add if not already present
        if(!sec.parts.find(p=>p.name===name)){
          sec.parts.push({name,sub:false});
          const wrRes=await apiSave("/api/workbook-rules/save",_workbookRules);
          if(!wrRes.ok) throw new Error("Workbook rules save failed: "+wrRes.error);
        }
      }
    }

    refreshSharedUi();
    show("wizard-result");
    resultDiv.innerHTML=`<div class="result-banner success">✅ <span style="font-weight:700">"${esc(name)}" created!</span> It will appear on the next generated build sheet.</div>`;
    toast("Part created!","success");
    setTimeout(()=>{
      $("addpart-modal").classList.remove("open");
    },1800);
  }catch(err){
    show("wizard-result");
    resultDiv.innerHTML=`<div class="result-banner error">❌ ${esc(String(err))}</div>`;
    toast("Error: "+err,"error");
  }
  btn.disabled=false; btn.textContent="✓ Create Part";
});

// ═══════════════════════════════════════════════════════
// PARTS CATALOG
// ═══════════════════════════════════════════════════════
const KIND_BADGE={light:"badge-light",equipment:"badge-equip",bar:"badge-bar",none:"badge-none"};

function renderCatalog(filter=""){
  const parts=(_catalog?.parts||[]).filter(p=>
    !filter||p.display_name.toLowerCase().includes(filter.toLowerCase())||
    p.part_id.toLowerCase().includes(filter.toLowerCase())
  );
  $("catalog-tbody").innerHTML=parts.map(p=>`
    <tr>
      <td style="font-weight:600">${esc(p.display_name)}</td>
      <td style="color:var(--muted);font-size:11px">${esc(p.category||"")}</td>
      <td><span class="badge ${KIND_BADGE[p.render_kind]||"badge-none"}">${esc(p.render_kind||"none")}</span></td>
      <td><span class="badge ${deriveDiagramFlag(p)?"badge-on":"badge-off"}">${deriveDiagramFlag(p)?"Yes":"No"}</span></td>
      <td><div class="view-chips">${(p.default_views||[]).map(v=>`<span class="chip">${v}</span>`).join("")}</div></td>
      <td><button class="btn btn-secondary btn-sm" onclick="openEditModal('${esc(p.part_id)}')">Edit</button></td>
    </tr>`).join("");
}

$("catalog-search").addEventListener("input",e=>renderCatalog(e.target.value));
$("btn-reload-catalog").addEventListener("click", async()=>{
  _catalog=await api("/api/catalog"); renderCatalog($("catalog-search").value); toast("Reloaded","success");
});

// ═══════════════════════════════════════════════════════
// EDIT PART MODAL (with images section)
// ═══════════════════════════════════════════════════════
let _editingPartId=null;

function syncModalDiagramStatus(){
  const rk=$("m-render-kind").value;
  const views=$("m-views").value.split(",").map(s=>s.trim()).filter(Boolean);
  $("m-diagram-status").textContent=isDiagramConfigured(rk, views)?"Yes":"No";
}

function onModalRenderKindChange(){
  const rk=$("m-render-kind").value;
  const showImgs=["equipment","bar"].includes(rk);
  const showSizes=["light","none"].includes(rk);
  $("modal-images-section").hidden=!showImgs;
  if(!$("modal-images-section").hidden) buildModalImageSection();
  $("modal-sizes-section").hidden=!showSizes;
  if(!$("modal-sizes-section").hidden) buildModalSizeSection();
  buildAltImageSection();
  syncModalDiagramStatus();
}

function buildModalImageSection(){
  const assetKey=$("m-asset-key").value.trim()||$("m-part-id").value.trim();
  const allViews=["front","side","top","rear"];
  const assetMap=getPartTypeAssetMap($("m-render-kind").value);
  // Read existing sizes from catalog entry
  const catalogPart=(_catalog?.parts||[]).find(p=>p.part_id===_editingPartId);
  const existingSizes=catalogPart?.size_per_view||{};

  $("modal-images-grid").innerHTML=allViews.map(view=>{
    const manifestPath=assetKey&&assetMap?.[assetKey]?.[view]
      ?"/assets/"+assetMap[assetKey][view]:null;
    const upld=_modalUploadedImages[view];
    const deleted=_modalDeletedViews.has(view);
    const hasImg=!deleted&&!!(manifestPath||upld);
    const sz=existingSizes[view]||{};
    const carSrc=`/assets/vehicles/PIU_${view}.png`;
    return `<div class="pm-view-row" data-view="${view}">
      <div class="pm-view-thumb ${hasImg?"has-file":""}" id="muz-${view}" title="Click to upload ${view} image">
        <input type="file" accept="image/*" data-view="${view}" class="muz-input" />
        <img id="muz-prev-${view}"
          ${upld?`src="${upld.dataUrl}"`:manifestPath&&!deleted?`src="${manifestPath}" onerror="this.style.display='none'"`:""} />
        ${!hasImg?'<span>🖼️</span>':""}
        <div class="pm-view-label">${view}</div>
      </div>
      <div class="pm-size-panel" id="modal-vs-${view}" ${hasImg?"":"style='display:none'"}>
        <label>Render size (inches)</label>
        <div class="pm-size-row">
          <span>W</span>
          <input type="number" id="modal-vw-${view}" class="modal-vw" data-view="${view}"
            value="${sz.w||""}" step="0.01" min="0.01" max="8" placeholder="—" />
          <span style="margin:0 2px">×</span>
          <span>H</span>
          <input type="number" id="modal-vh-${view}" class="modal-vh" data-view="${view}"
            value="${sz.h||""}" step="0.01" min="0.01" max="6" placeholder="—" />
          <button type="button" class="ar-lock-btn" id="ar-lock-${view}" data-view="${view}" data-locked="true" title="Lock aspect ratio" style="background:none;border:1px solid var(--border);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:13px;line-height:1.4;margin-left:2px">🔒</button>
        </div>
        <button class="btn btn-danger btn-sm modal-del-view" data-view="${view}" style="margin-top:6px;width:fit-content">🗑 Remove image</button>
      </div>
      <div class="pm-car-preview ${hasImg&&sz.w&&sz.h?"visible":""}" id="modal-preview-${view}">
        <img class="car-bg" src="${carSrc}" onerror="this.src=''" />
        <div class="part-overlay" id="modal-pov-${view}" style="${buildOverlayStyle(sz.w||0,sz.h||0,PM_PREVIEW_ANCHORS[view]||PM_PREVIEW_ANCHORS.front)}"></div>
        <span class="scale-note">~${PM_PREVIEW_SCALE}px/in</span>
      </div>
    </div>`;
  }).join("");

  // For equipment/bar: detect aspect ratio from existing manifest images
  const isEquip=["equipment","bar"].includes($("m-render-kind").value);
  if(isEquip){
    const assetKeyNow=$("m-asset-key").value.trim()||$("m-part-id").value.trim();
    allViews.forEach(view=>{
      const mPath=assetKeyNow&&assetMap?.[assetKeyNow]?.[view]?"/assets/"+assetMap[assetKeyNow][view]:null;
      if(mPath&&!_viewAspectRatios[view]){
        const probe=new Image();
        probe.onload=()=>{
          if(probe.naturalWidth&&probe.naturalHeight)
            _viewAspectRatios[view]=probe.naturalWidth/probe.naturalHeight;
        };
        probe.src=mPath;
      }
    });
  }

  // Upload inputs
  $("modal-images-grid").querySelectorAll(".muz-input").forEach(inp=>{
    inp.addEventListener("change",e=>{
      const file=e.target.files[0]; if(!file) return;
      const view=e.target.dataset.view;
      const ak=$("m-asset-key").value.trim()||$("m-part-id").value.trim();
      const reader=new FileReader();
      reader.onload=ev=>{
        const b64=ev.target.result.split(",")[1];
        _modalUploadedImages[view]={filename:`${ak}_${view}.png`,b64,dataUrl:ev.target.result};
        _modalDeletedViews.delete(view);
        $(`muz-prev-${view}`).src=ev.target.result;
        $(`muz-${view}`).classList.add("has-file");
        $(`modal-vs-${view}`).style.display="";
        // Detect and store aspect ratio from uploaded image
        if(["equipment","bar"].includes($("m-render-kind").value)){
          const probe=new Image();
          probe.onload=()=>{
            if(probe.naturalWidth&&probe.naturalHeight){
              _viewAspectRatios[view]=probe.naturalWidth/probe.naturalHeight;
              // Auto-fill H from existing W (or vice versa) once ratio is known
              const wEl=$(`modal-vw-${view}`); const hEl=$(`modal-vh-${view}`);
              if(wEl&&hEl){
                const w=parseFloat(wEl.value);
                if(w>0) hEl.value=(w/_viewAspectRatios[view]).toFixed(2);
              }
              updateModalCarPreview(view);
            }
          };
          probe.src=ev.target.result;
        }
        updateModalCarPreview(view);
      };
      reader.readAsDataURL(file);
    });
  });

  // AR lock toggle buttons
  $("modal-images-grid").querySelectorAll(".ar-lock-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const wasLocked=btn.dataset.locked==="true";
      btn.dataset.locked=(!wasLocked).toString();
      btn.textContent=wasLocked?"🔓":"🔒";
      // When locking: capture ratio from current W/H if both filled
      if(!wasLocked){
        const v=btn.dataset.view;
        const w=parseFloat($(`modal-vw-${v}`)?.value)||0, h=parseFloat($(`modal-vh-${v}`)?.value)||0;
        if(w>0&&h>0) _viewAspectRatios[v]=w/h;
      }
    });
  });

  // Size input live preview — link W↔H when lock button is engaged
  $("modal-images-grid").querySelectorAll(".modal-vw,.modal-vh").forEach(inp=>{
    inp.addEventListener("input",e=>{
      const view=e.target.dataset.view;
      const lockBtn=$(`ar-lock-${view}`);
      if(lockBtn?.dataset.locked==="true"&&_viewAspectRatios[view]){
        const ratio=_viewAspectRatios[view];
        if(e.target.classList.contains("modal-vw")){
          const w=parseFloat(e.target.value);
          if(w>0&&$(`modal-vh-${view}`)) $(`modal-vh-${view}`).value=(w/ratio).toFixed(2);
        } else {
          const h=parseFloat(e.target.value);
          if(h>0&&$(`modal-vw-${view}`)) $(`modal-vw-${view}`).value=(h*ratio).toFixed(2);
        }
      }
      updateModalCarPreview(view);
    });
  });

  // Delete buttons
  $("modal-images-grid").querySelectorAll(".modal-del-view").forEach(btn=>{
    btn.addEventListener("click",e=>{
      const view=e.target.dataset.view;
      _modalDeletedViews.add(view);
      delete _modalUploadedImages[view];
      const thumb=$(`muz-${view}`);
      thumb.classList.remove("has-file");
      const img=$(`muz-prev-${view}`); if(img){img.src="";img.style.display="none";}
      const sp=$(`modal-vs-${view}`); if(sp) sp.style.display="none";
      const pv=$(`modal-preview-${view}`); if(pv) pv.classList.remove("visible");
    });
  });
}

function updateModalCarPreview(view){
  const w=parseFloat($(`modal-vw-${view}`)?.value)||0;
  const h=parseFloat($(`modal-vh-${view}`)?.value)||0;
  const preview=$(`modal-preview-${view}`);
  const overlay=$(`modal-pov-${view}`);
  if(!preview||!overlay) return;
  const anchor=PM_PREVIEW_ANCHORS[view]||PM_PREVIEW_ANCHORS.front;
  if(w&&h){
    preview.classList.add("visible");
    overlay.style.cssText=buildOverlayStyle(w,h,anchor);
  } else {
    overlay.style.display="none";
  }
}

function openEditModal(partId){
  const p=(_catalog?.parts||[]).find(x=>x.part_id===partId); if(!p)return;
  _editingPartId=partId;
  Object.keys(_modalUploadedImages).forEach(k=>delete _modalUploadedImages[k]);
  _modalDeletedViews.clear();
  Object.keys(_altUploadedImages).forEach(k=>delete _altUploadedImages[k]);
  Object.keys(_altDeletedViews).forEach(k=>delete _altDeletedViews[k]);
  Object.keys(_viewAspectRatios).forEach(k=>delete _viewAspectRatios[k]);
  $("m-display-name").value=p.display_name||"";
  $("m-part-id").value=p.part_id||"";
  $("m-category").value=p.category||"equipment_note";
  $("m-render-kind").value=p.render_kind||"none";
  $("m-asset-key").value=p.asset_key||"";
  $("m-color-profile").value=p.default_color_profile||"";
  $("m-qty-policy").value=p.render_quantity_policy||"location_slots";
  $("m-views").value=(p.default_views||[]).join(", ");
  $("m-location-key").value=p.default_location_key||"";
  $("m-aliases").value=(p.aliases||[]).join("\n");
  syncModalDiagramStatus();
  buildModalLocSection(p.display_name);
  // accessory_of
  const accOf=p.accessory_of;
  $("m-accessory-of").value=Array.isArray(accOf)?accOf.join(", "):(accOf||"");
  // populate accessory suggestions from all part display names
  $("m-accessory-suggestions").innerHTML=(_catalog?.parts||[])
    .map(x=>`<option value="${esc(x.display_name)}">`).join("");
  // co_part_rules
  buildCopartRulesTable(p.co_part_rules||[]);
  const showImgs=["equipment","bar"].includes(p.render_kind||"none");
  const showSizes=["light","none"].includes(p.render_kind||"none");
  $("modal-images-section").hidden=!showImgs;
  if(showImgs) buildModalImageSection();
  $("modal-sizes-section").hidden=!showSizes;
  if(showSizes) buildModalSizeSection();
  $("edit-modal").classList.add("open");
}

// ── Location chips for part-type edit modal ──────────────────────────────────
function _allKnownLocations(){
  return allKnownLocationNames();
}

function buildModalLocSection(partDisplayName){
  const existing=(_workbookRules?.part_rules?.[partDisplayName]?.locations)||[];
  $("modal-loc-input").value="";
  renderLocChips(existing);
  // Populate datalist with all known locations not already assigned
  const all=_allKnownLocations();
  $("modal-loc-suggestions").innerHTML=all.map(l=>`<option value="${esc(l)}">`).join("");
}

function renderLocChips(locs){
  $("modal-loc-chips").innerHTML=locs.map(l=>
    `<span class="loc-chip">${esc(l)}<button class="loc-chip-rm" data-loc="${esc(l)}" title="Remove">✕</button></span>`
  ).join("");
  $("modal-loc-chips").querySelectorAll(".loc-chip-rm").forEach(btn=>
    btn.addEventListener("click",()=>{
      const remaining=getCurrentModalLocs().filter(x=>x!==btn.dataset.loc);
      renderLocChips(remaining);
    })
  );
}

function getCurrentModalLocs(){
  return [...$("modal-loc-chips").querySelectorAll(".loc-chip-rm")].map(b=>b.dataset.loc);
}

function addModalLoc(){
  const val=$("modal-loc-input").value.trim().toUpperCase();
  if(!val)return;
  const current=getCurrentModalLocs();
  if(!current.includes(val)) renderLocChips([...current,val]);
  $("modal-loc-input").value="";
}

$("btn-modal-add-loc").addEventListener("click",addModalLoc);
$("modal-loc-input").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();addModalLoc();}});

$("modal-close").addEventListener("click",()=>$("edit-modal").classList.remove("open"));
// ── Co-Part Rules table ──────────────────────────────────────────────────────
function _cprOverrideFields(prefix, obj){
  const skip=!!(obj&&obj.skip);
  let pat=(obj&&obj.pattern)||"";
  if(pat==="horizontal") pat="mirror";
  const side=(obj&&obj.side)||"";
  const asset=(obj&&obj.asset_key)||"";
  return `<div style="display:flex;flex-direction:column;gap:2px">
    <div style="display:flex;gap:4px;align-items:center">
      <input type="checkbox" class="${prefix}-skip" id="${prefix}-skip-cb" ${skip?"checked":""} style="margin:0" />
      <label for="${prefix}-skip-cb" style="font-size:11px;color:var(--danger,#c0392b);font-weight:600;cursor:pointer">Don't render</label>
    </div>
    <div style="display:flex;gap:3px;align-items:center">
      <span style="color:var(--muted);width:42px;font-size:10px;flex-shrink:0">Pattern</span>
      <select class="${prefix}-pattern" style="flex:1;font-size:11px;padding:1px 2px">
        <option value="">—</option>
        <option value="single"${pat==="single"?" selected":""}>single</option>
        <option value="mirror"${pat==="mirror"?" selected":""}>mirror</option>
        <option value="vertical"${pat==="vertical"?" selected":""}>vertical</option>
      </select>
    </div>
    <div style="display:flex;gap:3px;align-items:center">
      <span style="color:var(--muted);width:42px;font-size:10px;flex-shrink:0">Side</span>
      <select class="${prefix}-side" style="flex:1;font-size:11px;padding:1px 2px">
        <option value="">—</option>
        <option value="driver"${side==="driver"?" selected":""}>driver</option>
        <option value="passenger"${side==="passenger"?" selected":""}>passenger</option>
        <option value="center"${side==="center"?" selected":""}>center</option>
      </select>
    </div>
    <div style="display:flex;gap:3px;align-items:center">
      <span style="color:var(--muted);width:42px;font-size:10px;flex-shrink:0">Asset</span>
      <input type="text" class="${prefix}-asset" value="${esc(asset)}" placeholder="asset_key" style="flex:1;font-size:11px;padding:1px 3px" />
    </div>
  </div>`;
}

function buildCopartRulesTable(rules){
  const tbody=$("copart-rules-tbody");
  tbody.innerHTML="";
  const typeNames=(_catalog?.parts||[]).map(p=>p.display_name||p.part_id).filter(Boolean);
  const modelNames=(_partsLib?.parts||[]).map(p=>p.model_number||p.display_name).filter(Boolean);
  const copartOptions=[...new Set([...typeNames,...modelNames])];
  const datalistId="cpr-copart-list";
  const existingDl=document.getElementById(datalistId);
  if(existingDl) existingDl.remove();
  const dl=document.createElement("datalist");
  dl.id=datalistId;
  copartOptions.forEach(n=>{const o=document.createElement("option");o.value=n;dl.appendChild(o);});
  document.body.appendChild(dl);
  (rules||[]).forEach((rule,i)=>{
    const tr=document.createElement("tr");
    tr.style.borderTop="1px solid var(--border)";
    tr.innerHTML=`
      <td style="padding:4px"><input type="text" class="cpr-copart" list="${datalistId}" value="${esc(rule.co_part||"")}" placeholder="part display name" style="width:100%;font-size:11px" /></td>
      <td style="padding:4px">${_cprOverrideFields("cpr-present",rule.if_present)}</td>
      <td style="padding:4px">${_cprOverrideFields("cpr-absent",rule.if_absent)}</td>
      <td style="padding:4px;text-align:center;vertical-align:top"><button class="btn btn-danger btn-sm cpr-del" data-idx="${i}" style="padding:2px 6px">✕</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".cpr-del").forEach(btn=>btn.addEventListener("click",()=>{
    const rows=[...tbody.querySelectorAll("tr")];
    rows[parseInt(btn.dataset.idx)]?.remove();
    buildAltImageSection();
  }));
  buildAltImageSection();
}

function buildModalSizeSection(){
  const allViews=["front","side","top","rear"];
  const catalogPart=(_catalog?.parts||[]).find(p=>p.part_id===_editingPartId);
  const existingSizes=catalogPart?.size_per_view||{};
  $("modal-sizes-grid").innerHTML=allViews.map(view=>{
    const sz=existingSizes[view]||{};
    return `<div class="pm-view-row" data-view="${view}" style="align-items:center;padding:6px 0">
      <div class="pm-view-label" style="min-width:48px;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase">${view}</div>
      <div class="pm-size-panel" style="display:block;margin-left:10px">
        <div class="pm-size-row">
          <span>W</span>
          <input type="number" id="modal-vw-${view}" class="modal-vw" data-view="${view}"
            value="${sz.w||""}" step="0.01" min="0.01" max="8" placeholder="—" style="width:64px" />
          <span style="margin:0 4px">×</span>
          <span>H</span>
          <input type="number" id="modal-vh-${view}" class="modal-vh" data-view="${view}"
            value="${sz.h||""}" step="0.01" min="0.01" max="6" placeholder="—" style="width:64px" />
          <span style="margin-left:4px;font-size:11px;color:var(--muted)">in</span>
          <button type="button" class="ar-lock-btn" id="ar-lock-${view}" data-view="${view}" data-locked="false" title="Lock aspect ratio" style="background:none;border:1px solid var(--border);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:13px;line-height:1.4;margin-left:4px">🔓</button>
        </div>
      </div>
    </div>`;
  }).join("");

  // AR lock toggle
  $("modal-sizes-grid").querySelectorAll(".ar-lock-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const wasLocked=btn.dataset.locked==="true";
      btn.dataset.locked=(!wasLocked).toString();
      btn.textContent=wasLocked?"🔓":"🔒";
      if(!wasLocked){
        const v=btn.dataset.view;
        const w=parseFloat($(`modal-vw-${v}`)?.value)||0, h=parseFloat($(`modal-vh-${v}`)?.value)||0;
        if(w>0&&h>0) _viewAspectRatios[v]=w/h;
      }
    });
  });

  // W↔H linking when locked
  $("modal-sizes-grid").querySelectorAll(".modal-vw,.modal-vh").forEach(inp=>{
    inp.addEventListener("input",e=>{
      const view=e.target.dataset.view;
      const lockBtn=$(`ar-lock-${view}`);
      if(lockBtn?.dataset.locked==="true"&&_viewAspectRatios[view]){
        const ratio=_viewAspectRatios[view];
        if(e.target.classList.contains("modal-vw")){
          const w=parseFloat(e.target.value);
          if(w>0) $(`modal-vh-${view}`).value=(w/ratio).toFixed(2);
        } else {
          const h=parseFloat(e.target.value);
          if(h>0) $(`modal-vw-${view}`).value=(h*ratio).toFixed(2);
        }
      }
    });
  });
}

function getAltAssetKeys(){
  const rows=[...$("copart-rules-tbody").querySelectorAll("tr")];
  const keys=new Set();
  rows.forEach(tr=>{
    const p=tr.querySelector(".cpr-present-asset")?.value.trim();
    const a=tr.querySelector(".cpr-absent-asset")?.value.trim();
    if(p) keys.add(p);
    if(a) keys.add(a);
  });
  const primary=$("m-asset-key")?.value.trim();
  if(primary) keys.delete(primary);
  return [...keys].filter(Boolean);
}

function buildAltImageSection(){
  const rk=$("m-render-kind")?.value;
  const sec=$("modal-alt-images-section");
  if(!sec) return;
  if(!["equipment","bar"].includes(rk)){ sec.hidden=true; return; }
  const altKeys=getAltAssetKeys();
  sec.hidden=altKeys.length===0;
  if(!altKeys.length) return;
  const assetMap=getPartTypeAssetMap(rk);
  const grid=$("modal-alt-images-grid");
  grid.innerHTML=altKeys.map(ak=>{
    const akId=ak.replace(/[^a-z0-9]/gi,"_");
    const views=["front","side","top","rear"];
    return `<div style="margin-bottom:14px">
      <div style="font-weight:600;font-size:12px;margin-bottom:6px;color:var(--navy);font-family:monospace">${esc(ak)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        ${views.map(view=>{
          const upKey=`${ak}:${view}`;
          const upld=_altUploadedImages[upKey];
          const deleted=(_altDeletedViews[ak]||new Set()).has(view);
          const manifestPath=assetMap?.[ak]?.[view]?"/assets/"+assetMap[ak][view]:null;
          const hasImg=!deleted&&!!(manifestPath||upld);
          return `<div style="display:flex;flex-direction:column;align-items:center;gap:4px">
            <div class="pm-view-thumb ${hasImg?"has-file":""}" id="alt-muz-${akId}-${view}" title="Upload ${view} image for ${esc(ak)}" style="width:72px;height:72px">
              <input type="file" accept="image/*" class="alt-muz-input" data-alt-key="${esc(ak)}" data-view="${view}" />
              <img id="alt-muz-prev-${akId}-${view}"
                ${upld?`src="${upld.dataUrl}"`:manifestPath&&!deleted?`src="${manifestPath}" onerror="this.style.display='none'"`:""} />
              ${!hasImg?'<span style="font-size:18px">🖼️</span>':""}
            </div>
            <div style="font-size:10px;color:var(--muted)">${view}</div>
            ${hasImg?`<button class="btn btn-danger btn-sm alt-del-view" data-alt-key="${esc(ak)}" data-view="${view}" style="font-size:9px;padding:1px 5px">✕</button>`:""}
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }).join("");

  grid.querySelectorAll(".alt-muz-input").forEach(inp=>{
    inp.addEventListener("change",e=>{
      const file=e.target.files[0]; if(!file) return;
      const view=e.target.dataset.view;
      const ak=e.target.dataset.altKey;
      const akId=ak.replace(/[^a-z0-9]/gi,"_");
      const reader=new FileReader();
      reader.onload=ev=>{
        const b64=ev.target.result.split(",")[1];
        _altUploadedImages[`${ak}:${view}`]={filename:`${ak}_${view}.png`,b64,dataUrl:ev.target.result};
        if(!_altDeletedViews[ak]) _altDeletedViews[ak]=new Set();
        _altDeletedViews[ak].delete(view);
        const prev=$(`alt-muz-prev-${akId}-${view}`);
        if(prev) prev.src=ev.target.result;
        $(`alt-muz-${akId}-${view}`)?.classList.add("has-file");
        buildAltImageSection();
      };
      reader.readAsDataURL(file);
    });
  });

  grid.querySelectorAll(".alt-del-view").forEach(btn=>{
    btn.addEventListener("click",e=>{
      const view=e.target.dataset.view;
      const ak=e.target.dataset.altKey;
      if(!_altDeletedViews[ak]) _altDeletedViews[ak]=new Set();
      _altDeletedViews[ak].add(view);
      delete _altUploadedImages[`${ak}:${view}`];
      buildAltImageSection();
    });
  });
}

// Rebuild alt image section when asset key fields in co-part rules change
$("copart-rules-tbody").addEventListener("blur",e=>{
  if(e.target.classList.contains("cpr-present-asset")||e.target.classList.contains("cpr-absent-asset")){
    buildAltImageSection();
  }
},true);

function _readCprOverride(tr, prefix){
  const skip=tr.querySelector(`.${prefix}-skip`)?.checked||false;
  if(skip) return {skip:true};
  const pat=tr.querySelector(`.${prefix}-pattern`)?.value||"";
  const side=tr.querySelector(`.${prefix}-side`)?.value||"";
  const asset=tr.querySelector(`.${prefix}-asset`)?.value.trim()||"";
  const obj={};
  if(pat) obj.pattern=pat;
  if(side) obj.side=side;
  if(asset) obj.asset_key=asset;
  return Object.keys(obj).length?obj:null;
}

function readCopartRules(){
  const rows=[...$("copart-rules-tbody").querySelectorAll("tr")];
  return rows.map(tr=>{
    const co=tr.querySelector(".cpr-copart").value.trim();
    const rule={co_part:co};
    const ip=_readCprOverride(tr,"cpr-present");
    const ia=_readCprOverride(tr,"cpr-absent");
    if(ip) rule.if_present=ip;
    if(ia) rule.if_absent=ia;
    return rule;
  }).filter(r=>r.co_part);
}

$("btn-add-copart-rule").addEventListener("click",()=>{
  const existing=readCopartRules();
  buildCopartRulesTable([...existing,{co_part:"",if_present:{},if_absent:{}}]);
});

$("btn-modal-cancel").addEventListener("click",()=>$("edit-modal").classList.remove("open"));
$("edit-modal").addEventListener("click",e=>{if(e.target===$("edit-modal"))$("edit-modal").classList.remove("open");});

$("m-asset-key").addEventListener("blur",()=>{
  const rk=$("m-render-kind").value;
  if(["equipment","bar"].includes(rk)&&!$("modal-images-section").hidden) buildModalImageSection();
});
$("m-views").addEventListener("input",syncModalDiagramStatus);

$("btn-modal-save").addEventListener("click", async()=>{
  const btn=$("btn-modal-save"); btn.disabled=true; btn.textContent="Saving…";
  try{
    const assetKey=$("m-asset-key").value.trim();
    // manifestKey mirrors the fallback used in buildModalImageSection so reads/writes target the same slot
    const manifestKey=assetKey||$("m-part-id").value.trim();
    const rk=$("m-render-kind").value;
    // Upload new images + apply deletions to the correct manifest asset bucket
    if(["equipment","bar"].includes(rk)){
      const assetMap=getPartTypeAssetMap(rk);
      const assetFolder=partTypeUploadFolder(rk);
      const viewMap={...(assetMap[manifestKey]||{})};
      // Apply deletions
      _modalDeletedViews.forEach(v=>delete viewMap[v]);
      // Upload new
      for(const [view,img] of Object.entries(_modalUploadedImages)){
        const res=await api("/api/assets/upload",{folder:assetFolder,filename:img.filename,data:img.b64});
        if(!res.ok) throw new Error("Upload failed: "+res.error);
        viewMap[view]=`${assetFolder}/${img.filename}`;
      }
      assetMap[manifestKey]=viewMap;
      // Also save alternate asset images from co-part rules
      const altKeys=new Set([
        ...Object.keys(_altUploadedImages).map(k=>k.split(":")[0]),
        ...Object.keys(_altDeletedViews)
      ]);
      for(const ak of altKeys){
        const altViewMap={...(assetMap[ak]||{})};
        (_altDeletedViews[ak]||new Set()).forEach(v=>delete altViewMap[v]);
        for(const [upKey,img] of Object.entries(_altUploadedImages)){
          const [altKey,view]=upKey.split(":");
          if(altKey!==ak) continue;
          const res=await api("/api/assets/upload",{folder:assetFolder,filename:img.filename,data:img.b64});
          if(!res.ok) throw new Error("Upload failed: "+res.error);
          altViewMap[view]=`${assetFolder}/${img.filename}`;
        }
        assetMap[ak]=altViewMap;
      }
      await api("/api/manifest/save",_manifest);
    }
    // Collect per-view render sizes
    const size_per_view={};
    ["front","side","top","rear"].forEach(v=>{
      const w=parseFloat($(`modal-vw-${v}`)?.value)||0;
      const h=parseFloat($(`modal-vh-${v}`)?.value)||0;
      if(w&&h) size_per_view[v]={w,h};
    });
    const views=rk==="none"?[]:$("m-views").value.split(",").map(s=>s.trim()).filter(Boolean);
    const aliases=$("m-aliases").value.split("\n").map(s=>s.trim()).filter(Boolean);
    const diag=isDiagramConfigured(rk, views);
    const updated={
      part_id:$("m-part-id").value.trim(),
      display_name:$("m-display-name").value.trim(),
      category:$("m-category").value,
      render_kind:rk,
      diagram:diag,
      default_views:views,
    };
    if(assetKey) updated.asset_key=assetKey;
    if($("m-color-profile").value) updated.default_color_profile=$("m-color-profile").value;
    if($("m-location-key").value.trim()) updated.default_location_key=$("m-location-key").value.trim();
    if(rk!=="none") updated.render_quantity_policy=$("m-qty-policy").value;
    if(aliases.length) updated.aliases=aliases;
    if(Object.keys(size_per_view).length) updated.size_per_view=size_per_view;
    // accessory_of
    const accOfRaw=$("m-accessory-of").value.trim();
    if(accOfRaw){
      const parts=accOfRaw.split(",").map(s=>s.trim()).filter(Boolean);
      updated.accessory_of=parts.length===1?parts[0]:parts;
    }
    // co_part_rules
    const cpr=readCopartRules();
    updated.co_part_rules=cpr;
    const idx=_catalog.parts.findIndex(p=>p.part_id===_editingPartId);
    // Spread-merge: preserve any catalog fields the modal doesn't expose
    // (is_fixture, group_shapes, quantity_rules, conditions, model_remaps, etc.)
    if(idx>=0) _catalog.parts[idx]={..._catalog.parts[idx], ...updated};
    else _catalog.parts.push(updated);
    const res=await api("/api/catalog/save",_catalog);
    if(!res.ok) throw new Error(res.error);

    // Save location assignments back to workbook_rules part_rules
    const displayName=updated.display_name;
    const newLocs=getCurrentModalLocs();
    if(_workbookRules){
      if(!_workbookRules.part_rules) _workbookRules.part_rules={};
      if(!_workbookRules.part_rules[displayName]) _workbookRules.part_rules[displayName]={};
      _workbookRules.part_rules[displayName].locations=newLocs;
      // If name changed, migrate the old key
      const oldPart=_catalog.parts.find(p=>p.part_id===_editingPartId);
      if(oldPart&&oldPart.display_name!==displayName&&_workbookRules.part_rules[oldPart.display_name]){
        _workbookRules.part_rules[displayName]={
          ..._workbookRules.part_rules[oldPart.display_name],
          locations:newLocs
        };
        delete _workbookRules.part_rules[oldPart.display_name];
      }
      const wrRes=await apiSave("/api/workbook-rules/save",_workbookRules);
      if(!wrRes.ok) throw new Error("Workbook rules save failed: "+wrRes.error);
    }

    refreshSharedUi();
    toast("Part saved!","success"); $("edit-modal").classList.remove("open");
  }catch(err){toast("Save failed: "+err,"error");}
  btn.disabled=false; btn.textContent="Save Changes";
});

$("btn-modal-delete").addEventListener("click", async()=>{
  if(!confirm("Delete this part from the catalog?"))return;
  const deletedPart = _catalog.parts.find(p=>p.part_id===_editingPartId);
  const deletedName = deletedPart?.display_name;
  _catalog.parts=_catalog.parts.filter(p=>p.part_id!==_editingPartId);
  const res=await api("/api/catalog/save",_catalog);
  if(!res.ok){toast("Delete failed: "+res.error,"error");return;}

  // Remove from template_sections so it no longer appears in generated template
  if(deletedName&&_workbookRules?.template_sections){
    _workbookRules.template_sections.forEach(sec=>{
      sec.parts=sec.parts.filter(p=>p.name!==deletedName);
    });
    await apiSave("/api/workbook-rules/save",_workbookRules);
  }

  refreshSharedUi();
  toast("Part deleted","success");
  $("edit-modal").classList.remove("open");
});
