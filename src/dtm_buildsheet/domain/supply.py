"""Canonical part-supply vocabulary with legacy New/Used/Reused compatibility.

The application historically used ``new_or_used`` for both ownership and
condition, plus ``source`` only for some Reused rows.  Keep those fields during
the compatibility window, but make every new consumer reason from the three
unambiguous fields returned here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SUPPLY_NEW = "new"
SUPPLY_CUSTOMER = "customer_supplied"
CONDITION_NEW = "new"
CONDITION_USED = "used"

_LEGACY_NEW = {"", "new", "n"}
_LEGACY_CUSTOMER = {"used", "u", "reused", "r", "transfer", "transferred"}
_SUPPLY_KEYS = {"supply_type", "customer_condition", "customer_source", "new_or_used", "source"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _get(record: Mapping[str, Any] | object, name: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


@dataclass(frozen=True)
class SupplyState:
    supply_type: str
    customer_condition: str
    customer_source: str

    @property
    def is_customer_supplied(self) -> bool:
        return self.supply_type == SUPPLY_CUSTOMER

    @property
    def is_billable(self) -> bool:
        return self.supply_type == SUPPLY_NEW

    @property
    def source_needed(self) -> bool:
        return (
            self.supply_type == SUPPLY_CUSTOMER
            and self.customer_condition == CONDITION_USED
            and not self.customer_source
        )

    @property
    def label(self) -> str:
        if self.supply_type == SUPPLY_NEW:
            return "New"
        condition = (
            "New" if self.customer_condition == CONDITION_NEW
            else "Used" if self.customer_condition == CONDITION_USED
            else "Condition needed"
        )
        suffix = f" · {self.customer_source}" if self.customer_source else ""
        if self.source_needed:
            suffix = " · Source needed"
        return f"Customer supplied / {condition}{suffix}"


def supply_state(record: Mapping[str, Any] | object) -> SupplyState:
    """Return canonical supply meaning from a current or legacy record."""
    legacy = _text(_get(record, "new_or_used")).casefold()
    requested_type = _text(_get(record, "supply_type")).casefold().replace("-", "_").replace(" ", "_")
    if requested_type in {SUPPLY_NEW, "dtm", "dtm_supplied"}:
        supply_type = SUPPLY_NEW
    elif requested_type in {SUPPLY_CUSTOMER, "customer", "customer_owned"}:
        supply_type = SUPPLY_CUSTOMER
    else:
        supply_type = SUPPLY_CUSTOMER if legacy in _LEGACY_CUSTOMER else SUPPLY_NEW

    requested_condition = _text(_get(record, "customer_condition")).casefold()
    if supply_type == SUPPLY_CUSTOMER:
        if requested_condition in {CONDITION_NEW, CONDITION_USED}:
            condition = requested_condition
        elif legacy in _LEGACY_CUSTOMER:
            condition = CONDITION_USED
        else:
            condition = ""
    else:
        condition = ""

    source = _text(_get(record, "customer_source"))
    if not source and supply_type == SUPPLY_CUSTOMER:
        source = _text(_get(record, "source"))
    return SupplyState(supply_type, condition, source)


def legacy_fields_for(state: SupplyState, *, prior_status: Any = "", prior_source: Any = "") -> tuple[str, str]:
    """Return compatibility values for old consumers and workbook columns."""
    if state.supply_type == SUPPLY_NEW:
        prior = _text(prior_status)
        return (prior if prior and prior.casefold() in _LEGACY_NEW else "New"), _text(prior_source)
    prior = _text(prior_status)
    status = prior if prior.casefold() in _LEGACY_CUSTOMER else "Used"
    return status, state.customer_source


def normalized_supply_fields(record: Mapping[str, Any] | object) -> dict[str, str]:
    """Return canonical fields plus synchronized legacy compatibility fields."""
    state = supply_state(record)
    legacy_status, legacy_source = legacy_fields_for(
        state,
        prior_status=_get(record, "new_or_used"),
        prior_source=_get(record, "source"),
    )
    return {
        "supply_type": state.supply_type,
        "customer_condition": state.customer_condition,
        "customer_source": state.customer_source,
        "new_or_used": legacy_status,
        "source": legacy_source,
    }


def normalize_supply_dict(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a JSON-shaped record and add its canonical/legacy supply fields."""
    result = dict(record)
    result.update(normalized_supply_fields(record))
    return result


def normalize_component_supply_dict(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a component that already declares supply; leave neutral SKU rows alone."""
    if not _SUPPLY_KEYS.intersection(record):
        return dict(record)
    return normalize_supply_dict(record)


def supply_validation_error(record: Mapping[str, Any] | object) -> str:
    """Return a user-facing completeness error for an explicit supply choice."""
    state = supply_state(record)
    if state.supply_type != SUPPLY_CUSTOMER:
        return ""
    if state.customer_condition not in {CONDITION_NEW, CONDITION_USED}:
        return "Choose whether the customer-supplied part is New or Used"
    if state.customer_condition == CONDITION_USED and not state.customer_source:
        return "Enter where the customer-supplied used part will come from"
    return ""
