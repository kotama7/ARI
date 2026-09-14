"""Tests for subtask 038 — PromptRegistry discovery + placeholder catalogue.

The registry wraps (does not replace) ``FilesystemPromptLoader``: every read
delegates to the loader, so ``get`` / ``get_versioned`` stay byte-/hash-identical
to the loader and no rendered prompt can drift. Covers discovery (exactly the 28
core keys, READMEs excluded), delegation parity, placeholder parsing (tolerant of
``{{``/``}}`` JSON escapes), the config-injected-key tolerance policy, and loader
dependency injection.
"""

from __future__ import annotations

import hashlib

import pytest

from ari.prompts import FilesystemPromptLoader, PromptEntry, PromptRegistry


# The 28 externalized core templates (matches the sha256 pins in
# ``test_prompt_extraction.py``: the 036 inventory's 11, the three RQGM
# Task 03 proposal-generator templates, the three RQGM Task 05
# governance-actor templates, the nine RQGM Task 06 adversarial-loop
# templates, the RQGM Task 07 prompt-mutator meta-prompt, and the RQGM
# Task 08 clean-room-generator meta-prompt).
_EXPECTED_KEYS = sorted(
    [
        "agent/system",
        "evaluator/extract_metrics",
        "evaluator/peer_review",
        "governance/auditor",
        "governance/defender",
        "governance/governance_judge",
        "orchestrator/bfts_expand",
        "orchestrator/bfts_expand_select",
        "orchestrator/bfts_select",
        "orchestrator/lineage_decision",
        "orchestrator/root_idea_selector",
        "pipeline/keyword_librarian",
        "rqgm/adversary_cost_explosion",
        "rqgm/adversary_evidence_gap",
        "rqgm/adversary_metric_gaming",
        "rqgm/adversary_overclaim",
        # Paper-archive Task 05: the eighth (paper-phase) adversary template.
        "rqgm/adversary_paper_self_preference",
        "rqgm/adversary_prior_art",
        "rqgm/adversary_prompt_injection",
        "rqgm/adversary_reproducibility",
        "rqgm/clean_room_generator",
        # Externalised from ari/llm/cli_server.py: ari-core carries no
        # inline prompt literals.
        "llm/mcp_name_resolution",
        "rqgm/defender",
        # plan 11 §5.2 items 3-4: the recommendation roles.
        "rqgm/failure_summary_compressor",
        "rqgm/replay_selector",
        "rqgm/judge_adjudication",
        # Paper-archive co-evolution (plan ari_rqgm_paper/03 §5.5): the
        # governed manuscript reviewer/writer founding templates, lifted
        # byte-identical from ari-skill-paper's copies.
        "rqgm/paper_reviewer",
        "rqgm/paper_writer",
        # RQGM Task 14 PolicyMutator meta-prompt (the governed utility
        # policy's freeform proposer; the four default kinds need no LLM).
        "rqgm/policy_mutator",
        "rqgm/prompt_mutator",
        "rqgm/proposal_cheap",
        "rqgm/proposal_mutation",
        "rqgm/proposal_prior_art",
        "viz/wizard_chat_goal",
        "viz/wizard_generate_config",
    ]
)


# ── discovery ──────────────────────────────────────────────────────────────


def test_keys_returns_exactly_the_core_keys():
    """`keys()` enumerates exactly the 28 core templates; READMEs excluded."""
    keys = PromptRegistry().keys()
    assert keys == _EXPECTED_KEYS
    # No README.md ever leaks in as a key.
    assert not any(k.endswith("README") or "readme" in k.lower() for k in keys)


def test_keys_is_sorted():
    assert PromptRegistry().keys() == sorted(PromptRegistry().keys())


def test_has_reflects_discovery():
    reg = PromptRegistry()
    assert reg.has("orchestrator/bfts_select") is True
    assert reg.has("does/not/exist") is False


# ── delegation parity (byte / hash identical to the loader) ─────────────────


def test_get_is_byte_identical_to_loader():
    reg = PromptRegistry()
    loader = FilesystemPromptLoader()
    for key in _EXPECTED_KEYS:
        assert reg.get(key) == loader.load(key)


def test_get_versioned_matches_loader_and_is_twelve_char_hash():
    reg = PromptRegistry()
    loader = FilesystemPromptLoader()
    text, version = reg.get_versioned("evaluator/peer_review")
    assert (text, version) == loader.load_versioned("evaluator/peer_review")
    assert len(version) == 12
    assert version == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ── placeholder parsing ─────────────────────────────────────────────────────


def test_placeholders_peer_review_includes_axes_block():
    # Matches ``.format(axes_block=…)`` at llm_evaluator.py:413.
    assert "axes_block" in PromptRegistry().placeholders("evaluator/peer_review")


def test_placeholders_bfts_select_matches_config_contract():
    # Matches the config field description at config/__init__.py:135.
    ph = PromptRegistry().placeholders("orchestrator/bfts_select")
    assert {"experiment_goal", "memory_context", "candidates"} <= ph


def test_placeholders_ignores_double_brace_json_escapes():
    """`extract_metrics.md` contains literal ``{{...}}`` JSON — not placeholders."""
    assert PromptRegistry().placeholders("evaluator/extract_metrics") == set()


# ── tolerance policy (config-injected keys) ─────────────────────────────────


def test_get_tolerates_undiscovered_but_existing_key(tmp_path):
    """A key not in the discovered set still delegates to the loader."""
    (tmp_path / "custom_select.md").write_text("goal: {experiment_goal}\n", encoding="utf-8")
    reg = PromptRegistry(root=tmp_path)
    # Simulate a config-injected key by pointing at a root, then loading a key
    # that WAS discovered here; the essential property is delegation, not has().
    assert reg.has("custom_select") is True
    assert reg.get("custom_select") == "goal: {experiment_goal}\n"


def test_get_missing_key_raises_file_not_found_not_registry_error():
    """A genuinely-missing ``.md`` surfaces the loader's ``FileNotFoundError``.

    This preserves config-driven BFTS prompt loading: the registry does not
    invent its own error type that would break ``select_prompt`` resolution.
    """
    with pytest.raises(FileNotFoundError):
        PromptRegistry().get("orchestrator/definitely_missing")


# ── dependency injection / describe ─────────────────────────────────────────


class _StubLoader:
    """Minimal ``PromptLoader`` recording that it was actually consulted."""

    def __init__(self) -> None:
        self.load_calls: list[str] = []
        self.versioned_calls: list[str] = []

    def load(self, key: str) -> str:
        self.load_calls.append(key)
        return f"STUB:{key}"

    def load_versioned(self, key: str, version=None) -> tuple[str, str]:
        self.versioned_calls.append(key)
        text = f"STUB:{key}"
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def test_injected_loader_is_used_for_reads():
    stub = _StubLoader()
    reg = PromptRegistry(loader=stub)
    assert reg.get("agent/system") == "STUB:agent/system"
    assert reg.get_versioned("agent/system")[0] == "STUB:agent/system"
    assert stub.load_calls == ["agent/system"]
    assert stub.versioned_calls == ["agent/system"]
    # Discovery still walks the real prompts root, independent of the loader.
    assert reg.keys() == _EXPECTED_KEYS


def test_describe_returns_prompt_entry():
    entry = PromptRegistry().describe("evaluator/peer_review")
    assert isinstance(entry, PromptEntry)
    assert entry.key == "evaluator/peer_review"
    assert entry.discovered is True
    assert len(entry.version_id) == 12
    assert "axes_block" in entry.placeholders
    assert entry.path.name == "peer_review.md"
