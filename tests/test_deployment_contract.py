"""Regression checks for the local deployment/security contract.

These checks guard the repository's documented research-demo exposure boundary;
they do not certify a production deployment.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_docker_build_installs_exact_runtime_lock(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements-runtime.lock ./requirements-runtime.lock", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements-runtime.lock", dockerfile)
        self.assertNotIn("pip install --no-cache-dir -r requirements.txt", dockerfile)

    def test_docker_base_image_uses_versioned_python_and_debian_release(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.11.17-slim-trixie", dockerfile)
        self.assertNotIn("FROM python:3.11-slim", dockerfile)

    def test_docker_base_image_is_pinned_to_an_immutable_digest(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            r"(?m)^FROM python:3\.11\.17-slim-trixie@sha256:[0-9a-f]{64}$",
        )

    def test_dependabot_checks_docker_base_image_updates(self):
        dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: docker", dependabot)
        self.assertIn("interval: weekly", dependabot)

    def test_container_drops_root_privileges(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER\s+islandos\s*$")

    def test_container_has_healthcheck(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("/_stcore/health", dockerfile)

    def test_compose_publishes_only_on_loopback(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertRegex(compose, r'(?m)^\s*-\s*"127\.0\.0\.1:8501:8501"\s*$')
        self.assertNotRegex(compose, r'(?m)^\s*-\s*"0\.0\.0\.0:8501:8501"\s*$')

    def test_compose_uses_least_privilege_security_options(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("init: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn("      - ALL", compose)
        workflow = (ROOT / ".github/workflows/container-web-smoke.yml").read_text(encoding="utf-8")
        self.assertIn("docker compose config --quiet", workflow)

    def test_compose_uses_read_only_filesystem_ephemeral_storage_and_resource_limits(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for token in (
            "read_only: true",
            "/tmp:rw,noexec,nosuid,size=128m",
            "mem_limit: 1g",
            "cpus: 1.0",
            "pids_limit: 128",
            "HOME: /tmp/islandos-home",
            "XDG_CACHE_HOME: /tmp/xdg-cache",
            "MPLCONFIGDIR: /tmp/matplotlib",
        ):
            with self.subTest(token=token):
                self.assertIn(token, compose)
        self.assertIn("STREAMLIT_BROWSER_GATHER_USAGE_STATS=false", dockerfile)

    def test_container_smoke_verifies_runtime_hardening_not_only_static_config(self):
        workflow = (ROOT / ".github/workflows/container-web-smoke.yml").read_text(encoding="utf-8")
        for token in (
            "--read-only",
            "--tmpfs /tmp:rw,noexec,nosuid,size=128m",
            "--memory=1g",
            "--cpus=1",
            "--pids-limit=128",
            'config["ReadonlyRootfs"] is True',
            'config["Memory"] == 1073741824',
            'config["NanoCpus"] == 1000000000',
            'config["PidsLimit"] == 128',
        ):
            with self.subTest(token=token):
                self.assertIn(token, workflow)

    def test_pilot_acceptance_template_is_explicitly_unapproved_and_auditable(self):
        template = (ROOT / "docs/PILOT_ACCEPTANCE_TEMPLATE.md").read_text(encoding="utf-8")
        for phrase in ("NOT APPROVED", "NO-GO UNTIL ALL REQUIRED REVIEWS ARE COMPLETE", "abort criteria", "owner-approved", "SHA-256", "no actuator/control path"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), template.lower())
        self.assertIn("PILOT_ACCEPTANCE_TEMPLATE.md", (ROOT / "docs/DEMO_DEPLOYMENT.md").read_text(encoding="utf-8"))

    def test_runtime_lock_pins_direct_runtime_packages(self):
        lock = (ROOT / "requirements-runtime.lock").read_text(encoding="utf-8")
        pins = {}
        for line in lock.splitlines():
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line.strip())
            if match:
                pins[match.group(1).lower().replace("_", "-")] = match.group(2)
        for package in ("numpy", "matplotlib", "openpyxl", "streamlit", "pandas", "pymoo", "pip"):
            with self.subTest(package=package):
                self.assertIn(package, pins, f"{package} must be exactly pinned in the runtime lock")

    def test_deployment_runbook_keeps_production_boundary_explicit(self):
        runbook = (ROOT / "docs/DEMO_DEPLOYMENT.md").read_text(encoding="utf-8").lower()
        self.assertIn("research/demo deployment only", runbook)
        self.assertIn("not yet established", runbook)
        self.assertIn("authentication", runbook)
        self.assertIn("127.0.0.1", runbook)

    def test_dependency_audit_emits_retained_cyclonedx_sbom_artifacts(self):
        workflow = (ROOT / ".github/workflows/dependency-audit.yml").read_text(encoding="utf-8")
        self.assertIn("--format cyclonedx-json", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("retention-days: 30", workflow)
        self.assertIn("if: always()", workflow)

    def test_container_smoke_workflow_emits_full_image_sbom(self):
        workflow = (ROOT / ".github/workflows/container-web-smoke.yml").read_text(encoding="utf-8")
        self.assertIn("anchore/sbom-action@66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c", workflow)
        self.assertIn("image: islandos-web:ci", workflow)
        self.assertIn("format: cyclonedx-json", workflow)
        self.assertIn("mkdir -p build/sbom", workflow)
        self.assertIn("output-file: build/sbom/islandos-web-image.cdx.json", workflow)
        self.assertIn("upload-artifact-retention: 30", workflow)

    def test_release_candidate_attests_bundle_with_minimal_permissions(self):
        workflow = (ROOT / ".github/workflows/release-candidate.yml").read_text(encoding="utf-8")
        checklist = (ROOT / "docs/RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertIn("actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8", workflow)
        self.assertIn('subject-path: "dist/*"', workflow)
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("gh attestation verify", checklist)
        self.assertLess(workflow.index("Attest release bundle files"), workflow.index("Verify source archive provenance attestation"))
        self.assertLess(workflow.index("Verify source archive provenance attestation"), workflow.index("Upload release candidate bundle"))

    def test_deployment_preflight_passes_for_repository_configuration(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from deployment_preflight import run_checks
        checks = run_checks(ROOT)
        self.assertTrue(checks)
        self.assertTrue(
            all(check["status"] == "pass" for check in checks),
            "\\n".join(f"{c['name']}: {c['detail']}" for c in checks if c["status"] != "pass"),
        )
        self.assertFalse(any("production_authorized" in check for check in checks))

    def test_deployment_preflight_requires_capability_drop(self):
        import shutil
        import tempfile
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from deployment_preflight import run_checks
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            for relative in ("Dockerfile", "docker-compose.yml", "requirements-runtime.lock", "SECURITY.md"):
                shutil.copy2(ROOT / relative, temp_root / relative)
            for relative in ("docs/DEMO_DEPLOYMENT.md", ".github/workflows/container-web-smoke.yml"):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            compose = temp_root / "docker-compose.yml"
            compose.write_text(compose.read_text(encoding="utf-8").replace("cap_drop:", "capability_drop_removed:"), encoding="utf-8")
            checks = run_checks(temp_root)
            result = next(check for check in checks if check["name"] == "compose_least_privilege")
            self.assertEqual(result["status"], "fail")

    def test_deployment_preflight_fails_closed_on_public_compose_binding(self):
        import shutil
        import tempfile
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from deployment_preflight import run_checks
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            for relative in ("Dockerfile", "docker-compose.yml", "requirements-runtime.lock", "SECURITY.md"):
                shutil.copy2(ROOT / relative, temp_root / relative)
            for relative in ("docs/DEMO_DEPLOYMENT.md", ".github/workflows/container-web-smoke.yml"):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            compose = temp_root / "docker-compose.yml"
            compose.write_text(compose.read_text(encoding="utf-8").replace("127.0.0.1:8501:8501", "0.0.0.0:8501:8501"), encoding="utf-8")
            checks = run_checks(temp_root)
            result = next(check for check in checks if check["name"] == "compose_loopback_only")
            self.assertEqual(result["status"], "fail")


if __name__ == "__main__":
    unittest.main()
