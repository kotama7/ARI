"""Test fixtures.``InMemoryBackend`` (or an injected ``FakeLettaClient``
for ``LettaBackend``-specific paths). ARI_CHECKPOINT_DIR is set per test
to a tmp_path via the ``ckpt_env`` fixture.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the package-under-test is on sys.path (editable install not required
# during dev).
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@pytest.fixture
def ckpt_env(tmp_path, monkeypatch):
    """Create a fresh checkpoint dir + env and yield its Path."""
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "nX")
    monkeypatch.setenv("ARI_MEMORY_ACCESS_LOG", "on")
    # Isolate backend cache per-test.
    from ari_skill_memory.backends import clear_backend_cache
    clear_backend_cache()
    yield ckpt
    clear_backend_cache()


@pytest.fixture
def backend(ckpt_env):
    from ari_skill_memory.backends import get_backend
    return get_backend(checkpoint_dir=ckpt_env)


@pytest.fixture
def fake_letta_backend(ckpt_env, monkeypatch):
    """LettaBackend wired to an in-process FakeLettaClient."""
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "letta")
    from ari_skill_memory.config import load_config
    from ari_skill_memory.backends.letta_backend import LettaBackend
    from fake_letta import FakeLettaClient
    cfg = load_config(ckpt_env)
    fake = FakeLettaClient()
    # Align the fake's embedding_config with whatever env asks for so
    # generic LettaBackend tests don't trip the embedding-mismatch
    # integrity check (which is exercised on its own in
    # test_letta_embedding_compat.py). The fake represents a freshly
    # created agent — under normal use the agent is created with the
    # configured handle, so its config matches.
    configured = (cfg.letta_embedding_config or "letta-default").strip()
    if configured.lower() not in ("", "letta-default"):
        fake.embedding_config = {
            "handle": configured,
            "embedding_endpoint": (
                "https://api.openai.com/v1/embeddings"
                if configured.startswith("openai/")
                else "http://localhost:11434"
                if configured.startswith("ollama/")
                else ""
            ),
            "embedding_model": configured.split("/")[-1],
        }
    return LettaBackend(cfg, client=fake), fake
