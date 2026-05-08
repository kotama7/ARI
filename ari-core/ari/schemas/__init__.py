"""JSON Schemas shipped with ari-core."""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent


def load(name: str) -> dict:
    """Load and return a JSON schema by basename (with or without .json)."""
    fn = name if name.endswith(".json") else f"{name}.json"
    path = _HERE / fn
    return json.loads(path.read_text())


def schema_path(name: str) -> Path:
    fn = name if name.endswith(".json") else f"{name}.json"
    return _HERE / fn
