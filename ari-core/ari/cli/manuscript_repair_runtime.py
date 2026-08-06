"""Outer-runtime executors for admitted Manuscript Complete repairs.

This module is imported only for ``manuscript.mode=enforce`` with automatic
repair enabled.  It deliberately lives beside the normal BFTS runner: paper
Skills and the paper archive receive immutable briefs, never an experiment
execution capability.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from ari.manuscript.authority import (
    capture_repair_authority,
    validate_repair_authority,
)
from ari.manuscript.contracts import RepairBudgetV1, ResearchRepairRequestV1
from ari.manuscript.digest import canonical_digest
from ari.manuscript.repair import RepairExecutionResult


_EXPERIMENT_LABELS = {
    "baseline_comparison": "draft",
    "repetition_or_uncertainty": "validation",
    "ablation": "ablation",
    "validation_experiment": "validation",
}

_EXPERIMENT_DIRECTIVES = {
    "baseline_comparison": (
        "Run one directly comparable baseline measurement. Keep the existing "
        "target, dataset/workload, measurement definition, and environment fixed; "
        "change only the named method or baseline implementation."
    ),
    "repetition_or_uncertainty": (
        "Repeat the current measurement to quantify uncertainty. Keep the method, "
        "workload, environment, and metric definition fixed; change only seeds or "
        "repetition indices and report dispersion."
    ),
    "ablation": (
        "Run one ablation of the named component. Keep every other method, workload, "
        "environment, and metric definition fixed and report the delta."
    ),
    "validation_experiment": (
        "Run one targeted validation case for the admitted requirement. Keep the "
        "scientific target and primary method fixed; change only the validation case."
    ),
}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one mutable source projection atomically.

    Runtime source records are intentionally mutable aggregates.  Immutable
    request/attempt records remain under ``.ari-manuscript/attempts``.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def _json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _trace_count(checkpoint: Path) -> int:
    path = checkpoint / "prompt_trace.jsonl"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _repair_node_id(request: ResearchRepairRequestV1) -> str:
    suffix = request.request_digest.removeprefix("sha256:")[:24]
    return f"node_repair_{suffix}"


def _authority_is_current(
    checkpoint: Path,
    run_id: str,
    request: ResearchRepairRequestV1,
) -> bool:
    current = capture_repair_authority(checkpoint, run_id=run_id)
    return validate_repair_authority(current) == request.authority_digest


def _current_context_digest(checkpoint: Path) -> str:
    try:
        state = json.loads(
            (checkpoint / ".ari-manuscript" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        attempt = str(state.get("attempt_id") or "")
        if not attempt:
            return ""
        context = json.loads(
            (
                checkpoint
                / ".ari-manuscript"
                / "attempts"
                / attempt
                / "context.json"
            ).read_text(encoding="utf-8")
        )
        return str(context.get("context_digest") or "")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return ""


def _result(
    request: ResearchRepairRequestV1,
    status: str,
    **details: Any,
) -> RepairExecutionResult:
    return RepairExecutionResult(request.request_id, status, details)


def build_research_repair_executors(
    cfg,
    bfts,
    agent,
    all_nodes: list[Any],
    experiment_data: dict[str, Any],
    checkpoint_dir: str | Path,
    run_id: str,
) -> dict[str, Callable[..., RepairExecutionResult]]:
    """Bind admitted repair kinds to the existing research runtime.

    Every experiment request executes exactly one lineage-bound node through
    ``_run_loop``.  Temporarily reducing ``max_total_nodes`` prevents the
    repair action from widening into an ordinary open-ended exploration.
    """

    checkpoint = Path(checkpoint_dir).resolve()

    def _preflight(
        request: ResearchRepairRequestV1,
    ) -> RepairExecutionResult | None:
        if request.source_context_digest != _current_context_digest(checkpoint):
            return _result(request, "failed", reason="source_context_mismatch")
        if not _authority_is_current(checkpoint, run_id, request):
            return _result(request, "failed", reason="authority_digest_mismatch")
        return None

    def _derived_rebuild(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1 | None = None,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        # The outer coordinator invokes the common evidence segment after an
        # ``executed`` result; no separate projection implementation is allowed.
        return _result(
            request,
            "executed",
            action="common_evidence_segment_rebuild",
            new_nodes=0,
            experiment_runs=0,
            llm_calls=0,
        )

    def _literature_search(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        topic = str(experiment_data.get("goal") or "").strip()
        if not topic:
            return _result(request, "human_required", reason="research_topic_missing")
        target = checkpoint / "related_refs.json"
        existing = _json_object(target)
        if existing is None:
            return _result(request, "failed", reason="existing_retrieval_record_invalid")
        old_records = existing.get("records") or existing.get("papers") or []
        revisions = existing.get("retrieval_revisions") or []
        if not isinstance(old_records, list) or not isinstance(revisions, list):
            return _result(request, "failed", reason="existing_retrieval_record_invalid")
        for revision in revisions:
            if not isinstance(revision, dict):
                return _result(
                    request, "failed", reason="existing_retrieval_record_invalid"
                )
            if revision.get("request_digest") == request.request_digest:
                # The recorded response is the idempotency boundary.  A crash
                # after the provider call but before the transaction record can
                # therefore resume with no network access or duplicate query.
                return _result(
                    request,
                    "executed",
                    action="recorded_literature_retrieval_reused",
                    retrieval_revision_id=str(
                        revision.get("retrieval_revision_id") or ""
                    ),
                    record_count=len(
                        [item for item in old_records if isinstance(item, dict)]
                    ),
                    cache_reuse=True,
                    new_nodes=0,
                    experiment_runs=0,
                    llm_calls=1,
                )

        mcp = getattr(agent, "mcp", None)
        if mcp is None or not hasattr(mcp, "call_tool"):
            return _result(request, "unavailable", reason="literature_resolver_unavailable")
        parameters = {"topic": topic[:1200], "max_papers": 12}
        try:
            raw = mcp.call_tool("survey", parameters)
            if not isinstance(raw, dict) or raw.get("error"):
                return _result(
                    request,
                    "unavailable",
                    reason="literature_tool_failed",
                    resolver_error=str((raw or {}).get("error") or "invalid envelope")[:500],
                )
            body = raw.get("result")
            payload = json.loads(body) if isinstance(body, str) else body
            papers = (payload or {}).get("papers") if isinstance(payload, dict) else None
            records = [item for item in (papers or []) if isinstance(item, dict)]
        except Exception as exc:
            return _result(
                request,
                "unavailable",
                reason="literature_tool_failed",
                resolver_error=f"{type(exc).__name__}: {exc}"[:500],
            )
        if not records:
            return _result(request, "still_missing", reason="literature_result_empty")

        merged: dict[str, dict[str, Any]] = {}
        for index, item in enumerate([*old_records, *records]):
            if not isinstance(item, dict):
                continue
            identity = str(
                item.get("record_id")
                or item.get("paper_id")
                or item.get("id")
                or item.get("doi")
                or item.get("url")
                or item.get("title")
                or f"record-{index:04d}"
            )
            merged.setdefault(identity, dict(item))
        ordered_record_ids = sorted(merged)
        revision_payload = {
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "source_context_digest": request.source_context_digest,
            "semantic_capability_id": "ari.literature.search/v1",
            "tool_name": "survey",
            "query": topic[:1200],
            "parameters": parameters,
            "ordered_record_ids": ordered_record_ids,
            "cache_policy": "recorded-response-reuse-v1",
        }
        retrieval_revision_id = canonical_digest(revision_payload)
        revision = {
            "retrieval_revision_id": retrieval_revision_id,
            **revision_payload,
        }
        _atomic_json(
            target,
            {
                "schema_version": "ari.related-refs/v1",
                "records": [merged[key] for key in ordered_record_ids],
                "repair_request_ids": sorted(
                    set(existing.get("repair_request_ids") or ()) | {request.request_id}
                ),
                "retrieval_revisions": [
                    *revisions,
                    revision,
                ],
            },
        )
        return _result(
            request,
            "executed",
            action="recorded_literature_retrieval",
            retrieval_revision_id=retrieval_revision_id,
            record_count=len(merged),
            new_nodes=0,
            experiment_runs=0,
            # One admitted resolver-call unit is charged conservatively even
            # when the concrete survey provider is not an LLM.
            llm_calls=1,
        )

    def _limitation_disclosure(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1 | None = None,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        target = checkpoint / "manuscript_disclosures.json"
        existing = _json_object(target)
        if existing is None:
            return _result(request, "failed", reason="existing_disclosure_record_invalid")
        records = existing.get("records") or []
        if not isinstance(records, list):
            return _result(request, "failed", reason="existing_disclosure_record_invalid")
        by_id = {
            str(item.get("request_id")): dict(item)
            for item in records
            if isinstance(item, dict) and item.get("request_id")
        }
        by_id.setdefault(
            request.request_id,
            {
                "request_id": request.request_id,
                "source_context_digest": request.source_context_digest,
                "requirement_ids": list(request.requirement_ids),
                "limitation": (
                    "The evidence required by "
                    + ", ".join(request.requirement_ids)
                    + " was not available in the bound exploration snapshot; "
                    "the manuscript must disclose this gap and must not infer the missing result."
                ),
                "threat_to_validity": (
                    "Conclusions covered by the listed requirements remain limited "
                    "until new bound evidence resolves the recorded gap."
                ),
            },
        )
        _atomic_json(
            target,
            {
                "schema_version": "ari.manuscript-disclosures/v1",
                "records": [by_id[key] for key in sorted(by_id)],
            },
        )
        return _result(
            request,
            "executed",
            action="mandatory_disclosure_recorded",
            new_nodes=0,
            experiment_runs=0,
            llm_calls=0,
        )

    def _experiment(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        if remaining.max_new_nodes < 1 or remaining.max_experiment_runs < 1:
            return _result(request, "exhausted", reason="experiment_budget_exhausted")
        if remaining.max_llm_calls < 1:
            return _result(request, "exhausted", reason="llm_budget_exhausted")

        node_id = _repair_node_id(request)
        existing = next(
            (
                node
                for node in all_nodes
                if str(getattr(node, "repair_request_id", "") or "")
                == request.request_id
            ),
            None,
        )
        if existing is not None:
            existing_status = str(
                getattr(
                    getattr(existing, "status", ""),
                    "value",
                    getattr(existing, "status", ""),
                )
            )
            if existing_status == "success":
                return _result(
                    request,
                    "executed",
                    action="existing_repair_node_reused",
                    node_id=str(getattr(existing, "id", node_id)),
                    node_status=existing_status,
                    new_nodes=0,
                    experiment_runs=0,
                    llm_calls=0,
                )
            if existing_status in {"failed", "abandoned"}:
                return _result(
                    request,
                    "failed",
                    action="existing_repair_node_terminal",
                    reason=f"repair_node_{existing_status}",
                    node_id=str(getattr(existing, "id", node_id)),
                    node_status=existing_status,
                    new_nodes=0,
                    experiment_runs=0,
                    llm_calls=0,
                )
            if existing_status not in {"pending", "running"}:
                return _result(
                    request,
                    "failed",
                    reason="repair_node_status_invalid",
                    node_id=str(getattr(existing, "id", node_id)),
                    node_status=existing_status,
                    new_nodes=0,
                    experiment_runs=0,
                    llm_calls=0,
                )

        if existing is None:
            from ari.orchestrator.node import Node, NodeLabel
            from ari.pipeline.verified_context import select_best_node

            parent = select_best_node(all_nodes)
            label = NodeLabel.from_str(_EXPERIMENT_LABELS[request.kind])
            direction = (
                _EXPERIMENT_DIRECTIVES[request.kind]
                + "\n\nManuscript repair envelope (mandatory):\n"
                + f"- request_id: {request.request_id}\n"
                + f"- source_context_digest: {request.source_context_digest}\n"
                + f"- requirement_ids: {', '.join(request.requirement_ids)}\n"
                + f"- fixed_variables: {json.dumps(request.fixed_variables, sort_keys=True)}\n"
                + f"- allowed_changes: {', '.join(request.allowed_changes)}\n"
                + "Do not change variables or authority outside this envelope. "
                + "Report failure or unavailability explicitly; do not fabricate a result."
            )
            node = Node(
                id=node_id,
                parent_id=(str(getattr(parent, "id")) if parent is not None else None),
                depth=(
                    int(getattr(parent, "depth", -1)) + 1
                    if parent is not None
                    else 0
                ),
                memory_snapshot=(
                    list(getattr(parent, "memory_snapshot", []) or [])
                    if parent is not None
                    else []
                ),
                label=label,
                raw_label="manuscript-repair",
                ancestor_ids=(
                    list(getattr(parent, "ancestor_ids", []) or [])
                    + [str(getattr(parent, "id"))]
                    if parent is not None
                    else []
                ),
                original_direction=direction,
                repair_request_id=request.request_id,
                repair_requirement_ids=list(request.requirement_ids),
                repair_context_digest=request.source_context_digest,
                repair_allowed_changes=list(request.allowed_changes),
            )
            node.eval_summary = direction
            node.name = f"manuscript repair: {request.kind}"
            if parent is not None and node.id not in getattr(parent, "children", []):
                parent.children.append(node.id)

            rqgm = getattr(bfts, "rqgm", None)
            if rqgm is not None:
                stamp = getattr(rqgm, "stamp_node_producer", None)
                if callable(stamp):
                    stamp(node)
                record = getattr(rqgm, "record_expansion_proposal", None)
                if callable(record) and parent is not None:
                    record(parent, node)

            all_nodes.append(node)
        else:
            node = existing

        # Commit materialization before invoking the ordinary research loop.
        # If the process stops here, resume finds the lineage-bound pending
        # node and continues it instead of creating a duplicate request node.
        from ari.cli.bfts_loop import _run_loop, _save_checkpoint

        _save_checkpoint(
            checkpoint,
            run_id,
            experiment_data.get("file", checkpoint / "experiment.md"),
            all_nodes,
        )
        before_trace = _trace_count(checkpoint)
        original_nodes = cfg.bfts.max_total_nodes
        original_steps = cfg.bfts.max_react_steps
        try:
            # With one pending repair node and max_total_nodes equal to the
            # current list size, _run_loop executes that node but cannot expand
            # any frontier afterward.
            cfg.bfts.max_total_nodes = len(all_nodes)
            cfg.bfts.max_react_steps = min(
                int(original_steps), max(1, int(remaining.max_llm_calls))
            )
            _run_loop(
                cfg,
                bfts,
                agent,
                [node],
                all_nodes,
                experiment_data,
                checkpoint,
                run_id,
                total_processed=max(0, len(all_nodes) - 1),
            )
        finally:
            cfg.bfts.max_total_nodes = original_nodes
            cfg.bfts.max_react_steps = original_steps
        prompt_uses = max(1, _trace_count(checkpoint) - before_trace)
        return _result(
            request,
            "executed",
            action="bounded_research_node_executed",
            node_id=node.id,
            node_status=str(getattr(node.status, "value", node.status)),
            # A pre-existing pending/running node is a crash-reconciled unit
            # whose cost was not yet committed to a repair transaction.
            new_nodes=1,
            experiment_runs=1,
            llm_calls=prompt_uses,
        )

    def _certification(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        if remaining.max_experiment_runs < 1:
            return _result(request, "exhausted", reason="certification_budget_exhausted")
        rqgm = getattr(bfts, "rqgm", None)
        certify = getattr(rqgm, "certify_node", None) if rqgm is not None else None
        if not callable(certify):
            return _result(request, "unavailable", reason="certification_runtime_unavailable")
        from ari.pipeline.verified_context import select_best_node

        candidate = select_best_node(all_nodes)
        if candidate is None:
            return _result(request, "still_missing", reason="scientific_candidate_missing")
        frontier = certify(candidate)
        from ari.cli.bfts_loop import _save_checkpoint

        _save_checkpoint(
            checkpoint,
            run_id,
            experiment_data.get("file", checkpoint / "experiment.md"),
            all_nodes,
        )
        return _result(
            request,
            "executed",
            action="frozen_certification_suite_executed",
            node_id=str(getattr(candidate, "id", "")),
            frontier_class=str(frontier),
            assurance_status=str(getattr(candidate, "assurance_status", "")),
            new_nodes=0,
            experiment_runs=1,
            llm_calls=0,
        )

    def _human_required(
        request: ResearchRepairRequestV1,
        remaining: RepairBudgetV1 | None = None,
    ) -> RepairExecutionResult:
        failed = _preflight(request)
        if failed is not None:
            return failed
        return _result(
            request,
            "human_required",
            reason="resolver_requires_admitted_human_input",
        )

    return {
        "artifact_recovery": _derived_rebuild,
        "projection_rebuild": _derived_rebuild,
        "literature_search": _literature_search,
        "baseline_comparison": _experiment,
        "repetition_or_uncertainty": _experiment,
        "ablation": _experiment,
        "validation_experiment": _experiment,
        "assurance_certification": _certification,
        "method_clarification": _human_required,
        "limitation_disclosure": _limitation_disclosure,
        "human_decision": _human_required,
    }


__all__ = ["build_research_repair_executors"]
