"""Regression: the Letta agent's chat LLM is hardcoded inside this skill.

Background
----------
ARI never invokes the Letta agent's chat / messages API anywhere in
``ari_skill_memory``: only ``archival_insert`` and ``archival_search``
are called, and those use embeddings only. The Letta SDK still requires
a ``model=`` argument on ``agents.create``, so the skill passes a fixed
mock handle. The user-facing ``LETTA_LLM_CONFIG`` setting and
``letta_llm_config`` MemoryConfig field were removed because they
controlled a value that was never exercised.

These tests pin that contract so a future refactor can't quietly
re-introduce the dead config:

1. ``MemoryConfig`` must NOT have a ``letta_llm_config`` field — the
   public dataclass is the API surface other ARI components use.
2. ``LETTA_LLM_CONFIG`` env must NOT be read by ``load_config`` — even
   if it's set in the environment, it must have no effect.
3. ``_SdkLettaAdapter`` must construct cleanly without an LLM config and
   the model passed to ``agents.create`` must be the fixed mock handle.
"""
from __future__ import annotations

import dataclasses

import pytest

from ari_skill_memory.backends.letta_client import _SdkLettaAdapter
from ari_skill_memory.config import MemoryConfig, load_config


def _build_cfg(tmp_path) -> MemoryConfig:
    return MemoryConfig(
        checkpoint_dir=tmp_path,
        ckpt_hash="cafebabe1234",
        backend_name="letta",
        letta_base_url="http://letta-mock.test:8283",
        letta_api_key="",
        letta_embedding_config="letta-default",
        letta_timeout_s=10.0,
        letta_overfetch=200,
        letta_disable_self_edit=True,
        access_log_enabled=False,
        access_log_preview_chars=200,
        access_log_max_mb=100,
        react_search_limit=10,
        react_max_entry_chars=0,
    )


def test_memory_config_has_no_letta_llm_field():
    """The dataclass must not declare ``letta_llm_config`` — this would
    re-create the dead user-facing knob."""
    field_names = {f.name for f in dataclasses.fields(MemoryConfig)}
    assert "letta_llm_config" not in field_names, (
        "letta_llm_config must stay removed; the Letta agent's chat LLM "
        "is hardcoded inside _SdkLettaAdapter because ARI never invokes "
        "the agent's chat API. Re-adding this field re-exposes a "
        "user-configurable value that has no effect."
    )


def test_load_config_ignores_letta_llm_config_env(tmp_path, monkeypatch):
    """Even with ``LETTA_LLM_CONFIG`` set, ``load_config`` must not surface
    it on the resulting ``MemoryConfig``."""
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("LETTA_LLM_CONFIG", "openai/gpt-4o-mini")
    cfg = load_config(tmp_path)
    assert not hasattr(cfg, "letta_llm_config"), (
        "load_config must not expose letta_llm_config on MemoryConfig"
    )


def test_sdk_adapter_uses_hardcoded_mock_model(tmp_path):
    """``_SdkLettaAdapter._model`` must be the fixed default handle
    regardless of any env or config — it's the mock that satisfies the
    Letta SDK's mandatory ``model=`` arg without exposing user choice."""

    class _DummyLetta:
        def __init__(self, **_):
            pass

    cfg = _build_cfg(tmp_path)
    adapter = _SdkLettaAdapter(cfg, _DummyLetta)
    assert adapter._model == _SdkLettaAdapter._DEFAULT_HANDLE


def test_sdk_adapter_passes_mock_model_to_agents_create(tmp_path):
    """Verify the wire-level contract: ``agents.create`` receives the
    fixed mock handle as ``model=``. Captures kwargs from a fake SDK."""
    captured: dict = {}

    class _FakeAgents:
        def list(self, **_):
            return []

        def create(self, **kwargs):
            captured.update(kwargs)

            class _A:
                id = "agent-test-001"

            return _A()

    class _FakeLetta:
        def __init__(self, **_):
            self.agents = _FakeAgents()

    cfg = _build_cfg(tmp_path)
    adapter = _SdkLettaAdapter(cfg, _FakeLetta)
    aid = adapter.ensure_agent(
        "ari_agent_test", memory_editing_enabled=False, collections=[],
    )
    assert aid == "agent-test-001"
    assert captured.get("model") == _SdkLettaAdapter._DEFAULT_HANDLE, (
        f"agents.create must receive the fixed mock handle; got "
        f"{captured.get('model')!r}"
    )
