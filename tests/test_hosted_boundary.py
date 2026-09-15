"""Shared-user security contract; signed synthetic tokens, no cloud/keychain I/O."""
from __future__ import annotations

import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from dtm_buildsheet.app.hosted.application import Application
from dtm_buildsheet.app.hosted.artifacts import Artifacts
from dtm_buildsheet.app.hosted.auth import Denied, EntraTokens, Sessions
from dtm_buildsheet.app.hosted.jobs import Jobs
from dtm_buildsheet.app.hosted.metadata import AzureTableMetadata, Conflict
from dtm_buildsheet.app.request_context import RequestContext, bind_request, current_request
from tools.pilot.shared_user_fixtures import SqliteProofStore, SyntheticDocuments

TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
ALICE = "33333333-3333-4333-8333-333333333333"
BOB = "44444444-4444-4444-8444-444444444444"
OTHER = "55555555-5555-4555-8555-555555555555"
ORIGIN = "http://127.0.0.1:7666"


def test_expired_cleanup_is_bounded_dry_run_and_preserves_jobs(proof):
    from dtm_buildsheet.app.hosted.maintenance import cleanup_page
    p = proof.tokens.verify(proof.token())
    old_cookie, _, _ = Sessions(proof.store, clock=lambda: 0).create(p)
    live_cookie, _, _ = Sessions(proof.store, clock=lambda: 5000).create(p)
    from dtm_buildsheet.app.hosted.auth import digest
    old_key, live_key = "session-" + digest(old_cookie), "session-" + digest(live_cookie)
    proof.store.write(TENANT, "job-keep", {"expires": 0}, expected=None)
    preview = cleanup_page(proof.store, proof.artifacts, TENANT, "session", now=4000)
    assert preview["eligible"] == 1 and preview["deleted"] == 0
    assert proof.store.read(TENANT, old_key)
    result = cleanup_page(proof.store, proof.artifacts, TENANT, "session", now=4000, apply=True)
    assert result["deleted"] == 1
    assert proof.store.read(TENANT, old_key) is None
    assert proof.store.read(TENANT, live_key) and proof.store.read(TENANT, "job-keep")
    with pytest.raises(ValueError):
        cleanup_page(proof.store, proof.artifacts, TENANT, "job", apply=True)
    for i in range(3):
        proof.store.write(OTHER, "session-" + f"{i:064x}", {"owner": OTHER + ":" + ALICE, "expires": 0}, expected=None)
    one = cleanup_page(proof.store, proof.artifacts, OTHER, "session", limit=1, now=4000)
    two = cleanup_page(proof.store, proof.artifacts, OTHER, "session", limit=1, now=4000, after=one["after"])
    assert one["scanned"] == two["scanned"] == 1 and two["after"] > one["after"]


def test_cleanup_conflict_never_deletes_updated_session(proof, monkeypatch):
    from dtm_buildsheet.app.hosted.maintenance import cleanup_page
    from dtm_buildsheet.app.hosted.auth import digest
    p = proof.tokens.verify(proof.token())
    cookie, _, _ = Sessions(proof.store, clock=lambda: 0).create(p)
    key = "session-" + digest(cookie)
    original = proof.store.delete
    def concurrent_update(partition, key, *, expected):
        row = proof.store.read(partition, key)
        proof.store.write(partition, key, {**row.value, "expires": 9000}, expected=row.etag)
        original(partition, key, expected=expected)
    monkeypatch.setattr(proof.store, "delete", concurrent_update)
    result = cleanup_page(proof.store, proof.artifacts, TENANT, "session", now=4000, apply=True)
    assert result["conflicts"] == 1 and result["deleted"] == 0
    assert proof.store.read(TENANT, key).value["expires"] == 9000


def test_artifact_cleanup_retries_file_failure_and_rejects_symlink(proof, tmp_path):
    from dtm_buildsheet.app.hosted.maintenance import cleanup_page
    artifacts = Artifacts(proof.store, tmp_path / "cleanup-artifacts", clock=lambda: 0)
    p = proof.tokens.verify(proof.token())
    key = artifacts.publish(p, b"synthetic bytes", "pdf")
    file = artifacts.root / (key + ".pdf")
    outside = tmp_path / "preserve.txt"
    outside.write_bytes(b"preserve")
    file.unlink()
    file.symlink_to(outside)
    result = cleanup_page(proof.store, artifacts, TENANT, "artifact", now=4000, apply=True)
    assert result["file_errors"] == 1 and result["deleted"] == 0
    assert proof.store.read(TENANT, "artifact-" + key).value["cleanup_pending"] is True
    assert outside.read_bytes() == b"preserve"
    file.unlink()
    file.write_bytes(b"synthetic bytes")
    result = cleanup_page(proof.store, artifacts, TENANT, "artifact", now=4000, apply=True)
    assert result["deleted"] == 1 and not file.exists()
    assert proof.store.read(TENANT, "artifact-" + key) is None


def test_artifact_claim_conflict_and_publish_failure_preserve_safety(proof, monkeypatch):
    from dtm_buildsheet.app.hosted.maintenance import cleanup_page
    artifacts = Artifacts(proof.store, proof.artifacts.root, clock=lambda: 0)
    p = proof.tokens.verify(proof.token())
    key = artifacts.publish(p, b"keep", "pdf")
    def fail(*args, **kwargs):
        raise Conflict("changed")
    monkeypatch.setattr(proof.store, "write", fail)
    result = cleanup_page(proof.store, artifacts, TENANT, "artifact", now=4000, apply=True)
    assert result["conflicts"] == 1
    assert (artifacts.root / (key + ".pdf")).read_bytes() == b"keep"
    with pytest.raises(Conflict):
        artifacts.publish(p, b"orphan must be removed", "pdf")
    assert len(list(artifacts.root.iterdir())) == 1


def test_job_snapshot_restore_preserves_history_and_fences_all_replay(proof, tmp_path):
    from dtm_buildsheet.app.hosted.maintenance import snapshot_jobs, restore_jobs
    p = proof.tokens.verify(proof.token())
    args = dict(kind="export", request_id="done", resource="shared", revision="1", snapshot="reviewed")
    done = proof.jobs.enqueue(p, **args)
    key, lease = proof.jobs.claim(TENANT)
    assert key == done
    proof.jobs.advance(TENANT, key, lease, authorize=lambda *a: True,
                       revision_matches=lambda *a: True, apply_step=lambda *a: True)
    pending = proof.jobs.enqueue(p, **{**args, "request_id": "pending"})
    proof.jobs.claim(TENANT)
    proof.login()
    with pytest.raises(ValueError):
        snapshot_jobs(proof.store, TENANT)
    snapshot = snapshot_jobs(proof.store, TENANT, writers_stopped=True)
    assert set(snapshot["rows"]) == {"jobs", "job-" + done}
    restored = SqliteProofStore(tmp_path / "restored.sqlite")
    with pytest.raises(ValueError):
        restore_jobs(restored, snapshot, TENANT)
    result = restore_jobs(restored, snapshot, TENANT, writers_stopped=True)
    assert result["jobs_fenced"] and result["sessions_restored"] == 0
    assert restore_jobs(restored, snapshot, TENANT, writers_stopped=True) == result
    jobs = Jobs(SqliteProofStore(restored.path))
    assert jobs.read(p, done)["state"] == "succeeded"
    assert jobs.read(p, pending)["state"] == "interrupted"
    for action in (lambda: jobs.enqueue(p, **args),
                   lambda: jobs.enqueue(p, **{**args, "request_id": "missing-from-old-backup"}),
                   lambda: jobs.claim(TENANT),
                   lambda: jobs.advance(TENANT, pending, lease, authorize=lambda *a: True,
                                        revision_matches=lambda *a: True, apply_step=lambda *a: pytest.fail("provider called"))):
        with pytest.raises(Denied, match="recovery_review_required"):
            action()
    assert restored.scan(TENANT, "session-") == []


def test_restore_damage_wrong_tenant_and_existing_destination_fail_closed(proof, tmp_path):
    from dtm_buildsheet.app.hosted.maintenance import snapshot_jobs, restore_jobs
    snapshot = snapshot_jobs(proof.store, TENANT, writers_stopped=True)
    restored = SqliteProofStore(tmp_path / "restore.sqlite")
    for damaged in ({**snapshot, "created": snapshot["created"] + 1}, {**snapshot, "tenant": OTHER}):
        with pytest.raises(ValueError):
            restore_jobs(restored, damaged, TENANT, writers_stopped=True)
    assert restored.scan(TENANT, "") == []
    restored.write(TENANT, "existing", {"keep": True}, expected=None)
    with pytest.raises(Conflict):
        restore_jobs(restored, snapshot, TENANT, writers_stopped=True)
    assert restored.read(TENANT, "existing").value == {"keep": True}


def test_restore_partial_failure_retains_fence_and_resumes(proof, tmp_path, monkeypatch):
    from dtm_buildsheet.app.hosted.maintenance import snapshot_jobs, restore_jobs
    p = proof.tokens.verify(proof.token())
    proof.jobs.enqueue(p, kind="export", request_id="once", resource="shared", revision="1", snapshot="review")
    snapshot = snapshot_jobs(proof.store, TENANT, writers_stopped=True)
    restored = SqliteProofStore(tmp_path / "restore.sqlite")
    write = restored.write
    def fail(partition, key, value, *, expected):
        if key == "jobs":
            raise OSError("simulated storage outage")
        return write(partition, key, value, expected=expected)
    monkeypatch.setattr(restored, "write", fail)
    with pytest.raises(OSError):
        restore_jobs(restored, snapshot, TENANT, writers_stopped=True)
    assert restored.read(TENANT, "recovery")
    monkeypatch.setattr(restored, "write", write)
    assert restore_jobs(restored, snapshot, TENANT, writers_stopped=True)["jobs_fenced"]


def test_safe_telemetry_contains_no_request_or_provider_details(proof, capsys):
    import logging
    from dtm_buildsheet.app.hosted.telemetry import SafeLibraryHandler
    secret = "SENSITIVE_SENTINEL_DO_NOT_LOG"
    proof.request("/" + secret, HTTP_AUTHORIZATION=secret, HTTP_COOKIE=secret, QUERY_STRING=secret)
    proof.request("/api/hosted/session", method=secret, token_value=secret, body={"secret": secret})
    a = proof.login()
    proof.documents.read = lambda *a: (_ for _ in ()).throw(RuntimeError(secret))
    response = proof.request("/api/hosted/documents/shared", **a)
    assert response["status"] == 503
    record = logging.LogRecord("azure.identity", logging.ERROR, secret, 1, secret, (), None)
    SafeLibraryHandler().emit(record)
    logs = capsys.readouterr().out
    assert secret not in logs and a["token_value"] not in logs and a["csrf"] not in logs
    rows = [json.loads(line) for line in logs.splitlines()]
    assert all(set(row) <= {"at", "event", "route", "method", "request_id", "status", "duration_ms", "source", "severity"} for row in rows)
    assert any(row.get("request_id") == response["headers"]["X-Request-ID"] and row["status"] == 503 for row in rows)
    proof.request("/healthz")
    assert capsys.readouterr().out == ""


def test_azure_maintenance_uses_bounded_partition_query_and_exact_delete():
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError
    from azure.data.tables import TableEntity
    calls = []
    class SDK:
        def query_entities(self, query, **kwargs):
            calls.append((query, kwargs))
            for i in range(3):
                row = TableEntity({"RowKey": f"session-{i:064x}", "Payload": '{}'})
                row._metadata = {"etag": str(i)}
                yield row
        def delete_entity(self, **kwargs):
            calls.append(kwargs)
            if kwargs["etag"] == "stale":
                raise ResourceModifiedError("details")
    store = AzureTableMetadata(SDK())
    assert len(store.scan(TENANT, "session-", limit=2)) == 2
    assert calls[0][1]["parameters"]["tenant"] == TENANT
    assert calls[0][1]["results_per_page"] == 2
    store.delete(TENANT, "session-key", expected="exact")
    assert calls[-1]["match_condition"] == MatchConditions.IfNotModified
    with pytest.raises(ValueError):
        store.delete(TENANT, "session-key", expected="*")
    with pytest.raises(Conflict):
        store.delete(TENANT, "session-key", expected="stale")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def proof(tmp_path, signing_key):
    store = SqliteProofStore(tmp_path / "metadata.sqlite")
    keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key()))
    tokens = EntraTokens(TENANT, CLIENT, keys)
    artifacts, jobs, documents = Artifacts(store, tmp_path / "artifacts"), Jobs(store), SyntheticDocuments(store)
    documents.seed(TENANT, "shared", [ALICE, BOB])
    documents.seed(TENANT, "private", [ALICE])
    app = Application(mode="local-proof", origin=ORIGIN, tokens=tokens, store=store,
                      artifacts=artifacts, jobs=jobs, documents=documents)

    def token(user=ALICE, roles=("BuilderEditor",), **overrides):
        now = int(time.time())
        claims = {"iss": tokens.issuer, "aud": CLIENT, "tid": TENANT, "oid": user, "sub": user,
                  "name": user, "ver": "2.0", "iat": now, "nbf": now - 1, "exp": now + 3600,
                  "roles": list(roles)}
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "synthetic-key"})

    def request(path, *, method="GET", token_value=None, cookie="", csrf="", body=None, **headers):
        raw = json.dumps(body if body is not None else {}).encode()
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "127.0.0.1:7666",
               "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": "application/json",
               "wsgi.input": io.BytesIO(raw), "HTTP_COOKIE": cookie, "HTTP_X_DTM_CSRF": csrf,
               "HTTP_ORIGIN": ORIGIN}
        if token_value is not None:
            env["HTTP_X_MS_TOKEN_AAD_ID_TOKEN"] = token_value
        env.update(headers)
        response = {}
        def start(status, returned_headers):
            response.update(status=int(status.split()[0]), headers=dict(returned_headers))
        content = b"".join(app(env, start))
        response["body"] = json.loads(content) if response["headers"]["Content-Type"] == "application/json" else content
        return response

    def login(user=ALICE, roles=("BuilderEditor",)):
        encoded = token(user, roles)
        result = request("/api/hosted/session", method="POST", token_value=encoded)
        assert result["status"] == 200
        return {"token_value": encoded, "cookie": result["headers"]["Set-Cookie"].split(";", 1)[0],
                "csrf": result["body"]["csrf"]}
    return SimpleNamespace(**locals())


def test_real_signed_identity_and_concurrent_request_context(proof):
    a, b = proof.login(), proof.login(BOB, ("ShopEditor",))
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda client: proof.request("/api/hosted/session", **client), [a, b] * 20))
    for index, response in enumerate(responses):
        assert response["status"] == 200
        assert response["body"]["user"]["user_id"] == (ALICE if index % 2 == 0 else BOB)
        assert ("projects.edit" in response["body"]["capabilities"]) == (index % 2 == 0)
    assert current_request() is None
    from dtm_buildsheet.app.adapters import wiring
    context = RequestContext(TENANT, ALICE, "request", wiring.build_local_bundle())
    with bind_request(context):
        assert wiring.get_active_bundle() is context.bundle
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(current_request).result() is None
    assert current_request() is None


@pytest.mark.parametrize("changes", [
    {"aud": OTHER}, {"iss": "https://attacker.invalid"}, {"tid": OTHER}, {"ver": "1.0"},
    {"exp": 1}, {"nbf": int(time.time()) + 3600}, {"oid": ""}, {"roles": ["unknown"]},
    {"roles": "AppAdmin"}, {"sub": ""}, {"aud": [CLIENT, OTHER]},
])
def test_invalid_claims_fail_closed(proof, changes):
    response = proof.request("/api/hosted/session", method="POST", token_value=proof.token(**changes))
    assert response["status"] in {401, 403}
    assert "Set-Cookie" not in response["headers"]


def test_forged_headers_unsigned_and_wrong_key_tokens_cannot_login(proof):
    response = proof.request("/api/hosted/session", method="POST",
                             HTTP_X_MS_CLIENT_PRINCIPAL="AppAdmin", HTTP_X_MS_CLIENT_PRINCIPAL_ID=ALICE)
    assert response["status"] == 401
    claims = jwt.decode(proof.token(), options={"verify_signature": False})
    for encoded in (jwt.encode(claims, "", algorithm="none"), jwt.encode(claims, "x" * 32, algorithm="HS256")):
        assert proof.request("/api/hosted/session", method="POST", token_value=encoded)["status"] == 401
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = jwt.encode(claims, wrong_key, algorithm="RS256", headers={"kid": "synthetic-key"})
    assert proof.request("/api/hosted/session", method="POST", token_value=encoded)["status"] == 401


def test_session_binding_expiry_revocation_rotation_and_restart(proof):
    a, b = proof.login(), proof.login(BOB)
    stolen = {**a, "token_value": b["token_value"]}
    assert proof.request("/api/hosted/session", **stolen)["status"] == 401
    # New adapter/process view retains only hashed cookie and CSRF, never a JWT.
    reopened = SqliteProofStore(proof.store.path)
    principal = proof.tokens.verify(a["token_value"])
    cookie = a["cookie"].split("=", 1)[1]
    sessions = Sessions(reopened)
    assert sessions.check(principal, cookie)
    assert cookie.encode() not in proof.store.path.read_bytes()
    assert a["token_value"].encode() not in proof.store.path.read_bytes()
    assert a["csrf"].encode() not in proof.store.path.read_bytes()
    expired = Sessions(reopened, clock=lambda: time.time() + 1801)
    with pytest.raises(Denied):
        expired.check(principal, cookie)
    result = proof.request("/api/hosted/logout", method="POST", **a)
    assert result["body"]["redirect"] == "/.auth/logout"
    assert "Max-Age=0" in result["headers"]["Set-Cookie"]
    with pytest.raises(Denied):
        sessions.check(principal, cookie)
    assert proof.request("/api/hosted/session", **b)["status"] == 200
    proof.request("/api/hosted/session", method="POST", **b)
    assert proof.request("/api/hosted/session", **b)["status"] == 401


def test_csrf_origin_host_and_role_changes(proof):
    a = proof.login()
    for headers in ({"HTTP_ORIGIN": "https://evil.test"}, {"HTTP_ORIGIN": None}, {"HTTP_X_DTM_CSRF": ""},
                    {"HTTP_SEC_FETCH_SITE": "cross-site"}, {"HTTP_HOST": "evil.test"}):
        result = proof.request("/api/hosted/documents/shared", method="PUT", body={"notes": "bad"},
                               HTTP_IF_MATCH="1", **a, **headers)
        assert result["status"] in {400, 403}
    changed_roles = {**a, "token_value": proof.token(roles=("ShopEditor",))}
    assert proof.request("/api/hosted/documents/shared", method="PUT", HTTP_IF_MATCH="1",
                         body={"notes": "bad"}, **changed_roles)["status"] == 403
    changed_roles["token_value"] = proof.token(roles=())
    assert proof.request("/api/hosted/session", **changed_roles)["status"] == 403


def test_two_editors_stale_writes_and_resource_acl(proof):
    a, b = proof.login(), proof.login(BOB)
    barrier = threading.Barrier(2)
    def edit(client):
        row = proof.request("/api/hosted/documents/shared", **client)["body"]
        barrier.wait(timeout=5)
        return proof.request("/api/hosted/documents/shared", method="PUT", HTTP_IF_MATCH=row["revision"],
                             body={"notes": client["cookie"][:10]}, **client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, [a, b]))
    assert sorted(r["status"] for r in results) == [200, 409]
    row = proof.request("/api/hosted/documents/shared", **a)["body"]
    assert row["revision"] == "2" and row["document"]["updated_by"] in {ALICE, BOB}
    assert proof.request("/api/hosted/documents/private", **b)["status"] == 404
    assert proof.request("/api/hosted/documents/shared", method="PUT", body={"notes": "x"}, **a)["status"] == 428
    assert proof.request("/api/hosted/documents/shared", method="PUT", HTTP_IF_MATCH="*", body={"notes": "x"}, **a)["status"] == 428


@pytest.mark.parametrize("path,method", [
    ("/api/cloud/status", "GET"), ("/api/operations/access", "GET"), ("/api/calendar", "POST"),
    ("/api/quickbooks/callback", "GET"), ("/api/update/install", "POST"), ("/open", "POST"),
    ("/api/draft/save", "POST"), ("/api/export/pdf", "POST"), ("/parse", "POST"),
    ("/generate", "POST"), ("/api/project/pick-output-root", "GET"), ("/ui/js/projects.js", "GET"),
    ("/assets/../../etc/passwd", "GET"), ("/api/hosted/artifacts/%2e%2e", "GET"),
    ("/api/hosted/documents/shared/", "PUT"), ("/api/new-unclassified-route", "GET"),
])
def test_legacy_and_bypass_routes_never_dispatch(proof, path, method):
    a = proof.login()
    assert proof.request(path, method=method, **a)["status"] in {400, 404}
    assert proof.request(path, method=method)["status"] in {400, 401}


def test_authorized_artifact_download_restart_missing_symlinks_and_expiry(proof, tmp_path):
    a, b = proof.login(), proof.login(BOB)
    principal = proof.tokens.verify(a["token_value"])
    key = proof.artifacts.publish(principal, b"synthetic-pdf", "pdf")
    path = "/api/hosted/artifacts/" + key
    assert proof.request(path, **a)["body"] == b"synthetic-pdf"
    assert proof.request(path, **b)["status"] == 404
    restarted = Artifacts(SqliteProofStore(proof.store.path), proof.artifacts.root)
    assert restarted.download(principal, key)[0] == b"synthetic-pdf"
    expired = Artifacts(proof.store, proof.artifacts.root, clock=lambda: time.time() + 3601)
    with pytest.raises(Denied, match="artifact_expired"):
        expired.download(principal, key)
    artifact = proof.artifacts.root / f"{key}.pdf"
    artifact.unlink()
    assert proof.request(path, **a)["status"] == 410
    secret = tmp_path / "private.txt"
    secret.write_text("never disclose")
    artifact.symlink_to(secret)
    assert proof.request(path, **a)["status"] == 410
    assert proof.request("/api/hosted/artifacts/../../private.txt", **a)["status"] == 400


def test_job_review_idempotency_ownership_and_capacity(proof):
    a, b = proof.login(), proof.login(BOB)
    body = {"kind": "export", "resource": "shared", "request_id": "review-1"}
    def enqueue(client=a, payload=body):
        return proof.request("/api/hosted/jobs", method="POST", body=payload, HTTP_IF_MATCH="1", **client)
    result = enqueue()
    key = result["body"]["job_id"]
    assert result["status"] == 202 and enqueue()["body"]["job_id"] == key
    assert proof.request("/api/hosted/jobs/" + key, **b)["status"] == 404
    assert enqueue(payload={**body, "resource": "private"})["status"] == 409
    assert enqueue(payload={**body, "resource": "../../private"})["status"] == 404
    assert enqueue(proof.login(BOB, ("ShopEditor",)))["status"] == 403
    for n in range(proof.jobs.MAX_JOBS - 1):
        assert enqueue(payload={**body, "request_id": f"new-{n}"})["status"] == 202
    assert enqueue(payload={**body, "request_id": "overflow"})["status"] == 429


def test_worker_leases_conflict_revocation_and_restart(proof):
    principal = proof.tokens.verify(proof.token())
    now = [int(time.time())]
    jobs = Jobs(proof.store, clock=lambda: now[0])
    manager = proof.tokens.verify(proof.token(roles=("OperationsManager",)))
    key = jobs.enqueue(manager, kind="calendar-save", request_id="calendar", resource="shared", revision="1", snapshot="reviewed")
    restarted = Jobs(SqliteProofStore(proof.store.path), clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: worker.claim(TENANT), [jobs, restarted]))
    assert sum(item is not None for item in claims) == 1
    _, lease = next(item for item in claims if item)
    applied = []
    state = restarted.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                              apply_step=lambda job, event: applied.append(event) or False)
    assert state == "running" and restarted.read(manager, key)["step"] == 1
    state = jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: False,
                         apply_step=lambda *_: pytest.fail("Stale write"))
    assert state == "conflict" and len(applied) == 1
    key2 = jobs.enqueue(manager, kind="calendar-save", request_id="calendar-2", resource="shared", revision="2", snapshot="fresh")
    _, lease2 = jobs.claim(TENANT)
    assert jobs.advance(TENANT, key2, lease2, authorize=lambda *_: False, revision_matches=lambda _: True,
                        apply_step=lambda *_: pytest.fail("Revoked user write")) == "denied"
    key3 = jobs.enqueue(manager, kind="calendar-save", request_id="calendar-3", resource="shared", revision="3", snapshot="fresh")
    _, lease3 = jobs.claim(TENANT)
    now[0] += 121
    assert restarted.claim(TENANT) is None
    assert restarted.read(manager, key3)["state"] == "interrupted"
    with pytest.raises(Conflict):
        jobs.advance(TENANT, key3, lease3, authorize=lambda *_: True, revision_matches=lambda _: True,
                     apply_step=lambda *_: pytest.fail("Expired worker write"))


def test_worker_failure_stops_and_completed_job_is_not_replayed(proof):
    principal = proof.tokens.verify(proof.token())
    key = proof.jobs.enqueue(principal, kind="export", request_id="r", resource="shared", revision="1", snapshot="s")
    _, lease = proof.jobs.claim(TENANT)
    assert proof.jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                              apply_step=lambda *_: True) == "succeeded"
    assert proof.jobs.claim(TENANT) is None
    assert proof.jobs.enqueue(principal, kind="export", request_id="r", resource="shared", revision="1", snapshot="s") == key
    key = proof.jobs.enqueue(principal, kind="export", request_id="failed", resource="shared", revision="1", snapshot="s")
    _, lease = proof.jobs.claim(TENANT)
    def fail(*_):
        raise RuntimeError("secret provider error must not be persisted")
    assert proof.jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                              apply_step=fail) == "failed"
    assert "secret" not in json.dumps(proof.jobs.read(principal, key))


def test_archive_survives_copy_remove_crash_and_keeps_idempotency(proof, monkeypatch):
    principal = proof.tokens.verify(proof.token())
    key = proof.jobs.enqueue(principal, kind="export", request_id="r", resource="shared", revision="1", snapshot="s")
    _, lease = proof.jobs.claim(TENANT)
    proof.jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                       apply_step=lambda *_: True)
    write = proof.store.write
    def fail_after_copy(tenant, row_key, value, *, expected):
        if row_key == "jobs":
            raise RuntimeError("simulated crash after immutable archive write")
        return write(tenant, row_key, value, expected=expected)
    monkeypatch.setattr(proof.store, "write", fail_after_copy)
    with pytest.raises(RuntimeError):
        proof.jobs.archive_terminal(TENANT)
    restarted = Jobs(SqliteProofStore(proof.store.path))
    restarted.archive_terminal(TENANT)
    assert restarted.read(principal, key)["state"] == "succeeded"
    assert restarted.enqueue(principal, kind="export", request_id="r", resource="shared", revision="1", snapshot="s") == key
    assert restarted.claim(TENANT) is None
    with pytest.raises(Conflict):
        restarted.enqueue(principal, kind="export", request_id="r", resource="shared", revision="2", snapshot="new")


def test_maximum_bounded_queue_fits_table_property(proof):
    principal = proof.tokens.verify(proof.token())
    for n in range(proof.jobs.MAX_JOBS):
        proof.jobs.enqueue(principal, kind="export", request_id=str(n), resource="r" * 160,
                           revision="v" * 160, snapshot="s" * 160)
    for _ in range(proof.jobs.MAX_JOBS):
        key, lease = proof.jobs.claim(TENANT)
        for _ in range(64):
            assert proof.jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                                      apply_step=lambda *_: False) == "running"
        assert proof.jobs.advance(TENANT, key, lease, authorize=lambda *_: True, revision_matches=lambda _: True,
                                  apply_step=lambda *_: pytest.fail("Step cap exceeded")) == "failed"


def test_legacy_route_inventory_remains_closed(proof):
    import ast
    from pathlib import Path
    from dtm_buildsheet.app import server
    files = [Path(server.__file__), *Path(server.__file__).with_name("routes").glob("*.py")]
    paths = {node.value for file in files for node in ast.walk(ast.parse(file.read_text()))
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith(("/api/", "/assets/", "/ui/"))}
    assert len(paths) > 100
    client = proof.login()
    for path in paths:
        for method in ("GET", "POST", "PUT"):
            assert proof.request(path, method=method, **client)["status"] in {400, 404}, (method, path)


def test_different_tenant_cannot_resolve_session_document_job_or_artifact(proof):
    from dataclasses import replace
    client = proof.login()
    principal = proof.tokens.verify(client["token_value"])
    other_tenant = replace(principal, tenant=OTHER)
    key = proof.artifacts.publish(principal, b"private", "pdf")
    with pytest.raises(Denied):
        proof.artifacts.download(other_tenant, key)
    with pytest.raises(Denied):
        proof.app.sessions.check(other_tenant, client["cookie"].split("=", 1)[1])
    with pytest.raises(Denied):
        proof.documents.read(other_tenant, "shared")
    job = proof.jobs.enqueue(principal, kind="export", request_id="r", resource="shared", revision="1", snapshot="s")
    with pytest.raises(Denied):
        proof.jobs.read(other_tenant, job)


def test_hosted_mode_and_deployment_markers_reject_local_adapters(proof, monkeypatch):
    from dtm_buildsheet.app.adapters import wiring
    monkeypatch.setenv("DTM_RUNTIME_MODE", "hosted")
    for operation in (wiring.get_active_bundle, wiring.build_local_bundle, lambda: wiring.set_active_bundle(None)):
        with pytest.raises(RuntimeError):
            operation()
    with pytest.raises(ValueError):
        SqliteProofStore(proof.store.path)
    with pytest.raises(ValueError):
        Application(mode="local-proof", origin=ORIGIN, tokens=proof.tokens, store=proof.store,
                    artifacts=proof.artifacts, jobs=proof.jobs)
    with pytest.raises(ValueError):
        Application(mode="hosted", origin="https://builder.example", tokens=proof.tokens, store=proof.store,
                    artifacts=proof.artifacts, jobs=proof.jobs)
    monkeypatch.delenv("DTM_RUNTIME_MODE")
    monkeypatch.setenv("CONTAINER_APP_NAME", "deployed")
    with pytest.raises(RuntimeError):
        wiring.get_active_bundle()


def test_azure_table_adapter_uses_exact_sdk_preconditions_and_safe_limits(proof):
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError, ResourceModifiedError
    from azure.data.tables import TableEntity, UpdateMode
    calls = []
    class FakeSdk:
        def get_entity(self, **kwargs):
            row = TableEntity({"Payload": '{"ok":true}'})
            row._metadata = {"etag": 'W/"3"'}
            return row
        def create_entity(self, row):
            calls.append(("create", row))
            return {"etag": 'W/"1"'}
        def update_entity(self, row, **kwargs):
            calls.append(("update", kwargs))
            return {"etag": 'W/"4"'}
    client = FakeSdk()
    store = AzureTableMetadata(client)
    assert store.read(TENANT, "session").etag == 'W/"3"'
    assert store.write(TENANT, "s", {}, expected=None) == 'W/"1"'
    assert store.write(TENANT, "s", {}, expected='W/"3"') == 'W/"4"'
    assert calls[-1][1] == {"mode": UpdateMode.REPLACE, "etag": 'W/"3"', "match_condition": MatchConditions.IfNotModified}
    with pytest.raises(ValueError):
        store.write(TENANT, "s", {}, expected="*")
    with pytest.raises(ValueError):
        store.write(TENANT, "s", {"huge": "x" * 40000}, expected=None)
    for exception in (ResourceExistsError, ResourceModifiedError, ResourceNotFoundError):
        def fail(*args, **kwargs):
            raise exception("provider details")
        client.update_entity = fail
        with pytest.raises(Conflict):
            store.write(TENANT, "s", {}, expected="stale")


def test_health_body_limit_methods_no_fallback_and_cookie_flags(proof):
    assert proof.request("/healthz")["body"] == {"ok": True}
    assert proof.request("/healthz", method="TRACE")["status"] == 405
    a = proof.login()
    assert proof.request("/api/hosted/documents/shared", method="PUT", HTTP_IF_MATCH="1",
                         body={"notes": "x" * 65536}, **a)["status"] == 413
    proof.app.documents = None
    assert proof.request("/api/hosted/documents/shared", **a)["status"] == 503
    proof.app.mode = "hosted"
    proof.app.cookie_name = "__Host-dtm-session"
    cookie = proof.app._set_cookie("opaque", 1800)[1]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Domain=" not in cookie


def test_real_waitress_http_boundary(proof):
    from waitress import create_server
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    server = create_server(proof.app, host="127.0.0.1", port=0, threads=2, max_request_body_size=65536)
    origin = f"http://127.0.0.1:{server.effective_port}"
    proof.app.authority, proof.app.origin = origin.removeprefix("http://"), origin
    stopped = threading.Event()
    def run():
        # Stop the event loop before closing descriptors; avoid a shutdown race
        # in select() when the test tears down its real HTTP listener.
        while not stopped.is_set():
            # Combined desktop suites can allocate descriptors beyond select()'s
            # FD_SETSIZE. poll() keeps this HTTP/auth test independent of FD numbers.
            server.asyncore.loop(timeout=0.05, use_poll=True, count=1, map=server._map)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        with urlopen(origin + "/healthz", timeout=5) as response:
            assert json.load(response) == {"ok": True}
        with pytest.raises(HTTPError) as error:
            urlopen(origin + "/api/hosted/session", timeout=5)
        assert error.value.code == 401
        request = Request(origin + "/api/hosted/session", data=b"{}", headers={
            "Content-Type": "application/json", "Origin": origin, "X-MS-TOKEN-AAD-ID-TOKEN": proof.token(),
        })
        with urlopen(request, timeout=5) as response:
            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            assert json.load(response)["csrf"]
        request = Request(origin + "/api/hosted/session", headers={
            "Cookie": cookie, "X-MS-TOKEN-AAD-ID-TOKEN": proof.token(),
        })
        with urlopen(request, timeout=5) as response:
            assert json.load(response)["user"]["user_id"] == ALICE
    finally:
        stopped.set()
        thread.join(timeout=3)
        server.task_dispatcher.shutdown(timeout=2)
        server.close()
        assert not thread.is_alive()
