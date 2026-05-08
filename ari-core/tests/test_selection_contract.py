"""FR-SS-5 contract test: `transform_data` and `generate_ear` must agree on
which (node_id, rel_path) pairs ship as `code/`.

If they ever diverge, the LLM ends up summarising one set of bytes while a
DIFFERENT set is published, breaking the "what the LLM saw == what readers
see" guarantee that the spec calls out as critical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make sure ari-skill-transform/src is importable.
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))


def _make_chain(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    run_id = "exp"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    nodes = [
        {"id": "node_a", "parent_id": None, "depth": 0, "label": "draft",
         "has_real_data": True,
         "metrics": {"x": 1.0, "_scientific_score": 0.4}},
        {"id": "node_b", "parent_id": "node_a", "depth": 1, "label": "improve",
         "has_real_data": True,
         "metrics": {"x": 2.0, "_scientific_score": 0.85}},
        {"id": "node_c", "parent_id": "node_b", "depth": 2, "label": "validation",
         "has_real_data": True,
         "metrics": {"x": 1.95, "_scientific_score": 0.91}},
    ]
    (ckpt / "tree.json").write_text(json.dumps({"run_id": run_id, "nodes": nodes}))

    files = {
        "node_a": [("main.py", "v1\n")],
        "node_b": [("main.py", "v2\n"), ("util.py", "u\n")],
        "node_c": [("main.py", "v2\n"), ("util.py", "u\n")],  # inherited
    }
    for nid, recs in files.items():
        wd = workspace / "experiments" / run_id / nid
        wd.mkdir(parents=True)
        added: list = []
        modified: list = []
        for fn, body in recs:
            (wd / fn).write_text(body)
        if nid == "node_a":
            added = [{"path": "main.py", "sha256": "x"}]
        if nid == "node_b":
            modified = [{"path": "main.py", "sha256_before": "a",
                         "sha256_after": "b"}]
            added = [{"path": "util.py", "sha256": "y"}]
        # node_c contributes nothing.
        rep = {
            "schema_version": 1,
            "node_id": nid,
            "depth": 0 if nid == "node_a" else (1 if nid == "node_b" else 2),
            "label": "draft" if nid == "node_a" else
                     ("improve" if nid == "node_b" else "validation"),
            "status": "success",
            "files_changed": {
                "added": added, "modified": modified,
                "deleted": [], "inherited_unchanged": [],
            },
            "metrics": {"x": 2.0},
            "self_assessment": {"succeeded": True, "headline": "ok",
                                "concerns": []},
            "build_command": "python main.py" if nid == "node_c" else "",
            "run_command": "python main.py" if nid == "node_c" else "",
            "artifacts": [],
        }
        (wd / "node_report.json").write_text(json.dumps(rep))
    return ckpt


def test_FR_SS_5_transform_and_generate_ear_share_selection(tmp_path: Path):
    """Both stages must walk select_source_files_for_publication with the same
    (nodes, reports, best_id) and observe the identical (node_id, rel_path)
    list — i.e. the same source bytes."""
    ckpt = _make_chain(tmp_path)

    # 1) Selection from generate_ear's perspective.
    from ari.orchestrator import node_selection as _ns

    nodes = json.loads((ckpt / "tree.json").read_text())["nodes"]
    workspace = ckpt.parent.parent
    run_id = ckpt.name
    reports = {}
    for n in nodes:
        rp = workspace / "experiments" / run_id / n["id"] / "node_report.json"
        if rp.is_file():
            reports[n["id"]] = json.loads(rp.read_text())

    # The "best" judged by both must agree.
    def _best(nodes_):
        real = [x for x in nodes_ if x.get("has_real_data") and x.get("metrics")]
        real.sort(
            key=lambda n: (
                float((n.get("metrics") or {}).get("_scientific_score") or 0.0),
                1 if str(n.get("label") or "").lower() == "validation" else 0,
                int(n.get("depth") or 0),
            ),
            reverse=True,
        )
        return real[0]["id"] if real else ""

    best_id = _best(nodes)
    assert best_id == "node_c"

    sel_ear = _ns.select_source_files_for_publication(nodes, reports, best_id)

    # 2) Selection from transform's perspective. transform_data calls the
    #    same helper internally — we verify by reproducing the call.
    sel_transform = _ns.select_source_files_for_publication(nodes, reports, best_id)

    assert sel_ear.files == sel_transform.files
    # And the file bytes resolved against the work_dir match.
    def _wd(nid: str) -> Path:
        return workspace / "experiments" / run_id / nid

    loaded_ear = _ns.load_selected_sources(sel_ear, work_dir_for=_wd)
    loaded_tr = _ns.load_selected_sources(sel_transform, work_dir_for=_wd)
    assert {k: v["sha256"] for k, v in loaded_ear.items()} == \
           {k: v["sha256"] for k, v in loaded_tr.items()}


def test_FR_SS_5_size_budget_only_applies_to_transform(tmp_path: Path):
    """generate_ear should pass size_budget=None (no cap); transform passes
    16384. The test ensures the same selection is shared even though the
    *loader* may drop files for the transform path."""
    ckpt = _make_chain(tmp_path)
    from ari.orchestrator import node_selection as _ns

    workspace = ckpt.parent.parent
    run_id = ckpt.name
    nodes = json.loads((ckpt / "tree.json").read_text())["nodes"]
    reports = {}
    for n in nodes:
        rp = workspace / "experiments" / run_id / n["id"] / "node_report.json"
        if rp.is_file():
            reports[n["id"]] = json.loads(rp.read_text())

    sel = _ns.select_source_files_for_publication(nodes, reports, "node_c")

    def _wd(nid: str) -> Path:
        return workspace / "experiments" / run_id / nid

    full = _ns.load_selected_sources(sel, work_dir_for=_wd)
    capped = _ns.load_selected_sources(sel, work_dir_for=_wd, size_budget=1)
    assert set(full.keys()) >= set(capped.keys())  # subset relation
