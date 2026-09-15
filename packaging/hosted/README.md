# Stage 2 boundary — local image and review files, no deployment

The desktop/headless prototype and the hosted boundary are separate launch paths. The existing
Builder UI still runs through Stage 1 locally. The WSGI boundary exposes only the small authenticated
contract described in [HOSTED_BOUNDARY.md](../../docs/HOSTED_BOUNDARY.md); legacy business routes
are closed. It is not a deployable full Builder or a new mobile UI.

Local verification (synthetic RSA-signed users, disposable SQLite metadata and loopback Waitress):

```bash
.venv/bin/pip install -e '.[dev,hosted]'
DTM_CLOUD=0 .venv/bin/python tools/verify.py changed
```

`tests/test_hosted_boundary.py` starts/stops its own HTTP listener. Its synthetic adapters live
under `tools/pilot/shared_user_fixtures.py`, outside the wheel and container build context. No
Azure credentials, tenant, role assignments, trial or resources are needed. The test uses the
same JWT verification, sessions, WSGI routes, queue and artifact code as the production factory;
only the signing-key source and backing provider adapters are synthetic.

Selected HTTP arrangement: Waitress behind Container Apps HTTPS/auth ingress, bounded requests,
no trusted client Forwarded headers. The factory only accepts explicit hosted configuration and
uses managed identity for metadata, never developer CLI credentials. Its optional dependencies
do not change the desktop installer. `bootstrap.main()` defaults to loopback; the separate image
explicitly passes `--host 0.0.0.0` for its internal ingress interface, with no alternate public listener.
Do not use `headless.py`, `ThreadingHTTPServer`, or the Stage 1 image as the public server.

`Dockerfile` and `requirements.lock` define the separate Python-only hosted boundary. Stage it
with `tools/pilot/hosted_build_context.py`; never build from the checkout. The AMD64 image passed
the real startup, fail-closed HTTP, restart and safe-log checks under `--network none`, non-root,
read-only filesystem, no mounts/ports, 0.5 CPU and 512 MiB. No cloud connectivity is implied.
See [HOSTED_OPERATIONS.md](../../docs/HOSTED_OPERATIONS.md) for exact build/proof commands,
expiry cleanup, fenced job recovery, retention proposals and monitoring limits.

`auth-config.review.json` is an unsubmitted ARM auth subresource template. It requires the
specific pilot app, tenant, staff object IDs and secret **names**, with no credential values.
`deployment-contract.json` records the other settings and gates; it is not an ARM deployment.
No cloud validation or template submission has occurred. Enterprise-app assignment must also
be required in Entra; configure existing DTM app roles there. Keep token-store secrets scoped
separately from the Table managed identity and source records.

References checked for this design:

- [Container Apps Entra auth](https://learn.microsoft.com/en-us/azure/container-apps/authentication-entra)
- [Auth resource schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/containerapps/authconfigs)
- [Token store](https://learn.microsoft.com/en-us/azure/container-apps/token-store)
- [Table SDK conditional updates](https://learn.microsoft.com/en-us/python/api/azure-data-tables/azure.data.tables.tableclient?view=azure-python)
- [Waitress limits and proxy settings](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html)
