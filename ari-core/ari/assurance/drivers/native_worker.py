"""Hidden-case native HPC verifier worker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ari.assurance.native_hpc import (  # noqa: E402
    registered_native_families, verify_native_hpc)


def _candidate(kind: str, library: str, timeout: float):
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
    report = verify_native_hpc(
        args.kind,
        _candidate(args.kind, args.library, args.case_timeout),
        tier=args.tier,
        seed=args.seed,
    )
    sys.stdout.write(report.model_dump_json() + "\n")
    # A scientifically wrong candidate is a successfully completed verifier
    # execution whose typed report says ``fail``.  Non-zero process status is
    # reserved for verifier/substrate failure so infrastructure accounting
    # never conflates the two.
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
