"""Opt-in runtime adapter for the fixed manuscript compiler boundary."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ari.manuscript.contracts import RepairBudgetV1
from ari.manuscript.coordinator import (
    ManuscriptAuthoringBlocked,
    ManuscriptOutcome,
    compile_manuscript,
)
from ari.manuscript.digest import file_digest
from ari.manuscript.state import ManuscriptStateStore


_ARTIFACT_ENV = {
    "requirement_profile.json": "ARI_MANUSCRIPT_PROFILE_PATH",
    "context.json": "ARI_MANUSCRIPT_CONTEXT_PATH",
    "readiness.json": "ARI_MANUSCRIPT_READINESS_PATH",
    "section_briefs.json": "ARI_MANUSCRIPT_BRIEFS_PATH",
    "authoring_binding.json": "ARI_MANUSCRIPT_BINDING_PATH",
}


def _runtime_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def prepare_runtime_manuscript(
    checkpoint_dir: str | Path,
    all_nodes: Iterable[Any],
    *,
    experiment_data: dict[str, Any] | None = None,
    block_on_unready: bool = True,
) -> ManuscriptOutcome | None:
    """Compile the current source set and expose its exact artifact paths.

    The caller must invoke this only after evidence preparation and before the
    first authoring call.  In enforce mode an unresolved authoring requirement
    raises here, outside any ordinary paper-stage fail-open boundary.
    """

    mode = os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off").strip().lower()
    if mode == "off":
        return None
    checkpoint = Path(checkpoint_dir).resolve()
    from ari.manuscript.authority import capture_repair_authority

    authority_run_id = checkpoint.name or "unknown-run"
    try:
        tree = json.loads((checkpoint / "tree.json").read_text(encoding="utf-8"))
        authority_run_id = str(tree.get("run_id") or authority_run_id)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    authority = capture_repair_authority(checkpoint, run_id=authority_run_id)
    outcome = compile_manuscript(
        checkpoint,
        all_nodes,
        experiment_data=experiment_data,
        mode=mode,
        profile_id=os.environ.get(
            "ARI_MANUSCRIPT_PROFILE", "generic_empirical_v1"
        ),
        repair_policy=os.environ.get(
            "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE", "disabled"
        ),
        assurance_mode=os.environ.get("ARI_MANUSCRIPT_ASSURANCE_MODE", "off"),
        exploration_mode=os.environ.get(
            "ARI_MANUSCRIPT_EXPLORATION_MODE", "simple_bfts"
        ),
        paper_mode=os.environ.get("ARI_MANUSCRIPT_PAPER_MODE", "linear"),
        brief_character_budget=_runtime_int(
            "ARI_MANUSCRIPT_BRIEF_CHARACTER_BUDGET", 24_000
        ),
        repair_budget=RepairBudgetV1(
            max_rounds=_runtime_int("ARI_MANUSCRIPT_MAX_ROUNDS", 0),
            max_new_nodes=_runtime_int("ARI_MANUSCRIPT_MAX_NEW_NODES", 0),
            max_experiment_runs=_runtime_int(
                "ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS", 0
            ),
            max_llm_calls=_runtime_int("ARI_MANUSCRIPT_MAX_LLM_CALLS", 0),
        ),
        authority=authority,
    )
    for filename, env_name in _ARTIFACT_ENV.items():
        relative = (outcome.artifact_paths or {}).get(filename)
        if relative:
            os.environ[env_name] = str((checkpoint / relative).resolve())
        else:
            os.environ.pop(env_name, None)
    if mode == "enforce" and block_on_unready and not outcome.authoring_ready:
        raise ManuscriptAuthoringBlocked(outcome)
    return outcome


@dataclass(frozen=True)
class RuntimeRepairLoopResult:
    outcome: ManuscriptOutcome
    rounds: int
    termination_reason: str
    used_budget: dict[str, int]


def run_runtime_auto_repair(
    checkpoint_dir: str | Path,
    all_nodes: Iterable[Any],
    *,
    experiment_data: dict[str, Any] | None,
    evidence_rebuilder,
    executors: dict[str, Any],
) -> RuntimeRepairLoopResult:
    """Run the bounded outer compile/repair/rebuild loop.

    Research execution remains an injected outer-runtime adapter; neither a
    paper stage nor an archive candidate can call this function recursively.
    """

    if os.environ.get("ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE") != "auto":
        raise ValueError("automatic manuscript repair is not active")
    checkpoint = Path(checkpoint_dir).resolve()
    max_rounds = _runtime_int("ARI_MANUSCRIPT_MAX_ROUNDS", 0)
    store = ManuscriptStateStore(checkpoint)

    def _transaction_documents() -> list[dict[str, Any]]:
        root = store.root / "repair-transactions"
        documents: list[dict[str, Any]] = []
        if not root.is_dir():
            return documents
        for path in sorted(root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise ValueError(f"invalid persisted repair transaction: {path}")
            if not isinstance(value, dict) or value.get("schema_version") != (
                "ari.manuscript-repair-transaction/v1"
            ):
                raise ValueError(f"unknown persisted repair transaction: {path}")
            documents.append(value)
        return documents

    usage: dict[str, int] = {"new_nodes": 0, "experiment_runs": 0, "llm_calls": 0}
    for document in _transaction_documents():
        details = document.get("details") or {}
        if not isinstance(details, dict):
            raise ValueError("persisted repair transaction details are invalid")
        for key in usage:
            value = int(details.get(key, 0) or 0)
            if value < 0:
                raise ValueError("persisted repair transaction has negative budget use")
            usage[key] += value

    round_root = store.root / "auto-rounds"
    existing_rounds: dict[str, dict[str, Any]] = {}
    if round_root.is_dir():
        for path in sorted(round_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise ValueError(f"invalid persisted automatic repair round: {path}")
            if not isinstance(value, dict) or value.get("schema_version") != (
                "ari.manuscript-auto-repair-round/v1"
            ):
                raise ValueError(f"unknown automatic repair round: {path}")
            plan_digest = str(value.get("plan_digest") or "")
            if not plan_digest or plan_digest in existing_rounds:
                raise ValueError("automatic repair round identity is invalid or duplicated")
            existing_rounds[plan_digest] = value

    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    reconciled_rounds: set[str] = set()
    outcome = prepare_runtime_manuscript(
        checkpoint,
        all_nodes,
        experiment_data=experiment_data,
        block_on_unready=False,
    )
    assert outcome is not None
    reason = "authoring_ready" if outcome.authoring_ready else "round_budget_exhausted"
    completed_rounds = 0
    while True:
        if outcome.authoring_ready:
            reason = "authoring_ready"
            break
        readiness = outcome.readiness
        plan = outcome.repair_plan
        if readiness is None or plan is None or not plan.requests:
            reason = "no_admitted_repair_request"
            break
        vector = tuple(
            (item.requirement_id, item.status)
            for item in readiness.requirement_results
        )
        signature = (readiness.context_digest, vector)
        if signature in seen:
            reason = "no_progress_cycle"
            break
        seen.add(signature)

        # A crash can happen after request side effects commit but before the
        # evidence/context rebuild.  Reconcile that already-recorded round once
        # without invoking any executor again.
        if plan.plan_digest in existing_rounds and plan.plan_digest not in reconciled_rounds:
            reconciled_rounds.add(plan.plan_digest)
            evidence_rebuilder()
            next_outcome = prepare_runtime_manuscript(
                checkpoint,
                all_nodes,
                experiment_data=experiment_data,
                block_on_unready=False,
            )
            assert next_outcome is not None
            next_readiness = next_outcome.readiness
            if (
                next_readiness is not None
                and next_readiness.context_digest == readiness.context_digest
                and tuple(
                    (item.requirement_id, item.status)
                    for item in next_readiness.requirement_results
                )
                == vector
            ):
                outcome = next_outcome
                reason = "no_progress_cycle"
                break
            outcome = next_outcome
            continue

        if len(existing_rounds) >= max_rounds:
            reason = "round_budget_exhausted"
            break
        if (
            usage["new_nodes"] > _runtime_int("ARI_MANUSCRIPT_MAX_NEW_NODES", 0)
            or usage["experiment_runs"]
            > _runtime_int("ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS", 0)
            or usage["llm_calls"] > _runtime_int("ARI_MANUSCRIPT_MAX_LLM_CALLS", 0)
        ):
            reason = "cumulative_budget_exhausted"
            break
        current = store.read_state()
        current_state = str(current.get("state") or "absent")
        if current_state == "blocked_unavailable":
            store.transition(
                run_id=readiness.run_id,
                attempt=str(outcome.attempt_id),
                to_state="repair_pending",
                reason_code="automatic_repair_admitted",
                artifact_digests=(plan.plan_digest,),
            )
            current_state = "repair_pending"
        if current_state == "repair_pending":
            store.transition(
                run_id=readiness.run_id,
                attempt=str(outcome.attempt_id),
                to_state="repairing",
                reason_code="automatic_repair_round_started",
                artifact_digests=(plan.plan_digest,),
            )
        elif current_state != "repairing":
            raise ValueError(
                f"automatic repair cannot start from manuscript state {current_state}"
            )
        from ari.manuscript.repair import RepairExecutionResult, execute_repair_plan

        transactional: dict[str, Any] = {}
        for kind, executor in executors.items():
            def _wrap(request, remaining, *, _executor=executor):
                transaction_name = f"{request.request_id}.json"
                transaction_path = store.root / "repair-transactions" / transaction_name
                if transaction_path.is_file():
                    value = json.loads(transaction_path.read_text(encoding="utf-8"))
                    if (
                        value.get("request_digest") != request.request_digest
                        or value.get("authority_digest") != request.authority_digest
                    ):
                        raise ValueError("repair transaction identity mismatch")
                    details = dict(value.get("details") or {})
                    prior_use = {
                        key: int(details.get(key, 0) or 0)
                        for key in ("new_nodes", "experiment_runs", "llm_calls")
                    }
                    details.update(
                        {
                            "new_nodes": 0,
                            "experiment_runs": 0,
                            "llm_calls": 0,
                            "idempotent_reuse": True,
                            "prior_budget_use": prior_use,
                        }
                    )
                    return RepairExecutionResult(
                        request.request_id, str(value.get("status")), details
                    )
                import inspect

                result = (
                    _executor(request, remaining)
                    if len(inspect.signature(_executor).parameters) >= 2
                    else _executor(request)
                )
                store.write_once(
                    f"repair-transactions/{transaction_name}",
                    {
                        "schema_version": "ari.manuscript-repair-transaction/v1",
                        "run_id": plan.run_id,
                        "request_id": request.request_id,
                        "request_digest": request.request_digest,
                        "source_context_digest": request.source_context_digest,
                        "authority_digest": request.authority_digest,
                        "status": result.status,
                        "details": result.details,
                    },
                )
                return result

            transactional[kind] = _wrap

        results = execute_repair_plan(
            plan,
            executors=transactional,
            used_budget=usage,
        )
        round_index = len(existing_rounds)
        round_record = {
            "schema_version": "ari.manuscript-auto-repair-round/v1",
            "round": round_index,
            "plan_digest": plan.plan_digest,
            "source_context_digest": readiness.context_digest,
            "request_ids": [item.request_id for item in plan.requests],
            "results": [
                {
                    "request_id": item.request_id,
                    "status": item.status,
                    "details": item.details,
                }
                for item in results
            ],
            "used_budget": dict(usage),
        }
        suffix = plan.plan_digest.removeprefix("sha256:")[:32]
        store.write_once(f"auto-rounds/{suffix}.json", round_record)
        store.write_attempt_artifact(
            str(outcome.attempt_id),
            f"repair_execution_auto-{suffix}.json",
            round_record,
        )
        existing_rounds[plan.plan_digest] = round_record
        completed_rounds += 1
        if not any(item.status in {"executed", "satisfied"} for item in results):
            if any(item.status == "human_required" for item in results):
                reason = "human_decision_required"
            elif any(item.status == "exhausted" for item in results):
                reason = "cumulative_budget_exhausted"
            else:
                reason = "required_resolver_unavailable"
            break
        evidence_rebuilder()
        next_outcome = prepare_runtime_manuscript(
            checkpoint,
            all_nodes,
            experiment_data=experiment_data,
            block_on_unready=False,
        )
        assert next_outcome is not None
        next_readiness = next_outcome.readiness
        if (
            next_readiness is not None
            and next_readiness.context_digest == readiness.context_digest
            and tuple(
                (item.requirement_id, item.status)
                for item in next_readiness.requirement_results
            ) == vector
        ):
            outcome = next_outcome
            reason = "no_progress_cycle"
            break
        outcome = next_outcome
        reason = "authoring_ready" if outcome.authoring_ready else "round_budget_exhausted"

    if not outcome.authoring_ready:
        current = store.read_state()
        current_state = str(current.get("state") or "absent")
        target = (
            "blocked_unavailable"
            if reason in {
                "human_decision_required",
                "required_resolver_unavailable",
                "no_admitted_repair_request",
            }
            else "repair_pending"
        )
        from ari.manuscript.state import LEGAL_TRANSITIONS

        if target in LEGAL_TRANSITIONS.get(current_state, frozenset()):
            store.transition(
                run_id=(outcome.readiness.run_id if outcome.readiness else checkpoint.name),
                attempt=str(outcome.attempt_id),
                to_state=target,
                reason_code=f"automatic_repair_{reason}",
                artifact_digests=(
                    (outcome.readiness.readiness_digest,)
                    if outcome.readiness is not None
                    else ()
                ),
            )
    return RuntimeRepairLoopResult(
        outcome=outcome,
        rounds=completed_rounds,
        termination_reason=reason,
        used_budget=dict(usage),
    )


def transition_runtime_manuscript(
    checkpoint_dir: str | Path,
    to_state: str,
    *,
    reason_code: str,
    artifact_digests: tuple[str, ...] = (),
) -> None:
    """Append a state transition for the currently exposed binding."""

    binding_path = os.environ.get("ARI_MANUSCRIPT_BINDING_PATH", "").strip()
    if not binding_path:
        return
    from ari.manuscript.contracts import ManuscriptAuthoringBindingV1

    binding = ManuscriptAuthoringBindingV1.model_validate_json(
        Path(binding_path).read_text(encoding="utf-8")
    )
    ManuscriptStateStore(checkpoint_dir).transition(
        run_id=binding.run_id,
        attempt=binding.attempt_id,
        to_state=to_state,
        reason_code=reason_code,
        artifact_digests=artifact_digests or (binding.binding_digest,),
    )


def _source_inputs_fresh(checkpoint: Path, attempt_id: str) -> bool:
    from ari.manuscript.contracts import ExplorationSnapshotV1

    path = (
        checkpoint
        / ".ari-manuscript"
        / "attempts"
        / attempt_id
        / "source_snapshot.json"
    )
    try:
        snapshot = ExplorationSnapshotV1.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        for artifact in snapshot.artifacts:
            if artifact.status != "present" or artifact.relative_path is None:
                continue
            source = checkpoint / artifact.relative_path
            if not source.is_file() or file_digest(source)[0] != artifact.digest:
                return False
    except (OSError, ValueError):
        return False
    return True


def _paper_build_artifacts_fresh(checkpoint: Path, build: Any) -> bool:
    """Re-verify every typed PaperArtifact nested in the exact build."""

    payload = build.model_dump(mode="json")
    refs: dict[tuple[str, str], tuple[str, int]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("schema_version") == "ari.paper-artifact/v1":
                key = (str(value.get("role") or ""), str(value.get("relative_path") or ""))
                expected = (str(value.get("digest") or ""), int(value.get("size_bytes") or 0))
                previous = refs.get(key)
                if previous is not None and previous != expected:
                    raise ValueError("paper build declares conflicting artifact identities")
                refs[key] = expected
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    try:
        visit(payload)
        for (_, relative), expected in refs.items():
            source = checkpoint / relative
            if not source.is_file() or source.is_symlink():
                return False
            if file_digest(source) != expected:
                return False
    except (OSError, TypeError, ValueError):
        return False
    return bool(refs)


def _bound_manuscript_inputs_fresh(
    checkpoint: Path,
    build: Any,
    binding: Any,
) -> bool:
    required = {
        "manuscript-profile": "ARI_MANUSCRIPT_PROFILE_PATH",
        "manuscript-context": "ARI_MANUSCRIPT_CONTEXT_PATH",
        "manuscript-readiness": "ARI_MANUSCRIPT_READINESS_PATH",
        "section-briefs": "ARI_MANUSCRIPT_BRIEFS_PATH",
        "manuscript-authoring-binding": "ARI_MANUSCRIPT_BINDING_PATH",
    }
    by_role = {item.role: item for item in build.input_artifacts}
    if not set(required).issubset(by_role):
        return False
    for role, env_name in required.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            return False
        path = Path(raw).resolve()
        try:
            relative = path.relative_to(checkpoint).as_posix()
        except ValueError:
            return False
        declared = by_role[role]
        if (
            declared.relative_path != relative
            or not path.is_file()
            or path.is_symlink()
            or file_digest(path) != (declared.digest, declared.size_bytes)
        ):
            return False
    return bool(
        binding.target_build_id == build.build_id
        and binding.run_id == build.run_id
        and binding.attempt_id
    )


def finalize_runtime_publication(
    checkpoint_dir: str | Path,
) -> Any | None:
    """Build the independent publication lock after the verification segment.

    Missing reproduction is a failed gate, never an inferred success.  Audit
    emits the same shadow decision but does not alter the legacy paper build.
    """

    mode = os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off").strip().lower()
    if mode == "off":
        return None
    checkpoint = Path(checkpoint_dir).resolve()
    build_path = checkpoint / "paper_build.json"
    required_env = (
        "ARI_MANUSCRIPT_CONTEXT_PATH",
        "ARI_MANUSCRIPT_READINESS_PATH",
        "ARI_MANUSCRIPT_BINDING_PATH",
    )
    if not build_path.is_file() or any(not os.environ.get(name) for name in required_env):
        return None

    from ari.manuscript.contracts import (
        ManuscriptAuthoringBindingV1,
        ManuscriptContextV1,
        ManuscriptReadinessReportV1,
    )
    from ari.manuscript.publication import build_publication_decision
    from ari.paper_contract import parse_paper_build

    build = parse_paper_build(build_path.read_text(encoding="utf-8"))
    context = ManuscriptContextV1.model_validate_json(
        Path(os.environ["ARI_MANUSCRIPT_CONTEXT_PATH"]).read_text(encoding="utf-8")
    )
    readiness = ManuscriptReadinessReportV1.model_validate_json(
        Path(os.environ["ARI_MANUSCRIPT_READINESS_PATH"]).read_text(encoding="utf-8")
    )
    binding = ManuscriptAuthoringBindingV1.model_validate_json(
        Path(os.environ["ARI_MANUSCRIPT_BINDING_PATH"]).read_text(encoding="utf-8")
    )

    bound_build = _bound_manuscript_inputs_fresh(checkpoint, build, binding)
    source_fresh = _source_inputs_fresh(checkpoint, binding.attempt_id)
    state = ManuscriptStateStore(checkpoint).read_state()
    authored = str(state.get("state") or "") in {"authored", "finalized"}
    inputs_fresh = source_fresh and authored and _paper_build_artifacts_fresh(
        checkpoint, build
    ) and (
        bound_build if mode == "enforce" else True
    )

    reproduction_path = checkpoint / "ors_phase1.json"
    reproduction_passed = False
    reproduction_digest = "sha256:" + "0" * 64
    if reproduction_path.is_file():
        reproduction_digest = file_digest(reproduction_path)[0]
        try:
            reproduction = json.loads(reproduction_path.read_text(encoding="utf-8"))
            reproduction_passed = bool(
                reproduction.get("executed")
                and reproduction.get("exit_code") == 0
                and not (reproduction.get("missing") or [])
                and not reproduction.get("error")
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            reproduction_passed = False

    assurance_required = context.assurance.get("mode") == "enforce"
    assurance_passed = bool(
        context.assurance.get("publication_candidate")
        and context.assurance.get("attestation_item_ids")
    ) if assurance_required else None
    claim_passed = bool(build.gate and build.gate.status == "pass")
    claim_digest = (
        build.gate.report_digest if build.gate is not None else "sha256:" + "0" * 64
    )
    compile_passed = bool(
        build.status == "finalized"
        and build.compile
        and build.compile.status == "completed"
    )
    compile_digest = (
        build.compile.compile_digest
        if build.compile is not None
        else "sha256:" + "0" * 64
    )
    assurance_digests: tuple[str, ...] = ()
    try:
        from ari.manuscript.contracts import ExplorationSnapshotV1

        snapshot = ExplorationSnapshotV1.model_validate_json(
            (
                checkpoint
                / ".ari-manuscript"
                / "attempts"
                / binding.attempt_id
                / "source_snapshot.json"
            ).read_text(encoding="utf-8")
        )
        admitted_ids = set(context.assurance.get("attestation_item_ids") or ())
        assurance_digests = tuple(
            item.digest
            for item in snapshot.artifacts
            if item.item_id in admitted_ids and item.digest is not None
        )
    except (OSError, ValueError):
        assurance_digests = ()
    if assurance_required:
        assurance_passed = bool(assurance_passed and assurance_digests)
    decision = build_publication_decision(
        run_id=build.run_id,
        attempt_id=binding.attempt_id,
        paper_build_digest=build.build_digest,
        binding=binding,
        readiness=readiness,
        claim_gate_passed=claim_passed,
        claim_gate_digest=claim_digest,
        assurance_required=assurance_required,
        assurance_passed=assurance_passed,
        assurance_artifact_digests=assurance_digests,
        compile_passed=compile_passed,
        compile_digest=compile_digest,
        reproduction_passed=reproduction_passed,
        reproduction_digest=reproduction_digest,
        inputs_fresh=inputs_fresh,
    )
    store = ManuscriptStateStore(checkpoint)
    store.write_attempt_artifact(
        binding.attempt_id, "publication_decision.json", decision
    )
    if mode == "enforce":
        store.transition(
            run_id=build.run_id,
            attempt=binding.attempt_id,
            to_state=("finalized" if decision.decision == "publishable" else "publication_blocked"),
            reason_code=f"publication_{decision.decision}",
            artifact_digests=(build.build_digest, decision.decision_digest),
        )
    return decision


def lock_runtime_publication(checkpoint_dir: str | Path) -> Any:
    """Create the final lock only after a fresh publishable decision re-check."""

    checkpoint = Path(checkpoint_dir).resolve()
    from ari.manuscript.contracts import (
        ManuscriptAuthoringBindingV1,
        PublicationDecisionV1,
        PublicationLockV1,
    )
    from ari.paper_contract import parse_paper_build

    binding_path = Path(os.environ.get("ARI_MANUSCRIPT_BINDING_PATH", ""))
    if not binding_path.is_file():
        raise ValueError("publication lock requires an exposed authoring binding")
    binding = ManuscriptAuthoringBindingV1.model_validate_json(
        binding_path.read_text(encoding="utf-8")
    )
    attempt = checkpoint / ".ari-manuscript" / "attempts" / binding.attempt_id
    decision = PublicationDecisionV1.model_validate_json(
        (attempt / "publication_decision.json").read_text(encoding="utf-8")
    )
    build = parse_paper_build((checkpoint / "paper_build.json").read_text(encoding="utf-8"))
    if decision.decision != "publishable":
        raise ValueError("blocked publication decision cannot be locked")
    if (
        decision.paper_build_digest != build.build_digest
        or decision.authoring_binding_digest != binding.binding_digest
        or decision.run_id != build.run_id
        or decision.attempt_id != binding.attempt_id
    ):
        raise ValueError("publication decision no longer names the current build")
    state = ManuscriptStateStore(checkpoint).read_state()
    if state.get("attempt_id") != binding.attempt_id or state.get("state") != "finalized":
        raise ValueError("publication attempt is not finalized")
    if not (
        _source_inputs_fresh(checkpoint, binding.attempt_id)
        and _paper_build_artifacts_fresh(checkpoint, build)
        and _bound_manuscript_inputs_fresh(checkpoint, build, binding)
    ):
        raise ValueError("publication inputs changed after decision")
    reproduction = next(
        item for item in decision.subverdicts if item.gate == "reproduction"
    )
    reproduction_path = checkpoint / "ors_phase1.json"
    if (
        reproduction.status != "pass"
        or not reproduction_path.is_file()
        or file_digest(reproduction_path)[0] not in reproduction.artifact_digests
    ):
        raise ValueError("publication reproduction evidence is stale")
    pdfs = [item for item in build.final_artifacts if item.role == "pdf"]
    if not pdfs and build.compile and build.compile.pdf_artifact is not None:
        pdfs = [build.compile.pdf_artifact]
    if len(pdfs) != 1:
        raise ValueError("publication build does not identify one final PDF")
    lock = PublicationLockV1.create(
        run_id=build.run_id,
        attempt_id=binding.attempt_id,
        decision_digest=decision.decision_digest,
        paper_build_digest=build.build_digest,
        authoring_binding_digest=binding.binding_digest,
        pdf_digest=pdfs[0].digest,
        freshness_verified=True,
    )
    ManuscriptStateStore(checkpoint).write_attempt_artifact(
        binding.attempt_id, "publication_lock.json", lock
    )
    return lock


__all__ = [
    "finalize_runtime_publication",
    "lock_runtime_publication",
    "prepare_runtime_manuscript",
    "run_runtime_auto_repair",
    "RuntimeRepairLoopResult",
    "transition_runtime_manuscript",
]
