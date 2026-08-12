from __future__ import annotations

from dataclasses import dataclass, field

from .project_models import EquipmentPreferences


CUSTOMER_PROFILE_FIELDS = (
    "name",
    "contact_name",
    "contact_title",
    "contact_phone",
    "contact_email",
    "mobile_phone",
    "fax",
    "website",
    "bill_address_line1",
    "bill_address_line2",
    "bill_address_line3",
    "bill_city",
    "bill_state",
    "bill_postal_code",
    "bill_country",
    "ship_address_line1",
    "ship_address_line2",
    "ship_address_line3",
    "ship_city",
    "ship_state",
    "ship_postal_code",
    "ship_country",
    "notes",
    "taxable",
)

# This is deliberately the practical information DTM needs before it can
# safely prepare a customer-facing estimate. QuickBooks itself only requires a
# DisplayName, but estimates should never be created for an uncontactable,
# unbillable customer record.
REQUIRED_ESTIMATE_CUSTOMER_FIELDS = (
    "name",
    "contact_name",
    "contact_email",
    "contact_phone",
    "bill_address_line1",
    "bill_city",
    "bill_state",
    "bill_postal_code",
)

CUSTOMER_FIELD_LABELS = {
    "name": "Agency name",
    "contact_name": "Contact name",
    "contact_email": "Contact email",
    "contact_phone": "Primary phone",
    "bill_address_line1": "Billing address",
    "bill_city": "Billing city",
    "bill_state": "Billing state/province",
    "bill_postal_code": "Billing postal code",
}


@dataclass
class AgencyRecord:
    agency_id: str
    name: str
    contact_name: str = ""
    contact_title: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    mobile_phone: str = ""
    fax: str = ""
    website: str = ""
    bill_address_line1: str = ""
    bill_address_line2: str = ""
    bill_address_line3: str = ""
    bill_city: str = ""
    bill_state: str = ""
    bill_postal_code: str = ""
    bill_country: str = ""
    ship_address_line1: str = ""
    ship_address_line2: str = ""
    ship_address_line3: str = ""
    ship_city: str = ""
    ship_state: str = ""
    ship_postal_code: str = ""
    ship_country: str = ""
    notes: str = ""
    taxable: bool = False
    customer_since: str = ""
    # These are the agency's normal equipment choices.  New projects copy
    # them once; a project can then keep a different choice for an exception.
    default_preferences: EquipmentPreferences = field(default_factory=EquipmentPreferences)
    # Sparse manufacturer_id → discount-percent exceptions. Missing entries
    # continue to inherit the shared Default customer-pricing rule.
    pricing_overrides: dict[str, float] = field(default_factory=dict)
    qb_customer_id: str = ""   # FK → QuickBooks Customer.Id (empty = not linked)
    created_at: str = ""
    updated_at: str = ""
