"""Agent-as-judge draft scoring — paper-archive Task 03 §5.8 Residual.

Covers the real-LLM ``reviewer_score_fn`` seam ``cli/projects.py`` injects when
``rqgm.paper.reviewer.agent_as_judge.enabled``: it (a) reads the venue rubric
axes a deterministic reader cannot (novelty/significance) and so DISCRIMINATES
between two mature drafts the LLM-free rubric would tie at the ceiling; (b)
threads the ACTIVE reviewer prompt as the emphasis so an evolved reviewer scores
differently; and (c) is FAIL-OPEN — any LLM error, empty reply, or unparseable
score degrades to the deterministic rubric, never a fabricated constant.

No test calls a real LLM: the client is a scripted double.
"""

from __future__ import annotations

import json

from ari.config import ARIConfig, apply_paper_env_overrides
from ari.rqgm.paper_judge import (
    build_agent_as_judge_score_fn,
    deterministic_rubric_score_fn,
)


# ── scripted LLM double ──────────────────────────────────────────────────────

class _Resp:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class ScriptedJudgeLLM:
    """Returns a fixed reply per call; records the messages it saw."""

    def __init__(self, reply):
        self._reply = reply
        self.calls = []

    def complete(self, messages, require_tool=True, phase=None, **kw):
        self.calls.append({"messages": messages, "phase": phase, "kw": kw})
        if isinstance(self._reply, Exception):
            raise self._reply
        return _Resp(self._reply)


_MATURE = (
    "\\documentclass{article}\\begin{document}\n"
    + "\\section{Intro}\n% CLAIM:C1:NC1\n" * 6
    + ("x" * 9000)
    + "\n\\end{document}"
)
_OTHER_MATURE = _MATURE.replace("Intro", "Method")   # equally saturating


def _axis_reply(**scores) -> str:
    return json.dumps({"axis_scores": scores})


#: A reply covering enough of the venue rubric's weight to clear
#: `_MIN_AXIS_COVERAGE` (the five 0.2-weight axes are the bulk of it).
_FULL = {
    "measurement_validity": 0.7, "comparative_rigor": 0.7, "novelty": 0.7,
    "reproducibility": 0.7, "clarity_of_contribution": 0.7,
}


# ── discrimination: the whole point of the judge ─────────────────────────────

def test_judge_discriminates_where_deterministic_rubric_ties():
    """Two mature drafts BOTH saturate the deterministic rubric — it cannot
    tell them apart. The judge, reading novelty/significance, gives them
    DIFFERENT scores."""
    det = deterministic_rubric_score_fn()
    d1 = det("", _MATURE)
    d2 = det("", _OTHER_MATURE)
    assert d1 == d2                       # the ceiling: deterministic path ties

    # judge returns a HIGH-novelty verdict for draft 1, LOW for draft 2
    llm_hi = ScriptedJudgeLLM(_axis_reply(
        novelty=0.9, significance=0.9, measurement_validity=0.9,
        comparative_rigor=0.9, reproducibility=0.9, clarity_of_contribution=0.9,
    ))
    llm_lo = ScriptedJudgeLLM(_axis_reply(
        novelty=0.2, significance=0.2, measurement_validity=0.9,
        comparative_rigor=0.9, reproducibility=0.9, clarity_of_contribution=0.9,
    ))
    s_hi = build_agent_as_judge_score_fn(llm_hi)("", _MATURE)
    s_lo = build_agent_as_judge_score_fn(llm_lo)("", _OTHER_MATURE)
    assert 0.0 <= s_lo < s_hi <= 1.0      # the ceiling is broken


def test_active_reviewer_prompt_reaches_the_judge():
    """The reviewer's active prompt bytes are threaded into the judge prompt as
    the emphasis instruction — so co-evolving the reviewer can move the score."""
    llm = ScriptedJudgeLLM(_axis_reply(novelty=0.5))
    build_agent_as_judge_score_fn(llm)("EMPHASISE NOVELTY ABOVE ALL", _MATURE)
    user_msg = llm.calls[0]["messages"][-1]["content"]
    assert "EMPHASISE NOVELTY ABOVE ALL" in user_msg
    assert llm.calls[0]["phase"] == "paper_judge"


# ── fail-open: never a fabricated constant ───────────────────────────────────

def test_llm_error_falls_back_to_deterministic_rubric():
    llm = ScriptedJudgeLLM(RuntimeError("529 overloaded"))
    det = deterministic_rubric_score_fn()
    fn = build_agent_as_judge_score_fn(llm)
    assert fn("", _MATURE) == det("", _MATURE)


def test_unparseable_reply_falls_back():
    llm = ScriptedJudgeLLM("Sure! The paper is quite good, I'd say a 9/10.")
    det = deterministic_rubric_score_fn()
    fn = build_agent_as_judge_score_fn(llm)
    assert fn("", _MATURE) == det("", _MATURE)


def test_reply_naming_no_rubric_axis_falls_back():
    llm = ScriptedJudgeLLM(json.dumps({"axis_scores": {"vibes": 0.99}}))
    det = deterministic_rubric_score_fn()
    fn = build_agent_as_judge_score_fn(llm)
    assert fn("", _MATURE) == det("", _MATURE)


def test_empty_draft_does_not_spend_an_llm_call():
    llm = ScriptedJudgeLLM(_axis_reply(novelty=0.9))
    fn = build_agent_as_judge_score_fn(llm)
    out = fn("", "   ")
    assert llm.calls == []                            # no LLM spend
    assert out == deterministic_rubric_score_fn()("", "   ")   # => rubric base


def test_custom_fallback_is_honoured():
    llm = ScriptedJudgeLLM(RuntimeError("down"))
    fn = build_agent_as_judge_score_fn(
        llm, fallback_score_fn=lambda p, t: 0.123456,
    )
    assert fn("", _MATURE) == 0.123456


# ── json fencing / flat object tolerance ─────────────────────────────────────

def test_fenced_and_flat_json_are_parsed():
    fenced = "```json\n" + _axis_reply(novelty=0.8, significance=0.8) + "\n```"
    llm = ScriptedJudgeLLM(fenced)
    assert 0.0 < build_agent_as_judge_score_fn(llm)("", _MATURE) <= 1.0
    # a flat {axis: score} object (no axis_scores wrapper) is tolerated too
    flat = ScriptedJudgeLLM(json.dumps({"novelty": 0.8, "significance": 0.8}))
    assert 0.0 < build_agent_as_judge_score_fn(flat)("", _MATURE) <= 1.0


# ── the evidence channel must actually carry evidence (audit 2026-07-19) ─────
#
# `cli/projects.py` passes the CLI's {goal, topic, file} dict, which has NONE of
# the keys the judge reads; and `PaperArchiveRuntime._build_experiment` stores
# those keys as PATHS (the paper skill resolves them server-side). Both routes
# left three of four whitelisted context fields structurally empty in EVERY
# production run, while the tests — which never passed experiment_data — could
# not see it. The judge now resolves content itself.

def test_evidence_is_read_from_the_checkpoint(tmp_path):
    (tmp_path / "verified_context.json").write_text('{"claims": ["C1 GROUNDED"]}')
    (tmp_path / "science_data.json").write_text('{"speedup": 3.14159}')
    (tmp_path / "related_refs.json").write_text('[{"title": "PRIOR WORK X"}]')
    llm = ScriptedJudgeLLM(_axis_reply(**_FULL))
    fn = build_agent_as_judge_score_fn(llm, checkpoint_dir=tmp_path)
    fn("", _MATURE)
    user = llm.calls[0]["messages"][-1]["content"]
    assert "C1 GROUNDED" in user          # verified_context reached the judge
    assert "3.14159" in user              # science_data reached the judge
    assert "PRIOR WORK X" in user         # reference_context reached the judge


def test_evidence_paths_in_experiment_data_are_resolved(tmp_path):
    """`_build_experiment` hands these over as PATH strings — the judge must
    READ them, not interpolate the path."""
    sd = tmp_path / "science_data.json"
    sd.write_text('{"throughput": 42424}')
    llm = ScriptedJudgeLLM(_axis_reply(**_FULL))
    fn = build_agent_as_judge_score_fn(
        llm, experiment_data={"science_data_json": str(sd)},
    )
    fn("", _MATURE)
    user = llm.calls[0]["messages"][-1]["content"]
    assert "42424" in user                # content, ...
    assert str(sd) not in user            # ... not the path


def test_missing_evidence_is_announced_not_silent(tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        build_agent_as_judge_score_fn(ScriptedJudgeLLM("{}"),
                                      checkpoint_dir=tmp_path)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("no content for" in m for m in msgs), msgs
    assert any("verified_context" in m and "science_data" in m for m in msgs)


# ── fabricated / non-finite score defences (audit 2026-07-19) ────────────────

def test_nan_from_the_llm_does_not_become_a_score():
    """`json.loads` accepts a bare NaN literal and NaN survives naive clamping
    (both comparisons False), silently defeating every downstream comparison."""
    llm = ScriptedJudgeLLM('{"axis_scores": {"novelty": NaN}}')
    det = deterministic_rubric_score_fn()
    out = build_agent_as_judge_score_fn(llm)("", _MATURE)
    assert out == out                                   # not NaN
    assert out == det("", _MATURE)                      # fell back


def test_one_axis_is_not_reported_as_a_full_rubric_score():
    """A reply naming a single low-weight axis must NOT be combined into a
    confident-looking score that best-belief consumes as a rubric verdict."""
    llm = ScriptedJudgeLLM(_axis_reply(clarity=1.0))     # 1 of 13 axes
    det = deterministic_rubric_score_fn()
    assert build_agent_as_judge_score_fn(llm)("", _MATURE) == det("", _MATURE)


# ── provenance: a judge score and a fallback are the same float ──────────────

def test_provenance_counters_distinguish_judged_from_degraded():
    good = ScriptedJudgeLLM(_axis_reply(**_FULL))
    fn = build_agent_as_judge_score_fn(good)
    fn("", _MATURE)
    assert (fn.judged, fn.degraded) == (1, 0)
    assert fn.last_source == "judge"

    bad = ScriptedJudgeLLM(RuntimeError("down"))
    fn2 = build_agent_as_judge_score_fn(bad)
    fn2("", _MATURE)
    assert (fn2.judged, fn2.degraded) == (0, 1)
    assert fn2.last_source == "rubric:llm_error"


def test_max_tokens_is_forwarded_to_the_llm():
    """The knob is documented as the judge's cost control — it must be read."""
    llm = ScriptedJudgeLLM(_axis_reply(**_FULL))
    build_agent_as_judge_score_fn(llm, max_tokens=256)("", _MATURE)
    assert llm.calls[0]["kw"].get("max_tokens") == 256


def test_judge_call_matches_the_REAL_LLMClient_signature():
    """Close the mock-fidelity gap the 2026-07-19 audit flagged.

    ``ScriptedJudgeLLM.complete`` swallows ``**kw``, so a kwarg the REAL
    ``LLMClient.complete`` does not accept would pass here and TypeError in
    production — where the judge's blanket ``except`` would swallow it and
    degrade EVERY draft to the rubric, silently. Bind the judge's actual call
    against the real signature instead of trusting the double."""
    import inspect

    from ari.llm.client import LLMClient

    sig = inspect.signature(LLMClient.complete)
    llm = ScriptedJudgeLLM(_axis_reply(**_FULL))
    build_agent_as_judge_score_fn(llm, max_tokens=256)("", _MATURE)
    call = llm.calls[0]
    # every kwarg the judge sends must bind to the real client
    sig.bind(None, call["messages"], require_tool=False,
             phase=call["phase"], **call["kw"])


# ── config: opt-in, env override ─────────────────────────────────────────────

def test_agent_as_judge_defaults_off():
    cfg = ARIConfig()
    assert cfg.rqgm.paper.reviewer.agent_as_judge.enabled is False


def test_env_override_flips_agent_as_judge(monkeypatch):
    cfg = ARIConfig()
    monkeypatch.setenv("ARI_PAPER_AGENT_AS_JUDGE", "true")
    apply_paper_env_overrides(cfg)
    assert cfg.rqgm.paper.reviewer.agent_as_judge.enabled is True
    monkeypatch.setenv("ARI_PAPER_AGENT_AS_JUDGE", "0")
    apply_paper_env_overrides(cfg)
    assert cfg.rqgm.paper.reviewer.agent_as_judge.enabled is False
