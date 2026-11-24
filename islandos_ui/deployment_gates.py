"""Environment gates for the two local-only Streamlit pages.

These live in a small, standalone module rather than in ``navigation`` so a
long-running Streamlit process can import them after a deploy. Streamlit keeps
already-imported project modules in ``sys.modules`` after it pulls new files;
a newly added function on an old cached module is not visible until a full
restart. A module that did not exist before the deploy is imported fresh.

The customer workspace needs the loopback reference API; the site workspace
needs the local data directory flag. They are deliberately independent: one
flag must not expose a page whose other prerequisite is missing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

LOCAL_WORKSPACE_FLAG = "ISLANDOS_ENABLE_LOCAL_WORKSPACE"
LOCAL_API_BASE_URL = "ISLANDOS_API_BASE_URL"


def local_customer_workspace_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """The customer workspace needs the loopback reference API, nothing else."""
    env = os.environ if environ is None else environ
    return bool(env.get(LOCAL_API_BASE_URL, "").strip())


def local_site_workspace_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """The site workspace needs the local data directory flag, nothing else."""
    env = os.environ if environ is None else environ
    return env.get(LOCAL_WORKSPACE_FLAG, "").strip() == "1"
