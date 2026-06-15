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
6. Set **Publish directory** to `relay/public`
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

1. Copy the live HTTPS redirect URI (from Netlify or Vercel)
2. In your Intuit Developer Dashboard → **Production tab** → **Redirect URIs** → add the URL
3. In DTM Vehicle Builder → Settings → General → QuickBooks → App Registration:
   - Paste your **Production Client ID** and **Client Secret**
   - Set Environment to **production**
   - Paste the relay URI as **Redirect URI**
   - Click **Save Settings**
4. Click **Connect to QuickBooks** — the browser will open to Intuit's consent page

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
