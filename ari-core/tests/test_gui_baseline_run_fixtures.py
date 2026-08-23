"""GUI refresh Wave 0 (G0) — reference run fixture tests.

Pins the deterministic synthetic-checkpoint factory in
``tests/fixtures/gui_refresh/run_fixture_factory.py``:

- factory output is loadable by ``ari.checkpoint.load_nodes_tree``
  (small = 10, medium = 1000 nodes);
- same seed ⇒ byte-identical ``tree.json`` (design principle P2);
- each corrupt mode produces the intended failure shape under *current*
  library behaviour (asserted as-is — no library code changed);
- large (10000 nodes) generation completes with the right node count
  (kept fast: no ``load_nodes_tree`` reload of the large tier, since the
  repo defines no ``slow`` pytest marker).

Gate: docs/guides/gui_cutover_runbook.md §Compatibility matrix
("small × medium × large × corrupt checkpoint").
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from ari.checkpoint import load_nodes_tree
from ari.orchestrator.node import Node, NodeStatus

_FACTORY_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "gui_refresh"
    / "run_fixture_factory.py"
)


def _load_factory():
    spec = importlib.util.spec_from_file_location(
        "gui_refresh_run_fixture_factory", _FACTORY_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


factory = _load_factory()
make_run_checkpoint = factory.make_run_checkpoint

# The exact key set of Node.to_dict() — fixture nodes must not drift from it.
_NODE_KEYS = set(Node(id="probe", parent_id=None, depth=0).to_dict().keys())
_VALID_STATUSES = {s.value for s in NodeStatus}


# ──────────────────────────────────────────────
# loadability (small / medium)
# ──────────────────────────────────────────────


def test_small_fixture_loadable_and_schema_faithful(tmp_path):
    manifest = make_run_checkpoint(tmp_path / "small", nodes=10, seed=0)
    assert manifest["run_id"] == "fixture_10n"
    assert manifest["nodes"] == 10

    data = load_nodes_tree(tmp_path / "small")
    assert data is not None
    nodes = data["nodes"]
    assert len(nodes) == 10
    assert data["run_id"] == "fixture_10n"

    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        # Exact Node.to_dict() key set — schema fidelity, no drift.
        assert set(n.keys()) == _NODE_KEYS, n["id"]
        assert n["status"] in _VALID_STATUSES
        # No clock-derived values: fixed 2026-07-23 literals only.
        assert n["created_at"].startswith("2026-07-23T")
        if n["parent_id"] is None:
            assert n["depth"] == 0 and n["ancestor_ids"] == []
        else:
            parent = by_id[n["parent_id"]]
            assert n["depth"] == parent["depth"] + 1
            assert n["ancestor_ids"] == parent["ancestor_ids"] + [parent["id"]]
            assert n["id"] in parent["children"]
        if n["status"] == "success":
            assert "_scientific_score" in n["metrics"]
            assert 0.0 <= n["metrics"]["_scientific_score"] <= 1.0

    # Companion files exist with the production shapes.
    results = json.loads((tmp_path / "small" / "results.json").read_text())
    assert set(results["nodes"].keys()) == set(by_id.keys())
    first = next(iter(results["nodes"].values()))
    assert set(first.keys()) == {
        "artifacts", "metrics", "has_real_data", "eval_summary", "status", "error_log",
    }
    idea = json.loads((tmp_path / "small" / "idea.json").read_text())
    assert idea["ideas"], "idea.json must carry a non-empty ideas catalog"
    meta = json.loads((tmp_path / "small" / "meta.json").read_text())
    assert meta["run_id"] == "fixture_10n"
    trace_lines = (
        (tmp_path / "small" / "cost_trace.jsonl").read_text().strip().splitlines()
    )
    assert trace_lines
    for line in trace_lines:
        rec = json.loads(line)
        assert {"timestamp", "node_id", "model", "total_tokens",
                "estimated_cost_usd"} <= set(rec.keys())
        assert "epoch" not in rec  # simple_bfts lines omit epoch


def test_medium_fixture_loadable(tmp_path):
    manifest = make_run_checkpoint(tmp_path / "medium", nodes=1000, seed=0)
    assert manifest["nodes"] == 1000
    data = load_nodes_tree(tmp_path / "medium")
    assert data is not None
    assert len(data["nodes"]) == 1000
    assert data["run_id"] == "fixture_1000n"


# ──────────────────────────────────────────────
# determinism (P2)
# ──────────────────────────────────────────────


def test_same_seed_is_byte_identical(tmp_path):
    make_run_checkpoint(tmp_path / "a", nodes=50, seed=7)
    make_run_checkpoint(tmp_path / "b", nodes=50, seed=7)
    for fname in ("tree.json", "nodes_tree.json", "results.json",
                  "idea.json", "meta.json", "cost_trace.jsonl"):
        assert (tmp_path / "a" / fname).read_bytes() == (
            tmp_path / "b" / fname
        ).read_bytes(), f"{fname} not byte-identical for identical seeds"


def test_different_seed_changes_content(tmp_path):
    make_run_checkpoint(tmp_path / "a", nodes=50, seed=7)
    make_run_checkpoint(tmp_path / "c", nodes=50, seed=8)
    assert (tmp_path / "a" / "tree.json").read_bytes() != (
        tmp_path / "c" / "tree.json"
    ).read_bytes()


# ──────────────────────────────────────────────
# corrupt modes — assert CURRENT library behaviour
# ──────────────────────────────────────────────


def test_corrupt_truncated_jsonl(tmp_path):
    make_run_checkpoint(tmp_path / "run", nodes=10, seed=0, corrupt="truncated_jsonl")
    raw = (tmp_path / "run" / "cost_trace.jsonl").read_text()
    lines = raw.splitlines()
    assert lines, "trace must still have content"
    # Last line is torn mid-record: unparseable JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(lines[-1])
    # Earlier lines stay intact — a skip-bad-lines reader keeps them.
    for line in lines[:-1]:
        json.loads(line)
    # The tree itself is untouched: the run still loads.
    data = load_nodes_tree(tmp_path / "run")
    assert data is not None and len(data["nodes"]) == 10


def test_corrupt_invalid_json_returns_none(tmp_path):
    make_run_checkpoint(tmp_path / "run", nodes=10, seed=0, corrupt="invalid_json")
    # tree.json exists but is torn; current load_nodes_tree retries once on
    # JSONDecodeError then returns None (it never falls through to the valid
    # nodes_tree.json, because precedence picks the existing tree.json path).
    with pytest.raises(json.JSONDecodeError):
        json.loads((tmp_path / "run" / "tree.json").read_text())
    assert load_nodes_tree(tmp_path / "run") is None


def test_corrupt_partial_write_falls_back_to_nodes_tree(tmp_path):
    make_run_checkpoint(tmp_path / "run", nodes=10, seed=0, corrupt="partial_write")
    assert not (tmp_path / "run" / "tree.json").exists()
    assert (tmp_path / "run" / "nodes_tree.json").exists()
    # Current behaviour: tier-2 fallback loads nodes_tree.json successfully.
    data = load_nodes_tree(tmp_path / "run")
    assert data is not None
    assert len(data["nodes"]) == 10
    assert "experiment_goal" in data  # nodes_tree.json shape, not tree.json


def test_unknown_corrupt_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        make_run_checkpoint(tmp_path / "run", nodes=5, corrupt="nonsense")


# ──────────────────────────────────────────────
# large tier — generation completes, count matches
# ──────────────────────────────────────────────


def test_large_fixture_generation_completes(tmp_path):
    # No `slow` marker exists in this repo's pytest config, so this stays
    # fast: verify the node count by manifest + a raw text scan of tree.json
    # ('"parent_id":' appears exactly once per node) instead of a full
    # load_nodes_tree reload/parse of the large tier.
    manifest = make_run_checkpoint(tmp_path / "large", nodes=10000, seed=0)
    assert manifest["nodes"] == 10000
    assert manifest["run_id"] == "fixture_10000n"
    tree_path = tmp_path / "large" / "tree.json"
    assert tree_path.stat().st_size > 0
    raw = tree_path.read_text(encoding="utf-8")
    assert raw.count('"parent_id":') == 10000
    for fname in ("nodes_tree.json", "results.json", "idea.json",
                  "meta.json", "cost_trace.jsonl", "experiment.md"):
        assert (tmp_path / "large" / fname).exists()
