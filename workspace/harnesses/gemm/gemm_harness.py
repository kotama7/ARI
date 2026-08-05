"""Dense GEMM measurement harness (handoff study task A) — measurement CORE.

GEMM (C = A·B, dense, fp64) is the deliberately *compute-bound* counterpart to
the SpMM task: two independent insights — cache-friendly loop order (ikj) and
OpenMP parallelism — compound multiplicatively (each ~tens×, together ~hundreds×
over a naive ijl kernel), with blocking/SIMD on top. That gives a genuine
multi-rung optimization-QUALITY gradient (unlike SpMM's parallelize-or-not
cliff), so the handoff arms can separate by *how far up the ladder* a node gets.

v2 SCORE DENOMINATOR. The score is t_reference / t_candidate against the frozen
COMPETENT reference in gemm_kernels/reference_gemm.c, not against a naive
kernel. Against the naive kernel the reachable range was compressed to 1.17x
(median agent 81.3, best known rung 95.51, unreachable ceiling 111), which is
why "did the search find a better kernel" sat below the measurement band. The
competent reference opens that to 2.86x at the v2 problem size and removes the
ceiling. The resulting scale: a plain vectorised kernel lands near 0.35, adding
only the SVE flag reaches 0.80, and closing the rest needs real blocking work.

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

# PREREG: the fixed shape set (n, p, m) the geomean is taken over. Square +
# tall + fat so a kernel hardcoded to one shape (or to n==m==p) fails the others.
#
# v2 SIZE. Every shape's working set must exceed the 8 MiB CMG L2, or blocking
# cannot pay and the objective cannot see it. v1's 512-cube kept all three
# matrices resident (6.0 MiB), and there an independently written register-
# blocked kernel measured 1.046x a plain vectorised one — a tie inside the 2.8%
# band. At the v2 sizes the same pair separates to 1.289x. Working sets here are
# 24 / 18 / 18 MiB.
#
# m MUST NOT BE DIVISIBLE BY 32. The B-column stride aliases the L1 sets: at
# n=m=p=2048 the naive kernel took 242 s, over the 120 s per-process cap, while
# m=2040 took 45 s — a 5.35x swing from a 0.4% change in flops. 1000, 500 and
# 2000 are all safe (2000/32 = 62.5).
SHAPES: tuple[tuple[int, int, int], ...] = (
    (1000, 1000, 1000),   # square, 2.0 GFLOP, 22.9 MiB working set
    (2000, 500, 500),     # tall,   1.0 GFLOP, 17.2 MiB
    (1500, 600, 1500),    # narrow output / long reduction, 2.7 GFLOP, 30.9 MiB
)
# THE THIRD SHAPE WAS 500x500x2000 AND WAS CHANGED, measured in
# 20260803_shape/shape.json. n=500 over 48 threads is 10.4 rows per thread, so
# every row-parallel kernel is load-imbalanced there — including the unblocked
# ikj that the corpus's best gemm candidates actually write. Over 8 independent
# scorings the ikj's own credited time spread 4.73% at that shape against
# 0.63% for the blocked reference, i.e. the SHAPE made the score noisy for
# exactly the code the search produces. It also put the reference 1.306x behind
# ikj, so the denominator lost to the textbook kernel.
#
# Raising n alone does not fix it (1000x600x2000: ikj still 4.34%). 1500x600x1500
# does: blocked 7.341 ms / 0.18%, ikj 8.871 ms / 3.37%, ikj/blocked = 0.828, so
# the reference is 1.21x AHEAD of the textbook kernel and the stable path is also
# the fast one. The regime survives — p/m = 2.5 still stresses a long reduction
# against a narrow output — and 600 is not a multiple of 32.

# FROZEN reference build flags, appended to the defaults for the reference
# translation unit ONLY. The reference is defined as "competently blocked AND
# VECTORISED FOR THE TARGET ISA"; on the scoring target -march=native emits ZERO
# SVE (verified by objdump: z-operand count 0 under native, 134 under +sve, and
# 101.89 vs 471.51 GF/s on an FMA microbenchmark), so without this flag the
# frozen reference would silently be a weaker implementation than the measured
# one — which would inflate every score by about 2.3x without any warning.
#
# The default is chosen by ISA rather than hardcoded, because the login node is
# x86_64 while the compute nodes are aarch64 and the harness must stay importable
# and testable on both. Whichever set is used is RECORDED in the result, so a run
# built with the weaker reference is visible in the data instead of silent.
# Overridable only to port the harness to another target, never to retune it.
def _default_reference_cflags() -> str:
    """Build the reference the way a competent user of this toolchain would.

    -ffast-math is included because the reference must not be handicapped
    relative to the candidates it is the bar for: candidates may declare it
    (226 of 2133 v1 flag files did), and the 971.61x figure this reference's
    scale was calibrated from was measured with it. Leaving it off would make
    the frozen reference weaker than the implementation actually measured.
    """
    import platform as _plat

    if _plat.machine() != "aarch64":
        return "-ffast-math"
    return "-march=armv8.2-a+sve -ffast-math"


_REFERENCE_CFLAGS: tuple[str, ...] = tuple(
    _os_pin.environ.get("ARI_GEMM_REF_CFLAGS", _default_reference_cflags()).split()
)
_FP64_U = 2.0 ** -53  # double-precision unit roundoff
_C_EPS = 8.0          # PREREG correctness constant (same as SpMM)
# Forge-guard thresholds (used in measure_node's timing cross-check).
# v2: there is no clamp any more — the wall bound REJECTS a rep, it never floors
# one — so _REJECT_RATIO is now the whole forge guard and had to be recalibrated.
#  _REJECT_NOISE_FLOOR — below this overhead-corrected wall the reps are pure
#    jitter, so the rejection rule is not applied at all.
#  _REJECT_RATIO — reject a rep whose reported time is below this fraction of
#    the external lower bound. Calibrated on the 82,320 accepted reps of the v1
#    campaign, where tc/wall_lower_bound was distributed as
#        task     min    p0.1     p1     p50
#        gemm    0.095   0.484   0.819  0.882
#        spmm    0.228   0.917   0.942  0.979
#        stencil 0.758   0.981   0.988  0.995
#    NOTE the ratio alone does NOT bound the catchable forgery: with an
#    absolute slack S, catching a factor F needs T_real > S/(R - 1/F), which
#    diverges as F -> 2. At the scored 512-cube shape the smallest catchable
#    forgery was measured at 3.98x, and the guard cannot fire at all unless
#    the wall bound exceeds S/R = 2 ms. At 0.50 this false-rejects
#    0.11% / 0.01% / 0.00% of real reps — and a false rejection now costs one
#    repetition, not the node, because the rule `continue`s instead of breaking.
#    The old 0.05 only caught a >=20x forgery, which was tolerable only because
#    the clamp silently absorbed everything smaller.
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


def _run_timeout_seconds() -> float:
    """Frozen per-process resource limit for candidate and baseline executions."""
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
# v2: the work_dir-relative files that actually determine the score. Search
# control uses these to tell a real edit from a pure re-measurement; the v1
# rule diffed the whole work_dir, which never fired because every node
# rewrites results.json. Complete by construction: the evaluator compiles
# this source alone, from a header-less copy, against the sha256-pinned
# kernels dir, plus these flags - nothing else in the node dir reaches it.
SCORE_INPUTS: tuple[str, ...] = ("candidate_gemm.c", "candidate_flags.txt")


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

    cand_dst = _os.path.join(work_dir, "candidate_gemm.c")
    if not _os.path.exists(cand_dst):
        cand_src = _os.path.join(src_dir, "candidate_gemm.c")
        if _os.path.isfile(cand_src):
            _sh.copy2(cand_src, cand_dst)
            written.append("candidate_gemm.c")
    return written


# ── Candidate-declared compile flags (design C: flags are part of the search) ──
# The candidate may declare its OWN optimization flags in ``candidate_flags.txt``
# next to its kernel. They are applied to the CANDIDATE COMPILE ONLY. So the
# score means
#   (candidate source + candidate flags) vs (frozen reference + _REFERENCE_CFLAGS),
# which is what tuning an HPC kernel actually means.
#
# The reference gets a vectorisation flag the candidate is NOT denied: it may
# declare the same one, and on this toolchain that single flag is worth 2.28x.
# The point of the objective is that the flag alone takes a plain vectorised
# kernel to about 0.80 of the reference and the remaining gap has to be closed
# by writing a better kernel.
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


def _select_candidate_cc(work_dir: str) -> dict:
    """Resolve the candidate's declared compiler. Returns a record, never raises.

    ``{"requested", "cc", "resolved_path", "version", "status"}`` where status is
    one of ``default`` (nothing declared), ``selected``, ``not_allowed`` or
    ``unavailable``. The last two fall back to the default compiler and say so,
    so a node is never lost to a typo or a missing vendor module.
    """
    import os as _o
    import shutil as _sh

    default = _os_pin.environ.get("ARI_GEMM_CC", "cc")
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
                    extra_flags=()) -> str:
    """Compile ``gemm_main.c`` + the {reference|baseline|candidate} kernel into
    ``out_td``; return the exe path. The reference and baseline come from the
    package ``kernels_dir()`` and the candidate ONLY from ``work_dir`` — a
    tampered fixture copy in work_dir cannot affect the score. No BLAS is linked.

    ``reference`` is the v2 score denominator and is compiled with the defaults
    PLUS the frozen ``_REFERENCE_CFLAGS``; the candidate gets the defaults plus
    its own declared flags. Both therefore get the same *opportunity* to
    vectorise — the candidate may declare the same flag and does not have to
    beat a reference built with an option it is denied. ``baseline`` is the old
    naive kernel, retained as the absolute calibration anchor; it is not on the
    scoring path."""
    import os as _os
    import subprocess as _sub
    kdir = kernels_dir()
    main_c = _os.path.join(kdir, "gemm_main.c")
    _PKG_KERNELS = {
        "reference": "reference_gemm.c",
        "baseline": "baseline_gemm.c",
    }
    # reference_matched is the reference SOURCE built the candidate's way, so the
    # only difference left against the candidate is the source itself.
    _src_kind = "reference" if kind == "reference_matched" else kind
    kern_c = (_os.path.join(kdir, _PKG_KERNELS[_src_kind]) if _src_kind in _PKG_KERNELS
              else _os.path.join(work_dir or "", "candidate_gemm.c"))
    if not _os.path.isfile(kern_c):
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"kernel source not found ({kind}): {kern_c}")
    if kind == "reference":
        extra_flags = (*_REFERENCE_CFLAGS, *(extra_flags or ()))
    # v2: compile the candidate from a HEADER-LESS copy inside out_td. A
    # quoted #include searches the including file's OWN directory first, so a
    # candidate sitting in work_dir would bind to a work_dir copy of the
    # kernel header instead of the sha256-pinned one. The frozen stencil
    # harness did this; gemm and spmm did NOT, so both were exposed to a
    # tampered header. v2 applies it to all three.
    src_c = kern_c
    if kind == "candidate":
        import shutil as _sh
        src_c = _os.path.join(out_td, "candidate_gemm.c")
        _sh.copy2(kern_c, src_c)

    # The CANDIDATE process is built entirely with the compiler the candidate
    # selected — driver included. Mixing objects would mix OpenMP runtimes
    # (libgomp against libomp), and the pre-timer team creation lives in the
    # driver, so a mixed build would create the team in one runtime and run the
    # kernel in another. The driver source is hash-pinned either way, so
    # compiling it with a different compiler does not weaken integrity.
    # The REFERENCE and BASELINE always use the default toolchain: the score is a
    # ratio against one fixed object, and that object must not move.
    _cc_default = _os.environ.get("ARI_GEMM_CC", "cc")
    if kind in ("candidate", "reference_matched"):
        _sel = _select_candidate_cc(work_dir)
        _assert_selected_toolchain(_sel)
        cc = _sel.get("resolved_path") or _cc_default
    else:
        cc = _cc_default
    # The ISA flag is chosen for the compiler actually in use; see
    # _isa_flags_for. ARI_GEMM_CFLAGS still overrides everything.
    _env_cflags = _os.environ.get("ARI_GEMM_CFLAGS")
    base_cflags = (_env_cflags.split() if _env_cflags
                   else ["-O3", "-fopenmp", *_isa_flags_for(cc)])
    exe = _os.path.join(out_td, f"kernel_{kind}.exe")
    main_o = _os.path.join(out_td, f"main_{kind}.o")
    kern_o = _os.path.join(out_td, f"kern_{kind}.o")

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
    } - {"gemm"})
    if extra:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(
            f"{kind} kernel exports symbols other than 'gemm': {extra[:8]}")

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


def _run_exe(exe: str, work_td: str, A, B, problem_key: str | None = None,
             ld_library_path: str | None = None):
    """Run ONE cold timed call of ``exe`` on (A, B) in a fresh process; return
    ``(t_internal, t_wall, C)``.

    The kernel's OWN in-process clock is written to ``timing.bin`` (``t_internal``)
    but that file is NOT trustworthy: the candidate is linked into the same
    process and can locate + overwrite it (e.g. via ``/proc/self/cmdline`` or the
    fixed basename in the shared temp dir), forging an arbitrarily small time.
    So we ALSO record the EXTERNAL Python wall-clock around ``subprocess.run``
    (``t_wall``) — measured OUTSIDE the candidate's process, hence unforgeable in
    the "faster" direction. ``measure_node`` cross-checks the two: if the reported
    internal time is implausibly below what the wall-clock allows, the timer was
    forged and the family is rejected."""
    import os as _os
    import subprocess as _sub
    import time as _time
    A = np.ascontiguousarray(np.asarray(A, dtype=np.float64))
    B = np.ascontiguousarray(np.asarray(B, dtype=np.float64))
    n, p = int(A.shape[0]), int(A.shape[1])
    m = int(B.shape[1])
    prob = _os.path.join(work_td, "problem.bin")
    outf = _os.path.join(work_td, "c.bin")
    tf = _os.path.join(work_td, "timing.bin")

    def _write_problem(path):
        with open(path, "wb") as fh:
            np.array([n, m, p], dtype=np.int32).tofile(fh)
            A.tofile(fh)
            B.tofile(fh)


    # The problem file was written afresh before EVERY process launch, and within
    # one repetition the candidate and the reference are handed the SAME problem,
    # so it was written twice identically; because the seeds are a deterministic
    # function of the repetition index, every node in the campaign regenerated
    # the same files again. The file is content-determined by the shape and the
    # input seed, so it is cached under ARI_HARNESS_CACHE and HARD LINKED into
    # the run directory. Anti-gaming is untouched: the path the scored process
    # sees and the bytes behind it are exactly what they were, and the problem is
    # still fresh per repetition because the input seed is part of the key.
    expect_bytes = 12 + A.nbytes + B.nbytes
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
    # configuration. Explicit ARI_GEMM_THREADS still wins.
    run_env["OMP_NUM_THREADS"] = _os.environ.get(
        "ARI_GEMM_THREADS", _os.environ.get("OMP_NUM_THREADS", "16"))
    # A candidate may select a compiler whose runtime is not on the default
    # loader path. The vendor fcc is the case that matters here: it compiles and
    # links fine, then the executable dies with "libfjomphk.so: cannot open
    # shared object file" because that library only becomes visible once the
    # vendor entry module is loaded. Prepending the selected compiler's own
    # runtime directories fixes it WITHOUT loading a module into the scoring
    # process, which would change the environment for every later run in the
    # job. Only the candidate's process gets this; the reference's does not.
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
    _pr = _sub.Popen([exe, prob, outf, tf], stdout=_sub.PIPE, stderr=_sub.PIPE,
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
    rp = _sub.CompletedProcess(_pr.args, _pr.returncode, _out, _err)
    if rp.returncode != 0:
        raise RuntimeError(f"run failed: {rp.stderr.strip()[-600:]}")
    t = np.fromfile(tf, dtype=np.float64)
    if t.size < 1:
        raise RuntimeError("kernel wrote no timing")
    C = np.fromfile(outf, dtype=np.float64)
    if C.size != n * m:
        raise RuntimeError(f"kernel wrote {C.size} outputs, expected {n * m}")
    return float(t[0]), float(t_wall), C.reshape(n, m)


def _default_run_kernel(kind: str, work_dir: str, A, B):
    """Compile + run ONE cold timed call; return ``(t_internal, C)``. Kept for the
    login self-test; ``measure_node`` compiles once and reuses the exe."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        exe = _compile_kernel(kind, work_dir, td)
        ti, _tw, C = _run_exe(exe, td, A, B)
        return ti, C


def _unpack_run(res):
    """Normalize a runner result to ``(t_internal, t_wall, C)``. The real
    ``_run_exe`` returns all three; an INJECTED test runner returns ``(t, C)``,
    for which wall==internal (its cross-check is a no-op)."""
    if len(res) == 3:
        return float(res[0]), float(res[1]), res[2]
    ti, C = res
    return float(ti), float(ti), C


def _measure_node_once(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    shapes: tuple[tuple[int, int, int], ...] = SHAPES,
    seed: int = 0,
    warmup: int = 1,   # accepted for compatibility; cold measurement uses no warmup
    reps: int = 3,
) -> dict:
    """Measure a node's candidate GEMM against the fixed shape set.

    Each repetition runs a fresh random problem and verifies the candidate output.
    Candidate and reference are run as a matched pair, with alternating order.
    The case score is the median of accepted per-pair
    ``reference_time / credited_candidate_time`` ratios.

    The reference is re-measured on EVERY repetition rather than once per
    allocation. That was affordable only after the denominator stopped being the
    naive kernel: the reference costs about 5 ms where naive cost 5.1 s, a 970x
    reduction, so the matched pair is now the cheap option as well as the correct
    one. It matters because identical binaries were measured 2.4-2.9% apart
    across allocations, consistent in sign; pairing every repetition cancels that
    drift instead of importing it into the score.

    Returns the dict ``DeterministicEvaluator._score`` consumes:
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
            # Compile trusted infrastructure first so its failure is never
            # misclassified as a bad candidate.
            exes["reference"] = _compile_kernel("reference", work_dir, td_obj.name)
            # A SECOND DENOMINATOR, same frozen source, built with whatever
            # toolchain the candidate chose. The anchor reference is always built
            # with the default compiler, so a candidate selecting another one is
            # compared across a compiler boundary, and anything acting on one
            # side of it moves the ratio without touching either program.
            # Measured on the stencil 2026-08-03: with XOS_MMM_L_PAGING_POLICY
            # unset the anchor ratio is 0.2004 and with demand:demand:demand it
            # is 1.1781 -- 5.9x -- while the matched ratio stays 1.0028 / 0.9993
            # because both sides move together. Neither denominator replaces the
            # other: anchor is the end-to-end result including the compiler
            # choice, matched is the code alone, and their quotient is what the
            # toolchain bought.
            _sel_cc = _select_candidate_cc(work_dir)
            if _sel_cc.get("status") == "selected":
                exes["reference_matched"] = _compile_kernel(
                    "reference_matched", work_dir, td_obj.name,
                    extra_flags=_cand_flags)
            exes["candidate"] = _compile_kernel(
                "candidate", work_dir, td_obj.name, extra_flags=_cand_flags)
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

        # The candidate's process may need its selected compiler's runtime on
        # the loader path; the reference's must not be given anything extra,
        # because the denominator has to stay exactly the object it always was.
        _cand_libs = _runtime_libs_for(
            (_select_candidate_cc(work_dir) or {}).get("resolved_path"))

        def run(kind, _wd, _A, _B):
            return _run_exe(exes[kind], td_obj.name, _A, _B,
                            problem_key=_problem_key[0],
                            ld_library_path=(_cand_libs
                                             if kind in ("candidate", "reference_matched")
                                             else None))
    else:
        run = run_kernel

    try:
        for shape in shapes:
            name = "x".join(str(s) for s in shape)
            ratios: list[float] = []
            repetitions: list[dict[str, Any]] = []
            valid = True
            max_rel = 0.0
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
                _problem_key[0] = f"gemm_{name}_s{input_seed}"
                A, B = gen_problem(shape, seed=input_seed)
                C_ref = reference_gemm(A, B)
                observed: dict[str, tuple[float, float, Any]] = {}
                # Alternate within a run and reverse the starting order by seed.
                # This balances the unmatched repetition from odd rep counts
                # across the preregistered even number of seed blocks.
                order = (
                    ("candidate", "reference")
                    if (r + seed) % 2 == 0
                    else ("reference", "candidate")
                )
                rec["execution_order"] = list(order)
                for kind in order:
                    try:
                        observed[kind] = _unpack_run(run(kind, work_dir, A, B))
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

                tc, tc_wall, C_cand = observed["candidate"]
                # The matched denominator runs in the SAME repetition, so it
                # sees the node state the pair did. Its failure is never fatal:
                # the anchor ratio is the primary quantity and must not be lost
                # because a second build of the reference misbehaved.
                if "reference_matched" in exes:
                    try:
                        observed["reference_matched"] = _unpack_run(
                            run("reference_matched", work_dir, A, B))
                    except Exception as exc:
                        rec["measurements"]["reference_matched_error"] = str(exc)

                tb, tb_wall, C_ref_run = observed["reference"]
                # VERIFY THE DENOMINATOR TOO, once per case. The reference's
                # output was being discarded, so its correctness was only ever
                # checked by a unit test at 64x48x32 - and "correct small" does
                # not imply "correct at the scored size". A reference that were
                # wrong AND fast at 1000^3 would deflate every candidate's score
                # systematically and nothing here would notice. The numpy oracle
                # is already computed for the candidate, so this costs one extra
                # comparison per case rather than per repetition.
                if r == 0:
                    ref_ok, ref_mr = is_correct(C_ref_run, C_ref, A, B)
                    if not ref_ok:
                        raise HarnessInfrastructureError(
                            f"the FROZEN REFERENCE is incorrect on {name} at the "
                            f"scored size (max_rel={ref_mr}); every score computed "
                            f"against it would be meaningless")
                ok, mr = is_correct(C_cand, C_ref, A, B)
                max_rel = max(max_rel, mr)
                measurements = rec["measurements"]
                measurements.update({
                    "candidate_internal_seconds": float(tc),
                    "candidate_wall_seconds": float(tc_wall),
                    "reference_internal_seconds": float(tb),
                    "reference_wall_seconds": float(tb_wall),
                    "max_relative_error": float(mr),
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
                # v2 CHANGE. The wall bound is a FORGERY CHECK, not a floor.
                # It is not a tight lower bound on kernel time: the candidate's
                # OpenMP team teardown runs after the internal timer stops but
                # inside the process wall, so wall_lower_bound systematically
                # exceeds tc. Over the 82k accepted reps of the v1 campaign the
                # median tc/bound was 0.882 (gemm) / 0.979 (spmm) / 0.995
                # (stencil). Flooring the credited time with this bound put
                # 47-61% non-kernel content into the gemm score, bound in >99%
                # of reps, and left the metric unable to see a measured 1.58x
                # ISA-level win. So: reject a rep whose reported time is
                # implausibly far below the bound, and never floor it.
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

                # v2: credited IS the internal timer. `clamped` is retained at
                # False so downstream analysis code keyed on it still parses.
                credited = float(tc)
                clamped = False
                measurements["wall_bound_ratio"] = float(tc / wall_lower_bound) \
                    if wall_lower_bound > 0 else float("inf")
                ratio = tb / credited
                ratios.append(float(ratio))
                measurements.update({
                    "candidate_credited_seconds": float(credited),
                    "speedup": float(ratio),
                    "clamped": clamped,
                })
                # The second ratio, against the reference built the candidate's
                # way. Reported, never substituted: `speedup` stays the anchor
                # quantity every score in this study is expressed in.
                if "reference_matched" in observed:
                    tbm = float(observed["reference_matched"][0])
                    if tbm > 0:
                        measurements["reference_matched_seconds"] = tbm
                        measurements["speedup_matched"] = float(tbm / credited)
                        if ratio > 0:
                            measurements["toolchain_gain"] = float(
                                ratio / (tbm / credited))

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
                # v2: a rep rejected by the forge guard no longer kills the node
                # outright, but a candidate that cannot reach a majority of
                # plausible reps is still a CANDIDATE failure, not a measurement
                # one — otherwise dropping the clamp would turn a caught forgery
                # into a free retry.
                forged = n_implausible > n_reps - min_accepted
                if evaluation_status == "valid":
                    evaluation_status = (
                        "candidate_invalid" if forged else "measurement_invalid")
                reason = (
                    f"implausible timing on {name}: {n_implausible}/{n_reps} reps "
                    f"reported below {_REJECT_RATIO:g}x the wall-clock lower bound"
                    if forged else
                    f"insufficient matched repetitions on {name}: "
                    f"{len(ratios)}/{n_reps}, need {min_accepted}")
            speedup = _stats.median(ratios) if measurable else 0.0
            out_families[name] = {
                "speedup": float(speedup),
                "valid": measurable,
                "max_relative_error": max_rel,
                "n_clamped": n_clamped,
                "n_implausible": n_implausible,
                "credited_rule": "internal",
                "n_requested_repetitions": n_reps,
                "n_accepted_repetitions": len(ratios),
                "repetitions": repetitions,
            }
            # Validity is all-or-nothing across cases. Once one case is invalid,
            # running the remaining cases can only waste the allocation and turn
            # a scientific candidate failure into a Slurm timeout.
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
        # Provenance of the DENOMINATOR. Recorded on every result so a run whose
        # reference was built without the target's vector flags — which would
        # inflate every score by about 2.3x — is visible in the data.
        "score_basis": "reference",
        # WHICH COMPILER produced these numbers. Bare `cc` resolves from the
        # job's module environment, which is not fixed on this machine, so a
        # score without it cannot be reproduced or compared.
        "toolchain": _toolchain_identity(
            _os_pin.environ.get("ARI_GEMM_CC", "cc")),
        # WHICH COMPILER THE CANDIDATE CHOSE, and whether it got it. A run
        # where the vendor module was absent falls back and says so, so a
        # score is never silently attributed to a compiler that never ran.
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
    _assert_expected_toolchain(
        _os_pin.environ.get("ARI_GEMM_CC", "cc"))

    import hashlib as _hl
    import os as _os
    import shutil as _sh
    import tempfile as _tf

    result = _measure_node_once(work_dir, **kwargs)
    if result.get("evaluation_status") != "candidate_invalid":
        return result

    snap = _os.path.join(work_dir or "", ".lastgood")
    src = _os.path.join(snap, "candidate_gemm.c")
    if not _os.path.isfile(src):
        return result

    def _sha(path):
        try:
            return _hl.sha256(open(path, "rb").read()).hexdigest()
        except OSError:
            return None

    submitted = _os.path.join(work_dir, "candidate_gemm.c")
    if _sha(src) == _sha(submitted):
        return result                      # the snapshot IS what just failed

    td = _tf.mkdtemp(prefix="lastgood_")
    try:
        seed_work_dir(td)
        _sh.copy2(src, _os.path.join(td, "candidate_gemm.c"))
        fl = _os.path.join(snap, "candidate_flags.txt")
        if _os.path.isfile(fl):
            _sh.copy2(fl, _os.path.join(td, "candidate_flags.txt"))
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
