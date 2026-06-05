// ═══════════════════════════════════════════════════════
// UPDATE BANNER — two modes:
//   "restart" → background download is queued; one-click silent install
//   "download" → manual fallback for the very first install or when the
//                background download couldn't run (no cloud, etc.)
// Re-polls every 60s so the queued installer is picked up shortly after
// the background sync downloads it.
// ═══════════════════════════════════════════════════════
(function () {
  const banner = document.getElementById("update-banner");
  if (!banner) return;
  const text = banner.querySelector(".update-banner-text");
  const downloadBtn = document.getElementById("update-banner-download");
  const dismissBtn = document.getElementById("update-banner-dismiss");

  let currentInfo = null;
  let mode = "download"; // "download" | "restart"

  function show(info, currentVersion, kind) {
    currentInfo = info;
    mode = kind || "download";
    if (mode === "restart") {
      text.textContent =
        `Update v${info.version} ready — restart to install`;
      downloadBtn.textContent = "Restart Now";
    } else {
      text.textContent =
        `Update available — v${info.version}` +
        (currentVersion ? ` (you have v${currentVersion})` : "");
      downloadBtn.textContent = "Download";
    }
    banner.hidden = false;
  }

  function hide() {
    banner.hidden = true;
    currentInfo = null;
    mode = "download";
  }

  async function poll() {
    // Single source of truth: cloud_status.update_state. The server tells
    // us whether to show "Restart Now" (ready), nothing (downloading or
    // up-to-date), or "Download" (manual fallback only — non-Windows or
    // cloud disabled).
    try {
      const status = await api("/api/cloud/status");
      const us = status?.update_state;
      if (us?.state === "ready") {
        show({ version: us.ready_version }, us.current, "restart");
        return;
      }
      if (us?.state === "downloading" || us?.state === "up_to_date") {
        // Either the auto-update is fetching the installer right now
        // (no user action needed) or there's nothing to install.
        // Either way, no banner — the cloud modal carries the detail.
        hide();
        return;
      }
      if (us?.state === "available") {
        // Manual path: non-Windows or cloud disabled. Offer Download.
        show({ version: us.available_version }, us.current, "download");
        return;
      }
      if (us?.state === "platform_unsupported") {
        hide();
        return;
      }
    } catch (_) { /* fall through to manual check */ }
    // Fallback when cloud_status didn't return — usually a cold start
    // before the periodic sync finished its first iteration.
    try {
      const res = await api("/api/update/check");
      if (res && res.available && res.info) {
        show(res.info, res.current_version, "download");
      } else {
        hide();
      }
    } catch (e) {
      // Cloud may be off, network may be down — silent.
    }
  }

  downloadBtn.addEventListener("click", async () => {
    if (!currentInfo) return;
    downloadBtn.disabled = true;
    const originalText = downloadBtn.textContent;
    if (mode === "restart") {
      downloadBtn.textContent = "Installing…";
      try {
        await api("/api/update/install-now", {});
        // The server.install_now spawns the installer silently and exits
        // ~1.5s later. The webview will lose its socket; nothing more to
        // do here — the new version will come up automatically when the
        // installer's [Run] section fires.
      } catch (_) {
        // Connection dropping IS the expected case once the server
        // exits. Swallow.
      }
      return;
    }
    downloadBtn.textContent = "Downloading…";
    try {
      const res = await api("/api/update/download", { version: currentInfo.version });
      if (res && res.ok) {
        downloadBtn.textContent = "Saved";
      } else {
        downloadBtn.textContent = "Failed";
        console.error("Update download failed:", res && res.error);
      }
    } catch (e) {
      downloadBtn.textContent = "Failed";
      console.error(e);
    } finally {
      setTimeout(() => {
        downloadBtn.textContent = originalText;
        downloadBtn.disabled = false;
      }, 2500);
    }
  });

  dismissBtn.addEventListener("click", async () => {
    if (!currentInfo) {
      hide();
      return;
    }
    try {
      await api("/api/update/dismiss", { version: currentInfo.version });
    } catch (e) {
      console.error("Dismiss failed:", e);
    }
    hide();
  });

  // Defer the first poll so it doesn't compete with the initial paint.
  // Re-poll periodically so a freshly-queued installer becomes visible
  // within ~60s of the background download completing.
  window.addEventListener("DOMContentLoaded", () => {
    setTimeout(poll, 1500);
    setInterval(poll, 60_000);
  });
})();
