// ═══════════════════════════════════════════════════════
// SIZE RULES
// ═══════════════════════════════════════════════════════
const SIZE_CLASSES=["sm","md","lg","long","tracer","rd","sq"];
const SIZE_PX={sm:[36,9],md:[48,24],lg:[72,57],long:[72,9],tracer:[56,9],rd:[16,16],sq:[12,12]};

function initSizeRules(){ renderSizeDefs(); renderSizeRules(); }

function renderSizeDefs(){
  const defs=_manifest?.size_rule_definitions||{};
  $("size-defs-tbody").innerHTML=Object.entries(defs).map(([id,d])=>sizeDefRow(id,d)).join("");
  bindSizeDefEvents();
}

function sizeDefRow(id,d){
  const VLIST=["front","rear","side","top"];
  const views=d.views||{};
  // Use front view as preview reference; fall back to legacy fields
  const fv=views.front||{w:d.width_in||0.3,h:d.height_in||0.3};
  const pw=Math.min(Math.round(fv.w*96),80);
  const ph=Math.min(Math.round(fv.h*96),40);
  // Sub-rows for per-view editing (hidden by default)
  const subRows=VLIST.map(v=>{
    const vd=views[v]||{w:fv.w,h:fv.h};
    const vpw=Math.min(Math.round(vd.w*96),80);
    const vph=Math.min(Math.round(vd.h*96),40);
    return `<tr class="sd-view-sub" data-view="${v}" style="display:none">
      <td colspan="2" style="padding-left:28px">
        <span class="sd-view-badge">${v}</span>
      </td>
      <td>
        <div style="display:flex;align-items:center;gap:4px">
          W <input class="sd-vw" data-view="${v}" type="number" value="${vd.w}" step="0.001" min="0.01" max="8" />
          H <input class="sd-vh" data-view="${v}" type="number" value="${vd.h}" step="0.001" min="0.01" max="4" />
        </div>
      </td>
      <td></td>
      <td><div class="sp-rect sd-view-preview" style="width:${vpw}px;height:${vph}px"></div></td>
      <td></td>
    </tr>`;
  }).join("");
  return `<tr class="sd-main-row">
    <td><input class="sd-id" value="${esc(id)}" type="text" style="width:70px" /></td>
    <td><input class="sd-label" value="${esc(d.label||'')}" type="text" /></td>
    <td><button class="btn btn-secondary btn-sm sd-expand-btn">▼ Views</button></td>
    <td><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="sd-ar" ${d.maintain_aspect_ratio?"checked":""}> Maintain</label></td>
    <td><div class="sp-rect sd-preview" style="width:${pw}px;height:${ph}px"></div></td>
    <td><button class="btn btn-danger btn-sm sd-del">✕</button></td>
  </tr>${subRows}`;
}

function bindSizeDefEvents(){
  // Expand/collapse per-view sub-rows
  $("size-defs-tbody").querySelectorAll(".sd-expand-btn").forEach(btn=>{
    btn.addEventListener("click",e=>{
      const mainRow=e.target.closest("tr");
      let sib=mainRow.nextElementSibling;
      while(sib&&sib.classList.contains("sd-view-sub")){
        const hidden=sib.style.display==="none";
        sib.style.display=hidden?"":"none";
        sib=sib.nextElementSibling;
      }
      btn.textContent=btn.textContent.startsWith("▼")?"▲ Views":"▼ Views";
    });
  });
  // Live preview for per-view size inputs
  $("size-defs-tbody").querySelectorAll(".sd-vw,.sd-vh").forEach(inp=>{
    inp.addEventListener("input",e=>{
      const row=e.target.closest("tr");
      const w=parseFloat(row.querySelector(".sd-vw")?.value)||0.1;
      const h=parseFloat(row.querySelector(".sd-vh")?.value)||0.1;
      const prev=row.querySelector(".sd-view-preview");
      if(prev){prev.style.width=Math.min(Math.round(w*96),80)+"px";prev.style.height=Math.min(Math.round(h*96),40)+"px";}
      // Also update the main row front preview if this is the front view
      if(row.dataset.view==="front"){
        const mainPrev=row.previousElementSibling?.querySelector(".sd-preview");
        if(mainPrev){mainPrev.style.width=Math.min(Math.round(w*96),80)+"px";mainPrev.style.height=Math.min(Math.round(h*96),40)+"px";}
      }
    });
  });
  $("size-defs-tbody").querySelectorAll(".sd-del").forEach(b=>{
    b.addEventListener("click",e=>{
      // Remove main row + 4 view sub-rows
      const mainRow=e.target.closest("tr");
      let sib=mainRow.nextElementSibling;
      while(sib&&sib.classList.contains("sd-view-sub")){
        const next=sib.nextElementSibling;
        sib.remove();
        sib=next;
      }
      mainRow.remove();
    });
  });
}

$("btn-add-size-def").addEventListener("click",()=>{
  const newDef={label:"New Size",maintain_aspect_ratio:false,
    views:{front:{w:0.3,h:0.15},rear:{w:0.3,h:0.15},side:{w:0.2,h:0.1},top:{w:0.2,h:0.1}}};
  $("size-defs-tbody").insertAdjacentHTML("beforeend",sizeDefRow("new",newDef));
  bindSizeDefEvents();
});

function renderSizeRules(){
  const rules=_manifest?.part_number_size_rules||{};
  $("size-rules-tbody").innerHTML=Object.entries(rules).map(([pn,sc])=>sizeRuleRow(pn,sc)).join("");
  bindSizeRuleEvents();
}

function sizeRuleRow(pn,sc){
  const opts=SIZE_CLASSES.map(s=>`<option value="${s}" ${s===sc?"selected":""}>${s}</option>`).join("");
  const [pw,ph]=SIZE_PX[sc]||[20,8];
  return `<tr><td><input class="sr-pn" value="${esc(pn)}" type="text" /></td>
    <td><select class="sr-sc">${opts}</select></td>
    <td><div style="display:flex;align-items:center"><div class="sp-rect" style="width:${pw}px;height:${ph}px"></div></div></td>
    <td><button class="btn btn-danger btn-sm sr-del">✕</button></td></tr>`;
}

function bindSizeRuleEvents(){
  $("size-rules-tbody").querySelectorAll(".sr-sc").forEach(sel=>{
    sel.addEventListener("change",e=>{
      const r=e.target.closest("tr"), rect=r.querySelector(".sp-rect");
      const [pw,ph]=SIZE_PX[e.target.value]||[20,8];
      rect.style.width=pw+"px"; rect.style.height=ph+"px";
    });
  });
  $("size-rules-tbody").querySelectorAll(".sr-del").forEach(b=>b.addEventListener("click",e=>e.target.closest("tr").remove()));
}

$("btn-add-size-rule").addEventListener("click",()=>{
  $("size-rules-tbody").insertAdjacentHTML("beforeend",sizeRuleRow("","sm"));
  bindSizeRuleEvents();
});

$("btn-save-sizes").addEventListener("click",async()=>{
  const rules={};
  $("size-rules-tbody").querySelectorAll("tr").forEach(row=>{
    const pn=row.querySelector(".sr-pn")?.value?.trim();
    const sc=row.querySelector(".sr-sc")?.value;
    if(pn&&sc) rules[pn]=sc;
  });
  const defs={};
  $("size-defs-tbody").querySelectorAll(".sd-main-row").forEach(mainRow=>{
    const id=mainRow.querySelector(".sd-id")?.value?.trim();
    const label=mainRow.querySelector(".sd-label")?.value?.trim();
    const ar=mainRow.querySelector(".sd-ar")?.checked||false;
    if(!id) return;
    const views={};
    let sib=mainRow.nextElementSibling;
    while(sib&&sib.classList.contains("sd-view-sub")){
      const v=sib.dataset.view;
      const w=parseFloat(sib.querySelector(".sd-vw")?.value)||0;
      const h=parseFloat(sib.querySelector(".sd-vh")?.value)||0;
      if(v&&w&&h) views[v]={w,h};
      sib=sib.nextElementSibling;
    }
    defs[id]={label:label||id,maintain_aspect_ratio:ar,views};
  });
  _manifest.part_number_size_rules=rules;
  _manifest.size_rule_definitions=defs;
  const res=await apiSave("/api/manifest/save",_manifest);
  if(res.ok){ if(!res.proposed) toast("Size rules saved!","success"); }
  else toast("Save failed: "+res.error,"error");
});
