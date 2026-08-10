"""Client for the QuickBooks Online v3 Data API.

Reads (Phase 2 parts sync, Phase 3 customer down-sync) query Items and
Customers from the connected company. Its normal user-approved writes are
**Customer** (Phase 3 up-sync) and a reviewable **Estimate**. It never
touches Invoices, Transactions, Payments, or any other posting financial
record.

Like the OAuth client, it never logs response bodies (which contain item
names, prices, and other company data). Only the request name, HTTP status,
and Intuit's ``intuit_tid`` trace header are logged.
"""

from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

# QBO Data API base differs by environment. Sandbox companies are only
# reachable on the sandbox host; production companies only on the production
# host. Using the wrong one returns 401/AuthenticationFailed.
_BASE_URLS = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}

# Project references on Estimates require minor version 73 or later. Version
# 75 is the current supported QBO Data API baseline.
_MINOR_VERSION = "75"

_HTTP_TIMEOUT = 30  # data queries can be larger than token calls


class QuickBooksApiError(RuntimeError):
    """Raised when a QBO Data API request fails."""


def _fault_summary(response: requests.Response) -> str:
    """Return a short QBO error code/message without exposing response detail.

    Intuit's structured ``Message`` is a generic classification such as
    ``Business Validation Error``. ``Detail`` can contain company/customer or
    item data, so it is deliberately never surfaced or logged.
    """
    try:
        fault = response.json().get("Fault") or {}
        errors = fault.get("Error") or []
    except Exception:  # noqa: BLE001 - an error response may not be JSON
        return ""

    if isinstance(errors, dict):
        error = errors
    elif isinstance(errors, list) and errors and isinstance(errors[0], dict):
        error = errors[0]
    else:
        return ""

    code = str(error.get("code") or "").strip()
    message = " ".join(str(error.get("Message") or "").split())[:180]
    if code and message:
        return f"qb_{code}: {message}"
    if code:
        return f"qb_{code}"
    if message:
        return f"qb_error: {message}"
    return ""


def _http_error(response: requests.Response, intuit_tid: str) -> QuickBooksApiError:
    """Build a safe, actionable exception for a failed QBO HTTP request."""
    parts = [f"http_{response.status_code}"]
    if summary := _fault_summary(response):
        parts.append(summary)
    if intuit_tid:
        parts.append(f"intuit_tid={intuit_tid}")
    return QuickBooksApiError(" ".join(parts))


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
            raise _http_error(resp, tid)
        try:
            return resp.json().get("QueryResponse", {})
        except Exception as exc:  # noqa: BLE001
            raise QuickBooksApiError("unparseable_response") from exc

    def _post(self, entity: str, payload: dict, *, query_params: dict | None = None) -> dict:
        """POST a create/sparse-update to a QBO entity endpoint.

        Returns the parsed JSON envelope (e.g. ``{"Customer": {...}}``). Raises
        ``QuickBooksApiError`` on transport failure or non-200 status. Like
        ``query``, never logs the request or response body.
        """
        url = f"{self._base()}/v3/company/{self._realm_id}/{entity}"
        params = {"minorversion": _MINOR_VERSION, **(query_params or {})}
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
            raise _http_error(resp, tid)
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
            # QBO only returns the fields named in a query. Customer profile
            # data is intentionally broad (contacts, addresses, tax flag,
            # notes), so import every populated Customer field and normalize
            # the safe subset the app stores below.
            stmt = (
                "SELECT * FROM Customer WHERE Active = true "
                f"STARTPOSITION {start} MAXRESULTS {page_size}"
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

    def fetch_preferences(self) -> dict:
        """Return non-sensitive sales-form settings used by the estimate flow."""
        qr = self.query("SELECT * FROM Preferences")
        raw = qr.get("Preferences", {}) or {}
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        sales = raw.get("SalesFormsPrefs") or raw.get("SalesAndCustomersPrefs") or {}
        return {
            "using_price_levels": bool(sales.get("UsingPriceLevels", False)),
            "sales_custom_fields": _sales_form_custom_fields(sales),
        }

    # ── Customer writes (Phase 3 up-sync) ────────────────────────────────────
    #
    # Customer profile writes only; Estimate creation is kept separately below
    # because it is a user-approved, non-posting sales-form action.

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

    def find_top_level_customer_by_display_name(self, display_name: str) -> dict | None:
        """Return a normalized top-level Customer matching ``DisplayName``.

        Customer DisplayName is globally unique, but an old vehicle job may
        have the same text as an agency in a damaged/imported company. The
        estimate flow must never attach to a sub-customer, so filter the raw
        result before returning it.
        """
        name = (display_name or "").strip()
        if not name:
            return None
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        qr = self.query(f"SELECT * FROM Customer WHERE DisplayName = '{safe}'")
        for raw in qr.get("Customer", []) or []:
            normalized = _normalize_customer(raw)
            if not normalized["is_sub"]:
                return normalized
        return None

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

    def fetch_income_accounts(self) -> list[dict]:
        """Return active Income accounts ``[{id, name}]``.

        QBO requires an ``IncomeAccountRef`` on any sellable NonInventory/Service
        Item, so the sandbox-seeding tool needs one to attach.
        """
        qr = self.query(
            "SELECT Id, Name FROM Account WHERE AccountType = 'Income' "
            "AND Active = true MAXRESULTS 100"
        )
        return [
            {"id": str(a.get("Id", "")), "name": (a.get("Name") or "").strip()}
            for a in (qr.get("Account", []) or [])
        ]

    def create_item(self, payload: dict) -> dict:
        """Create an Item. Returns id + name.

        Only the sandbox-seeding tool calls this, and that tool refuses to run
        against a production realm — Item writes are a test-data convenience,
        never part of the normal app flow.
        """
        raw = (self._post("item", payload) or {}).get("Item", {}) or {}
        return {"qb_item_id": str(raw.get("Id", "")), "name": (raw.get("Name") or "").strip()}

    def create_estimate(self, payload: dict) -> dict:
        """Create an Estimate (non-posting draft). Returns id + doc number.

        Estimates do NOT post to the books — that's why they're the right object
        for a reviewable draft. Converting an accepted estimate into an Invoice
        is a separate, explicit action.
        """
        # The app fills the three legacy sales-form String fields exposed by
        # Preferences. Do not opt into the enhanced-custom-fields mode here:
        # that mode expects paid-API ``legacyIDV2`` values, whereas legacy
        # Preferences supplies the positional ids 1–3.
        raw = (self._post("estimate", payload) or {}).get("Estimate", {}) or {}
        return {
            "qb_estimate_id": str(raw.get("Id", "")),
            "doc_number": str(raw.get("DocNumber", "")),
        }


def _sales_form_custom_fields(sales_preferences: object) -> list[dict]:
    """Normalize enabled legacy sales-form custom fields from Preferences.

    QBO identifies these fields by position (``DefinitionId`` 1-3), while the
    customer decides their human-facing names in QuickBooks. Returning names
    with ids lets the estimate service map values by label instead of baking a
    sandbox company's ids into the app.
    """
    if not isinstance(sales_preferences, dict):
        return []
    raw_custom = sales_preferences.get("CustomField") or []

    def nested_entries(value: object):
        """Yield leaf field entries from QBO's nested Preferences structure.

        QBO returns the legacy settings as one or more wrapper objects, each
        with its own ``CustomField`` array: one group for enabled flags and
        another for field labels. A single wrapper is also valid in smaller
        companies, so deliberately handle both shapes.
        """
        if isinstance(value, list):
            for item in value:
                yield from nested_entries(item)
        elif isinstance(value, dict):
            if "Name" in value:
                yield value
            else:
                yield from nested_entries(value.get("CustomField") or [])

    enabled: dict[str, bool] = {}
    labels: dict[str, str] = {}
    for entry in nested_entries(raw_custom):
        match = re.fullmatch(
            r"SalesFormsPrefs\.(UseSalesCustom|SalesCustomName)([1-3])",
            str(entry.get("Name") or ""),
        )
        if not match:
            continue
        kind, position = match.groups()
        if kind == "UseSalesCustom":
            value = entry.get("BooleanValue", entry.get("StringValue", False))
            enabled[position] = value is True or str(value).strip().lower() == "true"
        else:
            label = str(entry.get("StringValue") or "").strip()
            if label:
                labels[position] = label

    return [
        {"definition_id": position, "name": labels[position]}
        for position in sorted(labels)
        if enabled.get(position, False)
    ]


def _build_customer_payload(fields: dict) -> dict:
    """Map VB agency fields to a QBO Customer payload (only supplied fields).

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
    title = (fields.get("contact_title") or "").strip()
    if title:
        payload["Title"] = title
    mobile = (fields.get("mobile_phone") or "").strip()
    if mobile:
        payload["Mobile"] = {"FreeFormNumber": mobile}
    fax = (fields.get("fax") or "").strip()
    if fax:
        payload["Fax"] = {"FreeFormNumber": fax}
    website = (fields.get("website") or "").strip()
    if website:
        payload["WebAddr"] = {"URI": website}
    notes = (fields.get("notes") or "").strip()
    if notes:
        payload["Notes"] = notes
    if fields.get("taxable") is not None:
        payload["Taxable"] = bool(fields["taxable"])

    bill_addr = _build_address_payload(fields, "bill")
    if bill_addr:
        payload["BillAddr"] = bill_addr
    ship_addr = _build_address_payload(fields, "ship")
    if ship_addr:
        payload["ShipAddr"] = ship_addr
    return payload


def _build_address_payload(fields: dict, kind: str) -> dict:
    """Convert flattened app address fields into QBO's address object."""
    mapping = {
        "line1": "Line1",
        "line2": "Line2",
        "line3": "Line3",
        "city": "City",
        "state": "CountrySubDivisionCode",
        "postal_code": "PostalCode",
        "country": "Country",
    }
    payload: dict = {}
    for suffix, qbo_field in mapping.items():
        field = f"{kind}_address_{suffix}" if suffix.startswith("line") else f"{kind}_{suffix}"
        value = (fields.get(field) or "").strip()
        if value:
            payload[qbo_field] = value
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
    """Reduce a raw QBO Customer to the app's customer-profile fields."""
    email = ((raw.get("PrimaryEmailAddr") or {}).get("Address") or "").strip()
    phone = ((raw.get("PrimaryPhone") or {}).get("FreeFormNumber") or "").strip()
    mobile = ((raw.get("Mobile") or {}).get("FreeFormNumber") or "").strip()
    fax = ((raw.get("Fax") or {}).get("FreeFormNumber") or "").strip()
    website = ((raw.get("WebAddr") or {}).get("URI") or "").strip()
    contact = " ".join(
        p for p in [(raw.get("GivenName") or "").strip(), (raw.get("FamilyName") or "").strip()] if p
    )
    # Prefer the company name; fall back to the display name.
    name = (raw.get("CompanyName") or raw.get("DisplayName") or "").strip()
    customer = {
        "qb_customer_id": str(raw.get("Id", "")),
        "sync_token": str(raw.get("SyncToken", "")),
        "name": name,
        "contact_name": contact,
        "contact_title": (raw.get("Title") or "").strip(),
        "contact_email": email,
        "contact_phone": phone,
        "mobile_phone": mobile,
        "fax": fax,
        "website": website,
        "notes": (raw.get("Notes") or "").strip(),
        "taxable": raw.get("Taxable") if isinstance(raw.get("Taxable"), bool) else None,
        "is_sub": bool(raw.get("Job")) or ("ParentRef" in raw),
    }
    customer.update(_normalize_address(raw.get("BillAddr"), "bill"))
    customer.update(_normalize_address(raw.get("ShipAddr"), "ship"))
    return customer


def _normalize_address(raw: object, kind: str) -> dict:
    """Flatten a QBO address without retaining unneeded API-only fields."""
    addr = raw if isinstance(raw, dict) else {}
    return {
        f"{kind}_address_line1": (addr.get("Line1") or "").strip(),
        f"{kind}_address_line2": (addr.get("Line2") or "").strip(),
        f"{kind}_address_line3": (addr.get("Line3") or "").strip(),
        f"{kind}_city": (addr.get("City") or "").strip(),
        f"{kind}_state": (addr.get("CountrySubDivisionCode") or "").strip(),
        f"{kind}_postal_code": (addr.get("PostalCode") or "").strip(),
        f"{kind}_country": (addr.get("Country") or "").strip(),
    }
