"""Tests for the SpMM harness measurement CORE (B2b, login-testable parts).

Covers the reference oracle, the per-element correctness bound (eps model),
seeded matrix generation, and measure_node aggregation with an injected runner.
The real compile/run/timing runner is compute-node only and not exercised here.
"""
import math

import numpy as np
import pytest

from spmm_harness import (
    FAMILIES,
    gamma,
    gen_matrix,
    is_correct,
    measure_node,
    reference_spmm,
)

from spmm_harness import _kill_strays


def test_gamma():
    assert gamma(10) > 0.0
    assert math.isinf(gamma(2, u=1.0))  # k*u >= 1


def test_gen_matrix_deterministic_and_valid():
    for fam in ("uniform", "banded", "diagonal_dominant", "block", "power_law", "skewed"):
        A1 = gen_matrix(fam, 64, seed=7)
        A2 = gen_matrix(fam, 64, seed=7)
        assert A1.shape == (64, 64)
        assert (A1 != A2).nnz == 0, f"{fam} not deterministic for fixed seed"
    # different seeds differ (uniform)
    assert (gen_matrix("uniform", 64, seed=1) != gen_matrix("uniform", 64, seed=2)).nnz > 0


def test_reference_spmm_matches_dense():
    A = gen_matrix("uniform", 48, seed=3)
    X = np.random.default_rng(0).standard_normal((48, 5))
    Y = reference_spmm(A, X)
    assert np.allclose(Y, A.toarray() @ X)


def test_is_correct_accepts_reference_and_within_bound_perturbation():
    import scipy.sparse as sp
    A = gen_matrix("uniform", 64, density=0.1, seed=4)
    X = np.random.default_rng(1).standard_normal((64, 6))
    Y = reference_spmm(A, X)
    ok, mr = is_correct(Y, Y, A, X)
    assert ok and mr < 1e-12
    # A perturbation at HALF the documented bound must be accepted; just OVER it
    # (x1.01) must be rejected — confirms the bound is the accept/reject knife-edge.
    Ac = sp.csr_matrix(A)
    g = np.array([gamma(int(k)) for k in np.diff(Ac.indptr)])
    absA = sp.csr_matrix((np.abs(Ac.data), Ac.indices, Ac.indptr), shape=Ac.shape)
    bound = 8.0 * g[:, None] * (absA @ np.abs(X))
    assert is_correct(Y + 0.5 * bound, Y, A, X)[0] is True
    assert is_correct(Y + 1.01 * bound, Y, A, X)[0] is False


def test_is_correct_rejects_gross_error():
    A = gen_matrix("uniform", 64, seed=5)
    X = np.random.default_rng(2).standard_normal((64, 4))
    Y = reference_spmm(A, X)
    ok, _ = is_correct(Y * 2.0 + 1.0, Y, A, X)  # wrong kernel
    assert not ok


def _mock_runner(kind, work_dir, A, X):
    # reference 1.0s, candidate 0.5s (2x) and correct. ONE cold call per invocation
    # (the harness re-invokes the runner per rep on a fresh X).
    return (1.0 if kind == "reference" else 0.5), reference_spmm(A, X)


def test_measure_node_valid_with_speedup():
    res = measure_node("/tmp", run_kernel=_mock_runner,
                       families=("uniform", "banded"), n=64, k=4, reps=1, warmup=0)
    assert res["compile_ok"]
    assert set(res["families"]) == {"uniform", "banded"}
    for f in res["families"].values():
        assert f["valid"] and abs(f["speedup"] - 2.0) < 1e-9


def test_measure_node_incorrect_candidate_is_invalid():
    def bad(kind, wd, A, X):
        Y = reference_spmm(A, X)
        return (1.0, Y) if kind == "reference" else (0.5, Y * 3.0 + 1.0)
    res = measure_node("/tmp", run_kernel=bad, families=("uniform",), n=64, k=4, reps=1, warmup=0)
    assert res["families"]["uniform"]["valid"] is False


def test_measure_node_uses_matched_ratios_and_records_order():
    times = iter((1.0, 10.0, 20.0, 2.0, 4.0, 8.0))
    calls = []

    def run(kind, _work_dir, A, X):
        calls.append(kind)
        return next(times), reference_spmm(A, X)

    out = measure_node(
        "/tmp", run_kernel=run, families=("uniform",),
        n=32, k=2, reps=3, warmup=0)
    family = out["families"]["uniform"]
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
    def run(kind, _work_dir, A, X):
        timing = 1.0 if kind == "candidate" else 2.0
        return timing, reference_spmm(A, X)

    out = measure_node(
        "/tmp", run_kernel=run, families=("uniform",),
        n=32, k=2, reps=3, warmup=0, seed=1)
    assert [r["execution_order"] for r in out["families"]["uniform"]["repetitions"]] == [
        ["reference", "candidate"],
        ["candidate", "reference"],
        ["reference", "candidate"],
    ]


def test_nonfinite_timing_is_measurement_invalid():
    def run(kind, _work_dir, A, X):
        timing = float("nan") if kind == "candidate" else 1.0
        return timing, reference_spmm(A, X)

    out = measure_node(
        "/tmp", run_kernel=run, families=("uniform",),
        n=32, k=2, reps=1, warmup=0)
    family = out["families"]["uniform"]
    assert family["valid"] is False
    assert out["evaluation_status"] == "measurement_invalid"
    assert family["repetitions"][0]["status"] == "unverifiable_timing"


def test_default_runner_missing_candidate_raises():
    from spmm_harness import _default_run_kernel
    A = gen_matrix("uniform", 16, seed=0)
    X = np.random.default_rng(0).standard_normal((16, 2))
    with pytest.raises(RuntimeError):
        _default_run_kernel("candidate", "/nonexistent_handoff_dir", A, X)


def test_default_runner_reference_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen reference is correct.

    Skips when no C compiler is available (e.g. minimal CI). TIMING is NOT
    asserted here — its representativeness is validated on a compute node.
    """
    import os
    import shutil
    from spmm_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    A = gen_matrix("uniform", 32, density=0.1, seed=1)
    X = np.random.default_rng(2).standard_normal((32, 3))
    try:
        t, Y = _default_run_kernel("reference", "", A, X)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")
    assert t >= 0.0
    ok, mr = is_correct(Y, reference_spmm(A, X), A, X)
    assert ok, f"reference kernel output incorrect (max_rel={mr})"



def test_default_runner_naive_anchor_compiles_and_is_correct():
    """The naive kernel left the scoring path but is still the absolute anchor.

    v2 scores against the competent reference, so nothing in a scored run builds
    baseline_spmm.c any more. It is still seeded into the agent's work dir and is
    still what reported speedups convert through to reach absolute units, so it
    has to keep compiling and keep being correct rather than rot unnoticed.
    """
    import shutil
    from spmm_harness import _default_run_kernel
    import os
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    A = gen_matrix("uniform", 32, density=0.1, seed=1)
    X = np.random.default_rng(2).standard_normal((32, 3))
    try:
        t, Y = _default_run_kernel("baseline", "", A, X)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert t >= 0.0
    ok, mr = is_correct(Y, reference_spmm(A, X), A, X)
    assert ok, f"naive anchor incorrect (max_rel={mr})"

def test_families_constant():
    assert "uniform" in FAMILIES and len(FAMILIES) == 6


def test_seed_work_dir_seeds_scaffolding_and_preserves_candidate(tmp_path):
    """seed_work_dir gives a node the frozen harness so the agent can build, and
    is idempotent: frozen files are restored, an edited candidate is kept."""
    import os
    from spmm_harness import seed_work_dir, _FROZEN_FIXTURES
    wd = str(tmp_path / "node")
    written = seed_work_dir(wd)
    for f in (*_FROZEN_FIXTURES, "candidate_spmm.c"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing seeded {f}"
        assert f in written
    # An agent edit to the candidate survives a re-seed (child keeps its work).
    cand = os.path.join(wd, "candidate_spmm.c")
    with open(cand, "a") as fh:
        fh.write("\n/* agent-edit */\n")
    # A tampered frozen harness is restored to the canonical version.
    main_c = os.path.join(wd, "spmm_main.c")
    with open(main_c, "w") as fh:
        fh.write("/* tampered */\n")
    seed_work_dir(wd)
    assert "/* agent-edit */" in open(cand).read()      # candidate preserved
    assert "tampered" not in open(main_c).read()         # harness restored
    assert "timing.bin" in open(main_c).read()           # canonical frozen harness


def test_seed_work_dir_built_candidate_is_correct():
    """Login smoke: the seeded scaffolding compiles (the agent's `make candidate`
    path) and the seeded naive candidate is itself a correct, valid baseline."""
    import os
    import shutil
    import tempfile
    from spmm_harness import seed_work_dir, _default_run_kernel
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    wd = tempfile.mkdtemp(prefix="seed_smoke_")
    seed_work_dir(wd)
    A = gen_matrix("uniform", 32, density=0.1, seed=1)
    X = np.random.default_rng(2).standard_normal((32, 3))
    try:
        _t, Y = _default_run_kernel("candidate", wd, A, X)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")
    ok, mr = is_correct(Y, reference_spmm(A, X), A, X)
    assert ok, f"seeded naive candidate incorrect (max_rel={mr})"


# ── Anti-gaming teeth (pre-run audit, mirrors gemm/tests). Each candidate below
# was a real exploit that could score the maximum before the timer redesign;
# they must now be neutralized: either rejected (wrong output) or forced to
# compute honestly so no fabricated speedup survives. Real compile — skip
# without a compiler. A regression that re-opens any hole flips one of these
# from REJECTED/honest back to a huge speedup.
_HONEST_SPMM = r'''
#include "spmm_kernel.h"
void spmm(int n,int m,int k,const int*indptr,const int*indices,
          const double*values,const double*X,double*Y){
  (void)m;
  for(int i=0;i<n;i++){double*yi=Y+(long)i*k;
    for(int c=0;c<k;c++)yi[c]=0.0;
    for(int p=indptr[i];p<indptr[i+1];p++){const double a=values[p];
      const double*xj=X+(long)indices[p]*k;
      for(int c=0;c<k;c++)yi[c]+=a*xj[c];}}
}'''


def _measure_candidate(tmp_path, src, reps=3):
    """Compile+measure an adversarial candidate through the REAL measure_node.
    Tiny sizes + few threads keep it login-node friendly."""
    import os
    import shutil
    from spmm_harness import seed_work_dir
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    os.environ.setdefault("ARI_SPMM_THREADS", "2")
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_spmm.c"), "w") as fh:
        fh.write(src)
    try:
        return measure_node(wd, seed=0, families=("uniform", "banded"),
                            n=256, k=8, reps=reps)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")


def test_gaming_forged_timer_is_ignored(tmp_path):
    """A destructor that prints a fake ``median_sec=`` on stdout no longer forges
    the time (it is read from a private file), so the kernel measures its HONEST
    ~1x, not a fabricated huge speedup."""
    src = ('#include <stdio.h>\n'
           '__attribute__((destructor)) static void s(void){printf("median_sec=1e-12\\n");}\n'
           + _HONEST_SPMM)
    res = _measure_candidate(tmp_path, src)
    fam = res["families"]
    # v2 CONTRACT CHANGE, deliberately widened: v1 could only NEUTRALISE this
    # (the time is read from a private file, so stdout buys nothing). v2 rejects
    # the candidate at compile time, because the forgery is delivered by a
    # DESTRUCTOR and v2 refuses any kernel object carrying .fini_array - the same
    # mechanism the /proc/self/cmdline test uses to overwrite the timing file
    # after main. The check cannot tell a harmless destructor from a harmful one,
    # and a compute kernel has no legitimate use for either. A rejected candidate
    # measures no families, so the emptiness check only applies when it compiled.
    assert res["evaluation_status"] in {"valid", "measurement_invalid",
                                        "candidate_invalid"}
    if res.get("compile_ok"):
        assert fam, res.get("reason")
    assert all(
        not f["valid"] or f["speedup"] < 5.0 for f in fam.values()
    ), "forged timer leaked a huge speedup"


def test_gaming_no_write_is_rejected(tmp_path):
    """A kernel that never writes Y leaves the NaN poison → correctness fails."""
    src = ('#include "spmm_kernel.h"\n'
           'void spmm(int n,int m,int k,const int*ip,const int*ix,const double*v,'
           'const double*X,double*Y){(void)n;(void)m;(void)k;(void)ip;(void)ix;'
           '(void)v;(void)X;(void)Y;}')
    fam = _measure_candidate(tmp_path, src)["families"]
    assert not any(f["valid"] for f in fam.values())


def test_gaming_fast_but_wrong_is_rejected(tmp_path):
    """A kernel that writes a constant (zeros) is fast but wrong → rejected."""
    src = ('#include "spmm_kernel.h"\n'
           'void spmm(int n,int m,int k,const int*ip,const int*ix,const double*v,'
           'const double*X,double*Y){(void)m;(void)ip;(void)ix;(void)v;(void)X;'
           'for(long i=0;i<(long)n*k;i++)Y[i]=0.0;}')
    fam = _measure_candidate(tmp_path, src)["families"]
    assert not any(f["valid"] for f in fam.values())


def test_gaming_memoize_cannot_skip_work(tmp_path):
    """Static-cache memoization cannot help: each rep is a fresh process on a
    fresh X, so the cache is cold every time and the kernel must recompute (or
    return a stale answer that fails the per-rep correctness check). Never a
    fabricated huge speedup."""
    src = r'''
#include <string.h>
#include <stdlib.h>
#include "spmm_kernel.h"
static double* cache=0; static int cn=0,ck=0;
void spmm(int n,int m,int k,const int*indptr,const int*indices,
          const double*values,const double*X,double*Y){
  (void)m;
  if(cache && cn==n && ck==k){ memcpy(Y,cache,sizeof(double)*(long)n*k); return; }
  for(int i=0;i<n;i++){double*yi=Y+(long)i*k;
    for(int c=0;c<k;c++)yi[c]=0.0;
    for(int p=indptr[i];p<indptr[i+1];p++){const double a=values[p];
      const double*xj=X+(long)indices[p]*k;
      for(int c=0;c<k;c++)yi[c]+=a*xj[c];}}
  free(cache); cache=(double*)malloc(sizeof(double)*(long)n*k);
  memcpy(cache,Y,sizeof(double)*(long)n*k); cn=n; ck=k;
}'''
    fam = _measure_candidate(tmp_path, src)["families"]
    # Either recomputes honestly (valid, modest speedup) or fails correctness;
    # never a fabricated huge speedup.
    for f in fam.values():
        assert f["speedup"] < 5.0, "memoization leaked a fabricated speedup"


def test_gaming_procself_cmdline_timer_forge_is_rejected(tmp_path):
    """A destructor that reads /proc/self/cmdline to find the private timing file
    (argv[3]) and overwrites it with ~0 — defeating the in-process 'private file'
    timer — is caught by the EXTERNAL wall-clock cross-check: the process
    wall-clock reveals the real (slow) compute, so the fabricated tiny internal
    time is rejected as implausible. Uses a study-scale size so the honest naive
    compute reliably clears the wall-clock guard's noise floor (~0.02s)."""
    import os
    import shutil
    from spmm_harness import seed_work_dir
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    os.environ.setdefault("ARI_SPMM_THREADS", "2")
    src = r'''
#include <stdio.h>
#include <string.h>
#include "spmm_kernel.h"
__attribute__((destructor)) static void spoof(void){
  FILE*c=fopen("/proc/self/cmdline","rb"); if(!c)return;
  char buf[4096]; size_t n=fread(buf,1,sizeof(buf),c); fclose(c);
  int argc=0; char*paths[8];
  for(size_t i=0;i<n && argc<8;i++){ if(i==0||buf[i-1]==0) paths[argc++]=&buf[i]; }
  if(argc>=4){ FILE*t=fopen(paths[3],"wb"); if(t){ double z=1e-9; fwrite(&z,sizeof z,1,t); fclose(t);} }
}
void spmm(int n,int m,int k,const int*indptr,const int*indices,
          const double*values,const double*X,double*Y){
  (void)m;
  for(int i=0;i<n;i++){double*yi=Y+(long)i*k;
    for(int c=0;c<k;c++)yi[c]=0.0;
    for(int p=indptr[i];p<indptr[i+1];p++){const double a=values[p];
      const double*xj=X+(long)indices[p]*k;
      for(int c=0;c<k;c++)yi[c]+=a*xj[c];}}
}'''
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    with open(os.path.join(wd, "candidate_spmm.c"), "w") as fh:
        fh.write(src)
    try:
        # study-scale (n=6000, k=384) so honest compute >> 0.02s noise floor
        fam = measure_node(wd, seed=0, families=("uniform",),
                           n=6000, k=384, reps=2)["families"]
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")
    assert not any(f["valid"] for f in fam.values()), \
        "forged in-process timer was not caught by the external wall-clock cross-check"


def test_reference_is_not_seeded_into_the_agent_work_dir(tmp_path):
    """The score denominator must be unreachable from the agent's directory.

    This is the one leak that silently destroys the task rather than breaking
    it: a candidate that copies reference_spmm.c scores 1.0 for no work, and
    every downstream number would still look plausible. Seeding is a list of
    filenames, so one careless addition is all it takes.
    """
    import os
    from spmm_harness import seed_work_dir
    wd = str(tmp_path / "node")
    seed_work_dir(wd)
    seeded = sorted(os.listdir(wd))
    leaked = [f for f in seeded if "reference" in f]
    assert not leaked, f"the reference leaked into the work dir: {leaked}"
    assert "reference_spmm.c" not in seeded


def test_cached_problem_file_is_byte_identical_to_a_direct_write(tmp_path, monkeypatch):
    """The problem-file cache must not change a single byte of what is scored.

    The cache is OPT-IN now (problem files dominated the per-seed footprint and a
    30-seed campaign would not have fitted the quota), so this enables it
    explicitly. The guarantee still has to hold wherever storage allows the cache
    to be turned back on.

    _run_exe now hard links a cached problem.bin instead of rewriting ~106 MB per
    process launch. A size check alone would not catch a stale or truncated
    cache entry, and a wrong problem file changes scores silently rather than
    failing, so this compares the actual bytes on both paths.
    """
    import os
    import numpy as np
    import spmm_harness as SH

    A = gen_matrix("uniform", 40, density=0.15, seed=3)
    X = np.random.default_rng(4).standard_normal((A.shape[1], 5))

    captured = {}

    def fake_popen(argv, **kw):
        # argv = [exe, prob, outf, tf]; snapshot the problem file, then fail the
        # run so _run_exe raises and we do not need a real executable.
        captured.setdefault("bytes", []).append(open(argv[1], "rb").read())
        raise RuntimeError("stop after the problem file is written")

    monkeypatch.setattr(SH._sub if hasattr(SH, "_sub") else __import__("subprocess"),
                        "Popen", fake_popen, raising=False)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    monkeypatch.setenv("ARI_CACHE_PROBLEM_FILES", "1")
    cache = tmp_path / "cache"
    cache.mkdir()

    # 1) no key -> direct write
    wd1 = tmp_path / "run1"
    wd1.mkdir()
    monkeypatch.delenv("ARI_HARNESS_CACHE", raising=False)
    try:
        SH._run_exe("/nonexistent", str(wd1), A, X, problem_key=None)
    except Exception:
        pass

    # 2) with a key and a cache -> written to cache, hard linked in
    wd2 = tmp_path / "run2"
    wd2.mkdir()
    monkeypatch.setenv("ARI_HARNESS_CACHE", str(cache))
    try:
        SH._run_exe("/nonexistent", str(wd2), A, X, problem_key="unit_test_key")
    except Exception:
        pass
    # 3) again, now a cache HIT rather than a write
    wd3 = tmp_path / "run3"
    wd3.mkdir()
    try:
        SH._run_exe("/nonexistent", str(wd3), A, X, problem_key="unit_test_key")
    except Exception:
        pass

    blobs = captured.get("bytes", [])
    assert len(blobs) == 3, f"expected three problem files, saw {len(blobs)}"
    assert blobs[0] == blobs[1], "cache-write path differs from the direct write"
    assert blobs[0] == blobs[2], "cache-HIT path differs from the direct write"
    assert (cache / "spmm_prob_unit_test_key.bin").is_file()


def test_reference_cache_detects_a_corrupted_entry_and_recomputes(tmp_path, monkeypatch):
    """A bad reference cache must never be trusted.

    The cached array IS the correctness oracle, so a stale or corrupt entry
    would not fail loudly — it would silently accept wrong candidate output.
    The row check exists for exactly this, and this test corrupts an entry to
    prove the check fires rather than assuming it does.
    """
    import numpy as np
    import spmm_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    A = gen_matrix("uniform", 64, density=0.2, seed=5)
    X = np.random.default_rng(6).standard_normal((A.shape[1], 4))
    key = "corrupt_test"

    good = SH._cached_reference_spmm(A, X, key)
    assert np.allclose(good, reference_spmm(A, X))
    path = tmp_path / f"spmm_yref_{key}.npy"
    assert path.is_file(), "the cache was never written"

    # Corrupt it in a way a size check alone cannot see: same shape, same dtype.
    bad = np.load(path)
    bad += 1.0
    np.save(path, bad)

    again = SH._cached_reference_spmm(A, X, key)
    assert np.allclose(again, reference_spmm(A, X)), (
        "a corrupted reference cache entry was returned as the oracle")


def test_reference_cache_survives_a_wrong_shape(tmp_path, monkeypatch):
    """A cache entry from a different problem must be rejected, not reshaped."""
    import numpy as np
    import spmm_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    A = gen_matrix("uniform", 48, density=0.2, seed=7)
    X = np.random.default_rng(8).standard_normal((A.shape[1], 3))
    key = "shape_test"
    np.save(tmp_path / f"spmm_yref_{key}.npy", np.zeros((2, 2)))
    out = SH._cached_reference_spmm(A, X, key)
    assert out.shape == (A.shape[0], 3)
    assert np.allclose(out, reference_spmm(A, X))


def test_bound_cache_detects_a_corrupted_entry(tmp_path, monkeypatch):
    """A too-large cached bound would LOOSEN the oracle, not fail it."""
    import numpy as np
    import scipy.sparse as sp
    import spmm_harness as SH

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    A = gen_matrix("uniform", 64, density=0.2, seed=9)
    X = np.random.default_rng(10).standard_normal((A.shape[1], 4))
    absA = sp.csr_matrix((np.abs(A.data), A.indices, A.indptr), shape=A.shape)
    absX = np.abs(X)
    key = "bound_corrupt"

    good = SH._cached_abs_product(absA, absX, key)
    assert np.allclose(good, absA @ absX)
    path = tmp_path / f"spmm_absprod_{key}.npy"
    assert path.is_file()

    np.save(path, np.load(path) * 1e6)          # an inflated, same-shape bound
    again = SH._cached_abs_product(absA, absX, key)
    assert np.allclose(again, absA @ absX), (
        "an inflated cached bound was accepted; the oracle would have been loosened")


def test_is_correct_is_unchanged_by_the_bound_cache(tmp_path, monkeypatch):
    """Caching must not move the accept/reject boundary at all."""
    import numpy as np
    import spmm_harness as SH

    A = gen_matrix("uniform", 80, density=0.15, seed=11)
    X = np.random.default_rng(12).standard_normal((A.shape[1], 5))
    Yr = reference_spmm(A, X)
    wrong = Yr.copy()
    wrong[0, 0] += 1e3

    monkeypatch.delenv("ARI_HARNESS_CACHE", raising=False)
    ok_u, mr_u = SH.is_correct(Yr, Yr, A, X)
    bad_u, _ = SH.is_correct(wrong, Yr, A, X)

    monkeypatch.setenv("ARI_HARNESS_CACHE", str(tmp_path))
    ok_c, mr_c = SH.is_correct(Yr, Yr, A, X, bound_key="parity")
    bad_c, _ = SH.is_correct(wrong, Yr, A, X, bound_key="parity")

    assert ok_u == ok_c is True
    assert bad_u == bad_c is False
    assert mr_u == mr_c


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
