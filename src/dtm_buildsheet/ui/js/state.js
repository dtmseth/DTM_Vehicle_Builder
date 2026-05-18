// ═══════════════════════════════════════════════════════
// SETTINGS — state + init
// ═══════════════════════════════════════════════════════
let _layouts=null, _manifest=null, _catalog=null, _workbookRules=null, _appSettings=null;
let _activeVehicle="PIU", _activeView="front";
let _selectedLocKey=null, _locsDirty=false;
const _uploadedImages={};  // view → {filename, b64, dataUrl}
const _modalUploadedImages={};  // view → {filename, b64, dataUrl}
const _modalDeletedViews=new Set();  // views marked for deletion from the active asset manifest bucket
const _altUploadedImages={};   // "assetKey:view" → {filename, b64, dataUrl}
const _altDeletedViews={};     // assetKey → Set<view>
const _viewAspectRatios={};   // view → w/h ratio (equipment/bar only, for locked AR)

function partTypeAssetBucket(renderKind){
  return renderKind==="bar"?"bar_assets":"equipment_assets";
}

function partTypeUploadFolder(renderKind){
  return renderKind==="bar"?"lights":"equipment";
}

function getPartTypeAssetMap(renderKind){
  const bucket=partTypeAssetBucket(renderKind);
  if(!_manifest[bucket]) _manifest[bucket]={};
  return _manifest[bucket];
}

function isDiagramConfigured(renderKind, views){
  return renderKind!=="none" && (views||[]).length>0;
}

function deriveDiagramFlag(part){
  return isDiagramConfigured(part?.render_kind||"none", part?.default_views||[]);
}

function refreshSharedUi(){
  populateLocationDropdown();
  renderCatalog($("catalog-search")?.value||"");
  renderPartsLibrary($("lib-search")?.value||"");
  if($("vehicle-cards")) renderVehicleCards();
  if($("vehicle-preset")) buildVehiclePresetOptions();
  if($("vehicle-selector")) populateVehicleSelector();
  if($("fixture-vehicle-selector")) populateFixtureVehicleSelector();

  if($("add-loc-modal")?.classList.contains("open")){
    almBuildImportList($("alm-import-search")?.value||"");
    almBuildPartTypeList();
  }

  if($("edit-modal")?.classList.contains("open")){
    buildModalLocSection($("m-display-name")?.value?.trim()||"");
  }

  if($("parts-modal")?.classList.contains("open")){
    const selectedTypes=[...$("pm-compat-types").querySelectorAll("input:checked")].map(cb=>cb.value);
    populatePmCategory($("pm-category")?.value||"");
    populatePmCompatTypes(selectedTypes);
  }
}

async function initSettings(){
  if(!_layouts)       _layouts       = await api("/api/layouts");
  if(!_manifest)      _manifest      = await api("/api/manifest");
  if(!_catalog)       _catalog       = await api("/api/catalog");
  if(!_workbookRules) _workbookRules = await api("/api/workbook-rules");
  if(!_appSettings)   _appSettings   = await api("/api/app-settings");
  populateVehicleSelector();
  initPlacements();
  initSizeRules();
  populateLocationDropdown();
  renderCatalog();
  initVehiclesTab();
  populateTemplateSectionSelect();
  syncWizardDiagramUi();
  await loadPartsLibrary();
  if (typeof initAgenciesTab === "function") initAgenciesTab();
  if (typeof initSalesRepsTab === "function") initSalesRepsTab();
  if (typeof initPresetsTab === "function") initPresetsTab();
}

function populateTemplateSectionSelect(){
  const sections = (_workbookRules?.template_sections || []).map(s => s.label);
  const sel = $("wp-template-section");
  if(!sel) return;
  sel.innerHTML = sections.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
}
