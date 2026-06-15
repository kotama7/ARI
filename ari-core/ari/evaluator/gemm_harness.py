"""Dense GEMM measurement harness (handoff study task A) — measurement CORE.

GEMM (C = A·B, dense, fp64) is the deliberately *compute-bound* counterpart to
the SpMM task: two independent insights — cache-friendly loop order (ikj) and
OpenMP parallelism — compound multiplicatively (each ~tens×, together ~hundreds×
over the naive ijl baseline), with blocking/SIMD on top. That gives a genuine
multi-rung optimization-QUALITY gradient (unlike SpMM's parallelize-or-not
cliff), so the handoff arms can separate by *how far up the ladder* a node gets.

This module owns the fp64 reference oracle, the per-output-element correctness
bound (contraction length p), the problem shapes the geomean is taken over, and
the per-shape geomean-speedup aggregation. The evaluator generates A and B; the
agent only supplies the kernel (and may NOT link BLAS — the build links none).

LOGIN-TESTABLE: gen_problem, reference_gemm, gamma, is_correct, measure_node with
an injected run_kernel. COMPUTE-NODE ONLY: _default_run_kernel (compile + OpenMP
run + timing) — validated on a compute node per the repo rule.

See ari-core/ari/evaluator/gemm_kernels/ and workspace/HARD_TASK_DESIGN.md.
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

# PREREG: the fixed shape set (n, p, m) the geomean is taken over. Square +
# tall + fat so a kernel hardcoded to one shape (or to n==m==p) fails the others.
# Sized so the naive ijl baseline is ~0.1-0.4s (measurable, not dominating).
SHAPES: tuple[tuple[int, int, int], ...] = (
    (512, 512, 512),
    (1024, 256, 256),
    (256, 256, 1024),
)
_FP64_U = 2.0 ** -53  # double-precision unit roundoff
_C_EPS = 8.0          # PREREG correctness constant (same as SpMM)


def gamma(k: int, u: float = _FP64_U) -> float:
    """Backward-stable summation error factor k*u/(1-k*u); inf when k*u>=1."""
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def gen_problem(shape: tuple[int, int, int], seed: int = 0):
    """Deterministic dense (A[n,p], B[p,m]) in [-1, 1)."""
    n, p, m = shape
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, p)).astype(np.float64)
    B = rng.standard_normal((p, m)).astype(np.float64)
    return A, B


def reference_gemm(A, B):
    """fp64 reference C = A @ B."""
    return np.asarray(A, dtype=np.float64) @ np.asarray(B, dtype=np.float64)


def is_correct(C_cand, C_ref, A, B, c_eps: float = _C_EPS, u: float = _FP64_U):
    """Per-element check against the contraction-length-scaled bound:
    |C_cand - C_ref| <= c_eps * gamma(p) * (|A| @ |B|). Returns (ok, max_rel)."""
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    p = int(A.shape[1])
    g = gamma(p, u)
    bound = c_eps * g * (np.abs(A) @ np.abs(B))
    Cc = np.asarray(C_cand, dtype=np.float64)
    Cr = np.asarray(C_ref, dtype=np.float64)
    if Cc.shape != Cr.shape:
        return False, float("inf")
    resid = np.abs(Cc - Cr)
    ok = bool(np.all(resid <= bound))
    denom = np.abs(Cr)
    max_rel = float(np.max(resid / np.where(denom > 0, denom, np.inf))) if Cr.size else 0.0
    return ok, max_rel


# Frozen scaffolding seeded into each node work_dir so the agent can build/test
# the same way the evaluator does. The evaluator measures against its OWN package
# copies, so a local copy cannot game the score.
_FROZEN_FIXTURES: tuple[str, ...] = (
    "gemm_kernel.h", "gemm_main.c", "baseline_gemm.c", "Makefile", "selftest.c",
)


def kernels_dir() -> str:
    """Absolute path to the packaged GEMM kernel fixtures."""
    import os as _os
    return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "gemm_kernels")


def seed_work_dir(work_dir: str) -> list[str]:
    """Seed *work_dir* with the frozen GEMM scaffolding + a starter candidate.

    Frozen files are always (re)written from the package; candidate_gemm.c is
    written only when absent (so a code-inheriting child keeps its parent's
    candidate). Idempotent; returns the basenames written."""
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
    cand_dst = _os.path.join(work_dir, "candidate_gemm.c")
    if not _os.path.exists(cand_dst):
        cand_src = _os.path.join(src_dir, "candidate_gemm.c")
        if _os.path.isfile(cand_src):
            _sh.copy2(cand_src, cand_dst)
            written.append("candidate_gemm.c")
    return written


def _default_run_kernel(kind: str, work_dir: str, A, B, warmup: int, reps: int):
    """Compile + run + time a GEMM kernel; return (median_seconds, C).

    ``kind="baseline"`` compiles the frozen ``baseline_gemm.c``; ``"candidate"``
    compiles the agent's ``candidate_gemm.c`` from ``work_dir``. IDENTICAL
    compiler + flags for both (anti-gaming). No BLAS is linked. OMP threads are
    pinned (reproducible, where parallelism actually pays off)."""
    import os as _os
    import subprocess as _sub
    import tempfile as _tmp

    kdir = kernels_dir()
    main_c = _os.path.join(kdir, "gemm_main.c")
    kern_c = (_os.path.join(kdir, "baseline_gemm.c") if kind == "baseline"
              else _os.path.join(work_dir or "", "candidate_gemm.c"))
    if not _os.path.isfile(kern_c):
        raise RuntimeError(f"kernel source not found ({kind}): {kern_c}")
    cc = _os.environ.get("ARI_GEMM_CC", "cc")
    cflags = _os.environ.get("ARI_GEMM_CFLAGS", "-O3 -fopenmp -march=native").split()

    A = np.ascontiguousarray(np.asarray(A, dtype=np.float64))
    B = np.ascontiguousarray(np.asarray(B, dtype=np.float64))
    n, p = int(A.shape[0]), int(A.shape[1])
    m = int(B.shape[1])
    with _tmp.TemporaryDirectory() as td:
        exe = _os.path.join(td, "kernel.exe")
        compile_cmd = [cc, *cflags, f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"]
        cp = _sub.run(compile_cmd, capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(f"compile failed ({kind}): {cp.stderr.strip()[-600:]}")
        prob = _os.path.join(td, "problem.bin")
        outf = _os.path.join(td, "c.bin")
        with open(prob, "wb") as fh:
            np.array([n, m, p], dtype=np.int32).tofile(fh)
            A.tofile(fh)
            B.tofile(fh)
        run_env = dict(_os.environ)
        run_env["OMP_NUM_THREADS"] = _os.environ.get("ARI_GEMM_THREADS", "16")
        rp = _sub.run([exe, prob, outf, str(int(warmup)), str(int(reps))],
                      capture_output=True, text=True, timeout=900, env=run_env)
        if rp.returncode != 0:
            raise RuntimeError(f"run failed ({kind}): {rp.stderr.strip()[-600:]}")
        median = None
        for line in rp.stdout.splitlines():
            if line.startswith("median_sec="):
                median = float(line.split("=", 1)[1])
        if median is None:
            raise RuntimeError(f"no timing in stdout ({kind}): {rp.stdout[-200:]}")
        C = np.fromfile(outf, dtype=np.float64).reshape(n, m)
    return median, C


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    shapes: tuple[tuple[int, int, int], ...] = SHAPES,
    seed: int = 0,
    warmup: int = 1,
    reps: int = 3,
) -> dict:
    """Measure a node's candidate GEMM against the fixed shape set.

    Returns the dict DeterministicEvaluator._score consumes:
    ``{"compile_ok", "families": {name: {"speedup", "valid", ...}}, "reason"}``.
    """
    run = run_kernel or _default_run_kernel
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"
    for shape in shapes:
        name = "x".join(str(s) for s in shape)
        A, B = gen_problem(shape, seed=seed)
        C_ref = reference_gemm(A, B)
        try:
            t_cand, C_cand = run("candidate", work_dir, A, B, warmup, reps)
            t_base, _ = run("baseline", work_dir, A, B, warmup, reps)
        except Exception as e:
            compile_ok = False
            reason = f"kernel run failed on {name}: {e}"
            out_families[name] = {"speedup": 0.0, "valid": False}
            continue
        ok, max_rel = is_correct(C_cand, C_ref, A, B)
        speedup = (t_base / t_cand) if (t_cand and t_cand > 0) else 0.0
        out_families[name] = {
            "speedup": float(speedup), "valid": bool(ok),
            "max_relative_error": max_rel,
        }
    return {"compile_ok": compile_ok, "families": out_families, "reason": reason}
