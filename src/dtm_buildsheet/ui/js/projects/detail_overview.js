// ── Projects module: detail Overview tab ──────────────────────────────────────

function _ptRenderOverview(project) {
  const c  = project.customer    || {};
  const pr = project.preferences || {};

  const custPairs = [
    ["Agency",     c.agency],
    ["Build Year", c.build_year],
    ["Sales Rep",  c.sales_rep],
  ].filter(([, v]) => v);

  const prefPairs = [
    ["Camera",      pr.camera_brand],
    ["Lighting",    (pr.lighting_brands || []).join(", ")],
    ["Push Bumper", pr.push_bumper_brand],
    ["Cage",        pr.cage_brand],
    ["Console",     pr.console_brand],
    ["Slick Top",   pr.slick_top ? "Yes" : null],
    ["Notes",       pr.notes],
  ].filter(([, v]) => v);

  const custHtml = custPairs.length
    ? custPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
    : `<p class="proj-empty-msg proj-empty-msg-padded">No customer info.</p>`;

  const prefHtml = prefPairs.length
    ? prefPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
    : `<p class="proj-empty-msg proj-empty-msg-padded">No preferences set.</p>`;

  const buildsHtml = typeof _ptBuildCardsMarkup === "function"
    ? _ptBuildCardsMarkup(project)
    : `<p class="proj-empty-msg">Builds are loading…</p>`;

  const panel = $("proj-ptab-overview");
  panel.innerHTML = `
    <div class="proj-overview-top">
      <div class="proj-overview-card">
        <div class="proj-overview-card-title">Customer Info</div>
        <div class="proj-overview-card-body">${custHtml}</div>
      </div>
      <div class="proj-overview-card">
        <div class="proj-overview-card-title">Equipment Preferences</div>
        <div class="proj-overview-card-body">${prefHtml}</div>
      </div>
    </div>
    <section class="proj-overview-builds" aria-label="Builds">
      <div class="proj-overview-builds-title">Builds</div>
      ${buildsHtml}
    </section>`;

  if (typeof _ptBindBuildCardOpeners === "function") _ptBindBuildCardOpeners(panel);
  if (typeof _ptLoadBuildsStats === "function") _ptLoadBuildsStats(project);
}
