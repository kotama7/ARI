"""Profiler worker: prints one typed profile on stdout.

Deliberately a SEPARATE worker from the verdict path. A profile is diagnostic —
it has no threshold, no negative control and no verdict — and running it in the
same process as the scored measurement would put the counter tool's fork/exec
between two timings it is supposed to sit outside.

Exit status is reserved for substrate failure. A candidate that could not be
profiled is a completed run whose typed profile records the error per point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ari.assurance.native_perf_profile import profile_problem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", required=True,
                        help="the PINNED problem revision to profile")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--dataset-revision", default=None,
                        help="the PINNED case set to profile on, so a profile and "
                             "a score can be read next to each other")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--reps", type=int, default=3,
                        help="independent PROCESSES per case (default 3: one "
                             "point has no spread)")
    parser.add_argument("--compiler", default=None)
    parser.add_argument("--flags", default=None,
                        help="PASS IT AS --flags=<value>, ALWAYS: a value that "
                             "starts with '-' and has no space is read by "
                             "argparse as an option, so a single declared flag "
                             "is rejected while two are accepted")
    parser.add_argument("--line-bytes", type=int, default=None,
                        help="L1 data line size, if the OS will not say. MEASURED "
                             "values only; without it the ratio is suppressed "
                             "rather than computed from a guess.")
    parser.add_argument("--l2-granule-bytes", type=int, default=None,
                        help="the unit L2D_CACHE_REFILL ticks in -- NOT the L1 "
                             "line. Measured at 128 B against a 256 B line here, "
                             "so passing the line size doubles the traffic.")
    parser.add_argument("--run-timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    profile = profile_problem(
        args.problem, Path(args.candidate),
        dataset_revision=args.dataset_revision,
        seed=args.seed, reps=args.reps, candidate_compiler=args.compiler,
        candidate_flags=args.flags, line_bytes=args.line_bytes,
        l2_granule_bytes=args.l2_granule_bytes, run_timeout=args.run_timeout)
    sys.stdout.write(profile.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
