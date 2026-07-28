"""RQGM Task 07 — GovernedPromptLoader + evolved prompt bodies
(docs/plans/ari_rqgm/07 §5.5-§5.6, §9).

Covers: Protocol conformance (``isinstance`` under ``runtime_checkable``),
byte-identical delegation for ungoverned keys (compared against the raw
snapshot goldens), checkpoint-scoped ``template_ref`` resolution under
``tmp_path`` with ``ARI_CHECKPOINT_DIR`` monkeypatched (repo convention),
hash-mismatch refusal (no in-place mutation), the write-once evolved-body
store, and the active-view builder.

No test calls a real LLM (P2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.prompts import FilesystemPromptLoader, PromptRegistry
from ari.protocols import PromptLoader
from ari.rqgm.events import hash12
from ari.rqgm.prompt_loader import (
    GovernedPromptLoader,
    PromptImmutabilityError,
    active_prompt_view,
    checkpoint_prompts_dir,
    evolved_prompt_path,
    resolve_checkpoint_prompt_text,
    write_evolved_prompt_body,
)
from ari.rqgm.prompt_spec import PromptSpec, build_founding_specs

_SNAP_DIR = Path(__file__).parent / "snapshots" / "prompts"


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _checkpoint_spec(prompt_id: str, text: str, **overrides) -> PromptSpec:
    base = dict(
        prompt_id=prompt_id,
        role="reviewer",
        version=2,
        status="active",
        generation_mode="mutation",
        parent_prompt_id="reviewer_prompt_v1",
        template_ref={"kind": "checkpoint",
                      "key": f"rqgm_prompts/{prompt_id}"},
        prompt_hash=hash12(text),
        full_sha256="0" * 64,
        spec={},
    )
    base.update(overrides)
    return PromptSpec(**base)


# ── Protocol conformance ─────────────────────────────────────────────────────


def test_governed_loader_satisfies_prompt_loader_protocol():
    loader = GovernedPromptLoader({})
    assert isinstance(loader, PromptLoader)
    assert isinstance(FilesystemPromptLoader(), PromptLoader)


# ── byte-identical delegation (§5.5 / §8) ────────────────────────────────────


def test_ungoverned_keys_delegate_byte_identically_to_goldens():
    """Every raw snapshot golden must come back byte-identical through a
    GovernedPromptLoader with an empty view — `simple_bfts` parity."""
    loader = GovernedPromptLoader({})
    fs = FilesystemPromptLoader()
    keys = PromptRegistry().keys()
    assert keys, "no prompt keys discovered"
    for key in keys:
        golden = _SNAP_DIR / f"{key}.md"
        assert golden.exists(), f"missing raw golden for {key}"
        text, version_id = loader.load_versioned(key)
        assert text == golden.read_text(encoding="utf-8")
        assert (text, version_id) == fs.load_versioned(key)


def test_governed_package_ref_delegates_and_verifies_hash():
    specs = build_founding_specs()
    view = active_prompt_view(specs)
    loader = GovernedPromptLoader(view)
    fs = FilesystemPromptLoader()
    assert loader.load_versioned("orchestrator/bfts_expand") == (
        fs.load_versioned("orchestrator/bfts_expand")
    )
    assert loader.load("evaluator/peer_review") == fs.load(
        "evaluator/peer_review"
    )


# ── checkpoint-scoped resolution (§5.6) ──────────────────────────────────────


def test_checkpoint_ref_resolves_under_env_pinned_checkpoint(
    monkeypatch, tmp_path
):
    text = "evolved reviewer prompt {proposal}\n"
    write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", text)
    spec = _checkpoint_spec("reviewer_prompt_v2", text)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    loader = GovernedPromptLoader({"rqgm_prompts/reviewer_prompt_v2": spec})
    got_text, got_hash = loader.load_versioned(
        "rqgm_prompts/reviewer_prompt_v2"
    )
    assert got_text == text
    assert got_hash == hash12(text) == spec.prompt_hash


def test_checkpoint_ref_explicit_dir_beats_env(tmp_path):
    text = "evolved body\n"
    write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", text)
    spec = _checkpoint_spec("reviewer_prompt_v2", text)
    loader = GovernedPromptLoader(
        {"rqgm_prompts/reviewer_prompt_v2": spec}, checkpoint_dir=tmp_path
    )
    assert loader.load("rqgm_prompts/reviewer_prompt_v2") == text


def test_checkpoint_ref_without_checkpoint_raises(tmp_path):
    spec = _checkpoint_spec("reviewer_prompt_v2", "body\n")
    loader = GovernedPromptLoader({"rqgm_prompts/reviewer_prompt_v2": spec})
    with pytest.raises(FileNotFoundError):
        loader.load("rqgm_prompts/reviewer_prompt_v2")


def test_hash_mismatch_is_refused(tmp_path):
    """Serving bytes that no longer match the frozen spec identity is an
    in-place mutation and must never succeed."""
    text = "original body\n"
    write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", text)
    spec = _checkpoint_spec(
        "reviewer_prompt_v2", text, prompt_hash=hash12("something else")
    )
    loader = GovernedPromptLoader(
        {"rqgm_prompts/reviewer_prompt_v2": spec}, checkpoint_dir=tmp_path
    )
    with pytest.raises(ValueError):
        loader.load("rqgm_prompts/reviewer_prompt_v2")


def test_resolve_checkpoint_prompt_text_helper(tmp_path):
    write_evolved_prompt_body(tmp_path, "g9", "body\n")
    assert resolve_checkpoint_prompt_text(
        tmp_path, "rqgm_prompts/g9.md"
    ) == ("body\n", hash12("body\n"))
    with pytest.raises(FileNotFoundError):
        resolve_checkpoint_prompt_text(None, "rqgm_prompts/g9.md")


# ── write-once bodies (no in-place mutation) ─────────────────────────────────


def test_write_evolved_prompt_body_is_write_once(tmp_path):
    path = write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", "a\n")
    assert path == evolved_prompt_path(tmp_path, "reviewer_prompt_v2")
    assert path.parent == checkpoint_prompts_dir(tmp_path)
    # Identical bytes: idempotent no-op (resume safety).
    write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", "a\n")
    # Different bytes: refused — a new prompt_id is required.
    with pytest.raises(PromptImmutabilityError):
        write_evolved_prompt_body(tmp_path, "reviewer_prompt_v2", "b\n")
    assert path.read_text(encoding="utf-8") == "a\n"


# ── active view builder ──────────────────────────────────────────────────────


def test_active_prompt_view_filters_statuses_and_last_wins():
    a1 = _checkpoint_spec("reviewer_prompt_v2", "a\n", status="active")
    shadow = _checkpoint_spec(
        "reviewer_prompt_v3", "b\n", status="shadow",
        template_ref={"kind": "checkpoint",
                      "key": "rqgm_prompts/reviewer_prompt_v3"},
    )
    prob = _checkpoint_spec(
        "reviewer_prompt_v4", "c\n", status="probationary_active",
        template_ref={"kind": "checkpoint",
                      "key": "rqgm_prompts/reviewer_prompt_v2"},
    )
    view = active_prompt_view([a1, shadow, prob])
    # shadow/candidate specs never enter the active view; for a contested
    # key the LAST registered active spec wins (event order).
    assert set(view) == {"rqgm_prompts/reviewer_prompt_v2"}
    assert view["rqgm_prompts/reviewer_prompt_v2"].prompt_id == (
        "reviewer_prompt_v4"
    )
