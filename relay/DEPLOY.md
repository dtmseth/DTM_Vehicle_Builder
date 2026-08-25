# QuickBooks Relay and Central Builder API — Deployment Guide

Intuit Production keys require an **HTTPS redirect URI on a real domain** — `localhost` is not
accepted. The live/default compatibility mode immediately relays the callback to the desktop and
uses a stateless token broker so the Intuit client secret is never embedded in the installer.

The repository also contains a **default-off, not-yet-deployed central mode**. In that mode an
authorized Builder Admin completes Intuit consent once, the callback stores application-encrypted
credentials server-side, and employees use only Microsoft 365 tokens issued for the Builder API.
Do not enable central mode as part of an ordinary relay deploy.

```
Intuit → https://your-relay-url/qb-callback?code=...&state=...&realmId=...
              │
              └── 302 → http://localhost:7655/api/quickbooks/callback?code=...&state=...&realmId=...
                            │
                            └── Local app captures tokens (in OS keychain)
```

---

## Netlify (selected host)

The existing DTM Netlify site is the selected host so this design adds no service provider. The Free
plan uses a hard monthly credit pool. If it is exhausted, Netlify pauses the site and functions
instead of silently charging an overage. The desktop recognizes that platform page and tells the
user that the Estimate was not created, the build is safe, and a Builder Admin must check
**Netlify → Usage & billing** or wait for the monthly reset. Verify current plan allowances before
commissioning; production deploys, function compute, requests, bandwidth, and storage can all use
plan capacity.

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

### Additional central-mode environment (do not configure or enable casually)

The central adapter refuses to start if its protected configuration is incomplete. Keep
`CENTRAL_QBO_ENABLED=false` through the first isolated deployment and verification.

| Variable | Purpose |
|---|---|
| `CENTRAL_QBO_ENABLED` | Explicit kill switch; absent/false preserves the live stateless relay behavior |
| `ENTRA_TENANT_ID` | Single allowed Microsoft tenant |
| `BUILDER_API_AUDIENCE` | Entra Builder API application/client ID expected in `aud` |
| `ENTRA_JWKS_URL` | Optional tenant JWKS override; normally derived from the tenant ID |
| `QBO_TOKEN_ENCRYPTION_KEY` | Dedicated random 32-byte key encoded as Base64; protect and back it up separately |
| `QBO_REALM_KEY` | Non-secret internal company alias; defaults to `dtm-company` |
| `QBO_ENVIRONMENT` | `sandbox` for isolated validation; later `production` only after approval |
| `QBO_MINOR_VERSION` | Optional Accounting API minor version; defaults to the reviewed code value |

Central mode also requires the existing `INTUIT_CLIENT_ID`, `INTUIT_CLIENT_SECRET`, and
`INTUIT_REDIRECT_URI`. Netlify Blobs hold only AES-256-GCM envelopes for credentials and OAuth state;
the encryption key remains in protected environment configuration. Strong reads and conditional
ETags serialize refresh-token rotation. Audit entries contain employee object ID, action, outcome,
time, entity type, and correlation ID—but no token, provider body, URL, or customer payload.

### Required Entra registration before isolated central testing

1. Create a single-tenant Builder API registration and expose delegated scope `Builder.Access`.
2. Define app roles `Builder.User` and `Builder.Admin`; assign normal users/admins deliberately.
3. Grant the existing desktop app the delegated Builder API permission and provide tenant admin
   consent. A Microsoft Graph token is not accepted by the central API.
4. Put only the public tenant ID, API audience, and delegated scope in desktop central config.
5. First deploy with central mode disabled. Then enable only in the isolated test context and compare
   company health and active Items against the existing local path before any write migration.

### Redirect URI to register in Intuit

```
https://<your-netlify-site>.netlify.app/.netlify/functions/qb-callback
```

Or with a custom domain (e.g. pointed at Netlify):
```
https://relay.northwindvisuals.com/.netlify/functions/qb-callback
```

---

## Legacy Vercel relay option

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
- In default compatibility mode, the callback forwards but never stores or logs `code`, `state`, or
  `realmId`; in central mode it consumes one-time encrypted state and passes the code directly to
  Intuit without logging or returning it
- The token broker never stores or logs codes, tokens, or response bodies
- The Intuit client secret exists only in Netlify's protected environment and is never shipped
- Central credentials never return to a desktop; only the server runtime can decrypt their Blob
  envelopes
- Estimate creation and PDF attachment remain separate writes; neither may be automatically retried
  because the other failed

## Central-mode recovery and usage limit

- If the desktop reports `central_service_limit_reached`, confirm that no Estimate was created, open
  **Netlify → Usage & billing**, and check whether the account/site is paused. Restore service or
  wait for the monthly reset, confirm central health, then retry once.
- Do not tell a user to reconnect Intuit for a Netlify usage pause. Reauthorization cannot restore a
  paused function.
- A normal provider outage remains `central_service_unavailable`; the desktop only labels a monthly
  limit when a bounded response matches Netlify's provider-owned pause page or the safe structured
  capacity code.
- Before production authorization, document Blob retention/export, encryption-key recovery and
  rotation, Entra role recovery, usage alerts, and the owner-only reconnect procedure.

---

## Sandbox / Development Testing

For sandbox testing (Development keys), skip the relay entirely. In the Intuit Developer Dashboard's **Development tab**, register:

```
http://localhost:7655/api/quickbooks/callback
```

Set Environment to **sandbox** in the app, and the local callback is used directly.
