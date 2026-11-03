#!/usr/bin/env python3
"""One-order Shopmonkey retail-pricing latency pilot.

This deliberately narrow tool watches one writable Seth Test estimate for a newly added I2E
line. It treats inventory Retail as MSRP and applies Whelen's 36%-off retail rule only while the
line is still priced at MSRP. Any other price is treated as a user override and preserved.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from dtm_buildsheet.app.adapters.shopmonkey.api_client import ShopmonkeyApiError
from dtm_buildsheet.app.services.shopmonkey_service import _client


EXPECTED_CUSTOMER_ID = "431796b2-517c-474a-bf4c-4a39b66b17da"
EXPECTED_CUSTOMER_NAME = "Seth Test"
EXPECTED_LABEL = "$ Retail $"
EXPECTED_PART_NUMBER = "I2E"
EXPECTED_BRAND = "Whelen"
RETAIL_DISCOUNT_PERCENT = Decimal("36")


def discounted_cents(msrp_cents: int, discount_percent: Decimal) -> int:
    multiplier = (Decimal("100") - discount_percent) / Decimal("100")
    return int((Decimal(msrp_cents) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def should_auto_price(
    *,
    current_cents: int,
    msrp_cents: int,
    target_cents: int,
    pricing_matrix_id: str = "",
) -> bool:
    """Own a new line only when Shopmonkey supplied its price automatically.

    Shopmonkey may immediately apply its default pricing matrix instead of copying inventory
    Retail/MSRP. A populated pricingMatrixId identifies that automatic price. A non-MSRP line
    without a matrix remains outside this pilot so a user's custom price is preserved.
    """
    automatically_priced = current_cents == msrp_cents or bool(_clean(pricing_matrix_id))
    return automatically_priced and current_cents != target_cents


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _parts(services: object):
    if not isinstance(services, list):
        return
    for service in services:
        if not isinstance(service, dict):
            continue
        for part in service.get("parts") or []:
            if isinstance(part, dict):
                yield service, part


def _part_matches(line: dict, *, inventory_id: str) -> bool:
    return (
        _clean(line.get("inventoryPartId")) == inventory_id
        or _clean(line.get("partNumber")).casefold() == EXPECTED_PART_NUMBER.casefold()
        or _clean(line.get("sku")).casefold() == EXPECTED_PART_NUMBER.casefold()
    )


def _provider_datetime(value: object) -> datetime | None:
    clean = _clean(value)
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _services(client, order_id: str) -> list[dict]:
    payload = client._request(
        "GET",
        f"/order/{order_id}/service",
        operation="retail_pricing_pilot_services",
    )
    rows = payload.get("data") or []
    return rows if isinstance(rows, list) else []


def _services_with_rate_limit_retry(client, order_id: str) -> list[dict]:
    while True:
        try:
            return _services(client, order_id)
        except ShopmonkeyApiError as exc:
            if exc.status_code != 429:
                raise
            delay = max(2, exc.retry_after)
            print(json.dumps({
                "waiting_for_rate_limit": True,
                "retry_after_seconds": delay,
            }), flush=True)
            time.sleep(delay)


def _find_live_part(client) -> dict:
    payload = client._request(
        "POST",
        "/inventory_part/search",
        operation="retail_pricing_pilot_inventory_lookup",
        body={"limit": 10, "skip": 0, "where": {"number": EXPECTED_PART_NUMBER}},
    )
    matches = [
        row
        for row in (payload.get("data") or [])
        if isinstance(row, dict)
        and _clean(row.get("number")).casefold() == EXPECTED_PART_NUMBER.casefold()
        and not row.get("deleted")
    ]
    if len(matches) != 1:
        raise RuntimeError("I2E inventory lookup was not unique")
    return matches[0]


def _validate_customer(client) -> None:
    matches = []
    for customer in client.search_customers(max_records=5000):
        if _clean(customer.get("id")) == EXPECTED_CUSTOMER_ID:
            matches.append(customer)
    if len(matches) != 1:
        raise RuntimeError("Seth Test customer lookup was not unique")
    customer = matches[0]
    if _clean(customer.get("companyName")) != EXPECTED_CUSTOMER_NAME:
        raise RuntimeError("The expected test customer changed")
    labels = {
        _clean(row.get("name"))
        for row in customer.get("labels") or []
        if isinstance(row, dict)
    }
    if EXPECTED_LABEL not in labels:
        raise RuntimeError("Seth Test no longer has the $ Retail $ label")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()

    client = _client()
    if client is None:
        raise SystemExit("Shopmonkey is not connected in the desktop app keychain.")

    _validate_customer(client)
    order = client._request(
        "GET",
        f"/order/{args.order_id}",
        operation="retail_pricing_pilot_order_validation",
    ).get("data") or {}
    if _clean(order.get("customerId")) != EXPECTED_CUSTOMER_ID:
        raise SystemExit("The supplied order does not belong to Seth Test.")
    if order.get("invoiced") or order.get("authorized") or order.get("readOnly"):
        raise SystemExit("The supplied order is not a writable, unauthorised estimate.")

    inventory = _find_live_part(client)
    brand = inventory.get("brand") if isinstance(inventory.get("brand"), dict) else {}
    if _clean(brand.get("name")) != EXPECTED_BRAND:
        raise SystemExit("I2E is no longer assigned to the Whelen brand.")
    inventory_id = _clean(inventory.get("id"))
    msrp_cents = int(inventory.get("retailCostCents"))
    target_cents = discounted_cents(msrp_cents, RETAIL_DISCOUNT_PERCENT)

    baseline_services = _services_with_rate_limit_retry(client, args.order_id)
    baseline_ids = {
        _clean(part.get("id"))
        for _, part in _parts(baseline_services)
        if _part_matches(part, inventory_id=inventory_id)
    }
    print(json.dumps({
        "ready": True,
        "customer": EXPECTED_CUSTOMER_NAME,
        "label": EXPECTED_LABEL,
        "part_number": EXPECTED_PART_NUMBER,
        "brand": EXPECTED_BRAND,
        "msrp": msrp_cents / 100,
        "discount_percent": float(RETAIL_DISCOUNT_PERCENT),
        "target_price": target_cents / 100,
        "existing_i2e_lines_ignored": len(baseline_ids),
    }, indent=2), flush=True)

    deadline = time.monotonic() + max(1, args.timeout_seconds)
    while time.monotonic() < deadline:
        cycle_started = time.perf_counter()
        services_started = time.perf_counter()
        services = _services_with_rate_limit_retry(client, args.order_id)
        services_ms = (time.perf_counter() - services_started) * 1000
        for service, line in _parts(services):
            if not _part_matches(line, inventory_id=inventory_id):
                continue
            line_id = _clean(line.get("id"))
            if not line_id or line_id in baseline_ids:
                continue
            current_cents = int(line.get("retailCostCents"))
            if not should_auto_price(
                current_cents=current_cents,
                msrp_cents=msrp_cents,
                target_cents=target_cents,
                pricing_matrix_id=_clean(line.get("pricingMatrixId")),
            ):
                outcome = "already_priced" if current_cents == target_cents else "manual_price_preserved"
                print(json.dumps({
                    "outcome": outcome,
                    "current_price": current_cents / 100,
                    "expected_msrp": msrp_cents / 100,
                    "target_price": target_cents / 100,
                    "services_fetch_ms": round(services_ms, 1),
                }, indent=2), flush=True)
                return

            service_id = _clean(service.get("id"))
            update_started = time.perf_counter()
            client._request(
                "PUT",
                f"/order/{args.order_id}/service/{service_id}/part/{line_id}",
                operation="retail_pricing_pilot_line_update",
                params={"includeOrder": "false"},
                body={"retailCostCents": target_cents},
            )
            update_ms = (time.perf_counter() - update_started) * 1000

            confirm_started = time.perf_counter()
            confirmed = False
            for _, check in _parts(_services_with_rate_limit_retry(client, args.order_id)):
                if _clean(check.get("id")) == line_id:
                    confirmed = int(check.get("retailCostCents")) == target_cents
                    break
            confirm_ms = (time.perf_counter() - confirm_started) * 1000
            detected_at = datetime.now(timezone.utc)
            created_at = _provider_datetime(line.get("createdDate"))
            print(json.dumps({
                "outcome": "repriced" if confirmed else "confirmation_failed",
                "original_price": current_cents / 100,
                "new_price": target_cents / 100,
                "discount_percent": float(RETAIL_DISCOUNT_PERCENT),
                "services_fetch_ms": round(services_ms, 1),
                "update_ms": round(update_ms, 1),
                "confirm_ms": round(confirm_ms, 1),
                "detected_to_confirmed_ms": round(update_ms + confirm_ms, 1),
                "created_to_detected_ms": (
                    round((detected_at - created_at).total_seconds() * 1000, 1)
                    if created_at is not None
                    else None
                ),
                "confirmed": confirmed,
            }, indent=2), flush=True)
            return

        elapsed = time.perf_counter() - cycle_started
        time.sleep(max(0.0, args.poll_seconds - elapsed))

    raise SystemExit("Timed out waiting for a newly added I2E line.")


if __name__ == "__main__":
    main()
