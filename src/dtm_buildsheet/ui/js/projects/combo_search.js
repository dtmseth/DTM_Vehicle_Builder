// ── Projects module: live-search combo widget ─────────────────────────────────
// Reusable helpers for agency and sales-rep search combos.

function _ptWireAgencySearch(inputEl, idEl, suggEl, onSelect) {
  let timer = null;
  const notify = () => { if (typeof onSelect === "function") onSelect(); };
  inputEl.addEventListener("input", () => {
    if (idEl && idEl.value) { idEl.value = ""; notify(); }
    clearTimeout(timer);
    const q = inputEl.value.trim();
    if (!q) { suggEl.style.display = "none"; return; }
    timer = setTimeout(async () => {
      const res = await api(`/api/agencies/search?q=${encodeURIComponent(q)}`);
      if (!res?.ok) return;
      const rows = (res.matches || []).map(m =>
        `<div class="sug-item" data-id="${esc(m.agency_id)}" data-name="${esc(m.name)}">${esc(m.name)}</div>`
      );
      rows.push(`<div class="sug-create">+ Create &quot;${esc(q)}&quot;</div>`);
      suggEl.innerHTML = rows.join("");
      suggEl.style.display = "";
      suggEl.querySelectorAll(".sug-item").forEach(el => {
        el.addEventListener("click", () => {
          inputEl.value = el.dataset.name;
          if (idEl) idEl.value = el.dataset.id;
          suggEl.style.display = "none";
          notify();
        });
      });
      const createEl = suggEl.querySelector(".sug-create");
      if (createEl) {
        createEl.addEventListener("click", () => {
          suggEl.style.display = "none";
          if (typeof openAgencyModal === "function") {
            openAgencyModal({ prefill: q, onSuccess: a => {
              inputEl.value = a.name;
              if (idEl) idEl.value = a.agency_id;
              notify();
            }});
          }
        });
      }
    }, 220);
  });
}

function _ptWireSalesRepSearch(inputEl, idEl, suggEl) {
  let timer = null;
  inputEl.addEventListener("input", () => {
    if (idEl) idEl.value = "";
    clearTimeout(timer);
    const q = inputEl.value.trim();
    if (!q) { suggEl.style.display = "none"; return; }
    timer = setTimeout(async () => {
      const res = await api(`/api/sales-reps/search?q=${encodeURIComponent(q)}`);
      if (!res?.ok) return;
      const rows = (res.matches || []).map(m =>
        `<div class="sug-item" data-id="${esc(m.rep_id)}" data-name="${esc(m.name)}">${esc(m.name)}</div>`
      );
      rows.push(`<div class="sug-create">+ Create &quot;${esc(q)}&quot;</div>`);
      suggEl.innerHTML = rows.join("");
      suggEl.style.display = "";
      suggEl.querySelectorAll(".sug-item").forEach(el => {
        el.addEventListener("click", () => {
          inputEl.value = el.dataset.name;
          if (idEl) idEl.value = el.dataset.id;
          suggEl.style.display = "none";
        });
      });
      const createEl = suggEl.querySelector(".sug-create");
      if (createEl) {
        createEl.addEventListener("click", () => {
          suggEl.style.display = "none";
          if (typeof openSalesRepModal === "function") {
            openSalesRepModal({ prefill: q, onSuccess: r => {
              inputEl.value = r.name;
              if (idEl) idEl.value = r.rep_id;
            }});
          }
        });
      }
    }, 220);
  });
}
