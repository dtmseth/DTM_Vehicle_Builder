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
  return res;
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
function toast(msg, type=""){
  const t=$("toast"); t.textContent=msg;
  t.className="toast show"+(type?" "+type:"");
  setTimeout(()=>t.className="toast",2800);
}
