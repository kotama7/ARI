"""Executable synthetic fixtures for the Manuscript Complete program.

Every measurement and Attestation produced here is test-only. The checked-in
manifests carry the same disclaimer and generator version so a generated
checkpoint cannot be mistaken for retained research evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ari.orchestrator.node import Node, NodeLabel, NodeStatus


GENERATOR_VERSION = "manuscript-fixture-factory-v1"
FIXTURE_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SyntheticFixture:
    fixture_id: str
    checkpoint: Path
    nodes: tuple[Any, ...]
    experiment_data: dict[str, str]
    manifest: dict[str, Any]


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _manifest(fixture_id: str) -> dict[str, Any]:
    value = json.loads(
        (FIXTURE_ROOT / fixture_id / "manifest.json").read_text(encoding="utf-8")
    )
    if value.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("fixture manifest and executable generator disagree")
    return value


def _node(
    node_id: str,
    *,
    parent_id: str | None = None,
    depth: int = 0,
    score: float = 0.9,
    direction: str = "Execute the frozen synthetic throughput protocol.",
    label: NodeLabel = NodeLabel.DRAFT,
) -> Node:
    node = Node(
        id=node_id,
        parent_id=parent_id,
        depth=depth,
        status=NodeStatus.SUCCESS,
        artifacts=[{"path": "measurement.json", "kind": "measurement"}],
        metrics={"throughput": 100.0 + score, "_scientific_score": score},
        has_real_data=True,
        label=label,
        ancestor_ids=(["node-root"] if parent_id == "node-root" else []),
        original_direction=direction,
        node_report_path=f"{node_id}/node_report.json",
    )
    return node


def _node_payload(node: Any) -> dict[str, Any]:
    return node.to_dict() if hasattr(node, "to_dict") else dict(node)


def _write_tree(checkpoint: Path, nodes: list[Any], *, run_id: str) -> None:
    payloads = [_node_payload(node) for node in nodes]
    _write(
        checkpoint / "tree.json",
        {
            "run_id": run_id,
            "experiment_file": str(checkpoint / "experiment.md"),
            "nodes": payloads,
        },
    )
    _write(
        checkpoint / "nodes_tree.json",
        {"run_id": run_id, "nodes": payloads},
    )
    _write(
        checkpoint / "results.json",
        {
            "run_id": run_id,
            "nodes": {
                str(item["id"]): {
                    "metrics": item.get("metrics") or {},
                    "status": item.get("status"),
                    "has_real_data": item.get("has_real_data", False),
                }
                for item in payloads
            },
        },
    )


def _base(checkpoint: Path, *, run_id: str) -> tuple[list[Any], dict[str, str]]:
    checkpoint.mkdir(parents=True, exist_ok=True)
    _write(
        checkpoint / "experiment.md",
        "# Synthetic throughput fixture\n\nMetrics: throughput\n",
    )
    _write(checkpoint / "measurement.json", {"throughput": 100.9, "synthetic": True})
    node = _node("node-root")
    nodes: list[Any] = [node]
    _write_tree(checkpoint, nodes, run_id=run_id)
    _write(
        checkpoint / "node-root" / "node_report.json",
        {
            "schema_version": 1,
            "node_id": "node-root",
            "status": "success",
            "metrics": {"throughput": 100.9},
            "synthetic": True,
        },
    )
    _write(
        checkpoint / "idea.json",
        {
            "research_question": "What throughput does the synthetic method produce?",
            "ideas": [
                {
                    "title": "Bound synthetic throughput study",
                    "description": "Measure the synthetic method's throughput.",
                    "hypothesis": "The method produces measurable throughput.",
                    "falsification_conditions": ["No throughput is measured."],
                    "experiment_plan": "Run the fixed workload and report throughput.",
                    "contributions": ["A test-only measured throughput record."],
                }
            ],
        },
    )
    _write(
        checkpoint / "science_data.json",
        {
            "schema_version": "ari.science-data/v1",
            "raw": {
                "configurations": [
                    {"configuration_id": "cfg-1", "role": "candidate"}
                ],
                "measurement_records": [
                    {"run_id": "measurement-1", "throughput": 100.9}
                ],
                "claims": [{"claim_id": "claim-1", "claim_type": "result"}],
            },
            "interpretation": {
                "status": "ok",
                "experiment_context": {"hardware": {"cpu": "synthetic-cpu"}},
            },
        },
    )
    _write(
        checkpoint / "related_refs.json",
        {
            "records": [
                {
                    "record_id": "ref-1",
                    "title": "Synthetic prior work",
                    "year": 2024,
                    "abstract": "Test-only related work.",
                }
            ]
        },
    )
    _write(
        checkpoint / "ear_manifest.json",
        {
            "environment": {"cpu": "synthetic-cpu"},
            "commands": ["python reproduce.py"],
            "has_environment": True,
            "has_reproduce_sh": True,
        },
    )
    _write(
        checkpoint / "verified_context.json",
        {"limitations": ["All values in this fixture are synthetic test data."]},
    )
    return nodes, {
        "goal": "What throughput does the synthetic method produce?",
        "topic": "synthetic-throughput",
        "file": str(checkpoint / "experiment.md"),
    }


def _large(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    nodes, data = _base(checkpoint, run_id=run_id)
    long_direction = "Synthetic bounded method detail. " * 70
    for index in range(1, 31):
        nodes.append(
            _node(
                f"node-{index:03d}",
                parent_id="node-root",
                depth=1,
                score=0.5 + index / 100,
                direction=f"case={index}. {long_direction}",
            )
        )
    _write_tree(checkpoint, nodes, run_id=run_id)
    science = json.loads((checkpoint / "science_data.json").read_text(encoding="utf-8"))
    science["raw"]["configurations"] = [
        {"configuration_id": f"cfg-{index:02d}", "role": "candidate"}
        for index in range(11)
    ]
    science["raw"]["measurement_records"] = [
        {"run_id": f"measurement-{index:02d}", "throughput": 100.0 + index}
        for index in range(22)
    ]
    science["raw"]["claims"] = [
        {"claim_id": f"claim-{index:02d}", "claim_type": "result"}
        for index in range(21)
    ]
    _write(checkpoint / "science_data.json", science)
    _write(
        checkpoint / "related_refs.json",
        {
            "records": [
                {
                    "record_id": f"ref-{index:02d}",
                    "title": f"Synthetic reference {index}",
                    "abstract": "Recorded test reference. " * 20,
                }
                for index in range(13)
            ]
        },
    )
    return nodes, data


def _negative(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    nodes, data = _base(checkpoint, run_id=run_id)
    for index, status in enumerate(("failed", "null", "inconclusive", "abandoned"), 1):
        nodes.append(
            {
                "id": f"node-negative-{index}",
                "parent_id": "node-root",
                "ancestor_ids": ["node-root"],
                "depth": 1,
                "status": status,
                "label": "debug",
                "has_real_data": False,
                "metrics": {},
                "artifacts": [],
                "error_log": f"synthetic {status} outcome",
            }
        )
    nodes.append(
        _node(
            "node-off-lineage",
            parent_id="node-root",
            depth=1,
            score=0.4,
            direction="Synthetic off-lineage sibling.",
        )
    )
    _write_tree(checkpoint, nodes, run_id=run_id)
    return nodes, data


def _tamper(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    nodes, data = _base(checkpoint, run_id=run_id)
    root = nodes[0]
    root.artifacts = [
        {"path": "measurement.json", "sha256": "0" * 64},
        {"path": "missing-measurement.json", "sha256": "1" * 64},
    ]
    stale = _node(
        "node-stale",
        parent_id="node-root",
        depth=1,
        score=1.0,
    )
    stale.metrics["_stale"] = True
    nodes.append(stale)
    _write_tree(checkpoint, nodes, run_id=run_id)
    return nodes, data


def _attestation(node_id: str, target_digest: str):
    from ari.assurance.models import (
        HarnessAttestationV1,
        HarnessPropertyResultV1,
        VerificationScopeV1,
    )

    digest = "sha256:" + "a" * 64
    return HarnessAttestationV1.create(
        run_id="run-mc_rqgm_assured",
        node_id=node_id,
        epoch_id="epoch-000",
        producer_epoch_id="epoch-000",
        research_contract_digest=digest,
        verification_contract_digest=digest,
        knowledge_skill_use_digest=digest,
        capability_binding_lock_digest=digest,
        baseline_harness_lock_digest=digest,
        active_harness_lock_digest=digest,
        harness_manifest_digest=digest,
        driver_digest=digest,
        oracle_digest=digest,
        dataset_digest=digest,
        container_digest=digest,
        target_logical_name="candidate.so",
        target_digest=target_digest,
        target_kind="shared-library",
        execution_identity=digest,
        execution_result_digest=digest,
        verdict="pass",
        property_results=(
            HarnessPropertyResultV1(
                property_id="numerical-equivalence",
                method="differential-testing",
                tier="certify",
                tested_scope=VerificationScopeV1(
                    values={"language": ("c",), "hardware": ("cpu",)}
                ),
                verdict="pass",
                covered_atom_digests=(digest,),
                evidence_artifact_refs=(),
            ),
        ),
        evidence_artifact_refs=(),
        infrastructure_status="ready",
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id="attempt-1",
        retry_index=0,
    )


def _rqgm(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    _, data = _base(checkpoint, run_id=run_id)
    target = "sha256:" + "b" * 64
    relative = "rqgm/kca/nodes/node-certified/attestations/certify.json"
    _write(
        checkpoint / relative,
        json.loads(_attestation("node-certified", target).model_dump_json()),
    )
    certified = _node("node-certified", score=0.8)
    certified.frontier_class = "scientific_frontier"
    certified.assurance_status = "pass"
    certified.assurance_tier = "certify"
    certified.verified_target_digest = target
    certified.attestation_refs = [relative]
    certified.property_verdicts = {"numerical-equivalence": "pass"}
    debug = _node("node-debug", score=0.99)
    debug.frontier_class = "debug_frontier"
    uncertified = _node("node-uncertified", score=0.9)
    uncertified.frontier_class = "uncertified_frontier"
    stale_relative = "rqgm/kca/nodes/node-stale-cert/attestations/certify.json"
    _write(
        checkpoint / stale_relative,
        json.loads(_attestation("node-stale-cert", target).model_dump_json()),
    )
    stale = _node("node-stale-cert", score=0.7)
    stale.frontier_class = "scientific_frontier"
    stale.assurance_status = "pass"
    stale.assurance_tier = "certify"
    stale.verified_target_digest = "sha256:" + "c" * 64
    stale.attestation_refs = [stale_relative]
    nodes: list[Any] = [certified, debug, uncertified, stale]
    _write_tree(checkpoint, nodes, run_id=run_id)
    return nodes, data


def _legacy(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    checkpoint.mkdir(parents=True, exist_ok=True)
    _write(checkpoint / "experiment.md", "# Synthetic legacy fixture\n")
    node = _node("node-root")
    nodes: list[Any] = [node]
    _write_tree(checkpoint, nodes, run_id=run_id)
    return nodes, {
        "goal": "Synthetic legacy goal",
        "topic": "legacy",
        "file": str(checkpoint / "experiment.md"),
    }


def _repairable(checkpoint: Path, run_id: str) -> tuple[list[Any], dict[str, str]]:
    nodes, data = _base(checkpoint, run_id=run_id)
    idea = json.loads((checkpoint / "idea.json").read_text(encoding="utf-8"))
    idea["research_contract"] = {
        "research_question": data["goal"],
        "claim_characteristics": {
            "comparative_claim": True,
            "stochastic_claim": True,
            "multi_component_claim": True,
        },
        "contributions": ["component A", "component B"],
    }
    _write(checkpoint / "idea.json", idea)
    return nodes, data


_BUILDERS = {
    "mc_small_linear": lambda checkpoint, run_id: _base(checkpoint, run_id=run_id),
    "mc_large_context": _large,
    "mc_negative_tree": _negative,
    "mc_tamper_stale": _tamper,
    "mc_rqgm_assured": _rqgm,
    "mc_legacy_checkpoint": _legacy,
    "mc_repairable_gap": _repairable,
}


def materialize_fixture(root: str | Path, fixture_id: str) -> SyntheticFixture:
    if fixture_id not in _BUILDERS:
        raise ValueError(f"unknown Manuscript Complete fixture: {fixture_id}")
    manifest = _manifest(fixture_id)
    checkpoint = Path(root).resolve() / fixture_id
    run_id = f"run-{fixture_id}"
    nodes, data = _BUILDERS[fixture_id](checkpoint, run_id)
    # Node reports are first-class provenance inputs.  Materialize one for every
    # generated Node unless a fixture intentionally supplied a more specific
    # report.  Dictionary-only negative nodes omit node_report_path on purpose.
    for node in nodes:
        payload = _node_payload(node)
        report_path = payload.get("node_report_path")
        if not isinstance(report_path, str) or not report_path.strip():
            continue
        destination = checkpoint / report_path
        if destination.exists():
            continue
        _write(
            destination,
            {
                "schema_version": 1,
                "node_id": payload.get("id"),
                "status": payload.get("status"),
                "metrics": payload.get("metrics") or {},
                "synthetic": True,
            },
        )
    _write(
        checkpoint / "SYNTHETIC_FIXTURE.json",
        {
            "fixture_id": fixture_id,
            "generator_version": GENERATOR_VERSION,
            "measurement_disclaimer": manifest["measurement_disclaimer"],
        },
    )
    return SyntheticFixture(
        fixture_id=fixture_id,
        checkpoint=checkpoint,
        nodes=tuple(nodes),
        experiment_data=data,
        manifest=manifest,
    )


__all__ = [
    "GENERATOR_VERSION",
    "SyntheticFixture",
    "materialize_fixture",
]
