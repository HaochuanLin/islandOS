"""The demo's own CSV download must stay loadable by the customer pages.

Measured 2026-11-24: the sidebar offered three differently shaped CSVs with near
identical labels, and the one labelled "energy-water CSV template" was refused by
both customer views. The refusal was correct; the dead end was that nothing on
the page handed the reader a file that does work. These tests pin the working
file to the parser's schema so a column rename breaks CI instead of the demo.
"""

from pathlib import Path

from islandos_core.customer_dashboard import (
    REQUIRED_CUSTOMER_COLUMNS,
    parse_customer_history_csv,
)
from islandos_core.demo_datasets import FORECAST_HISTORY_COLUMNS, synthetic_forecast_history_csv
from islandos_ui.upload_recovery import offer_schema_conformant_csv

REPO_ROOT = Path(__file__).resolve().parents[1]

CUSTOMER_PAGES = [
    "pages/05_Customer_Decision_Dashboard.py",
    "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
]


def test_demo_columns_match_the_parser_schema():
    """Two constants describe the same file; they must not drift apart."""
    assert FORECAST_HISTORY_COLUMNS == REQUIRED_CUSTOMER_COLUMNS


def test_demo_header_is_the_canonical_header():
    payload = synthetic_forecast_history_csv()
    header = payload.decode("utf-8-sig").splitlines()[0]
    assert header.split(",") == list(REQUIRED_CUSTOMER_COLUMNS)


def test_demo_csv_loads_through_the_real_parser():
    history = parse_customer_history_csv(synthetic_forecast_history_csv())
    assert history.row_count == 168
    assert set(history.signals) == {"pv_power", "wind_power", "essential_load", "electricity_price"}


def test_recovery_offer_exists_on_both_customer_pages():
    for relative_path in CUSTOMER_PAGES:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "from islandos_ui.upload_recovery import" in source
        assert "offer_schema_conformant_csv" in source
        assert "offer_schema_conformant_csv()" in source


def test_recovery_offer_is_callable_without_arguments():
    assert callable(offer_schema_conformant_csv)
    assert offer_schema_conformant_csv.__code__.co_argcount == 0
