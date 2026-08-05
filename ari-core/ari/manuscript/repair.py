"""Typed repair planning, budget accounting, and callback execution."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable

from ari.manuscript.contracts import (
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


RepairExecutor = Callable[[ResearchRepairRequestV1], RepairExecutionResult]


def execute_repair_plan(
    plan: ResearchRepairPlanV1,
    *,
    executors: dict[str, RepairExecutor],
    selected_request_ids: set[str] | None = None,
    used_budget: dict[str, int] | None = None,
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
    used_nodes = int(usage.get("new_nodes", 0) or 0)
    used_runs = int(usage.get("experiment_runs", 0) or 0)
    used_calls = int(usage.get("llm_calls", 0) or 0)
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
            max_resource_units=plan.budget.max_resource_units,
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
        new_nodes = int(result.details.get("new_nodes", 0) or 0)
        new_runs = int(result.details.get("experiment_runs", 0) or 0)
        new_calls = int(result.details.get("llm_calls", 0) or 0)
        if min(new_nodes, new_runs, new_calls) < 0:
            raise ValueError("repair executor reported negative budget use")
        if (
            new_nodes > request.budget.max_new_nodes
            or new_runs > request.budget.max_experiment_runs
            or new_calls > request.budget.max_llm_calls
        ):
            raise ValueError("repair executor exceeded its request budget")
        used_nodes += new_nodes
        used_runs += new_runs
        used_calls += new_calls
        if used_nodes > plan.budget.max_new_nodes or used_runs > plan.budget.max_experiment_runs or used_calls > plan.budget.max_llm_calls:
            raise ValueError("repair executor exceeded admitted plan budget")
        usage.update(
            {
                "new_nodes": used_nodes,
                "experiment_runs": used_runs,
                "llm_calls": used_calls,
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
    "build_repair_plan",
    "execute_repair_plan",
]
