import json
from pathlib import Path
import runpy


def test_operator_decision_record_demo_is_verified_and_advisory_only(capsys):
    repo_root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(repo_root / "examples" / "operator_decision_record_demo.py"),
        run_name="islandos_operator_decision_demo_test",
    )
    namespace["main"]()
    payload = json.loads(capsys.readouterr().out)

    assert payload["data_provenance"] == "synthetic_demo_data"
    assert payload["record_verification"]["valid"] is True
    assert payload["decision_record"]["status"] == "ready_for_human_review"
    assert payload["decision_record"]["operator_approval"] == "pending"
    assert payload["device_write_authorized"] is False
    assert payload["command_generated"] is False
