"""ARI pipeline package — Generic workflow execution engine.

Driven entirely by workflow.yaml (or pipeline.yaml for backward
compat).  No hardcoded tool names; data flow is declared in the YAML.
Adding a new skill or stage requires only YAML changes — no code
changes.

Phase 3C split this 1640-line module into the package layout below.
The original public symbols (``run_pipeline``, ``load_workflow``,
``build_best_nodes_context``, ``_extract_plan_sections`` etc.)
remain importable from ``ari.pipeline`` thanks to the re-exports
below.

Sub-modules (REFACTORING.md §4 mapping):

- :mod:`ari.pipeline.experiment_md`  — experiment.md helpers.
- :mod:`ari.pipeline.yaml_loader`    — workflow.yaml loaders +
  ``_resolve_templates``.
- :mod:`ari.pipeline.stage_control`  — ``_should_loop_back``,
  ``_format_vlm_feedback``.
- :mod:`ari.pipeline.context_builder`— BFTS-context + keyword
  extractor.
- :mod:`ari.pipeline.stage_runner`   — pre/post-tool dispatch,
  ReAct stage runner, subprocess MCP caller.
- :mod:`ari.pipeline.orchestrator`   — ``build_scientific_data`` +
  ``run_pipeline`` entry points.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# Re-exports preserve the historical ``ari.pipeline`` public surface.
from ari.pipeline.experiment_md import (  # noqa: F401,E402
    _AUTO_APPEND_BEGIN,
    _AUTO_APPEND_END,
    _build_auto_append_block,
    _extract_plan_sections,
    _promote_plan_to_experiment_md,
    parse_metric_from_experiment_md,
)
from ari.pipeline.yaml_loader import (  # noqa: F401,E402
    _resolve_templates,
    load_disabled_stage_names,
    load_pipeline,
    load_workflow,
)
from ari.pipeline.stage_control import (  # noqa: F401,E402
    _format_vlm_feedback,
    _should_loop_back,
)
from ari.pipeline.context_builder import (  # noqa: F401,E402
    _extract_keywords_from_nodes,
    build_best_nodes_context,
)
from ari.pipeline.stage_runner import (  # noqa: F401,E402
    _call_with_retry,
    _run_react_stage,
    _run_stage_subprocess,
)
from ari.pipeline.orchestrator import (  # noqa: F401,E402
    build_scientific_data,
    run_pipeline,
)
