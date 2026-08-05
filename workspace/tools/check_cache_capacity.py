"""Will the campaign's oracle cache fit before it fills the quota?

WHY THIS EXISTS. The harness caches, per repetition, both the generated problem
and the reference solution, keyed by the input seed. The final re-measurement
derives that seed as ``remeasure_seed = run_seed + 1_000_000`` and then
``input_seed = remeasure_seed * 100003 + rep``, so **every run seed produces a
fresh set of 15 problems per shape**. The cache therefore grows linearly in the
seed count, and a one-seed pre-flight cannot show it: measured here one seed
costs 24.6 GB, so a 30-seed campaign wants ~736 GB against 670 GB of remaining
quota.

The failure mode if it is not checked is bad. The quota is hit part-way through,
cache writes start failing, the oracle is recomputed instead of read, and the
runs that happen to be late in the campaign time out — so the damage lands
non-uniformly across seeds, which is exactly where a paired design cannot absorb
it.

The projection is self-calibrating: it measures the bytes an EXISTING remeasure
seed actually occupies rather than trusting a formula, then multiplies by the
seed count the campaign asks for.

USAGE
    python check_cache_capacity.py --seeds 30
    python check_cache_capacity.py --seeds 30 --quiet   # exit 1 if it will not fit
"""
import argparse
import collections
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CACHE = REPO / "workspace/checkpoints/harness_cache"

# input_seed = (run_seed + 1_000_000) * 100003 + rep  -- see run_handoff_ablation.py
# and each harness's _measure_node_once.
_REMEASURE_BASE = 1_000_000
_SEED_STRIDE = 100003
# TWO KEY ENCODINGS COEXIST, and assuming one silently drops the other:
#   gemm, stencil : ``_s{input_seed}``   with input_seed = seed * 100003 + rep
#   spmm          : ``_s{seed}_r{rep}``  -- seed and rep kept separate
# The first version of this file matched only the fused form and therefore
# missed every spmm entry, which is 57% of the per-seed volume. It reported
# 11.8 GB per seed instead of 24.6 and concluded a 30-seed campaign would fit
# when it will not.
_FUSED_RE = re.compile(r"_s(\d{6,})(?![\d]*_r)")
_SPLIT_RE = re.compile(r"_s(\d+)_r\d+")


def _matches_run_seed(name: str, run_seed: int) -> bool:
    remeasure = run_seed + _REMEASURE_BASE
    m = _SPLIT_RE.search(name)
    if m:
        return int(m.group(1)) == remeasure
    m = _FUSED_RE.search(name)
    if m:
        lo = remeasure * _SEED_STRIDE
        return lo <= int(m.group(1)) < lo + 10_000   # generous bound on reps
    return False


def _is_problem(name: str) -> bool:
    return name.startswith(("prob_", "spmm_prob_"))


def _bytes_for_remeasure_seed(cache: pathlib.Path, run_seed: int,
                              count_problems: bool = True) -> tuple[int, int]:
    """Bytes and file count a run seed's re-measurement will occupy.

    ``count_problems`` reflects ARI_CACHE_PROBLEM_FILES: with problem caching off
    those entries are never written, so counting the ones an earlier campaign
    left behind would project a campaign four times larger than the one about to
    run -- and refuse it.
    """
    total = count = 0
    for p in cache.iterdir():
        if not p.is_file() or not _matches_run_seed(p.name, run_seed):
            continue
        if not count_problems and _is_problem(p.name):
            continue
        total += p.stat().st_size
        count += 1
    return total, count


def _quota_bytes(path: pathlib.Path) -> tuple[int, int] | None:
    """(used, limit) in bytes from lfs quota, or None when unavailable."""
    try:
        out = subprocess.run(["lfs", "quota", "-u", os.environ.get("USER", ""), str(path)],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].startswith("/"):
            try:                       # lfs reports kbytes without -h
                return int(parts[1]) * 1024, int(parts[3]) * 1024
            except ValueError:
                return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--calibrate-seed", type=int, default=0,
                    help="run seed whose cached bytes are used as the per-seed cost")
    ap.add_argument("--quiet", action="store_true",
                    help="print one line and exit 1 if the campaign will not fit")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache) if args.cache else DEFAULT_CACHE
    if not cache.is_dir():
        print(f"no cache directory at {cache}; nothing to project")
        return 0

    # Problem files are opt-in now, so entries left on disk from before the
    # change must not inflate the projection of what a campaign will WRITE.
    cache_problems = os.environ.get("ARI_CACHE_PROBLEM_FILES", "0") == "1"
    per_seed, n_files = _bytes_for_remeasure_seed(
        cache, args.calibrate_seed, count_problems=cache_problems)
    if per_seed == 0:
        print(f"no cached entries for run seed {args.calibrate_seed}; "
              "run a --preflight first so the projection has something to measure")
        return 0

    projected = per_seed * args.seeds
    current = sum(p.stat().st_size for p in cache.iterdir() if p.is_file())
    already = per_seed                      # the calibration seed is already on disk
    additional = projected - already

    q = _quota_bytes(cache)
    gb = 1024 ** 3
    if args.quiet:
        head = (f"cache projection: {args.seeds} seeds x {per_seed/gb:.1f} GB = "
                f"{projected/gb:.0f} GB")
        if q:
            used, limit = q
            free = limit - used
            print(f"{head}; additional {additional/gb:.0f} GB vs {free/gb:.0f} GB free")
            return 1 if additional > free else 0
        print(head + "; quota unknown")
        return 0

    print(f"cache            : {cache}")
    print(f"currently on disk: {current/gb:.1f} GB")
    print(f"per run seed     : {per_seed/gb:.2f} GB ({n_files} files, "
          f"calibrated on seed {args.calibrate_seed})")
    print(f"projected total  : {args.seeds} seeds x {per_seed/gb:.2f} = "
          f"{projected/gb:.0f} GB   (additional {additional/gb:.0f} GB)")
    if q:
        used, limit = q
        print(f"quota            : {used/gb:.0f} GB used of {limit/gb:.0f} GB "
              f"({(limit-used)/gb:.0f} GB free)")
        if additional > limit - used:
            print()
            print("WILL NOT FIT. The quota is hit part-way through, cache writes")
            print("then fail, oracles are recomputed instead of read, and the runs")
            print("late in the campaign time out -- so the damage lands on some")
            print("seeds and not others, which a paired design cannot absorb.")
            print()
            print(f"Roughly {100*_problem_share(cache, args.calibrate_seed):.0f}% of this "
                  "is generated PROBLEM files, not reference solutions; they are")
            print("deterministic from the seed and cost well under a second to")
            print("regenerate. Caching only the solutions is the cheap lever.")
            return 1
        print("\nfits.")
    return 0


def _problem_share(cache: pathlib.Path, run_seed: int) -> float:
    """Fraction of one seed's cached bytes that is regenerable problem data."""
    tot = collections.Counter()
    for p in cache.iterdir():
        if not p.is_file() or not _matches_run_seed(p.name, run_seed):
            continue
        kind = "problem" if p.name.startswith(("prob_", "spmm_prob_")) else "oracle"
        tot[kind] += p.stat().st_size
    total = sum(tot.values())
    return tot["problem"] / total if total else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
