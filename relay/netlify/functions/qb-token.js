/**
 * Stateless QuickBooks confidential-client broker.
 *
 * The desktop app is a public client and cannot safely contain Intuit's client
 * secret. This function keeps that secret in Netlify's encrypted environment,
 * performs OAuth token lifecycle requests, and returns the result only to the
 * requesting desktop app over HTTPS. It does not persist or log request or
 * response bodies.
 */

const INTUIT_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer";
const INTUIT_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke";
const DEFAULT_CLIENT_ID = "ABxAw3sNZdGuVr4twlYRJ9oCp0AtlllPTOupxGKdaoya7in6ga";
const DEFAULT_REDIRECT_URI = "https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-callback";

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

function oauthError(status) {
  if (status === 400 || status === 401) return "invalid_grant";
  if (status === 429) return "token_broker_rate_limited";
  return "token_broker_request_failed";
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return response(405, { error: "method_not_allowed" });
  if ((event.body || "").length > 16384) return response(413, { error: "request_too_large" });

  const clientId = process.env.INTUIT_CLIENT_ID || DEFAULT_CLIENT_ID;
  const clientSecret = process.env.INTUIT_CLIENT_SECRET || "";
  const redirectUri = process.env.INTUIT_REDIRECT_URI || DEFAULT_REDIRECT_URI;
  if (!clientSecret) return response(503, { error: "token_broker_not_configured" });

  let body;
  try {
    body = JSON.parse(event.body || "{}");
  } catch (_) {
    return response(400, { error: "invalid_request" });
  }
  const action = String(body.action || "");
  const basic = Buffer.from(`${clientId}:${clientSecret}`, "utf8").toString("base64");
  const headers = { Authorization: `Basic ${basic}`, Accept: "application/json" };

  try {
    if (action === "exchange") {
      if (!body.code || body.redirect_uri !== redirectUri) {
        return response(400, { error: "invalid_request" });
      }
      const form = new URLSearchParams({
        grant_type: "authorization_code",
        code: String(body.code),
        redirect_uri: redirectUri,
      });
      const upstream = await fetch(INTUIT_TOKEN_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
      });
      if (!upstream.ok) return response(400, { error: oauthError(upstream.status) });
      return response(200, await upstream.json());
    }

    if (action === "refresh") {
      if (!body.refresh_token) return response(400, { error: "invalid_request" });
      const form = new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: String(body.refresh_token),
      });
      const upstream = await fetch(INTUIT_TOKEN_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
      });
      if (!upstream.ok) return response(400, { error: oauthError(upstream.status) });
      return response(200, await upstream.json());
    }

    if (action === "revoke") {
      if (!body.token) return response(400, { error: "invalid_request" });
      const upstream = await fetch(INTUIT_REVOKE_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ token: String(body.token) }),
      });
      if (!upstream.ok) return response(400, { error: oauthError(upstream.status) });
      return response(200, { revoked: true });
    }
    return response(400, { error: "invalid_action" });
  } catch (_) {
    return response(502, { error: "token_broker_unavailable" });
  }
};
