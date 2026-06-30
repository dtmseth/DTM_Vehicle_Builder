"""QuickBooks Online integration adapters.

Two thin, side-effecting adapters used by ``services/quickbooks_service.py``:

- ``credential_store`` — OS-keychain-backed storage for OAuth secrets
  (same msal-extensions encrypted persistence the M365 token cache uses).
- ``oauth_client`` — stateless HTTP client for Intuit's OAuth 2.0 endpoints
  (discovery document, code exchange, refresh, revoke).

See ``docs/QUICKBOOKS.md`` and
``docs/EXTERNAL_CONNECTION_SECURITY.md``.
"""
