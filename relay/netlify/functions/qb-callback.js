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
