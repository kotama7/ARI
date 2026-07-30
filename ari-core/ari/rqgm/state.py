"""RQGM run-level state: mode provenance (Task 01) + EpochState (Task 02).

Two concerns share this module (plan 02 §5.3 places ``EpochState`` here):

1. **Mode provenance** — ``{ckpt}/rqgm_state.json``. Absence of the file ==
   pure ``simple_bfts`` run == a current-ARI trajectory (P5
   absence-is-default, mirrored from ``bfts_web_provenance.json``). Written
   only when the effective mode is ``ari_rqgm``. Read-precedence rule
   (normative for Tasks 02-13, plan 01 §5.5): persisted state → typed ``cfg``
   → defaults; no RQGM code re-reads the package workflow.yaml directly.
2. **EpochState** — the immutable per-epoch freeze of the active component
   set, prompt hashes, and utility policy (plan 02 §5.6, §6), plus its
   deterministic ``epoch_fingerprint``. Persistence lives in
   :mod:`ari.rqgm.store` (event-log truth + ``epoch_state.json`` rollup).

JSON layout is owned by ``ari.checkpoint`` (byte-fixed ``indent=2,
ensure_ascii=False``, rewrite-whole-file) like every other checkpoint-root
snapshot; this module owns the schemas and the freeze policy.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ari.rqgm.events import (
    UTILITY_POLICY_ROLE,
    canonical_json,
    format_epoch_id,
    hash12,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import ARIConfig

log = logging.getLogger(__name__)

RQGM_STATE_FILENAME = "rqgm_state.json"
CONSTITUTION_FILENAME = "constitution.yaml"
RQGM_STATE_SCHEMA_VERSION = 1

# mode_source vocabulary (plan 01 §6.2): how the persisted mode was decided.
MODE_SOURCES = ("config", "env", "resume")


def read_rqgm_state(checkpoint_dir: str | Path) -> dict | None:
    """Absence-tolerant read: ``None`` when missing or unparseable."""
    from ari.checkpoint import load_rqgm_state_json

    return load_rqgm_state_json(checkpoint_dir)


def write_rqgm_state(checkpoint_dir: str | Path, state: dict) -> None:
    """Best-effort write — a state-write failure must never break the run."""
    try:
        from ari.checkpoint import save_rqgm_state_json

        save_rqgm_state_json(checkpoint_dir, state)
    except Exception:
        log.warning(
            "failed to write %s under %s", RQGM_STATE_FILENAME, checkpoint_dir,
            exc_info=True,
        )


def build_run_start_state(
    *, mode: str, rqgm_enabled: bool, mode_source: str = "config"
) -> dict:
    """Schema-v1 run-start payload (plan 01 §6.2).

    ``created_at`` is metadata only — never hashed and never read by decision
    logic (P2 determinism holds for every consumer of this file).
    """
    if mode_source not in MODE_SOURCES:
        log.warning("unknown mode_source %r; recording 'config'", mode_source)
        mode_source = "config"
    return {
        "schema_version": RQGM_STATE_SCHEMA_VERSION,
        "mode": mode,
        "rqgm_enabled": bool(rqgm_enabled),
        "mode_source": mode_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "switch_journal": [
            {"event": "run_start", "mode": mode, "epoch_id": None},
        ],
    }


def persist_run_start(
    checkpoint_dir: str | Path,
    *,
    mode: str = "ari_rqgm",
    rqgm_enabled: bool = True,
    mode_source: str = "config",
) -> None:
    """Write ``rqgm_state.json`` once at run start.

    Write-once: an existing file (resume, or a completed epoch-boundary
    downgrade journal) is never clobbered — later tasks (02/09) append journal
    entries through their own boundary transaction, not through this helper.
    """
    if (Path(checkpoint_dir) / RQGM_STATE_FILENAME).exists():
        return
    write_rqgm_state(
        checkpoint_dir,
        build_run_start_state(
            mode=mode, rqgm_enabled=rqgm_enabled, mode_source=mode_source
        ),
    )


def copy_constitution_if_missing(checkpoint_dir: str | Path) -> None:
    """Copy the bundled ``constitution.yaml`` into the checkpoint (copy-once).

    Follows the workflow.yaml copy pattern with the same don't-clobber guard
    (plan 01 §5.7): the constitutional layer is non-evolving, so the copy
    happens at most once and the checkpoint copy is read-only thereafter.
    Task 04 ships the bundled file at ``ari-core/config/constitution.yaml``
    (a human-readable statement — the authoritative rules stay in code);
    under any packaging without it, absence is a silent no-op.
    """
    from ari.config.finder import package_config_root

    src = package_config_root() / CONSTITUTION_FILENAME
    dst = Path(checkpoint_dir) / CONSTITUTION_FILENAME
    if not src.exists() or dst.exists():
        return
    try:
        import shutil

        shutil.copy2(str(src), str(dst))
    except Exception:
        log.warning("failed to copy %s into checkpoint", CONSTITUTION_FILENAME,
                    exc_info=True)


def record_constitution_hash(checkpoint_dir: str | Path) -> None:
    """Additively record ``constitution_hash`` in ``{ckpt}/meta.json``
    (plan 04 §6): children of an RQGM run inherit it and the existing viz
    launch gates can check it. Best-effort and additive-only — an existing
    key or an unreadable file is never clobbered, and failure never breaks
    the run. Never called under ``simple_bfts``.
    """
    try:
        import json

        from ari.rqgm.kernel_rules import CONSTITUTION_HASH

        meta_path = Path(checkpoint_dir) / "meta.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            except (json.JSONDecodeError, OSError):
                log.warning("meta.json unreadable; not recording "
                            "constitution_hash")
                return
        if meta.get("constitution_hash"):
            return
        meta["constitution_hash"] = CONSTITUTION_HASH
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        log.warning("failed to record constitution_hash in meta.json",
                    exc_info=True)


def reconcile_resume_mode(cfg: "ARIConfig", checkpoint_dir: str | Path) -> None:
    """Force *cfg* to the persisted mode on ``ari resume`` (plan 01 §5.5).

    The persisted mode wins over package config and env; a disagreement
    produces a warning, never a mid-run mode flip. A checkpoint without
    ``rqgm_state.json`` started (and stays) ``simple_bfts`` — there is no
    legal mid-run upgrade point in the legacy loop.
    """
    requested_mode = getattr(getattr(cfg, "ari", None), "mode", "simple_bfts")
    requested_enabled = bool(getattr(getattr(cfg, "rqgm", None), "enabled", False))
    state = read_rqgm_state(checkpoint_dir)
    if state is None:
        if requested_mode == "ari_rqgm" or requested_enabled:
            log.warning(
                "resume: no %s in %s — the run started as simple_bfts and "
                "cannot upgrade mid-run (ari.mode=%s rqgm.enabled=%s ignored)",
                RQGM_STATE_FILENAME, checkpoint_dir,
                requested_mode, requested_enabled,
            )
            cfg.ari.mode = "simple_bfts"
            cfg.rqgm.enabled = False
        return
    persisted_mode = str(state.get("mode", "simple_bfts"))
    if persisted_mode not in ("simple_bfts", "ari_rqgm"):
        log.warning(
            "resume: %s has unknown mode %r; treating as simple_bfts",
            RQGM_STATE_FILENAME, persisted_mode,
        )
        persisted_mode = "simple_bfts"
    persisted_enabled = bool(state.get("rqgm_enabled", False))
    if (requested_mode, requested_enabled) != (persisted_mode, persisted_enabled):
        log.warning(
            "resume: persisted mode wins — %s records mode=%s enabled=%s "
            "(config/env requested mode=%s enabled=%s); a run's mode is "
            "immutable except at epoch boundaries, downgrade-only",
            RQGM_STATE_FILENAME, persisted_mode, persisted_enabled,
            requested_mode, requested_enabled,
        )
    cfg.ari.mode = persisted_mode
    cfg.rqgm.enabled = persisted_enabled


# ─────────────────────────────────────────────────────────────────────────────
# EpochState (RQGM Task 02, plan 02 §5.6 / §6)
# ─────────────────────────────────────────────────────────────────────────────

EPOCH_STATE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class EpochState:
    """Immutable per-epoch freeze: active set + utility policy + fingerprint.

    Frozen for the duration of the epoch (global invariants 1-3): Task 04's
    ``validate_epoch_invariance`` later compares per-record
    ``prompt_hash``/``component_id`` against this snapshot. ``created_at`` is
    metadata only — excluded from :func:`epoch_fingerprint` (P2: no
    wall-clock in hashes). The mapping fields are copied at freeze time so
    later registry rebuilds never leak into a frozen epoch.
    """

    epoch_id: str
    epoch_seq: int
    status: str  # "open" | "closed"
    run_id: str = ""
    node_count_at_open: int = 0
    previous_epoch_id: str | None = None
    opened_by_transition_id: str | None = None
    active_components: dict = field(default_factory=dict)
    active_prompt_hashes: dict = field(default_factory=dict)
    #: EVERY active prompt hash at freeze (not the role->incumbent rollup in
    #: ``active_prompt_hashes``). This is the governed set the epoch-invariance
    #: check (CK-EPO-001) tests records against — a role with several active
    #: prompts (e.g. ``generator``) would otherwise false-flag its governed
    #: non-incumbent prompts. Sorted list for deterministic serialization.
    active_prompt_hash_set: list = field(default_factory=list)
    utility_policy: dict = field(default_factory=dict)
    registry_version: str = ""
    policy_settings: dict = field(default_factory=dict)
    policy_fingerprint: str = ""
    execution_identity: dict = field(default_factory=dict)
    execution_fingerprint: str = ""
    epoch_fingerprint: str = ""
    created_at: str = ""  # metadata; never hashed
    schema_version: int = EPOCH_STATE_SCHEMA_VERSION

    @property
    def record_id(self) -> str:
        return f"epochstate_{self.epoch_id}"


def epoch_state_payload(state: EpochState) -> dict:
    """Deterministic EpochState fields, §6 key order, WITHOUT ``created_at``.

    This is both the hashed body carried inside ``epoch_open`` events and the
    snapshot body (the snapshot re-adds ``created_at`` last).
    """
    return {
        "schema_version": state.schema_version,
        "record_id": state.record_id,
        "epoch_id": state.epoch_id,
        "epoch_seq": state.epoch_seq,
        "previous_epoch_id": state.previous_epoch_id,
        "opened_by_transition_id": state.opened_by_transition_id,
        "status": state.status,
        "run_id": state.run_id,
        "node_count_at_open": state.node_count_at_open,
        "active_components": dict(state.active_components),
        "active_prompt_hashes": dict(state.active_prompt_hashes),
        "active_prompt_hash_set": sorted(state.active_prompt_hash_set),
        "utility_policy": dict(state.utility_policy),
        "registry_version": state.registry_version,
        "policy_settings": dict(state.policy_settings),
        "policy_fingerprint": state.policy_fingerprint,
        "execution_identity": dict(state.execution_identity),
        "execution_fingerprint": state.execution_fingerprint,
        "epoch_fingerprint": state.epoch_fingerprint,
    }


def policy_fingerprint(state: EpochState) -> str:
    """Digest the frozen institution independently of its execution runtime.

    This commits the active component/prompt population, utility policy,
    constitution and every resolved RQGM policy knob captured in
    ``policy_settings``.  Keeping it separate from
    :func:`execution_fingerprint` prevents a model-provider revision from
    being mistaken for a policy amendment, while the composite
    :func:`epoch_fingerprint` still distinguishes either change.
    """
    return hash12(canonical_json({
        "active_components": dict(state.active_components),
        "active_prompt_hashes": dict(state.active_prompt_hashes),
        "active_prompt_hash_set": sorted(state.active_prompt_hash_set),
        "utility_policy": dict(state.utility_policy),
        "registry_version": state.registry_version,
        "policy_settings": dict(state.policy_settings),
    }))


def execution_fingerprint(state: EpochState) -> str:
    """Digest the declared model/tool/environment identity for an epoch.

    The identity records unresolved provider-side revisions explicitly.
    Consequently this hash proves equality of the *recorded declaration*,
    not equality of opaque provider weights when ``complete`` is false.
    """
    return hash12(canonical_json(dict(state.execution_identity)))


def epoch_fingerprint(state: EpochState) -> str:
    """``hash12(canonical_json(EpochState minus metadata timestamps))``.

    Excludes ``created_at`` (wall-clock metadata) and the fingerprint field
    itself; deterministic across machines and processes (P2). The epoch
    ``status`` is also excluded so open→closed does not re-fingerprint the
    frozen content.
    """
    payload = epoch_state_payload(state)
    payload.pop("epoch_fingerprint", None)
    payload.pop("status", None)
    # ``active_prompt_hash_set`` is fully determined by the registry (whose
    # identity ``registry_version`` already fingerprints), so it is persisted in
    # the payload but excluded here: it adds no identity the fingerprint doesn't
    # already carry, and excluding it keeps the fingerprint stable across the
    # field's introduction.
    payload.pop("active_prompt_hash_set", None)
    if int(state.schema_version) < 2:
        # Schema-v1 replay compatibility: additive v2 fields must not change
        # the digest of an already committed epoch_open event.
        for key in (
            "policy_settings",
            "policy_fingerprint",
            "execution_identity",
            "execution_fingerprint",
        ):
            payload.pop(key, None)
    return hash12(canonical_json(payload))


def epoch_state_from_payload(payload: dict, *, created_at: str = "") -> EpochState:
    """Rebuild an :class:`EpochState` from an ``epoch_open`` event payload
    (replay path, plan 02 §5.7). ``created_at`` comes from the event's
    ``ts_iso`` envelope metadata."""
    return EpochState(
        epoch_id=str(payload.get("epoch_id", "")),
        epoch_seq=int(payload.get("epoch_seq", 0)),
        status=str(payload.get("status", "open")),
        run_id=str(payload.get("run_id", "")),
        node_count_at_open=int(payload.get("node_count_at_open", 0)),
        previous_epoch_id=payload.get("previous_epoch_id"),
        opened_by_transition_id=payload.get("opened_by_transition_id"),
        active_components=dict(payload.get("active_components") or {}),
        active_prompt_hashes=dict(payload.get("active_prompt_hashes") or {}),
        active_prompt_hash_set=list(payload.get("active_prompt_hash_set") or []),
        utility_policy=dict(payload.get("utility_policy") or {}),
        registry_version=str(payload.get("registry_version", "")),
        policy_settings=dict(payload.get("policy_settings") or {}),
        policy_fingerprint=str(payload.get("policy_fingerprint", "")),
        execution_identity=dict(payload.get("execution_identity") or {}),
        execution_fingerprint=str(payload.get("execution_fingerprint", "")),
        epoch_fingerprint=str(payload.get("epoch_fingerprint", "")),
        created_at=created_at,
        schema_version=int(payload.get("schema_version",
                                       EPOCH_STATE_SCHEMA_VERSION)),
    )


def _plain_config(value):
    """Recursively convert typed config objects to canonical-JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(k): _plain_config(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (set, frozenset)):
        plain = [_plain_config(v) for v in value]
        return sorted(plain, key=lambda item: canonical_json(item))
    if isinstance(value, (list, tuple)):
        return [_plain_config(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _plain_config(dump(mode="json"))
        except TypeError:  # Pydantic v1-compatible fallback
            return _plain_config(dump())
    as_dict = getattr(value, "dict", None)
    if callable(as_dict):
        return _plain_config(as_dict())
    if hasattr(value, "__dict__"):
        return _plain_config({
            k: v for k, v in vars(value).items() if not str(k).startswith("_")
        })
    return str(value)


def capture_policy_settings(cfg) -> dict:
    """Capture all resolved policy knobs that can alter governed behaviour."""
    from ari.rqgm.kernel_rules import CONSTITUTION_HASH

    ari_cfg = getattr(cfg, "ari", None)
    return {
        "constitution_hash": CONSTITUTION_HASH,
        "ari_mode": str(getattr(ari_cfg, "mode", "simple_bfts")),
        "rqgm": _plain_config(getattr(cfg, "rqgm", None)) or {},
        "proposal_router": (
            _plain_config(getattr(cfg, "proposal_router", None)) or {}
        ),
        "paper": _plain_config(getattr(cfg, "paper", None)) or {},
    }


def capture_execution_identity(cfg) -> dict:
    """Capture the observable execution identity at epoch open.

    Provider weights, tool bundles, environments and data snapshots are not
    universally introspectable.  Deployments may pin their immutable
    identifiers through the four ``ARI_*_REVISION``/``*_DIGEST`` variables
    below.  Absence is represented by ``"unresolved"`` and makes
    ``complete`` false instead of silently treating a mutable model alias as
    a fixed implementation.
    """
    llm = getattr(cfg, "llm", None)
    skills = []
    for skill in getattr(cfg, "skills", None) or ():
        skills.append({
            "name": str(getattr(skill, "name", "") or ""),
            "phase": _plain_config(getattr(skill, "phase", "all")),
        })
    pins = {
        "provider_model_revision": (
            os.environ.get("ARI_MODEL_REVISION", "").strip() or "unresolved"
        ),
        "tool_bundle_revision": (
            os.environ.get("ARI_TOOL_BUNDLE_REVISION", "").strip()
            or "unresolved"
        ),
        "environment_digest": (
            os.environ.get("ARI_ENVIRONMENT_DIGEST", "").strip()
            or "unresolved"
        ),
        "data_snapshot_digest": (
            os.environ.get("ARI_DATA_SNAPSHOT_DIGEST", "").strip()
            or "unresolved"
        ),
    }
    return {
        "model_backend": str(getattr(llm, "backend", "") or ""),
        "model_id": str(getattr(llm, "model", "") or ""),
        "decoding": {
            "temperature": float(getattr(llm, "temperature", 0.7)),
        },
        "research_execution": {
            "search": _plain_config(getattr(cfg, "bfts", None)) or {},
            "evaluation": (
                _plain_config(getattr(cfg, "evaluator", None)) or {}
            ),
        },
        "skills": sorted(skills, key=lambda item: (item["name"],
                                                   str(item["phase"]))),
        "disabled_tools": sorted(
            str(name) for name in (getattr(cfg, "disabled_tools", None) or ())
        ),
        **pins,
        "complete": all(value != "unresolved" for value in pins.values()),
    }


def utility_policy_body(cfg) -> dict:
    """The utility-policy BODY from the resolved config — the hashed keys
    only, WITHOUT ``utility_policy_hash`` (plan 02 §5.6.2, plan 14 §6.1).

    Duck-typed ``getattr`` reads keep this total over pre-RQGM cfg objects
    and stub configs. ``canonical_json`` of this dict is exactly the bytes a
    governed utility-policy body file carries, so ``hash12`` of those bytes
    IS the entry's ``prompt_hash`` IS ``utility_policy_hash`` — one value,
    three names, zero new hashing (plan 14 §5.3).
    """
    ev = getattr(cfg, "evaluator", None)
    bf = getattr(cfg, "bfts", None)
    return {
        "composite": str(getattr(ev, "composite", "harmonic_mean")),
        "axis_weights": {
            str(k): float(v)
            for k, v in sorted((getattr(ev, "axis_weights", None) or {}).items())
        },
        "frontier_score": str(
            getattr(bf, "frontier_score", "scientific_plus_diversity")
        ),
        "depth_penalty_lambda": float(getattr(bf, "depth_penalty_lambda", 0.05)),
        "ucb_c": float(getattr(bf, "ucb_c", 0.5)),
    }


def seal_utility_policy(body: dict) -> dict:
    """``body`` + its ``utility_policy_hash`` (computed over the canonical
    JSON of the body ALONE, before the hash key is inserted — P2:
    content-only, no wall clock). The one place the seal is applied."""
    policy = dict(body)
    policy["utility_policy_hash"] = hash12(canonical_json(policy))
    return policy


def capture_utility_policy(cfg, registries=None, *, checkpoint_dir=None) -> dict:
    """Freeze the utility policy for the epoch about to open (plan 14 §5.7).

    **Precedence**: the ADOPTED policy in *registries* (the active
    ``utility_policy`` entry, resolved through
    :meth:`ari.rqgm.registry.GovernedPromptRegistry.resolve_text`), else the
    resolved *cfg*. The cfg branch is byte-identical to the pre-Task-14
    function, so epoch 0 of every run — and every epoch of a run that never
    adopts a policy — freezes exactly today's policy.

    This is the CAUSE half of the defining claim that at each epoch boundary
    the entire score is rewritten (plan 14 §1). Before Task 14 this function
    read only the static resolved cfg, so ``utility_policy_hash`` was a
    permanent constant for a run and the retirement that
    ``ari.rqgm.frontier_repair`` waits for could never fire. It now changes
    across epochs when — and only when — the score is actually rewritten
    through the governed path.

    Never raises into the run (the standing state-accessor contract): a
    tampered/unreadable body degrades to the cfg branch with a WARNING.

    *checkpoint_dir* is optional and additive: when omitted, body resolution
    falls back to the ``ARI_CHECKPOINT_DIR`` run pin (the standing
    ``prompt_loader._resolve_checkpoint_dir`` convention). Both
    :mod:`ari.rqgm.store` call sites hold the path already and pass it, so
    the adopted policy resolves even when the env pin is absent — without
    it, an unset pin would silently degrade to the cfg branch and quietly
    disable the rewrite this function exists to enable.
    """
    body = None
    if registries is not None:
        body = _adopted_utility_policy_body(
            registries, checkpoint_dir=checkpoint_dir
        )
    if body is None:
        body = utility_policy_body(cfg)
    return seal_utility_policy(body)


def _adopted_utility_policy_body(registries, *, checkpoint_dir=None) -> dict | None:
    """The active ``utility_policy`` entry's body, or ``None`` to fall back.

    ``None`` covers every pre-Task-14 shape: no registry at all
    (``simple_bfts`` / stubs), a registry with no ``utility_policy`` entry
    (epoch 0 before founding registration; a resumed pre-14 checkpoint), and
    any read/parse/verify failure (plan 14 §5.7 branches 1-3).
    """
    try:
        prompts = getattr(registries, "prompts", None)
        if prompts is None:
            return None
        active = prompts.active_prompt_hashes() or {}
        expected_hash = active.get(UTILITY_POLICY_ROLE)
        if not expected_hash:
            return None
        prompt_id = _active_utility_policy_id(prompts, expected_hash)
        if not prompt_id:
            return None
        text, version_id = prompts.resolve_text(
            prompt_id, checkpoint_dir=checkpoint_dir
        )
        if version_id != expected_hash:
            # CK-UTL-008 shape: the registered identity no longer describes
            # the bytes. resolve_text already refuses this, so this is a
            # belt-and-braces check for a registry that does not.
            log.warning(
                "adopted utility policy %s hashes to %s, expected %s; "
                "falling back to the cfg policy",
                prompt_id, version_id, expected_hash,
            )
            return None
        body = json.loads(text)
        if not isinstance(body, dict):
            raise TypeError(f"policy body is {type(body).__name__}, not a dict")
        body.pop("utility_policy_hash", None)  # the seal is never in the body
        return body
    except Exception:
        log.warning(
            "adopted utility policy unreadable; falling back to the cfg "
            "policy (the incumbent regime, always safe)", exc_info=True
        )
        return None


def _active_utility_policy_id(prompts, expected_hash: str) -> str:
    """The prompt_id of the active ``utility_policy`` entry whose hash is
    *expected_hash* (``active_prompt_hashes`` yields role → hash, not the
    id). Latest-registered wins, matching that rollup exactly."""
    from ari.rqgm.events import ACTIVE_STATUSES

    out = ""
    for pid, entry in (prompts.entries() or {}).items():
        if (
            str(getattr(entry, "role", "")) == UTILITY_POLICY_ROLE
            and str(getattr(entry, "status", "")) in ACTIVE_STATUSES
            and str(getattr(entry, "prompt_hash", "")) == str(expected_hash)
        ):
            out = str(pid)
    return out


def freeze_epoch(
    registries,
    cfg,
    *,
    epoch_seq: int,
    node_count: int,
    run_id: str = "",
    previous_epoch_id: str | None = None,
    opened_by_transition_id: str | None = None,
    checkpoint_dir=None,
    utility_policy_override: dict | None = None,
) -> EpochState:
    """Construct the frozen :class:`EpochState` at epoch open (plan 02 §5.6).

    *registries* is any object exposing ``components``
    (:class:`ari.rqgm.registry.ComponentRegistry`) and ``prompts``
    (:class:`ari.rqgm.registry.GovernedPromptRegistry`) —
    ``ari.rqgm.store.RqgmRuntimeState`` qualifies. The active maps are
    copied here, so the frozen state never tracks later registry objects.

    *checkpoint_dir* (optional, plan 14 §5.7) roots the adopted
    utility-policy body read; omitted, it falls back to the
    ``ARI_CHECKPOINT_DIR`` run pin.
    """
    state = EpochState(
        epoch_id=format_epoch_id(epoch_seq),
        epoch_seq=int(epoch_seq),
        status="open",
        run_id=str(run_id or ""),
        node_count_at_open=int(node_count),
        previous_epoch_id=previous_epoch_id,
        opened_by_transition_id=opened_by_transition_id,
        active_components=dict(registries.components.active_set()),
        active_prompt_hashes=dict(registries.prompts.active_prompt_hashes()),
        active_prompt_hash_set=sorted(
            registries.prompts.active_prompt_hash_set()),
        # Plan 14 §5.7 — the entire cause-side wiring, in one argument. Both
        # call sites are correct for free: ``store.open_epoch`` passes the
        # base state (no utility_policy entry at epoch 0 ⇒ the cfg
        # fallback), and ``store.run_boundary`` passes the TENTATIVE state
        # built from registry copies AFTER the transaction's events are
        # applied — so a policy adopted in this transaction is the policy
        # the next epoch freezes, with no ordering work and no second pass.
        utility_policy=(
            dict(utility_policy_override)
            if utility_policy_override is not None
            else capture_utility_policy(
                cfg, registries=registries, checkpoint_dir=checkpoint_dir
            )
        ),
        registry_version=registries.prompts.registry_version(),
        policy_settings=capture_policy_settings(cfg),
        execution_identity=capture_execution_identity(cfg),
        epoch_fingerprint="",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    state = replace(
        state,
        policy_fingerprint=policy_fingerprint(state),
        execution_fingerprint=execution_fingerprint(state),
    )
    return replace(state, epoch_fingerprint=epoch_fingerprint(state))
