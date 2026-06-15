/**
 * QuickBooks OAuth Relay — Vercel Serverless Function
 *
 * Intuit Production keys require HTTPS redirect URIs on a real domain.
 * This function accepts the OAuth callback from Intuit and issues a 302
 * to the local DTM Vehicle Builder server. It never reads, stores, or
 * logs the authorization code.
 *
 * Deploy URL:  https://<project>.vercel.app/api/qb-callback
 * Register this URL as the redirect URI in Intuit Developer Dashboard (Production tab).
 */

const LOCAL_PORT = 7655;

module.exports = function handler(req, res) {
  const params = new URLSearchParams(req.query || {}).toString();

  const destination = params
    ? `http://localhost:${LOCAL_PORT}/api/quickbooks/callback?${params}`
    : `http://localhost:${LOCAL_PORT}/api/quickbooks/callback`;

  res.setHeader("Cache-Control", "no-store");
  res.redirect(302, destination);
};
