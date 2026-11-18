"""Regression test for the public synthetic forecast-to-optimizer example."""
import json
from pathlib import Path
import runpy


def test_forecast_to_joint_optimizer_demo_runs_and_reports_scope(capsys):
    repo_root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(repo_root / "examples" / "forecast_to_joint_optimizer_demo.py"),
        run_name="islandos_optimizer_demo_test",
    )
    namespace["main"]()
    payload = json.loads(capsys.readouterr().out)

    assert payload["data_provenance"] == "synthetic_demo_data"
    assert payload["device_write_authorized"] is False
    assert payload["global_optimum_claimed"] is False
    assert payload["optimization"]["candidate_count"] > 0
    assert payload["optimization"]["feasible_count"] > 0
    assert payload["optimization"]["pareto_count"] > 0
    assert payload["water_service"]["service_feasible"] is True
    assert set(payload["baseline_worst_case_objectives"]) == {
        "battery_first", "grid_first"
    }
    assert payload["recommended_schedule"]["scenario_results"]
    assert "not a global optimum" in payload["method_scope"]
