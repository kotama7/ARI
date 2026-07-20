"""ari.llm.claude_code — Claude Code as an LLM-API-compatible ARI backend.

Selected via ``llm.backend: claude_code`` (or ``ARI_BACKEND=claude_code``).
Two modes (``llm.claude_code.mode``):

- ``strict_reproducibility`` — fresh ``claude -p`` subprocess per call,
  hermetic env allowlist, throwaway cwd, full provenance. For experiments,
  papers, baselines.
- ``low_overhead`` — resident Agent SDK worker, but each request is a fresh
  ``query()``; sessions are never resumed. For implementation-speed work.

Both modes suppress memory / MCP / tools / plugins / hooks / CLAUDE.md /
skills / session persistence (see policy.py) and answer through the same
``LLMClient.complete()`` surface as every other backend.

See docs/reference/claude_code_provider.md.
"""

from ari.llm.claude_code.cli_runner import ClaudeCliRunner, ClaudeCodeRunError
from ari.llm.claude_code.command import ClaudeCodeUnsupportedFlagError
from ari.llm.claude_code.policy import (
    ClaudeCodePolicy,
    ClaudeCodePolicyError,
    validate_policy,
)
from ari.llm.claude_code.provider import (
    ClaudeCodeProvider,
    ClaudeCodeToolsUnsupportedError,
    policy_from_settings,
)
from ari.llm.claude_code.sdk_runner import (
    ClaudeCodeSdkUnavailableError,
    ClaudeSdkRunner,
)
from ari.llm.claude_code.serializer import SerializedPrompt, serialize_messages
from ari.llm.claude_code.validation import ClaudeCodeSchemaError

__all__ = [
    "ClaudeCliRunner",
    "ClaudeCodePolicy",
    "ClaudeCodePolicyError",
    "ClaudeCodeProvider",
    "ClaudeCodeRunError",
    "ClaudeCodeSchemaError",
    "ClaudeCodeSdkUnavailableError",
    "ClaudeCodeToolsUnsupportedError",
    "ClaudeCodeUnsupportedFlagError",
    "ClaudeSdkRunner",
    "SerializedPrompt",
    "policy_from_settings",
    "serialize_messages",
    "validate_policy",
]
