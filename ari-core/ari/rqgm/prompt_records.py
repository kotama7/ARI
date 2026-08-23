"""Prompt-evolution record shapes + append-only persistence (RQGM Task 07 §6).

The three ``{ckpt}/prompt_evolution.jsonl`` line shapes — ``PromptCandidate``
(mutator output; candidates ONLY), ``PromptCandidateValidation`` (one per
lifecycle stage execution; the chain makes stage skipping detectable), and
``ComparisonObservation`` (shadow stage; observation-only, hashes never raw
output text) — plus the fail-open writer/reader and the derived
``prompt_specs.json`` rollup. Split out of :mod:`ari.rqgm.prompt_evolution`
(which re-exports everything here) the way Task 06 keeps its record layer in
``adversarial/records.py``.

Writer posture: lock-guarded, no-op without a resolvable checkpoint dir,
never raises into the run loop. ``created_at`` is wall-clock metadata only —
never hashed, never read by decision logic (P2).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ari.rqgm.prompt_loader import _resolve_checkpoint_dir

log = logging.getLogger(__name__)

PROMPT_EVOLUTION_FILENAME = "prompt_evolution.jsonl"
PROMPT_SPECS_FILENAME = "prompt_specs.json"
PROMPT_SPECS_SCHEMA_VERSION = 1

# Serialises appends (main-thread pipeline + worker-thread shadow
# observations) — the ``record_prompt_use`` lock discipline.
_LOCK = threading.Lock()


def _now_iso() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def format_candidate_record_id(seq: int) -> str:
    return "pcand_%05d" % int(seq)


def format_validation_record_id(seq: int) -> str:
    return "pval_%05d" % int(seq)


def format_observation_record_id(seq: int) -> str:
    return "cobs_%05d" % int(seq)


# ── records (plan 07 §6) ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PromptCandidate:
    """One proposed prompt (envelope + candidate fields). ``prompt_hash`` is
    the hash of the candidate template bytes the record is about."""

    record_id: str
    epoch_id: str
    component_id: str
    prompt_hash: str
    candidate_id: str
    role: str
    generated_by: dict = field(default_factory=dict)
    generation_mode: str = "mutation"
    mutation_kind: str = ""
    source_prompt_id: str | None = None
    failure_summary_refs: tuple[str, ...] = ()
    rationale: str = ""
    prompt_spec: dict = field(default_factory=dict)
    status: str = "candidate"
    created_at: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "record_type": "prompt_candidate",
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "candidate_id": self.candidate_id,
            "role": self.role,
            "generated_by": dict(self.generated_by),
            "generation_mode": self.generation_mode,
            "mutation_kind": self.mutation_kind,
            "source_prompt_id": self.source_prompt_id,
            "failure_summary_refs": list(self.failure_summary_refs),
            "rationale": self.rationale,
            "prompt_spec": dict(self.prompt_spec),
            "status": self.status,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
        }


def candidate_from_dict(d: dict) -> PromptCandidate:
    return PromptCandidate(
        record_id=str(d.get("record_id", "")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        prompt_hash=str(d.get("prompt_hash", "")),
        candidate_id=str(d.get("candidate_id", "")),
        role=str(d.get("role", "")),
        generated_by=dict(d.get("generated_by") or {}),
        generation_mode=str(d.get("generation_mode", "mutation")),
        mutation_kind=str(d.get("mutation_kind", "")),
        source_prompt_id=d.get("source_prompt_id"),
        failure_summary_refs=tuple(d.get("failure_summary_refs") or ()),
        rationale=str(d.get("rationale", "")),
        prompt_spec=dict(d.get("prompt_spec") or {}),
        status=str(d.get("status", "candidate")),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(d.get("source_refs") or ()),
    )


@dataclass(frozen=True)
class PromptCandidateValidation:
    """One stage execution's result (append-only; one record per run)."""

    record_id: str
    epoch_id: str
    component_id: str
    candidate_id: str
    role: str
    prompt_hash: str
    stage: str
    passed: bool
    evaluated_by: str = ""
    case_results: tuple = ()
    metrics: dict = field(default_factory=dict)
    details: str = ""
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "final"

    def to_dict(self) -> dict:
        return {
            "record_type": "prompt_candidate_validation",
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "candidate_id": self.candidate_id,
            "role": self.role,
            "prompt_hash": self.prompt_hash,
            "stage": self.stage,
            "passed": self.passed,
            "evaluated_by": self.evaluated_by,
            "case_results": [dict(c) for c in self.case_results],
            "metrics": dict(self.metrics),
            "details": self.details,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
            "status": self.status,
        }


@dataclass(frozen=True)
class ComparisonObservation:
    """Shadow-stage side-by-side record — observation-only, NEVER an
    accusation and never a score input (plan 07 §5.3 stage 6)."""

    record_id: str
    epoch_id: str
    component_id: str
    candidate_id: str
    incumbent_id: str
    role: str
    prompt_hash: str
    input_context_hash: str = ""
    node_id: str = ""
    candidate_output_hash: str = ""
    incumbent_output_hash: str = ""
    divergence: dict = field(default_factory=dict)
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "recorded"

    def to_dict(self) -> dict:
        return {
            "record_type": "comparison_observation",
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "candidate_id": self.candidate_id,
            "incumbent_id": self.incumbent_id,
            "role": self.role,
            "prompt_hash": self.prompt_hash,
            "input_context_hash": self.input_context_hash,
            "node_id": self.node_id,
            "candidate_output_hash": self.candidate_output_hash,
            "incumbent_output_hash": self.incumbent_output_hash,
            "divergence": dict(self.divergence),
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
            "status": self.status,
        }


# ── append-only log (fail-open writer; plan 07 §6 on-disk layout) ───────────


def record_prompt_evolution_event(checkpoint_dir, record) -> None:
    """Append one record to ``{ckpt}/prompt_evolution.jsonl``.

    Fail-open like every ARI provenance writer: no resolvable checkpoint →
    silent no-op; I/O failure is logged, never raised into the run loop.
    ``created_at`` is filled at append time when empty (metadata only).
    """
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    if not payload.get("created_at"):
        payload["created_at"] = _now_iso()
    try:
        with _LOCK:
            Path(ckpt).mkdir(parents=True, exist_ok=True)
            with open(
                Path(ckpt) / PROMPT_EVOLUTION_FILENAME, "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        log.warning("prompt-evolution append failed", exc_info=True)


def load_prompt_evolution_log(checkpoint_dir) -> list[dict]:
    """Absence-tolerant reader (raw line dicts, oldest first)."""
    out: list[dict] = []
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return out
    path = Path(ckpt) / PROMPT_EVOLUTION_FILENAME
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def build_prompt_specs_rollup(records: list[dict]) -> dict:
    """Derive the ``prompt_specs.json`` snapshot from the JSONL truth.

    Deterministic pure fold (P2): candidate specs keyed by ``candidate_id``
    in first-seen order, with their passed stages and terminal-rejection
    flag. The JSONL stays the source of truth; this rollup is disposable.
    """
    specs: dict[str, dict] = {}
    for rec in records:
        rtype = rec.get("record_type")
        if rtype == "prompt_candidate":
            cid = str(rec.get("candidate_id", ""))
            if cid and cid not in specs:
                specs[cid] = {
                    "prompt_spec": dict(rec.get("prompt_spec") or {}),
                    "role": str(rec.get("role", "")),
                    "generation_mode": str(rec.get("generation_mode", "")),
                    "stages_passed": [],
                    "rejected": False,
                }
        elif rtype == "prompt_candidate_validation":
            cid = str(rec.get("candidate_id", ""))
            entry = specs.get(cid)
            if entry is None:
                continue
            stage = str(rec.get("stage", ""))
            if rec.get("passed"):
                if stage not in entry["stages_passed"]:
                    entry["stages_passed"].append(stage)
            elif stage == "schema_dry_run":
                # Terminal for the candidate (plan 07 §5.3 stage 3).
                entry["rejected"] = True
    return {"schema_version": PROMPT_SPECS_SCHEMA_VERSION, "specs": specs}


def save_prompt_specs_snapshot(checkpoint_dir) -> None:
    """Best-effort rollup rewrite at epoch boundaries / run end."""
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return
    try:
        from ari.checkpoint import save_prompt_specs_json

        save_prompt_specs_json(
            ckpt, build_prompt_specs_rollup(load_prompt_evolution_log(ckpt))
        )
    except Exception:
        log.warning("prompt_specs.json write failed", exc_info=True)
