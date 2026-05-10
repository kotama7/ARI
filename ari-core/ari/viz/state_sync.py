"""Node-tree loading + WebSocket broadcast + filesystem watcher.

Phase 3B PR-3B-2 (viz/REFACTORING.md §2 Step 2): extracted from
``ari/viz/api_state.py``.  ``api_state.py`` keeps a re-export facade
so downstream callers (and the route table inside ``server.py``) see
the same names regardless of where each function landed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


log = logging.getLogger(__name__)



def _load_nodes_tree() -> dict | None:
    """Load the active checkpoint's node tree (Phase 2 §6-1 delegation).

    Search order, retry-on-mid-write semantics, and the empty-dict
    rejection rule live in ``ari.checkpoint.load_nodes_tree``; this
    wrapper only feeds it the active checkpoint dir from ``_st``.
    """
    if _st._checkpoint_dir is None:
        return None
    from ari.checkpoint import load_nodes_tree as _load
    return _load(_st._checkpoint_dir)




def _broadcast(data: dict) -> None:
    if not _st._clients or _st._loop is None:
        return
    msg = json.dumps({"type": "update", "data": data,
                       "timestamp": datetime.now(timezone.utc).isoformat()})
    # Phase 3B PR-3B-2: look up ``_do_broadcast`` via the api_state
    # facade so test monkeypatches against ``api_state._do_broadcast``
    # are honoured at call time.
    from . import api_state as _as
    asyncio.run_coroutine_threadsafe(_as._do_broadcast(msg), _st._loop)




async def _do_broadcast(msg: str) -> None:
    dead = set()
    for ws in list(_st._clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _st._clients.difference_update(dead)




def _watcher_thread() -> None:
    _last_mtimes: dict[str, float] = {}
    _last_ckpt: "Path | None" = None
    while True:
        time.sleep(1)
        if _st._checkpoint_dir is None:
            continue
        # Reset mtime cache when checkpoint directory changes
        if _st._checkpoint_dir != _last_ckpt:
            _last_mtimes.clear()
            _last_ckpt = _st._checkpoint_dir
        # Check both files for changes (tree.json preferred by _load_nodes_tree)
        changed = False
        for fname in ("tree.json", "nodes_tree.json"):
            p = _st._checkpoint_dir / fname
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
                if mtime != _last_mtimes.get(fname, 0):
                    _last_mtimes[fname] = mtime
                    changed = True
            except Exception:
                log.debug("watcher mtime check error", exc_info=True)
                pass
        # Also watch node_*/tree.json for experiments where tree lives in subdirs
        if not changed:
            try:
                for _nf in _st._checkpoint_dir.glob("node_*/tree.json"):
                    try:
                        _nf_key = str(_nf)
                        _nf_mtime = _nf.stat().st_mtime
                        if _nf_mtime != _last_mtimes.get(_nf_key, 0):
                            _last_mtimes[_nf_key] = _nf_mtime
                            changed = True
                    except OSError:
                        continue
            except Exception:
                pass
        if not changed:
            continue
        # Phase 3B PR-3B-2: defer to the api_state facade so tests that
        # monkeypatch ``api_state._load_nodes_tree`` / ``api_state._broadcast``
        # are honoured (the watcher polls in a thread that the test
        # may stub out).
        from . import api_state as _as
        data = _as._load_nodes_tree()
        if data:
            _as._broadcast(data)

