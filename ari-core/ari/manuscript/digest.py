"""Canonical digest and safe-artifact helpers for Manuscript Complete."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel


SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
ZERO_DIGEST = "sha256:" + "0" * 64


def canonical_json_bytes(value: Any) -> bytes:
    """Return the single normative JSON encoding used by manuscript contracts."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_digest(path: Path, *, max_bytes: int = 256 * 1024 * 1024) -> tuple[str, int]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"artifact exceeds manuscript read limit: {path} ({size} bytes)")
    payload = path.read_bytes()
    return bytes_digest(payload), len(payload)


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("manuscript artifact path must be safe and relative")
    return value


def normalize_digest(value: Any) -> str | None:
    """Normalize a recorded SHA-256 value without inventing a missing digest."""

    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw):
        raw = "sha256:" + raw
    if len(raw) == 71 and raw.startswith("sha256:") and all(
        c in "0123456789abcdef" for c in raw[7:]
    ):
        return raw
    return None


__all__ = [
    "SHA256_PATTERN",
    "ZERO_DIGEST",
    "bytes_digest",
    "canonical_digest",
    "canonical_json_bytes",
    "file_digest",
    "normalize_digest",
    "safe_relative_path",
]
