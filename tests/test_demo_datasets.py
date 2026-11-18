from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_core.demo_datasets import synthetic_forecast_history_csv


def test_synthetic_forecast_csv_matches_forecast_input_contract():
    payload = synthetic_forecast_history_csv()
    parsed = parse_customer_history_csv(payload, source_name="synthetic-demo.csv")

    assert parsed.row_count == 168
    assert parsed.timestamps_utc[0].isoformat() == "2026-01-01T00:00:00+00:00"
    assert set(parsed.signals) == {
        "pv_power", "wind_power", "essential_load", "electricity_price"
    }
    assert all(len(values) == 168 for values in parsed.signals.values())


def test_synthetic_forecast_csv_is_reproducible():
    assert synthetic_forecast_history_csv() == synthetic_forecast_history_csv()


def test_synthetic_forecast_csv_rejects_too_short_history():
    import pytest

    with pytest.raises(ValueError, match="at least 72"):
        synthetic_forecast_history_csv(hours=24)
