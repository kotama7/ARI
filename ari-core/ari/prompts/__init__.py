"""External prompt templates for ARI core (Phase PC).

PC3 lifts ``ari.agent.loop.SYSTEM_PROMPT`` out into
``ari/prompts/agent/system.md``; later PC PRs add the orchestrator,
pipeline, and evaluator prompts.
"""

from ari.prompts._loader import (  # noqa: F401
    FilesystemPromptLoader,
    PromptLoader,
    package_prompts_root,
)

# Subtask 044: deterministic, LLM-call-free prompt-provenance recorder.
# Additive re-export; keeps the recorder importable as ``ari.prompts.*``
# without exposing it via the public ``ari.public.*`` surface.
from ari.prompts._provenance import (  # noqa: F401
    PromptUseRecord,
    build_prompt_versions_rollup,
    load_prompt_trace,
    record_prompt_use,
)
