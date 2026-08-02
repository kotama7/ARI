#!/usr/bin/env python3
"""Generate or verify checked-in reproduction and grading JSON Schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "ari-core"))

from contracts import (  # noqa: E402
    GradeReportV1,
    ReproductionArtifactV1,
    ReproductionAttemptV1,
    ReproductionPlanV1,
    ReproductionRunV1,
)


CONTRACTS = {
    "grade-report-v1.schema.json": GradeReportV1,
    "reproduction-artifact-v1.schema.json": ReproductionArtifactV1,
    "reproduction-attempt-v1.schema.json": ReproductionAttemptV1,
    "reproduction-plan-v1.schema.json": ReproductionPlanV1,
    "reproduction-run-v1.schema.json": ReproductionRunV1,
}


def rendered(model: type) -> str:
    return (
        json.dumps(
            model.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    schema_dir = ROOT / "schemas"
    if arguments.write:
        schema_dir.mkdir(exist_ok=True)
    stale: list[str] = []
    for filename, model in CONTRACTS.items():
        path = schema_dir / filename
        expected = rendered(model)
        if arguments.write:
            path.write_text(expected, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != expected:
            stale.append(filename)
    if stale:
        print("stale paper-re schemas: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("paper-re contracts are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
