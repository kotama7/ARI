"""PR #A — tests T-A1..T-A8, T-A16 for ari/orchestrator/node_report.py.

Covers:
- T-A1: compute_files_changed -> {added, modified, deleted, inherited_unchanged}
- T-A2: extract_build_run_commands grep heuristic
- T-A3: classify_artifact_role extension mapping
- T-A4: build_node_report jsonschema conformance
- T-A5: write_node_report writes a file at work_dir/node_report.json
- T-A6: write_node_report on a "failed" node still produces a report
- T-A7: original_direction is preserved across evaluator overwrite of eval_summary
- T-A8: reconstruct_report_from_legacy migration produces a valid report
- T-A16: PathManager.META_FILES contains node_report.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.orchestrator import node_report as nr
from ari.orchestrator.node import Node, NodeLabel, NodeStatus
from ari.paths import PathManager


# ── small jsonschema validator (no external dep) ────────────────────────

def _load_schema() -> dict:
    here = Path(__file__).resolve().parent.parent / "ari" / "schemas" / "node_report.schema.json"
    return json.loads(here.read_text())


def _check_required(report: dict, schema: dict, *, path: str = "$") -> None:
    assert isinstance(report, dict), f"{path}: not a dict"
    for key in schema.get("required", []):
        assert key in report, f"{path}: missing required key {key!r}"


def _validate_minimal(report: dict) -> None:
    """Tiny validator: required keys + a few enum/integer constraints.

    Avoids pulling jsonschema as a hard test dep; the spec only requires
    that the report obeys the schema for the fields we control here.
    """
    schema = _load_schema()
    _check_required(report, schema)
    assert report["schema_version"] == 1
    assert report["label"] in {"draft", "improve", "debug", "ablation",
                               "validation", "other"}
    assert isinstance(report["depth"], int) and report["depth"] >= 0
    fc = report["files_changed"]
    for k in ("added", "modified", "deleted", "inherited_unchanged"):
        assert k in fc, f"files_changed missing {k!r}"
        assert isinstance(fc[k], list)
    for art in report.get("artifacts", []):
        assert "filename" in art and "role" in art
        assert art["role"] in {"data_output", "log", "binary", "figure", "unknown"}


def test_evaluation_case_schema_is_task_neutral() -> None:
    schema = _load_schema()
    case_schema = schema["properties"]["evaluation_cases"]["additionalProperties"]
    assert set(case_schema["properties"]) == {"valid", "measurements"}
    assert case_schema["additionalProperties"] is False

    measurements = case_schema["properties"]["measurements"]
    assert "properties" not in measurements
    assert set(measurements["additionalProperties"]["type"]) == {
        "number", "boolean", "string", "null",
    }


# ── helpers ──────────────────────────────────────────────────────────────

def _write(p: Path, content: str | bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content)
    else:
        p.write_bytes(content)
    return p


def _make_node(*, id_: str = "node_aaa", parent_id: str | None = None,
               depth: int = 0, status: NodeStatus = NodeStatus.SUCCESS,
               label: NodeLabel = NodeLabel.IMPROVE,
               **extra) -> Node:
    n = Node(id=id_, parent_id=parent_id, depth=depth, status=status, label=label)
    for k, v in extra.items():
        setattr(n, k, v)
    return n


# ── T-A1 ────────────────────────────────────────────────────────────────

def test_compute_files_changed_four_buckets(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"

    # parent: a.py + b.py + run_job.sh (will be inherited unchanged)
    _write(parent / "a.py", "print('parent-a')\n")
    _write(parent / "b.py", "print('parent-b')\n")
    _write(parent / "run_job.sh", "#!/bin/bash\necho hi\n")

    # child:
    #  - a.py byte-equal -> inherited_unchanged
    #  - b.py modified
    #  - c.py new -> added
    #  - run_job.sh deleted on the child side -> deleted
    _write(child / "a.py", "print('parent-a')\n")
    _write(child / "b.py", "print('child-b')\n")
    _write(child / "c.py", "print('child-c')\n")

    diff = nr.compute_files_changed(parent, child)
    added = {e["path"] for e in diff["added"]}
    modified = {e["path"] for e in diff["modified"]}
    inherited = {e["path"] for e in diff["inherited_unchanged"]}
    deleted = {e["path"] for e in diff["deleted"]}

    assert added == {"c.py"}
    assert modified == {"b.py"}
    assert inherited == {"a.py"}
    assert deleted == {"run_job.sh"}

    # All "modified" entries should have before/after sha256 set.
    mod = diff["modified"][0]
    assert mod["sha256_before"] and mod["sha256_after"]
    assert mod["sha256_before"] != mod["sha256_after"]


def test_file_notes_are_grafted_onto_files_changed(tmp_path: Path) -> None:
    """The agent's finish-JSON ``file_notes`` land on the matching
    files_changed entry (added/modified/deleted), so a reader knows what each
    touched file is without opening it. Unlisted files simply carry no note."""
    from ari.orchestrator.node_report import build_node_report

    parent = tmp_path / "parent"
    child = tmp_path / "child"
    _write(parent / "kernel.c", "void k(){}\n")
    _write(parent / "old.sh", "echo old\n")          # deleted on the child side
    _write(child / "kernel.c", "void k(){/*fast*/}\n")  # modified
    _write(child / "notes.csv", "a,b\n1,2\n")          # added, no note supplied

    class _Node:
        id = "n1"; parent_id = "p"; ancestor_ids: list = []
        label = "draft"; raw_label = "draft"; depth = 1
        status = "success"; created_at = ""; completed_at = ""
        metrics: dict = {}; artifacts: list = []; trace_log = None
        file_notes = {
            "kernel.c": "blocked GEMM inner loop",
            "old.sh": "superseded by the Makefile",
        }

    rep = build_node_report(node=_Node(), work_dir=child, parent_work_dir=parent,
                            eval_result=None, what_was_done="")
    fc = rep["files_changed"]
    assert "delta_vs_parent" not in rep
    assert {e["path"]: e.get("note") for e in fc["modified"]} == {
        "kernel.c": "blocked GEMM inner loop"}
    assert {e["path"]: e.get("note") for e in fc["deleted"]} == {
        "old.sh": "superseded by the Makefile"}
    # added file the agent did not note -> present, but no note key
    _added = {e["path"]: e for e in fc["added"]}
    assert "notes.csv" in _added and "note" not in _added["notes.csv"]


def test_files_changed_without_file_notes_has_no_note_keys(tmp_path: Path) -> None:
    """No agent notes (older nodes / agent omitted them) -> entries are unchanged."""
    from ari.orchestrator.node_report import build_node_report

    child = tmp_path / "child"
    _write(child / "a.c", "int main(){}\n")

    class _Node:
        id = "n2"; parent_id = None; ancestor_ids: list = []
        label = "draft"; raw_label = "draft"; depth = 0
        status = "success"; created_at = ""; completed_at = ""
        metrics: dict = {}; artifacts: list = []; trace_log = None

    rep = build_node_report(node=_Node(), work_dir=child, parent_work_dir=None,
                            eval_result=None, what_was_done="")
    assert all("note" not in e for e in rep["files_changed"]["added"])


def test_compute_files_changed_skips_blocklist(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    # parent has nothing of interest; child writes a node_report.json,
    # cost_trace.jsonl, and __pycache__/foo.cpython-313.pyc — none should
    # appear in the diff.
    _write(child / "good.py", "print('hi')\n")
    _write(child / "node_report.json", "{}\n")
    _write(child / "cost_trace.jsonl", "{}\n")
    _write(child / "__pycache__" / "foo.cpython-313.pyc", b"\x00\x01")

    diff = nr.compute_files_changed(parent, child)
    paths = {e["path"] for e in diff["added"]}
    assert paths == {"good.py"}


def test_compute_files_changed_no_parent_treats_all_as_added(tmp_path: Path) -> None:
    child = tmp_path / "child"
    _write(child / "x.py", "x\n")
    _write(child / "y.py", "y\n")
    diff = nr.compute_files_changed(None, child)
    assert {e["path"] for e in diff["added"]} == {"x.py", "y.py"}
    assert diff["modified"] == [] and diff["deleted"] == []
    assert diff["inherited_unchanged"] == []


# ── T-A2 ────────────────────────────────────────────────────────────────

def test_extract_build_run_commands_from_run_job(tmp_path: Path) -> None:
    work = tmp_path / "node"
    _write(work / "run_job.sh", (
        "#!/bin/bash\n"
        "#SBATCH -p cpu\n"
        "set -e\n"
        "cd $WORK\n"
        "g++ -O3 -fopenmp spmm.cpp -o spmm\n"
        "./spmm --m 1000 --n 1000 --out result.csv\n"
    ))
    build, run = nr.extract_build_run_commands(work)
    assert "g++" in build and "spmm.cpp" in build
    assert "./spmm" in run and "result.csv" in run


def test_extract_build_run_commands_returns_empty_when_absent(tmp_path: Path) -> None:
    work = tmp_path / "node"
    work.mkdir()
    _write(work / "notes.txt", "no commands here")
    build, run = nr.extract_build_run_commands(work)
    assert build == "" and run == ""


def test_extract_build_run_commands_skips_bare_var_assignments(tmp_path: Path) -> None:
    """Bug 3b: env var assignments containing build keywords (e.g. ``CXX=g++``)
    must not be classified as build_command. Without this fix, the extractor
    captured ``CXX=${CXX:-g++}`` as build_command and ``CXXFLAGS=...`` as
    run_command, leaving the actual compile + execute lines unrepresented in
    node_report.json."""
    work = tmp_path / "node"
    _write(work / "run_job.sh", (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "CXX=${CXX:-g++}\n"
        'CXXFLAGS="-O3 -march=native -fopenmp -std=c++17"\n'
        "g++ $CXXFLAGS spmm_envelope.cpp -o spmm_envelope\n"
        "./spmm_envelope --m 120000 --threads 8 2> run.log\n"
    ))
    build, run = nr.extract_build_run_commands(work)
    # Env-var assignments must NOT leak into build/run.
    assert not build.startswith("CXX=") and not build.startswith("CXXFLAGS=")
    assert not run.startswith("CXX=") and not run.startswith("CXXFLAGS=")
    # The actual compile line gets captured as build (literal g++ keyword).
    assert "spmm_envelope.cpp" in build, f"build={build!r}"
    # The execute line gets captured as run.
    assert "./spmm_envelope" in run, f"run={run!r}"


# ── T-A3 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("results.csv", "data_output"),
    ("metrics.json", "data_output"),
    ("config.yaml", "data_output"),
    ("logs.txt", "log"),
    ("ari.log", "log"),
    ("slurm-1234.out", "log"),
    ("slurm-1234.err", "log"),
    ("plot.png", "figure"),
    ("figure.pdf", "figure"),
    ("diagram.svg", "figure"),
    ("a.bin", "binary"),
    ("libfoo.so", "binary"),
    ("readme.weird", "unknown"),
    ("node_report.json", "unknown"),  # internal — not a publishable output.
    ("tree.json", "unknown"),
])
def test_classify_artifact_role(filename: str, expected: str) -> None:
    assert nr.classify_artifact_role(filename) == expected


def test_classify_artifact_role_executable_no_extension(tmp_path: Path) -> None:
    work = tmp_path / "n"
    work.mkdir()
    bin_file = work / "spmm_bench"
    bin_file.write_bytes(b"\x7fELF")
    bin_file.chmod(0o755)
    assert nr.classify_artifact_role("spmm_bench", work) == "binary"


# ── T-A4 + T-A5 ─────────────────────────────────────────────────────────

def test_build_and_write_node_report(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    _write(parent / "a.py", "old\n")
    _write(child / "a.py", "new\n")
    _write(child / "out.csv", "k,v\n1,2\n")
    _write(child / "run_job.sh", (
        "#!/bin/bash\n"
        "g++ -O2 a.cpp -o a\n"
        "./a --out out.csv\n"
    ))

    node = _make_node(
        id_="node_t1", parent_id="node_root", depth=2,
        label=NodeLabel.IMPROVE, status=NodeStatus.SUCCESS,
        ancestor_ids=["node_root", "node_mid"],
        artifacts=[str(child / "out.csv")],
        metrics={"throughput": 12.5},
        eval_summary="Looked fine",
    )
    eval_result = {
        "scientific_score": 0.71,
        "axis_scores": {"measurement_validity": 0.8, "comparative_rigor": 0.3},
        "axis_rationales": {
            "measurement_validity": "metric is well calibrated",
            "comparative_rigor": "no MKL baseline",
        },
        "reason": "Reported headline metric in line with expectation.",
        "has_real_data": True,
        "evaluation_cases": {
            "shape_a": {
                "valid": True,
                "measurements": {
                    "speedup": 1.25,
                    "max_relative_error": 1e-12,
                    "n_clamped": 0,
                },
            },
        },
    }

    out = nr.write_node_report(
        node=node, work_dir=child, parent_work_dir=parent,
        eval_result=eval_result,
        what_was_done="Optimised inner loop",
    )

    assert out == child / "node_report.json"
    report = json.loads(out.read_text())
    _validate_minimal(report)

    # Field-level checks.
    assert report["node_id"] == "node_t1"
    assert report["label"] == "improve"
    assert report["depth"] == 2
    assert report["status"] == "success"
    assert "a.py" in [m["path"] for m in report["files_changed"]["modified"]]
    assert "out.csv" in [a["path"] for a in report["files_changed"]["added"]]
    assert "g++" in report["build_command"]
    assert "./a" in report["run_command"]
    # axis with score < 0.4 -> concerns; 0.4..0.7 -> next_steps; >=0.7 -> dropped.
    concerns_text = " ".join(report["self_assessment"]["concerns"])
    assert "comparative_rigor" in concerns_text
    next_text = " ".join(report["next_steps_hints"])
    assert "measurement_validity" not in next_text  # 0.8 -> dropped from suggestions.
    # Artifact for out.csv is data_output.
    out_csv = next(a for a in report["artifacts"] if a["filename"] == "out.csv")
    assert out_csv["role"] == "data_output"
    assert out_csv.get("size") == (child / "out.csv").stat().st_size
    # Metrics now include scientific_score and axis_scores after evaluator merge.
    assert report["metrics"].get("_scientific_score") == 0.71
    assert "_axis_scores" in report["metrics"]
    assert report["measurement_valid"] is True
    assert report["evaluation_cases"]["shape_a"]["valid"] is True
    assert "succeeded" not in report["self_assessment"]


# ── T-A6 ────────────────────────────────────────────────────────────────

def test_write_node_report_for_failed_node(tmp_path: Path) -> None:
    work = tmp_path / "node_fail"
    _write(work / "x.py", "boom\n")

    node = _make_node(
        id_="node_fail", parent_id="node_root", depth=1,
        label=NodeLabel.DEBUG, status=NodeStatus.FAILED,
        eval_summary="Crashed", artifacts=[],
    )
    out = nr.write_node_report(
        node=node, work_dir=work, parent_work_dir=None,
        eval_result=None,
    )
    report = json.loads(out.read_text())
    _validate_minimal(report)
    assert report["status"] == "failed"
    assert report["measurement_valid"] is False
    assert "succeeded" not in report["self_assessment"]


def test_evaluator_reason_never_falls_back_to_llm_direction(
    tmp_path: Path,
) -> None:
    work = tmp_path / "node_no_eval"
    _write(work / "x.py", "pass\n")
    node = _make_node(
        id_="node_no_eval",
        parent_id="node_root",
        depth=1,
        label=NodeLabel.IMPROVE,
        status=NodeStatus.FAILED,
        eval_summary="Try a blocked and vectorized implementation next",
        artifacts=[],
    )
    report = nr.build_node_report(
        node=node,
        work_dir=work,
        parent_work_dir=None,
        eval_result=None,
    )
    assert report["evaluator_reason"] == ""

    node.evaluator_reason = "deterministic evaluator rejected the candidate"
    report = nr.build_node_report(
        node=node,
        work_dir=work,
        parent_work_dir=None,
        eval_result=None,
    )
    assert report["evaluator_reason"] == node.evaluator_reason


# ── T-A7 ────────────────────────────────────────────────────────────────

def test_original_direction_preserved_after_eval_summary_overwrite() -> None:
    n = Node(id="node_x", parent_id=None, depth=0)
    n.original_direction = "Sweep k from 1..930 with fp32/fp64"
    n.eval_summary = "<original direction>"
    # Simulate evaluator overwriting eval_summary later in the loop.
    n.eval_summary = "evaluator reason [scientific_score=0.43]"
    assert n.original_direction == "Sweep k from 1..930 with fp32/fp64"

    # And the to_dict() snapshot exposes both.
    d = n.to_dict()
    assert d["original_direction"] == "Sweep k from 1..930 with fp32/fp64"
    assert d["eval_summary"] != d["original_direction"]


# ── T-A8 ────────────────────────────────────────────────────────────────

def test_reconstruct_report_from_legacy(tmp_path: Path) -> None:
    work = tmp_path / "n"
    _write(work / "a.py", "...\n")
    _write(work / "Makefile", "all:\n\tg++ -O2 a.cpp\n")
    legacy = {
        "id": "node_legacy",
        "parent_id": "node_root",
        "depth": 1,
        "status": "success",
        "label": "improve",
        "ancestor_ids": ["node_root"],
        "metrics": {"x": 1},
        "eval_summary": "looks ok [scientific_score=0.55]",
        "has_real_data": True,
        "artifacts": ["a.py"],
    }
    rep = nr.reconstruct_report_from_legacy(
        node_dict=legacy, work_dir=work, parent_work_dir=None,
    )
    _validate_minimal(rep)
    # evaluator_reason should have stripped the trailing scientific_score tag.
    assert "scientific_score" not in rep["evaluator_reason"]
    assert rep["self_assessment"]["headline"] == "looks ok"


# ── T-A16 ───────────────────────────────────────────────────────────────

def test_meta_files_contains_node_report_json() -> None:
    assert "node_report.json" in PathManager.META_FILES
    assert PathManager.is_meta_file("node_report.json") is True


# ── the evaluator's axis rationales must REACH the report (dead-seam sweep) ──
#
# `derive_self_assessment_from_evaluator` maps per-axis rationales into
# `self_assessment.concerns` and `next_steps_hints`. The evaluator produced
# them, but they were a SIBLING of `metrics` in its result and the agent loop
# keeps only `metrics` (`node.metrics = eval_result["metrics"]`) — so they were
# dropped on every node and both fields were structurally empty on every run.

_RATIONALES = {
    "measurement_validity": "no baseline was measured at all",
    "comparative_rigor": "only one configuration was compared",
    "clarity_of_contribution": "the claim is stated clearly",
}
_SCORES = {"measurement_validity": 0.2, "comparative_rigor": 0.55,
           "clarity_of_contribution": 0.9}


def test_rationales_populate_concerns_and_next_steps():
    from types import SimpleNamespace as NS

    from ari.orchestrator.node_report.builder import (
        derive_self_assessment_from_evaluator,
    )

    node = NS(has_real_data=True)
    sa, hints = derive_self_assessment_from_evaluator(
        {"axis_scores": _SCORES, "axis_rationales": _RATIONALES}, node,
    )
    assert any("measurement_validity" in c for c in sa.get("concerns") or [])
    assert any("comparative_rigor" in h for h in hints)
    # a high-scoring axis is not an "improve me" hint
    assert not any("clarity_of_contribution" in x
                   for x in list(sa.get("concerns") or []) + list(hints))


def test_the_rationales_survive_the_metrics_channel():
    """They must ride the SAME dict as `_axis_scores`, which is the only thing
    the agent loop copies onto the node."""
    from pathlib import Path

    import ari.evaluator.llm_evaluator as _ev

    src = Path(_ev.__file__).read_text(encoding="utf-8")
    assert 'extracted_metrics["_axis_rationales"]' in src, (
        "the rationales are not stashed on the metrics dict, so they are "
        "dropped when the loop does node.metrics = eval_result['metrics']"
    )


def test_the_loop_hands_the_rationales_to_the_report():
    from pathlib import Path

    import ari.cli.bfts_loop as _b

    src = Path(_b.__file__).read_text(encoding="utf-8")
    assert '"axis_rationales": result.metrics.get(' in src


def test_inline_result_blob_is_marked_not_a_phantom_file(tmp_path: Path) -> None:
    """agent/loop.py emits {"type": "result", "stdout": ...} for captured tool
    output — an inline blob with no file. The builder keeps a display-only
    filename (schema requires it) but MUST mark it ``inline`` so the memory
    audit skips it instead of reporting {work_dir}/result as a missing file on
    every run. A dict artifact with a real filename is never marked inline."""
    inline = nr._artifact_to_record(
        {"type": "result", "stdout": "captured output"}, tmp_path)
    assert inline == {"filename": "result", "role": "unknown", "inline": True}

    (tmp_path / "metrics.csv").write_text("a,b\n1,2\n")
    real = nr._artifact_to_record({"filename": "metrics.csv"}, tmp_path)
    assert "inline" not in real
    assert real["filename"] == "metrics.csv" and "sha256" in real


def test_an_unhashable_produced_file_is_recorded_not_dropped(tmp_path):
    """A file the node PRODUCED whose sha256 cannot be read (foreign-uid
    container output, an ENOENT race, an I/O error) used to be dropped from all
    four buckets, so a node whose only output was unhashable looked like a node
    that changed nothing — the sterile gate then logged "no files vs parent"
    (a positive falsehood) and clamped the score to 0 with has_real_data=False,
    while the provenance audit built no ArtifactRef and the run read as fully
    audited."""
    from unittest import mock

    import ari.orchestrator.node_report.builder as B

    parent = tmp_path / "parent"; parent.mkdir()
    child = tmp_path / "child"; child.mkdir()
    (child / "results.csv").write_text("tile,gbps\n32,16.3\n")

    real = B._sha256_file

    def _flaky(path, **kw):
        if path.name == "results.csv":
            raise OSError("Permission denied")
        return real(path, **kw)

    with mock.patch.object(B, "_sha256_file", _flaky):
        fc = B.compute_files_changed(parent, child)

    assert fc["added"] == [] and fc["modified"] == [] and fc["deleted"] == []
    assert fc["unhashable"] == [
        {"path": "results.csv", "error": "OSError: Permission denied"}]


def test_files_changed_omits_unhashable_when_everything_hashes(tmp_path):
    """Additive: a clean report is byte-identical to before — no empty key."""
    from ari.orchestrator.node_report.builder import compute_files_changed

    parent = tmp_path / "p"; parent.mkdir()
    child = tmp_path / "c"; child.mkdir()
    (child / "out.txt").write_text("x")
    fc = compute_files_changed(parent, child)
    assert "unhashable" not in fc
    assert [e["path"] for e in fc["added"]] == ["out.txt"]


def test_an_unreadable_parent_does_not_fabricate_a_modification(tmp_path):
    """The inverse of the produced-file case: if the PARENT copy cannot be read
    we do not know whether the file changed. Emitting `modified` with
    sha256_before="" fabricated a diff even when child and parent were
    byte-identical, so a reader saw "modified kernel.c from <unknown> to ..."
    for a change that never happened."""
    from unittest import mock

    import ari.orchestrator.node_report.builder as B

    parent = tmp_path / "p"; parent.mkdir()
    child = tmp_path / "c"; child.mkdir()
    (parent / "kernel.c").write_text("int main(){}")
    (child / "kernel.c").write_text("int main(){}")   # IDENTICAL

    real = B._sha256_file

    def _flaky(path, **kw):
        if path.parent == parent:
            raise OSError("Input/output error")
        return real(path, **kw)

    with mock.patch.object(B, "_sha256_file", _flaky):
        fc = B.compute_files_changed(parent, child)

    assert fc["modified"] == [], "must not synthesize a diff from a failed parent read"
    assert fc.get("unhashable") and fc["unhashable"][0]["path"] == "kernel.c"
    assert "parent unreadable" in fc["unhashable"][0]["error"]
