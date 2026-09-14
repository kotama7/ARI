"""GovernedPromptLoader + evolved-prompt-body storage (RQGM Task 07 §5.5-§5.6).

The loader satisfies the existing :class:`ari.protocols.PromptLoader`
Protocol structurally, so it can stand wherever a
:class:`ari.prompts.FilesystemPromptLoader` stands today:

* ``simple_bfts``: never constructed — the 11 call sites keep building
  ``FilesystemPromptLoader()`` directly, byte-identical to today.
* ``ari_rqgm``: resolves a key against the epoch-frozen active PromptSpec
  view. ``package`` refs delegate to the fallback loader (byte-identical);
  ``checkpoint`` refs read ``{ckpt}/rqgm_prompts/<prompt_id>.md`` through a
  checkpoint-rooted ``FilesystemPromptLoader`` — one loading/hashing scheme,
  no second implementation. Ungoverned keys delegate untouched.

Evolved prompt bodies are WRITE-ONCE: :func:`write_evolved_prompt_body`
refuses to overwrite existing bytes with different bytes
(:class:`PromptImmutabilityError`) — the storage-level face of the
no-in-place-mutation prohibition (plan 07 §1; kernel hash checks are the
authority, this layer simply never creates the tampered state).

Deterministic, pure stdlib: no LLM calls, no network, no randomness (P2).
"""

from __future__ import annotations

from pathlib import Path

from ari.rqgm.events import ACTIVE_STATUSES, hash12
from ari.rqgm.prompt_spec import POLICY_TEMPLATE_REF_KIND, PromptSpec

#: Reserved by Task 02 (``ari.rqgm.store.RQGM_PROMPTS_DIRNAME``); re-stated
#: here import-light so loading a prompt never pulls the state store in.
RQGM_PROMPTS_DIRNAME = "rqgm_prompts"


class PromptImmutabilityError(RuntimeError):
    """An attempt to overwrite existing prompt bytes in place."""


def _resolve_checkpoint_dir(checkpoint_dir) -> Path | None:
    """Explicit arg first, then the ``ARI_CHECKPOINT_DIR`` run pin (the
    ``ari.prompts._provenance`` convention); ``None`` == not resolvable."""
    if checkpoint_dir is not None:
        return Path(checkpoint_dir)
    try:
        from ari.paths import PathManager

        return PathManager.checkpoint_dir_from_env()
    except Exception:
        return None


def checkpoint_prompts_dir(checkpoint_dir) -> Path:
    """``{ckpt}/rqgm_prompts/`` — evolved template bodies (plan 07 §5.6)."""
    return Path(checkpoint_dir) / RQGM_PROMPTS_DIRNAME


def evolved_prompt_path(checkpoint_dir, prompt_id: str) -> Path:
    return checkpoint_prompts_dir(checkpoint_dir) / f"{prompt_id}.md"


def write_evolved_prompt_body(checkpoint_dir, prompt_id: str, text: str) -> Path:
    """Persist one evolved template body, write-once.

    Identical re-writes are idempotent no-ops (resume safety); differing
    bytes for an existing ``prompt_id`` raise
    :class:`PromptImmutabilityError` — evolution always mints a NEW
    ``prompt_id``, never overwrites (plan 07 §1).
    """
    path = evolved_prompt_path(checkpoint_dir, prompt_id)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == text:
            return path
        raise PromptImmutabilityError(
            f"prompt body for {prompt_id!r} already exists with different "
            f"bytes; evolved prompts are write-once (new prompt_id required)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def evolved_policy_path(checkpoint_dir, prompt_id: str) -> Path:
    """``{ckpt}/rqgm_prompts/<prompt_id>.json`` — a governed utility-policy
    body (plan 14 §6.1). A ``.json`` sibling of :func:`evolved_prompt_path`
    under the same already-registered directory, so no new PathManager
    ``META_FILES`` entry and no new ``_INTERNAL_JSON_NAMES`` row is needed."""
    return checkpoint_prompts_dir(checkpoint_dir) / f"{prompt_id}.json"


def write_evolved_policy_body(checkpoint_dir, prompt_id: str, body: str) -> Path:
    """Persist one governed utility-policy body, write-once (plan 14 §5.3).

    *body* is the canonical JSON of the policy body — the bytes whose
    ``hash12`` IS the registered ``prompt_hash`` IS ``utility_policy_hash``.
    Identical re-writes are idempotent no-ops (resume safety); differing
    bytes for an existing ``prompt_id`` raise
    :class:`PromptImmutabilityError`. The exact discipline
    :func:`write_evolved_prompt_body` applies to template bytes: a rewrite
    always mints a NEW ``prompt_id``, never overwrites.
    """
    path = evolved_policy_path(checkpoint_dir, prompt_id)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == body:
            return path
        raise PromptImmutabilityError(
            f"policy body for {prompt_id!r} already exists with different "
            f"bytes; governed policies are write-once (new prompt_id "
            f"required)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def active_prompt_view(specs) -> dict[str, PromptSpec]:
    """``loader key -> PromptSpec`` over the ACTIVE_STATUSES specs.

    The registry view a :class:`GovernedPromptLoader` consumes for one frozen
    epoch. Later entries win per key (registration order is event order, so
    this is deterministic — the Task 02 rollup convention).

    Task 14 (plan 14 §5.3): specs whose ``template_ref.kind`` is ``policy``
    are FILTERED OUT. A utility policy is not a prompt to render; it is a
    policy to freeze. A policy spec carries no loader key, so nothing would
    ever request it — but relying on "nobody asks" would leave the
    ``unknown template_ref kind`` raise in :meth:`GovernedPromptLoader.
    load_versioned` one careless call away. Filtering keeps that raise
    unreachable rather than merely unreached.
    """
    view: dict[str, PromptSpec] = {}
    for spec in specs or ():
        if str(spec.template_ref.get("kind", "")) == POLICY_TEMPLATE_REF_KIND:
            continue
        if spec.status in ACTIVE_STATUSES:
            key = str(spec.template_ref.get("key", "")) or spec.prompt_id
            view[key] = spec
    return view


class GovernedPromptLoader:
    """Resolves keys via the epoch-frozen PromptSpec view; degrades to the
    fallback loader byte-identically for ungoverned keys (plan 07 §5.5).

    Satisfies :class:`ari.protocols.PromptLoader` structurally.
    """

    def __init__(
        self,
        registry_view=None,
        fallback=None,
        *,
        checkpoint_dir=None,
    ) -> None:
        self._view: dict[str, PromptSpec] = dict(registry_view or {})
        if fallback is None:
            from ari.prompts import FilesystemPromptLoader

            fallback = FilesystemPromptLoader()
        self._fallback = fallback
        self._checkpoint_dir = checkpoint_dir

    def load(self, key: str) -> str:
        return self.load_versioned(key)[0]

    def load_versioned(
        self, key: str, version: str | None = None
    ) -> tuple[str, str]:
        spec = self._view.get(key)
        if spec is None:
            # Byte-identical delegation: no spec governs this key.
            return self._fallback.load_versioned(key, version)
        kind = str(spec.template_ref.get("kind", ""))
        ref_key = str(spec.template_ref.get("key", "")) or key
        if kind == "package":
            text, version_id = self._fallback.load_versioned(ref_key, version)
        elif kind == "checkpoint":
            ckpt = _resolve_checkpoint_dir(self._checkpoint_dir)
            if ckpt is None:
                raise FileNotFoundError(
                    f"no checkpoint dir resolvable for evolved prompt "
                    f"{spec.prompt_id!r}"
                )
            from ari.prompts import FilesystemPromptLoader

            text, version_id = FilesystemPromptLoader(
                base=Path(ckpt)
            ).load_versioned(ref_key)
        else:
            raise ValueError(
                f"unknown template_ref kind {kind!r} for {spec.prompt_id!r}"
            )
        if spec.prompt_hash and version_id != spec.prompt_hash:
            # Kernel-grade refusal: never serve bytes that no longer match
            # the frozen spec identity (in-place mutation / tampering).
            raise ValueError(
                f"prompt bytes for {spec.prompt_id!r} hash to {version_id}, "
                f"expected {spec.prompt_hash} (in-place mutation is "
                f"prohibited)"
            )
        return text, version_id


def resolve_checkpoint_prompt_text(
    checkpoint_dir, relative_path: str
) -> tuple[str, str]:
    """Read one checkpoint-scoped prompt body, ``(text, hash12(text))``.

    Shared by :meth:`ari.rqgm.registry.GovernedPromptRegistry.resolve_text`'s
    ``checkpoint_file`` source kind (deferred to this task by Task 02).
    """
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        raise FileNotFoundError(
            f"no checkpoint dir resolvable for prompt body {relative_path!r}"
        )
    text = (Path(ckpt) / relative_path).read_text(encoding="utf-8")
    return text, hash12(text)
