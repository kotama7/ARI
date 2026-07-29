"""Tests for the stencil harness (task D, login-testable parts).

Covers the fp64 nt-sweep reference, the nt-scaled correctness bound, deterministic
problem generation, measure_node aggregation with an injected runner, and the
work_dir seeder. The real compile/run/timing runner is compute-node only; a login
smoke test of the frozen baseline is included (skips without a compiler).

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
        return 1.0, u             # baseline slower
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
        "candidate", "baseline", "baseline",
        "candidate", "candidate", "baseline",
    ]
    assert family["speedup"] == pytest.approx(10.0)
    assert [r["execution_order"] for r in family["repetitions"]] == [
        ["candidate", "baseline"],
        ["baseline", "candidate"],
        ["candidate", "baseline"],
    ]


def test_measure_node_reverses_starting_order_for_odd_seed():
    def run(kind, _work_dir, u0, nx, ny, nz, nt):
        timing = 1.0 if kind == "candidate" else 2.0
        return timing, reference_jacobi(u0, nx, ny, nz, nt)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8, 1),), reps=3, seed=1)
    assert [r["execution_order"] for r in out["families"]["8x8x8t1"]["repetitions"]] == [
        ["baseline", "candidate"],
        ["candidate", "baseline"],
        ["baseline", "candidate"],
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
    assert (256, 256, 256, 30) in SHAPES
    assert any(nx != ny or ny != nz for (nx, ny, nz, _nt) in SHAPES)  # >=1 box


def test_default_runner_baseline_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen baseline is correct."""
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
    assert ok, f"baseline incorrect (max_abs={ma})"


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
    assert result["evaluation_status"] in {"valid", "measurement_invalid"}
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
    """A destructor that reads /proc/self/cmdline to find the private timing file
    (argv[3]) and overwrites it with ~0 — defeating the in-process 'private file'
    timer — is caught by the EXTERNAL wall-clock cross-check: the process
    wall-clock reveals the real (slow) sweep time, so the fabricated tiny internal
    time is rejected as implausible. Uses a study-scale size so the honest naive
    sweep reliably clears the wall-clock guard's noise floor (~0.02s)."""
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
        "forged in-process timer was not caught by the external wall-clock cross-check"
