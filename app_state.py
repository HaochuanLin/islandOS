"""Stable input fingerprints for Streamlit result-state validation."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def strategy_run_signature(raw: bytes, source_label: str, settings: Mapping[str, Any]) -> str:
    """Return a deterministic signature for data provenance and model settings."""
    payload = {
        "source_label": str(source_label),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "settings": dict(settings),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
