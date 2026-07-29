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
# Forge-guard thresholds (used in measure_node's timing cross-check):
#  _REJECT_NOISE_FLOOR — below this overhead-corrected wall the reps are pure
#    jitter, so the REJECTION rule is not applied (only the clamp is).
#  _REJECT_RATIO — reject only a gross discrepancy the noise cannot explain
#    (reported time < this fraction of the external lower bound).
_REJECT_NOISE_FLOOR = 0.02
_REJECT_RATIO = 0.05
_C0 = 0.5
_CW = 1.0 / 12.0


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
    r"|--param=[A-Za-z0-9_-]+=[0-9]+)$"
)
_FLAG_DENY_SUBSTR = (
    "plugin", "specs", "profile", "sanitize", "-fdump", "-fexec-charset",
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
    for tok in raw.split():
        if tok.startswith("#"):
            continue
        if len(accepted) >= _FLAG_MAX_TOKENS:
            rejected.append(tok)
            continue
        low = tok.lower()
        if any(bad in low for bad in _FLAG_DENY_SUBSTR) or not _FLAG_ALLOW.match(tok):
            rejected.append(tok)
        else:
            accepted.append(tok)
    return accepted, rejected


def _compile_kernel(kind: str, work_dir: str, out_td: str,
                    extra_flags=()) -> str:
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
    main_c = _os.path.join(kdir, "stencil_main.c")
    kern_c = (_os.path.join(kdir, "baseline_stencil.c") if kind == "baseline"
              else _os.path.join(work_dir or "", "candidate_stencil.c"))
    if not _os.path.isfile(kern_c):
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"kernel source not found ({kind}): {kern_c}")
    src_c = kern_c
    if kind == "candidate":
        import shutil as _sh
        src_c = _os.path.join(out_td, "candidate_stencil.c")
        _sh.copy2(kern_c, src_c)
    cc = _os.environ.get("ARI_STENCIL_CC", "cc")
    cflags = _os.environ.get("ARI_STENCIL_CFLAGS", "-O3 -fopenmp -march=native").split()
    exe = _os.path.join(out_td, f"kernel_{kind}.exe")
    # candidate-declared flags come AFTER the defaults so they win (gcc: last
    # occurrence of a conflicting flag takes effect); baseline passes none.
    cflags = [*cflags, *(extra_flags or ())]
    try:
        cp = _sub.run([cc, *cflags, f"-I{kdir}", main_c, src_c, "-o", exe, "-lm"],
                      capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise HarnessInfrastructureError(
            f"compiler invocation failed ({kind}): {exc}") from exc
    if cp.returncode != 0:
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"compile failed ({kind}): {cp.stderr.strip()[-600:]}")
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
    trusted baseline's tb/tb_wall and so shrinking _wall_kernel — the candidate
    slowing its own referee. Returns how many were killed.
    """
    import os as _o
    import signal as _sig
    me = _o.getpid()
    killed = 0
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


def _run_exe(exe: str, work_td: str, u0, nx: int, ny: int, nz: int, nt: int):
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
    with open(prob, "wb") as fh:
        np.array([nx, ny, nz, nt], dtype=np.int32).tofile(fh)
        u0.tofile(fh)
    for stale in (outf, tf):
        try:
            _os.remove(stale)
        except OSError:
            pass
    run_env = dict(_os.environ)
    # Respect an ambient OMP_NUM_THREADS (the allocation's thread budget) instead of
    # forcing 16: the harness default silently contradicted the declared run
    # configuration. Explicit ARI_STENCIL_THREADS still wins.
    run_env["OMP_NUM_THREADS"] = _os.environ.get(
        "ARI_STENCIL_THREADS", _os.environ.get("OMP_NUM_THREADS", "16"))
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


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    shapes: tuple[tuple[int, int, int, int], ...] = SHAPES,
    seed: int = 0,
    warmup: int = 1,   # accepted for compatibility; cold measurement uses no warmup
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
    import statistics as _stats
    import tempfile as _tmp

    n_reps = max(1, int(reps))
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"

    _become_subreaper()
    _cand_flags: list[str] = []
    _rej_flags: list[str] = []
    evaluation_status = "valid"
    td_obj = None
    exes: dict[str, str] = {}
    if run_kernel is None:
        td_obj = _tmp.TemporaryDirectory()
        _cand_flags, _rej_flags = _sanitize_candidate_flags(work_dir)
        try:
            exes["baseline"] = _compile_kernel("baseline", work_dir, td_obj.name)
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

        def run(kind, _wd, _u0, _nx, _ny, _nz, _nt):
            return _run_exe(exes[kind], td_obj.name, _u0, _nx, _ny, _nz, _nt)
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
            for r in range(n_reps):
                input_seed = seed * 100003 + r
                rec = {
                    "index": r,
                    "status": "started",
                    "valid": False,
                    "measurements": {"input_seed": input_seed},
                }
                u0, nx, ny, nz, nt = gen_problem(shape, seed=input_seed)
                u_ref = reference_jacobi(u0, nx, ny, nz, nt)
                observed: dict[str, tuple[float, float, Any]] = {}
                # Reverse the starting order by seed so odd repetition counts
                # are balanced across the preregistered seed blocks.
                order = (
                    ("candidate", "baseline")
                    if (r + seed) % 2 == 0
                    else ("baseline", "candidate")
                )
                rec["execution_order"] = list(order)
                for kind in order:
                    try:
                        observed[kind] = _unpack_run(
                            run(kind, work_dir, u0, nx, ny, nz, nt))
                    except Exception as exc:
                        if kind == "baseline":
                            raise HarnessInfrastructureError(
                                f"baseline run failed on {name}, rep {r}: {exc}") from exc
                        valid = False
                        evaluation_status = "candidate_invalid"
                        reason = f"candidate run failed on {name}, rep {r}: {exc}"
                        rec["status"] = "candidate_run_failed"
                        rec["measurements"]["error"] = str(exc)
                        repetitions.append(rec)
                        break
                if not valid:
                    break

                tc, tc_wall, u_cand = observed["candidate"]
                tb, tb_wall, _ = observed["baseline"]
                ok, ma = is_correct(u_cand, u_ref, u0, nt)
                max_abs = max(max_abs, ma)
                measurements = rec["measurements"]
                measurements.update({
                    "candidate_internal_seconds": float(tc),
                    "candidate_wall_seconds": float(tc_wall),
                    "baseline_internal_seconds": float(tb),
                    "baseline_wall_seconds": float(tb_wall),
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
                measurements["baseline_overhead_seconds"] = float(overhead)
                measurements["candidate_wall_lower_bound_seconds"] = float(wall_lower_bound)
                if (wall_lower_bound > _REJECT_NOISE_FLOOR
                        and tc < _REJECT_RATIO * wall_lower_bound):
                    valid = False
                    evaluation_status = "candidate_invalid"
                    reason = (
                        f"implausible timing on {name}: reported {tc:.6g}s but "
                        f"wall-clock implies ~{wall_lower_bound:.6g}s")
                    rec["status"] = "implausible_timing"
                    repetitions.append(rec)
                    break

                if not all(np.isfinite(v) and v > 0.0
                           for v in (wall_lower_bound, tc, tb)):
                    rec["status"] = "unverifiable_timing"
                    repetitions.append(rec)
                    continue

                credited = max(tc, wall_lower_bound)
                clamped = credited != tc
                n_clamped += int(clamped)
                ratio = tb / credited
                ratios.append(float(ratio))
                measurements.update({
                    "candidate_credited_seconds": float(credited),
                    "speedup": float(ratio),
                    "clamped": clamped,
                })
                rec["status"] = "accepted"
                rec["valid"] = True
                repetitions.append(rec)

            min_accepted = n_reps // 2 + 1
            measurable = bool(valid and len(ratios) >= min_accepted)
            if valid and not measurable:
                if evaluation_status == "valid":
                    evaluation_status = "measurement_invalid"
                reason = (
                    f"insufficient matched repetitions on {name}: "
                    f"{len(ratios)}/{n_reps}, need {min_accepted}")
            speedup = _stats.median(ratios) if measurable else 0.0
            out_families[name] = {
                "speedup": float(speedup),
                "valid": measurable,
                "max_abs_error": max_abs,
                "n_clamped": n_clamped,
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
    }
