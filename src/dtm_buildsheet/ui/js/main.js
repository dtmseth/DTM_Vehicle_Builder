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
  // Resolve Entra roles before exposing any editable workspace. This prevents
  // older Builder controls from briefly appearing for read-only users.
  const accessSession = typeof initOperationsAccess === "function"
    ? await initOperationsAccess()
    : null;
  // Restore the QuickBooks surface after OAuth only when this role can use it.
  if (window.DTM_QUICKBOOKS_UI_ENABLED === true
      && typeof qbConsumeReturnTab === "function" && qbConsumeReturnTab()) return;
  const workspace = typeof _appFirstWorkspace === "function" ? _appFirstWorkspace() : "projects";
  if (workspace) switchTab(workspace);
});
