"use strict";

const { connectLambda } = require("@netlify/blobs");
const { loadConfig, loadHealth } = require("../../lib/shopmonkey-pricing");

const MAX_RECONCILE_AGE_SECONDS = 75 * 60;

function response(statusCode, payload) {
  return {
    statusCode,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
    body: JSON.stringify(payload),
  };
}

exports.handler = async (event) => {
  if (event.blobs) connectLambda(event);
  if (event.httpMethod !== "GET") return response(405, { ok: false, status: "method_not_allowed" });
  try {
    const [{ config, persisted }, health] = await Promise.all([loadConfig(), loadHealth()]);
    const checkedAt = Date.parse(String(health.last_reconcile_success_at || ""));
    const reconcileAgeSeconds = Number.isFinite(checkedAt)
      ? Math.max(0, Math.round((Date.now() - checkedAt) / 1000))
      : null;
    const credentialsReady = Boolean(
      process.env.SHOPMONKEY_API_KEY && process.env.SHOPMONKEY_WEBHOOK_SECRET,
    );
    const reconcileFresh = reconcileAgeSeconds !== null
      && reconcileAgeSeconds <= MAX_RECONCILE_AGE_SECONDS
      && health.last_api_check_ok === true;
    const ok = credentialsReady && persisted && config.enabled && reconcileFresh;
    return response(ok ? 200 : 503, {
      ok,
      status: ok ? "healthy" : "not_ready",
      mode: config.mode,
      config_persisted: persisted,
      pricing_enabled: config.enabled,
      credentials_ready: credentialsReady,
      reconciliation_fresh: reconcileFresh,
      reconciliation_age_seconds: reconcileAgeSeconds,
      last_webhook_success_at: health.last_success_at || "",
      last_reconciliation_at: health.last_reconcile_success_at || "",
      last_result: health.last_result || health.last_reconcile_result || "",
      last_error_at: health.last_error_at || "",
      last_error: health.last_error || "",
      repriced_total: Number(health.repriced_total || 0),
    });
  } catch (_) {
    return response(503, { ok: false, status: "health_unavailable" });
  }
};
