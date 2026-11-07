import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_shared_core_smoke_runs_without_streamlit_import():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "islandos_core_smoke.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["streamlit_imported"] is False
    assert report["import_status"] == "valid"
    assert report["task_readiness"] == "ready_for_screening"
    assert report["audit_event_count"] == 4
