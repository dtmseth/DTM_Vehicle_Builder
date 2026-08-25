/**
 * QuickBooks OAuth Relay — Netlify Serverless Function
 *
 * Intuit Production keys require HTTPS redirect URIs on a real domain.
 * This function accepts the OAuth callback from Intuit and issues a 302
 * to the local DTM Vehicle Builder server. It never reads, stores, or
 * logs the authorization code.
 *
 * Deploy URL:  https://<site>.netlify.app/.netlify/functions/qb-callback
 * Register this URL as the redirect URI in Intuit Developer Dashboard (Production tab).
 */

const LOCAL_PORT = 7655;

exports.handler = async (event) => {
  const qs = event.queryStringParameters || {};

  // Central mode is deliberately default-off. When commissioned, the admin's
  // one-time authorization is consumed and stored server-side; normal users
  // never receive the code or any resulting QBO token.
  if (["1", "true", "yes", "on"].includes(
    String(process.env.CENTRAL_QBO_ENABLED || "").trim().toLowerCase()
  )) {
    const { completeCentralOAuth } = await import("./_shared/netlify-central.mjs");
    const result = await completeCentralOAuth({
      state: String(qs.state || ""),
      code: String(qs.code || ""),
      realmId: String(qs.realmId || ""),
      correlation: "",
    });
    return {
      statusCode: 302,
      headers: {
        Location: result.location || "/?qb=error",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
      },
      body: "",
    };
  }

  const params = new URLSearchParams(qs).toString();

  const destination = params
    ? `http://localhost:${LOCAL_PORT}/api/quickbooks/callback?${params}`
    : `http://localhost:${LOCAL_PORT}/api/quickbooks/callback`;

  return {
    statusCode: 302,
    headers: {
      Location: destination,
      "Cache-Control": "no-store",
    },
    body: "",
  };
};
