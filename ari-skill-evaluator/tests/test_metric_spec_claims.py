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
    _load_prompt,
    _llm_extract_claims,
    _llm_extract_contract_flags,
    _normalize_claims,
    _load_idea_claims_source,
    _load_idea_plan_text,
    _resolve_contract_flags,
    _resolve_falsifiable_claims,
    _tool_make_metric_spec,
)

# Subtask 040: these two judge prompts were externalized to src/prompts/*.md and
# are now loaded via the skill-local loader; the rendered text is byte-identical
# to the former inline constants, so the content assertions below are unchanged.
_CLAIMS_EXTRACT_SYS = _load_prompt("claims_extract_sys")
_CONTRACT_FLAGS_SYS = _load_prompt("contract_flags_sys")


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
        {"claim": "B", "required_evidence": ["b_metric", " "]},  # blank evidence stripped
    ]}
    assert _normalize_claims(raw) == [
        {"claim": "A helps", "required_evidence": ["a_on", "a_off"]},
        {"claim": "B", "required_evidence": ["b_metric"]},
    ]


def test_normalize_claims_drops_bare_generic_evidence_names():
    # R1 false-coverage guard (P2a): a claim whose evidence list contains generic
    # tokens (k / matrix_id / mode_id ...) would be "covered" by ANY run that emits
    # such a name; generics are stripped, and a claim left with none is dropped.
    raw = {"claims": [
        {"claim": "M1 reduces branch misses vs M0",
         "required_evidence": ["mode_id", "branch_misses_per_kilo_instr", "matrix_id", "k"]},
        {"claim": "only generics", "required_evidence": ["k", "mode_id"]},
    ]}
    out = _normalize_claims(raw)
    assert out == [{"claim": "M1 reduces branch misses vs M0",
                    "required_evidence": ["branch_misses_per_kilo_instr"]}]


def test_claims_extract_prompt_demands_distinctive_userspace_names():
    s = _CLAIMS_EXTRACT_SYS
    assert "DISTINCTIVE" in s and "generic" in s          # naming rule stated
    assert "USERSPACE" in s and "privileged" in s         # feasibility rule stated


def test_normalize_claims_accepts_bare_list_and_empties():
    assert _normalize_claims([{"claim": "C", "required_evidence": ["c_val"]}]) == \
        [{"claim": "C", "required_evidence": ["c_val"]}]
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
    # obligation domain-neutrality guard, but for the EXTRACTOR prompt. "speedup" /
    # "throughput" were perf-flavoured examples removed on user instruction — a
    # seeded example self-fulfillingly biases the extracted evidence names.
    sys_l = _CLAIMS_EXTRACT_SYS.lower()
    for banned in ("roofline", "gflop", "flop/s", "bandwidth", "cache", "dram",
                   "stream", "arithmetic intensity", "speedup", "throughput",
                   "latency", "1.5x"):
        assert banned not in sys_l, banned


def test_llm_extract_claims_parses_wrapped_json(monkeypatch):
    async def _fake(**_kw):
        return _Resp('here are the claims: {"claims":[{"claim":"A helps",'
                     '"required_evidence":["a_on","a_off"]}]} done')
    monkeypatch.setattr("litellm.acompletion", _fake)
    out = asyncio.run(_llm_extract_claims("some plan with success criteria"))
    assert out == [{"claim": "A helps", "required_evidence": ["a_on", "a_off"]}]


def test_llm_extract_claims_token_budget_is_generous(monkeypatch):
    # regression: max_tokens=600 TRUNCATED the claims JSON mid-array on a real run
    # (finish_reason=length, ~8KB needed for 12 claims), the JSONDecodeError was
    # swallowed, and the contract silently carried claims=[] -- the plan-fidelity
    # gate never armed. Pin a generous floor.
    captured = {}

    async def _cap(**kw):
        captured.update(kw)
        return _Resp('{"claims":[]}')
    monkeypatch.setattr("litellm.acompletion", _cap)
    asyncio.run(_llm_extract_claims("plan"))
    assert captured["max_tokens"] >= 2048


def test_llm_extract_claims_degrades_on_bad_response(monkeypatch):
    async def _no_json(**_kw):
        return _Resp("no json here at all")
    monkeypatch.setattr("litellm.acompletion", _no_json)
    assert asyncio.run(_llm_extract_claims("plan")) == []

    async def _boom(**_kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("litellm.acompletion", _boom)
    assert asyncio.run(_llm_extract_claims("plan")) == []


# ── platform-capability note (P2c) ───────────────────────────────────────────

def test_load_platform_note_lists_unavailable_tools(tmp_path):
    from src.server import _load_platform_note
    (tmp_path / "platform_capabilities.json").write_text(json.dumps({
        "partition": "partA", "arch": "aarch64",
        "available": {"perf": False, "numactl": True}}))
    note = _load_platform_note(str(tmp_path))
    assert "UNAVAILABLE tools: perf" in note
    assert "numactl" in note                       # available listed too
    assert "partA" in note and "aarch64" in note   # provenance of the fact
    assert "Do NOT require" in note                # the instruction


def test_load_platform_note_absent_is_empty(tmp_path):
    from src.server import _load_platform_note
    assert _load_platform_note(str(tmp_path)) == ""      # no probe data
    assert _load_platform_note("") == ""


def test_claims_extraction_receives_platform_note(tmp_path, monkeypatch):
    # the note must reach the extraction LLM call's user content (claims are then
    # constrained to platform-measurable evidence).
    captured = {}

    async def _cap(**kw):
        captured.update(kw)
        return _Resp('{"claims":[]}')
    monkeypatch.setattr("litellm.acompletion", _cap)
    (tmp_path / "platform_capabilities.json").write_text(json.dumps({
        "partition": "partA", "available": {"perf": False}}))
    (tmp_path / "idea.json").write_text(json.dumps(
        {"ideas": [{"experiment_plan": "measure things and compare modes"}]}))
    asyncio.run(_resolve_falsifiable_claims(str(tmp_path)))
    user = next(m["content"] for m in captured["messages"] if m["role"] == "user")
    assert "UNAVAILABLE tools: perf" in user
    assert "Experiment plan:" in user


def test_resolve_routes_to_llm_on_plan_fallback(tmp_path, monkeypatch):
    # structured absent + plan present => _resolve must route through extraction.
    called = {}

    async def _spy(plan, platform_note=""):
        called["plan"] = plan
        return [{"claim": "from_llm", "required_evidence": ["e1"]}]
    monkeypatch.setattr("src.server._llm_extract_claims", _spy)
    idea = {"ideas": [{"experiment_plan": "## 9 success\n- M improves throughput"}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    out = asyncio.run(_resolve_falsifiable_claims(str(tmp_path)))
    assert "M improves throughput" in called.get("plan", "")
    assert out == [{"claim": "from_llm", "required_evidence": ["e1"]}]


# ── idea-owned requirement flags (G): resolution + extraction ─────────────────

_FALSE_FLAGS = {"correctness_required": False, "ceiling_must_be_measured": False}


def test_resolve_contract_flags_structured_is_false(tmp_path):
    idea = {"ideas": [{"falsifiable_claims": [{"claim": "x", "required_evidence": ["a"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    assert asyncio.run(_resolve_contract_flags(str(tmp_path))) == _FALSE_FLAGS


def test_resolve_contract_flags_absent_is_false(tmp_path):
    assert asyncio.run(_resolve_contract_flags(str(tmp_path))) == _FALSE_FLAGS


def test_resolve_contract_flags_routes_to_llm(tmp_path, monkeypatch):
    async def _spy(_plan):
        return {"correctness_required": True, "ceiling_must_be_measured": True}
    monkeypatch.setattr("src.server._llm_extract_contract_flags", _spy)
    (tmp_path / "idea.json").write_text(json.dumps(
        {"ideas": [{"experiment_plan": "kernel computes CSR SpMM, roofline-normalized"}]}))
    assert asyncio.run(_resolve_contract_flags(str(tmp_path))) == \
        {"correctness_required": True, "ceiling_must_be_measured": True}


def test_load_idea_plan_text_reads_regardless_of_claims(tmp_path):
    idea = {"ideas": [{"falsifiable_claims": [{"claim": "x", "required_evidence": ["a"]}],
                       "experiment_plan": "the kernel computes X, roofline-normalized"}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    assert "roofline-normalized" in _load_idea_plan_text(str(tmp_path))


def test_resolve_contract_flags_works_on_structured_path(tmp_path, monkeypatch):
    # finding-3 regression: an idea with BOTH structured claims AND a plan must STILL
    # resolve the flags (the structured short-circuit previously disabled them).
    async def _spy(_plan):
        return {"correctness_required": True, "ceiling_must_be_measured": True}
    monkeypatch.setattr("src.server._llm_extract_contract_flags", _spy)
    idea = {"ideas": [{"falsifiable_claims": [{"claim": "x", "required_evidence": ["a"]}],
                       "experiment_plan": "the kernel computes X"}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    assert asyncio.run(_resolve_contract_flags(str(tmp_path))) == \
        {"correctness_required": True, "ceiling_must_be_measured": True}


def test_contract_flags_prompt_is_domain_neutral():
    sys_l = _CONTRACT_FLAGS_SYS.lower()
    for banned in ("roofline", "gflop", "flop/s", "bandwidth", "cache", "dram", "stream"):
        assert banned not in sys_l, banned


def test_llm_extract_contract_flags_parses(monkeypatch):
    async def _fake(**_kw):
        return _Resp('verdict: {"correctness_required": true, "ceiling_must_be_measured": false}')
    monkeypatch.setattr("litellm.acompletion", _fake)
    assert asyncio.run(_llm_extract_contract_flags("plan")) == \
        {"correctness_required": True, "ceiling_must_be_measured": False}


def test_llm_extract_contract_flags_degrades(monkeypatch):
    async def _boom(**_kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("litellm.acompletion", _boom)
    assert asyncio.run(_llm_extract_contract_flags("plan")) == _FALSE_FLAGS


def test_make_metric_spec_sets_idea_owned_flags(tmp_path, monkeypatch):
    async def _flags(_ck):
        return {"correctness_required": True, "ceiling_must_be_measured": True}
    async def _no_claims(_ck):
        return []
    async def _fake_metric(_desc):
        return {}
    monkeypatch.setattr("src.server._resolve_contract_flags", _flags)
    monkeypatch.setattr("src.server._resolve_falsifiable_claims", _no_claims)
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_metric)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    spec = asyncio.run(_tool_make_metric_spec(
        {"experiment_text": "Metrics: GFLOP_per_s\n", "checkpoint_dir": str(tmp_path)}))
    mc = spec["metric_contract"]
    assert mc is not None
    assert mc["correctness_required"] is True and mc["ceiling_must_be_measured"] is True


def test_make_metric_spec_no_flags_when_idea_says_false(tmp_path, monkeypatch):
    async def _flags(_ck):
        return {"correctness_required": False, "ceiling_must_be_measured": False}
    async def _no_claims(_ck):
        return []
    async def _fake_metric(_desc):
        return {}
    monkeypatch.setattr("src.server._resolve_contract_flags", _flags)
    monkeypatch.setattr("src.server._resolve_falsifiable_claims", _no_claims)
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_metric)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    spec = asyncio.run(_tool_make_metric_spec(
        {"experiment_text": "Metrics: GFLOP_per_s\n", "checkpoint_dir": str(tmp_path)}))
    mc = spec["metric_contract"]
    if mc is not None:  # theory-safe: flags not stamped when the idea says false
        assert "correctness_required" not in mc
        assert "ceiling_must_be_measured" not in mc


def test_make_metric_spec_mint_once_returns_persisted_contract(tmp_path, monkeypatch):
    # FREEZE: a persisted claims-bearing contract must be returned VERBATIM on
    # re-calls — no re-extraction (LLM naming is not referentially stable; a
    # real run regenerated the vocabulary 3x and hid sibling evidence from the
    # exact-match gate).
    async def _fake_extract(_desc):
        return {}
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_extract)

    persisted = {"key": "GFLOP_per_s",
                 "claims": [{"claim": "first-mint claim",
                             "required_evidence": ["alpha_time_seconds"]}]}
    (tmp_path / "metric_contract.json").write_text(json.dumps(persisted))
    # an idea with DIFFERENT claims must NOT win over the frozen contract
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "regenerated claim", "required_evidence": ["beta_time_sec"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))

    async def _must_not_run(_ck):
        raise AssertionError("claims re-extraction ran despite a frozen contract")
    monkeypatch.setattr("src.server._resolve_falsifiable_claims", _must_not_run)

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    before = (tmp_path / "metric_contract.json").read_text()
    spec = asyncio.run(_tool_make_metric_spec(
        {"experiment_text": "Metrics: GFLOP_per_s\n", "checkpoint_dir": str(tmp_path)}))
    assert spec["contract_frozen"] is True
    assert spec["metric_contract"] == persisted
    assert (tmp_path / "metric_contract.json").read_text() == before  # not overwritten
    # per-node spec role still served (scoring guide is built per call)
    assert spec["scoring_guide"]


def test_make_metric_spec_empty_claims_contract_does_not_freeze(tmp_path, monkeypatch):
    # A persisted contract WITHOUT claims (e.g. scaffold-only) must not freeze:
    # the first claims-bearing mint is still allowed to happen.
    async def _fake_extract(_desc):
        return {}
    monkeypatch.setattr("src.server._llm_extract_metric_spec", _fake_extract)
    (tmp_path / "metric_contract.json").write_text(json.dumps({"key": "x", "claims": []}))
    idea = {"ideas": [{"falsifiable_claims": [
        {"claim": "real claim", "required_evidence": ["gamma_count"]}]}]}
    (tmp_path / "idea.json").write_text(json.dumps(idea))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    spec = asyncio.run(_tool_make_metric_spec(
        {"experiment_text": "Metrics: GFLOP_per_s\n", "checkpoint_dir": str(tmp_path)}))
    assert spec.get("contract_frozen") is not True
    assert spec["metric_contract"]["claims"][0]["claim"] == "real claim"
