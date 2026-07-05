"""3-D 7-point Jacobi stencil measurement harness (handoff study task D) —
measurement CORE.

The stencil is the deliberately *memory-bandwidth bound* counterpart to the
compute-bound GEMM task: each interior update reads 7 values and writes 1 with
almost no arithmetic reuse, so plain OpenMP parallelism saturates the memory
roofline fast (the easy plateau a strong model one-shots). Breaking past it
needs SIMD along the contiguous dimension, spatial cache blocking, NUMA
first-touch, and finally TEMPORAL / time blocking (advance several sweeps over a
cache-resident tile) to cut memory traffic. That long, non-obvious tail leaves a
genuine optimization-QUALITY gradient above the one-shot rung — so the handoff
arms can separate by *how far up the ladder* a node climbs, on a task a strict
reviewer accepts as a performance kernel (pure speed axis, numerical-equivalence
correctness, no NP-hardness, no accuracy tradeoff).

This module owns the fp64 reference oracle (nt naive sweeps), the per-element
nt-scaled correctness bound, the grid shapes the geomean is taken over, and the
per-shape geomean-speedup aggregation. The evaluator generates the field u0; the
agent only supplies the kernel (and may NOT link an external stencil library).

LOGIN-TESTABLE: gen_problem, reference_jacobi, gamma, is_correct, measure_node
with an injected run_kernel. COMPUTE-NODE ONLY: _default_run_kernel (compile +
OpenMP run + timing) — validated on a compute node per the repo rule.

See ari-core/ari/evaluator/stencil_kernels/ and workspace/HARD_TASK_DESIGN.md.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

# PREREG: the fixed grid set (nx, ny, nz, nt) the geomean is taken over. One cube
# plus two anisotropic boxes so a kernel hardcoded to a cube (or to nx==ny==nz)
# fails the others. Sized so the naive single-thread baseline is ~0.3-1.0s
# (memory-bound, measurable, not dominating) and two fp64 buffers fit in a few
# hundred MB. nt sweeps give the temporal-blocking ladder room to pay off.
#
# Env-overridable via ARI_STENCIL_SHAPES (";"-separated "nx,ny,nz,nt" tuples) so
# a sweep can trade wall-clock for a lighter grid WITHOUT changing the committed
# default. The speedup is a RATIO (baseline_time/candidate_time), robust to grid
# size once the grid exceeds cache — so e.g. "160,160,160,16;224,128,128,16;
# 128,128,224,16" evaluates ~8x faster with the same bandwidth-bound science.
def _default_shapes() -> tuple[tuple[int, int, int, int], ...]:
    import os as _os
    spec = _os.environ.get("ARI_STENCIL_SHAPES", "").strip()
    if not spec:
        return ((256, 256, 256, 30), (384, 192, 192, 30), (192, 192, 384, 30))
    out: list[tuple[int, int, int, int]] = []
    for grp in spec.split(";"):
        grp = grp.strip()
        if not grp:
            continue
        parts = tuple(int(x) for x in grp.split(","))
        if len(parts) != 4:
            raise ValueError(f"ARI_STENCIL_SHAPES tuple must be nx,ny,nz,nt: {grp!r}")
        out.append(parts)  # type: ignore[arg-type]
    return tuple(out) or ((256, 256, 256, 30), (384, 192, 192, 30), (192, 192, 384, 30))


SHAPES: tuple[tuple[int, int, int, int], ...] = _default_shapes()
_FP64_U = 2.0 ** -53  # double-precision unit roundoff
_C_EPS = 8.0          # PREREG correctness constant (same as GEMM/SpMM)
_C0 = 0.5
_CW = 1.0 / 12.0


def gamma(k: int, u: float = _FP64_U) -> float:
    """Backward-stable summation error factor k*u/(1-k*u); inf when k*u>=1."""
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def gen_problem(shape: tuple[int, int, int, int], seed: int = 0):
    """Deterministic fp64 field u0[nx,ny,nz] ~ N(0,1). Returns (u0, nx, ny, nz, nt)."""
    nx, ny, nz, nt = shape
    rng = np.random.default_rng(seed)
    u0 = rng.standard_normal((nx, ny, nz)).astype(np.float64)
    return u0, int(nx), int(ny), int(nz), int(nt)


def reference_jacobi(u0, nx: int, ny: int, nz: int, nt: int):
    """fp64 reference: nt naive Jacobi sweeps, fixed (Dirichlet) boundary planes."""
    u = np.asarray(u0, dtype=np.float64).reshape(nx, ny, nz).copy()
    for _ in range(int(nt)):
        new = u.copy()  # keeps boundary planes fixed = u0 forever
        new[1:-1, 1:-1, 1:-1] = (
            _C0 * u[1:-1, 1:-1, 1:-1]
            + _CW * (u[2:, 1:-1, 1:-1] + u[:-2, 1:-1, 1:-1]
                     + u[1:-1, 2:, 1:-1] + u[1:-1, :-2, 1:-1]
                     + u[1:-1, 1:-1, 2:] + u[1:-1, 1:-1, :-2])
        )
        u = new
    return u


def is_correct(u_cand, u_ref, u0, nt: int, c_eps: float = _C_EPS, u: float = _FP64_U):
    """Per-element check against the nt-scaled bound:
    |u_cand - u_ref| <= c_eps * gamma(7) * max(nt,1) * max|u0|.

    The 7-point update is a convex combination of the field (weights sum to 1,
    all positive), so values stay within [min(u0), max(u0)] and a single sweep's
    rounding is bounded by gamma(7)*max|u|; nt sweeps accumulate ~linearly.
    Returns (ok, max_abs_error)."""
    uc = np.asarray(u_cand, dtype=np.float64).ravel()
    ur = np.asarray(u_ref, dtype=np.float64).ravel()
    if uc.shape != ur.shape:
        return False, float("inf")
    amax = float(np.max(np.abs(np.asarray(u0, dtype=np.float64)))) or 1.0
    bound = c_eps * gamma(7, u) * float(max(int(nt), 1)) * amax
    resid = np.abs(uc - ur)
    ok = bool(np.all(resid <= bound))
    max_abs = float(np.max(resid)) if ur.size else 0.0
    return ok, max_abs


# Frozen scaffolding seeded into each node work_dir so the agent can build/test
# the same way the evaluator does. The evaluator measures against its OWN package
# copies, so a local copy cannot game the score.
_FROZEN_FIXTURES: tuple[str, ...] = (
    "stencil_kernel.h", "stencil_main.c", "baseline_stencil.c", "Makefile", "selftest.c",
)


def kernels_dir() -> str:
    """Absolute path to the packaged stencil kernel fixtures."""
    import os as _os
    return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "stencil_kernels")


def seed_work_dir(work_dir: str) -> list[str]:
    """Seed *work_dir* with the frozen stencil scaffolding + a starter candidate.

    Frozen files are always (re)written from the package; candidate_stencil.c is
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
    cand_dst = _os.path.join(work_dir, "candidate_stencil.c")
    if not _os.path.exists(cand_dst):
        cand_src = _os.path.join(src_dir, "candidate_stencil.c")
        if _os.path.isfile(cand_src):
            _sh.copy2(cand_src, cand_dst)
            written.append("candidate_stencil.c")
    return written


def _default_run_kernel(kind: str, work_dir: str, u0, nx: int, ny: int, nz: int,
                        nt: int, warmup: int, reps: int):
    """Compile + run + time a stencil kernel; return (median_seconds, u_final).

    ``kind="baseline"`` compiles the frozen ``baseline_stencil.c``;
    ``"candidate"`` compiles the agent's ``candidate_stencil.c`` from
    ``work_dir``. IDENTICAL compiler + flags for both (anti-gaming). No external
    library is linked. OMP threads are pinned (reproducible)."""
    import os as _os
    import subprocess as _sub
    import tempfile as _tmp

    kdir = kernels_dir()
    main_c = _os.path.join(kdir, "stencil_main.c")
    kern_c = (_os.path.join(kdir, "baseline_stencil.c") if kind == "baseline"
              else _os.path.join(work_dir or "", "candidate_stencil.c"))
    if not _os.path.isfile(kern_c):
        raise RuntimeError(f"kernel source not found ({kind}): {kern_c}")
    cc = _os.environ.get("ARI_STENCIL_CC", "cc")
    cflags = _os.environ.get("ARI_STENCIL_CFLAGS", "-O3 -fopenmp -march=native").split()

    u0 = np.ascontiguousarray(np.asarray(u0, dtype=np.float64))
    N = int(nx) * int(ny) * int(nz)
    with _tmp.TemporaryDirectory() as td:
        exe = _os.path.join(td, "kernel.exe")
        compile_cmd = [cc, *cflags, f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"]
        cp = _sub.run(compile_cmd, capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(f"compile failed ({kind}): {cp.stderr.strip()[-600:]}")
        prob = _os.path.join(td, "problem.bin")
        outf = _os.path.join(td, "u.bin")
        with open(prob, "wb") as fh:
            np.array([nx, ny, nz, nt], dtype=np.int32).tofile(fh)
            u0.tofile(fh)
        run_env = dict(_os.environ)
        run_env["OMP_NUM_THREADS"] = _os.environ.get("ARI_STENCIL_THREADS", "16")
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
        u = np.fromfile(outf, dtype=np.float64, count=N).reshape(nx, ny, nz)
    return median, u


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    shapes: tuple[tuple[int, int, int, int], ...] = SHAPES,
    seed: int = 0,
    warmup: int = 1,
    reps: int = 3,
) -> dict:
    """Measure a node's candidate stencil against the fixed grid set.

    Returns the dict DeterministicEvaluator._score consumes:
    ``{"compile_ok", "families": {name: {"speedup", "valid", ...}}, "reason"}``.
    """
    run = run_kernel or _default_run_kernel
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"
    for shape in shapes:
        nx, ny, nz, nt = (int(s) for s in shape)
        name = f"{nx}x{ny}x{nz}t{nt}"
        u0, nx, ny, nz, nt = gen_problem(shape, seed=seed)
        u_ref = reference_jacobi(u0, nx, ny, nz, nt)
        try:
            t_cand, u_cand = run("candidate", work_dir, u0, nx, ny, nz, nt, warmup, reps)
            t_base, _ = run("baseline", work_dir, u0, nx, ny, nz, nt, warmup, reps)
        except Exception as e:
            compile_ok = False
            reason = f"kernel run failed on {name}: {e}"
            out_families[name] = {"speedup": 0.0, "valid": False}
            continue
        ok, max_abs = is_correct(u_cand, u_ref, u0, nt)
        speedup = (t_base / t_cand) if (t_cand and t_cand > 0) else 0.0
        out_families[name] = {
            "speedup": float(speedup), "valid": bool(ok),
            "max_abs_error": max_abs,
        }
    return {"compile_ok": compile_ok, "families": out_families, "reason": reason}
