# QuickBooks OAuth Relay and Token Broker — Deployment Guide

Intuit Production keys require an **HTTPS redirect URI on a real domain** — `localhost` is not accepted. The callback function immediately 302s to the local DTM Vehicle Builder server. A second stateless function performs token exchange/refresh/revoke so the Intuit client secret is never embedded in the desktop installer. Neither function stores or logs tokens or request bodies.

```
Intuit → https://your-relay-url/qb-callback?code=...&state=...&realmId=...
              │
              └── 302 → http://localhost:7655/api/quickbooks/callback?code=...&state=...&realmId=...
                            │
                            └── Local app captures tokens (in OS keychain)
```

---

## Option A — Netlify (Recommended)

Netlify's free tier is more than enough. You can deploy from this repo or drag-drop a folder.

The verified production site is `https://dtmvehiclebuilder.netlify.app`.

### Deploy via Netlify CLI

```bash
npm install -g netlify-cli
cd relay/
netlify deploy --prod
```

The live URL will look like `https://magical-name-12345.netlify.app`.

### Deploy via GitHub (zero-config)

1. Push this repo to GitHub (or a fork of it)
2. Go to [app.netlify.com](https://app.netlify.com) → **Add new site → Import an existing project**
3. Connect to your repo
4. Set **Base directory** to `relay`
5. Leave Build command empty
6. Set **Publish directory** to `public`
7. Click **Deploy site**

### Required protected environment

In Netlify → Site configuration → Environment variables, add:

| Variable | Value |
|---|---|
| `INTUIT_CLIENT_SECRET` | Current Intuit Production client secret |
| `INTUIT_CLIENT_ID` | `ABxAw3sNZdGuVr4twlYRJ9oCp0AtlllPTOupxGKdaoya7in6ga` (optional; this verified public ID is also the code default) |
| `INTUIT_REDIRECT_URI` | `https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-callback` (optional; this verified URI is also the code default) |

Mark the secret as a secret value. Never put it in `netlify.toml`, a local `.env`, a build command,
or the repository. Trigger a new production deploy after changing an environment variable.

### Redirect URI to register in Intuit

```
https://<your-netlify-site>.netlify.app/.netlify/functions/qb-callback
```

Or with a custom domain (e.g. pointed at Netlify):
```
https://relay.northwindvisuals.com/.netlify/functions/qb-callback
```

---

## Option B — Vercel

```bash
npm install -g vercel
cd relay/
vercel --prod
```

The live URL will look like `https://dtm-qb-relay.vercel.app`.

### Redirect URI to register in Intuit

```
https://<your-vercel-project>.vercel.app/api/qb-callback
```

---

## After Deploying

1. Use the verified production origin exactly, without a trailing slash:
   `https://dtmvehiclebuilder.netlify.app`.
2. Verify all public assessment routes and the callback response:

   ```bash
   bash verify_deployment.sh https://<deployed-origin> netlify
   ```

   Use `vercel` as the second argument for a Vercel deployment. The explicit provider argument also
   handles custom domains correctly.

3. Enter the following values in Intuit, substituting only the verified deployed origin:

   | Intuit field | Netlify value | Vercel value |
   |---|---|---|
   | App host domain | `<deployed-origin-hostname>` | `<deployed-origin-hostname>` |
   | Launch URL | `<deployed-origin>/` | `<deployed-origin>/` |
   | Connect URL | `<deployed-origin>/connect/` | `<deployed-origin>/connect/` |
   | Reconnect URL | `<deployed-origin>/reconnect/` | `<deployed-origin>/reconnect/` |
   | Disconnect URL | `<deployed-origin>/disconnect/` | `<deployed-origin>/disconnect/` |
   | Production redirect URI | `<deployed-origin>/.netlify/functions/qb-callback` | `<deployed-origin>/api/qb-callback` |

4. In the Intuit Developer Dashboard → **Production** → **Redirect URIs**, add the verified
   Production redirect URI.
5. Store the Production secret only in Netlify's protected environment. Released desktops contain
   the public client ID and broker URL, so users click **Connect to QuickBooks** and sign in; they
   never enter or receive the client secret.

---

## Security Notes

- The callback function issues only HTTP 302 — it never returns HTML
- `Cache-Control: no-store` is set on every response
- The callback never reads, stores, or logs `code`, `state`, or `realmId`
- The token broker never stores or logs codes, tokens, or response bodies
- The Intuit client secret exists only in Netlify's protected environment and is never shipped

---

## Sandbox / Development Testing

For sandbox testing (Development keys), skip the relay entirely. In the Intuit Developer Dashboard's **Development tab**, register:

```
http://localhost:7655/api/quickbooks/callback
```

Set Environment to **sandbox** in the app, and the local callback is used directly.
