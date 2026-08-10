// ═══════════════════════════════════════════════════════
// LOCATION DROPDOWN (wizard)
// ═══════════════════════════════════════════════════════
function populateLocationDropdown(){
  $("wp-location-key").innerHTML='<option value="">— none —</option>'+
    allKnownLocationNames().map(l=>`<option value="${esc(l)}">${esc(l)}</option>`).join("");
}

// ═══════════════════════════════════════════════════════
// STARTUP
// ═══════════════════════════════════════════════════════
window.addEventListener("DOMContentLoaded", async()=>{
  try{const s=await api("/status"); if(s.existing_file) logLine("Found input: "+s.existing_file);}catch(e){}
  try{
    const settings=await api("/api/app-settings");
    if(settings && !_appSettings) _appSettings=settings;
  }catch(e){}
  // Keep a future internal QuickBooks OAuth round-trip out of the public UI.
  if (window.DTM_QUICKBOOKS_UI_ENABLED === true
      && typeof qbConsumeReturnTab === "function" && qbConsumeReturnTab()) return;
  // All tab-specific scripts are now loaded — open Projects tab as default
  switchTab("projects");
});
