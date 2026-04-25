"""Tests for ari.cost_tracker — pricing accuracy and model matching."""
import json
import math
from pathlib import Path

import pytest

from ari.cost_tracker import _PRICING, _estimate_cost, CostTracker
import ari.cost_tracker as cost_tracker_mod


# ══════════════════════════════════════════════
# 1. Pricing table: values match official rates
#    Verified 2026-03-28 against:
#      openai.com/api/pricing
#      claude.com/pricing (Anthropic docs)
#      ai.google.dev/pricing
# ══════════════════════════════════════════════

class TestPricingValues:
    """Each test encodes the official per-1K-token rate."""

    # --- OpenAI ---
    def test_gpt4o(self):
        assert _PRICING["gpt-4o"] == (0.0025, 0.010)

    def test_gpt4o_mini(self):
        assert _PRICING["gpt-4o-mini"] == (0.00015, 0.0006)

    def test_gpt5(self):
        # $1.25/$10.00 per MTok → $0.00125/$0.010 per KTok
        assert _PRICING["gpt-5"] == (0.00125, 0.010)

    def test_gpt5_2(self):
        # $1.75/$14.00 per MTok → $0.00175/$0.014 per KTok
        assert _PRICING["gpt-5.2"] == (0.00175, 0.014)

    def test_o3(self):
        # $2.00/$8.00 per MTok
        assert _PRICING["o3"] == (0.002, 0.008)

    def test_o3_mini(self):
        # $1.10/$4.40 per MTok
        assert _PRICING["o3-mini"] == (0.0011, 0.0044)

    def test_o4_mini(self):
        # $1.10/$4.40 per MTok
        assert _PRICING["o4-mini"] == (0.0011, 0.0044)

    def test_gpt4(self):
        assert _PRICING["gpt-4"] == (0.03, 0.06)

    def test_gpt35_turbo(self):
        assert _PRICING["gpt-3.5-turbo"] == (0.0005, 0.0015)

    # --- Anthropic ---
    def test_claude_opus_4_6(self):
        # $5/$25 per MTok
        assert _PRICING["claude-opus-4-6"] == (0.005, 0.025)

    def test_claude_sonnet_4_6(self):
        # $3/$15 per MTok
        assert _PRICING["claude-sonnet-4-6"] == (0.003, 0.015)

    def test_claude_sonnet_4_5(self):
        assert _PRICING["claude-sonnet-4-5"] == (0.003, 0.015)

    def test_claude_opus_4_5(self):
        assert _PRICING["claude-opus-4-5"] == (0.005, 0.025)

    def test_claude_opus_4_1(self):
        # $15/$75 per MTok
        assert _PRICING["claude-opus-4-1"] == (0.015, 0.075)

    def test_claude_opus_4(self):
        assert _PRICING["claude-opus-4"] == (0.015, 0.075)

    def test_claude_sonnet_4(self):
        assert _PRICING["claude-sonnet-4"] == (0.003, 0.015)

    def test_claude_haiku_4_5(self):
        # $1/$5 per MTok
        assert _PRICING["claude-haiku-4-5"] == (0.001, 0.005)

    def test_claude_3_5_sonnet(self):
        assert _PRICING["claude-3-5-sonnet"] == (0.003, 0.015)

    def test_claude_3_opus(self):
        assert _PRICING["claude-3-opus"] == (0.015, 0.075)

    # --- Google Gemini ---
    def test_gemini_25_pro(self):
        # $1.25/$10 per MTok (<=200k context)
        assert _PRICING["gemini-2.5-pro"] == (0.00125, 0.010)

    def test_gemini_20_flash(self):
        # $0.10/$0.40 per MTok
        assert _PRICING["gemini-2.0-flash"] == (0.0001, 0.0004)

    def test_gemini_15_pro(self):
        assert _PRICING["gemini-1.5-pro"] == (0.00125, 0.005)


# ══════════════════════════════════════════════
# 2. _estimate_cost — arithmetic and matching
# ══════════════════════════════════════════════

class TestEstimateCost:
    def test_basic_calculation(self):
        # gpt-4o: 1000 input + 500 output
        # = (1000 * 0.0025 + 500 * 0.010) / 1000 = (2.5 + 5.0) / 1000 = 0.0075
        cost = _estimate_cost("gpt-4o", 1000, 500)
        assert math.isclose(cost, 0.0075, rel_tol=1e-6)

    def test_zero_tokens(self):
        assert _estimate_cost("gpt-4o", 0, 0) == 0.0

    def test_unknown_model_returns_zero(self):
        assert _estimate_cost("totally-unknown-model", 1000, 1000) == 0.0

    def test_ollama_local_returns_zero(self):
        """Ollama (local) models are free — cost must be 0."""
        assert _estimate_cost("ollama_chat/qwen3:8b", 10000, 5000) == 0.0
        assert _estimate_cost("ollama_chat/llama3.3", 10000, 5000) == 0.0


# ══════════════════════════════════════════════
# 3. Model name matching (substring in litellm format)
#    LLMClient._model_name() produces:
#      openai:    "gpt-4o"
#      anthropic: "anthropic/claude-opus-4-6"
#      ollama:    "ollama_chat/qwen3:8b"
#      gemini:    "gemini/gemini-2.5-pro"
# ══════════════════════════════════════════════

class TestModelMatching:
    """Verify that _estimate_cost finds the right pricing key for each litellm model string."""

    def _match(self, model: str) -> str | None:
        return next((k for k in _PRICING if k in model.lower()), None)

    # OpenAI (bare names)
    def test_match_gpt4o(self):
        assert self._match("gpt-4o") == "gpt-4o-mini" or self._match("gpt-4o") == "gpt-4o"
        # More specific: gpt-4o must not match gpt-4o-mini
        assert self._match("gpt-4o") == "gpt-4o"

    def test_match_gpt4o_mini(self):
        assert self._match("gpt-4o-mini") == "gpt-4o-mini"

    def test_match_gpt5(self):
        assert self._match("gpt-5") == "gpt-5"

    def test_match_gpt5_2(self):
        assert self._match("gpt-5.2") == "gpt-5.2"

    def test_match_o3(self):
        assert self._match("o3") == "o3-mini" or self._match("o3") == "o3"
        assert self._match("o3") == "o3"

    def test_match_o3_mini(self):
        assert self._match("o3-mini") == "o3-mini"

    def test_match_o4_mini(self):
        assert self._match("o4-mini") == "o4-mini"

    # Anthropic (prefixed)
    def test_match_anthropic_opus_46(self):
        assert self._match("anthropic/claude-opus-4-6") == "claude-opus-4-6"

    def test_match_anthropic_sonnet_46(self):
        assert self._match("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"

    def test_match_anthropic_sonnet_45(self):
        assert self._match("anthropic/claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"

    def test_match_anthropic_haiku_45(self):
        assert self._match("anthropic/claude-haiku-4-5-20251001") == "claude-haiku-4-5"

    def test_match_anthropic_opus_4(self):
        assert self._match("anthropic/claude-opus-4-20250514") == "claude-opus-4"

    def test_match_anthropic_sonnet_4(self):
        assert self._match("anthropic/claude-sonnet-4-20250514") == "claude-sonnet-4"

    # Versioned Anthropic (e.g. claude-3-5-sonnet-20241022)
    def test_match_claude_35_sonnet_versioned(self):
        assert self._match("anthropic/claude-3-5-sonnet-20241022") == "claude-3-5-sonnet"

    def test_match_claude_3_opus_versioned(self):
        assert self._match("anthropic/claude-3-opus-20240229") == "claude-3-opus"

    # Gemini (prefixed)
    def test_match_gemini_25_pro(self):
        assert self._match("gemini/gemini-2.5-pro") == "gemini-2.5-pro"

    def test_match_gemini_20_flash(self):
        assert self._match("gemini/gemini-2.0-flash") == "gemini-2.0-flash"

    def test_match_gemini_15_pro(self):
        assert self._match("gemini/gemini-1.5-pro") == "gemini-1.5-pro"

    # Ambiguity: more-specific key must match before less-specific
    def test_gpt4o_mini_not_gpt4o(self):
        """gpt-4o-mini must match 'gpt-4o-mini', not 'gpt-4o'."""
        assert self._match("gpt-4o-mini") == "gpt-4o-mini"

    def test_gpt5_2_not_gpt5(self):
        """gpt-5.2 must match 'gpt-5.2', not 'gpt-5'."""
        assert self._match("gpt-5.2") == "gpt-5.2"

    def test_o3_mini_not_o3(self):
        """o3-mini must match 'o3-mini', not 'o3'."""
        assert self._match("o3-mini") == "o3-mini"

    def test_opus_46_not_opus_4(self):
        """claude-opus-4-6 must not match generic 'claude-opus-4'."""
        assert self._match("anthropic/claude-opus-4-6") == "claude-opus-4-6"

    def test_sonnet_45_not_sonnet_4(self):
        """claude-sonnet-4-5 must not match 'claude-sonnet-4'."""
        assert self._match("anthropic/claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"


# ══════════════════════════════════════════════
# 4. CostTracker integration
# ══════════════════════════════════════════════

class TestCostTracker:
    def test_record_and_summary(self, tmp_path):
        ct = CostTracker(tmp_path)
        ct.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=500,
                  node_id="n1", phase="bfts", skill="coding")
        assert ct.total_tokens == 1500
        assert ct.total_cost_usd > 0
        # Summary file written
        summary = json.loads((tmp_path / "cost_summary.json").read_text())
        assert summary["total_tokens"] == 1500
        assert summary["call_count"] == 1

    def test_trace_jsonl_written(self, tmp_path):
        ct = CostTracker(tmp_path)
        ct.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        lines = (tmp_path / "cost_trace.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["model"] == "gpt-4o"
        assert rec["prompt_tokens"] == 100

    def test_unknown_model_zero_cost(self, tmp_path):
        ct = CostTracker(tmp_path)
        ct.record(model="ollama_chat/qwen3:8b", prompt_tokens=10000, completion_tokens=5000)
        assert ct.total_cost_usd == 0.0

    def test_multiple_records_accumulate(self, tmp_path):
        ct = CostTracker(tmp_path)
        ct.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        ct.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        assert ct.total_tokens == 2000
        summary = json.loads((tmp_path / "cost_summary.json").read_text())
        assert summary["call_count"] == 2

    def test_by_model_breakdown(self, tmp_path):
        ct = CostTracker(tmp_path)
        ct.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        ct.record(model="anthropic/claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=0)
        summary = json.loads((tmp_path / "cost_summary.json").read_text())
        assert "gpt-4o" in summary["by_model"]
        assert "anthropic/claude-sonnet-4-6" in summary["by_model"]


# ══════════════════════════════════════════════
# 5. Re-init must not reset cost to zero
#    (regression test for the $0 bug)
# ══════════════════════════════════════════════

class TestCostTrackerReinit:
    """Verify that calling init() twice or creating a new CostTracker
    for the same directory preserves previously recorded costs."""

    def test_new_tracker_reloads_existing_trace(self, tmp_path):
        """Creating a second CostTracker on the same dir restores records from disk."""
        ct1 = CostTracker(tmp_path)
        ct1.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=500,
                   phase="bfts", skill="coding")
        cost_before = ct1.total_cost_usd
        tokens_before = ct1.total_tokens
        assert cost_before > 0

        # Simulate pipeline.py creating a new tracker for the same dir
        ct2 = CostTracker(tmp_path)
        assert ct2.total_cost_usd == cost_before
        assert ct2.total_tokens == tokens_before

    def test_new_tracker_continues_accumulating(self, tmp_path):
        """After reload, new records are added on top of existing ones."""
        ct1 = CostTracker(tmp_path)
        ct1.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        cost_after_first = ct1.total_cost_usd

        ct2 = CostTracker(tmp_path)
        ct2.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        assert ct2.total_cost_usd == pytest.approx(cost_after_first * 2, rel=1e-6)
        assert ct2.total_tokens == 2000

        # Verify cost_summary.json reflects the full total
        summary = json.loads((tmp_path / "cost_summary.json").read_text())
        assert summary["call_count"] == 2
        assert summary["total_tokens"] == 2000

    def test_init_idempotent_same_dir(self, tmp_path):
        """init() with the same directory returns the existing tracker."""
        old_tracker = cost_tracker_mod._tracker
        try:
            ct1 = cost_tracker_mod.init(tmp_path)
            ct1.record(model="gpt-4o", prompt_tokens=500, completion_tokens=100)
            cost_before = ct1.total_cost_usd

            # Second init with same path — must return same object
            ct2 = cost_tracker_mod.init(tmp_path)
            assert ct2 is ct1
            assert ct2.total_cost_usd == cost_before
        finally:
            cost_tracker_mod._tracker = old_tracker

    def test_init_idempotent_resolved_path(self, tmp_path):
        """init() treats equivalent paths (./dir vs dir) as the same."""
        old_tracker = cost_tracker_mod._tracker
        try:
            # Use two different Path representations of the same dir
            path_a = tmp_path / "ckpt"
            path_a.mkdir()
            path_b = tmp_path / "." / "ckpt"

            ct1 = cost_tracker_mod.init(path_a)
            ct1.record(model="gpt-4o", prompt_tokens=200, completion_tokens=50)

            ct2 = cost_tracker_mod.init(path_b)
            assert ct2 is ct1
        finally:
            cost_tracker_mod._tracker = old_tracker

    def test_init_different_dir_reloads(self, tmp_path):
        """init() with a new directory creates a fresh tracker that reloads disk records."""
        old_tracker = cost_tracker_mod._tracker
        try:
            dir_a = tmp_path / "run_a"
            dir_a.mkdir()
            dir_b = tmp_path / "run_b"
            dir_b.mkdir()

            ct1 = cost_tracker_mod.init(dir_a)
            ct1.record(model="gpt-4o", prompt_tokens=1000, completion_tokens=500)

            # Switch to a different dir — new tracker, no prior records
            ct2 = cost_tracker_mod.init(dir_b)
            assert ct2 is not ct1
            assert ct2.total_cost_usd == 0.0
            assert ct2.total_tokens == 0
        finally:
            cost_tracker_mod._tracker = old_tracker

    def test_reload_skips_corrupt_lines(self, tmp_path):
        """Corrupt JSONL lines are silently skipped during reload."""
        trace = tmp_path / "cost_trace.jsonl"
        good_record = {
            "timestamp": "2026-03-31T00:00:00Z", "node_id": "", "phase": "bfts",
            "skill": "coding", "model": "gpt-4o", "prompt_tokens": 1000,
            "completion_tokens": 500, "total_tokens": 1500,
            "estimated_cost_usd": 0.0075,
        }
        trace.write_text(
            json.dumps(good_record) + "\n"
            "NOT VALID JSON\n"
            "\n"
            + json.dumps(good_record) + "\n"
        )
        ct = CostTracker(tmp_path)
        assert len(ct._records) == 2
        assert ct.total_cost_usd == pytest.approx(0.015, rel=1e-6)

    def test_reload_empty_trace(self, tmp_path):
        """Empty cost_trace.jsonl does not crash."""
        (tmp_path / "cost_trace.jsonl").write_text("")
        ct = CostTracker(tmp_path)
        assert ct.total_cost_usd == 0.0
        assert ct.total_tokens == 0

    def test_reload_no_trace_file(self, tmp_path):
        """No cost_trace.jsonl file — starts fresh without error."""
        ct = CostTracker(tmp_path)
        assert ct.total_cost_usd == 0.0
        assert len(ct._records) == 0


# ══════════════════════════════════════════════
# 6. Metadata propagation via litellm callback
#    (regression: node_id/phase/skill were empty in cost_trace.jsonl)
# ══════════════════════════════════════════════

class _FakeUsage:
    def __init__(self, prompt=100, completion=50):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _FakeResponse:
    def __init__(self, model="gpt-4o", prompt=100, completion=50):
        self.model = model
        self.usage = _FakeUsage(prompt, completion)


class TestLitellmCallbackMetadata:
    """Verify that node_id/phase/skill supplied via litellm ``metadata=`` are
    carried into ``cost_trace.jsonl`` via ``_litellm_success_handler``."""

    def _fresh_tracker(self, tmp_path):
        """Drop the global singleton and return a fresh tracker on tmp_path."""
        old = cost_tracker_mod._tracker
        ct = cost_tracker_mod.init(tmp_path)
        return ct, old

    def test_metadata_from_litellm_params(self, tmp_path):
        """Primary path: litellm forwards ``metadata=`` into
        ``kwargs['litellm_params']['metadata']``."""
        _, prior = self._fresh_tracker(tmp_path)
        try:
            kwargs = {
                "model": "gpt-4o",
                "litellm_params": {
                    "metadata": {"node_id": "n42", "phase": "react", "skill": "agent_loop"},
                },
            }
            cost_tracker_mod._litellm_success_handler(kwargs, _FakeResponse(), 0, 0)
            line = (tmp_path / "cost_trace.jsonl").read_text().strip().splitlines()[-1]
            rec = json.loads(line)
            assert rec["node_id"] == "n42"
            assert rec["phase"] == "react"
            assert rec["skill"] == "agent_loop"
        finally:
            cost_tracker_mod._tracker = prior

    def test_metadata_from_top_level_kwarg(self, tmp_path):
        """Fallback path: metadata present at the top level (tests + older litellm)."""
        _, prior = self._fresh_tracker(tmp_path)
        try:
            kwargs = {
                "model": "gpt-4o",
                "metadata": {"node_id": "root", "phase": "bfts", "skill": "expand"},
            }
            cost_tracker_mod._litellm_success_handler(kwargs, _FakeResponse(), 0, 0)
            rec = json.loads((tmp_path / "cost_trace.jsonl").read_text().strip().splitlines()[-1])
            assert rec["node_id"] == "root"
            assert rec["phase"] == "bfts"
            assert rec["skill"] == "expand"
        finally:
            cost_tracker_mod._tracker = prior

    def test_missing_metadata_leaves_fields_empty(self, tmp_path):
        """No metadata → fields are empty strings (not errors)."""
        _, prior = self._fresh_tracker(tmp_path)
        try:
            kwargs = {"model": "gpt-4o"}
            cost_tracker_mod._litellm_success_handler(kwargs, _FakeResponse(), 0, 0)
            rec = json.loads((tmp_path / "cost_trace.jsonl").read_text().strip().splitlines()[-1])
            assert rec["node_id"] == ""
            assert rec["phase"] == ""
            assert rec["skill"] == ""
            # Tokens and model still captured
            assert rec["model"] == "gpt-4o"
            assert rec["prompt_tokens"] == 100
        finally:
            cost_tracker_mod._tracker = prior

    def test_zero_tokens_skipped(self, tmp_path):
        """Calls with zero prompt+completion tokens don't produce a record."""
        _, prior = self._fresh_tracker(tmp_path)
        try:
            kwargs = {"model": "gpt-4o"}
            resp = _FakeResponse(prompt=0, completion=0)
            cost_tracker_mod._litellm_success_handler(kwargs, resp, 0, 0)
            assert not (tmp_path / "cost_trace.jsonl").exists() or \
                   (tmp_path / "cost_trace.jsonl").read_text() == ""
        finally:
            cost_tracker_mod._tracker = prior


# ══════════════════════════════════════════════
# 7. LLMClient → cost_tracker: no double recording
#    (regression: records previously appeared twice per call)
# ══════════════════════════════════════════════

class TestLLMClientNoDoubleRecord:
    """``LLMClient.complete`` must record exactly once per LLM call."""

    def test_no_direct_record_call_in_client(self, tmp_path):
        """Confirm the client doesn't also call ``_ct.record`` directly —
        the global litellm callback is the single source of truth. Comment
        lines mentioning ``_ct.record`` are ignored; only executable code
        counts."""
        from ari.llm.client import LLMClient
        import inspect
        src = inspect.getsource(LLMClient.complete)
        code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        stripped = "\n".join(code_lines)
        assert "_ct.record(" not in stripped, (
            "LLMClient.complete() must not call cost_tracker.record() directly; "
            "rely on the global litellm success_callback instead to avoid double-counting."
        )

    def test_metadata_injected_into_kwargs(self):
        """LLMClient.complete constructs kwargs containing a metadata dict
        with the node_id/phase/skill it was told about."""
        import litellm as _litellm
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient, LLMMessage

        captured: dict = {}

        class _StubUsage:
            prompt_tokens = 1
            completion_tokens = 1
            total_tokens = 2

        class _StubMsg:
            content = "ok"
            tool_calls = None

        class _StubChoice:
            message = _StubMsg()

        class _StubResp:
            choices = [_StubChoice()]
            usage = _StubUsage()

        orig = _litellm.completion
        try:
            def _fake(*args, **kwargs):
                captured.update(kwargs)
                return _StubResp()
            _litellm.completion = _fake
            client = LLMClient(LLMConfig(backend="openai", model="gpt-4o"))
            client.complete(
                [LLMMessage(role="user", content="hi")],
                node_id="node-1", phase="react", skill="agent_loop",
            )
        finally:
            _litellm.completion = orig

        md = captured.get("metadata", {})
        assert md.get("node_id") == "node-1"
        assert md.get("phase") == "react"
        assert md.get("skill") == "agent_loop"

    def test_set_context_persists_across_calls(self):
        """Context set via ``set_context`` is reused on subsequent complete calls."""
        import litellm as _litellm
        from ari.config import LLMConfig
        from ari.llm.client import LLMClient, LLMMessage

        captured = []

        class _Resp:
            class _Choice:
                class _M:
                    content = "x"
                    tool_calls = None
                message = _M()
            choices = [_Choice()]

            class _U:
                prompt_tokens = 1
                completion_tokens = 1
                total_tokens = 2

            usage = _U()

        orig = _litellm.completion
        try:
            def _fake(*args, **kwargs):
                captured.append(kwargs.get("metadata", {}))
                return _Resp()
            _litellm.completion = _fake
            client = LLMClient(LLMConfig(backend="openai", model="gpt-4o"))
            client.set_context(node_id="n-7", phase="bfts", skill="expand")
            client.complete([LLMMessage(role="user", content="a")])
            client.complete([LLMMessage(role="user", content="b")])
        finally:
            _litellm.completion = orig

        assert all(c.get("node_id") == "n-7" for c in captured)
        assert all(c.get("phase") == "bfts" for c in captured)
        assert all(c.get("skill") == "expand" for c in captured)


# ══════════════════════════════════════════════
# 8. Skill bootstrap / env init / default-metadata injector
#    (skills running in subprocesses rely on these)
# ══════════════════════════════════════════════

class TestSkillBootstrap:
    def test_init_from_env_without_var(self, tmp_path, monkeypatch):
        """Missing ARI_CHECKPOINT_DIR → init_from_env returns None cleanly."""
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        old = cost_tracker_mod._tracker
        try:
            assert cost_tracker_mod.init_from_env() is None
        finally:
            cost_tracker_mod._tracker = old

    def test_init_from_env_with_var(self, tmp_path, monkeypatch):
        """Env var set → tracker initialised pointing at that dir."""
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
        old = cost_tracker_mod._tracker
        try:
            tracker = cost_tracker_mod.init_from_env()
            assert tracker is not None
            assert Path(tracker._trace_path).parent == tmp_path
        finally:
            cost_tracker_mod._tracker = old

    def test_set_default_metadata_injects_into_acompletion(self, tmp_path, monkeypatch):
        """After bootstrap_skill, litellm.acompletion calls carry the skill name."""
        import litellm as _litellm
        import asyncio

        # Reset the injector flag so the monkey-patch re-installs cleanly
        cost_tracker_mod._injector_installed = False
        cost_tracker_mod._DEFAULT_METADATA.clear()

        captured: dict = {}

        async def _fake_acompletion(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                usage = _FakeUsage()
                model = kwargs.get("model", "gpt-4o")

            return _R()

        def _fake_completion(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                usage = _FakeUsage()
                model = kwargs.get("model", "gpt-4o")

            return _R()

        orig_a = _litellm.acompletion
        orig_c = _litellm.completion
        old_tracker = cost_tracker_mod._tracker
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
        try:
            _litellm.acompletion = _fake_acompletion
            _litellm.completion = _fake_completion
            cost_tracker_mod.bootstrap_skill("paper", phase="write")

            # sync path
            _litellm.completion(model="gpt-4o")
            assert captured["metadata"]["skill"] == "paper"
            assert captured["metadata"]["phase"] == "write"

            captured.clear()
            # async path
            asyncio.run(_litellm.acompletion(model="gpt-4o"))
            assert captured["metadata"]["skill"] == "paper"
            assert captured["metadata"]["phase"] == "write"
        finally:
            _litellm.acompletion = orig_a
            _litellm.completion = orig_c
            cost_tracker_mod._tracker = old_tracker
            cost_tracker_mod._injector_installed = False
            cost_tracker_mod._DEFAULT_METADATA.clear()

    def test_default_metadata_does_not_overwrite_caller(self, tmp_path, monkeypatch):
        """Caller-supplied metadata wins on key collisions; defaults only fill gaps."""
        import litellm as _litellm

        cost_tracker_mod._injector_installed = False
        cost_tracker_mod._DEFAULT_METADATA.clear()
        captured: dict = {}

        def _fake_completion(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                usage = _FakeUsage()
                model = "gpt-4o"

            return _R()

        orig = _litellm.completion
        try:
            _litellm.completion = _fake_completion
            cost_tracker_mod.set_default_metadata(skill="paper", phase="write")

            # Caller overrides phase and adds node_id
            _litellm.completion(model="gpt-4o",
                                metadata={"phase": "reflect", "node_id": "n-9"})
            md = captured["metadata"]
            assert md["skill"] == "paper"       # from defaults (not specified by caller)
            assert md["phase"] == "reflect"     # caller wins
            assert md["node_id"] == "n-9"       # caller-only field
        finally:
            _litellm.completion = orig
            cost_tracker_mod._injector_installed = False
            cost_tracker_mod._DEFAULT_METADATA.clear()
