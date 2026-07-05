"""Prompt-provenance recorder (subtask 044) — deterministic, LLM-call-free.

Records *which prompt template* (and, where a rendered string is available,
*which rendered prompt*) produced each managed-prompt LLM call, into a
checkpoint-scoped, append-only JSONL artifact ``prompt_trace.jsonl``. This is
the structural twin of :mod:`ari.cost_tracker`'s ``cost_trace.jsonl``: same
append-under-lock discipline, same additive ``None``/``""``-defaulted fields,
same checkpoint scoping via ``ARI_CHECKPOINT_DIR`` / :class:`ari.paths.PathManager`.

Design constraints (P2 determinism — see ``docs/refactoring/011_prompt_management_plan.md`` §8.3):

* Pure stdlib: no LLM calls, no network, no third-party deps.
* Hashes are ``sha256(text.encode("utf-8")).hexdigest()[:12]`` — the *exact*
  scheme :meth:`ari.prompts._loader.FilesystemPromptLoader.load_versioned`
  already uses, so a template body hashes identically here and there and across
  machines. **No wall-clock, git SHA, host, or absolute path ever enters a
  hash** (the ``timestamp`` field is metadata only, never hashed).

Everything is *additive*: a pre-044 checkpoint simply lacks these files, and
every reader must treat their absence as "no provenance recorded" (never an
error). The recorder is a no-op when no checkpoint dir is resolvable (unit
tests, pre-launch), so wiring it into a call site is side-effect-free outside a
run.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# Filenames written at the checkpoint root (registered in
# ``PathManager.META_FILES`` so they are never copied into node work dirs nor
# surfaced as experiment artifacts).
PROMPT_TRACE_FILENAME = "prompt_trace.jsonl"
PROMPT_VERSIONS_FILENAME = "prompt_versions.json"

# Serialises concurrent appends from BFTS worker threads (mirrors
# ``cost_tracker``'s lock).
_LOCK = threading.Lock()


def hash12(text: str) -> str:
    """Return ``sha256(text)[:12]`` — identical to ``load_versioned``'s scheme.

    Deterministic and machine-stable; used for both ``template_hash`` (raw
    template body) and ``rendered_prompt_hash`` (post-``format`` string).
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class PromptUseRecord:
    """One managed-prompt LLM call's provenance.

    Modeled on :class:`ari.cost_tracker.CallRecord`: every non-essential field
    defaults so the schema can grow without breaking readers. ``prompt_name``
    and ``template_hash`` are the mandatory, always-computable fields; the
    registry-derived fields (``prompt_version`` / ``prompt_registry_version``)
    stay ``None`` until subtask 038 lands.
    """

    timestamp: str
    prompt_name: str
    template_hash: str
    rendered_prompt_hash: str | None = None
    prompt_version: str | None = None
    prompt_registry_version: str | None = None
    model: str = ""
    node_id: str = ""
    phase: str = ""
    # Reserves "skill" for subtask 040 (skill-side provenance); 044 is core-only.
    source: str = "core"


def _resolve_checkpoint_dir(checkpoint_dir: str | Path | None) -> Path | None:
    """Resolve the checkpoint dir, preferring an explicit arg then the env pin.

    Uses the same ``ARI_CHECKPOINT_DIR`` run pin that ``cost_tracker`` /
    ``paths`` use, going through :class:`ari.paths.PathManager` so the recorder
    stays independent of the env-var spelling.
    """
    if checkpoint_dir is not None:
        return Path(checkpoint_dir)
    try:
        from ari.paths import PathManager
        return PathManager.checkpoint_dir_from_env()
    except Exception:
        return None


def record_prompt_use(
    prompt_name: str,
    template_hash: str,
    *,
    rendered_text: str | None = None,
    model: str = "",
    node_id: str = "",
    phase: str = "",
    prompt_version: str | None = None,
    prompt_registry_version: str | None = None,
    checkpoint_dir: str | Path | None = None,
) -> None:
    """Append one prompt-use provenance record to ``prompt_trace.jsonl``.

    No-op (silently returns) when no checkpoint dir is resolvable, so the 11
    core call sites stay side-effect-free outside a run. ``rendered_prompt_hash``
    is computed only when *rendered_text* is supplied (some sites only load a
    template and never render a final string here — that is acceptable).

    Deterministic and offline: performs zero LLM/network calls; the only
    non-deterministic value (``timestamp``) is metadata and never hashed.
    """
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return
    # Coerce string fields defensively: in production these are always ``str``
    # (so this is a no-op), but it keeps the JSONL line serializable even if a
    # caller passes a non-string (e.g. a test double). Hashes are never derived
    # from these fields, so this cannot affect determinism.
    rec = PromptUseRecord(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        prompt_name=str(prompt_name),
        template_hash=str(template_hash),
        rendered_prompt_hash=hash12(rendered_text) if rendered_text is not None else None,
        prompt_version=prompt_version,
        prompt_registry_version=prompt_registry_version,
        model=str(model) if model else "",
        node_id=str(node_id) if node_id else "",
        phase=str(phase) if phase else "",
        source="core",
    )
    try:
        ckpt.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with _LOCK:
            with open(ckpt / PROMPT_TRACE_FILENAME, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Never break an LLM call because provenance logging failed
        # (same best-effort posture as cost_tracker's litellm handler).
        pass


def load_prompt_trace(checkpoint_dir: str | Path) -> list[dict]:
    """Read every record from ``prompt_trace.jsonl`` (best-effort, order-preserving).

    Returns an empty list when the file is absent (a pre-044 checkpoint) or
    unreadable — absence is "no provenance recorded", never an error.
    """
    path = Path(checkpoint_dir) / PROMPT_TRACE_FILENAME
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
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


def build_prompt_versions_rollup(checkpoint_dir: str | Path) -> dict:
    """Aggregate ``prompt_trace.jsonl`` into the run-level rollup mapping.

    Returns ``{prompt_name: {"template_hash", "prompt_version", "call_count"}}``.
    Deterministic: insertion order follows first-seen order in the trace, and
    dicts preserve insertion order, so the same trace always yields the same
    JSON. ``template_hash`` reflects the first record seen for that prompt.
    """
    rollup: dict[str, dict] = {}
    for rec in load_prompt_trace(checkpoint_dir):
        name = rec.get("prompt_name") or ""
        if not name:
            continue
        entry = rollup.get(name)
        if entry is None:
            rollup[name] = {
                "template_hash": rec.get("template_hash") or "",
                "prompt_version": rec.get("prompt_version"),
                "call_count": 1,
            }
        else:
            entry["call_count"] += 1
    return rollup
