"""Small conditional metadata port. Never use upsert or wildcard ETags."""
from __future__ import annotations

import json
import re
from itertools import islice
from dataclasses import dataclass
from typing import Protocol


class Conflict(Exception):
    """Reload/review required; never retry a business mutation blindly."""


@dataclass(frozen=True)
class Versioned:
    value: dict
    etag: str


class MetadataStore(Protocol):
    def read(self, partition: str, key: str) -> Versioned | None: ...
    def write(self, partition: str, key: str, value: dict, *, expected: str | None) -> str: ...


def scan_bounds(prefix, after, limit):
    if (not re.fullmatch(r"[a-z0-9-]*", prefix) or not re.fullmatch(r"[a-z0-9-]*", after)
            or not 1 <= limit <= 1000):
        raise ValueError("Invalid metadata scan bounds")
    return prefix + "~"


class AzureTableMetadata:
    """One JSON entity per logical operation; externally provisioned table only.

    Small bounded queue snapshots fit one entity, so enqueue/lease/checkpoint and
    their audit transitions are atomic without a cross-table transaction.
    Constructor takes an SDK TableClient authenticated by managed identity.
    """

    def __init__(self, client):
        self.client = client

    def read(self, partition, key):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            row = self.client.get_entity(partition_key=partition, row_key=key)
        except ResourceNotFoundError:
            return None
        return Versioned(json.loads(row["Payload"]), row.metadata["etag"])

    def scan(self, partition, prefix, *, after="", limit=100):
        upper = scan_bounds(prefix, after, limit)
        rows = self.client.query_entities(
            "PartitionKey eq @tenant and RowKey ge @prefix and RowKey lt @upper and RowKey gt @after",
            parameters={"tenant": partition, "prefix": prefix, "upper": upper, "after": after},
            results_per_page=limit,
        )
        return [(row["RowKey"], Versioned(json.loads(row["Payload"]), row.metadata["etag"]))
                for row in islice(rows, limit)]

    def delete(self, partition, key, *, expected):
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        if not expected or expected == "*":
            raise ValueError("An exact ETag is required")
        try:
            self.client.delete_entity(partition_key=partition, row_key=key, etag=expected,
                                      match_condition=MatchConditions.IfNotModified)
        except (ResourceModifiedError, ResourceNotFoundError):
            raise Conflict("Metadata changed") from None

    def write(self, partition, key, value, *, expected):
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
        from azure.data.tables import UpdateMode
        payload = json.dumps(value, separators=(",", ":"), allow_nan=False)
        # Azure's string property is limited to 64 KiB in UTF-16.
        if len(payload.encode("utf-16-le")) > 60000:
            raise ValueError("Metadata entity capacity exceeded")
        row = {"PartitionKey": partition, "RowKey": key, "Payload": payload}
        try:
            if expected is None:
                result = self.client.create_entity(row)
            else:
                if not expected or expected == "*":
                    raise ValueError("An exact ETag is required")
                result = self.client.update_entity(
                    row, mode=UpdateMode.REPLACE, etag=expected,
                    match_condition=MatchConditions.IfNotModified,
                )
        except (ResourceExistsError, ResourceModifiedError, ResourceNotFoundError):
            raise Conflict("Metadata changed") from None
        return result["etag"]
