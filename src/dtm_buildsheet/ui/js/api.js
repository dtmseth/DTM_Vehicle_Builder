// ═══════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════
const api = (path, body) =>
  fetch(path, body !== undefined
    ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}
    : undefined
  ).then(r => r.json());

async function apiSave(endpoint, data){
  const res = await api(endpoint, data);
  if(res?.ok && res.template_regen) setTimeout(loadTemplateInfo, 800);
  maybeProposalToast(res);
  // A proposal save means cloud is working — refresh the chip so the user
  // gets immediate confirmation that they're signed in (esp. on first save).
  if(res?.proposed) setTimeout(refreshCloudStatus, 200);
  return res;
}

// Phase 2-β: surface the proposal pipeline outcome to the user.
// "general" category = auto-merged by the settings-repo workflow within
// minutes. "advanced" = a PR opens and waits for owner review.
// No proposal field on the response = legacy/local-only save; nothing to
// say beyond whatever the caller's own toast already shows.
function maybeProposalToast(res){
  if(!res?.ok || !res.proposed) return;
  if(res.category === "general"){
    toast("Saved (auto-merging shortly)", "success");
  } else if(res.category === "advanced"){
    toast("Submitted for review", "info");
  }
}

function relativeTime(ms){
  const s = Math.floor((Date.now() - ms) / 1000);
  if(s < 10)  return "just now";
  if(s < 60)  return s + "s ago";
  const m = Math.floor(s / 60);
  if(m < 60)  return m + "m ago";
  const h = Math.floor(m / 60);
  if(h < 24)  return h + "h ago";
  return Math.floor(h / 24) + "d ago";
}

async function loadTemplateInfo(){
  const el = $("tpl-last-updated"); if(!el) return;
  updateSaveToDisplay();
  updateExportDirDisplay();
  try {
    const res = await api("/api/template/info");
    if(res.exists && res.mtime){
      el.textContent = "Last updated: " + relativeTime(res.mtime * 1000);
      el.style.color = "var(--muted)";
    } else {
      el.textContent = "Template file not found";
      el.style.color = "#b71c1c";
    }
  } catch(e){ el.textContent = ""; }
}

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const fmt = b => b<1024?b+"B":b<1048576?(b/1024).toFixed(1)+"KB":(b/1048576).toFixed(1)+"MB";
const slugify = s => s.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");

function show(id){$(id).removeAttribute("hidden")}
function hide(id){$(id).setAttribute("hidden","")}
function toast(msg, type=""){
  const t=$("toast"); t.textContent=msg;
  t.className="toast show"+(type?" "+type:"");
  setTimeout(()=>t.className="toast",2800);
}

// ─── Cloud connection indicator ─────────────────────────────────────────────
// Header chip showing cloud state + signed-in M365 user + profile photo.
// refreshCloudStatus() is called on app boot and after every successful
// proposal save (the "I just confirmed cloud works" moment).
function _cloudInitials(name){
  if(!name) return "?";
  const parts = String(name).trim().split(/\s+/);
  if(parts.length === 1) return parts[0].slice(0,2).toUpperCase();
  return (parts[0][0] + parts[parts.length-1][0]).toUpperCase();
}

function _setCloudChip({stateClass, text, title, photo, initials}){
  const chip = $("cloud-status"); if(!chip) return;
  // Strip every cloud-status-* state class so we don't accumulate them.
  chip.className = "cloud-status " + stateClass;
  chip.title = title || text;
  $("cloud-status-text").textContent = text;
  const photoEl = $("cloud-status-photo");
  const initialsEl = $("cloud-status-initials");
  if(photo){
    // Cache-bust on each call so a freshly-cached photo replaces a 404.
    photoEl.src = "/api/cloud/photo?t=" + Date.now();
    photoEl.hidden = false;
    initialsEl.hidden = true;
    photoEl.onerror = () => {
      // Photo isn't actually available — fall back to initials.
      photoEl.hidden = true;
      initialsEl.hidden = false;
      initialsEl.textContent = initials;
    };
  } else if(initials){
    photoEl.hidden = true;
    initialsEl.hidden = false;
    initialsEl.textContent = initials;
  } else {
    photoEl.hidden = true;
    initialsEl.hidden = true;
  }
}

async function refreshCloudStatus(){
  let res;
  try { res = await api("/api/cloud/status"); }
  catch(_){
    _setCloudChip({stateClass:"cloud-status-local", text:"Offline",
                   title:"Could not reach the local server"});
    return;
  }
  if(!res?.cloud_enabled){
    _setCloudChip({stateClass:"cloud-status-local", text:"Local mode",
                   title:"Cloud mode is disabled for this install"});
    return;
  }
  if(!res.signed_in){
    _setCloudChip({stateClass:"cloud-status-signed-out", text:"Sign in needed",
                   title:"Cloud mode is on but no Microsoft account is connected"});
    return;
  }
  const name = res.user?.display_name || res.user?.email || "Signed in";
  const initials = _cloudInitials(name);
  _setCloudChip({
    stateClass: "cloud-status-connected",
    text: `Connected to Microsoft via: ${name}`,
    title: res.user?.email
      ? `Connected to Microsoft via: ${name} (${res.user.email})`
      : `Connected to Microsoft via: ${name}`,
    photo: res.has_photo,
    initials,
  });
}

// Boot + 60s polling. The status endpoint is cheap (no Graph hit on the
// hot path — only on first-call photo fetch) so polling won't be noticed.
document.addEventListener("DOMContentLoaded", () => {
  refreshCloudStatus();
  setInterval(refreshCloudStatus, 60_000);
});
