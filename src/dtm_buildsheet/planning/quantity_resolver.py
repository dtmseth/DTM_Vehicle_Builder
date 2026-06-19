from __future__ import annotations


def apply_quantity_rules(spec: dict, ordered_quantity: int) -> dict:
    """Return the first quantity_rules entry whose qty matches ordered_quantity."""
    for rule in spec.get("quantity_rules", []):
        if rule.get("qty") == ordered_quantity:
            return dict(rule)
    return {}


def apply_quantity_rules_list(rules: list, ordered_quantity: int) -> dict:
    """Same as apply_quantity_rules but takes the rules list directly."""
    for rule in (rules or []):
        if rule.get("qty") == ordered_quantity:
            return dict(rule)
    return {}
