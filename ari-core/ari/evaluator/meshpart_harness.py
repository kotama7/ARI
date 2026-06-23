"""Mesh/graph partitioning measurement harness (handoff study task C — the
combinatorial-optimization Goldilocks candidate). The agent writes a balanced
k-way graph partitioner; the score combines edge-cut AND balance into a single
objective in [0,1] so it cannot be gamed by imbalancing (a degenerate
all-in-one-part partition has cut 0 but balance 0 -> score 0).

Why combinatorial optimization (vs the speed/accuracy tasks): ANY partition is a
valid, scoreable solution (no compile-or-die "None" nodes — the failure mode that
killed erfc for weak models), and the optimum is NP-hard (no terminal "solved"
state), so weak/mid models produce valid-but-suboptimal partitions that children
can refine — i.e. the valid-partial-progress regime handoff needs. (gpt-5.2 is
too strong: it one-shots ~spectral quality; the Goldilocks window is 8b/32b.)

Score design:
  imb = max_part_size / (N/k)            # 1.0 = perfect balance
  bal = 1                      if imb <= IMB_MAX (1.05)
        max(0, 1-(imb-IMB_MAX))  otherwise   (graded soft constraint; 2.05->0,
                                              degenerate all-in-one-part -> 0)
  q   = clamp((random_cut - cut) / (random_cut - 0.9*ref_cut), 0, 1)
  score = bal * q              # both balanced AND low-cut required
  ref_cut = min(recursive-spectral, BFS-block) cut   # robust, always defined

The balance decay is intentionally GRADED (not a cliff at 1.05): real greedy/BFS
partitioners land near imb 1.10-1.15, so a soft penalty preserves the partial-
credit gradient (children can climb cut quality without a balance step wiping it)
while still requiring imb <= 1.05 for full credit and zeroing degenerate partitions.
"""
from __future__ import annotations

import os
from typing import Any, Callable

import numpy as np

KWAY = 4
IMB_MAX = 1.05
N_NODES = 1500
KNN = 6
LONG_EDGE_FRAC = 0.01


def gen_mesh(seed: int = 0):
    """Procedural CUSTOM mesh (no memorized answer): 2D k-NN graph + a few
    long-range edges. Returns (N, k, xadj, adjncy, edges, pts). Deterministic."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    n = N_NODES
    pts = rng.random((n, 2))
    tree = cKDTree(pts)
    _, nbr = tree.query(pts, k=KNN + 1)
    edges = set()
    for i in range(n):
        for j in nbr[i, 1:]:
            a, b = int(i), int(j)
            edges.add((min(a, b), max(a, b)))
    for _ in range(n // int(1 / LONG_EDGE_FRAC)):
        a, b = int(rng.integers(0, n)), int(rng.integers(0, n))
        if a != b:
            edges.add((min(a, b), max(a, b)))
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b); adj[b].append(a)
    xadj = [0]; adjncy: list[int] = []
    for i in range(n):
        adjncy += sorted(adj[i]); xadj.append(len(adjncy))
    return (n, KWAY, np.array(xadj, np.int32), np.array(adjncy, np.int32),
            edges, pts)


def edge_cut(part, edges) -> int:
    p = np.asarray(part)
    return int(sum(1 for a, b in edges if p[a] != p[b]))


def imbalance(part, n: int, k: int) -> float:
    sizes = np.bincount(np.asarray(part), minlength=k)
    return float(sizes.max() / (n / k))


def _spectral_cut(n, k, edges):
    """A strong (but beatable) reference cut via recursive spectral bisection."""
    import scipy.sparse as sp
    from scipy.sparse.linalg import eigsh
    def bisect(idx):
        if len(idx) <= 1:
            return [idx]
        sub = set(int(x) for x in idx); m = {int(x): i for i, x in enumerate(idx)}
        rows = []; cols = []
        for a, b in edges:
            if a in sub and b in sub:
                rows += [m[a], m[b]]; cols += [m[b], m[a]]
        nn = len(idx)
        if not rows:
            return [idx[:nn // 2], idx[nn // 2:]]
        A = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(nn, nn))
        d = np.asarray(A.sum(1)).ravel(); L = sp.diags(d) - A
        try:
            _w, v = eigsh(L.astype(float), k=2, which="SM"); f = v[:, 1]
        except Exception:
            f = d
        order = np.argsort(f); h = nn // 2
        return [idx[order[:h]], idx[order[h:]]]
    groups = [np.arange(n)]
    while len(groups) < k:
        groups = [g for blk in groups for g in bisect(blk)]
    part = np.zeros(n, int)
    for lab, blk in enumerate(groups[:k]):
        part[blk] = lab
    return edge_cut(part, edges)


def _bfs_block_cut(n, k, xadj, adjncy, edges) -> int:
    """A deterministic, always-succeeding graph-aware reference cut: visit
    vertices in BFS order, then assign equal contiguous blocks of that order to
    the k parts. On a proximity graph this yields spatially-coherent regions
    (cut far below random). Used to make the reference robust when the spectral
    solver fails, and as a floor the spectral cut is expected to beat."""
    from collections import deque
    seen = np.zeros(n, dtype=bool)
    order = np.empty(n, dtype=np.int64)
    oi = 0
    for s in range(n):
        if seen[s]:
            continue
        seen[s] = True
        q = deque([s])
        while q:
            u = q.popleft(); order[oi] = u; oi += 1
            for e in range(int(xadj[u]), int(xadj[u + 1])):
                v = int(adjncy[e])
                if not seen[v]:
                    seen[v] = True; q.append(v)
    part = np.empty(n, dtype=np.int64)
    per = (n + k - 1) // k
    for i in range(n):
        p = i // per
        part[int(order[i])] = p if p < k else k - 1
    return edge_cut(part, edges)


def compute_score(cut: float, imb: float, random_cut: float, ref_cut: float,
                  imb_max: float = IMB_MAX) -> float:
    """Single combined objective in [0,1]: balanced AND low-cut required."""
    if imb <= imb_max:
        bal = 1.0
    else:
        # graded soft penalty: linear to 0 by imb = imb_max + 1.0 (= 2.05), so a
        # mildly-imbalanced good cut keeps partial credit (no hard cliff) while a
        # degenerate all-in-one-part (imb = k) still scores 0.
        bal = max(0.0, 1.0 - (imb - imb_max))
    denom = max(random_cut - 0.9 * ref_cut, 1.0)
    q = (random_cut - cut) / denom
    q = min(max(q, 0.0), 1.0)
    return float(bal * q)


# ---- frozen scaffolding ----------------------------------------------------
_FROZEN_FIXTURES: tuple[str, ...] = (
    "meshpart_kernel.h", "meshpart_main.c", "baseline_meshpart.c", "Makefile", "selftest.c",
)


def kernels_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "meshpart_kernels")


def _write_mesh_bin(path: str, n, k, xadj, adjncy):
    with open(path, "wb") as fh:
        np.array([n, k, len(adjncy)], np.int32).tofile(fh)
        xadj.astype(np.int32).tofile(fh)
        adjncy.astype(np.int32).tofile(fh)


def seed_work_dir(work_dir: str) -> list[str]:
    import shutil
    src_dir = kernels_dir()
    os.makedirs(work_dir, exist_ok=True)
    written: list[str] = []
    for name in _FROZEN_FIXTURES:
        src = os.path.join(src_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(work_dir, name))
            written.append(name)
    cand = os.path.join(work_dir, "candidate_meshpart.c")
    if not os.path.exists(cand):
        s = os.path.join(src_dir, "candidate_meshpart.c")
        if os.path.isfile(s):
            shutil.copy2(s, cand)
            written.append("candidate_meshpart.c")
    # seed a self-test mesh (DISTINCT seed from the evaluator's hidden mesh)
    try:
        n, k, xadj, adjncy, _e, _p = gen_mesh(seed=99173)
        _write_mesh_bin(os.path.join(work_dir, "selftest_mesh.bin"), n, k, xadj, adjncy)
        written.append("selftest_mesh.bin")
    except Exception:
        pass
    return written


def _default_run_kernel(work_dir: str, mesh_bin: str, n: int):
    import subprocess
    import tempfile
    kdir = kernels_dir()
    main_c = os.path.join(kdir, "meshpart_main.c")
    kern_c = os.path.join(work_dir or "", "candidate_meshpart.c")
    if not os.path.isfile(kern_c):
        raise RuntimeError(f"candidate not found: {kern_c}")
    cc = os.environ.get("ARI_MESHPART_CC", "cc")
    with tempfile.TemporaryDirectory() as td:
        exe = os.path.join(td, "mp.exe")
        cp = subprocess.run([cc, "-O2", f"-I{kdir}", main_c, kern_c, "-o", exe, "-lm"],
                            capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(f"compile failed: {cp.stderr.strip()[-600:]}")
        rp = subprocess.run([exe, mesh_bin], capture_output=True, text=True, timeout=300)
        if rp.returncode != 0:
            raise RuntimeError(f"run failed: {rp.stderr.strip()[-400:]}")
        part = np.array([int(z) for z in rp.stdout.split()], dtype=np.int64)
    if part.shape != (n,):
        raise RuntimeError(f"partition size {part.shape} != n {n}")
    return part


def measure_node(work_dir: str, *, run_kernel: Callable | None = None, seed: int = 0) -> dict:
    """Compile + run the candidate partitioner on the HIDDEN mesh (seed), score
    with the combined cut+balance objective. Returns a score-shaped dict."""
    import tempfile
    n, k, xadj, adjncy, edges, _pts = gen_mesh(seed=seed)
    rng = np.random.default_rng(seed + 7)
    random_cut = edge_cut(rng.integers(0, k, n), edges)
    # Robust reference: a deterministic graph-aware BFS-block cut always succeeds;
    # the recursive-spectral cut is normally tighter (better), so take the min.
    # If the spectral solver fails, fall back to the BFS-block cut (a real,
    # reachable reference) rather than a magic constant.
    bfs_cut = _bfs_block_cut(n, k, xadj, adjncy, edges)
    spectral_ok = True
    try:
        ref_cut = min(_spectral_cut(n, k, edges), bfs_cut)
    except Exception:
        ref_cut = bfs_cut
        spectral_ok = False
    run = run_kernel or _default_run_kernel
    try:
        if run_kernel is None:
            td = tempfile.mkdtemp(prefix="mp_mesh_")
            mb = os.path.join(td, "mesh.bin"); _write_mesh_bin(mb, n, k, xadj, adjncy)
            part = run(work_dir, mb, n)
        else:
            part = run(work_dir, None, n)
    except Exception as e:
        return {"compile_ok": False, "score": 0.0, "reason": f"meshpart run failed: {e}"}
    if part.min() < 0 or part.max() >= k:
        return {"compile_ok": True, "score": 0.0, "reason": "invalid part labels"}
    cut = edge_cut(part, edges)
    imb = imbalance(part, n, k)
    score = compute_score(cut, imb, random_cut, ref_cut)
    return {"compile_ok": True, "score": score, "cut": cut, "imbalance": imb,
            "random_cut": random_cut, "spectral_cut": ref_cut,
            "regions": {"edge_cut_ratio": (ref_cut / cut) if cut else 2.0,
                        "balanced": 1.0 if imb <= IMB_MAX else 0.0},
            "reason": "ok" if spectral_ok else "ok (spectral fallback: BFS-block reference)"}
