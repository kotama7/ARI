"""Phase 7 regression — child node work_dir must NOT inherit parent's
output artifacts.

The bug observed in production (run 20260504120448): every child node
re-used its parent's ``results.csv``, ``slurm-*.out``, ``run.log`` etc.
unchanged, so 10 BFTS nodes all reported the same numbers from a single
SLURM run. The ReAct agent saw the result files already on disk and
treated the experiment as already done.

Fix: inherit code / scripts / configs but blacklist output artifacts so
the child must regenerate them.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest


# Mirror the blacklist that lives in ``cli.py``. Keeping a local copy lets
# the tests assert the contract without importing the entire run loop.
_OUTPUT_BLACKLIST = (
    "results.csv", "results_*.csv", "*_results.csv",
    "result.csv", "metrics.csv",
    "run.log", "run_*.log", "*.run.log",
    "slurm-*.out", "slurm-*.err",
    "stdout.txt", "stderr.txt", "out.txt", "err.txt",
    "*.metrics.json", "metrics.json",
    "node_report.json",
)


def _is_output_artifact(rel_path: str, name: str) -> bool:
    for pat in _OUTPUT_BLACKLIST:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def test_blacklist_catches_results_csv():
    assert _is_output_artifact("results.csv", "results.csv")


def test_blacklist_catches_slurm_outputs():
    assert _is_output_artifact("slurm-1282.out", "slurm-1282.out")
    assert _is_output_artifact("slurm-9999.err", "slurm-9999.err")


def test_blacklist_catches_run_logs():
    assert _is_output_artifact("run.log", "run.log")
    assert _is_output_artifact("run_42.log", "run_42.log")
    assert _is_output_artifact("foo.run.log", "foo.run.log")


def test_blacklist_catches_metrics_json():
    assert _is_output_artifact("metrics.json", "metrics.json")
    assert _is_output_artifact("foo.metrics.json", "foo.metrics.json")


def test_blacklist_catches_node_report():
    """node_report.json is itself a derived artifact; the child rebuilds
    its own from scratch so we must not inherit the parent's."""
    assert _is_output_artifact("node_report.json", "node_report.json")


def test_blacklist_lets_source_code_through():
    """Source / scripts / configs MUST be inherited so the child can
    build on the parent."""
    assert not _is_output_artifact("spmm_envelope.cpp", "spmm_envelope.cpp")
    assert not _is_output_artifact("run_spmm.sh", "run_spmm.sh")
    assert not _is_output_artifact("Makefile", "Makefile")
    assert not _is_output_artifact("config.yaml", "config.yaml")
    assert not _is_output_artifact("data/input.bin", "input.bin")
    assert not _is_output_artifact("README.md", "README.md")


def test_blacklist_lets_compiled_binary_through():
    """Compiled executables are an in-between case: technically derived
    but expensive to rebuild. Inherit so the child can re-run without
    a rebuild step (it will re-execute and produce its own results)."""
    assert not _is_output_artifact("spmm_envelope", "spmm_envelope")
    assert not _is_output_artifact("a.out", "a.out")


def test_inheritance_simulation(tmp_path: Path):
    """Walk the parent dir like cli.py does, copy with blacklist, and
    verify only the right files end up in the child."""
    parent = tmp_path / "parent_node"
    child = tmp_path / "child_node"
    parent.mkdir()
    child.mkdir()

    # Source / scripts / configs — inherited.
    (parent / "spmm_envelope.cpp").write_text("// source")
    (parent / "run_spmm.sh").write_text("#!/bin/bash\n./spmm")
    (parent / "config.yaml").write_text("k: 64\n")
    (parent / "spmm_envelope").write_bytes(b"\x7fELF binary stub")
    # Output artifacts — blacklisted.
    (parent / "results.csv").write_text("kernel,K,GFLOP/s\nbase,1,0.5\n")
    (parent / "run.log").write_text("[INFO] kernel ran\n")
    (parent / "slurm-1282.out").write_text("Job 1282 OK\n")
    (parent / "metrics.json").write_text('{"GFLOP_per_s": 17.8}')
    (parent / "node_report.json").write_text('{"node_id": "p"}')

    # Simulate cli.py inheritance loop.
    import shutil
    skipped = 0
    for src in parent.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(parent)
        if _is_output_artifact(str(rel), src.name):
            skipped += 1
            continue
        dst = child / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))

    inherited = sorted(p.name for p in child.rglob("*") if p.is_file())
    # Source / scripts / configs / binary all inherited.
    assert "spmm_envelope.cpp" in inherited
    assert "run_spmm.sh" in inherited
    assert "config.yaml" in inherited
    assert "spmm_envelope" in inherited
    # Output artifacts NOT inherited — child must re-generate.
    assert "results.csv" not in inherited
    assert "run.log" not in inherited
    assert "slurm-1282.out" not in inherited
    assert "metrics.json" not in inherited
    assert "node_report.json" not in inherited
    # Skipped count matches blacklisted file count.
    assert skipped == 5


def test_inheritance_preserves_subdirectories(tmp_path: Path):
    """Source under nested dirs (e.g. src/lib.cpp) is inherited even
    when its sibling at top-level is blacklisted."""
    parent = tmp_path / "p"; parent.mkdir()
    child = tmp_path / "c"; child.mkdir()
    (parent / "src").mkdir()
    (parent / "src" / "lib.cpp").write_text("// lib")
    (parent / "results.csv").write_text("blacklisted")

    import shutil
    for src in parent.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(parent)
        if _is_output_artifact(str(rel), src.name):
            continue
        dst = child / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))

    assert (child / "src" / "lib.cpp").exists()
    assert not (child / "results.csv").exists()


# ---------------------------------------------------------------------------
# Phase 7-2: sterile node detection
# ---------------------------------------------------------------------------


def test_compute_files_changed_detects_sterile_child(tmp_path: Path):
    """When a child work_dir is bytewise identical to its parent (no
    additions, no modifications, no deletions), compute_files_changed
    returns empty added/modified/deleted lists. This is the signal
    cli.py uses to clamp the node's scientific_score and skip
    further BFTS expansion from this chain."""
    from ari.orchestrator.node_report import compute_files_changed

    parent = tmp_path / "parent"; parent.mkdir()
    child = tmp_path / "child"; child.mkdir()

    # Set up identical contents in both dirs.
    (parent / "src.cpp").write_text("// code")
    (parent / "results.csv").write_text("kernel,K,GFLOPs\nbase,1,0.5\n")
    import shutil
    for f in parent.iterdir():
        shutil.copy2(str(f), str(child / f.name))

    fc = compute_files_changed(parent, child)
    assert len(fc.get("added") or []) == 0
    assert len(fc.get("modified") or []) == 0
    assert len(fc.get("deleted") or []) == 0
    # All inherited unchanged.
    assert len(fc.get("inherited_unchanged") or []) == 2


def test_compute_files_changed_detects_real_child_work(tmp_path: Path):
    """A child that actually wrote new code or fresh results shows
    up as added / modified — the negation of the sterile case above."""
    from ari.orchestrator.node_report import compute_files_changed

    parent = tmp_path / "parent"; parent.mkdir()
    child = tmp_path / "child"; child.mkdir()

    (parent / "src.cpp").write_text("// v1")
    import shutil
    shutil.copy2(str(parent / "src.cpp"), str(child / "src.cpp"))
    # Child modifies the source AND adds a new result.
    (child / "src.cpp").write_text("// v2 — child evolved this")
    (child / "results.csv").write_text("kernel,K,GFLOPs\nimproved,1,1.7\n")

    fc = compute_files_changed(parent, child)
    assert len(fc.get("added") or []) == 1
    assert (fc["added"][0]["path"]
            if isinstance(fc["added"][0], dict)
            else fc["added"][0]) in ("results.csv",)
    assert len(fc.get("modified") or []) == 1
