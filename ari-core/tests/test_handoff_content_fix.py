"""Handoff channels must carry real payload (handoff study).

Guards two fixes that made the agent-face channels non-degenerate:
  (a) node_summary_view surfaces the node's actionable ``outcome`` (the
      self-assessment headline / eval reason), which the deterministic evaluator
      DOES populate but which was absent from ALL_FIELDS — so the summary used to
      collapse to score+filenames.
  (b) _load_parent_log falls back to the parent's tree.json ``trace_log`` when no
      run.log files exist (the BFTS/deterministic case), so code_plus_full_log is
      not silently empty (== code_only).
"""
import json

from ari.orchestrator.node_summary_view import ALL_FIELDS, node_summary_view


def _report(**kw):
    base = {
        "node_id": "node_abc12345", "label": "improve",
        "self_assessment": {"succeeded": True,
                            "headline": "edge-cut 327 vs random 3978, imbalance 1.048 (scientific_score=0.95)"},
        "metrics": {"_scientific_score": 0.95, "valid_geomean_speedup": 0.95},
        "files_changed": {"modified": [{"path": "candidate_meshpart.c"}]},
    }
    base.update(kw)
    return base


def test_outcome_is_in_all_fields_and_default():
    assert "outcome" in ALL_FIELDS


def test_summary_surfaces_actionable_outcome():
    v = node_summary_view(_report(), fields_enabled=None)
    assert "outcome:" in v
    assert "edge-cut 327" in v          # the actionable diagnostic reaches the child


def test_outcome_falls_back_to_eval_summary():
    rep = _report(self_assessment={"succeeded": True, "headline": ""},
                  eval_summary="speedup 60x correct")
    v = node_summary_view(rep, fields_enabled=None)
    assert "outcome: speedup 60x correct" in v


def test_outcome_ablatable():
    # RQ-B ablation: dropping outcome removes it but keeps the rest.
    v = node_summary_view(_report(), fields_enabled=[f for f in ALL_FIELDS if f != "outcome"])
    assert "outcome:" not in v and "key_metrics:" in v


def test_full_log_falls_back_to_tree_trace_log(tmp_path, monkeypatch):
    from ari.agent.loop import _load_parent_log
    # layout: <run>/<parent> and <run>/<child>; tree.json under ARI_CHECKPOINT_DIR
    run = tmp_path / "experiments" / "run1"
    (run / "node_parent").mkdir(parents=True)
    (run / "node_child").mkdir(parents=True)
    ck = tmp_path / "checkpoints" / "run1"
    ck.mkdir(parents=True)
    (ck / "tree.json").write_text(json.dumps({"nodes": [
        {"id": "node_parent", "trace_log": ["→ write_code(candidate.c)", "  ← {compiled}", "selftest: cut=327"]},
    ]}))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ck))

    class N:
        parent_id = "node_parent"
    log = _load_parent_log(N(), str(run / "node_child"))
    assert "trace_log" in log and "cut=327" in log and "write_code" in log


def test_full_log_empty_when_no_source(tmp_path, monkeypatch):
    from ari.agent.loop import _load_parent_log
    run = tmp_path / "experiments" / "run2"
    (run / "node_child").mkdir(parents=True)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)

    class N:
        parent_id = "node_missing"
    assert _load_parent_log(N(), str(run / "node_child")) == ""
