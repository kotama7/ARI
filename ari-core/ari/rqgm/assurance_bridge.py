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
    harness_inapplicability,
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


def _bounded(text: str) -> str:
    text = " ".join(scrub_host_identity(text).split())
    if len(text) > _MAX_REASON_CHARACTERS:
        text = text[: _MAX_REASON_CHARACTERS - 1] + "…"
    return text


def _failure_reason(exc: BaseException) -> str:
    return _bounded(f"{type(exc).__name__}: {exc}".strip())


def _reason(primary: str, *, skipped: list[str]) -> str:
    """One reason string for the record, however the tier ended.

    EVERY exit carries the skips, not just the clean one. Accumulating them and
    then emitting them only on the fall-through meant a tier that skipped one
    Harness and then hit an error reported the error alone -- which is worse
    than what it replaced, since abandoning the tier at the inapplicable Harness
    had at least recorded that much.

    Bounded and scrubbed like any other reason. The skip note interpolates a
    manifest id out of catalog YAML anyone may extend, and an all-inapplicable
    lock of forty Harnesses produced a 4,908-character note -- ten times the
    cap -- written raw into a checkpoint that can leave with a reproduction
    bundle.
    """
    notes = "; ".join(skipped)
    if primary and notes:
        return _bounded(f"{primary} | not applicable to this target: {notes}")
    if notes:
        return _bounded(f"not applicable to this target: {notes}")
    return primary


#: Properties whose failure is a MEASUREMENT, not a disqualification.
#:
#: A frontier class answers "may this node stand as a scientific result", and
#: not every property failure answers no. A candidate that computes the wrong
#: answer is not admissible; a candidate that computes the RIGHT answer more
#: slowly than a tuned reference is a perfectly good result that happens to
#: score low. Collapsing both into `fail -> debug_frontier` would send every
#: early node to repair: the shipped denominator is a competent blocked kernel
#: and the seed the agent starts from is measured at 0.008-0.02x of it, so a
#: performance-regression verdict is "fail" for essentially every node in the
#: first generations. The scoring path already draws this line -- its validity
#: is correctness and its ranking is the speedup -- and the two must not
#: disagree about what a node IS.
#:
#: FAIL-CLOSED, and named rather than derived. The vocabulary's own
#: `correctness_properties` lists numerical-equivalence and
#: interface-conformance and omits trajectory-equivalence, which IS the stencil
#: verifier's primary property -- using it as the disqualifying set would have
#: quietly stopped a wrong trajectory from disqualifying anything. So this names
#: the exemptions instead, and anything not named here disqualifies when it
#: fails.
#:
#: It lives here rather than in property_vocabulary.yaml because it is a
#: statement about what the FRONTIER does with a verdict, not about what the
#: property is or how it is verified. (It would also move the vocabulary digest,
#: which is pinned by every registration -- true, and not the reason.)
_QUALITY_PROPERTIES = frozenset({"performance-regression"})


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
        # Absolute at the boundary. Every verification path is derived from
        # this one, and `WorkspaceRefV1` refuses a relative root -- so a run
        # launched with a relative checkpoint dir reached the Harness, resolved
        # it, locked it, declared its target, and then recorded
        # `infrastructure_error` on both properties for a reason that had
        # nothing to do with the candidate.
        self.checkpoint_dir = Path(checkpoint_dir).resolve()
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
        self._classify(node, status=status,
                       frontier=self._frontier(status, property_verdicts),
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
            # WORST WINS, as in the screen loop above. One property_id can carry
            # several atoms -- one per required method -- and plain assignment
            # let whichever came last decide. A property with an uncovered
            # method beside a covered one that passed was recorded as "pass",
            # because the pass was written after the inconclusive. The aggregate
            # status was never wrong, so nothing was admitted that should not
            # have been; what was wrong is the per-property verdict that the
            # manuscript and the GUI read.
            previous = node.property_verdicts.get(requirement.property_id)
            if previous is None or _VERDICT_RANK[verdict] > _VERDICT_RANK[previous]:
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
            frontier=self._frontier(status, node.property_verdicts),
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
        not_applicable: list[str] = []
        for locked in self.baseline.harnesses:
            if not set(locked.covered_atom_digests) & required_atoms:
                continue
            manifest = manifests.get(locked.manifest_digest)
            if manifest is None:
                return attestations, "tampered", _reason(
                    "the active lock names a Harness manifest the catalog no "
                    "longer holds", skipped=not_applicable)
            # A LOCK IS RESOLVED FOR A CONTRACT; A NODE MAKES ONE ARTIFACT.
            #
            # So a lock holds Harnesses this candidate cannot be handed, and the
            # shipped catalog is that shape: `hpc/gemm-performance` scores
            # benchmark submissions, and every candidate ABI this system can
            # produce declares a shared library, so it is inapplicable to all of
            # them. Reaching for one anyway raised a request error, and a
            # request error abandoned the TIER -- every Harness after it went
            # unrun.
            #
            # MEASURED, so as not to overstate it: on the shipped catalog the
            # verdict does not move. The lock sorts by harness id, which puts
            # gemm-correctness before gemm-performance, so the inapplicable one
            # is last and nothing follows it to be lost. The defect is real but
            # latent, waiting on an id that sorts the other way, and what
            # changes today is the record -- "this Harness cannot judge this
            # artifact" is a fact about the pairing, not a request failure.
            #
            # Skipping cannot loosen anything: the skipped Harness's atoms stay
            # uncovered, so they read inconclusive and the tier can be no better
            # than that.
            inapplicable = harness_inapplicability(
                manifest=manifest, declaration=declaration)
            if inapplicable:
                not_applicable.append(f"{manifest.id}: {inapplicable}")
                continue
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
                return attestations, "inconclusive", _reason(
                    _failure_reason(exc), skipped=not_applicable)
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
                return attestations, "infrastructure_error", _reason(
                    _failure_reason(exc), skipped=not_applicable)
        # A skip is reported even when everything that DID run passed, because
        # the tier covered less than the lock provides and the record should
        # say so rather than reading as a clean sweep.
        return attestations, "", _reason("", skipped=not_applicable)

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

    def _frontier(self, status: str, property_verdicts: dict | None = None) -> str:
        if self.admission.modes.assurance == "audit":
            return "scientific_frontier"
        if status == "pass":
            return "scientific_frontier"
        if status == "fail":
            # WHICH property failed decides whether this is a repair or a
            # result. A wrong answer is a defect to debug; a correct answer that
            # is slower than the reference is the finding itself.
            failed = {name for name, verdict in (property_verdicts or {}).items()
                      if verdict == "fail"}
            if failed and failed <= _QUALITY_PROPERTIES:
                return "scientific_frontier"
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
                # WHY, when the status alone does not say. An infrastructure
                # failure is about the machinery, and used to be recorded as one
                # indistinguishable word for every way the machinery can break.
                #
                # Usually empty on a pass or a fail, which are about the
                # candidate and need no excuse -- but not always: a tier that
                # skipped a Harness it could not apply carries that note even
                # when everything which ran passed, because the tier covered
                # less than the lock provides.
                "status_reason": reason,
            },
        )


__all__ = ["RQGMAssuranceBridge"]
