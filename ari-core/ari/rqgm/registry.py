"""ComponentRegistry + GovernedPromptRegistry (RQGM Task 02, plan 02 §5.3).

**Naming**: the on-disk / record name stays ``PromptRegistry`` (spec
vocabulary) but the Python class is :class:`GovernedPromptRegistry` to avoid
colliding with the existing *discovery catalogue*
:class:`ari.prompts.registry.PromptRegistry`. The governed registry tracks
prompt *identity + status + hash* for epoch governance and **delegates** all
template loading/hashing to the existing loader — it never duplicates the
catalogue (see the cross-reference in ``ari/prompts/registry.py``'s scope:
enumeration/placeholders stay there; governance state lives here).

Storage-layer rule (global invariant 10, enforced at the lowest level):
registries expose **no status setter**. Entries are frozen dataclasses and the
only mutation path is replaying transition events appended through
:class:`ari.rqgm.store.EpochTransaction` (epoch boundary) or the
``emergency_quarantine`` mid-epoch exception — both owned by
:class:`ari.rqgm.store.RqgmStateStore`. Which status changes are *legal* is
Task 09's transition table; Task 04's kernel validates them. This module only
stores.

Deterministic, pure stdlib: no LLM calls, no network, no randomness (P2).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from ari.rqgm.events import (
    ACTIVE_STATUSES,
    canonical_json,
    hash12,
)

log = logging.getLogger(__name__)


# ── entries (frozen: no in-place status mutation possible) ──────────────────


@dataclass(frozen=True)
class ComponentEntry:
    """One governed component (plan 02 §6 registry snapshot shape).

    ``capabilities`` is the Task 11 §6.1 extension (agreed with this owning
    module): the per-entry ``can_*`` flag / ``allowed_targets`` /
    ``forbidden_targets`` declaration consumed by the kernel's
    ``validate_capability`` / ``validate_authority_non_expansion``. Flags
    default to absent == ``False`` (deny-by-default); the flag vocabulary
    and tier constraints live in :mod:`ari.rqgm.meta_rules`.
    """

    component_id: str
    role: str
    tier: str
    status: str
    prompt_id: str | None = None
    epoch_id_registered: str = ""
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    capabilities: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "tier": self.tier,
            "status": self.status,
            "prompt_id": self.prompt_id,
            "epoch_id_registered": self.epoch_id_registered,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
            "capabilities": dict(self.capabilities),
        }


@dataclass(frozen=True)
class GovernedPromptEntry:
    """One governed prompt version. Text is referenced by *source*, never
    inlined: ``{"kind": "committed_template", "key": <loader key>}`` today;
    ``{"kind": "checkpoint_file", "path": <ckpt-relative>}`` is reserved for
    Task 07 evolved prompts under ``rqgm_prompts/``."""

    prompt_id: str
    role: str
    status: str
    prompt_hash: str
    prompt_sha256: str
    source: dict = field(default_factory=dict)
    spec_ref: str | None = None
    epoch_id_registered: str = ""
    created_at: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "role": self.role,
            "status": self.status,
            "prompt_hash": self.prompt_hash,
            "prompt_sha256": self.prompt_sha256,
            "source": dict(self.source),
            "spec_ref": self.spec_ref,
            "epoch_id_registered": self.epoch_id_registered,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
        }


# ── read-only registries ────────────────────────────────────────────────────


class ComponentRegistry:
    """Read-only view over the replayed component entries.

    Mutation happens only by rebuilding from the event log (plan 02 §5.3);
    there is deliberately no ``set_status``-style API on this class.
    """

    def __init__(self, entries: dict[str, ComponentEntry] | None = None) -> None:
        self._entries: dict[str, ComponentEntry] = dict(entries or {})

    def get(self, component_id: str) -> ComponentEntry | None:
        return self._entries.get(component_id)

    def entries(self) -> dict[str, ComponentEntry]:
        """Copy of the id → entry map (insertion order = event order)."""
        return dict(self._entries)

    def active_set(self) -> dict[str, str]:
        """``role -> component_id`` for every role with an entry whose status
        is in :data:`ari.rqgm.events.ACTIVE_STATUSES`. When several entries of
        one role are active, the latest-registered wins (replay order is file
        order, so this is deterministic)."""
        out: dict[str, str] = {}
        for entry in self._entries.values():
            if entry.status in ACTIVE_STATUSES:
                out[entry.role] = entry.component_id
        return out


class GovernedPromptRegistry:
    """Read-only view over the replayed governed-prompt entries.

    Not the discovery catalogue: see module docstring for the
    ``ari.prompts.registry.PromptRegistry`` distinction. Template text is
    resolved by *delegation* to :class:`ari.prompts.FilesystemPromptLoader`,
    keeping the ``sha256(text)[:12]`` scheme the single source of prompt
    identity (plan 02 §5.4).
    """

    def __init__(
        self, entries: dict[str, GovernedPromptEntry] | None = None
    ) -> None:
        self._entries: dict[str, GovernedPromptEntry] = dict(entries or {})

    def get(self, prompt_id: str) -> GovernedPromptEntry | None:
        return self._entries.get(prompt_id)

    def entries(self) -> dict[str, GovernedPromptEntry]:
        """Copy of the id → entry map (insertion order = event order)."""
        return dict(self._entries)

    def active_prompt_hashes(self) -> dict[str, str]:
        """``role -> prompt_hash`` over the active statuses (latest wins).

        A ROLE→INCUMBENT rollup for prompt RESOLUTION (which prompt a role
        renders now). It is NOT the full governed set: a role with several
        active prompts (e.g. ``generator`` has bfts_expand + the proposal
        cheap/mutation/prior_art templates) collapses to one hash here. For the
        epoch-invariance membership test use :meth:`active_prompt_hash_set`.
        """
        out: dict[str, str] = {}
        for entry in self._entries.values():
            if entry.status in ACTIVE_STATUSES:
                out[entry.role] = entry.prompt_hash
        return out

    def active_prompt_hash_set(self) -> set[str]:
        """EVERY active prompt hash (not role-collapsed) — the frozen governed
        set an epoch's records must be scored under (pillar-1 / CK-EPO-001).
        ``active_prompt_hashes().values()`` under-covers roles with multiple
        active prompts, false-flagging governed non-incumbent prompts."""
        return {
            entry.prompt_hash
            for entry in self._entries.values()
            if entry.status in ACTIVE_STATUSES and entry.prompt_hash
        }

    def resolve_text(
        self, prompt_id: str, *, checkpoint_dir: str | Path | None = None
    ) -> tuple[str, str]:
        """Return ``(text, prompt_hash)`` for *prompt_id* by source kind.

        ``committed_template`` delegates to
        ``FilesystemPromptLoader.load_versioned`` (the returned ``version_id``
        IS the registry ``prompt_hash`` — pinned by tests).
        ``checkpoint_file`` (Task 07 evolved prompts) reads the write-once
        body under the checkpoint root (*checkpoint_dir* arg, else the
        ``ARI_CHECKPOINT_DIR`` run pin) and REFUSES bytes whose ``hash12``
        no longer matches the registered ``prompt_hash`` — the storage face
        of the no-in-place-mutation prohibition (kernel checks are the
        authority).

        ``policy`` (Task 14 governed utility policies, plan 14 §5.3) reads
        the write-once canonical-JSON body under the same directory with the
        IDENTICAL refusal, so it shares that branch verbatim rather than
        duplicating it (plan 14 R7's "a third kind is a third code path"
        concern, answered by not making it one). The kinds stay distinct in
        the vocabulary because a policy is never RENDERED: it carries no
        loader key and ``prompt_loader.active_prompt_view`` filters it out.

        **Why a policy is a "prompt" at all**: see the ``TEMPLATE_REF_KINDS``
        docstring in :mod:`ari.rqgm.prompt_spec` (plan 14 §5.3 decision) —
        its ``prompt_hash`` IS ``utility_policy_hash`` by construction, and
        the retirement→repair join and the epoch freeze seam are both
        prompt-keyed, so registering it here costs one row and duplicates
        nothing.
        """
        entry = self._entries.get(prompt_id)
        if entry is None:
            raise KeyError(prompt_id)
        kind = str(entry.source.get("kind", ""))
        if kind == "committed_template":
            from ari.prompts import FilesystemPromptLoader

            return FilesystemPromptLoader().load_versioned(
                str(entry.source.get("key", ""))
            )
        if kind in ("checkpoint_file", "policy"):
            from ari.rqgm.prompt_loader import resolve_checkpoint_prompt_text

            text, version_id = resolve_checkpoint_prompt_text(
                checkpoint_dir, str(entry.source.get("path", ""))
            )
            if entry.prompt_hash and version_id != entry.prompt_hash:
                raise ValueError(
                    f"prompt bytes for {prompt_id!r} hash to {version_id}, "
                    f"expected {entry.prompt_hash} (in-place mutation is "
                    f"prohibited)"
                )
            return text, version_id
        raise ValueError(f"unknown prompt source kind {kind!r} for {prompt_id}")

    def registry_version(self) -> str:
        """``hash12(canonical_json(sorted (prompt_id, role, status,
        prompt_sha256) tuples))`` — plan 02 §5.4, deterministic (P2).

        v1 covers prompt entries only (per the plan's tuple shape); component
        identity enters the epoch fingerprint via ``active_components``.
        """
        rows = sorted(
            [e.prompt_id, e.role, e.status, e.prompt_sha256]
            for e in self._entries.values()
        )
        return hash12(canonical_json(rows))

    def record_use(
        self,
        prompt_id: str,
        *,
        model: str = "",
        node_id: str = "",
        phase: str = "",
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        """Stamp one managed-prompt call with registry provenance (§5.5).

        Fills ``PromptUseRecord``'s two reserved fields (``prompt_version`` =
        the governed ``prompt_id``, ``prompt_registry_version``) with zero
        schema break. Under ``simple_bfts`` nothing calls this, so the fields
        stay ``None`` exactly as today. Best-effort like every provenance
        writer: unknown ids are ignored, never raised.
        """
        entry = self._entries.get(prompt_id)
        if entry is None:
            return
        from ari.prompts import record_prompt_use

        record_prompt_use(
            str(entry.source.get("key") or prompt_id),
            entry.prompt_hash,
            model=model,
            node_id=node_id,
            phase=phase,
            prompt_version=prompt_id,
            prompt_registry_version=self.registry_version(),
            checkpoint_dir=checkpoint_dir,
        )


# ── event application (replay-only mutation path) ───────────────────────────


def build_prompt_registration_payload(
    prompt_id: str,
    role: str,
    *,
    source_key: str,
    status: str = "candidate",
    epoch_id: str = "",
    spec_ref: str | None = None,
    source_refs: tuple[str, ...] | list[str] = (),
    loader=None,
) -> dict:
    """Build a ``prompt_registered`` event payload for a committed template.

    Loads the template through the (injectable) loader and computes both
    hashes from the raw template bytes: ``prompt_sha256`` (full 64-hex) and
    ``prompt_hash`` == ``load_versioned``'s ``sha256(text)[:12]`` — one
    scheme, no second implementation (plan 02 §5.4).
    """
    if loader is None:
        from ari.prompts import FilesystemPromptLoader

        loader = FilesystemPromptLoader()
    text, version_id = loader.load_versioned(source_key)
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if full[:12] != version_id:
        # Defensive: a custom loader with a divergent scheme would poison
        # registry identity; refuse rather than record a split-brain hash.
        raise ValueError(
            f"loader version_id {version_id!r} is not sha256[:12] of the text"
        )
    return {
        "prompt_id": prompt_id,
        "role": role,
        "status": status,
        "prompt_hash": version_id,
        "prompt_sha256": full,
        "source": {"kind": "committed_template", "key": source_key},
        "spec_ref": spec_ref,
        "epoch_id": epoch_id,
        "source_refs": list(source_refs),
    }


def apply_registry_event(
    components: dict[str, ComponentEntry],
    prompts: dict[str, GovernedPromptEntry],
    event_type: str,
    payload: dict,
    *,
    created_at: str = "",
) -> None:
    """Apply one committed transition event to the entry maps (replay path).

    This is the ONLY code that changes entry status, and it only ever runs
    over events already persisted in ``rqgm_transitions.jsonl``. Storage
    accepts any from/to statuses — legality is Task 09/04's concern. Unknown
    ids in status changes are logged and skipped (absence-tolerant replay).
    """
    if event_type == "component_registered":
        entry = ComponentEntry(
            component_id=str(payload.get("component_id", "")),
            role=str(payload.get("role", "")),
            tier=str(payload.get("tier", "institutional")),
            status=str(payload.get("status", "candidate")),
            prompt_id=payload.get("prompt_id"),
            epoch_id_registered=str(payload.get("epoch_id", "")),
            created_at=created_at,
            source_refs=tuple(payload.get("source_refs") or ()),
            capabilities=dict(payload.get("capabilities") or {}),
        )
        components[entry.component_id] = entry
    elif event_type == "prompt_registered":
        pentry = GovernedPromptEntry(
            prompt_id=str(payload.get("prompt_id", "")),
            role=str(payload.get("role", "")),
            status=str(payload.get("status", "candidate")),
            prompt_hash=str(payload.get("prompt_hash", "")),
            prompt_sha256=str(payload.get("prompt_sha256", "")),
            source=dict(payload.get("source") or {}),
            spec_ref=payload.get("spec_ref"),
            epoch_id_registered=str(payload.get("epoch_id", "")),
            created_at=created_at,
            source_refs=tuple(payload.get("source_refs") or ()),
        )
        prompts[pentry.prompt_id] = pentry
    elif event_type == "component_status_change":
        cid = str(payload.get("component_id", ""))
        if cid in components:
            components[cid] = replace(
                components[cid], status=str(payload.get("to_status", ""))
            )
        else:
            log.warning("component_status_change for unknown id %s skipped", cid)
    elif event_type == "prompt_status_change":
        pid = str(payload.get("prompt_id", ""))
        if pid in prompts:
            prompts[pid] = replace(
                prompts[pid], status=str(payload.get("to_status", ""))
            )
        else:
            log.warning("prompt_status_change for unknown id %s skipped", pid)
    elif event_type == "emergency_quarantine":
        # The sole mid-epoch mutation (spec emergency exception): force the
        # target to `quarantine` (or the recorded to_status).
        to_status = str(payload.get("to_status", "quarantine"))
        cid = payload.get("component_id")
        pid = payload.get("prompt_id")
        if cid and cid in components:
            components[cid] = replace(components[cid], status=to_status)
        if pid and pid in prompts:
            prompts[pid] = replace(prompts[pid], status=to_status)
    # epoch_* / transaction events carry no registry mutation.
