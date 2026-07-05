"""Storage Protocols + ABC (subtask 010; 006 §3.8-3.10 / §2.2 L1 Foundation).

Structural contracts for ARI's runtime storage I/O, so executors and drivers
reach persistence through injected interfaces rather than scattered, hard-wired
filesystem access. These are the *storage* members of the ``ari.protocols``
roadmap (the concrete realisation of its ``NodeStore`` entry).

Three seams, matching the target-architecture split:

- :class:`CheckpointStore` — **Protocol** (one concrete impl expected, §3.9):
  the run's ``tree.json`` / ``nodes_tree.json`` / ``results.json`` JSON I/O with
  the *exact* current layout, key order, ``indent=2, ensure_ascii=False``
  formatting, and 1.0 s throttled incremental writer. Satisfied structurally by
  :class:`ari.checkpoint.JsonCheckpointStore` (no subclassing), exactly how
  :class:`ari.evaluator.llm_evaluator.LLMEvaluator` satisfies
  :class:`ari.protocols.evaluator.Evaluator`.
- :class:`TraceStore` — **Protocol** (one concrete impl + in-memory test double,
  §3.10): per-node report read/write and append-only execution traces. Satisfied
  structurally by :class:`ari.trace_store.JsonlTraceStore`. This is the read/write
  seam subtask 011 deferred here for the BFTS node-report reads.
- :class:`ArtifactStore` — **ABC** (layout may vary across local/registry
  backends, §3.8): read/write experiment artefacts by *logical name*. Concrete
  :class:`ari.artifact_store.CheckpointArtifactStore` targets the flat checkpoint
  layout.

**No on-disk contract changes here.** Signatures mirror existing behaviour so the
concrete classes are pure wrappers; introducing these interfaces adds no LLM call
and changes no file name, key order, or throttle timing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable


@runtime_checkable
class CheckpointStore(Protocol):
    """Read/write the run's checkpoint JSON with the exact current layout.

    Mirrors the module functions in :mod:`ari.checkpoint` one-to-one so the
    concrete :class:`ari.checkpoint.JsonCheckpointStore` is a pure wrapper and
    the retained module-level functions stay byte-identical delegating shims.
    ``checkpoint_dir`` is passed per call (the store owns only the incremental
    writer's throttle bookkeeping, not a bound directory).
    """

    def save_tree_json(self, checkpoint_dir: str | Path, tree: dict) -> None: ...

    def save_nodes_tree_json(self, checkpoint_dir: str | Path, nodes: dict) -> None: ...

    def save_results_json(self, checkpoint_dir: str | Path, results: dict) -> None: ...

    def load_tree_json(self, checkpoint_dir: str | Path) -> dict | None: ...

    def load_nodes_tree_json(self, checkpoint_dir: str | Path) -> dict | None: ...

    def load_nodes_tree(self, checkpoint_dir: str | Path) -> dict | None:
        """3-tier precedence ``tree.json → nodes_tree.json → newest non-empty
        ``node_*/tree.json``, preserved from the module function."""
        ...

    def save_tree_incremental(
        self,
        checkpoint_dir: str | Path,
        writer: Callable[[], None],
        *,
        force: bool = False,
        throttle_sec: float = 1.0,
    ) -> None:
        """Throttled (default 1.0 s), lock-serialised incremental writer."""
        ...


@runtime_checkable
class TraceStore(Protocol):
    """Append/read execution traces and per-node reports.

    Decouples the executors that emit traces/reports from the on-disk layout.
    ``write_node_report`` / ``read_node_report`` / ``read_sibling_reports`` are
    the seam subtask 011 (BFTS strategy/executor split) deferred to this subtask;
    they operate on the same ``{node_work_dir}/node_report.json`` files that
    :mod:`ari.orchestrator.bfts` reads and :mod:`ari.cli.bfts_loop` writes today,
    byte-identically.
    """

    def append_trace(self, node_id: str, entry: str | dict) -> None: ...

    def read_trace(self, node_id: str) -> list: ...

    def write_node_report(self, node_id: str, report: dict) -> Path: ...

    def read_node_report(self, node_id: str) -> dict | None: ...

    def read_sibling_reports(
        self, node_ids: Iterable[Any]
    ) -> dict[str, dict]: ...


class ArtifactStore(ABC):
    """Read/write experiment artefacts by *logical name* (§3.8).

    ABC (not Protocol) because the on-disk layout may vary across a local flat
    checkpoint (:class:`ari.artifact_store.CheckpointArtifactStore`) and a future
    registry-backed store. Layout derivation is delegated to the composed
    ``PathManager`` / checkpoint dir; this contract stays domain-agnostic.

    The pipeline's *type-sniffing* output persistence (``.tex``/``.pdf``/figures
    special-cases) is owned by :class:`ari.pipeline.stages.OutputSink`
    (subtask 012) and is **not** duplicated here — this store is the
    by-logical-name access seam only.
    """

    @abstractmethod
    def put(self, name: str, data_or_path: str | bytes | Path) -> Path:
        """Store an artefact under logical *name*; return its on-disk path.

        ``Path`` copies the source file; ``bytes`` writes raw bytes; ``str``
        writes text. No suffix-based type-sniffing (that stays in ``OutputSink``).
        """
        ...

    @abstractmethod
    def get(self, name: str) -> Path:
        """Return the on-disk path for logical *name* (whether or not it exists)."""
        ...

    @abstractmethod
    def exists(self, name: str) -> bool: ...

    @abstractmethod
    def list(self, kind: str | None = None) -> list[Path]:
        """List artefact paths, optionally filtered by *kind* (a suffix like
        ``.pdf`` or a filename glob)."""
        ...
