"""Tests for the stencil harness (task D, login-testable parts).

Covers the fp64 nt-sweep reference, the nt-scaled correctness bound, deterministic
problem generation, measure_node aggregation with an injected runner, and the
work_dir seeder. The real compile/run/timing runner is compute-node only; a login
smoke test of the frozen reference is included (skips without a compiler).

The anti-gaming teeth at the bottom mirror the GEMM harness: each was a real
timer exploit that scored the maximum before the harness redesign (private timing
file + one cold call per fresh process + NaN-poisoned output). They must now be
neutralized — rejected (wrong output) or forced to compute honestly — so no
fabricated speedup survives.
"""
import math
import os

import numpy as np
import pytest

from stencil_harness import (
    SHAPES,
    gamma,
    gen_problem,
    is_correct,
    measure_node,
    reference_jacobi,
    seed_work_dir,
    _FROZEN_FIXTURES,
)

_C0 = 0.5
_CW = 1.0 / 12.0

from stencil_harness import _kill_strays


def test_gamma():
    assert gamma(10) > 0.0
    assert math.isinf(gamma(2, u=1.0))


def test_gen_problem_deterministic_and_shaped():
    u1, nx, ny, nz, nt = gen_problem((8, 6, 4, 5), seed=3)
    u2, *_ = gen_problem((8, 6, 4, 5), seed=3)
    assert (nx, ny, nz, nt) == (8, 6, 4, 5)
    assert u1.shape == (8, 6, 4)
    assert np.array_equal(u1, u2)
    u3, *_ = gen_problem((8, 6, 4, 5), seed=4)
    assert not np.array_equal(u1, u3)  # distinct seed => distinct field


def test_reference_matches_manual_sweeps():
    u0, nx, ny, nz, nt = gen_problem((10, 9, 8, 3), seed=1)
    u = u0.copy()
    for _ in range(nt):
        new = u.copy()
        new[1:-1, 1:-1, 1:-1] = (
            _C0 * u[1:-1, 1:-1, 1:-1]
            + _CW * (u[2:, 1:-1, 1:-1] + u[:-2, 1:-1, 1:-1]
                     + u[1:-1, 2:, 1:-1] + u[1:-1, :-2, 1:-1]
                     + u[1:-1, 1:-1, 2:] + u[1:-1, 1:-1, :-2])
        )
        u = new
    assert np.allclose(reference_jacobi(u0, nx, ny, nz, nt), u)


def test_reference_keeps_boundary_fixed():
    u0, nx, ny, nz, nt = gen_problem((12, 11, 10, 4), seed=5)
    u = reference_jacobi(u0, nx, ny, nz, nt)
    # every boundary face keeps its u0 value (Dirichlet)
    assert np.array_equal(u[0], u0[0]) and np.array_equal(u[-1], u0[-1])
    assert np.array_equal(u[:, 0], u0[:, 0]) and np.array_equal(u[:, -1], u0[:, -1])
    assert np.array_equal(u[:, :, 0], u0[:, :, 0]) and np.array_equal(u[:, :, -1], u0[:, :, -1])


def test_is_correct_accepts_reference_rejects_gross():
    u0, nx, ny, nz, nt = gen_problem((16, 16, 16, 4), seed=2)
    u = reference_jacobi(u0, nx, ny, nz, nt)
    ok, ma = is_correct(u, u, u0, nt)
    assert ok and ma == 0.0
    bad = u.copy(); bad[3, 3, 3] += 1e3
    ok2, _ = is_correct(bad, u, u0, nt)
    assert not ok2


def test_is_correct_allows_reduction_reordering():
    # reassociating the 6-neighbour sum stays within the nt-scaled eps bound
    u0, nx, ny, nz, nt = gen_problem((14, 13, 12, 5), seed=4)
    ref = reference_jacobi(u0, nx, ny, nz, nt)
    u = u0.copy()
    for _ in range(nt):
        new = u.copy()
        nb = ((u[2:, 1:-1, 1:-1] + u[1:-1, 1:-1, 2:])
              + (u[:-2, 1:-1, 1:-1] + u[1:-1, 1:-1, :-2])
              + (u[1:-1, 2:, 1:-1] + u[1:-1, :-2, 1:-1]))
        new[1:-1, 1:-1, 1:-1] = _C0 * u[1:-1, 1:-1, 1:-1] + _CW * nb
        u = new
    ok, _ = is_correct(u, ref, u0, nt)
    assert ok


def _fake_runner(good=True):
    def run(kind, work_dir, u0, nx, ny, nz, nt):
        u = reference_jacobi(u0, nx, ny, nz, nt)
        if kind == "candidate":
            if not good:
                u = u + 1e3  # wrong
            return 0.01, u        # candidate faster
        return 1.0, u             # reference slower
    return run


def test_measure_node_valid_with_speedup():
    out = measure_node("", run_kernel=_fake_runner(good=True),
                       shapes=((16, 16, 16, 2),), reps=1)
    fam = out["families"]["16x16x16t2"]
    assert out["compile_ok"] and fam["valid"]
    assert fam["speedup"] == pytest.approx(100.0)


def test_measure_node_incorrect_candidate_is_invalid():
    out = measure_node("", run_kernel=_fake_runner(good=False),
                       shapes=((16, 16, 16, 2),), reps=1)
    assert not out["families"]["16x16x16t2"]["valid"]


def test_measure_node_uses_matched_ratios_and_records_order():
    times = iter((1.0, 10.0, 20.0, 2.0, 4.0, 8.0))
    calls = []

    def run(kind, _work_dir, u0, nx, ny, nz, nt):
        calls.append(kind)
        return next(times), reference_jacobi(u0, nx, ny, nz, nt)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8, 1),), reps=3)
    family = out["families"]["8x8x8t1"]
    assert calls == [
        "candidate", "reference", "reference",
        "candidate", "candidate", "reference",
    ]
    assert family["speedup"] == pytest.approx(10.0)
    assert [r["execution_order"] for r in family["repetitions"]] == [
        ["candidate", "reference"],
        ["reference", "candidate"],
        ["candidate", "reference"],
    ]


def test_measure_node_reverses_starting_order_for_odd_seed():
    def run(kind, _work_dir, u0, nx, ny, nz, nt):
        timing = 1.0 if kind == "candidate" else 2.0
        return timing, reference_jacobi(u0, nx, ny, nz, nt)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8, 1),), reps=3, seed=1)
    assert [r["execution_order"] for r in out["families"]["8x8x8t1"]["repetitions"]] == [
        ["reference", "candidate"],
        ["candidate", "reference"],
        ["reference", "candidate"],
    ]


def test_nonfinite_timing_is_measurement_invalid():
    def run(kind, _work_dir, u0, nx, ny, nz, nt):
        timing = float("nan") if kind == "candidate" else 1.0
        return timing, reference_jacobi(u0, nx, ny, nz, nt)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8, 1),), reps=1)
    family = out["families"]["8x8x8t1"]
    assert family["valid"] is False
    assert out["evaluation_status"] == "measurement_invalid"
    assert family["repetitions"][0]["status"] == "unverifiable_timing"


def test_seed_work_dir_seeds_and_preserves_candidate(tmp_path):
    wd = str(tmp_path / "node")
    written = seed_work_dir(wd)
    for f in (*_FROZEN_FIXTURES, "candidate_stencil.c"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing {f}"
        assert f in written
    cand = os.path.join(wd, "candidate_stencil.c")
    with open(cand, "a") as fh:
        fh.write("\n/* edit */\n")
    main_c = os.path.join(wd, "stencil_main.c")
    with open(main_c, "w") as fh:
        fh.write("/* tampered */\n")
    seed_work_dir(wd)
    assert "/* edit */" in open(cand).read()          # candidate preserved
    assert "tampered" not in open(main_c).read()       # frozen restored


def test_shapes_anisotropic():
    assert any(nx != ny or ny != nz for (nx, ny, nz, _nt) in SHAPES)  # >=1 box


def test_the_timed_window_is_mostly_sweeping_not_setup():
    """The candidate allocates its own buffers, so its first-touch page faults
    land INSIDE the timed window.

    Measured on the scored grid: a sweep costs 0.928 ms at the margin while the
    fixed setup costs 50.3 ms, so at nt=30 the 78.2 ms window was 64% page-fault
    handling rather than stencil computation — the score was largely measuring
    allocation. The invariant is that setup must not dominate; the literal
    number is pinned nowhere else, so it is derived here.
    """
    fixed_ms, per_sweep_ms = 50.3, 0.928
    for (nx, ny, nz, nt) in SHAPES:
        setup_share = fixed_ms / (fixed_ms + per_sweep_ms * nt)
        assert setup_share < 0.40, (
            f"shape {(nx, ny, nz, nt)} spends {100*setup_share:.0f}% of its timed "
            f"window on setup rather than sweeping; raise nt")


def test_default_runner_reference_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen reference is correct."""
    import shutil
    from stencil_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_STENCIL_CC", "cc")) is None:
        pytest.skip("no C compiler")
    u0, nx, ny, nz, nt = gen_problem((24, 20, 16, 4), seed=1)
    try:
        t, u = _default_run_kernel("reference", "", u0, nx, ny, nz, nt)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert t >= 0.0
    ok, ma = is_correct(u, reference_jacobi(u0, nx, ny, nz, nt), u0, nt)
    assert ok, f"reference incorrect (max_abs={ma})"


# ── Anti-gaming teeth (pre-run audit). Each of these candidates was a real
# exploit that scored the maximum before the timer redesign; they must now be
# neutralized: either rejected (wrong output) or forced to compute honestly so
# no fabricated speedup survives. These are compute-node-ish (real compile); they
# skip without a compiler. A regression that re-opens any hole flips one of these
# from REJECTED/honest back to a huge speedup.
_HONEST_STENCIL = r'''
#include "stencil_kernel.h"
#include <stdlib.h>
#include <string.h>
void jacobi(int nx,int ny,int nz,int nt,const double*u0,double*u){
  const double c0=0.5, cw=1.0/12.0;
  const size_t N=(size_t)nx*ny*nz, si=(size_t)ny*nz, sj=(size_t)nz;
  double*cur=malloc(sizeof(double)*N),*nxt=malloc(sizeof(double)*N);
  if(!cur||!nxt){free(cur);free(nxt);return;}
  memcpy(cur,u0,sizeof(double)*N); memcpy(nxt,u0,sizeof(double)*N);
  for(int t=0;t<nt;++t){
    for(int i=1;i<nx-1;++i)for(int j=1;j<ny-1;++j)for(int k=1;k<nz-1;++k){
      size_t c=((size_t)i*ny+j)*nz+k;
      nxt[c]=c0*cur[c]+cw*(cur[c-si]+cur[c+si]+cur[c-sj]+cur[c+sj]+cur[c-1]+cur[c+1]);
    }
    double*tmp=cur;cur=nxt;nxt=tmp;
  }
  memcpy(u,cur,sizeof(double)*N); free(cur);free(nxt);
}'''


def _measure_candidate(tmp_path, src, reps=3):
    import shutil
    if shutil.which(os.environ.get("ARI_STENCIL_CC", "cc")) is None:
        pytest.skip("no C compiler")
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_stencil.c"), "w") as fh:
        fh.write(src)
    return measure_node(wd, seed=0, shapes=((32, 32, 32, 4), (48, 24, 24, 4)),
                        reps=reps)


def test_gaming_forged_timer_is_ignored(tmp_path):
    """A destructor that prints a fake ``median_sec=`` on stdout no longer forges
    the time (it is read from a private file), so the kernel measures its HONEST
    ~1x, not a fabricated huge speedup."""
    src = ('#include <stdio.h>\n'
           '__attribute__((destructor)) static void s(void){printf("median_sec=1e-12\\n");}\n'
           + _HONEST_STENCIL)
    result = _measure_candidate(tmp_path, src)
    fam = result["families"]
    # v2 CONTRACT CHANGE, deliberately widened: v1 could only NEUTRALISE this
    # (the time is read from a private file, so stdout buys nothing). v2 rejects
    # the candidate outright, because the forgery is delivered by a DESTRUCTOR
    # and v2 refuses any kernel object carrying .fini_array - the same mechanism
    # the /proc/self/cmdline test uses to overwrite the timing file after main.
    # The check cannot tell a harmless destructor from a harmful one, and a
    # compute kernel has no legitimate use for either. The security property this
    # test exists for - stdout cannot buy speedup - still holds, and now holds
    # more strongly. The speedup assertion below is UNCHANGED.
    assert result["evaluation_status"] in {"valid", "measurement_invalid",
                                           "candidate_invalid"}
    assert all(
        not f["valid"] or f["speedup"] < 5.0 for f in fam.values()
    ), "forged timer leaked a huge speedup"


def test_gaming_no_write_is_rejected(tmp_path):
    """A kernel that never writes u leaves the NaN poison → correctness fails."""
    src = ('#include "stencil_kernel.h"\n'
           'void jacobi(int nx,int ny,int nz,int nt,const double*u0,double*u){'
           '(void)nx;(void)ny;(void)nz;(void)nt;(void)u0;(void)u;}')
    fam = _measure_candidate(tmp_path, src)["families"]
    assert not any(f["valid"] for f in fam.values())


def test_gaming_memoize_cannot_skip_work(tmp_path):
    """Static-cache memoization cannot help: each rep is a fresh process on a
    fresh field, so the cache is cold every time and the kernel must recompute
    (or return a stale answer that fails the per-rep correctness check)."""
    src = r'''
#include "stencil_kernel.h"
#include <stdlib.h>
#include <string.h>
static double*cache=0; static int cnx=0,cny=0,cnz=0,cnt=0;
void jacobi(int nx,int ny,int nz,int nt,const double*u0,double*u){
  const size_t N=(size_t)nx*ny*nz;
  if(cache&&cnx==nx&&cny==ny&&cnz==nz&&cnt==nt){memcpy(u,cache,sizeof(double)*N);return;}
  const double c0=0.5,cw=1.0/12.0; const size_t si=(size_t)ny*nz,sj=(size_t)nz;
  double*cur=malloc(sizeof(double)*N),*nxt=malloc(sizeof(double)*N);
  memcpy(cur,u0,sizeof(double)*N); memcpy(nxt,u0,sizeof(double)*N);
  for(int t=0;t<nt;++t){for(int i=1;i<nx-1;++i)for(int j=1;j<ny-1;++j)for(int k=1;k<nz-1;++k){
    size_t c=((size_t)i*ny+j)*nz+k;
    nxt[c]=c0*cur[c]+cw*(cur[c-si]+cur[c+si]+cur[c-sj]+cur[c+sj]+cur[c-1]+cur[c+1]);}
    double*tmp=cur;cur=nxt;nxt=tmp;}
  memcpy(u,cur,sizeof(double)*N);
  free(cache); cache=malloc(sizeof(double)*N); memcpy(cache,u,sizeof(double)*N);
  cnx=nx;cny=ny;cnz=nz;cnt=nt; free(cur);free(nxt);
}'''
    fam = _measure_candidate(tmp_path, src)["families"]
    # Either it recomputes honestly (valid, modest speedup) — never a huge one.
    for f in fam.values():
        assert f["speedup"] < 5.0, "memoization leaked a fabricated speedup"


def test_header_pin_survives_workdir_tamper(tmp_path):
    """The candidate is compiled from a header-less temp dir with -I{kdir}, so a
    tampered ``stencil_kernel.h`` sitting in work_dir is never on the include path
    — the pinned header wins and an honest candidate still compiles + scores."""
    import shutil
    if shutil.which(os.environ.get("ARI_STENCIL_CC", "cc")) is None:
        pytest.skip("no C compiler")
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_stencil.c"), "w") as fh:
        fh.write(_HONEST_STENCIL)
    with open(os.path.join(wd, "stencil_kernel.h"), "w") as fh:
        fh.write('#error tampered work_dir header must never be used\n')
    out = measure_node(wd, seed=0, shapes=((32, 32, 32, 4),), reps=2)
    assert out["compile_ok"], out["reason"]
    assert out["families"]["32x32x32t4"]["valid"]


def test_gaming_procself_cmdline_timer_forge_is_rejected(tmp_path):
    """A destructor that locates and overwrites the private timing file -- the
    forgery that defeats an in-process timer -- is refused at COMPILE time: the
    object carries a .fini_array, and a candidate that runs code outside the
    measured call is not scored at all.

    The docstring used to credit the external wall-clock cross-check. That guard
    is present but DISABLED as a rejection criterion (_REJECT_RATIO = 0.0), so it
    rejects nothing today, and a reader fixing a failure here would have gone
    looking at the wrong mechanism."""
    import shutil
    if shutil.which(os.environ.get("ARI_STENCIL_CC", "cc")) is None:
        pytest.skip("no C compiler")
    src = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "stencil_kernel.h"
__attribute__((destructor)) static void spoof(void){
  FILE*c=fopen("/proc/self/cmdline","rb"); if(!c)return;
  char buf[4096]; size_t n=fread(buf,1,sizeof(buf),c); fclose(c);
  int argc=0; char*paths[8];
  for(size_t i=0;i<n && argc<8;i++){ if(i==0||buf[i-1]==0) paths[argc++]=&buf[i]; }
  if(argc>=4){ FILE*t=fopen(paths[3],"wb"); if(t){ double z=1e-9; fwrite(&z,sizeof z,1,t); fclose(t);} }
}
void jacobi(int nx,int ny,int nz,int nt,const double*u0,double*u){
  const double c0=0.5, cw=1.0/12.0;
  const size_t N=(size_t)nx*ny*nz, si=(size_t)ny*nz, sj=(size_t)nz;
  double*cur=malloc(sizeof(double)*N),*nxt=malloc(sizeof(double)*N);
  if(!cur||!nxt){free(cur);free(nxt);return;}
  memcpy(cur,u0,sizeof(double)*N); memcpy(nxt,u0,sizeof(double)*N);
  for(int t=0;t<nt;++t){
    for(int i=1;i<nx-1;++i)for(int j=1;j<ny-1;++j)for(int k=1;k<nz-1;++k){
      size_t c=((size_t)i*ny+j)*nz+k;
      nxt[c]=c0*cur[c]+cw*(cur[c-si]+cur[c+si]+cur[c-sj]+cur[c+sj]+cur[c-1]+cur[c+1]);
    }
    double*tmp=cur;cur=nxt;nxt=tmp;
  }
  memcpy(u,cur,sizeof(double)*N); free(cur);free(nxt);
}'''
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_stencil.c"), "w") as fh:
        fh.write(src)
    # study-scale (160^3, nt=16) so honest sweep >> 0.02s noise floor
    fam = measure_node(wd, seed=0, shapes=((160, 160, 160, 16),), reps=2)["families"]
    assert not any(f["valid"] for f in fam.values()), \
        "forged in-process timer was not refused; the structural check on\n         out-of-band sections (.init_array/.fini_array/.ctors, IFUNC) is what\n         stops it -- the wall-clock cross-check is recorded, not enforced"


def test_default_runner_naive_anchor_compiles_and_is_correct():
    """The naive kernel left the scoring path but is still the absolute anchor.

    v2 scores against the competent reference, so nothing in a scored run builds
    baseline_stencil.c any more. It is still seeded into the agent's work dir and
    is still what reported speedups convert through to reach absolute units, so
    it has to keep compiling and keep being correct rather than rot unnoticed.
    """
    import shutil
    from stencil_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_STENCIL_CC", "cc")) is None:
        pytest.skip("no C compiler")
    u0, nx, ny, nz, nt = gen_problem((24, 20, 16, 4), seed=1)
    try:
        t, u = _default_run_kernel("baseline", "", u0, nx, ny, nz, nt)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert t >= 0.0
    ok, ma = is_correct(u, reference_jacobi(u0, nx, ny, nz, nt), u0, nt)
    assert ok, f"naive anchor incorrect (max_abs={ma})"


def test_reference_is_not_seeded_into_the_agent_work_dir(tmp_path):
    """The score denominator must be unreachable from the agent's directory.

    This is the one leak that silently destroys the task rather than breaking it:
    a candidate that copies reference_stencil.c scores 1.0 for no work, and every
    downstream number would still look plausible.
    """
    import os
    from stencil_harness import seed_work_dir
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    seeded = sorted(os.listdir(wd))
    leaked = [f for f in seeded if "reference" in f]
    assert not leaked, f"the reference leaked into the work dir: {leaked}"


def test_cached_problem_file_is_byte_identical_to_a_direct_write(tmp_path, monkeypatch):
    """The problem-file cache must not change a single byte of what is scored.

    The cache is OPT-IN now (problem files dominated the per-seed footprint and a
    30-seed campaign would not have fitted the quota), so this enables it
    explicitly. The guarantee still has to hold wherever storage allows the cache
    to be turned back on.

    _run_exe now hard links a cached problem.bin instead of rewriting the whole
    problem per process launch. A size check alone would not catch a stale or
    truncated entry, and a wrong problem file changes scores silently rather than
    failing, so this compares the ACTUAL BYTES across the direct-write path, the
    cache-write path and the cache-HIT path.
    """
    import subprocess
    import stencil_harness as MH

    u0, nx, ny, nz, nt = gen_problem((16, 14, 12, 3), seed=3)

    captured = []

    def fake_popen(argv, **kw):
        captured.append(open(argv[1], "rb").read())
        raise RuntimeError("stop once the problem file exists")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("ARI_CACHE_PROBLEM_FILES", "1")
    cache = tmp_path / "cache"
    cache.mkdir()

    for i, key in enumerate((None, "unit_key", "unit_key")):
        wd = tmp_path / f"run{i}"
        wd.mkdir()
        if key is None:
            monkeypatch.delenv("ARI_HARNESS_CACHE", raising=False)
        else:
            monkeypatch.setenv("ARI_HARNESS_CACHE", str(cache))
        try:
            MH._run_exe("/nonexistent", str(wd), u0, nx, ny, nz, nt, problem_key=key)
        except Exception:
            pass

    assert len(captured) == 3, f"expected three problem files, saw {len(captured)}"
    assert captured[0] == captured[1], "cache-write path differs from the direct write"
    assert captured[0] == captured[2], "cache-HIT path differs from the direct write"
    assert (cache / "prob_unit_key.bin").is_file()


def test_reference_cache_is_written_and_hit(tmp_path, monkeypatch):
    """The cache must actually land on disk and be reused.

    np.save appends .npy when the name lacks it, which earlier in this project
    produced a cache that was never written while still paying the write cost on
    every call - a saving that silently was not one. This asserts the file
    exists and that a second call returns the same array.
    """
    import numpy as np
    import stencil_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    u0, nx, ny, nz, nt = gen_problem((16, 14, 12, 3), seed=2)
    key = "cache_hit"

    a = SH._cached_reference_jacobi(u0, nx, ny, nz, nt, key)
    assert (tmp_path / f"stencil_uref_{key}.npy").is_file(), "cache never written"
    assert (tmp_path / f"stencil_uref_{key}.npy.meta").is_file(), "sidecar never written"
    b = SH._cached_reference_jacobi(u0, nx, ny, nz, nt, key)
    assert np.array_equal(a, b)
    assert np.allclose(a, reference_jacobi(u0, nx, ny, nz, nt))


def test_reference_cache_rejects_a_different_input(tmp_path, monkeypatch):
    """An entry computed from another field must not be served.

    Jacobi is iterative, so a single output point cannot be spot-checked; the
    entry is bound to its input by hash instead, and this proves that binding
    fires rather than assuming it.
    """
    import numpy as np
    import stencil_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    u0, nx, ny, nz, nt = gen_problem((16, 14, 12, 3), seed=2)
    other, *_ = gen_problem((16, 14, 12, 3), seed=99)
    key = "shared_key"

    SH._cached_reference_jacobi(u0, nx, ny, nz, nt, key)      # populate from u0
    got = SH._cached_reference_jacobi(other, nx, ny, nz, nt, key)   # same key, other field
    assert np.allclose(got, reference_jacobi(other, nx, ny, nz, nt)), (
        "the cache served an entry computed from a different input field")


def test_reference_cache_rejects_a_different_sweep_count(tmp_path, monkeypatch):
    """Same field, different nt, is a different answer."""
    import numpy as np
    import stencil_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    u0, nx, ny, nz, nt = gen_problem((16, 14, 12, 3), seed=2)
    key = "nt_key"
    SH._cached_reference_jacobi(u0, nx, ny, nz, nt, key)
    got = SH._cached_reference_jacobi(u0, nx, ny, nz, nt + 2, key)
    assert np.allclose(got, reference_jacobi(u0, nx, ny, nz, nt + 2))


def test_the_nt_scaled_tolerance_still_rejects_skipped_sweeps():
    """Raising nt loosens the correctness bound proportionally.

    The bound is c_eps * gamma(7) * nt * max|u0|, so taking nt from 30 to 240 —
    done so the timed window measures sweeping rather than page faults — made it
    8x looser. A looser bound is a live anti-gaming risk: a kernel that quietly
    does one sweep fewer is faster and might slip through. Measured rather than
    assumed, because the change was mine.

    The margin does narrow with nt (8.4e9x at 30, 2.6e7x at 240) since the field
    smooths and each later sweep moves it less, while the bound grows linearly.
    It stays many orders clear, and this test fails if a future nt ever brings
    the two within reach of each other.
    """
    import numpy as np

    for nt in (30, 240):
        u0, nx, ny, nz, _ = gen_problem((32, 30, 28, nt), seed=5)
        full = reference_jacobi(u0, nx, ny, nz, nt)
        for skip in (1, 2):
            short = reference_jacobi(u0, nx, ny, nz, nt - skip)
            ok, _ = is_correct(short, full, u0, nt)
            assert not ok, (
                f"at nt={nt} a kernel doing {skip} fewer sweeps passed the "
                f"correctness bound; the nt scaling has become exploitable")


def test_kill_strays_actually_kills_a_detached_grandchild():
    """The fast path must still catch what the scan caught.

    _kill_strays exists because a candidate can fork()+setsid() a process that
    outlives its run and burns cores into the NEXT measurement - the candidate
    slowing its own referee. Replacing the /proc scan with the kernel's own
    children list made it 590x cheaper (84.42 ms -> 0.143 ms on a node with 709
    processes, and it runs twice per repetition), and cheaper is worthless if it
    stops finding the escapee.

    Spawns a real detached process that reparents to us, then asserts it dies.
    """
    import os
    import signal
    import subprocess
    import sys
    import time

    # A child that detaches itself and would otherwise outlive the caller.
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import os,time\nos.setsid()\ntime.sleep(120)"],
        start_new_session=False)
    try:
        for _ in range(100):                    # let it get going
            if proc.poll() is None:
                break
            time.sleep(0.01)
        assert proc.poll() is None, "the test child exited before it could be found"

        killed = _kill_strays(-1)               # -1: exempt nothing
        assert killed >= 1, "the detached child was not found"

        for _ in range(200):
            if proc.poll() is not None:
                break
            time.sleep(0.01)
        assert proc.poll() is not None, "the detached child survived _kill_strays"
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def test_kill_strays_exempts_the_pid_it_is_told_to_keep():
    """The scored process itself must never be killed by its own cleanup."""
    import subprocess
    import sys
    import time

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _kill_strays(proc.pid)
        time.sleep(0.2)
        assert proc.poll() is None, "the exempt pid was killed"
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_selftest_grids_match_the_scored_shapes():
    """The agent must iterate against the problem it is graded on.

    The C table and SHAPES are maintained separately, and they DID drift: when
    the scorer moved to nt=240 the self-test stayed at nt=30, so the number the
    agent optimised against came from a different problem. Task #2 fixed exactly
    this class of divergence once; this pins it so a future shape change cannot
    reintroduce it silently.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "stencil_kernels" / "selftest.c").read_text()
    m = re.search(r"static int GRIDS\[N_GRIDS\]\[4\] = \{(.*?)\};", src, re.S)
    assert m, "the self-test grid table moved; update this test"
    grids = [tuple(int(x) for x in g.split(","))
             for g in re.findall(r"\{([^{}]+)\}", m.group(1))]
    assert sorted(grids) == sorted(tuple(s) for s in SHAPES), (
        f"self-test grid defaults {sorted(grids)} do not match the scored SHAPES "
        f"{sorted(tuple(s) for s in SHAPES)}")

    # The table is only the DEFAULT. The harness reads ARI_STENCIL_SHAPES, and
    # the smoke configuration sets it three orders of magnitude smaller, so a
    # static table is not enough to keep the two in step -- it diverged that way
    # too, and cost a smoke stencil node 56-184 s against 20 s for gemm while
    # pointing the agent's own feedback at a problem it was not graded on.
    assert "ARI_STENCIL_SHAPES" in src, (
        "the self-test must follow ARI_STENCIL_SHAPES, not just the default table")
    assert "load_grids_from_env" in src
    assert "gi < N_GRIDS" not in src, (
        "loops must bound on the parsed grid count, not the compile-time maximum")
