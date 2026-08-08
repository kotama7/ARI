"""RQGM integration of fixed assurance outcomes and frontier eligibility."""

from __future__ import annotations

import re
from pathlib import Path

from ari import cost_tracker
from ari.assurance.drivers import builtin_driver_map
from ari.assurance.executors import PinnedContainerExecutor
from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessAttestationV1,
    HarnessCatalogSnapshotV1,
    VerificationContractV1,
)
from ari.assurance.request import (
    HarnessRequestError,
    build_native_harness_run_request,
    load_target_declaration,
)
from ari.assurance.runner import FixedVerifier
from ari.execution import WorkspaceRefV1
from ari.orchestrator.node_summary_view import scrub_host_identity
from ari.protocols.immutable_store import write_once_json

#: A reason is a diagnostic, so it is bounded and stripped of host identity.
#:
#: It is written into the checkpoint and can leave with a reproduction bundle,
#: and the messages that reach it quote absolute paths -- an unreadable image,
#: a missing executable, a compiler invocation. The same four substitutions the
#: agent-facing boundary makes, for the same reason.
_MAX_REASON_CHARACTERS = 480


def _failure_reason(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    text = " ".join(scrub_host_identity(text).split())
    if len(text) > _MAX_REASON_CHARACTERS:
        text = text[: _MAX_REASON_CHARACTERS - 1] + "…"
    return text


_VERDICT_RANK = {
    "pass": 0,
    "inconclusive": 1,
    "infrastructure_error": 2,
    "fail": 3,
    "tampered": 4,
}


class RQGMAssuranceBridge:
    """Execute frozen Harnesses and translate verdicts without re-judging them."""

    def __init__(
        self,
        *,
        artifacts,
        checkpoint_dir: str | Path,
        executor=None,
        drivers=None,
    ) -> None:
        self.admission = artifacts.admission
        self.documents = artifacts.documents
        self.checkpoint_dir = Path(checkpoint_dir)
        self.contract = VerificationContractV1.model_validate(
            self.documents["verification_contract.json"]
        )
        self.baseline = BaselineHarnessLockV1.model_validate(
            self.documents["baseline_harness_lock.json"]
        )
        self.catalog = HarnessCatalogSnapshotV1.model_validate(
            self.documents["harness_catalog_snapshot.json"]
        )
        driver_map = builtin_driver_map()
        driver_map.update(dict(drivers or {}))
        self._cost_tracker = cost_tracker.init(self.checkpoint_dir)
        self.verifier = FixedVerifier(
            driver_map,
            executor=executor or PinnedContainerExecutor(),
            execution_observer=self._record_verification_cost,
        )

    def _record_verification_cost(
        self,
        manifest,
        request,
        execution_result,
        attestation,
    ) -> None:
        """Persist verifier duration/resources without changing its verdict.

        Accounting is post-attestation telemetry.  A trace-write failure is
        retained as a typed node artifact, but it cannot convert a scientific
        pass/fail into an infrastructure error.
        """

        tiers = {item.tier for item in request.property_atoms}
        if len(tiers) != 1:
            raise ValueError("Harness execution must contain exactly one assurance tier")
        tier = tiers.pop()
        backend = (
            execution_result.container.runtime
            if execution_result.container is not None
            else "local-process"
        )
        try:
            self._cost_tracker.record_verification(
                node_id=request.node_id,
                epoch=request.epoch_id,
                tier=tier,
                harness_id=manifest.id,
                execution_identity=execution_result.execution_identity,
                execution_attempt_id=execution_result.attempt_id,
                attestation_digest=attestation.attestation_digest,
                execution_status=execution_result.status,
                started_at=execution_result.started_at,
                completed_at=execution_result.completed_at,
                cpu_cores=manifest.resources.cpu_cores,
                accelerators=manifest.resources.accelerators,
                memory_bytes=manifest.resources.memory_bytes,
                backend=backend,
            )
        except Exception as exc:
            write_once_json(
                self._node_root_from_id(request.node_id)
                / "verification_cost_errors"
                / f"{request.attempt_id}.json",
                {
                    "schema_version": "ari.verification-cost-error/v1",
                    "run_id": request.run_id,
                    "node_id": request.node_id,
                    "epoch_id": request.epoch_id,
                    "attempt_id": request.attempt_id,
                    "harness_id": manifest.id,
                    "attestation_digest": attestation.attestation_digest,
                    "error_type": type(exc).__name__,
                },
            )

    @staticmethod
    def _status(node) -> str:
        status = getattr(node, "status", "")
        return str(getattr(status, "value", status) or "")

    def assure(self, node) -> str:
        """Run the active screen suite and set typed node eligibility fields."""

        if self._status(node) != "success":
            self._classify(
                node,
                status="not-run-execution-failed",
                frontier="debug_frontier",
            )
            return node.frontier_class
        required = tuple(
            item for item in self.baseline.requirements if item.tier == "screen"
        )
        if not required:
            self._classify(node, status="pass", frontier="scientific_frontier")
            return node.frontier_class
        unsatisfied = {
            item.atom_digest
            for item in required
            if item.atom_digest in set(self.baseline.unsatisfied_atom_digests)
        }
        if unsatisfied:
            node.property_verdicts = {
                item.property_id: "inconclusive"
                for item in required
                if item.atom_digest in unsatisfied
            }
            self._classify(
                node,
                status="inconclusive",
                frontier=self._frontier("inconclusive"),
            )
            return node.frontier_class

        workspace, declaration, preflight_status = self._candidate_target(node)
        if preflight_status:
            self._classify(
                node,
                status=preflight_status,
                frontier=self._frontier(preflight_status),
            )
            return node.frontier_class

        attestations, runtime_failure, failure_reason = self._run_tier_suite(
            node, workspace, declaration, required, tier="screen"
        )

        by_atom: dict[str, list[str]] = {}
        for attestation in attestations:
            for result in attestation.property_results:
                for atom_digest in result.covered_atom_digests:
                    by_atom.setdefault(atom_digest, []).append(result.verdict)
        missing = {
            item.atom_digest for item in required
        } - set(by_atom)
        if missing and not runtime_failure:
            runtime_failure = "inconclusive"
        property_verdicts: dict[str, str] = {}
        aggregate: list[str] = []
        for requirement in required:
            verdicts = by_atom.get(requirement.atom_digest, ())
            verdict = (
                max(verdicts, key=lambda item: _VERDICT_RANK[item])
                if verdicts
                else runtime_failure or "inconclusive"
            )
            previous = property_verdicts.get(requirement.property_id)
            if previous is None or _VERDICT_RANK[verdict] > _VERDICT_RANK[previous]:
                property_verdicts[requirement.property_id] = verdict
            aggregate.append(verdict)
        status = (
            max(aggregate, key=lambda item: _VERDICT_RANK[item])
            if aggregate
            else runtime_failure or "inconclusive"
        )
        node.property_verdicts = property_verdicts
        node.verified_target_digest = declaration.target_digest
        self._classify(node, status=status, frontier=self._frontier(status),
                       reason=failure_reason)
        return node.frontier_class

    def certify(self, node) -> str:
        """Run the frozen certify suite for the current scientific candidate."""

        if self._status(node) != "success":
            return str(getattr(node, "frontier_class", "") or "debug_frontier")
        if (
            str(getattr(node, "assurance_status", "") or "") != "pass"
            or str(getattr(node, "frontier_class", "") or "")
            != "scientific_frontier"
        ):
            return str(getattr(node, "frontier_class", "") or "uncertified_frontier")
        required = tuple(
            item for item in self.baseline.requirements if item.tier == "certify"
        )
        if not required:
            return node.frontier_class
        unsatisfied = {
            item.atom_digest
            for item in required
            if item.atom_digest in set(self.baseline.unsatisfied_atom_digests)
        }
        if unsatisfied:
            node.property_verdicts.update(
                {
                    item.property_id: "inconclusive"
                    for item in required
                    if item.atom_digest in unsatisfied
                }
            )
            self._classify(
                node,
                status="inconclusive",
                frontier=self._frontier("inconclusive"),
                tier="certify",
            )
            return node.frontier_class
        workspace, declaration, preflight_status = self._candidate_target(node)
        if preflight_status:
            self._classify(
                node,
                status=preflight_status,
                frontier=self._frontier(preflight_status),
                tier="certify",
            )
            return node.frontier_class
        attestations, runtime_failure, failure_reason = self._run_tier_suite(
            node, workspace, declaration, required, tier="certify"
        )
        by_atom: dict[str, list[str]] = {}
        for attestation in attestations:
            for result in attestation.property_results:
                for atom_digest in result.covered_atom_digests:
                    by_atom.setdefault(atom_digest, []).append(result.verdict)
        missing = {item.atom_digest for item in required} - set(by_atom)
        if missing and not runtime_failure:
            runtime_failure = "inconclusive"
        aggregate: list[str] = []
        for requirement in required:
            verdicts = by_atom.get(requirement.atom_digest, ())
            verdict = (
                max(verdicts, key=lambda item: _VERDICT_RANK[item])
                if verdicts
                else runtime_failure or "inconclusive"
            )
            node.property_verdicts[requirement.property_id] = verdict
            aggregate.append(verdict)
        status = (
            max(aggregate, key=lambda item: _VERDICT_RANK[item])
            if aggregate
            else runtime_failure or "inconclusive"
        )
        node.verified_target_digest = declaration.target_digest
        self._classify(
            node,
            status=status,
            frontier=self._frontier(status),
            tier="certify",
            reason=failure_reason,
        )
        return node.frontier_class

    def _run_tier_suite(
        self, node, workspace, declaration, required, *, tier: str
    ):
        manifests = {item.manifest_digest: item for item in self.catalog.manifests}
        required_atoms = {item.atom_digest for item in required}
        attestations: list[HarnessAttestationV1] = []
        for locked in self.baseline.harnesses:
            if not set(locked.covered_atom_digests) & required_atoms:
                continue
            manifest = manifests.get(locked.manifest_digest)
            if manifest is None:
                return attestations, "tampered"
            try:
                attestations.append(
                    self._verify_locked(
                        node,
                        workspace,
                        declaration,
                        manifest,
                        locked,
                        tier=tier,
                    )
                )
            except HarnessRequestError as exc:
                return attestations, "inconclusive", _failure_reason(exc)
            except Exception as exc:
                # THE REASON, NOT JUST THE LABEL. This used to be a bare
                # `except Exception:`, so the one string that said WHY was
                # discarded here and the record carried "infrastructure_error"
                # and nothing else. Two unrelated defects -- a container runtime
                # that is installed nowhere, and a memory bound too small for
                # the launcher to start -- came out as that same word, and
                # finding out which took replaying the execution by hand.
                #
                # The verdict is unchanged: this is still an infrastructure
                # failure and still not a judgement about the candidate. Only
                # the record gains what was already in hand.
                return attestations, "infrastructure_error", _failure_reason(exc)
        return attestations, "", ""

    def _candidate_target(self, node):
        work_dir = Path(str(getattr(node, "work_dir", "") or ""))
        if not work_dir.is_absolute() or not work_dir.is_dir() or work_dir.is_symlink():
            return None, None, "inconclusive"
        workspace = WorkspaceRefV1(root=str(work_dir))
        try:
            return workspace, load_target_declaration(workspace), ""
        except FileNotFoundError:
            return None, None, "inconclusive"
        except Exception:
            return None, None, "tampered"

    def _verify_locked(
        self, node, workspace, declaration, manifest, locked, *, tier: str = "screen"
    ):
        epoch_id = str(getattr(node, "producer_epoch_id", "") or "epoch_000")
        node_root = self._node_root(node)
        request = build_native_harness_run_request(
            run_id=self.admission.run_id,
            node_id=str(node.id),
            epoch_id=epoch_id,
            workspace=workspace,
            execution_workspace=WorkspaceRefV1(
                root=str(
                    node_root
                    / "verification-workspaces"
                    / locked.harness_id.replace("/", "_")
                )
            ),
            declaration=declaration,
            manifest=manifest,
            locked=locked,
            baseline=self.baseline,
            tier=tier,
        )
        write_once_json(
            node_root
            / "harness_requests"
            / f"{locked.harness_id.replace('/', '_')}-{tier}.json",
            request,
        )
        attestation = self.verifier.run(
            manifest=manifest,
            request=request,
            baseline_lock=self.baseline,
            research_contract_digest=self.admission.research_contract_digest,
            verification_contract_digest=self.contract.contract_digest,
            knowledge_skill_use_digest=(
                str(getattr(node, "knowledge_skill_use_digest", "") or "")
                or "sha256:" + "0" * 64
            ),
            capability_binding_lock_digest=(
                self.admission.capability_binding_lock_digest
                or "sha256:" + "0" * 64
            ),
            producer_epoch_id=epoch_id,
        )
        relative = (
            Path("rqgm")
            / "kca"
            / "nodes"
            / str(node.id)
            / "attestations"
            / f"{attestation.attestation_digest.removeprefix('sha256:')}.json"
        )
        write_once_json(self.checkpoint_dir / relative, attestation)
        node.attestation_refs.append(relative.as_posix())
        return attestation

    def _frontier(self, status: str) -> str:
        if self.admission.modes.assurance == "audit":
            return "scientific_frontier"
        if status == "pass":
            return "scientific_frontier"
        if status == "fail":
            return "debug_frontier"
        return "uncertified_frontier"

    def _node_root(self, node) -> Path:
        return self._node_root_from_id(str(node.id))

    def _node_root_from_id(self, node_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", node_id):
            raise ValueError("unsafe node identity for assurance provenance")
        return self.checkpoint_dir / "rqgm" / "kca" / "nodes" / node_id

    def _classify(
        self, node, *, status: str, frontier: str, tier: str = "screen",
        reason: str = "",
    ) -> None:
        node.assurance_status = status
        node.assurance_tier = tier
        node.frontier_class = frontier
        summary_name = (
            "assurance_summary.json"
            if tier == "screen"
            else f"assurance_summary_{tier}.json"
        )
        write_once_json(
            self._node_root(node) / summary_name,
            {
                "schema_version": "ari.rqgm-assurance-summary/v1",
                "run_id": self.admission.run_id,
                "node_id": str(node.id),
                "verification_contract_digest": self.contract.contract_digest,
                "baseline_harness_lock_digest": self.baseline.lock_digest,
                "active_harness_lock_digest": self.admission.active_harness_lock_digest,
                "assurance_status": node.assurance_status,
                "assurance_tier": node.assurance_tier,
                "property_verdicts": dict(node.property_verdicts),
                "frontier_class": node.frontier_class,
                "attestation_refs": list(node.attestation_refs),
                "verified_target_digest": str(node.verified_target_digest or ""),
                # WHY, when the status alone does not say. Empty on every
                # ordinary verdict: a pass or a fail is about the candidate and
                # needs no excuse, while an infrastructure failure is about the
                # machinery and used to be recorded as one indistinguishable
                # word for every way the machinery can break.
                "status_reason": reason,
            },
        )


__all__ = ["RQGMAssuranceBridge"]
