"""Explicit, verifiable run and node context for Skill calls.

The context models are provider-neutral public data.  A per-connection HMAC
turns that data into a narrowly-scoped capability at the MCP transport
boundary; the authority key never appears in a tool argument, result, lock, or
Claude shim configuration.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RUN_CONTEXT_V1 = "ari.run-context/v1"
NODE_CONTEXT_V1 = "ari.node-context/v1"
AUTHORIZED_TOOL_CONTEXT_V1 = "ari.authorized-tool-context/v1"
CALL_CONTEXT_ARGUMENT = "ari_context"
CONTEXT_AUTHORITY_ENV = "ARI_CONTEXT_AUTHORITY_KEY"
SHA256_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class CallContextAuthorizationError(ValueError):
    """Raised when a call context is missing, malformed, or not authorized."""


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def run_scope_digest(run_id: str) -> str:
    """Return the canonical digest for a logical run identity."""

    return _canonical_digest({"run_id": run_id})


def lineage_digest(
    *,
    run_id: str,
    node_id: str,
    parent_node_id: str | None,
    ancestor_node_ids: list[str],
) -> str:
    """Bind an ordered root-to-parent lineage to one run and node."""

    return _canonical_digest(
        {
            "run_id": run_id,
            "node_id": node_id,
            "parent_node_id": parent_node_id,
            "ancestor_node_ids": ancestor_node_ids,
        }
    )


class RunContextV1(BaseModel):
    """Immutable identity for one ARI run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.run-context/v1"] = RUN_CONTEXT_V1
    run_id: str = Field(min_length=1)
    run_scope_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @classmethod
    def create(cls, run_id: str) -> "RunContextV1":
        normalized = str(run_id).strip()
        if not normalized:
            raise ValueError("run_id cannot be empty")
        return cls(run_id=normalized, run_scope_digest=run_scope_digest(normalized))

    @model_validator(mode="after")
    def _digest_matches(self) -> "RunContextV1":
        if self.run_scope_digest != run_scope_digest(self.run_id):
            raise ValueError("run_scope_digest does not match run_id")
        return self


class NodeContextV1(BaseModel):
    """Immutable node identity and its ordered, run-scoped ancestry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.node-context/v1"] = NODE_CONTEXT_V1
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    parent_node_id: str | None = None
    ancestor_node_ids: list[str] = Field(default_factory=list)
    lineage_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        node_id: str,
        parent_node_id: str | None = None,
        ancestor_node_ids: list[str] | tuple[str, ...] = (),
    ) -> "NodeContextV1":
        ancestors = [str(item) for item in ancestor_node_ids]
        return cls(
            run_id=str(run_id),
            node_id=str(node_id),
            parent_node_id=str(parent_node_id) if parent_node_id is not None else None,
            ancestor_node_ids=ancestors,
            lineage_digest=lineage_digest(
                run_id=str(run_id),
                node_id=str(node_id),
                parent_node_id=(
                    str(parent_node_id) if parent_node_id is not None else None
                ),
                ancestor_node_ids=ancestors,
            ),
        )

    @field_validator("ancestor_node_ids")
    @classmethod
    def _valid_ancestors(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("ancestor node IDs cannot be empty")
        if len(values) != len(set(values)):
            raise ValueError("ancestor node IDs must be unique")
        return values

    @model_validator(mode="after")
    def _consistent_lineage(self) -> "NodeContextV1":
        if self.node_id in self.ancestor_node_ids:
            raise ValueError("node cannot be its own ancestor")
        expected_parent = self.ancestor_node_ids[-1] if self.ancestor_node_ids else None
        if self.parent_node_id != expected_parent:
            raise ValueError(
                "parent_node_id must equal the final ancestor, or be null at root"
            )
        expected = lineage_digest(
            run_id=self.run_id,
            node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            ancestor_node_ids=self.ancestor_node_ids,
        )
        if self.lineage_digest != expected:
            raise ValueError("lineage_digest does not match the ordered lineage")
        return self

    @property
    def readable_node_ids(self) -> frozenset[str]:
        """Nodes this context may read: its ancestors and itself."""

        return frozenset([*self.ancestor_node_ids, self.node_id])


class ToolCallContextV1(BaseModel):
    """Explicit context supplied at a tool-call boundary.

    ``run_id`` and ``node_id`` remain as flattened provenance fields for the
    v1 result envelope.  Authorization requires the corresponding structured
    context, whose digests prevent accidental lineage corruption.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = ""
    node_id: str | None = None
    phase: str | None = None
    selection_reason: str = ""
    credential_scope_ids: list[str] = Field(default_factory=list)
    run_context: RunContextV1 | None = None
    node_context: NodeContextV1 | None = None

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        phase: str | None = None,
    ) -> "ToolCallContextV1":
        run = RunContextV1.create(run_id)
        return cls(run_id=run.run_id, phase=phase, run_context=run)

    @classmethod
    def for_node(
        cls,
        *,
        run_id: str,
        node_id: str,
        parent_node_id: str | None = None,
        ancestor_node_ids: list[str] | tuple[str, ...] = (),
        phase: str | None = None,
    ) -> "ToolCallContextV1":
        run = RunContextV1.create(run_id)
        node = NodeContextV1.create(
            run_id=run.run_id,
            node_id=node_id,
            parent_node_id=parent_node_id,
            ancestor_node_ids=ancestor_node_ids,
        )
        return cls(
            run_id=run.run_id,
            node_id=node.node_id,
            phase=phase,
            run_context=run,
            node_context=node,
        )

    @model_validator(mode="after")
    def _structured_context_matches_flattened(self) -> "ToolCallContextV1":
        if self.run_context is not None and self.run_id != self.run_context.run_id:
            raise ValueError("run_id does not match run_context")
        if self.node_context is not None:
            if self.node_id != self.node_context.node_id:
                raise ValueError("node_id does not match node_context")
            if self.run_id != self.node_context.run_id:
                raise ValueError("run_id does not match node_context")
            if self.run_context is None:
                raise ValueError("node_context requires run_context")
        return self

    def satisfies(self, requirement: str) -> bool:
        if requirement == "none":
            return True
        if requirement == "run":
            return self.run_context is not None
        if requirement == "node":
            return self.run_context is not None and self.node_context is not None
        return False


class AuthorizedToolContextV1(BaseModel):
    """Signed context capability injected by an ARI-controlled transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.authorized-tool-context/v1"] = (
        AUTHORIZED_TOOL_CONTEXT_V1
    )
    tool_name: str = Field(min_length=1)
    authority_id: str = Field(pattern=SHA256_DIGEST_PATTERN)
    nonce: str = Field(min_length=16)
    context: ToolCallContextV1
    signature: str = Field(pattern=r"^hmac-sha256:[0-9a-f]{64}$")


def new_context_authority_key() -> str:
    """Create a 256-bit per-connection authority key."""

    return secrets.token_hex(32)


def _key_bytes(key: str) -> bytes:
    try:
        payload = bytes.fromhex(key)
    except ValueError as exc:
        raise CallContextAuthorizationError("context authority key is malformed") from exc
    if len(payload) < 32:
        raise CallContextAuthorizationError("context authority key is too short")
    return payload


def _authority_id(key: str) -> str:
    return f"sha256:{hashlib.sha256(_key_bytes(key)).hexdigest()}"


def _signature_payload(document: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def authorize_tool_context(
    context: ToolCallContextV1,
    *,
    tool_name: str,
    authority_key: str,
) -> dict[str, Any]:
    """Sign one context for exactly one MCP tool name."""

    document: dict[str, Any] = {
        "schema_version": AUTHORIZED_TOOL_CONTEXT_V1,
        "tool_name": tool_name,
        "authority_id": _authority_id(authority_key),
        "nonce": secrets.token_hex(16),
        "context": context.model_dump(mode="json"),
    }
    signature = hmac.new(
        _key_bytes(authority_key),
        _signature_payload(document),
        hashlib.sha256,
    ).hexdigest()
    document["signature"] = f"hmac-sha256:{signature}"
    AuthorizedToolContextV1.model_validate(document)
    return document


def verify_tool_context(
    document: Any,
    *,
    tool_name: str,
    authority_key: str,
    requirement: Literal["run", "node"] = "node",
) -> ToolCallContextV1:
    """Verify a transport capability and return its structured context."""

    try:
        authorized = AuthorizedToolContextV1.model_validate(document)
    except Exception as exc:
        raise CallContextAuthorizationError("authorized call context is malformed") from exc
    if authorized.tool_name != tool_name:
        raise CallContextAuthorizationError("call context is bound to another tool")
    if authorized.authority_id != _authority_id(authority_key):
        raise CallContextAuthorizationError("call context authority does not match")
    supplied = authorized.model_dump(mode="json")
    expected = hmac.new(
        _key_bytes(authority_key),
        _signature_payload(supplied),
        hashlib.sha256,
    ).hexdigest()
    actual = authorized.signature.removeprefix("hmac-sha256:")
    if not hmac.compare_digest(actual, expected):
        raise CallContextAuthorizationError("call context signature is invalid")
    if not authorized.context.satisfies(requirement):
        raise CallContextAuthorizationError(
            f"tool requires explicit {requirement} context"
        )
    return authorized.context


__all__ = [
    "AUTHORIZED_TOOL_CONTEXT_V1",
    "CALL_CONTEXT_ARGUMENT",
    "CONTEXT_AUTHORITY_ENV",
    "NODE_CONTEXT_V1",
    "RUN_CONTEXT_V1",
    "AuthorizedToolContextV1",
    "CallContextAuthorizationError",
    "NodeContextV1",
    "RunContextV1",
    "ToolCallContextV1",
    "authorize_tool_context",
    "lineage_digest",
    "new_context_authority_key",
    "run_scope_digest",
    "verify_tool_context",
]
