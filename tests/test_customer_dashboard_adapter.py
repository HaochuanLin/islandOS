import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.customer_dashboard import parse_customer_history_csv


def make_csv(rows=72, *, timestamp_offset_hours=0, negative_load=False):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp_utc", "pv_power_kw", "wind_power_kw",
        "essential_load_kw", "electricity_price_per_kwh",
    ])
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(rows):
        stamp = start + timedelta(hours=index + timestamp_offset_hours)
        writer.writerow([
            stamp.isoformat(), 10, 4, -1 if negative_load else 15,
            -0.02 if index == 0 else 0.12,
        ])
    return output.getvalue().encode()


def test_customer_csv_adapter_preserves_units_timestamps_and_source_hash():
    payload = make_csv()
    result = parse_customer_history_csv(payload, source_name="site_export.csv")
    assert result.row_count == 72
    assert result.timestamps_utc[0].tzinfo == timezone.utc
    assert result.signals["pv_power"][0] == 10.0
    assert result.signals["electricity_price"][0] == -0.02
    assert len(result.source_sha256) == 64
    assert result.source_name == "site_export.csv"


def test_customer_csv_adapter_rejects_short_history():
    with pytest.raises(ValueError, match="at least 72"):
        parse_customer_history_csv(make_csv(rows=71))


def test_customer_csv_adapter_rejects_non_contiguous_timestamps():
    payload = make_csv().decode().replace("2026-01-01T02:00:00+00:00", "2026-01-01T03:00:00+00:00")
    with pytest.raises(ValueError, match="contiguous hourly"):
        parse_customer_history_csv(payload.encode())


def test_customer_csv_adapter_rejects_naive_timestamps():
    payload = make_csv().decode().replace("+00:00", "")
    with pytest.raises(ValueError, match="include a timezone"):
        parse_customer_history_csv(payload.encode())


def test_customer_csv_adapter_rejects_negative_physical_signals():
    with pytest.raises(ValueError, match="cannot be negative"):
        parse_customer_history_csv(make_csv(negative_load=True))


def test_customer_csv_adapter_rejects_missing_required_columns():
    payload = b"timestamp_utc,pv_power_kw\n2026-01-01T00:00:00Z,1\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_customer_history_csv(payload)
