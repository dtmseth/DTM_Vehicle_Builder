/**
 * Signed Shopmonkey Order webhook for production customer/brand pricing.
 *
 * Rules are loaded from the site-wide hosted configuration edited by the DTM
 * Builder. The code fails closed for missing/ambiguous customer types, unknown
 * brands, invalid price bases, non-writable orders, and custom line prices.
 * Secrets are supplied only by Netlify's protected environment. No request or
 * provider bodies are logged.
 */

const crypto = require("node:crypto");
const { connectLambda } = require("@netlify/blobs");
const {
  loadConfig,
  normalized,
  recordHealth,
  targetPriceCents,
} = require("../../lib/shopmonkey-pricing");

const API_BASE = "https://api.shopmonkey.cloud/v3";
const MAX_BODY_BYTES = 64 * 1024;
const SIGNATURE_TOLERANCE_SECONDS = 5 * 60;
const REQUEST_TIMEOUT_MS = 10_000;
const INVENTORY_CONCURRENCY = 8;

const completedDeliveries = new Map();

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

function header(event, name) {
  const wanted = name.toLowerCase();
  for (const [key, value] of Object.entries(event.headers || {})) {
    if (key.toLowerCase() === wanted) return String(value || "");
  }
  return "";
}

function rawBody(event) {
  const encoded = String(event.body || "");
  return event.isBase64Encoded
    ? Buffer.from(encoded, "base64")
    : Buffer.from(encoded, "utf8");
}

function constantTimeTextEqual(left, right) {
  const a = Buffer.from(String(left), "utf8");
  const b = Buffer.from(String(right), "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function verifySignature({ secret, messageId, timestamp, signature, payload, nowSeconds }) {
  if (!secret || !messageId || !timestamp || !signature) return false;
  if (!/^\d+$/.test(timestamp)) return false;
  const sentAt = Number(timestamp);
  if (!Number.isSafeInteger(sentAt)) return false;
  if (Math.abs(nowSeconds - sentAt) > SIGNATURE_TOLERANCE_SECONDS) return false;

  const rawKey = Buffer.from(secret, "utf8");
  const serializedKey = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  let decodedKey = Buffer.alloc(0);
  try {
    decodedKey = Buffer.from(serializedKey, "base64url");
  } catch (_) {
    decodedKey = Buffer.alloc(0);
  }
  const signingKeys = [rawKey];
  // Shopmonkey references Standard Webhooks, whose official libraries base64-decode
  // the presented secret before HMAC. Its guide also describes the literal secret as
  // the key, so accept both documented representations during key rotation.
  if (decodedKey.length >= 24 && decodedKey.length <= 64 && !decodedKey.equals(rawKey)) {
    signingKeys.push(decodedKey);
  }
  const digests = signingKeys.map((key) => crypto
    .createHmac("sha256", key)
    .update(`${messageId}.${timestamp}.`, "utf8")
    .update(payload)
    .digest("base64"));

  return signature
    .trim()
    .split(/\s+/)
    .some((candidate) => {
      const separator = candidate.indexOf(",");
      return separator > 0
        && candidate.slice(0, separator) === "v1"
        && digests.some((digest) => constantTimeTextEqual(candidate.slice(separator + 1), digest));
    });
}

class UpstreamError extends Error {
  constructor(status) {
    super("shopmonkey_request_failed");
    this.status = status;
  }
}

async function shopmonkeyEnvelopeRequest(apiKey, method, path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const upstream = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!upstream.ok) throw new UpstreamError(upstream.status);
    let payload;
    try {
      payload = await upstream.json();
    } catch (_) {
      throw new UpstreamError(502);
    }
    if (!payload || typeof payload !== "object" || payload.success === false) {
      throw new UpstreamError(502);
    }
    return payload;
  } catch (error) {
    if (error instanceof UpstreamError) throw error;
    throw new UpstreamError(502);
  } finally {
    clearTimeout(timeout);
  }
}

async function shopmonkeyRequest(apiKey, method, path, body) {
  return (await shopmonkeyEnvelopeRequest(apiKey, method, path, body)).data;
}

function partsFromServices(services) {
  const rows = [];
  for (const service of Array.isArray(services) ? services : []) {
    for (const part of Array.isArray(service.parts) ? service.parts : []) {
      rows.push({ service, part });
    }
  }
  return rows;
}

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

function isRecentLine(line, nowSeconds, maxAgeSeconds) {
  const createdSeconds = Date.parse(String(line.createdDate || "")) / 1000;
  if (!Number.isFinite(createdSeconds)) return false;
  const age = nowSeconds - createdSeconds;
  return age >= -30 && age <= maxAgeSeconds;
}

function matrixPriceLooksAutomatic(line) {
  if (!String(line.pricingMatrixId || "")) return false;
  const created = Date.parse(String(line.createdDate || ""));
  const updated = Date.parse(String(line.updatedDate || ""));
  // Shopmonkey may omit updatedDate on a newly inserted matrix-priced line.
  // Once a later edit timestamp exists, do not use the matrix ID as proof that
  // the current value is automatic; some providers retain origin metadata.
  return Number.isFinite(created) && (!Number.isFinite(updated) || updated - created <= 5000);
}

function deliveryAlreadyCompleted(messageId, nowSeconds) {
  for (const [id, expires] of completedDeliveries) {
    if (expires <= nowSeconds) completedDeliveries.delete(id);
  }
  return completedDeliveries.has(messageId);
}

async function applyPricingForOrder({
  apiKey,
  orderId,
  nowSeconds,
  maxLineAgeSeconds,
  config,
  allowPricingMatrix = true,
}) {
  const encodedOrderId = encodeURIComponent(orderId);
  const [order, services] = await Promise.all([
    shopmonkeyRequest(apiKey, "GET", `/order/${encodedOrderId}`),
    shopmonkeyRequest(apiKey, "GET", `/order/${encodedOrderId}/service`),
  ]);

  if (!order || order.id !== orderId || order.authorized || order.invoiced || order.readOnly) {
    return { result: "order_not_writable", repriced: 0 };
  }

  const customerId = String(order.customerId || "");
  if (!customerId) return { result: "customer_missing", repriced: 0 };
  const customer = await shopmonkeyRequest(
    apiKey,
    "GET",
    `/customer/${encodeURIComponent(customerId)}`,
  );
  const labelRows = Array.isArray(customer && customer.labels) ? customer.labels : [];
  const labelIds = new Set(labelRows.map((label) => String(label && label.id || "")).filter(Boolean));
  const labels = new Set(
    labelRows.map((label) => normalized(label && label.name)),
  );
  const enabledCustomerTypes = (config.customer_types || []).filter((row) => row.enabled);
  const matchingCustomerTypes = enabledCustomerTypes.filter((row) => (
    !row.match_untagged && (row.label_id
      ? labelIds.has(String(row.label_id))
      : labels.has(normalized(row.label)))
  ));
  if (matchingCustomerTypes.length > 1) {
    return { result: "customer_type_ambiguous", repriced: 0 };
  }
  const untaggedCustomerTypes = enabledCustomerTypes.filter((row) => row.match_untagged);
  if (!matchingCustomerTypes.length && untaggedCustomerTypes.length > 1) {
    return { result: "customer_type_ambiguous", repriced: 0 };
  }
  const customerType = matchingCustomerTypes[0] || untaggedCustomerTypes[0];
  if (!customerType) return { result: "customer_type_missing", repriced: 0 };
  const enabledRules = (config.rules || [])
    .filter((row) => row.enabled && row.customer_type_id === customerType.id);
  const rulesById = new Map(enabledRules.filter((row) => row.brand_id)
    .map((row) => [String(row.brand_id), row]));
  const legacyRulesByName = new Map(enabledRules.filter((row) => !row.brand_id)
    .map((row) => [normalized(row.brand), row]));

  let repriced = 0;
  let manualPreserved = 0;
  let eligibleLines = 0;
  let missingRule = 0;
  let invalidPriceBasis = 0;
  let lastTargetCents = null;
  const recentLines = partsFromServices(services).filter(({ part }) => (
    isRecentLine(part, nowSeconds, maxLineAgeSeconds)
  ));
  const lineCandidates = recentLines
    .map(({ service, part }) => ({
      service,
      part,
      lineInventoryId: String(part.inventoryPartId || ""),
    }))
    .filter(({ lineInventoryId }) => lineInventoryId);
  const candidatesWithInventory = await mapWithConcurrency(
    lineCandidates,
    INVENTORY_CONCURRENCY,
    async (candidate) => ({
    ...candidate,
    inventory: await shopmonkeyRequest(
      apiKey,
      "GET",
      `/inventory_part/${encodeURIComponent(candidate.lineInventoryId)}`,
    ),
    }),
  );

  for (const {
    service,
    part,
    lineInventoryId,
    inventory,
  } of candidatesWithInventory) {
    if (!inventory || inventory.deleted || String(inventory.id || "") !== lineInventoryId) continue;
    const brandObject = inventory && typeof inventory.brand === "object" ? inventory.brand : null;
    const brand = brandObject ? brandObject.name : inventory.brand;
    const rule = (brandObject && rulesById.get(String(brandObject.id || "")))
      || legacyRulesByName.get(normalized(brand));
    if (!rule) {
      missingRule += 1;
      continue;
    }
    const targetCents = targetPriceCents(inventory, rule);
    if (targetCents === null) {
      invalidPriceBasis += 1;
      continue;
    }
    eligibleLines += 1;
    lastTargetCents = targetCents;

    const currentCents = Number(part.retailCostCents);
    if (!Number.isSafeInteger(currentCents) || currentCents === targetCents) continue;
    const inventoryRetailCents = Number(inventory.retailCostCents);
    const automaticallyPriced = currentCents === inventoryRetailCents
      || (allowPricingMatrix && matrixPriceLooksAutomatic(part));
    if (!automaticallyPriced) {
      manualPreserved += 1;
      continue;
    }

    const serviceId = String(service.id || "");
    const lineId = String(part.id || "");
    if (!serviceId || !lineId) throw new UpstreamError(502);
    await shopmonkeyRequest(
      apiKey,
      "PUT",
      `/order/${encodedOrderId}/service/${encodeURIComponent(serviceId)}/part/${encodeURIComponent(lineId)}?includeOrder=false`,
      { retailCostCents: targetCents },
    );
    repriced += 1;
  }

  return {
    result: repriced ? "repriced" : "no_change",
    repriced,
    manual_preserved: manualPreserved,
    eligible_lines: eligibleLines,
    missing_rule: missingRule,
    invalid_price_basis: invalidPriceBasis,
    customer_type: customerType.id,
    ...(recentLines.length === 1 && lastTargetCents !== null
      ? { target_cents: lastTargetCents }
      : {}),
  };
}

exports.handler = async (event) => {
  if (event.blobs) connectLambda(event);
  if (event.httpMethod !== "POST") return response(405, { ok: false, error: "method_not_allowed" });

  const payload = rawBody(event);
  if (!payload.length || payload.length > MAX_BODY_BYTES) {
    return response(413, { ok: false, error: "request_too_large" });
  }
  if (!/^application\/json(?:\s*;|$)/i.test(header(event, "content-type"))) {
    return response(415, { ok: false, error: "json_required" });
  }

  const secret = process.env.SHOPMONKEY_WEBHOOK_SECRET || "";
  const apiKey = process.env.SHOPMONKEY_API_KEY || "";
  if (!secret || !apiKey) {
    return response(503, { ok: false, error: "webhook_not_configured" });
  }

  const messageId = header(event, "webhook-id");
  const timestamp = header(event, "webhook-timestamp");
  const signature = header(event, "webhook-signature");
  const version = header(event, "webhook-version");
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (version !== "3" || !verifySignature({
    secret,
    messageId,
    timestamp,
    signature,
    payload,
    nowSeconds,
  })) {
    return response(401, { ok: false, error: "invalid_signature" });
  }

  if (deliveryAlreadyCompleted(messageId, nowSeconds)) {
    return response(200, { ok: true, result: "duplicate" });
  }

  let webhook;
  try {
    webhook = JSON.parse(payload.toString("utf8"));
  } catch (_) {
    return response(400, { ok: false, error: "invalid_request" });
  }
  const orderId = String(webhook && webhook.data && (webhook.data.id || webhook.data.orderId) || "");
  if (
    String(webhook.apiVersion) !== "3"
    || !["INSERT", "UPDATE"].includes(String(webhook.operation || "").toUpperCase())
    || normalized(webhook.table) !== "order"
    || !orderId
  ) {
    completedDeliveries.set(messageId, nowSeconds + SIGNATURE_TOLERANCE_SECONDS);
    return response(200, { ok: true, result: "ignored" });
  }

  try {
    const { config } = await loadConfig();
    if (!config.enabled) {
      completedDeliveries.set(messageId, nowSeconds + SIGNATURE_TOLERANCE_SECONDS);
      return response(200, { ok: true, result: "pricing_disabled" });
    }
    if (config.mode === "test" && orderId !== config.test_order_id) {
      completedDeliveries.set(messageId, nowSeconds + SIGNATURE_TOLERANCE_SECONDS);
      return response(200, { ok: true, result: "ignored_test_scope" });
    }
    const receivedAt = new Date().toISOString();
    const result = await applyPricingForOrder({
      apiKey,
      orderId,
      nowSeconds,
      maxLineAgeSeconds: config.max_line_age_seconds,
      config,
      allowPricingMatrix: true,
    });
    await recordHealth({
      last_received_at: receivedAt,
      last_success_at: new Date().toISOString(),
      last_error: "",
      last_result: result.result,
      last_config_revision: config.revision,
      repriced_delta: result.repriced,
    }).catch(() => {});
    completedDeliveries.set(messageId, nowSeconds + SIGNATURE_TOLERANCE_SECONDS);
    return response(200, { ok: true, ...result });
  } catch (error) {
    await recordHealth({
      last_received_at: new Date().toISOString(),
      last_error_at: new Date().toISOString(),
      last_error: error instanceof UpstreamError ? `shopmonkey_${error.status}` : "pricing_unavailable",
      last_result: "error",
    }).catch(() => {});
    if (error instanceof UpstreamError && error.status === 429) {
      return response(429, { ok: false, error: "shopmonkey_rate_limited" });
    }
    return response(500, { ok: false, error: "pricing_unavailable" });
  }
};
exports.__test = {
  applyPricingForOrder,
  isRecentLine,
  mapWithConcurrency,
  matrixPriceLooksAutomatic,
  shopmonkeyEnvelopeRequest,
  shopmonkeyRequest,
  verifySignature,
};
