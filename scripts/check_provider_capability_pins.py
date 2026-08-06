#!/usr/bin/env python3
"""Report verified Provider locks that pin a Capability contract ARI no longer has.

A ``verified-lock-v1.json`` records the exact contract a Provider was promoted
against. That binding is the point: change the contract and the promotion no
longer describes what was verified, so the lock must be re-promoted. The
invalidation is the system working -- what was missing is anyone noticing it.

Nothing compared these pins to the live ontology, so a bundle could go stale and
keep looking promoted. This walks every bundle and says which ones no longer
match, and against which capability.

Usage:
  python scripts/check_provider_capability_pins.py           # report, exit 0
  python scripts/check_provider_capability_pins.py --strict  # exit 1 on any stale pin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ari-core"))

from ari.capability_binding.ontology import load_capability_ontology  # noqa: E402

ONTOLOGY = REPO / "ari-core" / "config" / "capabilities" / "ontology.yaml"
BUNDLES = REPO / "ari-skill-tool-registry" / "providers"
_REF = re.compile(r'"capability_ref":\s*"(ari\.[^"]+)"')
_DIGEST = re.compile(r'"capability_contract_digest":\s*"(sha256:[0-9a-f]{64})"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when any pin is stale"
    )
    arguments = parser.parse_args()

    if not BUNDLES.is_dir():
        print("no Provider bundles present; nothing to check")
        return 0
    live = {
        item.capability_ref: item.contract_digest
        for item in load_capability_ontology(ONTOLOGY).snapshot.contracts
    }

    stale: list[str] = []
    unbound: list[str] = []
    checked = 0
    for lock in sorted(BUNDLES.glob("*/*/verified-lock-v1.json")):
        try:
            text = lock.read_text(encoding="utf-8")
            json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"unreadable: {lock.relative_to(REPO)}: {exc}")
            stale.append(str(lock))
            continue
        pinned = set(_DIGEST.findall(text))
        bundle = lock.parent.relative_to(BUNDLES)
        for ref in sorted(set(_REF.findall(text))):
            if ref not in live:
                continue
            checked += 1
            if live[ref] in pinned:
                continue
            if not pinned:
                # Worse than a mismatch: this lock names a capability and never
                # bound its contract, so it cannot go stale -- it never
                # committed to anything.
                unbound.append(f"{bundle} -> {ref}")
                print(f"unbound   {bundle}")
                print(f"          {ref}: lock records no capability_contract_digest")
                continue
            # Deliberately not called "stale". A mismatch is one of two very
            # different things and this cannot tell them apart without history:
            # the contract moved after a real binding (re-promote), or the lock
            # pins a digest built by a different rule and was never bound to the
            # ontology at all (a promotion script computing its own synthetic
            # value over {capability_ref, semantic} produces exactly this, and
            # such a lock can never match and never detect the contract moving).
            # Calling both "stale" would assert a history that was not checked.
            stale.append(f"{bundle} -> {ref}")
            print(f"mismatch  {bundle}")
            print(f"          {ref}")
            print(f"          ontology now {live[ref][:23]}…; not among the {len(pinned)} pinned")

    if not stale and not unbound:
        print(f"all {checked} Provider capability pin(s) match the ontology")
        return 0
    print()
    if stale:
        print(
            f"{len(stale)} mismatched of {checked}: the pinned digest is not the "
            "ontology's. Either the contract moved after a real binding, in which "
            "case re-promote against the current one; or the lock pins a digest "
            "built by a different rule and was never bound to the ontology, in "
            "which case re-promoting changes nothing and the promotion script is "
            "what needs fixing. Compare the pinned value against the ontology's "
            "own construction before assuming which."
        )
    if unbound:
        print(
            f"{len(unbound)} unbound of {checked}: the lock claims a capability "
            "and never recorded which contract it was verified against, so "
            "nothing can detect the contract moving underneath it."
        )
    return 1 if arguments.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
