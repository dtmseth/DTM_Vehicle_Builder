"""Hermetic security/refresh tests for the provider-neutral central core."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from dtm_buildsheet.app.quickbooks_central import (
    BUILDER_ADMIN_ROLE,
    BUILDER_USER_ROLE,
    CentralQuickBooksService,
    EntraTokenValidator,
    RefreshCoordinator,
    ServerCredentials,
)
from dtm_buildsheet.app.quickbooks_central.hermetic import (
    HermeticQboProvider,
    HermeticSignatureVerifier,
    InMemoryAuditStore,
    InMemoryCredentialStore,
    InMemoryLockProvider,
)


NOW = 1_800_000_000.0
TENANT = "dtm-tenant"
AUDIENCE = "builder-api-client-id"
REALM_KEY = "dtm-company"


def _claims(*, roles=None, tenant=TENANT, audience=AUDIENCE, exp=NOW + 3600):
    return {
        "tid": tenant,
        "aud": audience,
        "exp": exp,
        "sub": "pairwise-subject",
        "oid": "employee-object-id",
        "roles": list(roles or []),
    }


def _fixture(*, qbo=None, credentials=None):
    verifier = HermeticSignatureVerifier(b"hermetic-signing-key")
    identity = EntraTokenValidator(
        verifier=verifier,
        tenant_id=TENANT,
        audience=AUDIENCE,
        now=lambda: NOW,
    )
    store = InMemoryCredentialStore()
    store.seed(
        REALM_KEY,
        credentials
        or ServerCredentials(
            realm_id="realm-id-never-returned",
            access_token="server-access-token",
            refresh_token="server-refresh-token",
            access_expires_at=NOW + 3600,
        ),
    )
    locks = InMemoryLockProvider()
    audit = InMemoryAuditStore()
    qbo = qbo or HermeticQboProvider(
        items=[
            {
                "qb_item_id": "item-1",
                "name": "Test Item",
                "sku": "SKU-1",
                "unit_price": 12.5,
                "type": "Inventory",
                "active": True,
            }
        ],
        now=lambda: NOW,
    )
    refresh = RefreshCoordinator(
        credentials=store,
        locks=locks,
        qbo=qbo,
        now=lambda: NOW,
    )
    service = CentralQuickBooksService(
        realm_key=REALM_KEY,
        identity=identity,
        refresh=refresh,
        qbo=qbo,
        audit=audit,
    )
    return service, verifier, store, audit, qbo, refresh


def _bearer(verifier, *, roles, **overrides):
    return "Bearer " + verifier.mint(_claims(roles=roles, **overrides))


def test_user_and_admin_roles_are_authorized_for_narrow_endpoints():
    service, verifier, _, audit, _, _ = _fixture()

    user = service.connection_health(
        _bearer(verifier, roles=[BUILDER_USER_ROLE]),
        correlation_id="user-health",
    )
    admin = service.connection_health(
        _bearer(verifier, roles=[BUILDER_ADMIN_ROLE]),
        correlation_id="admin-health",
        admin_details=True,
    )
    admin_catalog = service.active_items(
        _bearer(verifier, roles=[BUILDER_ADMIN_ROLE]),
        correlation_id="admin-catalog",
    )

    assert user.status_code == 200
    assert user.body["connected"] is True
    assert "admin" not in user.body
    assert admin.status_code == 200
    assert admin.body["admin"] == {"realm_bound": True, "credential_generation": 0}
    assert admin_catalog.status_code == 200
    assert admin_catalog.body["item_count"] == 1
    assert [record.correlation_id for record in audit.records] == [
        "user-health",
        "admin-health",
        "admin-catalog",
    ]


@pytest.mark.parametrize(
    ("authorization", "expected_status", "expected_code"),
    [
        ("", 401, "unauthenticated"),
        ("Bearer {wrong_tenant}", 401, "wrong_tenant"),
        ("Bearer {wrong_audience}", 401, "wrong_audience"),
        ("Bearer {expired}", 401, "expired_token"),
        ("Bearer {missing_role}", 403, "forbidden"),
    ],
)
def test_identity_failures_are_401_or_403(authorization, expected_status, expected_code):
    service, verifier, _, _, _, _ = _fixture()
    tokens = {
        "wrong_tenant": verifier.mint(_claims(roles=[BUILDER_USER_ROLE], tenant="other")),
        "wrong_audience": verifier.mint(_claims(roles=[BUILDER_USER_ROLE], audience="graph")),
        "expired": verifier.mint(_claims(roles=[BUILDER_USER_ROLE], exp=NOW - 1)),
        "missing_role": verifier.mint(_claims(roles=[])),
    }
    for name, token in tokens.items():
        authorization = authorization.replace("{" + name + "}", token)

    result = service.connection_health(authorization, correlation_id="auth-check")

    assert result.status_code == expected_status
    assert result.body["error"]["code"] == expected_code


def test_admin_health_rejects_builder_user():
    service, verifier, _, _, _, _ = _fixture()
    result = service.connection_health(
        _bearer(verifier, roles=[BUILDER_USER_ROLE]),
        correlation_id="admin-only",
        admin_details=True,
    )
    assert result.status_code == 403
    assert result.body["error"]["code"] == "forbidden"


def test_concurrent_refresh_uses_one_latest_rotating_token():
    expired = ServerCredentials(
        realm_id="realm",
        access_token="expired-access",
        refresh_token="initial-refresh",
        access_expires_at=NOW - 10,
    )
    _, _, store, _, qbo, refresh = _fixture(credentials=expired)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: refresh.get(REALM_KEY), range(24)))

    assert qbo.refresh_count == 1
    assert qbo.refresh_tokens_seen == ["initial-refresh"]
    assert {result.access_token for result in results} == {"hermetic-access-1"}
    latest = store.load(REALM_KEY)
    assert latest is not None
    assert latest.refresh_token == "hermetic-refresh-1"
    assert latest.version == 1


class _ExplodingQbo(HermeticQboProvider):
    def fetch_active_items(self, *, access_token: str, realm_id: str):
        raise RuntimeError(
            "token=server-secret https://provider.example/customer?payload=private-customer"
        )


def test_errors_are_structured_and_redact_provider_secrets_urls_and_payloads():
    qbo = _ExplodingQbo(now=lambda: NOW)
    service, verifier, _, audit, _, _ = _fixture(qbo=qbo)
    result = service.active_items(
        _bearer(verifier, roles=[BUILDER_USER_ROLE]),
        correlation_id="safe-error",
    )

    rendered = json.dumps(result.body)
    assert result.status_code == 503
    assert result.body["error"]["code"] == "provider_unavailable"
    for forbidden in ("server-secret", "provider.example", "private-customer", "realm-id"):
        assert forbidden not in rendered
    assert audit.records[-1].error_code == "provider_unavailable"


def test_untrusted_correlation_value_is_not_echoed_or_audited():
    service, verifier, _, audit, _, _ = _fixture()
    malicious = "Bearer server-secret https://signed.example/?token=private"
    result = service.active_items(
        _bearer(verifier, roles=[BUILDER_USER_ROLE]),
        correlation_id=malicious,
    )

    assert result.status_code == 200
    assert result.body["correlation_id"] != malicious
    assert "server-secret" not in result.body["correlation_id"]
    assert audit.records[-1].correlation_id == result.body["correlation_id"]


def test_audit_attributes_catalog_read_to_employee_object_id_without_item_payload():
    service, verifier, _, audit, _, _ = _fixture()
    result = service.active_items(
        _bearer(verifier, roles=[BUILDER_USER_ROLE]),
        correlation_id="audit-correlation",
    )

    assert result.status_code == 200
    record = audit.records[-1]
    assert record.tenant_id == TENANT
    assert record.user_object_id == "employee-object-id"
    assert record.action == "quickbooks.catalog.active_items.read"
    assert record.outcome == "success"
    assert record.correlation_id == "audit-correlation"
    assert "Test Item" not in repr(record)


def test_hermetic_credential_adapter_refuses_production_use():
    with pytest.raises(RuntimeError, match="refuses_production"):
        InMemoryCredentialStore(environment="production")


def test_server_credentials_repr_never_contains_tokens():
    credentials = ServerCredentials(
        realm_id="realm",
        access_token="access-secret",
        refresh_token="refresh-secret",
        access_expires_at=NOW,
    )
    assert "access-secret" not in repr(credentials)
    assert "refresh-secret" not in repr(credentials)
