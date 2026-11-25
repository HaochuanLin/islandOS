"""Shared visual language for the customer-facing Streamlit pages.

The public pages are read by judges on a projector and on laptops, often at a
distance.  Streamlit's stock type scale is too small for that setting, and its
default red/blue accents read as a generic demo rather than an operations
product.  This module loads one stylesheet that applies the same palette and
type scale as the React console: deep sea, tidal green, warm paper, a serif
display face and a larger working text size.

The stylesheet is deliberately selector-based rather than a new component
library.  Pages keep their existing Streamlit structure and behaviour; only the
presentation changes.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st


_CSS_PATH = Path(__file__).with_name("streamlit_theme.css")


def _stylesheet() -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def apply_theme() -> None:
    """Install the shared customer-page theme for the current app run."""
    st.html(f"<style>{_stylesheet()}</style>")
