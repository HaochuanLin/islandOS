from __future__ import annotations

import json

import pytest

from islandos_core.dataset_provenance import (
    DatasetProvenanceError,
    sha256_file_bytes,
    validate_dataset_provenance,
)


@pytest.fixture
def metadata():
    return {
        "dataset_id": "pvgis-demo-001",
        "source_name": "European Commission Joint Research Centre PVGIS",
        "source_url": "https://re.jrc.ec.europa.eu/pvg_tools/en/",
        "retrieved_at": "2026-10-23T12:00:00Z",
        "time_start": "2020-01-01T00:00:00Z",
        "time_end": "2020-01-08T00:00:00Z",
        "timezone": "UTC",
        "frequency": "1h",
        "variables": [
            {"name": "ghi", "unit": "W/m2", "meaning": "Global horizontal irradiance"},
            {"name": "pv_power", "unit": "kW", "meaning": "Model-estimated photovoltaic power"},
        ],
        "license": "Verify source terms for each downloaded product",
        "data_status": "public_reanalysis",
        "source_version": "PVGIS API v6; response schema must be pinned by adapter",
    }


def test_valid_metadata_is_json_compatible_and_labels_data_status(metadata):
    result = validate_dataset_provenance(metadata)
    restored = json.loads(json.dumps(result))
    assert restored["provenance_schema_version"] == "1.0"
    assert restored["data_status"] == "public_reanalysis"
    assert restored["variables"][1]["unit"] == "kW"
    assert "sha256" not in restored


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_url", "http://example.com/data.csv", "HTTPS"),
        ("retrieved_at", "2026-10-23T12:00:00", "timezone"),
        ("time_end", "2019-12-31T00:00:00Z", "earlier"),
        ("data_status", "real", "data_status"),
        ("variables", [], "non-empty"),
        ("sha256", "abc", "SHA-256"),
    ],
)
def test_invalid_metadata_fails_closed(metadata, field, value, message):
    metadata[field] = value
    with pytest.raises(DatasetProvenanceError, match=message):
        validate_dataset_provenance(metadata)


def test_missing_fields_are_reported(metadata):
    del metadata["license"]
    with pytest.raises(DatasetProvenanceError, match="license"):
        validate_dataset_provenance(metadata)


def test_duplicate_variable_names_are_rejected(metadata):
    metadata["variables"].append(dict(metadata["variables"][0]))
    with pytest.raises(DatasetProvenanceError, match="duplicate variable"):
        validate_dataset_provenance(metadata)


def test_sha256_is_deterministic_and_matches_exact_bytes():
    assert sha256_file_bytes(b"data\n") == sha256_file_bytes(b"data\n")
    assert sha256_file_bytes(b"data\n") != sha256_file_bytes(b"data")
