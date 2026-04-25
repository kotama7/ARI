"""Environment → config resolution for ari-skill-memory.

The configuration is read entirely from environment variables; callers
never pass in-memory dicts.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryConfig:
    checkpoint_dir: Path
    ckpt_hash: str
    backend_name: str  # "letta" | "in_memory"
    letta_base_url: str
    letta_api_key: str
    letta_embedding_config: str
    letta_timeout_s: float
    letta_overfetch: int
    letta_disable_self_edit: bool
    access_log_enabled: bool
    access_log_preview_chars: int
    access_log_max_mb: int
    react_search_limit: int
    react_max_entry_chars: int


def _ckpt_hash(checkpoint_dir: Path) -> str:
    return hashlib.sha1(str(checkpoint_dir.resolve()).encode("utf-8")).hexdigest()[:12]


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def load_config(checkpoint_dir: "str | Path | None" = None) -> MemoryConfig:
    """Resolve configuration from env.

    Per §9: ``ARI_CHECKPOINT_DIR`` is required unless ``checkpoint_dir`` is
    supplied explicitly (library callers may inject it).
    """
    ckpt = checkpoint_dir
    if ckpt is None:
        ckpt_env = os.environ.get("ARI_CHECKPOINT_DIR")
        if not ckpt_env:
            raise RuntimeError(
                "ari-skill-memory requires ARI_CHECKPOINT_DIR — "
                "no global fallback exists."
            )
        ckpt = ckpt_env
    ckpt_path = Path(ckpt).expanduser()
    h = _ckpt_hash(ckpt_path)

    backend_name = os.environ.get("ARI_MEMORY_BACKEND", "letta").strip().lower()
    if backend_name not in ("letta", "in_memory"):
        raise RuntimeError(
            f"ARI_MEMORY_BACKEND={backend_name!r} is not supported — "
            "only 'letta' (production) and 'in_memory' (tests) are accepted."
        )

    return MemoryConfig(
        checkpoint_dir=ckpt_path,
        ckpt_hash=h,
        backend_name=backend_name,
        letta_base_url=os.environ.get("LETTA_BASE_URL", "http://localhost:8283"),
        letta_api_key=os.environ.get("LETTA_API_KEY", ""),
        letta_embedding_config=os.environ.get("LETTA_EMBEDDING_CONFIG", "letta-default"),
        letta_timeout_s=_float_env("ARI_MEMORY_LETTA_TIMEOUT_S", 10.0),
        letta_overfetch=_int_env("ARI_MEMORY_LETTA_OVERFETCH", 200),
        letta_disable_self_edit=_bool_env("ARI_MEMORY_LETTA_DISABLE_SELF_EDIT", True),
        access_log_enabled=os.environ.get("ARI_MEMORY_ACCESS_LOG", "on").lower() != "off",
        access_log_preview_chars=_int_env("ARI_MEMORY_ACCESS_PREVIEW_CHARS", 200),
        access_log_max_mb=_int_env("ARI_MEMORY_ACCESS_LOG_MAX_MB", 100),
        react_search_limit=_int_env("ARI_REACT_MEMORY_SEARCH_LIMIT", 10),
        react_max_entry_chars=_int_env("ARI_REACT_MEMORY_MAX_ENTRY_CHARS", 0),
    )
