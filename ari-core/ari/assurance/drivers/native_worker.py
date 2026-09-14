"""Hidden-case native HPC verifier worker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ari.assurance.native_hpc import (  # noqa: E402
    NativeHPCVerificationReportV1, registered_native_families,
    verify_native_hpc)
from ari.assurance.native_perf_common import sandbox_record  # noqa: E402


def _candidate(kind: str, library: str, timeout: float,
               observed: dict | None = None):
    """The candidate as a callable, and what its launches ran under.

    WHY THE OBSERVATION IS COLLECTED HERE. A family verifies a ``Callable`` and
    never launches anything, so it cannot know what the candidate ran under.
    This function is what spawns the isolated host, so it is the only place that
    can say -- the same reason ``run_timed`` observes in the parent for the other
    two families.
    """
    package_root = Path(__file__).resolve().parents[3]

    def invoke(case):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ari.assurance.drivers.native_candidate_host",
                "--kind",
                kind,
                "--library",
                library,
            ],
            input=json.dumps(case, allow_nan=True),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": str(package_root),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            },
        )
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"candidate host emitted malformed output (exit={completed.returncode})"
            ) from exc
        if completed.returncode != 0 or not envelope.get("ok"):
            raise RuntimeError(str(envelope.get("error") or "candidate host failed"))
        if observed is not None and isinstance(envelope.get("sandbox"), dict):
            # LAST WRITER RATHER THAN FIRST, deliberately. Every launch of one
            # verification is in one namespace, so the answers agree; if a
            # future host ever disagreed between cases, the record should show
            # the condition the report was finished under and not the one it
            # started under.
            observed.update(envelope["sandbox"])
        return envelope["result"]

    return invoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    # Validated against what is REGISTERED, so the accepted set and the set the
    # verifier can actually dispatch cannot drift apart.
    parser.add_argument("--kind", choices=registered_native_families(), required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--tier", choices=("screen", "validate", "certify"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--case-timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    sandbox: dict = {}
    report = verify_native_hpc(
        args.kind,
        _candidate(args.kind, args.library, args.case_timeout, sandbox),
        tier=args.tier,
        seed=args.seed,
    )
    # RE-CREATED RATHER THAN MUTATED, because the digest has to cover it. The
    # family builds the report and does not launch; this worker launches and
    # does not verify. Attaching the record here is what lets the report carry a
    # field neither half could fill alone, with report_digest computed over it.
    fields = report.model_dump(mode="python", exclude={"report_digest"})
    fields["sandbox"] = sandbox_record(sandbox)
    report = NativeHPCVerificationReportV1.create(**fields)
    sys.stdout.write(report.model_dump_json() + "\n")
    # A scientifically wrong candidate is a successfully completed verifier
    # execution whose typed report says ``fail``.  Non-zero process status is
    # reserved for verifier/substrate failure so infrastructure accounting
    # never conflates the two.
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
