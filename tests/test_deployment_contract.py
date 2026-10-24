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


if __name__ == "__main__":
    unittest.main()
