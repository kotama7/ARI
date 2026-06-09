"""Tests for the plan-fidelity claims resolution in make_metric_spec (evaluator).

Deterministic: the structured ``falsifiable_claims`` path needs no LLM. These
helpers extract the idea's claims into ``metric_contract.claims``, which the hard
gate (tested in ari-core) turns into a ``claim_evidence_missing`` block when a
declared claim is wholly unsupported by the emitted measurements.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server import (  # noqa: E402
    _CLAIMS_EXTRACT_SYS,
    _llm_extract_claims,
    _normalize_claims,
    _load_idea_claims_source,
    _resolve_falsifiable_claims,
    _tool_make_metric_spec,
)


class _Msg:
    def __init__(self, c): self.content = c


class _Choice:
    def __init__(self, c): self.message = _Msg(c)


class _Resp:
    def __init__(self, c): self.choices = [_Choice(c)]


def test_normalize_claims_coerces_and_drops_malformed():
    raw = {"claims": [
        {"claim": "A helps", "required_evidence": ["a_on", "a_off"]},
        {"claim": "no evidence", "required_evidence": []},   # dropped (nothing checkable)
        {"required_evidence": ["x"]},                         # dropped (no claim text)
        "garbage",                                            # dropped
        {"claim": "B", "required_evidence": ["b1", " "]},     # blank evidence stripped
    ]}
    assert _normalize_claims(raw) == [
        {"claim": "A helps", "required_evidence": ["a_on", "a_off"]},
        {"claim": "B", "required_evidence": ["b1"]},
    ]


def test_normalize_claims_accepts_bare_list_and_empties():
    assert _normalize_claims([{"claim": "C", "required_evidence": ["c"]}]) == \
        [{"claim": "C", "required_evidence": ["c"]}]
    assert _normalize_claims({}) == []
    assert _normalize_claims(None) == []
    assert _normalize_claims({"claims": "nope"}) == []


def test_load_idea_claims_source_structured(tmp_path):
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "M helps", "required_evidence": ["m_on", "m_off"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    structured, plan = _load_idea_claims_source(str(tmp_path))
    assert plan == ""
    assert structured == [{"claim": "M helps", "required_evidence": ["m_on", "m_off"]}]


def test_load_idea_claims_source_plan_fallback(tmp_path):
    idea = {"ideas": [{"experiment_plan": "## 9) success\n- M improves throughput"}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    structured, plan = _load_idea_claims_source(str(tmp_path))
    assert structured is None
    assert "M improves throughput" in plan


def test_load_idea_claims_source_absent(tmp_path):
    assert _load_idea_claims_source(str(tmp_path)) == (None, "")
    assert _load_idea_claims_source("") == (None, "")


def test_resolve_uses_structured_without_llm(tmp_path):
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "M helps", "required_evidence": ["m_on", "m_off"]},
        {"claim": "bad", "required_evidence": []}]}]}  # dropped by normalize
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    out = asyncio.run(_resolve_falsifiable_claims(str(tmp_path)))
    assert out == [{"claim": "M helps", "required_evidence": ["m_on", "m_off"]}]


def test_make_metric_spec_attaches_structured_claims(tmp_path, monkeypatch):
    # End-to-end (deterministic, no network): the idea's structured
    # falsifiable_claims attach to the contract even though primary_metric is absent
    # and the metric concept does not classify (claims are decoupled from concept).
    async def _fake_extract(_desc):
        return {}
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_extract)
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "page-shaping helps", "required_evidence": ["thp_on", "thp_off"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    text = "Title\n\nMetrics: GFLOP_per_s\n"
    spec = asyncio.run(_tool_make_metric_spec(
        {"experiment_text": text, "checkpoint_dir": str(tmp_path)}))
    mc = spec["metric_contract"]
    assert mc is not None
    assert mc["claims"] == [{"claim": "page-shaping helps", "required_evidence": ["thp_on", "thp_off"]}]


def test_make_metric_spec_persists_contract_file(tmp_path, monkeypatch):
    # The persist half of the integration seam: make_metric_spec must WRITE
    # {checkpoint}/metric_contract.json so the paper pipeline can graft it onto
    # science_data for the gate (without this the declared contract is inert).
    async def _fake_extract(_desc):
        return {}
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_extract)
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "X helps", "required_evidence": ["x_on", "x_off"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    asyncio.run(_tool_make_metric_spec(
        {"experiment_text": "Metrics: GFLOP_per_s\n", "checkpoint_dir": str(tmp_path)}))
    persisted = tmp_path / "metric_contract.json"
    assert persisted.is_file()
    obj = json.loads(persisted.read_text())
    assert obj["claims"] == [{"claim": "X helps", "required_evidence": ["x_on", "x_off"]}]


# ── LLM-extraction path (deterministic via monkeypatch — no network) ──────────

def test_claims_extract_prompt_is_domain_neutral():
    # HARD CONSTRAINT: the extraction prompt itself must not leak domain vocabulary
    # (it shapes the required_evidence names the gate then keys on). Mirrors the
    # obligation domain-neutrality guard, but for the EXTRACTOR prompt.
    sys_l = _CLAIMS_EXTRACT_SYS.lower()
    for banned in ("roofline", "gflop", "flop/s", "bandwidth", "cache", "dram",
                   "stream", "arithmetic intensity"):
        assert banned not in sys_l, banned


def test_llm_extract_claims_parses_wrapped_json(monkeypatch):
    async def _fake(**_kw):
        return _Resp('here are the claims: {"claims":[{"claim":"A helps",'
                     '"required_evidence":["a_on","a_off"]}]} done')
    monkeypatch.setattr("litellm.acompletion", _fake)
    out = asyncio.run(_llm_extract_claims("some plan with success criteria"))
    assert out == [{"claim": "A helps", "required_evidence": ["a_on", "a_off"]}]


def test_llm_extract_claims_degrades_on_bad_response(monkeypatch):
    async def _no_json(**_kw):
        return _Resp("no json here at all")
    monkeypatch.setattr("litellm.acompletion", _no_json)
    assert asyncio.run(_llm_extract_claims("plan")) == []

    async def _boom(**_kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("litellm.acompletion", _boom)
    assert asyncio.run(_llm_extract_claims("plan")) == []


def test_resolve_routes_to_llm_on_plan_fallback(tmp_path, monkeypatch):
    # structured absent + plan present => _resolve must route through extraction.
    called = {}

    async def _spy(plan):
        called["plan"] = plan
        return [{"claim": "from_llm", "required_evidence": ["e1"]}]
    monkeypatch.setattr("src.server._llm_extract_claims", _spy)
    idea = {"ideas": [{"experiment_plan": "## 9 success\n- M improves throughput"}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    out = asyncio.run(_resolve_falsifiable_claims(str(tmp_path)))
    assert "M improves throughput" in called.get("plan", "")
    assert out == [{"claim": "from_llm", "required_evidence": ["e1"]}]
