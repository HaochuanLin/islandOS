"""A concrete recovery step after an upload is refused.

This lives in its own module so a long-running Streamlit process can import it
after a deploy. Streamlit keeps already-imported project modules in
``sys.modules``; a function added to ``upload_guard`` is invisible to the old
cached module until a full restart, even when a page file imports it. A module
that did not exist before the deploy is imported fresh.

The function only *offers* the canonical site-history CSV after a rejection; it
does not weaken validation or continue with the rejected file.
"""

from __future__ import annotations

import streamlit as st


def offer_schema_conformant_csv() -> None:
    """After a rejection, hand the reader a file that does satisfy the schema.

    Measured 2026-11-24: the demo offers three CSV downloads with near-identical
    labels, and only the canonical "site history" one loads into the customer
    pages. Uploading the other template is refused correctly — but the refusal
    named the columns without naming a file that has them, which is a dead end
    for a reader who does not write Python. Offering the demo's own canonical
    file here turns that dead end into one click.
    """
    from islandos_core.customer_dashboard import REQUIRED_CUSTOMER_COLUMNS
    from islandos_core.demo_datasets import synthetic_forecast_history_csv

    st.caption(
        "A file that loads without changes uses exactly these columns: "
        + ", ".join(f"`{name}`" for name in REQUIRED_CUSTOMER_COLUMNS)
        + ". The demo's canonical site-history CSV already has them."
    )
    st.download_button(
        "⬇ Download a site-history CSV this page accepts",
        data=synthetic_forecast_history_csv(),
        file_name="islandos_site_history_canonical.csv",
        mime="text/csv",
        help=(
            "168 hourly synthetic rows in the canonical customer columns. Upload it "
            "unchanged to see this page work end to end."
        ),
    )
