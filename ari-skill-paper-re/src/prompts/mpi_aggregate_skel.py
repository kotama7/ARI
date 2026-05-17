"""MPI result aggregation skeleton — auto-injected by ari-skill-paper-re
when ``reproduce_contract.execution_profile.kind`` ∈ {"mpi", "mpi_gpu"}.

The replicator agent should:

    1. Import or copy ``gather_and_write_csv`` from this file into
       reproduce.sh's CSV-emit step (or call this module directly).
    2. Construct a per-rank dict of metric -> value matching the rubric's
       ``execution_profile.metric_columns`` exactly.
    3. Pass it to ``gather_and_write_csv(local_metrics, csv_path)``.

Rank 0 performs MPI gather, sorts by rank, writes a single CSV
(``submission/results/<file>.csv`` by convention). The ``rank`` and
``paper_paper_scale_point`` columns are always emitted first; the rest of
the header is the union of dict keys seen on rank 0.

Per-rank logs are NOT this module's responsibility — write them
separately to ``submission/logs/rank-<rank>.log`` if needed.
"""

from __future__ import annotations

import csv
import os
import sys


def _rank_size():
    """Return ``(comm, rank, size)`` using mpi4py if available, else
    fall back to ``SLURM_PROCID`` / ``SLURM_NTASKS`` env vars (works for
    plain ``srun`` invocations without MPI bindings) so this helper still
    produces a useful CSV under non-MPI parallel launches.
    """
    try:
        from mpi4py import MPI  # type: ignore[import-not-found]
        comm = MPI.COMM_WORLD
        return comm, comm.Get_rank(), comm.Get_size()
    except ImportError:
        rank = int(os.environ.get("SLURM_PROCID", "0"))
        size = int(os.environ.get("SLURM_NTASKS", "1"))
        return None, rank, size


def gather_and_write_csv(
    local_metrics: dict,
    csv_path: str,
    *,
    paper_scale: bool = True,
) -> None:
    """Gather per-rank ``local_metrics`` to rank 0 and write a single CSV.

    Args:
        local_metrics: dict of metric_name -> value for THIS rank.
        csv_path: destination CSV path. Parent dirs are created on demand.
        paper_scale: True iff this scale point matches paper's reported
            scale. False = reduced-scale (e.g. 8 ranks vs paper's 8K) when
            ``execution_profile.accepts_reduced_scale`` is true.

    Rank 0 writes the CSV; all other ranks return after gather.
    """
    comm, rank, size = _rank_size()
    if comm is not None:
        rows = comm.gather((rank, dict(local_metrics), paper_scale), root=0)
    else:
        # Non-MPI fallback: each rank writes its own row file and rank 0
        # concatenates. The simple in-memory path only works for size==1.
        if size > 1:
            sys.stderr.write(
                "mpi_aggregate: mpi4py unavailable AND SLURM_NTASKS>1 — "
                "install mpi4py (``pip install --user mpi4py``) or use\n"
                "``srun -n N`` with a PMI-aware MPI; aggregation is not\n"
                "reliable from env-vars alone.\n"
            )
        rows = [(rank, dict(local_metrics), paper_scale)]

    if rank != 0:
        return

    rows = sorted(rows, key=lambda r: r[0])
    metric_keys: list[str] = []
    seen: set = set()
    for _r, m, _p in rows:
        for k in m:
            if k not in seen:
                metric_keys.append(k)
                seen.add(k)
    header = ["rank", "paper_paper_scale_point"] + metric_keys

    out_dir = os.path.dirname(os.path.abspath(csv_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for r, m, ps in rows:
            row = {"rank": r, "paper_paper_scale_point": bool(ps)}
            row.update(m)
            writer.writerow(row)


if __name__ == "__main__":
    # Lightweight smoke when run directly: each rank reports its rank id
    # as ``runtime_sec`` so the resulting CSV is trivially inspectable.
    _comm, _rank, _size = _rank_size()
    sample = {"runtime_sec": float(_rank), "size": _size}
    gather_and_write_csv(sample, csv_path="submission/results/_smoke.csv")
