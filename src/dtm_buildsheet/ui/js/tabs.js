// ═══════════════════════════════════════════════════════
// TAB ROUTING
// ═══════════════════════════════════════════════════════
document.querySelectorAll(".htab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".htab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const t = btn.dataset.tab;
    $("tab-generate").hidden = t!=="generate";
    $("tab-settings").hidden = t!=="settings";
    if (t==="settings") initSettings();
  });
});

document.querySelectorAll(".stab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".stab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    ["placements","fixtures","sizes","addpart","catalog","parts","vehicles","tools"].forEach(s =>
      $("stab-"+s).hidden = s!==btn.dataset.stab
    );
    if(btn.dataset.stab === "tools") loadTemplateInfo();
    if(btn.dataset.stab === "fixtures") initFixtures();
  });
});
