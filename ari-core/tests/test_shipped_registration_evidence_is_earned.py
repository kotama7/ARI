"""The bundles this repository SHIPS, asked whether their claims re-derive.

WHAT IS ALREADY COVERED, AND WHY IT WAS NOT ENOUGH. Several suites hold the
promotion SURFACES to deriving their evidence rather than declaring it --
``test_harness_repin_surface``, ``test_native_promotion_surface``, the two
control-sequence suites. All of them test the code that writes a bundle. None of
them looks at a bundle.

That gap is not hypothetical, it is the defect the surfaces were fixed for.
``hpc/gemm-performance`` shipped ``status: verified`` with seven values typed as
LITERALS and ``attestation_digests`` pointing at its own registration report --
the evidence citing itself as the execution it never performed. A correct
surface does not repair a stale bundle: the bytes on disk keep their claims
until something re-earns them, and until this file nothing read those bytes back.

So these walk ``config/harnesses/catalog.yaml`` and ask, of every row:

* is every cited attestation a FILE beside the bundle, and every file cited;
* is the registration report among the citations -- the self-citation that made
  a report of nothing look like a record of five runs;
* does ``run_count`` count those runs;
* do ``clean_control_verdict`` and ``negative_control_verdict`` READ BACK off
  the attestations labelled clean and negative?

The last is the one a literal cannot survive. A hand-typed "pass" beside runs
that failed is exactly what the field was invented to prevent and exactly what
it recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

HARNESS_ROOT = Path(__file__).resolve().parents[1] / "config" / "harnesses"
CATALOG = HARNESS_ROOT / "catalog.yaml"


def _rows():
    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    return [(entry["id"], entry) for entry in document["entries"]]


def _bundle(entry) -> Path:
    return (HARNESS_ROOT / entry["registration_evidence"]).parent


def _attestations(entry) -> dict[str, dict]:
    return {path.name.replace(".attestation.json", ""):
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(_bundle(entry).glob("*.attestation.json"))}


def _evidence(entry) -> dict:
    return json.loads((HARNESS_ROOT / entry["registration_evidence"])
                      .read_text(encoding="utf-8"))


IDS = [row[0] for row in _rows()]
ENTRIES = [row[1] for row in _rows()]


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_every_cited_attestation_is_a_run_shipped_beside_the_bundle(entry) -> None:
    """A digest is not a run. These have to be the same set, both ways.

    Cited-but-absent is a claim about an execution nobody can read; present-but-
    uncited is a run the evidence does not stand on, which is the shape a
    cherry-picked bundle would have.
    """
    evidence = _evidence(entry)
    attestations = _attestations(entry)
    assert attestations, (
        f"{entry['id']} ships no attestation at all; its registration evidence "
        f"describes executions that are not in the tree")
    cited = set(evidence["attestation_digests"])
    present = {item["attestation_digest"] for item in attestations.values()}
    assert cited == present, (
        f"{entry['id']}: cited {sorted(cited - present)} are not beside the "
        f"bundle, and {sorted(present - cited)} are beside it uncited")


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_registration_report_is_not_cited_as_one_of_the_runs(entry) -> None:
    """THE DEFECT, exactly. attestation_digests held one entry and it was the
    digest of the report that field appears in -- a bundle citing itself as the
    execution it had not performed, which reads as evidence and is a loop."""
    evidence = _evidence(entry)
    report = json.loads((HARNESS_ROOT / entry["registration_report"])
                        .read_text(encoding="utf-8"))
    assert report["report_digest"] not in set(evidence["attestation_digests"]), (
        f"{entry['id']} cites its own registration report as an execution")


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_run_count_counts_the_runs(entry) -> None:
    evidence = _evidence(entry)
    attestations = _attestations(entry)
    assert evidence["run_count"] == len(attestations), (
        f"{entry['id']} declares run_count={evidence['run_count']} and ships "
        f"{len(attestations)} attestations")


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_control_verdicts_read_back_off_the_runs(entry) -> None:
    """The two fields a literal survives longest in, re-derived from the runs.

    Labels carry the roles: a control sequence names each execution for what it
    is, and the name is how a reader tells the clean control from the negative
    one without re-running the container. A bundle whose runs cannot be sorted
    into the two roles cannot support either claim, which is itself the finding.
    """
    evidence = _evidence(entry)
    attestations = _attestations(entry)
    clean = {k: v for k, v in attestations.items() if k.startswith("clean")}
    negative = {k: v for k, v in attestations.items() if k.startswith("negative")}
    assert clean and negative, (
        f"{entry['id']} ships {sorted(attestations)}; without a clean and a "
        f"negative control its two control verdicts describe nothing")

    clean_verdicts = {item["verdict"] for item in clean.values()}
    assert clean_verdicts == {evidence["clean_control_verdict"]}, (
        f"{entry['id']} declares clean_control_verdict="
        f"{evidence['clean_control_verdict']!r} and its clean runs "
        f"{sorted(clean)} read {sorted(clean_verdicts)}")

    negative_verdicts = {item["verdict"] for item in negative.values()}
    assert negative_verdicts == {evidence["negative_control_verdict"]}, (
        f"{entry['id']} declares negative_control_verdict="
        f"{evidence['negative_control_verdict']!r} and its negative runs "
        f"{sorted(negative)} read {sorted(negative_verdicts)}")


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_bundle_keeps_the_record_its_claims_were_derived_from(entry) -> None:
    """Derived once is not the same as derivable now.

    Both promotion surfaces write the intermediate they read the declared values
    out of -- ``control_sequence.json`` for the families that run a sequence,
    ``control_derivation.json`` for the native one. Shipping it is what lets a
    reader repeat the derivation instead of trusting that it happened.
    """
    bundle = _bundle(entry)
    records = [name for name in ("control_sequence.json", "control_derivation.json")
               if (bundle / name).is_file()]
    assert records, (
        f"{entry['id']} ships attestations and declared values but no record of "
        f"how the second was read off the first")


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_bundle_describes_the_manifest_it_ships_beside(entry) -> None:
    """Coherent is not the same as CURRENT, and the checks above are only the first.

    Every assertion before this one is satisfied by a bundle that was earned
    honestly and then left behind: re-pinning moves manifest_digest, and the
    evidence, report and approval that named the old one keep citing real runs
    of real controls with verdicts that still re-derive. Measured on this tree
    while a re-pin was in flight: all twenty-five checks above passed while
    ``load_harness_catalog`` refused the catalog outright.

    That refusal is a gate and it fires, but it says "registration report
    differs" -- true, and it does not say which of the three moved or why. This
    one names it: the signature is over a manifest that is no longer the one
    shipping beside it, so the bundle has to be re-earned rather than re-pointed.
    """
    manifest = yaml.safe_load(
        (HARNESS_ROOT / entry["manifest"]).read_text(encoding="utf-8"))
    evidence = _evidence(entry)
    approval = json.loads((HARNESS_ROOT / entry["promotion_approval"])
                          .read_text(encoding="utf-8"))
    report = json.loads((HARNESS_ROOT / entry["registration_report"])
                        .read_text(encoding="utf-8"))
    digest = manifest["manifest_digest"]
    assert evidence["manifest_digest"] == digest, (
        f"{entry['id']}: the evidence describes manifest "
        f"{evidence['manifest_digest'][:22]} and the manifest beside it is "
        f"{digest[:22]}; a re-pin moved the digest and the bundle was not re-earned")
    assert approval["harness_manifest_digest"] == digest, (
        f"{entry['id']}: the SIGNATURE is over manifest "
        f"{approval['harness_manifest_digest'][:22]}, not over {digest[:22]}")
    assert approval["registration_report_digest"] == report["report_digest"], (
        f"{entry['id']}: the signature names a registration report that is not "
        f"the one shipped")
