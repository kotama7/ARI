"""Content-addressed artifacts and credential-free invocation cassettes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from models import (
    CatalogLockV1,
    InvocationCassetteV1,
    canonical_json,
    cassette_key,
    credential_field_paths,
    sha256_digest,
)
from providers import ProviderResponseV1


class RegistryStorageError(RuntimeError):
    pass


_CREDENTIAL_TEXT_RE = re.compile(
    r"(?:-----BEGIN [^-\n]*PRIVATE KEY-----|"
    r"(?:^|[\s{'\",])(?:api[_-]?key|apikey|secret|client[_-]?secret|"
    r"password|passwd|credential|access[_-]?token|refresh[_-]?token|token|"
    r"authorization|bearer|private[_-]?key)[\"']?\s*[:=]\s*\S{4,})",
    re.IGNORECASE | re.MULTILINE,
)


def _safe_relative(name: str) -> Path:
    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise RegistryStorageError(f"unsafe registry artifact name: {name!r}")
    return path


def _atomic_write(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


class RegistryArtifactStore:
    """Safe root implementing the public ArtifactStore protocol by duck typing."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, name: str) -> Path:
        relative = _safe_relative(name)
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise RegistryStorageError(f"artifact escapes store: {name}") from exc
        return target

    def exists(self, name: str) -> bool:
        target = self.get(name)
        return target.is_file() and not target.is_symlink()

    def put(self, name: str, data_or_path: str | bytes | Path) -> Path:
        target = self.get(name)
        if target.is_symlink():
            raise RegistryStorageError(f"refusing symbolic artifact: {name}")
        if isinstance(data_or_path, Path):
            payload = data_or_path.read_bytes()
        elif isinstance(data_or_path, bytes):
            payload = data_or_path
        else:
            payload = data_or_path.encode("utf-8")
        if target.is_file():
            if target.read_bytes() != payload:
                raise RegistryStorageError(f"refusing to overwrite artifact: {name}")
            return target
        _atomic_write(target, payload)
        return target

    def list(self, kind: str | None = None) -> list[Path]:
        files = sorted(path for path in self.root.rglob("*") if path.is_file())
        if kind is None:
            return files
        if kind.startswith("."):
            return [path for path in files if path.suffix == kind]
        return [path for path in files if path.match(kind)]


class CassetteStore:
    def __init__(
        self,
        root: str | Path,
        *,
        artifact_store: RegistryArtifactStore | None = None,
        forbidden_values: Iterable[str] = (),
        inline_raw_limit: int = 4_000,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_store = artifact_store
        self.forbidden_values = tuple(
            value for value in forbidden_values if isinstance(value, str) and value
        )
        self.inline_raw_limit = inline_raw_limit

    def _path(self, key: str) -> Path:
        digest = key.removeprefix("sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RegistryStorageError("cassette key is malformed")
        return self.root / digest[:2] / f"{digest}.json"

    def _raw_record(self, response: ProviderResponseV1) -> dict[str, Any]:
        text = response.text
        if not text:
            raise RegistryStorageError("empty provider responses are not recordable")
        folded = text.casefold()
        if response.is_error and any(
            marker in folded
            for marker in (
                "unauthorized",
                "unauthenticated",
                "authentication failed",
                "invalid api key",
                "forbidden",
            )
        ):
            raise RegistryStorageError(
                "authentication failures are not valid cassettes"
            )
        for secret in self.forbidden_values:
            if secret in text or (
                response.structured is not None
                and secret in canonical_json(response.structured)
            ):
                raise RegistryStorageError(
                    "provider response contains credential material"
                )
        structured_paths = credential_field_paths(
            response.structured, "provider_response"
        )
        if structured_paths:
            raise RegistryStorageError(
                f"provider response contains credential fields: {structured_paths}"
            )
        try:
            parsed_text = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed_text = None
        parsed_paths = credential_field_paths(parsed_text, "provider_response_text")
        if parsed_paths or _CREDENTIAL_TEXT_RE.search(text):
            raise RegistryStorageError(
                "provider response contains credential material and is not recordable"
            )
        payload = text.encode("utf-8")
        record: dict[str, Any] = {
            "is_error": response.is_error,
            "structured": response.structured,
            "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "size": len(payload),
        }
        if len(payload) <= self.inline_raw_limit:
            record["text"] = text
            return record
        if self.artifact_store is None:
            raise RegistryStorageError(
                "large record responses require an artifact store"
            )
        digest = record["digest"].removeprefix("sha256:")
        logical_name = f"raw-cassettes/sha256/{digest[:2]}/{digest}.txt"
        self.artifact_store.put(logical_name, payload)
        record["artifact"] = logical_name
        return record

    def record(
        self,
        *,
        tool_ref: str,
        arguments: dict[str, Any],
        catalog_digest: str,
        policy_digest: str,
        selection_reason: str,
        rejected_candidates: list[dict[str, Any]],
        raw_response: ProviderResponseV1,
        result_envelope: dict[str, Any],
    ) -> InvocationCassetteV1:
        argument_paths = credential_field_paths(arguments, "arguments")
        if argument_paths:
            raise RegistryStorageError(
                f"record arguments contain credential fields: {argument_paths}"
            )
        key = cassette_key(tool_ref, arguments)
        cassette = InvocationCassetteV1(
            cassette_key=key,
            tool_ref=tool_ref,
            arguments=arguments,
            arguments_digest=sha256_digest(arguments),
            catalog_digest=catalog_digest,
            policy_digest=policy_digest,
            selection_reason=selection_reason,
            rejected_candidates=rejected_candidates,
            raw_response=self._raw_record(raw_response),
            result_envelope=result_envelope,
        )
        path = self._path(key)
        payload = (
            json.dumps(
                cassette.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if path.is_symlink():
            raise RegistryStorageError("symbolic cassette paths are refused")
        if path.is_file():
            try:
                existing = InvocationCassetteV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError, ValueError) as exc:
                raise RegistryStorageError(
                    f"existing cassette is corrupt: {exc}"
                ) from exc
            if existing.model_dump(mode="json") != cassette.model_dump(mode="json"):
                raise RegistryStorageError(
                    "cassette key already exists with different provenance"
                )
            return existing
        _atomic_write(path, payload)
        return cassette

    def load(self, tool_ref: str, arguments: dict[str, Any]) -> InvocationCassetteV1:
        key = cassette_key(tool_ref, arguments)
        path = self._path(key)
        if path.is_symlink():
            raise RegistryStorageError("symbolic cassette paths are refused")
        try:
            if path.stat().st_size > 10_000_000:
                raise RegistryStorageError("cassette exceeds 10 MB")
            cassette = InvocationCassetteV1.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except RegistryStorageError:
            raise
        except (OSError, ValidationError, ValueError) as exc:
            raise RegistryStorageError(
                f"cassette unavailable or invalid: {exc}"
            ) from exc
        return cassette

    def list_records(self) -> list[Path]:
        return sorted(path for path in self.root.glob("*/*.json") if path.is_file())


def persist_catalog_for_ear(
    artifact_store: RegistryArtifactStore,
    lock: CatalogLockV1,
) -> None:
    """Persist the exact lock and value-free run manifest under ``ear/catalog``."""

    lock_payload = (
        json.dumps(
            lock.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    artifact_store.put("CATALOG.lock", lock_payload)
    artifact_store.put(
        "catalog-provenance.json",
        json.dumps(
            {
                "schema_version": "ari.catalog-provenance/v1",
                "catalog_digest": lock.catalog_digest,
                "policy_digest": lock.policy_digest,
                "tool_refs": sorted(tool.tool_ref for tool in lock.tools),
                "quarantined": [
                    item.model_dump(mode="json") for item in lock.quarantined
                ],
                "overlaps": [item.model_dump(mode="json") for item in lock.overlaps],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


__all__ = [
    "CassetteStore",
    "RegistryArtifactStore",
    "RegistryStorageError",
    "persist_catalog_for_ear",
]
