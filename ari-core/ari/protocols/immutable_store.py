"""Fixed-path, write-once JSON storage for immutable scientific contracts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def rendered_json(value: BaseModel | dict[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"


def write_once_json(path: str | Path, value: BaseModel | dict[str, Any]) -> Path:
    """Publish exact bytes once; an existing different value is an error."""

    target = Path(path)
    payload = rendered_json(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError(f"immutable artifact mismatch: {target.name}")
        return target
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    descriptor_owned = True
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            descriptor_owned = False
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != payload:
                raise ValueError(f"immutable artifact race mismatch: {target.name}")
        return target
    finally:
        if descriptor_owned:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_json_model(path: str | Path, model: type[T]) -> T:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"symbolic link refused: {source.name}")
    document = json.loads(source.read_text(encoding="utf-8"))
    return model.model_validate(document)


def canonical_document_digest(value: BaseModel | dict[str, Any]) -> str:
    """Expose the canonical digest of a persisted document for audit tooling."""

    from ari.protocols.integrity import canonical_digest

    return canonical_digest(value)


__all__ = [
    "canonical_document_digest",
    "load_json_model",
    "rendered_json",
    "write_once_json",
]
