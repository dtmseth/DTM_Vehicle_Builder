"""Minimal client for the Shopmonkey v3 REST API."""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.shopmonkey.cloud/v3"
_HTTP_TIMEOUT = 30


class ShopmonkeyApiError(RuntimeError):
    """A provider failure safe to surface without response/customer data."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 0,
        request_id: str = "",
        retry_after: int = 0,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after


def request_json_document(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = _HTTP_TIMEOUT,
) -> tuple[int, dict]:
    """Perform bounded hosted-provider I/O behind the adapter boundary."""
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            data=data,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - transport text may contain request details
        raise ShopmonkeyApiError("request_failed") from None
    try:
        document = response.json()
    except Exception:  # noqa: BLE001 - callers map malformed provider responses safely
        document = {}
    return response.status_code, document if isinstance(document, dict) else {}


class ShopmonkeyApiClient:
    def __init__(self, *, api_key: str) -> None:
        self._api_key = str(api_key or "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        headers = self._headers()
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = requests.request(
                method,
                f"{_BASE_URL}{path}",
                headers=headers,
                params=params,
                json=body,
                timeout=_HTTP_TIMEOUT,
            )
        except Exception:  # noqa: BLE001 - transport text may contain request details
            raise ShopmonkeyApiError("request_failed") from None

        request_id = response.headers.get("x-request-id", "")
        logger.info(
            "Shopmonkey API: operation=%s status=%s request_id=%s",
            operation,
            response.status_code,
            request_id,
        )
        if not 200 <= response.status_code < 300:
            retry_after = 0
            if response.status_code == 429:
                try:
                    retry_after = max(0, int(response.headers.get("Retry-After", "0")))
                except (TypeError, ValueError):
                    retry_after = 0
            raise ShopmonkeyApiError(
                f"http_{response.status_code}",
                status_code=response.status_code,
                request_id=request_id,
                retry_after=retry_after,
            )
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - provider can return malformed JSON
            raise ShopmonkeyApiError(
                "unparseable_response", request_id=request_id
            ) from None
        if not isinstance(payload, dict):
            raise ShopmonkeyApiError("unparseable_response", request_id=request_id)
        if payload.get("success") is False:
            provider_code = str(payload.get("code") or "provider_error")[:80]
            raise ShopmonkeyApiError(provider_code, request_id=request_id)
        return payload

    def check_status(self) -> None:
        self._request("GET", "/auth/api_key/status", operation="api_key_status")

    def _list_records(
        self,
        path: str,
        *,
        operation: str,
        page_size: int = 100,
        max_records: int = 5000,
    ) -> list[dict]:
        """Return one bounded, paginated Shopmonkey collection."""
        records: list[dict] = []
        skip = 0
        while len(records) < max_records:
            limit = min(page_size, max_records - len(records))
            payload = self._request(
                "GET",
                path,
                operation=operation,
                params={"limit": limit, "skip": skip},
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                raise ShopmonkeyApiError("unparseable_response")
            records.extend(
                row for row in batch if isinstance(row, dict) and not row.get("deleted")
            )
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if ("hasMore" in meta and not meta.get("hasMore")) or (
                "hasMore" not in meta and len(batch) < limit
            ):
                break
            if not batch:
                break
            skip += len(batch)
        return records[:max_records]

    def list_labels(self) -> list[dict]:
        return self._list_records("/label", operation="label_list")

    def list_brands(self) -> list[dict]:
        return self._list_records("/brand", operation="brand_list")

    def search_customers(self, *, page_size: int = 100, max_records: int = 5000) -> list[dict]:
        """Return active customers with bounded skip/limit pagination."""
        customers: list[dict] = []
        skip = 0
        while len(customers) < max_records:
            limit = min(page_size, max_records - len(customers))
            payload = self._request(
                "POST",
                "/customer/search",
                operation="customer_search",
                body={"limit": limit, "skip": skip},
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                raise ShopmonkeyApiError("unparseable_response")
            customers.extend(row for row in batch if isinstance(row, dict) and not row.get("deleted"))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if ("hasMore" in meta and not meta.get("hasMore")) or (
                "hasMore" not in meta and len(batch) < limit
            ):
                break
            if not batch:
                break
            skip += len(batch)
        return customers[:max_records]

    def fetch_customer_vehicles(
        self, customer_id: str, *, page_size: int = 100, max_records: int = 2000
    ) -> list[dict]:
        vehicles: list[dict] = []
        skip = 0
        safe_id = quote(str(customer_id), safe="")
        while len(vehicles) < max_records:
            limit = min(page_size, max_records - len(vehicles))
            payload = self._request(
                "GET",
                f"/customer/{safe_id}/vehicle",
                operation="customer_vehicles",
                params={"limit": limit, "skip": skip},
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                raise ShopmonkeyApiError("unparseable_response")
            vehicles.extend(row for row in batch if isinstance(row, dict) and not row.get("deleted"))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if ("hasMore" in meta and not meta.get("hasMore")) or (
                "hasMore" not in meta and len(batch) < limit
            ):
                break
            if not batch:
                break
            skip += len(batch)
        return vehicles[:max_records]

    def _search_inventory(
        self,
        path: str,
        *,
        operation: str,
        where: dict | None = None,
        page_size: int = 100,
        max_records: int = 20000,
    ) -> list[dict]:
        records: list[dict] = []
        skip = 0
        while len(records) < max_records:
            limit = min(page_size, max_records - len(records))
            body = {"limit": limit, "skip": skip}
            if where:
                body["where"] = where
            payload = self._request(
                "POST",
                path,
                operation=operation,
                body=body,
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                raise ShopmonkeyApiError("unparseable_response")
            records.extend(
                row for row in batch if isinstance(row, dict) and not row.get("deleted")
            )
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if ("hasMore" in meta and not meta.get("hasMore")) or (
                "hasMore" not in meta and len(batch) < limit
            ):
                break
            if not batch:
                break
            skip += len(batch)
        return records[:max_records]

    def search_inventory_parts(self, *, category_id: str = "") -> list[dict]:
        clean_category_id = str(category_id or "").strip()
        return self._search_inventory(
            "/inventory_part/search",
            operation="inventory_part_search",
            where={"categoryId": clean_category_id} if clean_category_id else None,
        )

    def create_inventory_part(self, *, name: str, category_id: str = "") -> dict:
        """Create one inventory part and return Shopmonkey's stored record."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        body = {"name": clean_name}
        if clean_category_id := str(category_id or "").strip():
            body["categoryId"] = clean_category_id
        payload = self._request(
            "POST",
            "/inventory_part",
            operation="inventory_part_create",
            body=body,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopmonkeyApiError("unparseable_response")
        return data
    def search_inventory_tires(self) -> list[dict]:
        return self._search_inventory(
            "/inventory_tire/search", operation="inventory_tire_search"
        )

    def soft_delete_inventory_part(self, inventory_part_id: str, *, reason: str = "") -> None:
        """Archive one inventory part through Shopmonkey's documented soft-delete API."""
        safe_id = quote(str(inventory_part_id), safe="")
        if not safe_id:
            raise ValueError("inventory_part_id is required")
        self._request(
            "PATCH",
            f"/inventory_part/{safe_id}/delete",
            operation="inventory_part_soft_delete",
            body={"reason": str(reason or "")},
        )

    def soft_delete_inventory_tire(self, inventory_tire_id: str, *, reason: str = "") -> None:
        """Archive one inventory tire through Shopmonkey's documented soft-delete API."""
        safe_id = quote(str(inventory_tire_id), safe="")
        if not safe_id:
            raise ValueError("inventory_tire_id is required")
        self._request(
            "PATCH",
            f"/inventory_tire/{safe_id}/delete",
            operation="inventory_tire_soft_delete",
            body={"reason": str(reason or "")},
        )

    def list_inventory_categories(
        self, *, page_size: int = 100, max_records: int = 5000
    ) -> list[dict]:
        records: list[dict] = []
        skip = 0
        while len(records) < max_records:
            limit = min(page_size, max_records - len(records))
            payload = self._request(
                "GET",
                "/inventory_category",
                operation="inventory_category_list",
                params={"limit": limit, "skip": skip},
            )
            batch = payload.get("data") or []
            if not isinstance(batch, list):
                raise ShopmonkeyApiError("unparseable_response")
            records.extend(
                row for row in batch if isinstance(row, dict) and not row.get("deleted")
            )
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if ("hasMore" in meta and not meta.get("hasMore")) or (
                "hasMore" not in meta and len(batch) < limit
            ):
                break
            if not batch:
                break
            skip += len(batch)
        return records[:max_records]

    def create_inventory_category(self, name: str, *, parent_id: str = "") -> dict:
        """Create one inventory category and return Shopmonkey's stored record."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        body = {"name": clean_name}
        if clean_parent_id := str(parent_id or "").strip():
            body["parentId"] = clean_parent_id
        payload = self._request(
            "POST",
            "/inventory_category",
            operation="inventory_category_create",
            body=body,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopmonkeyApiError("unparseable_response")
        return data
