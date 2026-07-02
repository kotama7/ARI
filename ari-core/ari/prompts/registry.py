"""PromptRegistry — Phase 7 / subtask 038 (``docs/refactoring/subtasks/038_introduce_prompt_registry_and_loader.md``).

A discoverable, self-validating catalogue of prompt-template keys layered
**over** — and delegating every file read to — the already-shipped
:class:`ari.prompts._loader.FilesystemPromptLoader`. This module *wraps, does
not replace,* that loader: ``get`` == ``loader.load``, ``get_versioned`` ==
``loader.load_versioned``, so the KEEP contract of the loader (including
``load_versioned``'s ``sha256(text)[:12]`` scheme) is untouched and every
rendered prompt stays byte-identical.

What the registry adds over the loader (which only answers "given a key, read
its file"):

* enumeration — :meth:`PromptRegistry.keys` lists every externalized ``.md``
  key discovered under :func:`ari.prompts._loader.package_prompts_root`;
* placeholder introspection — :meth:`PromptRegistry.placeholders` derives a
  template's ``str.format`` field names *from the template itself* (no second
  source of truth / manifest), tolerant of ``{{``/``}}`` JSON escapes;
* a machine-readable :class:`PromptEntry` describe surface a future
  ``check_prompts.py`` gate can consume.

Determinism (design principle P2): pure stdlib only (``string``, ``pathlib``,
``dataclasses``) — no LLM calls, no network, no wall-clock/randomness; discovery
and hashing are machine-stable.

Tolerance policy (§7.2): ``get`` / ``get_versioned`` / ``placeholders`` do
**not** require :meth:`has` — a key that arrives via config (e.g. the
config-injected ``BFTSConfig.select_prompt`` / ``expand_select_prompt``) still
delegates to the loader, so only the loader's own ``FileNotFoundError`` (a
genuinely missing ``.md``) ever propagates.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

from ari.prompts._loader import (
    FilesystemPromptLoader,
    PromptLoader,
    package_prompts_root,
)


def _extract_placeholders(text: str) -> frozenset[str]:
    """Return the ``str.format`` field names referenced in *text*.

    Parsed with :meth:`string.Formatter.parse` (stdlib): it yields
    ``field_name is None`` for literal text and correctly skips ``{{`` / ``}}``
    escapes, so literal JSON braces (common in the evaluator/orchestrator
    prompts that request JSON output) never register as placeholders. Auto-
    numbering ``{}`` yields an empty field name and is ignored. A compound
    field (``{a.b}``, ``{a[0]}``) is reduced to its leading identifier ``a`` —
    the name ``str.format`` actually consumes from the keyword arguments.
    """
    names: set[str] = set()
    for _literal, field_name, _format_spec, _conversion in string.Formatter().parse(text):
        if not field_name:
            continue
        root = field_name.replace("[", ".").split(".", 1)[0]
        if root:
            names.add(root)
    return frozenset(names)


@dataclass(frozen=True)
class PromptEntry:
    """Immutable catalogue record describing one prompt key.

    ``discovered`` is ``False`` for a config-injected key the registry resolved
    by delegation but did not statically discover under the prompts root.
    """

    key: str
    path: Path
    discovered: bool
    version_id: str
    placeholders: frozenset[str]


class PromptRegistry:
    """Discovery + placeholder catalogue over a :class:`PromptLoader`.

    The registry delegates all I/O to an injected loader (default
    :class:`FilesystemPromptLoader`), mirroring the loader's own test-swap
    design, and adds no new read/hash semantics of its own.
    """

    def __init__(
        self,
        loader: PromptLoader | None = None,
        root: Path | None = None,
    ) -> None:
        self._root = root or package_prompts_root()
        self._loader = loader if loader is not None else FilesystemPromptLoader(self._root)
        self._keys = self._discover(self._root)

    @staticmethod
    def _discover(root: Path) -> frozenset[str]:
        """Discover every ``*.md`` key under *root* (excluding ``README.md``).

        Key = the path relative to *root* minus the ``.md`` suffix, POSIX-style
        (``orchestrator/bfts_expand.md`` -> ``orchestrator/bfts_expand``).
        """
        keys: set[str] = set()
        for path in root.rglob("*.md"):
            if path.name == "README.md":
                continue
            keys.add(path.relative_to(root).with_suffix("").as_posix())
        return frozenset(keys)

    def keys(self) -> list[str]:
        """Return the sorted list of discovered prompt keys."""
        return sorted(self._keys)

    def has(self, key: str) -> bool:
        """Return whether *key* was statically discovered under the root."""
        return key in self._keys

    def get(self, key: str) -> str:
        """Return the raw template text for *key* (delegates to the loader)."""
        return self._loader.load(key)

    def get_versioned(self, key: str) -> tuple[str, str]:
        """Return ``(text, version_id)`` for *key* (delegates to the loader).

        ``version_id`` is the loader's ``sha256(text)[:12]`` — preserved exactly.
        """
        return self._loader.load_versioned(key)

    def placeholders(self, key: str) -> set[str]:
        """Return the ``str.format`` placeholder names declared by *key*'s template."""
        return set(_extract_placeholders(self.get(key)))

    def describe(self, key: str) -> PromptEntry:
        """Return a :class:`PromptEntry` for *key* (reads the template via the loader)."""
        text, version_id = self.get_versioned(key)
        return PromptEntry(
            key=key,
            path=self._root / f"{key}.md",
            discovered=self.has(key),
            version_id=version_id,
            placeholders=_extract_placeholders(text),
        )
