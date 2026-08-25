"""Allowlisted errors for the central service safety boundary."""

from __future__ import annotations

from .contracts import EndpointResult


_SAFE_MESSAGES = {
    "unauthenticated": "Authentication is required.",
    "invalid_token": "The Builder API token is invalid.",
    "wrong_tenant": "This account is not authorized for the Builder API.",
    "wrong_audience": "The token was not issued for the Builder API.",
    "expired_token": "The Builder API session has expired.",
    "missing_subject": "The Builder API token has no usable subject.",
    "forbidden": "The signed-in user does not have the required Builder role.",
    "not_connected": "The managed QuickBooks company connection is unavailable.",
    "credential_conflict": "The managed QuickBooks credential changed; retry the request.",
    "provider_unavailable": "QuickBooks is temporarily unavailable.",
    "service_capacity_exhausted": "The hosted Builder API has reached its usage limit.",
    "invalid_provider_data": "QuickBooks returned data the Builder API could not accept.",
    "internal_error": "The Builder API could not complete the request.",
}


class CentralServiceError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 500) -> None:
        self.code = code if code in _SAFE_MESSAGES else "internal_error"
        self.status_code = status_code
        super().__init__(self.code)


def safe_error_result(error: CentralServiceError, correlation_id: str) -> EndpointResult:
    """Return no exception text, provider detail, URL, payload, or credential."""
    return EndpointResult(
        status_code=error.status_code,
        body={
            "ok": False,
            "error": {
                "code": error.code,
                "message": _SAFE_MESSAGES[error.code],
            },
            "correlation_id": correlation_id,
        },
    )
