"""Canonical agency abbreviations used by project and file identity."""
from __future__ import annotations

import re


_ACRONYM_STOP_WORDS = {"and", "of", "the"}


def clean_agency_abbreviation(value: object) -> str:
    """Return a compact user-authored abbreviation safe for visible paths."""
    cleaned = re.sub(r"[~\"#%*:<>?/\\{|}]+", " ", str(value or ""))
    return " ".join(cleaned.split()).strip(" .")[:40]


def default_agency_abbreviation(name: object) -> str:
    """Derive the editable default abbreviation for an agency name.

    County sheriff agencies use the readable county name. A short explicit
    parenthetical acronym is honored for names such as ICE and HSI. Other
    names use the first character of each meaningful word.
    """
    value = " ".join(str(name or "").split()).strip()
    if not value:
        return ""

    county = re.match(
        r"^(?P<county>.+?)\s+county\b.*\bsheriff(?:'s|s)?\b",
        value,
        flags=re.IGNORECASE,
    )
    if county:
        return clean_agency_abbreviation(county.group("county"))

    parenthetical = re.findall(r"\(([^()]*)\)", value)
    if parenthetical:
        candidate = clean_agency_abbreviation(parenthetical[-1])
        compact = re.sub(r"[^A-Za-z0-9]", "", candidate)
        if 2 <= len(compact) <= 10 and candidate.upper() == candidate:
            return compact.upper()

    words = [
        word for word in re.findall(r"[A-Za-z0-9]+", value)
        if word.casefold() not in _ACRONYM_STOP_WORDS
    ]
    if len(words) == 1 and words[0].isupper() and 2 <= len(words[0]) <= 10:
        return clean_agency_abbreviation(words[0])
    initials = "".join(word[0] for word in words).upper()
    return clean_agency_abbreviation(initials)


def effective_agency_abbreviation(abbreviation: object, name: object) -> str:
    return clean_agency_abbreviation(abbreviation) or default_agency_abbreviation(name)
