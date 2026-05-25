"""ari.agent — ReAct loop, environment capture, and workflow guidance.

Hosts the conversational driver that runs an LLM in a tool-calling loop
against the MCP skills.  The loop reads the per-node prompt assembly
from ``ari/agent/loop.py`` (system prompt is externalised under
``ari/prompts/agent/system.md`` since Phase PC3) and dispatches tool
calls through ``MCPClient``.

Modules:
- ``loop`` — the main ``AgentLoop`` driver and per-node prompt builder.
- ``message_utils`` — token-budget-aware history compaction.
- ``tool_manager`` — MCP client lifecycle wrapper.
- ``guidance`` — per-stage workflow hints injected as system messages.
- ``run_env`` — environment-variable + working-directory snapshot.
- ``react_driver`` — pipeline-stage entry point that calls AgentLoop.
- ``workflow`` — workflow.yaml stage validation.

See also:
- ``docs/concepts/architecture.md`` (Per-Node Prompt Composition, Pipeline-driven ReAct).
- ``git log -- ari-core/ari/agent/`` for the Phase 3D split history.
"""
