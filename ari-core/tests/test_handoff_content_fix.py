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


def test_conclusion_never_rides_the_log_channel_via_trace_log_branch(tmp_path):
    """THE branch that actually runs in production. Measured on a real study:
    ``trace_log`` was non-empty on 31/31 nodes, so ``_render_parent_execution_log``
    takes the trace_log branch essentially always — an earlier guard that lived
    only in the messages branch was therefore dead code, and orthogonality held
    only by accident (trace_log is appended at the tool-execution site alone).

    trace_log also feeds the viz tree, so a future "show the node's conclusion in
    the tree" change is the realistic way the parent's CONCLUSION gets in here —
    at which point code_plus_full_log becomes a superset of code_plus_summary and
    the 2x2 factorial stops measuring what it claims. Pin it: no matter how the
    conclusion reaches the body, it does not reach the child.
    """
    from ari.agent.loop import _render_parent_execution_log
    pdir = tmp_path / "node_parent"
    pdir.mkdir()
    finish = json.dumps({
        "status": "success", "summary": "CONCLUSION_MARKER blocked GEMM ikj",
        "metrics": {"speedup": 41.5}, "next_steps": ["try AVX-512 intrinsics"],
    })
    (pdir / "full_log.json").write_text(json.dumps({
        # non-empty trace_log -> the LIVE branch; and someone has helpfully
        # appended the finish JSON to it (the future regression this guards).
        "trace_log": ["→ write_code(candidate.c)", "← written", f"finish: {finish}"],
        "messages": [
            {"role": "assistant", "content": "",
             "tool_calls": [{"name": "write_code", "arguments": "candidate.c"}]},
            {"role": "tool", "content": "written"},
            {"role": "assistant", "_finish": True, "content": finish},
        ],
    }))
    out = _render_parent_execution_log(pdir, 48_000)
    assert "write_code" in out                       # trajectory still carried
    assert "CONCLUSION_MARKER" not in out            # conclusion scrubbed
    assert "next_steps" not in out and "41.5" not in out


def test_parent_finish_json_never_rides_the_full_log_handoff(tmp_path):
    """ARM ORTHOGONALITY (load-bearing for the whole study): the parent's finish
    JSON is its CONCLUSION and is the payload of the *summary* channel (parent
    node_report). The *log* channel carries the raw trajectory only. If the
    conclusion leaked in here, code_plus_full_log would become a superset of
    code_plus_summary and the four arms would stop separating what they claim to.
    The finish JSON stays in the saved full_log.json for human/analysis readers.
    """
    from ari.agent.loop import _render_parent_execution_log
    pdir = tmp_path / "node_parent"
    pdir.mkdir()
    (pdir / "full_log.json").write_text(json.dumps({
        # no trace_log -> exercise the messages-reconstruction fallback
        "messages": [
            {"role": "system", "content": "you are an agent"},
            {"role": "user", "content": "the goal"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"name": "write_code", "arguments": "candidate.c"}]},
            {"role": "tool", "content": "written"},
            {"role": "assistant", "_finish": True, "content": json.dumps({
                "status": "success", "summary": "CONCLUSION_MARKER blocked GEMM",
                "metrics": {"speedup": 41.5}, "next_steps": ["try AVX-512"],
            })},
        ],
    }))
    out = _render_parent_execution_log(pdir, 48_000)
    assert "write_code" in out and "written" in out       # trajectory IS carried
    assert "CONCLUSION_MARKER" not in out                  # conclusion is NOT
    assert "next_steps" not in out and "41.5" not in out


def test_finish_json_is_kept_in_the_saved_log():
    """...but it MUST survive serialization into full_log.json — the record has
    to show what the agent concluded (and the ``_finish`` tag is what lets the
    renderer above withhold it)."""
    from ari.agent.loop import serialize_messages
    out = serialize_messages([
        {"role": "assistant", "content": "{\"status\": \"success\"}", "_finish": True},
        {"role": "assistant", "content": "mid-run"},
    ])
    assert out[0]["_finish"] is True
    assert out[0]["content"] == "{\"status\": \"success\"}"
    assert "_finish" not in out[1]


def test_full_log_empty_when_no_source(tmp_path, monkeypatch):
    from ari.agent.loop import _load_parent_log
    run = tmp_path / "experiments" / "run2"
    (run / "node_child").mkdir(parents=True)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)

    class N:
        parent_id = "node_missing"
    assert _load_parent_log(N(), str(run / "node_child")) == ""
