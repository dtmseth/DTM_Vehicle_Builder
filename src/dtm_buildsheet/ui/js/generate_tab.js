// ═══════════════════════════════════════════════════════
// GENERATE TAB
// ═══════════════════════════════════════════════════════
let fileB64=null, fileName=null, _parsedDraftId=null;

const dz=$("drop-zone");
dz.addEventListener("dragover", e=>{e.preventDefault();dz.classList.add("drag-over")});
dz.addEventListener("dragleave", ()=>dz.classList.remove("drag-over"));
dz.addEventListener("drop", e=>{e.preventDefault();dz.classList.remove("drag-over");handleFile(e.dataTransfer.files[0])});
$("file-input").addEventListener("change", e=>handleFile(e.target.files[0]));

function showProjectLoadedState(filename, filesizeStr) {
  $("fname").textContent = filename;
  $("fsize").textContent = filesizeStr;
  dz.hidden = true;
  $("file-loaded").style.display = "flex";
  show("card-proj");
  show("card-parts");
  $("btn-generate").disabled = false;
}

function handleFile(file) {
  if (!file) return;
  if (!file.name.endsWith(".xlsx")){alert("Please select an .xlsx file.");return;}
  fileName=file.name;
  const reader=new FileReader();
  reader.onload = async e => {
    fileB64=e.target.result.split(",")[1];
    logLine("Parsing workbook…");
    const res=await api("/parse",{filename:fileName,data:fileB64});
    if (res.ok) {
      _parsedDraftId = res.draft_id || null;
      renderInfo(res.info); renderParts(res.parts);
      showProjectLoadedState(file.name, fmt(file.size));
      logLine("Parsed — "+res.parts.length+" parts found.");

      // Show preview card and kick off an initial render
      if (_parsedDraftId) {
        show("card-preview");
        pvLoad(_parsedDraftId);
      }
    } else logLine("Parse error: "+res.error);
  };
  reader.readAsDataURL(file);
}

function renderInfo(info) {
  const pairs=[["Agency",info.Agency],["Project ID",info.ProjectID],["Quote #",info.QuoteNumber],
    ["Sales Rep",info.SalesRep],["Vehicle",info.VehicleType],["Contact",info.PrimaryContact],
    ["Phone",info.Phone],["Email",info.Email]];
  $("info-grid").innerHTML=pairs.map(([l,v])=>
    `<div class="info-item"><label>${l}</label><span class="${v?"":"empty"}">${v||"—"}</span></div>`
  ).join("");
}

function renderParts(parts) {
  $("parts-count").textContent=parts.length;
  $("parts-tbody").innerHTML=parts.map(p=>
    `<tr><td style="font-weight:500">${esc(p.name)}</td>
     <td style="color:var(--muted)">${esc(p.location||"—")}</td>
     <td>${esc(p.color||"—")}</td><td>${p.qty||"—"}</td>
     <td><span class="badge ${p.include?"badge-on":"badge-off"}">${p.include?"Yes":"No"}</span></td></tr>`
  ).join("");
}

$("btn-clear").addEventListener("click", ()=>{
  fileB64=null; fileName=null; _parsedDraftId=null;
  $("file-input").value="";
  $("file-loaded").style.display="none"; dz.hidden=false;
  hide("card-proj");hide("card-parts");hide("card-preview");
  hide("card-results");hide("card-warns");hide("card-output");
  hide("card-log");hide("reset-row");
  $("log-box").textContent=""; $("btn-generate").disabled=true;
});

// Reload preview button
$("btn-reload-preview").addEventListener("click", ()=>{
  if (_parsedDraftId) pvLoad(_parsedDraftId);
});

$("btn-generate").addEventListener("click", async ()=>{
  if(!fileB64 && !_parsedDraftId) return;
  $("btn-generate").disabled=true; $("spinner").style.display="block";
  $("btn-label").textContent="Generating…";
  hide("card-results");hide("card-warns");hide("card-output");hide("reset-row");
  logLine("Starting generation…");
  const res = _parsedDraftId
    ? await api("/api/draft/generate", { draft_id: _parsedDraftId })
    : await api("/generate", { filename: fileName, data: fileB64 });
  if(res.log) res.log.split("\n").forEach(l=>logLine(l));
  if(res.ok){
    $("result-banner").className="result-banner success";
    $("banner-icon").textContent="✅"; $("banner-msg").textContent="Build sheet generated successfully";
    $("banner-sub").textContent=res.output_name;
    $("stat-parts").textContent=res.parts_count; $("stat-pl").textContent=res.placements_count;
    $("stat-warn").textContent=res.warnings_count;
    $("stat-warn").style.color=res.warnings_count===0?"var(--green)":"var(--yellow)";
    show("card-results");
    if(res.all_warnings?.length){
      $("warn-list").innerHTML=res.all_warnings.map(w=>`<li class="warn-item">⚠️ ${esc(w)}</li>`).join("");
      show("card-warns");
    }
    $("out-name").textContent=res.output_name; $("out-path").textContent=res.output_path;
    window._outputPath=res.output_path; show("card-output");
  } else {
    $("result-banner").className="result-banner error";
    $("banner-icon").textContent="❌"; $("banner-msg").textContent="Generation failed";
    $("banner-sub").textContent=res.error||"Unknown error"; show("card-results");
  }
  $("spinner").style.display="none"; $("btn-label").textContent="⚡ Generate Build Sheet";
  $("btn-generate").disabled=false; show("reset-row");
});

// Workbook template regeneration
$("btn-regen-template").addEventListener("click", async ()=>{
  $("btn-regen-template").disabled=true;
  $("spinner-tpl").style.display="inline-block";
  $("tpl-label").textContent="Generating…";
  $("tpl-result").style.display="none";
  try {
    const res = await api("/api/template/generate", {});
    const el = $("tpl-result");
    el.style.display="block";
    if(res.ok){
      el.style.background="var(--green,#e8f5e9)"; el.style.color="#1b5e20";
      el.textContent=`✅ Saved: ${res.filename}`;
      loadTemplateInfo();
    } else {
      el.style.background="#fdecea"; el.style.color="#b71c1c";
      el.textContent=`❌ ${res.error}`;
    }
  } catch(e){
    const el=$("tpl-result");
    el.style.display="block"; el.style.background="#fdecea"; el.style.color="#b71c1c";
    el.textContent=`❌ ${e.message}`;
  }
  $("spinner-tpl").style.display="none";
  $("tpl-label").textContent="🔄 Regenerate Workbook Template";
  $("btn-regen-template").disabled=false;
});

$("btn-open").addEventListener("click", ()=>api("/open",{path:window._outputPath}));

$("btn-export-pdf").addEventListener("click", async ()=>{
  if(!window._outputPath)return;
  $("btn-export-pdf").disabled=true;
  $("pdf-spinner").style.display="inline-block";
  $("pdf-label").textContent="Exporting…";
  $("pdf-status").style.display="none";
  $("btn-open-pdf").style.display="none";
  const res=await api("/api/export/pdf",{output_path:window._outputPath});
  $("pdf-spinner").style.display="none";
  $("pdf-label").textContent="Export PDF";
  const el=$("pdf-status");
  el.style.display="block";
  if(res.ok){
    el.style.color="var(--green)"; el.textContent="✅ Exported: "+res.pdf_name;
    window._pdfPath=res.pdf_path; $("btn-open-pdf").style.display="block";
  } else {
    el.style.color="#c0392b"; el.textContent="❌ "+res.error;
  }
  $("btn-export-pdf").disabled=false;
});

$("btn-open-pdf").addEventListener("click", ()=>api("/open",{path:window._pdfPath}));

$("btn-reset").addEventListener("click", ()=>location.reload());

// ── Save-To folder picker ─────────────────────────────────────────────────
function updateSaveToDisplay(){
  const el=$("tpl-save-dir"); if(!el) return;
  const dir=(_appSettings||{}).template_save_dir||"";
  if(dir){ el.textContent=dir; el.title=dir; el.style.color="var(--navy)"; }
  else   { el.textContent="Default (workspace folder)"; el.title=""; el.style.color="var(--muted)"; }
}

$("btn-pick-save-dir").addEventListener("click", async()=>{
  const res=await api("/api/template/pick-folder");
  if(!res.ok) return;
  if(!_appSettings) _appSettings={};
  _appSettings.template_save_dir=res.path;
  await api("/api/app-settings/save",_appSettings);
  updateSaveToDisplay();
  autoRegenTemplate();
});

$("btn-clear-save-dir").addEventListener("click", async()=>{
  if(!_appSettings) _appSettings={};
  delete _appSettings.template_save_dir;
  await api("/api/app-settings/save",_appSettings);
  updateSaveToDisplay();
  autoRegenTemplate();
});

function autoRegenTemplate() {
  api("/api/template/generate", {}).then(loadTemplateInfo).catch(() => {});
}

function logLine(msg){show("card-log"); $("log-box").textContent+=msg+"\n"; $("log-box").scrollTop=$("log-box").scrollHeight;}
