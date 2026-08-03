#!/usr/bin/env python3
"""Generate the reviewed tool-registry JSON Schemas from canonical models.

The default mode is a drift check.  ``--write`` is an operator action used
after a contract change; generated files are committed with the model change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
for dependency in (PACKAGE_ROOT.parent / "ari-core", SRC):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from admission import AdmissionPolicyV1  # noqa: E402
from models import (  # noqa: E402
    AdmissionDecisionV1,
    CanonicalToolDescriptorV1,
    CatalogIndexV1,
    CatalogLockV1,
    InvocationCassetteV1,
    RegistryHandleV1,
)
from sources import SourcesDocumentV1  # noqa: E402


ModelType: TypeAlias = type[BaseModel]
CONTRACTS: tuple[tuple[str, str, ModelType], ...] = (
    ("catalog-lock-v1.schema.json", "ARI Catalog Lock v1", CatalogLockV1),
    ("catalog-index-v1.schema.json", "ARI Catalog Index v1", CatalogIndexV1),
    (
        "tool-descriptor-v1.schema.json",
        "ARI Canonical Tool Descriptor v1",
        CanonicalToolDescriptorV1,
    ),
    (
        "admission-decision-v1.schema.json",
        "ARI Admission Decision v1",
        AdmissionDecisionV1,
    ),
    (
        "admission-policy-v1.schema.json",
        "ARI Admission Policy v1",
        AdmissionPolicyV1,
    ),
    ("registry-handle-v1.schema.json", "ARI Registry Handle v1", RegistryHandleV1),
    ("tool-cassette-v1.schema.json", "ARI Tool Cassette v1", InvocationCassetteV1),
    ("catalog-sources-v1.schema.json", "ARI Catalog Sources v1", SourcesDocumentV1),
)


def _document(filename: str, title: str, model: ModelType) -> dict:
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ari.dev/schemas/tool-registry/{filename}"
    schema["title"] = title
    return schema


def expected_outputs() -> dict[Path, str]:
    schema_root = PACKAGE_ROOT / "schemas"
    return {
        schema_root / filename: json.dumps(
            _document(filename, title, model),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
        for filename, title, model in CONTRACTS
    }


def sync(*, write: bool) -> list[Path]:
    drift: list[Path] = []
    for path, expected in expected_outputs().items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        drift.append(path)
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite generated registry JSON Schemas",
    )
    args = parser.parse_args(argv)
    drift = sync(write=args.write)
    if not drift:
        print("tool-registry contracts are up to date")
        return 0
    action = "updated" if args.write else "out of date"
    for path in drift:
        print(f"{action}: {path.relative_to(PACKAGE_ROOT)}")
    return 0 if args.write else 1


if __name__ == "__main__":
    raise SystemExit(main())
