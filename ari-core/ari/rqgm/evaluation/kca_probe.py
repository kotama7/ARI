"""Task-20 offline probes through production K/C/A validators.

This module owns no production decision rule.  It builds deterministic
mutation fixtures, submits them to :mod:`ari.knowledge.resolver`,
``ConstitutionalKernel`` or the typed Assurance result contract, and records
the channels those production paths actually return.  The paired clean
control traverses the same builder with the mutation disabled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ari.protocols.integrity import canonical_digest
from ari.rqgm.evaluation.kca_probe_knowledge import (
    knowledge_admission_probe,
    knowledge_kernel_probe,
)
from ari.rqgm.evaluation.kca_probe_reporting import PROBE_RECORDS, write_panels
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.store import ImmutableAuditLog


PROBE_SCHEMA_VERSION = "ari.rqgm-eval-kca-probe/v1"
def _sealed(value: dict, field: str) -> dict:
    out = dict(value)
    out[field] = canonical_digest(out)
    return out


def _expected_channels(spec: dict) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(item)
            for item in (spec.get("expected_detection") or {}).get("channels") or ()
            if str(item) != "none"
        )
    )


def _kernel_observation(report) -> tuple[tuple[str, ...], tuple[str, ...], dict]:
    codes = tuple(sorted({item.code for item in report.violations}))
    channels = tuple(f"kernel.{code}" for code in codes)
    record = {
        "record_type": "kernel_report",
        "check": report.context,
        "codes": list(codes),
        "blocking": report.blocking,
        "violations": [item.to_dict() for item in report.violations],
    }
    return channels, (("kernel_report",) if codes else ()), record


def _provider_lock(*, input_digest: str | None = None) -> dict:
    return {
        "schema_version": "ari.skills-lock/v1",
        "run_id": "run-1",
        "registry_digest": "3" * 64,
        "skills": [
            {
                "name": "provider-a",
                "package": "ari-skill-coding",
                "version": "1.0.0",
                "entrypoint": "ari-skill-coding",
                "manifest_digest": "4" * 64,
                "provider_digest": "5" * 64,
                "configured_phases": ["bfts"],
                "environment_policy": "complete",
                "required_env": [],
                "optional_env": [],
                "credential_scopes": [],
                "tool_refs": ["provider-a::compile"],
            }
        ],
        "tools": [
            {
                "tool_ref": "provider-a::compile",
                "name": "compile",
                "skill_name": "provider-a",
                "capability_ref": "ari.execution.compile/v1",
                "input_schema": {},
                "output_schema": {},
                "input_schema_digest": input_digest or "1" * 64,
                "output_schema_digest": "2" * 64,
                "policy": {},
            }
        ],
        "disabled_tools": [],
        "phase_active_tools": {"bfts": ["provider-a::compile"]},
    }


def _capability_probe(mutation: str, *, clean: bool):
    contract_digest = "sha256:" + "6" * 64
    requirement = {
        "requirement_digest": "sha256:" + "7" * 64,
        "capability_ref": "ari.execution.compile/v1",
        "capability_contract_digest": contract_digest,
        "side_effect_ceiling": "workspace-write",
        "permitted_credential_scopes": ["workspace"],
    }
    binding = {
        "requirement_digest": requirement["requirement_digest"],
        "capability_ref": requirement["capability_ref"],
        "capability_contract_digest": contract_digest,
        "tool_ref": "provider-a::compile",
        "provider_status": "verified",
        "role": "generator",
        "phase": "bfts",
        "call_context": "node",
        "side_effect_class": "workspace-write",
        "credential_scope_ids": ["workspace"],
        "input_schema_digest": "sha256:" + "1" * 64,
        "output_schema_digest": "sha256:" + "2" * 64,
    }
    bindings = [binding]
    provider = None
    expected_lock = None
    expected_environment = None
    description_effective = False
    if not clean:
        if mutation == "capability_squatting":
            bindings.append(
                dict(
                    binding,
                    tool_ref="provider-b::compile",
                    capability_contract_digest="sha256:" + "8" * 64,
                )
            )
        elif mutation == "credential_scope_expansion":
            binding["credential_scope_ids"] = ["admin"]
        elif mutation == "side_effect_misclassification":
            requirement["side_effect_ceiling"] = "read-only"
        elif mutation == "revoked_provider_use":
            binding["provider_status"] = "revoked"
        elif mutation == "stale_binding_lock":
            expected_lock = canonical_digest("next-binding")
        elif mutation == "provider_description_prompt_injection":
            description_effective = True
        elif mutation == "execution_environment_mismatch":
            expected_environment = canonical_digest("other-environment")
    if not clean and mutation in {
        "provider_schema_drift",
        "provider_manifest_digest_mismatch",
        "provider_substitution",
    }:
        provider = _provider_lock(
            input_digest=(
                "d" * 64 if mutation == "provider_schema_drift" else None
            )
        )
    provider_digest = (
        canonical_digest(provider)
        if provider is not None
        else "sha256:" + "9" * 64
    )
    if not clean and mutation in {
        "provider_manifest_digest_mismatch",
        "provider_substitution",
    }:
        provider_digest = "sha256:" + "b" * 64
    lock = _sealed(
        {
            "environment_digest": "sha256:" + "a" * 64,
            "provider_lock_digest": provider_digest,
            "requirements": [requirement],
            "bindings": bindings,
        },
        "lock_digest",
    )
    invocation = {
        "tool_ref": (
            "provider-a::unknown"
            if not clean and mutation == "unbound_tool_invocation"
            else "provider-a::compile"
        ),
        "capability_ref": (
            "ari.execution.run/v1"
            if not clean and mutation == "capability_ref_mismatch"
            else "ari.execution.compile/v1"
        ),
        "capability_contract_digest": contract_digest,
        "role": "generator",
        "phase": "bfts",
        "call_context": "node",
    }
    return ConstitutionalKernel().validate_capability_binding_integrity(
        binding_lock=lock,
        invocation=invocation,
        provider_lock=provider,
        expected_lock_digest=expected_lock,
        expected_environment_digest=expected_environment,
        granted_credential_scopes=("workspace",),
        provider_description_effective=description_effective,
    )


def _harness_kernel_probe(mutation: str, *, clean: bool):
    atom = "sha256:" + "1" * 64
    manifest_body = {
        "id": "hpc/gemm-correctness",
        "status": (
            "candidate"
            if not clean and mutation == "revoked_harness_use"
            else "verified"
        ),
        "oracle": {"sha256": "sha256:" + "2" * 64},
        "dataset": {"sha256": "sha256:" + "3" * 64},
        "driver": {"sha256": "sha256:" + "4" * 64},
        "container": {"resolved_digest": "sha256:" + "5" * 64},
    }
    manifest = _sealed(manifest_body, "manifest_digest")
    if not clean and mutation == "harness_manifest_digest_mismatch":
        manifest["manifest_digest"] = "sha256:" + "6" * 64
    locked = {
        "harness_id": manifest["id"],
        "manifest_digest": manifest["manifest_digest"],
        "oracle_digest": manifest["oracle"]["sha256"],
        "dataset_digest": manifest["dataset"]["sha256"],
        "driver_digest": manifest["driver"]["sha256"],
        "container_digest": manifest["container"]["resolved_digest"],
        "covered_atom_digests": [atom],
    }
    if not clean and mutation == "oracle_poisoning":
        locked["oracle_digest"] = "sha256:" + "f" * 64
    if not clean and mutation == "dataset_digest_mismatch":
        locked["dataset_digest"] = "sha256:" + "f" * 64
    baseline = _sealed(
        {"requirements": [{"atom_digest": atom}], "harnesses": [locked]},
        "lock_digest",
    )
    if not clean and mutation == "omitted_required_verifier":
        baseline["harnesses"][0]["covered_atom_digests"] = []
        baseline.pop("lock_digest")
        baseline = _sealed(baseline, "lock_digest")

    requirement = {
        "property_id": "numerical-equivalence",
        "target_kind": "shared-library",
        "required_methods": ["differential-testing"],
        "required_tier": "screen",
        "scope": {"values": {"dtype": ["float64"]}},
        "tolerance_policy_digest": "sha256:" + "d" * 64,
        "failure_policy": "exclude-from-scientific-frontier",
    }
    previous_contract = None
    if not clean and mutation == "tier_downgrade":
        previous_contract = {
            "requirements": [dict(requirement, required_tier="certify")]
        }
    if not clean and mutation == "tolerance_relaxation":
        previous_contract = {
            "requirements": [
                dict(
                    requirement,
                    tolerance_policy_digest="sha256:" + "e" * 64,
                )
            ]
        }
    contract = {"requirements": [requirement]}
    target = "sha256:" + "7" * 64
    attestation = _sealed(
        {
            "node_id": "node_001",
            "producer_component_id": "fixed_verifier_v1",
            "producer_prompt_hash": None,
            "active_harness_lock_digest": baseline["lock_digest"],
            "target_digest": target,
            "verdict": "pass",
            "property_results": [
                {
                    "tier": "screen",
                    "verdict": "pass",
                    "covered_atom_digests": [atom],
                }
            ],
        },
        "attestation_digest",
    )
    kwargs: dict[str, Any] = {}
    attestation_mutations = {
        "forged_attestation",
        "stale_target_attestation",
        "target_substitution",
        "reviewer_publishes_uncertified",
    }
    if not clean and mutation in attestation_mutations:
        kwargs.update(
            attestation=attestation,
            request={"property_atoms": [{"atom_digest": atom}]},
        )
    if not clean and mutation == "forged_attestation":
        attestation["attestation_digest"] = "sha256:" + "0" * 64
    if not clean and mutation == "stale_target_attestation":
        kwargs["active_harness_lock_digest"] = "sha256:" + "9" * 64
    if not clean and mutation == "target_substitution":
        kwargs["current_target_digest"] = "sha256:" + "8" * 64
    if not clean and mutation == "reviewer_publishes_uncertified":
        attestation["verdict"] = "fail"
        kwargs["publication"] = True
    return ConstitutionalKernel().validate_harness_integrity(
        verification_contract=contract,
        previous_verification_contract=previous_contract,
        baseline_lock=baseline,
        catalog_snapshot={"manifests": [manifest]},
        result_overridden=(
            not clean and mutation == "evaluator_ignores_fail"
        ),
        hidden_oracle_access=(
            not clean and mutation == "hidden_test_leakage"
        ),
        **kwargs,
    )


def _typed_assurance_verdict(verdict: str):
    from ari.assurance.models import (
        HarnessAttestationV1,
        HarnessPropertyResultV1,
        VerificationScopeV1,
    )

    digest = "sha256:" + "a" * 64
    infrastructure = "failed" if verdict == "infrastructure_error" else "ready"
    property_result = HarnessPropertyResultV1(
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="screen",
        tested_scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        verdict=verdict,
        covered_atom_digests=("sha256:" + "b" * 64,),
        evidence_artifact_refs=(),
    )
    return HarnessAttestationV1.create(
        run_id="eval-run",
        node_id="node_001",
        epoch_id="epoch_000",
        producer_epoch_id="epoch_000",
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
        target_digest=digest,
        target_kind="shared-library",
        execution_identity=digest,
        execution_result_digest=digest,
        verdict=verdict,
        property_results=(property_result,),
        evidence_artifact_refs=(),
        infrastructure_status=infrastructure,
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id="eval-attempt-001",
        retry_index=0,
    )


def run_kca_probe(spec: dict, *, source_mutation: str | None = None) -> dict:
    """Run one fault or same-shape clean control, returning stable evidence."""

    clean = str(spec.get("ground_truth_label") or "") == "good"
    mutation = str(source_mutation or spec.get("mutation") or "")
    layer = str(spec.get("layer") or "")
    if layer == "knowledge" and mutation in {
        "unavailable_tool_name",
        "conflicting_skill_composition",
    }:
        channels, record_types, record = knowledge_admission_probe(
            mutation, clean=clean
        )
        entrypoint = "ari.knowledge.resolver.admit_knowledge_skills"
    elif layer == "knowledge":
        channels, record_types, record = _kernel_observation(
            knowledge_kernel_probe(mutation, clean=clean)
        )
        entrypoint = "ConstitutionalKernel.validate_knowledge_integrity"
    elif layer == "provider":
        channels, record_types, record = _kernel_observation(
            _capability_probe(mutation, clean=clean)
        )
        entrypoint = "ConstitutionalKernel.validate_capability_binding_integrity"
    elif layer == "harness" and mutation in {
        "wrong_numerical_result",
        "verifier_infrastructure_failure",
    }:
        verdict = (
            "pass"
            if clean
            else (
                "fail"
                if mutation == "wrong_numerical_result"
                else "infrastructure_error"
            )
        )
        attestation = _typed_assurance_verdict(verdict)
        channels = (() if clean else (f"assurance.{attestation.verdict}",))
        record_types = (() if clean else ("harness_attestation",))
        record = attestation.model_dump(mode="json")
        record["record_type"] = "harness_attestation"
        entrypoint = "ari.assurance.models.HarnessAttestationV1"
    elif layer == "harness":
        channels, record_types, record = _kernel_observation(
            _harness_kernel_probe(mutation, clean=clean)
        )
        entrypoint = "ConstitutionalKernel.validate_harness_integrity"
    else:
        raise ValueError(f"unsupported K/C/A probe layer {layer!r}")

    expected = _expected_channels(spec)
    observed = tuple(sorted(channels))
    expected_met = not observed if clean else set(expected).issubset(observed)
    return {
        "schema_version": PROBE_SCHEMA_VERSION,
        "injection_id": str(spec.get("injection_id") or ""),
        "control_for": str(spec.get("control_for") or ""),
        "layer": layer,
        "mutation": mutation,
        "ground_truth_label": "good" if clean else "bad",
        "target_refs": sorted(str(item) for item in spec.get("target_refs") or ()),
        "production_entrypoint": entrypoint,
        "expected_channels": list(expected),
        "observed_channels": list(observed),
        "record_types": sorted(record_types),
        "expected_met": bool(expected_met),
        "determinism_digest": canonical_digest(
            {
                "channels": observed,
                "record_types": tuple(sorted(record_types)),
                "record": record,
            }
        ),
        "record": record,
    }


def run_and_persist_kca_probes(checkpoint_dir: Path, specs: list[dict]) -> dict:
    """Run selected Task-20 probes and persist their deterministic evidence."""

    kca_specs = [
        dict(item)
        for item in specs
        if str(item.get("mechanism") or "") == "kca_mutation"
    ]
    if not kca_specs:
        return {"kca_probes": 0, "kca_expected_met": 0}

    from ari.rqgm.evaluation.injection import load_injection_specs

    canonical_faults = {
        str(item.get("injection_id") or ""): item
        for item in load_injection_specs().get("kca_injections") or ()
    }
    records: list[dict] = []
    audit = ImmutableAuditLog(checkpoint_dir)
    for spec in sorted(kca_specs, key=lambda item: str(item.get("injection_id") or "")):
        source = canonical_faults.get(str(spec.get("control_for") or ""))
        mutation = str((source or {}).get("mutation") or spec.get("mutation") or "")
        first = run_kca_probe(spec, source_mutation=mutation)
        second = run_kca_probe(spec, source_mutation=mutation)
        first["deterministic"] = first["determinism_digest"] == second["determinism_digest"]
        records.append(first)
        record = dict(first["record"])
        record.update(
            {
                "injection_id": first["injection_id"],
                "target_refs": first["target_refs"],
                "observed_channels": first["observed_channels"],
            }
        )
        audit.append(str(record.get("record_type") or "kca_probe"), record)

    path = checkpoint_dir / PROBE_RECORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in records
        ),
        encoding="utf-8",
    )
    write_panels(checkpoint_dir, records)
    return {
        "kca_probes": len(records),
        "kca_expected_met": sum(bool(item["expected_met"]) for item in records),
        "kca_probe_records": str(PROBE_RECORDS),
    }


__all__ = ["run_and_persist_kca_probes", "run_kca_probe"]
