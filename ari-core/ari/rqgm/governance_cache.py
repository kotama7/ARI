"""Governance result cache + the spec-fixed ``cache_key`` (RQGM Task 12).

Replay evaluation (``rqgm.replay.use_cached_results: true``) and repeated
governance evaluations of the same artifact must not re-pay LLM cost
(``docs/reference/rqgm_schemas.md``, "Governance-cache schema (Task 12)").
Spec-fixed composition::

    cache_key = sha256("\\x1f".join(
        artifact_hash, prompt_hash, role, epoch_id,
        input_context_hash, output_schema_hash,
    ))[:16]

* record-separator join prevents component ambiguity; 16 hex chars matches
  the EAR artifact-id precedent;
* ``prompt_hash`` is the existing ``hash12`` scheme (no second scheme);
* canonical JSON (``ari.rqgm.events.canonical_json``) feeds the two content
  hashes — no wall-clock, host, or absolute path ever enters a key (P2);
  ``created_at`` on stored records is provenance only, NEVER part of the key;
* ``epoch_id`` inclusion is deliberate (epoch-local fixed-evaluator
  guarantee); the ONE sanctioned cross-epoch exception is replay — the
  lookup key for a replayed case uses the case's original epoch id
  (:func:`replay_lookup_key`), which is what makes ``use_cached_results``
  effective across epochs.

Store: ``{ckpt}/rqgm_governance_cache.jsonl`` — append-only JSONL (module
lock, run-pin no-op, never raises; modeled on ``record_prompt_use``),
loaded into an in-memory index at first use. Absence of the file == empty
cache, never an error. Entries are never invalidated in place: a retired
prompt's entries simply stop being addressable (its ``prompt_hash`` never
recurs in a lookup) — consistent with selective erasure's
no-physical-deletion rule (invariant 13).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from ari.rqgm.events import canonical_json

log = logging.getLogger(__name__)

GOVERNANCE_CACHE_FILENAME = "rqgm_governance_cache.jsonl"
GOVERNANCE_CACHE_SCHEMA_VERSION = 1

#: Record-separator join of the six key components: an in-band separator no
#: component can contain is what keeps the concatenation unambiguous.
_KEY_SEPARATOR = "\x1f"

_LOCK = threading.Lock()


def canonical_hash(payload: object) -> str:
    """``sha256:<hex>`` over the canonical JSON of *payload* — the
    ``input_context_hash`` / ``output_schema_hash`` builder (canonical JSON,
    so dict key order never changes the hash)."""
    return "sha256:" + hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def make_cache_key(
    *,
    artifact_hash: str,
    prompt_hash: str,
    role: str,
    epoch_id: str,
    input_context_hash: str,
    output_schema_hash: str,
) -> str:
    """The spec-fixed composition (the formula in this module's docstring) —
    component order and separator are fixed, never derived, and pinned by the
    golden-key test. Pure; P2-clean."""
    joined = _KEY_SEPARATOR.join([
        str(artifact_hash),
        str(prompt_hash),
        str(role),
        str(epoch_id),
        str(input_context_hash),
        str(output_schema_hash),
    ])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def case_origin_epoch(case) -> str:
    """A replayed case's ORIGIN epoch id (falls back to ``epoch_id`` for
    dict/object cases that predate the origin field)."""
    if isinstance(case, dict):
        return str(case.get("origin_epoch_id") or case.get("epoch_id") or "")
    return str(
        getattr(case, "origin_epoch_id", "")
        or getattr(case, "epoch_id", "")
        or ""
    )


def replay_lookup_key(
    case,
    *,
    prompt_hash: str,
    role: str,
    artifact_hash: str = "",
    input_context_hash: str = "",
    output_schema_hash: str = "",
) -> str:
    """The replay rule: when replaying case *c* against prompt *p*,
    ``epoch_id`` is the case's ORIGIN epoch and ``prompt_hash`` is the
    candidate's own hash — a candidate re-run against old cases caches
    correctly across epochs."""
    origin = case_origin_epoch(case)
    return make_cache_key(
        artifact_hash=artifact_hash,
        prompt_hash=prompt_hash,
        role=role,
        epoch_id=origin,
        input_context_hash=input_context_hash,
        output_schema_hash=output_schema_hash,
    )


class GovernanceCache:
    """Append-only ``{ckpt}/rqgm_governance_cache.jsonl`` + in-memory index.

    Writer posture (shared with every ARI provenance writer): lock-guarded,
    no-op without a resolvable checkpoint dir, never raises into the run
    loop. The index is rebuilt from the JSONL on first access (resume, §8).
    """

    def __init__(self, checkpoint_dir: str | Path | None = None) -> None:
        self._ckpt = (
            Path(checkpoint_dir) if checkpoint_dir is not None else None
        )
        self._index: dict[str, dict] | None = None

    def _path(self) -> Path | None:
        from ari.rqgm.store import _resolve_checkpoint_dir

        ckpt = _resolve_checkpoint_dir(self._ckpt)
        return None if ckpt is None else ckpt / GOVERNANCE_CACHE_FILENAME

    def _load(self) -> dict[str, dict]:
        if self._index is not None:
            return self._index
        index: dict[str, dict] = {}
        path = self._path()
        if path is not None and path.exists():
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
                        if isinstance(d, dict) and d.get("cache_key"):
                            index[str(d["cache_key"])] = d
            except OSError:
                log.warning("governance cache read failed (empty cache)",
                            exc_info=True)
        self._index = index
        return index

    def make_key(self, **components) -> str:
        return make_cache_key(**components)

    def get(self, key: str) -> dict | None:
        """Cache lookup; ``None`` == miss (absence is never an error)."""
        try:
            record = self._load().get(str(key))
            return dict(record) if record is not None else None
        except Exception:
            log.warning("governance cache get failed (miss)", exc_info=True)
            return None

    def put(self, key: str, record: dict) -> None:
        """Append one cache record (idempotent per key in the index; the
        JSONL keeps every line — append-only, no in-place invalidation)."""
        try:
            line = {
                "schema_version": GOVERNANCE_CACHE_SCHEMA_VERSION,
                "cache_key": str(key),
            }
            line.update({
                k: v for k, v in dict(record or {}).items()
                if k not in ("schema_version", "cache_key")
            })
            # Provenance only — NEVER part of cache_key (P2: a wall clock in
            # the key would make every lookup a miss).
            line.setdefault(
                "created_at",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            path = self._path()
            if path is None:
                return
            with _LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._load()[str(key)] = line
        except Exception:
            log.warning("governance cache put failed (entry dropped)",
                        exc_info=True)
