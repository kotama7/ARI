"""`catalog_source_revision` is a version LABEL, and nothing bound it to a version.

WHY THIS FILE EXISTS. `snapshot_digest` is derived from the catalog's content, so
it moves whenever the catalog moves. `catalog_source_revision` is read verbatim
out of `catalog.yaml` (`ari/assurance/catalog.py`, the `raw.get` at the bottom of
`load_harness_catalog`) and is compared against nothing, so it moves only when a
human retypes it. The two are written side by side into every snapshot, which
reads as if the label named the content. It did not.

What that permitted, measured on this tree: `config/harnesses/catalog.yaml` and
the retained `evidence/production_e2e/harness_catalog_snapshot.json` both declare
`ari-harness-catalog/1@d303a4ca…`, and they are not the same catalog. One entry
was added, and every one of the four entries they share had its manifest,
registration report, registration evidence and promotion approval digest replaced
underneath the label. Twelve commits touched `catalog.yaml` without the label
changing once. A run pinned to that revision cannot say which of those catalogs
it was judged against.

WHAT THIS FILE DOES NOT ASSERT. Not "the live catalog must equal the retained
snapshot". The retained snapshot is the frozen record of a past run and is
SUPPOSED to describe the catalog as it was then; a guard that fired merely
because the catalog moved on would have to be suppressed the first time someone
legitimately registered a harness. Every guard here is satisfied by bumping
`catalog_source_revision` — by naming the new catalog — which is the correct act
rather than a suppression.

SHAPE. The revision embeds a git commit sha of the source tree it was cut from
(`scripts/rqgm_assurance/promote_native_harnesses.py` mints it as
``f"ari-harness-catalog/1@{source_commit}"``). No function of `catalog.yaml` can
recompute a commit sha, so `load_harness_catalog` could only ever check the
STRING'S SHAPE, never its correspondence to the content. Correspondence has to be
recorded by whoever cuts the revision. That is what the pin below is: updating it
is the deliberate act of recording a new catalog version.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ari.assurance.catalog import load_harness_catalog
from ari.assurance.models import HarnessCatalogSnapshotV1

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPOSITORY / "ari-core" / "config"
HARNESS_ROOT = CONFIG_ROOT / "harnesses"
LIVE_CATALOG = HARNESS_ROOT / "catalog.yaml"

# THE PIN. The revision the catalog declares, and the content that revision names.
#
# To change the catalog: change it, bump `catalog_source_revision` in
# `config/harnesses/catalog.yaml` to name the new catalog, then record the new
# pairing here. Editing only this pair to make the test green re-uses one label
# for two catalogs, which is the defect this file exists to catch.
PINNED_REVISION = "ari-harness-catalog/1@7be41f8059c8655d518d6cfc8f858a7368e83856"
PINNED_SNAPSHOT_DIGEST = (
    "sha256:53d4bf365b32a5f63d486027be27b62469b823cdff78c07880533fa67ad6643f"
)


def _declared_pairing(catalog_path: Path) -> tuple[str, str]:
    """What a catalog claims to be, and what it actually is."""

    snapshot = load_harness_catalog(catalog_path)
    return snapshot.catalog_source_revision, snapshot.snapshot_digest


def _check_revision_pin(
    catalog_path: Path, *, revision: str, snapshot_digest: str
) -> None:
    """Raise unless the catalog is still the content its revision was pinned to.

    Split by which half moved, because the three cases need three different
    actions and a bare inequality would not say which one.
    """

    actual_revision, actual_digest = _declared_pairing(catalog_path)
    if (actual_revision, actual_digest) == (revision, snapshot_digest):
        return
    if actual_revision == revision and actual_digest != snapshot_digest:
        raise AssertionError(
            f"the harness catalog content changed but catalog_source_revision did "
            f"not: revision {actual_revision!r} named {snapshot_digest} when it was "
            f"pinned and names {actual_digest} now. One revision string cannot name "
            f"two catalogs — a run pinned to it could not say which one judged it. "
            f"Bump catalog_source_revision in config/harnesses/catalog.yaml to name "
            f"the new catalog, then record the new pairing in {Path(__file__).name}."
        )
    if actual_revision != revision and actual_digest == snapshot_digest:
        raise AssertionError(
            f"catalog_source_revision moved to {actual_revision!r} but the harness "
            f"catalog content did not change ({actual_digest}). A revision that "
            f"names nothing new makes the label stop tracking anything. Either "
            f"restore {revision!r} or record the new pairing in "
            f"{Path(__file__).name} deliberately."
        )
    raise AssertionError(
        f"the harness catalog moved to {actual_revision!r} / {actual_digest}, "
        f"pinned at {revision!r} / {snapshot_digest}. If that bump was the "
        f"deliberate act of registering a new catalog, record the new pairing in "
        f"{Path(__file__).name}."
    )


def _harness_tree_copy(tmp_path: Path) -> Path:
    """A whole scratch copy: the cross-checks read files beside the catalog."""

    destination = tmp_path / "harnesses"
    shutil.copytree(HARNESS_ROOT, destination)
    return destination


def _rewrite_catalog(catalog_path: Path, mutate) -> None:
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    mutate(raw)
    catalog_path.write_text(
        yaml.safe_dump(raw, sort_keys=False), encoding="utf-8"
    )


# --- the pin ----------------------------------------------------------------

def test_the_declared_revision_still_names_the_content_it_was_pinned_to() -> None:
    """The shipped catalog is the catalog its revision string was recorded for."""

    _check_revision_pin(
        LIVE_CATALOG,
        revision=PINNED_REVISION,
        snapshot_digest=PINNED_SNAPSHOT_DIGEST,
    )


def test_the_pin_fires_when_an_entry_is_added_without_a_revision_bump(
    tmp_path: Path,
) -> None:
    """The exact event that went unnoticed, replayed on a scratch tree.

    Start from the catalog WITHOUT `hpc/gemm-dense-fp64-problem-correctness`,
    pin that pairing, then add the entry back and leave `catalog_source_revision`
    alone — which is what actually happened here. The good case has to pass in
    the same test, or this proves only that the guard is noisy.
    """

    tree = _harness_tree_copy(tmp_path)
    catalog_path = tree / "catalog.yaml"
    added = "hpc/gemm-dense-fp64-problem-correctness"
    _rewrite_catalog(
        catalog_path,
        lambda raw: raw.__setitem__(
            "entries",
            [item for item in raw["entries"] if item["id"] != added],
        ),
    )
    revision, four_entry_digest = _declared_pairing(catalog_path)
    assert revision == PINNED_REVISION
    assert four_entry_digest != PINNED_SNAPSHOT_DIGEST

    # good case: unchanged catalog, pin holds
    _check_revision_pin(
        catalog_path, revision=revision, snapshot_digest=four_entry_digest
    )

    # failing case: the entry comes back, the revision does not move
    shutil.copyfile(LIVE_CATALOG, catalog_path)
    assert _declared_pairing(catalog_path)[0] == revision, (
        "the replay must change only the content, or it tests the wrong thing"
    )
    with pytest.raises(AssertionError, match="content changed but"):
        _check_revision_pin(
            catalog_path, revision=revision, snapshot_digest=four_entry_digest
        )


def test_the_pin_covers_the_whole_snapshot_and_not_only_the_entry_list(
    tmp_path: Path,
) -> None:
    """`driver_protocol_version` is inside the snapshot payload and has no
    cross-check of its own, so it could move under a frozen revision too."""

    tree = _harness_tree_copy(tmp_path)
    catalog_path = tree / "catalog.yaml"
    _rewrite_catalog(
        catalog_path,
        lambda raw: raw.__setitem__("driver_protocol_version", "ari.harness-driver/v2"),
    )
    with pytest.raises(AssertionError, match="content changed but"):
        _check_revision_pin(
            catalog_path,
            revision=PINNED_REVISION,
            snapshot_digest=PINNED_SNAPSHOT_DIGEST,
        )


# --- one revision string, one catalog ---------------------------------------

def _recorded_catalogs() -> dict[str, dict[str, str]]:
    """Every (revision -> content) pairing written down anywhere under config/.

    The live catalog and every retained snapshot are read the same way, because
    the claim is about the label, not about which file carries it.
    """

    revision, digest = _declared_pairing(LIVE_CATALOG)
    recorded: dict[str, dict[str, str]] = {
        revision: {str(LIVE_CATALOG.relative_to(REPOSITORY)): digest}
    }
    for path in sorted(CONFIG_ROOT.rglob("harness_catalog_snapshot.json")):
        snapshot = HarnessCatalogSnapshotV1.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        recorded.setdefault(snapshot.catalog_source_revision, {})[
            str(path.relative_to(REPOSITORY))
        ] = snapshot.snapshot_digest
    return recorded


def test_a_revision_string_never_names_two_different_catalogs() -> None:
    """A label reused for two contents identifies neither.

    This is NOT "the catalog may not move". A retained snapshot is allowed to
    describe an older catalog forever — that is what it is for. What is not
    allowed is for the older catalog and the newer one to answer to the same
    name, because then a run that pinned the name cannot say which set of
    harnesses judged it. The catalog is the mutable side, so bumping
    `catalog_source_revision` always resolves this.
    """

    collisions = {
        revision: sources
        for revision, sources in _recorded_catalogs().items()
        if len(set(sources.values())) > 1
    }
    assert not collisions, "\n".join(
        [
            "one catalog_source_revision names more than one catalog:",
            *(
                f"  {revision}"
                + "".join(f"\n    {digest}  {source}" for source, digest in sorted(sources.items()))
                for revision, sources in sorted(collisions.items())
            ),
            "",
            "Bump catalog_source_revision in config/harnesses/catalog.yaml so the "
            "current catalog stops answering to a name an earlier one already has.",
        ]
    )


# --- what the snapshot's self-pins actually reach ---------------------------

def test_the_snapshot_self_pins_bind_the_record_and_not_the_tree(
    tmp_path: Path,
) -> None:
    """The property `config/README.md` states about the retained snapshot.

    The self-pins are over the snapshot's OWN bytes: the embedded manifest
    copies each carry `manifest_digest` and the file carries `snapshot_digest`,
    so the record cannot be rewritten in place. They do not reach the manifests
    on disk — the snapshot is a copy, and it keeps validating after those move.
    Editing a live manifest is caught by `load_harness_catalog` reading the tree
    instead, which is a different check in a different place.
    """

    tree = _harness_tree_copy(tmp_path)
    manifest_path = tree / "builtin" / "hpc_gemm_correctness.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["description"] = manifest["description"] + " (edited)"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    # the retained record still validates: it is a copy, not a view
    snapshot_path = (
        tree / "evidence" / "production_e2e" / "harness_catalog_snapshot.json"
    )
    HarnessCatalogSnapshotV1.model_validate_json(
        snapshot_path.read_text(encoding="utf-8")
    )

    # the tree is where the edit is caught
    with pytest.raises(ValueError, match="Harness manifest digest mismatch"):
        load_harness_catalog(tree / "catalog.yaml")
