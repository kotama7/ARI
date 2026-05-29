"""Cost tracker for ARI — writes per-call logs and per-experiment summaries."""

from __future__ import annotations
import json, os, threading, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Pricing per 1K tokens (input, output) in USD.
#
# Phase PC1: the actual table lives in ``ari/configs/model_prices.yaml``
# so adding a new model is a YAML edit, not a code change.  We load it
# lazily on first use to avoid forcing PyYAML on contexts that never
# call ``_estimate_cost`` (e.g. shallow CLI imports).


def _load_pricing() -> dict[str, tuple[float, float]]:
    try:
        from ari.configs import FilesystemConfigLoader
        raw = FilesystemConfigLoader().load("model_prices")
    except Exception:
        return {}
    out: dict[str, tuple[float, float]] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                out[str(k)] = (float(v[0]), float(v[1]))
            except (TypeError, ValueError):
                continue
    return out


_PRICING_CACHE: dict[str, tuple[float, float]] | None = None


def _pricing() -> dict[str, tuple[float, float]]:
    global _PRICING_CACHE
    if _PRICING_CACHE is None:
        _PRICING_CACHE = _load_pricing()
    return _PRICING_CACHE


def __getattr__(name: str):  # PEP 562 — keep ``_PRICING`` source-compatible.
    if name == "_PRICING":
        return _pricing()
    raise AttributeError(name)

def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _pricing()
    key = next((k for k in pricing if k in model.lower()), None)
    if not key:
        return 0.0
    inp, out = pricing[key]
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
    # additive fields; default-None keeps
    # existing callers source-compatible.
    component: str | None = None      # "memory" | "llm" | None
    op: str | None = None             # "add" | "search" | "purge" | ...
    backend: str | None = None        # "letta" | None
    embedding_tokens: int = 0
    latency_ms: float | None = None

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
               node_id: str = "", phase: str = "", skill: str = "",
               component: str | None = None, op: str | None = None,
               backend: str | None = None, embedding_tokens: int = 0,
               latency_ms: float | None = None,
               cost_usd: float | None = None) -> None:
        # Trust an authoritative upstream cost when provided (e.g. the CLI shim
        # forwards claude -p's ``total_cost_usd``). litellm's pricing table has
        # no entry for synthetic shim models like "claude-cli", so without this
        # path the call would otherwise be booked at $0.
        cost = (
            float(cost_usd)
            if cost_usd is not None
            else _estimate_cost(model, prompt_tokens, completion_tokens)
        )
        rec = CallRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            node_id=node_id, phase=phase, skill=skill, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=cost,
            component=component, op=op, backend=backend,
            embedding_tokens=embedding_tokens, latency_ms=latency_ms,
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
        _install_litellm_metadata_injector()
        return _tracker
    _tracker = CostTracker(log_dir)
    _install_litellm_callback()
    # Apply ARI's model/api_base routing to every litellm call in this
    # process (orchestrator side), mirroring what bootstrap_skill already
    # does inside each MCP skill subprocess.
    _install_litellm_metadata_injector()
    return _tracker


def init_from_env() -> Optional[CostTracker]:
    """Initialise the tracker from ``ARI_CHECKPOINT_DIR`` if set.

    Designed for MCP skill subprocesses: they inherit the checkpoint dir
    via env var and just need a one-line call to start logging. Returns
    the tracker on success, ``None`` when the env var is missing or the
    directory cannot be created.
    """
    from ari.paths import PathManager as _PathManager
    ckpt = _PathManager.checkpoint_dir_from_env()
    if ckpt is None:
        return None
    try:
        return init(ckpt)
    except Exception:
        return None


_DEFAULT_METADATA: dict[str, str] = {}


def set_default_metadata(**kwargs: str) -> None:
    """Record default metadata (skill, phase, ...) merged into every
    ``litellm.completion`` / ``acompletion`` call issued from this process.

    Call sites that pass their own ``metadata=`` kwarg win on key collisions —
    defaults only fill in unset fields. Used by skill subprocesses so the
    skill name is attributed automatically without touching every call site.
    """
    for k, v in kwargs.items():
        if v is None:
            _DEFAULT_METADATA.pop(k, None)
        else:
            _DEFAULT_METADATA[k] = str(v)
    _install_litellm_metadata_injector()


_injector_installed = False


def _apply_ari_routing(kwargs: dict) -> None:
    """Normalise a litellm-call kwargs in place so synthetic-shim models
    (``claude-cli``, ``codex-cli``) reach the shim correctly.

    Two concerns, both single-point so skills don't have to duplicate them:

    * **Provider prefix.** A bare ``model="claude-cli"`` makes litellm raise
      ``LLM Provider NOT provided`` because no built-in routing table covers
      that name. :func:`ari.llm.routing.resolve_litellm_model` applies the
      same prefix rules the agent ReAct client uses.
    * **Base URL.** With ``ARI_BACKEND=cli-shim``, fill in ``api_base`` from
      ``ARI_LLM_API_BASE`` (default :8900) when the caller didn't supply one
      — otherwise the request would hit ``api.openai.com``.

    Real OpenAI / Anthropic / Ollama backends are untouched.
    """
    try:
        from ari.llm.routing import resolve_litellm_model
    except ImportError:
        return
    backend = os.environ.get("ARI_BACKEND", "")
    model = kwargs.get("model")
    if model:
        resolved = resolve_litellm_model(model, backend=backend)
        if resolved != model:
            kwargs["model"] = resolved
    if backend in ("cli-shim", "cli_shim") and "api_base" not in kwargs:
        base = os.environ.get("ARI_LLM_API_BASE")
        if base:
            kwargs["api_base"] = base
            kwargs.setdefault(
                "api_key", os.environ.get("OPENAI_API_KEY") or "cli-shim"
            )


def _install_litellm_metadata_injector() -> None:
    """Wrap ``litellm.completion`` / ``litellm.acompletion`` to apply ARI's
    process-wide conventions:

    1. merge defaults from :func:`set_default_metadata` into ``metadata=``,
    2. normalise ``model`` (and fill ``api_base`` for cli-shim) so every
       call from any skill / module routes correctly.

    Idempotent; safe to call from multiple init paths.
    """
    global _injector_installed
    if _injector_installed:
        return
    try:
        import litellm as _litellm
    except ImportError:
        return

    def _merge(user_md):
        merged = dict(_DEFAULT_METADATA)
        if isinstance(user_md, dict):
            merged.update({k: v for k, v in user_md.items() if v not in (None, "")})
        return merged

    _orig_completion = _litellm.completion
    _orig_acompletion = _litellm.acompletion

    def _completion(*args, **kwargs):
        kwargs["metadata"] = _merge(kwargs.get("metadata"))
        _apply_ari_routing(kwargs)
        return _orig_completion(*args, **kwargs)

    async def _acompletion(*args, **kwargs):
        kwargs["metadata"] = _merge(kwargs.get("metadata"))
        _apply_ari_routing(kwargs)
        return await _orig_acompletion(*args, **kwargs)

    _litellm.completion = _completion
    _litellm.acompletion = _acompletion
    _injector_installed = True


def bootstrap_skill(skill: str, phase: str | None = None) -> Optional[CostTracker]:
    """Convenience for MCP skill servers: initialise the tracker from env
    and register the skill name (and optional phase) as default metadata.

    Usage at the top of a skill's ``server.py``::

        try:
            from ari import cost_tracker as _ct
            _ct.bootstrap_skill("paper")
        except Exception:
            pass
    """
    md: dict[str, str] = {"skill": skill}
    if phase:
        md["phase"] = phase
    set_default_metadata(**md)
    return init_from_env()

def record(**kwargs) -> None:
    if _tracker is not None:
        _tracker.record(**kwargs)

def get() -> Optional[CostTracker]:
    return _tracker


# ── litellm global callback ─────────────────────────────────────────────────
# Catches ALL litellm.completion/acompletion calls across the process,
# including those from MCP skill servers (paper-skill, plot-skill, etc.)
# which call litellm directly without going through ari.llm.client.

def _extract_upstream_cost(usage) -> float | None:
    """Read an upstream-reported ``cost_usd`` from a litellm Usage object.

    litellm's ``Usage`` pydantic model may expose extra fields as attributes,
    on ``model_extra``, or only in the raw dict — depending on version — so
    we try the common access paths in order. Returns ``None`` when no
    authoritative cost is available; the caller falls back to the price-table
    estimate.
    """
    if usage is None:
        return None
    candidates = ("cost_usd", "x_ari_cost_usd")
    for attr in candidates:
        v = getattr(usage, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    extra = getattr(usage, "model_extra", None)
    if isinstance(extra, dict):
        for key in candidates:
            if extra.get(key) is not None:
                try:
                    return float(extra[key])
                except (TypeError, ValueError):
                    pass
    d = getattr(usage, "__dict__", None)
    if isinstance(d, dict):
        for key in candidates:
            if d.get(key) is not None:
                try:
                    return float(d[key])
                except (TypeError, ValueError):
                    pass
    if isinstance(usage, dict):
        for key in candidates:
            if usage.get(key) is not None:
                try:
                    return float(usage[key])
                except (TypeError, ValueError):
                    pass
    return None


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
        # Detect skill/phase/node_id from litellm metadata.
        # litellm forwards a caller's ``metadata=`` kwarg into
        # ``kwargs['litellm_params']['metadata']``; the plain top-level
        # ``metadata`` key is also checked so that tests (which invoke the
        # handler directly) and older litellm versions still work.
        lp = kwargs.get("litellm_params", {}) or {}
        metadata = (lp.get("metadata") or kwargs.get("metadata") or {})
        _tracker.record(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            phase=metadata.get("phase", "") or "",
            skill=metadata.get("skill", "") or "",
            node_id=metadata.get("node_id", "") or "",
            cost_usd=_extract_upstream_cost(usage),
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
