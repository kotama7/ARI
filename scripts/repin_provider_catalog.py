#!/usr/bin/env python3
"""Re-pin (or verify) the source identities in the Capability Provider catalog.

The catalog loader verifies only ``manifest_sha256``; a package edit that
leaves the manifest untouched passes silently, and a manifest edit fails the
whole load with ``Provider manifest drift``. Both cases need the same fix, so
it lives in one place instead of being redone by hand.

Definitions, matching the comment at the top of the catalog:

  manifest_sha256  = "sha256:" + manifest_digest(load_skill_manifest(...))
  full_commit_sha  = the last commit that touched the package directory
  package_sha256   = canonical_digest({package-relative path: bytes_digest(blob)})
                     over every git-tracked file of the package at that commit

Usage:
  python scripts/repin_provider_catalog.py            # verify, exit 1 on drift
  python scripts/repin_provider_catalog.py --update   # rewrite the pins
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ari-core"))

from ari.protocols.integrity import bytes_digest, canonical_digest  # noqa: E402
from ari.skill_manifest import load_skill_manifest, manifest_digest  # noqa: E402

CATALOG = REPO / "ari-core" / "config" / "providers" / "catalog.yaml"


def _git(*argv: str, binary: bool = False):
    completed = subprocess.run(
        ["git", *argv], cwd=REPO, capture_output=True, check=True
    )
    return completed.stdout if binary else completed.stdout.decode().strip()


def package_pins(package: str) -> dict[str, str]:
    commit = _git("log", "-1", "--format=%H", "--", package)
    if not commit:
        raise SystemExit(f"no commit touches {package}")
    names = _git("ls-tree", "-r", "--name-only", f"{commit}:{package}").split()
    digests = {
        name: bytes_digest(_git("show", f"{commit}:{package}/{name}", binary=True))
        for name in names
    }
    return {
        "full_commit_sha": commit,
        "package_sha256": canonical_digest(digests),
        "manifest_sha256": "sha256:"
        + manifest_digest(load_skill_manifest(REPO / package / "skill.yaml")),
    }


def _entry_spans(text: str, packages: list[str]) -> dict[str, tuple[int, int]]:
    """Character span of each catalog entry, keyed by its package name.

    An entry starts at its own ``- provider_id:`` line and ends where the next
    one starts, so a rewrite cannot reach a sibling that happens to record the
    same digest.
    """

    starts = [match.start() for match in re.finditer(r"^  - provider_id:", text, re.M)]
    if len(starts) != len(packages):
        raise SystemExit("catalog entries could not be located for rewriting")
    bounds = starts + [len(text)]
    spans: dict[str, tuple[int, int]] = {}
    for index, package in enumerate(packages):
        block = text[bounds[index] : bounds[index + 1]]
        if f"package: {package}\n" not in block:
            raise SystemExit(f"catalog entry order does not match: {package}")
        spans[package] = (bounds[index], bounds[index + 1])
    return spans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="rewrite the pins")
    arguments = parser.parse_args()

    import yaml

    text = CATALOG.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    drifted = []
    # Rewrite inside each entry's own span. A whole-file replace looks right
    # until two packages happen to share a value -- which they do whenever one
    # commit touches both -- and then the first package's new commit is written
    # over every occurrence, the later packages never match their own recorded
    # value, and the pins oscillate forever between update and check.
    spans = _entry_spans(text, [str(item["package"]) for item in document["entries"]])
    edits: dict[str, str] = {}
    for entry in document["entries"]:
        package = str(entry["package"])
        observed = package_pins(package)
        recorded = {
            "full_commit_sha": str(entry["source"]["full_commit_sha"]),
            "package_sha256": str(entry["source"]["package_sha256"]),
            "manifest_sha256": str(entry["manifest_sha256"]),
        }
        block = edits.get(package, text[slice(*spans[package])])
        for field, value in observed.items():
            if recorded[field] == value:
                continue
            drifted.append(f"{package}: {field}")
            print(f"{package:18s} {field:16s} {recorded[field][:18]}… -> {value[:18]}…")
            block = block.replace(recorded[field], value)
        edits[package] = block
    for package, block in sorted(
        edits.items(), key=lambda item: spans[item[0]][0], reverse=True
    ):
        start, stop = spans[package]
        text = text[:start] + block + text[stop:]

    if not drifted:
        print("provider catalog pins match the tree")
        return 0
    if not arguments.update:
        print(f"\n{len(drifted)} pin(s) drifted; rerun with --update", file=sys.stderr)
        return 1
    CATALOG.write_text(text, encoding="utf-8")
    print(f"\nrewrote {len(drifted)} pin(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
