"""Every commit a shipped artifact cites, asked whether this branch still has it.

WHY THIS FILE EXISTS. Registration evidence pins ``source_full_commit_sha`` so a
reader can go and get the bytes that were measured. Nothing checked that the
commit is still there, and a history rewrite makes it not be: rewriting the
branch to drop three paths that carried machine identity moved every hash, and
the pins written the hour before named commits the new history does not contain.

MEASURED after that rewrite: the HEAD tree was byte-identical to the old one and
no object a push would carry held any machine identity -- both true, both
verified, and neither is the question a REFERENCE asks. The provenance pins were
orphaned and it took a separate commit to notice.

REACHABILITY, NOT EXISTENCE, and the difference is the whole check. The
pre-rewrite commits are still in this repository's object store: the reflog and
several checkpoint worktrees hold them, so ``git cat-file -t`` resolves every one
of them and a check written that way passes while the pins are broken for
everyone else. What a clone of the pushed branch can resolve is what is
REACHABLE from it, so that is what is asked here.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPOSITORY / "ari-core" / "config" / "harnesses"
CATALOG = HARNESS_ROOT / "catalog.yaml"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _in_a_git_checkout() -> bool:
    result = subprocess.run(["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"],
                            capture_output=True, timeout=60)
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _in_a_git_checkout(),
    reason="provenance pins can only be resolved inside a git checkout")


def _reachable(sha: str) -> bool:
    """Is this commit an ancestor of HEAD?

    Not ``cat-file``: an object can be present and unreachable, which is exactly
    the state a rewrite leaves behind locally and does not ship.
    """
    return subprocess.run(
        ["git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor", sha, "HEAD"],
        capture_output=True, timeout=120).returncode == 0


def _pinned_commits() -> list[tuple[str, str]]:
    """``(where it is written, the commit it names)`` for every provenance pin."""
    found: list[tuple[str, str]] = []
    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    revision = str(document.get("catalog_source_revision", ""))
    if "@" in revision:
        found.append(("catalog.yaml:catalog_source_revision",
                      revision.rsplit("@", 1)[1]))
    # DERIVED FROM THE ARTIFACTS, NOT LISTED. This named three fields and three
    # globs: catalog_source_revision, source_full_commit_sha in two places, and
    # registration_commit. It found what it was told to find, so a fourth
    # provenance field or a new artifact kind would have gone unnoticed -- the
    # same subset coverage this file exists to catch one layer up, in the file
    # that catches it.
    #
    # It walks every shipped artifact instead, and takes any key whose NAME says
    # it holds a commit. That derives the field set from what the artifacts
    # actually call things rather than from what someone remembered, and it
    # keeps the false-positive surface bounded: a 40-hex value under a key not
    # named for a commit is some other digest and is left alone. An earlier
    # sketch scanned every 40-hex string and would have flagged the sha1 of the
    # empty string in a package manifest as an orphaned commit.
    def _walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if ("commit" in str(key).lower() and isinstance(item, str)
                        and _SHA.match(item.strip())):
                    found.append((f"{where}:{key}", item.strip()))
                else:
                    _walk(item, where)
        elif isinstance(value, list):
            for item in value:
                _walk(item, where)

    for path in sorted(HARNESS_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            body = (json.loads(text) if path.suffix == ".json"
                    else yaml.safe_load(text))
        except (OSError, ValueError):
            continue
        _walk(body, path.relative_to(HARNESS_ROOT).as_posix())
    return found


def _live_paths() -> set[str]:
    """The artifacts the LIVE catalog points at, derived from the catalog.

    Not a list of directories. A catalog entry names its manifest, report,
    evidence and approval, so the live set is whatever those name -- and the
    evidence bundle's siblings come with it. Everything else under the harness
    root is a record of a past run, which the repository already distinguishes:
    test_harness_catalog_revision calls production_e2e "the frozen record of a
    past run" and it is not a catalog entry.
    """
    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    live = {"catalog.yaml"}
    for entry in document["entries"]:
        for key in ("manifest", "registration_report", "registration_evidence",
                    "promotion_approval"):
            value = entry.get(key)
            if not value:
                continue
            live.add(value)
            path = HARNESS_ROOT / value
            if key == "registration_evidence":
                for sibling in path.parent.rglob("*"):
                    if sibling.is_file():
                        live.add(sibling.relative_to(HARNESS_ROOT).as_posix())
    return live


LIVE = _live_paths()
ALL_PINS = _pinned_commits()
PINS = [(where, sha) for where, sha in ALL_PINS
        if where.rsplit(":", 1)[0] in LIVE]
RETAINED = [(where, sha) for where, sha in ALL_PINS
            if where.rsplit(":", 1)[0] not in LIVE]

#: Provenance pins in RETAINED records that this branch can no longer resolve,
#: and why. Recorded rather than skipped: a retained record describes a past run
#: and cannot be re-earned, so its pin is not a defect to fix -- but it is a
#: claim nobody can check, and it must not grow without someone noticing.
#:
#: 361a85d7 was a commit of this branch. Rewriting the history to drop three
#: paths that carried machine identity moved every hash; the reflog expiry and
#: `gc --prune=now` that followed removed the original. Its rewritten equivalent
#: is 97107af3, reachable, and identical in tree. The retained records cannot be
#: repointed at it: both are digest-bound over their own contents, so editing
#: the field would forge them, and four test modules read them.
#:
#: The purge was verified five ways -- orphaned blobs gone, 61 refs unchanged,
#: HEAD unchanged, every worktree valid, fsck silent -- and not one of those
#: asked whether a shipped artifact CITED a pruned commit.
KNOWN_UNRESOLVABLE = {"361a85d7fde8872f6f2299d31866915cc4333a89"}


def test_there_are_provenance_pins_to_check() -> None:
    """A test that silently checks nothing is the failure it is meant to catch."""
    assert PINS, "no shipped artifact pins a source commit; this file is inert"
    assert all(_SHA.match(sha) for _, sha in PINS), (
        f"a pin is not a full commit sha: "
        f"{[p for p in PINS if not _SHA.match(p[1])]}")


@pytest.mark.parametrize("where,sha", PINS, ids=[p[0] for p in PINS])
def test_the_commit_a_shipped_artifact_cites_is_reachable(where, sha) -> None:
    assert _reachable(sha), (
        f"{where} names {sha[:12]}, which is not an ancestor of HEAD. A clone of "
        f"this branch cannot resolve it, so the provenance claim cannot be "
        f"checked by anyone but this working copy -- the state a history rewrite "
        f"leaves behind. Re-earn the bundle at a commit this history has.")


def test_a_retained_record_cites_only_the_commits_already_known_lost() -> None:
    """Retained records are not re-earnable, so their pins are pinned instead.

    A record of a past run describes what was true then; after a history rewrite
    its commits may be gone, and re-running a production e2e to repair a
    provenance field is not a repair, it is a different run. So the unresolvable
    set is recorded and guarded rather than exempted: this fails if a retained
    record starts citing a commit that is not the one already known lost, which
    is what a second rewrite would do.
    """
    unresolvable = {sha for _, sha in RETAINED if not _reachable(sha)}
    assert unresolvable <= KNOWN_UNRESOLVABLE, (
        f"a retained record cites {sorted(unresolvable - KNOWN_UNRESOLVABLE)}, "
        f"which this branch cannot resolve and which is not the loss already "
        f"recorded here")


def test_the_live_and_retained_split_is_derived_from_the_catalog() -> None:
    """The split must come from what the catalog names, not from a directory list.

    An exemption written as a path prefix would grow silently: a second retained
    tree, or a live bundle moved beside one, would inherit the exemption without
    anyone deciding it should.
    """
    assert PINS, "no live provenance pin is being checked"
    assert RETAINED, (
        "nothing is classified as retained; if that is true the split is inert "
        "and the known-lost record above is describing nothing")
    assert not (set(PINS) & set(RETAINED))
