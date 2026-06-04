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

// Cached so the modal can render the same identity the chip is showing
// without a second fetch. Updated by every refreshCloudStatus() call.
let _lastCloudStatus = null;

function _setCloudChip({stateClass, text, title, photo, initials, syncing}){
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
  // Spinner overlay — shown whenever the backend reports a sync in flight.
  const spinner = $("cloud-status-spinner");
  if(spinner) spinner.hidden = !syncing;
}

async function refreshCloudStatus(){
  let res;
  try { res = await api("/api/cloud/status"); }
  catch(_){
    _lastCloudStatus = null;
    _setCloudChip({stateClass:"cloud-status-local", text:"Offline",
                   title:"Could not reach the local server"});
    return;
  }
  _lastCloudStatus = res;
  const syncing = !!res?.syncing;
  if(!res?.cloud_enabled){
    _setCloudChip({stateClass:"cloud-status-local", text:"Local mode",
                   title:"Cloud mode is disabled for this install", syncing});
    return;
  }
  if(!res.signed_in){
    _setCloudChip({stateClass:"cloud-status-signed-out", text:"Sign in needed",
                   title:"Cloud mode is on but no Microsoft account is connected",
                   syncing});
    return;
  }
  const name = res.user?.display_name || res.user?.email || "Signed in";
  const initials = _cloudInitials(name);
  _setCloudChip({
    stateClass: "cloud-status-connected",
    text: name,  // Shorter — name + photo carries the rest. Full context lives in the tooltip and modal.
    title: res.user?.email
      ? `Connected to Microsoft via: ${name} (${res.user.email})`
      : `Connected to Microsoft via: ${name}`,
    photo: res.has_photo,
    initials,
    syncing,
  });
}

// ─── Cloud status modal ─────────────────────────────────────────────────────
// Click the chip → opens a modal with: user identity, last sync timestamp,
// "Force sync now" (runs all syncs immediately), "Switch user"
// (signout + signin), and a "Sign in" button when not signed in.

let _lastSyncAt = null;  // millis since epoch of the last completed sync

function _formatLastSync(){
  if(!_lastSyncAt) return "Not synced yet this session";
  return "Last sync: " + relativeTime(_lastSyncAt);
}

function _refreshCloudModalBody(){
  const status = _lastCloudStatus;
  const signedInPanel = $("cloud-modal-signed-in");
  const signedOutPanel = $("cloud-modal-signed-out");
  const switchBtn = $("cloud-modal-switch");
  const signinBtn = $("cloud-modal-signin");
  const signedOutText = $("cloud-modal-signed-out-text");

  if(status?.signed_in){
    signedInPanel.hidden = false;
    signedOutPanel.hidden = true;
    switchBtn.hidden = false;
    signinBtn.hidden = true;
    const name = status.user?.display_name || status.user?.email || "Signed in";
    $("cloud-modal-name").textContent = name;
    $("cloud-modal-email").textContent = status.user?.email || "";
    const photoEl = $("cloud-modal-photo");
    const initialsEl = $("cloud-modal-initials");
    if(status.has_photo){
      photoEl.src = "/api/cloud/photo?t=" + Date.now();
      photoEl.hidden = false;
      initialsEl.hidden = true;
      photoEl.onerror = () => {
        photoEl.hidden = true;
        initialsEl.hidden = false;
        initialsEl.textContent = _cloudInitials(name);
      };
    } else {
      photoEl.hidden = true;
      initialsEl.hidden = false;
      initialsEl.textContent = _cloudInitials(name);
    }
    $("cloud-modal-last-sync").textContent = _formatLastSync();
  } else {
    signedInPanel.hidden = true;
    signedOutPanel.hidden = false;
    switchBtn.hidden = true;
    signinBtn.hidden = !(status?.cloud_enabled);
    signedOutText.textContent = status?.cloud_enabled
      ? "Cloud mode is on but no Microsoft account is connected. Sign in to start syncing."
      : "Cloud mode is disabled for this install. " + _formatLastSync();
  }

  // Sync button label reflects current state.
  const syncLabel = $("cloud-modal-sync-label");
  if(_lastCloudStatus?.syncing){
    syncLabel.innerHTML = '<span class="cloud-modal-sync-active">⟳</span> Syncing…';
  } else {
    syncLabel.textContent = "⟳ Force sync now";
  }
}

function openCloudModal(){
  refreshCloudStatus().then(_refreshCloudModalBody);
  $("cloud-modal").classList.add("open");
}

function closeCloudModal(){
  $("cloud-modal").classList.remove("open");
}

async function _doForceSync(){
  const btn = $("cloud-modal-sync");
  btn.disabled = true;
  $("cloud-modal-sync-label").innerHTML = '<span class="cloud-modal-sync-active">⟳</span> Syncing…';
  try {
    // Pre-emptively refresh the chip to show the spinner before /api/cloud/sync
    // returns (the next refresh will see syncing=true while the call is alive).
    refreshCloudStatus();
    const res = await api("/api/cloud/sync", {});
    if(res?.ok){
      _lastSyncAt = Date.now();
      toast("Sync complete", "success");
    } else {
      toast("Sync failed: " + (res?.error || "unknown error"), "error");
    }
  } catch(e){
    toast("Sync failed: " + e.message, "error");
  } finally {
    btn.disabled = false;
    await refreshCloudStatus();
    _refreshCloudModalBody();
  }
}

async function _doSwitchUser(){
  const btn = $("cloud-modal-switch");
  btn.disabled = true;
  try {
    await api("/api/cloud/signout", {});
    const res = await api("/api/cloud/signin", {});
    if(res?.ok){
      toast("Signed in as " + (res.user?.display_name || "user"), "success");
      await refreshCloudStatus();
      _refreshCloudModalBody();
    } else {
      toast("Sign-in failed: " + (res?.error || "unknown error"), "error");
    }
  } finally {
    btn.disabled = false;
  }
}

async function _doSignin(){
  const btn = $("cloud-modal-signin");
  btn.disabled = true;
  try {
    const res = await api("/api/cloud/signin", {});
    if(res?.ok){
      toast("Signed in as " + (res.user?.display_name || "user"), "success");
      await refreshCloudStatus();
      _refreshCloudModalBody();
    } else {
      toast("Sign-in failed: " + (res?.error || "unknown error"), "error");
    }
  } finally {
    btn.disabled = false;
  }
}

// Boot + 60s polling. The status endpoint is cheap (no Graph hit on the
// hot path — only on first-call photo fetch) so polling won't be noticed.
document.addEventListener("DOMContentLoaded", () => {
  refreshCloudStatus();
  setInterval(refreshCloudStatus, 60_000);
  // Modal wiring — each listener belongs to exactly one element so the
  // single-listener pattern from the rest of the app is preserved.
  $("cloud-status")?.addEventListener("click", openCloudModal);
  $("cloud-modal-close")?.addEventListener("click", closeCloudModal);
  $("cloud-modal-done")?.addEventListener("click", closeCloudModal);
  $("cloud-modal-sync")?.addEventListener("click", _doForceSync);
  $("cloud-modal-switch")?.addEventListener("click", _doSwitchUser);
  $("cloud-modal-signin")?.addEventListener("click", _doSignin);
  // Close-on-backdrop-click parity with other modals.
  $("cloud-modal")?.addEventListener("click", (e) => {
    if(e.target.id === "cloud-modal") closeCloudModal();
  });
});

// Track sync completions from the chip polling cycle so "Last sync" stays
// fresh whether the sync was kicked off by the timer or the button.
const _origRefreshCloudStatus_forSyncTime = refreshCloudStatus;
refreshCloudStatus = async function(){
  const wasSyncing = _lastCloudStatus?.syncing;
  await _origRefreshCloudStatus_forSyncTime();
  // Edge-trigger: just transitioned from syncing → not-syncing means a
  // background or forced sync just landed.
  if(wasSyncing && _lastCloudStatus && !_lastCloudStatus.syncing){
    _lastSyncAt = Date.now();
    if(!$("cloud-modal").classList.contains("open")) return;  // no UI to update
    _refreshCloudModalBody();
  }
};
