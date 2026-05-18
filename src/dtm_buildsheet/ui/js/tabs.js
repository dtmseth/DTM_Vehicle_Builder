// ═══════════════════════════════════════════════════════
// TAB ROUTING
// ═══════════════════════════════════════════════════════
function switchTab(t) {
  document.querySelectorAll(".htab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === t);
  });
  $("tab-projects").hidden = t !== "projects";
  $("tab-settings").hidden = t !== "settings";
  if (t === "settings") initSettings();
  if (t === "projects") initProjectsTab();
}

document.querySelectorAll(".htab").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.querySelectorAll(".stab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".stab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    ["placements","fixtures","sizes","catalog","parts","vehicles","agencies","sales-reps","presets","tools"].forEach(s =>
      $("stab-"+s).hidden = s!==btn.dataset.stab
    );
    if(btn.dataset.stab === "tools") loadTemplateInfo();
    if(btn.dataset.stab === "fixtures") initFixtures();
    if(btn.dataset.stab === "sales-reps" && typeof initSalesRepsTab === "function") initSalesRepsTab();
  });
});
