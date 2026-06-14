"""SpMM measurement harness for the handoff study (B2b) — measurement CORE.

This is the engine ``DeterministicEvaluator.measure_fn`` calls. It owns the
fixed reference oracle (fp64 ``Y = A @ X``), the per-output-element correctness
bound (PREREG eps model), the seeded matrix families, and the per-family
geomean-speedup aggregation — i.e. everything that makes a "valid speedup"
well-defined and un-gameable (the evaluator generates A and X; the agent only
supplies a kernel).

LOGIN-TESTABLE (pure numpy/scipy, validated here): ``gen_matrix``,
``reference_spmm``, ``gamma``, ``is_correct``, and ``measure_node`` with an
injected ``run_kernel``.

COMPUTE-NODE ONLY (NOT validated on a login node — repo rule "validate
environment-dependent logic on a real compute node"): ``_default_run_kernel``
(compile + OpenMP run + timing of the agent's C kernel) and the ``.c`` kernel
fixtures. Those land + are validated separately. Until then ``measure_node``
with the default runner will raise, and DeterministicEvaluator degrades to a
graceful invalid result.

See ari-core/ari/evaluator/Plan.md and ari-core/PREREG_handoff_study.md.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import scipy.sparse as sp

# PREREG: the fixed family set the geomean is taken over.
FAMILIES: tuple[str, ...] = (
    "uniform", "banded", "power_law", "block", "diagonal_dominant", "skewed",
)
_FP64_U = 2.0 ** -53  # double-precision unit roundoff


def gamma(k: int, u: float = _FP64_U) -> float:
    """Backward-stable summation error factor k*u/(1-k*u); inf when k*u>=1."""
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def gen_matrix(family: str, n: int = 512, *, density: float = 0.02,
               seed: int = 0) -> sp.csr_matrix:
    """Deterministic CSR matrix for a named family (seeded; reproducible)."""
    rng = np.random.default_rng(seed)
    fam = family.lower()
    if fam == "uniform":
        A = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal)
    elif fam == "banded":
        bw = max(1, int(n * density))
        diags = [rng.standard_normal(n - abs(o)) for o in range(-bw, bw + 1)]
        A = sp.diags(diags, list(range(-bw, bw + 1)), shape=(n, n)).tocsr()
    elif fam == "diagonal_dominant":
        A = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal).tolil()
        for i in range(n):
            A[i, i] = float(abs(A[i]).sum()) + 1.0
        A = A.tocsr()
    elif fam == "block":
        b = max(1, n // 16)
        blk = sp.random(b, b, density=min(1.0, density * 16), format="csr",
                        random_state=rng, data_rvs=rng.standard_normal)
        A = sp.block_diag([blk] * (n // b), format="csr")
        A = A[:n, :n].tocsr()
    elif fam in ("power_law", "skewed"):
        # row nnz follows a heavy-tailed distribution (a few very dense rows).
        rows, cols, vals = [], [], []
        for i in range(n):
            deg = int(min(n, 1 + rng.pareto(1.5) * n * density))
            cs = rng.choice(n, size=min(deg, n), replace=False)
            rows.extend([i] * len(cs)); cols.extend(cs.tolist())
            vals.extend(rng.standard_normal(len(cs)).tolist())
        A = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    else:
        raise ValueError(f"unknown matrix family: {family}")
    A.eliminate_zeros()
    return A.tocsr()


def reference_spmm(A: sp.csr_matrix, X: np.ndarray) -> np.ndarray:
    """Reference Y = A @ X in fp64 (the correctness ground truth)."""
    return np.asarray(sp.csr_matrix(A).astype(np.float64) @ np.asarray(X, dtype=np.float64))


def is_correct(Y_cand: np.ndarray, Y_ref: np.ndarray, A: sp.csr_matrix,
               X: np.ndarray, *, C: float = 8.0, u: float = _FP64_U) -> tuple[bool, float]:
    """Per-element correctness against the PREREG bound; returns (ok, max_rel_resid).

    Accept iff for every output element ``|Y_cand-Y_ref| <= C * gamma_{nnz_i} *
    (|A| @ |X|)`` where ``nnz_i`` is the nnz of A's row i (the length of that
    output element's summation). Scales the tolerance per-row with row length,
    so legitimate FP-reorderings on dense (power-law) rows are not falsely
    rejected and wrong kernels on short rows are not falsely accepted.
    """
    A = sp.csr_matrix(A)
    Yc = np.asarray(Y_cand, dtype=np.float64)
    Yr = np.asarray(Y_ref, dtype=np.float64)
    if Yc.shape != Yr.shape:
        return False, float("inf")
    nnz_per_row = np.diff(A.indptr)
    g = np.array([gamma(int(k), u) for k in nnz_per_row], dtype=np.float64)
    absA = sp.csr_matrix((np.abs(A.data), A.indices, A.indptr), shape=A.shape)
    bound = C * g[:, None] * (absA @ np.abs(np.asarray(X, dtype=np.float64)))
    resid = np.abs(Yc - Yr)
    ok = bool(np.all(resid <= bound))
    denom = np.abs(Yr)
    max_rel = float(np.max(resid / np.where(denom > 0, denom, np.inf))) if Yr.size else 0.0
    return ok, max_rel


# Frozen scaffolding every node work_dir needs so the AGENT can compile-test its
# candidate exactly as the evaluator does. The evaluator still measures against
# its OWN package copies (see _default_run_kernel below), so seeding a node a
# local copy of the harness cannot game the score.
_FROZEN_FIXTURES: tuple[str, ...] = (
    "spmm_kernel.h", "spmm_main.c", "baseline_spmm.c", "Makefile", "selftest.c",
)


def kernels_dir() -> str:
    """Absolute path to the packaged SpMM kernel fixtures."""
    import os as _os
    return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "spmm_kernels")


def seed_work_dir(work_dir: str) -> list[str]:
    """Seed *work_dir* with the frozen SpMM scaffolding + a starter candidate.

    Without this the agent has no ``spmm_kernel.h`` / ``spmm_main.c`` to compile
    against and flails (writes its own broken ``main()``), so every node fails.

    The frozen files (header, timing harness, baseline, Makefile) are always
    (re)written from the package fixtures so a node always builds against the
    canonical harness — even if a parent left a modified copy. ``candidate_spmm.c``
    is written ONLY when absent, so a code-inheriting child keeps its parent's
    candidate. Idempotent; returns the basenames written.
    """
    import os as _os
    import shutil as _sh
    src_dir = kernels_dir()
    _os.makedirs(work_dir, exist_ok=True)
    written: list[str] = []
    for name in _FROZEN_FIXTURES:
        src = _os.path.join(src_dir, name)
        if _os.path.isfile(src):
            _sh.copy2(src, _os.path.join(work_dir, name))
            written.append(name)
    cand_dst = _os.path.join(work_dir, "candidate_spmm.c")
    if not _os.path.exists(cand_dst):
        cand_src = _os.path.join(src_dir, "candidate_spmm.c")
        if _os.path.isfile(cand_src):
            _sh.copy2(cand_src, cand_dst)
            written.append("candidate_spmm.c")
    return written


def _default_run_kernel(kind: str, work_dir: str, A, X, warmup: int, reps: int):
    """Compile + run + time a SpMM kernel; return (median_seconds, Y).

    ``kind="baseline"`` compiles the frozen ``baseline_spmm.c``; ``"candidate"``
    compiles the agent's ``candidate_spmm.c`` from ``work_dir``. IDENTICAL
    compiler + flags for both (anti-gaming). Mechanics (compile / run /
    correctness) are smoke-tested on a login node; TIMING representativeness
    (W warmup / R reps median, OpenMP scaling) must be validated on a compute
    node (repo rule), so production runs of the study run on compute nodes.
    """
    import os as _os
    import subprocess as _sub
    import tempfile as _tmp

    kdir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "spmm_kernels")
    main_c = _os.path.join(kdir, "spmm_main.c")
    kern_c = (_os.path.join(kdir, "baseline_spmm.c") if kind == "baseline"
              else _os.path.join(work_dir or "", "candidate_spmm.c"))
    if not _os.path.isfile(kern_c):
        raise RuntimeError(f"kernel source not found ({kind}): {kern_c}")
    cc = _os.environ.get("ARI_SPMM_CC", "cc")
    cflags = _os.environ.get("ARI_SPMM_CFLAGS", "-O3 -fopenmp").split()

    Acsr = sp.csr_matrix(A).astype(np.float64)
    Acsr.sort_indices()
    Xc = np.ascontiguousarray(np.asarray(X, dtype=np.float64))
    n, m = int(Acsr.shape[0]), int(Acsr.shape[1])
    k = int(Xc.shape[1])
    nnz = int(Acsr.nnz)
    with _tmp.TemporaryDirectory() as td:
        exe = _os.path.join(td, "kernel.exe")
        compile_cmd = [cc, *cflags, f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"]
        cp = _sub.run(compile_cmd, capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(f"compile failed ({kind}): {cp.stderr.strip()[-600:]}")
        prob = _os.path.join(td, "problem.bin")
        outf = _os.path.join(td, "y.bin")
        with open(prob, "wb") as fh:
            np.array([n, m, k, nnz], dtype=np.int32).tofile(fh)
            Acsr.indptr.astype(np.int32).tofile(fh)
            Acsr.indices.astype(np.int32).tofile(fh)
            Acsr.data.astype(np.float64).tofile(fh)
            Xc.tofile(fh)
        rp = _sub.run([exe, prob, outf, str(int(warmup)), str(int(reps))],
                      capture_output=True, text=True, timeout=900)
        if rp.returncode != 0:
            raise RuntimeError(f"run failed ({kind}): {rp.stderr.strip()[-600:]}")
        median = None
        for line in rp.stdout.splitlines():
            if line.startswith("median_sec="):
                median = float(line.split("=", 1)[1])
        if median is None:
            raise RuntimeError(f"no timing in stdout ({kind}): {rp.stdout[-200:]}")
        Y = np.fromfile(outf, dtype=np.float64).reshape(n, k)
    return median, Y


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    families: tuple[str, ...] = FAMILIES,
    n: int = 512,
    k: int = 32,
    seed: int = 0,
    warmup: int = 3,
    reps: int = 10,
) -> dict:
    """Measure a node's candidate SpMM kernel against the fixed family set.

    ``run_kernel(kind, work_dir, A, X, warmup, reps) -> (median_seconds, Y)``
    compiles+runs the baseline ('baseline') or the agent's candidate
    ('candidate') and returns its timing + output. The evaluator owns A and X
    (the agent cannot supply them — anti-gaming). Returns the dict
    DeterministicEvaluator._score consumes.
    """
    run = run_kernel or _default_run_kernel
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"
    for fam in families:
        A = gen_matrix(fam, n, seed=seed)
        X = np.random.default_rng(seed + 1).standard_normal((A.shape[1], k))
        Y_ref = reference_spmm(A, X)
        try:
            # Candidate first: a missing/broken candidate fails fast without
            # paying for a baseline compile.
            t_cand, Y_cand = run("candidate", work_dir, A, X, warmup, reps)
            t_base, _ = run("baseline", work_dir, A, X, warmup, reps)
        except Exception as e:
            compile_ok = False
            reason = f"kernel run failed on {fam}: {e}"
            out_families[fam] = {"speedup": 0.0, "valid": False}
            continue
        ok, max_rel = is_correct(Y_cand, Y_ref, A, X)
        speedup = (t_base / t_cand) if (t_cand and t_cand > 0) else 0.0
        out_families[fam] = {
            "speedup": float(speedup), "valid": bool(ok),
            "max_relative_error": max_rel,
        }
    return {"compile_ok": compile_ok, "families": out_families, "reason": reason}
