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
