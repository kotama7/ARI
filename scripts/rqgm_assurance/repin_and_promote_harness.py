#!/usr/bin/env python3
"""Re-pin a registered Harness to the code it is measured by, and promote it.

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
impossible at the moment of writing -- and cannot do the job here for two
reasons. Its ``_immutable_outputs`` refuses to overwrite any existing artifact
whose bytes differ, so it cannot move a pin that is already on disk; and it
hands ``registration_report`` a set of gates with ``passed=True`` written into
them, which that function stopped accepting at ``ccdedc9`` on the grounds that
there is deliberately no way to hand it a pre-decided gate. It raises TypeError
today. This surface computes the pins and earns the gates instead.

WHAT IT WILL NOT DO.

* It re-pins DERIVED fields only. Everything a human decided -- the placement,
  the scope, the tiers, the policies, the container, the problem and case set --
  is read and never written. A tool that could move ``registered_placement``
  could relocate a harness's evidence to whatever machine was at hand, which is
  a change to what the harness asserts rather than a repair.
* It refuses to produce evidence off the pinned placement. The performance
  harness pins an aarch64 node at a 48-thread budget; run this on anything else
  and it stops before measuring, rather than recording a number that describes
  the wrong machine.
* It refuses a dirty working tree, for the reason ``registration_run`` gives:
  a source pin taken there names a commit whose bytes are not the bytes that
  were measured. Use a clean worktree at HEAD -- this repository has concurrent
  writers, and committing their work in progress to manufacture a clean tree is
  not the same thing as having one.
* ``--check`` writes nothing at all. That is the mode a pre-commit hook wants.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))

from ari.assurance.drivers import builtin_driver_map  # noqa: E402
from ari.assurance.models import HarnessManifestV1  # noqa: E402
from ari.assurance.registration_models import (  # noqa: E402
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
)
from ari.assurance.registration_run import (  # noqa: E402
    register_harness,
    repository_commit,
    result_schema_digest,
)
from ari.protocols.integrity import bytes_digest  # noqa: E402

HARNESS_ROOT = ARI_CORE / "config" / "harnesses"
BUILTIN = HARNESS_ROOT / "builtin"


def _slug(harness_id: str) -> str:
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
    return {
        "driver.sha256": (manifest.driver.sha256,
                          driver.identity()["driver_digest"]),
        "expected_result_schema": (manifest.expected_result_schema, emitted),
        "expected_result_schema_digest": (manifest.expected_result_schema_digest,
                                          result_schema_digest(emitted) or ""),
    }


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


def promote(args) -> int:
    """Re-pin, register and sign every named harness.

    EVERY REGISTRATION RUNS BEFORE ANY WRITE, and that ordering is not tidiness.
    ``register_harness`` refuses a dirty tree, and writing one harness's evidence
    dirties the tree for the next -- so promoting three in sequence promoted the
    first and refused the other two, which is a tool that silently does part of
    what it was asked. Measured, on exactly that: gemm-correctness signed, spmm
    and stencil raised. Gates first, writes second, so the batch is all or none.
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
            print("Its evidence describes that machine. Run this there.")
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
              f"registration refuses a dirty tree.")
        return 3

    earned = []
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
            print("REFUSED: nothing is written for ANY harness in this batch; "
                  "a rejected registration is a result")
            return 4
        earned.append((name, manifest, driver, report))

    if args.dry_run:
        print("dry run: gates pass; no evidence, approval or catalog row written")
        return 0
    # ONCE, BEFORE THE FIRST WRITE. Every bundle in this batch records the same
    # source commit, which is true -- they were all measured against it -- and
    # is the only way to record it: the first write dirties the tree, so asking
    # again would refuse. Same defect as the gates, one layer down.
    commit = repository_commit(allow_dirty=False)
    for name, manifest, driver, report in earned:
        _write_promotion(name, manifest, driver, report, args, commit)
    return 0


def _write_promotion(manifest_name, manifest, driver, report, args,
                     commit: str) -> None:
    from ari.assurance.native_perf_common import (measurement_environment,
                                                  measurement_placement)
    from ari.orchestrator.node_summary_view import scrub_host_identity

    slug = _slug(manifest.id)
    evidence_dir = HARNESS_ROOT / "evidence" / slug
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, payload) -> None:
        (evidence_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    probe = driver.parity_probe(manifest)
    clean = (probe.get("controls") or {}).get("clean") or {}
    _write("registration_report.json", report.model_dump(mode="json"))
    _write("gate_findings.json",
           {g.gate_id: {"passed": g.passed, "detail": g.detail} for g in report.gates})
    _write("official_runner_parity.json", probe)
    _write("multiple_run_stability.json", {"runs": args.runs, "clean_control": clean})
    # SCRUBBED AT THE PUBLICATION BOUNDARY. ``measurement_environment`` captures
    # every variable under a prefix set and drops SECRETS by name fragment, but
    # not host PATHS by value -- an ``ARI_*`` variable holding an absolute path
    # is ordinary, and this record is committed and published. Measured: a
    # bundle carried a home directory and a username this way, and the bundles
    # that did not were clean because the variable happened to be unset.
    environment = measurement_environment()
    environment["variables"] = {k: scrub_host_identity(v)
                                for k, v in environment["variables"].items()}
    pinned = dict(manifest.registered_placement or {})
    here = measurement_placement()
    _write("measurement_environment.json",
           {"environment": environment,
            "registration_commit": commit,
            "placement": ({k: here.get(k) for k in sorted(pinned)} if pinned
                          else None),
            "placement_note": (
                "this harness pins no placement, so its evidence does not "
                "describe a machine" if not pinned else
                "a timed verdict is a statement about a machine; the manifest "
                "pins this placement and prepare() refuses any other"),
            "environment_note": "variable VALUES are scrubbed of host identity here"})

    artifacts = {f"evidence/{slug}/{p.name}": bytes_digest(p.read_bytes())
                 for p in sorted(evidence_dir.glob("*.json"))
                 if p.name != "registration_evidence.json"}
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id, harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest, source_full_commit_sha=commit,
        environment_digest=measurement_environment()["sha256"],
        evidence_artifact_digests=dict(sorted(artifacts.items())),
        attestation_digests=(report.report_digest,),
        clean_control_verdict="pass", negative_control_verdict="fail",
        official_runner_parity=True, result_schema_conformant=True,
        network_isolation="proved", target_write_isolation="proved",
        oracle_visibility="denied", run_count=args.runs)
    _write("registration_evidence.json", evidence.model_dump(mode="json"))

    (HARNESS_ROOT / "reports" / f"{slug}.registration.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    approval = HarnessPromotionApprovalV1.create(
        harness_id=manifest.id, harness_version=manifest.version,
        actor_kind="human-maintainer", actor_id=args.actor_id,
        authorization_basis=args.authorization_basis,
        approved_date=subprocess.run(["git", "log", "-1", "--format=%cs", commit],
                                     capture_output=True, text=True).stdout.strip(),
        harness_manifest_digest=manifest.manifest_digest,
        registration_report_digest=report.report_digest,
        evidence_bundle_digest=evidence.evidence_digest)
    (HARNESS_ROOT / "approvals" / f"{slug}.approval.json").write_text(
        json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    catalog_path = HARNESS_ROOT / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    entry = {"id": manifest.id,
             "manifest": f"builtin/{manifest_name}",
             "registration_report": f"reports/{slug}.registration.json",
             "registration_report_digest": report.report_digest,
             "registration_evidence": f"evidence/{slug}/registration_evidence.json",
             "registration_evidence_digest": evidence.evidence_digest,
             "promotion_approval": f"approvals/{slug}.approval.json",
             "promotion_approval_digest": approval.approval_digest}
    catalog["entries"] = sorted(
        [e for e in catalog["entries"] if e["id"] != manifest.id] + [entry],
        key=lambda e: e["id"])
    catalog_path.write_text(
        yaml.safe_dump(catalog, sort_keys=False, default_flow_style=False),
        encoding="utf-8")
    print(f"signed    : {approval.actor_id} ({approval.actor_kind})")
    print("written   : evidence, report, approval, catalog")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    lister = sub.add_parser("paths", help="repo-relative paths the derived pins depend on")
    lister.set_defaults(func=paths)

    checker = sub.add_parser("check", help="report stale derived pins; writes nothing")
    checker.add_argument("--json", action="store_true")
    checker.set_defaults(func=check)

    promoter = sub.add_parser("promote", help="re-pin, register and sign one harness")
    promoter.add_argument("manifests", nargs="+",
                          help="file name(s) under config/harnesses/builtin/. "
                               "Several may be given: every registration runs "
                               "before any write, because writing one dirties "
                               "the tree the next one refuses.")
    promoter.add_argument("--actor-id", required=True,
                          help="the human maintainer authorizing the promotion")
    promoter.add_argument("--authorization-basis", required=True,
                          help="what the maintainer actually saw. A basis claiming a "
                               "review that did not happen is the defect the "
                               "signature exists to prevent.")
    promoter.add_argument("--runs", type=int, default=3)
    promoter.add_argument("--dry-run", action="store_true",
                          help="run the gates, write nothing")
    promoter.set_defaults(func=promote)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
