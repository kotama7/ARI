"""``ari._factory`` — a minimal, import-driven string→impl registry (subtask 014).

**Name-collision note (load-bearing).** This module is *not* :mod:`ari.registry`.
``ari.registry`` is the **HTTP artifact-registry** FastAPI server wired to the
``ari registry`` CLI (``ari/registry/app.py::build_app``); it is a live external
contract and is left untouched. ``ari._factory`` is an in-tree
dependency-injection / factory helper that unifies ARI's previously ad-hoc
string-keyed dispatchers behind one uniform lookup with a single unknown-key
error path and one canonical key list. The leading underscore marks it internal
(it is deliberately **not** part of ``ari.public.*``).

Design (subtask 014 §7.1):

- :class:`BaseRegistry` holds a ``dict[str, value]`` of eagerly-registered
  values *and* a ``dict[str, loader]`` of lazily-resolved factories, so
  optional-dependency backends (``zenodo`` / ``gh``) import only on demand and
  still degrade to their domain error on ``ImportError``.
- Registration is **import-driven** (in-tree ``register`` / ``register_lazy``
  calls). There is deliberately **no** ``importlib.metadata`` entry-point plugin
  system (none exists in this repo; ``pyproject.toml`` declares only the
  ``ari = ari.cli:app`` console script).
- :meth:`keys` is the single source of truth a parity test can compare against
  ``EvaluatorConfig.composite`` (a ``Literal``) and the ``publish.schema.json``
  backend-name enum, so the two can never silently drift again.

Current adopters: the evaluator composite formulas
(``ari.evaluator.llm_evaluator``) and the publish backends
(``ari.publish``). ``ari.llm.routing.resolve_litellm_model`` is intentionally
**not** adopted (it transforms a model id rather than constructing an object and
is public-adjacent — see subtask 014 §7.2 step 3).
"""
from __future__ import annotations

from typing import Callable, Generic, Iterator, TypeVar

T = TypeVar("T")


class BaseRegistry(Generic[T]):
    """A tiny typed, string-keyed registry supporting eager + lazy entries.

    Two registration modes:

    - :meth:`register` stores an eager *value*; :meth:`resolve` returns it
      unchanged (used for the evaluator composite *functions*, which are the
      values themselves).
    - :meth:`register_lazy` stores a zero-arg *loader*; :meth:`resolve` invokes
      it on each call (used for publish backends, whose modules must import
      lazily so optional dependencies stay optional). The loader is re-invoked
      each ``resolve`` — identical to the original ``if/elif`` behaviour, since
      Python caches the imported module in ``sys.modules``.

    An unknown key raises ``error_cls`` (default :class:`KeyError`) with a
    message that lists the valid keys — the single uniform "unknown key" path
    that replaces the three hand-rolled ones.
    """

    def __init__(self, name: str, *, error_cls: type[Exception] = KeyError) -> None:
        self._name = name
        self._error_cls = error_cls
        self._values: dict[str, T] = {}
        self._loaders: dict[str, Callable[[], T]] = {}

    # ── registration ─────────────────────────────────────────────────────
    def register(self, key: str, value: T) -> None:
        """Register an eager value returned as-is by :meth:`resolve`."""
        self._values[key] = value

    def register_lazy(self, key: str, loader: Callable[[], T]) -> None:
        """Register a zero-arg loader invoked by :meth:`resolve` on demand."""
        self._loaders[key] = loader

    # ── lookup ───────────────────────────────────────────────────────────
    def resolve(self, key: str) -> T:
        """Return the eager value for ``key`` or the lazy loader's result.

        Raises ``error_cls`` (listing the valid keys) if ``key`` is unknown.
        """
        if key in self._values:
            return self._values[key]
        if key in self._loaders:
            return self._loaders[key]()
        raise self._error_cls(
            f"unknown {self._name} key: {key!r}; valid options: {sorted(self.keys())}"
        )

    def keys(self) -> list[str]:
        """Canonical valid-key list (eager + lazy) — the single source of truth."""
        return list(self._values) + [k for k in self._loaders if k not in self._values]

    def as_dict(self) -> dict[str, T]:
        """Snapshot of the eagerly-registered ``{key: value}`` pairs.

        Used to expose a back-compat plain-``dict`` alias (e.g. ``_COMPOSITES``)
        for callers/tests that import the mapping directly. Lazy entries are
        omitted because materialising them may trigger optional imports.
        """
        return dict(self._values)

    def __contains__(self, key: object) -> bool:
        return key in self._values or key in self._loaders

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"BaseRegistry(name={self._name!r}, keys={sorted(self.keys())})"


__all__ = ["BaseRegistry"]
