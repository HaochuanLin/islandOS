"""Uniform, fail-closed presentation for rejected uploads.

Validation itself already lives in ``islandos_core``: parsers raise `ValueError`
with a specific reason and callers stop instead of continuing with partial data.
What was missing is the user-facing half of that contract: every rejection should
say what failed, that nothing was processed, and what to change in the file. A
bare ``st.error(f"...: {exc}")`` tells a user the parser was unhappy without
telling them what to do.
"""

from __future__ import annotations

import streamlit as st

_FIX_HINTS = (
    ("missing required columns", "Add the missing columns using the documented header names; do not rename or drop existing ones."),
    ("timestamp", "Use ISO-8601 timestamps with an explicit timezone (for example 2026-01-01T00:00:00Z), one row per interval, in non-decreasing order."),
    ("must be numeric", "Remove unit suffixes from numeric cells (no 'kW', commas or thousands separators); export plain numbers."),
    ("cannot be negative", "Supply non-negative values for the power and load columns the schema marks as non-negative."),
    ("at least", "Extend the file to the stated minimum number of continuous rows; gaps and duplicated intervals both fail the check."),
)

_DEFAULT_HINT = (
    "Correct the rows named in the message and upload again. The file was not stored, "
    "and no calculation used it."
)


def fix_hint(detail: str) -> str:
    """Return a concrete next action for a parser message."""
    lowered = detail.lower()
    for needle, hint in _FIX_HINTS:
        if needle in lowered:
            return hint
    return _DEFAULT_HINT


def rejection_message(label: str, detail: str) -> str:
    """Build the three-part rejection message: what happened, why, and what to do."""
    return (
        f"**{label} rejected - nothing was processed.**\n\n"
        f"**What failed:** {detail}\n\n"
        f"**How to fix:** {fix_hint(detail)}"
    )


def reject_upload(label: str, detail: str) -> None:
    """Render a rejection panel. Callers must stop; this only reports."""
    st.error(rejection_message(label, str(detail)))
