#!/usr/bin/env python3
"""Refuse a commit that leaves the shipped Harness catalog unable to load.

WHY THIS IS A SEPARATE SURFACE FROM THE PIN GATE. They answer two questions and
the answers have two different repairs. "Does this manifest pin the code it is
measured by" is repaired by re-pinning, and ``repin_and_promote_harness.py``
both asks it and performs the repair. "Do the artifacts BESIDE this manifest
still describe it" is repaired ONLY by re-earning them -- running the harness's
controls again and signing the result -- and no amount of re-pinning helps.

It is also a separate FILE, deliberately. That surface is held to naming no path
inside ``config/harnesses/evidence``, ``approvals``, ``reports`` or the catalog,
on the principle that it cannot write a bundle it cannot name, and a test
enforces it by scanning the module's string constants. Putting this check there
would have required naming all four. So the check that must read the published
bytes lives apart from the surface that must not.

WHAT IT ASKS, AND WHY IT ASKS RATHER THAN CHECKS. The obvious implementation is
to compare each manifest's ``manifest_digest`` against the back-references in
the report and evidence beside it. That is three of the comparisons
``load_harness_catalog`` already makes -- it also checks each artifact's own
digest, its harness id, the approval, and the digest the catalog row advertises
-- so writing those three would be a subset standing in for a definition that
already exists, and would go quiet the first time a fourth cross-check was
added. The property wanted here IS "the catalog loads", so that is what is
asked.

MEASURED, on the day this was written: a manifest moved without its evidence
being re-earned THREE times, by three different actors, and each time the
tooling refused only afterwards -- ``promote`` on the far side, or
``load_harness_catalog`` for whoever pulled next. Every one of them committed
cleanly. The failure surfaced in someone else's working tree.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
if str(ARI_CORE) not in sys.path:
    sys.path.insert(0, str(ARI_CORE))


def shipped_catalog() -> Path:
    """The catalog this repository ships, located rather than configured."""
    return ARI_CORE / "config" / "harnesses" / "catalog.yaml"


def catalog_load_failure(path: Path) -> str | None:
    """Why the catalog will not load, or ``None`` if it does.

    Returns the message rather than raising: the caller is a gate that has to
    print it, and the harness that failed is named in it.
    """
    if not path.is_file():
        # NOT A FAILURE. A tree with no catalog has nothing to contradict, and
        # refusing here would block every commit in a checkout that does not
        # ship one. The absence is reported by the caller, not judged here.
        return None
    try:
        from ari.assurance.catalog import load_harness_catalog

        load_harness_catalog(path)
    except Exception as exc:  # the loader raises ValueError, but an artifact
        return f"{type(exc).__name__}: {exc}"  # that will not parse can raise anything
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=None,
                        help="the catalog to load; defaults to the shipped one")
    args = parser.parse_args(argv)

    path = args.catalog or shipped_catalog()
    if not path.is_file():
        print(f"no catalog at {path.relative_to(REPO_ROOT)}; nothing to check")
        return 0
    failure = catalog_load_failure(path)
    if failure is None:
        print("the shipped catalog loads")
        return 0
    print(f"the shipped catalog will not load -- {failure}")
    print("")
    print("  A bundle has stopped describing the manifest beside it. This is NOT")
    print("  repaired by re-pinning: the evidence and the signature over it have")
    print("  to be RE-EARNED by running that harness's controls again.")
    return 1


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
