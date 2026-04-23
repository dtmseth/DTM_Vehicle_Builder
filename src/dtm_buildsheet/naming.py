from __future__ import annotations

import re


CANONICAL_NAME_FIXES = {
    "Light Controler": "Light Controller",
    "GPD W/ Extention": "GPD W/ Extension",
    "SPECIFY LICATION": "Specify Location",
}


def canonical_name(value: str) -> str:
    return CANONICAL_NAME_FIXES.get(value, value)


def safe_project_id(value: str, fallback: str = "PROJECT") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or fallback
