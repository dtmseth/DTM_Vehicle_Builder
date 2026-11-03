"use strict";

const { connectLambda } = require("@netlify/blobs");

/**
 * Authenticated configuration boundary for the Builder's Shopmonkey pricing UI.
 * The desktop signs requests with its keychain-held Shopmonkey API key; the key
 * itself is never sent to this endpoint or stored in a workspace file.
 */

const {
  loadConfig,
  loadHealth,
  saveConfig,
  verifyManagementRequest,
} = require("../../lib/shopmonkey-pricing");

const MAX_BODY_BYTES = 64 * 1024;
const seenNonces = new Map();

function response(statusCode, payload) {
  return {
    statusCode,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
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
  return event.isBase64Encoded ? Buffer.from(encoded, "base64") : Buffer.from(encoded, "utf8");
}

function nonceWasSeen(nonce, nowSeconds) {
  for (const [value, expires] of seenNonces) {
    if (expires <= nowSeconds) seenNonces.delete(value);
  }
  if (seenNonces.has(nonce)) return true;
  seenNonces.set(nonce, nowSeconds + 5 * 60);
  return false;
}

exports.handler = async (event) => {
  if (event.blobs) connectLambda(event);
  const method = String(event.httpMethod || "").toUpperCase();
  if (!['GET', 'PUT'].includes(method)) return response(405, { ok: false, error: "method_not_allowed" });

  const body = rawBody(event);
  if (body.length > MAX_BODY_BYTES) return response(413, { ok: false, error: "request_too_large" });
  if (method === "PUT" && !/^application\/json(?:\s*;|$)/i.test(header(event, "content-type"))) {
    return response(415, { ok: false, error: "json_required" });
  }

  const apiKey = process.env.SHOPMONKEY_API_KEY || "";
  if (!apiKey) return response(503, { ok: false, error: "pricing_not_configured" });
  const timestamp = header(event, "x-dtm-timestamp");
  const nonce = header(event, "x-dtm-nonce");
  const signature = header(event, "x-dtm-signature");
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (!verifyManagementRequest({
    secret: apiKey,
    timestamp,
    nonce,
    method,
    body,
    signature,
    nowSeconds,
  }) || nonceWasSeen(nonce, nowSeconds)) {
    return response(401, { ok: false, error: "invalid_management_signature" });
  }

  try {
    if (method === "GET") {
      const [{ config, persisted }, health] = await Promise.all([loadConfig(), loadHealth()]);
      return response(200, { ok: true, config, persisted, health });
    }

    let payload;
    try {
      payload = JSON.parse(body.toString("utf8"));
    } catch (_) {
      return response(400, { ok: false, error: "invalid_request" });
    }
    const result = await saveConfig(payload && payload.config, payload && payload.expected_revision);
    if (result.conflict) {
      return response(409, { ok: false, error: "pricing_config_conflict", config: result.config });
    }
    if (!result.ok) {
      return response(400, { ok: false, error: "pricing_config_invalid", errors: result.errors || [] });
    }
    return response(200, { ok: true, config: result.config });
  } catch (_) {
    return response(503, { ok: false, error: "pricing_config_unavailable" });
  }
};
