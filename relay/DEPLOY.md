# QuickBooks OAuth Relay — Deployment Guide

Intuit Production keys require an **HTTPS redirect URI on a real domain** — `localhost` is not accepted. This tiny relay endpoint acts as a pass-through: it accepts the callback from Intuit and immediately 302s to the local DTM Vehicle Builder server. It never reads, stores, or logs the authorization code.

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

1. Copy the deployed origin exactly, without a trailing slash (for example,
   `https://dtm-qb-relay.netlify.app`). Do not invent or pre-enter a hostname before the provider
   has assigned it.
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
5. After Intuit approves the app and issues Production credentials, enter them only in DTM Vehicle
   Builder → Advanced Settings → **QB Catalog Preview**. Paste the same Production redirect URI.
   Do not switch the standard QuickBooks profile to Production.
6. Stop before selecting **Connect production preview** until the owner is ready to authorize and
   review the production mapping workflow.

---

## Security Notes

- The relay function issues only HTTP 302 — it never returns HTML
- `Cache-Control: no-store` is set on every response
- The function never reads, stores, or logs `code`, `state`, or `realmId`
- The authorization code is valid for only a few minutes and is useless without the client secret, which never leaves your machine

---

## Sandbox / Development Testing

For sandbox testing (Development keys), skip the relay entirely. In the Intuit Developer Dashboard's **Development tab**, register:

```
http://localhost:7655/api/quickbooks/callback
```

Set Environment to **sandbox** in the app, and the local callback is used directly.
