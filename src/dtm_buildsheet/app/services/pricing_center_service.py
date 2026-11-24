"""Local-first Pricing Center import, rule, reconciliation, and export workflow."""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

import fitz
from openpyxl import Workbook, load_workbook

from ...paths import AppPaths
from ..adapters.shopmonkey.api_client import ShopmonkeyApiError
from . import shopmonkey_service
from . import pricing_cloud_service

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
EXPORT_ROW_LIMIT = 10_000
API_REQUESTS_PER_MINUTE = 90
API_MAX_MINUTES = 5
API_CALLS_PER_PART = 3
API_MAX_PARTS = (API_REQUESTS_PER_MINUTE * API_MAX_MINUTES * 8 // 10) // API_CALLS_PER_PART
SCOPE_OPTION_CACHE_SECONDS = 300
SNAPSHOT_MAX_AGE = timedelta(days=1)
_STORE_INIT_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()
_ANYGLIDE_PARSER_VERSION = "anyglide-parser-v2-spaced-prices"

RULE_METHODS = {
    "markup_percent_cost",
    "margin_percent_cost",
    "discount_percent_msrp",
    "flat_markup_cost",
    "flat_discount_msrp",
    "markup_percent_source",
    "flat_markup_source",
    "imported_value",
    "fixed_retail",
}
TARGET_FIELDS = (
    "sku", "description", "cost", "msrp", "map_price", "agency_price", "retail", "brand", "vendor",
    "effective_date", "unit", "shopmonkey_id",
)

# These presets describe vendor formats, not business pricing rules.  The user still
# confirms every proposed column assignment in the import wizard.
_BUILTIN_VENDOR_TEMPLATES: tuple[dict, ...] = (
    {
        "id": "stalker-internal-xlsx", "name": "Stalker internal pricing", "vendor": "Stalker",
        "file_type": ".xlsx", "filename": r"stalker.*internal.*pricing", "custom_parser": "stalker_internal",
        "mapping": {"sku": ("SKU",), "description": ("Product",),
                    "cost": ("Our Cost",), "msrp": ("List Price",)},
    },
    {
        "id": "stalker-dtm-pdf", "name": "Stalker DTM fleet pricing", "vendor": "Stalker",
        "file_type": ".pdf", "filename": r"stalker.*dtm.*pricing", "candidate": r"Page 1",
        "effective_date": "2026-10-26",
        "mapping": {"sku": ("MODEL NUMBER",), "cost": ("DTM Fleet PRICE",),
                    "msrp": ("STATE CONTRACT",), "effective_date": ("EFFECTIVE DATE",)},
    },
    {
        "id": "troy-master-xlsx", "name": "Troy master price list", "vendor": "Troy",
        "file_type": ".xlsx", "filename": r"troy.*master.*price", "custom_parser": "troy_all_sheets",
        "mapping": {"sku": ("TROY PART #",), "description": ("ITEM DESCRIPTION",),
                    "cost": ("DISCOUNT %",), "msrp": ("MSRP",)},
    },
    {
        "id": "whelen-compare-xlsx", "name": "Whelen account pricing", "vendor": "Whelen",
        "file_type": ".xlsx", "filename": r"whelen", "candidate": r"^Compare$",
        "effective_date": "2026-06-01",
        "mapping": {"sku": ("MODEL",), "description": ("DESCRIPTION",),
                    "cost": ("Buy 1-9",), "msrp": ("LIST",)},
    },
    {
        "id": "santa-cruz-xlsx", "name": "Santa Cruz price list", "vendor": "Santa Cruz",
        "file_type": ".xlsx", "filename": r"santa.*cruz", "candidate": r"^Item List$",
        "effective_date": "2026-01-01",
        "mapping": {"sku": ("PART NO.",), "description": ("DESCRIPTION",),
                    "cost": ("PER ORDER",), "msrp": ("LIST",)},
    },
    {
        "id": "tigertough-seat-covers-xlsx", "name": "TigerTough reseller pricing", "vendor": "TigerTough",
        "file_type": ".xlsx", "filename": r"tiger\s*tough.*jan", "candidate": r"^Sheet1$",
        "effective_date": "2026-01-01",
        "mapping": {"sku": ("Item Number",), "cost": ("Reseller Price",), "msrp": ("MSRP",),
                    "effective_date": ("Starting Date",)},
    },
    {
        "id": "tigertough-floor-liners-xlsx", "name": "TigerTough floor liner pricing", "vendor": "TigerTough",
        "file_type": ".xlsx", "filename": r"tigertough.*floor.*liner", "candidate": r"^Sheet1$",
        "mapping": {"sku": ("SKU",), "description": ("Description",), "cost": ("Cost",), "msrp": ("MSRP",)},
    },
    {
        "id": "kussmaul-xlsx", "name": "Kussmaul quantity pricing", "vendor": "Kussmaul",
        "file_type": ".xlsx", "filename": r"kussmaul", "candidate": r"^Sheet1$",
        "effective_date": "2026-09-01",
        "mapping": {"sku": ("Part Number",), "description": ("Description",),
                    "cost": ("0.3",), "msrp": ("Selling Price",)},
    },
    {
        "id": "truckvault-xlsx", "name": "TruckVault catalog pricing", "vendor": "TruckVault",
        "file_type": ".xlsx", "filename": r"truck\s*vault", "custom_parser": "truckvault",
        "mapping": {"sku": ("Stock Code",), "description": ("Description",),
                    "cost": ("Calculated Cost (72% of MSRP)",), "msrp": ("MSRP",)},
    },
    {
        "id": "redarc-xlsx", "name": "REDARC L30 pricing", "vendor": "REDARC",
        "file_type": ".xlsx", "filename": r"redarc", "candidate": r"^L30$",
        "effective_date": "2025-09-15",
        "mapping": {"sku": ("Part Number",), "description": ("Part Description",),
                    "cost": ("Net Invoice L30% (2)",), "msrp": ("Sept 15, 2025 MSRP",)},
    },
    {
        "id": "setina-xlsx", "name": "Setina multi-sheet price list", "vendor": "Setina",
        "file_type": ".xlsx", "filename": r"setina", "custom_parser": "setina",
        "effective_date": "2026-07-01",
        "mapping": {"sku": ("Part Number",), "description": ("Description",),
                    "cost": ("Dealer Price",), "msrp": ("MSRP",)},
    },
    {
        "id": "nightride-pdf", "name": "NightRide dealer pricing", "vendor": "Nightride",
        "file_type": ".pdf", "filename": r"nightride.*dealer", "candidate": r"Page 1",
        "effective_date": "2026-06-01",
        "mapping": {"sku": ("SKU",), "description": ("Product Name",),
                    "cost": ("Reseller Price",), "msrp": ("MSRP",), "agency_price": ("MAP",)},
    },
    {
        "id": "pac-pdf", "name": "PAC Tool Mounts dealer pricing", "vendor": "PAC",
        "file_type": ".pdf", "filename": r"pac.*tool.*mount", "custom_parser": "pac",
        "effective_date": "2026-01-01",
        "mapping": {"sku": ("Part Number",), "description": ("Description",),
                    "cost": ("Dealer Price",), "msrp": ("MSRP",)},
    },
    {
        "id": "gamber-program-xlsx", "name": "Gamber-Johnson program pricing", "vendor": "Gamber-Johnson",
        "file_type": ".xlsx", "filename": r"gamber.*65%", "candidate": r"^Table 1$",
        "effective_date": "2025-07-01",
        "mapping": {"sku": ("Item Number",), "description": ("Product Description",),
                    "cost": ("Program Pricing",), "msrp": ("July 1, 2025 List Price",)},
    },
    {
        "id": "gamber-gold-xlsx", "name": "Gamber-Johnson Gold pricing", "vendor": "Gamber-Johnson",
        "file_type": ".xlsx", "filename": r"gamber johnson.*july", "candidate": r"^2025 Gold",
        "effective_date": "2025-07-01", "custom_parser": "gamber_gold",
        "mapping": {"sku": ("Item Number",), "description": ("Product Description",),
                    "cost": ("Gold",), "msrp": ("List Price",), "agency_price": ("Sell",)},
    },
    {
        "id": "soundoff-xlsx", "name": "SoundOff Signal multi-sheet price list", "vendor": "SoundOff Signal",
        "file_type": ".xlsx", "filename": r"soundoff.*signal", "custom_parser": "soundoff",
        "effective_date": "2026-02-09",
        "mapping": {"sku": ("Part Number",), "description": ("Description",),
                    "cost": ("Calculated Cost (40% of MSRP)",), "msrp": ("MSRP",)},
    },
    {
        "id": "patrol-pc-pdf", "name": "Patrol PC master price list", "vendor": "PatrolPC",
        "file_type": ".pdf", "filename": r"patrol\s*pc", "custom_parser": "patrol_pc",
        "effective_date": "2026-05-20",
        "mapping": {"sku": ("Item",), "description": ("Description",),
                    "cost": ("Distributor",), "msrp": ("List",)},
    },
    {
        "id": "anyglide-pdf", "name": "AnyGlide catalog pricing", "vendor": "AnyGlide",
        "file_type": ".pdf", "filename": r"anyglide", "custom_parser": "anyglide",
        "effective_date": "2026-06-17",
        "mapping": {"sku": ("SKU",), "description": ("Description",),
                    "cost": ("Dealer",), "msrp": ("MSRP",)},
    },
    {
        "id": "westin-xlsx", "name": "Westin account net pricing", "vendor": "Westin",
        "file_type": ".xlsx", "filename": r"westin", "candidate": r"Account Net Prices",
        "effective_date": "2026-05-01",
        "mapping": {"sku": ("Part#",), "description": ("Application Description", "Product"),
                    "cost": ("YOUR COST",), "msrp": ("Retail",), "brand": ("Brand",)},
    },
    {
        "id": "havis-master-msrp-xlsx", "name": "Havis master MSRP", "vendor": "Havis",
        "file_type": ".xlsx", "filename": r"havis.*master.*msrp", "custom_parser": "havis_master",
        "mapping": {"sku": ("Catalog No.",), "description": ("Product Title",),
                    "msrp": ("MSRP",), "effective_date": ("Effective Date",)},
    },
    {
        "id": "angel-armor-pdf", "name": "Angel Armor agency pricing", "vendor": "Angel Armor",
        "file_type": ".pdf", "filename": r"angel.*armor", "custom_parser": "angel_armor",
        "effective_date": "2026-01-01",
        "mapping": {"sku": ("SKU",), "description": ("Description",),
                    "cost": ("Pro Price",), "msrp": ("MSRP",),
                    "agency_price": ("Agency Price",)},
    },
)

_INITIAL_RULES = (
    ("brand-whelen", "Whelen", "brand", "Whelen", "markup_percent_cost", "15.94", "retail"),
    ("brand-nightride", "Nightride", "brand", "Nightride", "markup_percent_cost", "25", "retail"),
    ("brand-truckvault", "TruckVault", "brand", "TruckVault", "markup_percent_cost", "25", "retail"),
    ("brand-westin", "Westin", "brand", "Westin", "markup_percent_cost", "25", "retail"),
    ("brand-sw-military", "SW Military", "brand", "SW Military", "markup_percent_cost", "25", "retail"),
    ("brand-kussmaul", "Kussmaul", "brand", "Kussmaul", "markup_percent_cost", "28.57", "retail"),
    ("brand-soundoff", "SoundOff", "brand", "SoundOff", "markup_percent_cost", "30.95", "retail"),
    ("brand-soundoff-signal", "SoundOff Signal", "brand", "SoundOff Signal", "markup_percent_cost", "30.95", "retail"),
    ("brand-troy", "Troy", "brand", "Troy", "markup_percent_cost", "21.43", "retail"),
    ("brand-gamber", "Gamber-Johnson", "brand", "Gamber-Johnson", "imported_value", "", "agency_price"),
    ("brand-lind", "LIND", "brand", "LIND", "imported_value", "", "agency_price"),
    ("brand-tigertough", "TigerTough", "brand", "TigerTough", "discount_percent_msrp", "10", "retail"),
    ("brand-redarc", "REDARC", "brand", "REDARC", "markup_percent_cost", "41.43", "retail"),
    ("brand-patrolpc", "PatrolPC", "brand", "PatrolPC", "markup_percent_cost", "11", "retail"),
    ("brand-setina", "Setina", "brand", "Setina", "markup_percent_cost", "20.28", "retail"),
    ("vendor-pac", "PAC Tools", "vendor", "PAC", "markup_percent_cost", "26.67", "retail"),
    ("brand-santacruz", "Santa Cruz", "brand", "Santa Cruz", "markup_percent_cost", "25", "retail"),
    ("brand-stalker", "Stalker", "brand", "Stalker", "discount_percent_msrp", "0", "retail"),
    ("brand-anyglide", "AnyGlide", "brand", "AnyGlide", "discount_percent_msrp", "0", "retail"),
    ("brand-magmic", "Mag Mic", "brand", "Mag Mic", "discount_percent_msrp", "0", "retail"),
    ("brand-angel-armor", "Angel Armor custom vendor price", "brand", "Angel Armor", "imported_value", "", "agency_price"),
    ("sku-redarc-lbat", "REDARC battery exception", "sku", "LBAT12150-SB", "markup_percent_cost", "32", "retail"),
    ("sku-redarc-pps", "REDARC power system exception", "sku", "PPS12100NA", "markup_percent_cost", "32", "retail"),
    ("sku-setina-ck1266", "Setina fold-down window", "sku", "CK1266FDT15F150", "fixed_retail", "0", "retail"),
    ("sku-setina-ck1266-10", "Setina fold-down window 10-pack", "sku", "CK1266FDT15F150-10", "fixed_retail", "0", "retail"),
    ("sku-brother-pj822", "Brother PJ-822", "sku", "PJ-822", "fixed_retail", "387.59", "retail"),
    ("sku-pac-handle-dt", "PAC exception HANDLE-DT", "sku", "HANDLE-DT", "fixed_retail", "53.14", "retail"),
    ("sku-pac-handle-pt", "PAC exception HANDLE-PT", "sku", "HANDLE-PT", "fixed_retail", "40.47", "retail"),
    ("sku-pac-2019", "PAC exception 2019", "sku", "2019", "fixed_retail", "1.20", "retail"),
    ("sku-pac-2020", "PAC exception 2020", "sku", "2020", "fixed_retail", "1.46", "retail"),
    ("sku-pac-7062-mp", "PAC exception 7062-MP", "sku", "7062-MP", "fixed_retail", "1.08", "retail"),
    ("sku-pac-7062-ap", "PAC exception 7062-AP", "sku", "7062-AP", "fixed_retail", "1.08", "retail"),
    ("sku-pac-7002", "PAC exception 7002", "sku", "7002", "fixed_retail", "13.87", "retail"),
    ("sku-pac-7016-100", "PAC exception 7016-100", "sku", "7016-100", "fixed_retail", "18.94", "retail"),
    ("sku-pac-3023", "PAC exception 3023", "sku", "3023", "fixed_retail", "1.96", "retail"),
    ("sku-pac-3024", "PAC exception 3024", "sku", "3024", "fixed_retail", "1.96", "retail"),
    ("sku-pac-7053", "PAC exception 7053", "sku", "7053", "fixed_retail", "21.22", "retail"),
    ("sku-pac-7054", "PAC exception 7054", "sku", "7054", "fixed_retail", "40.98", "retail"),
    ("sku-pac-2104", "PAC exception 2104", "sku", "2104", "fixed_retail", "3.86", "retail"),
    ("sku-pac-2010", "PAC exception 2010", "sku", "2010", "fixed_retail", "4.37", "retail"),
    ("sku-pac-2018", "PAC exception 2018", "sku", "2018", "fixed_retail", "4.24", "retail"),
    ("sku-pac-2023", "PAC exception 2023", "sku", "2023", "fixed_retail", "7.03", "retail"),
    ("sku-pac-7018", "PAC exception 7018", "sku", "7018", "fixed_retail", "9.18", "retail"),
    ("sku-pac-7019", "PAC exception 7019", "sku", "7019", "fixed_retail", "8.42", "retail"),
    ("sku-pac-7052", "PAC exception 7052", "sku", "7052", "fixed_retail", "8.17", "retail"),
    ("sku-pac-a41632s", "PAC exception A41632S", "sku", "A41632S", "fixed_retail", "1.20", "retail"),
    ("sku-pac-a416s", "PAC exception A416S", "sku", "A416S", "fixed_retail", "0.82", "retail"),
    ("sku-pac-a432s", "PAC exception A432S", "sku", "A432S", "fixed_retail", "1.46", "retail"),
    ("sku-pac-a648s", "PAC exception A648S", "sku", "A648S", "fixed_retail", "2.47", "retail"),
    ("sku-pac-7009", "PAC exception 7009", "sku", "7009", "fixed_retail", "398.95", "retail"),
    ("sku-pac-7004d", "PAC exception 7004D", "sku", "7004D", "fixed_retail", "103.81", "retail"),
    ("sku-pac-7058", "PAC exception 7058", "sku", "7058", "fixed_retail", "221.61", "retail"),
    ("sku-pac-7004md", "PAC exception 7004MD", "sku", "7004MD", "fixed_retail", "103.81", "retail"),
    ("sku-pac-7059", "PAC exception 7059", "sku", "7059", "fixed_retail", "343.47", "retail"),
    ("sku-pac-k8010-12", "PAC exception K8010-12", "sku", "K8010-12", "fixed_retail", "96.14", "retail"),
    ("sku-pac-k8010-24", "PAC exception K8010-24", "sku", "K8010-24", "fixed_retail", "185.70", "retail"),
)

# Standard Buy and Standard Sell terms from DTM Vendor Pricing Guide v1.0.
# Promotional/package/bulk terms are intentionally excluded from automatic rules.
_VENDOR_GUIDE_RULE_VERSION = "dtm-vendor-pricing-guide-v1"
_GAMBER_SELL_RULE_VERSION = "gamber-johnson-gold-sell-v1"
_VENDOR_GUIDE_RULES = (
    # id, name, scope type/value, retail method/amount/source,
    # cost enabled/method/amount/source, additional cost discount enabled/percent
    ("brand-whelen", "Whelen standard", "brand", "Whelen", "discount_percent_msrp", "36", "msrp", True, "discount_percent_msrp", "40", "msrp", True, "8"),
    ("brand-setina", "Setina standard", "brand", "Setina", "discount_percent_msrp", "20", "msrp", True, "discount_percent_msrp", "30", "msrp", True, "5"),
    ("brand-westin", "Westin standard", "brand", "Westin", "discount_percent_msrp", "15", "msrp", True, "discount_percent_msrp", "50.59", "msrp", False, ""),
    ("brand-sw-military", "SW Military Westin pricing", "brand", "SW Military", "discount_percent_msrp", "15", "msrp", True, "discount_percent_msrp", "50.59", "msrp", False, ""),
    ("brand-gamber", "Gamber Johnson Gold and Sell", "brand", "Gamber Johnson", "imported_value", "", "agency_price", True, "imported_value", "", "cost", False, ""),
    ("brand-lind", "Lind — Gamber Johnson Gold and Sell", "brand", "Lind", "imported_value", "", "agency_price", True, "imported_value", "", "cost", False, ""),
    ("brand-soundoff-signal", "SoundOff Signal standard", "brand", "SoundOff Signal", "discount_percent_msrp", "45", "msrp", True, "discount_percent_msrp", "60", "msrp", False, ""),
    ("brand-havis", "Havis standard", "brand", "Havis", "discount_percent_msrp", "20", "msrp", False, "", "", "", False, ""),
    ("brand-american-aluminum", "American Aluminum price sheet", "brand", "American Aluminum", "imported_value", "", "agency_price", True, "imported_value", "", "cost", False, ""),
    ("brand-tigertough", "TigerTough standard", "brand", "TigerTough", "discount_percent_msrp", "10", "msrp", True, "discount_percent_msrp", "29", "msrp", False, ""),
    ("brand-intermotive", "Intermotive standard", "brand", "Intermotive", "discount_percent_msrp", "0", "msrp", True, "discount_percent_msrp", "10", "msrp", False, ""),
    ("brand-santacruz", "Santa Cruz standard", "brand", "Santa Cruz", "discount_percent_msrp", "25", "msrp", True, "discount_percent_msrp", "40", "msrp", False, ""),
    ("brand-troy", "Troy Products standard", "brand", "Troy Products", "discount_percent_msrp", "15", "msrp", True, "discount_percent_msrp", "30", "msrp", False, ""),
    ("brand-truckvault", "TruckVault standard", "brand", "TruckVault", "discount_percent_msrp", "10", "msrp", True, "discount_percent_msrp", "28", "msrp", False, ""),
    ("brand-kussmaul", "Kussmaul standard", "brand", "Kussmaul", "discount_percent_msrp", "10", "msrp", True, "discount_percent_msrp", "30", "msrp", False, ""),
    ("brand-nightride", "NightRide standard", "brand", "NightRide", "markup_percent_cost", "25", "cost", True, "imported_value", "", "cost", False, ""),
    ("vendor-pac", "PAC Tool standard", "vendor", "PAC", "discount_percent_msrp", "5", "msrp", True, "discount_percent_msrp", "25", "msrp", False, ""),
    ("brand-patrolpc", "Patrol PC standard", "brand", "Patrol PC", "discount_percent_msrp", "26", "msrp", True, "discount_percent_msrp", "33", "msrp", False, ""),
    ("brand-angel-armor", "Angel Armor Pro and Agency pricing", "brand", "Angel Armor", "imported_value", "", "agency_price", True, "imported_value", "", "cost", False, ""),
    ("brand-ace-k9", "Ace K-9 standard", "brand", "Ace K-9", "discount_percent_msrp", "0", "msrp", True, "discount_percent_msrp", "5", "msrp", False, ""),
    ("brand-ziamatic", "Ziamatic standard", "brand", "Ziamatic", "discount_percent_msrp", "10", "msrp", True, "discount_percent_msrp", "30", "msrp", False, ""),
    ("brand-magmic", "Magnetic Mic standard", "brand", "Magnetic Mic", "discount_percent_msrp", "0", "msrp", True, "fixed_retail", "29", "cost", False, ""),
    ("brand-redarc", "REDARC standard", "brand", "REDARC", "discount_percent_msrp", "10", "msrp", True, "discount_percent_msrp", "30", "msrp", False, ""),
    ("brand-bullet-point", "Bullet Point Mounts standard", "brand", "Bullet Point Mounts", "discount_percent_msrp", "0", "msrp", True, "discount_percent_msrp", "15", "msrp", False, ""),
    ("brand-stalker", "Stalker standard", "brand", "Stalker", "discount_percent_msrp", "0", "msrp", True, "imported_value", "", "cost", False, ""),
    ("brand-truck-accessories", "Truck Accessories MAP pricing", "brand", "Truck Accessories", "imported_value", "", "agency_price", False, "", "", "", False, ""),
)


def _initial_rule_group(rule_id: str) -> str:
    if rule_id.startswith("sku-pac-"):
        return "PAC"
    if rule_id.startswith("sku-redarc-"):
        return "REDARC"
    if rule_id.startswith("sku-setina-"):
        return "Setina"
    if rule_id == "sku-brother-pj822":
        return "Brother"
    return ""


class PricingCenterError(ValueError):
    """A validation error safe to show in the Pricing Center UI."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_age(row: dict) -> timedelta:
    try:
        created = datetime.fromisoformat(_clean(row.get("created_at")))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(timedelta(0), datetime.now(timezone.utc) - created.astimezone(timezone.utc))
    except (TypeError, ValueError):
        return SNAPSHOT_MAX_AGE


def _snapshot_is_stale(row: dict | None) -> bool:
    return not row or _snapshot_age(row) >= SNAPSHOT_MAX_AGE


def _public_snapshot(row: dict | None) -> dict | None:
    if not row:
        return None
    result = {key: row[key] for key in ("id", "filename", "generation_date", "row_count", "used_at", "created_at")}
    result["is_stale"] = _snapshot_is_stale(row)
    result["age_hours"] = round(_snapshot_age(row).total_seconds() / 3600, 1)
    return result


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _clean(value).upper())


_CATALOG_SCOPE_ALIASES = {
    "PAC": "PAC",
    "PACTOOL": "PAC",
    "PACTOOLS": "PAC",
    "PACTOOLMOUNTS": "PAC",
    "PERFORMANCEADVANTAGECOMPANY": "PAC",
    "WHELENENGINEERING": "WHELEN",
    "SOUNDOFF": "SOUNDOFFSIGNAL",
    "SOUNDOFFSIGNAL": "SOUNDOFFSIGNAL",
    "SETINAMANUFACTURING": "SETINA",
    "TROY": "TROYPRODUCTS",
    "TROYPRODUCTS": "TROYPRODUCTS",
    "WESTINAUTOMOTIVE": "WESTIN",
    "WESTINPUBLICSAFETY": "WESTIN",
    "STALKER": "STALKERRADAR",
    "STALKERRADAR": "STALKERRADAR",
    "SANTACRUZ": "SANTACRUZGUNLOCKS",
    "SANTACRUZGUNLOCKS": "SANTACRUZGUNLOCKS",
    "MAGMIC": "MAGNETICMIC",
    "MAGNETICMIC": "MAGNETICMIC",
}


def _catalog_scope_key(value: object) -> str:
    key = _key(value)
    return _CATALOG_SCOPE_ALIASES.get(key, key)


def _money(value: object) -> Decimal | None:
    raw = re.sub(r"\s+", "", _clean(value).replace("$", "").replace(",", "").replace("%", ""))
    if not raw or raw.lower() in {"n/a", "na", "none", "-"}:
        return None
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    try:
        return Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _money_text(value: Decimal | None) -> str:
    return "" if value is None else format(value.quantize(Decimal("0.01")), ".2f")


def _safe_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return clean[:160] or "price-list"


def _decode_upload(payload: dict) -> tuple[str, bytes]:
    name = _safe_name(_clean(payload.get("filename")))
    encoded = _clean(payload.get("content_base64"))
    if not encoded:
        raise PricingCenterError("Choose a file to upload.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise PricingCenterError("The uploaded file could not be decoded.") from exc
    if not content:
        raise PricingCenterError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise PricingCenterError("Price-list files must be 25 MB or smaller.")
    return name, content


def _iso_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = _clean(value)
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _candidate_effective_date(candidate: dict, mapping: dict[str, str]) -> str:
    header = mapping.get("effective_date") or _suggest_mapping(candidate["headers"]).get("effective_date", "")
    if not header or header not in candidate["headers"]:
        return ""
    index = candidate["headers"].index(header)
    for row in candidate["rows"][:100]:
        if index < len(row) and (resolved := _iso_date(row[index])):
            return resolved
    return ""


def _source_effective_date(path: Path, suffix: str, client_modified: object = "") -> str:
    if suffix == ".xlsx":
        workbook = None
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            if resolved := _iso_date(workbook.properties.modified or workbook.properties.created):
                return resolved
        except Exception:
            pass
        finally:
            if workbook is not None:
                workbook.close()
    return _iso_date(client_modified) or datetime.now().astimezone().date().isoformat()


class PricingStore:
    def __init__(self, paths: AppPaths) -> None:
        self.root = paths.workspace_pricing_dir
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("sources", "snapshots", "reviews", "exports"):
            (self.root / name).mkdir(exist_ok=True)
        self.database = self.root / "pricing_center.sqlite3"
        database_key = self.database.resolve()
        with _STORE_INIT_LOCK:
            pricing_cloud_service.hydrate_database_if_missing(self.database)
            if database_key not in _INITIALIZED_DATABASES:
                self._initialize()
                _INITIALIZED_DATABASES.add(database_key)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        guide_migrated = False
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, scope_type TEXT NOT NULL,
                    scope_value TEXT NOT NULL, method TEXT NOT NULL, amount TEXT NOT NULL,
                    source_field TEXT NOT NULL, enabled INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    group_name TEXT NOT NULL DEFAULT '', cost_method TEXT NOT NULL DEFAULT '',
                    cost_amount TEXT NOT NULL DEFAULT '', cost_source_field TEXT NOT NULL DEFAULT '',
                    cost_enabled INTEGER NOT NULL DEFAULT 0,
                    cost_discount_enabled INTEGER NOT NULL DEFAULT 0,
                    cost_discount_percent TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS presets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, vendor TEXT NOT NULL,
                    file_type TEXT NOT NULL, candidate_label TEXT NOT NULL,
                    mapping_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_sessions (
                    id TEXT PRIMARY KEY, vendor TEXT NOT NULL, effective_date TEXT NOT NULL,
                    filename TEXT NOT NULL, source_path TEXT NOT NULL, matrix_path TEXT NOT NULL,
                    candidate_json TEXT NOT NULL, mapping_json TEXT NOT NULL,
                    normalized_path TEXT NOT NULL, include_notes INTEGER NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    rule_override_id TEXT NOT NULL DEFAULT '',
                    rule_override_set INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, generation_date TEXT NOT NULL,
                    headers_json TEXT NOT NULL, rows_path TEXT NOT NULL, row_count INTEGER NOT NULL,
                    used_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                    review_path TEXT NOT NULL, artifact_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    missing_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, mime TEXT NOT NULL,
                    filename TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reference_cache (
                    key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "missing_count" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN missing_count INTEGER NOT NULL DEFAULT 0")
            rule_columns = {row[1] for row in db.execute("PRAGMA table_info(rules)")}
            if "group_name" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
            if "cost_method" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_method TEXT NOT NULL DEFAULT ''")
            if "cost_amount" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_amount TEXT NOT NULL DEFAULT ''")
            if "cost_source_field" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_source_field TEXT NOT NULL DEFAULT ''")
            if "cost_enabled" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_enabled INTEGER NOT NULL DEFAULT 0")
            if "cost_discount_enabled" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_discount_enabled INTEGER NOT NULL DEFAULT 0")
            if "cost_discount_percent" not in rule_columns:
                db.execute("ALTER TABLE rules ADD COLUMN cost_discount_percent TEXT NOT NULL DEFAULT ''")
            session_columns = {row[1] for row in db.execute("PRAGMA table_info(import_sessions)")}
            if "rule_override_id" not in session_columns:
                db.execute("ALTER TABLE import_sessions ADD COLUMN rule_override_id TEXT NOT NULL DEFAULT ''")
            if "rule_override_set" not in session_columns:
                db.execute("ALTER TABLE import_sessions ADD COLUMN rule_override_set INTEGER NOT NULL DEFAULT 0")
            if not db.execute("SELECT 1 FROM rules LIMIT 1").fetchone():
                seeded_at = _now()
                db.executemany(
                    "INSERT INTO rules (id,name,scope_type,scope_value,method,amount,source_field,enabled,updated_at,group_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(*rule, 1, seeded_at, _initial_rule_group(rule[0])) for rule in _INITIAL_RULES],
                )
            db.execute("UPDATE rules SET group_name='PAC' WHERE id LIKE 'sku-pac-%' AND group_name='' ")
            db.execute("UPDATE rules SET group_name='REDARC' WHERE id LIKE 'sku-redarc-%' AND group_name='' ")
            db.execute("UPDATE rules SET group_name='Setina' WHERE id LIKE 'sku-setina-%' AND group_name='' ")
            db.execute("UPDATE rules SET group_name='Brother' WHERE id='sku-brother-pj822' AND group_name='' ")
            db.execute("DELETE FROM rules WHERE method='unchanged'")
            db.execute("UPDATE rules SET source_field='agency_price' WHERE source_field='map_price'")
            guide_applied = db.execute(
                "SELECT 1 FROM reference_cache WHERE key=?", (_VENDOR_GUIDE_RULE_VERSION,),
            ).fetchone()
            if not guide_applied:
                guide_migrated = True
                applied_at = _now()
                db.execute("DELETE FROM rules WHERE id='brand-soundoff'")
                db.executemany(
                    """
                    INSERT OR REPLACE INTO rules (
                        id,name,scope_type,scope_value,method,amount,source_field,enabled,updated_at,
                        group_name,cost_method,cost_amount,cost_source_field,cost_enabled,
                        cost_discount_enabled,cost_discount_percent
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            rule_id, name, scope_type, scope_value,
                            method, amount, source_field, 1, applied_at, "",
                            cost_method, cost_amount, cost_source_field, 1 if cost_enabled else 0,
                            1 if cost_discount_enabled else 0, cost_discount_percent,
                        )
                        for (
                            rule_id, name, scope_type, scope_value,
                            method, amount, source_field,
                            cost_enabled, cost_method, cost_amount, cost_source_field,
                            cost_discount_enabled, cost_discount_percent,
                        ) in _VENDOR_GUIDE_RULES
                    ],
                )
                db.execute(
                    "INSERT INTO reference_cache (key,payload_json,updated_at) VALUES (?,?,?)",
                    (
                        _VENDOR_GUIDE_RULE_VERSION,
                        json.dumps({"source": "DTM Vendor Pricing Guide.docx", "rule_count": len(_VENDOR_GUIDE_RULES)}),
                        applied_at,
                    ),
                )
            gamber_sell_applied = db.execute(
                "SELECT 1 FROM reference_cache WHERE key=?", (_GAMBER_SELL_RULE_VERSION,),
            ).fetchone()
            if not gamber_sell_applied:
                guide_migrated = True
                applied_at = _now()
                for rule_id, name in (
                    ("brand-gamber", "Gamber Johnson Gold and Sell"),
                    ("brand-lind", "Lind — Gamber Johnson Gold and Sell"),
                ):
                    db.execute(
                        """
                        UPDATE rules SET name=?,method='imported_value',amount='',
                            source_field='agency_price',cost_method='imported_value',cost_amount='',
                            cost_source_field='cost',cost_enabled=1,cost_discount_enabled=0,
                            cost_discount_percent='',updated_at=? WHERE id=?
                        """,
                        (name, applied_at, rule_id),
                    )
                db.execute(
                    "INSERT INTO reference_cache (key,payload_json,updated_at) VALUES (?,?,?)",
                    (
                        _GAMBER_SELL_RULE_VERSION,
                        json.dumps({"source": "Gamber Johnson Gold price list", "rule_count": 2}),
                        applied_at,
                    ),
                )
        if guide_migrated:
            pricing_cloud_service.mirror_database_in_background(self.database)

    def list_rows(self, table: str, order: str = "updated_at DESC") -> list[dict]:
        if table not in {"rules", "presets", "import_sessions", "snapshots", "runs"}:
            raise ValueError("unsupported table")
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def get(self, table: str, row_id: str) -> dict | None:
        if table not in {"rules", "presets", "import_sessions", "snapshots", "runs", "artifacts"}:
            raise ValueError("unsupported table")
        with self.connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None

    def latest(self, table: str) -> dict | None:
        rows = self.list_rows(table, "created_at DESC")
        return rows[0] if rows else None


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _json_read(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reference_cache_exists(store: PricingStore, key: str) -> bool:
    with store.connect() as database:
        return bool(database.execute(
            "SELECT 1 FROM reference_cache WHERE key=?", (key,),
        ).fetchone())


def _mirror_database(store: PricingStore) -> None:
    pricing_cloud_service.mirror_database_in_background(store.database)


def _rows_from_csv(content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    rows = [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    return [_candidate("CSV", rows, "csv:1")]


def _sheet_rows(sheet) -> list[list[object]]:
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _rows_from_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return [_candidate(sheet.title, _sheet_rows(sheet), f"sheet:{index}") for index, sheet in enumerate(workbook.worksheets)]
    finally:
        workbook.close()


def _rows_from_xls(path: Path) -> list[dict]:
    try:
        import xlrd
    except ImportError as exc:
        raise PricingCenterError("Legacy .xls support is not installed in this Builder version.") from exc
    workbook = xlrd.open_workbook(path)
    return [
        _candidate(sheet.name, [sheet.row_values(i) for i in range(sheet.nrows)], f"sheet:{index}")
        for index, sheet in enumerate(workbook.sheets())
    ]


def _rows_from_pdf(path: Path) -> list[dict]:
    document = fitz.open(path)
    candidates: list[dict] = []
    try:
        for page_index, page in enumerate(document):
            finder = page.find_tables()
            for table_index, table in enumerate(finder.tables):
                rows = table.extract()
                if rows:
                    candidate = _candidate(
                        f"Page {page_index + 1}, table {table_index + 1}", rows,
                        f"page:{page_index + 1}:table:{table_index + 1}",
                    )
                    candidate["provenance"] = [{"page": page_index + 1, "table": table_index + 1}]
                    candidates.append(candidate)
    finally:
        document.close()
    if not candidates:
        raise PricingCenterError(
            "No table was detected in this PDF. A vendor preset or a text-based PDF is required; scanned PDFs need OCR before import."
        )
    grouped: dict[tuple[str, ...], dict] = {}
    for candidate in candidates:
        signature = tuple(_key(header) for header in candidate["headers"])
        if signature not in grouped:
            grouped[signature] = dict(candidate)
            grouped[signature]["rows"] = list(candidate["rows"])
            grouped[signature]["provenance"] = list(candidate["provenance"])
            continue
        merged = grouped[signature]
        merged["rows"].extend(candidate["rows"])
        merged["row_count"] += candidate["row_count"]
        merged["provenance"].extend(candidate["provenance"])
    result: list[dict] = []
    for index, merged in enumerate(grouped.values(), start=1):
        pages = sorted({item["page"] for item in merged["provenance"]})
        if len(merged["provenance"]) > 1:
            merged["id"] = f"pdf-group:{index}"
            merged["label"] = f"Pages {pages[0]}–{pages[-1]}, matching tables"
        result.append(merged)
    return result


def _header_score(row: Iterable[object]) -> int:
    aliases = {
        "sku", "part", "partnumber", "item", "itemnumber", "description", "name",
        "cost", "dealer", "agency", "msrp", "list", "retail", "price", "brand", "vendor",
    }
    score = 0
    for value in row:
        compact = re.sub(r"[^a-z0-9]+", "", _clean(value).lower())
        if any(alias in compact for alias in aliases):
            score += 1
    return score


def _row_repeats_headers(row: Iterable[object], headers: Iterable[object]) -> bool:
    row_values = list(row)
    header_values = list(headers)
    matches = sum(
        1 for value, header in zip(row_values, header_values)
        if _clean(value) and _key(value) == _key(header)
    )
    return matches >= 2


def _candidate(label: str, raw_rows: list[list[object]], source: str) -> dict:
    rows = [list(row) for row in raw_rows if any(_clean(cell) for cell in row)]
    if not rows:
        return {"id": source, "label": label, "headers": [], "rows": [], "row_count": 0, "header_row": 0}
    header_index = max(range(min(25, len(rows))), key=lambda index: (_header_score(rows[index]), -index))
    width = max(len(row) for row in rows)
    header_values = rows[header_index] + [""] * (width - len(rows[header_index]))
    seen: Counter[str] = Counter()
    headers: list[str] = []
    for index, value in enumerate(header_values):
        base = _clean(value) or f"Column {index + 1}"
        seen[base] += 1
        headers.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    data = [(row + [""] * (width - len(row)))[:width] for row in rows[header_index + 1:]]
    data = [row for row in data if not _row_repeats_headers(row, headers)]
    return {
        "id": source,
        "label": label,
        "headers": headers,
        "rows": [[_clean(cell) for cell in row] for row in data],
        "row_count": len(data),
        "header_row": header_index + 1,
    }


def _canonical_candidate(
    label: str, headers: list[str], rows: list[list[object]], source: str,
    provenance: list[dict] | None = None,
) -> dict:
    width = len(headers)
    cleaned_rows = [
        list(row) for row in rows
        if not _row_repeats_headers(row, headers)
    ]
    result = {
        "id": source,
        "label": label,
        "headers": headers,
        "rows": [[_clean(cell) for cell in (list(row) + [""] * width)[:width]] for row in cleaned_rows],
        "row_count": len(cleaned_rows),
        "header_row": 1,
    }
    if provenance:
        result["provenance"] = provenance
    return result


def _builtin_template(filename: str, vendor: object, suffix: str) -> dict | None:
    vendor_key = _key(vendor)
    readable_filename = re.sub(r"[_-]+", " ", filename)
    matches: list[tuple[int, dict]] = []
    for template in _BUILTIN_VENDOR_TEMPLATES:
        if template["file_type"] != suffix:
            continue
        filename_match = bool(
            re.search(template["filename"], filename, flags=re.IGNORECASE)
            or re.search(template["filename"], readable_filename, flags=re.IGNORECASE)
        )
        vendor_match = vendor_key == _key(template["vendor"])
        if filename_match or vendor_match:
            matches.append(((4 if filename_match else 0) + (2 if vendor_match else 0), template))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _template_header(headers: list[str], aliases: Iterable[str]) -> str:
    keyed = [(_key(header), header) for header in headers]
    for alias in aliases:
        alias_key = _key(alias)
        exact = [header for key, header in keyed if key == alias_key]
        if exact:
            return exact[-1]
    for alias in aliases:
        alias_key = _key(alias)
        partial = [header for key, header in keyed if alias_key and alias_key in key]
        if partial:
            return partial[-1]
    return ""


def _template_mapping(template: dict, candidate: dict) -> dict[str, str]:
    return {
        field: header
        for field, aliases in template.get("mapping", {}).items()
        if (header := _template_header(candidate["headers"], aliases))
    }


def _apply_template_candidate(template: dict, candidates: list[dict]) -> tuple[list[dict], dict[str, str]]:
    pattern = template.get("candidate")
    chosen = next(
        (item for item in candidates if not pattern or re.search(pattern, item["label"], flags=re.IGNORECASE)),
        candidates[0],
    )
    ordered = [chosen, *(item for item in candidates if item is not chosen)]
    return ordered, _template_mapping(template, chosen)


def _mapped_row_looks_like_header(row: dict, mapping: dict[str, str]) -> bool:
    comparisons = [
        (_key(row.get(field)), _key(header))
        for field, header in mapping.items()
        if _clean(row.get(field)) and _clean(header)
    ]
    exact_matches = sum(1 for value, header in comparisons if value == header)
    sku_value = _key(row.get("sku"))
    sku_header = _key(mapping.get("sku"))
    return exact_matches >= 2 or bool(sku_value and sku_value == sku_header)


def _dedupe_by_sku(rows: list[list[object]]) -> list[list[object]]:
    result: dict[str, list[object]] = {}
    order: list[str] = []
    for row in rows:
        sku = _key(row[0] if row else "")
        if not sku:
            continue
        if sku not in result:
            result[sku] = row
            order.append(sku)
        elif sum(bool(_clean(cell)) for cell in row) > sum(bool(_clean(cell)) for cell in result[sku]):
            result[sku] = row
    return [result[sku] for sku in order]


def _xlsx_header_row(sheet, required: str = "partnumber") -> tuple[list[str], list[list[object]]]:
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    for index, row in enumerate(rows[:25]):
        headers = [_clean(value) for value in row]
        if any(required == _key(header).lower() for header in headers):
            return headers, rows[index + 1:]
    return [], []


def _parse_stalker_internal_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[object]] = []
    try:
        sheet = next((item for item in workbook.worksheets if item.title == "Pricing"), workbook.active)
        headers, source_rows = _xlsx_header_row(sheet, required="internalsku")
        indexes = {header: index for index, header in enumerate(headers)}
        internal_header = _template_header(headers, ("Internal SKU",))
        manufacturer_header = _template_header(headers, ("Manufacturer Part #",))
        description_header = _template_header(headers, ("Product",))
        cost_header = _template_header(headers, ("Our Cost",))
        msrp_header = _template_header(headers, ("List Price",))
        for source in source_rows:
            internal_sku = _clean(source[indexes[internal_header]] if internal_header and indexes[internal_header] < len(source) else "")
            manufacturer_sku = _clean(source[indexes[manufacturer_header]] if manufacturer_header and indexes[manufacturer_header] < len(source) else "")
            sku = manufacturer_sku or internal_sku
            cost = source[indexes[cost_header]] if cost_header and indexes[cost_header] < len(source) else ""
            msrp = source[indexes[msrp_header]] if msrp_header and indexes[msrp_header] < len(source) else ""
            if not sku or (_money(cost) is None and _money(msrp) is None):
                continue
            description = source[indexes[description_header]] if description_header and indexes[description_header] < len(source) else ""
            rows.append([sku, description, cost, msrp, internal_sku, manufacturer_sku])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "Stalker internal pricing", ["SKU", "Product", "Our Cost", "List Price", "Internal SKU", "Manufacturer Part #"],
        _dedupe_by_sku(rows), "template:stalker-internal",
    )]


def _parse_troy_all_sheets_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[object]] = []
    try:
        master = [sheet for sheet in workbook.worksheets if sheet.title == "MASTER PRICE LIST"]
        sheets = [*master, *(sheet for sheet in workbook.worksheets if sheet not in master)]
        for sheet in sheets:
            headers, source_rows = _xlsx_header_row(sheet, required="troypart")
            if not headers:
                continue
            indexes = {header: index for index, header in enumerate(headers)}
            sku_header = _template_header(headers, ("TROY PART #",))
            description_header = _template_header(headers, ("ITEM DESCRIPTION",))
            cost_header = _template_header(headers, ("DISCOUNT %",))
            msrp_header = _template_header(headers, ("MSRP",))
            for source in source_rows:
                sku = _clean(source[indexes[sku_header]] if sku_header and indexes[sku_header] < len(source) else "")
                cost = source[indexes[cost_header]] if cost_header and indexes[cost_header] < len(source) else ""
                msrp = source[indexes[msrp_header]] if msrp_header and indexes[msrp_header] < len(source) else ""
                if not sku or (_money(cost) is None and _money(msrp) is None):
                    continue
                description = source[indexes[description_header]] if description_header and indexes[description_header] < len(source) else ""
                rows.append([sku, description, cost, msrp])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "All Troy product sheets", ["TROY PART #", "ITEM DESCRIPTION", "DISCOUNT %", "MSRP"],
        _dedupe_by_sku(rows), "template:troy-all-sheets",
    )]


def _parse_setina_xlsx(path: Path) -> list[dict]:
    rows: list[list[object]] = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            headers, source_rows = _xlsx_header_row(sheet)
            if not headers:
                continue
            sku_header = _template_header(headers, ("Part Number",))
            description_header = _template_header(headers, ("Description",))
            msrp_header = _template_header(headers, ("Retail Price", "Retail"))
            cost_header = _template_header(headers, ("Dealer Price",))
            if not sku_header or not msrp_header:
                continue
            indexes = {header: index for index, header in enumerate(headers)}
            for source in source_rows:
                sku = _clean(source[indexes[sku_header]] if indexes[sku_header] < len(source) else "")
                msrp = source[indexes[msrp_header]] if indexes[msrp_header] < len(source) else ""
                cost = source[indexes[cost_header]] if cost_header and indexes[cost_header] < len(source) else ""
                if sku == "0" or not re.search(r"\d", sku) or (_money(msrp) is None and _money(cost) is None):
                    continue
                description = source[indexes[description_header]] if description_header and indexes[description_header] < len(source) else ""
                rows.append([sku, description, cost, msrp])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "All Setina product sheets", ["Part Number", "Description", "Dealer Price", "MSRP"],
        _dedupe_by_sku(rows), "template:setina",
    )]


def _parse_truckvault_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[object]] = []
    try:
        sheet = workbook.active
        source_rows = list(sheet.iter_rows(values_only=True))
        headers = [_clean(value) for value in source_rows[0]]
        indexes = {header: index for index, header in enumerate(headers)}
        sku_header = _template_header(headers, ("Stock Code",))
        description_header = _template_header(headers, ("Description",))
        msrp_header = _template_header(headers, ("MSRP",))
        for source in source_rows[1:]:
            sku = _clean(source[indexes[sku_header]] if indexes[sku_header] < len(source) else "")
            msrp = _money(source[indexes[msrp_header]] if indexes[msrp_header] < len(source) else "")
            if not sku or msrp is None:
                continue
            description = source[indexes[description_header]] if indexes[description_header] < len(source) else ""
            cost = (msrp * Decimal("0.72")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rows.append([sku, description, _money_text(cost), _money_text(msrp)])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "TruckVault pricing with standard buy cost",
        ["Stock Code", "Description", "Calculated Cost (72% of MSRP)", "MSRP"],
        rows, "template:truckvault",
    )]


def _parse_soundoff_xlsx(path: Path) -> list[dict]:
    rows: list[list[object]] = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            headers, source_rows = _xlsx_header_row(sheet)
            if not headers:
                continue
            sku_header = _template_header(headers, ("Part Number",))
            description_header = _template_header(headers, ("Description",))
            msrp_header = _template_header(headers, ("List Price",))
            if not sku_header or not msrp_header:
                continue
            indexes = {header: index for index, header in enumerate(headers)}
            for source in source_rows:
                sku = _clean(source[indexes[sku_header]] if indexes[sku_header] < len(source) else "")
                msrp = _money(source[indexes[msrp_header]] if indexes[msrp_header] < len(source) else "")
                if not sku or msrp is None:
                    continue
                description = source[indexes[description_header]] if description_header and indexes[description_header] < len(source) else ""
                cost = (msrp * Decimal("0.40")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                rows.append([sku, description, _money_text(cost), _money_text(msrp)])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "All SoundOff product sheets",
        ["Part Number", "Description", "Calculated Cost (40% of MSRP)", "MSRP"],
        _dedupe_by_sku(rows), "template:soundoff",
    )]


def _parse_gamber_gold_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[object]] = []
    try:
        sheet = next(item for item in workbook.worksheets if item.title.startswith("2025 Gold"))
        source_rows = list(sheet.iter_rows(values_only=True))
        headers = [_clean(value) for value in source_rows[0]][:7]
        indexes = {header: index for index, header in enumerate(headers)}
        sku_header = _template_header(headers, ("Item Number",))
        description_header = _template_header(headers, ("Product Description",))
        msrp_header = _template_header(headers, ("7/1/25 List Price",))
        sell_header = _template_header(headers, ("Sell",))
        cost_header = _template_header(headers, ("Gold",))
        for source in source_rows[1:]:
            sku = _clean(source[indexes[sku_header]] if indexes[sku_header] < len(source) else "")
            if not sku:
                continue
            msrp = source[indexes[msrp_header]] if indexes[msrp_header] < len(source) else ""
            sell = source[indexes[sell_header]] if sell_header and indexes[sell_header] < len(source) else ""
            cost = source[indexes[cost_header]] if indexes[cost_header] < len(source) else ""
            if _money(msrp) is None and _money(cost) is None and _money(sell) is None:
                continue
            description = source[indexes[description_header]] if indexes[description_header] < len(source) else ""
            rows.append([sku, description, cost, msrp, sell])
    finally:
        workbook.close()
    return [_canonical_candidate(
        "2025 Gold pricing", ["Item Number", "Product Description", "Gold", "List Price", "Sell"],
        _dedupe_by_sku(rows), "template:gamber-gold",
    )]


def _parse_havis_master_xlsx(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[object]] = []
    effective_date = ""
    try:
        for sheet in workbook.worksheets:
            source_rows = list(sheet.iter_rows(values_only=True))
            for header_index, source in enumerate(source_rows[:25]):
                headers = [_clean(value) for value in source]
                sku_header = _template_header(headers, ("Catalog No.",))
                description_header = _template_header(headers, ("Product Title",))
                msrp_header = _template_header(headers, ("MSRP Effective", "MSRP",))
                if not sku_header or not msrp_header:
                    continue
                indexes = {header: index for index, header in enumerate(headers)}
                header_match = re.search(
                    r"(?:effective\s*)?(\d{1,2}/\d{1,2}/\d{4})",
                    msrp_header,
                    flags=re.IGNORECASE,
                )
                effective_date = _iso_date(header_match.group(1)) if header_match else ""
                for data in source_rows[header_index + 1:]:
                    sku = _clean(data[indexes[sku_header]] if indexes[sku_header] < len(data) else "")
                    msrp = data[indexes[msrp_header]] if indexes[msrp_header] < len(data) else ""
                    if not sku or _money(msrp) is None:
                        continue
                    description = (
                        data[indexes[description_header]]
                        if description_header and indexes[description_header] < len(data)
                        else ""
                    )
                    rows.append([sku, description, _money_text(_money(msrp)), effective_date])
                break
            if rows:
                break
    finally:
        workbook.close()
    return [_canonical_candidate(
        "Havis master MSRP", ["Catalog No.", "Product Title", "MSRP", "Effective Date"],
        _dedupe_by_sku(rows), "template:havis-master-msrp",
    )]


def _pdf_cell(value: object) -> str:
    return " ".join(_clean(value).replace("\n", " ").split())


def _patrol_pc_table_row(cells: list[str]) -> list[object] | None:
    if len(cells) < 5:
        return None
    sku, description, msrp, contract, cost = cells[:5]
    if not sku:
        return None
    prices = (msrp, contract, cost)
    if all(_key(value) == "INCLUDED" for value in prices):
        return [re.sub(r"\s+", "", sku), description, "0.00", "0.00", "0.00"]
    if _money(msrp) is None and _money(cost) is None:
        return None
    return [re.sub(r"\s+", "", sku), description, cost, msrp, contract]


def _dedupe_patrol_pc_rows(rows: list[list[object]]) -> list[list[object]]:
    """Prefer separately priced rows when a SKU is also included in a configuration."""
    result: dict[str, list[object]] = {}
    order: list[str] = []
    for row in rows:
        sku = _key(row[0] if row else "")
        if not sku:
            continue
        price_score = sum(bool(_money(value)) for value in row[2:5])
        current_score = sum(bool(_money(value)) for value in result.get(sku, [])[2:5])
        if sku not in result:
            order.append(sku)
        if sku not in result or price_score > current_score:
            result[sku] = row
    return [result[sku] for sku in order]


def _parse_fixed_pdf_tables(path: Path, parser: str) -> list[dict]:
    document = fitz.open(path)
    rows: list[list[object]] = []
    provenance: list[dict] = []
    try:
        for page_number, page in enumerate(document, start=1):
            if parser == "anyglide" and page_number > 9:
                continue
            for table_number, table in enumerate(page.find_tables().tables, start=1):
                extracted = table.extract()
                provenance.append({"page": page_number, "table": table_number})
                for raw in extracted:
                    cells = [_pdf_cell(value) for value in raw]
                    if parser == "pac" and len(cells) >= 6:
                        sku, description, msrp, cost = cells[0], cells[2], cells[3], cells[4]
                        if sku and (_money(msrp) is not None or _money(cost) is not None):
                            rows.append([re.sub(r"\s+", "", sku), description, cost, msrp, cells[5]])
                    elif parser == "patrol_pc":
                        if parsed := _patrol_pc_table_row(cells):
                            rows.append(parsed)
                    elif parser == "anyglide" and len(cells) >= 6:
                        sku, description, msrp, cost = cells[0], cells[2], cells[3], cells[4]
                        if sku and (_money(msrp) is not None or _money(cost) is not None):
                            rows.append([re.sub(r"\s+", "", sku), description, cost, msrp])
    finally:
        document.close()
    if parser == "pac":
        return [_canonical_candidate(
            "PAC dealer price tables", ["Part Number", "Description", "Dealer Price", "MSRP", "Purchase 25+"],
            _dedupe_by_sku(rows), "template:pac", provenance,
        )]
    if parser == "patrol_pc":
        return [_canonical_candidate(
            "Patrol PC master price list", ["Item", "Description", "Distributor", "List", "Contract"],
            _dedupe_patrol_pc_rows(rows), "template:patrol-pc", provenance,
        )]
    return [_canonical_candidate(
        "AnyGlide catalog price tables", ["SKU", "Description", "Dealer", "MSRP"],
        rows, "template:anyglide", provenance,
    )]


def _parse_angel_armor_pdf(path: Path) -> list[dict]:
    document = fitz.open(path)
    rows: list[list[object]] = []
    current_make = ""
    current_model = ""
    price_pattern = re.compile(r"\$?\s*([\d,]+\.\d{2})")
    sku_pattern = re.compile(r"\b\d{2}-\d{5}\b")
    ignored = {"ALL COST IS IN USD", "CUSTOM IIIA AND III+ PROJECTS AVAILABLE UPON REQUEST/APPROVAL"}
    try:
        for page in document:
            for raw_line in page.get_text("text", sort=True).splitlines():
                line = " ".join(raw_line.split())
                if not line or line in ignored or line.startswith("v1."):
                    continue
                if "MSRP" in line and "AGENCY" in line:
                    current_model = line.split("MSRP", 1)[0].strip()
                    continue
                prices = price_pattern.findall(line)
                skus = sku_pattern.findall(line)
                if skus and len(prices) >= 2:
                    prefix = line[:line.find(prices[0])].replace("$", "").strip()
                    rating = next((value for value in ("III+", "IIIA") if value in line), "")
                    detail = "Rear bulkhead" if "REAR BULKHEAD" in line else "Rear hatch" if "REAR HATCH" in line else "Panel"
                    base_description = " ".join(value for value in (current_make, current_model, prefix, rating, detail) if value)
                    for sku in skus:
                        pro_price = prices[2] if len(prices) >= 3 else ""
                        rows.append([sku, base_description, pro_price, prices[0], prices[1]])
                    continue
                if not prices and line == line.upper() and len(line) < 45 and "COMING SOON" not in line:
                    current_make = line
    finally:
        document.close()
    return [_canonical_candidate(
        "Angel Armor agency price tables", ["SKU", "Description", "Pro Price", "MSRP", "Agency Price"],
        _dedupe_by_sku(rows), "template:angel-armor",
    )]


def _custom_template_candidates(path: Path, parser: str) -> list[dict]:
    if parser == "stalker_internal":
        return _parse_stalker_internal_xlsx(path)
    if parser == "troy_all_sheets":
        return _parse_troy_all_sheets_xlsx(path)
    if parser == "setina":
        return _parse_setina_xlsx(path)
    if parser == "truckvault":
        return _parse_truckvault_xlsx(path)
    if parser == "soundoff":
        return _parse_soundoff_xlsx(path)
    if parser == "gamber_gold":
        return _parse_gamber_gold_xlsx(path)
    if parser == "havis_master":
        return _parse_havis_master_xlsx(path)
    if parser == "angel_armor":
        return _parse_angel_armor_pdf(path)
    return _parse_fixed_pdf_tables(path, parser)


def _suggest_mapping(headers: list[str]) -> dict[str, str]:
    patterns = {
        "shopmonkey_id": ("shopmonkeyid", "inventoryid"),
        "sku": ("sku", "partnumber", "part#", "itemnumber", "model"),
        "description": ("description", "productname", "itemdescription", "name"),
        "cost": ("dealercost", "cost", "netprice", "dealerprice"),
        "msrp": ("msrp", "listprice", "suggestedretail", "retailprice", "retail"),
        "agency_price": ("agencyprice", "agencycost", "agency", "mapprice", "minimumadvertisedprice", "map", "customvendorprice"),
        "brand": ("brand", "manufacturer", "mfg"),
        "vendor": ("vendor", "supplier"),
        "effective_date": ("effectivedate", "priceeffective", "date"),
        "unit": ("uom", "unitofmeasure", "unit"),
    }
    compact = {header: re.sub(r"[^a-z0-9#]+", "", header.lower()) for header in headers}
    result: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in patterns.items():
        for header, value in compact.items():
            if header not in used and any(
                alias == value
                or (alias in value and not (field == "msrp" and alias == "retail" and value.startswith("our")))
                for alias in aliases
            ):
                result[field] = header
                used.add(header)
                break
    return result


def inspect_price_list(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    filename, content = _decode_upload(payload)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls", ".pdf"}:
        raise PricingCenterError("Use a PDF, Excel, or CSV price list.")
    session_id = uuid.uuid4().hex
    source_path = store.root / "sources" / f"{session_id}-{filename}"
    template = _builtin_template(filename, payload.get("vendor"), suffix)
    if not template and not _clean(payload.get("vendor")):
        raise PricingCenterError("Enter the vendor name for this price-list format.")
    source_path.write_bytes(content)
    if template and template.get("custom_parser"):
        candidates = _custom_template_candidates(source_path, template["custom_parser"])
    elif suffix == ".csv":
        candidates = _rows_from_csv(content)
    elif suffix == ".xlsx":
        candidates = _rows_from_xlsx(source_path)
    elif suffix == ".xls":
        candidates = _rows_from_xls(source_path)
    else:
        candidates = _rows_from_pdf(source_path)
    candidates = [item for item in candidates if item["headers"] and item["row_count"]]
    if not candidates:
        raise PricingCenterError("No usable table was found in this file.")
    template_mapping: dict[str, str] = {}
    if template:
        candidates, template_mapping = _apply_template_candidate(template, candidates)
    matrix_path = store.root / "sources" / f"{session_id}-tables.json"
    _json_write(matrix_path, candidates)
    first = candidates[0]
    resolved_vendor = _clean(payload.get("vendor")) or _clean(template.get("vendor") if template else "")
    resolved_effective_date = (
        _clean(payload.get("effective_date"))
        or _clean(template.get("effective_date") if template else "")
        or _candidate_effective_date(first, template_mapping)
        or _source_effective_date(source_path, suffix, payload.get("file_last_modified"))
    )
    now = _now()
    with store.connect() as db:
        db.execute(
            "INSERT INTO import_sessions (id,vendor,effective_date,filename,source_path,matrix_path,candidate_json,mapping_json,normalized_path,include_notes,status,created_at,updated_at,rule_override_id,rule_override_set) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id, resolved_vendor, resolved_effective_date,
                filename, str(source_path), str(matrix_path), first["id"], "{}", "",
                1 if payload.get("include_notes", True) else 0, "inspected", now, now, "", 0,
            ),
        )
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        source_path, f"Vendor Sources/{session_id}-{filename}",
    )
    vendor_key = _key(resolved_vendor)
    preset = next(
        (
            row for row in store.list_rows("presets")
            if _key(row["vendor"]) == vendor_key and row["file_type"] == suffix
        ),
        None,
    )
    preset_mapping = json.loads(preset["mapping_json"]) if preset else {}
    public = []
    for item in candidates:
        suggested = _suggest_mapping(item["headers"])
        if template and item is candidates[0] and template_mapping:
            suggested = dict(template_mapping)
        if preset and (
            len(candidates) == 1
            or not preset["candidate_label"]
            or preset["candidate_label"] == item["label"]
        ):
            if all(header in item["headers"] for header in preset_mapping.values()):
                suggested = dict(preset_mapping)
        if suggested.get("map_price") and not suggested.get("agency_price"):
            suggested["agency_price"] = suggested["map_price"]
        suggested.pop("map_price", None)
        suggested.pop("retail", None)
        public.append({**item, "rows": item["rows"][:12], "suggested_mapping": suggested})
    return {
        "ok": True, "session_id": session_id, "filename": filename, "candidates": public,
        "vendor": resolved_vendor, "effective_date": resolved_effective_date,
        "vendor_auto_detected": bool(template and not _clean(payload.get("vendor"))),
        "preset_applied": bool(preset or template),
        "preset_name": preset["name"] if preset else template["name"] if template else "",
        "template_id": template["id"] if template else "",
    }


def confirm_mapping(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    session = store.get("import_sessions", _clean(payload.get("session_id")))
    if not session:
        raise PricingCenterError("This price-list session no longer exists.")
    candidates = _json_read(session["matrix_path"])
    candidate_id = _clean(payload.get("candidate_id")) or session["candidate_json"]
    candidate = next((item for item in candidates if item["id"] == candidate_id), None)
    if not candidate:
        raise PricingCenterError("Choose a worksheet or PDF table.")
    mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else {}
    mapping = {field: _clean(mapping.get(field)) for field in TARGET_FIELDS if _clean(mapping.get(field))}
    if mapping.get("map_price") and not mapping.get("agency_price"):
        mapping["agency_price"] = mapping["map_price"]
    mapping.pop("map_price", None)
    mapping.pop("retail", None)
    if not mapping.get("sku"):
        raise PricingCenterError("Assign a source column to SKU / part number.")
    price_fields = ("cost", "msrp", "agency_price")
    if not any(mapping.get(field) for field in price_fields):
        raise PricingCenterError("Assign at least one price column: cost, MSRP, or custom vendor price.")
    unknown = [header for header in mapping.values() if header not in candidate["headers"]]
    if unknown:
        raise PricingCenterError(f"A mapped source column was not found: {unknown[0]}")
    indexes = {header: index for index, header in enumerate(candidate["headers"])}
    session_vendor = _clean(payload.get("vendor")) or session["vendor"]
    template = _builtin_template(session["filename"], session_vendor, Path(session["filename"]).suffix.lower())
    inferred_brand = _clean(template.get("vendor") if template else "")
    normalized: list[dict] = []
    missing_sku = invalid_price = repeated_header = 0
    seen: Counter[str] = Counter()
    for row_number, source in enumerate(candidate["rows"], start=candidate["header_row"] + 1):
        row = {field: _clean(source[indexes[header]]) for field, header in mapping.items()}
        row["source_row"] = row_number
        if not row.get("sku"):
            missing_sku += 1
            continue
        if _mapped_row_looks_like_header(row, mapping):
            repeated_header += 1
            continue
        row["vendor"] = row.get("vendor") or session_vendor
        row["brand"] = row.get("brand") or inferred_brand
        row["effective_date"] = row.get("effective_date") or _clean(payload.get("effective_date")) or session["effective_date"]
        parsed_prices = {field: _money(row.get(field)) for field in price_fields}
        if all(value is None for value in parsed_prices.values()):
            invalid_price += 1
            continue
        row.update({field: _money_text(value) for field, value in parsed_prices.items()})
        seen[_key(row["sku"])] += 1
        normalized.append(row)
    duplicates = sum(count - 1 for count in seen.values() if count > 1)
    normalized_path = store.root / "sources" / f"{session['id']}-normalized.json"
    _json_write(normalized_path, normalized)
    now = _now()
    with store.connect() as db:
        db.execute(
            "UPDATE import_sessions SET vendor=?,effective_date=?,candidate_json=?,mapping_json=?,normalized_path=?,include_notes=?,status=?,updated_at=? WHERE id=?",
            (
                _clean(payload.get("vendor")) or session["vendor"],
                _clean(payload.get("effective_date")) or session["effective_date"],
                candidate_id, json.dumps(mapping), str(normalized_path),
                1 if payload.get("include_notes", True) else 0, "mapped", now, session["id"],
            ),
        )
        # A confirmed mapping replaces the normalized vendor source. Any older
        # review/export must be regenerated from that new source before reuse.
        db.execute(
            "UPDATE runs SET status='source_changed' WHERE session_id=?",
            (session["id"],),
        )
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        normalized_path, f"Vendor Sources/{session['id']}-normalized.json",
    )
    if payload.get("save_preset"):
        save_preset(paths, {
            "name": _clean(payload.get("preset_name")) or f"{_clean(payload.get('vendor'))} {Path(session['filename']).suffix.upper()}",
            "vendor": _clean(payload.get("vendor")), "file_type": Path(session["filename"]).suffix.lower(),
            "candidate_label": candidate["label"], "mapping": mapping,
        })
    return {
        "ok": True, "session_id": session["id"], "rows_ready": len(normalized),
        "missing_sku": missing_sku, "duplicate_sku": duplicates, "invalid_price": invalid_price,
        "repeated_header": repeated_header,
        "excluded_rows": missing_sku + invalid_price + repeated_header,
    }


def resume_import(paths: AppPaths, payload: dict) -> dict:
    """Restore a saved import at column assignment or rule/reconciliation review."""
    store = PricingStore(paths)
    session = store.get("import_sessions", _clean(payload.get("session_id")))
    if not session:
        raise PricingCenterError("This saved price-list import no longer exists.")
    candidates = _json_read(session["matrix_path"])
    saved_mapping = json.loads(session["mapping_json"] or "{}")
    public_candidates = []
    for item in candidates:
        suggested = saved_mapping if saved_mapping and item["id"] == session["candidate_json"] else _suggest_mapping(item["headers"])
        public_candidates.append({**item, "rows": item["rows"][:12], "suggested_mapping": suggested})
    runs = [row for row in store.list_rows("runs", "created_at DESC") if row["session_id"] == session["id"]]
    latest_run = runs[0] if runs else None
    latest_snapshot = store.latest("snapshots")
    needs_rematch = bool(
        latest_run and (
            (latest_snapshot and latest_run["snapshot_id"] != latest_snapshot["id"])
            or latest_run["status"] == "source_changed"
        )
    )
    suffix = Path(session["filename"]).suffix.lower()
    template = _builtin_template(session["filename"], session["vendor"], suffix)
    source_refresh_needed = bool(
        template and template.get("id") == "anyglide-pdf"
        and not _reference_cache_exists(
            store, f"{_ANYGLIDE_PARSER_VERSION}:{session['id']}",
        )
    )
    if source_refresh_needed and session.get("normalized_path"):
        _normalized_sources_with_price_repairs(store, session)
    vendor_key = _key(session["vendor"])
    preset = next((
        row for row in store.list_rows("presets")
        if _key(row["vendor"]) == vendor_key and row["file_type"] == suffix
    ), None)
    return {
        "ok": True,
        "session": {
            "id": session["id"], "vendor": session["vendor"],
            "effective_date": session["effective_date"], "filename": session["filename"],
            "status": session["status"], "include_notes": bool(session["include_notes"]),
        },
        "candidates": public_candidates,
        "candidate_id": session["candidate_json"],
        "mapping": saved_mapping,
        "run_id": latest_run["id"] if latest_run else "",
        "run_status": latest_run["status"] if latest_run else "",
        "needs_rematch": needs_rematch,
        "source_refreshed": source_refresh_needed,
        "preset_applied": bool(preset or template),
        "preset_name": preset["name"] if preset else template["name"] if template else "",
    }


def finalize_review(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    rows = _json_read(run["review_path"])
    unresolved = [row for row in rows if row.get("status") == "needs_review"]
    if unresolved:
        raise PricingCenterError("Resolve every part that still needs review before finalizing this price list.")
    with store.connect() as db:
        db.execute("UPDATE runs SET status='ready' WHERE id=?", (run["id"],))
    _mirror_database(store)
    return {"ok": True, "run_id": run["id"], "status": "ready"}


def delete_import(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    session = store.get("import_sessions", _clean(payload.get("session_id")))
    if not session:
        raise PricingCenterError("This price-list import no longer exists.")
    runs = [row for row in store.list_rows("runs", "created_at DESC") if row["session_id"] == session["id"]]
    artifact_ids = [row["artifact_id"] for row in runs if row.get("artifact_id")]
    paths_to_remove = [session.get("source_path"), session.get("matrix_path"), session.get("normalized_path")]
    paths_to_remove.extend(row.get("review_path") for row in runs)
    paths_to_remove.extend(row.get("artifact_path") for row in runs)
    root = store.root.resolve()
    for raw_path in paths_to_remove:
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        path.unlink(missing_ok=True)
    for run in runs:
        export_dir = store.root / "exports" / run["id"]
        if export_dir.is_dir():
            shutil.rmtree(export_dir)
    with store.connect() as db:
        if artifact_ids:
            db.executemany("DELETE FROM artifacts WHERE id=?", [(value,) for value in artifact_ids])
        db.executemany("DELETE FROM runs WHERE id=?", [(row["id"],) for row in runs])
        db.execute("DELETE FROM import_sessions WHERE id=?", (session["id"],))
    _mirror_database(store)
    return {"ok": True, "deleted": True, "session_id": session["id"]}


def list_rules(paths: AppPaths) -> dict:
    rows = PricingStore(paths).list_rows("rules")
    for row in rows:
        row["enabled"] = bool(row["enabled"])
        row["cost_enabled"] = bool(row.get("cost_enabled"))
        row["cost_discount_enabled"] = bool(row.get("cost_discount_enabled"))
    return {"ok": True, "rules": rows, "exceptions": [row for row in rows if row["scope_type"] == "sku"]}


def _scope_reference_cache(store: PricingStore) -> tuple[dict, str]:
    with store.connect() as db:
        row = db.execute(
            "SELECT payload_json,updated_at FROM reference_cache WHERE key='shopmonkey_scopes'"
        ).fetchone()
    if not row:
        return {}, ""
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return (payload if isinstance(payload, dict) else {}), _clean(row["updated_at"])


def _scope_cache_is_fresh(updated_at: str) -> bool:
    if not updated_at:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    return age.total_seconds() < SCOPE_OPTION_CACHE_SECONDS


def _scope_counts(store: PricingStore) -> tuple[Counter[str], Counter[str], dict[str, str], dict[str, str]]:
    brand_counts: Counter[str] = Counter()
    vendor_counts: Counter[str] = Counter()
    brand_names: dict[str, str] = {}
    vendor_names: dict[str, str] = {}
    snapshot = store.latest("snapshots")
    records = _json_read(snapshot["rows_path"]) if snapshot else []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        for prefix, counts, names in (
            ("Brand", brand_counts, brand_names), ("Vendor", vendor_counts, vendor_names),
        ):
            name = _clean(_field(record, prefix))
            key = _key(name)
            if key:
                counts[key] += 1
                names.setdefault(key, name)
    return brand_counts, vendor_counts, brand_names, vendor_names


def _scope_option_rows(store: PricingStore, references: dict) -> tuple[list[dict], list[dict]]:
    brand_counts, vendor_counts, brand_names, vendor_names = _scope_counts(store)
    rules = store.list_rows("rules")
    for rule in rules:
        scope_type = _clean(rule.get("scope_type")).lower()
        if scope_type not in {"brand", "vendor"}:
            continue
        name = _clean(rule.get("scope_value"))
        key = _key(name)
        if scope_type == "brand" and key:
            brand_names.setdefault(key, name)
        elif scope_type == "vendor" and key:
            vendor_names.setdefault(key, name)

    def merge(kind: str, counts: Counter[str], names: dict[str, str]) -> list[dict]:
        result: dict[str, dict] = {
            key: {"id": "", "name": name, "part_count": int(counts.get(key, 0))}
            for key, name in names.items()
        }
        for row in references.get(kind, []) if isinstance(references.get(kind), list) else []:
            if not isinstance(row, dict):
                continue
            name = _clean(row.get("name")); key = _key(name)
            if not key:
                continue
            result[key] = {
                "id": _clean(row.get("id")), "name": name,
                "part_count": int(counts.get(key, result.get(key, {}).get("part_count", 0))),
            }
        return sorted(result.values(), key=lambda row: row["name"].casefold())

    return merge("brands", brand_counts, brand_names), merge("vendors", vendor_counts, vendor_names)


def scope_options(paths: AppPaths, *, refresh: bool = False) -> dict:
    """Return instant cached choices, optionally refreshing two small provider collections."""
    store = PricingStore(paths)
    references, updated_at = _scope_reference_cache(store)
    client = shopmonkey_service._client() if refresh else None
    connected = client is not None if refresh else bool(references)
    if refresh and connected and not _scope_cache_is_fresh(updated_at):
        try:
            brands = [
                {"id": _clean(row.get("id")), "name": _clean(row.get("name"))}
                for row in client.list_brands()
                if _clean(row.get("id")) and _clean(row.get("name"))
                and _clean(row.get("entity")).lower() == "part"
            ]
            vendors = [
                {"id": _clean(row.get("id")), "name": _clean(row.get("name"))}
                for row in client.list_vendors()
                if _clean(row.get("id")) and _clean(row.get("name"))
            ]
            references = {"brands": brands, "vendors": vendors}
            updated_at = _now()
            with store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO reference_cache (key,payload_json,updated_at) VALUES (?,?,?)",
                    ("shopmonkey_scopes", json.dumps(references), updated_at),
                )
        except ShopmonkeyApiError:
            pass
    brands, vendors = _scope_option_rows(store, references)
    return {
        "ok": True, "brands": brands, "vendors": vendors,
        "updated_at": updated_at, "connected": connected,
        "count_source": "current Shopmonkey inventory baseline",
    }


def _validate_rule_calculation(method: str, amount: str, source_field: str, label: str) -> None:
    if method not in RULE_METHODS:
        raise PricingCenterError(f"Choose a supported {label} pricing method.")
    parsed_amount = _money(amount)
    if method != "imported_value":
        if parsed_amount is None or parsed_amount < 0:
            raise PricingCenterError(f"Enter a non-negative {label} rule amount.")
        if method in {"margin_percent_cost", "discount_percent_msrp"} and parsed_amount >= 100:
            raise PricingCenterError(f"{label.title()} margin and discount percentages must be less than 100%.")
    if method == "imported_value" and source_field not in {"cost", "msrp", "agency_price"}:
        raise PricingCenterError(f"Choose cost, MSRP, or the custom vendor price column for {label}.")
    if method in {"markup_percent_source", "flat_markup_source"} and source_field != "agency_price":
        raise PricingCenterError(f"Choose the custom vendor price column as the {label} calculation source.")


def save_rule(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    rule_id = _clean(payload.get("id")) or uuid.uuid4().hex
    scope_type = _clean(payload.get("scope_type")).lower()
    scope_value = _clean(payload.get("scope_value"))
    method = _clean(payload.get("method"))
    if scope_type not in {"sku", "brand", "vendor", "session"}:
        raise PricingCenterError("Choose SKU, brand, vendor, or this import as the rule scope.")
    if not scope_value:
        raise PricingCenterError("Enter the SKU, brand, vendor, or import session this rule applies to.")
    amount = _clean(payload.get("amount"))
    source_field = _clean(payload.get("source_field")) or "retail"
    _validate_rule_calculation(method, amount, source_field, "Our Retail (sell)")
    cost_enabled = scope_type != "sku" and bool(payload.get("cost_enabled"))
    cost_method = _clean(payload.get("cost_method")) if cost_enabled else ""
    cost_amount = _clean(payload.get("cost_amount")) if cost_enabled else ""
    cost_source_field = (_clean(payload.get("cost_source_field")) or "cost") if cost_enabled else ""
    if cost_enabled:
        _validate_rule_calculation(cost_method, cost_amount, cost_source_field, "Our Cost")
    cost_discount_enabled = cost_enabled and bool(payload.get("cost_discount_enabled"))
    cost_discount_percent = _clean(payload.get("cost_discount_percent")) if cost_discount_enabled else ""
    if cost_discount_enabled:
        parsed_discount = _money(cost_discount_percent)
        if parsed_discount is None or parsed_discount < 0 or parsed_discount >= 100:
            raise PricingCenterError("Enter an additional Our Cost discount from 0 up to, but not including, 100%.")
    now = _now()
    group_name = _clean(payload.get("group_name")) if scope_type == "sku" else ""
    if scope_type == "sku" and not group_name:
        raise PricingCenterError("Choose the vendor or brand group for this SKU exception.")
    with store.connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO rules (id,name,scope_type,scope_value,method,amount,source_field,enabled,updated_at,group_name,cost_method,cost_amount,cost_source_field,cost_enabled,cost_discount_enabled,cost_discount_percent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rule_id, _clean(payload.get("name")) or f"{scope_value or 'Import'} pricing",
                scope_type, scope_value, method, amount, source_field,
                1 if payload.get("enabled", True) else 0, now, group_name,
                cost_method, cost_amount, cost_source_field, 1 if cost_enabled else 0,
                1 if cost_discount_enabled else 0, cost_discount_percent,
            ),
        )
    _mirror_database(store)
    return {"ok": True, "rule_id": rule_id}


def delete_rule(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    with store.connect() as db:
        changed = db.execute("DELETE FROM rules WHERE id=?", (_clean(payload.get("id")),)).rowcount
    _mirror_database(store)
    return {"ok": True, "deleted": bool(changed)}


def list_presets(paths: AppPaths) -> dict:
    rows = PricingStore(paths).list_rows("presets")
    for row in rows:
        row["mapping"] = json.loads(row.pop("mapping_json"))
        row["built_in"] = False
    built_ins = [
        {
            "id": template["id"], "name": template["name"], "vendor": template["vendor"],
            "file_type": template["file_type"], "candidate_label": template.get("candidate", ""),
            "mapping": {field: aliases[0] for field, aliases in template["mapping"].items()},
            "effective_date": template.get("effective_date", ""), "built_in": True,
        }
        for template in _BUILTIN_VENDOR_TEMPLATES
    ]
    return {"ok": True, "presets": [*built_ins, *rows]}


def save_preset(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    preset_id = _clean(payload.get("id")) or uuid.uuid4().hex
    mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else {}
    if not _clean(payload.get("name")) or not mapping.get("sku"):
        raise PricingCenterError("A preset needs a name and an SKU column mapping.")
    with store.connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO presets VALUES (?,?,?,?,?,?,?)",
            (
                preset_id, _clean(payload.get("name")), _clean(payload.get("vendor")),
                _clean(payload.get("file_type")), _clean(payload.get("candidate_label")),
                json.dumps(mapping), _now(),
            ),
        )
    _mirror_database(store)
    return {"ok": True, "preset_id": preset_id}


def _find_shopmonkey_header(rows: list[list[object]]) -> int:
    for index, row in enumerate(rows[:30]):
        normalized = {_key(cell) for cell in row}
        if "NAME" in normalized and "SHOPMONKEYIDOPTIONAL" in normalized:
            return index
    raise PricingCenterError("This does not look like a full Shopmonkey parts export.")


def upload_snapshot(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    filename, content = _decode_upload(payload)
    if Path(filename).suffix.lower() != ".xlsx":
        raise PricingCenterError("Upload the full Shopmonkey parts export as an .xlsx file.")
    snapshot_id = uuid.uuid4().hex
    source_path = store.root / "snapshots" / f"{snapshot_id}-{filename}"
    source_path.write_bytes(content)
    workbook = load_workbook(source_path, read_only=False, data_only=True)
    try:
        sheet = workbook.active
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    header_index = _find_shopmonkey_header(rows)
    headers = [_clean(value) or f"Column {index + 1}" for index, value in enumerate(rows[header_index])]
    width = len(headers)
    generation_date = ""
    for row in rows[:header_index]:
        for index, value in enumerate(row):
            if _key(value) == "GENERATIONDATE":
                generation_date = next(
                    (_clean(candidate) for candidate in row[index + 1:] if _clean(candidate)),
                    "",
                )
    records: list[dict] = []
    for raw in rows[header_index + 1:]:
        padded = (raw + [None] * (width - len(raw)))[:width]
        if not any(_clean(cell) for cell in padded):
            continue
        record = {headers[index]: padded[index] for index in range(width)}
        records.append(record)
    rows_path = store.root / "snapshots" / f"{snapshot_id}-rows.json"
    _json_write(rows_path, records)
    now = _now()
    with store.connect() as db:
        db.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
            (snapshot_id, filename, generation_date, json.dumps(headers), str(rows_path), len(records), "", now),
        )
    verified_runs = _verify_imported_runs(store, records)
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        source_path, f"Shopmonkey Baselines/{snapshot_id}-{filename}",
    )
    return {
        "ok": True, "snapshot_id": snapshot_id, "filename": filename,
        "generation_date": generation_date, "row_count": len(records),
        "created_at": now, "verified_runs": verified_runs,
    }


def _verify_imported_runs(store: PricingStore, inventory: list[dict]) -> int:
    """Verify unconfirmed bulk imports from the next full Shopmonkey export."""
    by_id = {_key(_field(row, "Shopmonkey ID")): row for row in inventory if _field(row, "Shopmonkey ID")}
    verified = 0
    with store.connect() as db:
        pending = [dict(row) for row in db.execute("SELECT * FROM runs WHERE status='imported_unverified'")]
        for run in pending:
            review = _json_read(run["review_path"])
            included = [row for row in review if row.get("included")]
            if not included or any(not row.get("shopmonkey_id") for row in included):
                continue
            matches = True
            for desired in included:
                observed = by_id.get(_key(desired["shopmonkey_id"]))
                if not observed or (
                    _money(_field(observed, "Cost")) != _money(desired.get("new_cost"))
                    or _money(_field(observed, "Retail")) != _money(desired.get("new_retail"))
                    or _clean(_field(observed, "Note")) != _clean(desired.get("new_note"))
                ):
                    matches = False
                    break
            if matches:
                db.execute("UPDATE runs SET status='verified' WHERE id=?", (run["id"],))
                verified += 1
    return verified


def _header(record: dict, prefix: str) -> str:
    wanted = _key(prefix)
    return next((name for name in record if _key(name).startswith(wanted)), "")


def _field(record: dict, prefix: str) -> object:
    name = _header(record, prefix)
    return record.get(name) if name else ""


def _select_rule(rules: list[dict], source: dict, session_id: str) -> dict | None:
    checks = (
        ("sku", _key(source.get("sku"))),
        ("brand", _catalog_scope_key(source.get("brand"))),
        ("vendor", _catalog_scope_key(source.get("vendor"))),
        ("session", _key(session_id)),
    )
    for scope_type, value in checks:
        for rule in rules:
            rule_value = _catalog_scope_key(rule["scope_value"]) if scope_type in {"brand", "vendor"} else _key(rule["scope_value"])
            if rule["enabled"] and rule["scope_type"] == scope_type and rule_value == value:
                return rule
    return None


def _select_cost_rule(rules: list[dict], source: dict, session_id: str) -> dict | None:
    checks = (
        ("brand", _catalog_scope_key(source.get("brand"))),
        ("vendor", _catalog_scope_key(source.get("vendor"))),
        ("session", _key(session_id)),
    )
    for scope_type, value in checks:
        for rule in rules:
            rule_value = _catalog_scope_key(rule["scope_value"]) if scope_type in {"brand", "vendor"} else _key(rule["scope_value"])
            if rule["enabled"] and rule.get("cost_enabled") and rule["scope_type"] == scope_type and rule_value == value:
                return rule
    return None


def _select_base_rule(rules: list[dict], source: dict, session_id: str) -> dict | None:
    """Select the broader brand/vendor/import rule without SKU exceptions."""
    checks = (
        ("brand", _catalog_scope_key(source.get("brand"))),
        ("vendor", _catalog_scope_key(source.get("vendor"))),
        ("session", _key(session_id)),
    )
    for scope_type, value in checks:
        for rule in rules:
            rule_value = _catalog_scope_key(rule["scope_value"]) if scope_type in {"brand", "vendor"} else _key(rule["scope_value"])
            if rule["enabled"] and rule["scope_type"] == scope_type and rule_value == value:
                return rule
    return None


def _selected_session_rule(rules: list[dict], source: dict, session: dict) -> dict | None:
    if not session.get("rule_override_set"):
        return _select_rule(rules, source, session["id"])
    override_id = _clean(session.get("rule_override_id"))
    if not override_id:
        return None
    sku_rule = next((
        rule for rule in rules
        if rule["enabled"] and rule["scope_type"] == "sku"
        and _key(rule["scope_value"]) == _key(source.get("sku"))
    ), None)
    return sku_rule or next((rule for rule in rules if rule["enabled"] and rule["id"] == override_id), None)


def _selected_session_cost_rule(rules: list[dict], source: dict, session: dict) -> dict | None:
    if not session.get("rule_override_set"):
        base_rule = _select_base_rule(rules, source, session["id"])
        return base_rule if base_rule and base_rule.get("cost_enabled") else None
    override_id = _clean(session.get("rule_override_id"))
    return next((
        rule for rule in rules
        if rule["enabled"] and rule.get("cost_enabled") and rule["id"] == override_id
    ), None)


def _calculate_rule_value(
    method: str,
    amount_value: object,
    source_field: str,
    source: dict,
    current_value: Decimal | None,
) -> Decimal | None:
    amount = _money(amount_value) or Decimal("0")
    cost = _money(source.get("cost"))
    msrp = _money(source.get("msrp"))
    if method == "markup_percent_cost":
        value = cost * (Decimal("1") + amount / Decimal("100")) if cost is not None else None
    elif method == "margin_percent_cost":
        denominator = Decimal("1") - amount / Decimal("100")
        value = cost / denominator if cost is not None and denominator > 0 else None
    elif method == "discount_percent_msrp":
        value = msrp * (Decimal("1") - amount / Decimal("100")) if msrp is not None else None
    elif method == "flat_markup_cost":
        value = cost + amount if cost is not None else None
    elif method == "flat_discount_msrp":
        value = msrp - amount if msrp is not None else None
    elif method == "markup_percent_source":
        source_value = _money(source.get(source_field or "agency_price"))
        value = source_value * (Decimal("1") + amount / Decimal("100")) if source_value is not None else None
    elif method == "flat_markup_source":
        source_value = _money(source.get(source_field or "agency_price"))
        value = source_value + amount if source_value is not None else None
    elif method == "imported_value":
        value = _money(source.get(source_field or "retail"))
    elif method == "fixed_retail":
        value = amount
    else:
        value = current_value
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if value is not None and value >= 0 else None


def calculate_retail(rule: dict, source: dict, current_retail: Decimal | None) -> Decimal | None:
    return _calculate_rule_value(
        rule["method"], rule.get("amount"), rule.get("source_field") or "retail", source, current_retail,
    )


def calculate_cost(rule: dict, source: dict, current_cost: Decimal | None) -> Decimal | None:
    value = _calculate_rule_value(
        rule.get("cost_method") or "imported_value",
        rule.get("cost_amount"), rule.get("cost_source_field") or "cost", source, current_cost,
    )
    if value is not None and rule.get("cost_discount_enabled"):
        discount = _money(rule.get("cost_discount_percent")) or Decimal("0")
        value = value * (Decimal("1") - discount / Decimal("100"))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if value is not None and value >= 0 else None


def _calculation_source_value(
    method: str, source_field: str, source: dict, current_value: Decimal | None,
) -> Decimal | None:
    if method in {"markup_percent_cost", "margin_percent_cost", "flat_markup_cost"}:
        return _money(source.get("cost"))
    if method in {"discount_percent_msrp", "flat_discount_msrp"}:
        return _money(source.get("msrp"))
    if method in {"markup_percent_source", "flat_markup_source", "imported_value"}:
        return _money(source.get(source_field))
    if method == "fixed_retail":
        return None
    return current_value


def _calculation_adjustment(
    method: str, amount_value: object, source_field: str, *, cost_discount: object = "",
) -> str:
    amount = _money(amount_value) or Decimal("0")
    compact = format(amount.normalize(), "f")
    if method == "markup_percent_cost" or method == "markup_percent_source":
        label = f"{compact}% markup"
    elif method == "margin_percent_cost":
        label = f"{compact}% margin"
    elif method == "discount_percent_msrp":
        label = f"{compact}% off"
    elif method == "flat_markup_cost" or method == "flat_markup_source":
        label = f"+${format(amount, '.2f')}"
    elif method == "flat_discount_msrp":
        label = f"-${format(amount, '.2f')}"
    elif method == "fixed_retail":
        label = "Fixed price"
    elif method == "imported_value":
        label = {
            "cost": "Use vendor-list cost",
            "msrp": "Use MSRP",
            "agency_price": "Use custom price",
        }.get(source_field, "Use listed price")
    else:
        label = "No adjustment"
    additional = _money(cost_discount)
    if additional is not None and additional > 0:
        label = f"{label}, then {format(additional.normalize(), 'f')}% off"
    return label


def _preview_rule(rule: dict) -> dict:
    keys = (
        "id", "name", "scope_type", "scope_value", "method", "amount", "source_field",
        "cost_enabled", "cost_method", "cost_amount", "cost_source_field",
        "cost_discount_enabled", "cost_discount_percent",
    )
    return {key: rule.get(key, "") for key in keys}


def _normalized_sources_with_price_repairs(store: PricingStore, session: dict) -> list[dict]:
    """Reload mapped prices from the preserved raw table after parser improvements."""
    mapping = json.loads(session.get("mapping_json") or "{}")
    matrix_path = session.get("matrix_path")
    candidates = _json_read(matrix_path) if matrix_path else []
    template = _builtin_template(
        session.get("filename", ""), session.get("vendor", ""),
        Path(session.get("filename", "")).suffix.lower(),
    )
    session_id = _clean(session.get("id"))
    parser_cache_key = f"{_ANYGLIDE_PARSER_VERSION}:{session_id}"
    if (
        template and template.get("id") == "anyglide-pdf"
        and not _reference_cache_exists(store, parser_cache_key)
        and Path(session.get("source_path") or "").is_file()
    ):
        candidates = _custom_template_candidates(
            Path(session["source_path"]), template["custom_parser"],
        )
        candidates, _template_mapping_result = _apply_template_candidate(template, candidates)
        _json_write(Path(session["matrix_path"]), candidates)
        selected_candidate = next(
            (item for item in candidates if item.get("id") == session.get("candidate_json")),
            candidates[0] if candidates else None,
        )
        if selected_candidate and mapping:
            indexes = {
                header: index
                for index, header in enumerate(selected_candidate.get("headers") or [])
            }
            inferred_brand = _clean(template.get("vendor"))
            rebuilt: list[dict] = []
            for row_number, raw_row in enumerate(
                selected_candidate.get("rows") or [],
                start=int(selected_candidate.get("header_row") or 1) + 1,
            ):
                row = {
                    field: _clean(raw_row[indexes[header]])
                    for field, header in mapping.items()
                    if header in indexes and indexes[header] < len(raw_row)
                }
                row["source_row"] = row_number
                if not row.get("sku") or _mapped_row_looks_like_header(row, mapping):
                    continue
                parsed_prices = {
                    field: _money(row.get(field))
                    for field in ("cost", "msrp", "agency_price")
                }
                if all(value is None for value in parsed_prices.values()):
                    continue
                row.update({field: _money_text(value) for field, value in parsed_prices.items()})
                row["vendor"] = row.get("vendor") or session.get("vendor", "")
                row["brand"] = row.get("brand") or inferred_brand
                row["effective_date"] = row.get("effective_date") or session.get("effective_date", "")
                rebuilt.append(row)
            normalized_path = Path(session["normalized_path"])
            _json_write(normalized_path, rebuilt)
            pricing_cloud_service.mirror_file_in_background(
                normalized_path, f"Vendor Sources/{session_id}-normalized.json",
            )
        with store.connect() as database:
            database.execute(
                "INSERT OR REPLACE INTO reference_cache VALUES (?,?,?)",
                (parser_cache_key, json.dumps({"row_count": len(rebuilt) if selected_candidate and mapping else 0}), _now()),
            )
        _mirror_database(store)
    sources = _json_read(session["normalized_path"])
    candidate = next(
        (item for item in candidates if item.get("id") == session.get("candidate_json")),
        None,
    )
    if not sources or not candidate or not mapping:
        return sources
    indexes = {header: index for index, header in enumerate(candidate.get("headers") or [])}
    changed = False
    for source in sources:
        try:
            raw_index = int(source.get("source_row")) - int(candidate.get("header_row") or 1) - 1
            raw_row = candidate["rows"][raw_index]
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        for field in ("cost", "msrp", "agency_price"):
            header = mapping.get(field)
            if not header or header not in indexes:
                continue
            parsed = _money(raw_row[indexes[header]] if indexes[header] < len(raw_row) else "")
            repaired = _money_text(parsed)
            if repaired and repaired != source.get(field):
                source[field] = repaired
                changed = True
    if changed:
        normalized_path = Path(session["normalized_path"])
        _json_write(normalized_path, sources)
        pricing_cloud_service.mirror_file_in_background(
            normalized_path, f"Vendor Sources/{session['id']}-normalized.json",
        )
    return sources


def rule_preview(paths: AppPaths, payload: dict) -> dict:
    """Save/resolve the import-level rule choice and return calculated examples."""
    store = PricingStore(paths)
    session = store.get("import_sessions", _clean(payload.get("session_id")))
    if not session or not session.get("normalized_path"):
        raise PricingCenterError("Confirm the price-list columns before choosing a pricing rule.")
    rules = store.list_rows("rules")
    if "choice" in payload:
        choice = _clean(payload.get("choice"))
        if choice == "auto":
            override_id, override_set = "", 0
        elif choice == "none":
            override_id, override_set = "", 1
        else:
            selected = next((rule for rule in rules if rule["id"] == choice and rule["enabled"] and rule["scope_type"] != "sku"), None)
            if not selected:
                raise PricingCenterError("Choose an available brand or vendor pricing rule.")
            override_id, override_set = selected["id"], 1
        with store.connect() as db:
            db.execute(
                "UPDATE import_sessions SET rule_override_id=?,rule_override_set=?,updated_at=? WHERE id=?",
                (override_id, override_set, _now(), session["id"]),
            )
        session = store.get("import_sessions", session["id"])
        _mirror_database(store)

    sources = _normalized_sources_with_price_repairs(store, session)
    example_search = _clean(payload.get("search")).lower()
    example_sources = [
        source for source in sources
        if not example_search or example_search in " ".join(
            _clean(source.get(field)).lower()
            for field in ("sku", "description", "brand", "vendor")
        )
    ]
    base_rules: list[dict] = []
    for source in sources:
        rule = _select_base_rule(rules, source, session["id"])
        if rule and all(existing["id"] != rule["id"] for existing in base_rules):
            base_rules.append(rule)
    if session.get("rule_override_set"):
        choice = session.get("rule_override_id") or "none"
    else:
        choice = "auto"
    auto_label = (
        base_rules[0]["name"] if len(base_rules) == 1
        else f"Automatic by brand/vendor ({len(base_rules)} rules)" if base_rules
        else "No matching rule"
    )
    if session.get("rule_override_set"):
        applied_rules = [
            rule for rule in rules
            if session.get("rule_override_id") and rule["id"] == session.get("rule_override_id")
        ]
    else:
        applied_rules = base_rules

    snapshot = store.latest("snapshots")
    examples: list[dict] = []
    if snapshot:
        inventory = _json_read(snapshot["rows_path"])
        by_id: dict[str, list[dict]] = defaultdict(list)
        by_brand_sku: dict[tuple[str, str], list[dict]] = defaultdict(list)
        by_vendor_sku: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in inventory:
            if sm_id := _key(_field(row, "Shopmonkey ID")):
                by_id[sm_id].append(row)
            if sku := _key(_field(row, "SKU")):
                by_brand_sku[(_catalog_scope_key(_field(row, "Brand")), sku)].append(row)
                by_vendor_sku[(_catalog_scope_key(_field(row, "Vendor")), sku)].append(row)
        matched: list[tuple[dict, dict]] = []
        unmatched: list[tuple[dict, dict]] = []
        for source in example_sources:
            candidates = by_id.get(_key(source.get("shopmonkey_id")), []) if source.get("shopmonkey_id") else []
            if not candidates and source.get("brand"):
                candidates = by_brand_sku.get((_catalog_scope_key(source.get("brand")), _key(source.get("sku"))), [])
            if not candidates and source.get("vendor"):
                candidates = by_vendor_sku.get((_catalog_scope_key(source.get("vendor")), _key(source.get("sku"))), [])
            pair = (source, candidates[0] if len(candidates) == 1 else {})
            if len(candidates) == 1:
                matched.append(pair)
            elif example_search or len(unmatched) < 3:
                unmatched.append(pair)
            if not example_search and len(matched) >= 3:
                break
        example_limit = 20 if example_search else 3
        for source, current in (matched + unmatched)[:example_limit]:
            current_cost = _money(_field(current, "Cost"))
            current_retail = _money(_field(current, "Retail"))
            rule = _selected_session_rule(rules, source, session)
            cost_rule = _selected_session_cost_rule(rules, source, session)
            imported_cost = _money(source.get("cost")) if source.get("cost") else current_cost
            new_cost = calculate_cost(cost_rule, source, current_cost) if cost_rule else imported_cost
            retail_source = {**source, "cost": _money_text(new_cost)}
            new_retail = calculate_retail(rule, retail_source, current_retail) if rule else None
            if cost_rule:
                cost_source = _calculation_source_value(
                    cost_rule.get("cost_method") or "imported_value",
                    cost_rule.get("cost_source_field") or "cost", source, current_cost,
                )
                cost_adjustment = _calculation_adjustment(
                    cost_rule.get("cost_method") or "imported_value",
                    cost_rule.get("cost_amount"), cost_rule.get("cost_source_field") or "cost",
                    cost_discount=(
                        cost_rule.get("cost_discount_percent")
                        if cost_rule.get("cost_discount_enabled") else ""
                    ),
                )
            else:
                cost_source = imported_cost
                cost_adjustment = "Use vendor-list cost" if source.get("cost") else "Keep current cost"
            retail_source_value = _calculation_source_value(
                rule["method"], rule.get("source_field") or "retail", retail_source, current_retail,
            ) if rule else current_retail
            retail_adjustment = _calculation_adjustment(
                rule["method"], rule.get("amount"), rule.get("source_field") or "retail",
            ) if rule else "No pricing rule"
            source_description = _clean(source.get("description"))
            shopmonkey_description = _clean(_field(current, "Name"))
            examples.append({
                "sku": source.get("sku", ""),
                "description": source_description or shopmonkey_description,
                "description_source": (
                    "vendor" if source_description else "shopmonkey" if shopmonkey_description else ""
                ),
                "current_cost": _money_text(current_cost), "new_cost": _money_text(new_cost),
                "current_retail": _money_text(current_retail), "new_retail": _money_text(new_retail),
                "cost_source_value": _money_text(cost_source), "cost_adjustment": cost_adjustment,
                "retail_source_value": _money_text(retail_source_value),
                "retail_adjustment": retail_adjustment,
                "rule_name": rule["name"] if rule else "No pricing rule", "matched": bool(current),
            })
    return {
        "ok": True, "choice": choice, "auto_label": auto_label,
        "options": [_preview_rule(rule) for rule in rules if rule["enabled"] and rule["scope_type"] != "sku"],
        "applied_rules": [_preview_rule(rule) for rule in applied_rules],
        "examples": examples, "example_search": example_search,
        "example_total": len(example_sources), "snapshot": _public_snapshot(snapshot),
    }


def _managed_note(existing: object, msrp: Decimal | None, effective_date: str, enabled: bool) -> str:
    note = _clean(existing)
    if not enabled:
        return note
    kept = [
        line for line in note.splitlines()
        if not re.match(r"^(MSRP|Price list effective):", line.strip(), flags=re.IGNORECASE)
    ]
    while kept and not kept[-1].strip():
        kept.pop()
    if msrp is not None:
        kept.append(f"MSRP: ${msrp:.2f}")
    if effective_date:
        kept.append(f"Price list effective: {effective_date}")
    return "\n".join(kept)


def reconcile(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    session = store.get("import_sessions", _clean(payload.get("session_id")))
    snapshot = store.get("snapshots", _clean(payload.get("snapshot_id"))) or store.latest("snapshots")
    if not session or not session["normalized_path"]:
        raise PricingCenterError("Confirm the price-list column assignments first.")
    if not snapshot:
        raise PricingCenterError("Upload a current full Shopmonkey parts export first.")
    latest_snapshot = store.latest("snapshots")
    if not latest_snapshot or latest_snapshot["id"] != snapshot["id"]:
        raise PricingCenterError("A newer Shopmonkey parts export is available. Run matching again with the current export.")
    if _snapshot_is_stale(snapshot):
        raise PricingCenterError("The Shopmonkey parts export is more than 24 hours old. Upload a current export before matching.")
    sources = _normalized_sources_with_price_repairs(store, session)
    inventory = _json_read(snapshot["rows_path"])
    rules = PricingStore(paths).list_rows("rules")
    by_id: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    by_brand_sku: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    by_vendor_sku: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    for index, row in enumerate(inventory):
        sm_id = _key(_field(row, "Shopmonkey ID"))
        sku = _key(_field(row, "SKU"))
        if sm_id:
            by_id[sm_id].append((index, row))
        if sku:
            by_brand_sku[(_catalog_scope_key(_field(row, "Brand")), sku)].append((index, row))
            by_vendor_sku[(_catalog_scope_key(_field(row, "Vendor")), sku)].append((index, row))
    review: list[dict] = []
    matched_inventory: set[int] = set()
    for source in sources:
        candidates = by_id.get(_key(source.get("shopmonkey_id")), []) if source.get("shopmonkey_id") else []
        method = "Shopmonkey ID"
        if not candidates and _key(source.get("brand")):
            candidates = by_brand_sku.get((_catalog_scope_key(source.get("brand")), _key(source.get("sku"))), [])
            method = "Brand + SKU"
        if not candidates and _key(source.get("vendor")):
            candidates = by_vendor_sku.get((_catalog_scope_key(source.get("vendor")), _key(source.get("sku"))), [])
            method = "Vendor + SKU"
        current_index, current = candidates[0] if len(candidates) == 1 else (-1, {})
        rule = _selected_session_rule(rules, source, session)
        cost_rule = _selected_session_cost_rule(rules, source, session)
        current_cost = _money(_field(current, "Cost"))
        current_retail = _money(_field(current, "Retail"))
        imported_cost = _money(source.get("cost")) if source.get("cost") else current_cost
        new_cost = calculate_cost(cost_rule, source, current_cost) if cost_rule else imported_cost
        retail_source = {**source, "cost": _money_text(new_cost)}
        new_retail = calculate_retail(rule, retail_source, current_retail) if rule else None
        note = _managed_note(
            _field(current, "Note"), _money(source.get("msrp")),
            source.get("effective_date") or session["effective_date"], bool(session["include_notes"]),
        )
        if len(candidates) == 1:
            matched_inventory.add(current_index)
        if len(candidates) > 1:
            status = "needs_review"
            reason = f"{len(candidates)} possible Shopmonkey matches"
        elif not candidates:
            status = "possible_new"
            reason = "No exact Shopmonkey match"
        elif cost_rule and new_cost is None:
            status = "needs_review"
            reason = "The Our Cost rule needs a missing source value"
        elif not rule:
            status = "needs_review"
            reason = "No applicable pricing rule"
        elif new_retail is None:
            status = "needs_review"
            reason = "The pricing rule needs a missing source value"
        else:
            changed = new_cost != current_cost or new_retail != current_retail or note != _clean(_field(current, "Note"))
            status = "updated" if changed else "unchanged"
            reason = method
        source_description = _clean(source.get("description"))
        shopmonkey_description = _clean(_field(current, "Name"))
        review.append({
            "id": uuid.uuid4().hex, "source": source, "inventory_index": current_index,
            "shopmonkey_id": _clean(_field(current, "Shopmonkey ID")),
            "sku": source.get("sku", ""),
            "description": source_description or shopmonkey_description,
            "description_source": (
                "vendor" if source_description else "shopmonkey" if shopmonkey_description else ""
            ),
            "brand": source.get("brand", ""), "vendor": source.get("vendor", ""),
            "current_cost": _money_text(current_cost), "new_cost": _money_text(new_cost),
            "current_retail": _money_text(current_retail), "new_retail": _money_text(new_retail),
            "new_note": note, "status": status, "reason": reason,
            "rule_id": rule["id"] if rule else "", "cost_rule_id": cost_rule["id"] if cost_rule else "",
            "approved_new": False, "included": status == "updated",
            "candidate_matches": [
                {
                    "inventory_index": index,
                    "shopmonkey_id": _clean(_field(candidate_row, "Shopmonkey ID")),
                    "sku": _clean(_field(candidate_row, "SKU")),
                    "brand": _clean(_field(candidate_row, "Brand")),
                    "vendor": _clean(_field(candidate_row, "Vendor")),
                    "name": _clean(_field(candidate_row, "Name")),
                    "cost": _money_text(_money(_field(candidate_row, "Cost"))),
                    "retail": _money_text(_money(_field(candidate_row, "Retail"))),
                }
                for index, candidate_row in candidates
            ] if len(candidates) > 1 else [],
        })
    run_id = uuid.uuid4().hex
    review_path = store.root / "reviews" / f"{run_id}.json"
    _json_write(review_path, review)
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs (id,session_id,snapshot_id,review_path,artifact_id,artifact_path,status,created_at,missing_count) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id, session["id"], snapshot["id"], str(review_path), "", "",
                "review", _now(), len(inventory) - len(matched_inventory),
            ),
        )
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        review_path, f"Runs/{run_id}-review.json",
    )
    return {"ok": True, "run_id": run_id, **_review_summary(review, len(inventory) - len(matched_inventory))}


def _review_summary(rows: list[dict], missing_count: int = 0) -> dict:
    counts = Counter(row["status"] for row in rows)
    brands: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        brands[row.get("brand") or "Unbranded"][row["status"]] += 1
    return {
        "counts": {key: counts.get(key, 0) for key in ("updated", "possible_new", "unchanged", "needs_review", "skipped")},
        "selected_count": sum(1 for row in rows if row.get("included")),
        "approved_new_count": sum(1 for row in rows if row.get("approved_new")),
        "missing_from_price_list": missing_count,
        "brands": [
            {"name": name, "new": count["possible_new"], "updated": count["updated"], "review": count["needs_review"]}
            for name, count in sorted(brands.items())
        ],
    }


def _filtered_review_rows(rows: list[dict], status: str, search: str) -> list[dict]:
    filtered = [row for row in rows if (not status or row["status"] == status)]
    if search:
        filtered = [
            row for row in filtered
            if search in " ".join(
                _clean(row.get(field)).lower()
                for field in ("sku", "brand", "vendor", "description", "shopmonkey_id")
            )
        ]
    return filtered


def _review_row_selectable(row: dict) -> bool:
    return row.get("status") in {"updated", "possible_new"}


def _review_row_selected(row: dict) -> bool:
    if row.get("status") == "possible_new":
        return bool(row.get("approved_new"))
    return bool(row.get("included"))


def get_review(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    rows = _json_read(run["review_path"])
    status = _clean(payload.get("status"))
    search = _clean(payload.get("search")).lower()
    filtered = _filtered_review_rows(rows, status, search)
    selectable = [row for row in filtered if _review_row_selectable(row)]
    page = max(1, int(payload.get("page") or 1))
    page_size = min(200, max(10, int(payload.get("page_size") or 50)))
    start = (page - 1) * page_size
    stored_snapshot = store.get("snapshots", run["snapshot_id"])
    snapshot = _public_snapshot(stored_snapshot)
    return {
        "ok": True, "run_id": run["id"], "session_id": run["session_id"],
        "rows": filtered[start:start + page_size],
        "total": len(filtered), "page": page, "page_size": page_size,
        "selectable_total": len(selectable),
        "selected_total": sum(1 for row in selectable if _review_row_selected(row)),
        "snapshot": snapshot, **_review_summary(rows, int(run.get("missing_count") or 0)),
    }


def update_review_row(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    rows = _json_read(run["review_path"])
    target = next((row for row in rows if row["id"] == _clean(payload.get("row_id"))), None)
    if not target:
        raise PricingCenterError("The selected review row was not found.")
    if "included" in payload:
        target["included"] = bool(payload["included"])
    if "approved_new" in payload:
        target["approved_new"] = bool(payload["approved_new"])
        target["included"] = bool(payload["approved_new"])
    if "skipped" in payload:
        if bool(payload["skipped"]):
            target["pre_skip_status"] = target.get("status", "needs_review")
            target["pre_skip_reason"] = target.get("reason", "Needs review")
            target["status"] = "skipped"
            target["reason"] = "Skipped by user"
            target["included"] = False
            target["approved_new"] = False
        elif target.get("status") == "skipped":
            target["status"] = target.pop("pre_skip_status", "needs_review")
            target["reason"] = target.pop("pre_skip_reason", "Needs review")
            target["included"] = False
    if "inventory_index" in payload:
        snapshot = store.get("snapshots", run["snapshot_id"])
        inventory = _json_read(snapshot["rows_path"])
        index = int(payload["inventory_index"])
        if index < 0 or index >= len(inventory):
            raise PricingCenterError("The selected Shopmonkey match is not valid.")
        conflict = next((
            row for row in rows
            if row["id"] != target["id"] and row.get("inventory_index") == index
            and row.get("status") != "skipped"
        ), None)
        if conflict:
            raise PricingCenterError(
                f"That Shopmonkey part is already matched to {conflict.get('sku') or 'another price-list row'}."
            )
        current = inventory[index]
        session = store.get("import_sessions", run["session_id"])
        rules = store.list_rows("rules")
        source = target["source"]
        rule = _selected_session_rule(rules, source, session)
        current_cost = _money(_field(current, "Cost"))
        current_retail = _money(_field(current, "Retail"))
        new_cost = _money(source.get("cost")) if source.get("cost") else current_cost
        new_retail = calculate_retail(rule, source, current_retail) if rule else None
        target["inventory_index"] = index
        target["shopmonkey_id"] = _clean(_field(current, "Shopmonkey ID"))
        source_description = _clean(source.get("description"))
        shopmonkey_description = _clean(_field(current, "Name"))
        target["description"] = source_description or shopmonkey_description
        target["description_source"] = (
            "vendor" if source_description else "shopmonkey" if shopmonkey_description else ""
        )
        target["current_cost"] = _money_text(current_cost)
        target["current_retail"] = _money_text(current_retail)
        target["new_cost"] = _money_text(new_cost)
        target["new_retail"] = _money_text(new_retail)
        target["new_note"] = _managed_note(
            _field(current, "Note"), _money(source.get("msrp")),
            source.get("effective_date") or session["effective_date"], bool(session["include_notes"]),
        )
        target["rule_id"] = rule["id"] if rule else ""
        target["candidate_matches"] = []
        target.pop("pre_skip_status", None)
        target.pop("pre_skip_reason", None)
        target["status"] = "updated" if rule and new_retail is not None else "needs_review"
        target["included"] = target["status"] == "updated"
        target["reason"] = "Manually matched" if target["included"] else "No applicable pricing rule"
    _json_write(Path(run["review_path"]), rows)
    pricing_cloud_service.mirror_file_in_background(
        Path(run["review_path"]), f"Runs/{run['id']}-review.json",
    )
    return {"ok": True, **_review_summary(rows)}


def bulk_update_review_rows(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    rows = _json_read(run["review_path"])
    status = _clean(payload.get("status"))
    search = _clean(payload.get("search")).lower()
    if status not in {"updated", "possible_new"}:
        raise PricingCenterError("Choose a selectable part view before using a bulk selection.")
    selected = bool(payload.get("selected"))
    targets = [
        row for row in _filtered_review_rows(rows, status, search)
        if _review_row_selectable(row)
    ]
    for row in targets:
        if row["status"] == "possible_new":
            row["approved_new"] = selected
        row["included"] = selected
    review_path = Path(run["review_path"])
    _json_write(review_path, rows)
    pricing_cloud_service.mirror_file_in_background(
        review_path, f"Runs/{run['id']}-review.json",
    )
    return {
        "ok": True, "updated_count": len(targets), "selected": selected,
        **_review_summary(rows, int(run.get("missing_count") or 0)),
    }


def update_review_settings(paths: AppPaths, payload: dict) -> dict:
    """Apply final-review note settings without rerunning part matching."""
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    session = store.get("import_sessions", run["session_id"])
    snapshot = store.get("snapshots", run["snapshot_id"])
    if not session or not snapshot:
        raise PricingCenterError("The saved import or Shopmonkey baseline is no longer available.")
    include_notes = bool(payload.get("include_notes"))
    inventory = _json_read(snapshot["rows_path"])
    rows = _json_read(run["review_path"])
    for row in rows:
        current = inventory[row["inventory_index"]] if 0 <= row.get("inventory_index", -1) < len(inventory) else {}
        source = row.get("source") or {}
        prior_status = row.get("status")
        row["new_note"] = _managed_note(
            _field(current, "Note"), _money(source.get("msrp")),
            source.get("effective_date") or session["effective_date"], include_notes,
        )
        if prior_status in {"updated", "unchanged"}:
            changed = (
                _money(row.get("new_cost")) != _money(row.get("current_cost"))
                or _money(row.get("new_retail")) != _money(row.get("current_retail"))
                or _clean(row.get("new_note")) != _clean(_field(current, "Note"))
            )
            row["status"] = "updated" if changed else "unchanged"
            if prior_status != row["status"]:
                row["included"] = row["status"] == "updated"
    _json_write(Path(run["review_path"]), rows)
    with store.connect() as db:
        db.execute("UPDATE import_sessions SET include_notes=?,updated_at=? WHERE id=?", (1 if include_notes else 0, _now(), session["id"]))
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        Path(run["review_path"]), f"Runs/{run['id']}-review.json",
    )
    return {"ok": True, "include_notes": include_notes, **_review_summary(rows, int(run.get("missing_count") or 0))}


def _write_export_file(path: Path, headers: list[str], records: list[dict]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for column, header in enumerate(headers, start=1):
        sheet.cell(1, column, header)
    for row_index, record in enumerate(records, start=2):
        for column, header in enumerate(headers, start=1):
            sheet.cell(row_index, column, record.get(header))
    workbook.save(path)


def create_export(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    snapshot = store.get("snapshots", run["snapshot_id"])
    latest = store.latest("snapshots")
    if not snapshot or not latest or latest["id"] != snapshot["id"]:
        raise PricingCenterError("A newer Shopmonkey parts export is available. Run matching again before exporting.")
    if _snapshot_is_stale(snapshot):
        raise PricingCenterError("The Shopmonkey parts export is more than 24 hours old. Upload a current export before exporting.")
    review = _json_read(run["review_path"])
    unresolved = [row for row in review if row["included"] and row["status"] == "needs_review"]
    if unresolved:
        raise PricingCenterError("Resolve included rows that still need review before exporting.")
    inventory = _json_read(snapshot["rows_path"])
    headers = json.loads(snapshot["headers_json"])
    records: list[dict] = []
    for row in review:
        if not row["included"]:
            continue
        if row["status"] == "possible_new" and not row["approved_new"]:
            continue
        if row["inventory_index"] >= 0:
            record = dict(inventory[row["inventory_index"]])
        else:
            record = {header: None for header in headers}
            record[_header(record, "Name") or headers[0]] = row["description"] or row["sku"]
            for prefix, value in (("SKU", row["sku"]), ("Part #", row["sku"]), ("Vendor", row["vendor"]), ("Brand", row["brand"])):
                if column := _header(record, prefix):
                    record[column] = value
        for prefix, value in (("Cost", row["new_cost"]), ("Retail", row["new_retail"]), ("Note", row["new_note"])):
            if column := _header(record, prefix):
                record[column] = float(value) if prefix != "Note" and value != "" else value
        records.append(record)
    if not records:
        raise PricingCenterError("No approved price changes are selected for export.")
    output_dir = store.root / "exports" / run["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, start in enumerate(range(0, len(records), EXPORT_ROW_LIMIT), start=1):
        suffix = f"-{index:02d}" if len(records) > EXPORT_ROW_LIMIT else ""
        path = output_dir / f"shopmonkey-pricing-import{suffix}.xlsx"
        _write_export_file(path, headers, records[start:start + EXPORT_ROW_LIMIT])
        files.append(path)
    if len(files) == 1:
        artifact_path = files[0]
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        artifact_path = output_dir / f"shopmonkey-pricing-import-{run['id'][:8]}.zip"
        with zipfile.ZipFile(artifact_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.name)
        mime = "application/zip"
    artifact_id = uuid.uuid4().hex
    with store.connect() as db:
        db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)", (artifact_id, str(artifact_path), mime, artifact_path.name, _now()))
        db.execute("UPDATE runs SET artifact_id=?,artifact_path=?,status=? WHERE id=?", (artifact_id, str(artifact_path), "exported", run["id"]))
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        artifact_path, f"Exports/{run['id']}/{artifact_path.name}",
    )
    return {
        "ok": True, "artifact_id": artifact_id, "filename": artifact_path.name,
        "row_count": len(records), "file_count": len(files),
        "download_url": f"/api/pricing/download/{artifact_id}",
    }


def create_bulk_export(paths: AppPaths, payload: dict) -> dict:
    """Combine all finalized vendor lists into one Shopmonkey import package."""
    mode = _clean(payload.get("mode")).lower()
    if mode not in {"all", "changed"}:
        raise PricingCenterError("Choose whether to export all finalized parts or only changed parts.")
    store = PricingStore(paths)
    snapshot = store.latest("snapshots")
    if not snapshot:
        raise PricingCenterError("Upload a current full Shopmonkey parts export first.")
    if _snapshot_is_stale(snapshot):
        raise PricingCenterError("The Shopmonkey parts export is more than 24 hours old. Upload a current export before exporting.")
    inventory = _json_read(snapshot["rows_path"])
    headers = json.loads(snapshot["headers_json"])
    completed_statuses = {"ready", "exported", "imported", "imported_unverified", "verified", "api_applied"}
    latest_by_session: dict[str, dict] = {}
    for run in store.list_rows("runs", "created_at DESC"):
        latest_by_session.setdefault(run["session_id"], run)
    runs = [run for run in latest_by_session.values() if run["status"] in completed_statuses]
    if not runs:
        raise PricingCenterError("Finish reviewing at least one vendor price list before creating a bulk export.")
    outdated = [run for run in runs if run["snapshot_id"] != snapshot["id"]]
    if outdated:
        sessions = {row["id"]: row for row in store.list_rows("import_sessions")}
        names = [
            _clean(sessions.get(run["session_id"], {}).get("vendor"))
            or _clean(sessions.get(run["session_id"], {}).get("filename"))
            or "an imported price list"
            for run in outdated
        ]
        display = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        raise PricingCenterError(
            f"Rematch {display} with the current Shopmonkey parts import first. "
            "Choose Continue import beside each list, review the refreshed matches, and finalize it again."
        )

    chosen: dict[str, dict] = {}
    for run in runs:
        for row in _json_read(run["review_path"]):
            include = bool(row.get("included")) or bool(row.get("approved_new"))
            if mode == "all" and row.get("status") == "unchanged":
                include = True
            if not include or row.get("status") == "needs_review":
                continue
            if row.get("status") == "possible_new" and not row.get("approved_new"):
                continue
            key = _key(row.get("shopmonkey_id")) or f"{_catalog_scope_key(row.get('vendor') or row.get('brand'))}:{_key(row.get('sku'))}"
            if key:
                chosen.setdefault(key, row)

    records: list[dict] = []
    for row in chosen.values():
        if row["inventory_index"] >= 0:
            record = dict(inventory[row["inventory_index"]])
        else:
            record = {header: None for header in headers}
            record[_header(record, "Name") or headers[0]] = row["description"] or row["sku"]
            for prefix, value in (("SKU", row["sku"]), ("Part #", row["sku"]), ("Vendor", row["vendor"]), ("Brand", row["brand"])):
                if column := _header(record, prefix):
                    record[column] = value
        for prefix, value in (("Cost", row["new_cost"]), ("Retail", row["new_retail"]), ("Note", row["new_note"])):
            if column := _header(record, prefix):
                record[column] = float(value) if prefix != "Note" and value != "" else value
        records.append(record)
    if not records:
        detail = "different from Shopmonkey" if mode == "changed" else "available in finalized price lists"
        raise PricingCenterError(f"No parts {detail} are ready for export.")

    export_id = uuid.uuid4().hex
    output_dir = store.root / "exports" / f"bulk-{export_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, start in enumerate(range(0, len(records), EXPORT_ROW_LIMIT), start=1):
        suffix = f"-{index:02d}" if len(records) > EXPORT_ROW_LIMIT else ""
        path = output_dir / f"shopmonkey-all-vendor-pricing{suffix}.xlsx"
        _write_export_file(path, headers, records[start:start + EXPORT_ROW_LIMIT])
        files.append(path)
    if len(files) == 1:
        artifact_path = files[0]
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        artifact_path = output_dir / f"shopmonkey-all-vendor-pricing-{export_id[:8]}.zip"
        with zipfile.ZipFile(artifact_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.name)
        mime = "application/zip"
    artifact_id = uuid.uuid4().hex
    with store.connect() as db:
        db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)", (artifact_id, str(artifact_path), mime, artifact_path.name, _now()))
        if mode == "all":
            for run in runs:
                status = run["status"] if run["status"] in {"imported", "verified", "api_applied"} else "exported"
                db.execute(
                    "UPDATE runs SET artifact_id=?,artifact_path=?,status=? WHERE id=?",
                    (artifact_id, str(artifact_path), status, run["id"]),
                )
    _mirror_database(store)
    pricing_cloud_service.mirror_file_in_background(
        artifact_path, f"Exports/Bulk/{artifact_path.name}",
    )
    return {
        "ok": True, "artifact_id": artifact_id, "filename": artifact_path.name,
        "row_count": len(records), "file_count": len(files), "mode": mode,
        "exported_list_count": len(runs) if mode == "all" else 0,
        "download_url": f"/api/pricing/download/{artifact_id}",
    }


def mark_imported(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run or run["status"] not in {"exported", "imported"}:
        raise PricingCenterError("Create the bulk-import file before marking it imported.")
    if run["status"] == "imported":
        return {"ok": True, "run_id": run["id"], "status": "imported"}
    with store.connect() as db:
        db.execute("UPDATE runs SET status='imported' WHERE id=?", (run["id"],))
        db.execute("UPDATE snapshots SET used_at=? WHERE id=?", (_now(), run["snapshot_id"]))
    _mirror_database(store)
    return {"ok": True, "run_id": run["id"], "status": "imported"}


def mark_all_imported(paths: AppPaths, _payload: dict) -> dict:
    """Confirm every currently exported vendor list was imported into Shopmonkey."""
    store = PricingStore(paths)
    latest_by_session: dict[str, dict] = {}
    for run in store.list_rows("runs", "created_at DESC"):
        latest_by_session.setdefault(run["session_id"], run)
    exported = [run for run in latest_by_session.values() if run["status"] == "exported"]
    if not exported:
        raise PricingCenterError("Export all vendor price lists before marking them imported.")
    imported_at = _now()
    with store.connect() as db:
        db.executemany("UPDATE runs SET status='imported' WHERE id=?", [(run["id"],) for run in exported])
        db.executemany(
            "UPDATE snapshots SET used_at=? WHERE id=?",
            [(imported_at, run["snapshot_id"]) for run in exported],
        )
    _mirror_database(store)
    return {"ok": True, "imported_count": len(exported), "status": "imported"}


def get_artifact(paths: AppPaths, artifact_id: str) -> tuple[bytes, str, str]:
    artifact = PricingStore(paths).get("artifacts", artifact_id)
    if not artifact:
        raise PricingCenterError("That export file is no longer available.")
    path = Path(artifact["path"])
    try:
        path.resolve().relative_to(PricingStore(paths).root.resolve())
    except ValueError as exc:
        raise PricingCenterError("The export path is invalid.") from exc
    return path.read_bytes(), artifact["mime"], artifact["filename"]


def api_plan(paths: AppPaths, payload: dict) -> dict:
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    if not run:
        raise PricingCenterError("This pricing review no longer exists.")
    rows = _json_read(run["review_path"])
    eligible = [row for row in rows if row["included"] and row["inventory_index"] >= 0 and row["status"] == "updated"]
    calls = len(eligible) * API_CALLS_PER_PART
    seconds = int((calls / API_REQUESTS_PER_MINUTE) * 60 + 0.999)
    return {
        "ok": True, "eligible_parts": len(eligible), "estimated_calls": calls,
        "estimated_seconds": seconds, "max_parts": API_MAX_PARTS,
        "allowed": 0 < len(eligible) <= API_MAX_PARTS,
        "reason": "" if 0 < len(eligible) <= API_MAX_PARTS else (
            "No existing-part updates are selected." if not eligible else "This would exceed the five-minute API limit. Use the bulk export."
        ),
    }


def _cents(value: object) -> int | None:
    money = _money(value)
    return int(money * 100) if money is not None else None


def _provider_call(operation, deadline: float):
    """Retry bounded Shopmonkey throttles without logging record contents."""
    for attempt in range(3):
        try:
            return operation()
        except ShopmonkeyApiError as exc:
            if exc.status_code != 429 or attempt == 2:
                raise
            wait = min(30, max(1, exc.retry_after))
            if time.monotonic() + wait >= deadline:
                raise PricingCenterError("The five-minute API window was reached. Remaining changes were not sent.") from exc
            time.sleep(wait)
    raise RuntimeError("unreachable")


def apply_api_updates(paths: AppPaths, payload: dict) -> dict:
    if _clean(payload.get("confirmation")) != "APPLY":
        raise PricingCenterError("Type APPLY to confirm the live Shopmonkey update.")
    plan = api_plan(paths, payload)
    if not plan["allowed"]:
        raise PricingCenterError(plan["reason"])
    store = PricingStore(paths)
    run = store.get("runs", _clean(payload.get("run_id")))
    snapshot = store.get("snapshots", run["snapshot_id"])
    latest = store.latest("snapshots")
    if not latest or latest["id"] != snapshot["id"]:
        raise PricingCenterError("A newer Shopmonkey parts export is available. Run matching again before applying API updates.")
    if _snapshot_is_stale(snapshot):
        raise PricingCenterError("The Shopmonkey parts export is more than 24 hours old. Upload a current export before applying API updates.")
    client = shopmonkey_service._client()  # Existing keychain-backed app connection.
    if client is None:
        raise PricingCenterError("Connect Shopmonkey in Settings before using API updates.")
    rows = _json_read(run["review_path"])
    inventory = _json_read(snapshot["rows_path"])
    selected = [row for row in rows if row["included"] and row["inventory_index"] >= 0 and row["status"] == "updated"]
    completed = 0
    conflicts: list[dict] = []
    interval = 60 / API_REQUESTS_PER_MINUTE
    deadline = time.monotonic() + API_MAX_MINUTES * 60
    for position, row in enumerate(selected):
        if time.monotonic() + (API_CALLS_PER_PART * interval) >= deadline:
            conflicts.extend({
                "sku": remaining["sku"], "shopmonkey_id": remaining["shopmonkey_id"],
                "reason": "Not sent because the five-minute API window was reached",
            } for remaining in selected[position:])
            break
        try:
            live = _provider_call(lambda: client.find_inventory_part(row["shopmonkey_id"]), deadline)
        except (ShopmonkeyApiError, PricingCenterError):
            conflicts.extend({
                "sku": remaining["sku"], "shopmonkey_id": remaining["shopmonkey_id"],
                "reason": "Not sent because Shopmonkey stopped responding",
            } for remaining in selected[position:])
            break
        if (
            live.get("wholesaleCostCents") != _cents(row["current_cost"])
            or live.get("retailCostCents") != _cents(row["current_retail"])
            or _clean(live.get("note")) != _clean(_field(inventory[row["inventory_index"]], "Note"))
        ):
            conflicts.append({"sku": row["sku"], "shopmonkey_id": row["shopmonkey_id"], "reason": "Shopmonkey changed after the baseline export"})
            continue
        time.sleep(interval)
        try:
            _provider_call(lambda: client.update_inventory_part(
                row["shopmonkey_id"], wholesale_cost_cents=_cents(row["new_cost"]),
                retail_cost_cents=_cents(row["new_retail"]), note=row["new_note"],
            ), deadline)
            time.sleep(interval)
            verify = _provider_call(lambda: client.find_inventory_part(row["shopmonkey_id"]), deadline)
        except (ShopmonkeyApiError, PricingCenterError):
            conflicts.append({
                "sku": row["sku"], "shopmonkey_id": row["shopmonkey_id"],
                "reason": "The update could not be confirmed; verify this part in Shopmonkey",
            })
            conflicts.extend({
                "sku": remaining["sku"], "shopmonkey_id": remaining["shopmonkey_id"],
                "reason": "Not sent after the prior update could not be confirmed",
            } for remaining in selected[position + 1:])
            break
        if verify.get("wholesaleCostCents") == _cents(row["new_cost"]) and verify.get("retailCostCents") == _cents(row["new_retail"]) and _clean(verify.get("note")) == _clean(row["new_note"]):
            completed += 1
        else:
            conflicts.append({"sku": row["sku"], "shopmonkey_id": row["shopmonkey_id"], "reason": "Readback did not match the requested update"})
        time.sleep(interval)
    with store.connect() as db:
        db.execute("UPDATE snapshots SET used_at=? WHERE id=?", (_now(), snapshot["id"]))
        db.execute("UPDATE runs SET status=? WHERE id=?", ("api_applied", run["id"]))
    _mirror_database(store)
    return {
        "ok": True,
        "fully_applied": not conflicts,
        "completed": completed,
        "conflicts": conflicts,
        "requested": len(selected),
    }


def _price_list_part_index(store: PricingStore) -> tuple[dict, list[dict]]:
    """Return compact list statistics and the newest copy of each vendor/SKU."""
    sessions = store.list_rows("import_sessions", "updated_at DESC")
    unique: dict[str, dict] = {}
    total_parts = 0
    lists_with_parts = 0
    for session in sessions:
        normalized_path = _clean(session.get("normalized_path"))
        if not normalized_path or not Path(normalized_path).is_file():
            continue
        rows = _json_read(normalized_path)
        if not isinstance(rows, list) or not rows:
            continue
        lists_with_parts += 1
        total_parts += len(rows)
        for source in rows:
            sku = _key(source.get("sku"))
            scope = _catalog_scope_key(source.get("vendor") or source.get("brand") or session.get("vendor"))
            if not sku:
                continue
            key = f"{scope}:{sku}"
            unique.setdefault(key, {
                "session_id": _clean(session.get("id")),
                "sku": _clean(source.get("sku")),
                "description": _clean(source.get("description")),
                "brand": _clean(source.get("brand")),
                "vendor": _clean(source.get("vendor") or session.get("vendor")),
                "shopmonkey_id": _clean(source.get("shopmonkey_id")),
                "effective_date": _clean(source.get("effective_date") or session.get("effective_date")),
                "source_file": _clean(session.get("filename")),
            })
    return {
        "price_list_count": lists_with_parts,
        "total_parts": total_parts,
        "unique_parts": len(unique),
    }, list(unique.values())


def inventory_coverage(paths: AppPaths, payload: dict) -> dict:
    """Show which Shopmonkey inventory parts are absent from every vendor list."""
    store = PricingStore(paths)
    list_stats, parts = _price_list_part_index(store)
    snapshot = store.latest("snapshots")
    inventory = _json_read(snapshot["rows_path"]) if snapshot else []
    latest_runs: dict[str, dict] = {}
    for run in store.list_rows("runs", "created_at DESC"):
        latest_runs.setdefault(run["session_id"], run)
    manually_matched_inventory: set[int] = set()
    if snapshot:
        for run in latest_runs.values():
            if run.get("snapshot_id") != snapshot["id"] or not Path(run.get("review_path") or "").is_file():
                continue
            for row in _json_read(run["review_path"]):
                inventory_index = row.get("inventory_index")
                if isinstance(inventory_index, int) and inventory_index >= 0:
                    manually_matched_inventory.add(inventory_index)
    by_id: dict[str, list[dict]] = defaultdict(list)
    by_brand_sku: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_vendor_sku: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for part in parts:
        shopmonkey_id = _key(part.get("shopmonkey_id"))
        sku = _key(part.get("sku"))
        if shopmonkey_id:
            by_id[shopmonkey_id].append(part)
        if sku:
            by_brand_sku[(_catalog_scope_key(part.get("brand")), sku)].append(part)
            by_vendor_sku[(_catalog_scope_key(part.get("vendor")), sku)].append(part)

    matched = 0
    unmatched: list[dict] = []
    for inventory_index, row in enumerate(inventory):
        if inventory_index in manually_matched_inventory:
            matched += 1
            continue
        shopmonkey_id = _clean(_field(row, "Shopmonkey ID"))
        sku = _clean(_field(row, "SKU"))
        brand = _clean(_field(row, "Brand"))
        vendor = _clean(_field(row, "Vendor"))
        candidates = by_id.get(_key(shopmonkey_id), []) if shopmonkey_id else []
        if not candidates and brand:
            candidates = by_brand_sku.get(
                (_catalog_scope_key(brand), _key(sku)), [],
            )
        if not candidates and vendor:
            candidates = by_vendor_sku.get(
                (_catalog_scope_key(vendor), _key(sku)), [],
            )
        if candidates:
            matched += 1
            continue
        unmatched.append({
            "sku": sku,
            "description": _clean(_field(row, "Name")),
            "brand": brand,
            "vendor": vendor,
            "shopmonkey_id": shopmonkey_id,
            "cost": _money_text(_money(_field(row, "Cost"))),
            "retail": _money_text(_money(_field(row, "Retail"))),
            "reason": "Not found in imported price lists",
        })

    brand_counts = Counter(_clean(part.get("brand")) or "Unbranded" for part in unmatched)
    brand_filter = _clean(payload.get("brand"))
    search = _clean(payload.get("search")).lower()
    filtered = [
        part for part in unmatched
        if (
            not brand_filter
            or (brand_filter == "__unbranded__" and not _clean(part.get("brand")))
            or _catalog_scope_key(part.get("brand")) == _catalog_scope_key(brand_filter)
        ) and (
            not search or search in " ".join(
                _clean(part.get(field)).lower()
                for field in ("sku", "description", "brand", "vendor", "shopmonkey_id", "reason")
            )
        )
    ]
    page = max(1, int(payload.get("page") or 1))
    page_size = min(100, max(10, int(payload.get("page_size") or 20)))
    start = (page - 1) * page_size
    return {
        "ok": True,
        "snapshot": _public_snapshot(snapshot),
        "stats": {
            **list_stats,
            "shopmonkey_parts": len(inventory),
            "matched_parts": matched,
            "unmatched_parts": len(unmatched),
        },
        "rows": filtered[start:start + page_size],
        "brands": [
            {
                "name": name,
                "value": "__unbranded__" if name == "Unbranded" else name,
                "count": count,
            }
            for name, count in sorted(brand_counts.items(), key=lambda item: item[0].lower())
        ],
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
    }


def summary(paths: AppPaths) -> dict:
    store = PricingStore(paths)
    latest_snapshot = store.latest("snapshots")
    latest_run = store.latest("runs")
    rules = store.list_rows("rules")
    sessions = store.list_rows("import_sessions")
    price_list_stats, _price_list_parts = _price_list_part_index(store)
    def public_run(row: dict | None) -> dict | None:
        if not row:
            return None
        return {key: row[key] for key in ("id", "session_id", "snapshot_id", "artifact_id", "status", "created_at", "missing_count")}

    run_rows = store.list_rows("runs", "created_at DESC")
    latest_runs: dict[str, dict] = {}
    for row in run_rows:
        latest_runs.setdefault(row["session_id"], row)

    def applied_rule_ids(session: dict) -> list[str]:
        if session.get("rule_override_set"):
            override_id = _clean(session.get("rule_override_id"))
            return [override_id] if override_id and any(rule["id"] == override_id for rule in rules) else []
        sources: list[dict] = []
        if session.get("normalized_path") and Path(session["normalized_path"]).is_file():
            sources = _json_read(session["normalized_path"])
        if not sources:
            sources = [{"vendor": session.get("vendor"), "brand": ""}]
        ids: list[str] = []
        for source in sources:
            checks = (
                ("brand", _catalog_scope_key(source.get("brand"))),
                ("vendor", _catalog_scope_key(source.get("vendor") or session.get("vendor"))),
                ("session", _key(session["id"])),
            )
            selected = next((
                rule for scope_type, value in checks for rule in rules
                if rule["enabled"] and rule["scope_type"] == scope_type
                and (_catalog_scope_key(rule["scope_value"]) if scope_type in {"brand", "vendor"} else _key(rule["scope_value"])) == value
            ), None)
            if selected and selected["id"] not in ids:
                ids.append(selected["id"])
        return ids

    completed_statuses = {"ready", "exported", "imported", "imported_unverified", "verified", "api_applied"}
    def public_session(row: dict) -> dict:
        result = {key: row[key] for key in ("id", "vendor", "effective_date", "filename", "status", "created_at", "updated_at")}
        run = latest_runs.get(row["id"])
        rule_ids = applied_rule_ids(row)
        needs_rematch = bool(
            run and (
                (latest_snapshot and run["snapshot_id"] != latest_snapshot["id"])
                or run["status"] == "source_changed"
            )
        )
        result.update({
            "applied_rule_ids": rule_ids,
            "run_id": run["id"] if run else "",
            "run_status": run["status"] if run else "",
            "can_export": bool(run and run["status"] in completed_statuses and not needs_rematch),
            "continue_import": not bool(run and run["status"] in completed_statuses and not needs_rematch),
            "needs_rematch": needs_rematch,
            "artifact_id": run["artifact_id"] if run else "",
            "download_url": f"/api/pricing/download/{run['artifact_id']}" if run and run["artifact_id"] else "",
        })
        artifact = store.get("artifacts", run["artifact_id"]) if run and run["artifact_id"] else None
        result["artifact_filename"] = artifact["filename"] if artifact else ""
        normalized_path = _clean(row.get("normalized_path"))
        result["part_count"] = (
            len(_json_read(normalized_path))
            if normalized_path and Path(normalized_path).is_file()
            else 0
        )
        return result

    return {
        "ok": True,
        "snapshot": _public_snapshot(latest_snapshot),
        "latest_run": public_run(latest_run),
        "rule_count": len([row for row in rules if row["scope_type"] != "sku"]),
        "exception_count": len([row for row in rules if row["scope_type"] == "sku"]),
        "preset_count": len(_BUILTIN_VENDOR_TEMPLATES) + len(store.list_rows("presets")),
        "price_list_stats": price_list_stats,
        "sessions": [public_session(row) for row in sessions],
        "runs": [public_run(row) for row in run_rows],
        "api_max_parts": API_MAX_PARTS,
    }
