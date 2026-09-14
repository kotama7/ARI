"""Versioned Manuscript Complete program metrics over labelled cases."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from ari.manuscript.contracts import (
    ManuscriptEvaluationMetricV1,
    ManuscriptEvaluationReportV1,
)


EVALUATOR_VERSION = "manuscript-program-evaluator-v1"
_STATUSES = {"satisfied", "not_applicable", "unavailable", "missing"}


def _ratio(metric_id: str, numerator: float, denominator: float, refs=()):
    if denominator == 0:
        return ManuscriptEvaluationMetricV1(
            metric_id=metric_id,
            numerator=numerator,
            denominator=0,
            value=None,
            status="not_applicable",
            evidence_refs=tuple(refs),
        )
    return ManuscriptEvaluationMetricV1(
        metric_id=metric_id,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        status="measured",
        evidence_refs=tuple(refs),
    )


def _count(metric_id: str, value: float, refs=()):
    return ManuscriptEvaluationMetricV1(
        metric_id=metric_id,
        numerator=value,
        denominator=None,
        value=value,
        status="measured",
        evidence_refs=tuple(refs),
    )


def evaluate_labelled_cases(
    cases: Iterable[dict[str, Any]],
    *,
    dataset_id: str,
) -> ManuscriptEvaluationReportV1:
    rows = [dict(item) for item in cases]
    case_ids = tuple(str(item["case_id"]) for item in rows)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("labelled evaluation cases must have unique IDs")

    total_requirements = accounted = tp = fp = fn = 0
    inventory = projected = silent_omissions = 0
    headline_total = headline_covered = 0
    negative_total = negative_visible = 0
    repair_total = repair_unnecessary = repair_satisfied = 0
    repair_cost = 0.0
    attempts = rounds = finalized_cases = 0
    off_total = off_identity = 0
    blocked_reasons: Counter[str] = Counter()
    topology: dict[str, dict[str, float]] = defaultdict(
        lambda: {"cases": 0.0, "llm_calls": 0.0, "experiment_runs": 0.0, "resource_units": 0.0}
    )

    for row in rows:
        requirements = row.get("requirements") or []
        for requirement in requirements:
            total_requirements += 1
            observed = str(requirement.get("observed_status") or "")
            expected_missing = bool(requirement.get("expected_missing", False))
            observed_missing = observed in {"missing", "unavailable"}
            accounted += int(observed in _STATUSES)
            tp += int(expected_missing and observed_missing)
            fp += int(not expected_missing and observed_missing)
            fn += int(expected_missing and not observed_missing)

        inv = int(row.get("inventory_count", 0) or 0)
        inc = int(row.get("included_count", 0) or 0)
        omi = int(row.get("omission_count", 0) or 0)
        inventory += inv
        projected += inc + omi
        silent_omissions += max(0, inv - inc - omi)
        headline_total += int(row.get("headline_claim_count", 0) or 0)
        headline_covered += int(row.get("headline_evidence_covered", 0) or 0)
        negative_total += int(row.get("negative_result_count", 0) or 0)
        negative_visible += int(row.get("negative_result_visible", 0) or 0)
        repair_total += int(row.get("repair_request_count", 0) or 0)
        repair_unnecessary += int(row.get("unnecessary_repair_count", 0) or 0)
        repair_satisfied += int(row.get("repair_satisfied_count", 0) or 0)
        repair_cost += float(row.get("repair_cost", 0.0) or 0.0)
        if row.get("finalized"):
            finalized_cases += 1
            attempts += int(row.get("attempt_count", 0) or 0)
            rounds += int(row.get("round_count", 0) or 0)
        for reason in row.get("blocked_reasons") or []:
            blocked_reasons[str(reason)] += 1
        if "off_identity" in row:
            off_total += 1
            off_identity += int(bool(row.get("off_identity")))
        topology_id = str(row.get("topology") or "unspecified")
        cost = row.get("cost") or {}
        topology[topology_id]["cases"] += 1
        for key in ("llm_calls", "experiment_runs", "resource_units"):
            topology[topology_id][key] += float(cost.get(key, 0.0) or 0.0)

    refs = case_ids
    metrics = (
        _ratio("requirement-accounting-rate", accounted, total_requirements, refs),
        _ratio("missing-detection-precision", tp, tp + fp, refs),
        _ratio("missing-detection-recall", tp, tp + fn, refs),
        _count("silent-omission-count", silent_omissions, refs),
        _ratio("inventory-projection-accounting-rate", projected, inventory, refs),
        _ratio("headline-publishable-evidence-coverage", headline_covered, headline_total, refs),
        _ratio("negative-result-visibility", negative_visible, negative_total, refs),
        _ratio("unnecessary-repair-rate", repair_unnecessary, repair_total, refs),
        _ratio("repair-success-rate", repair_satisfied, repair_total, refs),
        _ratio("repair-marginal-cost", repair_cost, repair_satisfied, refs),
        _ratio("attempts-to-finalization", attempts, finalized_cases, refs),
        _ratio("rounds-to-finalization", rounds, finalized_cases, refs),
        _ratio("legacy-off-identity-rate", off_identity, off_total, refs),
    )
    topology_rows = tuple(
        {"topology": key, **topology[key]} for key in sorted(topology)
    )
    return ManuscriptEvaluationReportV1.create(
        dataset_id=dataset_id,
        evaluator_version=EVALUATOR_VERSION,
        case_ids=case_ids,
        metrics=metrics,
        blocked_reason_distribution=dict(sorted(blocked_reasons.items())),
        topology_costs=topology_rows,
    )


__all__ = ["EVALUATOR_VERSION", "evaluate_labelled_cases"]
