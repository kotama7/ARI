#!/usr/bin/env python3
"""Run a production GEMM certify Attestation through the publication gate."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import promote_native_harnesses as promotion  # noqa: E402
from ari.assurance.catalog import load_harness_catalog  # noqa: E402
from ari.assurance.models import VerificationContractV1  # noqa: E402
from ari.assurance.resolver import (  # noqa: E402
    mint_baseline_harness_lock,
    resolve_harness_suite,
)
from ari.claim_gate_contract import (  # noqa: E402
    GateFormulaProvenanceV1,
    GateReportV1,
)
from ari.execution import MeasurementRecordV1, WorkspaceRefV1  # noqa: E402
from ari.manuscript.digest import file_digest  # noqa: E402
from ari.manuscript.runtime import (  # noqa: E402
    finalize_runtime_publication,
    prepare_runtime_manuscript,
    transition_runtime_manuscript,
)
from ari.orchestrator.node import Node, NodeLabel, NodeStatus  # noqa: E402
from ari.paper_contract import (  # noqa: E402
    PaperArtifactV1,
    PaperBuildV1,
    PaperCompileV1,
    PaperGateSummaryV1,
    PaperNumericCoverageV1,
    PaperRevisionV1,
)
from ari.protocols.integrity import bytes_digest, canonical_digest  # noqa: E402
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1  # noqa: E402
from ari.rqgm.assurance_bridge import RQGMAssuranceBridge  # noqa: E402
from ari.science_data_base import ScienceArtifactRefV1, ScienceEnvironmentV1  # noqa: E402
from ari.science_data_contract import (  # noqa: E402
    ScienceConfigurationV1,
    ScienceDataV1,
    ScienceRawV1,
)
from ari.science_data_derived import (  # noqa: E402
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceProvenanceV1,
)
from ari.pipeline.claim_gate.numeric import formula_registry_digest  # noqa: E402


RUN_ID = "native-certify-publication-e2e"
NODE_ID = "publication-candidate"
ZERO_SHA = "sha256:" + "0" * 64


def _json_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _paper_artifact(checkpoint: Path, role: str, relative: str, media_type: str):
    digest, size = file_digest(checkpoint / relative)
    return PaperArtifactV1(
        role=role,
        relative_path=relative,
        digest=digest,
        media_type=media_type,
        size_bytes=size,
    )


def _science_artifact(checkpoint: Path, relative: str, role: str):
    digest, size = file_digest(checkpoint / relative)
    return ScienceArtifactRefV1(
        relative_path=relative,
        digest=digest,
        media_type="application/json",
        role=role,
        size_bytes=size,
    )


def _build_science_data(checkpoint: Path, attestation, wall_seconds: float):
    tree_artifact = _science_artifact(checkpoint, "tree.json", "experiment-tree")
    measurement_payload = {
        "schema_version": "ari.e2e-measurement-set/v1",
        "metric_id": "verification_wall_seconds",
        "value": wall_seconds,
        "unit": "s",
        "attestation_digest": attestation.attestation_digest,
        "execution_identity": attestation.execution_identity,
    }
    _write_json(checkpoint / "measurement_set.json", measurement_payload)
    measurement_artifact = _science_artifact(
        checkpoint, "measurement_set.json", "measurement-set"
    )
    measurement = MeasurementRecordV1(
        metric_id="verification_wall_seconds",
        value=wall_seconds,
        unit="s",
        unit_status="declared",
        execution_identity=attestation.execution_identity,
        execution_attempt_id=attestation.attempt_id,
        execution_status="completed",
        exit_code=0,
    )
    configuration = ScienceConfigurationV1(
        config_id="certified-gemm",
        run_id=RUN_ID,
        node_id=NODE_ID,
        rank=1,
        label="certified native GEMM",
        source_kind="typed-measurement",
        claim_eligible=True,
        parameters={"assurance_tier": "certify"},
        measurements={"verification_wall_seconds": wall_seconds},
        measurement_records=(measurement,),
        environment=ScienceEnvironmentV1(
            executor="fixed_verifier_v1",
            arch=platform.machine(),
            environment_digest=attestation.container_digest,
        ),
        source_artifacts=(tree_artifact, measurement_artifact),
    )
    raw = ScienceRawV1.create(
        tree_artifact=tree_artifact,
        configurations=(configuration,),
        node_report_status="complete",
        measurement_status="complete",
    )
    derived = ScienceDerivedV1.create(
        formula_registry_digest=formula_registry_digest(),
        summary_stats={
            "configuration_count": 1,
            "certify_pass_count": 1,
        },
    )
    interpretation = ScienceInterpretationV1.create(
        status="unavailable",
        input_raw_digest=raw.raw_digest,
        experiment_context={},
        error_kind="not-required-for-fixed-e2e",
        error_message="No model interpretation is used in this fixed verification E2E.",
    )
    provenance = ScienceProvenanceV1(
        producer_tool_ref="fixed_verifier_v1",
        producer_version="1",
        input_artifacts=(tree_artifact, measurement_artifact),
        admission_artifacts=(),
    )
    return ScienceDataV1.create(
        run_id=RUN_ID,
        raw=raw,
        derived=derived,
        interpretation=interpretation,
        limitations=(
            "The Attestation covers only the registered GEMM ABI and generated certify cases.",
        ),
        provenance=provenance,
    )


def _write_manuscript_sources(checkpoint: Path, node: Node, attestation) -> None:
    _write_json(
        checkpoint / "idea.json",
        {
            "research_contract": {
                "contract_digest": canonical_digest(
                    {"run_id": RUN_ID, "objective": "certify-publication-e2e"}
                ),
                "research_question": (
                    "Can an artifact-bound native GEMM certification gate a publication?"
                ),
                "objective": "Exercise the production certification and publication boundary.",
                "hypothesis": "A correct ABI-conforming GEMM target passes certify.",
                "falsification_conditions": [
                    "Any required certify property fails or the target digest differs."
                ],
                "contributions": [
                    "A fixed-verifier-to-publication integration record."
                ],
                "method": "Run the locked native GEMM suite and bind its Attestation.",
            },
            "ideas": [
                {
                    "title": "Native certification publication E2E",
                    "experiment_plan": (
                        "Compile the registered reference target, run screen and certify, "
                        "then compile and gate a minimal paper artifact."
                    ),
                }
            ],
        },
    )
    _write_json(
        checkpoint / "evaluation_criteria.json",
        {"primary_metric": "verification_wall_seconds", "direction": "minimize"},
    )
    tree = {
        "schema_version": "ari.e2e-tree/v1",
        "run_id": RUN_ID,
        "nodes": [node.to_dict()],
    }
    _write_json(checkpoint / "tree.json", tree)
    _write_json(checkpoint / "nodes_tree.json", tree)
    _write_json(
        checkpoint / "node_provenance_audit.json",
        {"results": [{"node_id": NODE_ID, "status": "complete"}]},
    )
    cost = json.loads((checkpoint / "cost_summary.json").read_text(encoding="utf-8"))
    wall_seconds = float(cost["verification_resources"]["wall_time_seconds"])
    _write_json(
        checkpoint / "science_data.json",
        _build_science_data(checkpoint, attestation, wall_seconds),
    )
    _write_json(
        checkpoint / "related_refs.json",
        {
            "records": [
                {
                    "record_id": "ari-assurance-design",
                    "title": "ARI Scientific Assurance design record",
                    "url": "https://github.com/kotama7/ARI",
                    "year": 2026,
                    "authors": ["ARI contributors"],
                    "citation_key": "ari2026assurance",
                    "record_digest": canonical_digest("ari-assurance-design"),
                }
            ]
        },
    )
    _write_json(
        checkpoint / "ear_manifest.json",
        {
            "schema_version": "ari.e2e-ear/v1",
            "commands": [
                "ari harness verify --tier screen",
                "ari harness verify --tier certify",
            ],
            "environment": {
                "architecture": platform.machine(),
                "container_digest": attestation.container_digest,
                "network": "deny",
            },
        },
    )
    _write_json(
        checkpoint / "ear_published" / "manifest.lock",
        {
            "schema_version": "ari.e2e-code-bundle-lock/v1",
            "target_digest": attestation.target_digest,
            "attestation_digest": attestation.attestation_digest,
        },
    )
    _write_json(
        checkpoint / "figures_manifest.json",
        {"schema_version": "ari.e2e-figure-batch/v1", "figures": []},
    )
    _write_json(
        checkpoint / "verified_context.json",
        {
            "limitations": [
                {
                    "text": (
                        "Certification is scoped to the declared ABI, cases, dtype, and CPU environment."
                    )
                }
            ]
        },
    )
    _write_json(
        checkpoint / "manuscript_disclosures.json",
        {
            "records": [
                {
                    "limitation": "No claim beyond registered Harness scope is made.",
                    "threat_to_validity": (
                        "Generated cases do not constitute a proof over all possible inputs."
                    ),
                }
            ]
        },
    )


def _compile_paper(checkpoint: Path, binding, readiness, context, attestation):
    paper_dir = checkpoint / "paper"
    paper_dir.mkdir(parents=True)
    tex_relative = "paper/full_paper.tex"
    bib_relative = "paper/refs.bib"
    tex = (
        "\\documentclass{article}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\title{Artifact-Bound Native GEMM Certification E2E}\n"
        "\\author{ARI Fixed Runtime}\n"
        "\\begin{document}\n\\maketitle\n"
        "A locked native verifier certified the exact candidate artifact. "
        "The measured verifier wall time is reported only from executor timestamps.\n"
        "\\section{Limitations}\nThe result is scoped to the registered Harness.\n"
        "\\end{document}\n"
    )
    (checkpoint / tex_relative).write_text(tex, encoding="utf-8")
    (checkpoint / bib_relative).write_text(
        "@misc{ari2026assurance,title={ARI Scientific Assurance},year={2026}}\n",
        encoding="utf-8",
    )
    compiler = shutil.which("pdflatex")
    if compiler is None:
        raise RuntimeError("pdflatex is required for publication E2E")
    argv = [
        compiler,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        "full_paper.tex",
    ]
    completed = subprocess.run(
        argv,
        cwd=paper_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    (paper_dir / "compile.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (paper_dir / "compile.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not (paper_dir / "full_paper.pdf").is_file():
        raise RuntimeError("publication E2E paper compilation failed")
    gate = GateReportV1.create(
        source_run_id=RUN_ID,
        phase="final",
        policy_mode="strict",
        comparison_scope="same_environment",
        status="passed",
        should_block=False,
        policy_digest=canonical_digest("e2e-claim-evidence-policy/v1"),
        evidence_digest=attestation.attestation_digest,
        formula_provenance=GateFormulaProvenanceV1(
            registry_digest=formula_registry_digest(),
            formulas_used=(),
            unit_conversions=(),
        ),
        blocking_findings=(),
        advisory_findings=(),
        metrics={"certified_claims": 1},
    )
    _write_json(checkpoint / "claim_gate_report.json", gate)
    tex_artifact = _paper_artifact(checkpoint, "final-tex", tex_relative, "text/x-tex")
    bib_artifact = _paper_artifact(checkpoint, "bibtex", bib_relative, "text/x-bibtex")
    pdf_artifact = _paper_artifact(
        checkpoint, "pdf", "paper/full_paper.pdf", "application/pdf"
    )
    stdout_artifact = _paper_artifact(
        checkpoint,
        "compile-stdout",
        "paper/compile.stdout.log",
        "text/plain",
    )
    stderr_artifact = _paper_artifact(
        checkpoint,
        "compile-stderr",
        "paper/compile.stderr.log",
        "text/plain",
    )
    revision = PaperRevisionV1.create(
        revision=0,
        reason="initial",
        tex_artifact=tex_artifact,
        bib_artifact=bib_artifact,
        claim_anchors=("CLAIM:CERTIFY:E2E",),
        citation_keys=(),
        figure_ids=(),
        math_digest=canonical_digest("no-mathematical-expression"),
    )
    compile_record = PaperCompileV1.create(
        status="completed",
        commands=(("pdflatex", *argv[1:]),),
        execution_identities=(
            canonical_digest(
                {
                    "compiler_digest": promotion._stream_digest(Path(compiler).resolve()),
                    "tex_digest": tex_artifact.digest,
                    "argv": ["pdflatex", *argv[1:]],
                }
            ),
        ),
        log_artifacts=(stdout_artifact, stderr_artifact),
        pdf_artifact=pdf_artifact,
        environment_digest=canonical_digest(
            {"architecture": platform.machine(), "compiler": "pdflatex"}
        ),
    )
    inputs = (
        _paper_artifact(
            checkpoint, "science-data", "science_data.json", "application/json"
        ),
        _paper_artifact(
            checkpoint,
            "figure-batch",
            "figures_manifest.json",
            "application/json",
        ),
        _paper_artifact(
            checkpoint,
            "retrieval-records",
            "related_refs.json",
            "application/json",
        ),
        _paper_artifact(
            checkpoint, "ear-manifest", "ear_manifest.json", "application/json"
        ),
        _paper_artifact(
            checkpoint,
            "manuscript-context",
            Path(os.environ["ARI_MANUSCRIPT_CONTEXT_PATH"])
            .relative_to(checkpoint)
            .as_posix(),
            "application/json",
        ),
        _paper_artifact(
            checkpoint,
            "manuscript-readiness",
            Path(os.environ["ARI_MANUSCRIPT_READINESS_PATH"])
            .relative_to(checkpoint)
            .as_posix(),
            "application/json",
        ),
        _paper_artifact(
            checkpoint,
            "manuscript-authoring-binding",
            Path(os.environ["ARI_MANUSCRIPT_BINDING_PATH"])
            .relative_to(checkpoint)
            .as_posix(),
            "application/json",
        ),
    )
    build = PaperBuildV1.create(
        build_id=binding.target_build_id,
        run_id=RUN_ID,
        build_revision=0,
        status="finalized",
        input_artifacts=inputs,
        venue_id="internal-e2e",
        venue_version="1",
        template_digest=bytes_digest(tex.encode("utf-8")),
        rubric_id="certification-e2e/v1",
        rubric_version="1",
        rubric_digest=readiness.profile_digest,
        ear_digest=next(item.digest for item in inputs if item.role == "ear-manifest"),
        revisions=(revision,),
        compile=compile_record,
        gate=PaperGateSummaryV1(
            mode="strict",
            status="pass",
            blocking_error_count=0,
            report_digest=gate.report_digest,
        ),
        numeric_coverage=PaperNumericCoverageV1(
            result_mentions=1,
            linked_mentions=1,
            excluded_mentions=0,
            unresolved_anchors=0,
            uncovered_mentions=0,
        ),
        final_artifacts=(tex_artifact, bib_artifact, pdf_artifact),
        limitations=tuple(context.limitations),
    )
    _write_json(checkpoint / "paper_build.json", build)
    return build


def _authoritative_cost(checkpoint: Path) -> dict[str, Any]:
    records = []
    for line in (checkpoint / "cost_trace.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("component") != "assurance":
            continue
        records.append(
            {
                "accelerator_seconds": record["accelerator_seconds"],
                "attestation_digest": record["attestation_digest"],
                "cpu_core_seconds": record["cpu_core_seconds"],
                "execution_attempt_id": record["execution_attempt_id"],
                "execution_identity": record["execution_identity"],
                "execution_status": record["execution_status"],
                "harness_id": record["harness_id"],
                "memory_byte_seconds": record["memory_byte_seconds"],
                "measurement_basis": record["resource_measurement_basis"],
                "pricing_status": record["cost_status"],
                "tier": record["phase"],
                "wall_time_seconds": record["wall_time_ms"] / 1000.0,
            }
        )
    if {item["tier"] for item in records} != {"screen", "certify"}:
        raise RuntimeError("authoritative E2E cost lacks screen or certify execution")
    report: dict[str, Any] = {
        "schema_version": "ari.authoritative-verification-cost/v1",
        "run_id": RUN_ID,
        "node_id": NODE_ID,
        "measurement_semantics": {
            "wall_time_seconds": "executor start/completion timestamps",
            "cpu_core_seconds": "declared allocation multiplied by measured wall time",
            "accelerator_seconds": "declared allocation multiplied by measured wall time",
            "memory_byte_seconds": "declared allocation multiplied by measured wall time",
            "monetary_cost": "null until a digest-bound rate card or invoice exists",
        },
        "records": sorted(records, key=lambda item: (item["tier"], item["execution_attempt_id"])),
        "totals": {
            "wall_time_seconds": sum(item["wall_time_seconds"] for item in records),
            "cpu_core_seconds": sum(item["cpu_core_seconds"] for item in records),
            "accelerator_seconds": sum(item["accelerator_seconds"] for item in records),
            "memory_byte_seconds": sum(item["memory_byte_seconds"] for item in records),
            "monetary_cost_usd": None,
            "pricing_status": "unpriced",
        },
    }
    report["measurement_digest"] = canonical_digest(report)
    return report


def _publish_evidence(
    *,
    evidence_root: Path,
    attestation_path: Path,
    decision_path: Path,
    cost: dict[str, Any],
    report: dict[str, Any],
) -> None:
    outputs = {
        evidence_root / "certify_attestation.json": attestation_path.read_bytes(),
        evidence_root / "publication_decision.json": decision_path.read_bytes(),
        evidence_root / "authoritative_verification_cost.json": _json_bytes(cost),
        evidence_root / "e2e_report.json": _json_bytes(report),
    }
    for path, payload in outputs.items():
        if path.exists() and path.read_bytes() != payload:
            raise RuntimeError(f"immutable production E2E evidence differs: {path}")
    for path, payload in outputs.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def run(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.checkpoint.resolve()
    if checkpoint.exists() and any(checkpoint.iterdir()):
        raise RuntimeError("E2E checkpoint must be absent or empty")
    checkpoint.mkdir(parents=True, exist_ok=True)
    container_root = args.container_root.resolve(strict=True)
    os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(container_root)
    catalog = load_harness_catalog(
        ARI_CORE / "config" / "harnesses" / "catalog.yaml"
    )
    manifest = next(
        (item for item in catalog.manifests if item.id == "hpc/gemm-correctness"),
        None,
    )
    if manifest is None or manifest.status != "verified":
        raise RuntimeError("production GEMM Harness is not verified")
    base_contract = promotion._contract(
        manifest=manifest,
        source_commit=manifest.source_full_commit_sha,
    )
    research_digest = canonical_digest({"run_id": RUN_ID, "goal": "publication-e2e"})
    contract = VerificationContractV1.create(
        run_id=RUN_ID,
        research_contract_digest=research_digest,
        requirements=base_contract.requirements,
        admission_confidence=1.0,
        human_review_identity=canonical_digest("publication-e2e-admission"),
        property_vocabulary_digest=catalog.property_vocabulary_digest,
    )
    environment = EnvironmentSnapshotV1.create(
        resource_types=("cpu", "process"),
        features=("landlock", "network-namespace"),
        transports=("local-process",),
        network_classes=("deny",),
        metadata={
            "architecture": platform.machine(),
            "container_digest": manifest.container.resolved_digest,
        },
    )
    suite = resolve_harness_suite(
        contract=contract,
        catalog=catalog,
        environment=environment,
    )
    baseline = mint_baseline_harness_lock(
        run_id=RUN_ID,
        research_contract_digest=research_digest,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=manifest.oracle.sha256,
        suite=suite,
    )
    candidate_dir = checkpoint / "nodes" / NODE_ID / "candidate"
    candidate_dir.mkdir(parents=True)
    candidate = candidate_dir / "candidate.so"
    promotion._compile_candidate(
        promotion.CANDIDATE_SOURCE,
        candidate,
        "ARI_PROBE_ORACLE_ACCESS",
    )
    workspace = WorkspaceRefV1(root=str(candidate_dir))
    declaration = promotion.HarnessTargetDeclarationV1.create(
        logical_name="candidate.so",
        target_kind="shared-library",
        subject_type="program",
        language="c",
        hardware="cpu",
        architecture=platform.machine(),
        dtype="float64",
        interface_contract=manifest.target_interface_contract,
        target_digest=workspace.file_digest("candidate.so"),
    )
    workspace.atomic_write_text(
        "assurance_target.json", declaration.model_dump_json(indent=2) + "\n"
    )
    admission = SimpleNamespace(
        run_id=RUN_ID,
        research_contract_digest=research_digest,
        capability_binding_lock_digest=canonical_digest("e2e-no-provider"),
        active_harness_lock_digest=baseline.lock_digest,
        modes=SimpleNamespace(assurance="enforce"),
    )
    artifacts = SimpleNamespace(
        admission=admission,
        documents={
            "verification_contract.json": contract.model_dump(mode="json"),
            "baseline_harness_lock.json": baseline.model_dump(mode="json"),
            "harness_catalog_snapshot.json": catalog.model_dump(mode="json"),
        },
    )
    bridge = RQGMAssuranceBridge(artifacts=artifacts, checkpoint_dir=checkpoint)
    node = Node(
        id=NODE_ID,
        parent_id=None,
        depth=0,
        status=NodeStatus.SUCCESS,
        label=NodeLabel.VALIDATION,
        name="certified-native-gemm",
        original_direction=(
            "Verify the exact GEMM shared library under the production lock."
        ),
        metrics={"_scientific_score": 1.0, "certify_pass": 1.0},
        has_real_data=True,
        producer_component_id="generator",
        producer_prompt_hash=canonical_digest("e2e-generator-prompt"),
        producer_epoch_id="epoch-000",
        knowledge_skill_use_digest=canonical_digest("e2e-no-knowledge"),
        capability_binding_lock_digest=admission.capability_binding_lock_digest,
    )
    node.work_dir = str(candidate_dir)
    bridge.assure(node)
    if node.assurance_status != "pass" or node.frontier_class != "scientific_frontier":
        raise RuntimeError("production screen did not admit the E2E candidate")
    bridge.certify(node)
    if (
        node.assurance_status != "pass"
        or node.assurance_tier != "certify"
        or node.frontier_class != "scientific_frontier"
    ):
        raise RuntimeError("production certify did not pass the E2E candidate")
    node.artifacts = [
        {
            "relative_path": candidate.relative_to(checkpoint).as_posix(),
            "digest": workspace.file_digest("candidate.so"),
            "size_bytes": candidate.stat().st_size,
            "media_type": "application/x-sharedlib",
        }
    ]
    certify_path = checkpoint / node.attestation_refs[-1]
    from ari.assurance.models import HarnessAttestationV1

    certify_attestation = HarnessAttestationV1.model_validate_json(
        certify_path.read_text(encoding="utf-8")
    )
    if "certify" not in {item.tier for item in certify_attestation.property_results}:
        raise RuntimeError("final Attestation is not a certify result")
    _write_manuscript_sources(checkpoint, node, certify_attestation)
    os.environ.update(
        {
            "ARI_MANUSCRIPT_RUNTIME_MODE": "enforce",
            "ARI_MANUSCRIPT_ASSURANCE_MODE": "enforce",
            "ARI_MANUSCRIPT_EXPLORATION_MODE": "ari_rqgm",
            "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE": "disabled",
        }
    )
    outcome = prepare_runtime_manuscript(
        checkpoint,
        [node],
        experiment_data={"goal": "certify-to-publication E2E"},
    )
    if outcome is None or not outcome.authoring_ready or outcome.authoring_binding is None:
        raise RuntimeError("certified E2E evidence did not become authoring-ready")
    if outcome.readiness is None or outcome.readiness.publication_verdict != "ready":
        raise RuntimeError("certified E2E evidence did not become publication-ready")
    transition_runtime_manuscript(
        checkpoint,
        "authoring",
        reason_code="fixed_e2e_authoring_started",
        artifact_digests=(outcome.authoring_binding.binding_digest,),
    )
    build = _compile_paper(
        checkpoint,
        outcome.authoring_binding,
        outcome.readiness,
        outcome.context,
        certify_attestation,
    )
    transition_runtime_manuscript(
        checkpoint,
        "authored",
        reason_code="fixed_e2e_authoring_completed",
        artifact_digests=(build.build_digest,),
    )
    reproduction = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "p=Path(sys.argv[1]); "
                "raise SystemExit(0 if p.is_file() and p.stat().st_size > 0 else 1)"
            ),
            str(checkpoint / "paper" / "full_paper.pdf"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    _write_json(
        checkpoint / "ors_phase1.json",
        {
            "schema_version": "ari.e2e-reproduction/v1",
            "executed": True,
            "exit_code": reproduction.returncode,
            "missing": [],
            "error": "" if reproduction.returncode == 0 else "reproduction failed",
            "command_identity": canonical_digest(
                {"operation": "verify-pdf-present", "paper_build": build.build_digest}
            ),
        },
    )
    decision = finalize_runtime_publication(checkpoint)
    if decision is None or decision.decision != "publishable":
        raise RuntimeError("certify-to-publication E2E was blocked")
    decision_path = (
        checkpoint
        / ".ari-manuscript"
        / "attempts"
        / outcome.authoring_binding.attempt_id
        / "publication_decision.json"
    )
    cost = _authoritative_cost(checkpoint)
    report: dict[str, Any] = {
        "schema_version": "ari.certify-publication-e2e-report/v1",
        "run_id": RUN_ID,
        "source_full_commit_sha": manifest.source_full_commit_sha,
        "harness_catalog_snapshot_digest": catalog.snapshot_digest,
        "verification_contract_digest": contract.contract_digest,
        "baseline_harness_lock_digest": baseline.lock_digest,
        "target_digest": certify_attestation.target_digest,
        "certify_attestation_digest": certify_attestation.attestation_digest,
        "manuscript_readiness_digest": outcome.readiness.readiness_digest,
        "paper_build_digest": build.build_digest,
        "publication_decision_digest": decision.decision_digest,
        "publication_decision": decision.decision,
        "verification_cost_measurement_digest": cost["measurement_digest"],
        "physical_node_identity_persisted": False,
    }
    report["report_digest"] = canonical_digest(report)
    _publish_evidence(
        evidence_root=args.evidence_root.resolve(),
        attestation_path=certify_path,
        decision_path=decision_path,
        cost=cost,
        report=report,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=(
            ARI_CORE / "config" / "harnesses" / "evidence" / "production_e2e"
        ),
    )
    args = parser.parse_args(argv)
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
