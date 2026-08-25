from __future__ import annotations
import pytest

from dtm_buildsheet.domain.supply import (
    normalize_component_supply_dict,
    normalized_supply_fields,
    supply_state,
    supply_validation_error,
)


@pytest.mark.parametrize(
    ("legacy", "expected_type", "expected_condition"),
    [
        ("", "new", ""),
        ("New", "new", ""),
        ("Used", "customer_supplied", "used"),
        ("Reused", "customer_supplied", "used"),
    ],
)
def test_legacy_supply_mapping(legacy, expected_type, expected_condition):
    state = supply_state({"new_or_used": legacy})
    assert (state.supply_type, state.customer_condition) == (
        expected_type, expected_condition,
    )


def test_explicit_customer_new_is_non_billable_and_keeps_source():
    state = supply_state({
        "supply_type": "customer_supplied",
        "customer_condition": "new",
        "customer_source": "Agency stock",
    })
    assert state.is_customer_supplied is True
    assert state.is_billable is False
    assert state.label == "Customer supplied / New · Agency stock"


def test_source_less_legacy_used_remains_readable_and_flagged():
    fields = normalized_supply_fields({"new_or_used": "Reused"})
    assert fields["supply_type"] == "customer_supplied"
    assert fields["customer_condition"] == "used"
    assert supply_state(fields).label == "Customer supplied / Used · Source needed"


def test_explicit_customer_used_requires_source():
    error = supply_validation_error({
        "supply_type": "customer_supplied",
        "customer_condition": "used",
    })
    assert error == "Enter where the customer-supplied used part will come from"


def test_customer_condition_is_required_for_customer_supply():
    error = supply_validation_error({"supply_type": "customer_supplied"})
    assert error == "Choose whether the customer-supplied part is New or Used"


def test_neutral_component_is_not_given_supply_fields():
    component = {"label": "Mounting location", "detail": "Upper grille"}
    assert normalize_component_supply_dict(component) == component
