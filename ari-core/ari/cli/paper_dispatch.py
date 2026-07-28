"""The paper-phase execution-mode dispatch, shared by every CLI entry point.

`ari paper` owned this block privately, so the paper axis
(`paper.mode: linear | rqgm_archive`, docs/plans/ari_rqgm_paper Task 01) was
reachable ONLY by invoking `ari paper` on an already-finished checkpoint. The
one-pass entries — `ari run` (exploration → paper) and `ari resume` — called
``generate_paper_section`` directly and unconditionally, so a config or env that
asked for `rqgm_archive` was silently ignored there and the run produced a linear
paper with no `paper_archive_state.json` and no provenance that the request had
been dropped. Hoisting the dispatch here makes the three entries agree.

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
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

PAPER_ARCHIVE_STATE_FILENAME = "paper_archive_state.json"


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
) -> str:
    """Resolve the paper axis and run the paper phase. Returns the effective
    mode actually run (``"linear"`` or ``"rqgm_archive"``).

    ``linear_paper_fn`` is ``ari.core.generate_paper_section`` — passed in
    rather than imported so the CLI modules keep their existing lazy-lookup
    indirection (tests patch ``ari.cli.generate_paper_section``).
    """
    from ari.config import _effective_paper_mode_str, apply_paper_env_overrides

    apply_paper_env_overrides(cfg)
    state_path = Path(checkpoint_dir) / PAPER_ARCHIVE_STATE_FILENAME
    state_existed = state_path.exists()
    if state_existed:
        # Re-invocation: the persisted paper mode wins (Task 01 §5.5). Only
        # reached when the provenance file exists — never on a pure linear
        # checkpoint, so no ari.rqgm module is imported on the linear path.
        from ari.rqgm.paper_runtime import reconcile_paper_resume_mode
        reconcile_paper_resume_mode(cfg, checkpoint_dir)

    if _effective_paper_mode_str(cfg) != "rqgm_archive":
        linear_paper_fn(all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str)
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
    rt.run_archive(
        all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str,
        linear_fallback=linear_paper_fn,
    )
    log_agent_as_judge_provenance(reviewer_score_fn)
    return "rqgm_archive"
