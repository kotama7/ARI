"""Operator-only catalog synchronization; runtime never imports this command."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from admission import AdmissionPolicyV1
from catalog import (
    CATALOG_INDEX_FILENAME,
    CATALOG_LOCK_FILENAME,
    build_catalog,
    write_reviewable_catalog,
)
from sources import StdioCatalogSource, load_source_specs


async def _sync(args: argparse.Namespace) -> dict:
    specs = load_source_specs(args.sources)
    sources = [StdioCatalogSource(spec) for spec in specs]
    policy = (
        AdmissionPolicyV1.model_validate_json(
            Path(args.policy).read_text(encoding="utf-8")
        )
        if args.policy
        else AdmissionPolicyV1()
    )
    result = await build_catalog(
        sources,
        policy=policy,
        max_origin_depth=args.max_origin_depth,
    )
    return write_reviewable_catalog(
        lock_path=args.lock,
        index_path=args.index,
        result=result,
        approve=args.approve,
    )


def main(argv: list[str] | None = None) -> int:
    package_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default=str(package_root / "sources.yaml"))
    parser.add_argument("--policy", default="")
    parser.add_argument("--lock", default=str(package_root / CATALOG_LOCK_FILENAME))
    parser.add_argument("--index", default=str(package_root / CATALOG_INDEX_FILENAME))
    parser.add_argument("--max-origin-depth", type=int, default=16)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="replace the reviewed active lock; otherwise write *.pending + diff",
    )
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_sync(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 3 if report.get("status") == "pending-review" else 0


if __name__ == "__main__":
    raise SystemExit(main())
