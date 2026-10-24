"""Integration tests for the app's CSV upload-to-export workflow."""
import csv
import io
from datetime import datetime

import pytest

from experiments.compare_energy_water_strategies import Config
from islandos_core.app_workflow import (
    dataframe_csv,
    parse_uploaded_csv,
    run_uploaded_strategy_comparison,
)
from tools.generate_synthetic_site_csv import FIELDS, generate_rows


def csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def test_valid_upload_runs_all_strategies_and_exports_provenance() -> None:
    raw = csv_bytes(generate_rows(30, 101, datetime(2026, 1, 1)))
    config = Config(
        ro_rated_power_kw=10.0,
        specific_energy_kwh_m3=4.0,
        tank_capacity_m3=50.0,
        initial_water_m3=10.0,
        min_run_hours=1,
    )

    steps, detail, summary = run_uploaded_strategy_comparison(raw, config)

    assert len(steps) == 30
    assert len(summary) == 5
    assert len(detail) == len(steps) * len(summary)
    assert {row["strategy"] for row in summary} == {
        "no_ro_baseline",
        "surplus_only",
        "off_peak_only",
        "hybrid_surplus_then_off_peak",
        "emergency_backup",
    }

    provenance = {
        "source_type": "user_uploaded_unverified",
        "input_sha256": "a" * 64,
        "run_signature": "b" * 64,
    }
    exported = dataframe_csv(summary, provenance)
    parsed = list(csv.DictReader(io.StringIO(exported.decode("utf-8"))))
    assert len(parsed) == 5
    assert {row["source_type"] for row in parsed} == {"user_uploaded_unverified"}
    assert {row["input_sha256"] for row in parsed} == {"a" * 64}
    assert {row["run_signature"] for row in parsed} == {"b" * 64}


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"timestamp,water_demand_m3\n2026-01-01T00:00:00,1\n",
        b"timestamp,renewable_surplus_kw,diesel_displacement_potential_kw,grid_price_per_kwh,off_peak,grid_available,water_demand_m3\n"
        b"2026-01-01T00:00:00,0,0,0.1,true,true,1,unexpected\n",
    ],
)
def test_invalid_upload_fails_before_strategy_comparison(raw: bytes) -> None:
    config = Config(
        ro_rated_power_kw=10.0,
        specific_energy_kwh_m3=4.0,
        tank_capacity_m3=50.0,
        initial_water_m3=10.0,
        min_run_hours=1,
    )
    with pytest.raises((ValueError, OSError)):
        run_uploaded_strategy_comparison(raw, config)


def test_uploaded_csv_parser_accepts_valid_hourly_data() -> None:
    raw = csv_bytes(generate_rows(25, 102, datetime(2026, 2, 1)))
    parsed = parse_uploaded_csv(raw)
    assert len(parsed) == 25
    assert parsed[0].timestamp == "2026-02-01T00:00:00"
