"""Client for the QuickBooks Online v3 Data API.

Reads (Phase 2 parts sync, Phase 3 customer down-sync) query Items and
Customers from the connected company. The only writes this client performs
are to the **Customer** entity (Phase 3 up-sync) — the single write target
the integration's security boundary authorizes. It never touches Invoices,
Transactions, Payments, or any financial record.

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

    def _post(self, entity: str, payload: dict) -> dict:
        """POST a create/sparse-update to a QBO entity endpoint.

        Returns the parsed JSON envelope (e.g. ``{"Customer": {...}}``). Raises
        ``QuickBooksApiError`` on transport failure or non-200 status. Like
        ``query``, never logs the request or response body.
        """
        url = f"{self._base()}/v3/company/{self._realm_id}/{entity}"
        params = {"minorversion": _MINOR_VERSION}
        headers = {**self._headers(), "Content-Type": "application/json"}
        try:
            resp = requests.post(
                url, headers=headers, params=params, json=payload, timeout=_HTTP_TIMEOUT
            )
        except Exception as exc:  # noqa: BLE001
            raise QuickBooksApiError(f"request_failed: {exc}") from exc

        tid = resp.headers.get("intuit_tid", "")
        logger.info("QB %s write: status=%s intuit_tid=%s", entity, resp.status_code, tid)
        if resp.status_code != 200:
            raise QuickBooksApiError(f"http_{resp.status_code} intuit_tid={tid}")
        try:
            return resp.json()
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

    def fetch_active_customers(self, *, page_size: int = 1000, top_level_only: bool = True) -> list[dict]:
        """Return active Customers (top-level only by default).

        Sub-customers / jobs (``Job=true`` or with a ``ParentRef``) are excluded
        when ``top_level_only`` — those map to vehicle-level records, not
        agencies. Normalized to the subset the agency importer needs.
        """
        customers: list[dict] = []
        start = 1
        while True:
            stmt = (
                "SELECT Id, DisplayName, CompanyName, GivenName, FamilyName, "
                "PrimaryEmailAddr, PrimaryPhone, Job, Active "
                f"FROM Customer WHERE Active = true STARTPOSITION {start} MAXRESULTS {page_size}"
            )
            qr = self.query(stmt)
            batch = qr.get("Customer", []) or []
            for raw in batch:
                norm = _normalize_customer(raw)
                if top_level_only and norm["is_sub"]:
                    continue
                customers.append(norm)
            if len(batch) < page_size:
                break
            start += page_size
        return customers

    # ── Customer writes (Phase 3 up-sync) ────────────────────────────────────
    #
    # The only entity this client writes. Customer (and its Job sub-customers)
    # is the integration's sole authorized write target — never financial data.

    def read_customer(self, customer_id: str) -> dict | None:
        """Fetch a single Customer (raw QBO shape, including ``SyncToken``).

        Returns ``None`` if the Id no longer exists in the company (e.g. the
        customer was deleted in QuickBooks). The raw payload is needed because
        a sparse update must echo the current ``SyncToken``.
        """
        cid = str(customer_id).strip()
        if not cid:
            return None
        qr = self.query(f"SELECT * FROM Customer WHERE Id = '{cid}'")
        batch = qr.get("Customer", []) or []
        return batch[0] if batch else None

    def create_customer(self, fields: dict) -> dict:
        """Create a Customer from VB agency ``fields``. Returns id + sync token."""
        envelope = self._post("customer", _build_customer_payload(fields))
        return _customer_result(envelope)

    def update_customer(self, customer_id: str, sync_token: str, fields: dict) -> dict:
        """Sparse-update an existing Customer's contact fields. Returns id + token."""
        payload = {
            "Id": str(customer_id),
            "SyncToken": str(sync_token),
            "sparse": True,
            **_build_customer_payload(fields),
        }
        envelope = self._post("customer", payload)
        return _customer_result(envelope)

    def find_customer_by_display_name(self, display_name: str) -> str:
        """Return the Id of a Customer with this exact DisplayName, or ''.

        DisplayName is globally unique in QBO, so this is the idempotency probe
        for sub-customer (job) creation: if a job was created on a prior run but
        its Id was never written back, we reuse it instead of erroring on a
        duplicate-name create.
        """
        name = (display_name or "").strip()
        if not name:
            return ""
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        qr = self.query(f"SELECT Id FROM Customer WHERE DisplayName = '{safe}'")
        batch = qr.get("Customer", []) or []
        return str(batch[0].get("Id", "")) if batch else ""

    def create_job(self, parent_customer_id: str, display_name: str) -> dict:
        """Create a sub-customer (job) under a parent Customer. Returns id + token.

        A QBO "job" is a Customer with ``Job=true`` and a ``ParentRef``. This is
        the only API path to a per-vehicle "project" container — QBO displays it
        nested under the parent and it can be batch-converted to a Project in the
        QBO UI. ``Customer.IsProject`` itself is read-only via the API.
        """
        payload = {
            "DisplayName": display_name,
            "Job": True,
            "ParentRef": {"value": str(parent_customer_id)},
        }
        return _customer_result(self._post("customer", payload))

    def create_estimate(self, payload: dict) -> dict:
        """Create an Estimate (non-posting draft). Returns id + doc number.

        Estimates do NOT post to the books — that's why they're the right object
        for a reviewable draft. Converting an accepted estimate into an Invoice
        is a separate, explicit action.
        """
        raw = (self._post("estimate", payload) or {}).get("Estimate", {}) or {}
        return {
            "qb_estimate_id": str(raw.get("Id", "")),
            "doc_number": str(raw.get("DocNumber", "")),
        }


def _build_customer_payload(fields: dict) -> dict:
    """Map VB agency fields to a QBO Customer payload (only non-empty fields).

    ``contact_name`` is split on the first space into Given/Family so it
    round-trips with ``_normalize_customer`` on the way back down.
    """
    payload: dict = {}
    name = (fields.get("name") or "").strip()
    if name:
        # DisplayName must be unique in QBO; CompanyName carries the org name.
        payload["DisplayName"] = name
        payload["CompanyName"] = name
    email = (fields.get("contact_email") or "").strip()
    if email:
        payload["PrimaryEmailAddr"] = {"Address": email}
    phone = (fields.get("contact_phone") or "").strip()
    if phone:
        payload["PrimaryPhone"] = {"FreeFormNumber": phone}
    contact = (fields.get("contact_name") or "").strip()
    if contact:
        first, _, last = contact.partition(" ")
        payload["GivenName"] = first
        if last:
            payload["FamilyName"] = last
    return payload


def _customer_result(envelope: dict) -> dict:
    raw = (envelope or {}).get("Customer", {}) or {}
    return {
        "qb_customer_id": str(raw.get("Id", "")),
        "sync_token": str(raw.get("SyncToken", "")),
    }


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


def _normalize_customer(raw: dict) -> dict:
    """Reduce a raw QBO Customer to the fields the agency importer stores."""
    email = ((raw.get("PrimaryEmailAddr") or {}).get("Address") or "").strip()
    phone = ((raw.get("PrimaryPhone") or {}).get("FreeFormNumber") or "").strip()
    contact = " ".join(
        p for p in [(raw.get("GivenName") or "").strip(), (raw.get("FamilyName") or "").strip()] if p
    )
    # Prefer the company name; fall back to the display name.
    name = (raw.get("CompanyName") or raw.get("DisplayName") or "").strip()
    return {
        "qb_customer_id": str(raw.get("Id", "")),
        "name": name,
        "contact_name": contact,
        "contact_email": email,
        "contact_phone": phone,
        "is_sub": bool(raw.get("Job")) or ("ParentRef" in raw),
    }
