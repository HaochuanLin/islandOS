from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from experiments.validate_dataset_provenance import main
from islandos_core.dataset_provenance import sha256_file_bytes


def valid_metadata():
    return {
        "dataset_id": "test-dataset",
        "source_name": "Example public dataset",
        "source_url": "https://example.org/data",
        "retrieved_at": "2026-10-23T12:00:00Z",
        "time_start": "2020-01-01T00:00:00Z",
        "time_end": "2020-01-02T00:00:00Z",
        "timezone": "UTC",
        "frequency": "1h",
        "variables": [{"name": "water_demand", "unit": "m3", "meaning": "Hourly water demand"}],
        "license": "CC BY 4.0",
        "data_status": "public_reanalysis",
        "source_version": "fixture-v1",
    }


def test_cli_normalizes_metadata_and_writes_output(tmp_path, capsys):
    source = tmp_path / "provenance.json"
    output = tmp_path / "nested" / "normalized.json"
    source.write_text(json.dumps(valid_metadata()), encoding="utf-8")

    assert main([str(source), "--output", str(output)]) == 0
    assert capsys.readouterr().err == ""
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["provenance_schema_version"] == "1.0"
    assert result["dataset_id"] == "test-dataset"


def test_cli_hashes_artifact_and_records_exact_digest(tmp_path):
    source = tmp_path / "provenance.json"
    artifact = tmp_path / "measurements.csv"
    source.write_text(json.dumps(valid_metadata()), encoding="utf-8")
    artifact.write_bytes(b"timestamp,value\n2020-01-01T00:00:00Z,1\n")

    assert main([str(source), "--artifact", str(artifact), "--output", str(tmp_path / "out.json")]) == 0
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert result["sha256"] == sha256_file_bytes(artifact.read_bytes())


def test_cli_rejects_artifact_hash_mismatch(tmp_path, capsys):
    source = tmp_path / "provenance.json"
    artifact = tmp_path / "measurements.csv"
    metadata = valid_metadata()
    metadata["sha256"] = "0" * 64
    source.write_text(json.dumps(metadata), encoding="utf-8")
    artifact.write_bytes(b"actual file bytes")

    assert main([str(source), "--artifact", str(artifact)]) == 2
    captured = capsys.readouterr()
    assert "does not match" in captured.err
    assert captured.out == ""


def test_cli_rejects_non_object_json_root(tmp_path, capsys):
    source = tmp_path / "provenance.json"
    source.write_text("[]", encoding="utf-8")

    assert main([str(source)]) == 2
    assert "root must be an object" in capsys.readouterr().err


def test_documented_module_entrypoint_runs_from_repository_root(tmp_path):
    source = tmp_path / "provenance.json"
    source.write_text(json.dumps(valid_metadata()), encoding="utf-8")
    repository_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.validate_dataset_provenance",
            str(source),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["dataset_id"] == "test-dataset"
    assert result.stderr == ""
