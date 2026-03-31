"""Cost tracker for ARI — writes per-call logs and per-experiment summaries."""

from __future__ import annotations
import json, threading, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Pricing per 1K tokens (input, output) in USD.
# Sources: openai.com/api/pricing, claude.com/pricing, ai.google.dev/pricing
# Last verified: 2026-03-28
_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-5.2":           (0.00175, 0.014),
    "gpt-5":             (0.00125, 0.010),
    "gpt-4o-mini":       (0.00015, 0.0006),
    "gpt-4o":            (0.0025, 0.010),
    "gpt-4":             (0.03, 0.06),
    "gpt-3.5-turbo":     (0.0005, 0.0015),
    "o3-mini":           (0.0011, 0.0044),
    "o4-mini":           (0.0011, 0.0044),
    "o3":                (0.002, 0.008),
    # Anthropic
    "claude-opus-4-6":   (0.005, 0.025),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-opus-4-5":   (0.005, 0.025),
    "claude-opus-4-1":   (0.015, 0.075),
    "claude-opus-4":     (0.015, 0.075),
    "claude-sonnet-4":   (0.003, 0.015),
    "claude-haiku-4-5":  (0.001, 0.005),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-opus":     (0.015, 0.075),
    # Google Gemini
    "gemini-2.5-pro":    (0.00125, 0.010),
    "gemini-2.0-flash":  (0.0001, 0.0004),
    "gemini-1.5-pro":    (0.00125, 0.005),
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
        # Reload existing records from cost_trace.jsonl so that
        # re-initialisation (e.g. pipeline.py after cli.py) does not
        # discard costs already written to disk.
        self._reload_existing()

    def _reload_existing(self) -> None:
        """Restore in-memory records from an existing cost_trace.jsonl file."""
        if not self._trace_path.exists():
            return
        try:
            with open(self._trace_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        self._records.append(CallRecord(
                            timestamp=d.get("timestamp", ""),
                            node_id=d.get("node_id", ""),
                            phase=d.get("phase", ""),
                            skill=d.get("skill", ""),
                            model=d.get("model", ""),
                            prompt_tokens=d.get("prompt_tokens", 0),
                            completion_tokens=d.get("completion_tokens", 0),
                            total_tokens=d.get("total_tokens", 0),
                            estimated_cost_usd=d.get("estimated_cost_usd", 0.0),
                        ))
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass

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
    """Initialise (or reuse) the global cost tracker for *log_dir*.

    Idempotent: if a tracker already exists for the same directory it is
    returned as-is so that accumulated in-memory records are not lost.
    If a *new* tracker is created it automatically reloads any records
    already persisted in ``cost_trace.jsonl``.
    """
    global _tracker
    resolved = Path(log_dir).resolve()
    if _tracker is not None and _tracker._dir.resolve() == resolved:
        _install_litellm_callback()
        return _tracker
    _tracker = CostTracker(log_dir)
    _install_litellm_callback()
    return _tracker

def record(**kwargs) -> None:
    if _tracker is not None:
        _tracker.record(**kwargs)

def get() -> Optional[CostTracker]:
    return _tracker


# ── litellm global callback ─────────────────────────────────────────────────
# Catches ALL litellm.completion/acompletion calls across the process,
# including those from MCP skill servers (paper-skill, plot-skill, etc.)
# which call litellm directly without going through ari.llm.client.

def _litellm_success_handler(kwargs, response_obj, start_time, end_time):
    """litellm success_callback: log every LLM call to cost_tracker."""
    if _tracker is None:
        return
    try:
        usage = getattr(response_obj, "usage", None)
        if not usage:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        if prompt_tokens == 0 and completion_tokens == 0:
            return
        model = kwargs.get("model", "") or getattr(response_obj, "model", "") or ""
        # Detect skill/phase from litellm metadata if available
        metadata = kwargs.get("litellm_params", {}).get("metadata", {}) or {}
        skill = metadata.get("skill", "") or ""
        _tracker.record(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            phase=metadata.get("phase", ""),
            skill=skill,
            node_id=metadata.get("node_id", ""),
        )
    except Exception:
        pass  # Never break the LLM call due to tracking errors


def _install_litellm_callback():
    """Register the global litellm callback (idempotent)."""
    try:
        import litellm
        if litellm.success_callback is None:
            litellm.success_callback = []
        if _litellm_success_handler not in litellm.success_callback:
            litellm.success_callback.append(_litellm_success_handler)
    except ImportError:
        pass
