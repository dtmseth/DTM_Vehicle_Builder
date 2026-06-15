# External Connection Security Standards

**Applies to**: All external API integrations in DTM Vehicle Builder  
**Last updated**: 2026-06-15

This document defines the mandatory security standard for every external connection this application makes. Any new integration must satisfy these requirements before merging. Existing integrations are measured against this baseline.

---

## Covered Connections

| Connection | Auth Method | Status |
|------------|-------------|--------|
| Microsoft 365 / SharePoint | OAuth 2.0 via MSAL + OS keychain | ✅ Compliant |
| GitHub | GitHub Actions secrets (server-side only) | ✅ Compliant |
| QuickBooks Online | OAuth 2.0 via `keyring` + OS keychain | Planned — Phase 1 |

---

## Credential Storage

### Rule: Use OS Keychain for All OAuth Tokens

OAuth access tokens, refresh tokens, and client secrets must be stored in the OS-native credential store — not in plaintext files and not in manually managed encryption files.

| Platform | Storage Mechanism |
|----------|------------------|
| macOS | Keychain (via `keyring` or `msal_extensions`) |
| Windows | Windows Credential Locker / DPAPI |
| Linux | libsecret / Secret Service (falls back to in-memory if unavailable) |

**Python implementation** — use the `keyring` library:

```python
import keyring

SERVICE = "DTM Vehicle Builder"

def store_credential(key: str, value: str) -> None:
    keyring.set_password(SERVICE, key, value)

def load_credential(key: str) -> str | None:
    return keyring.get_password(SERVICE, key)

def delete_credential(key: str) -> None:
    try:
        keyring.delete_password(SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
```

Store each credential under a distinct key, e.g.:
- `"qb_refresh_token"`, `"qb_access_token"`, `"qb_realm_id"`, `"qb_client_secret"`

### Rule: Non-Secret Identifiers May Live in Plain JSON

Config values that are not credentials — tenant IDs, client IDs, site IDs, realm IDs used only for routing — may be stored in plain JSON config files. These are publicly discoverable identifiers, not secrets. Examples from the M365 integration: `tenant_id`, `client_id`, `sharepoint_site_id`.

For QuickBooks, `client_id` and non-sensitive metadata (last sync timestamp, connection status) may live in `quickbooks_config.json` as plaintext. Secrets go to the OS keychain.

### Rule: No Hardcoded Credentials in Source Code

No credential value of any kind may appear as a literal string in source code or be committed to the repository. Credentials enter the app only through:
1. OS keychain (runtime read)
2. Environment variables (for CI/deployment contexts)
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
| CSRF protection | ✅ | MSAL handles state internally |
| HTTPS only | ✅ | Microsoft Graph is HTTPS-only |
| Discovery document | ✅ | MSAL handles automatically |

### GitHub

| Requirement | Status | Notes |
|-------------|--------|-------|
| Credential storage | ✅ | GitHub Actions Secrets (platform-managed) |
| Token masking in logs | ✅ | `::add-mask::` used in workflows |
| No direct connection from app | ✅ | App writes to SharePoint; GitHub Actions reads from there |

### QuickBooks Online (Planned)

| Requirement | Status | Notes |
|-------------|--------|-------|
| OS keychain token storage | Planned — Phase 1 | Use `keyring` library |
| CSRF state validation | Planned — Phase 1 | |
| 302-only callback | Planned — Phase 1 | |
| HTTPS relay for production redirect URI | Planned — Phase 1 | Hosted relay required |
| No credentials in logs | Planned — Phase 1 | |
| Token rotation | Planned — Phase 1 | QB rotates on every refresh |
| Discovery document | Planned — Phase 1 | |
| Cache-Control: no-store on QB routes | Planned — Phase 2 | |
| textContent for QB data in UI | Planned — Phase 2 | |

---

## Adding a New External Connection

Any new integration must, before merging:

1. Store all credentials in OS keychain via `keyring` (or an equivalent library that wraps the OS store)
2. Log no credential values, no token strings, no raw API response bodies
3. If OAuth: implement CSRF state validation and 302-only callback
4. If OAuth in production: HTTPS redirect URI (relay if needed for localhost apps)
5. Add `Cache-Control: no-store` to all local routes that return data from the new connection
6. Pass all external string data through `textContent` or server-side escaping before UI rendering
7. Add the connection to the compliance table in this document
