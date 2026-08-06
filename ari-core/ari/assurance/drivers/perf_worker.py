"""Performance verifier worker: prints one typed report on stdout.

Mirrors ``native_worker`` deliberately. A scientifically slow or wrong candidate
is a SUCCESSFULLY COMPLETED verifier execution whose typed report says ``fail``;
a non-zero process status is reserved for verifier or substrate failure, so
infrastructure accounting never conflates the two.
"""

from __future__ import annotations

import argparse
import sys

from ari.assurance.native_perf import verify_native_perf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", required=True,
                        help="the PINNED problem revision to measure. Not a "
                             "choice out of a fixed list: a problem is a "
                             "registered directory, so adding a research theme "
                             "is not an ARI edit.")
    parser.add_argument("--candidate", required=True,
                        help="path to the candidate kernel source")
    parser.add_argument("--tier", choices=("screen", "validate", "certify"),
                        required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dataset-revision", default=None,
                        help="the PINNED case set to measure on. A size is chosen "
                             "by naming a registered set, never by passing shapes: "
                             "registration evidence is established at a size and "
                             "does not transfer.")
    parser.add_argument("--compiler", default=None,
                        help="compiler the candidate declared, if any")
    parser.add_argument("--flags", default=None,
                        help="flags the candidate declared, screened before use. "
                             "PASS IT AS --flags=<value>, ALWAYS. A value that "
                             "starts with '-' and contains no space is read by "
                             "argparse as an option, so ['--flags', '-O3'] is "
                             "REJECTED while ['--flags', '-O3 -ffast-math'] is "
                             "accepted -- a candidate declaring exactly one flag "
                             "would fail as a verifier crash rather than as a "
                             "candidate. Measured, not reasoned about.")
    parser.add_argument("--regression-threshold", type=float, default=1.0)
    parser.add_argument("--run-timeout", type=float, default=300.0)
    parser.add_argument("--negative-control", action="store_true")
    args = parser.parse_args(argv)
    report = verify_native_perf(
        args.problem, args.candidate, tier=args.tier, seed=args.seed,
        candidate_compiler=args.compiler, candidate_flags=args.flags,
        **({"dataset_revision": args.dataset_revision}
           if args.dataset_revision else {}),
        regression_threshold=args.regression_threshold,
        run_timeout=args.run_timeout, negative_control=args.negative_control)
    sys.stdout.write(report.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
