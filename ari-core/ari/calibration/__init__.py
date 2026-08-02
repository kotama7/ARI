"""Versioned, human-curated evaluator calibration assets."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def load_evaluator_calibration_v1() -> dict[str, Any]:
    """Load the bundled v1 corpus without consulting network or model state."""

    resource = files(__package__).joinpath("evaluator_v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


__all__ = ["load_evaluator_calibration_v1"]
