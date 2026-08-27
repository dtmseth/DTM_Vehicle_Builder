# External Connection Security Standards

**Applies to**: All external API integrations in DTM Vehicle Builder  
**Last updated**: 2026-08-26

This document defines the mandatory security standard for every external connection this application makes. Any new integration must satisfy these requirements before merging. Existing integrations are measured against this baseline.

---

## Covered Connections

| Connection | Auth Method | Status |
|------------|-------------|--------|
| Microsoft 365 / SharePoint | OAuth 2.0 via MSAL + OS keychain | ✅ Compliant |
| GitHub | GitHub Actions secrets (server-side only) | ✅ Compliant |
| QuickBooks Online | OAuth 2.0; per-user tokens in OS keychain; app secret in stateless Netlify broker environment | ✅ Compliant |

## Credential Storage

### Rule: Use OS Keychain for All OAuth Tokens

Desktop OAuth access tokens and refresh tokens must be stored in the OS-native credential store — not in plaintext files and not in manually managed encryption files. A confidential-client secret must never be embedded in a distributed desktop app. When a provider requires one, it belongs only in a protected server-side deployment environment.

| Platform | Storage Mechanism |
|----------|------------------|
| macOS | Keychain |
| Windows | Windows Credential Locker / DPAPI |
| Linux | libsecret / Secret Service (falls back to in-memory if unavailable) |

**Python implementation** — use `msal-extensions` encrypted persistence (already a dependency; used by both the M365 token cache and the QuickBooks credential store). It selects the right OS backend automatically and avoids adding a second keychain library.

```python
from msal_extensions import build_encrypted_persistence

# Store one encrypted JSON blob per integration. The plaintext never
# touches disk; the OS keychain holds the encryption key.
persistence = build_encrypted_persistence(location)   # .bin sentinel path
persistence.save(json.dumps(secrets))                 # encrypt + store
secrets = json.loads(persistence.load())              # decrypt
```

Reference implementations:
- M365 token cache: `adapters/cloud/msal_client.py` (`_build_token_cache`)
- QuickBooks secret blob: `adapters/quickbooks/credential_store.py` (`QuickBooksCredentialStore`)

When the keychain backend is unavailable (e.g. headless Linux without libsecret), fall back to a process-lifetime **in-memory** store — never plaintext on disk.

### Rule: Non-Secret Identifiers May Live in Plain JSON

Config values that are not credentials — tenant IDs, client IDs, site IDs, realm IDs used only for routing — may be stored in plain JSON config files. These are publicly discoverable identifiers, not secrets. Examples from the M365 integration: `tenant_id`, `client_id`, `sharepoint_site_id`.

For QuickBooks, `client_id`, managed broker URL, and non-sensitive metadata (last sync timestamp, connection status) may live in `quickbooks_config.json` as plaintext. User tokens go to the OS keychain; the Intuit app secret exists only in Netlify's protected environment.

### Rule: No Hardcoded Credentials in Source Code

No credential value of any kind may appear as a literal string in source code or be committed to the repository. Credentials enter the app only through:
1. OS keychain (desktop runtime read)
2. Protected environment variables (server-side CI/deployment contexts only)
3. User-initiated OAuth flows

---

## Logging

### Rule: Credentials and External Data Must Never Appear in Logs

The application log must never contain:
- Any token value (access token, refresh token, authorization code)
- Any credential (client secret, API key, password)
- Any identifier that could be used to reconstruct a session (realm ID, tenant ID when used as a key alongside a token)
- Raw API response bodies from external services (which may contain customer data)

Log only: operation names, HTTP status codes, timestamps, and service-provided trace IDs (e.g., `intuit_tid` from QuickBooks, correlation IDs from Microsoft Graph).

### Rule: Never Log External Request or Redirect URLs

External providers may redirect a download to a time-limited, signed URL. Those URLs can carry
temporary authorization query parameters even when the original request did not. Do not log raw
`requests` exceptions, response URLs, request URLs, redirect targets, or exception text derived
from them. Convert provider failures into a safe application error containing only the operation,
the app-relative record path, and an HTTP status or exception type. Suppress the original exception
chain when doing so.

```python
# Correct
logger.info("QB sync complete: status=%d, intuit_tid=%s", response.status_code, response.headers.get("intuit_tid"))

# Wrong — never do this
logger.debug("Token: %s", access_token)
logger.debug("Response body: %s", response.json())
```

### Rule: Credentials Must Not Appear in Browser Console

Data returned by local API routes must never include credential values. The JavaScript layer must never log tokens to `console.log`. Confirm this during testing by opening browser devtools during auth flows.

---

## OAuth Flows

These rules apply to every OAuth 2.0 Authorization Code flow the app implements.

### CSRF Protection (State Parameter)

Before opening the browser for authorization, generate a cryptographically random `state` value using `secrets.token_urlsafe(32)`. Store it in memory for the duration of the flow. When the callback arrives, compare the returned `state` using `secrets.compare_digest`. Reject with HTTP 400 on any mismatch. Consume the state value after one use.

### OAuth Callback — 302 Redirect Required

The OAuth callback endpoint must never return HTML content that echoes the authorization code, tokens, or any URL parameter. After completing the token exchange and storing credentials, issue a server-side HTTP `302 Found` redirect to a clean URL. This prevents credential leakage via HTTP Referer headers.

### HTTPS Redirect URI for Production

OAuth redirect URIs registered for production environments must use HTTPS on a real domain. `http://localhost` is acceptable for development/sandbox environments only. For desktop apps that run on localhost, a hosted relay endpoint (a minimal serverless function that issues a 302 to localhost) satisfies this requirement.

### Confidential Desktop Clients

Never ship a provider client secret inside an installer. The managed QuickBooks flow uses two small
HTTPS functions on the verified Netlify origin: `qb-callback` remains a redirect-only 302 relay,
and `qb-token` performs exchange/refresh/revoke using the Intuit secret from Netlify's protected
environment. The broker is stateless, uses `Cache-Control: no-store`, never logs bodies, and never
stores a user token. Returned tokens go directly to the requesting desktop and are immediately
saved in that workstation's OS keychain.

### Token Rotation

For any OAuth provider that rotates refresh tokens on use (QuickBooks does; MSAL handles this internally for M365): the new token must be stored immediately after every token refresh. The previous token is invalidated. Failure to store the new token breaks the connection permanently.

### Discovery Documents

Use the provider's OpenID Connect discovery document to obtain current endpoint URLs rather than hardcoding them. This ensures the app handles endpoint changes without a code update.

- QuickBooks: `https://developer.api.intuit.com/.well-known/openid_configuration`
- Microsoft: `https://login.microsoftonline.com/{tenant}/.well-known/openid-configuration` (MSAL handles this automatically)

---

## HTTP Security

### Cache-Control

Any local API route (`/api/*`) that returns data sourced from an external service must include:

```
Cache-Control: no-store
```

This prevents sensitive data from being cached by the pywebview browser component.

### HTTP Method Restriction

The local HTTP server must reject any HTTP method it does not explicitly handle with `405 Method Not Allowed`. At minimum, `TRACE` must be disabled. This applies regardless of route.

### All External Traffic Over HTTPS

Every outbound request to an external service must use HTTPS. Plain HTTP to external hosts is never acceptable.

---

## Input Handling

### External Data Rendered in the UI

Any string value received from an external API that is rendered in the browser UI must be treated as untrusted. Use `textContent` (not `innerHTML`) when inserting external data via JavaScript. If server-side rendering is used, HTML-escape all external values before including them in responses.

### Data Passed to XML/Document Generation

Data from external APIs that flows into document generation (python-pptx, lxml, openpyxl) must be sanitized to strip or escape characters that have meaning in XML (`<`, `>`, `&`, `"`, `'`) before being passed to the generation layer.

---

## Compliance by Connection

### Microsoft 365 / SharePoint

| Requirement | Status | Notes |
|-------------|--------|-------|
| OS keychain token storage | ✅ | `msal_extensions` uses Keychain/DPAPI/libsecret |
| No plaintext token storage | ✅ | Tokens are ephemeral in memory |
| No credentials in logs | ✅ | Verified in audit |
| Signed redirect URLs excluded from logs/errors | ✅ | `SharePointGraphProvider` converts HTTP and transport failures to safe summaries without request/redirect URLs |
| CSRF protection | ✅ | MSAL handles state internally |
| HTTPS only | ✅ | Microsoft Graph is HTTPS-only |
| Discovery document | ✅ | MSAL handles automatically |

### GitHub

| Requirement | Status | Notes |
|-------------|--------|-------|
| Credential storage | ✅ | GitHub Actions Secrets (platform-managed) |
| Token masking in logs | ✅ | `::add-mask::` used in workflows |
| No direct connection from app | ✅ | App writes to SharePoint; GitHub Actions reads from there |

### QuickBooks Online

| Requirement | Status | Notes |
|-------------|--------|-------|
| OS keychain token storage | ✅ | `msal-extensions` encrypted blob, in-memory fallback |
| CSRF state validation | ✅ | `secrets.compare_digest`, single-use state |
| 302-only callback | ✅ | `routes/quickbooks.py` `_handle_callback` |
| No credentials in logs | ✅ | OAuth client logs no tokens/bodies; service logs no secrets |
| Token rotation | ✅ | Rotated refresh token saved on every refresh |
| Discovery document | ✅ | `oauth_client._discover()` with static fallback |
| Cache-Control: no-store on QB routes | ✅ | Set on all `/api/quickbooks/*` responses |
| HTTPS relay for production redirect URI | ✅ | Deployed `qb-callback` relay on the verified Netlify origin; 302-only and stateless |
| Isolated production catalog preview | ✅ | Separate metadata/keychain/cache; preview cannot reconcile, poll, or write Builder catalog data |
| Safe QB data rendering in UI | ✅ | QB/catalog values use DOM text nodes/`textContent`; smoke coverage rejects unsafe external requests and console failures |

---

## Adding a New External Connection

Any new integration must, before merging:

1. Store all credentials in the OS keychain via `msal-extensions` encrypted persistence (see `adapters/quickbooks/credential_store.py` for the pattern)
2. Log no credential values, no token strings, no raw API response bodies
3. If OAuth: implement CSRF state validation and 302-only callback
4. If OAuth in production: HTTPS redirect URI (relay if needed for localhost apps)
5. Add `Cache-Control: no-store` to all local routes that return data from the new connection
6. Pass all external string data through `textContent` or server-side escaping before UI rendering
7. Add the connection to the compliance table in this document
