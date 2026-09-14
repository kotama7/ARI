"""Problem-correctness worker: prints one typed report on stdout.

Mirrors ``perf_worker`` deliberately. A candidate that is wrong, or that does not
build, is a SUCCESSFULLY COMPLETED verifier execution whose typed report says
``fail``; a non-zero process status is reserved for verifier or substrate
failure, so infrastructure accounting never conflates the two.
"""

from __future__ import annotations

import argparse
import sys

from ari.assurance.native_problem_correctness import verify_problem_correctness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem", required=True,
                        help="the PINNED problem revision to verify against. A "
                             "problem is a registered directory, so adding a "
                             "research theme is not an ARI edit.")
    parser.add_argument("--candidate", required=True,
                        help="path to the candidate kernel source")
    parser.add_argument("--tier", choices=("screen", "validate", "certify"),
                        required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dataset-revision", default=None,
                        help="the PINNED case set to verify on. A size is chosen "
                             "by naming a registered set, never by passing shapes.")
    parser.add_argument("--compiler", default=None,
                        help="compiler the candidate declared, if any")
    parser.add_argument("--flags", default=None,
                        help="flags the candidate declared, screened before use. "
                             "PASS IT AS --flags=<value>, ALWAYS: a value that "
                             "starts with '-' and contains no space is read by "
                             "argparse as an option, so a candidate declaring "
                             "exactly one flag would fail as a verifier crash "
                             "rather than as a candidate.")
    parser.add_argument("--run-timeout", type=float, default=300.0)
    parser.add_argument("--negative-control", action="store_true",
                        help="label only; recorded in the report and never "
                             "alters a verdict. The controls this harness "
                             "registers against are the problem's own kernels, "
                             "so nothing needs synthetic corruption.")
    args = parser.parse_args(argv)
    report = verify_problem_correctness(
        args.problem, args.candidate, tier=args.tier, seed=args.seed,
        candidate_compiler=args.compiler, candidate_flags=args.flags,
        **({"dataset_revision": args.dataset_revision}
           if args.dataset_revision else {}),
        run_timeout=args.run_timeout, negative_control=args.negative_control)
    sys.stdout.write(report.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
