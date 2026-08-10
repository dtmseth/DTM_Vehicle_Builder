#!/usr/bin/env python3
"""Seed a QuickBooks **sandbox** company with the real inventory CSV as Items.

Your manual sandbox import failed, so this pushes each CSV row in as a
NonInventory Item via the API, giving the sandbox realistic parts (name +
price) to test linking and estimates against.

SAFETY: this refuses to run unless the connected company is the **sandbox**
(``environment == "sandbox"``). It will never create Items in a production
company. It is also idempotent — Items whose Name already exists are skipped.

Prereqs: connect the dev app to your sandbox first (Settings → QuickBooks,
environment = sandbox, Connect). This tool reuses those stored credentials.

Usage:
  python tools/qb_seed_sandbox.py PATH/TO/export.csv            # dry run
  python tools/qb_seed_sandbox.py PATH/TO/export.csv --write    # create items
  python tools/qb_seed_sandbox.py PATH/TO/export.csv --write --limit 25
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


# ── pure, testable core ───────────────────────────────────────────────────────


def build_item_payload(row: dict, income_account_id: str) -> dict | None:
    """Map a CSV row to a QBO Item create payload, or None if unseedable.

    Name = part number (``Product/Service Name``) — unique in QBO and what the
    later part-number link keys off. Description = the friendly Sales
    Description. Price falls back to 0 when blank. Colons are stripped from the
    Name (QBO reserves ':' for sub-items).
    """
    name = (row.get("Product/Service Name") or "").strip().replace(":", "-")
    if not name:
        return None
    desc = " ".join((row.get("Sales Description") or "").split())
    price_raw = (row.get("Price") or "").strip()
    try:
        price = float(price_raw) if price_raw else 0.0
    except ValueError:
        price = 0.0
    payload = {
        "Name": name[:100],
        "Type": "NonInventory",
        "Sku": name[:100],
        "UnitPrice": price,
        "IncomeAccountRef": {"value": str(income_account_id)},
    }
    if desc:
        payload["Description"] = desc[:1000]
    return payload


def plan_seed(rows: list[dict], existing_names: set[str], income_account_id: str):
    """Return (to_create, skipped_existing, unseedable).

    to_create: list of (name, payload). skipped/unseedable: list of names.
    Names already present in ``existing_names`` (case-insensitive) are skipped
    so re-runs don't duplicate.
    """
    existing_lower = {n.lower() for n in existing_names}
    to_create, skipped, unseedable = [], [], []
    seen: set[str] = set()
    for row in rows:
        payload = build_item_payload(row, income_account_id)
        if payload is None:
            unseedable.append((row.get("Product/Service Name") or "").strip())
            continue
        name = payload["Name"]
        key = name.lower()
        if key in existing_lower or key in seen:
            skipped.append(name)
            continue
        seen.add(key)
        to_create.append((name, payload))
    return to_create, skipped, unseedable


# ── live run ──────────────────────────────────────────────────────────────────


def _read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--write", action="store_true", help="actually create the Items")
    ap.add_argument("--limit", type=int, default=0, help="cap how many to create (smoke test)")
    ap.add_argument("--income-account-id", default="", help="override the income account")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    from dtm_buildsheet.app.adapters.quickbooks.api_client import (
        QuickBooksApiClient,
        QuickBooksApiError,
    )
    from dtm_buildsheet.app.services import quickbooks_service
    from dtm_buildsheet.paths import AppPaths

    paths = AppPaths()
    status = quickbooks_service.get_status(paths)
    if not status.get("connected"):
        print("Not connected to QuickBooks. Connect the dev app to your sandbox first.",
              file=sys.stderr)
        return 2
    # HARD GATE: sandbox only. Never create Items in production.
    if status.get("environment") != "sandbox":
        print(f"REFUSING: connected environment is '{status.get('environment')}', not "
              "'sandbox'. This tool only seeds sandbox companies.", file=sys.stderr)
        return 2

    access = quickbooks_service.ensure_access_token(paths)
    realm = quickbooks_service.get_realm_id(paths)
    client = QuickBooksApiClient(access_token=access, realm_id=realm, environment="sandbox")

    income_id = args.income_account_id
    if not income_id:
        accounts = client.fetch_income_accounts()
        if not accounts:
            print("No income account found in the sandbox; cannot create sellable items.",
                  file=sys.stderr)
            return 2
        income_id = accounts[0]["id"]
        print(f"Using income account: {accounts[0]['name']} (id {income_id})")

    existing = {it["name"] for it in client.fetch_active_items()}
    rows = _read_rows(args.csv)
    to_create, skipped, unseedable = plan_seed(rows, existing, income_id)

    print(f"\nCSV rows: {len(rows)}")
    print(f"  to create : {len(to_create)}")
    print(f"  skip (exists): {len(skipped)}")
    print(f"  unseedable (no name): {len(unseedable)}")

    if not args.write:
        print("\n(dry run — re-run with --write to create the Items)")
        for name, payload in to_create[:10]:
            print(f"   would create  {name:22s}  {payload.get('Description','')[:40]}  ${payload['UnitPrice']}")
        return 0

    batch = to_create[: args.limit] if args.limit else to_create
    print(f"\nCreating {len(batch)} items…")
    created = errors = 0
    for i, (name, payload) in enumerate(batch, 1):
        try:
            client.create_item(payload)
            created += 1
        except QuickBooksApiError as exc:
            errors += 1
            print(f"   ! {name}: {exc}", file=sys.stderr)
        if i % 50 == 0:
            print(f"   …{i}/{len(batch)}")
    print(f"\n✍  created {created}, {errors} errors, {len(skipped)} skipped (already present)")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
