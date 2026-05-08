"""Recursion lineage helpers for ARI sub-experiments.

Each child checkpoint records ``parent_run_id`` in its ``meta.json``. This
module walks that chain to expose ancestor artifacts to descendants in a
controlled, read-only fashion.

Inheritance contract (matches the design discussion):

  - venue.md (rubric)  : always inherited via ``ARI_RUBRIC`` env var
  - memory             : ancestor-scoped read (existing in ari-skill-memory)
  - idea.json          : ancestor-scoped READ-ONLY catalog (this module)
  - plan.md            : NOT inherited by default — child writes its own

Crucially, the *directive* path in pipeline.py reads only the current
checkpoint's idea.json (auto-consumes ideas[0] as the plan). The lineage
walk implemented here is the *catalog* path — invoked explicitly by VirSci
to inform new idea generation, or by the sub-experiment launch API when a
caller asks to materialise a specific parent idea (``--from-idea N``).

Keeping the two paths separate is what prevents children from being
silently locked into a parent's research direction.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


def _logs_root_candidates() -> list[Path]:
    """Possible roots under which checkpoint dirs live.

    Mirrors the discovery logic in ``viz/api_orchestrator._logs_root`` but
    keeps this module independent of the viz package so non-viz callers
    (CLI, MCP skills) can use it.

    When ``ARI_ORCHESTRATOR_LOGS`` is set it takes strict precedence so
    tests can scope lineage searches to a tmp directory without picking
    up unrelated paths leaked from the surrounding environment.
    """
    override = os.environ.get("ARI_ORCHESTRATOR_LOGS")
    if override:
        return [Path(override).expanduser()]
    cands: list[Path] = []
    ws = os.environ.get("ARI_WORKSPACE")
    if ws:
        cands.append(Path(ws).expanduser() / "checkpoints")
    # ARI_CHECKPOINT_DIR points at a *single* run; its parent is the logs
    # root. Skip when the parent is /tmp or a similar non-checkpoint
    # directory to avoid scanning unrelated artifacts (ssh sockets, etc.).
    ck = os.environ.get("ARI_CHECKPOINT_DIR")
    if ck:
        parent = Path(ck).expanduser().parent
        # Only accept if the parent dir name is "checkpoints" or otherwise
        # plausibly a checkpoint root. Permission-locked roots like /tmp
        # would otherwise slow walks and trigger PermissionError.
        if parent.name == "checkpoints":
            cands.append(parent)
    # Fall back to the conventional layout.
    cands.append(Path.cwd() / "workspace" / "checkpoints")
    return cands


def _resolve_ckpt_by_run_id(run_id: str) -> Path | None:
    """Locate the checkpoint dir for a given run_id by scanning roots.

    Defensive against permission errors and unreadable directories — they
    are skipped silently so a stray non-checkpoint path on the candidate
    list (e.g. an unreadable socket dir) does not break resolution.
    """
    if not run_id:
        return None
    for root in _logs_root_candidates():
        cand = root / run_id
        try:
            if cand.is_dir() and (cand / "meta.json").exists():
                return cand
        except (OSError, PermissionError):
            continue
    # Last resort: scan every root for a meta.json with the matching run_id.
    for root in _logs_root_candidates():
        try:
            if not root.is_dir():
                continue
            entries = list(root.iterdir())
        except (OSError, PermissionError):
            continue
        for ck in entries:
            try:
                if not ck.is_dir():
                    continue
                meta_f = ck / "meta.json"
                if not meta_f.exists():
                    continue
                meta = json.loads(meta_f.read_text())
            except (OSError, PermissionError, json.JSONDecodeError):
                continue
            except Exception:
                continue
            if isinstance(meta, dict) and meta.get("run_id") == run_id:
                return ck
    return None


def _read_parent_run_id(ckpt_dir: Path) -> str | None:
    meta_f = ckpt_dir / "meta.json"
    if not meta_f.exists():
        return None
    try:
        meta = json.loads(meta_f.read_text())
    except Exception as e:
        log.warning("lineage: malformed meta.json at %s: %s", meta_f, e)
        return None
    if not isinstance(meta, dict):
        return None
    pid = meta.get("parent_run_id")
    return str(pid) if pid else None


def walk_ancestor_ckpts(
    ckpt_dir: str | Path, *, include_self: bool = False, max_depth: int = 16
) -> Iterator[Path]:
    """Yield ckpt directories along the lineage chain.

    Order: self (if ``include_self``) → parent → grandparent → …

    Cycles (which should not occur but defensively guarded) and chains
    deeper than ``max_depth`` terminate the walk silently. Missing parent
    run_ids also terminate cleanly.
    """
    cur = Path(ckpt_dir).expanduser().resolve()
    seen: set[str] = set()
    if include_self:
        yield cur
    seen.add(str(cur))
    for _ in range(max_depth):
        pid = _read_parent_run_id(cur)
        if not pid:
            return
        nxt = _resolve_ckpt_by_run_id(pid)
        if nxt is None:
            return
        nxt_resolved = nxt.resolve()
        if str(nxt_resolved) in seen:
            return
        seen.add(str(nxt_resolved))
        yield nxt_resolved
        cur = nxt_resolved


def get_idea_pool_for_ckpt(
    ckpt_dir: str | Path,
    *,
    walk_ancestors: bool = True,
    exclude_self: bool = False,
) -> list[dict]:
    """Aggregate idea.json catalogs along the lineage.

    Returns a list of entries::

        [
          {"run_id": str, "depth": int, "ckpt_dir": str, "ideas": [...]},
          ...
        ]

    ``depth`` is 0 for self and increases for each ancestor hop. The list
    is empty when no idea.json files are found along the chain.

    This is the *catalog* read path — callers (VirSci ancestor-context
    builder, sub-experiment launcher) explicitly opt into it. The pipeline's
    *directive* path remains self-only.
    """
    ckpt = Path(ckpt_dir).expanduser().resolve()
    pool: list[dict] = []

    def _try_load(d: Path, depth: int) -> None:
        ip = d / "idea.json"
        if not ip.exists():
            return
        try:
            data = json.loads(ip.read_text())
        except Exception as e:
            log.warning("lineage: malformed idea.json at %s: %s", ip, e)
            return
        ideas = data.get("ideas") if isinstance(data, dict) else None
        if not ideas:
            return
        # Resolve run_id from meta.json when available so callers can
        # reference it without parsing the path.
        run_id = ckpt.name
        meta_f = d / "meta.json"
        if meta_f.exists():
            try:
                meta = json.loads(meta_f.read_text())
                if isinstance(meta, dict) and meta.get("run_id"):
                    run_id = str(meta["run_id"])
            except Exception:
                pass
        else:
            run_id = d.name
        pool.append(
            {
                "run_id": run_id,
                "depth": depth,
                "ckpt_dir": str(d),
                "ideas": ideas,
            }
        )

    if not exclude_self:
        _try_load(ckpt, 0)
    if walk_ancestors:
        for depth, anc in enumerate(walk_ancestor_ckpts(ckpt), start=1):
            _try_load(anc, depth)
    return pool


def format_ancestor_pool_for_virsci(pool: list[dict], *, max_per_run: int = 3) -> str:
    """Render the catalog as a context block for VirSci agent prompts.

    Returns "" when there is nothing useful to inject — callers can drop the
    block silently in that case.
    """
    if not pool:
        return ""
    # Skip self entries — VirSci is generating self's idea.json right now.
    ancestors = [e for e in pool if e.get("depth", 0) > 0]
    if not ancestors:
        return ""
    lines = ["Prior research thread (ancestor runs in this lineage):"]
    for entry in ancestors:
        rid = str(entry.get("run_id", ""))[-12:]
        depth = entry.get("depth", "?")
        for idea in (entry.get("ideas") or [])[:max_per_run]:
            title = (idea.get("title") or "").strip().replace("\n", " ")[:140]
            score = idea.get("overall_score", "")
            lines.append(
                f"- run {rid} (depth {depth}, score {score}): {title}"
            )
    lines.append(
        "Treat these as context — refine, extend, or explicitly pivot from "
        "them, but make your relationship to them explicit in the description."
    )
    return "\n".join(lines) + "\n\n"
