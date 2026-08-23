"""GUI config document store (gui_refresh task 05 Wave 3b, ADR-12).

Durable server-side storage for the three GUI-only configuration scopes —
project defaults, run templates, run drafts.  Documents live under
``{workspace_root}/gui_store/``, a sibling of
``checkpoints/`` (ADR-12)::

    {workspace_root}/gui_store/
    ├── project_config.json              # the single default project's config
    ├── run_templates/{template_id}.json
    ├── run_drafts/{draft_id}.json
    └── launches/{idempotency_key}.json  # idempotent-launch records (Wave 4e)

Why there (ADR-12): workspace-scoped — no global home-directory ARI dir
(v0.5.0 principle), survives checkpoint deletion (templates outlive runs), additive,
and **never read by the CLI / simple_bfts path** — launch materializes every
effective value into the checkpoint exactly as today.  This module is a
GUI-only convenience layer; nothing in ``ari/`` outside ``ari.viz.v1``
imports it.

Storage contract:

- every document is stored as the envelope
  ``{"schema_version": 1, "kind": "<kind>", "revision": n, "body": {...}}``
  serialized deterministically (``sort_keys=True``, 2-space indent, trailing
  newline) — P2: byte-stable for identical content;
- ``revision`` is a per-document integer starting at 1 and incremented on
  every successful write; it maps 1:1 to the HTTP ``ETag``/``If-Match``
  optimistic-concurrency scheme (ADR-12) — ``write(expected_revision=k)``
  raises :class:`RevisionConflict` unless the current revision is exactly
  ``k`` (``0`` == "document must not exist yet");
- writes are atomic and durable: same-directory temp file + ``fsync`` +
  ``os.replace`` + best-effort directory fsync — a crash mid-write leaves
  the previous document intact, so a torn write can never be observed (the
  same write discipline the secret path uses);
- owner-only permissions: files ``0o600``, directories ``0o700`` — same
  discipline as the secret write path even though these documents hold
  config, not secrets;
- document IDs are supplied by the caller (deterministic — the store never
  invents IDs) and validated against ``^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$``,
  which structurally excludes path traversal (no ``/``, no ``.``) — a
  document id can never escape the store root.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from ...paths import RuntimePathResolver

SCHEMA_VERSION = 1

# ── document kinds ──────────────────────────────────────────────────────────

KIND_PROJECT_CONFIG = "project_config"  # singleton (ADR-08 default project)
KIND_RUN_TEMPLATE = "run_template"
KIND_RUN_DRAFT = "run_draft"
# Wave 4e: idempotent-launch records — one document per
# idempotency key mapping key -> {run_id, checkpoint_path, draft_id} so a
# duplicate POST /api/v1/runs replays the SAME run instead of spawning a
# second subprocess (double-click safety survives a server restart).
KIND_LAUNCH = "launch"

KINDS: tuple[str, ...] = (
    KIND_PROJECT_CONFIG,
    KIND_RUN_TEMPLATE,
    KIND_RUN_DRAFT,
    KIND_LAUNCH,
)

# kind -> subdirectory under gui_store/ (the singleton has none).
_KIND_SUBDIRS: dict[str, str] = {
    KIND_RUN_TEMPLATE: "run_templates",
    KIND_RUN_DRAFT: "run_drafts",
    KIND_LAUNCH: "launches",
}

# Caller-supplied document IDs: no separators, no dots — traversal is
# structurally impossible, and ``{doc_id}.json`` round-trips via ``Path.stem``.
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# In-process read-modify-write serialization (the viz server is a
# ThreadingHTTPServer; cross-process safety is the optimistic revision check).
_LOCK = threading.Lock()


class RevisionConflict(Exception):
    """Optimistic-concurrency failure: on-disk revision != expected."""

    def __init__(
        self, kind: str, doc_id: str | None, expected: int, actual: int
    ) -> None:
        self.kind = kind
        self.doc_id = doc_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"revision conflict on {kind}"
            f"{f'/{doc_id}' if doc_id else ''}: "
            f"expected {expected}, found {actual}"
        )


class CorruptDocument(Exception):
    """The on-disk document is not a valid store envelope (bad JSON, or a
    missing/invalid ``revision``).  An unconditional ``write`` (i.e.
    ``expected_revision=None``) may overwrite it as the repair path."""


class GuiStore:
    """Document store rooted at ``{workspace_root}/gui_store/`` (ADR-12)."""

    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root).resolve() / "gui_store"

    @classmethod
    def from_env(cls) -> "GuiStore":
        """Build a store from the canonical workspace root — the same
        :meth:`ari.paths.RuntimePathResolver.resolve_workspace_root` policy
        every other workspace consumer uses (``ARI_CHECKPOINT_DIR`` wins)."""
        return cls(RuntimePathResolver.resolve_workspace_root())

    @property
    def root(self) -> Path:
        """``{workspace_root}/gui_store/`` (may not exist until first write)."""
        return self._root

    # ── path mapping / validation ─────────────────────────────────────

    def _path_for(self, kind: str, doc_id: str | None) -> Path:
        if kind == KIND_PROJECT_CONFIG:
            if doc_id is not None:
                raise ValueError(
                    "project_config is a singleton — doc_id must be None"
                )
            return self._root / "project_config.json"
        subdir = _KIND_SUBDIRS.get(kind)
        if subdir is None:
            raise ValueError(f"unknown document kind: {kind!r}")
        if doc_id is None or not _DOC_ID_RE.fullmatch(doc_id):
            raise ValueError(
                f"invalid doc_id {doc_id!r} for kind {kind!r} "
                "(must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$)"
            )
        return self._root / subdir / f"{doc_id}.json"

    # ── read ──────────────────────────────────────────────────────────

    def read(
        self, kind: str, doc_id: str | None = None
    ) -> tuple[dict, int] | None:
        """Return ``(doc, revision)`` for one document, or ``None`` when it
        does not exist.  ``doc`` is the full stored envelope; ``revision``
        is ``doc["revision"]`` surfaced for the ETag mapping."""
        return self._load(self._path_for(kind, doc_id))

    @staticmethod
    def _load(path: Path) -> tuple[dict, int] | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            doc = json.loads(raw)
        except ValueError as e:
            raise CorruptDocument(f"{path.name}: invalid JSON: {e}") from e
        rev = doc.get("revision") if isinstance(doc, dict) else None
        if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1:
            raise CorruptDocument(
                f"{path.name}: missing/invalid integer revision"
            )
        return doc, rev

    # ── write (atomic, optimistic concurrency) ────────────────────────

    def write(
        self,
        kind: str,
        body: dict,
        doc_id: str | None = None,
        expected_revision: int | None = None,
    ) -> int:
        """Persist ``body`` as the new content of one document; return the
        new revision.

        ``expected_revision=None`` writes unconditionally (last-write-wins,
        and the only path allowed to overwrite a :class:`CorruptDocument`).
        ``expected_revision=k`` requires the current on-disk revision to be
        exactly ``k`` (``0`` == the document must not exist yet) and raises
        :class:`RevisionConflict` otherwise — the ``If-Match`` mapping.
        """
        if not isinstance(body, dict):
            raise ValueError("body must be a dict")
        path = self._path_for(kind, doc_id)
        with _LOCK:
            try:
                loaded = self._load(path)
            except CorruptDocument:
                if expected_revision is not None:
                    raise
                loaded = None  # unconditional write repairs a corrupt doc
            current = loaded[1] if loaded is not None else 0
            if expected_revision is not None and expected_revision != current:
                raise RevisionConflict(kind, doc_id, expected_revision, current)
            new_rev = current + 1
            doc = {
                "schema_version": SCHEMA_VERSION,
                "kind": kind,
                "revision": new_rev,
                "body": body,
            }
            self._ensure_dirs(path.parent)
            data = (
                json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n"
            ).encode("utf-8")
            self._atomic_write(path, data)
            return new_rev

    def delete(
        self,
        kind: str,
        doc_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        """Remove one document; return ``True`` when it existed.

        With ``expected_revision`` set the same optimistic check as
        :meth:`write` applies (a missing document has revision ``0``).
        """
        path = self._path_for(kind, doc_id)
        with _LOCK:
            if not path.exists():
                if expected_revision is not None and expected_revision != 0:
                    raise RevisionConflict(kind, doc_id, expected_revision, 0)
                return False
            if expected_revision is not None:
                loaded = self._load(path)  # CorruptDocument propagates
                current = loaded[1] if loaded is not None else 0
                if expected_revision != current:
                    raise RevisionConflict(
                        kind, doc_id, expected_revision, current
                    )
            try:
                path.unlink()
            except FileNotFoundError:  # pragma: no cover - race guard
                return False
            return True

    # ── list (templates / drafts) ─────────────────────────────────────

    def list(self, kind: str) -> list[tuple[str, dict]]:
        """All documents of a listable kind as ``(doc_id, doc)`` pairs,
        sorted by ``doc_id`` (codepoint order — deterministic, P2).

        Only ``run_template``/``run_draft`` are listable (the singleton is
        :meth:`read`).  Files that are not valid store documents (foreign
        names, non-``.json``, corrupt envelopes) are deterministically
        omitted rather than failing the whole listing.
        """
        subdir = _KIND_SUBDIRS.get(kind)
        if subdir is None:
            raise ValueError(f"kind {kind!r} is not listable")
        d = self._root / subdir
        if not d.is_dir():
            return []
        out: list[tuple[str, dict]] = []
        for p in sorted(d.iterdir(), key=lambda p: p.name):
            if not p.is_file() or p.suffix != ".json":
                continue
            doc_id = p.stem
            if not _DOC_ID_RE.fullmatch(doc_id):
                continue
            try:
                loaded = self._load(p)
            except CorruptDocument:
                continue
            if loaded is not None:
                out.append((doc_id, loaded[0]))
        return out

    # ── internals ─────────────────────────────────────────────────────

    def _ensure_dirs(self, leaf: Path) -> None:
        """Create ``gui_store/`` (+ subdir) and (re-)assert ``0o700`` on the
        store-owned directories only — never on the workspace root."""
        self._root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, _DIR_MODE)
        if leaf != self._root:
            leaf.mkdir(exist_ok=True)
            os.chmod(leaf, _DIR_MODE)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        """Same-directory temp file + fsync + ``os.replace`` (+ best-effort
        directory fsync).  A crash before the replace leaves the previous
        document byte-intact; the orphan temp file is removed on error."""
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(tmp_name, _FILE_MODE)  # mkstemp is 0o600; re-assert
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass
            raise
        try:  # durability of the rename itself (best-effort)
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:  # pragma: no cover - platform-dependent
            pass
