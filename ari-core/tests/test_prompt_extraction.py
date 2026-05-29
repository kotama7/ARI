"""Phase PC regression — extracted prompt files stay byte-identical.

PROMPTS_AND_CONFIG.md §4 demands a sha256 hash check on every
externalised prompt so a stray ``\\n`` change cannot silently shift
LLM behaviour.  Add a row here for each new ``ari/prompts/<key>.md``
that lands.
"""
from __future__ import annotations

import hashlib

import pytest

from ari.prompts import FilesystemPromptLoader


# (key, expected sha256 of the on-disk prompt body before the run)
_EXPECTED_HASHES: list[tuple[str, str]] = [
    # PC3 — agent system prompt.  Hash captured against the original
    # ``SYSTEM_PROMPT`` constant immediately before extraction.
    (
        "agent/system",
        "a50abe13d568c07c6cd25b930d27b48c42179fbe629cdf64ab2d3ed48585cdbf",
    ),
    # PC4 — orchestrator lineage decision prompt.
    (
        "orchestrator/lineage_decision",
        "33986674d50606428fc0e8f7c177894a21794d42b28acdfafc297819f9a9a6fd",
    ),
    # PC4 — orchestrator root-idea selector prompt.
    (
        "orchestrator/root_idea_selector",
        "803cc751a8874e05bbaddcafdac0215a54d4dea6c6b561f292931972cdbeb07d",
    ),
    # PC2 — pipeline keyword librarian prompt.
    (
        "pipeline/keyword_librarian",
        "c538a34ef8351eb59958b115a6221c2b5db7188521900ed5d913f6d73369e108",
    ),
    # PC5 — BFTS select-next prompt (v0.7.2: drop "low retry" criterion, B-3).
    (
        "orchestrator/bfts_select",
        "38b1ea409ff58bc0b5342b7fc677b3c64c5374bf35b0d5c9b0594a401fd4b71b",
    ),
    # PC5 — BFTS expand-select prompt.
    (
        "orchestrator/bfts_expand_select",
        "cff71dfe47770d9fdc23c704ca01717030f73b7ecb36f95cb9f1a49624709465",
    ),
    # PC5 — BFTS expand prompt (v0.7.2: depth/budget surfaces, I-4 + I-1).
    (
        "orchestrator/bfts_expand",
        "af0aba2d5805541d3a0ee5122019661a06c3ce27427c98690751ba487214703f",
    ),
    # PC6 — evaluator extract-metrics prompt (BASE_SYSTEM legacy 5-axis).
    # The .md file ends with a trailing newline; the in-class constant
    # does not, so the .py call site strips one before exposing it.
    (
        "evaluator/extract_metrics",
        "a9cf2dcbea0d6c8414514e5ad0f17b60215269218ae7fc042aec393321ebeffb",
    ),
    # PC6 — evaluator dynamic-axes peer-review prompt.
    (
        "evaluator/peer_review",
        "05205ee7b5215dd88418539d940c9140f3a0f4e1be940a4b330daea15a72a798",
    ),
    # PC8 — viz wizard chat-goal prompt.
    (
        "viz/wizard_chat_goal",
        "723a3f64dd110c480232829c89ddb97d536f77e7ecaa6fa336225eb04e900a58",
    ),
    # PC8 — viz wizard generate-config prompt.  Template form (with the
    # ``{goal}`` placeholder unsubstituted); the call-site formats it
    # against the user's research goal at runtime.
    (
        "viz/wizard_generate_config",
        "4bfc6a4237c57de8232b48020c709eece289f29a9260d68922a753ab1e664624",
    ),
]


@pytest.mark.parametrize("key,expected_sha", _EXPECTED_HASHES, ids=lambda v: v if isinstance(v, str) else "")
def test_prompt_byte_identical(key: str, expected_sha: str):
    """Each externalised prompt must hash to the value pinned in this file."""
    text = FilesystemPromptLoader().load(key)
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert actual == expected_sha, (
        f"prompt '{key}' drifted: expected {expected_sha}, got {actual}.\n"
        "If the change is intentional, update _EXPECTED_HASHES."
    )


def test_agent_system_prompt_format_preserves_template_vars():
    """``.format(...)`` over the externalised prompt produces a string
    that matches what the inline constant produced."""
    text = FilesystemPromptLoader().load("agent/system")
    formatted = text.format(tool_desc="X", memory_rules="", extra="")
    assert "AVAILABLE TOOLS:\nX" in formatted
    assert formatted.endswith("findings\n")


def test_loader_versioned_returns_stable_hash_prefix():
    text, version = FilesystemPromptLoader().load_versioned("agent/system")
    assert text
    assert len(version) == 12
    # Version is the truncated sha256 — must be deterministic.
    assert version == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
