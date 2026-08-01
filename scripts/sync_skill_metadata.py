#!/usr/bin/env python3
"""Generate compatibility metadata from canonical ``skill.yaml`` files.

The canonical manifests are reviewed source.  ``mcp.json`` and the published
JSON Schema are deterministic derived artifacts.  Run with ``--write`` after a
manifest/model change; CI uses the default ``--check`` mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))

from ari.skill_manifest import (  # noqa: E402
    SkillManifestV1,
    legacy_mcp_document,
    load_skill_manifest,
)


SCHEMA_PATH = ARI_CORE / "ari" / "schemas" / "skill_manifest_v1.schema.json"


def _json_text(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def schema_document() -> dict:
    schema = SkillManifestV1.model_json_schema()
    schema["$id"] = "https://ari.dev/schemas/skill-manifest-v1.schema.json"
    schema["title"] = "ARI Skill Manifest v1"
    return schema


def expected_outputs(repo_root: Path = REPO_ROOT) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for manifest_path in sorted(repo_root.glob("ari-skill-*/skill.yaml")):
        manifest = load_skill_manifest(manifest_path)
        outputs[manifest_path.parent / "mcp.json"] = _json_text(
            legacy_mcp_document(manifest)
        )
    schema_path = repo_root / "ari-core" / "ari" / "schemas" / SCHEMA_PATH.name
    outputs[schema_path] = _json_text(schema_document())
    return outputs


def sync(*, write: bool, repo_root: Path = REPO_ROOT) -> list[Path]:
    drift: list[Path] = []
    for path, expected in expected_outputs(repo_root).items():
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
        help="rewrite generated mcp.json files and the JSON Schema",
    )
    args = parser.parse_args(argv)
    drift = sync(write=args.write)
    if not drift:
        print("skill metadata is up to date")
        return 0
    action = "updated" if args.write else "out of date"
    for path in drift:
        print(f"{action}: {path.relative_to(REPO_ROOT)}")
    return 0 if args.write else 1


if __name__ == "__main__":
    raise SystemExit(main())
