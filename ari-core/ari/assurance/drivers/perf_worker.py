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
    parser.add_argument("--kind", choices=("gemm",), required=True)
    parser.add_argument("--candidate", required=True,
                        help="path to the candidate kernel source")
    parser.add_argument("--tier", choices=("screen", "validate", "certify"),
                        required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--compiler", default=None,
                        help="compiler the candidate declared, if any")
    parser.add_argument("--flags", default=None,
                        help="flags the candidate declared, screened before use")
    parser.add_argument("--regression-threshold", type=float, default=1.0)
    parser.add_argument("--run-timeout", type=float, default=300.0)
    parser.add_argument("--negative-control", action="store_true")
    args = parser.parse_args(argv)
    report = verify_native_perf(
        args.kind, args.candidate, tier=args.tier, seed=args.seed,
        candidate_compiler=args.compiler, candidate_flags=args.flags,
        regression_threshold=args.regression_threshold,
        run_timeout=args.run_timeout, negative_control=args.negative_control)
    sys.stdout.write(report.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
