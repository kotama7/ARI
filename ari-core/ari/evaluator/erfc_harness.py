"""Accuracy-coverage measurement harness (handoff study task B — the Goldilocks
task). The agent implements ``double myerfc(double x)`` (= erfc, library erf/erfc
forbidden) to relative tolerance across a WIDE domain; the score is the FRACTION
of hidden test points within tolerance.

Why this is the "Goldilocks" task (validated, gpt-5.2 4-round trajectory
6%→4%→65%→99.6%): unlike the kernel-speed tasks (SpMM/GEMM) which have a short
ladder and a hard ceiling a strong model one-shots, erfc has a LONG, GRADED,
CUMULATIVE ladder — distinct domain regions (center / mid / tail / deep tail)
must each be conquered with a different numerical regime (series, asymptotic,
continued fraction), and the tail catastrophically cancels so it cannot be
one-shot. Progress accumulates region-by-region, so a child that inherits the
parent's partial implementation + per-region diagnostics can climb faster —
i.e. this is where handoff content can actually matter.

Score = fraction of hidden points with relative error < TOL (naturally in [0,1];
no speedup/log normalization needed). LOGIN-TESTABLE (pure numpy/scipy +
optional compile). The compile/run of the C candidate is the only compute step.
"""
from __future__ import annotations

import os
from typing import Any, Callable

import numpy as np

# PREREG: fixed domain, tolerance, and the hidden test grid (regions the score
# is computed over). The agent does NOT see these points — only per-region pass
# rates via the seeded selftest, forcing iterative discovery.
DOMAIN: tuple[float, float] = (-5.0, 26.0)
TOL: float = 1e-9
REGIONS: tuple[tuple[float, float, str], ...] = (
    (-5.0, 2.0, "center"),
    (2.0, 6.0, "mid"),
    (6.0, 15.0, "tail"),
    (15.0, 26.0, "deeptail"),
)


def _ref_erfc(x):
    from scipy.special import erfc as _erfc
    return _erfc(np.asarray(x, dtype=np.float64))


SELFTEST_SEED = 9173  # seeded into ref_points.csv; DISTINCT from eval seeds so a
                      # candidate cannot pass by hardcoding the self-test points.


def gen_points(seed: int = 0, n_per_region: int = 60):
    """Region-stratified hidden test points (log-spaced in the tail where erfc
    spans many decades). ``seed`` jitters each point WITHIN its region so the
    self-test and the evaluator use independent point sets — only a genuinely
    accurate myerfc generalizes; a lookup table tuned to one set fails the other."""
    rng = np.random.default_rng(seed)
    pts = []
    for lo, hi, _name in REGIONS:
        if lo > 0:
            base = np.geomspace(max(lo, 1e-6), hi, n_per_region)
        else:
            base = np.linspace(lo, hi, n_per_region)
        # small in-region jitter (fraction of the local spacing), seed-dependent
        span = (hi - lo)
        jit = rng.uniform(-0.4, 0.4, base.size) * (span / n_per_region)
        x = np.clip(base + jit, lo, hi - 1e-12)
        pts.append(x)
    x = np.unique(np.concatenate(pts))
    ref = _ref_erfc(x)
    keep = ref > 0  # representable in double
    return x[keep], ref[keep]


# ---- frozen scaffolding ----------------------------------------------------
_FROZEN_FIXTURES: tuple[str, ...] = (
    "erfc_kernel.h", "erfc_main.c", "baseline_erfc.c", "Makefile", "selftest.c",
)


def kernels_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "erfc_kernels")


def seed_work_dir(work_dir: str) -> list[str]:
    """Seed *work_dir* with the frozen scaffolding + a (poor) starter candidate.
    Frozen files always (re)written; candidate kept when present (child inherits
    its parent's partial implementation). Idempotent."""
    import shutil
    src_dir = kernels_dir()
    os.makedirs(work_dir, exist_ok=True)
    written: list[str] = []
    for name in _FROZEN_FIXTURES:
        src = os.path.join(src_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(work_dir, name))
            written.append(name)
    cand = os.path.join(work_dir, "candidate_erfc.c")
    if not os.path.exists(cand):
        s = os.path.join(src_dir, "candidate_erfc.c")
        if os.path.isfile(s):
            shutil.copy2(s, cand)
            written.append("candidate_erfc.c")
    # Seed the self-test's reference points (DISTINCT seed from the evaluator's),
    # always (re)written so it tracks the current REGIONS/domain.
    try:
        sx, sref = gen_points(seed=SELFTEST_SEED)
        with open(os.path.join(work_dir, "ref_points.csv"), "w") as fh:
            for xv, rv in zip(sx, sref):
                fh.write("%.17e %.17e\n" % (xv, rv))
        written.append("ref_points.csv")
    except Exception:
        pass
    return written


def _default_run_kernel(work_dir: str, x):
    """Compile the agent's candidate_erfc.c against the frozen harness and
    evaluate myerfc at the given points. Returns the candidate's outputs (np)."""
    import subprocess
    import tempfile
    kdir = kernels_dir()
    main_c = os.path.join(kdir, "erfc_main.c")
    kern_c = os.path.join(work_dir or "", "candidate_erfc.c")
    if not os.path.isfile(kern_c):
        raise RuntimeError(f"candidate not found: {kern_c}")
    cc = os.environ.get("ARI_ERFC_CC", "cc")
    cflags = os.environ.get("ARI_ERFC_CFLAGS", "-O2").split()
    with tempfile.TemporaryDirectory() as td:
        exe = os.path.join(td, "erfc.exe")
        cp = subprocess.run([cc, *cflags, f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"],
                            capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(f"compile failed: {cp.stderr.strip()[-600:]}")
        xf = os.path.join(td, "xs.txt")
        with open(xf, "w") as fh:
            fh.write("\n".join("%.17e" % v for v in x))
        rp = subprocess.run([exe, xf], capture_output=True, text=True, timeout=300)
        if rp.returncode != 0:
            raise RuntimeError(f"run failed: {rp.stderr.strip()[-400:]}")
        vals = np.array([float(z) for z in rp.stdout.split()], dtype=np.float64)
    if vals.shape != x.shape:
        raise RuntimeError(f"output count {vals.shape} != points {x.shape}")
    return vals


def measure_node(work_dir: str, *, run_kernel: Callable | None = None,
                 seed: int = 0, tol: float = TOL) -> dict:
    """Compile + grade the candidate. Returns a SCORE-shaped dict (not speedup):
    ``{"compile_ok", "score" (overall pass fraction), "regions": {name: frac},
    "reason"}``. score is naturally in [0,1]."""
    run = run_kernel or _default_run_kernel
    x, ref = gen_points(seed=seed)
    try:
        got = run(work_dir, x)
    except Exception as e:
        return {"compile_ok": False, "score": 0.0, "regions": {}, "reason": f"erfc run failed: {e}"}
    with np.errstate(divide="ignore", invalid="ignore"):
        relerr = np.abs(got - ref) / np.abs(ref)
    ok = np.isfinite(relerr) & (relerr < tol)
    regions: dict[str, float] = {}
    for lo, hi, name in REGIONS:
        mk = (x >= lo) & (x < hi)
        regions[name] = float(ok[mk].mean()) if mk.any() else 1.0
    return {"compile_ok": True, "score": float(ok.mean()), "regions": regions,
            "reason": "ok"}
