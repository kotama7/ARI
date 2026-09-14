#!/usr/bin/env python3
"""Offline pre-v1 ``science_data.json`` to ``ScienceDataV1`` converter.

This command is intentionally absent from every MCP manifest.  It is a
checkpoint maintenance operation, not a fallback used by live runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ari-core"))

from ari.public.science_data import migrate_legacy_science_data  # noqa: E402


def migrate_file(
    source: Path,
    destination: Path,
    *,
    run_id: str,
    overwrite: bool = False,
) -> Path:
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if source == destination:
        raise ValueError("offline migration requires a distinct output path")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {destination}")
    value = json.loads(source.read_text(encoding="utf-8"))
    migrated = migrate_legacy_science_data(
        value,
        run_id=run_id,
        logical_name=source.name,
    )
    payload = (
        json.dumps(
            migrated.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    output = migrate_file(
        args.source,
        args.output,
        run_id=args.run_id,
        overwrite=args.force,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
