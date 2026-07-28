"""Paper-candidate RQGM escalation + bundle pre-signals + paper_writer view.

Covers the three plan-specified paper-phase hooks:

* ITEM 1 — the ``paper_candidate`` producer: ``ari paper`` pre-flight
  escalates the best node (verified_context ranking) through the EXISTING
  per-node machinery — one paper-candidate adversarial round + the L3
  ladder, with ValidatedAttackRecords flowing to the AdversarialReplayPool
  (docs/plans/ari_rqgm 03 trigger table / 06 §5.5 / 12 §5.2).
* ITEM 2 — ``build_artifact_bundle`` populated from real checkpoint
  artifacts (claim-gate findings, related_refs, verified_context) so the
  paper adversaries fire on real pre-signals (plan 06 §5.2).
* ITEM 3 — the ``paper_writer`` context view + kernel whitelist
  (plan 12 §5.4/§5.7), constitution-pinned.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ari.config import ARIConfig
from ari.rqgm.adversarial.engine import build_artifact_bundle
from ari.rqgm.adversarial.pool import (
    AdversarialCaseLog,
    AdversarialReplayPool,
    ADVERSARIAL_CASES_FILENAME,
    REPLAY_POOL_SNAPSHOT_FILENAME,
)
from ari.rqgm.runtime import RQGMRuntime


# ── deterministic actor-routing LLM (mirrors test_rqgm_adversarial) ─────────


class _ScriptedLLM:
    def __init__(self, adversary_reply, defender_reply, judge_reply) -> None:
        self._adv = adversary_reply
        self._def = defender_reply
        self._jdg = judge_reply
        self.calls: list = []

    def complete(self, messages, require_tool=True, **kwargs):
        prompt = messages[0]["content"]
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        if "ArtifactJudge" in prompt:
            reply = self._jdg
        elif "artifact Defender" in prompt:
            reply = self._def
        elif "Adversary" in prompt:
            reply = self._adv
        else:  # pragma: no cover - unexpected routing
            reply = ""
        return SimpleNamespace(content=reply)


_ADV = json.dumps({
    "attack_claim": "Conclusion claims 'first ever'; evidence is thinner.",
    "severity_claimed": "high",
    "confidence": 0.8,
})
_DEF = json.dumps({"stance": "rebut", "rebuttal_text": "grounded", "confidence": 0.5})
_JUDGE_VALID = json.dumps({"verdict": "valid", "severity": "high", "rationale": "ok"})


def _node(node_id="node_best", score=0.8, parent_id=None):
    # "first ever" fires the deterministic novelty signal → overclaim.
    return SimpleNamespace(
        id=node_id,
        metrics={"_scientific_score": score},
        plan="We present the first ever fused kernel.",
        eval_summary="A first ever result.",
        work_dir="",
        parent_id=parent_id,
    )


def _seed_paper_artifacts(ckpt):
    """Write the paper-phase pre-signal artifacts ITEM 2 reads."""
    (ckpt / "evaluation").mkdir(parents=True, exist_ok=True)
    (ckpt / "evaluation" / "claim_evidence_hard_gate_final.json").write_text(
        json.dumps({
            "gate": "claim_evidence_hard_gate", "phase": "final",
            "errors": [
                {"claim_id": "C3", "type": "missing_evidence"},
                {"claim_id": "C4", "numeric_id": "n1", "type": "numeric_mismatch"},
            ],
            "warnings": [
                {"type": "uncovered_numeric", "section": "results"},
            ],
        })
    )
    (ckpt / "related_refs.json").write_text(
        json.dumps({"refs": [{"id": "ref12", "title": "A prior fused kernel"}]})
    )
    (ckpt / "verified_context.json").write_text(
        json.dumps({
            "best_node_id": "node_best", "lineage": ["node_best"],
            "claims": [], "usable_for_claims": [],
            "limitations": [{"claim_id": "C3", "note": "no grounding"}],
        })
    )


def _rqgm_runtime(ckpt, llm=None):
    cfg = ARIConfig(
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True,
              "adversarial": {"types": ["overclaim"], "sample_mod": 0}},
    )
    return RQGMRuntime(cfg, checkpoint_dir=ckpt, llm=llm)


# ── ITEM 2: bundle populated from real artifacts (pre-signals non-empty) ────


def test_bundle_populated_from_real_paper_artifacts(tmp_path):
    _seed_paper_artifacts(tmp_path)
    bundle = build_artifact_bundle(_node(), tmp_path)
    kinds = {f["kind"] for f in bundle.gate_findings}
    # Claim-gate + verified-context gaps become real pre-signals.
    assert "missing_evidence" in kinds       # overclaim + evidence_gap
    assert "numeric_mismatch" in kinds       # metric_gaming derives a flag
    assert "uncovered_numeric" in kinds      # evidence_gap
    assert bundle.related_refs                # prior_art source
    assert "numeric_mismatch" in bundle.validate_metrics_flags


def test_bundle_pre_signals_fire_on_real_signals(tmp_path):
    from ari.rqgm.adversarial.engine import (
        _pre_evidence_gap, _pre_metric_gaming, _pre_overclaim, _pre_prior_art,
    )
    _seed_paper_artifacts(tmp_path)
    bundle = build_artifact_bundle(_node(), tmp_path)
    assert _pre_overclaim(bundle)       # claim-gate missing_evidence
    assert _pre_evidence_gap(bundle)    # missing_evidence / uncovered_numeric
    assert _pre_metric_gaming(bundle)   # numeric_mismatch flag
    assert _pre_prior_art(bundle)       # related_refs + novelty signal


def test_bundle_reproducibility_signal_from_normalized_commands(tmp_path):
    from ari.rqgm.adversarial.engine import _pre_reproducibility
    wd = tmp_path / "wd"
    wd.mkdir()
    # node_report carries the builder's SINGULAR command keys; the bundle
    # bridges them to the plural lists the reproducibility pre-signal scans.
    (wd / "node_report.json").write_text(json.dumps({
        "node_id": "node_best",
        "run_command": "python run.py --data /home/alice/private/set",
        "build_command": "make",
    }))
    node = _node()
    node.work_dir = str(wd)
    bundle = build_artifact_bundle(node, tmp_path)
    assert bundle.node_report["run_commands"] == [
        "python run.py --data /home/alice/private/set"
    ]
    assert _pre_reproducibility(bundle)  # host-local path in the run command


# ── ITEM 1: paper pre-flight escalation (round + L3 + pool) ─────────────────


def test_paper_candidate_escalation_runs_round_and_admits_to_pool(tmp_path):
    from ari.rqgm.budget import GOVERNANCE_LEVEL_EVENT, LEVEL_ADJUDICATED
    from ari.rqgm.store import ImmutableAuditLog

    _seed_paper_artifacts(tmp_path)
    llm = _ScriptedLLM(_ADV, _DEF, _JUDGE_VALID)
    runtime = _rqgm_runtime(tmp_path, llm=llm)
    best = _node()

    summary = runtime.run_paper_candidate_escalation(best, all_nodes=[best])

    # ONE round ran with at least one validated attack.
    assert summary is not None
    assert summary["attacks"] >= 1
    assert summary["validated"] >= 1

    # should_attack saw paper_candidate=True → the L3 ladder recorded it.
    levels = [
        line for line in ImmutableAuditLog.read(tmp_path)
        if line.get("event_type") == GOVERNANCE_LEVEL_EVENT
    ]
    assert levels, "no governance_level event was recorded"
    paper_level = next(
        (l for l in levels
         if "paper_candidate" in (l.get("payload") or {}).get("triggers", [])),
        None,
    )
    assert paper_level is not None
    assert paper_level["payload"]["level"] == LEVEL_ADJUDICATED

    # The validated paper-claim attack landed in the AdversarialReplayPool.
    cases = runtime.adversarial_pool.cases()
    assert len(cases) == 1
    assert cases[0]["case_type"] == "overclaim"
    # …and the raw attack targeted a paper_claim artifact (the overclaim
    # adversary's default target class).
    raw = [
        line for line in AdversarialCaseLog.read(tmp_path)
        if line.get("record_type") == "raw_attack"
    ]
    assert raw and raw[0]["target_artifact"]["type"] == "paper_claim"

    # The pool snapshot is on disk and reloads with the same case.
    reloaded = AdversarialReplayPool.load(
        tmp_path,
        getattr(runtime.cfg.rqgm, "adversarial", None),
    )
    assert [c["case_id"] for c in reloaded.cases()] == [cases[0]["case_id"]]


def test_paper_candidate_escalation_is_idempotent_across_reruns(tmp_path):
    _seed_paper_artifacts(tmp_path)
    llm = _ScriptedLLM(_ADV, _DEF, _JUDGE_VALID)
    runtime = _rqgm_runtime(tmp_path, llm=llm)
    best = _node()

    first = runtime.run_paper_candidate_escalation(best, all_nodes=[best])
    assert first is not None and first["validated"] >= 1

    # A fresh runtime over the same checkpoint (simulated ``ari paper`` re-run):
    # the per-node round marker suppresses a second round and pool dedup keeps
    # the case count stable.
    runtime2 = _rqgm_runtime(tmp_path, llm=llm)
    second = runtime2.run_paper_candidate_escalation(best, all_nodes=[best])
    assert second is None  # round marker honored
    assert len(runtime2.adversarial_pool.cases()) == 1


# ── (c) fail-open: missing artifacts → empty pre-signals, no crash ──────────


def test_escalation_fail_open_with_missing_artifacts(tmp_path):
    # No paper artifacts seeded and no LLM: the bundle degrades to empty
    # pre-signals, the round runs zero attacks, nothing crashes.
    bundle = build_artifact_bundle(_node(), tmp_path)
    assert bundle.gate_findings == ()
    assert bundle.related_refs == ()
    assert bundle.validate_metrics_flags == ()

    runtime = _rqgm_runtime(tmp_path, llm=None)
    best = _node()
    summary = runtime.run_paper_candidate_escalation(best, all_nodes=[best])
    # The round is triggered (paper_candidate) but produces no attacks
    # (no LLM), and the pool stays empty — never a crash.
    assert summary == {"node_id": "node_best", "attacks": 0, "validated": 0,
                       "penalty": 0.0}
    assert runtime.adversarial_pool.cases() == []


def test_escalation_none_best_node_is_a_noop(tmp_path):
    runtime = _rqgm_runtime(tmp_path, llm=None)
    assert runtime.run_paper_candidate_escalation(None) is None


# ── (b) non-RQGM paper run: no adversarial round, no RQGM files ─────────────


def test_non_rqgm_paper_run_writes_no_rqgm_files(tmp_path):
    # simple_bfts build_runtime never constructs an RQGMRuntime, so the paper
    # command's escalation branch (getattr(bfts, "rqgm", None)) is a dead
    # branch — no adversarial round, no RQGM files.
    from ari.core import build_runtime

    cfg = ARIConfig(llm={"model": "fake"})
    _, _, _mcp, bfts, _agent, _ = build_runtime(
        cfg, "goal", checkpoint_dir=tmp_path
    )
    assert getattr(bfts, "rqgm", None) is None
    names = sorted(p.name for p in tmp_path.rglob("*"))
    assert ADVERSARIAL_CASES_FILENAME not in names
    assert REPLAY_POOL_SNAPSHOT_FILENAME not in names


# ── ITEM 3: paper_writer context view + kernel whitelist ────────────────────


def test_paper_writer_view_accepts_whitelisted_fields_rejects_foreign():
    from ari.rqgm.context_views import (
        PAPER_WRITER_FIELDS, build_paper_writer_context,
    )
    from ari.rqgm.kernel import ConstitutionalKernel

    assert PAPER_WRITER_FIELDS == frozenset({
        "verified_context", "science_data", "claim_registry",
    })
    view = build_paper_writer_context(
        {"best_node_id": "n1", "claims": []},
        {"configurations": []},
        {"claims": {"C1": "supported"}},
    )
    assert set(view) == PAPER_WRITER_FIELDS

    kernel = ConstitutionalKernel()
    ok = kernel.validate_context_scope("paper_writer", view)
    assert not ok.blocking
    assert ok.violations == ()

    # A foreign field (e.g. a raw transcript) is flagged (warn-and-flag).
    leaked = dict(view)
    leaked["raw_transcript"] = "…"
    bad = kernel.validate_context_scope("paper_writer", leaked)
    assert [v.code for v in bad.violations] == ["CK-CTX-001"]
    assert not bad.blocking  # context-scope never blocks (plan 04 §5.5)


# ── (e) constitution hash re-pin verified ──────────────────────────────────


def test_constitution_hash_repinned_for_paper_writer():
    from ari.rqgm import kernel_rules

    assert "paper_writer" in kernel_rules.CONTEXT_VIEW_WHITELISTS
    # The amendment changed the pinned hash; the value is the one the kernel
    # test pins (single source — recompute must match the module constant).
    # Re-pinned 2026-07-16 by the Task 14 amendment (plan 14 §5.2/§5.6): this
    # assertion imports the kernel suite's pin rather than re-spelling the
    # literal, so a future amendment re-pins in ONE place.
    from tests.test_rqgm_kernel import _EXPECTED_CONSTITUTION_HASH

    assert kernel_rules.CONSTITUTION_HASH == kernel_rules.constitution_hash()
    assert kernel_rules.CONSTITUTION_HASH == _EXPECTED_CONSTITUTION_HASH


def test_paper_writer_is_now_a_full_evolvable_role():
    # Constitutional amendment (plan ari_rqgm_paper/03 §5.2): the 2026-07-15
    # "context-scope role only" decision is SUPERSEDED — the governed writer
    # prompt now lives in ari-core and drives the ungoverned skill, so
    # paper_writer is PROMOTED to a full evolvable role (capability-matrix
    # institutional + meta), and paper_reviewer is added likewise. Neither may
    # write the registry or activate candidates.
    from ari.rqgm import kernel_rules
    from ari.rqgm.events import EVOLVABLE_ROLES

    for role in ("paper_writer", "paper_reviewer"):
        assert role in EVOLVABLE_ROLES
        assert (role, "institutional") in kernel_rules.CAPABILITY_MATRIX
        assert (role, "meta") in kernel_rules.CAPABILITY_MATRIX
        caps = kernel_rules.CAPABILITY_MATRIX[(role, "institutional")]
        assert ("write", "registry") not in caps
        assert ("activate", "candidates") not in caps
