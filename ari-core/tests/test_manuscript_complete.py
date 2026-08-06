from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ari.manuscript.briefs import build_section_briefs
from ari.manuscript.contracts import (
    ManuscriptAuthoringBindingV1,
    ManuscriptContextV1,
    ManuscriptReadinessReportV1,
    RepairBudgetV1,
    RequirementResultV1,
)
from ari.manuscript.coordinator import compile_manuscript
from ari.manuscript.profiles import generic_empirical_profile
from ari.manuscript.publication import build_publication_decision
from ari.manuscript.readiness import evaluate_readiness
from ari.manuscript.repair import (
    RepairExecutionResult,
    build_repair_plan,
    execute_repair_plan,
)
from ari.manuscript.segments import prepare_segment_execution
from ari.orchestrator.node import Node, NodeLabel, NodeStatus


D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
D4 = "sha256:" + "4" * 64


def _fixture_factory():
    path = (
        Path(__file__).parent
        / "fixtures"
        / "manuscript_complete"
        / "factory.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ari_test_manuscript_fixture_factory", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module while decorating the class.
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def test_baseline_fixture_catalog_is_complete() -> None:
    root = Path(__file__).parent / "fixtures" / "manuscript_complete"
    expected = {
        "mc_small_linear",
        "mc_large_context",
        "mc_negative_tree",
        "mc_tamper_stale",
        "mc_rqgm_assured",
        "mc_legacy_checkpoint",
        "mc_repairable_gap",
    }
    assert {
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "manifest.json").is_file()
    } == expected
    for fixture_id in expected:
        manifest = json.loads(
            (root / fixture_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["schema_version"] == "ari.manuscript-fixture/v1"
        assert manifest["fixture_id"] == fixture_id
        assert manifest["origin"].startswith("synthetic")
        assert manifest["generator_version"] == "manuscript-fixture-factory-v1"
        assert manifest["measurement_disclaimer"]
        assert manifest["properties"]
        assert manifest["expected_labels"]


def test_baseline_fixture_classes_are_executable(tmp_path: Path) -> None:
    factory = _fixture_factory()
    fixture_ids = {
        path.name
        for path in factory.FIXTURE_ROOT.iterdir()
        if path.is_dir() and (path / "manifest.json").is_file()
    }
    generated = {
        fixture_id: factory.materialize_fixture(tmp_path, fixture_id)
        for fixture_id in fixture_ids
    }
    assert set(generated) == fixture_ids
    for fixture_id, fixture in generated.items():
        marker = json.loads(
            (fixture.checkpoint / "SYNTHETIC_FIXTURE.json").read_text(
                encoding="utf-8"
            )
        )
        assert marker["fixture_id"] == fixture_id
        assert marker["generator_version"] == factory.GENERATOR_VERSION
        assert "test" in marker["measurement_disclaimer"].lower()


def test_executable_fixture_expectations(tmp_path: Path) -> None:
    factory = _fixture_factory()

    small = factory.materialize_fixture(tmp_path, "mc_small_linear")
    first = compile_manuscript(
        small.checkpoint,
        small.nodes,
        experiment_data=small.experiment_data,
        mode="enforce",
    )
    second = compile_manuscript(
        small.checkpoint,
        small.nodes,
        experiment_data=small.experiment_data,
        mode="enforce",
    )
    assert first.authoring_ready
    assert first.context.context_digest == second.context.context_digest

    large = factory.materialize_fixture(tmp_path, "mc_large_context")
    large_outcome = compile_manuscript(
        large.checkpoint,
        large.nodes,
        experiment_data=large.experiment_data,
        mode="audit",
        brief_character_budget=24_000,
    )
    assert len(large_outcome.context.methods) > 20
    assert len(large_outcome.context.related_work) == 13
    assert len(large_outcome.context.model_dump_json()) > 48_000
    assert len(large_outcome.briefs.briefs) > 9
    assert all(not brief.omitted_item_ids for brief in large_outcome.briefs.briefs)
    assert (
        set(large_outcome.omissions.inventory_item_ids)
        == set(large_outcome.omissions.included_item_ids)
        | {item.item_id for item in large_outcome.omissions.omissions}
    )

    negative = factory.materialize_fixture(tmp_path, "mc_negative_tree")
    negative_outcome = compile_manuscript(
        negative.checkpoint,
        negative.nodes,
        experiment_data=negative.experiment_data,
        mode="audit",
    )
    negative_ids = {
        item["node_id"] for item in negative_outcome.context.negative_results
    }
    assert len(negative_ids) == 4
    negative_evidence = {
        item.evidence_id
        for item in negative_outcome.context.evidence_records
        if item.node_id in negative_ids
    }
    assert negative_evidence
    assert all(
        negative_evidence.isdisjoint(brief.allowed_evidence_ids)
        for brief in negative_outcome.briefs.briefs
    )

    tamper = factory.materialize_fixture(tmp_path, "mc_tamper_stale")
    tamper_outcome = compile_manuscript(
        tamper.checkpoint,
        tamper.nodes,
        experiment_data=tamper.experiment_data,
        mode="audit",
    )
    assert "excluded" in {
        item.lane for item in tamper_outcome.context.evidence_records
    }
    assert {
        item.reason for item in tamper_outcome.omissions.omissions
    }.issuperset({"missing_on_disk", "digest_mismatch"})

    rqgm = factory.materialize_fixture(tmp_path, "mc_rqgm_assured")
    rqgm_outcome = compile_manuscript(
        rqgm.checkpoint,
        rqgm.nodes,
        experiment_data=rqgm.experiment_data,
        mode="enforce",
        assurance_mode="enforce",
        exploration_mode="ari_rqgm",
    )
    assert rqgm_outcome.context.subjects["scientific_winner"] == "node-debug"
    assert rqgm_outcome.context.subjects["publication_candidate"] is None
    assert "node-certified" in rqgm_outcome.context.subjects["certified_alternatives"]
    assert rqgm_outcome.readiness.publication_verdict == "blocked"

    legacy = factory.materialize_fixture(tmp_path, "mc_legacy_checkpoint")
    off = compile_manuscript(
        legacy.checkpoint,
        legacy.nodes,
        experiment_data=legacy.experiment_data,
        mode="off",
    )
    assert off.state == "disabled"
    assert not (legacy.checkpoint / ".ari-manuscript").exists()
    audit = compile_manuscript(
        legacy.checkpoint,
        legacy.nodes,
        experiment_data=legacy.experiment_data,
        mode="audit",
    )
    assert audit.readiness.counts["missing"] > 0

    repairable = factory.materialize_fixture(tmp_path, "mc_repairable_gap")
    repairable_outcome = compile_manuscript(
        repairable.checkpoint,
        repairable.nodes,
        experiment_data=repairable.experiment_data,
        mode="enforce",
        repair_policy="explicit",
    )
    missing = {
        item.requirement_id: item.resolver_kind
        for item in repairable_outcome.readiness.requirement_results
        if item.status == "missing"
    }
    assert missing["MC-CP-001"] == "baseline_comparison"
    assert missing["MC-RS-002"] == "repetition_or_uncertainty"
    assert missing["MC-AB-001"] == "ablation"


def _ready_checkpoint(tmp_path: Path) -> tuple[Path, list[Node], dict]:
    checkpoint = tmp_path / "run-ready"
    checkpoint.mkdir()
    _write(checkpoint / "experiment.md", "# Bound experiment\nMeasure throughput.")
    _write(checkpoint / "measurement.json", {"throughput": 101.0})
    node = Node(
        id="node-root",
        parent_id=None,
        depth=0,
        status=NodeStatus.SUCCESS,
        artifacts=[{"path": "measurement.json", "kind": "measurement"}],
        metrics={"throughput": 101.0, "_scientific_score": 0.9},
        has_real_data=True,
        label=NodeLabel.DRAFT,
        original_direction="Execute the frozen throughput protocol.",
    )
    _write(
        checkpoint / "tree.json",
        {
            "run_id": "run-ready",
            "experiment_file": str(checkpoint / "experiment.md"),
            "nodes": [node.to_dict()],
        },
    )
    _write(
        checkpoint / "nodes_tree.json",
        {"run_id": "run-ready", "nodes": [node.to_dict()]},
    )
    _write(
        checkpoint / "idea.json",
        {
            "research_question": "Does the method improve throughput?",
            "ideas": [
                {
                    "title": "Bound throughput study",
                    "description": "Does the method improve throughput?",
                    "hypothesis": "The method increases throughput.",
                    "falsification_conditions": ["Throughput does not increase."],
                    "experiment_plan": "Run the fixed workload and report throughput.",
                    "contributions": ["A measured throughput result."],
                }
            ],
        },
    )
    _write(
        checkpoint / "science_data.json",
        {
            "schema_version": "ari.science-data/v1",
            "raw": {
                "configurations": [{"configuration_id": "cfg-1"}],
                "measurement_records": [
                    {"run_id": "measurement-1", "throughput": 101.0}
                ],
                "claims": [{"claim_id": "claim-1"}],
            },
            "interpretation": {
                "status": "ok",
                "experiment_context": {"hardware": {"cpu": "test-cpu"}},
            },
        },
    )
    _write(
        checkpoint / "related_refs.json",
        {
            "records": [
                {
                    "record_id": "ref-1",
                    "title": "Prior throughput study",
                    "year": 2024,
                    "citation_key": "Prior2024",
                    "abstract": "A comparable prior study.",
                }
            ]
        },
    )
    _write(
        checkpoint / "ear_manifest.json",
        {
            "environment": {"cpu": "test-cpu"},
            "commands": ["python reproduce.py"],
            "has_environment": True,
            "has_reproduce_sh": True,
        },
    )
    _write(
        checkpoint / "verified_context.json",
        {"limitations": ["The test uses one synthetic workload."]},
    )
    data = {
        "goal": "Does the method improve throughput?",
        "topic": "throughput",
        "file": str(checkpoint / "experiment.md"),
    }
    return checkpoint, [node], data


def test_off_is_exact_no_artifact_identity(tmp_path: Path) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="off"
    )
    assert outcome.state == "disabled"
    assert not (checkpoint / ".ari-manuscript").exists()


def test_default_cli_import_does_not_load_manuscript_domain() -> None:
    environment = dict(os.environ)
    core_root = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (core_root, environment.get("PYTHONPATH", ""))
        if item
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import ari.cli; "
                "assert not any(n == 'ari.manuscript' or "
                "n.startswith('ari.manuscript.') for n in sys.modules)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_auto_repair_configuration_is_rejected_outside_enforce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ari.config import ARIConfig, apply_manuscript_env_overrides

    with pytest.raises(ValueError, match="requires manuscript.mode=enforce"):
        ARIConfig.model_validate(
            {"manuscript": {"mode": "audit", "repair": {"policy": "auto"}}}
        )

    cfg = ARIConfig()
    monkeypatch.setenv("ARI_MANUSCRIPT_MODE", "off")
    monkeypatch.setenv("ARI_MANUSCRIPT_REPAIR_POLICY", "auto")
    with pytest.raises(ValueError, match="requires manuscript.mode=enforce"):
        apply_manuscript_env_overrides(cfg)


def test_state_projection_is_chain_bound_and_recovers_one_commit_window(
    tmp_path: Path,
) -> None:
    from ari.manuscript.state import ManuscriptStateStore

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="enforce"
    )
    assert outcome.authoring_ready
    store = ManuscriptStateStore(checkpoint)
    prior = store.state_path.read_bytes()
    store.transition(
        run_id=outcome.readiness.run_id,
        attempt=str(outcome.attempt_id),
        to_state="authoring",
        reason_code="test_authoring_started",
    )
    store.state_path.write_bytes(prior)
    assert store.read_state()["state"] == "authoring"

    tampered = store.read_state()
    tampered["sequence"] = 999
    store.state_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from transition chain"):
        store.read_state()


def test_compile_is_deterministic_and_tamper_evident(tmp_path: Path) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    first = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="enforce"
    )
    second = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="enforce"
    )
    assert first.attempt_id == second.attempt_id
    assert first.context.context_digest == second.context.context_digest
    assert first.readiness.readiness_digest == second.readiness.readiness_digest
    assert first.authoring_ready
    assert first.readiness.authoring_verdict == "ready"

    context_path = (
        checkpoint
        / ".ari-manuscript"
        / "attempts"
        / str(first.attempt_id)
        / "context.json"
    )
    document = json.loads(context_path.read_text(encoding="utf-8"))
    document["limitations"] = ["tampered"]
    with pytest.raises(ValueError, match="context_digest"):
        ManuscriptContextV1.model_validate(document)


def test_source_symlink_is_not_resolved_into_admissible_evidence(
    tmp_path: Path,
) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    measurement = checkpoint / "measurement.json"
    target = checkpoint / "real-measurement.json"
    measurement.rename(target)
    measurement.symlink_to(target.name)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="audit"
    )
    artifact = next(
        item
        for item in outcome.context.evidence_records
        if item.node_id == "node-root"
    )
    assert artifact.lane == "excluded"
    assert "artifact_invalid" in artifact.reason_codes
    assert "unsafe_path" in {
        item.reason for item in outcome.omissions.omissions
    }


def test_negative_nodes_are_visible_and_never_positive_evidence(tmp_path: Path) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    failed = Node(
        id="node-failed",
        parent_id="node-root",
        depth=1,
        status=NodeStatus.FAILED,
        label=NodeLabel.DEBUG,
        ancestor_ids=["node-root"],
        error_log="measurement process failed",
    )
    nodes[0].children.append(failed.id)
    nodes.append(failed)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="audit"
    )
    record = next(
        item for item in outcome.context.evidence_records if item.node_id == failed.id
    )
    assert record.lane == "contextual_negative"
    assert not record.claim_eligible_fact
    assert any(item["node_id"] == failed.id for item in outcome.context.negative_results)
    assert any(
        record.evidence_id in brief.contextual_negative_ids
        for brief in outcome.briefs.briefs
    )


def test_required_brief_items_split_without_omission(tmp_path: Path) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="audit"
    )
    payload = outcome.context.digest_payload()
    payload["related_work"] = tuple(
        {
            "reference_id": f"ref-{index:03d}",
            "title": "T" * 80,
            "abstract": "A" * 120,
        }
        for index in range(40)
    )
    context = ManuscriptContextV1.create(**payload)
    readiness = evaluate_readiness(
        generic_empirical_profile(), context, outcome.omissions
    )
    bundle = build_section_briefs(
        generic_empirical_profile(), context, readiness, character_budget=2_000
    )
    related = [item for item in bundle.briefs if item.section_id.startswith("related-work")]
    assert len(related) > 1
    assert all(not item.omitted_item_ids for item in bundle.briefs)
    assert sum(len(item.content_items) for item in related) == 40


def test_segment_record_reuses_only_fresh_outputs(tmp_path: Path) -> None:
    checkpoint = tmp_path / "segment-run"
    checkpoint.mkdir()
    _write(checkpoint / "tree.json", {"run_id": "segment-run", "nodes": []})
    _write(checkpoint / "source.json", {"value": 1})
    workflow = checkpoint / "workflow.yaml"
    _write(
        workflow,
        """pipeline:
  - stage: make_evidence
    segment: evidence
    enabled: true
    outputs:
      file: '{{checkpoint_dir}}/evidence.json'
  - stage: write_paper
    segment: authoring
    enabled: true
    outputs:
      file: '{{checkpoint_dir}}/full_paper.tex'
  - stage: verify
    segment: verification
    enabled: true
    outputs:
      file: '{{checkpoint_dir}}/paper_build.json'
""",
    )
    stages = json.loads(json.dumps([]))
    first = prepare_segment_execution(
        checkpoint, workflow, stages, {"evidence"}
    )
    assert not first.reusable
    _write(checkpoint / "evidence.json", {"evidence": True})
    record = first.finish(status="completed")
    assert record.segments == ("evidence",)

    second = prepare_segment_execution(
        checkpoint, workflow, stages, {"evidence"}
    )
    assert second.reusable
    _write(checkpoint / "evidence.json", {"evidence": "tampered"})
    third = prepare_segment_execution(
        checkpoint, workflow, stages, {"evidence"}
    )
    assert not third.reusable


def _missing_readiness(resolver: str = "baseline_comparison") -> ManuscriptReadinessReportV1:
    result = RequirementResultV1(
        requirement_id="MC-TEST-001",
        applicable=True,
        status="missing",
        reason_code="test_gap",
        authoring_blocking=True,
        publication_blocking=True,
        resolver_kind=resolver,
        evaluator_version="manuscript-evaluator-v1",
    )
    return ManuscriptReadinessReportV1.create(
        run_id="run-repair",
        profile_digest=D1,
        context_digest=D2,
        evaluator_version="manuscript-evaluator-v1",
        requirement_results=(result,),
        authoring_verdict="repair_required",
        publication_verdict="blocked",
        counts={
            "satisfied": 0,
            "not_applicable": 0,
            "unavailable": 0,
            "missing": 1,
        },
    )


def test_repair_identity_and_budget_are_fixed() -> None:
    readiness = _missing_readiness()
    exhausted = build_repair_plan(
        readiness,
        policy="explicit",
        budget=RepairBudgetV1(
            max_rounds=1, max_new_nodes=0, max_experiment_runs=0, max_llm_calls=0
        ),
    )
    assert exhausted.plan_digest == build_repair_plan(
        readiness,
        policy="explicit",
        budget=exhausted.budget,
    ).plan_digest
    called = False

    def executor(request, remaining):
        nonlocal called
        called = True
        return RepairExecutionResult(request.request_id, "executed", {})

    results = execute_repair_plan(
        exhausted, executors={"baseline_comparison": executor}
    )
    assert results[0].status == "exhausted"
    assert not called

    admitted = build_repair_plan(
        readiness,
        policy="explicit",
        budget=RepairBudgetV1(
            max_rounds=1, max_new_nodes=1, max_experiment_runs=1, max_llm_calls=1
        ),
    )

    def bounded(request, remaining):
        return RepairExecutionResult(
            request.request_id,
            "executed",
            {"new_nodes": 1, "experiment_runs": 1, "llm_calls": 1},
        )

    usage: dict[str, int | float] = {}
    results = execute_repair_plan(
        admitted,
        executors={"baseline_comparison": bounded},
        used_budget=usage,
    )
    assert results[0].status == "executed"
    assert usage == {
        "new_nodes": 1,
        "experiment_runs": 1,
        "llm_calls": 1,
        "resource_units": 0.0,
    }

    resource_limited = build_repair_plan(
        readiness,
        policy="explicit",
        budget=RepairBudgetV1(
            max_rounds=1,
            max_new_nodes=1,
            max_experiment_runs=1,
            max_llm_calls=1,
            max_resource_units=0.5,
        ),
    )

    def resource_overrun(request, remaining):
        return RepairExecutionResult(
            request.request_id,
            "executed",
            {
                "new_nodes": 1,
                "experiment_runs": 1,
                "llm_calls": 1,
                "resource_units": 0.75,
            },
        )

    with pytest.raises(ValueError, match="request budget"):
        execute_repair_plan(
            resource_limited,
            executors={"baseline_comparison": resource_overrun},
        )


def test_repair_commit_records_are_digest_bound() -> None:
    from ari.manuscript.contracts import (
        AutoRepairRoundResultV1,
        ManuscriptAutoRepairRoundV1,
        ManuscriptRepairTransactionV1,
        RepairBudgetUsageV1,
    )

    transaction = ManuscriptRepairTransactionV1.create(
        run_id="run-repair",
        request_id="repair-test-001",
        request_digest=D1,
        source_context_digest=D2,
        authority_digest=D3,
        status="executed",
        details={"new_nodes": 1, "resource_units": 0.5},
    )
    transaction_payload = transaction.model_dump(mode="json")
    transaction_payload["details"]["new_nodes"] = 0
    with pytest.raises(ValueError, match="transaction_digest"):
        ManuscriptRepairTransactionV1.model_validate(transaction_payload)

    round_record = ManuscriptAutoRepairRoundV1.create(
        round=0,
        plan_digest=D4,
        source_context_digest=D2,
        request_ids=(transaction.request_id,),
        transaction_digests=(transaction.transaction_digest,),
        results=(
            AutoRepairRoundResultV1(
                request_id=transaction.request_id,
                status="executed",
                details=transaction.details,
            ),
        ),
        used_budget=RepairBudgetUsageV1(new_nodes=1, resource_units=0.5),
    )
    round_payload = round_record.model_dump(mode="json")
    round_payload["used_budget"]["resource_units"] = 0.0
    with pytest.raises(ValueError, match="round_digest"):
        ManuscriptAutoRepairRoundV1.model_validate(round_payload)


def test_auto_repair_resume_does_not_repeat_committed_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    (checkpoint / "related_refs.json").unlink()
    for name, value in {
        "ARI_MANUSCRIPT_RUNTIME_MODE": "enforce",
        "ARI_MANUSCRIPT_PROFILE": "generic_empirical_v1",
        "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE": "auto",
        "ARI_MANUSCRIPT_ASSURANCE_MODE": "off",
        "ARI_MANUSCRIPT_EXPLORATION_MODE": "simple_bfts",
        "ARI_MANUSCRIPT_PAPER_MODE": "linear",
        "ARI_MANUSCRIPT_BRIEF_CHARACTER_BUDGET": "24000",
        "ARI_MANUSCRIPT_MAX_ROUNDS": "2",
        "ARI_MANUSCRIPT_MAX_NEW_NODES": "1",
        "ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS": "1",
        "ARI_MANUSCRIPT_MAX_LLM_CALLS": "1",
    }.items():
        monkeypatch.setenv(name, value)

    calls = 0

    def literature(request, remaining):
        nonlocal calls
        calls += 1
        return RepairExecutionResult(
            request.request_id,
            "executed",
            {"new_nodes": 0, "experiment_runs": 0, "llm_calls": 1},
        )

    rebuilds = 0

    def interrupted_rebuild():
        nonlocal rebuilds
        rebuilds += 1
        if rebuilds == 1:
            raise RuntimeError("injected interruption after committed repair")
        _write(
            checkpoint / "related_refs.json",
            {"records": [{"record_id": "ref-resumed", "title": "Recovered prior work"}]},
        )

    from ari.manuscript.runtime import run_runtime_auto_repair

    with pytest.raises(RuntimeError, match="injected interruption"):
        run_runtime_auto_repair(
            checkpoint,
            nodes,
            experiment_data=data,
            evidence_rebuilder=interrupted_rebuild,
            executors={"literature_search": literature},
        )
    assert calls == 1
    assert list(
        (checkpoint / ".ari-manuscript" / "repair-transactions").glob("*.json")
    )

    resumed = run_runtime_auto_repair(
        checkpoint,
        nodes,
        experiment_data=data,
        evidence_rebuilder=interrupted_rebuild,
        executors={"literature_search": literature},
    )
    assert calls == 1
    assert resumed.outcome.authoring_ready
    assert resumed.termination_reason == "authoring_ready"


@pytest.mark.parametrize(
    ("executor_status", "expected_reason"),
    (
        ("executed", "no_progress_cycle"),
        ("human_required", "human_decision_required"),
    ),
)
def test_auto_repair_stops_on_no_progress_or_human_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    executor_status: str,
    expected_reason: str,
) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    (checkpoint / "related_refs.json").unlink()
    for name, value in {
        "ARI_MANUSCRIPT_RUNTIME_MODE": "enforce",
        "ARI_MANUSCRIPT_PROFILE": "generic_empirical_v1",
        "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE": "auto",
        "ARI_MANUSCRIPT_ASSURANCE_MODE": "off",
        "ARI_MANUSCRIPT_EXPLORATION_MODE": "simple_bfts",
        "ARI_MANUSCRIPT_PAPER_MODE": "linear",
        "ARI_MANUSCRIPT_BRIEF_CHARACTER_BUDGET": "24000",
        "ARI_MANUSCRIPT_MAX_ROUNDS": "2",
        "ARI_MANUSCRIPT_MAX_NEW_NODES": "0",
        "ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS": "0",
        "ARI_MANUSCRIPT_MAX_LLM_CALLS": "1",
    }.items():
        monkeypatch.setenv(name, value)

    def literature(request, _remaining):
        return RepairExecutionResult(
            request.request_id,
            executor_status,
            {
                "new_nodes": 0,
                "experiment_runs": 0,
                "llm_calls": int(executor_status == "executed"),
            },
        )

    from ari.manuscript.runtime import run_runtime_auto_repair

    result = run_runtime_auto_repair(
        checkpoint,
        nodes,
        experiment_data=data,
        evidence_rebuilder=lambda: None,
        executors={"literature_search": literature},
    )
    assert not result.outcome.authoring_ready
    assert result.termination_reason == expected_reason


def test_recorded_literature_repair_resumes_without_provider(
    tmp_path: Path,
) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="audit"
    )
    from ari.config import auto_config
    from ari.manuscript.authority import capture_repair_authority
    from ari.manuscript.contracts import ResearchRepairRequestV1
    from ari.manuscript.repair import authority_digest

    authority = capture_repair_authority(checkpoint, run_id="run-ready")
    request = ResearchRepairRequestV1.create(
        request_id="repair-literature-cache",
        source_context_digest=outcome.context.context_digest,
        requirement_ids=("MC-RW-001",),
        kind="literature_search",
        fixed_variables={"topic": data["goal"]},
        allowed_changes=("recorded_retrieval_revision",),
        required_capability_ids=("literature-retrieval",),
        preconditions=("source_context_is_current", "authority_digest_matches"),
        success_predicate_id="recorded-retrieval-nonempty-v1",
        stop_conditions=("request_budget_exhausted",),
        budget=RepairBudgetV1(max_rounds=1, max_llm_calls=1),
        authority_digest=authority_digest(authority),
    )

    class MCP:
        def __init__(self):
            self.calls = 0

        def call_tool(self, name, arguments):
            self.calls += 1
            assert name == "survey"
            return {
                "result": json.dumps(
                    {
                        "papers": [
                            {
                                "record_id": "ref-repair",
                                "title": "Recorded repair reference",
                            }
                        ]
                    }
                )
            }

    class Agent:
        def __init__(self):
            self.mcp = MCP()

    agent = Agent()
    from ari.cli.manuscript_repair_runtime import build_research_repair_executors

    executors = build_research_repair_executors(
        auto_config(), object(), agent, nodes, data, checkpoint, "run-ready"
    )
    first = executors["literature_search"](
        request, RepairBudgetV1(max_rounds=1, max_llm_calls=1)
    )
    assert first.status == "executed"
    assert agent.mcp.calls == 1
    agent.mcp = None
    resumed = executors["literature_search"](
        request, RepairBudgetV1(max_rounds=1, max_llm_calls=1)
    )
    assert resumed.status == "executed"
    assert resumed.details["cache_reuse"] is True
    document = json.loads((checkpoint / "related_refs.json").read_text(encoding="utf-8"))
    revision = document["retrieval_revisions"][0]
    assert revision["request_digest"] == request.request_digest
    assert revision["semantic_capability_id"] == "ari.literature.search/v1"
    assert revision["parameters"] == {"topic": data["goal"], "max_papers": 12}


def test_research_repair_node_uses_normal_loop_and_rqgm_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="audit", repair_policy="explicit"
    )
    from ari.config import auto_config
    from ari.manuscript.authority import capture_repair_authority
    from ari.manuscript.contracts import ResearchRepairRequestV1
    from ari.manuscript.repair import authority_digest

    cfg = auto_config()
    authority = capture_repair_authority(checkpoint, run_id="run-ready")
    request = ResearchRepairRequestV1.create(
        request_id="repair-test-lineage",
        source_context_digest=outcome.context.context_digest,
        requirement_ids=("MC-CP-001",),
        kind="baseline_comparison",
        fixed_variables={"dataset": "fixed"},
        allowed_changes=("method_or_baseline_only",),
        required_capability_ids=("research-execution",),
        preconditions=("source_context_is_current", "authority_digest_matches"),
        success_predicate_id="comparable-measurement-completed-v1",
        stop_conditions=("request_budget_exhausted",),
        budget=RepairBudgetV1(
            max_rounds=1, max_new_nodes=1, max_experiment_runs=1, max_llm_calls=1
        ),
        authority_digest=authority_digest(authority),
    )

    class RQGM:
        def __init__(self):
            self.stamped = []
            self.recorded = []

        def stamp_node_producer(self, node):
            self.stamped.append(node.id)
            node.producer_component_id = "component-generator-v1"
            return True

        def record_expansion_proposal(self, parent, node):
            self.recorded.append((parent.id, node.id))

    class BFTS:
        def __init__(self):
            self.rqgm = RQGM()

    class Agent:
        mcp = None

    observed = {}
    loop_calls = 0

    def fake_loop(
        loop_cfg,
        bfts,
        agent,
        pending,
        all_nodes,
        experiment_data,
        checkpoint_dir,
        run_id,
        total_processed=0,
    ):
        nonlocal loop_calls
        loop_calls += 1
        observed["max_total_nodes"] = loop_cfg.bfts.max_total_nodes
        observed["pending"] = list(pending)
        if loop_calls == 1:
            raise RuntimeError("injected interruption after node materialization")
        pending[0].mark_success()
        return total_processed + 1

    monkeypatch.setattr("ari.cli.bfts_loop._run_loop", fake_loop)
    bfts = BFTS()
    original_max = cfg.bfts.max_total_nodes
    from ari.cli.manuscript_repair_runtime import build_research_repair_executors

    executors = build_research_repair_executors(
        cfg, bfts, Agent(), nodes, data, checkpoint, "run-ready"
    )
    remaining = RepairBudgetV1(
        max_rounds=1, max_new_nodes=1, max_experiment_runs=1, max_llm_calls=1
    )
    with pytest.raises(RuntimeError, match="node materialization"):
        executors["baseline_comparison"](request, remaining)
    persisted_tree = json.loads((checkpoint / "tree.json").read_text(encoding="utf-8"))
    assert any(
        item.get("repair_request_id") == request.request_id
        for item in persisted_tree["nodes"]
    )
    result = executors["baseline_comparison"](request, remaining)
    repair_node = observed["pending"][0]
    assert result.status == "executed"
    assert repair_node.repair_request_id == request.request_id
    assert repair_node.repair_requirement_ids == ["MC-CP-001"]
    assert repair_node.repair_context_digest == outcome.context.context_digest
    assert repair_node.repair_allowed_changes == ["method_or_baseline_only"]
    assert bfts.rqgm.stamped == [repair_node.id]
    assert bfts.rqgm.recorded == [("node-root", repair_node.id)]
    assert loop_calls == 2
    assert observed["max_total_nodes"] == len(nodes)
    assert cfg.bfts.max_total_nodes == original_max


def _ready_report(*, publication_ready: bool = True) -> ManuscriptReadinessReportV1:
    result = RequirementResultV1(
        requirement_id="MC-TEST-READY",
        applicable=True,
        status="satisfied" if publication_ready else "missing",
        reason_code="evidence_present" if publication_ready else "missing",
        authoring_blocking=False,
        publication_blocking=True,
        resolver_kind=None if publication_ready else "projection_rebuild",
        evaluator_version="manuscript-evaluator-v1",
    )
    return ManuscriptReadinessReportV1.create(
        run_id="run-publication",
        profile_digest=D1,
        context_digest=D2,
        evaluator_version="manuscript-evaluator-v1",
        requirement_results=(result,),
        authoring_verdict="ready",
        publication_verdict="ready" if publication_ready else "blocked",
        counts={
            "satisfied": int(publication_ready),
            "not_applicable": 0,
            "unavailable": 0,
            "missing": int(not publication_ready),
        },
    )


def test_publication_decision_is_logical_and() -> None:
    readiness = _ready_report()
    binding = ManuscriptAuthoringBindingV1.create(
        run_id="run-publication",
        attempt_id="mca-test",
        source_snapshot_digest=D3,
        profile_digest=D1,
        context_digest=D2,
        readiness_digest=readiness.readiness_digest,
        brief_bundle_digest=D4,
        paper_mode="linear",
        backend_version="linear-manuscript-v1",
        target_build_id="paper-run-publication",
        target_build_revision=0,
    )
    for failed in (None, "claim", "compile", "reproduction", "freshness"):
        decision = build_publication_decision(
            run_id="run-publication",
            attempt_id="mca-test",
            paper_build_digest=D1,
            binding=binding,
            readiness=readiness,
            claim_gate_passed=failed != "claim",
            claim_gate_digest=D2,
            assurance_required=False,
            assurance_passed=None,
            compile_passed=failed != "compile",
            compile_digest=D3,
            reproduction_passed=failed != "reproduction",
            reproduction_digest=D4,
            inputs_fresh=failed != "freshness",
        )
        assert decision.decision == ("publishable" if failed is None else "blocked")
        assert len(decision.subverdicts) == 6

    not_ready = _ready_report(publication_ready=False)
    not_ready_binding = ManuscriptAuthoringBindingV1.create(
        run_id="run-publication",
        attempt_id="mca-test",
        source_snapshot_digest=D3,
        profile_digest=D1,
        context_digest=D2,
        readiness_digest=not_ready.readiness_digest,
        brief_bundle_digest=D4,
        paper_mode="linear",
        backend_version="linear-manuscript-v1",
        target_build_id="paper-run-publication",
        target_build_revision=0,
    )
    readiness_failure = build_publication_decision(
        run_id="run-publication",
        attempt_id="mca-test",
        paper_build_digest=D1,
        binding=not_ready_binding,
        readiness=not_ready,
        claim_gate_passed=True,
        claim_gate_digest=D2,
        assurance_required=False,
        assurance_passed=None,
        compile_passed=True,
        compile_digest=D3,
        reproduction_passed=True,
        reproduction_digest=D4,
        inputs_fresh=True,
    )
    assert readiness_failure.decision == "blocked"
    assert next(
        item for item in readiness_failure.subverdicts
        if item.gate == "manuscript_readiness"
    ).status == "fail"

    assurance_failure = build_publication_decision(
        run_id="run-publication",
        attempt_id="mca-test",
        paper_build_digest=D1,
        binding=binding,
        readiness=readiness,
        claim_gate_passed=True,
        claim_gate_digest=D2,
        assurance_required=True,
        assurance_passed=False,
        assurance_artifact_digests=(),
        compile_passed=True,
        compile_digest=D3,
        reproduction_passed=True,
        reproduction_digest=D4,
        inputs_fresh=True,
    )
    assert assurance_failure.decision == "blocked"
    assert next(
        item for item in assurance_failure.subverdicts
        if item.gate == "assurance"
    ).status == "fail"


def _materialize_publishable_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exploration_mode: str = "simple_bfts",
    paper_mode: str = "linear",
    include_disclosures: bool = True,
    include_contextual_negative: bool = False,
    final_tex_extra: str = "",
):
    from ari.manuscript.digest import file_digest
    from ari.manuscript.state import ManuscriptStateStore
    from ari.paper_contract import (
        PaperArtifactV1,
        PaperBuildV1,
        PaperCompileV1,
        PaperGateSummaryV1,
        PaperNumericCoverageV1,
        PaperRevisionV1,
    )

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    if include_contextual_negative:
        negative = {
            "id": "node-contextual-negative",
            "parent_id": "node-root",
            "ancestor_ids": ["node-root"],
            "depth": 1,
            "status": "failed",
            "label": "debug",
            "has_real_data": False,
            "metrics": {},
            "artifacts": [],
            "error_log": "injected negative result",
        }
        nodes.append(negative)
        for name in ("tree.json", "nodes_tree.json"):
            payload = json.loads((checkpoint / name).read_text(encoding="utf-8"))
            payload["nodes"] = [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in nodes
            ]
            _write(checkpoint / name, payload)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="enforce",
        exploration_mode=exploration_mode,
        paper_mode=paper_mode,
    )
    assert outcome.authoring_ready and outcome.authoring_binding is not None
    attempt = checkpoint / ".ari-manuscript" / "attempts" / str(outcome.attempt_id)

    _write(checkpoint / "paper_inputs" / "figures.json", {"figures": []})
    _write(checkpoint / "paper" / "revision-00.tex", "draft")
    disclosures = tuple(sorted({
        item
        for brief in outcome.briefs.briefs
        for item in brief.required_disclosures
    }))
    final_tex = "final\n"
    if include_disclosures:
        final_tex += "\n".join(disclosures) + "\n"
    final_tex += final_tex_extra
    _write(checkpoint / "full_paper.tex", final_tex)
    _write(checkpoint / "refs.bib", "@misc{Prior2024}")
    _write(checkpoint / "logs" / "stdout.log", "ok")
    _write(checkpoint / "logs" / "stderr.log", "")
    (checkpoint / "full_paper.pdf").write_bytes(b"%PDF-1.4\nsynthetic\n")
    _write(
        checkpoint / "ors_phase1.json",
        {"executed": True, "exit_code": 0, "missing": []},
    )

    def artifact(role: str, relative: str, media_type: str = "application/json"):
        digest, size = file_digest(checkpoint / relative)
        return PaperArtifactV1(
            role=role,
            relative_path=relative,
            digest=digest,
            media_type=media_type,
            size_bytes=size,
        )

    input_artifacts = (
        artifact("science-data", "science_data.json"),
        artifact("figure-batch", "paper_inputs/figures.json"),
        artifact("retrieval-records", "related_refs.json"),
        artifact("ear-manifest", "ear_manifest.json"),
        artifact(
            "manuscript-profile",
            f".ari-manuscript/attempts/{outcome.attempt_id}/requirement_profile.json",
        ),
        artifact(
            "manuscript-context",
            f".ari-manuscript/attempts/{outcome.attempt_id}/context.json",
        ),
        artifact(
            "manuscript-readiness",
            f".ari-manuscript/attempts/{outcome.attempt_id}/readiness.json",
        ),
        artifact(
            "section-briefs",
            f".ari-manuscript/attempts/{outcome.attempt_id}/section_briefs.json",
        ),
        artifact(
            "manuscript-authoring-binding",
            f".ari-manuscript/attempts/{outcome.attempt_id}/authoring_binding.json",
        ),
    )
    draft = artifact("draft-tex", "paper/revision-00.tex", "text/x-tex")
    bib = artifact("bibtex", "refs.bib", "application/x-bibtex")
    final_tex = artifact("final-tex", "full_paper.tex", "text/x-tex")
    pdf = artifact("pdf", "full_paper.pdf", "application/pdf")
    compile_record = PaperCompileV1.create(
        status="completed",
        commands=(("pdflatex", "-no-shell-escape", "full_paper.tex"),),
        execution_identities=(D1,),
        log_artifacts=(
            artifact("compile-stdout", "logs/stdout.log", "text/plain"),
            artifact("compile-stderr", "logs/stderr.log", "text/plain"),
        ),
        pdf_artifact=pdf,
        environment_digest=D2,
    )
    revision = PaperRevisionV1.create(
        revision=0,
        reason="initial",
        tex_artifact=draft,
        bib_artifact=bib,
        math_digest=D3,
    )
    build = PaperBuildV1.create(
        build_id=outcome.authoring_binding.target_build_id,
        run_id=outcome.authoring_binding.run_id,
        build_revision=0,
        status="finalized",
        input_artifacts=input_artifacts,
        venue_id="test-venue",
        venue_version="1",
        template_digest=D1,
        rubric_id="test-rubric",
        rubric_version="1",
        rubric_digest=D2,
        ear_digest=input_artifacts[3].digest,
        revisions=(revision,),
        compile=compile_record,
        gate=PaperGateSummaryV1(
            mode="strict",
            status="pass",
            blocking_error_count=0,
            report_digest=D4,
        ),
        numeric_coverage=PaperNumericCoverageV1(
            result_mentions=0,
            linked_mentions=0,
            excluded_mentions=0,
            unresolved_anchors=0,
            uncovered_mentions=0,
        ),
        final_artifacts=(final_tex, bib, pdf),
    )
    _write(checkpoint / "paper_build.json", build.model_dump(mode="json"))
    environment = {
        "ARI_MANUSCRIPT_RUNTIME_MODE": "enforce",
        "ARI_MANUSCRIPT_PROFILE_PATH": str(attempt / "requirement_profile.json"),
        "ARI_MANUSCRIPT_CONTEXT_PATH": str(attempt / "context.json"),
        "ARI_MANUSCRIPT_READINESS_PATH": str(attempt / "readiness.json"),
        "ARI_MANUSCRIPT_BRIEFS_PATH": str(attempt / "section_briefs.json"),
        "ARI_MANUSCRIPT_BINDING_PATH": str(attempt / "authoring_binding.json"),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    store = ManuscriptStateStore(checkpoint)
    store.transition(
        run_id=build.run_id,
        attempt=str(outcome.attempt_id),
        to_state="authoring",
        reason_code="test_authoring_started",
    )
    store.transition(
        run_id=build.run_id,
        attempt=str(outcome.attempt_id),
        to_state="authored",
        reason_code="test_authoring_completed",
        artifact_digests=(build.build_digest,),
    )
    return checkpoint, outcome, build


def test_publication_finalizer_and_lock_recheck_exact_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ari.manuscript.runtime import (
        finalize_runtime_publication,
        lock_runtime_publication,
    )

    checkpoint, outcome, build = _materialize_publishable_build(
        tmp_path, monkeypatch
    )
    decision = finalize_runtime_publication(checkpoint)
    assert decision.decision == "publishable"
    assert decision.paper_build_digest == build.build_digest
    lock = lock_runtime_publication(checkpoint)
    assert lock.decision_digest == decision.decision_digest
    assert lock.pdf_digest == next(
        item.digest for item in build.final_artifacts if item.role == "pdf"
    )

    # A post-decision source mutation invalidates even an already-created lock;
    # re-locking must re-hash the exact source set and fail closed.
    _write(checkpoint / "measurement.json", {"throughput": 999.0})
    with pytest.raises(ValueError, match="inputs changed"):
        lock_runtime_publication(checkpoint)


@pytest.mark.parametrize(
    ("fault", "failed_gate"),
    (
        ("missing_pdf", "freshness"),
        ("missing_reproduction", "reproduction"),
        ("missing_disclosure", "claim_evidence"),
        ("contextual_negative_support", "claim_evidence"),
    ),
)
def test_publication_failure_injection_matrix_blocks_before_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    failed_gate: str,
) -> None:
    from ari.manuscript.runtime import (
        finalize_runtime_publication,
        lock_runtime_publication,
    )

    case_root = tmp_path / fault
    case_root.mkdir()
    negative_id = "node-evidence:node-contextual-negative"
    checkpoint, outcome, _build = _materialize_publishable_build(
        case_root,
        monkeypatch,
        include_disclosures=fault != "missing_disclosure",
        include_contextual_negative=fault == "contextual_negative_support",
        final_tex_extra=(
            f"The headline claim is supported by {negative_id}.\n"
            if fault == "contextual_negative_support"
            else ""
        ),
    )
    if fault == "missing_pdf":
        (checkpoint / "full_paper.pdf").unlink()
    elif fault == "missing_reproduction":
        (checkpoint / "ors_phase1.json").unlink()

    decision = finalize_runtime_publication(checkpoint)
    assert decision.decision == "blocked"
    assert next(
        item for item in decision.subverdicts if item.gate == failed_gate
    ).status == "fail"
    with pytest.raises(ValueError, match="blocked publication decision"):
        lock_runtime_publication(checkpoint)
    attempt = (
        checkpoint
        / ".ari-manuscript"
        / "attempts"
        / str(outcome.attempt_id)
    )
    assert not (attempt / "publication_lock.json").exists()


def test_malformed_manuscript_contract_blocks_publication_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ari.manuscript.runtime import finalize_runtime_publication

    checkpoint, _outcome, _build = _materialize_publishable_build(
        tmp_path, monkeypatch
    )
    readiness_path = Path(os.environ["ARI_MANUSCRIPT_READINESS_PATH"])
    _write(
        readiness_path,
        {"schema_version": "ari.unknown-manuscript-readiness/v999"},
    )
    with pytest.raises(ValueError):
        finalize_runtime_publication(checkpoint)


def test_four_topology_release_e2e_locks_exact_bound_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ari.manuscript.runtime import (
        finalize_runtime_publication,
        lock_runtime_publication,
    )

    observed = {}
    for exploration_mode in ("simple_bfts", "ari_rqgm"):
        for paper_mode in ("linear", "rqgm_archive"):
            topology = f"{exploration_mode}+{paper_mode}"
            case_root = tmp_path / topology
            case_root.mkdir()
            checkpoint, outcome, build = _materialize_publishable_build(
                case_root,
                monkeypatch,
                exploration_mode=exploration_mode,
                paper_mode=paper_mode,
            )
            decision = finalize_runtime_publication(checkpoint)
            lock = lock_runtime_publication(checkpoint)
            assert decision.decision == "publishable"
            assert decision.paper_build_digest == build.build_digest
            assert lock.decision_digest == decision.decision_digest
            assert lock.authoring_binding_digest == (
                outcome.authoring_binding.binding_digest
            )
            observed[topology] = (
                outcome.readiness.readiness_digest,
                outcome.authoring_binding.paper_mode,
                lock.paper_build_digest,
            )
    assert set(observed) == {
        "simple_bfts+linear",
        "simple_bfts+rqgm_archive",
        "ari_rqgm+linear",
        "ari_rqgm+rqgm_archive",
    }


def test_required_brief_item_budget_failure_is_explicit(tmp_path: Path) -> None:
    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint, nodes, experiment_data=data, mode="enforce"
    )
    with pytest.raises(ValueError, match="cannot fit"):
        build_section_briefs(
            generic_empirical_profile(),
            outcome.context,
            outcome.readiness,
            character_budget=1,
        )


def test_legacy_migration_and_rollback_are_additive(tmp_path: Path) -> None:
    factory = _fixture_factory()
    fixture = factory.materialize_fixture(tmp_path, "mc_legacy_checkpoint")
    legacy_paper = fixture.checkpoint / "full_paper.tex"
    legacy_bytes = b"legacy paper bytes\n"
    legacy_paper.write_bytes(legacy_bytes)

    off = compile_manuscript(
        fixture.checkpoint,
        fixture.nodes,
        experiment_data=fixture.experiment_data,
        mode="off",
    )
    assert off.state == "disabled"
    assert not (fixture.checkpoint / ".ari-manuscript").exists()

    audit = compile_manuscript(
        fixture.checkpoint,
        fixture.nodes,
        experiment_data=fixture.experiment_data,
        mode="audit",
    )
    assert audit.readiness.counts["missing"] > 0
    enforce = compile_manuscript(
        fixture.checkpoint,
        fixture.nodes,
        experiment_data=fixture.experiment_data,
        mode="enforce",
    )
    assert not enforce.authoring_ready
    manuscript_root = fixture.checkpoint / ".ari-manuscript"
    before_rollback = {
        path.relative_to(manuscript_root).as_posix(): path.read_bytes()
        for path in manuscript_root.rglob("*")
        if path.is_file()
    }

    rolled_back = compile_manuscript(
        fixture.checkpoint,
        fixture.nodes,
        experiment_data=fixture.experiment_data,
        mode="off",
    )
    after_rollback = {
        path.relative_to(manuscript_root).as_posix(): path.read_bytes()
        for path in manuscript_root.rglob("*")
        if path.is_file()
    }
    assert rolled_back.state == "disabled"
    assert after_rollback == before_rollback
    assert legacy_paper.read_bytes() == legacy_bytes


def test_program_evaluation_reports_zero_denominators_honestly() -> None:
    from ari.manuscript.evaluation import evaluate_labelled_cases

    report = evaluate_labelled_cases(
        [
            {
                "case_id": "case-clean",
                "requirements": [
                    {"expected_missing": False, "observed_status": "satisfied"}
                ],
                "inventory_count": 3,
                "included_count": 2,
                "omission_count": 1,
                "headline_claim_count": 0,
                "negative_result_count": 0,
                "repair_request_count": 0,
                "off_identity": True,
                "topology": "simple_bfts+linear",
                "cost": {"llm_calls": 0},
            }
        ],
        dataset_id="mc-eval-test",
    )
    by_id = {item.metric_id: item for item in report.metrics}
    assert by_id["requirement-accounting-rate"].value == 1.0
    assert by_id["silent-omission-count"].value == 0
    assert by_id["headline-publishable-evidence-coverage"].status == "not_applicable"
    assert by_id["headline-publishable-evidence-coverage"].value is None
    assert by_id["repair-success-rate"].status == "not_applicable"


def test_manuscript_cli_compile_and_status(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from ari.cli import app

    checkpoint, _, _ = _ready_checkpoint(tmp_path)
    runner = CliRunner()
    compiled = runner.invoke(
        app, ["manuscript", "compile", str(checkpoint), "--mode", "audit"]
    )
    assert compiled.exit_code == 0, compiled.output
    payload = json.loads(compiled.output)
    assert payload["attempt_id"].startswith("mca-")
    status = runner.invoke(app, ["manuscript", "status", str(checkpoint)])
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["readiness"]["authoring_verdict"] == "ready"


def test_manuscript_evaluation_cli_writes_digest_bound_report(tmp_path: Path) -> None:
    from ari.manuscript.contracts import ManuscriptEvaluationReportV1

    cases = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    _write(cases, {"dataset_id": "mc-cli-empty", "cases": []})
    repo = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo / "ari-core")
    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "evaluate_manuscript_complete.py"),
            str(cases),
            "--output",
            str(report_path),
        ],
        cwd=repo,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = ManuscriptEvaluationReportV1.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    assert report.dataset_id == "mc-cli-empty"
    assert all(
        metric.status == "not_applicable" and metric.value is None
        for metric in report.metrics
        if metric.denominator == 0
    )


def _expose_manuscript_outcome(
    monkeypatch: pytest.MonkeyPatch, checkpoint: Path, outcome, *, mode: str
) -> None:
    names = {
        "requirement_profile.json": "ARI_MANUSCRIPT_PROFILE_PATH",
        "context.json": "ARI_MANUSCRIPT_CONTEXT_PATH",
        "readiness.json": "ARI_MANUSCRIPT_READINESS_PATH",
        "section_briefs.json": "ARI_MANUSCRIPT_BRIEFS_PATH",
        "authoring_binding.json": "ARI_MANUSCRIPT_BINDING_PATH",
    }
    monkeypatch.setenv("ARI_MANUSCRIPT_RUNTIME_MODE", mode)
    for filename, env_name in names.items():
        monkeypatch.setenv(
            env_name, str(checkpoint / outcome.artifact_paths[filename])
        )


class _ManuscriptArchiveReviewer:
    prompt_hash = "test-reviewer"

    def __init__(
        self,
        *,
        expect_fixed: bool = True,
        preferred_marker: str = "999.9\\%",
    ) -> None:
        self.bindings: list[str] = []
        self.expect_fixed = expect_fixed
        self.preferred_marker = preferred_marker

    def bind_manuscript_inputs(self, binding: dict, fixed_block: str) -> None:
        self.bindings.append(str(binding.get("input_fingerprint") or ""))
        assert binding.get("binding_digest")
        assert binding.get("section_brief_digests")
        assert binding.get("allowed_evidence_ids")
        assert bool(fixed_block) is self.expect_fixed

    def score(self, tex_path: str) -> float:
        text = Path(tex_path).read_text(encoding="utf-8")
        return 0.99 if self.preferred_marker in text else 0.10

    def review(self, _tex_path: str):  # pragma: no cover - depth-one fixture
        raise AssertionError("the depth-one archive must not refine")


class _ManuscriptArchiveMCP:
    def __init__(
        self,
        disclosures: tuple[str, ...],
        *,
        invalid_text: str = "The measured throughput improved by 999.9\\%.\n",
    ) -> None:
        self.disclosures = "\n".join(disclosures)
        self.writer_inputs: list[str] = []
        self.invalid_text = invalid_text

    def call_tool(self, name: str, args: dict):
        if name == "write_paper_iterative":
            self.writer_inputs.append(str(args.get("writer_prompt_override") or ""))
            invalid = int(args["decode_seed"]) == 1000
            numeric = self.invalid_text if invalid else ""
            return {
                "latex": (
                    "\\documentclass{article}\n\\begin{document}\n"
                    "\\section{Results}\n"
                    + numeric
                    + self.disclosures
                    + "\n\\end{document}\n"
                )
            }
        if name == "compile_paper":
            return {"success": True}
        raise AssertionError(f"unexpected paper tool: {name}")


def _manuscript_archive_cfg():
    from ari.config import ARIConfig

    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.paper.enabled = True
    cfg.rqgm.paper.archive.width = 2
    cfg.rqgm.paper.archive.depth = 1
    cfg.rqgm.paper.archive.refine_rounds = 0
    cfg.rqgm.paper.archive.max_expansions = 2
    return cfg


def test_four_topologies_share_readiness_and_binding_semantics(tmp_path: Path) -> None:
    signatures = {}
    for exploration_mode in ("simple_bfts", "ari_rqgm"):
        for paper_mode in ("linear", "rqgm_archive"):
            case_root = tmp_path / f"{exploration_mode}-{paper_mode}"
            case_root.mkdir()
            checkpoint, nodes, data = _ready_checkpoint(case_root)
            outcome = compile_manuscript(
                checkpoint,
                nodes,
                experiment_data=data,
                mode="enforce",
                exploration_mode=exploration_mode,
                paper_mode=paper_mode,
            )
            assert outcome.authoring_ready
            assert outcome.authoring_binding is not None
            assert outcome.authoring_binding.paper_mode == paper_mode
            from ari.manuscript.contracts import ExplorationSnapshotV1

            snapshot = ExplorationSnapshotV1.model_validate_json(
                (checkpoint / outcome.artifact_paths["source_snapshot.json"])
                .read_text(encoding="utf-8")
            )
            assert snapshot.exploration_mode == exploration_mode
            signatures[(exploration_mode, paper_mode)] = tuple(
                (
                    item.requirement_id,
                    item.applicable,
                    item.status,
                    item.authoring_blocking,
                    item.publication_blocking,
                )
                for item in outcome.readiness.requirement_results
            )
    assert len(set(signatures.values())) == 1


def test_rqgm_archive_uses_one_bundle_and_hard_disqualifies_before_utility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ari.manuscript.briefs import render_brief_bundle
    from ari.rqgm.paper_archive import read_paper_draft_archive
    from ari.rqgm.paper_runtime import PaperArchiveRuntime, read_paper_archive_state

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="enforce",
        paper_mode="rqgm_archive",
    )
    assert outcome.authoring_ready and outcome.briefs is not None
    rendered = render_brief_bundle(outcome.briefs)
    assert "Allowed positive-claim evidence IDs:" in rendered
    assert "Forbidden/non-publishable evidence IDs:" in rendered
    disclosures = tuple(sorted({
        item
        for brief in outcome.briefs.briefs
        for item in brief.required_disclosures
    }))
    _expose_manuscript_outcome(monkeypatch, checkpoint, outcome, mode="enforce")

    reviewer = _ManuscriptArchiveReviewer()
    mcp = _ManuscriptArchiveMCP(disclosures)
    runtime = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=reviewer,
    )
    runtime.run_archive(nodes, data, checkpoint, mcp, "")

    records = read_paper_draft_archive(checkpoint)
    assert len(records) == 2
    invalid = next(record for record in records if "999.9\\%" in (
        checkpoint / record["tex_path"]
    ).read_text(encoding="utf-8"))
    winner = next(record for record in records if record["is_best_belief"])
    assert invalid["review_score"] > winner["review_score"]
    assert invalid["manuscript_hard_disqualified"] is True
    assert any(
        reason.startswith("claim_gate:uncovered_numeric")
        for reason in invalid["manuscript_hard_disqualification_reasons"]
    )
    assert winner["manuscript_candidate_status"] == "admissible"
    assert winner["manuscript_bound"] is True
    assert (checkpoint / "full_paper.tex").read_bytes() == (
        checkpoint / winner["tex_path"]
    ).read_bytes()

    fingerprints = {record["manuscript_input_fingerprint"] for record in records}
    assert len(fingerprints) == 1
    assert set(reviewer.bindings) == fingerprints
    assert len(set(mcp.writer_inputs)) == 1
    fingerprint = fingerprints.pop()
    assert fingerprint and fingerprint in mcp.writer_inputs[0]
    state = read_paper_archive_state(checkpoint)["manuscript_authoring"]
    assert state["status"] == "manuscript_bound_winner"
    assert state["winner_tex_sha256"] == winner["tex_sha256"]

    # A newly compiled bundle cannot reuse or silently skip the old winner.
    _write(
        checkpoint / "verified_context.json",
        {"limitations": ["The test uses one synthetic workload and one host."]},
    )
    newer = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="enforce",
        paper_mode="rqgm_archive",
    )
    assert newer.authoring_ready
    assert newer.attempt_id != outcome.attempt_id
    _expose_manuscript_outcome(monkeypatch, checkpoint, newer, mode="enforce")
    with pytest.raises(Exception, match="stale manuscript archive binding"):
        runtime.run_archive(nodes, data, checkpoint, mcp, "")
    assert len(mcp.writer_inputs) == 2, "stale resume must make no additional model call"


def test_rqgm_archive_contextual_negative_cannot_win_as_positive_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ari.rqgm.paper_archive import read_paper_draft_archive
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    negative = {
        "id": "node-contextual-negative",
        "parent_id": "node-root",
        "ancestor_ids": ["node-root"],
        "depth": 1,
        "status": "failed",
        "label": "debug",
        "has_real_data": False,
        "metrics": {},
        "artifacts": [],
        "error_log": "injected negative result",
    }
    nodes.append(negative)
    for name in ("tree.json", "nodes_tree.json"):
        payload = json.loads((checkpoint / name).read_text(encoding="utf-8"))
        payload["nodes"] = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in nodes
        ]
        _write(checkpoint / name, payload)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="enforce",
        paper_mode="rqgm_archive",
    )
    negative_ids = tuple(sorted({
        evidence_id
        for brief in outcome.briefs.briefs
        for evidence_id in brief.contextual_negative_ids
    }))
    assert negative_ids
    marker = negative_ids[0]
    disclosures = tuple(sorted({
        item
        for brief in outcome.briefs.briefs
        for item in brief.required_disclosures
    }))
    _expose_manuscript_outcome(monkeypatch, checkpoint, outcome, mode="enforce")
    reviewer = _ManuscriptArchiveReviewer(preferred_marker=marker)
    mcp = _ManuscriptArchiveMCP(
        disclosures,
        invalid_text=f"The headline improvement is supported by {marker}.\n",
    )
    runtime = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=reviewer,
    )
    runtime.run_archive(nodes, data, checkpoint, mcp, "")

    records = read_paper_draft_archive(checkpoint)
    invalid = next(
        record
        for record in records
        if marker in (checkpoint / record["tex_path"]).read_text(encoding="utf-8")
    )
    winner = next(record for record in records if record["is_best_belief"])
    assert invalid["review_score"] > winner["review_score"]
    assert invalid["manuscript_hard_disqualified"] is True
    assert f"contextual_negative_evidence:{marker}" in (
        invalid["manuscript_hard_disqualification_reasons"]
    )
    assert invalid["manuscript_contextual_negative_evidence_mentions"] == [marker]


def test_enforced_archive_failure_rejects_an_unbound_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ari.rqgm.paper_runtime import (
        ManuscriptArchiveAuthoringError,
        PaperArchiveRuntime,
        read_paper_archive_state,
    )

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="enforce",
        paper_mode="rqgm_archive",
    )
    _expose_manuscript_outcome(monkeypatch, checkpoint, outcome, mode="enforce")

    class DeadMCP:
        def call_tool(self, _name: str, _args: dict):
            raise RuntimeError("archive unavailable")

    called = []

    def unbound_fallback(*_args, **_kwargs):
        called.append(True)

    mcp = DeadMCP()
    runtime = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=_ManuscriptArchiveReviewer(),
    )
    with pytest.raises(
        ManuscriptArchiveAuthoringError,
        match="no explicitly bound linear fallback",
    ):
        runtime.run_archive(
            nodes,
            data,
            checkpoint,
            mcp,
            "",
            linear_fallback=unbound_fallback,
        )
    assert called == []
    state = read_paper_archive_state(checkpoint)["manuscript_authoring"]
    assert state["status"] == "authoring_backend_failed"


def test_audit_archive_backend_failure_records_legacy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ari.rqgm.paper_runtime import PaperArchiveRuntime, read_paper_archive_state

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="audit",
        paper_mode="rqgm_archive",
    )
    _expose_manuscript_outcome(monkeypatch, checkpoint, outcome, mode="audit")

    class DeadMCP:
        def call_tool(self, _name: str, _args: dict):
            raise RuntimeError("injected network outage")

    fallback_calls = []

    def legacy_fallback(*_args, **_kwargs):
        fallback_calls.append(True)

    mcp = DeadMCP()
    runtime = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=_ManuscriptArchiveReviewer(expect_fixed=False),
    )
    runtime.run_archive(
        nodes,
        data,
        checkpoint,
        mcp,
        "",
        linear_fallback=legacy_fallback,
    )
    assert fallback_calls == [True]
    state = read_paper_archive_state(checkpoint)["manuscript_authoring"]
    assert state["status"] == "audit_legacy_linear_fallback"
    assert "injected network outage" in state["failure_reason"]


def test_audit_archive_records_legacy_authoring_and_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ari.rqgm.paper_archive import read_paper_draft_archive
    from ari.rqgm.paper_runtime import PaperArchiveRuntime, read_paper_archive_state

    checkpoint, nodes, data = _ready_checkpoint(tmp_path)
    outcome = compile_manuscript(
        checkpoint,
        nodes,
        experiment_data=data,
        mode="audit",
        paper_mode="rqgm_archive",
    )
    assert outcome.briefs is not None
    disclosures = tuple(sorted({
        item
        for brief in outcome.briefs.briefs
        for item in brief.required_disclosures
    }))
    _expose_manuscript_outcome(monkeypatch, checkpoint, outcome, mode="audit")
    reviewer = _ManuscriptArchiveReviewer(expect_fixed=False)
    mcp = _ManuscriptArchiveMCP(disclosures)
    runtime = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=reviewer,
    )
    runtime.run_archive(nodes, data, checkpoint, mcp, "")

    records = read_paper_draft_archive(checkpoint)
    assert records and all(record["manuscript_bound"] is False for record in records)
    assert all(record["manuscript_input_fingerprint"] for record in records)
    high = max(records, key=lambda record: record["review_score"])
    assert high["is_best_belief"] is True
    assert high["manuscript_candidate_status"] == "audit_findings"
    assert high["manuscript_hard_disqualified"] is False
    state = read_paper_archive_state(checkpoint)["manuscript_authoring"]
    assert state["status"] == "audit_legacy_archive_winner"

    # Switching the same durable archive from audit to enforce is a stale
    # resume disagreement and must fail before another writer call.
    monkeypatch.setenv("ARI_MANUSCRIPT_RUNTIME_MODE", "enforce")
    stricter = PaperArchiveRuntime(
        _manuscript_archive_cfg(),
        checkpoint_dir=checkpoint,
        mcp=mcp,
        reviewer=_ManuscriptArchiveReviewer(),
    )
    with pytest.raises(Exception, match="stale manuscript archive binding"):
        stricter.run_archive(nodes, data, checkpoint, mcp, "")
    assert len(mcp.writer_inputs) == 2
