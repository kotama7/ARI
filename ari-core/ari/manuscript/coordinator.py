"""Fixed coordinator between evidence preparation and paper authoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ari.manuscript.briefs import build_section_briefs, render_brief_bundle
from ari.manuscript.builder import build_manuscript_context
from ari.manuscript.contracts import (
    ManuscriptAuthoringBindingV1,
    ManuscriptContextV1,
    ManuscriptReadinessReportV1,
    ManuscriptRequirementProfileV1,
    OmissionManifestV1,
    RepairBudgetV1,
    ResearchRepairPlanV1,
    SectionBriefBundleV1,
)
from ari.manuscript.profiles import resolve_profile
from ari.manuscript.readiness import evaluate_readiness
from ari.manuscript.repair import build_repair_plan
from ari.manuscript.snapshot import build_exploration_snapshot
from ari.manuscript.state import ManuscriptStateStore, attempt_id


@dataclass(frozen=True)
class ManuscriptOutcome:
    mode: str
    attempt_id: str | None
    state: str
    profile: ManuscriptRequirementProfileV1 | None = None
    context: ManuscriptContextV1 | None = None
    omissions: OmissionManifestV1 | None = None
    readiness: ManuscriptReadinessReportV1 | None = None
    briefs: SectionBriefBundleV1 | None = None
    authoring_binding: ManuscriptAuthoringBindingV1 | None = None
    repair_plan: ResearchRepairPlanV1 | None = None
    artifact_paths: dict[str, str] | None = None

    @property
    def authoring_ready(self) -> bool:
        return bool(
            self.readiness
            and self.readiness.authoring_verdict in {"ready", "ready_with_disclosures"}
            and self.briefs
            and self.authoring_binding
        )


class ManuscriptAuthoringBlocked(RuntimeError):
    """Enforce mode stopped before any paper-authoring model call."""

    def __init__(self, outcome: ManuscriptOutcome):
        self.outcome = outcome
        readiness = outcome.readiness
        missing = [] if readiness is None else [
            item.requirement_id
            for item in readiness.requirement_results
            if item.authoring_blocking and item.status in {"missing", "unavailable"}
        ]
        super().__init__(
            "manuscript authoring blocked; unresolved requirements: "
            + (", ".join(missing) if missing else "unknown")
        )


def _target_state(readiness: ManuscriptReadinessReportV1) -> str:
    return {
        "ready": "ready",
        "ready_with_disclosures": "ready_with_disclosures",
        "repair_required": "repair_pending",
        "blocked": "blocked_unavailable",
    }[readiness.authoring_verdict]


def _transition_attempt(
    store: ManuscriptStateStore,
    *,
    run_id: str,
    attempt: str,
    source_digest: str,
    context_digest: str,
    readiness_digest: str,
    target: str,
) -> None:
    state = store.read_state()
    current = str(state.get("state") or "absent")
    current_attempt = state.get("attempt_id")
    if current_attempt == attempt and current == target:
        return
    # A repair transaction owns the only exit from repair_pending.  Recompiling
    # after a source change first records that repair/rebuild boundary and then
    # binds the new digest-derived attempt.  Same-attempt resumes continue from
    # the last durable transition rather than appending duplicate transitions.
    if current_attempt != attempt and current == "repair_pending":
        store.transition(
            run_id=run_id,
            attempt=str(current_attempt or attempt),
            to_state="repairing",
            reason_code="repair_rebuild_started",
        )
        current = "repairing"

    progression = (
        ("source_bound", "source_snapshot_bound", (source_digest,)),
        ("compiled", "manuscript_context_compiled", (context_digest,)),
        ("assessed", "manuscript_readiness_evaluated", (readiness_digest,)),
        (target, f"authoring_{target}", (readiness_digest,)),
    )
    if current_attempt == attempt:
        completed = {"source_bound": 0, "compiled": 1, "assessed": 2}.get(current, -1)
        pending = progression[completed + 1 :]
    else:
        pending = progression
    for to_state, reason_code, digests in pending:
        store.transition(
            run_id=run_id,
            attempt=attempt,
            to_state=to_state,
            reason_code=reason_code,
            artifact_digests=digests,
        )


def compile_manuscript(
    checkpoint_dir: str | Path,
    all_nodes: Iterable[Any],
    *,
    experiment_data: dict[str, Any] | None = None,
    mode: str = "audit",
    profile_id: str = "generic_empirical_v1",
    repair_policy: str = "disabled",
    assurance_mode: str = "off",
    exploration_mode: str = "simple_bfts",
    paper_mode: str = "linear",
    brief_character_budget: int = 24_000,
    repair_budget: RepairBudgetV1 | None = None,
    authority: dict[str, Any] | None = None,
    persist: bool = True,
) -> ManuscriptOutcome:
    if mode == "off":
        return ManuscriptOutcome(mode="off", attempt_id=None, state="disabled")
    if mode not in {"audit", "enforce"}:
        raise ValueError(f"unknown manuscript mode: {mode}")
    if repair_policy not in {"disabled", "explicit", "auto"}:
        raise ValueError(f"unknown manuscript repair policy: {repair_policy}")
    if repair_policy == "auto" and mode != "enforce":
        raise ValueError("automatic manuscript repair requires enforce mode")
    checkpoint = Path(checkpoint_dir).resolve()
    profile = resolve_profile(profile_id)
    snapshot = build_exploration_snapshot(
        checkpoint,
        all_nodes,
        experiment_data=experiment_data,
        exploration_mode=exploration_mode,
    )
    context, omissions = build_manuscript_context(
        checkpoint,
        snapshot,
        profile,
        assurance_mode=assurance_mode,
    )
    readiness = evaluate_readiness(profile, context, omissions)
    attempt = attempt_id(snapshot.snapshot_digest, profile.profile_digest)
    repair_plan = None
    if readiness.authoring_verdict in {"repair_required", "blocked"}:
        repair_plan = build_repair_plan(
            readiness,
            policy=repair_policy,
            budget=repair_budget,
            authority=authority,
        )
    briefs = None
    binding = None
    if (
        readiness.authoring_verdict in {"ready", "ready_with_disclosures"}
        or mode == "audit"
    ):
        briefs = build_section_briefs(
            profile,
            context,
            readiness,
            character_budget=brief_character_budget,
        )
        binding = ManuscriptAuthoringBindingV1.create(
            run_id=snapshot.run_id,
            attempt_id=attempt,
            source_snapshot_digest=snapshot.snapshot_digest,
            profile_digest=profile.profile_digest,
            context_digest=context.context_digest,
            readiness_digest=readiness.readiness_digest,
            brief_bundle_digest=briefs.bundle_digest,
            paper_mode=("rqgm_archive" if paper_mode == "rqgm_archive" else "linear"),
            backend_version=(
                "rqgm-archive-manuscript-v1"
                if paper_mode == "rqgm_archive"
                else "linear-manuscript-v1"
            ),
            target_build_id=f"paper-{snapshot.run_id}"[:512],
            target_build_revision=0,
        )
    paths: dict[str, str] = {}
    if persist:
        store = ManuscriptStateStore(checkpoint)
        artifacts = (
            ("source_snapshot.json", snapshot),
            ("requirement_profile.json", profile),
            ("context.json", context),
            ("omission_manifest.json", omissions),
            ("readiness.json", readiness),
        )
        for filename, value in artifacts:
            path = store.write_attempt_artifact(attempt, filename, value)
            paths[filename] = path.relative_to(checkpoint).as_posix()
        if repair_plan is not None:
            path = store.write_attempt_artifact(attempt, "repair_plan.json", repair_plan)
            paths["repair_plan.json"] = path.relative_to(checkpoint).as_posix()
            if authority is not None:
                path = store.write_attempt_artifact(
                    attempt, "repair_authority.json", authority
                )
                paths["repair_authority.json"] = path.relative_to(checkpoint).as_posix()
        if briefs is not None and binding is not None:
            path = store.write_attempt_artifact(attempt, "section_briefs.json", briefs)
            paths["section_briefs.json"] = path.relative_to(checkpoint).as_posix()
            path = store.write_attempt_artifact(attempt, "authoring_binding.json", binding)
            paths["authoring_binding.json"] = path.relative_to(checkpoint).as_posix()
            text_path = store.attempt_dir(attempt) / "authoring_briefs.txt"
            text_payload = render_brief_bundle(briefs).encode("utf-8")
            if text_path.exists() and text_path.read_bytes() != text_payload:
                raise ValueError("immutable manuscript authoring brief text differs")
            if not text_path.exists():
                store._atomic_write(text_path, text_payload)
            paths["authoring_briefs.txt"] = text_path.relative_to(checkpoint).as_posix()
        _transition_attempt(
            store,
            run_id=snapshot.run_id,
            attempt=attempt,
            source_digest=snapshot.snapshot_digest,
            context_digest=context.context_digest,
            readiness_digest=readiness.readiness_digest,
            target=_target_state(readiness),
        )
    return ManuscriptOutcome(
        mode=mode,
        attempt_id=attempt,
        state=_target_state(readiness),
        profile=profile,
        context=context,
        omissions=omissions,
        readiness=readiness,
        briefs=briefs,
        authoring_binding=binding,
        repair_plan=repair_plan,
        artifact_paths=paths,
    )


__all__ = ["ManuscriptAuthoringBlocked", "ManuscriptOutcome", "compile_manuscript"]
