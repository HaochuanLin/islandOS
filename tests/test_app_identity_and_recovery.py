"""Regressions for two session-facing failures found in the integration sweep.

Both are about a page surviving state it did not create: a shared dataset record
that fails verification, and an annual-economics binding whose identity moved
with the wall clock instead of the window it describes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_PAGE = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
JOINT_PAGE = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"
SESSION_KEY = "islandos_session_site_dataset"


def _broken_session_state(app: AppTest) -> None:
    app.session_state[SESSION_KEY] = {
        "file_name": "site.csv",
        "payload": b"timestamp_utc,pv_power_kw\n2026-01-01T00:00:00Z,1\n",
        "sha256": "0" * 64,
        "source_type": "customer_provided",
        "byte_count": 43,
    }


@pytest.mark.parametrize("page", [CUSTOMER_PAGE, JOINT_PAGE], ids=["05-dashboard", "06-optimizer"])
def test_a_tampered_session_dataset_is_discarded_instead_of_crashing(page: Path):
    app = AppTest.from_file(str(page), default_timeout=120)
    _broken_session_state(app)
    app.run()

    assert not app.exception, "\n".join(str(error) for error in app.exception)
    assert any("discarded" in warning.value for warning in app.warning)
    assert SESSION_KEY not in app.session_state


def test_customer_annual_binding_identity_does_not_move_with_the_clock():
    """Same inputs twice must produce the same manifest and binding digests."""
    seen = []
    for _ in range(2):
        app = AppTest.from_file(str(CUSTOMER_PAGE), default_timeout=120).run()
        assert not app.exception, "\n".join(str(error) for error in app.exception)
        facts = [caption.value for caption in app.caption if "Binding SHA-256" in caption.value]
        assert facts, "the annual economics basis is missing from the page"
        seen.append(facts[0])

    assert seen[0] == seen[1], (
        "two renders of the same inputs produced different annual bindings:\n"
        f"{seen[0]}\n{seen[1]}"
    )
