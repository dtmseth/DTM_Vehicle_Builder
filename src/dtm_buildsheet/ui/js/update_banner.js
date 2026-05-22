// ═══════════════════════════════════════════════════════
// UPDATE BANNER — polls /api/update/check at launch and on
// reconnect; shows a top-of-page banner with Download +
// Dismiss when a newer installer is available.
// ═══════════════════════════════════════════════════════
(function () {
  const banner = document.getElementById("update-banner");
  if (!banner) return;
  const text = banner.querySelector(".update-banner-text");
  const downloadBtn = document.getElementById("update-banner-download");
  const dismissBtn = document.getElementById("update-banner-dismiss");

  let currentInfo = null;

  function show(info, currentVersion) {
    currentInfo = info;
    text.textContent =
      `Update available — v${info.version}` +
      (currentVersion ? ` (you have v${currentVersion})` : "");
    banner.hidden = false;
  }

  function hide() {
    banner.hidden = true;
    currentInfo = null;
  }

  async function poll() {
    try {
      const res = await api("/api/update/check");
      if (res && res.available && res.info) {
        show(res.info, res.current_version);
      } else {
        hide();
      }
    } catch (e) {
      // Cloud may be off, network may be down — silent. No banner is the
      // right default when we don't know.
    }
  }

  downloadBtn.addEventListener("click", async () => {
    if (!currentInfo) return;
    downloadBtn.disabled = true;
    const originalText = downloadBtn.textContent;
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
  window.addEventListener("DOMContentLoaded", () => {
    setTimeout(poll, 1500);
  });
})();
