"""Typed repair planning, budget accounting, and callback execution."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import math
from typing import Any, Callable

from ari.manuscript.contracts import (
    ManuscriptRepairTransactionV1,
    ManuscriptReadinessReportV1,
    RepairBudgetV1,
    ResearchRepairPlanV1,
    ResearchRepairRequestV1,
)
from ari.manuscript.digest import canonical_digest


DEFAULT_SUCCESS_PREDICATES = {
    "artifact_recovery": "artifact-present-and-digest-valid-v1",
    "projection_rebuild": "requirement-reassessed-satisfied-v1",
    "literature_search": "recorded-retrieval-nonempty-v1",
    "baseline_comparison": "comparable-measurement-completed-v1",
    "repetition_or_uncertainty": "uncertainty-evidence-completed-v1",
    "ablation": "ablation-measurement-completed-v1",
    "validation_experiment": "validation-measurement-completed-v1",
    "assurance_certification": "current-target-certification-pass-v1",
    "method_clarification": "admitted-method-record-present-v1",
    "limitation_disclosure": "mandatory-disclosure-bound-v1",
    "human_decision": "admitted-human-decision-present-v1",
}

REPAIR_PRIORITY = {
    "projection_rebuild": 1,
    "artifact_recovery": 1,
    "assurance_certification": 2,
    "literature_search": 3,
    "validation_experiment": 4,
    "baseline_comparison": 5,
    "repetition_or_uncertainty": 5,
    "ablation": 5,
    "method_clarification": 6,
    "limitation_disclosure": 7,
    "human_decision": 8,
}

REPAIR_ALLOWED_CHANGES = {
    "projection_rebuild": ("derived_manuscript_artifacts",),
    "artifact_recovery": ("missing_derived_artifacts",),
    "literature_search": ("recorded_retrieval_revision",),
    "baseline_comparison": ("method_or_baseline_only",),
    "repetition_or_uncertainty": ("seed_or_repetition_only",),
    "ablation": ("named_component_only",),
    "validation_experiment": ("validation_case_only",),
    "assurance_certification": ("certification_attestations",),
    "method_clarification": ("typed_method_record",),
    "limitation_disclosure": ("mandatory_disclosure_record",),
    "human_decision": ("admitted_human_decision_record",),
}

REPAIR_CAPABILITIES = {
    "literature_search": ("literature-retrieval",),
    "baseline_comparison": ("research-execution",),
    "repetition_or_uncertainty": ("research-execution",),
    "ablation": ("research-execution",),
    "validation_experiment": ("research-execution",),
    "assurance_certification": ("assurance-certification",),
}

REPAIR_MINIMUM_COST = {
    "literature_search": (0, 0, 1),
    "baseline_comparison": (1, 1, 1),
    "repetition_or_uncertainty": (1, 1, 1),
    "ablation": (1, 1, 1),
    "validation_experiment": (1, 1, 1),
    "assurance_certification": (0, 1, 0),
    "method_clarification": (0, 0, 1),
}


def authority_digest(authority: dict[str, Any] | None) -> str:
    if authority and authority.get("schema_version") == "ari.manuscript-repair-authority/v1":
        from ari.manuscript.authority import validate_repair_authority

        return validate_repair_authority(authority)
    return canonical_digest(authority or {"mode": "legacy-inherited"})


def build_repair_plan(
    readiness: ManuscriptReadinessReportV1,
    *,
    policy: str,
    budget: RepairBudgetV1 | None = None,
    authority: dict[str, Any] | None = None,
) -> ResearchRepairPlanV1:
    plan_budget = budget or RepairBudgetV1()
    auth_digest = authority_digest(authority)
    grouped: dict[str, list[str]] = {}
    for result in readiness.requirement_results:
        if result.status not in {"missing", "unavailable"} or result.resolver_kind is None:
            continue
        grouped.setdefault(result.resolver_kind, []).append(result.requirement_id)
    requests: list[ResearchRepairRequestV1] = []
    for kind, requirement_ids in sorted(
        grouped.items(), key=lambda item: (REPAIR_PRIORITY.get(item[0], 99), item[0])
    ):
        identity_payload = {
            "source_context_digest": readiness.context_digest,
            "requirements": sorted(requirement_ids),
            "kind": kind,
            "success_predicate": DEFAULT_SUCCESS_PREDICATES[kind],
        }
        request_id = f"repair-{canonical_digest(identity_payload)[7:31]}"
        requests.append(
            ResearchRepairRequestV1.create(
                request_id=request_id,
                source_context_digest=readiness.context_digest,
                requirement_ids=tuple(sorted(requirement_ids)),
                kind=kind,
                fixed_variables={
                    "requirement_ids": sorted(requirement_ids),
                    "source_readiness_digest": readiness.readiness_digest,
                },
                allowed_changes=REPAIR_ALLOWED_CHANGES.get(kind, ()),
                required_capability_ids=REPAIR_CAPABILITIES.get(kind, ()),
                required_harness_ids=(
                    ("frozen-certification-suite",)
                    if kind == "assurance_certification"
                    else ()
                ),
                preconditions=("source_context_is_current", "authority_digest_matches"),
                success_predicate_id=DEFAULT_SUCCESS_PREDICATES[kind],
                stop_conditions=("request_budget_exhausted", "human_intervention_required"),
                budget=plan_budget,
                authority_digest=auth_digest,
            )
        )
    return ResearchRepairPlanV1.create(
        run_id=readiness.run_id,
        source_context_digest=readiness.context_digest,
        readiness_digest=readiness.readiness_digest,
        policy=(policy if policy in {"disabled", "explicit", "auto"} else "disabled"),
        budget=plan_budget,
        authority_digest=auth_digest,
        requests=tuple(requests),
    )


@dataclass(frozen=True)
class RepairExecutionResult:
    request_id: str
    status: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in {
            "executed", "satisfied", "still_missing", "failed", "exhausted",
            "human_required", "unavailable",
        }:
            raise ValueError(f"unknown repair execution status: {self.status}")
        if not isinstance(self.details, dict):
            raise ValueError("repair execution details must be an object")
        try:
            json.dumps(self.details, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("repair execution details must be finite JSON") from exc


RepairExecutor = Callable[[ResearchRepairRequestV1], RepairExecutionResult]


def bind_transactional_executors(
    plan: ResearchRepairPlanV1,
    checkpoint_dir,
    executors: dict[str, RepairExecutor],
) -> dict[str, RepairExecutor]:
    """Wrap resolvers in immutable request-level idempotency commits."""

    from pathlib import Path

    from ari.manuscript.digest import path_has_symlink_component
    from ari.manuscript.state import ManuscriptStateStore

    store = ManuscriptStateStore(checkpoint_dir)
    checkpoint = Path(checkpoint_dir).resolve()
    transactional: dict[str, RepairExecutor] = {}
    for kind, executor in executors.items():

        def _wrap(request, remaining=None, *, _executor=executor):
            transaction_name = f"{request.request_id}.json"
            transaction_path = (
                store.root / "repair-transactions" / transaction_name
            )
            if transaction_path.exists() or transaction_path.is_symlink():
                if (
                    not transaction_path.is_file()
                    or path_has_symlink_component(checkpoint, transaction_path)
                ):
                    raise ValueError("repair transaction path is unsafe")
                value = ManuscriptRepairTransactionV1.model_validate_json(
                    transaction_path.read_text(encoding="utf-8")
                )
                if (
                    value.run_id != plan.run_id
                    or value.request_id != request.request_id
                    or value.request_digest != request.request_digest
                    or value.source_context_digest != request.source_context_digest
                    or value.authority_digest != request.authority_digest
                ):
                    raise ValueError("repair transaction identity mismatch")
                details = dict(value.details)
                prior_use = {
                    "new_nodes": details.get("new_nodes", 0),
                    "experiment_runs": details.get("experiment_runs", 0),
                    "llm_calls": details.get("llm_calls", 0),
                    "resource_units": details.get("resource_units", 0.0),
                }
                details.update(
                    {
                        "new_nodes": 0,
                        "experiment_runs": 0,
                        "llm_calls": 0,
                        "resource_units": 0.0,
                        "idempotent_reuse": True,
                        "prior_budget_use": prior_use,
                    }
                )
                return RepairExecutionResult(request.request_id, value.status, details)
            result = (
                _executor(request, remaining)
                if remaining is not None
                and len(inspect.signature(_executor).parameters) >= 2
                else _executor(request)
            )
            if result.request_id != request.request_id:
                raise ValueError("repair executor returned another request identity")
            transaction = ManuscriptRepairTransactionV1.create(
                run_id=plan.run_id,
                request_id=request.request_id,
                request_digest=request.request_digest,
                source_context_digest=request.source_context_digest,
                authority_digest=request.authority_digest,
                status=result.status,
                details=result.details,
            )
            store.write_once(
                f"repair-transactions/{transaction_name}", transaction
            )
            return result

        transactional[kind] = _wrap
    return transactional


def committed_repair_usage(
    plan: ResearchRepairPlanV1,
    checkpoint_dir,
) -> dict[str, int | float]:
    """Reconstruct plan-local consumed budget from verified transactions."""

    from pathlib import Path

    from ari.manuscript.digest import path_has_symlink_component
    from ari.manuscript.state import ManuscriptStateStore

    checkpoint = Path(checkpoint_dir).resolve()
    store = ManuscriptStateStore(checkpoint)
    usage: dict[str, int | float] = {
        "new_nodes": 0,
        "experiment_runs": 0,
        "llm_calls": 0,
        "resource_units": 0.0,
    }
    for request in plan.requests:
        path = store.root / "repair-transactions" / f"{request.request_id}.json"
        if not (path.exists() or path.is_symlink()):
            continue
        if not path.is_file() or path_has_symlink_component(checkpoint, path):
            raise ValueError("repair transaction path is unsafe")
        record = ManuscriptRepairTransactionV1.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if (
            record.run_id != plan.run_id
            or record.request_id != request.request_id
            or record.request_digest != request.request_digest
            or record.source_context_digest != request.source_context_digest
            or record.authority_digest != request.authority_digest
        ):
            raise ValueError("repair transaction identity mismatch")
        for key in ("new_nodes", "experiment_runs", "llm_calls"):
            value = record.details.get(key, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("repair transaction has invalid budget use")
            usage[key] = int(usage[key]) + value
        resource = record.details.get("resource_units", 0.0)
        if (
            not isinstance(resource, (int, float))
            or isinstance(resource, bool)
            or not math.isfinite(float(resource))
            or float(resource) < 0
        ):
            raise ValueError("repair transaction has invalid resource use")
        usage["resource_units"] = float(usage["resource_units"]) + float(resource)
    return usage


def execute_repair_plan(
    plan: ResearchRepairPlanV1,
    *,
    executors: dict[str, RepairExecutor],
    selected_request_ids: set[str] | None = None,
    used_budget: dict[str, int | float] | None = None,
) -> tuple[RepairExecutionResult, ...]:
    """Execute admitted callbacks without inferring unavailable authority.

    Scientific satisfaction is deliberately not returned here; callers must
    rebuild context/readiness and close requirements from fresh evidence.
    """

    if plan.policy == "disabled":
        return ()
    selected = (
        {item.request_id for item in plan.requests}
        if selected_request_ids is None
        else set(selected_request_ids)
    )
    unknown = selected - {item.request_id for item in plan.requests}
    if unknown:
        raise ValueError("selected repair request is absent from the admitted plan")
    results: list[RepairExecutionResult] = []
    usage = used_budget if used_budget is not None else {}

    def budget_integer(value: Any, *, label: str) -> int:
        if value is None:
            return 0
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"repair budget has invalid {label}")
        return value

    def resource_value(value: Any, *, label: str) -> float:
        if value is None:
            return 0.0
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"repair budget has invalid {label}")
        return float(value)

    used_nodes = budget_integer(usage.get("new_nodes", 0), label="node use")
    used_runs = budget_integer(
        usage.get("experiment_runs", 0), label="experiment use"
    )
    used_calls = budget_integer(usage.get("llm_calls", 0), label="call use")
    used_resources = resource_value(
        usage.get("resource_units", 0.0), label="resource use"
    )
    if (
        used_nodes > plan.budget.max_new_nodes
        or used_runs > plan.budget.max_experiment_runs
        or used_calls > plan.budget.max_llm_calls
        or (
            plan.budget.max_resource_units is not None
            and used_resources > plan.budget.max_resource_units
        )
    ):
        raise ValueError("committed repair use exceeds admitted plan budget")
    for request in plan.requests:
        if request.request_id not in selected:
            continue
        if request.authority_digest != plan.authority_digest:
            raise ValueError("repair request authority differs from admitted plan")
        executor = executors.get(request.kind)
        if executor is None:
            results.append(RepairExecutionResult(request.request_id, "unavailable", {"reason": "resolver_unavailable"}))
            continue
        minimum = REPAIR_MINIMUM_COST.get(request.kind, (0, 0, 0))
        remaining = RepairBudgetV1(
            max_rounds=max(0, plan.budget.max_rounds),
            max_new_nodes=max(0, plan.budget.max_new_nodes - used_nodes),
            max_experiment_runs=max(
                0, plan.budget.max_experiment_runs - used_runs
            ),
            max_llm_calls=max(0, plan.budget.max_llm_calls - used_calls),
            max_resource_units=(
                None
                if plan.budget.max_resource_units is None
                else max(0.0, plan.budget.max_resource_units - used_resources)
            ),
        )
        if (
            remaining.max_new_nodes < minimum[0]
            or remaining.max_experiment_runs < minimum[1]
            or remaining.max_llm_calls < minimum[2]
        ):
            results.append(
                RepairExecutionResult(
                    request.request_id,
                    "exhausted",
                    {"reason": "plan_budget_exhausted"},
                )
            )
            continue
        parameters = inspect.signature(executor).parameters
        result = (
            executor(request, remaining)
            if len(parameters) >= 2
            else executor(request)
        )
        if result.request_id != request.request_id:
            raise ValueError("repair executor returned another request identity")
        results.append(result)
        new_nodes = budget_integer(
            result.details.get("new_nodes", 0), label="executor node use"
        )
        new_runs = budget_integer(
            result.details.get("experiment_runs", 0),
            label="executor experiment use",
        )
        new_calls = budget_integer(
            result.details.get("llm_calls", 0), label="executor call use"
        )
        new_resources = resource_value(
            result.details.get("resource_units", 0.0),
            label="executor resource use",
        )
        if (
            new_nodes > request.budget.max_new_nodes
            or new_runs > request.budget.max_experiment_runs
            or new_calls > request.budget.max_llm_calls
            or (
                request.budget.max_resource_units is not None
                and new_resources > request.budget.max_resource_units
            )
        ):
            raise ValueError("repair executor exceeded its request budget")
        used_nodes += new_nodes
        used_runs += new_runs
        used_calls += new_calls
        used_resources += new_resources
        if (
            used_nodes > plan.budget.max_new_nodes
            or used_runs > plan.budget.max_experiment_runs
            or used_calls > plan.budget.max_llm_calls
            or (
                plan.budget.max_resource_units is not None
                and used_resources > plan.budget.max_resource_units
            )
        ):
            raise ValueError("repair executor exceeded admitted plan budget")
        usage.update(
            {
                "new_nodes": used_nodes,
                "experiment_runs": used_runs,
                "llm_calls": used_calls,
                "resource_units": used_resources,
            }
        )
    return tuple(results)


__all__ = [
    "DEFAULT_SUCCESS_PREDICATES",
    "REPAIR_ALLOWED_CHANGES",
    "REPAIR_CAPABILITIES",
    "REPAIR_PRIORITY",
    "REPAIR_MINIMUM_COST",
    "RepairExecutionResult",
    "authority_digest",
    "bind_transactional_executors",
    "committed_repair_usage",
    "build_repair_plan",
    "execute_repair_plan",
]
