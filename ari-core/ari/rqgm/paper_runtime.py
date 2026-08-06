"""Paper-archive runtime facade + mode provenance (paper-archive Task 01/02,
docs/plans/ari_rqgm_paper/01, /02 §5.3).

:class:`PaperArchiveRuntime` is the single funnel for all paper-archive
construction, the paper-phase analog of :class:`ari.rqgm.runtime.RQGMRuntime`.
It is imported LAZILY inside the ``rqgm_archive`` branch of the paper entry —
under ``linear`` no ``ari.rqgm`` module is imported on the paper path
(identity-default guarantee, Task 01 §5.3/§8.1).

Scope: the whole paper-archive plan set (Tasks 01-07) lands in this module.
``run_archive`` seeds ``width`` drafts, expands the tree to depth > 1 via
``paper_refine`` child nodes, best-belief selects a winner, and lazily compiles
it (02). On top of that substrate sit the governed ``paper_writer`` /
``paper_reviewer`` roles whose PROMPT BYTES RQGM evolves (03), the anchor
utility and epoch-winner selection (04), the ``paper_self_preference``
adversary (05), the per-epoch cost caps (06), and the claim-gate handoff (07).

The reviewer is still an injectable seam, but the injected default is no longer
the whole story: :class:`_DefaultPaperReviewer` (deterministic, LLM-free) is the
PRE-GOVERNANCE substrate used when no governed prompt is active, while the
governed reviewer below renders the epoch's ACTIVE ``paper_reviewer`` prompt and
is what makes the reviewer half of co-evolution live. The best-belief ``.tex``
is handed to the EXISTING linear compile + claim-gate tail unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable

from ari.pipeline.verified_context import select_best_node
from ari.rqgm.paper_archive import (
    PAPER_DRAFT_ARCHIVE_FILENAME,
    PaperArchiveStrategy,
    archive_node_budget,
    erase_paper_reviewer_utilities,
    mark_paper_draft_flags,
    record_paper_draft_manuscript_evaluation,
    read_paper_draft_archive,
    restore_archive_round,
)
from ari.rqgm.paper_draft_executor import PaperDraftExecutor
from ari.rqgm.paper_mode import PaperMode, resolve_paper_mode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import ARIConfig
    from ari.orchestrator.node import Node

log = logging.getLogger(__name__)

PAPER_ARCHIVE_STATE_FILENAME = "paper_archive_state.json"
PAPER_ARCHIVE_STATE_SCHEMA_VERSION = 1

# mode_source vocabulary (Task 01 §6.2): how the persisted paper mode was decided.
PAPER_MODE_SOURCES = ("config", "env", "resume")

#: Workflow stages the ARCHIVE owns, disabled in the Task 07 handoff config so
#: the linear tail runs on the winner instead of regenerating over it
#: (07 §5.1 "the archive substitutes for `write_paper` + `paper_refine`";
#: §4 "those two are the archive's job in `rqgm_archive` mode";
#: R5 "`materialize_winner` is the single writer").
#:
#: `write_paper` is NOT listed: it already no-ops via its own
#: `skip_if_exists: {ckpt}/full_paper.tex` guard, which §5.4 explicitly relies on
#: ("the `skip_if_exists` stage guards behave identically"). Disabling it too
#: would be redundant and would break the §8.3 fail-open, where a winner-less
#: archive MUST let `write_paper` run.
#:
#: `review_paper` / `merge_reviews` are NOT listed either, though 02 R3 also
#: names the review stages ("skips the linear write/review/refine stages"). Its
#: cost half is deliberately left open and recorded as a residual: disabling
#: `review_paper` would delete `review_report.json`, which has real consumers
#: OUTSIDE the pipeline (`cli/projects.py:323,413`, `viz/checkpoint_api.py:177,270`,
#: `viz/services/state_service.py:77` `has_review`). Removing it would violate 07
#: §5.1's stronger, same-plan guarantee that "everything downstream is
#: byte-identical". Closing R3's cost half needs those consumers handled first —
#: see the 2026-07-17 residual in 07 §12. This set is exactly what §5.4/R5's
#: single-writer invariant requires and nothing more.
HANDOFF_DISABLED_STAGES = frozenset({"paper_refine"})


class ManuscriptArchiveAuthoringError(RuntimeError):
    """The archive could not produce an admissible, manuscript-bound draft."""


# ─────────────────────────────────────────────────────────────────────────────
# Cost model — the per-epoch draft-population bound (paper-archive Task 06 §5.4.1
# / §7). Pure; depth-independent (§5.6): raising `archive.depth` moves no term.
# ─────────────────────────────────────────────────────────────────────────────


def paper_expansion_budget(cfg) -> int:
    """The §5.4.1 per-epoch draft-population bound:
    ``min(width * (1 + refine_rounds), max_expansions)``.

    This is the SAME value ``PaperArchiveStrategy`` caps on (its
    ``node_budget``): it delegates to :func:`ari.rqgm.paper_archive.archive_node_budget`,
    the single source of truth, so the cost model and the live strategy cap can
    never diverge. The tree is capped by the node budget at ANY depth, because
    ``should_prune`` retires a frontier node the moment
    ``current_total >= max_total_nodes`` (bfts.py:501-502) BEFORE the depth
    test — independent of ``archive.depth`` (no ``width^depth`` term). Pure and
    duck-typed (a raw dict or a typed model both work)."""
    arch = getattr(getattr(getattr(cfg, "rqgm", None), "paper", None),
                   "archive", None)
    if arch is None:
        arch = _get_archive_dict(cfg)
    return archive_node_budget(arch)


def _read(obj, name, default):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _get_archive_dict(cfg):
    rqgm = _read(cfg, "rqgm", {}) or {}
    paper = _read(rqgm, "paper", {}) or {}
    return _read(paper, "archive", {}) or {}


# ─────────────────────────────────────────────────────────────────────────────
# paper_archive_state.json — paper-phase mode provenance (§6.2)
# ─────────────────────────────────────────────────────────────────────────────


def read_paper_archive_state(checkpoint_dir: str | Path) -> dict | None:
    """Absence-tolerant read: ``None`` when missing or unparseable."""
    from ari.checkpoint import load_paper_archive_state_json

    return load_paper_archive_state_json(checkpoint_dir)


def write_paper_archive_state(checkpoint_dir: str | Path, state: dict) -> None:
    """Best-effort write — a state-write failure must never break the run."""
    try:
        from ari.checkpoint import save_paper_archive_state_json

        save_paper_archive_state_json(checkpoint_dir, state)
    except Exception:
        log.warning(
            "failed to write %s under %s", PAPER_ARCHIVE_STATE_FILENAME,
            checkpoint_dir, exc_info=True,
        )


def build_paper_run_start_state(
    *,
    paper_mode: str,
    rqgm_paper_enabled: bool,
    mode_source: str = "config",
    exploration_mode: str = "",
    seed_node_id: str | None = None,
    evaluation_condition_id: str = "",
) -> dict:
    """Schema-v1 paper-phase-start payload (Task 01 §6.2).

    ``created_at`` is metadata only — never hashed and never read by decision
    logic (P2 holds for every consumer of this file)."""
    if mode_source not in PAPER_MODE_SOURCES:
        log.warning("unknown mode_source %r; recording 'config'", mode_source)
        mode_source = "config"
    state = {
        "schema_version": PAPER_ARCHIVE_STATE_SCHEMA_VERSION,
        "paper_mode": paper_mode,
        "rqgm_paper_enabled": bool(rqgm_paper_enabled),
        "mode_source": mode_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "exploration_mode": str(exploration_mode or ""),
        "seed_node_id": seed_node_id,
        "switch_journal": [
            {"event": "paper_phase_start", "paper_mode": paper_mode,
             "epoch_id": None},
        ],
    }
    if evaluation_condition_id:
        state["evaluation_condition_id"] = str(evaluation_condition_id)
    return state


#: Append-only trail of the seeds later paper invocations actually used.
SEED_JOURNAL_FIELD = "seed_journal"


def latest_recorded_seed(state: dict) -> "str | None":
    """The most recent seed this state file knows about — the last journal
    entry if the seed ever changed, else the paper-phase-start record."""
    journal = state.get(SEED_JOURNAL_FIELD)
    if isinstance(journal, list):
        for entry in reversed(journal):
            if isinstance(entry, dict) and entry.get("seed_node_id"):
                return str(entry["seed_node_id"])
    seed = state.get("seed_node_id")
    return str(seed) if seed else None


def journal_seed_change(
    checkpoint_dir: str | Path, seed_node_id: "str | None",
) -> bool:
    """Append a ``seed_changed`` entry when this invocation's seed differs
    from the latest one the file records. Returns whether it appended.

    Deliberately records only the ids: WHY the seed moved is already in the
    durable logs this file sits next to — ``rqgm_audit.jsonl`` for the
    erasure events, ``rqgm_adversarial_cases.jsonl`` for the validated-attack
    penalties — and inferring a reason here could only guess. Best-effort:
    a provenance note must never break the paper phase."""
    if not seed_node_id:
        return False
    try:
        state = read_paper_archive_state(checkpoint_dir)
        if not isinstance(state, dict) or not state:
            return False
        prior = latest_recorded_seed(state)
        if str(prior or "") == str(seed_node_id):
            return False
        journal = state.get(SEED_JOURNAL_FIELD)
        if not isinstance(journal, list):
            journal = []
        journal.append({
            "event": "seed_changed",
            "prior_seed_node_id": prior,
            "seed_node_id": str(seed_node_id),
        })
        state[SEED_JOURNAL_FIELD] = journal
        write_paper_archive_state(checkpoint_dir, state)
        log.info(
            "paper seed changed since the recorded start (%s -> %s); "
            "journaled in %s",
            prior, seed_node_id, PAPER_ARCHIVE_STATE_FILENAME,
        )
        return True
    except Exception:
        log.warning("seed-change journaling failed (best-effort)",
                    exc_info=True)
        return False


def persist_paper_run_start(
    checkpoint_dir: str | Path,
    *,
    paper_mode: str = "rqgm_archive",
    rqgm_paper_enabled: bool = True,
    mode_source: str = "config",
    exploration_mode: str = "",
    seed_node_id: str | None = None,
    evaluation_condition_id: str = "",
) -> None:
    """Write ``paper_archive_state.json`` once at paper-phase start.

    Write-once: an existing file (re-invocation) is never clobbered — the
    persisted mode wins on re-invocation (§5.5), and the epoch-boundary journal
    entries Task 03 appends go through their own transaction.

    ``seed_node_id`` is the one field write-once cannot keep true: it records
    what the FIRST paper invocation started from, while the live seed is
    recomputed every round (``_run_one_round`` → ``select_best_node`` →
    ``_make_paper_root``) under three mechanisms that exist precisely to change
    it — selective erasure excluding the recorded seed, an escalation penalty
    demoting it, and the penalty replay that re-applies both before selection.
    So a later invocation computing a different seed APPENDS to the seed
    journal instead of rewriting the record (the
    ``paper_utility_policy_journal`` pattern), leaving the file able to tell
    the whole story rather than a silently stale first line."""
    if (Path(checkpoint_dir) / PAPER_ARCHIVE_STATE_FILENAME).exists():
        journal_seed_change(checkpoint_dir, seed_node_id)
        return
    write_paper_archive_state(
        checkpoint_dir,
        build_paper_run_start_state(
            paper_mode=paper_mode,
            rqgm_paper_enabled=rqgm_paper_enabled,
            mode_source=mode_source,
            exploration_mode=exploration_mode,
            seed_node_id=seed_node_id,
            evaluation_condition_id=evaluation_condition_id,
        ),
    )


def reconcile_paper_resume_mode(
    cfg: "ARIConfig", checkpoint_dir: str | Path
) -> None:
    """Force *cfg* to the persisted paper mode on a re-invoked ``ari paper``
    (Task 01 §5.5).

    The persisted paper mode wins over config and env; a disagreement produces
    a warning, never a silent mode flip on re-invocation. A checkpoint WITHOUT
    ``paper_archive_state.json`` started (and stays) ``linear`` for that paper
    phase — absence is default (the caller only invokes this when the file
    exists, so no ``ari.rqgm`` module loads on a pure-linear re-invocation).
    """
    requested_mode = getattr(getattr(cfg, "paper", None), "mode", "linear")
    requested_enabled = bool(
        getattr(getattr(getattr(cfg, "rqgm", None), "paper", None),
                "enabled", False)
    )
    state = read_paper_archive_state(checkpoint_dir)
    if state is None:
        return
    persisted_mode = str(state.get("paper_mode", "linear"))
    if persisted_mode not in ("linear", "rqgm_archive"):
        log.warning(
            "resume: %s has unknown paper_mode %r; treating as linear",
            PAPER_ARCHIVE_STATE_FILENAME, persisted_mode,
        )
        persisted_mode = "linear"
    persisted_enabled = bool(state.get("rqgm_paper_enabled", False))
    if (requested_mode, requested_enabled) != (persisted_mode, persisted_enabled):
        log.warning(
            "resume: persisted paper mode wins — %s records paper_mode=%s "
            "enabled=%s (config/env requested paper_mode=%s enabled=%s); a "
            "paper phase's mode is set at the first invocation and read "
            "persisted-first thereafter",
            PAPER_ARCHIVE_STATE_FILENAME, persisted_mode, persisted_enabled,
            requested_mode, requested_enabled,
        )
    cfg.paper.mode = persisted_mode
    cfg.rqgm.paper.enabled = persisted_enabled


# ─────────────────────────────────────────────────────────────────────────────
# Default reviewer oracle — deterministic, LLM-free. NOT dead: it is the
# fallback the archive runs on when no governed paper_reviewer prompt is active
# (and the scriptable oracle tests pin behaviour against). The governed reviewer
# below supersedes it whenever an epoch has an active prompt.
# ─────────────────────────────────────────────────────────────────────────────


class _DefaultPaperReviewer:
    """A deterministic (P2), LLM-free scoring oracle: the reviewer the archive
    substrate runs on until a governed ``paper_reviewer`` prompt is active. It
    is the constructor default (no ``reviewer=`` injected), so every round
    before the first governed one scores through here.

    ``score`` reads the ``.tex`` TEXT only (no compile, §5.5) and maps its
    structural features to a bounded score in [0, 1]; ``review`` returns no
    actionable revisions (``paper_refine`` then keeps the paper unchanged per
    its non-destructive contract). Task 03/04 swap this for the governed
    reviewer anchored on the accept/reject corpus.
    """

    prompt_hash = "paper_reviewer_default_v0"

    def review(self, tex_path: str):
        return SimpleNamespace(suggested_revisions_json="[]")

    def score(self, tex_path: str) -> float:
        try:
            text = Path(tex_path).read_text(encoding="utf-8")
        except OSError:
            return 0.0
        anchors = text.count("% CLAIM")
        sections = text.count("\\section")
        length = len(text)
        raw = (
            0.4 * _sat(length / 8000.0)
            + 0.3 * _sat(anchors / 8.0)
            + 0.3 * _sat(sections / 6.0)
        )
        return round(raw, 6)


def _sat(x: float) -> float:
    return 1.0 if x >= 1.0 else (0.0 if x <= 0.0 else x)


# ─────────────────────────────────────────────────────────────────────────────
# Governed paper reviewer (Task 03/04) — the GOVERNED reviewer whose bytes RQGM
# evolves. Renders the epoch's ACTIVE paper_reviewer prompt, scores drafts in
# ari-core (never review_compiled_paper), emits a review_record per score, and
# carries the active prompt_hash so co-evolution is observable end-to-end.
# ─────────────────────────────────────────────────────────────────────────────


class GovernedPaperReviewer:
    """The governed ``paper_reviewer`` oracle (docs/plans/ari_rqgm_paper/03
    §5.8, /04 §5.4).

    Driven by the epoch's ACTIVE ``paper_reviewer`` prompt TEXT + hash (the
    evolving bytes live in ari-core, not the skill). ``review`` returns REAL
    suggested revisions so ``paper_refine`` actually refines and the draft tree
    deepens past depth 2; ``score`` reads the ``.tex`` TEXT only (no compile,
    §5.5) and — crucially — writes a ``review_record`` into ``rqgm_audit.jsonl``
    per score so ``paper_reviewer_v1`` is reliability-assessable (its
    registration is operative, not nominal).

    The ACTIVE prompt bytes are an input to BOTH judgements this class makes
    (§5.8): ``score`` scores each draft on the rubric the prompt declares, and
    ``anchor_verdict`` judges each reference manuscript through the prompt. That
    is what makes the reviewer half of co-evolution live — evolved bytes move
    best-belief selection and anchor agreement.

    Injectable seams keep it deterministic and scriptable (P2): ``score_fn``
    maps (prompt_text, draft text) -> score — the seam an LLM-backed
    agent-as-judge scorer plugs into, and prompt-carrying so an injected scorer
    is never prompt-blind; ``revise_fn`` maps draft text -> revisions JSON;
    ``verdict_fn`` maps (prompt_text, anchor_case_view) -> accept_recommendation
    (used by the anchor scorer). Absent ``score_fn``/``revise_fn`` the defaults
    are deterministic and LLM-free so the substrate runs today. Absent
    ``verdict_fn`` there is NO verdict source and the anchor reports zero
    coverage — never a forged verdict (plan 04 §4/§5.9, §10 R4).
    """

    def __init__(
        self,
        *,
        prompt_text: str,
        prompt_hash: str,
        checkpoint_dir=None,
        epoch_id: str = "epoch_000",
        component_id: str = "paper_reviewer_v1",
        role: str = "paper_reviewer",
        score_fn=None,
        revise_fn=None,
        verdict_fn=None,
        confidence_fn=None,
    ) -> None:
        self.prompt_text = str(prompt_text or "")
        self.prompt_hash = str(prompt_hash or "")
        self.ckpt = checkpoint_dir
        self.epoch_id = str(epoch_id)
        self.component_id = str(component_id)
        self.role = str(role)
        self._score_fn = score_fn
        self._revise_fn = revise_fn
        self._verdict_fn = verdict_fn
        # ``confidence_fn(prompt_text) -> float`` — the reviewer's STATED
        # confidence (§5.8). A reviewer whose stated confidence drifts from
        # the scores it emits is mis-calibrated and falls below RELIABILITY_
        # FLOOR. Default: confidence == score (calibrated).
        self._confidence_fn = confidence_fn
        self._review_seq = 0
        self._rubric_warned = False
        self._axes = None                 # lazy venue-rubric score dimensions
        self._manuscript_binding: dict = {}
        self._manuscript_fixed_block = ""
        # The reviewer's held-out anchor agreement rate (0..1), set by the
        # runtime's anchor scorer before draft scoring. Stamped on every DRAFT
        # review_record's ``agreement`` so a reviewer that disagrees with the
        # ground truth is reliability-penalised regardless of draft count — the
        # anchor (not per-draft self-scoring) is the trust signal (§5.1).
        self._anchor_agreement = None

    # ── the archive-scorer surface (injected into PaperDraftExecutor) ────
    def bind_manuscript_inputs(self, binding: dict, fixed_block: str) -> None:
        """Bind every draft judgement to one immutable manuscript bundle.

        The governed prompt hash continues to identify the evolvable reviewer
        bytes.  The separate manuscript fingerprint identifies the fixed
        evidence/readiness block; neither identity is allowed to masquerade as
        the other.  Rebinding one reviewer instance to different bytes is a
        stale-input error, not prompt evolution.
        """

        incoming = dict(binding or {})
        prior = str(self._manuscript_binding.get("input_fingerprint") or "")
        current = str(incoming.get("input_fingerprint") or "")
        if prior and prior != current:
            raise ValueError("paper reviewer manuscript binding changed within an epoch")
        self._manuscript_binding = incoming
        self._manuscript_fixed_block = str(fixed_block or "")
        for callback in (self._score_fn, self._revise_fn):
            bind = getattr(callback, "bind_manuscript_inputs", None)
            if callable(bind):
                bind(incoming, self._manuscript_fixed_block)

    def _draft_prompt_text(self) -> str:
        if not self._manuscript_fixed_block:
            return self.prompt_text
        return (
            f"{self.prompt_text}\n\n{self._manuscript_fixed_block}"
            if self.prompt_text
            else self._manuscript_fixed_block
        )

    def review(self, tex_path: str):
        """REAL suggested revisions so ``paper_refine`` deepens the tree."""
        text = _read_text(tex_path)
        if self._revise_fn is not None:
            revs = self._revise_fn(text)
        else:
            # A concrete, anchor-safe substitution the skill can apply; keeps
            # the refine child a genuine improvement over its parent so the
            # frontier expands it (depth 3), not a no-op like the Wave-3a
            # placeholder reviewer.
            revs = json.dumps(
                [{"type": "improve", "instruction":
                  "Tighten the claims and remove any unsupported adjective."}],
                ensure_ascii=False,
            )
        return SimpleNamespace(suggested_revisions_json=revs)

    def set_anchor_agreement(self, rate) -> None:
        self._anchor_agreement = None if rate is None else float(rate)

    @property
    def draft_axes(self) -> list:
        """The VENUE RUBRIC's score dimensions this reviewer scores drafts on
        (``GENERIC_AXES`` + ``rubric_to_axes``, plan 03 §4). Resolved once per
        reviewer; the venue owns them, so a co-evolved prompt cannot add or
        drop one — it can only emphasise (:func:`emphasised_axes`)."""
        if self._axes is None:
            self._axes = draft_axes(_venue_rubric())
        return self._axes

    def score(self, tex_path: str) -> float:
        """The draft score the archive best-belief-selects on (§5.8/§5.9).

        The SCORE DIMENSIONS are the venue rubric's (:attr:`draft_axes`); the
        ACTIVE prompt supplies this reviewer's EMPHASIS over them, so a
        co-evolved reviewer still moves draft selection without being able to
        mint or delete a dimension. The injected ``score_fn`` receives the
        prompt too — that is the seam an LLM-backed agent-as-judge plugs into,
        and the only path that can score an axis no deterministic reader can
        read (§5.8 Residual)."""
        text = _read_text(tex_path)
        if self._score_fn is not None:
            score = float(self._score_fn(self.prompt_text, text))
        else:
            axes = self.draft_axes
            rubric_score = _rubric_draft_score(self.prompt_text, text, axes)
            # None => the venue rubric declares no axis this LLM-free scorer
            # can read at all. Reported, not hidden — a run scoring on the
            # structural base is NOT governed scoring (§5.9 on-ramp).
            score = (_structural_score(text) if rubric_score is None
                     else rubric_score)
            self._warn_if_prompt_independent(axes)
        # A DRAFT review_record carries the reviewer's held-out anchor
        # agreement (its trust signal, §5.1), not a self-graded confidence:
        # a reviewer's per-draft self-confidence is only meaningfully
        # assessable against ground truth. When there is no anchor (on-ramp),
        # the record stays assessable via the stated confidence instead.
        if self._anchor_agreement is not None:
            self._append_review_record(
                node_id=Path(tex_path).parent.name, outcome_score=score,
                confidence=None, agreement=self._anchor_agreement,
            )
        else:
            # `stated_confidence()` is None when no confidence source is wired
            # (the production shape). The record then carries NO confidence key
            # and calibration stays ABSENT — it does not carry `score` itself,
            # which was the pre-2026-07-17 default and fabricated PERFECT
            # calibration (`|score - score| = 0` => a free `1 - 0 = 1.0` part
            # in every reliability_score).
            self._append_review_record(
                node_id=Path(tex_path).parent.name, outcome_score=score,
                confidence=self.stated_confidence(), agreement=None,
            )
        return round(score, 6)

    def _warn_if_prompt_independent(self, axes: list) -> None:
        """WARN (once per reviewer) when the active prompt names NO venue-rubric
        axis. The draft is still scored — on the venue's own weighting, which is
        governance data, not a heuristic — but the reviewer's own bytes are then
        not an input to it, so evolving them cannot move best-belief selection.
        That fact is announced rather than left to be discovered."""
        if self._rubric_warned or emphasised_axes(self.prompt_text, axes):
            return
        self._rubric_warned = True
        log.warning(
            "paper_reviewer %s (%s) names no venue-rubric axis: draft scores "
            "are the rubric's own weighting and PROMPT-INDEPENDENT — evolving "
            "these bytes cannot move best-belief selection "
            "(plan ari_rqgm_paper/03 §5.8)",
            self.component_id, self.prompt_hash[:8],
        )

    def stated_confidence(self) -> "float | None":
        """The reviewer's STATED confidence, or ``None`` when NO confidence
        source is wired (§5.8).

        ``None`` is an ABSENCE, not a low confidence: callers MUST omit the
        field rather than substitute a number. This returned ``1.0`` until
        2026-07-17, and because production wires no ``confidence_fn``
        (`cli/projects.py`), that constant was the confidence stamped on every
        anchor review_record in every real run. It corrupted the reliability
        channel algebraically: an anchor record's ``outcome_score`` IS its
        ``agreement``, so a pinned ``confidence = 1.0`` makes
        ``calibration_error = mean|1.0 - agreement| = 1 - agreement_rate``, and
        ``reliability_score = mean[1 - attack_ratio, agreement_rate,
        1 - calibration_error]`` then averages the SAME signal twice under two
        names (measured: agreement_rate 0.5 => calibration_error 0.5 =>
        reliability 0.667, where the honest value is 0.75). Two of the three
        parts were one restated signal presented as independent evidence, and
        that score gates RELIABILITY_FLOOR.

        With ``None``, ``_reliability.py:102-107`` (which already filters
        non-numeric confidence out of ``calibrations``) leaves
        ``calibration_error`` ABSENT and ``reliability_score`` averages only
        the parts that actually exist — the same discipline that module already
        applies to every other missing part."""
        if self._confidence_fn is None:
            return None
        return float(self._confidence_fn(self.prompt_text))

    # ── §5.8 review_record append (the reliability signal) ──────────────
    def _append_review_record(self, *, node_id, outcome_score, confidence,
                              agreement, source_refs=()):
        if self.ckpt is None:
            return
        try:
            from ari.rqgm.governance._records import created_at_now
            from ari.rqgm.store import ImmutableAuditLog

            self._review_seq += 1
            payload = {
                "record_type": "review_record",
                "record_id": f"prev_{self.prompt_hash[:6]}_{self._review_seq:04d}",
                "epoch_id": self.epoch_id,
                "component_id": self.component_id,
                "role": self.role,
                "prompt_hash": self.prompt_hash,
                "created_at": created_at_now(),
                "status": "active",
                "outcome_score": float(outcome_score),
                "node_id": str(node_id),
                "source_refs": list(source_refs),
            }
            if self._manuscript_binding:
                payload.update({
                    "manuscript_input_fingerprint": str(
                        self._manuscript_binding.get("input_fingerprint") or ""
                    ),
                    "manuscript_binding_digest": str(
                        self._manuscript_binding.get("binding_digest") or ""
                    ),
                    "manuscript_brief_bundle_digest": str(
                        self._manuscript_binding.get("brief_bundle_digest") or ""
                    ),
                    "manuscript_section_brief_digests": list(
                        self._manuscript_binding.get("section_brief_digests") or ()
                    ),
                })
            if confidence is not None:
                payload["confidence"] = float(confidence)
            if agreement is not None:
                payload["agreement"] = float(agreement)
            ImmutableAuditLog(self.ckpt).append("review_record", payload)
        except Exception:
            log.debug("review_record append failed (best-effort)", exc_info=True)

    # ── anchor scoring: the reviewer's verdict on one reference manuscript ─
    def anchor_verdict(self, case: dict) -> "str | None":
        """The reviewer's ``accept_recommendation`` on one anchor case, driven
        by the ACTIVE prompt text (so a co-evolved reviewer can agree better
        than its incumbent). Deterministic; scriptable via ``verdict_fn``.

        ``None`` => NO VERDICT SOURCE is wired => ZERO COVERAGE (plan 04 §5.9's
        on-ramp), never a forged verdict. Refusing to anchor is strictly safer
        than anchoring on self-labels (§5.3); "the honest response is to have no
        anchor rather than a captured one" (§5.9). Callers MUST skip a ``None``
        rather than score it — it is an absence, not a miss.

        The case's LABEL is never an input (§4, §10 R4): the verdict source only
        ever sees :func:`anchor_case_view`, which has no label field. A verdict
        derived from the label would make agreement 1.0 by construction and the
        anchor would measure nothing."""
        if self._verdict_fn is None:
            return None
        from ari.rqgm.paper_anchor import anchor_case_view

        return str(self._verdict_fn(self.prompt_text, anchor_case_view(case)))


def _read_text(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


# ── the venue-rubric draft rubric (plan 03 §4 / §5.8) ───────────────────────
#
# WHERE THE SCORE DIMENSIONS COME FROM (re-specified 2026-07-17). The draft's
# scoring axes are the VENUE RUBRIC's score dimensions, derived with the
# machinery plan 03 §4 names for exactly this job — `dynamic_axes.GENERIC_AXES`
# (the domain-agnostic floor) + `dynamic_axes.rubric_to_axes` (venue rubric ->
# score dimensions), composed by that module's own public composer
# `build_axes_for_run`, and resolved from the same `ARI_RUBRIC` source the
# exploration evaluator resolves (`core._load_rubric_dict_for_axes`). With no
# rubric on disk the axis set degrades to `GENERIC_AXES` alone — that module's
# own documented degradation ("callers degrade to the generic floor"), not a
# local invention.
#
# WHAT THIS REPLACED, AND WHY (the 2026-07-17 finding). The shipped scorer
# derived the axes from the REVIEWER PROMPT instead: a `_RUBRIC_AXES` table of
# prompt trigger words, clause-scoped by a `_CRITERION_MARKERS` list, weighted
# by the share of "criterion clauses" each axis won. No plan sanctioned it —
# `grep dynamic_axes|rubric_to_axes|GENERIC_AXES paper_runtime.py` returned
# NOTHING while §4 named all three — and it produced ZERO discrimination:
# measured under the SHIPPED founding prompt, a 100-char stub (0 claims, 0
# sections) and a rich 8000-char draft (8 claims, 6 sections) BOTH scored
# exactly 1.0, because that prompt honestly declares ONE criterion
# (reproducibility) and the reading zeroed every axis it did not name. In-epoch
# best-belief selection was degenerate by default. Sourcing the axes from the
# reviewer's own evolving bytes was also the wrong trust boundary: it let a
# candidate reviewer MINT or DELETE score dimensions by wording. The venue owns
# the dimensions; the reviewer owns only its emphasis over them (below).
#
# HOW AN AXIS IS READ, AND WHEN IT IS ABSENT. Absent an injected `score_fn`
# there is no LLM on this path (P2: deterministic, no network, no wall clock),
# so each axis is read by a bounded [0,1] read of the draft TEXT (§5.5: no
# compile). A reader declares the SUBJECT it measures — a property of the
# MEASUREMENT itself — and reads an axis when the axis's own RUBRIC BYTES (its
# name + description, venue-authored) name that subject. This binding rule is
# the one rule plan 03 lacked; it is written down in §5.8 (amended 2026-07-17)
# rather than assumed here.
#
# An axis NO reader can read (`novelty`: "Does the work advance beyond existing
# approaches?") is ABSENT — it is excluded from the composite, never scored by
# a constant. That is the same discipline `governance/_reliability.py:110-119`
# applies to a missing calibration part: average the parts that exist, never
# fabricate the ones that do not. A rubric axis is only scoreable in full by
# the agent-as-judge path (an injected `score_fn`, §5.8's Residual); until that
# lands the LLM-free composite honestly covers the readable subset and says so.


def _venue_rubric() -> "dict | None":
    """The ACTIVE venue rubric, resolved exactly as the exploration evaluator
    resolves it (`ARI_RUBRIC` -> `config/reviewer_rubrics/<id>.yaml`). ``None``
    when no rubric is on disk => the axis set degrades to ``GENERIC_AXES``."""
    try:
        from ari.core import _load_rubric_dict_for_axes

        return _load_rubric_dict_for_axes()
    except Exception:
        log.debug("venue rubric load failed (generic floor)", exc_info=True)
        return None


def draft_axes(rubric=None) -> list:
    """The draft's score dimensions: ``GENERIC_AXES`` + the venue rubric's
    ``score_dimensions``, via ``dynamic_axes``' own composer (plan 03 §4)."""
    from ari.evaluator.dynamic_axes import build_axes_for_run

    return build_axes_for_run(rubric=rubric)


def _paper_founding_output_schema(role: str) -> "dict | None":
    """The founding ``output_schema`` for a governed paper role, read from
    :data:`ari.rqgm.prompt_spec.PAPER_FOUNDING_PROMPT_TABLE` — the SAME reply
    contract the live runtime enforces (``paper_reviewer`` -> json_object with a
    ``accept_recommendation`` string; ``paper_writer`` -> freeform). ``None`` for
    a role with no paper founding row (schema_dry_run then has nothing to check
    and is a no-op, never a drop). Deterministic table read."""
    from ari.rqgm.prompt_spec import PAPER_FOUNDING_PROMPT_TABLE

    for _pid, _key, table_role, _evolvable, schema in PAPER_FOUNDING_PROMPT_TABLE:
        if table_role == role:
            return dict(schema)
    return None


#: The environment-specific identifiers the founding reviewer prompt's own
#: reproducibility criterion names (prompts/rqgm/paper_reviewer.md:9).
_ENV_SPECIFIC_MARKERS: tuple[str, ...] = (
    "/home/", "/scratch/", "/work/", "/mnt/", "hostname",
    "node id", "cluster name",
)


def _read_claim_anchors(text: str) -> float:
    return _sat(text.count("% CLAIM") / 8.0)


def _read_sectioning(text: str) -> float:
    return _sat(text.count("\\section") / 6.0)


def _read_body_depth(text: str) -> float:
    return _sat(len(text) / 8000.0)


def _read_env_leakage(text: str) -> float:
    low = text.lower()
    hits = sum(low.count(m) for m in _ENV_SPECIFIC_MARKERS)
    return 1.0 - _sat(hits / 4.0)


#: ``(reader_id, subject terms, read)``. The subject terms describe WHAT THE
#: READ MEASURES; they are matched against an AXIS's rubric bytes (name +
#: description), never against the reviewer's prompt — a co-evolving reviewer
#: must not be able to conjure a scoring axis by choosing words. Word-bounded
#: stems (``reproduc`` matches "reproducibility"/"reproduce").
_DRAFT_READERS: tuple[tuple[str, tuple[str, ...], "Callable[[str], float]"], ...] = (
    ("claim_anchors",
     ("claim", "contribution", "support", "evidence", "grounded", "sound",
      "correct"),
     _read_claim_anchors),
    ("sectioning",
     ("clarity", "clear", "presentation", "writing", "written", "organiz",
      "structure", "readab", "exposition"),
     _read_sectioning),
    ("body_depth",
     ("quality", "detail", "thorough", "depth", "rigor", "methodolog",
      "complete"),
     _read_body_depth),
    ("env_leakage",
     ("reproduc", "replicat", "artifact", "availab"),
     _read_env_leakage),
)

#: An emphasised axis counts DOUBLE. Bounded on purpose: the reviewer's bytes
#: re-rank the venue's dimensions, they never delete one (which is exactly what
#: the prompt-sourced predecessor did — an axis the prompt did not name carried
#: zero weight, collapsing the founding rubric to a single axis).
_EMPHASIS_MULTIPLIER = 2.0


def _axis_rubric_bytes(axis) -> str:
    """An axis's venue-authored bytes: its name + description, case-folded."""
    name = str(getattr(axis, "name", "") or "").replace("_", " ")
    return f"{name} {getattr(axis, 'description', '') or ''}".lower()


def axis_draft_score(axis, text: str) -> "float | None":
    """One axis's bounded [0,1] read of the draft, or ``None`` when NO reader
    can read it (ABSENT — the caller excludes it, never scores it 0 or 1)."""
    haystack = _axis_rubric_bytes(axis)
    reads = [
        fn(text) for _rid, subject, fn in _DRAFT_READERS
        if any(re.search(r"\b" + re.escape(t), haystack) for t in subject)
    ]
    if not reads:
        return None
    return sum(reads) / len(reads)


def emphasised_axes(prompt_text: str, axes: list) -> set:
    """The venue-rubric axes the reviewer PROMPT names (§5.8).

    The vocabulary is the RUBRIC's — an axis is named when a word of its own
    name appears in the prompt — so the prompt can only ever re-weight
    dimensions the venue already declared. ``set()`` when the prompt names
    none: the score is then the venue's own weighting and evolving these bytes
    cannot move it, which :meth:`_warn_if_prompt_independent` announces."""
    low = (prompt_text or "").lower()
    out = set()
    for axis in axes:
        tokens = [t for t in str(getattr(axis, "name", "")).split("_")
                  if len(t) >= 4]
        if tokens and any(re.search(r"\b" + re.escape(t), low) for t in tokens):
            out.add(axis.name)
    return out


def _rubric_draft_score(prompt_text: str, text: str, axes: list) -> "float | None":
    """The draft score over the VENUE RUBRIC's axes (deterministic, LLM-free).

    Each readable axis contributes its bounded read at its rubric weight
    (``dynamic_axes.axes_to_weights``), doubled where the reviewer's prompt
    emphasises it. Unreadable axes are ABSENT and excluded. ``None`` when the
    rubric declares no axis this scorer can read at all — the caller then has
    no venue rubric to score on and falls through to the structural base."""
    from ari.evaluator.dynamic_axes import axes_to_weights

    weights = axes_to_weights(axes)
    emphasis = emphasised_axes(prompt_text, axes)
    num = 0.0
    den = 0.0
    for axis in axes:
        read = axis_draft_score(axis, text)
        if read is None:
            continue                       # ABSENT: no reader, never a constant
        weight = weights.get(axis.name, 0.0) * (
            _EMPHASIS_MULTIPLIER if axis.name in emphasis else 1.0
        )
        num += weight * read
        den += weight
    if den <= 0.0:
        return None
    return round(num / den, 6)


def _structural_score(text: str) -> float:
    """The rubric-INDEPENDENT structural base. Reachable only when the venue
    rubric declares no axis this LLM-free scorer can read (and via
    :class:`_DefaultPaperReviewer`, the pre-governance substrate). Never the
    governed path."""
    anchors = text.count("% CLAIM")
    sections = text.count("\\section")
    length = len(text)
    raw = (
        0.4 * _sat(length / 8000.0)
        + 0.3 * _sat(anchors / 8.0)
        + 0.3 * _sat(sections / 6.0)
    )
    return round(raw, 6)


# ─────────────────────────────────────────────────────────────────────────────
# PaperArchiveRuntime — the single construction funnel (§5.3/§5.4)
# ─────────────────────────────────────────────────────────────────────────────


class PaperArchiveRuntime:
    """Facade constructed only under the effective ``rqgm_archive`` paper mode.

    Task 01 fixes the construction site + provenance; Task 02 fills
    ``run_archive`` with the runnable best-first draft archive. The governed
    roles, the anchor utility, the self-preference adversary, the per-epoch cost
    caps, and the multi-round epoch loop (Tasks 03-07) all live inside THIS
    facade — never scattered at the call site, which is the property that keeps
    ``linear`` mode free of any ``ari.rqgm`` import.
    """

    def __init__(self, cfg: "ARIConfig", *, checkpoint_dir=None, mcp=None,
                 reviewer=None, llm=None, reviewer_verdict_fn=None,
                 reviewer_score_fn=None, reviewer_revise_fn=None,
                 reviewer_confidence_fn=None, adversary_llm=None,
                 schema_dry_run_fn=None) -> None:
        self.cfg = cfg
        self.checkpoint_dir = checkpoint_dir
        self.mcp = mcp
        self.memory = None
        # docs/plans/ari_rqgm_paper/05: the paper_self_preference adversary's
        # LLM seam (attack/defense/adjudication). Defaults to ``llm`` (the real
        # LLMClient in production, .complete-shaped); tests inject a scriptable
        # governance LLM. ``None`` on both => no attacks (AdversaryEngine's
        # no-LLM floor), which is the cheap on-ramp posture.
        self._adversary_llm = adversary_llm
        self._selfpref_round = None
        # Task 03/04 co-evolution seams. ``llm`` is the paper-phase mutator
        # callable (prompt -> str) the PromptMutator uses to co-evolve the
        # governed reviewer/writer bytes; ``reviewer_verdict_fn`` /
        # ``reviewer_score_fn`` / ``reviewer_revise_fn`` script the governed
        # reviewer (deterministic P2 in tests). ``reviewer`` (Wave-3a) still
        # overrides everything for the pure substrate path / on-ramp.
        # Both reviewer judgement seams carry the ACTIVE prompt text as their
        # first argument — ``reviewer_score_fn(prompt_text, draft_text)`` and
        # ``reviewer_verdict_fn(prompt_text, anchor_case_view)`` — so an
        # injected scorer/judge is never prompt-blind (§5.8).
        self.llm = llm
        self._reviewer_override = reviewer
        self._reviewer_verdict_fn = reviewer_verdict_fn
        self._reviewer_score_fn = reviewer_score_fn
        self._reviewer_revise_fn = reviewer_revise_fn
        self._reviewer_confidence_fn = reviewer_confidence_fn
        # docs/plans/ari_rqgm_paper/03 §5.9 step 2: the schema_dry_run LLM reply
        # seam. schema_dry_run renders a candidate prompt to a reply and checks
        # it against the role's founding output_schema — a non-deterministic,
        # budgeted LLM call, so it is INCOMPATIBLE with this evaluator's default
        # deterministic (P2) path. It runs ONLY when this reply seam
        # ``(role, prompt_text, output_schema) -> reply_text`` is injected, and
        # is a documented no-op (skipped, never a fabricated pass) otherwise —
        # production (cli/projects.py:219) injects none. Distinct from ``llm``
        # (the PromptMutator's prompt->str seam) on purpose: that callable emits
        # a mutated PROMPT, not a schema-checkable reply.
        self._schema_dry_run_fn = schema_dry_run_fn
        # The active reviewer used by the CURRENT round's executor (rebuilt per
        # round from the epoch's active prompt); a deterministic default until
        # the first governed round resolves the active prompt.
        self.reviewer = (
            reviewer if reviewer is not None else _DefaultPaperReviewer()
        )
        self._rqgm = None                 # inner RQGMRuntime (lazy, paper_phase)
        self._anchor_pool = None
        # The active paper_reviewer / paper_writer prompt_hash observed at each
        # round head — the co-evolution witnesses the §11/self-check prints. The
        # writer sequence changes iff the writer PROMPT genuinely co-evolves
        # (§5.1, revised 2026-07-16): a real claim-gate-faithfulness sanction
        # opens its role and a shadow successor adopts via the existing T6.
        self.reviewer_prompt_hash_sequence: list[str] = []
        self.writer_prompt_hash_sequence: list[str] = []
        # The active writer's last-scored draft faithfulness (observability;
        # None until the first round's draft is gate-scored).
        self._last_writer_faithfulness = None
        # Task 06 (docs/plans/ari_rqgm_paper/06 §5.1): the REUSED
        # GovernanceBudgetManager (lazy, fail-open to None) + the current paper
        # epoch it reads counters against. `current_paper_epoch` tracks the
        # inner RQGM's frozen open epoch so the paper manager and the inner
        # manager share one per-epoch counter home (rqgm_audit.jsonl).
        self._budget_manager = None
        self._current_epoch_obj = None
        self._compiles = 0                # lazy-compile audit (§6.3, bounded top-K)
        self._last_expansions = 0         # last round's draft population (§6.3)
        # Opt-in Manuscript Complete binding.  Populated before any archive
        # resume check or model call; ``None`` keeps the historical off path
        # byte/import compatible.
        self._manuscript_inputs: dict | None = None

    @property
    def paper_mode(self) -> PaperMode:
        return resolve_paper_mode(self.cfg)

    # ── Task 06: the REUSED GovernanceBudgetManager (§5.1) ───────────────
    @property
    def current_paper_epoch(self):
        """The frozen open paper epoch the budget manager reads counters
        against. When the inner RQGMRuntime is live its `current_epoch` (a real
        `EpochState`) is authoritative — the paper manager and the inner
        manager then share one per-epoch counter home. Before the first round
        opens, a lightweight namespace carries a stable id so `_epoch_id()`
        never returns empty."""
        if self._current_epoch_obj is not None:
            return self._current_epoch_obj
        return SimpleNamespace(epoch_id="paper_epoch_000", run_id="paper")

    @property
    def budget_manager(self):
        """Reuses :class:`ari.rqgm.budget.GovernanceBudgetManager` UNCHANGED
        (Task 12 / paper-archive Task 06 §5.1) — the paper path adds no
        budget-manager rewrite, only the additive PAPER_ANCHOR_SCORING kind.
        Lazy, fail-open to ``None``; every paper consumer tolerates absence
        (decision-point gating only, never mid-call, never a raise)."""
        if self._budget_manager is None and self.checkpoint_dir is not None:
            try:
                from ari import cost_tracker
                from ari.rqgm.budget import GovernanceBudgetManager
                from ari.rqgm.store import ImmutableAuditLog

                self._budget_manager = GovernanceBudgetManager(
                    self.cfg,                       # same duck-typed cfg
                    epoch_state=lambda: self.current_paper_epoch,
                    cost_tracker=cost_tracker.get(),
                    checkpoint_dir=self.checkpoint_dir,
                    audit_log=ImmutableAuditLog(self.checkpoint_dir),
                    proposal_store=None,            # no VirSci on the paper path
                )
            except Exception:
                log.warning("paper GovernanceBudgetManager construction failed",
                            exc_info=True)
        return self._budget_manager

    def persist_mode(
        self,
        checkpoint_dir=None,
        *,
        mode_source: str = "config",
        exploration_mode: str = "",
        seed_node_id: str | None = None,
    ) -> None:
        """Write-once paper-phase-start persistence of
        ``{ckpt}/paper_archive_state.json``."""
        ckpt = checkpoint_dir if checkpoint_dir is not None else self.checkpoint_dir
        if ckpt is None:
            log.warning(
                "persist_mode: no checkpoint_dir — %s not written",
                PAPER_ARCHIVE_STATE_FILENAME,
            )
            return
        enabled = bool(
            getattr(getattr(getattr(self.cfg, "rqgm", None), "paper", None),
                    "enabled", False)
        )
        exploration_mode = exploration_mode or getattr(
            getattr(self.cfg, "ari", None), "mode", ""
        )
        try:
            from ari.rqgm.evaluation.paper_ablation import posture_from_config

            posture = posture_from_config(self.cfg)
            evaluation_condition_id = (
                posture.condition_id if posture is not None else ""
            )
        except Exception:
            evaluation_condition_id = ""
        persist_paper_run_start(
            ckpt,
            paper_mode=self.paper_mode.value,
            rqgm_paper_enabled=enabled,
            mode_source=mode_source,
            exploration_mode=exploration_mode,
            seed_node_id=seed_node_id,
            evaluation_condition_id=evaluation_condition_id,
        )

    @staticmethod
    def _manuscript_runtime_mode() -> str:
        mode = os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off").strip().lower()
        if mode not in {"off", "audit", "enforce"}:
            raise ValueError(f"unknown manuscript runtime mode: {mode!r}")
        return mode

    def _write_manuscript_archive_state(
        self, ckpt: Path, manuscript_state: dict, *, require_round_trip: bool
    ) -> None:
        state = read_paper_archive_state(ckpt) or {
            "schema_version": PAPER_ARCHIVE_STATE_SCHEMA_VERSION,
            "paper_mode": "rqgm_archive",
            "rqgm_paper_enabled": True,
            "mode_source": "config",
        }
        state["manuscript_authoring"] = dict(manuscript_state)
        write_paper_archive_state(ckpt, state)
        if require_round_trip:
            persisted = (read_paper_archive_state(ckpt) or {}).get(
                "manuscript_authoring"
            )
            expected = json.loads(json.dumps(manuscript_state, ensure_ascii=False))
            if persisted != expected:
                raise ManuscriptArchiveAuthoringError(
                    "enforced archive manuscript binding did not persist"
                )

    def _prepare_manuscript_archive_binding(self, ckpt: Path) -> dict | None:
        """Validate and freeze the complete authoring lineage before resume.

        This runs before ``_winner_already_materialised``.  Consequently a
        stale bundle cannot hide behind an already-written winner and skip the
        validation that a fresh archive invocation receives.
        """

        mode = self._manuscript_runtime_mode()
        self._manuscript_inputs = None
        if mode == "off":
            return None

        from ari.manuscript.digest import path_has_symlink_component
        from ari.public.manuscript import (
            ExplorationSnapshotV1,
            ManuscriptAuthoringBindingV1,
            ManuscriptContextV1,
            ManuscriptReadinessReportV1,
            ManuscriptRequirementProfileV1,
            OmissionManifestV1,
            SectionBriefBundleV1,
            canonical_digest,
        )

        root = ckpt.resolve()
        specs = (
            ("ARI_MANUSCRIPT_PROFILE_PATH", "requirement_profile.json",
             ManuscriptRequirementProfileV1),
            ("ARI_MANUSCRIPT_CONTEXT_PATH", "context.json", ManuscriptContextV1),
            ("ARI_MANUSCRIPT_READINESS_PATH", "readiness.json",
             ManuscriptReadinessReportV1),
            ("ARI_MANUSCRIPT_BRIEFS_PATH", "section_briefs.json",
             SectionBriefBundleV1),
            ("ARI_MANUSCRIPT_BINDING_PATH", "authoring_binding.json",
             ManuscriptAuthoringBindingV1),
        )
        loaded: dict[str, object] = {}
        paths: dict[str, Path] = {}
        for env_name, filename, model in specs:
            raw = os.environ.get(env_name, "").strip()
            if not raw:
                raise ManuscriptArchiveAuthoringError(
                    f"manuscript archive lacks {env_name}"
                )
            path = Path(os.path.abspath(raw))
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ManuscriptArchiveAuthoringError(
                    f"{env_name} escapes the manuscript checkpoint"
                ) from exc
            if (
                not path.is_file()
                or path.is_symlink()
                or path_has_symlink_component(root, path)
            ):
                raise ManuscriptArchiveAuthoringError(
                    f"{env_name} is missing or traverses a symlink"
                )
            try:
                loaded[filename] = model.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise ManuscriptArchiveAuthoringError(
                    f"{filename} is not a valid digest-bound manuscript contract"
                ) from exc
            paths[filename] = path

        profile = loaded["requirement_profile.json"]
        context = loaded["context.json"]
        readiness = loaded["readiness.json"]
        briefs = loaded["section_briefs.json"]
        binding = loaded["authoring_binding.json"]
        attempt = root / ".ari-manuscript" / "attempts" / binding.attempt_id
        for _env_name, filename, _model in specs:
            if paths[filename] != attempt / filename:
                raise ManuscriptArchiveAuthoringError(
                    "archive manuscript inputs do not share the exact attempt directory"
                )
        snapshot_path = attempt / "source_snapshot.json"
        omission_path = attempt / "omission_manifest.json"
        for path in (snapshot_path, omission_path):
            if (
                not path.is_file()
                or path.is_symlink()
                or path_has_symlink_component(root, path)
            ):
                raise ManuscriptArchiveAuthoringError(
                    f"archive manuscript attempt lacks safe {path.name}"
                )
        try:
            snapshot = ExplorationSnapshotV1.model_validate_json(
                snapshot_path.read_text(encoding="utf-8")
            )
            omissions = OmissionManifestV1.model_validate_json(
                omission_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ManuscriptArchiveAuthoringError(
                "archive manuscript source/omission contract is invalid"
            ) from exc

        lineage_ok = (
            binding.paper_mode == "rqgm_archive"
            and binding.attempt_id == attempt.name
            and snapshot.run_id == context.run_id == readiness.run_id
            == briefs.run_id == binding.run_id
            and binding.source_snapshot_digest == snapshot.snapshot_digest
            == context.source_snapshot_digest == omissions.source_snapshot_digest
            and profile.profile_digest == context.profile_digest
            == readiness.profile_digest == briefs.profile_digest
            == binding.profile_digest
            and context.omission_manifest_digest == omissions.manifest_digest
            and context.context_digest == readiness.context_digest
            == briefs.context_digest == binding.context_digest
            and readiness.readiness_digest == briefs.readiness_digest
            == binding.readiness_digest
            and briefs.bundle_digest == binding.brief_bundle_digest
        )
        if not lineage_ok:
            raise ManuscriptArchiveAuthoringError(
                "archive manuscript inputs do not share one digest lineage"
            )
        if mode == "enforce" and readiness.authoring_verdict not in {
            "ready", "ready_with_disclosures"
        }:
            raise ManuscriptArchiveAuthoringError(
                "enforced archive binding is not authoring-ready"
            )

        section_digests = tuple(brief.brief_digest for brief in briefs.briefs)
        allowed = tuple(sorted({
            item for brief in briefs.briefs for item in brief.allowed_evidence_ids
        }))
        negatives = tuple(sorted({
            item for brief in briefs.briefs for item in brief.contextual_negative_ids
        }))
        forbidden = tuple(sorted({
            item for brief in briefs.briefs for item in brief.forbidden_evidence_ids
        }))
        disclosures = tuple(sorted({
            item for brief in briefs.briefs for item in brief.required_disclosures
        }))
        fingerprint_payload = {
            "schema_version": "ari.manuscript-archive-input/v1",
            "run_id": binding.run_id,
            "attempt_id": binding.attempt_id,
            "source_snapshot_digest": binding.source_snapshot_digest,
            "profile_digest": profile.profile_digest,
            "context_digest": context.context_digest,
            "readiness_digest": readiness.readiness_digest,
            "brief_bundle_digest": briefs.bundle_digest,
            "binding_digest": binding.binding_digest,
            "section_brief_digests": section_digests,
            "allowed_evidence_ids": allowed,
            "contextual_negative_ids": negatives,
            "forbidden_evidence_ids": forbidden,
            "required_disclosures": disclosures,
            "omission_count": len(omissions.omissions),
        }
        fingerprint = canonical_digest(fingerprint_payload)
        info = {
            "mode": mode,
            "manuscript_bound": mode == "enforce",
            "run_id": binding.run_id,
            "attempt_id": binding.attempt_id,
            "source_snapshot_digest": binding.source_snapshot_digest,
            "profile_digest": profile.profile_digest,
            "context_digest": context.context_digest,
            "readiness_digest": readiness.readiness_digest,
            "brief_bundle_digest": briefs.bundle_digest,
            "binding_digest": binding.binding_digest,
            "section_brief_digests": section_digests,
            "allowed_evidence_ids": allowed,
            "contextual_negative_ids": negatives,
            "forbidden_evidence_ids": forbidden,
            "required_disclosures": disclosures,
            "omission_count": len(omissions.omissions),
            "input_fingerprint": fingerprint,
            "_briefs": briefs,
            "_binding": binding,
        }

        state = read_paper_archive_state(root) or {}
        prior = state.get("manuscript_authoring")
        prior = prior if isinstance(prior, dict) else {}
        records = read_paper_draft_archive(root)
        stale_reasons: list[str] = []
        if prior:
            if str(prior.get("input_fingerprint") or "") != fingerprint:
                stale_reasons.append("input_fingerprint_changed")
            if str(prior.get("mode") or "") != mode:
                stale_reasons.append("manuscript_mode_changed")
        elif records:
            stale_reasons.append("preexisting_archive_has_no_binding_state")
        for record in records:
            recorded = str(record.get("manuscript_input_fingerprint") or "")
            if recorded != fingerprint:
                stale_reasons.append(
                    f"draft_binding_mismatch:{record.get('epoch_id', '')}:"
                    f"{record.get('node_id', '')}"
                )
                break

        state_record = {
            key: value
            for key, value in info.items()
            if not key.startswith("_")
        }
        state_record.update({
            "status": (
                "stale_detected"
                if stale_reasons
                else "bound"
                if mode == "enforce"
                else "audit_legacy_authoring_observed"
            ),
            "stale_reasons": stale_reasons,
        })
        self._write_manuscript_archive_state(
            root, state_record, require_round_trip=mode == "enforce"
        )
        if stale_reasons and mode == "enforce":
            raise ManuscriptArchiveAuthoringError(
                "stale manuscript archive binding detected before resume: "
                + ", ".join(stale_reasons)
            )
        info["stale"] = bool(stale_reasons)
        self._manuscript_inputs = info
        return info

    def _record_manuscript_archive_outcome(
        self,
        ckpt: Path,
        *,
        status: str,
        failure_reason: str = "",
        winner=None,
    ) -> None:
        info = self._manuscript_inputs
        if not info:
            return
        record = {
            key: value for key, value in info.items()
            if not key.startswith("_") and key != "stale"
        }
        record["status"] = str(status)
        record["stale_reasons"] = list(
            ((read_paper_archive_state(ckpt) or {}).get("manuscript_authoring") or {})
            .get("stale_reasons", [])
        )
        if failure_reason:
            record["failure_reason"] = str(failure_reason)[:2_000]
        tex_ref = self._winner_tex_ref(winner)
        if tex_ref:
            path = Path(tex_ref)
            try:
                record["winner_id"] = str(getattr(winner, "id", "") or "")
                record["winner_tex_sha256"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                record["winner_id"] = str(getattr(winner, "id", "") or "")
                record["winner_tex_sha256"] = ""
        self._write_manuscript_archive_state(
            ckpt,
            record,
            require_round_trip=info.get("mode") == "enforce",
        )

    # ── the runnable archive (Task 02 §5.3) ─────────────────────────────
    def run_archive(
        self,
        all_nodes,
        experiment_data: dict,
        checkpoint_dir,
        mcp,
        cfg_str: str,
        *,
        linear_fallback: Callable | None = None,
    ) -> Path:
        """One paper EPOCH = one archive round. Build the best-first draft
        tree, best-belief select the winner, lazily compile it, copy it to the
        canonical ``{ckpt}/full_paper.tex``, then hand off to the EXISTING
        linear pipeline (claim-gate tail). Fail-open: any archive failure
        degrades to the linear pipeline (§8.5)."""
        ckpt = Path(checkpoint_dir)
        manuscript = self._prepare_manuscript_archive_binding(ckpt)
        archive_error: Exception | None = None
        stale_audit = bool(manuscript and manuscript.get("stale"))
        if stale_audit:
            archive_error = ManuscriptArchiveAuthoringError(
                "stale manuscript bundle detected; archive continuation skipped"
            )
            log.warning("paper archive: %s", archive_error)
        elif self._winner_already_materialised(ckpt):
            # 07 §8.6.6 / §9 Resume / R5: a resumed run whose winner is already
            # on the canonical path skips straight to the unchanged tail — no
            # re-spend of the archive's LLM budget, and no second materialise.
            log.info(
                "paper archive: winner already materialised at %s; skipping the "
                "archive (resume, 07 §8.6)", ckpt / "full_paper.tex",
            )
        else:
            try:
                if self._coevolution_enabled():
                    self._run_coevolution(all_nodes, experiment_data, ckpt, mcp)
                else:
                    self._run_one_round(all_nodes, experiment_data, ckpt, mcp)
                if not self._winner_already_materialised(ckpt):
                    raise ManuscriptArchiveAuthoringError(
                        "paper archive produced no admissible winner"
                    )
            except Exception as exc:
                archive_error = exc
                log.warning(
                    "paper archive failed; falling back to the linear pipeline",
                    exc_info=True,
                )

        winner_record = next(
            (
                record
                for record in reversed(read_paper_draft_archive(ckpt))
                if bool(record.get("is_best_belief"))
            ),
            None,
        )
        winner = None
        if winner_record is not None:
            winner = SimpleNamespace(
                id=str(winner_record.get("node_id") or ""),
                artifacts=[str(ckpt / str(winner_record.get("tex_path") or ""))],
            )

        if manuscript:
            if archive_error is None:
                self._record_manuscript_archive_outcome(
                    ckpt,
                    status=(
                        "manuscript_bound_winner"
                        if manuscript.get("mode") == "enforce"
                        else "audit_legacy_archive_winner"
                    ),
                    winner=winner,
                )
            elif manuscript.get("mode") == "enforce":
                if not bool(
                    getattr(linear_fallback, "_ari_manuscript_bound", False)
                ):
                    self._record_manuscript_archive_outcome(
                        ckpt,
                        status="authoring_backend_failed",
                        failure_reason=str(archive_error),
                    )
                    raise ManuscriptArchiveAuthoringError(
                        "enforced archive failure has no explicitly bound linear fallback"
                    ) from archive_error
                self._record_manuscript_archive_outcome(
                    ckpt,
                    status="bound_linear_fallback",
                    failure_reason=str(archive_error),
                )
            else:
                self._record_manuscript_archive_outcome(
                    ckpt,
                    status="audit_legacy_linear_fallback",
                    failure_reason=str(archive_error),
                )
        # THE Task 07 handoff (07 §5.1/§5.4/R5). The archive substitutes for the
        # generation stages; the EXISTING tail (link_paper_claims_final ->
        # claim_evidence_hard_gate_final -> render_paper -> finalize_paper) runs
        # unchanged on the winner.
        #
        # `write_paper` skips itself via `skip_if_exists: {ckpt}/full_paper.tex`
        # (workflow.yaml:207), but `paper_refine` has NO such guard and declares
        # `outputs.file: {ckpt}/full_paper.tex` — it is the only OTHER stage that
        # writes the canonical path (verified by enumerating workflow.yaml). Left
        # enabled it refined over the materialised winner, so `full_paper.tex` was
        # written TWICE and `materialize_winner` was not the single writer §5.4/R5
        # promises. Disabling it at the handoff is what makes that promise true.
        # See the 2026-07-17 amendment in 07 §5.1: the plan mandated the outcome
        # but named no mechanism, and its own sketch (the original `_cfg_str`)
        # cannot deliver it.
        #
        # Gated on the DURABLE winner signal, not an in-memory flag, so a resumed
        # run that skipped the archive above still protects its winner. No winner
        # (archive failed / fail-open) => the ORIGINAL cfg, so `write_paper` runs
        # and the run degrades to the linear result (§8.3).
        if linear_fallback is not None:
            try:
                use_archive_winner = self._winner_already_materialised(ckpt) and not (
                    manuscript and archive_error is not None
                )
                if use_archive_winner:
                    linear_fallback(
                        all_nodes, experiment_data, checkpoint_dir, mcp,
                        cfg_str, disable_stages=HANDOFF_DISABLED_STAGES,
                    )
                else:
                    linear_fallback(
                        all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str
                    )
            except Exception as exc:
                if manuscript:
                    self._record_manuscript_archive_outcome(
                        ckpt,
                        status="verification_or_fallback_failed",
                        failure_reason=str(exc),
                        winner=winner,
                    )
                raise
        return ckpt / "full_paper.tex"

    @staticmethod
    def _winner_already_materialised(ckpt: Path) -> bool:
        """Is the archive's winner already on the canonical path?

        BOTH durable signals are required: ``{ckpt}/full_paper.tex`` exists AND
        the archive recorded a best-belief winner. The record is what
        distinguishes an archive winner from a §8.3 fail-open LINEAR degrade —
        where `write_paper` also wrote `full_paper.tex` but no draft was ever
        best-belief-marked. Keying on the file alone would pin such a checkpoint
        to linear forever (the archive could never re-attempt) AND would suppress
        `paper_refine` on a run that legitimately needs it.

        Deliberately a read of durable state rather than an instance flag: it is
        equally true on the resume path, where the winner was materialised by an
        earlier process. `materialize_winner` therefore stays the pure
        select-and-copy 07 §7 pins (it gains no state read/write of its own).
        """
        if not (ckpt / "full_paper.tex").exists():
            return False
        return any(bool(r.get("is_best_belief"))
                   for r in read_paper_draft_archive(ckpt))

    def _coevolution_enabled(self) -> bool:
        """The governed multi-round loop runs UNLESS an explicit ``reviewer``
        oracle was injected (the pure-substrate path — the loop OWNS its
        reviewer, rebuilding it per round from the epoch's active governed
        prompt, so an external override is incompatible with it).

        The on-ramp toggle ``rqgm.paper.prompt_evolution.enabled: false`` does
        NOT skip the loop: the roles are still registered and scored (the loop
        runs), only candidate minting is suppressed (enforced inside the inner
        RQGMRuntime), so the roles stay pinned at their founding v1 prompts —
        best-of-N reviewed drafts with NO co-evolution (plan 03 §5.9)."""
        return self._reviewer_override is None

    # ── Task 03/04 co-evolution loop (multi-round epoch boundary) ────────
    def _run_coevolution(self, all_nodes, experiment_data, ckpt, mcp):
        """Run ``rqgm.paper.epoch.rounds`` archive rounds. Round 0 opens
        ``epoch_000`` (registering the paper founding roles, paper-mode-gated);
        each later round head fires the INHERITED ensure_epoch boundary
        (Propose -> Validate -> Audit -> Adopt, docs/plans/ari_rqgm_paper/03
        §5.9) so the governed paper_reviewer bytes co-evolve. The active
        reviewer prompt_hash observed at each round head is the co-evolution
        witness (§11)."""
        from ari.rqgm.paper_anchor import load_anchor_corpus

        rqgm = self._build_inner_rqgm(ckpt, mcp)
        if rqgm is None:                                   # kernel unavailable
            self._run_one_round(all_nodes, experiment_data, ckpt, mcp)
            return
        self._anchor_pool = load_anchor_corpus(self.cfg, ckpt)
        rqgm._anchor_pool = self._anchor_pool
        self._freeze_paper_utility_policy(ckpt)
        rounds = self._epoch_rounds()
        best = None
        round_bests: list = []
        prior_reviewer_hash = ""
        try:
            from ari.rqgm.evaluation.paper_ablation import posture_from_config

            comparison_posture = posture_from_config(self.cfg)
        except Exception:
            comparison_posture = None
        for round_idx in range(max(1, rounds)):
            rqgm.ensure_epoch(round_idx, checkpoint_dir=ckpt, run_id="paper")
            # Task 06 §5.1: adopt the inner runtime's frozen open epoch as the
            # budget counter home for this round, so the paper manager's
            # per-epoch caps key off the SAME epoch_id the inner governance
            # uses (one counter home in rqgm_audit.jsonl).
            self._current_epoch_obj = rqgm.current_epoch
            # The registries live on the RqgmRuntimeState (rqgm.state), NOT the
            # EpochState ensure_epoch returns — read the POST-boundary active
            # set from it so an adopted successor is observed at the round head.
            st = rqgm.state
            epoch_id, reviewer_hash, reviewer_text, writer_hash, writer_text = (
                self._resolve_active(st, ckpt, round_idx)
            )
            if (
                comparison_posture is not None
                and comparison_posture.selective_erasure
                and prior_reviewer_hash
                and reviewer_hash != prior_reviewer_hash
            ):
                stale_refs = erase_paper_reviewer_utilities(
                    ckpt,
                    prior_reviewer_hash,
                    replacement_epoch_id=epoch_id,
                    replacement_prompt_hash=reviewer_hash,
                )
                for prior in round_bests:
                    metrics = getattr(prior, "metrics", None)
                    if (
                        isinstance(metrics, dict)
                        and str(metrics.get("_reviewer_prompt_hash") or "")
                        == prior_reviewer_hash
                    ):
                        metrics["_valid_for_frontier"] = False
                        metrics["_stale_reason"] = "reviewer_replaced"
                rqgm._append_audit_event(
                    "paper_utility_erasure",
                    {
                        "epoch_id": epoch_id,
                        "displaced_reviewer_prompt_hash": prior_reviewer_hash,
                        "replacement_reviewer_prompt_hash": reviewer_hash,
                        "erased_utility_count": len(stale_refs),
                        "affected_drafts": stale_refs,
                        "logical_only": True,
                    },
                    checkpoint_dir=ckpt,
                )
            prior_reviewer_hash = reviewer_hash
            self.reviewer_prompt_hash_sequence.append(reviewer_hash)
            self.writer_prompt_hash_sequence.append(writer_hash)
            self.reviewer = self._build_reviewer(
                reviewer_text, reviewer_hash, ckpt, epoch_id
            )
            # Anchor signal FIRST (§5.8 / §5.4): score the ACTIVE reviewer on
            # the held-out anchor, writing per-case results into the pool
            # (board scoring), one review_record per case (reliability), and
            # setting the reviewer's agreement rate so its DRAFT review_records
            # inherit the anchor trust signal. A reviewer that disagrees with
            # the ground truth is thereby both reliability-below-floor AND
            # board-low => impeachable at the next boundary => opening for the
            # co-evolved successor. (The over-accepted adversarial round fires
            # AFTER the drafts are built, below, so the writer-culpability
            # signal — the drafts' Layer-0 gate faithfulness — is available.)
            self._score_reviewer_on_anchor(
                self.reviewer, rqgm=rqgm, epoch_id=epoch_id, checkpoint_dir=ckpt
            )
            best = self._run_one_round(
                all_nodes, experiment_data, ckpt, mcp,
                epoch_id=epoch_id, writer_hash=writer_hash,
                writer_text=writer_text,
            )
            if best is not None:
                round_bests.append(best)
            # Writer anchor (§5.1, revised 2026-07-16): score the ACTIVE
            # writer's draft against the Layer-0 claim-evidence gate
            # (read-only). An UNFAITHFUL draft makes the writer a culpable
            # component for the over-accepted-AND-unfaithful draft — the round
            # below then binds paper_writer too, opening its role for the shadow
            # successor. A FAITHFUL draft binds the reviewer only (the writer
            # sanction is causal in the writer's OWN drafts). The gate is never
            # wrapped/evolved; RQGM only READS its findings.
            writer_unfaithful = self._writer_draft_unfaithful(
                best, ckpt, writer_hash=writer_hash, epoch_id=epoch_id,
            )
            self._attack_over_accepted(
                self.reviewer, self._anchor_pool, rqgm=rqgm,
                epoch_id=epoch_id, checkpoint_dir=ckpt,
                writer_unfaithful=writer_unfaithful,
            )
        # RQGM-paper P0-P4 compare one shared archive across epochs. In the
        # no-erasure arm, old reviewer scores remain eligible; with erasure,
        # displaced-reviewer rows are retained for provenance but ineligible
        # (select_best_node itself excludes `_valid_for_frontier: False`).
        # Legacy B-paper presets preserve their prior final-round selection.
        if comparison_posture is not None:
            best = select_best_node(round_bests)
        if best is not None:
            self._finalize_best(best, ckpt, mcp)
            # Re-mirror so the final epoch reflects the winner's lazy compile.
            self._persist_budget_counters(ckpt)

    def _run_one_round(
        self, all_nodes, experiment_data, ckpt, mcp, *,
        epoch_id: str = "epoch_000", writer_hash: str = "founding",
        writer_text: str = "",
    ) -> "Node | None":
        best_node = select_best_node(all_nodes)
        root = self._make_paper_root(best_node)
        experiment = self._build_experiment(
            experiment_data, all_nodes, ckpt,
            writer_hash=writer_hash, writer_text=writer_text,
        )
        strat = PaperArchiveStrategy(self.cfg.rqgm.paper.archive, root_task=root)
        execu = PaperDraftExecutor(
            mcp, reviewer=self.reviewer, checkpoint_dir=ckpt, epoch_id=epoch_id
        )
        # Resume (§8.6 / §9 Resume; Task 06 §8.5/§9.11): rebuild THIS epoch's
        # already-recorded drafts from the durable archive instead of restarting
        # from an empty list. Content-hash safe — a record whose .tex no longer
        # matches its `tex_sha256` is dropped and regenerates. Pre-populating
        # `archive` is what makes `should_prune(current_total=1 + len(archive))`
        # below bind at the EPOCH total across invocations (a resume must not
        # re-fund the round) and `_last_expansions` a genuine
        # derived-from-durable-records value. Empty on a fresh checkpoint, so a
        # first run is byte-identical to before.
        archive: list = restore_archive_round(ckpt, strat, root, epoch_id)
        archive = [
            self._evaluate_manuscript_candidate(node, ckpt)
            for node in archive
        ]
        execu.restore(archive)
        if archive:
            log.info(
                "paper archive: restored %d recorded draft(s) for %s from %s "
                "(resume, 02 §8.6) — not regenerating them",
                len(archive), epoch_id, PAPER_DRAFT_ARCHIVE_FILENAME,
            )
        frontier: list = [root] + list(archive)
        goal = experiment.get("goal", "")
        while frontier:
            parent = strat.select_best_to_expand(frontier, goal, self.memory)
            if strat.should_prune(parent, current_total=1 + len(archive)):
                frontier.remove(parent)                     # depth / budget / erasure
                continue
            children = strat.expand(parent, existing_children=archive)
            if not children:                                # fan-out full or budget spent
                frontier.remove(parent)
                continue
            cand = strat.select_next_node(children, goal, self.memory)
            cand = execu.run(cand, experiment)              # ONE skill call (§5.4)
            cand = self._evaluate_manuscript_candidate(cand, ckpt)
            strat.record_run(cand)
            archive.append(cand)
            frontier.append(cand)                           # a refined draft is expandable
        # Erased drafts (`_valid_for_frontier: False`, paper reviewer erasure)
        # are excluded by select_best_node itself — same clause that guards the
        # exploration seed above.
        best = select_best_node(archive)
        self._last_expansions = len(archive)
        if best is not None and not self._coevolution_enabled():
            self._finalize_best(best, ckpt, mcp)
        # Task 06 §6.3: mirror the per-epoch budget counters into
        # paper_archive_state.json (the audit log stays the source of truth).
        # Persisted AFTER finalize so the winner's lazy compile is reflected.
        self._persist_budget_counters(ckpt)
        return best

    @staticmethod
    def _normalise_disclosure_text(value: str) -> str:
        value = re.sub(r"\\[A-Za-z@]+\*?", " ", str(value or ""))
        value = "".join(
            character if character.isalnum() else " "
            for character in value.casefold()
        )
        return " ".join(value.split())

    @staticmethod
    def _contains_manuscript_evidence_id(text: str, evidence_id: str) -> bool:
        token = str(evidence_id or "")
        if not token:
            return False
        # A sentence-ending period is a delimiter; generated evidence IDs do
        # not end in a period.
        alphabet = r"A-Za-z0-9_:/-"
        return bool(
            re.search(
                rf"(?<![{alphabet}]){re.escape(token)}(?![{alphabet}])",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _evaluate_manuscript_candidate(self, node, ckpt: Path):
        """Apply non-compensable candidate checks before archive selection.

        The existing Layer-0 gate remains the final authority.  This read-only
        pass prevents a candidate already known to violate the same objective
        constraints from winning merely because an evolving reviewer assigned
        it a larger utility score.  Audit mode persists identical diagnostics
        without changing eligibility.
        """

        info = self._manuscript_inputs
        if not info:
            return node
        mode = str(info.get("mode") or "audit")
        metrics = getattr(node, "metrics", None)
        if not isinstance(metrics, dict):
            metrics = {}
            node.metrics = metrics
        reasons: list[str] = []
        records = [
            record
            for record in read_paper_draft_archive(ckpt)
            if str(record.get("node_id") or "") == str(getattr(node, "id", ""))
            and str(record.get("epoch_id") or "")
            == str(metrics.get("_paper_epoch_id") or "")
        ]
        record = records[-1] if records else {}
        expected_fields = {
            "manuscript_input_fingerprint": info["input_fingerprint"],
            "manuscript_binding_digest": info["binding_digest"],
            "manuscript_profile_digest": info["profile_digest"],
            "manuscript_context_digest": info["context_digest"],
            "manuscript_readiness_digest": info["readiness_digest"],
            "manuscript_brief_bundle_digest": info["brief_bundle_digest"],
        }
        for field, expected in expected_fields.items():
            if str(record.get(field) or "") != str(expected):
                reasons.append(f"input_digest_mismatch:{field}")
        if mode == "enforce" and not bool(record.get("manuscript_bound", False)):
            reasons.append("candidate_not_manuscript_bound")

        tex_ref = self._winner_tex_ref(node)
        tex_path = Path(tex_ref) if tex_ref else Path()
        text = ""
        artifact_digest = ""
        try:
            from ari.manuscript.digest import path_has_symlink_component

            absolute = Path(os.path.abspath(tex_path))
            absolute.relative_to(ckpt.resolve())
            if (
                not absolute.is_file()
                or absolute.is_symlink()
                or path_has_symlink_component(ckpt.resolve(), absolute)
            ):
                raise OSError("unsafe candidate path")
            raw = absolute.read_bytes()
            artifact_digest = hashlib.sha256(raw).hexdigest()
            if artifact_digest != str(record.get("tex_sha256") or ""):
                reasons.append("candidate_artifact_digest_mismatch")
            text = raw.decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            reasons.append("invalid_candidate_artifact")

        contextual_negative_mentions = [
            evidence_id
            for evidence_id in info.get("contextual_negative_ids", ())
            if self._contains_manuscript_evidence_id(text, evidence_id)
        ]
        reasons.extend(
            f"contextual_negative_evidence:{evidence_id}"
            for evidence_id in contextual_negative_mentions
        )
        forbidden_mentions = [
            evidence_id
            for evidence_id in info.get("forbidden_evidence_ids", ())
            if self._contains_manuscript_evidence_id(text, evidence_id)
        ]
        reasons.extend(
            f"forbidden_evidence:{evidence_id}"
            for evidence_id in forbidden_mentions
        )
        normalised_draft = self._normalise_disclosure_text(text)
        missing_disclosures = [
            disclosure
            for disclosure in info.get("required_disclosures", ())
            if self._normalise_disclosure_text(disclosure) not in normalised_draft
        ]
        reasons.extend("missing_required_disclosure" for _ in missing_disclosures)

        gate_report: dict = {}
        if text:
            try:
                from ari.pipeline.claim_gate.gate import run_hard_gate
                from ari.public.manuscript import canonical_digest

                def _json_artifact(name: str) -> dict:
                    path = ckpt / name
                    try:
                        value = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        return {}
                    return value if isinstance(value, dict) else {}

                gate_report = run_hard_gate(
                    ckpt,
                    paper_tex=text,
                    science_data=_json_artifact("science_data.json"),
                    figures_manifest=_json_artifact("figures_manifest.json"),
                    policy={"mode": "strict"},
                    phase="draft",
                    write=False,
                )
                for finding in gate_report.get("blocking_findings", ()) or ():
                    finding_type = str((finding or {}).get("type") or "unknown")
                    reasons.append(f"claim_gate:{finding_type}")
                gate_digest = canonical_digest(gate_report)
            except Exception as exc:
                reasons.append(f"candidate_gate_error:{type(exc).__name__}")
                gate_digest = ""
        else:
            gate_digest = ""

        reasons = list(dict.fromkeys(reasons))
        disqualified = mode == "enforce" and bool(reasons)
        metrics["_manuscript_hard_disqualified"] = disqualified
        metrics["_manuscript_hard_disqualification_reasons"] = tuple(reasons)
        metrics["_manuscript_input_fingerprint"] = str(
            info["input_fingerprint"]
        )
        if disqualified:
            metrics["_valid_for_frontier"] = False
        evaluation = {
            "manuscript_candidate_status": (
                "hard_disqualified"
                if disqualified
                else "audit_findings"
                if reasons
                else "admissible"
            ),
            "manuscript_hard_disqualified": disqualified,
            "manuscript_hard_disqualification_reasons": reasons,
            "manuscript_candidate_artifact_sha256": artifact_digest,
            "manuscript_candidate_gate_digest": gate_digest,
            "manuscript_candidate_gate_status": str(
                gate_report.get("status") or "not_run"
            ),
            "manuscript_contextual_negative_evidence_mentions": (
                contextual_negative_mentions
            ),
            "manuscript_forbidden_evidence_mentions": forbidden_mentions,
            "manuscript_missing_required_disclosures": missing_disclosures,
        }
        record_paper_draft_manuscript_evaluation(
            ckpt,
            str(getattr(node, "id", "")),
            epoch_id=str(metrics.get("_paper_epoch_id") or ""),
            evaluation=evaluation,
        )
        return node

    def _make_paper_root(self, best_node) -> "Node":
        """A synthetic depth-0 ``Node`` wrapping the exploration winner. It is
        NOT a draft and is never scored — ``select_best_to_expand`` ranks it by
        the seeds-first rule (§5.2), not by a ``_scientific_score`` it lacks."""
        from ari.orchestrator.node import Node, NodeLabel

        root = Node(id="paper_root", parent_id=None, depth=0, label=NodeLabel.DRAFT)
        root.original_direction = "root"
        root.has_real_data = False
        if best_node is not None:
            root.ancestor_ids = list(getattr(best_node, "ancestor_ids", []) or [])
            root.metrics = {"_seed_node_id": getattr(best_node, "id", "")}
        return root

    def _build_experiment(
        self, experiment_data, all_nodes, ckpt, *,
        writer_hash: str = "founding", writer_text: str = "",
    ) -> dict:
        """Frozen paper-task inputs (paths to the verified context / science
        data / figures / refs). Best-effort — the skill tolerates empties.

        ``writer_hash`` is the epoch's ACTIVE paper_writer framing (Task 03
        supplies the population; a single founding framing before co-evolution,
        so seed diversity is decode-seed only); ``writer_text`` is the governed
        paper_writer prompt bytes threaded to the skill as
        ``writer_prompt_override`` (§5.8)."""
        try:
            from ari.pipeline.verified_context import write_verified_context

            write_verified_context(ckpt, all_nodes)
        except Exception:
            log.debug("verified_context build failed (best-effort)", exc_info=True)

        def _p(name: str) -> str:
            p = ckpt / name
            return str(p) if p.exists() else ""

        nodes_json = ckpt / "nodes_tree.json"
        if not nodes_json.exists():
            nodes_json = ckpt / "tree.json"
        pe = getattr(getattr(self.cfg, "rqgm", None), "paper", None)
        pe_enabled = bool(
            getattr(getattr(pe, "prompt_evolution", None), "enabled", True)
        )
        experiment_summary = experiment_data.get("goal", "")
        manuscript_record: dict = {}
        manuscript_fixed_block = ""
        manuscript_mode = self._manuscript_runtime_mode()
        if manuscript_mode != "off":
            info = self._manuscript_inputs or self._prepare_manuscript_archive_binding(
                Path(ckpt)
            )
            if info is None:
                raise ManuscriptArchiveAuthoringError(
                    "manuscript archive lacks a prepared input binding"
                )
            manuscript_record = {
                key: value for key, value in info.items()
                if not key.startswith("_") and key != "stale"
            }
            if manuscript_mode == "enforce":
                from ari.public.manuscript import render_brief_bundle

                rendered = render_brief_bundle(info["_briefs"])
                manuscript_fixed_block = "\n".join((
                    "══ IMMUTABLE MANUSCRIPT ARCHIVE INPUT ══",
                    f"input_fingerprint: {info['input_fingerprint']}",
                    f"binding_digest: {info['binding_digest']}",
                    f"profile_digest: {info['profile_digest']}",
                    f"context_digest: {info['context_digest']}",
                    f"readiness_digest: {info['readiness_digest']}",
                    f"brief_bundle_digest: {info['brief_bundle_digest']}",
                    rendered,
                    "Do not alter evidence lanes, readiness, required disclosures, "
                    "or the fixed digests above.",
                    "══ END IMMUTABLE MANUSCRIPT ARCHIVE INPUT ══",
                ))
                experiment_summary = manuscript_fixed_block
        return {
            "goal": experiment_data.get("goal", ""),
            "experiment_summary": experiment_summary,
            "verified_context_json": _p("verified_context.json"),
            "science_data_json": _p("science_data.json"),
            "figures_manifest_json": _p("figures_manifest.json"),
            "refs_json": _p("related_refs.json"),
            "nodes_json_path": str(nodes_json) if nodes_json.exists() else "",
            "venue": "arxiv",
            "author_name": "",
            "writer_prompt_hashes": [str(writer_hash or "founding")],
            "writer_prompt_text": str(writer_text or ""),   # §5.8 override
            "prompt_evolution_enabled": pe_enabled,
            "manuscript_binding": manuscript_record,
            "manuscript_fixed_block": manuscript_fixed_block,
        }

    # ── co-evolution helpers (inner RQGM machinery reuse) ───────────────
    def _epoch_rounds(self) -> int:
        ep = getattr(getattr(getattr(self.cfg, "rqgm", None), "paper", None),
                     "epoch", None)
        try:
            return max(1, int(getattr(ep, "rounds", 2)))
        except (TypeError, ValueError):
            return 2

    def _freeze_paper_utility_policy(self, ckpt) -> None:
        """Freeze the ``paper_utility_policy`` (Task 04 §5.5) into
        ``paper_archive_state.json``. Content-only hash (P2): the
        ``WRITER_ANCHOR_DESCRIPTOR`` (§5.1, revised 2026-07-16 — the writer IS
        anchored, to the Layer-0 claim-evidence gate), the anchor identity, and
        BOTH label-source mixes, so a drift toward self-labelling moves the
        frozen epoch identity. ``paper_epoch_fingerprint`` is that policy hash
        (``hash12(canonical_json(paper_utility_policy))``, Task 04 §6.3 as
        landed): it changes iff the anchor identity changes, which is §5.5's
        biconditional. Rides Task 14's governed capture; no paper-local utility
        machinery. A resume against a mutated corpus is DETECTED and warned, not
        silently flipped (§8.5 / §9 Resume). Best-effort — never raises into the
        run."""
        try:
            from ari.rqgm.paper_anchor import capture_paper_utility_policy

            pool = self._anchor_pool
            policy = capture_paper_utility_policy(
                self.cfg,
                corpus_digest=getattr(pool, "corpus_digest", ""),
                held_out_ids=list(getattr(pool, "held_out_ids", []) or []),
                label_source_mix=dict(getattr(pool, "label_source_mix", {}) or {}),
                held_out_label_source_mix=dict(
                    getattr(pool, "held_out_label_source_mix", {}) or {}
                ),
            )
            state = read_paper_archive_state(ckpt) or {}
            prior = state.get("paper_utility_policy") or {}
            prior_hash = str(prior.get("paper_utility_policy_hash", "") or "")
            new_hash = str(policy["paper_utility_policy_hash"])
            if prior_hash and prior_hash != new_hash:
                # §8.5 / §9 Resume: a corpus (or anchor-config) swap across a
                # resume is DETECTED and announced — never a silent mid-run
                # policy flip. Journal the superseded policy so the flip stays
                # DIFFABLE; the bare overwrite alone would destroy the record.
                log.warning(
                    "resume: paper utility policy digest mismatch — persisted "
                    "%s (corpus_digest=%s, held_out=%d) vs freshly captured %s "
                    "(corpus_digest=%s, held_out=%d); the anchor corpus or "
                    "anchor config changed across invocations (plan 04 §8.5)",
                    prior_hash, prior.get("anchor_corpus_digest", ""),
                    len(prior.get("anchor_held_out_ids", []) or []),
                    new_hash, policy.get("anchor_corpus_digest", ""),
                    len(policy.get("anchor_held_out_ids", []) or []),
                )
                state.setdefault("paper_utility_policy_journal", []).append(
                    {"event": "policy_digest_mismatch",
                     "prior_paper_utility_policy": prior,
                     "new_paper_utility_policy_hash": new_hash}
                )
            state["paper_utility_policy"] = policy
            state["paper_epoch_fingerprint"] = new_hash
            write_paper_archive_state(ckpt, state)
        except Exception:
            log.warning("paper utility policy freeze failed (best-effort)",
                        exc_info=True)

    def _build_inner_rqgm(self, ckpt, mcp):
        """The inner ``RQGMRuntime`` (paper_phase) whose kernel / store /
        governance / transition engine drive the boundary VERBATIM. ``None``
        when construction fails (=> the substrate-only single round)."""
        try:
            from ari.rqgm.runtime import RQGMRuntime

            rt = RQGMRuntime(
                self.cfg, ckpt, llm=self.llm, mcp=mcp, paper_phase=True,
                anchor_pool=self._anchor_pool,
                paper_candidate_evaluator=self._paper_candidate_evaluator,
            )
            if rt.kernel is None:
                return None
            return rt
        except Exception:
            log.warning("inner RQGMRuntime construction failed; paper archive "
                        "runs without co-evolution", exc_info=True)
            return None

    def _resolve_active(self, st, ckpt, round_idx):
        """``(epoch_id, reviewer_hash, reviewer_text, writer_hash,
        writer_text)`` for the round — the epoch-FROZEN active governed
        prompts. Falls back to the founding bytes when the registry is
        unavailable."""
        epoch_id = (
            str(getattr(getattr(st, "epoch", None), "epoch_id", ""))
            or f"epoch_{round_idx:03d}"
        )
        r_hash, r_text = self._active_prompt(st, ckpt, "paper_reviewer",
                                             "rqgm/paper_reviewer")
        w_hash, w_text = self._active_prompt(st, ckpt, "paper_writer",
                                             "rqgm/paper_writer")
        return epoch_id, r_hash, r_text, w_hash, w_text

    def _active_prompt(self, st, ckpt, role, founding_key):
        """``(prompt_hash, text)`` of the role's ACTIVE governed prompt (the
        latest-active rollup), resolved to bytes; founding bytes on any gap."""
        try:
            prompts = getattr(st, "prompts", None)
            if prompts is not None:
                active = prompts.active_prompt_hashes().get(role)
                if active:
                    for pid, entry in prompts.entries().items():
                        if (str(getattr(entry, "role", "")) == role
                                and str(getattr(entry, "prompt_hash", ""))
                                == active):
                            text, h = prompts.resolve_text(
                                pid, checkpoint_dir=ckpt
                            )
                            return h, text
        except Exception:
            log.debug("active prompt resolve failed for %s (founding bytes)",
                      role, exc_info=True)
        from ari.prompts import FilesystemPromptLoader

        text, h = FilesystemPromptLoader().load_versioned(founding_key)
        return h, text

    def _build_reviewer(self, prompt_text, prompt_hash, ckpt, epoch_id):
        if self._reviewer_override is not None:
            return self._reviewer_override
        return GovernedPaperReviewer(
            prompt_text=prompt_text, prompt_hash=prompt_hash,
            checkpoint_dir=ckpt, epoch_id=epoch_id,
            score_fn=self._reviewer_score_fn,
            revise_fn=self._reviewer_revise_fn,
            verdict_fn=self._reviewer_verdict_fn,
            confidence_fn=self._reviewer_confidence_fn,
        )

    def _score_reviewer_on_anchor(self, reviewer, *, rqgm=None, epoch_id="",
                                  checkpoint_dir=None):
        """Populate the anchor pool's per-case ``results`` for the ACTIVE
        reviewer and emit one review_record per held-out case (§5.8 / §5.4).

        The anchor's job is (a) score the reviewer's utility (Task 04), (b) set
        the reviewer's agreement rate so its DRAFT review_records inherit the
        anchor trust signal, and (c) supply the adversary's pre-signal — WHICH
        over-accepted drafts to attack. It NEVER manufactures a
        ValidatedAttackRecord. The over-accepted adversarial round itself is
        fired by the caller AFTER the drafts are built (so the writer-
        culpability signal is available); see :meth:`_attack_over_accepted`.
        A disagreeing reviewer scores 0 on the anchor board (=> board-low) and
        low agreement (=> reliability below floor)."""
        pool = self._anchor_pool
        if pool is None or not getattr(pool, "anchor_cases", None):
            return
        from ari.rqgm.budget import BudgetedAction, PAPER_ANCHOR_SCORING
        from ari.rqgm.paper_anchor import (
            paper_reviewer_agreement,
            reviewer_anchor_cases,
        )

        # The REVIEWER's corpus cases only: the pool also carries the writer's
        # claim-gate faithfulness cases (§5.1), which are a different subject's
        # anchor — scoring the reviewer against one would count as a miss and
        # dilute its agreement with evidence that is not its ground truth.
        corpus_cases = reviewer_anchor_cases(pool)

        # Task 06 §5.3/§5.5: anchor-agreement utility is the ONE additive
        # budgeted-action kind. Gate each held-out case scored against
        # `rqgm.paper.anchor.sample_size` (per-candidate). Fail-open: budget
        # exhaustion DEGRADES (stops scoring further cases), never raises and
        # never blocks best-belief selection — the reviewer keeps whatever
        # agreement the scored prefix gives it.
        bm = self.budget_manager
        # None => no confidence source is wired => the anchor review_records
        # carry NO confidence key and `calibration_error` stays ABSENT. NEVER a
        # constant: an anchor record's outcome_score IS its agreement, so any
        # pinned confidence makes calibration a restatement of agreement (see
        # `GovernedPaperReviewer.stated_confidence`).
        conf = reviewer.stated_confidence() if hasattr(
            reviewer, "stated_confidence") else None
        hits = 0
        total = 0
        for case in corpus_cases:
            if bm is not None:
                verdict = bm.gate(
                    BudgetedAction(PAPER_ANCHOR_SCORING),
                    node_id=str(case.get("case_id", "")),
                )
                if not verdict.allowed:
                    break                       # sample_size budget spent
                bm.consume(BudgetedAction(PAPER_ANCHOR_SCORING))
            try:
                rec = reviewer.anchor_verdict(case) if hasattr(
                    reviewer, "anchor_verdict") else None
            except Exception:
                rec = None
            if rec is None:
                # NO VERDICT SOURCE => this case is not coverage. Skip it
                # entirely: do not count it in `total`, do not stamp a board
                # result, do not emit a review_record. Scoring it would binarize
                # to a MISS and manufacture a 0.0 anchor board out of an absence
                # — impeaching the reviewer on evidence nobody produced. With
                # `total` left at 0 the guard below correctly leaves
                # `_anchor_agreement` unset (zero coverage, §5.9 on-ramp).
                continue
            agree = 1.0 if paper_reviewer_agreement(
                {"accept_recommendation": rec}, case) else 0.0
            hits += int(agree)
            total += 1
            case.setdefault("results", {})[reviewer.prompt_hash] = agree
            if hasattr(reviewer, "_append_review_record"):
                # A stated-confident anchor verdict that misses ground truth is
                # the "synthetically mis-calibrated reviewer double" (§9): a
                # high stated confidence far from the outcome (agreement) drives
                # calibration_error high.
                reviewer._append_review_record(
                    node_id=str(case.get("case_id", "anchor")),
                    outcome_score=agree, confidence=conf, agreement=agree,
                )
        if total and hasattr(reviewer, "set_anchor_agreement"):
            reviewer.set_anchor_agreement(hits / total)

    def _writer_draft_unfaithful(self, best, ckpt, *, writer_hash="",
                                 epoch_id="") -> bool:
        """Score the ACTIVE writer's best draft against the Layer-0 claim-
        evidence hard gate, LAND the score on the anchor board (keyed on
        *writer_hash*), and return whether the draft is UNFAITHFUL (§5.1,
        revised 2026-07-16).

        The gate stays Layer-0: ``run_hard_gate(write=False)`` READS the draft
        against the run's ``science_data.json`` deterministically (no LLM, no
        wall clock) and is NEVER wrapped or evolved — exactly as the adversarial
        pre-signals already read it. Absent science_data (nothing to verify
        against) => faithful (no writer sanction). Fail-open: any error degrades
        to faithful, never a crash into the paper phase and never a spurious
        sanction. Stores the faithfulness score for the §11 self-check."""
        try:
            if best is None:
                return False
            arts = getattr(best, "artifacts", None) or []
            if not arts:
                return False
            tex = Path(arts[0])
            science_path = Path(ckpt) / "science_data.json"
            if not tex.exists() or not science_path.exists():
                return False
            science_data = json.loads(
                science_path.read_text(encoding="utf-8")
            )
            links = None
            links_path = Path(ckpt) / "paper_claim_links.json"
            if links_path.exists():
                try:
                    links = json.loads(links_path.read_text(encoding="utf-8"))
                except Exception:
                    links = None
            from ari.pipeline.claim_gate.gate import run_hard_gate
            from ari.rqgm.paper_anchor import (
                WRITER_FAITHFULNESS_THRESHOLD,
                draft_is_unfaithful,
                writer_faithfulness_score,
            )

            report = run_hard_gate(
                ckpt,
                paper_tex=tex.read_text(encoding="utf-8"),
                science_data=science_data,
                paper_claim_links=links,
                write=False,               # Layer-0 read-only: never persists
                phase="draft",
            )
            score = writer_faithfulness_score(report)
            self._last_writer_faithfulness = score
            # Land the score on the ANCHOR BOARD keyed on the active writer's
            # prompt_hash (§5.1). This is what makes the writer's anchor
            # OPERATIVE: `adjudicate_motion` board-scores the writer's
            # impeachment motion off this case, so an unfaithful incumbent is
            # board-LOW and its motion is upheld instead of dismissed "in favor
            # of the incumbent" (a `None` board cannot clamp). Without it the
            # faithfulness was computed and discarded, the writer's role never
            # opened, and its shadow successor waited forever.
            if self._anchor_pool is not None and writer_hash:
                self._anchor_pool.record_writer_faithfulness(
                    prompt_hash=writer_hash, score=score, epoch_id=epoch_id,
                )
            return draft_is_unfaithful(
                report, threshold=WRITER_FAITHFULNESS_THRESHOLD
            )
        except Exception:
            log.warning("writer draft faithfulness scoring failed "
                        "(fail-open => faithful)", exc_info=True)
            return False

    def _self_preference_cfg(self):
        return getattr(
            getattr(getattr(self.cfg, "rqgm", None), "paper", None),
            "self_preference", None,
        )

    def _attack_over_accepted(self, reviewer, pool, *, rqgm, epoch_id,
                              checkpoint_dir, writer_unfaithful=False):
        """Fire a REAL paper_self_preference adversarial round per over-accepted
        draft (plan 05 §5.2). Deterministic pre-signal, LLM attack/defense/
        adjudication, Task-15 target binding to ``paper_reviewer_v1`` — and,
        when *writer_unfaithful* (the active writer's draft failed the Layer-0
        claim gate, §5.1), ALSO to ``paper_writer_v1`` (the over-accepted-AND-
        unfaithful draft has two culpable components). Best-effort: never raises
        into the paper phase."""
        try:
            from ari.rqgm.evaluation.paper_ablation import posture_from_config

            posture = posture_from_config(self.cfg)
        except Exception:
            posture = None
        if posture is not None and not posture.adversarial_pool:
            return
        sp = self._self_preference_cfg()
        if sp is not None and not bool(getattr(sp, "enabled", True)):
            return
        if rqgm is None or checkpoint_dir is None:
            return
        try:
            from ari.rqgm.paper_anchor import reviewer_anchor_cases
            from ari.rqgm.paper_self_preference import (
                _held_out_sample,
                compute_self_preference_margin,
                over_accepted_cases,
            )

            # The over-acceptance pre-signal + the AI-vs-human population
            # margin are statistics over the REVIEWER's reference corpus; the
            # pool's writer faithfulness cases (§5.1) are a different subject's
            # anchor and must not enter either sample.
            cases = reviewer_anchor_cases(pool)
            over = over_accepted_cases(reviewer, cases)
            if not over:
                return
            accept_threshold = float(getattr(sp, "accept_threshold", 0.6))
            margin_threshold = float(getattr(sp, "margin", 0.1))
            sample_size = int(getattr(sp, "sample_size", 8))
            # Population AI-vs-human statistic + the {ckpt}/rqgm/ evidence
            # artifact the pre-signal cites (0.0 when the corpus has no split).
            population_margin = compute_self_preference_margin(
                reviewer, cases, sample_size=sample_size, epoch_id=epoch_id,
                checkpoint_dir=checkpoint_dir,
            )
            adv_round = self._self_preference_round(rqgm, checkpoint_dir)
            if adv_round is None:
                return
            # Task 06 §5.3/§5.5: the paper_self_preference adversary is an
            # ADVERSARY_CALL — REUSED verbatim, capped per epoch at
            # `rqgm.adversarial.max_adversary_calls_per_epoch` (24). Gate each
            # round so a runaway anchor never spends past the shared adversary
            # budget; fail-open (degrade => stop attacking, never block).
            from ari.rqgm.budget import ADVERSARY_CALL, BudgetedAction

            bm = self.budget_manager
            # Task 06 §5.1/§5.6 / D1 (single schema home): the attacked
            # population is the held-out sample (`rqgm.paper.self_preference.
            # sample_size`, plan 05 §5.3), and the dispatch count is bounded ONLY
            # by the shared adversary cap in the gate below
            # (`rqgm.adversarial.max_adversary_calls_per_epoch`) — no un-homed
            # literal. Deterministic (`_held_out_sample` sorts by case_id).
            for case in _held_out_sample(over, sample_size):
                if bm is not None:
                    verdict = bm.gate(
                        BudgetedAction(ADVERSARY_CALL),
                        node_id=str(case.get("case_id", "")),
                    )
                    if not verdict.allowed:
                        break                   # per-epoch adversary cap spent
                    bm.consume(BudgetedAction(ADVERSARY_CALL))
                node = self._over_accepted_node(
                    case, epoch_id=epoch_id,
                    accept_threshold=accept_threshold,
                    margin_threshold=margin_threshold,
                    population_margin=population_margin,
                    writer_unfaithful=writer_unfaithful,
                )
                adv_round.run(node, paper_candidate=True)
        except Exception:
            log.warning("paper self-preference round failed (fail-open)",
                        exc_info=True)

    def _self_preference_round(self, rqgm, checkpoint_dir):
        """The paper self-preference :class:`AdversarialRound`, built once per
        runtime over the ``rqgm.adversarial`` slice and the adversary LLM seam,
        reading the epoch-FROZEN active component map so ``target_component_id``
        resolves to the incumbent ``paper_reviewer`` (Task 15)."""
        if self._selfpref_round is not None:
            return self._selfpref_round
        try:
            from ari.rqgm.adversarial import AdversarialRound

            adv_llm = (
                self._adversary_llm if self._adversary_llm is not None
                else self.llm
            )
            self._selfpref_round = AdversarialRound(
                getattr(getattr(self.cfg, "rqgm", None), "adversarial", None),
                llm=adv_llm,
                checkpoint_dir=checkpoint_dir,
                epoch_state=lambda: rqgm.current_epoch,
            )
        except Exception:
            log.warning("paper self-preference round construction failed",
                        exc_info=True)
            self._selfpref_round = None
        return self._selfpref_round

    @staticmethod
    def _over_accepted_node(case, *, epoch_id, accept_threshold,
                            margin_threshold, population_margin,
                            writer_unfaithful=False):
        """A synthetic ``paper_claim`` node for one over-accepted anchor draft.
        Its reserved paper metrics drive ``_pre_paper_self_preference``: the
        reviewer ACCEPTED it, and the DIRECT per-draft anchor over-acceptance
        (``_paper_anchor_over_accepted_case``) is the signal — the population
        AI-vs-human ``_self_preference_margin`` rides alongside BY VALUE and
        fires signal 2 only when the corpus genuinely carries an authorship
        split. The node is transient — the
        in-phase penalty on it has no archive effect; this round exists for the
        reviewer's (and, when *writer_unfaithful*, the writer's) ACCOUNTABILITY,
        not to demote a real draft.

        ``_paper_writer_unfaithful`` carries the active writer's OWN draft
        faithfulness (Layer-0 claim gate, §5.1): when set, the round ALSO binds
        ``paper_writer`` to the validated attack (``round._roles_for_node``), so
        the writer's role opens for its shadow successor. A faithful draft binds
        the reviewer only."""
        case_id = str(case.get("case_id", "anchor"))
        metrics = {
            "_scientific_score": 1.0,
            "_paper_self_preference_candidate": True,
            "_reviewer_accept_score": 1.0,
            "_self_preference_accept_threshold": float(accept_threshold),
            # The POPULATION AI-vs-human statistic BY VALUE, exactly as
            # `compute_self_preference_margin` computed it and exactly as
            # `paper_self_preference_stat.json` — the artifact signal 2 cites —
            # records it. A self-preference margin is a RATE in [0,1]; the
            # `max(margin, 1.0)` that stood here was therefore ALWAYS 1.0 and
            # discarded the real statistic unconditionally, so every raw_attack
            # carried an evidence ref to a file that refuted its own trigger.
            # `0.0` on an all-human corpus is the honest reading: no authorship
            # split, no population signal, signal 2 correctly silent.
            "_self_preference_margin": float(population_margin),
            "_self_preference_threshold": float(margin_threshold),
            # The DIRECT per-draft over-acceptance signal — a DIFFERENT subject
            # from the population statistic, so it carries its own key and cites
            # its own evidence (the anchor CASE). This node exists BECAUSE the
            # frozen incumbent accepted THIS anchor case whose human ground
            # truth is `reject` (`over_accepted_cases`), which is a real,
            # deterministic, per-draft fact that holds on an all-human corpus.
            # Plan 05 §5.1 clause 3, third bullet (amended 2026-07-17).
            "_paper_anchor_over_accepted_case": case_id,
        }
        if writer_unfaithful:
            metrics["_paper_writer_unfaithful"] = True
        node = SimpleNamespace(
            # The id `_selfpref_anchor_case` parses back when this draft's
            # validated attack is later replayed against a candidate reviewer
            # (the §5.5 replay board) — keep the two halves on one constant.
            id=f"{PaperArchiveRuntime._SELFPREF_NODE_PREFIX}{epoch_id}_{case_id}",
            work_dir="",
            metrics=metrics,
        )
        return node

    def _paper_candidate_evaluator(self, st, ckpt, anchor_pool,
                                   replay_pool=None):
        """Full-spine evaluations for the pending paper candidates (§5.4),
        merged into ``resolve_transition``'s candidate_evaluations exactly like
        the utility_policy criterion.

        The reviewer candidate is scored on the §5.4/§5.5 DUAL objective — two
        boards computed from two independent sources, never one number copied
        into both fields:

        * ``anchor_score`` — held-out agreement with the human corpus (the
          APReS utility), from :func:`score_reviewer_on_anchor`;
        * ``replay_score`` — the candidate's pass rate over the pooled
          ``paper_self_preference`` cases (:meth:`_candidate_replay_board`).

        A board with no basis is reported ABSENT (``None``) and carries the
        ``no_replay_basis`` sentinel, so the engine's role-scoped waiver — not a
        fabricated number — is what keeps the on-ramp candidate moving. The
        writer (no anchor, no drafts yet) is pure zero coverage. Deterministic,
        never raises."""
        from ari.rqgm.governance._adjudication import CANDIDATE_PASS_THRESHOLD
        from ari.rqgm.paper_anchor import score_reviewer_on_anchor
        from ari.rqgm.prompt_evolution import (
            constitutional_validation_failures,
            role_instruction_constraint_failures,
            static_validation_failures,
        )
        from ari.rqgm.prompt_records import (
            candidate_from_dict,
            load_prompt_evolution_log,
        )
        from ari.rqgm.transition_engine import (
            NO_REPLAY_BASIS_KEY,
            NO_SHADOW_BASIS_KEY,
        )

        out: list = []
        prompts = getattr(st, "prompts", None)
        if prompts is None:
            return out
        # The candidate SPECs that the two spec-dependent deterministic stages
        # (static_validation, constitutional_validation) need are carried only by
        # the append-only ``prompt_evolution.jsonl`` — a GovernedPromptEntry is
        # text-only (registry.py:80). Reconstruct them once, keyed by
        # ``candidate_id`` (== the registry ``prompt_id``, prompt_evolution.py:
        # 1177/1186): this closes the plan 03 §5.9 step-2 residual verbatim
        # ("reconstructing the candidate spec from the evolution log"). A pending
        # entry with no matching record cannot be spec-checked, so those two
        # stages are then an explicit skip — never a fabricated pass.
        try:
            cand_records = {
                str(r.get("candidate_id", "")): r
                for r in load_prompt_evolution_log(ckpt)
                if str(r.get("record_type", "")) == "prompt_candidate"
            }
        except Exception:
            log.debug("prompt_evolution log read failed (spec stages skip)",
                      exc_info=True)
            cand_records = {}
        for pid, entry in (prompts.entries() or {}).items():
            role = str(getattr(entry, "role", ""))
            status = str(getattr(entry, "status", ""))
            if role not in ("paper_reviewer", "paper_writer"):
                continue
            if status not in ("candidate", "validated", "shadow"):
                continue
            try:
                text, phash = prompts.resolve_text(pid, checkpoint_dir=ckpt)
            except Exception:
                continue
            # ── deterministic candidate-validation stages (plan 03 §5.9 step 2)
            # Run monotonically BEFORE any board scores the candidate, in the
            # order the six-stage lifecycle states (static_validation ->
            # constitutional_validation -> schema_dry_run). A candidate that fails
            # ANY stage is DROPPED (``continue``) — it never enters
            # ``candidate_evaluations``, so no board score can carry it up the
            # role-agnostic T1/T3/T6 spine to ``active``. Every check REUSES the
            # parent set's pure-function stage (``prompt_evolution.py``), so there
            # is exactly one definition of each stage — never a paper-local copy.
            # These stages are what the never-instantiated
            # ``CandidateValidationPipeline`` was documented to run but never did.
            cand_rec = cand_records.get(str(pid))
            cand = candidate_from_dict(cand_rec) if cand_rec else None
            if cand is not None:
                # Stage 1 — static_validation (deterministic, ALWAYS): placeholder
                # contract vs the declared input_contract, hash discipline,
                # template_ref/generation_mode/mutation_kind legality, size
                # budget, and lineage. Needs the candidate spec, hence the log
                # reconstruction above.
                static_fail = static_validation_failures(cand, text)
                if static_fail:
                    log.warning(
                        "paper candidate %s (%s) DROPPED before scoring: "
                        "static_validation failed %s — never enters "
                        "candidate_evaluations (plan 03 §5.9 step 2)",
                        pid, role, static_fail,
                    )
                    continue
                # Stage 2 — constitutional_validation (deterministic, ALWAYS),
                # METADATA side: the declared ``constitutional_constraints`` carry
                # the §5.4 clauses, provenance legality, no-instant-activation,
                # and same-role separation. The byte-side companion is the
                # role_instruction check just below.
                const_fail = constitutional_validation_failures(cand)
                if const_fail:
                    log.warning(
                        "paper candidate %s (%s) DROPPED before scoring: "
                        "constitutional_validation failed %s — never enters "
                        "candidate_evaluations (plan 03 §5.9 step 2)",
                        pid, role, const_fail,
                    )
                    continue
            # Stage 2 (byte side) — constitutional binding on the RESOLVED
            # role_instruction BYTES (plan 03 §5.9 step 2 / 05 §5.5). The
            # metadata-side check above reads the declared constraint list, which
            # PromptMutator.propose force-injects (prompt_evolution.py:681-686),
            # so the LOAD-BEARING check is that the instruction bytes still carry
            # each §5.4 clause verbatim; both share REQUIRED_CONSTRAINTS_BY_ROLE
            # (one authority). This runs even without a reconstructed spec, so it
            # is the pillar-4 gate on every pending paper candidate.
            missing = role_instruction_constraint_failures(role, text)
            if missing:
                log.warning(
                    "paper candidate %s (%s) DROPPED before scoring: resolved "
                    "role_instruction is missing mandatory §5.4 constitutional "
                    "clause(s) %s — never enters candidate_evaluations "
                    "(pillar-4 constitutional binding; plan 03 §5.9 step 2)",
                    pid, role, missing,
                )
                continue
            # Stage 3 — schema_dry_run (LLM-GATED): render the candidate prompt to
            # a reply and check it against the role's founding output_schema. It
            # is a non-deterministic, budgeted LLM call, INCOMPATIBLE with this
            # deterministic (P2) evaluator's default path, so it RUNS only when an
            # LLM reply seam is injected and is a documented SKIP otherwise
            # (production injects none — cli/projects.py:219). A skip is NEVER a
            # fabricated pass. On a schema-nonconforming reply the candidate is
            # DROPPED (terminal, per the lifecycle docstring).
            schema_fail = self._schema_dry_run_failures(role, text)
            if schema_fail:
                log.warning(
                    "paper candidate %s (%s) DROPPED before scoring: "
                    "schema_dry_run reply failed the founding output_schema %s "
                    "(plan 03 §5.9 step 2)",
                    pid, role, schema_fail,
                )
                continue
            if role == "paper_reviewer" and anchor_pool is not None:
                cand_reviewer = GovernedPaperReviewer(
                    prompt_text=text, prompt_hash=phash,
                    verdict_fn=self._reviewer_verdict_fn,
                )
                acc, anchor_refs = score_reviewer_on_anchor(
                    anchor_pool, cand_reviewer.anchor_verdict
                )
                replay, replay_refs = self._candidate_replay_board(
                    cand_reviewer, replay_pool, anchor_pool
                )
                if acc is None and replay is None:
                    # Genuine zero coverage on BOTH boards (§5.5's bootstrap
                    # on-ramp: no anchor corpus and no pooled case yet).
                    out.append(self._no_basis_eval(pid, role))
                    continue
                # Both boards required (§5.4's dual constraint): the candidate
                # clears CANDIDATE_PASS_THRESHOLD on every board that HAS a
                # basis. A board without one abstains — it never votes pass.
                scored = [s for s in (acc, replay) if s is not None]
                verdict = (
                    "pass" if min(scored) >= CANDIDATE_PASS_THRESHOLD
                    else "fail"
                )
                out.append({
                    "prompt_id": pid, "role": role, "verdict": verdict,
                    # Two boards, two sources. `replay_score` is the pooled
                    # self-preference pass rate and `anchor_score` the held-out
                    # corpus agreement; neither is ever a copy of the other, and
                    # a board without a basis is `None`, never a stand-in.
                    "replay_score": replay, "anchor_score": acc,
                    # The pool's OWN case_ids — the cases actually replayed.
                    "case_refs": list(replay_refs),
                    "case_count": len(replay_refs),
                    "anchor_case_refs": list(anchor_refs),
                    # No paper role is ever shadow-EXECUTED (there is no
                    # shadow-serving path in the paper phase), so the shadow
                    # stage is vacuous by construction: reported absent and
                    # waived by role, never back-filled from the anchor run.
                    # Structural and unconditional — unlike the replay board
                    # below, no pool state can ever give this stage a sample.
                    "shadow_samples": 0, "shadow_score": None,
                    NO_SHADOW_BASIS_KEY: True,
                    # The T3 replay COUNT floor is waived ONLY when the replay
                    # board is honestly ABSENT (§5.5's on-ramp: "the first paper
                    # reviewer is never blocked for lacking cases it could not
                    # yet have"). `case_refs` above are the pool's REAL case_ids
                    # — when the board HAS cases the floor has something honest
                    # to count, so it counts them. Declaring the absence
                    # unconditionally let a genuine 1-case board clear
                    # `replay_min_cases: 4`, which no plan sanctions.
                    **({NO_REPLAY_BASIS_KEY: True} if replay is None else {}),
                    "cached": False,
                })
            else:
                # The writer is scored epoch-locally by the frozen reviewer
                # (its DRAFT winners are epoch-local, §5.6), so its candidate
                # PROMPT passes the spine and climbs to `shadow`. It then WAITS
                # for a role opening — which, since §5.1 (revised 2026-07-16),
                # the claim-gate faithfulness sanction DELIVERS: an unfaithful
                # active writer is impeached, its role opens, and this waiting
                # shadow adopts via the existing T6 (the writer PROMPT
                # co-evolves).
                out.append(self._no_basis_eval(pid, role))
        return out

    def _schema_dry_run_failures(self, role: str, prompt_text: str) -> list:
        """The §5.9 step-2 ``schema_dry_run`` stage (plan 07 §5.3 stage 3),
        behind the injected LLM reply seam. Returns:

        * ``[]`` — the stage PASSED, OR it is a documented SKIP because no LLM
          reply seam is wired (``schema_dry_run_fn is None`` — the production
          wiring: ``cli/projects.py:219`` injects none). A skip is NEVER a
          fabricated pass: it means the stage did not run and the candidate
          proceeds to the boards exactly as before this wiring.
        * a non-empty list of schema failures — the injected LLM produced a reply
          that does NOT conform to the role's founding ``output_schema``; the
          caller DROPS the candidate (terminal on failure, per the lifecycle).

        The conformance check REUSES ``check_output_against_schema`` verbatim; the
        schema is the role's founding entry (:func:`_paper_founding_output_schema`
        over ``PAPER_FOUNDING_PROMPT_TABLE``), i.e. the SAME contract the runtime
        enforces on live replies. Deterministic given a deterministic seam; never
        raises (a seam error is a SKIP, not a fabricated pass or a drop, keeping
        the evaluator's P2 never-raise contract)."""
        fn = self._schema_dry_run_fn
        if fn is None:
            return []                      # documented no-op: no LLM reply seam
        schema = _paper_founding_output_schema(role)
        if schema is None:
            return []                      # unknown role => nothing to check
        try:
            from ari.rqgm.prompt_evolution import check_output_against_schema

            reply = fn(role, prompt_text, dict(schema))
            return check_output_against_schema(str(reply or ""), schema)
        except Exception:
            log.debug("schema_dry_run seam raised for role %s (skipped, never a "
                      "fabricated pass)", role, exc_info=True)
            return []

    #: The synthetic node id ``_over_accepted_node`` mints for one
    #: over-accepted anchor draft — the bridge back from a pooled
    #: ``paper_self_preference`` case to the anchor case it was raised over.
    _SELFPREF_NODE_PREFIX = "selfpref_"

    @staticmethod
    def _selfpref_anchor_case(view, corpus_cases):
        """The anchor case one pooled ``paper_self_preference`` replay view was
        raised over, or ``None``.

        The pool's ``replay_view`` carries the attacked artifact by reference
        (``artifact_refs`` -> the ``selfpref_{epoch_id}_{case_id}`` node
        :meth:`_over_accepted_node` minted), never the manuscript itself, so the
        case is resolved back through the anchor corpus. Matched by longest
        ``case_id`` suffix (``epoch_id`` and ``case_id`` both contain ``_``, so
        a positional split is ambiguous); longest-wins keeps it deterministic
        when one case_id is a suffix of another. Unmatched -> ``None`` -> the
        case abstains, never a guess."""
        refs = [str(r) for r in ((view or {}).get("artifact_refs") or ())]
        best = None
        for case in corpus_cases or ():
            cid = str(case.get("case_id", ""))
            if not cid:
                continue
            for ref in refs:
                if (ref.startswith(PaperArchiveRuntime._SELFPREF_NODE_PREFIX)
                        and ref.endswith(f"_{cid}")):
                    if best is None or len(cid) > len(str(
                            best.get("case_id", ""))):
                        best = case
        return best

    def _candidate_replay_board(self, cand_reviewer, replay_pool, anchor_pool):
        """The REAL §5.4/§5.5 dual-objective replay board for a candidate
        ``paper_reviewer``: the pooled ``paper_self_preference`` cases — drafts
        the INCUMBENT reviewer over-accepted and the adversarial round then
        validated — re-judged by the CANDIDATE. A case PASSES iff the candidate
        REJECTS the draft its incumbent accepted, which is precisely "a
        candidate that flags the pooled AI paper clears ``replay_evaluation``".

        This is the read side the pool never had: until now the paper phase
        ADMITTED self-preference cases (``_admit_paper_validated_attacks``) and
        never selected from them, so the pool was a write-only sink and the
        "dual objective" was one anchor number copied into both fields.

        Returns ``(pass_rate, case_refs)``, or ``(None, [])`` when the pool holds
        no applicable case or none can be re-judged (no verdict source wired) —
        an explicit ABSENCE the caller declares with the ``no_replay_basis``
        sentinel, never a number nobody computed. Deterministic (the pool's own
        severity/recency/case_id order); never raises.

        The verdict source is honest as of the answer-key deletion: with no
        ``verdict_fn`` wired ``anchor_verdict`` returns ``None`` and every case
        ABSTAINS, so this board reports ABSENT rather than scoring 1.0 off the
        corpus label. A wired judge only ever sees ``anchor_case_view`` (no label
        field), so the pass here — the candidate REJECTS what the incumbent
        accepted — is earned on the manuscript, not read off the key."""
        if replay_pool is None or cand_reviewer is None:
            return None, []
        try:
            from ari.rqgm.paper_anchor import (
                binarize_recommendation,
                reviewer_anchor_cases,
            )

            max_cases = int(getattr(
                getattr(getattr(self.cfg, "rqgm", None), "replay", None),
                "max_cases_per_epoch", 8,
            ))
            selected = [
                c for c in (replay_pool.select_for_replay(max_cases) or ())
                if str(getattr(c, "case_type", "")) == "paper_self_preference"
            ]
            if not selected:
                return None, []
            corpus_cases = reviewer_anchor_cases(anchor_pool)
            hits = 0
            refs: list[str] = []
            for case in selected:
                cid = str(getattr(case, "case_id", ""))
                # `paper_reviewer` is not a clean-room role, so the full replay
                # view is permitted (pool._REPLAY_VIEW_DENIED_ROLES).
                view = replay_pool.replay_view(cid, actor_role="paper_reviewer")
                anchor_case = self._selfpref_anchor_case(view, corpus_cases)
                if anchor_case is None:
                    continue                    # unresolvable -> abstain
                rec = cand_reviewer.anchor_verdict(anchor_case)
                if rec is None:
                    continue                    # no verdict source -> abstain
                # PASS iff the candidate REJECTS what the incumbent accepted.
                # An unparseable verdict (`None`) is a MISS, never a pass — the
                # same conservative rule `paper_reviewer_agreement` applies.
                hits += int(binarize_recommendation(str(rec)) == "reject")
                refs.append(cid)
            if not refs:
                return None, []
            return round(hits / len(refs), 6), sorted(refs)
        except Exception:
            log.warning("candidate replay board failed (fail-open: the board "
                        "is reported ABSENT, never fabricated)", exc_info=True)
            return None, []

    def _no_basis_eval(self, pid, role):
        """The honest ZERO-COVERAGE evaluation for a paper candidate with no
        replay/anchor basis: a candidate PROMPT has authored no drafts and
        scored no anchor case yet (plan 03 §5.9 step 2, plan 04 §5.1/§5.9).

        Nothing is computed here, so nothing is reported: the boards are
        ``None`` and the counts are ``0``/empty — the same honest signal
        ``_case_evaluation`` emits (prompt_evolution.py:961-964) and
        ``score_reviewer_on_anchor`` returns as ``(None, [])``. BOTH count
        floors are honestly absent here, so both are declared and WAIVED by role
        at the decision site (``transition_engine.NO_REPLAY_BASIS_ROLES``): T3's
        ``replay_min_cases`` via ``no_replay_basis`` (this candidate has no
        replay board at all) and T6's ``shadow_min_samples`` via
        ``no_shadow_basis`` (no paper role is ever shadow-EXECUTED). Declared in
        the open and greppable in the transition notes, never cleared by
        synthetic refs. With ``case_refs`` empty, ``_eval_refs`` cites the
        evaluation itself (``candidate_evaluation:{pid}``) rather than cases
        that do not exist.

        The writer candidate still reaches ``shadow`` and WAITS there for the
        real claim-gate faithfulness sanction to open its role (T6's
        ``_role_opening`` guard is untouched) — the plan-required outcome, now
        without forged counts standing behind it."""
        from ari.rqgm.transition_engine import (
            NO_REPLAY_BASIS_KEY,
            NO_SHADOW_BASIS_KEY,
        )

        return {
            "prompt_id": pid, "role": role, "verdict": "pass",
            "replay_score": None, "anchor_score": None,
            "case_refs": [], "case_count": 0,
            "shadow_samples": 0, "shadow_score": None,
            NO_REPLAY_BASIS_KEY: True, NO_SHADOW_BASIS_KEY: True,
            "cached": False,
        }

    def _persist_budget_counters(self, ckpt, *, expansions: int | None = None) -> None:
        """Write the §6.3 per-epoch budget-counter mirror into
        ``paper_archive_state.json``. Counters are DERIVED from the durable
        ``rqgm_audit.jsonl`` ``budget_consumed`` lines (the same
        derive-from-records discipline ``GovernanceBudgetManager._restore``
        uses), so ``ari paper`` re-invocation never double-counts. Best-effort:
        a mirror-write failure never breaks the paper phase."""
        if expansions is None:
            expansions = self._last_expansions
        try:
            from ari.rqgm.budget import (
                ADVERSARY_CALL,
                BUDGET_CONSUMED_EVENT,
                PAPER_ANCHOR_SCORING,
                PROMPT_CANDIDATE,
            )
            from ari.rqgm.store import ImmutableAuditLog

            epoch_id = str(getattr(self.current_paper_epoch, "epoch_id", "")
                           or "paper_epoch_000")
            tallies: dict[str, int] = {}
            for line in ImmutableAuditLog.read(ckpt):
                if line.get("event_type") != BUDGET_CONSUMED_EVENT:
                    continue
                p = line.get("payload") or {}
                if str(p.get("epoch_id", "") or "") != epoch_id:
                    continue
                key = str(p.get("counter_key") or p.get("kind") or "")
                try:
                    tallies[key] = tallies.get(key, 0) + int(p.get("count", 1))
                except (TypeError, ValueError):
                    tallies[key] = tallies.get(key, 0) + 1
            counters = {
                "paper_epoch_id": epoch_id,
                "draft_expansions": int(expansions),
                "adversary_calls": tallies.get(ADVERSARY_CALL, 0),
                "anchor_scoring_calls": tallies.get(PAPER_ANCHOR_SCORING, 0),
                "prompt_candidates": {
                    "paper_writer": tallies.get(
                        f"{PROMPT_CANDIDATE}:paper_writer", 0),
                    "paper_reviewer": tallies.get(
                        f"{PROMPT_CANDIDATE}:paper_reviewer", 0),
                },
                "compiles": int(self._compiles),
            }
            state = read_paper_archive_state(ckpt) or {}
            state["budget_counters"] = counters
            write_paper_archive_state(ckpt, state)
        except Exception:
            log.debug("budget-counter mirror write failed (best-effort)",
                      exc_info=True)

    def _finalize_best(self, best, ckpt, mcp) -> Path:
        """Single lazy ``compile_paper`` gated by ``compile_threshold`` (§5.4.3
        lazy-compile guard); marks ``is_best_belief`` / ``compiled``; then hands
        the winner to :meth:`materialize_winner` for the pure copy to the
        canonical ``{ckpt}/full_paper.tex`` (the Task 07 handoff surface)."""
        arts = best.artifacts or []
        if not arts:
            return ckpt / "full_paper.tex"
        tex = Path(arts[0])
        score = float((best.metrics or {}).get("_scientific_score", 0.0))
        threshold = float(
            getattr(self.cfg.rqgm.paper.archive, "compile_threshold", 0.0)
        )
        epoch_id = str(
            (getattr(best, "metrics", None) or {}).get("_paper_epoch_id") or ""
        )
        mark_paper_draft_flags(
            ckpt, best.id, epoch_id=epoch_id or None, is_best_belief=True
        )
        if score >= threshold:
            try:
                fn = getattr(mcp, "call_tool", None) or getattr(mcp, "call", None)
                if fn is not None:
                    fn("compile_paper",
                       {"tex_dir": str(tex.parent), "main_file": tex.name})
                self._compiles += 1
                mark_paper_draft_flags(
                    ckpt, best.id, epoch_id=epoch_id or None, compiled=True
                )
            except Exception:
                log.warning("lazy compile of the best-belief draft failed",
                            exc_info=True)
        return self.materialize_winner(best, ckpt)

    # ── Task 07 handoff: pure select-and-copy (§5.1/§5.2/§7) ─────────────
    def materialize_winner(self, winner, checkpoint_dir) -> Path:
        """Materialise the archive's best draft to the canonical linear-pipeline
        input ``{ckpt}/full_paper.tex`` (docs/plans/ari_rqgm_paper/07 §5.1/§5.2).

        PURE select-and-copy — no gate call, no kernel call, no LLM, no
        re-scoring (P2 determinism at the boundary). Idempotent and resume-safe:
        a second call copies the same bytes. Fail-open (§8.3): a winner without
        a materialisable ``tex_ref`` leaves ``{ckpt}/full_paper.tex`` untouched
        so the existing ``write_paper`` output (or a prior pass) stays the
        source of truth, degrading to the linear result rather than crashing.

        The winner's ``.tex`` then flows into the EXISTING compile + Layer-0
        ``claim_evidence_hard_gate_final`` + ``finalize_paper`` tail UNCHANGED.
        Both archive-owned generation stages are kept off it: ``write_paper``
        skips itself via ``skip_if_exists: {ckpt}/full_paper.tex``
        (workflow.yaml:207), and ``paper_refine`` — which has no such guard and
        would otherwise refine over these bytes — is disabled in the handoff
        config (:data:`HANDOFF_DISABLED_STAGES`, applied in :meth:`run_archive`).
        Together those make this method the SINGLE writer of the canonical path
        (§5.4/R5); the tail then runs byte-for-byte as in a linear run. This
        method never touches the gate (the gate stays a Layer-0 sibling, §5.3)."""
        ckpt = Path(checkpoint_dir)
        dst = ckpt / "full_paper.tex"
        tex_ref = self._winner_tex_ref(winner)
        if not tex_ref:
            log.warning("materialize_winner: winner has no tex_ref; leaving "
                        "%s untouched (fail-open to linear, §8.3)", dst)
            return dst
        src = Path(tex_ref)
        try:
            if src.exists() and src.resolve() != dst.resolve():
                shutil.copyfile(src, dst)
        except OSError:
            log.warning("failed to copy the winning draft %s -> %s", src, dst,
                        exc_info=True)
        return dst

    @staticmethod
    def _winner_tex_ref(winner) -> str:
        """The winner draft's rendered ``.tex`` path (its ``artifacts[0]``, the
        per-draft ``{ckpt}/archive/<draft_id>/full_paper.tex`` of §5.4).
        Absence-tolerant: ``""`` when the winner is ``None`` / artifact-less."""
        if winner is None:
            return ""
        arts = getattr(winner, "artifacts", None) or []
        return str(arts[0]) if arts else ""
