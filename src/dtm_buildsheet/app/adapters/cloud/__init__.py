"""Cloud adapter implementations: M365 + SharePoint + Graph API.

These are the first concrete adapters behind the interfaces defined in
`app/adapters/interfaces.py`. They are imported only when the build wires
them in (see `app/adapters/wiring.py`), so the package can still run with
local-only adapters when cloud is disabled.
"""
