"""One-line-of-truth header block shared by every IslandOS entry page.

Each entry page answers four questions before it shows a single number: what
this page answers, where the data comes from, what a reader may conclude, and
what the page cannot tell them. Keeping the block in one place means a page
cannot quietly grow a different tone or drop the limitations line.
"""

from __future__ import annotations

from html import escape

import streamlit as st


def render_page_title(kicker: str, title: str, dek: str) -> None:
    """Render the display heading in the shared IslandOS type scale.

    ``kicker`` is the small all-caps line above the title, ``title`` is the H1,
    and ``dek`` is the one-sentence orientation line.  All three are escaped
    because they are written as HTML rather than through Streamlit's own title
    widget, which keeps the type scale independent of Streamlit's defaults.
    """
    st.html(
        '<section class="ios-hero">'
        f'<p class="ios-kicker">{escape(kicker)}</p>'
        f"<h1>{escape(title)}</h1>"
        f'<p class="ios-hero__dek">{escape(dek)}</p>'
        "</section>"
    )


def render_page_header(question: str, data: str, conclusions: str, limits: str) -> None:
    """Render the four-part brief. Keep every argument to one short sentence."""
    items = (
        ("Answers", question),
        ("Data", data),
        ("You can conclude", conclusions),
        ("Limits", limits),
    )
    cells = "".join(
        (
            '<div class="ios-brief__item">'
            f'<span class="ios-brief__label">{escape(label)}</span>'
            f'<p class="ios-brief__text">{escape(value)}</p>'
            "</div>"
        )
        for label, value in items
    )
    st.html(f'<aside class="ios-brief" aria-label="Page brief">{cells}</aside>')
