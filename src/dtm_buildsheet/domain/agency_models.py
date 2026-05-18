from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgencyRecord:
    agency_id: str
    name: str
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    customer_since: str = ""
    created_at: str = ""
    updated_at: str = ""
