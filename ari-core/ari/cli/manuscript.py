"""Operator CLI for Manuscript Complete attempts and explicit repair.

Domain imports stay inside callbacks so constructing the ordinary ``ari`` CLI
does not import ``ari.manuscript`` or create manuscript state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import typer


manuscript_app = typer.Typer(
    help="Inspect, compile, repair, and explain Manuscript Complete attempts."
)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _emit(value: Any) -> None:
    typer.echo(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
    )


def _checkpoint(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise typer.BadParameter(f"checkpoint is not a directory: {resolved}")
    if not (resolved / "tree.json").is_file():
        raise typer.BadParameter(f"checkpoint has no tree.json: {resolved}")
    return resolved


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise typer.BadParameter(f"JSON document is not an object: {path}")
    return value


def _state(checkpoint: Path) -> dict[str, Any]:
    from ari.manuscript.state import ManuscriptStateStore

    return ManuscriptStateStore(checkpoint).read_state()


def _attempt_dir(checkpoint: Path, state: dict[str, Any]) -> Path:
    attempt = str(state.get("attempt_id") or "")
    if not attempt:
        raise typer.BadParameter(
            "checkpoint has no manuscript attempt; run `ari manuscript compile` first"
        )
    path = checkpoint / ".ari-manuscript" / "attempts" / attempt
    if not path.is_dir():
        raise typer.BadParameter(f"manuscript attempt directory is missing: {path}")
    return path


def _load_nodes(checkpoint: Path) -> tuple[str, list[Any]]:
    from ari.orchestrator.node import Node, NodeLabel, NodeStatus

    tree = _read_object(checkpoint / "tree.json")
    run_id = str(tree.get("run_id") or checkpoint.name)
    nodes: list[Any] = []
    for raw in tree.get("nodes") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        node = Node(
            id=str(raw["id"]),
            parent_id=raw.get("parent_id"),
            depth=int(raw.get("depth") or 0),
            retry_count=int(raw.get("retry_count") or 0),
            memory_snapshot=list(raw.get("memory_snapshot") or []),
            artifacts=list(raw.get("artifacts") or []),
            trace_log=list(raw.get("trace_log") or []),
            error_log=raw.get("error_log"),
            metrics=dict(raw.get("metrics") or {}),
            has_real_data=bool(raw.get("has_real_data", False)),
            eval_summary=raw.get("eval_summary") or raw.get("score_reason"),
            label=NodeLabel.from_str(str(raw.get("label") or "draft")),
            raw_label=str(raw.get("raw_label") or ""),
            name=str(raw.get("name") or ""),
            ancestor_ids=list(raw.get("ancestor_ids") or []),
            children=list(raw.get("children") or []),
            created_at=str(raw.get("created_at") or ""),
            completed_at=str(raw.get("completed_at") or ""),
            original_direction=raw.get("original_direction"),
            producer_component_id=str(raw.get("producer_component_id") or ""),
            producer_prompt_hash=str(raw.get("producer_prompt_hash") or ""),
            producer_epoch_id=str(raw.get("producer_epoch_id") or ""),
            node_report_path=raw.get("node_report_path"),
            knowledge_skill_refs=list(raw.get("knowledge_skill_refs") or []),
            knowledge_skill_use_digest=str(raw.get("knowledge_skill_use_digest") or ""),
            instruction_identity_digest=str(raw.get("instruction_identity_digest") or ""),
            capability_binding_lock_digest=str(raw.get("capability_binding_lock_digest") or ""),
            bound_tool_refs=list(raw.get("bound_tool_refs") or []),
            assurance_status=str(raw.get("assurance_status") or ""),
            assurance_tier=str(raw.get("assurance_tier") or ""),
            baseline_harness_lock_digest=str(raw.get("baseline_harness_lock_digest") or ""),
            active_harness_lock_digest=str(raw.get("active_harness_lock_digest") or ""),
            attestation_refs=list(raw.get("attestation_refs") or []),
            verified_target_digest=str(raw.get("verified_target_digest") or ""),
            property_verdicts=dict(raw.get("property_verdicts") or {}),
            frontier_class=str(raw.get("frontier_class") or ""),
            repair_request_id=str(raw.get("repair_request_id") or ""),
            repair_requirement_ids=list(raw.get("repair_requirement_ids") or []),
            repair_context_digest=str(raw.get("repair_context_digest") or ""),
            repair_allowed_changes=list(raw.get("repair_allowed_changes") or []),
        )
        try:
            node.status = NodeStatus(str(raw.get("status") or "pending"))
        except ValueError:
            node.status = NodeStatus.PENDING
        nodes.append(node)
    return run_id, nodes


def _experiment_data(checkpoint: Path) -> dict[str, str]:
    tree = _read_object(checkpoint / "tree.json")
    local = checkpoint / "experiment.md"
    source = local if local.is_file() else Path(str(tree.get("experiment_file") or ""))
    try:
        text = source.read_text(encoding="utf-8") if source.is_file() else ""
    except (OSError, UnicodeDecodeError):
        text = ""
    match = re.search(r"^#\s*(.+)", text, re.MULTILINE)
    title = match.group(1)[:80] if match else source.stem
    topic = re.sub(r"[^a-zA-Z0-9_-]", "_", title)
    return {"goal": text, "topic": topic, "file": str(source)}


def _config(config: Path | None, checkpoint: Path):
    from ari.cli.run import _resolve_cfg

    effective = config
    if effective is None and (checkpoint / "workflow.yaml").is_file():
        effective = checkpoint / "workflow.yaml"
    return _resolve_cfg(effective)


def _paper_mode(cfg) -> str:
    from ari.config import _effective_paper_mode_str

    return _effective_paper_mode_str(cfg)


def _repair_budget(cfg):
    from ari.manuscript.contracts import RepairBudgetV1

    repair = cfg.manuscript.repair
    return RepairBudgetV1(
        max_rounds=repair.max_rounds,
        max_new_nodes=repair.max_new_nodes,
        max_experiment_runs=repair.max_experiment_runs,
        max_llm_calls=repair.max_llm_calls,
        max_resource_units=repair.max_resource_units,
    )


@manuscript_app.command("status")
def manuscript_status(
    checkpoint_dir: Path = typer.Argument(...),
    fail_if_blocked: bool = typer.Option(False, "--fail-if-blocked"),
) -> None:
    """Show the current attempt, gaps, repair budget, and publication lock."""

    checkpoint = _checkpoint(checkpoint_dir)
    state = _state(checkpoint)
    payload: dict[str, Any] = {"checkpoint": str(checkpoint), "state": state}
    if state.get("attempt_id"):
        attempt = _attempt_dir(checkpoint, state)
        readiness_path = attempt / "readiness.json"
        if readiness_path.is_file():
            from ari.manuscript.contracts import ManuscriptReadinessReportV1

            readiness = ManuscriptReadinessReportV1.model_validate(
                _read_object(readiness_path)
            )
            payload["readiness"] = {
                "readiness_digest": readiness.readiness_digest,
                "authoring_verdict": readiness.authoring_verdict,
                "publication_verdict": readiness.publication_verdict,
                "counts": readiness.counts,
                "outstanding": [
                    {
                        "requirement_id": item.requirement_id,
                        "status": item.status,
                        "reason_code": item.reason_code,
                        "resolver_kind": item.resolver_kind,
                        "authoring_blocking": item.authoring_blocking,
                        "publication_blocking": item.publication_blocking,
                    }
                    for item in readiness.requirement_results
                    if item.status in {"missing", "unavailable"}
                ],
            }
        plan_path = attempt / "repair_plan.json"
        if plan_path.is_file():
            payload["repair_plan"] = _read_object(plan_path)
        decision_path = attempt / "publication_decision.json"
        if decision_path.is_file():
            payload["publication_decision"] = _read_object(decision_path)
        lock_path = attempt / "publication_lock.json"
        if lock_path.is_file():
            payload["publication_lock"] = _read_object(lock_path)
    _emit(payload)
    readiness_payload = payload.get("readiness") or {}
    if fail_if_blocked and (
        readiness_payload.get("authoring_verdict") in {"repair_required", "blocked"}
        or readiness_payload.get("publication_verdict") == "blocked"
    ):
        raise typer.Exit(2)


@manuscript_app.command("inspect")
def manuscript_inspect(
    checkpoint_dir: Path = typer.Argument(...),
    requirement: str | None = typer.Option(None, "--requirement"),
    lane: str | None = typer.Option(None, "--lane"),
    node: str | None = typer.Option(None, "--node"),
) -> None:
    """Inspect requirement traces, evidence lanes, omissions, or one node."""

    checkpoint = _checkpoint(checkpoint_dir)
    state = _state(checkpoint)
    attempt = _attempt_dir(checkpoint, state)
    from ari.manuscript.contracts import (
        ManuscriptContextV1,
        ManuscriptReadinessReportV1,
        OmissionManifestV1,
    )

    context = ManuscriptContextV1.model_validate(_read_object(attempt / "context.json"))
    readiness = ManuscriptReadinessReportV1.model_validate(
        _read_object(attempt / "readiness.json")
    )
    omissions = OmissionManifestV1.model_validate(
        _read_object(attempt / "omission_manifest.json")
    )
    requirement_rows = [
        item.model_dump(mode="json")
        for item in readiness.requirement_results
        if requirement is None or item.requirement_id == requirement
    ]
    evidence_rows = [
        item.model_dump(mode="json")
        for item in context.evidence_records
        if (lane is None or item.lane == lane)
        and (node is None or item.node_id == node)
    ]
    history_rows = [
        item
        for item in context.exploration_history
        if node is None or str(item.get("node_id")) == node
    ]
    if requirement and not requirement_rows:
        raise typer.BadParameter(f"unknown requirement in current profile: {requirement}")
    if lane and lane not in {"publishable", "exploratory", "contextual_negative", "excluded"}:
        raise typer.BadParameter(f"unknown evidence lane: {lane}")
    _emit(
        {
            "attempt_id": state.get("attempt_id"),
            "context_digest": context.context_digest,
            "requirements": requirement_rows,
            "evidence": evidence_rows,
            "exploration_history": history_rows,
            "omissions": [item.model_dump(mode="json") for item in omissions.omissions],
        }
    )


@manuscript_app.command("compile")
def manuscript_compile(
    checkpoint_dir: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
    mode: str = typer.Option("audit", "--mode"),
    profile: str | None = typer.Option(None, "--profile"),
    repair_policy: str | None = typer.Option(None, "--repair-policy"),
) -> None:
    """Compile a fresh deterministic attempt without starting authoring."""

    checkpoint = _checkpoint(checkpoint_dir)
    if mode not in {"audit", "enforce"}:
        raise typer.BadParameter("--mode must be audit or enforce")
    cfg = _config(config, checkpoint)
    policy = repair_policy or cfg.manuscript.repair.policy
    if policy not in {"disabled", "explicit", "auto"}:
        raise typer.BadParameter("invalid repair policy")
    if policy == "auto" and mode != "enforce":
        raise typer.BadParameter("auto repair requires --mode enforce")
    run_id, nodes = _load_nodes(checkpoint)
    data = _experiment_data(checkpoint)
    cfg.manuscript.mode = mode
    cfg.manuscript.repair.policy = policy
    from ari.cli.paper_dispatch import _manuscript_runtime_environment
    from ari.manuscript.authority import capture_repair_authority
    from ari.manuscript.coordinator import compile_manuscript

    with _manuscript_runtime_environment(cfg, paper_mode=_paper_mode(cfg)):
        outcome = compile_manuscript(
            checkpoint,
            nodes,
            experiment_data=data,
            mode=mode,
            profile_id=profile or cfg.manuscript.profile,
            repair_policy=policy,
            assurance_mode=str(getattr(cfg.assurance, "mode", "off")),
            exploration_mode=str(getattr(cfg.ari, "mode", "simple_bfts")),
            paper_mode=_paper_mode(cfg),
            brief_character_budget=cfg.manuscript.brief_character_budget,
            repair_budget=_repair_budget(cfg),
            authority=capture_repair_authority(checkpoint, run_id=run_id),
        )
    _emit(
        {
            "attempt_id": outcome.attempt_id,
            "state": outcome.state,
            "authoring_ready": outcome.authoring_ready,
            "readiness": outcome.readiness,
            "artifact_paths": outcome.artifact_paths,
        }
    )


def _build_explicit_plan(checkpoint: Path, cfg):
    from ari.cli.paper_dispatch import _manuscript_runtime_environment
    from ari.manuscript.authority import capture_repair_authority
    from ari.manuscript.contracts import ManuscriptReadinessReportV1
    from ari.manuscript.repair import build_repair_plan
    from ari.manuscript.state import ManuscriptStateStore

    state = _state(checkpoint)
    attempt = _attempt_dir(checkpoint, state)
    readiness = ManuscriptReadinessReportV1.model_validate(
        _read_object(attempt / "readiness.json")
    )
    if cfg.manuscript.mode == "off":
        cfg.manuscript.mode = "audit"
    cfg.manuscript.repair.policy = "explicit"
    with _manuscript_runtime_environment(cfg, paper_mode=_paper_mode(cfg)):
        authority = capture_repair_authority(checkpoint, run_id=readiness.run_id)
        plan = build_repair_plan(
            readiness,
            policy="explicit",
            budget=_repair_budget(cfg),
            authority=authority,
        )
    suffix = plan.plan_digest.removeprefix("sha256:")[:24]
    store = ManuscriptStateStore(checkpoint)
    store.write_attempt_artifact(
        str(state["attempt_id"]), f"repair_plan.explicit-{suffix}.json", plan
    )
    store.write_attempt_artifact(
        str(state["attempt_id"]), f"repair_authority.explicit-{suffix}.json", authority
    )
    return state, readiness, plan, authority


@manuscript_app.command("plan-repair")
def manuscript_plan_repair(
    checkpoint_dir: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Persist the deterministic explicit plan; performs no external action."""

    checkpoint = _checkpoint(checkpoint_dir)
    cfg = _config(config, checkpoint)
    state, readiness, plan, authority = _build_explicit_plan(checkpoint, cfg)
    _emit(
        {
            "attempt_id": state.get("attempt_id"),
            "source_context_digest": readiness.context_digest,
            "plan": plan,
            "authority": authority,
            "mutation_scope": [
                {
                    "request_id": item.request_id,
                    "kind": item.kind,
                    "requirement_ids": item.requirement_ids,
                    "allowed_changes": item.allowed_changes,
                    "budget": item.budget,
                }
                for item in plan.requests
            ],
        }
    )


@manuscript_app.command("repair")
def manuscript_repair(
    checkpoint_dir: Path = typer.Argument(...),
    request: list[str] | None = typer.Option(None, "--request"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Execute selected admitted requests through the resumable research runtime."""

    checkpoint = _checkpoint(checkpoint_dir)
    cfg = _config(config, checkpoint)
    cfg.manuscript.mode = "enforce"
    cfg.manuscript.repair.policy = "explicit"
    state, readiness, plan, authority = _build_explicit_plan(checkpoint, cfg)
    selected = set(request or [item.request_id for item in plan.requests])
    known = {item.request_id for item in plan.requests}
    if not selected:
        _emit({"status": "nothing_to_repair", "plan_digest": plan.plan_digest})
        return
    unknown = selected - known
    if unknown:
        raise typer.BadParameter("unknown request IDs: " + ", ".join(sorted(unknown)))
    scope = [
        item.model_dump(mode="json")
        for item in plan.requests
        if item.request_id in selected
    ]
    typer.echo(
        json.dumps(
            {"event": "repair_admitted", "plan_digest": plan.plan_digest, "scope": scope},
            ensure_ascii=False,
            sort_keys=True,
        ),
        err=True,
    )

    from ari.manuscript.digest import canonical_digest
    from ari.manuscript.state import ManuscriptStateStore

    admission_id = canonical_digest(
        {"plan_digest": plan.plan_digest, "selected": sorted(selected)}
    ).removeprefix("sha256:")[:24]
    store = ManuscriptStateStore(checkpoint)
    attempt_id = str(state["attempt_id"])
    execution_name = f"repair_execution.explicit-{admission_id}.json"
    execution_path = store.attempt_dir(attempt_id) / execution_name
    if execution_path.is_file():
        _emit({"reused": True, "execution": _read_object(execution_path)})
        return
    store.write_attempt_artifact(
        attempt_id,
        f"repair_admission.explicit-{admission_id}.json",
        {
            "schema_version": "ari.manuscript-repair-admission/v1",
            "plan_digest": plan.plan_digest,
            "source_context_digest": readiness.context_digest,
            "authority_digest": plan.authority_digest,
            "selected_request_ids": sorted(selected),
            "scope": scope,
        },
    )

    run_id, nodes = _load_nodes(checkpoint)
    data = _experiment_data(checkpoint)
    cfg.logging.dir = str(checkpoint)
    cfg.checkpoint.dir = str(checkpoint)
    from ari.config import apply_rqgm_env_overrides

    apply_rqgm_env_overrides(cfg)
    if (
        (checkpoint / "rqgm_state.json").is_file()
        or getattr(cfg.ari, "mode", "simple_bfts") == "ari_rqgm"
    ):
        from ari.rqgm.state import reconcile_resume_mode

        reconcile_resume_mode(cfg, checkpoint)
    from ari.core import build_runtime, generate_paper_section

    _, _, mcp, bfts, agent, _ = build_runtime(
        cfg, data["goal"], checkpoint_dir=checkpoint
    )
    agent.checkpoint_dir = str(checkpoint)
    from ari.cli.manuscript_repair_runtime import build_research_repair_executors
    from ari.cli.paper_dispatch import _manuscript_runtime_environment
    from ari.manuscript.coordinator import compile_manuscript
    from ari.manuscript.repair import execute_repair_plan
    from ari.manuscript.authority import capture_repair_authority

    current_state = str(state.get("state") or "absent")
    if current_state in {"blocked_unavailable", "publication_blocked"}:
        store.transition(
            run_id=run_id,
            attempt=attempt_id,
            to_state="repair_pending",
            reason_code="explicit_repair_admitted",
            artifact_digests=(plan.plan_digest,),
        )
        current_state = "repair_pending"
    if current_state == "repair_pending":
        store.transition(
            run_id=run_id,
            attempt=attempt_id,
            to_state="repairing",
            reason_code="explicit_repair_started",
            artifact_digests=(plan.plan_digest,),
        )
    elif current_state != "repairing":
        raise typer.BadParameter(
            f"current manuscript state cannot start repair: {current_state}"
        )

    executors = build_research_repair_executors(
        cfg, bfts, agent, nodes, data, checkpoint, run_id
    )
    used_budget: dict[str, int] = {}
    with _manuscript_runtime_environment(cfg, paper_mode=_paper_mode(cfg)):
        results = execute_repair_plan(
            plan,
            executors=executors,
            selected_request_ids=selected,
            used_budget=used_budget,
        )
        if any(item.status in {"executed", "satisfied"} for item in results):
            workflow = checkpoint / "workflow.yaml"
            if not workflow.is_file() and config is not None:
                workflow = config
            generate_paper_section(
                nodes,
                data,
                checkpoint,
                mcp,
                str(workflow),
                include_segments=frozenset({"evidence"}),
            )
        new_authority = capture_repair_authority(checkpoint, run_id=run_id)
        outcome = compile_manuscript(
            checkpoint,
            nodes,
            experiment_data=data,
            mode="enforce",
            profile_id=cfg.manuscript.profile,
            repair_policy="explicit",
            assurance_mode=str(getattr(cfg.assurance, "mode", "off")),
            exploration_mode=str(getattr(cfg.ari, "mode", "simple_bfts")),
            paper_mode=_paper_mode(cfg),
            brief_character_budget=cfg.manuscript.brief_character_budget,
            repair_budget=_repair_budget(cfg),
            authority=new_authority,
        )

    fresh_by_id = {
        item.requirement_id: item for item in outcome.readiness.requirement_results
    }
    closures = []
    for result in results:
        admitted = next(item for item in plan.requests if item.request_id == result.request_id)
        closed = all(
            fresh_by_id[requirement_id].status in {"satisfied", "not_applicable"}
            for requirement_id in admitted.requirement_ids
        )
        closures.append(
            {
                "request_id": result.request_id,
                "executor_status": result.status,
                "status": "satisfied" if closed else (
                    result.status
                    if result.status in {"failed", "exhausted", "human_required", "unavailable"}
                    else "still_missing"
                ),
                "details": result.details,
                "requirement_results": [
                    fresh_by_id[item].model_dump(mode="json")
                    for item in admitted.requirement_ids
                ],
            }
        )
    execution = {
        "schema_version": "ari.manuscript-repair-execution/v1",
        "admission_id": admission_id,
        "plan_digest": plan.plan_digest,
        "source_context_digest": readiness.context_digest,
        "result_context_digest": outcome.context.context_digest,
        "result_readiness_digest": outcome.readiness.readiness_digest,
        "used_budget": used_budget,
        "closures": closures,
    }
    store.write_attempt_artifact(attempt_id, execution_name, execution)
    _emit(
        {
            "reused": False,
            "execution": execution,
            "new_attempt_id": outcome.attempt_id,
            "authoring_ready": outcome.authoring_ready,
        }
    )
    if any(item["status"] != "satisfied" for item in closures):
        raise typer.Exit(2)


@manuscript_app.command("explain-publication")
def manuscript_explain_publication(
    checkpoint_dir: Path = typer.Argument(...),
) -> None:
    """Explain each independent publication gate for the current attempt."""

    checkpoint = _checkpoint(checkpoint_dir)
    state = _state(checkpoint)
    attempt = _attempt_dir(checkpoint, state)
    decision_path = attempt / "publication_decision.json"
    if not decision_path.is_file():
        _emit(
            {
                "decision": "not_evaluated",
                "reason": "publication_decision_missing",
                "attempt_id": state.get("attempt_id"),
            }
        )
        raise typer.Exit(2)
    from ari.manuscript.contracts import PublicationDecisionV1

    decision = PublicationDecisionV1.model_validate(_read_object(decision_path))
    _emit(
        {
            "attempt_id": decision.attempt_id,
            "decision": decision.decision,
            "decision_digest": decision.decision_digest,
            "paper_build_digest": decision.paper_build_digest,
            "gates": [item.model_dump(mode="json") for item in decision.subverdicts],
        }
    )
    if decision.decision != "publishable":
        raise typer.Exit(2)


@manuscript_app.command("lock-publication")
def manuscript_lock_publication(
    checkpoint_dir: Path = typer.Argument(...),
) -> None:
    """TOCTOU-check and lock the exact publishable build and final PDF."""

    checkpoint = _checkpoint(checkpoint_dir)
    state = _state(checkpoint)
    attempt = _attempt_dir(checkpoint, state)
    names = {
        "ARI_MANUSCRIPT_RUNTIME_MODE": "enforce",
        "ARI_MANUSCRIPT_PROFILE_PATH": str(attempt / "requirement_profile.json"),
        "ARI_MANUSCRIPT_CONTEXT_PATH": str(attempt / "context.json"),
        "ARI_MANUSCRIPT_READINESS_PATH": str(attempt / "readiness.json"),
        "ARI_MANUSCRIPT_BRIEFS_PATH": str(attempt / "section_briefs.json"),
        "ARI_MANUSCRIPT_BINDING_PATH": str(attempt / "authoring_binding.json"),
    }
    import os

    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update(names)
        from ari.manuscript.runtime import lock_runtime_publication

        lock = lock_runtime_publication(checkpoint)
    except (OSError, ValueError) as exc:
        _emit(
            {
                "locked": False,
                "attempt_id": state.get("attempt_id"),
                "reason": str(exc),
            }
        )
        raise typer.Exit(2)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    _emit({"locked": True, "publication_lock": lock})


__all__ = ["manuscript_app"]
