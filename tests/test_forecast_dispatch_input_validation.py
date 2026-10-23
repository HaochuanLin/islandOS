import csv

import pytest

from experiments.evaluate_forecast_dispatch import (
    load_forecast_water_demand,
    load_paired_series,
)


FIELDS = [
    "timestamp_utc",
    "actual_surplus_kw",
    "forecast_surplus_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
]


def write_csv(tmp_path, rows, fields=FIELDS):
    path = tmp_path / "input.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def valid_rows():
    return [
        {
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "actual_surplus_kw": "12",
            "forecast_surplus_kw": "11",
            "water_demand_m3": "1.2",
            "cooling_demand_kw_th": "4",
        },
        {
            "timestamp_utc": "2026-01-01T01:00:00Z",
            "actual_surplus_kw": "14",
            "forecast_surplus_kw": "13",
            "water_demand_m3": "1.3",
            "cooling_demand_kw_th": "4.5",
        },
    ]


def test_load_paired_series_accepts_valid_hourly_timezone_aware_rows(tmp_path):
    path = write_csv(tmp_path, valid_rows())

    timestamps, scenario, forecast = load_paired_series(path)

    assert timestamps == ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]
    assert list(scenario.available_surplus_kw) == [12.0, 14.0]
    assert list(scenario.water_demand_m3_per_hour) == [1.2, 1.3]
    assert forecast == [11.0, 13.0]


def test_load_paired_series_rejects_missing_required_columns(tmp_path):
    path = write_csv(tmp_path, valid_rows(), fields=FIELDS[:-1])

    with pytest.raises(ValueError, match="missing columns: cooling_demand_kw_th"):
        load_paired_series(path)


def test_load_paired_series_rejects_timestamps_without_timezone(tmp_path):
    rows = valid_rows()
    rows[0]["timestamp_utc"] = "2026-01-01T00:00:00"

    with pytest.raises(ValueError, match="must include a timezone"):
        load_paired_series(write_csv(tmp_path, rows))


def test_load_paired_series_rejects_non_hourly_or_duplicate_timestamps(tmp_path):
    rows = valid_rows()
    rows[1]["timestamp_utc"] = "2026-01-01T02:00:00Z"

    with pytest.raises(ValueError, match="strictly ordered hourly timestamps"):
        load_paired_series(write_csv(tmp_path, rows))

    rows[1]["timestamp_utc"] = rows[0]["timestamp_utc"]
    with pytest.raises(ValueError, match="strictly ordered hourly timestamps"):
        load_paired_series(write_csv(tmp_path, rows))


@pytest.mark.parametrize("bad_value", ["-0.1", "nan", "inf", "not-a-number", ""])
def test_load_paired_series_rejects_invalid_numeric_values(tmp_path, bad_value):
    rows = valid_rows()
    rows[0]["actual_surplus_kw"] = bad_value

    with pytest.raises(ValueError):
        load_paired_series(write_csv(tmp_path, rows))


@pytest.mark.parametrize("bad_value", ["-1", "nan", "inf", ""])
def test_forecast_water_demand_rejects_invalid_values(tmp_path, bad_value):
    rows = valid_rows()
    fields = FIELDS + ["forecast_water_demand_m3"]
    for row in rows:
        row["forecast_water_demand_m3"] = row["water_demand_m3"]
    rows[1]["forecast_water_demand_m3"] = bad_value
    path = write_csv(tmp_path, rows, fields=fields)

    with pytest.raises(ValueError):
        load_forecast_water_demand(path, [1.2, 1.3])
