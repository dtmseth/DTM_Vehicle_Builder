#!/usr/bin/env python3
"""Measure a prebuilt Stage 1 image on an explicitly selected local Docker engine.

Uses only the staged compose context and its named synthetic volume. Does not
install/build/pull/deploy, bind-mount host files, or remove volumes. Always stops
its compose services. Detailed logs/results stay outside the checkout.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = """
import json,time
from pathlib import Path
p=Path('/sys/fs/cgroup')
while True:
    cpu=dict(line.split() for line in (p/'cpu.stat').read_text().splitlines())
    print(json.dumps({'at':time.monotonic(),'memory':int((p/'memory.current').read_text()),
                      'cpu_usec':int(cpu['usage_usec'])}),flush=True)
    time.sleep(.2)
"""


class Proof:
    def __init__(self, args):
        self.args = args
        self.env = dict(os.environ, DOCKER_HOST=args.docker_host, DTM_CLOUD="0",
                        DOCKER_DEFAULT_PLATFORM=args.platform)
        self.compose = ["docker", "compose", "--project-directory", str(args.context)]
        self.results = args.results
        self.report = {"environment": "local Linux VM; not Azure performance",
                       "requested_platform": args.platform, "ok": False}

    def run(self, command, *, timeout=180, **kwargs):
        return subprocess.run(command, env=self.env, capture_output=True, text=True,
                              check=True, timeout=timeout, **kwargs).stdout.strip()

    def inspect(self):
        return json.loads(self.run(["docker", "inspect", self.container]))[0]

    def execute(self, *command):
        return self.run(["docker", "exec", self.container, *command])

    def health(self):
        with urlopen("http://127.0.0.1:7665/healthz", timeout=2) as response:
            return json.load(response)

    def wait_health(self):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if self.health()["ok"]:
                    return
            except Exception:
                pass
            time.sleep(.2)
        raise RuntimeError("Container did not become reachable; inspect container.log")

    def start(self, cpus, memory):
        self.env.update(PILOT_CPUS=str(cpus), PILOT_MEMORY=memory)
        started = time.monotonic()
        self.run([*self.compose, "up", "-d", "--no-build", "--pull", "never", "--force-recreate"])
        self.container = self.run([*self.compose, "ps", "-q", "builder"])
        self.wait_health()
        elapsed = time.monotonic() - started
        info = self.inspect()
        assert info["Image"] == self.image_id, "Builder did not start the inspected image"
        host = info["HostConfig"]
        expected_memory = {"1g": 1024**3, "2g": 2 * 1024**3}[memory]
        assert host["Memory"] == expected_memory and host["NanoCpus"] == int(cpus * 1e9)
        assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
        assert all(mount["Type"] != "bind" for mount in info["Mounts"])
        assert set(info["NetworkSettings"]["Networks"]) == {"dtm-local-pilot_isolated"}
        relay = self.run([*self.compose, "ps", "-q", "relay"])
        relay_info = json.loads(self.run(["docker", "inspect", relay]))[0]
        assert relay_info["Image"] == self.image_id, "Relay did not start the inspected image"
        assert relay_info["NetworkSettings"]["Ports"]["7665/tcp"][0]["HostIp"] == "127.0.0.1"
        return round(elapsed, 3)

    def cgroup(self):
        return json.loads(self.execute("python", "-c", """
import json
from pathlib import Path
p=Path('/sys/fs/cgroup')
print(json.dumps({name:(p/name).read_text().strip() for name in
 ['memory.current','memory.peak','memory.max','memory.events','cpu.max','cpu.stat']}))
"""))

    def sampled_exercise(self, label, *, ui_only):
        log = self.results / f"{label}-cgroup.jsonl"
        with log.open("w") as stream:
            sampler = subprocess.Popen(["docker", "exec", self.container, "python", "-c", SAMPLE],
                                       env=self.env, stdout=stream, stderr=subprocess.DEVNULL)
            try:
                command = [sys.executable, str(ROOT / "tools/pilot/exercise.py"),
                           "--url", "http://127.0.0.1:7665", "--results", str(self.results / label)]
                if ui_only:
                    command.append("--ui-only")
                result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=360)
                (self.results / f"{label}-client.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(f"{label} failed; inspect {label}-client.log")
            finally:
                sampler.terminate()
                sampler.wait(timeout=10)
                # Killing docker exec's client may leave its process alive. This
                # exact sampler argv is unique, and only runs in our container.
                self.execute("python", "-c", """
import os
from pathlib import Path
for p in Path('/proc').iterdir():
    if p.name.isdigit() and int(p.name)!=os.getpid():
        try:
            args=(p/'cmdline').read_bytes().split(b'\\0')
            if len(args)>2 and args[1]==b'-c' and args[2].startswith(b'\\nimport json,time\\n'):
                os.kill(int(p.name),15)
        except (OSError,ProcessLookupError): pass
""")
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        assert rows
        report = json.loads((self.results / label / "results.json").read_text())
        report.update(container_sizing_verified=True, cgroup=self.cgroup(),
                      sampled_peak_cgroup_mib=round(max(r["memory"] for r in rows) / 1024**2, 2))
        assert "oom_kill 0" in report["cgroup"]["memory.events"]
        return report

    def perform(self):
        # Refuse to take over an existing project/container, even one with our name.
        if self.run([*self.compose, "ps", "-aq"]):
            raise ValueError("Pilot compose project already exists; inspect it first")
        image = json.loads(self.run(["docker", "image", "inspect", "dtm-local-pilot:stage1"]))[0]
        assert f"{image['Os']}/{image['Architecture']}" == self.args.platform, "Wrong image architecture"
        self.image_id = image["Id"]
        self.report["image"] = {k: image[k] for k in ("Id", "Architecture", "Os", "Size")}
        try:
            self.report["first_start_seconds"] = self.start(.5, "1g")
            self.report["runtime"] = {
                "kernel": self.execute("uname", "-a"), "uid": self.execute("id"),
                "python": self.execute("python", "--version"),
                "libreoffice": self.execute("soffice", "--version"),
                "calibri_substitute": self.execute("fc-match", "Calibri"),
                "dependencies": self.execute("python", "-m", "pip", "check"),
            }
            (self.results / "debian-packages.txt").write_text(self.execute("dpkg-query", "-W") + "\n")
            before = self.cgroup()
            started = time.monotonic()
            time.sleep(5)
            after = self.cgroup()
            cpu = lambda d: int(dict(line.split() for line in d["cpu.stat"].splitlines())["usage_usec"])
            self.report["idle"] = {
                "cgroup_memory_mib": round(int(after["memory.current"]) / 1024**2, 2),
                "cpu_percent_one_core": round((cpu(after) - cpu(before)) / ((time.monotonic() - started) * 10000), 2),
            }
            self.report["interactive_0.5cpu_1g"] = self.sampled_exercise("interactive", ui_only=True)
            draft_hash = """
import hashlib,json
from pathlib import Path
print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
Path('/pilot-data/workspace/drafts').glob('*.json')}))
"""
            before = self.execute("python", "-c", draft_hash)
            assert json.loads(before), "No persisted draft hashes"
            started = time.monotonic()
            self.run([*self.compose, "restart", "builder"])
            self.wait_health()
            self.report["restart_seconds"] = round(time.monotonic() - started, 3)
            assert self.execute("python", "-c", draft_hash) == before
            self.report["restart_preserved_edits"] = True
            self.report["export_configuration_start_seconds"] = self.start(1, "2g")
            self.report["exports_1cpu_2g"] = self.sampled_exercise("exports", ui_only=False)
            self.report["egress"] = json.loads(self.execute("python", "-c", """
import socket,json
results={}
for name in ('graph.microsoft.com','quickbooks.api.intuit.com','1.1.1.1'):
    try:
        s=socket.create_connection((name,443),timeout=2)
        s.close()
        results[name]='unexpected_connection'
    except OSError:
        results[name]='blocked'
print(json.dumps(results))
"""))
            assert set(self.report["egress"].values()) == {"blocked"}
            network = self.run(["docker", "network", "inspect", "dtm-local-pilot_isolated"])
            assert json.loads(network)[0]["Internal"] is True
            self.report["internal_network"] = True
            info = self.inspect()
            assert not info["State"]["OOMKilled"]
            self.report["ok"] = True
        finally:
            try:
                if getattr(self, "container", None):
                    logs = subprocess.run(["docker", "logs", self.container], env=self.env,
                                          capture_output=True, text=True, timeout=15)
                    (self.results / "container.log").write_text(logs.stdout + logs.stderr)
            finally:
                try:
                    self.run([*self.compose, "down"], timeout=180)
                    self.report["containers_stopped"] = True
                finally:
                    (self.results / "container-results.json").write_text(json.dumps(self.report, indent=2) + "\n")
        print(json.dumps({"ok": self.report["ok"], "results": str(self.results),
                          "architecture": image["Architecture"], "image_bytes": image["Size"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--docker-host", required=True, help="Explicit local unix:// Docker socket")
    parser.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"),
                        help="Required image architecture; verified before starting services")
    args = parser.parse_args()
    if not args.docker_host.startswith("unix://"):
        parser.error("Only a local Unix socket is allowed")
    for name in ("context", "results"):
        path = getattr(args, name).resolve()
        if path.is_relative_to(ROOT):
            parser.error("Context/results must remain outside the checkout")
        setattr(args, name, path)
    if not (args.context / "context-manifest.json").is_file():
        parser.error("Use tools/pilot/build_context.py first")
    # Check staged compose identity and content against the repository before
    # authorizing commands that can start/stop a compose project.
    for name in ("compose.yaml", "Dockerfile"):
        if (args.context / name).read_bytes() != (ROOT / "packaging/pilot" / name).read_bytes():
            parser.error(f"Staged {name} differs from reviewed pilot configuration")
    args.results.mkdir(parents=True, exist_ok=False)
    Proof(args).perform()


if __name__ == "__main__":
    main()
