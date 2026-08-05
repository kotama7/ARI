"""Pre-compute the oracle caches before a campaign starts.

Measured on the stencil band run: the first scoring took 1720.5 s and every
later one took ~112 s, a factor of 15.4. The whole difference is the numpy
oracle - reference_jacobi at nt=240, reference_spmm and its |A|@|X| bound - being
computed for the first time. Those values are deterministic functions of the
problem, so they are the same for EVERY node in the campaign; the only question
is which unlucky node pays for them.

Left alone, that is the first node of the run, and it pays it inside its own
per-node timeout. A node that spends 29 minutes filling a shared cache can hit
the watchdog and be recorded as an infrastructure failure - a node lost to
bookkeeping, not to science.

Run this once per (task, size) before launching. It is idempotent: an entry that
already verifies is left alone, so re-running after a partial fill costs only
the verification.
"""
import argparse
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[3]


def warm(task: str, reps: int, seed: int, extra: dict) -> None:
    sys.path.insert(0, str(REPO / "ari-core"))
    sys.path.insert(0, str(REPO / f"workspace/harnesses/{task}"))
    os.environ.setdefault("ARI_WORKSPACE", str(REPO / "workspace"))
    H = __import__(f"{task}_harness")

    cache = os.environ.get("ARI_HARNESS_CACHE", "")
    if not cache:
        print("ARI_HARNESS_CACHE is unset — nothing would be cached; refusing.",
              file=sys.stderr)
        raise SystemExit(2)
    print(f"task={task} reps={reps} seed={seed} cache={cache}")

    t0 = time.monotonic()
    n_done = 0
    if task == "stencil":
        for shape in H.SHAPES:
            for r in range(reps):
                input_seed = seed * 100003 + r
                key = f"stencil_{shape[0]}x{shape[1]}x{shape[2]}t{shape[3]}_s{input_seed}"
                u0, nx, ny, nz, nt = H.gen_problem(shape, seed=input_seed)
                H._cached_reference_jacobi(u0, nx, ny, nz, nt, key)
                n_done += 1
                print(f"  {key}  ({n_done}) {time.monotonic()-t0:7.1f}s", flush=True)
    elif task == "spmm":
        import numpy as np
        n = int(extra.get("n", 20000)); k = int(extra.get("k", 64))
        import scipy.sparse as sp
        for fam in H.FAMILIES:
            A = H._gen_matrix_cached(fam, n, seed=seed)
            absA = sp.csr_matrix((abs(A.data), A.indices, A.indptr), shape=A.shape)
            for r in range(reps):
                input_seed = seed * 100003 + r + 1
                key = f"{fam}_n{n}_k{k}_s{seed}_r{input_seed}"
                X = np.random.default_rng(input_seed).standard_normal((A.shape[1], k))
                H._cached_reference_spmm(A, X, key)
                H._cached_abs_product(absA, abs(X), key)
                n_done += 1
                print(f"  {key}  ({n_done}) {time.monotonic()-t0:7.1f}s", flush=True)
    else:
        print(f"{task}: python oracle costs 0.14 s per repetition — no warming needed")
        return
    print(f"\nwarmed {n_done} entries in {time.monotonic()-t0:.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task", choices=("gemm", "spmm", "stencil"))
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--k", type=int, default=64)
    a = ap.parse_args()
    warm(a.task, a.reps, a.seed, {"n": a.n, "k": a.k})
