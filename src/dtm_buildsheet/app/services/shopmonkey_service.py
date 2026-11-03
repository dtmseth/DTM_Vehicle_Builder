"""Secure Shopmonkey connection, guarded catalog writes, and cleanup reporting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from ...paths import AppPaths
from ..adapters.shopmonkey.api_client import (
    ShopmonkeyApiClient,
    ShopmonkeyApiError,
    request_json_document,
)
from ..adapters.shopmonkey.credential_store import ShopmonkeyCredentialStore
from . import agency_service

_CUSTOMER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PRICING_ADMIN_URL = (
    "https://dtmvehiclebuilder.netlify.app/.netlify/functions/shopmonkey-pricing-admin"
)
_PRICING_HEALTH_URL = (
    "https://dtmvehiclebuilder.netlify.app/.netlify/functions/shopmonkey-health"
)
_PRICING_TIMEOUT_SECONDS = 20

ESTIMATE_LINE_BREAK_CATEGORY = "Estimate Line Breaks (Page, Heading, etc.)"
ESTIMATE_LINE_BREAK_HEADINGS = (
    "Front Configuration",
    "Side Configuration",
    "Rear Configuration",
    "Roof Configuration",
    "Cabin Configuration",
    "Technology",
    "Services",
)
_LINE_BREAK_RULE = "-" * 35


def _store() -> ShopmonkeyCredentialStore:
    return ShopmonkeyCredentialStore()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> dict:
    saved = _store().load()
    configured = bool(str(saved.get("api_key") or "").strip())
    return {
        "ok": True,
        "configured": configured,
        "connected": configured,
        "verified_at": str(saved.get("verified_at") or ""),
        "read_only": False,
        "writable": True,
    }

def _safe_error(exc: ShopmonkeyApiError) -> dict:
    if exc.status_code == 401:
        detail = "Shopmonkey did not accept this API key."
        error = "invalid_api_key"
    elif exc.status_code == 403:
        detail = "This Shopmonkey key does not have permission for that data."
        error = "permission_denied"
    elif exc.status_code == 429:
        wait = f" Try again in about {exc.retry_after} seconds." if exc.retry_after else " Try again shortly."
        detail = "Shopmonkey temporarily rate-limited the request." + wait
        error = "rate_limited"
    else:
        detail = "The app could not complete the Shopmonkey request."
        error = "shopmonkey_unavailable"
    payload = {"ok": False, "error": error, "detail": detail}
    if exc.request_id:
        payload["request_id"] = exc.request_id
    if exc.retry_after:
        payload["retry_after"] = exc.retry_after
    return payload


def connect(api_key: str) -> dict:
    key = str(api_key or "").strip()
    if not key:
        return {"ok": False, "error": "api_key_required", "detail": "Paste a Shopmonkey API key."}
    try:
        ShopmonkeyApiClient(api_key=key).check_status()
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)
    verified_at = _utc_now()
    _store().save({"api_key": key, "verified_at": verified_at})
    return {
        "ok": True,
        "configured": True,
        "connected": True,
        "verified_at": verified_at,
        "read_only": False,
        "writable": True,
    }


def test_connection() -> dict:
    saved = _store().load()
    key = str(saved.get("api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "not_configured", "detail": "Connect Shopmonkey first."}
    try:
        ShopmonkeyApiClient(api_key=key).check_status()
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)
    verified_at = _utc_now()
    _store().save({**saved, "verified_at": verified_at})
    return {
        "ok": True,
        "configured": True,
        "connected": True,
        "verified_at": verified_at,
        "read_only": False,
        "writable": True,
    }


def disconnect() -> dict:
    _store().clear()
    return {
        "ok": True,
        "configured": False,
        "connected": False,
        "verified_at": "",
        "read_only": False,
        "writable": True,
    }


def _client() -> ShopmonkeyApiClient | None:
    key = str(_store().load().get("api_key") or "").strip()
    return ShopmonkeyApiClient(api_key=key) if key else None


def _pricing_management_request(method: str, payload: dict | None = None) -> tuple[int, dict]:
    key = str(_store().load().get("api_key") or "").strip()
    if not key:
        return 401, {
            "ok": False,
            "error": "not_configured",
            "detail": "Connect Shopmonkey on this computer before editing hosted pricing.",
        }
    body = (
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if payload is not None
        else b""
    )
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    body_digest = hashlib.sha256(body).hexdigest()
    signature = hmac.new(
        key.encode("utf-8"),
        f"{timestamp}.{nonce}.{method.upper()}.{body_digest}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    headers = {
        "Accept": "application/json",
        "X-DTM-Timestamp": timestamp,
        "X-DTM-Nonce": nonce,
        "X-DTM-Signature": base64.b64encode(signature).decode("ascii"),
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        status_code, document = request_json_document(
            method.upper(),
            _PRICING_ADMIN_URL,
            headers=headers,
            data=body or None,
            timeout=_PRICING_TIMEOUT_SECONDS,
        )
    except ShopmonkeyApiError:
        return 503, {
            "ok": False,
            "error": "pricing_host_unavailable",
            "detail": "The hosted pricing service could not be reached.",
        }
    if status_code == 401:
        return 401, {
            "ok": False,
            "error": "pricing_auth_mismatch",
            "detail": "The Builder and hosted pricing service do not have the same Shopmonkey API key.",
        }
    if status_code == 409:
        return 409, {
            "ok": False,
            "error": "pricing_config_conflict",
            "detail": "Pricing settings changed elsewhere. Reload them before saving.",
            "config": document.get("config") if isinstance(document.get("config"), dict) else {},
        }
    if not 200 <= status_code < 300:
        return status_code, {
            "ok": False,
            "error": str(document.get("error") or "pricing_host_unavailable"),
            "detail": "The hosted pricing service rejected the settings.",
            "errors": document.get("errors") if isinstance(document.get("errors"), list) else [],
        }
    return status_code, document


def _hosted_pricing_health() -> dict:
    try:
        _status_code, document = request_json_document(
            "GET",
            _PRICING_HEALTH_URL,
            timeout=_PRICING_TIMEOUT_SECONDS,
        )
    except ShopmonkeyApiError:
        return {"ok": False, "status": "health_unavailable"}
    return document


def get_pricing_settings() -> dict:
    _status, result = _pricing_management_request("GET")
    if result.get("ok"):
        result["hosted_health"] = _hosted_pricing_health()
    return result


def _pricing_references(client: ShopmonkeyApiClient) -> dict:
    def choices(rows: list[dict], *, entity: str) -> list[dict]:
        unique: dict[str, dict] = {}
        for row in rows:
            row_id = _clean(row.get("id"))
            name = _clean(row.get("name"))
            if not row_id or not name or _clean(row.get("entity")).lower() != entity.lower():
                continue
            choice = {"id": row_id, "name": name}
            if color := _clean(row.get("color")).lower():
                choice["color"] = color
            unique.setdefault(_name_key(name), choice)
        return sorted(unique.values(), key=lambda row: row["name"].casefold())

    return {
        "customer_labels": choices(client.list_labels(), entity="Customer"),
        "brands": choices(client.list_brands(), entity="Part"),
    }


def pricing_reference_data() -> dict:
    client = _client()
    if client is None:
        return {
            "ok": False,
            "error": "not_configured",
            "detail": "Connect Shopmonkey before loading labels and brands.",
        }
    try:
        return {"ok": True, **_pricing_references(client)}
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)


def _canonicalize_pricing_references(config: dict) -> tuple[dict, list[str]]:
    client = _client()
    if client is None:
        return config, ["Connect Shopmonkey before saving pricing settings."]
    references = _pricing_references(client)
    labels = {row["id"]: row["name"] for row in references["customer_labels"]}
    brands = {row["id"]: row["name"] for row in references["brands"]}
    candidate = json.loads(json.dumps(config))
    errors: list[str] = []
    candidate["schema_version"] = 2
    for index, row in enumerate(candidate.get("customer_types") or []):
        if not isinstance(row, dict):
            continue
        reference_id = _clean(row.get("label_id"))
        if reference_id not in labels:
            if row.get("enabled") is not False:
                errors.append(
                    f"Customer type {index + 1} must use an existing Shopmonkey Customer label."
                )
            row["label_id"] = ""
            continue
        row["label_id"] = reference_id
        row["label"] = labels[reference_id]
    for index, row in enumerate(candidate.get("rules") or []):
        if not isinstance(row, dict):
            continue
        reference_id = _clean(row.get("brand_id"))
        if reference_id not in brands:
            if row.get("enabled") is not False:
                errors.append(
                    f"Price rule {index + 1} must use an existing Shopmonkey Part brand."
                )
            row["brand_id"] = ""
            continue
        row["brand_id"] = reference_id
        row["brand"] = brands[reference_id]
    return candidate, errors


def save_pricing_settings(config: object, expected_revision: object) -> dict:
    if not isinstance(config, dict):
        return {
            "ok": False,
            "error": "pricing_config_invalid",
            "detail": "Pricing settings must be a JSON object.",
        }
    try:
        candidate, errors = _canonicalize_pricing_references(config)
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)
    if errors:
        return {
            "ok": False,
            "error": "pricing_reference_invalid",
            "detail": "Choose existing Shopmonkey labels and brands.",
            "errors": errors,
        }
    _status, result = _pricing_management_request("PUT", {
        "config": candidate,
        "expected_revision": str(expected_revision or ""),
    })
    return result


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _name_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _phone_key(value: object) -> str:
    return re.sub(r"\D", "", _clean(value))


def _primary(rows: object, field: str) -> str:
    if not isinstance(rows, list):
        return ""
    values = [row for row in rows if isinstance(row, dict) and _clean(row.get(field))]
    if not values:
        return ""
    preferred = next((row for row in values if row.get("primary")), values[0])
    return _clean(preferred.get(field))


def _customer_name(raw: dict) -> str:
    company = _clean(raw.get("companyName"))
    if company:
        return company
    person = _clean(f"{_clean(raw.get('firstName'))} {_clean(raw.get('lastName'))}")
    return person or _clean(raw.get("coalescedFirstNameOrCompanyName")) or "Unnamed customer"


def _normalize_customer(raw: dict) -> dict:
    name = _customer_name(raw)
    email = _primary(raw.get("emails"), "email")
    phone = _primary(raw.get("phoneNumbers"), "number")
    address = ", ".join(filter(None, [
        _clean(raw.get("address1")),
        _clean(raw.get("address2")),
        _clean(raw.get("city")),
        _clean(raw.get("state")),
        _clean(raw.get("postalCode")),
    ]))
    return {
        "shopmonkey_customer_id": _clean(raw.get("id")),
        "external_id": _clean(raw.get("externalId")),
        "name": name,
        "customer_type": _clean(raw.get("customerType")) or "Customer",
        "contact_name": _clean(f"{_clean(raw.get('firstName'))} {_clean(raw.get('lastName'))}"),
        "email": email,
        "phone": phone,
        "address": address,
        "address1": _clean(raw.get("address1")),
        "city": _clean(raw.get("city")),
        "state": _clean(raw.get("state")),
        "postal_code": _clean(raw.get("postalCode")),
        "country": _clean(raw.get("country")),
        "tax_exempt": bool(raw.get("taxExempt")),
        "gst_exempt": bool(raw.get("gstExempt")),
        "hst_exempt": bool(raw.get("hstExempt")),
        "pst_exempt": bool(raw.get("pstExempt")),
        "vehicle_count": int(raw.get("vehicleCount") or 0),
        "imported": bool(raw.get("imported")),
        "issues": [],
    }


def cleanup_report(paths: AppPaths) -> dict:
    client = _client()
    if client is None:
        return {"ok": False, "error": "not_configured", "detail": "Connect Shopmonkey first."}
    try:
        records = [_normalize_customer(raw) for raw in client.search_customers()]
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)

    local_by_name = defaultdict(list)
    for agency in agency_service.load_agencies(paths):
        local_by_name[_name_key(agency.name)].append(agency)

    names: dict[str, list[dict]] = defaultdict(list)
    emails: dict[str, list[dict]] = defaultdict(list)
    phones: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        names[_name_key(record["name"])].append(record)
        if record["email"]:
            emails[record["email"].lower()].append(record)
        if len(_phone_key(record["phone"])) >= 7:
            phones[_phone_key(record["phone"])].append(record)

    duplicate_groups = 0
    for groups, label in ((names, "name"), (emails, "email"), (phones, "phone")):
        for key, members in groups.items():
            if key and len(members) > 1:
                duplicate_groups += 1
                for record in members:
                    record["issues"].append(f"Possible duplicate {label} ({len(members)} records)")

    tax_mismatches = 0
    missing_contacts = 0
    for record in records:
        if record["name"] == "Unnamed customer":
            record["issues"].append("Missing customer or company name")
        if not record["email"]:
            record["issues"].append("Missing email")
        if not record["phone"]:
            record["issues"].append("Missing phone")
        if not record["email"] and not record["phone"]:
            missing_contacts += 1
        missing_address = [
            label for label, value in (
                ("street", record["address1"]),
                ("city", record["city"]),
                ("state", record["state"]),
                ("postal code", record["postal_code"]),
            ) if not value
        ]
        if missing_address:
            record["issues"].append("Missing address: " + ", ".join(missing_address))

        local_matches = local_by_name.get(_name_key(record["name"]), [])
        if len(local_matches) == 1:
            local = local_matches[0]
            record["dtm_agency"] = {"agency_id": local.agency_id, "name": local.name}
            if record["tax_exempt"] != (not local.taxable):
                tax_mismatches += 1
                record["issues"].append("Tax status differs from DTM agency")
        elif len(local_matches) > 1:
            record["issues"].append("Multiple DTM agencies have this name")
        else:
            record["dtm_agency"] = None

    records.sort(key=lambda row: (-len(row["issues"]), row["name"].lower()))
    return {
        "ok": True,
        "read_only": True,
        "generated_at": _utc_now(),
        "summary": {
            "total": len(records),
            "fleets": sum(1 for row in records if row["customer_type"].lower() == "fleet"),
            "customers": sum(1 for row in records if row["customer_type"].lower() != "fleet"),
            "records_with_issues": sum(1 for row in records if row["issues"]),
            "duplicate_groups": duplicate_groups,
            "tax_mismatches": tax_mismatches,
            "missing_all_contact": missing_contacts,
        },
        "customers": records,
    }


def customer_vehicles(customer_id: str) -> dict:
    customer_id = str(customer_id or "").strip()
    if not _CUSTOMER_ID_RE.fullmatch(customer_id):
        return {"ok": False, "error": "invalid_customer_id", "detail": "Invalid Shopmonkey customer ID."}
    client = _client()
    if client is None:
        return {"ok": False, "error": "not_configured", "detail": "Connect Shopmonkey first."}
    try:
        raw_vehicles = client.fetch_customer_vehicles(customer_id)
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)

    vehicles = []
    for raw in raw_vehicles:
        year = _clean(raw.get("year"))
        make = _clean(raw.get("make"))
        model = _clean(raw.get("model"))
        unit = _clean(raw.get("unit"))
        vin = _clean(raw.get("vin"))
        name = _clean(raw.get("name")) or _clean(f"{year} {make} {model}") or unit or vin or "Unnamed vehicle"
        issues = []
        if not unit:
            issues.append("Missing unit number")
        if not vin:
            issues.append("Missing VIN")
        if not (year and make and model):
            issues.append("Incomplete year/make/model")
        if int(raw.get("ownerCount") or 0) < 1:
            issues.append("No customer owner link")
        if not raw.get("customPhoto"):
            issues.append("No custom photo")
        vehicles.append({
            "shopmonkey_vehicle_id": _clean(raw.get("id")),
            "external_id": _clean(raw.get("externalId")),
            "name": name,
            "year": year,
            "make": make,
            "model": model,
            "unit": unit,
            "vin": vin,
            "license_plate": _clean(raw.get("licensePlate")),
            "vehicle_serial": _clean(raw.get("serial")),
            "has_custom_photo": bool(raw.get("customPhoto")),
            "issues": issues,
        })
    vehicles.sort(key=lambda row: (-len(row["issues"]), row["name"].lower()))
    return {
        "ok": True,
        "read_only": True,
        "customer_id": customer_id,
        "summary": {
            "total": len(vehicles),
            "with_issues": sum(1 for row in vehicles if row["issues"]),
            "missing_photos": sum(1 for row in vehicles if not row["has_custom_photo"]),
        },
        "vehicles": vehicles,
    }


def _snapshot_dir(paths: AppPaths):
    """Local-only inventory recovery exports; not part of shared settings/work sync."""
    return paths.workspace_dir / "shopmonkey_inventory_snapshots"


def _money_cents(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _nested_name(raw: dict, key: str) -> str:
    value = raw.get(key)
    return _clean(value.get("name")) if isinstance(value, dict) else ""


def _inventory_preview_row(raw: dict, kind: str, categories: dict[str, str]) -> dict:
    category_id = _clean(raw.get("categoryId"))
    tire_model = raw.get("tireModel") if isinstance(raw.get("tireModel"), dict) else {}
    tire_category = tire_model.get("category") if isinstance(tire_model.get("category"), dict) else {}
    if kind == "tire" and not category_id:
        category_id = _clean(tire_category.get("id"))
    brand = _nested_name(raw, "brand")
    if kind == "tire" and not brand:
        tire_brand = tire_model.get("brand") if isinstance(tire_model.get("brand"), dict) else {}
        brand = _clean(tire_brand.get("name"))
    vendor = _nested_name(raw, "vendor")
    if kind == "tire" and not vendor:
        tire_vendor = tire_model.get("vendor") if isinstance(tire_model.get("vendor"), dict) else {}
        vendor = _clean(tire_vendor.get("name"))
    name = _clean(raw.get("name"))
    if kind == "tire" and not name:
        name = _clean(tire_model.get("name")) or _clean(raw.get("size"))
    quantity = _number(raw.get("quantity"))
    retail_cents = _money_cents(raw.get("retailCostCents"))
    return {
        "kind": kind,
        "shopmonkey_id": _clean(raw.get("id")),
        "name": name or "Unnamed inventory item",
        "sku": _clean(raw.get("sku")),
        "part_number": _clean(raw.get("number")),
        "brand": brand,
        "vendor": vendor,
        "category": categories.get(category_id) or _clean(tire_category.get("name")),
        "quantity": quantity,
        "wholesale_cost_cents": _money_cents(raw.get("wholesaleCostCents")),
        "retail_cost_cents": retail_cents,
        "retail_value_cents": int(round(quantity * retail_cents)) if retail_cents is not None else 0,
        "bin_location": _clean(raw.get("binLocation")),
        "has_photo": bool(raw.get("photo") or raw.get("templatePhotoBlobId")),
        "created_date": _clean(raw.get("createdDate")),
        "updated_date": _clean(raw.get("updatedDate")),
    }


def _estimate_line_break_name(heading: str) -> str:
    return f"{_LINE_BREAK_RULE}{heading}{_LINE_BREAK_RULE}"


def ensure_estimate_line_breaks() -> dict:
    """Idempotently create the estimate-divider category and its utility parts."""
    client = _client()
    if client is None:
        return {"ok": False, "error": "not_configured", "detail": "Connect Shopmonkey first."}
    try:
        categories = client.list_inventory_categories()
        category = next(
            (
                row for row in categories
                if _clean(row.get("name")).casefold() == ESTIMATE_LINE_BREAK_CATEGORY.casefold()
            ),
            None,
        )
        category_created = category is None
        if category is None:
            category = client.create_inventory_category(ESTIMATE_LINE_BREAK_CATEGORY)
        category_id = _clean(category.get("id"))
        if not category_id:
            raise ShopmonkeyApiError("unparseable_response")

        existing_parts = client.search_inventory_parts(category_id=category_id)
        existing_names = {
            _clean(row.get("name")).casefold()
            for row in existing_parts
            if _clean(row.get("categoryId")) == category_id
        }
        created = []
        existing = []
        for heading in ESTIMATE_LINE_BREAK_HEADINGS:
            name = _estimate_line_break_name(heading)
            if name.casefold() in existing_names:
                existing.append(name)
                continue
            stored = client.create_inventory_part(name=name, category_id=category_id)
            created.append(_clean(stored.get("name")) or name)
            existing_names.add(name.casefold())
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)

    return {
        "ok": True,
        "read_only": False,
        "category": {
            "id": category_id,
            "name": _clean(category.get("name")) or ESTIMATE_LINE_BREAK_CATEGORY,
            "created": category_created,
        },
        "created": created,
        "existing": existing,
        "total": len(created) + len(existing),
    }


def create_inventory_snapshot(paths: AppPaths) -> dict:
    """Read all active inventory and save a recovery snapshot before reset.

    This deliberately has no delete side effect. The returned reset plan is a
    preview of the exact resource counts that a later, separately confirmed
    operation could soft-delete.
    """
    client = _client()
    if client is None:
        return {"ok": False, "error": "not_configured", "detail": "Connect Shopmonkey first."}
    try:
        parts = client.search_inventory_parts()
        tires = client.search_inventory_tires()
        categories = client.list_inventory_categories()
    except ShopmonkeyApiError as exc:
        return _safe_error(exc)

    created_at = _utc_now()
    snapshot_id = uuid.uuid4().hex
    snapshot_data = {
        "schema_version": 1,
        "provider": "shopmonkey",
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "scope": {
            "inventory_parts": True,
            "inventory_tires": True,
            "inventory_categories": True,
            "customers": False,
            "vehicles": False,
            "orders": False,
            "messages": False,
        },
        "inventory_parts": parts,
        "inventory_tires": tires,
        "inventory_categories": categories,
    }
    canonical = json.dumps(snapshot_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    document = {**snapshot_data, "sha256": digest}

    snapshot_dir = _snapshot_dir(paths)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = created_at.replace("+00:00", "Z").replace(":", "").replace(".", "-")
    target = snapshot_dir / f"shopmonkey_inventory_{timestamp}_{snapshot_id[:8]}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)

    category_names = {
        _clean(row.get("id")): _clean(row.get("name"))
        for row in categories
        if isinstance(row, dict) and _clean(row.get("id"))
    }
    preview = [
        *(_inventory_preview_row(row, "part", category_names) for row in parts),
        *(_inventory_preview_row(row, "tire", category_names) for row in tires),
    ]
    preview.sort(key=lambda row: (row["kind"], row["brand"].lower(), row["name"].lower()))
    name_counts: dict[str, int] = defaultdict(int)
    for row in preview:
        if name_key := _name_key(row["name"]):
            name_counts[name_key] += 1
    return {
        "ok": True,
        "read_only": True,
        "snapshot_id": snapshot_id,
        "snapshot_file": str(target),
        "sha256": digest,
        "created_at": created_at,
        "scope": document["scope"],
        "summary": {
            "parts": len(parts),
            "tires": len(tires),
            "categories": len(categories),
            "total_items": len(parts) + len(tires),
            "quantity": sum(row["quantity"] for row in preview),
            "retail_value_cents": sum(row["retail_value_cents"] for row in preview),
            "missing_sku": sum(1 for row in preview if not row["sku"]),
            "missing_part_number": sum(1 for row in preview if not row["part_number"]),
            "missing_price": sum(1 for row in preview if row["retail_cost_cents"] is None),
            "missing_photo": sum(1 for row in preview if not row["has_photo"]),
            "missing_brand": sum(1 for row in preview if not row["brand"]),
            "missing_category": sum(1 for row in preview if not row["category"]),
            "negative_quantity": sum(1 for row in preview if row["quantity"] < 0),
            "zero_quantity": sum(1 for row in preview if row["quantity"] == 0),
            "duplicate_name_groups": sum(1 for count in name_counts.values() if count > 1),
        },
        "reset_preview": {
            "soft_delete_parts": len(parts),
            "soft_delete_tires": len(tires),
            "soft_delete_categories": len(categories),
            "enabled": False,
            "blocked_reason": "Stage and approve replacement price lists before enabling deletion.",
        },
        "items": preview,
    }
