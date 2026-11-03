"use strict";

/** Five-minute safety net for recently changed Shopmonkey orders. */

const { loadConfig, recordHealth } = require("./shopmonkey-pricing");
const {
  applyPricingForOrder,
  shopmonkeyEnvelopeRequest,
} = require("../netlify/functions/shopmonkey-webhook").__test;

const ORDER_LOOKBACK_SECONDS = 15 * 60;
const ORDER_LIMIT = 50;
const ORDER_RACE_BUFFER = 25;
const ORDER_CONCURRENCY = 3;

async function mapWithConcurrency(rows, concurrency, callback) {
  const output = new Array(rows.length);
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < rows.length) {
      const index = nextIndex;
      nextIndex += 1;
      output[index] = await callback(rows[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, rows.length) }, () => worker()));
  return output;
}

function recentlyUpdated(order, nowSeconds) {
  const value = order && (order.updatedDate || order.createdDate || order.orderCreatedDate);
  const updatedSeconds = Date.parse(String(value || "")) / 1000;
  return Number.isFinite(updatedSeconds)
    && updatedSeconds <= nowSeconds + 30
    && nowSeconds - updatedSeconds <= ORDER_LOOKBACK_SECONDS;
}

async function recentOrderIds(apiKey, nowSeconds) {
  // Shopmonkey currently ignores descending order instructions on this
  // endpoint. Read the count, then page from the tail with a small buffer for
  // orders created between the two bounded requests.
  const firstPage = await shopmonkeyEnvelopeRequest(apiKey, "GET", "/order?limit=1&skip=0");
  const total = Number(firstPage && firstPage.meta && firstPage.meta.total);
  if (!Number.isSafeInteger(total) || total < 0) throw new Error("order_total_unavailable");
  const skip = Math.max(0, total - ORDER_LIMIT);
  const page = await shopmonkeyEnvelopeRequest(
    apiKey,
    "GET",
    `/order?limit=${ORDER_LIMIT + ORDER_RACE_BUFFER}&skip=${skip}`,
  );
  return (Array.isArray(page && page.data) ? page.data : [])
    .filter((order) => order && !order.deleted && recentlyUpdated(order, nowSeconds))
    .map((order) => String(order.id || ""))
    .filter(Boolean);
}

async function runReconciliation() {
  const apiKey = process.env.SHOPMONKEY_API_KEY || "";
  const nowSeconds = Math.floor(Date.now() / 1000);
  const nowIso = new Date().toISOString();
  if (!apiKey) throw new Error("pricing_not_configured");

  try {
    const { config } = await loadConfig();
    if (!config.enabled) {
      await recordHealth({
        last_reconcile_at: nowIso,
        last_reconcile_success_at: nowIso,
        last_reconcile_result: "pricing_disabled",
        last_api_check_at: nowIso,
        last_api_check_ok: true,
      });
      return { ok: true, orders: 0, repriced: 0, result: "pricing_disabled" };
    }

    const orderIds = config.mode === "test"
      ? (config.test_order_id ? [config.test_order_id] : [])
      : await recentOrderIds(apiKey, nowSeconds);
    const results = await mapWithConcurrency(orderIds, ORDER_CONCURRENCY, (orderId) => (
      applyPricingForOrder({
        apiKey,
        orderId,
        nowSeconds,
        maxLineAgeSeconds: config.max_line_age_seconds,
        config,
        allowPricingMatrix: false,
      })
    ));
    const repriced = results.reduce((sum, result) => sum + Number(result.repriced || 0), 0);
    await recordHealth({
      last_reconcile_at: nowIso,
      last_reconcile_success_at: new Date().toISOString(),
      last_reconcile_result: repriced ? "repriced" : "no_change",
      last_api_check_at: nowIso,
      last_api_check_ok: true,
      last_error: "",
      last_config_revision: config.revision,
      repriced_delta: repriced,
    });
    return { ok: true, orders: orderIds.length, repriced };
  } catch (_) {
    await recordHealth({
      last_reconcile_at: nowIso,
      last_error_at: new Date().toISOString(),
      last_error: "reconciliation_failed",
      last_reconcile_result: "error",
      last_api_check_at: nowIso,
      last_api_check_ok: false,
    }).catch(() => {});
    throw new Error("reconciliation_failed");
  }
}

module.exports = { recentOrderIds, recentlyUpdated, runReconciliation };
