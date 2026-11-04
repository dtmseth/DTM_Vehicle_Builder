(function () {
  "use strict";

  const STORAGE_KEY = "dtm_builder_theme";
  const root = document.documentElement;

  function validTheme(value) {
    return value === "dark" || value === "light" ? value : "";
  }

  function serverTheme() {
    return validTheme(root.dataset.theme);
  }

  function browserTheme() {
    try {
      return validTheme(window.localStorage.getItem(STORAGE_KEY));
    } catch (_) {
      return "";
    }
  }

  function persistTheme(theme) {
    fetch("/api/ui-preferences/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
      cache: "no-store",
    }).catch(() => {
      // localStorage remains a session-level fallback when the local app
      // server is shutting down or its preference file cannot be written.
    });
  }

  function updateButton(theme) {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    const dark = theme === "dark";
    const label = dark ? "Switch to light mode" : "Switch to dark mode";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.setAttribute("aria-pressed", String(dark));
    const icon = document.getElementById("connection-theme-icon");
    if (icon) icon.textContent = dark ? "☀" : "☾";
    const buttonLabel = document.getElementById("theme-toggle-label");
    if (buttonLabel) buttonLabel.textContent = dark ? "Use light mode" : "Use dark mode";
    const detail = document.getElementById("connection-theme-detail");
    if (detail) detail.textContent = dark ? "Dark mode is active" : "Light mode is active";
  }

  function applyTheme(theme, persist) {
    const next = theme === "dark" ? "dark" : "light";
    root.dataset.theme = next;
    root.style.colorScheme = next;
    if (persist) {
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch (_) {
        // A locked-down WebView may reject local storage. The active session
        // still gets the selected theme.
      }
      persistTheme(next);
    }
    updateButton(next);
    window.dispatchEvent(new CustomEvent("dtm-theme-change", { detail: { theme: next } }));
  }

  // This script is intentionally loaded before the stylesheets. Applying the
  // saved value synchronously prevents a bright first frame in dark mode.
  const initialServerTheme = serverTheme();
  const initialBrowserTheme = browserTheme();
  applyTheme(initialServerTheme || initialBrowserTheme || "light", false);

  window.DTMTheme = {
    current: () => root.dataset.theme || "light",
    set: (theme) => applyTheme(theme, true),
  };

  window.addEventListener("DOMContentLoaded", () => {
    updateButton(root.dataset.theme || "light");
    // One-time migration for existing installs that still have the old
    // webview-only value. Future launches receive the durable value in the
    // opening HTML, before styles render.
    if (!initialServerTheme && initialBrowserTheme) persistTheme(initialBrowserTheme);
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
      applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true);
    });
  });
})();
