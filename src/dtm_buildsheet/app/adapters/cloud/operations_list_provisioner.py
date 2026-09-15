"""Safe Microsoft Graph provisioning for the operations SharePoint lists."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import requests

from .config import GRAPH_ENDPOINT
from .operations_list_schema import (
    DEADLINE_OVERRIDE_SCHEMA_COLUMN_NAMES,
    DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
    EVENTS_LIST_NAME,
    FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION,
    LEGACY_FINAL_FINISH_STATUS_CHOICES,
    LEGACY_PARTS_STATUS_CHOICES,
    OPERATIONS_LIST_NAME,
    OPERATIONS_LIST_SPECS,
    OPERATIONS_REQUESTS_LIST,
    PARTS_ORDERED_SCHEMA_COLUMN_NAMES,
    PARTS_ORDERED_SCHEMA_CONFIRMATION,
    PROVISION_CONFIRMATION,
    PHONE_REQUESTS_PROVISION_CONFIRMATION,
    RECOVERY_SCHEMA_COLUMN_NAMES,
    RECOVERY_SCHEMA_CONFIRMATION,
    SharePointColumnSpec,
    SharePointListSpec,
)


ProvisioningState = Literal["missing", "valid", "mismatch"]


class OperationsListProvisioningError(RuntimeError):
    """Safe provisioning failure without response bodies, tokens, or URLs."""


@dataclass(frozen=True)
class ListInspection:
    name: str
    state: ProvisioningState
    list_id: str = ""
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "list_id": self.list_id,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class ProvisioningReport:
    lists: tuple[ListInspection, ...]

    @property
    def ready(self) -> bool:
        return bool(self.lists) and all(item.state == "valid" for item in self.lists)

    @property
    def has_mismatch(self) -> bool:
        return any(item.state == "mismatch" for item in self.lists)

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "lists": [item.to_dict() for item in self.lists],
        }


class OperationsListProvisioner:
    """Inspect and create only the reviewed operations lists.

    Routine creation never patches, renames, or deletes mismatched lists.
    Narrow, confirmation-gated upgrades accept only their reviewed prior state.
    """

    def __init__(
        self,
        *,
        token: str,
        site_id: str,
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not str(token or "").strip():
            raise ValueError("token is required")
        if not str(site_id or "").strip():
            raise ValueError("site_id is required")
        self._site_id = str(site_id).strip()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._session = session or requests.Session()
        self._timeout = max(1.0, min(float(timeout_seconds), 120.0))

    def inspect(self) -> ProvisioningReport:
        return self._inspect_specs(OPERATIONS_LIST_SPECS)

    def inspect_phone_requests(self) -> ProvisioningReport:
        """Inspect only the append-only phone request queue."""

        return self._inspect_specs((OPERATIONS_REQUESTS_LIST,))

    def _inspect_specs(
        self,
        specs: tuple[SharePointListSpec, ...],
    ) -> ProvisioningReport:
        existing = self._collection(
            self._lists_url("$select=id,name,displayName&$top=999"),
            operation="list inspection",
        )
        inspections: list[ListInspection] = []
        for spec in specs:
            candidates = [
                item for item in existing
                if self._has_normalized_list_name(item, spec.name)
            ]
            matches = [item for item in candidates if self._matches_list_name(item, spec.name)]
            if candidates and (len(candidates) != 1 or len(matches) != 1):
                inspections.append(ListInspection(
                    name=spec.name,
                    state="mismatch",
                    issues=("A conflicting or ambiguous list name already exists",),
                ))
                continue
            if not matches:
                inspections.append(ListInspection(name=spec.name, state="missing"))
                continue
            list_id = str(matches[0].get("id") or "").strip()
            if not list_id:
                inspections.append(ListInspection(
                    name=spec.name,
                    state="mismatch",
                    issues=("Matching list has no durable Graph ID",),
                ))
                continue
            columns = self._collection(
                self._columns_url(list_id),
                operation=f"{spec.name} column inspection",
            )
            issues = self._validate_columns(spec, columns)
            inspections.append(ListInspection(
                name=spec.name,
                state="mismatch" if issues else "valid",
                list_id=list_id,
                issues=tuple(issues),
            ))
        return ProvisioningReport(lists=tuple(inspections))

    def apply_phone_requests_list(
        self,
        *,
        confirmation: str,
    ) -> ProvisioningReport:
        """Create only the reviewed phone request queue after core validation."""

        if confirmation != PHONE_REQUESTS_PROVISION_CONFIRMATION:
            raise OperationsListProvisioningError(
                "Creation confirmation must exactly equal: "
                f"{PHONE_REQUESTS_PROVISION_CONFIRMATION}"
            )
        core = self.inspect()
        if not core.ready:
            raise OperationsListProvisioningError(
                "Phone request provisioning requires both core Operations lists "
                "to match the reviewed schema"
            )
        before = self.inspect_phone_requests()
        if before.has_mismatch:
            raise OperationsListProvisioningError(
                "Existing phone request list schema mismatch; no list was created"
            )
        if before.lists[0].state == "missing":
            self._create_list(OPERATIONS_REQUESTS_LIST)
        after = self.inspect_phone_requests()
        if not after.ready:
            raise OperationsListProvisioningError(
                "Post-create phone request schema validation failed"
            )
        return after

    def apply(self, *, confirmation: str) -> ProvisioningReport:
        if confirmation != PROVISION_CONFIRMATION:
            raise OperationsListProvisioningError(
                f"Creation confirmation must exactly equal: {PROVISION_CONFIRMATION}"
            )
        before = self.inspect()
        if before.has_mismatch:
            raise OperationsListProvisioningError(
                "Existing operations list schema mismatch; no lists were created"
            )
        missing_names = {item.name for item in before.lists if item.state == "missing"}
        for spec in OPERATIONS_LIST_SPECS:
            if spec.name in missing_names:
                self._create_list(spec)
        after = self.inspect()
        if not after.ready:
            raise OperationsListProvisioningError(
                "Post-create schema validation failed; operations clients remain disabled"
            )
        return after

    def apply_recovery_schema_upgrade(
        self,
        *,
        confirmation: str,
    ) -> ProvisioningReport:
        """Add only the reviewed recovery fields to the two existing lists."""

        return self._apply_additive_schema_upgrade(
            confirmation=confirmation,
            required_confirmation=RECOVERY_SCHEMA_CONFIRMATION,
            allowed_columns=RECOVERY_SCHEMA_COLUMN_NAMES,
            upgrade_label="Operations recovery",
        )

    def apply_deadline_override_schema_upgrade(
        self,
        *,
        confirmation: str,
    ) -> ProvisioningReport:
        """Add only the reviewed manual deadline-override field."""

        return self._apply_additive_schema_upgrade(
            confirmation=confirmation,
            required_confirmation=DEADLINE_OVERRIDE_SCHEMA_CONFIRMATION,
            allowed_columns=DEADLINE_OVERRIDE_SCHEMA_COLUMN_NAMES,
            upgrade_label="Operations deadline override",
        )

    def apply_parts_ordered_schema_upgrade(
        self,
        *,
        confirmation: str,
    ) -> ProvisioningReport:
        """Add the ordered milestone and extend only the PartsStatus choices."""

        if confirmation != PARTS_ORDERED_SCHEMA_CONFIRMATION:
            raise OperationsListProvisioningError(
                f"Upgrade confirmation must exactly equal: {PARTS_ORDERED_SCHEMA_CONFIRMATION}"
            )
        before = self.inspect()
        by_name = {item.name: item for item in before.lists}
        allowed_issues = {
            OPERATIONS_LIST_NAME: {
                "Missing column: PartsOrderedAtUtc",
                "PartsStatus has incorrect choices",
            },
            EVENTS_LIST_NAME: set(),
        }
        for spec in OPERATIONS_LIST_SPECS:
            inspection = by_name[spec.name]
            if inspection.state == "missing":
                raise OperationsListProvisioningError(
                    "Parts Ordered upgrade requires both existing lists"
                )
            if any(issue not in allowed_issues[spec.name] for issue in inspection.issues):
                raise OperationsListProvisioningError(
                    "Existing operations schema has a non-upgrade mismatch; no changes were made"
                )

        operations = by_name[OPERATIONS_LIST_NAME]
        operations_spec = next(
            spec for spec in OPERATIONS_LIST_SPECS if spec.name == OPERATIONS_LIST_NAME
        )
        choices_need_upgrade = "PartsStatus has incorrect choices" in operations.issues
        parts_status_column: dict | None = None
        if choices_need_upgrade:
            parts_status_column = self._get_column(
                list_id=operations.list_id,
                column_name="PartsStatus",
            )
            actual_choices = tuple(
                str(value)
                for value in (parts_status_column.get("choice") or {}).get("choices", [])
            )
            if actual_choices != LEGACY_PARTS_STATUS_CHOICES:
                raise OperationsListProvisioningError(
                    "PartsStatus choices are not the reviewed pre-upgrade values; no changes were made"
                )

        if "Missing column: PartsOrderedAtUtc" in operations.issues:
            expected = {column.name: column for column in operations_spec.columns}
            self._create_column(
                list_id=operations.list_id,
                list_name=OPERATIONS_LIST_NAME,
                column=expected[PARTS_ORDERED_SCHEMA_COLUMN_NAMES[OPERATIONS_LIST_NAME][0]],
            )
        if choices_need_upgrade and parts_status_column is not None:
            expected = {column.name: column for column in operations_spec.columns}
            self._update_choice_column(
                list_id=operations.list_id,
                list_name=OPERATIONS_LIST_NAME,
                column_id=str(parts_status_column.get("id") or "").strip(),
                column=expected["PartsStatus"],
            )

        after = self.inspect()
        if not after.ready:
            raise OperationsListProvisioningError(
                "Post-upgrade schema validation failed; operations clients remain disabled"
            )
        return after

    def apply_final_finish_delivered_schema_upgrade(
        self,
        *,
        confirmation: str,
    ) -> ProvisioningReport:
        """Extend only FinalFinishStatus with the reviewed Delivered choice."""

        if confirmation != FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION:
            raise OperationsListProvisioningError(
                "Upgrade confirmation must exactly equal: "
                f"{FINAL_FINISH_DELIVERED_SCHEMA_CONFIRMATION}"
            )
        before = self.inspect()
        by_name = {item.name: item for item in before.lists}
        allowed_issues = {
            OPERATIONS_LIST_NAME: {"FinalFinishStatus has incorrect choices"},
            EVENTS_LIST_NAME: set(),
        }
        for spec in OPERATIONS_LIST_SPECS:
            inspection = by_name[spec.name]
            if inspection.state == "missing":
                raise OperationsListProvisioningError(
                    "Final Finish Delivered upgrade requires both existing lists"
                )
            if any(issue not in allowed_issues[spec.name] for issue in inspection.issues):
                raise OperationsListProvisioningError(
                    "Existing operations schema has a non-upgrade mismatch; no changes were made"
                )

        operations = by_name[OPERATIONS_LIST_NAME]
        if not operations.issues:
            return before
        status_column = self._get_column(
            list_id=operations.list_id,
            column_name="FinalFinishStatus",
        )
        actual_choices = tuple(
            str(value)
            for value in (status_column.get("choice") or {}).get("choices", [])
        )
        if actual_choices != LEGACY_FINAL_FINISH_STATUS_CHOICES:
            raise OperationsListProvisioningError(
                "FinalFinishStatus choices are not the reviewed pre-upgrade values; "
                "no changes were made"
            )
        operations_spec = next(
            spec for spec in OPERATIONS_LIST_SPECS if spec.name == OPERATIONS_LIST_NAME
        )
        expected = {column.name: column for column in operations_spec.columns}
        self._update_choice_column(
            list_id=operations.list_id,
            list_name=OPERATIONS_LIST_NAME,
            column_id=str(status_column.get("id") or "").strip(),
            column=expected["FinalFinishStatus"],
        )

        after = self.inspect()
        if not after.ready:
            raise OperationsListProvisioningError(
                "Post-upgrade schema validation failed; operations clients remain disabled"
            )
        return after

    def _apply_additive_schema_upgrade(
        self,
        *,
        confirmation: str,
        required_confirmation: str,
        allowed_columns: dict[str, tuple[str, ...]],
        upgrade_label: str,
    ) -> ProvisioningReport:
        if confirmation != required_confirmation:
            raise OperationsListProvisioningError(
                f"Upgrade confirmation must exactly equal: {required_confirmation}"
            )
        before = self.inspect()
        by_name = {item.name: item for item in before.lists}
        missing_by_list: dict[str, set[str]] = {}
        for spec in OPERATIONS_LIST_SPECS:
            inspection = by_name[spec.name]
            if inspection.state == "missing":
                raise OperationsListProvisioningError(
                    f"{upgrade_label} upgrade requires both existing lists"
                )
            allowed = set(allowed_columns.get(spec.name, ()))
            missing: set[str] = set()
            blockers: list[str] = []
            for issue in inspection.issues:
                prefix = "Missing column: "
                if issue.startswith(prefix) and issue[len(prefix):] in allowed:
                    missing.add(issue[len(prefix):])
                else:
                    blockers.append(issue)
            if blockers:
                raise OperationsListProvisioningError(
                    "Existing operations schema has a non-upgrade mismatch; no columns were added"
                )
            missing_by_list[spec.name] = missing

        for spec in OPERATIONS_LIST_SPECS:
            inspection = by_name[spec.name]
            expected = {column.name: column for column in spec.columns}
            for column_name in allowed_columns.get(spec.name, ()):
                if column_name in missing_by_list[spec.name]:
                    self._create_column(
                        list_id=inspection.list_id,
                        list_name=spec.name,
                        column=expected[column_name],
                    )
        after = self.inspect()
        if not after.ready:
            raise OperationsListProvisioningError(
                "Post-upgrade schema validation failed; operations clients remain disabled"
            )
        return after

    def _create_list(self, spec: SharePointListSpec) -> None:
        response = self._send(
            "post",
            self._lists_url(),
            operation=f"{spec.name} creation",
            json=spec.graph_create_payload(),
        )
        self._raise_for_status(response, operation=f"{spec.name} creation")

    def _create_column(
        self,
        *,
        list_id: str,
        list_name: str,
        column: SharePointColumnSpec,
    ) -> None:
        response = self._send(
            "post",
            self._columns_url(list_id, query=False),
            operation=f"{list_name} schema-column creation",
            json=column.graph_payload(),
        )
        self._raise_for_status(
            response,
            operation=f"{list_name} schema-column creation",
        )

    def _get_column(self, *, list_id: str, column_name: str) -> dict:
        columns = self._collection(
            self._columns_url(list_id),
            operation=f"{column_name} column inspection",
        )
        match = next(
            (column for column in columns if column.get("name") == column_name),
            None,
        )
        if match is None:
            raise OperationsListProvisioningError(
                f"Existing operations schema is missing {column_name}"
            )
        return match

    def _update_choice_column(
        self,
        *,
        list_id: str,
        list_name: str,
        column_id: str,
        column: SharePointColumnSpec,
    ) -> None:
        if not column_id:
            raise OperationsListProvisioningError(
                f"{column.name} has no durable Graph column ID"
            )
        response = self._send(
            "patch",
            self._column_url(list_id, column_id),
            operation=f"{list_name} choice extension",
            json={"choice": column.graph_payload()["choice"]},
        )
        self._raise_for_status(response, operation=f"{list_name} choice extension")

    def _collection(self, url: str, *, operation: str) -> list[dict]:
        rows: list[dict] = []
        next_url = url
        while next_url:
            response = self._send("get", next_url, operation=operation)
            self._raise_for_status(response, operation=operation)
            payload = self._response_json(response, operation=operation)
            value = payload.get("value", [])
            if not isinstance(value, list):
                raise OperationsListProvisioningError(
                    f"SharePoint {operation} returned an invalid collection"
                )
            rows.extend(item for item in value if isinstance(item, dict))
            next_url = str(payload.get("@odata.nextLink") or "").strip()
        return rows

    def _send(self, method: str, url: str, *, operation: str, **kwargs):
        try:
            return getattr(self._session, method)(
                url,
                headers=self._headers,
                timeout=self._timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise OperationsListProvisioningError(
                f"SharePoint {operation} request failed ({type(exc).__name__})"
            ) from None

    @staticmethod
    def _raise_for_status(response, *, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException:
            status = getattr(response, "status_code", None)
            detail = f"HTTP {status}" if status else "HTTP request failed"
            raise OperationsListProvisioningError(
                f"SharePoint {operation} failed ({detail})"
            ) from None

    @staticmethod
    def _response_json(response, *, operation: str) -> dict:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise OperationsListProvisioningError(
                f"SharePoint {operation} returned invalid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise OperationsListProvisioningError(
                f"SharePoint {operation} returned an invalid object"
            )
        return payload

    @staticmethod
    def _matches_list_name(item: dict, expected: str) -> bool:
        wanted = expected.casefold()
        return any(
            str(item.get(field) or "").strip().casefold() == wanted
            for field in ("name", "displayName")
        )

    @classmethod
    def _has_normalized_list_name(cls, item: dict, expected: str) -> bool:
        wanted = cls._normalize_name(expected)
        return any(
            cls._normalize_name(str(item.get(field) or "")) == wanted
            for field in ("name", "displayName")
        )

    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    @classmethod
    def _validate_columns(
        cls,
        spec: SharePointListSpec,
        actual_columns: list[dict],
    ) -> list[str]:
        issues: list[str] = []
        actual = {
            str(column.get("name") or "").strip(): column
            for column in actual_columns
            if str(column.get("name") or "").strip()
        }
        title = actual.get("Title")
        if title is None:
            issues.append("Missing built-in Title column")
        elif "text" not in title:
            issues.append("Built-in Title column is not text")
        elif not bool(title.get("required", False)):
            issues.append("Built-in Title column is not required")

        expected_names = {column.name for column in spec.columns}
        for column in spec.columns:
            found = actual.get(column.name)
            if found is None:
                issues.append(f"Missing column: {column.name}")
                continue
            issues.extend(cls._column_issues(column, found))

        for name, found in actual.items():
            if name in expected_names or name in {"Title", "Attachments"}:
                continue
            if (
                str(found.get("columnGroup") or "").strip() == "Custom Columns"
                and not bool(found.get("readOnly", False))
                and not bool(found.get("hidden", False))
            ):
                issues.append(f"Unexpected custom column: {name}")
        return issues

    @staticmethod
    def _column_issues(expected: SharePointColumnSpec, actual: dict) -> list[str]:
        issues: list[str] = []
        for key, wanted in (
            ("required", expected.required),
            ("indexed", expected.indexed),
            ("enforceUniqueValues", expected.unique),
        ):
            if bool(actual.get(key, False)) != wanted:
                issues.append(f"{expected.name} has incorrect {key}")

        if expected.kind in {"text", "multiline"}:
            facet = actual.get("text")
            if not isinstance(facet, dict):
                issues.append(f"{expected.name} is not a text column")
            elif bool(facet.get("allowMultipleLines", False)) != (
                expected.kind == "multiline"
            ):
                issues.append(f"{expected.name} has incorrect multiline setting")
        elif expected.kind == "choice":
            facet = actual.get("choice")
            if not isinstance(facet, dict):
                issues.append(f"{expected.name} is not a choice column")
            elif tuple(str(value) for value in facet.get("choices", [])) != expected.choices:
                issues.append(f"{expected.name} has incorrect choices")
        elif expected.kind in {"date", "datetime"}:
            facet = actual.get("dateTime")
            wanted = "dateOnly" if expected.kind == "date" else "dateTime"
            if not isinstance(facet, dict) or facet.get("format") != wanted:
                issues.append(f"{expected.name} has incorrect date format")
        elif expected.kind == "number":
            facet = actual.get("number")
            if not isinstance(facet, dict) or facet.get("decimalPlaces") != "none":
                issues.append(f"{expected.name} is not an integer number column")
        elif expected.kind == "boolean" and not isinstance(actual.get("boolean"), dict):
            issues.append(f"{expected.name} is not a yes/no column")
        return issues

    def _lists_url(self, query: str = "") -> str:
        url = (
            f"{GRAPH_ENDPOINT}/sites/{quote(self._site_id, safe='')}/lists"
        )
        return f"{url}?{query}" if query else url

    def _columns_url(self, list_id: str, *, query: bool = True) -> str:
        base = f"{self._lists_url()}/{quote(list_id, safe='')}/columns"
        if not query:
            return base
        selected = (
            "id,name,required,indexed,enforceUniqueValues,columnGroup,"
            "readOnly,hidden,text,choice,dateTime,number,boolean"
        )
        return f"{base}?$select={selected}&$top=999"

    def _column_url(self, list_id: str, column_id: str) -> str:
        return (
            f"{self._columns_url(list_id, query=False)}/"
            f"{quote(column_id, safe='')}"
        )
