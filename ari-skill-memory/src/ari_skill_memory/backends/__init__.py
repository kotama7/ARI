"""Memory backend factory."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from ari_skill_memory.backends.base import MemoryBackend
from ari_skill_memory.config import load_config

_BACKENDS: dict[str, MemoryBackend] = {}
_LOCK = threading.Lock()


def get_backend(
    checkpoint_dir: "str | Path | None" = None,
    *,
    reset: bool = False,
) -> MemoryBackend:
    """Return the per-checkpoint ``MemoryBackend`` instance.

    Instances are cached by resolved checkpoint path so repeated calls
    from the same process share the same backend (and, for Letta, the
    same agent handle).
    """
    cfg = load_config(checkpoint_dir)
    cache_key = f"{cfg.backend_name}:{cfg.ckpt_hash}"

    with _LOCK:
        if reset and cache_key in _BACKENDS:
            try:
                _BACKENDS[cache_key].close()
            except Exception:
                pass
            _BACKENDS.pop(cache_key, None)
        if cache_key in _BACKENDS:
            return _BACKENDS[cache_key]

        if cfg.backend_name == "in_memory":
            from ari_skill_memory.backends.in_memory import InMemoryBackend
            backend: MemoryBackend = InMemoryBackend(cfg)
        elif cfg.backend_name == "letta":
            from ari_skill_memory.backends.letta_backend import LettaBackend
            backend = LettaBackend(cfg)
        else:
            raise RuntimeError(f"Unknown backend: {cfg.backend_name!r}")

        _BACKENDS[cache_key] = backend
        return backend


def clear_backend_cache() -> None:
    """Test-only: drop the cached instances so fresh env vars are picked up."""
    with _LOCK:
        for b in list(_BACKENDS.values()):
            try:
                b.close()
            except Exception:
                pass
        _BACKENDS.clear()


__all__ = ["MemoryBackend", "get_backend", "clear_backend_cache"]
