#!/usr/bin/env python3
"""Re-pin a registered Harness to the code it is measured by. Nothing else.

WHY THIS EXISTS. A manifest pins DERIVED values -- the driver's content digest,
the digest of the result schema ARI ships for the type that driver emits, and
its own manifest digest over both. Every one of them is computable from the
repository, and none of them was computed by anything that writes a manifest.
They were typed in. So an edit to instrument code silently invalidates the pin,
``driver.prepare()`` then refuses the harness with "driver bytes drifted", and
the harness is registered, signed, and unable to run.

Measured: this has happened three times in distinct episodes. The most recent
took two harnesses at once, because ``native_perf_common.py`` sits inside both
the performance driver's digest and the problem-correctness driver's.

WHY IT IS NOT ``promote_native_harnesses.py``. That script CONSTRUCTS the three
ARI-native manifests, which buys one real thing -- a typed-in driver pin is
impossible at the moment of writing -- and cannot do the job here: its
``_immutable_outputs`` refuses to overwrite any existing artifact whose bytes
differ, so it cannot move a pin that is already on disk. It does run that
family's control sequence, which this surface does not and never will, so it
remains where a native-family registration is EARNED.

WHAT IT WILL NOT DO.

* It re-pins DERIVED fields only. Everything a human decided -- the placement,
  the scope, the tiers, the policies, the container, the problem and case set --
  is read and never written. A tool that could move ``registered_placement``
  could relocate a harness's evidence to whatever machine was at hand, which is
  a change to what the harness asserts rather than a repair.
* IT WILL NOT WRITE REGISTRATION EVIDENCE, A PROMOTION APPROVAL OR A CATALOG
  ROW. It used to, and that is the defect this file now exists without.
  ``_write_promotion`` passed SEVEN ``HarnessRegistrationEvidenceV1`` fields as
  literals -- ``clean_control_verdict="pass"``, ``negative_control_verdict=
  "fail"``, ``official_runner_parity=True``, ``result_schema_conformant=True``,
  ``network_isolation="proved"``, ``target_write_isolation="proved"``,
  ``oracle_visibility="denied"`` -- and pointed ``attestation_digests`` at its
  own registration report, so the bundle cited itself as the execution it never
  performed. Both harnesses that ship no attestations were registered through
  it, and ``hpc/gemm-performance``'s bundle carries those seven values today.
  The ``promote`` mode remains only to say this and name where the evidence is
  earned instead; the module constructs neither evidence model at all, which is
  a property a test reads off the syntax tree rather than a habit.
* It refuses to run its gate report off the pinned placement. The performance
  harness pins an aarch64 node at a 48-thread budget; run this on anything else
  and it stops before measuring, rather than reporting a verdict that describes
  the wrong machine.
* Its gate report refuses a dirty working tree, for the reason
  ``registration_run`` gives: a source pin taken there names a commit whose
  bytes are not the bytes that were measured. Use a clean worktree at HEAD --
  this repository has concurrent writers, and committing their work in progress
  to manufacture a clean tree is not the same thing as having one.
* ``check`` writes nothing at all. That is the mode a pre-commit hook wants.

WHY IT REFUSES RATHER THAN GROWING A CONTROL SEQUENCE. The other repair was to
derive those seven here from a real sequence, sharing
``attest_problem_correctness.py``'s machinery instead of duplicating it. It does
not work on THIS surface, for three reasons:

* A control sequence is per-driver-family, and this surface accepts any manifest
  under ``builtin/``. ``attest_problem_correctness.CONTROLS`` stages the
  PROBLEM's own reference and wrong kernels plus the driver's own extra-symbol
  transform; none of that exists for ``native-perf/v1``, and that is the family
  whose bundle carries the declared seven right now. Sharing that machinery
  would close the surface for a family it is already closed for, and leave it
  open for the one it is open for.
* It would weld the re-pin to a pinned container image. A re-pin is what you
  need when a digest has drifted, which is exactly when you may be on a machine
  that cannot run the controls at all -- so requiring a container root here
  would turn a repairable pin into an unrepairable one.
* What it could honestly write is not separable from what it could not. The
  catalog row pins ``registration_report_digest`` beside the evidence and
  approval digests, so writing a freshly earned report without freshly earned
  evidence leaves a row naming bytes that changed.

So the pin is repaired here and the evidence is earned where the controls run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))

from ari.assurance.drivers import builtin_driver_map  # noqa: E402
from ari.assurance.models import HarnessManifestV1  # noqa: E402
# NOT IMPORTED, DELIBERATELY: HarnessRegistrationEvidenceV1 and
# HarnessPromotionApprovalV1. This surface observed no execution, so it has
# nothing to put in either of them; not importing them is what makes that a
# fact about the module rather than a discipline about its authors.
from ari.assurance.registration_run import (  # noqa: E402
    register_harness,
    result_schema_digest,
)

HARNESS_ROOT = ARI_CORE / "config" / "harnesses"
BUILTIN = HARNESS_ROOT / "builtin"


def _slug(harness_id: str) -> str:
    """The evidence-directory name for a harness id.

    UNUSED HERE SINCE THIS SURFACE STOPPED WRITING BUNDLES, and kept anyway:
    ``attest_problem_correctness.py`` imports it, so that the derived-pin rules
    and the slug spelling have one home rather than two that can disagree.
    Deleting it as dead code breaks the surface that earns the evidence.
    """
    return harness_id.replace("/", "_").replace("-", "_")


def _load(path: Path) -> HarnessManifestV1:
    return HarnessManifestV1.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))


def derived_pins(manifest: HarnessManifestV1) -> dict[str, tuple[str, str]]:
    """``field -> (pinned, computed)`` for every value the code decides.

    The three are not independent: ``manifest_digest`` covers the other two, so
    a stale driver pin is also a stale manifest digest. They are reported
    separately because they fail different gates -- ``full_sha256_integrity``
    and ``result_schema_conformance`` -- and a reader chasing one gate should
    not have to know that.
    """
    driver = builtin_driver_map().get(manifest.driver.revision)
    if driver is None:
        raise SystemExit(
            f"{manifest.id}: pins driver {manifest.driver.revision!r}, which does "
            f"not exist; this harness cannot be launched at all")
    emitted = driver.report_schema_version
    pins = {
        "driver.sha256": (manifest.driver.sha256,
                          driver.identity()["driver_digest"]),
        "expected_result_schema": (manifest.expected_result_schema, emitted),
        "expected_result_schema_digest": (manifest.expected_result_schema_digest,
                                          result_schema_digest(emitted) or ""),
    }
    # THE QUESTION AND THE SIZES, which ``prepare`` refuses on exactly as it
    # refuses on the driver. Both are computed from repository bytes, so both
    # drift the same way -- and this surface enumerated only the instrument.
    # Demonstrated: appending a comment to the pinned problem's frozen reference
    # left ``check`` reporting that harness clean while ``prepare`` raised
    # "the registered question has changed". The gate that blocks a commit was
    # therefore blind to the whole class of edit that lives under
    # config/harnesses/problems and config/harnesses/case_sets.
    #
    # Absent for a harness that pins neither, and reported as their own fields
    # because a reader chasing "the registered question has changed" should find
    # the field that names the question.
    pins.update(_question_pins(manifest))
    return pins


def _question_pins(manifest: HarnessManifestV1) -> dict[str, tuple[str, str]]:
    """``oracle.sha256`` and ``dataset.sha256``, when this harness pins them.

    Read through the same loaders ``prepare`` uses, so a pin this reports as
    current is one ``prepare`` will accept. A revision that will not load is
    reported as an empty computed value rather than raising: an unresolvable
    problem is a finding for the operator, not a crash in a gate.
    """
    from ari.assurance.native_perf_common import load_case_set
    from ari.assurance.problems import load_problem

    found: dict[str, tuple[str, str]] = {}
    # RESOLVES OR IT IS NOT THIS SURFACE'S PIN. The oracle slot does not always
    # hold a pinned problem: the three ARI-native manifests pin a GENERATED
    # oracle revision (``ari-native-gemm-oracle/v1@<sha>``) and a generated case
    # set, neither of which ``load_problem``/``load_case_set`` can resolve, and
    # neither of which their driver's ``prepare`` reads. Treating a failure to
    # resolve as drift reported all three as stale against a pin that is not of
    # this kind -- a false positive that a blocking gate would have turned into
    # three harnesses nobody could commit against.
    #
    # So: report a pin only where it is derivable. What that costs is a genuinely
    # unresolvable problem going unreported HERE; ``prepare`` still refuses it at
    # run time, and it refuses loudly, naming the revision.
    for slot, loader in (("oracle", lambda r: load_problem(r).digest),
                         ("dataset", lambda r: load_case_set(r)[1])):
        asset = getattr(manifest, slot, None)
        revision = (getattr(asset, "revision", "") or "").strip()
        if not revision:
            continue
        try:
            computed = loader(revision)
        except Exception:
            continue
        found[f"{slot}.sha256"] = (asset.sha256, computed)
    return found


def stale_pins(manifest: HarnessManifestV1) -> dict[str, tuple[str, str]]:
    return {name: pair for name, pair in derived_pins(manifest).items()
            if pair[0] != pair[1]}


def repin(manifest: HarnessManifestV1) -> HarnessManifestV1:
    """A manifest with every DERIVED field recomputed and nothing else touched."""
    computed = derived_pins(manifest)
    fields = manifest.model_dump(mode="python", exclude={"manifest_digest"})
    fields["driver"] = {**fields["driver"],
                        "sha256": computed["driver.sha256"][1]}
    fields["expected_result_schema"] = computed["expected_result_schema"][1]
    fields["expected_result_schema_digest"] = (
        computed["expected_result_schema_digest"][1])
    # THE QUESTION AND THE SIZES. Moving these is not the same act as moving the
    # instrument pin, and the caller says so: re-pinning the driver accepts code
    # that was reviewed as code, while re-pinning the oracle accepts a PROBLEM,
    # which is pinned but not approved -- anyone may edit one, no signature. The
    # manifest's pin is the only thing that stops an edited question riding
    # under a signature given for the old one, so it is moved only through a
    # re-registration that a human signs again. Refusing to move it here instead
    # would leave the harness permanently unable to run with no way back.
    for field, key in (("oracle", "oracle.sha256"), ("dataset", "dataset.sha256")):
        if key in computed and computed[key][1]:
            fields[field] = {**fields[field], "sha256": computed[key][1]}
    return HarnessManifestV1.create(**fields)


def _placement_mismatch(manifest: HarnessManifestV1) -> dict:
    """What the manifest pins versus this machine, for the keys it pins.

    Empty when the manifest pins no placement, which is the honest answer for a
    deterministic verifier: a residual bound does not depend on the allocation's
    shape, so there is nothing about this machine for its evidence to describe.
    """
    pinned = dict(manifest.registered_placement or {})
    if not pinned:
        return {}
    from ari.assurance.native_perf_common import measurement_placement

    here = measurement_placement()
    return {key: (pinned[key], here.get(key))
            for key in sorted(pinned) if here.get(key) != pinned[key]}


def check(args) -> int:
    """Report stale derived pins. Writes nothing; the pre-commit gate uses this."""
    findings: dict[str, dict] = {}
    for path in sorted(BUILTIN.glob("*.yaml")):
        stale = stale_pins(_load(path))
        if stale:
            findings[path.name] = {name: {"pinned": a, "computed": b}
                                   for name, (a, b) in stale.items()}
    if args.json:
        print(json.dumps(findings, indent=2, sort_keys=True))
    else:
        for name, fields in findings.items():
            print(f"{name}: {', '.join(sorted(fields))}")
        print(f"{len(findings)} manifest(s) pin a digest the code no longer has"
              if findings else "every manifest pins the code it is measured by")
    return 1 if findings else 0


def paths(args) -> int:
    """Every repo-relative path a manifest's derived pins depend on.

    DERIVED, not typed. A hook that carried its own list of instrument files
    would drift from the digests exactly the way the manifests did -- and it
    would drift silently, because a path missing from the list simply stops
    triggering. The digest functions are the authority on what they cover, so
    they are asked.

    ``kernels/**`` reaches this through the glob perf_driver_digest walks, so a
    new kernel source is covered without anyone remembering.
    """
    from ari.assurance.drivers.native import native_driver_digest
    from ari.assurance.drivers.perf import perf_driver_digest
    from ari.assurance.drivers.problem_correctness import (
        problem_correctness_driver_digest)

    covered: set[Path] = set()
    for digest in (native_driver_digest, perf_driver_digest,
                   problem_correctness_driver_digest):
        # The functions do not expose their file list, so it is recovered the
        # only way that cannot go stale: ask what they read, by watching them.
        covered |= _files_read_by(digest)
    covered |= set(BUILTIN.glob("*.yaml"))
    covered |= set((ARI_CORE / "ari" / "schemas").glob("native_*report*.json"))
    # THE QUESTION AND THE SIZES. ``prepare`` refuses on the oracle and dataset
    # pins exactly as it refuses on the driver, and both are computed from these
    # trees -- so a commit that edits a problem's frozen reference or a case
    # set's shapes invalidates a manifest just as surely as an instrument edit.
    # Demonstrated before this line existed: appending a comment to the pinned
    # problem's reference left the gate silent and ``prepare`` raising.
    for tree in ("problems", "case_sets"):
        root = HARNESS_ROOT / tree
        if root.is_dir():
            covered |= {p for p in root.rglob("*") if p.is_file()}
    for path in sorted(covered):
        print(path.relative_to(REPO_ROOT))
    return 0


def _files_read_by(digest_fn) -> set[Path]:
    """Which files a digest function opened, observed rather than declared."""
    opened: set[Path] = set()
    real = Path.read_bytes

    def watched(self, *a, **k):
        opened.add(self.resolve())
        return real(self, *a, **k)

    Path.read_bytes = watched
    try:
        digest_fn()
    finally:
        Path.read_bytes = real
    return {p for p in opened if p.is_relative_to(REPO_ROOT)}


def attesting_surfaces() -> dict[str, str | None]:
    """``driver revision -> the surface that can EARN that family's evidence``.

    ``None`` is a real answer and not a hole: it says no surface in this
    repository can earn that family's registration evidence, because the family
    has no control sequence. Saying so is the point -- an unearnable bundle is
    exactly what the seven literals used to hide, and a caller sent to a surface
    that does not exist would go looking rather than assume it had been done.

    Keyed by the revision CONSTANTS rather than by copies of their strings, so
    renaming a revision breaks this import instead of dropping a family out of
    the map in silence. A test requires every shipped manifest's revision to be
    a key here, so a new family arrives with an answer or turns the suite red.
    """
    from ari.assurance.drivers.native import NATIVE_DRIVER_REVISION
    from ari.assurance.drivers.perf import PERF_DRIVER_REVISION
    from ari.assurance.drivers.problem_correctness import (
        PROBLEM_CORRECTNESS_DRIVER_REVISION)

    return {
        PROBLEM_CORRECTNESS_DRIVER_REVISION: (
            "attest_problem_correctness.py promote --manifest {manifest} "
            "--container-root <the directory holding the pinned image> "
            "--actor-id <maintainer> --authorization-basis '<what you saw>' "
            "--approved-date <date>"),
        NATIVE_DRIVER_REVISION: (
            "promote_native_harnesses.py, which runs this family's "
            "four-execution control sequence -- though its _immutable_outputs "
            "refuses to overwrite an existing artifact, so a RE-registration "
            "needs the shape attest_problem_correctness.py has"),
        # No control sequence exists for the performance family. Its bundle is
        # the one still carrying the seven declared values, and it cannot be
        # honestly renewed until something can run its controls.
        PERF_DRIVER_REVISION: None,
    }


def _print_next_step(loaded: list[tuple[str, HarnessManifestV1]]) -> None:
    """Where the registration evidence has to be earned, named per family."""
    surfaces = attesting_surfaces()
    print("")
    print("NOT WRITTEN: registration evidence, promotion approval, catalog row.")
    print("Re-pinning moves manifest_digest, so the evidence bundle and the")
    print("signature over it have to be re-earned by RUNNING the harness's")
    print("controls -- which this surface never does. Earn them here:")
    for name, manifest in loaded:
        revision = manifest.driver.revision
        if revision not in surfaces:
            print(f"  {manifest.id}: driver {revision} has no entry here, so no "
                  f"surface is known to earn its evidence")
        elif surfaces[revision] is None:
            print(f"  {manifest.id}: NOTHING can earn this family's evidence "
                  f"today -- it has no control sequence, and its registration "
                  f"cannot be honestly renewed until one exists")
        else:
            print(f"  {manifest.id}: scripts/rqgm_assurance/"
                  + surfaces[revision].replace("{manifest}", name))


def repin_manifests(args) -> int:
    """Re-pin every named manifest's DERIVED fields, and report its gates.

    EVERY MANIFEST IS RE-PINNED BEFORE ANY GATE RUNS, and that ordering is not
    tidiness. ``register_harness`` refuses a dirty tree and writing one manifest
    dirties the tree for the next -- so a batch of three used to get one done
    and raise on the other two, which is a tool that silently does part of what
    it was asked. Measured, on exactly that: gemm-correctness through, spmm and
    stencil raised. Re-pins first, gates second, so the batch is all or none.

    The gate report is printed and never recorded. It answers "is this manifest
    registrable again", which is what you want to know before spending container
    time on the surface that can actually re-register it.
    """
    loaded, needs_commit = [], []
    for name in args.manifests:
        path = BUILTIN / name
        manifest = _load(path)
        stale = stale_pins(manifest)
        print(f"harness   : {manifest.id}")
        for field, (pinned, computed) in sorted(stale.items()):
            print(f"  re-pin  : {field}  {pinned[:26]}… -> {computed[:26]}…")
        if not stale:
            print("  pins    : already current")
        differs = _placement_mismatch(manifest)
        if differs:
            print(f"REFUSED: this is not the placement {manifest.id} pins: {differs}")
            print("Its gates measure that machine. Run this there.")
            return 2
        repinned = repin(manifest)
        if stale:
            needs_commit.append((path, repinned))
        loaded.append((name, repinned))

    if needs_commit and not args.dry_run:
        for path, manifest in needs_commit:
            path.write_text(yaml.safe_dump(manifest.model_dump(mode="json"),
                                           sort_keys=True, default_flow_style=False),
                            encoding="utf-8")
            print(f"  manifest: {manifest.id} -> {manifest.manifest_digest}")
        print(f"Re-pinned {len(needs_commit)} manifest(s). Commit them, then re-run: "
              f"the gate report refuses a dirty tree.")
        _print_next_step(loaded)
        return 3

    for name, manifest in loaded:
        driver = builtin_driver_map()[manifest.driver.revision]
        report = register_harness(manifest, driver, runs=args.runs, allow_dirty=False)
        passed = sum(1 for gate in report.gates if gate.passed)
        print(f"gates     : {manifest.id}  {passed}/{len(report.gates)}  "
              f"decision={report.decision!r}")
        for gate in report.gates:
            if not gate.passed:
                print(f"  FAIL {gate.gate_id}: {gate.detail[:96]}")
        if report.decision != "eligible-for-verified":
            print("REFUSED: the re-pinned manifest does not pass its own gates; "
                  "a rejected registration is a result")
            return 4

    _print_next_step(loaded)
    return 0


def promote(args) -> int:
    """REFUSED, always: this surface cannot earn what a promotion asserts.

    KEPT AS A MODE RATHER THAN DELETED. Deleting it would answer an existing
    invocation -- the pre-commit hook printed one for three episodes -- with
    argparse's "invalid choice", and what a caller needs here is not that the
    word is wrong but where the evidence is earned. So it loads the manifests it
    was given, purely to name their families, and writes nothing.

    ``--actor-id`` and ``--authorization-basis`` are accepted and no longer
    required, so a maintainer's real signature reaches this explanation instead
    of a usage error. Nothing is signed either way.
    """
    print("REFUSED: this surface writes no registration evidence, no promotion "
          "approval and no catalog row.")
    print("")
    print("A promotion asserts seven things about executions -- two control "
          "verdicts, network isolation, target-write isolation, oracle "
          "visibility, result-schema conformance and official-runner parity -- "
          "plus the attestations they were read off. This surface runs no "
          "controls, so it used to write all seven as literals and point "
          "attestation_digests at its own registration report: the bundle cited "
          "itself as the execution it never performed.")
    if args.actor_id or args.authorization_basis:
        print("")
        print("A signature was supplied. NOTHING WAS SIGNED: an approval over "
              "evidence no execution produced is the forgery this refusal "
              "exists to prevent.")
    print("")
    print(f"Re-pin here:  {Path(__file__).name} repin {' '.join(args.manifests)}")
    named = [(name, _load(BUILTIN / name)) for name in args.manifests
             if (BUILTIN / name).is_file()]
    if named:
        _print_next_step(named)
    return 6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    lister = sub.add_parser("paths", help="repo-relative paths the derived pins depend on")
    lister.set_defaults(func=paths)

    checker = sub.add_parser("check", help="report stale derived pins; writes nothing")
    checker.add_argument("--json", action="store_true")
    checker.set_defaults(func=check)

    repinner = sub.add_parser(
        "repin", help="re-pin derived manifest fields and report the gates")
    repinner.add_argument("manifests", nargs="+",
                          help="file name(s) under config/harnesses/builtin/. "
                               "Several may be given: every manifest is re-pinned "
                               "before any gate runs, because writing one dirties "
                               "the tree the next one refuses.")
    repinner.add_argument("--runs", type=int, default=3,
                          help="parity-probe repetitions behind the stability gate")
    repinner.add_argument("--dry-run", action="store_true",
                          help="report the re-pin and run the gates, write nothing")
    repinner.set_defaults(func=repin_manifests)

    # KEPT SO IT CAN REFUSE. An invocation that used to mint declared evidence
    # reaches an explanation and the surface that earns it, rather than an
    # argparse usage error that says only that the word is gone.
    promoter = sub.add_parser(
        "promote", help="REFUSED: registration evidence is earned elsewhere")
    promoter.add_argument("manifests", nargs="+",
                          help="file name(s) under config/harnesses/builtin/, "
                               "read only to name the surface that can attest "
                               "each one's family")
    promoter.add_argument("--actor-id", default="",
                          help="accepted and unused; nothing here is signed")
    promoter.add_argument("--authorization-basis", default="",
                          help="accepted and unused; nothing here is signed")
    promoter.add_argument("--runs", type=int, default=3, help=argparse.SUPPRESS)
    promoter.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    promoter.set_defaults(func=promote)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
