"""JSONL trace + node-report store (subtask 010).

:class:`JsonlTraceStore` is the concrete, KEEP-behaviour realisation of
:class:`ari.protocols.stores.TraceStore`. It owns per-node report read/write and
append-only execution traces, resolved through the existing
:class:`ari.paths.PathManager` node-work-dir layout — **no file names or formats
change**.

The ``write_node_report`` / ``read_node_report`` / ``read_sibling_reports``
methods are the read/write seam subtask **011** (BFTS strategy/executor split)
deferred to this subtask: they operate on the same
``{node_work_dir}/node_report.json`` files that
:func:`ari.orchestrator.bfts.BFTS._get_node_report` reads and
:func:`ari.cli.bfts_loop._run_loop` writes today.

- ``write_node_report(node_id, report)`` writes a **pre-built** report dict with
  ``json.dumps(report, indent=2, ensure_ascii=False)`` — byte-identical to
  :func:`ari.orchestrator.node_report.write_node_report`'s write (builder.py
  L621). Build the report via
  :func:`ari.orchestrator.node_report.build_node_report` first, then hand it here.
- ``read_node_report`` / ``read_sibling_reports`` mirror
  ``BFTS._get_node_report`` / ``BFTS._load_sibling_node_reports`` (best-effort,
  ``None`` on any failure).

``append_trace`` / ``read_trace`` provide an append-only per-node JSONL trace
seam (``{node_work_dir}/trace.jsonl``); no production writer emits it yet — it is
the seam executors can adopt without re-touching the store.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class JsonlTraceStore:
    """Per-node report + trace store over the flat node-work-dir layout.

    Resolves node work directories through :class:`ari.paths.PathManager`. The
    active run is pinned by ``ARI_CHECKPOINT_DIR`` unless an explicit
    *path_manager* + *run_id* (or *checkpoint_dir*) is supplied — the same
    resolution :func:`ari.orchestrator.bfts._resolve_pm_and_run_id` performs.
    """

    def __init__(
        self,
        *,
        path_manager: Any = None,
        run_id: str | None = None,
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        self._pm = path_manager
        self._run_id = run_id
        if checkpoint_dir is not None:
            self._bind_from_checkpoint_dir(checkpoint_dir)

    # ── resolution ────────────────────────────────────────────────────

    def _bind_from_checkpoint_dir(self, checkpoint_dir: str | Path) -> None:
        from ari.paths import PathManager

        ckpt = Path(checkpoint_dir)
        self._pm = PathManager.from_checkpoint_dir(ckpt)
        self._run_id = os.path.basename(str(ckpt).rstrip("/"))

    def _resolve_pm_and_run_id(self) -> tuple[Any, str] | None:
        """Return ``(PathManager, run_id)`` or ``None`` if unresolvable.

        Mirrors :func:`ari.orchestrator.bfts._resolve_pm_and_run_id`: uses the
        injected pair when present, else recovers from ``ARI_CHECKPOINT_DIR``.
        """
        if self._pm is not None and self._run_id is not None:
            return self._pm, self._run_id
        from ari.paths import PathManager

        ckpt_path = PathManager.checkpoint_dir_from_env()
        if ckpt_path is None:
            return None
        try:
            pm = PathManager.from_checkpoint_dir(ckpt_path)
            run_id = os.path.basename(str(ckpt_path).rstrip("/"))
            return pm, run_id
        except Exception:
            return None

    def _node_work_dir(self, node_id: str) -> Path | None:
        resolved = self._resolve_pm_and_run_id()
        if resolved is None:
            return None
        pm, run_id = resolved
        return pm.node_work_dir(run_id, node_id)

    @staticmethod
    def _node_id_of(item: Any) -> str:
        """Accept either a node id string or an object exposing ``.id``."""
        return item if isinstance(item, str) else str(getattr(item, "id", item))

    # ── node reports ──────────────────────────────────────────────────

    def write_node_report(self, node_id: str, report: dict) -> Path:
        """Write a **pre-built** report dict to ``{node_work_dir}/node_report.json``.

        Byte-identical to :func:`ari.orchestrator.node_report.write_node_report`'s
        write step (``indent=2, ensure_ascii=False``). Build the report via
        :func:`ari.orchestrator.node_report.build_node_report` and pass it here.
        """
        work_dir = self._node_work_dir(node_id)
        if work_dir is None:
            raise RuntimeError(
                "JsonlTraceStore: cannot resolve node work dir "
                "(no ARI_CHECKPOINT_DIR and no explicit path_manager/run_id)"
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        out_path = work_dir / "node_report.json"
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        return out_path

    def read_node_report(self, node_id: str) -> dict | None:
        """Best-effort read of ``{node_work_dir}/node_report.json``.

        Mirrors ``BFTS._get_node_report``: returns the parsed dict or ``None``
        when the file is absent or fails to parse.
        """
        work_dir = self._node_work_dir(node_id)
        if work_dir is None:
            return None
        path = work_dir / "node_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def read_sibling_reports(self, node_ids: Any) -> dict[str, dict]:
        """Best-effort load of ``node_report.json`` for each of *node_ids*.

        Accepts an iterable of id strings or node objects (``.id``). Mirrors
        ``BFTS._load_sibling_node_reports``: silently skips anything unreadable.
        """
        out: dict[str, dict] = {}
        for item in node_ids:
            nid = self._node_id_of(item)
            try:
                rep = self.read_node_report(nid)
            except Exception:
                continue
            if rep:
                out[nid] = rep
        return out

    # ── execution traces ──────────────────────────────────────────────

    def append_trace(self, node_id: str, entry: str | dict) -> None:
        """Append *entry* as one JSON line to ``{node_work_dir}/trace.jsonl``.

        Strings and dicts both round-trip through :func:`read_trace`.
        """
        work_dir = self._node_work_dir(node_id)
        if work_dir is None:
            raise RuntimeError(
                "JsonlTraceStore: cannot resolve node work dir for trace append"
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with (work_dir / "trace.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_trace(self, node_id: str) -> list:
        """Read ``{node_work_dir}/trace.jsonl`` back into a list of entries.

        Returns ``[]`` when the trace file is absent. Malformed lines are
        skipped (best-effort, like the node-report readers).
        """
        work_dir = self._node_work_dir(node_id)
        if work_dir is None:
            return []
        path = work_dir / "trace.jsonl"
        if not path.is_file():
            return []
        out: list = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
