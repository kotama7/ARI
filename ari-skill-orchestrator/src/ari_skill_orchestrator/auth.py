"""Authentication adapters and run-owner authorization."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from pathlib import Path

from .contracts import PrincipalV1


class AuthenticationError(PermissionError):
    pass


class AuthorizationError(PermissionError):
    pass


def _read_token_file(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise AuthenticationError("orchestrator token digest file is invalid") from exc
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise AuthenticationError("orchestrator token digest file is not regular")
        if status.st_mode & 0o077:
            raise AuthenticationError(
                "orchestrator token digest file must have mode 0600"
            )
        if status.st_size > 1024 * 1024:
            raise AuthenticationError("orchestrator token digest file is too large")
        chunks: list[bytes] = []
        remaining = 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except AuthenticationError:
        raise
    except OSError as exc:
        raise AuthenticationError("orchestrator token digest file is invalid") from exc
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if len(payload) > 1024 * 1024:
        raise AuthenticationError("orchestrator token digest file is too large")
    return payload


def _decode_token_document(payload: bytes) -> dict[str, object]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("orchestrator token digest file is invalid") from exc
    if not isinstance(document, dict):
        raise AuthenticationError("orchestrator token digest file must be an object")
    if document.get("schema_version") != "ari.orchestrator-token-digests/v1":
        raise AuthenticationError("unsupported orchestrator token digest schema")
    return document


def _parse_token_record(raw: object) -> tuple[str, str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise AuthenticationError("orchestrator token digest record is invalid")
    digest = str(raw.get("token_sha256") or "")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise AuthenticationError("invalid bearer token digest")
    raw_roles = raw.get("roles") or []
    if not isinstance(raw_roles, list) or any(
        not isinstance(item, str) for item in raw_roles
    ):
        raise AuthenticationError("bearer token roles must be a string list")
    try:
        principal = PrincipalV1(
            principal_id=str(raw.get("principal_id") or ""),
            roles=tuple(raw_roles),
            authentication="bearer",
        )
    except ValueError as exc:
        raise AuthenticationError("bearer token principal is invalid") from exc
    return digest, principal.principal_id, principal.roles


def local_principal() -> PrincipalV1:
    principal_id = os.environ.get("ARI_ORCHESTRATOR_PRINCIPAL_ID", "local-user")
    roles = tuple(
        item.strip()
        for item in os.environ.get("ARI_ORCHESTRATOR_PRINCIPAL_ROLES", "").split(",")
        if item.strip()
    )
    return PrincipalV1(
        principal_id=principal_id,
        roles=roles,
        authentication="local-stdio",
    )


def require_owner(principal: PrincipalV1, owner_id: str) -> None:
    if principal.principal_id != owner_id and not principal.is_admin:
        raise AuthorizationError("principal is not authorized for this run")


class HashedTokenVerifier:
    """MCP TokenVerifier backed by a value-free, mode-0600 token digest file.

    The file contains SHA-256 token digests, never bearer token plaintext.  It is
    intentionally a small local adapter; deployments may replace it with any MCP
    SDK ``TokenVerifier`` implementing OAuth resource-server semantics.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records = self._load()

    def _load(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        document = _decode_token_document(_read_token_file(self.path))
        records: dict[str, tuple[str, tuple[str, ...]]] = {}
        raw_tokens = document.get("tokens")
        if not isinstance(raw_tokens, list):
            raise AuthenticationError(
                "orchestrator token digest records must be a list"
            )
        for raw in raw_tokens:
            digest, principal_id, roles = _parse_token_record(raw)
            if digest in records:
                raise AuthenticationError("duplicate bearer token digest")
            records[digest] = (principal_id, roles)
        if not records:
            raise AuthenticationError("token digest file contains no tokens")
        return records

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matched: tuple[str, tuple[str, ...]] | None = None
        for expected, record in self._records.items():
            if hmac.compare_digest(digest, expected):
                matched = record
        if matched is None:
            return None
        principal_id, roles = matched
        return AccessToken(
            token=token,
            client_id=principal_id,
            scopes=[f"role:{role}" for role in roles],
        )


def request_principal() -> PrincipalV1:
    """Resolve HTTP bearer identity when present, otherwise local stdio identity."""

    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access = get_access_token()
    except (ImportError, LookupError):
        access = None
    if access is None:
        return local_principal()
    roles = tuple(
        scope.removeprefix("role:")
        for scope in access.scopes
        if scope.startswith("role:")
    )
    return PrincipalV1(
        principal_id=access.client_id,
        roles=roles,
        authentication="bearer",
    )


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "HashedTokenVerifier",
    "local_principal",
    "request_principal",
    "require_owner",
]
