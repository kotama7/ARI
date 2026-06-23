"""Tests for the mesh/graph partitioning harness (Goldilocks task C, combinatorial).

Covers the procedural custom mesh (CSR validity, determinism, distinct seeds), the
combined cut+balance score (and that it cannot be gamed by imbalancing), the
edge_cut/imbalance helpers, measure_node with injected pattern runners, the
work_dir seeder, and the evaluator's score-shaped contract. The real compile/run
path is exercised by a login smoke test (skips without a C compiler).
"""
import os

import numpy as np
import pytest

from ari.evaluator import meshpart_harness as M


def test_gen_mesh_deterministic_csr_and_distinct_seeds():
    n0, k0, xadj0, adj0, edges0, pts0 = M.gen_mesh(seed=0)
    n1, k1, xadj1, adj1, edges1, _ = M.gen_mesh(seed=0)  # same seed -> identical
    assert n0 == M.N_NODES and k0 == M.KWAY
    assert np.array_equal(xadj0, xadj1) and np.array_equal(adj0, adj1)
    # CSR shape invariants
    assert xadj0.shape == (n0 + 1,) and xadj0[0] == 0 and xadj0[-1] == adj0.size
    assert np.all(np.diff(xadj0) >= 0)            # monotonic non-decreasing
    assert adj0.min() >= 0 and adj0.max() < n0
    # undirected: every neighbor relation is symmetric
    a, b = next(iter(edges0))
    assert b in adj0[xadj0[a]:xadj0[a + 1]] and a in adj0[xadj0[b]:xadj0[b + 1]]
    # distinct seeds -> essentially different graphs (no memorized answer)
    _, _, _, _, edges_s, _ = M.gen_mesh(seed=12345)
    assert len(edges0 ^ edges_s) > 0.5 * len(edges0)


def test_edge_cut_and_imbalance_helpers():
    edges = {(0, 1), (1, 2), (2, 3)}            # 4-node path
    assert M.edge_cut([0, 0, 1, 1], edges) == 1  # only (1,2) crosses
    assert M.edge_cut([0, 0, 0, 0], edges) == 0
    assert M.imbalance([0, 0, 1, 1], 4, 2) == pytest.approx(1.0)
    assert M.imbalance([0, 0, 0, 0], 4, 2) == pytest.approx(2.0)  # all in one part


def test_compute_score_balanced_lowcut_and_anti_gaming():
    rnd, ref = 1000.0, 100.0
    # balanced and cut ~ reference -> near 1
    assert M.compute_score(100, 1.0, rnd, ref) > 0.95
    # balanced and cut below 0.9*ref -> clamps to 1
    assert M.compute_score(50, 1.0, rnd, ref) == pytest.approx(1.0)
    # worse-than-random cut -> q clamps to 0
    assert M.compute_score(1200, 1.0, rnd, ref) == pytest.approx(0.0)
    # DEGENERATE all-in-one-part: cut 0 but imbalance k -> balance kills it -> 0
    assert M.compute_score(0, float(M.KWAY), rnd, ref) == pytest.approx(0.0)


def test_compute_score_balance_decay_is_graded_not_a_cliff():
    rnd, ref = 1000.0, 100.0
    full = M.compute_score(100, 1.0, rnd, ref)
    # graded, monotonically decreasing soft penalty (no hard cliff at 1.55):
    s130 = M.compute_score(100, 1.30, rnd, ref)
    s155 = M.compute_score(100, 1.55, rnd, ref)
    s200 = M.compute_score(100, 2.00, rnd, ref)
    assert full > s130 > s155 > s200 > 0.0     # all still earn partial credit
    assert s155 > 0.4                          # mid-imbalance is NOT wiped to 0
    # only reaches 0 at imb = IMB_MAX + 1.0 (= 2.05), and stays 0 past it
    assert M.compute_score(100, M.IMB_MAX + 1.0, rnd, ref) == pytest.approx(0.0)
    assert M.compute_score(100, 3.0, rnd, ref) == pytest.approx(0.0)


def test_bfs_block_reference_beats_random():
    n, k, xadj, adjncy, edges, _ = M.gen_mesh(seed=0)
    rng = np.random.default_rng(7)
    random_cut = M.edge_cut(rng.integers(0, k, n), edges)
    bfs = M._bfs_block_cut(n, k, xadj, adjncy, edges)
    assert 0 < bfs < random_cut                # a real, graph-aware reachable cut


def test_spectral_failure_falls_back_to_bfs_block_reference(monkeypatch):
    # if the spectral solver fails, ref_cut falls back to the deterministic
    # BFS-block cut (a real reachable reference), not a magic constant; scoring
    # still works and the reason flags the fallback.
    def boom(n, k, edges):
        raise RuntimeError("eigsh failed")
    monkeypatch.setattr(M, "_spectral_cut", boom)
    out = M.measure_node("", run_kernel=_runner(lambda n: np.arange(n) % M.KWAY), seed=0)
    assert out["compile_ok"] and "fallback" in out["reason"]
    n, k, xadj, adjncy, edges, _ = M.gen_mesh(seed=0)
    assert out["spectral_cut"] == M._bfs_block_cut(n, k, xadj, adjncy, edges)


def _runner(make_part):
    def run(work_dir, mesh_bin, n):
        return np.asarray(make_part(n), dtype=np.int64)
    return run


def test_measure_node_random_and_roundrobin_score_low():
    rand = M.measure_node("", run_kernel=_runner(
        lambda n: np.random.default_rng(1).integers(0, M.KWAY, n)), seed=0)
    assert rand["compile_ok"] and rand["score"] < 0.15
    rr = M.measure_node("", run_kernel=_runner(lambda n: np.arange(n) % M.KWAY), seed=0)
    assert rr["compile_ok"] and rr["score"] < 0.15


def test_measure_node_degenerate_is_zero_not_none():
    # all-in-one-part is a VALID (compiling) but worthless partition -> score 0,
    # NOT None: combinatorial tasks never produce compile-or-die None nodes.
    out = M.measure_node("", run_kernel=_runner(lambda n: np.zeros(n, int)), seed=0)
    assert out["compile_ok"] and out["score"] == pytest.approx(0.0)


def test_measure_node_invalid_labels_scored_zero():
    out = M.measure_node("", run_kernel=_runner(lambda n: np.full(n, M.KWAY)), seed=0)
    assert out["compile_ok"] and out["score"] == 0.0 and "invalid" in out["reason"]


def test_measure_node_run_failure_is_zero():
    def boom(work_dir, mesh_bin, n):
        raise RuntimeError("nope")
    out = M.measure_node("", run_kernel=boom, seed=0)
    assert out["compile_ok"] is False and out["score"] == 0.0


def test_seed_work_dir_seeds_scaffolding_and_selftest_mesh(tmp_path):
    wd = str(tmp_path / "node")
    written = M.seed_work_dir(wd)
    for f in (*M._FROZEN_FIXTURES, "candidate_meshpart.c", "selftest_mesh.bin"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing {f}"
        assert f in written
    # candidate edits preserved; frozen driver restored on re-seed
    cand = os.path.join(wd, "candidate_meshpart.c")
    with open(cand, "a") as fh:
        fh.write("\n/* edit */\n")
    with open(os.path.join(wd, "meshpart_main.c"), "w") as fh:
        fh.write("/* tampered */\n")
    M.seed_work_dir(wd)
    assert "/* edit */" in open(cand).read()
    assert "tampered" not in open(os.path.join(wd, "meshpart_main.c")).read()


def test_evaluator_score_shaped_path():
    from ari.evaluator.deterministic_evaluator import DeterministicEvaluator
    ev = DeterministicEvaluator()
    out = ev._score({"compile_ok": True, "score": 0.74, "cut": 974, "imbalance": 1.0,
                     "regions": {"edge_cut_ratio": 1.2, "balanced": 1.0}, "reason": "ok"})
    assert out["metrics"]["_scientific_score"] == pytest.approx(0.74)
    assert out["metrics"]["valid_geomean_speedup"] == pytest.approx(0.74)  # analyzer hook
    assert out["valid"] and out["has_real_data"]
    assert out["metrics"]["region_balanced"] == pytest.approx(1.0)


_GOOD_PARTITIONER = r"""
#include "meshpart_kernel.h"
#include <stdlib.h>
void partition(int n, int k, const int *xadj, const int *adjncy, int *part) {
    int *order = (int*)malloc(sizeof(int)*n);
    char *seen = (char*)calloc(n,1);
    int *q = (int*)malloc(sizeof(int)*n);
    int qh=0, qt=0, oi=0;
    for (int s=0; s<n; s++) {
        if (seen[s]) continue;
        seen[s]=1; q[qt++]=s;
        while (qh<qt) {
            int u=q[qh++]; order[oi++]=u;
            for (int e=xadj[u]; e<xadj[u+1]; e++){int v=adjncy[e]; if(!seen[v]){seen[v]=1; q[qt++]=v;}}
        }
    }
    int per=(n+k-1)/k;
    for (int i=0;i<n;i++){int p=i/per; if(p>=k)p=k-1; part[order[i]]=p;}
    free(order); free(seen); free(q);
}
"""


def test_default_path_compiles_baseline_low_good_high(tmp_path):
    """Login smoke: real compile/run gives the cut+balance gradient — the seeded
    round-robin baseline scores ~0, a graph-aware BFS-block partitioner scores high."""
    import shutil
    if shutil.which(os.environ.get("ARI_MESHPART_CC", "cc")) is None:
        pytest.skip("no C compiler")
    wd = str(tmp_path / "node")
    M.seed_work_dir(wd)
    try:
        base = M.measure_node(wd, seed=0)               # round-robin baseline as seeded
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert base["compile_ok"] and base["score"] < 0.1
    with open(os.path.join(wd, "candidate_meshpart.c"), "w") as fh:
        fh.write(_GOOD_PARTITIONER)
    good = M.measure_node(wd, seed=0)
    assert good["compile_ok"] and good["score"] > 0.5
    assert good["cut"] < base["cut"] and good["imbalance"] <= M.IMB_MAX
