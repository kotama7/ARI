"""RQGM-paper-aligned P0-P4 postures, read by the paper runtime during a run.

The postures are experimental arms, not product modes.  Existing mechanism
switches still control the archive, adversary, repair engine, and kernel
enforcement.  This module owns the only missing distinction: which governed
paper roles may evolve, and validates that a preset's ordinary switches match
the declared RQGM-paper condition.

WHY THIS IS NOT IN ``ari.rqgm.evaluation``.  It lived there, and that made the
production paper path depend on the Task-13/20 evaluation harness: the ordinary
``ari paper`` run reaches ``paper_phase=True`` and imports this module at five
sites in ``runtime`` and ``paper_runtime``, none of them behind an
evaluation-only flag.  Deleting or not shipping the evaluation package would
have broken an ordinary paper run outright at ``RQGMRuntime.__init__``.

It never belonged there.  The evaluation package is the LLM-free machinery
behind ``scripts/rqgm_eval/run_ablation.py`` -- the metric computer, the
injection appliers, the doubles, the condition expansion, the smoke runner --
all of which run OVER a finished checkpoint.  This runs DURING a run, and no
module inside that package ever imported it; its only importers were the two
production runtimes.  Its input is a production config field declared in
``ari.config`` (``rqgm.eval.paper_ablation``) with a default in
``configs/defaults.yaml``, so the schema was already production and only its
interpreter was filed under evaluation.

Inert by construction rather than by placement: ``posture_from_config`` returns
``None`` unless ``rqgm.eval.enabled`` is set, and ``config_violations`` then
returns nothing.  A normal run reads the field, gets ``None``, and behaves
exactly as it did before.  The evaluation harness may import this (production is
the allowed direction to depend on); production must not import the harness.
"""

from __future__ import annotations

from dataclasses import dataclass


PAPER_ABLATION_CONDITION_IDS: tuple[str, ...] = (
    "P0_hgm_h_fixed_critic",
    "P1_rqgm_replacement_only",
    "P2_rqgm_no_erasure",
    "P3_rqgm_full",
    "P4_constitutional_rqgm",
)


@dataclass(frozen=True)
class PaperAblationPosture:
    """Mechanism membership for one RQGM-paper comparison arm."""

    condition_id: str
    writer_evolution: bool
    reviewer_replacement: bool
    adversarial_pool: bool
    selective_erasure: bool
    constitutional_layer: bool

    def role_evolution_enabled(self, role: str) -> bool:
        if str(role) == "paper_writer":
            return self.writer_evolution
        if str(role) == "paper_reviewer":
            return self.reviewer_replacement
        return True


POSTURES: dict[str, PaperAblationPosture] = {
    "P0_hgm_h_fixed_critic": PaperAblationPosture(
        "P0_hgm_h_fixed_critic", True, False, False, False, False,
    ),
    "P1_rqgm_replacement_only": PaperAblationPosture(
        "P1_rqgm_replacement_only", True, True, False, True, False,
    ),
    "P2_rqgm_no_erasure": PaperAblationPosture(
        "P2_rqgm_no_erasure", True, True, True, False, False,
    ),
    "P3_rqgm_full": PaperAblationPosture(
        "P3_rqgm_full", True, True, True, True, False,
    ),
    "P4_constitutional_rqgm": PaperAblationPosture(
        "P4_constitutional_rqgm", True, True, True, True, True,
    ),
}


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def posture_from_config(cfg) -> PaperAblationPosture | None:
    """Return the active evaluation posture, or ``None`` in normal runs."""

    rqgm = _get(cfg, "rqgm")
    eval_cfg = _get(rqgm, "eval")
    if not bool(_get(eval_cfg, "enabled", False)):
        return None
    selector = _get(eval_cfg, "paper_ablation")
    condition_id = str(_get(selector, "condition_id", "") or "")
    return POSTURES.get(condition_id)


def config_violations(cfg) -> list[str]:
    """Check that existing mechanism switches realize the declared posture.

    P0-P3 keep the fixed kernel present but use ``audit_only`` so it observes
    without blocking, which is the safe application-level approximation of
    the original RQGM conditions.  P4 uses standard enforcement.
    """

    posture = posture_from_config(cfg)
    if posture is None:
        return []
    rqgm = _get(cfg, "rqgm")
    paper = _get(rqgm, "paper")
    checks = (
        ("rqgm.paper.prompt_evolution.enabled",
         bool(_get(_get(paper, "prompt_evolution"), "enabled", True)),
         posture.writer_evolution or posture.reviewer_replacement),
        ("rqgm.paper.self_preference.enabled",
         bool(_get(_get(paper, "self_preference"), "enabled", True)),
         posture.adversarial_pool),
        ("rqgm.frontier_repair.enabled",
         bool(_get(_get(rqgm, "frontier_repair"), "enabled", True)),
         posture.selective_erasure),
        ("rqgm.kernel.enforcement",
         str(_get(_get(rqgm, "kernel"), "enforcement", "standard")),
         "standard" if posture.constitutional_layer else "audit_only"),
    )
    return [
        f"{posture.condition_id}: {path}={actual!r}, expected {expected!r}"
        for path, actual, expected in checks
        if actual != expected
    ]
