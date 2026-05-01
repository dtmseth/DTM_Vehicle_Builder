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
});
