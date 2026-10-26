#!/usr/bin/env python3
"""Fail-closed configuration checks for the local IslandOS research/demo deployment.

This static preflight is not a production authorization or a running-service test.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path


def run_checks(root: Path) -> list[dict[str, str]]:
    root = root.resolve()

    def read(path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8")
        except OSError:
            return ""

    docker = read("Dockerfile")
    compose = read("docker-compose.yml")
    lock = read("requirements-runtime.lock")
    workflow = read(".github/workflows/container-web-smoke.yml")
    runbook = read("docs/DEMO_DEPLOYMENT.md").lower()
    security = read("SECURITY.md").lower()
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    add("runtime_lock_present", bool(lock.strip()), "runtime lock exists" if lock.strip() else "requirements-runtime.lock missing or empty")
    match = re.search(r"(?m)^FROM\s+(\S+)$", docker)
    base = match.group(1) if match else ""
    pinned = bool(re.fullmatch(r"python:3\.11\.17-slim-trixie@sha256:[0-9a-f]{64}", base))
    add("base_image_digest_pinned", pinned, "immutable Python base digest is pinned" if pinned else "versioned Python base image must be pinned by SHA-256 digest")
    nonroot = bool(re.search(r"(?m)^USER\s+islandos\s*$", docker))
    add("container_non_root", nonroot, "container declares non-root runtime user" if nonroot else "Dockerfile must declare USER islandos")
    loopback = bool(re.search(r'(?m)^\s*-\s*"127\.0\.0\.1:8501:8501"\s*$', compose))
    wildcard = bool(re.search(r'(?m)^\s*-\s*"(?:0\.0\.0\.0|:::):8501:8501"\s*$', compose))
    add("compose_loopback_only", loopback and not wildcard, "web port binds to loopback only" if loopback and not wildcard else "Compose must bind 127.0.0.1:8501:8501 only")
    least_privilege = all(token in compose for token in ("init: true", "no-new-privileges:true", "cap_drop:", "- ALL"))
    add("compose_least_privilege", least_privilege, "Compose drops Linux capabilities and disables privilege escalation" if least_privilege else "Compose must set init: true, no-new-privileges:true, and cap_drop: [ALL]")
    read_only = bool(re.search(r"(?m)^\s*read_only:\s*true\s*$", compose))
    add("compose_read_only_rootfs", read_only, "container root filesystem is read-only" if read_only else "Compose must set read_only: true")
    tmpfs = "/tmp:rw,noexec,nosuid,size=128m" in compose
    add("compose_ephemeral_tmpfs", tmpfs, "transient writes are limited to a no-exec tmpfs" if tmpfs else "Compose must mount /tmp as a bounded noexec/nosuid tmpfs")
    resource_limits = all(token in compose for token in ("mem_limit: 1g", "cpus: 1.0", "pids_limit: 128"))
    add("compose_resource_limits", resource_limits, "memory, CPU, and process count are bounded" if resource_limits else "Compose must bound memory, CPU, and PID count")
    log_rotation = all(token in compose for token in ('max-size: "10m"', 'max-file: "3"'))
    add("compose_log_rotation", log_rotation, "container logs have bounded size and file count" if log_rotation else "Compose must cap JSON logs at 10 MB x 3 files")
    graceful_stop = "stop_grace_period: 20s" in compose
    add("compose_graceful_stop", graceful_stop, "container has a bounded graceful shutdown window" if graceful_stop else "Compose must declare stop_grace_period: 20s")
    ephemeral_caches = all(token in compose for token in (
        "HOME: /tmp/islandos-home", "XDG_CACHE_HOME: /tmp/xdg-cache",
        "MPLCONFIGDIR: /tmp/matplotlib", 'STREAMLIT_BROWSER_GATHER_USAGE_STATS: "false"',
    ))
    add("compose_ephemeral_cache_paths", ephemeral_caches, "application caches are redirected to ephemeral storage" if ephemeral_caches else "Compose must redirect writable caches to /tmp and disable Streamlit usage telemetry")
    runtime_hardening = all(token in workflow for token in (
        "--read-only", "--tmpfs /tmp:rw,noexec,nosuid,size=128m",
        "--memory=1g", "--cpus=1", "--pids-limit=128",
        "--stop-timeout 20", "--log-opt max-size=10m", "--log-opt max-file=3",
        "config[\"ReadonlyRootfs\"] is True", 'config["Memory"] == 1073741824',
        'config["NanoCpus"] == 1000000000', 'config["PidsLimit"] == 128',
        'config["LogConfig"]["Config"]["max-size"] == "10m"',
        'config["LogConfig"]["Config"]["max-file"] == "3"',
    ))
    add("ci_runtime_hardening_verified", runtime_hardening, "CI runs and inspects a read-only, resource-bounded container" if runtime_hardening else "container smoke CI must verify read-only root, tmpfs, memory, CPU, and PID limits")
    compose_ci = "docker compose config --quiet" in workflow
    add("compose_schema_checked_in_ci", compose_ci, "CI validates the Compose configuration" if compose_ci else "container smoke workflow must run docker compose config --quiet")
    health = "HEALTHCHECK" in docker and "/_stcore/health" in docker
    add("container_healthcheck", health, "Streamlit health check is configured" if health else "Docker health check missing")
    sbom = all(x in workflow for x in ("anchore/sbom-action@", "image: islandos-web:ci", "format: cyclonedx-json", "output-file: build/sbom/islandos-web-image.cdx.json", "upload-artifact-retention: 30"))
    add("container_sbom", sbom, "CycloneDX image SBOM is generated and retained" if sbom else "container image SBOM or 30-day retention is missing")
    docs = all(x in runbook for x in ("research/demo deployment only", "not yet established", "authentication", "127.0.0.1"))
    add("deployment_boundary_documented", docs, "runbook states local demo boundary and production gaps" if docs else "runbook must state demo-only scope, authentication gap, and loopback binding")
    security_ok = all(x in security for x in ("not a production service", "not be connected directly", "image signing"))
    add("security_gaps_documented", security_ok, "prototype and signing limitations are documented" if security_ok else "security policy must state prototype boundary and image-signing gap")
    try:
        rev = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, check=True, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    rev_ok = bool(re.fullmatch(r"[0-9a-f]{40}", rev))
    add("git_revision_recorded", rev_ok, f"checkout revision: {rev}" if rev_ok else "run from a Git checkout with a resolvable HEAD SHA")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="emit JSON for automation")
    args = parser.parse_args()
    checks = run_checks(args.root)
    failed = sum(item["status"] != "pass" for item in checks)
    report = {"scope": "local research/demo configuration only", "production_authorized": False, "passed": len(checks)-failed, "failed": failed, "checks": checks}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("IslandOS local deployment preflight (not production authorization)")
        for item in checks:
            print(f"[{item['status'].upper()}] {item['name']}: {item['detail']}")
        print(f"Result: {report['passed']} passed, {report['failed']} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
