"""Task 20 section 8 Harness-Assurance acceptance criteria 40, 41 and 47.

Section 8 names a test id per criterion, and three of the Harness-Assurance
ids had no test under them. What each binds here:

* 40 ``test_infrastructure_error_semantics`` — an infrastructure error is
  neither a scientific failure nor an accusation. Both halves against
  production: the bridge's own frontier classification over its whole verdict
  vocabulary and the evaluator's ranking currency for the first, and the
  CK-HAR-019 boundary plus a real epoch audit for the second.
* 41 ``test_ordinary_failure_no_impeachment`` — a wrong candidate is an
  ordinary failed experiment. The node's own kernel boundary raises nothing
  the honest node does not, and the record production writes for it drives no
  motion through the real governance pipeline.
* 47 ``test_hidden_test_isolation`` — the candidate is never handed the
  answer: not by registration (a Harness that will not keep its tests to the
  verifier cannot be registered), not by the work dir it starts from, and not
  by the problem file the frozen driver hands its child.

Every fixture below drives production code rather than restating what it
writes: the audit records come from ``RQGMRuntime._record_kca_node_provenance``
and the verdicts from real ``HarnessAttestationV1`` documents, so a payload
that drifts from this file's expectations is a real drift.

No LLM and no network: the governance orchestrator runs with ``llm=None``,
which is its fully deterministic floor.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ari.assurance.models import (
    HarnessAttestationV1,
    HarnessManifestV1,
    HarnessPropertyResultV1,
    VerificationScopeV1,
)
from ari.config import RQGMConfig
from ari.rqgm.governance import GovernanceOrchestrator
from ari.rqgm.governance._pipeline import _epoch_records
from ari.rqgm.governance._prosecution import ATTACK_THRESHOLD, classify_target
from ari.rqgm.governance._reliability import build_reliability_entries
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.runtime import RQGMRuntime
from ari.rqgm.store import ImmutableAuditLog


SHA = "sha256:" + "1" * 64
EPOCH = "epoch_000"
GENERATOR = "generator_v1"
PROMPT_HASH = "a" * 12


# ── one real Attestation, and the audit record production writes for it ──────


def _attestation(node_id: str, verdict: str) -> HarnessAttestationV1:
    """A real Attestation carrying *verdict*, minted the way a driver mints it."""
    result = HarnessPropertyResultV1(
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="screen",
        tested_scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        verdict=verdict,
        covered_atom_digests=(SHA,),
        evidence_artifact_refs=(),
    )
    return HarnessAttestationV1.create(
        run_id="run-1",
        node_id=node_id,
        epoch_id=EPOCH,
        producer_epoch_id=EPOCH,
        research_contract_digest=SHA,
        verification_contract_digest=SHA,
        knowledge_skill_use_digest=SHA,
        capability_binding_lock_digest=SHA,
        baseline_harness_lock_digest=SHA,
        active_harness_lock_digest=SHA,
        harness_manifest_digest=SHA,
        driver_digest=SHA,
        oracle_digest=SHA,
        dataset_digest=SHA,
        container_digest=SHA,
        target_logical_name="candidate.so",
        target_digest=SHA,
        target_kind="shared-library",
        execution_identity=SHA,
        execution_result_digest=SHA,
        verdict=verdict,
        property_results=(result,),
        evidence_artifact_refs=(),
        # The model refuses "the machine is fine" beside an infrastructure
        # error, so the two fields are moved together rather than separately.
        infrastructure_status=(
            "failed" if verdict == "infrastructure_error" else "ready"
        ),
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id="attempt-1",
        retry_index=0,
    )


def _audit_log_for_nodes(checkpoint: Path, verdict: str, count: int) -> list:
    """*count* nodes whose verification came back *verdict*, in a real log.

    The records are not written by this file: they are produced by
    ``RQGMRuntime._record_kca_node_provenance``, the method that folds a
    finished node's Attestations into the epoch audit log, so what the
    governance pipeline reads below is what a run would actually hand it.
    """
    runtime = RQGMRuntime.__new__(RQGMRuntime)
    runtime._kca_feature_enabled = True
    runtime._run_admission = SimpleNamespace(
        knowledge_skill_lock_digest=None, capability_binding_lock_digest=None
    )
    runtime.checkpoint_dir = checkpoint
    runtime._epoch_state = SimpleNamespace(
        epoch=SimpleNamespace(epoch_id=EPOCH)
    )
    runtime._capability_authorization_view = None
    for index in range(count):
        node_id = f"node_{index:03d}"
        relative = f"rqgm/kca/nodes/{node_id}/screen.attestation.json"
        path = checkpoint / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_attestation(node_id, verdict).model_dump(mode="json")),
            encoding="utf-8",
        )
        runtime._record_kca_node_provenance(
            SimpleNamespace(
                id=node_id,
                attestation_refs=(relative,),
                producer_component_id=GENERATOR,
                producer_prompt_hash=PROMPT_HASH,
                verified_target_digest=SHA,
            )
        )
    log = ImmutableAuditLog.read(checkpoint)
    records = _epoch_records(log, EPOCH)
    assert len(records) == count, (
        f"production wrote {len(records)} records for {count} verified nodes; "
        "the governance assertions below would be about an empty log")
    assert {str(record.get("status")) for record in records.values()} == {verdict}
    assert {
        str(record.get("target_component_id")) for record in records.values()
    } == {GENERATOR}, "the records do not even name the Generator as their subject"
    return log


def _generator_own_records() -> list:
    """The Generator's own outputs, so its reliability is measured, not absent.

    Without them the component is ``insufficient_data`` and no motion could be
    filed against it for any reason -- which would make every assertion below
    true for the wrong reason.
    """
    return [
        {
            "record_type": "node_proposal",
            "schema_version": 1,
            "record_id": f"gen_{index:05d}",
            "epoch_id": EPOCH,
            "component_id": GENERATOR,
            "prompt_hash": PROMPT_HASH,
            "role": "generator",
            "created_at": "2026-08-19T00:00:00Z",
            "source_refs": [],
            "status": "recorded",
        }
        for index in range(2)
    ]


def _validated_attack(seq: int) -> dict:
    """A REAL validated attack against the Generator: the positive control.

    Built by the producer rather than by hand, because the point of the
    control is that this pipeline DOES file a motion when the accusation is
    the kind governance is for -- if the control were a hand-made dict whose
    key the producer never writes, the zero it is controlling would be
    meaningless.
    """
    from ari.rqgm.adversarial.records import (
        EvidenceRef,
        JudgmentRecord,
        RawAttackRecord,
        TargetArtifact,
        make_validated_attack_record,
    )

    attack = RawAttackRecord(
        record_id="atk_%06d" % seq,
        adversary_type="overclaim",
        target_artifact=TargetArtifact(
            type="paper_claim",
            node_id="node_017",
            ref="paper.md#/claims/1",
            artifact_hash="sha256:abc",
        ),
        attack_claim="the conclusion outruns the recorded evidence",
        attack_evidence_refs=(EvidenceRef(path="node_report.json"),),
        severity_claimed="high",
        confidence=0.8,
        epoch_id=EPOCH,
        component_id="adversary_overclaim_v1",
        prompt_hash=PROMPT_HASH,
        created_at="2026-07-06T00:00:00Z",
    )
    judgment = JudgmentRecord(
        record_id="jdg_%06d" % seq,
        raw_attack_id=attack.record_id,
        defense_id="def_%06d" % seq,
        verdict="valid",
        severity="high",
        rationale="claim unsupported by the recorded evidence",
        defense_status="present",
        epoch_id=EPOCH,
        component_id="artifact_judge_v1",
        prompt_hash=PROMPT_HASH,
        created_at="2026-07-06T00:00:00Z",
    )
    return make_validated_attack_record(
        judgment,
        attack,
        record_id="vat_%06d" % seq,
        expected_behavior={"generator": "stop emitting the defect class"},
        affected_components=("generator",),
        target_component_id=GENERATOR,
    ).to_dict()


def _audit(log: list) -> tuple:
    """One real epoch audit. Returns ``(report, written records)``."""
    orchestrator = GovernanceOrchestrator(
        RQGMConfig(enabled=True, governance={}, replay={}),
        kernel=ConstitutionalKernel(),
    )
    report = orchestrator.audit_epoch(
        epoch_state=SimpleNamespace(
            epoch_id=EPOCH, active_prompt_hashes={"generator": PROMPT_HASH}
        ),
        audit_log=log,
        component_registry=None,
        prompt_registry=None,
        candidate_prompts=(),
        adversarial_replay_pool=None,
    )
    return report, list(orchestrator.written)


def _governance_is_silent_about(log: list, baseline: list) -> None:
    """No motion, and no governance record the baseline epoch did not write.

    The record-type comparison is what carries "no failing node is ever driven
    through governance": it is not a list of the record types that would be an
    accusation, it is every type the audit emitted, compared against the same
    epoch with the failed nodes taken out. A prosecution of any shape shows up
    as a type the baseline does not have.
    """
    report, written = _audit(log)
    base_report, base_written = _audit(baseline)
    assert report.impeachment_motions == [], report.impeachment_motions
    assert report.adjudications == [], report.adjudications
    assert {kind for kind, _ in written} == {kind for kind, _ in base_written}
    assert base_report.impeachment_motions == []
    entries = {
        entry["component_id"]: entry
        for entry in build_reliability_entries(
            list(_epoch_records(log, EPOCH).values())
        )
    }
    generator = entries[GENERATOR]
    assert generator["observation_count"] > 0, (
        "the Generator authored nothing this epoch, so it is unprosecutable "
        "for any reason and this test proves nothing")
    assert generator["validated_attack_involvement"] == 0
    assert classify_target(generator) is None


def _positive_control(log: list) -> None:
    """The same epoch, with the accusation governance IS for: a motion is filed.

    Without this the silence above could be a pipeline that never files
    anything.
    """
    report, written = _audit(log + [_validated_attack(1), _validated_attack(2)])
    motions = [payload for kind, payload in written if kind == "impeachment_motion"]
    assert len(report.impeachment_motions) == 1
    assert [motion["target_component_id"] for motion in motions] == [GENERATOR]
    assert motions[0]["charge"] == "validated_attack_threshold_exceeded"


# ── the node's own constitutional boundary ──────────────────────────────────


def _kca_harness_codes(checkpoint: Path, *, assurance_mode="enforce", **node_fields):
    """The CK-HAR codes the node's recorded assurance outcome raises.

    Enters at ``_kca_reports_for_node``, the fan-out ``run_per_node_kernel_check``
    calls, so every input the rules see is derived by the runtime from what the
    assurance bridge recorded -- never handed in by this test.
    """
    (checkpoint / "rqgm" / "kca" / "nodes" / "n1").mkdir(parents=True, exist_ok=True)
    admission = SimpleNamespace(
        knowledge_skill_lock_digest=None,
        capability_binding_lock_digest=None,
        verification_contract_digest="",
        verification_environment_digest=None,
        active_harness_lock_digest=None,
        baseline_harness_lock_digest="sha256:" + "f" * 64,
        modes=SimpleNamespace(assurance=assurance_mode),
    )
    runtime = RQGMRuntime.__new__(RQGMRuntime)
    runtime.checkpoint_dir = checkpoint
    runtime._admission_artifacts = SimpleNamespace(documents={})
    runtime._capability_authorization_view = None
    node = SimpleNamespace(
        id="n1", attestation_refs=(), verified_target_digest="", **node_fields
    )
    reports = runtime._kca_reports_for_node(
        ConstitutionalKernel(), admission, node, "n1"
    )
    return {
        violation.code
        for report in reports
        for violation in report.violations
        if violation.code.startswith("CK-HAR-")
    }


# ── criterion 41 ────────────────────────────────────────────────────────────


def test_ordinary_failure_no_impeachment(tmp_path):
    """Task 20 section 8 criterion 41: one wrong candidate does not impeach
    the Generator, and no failing node is driven through governance at all.

    More than one, in fact: the fixture fails ``ATTACK_THRESHOLD + 1`` nodes,
    read off the prosecutor's own threshold, so the count that would clear the
    bar if a failed verification counted as an accusation is the count used.

    Three places, because a wrong candidate could become an accusation at any
    of them: the node's own kernel boundary, the epoch audit's reliability
    arithmetic, and the motion pipeline. The last is compared against the same
    epoch with the failures removed, so a prosecution of ANY shape shows up
    rather than only the ones this file thought to name.
    """
    honest = _kca_harness_codes(
        tmp_path / "honest",
        assurance_status="pass",
        property_verdicts={"numerical-equivalence": "pass"},
        frontier_class="scientific_frontier",
    )
    failed = _kca_harness_codes(
        tmp_path / "failed",
        assurance_status="fail",
        property_verdicts={"numerical-equivalence": "fail"},
        frontier_class="debug_frontier",
    )
    assert failed <= honest, (
        f"a failed candidate raised {sorted(failed - honest)} that the same "
        "node passing does not; an ordinary failure became a constitutional "
        "finding")

    # ... and the accusation IS available: a fail restated as a success raises
    # it, so the silence above is about the failure being ordinary.
    claimed = _kca_harness_codes(
        tmp_path / "claimed",
        assurance_status="pass",
        property_verdicts={"numerical-equivalence": "fail"},
        frontier_class="scientific_frontier",
    )
    assert claimed - honest == {"CK-HAR-019"}

    log = _audit_log_for_nodes(
        tmp_path / "run", "fail", ATTACK_THRESHOLD + 1
    ) + _generator_own_records()
    _governance_is_silent_about(log, _generator_own_records())
    _positive_control(log)


# ── criterion 40 ────────────────────────────────────────────────────────────


def test_infrastructure_error_semantics(tmp_path):
    """Task 20 section 8 criterion 40: an infrastructure error is neither a
    scientific failure nor an impeachment.

    Not a scientific failure, at the two places a run says what an outcome
    was: the bridge's frontier classification -- read over its whole verdict
    vocabulary, so a verdict added to that vocabulary is classified here on
    the day it lands -- and the evaluator's ranking currency, where an outage
    must carry no score at all rather than the zero a measured loss earns.

    Not an impeachment, at the two places a verdict could become one: the
    CK-HAR-019 boundary, which is ``block`` and would mark the node
    ``tampered``, and the epoch audit that reads the record production writes
    for it.
    """
    from ari.rqgm.assurance_bridge import _VERDICT_RANK, RQGMAssuranceBridge

    bridge = SimpleNamespace(
        admission=SimpleNamespace(modes=SimpleNamespace(assurance="enforce"))
    )
    vocabulary = tuple(_VERDICT_RANK)
    assert {"pass", "fail", "infrastructure_error"} <= set(vocabulary), vocabulary
    classes = {
        verdict: RQGMAssuranceBridge._frontier(
            bridge, verdict, {"numerical-equivalence": verdict}
        )
        for verdict in vocabulary
    }
    assert classes["pass"] == "scientific_frontier"
    # The scientific frontier is for a pass and for nothing else...
    assert [
        verdict for verdict, where in classes.items()
        if where == "scientific_frontier"
    ] == ["pass"]
    # ... a candidate that was measured and lost is a result to repair ...
    assert classes["fail"] == "debug_frontier"
    # ... and broken machinery is neither of those things.
    assert classes["infrastructure_error"] not in {
        "scientific_frontier", classes["fail"]
    }

    from ari.evaluator.deterministic_evaluator import DeterministicEvaluator

    def _broken(_work_dir):
        raise RuntimeError("the harness could not be resolved")

    outage = DeterministicEvaluator(measure_fn=_broken).evaluate_sync("g", [], "s")
    assert outage["evaluation_status"] == "infrastructure_error"
    lost = DeterministicEvaluator()._score({"compile_ok": False, "families": {}})
    assert lost["metrics"]["_scientific_score"] == 0.0
    assert outage["metrics"] == {} and "scientific_score" not in outage, (
        "an outage was ranked; a zero there is a claim about the candidate")

    # The mismatch the certify path manufactures on its own: the status is
    # rewritten to infrastructure_error while the per-property verdicts
    # already merged into the node stay behind. Broken machinery is not a
    # suppressed verdict.
    honest = _kca_harness_codes(
        tmp_path / "honest",
        assurance_status="pass",
        property_verdicts={"numerical-equivalence": "pass"},
        frontier_class="scientific_frontier",
    )
    outaged = _kca_harness_codes(
        tmp_path / "outage",
        assurance_status="infrastructure_error",
        property_verdicts={"numerical-equivalence": "fail"},
        frontier_class="uncertified_frontier",
    )
    assert outaged <= honest, sorted(outaged - honest)
    # The neighbouring state still fires, so the exemption is not a hole: an
    # infrastructure error standing on the scientific frontier was put there
    # by something other than the fail-open path.
    promoted = _kca_harness_codes(
        tmp_path / "promoted",
        assurance_status="infrastructure_error",
        property_verdicts={"numerical-equivalence": "fail"},
        frontier_class="scientific_frontier",
    )
    assert promoted - honest == {"CK-HAR-019"}

    log = _audit_log_for_nodes(
        tmp_path / "run", "infrastructure_error", ATTACK_THRESHOLD + 1
    ) + _generator_own_records()
    _governance_is_silent_about(log, _generator_own_records())
    _positive_control(log)


# ── criterion 47 ────────────────────────────────────────────────────────────


class _StubManifest:
    """Only the fields the registration gates read.

    A real manifest is a frozen 46-field contract; what is under test is
    whether the gate LOOKS at the policy, so the fixture supplies the fields
    the gates read and nothing else.
    """

    scorer_determinism = "deterministic"
    nondeterminism_declaration = "none"
    timeout_seconds = 600
    hidden_test_policy = "verifier-only"
    network_policy = "deny"
    credential_policy = "none"
    source_full_commit_sha = "b" * 40
    expected_result_schema = "ari.stub-report/v1"
    expected_result_schema_digest = "sha256:" + "c" * 64

    class _Asset:
        sha256 = "sha256:" + "a" * 64
        license = "MIT"

    dataset = oracle = driver = model = _Asset()


def _gate_verdicts(policy):
    from ari.assurance.registration_gates import GateEvidence, evaluate_gates

    manifest = _StubManifest()
    manifest.hidden_test_policy = policy
    return {gate.gate_id: gate.passed for gate in evaluate_gates(
        GateEvidence(manifest=manifest))}


def _instance_bytes(value) -> int:
    """Total bytes of every array reachable in a family's problem instance.

    Walks whatever the family generated rather than knowing its shape: dense
    arrays by ``nbytes``, a sparse matrix by the three arrays it is made of.
    """
    import numpy as np

    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if all(hasattr(value, name) for name in ("indptr", "indices", "data")):
        return int(value.indptr.nbytes + value.indices.nbytes + value.data.nbytes)
    if isinstance(value, (tuple, list)):
        return sum(_instance_bytes(item) for item in value)
    return 0


def _smallest_cases_by_family() -> dict:
    """One case per registered family: the cheapest set shipped for it.

    Derived from both registries -- the families ARI has registered and the
    case sets it ships -- so a family added tomorrow is measured here rather
    than silently skipped.
    """
    import yaml

    from ari.assurance.native_perf_common import case_sets_root, load_case_set
    from ari.assurance.native_perf_family import get_family, registered_families

    out: dict = {}
    for path in sorted(case_sets_root().glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        revision = str(raw.get("revision", ""))
        if not revision:
            continue
        case_set, _digest = load_case_set(revision)
        if case_set.kind not in registered_families():
            continue
        family = get_family(case_set.kind)
        for case in case_set.cases:
            size = family.output_elements(tuple(case))
            best = out.get(case_set.kind)
            if best is None or size < best[1]:
                out[case_set.kind] = (tuple(case), size)
    missing = set(registered_families()) - set(out)
    assert not missing, f"no shipped case set for registered families {missing}"
    return out


def test_hidden_test_isolation(tmp_path, monkeypatch):
    """Task 20 section 8 criterion 47: a candidate cannot read the hidden
    oracle or the hidden tests.

    Three surfaces, because "cannot read" is a claim about everything the
    candidate is handed:

    1. REGISTRATION. A Harness that will not keep its tests to the verifier
       cannot be registered. Read over the policy vocabulary the manifest
       schema declares, so the check is "exactly one value is admissible"
       rather than "this one value is refused".
    2. THE WORK DIR the agent starts in. Every problem ARI can load is
       materialized, and every file its scaffolding declares whose bytes were
       not seeded must be absent from the work dir -- the reference and,
       without this file naming them, the negative controls, which are the
       hidden tests for the problems that ship them.
    3. THE PROBLEM FILE the frozen driver hands the child. Its size must be
       the instance's own arrays plus a header, so there is no room in it for
       the answer -- measured against what the family generated rather than
       against a layout kept here.
    """
    from typing import get_args

    from ari.assurance.problems import registered_problems

    # 1. registration
    options = get_args(
        HarnessManifestV1.model_fields["hidden_test_policy"].annotation
    )
    assert len(options) >= 2, options
    admissible = {
        policy for policy in options
        if _gate_verdicts(policy)["hidden_test_isolation"]
    }
    assert admissible == {"verifier-only"}, admissible
    for policy in options:
        verdicts = _gate_verdicts(policy)
        assert verdicts["hidden_test_isolation"] == (policy in admissible)
        # The same policy settles the oracle/target gate; both must move
        # together or one of them is decorative.
        assert (
            verdicts["target_oracle_test_isolation"]
            == verdicts["hidden_test_isolation"]
        )
    assert not _gate_verdicts(None)["hidden_test_isolation"], (
        "a manifest that declares no hidden-test policy was admitted")

    # 2. the work dir
    checked = 0
    for revision in registered_problems():
        checked += _work_dir_hides_the_withheld(revision, tmp_path)
    # ... and one problem built here, carrying the optional scaffolding a
    # shipped problem may not declare -- the two negative controls, which are
    # the hidden tests for the problems that have them.
    monkeypatch.setenv("ARI_HARNESS_PROBLEMS", str(_synthetic_problem_root(tmp_path)))
    checked += _work_dir_hides_the_withheld("widget/v1@test", tmp_path)
    assert checked, "no problem was materialized; the loop is vacuous"

    # 3. the problem file the child reads
    from ari.assurance.native_perf_family import get_family

    cases = _smallest_cases_by_family()
    assert cases, "no performance family is registered; the loop is vacuous"
    for name, (case, elements) in sorted(cases.items()):
        family = get_family(name)
        instance = family.generate(case, 7)
        path = tmp_path / f"{name}-problem.bin"
        family.write(path, instance)
        surplus = path.stat().st_size - _instance_bytes(instance)
        assert 0 <= surplus <= 64, (
            f"{name} writes {surplus} bytes beyond the inputs it generated; "
            "the file the candidate reads holds something else")
        assert surplus < elements * 8, (
            f"{name} leaves room for the {elements}-element answer in the "
            "file the candidate is handed")


def _work_dir_hides_the_withheld(revision: str, tmp_path) -> int:
    """Materialize one problem and prove the work dir holds nothing withheld.

    The withheld set is DERIVED -- every file the scaffolding declares that
    ``materialize`` did not seed -- so the reference and the negative controls
    are covered without this file naming them, and a seventh scaffolding file
    added tomorrow is covered on the day it lands. Compared by BYTES rather
    than by name: a copy under another name is still the answer.
    """
    from ari.assurance.problems import (
        PROBLEM_STATEMENT_NAME,
        load_problem,
        materialize,
    )
    from ari.protocols.integrity import bytes_digest

    problem = load_problem(revision)
    work = tmp_path / "work" / revision.replace("/", "_").replace("@", "_")
    work.mkdir(parents=True)
    record = materialize(problem, work)
    seeded = {item["name"] for item in record["seeded"]}
    assert PROBLEM_STATEMENT_NAME in seeded, (revision, sorted(seeded))
    # By CONTENT, not by name: the seed candidate is deliberately seeded under
    # the scored name, so a name comparison would call it withheld and a byte
    # comparison would then find it and fail for the wrong reason.
    seeded_digests = {str(item["sha256"]) for item in record["seeded"]}
    withheld = {
        name: problem.path(name).read_bytes()
        for name in problem.definition.scaffolding.declared_files()
        if bytes_digest(problem.path(name).read_bytes()) not in seeded_digests
    }
    assert problem.definition.scaffolding.reference in withheld, (
        f"{revision} seeds its own reference into the work dir; the task is "
        "a copy rather than a measurement")
    assert record["withheld"] == [problem.definition.scaffolding.reference]
    present = {path.read_bytes() for path in work.rglob("*") if path.is_file()}
    assert present, revision
    for name, body in withheld.items():
        assert body not in present, (
            f"{revision}: {name} is readable from the work dir the agent "
            "starts in")
    return 1


def _synthetic_problem_root(tmp_path) -> Path:
    """A problem declaring every scaffolding file the schema allows."""
    root = tmp_path / "problems"
    (root / "widget").mkdir(parents=True)
    for name, body in (
        ("widget.h", "void widget(int n, const double *a, double *b);\n"),
        ("widget_main.c", "int main(void){return 0;}\n"),
        ("reference_widget.c", "/* the denominator */\n"),
        ("seed_widget.c", "/* correct, unoptimised */\n"),
        ("profiled_widget.c", "/* the counter-gated driver */\n"),
        ("slow_widget.c", "/* correct and slow */\n"),
        ("wrong_widget.c", "/* fast and wrong */\n"),
    ):
        (root / "widget" / name).write_text(body, encoding="utf-8")
    (root / "widget" / "problem.yaml").write_text(
        "schema_version: ari.harness-problem/v1\n"
        "id: widget\n"
        "revision: widget/v1@test\n"
        "family: widget\n"
        "entry_point: widget\n"
        "description: A problem used to test the isolation of hidden material.\n"
        "scaffolding:\n"
        "  contract_header: widget.h\n"
        "  driver: widget_main.c\n"
        "  reference: reference_widget.c\n"
        "  seed_candidate: seed_widget.c\n"
        "  profiled_driver: profiled_widget.c\n"
        "  negative_control_slow: slow_widget.c\n"
        "  negative_control_wrong: wrong_widget.c\n"
        "score_inputs: [candidate.c]\n"
        "case_set: widget-cases/v1@test\n"
        "axis: speedup\n"
        "denominator: competent_frozen\n"
        "goal: |\n"
        "  Make widget faster without changing what it computes.\n",
        encoding="utf-8",
    )
    return root
