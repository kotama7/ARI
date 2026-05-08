"""PR #B: nodes_to_science_data report-driven path.

Covers:
- T-B1: prompt size shrinks under 24KB when reports are available
- T-B2: legacy fallback path still works (no reports → unchanged behaviour)
- T-B3: implementation_overview in LLM output is surfaced into return dict
- T-B6: filter_nodes(for_synthesis) excludes abandoned/no-data nodes
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make sure ari-skill-transform/src is importable.
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))


def _get_module():
    """Import the transform skill's server.py, defeating any sys.path shadow
    from sibling skills (paper, paper-re) that also expose `server.py`."""
    import importlib

    ts = str(_TRANSFORM_SRC)
    if ts in sys.path:
        sys.path.remove(ts)
    sys.path.insert(0, ts)
    if "server" in sys.modules:
        del sys.modules["server"]
    return importlib.import_module("server")


def _get_fn():
    mod = _get_module()
    fn = mod.nodes_to_science_data
    if hasattr(fn, "fn"):
        fn = fn.fn
    elif hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _get_litellm_target():
    """Return the litellm module attached to the transform server."""
    return _get_module().litellm


def _make_checkpoint(tmp_path: Path, *, with_reports: bool = True) -> Path:
    workspace = tmp_path / "ws"
    run_id = "exp"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    nodes = [
        {"id": "node_a", "parent_id": None, "depth": 0, "label": "draft",
         "has_real_data": True, "metrics": {"x": 1.0, "_scientific_score": 0.4},
         "eval_summary": "baseline", "artifacts": []},
        {"id": "node_b", "parent_id": "node_a", "depth": 1, "label": "improve",
         "has_real_data": True, "metrics": {"x": 2.0, "_scientific_score": 0.85},
         "eval_summary": "improved", "artifacts": []},
        {"id": "node_c", "parent_id": "node_a", "depth": 1, "label": "draft",
         "has_real_data": False, "metrics": {},
         "eval_summary": "abandoned", "artifacts": []},
    ]
    (ckpt / "tree.json").write_text(
        json.dumps({"run_id": run_id, "experiment_goal": "test", "nodes": nodes}))
    if with_reports:
        for nid, files_added in (("node_a", ["main.py"]),
                                 ("node_b", ["main.py"]),  # modified
                                 ):
            wd = workspace / "experiments" / run_id / nid
            wd.mkdir(parents=True)
            (wd / "main.py").write_text(f"# {nid}\nprint('hello')\n")
            rep = {
                "schema_version": 1,
                "node_id": nid,
                "depth": 0 if nid == "node_a" else 1,
                "label": "draft" if nid == "node_a" else "improve",
                "status": "success",
                "files_changed": {
                    "added": [{"path": "main.py", "sha256": "x"}] if nid == "node_a"
                              else [],
                    "modified": [{"path": "main.py",
                                  "sha256_before": "a", "sha256_after": "b"}]
                                if nid == "node_b" else [],
                    "deleted": [], "inherited_unchanged": [],
                },
                "delta_vs_parent": "made faster" if nid == "node_b" else "initial",
                "self_assessment": {"succeeded": True, "headline": "ok",
                                    "concerns": []},
                "metrics": {"x": 1.0 if nid == "node_a" else 2.0},
                "artifacts": [],
                "build_command": "python -c 'pass'" if nid == "node_b" else "",
                "run_command": "python main.py" if nid == "node_b" else "",
            }
            (wd / "node_report.json").write_text(json.dumps(rep))
    return ckpt


def test_TB1_prompt_size_shrinks_with_reports(tmp_path: Path):
    """When node_report.json is present, the LLM prompt should be much smaller
    than the legacy 64KB-of-artifact-text path."""
    ckpt = _make_checkpoint(tmp_path, with_reports=True)
    fn = _get_fn()

    captured: dict = {}

    async def _fake(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]

        class _R:
            choices = [type("C", (), {
                "message": type("M", (), {
                    "content": json.dumps({
                        "evaluation_protocol": {"domain": "test"},
                        "experiment_context": {"hardware": "CPU"},
                    }),
                })()
            })]
        return _R()

    _srv = _get_module()
    with patch.object(_srv.litellm, "acompletion", _fake):
        out = asyncio.run(fn(str(ckpt / "tree.json")))

    assert out.get("report_driven") is True, out
    prompt = captured["prompt"]
    # Spec NFR-11: typical 16-24KB. We assert a generous 30KB upper bound.
    assert len(prompt) < 30_000, f"prompt too large: {len(prompt)} chars"
    # Sanity: report-driven prompt mentions delta_vs_parent.
    assert "delta_vs_parent" in prompt
    # The compact source blob path is taken.
    assert "VERBATIM SOURCE" in prompt


def test_TB2_legacy_fallback_when_no_reports(tmp_path: Path):
    """No node_report.json anywhere → use legacy artifact-text path."""
    ckpt = _make_checkpoint(tmp_path, with_reports=False)
    fn = _get_fn()
    captured: dict = {}

    async def _fake(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]

        class _R:
            choices = [type("C", (), {
                "message": type("M", (), {
                    "content": '{"experiment_context": {"hardware": "CPU"}}',
                })()
            })]
        return _R()

    _srv = _get_module()
    with patch.object(_srv.litellm, "acompletion", _fake):
        out = asyncio.run(fn(str(ckpt / "tree.json")))

    assert out.get("report_driven") is False
    assert "EXPERIMENT TREE" in captured["prompt"]
    assert "implementation_overview" not in out


def test_TB3_implementation_overview_surfaces_when_present(tmp_path: Path):
    """When the LLM emits implementation_overview, it ends up in the
    return dict."""
    ckpt = _make_checkpoint(tmp_path, with_reports=True)
    fn = _get_fn()

    async def _fake(**kwargs):
        class _R:
            choices = [type("C", (), {
                "message": type("M", (), {
                    "content": json.dumps({
                        "evaluation_protocol": {"domain": "test"},
                        "experiment_context": {},
                        "implementation_overview": {
                            "architecture": "Three-loop CSR",
                            "key_algorithms": [],
                            "optimizations": ["O3", "OpenMP"],
                        },
                    }),
                })()
            })]
        return _R()

    _srv = _get_module()
    with patch.object(_srv.litellm, "acompletion", _fake):
        out = asyncio.run(fn(str(ckpt / "tree.json")))

    assert "implementation_overview" in out
    assert out["implementation_overview"]["architecture"] == "Three-loop CSR"
    assert out["implementation_overview"]["optimizations"] == ["O3", "OpenMP"]


def test_TB3b_implementation_overview_absent_when_llm_omits(tmp_path: Path):
    ckpt = _make_checkpoint(tmp_path, with_reports=True)
    fn = _get_fn()

    async def _fake(**kwargs):
        class _R:
            choices = [type("C", (), {
                "message": type("M", (), {
                    "content": '{"experiment_context": {}}',
                })()
            })]
        return _R()

    _srv = _get_module()
    with patch.object(_srv.litellm, "acompletion", _fake):
        out = asyncio.run(fn(str(ckpt / "tree.json")))

    assert "implementation_overview" not in out


def test_TB6_for_synthesis_filter_drops_abandoned(tmp_path: Path):
    """node_c (has_real_data=false, no metrics) is dropped from the prompt
    by filter_nodes(for_synthesis), while node_a (best ancestor) and
    node_b (best) survive."""
    ckpt = _make_checkpoint(tmp_path, with_reports=True)
    fn = _get_fn()

    captured: dict = {}

    async def _fake(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]

        class _R:
            choices = [type("C", (), {
                "message": type("M", (), {
                    "content": '{"experiment_context": {}}',
                })()
            })]
        return _R()

    _srv = _get_module()
    with patch.object(_srv.litellm, "acompletion", _fake):
        asyncio.run(fn(str(ckpt / "tree.json")))

    prompt = captured["prompt"]
    # node_a (DRAFT) and node_b (IMPROVE) are both kept (real data).
    assert "[DRAFT depth=0]" in prompt
    assert "[IMPROVE depth=1]" in prompt
    # node_c was abandoned with no metrics — its label "draft" duplicates
    # node_a's so we check for its specific delta string instead.
    assert "abandoned" not in prompt.lower()
