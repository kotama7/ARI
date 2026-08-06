"""Opt-in runtime adapter for the fixed manuscript compiler boundary."""

from __future__ import annotations

import os
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ari.manuscript.contracts import (
    AutoRepairRoundResultV1,
    ManuscriptAutoRepairRoundV1,
    ManuscriptRepairTransactionV1,
    RepairBudgetUsageV1,
    RepairBudgetV1,
)
from ari.manuscript.coordinator import (
    ManuscriptAuthoringBlocked,
    ManuscriptOutcome,
    compile_manuscript,
)
from ari.manuscript.digest import file_digest, path_has_symlink_component
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


def _runtime_optional_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


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
            max_resource_units=_runtime_optional_float(
                "ARI_MANUSCRIPT_MAX_RESOURCE_UNITS"
            ),
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
    used_budget: dict[str, int | float]


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

    def _transaction_documents() -> list[ManuscriptRepairTransactionV1]:
        root = store.root / "repair-transactions"
        documents: list[ManuscriptRepairTransactionV1] = []
        if not root.is_dir():
            return documents
        if path_has_symlink_component(checkpoint, root):
            raise ValueError("repair transaction directory cannot be a symlink")
        for path in sorted(root.glob("*.json")):
            try:
                if path_has_symlink_component(checkpoint, path):
                    raise ValueError("repair transaction cannot be a symlink")
                value = ManuscriptRepairTransactionV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                raise ValueError(f"invalid persisted repair transaction: {path}")
            if path.name != f"{value.request_id}.json":
                raise ValueError("repair transaction filename disagrees with its request")
            documents.append(value)
        return documents

    usage: dict[str, int | float] = {
        "new_nodes": 0,
        "experiment_runs": 0,
        "llm_calls": 0,
        "resource_units": 0.0,
    }
    for document in _transaction_documents():
        details = document.details
        for key in usage:
            raw_value = details.get(key, 0.0 if key == "resource_units" else 0)
            if key == "resource_units":
                if (
                    not isinstance(raw_value, (int, float))
                    or isinstance(raw_value, bool)
                ):
                    raise ValueError(
                        "persisted repair transaction has invalid budget use"
                    )
                value: int | float = float(raw_value)
            else:
                if not isinstance(raw_value, int) or isinstance(raw_value, bool):
                    raise ValueError(
                        "persisted repair transaction has invalid budget use"
                    )
                value = raw_value
            if not math.isfinite(value) or value < 0:
                raise ValueError("persisted repair transaction has negative budget use")
            usage[key] += value

    round_root = store.root / "auto-rounds"
    existing_rounds: dict[str, ManuscriptAutoRepairRoundV1] = {}
    if round_root.is_dir():
        if path_has_symlink_component(checkpoint, round_root):
            raise ValueError("automatic repair round directory cannot be a symlink")
        for path in sorted(round_root.glob("*.json")):
            try:
                if path_has_symlink_component(checkpoint, path):
                    raise ValueError("automatic repair round cannot be a symlink")
                value = ManuscriptAutoRepairRoundV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                raise ValueError(f"invalid persisted automatic repair round: {path}")
            plan_digest = value.plan_digest
            if not plan_digest or plan_digest in existing_rounds:
                raise ValueError("automatic repair round identity is invalid or duplicated")
            expected_name = f"{plan_digest.removeprefix('sha256:')[:32]}.json"
            if path.name != expected_name:
                raise ValueError("automatic repair round filename disagrees with its plan")
            existing_rounds[plan_digest] = value
        if sorted(item.round for item in existing_rounds.values()) != list(
            range(len(existing_rounds))
        ):
            raise ValueError("automatic repair round sequence is not contiguous")

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
            or (
                _runtime_optional_float("ARI_MANUSCRIPT_MAX_RESOURCE_UNITS")
                is not None
                and usage["resource_units"]
                > float(
                    _runtime_optional_float("ARI_MANUSCRIPT_MAX_RESOURCE_UNITS")
                )
            )
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
        from ari.manuscript.repair import (
            bind_transactional_executors,
            execute_repair_plan,
        )

        transactional = bind_transactional_executors(
            plan, checkpoint, executors
        )

        results = execute_repair_plan(
            plan,
            executors=transactional,
            used_budget=usage,
        )
        round_index = len(existing_rounds)
        transaction_digests: list[str] = []
        for item in results:
            path = store.root / "repair-transactions" / f"{item.request_id}.json"
            if path.is_file() and not path_has_symlink_component(checkpoint, path):
                transaction_digests.append(
                    ManuscriptRepairTransactionV1.model_validate_json(
                        path.read_text(encoding="utf-8")
                    ).transaction_digest
                )
        round_record = ManuscriptAutoRepairRoundV1.create(
            round=round_index,
            plan_digest=plan.plan_digest,
            source_context_digest=readiness.context_digest,
            request_ids=tuple(item.request_id for item in plan.requests),
            transaction_digests=tuple(transaction_digests),
            results=tuple(
                AutoRepairRoundResultV1(
                    request_id=item.request_id,
                    status=item.status,
                    details=item.details,
                )
                for item in results
            ),
            used_budget=RepairBudgetUsageV1.model_validate(usage),
        )
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
            if artifact.relative_path is None:
                continue
            source = checkpoint / artifact.relative_path
            if artifact.status == "missing":
                if source.exists() or path_has_symlink_component(checkpoint, source):
                    return False
                continue
            if artifact.digest is None or artifact.size_bytes is None:
                # A path-bearing source with no stable byte identity cannot
                # authorize publication freshness.
                return False
            if (
                not source.is_file()
                or path_has_symlink_component(checkpoint, source)
                or file_digest(source)
                != (artifact.digest, artifact.size_bytes)
            ):
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
            if not source.is_file() or path_has_symlink_component(checkpoint, source):
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
    loaded: dict[str, Any] = {}
    from ari.manuscript.contracts import (
        ManuscriptAuthoringBindingV1,
        ManuscriptContextV1,
        ManuscriptReadinessReportV1,
        ManuscriptRequirementProfileV1,
        SectionBriefBundleV1,
    )

    contracts = {
        "manuscript-profile": ManuscriptRequirementProfileV1,
        "manuscript-context": ManuscriptContextV1,
        "manuscript-readiness": ManuscriptReadinessReportV1,
        "section-briefs": SectionBriefBundleV1,
        "manuscript-authoring-binding": ManuscriptAuthoringBindingV1,
    }
    expected_names = {
        "manuscript-profile": "requirement_profile.json",
        "manuscript-context": "context.json",
        "manuscript-readiness": "readiness.json",
        "section-briefs": "section_briefs.json",
        "manuscript-authoring-binding": "authoring_binding.json",
    }
    expected_root = (
        checkpoint / ".ari-manuscript" / "attempts" / binding.attempt_id
    ).resolve()
    for role, env_name in required.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            return False
        path = Path(os.path.abspath(Path(raw)))
        try:
            relative = path.relative_to(checkpoint).as_posix()
        except ValueError:
            return False
        declared = by_role[role]
        if (
            path.parent != expected_root
            or path.name != expected_names[role]
            or declared.relative_path != relative
            or not path.is_file()
            or path_has_symlink_component(checkpoint, path)
            or file_digest(path) != (declared.digest, declared.size_bytes)
        ):
            return False
        try:
            loaded[role] = contracts[role].model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
    profile = loaded["manuscript-profile"]
    context = loaded["manuscript-context"]
    readiness = loaded["manuscript-readiness"]
    briefs = loaded["section-briefs"]
    loaded_binding = loaded["manuscript-authoring-binding"]
    return bool(
        loaded_binding == binding
        and context.profile_digest == profile.profile_digest
        and readiness.profile_digest == profile.profile_digest
        and briefs.profile_digest == profile.profile_digest
        and binding.profile_digest == profile.profile_digest
        and readiness.context_digest == context.context_digest
        and briefs.context_digest == context.context_digest
        and binding.context_digest == context.context_digest
        and briefs.readiness_digest == readiness.readiness_digest
        and binding.readiness_digest == readiness.readiness_digest
        and binding.brief_bundle_digest == briefs.bundle_digest
        and binding.source_snapshot_digest == context.source_snapshot_digest
        and binding.target_build_id == build.build_id
        and binding.target_build_revision == build.build_revision
        and binding.run_id == build.run_id
        and binding.attempt_id
        and readiness.authoring_verdict in {"ready", "ready_with_disclosures"}
    )


def _normalise_required_text(value: str) -> str:
    """Normalise prose for deterministic disclosure-presence checks."""

    value = re.sub(r"\\[A-Za-z@]+\*?", " ", str(value or ""))
    value = "".join(
        character if character.isalnum() else " "
        for character in value.casefold()
    )
    return " ".join(value.split())


def _contains_machine_id(text: str, identity: str) -> bool:
    token = str(identity or "")
    if not token:
        return False
    # A period commonly follows an ID at sentence end, so it is deliberately
    # treated as a delimiter. Generated Manuscript evidence IDs do not end in
    # a period.
    alphabet = r"A-Za-z0-9_:/-"
    return bool(
        re.search(
            rf"(?<![{alphabet}]){re.escape(token)}(?![{alphabet}])",
            text,
            flags=re.IGNORECASE,
        )
    )


def _manuscript_authoring_content_pass(
    checkpoint: Path,
    build: Any,
) -> bool:
    """Re-check the fixed brief obligations against the exact final TeX.

    Contextual-negative evidence remains available to write an honest negative
    result in prose, but its machine evidence ID cannot be emitted as claim
    support.  The same conservative rule applies to exploratory/excluded IDs.
    Required disclosures must occur at least once after LaTeX-insensitive text
    normalisation.  This check is shared by linear and archive authoring at the
    publication boundary; archive candidate screening is an earlier defence,
    not the final authority.
    """

    from ari.manuscript.contracts import SectionBriefBundleV1

    briefs_raw = os.environ.get("ARI_MANUSCRIPT_BRIEFS_PATH", "").strip()
    if not briefs_raw:
        return False
    briefs_path = Path(os.path.abspath(briefs_raw))
    try:
        briefs_path.relative_to(checkpoint)
    except ValueError:
        return False
    if (
        not briefs_path.is_file()
        or briefs_path.is_symlink()
        or path_has_symlink_component(checkpoint, briefs_path)
    ):
        return False
    try:
        briefs = SectionBriefBundleV1.model_validate_json(
            briefs_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False

    final_tex = [item for item in build.final_artifacts if item.role == "final-tex"]
    if len(final_tex) != 1:
        return False
    tex_path = checkpoint / final_tex[0].relative_path
    if (
        not tex_path.is_file()
        or tex_path.is_symlink()
        or path_has_symlink_component(checkpoint, tex_path)
    ):
        return False
    try:
        text = tex_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    non_positive_ids = {
        str(evidence_id)
        for brief in briefs.briefs
        for evidence_id in (
            *brief.contextual_negative_ids,
            *brief.forbidden_evidence_ids,
        )
        if str(evidence_id)
    }
    if any(_contains_machine_id(text, evidence_id) for evidence_id in non_positive_ids):
        return False
    required = {
        str(disclosure)
        for brief in briefs.briefs
        for disclosure in brief.required_disclosures
        if _normalise_required_text(str(disclosure))
    }
    normalised_text = _normalise_required_text(text)
    return all(
        _normalise_required_text(disclosure) in normalised_text
        for disclosure in required
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
    if path_has_symlink_component(checkpoint, build_path) or any(
        path_has_symlink_component(
            checkpoint, Path(os.path.abspath(os.environ[name]))
        )
        for name in required_env
    ):
        raise ValueError("publication input path is outside or traverses a symlink")

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
    if reproduction_path.is_file() and not path_has_symlink_component(
        checkpoint, reproduction_path
    ):
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
    claim_passed = bool(
        build.gate
        and build.gate.status == "pass"
        and _manuscript_authoring_content_pass(checkpoint, build)
    )
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
    if not binding_path.is_file() or path_has_symlink_component(
        checkpoint, Path(os.path.abspath(binding_path))
    ):
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
        or path_has_symlink_component(checkpoint, reproduction_path)
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
