"""URL slugs for the pages the menu exposes.

Streamlit derives a page's slug from its file name, so renaming a file silently
killed every bookmark and shared link to it — ``/06_Forecast_…`` in particular.
The menu now declares each slug explicitly, and the value is the one the public
app already serves: declaring it changes nothing today, and future renames keep
the link alive.
"""

from __future__ import annotations


def page_url_path(page_file: str) -> str:
    """Return the stable slug for a page file path, e.g. ``pages/06_X.py`` -> ``X``."""
    if not isinstance(page_file, str) or not page_file.strip():
        raise ValueError("page_file must be a non-empty path")
    stem = page_file.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".py")
    prefix, _, rest = stem.partition("_")
    return rest if prefix.isdigit() and rest else stem
