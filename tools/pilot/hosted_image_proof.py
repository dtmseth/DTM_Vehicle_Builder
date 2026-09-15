#!/usr/bin/env python3
"""Exercise the real hosted factory in a network-disabled local AMD64 container.

No Azure resources, fake auth switch, host mounts, ports or credentials. Synthetic
configuration lets the real lazy SDK factory start; no metadata call is permitted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

NAME = "dtm-hosted-readiness-proof"
IMAGE = "dtm-hosted-boundary:local"
CHECK = r'''
import json,urllib.request,urllib.error
responses=[]
for path,headers in [('/healthz',{}),('/api/hosted/session',{}),('/',{}),
 ('/api/hosted/session',{'X-MS-CLIENT-PRINCIPAL':'AppAdmin','X-MS-CLIENT-PRINCIPAL-ID':'fake'}),
 ('/api/hosted/session',{'X-MS-TOKEN-AAD-ID-TOKEN':'SENSITIVE_SENTINEL_DO_NOT_LOG'})]:
    request=urllib.request.Request('http://127.0.0.1:8080'+path,headers={'Host':'pilot.invalid',**headers})
    try: response=urllib.request.urlopen(request,timeout=3)
    except urllib.error.HTTPError as exc: response=exc
    with response:
        body=json.load(response)
        responses.append({'path':path,'status':response.status,'body':body,
                          'cache':response.headers.get('Cache-Control')})
assert [r['status'] for r in responses]==[200,401,401,401,401],responses
assert responses[0]['body']=={'ok':True}
assert all(r['cache']=='no-store' for r in responses)
print(json.dumps(responses))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-host", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    results = args.results.resolve()
    if not args.docker_host.startswith("unix://") or results.is_relative_to(root) or results.exists():
        parser.error("Use a local Unix socket and new external results directory")
    env = dict(os.environ, DOCKER_HOST=args.docker_host)
    def run(*command, check=True):
        return subprocess.run(["docker", *command], env=env, text=True, capture_output=True,
                              timeout=90, check=check)
    if run("container", "inspect", NAME, check=False).returncode == 0:
        raise ValueError("Proof container already exists; inspect first")
    results.mkdir(parents=True)
    image = json.loads(run("image", "inspect", IMAGE).stdout)[0]
    assert image["Os"] == "linux" and image["Architecture"] == "amd64"
    report = {"ok": False, "image": {k: image[k] for k in ("Id", "Size", "Architecture", "Os")}}
    container = None
    try:
        common = ["--platform", "linux/amd64", "--network", "none", "--read-only", "--cap-drop", "ALL",
                  "--security-opt", "no-new-privileges:true", "--cpus", "0.5", "--memory", "512m",
                  "--pids-limit", "64", "--tmpfs", "/tmp:size=128m,mode=1777"]
        invalid = run("run", "--rm", *common, IMAGE, check=False)
        assert invalid.returncode == 1 and "startup_failed" in invalid.stdout
        assert not invalid.stderr and "Traceback" not in invalid.stdout
        report["missing_configuration_denied"] = True
        configuration = {
            "DTM_HOSTED_ORIGIN": "https://pilot.invalid",
            "DTM_HOSTED_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "DTM_HOSTED_CLIENT_ID": "22222222-2222-4222-8222-222222222222",
            "DTM_METADATA_ACCOUNT": "syntheticpilot",
            "DTM_METADATA_TABLE": "SyntheticMetadata",
            "DTM_METADATA_IDENTITY_CLIENT_ID": "33333333-3333-4333-8333-333333333333",
        }
        flags = [arg for key, value in configuration.items() for arg in ("-e", f"{key}={value}")]
        started = time.monotonic()
        container = run("run", "-d", "--name", NAME, *common, *flags, IMAGE).stdout.strip()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = run("exec", container, "python", "-c", CHECK, check=False)
            if result.returncode == 0:
                report["responses"] = json.loads(result.stdout)
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Hosted HTTP proof failed")
        report["startup_and_negative_checks_seconds"] = round(time.monotonic() - started, 3)
        info = json.loads(run("inspect", container).stdout)[0]
        assert info["Image"] == image["Id"] and info["Config"]["User"] == "10001:10001"
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert info["HostConfig"]["ReadonlyRootfs"] and not info["HostConfig"]["PortBindings"]
        assert not info["Mounts"] and not info["State"]["OOMKilled"]
        report["network_disabled"] = report["nonroot_readonly_no_mounts_or_ports"] = True
        runtime = run("exec", container, "python", "-c", """
import importlib.util,json,os,pathlib,platform
import dtm_buildsheet
root=pathlib.Path(dtm_buildsheet.__file__).parent
assert not (root/'ui').exists() and not (root/'resources').exists()
assert importlib.util.find_spec('dtm_buildsheet.headless') is None
assert importlib.util.find_spec('dtm_buildsheet.pilot_fixtures') is None
print(json.dumps({'python':platform.python_version(),'uid':os.getuid(),'fixtures_assets_absent':True}))
""")
        report["runtime"] = json.loads(runtime.stdout)
        report["dependencies"] = run("exec", container, "python", "-m", "pip", "check").stdout.strip()
        before = run("exec", container, "python", "-c", "from pathlib import Path; print(Path('/sys/fs/cgroup/memory.current').read_text())")
        report["observed_memory_mib"] = round(int(before.stdout) / 1024**2, 2)
        run("restart", "--time", "10", container)
        for _ in range(60):
            if run("exec", container, "python", "-c", CHECK, check=False).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Restart proof failed")
        report["restart_verified"] = True
        logs = run("logs", container)
        all_logs = logs.stdout + logs.stderr
        (results / "container.log").write_text(all_logs)
        assert "SENSITIVE_SENTINEL" not in all_logs and "Traceback" not in all_logs
        for line in all_logs.splitlines():
            record = json.loads(line)
            assert set(record) <= {"at", "event", "route", "method", "request_id", "status", "duration_ms", "source", "severity"}
        report["safe_log_schema_verified"] = report["ok"] = True
    finally:
        if container:
            run("stop", "--time", "10", container)
            run("rm", container)
            report["container_removed"] = True
        (results / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": report["ok"], "results": str(results), "image_bytes": image["Size"]}))


if __name__ == "__main__":
    main()
