"""Explicit request identity; background threads must bind their own context."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters.wiring import AdapterBundle


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    user_id: str
    request_id: str
    bundle: AdapterBundle


_request: ContextVar[RequestContext | None] = ContextVar("dtm_request", default=None)


def current_request() -> RequestContext | None:
    return _request.get()


def hosted_process() -> bool:
    return os.environ.get("DTM_RUNTIME_MODE") == "hosted" or any(
        os.environ.get(key) for key in ("CONTAINER_APP_NAME", "WEBSITE_INSTANCE_ID", "K_REVISION")
    )


@contextmanager
def bind_request(context: RequestContext):
    token = _request.set(context)
    try:
        yield context
    finally:
        _request.reset(token)
