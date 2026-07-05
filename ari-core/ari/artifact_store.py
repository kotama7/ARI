"""By-logical-name artefact store (subtask 010).

:class:`CheckpointArtifactStore` is a minimal concrete
:class:`ari.protocols.stores.ArtifactStore` over the **flat** checkpoint layout:
it maps a logical artefact name to ``{checkpoint_dir}/{name}`` and offers
``put`` / ``get`` / ``exists`` / ``list``.

**Reconciliation with subtask 012.** The pipeline's *type-sniffing* output
persistence — the ``.tex`` → ``result["latex"]``, binary ``.pdf``/``.png`` copy,
and ``generate_figures`` manifest special-cases — was already extracted into
:class:`ari.pipeline.stages.OutputSink` (subtask 012, ``pipeline/stages.py``).
This store does **not** duplicate that suffix-driven writer; ``put`` performs a
plain, unambiguous write (copy a ``Path``, write ``bytes``, write ``str`` text).
Folding ``OutputSink``'s type-sniffing behind this store — so the pipeline
persists through ``ArtifactStore.put`` — is **REVIEW_REQUIRED / deferred**: it
would move logic that 012 already owns and must be done without changing
``OutputSink``'s observable behaviour.

Path derivation stays in the flat checkpoint dir (an on-disk contract). No
``runs/<id>/{artifacts,...}`` consolidation and no ``RuntimePathResolver``
dependency happen here.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ari.protocols.stores import ArtifactStore

log = logging.getLogger(__name__)


class CheckpointArtifactStore(ArtifactStore):
    """Local artefact store rooted at a single flat checkpoint directory.

    Parameters
    ----------
    checkpoint_dir:
        The run's flat checkpoint directory (``{workspace}/checkpoints/{run_id}``).
        Logical names resolve to direct children of this directory.
    """

    def __init__(self, checkpoint_dir: str | Path) -> None:
        self._dir = Path(checkpoint_dir)

    @property
    def checkpoint_dir(self) -> Path:
        return self._dir

    def get(self, name: str) -> Path:
        """Return the on-disk path for logical *name* (existent or not)."""
        return self._dir / name

    def exists(self, name: str) -> bool:
        return (self._dir / name).exists()

    def put(self, name: str, data_or_path: str | bytes | Path) -> Path:
        """Store an artefact under logical *name*; return its on-disk path.

        - ``Path`` (or an existing-file path object): copy the source file's
          bytes verbatim.
        - ``bytes``: write raw bytes.
        - ``str``: write text.

        No suffix-based type-sniffing — that stays in
        :class:`ari.pipeline.stages.OutputSink` (subtask 012).
        """
        dst = self._dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data_or_path, Path):
            shutil.copyfile(data_or_path, dst)
        elif isinstance(data_or_path, bytes):
            dst.write_bytes(data_or_path)
        else:
            dst.write_text(data_or_path)
        log.debug("CheckpointArtifactStore: wrote %s", dst)
        return dst

    def list(self, kind: str | None = None) -> list[Path]:
        """List artefact files directly under the checkpoint dir.

        *kind* filters results: a leading-dot suffix (e.g. ``.pdf``) matches by
        file extension; any other value is treated as a filename glob (e.g.
        ``fig_*``). ``None`` returns every regular file. Results are sorted for
        determinism.
        """
        if not self._dir.is_dir():
            return []
        if kind is None:
            paths = [p for p in self._dir.iterdir() if p.is_file()]
        elif kind.startswith("."):
            paths = [p for p in self._dir.iterdir() if p.is_file() and p.suffix == kind]
        else:
            paths = [p for p in self._dir.glob(kind) if p.is_file()]
        return sorted(paths)
