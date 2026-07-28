"""GovernanceJudge + ReplayBoard + AnchorBoard + JuryPanel (Task 05 §5.3 step 6).

**Bounded LLM.** The boards are deterministic given cached case results
(Task 12 caching; case content is Task 06's): a board score is the mean of
the subject's cached results over at most ``rqgm.replay.max_cases_per_epoch``
cases (``max_cases_for_retirement`` when the motion puts a RetirementEvent
under consideration — Task 12 §5.4; the caller picks the cap), sorted by
case id. The GovernanceJudge (LLM) rules each motion
``upheld / partially_upheld / dismissed`` but **cannot contradict** the board
scores — a contradicting verdict is clamped and flagged for the self-audit
(the results.json-merge "deterministic evidence beats LLM opinion" doctrine).

Fallbacks (total): LLM failure/malformed → ``dismissed`` (incumbent
presumption); a board *failure* (exception while scoring) → ``inconclusive``,
motion carried to next epoch. The JuryPanel (majority over three judge
samples) is config-off in v1.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_JUDGE_OUTCOMES = ("upheld", "partially_upheld", "dismissed")

#: Board-bounding thresholds (deterministic, fixed in code like the
#: prosecution thresholds): a subject scoring ≥ HIGH on the boards cannot be
#: found against; one scoring ≤ LOW cannot be fully exonerated.
BOARD_HIGH = 0.8
BOARD_LOW = 0.2

#: Candidate pass floor over both boards (§6.1 ``candidate_evaluations``).
CANDIDATE_PASS_THRESHOLD = 0.6

_ROUND = 6


def _iter_cases(source) -> list:
    """Normalise a case source (callable / iterable / None) to a dict list,
    sorted by ``case_id`` for deterministic sampling."""
    if source is None:
        return []
    cases = source() if callable(source) else source
    out = []
    for case in cases or ():
        if isinstance(case, dict):
            out.append(case)
        else:
            d = getattr(case, "to_dict", None)
            out.append(d() if callable(d) else dict(vars(case)))
    return sorted(out, key=lambda c: str(c.get("case_id", "")))


def board_score(
    pool_cases, subject_keys: tuple, *, max_cases: int
) -> tuple[float | None, list, int]:
    """``(score | None, case_refs, cases_used)`` for one subject.

    A case contributes iff its ``results`` map carries any of the subject's
    keys (component_id / prompt_id / prompt_hash — duck-typed against
    Task 06's cached-result shape). No matching case → ``(None, [], 0)``:
    board unavailable, never fabricated.
    """
    scores = []
    refs = []
    for case in _iter_cases(pool_cases):
        if max_cases > 0 and len(scores) >= max_cases:
            break
        results = case.get("results")
        if not isinstance(results, dict):
            continue
        for key in subject_keys:
            if key and key in results:
                try:
                    scores.append(float(results[key]))
                except (TypeError, ValueError):
                    break
                refs.append(str(case.get("case_id", "")))
                break
    if not scores:
        return None, [], 0
    return round(sum(scores) / len(scores), _ROUND), refs, len(scores)


def replay_cases(pool):
    """The replay-case source off a Task 06 pool (duck-typed; None-safe)."""
    if pool is None:
        return None
    cases = getattr(pool, "cases", None)
    return cases if cases is not None else pool


def anchor_cases(pool):
    """The held-out anchor-case source (absent on most pools in v1)."""
    if pool is None:
        return None
    return getattr(pool, "anchor_cases", None)


def _parse_judge_reply(raw: str) -> tuple[str, str] | None:
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    outcome = str(data.get("outcome", "") or "")
    if outcome not in _JUDGE_OUTCOMES:
        return None
    return outcome, str(data.get("rationale", "") or "")


def _bounded_outcome(
    outcome: str, incumbent_board: float | None
) -> tuple[str, bool]:
    """Clamp a judge verdict that contradicts the deterministic boards."""
    if incumbent_board is None:
        return outcome, False
    if incumbent_board >= BOARD_HIGH and outcome != "dismissed":
        return "dismissed", True
    if incumbent_board <= BOARD_LOW and outcome == "dismissed":
        return "partially_upheld", True
    return outcome, False


def adjudicate_motion(
    *,
    motion,
    defense,
    pool,
    subject_keys: tuple,
    max_cases: int,
    jury_samples: int,
    render_judge=None,
    degradations: list,
    findings: list,
) -> dict:
    """Rule one motion; returns the §6.1 adjudication entry fields plus the
    board scores (the caller builds the ImpeachmentOutcome record)."""
    try:
        replay_score, replay_refs, replay_used = board_score(
            replay_cases(pool), subject_keys, max_cases=max_cases
        )
        anchor_score, anchor_refs, anchor_used = board_score(
            anchor_cases(pool), subject_keys, max_cases=max_cases
        )
    except Exception:
        # Board failure: inconclusive, motion carried to next epoch (§5.3).
        log.warning("board scoring failed for %s", motion.record_id,
                    exc_info=True)
        degradations.append(f"board_failure:{motion.record_id}")
        return {
            "outcome": "inconclusive",
            "rationale": "board failure; motion carried to next epoch",
            "replay_score": None, "anchor_score": None,
            "replay_refs": [], "anchor_refs": [],
            "replay_used": 0, "anchor_used": 0,
            "clamped": False,
        }
    available = [s for s in (replay_score, anchor_score) if s is not None]
    incumbent_board = (
        round(sum(available) / len(available), _ROUND) if available else None
    )
    samples = []
    rationale = ""
    for _ in range(max(1, jury_samples)):
        raw = (
            render_judge(motion, defense, replay_score, anchor_score)
            if render_judge
            else None
        )
        parsed = _parse_judge_reply(raw) if raw is not None else None
        if parsed is not None:
            samples.append(parsed[0])
            rationale = rationale or parsed[1]
    if not samples:
        degradations.append(f"judge_llm_fallback:{motion.record_id}")
        outcome = "dismissed"
        rationale = "judge unavailable; dismissed in favor of the incumbent"
    else:
        # Majority vote (JuryPanel); ties break toward the incumbent in the
        # fixed outcome order dismissed > partially_upheld > upheld.
        order = ("dismissed", "partially_upheld", "upheld")
        counts = {o: samples.count(o) for o in order}
        outcome = max(order, key=lambda o: (counts[o], -order.index(o)))
    bounded, clamped = _bounded_outcome(outcome, incumbent_board)
    if clamped:
        findings.append(
            {
                "kind": "judge_clamped_by_board",
                "motion_id": motion.record_id,
                "judge_outcome": outcome,
                "bounded_outcome": bounded,
                "incumbent_board": incumbent_board,
            }
        )
    return {
        "outcome": bounded,
        "rationale": rationale,
        "replay_score": replay_score, "anchor_score": anchor_score,
        "replay_refs": replay_refs, "anchor_refs": anchor_refs,
        "replay_used": replay_used, "anchor_used": anchor_used,
        "clamped": clamped,
    }


def _cached_board_score(
    pool_cases,
    subject_keys: tuple,
    *,
    max_cases: int,
    cache,
    prompt_hash: str,
    role: str,
) -> tuple[float | None, list, int]:
    """:func:`board_score` with the Task 12 governance cache consulted FIRST
    (plan 12 §5.5 ``use_cached_results``): each ``(case, prompt)`` pair is
    looked up under the case's origin epoch (§6.2 replay rule); pool-derived
    scores are written back so replaying the same pair never re-pays."""
    from ari.rqgm.governance_cache import case_origin_epoch, replay_lookup_key

    scores: list[float] = []
    refs: list[str] = []
    for case in _iter_cases(pool_cases):
        if max_cases > 0 and len(scores) >= max_cases:
            break
        key = replay_lookup_key(case, prompt_hash=prompt_hash, role=role)
        hit = cache.get(key)
        if hit is not None and isinstance(
            hit.get("score"), (int, float)
        ) and not isinstance(hit.get("score"), bool):
            scores.append(float(hit["score"]))
            refs.append(str(case.get("case_id", "")))
            continue
        results = case.get("results")
        if not isinstance(results, dict):
            continue
        for k in subject_keys:
            if k and k in results:
                try:
                    value = float(results[k])
                except (TypeError, ValueError):
                    break
                scores.append(value)
                refs.append(str(case.get("case_id", "")))
                cache.put(key, {
                    "role": role,
                    "epoch_id": case_origin_epoch(case),
                    "prompt_hash": prompt_hash,
                    "result_ref": str(case.get("case_id", "")),
                    "score": value,
                })
                break
    if not scores:
        return None, [], 0
    return round(sum(scores) / len(scores), _ROUND), refs, len(scores)


def evaluate_candidates(
    *,
    candidate_prompts,
    pool,
    max_cases: int,
    use_cached: bool,
    cache=None,
) -> tuple[list, int, int]:
    """§6.1 ``candidate_evaluations``: deterministic board scoring of the
    Task 07/08 candidate PromptSpecs (this facade never creates candidates).
    *cache* is the optional Task 12 :class:`GovernanceCache`; with
    ``use_cached`` it is consulted before the pool's stored case results
    (plan 12 §5.5) and filled from them. Returns
    ``(evaluations, replay_cases_used, anchor_cases_used)``."""
    evaluations = []
    replay_used_total = 0
    anchor_used_total = 0
    normalized = []
    for cand in candidate_prompts or ():
        c = cand if isinstance(cand, dict) else {
            "prompt_id": getattr(cand, "prompt_id", ""),
            "role": getattr(cand, "role", ""),
            "prompt_hash": getattr(cand, "prompt_hash", None),
        }
        normalized.append(c)
    for c in sorted(normalized, key=lambda c: str(c.get("prompt_id", ""))):
        keys = tuple(
            k for k in (c.get("prompt_id"), c.get("prompt_hash")) if k
        )
        prompt_hash = str(c.get("prompt_hash") or "")
        if use_cached and cache is not None and prompt_hash:
            replay_score, replay_refs, r_used = _cached_board_score(
                replay_cases(pool), keys, max_cases=max_cases,
                cache=cache, prompt_hash=prompt_hash,
                role=str(c.get("role", "")),
            )
        else:
            replay_score, replay_refs, r_used = board_score(
                replay_cases(pool), keys, max_cases=max_cases
            )
        anchor_score, _, a_used = board_score(
            anchor_cases(pool), keys, max_cases=max_cases
        )
        replay_used_total += r_used
        anchor_used_total += a_used
        if replay_score is None and anchor_score is None:
            verdict = "inconclusive"
        else:
            available = [
                s for s in (replay_score, anchor_score) if s is not None
            ]
            verdict = (
                "pass"
                if min(available) >= CANDIDATE_PASS_THRESHOLD
                else "fail"
            )
        evaluations.append(
            {
                "prompt_id": str(c.get("prompt_id", "")),
                "role": str(c.get("role", "")),
                "replay_score": replay_score,
                "anchor_score": anchor_score,
                "verdict": verdict,
                "case_refs": replay_refs,
                "cached": bool(use_cached),
            }
        )
    return evaluations, replay_used_total, anchor_used_total
