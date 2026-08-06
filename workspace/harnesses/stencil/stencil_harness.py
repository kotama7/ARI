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

import re as _re_flags

from typing import Any, Callable

# v2 CONTROL-SIDE BLAS PINNING. The evaluator computes its fp64 reference with
# numpy immediately before every measured pair, so an unpinned parent BLAS runs
# 48 threads against the candidate's 48 and destroys the measurement. Measured on
# A64FX, 5 reps per case, same candidate: unpinned the candidate's internal time
# spread 14.1x / 21.2x / 28.9x and one case's speedup came out 26.6 instead of
# 313.7; pinned, the spread is 1.0x and the CV is 0.5-1.5%.
#
# The study launcher exported these, but the HARNESS did not - so any direct
# measure_node call (a re-score, a reviewer reproducing, the reference-ladder
# job) silently produced contaminated numbers. A harness must guarantee the
# conditions its own numbers depend on. Set before numpy is imported, because
# OpenBLAS reads them when the library loads; verified again at measure time so a
# caller who deliberately overrides them gets a refusal rather than a bad score.
import os as _os_pin
for _v in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
           "OMP_NUM_THREADS_BLAS", "VECLIB_MAXIMUM_THREADS"):
    _os_pin.environ.setdefault(_v, "1")
_os_pin.environ.setdefault("OPENBLAS_MAIN_FREE", "1")
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
# nt IS 120, NOT 30, AND THAT IS A MEASUREMENT FIX RATHER THAN A SIZE PREFERENCE.
# The candidate allocates its own ping-pong buffers, so the page faults for
# 268 MB of first touch land INSIDE the timed window. Measured on the scored
# grid the window fits t = 50.57 ms + 0.9298 ms per sweep, so the fixed part is
# page-fault handling and it does not shrink - only its SHARE does:
#     nt= 30   78.5 ms   64.4% setup
#     nt= 60  106.4 ms   47.5%
#     nt=120  161.5 ms   31.3%
#     nt=240  273.7 ms   18.5%
# 240 is chosen because the score should measure the stencil, and at 30 it was
# measuring allocation. The measurement gets tighter with it as well (per-launch
# sd 1.024% at nt=30 against 0.504% at nt=120), which is what the sibling
# resolution gate needs. Per SWEEP it is also cheaper: 2.62 ms at nt=30 against
# 1.14 ms at nt=240.
def _default_shapes() -> tuple[tuple[int, int, int, int], ...]:
    import os as _os
    spec = _os.environ.get("ARI_STENCIL_SHAPES", "").strip()
    if not spec:
        return ((256, 256, 256, 240), (384, 192, 192, 240), (192, 192, 384, 240))
    out: list[tuple[int, int, int, int]] = []
    for grp in spec.split(";"):
        grp = grp.strip()
        if not grp:
            continue
        parts = tuple(int(x) for x in grp.split(","))
        if len(parts) != 4:
            raise ValueError(f"ARI_STENCIL_SHAPES tuple must be nx,ny,nz,nt: {grp!r}")
        out.append(parts)  # type: ignore[arg-type]
    return tuple(out) or ((256, 256, 256, 240), (384, 192, 192, 240), (192, 192, 384, 240))


SHAPES: tuple[tuple[int, int, int, int], ...] = _default_shapes()
_FP64_U = 2.0 ** -53  # double-precision unit roundoff
_C_EPS = 8.0          # PREREG correctness constant (same as GEMM/SpMM)
# Forge-guard thresholds (used in measure_node's timing cross-check).
# v2: there is no clamp any more - the wall bound REJECTS a rep, it never floors
# one - so _REJECT_RATIO is the whole forge guard and had to be recalibrated.
# Calibrated on the 82,320 accepted reps of the v1 campaign, where
# tc/wall_lower_bound was distributed as
#     task     min    p0.1     p1     p50
#     gemm    0.095   0.484   0.819  0.882
#     spmm    0.228   0.917   0.942  0.979
#     stencil 0.758   0.981   0.988  0.995
# NOTE the ratio alone does NOT bound the catchable forgery: with an absolute
# slack S, catching a factor F needs T_real > S/(R - 1/F), which diverges as
# F -> 2. At the scored 512-cube gemm shape the smallest catchable forgery was
# measured at 3.98x, and the guard cannot fire at all unless the wall bound
# exceeds S/R = 2 ms. At 0.50 this false-rejects
# 0.11% / 0.01% / 0.00% of real reps - and a false rejection now costs one
# repetition, not the node, because the rule continues instead of breaking.
# Forge guard. v2 REMOVED the wall bound as a rejection criterion; it is recorded
# as a diagnostic only. wall_lower_bound = tc_wall - (tb_wall - tb) subtracts the
# BASELINE's non-kernel wall from the CANDIDATE's, so it measures nothing about
# the candidate's kernel: it is process startup, problem read and output write,
# MEASURED on this machine (20260802_overhead/overhead.json, reps=7, reference
# scored as itself) at 18.9-21.1 ms for gemm, 56.5-91.3 ms for spmm and
# 109.0-127.0 ms for stencil - 80-88% / 81-94% / 32-34% of the frozen
# reference's whole wall. It goes NEGATIVE when the baseline's overhead
# exceeds the candidate's whole wall. Two hardware runs settled it - at ratio
# 0.50 it failed the study's own selected gemm candidate (2 of 3 reps called
# implausible), and at 0.02 it still did, because once the pre-timer region makes
# the kernel genuinely fast (0.8-1.5 ms against the ~60 ms bound THAT RUN saw;
# it predates the v2 sizes, and the bound is configuration-dependent - see the
# measured per-task overheads above) the honest ratio is about 0.015. No threshold separates a fast honest kernel from a forgery,
# because the bound does not measure the kernel.
#
# Forgery is prevented STRUCTURALLY instead, in _compile_kernel: the symbol
# allowlist stops a candidate defining clock_gettime (now_sec is static and not
# shadowable), and the .init_array/.preinit_array/.ctors and IFUNC checks stop
# work being moved before main. A candidate cannot reach the timer any other way:
# CLOCK_MONOTONIC is not settable, and work deferred to a thread after the kernel
# returns leaves the NaN-poisoned output failing the correctness oracle.
# Setting _REJECT_RATIO above 0 re-enables the rejection for experiments.
_REJECT_ABS_SLACK = 0.0
_REJECT_RATIO = 0.0
_C0 = 0.5
_CW = 1.0 / 12.0


# FROZEN reference build flags for the reference translation unit ONLY. Unlike
# the other two tasks this kernel is bandwidth-bound, so the vector flag is worth
# far less here than parallel first touch is — but it is still applied, and the
# set used is RECORDED in every result so a run built with a weaker reference is
# visible in the data instead of silent. The default is chosen by ISA because the
# login node is x86_64 while compute nodes are aarch64 and the harness must stay
# importable on both. Overridable only to port the harness, never to retune it.
def _default_reference_cflags() -> str:
    import platform as _plat

    if _plat.machine() != "aarch64":
        return "-ffast-math"
    return "-march=armv8.2-a+sve -ffast-math"


_REFERENCE_CFLAGS: tuple[str, ...] = tuple(
    _os_pin.environ.get("ARI_STENCIL_REF_CFLAGS", _default_reference_cflags()).split()
)


def _run_timeout_seconds() -> float:
    """Frozen per-process resource limit for candidate and baseline executions."""
    import math
    import os

    try:
        value = float(os.environ.get("ARI_HARNESS_RUN_TIMEOUT_S", "120"))
    except ValueError:
        value = 120.0
    return value if math.isfinite(value) and value > 0.0 else 120.0


class CandidateInvalidError(RuntimeError):
    """The submitted candidate is missing, does not compile, or does not run."""


class HarnessInfrastructureError(RuntimeError):
    """The trusted compiler/baseline/measurement infrastructure failed."""


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
    """fp64 reference: nt naive Jacobi sweeps, fixed (Dirichlet) boundary planes.

    v2: same arithmetic, same operand ORDER, far less memory traffic. v1 did
    ``new = u.copy()`` every sweep and let numpy allocate a fresh temporary for
    each of the five neighbour additions, so a 256-cube 30-sweep reference moved
    roughly 24 GB through the allocator and took 16.1 s. The control-side
    reference is the dominant cost of a stencil node - 133 s per node, about
    33 h over 900 nodes - and it depends only on (shape, input_seed), so it was
    recomputed identically for every node of every arm.

    Two preallocated buffers ping-pong; the boundary planes are Dirichlet and
    therefore already correct in BOTH buffers after the initial copy, so only the
    interior is ever written. The additions are issued in exactly the order the
    v1 expression evaluated them, so the result is bit-identical - verified on
    all three scored shapes.
    """
    src = np.asarray(u0, dtype=np.float64).reshape(nx, ny, nz).copy()
    if int(nt) <= 0:
        return src
    dst = src.copy()                      # boundaries fixed = u0 in both buffers
    interior = (slice(1, -1), slice(1, -1), slice(1, -1))
    s = np.empty_like(src[interior])
    c0u = np.empty_like(s)
    for _ in range(int(nt)):
        np.add(src[2:, 1:-1, 1:-1], src[:-2, 1:-1, 1:-1], out=s)
        np.add(s, src[1:-1, 2:, 1:-1], out=s)
        np.add(s, src[1:-1, :-2, 1:-1], out=s)
        np.add(s, src[1:-1, 1:-1, 2:], out=s)
        np.add(s, src[1:-1, 1:-1, :-2], out=s)
        np.multiply(s, _CW, out=s)
        np.multiply(src[interior], _C0, out=c0u)
        np.add(c0u, s, out=dst[interior])
        src, dst = dst, src
    return src


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
# v2: the work_dir-relative files that actually determine the score. Search
# control uses these to tell a real edit from a pure re-measurement; the v1
# rule diffed the whole work_dir, which never fired because every node
# rewrites results.json. Complete by construction: the evaluator compiles
# this source alone, from a header-less copy, against the sha256-pinned
# kernels dir, plus these flags AND the declared compiler - nothing else in
# the node dir reaches it. candidate_cc.txt was missing from a list whose
# comment claimed completeness, so changing only the compiler read as a pure
# re-measurement while moving the score across a toolchain boundary.
SCORE_INPUTS: tuple[str, ...] = ("candidate_stencil.c", "candidate_flags.txt",
                                  "candidate_cc.txt")


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
    # v2: seed an empty flags file. It was never seeded in v1 although
    # experiment.md tells the agent to write it, so 258 nodes (9.6%) burned
    # a step on "File not found" - the single largest avoidable failure in
    # the corpus. Seeded only when absent, so an inheriting child keeps its
    # parent's flags.
    flags_dst = _os.path.join(work_dir, "candidate_flags.txt")
    if not _os.path.exists(flags_dst):
        with open(flags_dst, "w", encoding="utf-8") as _fh:
            _fh.write("# One optimization flag per line, e.g. -O3\n")
        written.append("candidate_flags.txt")

    cand_dst = _os.path.join(work_dir, "candidate_stencil.c")
    if not _os.path.exists(cand_dst):
        cand_src = _os.path.join(src_dir, "candidate_stencil.c")
        if _os.path.isfile(cand_src):
            _sh.copy2(cand_src, cand_dst)
            written.append("candidate_stencil.c")
    return written


# ── Candidate-declared compile flags (design C: flags are part of the search) ──
# The candidate may declare its OWN optimization flags in ``candidate_flags.txt``
# next to its kernel. They are applied to the CANDIDATE COMPILE ONLY; the frozen
# naive baseline always keeps the fixed default flags, because it is the reference
# point the speedup is measured against. So "speedup" here means
#   (candidate source + candidate flags)  vs  (naive baseline + default flags),
# which is what tuning an HPC kernel actually means.
#
# Flags are screened, because the compile line is otherwise a code-injection and
# link surface: -I/-D/-include could redefine the FROZEN harness, -l/-L/-Wl could
# link a BLAS (explicitly out of scope for this task), -o/-c/-S/-E could redirect
# the build, -fplugin/-specs/-B could swap the toolchain, and -fprofile-* both
# writes files and would carry information BETWEEN reps (defeating the
# fresh-process-per-rep memoization defence). Only optimization/tuning flags pass.
# Numerics are NOT screened (e.g. -ffast-math is allowed): correctness is decided
# by the reference oracle's error bound, so a transform that stays inside the
# bound is a legitimate optimization and one that does not is rejected on results.
_FLAGS_FILE = "candidate_flags.txt"
_FLAG_MAX_TOKENS = 32
_FLAG_ALLOW = _re_flags.compile(
    r"^(?:-O[0-3sgz]?|-Ofast"
    r"|-f[A-Za-z0-9][A-Za-z0-9._-]*(?:=[A-Za-z0-9._,+-]+)?"
    r"|-m[A-Za-z0-9][A-Za-z0-9._-]*(?:=[A-Za-z0-9._,+-]+)?"
    # Vendor-compiler spellings. Without these a candidate that
    # selects fcc is stuck in its traditional mode and cannot reach
    # -Nclang, the mode in which fcc MEASURED 403 GF/s against gcc's
    # 385 on this kernel — i.e. the flag screen, not the compiler,
    # was what made the vendor toolchain a losing choice. -K and -N
    # are option NAMESPACES, not a blanket: the deny list below still
    # applies, and library-linking spellings (-SSL2, -SCALAPACK) do
    # not match this pattern at all.
    r"|-K[A-Za-z0-9][A-Za-z0-9._,=-]*"
    r"|-N[A-Za-z0-9][A-Za-z0-9._,=-]*"
    r"|--param=[A-Za-z0-9_-]+=[0-9]+)$"
)
_FLAG_DENY_SUBSTR = (
    "plugin", "specs", "profile", "sanitize", "-fdump", "-fexec-charset",
    # v2: the frozen main creates the OpenMP team before the timer, so a
    # candidate must not be able to switch OpenMP off for its own object.
    # Deny only that: a bare "openmp" substring also killed -fopenmp-simd,
    # which 226 of the 2,133 v1 flag files (10.6%) used and which cannot
    # touch the frozen main, since the main is compiled separately with the
    # default flags regardless.
    "-fno-openmp",
    # -flto / -fwhole-program defeat the object-level symbol allowlist.
    "lto", "whole-program",
    # Vendor equivalents of the behaviours already denied above.
    # -Knoopenmp / -Nnoopenmp are the fcc spellings of -fno-openmp, and
    # would delete the pre-timer team creation from the candidate
    # binary while the reference keeps it. SSL2/SCALAPACK link the
    # vendor BLAS, which is out of scope for these tasks in the same
    # way -lblas is; they do not match the allowlist either, so this is
    # belt and braces. fjprof writes profile files and carries state
    # between repetitions, like -fprofile-*.
    "noopenmp", "ssl2", "scalapack", "fjprof",
)


def _sanitize_candidate_flags(work_dir: str):
    """Read + screen ``candidate_flags.txt``. Returns ``(accepted, rejected)``."""
    import os as _o
    if not work_dir:
        return [], []
    path = _o.path.join(work_dir, _FLAGS_FILE)
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], []
    accepted, rejected = [], []
    # v2 PARSING. Two v1 defects, both measured on the 2,133 flag files of the
    # v1 campaign:
    #  * raw.split() then "skip tokens starting with #" only drops the '#' token
    #    itself, so a literal backslash-n written instead of a newline glued the
    #    comment tail to the first real flag and destroyed it - 29 x -ffast-math,
    #    29 x -march=native, 25 x -O3, 8 x -funroll-loops across 54 files.
    #  * the Makefile strips comments LINE-wise (so the agent's local build saw
    #    different flags than the scored build did). Stripping from '#' to end of
    #    line here makes the two agree.
    raw = raw.replace("\\n", "\n").replace("\\t", "\t")
    body = "\n".join(line.split("#", 1)[0] for line in raw.splitlines())
    for tok in body.split():
        if len(accepted) >= _FLAG_MAX_TOKENS:
            rejected.append(tok)
            continue
        low = tok.lower()
        if any(bad in low for bad in _FLAG_DENY_SUBSTR) or not _FLAG_ALLOW.match(tok):
            rejected.append(tok)
        else:
            accepted.append(tok)
    return accepted, rejected


def _toolchain_identity(cc: str) -> dict:
    """Resolve the compiler actually invoked, and its version string.

    The harness compiles with bare ``cc`` unless ARI_*_CC overrides it, so the
    toolchain is whatever the job's module environment puts first on PATH. That
    is not a fixed quantity on this machine: the login node resolves ``cc`` to
    GCC 11.5.0 while the compute nodes give GCC 8.5.0, and loading the vendor
    entry module puts a Fujitsu ``fcc`` in scope whose -Kfast measured 111 GF/s
    against gcc's 385 on the same kernel. A score is therefore only interpretable
    together with the compiler that produced it, and nothing recorded it before.

    Failures are recorded, not raised: an unresolvable compiler will fail the
    build a moment later with a better message than this probe could give.
    """
    import shutil as _sh
    import subprocess as _sp

    path = _sh.which(cc) or cc
    try:
        cp = _sp.run([cc, "--version"], capture_output=True, text=True, timeout=30)
        version = (cp.stdout or cp.stderr).strip().splitlines()
        version = version[0] if version else ""
    except Exception as exc:                      # noqa: BLE001 - diagnostic only
        version = f"<unavailable: {exc}>"
    return {"cc": cc, "resolved_path": path, "version": version}


# COMPILER SELECTION IS PART OF THE SEARCH SPACE.
#
# Choosing a toolchain is real HPC tuning, and on this machine it is not a small
# axis: on the same kernel gcc 8.5.0 measured 385.0 GF/s, clang 20.1.8 385.9,
# and the vendor fcc 111.2 under -Kfast but 403 under -Nclang. Denying it would
# measure code generation under one compiler and call it optimisation ability.
#
# It is an ALLOWLIST, not an open field, because the compile line is otherwise a
# way to replace the measurement apparatus: -B/-specs/-fplugin remain rejected by
# the flag screen, and only names appearing here can be selected. Each entry is
# resolved to an absolute path so a PATH change cannot silently redirect it, and
# the resolved path and version are recorded on the result.
#
# THE DENOMINATOR DOES NOT MOVE. The frozen reference is always built with the
# default toolchain, so the score stays a ratio against one fixed object. A
# candidate that wins by picking a better compiler has won on a real axis; a
# candidate whose compiler is missing falls back to the default rather than
# failing, because an absent vendor module is an environment fact, not a
# candidate error.
_CC_FILE = "candidate_cc.txt"
_CC_ALLOW = {
    "cc": ("cc",),
    "gcc": ("gcc", "cc"),
    "clang": ("clang",),
    # The vendor compiler is only on PATH once its entry module is loaded, so
    # the install path is tried directly as well.
    "fcc": ("fcc", "/opt/FJSVstclanga/cp-1.0.30.01/bin/fcc"),
}


def _selected_cc_crosses_a_compiler_boundary(sel: dict) -> bool:
    """True when the candidate's resolved compiler is NOT the default one.

    The matched denominator exists to remove a COMPILER BOUNDARY from the
    comparison. ``status == "selected"`` only means the candidate named an
    allowlisted compiler that resolved -- and the allowlist contains the default
    (``cc``), while ``gcc`` falls back to ``cc``. Gating on status alone
    therefore built a matched reference for candidates that selected the very
    compiler the anchor already uses, where the two builds differ only by
    _REFERENCE_CFLAGS: the quotient then reads as "what the toolchain bought"
    while measuring the reference's own flags. Resolved paths are compared
    through realpath, so ``cc`` and ``gcc`` naming one binary is one compiler.
    """
    import os as _o
    import shutil as _sh

    if sel.get("status") != "selected":
        return False
    chosen = str(sel.get("resolved_path") or "")
    if not chosen:
        return False
    default = _os_pin.environ.get("ARI_STENCIL_CC", "cc")
    default_path = _sh.which(default) or default
    return _o.path.realpath(chosen) != _o.path.realpath(default_path)


def _select_candidate_cc(work_dir: str) -> dict:
    """Resolve the candidate's declared compiler. Returns a record, never raises.

    ``{"requested", "cc", "resolved_path", "version", "status"}`` where status is
    one of ``default`` (nothing declared), ``selected``, ``not_allowed`` or
    ``unavailable``. The last two fall back to the default compiler and say so,
    so a node is never lost to a typo or a missing vendor module.
    """
    import os as _o
    import shutil as _sh

    default = _os_pin.environ.get("ARI_STENCIL_CC", "cc")
    path = _o.path.join(work_dir or "", _CC_FILE)
    try:
        want = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        rec = _toolchain_identity(default)
        rec.update({"requested": None, "status": "default"})
        return rec
    # first non-comment token only; the file is a selection, not a command line
    want = next((ln.split("#", 1)[0].strip()
                 for ln in want.splitlines() if ln.split("#", 1)[0].strip()), "")
    if not want:
        rec = _toolchain_identity(default)
        rec.update({"requested": None, "status": "default"})
        return rec
    if want not in _CC_ALLOW:
        rec = _toolchain_identity(default)
        rec.update({"requested": want, "status": "not_allowed"})
        return rec
    for cand in _CC_ALLOW[want]:
        resolved = _sh.which(cand) or (cand if _o.path.isfile(cand) else None)
        if resolved:
            rec = _toolchain_identity(resolved)
            rec.update({"requested": want, "status": "selected"})
            return rec
    rec = _toolchain_identity(default)
    rec.update({"requested": want, "status": "unavailable"})
    return rec


# Per-compiler version pinning, because selecting "gcc" does not select a
# VERSION. `_select_candidate_cc` resolves names through PATH, so a `module
# load` anywhere in the job changes which gcc a candidate declaring "gcc" gets,
# and the campaign is many jobs over hours. The default compiler is covered by
# ARI_EXPECTED_CC_VERSION; this covers every compiler a candidate may select.
#
# Set ARI_EXPECTED_TOOLCHAINS to a comma-separated list of name=substring pairs,
# e.g. "gcc=8.5.0,clang=20.1.8,fcc=4.11.1". A selected compiler whose version
# does not contain its expected substring stops the run as an INFRASTRUCTURE
# error, not a candidate error: the candidate asked for a legal compiler and the
# environment supplied a different one, which is the environment's fault.
# Unset, nothing is enforced.
def _expected_toolchain_map() -> dict:
    raw = _os_pin.environ.get("ARI_EXPECTED_TOOLCHAINS", "").strip()
    out = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, want = item.partition("=")
        name, want = name.strip(), want.strip()
        if name and want:
            out[name] = want
    return out


def _assert_selected_toolchain(sel: dict) -> None:
    """Fail closed when a SELECTED compiler is not the pinned version."""
    want_map = _expected_toolchain_map()
    if not want_map or not sel:
        return
    name = sel.get("requested")
    if not name or sel.get("status") != "selected":
        return
    want = want_map.get(name)
    if want and want not in (sel.get("version") or ""):
        raise HarnessInfrastructureError(
            f"selected compiler {name!r} is version {sel.get('version')!r}, "
            f"which does not contain the pinned {want!r} "
            f"(resolved {sel.get('resolved_path')}); refusing to score, because "
            f"a compiler version change is larger than the effect being measured")


def _compile_kernel(kind: str, work_dir: str, out_td: str,
                    extra_flags=(), main_src: str | None = None,
                    tag: str | None = None) -> str:
    """Compile ``stencil_main.c`` + the {baseline|candidate} kernel into
    ``out_td``; return the exe path. IDENTICAL compiler + flags for both
    (anti-gaming). The baseline comes from the package ``kernels_dir()`` and the
    candidate ONLY from ``work_dir`` — a tampered fixture copy in work_dir cannot
    affect the score. No external stencil library is linked.

    The candidate is compiled from a HEADER-LESS copy inside ``out_td``: a quoted
    ``#include "stencil_kernel.h"`` searches the including file's OWN directory
    first, so a candidate sitting in work_dir would bind to a work_dir copy of the
    header instead of the sha256-pinned one; copying it into ``out_td`` (which has
    no header) forces the include to fall through to ``-I{kdir}``, the pinned
    header. (baseline already lives beside kdir.)"""
    import os as _os
    import subprocess as _sub
    kdir = kernels_dir()
    # main_src swaps the FROZEN DRIVER only -- same kernel source, same
    # compiler, same flags, same symbol and out-of-band checks. It exists for
    # stencil_main_profiled.c, which is this driver plus a counter gate; the
    # scored build passes nothing and is unchanged. Keeping one compile path
    # is the point: a second one would drift from the flags being profiled.
    main_c = main_src or _os.path.join(kdir, "stencil_main.c")
    _tag = tag or kind
    _PKG_KERNELS = {
        "reference": "reference_stencil.c",
        "baseline": "baseline_stencil.c",
    }
    # reference_matched is the reference SOURCE built the candidate's way: same
    # frozen kernel, the candidate's compiler and the candidate's flags, so the
    # only difference left against the candidate is the source itself.
    _src_kind = "reference" if kind == "reference_matched" else kind
    kern_c = (_os.path.join(kdir, _PKG_KERNELS[_src_kind]) if _src_kind in _PKG_KERNELS
              else _os.path.join(work_dir or "", "candidate_stencil.c"))
    if kind == "reference":
        extra_flags = (*_REFERENCE_CFLAGS, *(extra_flags or ()))
    if not _os.path.isfile(kern_c):
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"kernel source not found ({kind}): {kern_c}")
    # v2: compile the candidate from a HEADER-LESS copy inside out_td (see
    # the docstring). gemm and spmm did not do this in v1 and were exposed
    # to a tampered work_dir header; v2 applies it to all three.
    src_c = kern_c
    if kind == "candidate":
        import shutil as _sh
        src_c = _os.path.join(out_td, f"candidate_{_tag}_stencil.c")
        _sh.copy2(kern_c, src_c)

    _cc_default = _os.environ.get("ARI_STENCIL_CC", "cc")
    if kind in ("candidate", "reference_matched"):
        _sel = _select_candidate_cc(work_dir)
        _assert_selected_toolchain(_sel)
        cc = _sel.get("resolved_path") or _cc_default
    else:
        cc = _cc_default
    # The ISA flag is chosen for the compiler actually in use; see
    # _isa_flags_for. ARI_STENCIL_CFLAGS still overrides everything.
    _env_cflags = _os.environ.get("ARI_STENCIL_CFLAGS")
    base_cflags = (_env_cflags.split() if _env_cflags
                   else ["-O3", "-fopenmp", *_isa_flags_for(cc)])
    exe = _os.path.join(out_td, f"kernel_{_tag}.exe")
    main_o = _os.path.join(out_td, f"main_{_tag}.o")
    kern_o = _os.path.join(out_td, f"kern_{_tag}.o")

    def _run(argv, what):
        try:
            return _sub.run(argv, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            raise HarnessInfrastructureError(
                f"{what} invocation failed ({kind}): {exc}") from exc

    # v2: the frozen main is compiled with the DEFAULT flags only. In v1 one
    # invocation compiled main + kernel together with the candidate's flags
    # appended, so a candidate flag reached the frozen driver - e.g. -fno-openmp
    # would delete the pre-timer team-creation region from the candidate binary
    # while the baseline kept it, deflating the wall lower bound.
    cp = _run([cc, *base_cflags, f"-I{kdir}", "-c", main_c, "-o", main_o], "compiler")
    if cp.returncode != 0:
        raise HarnessInfrastructureError(
            f"frozen driver failed to compile: {cp.stderr.strip()[-600:]}")

    # Candidate-declared flags come AFTER the defaults so they win, and apply to
    # the KERNEL translation unit only.
    kern_cflags = [*base_cflags, *(extra_flags or ())]
    cp = _run([cc, *kern_cflags, f"-I{kdir}", "-c", src_c, "-o", kern_o], "compiler")
    if cp.returncode != 0:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"compile failed ({kind}): {cp.stderr.strip()[-600:]}")

    # v2 SYMBOL ALLOWLIST. The kernel and the frozen driver link into one
    # executable, so a kernel that defines clock_gettime (or GOMP_parallel, or a
    # constructor) wins the link and can move work out of the timed window or
    # forge the timer outright - verified reachable with nm. v1's wall clamp made
    # that worthless; with credited = the internal timer it is a live lever, so
    # the kernel object may export the kernel entry point and nothing else. On
    # the v1 corpus all 2,604 candidate sources that compiled exported exactly
    # their kernel symbol and nothing more, so this rejects no real candidate.
    nm = _run(["nm", "-g", "--defined-only", kern_o], "nm")
    if nm.returncode != 0:
        raise HarnessInfrastructureError(
            f"symbol check unavailable ({kind}): {nm.stderr.strip()[-300:]}")
    extra = sorted({
        parts[-1] for line in nm.stdout.splitlines()
        if len(parts := line.split()) >= 3 and parts[-2] in "TDBRWVi"
    } - {"jacobi"})
    if extra:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(
            f"{kind} kernel exports symbols other than 'jacobi': {extra[:8]}")

    # v2 OUT-OF-BAND EXECUTION CHECK. Code that runs outside the measured call
    # exports no extra global symbol, so the name allowlist above cannot see it.
    # Verified on this toolchain: a constructor emits .init_array and runs before
    # main; an ifunc emits a symbol of type IFUNC and its resolver runs at load;
    # a DESTRUCTOR emits .fini_array and runs after main has written the timing
    # file - which is exactly how the frozen forge test cheats, by reading
    # /proc/self/cmdline for the private timing path and overwriting it with 1e-9.
    # A constructor or resolver moves setup out of the window; a destructor
    # rewrites the result after it. None of them has a legitimate use in a
    # compute kernel.
    sec = _run(["readelf", "-SW", kern_o], "readelf")
    sym = _run(["readelf", "-sW", kern_o], "readelf")
    if sec.returncode != 0 or sym.returncode != 0:
        raise HarnessInfrastructureError(
            f"ELF inspection unavailable ({kind}): "
            f"{(sec.stderr or sym.stderr).strip()[-300:]}")
    out_of_band = sorted({s for s in (".init_array", ".preinit_array", ".ctors",
                                     ".fini_array", ".dtors")
                          if s in sec.stdout})
    ifuncs = sorted({p[7] for ln in sym.stdout.splitlines()
                     if len(p := ln.split()) >= 8 and p[3] == "IFUNC"})
    if out_of_band or ifuncs:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(
            f"{kind} kernel runs code outside the measured call "
            f"(sections={out_of_band}, ifunc={ifuncs}); all work must happen "
            f"inside gemm/spmm/jacobi")

    # v2 UNDEFINED-REFERENCE DENYLIST. Blocking out-of-band SECTIONS is not
    # enough: a handler registered with atexit from inside the kernel needs no
    # .fini_array, and the whole "overwrite the private timing file" family only
    # needs to open a file. A compute kernel needs neither. Calibrated on the
    # 2,604 v1 candidates that compile: their undefined references are the OpenMP
    # runtime, malloc/free/posix_memalign/aligned_alloc/memcpy/memset, and
    # stderr/fwrite/fprintf/exit/abort - ZERO open a file and ZERO register an
    # exit hook, so this rejects no real candidate.
    _FORBIDDEN_REFS = {
        "fopen", "fopen64", "freopen", "freopen64", "open", "open64", "openat",
        "creat", "creat64", "fdopen", "atexit", "__cxa_atexit", "on_exit",
        "popen", "system", "fork", "vfork", "execve", "execl", "execlp", "execvp",
        "dlopen", "dlsym", "readlink", "syscall", "ptrace",
    }
    undef = {p[-1] for ln in _run(["nm", "-u", kern_o], "nm").stdout.splitlines()
             if (p := ln.split()) and len(p) >= 2}
    banned = sorted(undef & _FORBIDDEN_REFS)
    if banned:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(
            f"{kind} kernel references {banned}; a compute kernel must not open "
            f"files, register exit hooks or spawn processes")

    # v2 D4 FIX: the candidate's screened flags must reach the LINK too, not
    # only the kernel compile. On GCC, -ffast-math at link time pulls in
    # crtfastmath.o, which sets FTZ/DAZ process-wide - verified with -Wl,-t:
    # present on a v1-style single compile+link, absent when linking with the
    # base flags only, present again once the candidate flags are restored.
    # Without this a candidate declaring -ffast-math (which experiment.md
    # blesses and 29 corpus flag files use) gets different denormal behaviour
    # in the scored build than in its own `make candidate`, changing both the
    # timing and the correctness oracle. The flags are already screened, and
    # -flto/-whole-program are denied, so nothing here defeats the
    # object-level symbol and section checks performed above.
    cp = _run([cc, *base_cflags, *(extra_flags or ()), main_o, kern_o,
               "-o", exe, "-lm"], "linker")
    if cp.returncode != 0:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"link failed ({kind}): {cp.stderr.strip()[-600:]}")
    return exe


def _become_subreaper() -> None:
    """Adopt orphaned descendants so a detached grandchild cannot escape us.

    ``killpg`` alone CANNOT reach the threat its call site describes: a candidate
    that fork()s and calls setsid() lands in a NEW session and NEW process group,
    which the scored process's pgid does not cover. With PR_SET_CHILD_SUBREAPER
    set, such an escapee reparents to THIS process when its intermediate parent
    exits, so ``_kill_strays`` can find it by PPid. Best-effort: on kernels or
    platforms without the option we simply keep the pgid kill.
    """
    try:
        import ctypes as _ct
        _ct.CDLL("libc.so.6", use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
    except Exception:
        pass


def _kill_strays(known_pid: int) -> int:
    """SIGKILL every process that has reparented to us (detached escapees).

    Such a process keeps burning cores into the NEXT measurement, inflating the
    trusted reference's tb/tb_wall and so shrinking _wall_kernel — the candidate
    slowing its own referee. Returns how many were killed.

    ASKS THE KERNEL FOR ITS CHILDREN INSTEAD OF SCANNING /proc. The original
    listed every pid on the node and opened /proc/<pid>/status to read PPid,
    which on the scoring node means 709 small file reads, twice per repetition:
    measured at 84.42 ms per call against 0.143 ms for this version, a factor of
    590, and about 19% of a whole spmm repetition.

    The set found is IDENTICAL, not merely similar: a process that has reparented
    to us has our pid as its PPid, and /proc/<pid>/task/<tid>/children lists
    exactly the pids whose PPid is that thread's process. Scanning all of /proc
    to filter on PPid == me computes the same predicate the long way round.

    Falls back to the scan when the children file is unavailable (it needs
    CONFIG_PROC_CHILDREN), so a kernel without it keeps the protection.
    """
    import os as _o
    import signal as _sig

    me = _o.getpid()
    killed = 0
    kids: set[int] = set()
    have_children_file = False
    try:
        for tid in _o.listdir(f"/proc/{me}/task"):
            try:
                with open(f"/proc/{me}/task/{tid}/children") as fh:
                    have_children_file = True
                    kids.update(int(x) for x in fh.read().split())
            except OSError:
                continue
    except OSError:
        have_children_file = False

    if have_children_file:
        for pid in kids:
            if pid in (me, known_pid):
                continue
            try:
                _o.kill(pid, _sig.SIGKILL)
                killed += 1
            except (OSError, ValueError):
                continue
        return killed

    # Fallback: the kernel does not expose the children file.
    try:
        entries = _o.listdir("/proc")
    except OSError:
        return 0
    for ent in entries:
        if not ent.isdigit():
            continue
        pid = int(ent)
        if pid in (me, known_pid):
            continue
        try:
            with open(f"/proc/{pid}/status") as fh:
                ppid = -1
                for line in fh:
                    if line.startswith("PPid:"):
                        ppid = int(line.split()[1])
                        break
            if ppid == me:
                _o.kill(pid, _sig.SIGKILL)
                killed += 1
        except (OSError, ValueError):
            continue
    return killed



def _problem_cache_dir():
    """Shared directory for cached problem files, or None when unset."""
    import os as _os

    d = _os.environ.get("ARI_HARNESS_CACHE", "").strip()
    if not d:
        return None
    try:
        _os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return d



def _warn_once(msg: str) -> None:
    """Emit a harness warning at most once per distinct message per process."""
    import sys as _sys

    seen = _warn_once.__dict__.setdefault("_seen", set())
    if msg in seen:
        return
    seen.add(msg)
    print(f"[stencil_harness] {msg}", file=_sys.stderr, flush=True)


def _cached_reference_jacobi(u0, nx, ny, nz, nt, key: str | None):
    """``reference_jacobi`` with a disk cache BOUND TO ITS INPUT.

    Measured on the compute node at the scored size: 5.129 s per repetition,
    against 5.96 s for the whole repetition and 0.075 s for the C kernel being
    scored. The numpy oracle IS the cost of measuring this task.

    It cannot be spot-checked the way a matrix product can - Jacobi is
    iterative, so one output point cannot be recomputed without the whole
    history. Instead the entry stores the SHA-256 of the u0 it was computed
    from, and a hit is accepted only when that matches the u0 in hand. Hashing
    the field costs about 0.2 s against the 5.1 s it saves, and it catches
    corruption, a truncated write and a key collision alike. Shape, dtype and
    the sweep count are checked too, since a field of the right size from a
    different nt would otherwise pass.
    """
    _assert_expected_toolchain(
        _os_pin.environ.get("ARI_STENCIL_CC", "cc"))

    import hashlib as _hl
    import os as _os

    if not key:
        return reference_jacobi(u0, nx, ny, nz, nt)
    cdir = _os.environ.get("ARI_HARNESS_CACHE", "").strip()
    if not cdir:
        return reference_jacobi(u0, nx, ny, nz, nt)
    try:
        _os.makedirs(cdir, exist_ok=True)
    except OSError:
        return reference_jacobi(u0, nx, ny, nz, nt)

    arr = np.ascontiguousarray(np.asarray(u0, dtype=np.float64))
    digest = _hl.sha256(arr.tobytes()).hexdigest()
    # A bare .npy plus a small sidecar, not an .npz: npz is a zip container and
    # reading the 134 MB field back out of one measured 1.05 s on the warm path
    # against 6.21 s cold, so the container was eating a fifth of the saving.
    # The sidecar is read first, so a mismatched entry costs a few bytes of I/O
    # rather than a full field read.
    path = _os.path.join(cdir, f"stencil_uref_{key}.npy")
    meta = path + ".meta"
    if _os.path.isfile(path) and _os.path.isfile(meta):
        try:
            import json as _json
            with open(meta) as fh:
                md = _json.load(fh)
            if (md.get("u0_sha") == digest and int(md.get("nt", -1)) == int(nt)
                    and tuple(md.get("shape") or ()) == tuple(arr.shape)):
                u = np.load(path, mmap_mode=None)
                if u.shape == arr.shape and u.dtype == np.float64:
                    return u
                _warn_once(f"stencil reference cache array mismatch for {key}; recomputing")
            else:
                _warn_once(f"stencil reference cache does not match its input for "
                           f"{key}; recomputing")
        except Exception as exc:
            _warn_once(f"stencil reference cache unreadable for {key} ({exc}); "
                       f"recomputing")
    u = reference_jacobi(u0, nx, ny, nz, nt)
    try:
        import json as _json
        tmp = f"{path}.{_os.getpid()}.tmp.npy"
        np.save(tmp, u)                       # name already ends .npy, so no rename
        _os.replace(tmp, path)
        tmpm = f"{meta}.{_os.getpid()}.tmp"
        with open(tmpm, "w") as fh:
            _json.dump({"u0_sha": digest, "nt": int(nt),
                        "shape": list(arr.shape)}, fh)
        _os.replace(tmpm, meta)               # sidecar LAST: a half-written pair
    except Exception as exc:                  # is then simply a miss, not a lie
        _warn_once(f"stencil reference cache write failed ({exc}); continuing uncached")
    return u


# Runtime library directories a selected compiler's output needs at LOAD time.
# Measured: an fcc-built executable dies with "libfjomphk.so: cannot open shared
# object file" unless these are on the loader path, and the vendor entry module
# sets exactly these two. gcc and clang need nothing extra here.
_CC_RUNTIME_LIBS = {
    "/opt/FJSVstclanga/cp-1.0.30.01/bin/fcc": (
        "/opt/FJSVstclanga/cp-1.0.30.01/lib64:/opt/FJSVstclanga/cp-1.0.30.01/lib"),
}


def _runtime_libs_for(resolved_cc: str | None) -> str | None:
    """LD_LIBRARY_PATH additions for an executable built by ``resolved_cc``."""
    if not resolved_cc:
        return None
    if resolved_cc in _CC_RUNTIME_LIBS:
        return _CC_RUNTIME_LIBS[resolved_cc]
    # match by basename too, so a differently-rooted vendor install still works
    import os as _o
    base = _o.path.basename(resolved_cc)
    for known, libs in _CC_RUNTIME_LIBS.items():
        if _o.path.basename(known) == base:
            root = _o.path.dirname(_o.path.dirname(resolved_cc))
            cand = f"{root}/lib64:{root}/lib"
            return cand if _o.path.isdir(f"{root}/lib64") else libs
    return None


def _run_exe(exe: str, work_td: str, u0, nx: int, ny: int, nz: int, nt: int, problem_key: str | None = None,
             ld_library_path: str | None = None, launcher: tuple = (),
             capture: dict | None = None):
    """Run ONE cold timed call of ``exe`` on (u0, nx, ny, nz, nt) in a fresh
    process; return ``(t_internal, t_wall, u_final)``.

    The kernel's OWN in-process clock is written to ``timing.bin`` (``t_internal``,
    argv[3]) but that file is NOT trustworthy: the candidate is linked into the
    same process and can locate + overwrite it (e.g. via ``/proc/self/cmdline`` or
    the fixed basename in the shared temp dir), forging an arbitrarily small time.
    So we ALSO record the EXTERNAL Python wall-clock around ``subprocess.run``
    (``t_wall``) — measured OUTSIDE the candidate's process, hence unforgeable in
    the "faster" direction. ``measure_node`` cross-checks the two: if the reported
    internal time is implausibly below what the wall-clock allows, the timer was
    forged and the family is rejected. A short output (partial write) raises."""
    import os as _os
    import subprocess as _sub
    import time as _time
    u0 = np.ascontiguousarray(np.asarray(u0, dtype=np.float64))
    nx, ny, nz, nt = int(nx), int(ny), int(nz), int(nt)
    N = nx * ny * nz
    prob = _os.path.join(work_td, "problem.bin")
    outf = _os.path.join(work_td, "u.bin")
    tf = _os.path.join(work_td, "timing.bin")

    def _write_problem(path):
        with open(path, "wb") as fh:
            np.array([nx, ny, nz, nt], dtype=np.int32).tofile(fh)
            u0.tofile(fh)


    # The problem file was written afresh before EVERY process launch, and within
    # one repetition the candidate and the reference are handed the SAME problem,
    # so it was written twice identically; because the seeds are a deterministic
    # function of the repetition index, every node in the campaign regenerated
    # the same files again. The file is content-determined by the shape and the
    # input seed, so it is cached under ARI_HARNESS_CACHE and HARD LINKED into
    # the run directory. Anti-gaming is untouched: the path the scored process
    # sees and the bytes behind it are exactly what they were, and the problem is
    # still fresh per repetition because the input seed is part of the key.
    expect_bytes = 16 + u0.nbytes
    cached = None
    # PROBLEM FILES ARE NOT CACHED BY DEFAULT. The reference SOLUTION still is --
    # that is the expensive object. The generated problem is not: it is
    # deterministic from the input seed and costs well under a second to rebuild,
    # yet it dominated the cache because the key includes the input seed and the
    # final re-measurement derives that from the RUN seed, so every seed created a
    # fresh set. Measured: 72% of the per-seed bytes, and a 30-seed campaign
    # wanted ~802 GB against ~694 GB of quota -- it would have hit the limit
    # part-way through, then silently recomputed oracles and timed out the runs
    # late in the campaign.
    #
    # Dropping it does not move the score. Measured A/B on one node, reps=15, four
    # scorings each: median geomean 1.000144 with the full cache against 0.999621
    # with solutions only, a 0.052% difference against a 0.150% band. It cannot:
    # the bytes are identical (both launches of a repetition are handed the same
    # in-memory problem), the read happens before the timed window opens, and the
    # credited time is the kernel's own internal timer. What it costs is wall
    # clock -- measured +18.5 s on a 98 s scoring.
    #
    # Set ARI_CACHE_PROBLEM_FILES=1 to restore the old behaviour where storage
    # allows it.
    if problem_key and _os.environ.get("ARI_CACHE_PROBLEM_FILES", "0") == "1":
        cdir = _problem_cache_dir()
        if cdir:
            cached = _os.path.join(cdir, f"prob_{problem_key}.bin")
            try:
                if not (_os.path.isfile(cached)
                        and _os.path.getsize(cached) == expect_bytes):
                    tmp = f"{cached}.{_os.getpid()}.tmp"
                    _write_problem(tmp)
                    _os.replace(tmp, cached)
            except Exception:
                cached = None
    try:
        if _os.path.lexists(prob):
            _os.remove(prob)
    except OSError:
        pass
    linked = False
    if cached:
        try:
            _os.link(cached, prob)
            linked = True
        except OSError:
            try:
                import shutil as _sh
                _sh.copyfile(cached, prob)
                linked = True
            except Exception:
                linked = False
    if not linked:
        _write_problem(prob)
    for stale in (outf, tf):
        try:
            _os.remove(stale)
        except OSError:
            pass
    run_env = dict(_os.environ)
    # v2: the scored process must not learn where the node work_dir is.
    # A candidate that reads ARI_WORK_DIR can pull in a file the sterility
    # gate does not hash, which breaks SCORE_INPUTS completeness.
    run_env.pop("ARI_WORK_DIR", None)
    # Respect an ambient OMP_NUM_THREADS (the allocation's thread budget) instead of
    # forcing 16: the harness default silently contradicted the declared run
    # configuration. Explicit ARI_STENCIL_THREADS still wins.
    run_env["OMP_NUM_THREADS"] = _os.environ.get(
        "ARI_STENCIL_THREADS", _os.environ.get("OMP_NUM_THREADS", "16"))
    # A candidate may select a compiler whose runtime is not on the default
    # loader path (the vendor fcc dies with "libfjomphk.so: cannot open shared
    # object file" without it). Only the candidate's process gets this; the
    # reference's must stay exactly the object it always was.
    if ld_library_path:
        prev = run_env.get("LD_LIBRARY_PATH", "")
        run_env["LD_LIBRARY_PATH"] = (
            f"{ld_library_path}:{prev}" if prev else ld_library_path)
    _w0 = _time.monotonic()
    # start_new_session makes the scored process its own process-group leader, so its
    # pid IS the pgid. A candidate can fork()+setsid() a detached grandchild that
    # OUTLIVES the run: it keeps burning cores into the NEXT measurement, inflating
    # the trusted baseline's tb/tb_wall (hence _overhead) and shrinking _wall_kernel —
    # the candidate slowing its own referee. Kill the whole group afterwards so no
    # candidate-spawned work survives into another timing window.
    import signal as _signal
    _pr = _sub.Popen([*launcher, exe, prob, outf, tf], stdout=_sub.PIPE, stderr=_sub.PIPE,
                     text=True, env=run_env, start_new_session=True)
    _timed_out = False
    try:
        _out, _err = _pr.communicate(timeout=_run_timeout_seconds())
    except _sub.TimeoutExpired:
        _timed_out = True
        _out, _err = "", "timed out"
    t_wall = _time.monotonic() - _w0
    try:
        _os.killpg(_pr.pid, _signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    # killpg cannot reach a setsid() escapee (new session => new pgid); reap by
    # reparenting instead. See _become_subreaper / _kill_strays.
    _kill_strays(_pr.pid)
    if _timed_out:
        _pr.wait()
        raise RuntimeError("run timed out")
    # `capture` is how the counter launcher's stdout gets back out. Nothing
    # reads it otherwise: the scored path drains stdout only so the pipe
    # cannot fill. Default None => byte-identical behaviour.
    if capture is not None:
        capture["stdout"] = _out
        capture["stderr"] = _err
    rp = _sub.CompletedProcess(_pr.args, _pr.returncode, _out, _err)
    if rp.returncode != 0:
        raise RuntimeError(f"run failed: {rp.stderr.strip()[-600:]}")
    t = np.fromfile(tf, dtype=np.float64)
    if t.size < 1:
        raise RuntimeError("kernel wrote no timing")
    u = np.fromfile(outf, dtype=np.float64)
    if u.size != N:
        raise RuntimeError(f"kernel wrote {u.size} outputs, expected {N}")
    return float(t[0]), float(t_wall), u.reshape(nx, ny, nz)


def _default_run_kernel(kind: str, work_dir: str, u0, nx: int, ny: int, nz: int,
                        nt: int):
    """Compile + run ONE cold timed call; return ``(t_internal, u_final)``. Kept
    for the login self-test; ``measure_node`` compiles once and reuses the exe.

    ``kind="baseline"`` compiles the frozen ``baseline_stencil.c``;
    ``"candidate"`` compiles the agent's ``candidate_stencil.c`` from
    ``work_dir``. IDENTICAL compiler + flags for both (anti-gaming). No external
    library is linked. OMP threads are pinned (reproducible)."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        exe = _compile_kernel(kind, work_dir, td)
        ti, _tw, u = _run_exe(exe, td, u0, nx, ny, nz, nt)
        return ti, u


def _unpack_run(res):
    """Normalize a runner result to ``(t_internal, t_wall, u_final)``. The real
    ``_run_exe`` returns all three; an INJECTED test runner returns ``(t, u)``,
    for which wall==internal (its cross-check is a no-op)."""
    if len(res) == 3:
        return float(res[0]), float(res[1]), res[2]
    ti, u = res
    return float(ti), float(ti), u


def _measure_node_once(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    shapes: tuple[tuple[int, int, int, int], ...] = SHAPES,
    seed: int = 0,
    # INERT. Accepted so an old caller does not break, and never read: the
    # measurement is one cold call in a fresh process per repetition, which
    # is what makes an in-process warmup unexploitable. A default of 1
    # read as "this many warmup iterations happen"; none do.
    warmup: int = 1,
    reps: int = 3,
) -> dict:
    """Measure a node's candidate stencil against the fixed grid set.

    Each repetition runs a fresh random field and verifies the candidate output.
    Candidate and baseline form one matched timing pair with alternating execution
    order. The external wall clock checks and, when needed, clamps the candidate's
    internal timing. The executable is compiled once per kind and reused across
    fresh processes. The case speedup is the median of accepted per-pair
    ``baseline_time / credited_candidate_time`` ratios.

    Returns the dict DeterministicEvaluator._score consumes:
    ``{"compile_ok", "families": {name: {"speedup", "valid", ...}}, "reason"}``.
    """
    # v2: refuse to measure if the control-side BLAS could contend with the
    # candidate (see the pinning block at the top of this module).
    _unpinned = [v for v in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
                 if _os_pin.environ.get(v) not in (None, "1")]
    if _unpinned:
        raise HarnessInfrastructureError(
            f"control-side BLAS is not pinned to one thread ({_unpinned}); the "
            f"reference solve would contend with the candidate and the measured "
            f"time would be meaningless")
    import statistics as _stats
    import tempfile as _tmp

    n_reps = max(1, int(reps))
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"

    _become_subreaper()
    _problem_key: list[str | None] = [None]
    _cand_flags: list[str] = []
    _rej_flags: list[str] = []
    evaluation_status = "valid"
    td_obj = None
    exes: dict[str, str] = {}
    if run_kernel is None:
        td_obj = _tmp.TemporaryDirectory()
        _cand_flags, _rej_flags = _sanitize_candidate_flags(work_dir)
        try:
            exes["reference"] = _compile_kernel("reference", work_dir, td_obj.name)
            exes["candidate"] = _compile_kernel(
                "candidate", work_dir, td_obj.name, extra_flags=_cand_flags)
            # A SECOND DENOMINATOR, same frozen source, built with whatever
            # toolchain the candidate chose.
            #
            # The anchor reference is always built with the default compiler, so
            # a candidate that selects another one is compared across a compiler
            # boundary -- and anything that acts on one side of that boundary and
            # not the other moves the ratio without touching either program.
            # Measured 2026-08-03: XOS_MMM_L_PAGING_POLICY is read only by the
            # vendor large-page library, which only Fujitsu builds link, and it
            # moved a Fujitsu-built stencil 5.9x while leaving the GCC-built
            # reference untouched. The paired per-repetition design cancels
            # time-varying conditions (a cold page cache turned 214 ms into
            # 2086 ms and vanished in the ratio) but it cannot cancel an
            # asymmetry between the two builds.
            #
            # Measuring the reference a second time under the candidate's own
            # toolchain gives a ratio in which such effects DO cancel. Neither
            # denominator replaces the other: the anchor ratio is the end-to-end
            # result including the compiler choice, the matched ratio is the
            # contribution of the code alone, and their difference is what the
            # compiler bought. The frozen source is still one object.
            _sel_cc = _select_candidate_cc(work_dir)
            if _selected_cc_crosses_a_compiler_boundary(_sel_cc):
                exes["reference_matched"] = _compile_kernel(
                    "reference_matched", work_dir, td_obj.name,
                    extra_flags=_cand_flags)
        except CandidateInvalidError as exc:
            td_obj.cleanup()
            return {
                "compile_ok": False,
                "families": {},
                "reason": str(exc),
                "evaluation_status": "candidate_invalid",
                "candidate_cflags": list(_cand_flags),
                "rejected_cflags": list(_rej_flags),
            }
        except Exception:
            td_obj.cleanup()
            raise

        _cand_libs = _runtime_libs_for(
            (_select_candidate_cc(work_dir) or {}).get("resolved_path"))
        def run(kind, _wd, _u0, _nx, _ny, _nz, _nt):
            return _run_exe(exes[kind], td_obj.name, _u0, _nx, _ny, _nz, _nt,
                            problem_key=_problem_key[0],
                            ld_library_path=(_cand_libs
                                             if kind in ("candidate", "reference_matched")
                                             else None))
    else:
        run = run_kernel

    try:
        for shape in shapes:
            nx, ny, nz, nt = (int(s) for s in shape)
            name = f"{nx}x{ny}x{nz}t{nt}"
            ratios: list[float] = []
            repetitions: list[dict[str, Any]] = []
            valid = True
            max_abs = 0.0
            n_clamped = 0
            n_implausible = 0
            for r in range(n_reps):
                input_seed = seed * 100003 + r
                rec = {
                    "index": r,
                    "status": "started",
                    "valid": False,
                    "measurements": {"input_seed": input_seed},
                }
                _problem_key[0] = f"stencil_{name}_s{input_seed}"
                u0, nx, ny, nz, nt = gen_problem(shape, seed=input_seed)
                u_ref = _cached_reference_jacobi(
                    u0, nx, ny, nz, nt, _problem_key[0])
                observed: dict[str, tuple[float, float, Any]] = {}
                # Reverse the starting order by seed so odd repetition counts
                # are balanced across the preregistered seed blocks.
                order = (
                    ("candidate", "reference")
                    if (r + seed) % 2 == 0
                    else ("reference", "candidate")
                )
                rec["execution_order"] = list(order)
                for kind in order:
                    try:
                        observed[kind] = _unpack_run(
                            run(kind, work_dir, u0, nx, ny, nz, nt))
                    except Exception as exc:
                        if kind == "reference":
                            raise HarnessInfrastructureError(
                                f"reference run failed on {name}, rep {r}: {exc}") from exc
                        valid = False
                        evaluation_status = "candidate_invalid"
                        reason = f"candidate run failed on {name}, rep {r}: {exc}"
                        rec["status"] = "candidate_run_failed"
                        rec["measurements"]["error"] = str(exc)
                        repetitions.append(rec)
                        break
                if not valid:
                    break

                # The matched denominator runs in the SAME repetition, so it sees
                # the same node state the pair did. Its failure is not fatal: the
                # anchor ratio is the primary quantity and must not be lost
                # because a second build of the reference misbehaved.
                if "reference_matched" in exes:
                    try:
                        observed["reference_matched"] = _unpack_run(
                            run("reference_matched", work_dir, u0, nx, ny, nz, nt))
                    except Exception as exc:
                        rec["measurements"]["reference_matched_error"] = str(exc)

                tc, tc_wall, u_cand = observed["candidate"]
                tb, tb_wall, u_ref_run = observed["reference"]
                # See the gemm harness: the denominator itself is verified once
                # per case, because it was only ever checked by a unit test at a
                # size far below the scored one.
                if r == 0:
                    ref_ok, ref_ma = is_correct(u_ref_run, u_ref, u0, nt)
                    if not ref_ok:
                        raise HarnessInfrastructureError(
                            f"the FROZEN REFERENCE is incorrect on {name} at the "
                            f"scored size (max_abs={ref_ma}); every score computed "
                            f"against it would be meaningless")
                ok, ma = is_correct(u_cand, u_ref, u0, nt)
                max_abs = max(max_abs, ma)
                measurements = rec["measurements"]
                measurements.update({
                    "candidate_internal_seconds": float(tc),
                    "candidate_wall_seconds": float(tc_wall),
                    "reference_internal_seconds": float(tb),
                    "reference_wall_seconds": float(tb_wall),
                    "max_abs_error": float(ma),
                })
                if not ok:
                    valid = False
                    evaluation_status = "candidate_invalid"
                    reason = f"incorrect output on {name}, rep {r}"
                    rec["status"] = "incorrect"
                    repetitions.append(rec)
                    break

                overhead = max(0.0, tb_wall - tb)
                wall_lower_bound = tc_wall - overhead
                measurements["reference_overhead_seconds"] = float(overhead)
                measurements["candidate_wall_lower_bound_seconds"] = float(wall_lower_bound)
                # v2: the wall bound is a FORGERY CHECK, not a floor. It is not a
                # tight lower bound on kernel time - OpenMP team teardown runs
                # after the internal timer stops but inside the process wall, so
                # the bound systematically exceeds tc. Reject an implausible rep.
                if (_REJECT_RATIO > 0.0 and wall_lower_bound > 0.0
                        and tc + _REJECT_ABS_SLACK < _REJECT_RATIO * wall_lower_bound):
                    n_implausible += 1
                    measurements["wall_bound_ratio"] = float(tc / wall_lower_bound)
                    rec["status"] = "implausible_timing"
                    repetitions.append(rec)
                    continue

                # v2: a non-positive wall bound no longer discards the repetition.
                # The bound is tc_wall - (tb_wall - tb), i.e. the BASELINE's
                # non-kernel wall applied to the CANDIDATE, so under node
                # contention it can exceed the candidate's whole wall and go
                # negative. On a contended A64FX node that discarded one
                # repetition of EVERY case, in v1 as well as v2 - v1 survived
                # only because two of three still cleared the majority. The bound
                # is DISABLED as a rejection criterion (_REJECT_RATIO = 0.0,
                # so the guard above is unreachable) and forgery is prevented
                # structurally, so an unavailable bound costs nothing: it is
                # recorded as a diagnostic and never gates a rep. Only a
                # genuinely unusable timing is unverifiable.
                measurements["wall_bound_ratio"] = (
                    float(tc / wall_lower_bound) if wall_lower_bound > 0 else None)
                if not all(np.isfinite(v) and v > 0.0 for v in (tc, tb)):
                    rec["status"] = "unverifiable_timing"
                    repetitions.append(rec)
                    continue

                # v2: credited IS the internal timer. `clamped` stays in the record
                # (always False) so downstream analysis keyed on it still parses.
                credited = float(tc)
                clamped = False
                measurements["wall_bound_ratio"] = float(tc / wall_lower_bound)
                ratio = tb / credited
                ratios.append(float(ratio))
                measurements.update({
                    "candidate_credited_seconds": float(credited),
                    "speedup": float(ratio),
                    "clamped": clamped,
                })
                # The second ratio, against the reference built the candidate's
                # way. It is reported, never substituted: `speedup` remains the
                # anchor quantity every score in this study is expressed in.
                if "reference_matched" in observed:
                    tbm = float(observed["reference_matched"][0])
                    if tbm > 0:
                        measurements["reference_matched_seconds"] = tbm
                        measurements["speedup_matched"] = float(tbm / credited)
                        # anchor / matched isolates what the toolchain bought,
                        # since the two denominators differ only in how the same
                        # frozen source was built.
                        if ratio > 0:
                            measurements["toolchain_gain"] = float(ratio / (tbm / credited))
                rec["status"] = "accepted"
                rec["valid"] = True
                repetitions.append(rec)

            # v2 deterrence: a single implausible rep is dropped and never enters
            # the median, so it buys the candidate nothing - but repeated
            # implausible reps in ONE case are not jitter. Over the v1 corpus
            # (11,222 cases) exactly one case had >=2 under this guard, so the
            # threshold restores the deterrent v1's node-killing rule provided,
            # at a 0.009% false-positive rate, without letting one noisy rep
            # kill a node.
            if n_implausible >= 2:
                valid = False
                evaluation_status = "candidate_invalid"
                reason = (
                    f"implausible timing on {name}: {n_implausible}/{n_reps} reps "
                    f"below {_REJECT_RATIO:g}x the wall-clock lower bound")
            min_accepted = n_reps // 2 + 1
            measurable = bool(valid and len(ratios) >= min_accepted)
            if valid and not measurable:
                # v2: a rep dropped by the forge guard must not become a free retry -
                # failing to reach a plausible majority is a CANDIDATE failure.
                forged = n_implausible > n_reps - min_accepted
                if evaluation_status == "valid":
                    evaluation_status = (
                        "candidate_invalid" if forged else "measurement_invalid")
                reason = (
                    f"implausible timing on {name}: {n_implausible}/{n_reps} reps "
                    f"below {_REJECT_RATIO:g}x the wall-clock lower bound"
                    if forged else
                    f"insufficient matched repetitions on {name}: "
                    f"{len(ratios)}/{n_reps}, need {min_accepted}")
            speedup = _stats.median(ratios) if measurable else 0.0
            out_families[name] = {
                "speedup": float(speedup),
                "valid": measurable,
                "max_abs_error": max_abs,
                "n_clamped": n_clamped,
                "n_implausible": n_implausible,
                "credited_rule": "internal",
                "n_requested_repetitions": n_reps,
                "n_accepted_repetitions": len(ratios),
                "repetitions": repetitions,
            }
            # A single invalid shape invalidates the all-case score. Stop here so
            # a hanging candidate is recorded as candidate_invalid within the
            # worker budget instead of becoming a Slurm infrastructure timeout.
            if not measurable:
                break
    finally:
        if td_obj is not None:
            td_obj.cleanup()
    return {
        "compile_ok": compile_ok,
        "families": out_families,
        "reason": reason,
        "evaluation_status": evaluation_status,
        "candidate_cflags": list(_cand_flags),
        "rejected_cflags": list(_rej_flags),
        # Provenance of the DENOMINATOR, recorded on every result.
        "score_basis": "reference",
        # WHICH COMPILER produced these numbers. Bare `cc` resolves from the
        # job's module environment, which is not fixed on this machine, so a
        # score without it cannot be reproduced or compared.
        "toolchain": _toolchain_identity(
            _os_pin.environ.get("ARI_STENCIL_CC", "cc")),
        "candidate_toolchain": _select_candidate_cc(work_dir),
        "reference_cflags": list(_REFERENCE_CFLAGS),
        "measurement_environment": measurement_environment(),
    }


def _assert_expected_toolchain(cc: str) -> None:
    """Fail closed when the compiler is not the one the campaign pinned.

    THE THREAT. The harness compiles with whatever ``cc`` the job's module
    environment puts first on PATH, and on this machine that is not a constant:
    the login node gives GCC 11.5.0, the compute nodes GCC 8.5.0, and loading the
    vendor entry module brings a Fujitsu ``fcc`` whose -Kfast measured 111 GF/s
    against gcc's 385 on the same kernel. A campaign is 270 runs submitted as
    many jobs over hours; if any of them starts with a different module state,
    the compiler silently changes mid-experiment. That difference is larger than
    any effect being measured, and because runs are submitted per task/arm/seed
    it would be CONFOUNDED with the conditions rather than spread evenly.

    Recording the toolchain (see ``_toolchain_identity``) makes that detectable
    after the fact. This makes it non-silent at the time: set
    ``ARI_EXPECTED_CC_VERSION`` to a substring of the intended ``cc --version``
    line and any run whose compiler does not match stops as an infrastructure
    error instead of contributing a number. Unset, nothing is enforced — pinning
    is the campaign driver's decision, not this module's.

    The candidate cannot reach this: compile flags are screened by an allowlist
    that admits only -O/-f/-m/--param and denies -B, -specs and -fplugin, so the
    toolchain is not part of the search space.
    """
    want = _os_pin.environ.get("ARI_EXPECTED_CC_VERSION", "").strip()
    if not want:
        return
    got = _toolchain_identity(cc)
    if want not in got["version"]:
        raise HarnessInfrastructureError(
            f"toolchain mismatch: ARI_EXPECTED_CC_VERSION={want!r} but {cc} at "
            f"{got['resolved_path']} reports {got['version']!r}; refusing to "
            f"score, because a compiler change is larger than the effect being "
            f"measured")


def measure_node(work_dir: str, **kwargs) -> dict:
    """Score the node, falling back to its last known-good snapshot.

    In the previous campaign 86.8% of agent-authored invalid nodes had never
    recompiled their final source edit (odds ratio 26.2), so a node that ends
    broken usually had a working state a few edits earlier and the zero it scored
    measured an accident rather than its work. ``make check`` snapshots the
    source and flags into ``.lastgood/`` on every passing selftest; if the
    SUBMITTED candidate is invalid and a DIFFERENT snapshot exists, the snapshot
    is scored instead and the record says so.

    This is sound only because the selftest now measures what the evaluator
    measures (task #2). Under the v1 selftest, 45 of the recoverable nodes - 42
    of them stencil - were wrong-answer nodes whose "last good" state had been
    certified by a check that could not see the failure, so rolling back would
    have scored a certified-wrong program.

    The rollback never rescues a candidate the evaluator judged CORRECT but slow,
    and never runs twice: only a candidate_invalid verdict triggers it.
    """
    import hashlib as _hl
    import os as _os
    import shutil as _sh
    import tempfile as _tf

    result = _measure_node_once(work_dir, **kwargs)
    if result.get("evaluation_status") != "candidate_invalid":
        return result

    snap = _os.path.join(work_dir or "", ".lastgood")
    src = _os.path.join(snap, "candidate_stencil.c")
    if not _os.path.isfile(src):
        return result

    def _sha(path):
        try:
            return _hl.sha256(open(path, "rb").read()).hexdigest()
        except OSError:
            return None

    submitted = _os.path.join(work_dir, "candidate_stencil.c")
    if _sha(src) == _sha(submitted):
        return result                      # the snapshot IS what just failed

    td = _tf.mkdtemp(prefix="lastgood_")
    try:
        seed_work_dir(td)
        _sh.copy2(src, _os.path.join(td, "candidate_stencil.c"))
        # Everything in SCORE_INPUTS, not just the source: restoring the
        # code without the compiler that built it re-scores the last-good
        # candidate under the DEFAULT toolchain and reports the number as
        # if it were that candidate's.
        for _name in SCORE_INPUTS[1:]:
            _p = _os.path.join(snap, _name)
            if _os.path.isfile(_p):
                _sh.copy2(_p, _os.path.join(td, _name))
        rolled = _measure_node_once(td, **kwargs)
    except Exception:
        return result
    finally:
        _sh.rmtree(td, ignore_errors=True)

    if rolled.get("evaluation_status") == "candidate_invalid":
        return result                      # the snapshot is no better; keep the honest zero
    rolled["rolled_back"] = True
    rolled["rolled_back_from_sha256"] = _sha(submitted)
    rolled["rolled_back_to_sha256"] = _sha(src)
    rolled["submitted_reason"] = result.get("reason")
    return rolled

# ---------------------------------------------------------------------------
# What environment was this measured under?
#
# The scored process inherits the ambient environment, and on 2026-08-03 one
# ambient variable was measured moving a Fujitsu-built stencil by 5.9x
# (XOS_MMM_L_PAGING_POLICY, read only by the vendor large-page library, which
# only Fujitsu builds link). The reference is always built with the default
# compiler, so that variable moves the RATIO asymmetrically: it changes the
# candidate's side and not the denominator's.
#
# Eleven other candidates -- glibc allocator knobs, OpenMP runtime knobs, the
# large-page type -- were swept on a GCC build and moved the fixed term by
# nothing distinguishable from noise, so this records rather than restricts.
# Recording is the part that costs nothing and cannot be wrong: an unknown
# factor will always remain (this one was unknown all day), and a record can be
# consulted afterwards where an absent record cannot.
#
# SECRETS ARE NEVER RECORDED. The prefix allowlist admits only measurement
# variables, and any name that looks like a credential is dropped even if it
# somehow matches one.
# Prefixes, not names. A hand list records exactly the variables somebody
# thought of: the study manifest pinned 24 by name and none of them was
# XOS_MMM_L_PAGING_POLICY, which was later measured to move the same frozen
# source by 5.9x. The threading families below came the other way -- the manifest
# had them and this capture did not -- so neither set contained the other.
_ENV_PREFIXES = ("OMP_", "GOMP_", "KMP_", "XOS_", "FLIB_", "FJ_", "MALLOC_",
                 "LD_LIBRARY_PATH", "LD_PRELOAD", "NUMA",
                 # ARI_ as a whole, not one prefix per task. The per-task list
                 # missed ARI_CACHE_PROBLEM_FILES, ARI_EXPECTED_TOOLCHAINS and
                 # every knob of any task added later -- the same
                 # enumerate-by-name failure the manifest's hand list had. The
                 # secret filter below is what makes the wider net safe.
                 "ARI_",
                 # BLAS/threading runtimes: any of these silently re-threads a
                 # kernel that links one, changing the number without the code.
                 "OPENBLAS_", "GOTO_", "MKL_", "BLIS_", "VECLIB_", "NUMEXPR_")
_ENV_SECRET = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")


def measurement_environment(extra: dict | None = None) -> dict:
    """The measurement-relevant environment, plus a digest of it."""
    import hashlib as _hl
    import json as _js
    import os as _o
    env = {}
    for k, v in sorted(_o.environ.items()):
        if not k.startswith(_ENV_PREFIXES):
            continue
        if any(s in k.upper() for s in _ENV_SECRET):
            continue
        env[k] = v
    if extra:
        env.update({k: v for k, v in extra.items()
                    if not any(s in k.upper() for s in _ENV_SECRET)})
    digest = _hl.sha256(
        _js.dumps(env, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"variables": env, "sha256": digest,
            "note": "recorded, not restricted; an ambient variable outside this "
                    "prefix set is neither captured nor known to be harmless"}

# ---------------------------------------------------------------------------
def _isa_flags_for(cc: str) -> list[str]:
    """How THIS compiler spells "target the machine we are running on".

    The base flags carry an intent, not a literal: `-march=native` means "use
    this machine's ISA". Handing that spelling to every compiler is what broke
    candidate compiler selection -- `fcc -Nclang` is clang-7 based and answers
    `the clang compiler does not support '-march=native'`, so a candidate that
    wrote `fcc` into candidate_cc.txt was told the choice existed and then failed
    to compile every time, on all three tasks. The offer and the reality
    disagreed, and nothing checked that they agreed.

    fcc needs no flag at all: it targets A64FX and nothing else, so the intent is
    already satisfied. gcc and clang take the portable spelling.
    """
    import os as _o
    base = _o.path.basename(cc or "")
    if base in ("fcc", "FCC", "mpifcc", "mpiFCC"):
        return []
    return ["-march=native"]


# ── hardware counters for the SCORED region ────────────────────────────────
# NEVER SCORED, and deliberately so. This measures the same region the score is
# built from, with the same compiler and the same flags, but its numbers do not
# enter `speedup`, `valid`, or anything the evaluator reads. A profile that could
# move a score would be a second scoring channel with none of the anti-gaming
# surface of the first.
#
# WHY THE REGION AND NOT THE PROCESS. The timed window is one kernel call; around
# it in the same process sit the problem read, the serial NaN poison of the
# output and the write-out. Counting the whole process was measured at 7.16x the
# region's cycles on a compute node, and it drags the L2D ratio toward
# "memory bound" for every candidate, because the poison pass is pure
# write-allocate traffic. So the profiled build marks the region and
# region_counters gates on those marks.
#
# WHAT IT IS BLIND TO. The harness first-touches its buffers OUTSIDE the timed
# window (the poison loop is serial), so page-fault, TLB and NUMA-placement work
# is mostly not in here -- see [declares].blind_to. Only scratch the candidate
# allocates itself faults inside the region.
#
# COLD, ONCE, like the score. No warmup and no in-process repetition: a warm
# profile would describe a regime the score never measures. For statistics, run
# this again in a fresh process.
_COUNTERS_SRC = "workspace/tools/region_counters.c"


def _counters_binary(build_dir: str) -> tuple[str, str]:
    """Resolve region_counters, building it if needed. Returns (path, sha256).

    The source digest travels with the profile because region_counters lives in
    workspace/tools/, OUTSIDE this harness's [files] pins -- so unlike the scored
    scaffolding it is not content-addressed by the registry, and the record has
    to carry its own provenance or the profile is unattributable.
    """
    import hashlib as _hl
    import os as _o
    import subprocess as _sp

    repo = _o.path.dirname(_o.path.dirname(_o.path.dirname(
        _o.path.dirname(_o.path.abspath(__file__)))))
    src = _o.path.join(repo, _COUNTERS_SRC)
    if not _o.path.isfile(src):
        raise HarnessInfrastructureError(f"counter tool source not found: {src}")
    digest = _hl.sha256(open(src, "rb").read()).hexdigest()
    given = _os_pin.environ.get("ARI_REGION_COUNTERS")
    if given and _o.path.isfile(given):
        return given, digest
    exe = _o.path.join(build_dir, "region_counters")
    cc = _os_pin.environ.get("ARI_PROBE_CC") or "cc"
    cp = _sp.run([cc, "-O2", src, "-o", exe], capture_output=True, text=True,
                 timeout=120)
    if cp.returncode != 0:
        raise HarnessInfrastructureError(
            f"could not build the counter tool: {cp.stderr.strip()[-400:]}")
    return exe, digest


def _profile_common(*, task, work_dir, counters, digest, td, exe, run_one,
                    case, input_seed, line_bytes):
    """Run one gated, counted execution and return the record."""
    import json as _json
    import os as _o

    launcher = [counters, "--gate", "--json"]
    if line_bytes:
        launcher += ["--line-bytes", str(int(line_bytes))]
    launcher.append("--")          # region_counters needs it before the command
    cap: dict = {}
    t_internal = None
    error = None
    counters_out = None
    try:
        res = run_one(exe, td, tuple(launcher), cap)
        t_internal = res
    except Exception as exc:                      # noqa: BLE001 - recorded, not raised
        error = f"{type(exc).__name__}: {exc}"
    raw = (cap.get("stdout") or "").strip()
    if raw:
        try:
            counters_out = _json.loads(raw.splitlines()[-1])
        except ValueError:
            error = error or f"counter output was not JSON: {raw[:200]}"
    elif error is None:
        error = "the counter tool produced no output"

    return {
        "task": task,
        "scored": False,
        "case": case,
        "input_seed": input_seed,
        "credited_seconds": t_internal,
        "counters": counters_out,
        "error": error,
        # The same capture the score carries, so a profile can only ever be read
        # next to a score taken under the same conditions. check_environment_drift
        # compares these digests.
        "measurement_environment": measurement_environment(),
        "toolchain": _toolchain_identity(
            _os_pin.environ.get("ARI_STENCIL_CC", "cc")),
        "candidate_toolchain": _select_candidate_cc(work_dir),
        "counter_tool_sha256": digest,
        "threads": _os_pin.environ.get(
            "ARI_STENCIL_THREADS", _os_pin.environ.get("OMP_NUM_THREADS", "")),
        # Which node class produced this. The array job is submitted without an
        # explicit partition, so the scheduler decides; a profile compared across
        # architectures would be comparing two machines.
        "machine": _os_pin.uname().machine,
    }


def profile_node(work_dir: str, *, seed: int = 0, shape=None,
                 line_bytes: int | None = None) -> dict:
    """Counters for the candidate's SCORED region on one stencil shape.

    Uses the FIRST scored shape and repetition 0's input seed by default, so the
    profile describes a problem the score was actually taken on."""
    import os as _o
    import tempfile as _tf

    shape = tuple(shape) if shape else SHAPES[0]
    input_seed = seed * 100003 + 0
    nx0, ny0, nz0, nt0 = shape
    name = f"{nx0}x{ny0}x{nz0}t{nt0}"
    td_obj = _tf.TemporaryDirectory()
    try:
        counters, digest = _counters_binary(td_obj.name)
        _cand_flags, _ = _sanitize_candidate_flags(work_dir)
        exe = _compile_kernel("candidate", work_dir, td_obj.name,
                              extra_flags=_cand_flags,
                              main_src=_o.path.join(kernels_dir(),
                                                    "stencil_main_profiled.c"),
                              tag="candidate_profiled")
        u0, nx, ny, nz, nt = gen_problem(shape, seed=input_seed)

        def _run_one(exe, td, launcher, cap):
            ti, _tw, _u = _run_exe(exe, td, u0, nx, ny, nz, nt,
                                   launcher=launcher, capture=cap)
            return ti

        return _profile_common(
            task="stencil", work_dir=work_dir, counters=counters, digest=digest,
            td=td_obj.name, exe=exe, run_one=_run_one, case=name,
            input_seed=input_seed, line_bytes=line_bytes)
    finally:
        td_obj.cleanup()
