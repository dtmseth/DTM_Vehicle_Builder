"""Read client for the QuickBooks Online v3 Data API.

Phase 2 (parts sync) uses this to query Items from the connected company.
It is intentionally read-only — no create/update/delete methods live here.

Like the OAuth client, it never logs response bodies (which contain item
names, prices, and other company data). Only the request name, HTTP status,
and Intuit's ``intuit_tid`` trace header are logged.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# QBO Data API base differs by environment. Sandbox companies are only
# reachable on the sandbox host; production companies only on the production
# host. Using the wrong one returns 401/AuthenticationFailed.
_BASE_URLS = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}

# Pinned minor version. Well within Intuit's supported range; bump
# deliberately if a newer field is needed.
_MINOR_VERSION = "70"

_HTTP_TIMEOUT = 30  # data queries can be larger than token calls


class QuickBooksApiError(RuntimeError):
    """Raised when a QBO Data API request fails."""


class QuickBooksApiClient:
    def __init__(self, *, access_token: str, realm_id: str, environment: str = "production") -> None:
        self._access_token = access_token
        self._realm_id = realm_id
        self._environment = environment if environment in _BASE_URLS else "production"

    def _base(self) -> str:
        return _BASE_URLS[self._environment]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    def query(self, statement: str) -> dict:
        """Run a QBO SQL-like query and return the parsed ``QueryResponse``.

        Raises ``QuickBooksApiError`` on transport failure or non-200 status.
        """
        url = f"{self._base()}/v3/company/{self._realm_id}/query"
        params = {"query": statement, "minorversion": _MINOR_VERSION}
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=_HTTP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            raise QuickBooksApiError(f"request_failed: {exc}") from exc

        tid = resp.headers.get("intuit_tid", "")
        logger.info("QB query: status=%s intuit_tid=%s", resp.status_code, tid)
        if resp.status_code != 200:
            # Surface status + trace id only; never the body (company data / detail).
            raise QuickBooksApiError(f"http_{resp.status_code} intuit_tid={tid}")
        try:
            return resp.json().get("QueryResponse", {})
        except Exception as exc:  # noqa: BLE001
            raise QuickBooksApiError("unparseable_response") from exc

    def fetch_active_items(self, *, page_size: int = 1000) -> list[dict]:
        """Return all active Items, following QBO's STARTPOSITION pagination.

        Each returned dict is the normalized subset the sync layer needs —
        never the raw QBO payload — so callers don't accidentally persist or
        log fields we don't intend to store.
        """
        items: list[dict] = []
        start = 1
        while True:
            stmt = (
                "SELECT Id, Name, Sku, Description, UnitPrice, Type, Active "
                f"FROM Item WHERE Active = true STARTPOSITION {start} MAXRESULTS {page_size}"
            )
            qr = self.query(stmt)
            batch = qr.get("Item", []) or []
            for raw in batch:
                items.append(_normalize_item(raw))
            if len(batch) < page_size:
                break
            start += page_size
        return items


def _normalize_item(raw: dict) -> dict:
    """Reduce a raw QBO Item to the fields the sync layer stores."""
    price = raw.get("UnitPrice")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "qb_item_id": str(raw.get("Id", "")),
        "name": (raw.get("Name") or "").strip(),
        "sku": (raw.get("Sku") or "").strip(),
        "description": (raw.get("Description") or "").strip(),
        "unit_price": price,
        "type": (raw.get("Type") or "").strip(),
    }
