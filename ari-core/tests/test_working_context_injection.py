"""Phase 0 — Tier 1/2 working-context injection.

Covers ari.agent.loop.build_working_context_messages, the deterministic,
loop-orchestrated replacement for the old one-shot semantic pre-seed
(PLAN_memory_inheritance.md §4-5). Verifies:

  (1a) experiment core is injected for every node (incl. root);
  (1b) ancestor result_summary entries are injected deterministically and
       in full (per-entry cap, not the old aggregate [:800] truncation);
       sibling/non-ancestor entries never appear;
  (2)  the semantic supplement is per-entry capped and deduped vs (1b);
  - the MCPClient ``{"result": "<json>"}`` envelope is unwrapped.
"""
from __future__ import annotations

import json

from ari.agent.loop import build_working_context_messages, _mcp_payload


def _wrap(payload: dict) -> dict:
    """Mimic MCPClient.call_tool's envelope: {"result": "<json text>"}."""
    return {"result": json.dumps(payload)}


def _fake_call_tool(*, ctx=None, node_memory=None, search=None, calls=None):
    """Build a call_tool(name, args) stub backed by canned payloads.

    node_memory: {node_id: [entry, ...]}; entry = {"text", "metadata"}.
    search:      list of {"text": ...} returned by search_memory.
    calls:       optional list to record (name, args) for assertions.
    """
    node_memory = node_memory or {}
    search = search or []

    def call_tool(name, args):
        if calls is not None:
            calls.append((name, args))
        if name == "get_experiment_context":
            return _wrap(ctx or {})
        if name == "get_node_memory":
            return _wrap({"entries": node_memory.get(args["node_id"], [])})
        if name == "search_memory":
            return _wrap({"results": search})
        raise AssertionError(f"unexpected tool {name}")

    return call_tool


# ── _mcp_payload envelope unwrapping ─────────────────────────────────────

def test_mcp_payload_unwraps_result_envelope():
    assert _mcp_payload({"result": json.dumps({"a": 1})}) == {"a": 1}


def test_mcp_payload_accepts_bare_dict_and_json_string():
    assert _mcp_payload({"entries": []}) == {"entries": []}
    assert _mcp_payload(json.dumps({"x": 2})) == {"x": 2}


def test_mcp_payload_returns_empty_on_garbage():
    assert _mcp_payload({"result": "not json"}) == {}
    assert _mcp_payload(None) == {}
    assert _mcp_payload(12345) == {}


# ── (1a) experiment core ─────────────────────────────────────────────────

def test_experiment_core_injected_for_root():
    call = _fake_call_tool(ctx={
        "primary_metric": "GB/s", "higher_is_better": True,
        "metric_rationale": "memory-bound kernel", "hardware_spec": "cpuX",
    })
    msgs = build_working_context_messages(
        call, depth=0, ancestor_ids=[], eval_summary=None, experiment_goal="goal",
    )
    assert len(msgs) == 1
    c = msgs[0]["content"]
    assert "Experiment context" in c
    assert "primary_metric: GB/s" in c and "hardware_spec: cpuX" in c


def test_experiment_core_fields_are_capped():
    # Real depth-4 chains injected ~3 KB of verbose core fields; each field is
    # now capped (PLAN §8 token budget / Phase 0.1).
    call = _fake_call_tool(ctx={"primary_metric": "GB/s", "metric_rationale": "R" * 1000})
    msgs = build_working_context_messages(
        call, depth=0, ancestor_ids=[], eval_summary=None, experiment_goal="g",
    )
    c = msgs[0]["content"]
    assert "R" * 400 in c and "R" * 401 not in c   # per-field cap applied
    assert "truncated" in c


def test_experiment_core_skipped_when_unseeded():
    call = _fake_call_tool(ctx={})
    msgs = build_working_context_messages(
        call, depth=0, ancestor_ids=[], eval_summary=None, experiment_goal="g",
    )
    assert msgs == []


# ── (1b) ancestor core (deterministic, full, scoped) ─────────────────────

def _rs(text):  # a result_summary entry
    return {"text": text, "metadata": {"type": "result_summary"}}


def test_ancestor_core_injects_all_summaries_in_order():
    nm = {
        "root": [_rs("ROOT: baseline 100 GB/s"), {"text": "noise", "metadata": {"type": "survey_papers"}}],
        "p1": [_rs("P1: tiling -> 140 GB/s")],
    }
    msgs = build_working_context_messages(
        _fake_call_tool(node_memory=nm),
        depth=2, ancestor_ids=["root", "p1"], eval_summary="q", experiment_goal="g",
    )
    concl = [m for m in msgs if "Established conclusions" in m["content"]]
    assert len(concl) == 1
    c = concl[0]["content"]
    # both ancestor conclusions present, in ancestor order, non-result_summary excluded
    assert "ROOT: baseline 100 GB/s" in c
    assert "P1: tiling -> 140 GB/s" in c
    assert "noise" not in c
    assert c.index("ROOT") < c.index("P1")


def test_ancestor_core_per_entry_cap_not_aggregate():
    # Two long summaries: old code joined then cut at 800 total (2nd lost).
    # New code caps each at 600 and keeps BOTH.
    a, b = "A" * 1000, "B" * 1000
    msgs = build_working_context_messages(
        _fake_call_tool(node_memory={"root": [_rs(a)], "p1": [_rs(b)]}),
        depth=2, ancestor_ids=["root", "p1"], eval_summary=None, experiment_goal=None,
    )
    c = next(m["content"] for m in msgs if "Established conclusions" in m["content"])
    assert "A" * 600 in c and "B" * 600 in c      # both survive, each capped at 600
    assert "A" * 601 not in c                       # per-entry cap applied


def test_root_node_gets_no_ancestor_core():
    msgs = build_working_context_messages(
        _fake_call_tool(node_memory={"root": [_rs("x")]}),
        depth=0, ancestor_ids=[], eval_summary=None, experiment_goal=None,
    )
    assert all("Established conclusions" not in m["content"] for m in msgs)


def test_only_queried_ancestors_are_fetched():
    calls = []
    build_working_context_messages(
        _fake_call_tool(node_memory={"root": [_rs("x")]}, calls=calls),
        depth=1, ancestor_ids=["root"], eval_summary="q", experiment_goal="g",
    )
    fetched = {a["node_id"] for (n, a) in calls if n == "get_node_memory"}
    assert fetched == {"root"}  # never fetches siblings/non-ancestors


# ── (2) detail supplement: cap + dedup ───────────────────────────────────

def test_supplement_dedups_against_ancestor_core():
    summary = "P1: tiling -> 140 GB/s and notes"
    msgs = build_working_context_messages(
        _fake_call_tool(
            node_memory={"p1": [_rs(summary)]},
            search=[{"text": summary}, {"text": "extra detail: cache misses high"}],
        ),
        depth=1, ancestor_ids=["p1"], eval_summary="q", experiment_goal="g",
    )
    supp = [m for m in msgs if "Related prior findings" in m["content"]]
    assert len(supp) == 1
    c = supp[0]["content"]
    assert "extra detail: cache misses high" in c
    # the entry already injected as a conclusion is deduped out of the supplement
    assert c.count("tiling -> 140 GB/s") == 0


def test_supplement_per_entry_capped_at_400():
    long = "Z" * 1000
    msgs = build_working_context_messages(
        _fake_call_tool(node_memory={}, search=[{"text": long}]),
        depth=1, ancestor_ids=["p1"], eval_summary="q", experiment_goal="g",
    )
    c = next(m["content"] for m in msgs if "Related prior findings" in m["content"])
    assert "Z" * 400 in c and "Z" * 401 not in c
