"""Run a local, offline first-run health check for IslandOS.

This diagnostic checks the Python runtime, required runtime packages, core
repository files, and shared configuration loader. It does not install
packages, contact the network, or certify site data, model validity, or safety.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "islandos_config.py",
    "islandos_core/forecasting.py",
    "config/site_parameters.example.json",
)
REQUIRED_RUNTIME_MODULES = ("numpy", "matplotlib", "openpyxl", "streamlit", "pandas", "pymoo")


def run_doctor(config_path: str | Path | None = None, *, root: Path = ROOT,
               python_version: tuple[int, int] | None = None) -> dict[str, Any]:
    """Return deterministic diagnostics without changing the working tree."""
    version = python_version or (sys.version_info.major, sys.version_info.minor)
    checks: list[dict[str, str]] = []

    runtime_ok = version >= (3, 10)
    checks.append({
        "id": "python_runtime",
        "status": "pass" if runtime_ok else "fail",
        "detail": f"Python {version[0]}.{version[1]} detected; Python 3.10+ is required.",
    })

    missing = [relative for relative in REQUIRED_FILES if not (root / relative).is_file()]
    checks.append({
        "id": "repository_layout",
        "status": "pass" if not missing else "fail",
        "detail": "Required core files are present." if not missing
                  else "Missing required file(s): " + ", ".join(missing),
    })

    missing_modules: list[str] = []
    for module_name in REQUIRED_RUNTIME_MODULES:
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing_modules.append(module_name)
    checks.append({
        "id": "runtime_dependencies",
        "status": "pass" if not missing_modules else "fail",
        "detail": "Required runtime packages are import-discoverable."
                  if not missing_modules
                  else "Missing runtime package(s): " + ", ".join(missing_modules),
    })

    if not missing and runtime_ok and not missing_modules:
        # Import only the standard-library configuration module after placing
        # the repository root on the import path; no optional ML dependencies.
        root_text = str(root.resolve())
        inserted = root_text not in sys.path
        if inserted:
            sys.path.insert(0, root_text)
        try:
            from islandos_config import load_config
            selected = Path(config_path) if config_path is not None else root / "config/site_parameters.example.json"
            config = load_config(selected)
            metadata = config.get("metadata")
            name = metadata.get("name", "unnamed") if isinstance(metadata, dict) else "unnamed"
            checks.append({
                "id": "site_configuration",
                "status": "pass",
                "detail": f"Configuration is structurally valid ({name!r}); validity is not site-data verification.",
            })
        except (OSError, ValueError, TypeError, ImportError) as exc:
            checks.append({
                "id": "site_configuration",
                "status": "fail",
                "detail": f"Configuration check failed: {exc}",
            })
        finally:
            if inserted:
                try:
                    sys.path.remove(root_text)
                except ValueError:
                    pass
    else:
        checks.append({
            "id": "site_configuration",
            "status": "blocked",
            "detail": "Skipped because runtime, dependency, or repository-layout checks failed.",
        })

    failures = sum(check["status"] == "fail" for check in checks)
    return {
        "schema_version": 1,
        "status": "ready_for_local_smoke_tests" if failures == 0 else "needs_attention",
        "checks": checks,
        "limitations": [
            "This offline diagnostic does not install dependencies or contact external services.",
            "Configuration validity does not establish data provenance, physical validity, or operational safety.",
            "A successful check is not evidence that a real site has been calibrated or validated.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Optional site configuration JSON to validate instead of the example.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    report = run_doctor(args.config)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"IslandOS doctor: {report['status']}")
        for check in report["checks"]:
            print(f"[{check['status'].upper()}] {check['id']}: {check['detail']}")
        print("Scope: local structural checks only; no site validation or safety certification.")
    return 0 if report["status"] == "ready_for_local_smoke_tests" else 2


if __name__ == "__main__":
    raise SystemExit(main())
