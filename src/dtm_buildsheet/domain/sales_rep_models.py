from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SalesRepRecord:
    rep_id: str
    name: str
    phone: str = ""
    email: str = ""
    created_at: str = ""
    updated_at: str = ""
