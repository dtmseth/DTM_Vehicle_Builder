# QuickBooks App Assessment Questionnaire — Prepared Answers

**App**: DTM Vehicle Builder  
**Purpose**: Internal use only — connects to our single QBO company  
**Last updated**: 2026-06-15

Use this document as a reference when completing the questionnaire in the Intuit Developer Dashboard. The questionnaire is organized into tabs; the sections below follow that order.

Before starting the questionnaire, complete Phase 1 of the integration (OAuth flow working against sandbox) and run the full connect / disconnect / reconnect test cycle. Intuit requires testing to be confirmed and will reject submissions where it has not been done.

---

## Before You Begin — Information to Have Ready

| Field | Value |
|-------|-------|
| App name | DTM Vehicle Builder |
| App category | Accounting / Internal business tool |
| Countries served | United States |
| Number of QBO companies (realms) | 1 — our company only |
| Host domain | [your domain, e.g. dtmnorthwindvisuals.com] |
| Launch URL | https://[your-domain.com] |
| Disconnect URL | https://[your-domain.com] |
| Redirect URI (Production) | https://[your-domain.com]/.netlify/functions/qb-callback |
| Redirect URI (Development) | http://localhost:7655/api/quickbooks/callback |
| Scope | com.intuit.quickbooks.accounting |
| Hosting location | United States — runs locally on user machines |
| IP address | Not applicable — desktop application, no fixed IP |

---

## Section 1 — How Your App Operates

**What does your app do?**
> DTM Vehicle Builder is an internal desktop application used by our team to configure and generate vehicle build sheets for law enforcement and emergency vehicle upfits. The QuickBooks integration syncs our parts catalog (QBO Items) into the app so that part numbers, descriptions, and pricing stay current, and creates QBO Customer and Project records from build projects so our technicians can log time against specific vehicle builds in QuickBooks.

**Who are your customers / users?**
> This app is for internal use only. It is used exclusively by our own company's staff. It is not distributed to or used by any external customers or third parties.

**How many QuickBooks companies will your app connect to?**
> One (1). This app connects only to our own company's QuickBooks Online account. It is not a multi-tenant or multi-company application.

**Does your app integrate with platforms other than Intuit?**
> No.

**Is your app available to the public?**
> No. This is an internal tool, not published on any app store or available for external download.

---

## Section 2 — How You Manage Data

**Do you store QuickBooks data?**
> Yes, locally on the machine running the application. Parts data (item names, SKUs, unit prices, active status) is cached in a local JSON file on the user's workstation as part of the app's parts catalog. No data is transmitted to or stored on any external servers or third-party systems.

**Where is data stored?**
> On the local machine only, in the application's working directory. The machine is our own company's workstation located in the United States.

**Do you share QuickBooks data with any third parties?**
> No. QuickBooks data never leaves the local machine and is never transmitted to any server other than Intuit's own API endpoints.

**For what purposes do you use QuickBooks data?**
> QuickBooks data is used solely to operate the features of this internal application — specifically, to maintain an up-to-date parts catalog and to create project scaffolds in QuickBooks for time tracking. It is not used for any secondary purpose, analytics, advertising, or data resale.

**How long do you retain QuickBooks data?**
> Parts catalog data is retained indefinitely on the local machine as part of the application's operational data. Users can delete the application and all its data at any time. There is no external retention or archival.

**Can a user disconnect your app from their QuickBooks account?**
> Yes. The application has a "Disconnect" function in Settings → QuickBooks that clears all stored OAuth tokens from the local machine and revokes access. After disconnecting, the app cannot access QuickBooks data until the owner re-authorizes.

---

## Section 3 — API Usage

**What QuickBooks data does your app read?**
> - Items: to sync parts catalog data (name, SKU, unit price, active/inactive status)
> - Customers: to look up existing agency records when creating project scaffolds

**What QuickBooks data does your app write?**
> - Customers: we create a Customer record per agency when pushing a project, if one does not already exist
> - Projects (Customers with Job=true): we create one project record per vehicle build for time tracking purposes

**Does your app write to any financial records — invoices, transactions, payments, or journal entries?**
> No. The app never writes to or modifies any financial records in QuickBooks.

**Do you request only the scopes your app needs?**
> Yes. We request only `com.intuit.quickbooks.accounting`, which is the minimum scope required for Item reads and Customer/Project writes.

**Does your app handle API errors?**
> Yes. HTTP errors from the QBO API surface a user-visible error message in the application. The `intuit_tid` value from response headers is captured in the application log for troubleshooting. Errors are never exposed as raw stack traces or logged with sensitive data.

**Can your app store error information in logs that can be shared for troubleshooting?**
> Yes. The application maintains a local log file. Errors are logged with operation names, timestamps, HTTP status codes, and the `intuit_tid` header value. Credentials, tokens, realm IDs, and QuickBooks data values are never written to the log.

---

## Section 4 — Authorization

**How does your app authenticate with QuickBooks?**
> OAuth 2.0 Authorization Code flow. The app owner completes a one-time browser-based authorization. The resulting access token and refresh token are stored encrypted on the local machine. All subsequent API calls use the access token, which is automatically refreshed before expiry.

**How and where do you store OAuth tokens?**
> The refresh token, access token, realm ID, and client secret are stored in the operating system's native credential store — macOS Keychain on Mac, Windows Credential Locker (DPAPI) on Windows — as an encrypted blob via the `msal-extensions` library (the same mechanism that protects our existing Microsoft 365 token cache). These values never touch disk as plaintext. A separate non-sensitive metadata file (`quickbooks_config.json`) stores only the client ID, token expiry timestamps, and connection status — no credential values. Both the OS credential store and the metadata file are restricted to the local machine and are never synced to any external service.

**Do you rotate and save the new refresh token after each token refresh?**
> Yes. Every time the access token is refreshed, the newly issued refresh token is immediately decrypted (old), the new token is re-encrypted, and the configuration file is updated atomically. The previous refresh token is discarded. Failing to do this would invalidate the connection, so this is enforced in code.

**Have you implemented CSRF protection in the OAuth flow?**
> Yes. Before opening the browser for authorization, the application generates a cryptographically random `state` value using `secrets.token_urlsafe(32)` and stores it in memory. When the OAuth callback is received, the returned `state` is compared using a constant-time comparison (`secrets.compare_digest`). Any mismatch is rejected with a 400 error and the authorization flow is aborted.

**Have you tested your app's connect, disconnect, and reconnect flows in a non-production environment?**
> Yes. All three flows have been tested against a sandbox company using Development keys prior to submitting this questionnaire:
> - **Connect**: Full OAuth round-trip — browser authorization, callback capture, token storage, connection status confirmed
> - **Disconnect**: Tokens cleared from local storage, connection status set to disconnected, API calls rejected
> - **Reconnect**: Full OAuth flow repeated from disconnected state, new tokens stored, connection restored

*(Complete this testing before submitting. This is the most common rejection reason.)*

---

## Section 5 — Error Handling

**Does your app handle API errors gracefully?**
> Yes. The application handles HTTP errors from the QBO API and surfaces plain-language error messages to the user. It does not expose raw API responses, error bodies, or stack traces in the UI.

**Does your app capture the `intuit_tid` field from response headers?**
> Yes. The `intuit_tid` value is captured from every QBO API response header and recorded in the local application log alongside the operation name, timestamp, and HTTP status code. This allows Intuit support to trace specific requests if needed.

**Does your app log errors in a way that can be shared for troubleshooting?**
> Yes. Errors are written to a local log file in a structured format. The log contains only operation context (timestamps, status codes, `intuit_tid` values) — never credentials, tokens, realm IDs, or QuickBooks data values.

---

## Section 6 — Legal Compliance

**Has your company ever received complaints, lawsuits, or investigative requests from regulatory authorities or government agencies related to your app or data practices?**
> No.

**Have you worked with legal counsel to understand any regulatory requirements related to your business activities and use of QuickBooks data?**
> Yes. We have reviewed our obligations as an internal business tool and operate in compliance with applicable law. We do not handle external customer data through this application; it is used solely by our own staff.

**Will your app comply with Intuit's Developer Terms of Service and security policies?**
> Yes. We have reviewed and will comply with Intuit's Developer Terms of Service, data usage policies, and security requirements.

**Does your business comply with applicable sanctions and export control laws?**
> Yes.

**Do you use Intuit customer data only for the benefit of the original customer (our own company), not for any secondary purpose?**
> Yes. All QuickBooks data accessed through this app is used exclusively for the operational benefit of our own company. It is not shared, sold, or used for any purpose other than operating this internal tool.

---

## Section 7 — Security

**Does your app comply with Intuit's security policies?**
> Yes. We confirm compliance with Intuit's published security requirements, including OAuth token encryption, HTTPS for all external communications, no logging of credentials or customer data, and CSRF protection in the OAuth flow.

**How does your app secure OAuth tokens at rest?**
> All OAuth credential values (refresh token, access token, realm ID, client secret) are stored exclusively in the operating system's native credential store — macOS Keychain on Mac, Windows Credential Locker (DPAPI) on Windows — as an encrypted blob via the `msal-extensions` library (the same mechanism that protects our existing Microsoft 365 token cache). The OS handles AES encryption and key management natively at the hardware security layer. Plaintext credential values are never written to any file on disk, never logged, and never exposed in the application UI.

**Does your app use HTTPS for all pages and API communications?**
> Yes. All communications with Intuit's API endpoints use HTTPS. The OAuth redirect URI uses HTTPS (hosted relay endpoint). The application's local UI runs on localhost, which is not subject to the external HTTPS requirement, but all external traffic is encrypted.

**Does your app prevent sensitive data from appearing in logs or browser consoles?**
> Yes. The application logger is explicitly configured to exclude credential values, token strings, realm IDs, and raw QuickBooks data. Error logging captures only operation metadata (`intuit_tid`, HTTP status, timestamp).

**Does your app implement CSRF protection?**
> Yes, via the OAuth `state` parameter as described in the Authorization section.

**Does your app expose any third-party access to QuickBooks data?**
> No. QuickBooks data is accessed only by this application, on the local machine, by our own staff.

**Does your app implement proper session and access controls?**
> The application is a single-user desktop application accessed only by authorized internal staff on company-owned machines. There are no external user-facing login credentials or multi-user sessions. Access control is enforced at the operating system level.

**Has your application been assessed for common web vulnerabilities (XSS, CSRF, injection)?**
> Yes. The application's local web server has been reviewed for:
> - **XSS**: QuickBooks data is rendered using `textContent` (not `innerHTML`) in the JavaScript UI, preventing injection of HTML from API responses
> - **CSRF**: OAuth flow uses a cryptographically random `state` parameter
> - **SQL Injection**: Not applicable — the application does not use a SQL database
> - **XML Injection**: Data passed to the Python XML/PPTX generation layer is sanitized before use
> - **HTTP TRACE**: The local server is configured to reject TRACE and other unused HTTP methods with 405

---

## Submission Checklist

Before clicking submit:

- [ ] Phase 1 integration is complete and tested against a sandbox company
- [ ] Connect flow tested: OAuth round-trip works, tokens encrypted on disk
- [ ] Disconnect flow tested: tokens cleared, connection status reflects disconnected
- [ ] Reconnect flow tested: full OAuth flow works from disconnected state
- [ ] AES-256 encryption confirmed on all token fields in `quickbooks_config.json`
- [ ] Key stored in separate file (`quickbooks_key.bin`) from config
- [ ] OAuth callback issues HTTP 302 (not HTML) after saving tokens
- [ ] CSRF state validation confirmed working (tested with mismatched state)
- [ ] Application logs reviewed — no tokens, realm IDs, or QB data visible
- [ ] `Cache-Control: no-store` header on all `/api/quickbooks/*` routes
- [ ] HTTP TRACE rejected by local server
- [ ] Production redirect URI registered in Intuit Developer Dashboard
- [ ] Hosted relay endpoint deployed and tested end-to-end
- [ ] `quickbooks_key.bin` and `quickbooks_config.json` in `.gitignore`
- [ ] Both files confirmed absent from SharePoint mirror logic
