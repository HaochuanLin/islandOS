"""End-to-end reproducibility tests for the Stage 8 synthetic example."""
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "synthetic_customer_impact_demo.py"


def run_demo():
    completed = subprocess.run(
        [sys.executable, str(DEMO)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_demo_runs_and_emits_a_synthetic_advisory_only_comparison():
    report = run_demo()
    assert report["data_provenance"] == "synthetic_demo_data — not measured site data"
    assert report["evidence_classification"] == "synthetic_model_output"
    assert report["candidate_is_optimizer"] is False
    assert report["same_inputs_and_equipment_configuration"] is True
    assert report["equipment_constraint_audit"]["passed"] is True
    assert report["service_equivalence"]["passed"] is True
    assert report["net_customer_value"] is None
    assert report["commercial_costs"] is None


def test_demo_is_deterministic():
    first = run_demo()
    second = run_demo()
    assert first == second
