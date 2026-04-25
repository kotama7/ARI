"""Integrity check: agent's embedding_config vs configured handle.

The original ``add_memory`` 400 (``Expecting value: line 1 column 1
(char 0)``) reproduced when an agent created with the public
``letta/letta-free`` embedding handle (endpoint
``https://embeddings.memgpt.ai``) tried to insert while the upstream
embedding service was down — Letta's ``embeddings.py:_call_api`` calls
``response.json()`` on the empty 522 body and raises ``JSONDecodeError``,
which the server then repackages as a 400.

We can't fix Letta's code, but we can detect the failure mode at agent
load time and surface a clear, actionable error rather than letting the
opaque 400 escape on every write. These tests pin that behavior:

  - When the agent uses the flaky public endpoint AND the operator has
    explicitly configured a different ``LETTA_EMBEDDING_CONFIG``, we
    raise a ``RuntimeError`` naming both handles and the recovery path.
  - When the operator has NOT explicitly configured anything (handle is
    the default ``letta-default``), we just warn and let the call
    proceed — backwards-compatible with default deployments.
  - When the agent already uses the configured handle, no error.
"""
from __future__ import annotations

import logging

import pytest


@pytest.fixture
def letta_backend_with_fake(ckpt_env, monkeypatch):
    """Build a LettaBackend with FakeLettaClient and full control over
    its embedding_config — used by the integrity-check tests."""
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "letta")
    from ari_skill_memory.config import load_config
    from ari_skill_memory.backends.letta_backend import LettaBackend
    from fake_letta import FakeLettaClient

    def _build(*, configured: str, agent_handle: str, agent_endpoint: str):
        monkeypatch.setenv("LETTA_EMBEDDING_CONFIG", configured)
        cfg = load_config(ckpt_env)
        fake = FakeLettaClient()
        fake.embedding_config = {
            "handle": agent_handle,
            "embedding_endpoint": agent_endpoint,
            "embedding_model": agent_handle.split("/")[-1],
        }
        return LettaBackend(cfg, client=fake), fake

    return _build


def test_explicit_mismatch_with_memgpt_ai_raises(letta_backend_with_fake):
    """Operator asked for OpenAI; agent is wired to memgpt.ai → hard error."""
    backend, _ = letta_backend_with_fake(
        configured="openai/text-embedding-3-small",
        agent_handle="letta/letta-free",
        agent_endpoint="https://embeddings.memgpt.ai",
    )
    with pytest.raises(RuntimeError) as ei:
        backend.add_memory("nX", "any", {})
    msg = str(ei.value)
    assert "embedding mismatch" in msg
    assert "letta/letta-free" in msg
    assert "openai/text-embedding-3-small" in msg
    assert "purge_checkpoint" in msg


def test_default_with_memgpt_ai_warns_but_allows(
    letta_backend_with_fake, caplog
):
    """Operator did not ask for anything specific (``letta-default``)
    → behavior must be backwards-compatible: warn but don't block."""
    caplog.set_level(logging.WARNING, logger="ari_skill_memory")
    backend, _ = letta_backend_with_fake(
        configured="letta-default",
        agent_handle="letta/letta-free",
        agent_endpoint="https://embeddings.memgpt.ai",
    )
    # Must not raise.
    r = backend.add_memory("nX", "any", {})
    assert r["ok"] is True
    assert any(
        "embeddings.memgpt.ai" in rec.getMessage()
        for rec in caplog.records
    ), "expected a warning about the flaky endpoint"


def test_matched_handle_no_error(letta_backend_with_fake):
    """Configured handle matches the agent — silent happy path."""
    backend, _ = letta_backend_with_fake(
        configured="openai/text-embedding-3-small",
        agent_handle="openai/text-embedding-3-small",
        agent_endpoint="https://api.openai.com/v1/embeddings",
    )
    r = backend.add_memory("nX", "any", {})
    assert r["ok"] is True


def test_compat_check_runs_only_once_per_agent(letta_backend_with_fake):
    """The check should fire on first agent resolution and not again on
    subsequent calls — otherwise it adds latency to every write."""
    backend, fake = letta_backend_with_fake(
        configured="openai/text-embedding-3-small",
        agent_handle="openai/text-embedding-3-small",
        agent_endpoint="https://api.openai.com/v1/embeddings",
    )
    calls = {"n": 0}
    orig = fake.get_agent_embedding

    def counting(agent_id):
        calls["n"] += 1
        return orig(agent_id)

    fake.get_agent_embedding = counting  # type: ignore[assignment]
    backend.add_memory("nX", "first", {})
    backend.add_memory("nX", "second", {})
    backend.add_memory("nX", "third", {})
    assert calls["n"] <= 1, (
        f"embedding probe ran {calls['n']} times; should be cached"
    )
