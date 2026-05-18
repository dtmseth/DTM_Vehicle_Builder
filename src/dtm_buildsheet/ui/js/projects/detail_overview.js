// ── Projects module: detail Overview tab ──────────────────────────────────────

function _ptRenderOverview(project) {
  const c  = project.customer    || {};
  const pr = project.preferences || {};

  const custPairs = [
    ["Agency",     c.agency],
    ["Build Year", c.build_year],
    ["Quote #",    c.quote_number],
    ["Sales Rep",  c.sales_rep],
  ].filter(([, v]) => v);

  const prefPairs = [
    ["Camera",      pr.camera_brand],
    ["Lighting",    (pr.lighting_brands || []).join(", ")],
    ["Push Bumper", pr.push_bumper_brand],
    ["Cage",        pr.cage_brand],
    ["Slick Top",   pr.slick_top ? "Yes" : null],
    ["Notes",       pr.notes],
  ].filter(([, v]) => v);

  const custHtml = custPairs.length
    ? custPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
    : `<p class="proj-empty-msg proj-empty-msg-padded">No customer info.</p>`;

  const prefHtml = prefPairs.length
    ? prefPairs.map(([l, v]) => _ptInfoRow(l, v)).join("")
    : `<p class="proj-empty-msg proj-empty-msg-padded">No preferences set.</p>`;

  const fleetHtml = _ptUnitFleetSummaryCards(project.build_units || []);

  $("proj-ptab-overview").innerHTML = `
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
    ${fleetHtml}`;
}
