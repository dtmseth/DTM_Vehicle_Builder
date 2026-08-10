// ═══════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════
// Returns parsed JSON. Non-2xx responses that still carry a JSON body
// (e.g. {"error": ...} on a 400/404) resolve normally so callers can read
// res.error — many do. Only a body that isn't JSON at all (a 500 HTML error
// page) rejects, and it does so with the status + path so the failure is
// diagnosable instead of surfacing as a generic "Error loading X."
const api = (path, body) =>
  fetch(path, body !== undefined
    ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}
    : undefined
  ).then(async r => {
    try {
      return await r.json();
    } catch (_) {
      throw new Error(`${path} → ${r.status} ${r.statusText} (non-JSON response)`);
    }
  });

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
// queued = cloud was unreachable; the change is persisted for retry on
// the next sync cycle, but the user should know the cloud-side step
// didn't complete this moment.
function maybeProposalToast(res){
  if(!res?.ok) return;
  if(res.queued){
    toast("Saved locally — will retry sync when the cloud is reachable", "warn");
    return;
  }
  if(!res.proposed) return;
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
let _toastTimer;

async function _copyToastMessage(message){
  try {
    await navigator.clipboard.writeText(message);
    return true;
  } catch (_) {
    // pywebview and older embedded browsers may not expose Clipboard API.
    const field = document.createElement("textarea");
    field.value = message;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}

function toast(msg, type=""){
  const t=$("toast");
  const message = String(msg || "");
  const copyable = type === "error";
  t.textContent=message;
  t.className="toast show"+(type?" "+type:"");
  t.onclick = null;
  t.onkeydown = null;
  t.removeAttribute("role");
  t.removeAttribute("tabindex");
  t.removeAttribute("title");
  if (copyable) {
    t.classList.add("copyable");
    t.setAttribute("role", "button");
    t.setAttribute("tabindex", "0");
    t.title = "Click to copy this error";
    const copy = async () => {
      const copied = await _copyToastMessage(message);
      if (copied) {
        t.textContent = "✓ Error copied to clipboard";
        t.className = "toast show success";
      }
    };
    t.onclick = copy;
    t.onkeydown = event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        copy();
      }
    };
  }
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(()=>t.className="toast",copyable ? 7000 : 2800);
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

// Tracks the data_version we last reacted to. When the backend bumps this
// (sync changed local files), refreshCloudStatus() detects the transition
// and triggers a UI refresh for whatever the user is currently looking at —
// otherwise sync silently changes files and the UI shows stale lists until
// the user navigates away and back.
let _lastSeenDataVersion = null;

function _refreshVisibleDataAfterSync(){
  // Re-fetch anything sync could have changed under the user's feet.
  // Projects list is the most common; settings tabs (agencies, sales
  // reps, presets) also need a refresh — without it, a teammate's
  // deletion shows up in the local file but the rendered list stays
  // stale until the user navigates away and back.
  try {
    if (typeof _ptLoadAll === "function") {
      _ptLoadAll().then(() => {
        if (typeof _ptRenderList === "function") _ptRenderList();
      }).catch(e => console.warn("Post-sync projects refresh failed:", e));
    }
    if (typeof refreshAgenciesTab === "function") {
      refreshAgenciesTab().catch(e => console.warn("Post-sync agencies refresh failed:", e));
    }
    if (typeof refreshSalesRepsTab === "function") {
      refreshSalesRepsTab().catch(e => console.warn("Post-sync sales-reps refresh failed:", e));
    }
    if (typeof refreshPresetsTab === "function") {
      refreshPresetsTab().catch(e => console.warn("Post-sync presets refresh failed:", e));
    }
  } catch (e) {
    console.warn("Post-sync refresh threw:", e);
  }
}

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
  // Detect "data changed under us" via the data_version counter the
  // backend bumps on every sync that produced observable changes. Don't
  // fire on the very first poll (would re-fetch unnecessarily on app
  // load); only when the version transitions to something newer.
  const dv = res?.data_version;
  if (typeof dv === "number") {
    if (_lastSeenDataVersion === null) {
      _lastSeenDataVersion = dv;
    } else if (dv !== _lastSeenDataVersion) {
      _lastSeenDataVersion = dv;
      _refreshVisibleDataAfterSync();
    }
  }
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

function _renderChangesRow(changes){
  // changes = { summary: "...", items: [...] } | null
  // Populated for ~10s after a sync that actually transferred something.
  // Listing the items lets the user see what landed without re-reading
  // the project list themselves.
  const el = $("cloud-modal-changes");
  if(!el) return;
  if(!changes || !changes.summary){
    el.hidden = true;
    el.textContent = "";
    el.style.color = "";
    el.title = "";
    return;
  }
  el.hidden = false;
  el.textContent = "🔄 " + changes.summary;
  el.style.color = "var(--green, #166534)";
  el.title = (changes.items || []).join("\n");
}

function _renderUpdateStateRow(state){
  const el = $("cloud-modal-update-state");
  if(!el) return;
  if(!state){ el.textContent = ""; el.style.color = ""; el.title = ""; return; }
  const cur = state.current || "";
  let txt = "", color = "var(--muted)", title = "";
  switch(state.state){
    case "ready":
      txt = `🔄 Update v${state.ready_version} downloaded — restart to install`;
      color = "var(--green, #166534)";
      title = "Click Restart Now in the banner above (or close and reopen the app) to apply.";
      break;
    case "downloading":
      txt = `⬇️ Downloading v${state.downloading_version}…`;
      color = "var(--navy)";
      title = "The new version is being downloaded in the background. It will install on next restart.";
      break;
    case "available":
      txt = `⬇️ Update v${state.available_version} available`;
      color = "var(--navy)";
      title = "A newer version is available. Use the banner above to download it.";
      break;
    case "platform_unsupported":
      txt = `✅ v${cur} (auto-update unavailable on this platform)`;
      title = "Auto-update isn't supported on this OS — download new releases manually when notified.";
      break;
    case "up_to_date":
    default:
      txt = `✅ Up to date · v${cur}`;
      color = "var(--green, #166534)";
      title = "You're running the latest release.";
      break;
  }
  el.textContent = txt;
  el.style.color = color;
  el.title = title;
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
    // Queue items remaining after a sync cycle ran already retried at
    // least once and still failed — surface them as a warning so the
    // user knows a real failure is being retried, not work in flight.
    const queue = status.pending_queue || {};
    const pending = (queue.proposals || 0) + (queue.exports || 0);
    const pendingEl = $("cloud-modal-pending");
    if(pendingEl){
      if(pending > 0){
        pendingEl.hidden = false;
        pendingEl.innerHTML = `⚠️ ${pending} upload${pending === 1 ? "" : "s"} failed — will retry on next sync`;
        pendingEl.style.color = "var(--orange, #b45309)";
        pendingEl.title = "These changes saved locally but couldn't reach SharePoint. Check dtm_buildsheet.log for the exact reason (most often a library-name mismatch or expired token).";
      } else {
        pendingEl.hidden = true;
        pendingEl.style.color = "";
        pendingEl.title = "";
      }
    }
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
    _renderUpdateStateRow(status.update_state);
    _renderChangesRow(status.changes);
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
    // force_account_picker tells MSAL to add prompt=select_account to the
    // OAuth request. Without it the browser's existing Microsoft session
    // wins silently and "Switch User" appears to do nothing.
    const res = await api("/api/cloud/signin", {force_account_picker: true});
    if(res?.ok){
      toast("Signed in as " + (res.user?.display_name || "user"), "success");
      await refreshCloudStatus();
      _refreshCloudModalBody();
    } else {
      toast("Sign-in failed: " + (res?.error || "unknown error"), "error");
    }
  } catch(e) {
    toast("Sign-in failed: " + (e?.message || "unknown error"), "error");
  } finally {
    btn.disabled = false;
    await refreshCloudStatus();
    _refreshCloudModalBody();
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
  } catch(e) {
    toast("Sign-in failed: " + (e?.message || "unknown error"), "error");
  } finally {
    btn.disabled = false;
    await refreshCloudStatus();
    _refreshCloudModalBody();
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
