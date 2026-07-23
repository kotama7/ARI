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


# ── The summary channel must carry the MEASURED verdict, never the agent's
# self-narrative. Observed live in a gemm pilot: a candidate that did not compile
# (score 0.0, has_real_data=False) shipped "The kernel passes the self-test and
# achieves ~23.3x speedup" to its child as `evaluator_reason`, because the
# deterministic evaluator's reason — written to node.eval_summary — was then
# overwritten by mark_success(eval_summary=<agent finish-JSON summary>). Only the
# +summary arms receive that field, so the misinformation biased the very arm
# comparison the study measures.

def test_evaluator_verdict_survives_mark_success():
    """A verdict already on the node must not be replaced by the agent's summary."""
    from ari.orchestrator.node import Node
    n = Node(id="node_x", parent_id=None, depth=0)
    verdict = "compile failed: candidate_gemm.c:56: error [scientific_score=0.00]"
    n.eval_summary = verdict
    # the expression loop.py's finish_json path now passes
    n.mark_success(artifacts=[],
                   eval_summary=(n.eval_summary or "agent: ~23.3x, self-test passes"))
    assert n.eval_summary == verdict
    assert "23.3" not in n.eval_summary, "agent self-claim replaced the measured verdict"


def test_agent_summary_still_used_when_no_evaluator_ran():
    """Fallback preserved: with no evaluator verdict the agent summary is kept."""
    from ari.orchestrator.node import Node
    n = Node(id="node_y", parent_id=None, depth=0)
    assert not n.eval_summary
    n.mark_success(artifacts=[], eval_summary=(n.eval_summary or "agent narrative"))
    assert n.eval_summary == "agent narrative"


def test_finish_json_path_does_not_pass_bare_agent_summary():
    """Source guard on the exact regression: the finish_json mark_success call must
    prefer the evaluator verdict. A refactor back to ``eval_summary=summary`` there
    silently re-opens the channel to unverified self-report."""
    import inspect
    import re
    from ari.agent import loop as _loop
    src = inspect.getsource(_loop)
    i = src.find('node.ended_by = "finish_json"')
    assert i != -1, "finish_json path not found — update this guard"
    window = src[i:i + 1600]
    m = re.search(r"node\.mark_success\((.*?)\)", window, re.S)
    assert m, "mark_success call not found after the finish_json marker"
    args = m.group(1)
    assert "node.eval_summary or" in args, (
        "finish_json mark_success no longer prefers the evaluator verdict: " + args.strip())


# ── The summary channel's `outcome` must agree with the MEASUREMENT. Preferring
# the agent's narrative unconditionally shipped a self-reported success next to
# the score that refuted it (observed live: "passes the self-test and achieves
# ~22.9x speedup" beside _scientific_score=0.0 for a candidate that did not
# compile) — unverified self-report re-entering a deterministic loop, and only
# through the +summary arms.

def _failed_report(**kw):
    """A node the MEASUREMENT rejected, but whose agent-loop status is 'success'
    (the agent completed its turns) and whose narrative claims success."""
    base = {
        "node_id": "node_bad", "status": "success",
        "what_was_done": "Implemented ikj + OpenMP; passes the self-test and achieves ~22.9x speedup.",
        "self_assessment": {"succeeded": False, "headline": "~22.9x speedup, self-test passes"},
        "evaluator_reason": "compile failed: candidate_gemm.c:27: error: 'crowd' undeclared [scientific_score=0.00]",
        "metrics": {"_scientific_score": 0.0, "valid_geomean_speedup": 0.0},
    }
    base.update(kw)
    return base


def test_outcome_uses_the_verdict_when_the_measurement_rejected_the_node():
    v = node_summary_view(_failed_report(), fields_enabled=None)
    assert "compile failed" in v, "the child was not told why the parent failed"
    assert "22.9x" not in v, "the agent's refuted success claim reached the child"
    assert "passes the self-test" not in v


def test_outcome_keeps_the_agent_narrative_when_the_measurement_agrees():
    rep = _failed_report(self_assessment={"succeeded": True, "headline": "h"},
                         metrics={"_scientific_score": 0.42, "valid_geomean_speedup": 28.4},
                         what_was_done="Blocked ikj + OpenMP.")
    v = node_summary_view(rep, fields_enabled=None)
    assert "Blocked ikj + OpenMP." in v


def test_known_failures_not_gated_on_the_agent_loop_status():
    """status='success' is the AGENT-LOOP status; a node whose candidate did not
    compile still reports it. Gating on it hid the failure reason exactly when it
    mattered."""
    from ari.orchestrator.node_summary_view import derive_known_failures
    kf = derive_known_failures(_failed_report())
    assert any("compile failed" in k for k in kf), kf


def test_view_scrubs_host_identity_from_agent_facing_text(monkeypatch):
    """node_report.json stays raw (scrubbed only at publication), but this view
    feeds the CHILD'S PROMPT and must never carry work_dir / $HOME / username /
    hostname — a compiler error in the verdict quotes absolute paths."""
    monkeypatch.setenv("ARI_WORK_DIR", "/scratch/fs0/homedir/ARI/workspace/experiments/r/node_x")
    monkeypatch.setenv("HOME", "/scratch/fs0/homedir")
    monkeypatch.setenv("USER", "alice")
    rep = _failed_report(evaluator_reason=(
        "compile failed: /scratch/fs0/homedir/ARI/workspace/experiments/r/node_x/candidate.c:1: "
        "error: boom (owner alice)"))
    v = node_summary_view(rep, fields_enabled=None)
    assert "/scratch/fs0/homedir" not in v
    assert "alice" not in v
    assert "/workspace/candidate.c" in v, v


def test_full_log_treatment_is_the_execution_record_not_stray_stdout(tmp_path):
    """FINDING #19: the +full_log arm must deliver the SAME KIND of object for every
    node. The stray-file glob (run.log / slurm-*.out / stdout.txt) used to run first
    and return early, so a child whose parent happened to `tee run.log` got a build
    log while its cousin got the execution trace — the treatment was not a constant.
    The per-node execution record now wins; the glob remains for non-BFTS runs."""
    from ari.agent.loop import _load_parent_log
    run = tmp_path / "run"
    pdir = run / "node_parent"
    pdir.mkdir(parents=True)
    # a stray build log the agent produced itself
    (pdir / "run.log").write_text("cc -O3 ...\nBUILD OK\n")
    # and the real per-node execution record
    (pdir / "full_log.json").write_text(json.dumps(
        {"trace_log": ["→ write_code(candidate.c)", "← written"]}))

    class _N:
        parent_id = "node_parent"
        id = "node_child"
    out = _load_parent_log(_N(), str(run / "node_child"))
    assert "write_code" in out, "the execution record did not win over stray stdout"
    assert "BUILD OK" not in out, "a stray build log preempted the execution record"
