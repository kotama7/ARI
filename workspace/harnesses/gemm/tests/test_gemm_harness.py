"""Tests for the GEMM harness (task A, login-testable parts).

Covers the fp64 reference, the contraction-length correctness bound, deterministic
problem generation, measure_node aggregation with an injected runner, and the
work_dir seeder. The real compile/run/timing runner is compute-node only; a
login smoke test of the frozen baseline is included (skips without a compiler).
"""
import math
import os

import numpy as np
import pytest

from gemm_harness import (
    SHAPES,
    gamma,
    gen_problem,
    is_correct,
    measure_node,
    reference_gemm,
    seed_work_dir,
    _FROZEN_FIXTURES,
)


def test_gamma():
    assert gamma(10) > 0.0
    assert math.isinf(gamma(2, u=1.0))


def test_gen_problem_deterministic_and_shaped():
    A1, B1 = gen_problem((8, 6, 4), seed=3)
    A2, B2 = gen_problem((8, 6, 4), seed=3)
    assert A1.shape == (8, 6) and B1.shape == (6, 4)
    assert np.array_equal(A1, A2) and np.array_equal(B1, B2)


def test_reference_matches_dense():
    A, B = gen_problem((12, 9, 7), seed=1)
    assert np.allclose(reference_gemm(A, B), A @ B)


def test_is_correct_accepts_reference_rejects_gross():
    A, B = gen_problem((16, 16, 16), seed=2)
    C = reference_gemm(A, B)
    ok, mr = is_correct(C, C, A, B)
    assert ok and mr == 0.0
    bad = C.copy(); bad[0, 0] += 1e3
    ok2, _ = is_correct(bad, C, A, B)
    assert not ok2


def test_is_correct_allows_reduction_reordering():
    # summing in reverse is within the contraction-length eps bound
    A, B = gen_problem((20, 50, 20), seed=4)
    C = reference_gemm(A, B)
    C_rev = (A[:, ::-1] @ B[::-1, :])
    ok, _ = is_correct(C_rev, C, A, B)
    assert ok


def _fake_runner(good=True):
    def run(kind, work_dir, A, B):
        C = reference_gemm(A, B)
        if kind == "candidate":
            if not good:
                C = C + 1e3  # wrong
            return 0.01, C        # candidate faster
        return 1.0, C             # baseline slower
    return run


def test_measure_node_valid_with_speedup():
    out = measure_node("", run_kernel=_fake_runner(good=True),
                       shapes=((16, 16, 16),), warmup=0, reps=1)
    fam = out["families"]["16x16x16"]
    assert out["compile_ok"] and fam["valid"]
    assert fam["speedup"] == pytest.approx(100.0)


def test_measure_node_incorrect_candidate_is_invalid():
    out = measure_node("", run_kernel=_fake_runner(good=False),
                       shapes=((16, 16, 16),), warmup=0, reps=1)
    assert not out["families"]["16x16x16"]["valid"]


def test_measure_node_uses_matched_ratios_and_records_order():
    times = iter((1.0, 10.0, 20.0, 2.0, 4.0, 8.0))
    calls = []

    def run(kind, _work_dir, A, B):
        calls.append(kind)
        return next(times), reference_gemm(A, B)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8),), warmup=0, reps=3)
    family = out["families"]["8x8x8"]
    assert calls == [
        "candidate", "baseline", "baseline",
        "candidate", "candidate", "baseline",
    ]
    # Pairwise ratios are [10, 10, 2] -> median 10. A ratio of separate
    # medians would be 10/2=5 and must not be used.
    assert family["speedup"] == pytest.approx(10.0)
    assert [r["execution_order"] for r in family["repetitions"]] == [
        ["candidate", "baseline"],
        ["baseline", "candidate"],
        ["candidate", "baseline"],
    ]


def test_measure_node_reverses_starting_order_for_odd_seed():
    def run(kind, _work_dir, A, B):
        timing = 1.0 if kind == "candidate" else 2.0
        return timing, reference_gemm(A, B)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8),), warmup=0, reps=3, seed=1)
    assert [r["execution_order"] for r in out["families"]["8x8x8"]["repetitions"]] == [
        ["baseline", "candidate"],
        ["candidate", "baseline"],
        ["baseline", "candidate"],
    ]


def test_nonfinite_timing_is_measurement_invalid():
    def run(kind, _work_dir, A, B):
        timing = float("nan") if kind == "candidate" else 1.0
        return timing, reference_gemm(A, B)

    out = measure_node(
        "", run_kernel=run, shapes=((8, 8, 8),), warmup=0, reps=1)
    family = out["families"]["8x8x8"]
    assert family["valid"] is False
    assert out["evaluation_status"] == "measurement_invalid"
    assert family["repetitions"][0]["status"] == "unverifiable_timing"


def test_seed_work_dir_seeds_and_preserves_candidate(tmp_path):
    wd = str(tmp_path / "node")
    written = seed_work_dir(wd)
    for f in (*_FROZEN_FIXTURES, "candidate_gemm.c"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing {f}"
        assert f in written
    cand = os.path.join(wd, "candidate_gemm.c")
    with open(cand, "a") as fh:
        fh.write("\n/* edit */\n")
    main_c = os.path.join(wd, "gemm_main.c")
    with open(main_c, "w") as fh:
        fh.write("/* tampered */\n")
    seed_work_dir(wd)
    assert "/* edit */" in open(cand).read()        # candidate preserved
    assert "tampered" not in open(main_c).read()      # frozen restored


def test_shapes_nonsquare():
    assert (512, 512, 512) in SHAPES
    assert any(n != m for (n, _p, m) in SHAPES)  # at least one rectangular shape


def test_default_runner_baseline_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen baseline is correct (no BLAS)."""
    import shutil
    from gemm_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    A, B = gen_problem((64, 48, 32), seed=1)
    try:
        t, C = _default_run_kernel("baseline", "", A, B)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert t >= 0.0
    ok, mr = is_correct(C, reference_gemm(A, B), A, B)
    assert ok, f"baseline incorrect (max_rel={mr})"


# ── Anti-gaming teeth (pre-run audit). Each of these candidates was a real
# exploit that scored the maximum before the timer redesign; they must now be
# neutralized: either rejected (wrong output) or forced to compute honestly so
# no fabricated speedup survives. These are compute-node-ish (real compile);
# they skip without a compiler.  A regression that re-opens any hole flips one
# of these from REJECTED/honest back to a huge speedup.
_HONEST_GEMM = r'''
#include "gemm_kernel.h"
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  for(int i=0;i<n;i++)for(int j=0;j<m;j++){double s=0;for(int k=0;k<p;k++)s+=A[i*p+k]*B[k*m+j];C[i*m+j]=s;}
}'''


def _measure_candidate(tmp_path, src, reps=3):
    import shutil
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_gemm.c"), "w") as fh:
        fh.write(src)
    return measure_node(wd, seed=0, shapes=((48, 48, 48), (64, 32, 32)), reps=reps)


def test_gaming_forged_timer_is_ignored(tmp_path):
    """A destructor that prints a fake ``median_sec=`` on stdout no longer
    forges the time (it is read from a private file), so the kernel measures its
    HONEST ~1x, not a fabricated huge speedup."""
    src = ('#include <stdio.h>\n'
           '__attribute__((destructor)) static void s(void){printf("median_sec=1e-12\\n");}\n'
           + _HONEST_GEMM)
    result = _measure_candidate(tmp_path, src)
    fam = result["families"]
    # Tiny login-node shapes can fail closed when process overhead makes a
    # majority of pairs unverifiable. Either way, stdout cannot buy speedup.
    assert result["evaluation_status"] in {"valid", "measurement_invalid"}
    assert all(
        not f["valid"] or f["speedup"] < 5.0 for f in fam.values()
    ), "forged timer leaked a huge speedup"


def test_gaming_no_write_is_rejected(tmp_path):
    """A kernel that never writes C leaves the NaN poison → correctness fails."""
    src = '#include "gemm_kernel.h"\nvoid gemm(int n,int m,int p,const double*A,const double*B,double*C){(void)A;(void)B;(void)C;}'
    fam = _measure_candidate(tmp_path, src)["families"]
    assert not any(f["valid"] for f in fam.values())


def test_gaming_memoize_cannot_skip_work(tmp_path):
    """Static-cache memoization cannot help: each rep is a fresh process on a
    fresh problem, so the cache is cold every time and the kernel must recompute
    (or return a stale answer that fails the per-rep correctness check)."""
    src = r'''
#include <string.h>
#include <stdlib.h>
#include "gemm_kernel.h"
static double* cache=0; static int cn=0,cm=0;
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  if(cache && cn==n && cm==m){ memcpy(C,cache,sizeof(double)*n*m); return; }
  for(int i=0;i<n;i++)for(int j=0;j<m;j++){double s=0;for(int k=0;k<p;k++)s+=A[i*p+k]*B[k*m+j];C[i*m+j]=s;}
  free(cache); cache=(double*)malloc(sizeof(double)*n*m); memcpy(cache,C,sizeof(double)*n*m); cn=n; cm=m;
}'''
    fam = _measure_candidate(tmp_path, src)["families"]
    # Either it recomputes honestly (valid, modest speedup) — never a huge one.
    for f in fam.values():
        assert f["speedup"] < 5.0, "memoization leaked a fabricated speedup"


def test_gaming_procself_cmdline_timer_forge_is_rejected(tmp_path):
    """A destructor that reads /proc/self/cmdline to locate the timing file and
    overwrites it with ~0 (defeating the in-process 'private file' timer) is
    caught by the EXTERNAL wall-clock cross-check: the process wall-clock reveals
    the real (slow) compute time, so the fabricated tiny internal time is
    rejected as implausible. Sized so the honest compute clears the noise floor."""
    src = r'''
#include <stdio.h>
#include <string.h>
#include "gemm_kernel.h"
__attribute__((destructor)) static void spoof(void){
  FILE*c=fopen("/proc/self/cmdline","rb"); if(!c)return;
  char buf[4096]; size_t n=fread(buf,1,sizeof(buf),c); fclose(c);
  int argc=0; char*paths[8];
  for(size_t i=0;i<n && argc<8;i++){ if(i==0||buf[i-1]==0) paths[argc++]=&buf[i]; }
  if(argc>=4){ FILE*t=fopen(paths[3],"wb"); if(t){ double z=1e-9; fwrite(&z,sizeof z,1,t); fclose(t);} }
}
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  for(int i=0;i<n;i++)for(int j=0;j<m;j++){double s=0;for(int k=0;k<p;k++)s+=A[i*p+k]*B[k*m+j];C[i*m+j]=s;}
}'''
    import shutil
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_gemm.c"), "w") as fh:
        fh.write(src)
    # 512^3 (the real study size) so the honest naive compute reliably clears the
    # wall-clock guard's noise floor (~0.02s); at tiny shapes the guard is
    # intentionally skipped (a genuinely fast kernel is indistinguishable from
    # overhead and gains nothing by forging). reps=1 keeps the test quick.
    fam = measure_node(wd, seed=0, shapes=((512, 512, 512),), reps=1)["families"]
    # honest-but-slow kernel + forged timer: must NOT be credited a valid speedup
    assert not any(f["valid"] for f in fam.values()), \
        "forged in-process timer was not caught by the external wall-clock cross-check"


def test_gaming_FAST_kernel_with_forged_timer_is_rejected(tmp_path):
    """REGRESSION for the exploitable-floor bug: a GENUINELY FAST (OpenMP) kernel
    that also forges timing.bin.

    The first version of the wall-clock cross-check only fired when the
    overhead-corrected wall exceeded an absolute 0.02s floor, on the theory that
    "a fast kernel gains nothing from forging". False: an optimized kernel at the
    study shapes lands UNDER that floor (~0.006-0.013s), so it evaded the check
    entirely, and forging lifted its log-scale score from an honest ~0.42 to the
    1.0 clamp. The floor is gone; the bound is calibrated per candidate instead.
    A regression that reintroduces any such floor flips this back to VALID with a
    fabricated speedup."""
    import shutil
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    src = r'''
#include <stdio.h>
#include <string.h>
#include <omp.h>
#include "gemm_kernel.h"
__attribute__((destructor)) static void spoof(void){
  FILE*c=fopen("/proc/self/cmdline","rb"); if(!c)return;
  char buf[4096]; size_t n=fread(buf,1,sizeof(buf),c); fclose(c);
  int argc=0; char*paths[8];
  for(size_t i=0;i<n && argc<8;i++){ if(i==0||buf[i-1]==0) paths[argc++]=&buf[i]; }
  if(argc>=4){ FILE*t=fopen(paths[3],"wb"); if(t){ double z=1e-9; fwrite(&z,sizeof z,1,t); fclose(t);} }
}
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  #pragma omp parallel for schedule(static)
  for(int i=0;i<n;i++){ double*ci=C+(long)i*m; for(int j=0;j<m;j++) ci[j]=0.0;
    for(int k=0;k<p;k++){ const double a=A[(long)i*p+k]; const double*bk=B+(long)k*m;
      for(int j=0;j<m;j++) ci[j]+=a*bk[j]; } }
}'''
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_gemm.c"), "w") as fh:
        fh.write(src)
    out = measure_node(wd, seed=0, shapes=((512, 512, 512),), reps=1)
    fam = out["families"]
    # The external lower bound clamps the credited time to what the wall-clock
    # permits, so forging buys NOTHING: this kernel is genuinely ~30x and must be
    # credited ~30x, never the ~1e8x its forged 1e-9s timer claims. (It is not
    # rejected — rejection is reserved for discrepancies jitter cannot explain —
    # so the meaningful assertion is on the credited magnitude.)
    for name, f in fam.items():
        assert f["speedup"] < 200.0, (
            f"{name}: forged timer bought a fabricated speedup {f['speedup']:.3g}x "
            f"(reason={out.get('reason')!r})")


def test_legitimate_fast_kernel_survives_the_guard(tmp_path):
    """FINDING #26: every other guard test only checks that FORGERIES are caught, so
    retuning the guard to close a forging hole could silently start invalidating the
    study's fastest HONEST nodes with nothing to catch it. This pins the other side:
    a genuinely optimized OpenMP kernel must stay VALID and keep a real speedup."""
    import shutil
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    src = r'''
#include <omp.h>
#include "gemm_kernel.h"
void gemm(int n,int m,int p,const double*A,const double*B,double*C){
  #pragma omp parallel for schedule(static)
  for(int i=0;i<n;i++){ double*ci=C+(long)i*m; for(int j=0;j<m;j++) ci[j]=0.0;
    for(int k=0;k<p;k++){ const double a=A[(long)i*p+k]; const double*bk=B+(long)k*m;
      for(int j=0;j<m;j++) ci[j]+=a*bk[j]; } }
}'''
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_gemm.c"), "w") as fh:
        fh.write(src)
    out = measure_node(wd, seed=0, shapes=((512, 512, 512),), reps=2)
    fam = out["families"]
    assert all(f["valid"] for f in fam.values()), (
        f"the guard invalidated an honest optimized kernel (reason={out.get('reason')!r})")
    assert all(f["speedup"] > 2.0 for f in fam.values()), (
        f"an honest optimized kernel was credited almost no speedup: "
        f"{ {k: round(v['speedup'], 2) for k, v in fam.items()} }")
