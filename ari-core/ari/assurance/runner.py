"""Fixed-verifier execution over an already-minted Harness Lock."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ari.assurance.attestation import validate_attestation
from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessManifestV1,
    HarnessRunRequestV1,
    NormalizedHarnessResultV1,
)
from ari.execution import ExecutionResultV1, execute_local
from ari.protocols.assurance import HarnessDriverProtocol
from ari.protocols.integrity import canonical_digest


class HarnessExecutionError(RuntimeError):
    pass


class FixedVerifier:
    """Prompt-free verifier; selection and persistence stay outside this class."""

    component_id = "fixed_verifier_v1"
    prompt_hash = None

    def __init__(
        self,
        drivers: dict[str, HarnessDriverProtocol],
        *,
        executor: Callable[..., ExecutionResultV1] = execute_local,
        execution_observer: Callable[
            [
                HarnessManifestV1,
                HarnessRunRequestV1,
                ExecutionResultV1,
                HarnessAttestationV1,
            ],
            None,
        ]
        | None = None,
    ) -> None:
        self._drivers = dict(drivers)
        self._executor = executor
        self._execution_observer = execution_observer

    def run(
        self,
        *,
        manifest: HarnessManifestV1,
        request: HarnessRunRequestV1,
        baseline_lock: BaselineHarnessLockV1,
        research_contract_digest: str,
        verification_contract_digest: str,
        knowledge_skill_use_digest: str,
        capability_binding_lock_digest: str,
        producer_epoch_id: str,
        network_isolation_verified: bool = False,
    ) -> HarnessAttestationV1:
        if request.execution_request.request_id != request.attempt_id:
            raise HarnessExecutionError("Execution request_id must equal locked attempt_id")
        if request.harness.manifest_digest != manifest.manifest_digest:
            raise HarnessExecutionError("Harness Manifest differs from lock")
        if request.harness not in baseline_lock.harnesses:
            raise HarnessExecutionError("Harness is absent from baseline lock")
        if request.active_harness_lock_digest != baseline_lock.lock_digest:
            # Revision support passes the revision digest and a separately validated active view.
            raise HarnessExecutionError("baseline verifier requires active baseline lock")
        current_target = request.target_workspace.file_digest(request.target_logical_name)
        if current_target != request.target_digest:
            raise HarnessExecutionError("candidate target changed before verification")
        driver = self._drivers.get(manifest.driver.revision)
        if driver is None:
            raise HarnessExecutionError("locked Harness driver is unavailable")
        identity = driver.identity()
        if identity.get("driver_digest") != request.harness.driver_digest:
            raise HarnessExecutionError("Harness driver identity drift")
        driver.prepare(manifest, request)
        built = driver.build_request(manifest, request)
        if built != request.execution_request:
            raise HarnessExecutionError("driver attempted to change locked ExecutionRequest")
        try:
            execution_result = self._executor(
                built,
                network_isolation_verified=network_isolation_verified,
            )
            self._validate_execution_result(built, execution_result)
            normalized_raw = driver.normalize_result(manifest, request, execution_result)
            normalized = NormalizedHarnessResultV1.model_validate(normalized_raw)
        except Exception as exc:
            raise HarnessExecutionError(f"locked Harness execution failed: {exc}") from exc
        after_target = request.target_workspace.file_digest(request.target_logical_name)
        if after_target != request.target_digest:
            raise HarnessExecutionError("candidate target changed during verification")
        attestation = HarnessAttestationV1.create(
            run_id=request.run_id,
            node_id=request.node_id,
            epoch_id=request.epoch_id,
            producer_epoch_id=producer_epoch_id,
            research_contract_digest=research_contract_digest,
            verification_contract_digest=verification_contract_digest,
            knowledge_skill_use_digest=knowledge_skill_use_digest,
            capability_binding_lock_digest=capability_binding_lock_digest,
            baseline_harness_lock_digest=baseline_lock.lock_digest,
            active_harness_lock_digest=request.active_harness_lock_digest,
            harness_manifest_digest=manifest.manifest_digest,
            driver_digest=manifest.driver.sha256,
            oracle_digest=manifest.oracle.sha256,
            dataset_digest=manifest.dataset.sha256,
            container_digest=manifest.container.resolved_digest,
            target_logical_name=request.target_logical_name,
            target_digest=request.target_digest,
            target_kind=request.target_kind,
            execution_identity=execution_result.execution_identity,
            execution_result_digest=canonical_digest(execution_result),
            verdict=normalized.verdict,
            property_results=normalized.property_results,
            evidence_artifact_refs=normalized.evidence_artifact_refs,
            infrastructure_status=normalized.infrastructure_status,
            nondeterminism_declaration=manifest.nondeterminism_declaration,
            nondeterminism_observations=normalized.nondeterminism_observations,
            attempt_id=request.attempt_id,
            retry_index=request.retry_index,
        )
        validate_attestation(
            attestation=attestation,
            request=request,
            baseline_lock=baseline_lock,
            current_target_digest=after_target,
        )
        if self._execution_observer is not None:
            self._execution_observer(
                manifest,
                request,
                execution_result,
                attestation,
            )
        return attestation

    @staticmethod
    def _validate_execution_result(
        request: Any,
        result: ExecutionResultV1,
    ) -> None:
        """Reject a well-shaped result that belongs to another execution.

        Container executors may wrap the locked in-container argv, so their
        ``execution_identity`` legitimately commits to the reviewed outer
        launch request rather than ``request.execution_identity``.  The
        immutable identities which must survive that wrapping are checked
        here explicitly.
        """

        if result.request_id != request.request_id:
            raise HarnessExecutionError(
                "Harness execution result belongs to another request"
            )
        if result.input_digests != request.input_digests:
            raise HarnessExecutionError(
                "Harness execution result input digests differ from request"
            )
        if set(result.input_bindings) != set(request.input_digests):
            raise HarnessExecutionError(
                "Harness execution result has incomplete input bindings"
            )
        if any(
            binding == "external-unverified"
            for binding in result.input_bindings.values()
        ):
            raise HarnessExecutionError(
                "Harness execution used an unverified input binding"
            )
        if result.container != request.container:
            raise HarnessExecutionError(
                "Harness execution result container identity differs from request"
            )
        if request.network == "deny" and (
            result.network != "deny" or result.network_report != "isolated"
        ):
            raise HarnessExecutionError(
                "Harness execution did not prove network isolation"
            )


__all__ = ["FixedVerifier", "HarnessExecutionError"]
