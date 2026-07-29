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
import re as _re_flags
from typing import Any, Callable

import numpy as np
import scipy.sparse as sp

# PREREG: the fixed family set the geomean is taken over.
FAMILIES: tuple[str, ...] = (
    "uniform", "banded", "power_law", "block", "diagonal_dominant", "skewed",
)
_FP64_U = 2.0 ** -53  # double-precision unit roundoff
# Forge-guard thresholds (used in measure_node's timing cross-check):
#  _REJECT_NOISE_FLOOR — below this overhead-corrected wall the reps are pure
#    jitter, so the REJECTION rule is not applied (only the clamp is).
#  _REJECT_RATIO — reject only a gross discrepancy the noise cannot explain
#    (reported time < this fraction of the external lower bound).
_REJECT_NOISE_FLOOR = 0.02
_REJECT_RATIO = 0.05


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
    """Compile ``spmm_main.c`` + the {baseline|candidate} kernel into ``out_td``;
    return the exe path. IDENTICAL compiler + flags for both (anti-gaming). The
    baseline comes from the package ``kernels_dir()`` and the candidate ONLY from
    ``work_dir`` — a tampered fixture copy in work_dir cannot affect the score.
    No BLAS is linked."""
    import os as _os
    import subprocess as _sub
    kdir = kernels_dir()
    main_c = _os.path.join(kdir, "spmm_main.c")
    kern_c = (_os.path.join(kdir, "baseline_spmm.c") if kind == "baseline"
              else _os.path.join(work_dir or "", "candidate_spmm.c"))
    if not _os.path.isfile(kern_c):
        exc = CandidateInvalidError if kind == "candidate" else HarnessInfrastructureError
        raise exc(f"kernel source not found ({kind}): {kern_c}")
    cc = _os.environ.get("ARI_SPMM_CC", "cc")
    cflags = _os.environ.get("ARI_SPMM_CFLAGS", "-O3 -fopenmp").split()
    exe = _os.path.join(out_td, f"kernel_{kind}.exe")
    # candidate-declared flags come AFTER the defaults so they win (gcc: last
    # occurrence of a conflicting flag takes effect); baseline passes none.
    cflags = [*cflags, *(extra_flags or ())]
    try:
        cp = _sub.run([cc, *cflags, f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"],
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


def _run_exe(exe: str, work_td: str, A, X):
    """Run ONE cold timed call of ``exe`` on (A, X) in a fresh process; return
    ``(t_internal, t_wall, Y)``.

    The kernel's OWN in-process clock is written to ``timing.bin`` (``t_internal``,
    argv[3]) but that file is NOT trustworthy: the candidate is linked into the
    same process and can locate + overwrite it (e.g. via ``/proc/self/cmdline`` or
    the fixed basename in the shared temp dir), forging an arbitrarily small time.
    So we ALSO record the EXTERNAL Python wall-clock around ``subprocess.run``
    (``t_wall``) — measured OUTSIDE the candidate's process, hence unforgeable in
    the "faster" direction. ``measure_node`` cross-checks the two: if the reported
    internal time is implausibly below what the wall-clock allows, the timer was
    forged and the family is rejected. A short output (partial write) raises.

    The OpenMP thread budget is fixed by the batch job. Without this, libgomp
    defaults to ALL cores
    (e.g. 192) which, on the study's matrices, is pure overhead — even a perfect
    kernel measures ~1x. The baseline is single-threaded (no pragmas), so this
    only caps the candidate's parallelism. The study uses 48 threads on fx700;
    ``ARI_SPMM_THREADS`` is recorded and takes precedence over
    ``OMP_NUM_THREADS``."""
    import os as _os
    import subprocess as _sub
    import time as _time
    Acsr = sp.csr_matrix(A).astype(np.float64)
    Acsr.sort_indices()
    Xc = np.ascontiguousarray(np.asarray(X, dtype=np.float64))
    n, m = int(Acsr.shape[0]), int(Acsr.shape[1])
    k = int(Xc.shape[1])
    nnz = int(Acsr.nnz)
    prob = _os.path.join(work_td, "problem.bin")
    outf = _os.path.join(work_td, "y.bin")
    tf = _os.path.join(work_td, "timing.bin")
    with open(prob, "wb") as fh:
        np.array([n, m, k, nnz], dtype=np.int32).tofile(fh)
        Acsr.indptr.astype(np.int32).tofile(fh)
        Acsr.indices.astype(np.int32).tofile(fh)
        Acsr.data.astype(np.float64).tofile(fh)
        Xc.tofile(fh)
    for stale in (outf, tf):
        try:
            _os.remove(stale)
        except OSError:
            pass
    run_env = dict(_os.environ)
    # Respect an ambient OMP_NUM_THREADS (the allocation's thread budget) instead of
    # forcing 16: the harness default silently contradicted the declared run
    # configuration. Explicit ARI_SPMM_THREADS still wins.
    run_env["OMP_NUM_THREADS"] = _os.environ.get(
        "ARI_SPMM_THREADS", _os.environ.get("OMP_NUM_THREADS", "16"))
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
    Y = np.fromfile(outf, dtype=np.float64)
    if Y.size != n * k:
        raise RuntimeError(f"kernel wrote {Y.size} outputs, expected {n * k}")
    return float(t[0]), float(t_wall), Y.reshape(n, k)


def _default_run_kernel(kind: str, work_dir: str, A, X):
    """Compile + run ONE cold timed call; return ``(seconds, Y)``.

    ``kind="baseline"`` compiles the frozen ``baseline_spmm.c``; ``"candidate"``
    compiles the agent's ``candidate_spmm.c`` from ``work_dir``. IDENTICAL
    compiler + flags for both (anti-gaming). Kept for the login self-test;
    ``measure_node`` compiles once and reuses the exe across reps.
    """
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as td:
        exe = _compile_kernel(kind, work_dir, td)
        ti, _tw, Y = _run_exe(exe, td, A, X)
        return ti, Y


def _unpack_run(res):
    """Normalize a runner result to ``(t_internal, t_wall, Y)``. The real
    ``_run_exe`` returns all three; an INJECTED test runner returns ``(t, Y)``,
    for which wall==internal (its cross-check is a no-op)."""
    if len(res) == 3:
        return float(res[0]), float(res[1]), res[2]
    ti, Y = res
    return float(ti), float(ti), Y


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    families: tuple[str, ...] = FAMILIES,
    n: int = 512,
    k: int = 32,
    seed: int = 0,
    warmup: int = 3,   # accepted for compatibility; cold measurement uses no warmup
    reps: int = 10,
) -> dict:
    """Measure a node's candidate SpMM kernel against the fixed family set.

    ``run_kernel(kind, work_dir, A, X) -> (seconds, Y)`` runs ONE cold timed
    call of the baseline ('baseline') or the agent's candidate ('candidate') and
    returns its timing + output. The evaluator owns A and X (the agent cannot
    supply them — anti-gaming).

    A defines each family's structure; each repetition draws a fresh random X and
    verifies the candidate output against the fp64 reference. Candidate and
    baseline form one matched timing pair with alternating execution order. The
    external wall clock checks and, when needed, clamps the candidate's internal
    timing. The family speedup is the median of accepted per-pair
    ``baseline_time / credited_candidate_time`` ratios.

    Returns the dict ``DeterministicEvaluator._score`` consumes:
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

        def run(kind, _wd, _A, _X):
            return _run_exe(exes[kind], td_obj.name, _A, _X)
    else:
        run = run_kernel

    try:
        for fam in families:
            A = gen_matrix(fam, n, seed=seed)
            ratios: list[float] = []
            repetitions: list[dict[str, Any]] = []
            valid = True
            max_rel = 0.0
            n_clamped = 0
            for r in range(n_reps):
                input_seed = seed * 100003 + r + 1
                rec = {
                    "index": r,
                    "status": "started",
                    "valid": False,
                    "measurements": {"input_seed": input_seed},
                }
                X = np.random.default_rng(input_seed).standard_normal((A.shape[1], k))
                Y_ref = reference_spmm(A, X)
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
                        observed[kind] = _unpack_run(run(kind, work_dir, A, X))
                    except Exception as exc:
                        if kind == "baseline":
                            raise HarnessInfrastructureError(
                                f"baseline run failed on {fam}, rep {r}: {exc}") from exc
                        valid = False
                        evaluation_status = "candidate_invalid"
                        reason = f"candidate run failed on {fam}, rep {r}: {exc}"
                        rec["status"] = "candidate_run_failed"
                        rec["measurements"]["error"] = str(exc)
                        repetitions.append(rec)
                        break
                if not valid:
                    break

                tc, tc_wall, Y_cand = observed["candidate"]
                tb, tb_wall, _ = observed["baseline"]
                ok, mr = is_correct(Y_cand, Y_ref, A, X)
                max_rel = max(max_rel, mr)
                measurements = rec["measurements"]
                measurements.update({
                    "candidate_internal_seconds": float(tc),
                    "candidate_wall_seconds": float(tc_wall),
                    "baseline_internal_seconds": float(tb),
                    "baseline_wall_seconds": float(tb_wall),
                    "max_relative_error": float(mr),
                })
                if not ok:
                    valid = False
                    evaluation_status = "candidate_invalid"
                    reason = f"incorrect output on {fam}, rep {r}"
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
                        f"implausible timing on {fam}: reported {tc:.6g}s but "
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
                    f"insufficient matched repetitions on {fam}: "
                    f"{len(ratios)}/{n_reps}, need {min_accepted}")
            speedup = _stats.median(ratios) if measurable else 0.0
            out_families[fam] = {
                "speedup": float(speedup),
                "valid": measurable,
                "max_relative_error": max_rel,
                "n_clamped": n_clamped,
                "n_requested_repetitions": n_reps,
                "n_accepted_repetitions": len(ratios),
                "repetitions": repetitions,
            }
            # The task score requires every family. After one family is invalid,
            # further execution cannot recover a score and only risks exhausting
            # the batch allocation.
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
