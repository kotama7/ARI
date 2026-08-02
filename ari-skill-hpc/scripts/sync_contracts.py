#!/usr/bin/env python3
"""Generate or verify the checked-in JSON Schemas for HPC v1 contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "ari-core"))

from ari_skill_hpc.contracts import (  # noqa: E402
    JobHandleV1,
    JobRequestV1,
    JobResultV1,
    JobStatusV1,
    JobSubmitArgumentsV1,
)
from ari_skill_hpc.execution_adapter import ExecutionHandoffV1  # noqa: E402


CONTRACTS = {
    "execution-handoff-v1.schema.json": ExecutionHandoffV1,
    "job-handle-v1.schema.json": JobHandleV1,
    "job-request-v1.schema.json": JobRequestV1,
    "job-result-v1.schema.json": JobResultV1,
    "job-status-v1.schema.json": JobStatusV1,
    "job-submit-arguments-v1.schema.json": JobSubmitArgumentsV1,
}


def rendered(model: type) -> str:
    return (
        json.dumps(
            model.model_json_schema(), ensure_ascii=False, sort_keys=True, indent=2
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
        print("stale HPC schemas: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("HPC contracts are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
