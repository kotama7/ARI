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
    # THE MANIFESTS, which this scanned past. A manifest carries the same field,
    # and it is the one that actually broke: both native Harnesses shipped a
    # ``source_full_commit_sha`` naming a commit made in a detached ceremony
    # worktree, which was HEAD while the registration gate looked at it and was
    # never reachable from the branch afterwards. The gate could only catch it on
    # the next re-registration; nothing standing caught it at all.
    for path in sorted(HARNESS_ROOT.glob("builtin/*.yaml")):
        body = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sha = str(body.get("source_full_commit_sha", ""))
        if sha:
            found.append((f"{path.name}:source_full_commit_sha", sha))
    for path in sorted(HARNESS_ROOT.glob("evidence/*/registration_evidence.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        sha = str(body.get("source_full_commit_sha", ""))
        if sha:
            found.append((f"{path.parent.name}:source_full_commit_sha", sha))
    for path in sorted(HARNESS_ROOT.glob("evidence/*/measurement_environment.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        sha = str(body.get("registration_commit", ""))
        if sha:
            found.append((f"{path.parent.name}:registration_commit", sha))
    return found


PINS = _pinned_commits()


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
