"""Deterministic self-preference statistic for the paper reviewer
(paper-archive Task 05; docs/reference/rqgm_schemas.md, the
``rqgm/paper_self_preference_stat.json`` section).

The ``paper_self_preference`` adversary attacks a reviewer DECISION the
artifact reveals: an AI-authored draft the incumbent ``paper_reviewer``
accepted that the human ground-truth anchor would reject. The anchor supplies
the pre-signal — WHICH over-accepted drafts to attack — and this module owns
its two deterministic, LLM-free pieces:

* :func:`over_accepted_cases` — the anchor cases the frozen incumbent reviewer
  ACCEPTED although their ground truth is ``reject`` (the direct
  over-acceptance signal the anchor supplies);
* :func:`compute_self_preference_margin` — the population statistic (mean
  reviewer acceptance on AI-labeled papers minus mean on human-labeled ones)
  over a deterministic held-out sample, written by value to the audit artifact
  ``{ckpt}/rqgm/paper_self_preference_stat.json`` (the ``attack_evidence_ref``
  the pre-signal cites). ``0.0`` when the corpus carries no AI/human split.

Pure stdlib + ``ari.rqgm`` types: no LLM calls, no network, no randomness
(P2). ``created_at`` is metadata only and never enters any hash.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ari.rqgm.paper_anchor import _case_target_label, binarize_recommendation

log = logging.getLogger(__name__)

PAPER_SELF_PREFERENCE_STAT_FILENAME = "paper_self_preference_stat.json"
#: The snapshot dir the pre-signal's evidence ref points into (pool.py:46).
RQGM_SNAPSHOT_DIRNAME = "rqgm"


def _reviewer_accepts(reviewer, case: dict) -> bool:
    """``True`` iff the reviewer's ``accept_recommendation`` on *case*
    binarises to ``accept`` (deterministic; the frozen incumbent's verdict).

    NO verdict (``None`` — no verdict source wired, or the call failed) is NOT
    an over-acceptance: ``False``. The old ``except: rec = "accept"`` forged one,
    which here means inventing the over-accepted draft the whole adversarial
    round attacks — an attack on a decision the reviewer never made."""
    try:
        rec = reviewer.anchor_verdict(case)
    except Exception:  # never raise into the paper phase (§7 contract)
        rec = None
    if rec is None:
        return False
    return binarize_recommendation(str(rec)) == "accept"


def over_accepted_cases(reviewer, cases) -> list[dict]:
    """The held-out anchor cases the reviewer ACCEPTED though their ground
    truth is ``reject`` — the direct over-acceptance signal (§5.1). Sorted by
    ``case_id`` (deterministic, no wall clock)."""
    out = []
    for case in sorted(cases or (), key=lambda c: str(c.get("case_id", ""))):
        if str(_case_target_label(case)) != "reject":
            continue
        if _reviewer_accepts(reviewer, case):
            out.append(case)
    return out


def _held_out_sample(cases, sample_size: int) -> list[dict]:
    ranked = sorted(cases or (), key=lambda c: str(c.get("case_id", "")))
    return ranked[: max(0, int(sample_size))] if sample_size else list(ranked)


def compute_self_preference_margin(
    reviewer,
    cases,
    *,
    sample_size: int = 8,
    epoch_id: str = "",
    checkpoint_dir=None,
) -> float:
    """The deterministic AI-vs-human self-preference margin (§5.3).

    ``mean(reviewer accepts | authorship == ai) - mean(reviewer accepts |
    authorship == human)`` over the held-out sample; ``0.0`` when either half
    is empty (the corpus-absent / AI-only degradation — never an error).
    Writes the byte-fixed statistic artifact when *checkpoint_dir* is given.
    Pure over the frozen incumbent's verdicts (P2)."""
    sample = _held_out_sample(cases, sample_size)
    per_case: dict[str, float] = {}
    ai: list[float] = []
    human: list[float] = []
    for case in sample:
        cid = str(case.get("case_id", ""))
        accept = 1.0 if _reviewer_accepts(reviewer, case) else 0.0
        per_case[cid] = accept
        authorship = str(case.get("authorship", ""))
        if authorship == "ai":
            ai.append(accept)
        elif authorship == "human":
            human.append(accept)
    if ai and human:
        margin = round(sum(ai) / len(ai) - sum(human) / len(human), 6)
    else:
        margin = 0.0
    if checkpoint_dir is not None:
        _write_stat(
            checkpoint_dir,
            epoch_id=epoch_id,
            sample_ids=[str(c.get("case_id", "")) for c in sample],
            per_case_scores=per_case,
            ai_mean=round(sum(ai) / len(ai), 6) if ai else None,
            human_mean=round(sum(human) / len(human), 6) if human else None,
            margin=margin,
        )
    return margin


def _write_stat(
    checkpoint_dir,
    *,
    epoch_id: str,
    sample_ids: list[str],
    per_case_scores: dict,
    ai_mean,
    human_mean,
    margin: float,
) -> None:
    """Best-effort byte-fixed write of the statistic artifact (never raises
    into the run — the ``adversarial_replay_pool.json`` snapshot precedent)."""
    try:
        snap = Path(checkpoint_dir) / RQGM_SNAPSHOT_DIRNAME
        snap.mkdir(parents=True, exist_ok=True)
        payload = {
            "record_type": "paper_self_preference_stat",
            "schema_version": 1,
            "epoch_id": str(epoch_id),
            "sample_ids": sorted(str(s) for s in sample_ids),
            "per_case_scores": {
                str(k): float(v) for k, v in sorted(per_case_scores.items())
            },
            "ai_mean": ai_mean,
            "human_mean": human_mean,
            "margin": float(margin),
        }
        (snap / PAPER_SELF_PREFERENCE_STAT_FILENAME).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.warning("paper self-preference stat write failed (best-effort)",
                    exc_info=True)
