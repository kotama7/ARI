"""The paper-phase execution-mode dispatch, shared by every CLI entry point.

`ari paper` owned this block privately, so the paper axis
(`paper.mode: linear | rqgm_archive`, docs/plans/ari_rqgm_paper Task 01) was
reachable ONLY by invoking `ari paper` on an already-finished checkpoint. The
one-pass entries — `ari run` (exploration → paper) and `ari resume` — called
``generate_paper_section`` directly and unconditionally, so a config or env that
asked for `rqgm_archive` was silently ignored there and the run produced a linear
paper with no `paper_archive_state.json` and no provenance that the request had
been dropped. Hoisting the dispatch here makes the three entries agree.

The RQGM **paper-candidate pre-flight** (penalty replay → escalate-to-fixpoint →
re-ideation) is hoisted here for the same reason: it, too, lived privately in
`ari paper`, so a one-pass `ari run` never ran the paper-candidate adversarial
round, and exploration's own per-node rounds do not cover it — the paper
artifacts that round attacks (claim-gate findings, `verified_context.json`,
related refs) are written by the paper stages, so before them the pre-signals are
empty and the paper-claim adversaries sit on their no-attack floor.

That same fact bounds WHEN the round is worth running, because its §5.3 marker is
one-shot per node and epoch-agnostic: fired against an empty bundle it is spent
forever, permanently suppressing the artifact-grounded round a later invocation
could run. So the pre-flight is gated on the evidence existing — it runs before
the pipeline when a previous pass produced those artifacts (where a demotion can
still re-crown this paper's own seed), and otherwise once more after the pipeline
has written them, where the penalty reaches selection on the next invocation
through `replay_utility_penalties`. The three entries agree here as well.

**Identity-default guarantee preserved.** The default `linear` path still imports
no `ari.rqgm` module: :func:`ari.config.apply_paper_env_overrides` is
import-free, the resume reconcile is gated on the state file's existence (absent
on every linear checkpoint), ``_effective_paper_mode_str`` mirrors
``resolve_paper_mode`` without importing ``ari.rqgm``, and
``PaperArchiveRuntime`` is imported lazily only when both flags agree.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

PAPER_ARCHIVE_STATE_FILENAME = "paper_archive_state.json"

_MANUSCRIPT_RUNTIME_ENV = (
    "ARI_MANUSCRIPT_RUNTIME_MODE",
    "ARI_MANUSCRIPT_PROFILE",
    "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE",
    "ARI_MANUSCRIPT_BRIEF_CHARACTER_BUDGET",
    "ARI_MANUSCRIPT_MAX_ROUNDS",
    "ARI_MANUSCRIPT_MAX_NEW_NODES",
    "ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS",
    "ARI_MANUSCRIPT_MAX_LLM_CALLS",
    "ARI_MANUSCRIPT_ASSURANCE_MODE",
    "ARI_MANUSCRIPT_KNOWLEDGE_MODE",
    "ARI_MANUSCRIPT_CAPABILITY_MODE",
    "ARI_MANUSCRIPT_EXPLORATION_MODE",
    "ARI_MANUSCRIPT_PAPER_MODE",
    "ARI_MANUSCRIPT_CONTEXT_PATH",
    "ARI_MANUSCRIPT_PROFILE_PATH",
    "ARI_MANUSCRIPT_READINESS_PATH",
    "ARI_MANUSCRIPT_BRIEFS_PATH",
    "ARI_MANUSCRIPT_BINDING_PATH",
)


@contextmanager
def _manuscript_runtime_environment(cfg, *, paper_mode: str):
    """Expose the resolved opt-in posture to the fixed pipeline boundary.

    The default/off branch yields without touching the process environment or
    importing ``ari.manuscript``.
    """

    from ari.config import _effective_manuscript_mode_str

    mode = _effective_manuscript_mode_str(cfg)
    repair_policy = getattr(getattr(cfg.manuscript, "repair", None), "policy", "disabled")
    if repair_policy == "auto" and mode != "enforce":
        raise ValueError("manuscript repair.policy=auto requires manuscript.mode=enforce")
    if mode == "off":
        yield
        return
    old = {key: os.environ.get(key) for key in _MANUSCRIPT_RUNTIME_ENV}
    manuscript = cfg.manuscript
    repair = manuscript.repair
    values = {
        "ARI_MANUSCRIPT_RUNTIME_MODE": mode,
        "ARI_MANUSCRIPT_PROFILE": manuscript.profile,
        "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE": repair.policy,
        "ARI_MANUSCRIPT_BRIEF_CHARACTER_BUDGET": str(manuscript.brief_character_budget),
        "ARI_MANUSCRIPT_MAX_ROUNDS": str(repair.max_rounds),
        "ARI_MANUSCRIPT_MAX_NEW_NODES": str(repair.max_new_nodes),
        "ARI_MANUSCRIPT_MAX_EXPERIMENT_RUNS": str(repair.max_experiment_runs),
        "ARI_MANUSCRIPT_MAX_LLM_CALLS": str(repair.max_llm_calls),
        "ARI_MANUSCRIPT_ASSURANCE_MODE": getattr(cfg.assurance, "mode", "off"),
        "ARI_MANUSCRIPT_KNOWLEDGE_MODE": getattr(cfg.knowledge, "mode", "off"),
        "ARI_MANUSCRIPT_CAPABILITY_MODE": getattr(cfg.capability_binding, "mode", "legacy"),
        "ARI_MANUSCRIPT_EXPLORATION_MODE": getattr(cfg.ari, "mode", "simple_bfts"),
        "ARI_MANUSCRIPT_PAPER_MODE": paper_mode,
    }
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_agent_as_judge(cfg, paper_llm, experiment_data, checkpoint_dir):
    """The opt-in agent-as-judge ``reviewer_score_fn`` (paper-archive Task 03
    §5.8 Residual), or ``None`` for the deterministic path.

    OFF => the deterministic venue rubric (P2) keeps the draft path LLM-free.
    ON => a real-``LLMClient``-backed scorer that reads the axes no
    deterministic reader can (novelty/significance) and breaks the 1.0
    discrimination ceiling.

    ``checkpoint_dir`` is what lets the judge resolve the Layer-0 evidence
    channels: the CLI's ``experiment_data`` is a ``{goal, topic, file}`` dict
    carrying none of them, and the runtime's own dict stores them as PATHS (the
    paper skill resolves those server-side; the judge renders in-process).
    Fail-open: a wiring failure degrades to the rubric, loudly."""
    aj = cfg.rqgm.paper.reviewer.agent_as_judge
    if not aj.enabled:
        return None
    if paper_llm is None:
        log.warning("agent-as-judge is enabled but no LLM client is available "
                    "on this entry point; using the deterministic rubric")
        return None
    try:
        from ari.rqgm.paper_judge import build_agent_as_judge_score_fn

        fn = build_agent_as_judge_score_fn(
            paper_llm,
            experiment_data=experiment_data,
            checkpoint_dir=checkpoint_dir,
            max_tokens=getattr(aj, "max_tokens", None),
        )
        log.info("paper archive: agent-as-judge reviewer scoring ENABLED "
                 "(real LLM on the draft path)")
        return fn
    except Exception as exc:                       # noqa: BLE001 — never block
        log.warning("agent-as-judge wiring failed (%s); "
                    "using the deterministic rubric", exc)
        return None


def log_agent_as_judge_provenance(score_fn) -> None:
    """Durable provenance in ``ari.log``: a judge score and a fallback rubric
    score are the same float to every consumer, so a run whose LLM was down for
    EVERY call would otherwise be indistinguishable from a fully judged one."""
    if score_fn is None:
        return
    judged = getattr(score_fn, "judged", None)
    if judged is None:
        return
    log.info(
        "agent-as-judge provenance: %s draft score(s) judged by the LLM, "
        "%s degraded to the deterministic rubric",
        judged, getattr(score_fn, "degraded", None),
    )
    if judged == 0:
        log.warning(
            "agent-as-judge was ENABLED but scored NOTHING — every draft score "
            "came from the deterministic rubric; the run is not agent-judged",
        )


def _escalate_paper_candidate_to_fixpoint(rqgm, all_nodes):
    """Select → escalate → re-select until the winner is stable.

    A judge-validated attack in the escalation round applies the bounded
    utility penalty (plan 06 §5.4), rewriting the candidate's
    ``_scientific_score`` in place — so the post-round re-selection can
    crown a different node. Looping guarantees the node the paper is
    actually about never escapes its L3 paper-candidate round. Terminates:
    each node is escalated at most once per pass (local set; the §5.3
    round marker additionally makes repeat rounds no-ops across runs).
    Returns the final (stable) winner, or ``None`` when every candidate
    is erased.
    """
    from ari.pipeline.verified_context import select_best_node

    best = select_best_node(all_nodes)
    escalated: set[str] = set()
    while best is not None:
        cand_id = str(getattr(best, "id", "") or "")
        if cand_id in escalated:
            break
        escalated.add(cand_id)
        rqgm.run_paper_candidate_escalation(best, all_nodes=all_nodes)
        best = select_best_node(all_nodes)
    return best


#: The paper pre-signal artifacts ``build_artifact_bundle`` reads (plan 06
#: §5.2). The §5.3 round marker is ONE-SHOT per node and epoch-agnostic, so a
#: round fired before any of these exist spends it on an empty bundle — only
#: the node-text `overclaim` fallback can fire — and permanently suppresses the
#: artifact-grounded round (prior_art / evidence_gap / metric_gaming) that a
#: later invocation could run. Hence the gate.
_PAPER_PRESIGNAL_ARTIFACTS = (
    "verified_context.json",
    "related_refs.json",
    "evaluation/claim_evidence_hard_gate_final.json",
    "evaluation/claim_evidence_hard_gate_draft.json",
)


def paper_presignal_artifacts_present(checkpoint_dir) -> bool:
    """True when at least one paper pre-signal artifact exists on disk."""
    try:
        ckpt = Path(checkpoint_dir)
        return any((ckpt / rel).is_file() for rel in _PAPER_PRESIGNAL_ARTIFACTS)
    except Exception:  # pragma: no cover - defensive
        return False


def run_paper_candidate_preflight(rqgm, all_nodes, experiment_data,
                                  checkpoint_dir, *,
                                  post_pipeline: bool = False) -> bool:
    """RQGM paper-candidate pre-flight (plan 03 trigger table / 06 §5.5 /
    12 §5.2), shared by every CLI entry.

    Escalates the best node (the verified_context ranking) through the
    EXISTING per-node RQGM machinery — one paper-candidate adversarial round
    + L3 governance, with the validated attacks flowing to the
    AdversarialReplayPool. The round is NOT merely observational: a
    judge-validated attack applies the bounded utility penalty (plan 06
    §5.4), rewriting ``_scientific_score`` in place, so the downstream
    seed / verified-context re-selection can crown a DIFFERENT node. Two
    consequences handled here:

    1. persisted penalties are replayed onto the loaded nodes first
       (``replay_utility_penalties``) — a separate ``ari paper`` process
       never writes ``tree.json``, so without replay a re-run reverts the
       ranking while the §5.3 round marker suppresses a second round (P2);
    2. selection→escalation runs to a FIXPOINT, so a node crowned by a
       demotion still gets its own L3 round.

    **Gated on the paper evidence existing** (:data:`_PAPER_PRESIGNAL_ARTIFACTS`):
    the round's whole point is to attack the paper's real artifacts, and its
    marker is one-shot per node, so on a checkpoint that has not produced a
    paper yet the pre-flight defers rather than spending the marker on an
    empty bundle. ``run_paper_phase`` then re-invokes it with
    ``post_pipeline=True`` once the pipeline HAS produced those artifacts, so
    the round still runs — its penalty lands durably in the case log and
    reaches selection on the next invocation through
    ``replay_utility_penalties``. Before-the-pipeline is what lets a demotion
    re-crown the paper's own seed; after is the best available on a first
    pass, where no evidence existed to judge beforehand.

    Duck-typed on *rqgm* (present only under ``ari_rqgm``); a non-RQGM run
    never reaches this function. Fail-open: any failure logs and never
    blocks the paper pipeline. Returns ``True`` when the escalation ran.
    """
    if rqgm is None:
        return False
    if not paper_presignal_artifacts_present(checkpoint_dir):
        log.info(
            "paper-candidate pre-flight deferred%s: none of %s exists yet, "
            "and the round marker is one-shot per node — spending it on an "
            "empty bundle would permanently suppress the artifact-grounded "
            "round",
            " again" if post_pipeline else "",
            "/".join(_PAPER_PRESIGNAL_ARTIFACTS),
        )
        return False
    if post_pipeline:
        log.info(
            "running the paper-candidate round AFTER the paper pipeline: the "
            "artifacts it attacks did not exist at pre-flight time, so any "
            "penalty reaches selection on the next invocation (replay), not "
            "this one",
        )
    try:
        replay = getattr(rqgm, "replay_utility_penalties", None)
        if callable(replay):
            replay(all_nodes)
        best = _escalate_paper_candidate_to_fixpoint(rqgm, all_nodes)
        if best is not None:
            # RQGM re-ideation (plan 03 §5.2): `paper_candidate` is the
            # fourth declared trigger event and the plan names paper
            # pre-flight as its hook — keyed to the FINAL winner (the node
            # the paper is actually about).
            reideate = getattr(rqgm, "reideate", None)
            if callable(reideate):
                reideate("paper_candidate", {
                    "goal": (experiment_data or {}).get("goal", ""),
                    "checkpoint_dir": str(checkpoint_dir),
                    "node_id": getattr(best, "id", ""),
                })
        return True
    except Exception as exc:
        log.warning("rqgm paper-candidate escalation failed: %s", exc)
        return False


def run_paper_phase(
    cfg,
    all_nodes,
    experiment_data: dict,
    checkpoint_dir,
    mcp,
    cfg_str: str,
    *,
    linear_paper_fn: Callable,
    paper_llm=None,
    rqgm=None,
    repair_executors: dict[str, Callable] | None = None,
) -> str:
    """Resolve the paper axis and run the paper phase. Returns the effective
    mode actually run (``"linear"`` or ``"rqgm_archive"``).

    ``linear_paper_fn`` is ``ari.core.generate_paper_section`` — passed in
    rather than imported so the CLI modules keep their existing lazy-lookup
    indirection (tests patch ``ari.cli.generate_paper_section``).

    ``rqgm`` is the exploration ``RQGMRuntime`` (``getattr(bfts, "rqgm",
    None)``) — present only under ``ari.mode: ari_rqgm``, and passed rather
    than discovered so this module keeps its no-``ari.rqgm``-import
    discipline. When present, the paper-candidate pre-flight runs BEFORE the
    mode branch, so it fires on the exploration axis independently of
    ``paper.mode`` (the 2x2 orthogonality the paper plans pin) — and, when
    the paper evidence does not exist yet, once more AFTER the pipeline
    produced it (see :func:`run_paper_candidate_preflight`).
    """
    from ari.config import (
        _effective_paper_mode_str,
        apply_manuscript_env_overrides,
        apply_paper_env_overrides,
    )

    escalated = run_paper_candidate_preflight(
        rqgm, all_nodes, experiment_data, checkpoint_dir)
    apply_paper_env_overrides(cfg)
    apply_manuscript_env_overrides(cfg)
    state_path = Path(checkpoint_dir) / PAPER_ARCHIVE_STATE_FILENAME
    state_existed = state_path.exists()
    if state_existed:
        # Re-invocation: the persisted paper mode wins (Task 01 §5.5). Only
        # reached when the provenance file exists — never on a pure linear
        # checkpoint, so no ari.rqgm module is imported on the linear path.
        from ari.rqgm.paper_runtime import reconcile_paper_resume_mode
        reconcile_paper_resume_mode(cfg, checkpoint_dir)

    if _effective_paper_mode_str(cfg) != "rqgm_archive":
        with _manuscript_runtime_environment(cfg, paper_mode="linear"):
            manuscript_mode = os.environ.get(
                "ARI_MANUSCRIPT_RUNTIME_MODE", "off"
            ).strip().lower()
            if manuscript_mode == "off":
                linear_paper_fn(
                    all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str
                )
            else:
                linear_paper_fn(
                    all_nodes,
                    experiment_data,
                    checkpoint_dir,
                    mcp,
                    cfg_str,
                    include_segments=frozenset({"evidence"}),
                )
                from ari.manuscript.runtime import prepare_runtime_manuscript

                outcome = prepare_runtime_manuscript(
                    checkpoint_dir,
                    all_nodes,
                    experiment_data=experiment_data,
                    block_on_unready=False,
                )
                assert outcome is not None
                if (
                    manuscript_mode == "enforce"
                    and not outcome.authoring_ready
                    and os.environ.get(
                        "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE", "disabled"
                    ) == "auto"
                    and repair_executors is not None
                ):
                    from ari.manuscript.runtime import run_runtime_auto_repair

                    repaired = run_runtime_auto_repair(
                        checkpoint_dir,
                        all_nodes,
                        experiment_data=experiment_data,
                        evidence_rebuilder=lambda: linear_paper_fn(
                            all_nodes,
                            experiment_data,
                            checkpoint_dir,
                            mcp,
                            cfg_str,
                            include_segments=frozenset({"evidence"}),
                        ),
                        executors=repair_executors,
                    )
                    outcome = repaired.outcome
                if manuscript_mode == "enforce" and not outcome.authoring_ready:
                    from ari.manuscript.coordinator import ManuscriptAuthoringBlocked

                    raise ManuscriptAuthoringBlocked(outcome)
                linear_paper_fn(
                    all_nodes,
                    experiment_data,
                    checkpoint_dir,
                    mcp,
                    cfg_str,
                    include_segments=frozenset({"authoring"}),
                )
                linear_paper_fn(
                    all_nodes,
                    experiment_data,
                    checkpoint_dir,
                    mcp,
                    cfg_str,
                    include_segments=frozenset({"verification"}),
                )
        if not escalated:
            run_paper_candidate_preflight(
                rqgm, all_nodes, experiment_data, checkpoint_dir,
                post_pipeline=True)
        return "linear"

    mode_source = (
        "resume" if state_existed else
        ("env" if (os.environ.get("ARI_PAPER_MODE")
                   or os.environ.get("ARI_RQGM_PAPER_ENABLED"))
         else "config")
    )
    from ari.pipeline.verified_context import select_best_node
    from ari.rqgm.paper_runtime import PaperArchiveRuntime  # lazy: archive only

    seed = select_best_node(all_nodes)
    reviewer_score_fn = build_agent_as_judge(
        cfg, paper_llm, experiment_data, checkpoint_dir,
    )
    # `llm` and `adversary_llm` are what make the paper phase's GOVERNANCE real:
    # `llm` feeds the inner RQGMRuntime (paper_runtime.py:1291) and therefore the
    # PromptMutator that co-evolves the governed paper_writer / paper_reviewer
    # bytes; `adversary_llm` (falling back to `llm`, paper_runtime.py:1604-1605)
    # feeds the paper_self_preference AdversarialRound. Production omitted BOTH,
    # so `AdversaryEngine.attack` sat on its no-LLM floor and emitted zero
    # attacks, and no candidate prompt was ever minted — while
    # `rqgm.paper.self_preference.enabled` and
    # `rqgm.paper.prompt_evolution.enabled` both default to TRUE, i.e. the config
    # promised behaviour that could not happen. Passing the paper-phase client
    # here is what makes those defaults honest.
    rt = PaperArchiveRuntime(
        cfg, checkpoint_dir=checkpoint_dir, mcp=mcp,
        reviewer_score_fn=reviewer_score_fn,
        llm=paper_llm, adversary_llm=paper_llm,
    )
    rt.persist_mode(
        checkpoint_dir,
        mode_source=mode_source,
        exploration_mode=getattr(getattr(cfg, "ari", None), "mode", ""),
        seed_node_id=getattr(seed, "id", None),
    )
    # Tasks 02-07 own the archive loop, best-belief selection, and the compile +
    # claim-gate handoff. The archive builds the winning full_paper.tex, then
    # delegates to the SAME linear pipeline for the claim-gate tail.
    with _manuscript_runtime_environment(cfg, paper_mode="rqgm_archive"):
        fallback = linear_paper_fn
        manuscript_mode = os.environ.get(
            "ARI_MANUSCRIPT_RUNTIME_MODE", "off"
        ).strip().lower()
        if manuscript_mode != "off":
            # Archive authoring used to run before transform/EAR/figure stages.
            # Run the additive evidence segment first, compile the common ready
            # bundle, and only then allow the archive's first model call.
            linear_paper_fn(
                all_nodes,
                experiment_data,
                checkpoint_dir,
                mcp,
                cfg_str,
                include_segments=frozenset({"evidence"}),
            )
            from ari.manuscript.runtime import prepare_runtime_manuscript

            outcome = prepare_runtime_manuscript(
                checkpoint_dir,
                all_nodes,
                experiment_data=experiment_data,
                block_on_unready=False,
            )
            assert outcome is not None
            if (
                manuscript_mode == "enforce"
                and not outcome.authoring_ready
                and os.environ.get(
                    "ARI_MANUSCRIPT_REPAIR_POLICY_EFFECTIVE", "disabled"
                ) == "auto"
                and repair_executors is not None
            ):
                from ari.manuscript.runtime import run_runtime_auto_repair

                repaired = run_runtime_auto_repair(
                    checkpoint_dir,
                    all_nodes,
                    experiment_data=experiment_data,
                    evidence_rebuilder=lambda: linear_paper_fn(
                        all_nodes,
                        experiment_data,
                        checkpoint_dir,
                        mcp,
                        cfg_str,
                        include_segments=frozenset({"evidence"}),
                    ),
                    executors=repair_executors,
                )
                outcome = repaired.outcome
            if manuscript_mode == "enforce" and not outcome.authoring_ready:
                from ari.manuscript.coordinator import ManuscriptAuthoringBlocked

                raise ManuscriptAuthoringBlocked(outcome)
            from ari.manuscript.runtime import transition_runtime_manuscript

            transition_runtime_manuscript(
                checkpoint_dir,
                "authoring",
                reason_code=(
                    "archive_authoring_started"
                    if manuscript_mode == "enforce"
                    else "audit_archive_authoring_started"
                ),
            )

            def _segmented_fallback(
                nodes,
                data,
                ckpt,
                fallback_mcp,
                fallback_cfg,
                *,
                disable_stages=frozenset(),
            ):
                # A materialised archive winner needs only the common fixed
                # verification tail.  If archive generation failed, the bound
                # linear authoring backend consumes the same ready bundle first.
                if disable_stages:
                    transition_runtime_manuscript(
                        ckpt,
                        "authored",
                        reason_code="archive_winner_authored",
                    )
                    return linear_paper_fn(
                        nodes,
                        data,
                        ckpt,
                        fallback_mcp,
                        fallback_cfg,
                        disable_stages=disable_stages,
                        include_segments=frozenset({"verification"}),
                    )
                linear_paper_fn(
                    nodes,
                    data,
                    ckpt,
                    fallback_mcp,
                    fallback_cfg,
                    include_segments=frozenset({"authoring"}),
                )
                return linear_paper_fn(
                    nodes,
                    data,
                    ckpt,
                    fallback_mcp,
                    fallback_cfg,
                    include_segments=frozenset({"verification"}),
                )

            fallback = _segmented_fallback
        rt.run_archive(
            all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str,
            linear_fallback=fallback,
        )
    log_agent_as_judge_provenance(reviewer_score_fn)
    if not escalated:
        run_paper_candidate_preflight(
            rqgm, all_nodes, experiment_data, checkpoint_dir,
            post_pipeline=True)
    return "rqgm_archive"
