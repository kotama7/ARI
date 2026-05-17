"""Unit smoke for ``prompts/mpi_aggregate_skel.py`` — the skeleton injected
into ``submission/`` whenever ``execution_profile.kind`` ∈ {"mpi", "mpi_gpu"}.

We exercise the rank-0 / fallback path without an actual MPI runtime by
patching ``SLURM_PROCID`` / ``SLURM_NTASKS`` and verifying the generated
CSV has the schema the rubric grader expects.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKEL = ROOT / "src" / "prompts" / "mpi_aggregate_skel.py"


def _import_skel():
    spec = importlib.util.spec_from_file_location("mpi_aggregate_skel", SKEL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mpi_aggregate_skel"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_skel_exists_and_imports():
    assert SKEL.is_file()
    mod = _import_skel()
    assert hasattr(mod, "gather_and_write_csv")
    assert hasattr(mod, "_rank_size")


def test_single_rank_fallback_writes_csv(tmp_path, monkeypatch):
    """Rank 0 / size 1 fallback (no mpi4py): writes a one-row CSV with the
    rank + paper_paper_scale_point columns + the user metrics."""
    mod = _import_skel()
    # Force the env-var fallback by simulating mpi4py absence:
    monkeypatch.setitem(sys.modules, "mpi4py", None)
    # Re-import to pick up the masked module:
    import importlib
    sys.modules.pop("mpi_aggregate_skel", None)
    mod = _import_skel()

    monkeypatch.setenv("SLURM_PROCID", "0")
    monkeypatch.setenv("SLURM_NTASKS", "1")
    csv_path = tmp_path / "out" / "results.csv"
    mod.gather_and_write_csv(
        {"runtime_sec": 4.2, "gflops": 12.5},
        str(csv_path),
        paper_scale=True,
    )
    assert csv_path.is_file()
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["rank"] == "0"
    assert rows[0]["paper_paper_scale_point"] == "True"
    assert rows[0]["runtime_sec"] == "4.2"
    assert rows[0]["gflops"] == "12.5"


def test_csv_header_order_rank_first(tmp_path, monkeypatch):
    """Header order: rank, paper_paper_scale_point, then user metric keys
    in insertion order (Python dict preserves)."""
    monkeypatch.setitem(sys.modules, "mpi4py", None)
    sys.modules.pop("mpi_aggregate_skel", None)
    mod = _import_skel()
    monkeypatch.setenv("SLURM_PROCID", "0")
    monkeypatch.setenv("SLURM_NTASKS", "1")
    csv_path = tmp_path / "r.csv"
    mod.gather_and_write_csv(
        {"nodes": 4, "ranks": 32, "runtime_sec": 1.0, "gflops": 99.9},
        str(csv_path),
    )
    with csv_path.open() as f:
        header = f.readline().strip().split(",")
    assert header == [
        "rank", "paper_paper_scale_point",
        "nodes", "ranks", "runtime_sec", "gflops",
    ]
