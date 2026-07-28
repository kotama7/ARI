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
    # RQGM Task 03 — ProposalRouter generator prompts (committed from day
    # one; hashes captured at extraction, docs/plans/ari_rqgm/03 §7).
    (
        "rqgm/proposal_cheap",
        "49e2b05bdfebc42f4c0ae3b928b97c4ec2cd0e34722824880e7df51c1cad07ab",
    ),
    (
        "rqgm/proposal_mutation",
        "b77da9cc7e1529cd4c4ede327ed6fc18d82a502991c7a109757b2df20c007107",
    ),
    (
        "rqgm/proposal_prior_art",
        "81d78be59631b33af9a1479bc4ef7fd0c9d8de6143951be7c0805eaab8b26075",
    ),
    # RQGM Task 06 — adversarial-loop actor prompts (committed from day one;
    # hashes captured at extraction, docs/plans/ari_rqgm/06 §5.2/§7).
    (
        "rqgm/adversary_overclaim",
        "f037e38ea9fc4364d35eef417e36ee41ba4508ed95b5527a5b8a723493c4d256",
    ),
    (
        "rqgm/adversary_metric_gaming",
        "7ec5dac24de042558a8774863eaee773948c2da5b66e690e1f21c4a7963b2f99",
    ),
    (
        "rqgm/adversary_prior_art",
        "215e2e8f2482a6b701e9d70a25e8f66f019f9fdc67fb050bbf3156795106132d",
    ),
    (
        "rqgm/adversary_reproducibility",
        "82c54c806503ce229d013ae37fe62ccd9d82266a9e90092155913c034c5d63e6",
    ),
    (
        "rqgm/adversary_evidence_gap",
        "87d938dca63c26d5fd52787813deb221b22e4fe051baec743a388d64a3d12e71",
    ),
    (
        "rqgm/adversary_cost_explosion",
        "c1d10f56b70ed478e48f5742b3337fda17e6ab26dc14e7d0b9dcee6fd0d7547f",
    ),
    (
        "rqgm/adversary_prompt_injection",
        "51897a5425e055983ee174252cd304d9b729dd17c9e7947653ba6f097faa04d7",
    ),
    # Paper-archive Task 05 — the eighth (paper-phase) adversary template
    # (docs/plans/ari_rqgm_paper/05 §5.1; paper-mode-gated founding row).
    (
        "rqgm/adversary_paper_self_preference",
        "9dfe9812549b7e092718065f7e946dd44471451603c0bd117a72dcf890ef0e97",
    ),
    (
        "rqgm/defender",
        "f029469f8b6c75c6e18ba74277eed76dfc7b16650505010dedc637c4c3a9304a",
    ),
    (
        "rqgm/judge_adjudication",
        "7e8dd5ed5fe5332cc2908dca6c8185676f192423b995992ca68c25a047b8329a",
    ),
    # RQGM Task 07 — PromptMutator meta-prompt (committed from day one;
    # hash captured at extraction, docs/plans/ari_rqgm/07 §5.4/§7).
    (
        "rqgm/prompt_mutator",
        "859a0ce514d3f4407ff0eba31a1c40ab447d591446f612bac7af7654f5efd847",
    ),
    # RQGM Task 08 — CleanRoomPromptGenerator meta-prompt (committed from
    # day one; hash captured at extraction, docs/plans/ari_rqgm/08 §5.3/§7).
    (
        "rqgm/clean_room_generator",
        "1def8e77f92fdd0e735708f6b2fa5fd5d878b9b297a84c68d2e266552e880550",
    ),
    # Paper-archive co-evolution (plan ari_rqgm_paper/03 §5.5) — the governed
    # manuscript writer/reviewer founding templates, LIFTED byte-identical
    # from ari-skill-paper/src/prompts/{paper_writer,academic_reviewer}.md so
    # the governed roles start from exactly today's proven behavior.
    (
        "rqgm/paper_writer",
        "f38a15f0f140912dcd7eb5df13ca4ff706f60c4731c3c9feea508c1fb21cba7c",
    ),
    (
        "rqgm/paper_reviewer",
        "04b3c49d070d729065dcd2e9806f8580fbe0362c939b6c447cc57fefd188f186",
    ),
    # RQGM Task 05 — governance-actor prompts (committed from day one;
    # hashes captured at extraction, docs/plans/ari_rqgm/05 §5.3/§7).
    (
        "governance/auditor",
        "9f0efc9e07746850289f3be38f821f67e35772e775814f620be1289c6d5b774c",
    ),
    (
        "governance/defender",
        "4c65730dee1a6a03289c059d62e858e9c4000e1e95d2dce86b2e4513453d89cb",
    ),
    (
        "governance/governance_judge",
        "a70a98ed166c6479c177e0630b59794f0f23933259149cd94e0d77daff54fff9",
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
