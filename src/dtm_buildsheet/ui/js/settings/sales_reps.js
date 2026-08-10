// Settings → Sales Reps tab
// Also owns the sales rep create/edit modal used from the project wizard.
(function () {
  let _reps = [];
  let _editingId = null;
  let _pendingOnSuccess = null;
  let _initialized = false;
  let _listWired = false;

  // Attribute-safe escape (also handles quotes, which shared esc() does not).
  const escAttr = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function _wireList() {
    if (_listWired) return;
    const container = $("sales-rep-list-container");
    if (!container) return;
    _listWired = true;
    // Delegated so names with apostrophes/quotes can't break the handler.
    container.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (!btn) return;
      const id = btn.getAttribute("data-id");
      if (btn.dataset.act === "edit") {
        salesRepEdit(id);
      } else if (btn.dataset.act === "del") {
        const r = _reps.find(x => x.rep_id === id);
        salesRepDelete(id, r ? r.name : "");
      }
    });
  }

  function _renderTable(list) {
    const container = $("sales-rep-list-container");
    if (!container) return;
    _wireList();
    if (!list.length) {
      container.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0">No sales reps yet. Add your first rep above.</p>`;
      return;
    }
    container.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:6px 8px">Name</th>
            <th style="text-align:left;padding:6px 8px">Phone</th>
            <th style="text-align:left;padding:6px 8px">Email</th>
            <th style="padding:6px 8px"></th>
          </tr>
        </thead>
        <tbody>
          ${list.map(r => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:7px 8px;font-weight:600">${esc(r.name)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(r.phone)}</td>
              <td style="padding:7px 8px;color:var(--muted)">${esc(r.email)}</td>
              <td style="padding:7px 8px;white-space:nowrap;text-align:right">
                <button class="btn btn-secondary btn-sm" data-act="edit" data-id="${escAttr(r.rep_id)}">Edit</button>
                <button class="btn btn-secondary btn-sm" style="margin-left:4px;color:var(--red)" data-act="del" data-id="${escAttr(r.rep_id)}">Delete</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  }

  async function _load() {
    const res = await api("/api/sales-reps");
    _reps = res?.sales_reps || [];
    _filterAndRender();
  }

  function _filterAndRender() {
    const q = ($("sales-rep-search")?.value || "").toLowerCase();
    const filtered = q ? _reps.filter(r => r.name.toLowerCase().includes(q)) : _reps;
    _renderTable(filtered);
  }

  // ── public API ─────────────────────────────────────────────────────────────
  window.openSalesRepModal = function (options = {}) {
    _pendingOnSuccess = options.onSuccess || null;
    _editingId = options.repId || null;
    const rep = _editingId ? _reps.find(r => r.rep_id === _editingId) : null;
    $("sr-name").value  = rep?.name  || options.prefill || "";
    $("sr-phone").value = rep?.phone || "";
    $("sr-email").value = rep?.email || "";
    $("sr-create-modal").classList.add("open");
    setTimeout(() => $("sr-name").focus(), 50);
  };

  window.salesRepEdit = function (repId) {
    openSalesRepModal({ repId });
  };

  window.salesRepDelete = async function (repId, name) {
    if (!confirm(`Remove "${name}" from the sales rep list?`)) return;
    const res = await fetch(`/api/sales-rep/${encodeURIComponent(repId)}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (data?.ok) {
      toast(`"${name}" removed`, "success");
      await _load();
    } else {
      toast(data?.error || "Delete failed", "error");
    }
  };

  window.initSalesRepsTab = async function () {
    await _load();
    if (_initialized) return;
    _initialized = true;
    $("btn-add-sales-rep")?.addEventListener("click", () => openSalesRepModal({}));
    $("sales-rep-search")?.addEventListener("input", _filterAndRender);
  };
  window.refreshSalesRepsTab = _load;

  // ── modal wiring — one listener, attached at script load ───────────────────
  function _closeModal() {
    $("sr-create-modal").classList.remove("open");
    _pendingOnSuccess = null;
    _editingId = null;
  }

  $("sr-create-close")?.addEventListener("click", _closeModal);
  $("sr-cancel")?.addEventListener("click", _closeModal);

  $("sr-save")?.addEventListener("click", async () => {
    const name  = $("sr-name").value.trim();
    const phone = $("sr-phone").value.trim();
    const email = $("sr-email").value.trim();
    if (!name)  { toast("Name is required",  "error"); return; }
    if (!phone) { toast("Phone is required", "error"); return; }
    if (!email) { toast("Email is required", "error"); return; }
    const payload = { name, phone, email };
    if (_editingId) payload.rep_id = _editingId;
    // apiSave so the Phase 2-β proposal toast fires when cloud mode is on.
    const res = await apiSave("/api/sales-rep/save", payload);
    if (res?.ok) {
      _closeModal();
      if (!res.proposed) {
        toast(_editingId ? "Rep updated" : `"${res.rep.name}" added`, "success");
      }
      if (_pendingOnSuccess) { _pendingOnSuccess(res.rep); _pendingOnSuccess = null; }
      await _load();
    } else {
      toast(res?.error || "Save failed", "error");
    }
  });
})();
