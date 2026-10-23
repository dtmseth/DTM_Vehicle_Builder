// ═══════════════════════════════════════════════════════
// UPDATE BANNER — two modes:
//   "restart" → background download is queued; install on close or restart now
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
  let hiddenReadyVersion = null;
  let installing = false;

  function show(info, currentVersion, kind) {
    currentInfo = info;
    mode = kind || "download";
    if (mode === "restart") {
      if (hiddenReadyVersion === info.version) {
        hide();
        return;
      }
      text.textContent =
        `Update v${info.version} ready — keep working; it will install quietly when you close DTM`;
      downloadBtn.textContent = "Restart & Install";
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
    // Do not let the one-minute refresh overwrite the shutdown explanation
    // while the native app is handing control to the Windows installer.
    if (installing) return;
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
      if (us?.state === "platform_unsupported" || us?.state === "dev_build") {
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
      installing = true;
      const confirmed = window.confirm(
        `DTM Vehicle Builder will close completely, then install v${currentInfo.version}.\n\n` +
        "Windows will show the installation progress after DTM exits. Do not reopen DTM while " +
        "that window is active; DTM will reopen automatically when it finishes."
      );
      if (!confirmed) {
        installing = false;
        downloadBtn.disabled = false;
        return;
      }
      downloadBtn.textContent = "Preparing update…";
      text.textContent =
        "Opening update progress. DTM will close only after that window is visible.";
      const closeFallback = setTimeout(() => {
        text.textContent =
          "Windows is taking longer to prepare the update window. Keep DTM open; " +
          "it will close automatically when the progress window is ready.";
        downloadBtn.textContent = "Still preparing…";
      }, 5000);
      try {
        const res = window.pywebview?.api?.install_update
          ? await window.pywebview.api.install_update()
          : await api("/api/update/install-now", {});
        if (!res?.ok) {
          throw new Error(res?.error || "The updater could not start.");
        }
      } catch (error) {
        clearTimeout(closeFallback);
        installing = false;
        downloadBtn.textContent = originalText;
        downloadBtn.disabled = false;
        text.textContent = `Update v${currentInfo.version} is ready. ` +
          (error?.message || "The updater could not start.");
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
    if (mode === "restart") {
      // The installer is already downloaded. Hide the reminder for this app
      // session only; the update will still install on a normal close.
      hiddenReadyVersion = currentInfo.version;
    } else {
      try {
        await api("/api/update/dismiss", { version: currentInfo.version });
      } catch (e) {
        console.error("Dismiss failed:", e);
      }
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
