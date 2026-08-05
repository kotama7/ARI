from __future__ import annotations

import json
from pathlib import Path

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
    assert {path.name for path in root.iterdir() if path.is_dir()} == expected
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

    usage: dict[str, int] = {}
    results = execute_repair_plan(
        admitted,
        executors={"baseline_comparison": bounded},
        used_budget=usage,
    )
    assert results[0].status == "executed"
    assert usage == {"new_nodes": 1, "experiment_runs": 1, "llm_calls": 1}


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
        observed["max_total_nodes"] = loop_cfg.bfts.max_total_nodes
        observed["pending"] = list(pending)
        pending[0].mark_success()
        return total_processed + 1

    monkeypatch.setattr("ari.cli.bfts_loop._run_loop", fake_loop)
    bfts = BFTS()
    original_max = cfg.bfts.max_total_nodes
    from ari.cli.manuscript_repair_runtime import build_research_repair_executors

    executors = build_research_repair_executors(
        cfg, bfts, Agent(), nodes, data, checkpoint, "run-ready"
    )
    result = executors["baseline_comparison"](
        request,
        RepairBudgetV1(
            max_rounds=1, max_new_nodes=1, max_experiment_runs=1, max_llm_calls=1
        ),
    )
    repair_node = observed["pending"][0]
    assert result.status == "executed"
    assert repair_node.repair_request_id == request.request_id
    assert repair_node.repair_requirement_ids == ["MC-CP-001"]
    assert repair_node.repair_context_digest == outcome.context.context_digest
    assert repair_node.repair_allowed_changes == ["method_or_baseline_only"]
    assert bfts.rqgm.stamped == [repair_node.id]
    assert bfts.rqgm.recorded == [("node-root", repair_node.id)]
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
