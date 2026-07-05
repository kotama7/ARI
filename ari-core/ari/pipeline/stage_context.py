"""Pipeline run-state value object (subtask 012).

``StageContext`` bundles the mutable state that ``run_pipeline`` previously
threaded by hand — the ``tpl_vars`` template registry and the
``stage_outputs`` result map — together with the read-only run inputs the
individual stages need (checkpoint dir, config path, resolved workflow
config, the intentionally-disabled stage set, and the best-node metrics used
for the ``actual_metrics`` fallback).

The object carries **no behaviour**; it exists only to replace the manual
dict threading. Mutation semantics are identical to the historical inline
loop: the workflow driver and the stage objects read and write
``tpl_vars`` / ``stage_outputs`` in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StageContext:
    """Shared, mutable per-run state passed to every stage method."""

    checkpoint_dir: Path
    config_path: str
    wf_cfg: dict
    disabled_stages: set
    best_metrics: Any = None
    tpl_vars: dict = field(default_factory=dict)
    stage_outputs: dict = field(default_factory=dict)
