"""Readable static tables for the customer-facing Streamlit pages.

Streamlit's dataframe element paints its text on a canvas at roughly 12px, so
CSS cannot enlarge it.  That is too small for a reviewer sitting across a table.
These pages therefore use ``st.table`` (real HTML) and this helper normalises
number formatting before display: whole-number columns stay whole, money and
rates keep two decimals, very small coefficients keep four, and thousands get
separators.  The result stays a pandas Styler, so numerals remain right-aligned.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def _format_for(series: pd.Series) -> str:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return "{:.2f}"

    absolute = values.abs()
    finite = absolute[absolute != 0]

    # Counts, hours, years and whole kWh values do not need decimal tails.
    if bool((values % 1 == 0).all()):
        return "{:,.0f}"

    smallest = float(finite.min()) if not finite.empty else 1.0
    decimals = 4 if smallest < 0.01 else 3 if smallest < 0.1 else 2
    return f"{{:,.{decimals}f}}"


def render_table(
    data: Any,
    *,
    hide_index: bool = True,
    index: bool = False,
    max_rows: int | None = None,
) -> None:
    """Render a full-width, large-type table from a DataFrame-like object.

    ``max_rows`` is available for long audit tables; the default shows every
    row because these customer tables are part of the evidence, not a preview.
    """
    frame = pd.DataFrame(data).copy()
    if index:
        frame = frame.reset_index()
    if max_rows is not None:
        frame = frame.head(max_rows)

    formats = {
        column: _format_for(frame[column])
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column]) and not pd.api.types.is_bool_dtype(frame[column])
    }
    styler = frame.style.format(formats, na_rep="—")
    st.table(styler, width="stretch", hide_index=hide_index)
