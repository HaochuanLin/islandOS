"""Rejected uploads must say what failed, that nothing was processed, and how to fix it."""

from pathlib import Path

import pytest

from islandos_core.customer_dashboard import parse_customer_history_csv
from islandos_ui.upload_guard import fix_hint, rejection_message

REPO_ROOT = Path(__file__).resolve().parents[1]

HANDLERS = [
    "pages/05_Customer_Decision_Dashboard.py",
    "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
    "pages/2_Rolling_Horizon_Lab.py",
    "islandos_ui/workspace.py",
]


def test_message_states_three_things():
    text = rejection_message("Site history CSV", "CSV is missing required columns: pv_power_kw")
    assert "Site history CSV rejected - nothing was processed." in text
    assert "**What failed:** CSV is missing required columns: pv_power_kw" in text
    assert "**How to fix:** Add the missing columns" in text


def test_hint_maps_parser_messages_to_actions():
    assert "ISO-8601" in fix_hint("row 4 has an invalid ISO-8601 timestamp")
    assert "plain numbers" in fix_hint("row 7 column pv_power_kw must be numeric")
    assert "non-negative" in fix_hint("row 2 column essential_load_kw cannot be negative")
    assert "minimum number of continuous rows" in fix_hint("CSV requires at least 72 hourly observations")


def test_unknown_detail_still_gives_a_next_action():
    hint = fix_hint("something the parser did not categorise")
    assert "not stored" in hint and "no calculation used it" in hint


@pytest.mark.parametrize("relative_path", HANDLERS)
def test_handlers_use_the_shared_panel(relative_path: str):
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "from islandos_ui.upload_guard import reject_upload" in source
    assert "reject_upload(" in source


def test_real_parser_failure_produces_actionable_copy():
    bad = b"timestamp_utc,pv_power_kw\n2026-01-01T00:00:00Z,1.0\n"
    with pytest.raises(ValueError) as excinfo:
        parse_customer_history_csv(bad)
    text = rejection_message("Site history CSV", str(excinfo.value))
    assert "What failed:" in text and "How to fix:" in text
    assert "missing required columns" in text.lower()
