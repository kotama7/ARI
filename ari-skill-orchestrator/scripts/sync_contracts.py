#!/usr/bin/env python3
"""Generate or verify checked-in orchestrator JSON Schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ari_skill_orchestrator.contracts import (  # noqa: E402
    ArtifactRefV1,
    PrincipalV1,
    RunHandleV1,
    RunRequestV1,
    RunResultV1,
    RunStatusV1,
)


CONTRACTS = {
    "artifact-ref-v1.schema.json": ArtifactRefV1,
    "principal-v1.schema.json": PrincipalV1,
    "run-handle-v1.schema.json": RunHandleV1,
    "run-request-v1.schema.json": RunRequestV1,
    "run-result-v1.schema.json": RunResultV1,
    "run-status-v1.schema.json": RunStatusV1,
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
        print("stale orchestrator schemas: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("orchestrator contracts are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
