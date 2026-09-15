"""WSGI request boundary. Desktop route dispatch is deliberately not reachable.

Stage 2 proves auth/storage contracts using synthetic resource adapters. Real
SharePoint/Calendar/QBO adapters enter only after their Stage 4 tests. The existing
UI and business services remain shared; this module is not a second Builder.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Protocol
from urllib.parse import urlsplit

from ...domain.operations_policy import Capability, has_capability
from ..request_context import RequestContext, bind_request, hosted_process
from .auth import Denied, RequestIdentity, Sessions
from .metadata import AzureTableMetadata, Conflict, Versioned
from .telemetry import request_event


class ReviewedDocuments(Protocol):
    """Authoritative documents; implementations enforce ACL/schema/finalization.

    ETag preconditions must be applied at the provider, not to a local cache.
    Review returns a stable snapshot reference; no client filesystem path is valid.
    No production implementation is wired yet. Synthetic adapter is test-only.
    """
    def read(self, principal, resource: str) -> Versioned: ...
    def write(self, principal, resource: str, value: dict, expected: str) -> str: ...
    def review(self, principal, kind: str, resource: str, expected: str) -> str: ...


class UnavailableAdapter:
    """Never accidentally fall through to desktop storage or provider workers."""
    def __getattr__(self, name):
        raise Denied(503, "provider_not_enabled")


class Application:
    MAX_BODY = 64 * 1024

    def __init__(self, *, mode, origin, tokens, store, artifacts, jobs, documents=None):
        parsed = urlsplit(origin)
        if (parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password
                or not parsed.hostname):
            raise ValueError("An exact origin is required")
        if mode == "local-proof":
            if hosted_process() or parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
                raise ValueError("Local proof is loopback-only and unavailable on deployed hosts")
        elif mode == "hosted":
            if parsed.scheme != "https" or type(store) is not AzureTableMetadata:
                raise ValueError("Hosted mode requires HTTPS and Azure Table metadata")
        else:
            raise ValueError("Explicit runtime mode required")
        self.mode, self.origin, self.authority = mode, origin, parsed.netloc
        self.tokens, self.store = tokens, store
        self.sessions, self.artifacts, self.jobs = Sessions(store), artifacts, jobs
        self.documents = documents
        self.cookie_name = "__Host-dtm-session" if mode == "hosted" else "dtm-local-proof-session"

    def __call__(self, environ, start_response):
        started = time.monotonic()
        request_id = secrets.token_hex(16)
        headers = []
        try:
            status, data, ctype, headers = self.dispatch(environ, request_id)
        except Denied as exc:
            status, data, ctype = exc.status, {"ok": False, "error": exc.code}, "application/json"
        except Conflict:
            status, data, ctype = 409, {"ok": False, "error": "revision_conflict"}, "application/json"
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            status, data, ctype = 400, {"ok": False, "error": "invalid_request"}, "application/json"
        except Exception:
            # No request/provider details in logs or responses. Correlate by this ID.
            status, data, ctype = 503, {"ok": False, "error": "service_unavailable"}, "application/json"
        try:
            content = json.dumps(data, allow_nan=False).encode() if isinstance(data, dict) else data
            if not isinstance(content, bytes):
                raise ValueError("Invalid response")
        except (ValueError, TypeError):
            status, ctype, headers = 503, "application/json", []
            content = b'{"ok":false,"error":"service_unavailable"}'
        headers += [
            ("Content-Type", ctype), ("Content-Length", str(len(content))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
            ("X-Request-ID", request_id),
        ]
        if self.mode == "hosted":
            headers.append(("Strict-Transport-Security", "max-age=31536000"))
        request_event(environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", ""),
                      request_id, status, time.monotonic() - started)
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [content]

    def dispatch(self, env, request_id):
        method, path = env.get("REQUEST_METHOD", ""), env.get("PATH_INFO", "")
        if method not in {"GET", "POST", "PUT"}:
            raise Denied(405, "method_not_allowed")
        if env.get("HTTP_HOST") != self.authority:
            raise Denied(400, "invalid_host")
        if env.get("QUERY_STRING") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", path) or ".." in path or "//" in path:
            raise Denied(400, "invalid_path")
        if path == "/healthz" and method == "GET":
            return 200, {"ok": True}, "application/json", []
        origin = env.get("HTTP_ORIGIN")
        if origin is not None and origin != self.origin:
            raise Denied(403, "invalid_origin")
        if method != "GET" and origin != self.origin:
            raise Denied(403, "origin_required")
        if env.get("HTTP_SEC_FETCH_SITE") not in (None, "same-origin", "none"):
            raise Denied(403, "cross_site_request")
        # Only the independently validated signed ID token authorizes a user.
        # Ignore all unsigned principal, email, role, and forwarded headers.
        principal = self.tokens.verify(env.get("HTTP_X_MS_TOKEN_AAD_ID_TOKEN", ""))
        from ..adapters.wiring import AdapterBundle
        unavailable = UnavailableAdapter()
        bundle = AdapterBundle(
            identity=RequestIdentity(principal.user), storage=unavailable,
            proposals=unavailable, notifications=unavailable,
        )
        context = RequestContext(principal.tenant, principal.user.user_id, request_id, bundle)
        with bind_request(context):
            return self._authenticated(env, principal, path, method)

    def _cookie(self, env):
        raw = env.get("HTTP_COOKIE", "")
        # Ambiguous duplicates (cookie tossing) fail closed.
        if sum(part.strip().split("=", 1)[0] == self.cookie_name for part in raw.split(";")) > 1:
            raise Denied(401, "invalid_session")
        cookies = SimpleCookie()
        cookies.load(raw)
        return cookies[self.cookie_name].value if self.cookie_name in cookies else ""

    def _set_cookie(self, value, lifetime):
        return ("Set-Cookie", f"{self.cookie_name}={value}; Path=/; Max-Age={lifetime}; "
                f"HttpOnly; SameSite=Strict" + ("; Secure" if self.mode == "hosted" else ""))

    def _body(self, env):
        if env.get("CONTENT_TYPE") != "application/json":
            raise Denied(415, "json_required")
        length = int(env.get("CONTENT_LENGTH") or "0")
        if not 0 < length <= self.MAX_BODY:
            raise Denied(413, "body_limit")
        raw = env["wsgi.input"].read(length)
        if len(raw) != length:
            raise ValueError("Incomplete body")
        body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(body, dict):
            raise ValueError("Object required")
        return body

    def _authenticated(self, env, principal, path, method):
        if path == "/api/hosted/session" and method == "POST":
            self._body(env)
            # Rotate any existing session, so bootstrap cannot fixate a session.
            cookie = self._cookie(env)
            if cookie:
                self.sessions.revoke(principal, cookie)
            cookie, csrf, expires = self.sessions.create(principal)
            import time
            return 200, {"ok": True, "csrf": csrf, "expires": expires}, "application/json", [
                self._set_cookie(cookie, max(0, expires - int(time.time())))
            ]
        cookie = self._cookie(env)
        self.sessions.check(principal, cookie, env.get("HTTP_X_DTM_CSRF", "") if method != "GET" else None)
        if path == "/api/hosted/session" and method == "GET":
            from ..services.operations_access_service import describe_access_session
            return 200, describe_access_session(cloud_enabled=False), "application/json", []
        if path == "/api/hosted/logout" and method == "POST":
            self._body(env)
            self.sessions.revoke(principal, cookie)
            return 200, {"ok": True, "redirect": "/.auth/logout"}, "application/json", [self._set_cookie("", 0)]
        match = re.fullmatch(r"/api/hosted/artifacts/([0-9a-f]{48})", path)
        if match and method == "GET":
            self._require(principal, Capability.PROJECTS_VIEW)
            content, extension = self.artifacts.download(principal, match[1])
            ctype = "application/pdf" if extension == "pdf" else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            return 200, content, ctype, [("Content-Disposition", f'attachment; filename="build.{extension}"')]
        match = re.fullmatch(r"/api/hosted/jobs/([0-9a-f]{64})", path)
        if match and method == "GET":
            return 200, {"ok": True, "job": self.jobs.read(principal, match[1])}, "application/json", []
        match = re.fullmatch(r"/api/hosted/documents/([A-Za-z0-9_-]{1,80})", path)
        if match and method in {"GET", "PUT"}:
            self._require(principal, Capability.PROJECTS_VIEW if method == "GET" else Capability.PROJECTS_EDIT)
            self._documents_ready()
            if method == "GET":
                row = self.documents.read(principal, match[1])
                return 200, {"ok": True, "document": row.value, "revision": row.etag}, "application/json", []
            revision = self.documents.write(principal, match[1], self._body(env), self._revision(env))
            return 200, {"ok": True, "revision": revision}, "application/json", []
        if path == "/api/hosted/jobs" and method == "POST":
            from .jobs import KINDS
            body = self._body(env)
            if set(body) != {"kind", "resource", "request_id"} or body["kind"] not in KINDS:
                raise ValueError("Invalid job intent")
            self._require(principal, KINDS[body["kind"]])
            self._documents_ready()
            revision = self._revision(env)
            snapshot = self.documents.review(principal, body["kind"], body["resource"], revision)
            key = self.jobs.enqueue(principal, kind=body["kind"], resource=body["resource"],
                                    request_id=body["request_id"], revision=revision, snapshot=snapshot)
            return 202, {"ok": True, "job_id": key}, "application/json", []
        # Includes legacy cloud/Operations/Calendar/QBO routes with their own guards,
        # native paths, static files, callbacks and all future unclassified routes.
        raise Denied(404, "route_not_enabled")

    @staticmethod
    def _require(principal, capability):
        if not has_capability(principal.user.roles, capability):
            raise Denied()

    @staticmethod
    def _revision(env):
        value = env.get("HTTP_IF_MATCH", "")
        if not value or value == "*" or len(value) > 160:
            raise Denied(428, "exact_revision_required")
        return value

    def _documents_ready(self):
        if self.documents is None:
            raise Denied(503, "provider_not_enabled")
