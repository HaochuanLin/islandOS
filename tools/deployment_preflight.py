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
