"""Cost tracker for ARI — writes per-call logs and per-experiment summaries."""

from __future__ import annotations
import json, threading, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":            (0.0025, 0.010),
    "gpt-4o-mini":       (0.00015, 0.0006),
    "gpt-5":             (0.01, 0.04),
    "gpt-5.2":           (0.01, 0.04),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-opus":     (0.015, 0.075),
    "gpt-4":             (0.03, 0.06),
    "gpt-3.5-turbo":     (0.0005, 0.0015),
}

def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    key = next((k for k in _PRICING if k in model.lower()), None)
    if not key:
        return 0.0
    inp, out = _PRICING[key]
    return (prompt_tokens * inp + completion_tokens * out) / 1000.0

@dataclass
class CallRecord:
    timestamp: str
    node_id: str
    phase: str
    skill: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

class CostTracker:
    """Thread-safe per-experiment cost tracker."""
    def __init__(self, log_dir: str | Path) -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._trace_path = self._dir / "cost_trace.jsonl"
        self._summary_path = self._dir / "cost_summary.json"
        self._lock = threading.Lock()
        self._records: list[CallRecord] = []

    def record(self, *, model: str, prompt_tokens: int, completion_tokens: int,
               node_id: str = "", phase: str = "", skill: str = "") -> None:
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)
        rec = CallRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            node_id=node_id, phase=phase, skill=skill, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=cost,
        )
        with self._lock:
            self._records.append(rec)
            with open(self._trace_path, "a") as f:
                f.write(json.dumps(asdict(rec)) + "\n")
        self._write_summary()

    def _write_summary(self) -> None:
        with self._lock:
            records = list(self._records)
        if not records:
            return
        total_cost = sum(r.estimated_cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)
        by_phase: dict = {}
        by_model: dict = {}
        for r in records:
            p = r.phase or "unknown"
            by_phase.setdefault(p, {"cost_usd": 0.0, "tokens": 0})
            by_phase[p]["cost_usd"] += r.estimated_cost_usd
            by_phase[p]["tokens"] += r.total_tokens
            by_model.setdefault(r.model, {"cost_usd": 0.0, "tokens": 0})
            by_model[r.model]["cost_usd"] += r.estimated_cost_usd
            by_model[r.model]["tokens"] += r.total_tokens
        summary = {
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "call_count": len(records),
            "by_phase": {k: {"cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
                         for k, v in by_phase.items()},
            "by_model": {k: {"cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
                         for k, v in by_model.items()},
        }
        with open(self._summary_path, "w") as f:
            json.dump(summary, f, indent=2)

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return sum(r.estimated_cost_usd for r in self._records)

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return sum(r.total_tokens for r in self._records)

_tracker: Optional[CostTracker] = None

def init(log_dir: str | Path) -> CostTracker:
    global _tracker
    _tracker = CostTracker(log_dir)
    return _tracker

def record(**kwargs) -> None:
    if _tracker is not None:
        _tracker.record(**kwargs)

def get() -> Optional[CostTracker]:
    return _tracker
