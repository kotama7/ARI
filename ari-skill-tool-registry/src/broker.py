"""Immutable runtime broker exposed through the five-tool MCP surface."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaError

from ari.public.result import (
    ResultArtifactV1,
    ResultEnvelopeV1,
    ResultEnvelopeNormalizer,
    ToolCallContextV1,
)

from catalog import build_catalog_index
from models import (
    AdmissionDecisionV1,
    AdmissionLevel,
    CanonicalToolDescriptorV1,
    CatalogIndexV1,
    CatalogLockV1,
    InvocationMode,
    RegistryHandleV1,
    admission_rank,
    canonical_json,
    credential_field_paths,
    meets_admission,
    sanitize_text,
    sha256_digest,
)
from openroad_adapter import (
    OPENROAD_ADAPTER_ID,
    OPENROAD_ADAPTER_VERSION,
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadProviderPinV1,
    openroad_adapter_digest,
)
from providers import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderResponseV1,
    PythonStdioLauncherV1,
    STDIO_ADAPTER_ID,
    STDIO_ADAPTER_VERSION,
    StdioMCPAdapter,
    stdio_adapter_digest,
)
from storage import (
    CassetteStore,
    RegistryArtifactStore,
    RegistryStorageError,
    persist_catalog_for_ear,
)
from tooluniverse_adapter import (
    TOOLUNIVERSE_ADAPTER_ID,
    TOOLUNIVERSE_ADAPTER_VERSION,
    ToolUniverseCompactAdapter,
    tooluniverse_adapter_digest,
)


MAX_DISCOVER_RESULTS = 25
MAX_DESCRIBE_CHARS = 4_000
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._:+/-]*")
_ALLOWED_CONSTRAINTS = frozenset(
    {
        "capability_ref",
        "cursor",
        "determinism",
        "min_admission",
        "permission",
        "provider_id",
        "side_effects",
        "source_id",
    }
)


class BrokerError(RuntimeError):
    pass


class BrokerAdmissionError(BrokerError):
    pass


class BrokerProtocolError(BrokerError):
    pass


@dataclass
class _PendingOperation:
    arguments: dict[str, Any]
    selection_reason: str
    rejected_candidates: list[dict[str, Any]]


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {"value": value}


class CatalogBroker:
    """Read one catalog snapshot at construction and never refresh it."""

    def __init__(
        self,
        lock: CatalogLockV1,
        *,
        index: CatalogIndexV1 | None = None,
        adapters: dict[str, ProviderAdapter] | None = None,
        artifact_store: RegistryArtifactStore | None = None,
        cassette_store: CassetteStore | None = None,
        inline_result_limit: int = 4_000,
    ) -> None:
        self.lock = lock
        expected_index = build_catalog_index(lock)
        self.index = index or expected_index
        if self.index.model_dump(mode="json") != expected_index.model_dump(mode="json"):
            raise BrokerProtocolError(
                "catalog index is not the exact derivation of the active lock"
            )
        self._descriptors = {tool.tool_ref: tool for tool in lock.tools}
        self._admissions = {item.tool_ref: item for item in lock.admissions}
        self._sources = {source.source_id: source for source in lock.sources}
        self._adapters = dict(adapters or {})
        unknown_adapters = sorted(set(self._adapters) - set(self._sources))
        if unknown_adapters:
            raise BrokerProtocolError(
                f"adapter overrides refer to unknown sources: {unknown_adapters}"
            )
        self.artifact_store = artifact_store
        self.cassette_store = cassette_store
        self.normalizer = ResultEnvelopeNormalizer(
            artifact_store=artifact_store,
            inline_limit=inline_result_limit,
        )
        self._pending: dict[str, _PendingOperation] = {}
        if artifact_store is not None:
            persist_catalog_for_ear(artifact_store, lock)

    @staticmethod
    def _pending_name(handle_ref: str) -> str:
        return f"pending/{handle_ref.removeprefix('sha256:')}.json"

    def _persist_pending(
        self,
        handle: RegistryHandleV1,
        pending: _PendingOperation,
    ) -> None:
        if self.artifact_store is None or handle.mode != "record":
            return
        payload: dict[str, Any] = {
            "schema_version": "ari.registry-pending/v1",
            "handle_ref": handle.handle_ref,
            "tool_ref": handle.tool_ref,
            "cassette_key": handle.cassette_key,
            "arguments": pending.arguments,
            "selection_reason": pending.selection_reason,
            "rejected_candidates": pending.rejected_candidates,
        }
        payload["pending_digest"] = sha256_digest(payload)
        self.artifact_store.put(
            self._pending_name(handle.handle_ref),
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def _load_pending(self, handle: RegistryHandleV1) -> _PendingOperation | None:
        cached = self._pending.get(handle.handle_ref)
        if cached is not None:
            return cached
        if self.artifact_store is None or handle.mode != "record":
            return None
        name = self._pending_name(handle.handle_ref)
        if not self.artifact_store.exists(name):
            return None
        path = self.artifact_store.get(name)
        if path.stat().st_size > 1_000_000:
            raise BrokerProtocolError("pending invocation context exceeds 1 MB")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise BrokerProtocolError(
                f"pending invocation context is invalid: {exc}"
            ) from exc
        required = {
            "schema_version",
            "handle_ref",
            "tool_ref",
            "cassette_key",
            "arguments",
            "selection_reason",
            "rejected_candidates",
            "pending_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise BrokerProtocolError("pending invocation context has invalid fields")
        digest = payload.pop("pending_digest")
        if digest != sha256_digest(payload):
            raise BrokerProtocolError("pending invocation context digest is invalid")
        if (
            payload["schema_version"] != "ari.registry-pending/v1"
            or payload["handle_ref"] != handle.handle_ref
            or payload["tool_ref"] != handle.tool_ref
            or payload["cassette_key"] != handle.cassette_key
            or not isinstance(payload["arguments"], dict)
            or not isinstance(payload["selection_reason"], str)
            or not isinstance(payload["rejected_candidates"], list)
        ):
            raise BrokerProtocolError(
                "pending invocation context does not match the registry handle"
            )
        pending = _PendingOperation(
            arguments=payload["arguments"],
            selection_reason=payload["selection_reason"],
            rejected_candidates=payload["rejected_candidates"],
        )
        self._pending[handle.handle_ref] = pending
        return pending

    def _descriptor(self, tool_ref: str) -> CanonicalToolDescriptorV1:
        descriptor = self._descriptors.get(tool_ref)
        if descriptor is None:
            raise BrokerAdmissionError(
                "invoke requires an exact tool_ref from the active CATALOG.lock"
            )
        return descriptor

    def _decision(self, tool_ref: str) -> AdmissionDecisionV1:
        decision = self._admissions.get(tool_ref)
        if decision is None:
            raise BrokerProtocolError("active catalog has no admission decision")
        return decision

    def _adapter(self, source_id: str) -> ProviderAdapter:
        override = self._adapters.get(source_id)
        if override is not None:
            return override
        source = self._sources.get(source_id)
        if source is None:
            raise BrokerProtocolError(f"unknown provider source: {source_id}")
        if source.kind == "fixture":
            raise BrokerProtocolError(
                "fixture sources require explicit adapter injection and are not "
                "production-registered"
            )
        if source.kind == "openroad":
            if (
                source.adapter_id != OPENROAD_ADAPTER_ID
                or source.adapter_version != OPENROAD_ADAPTER_VERSION
                or source.adapter_digest != openroad_adapter_digest()
            ):
                raise BrokerProtocolError(
                    "OpenROAD adapter identity drifted from CATALOG.lock"
                )
            leaf_names = {
                descriptor.provider_tool_name
                for descriptor in self.lock.tools
                if source_id in descriptor.source_ids
            }
            try:
                launcher = PythonStdioLauncherV1.model_validate(
                    source.runtime["launcher"]
                )
                pin = OpenRoadProviderPinV1.model_validate(
                    source.runtime["pin"]
                ).model_dump(mode="json")
                raw_experiments = source.runtime["experiments"]
                if not isinstance(raw_experiments, list):
                    raise TypeError("experiments must be an array")
                experiments = [
                    OpenRoadExperimentV1.model_validate(item)
                    for item in raw_experiments
                ]
                expected_names = {
                    OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
                    for profile in experiments
                }
                if leaf_names != expected_names:
                    raise ValueError(
                        "locked OpenROAD leaves do not exactly match runtime profiles"
                    )
                adapter = OpenRoadExperimentAdapter(
                    launcher,
                    expected_provider_digest=source.provider_digest,
                    pin=pin,
                    experiments=experiments,
                    artifact_store=self.artifact_store,
                    allowed_leaf_names=leaf_names,
                    timeout_seconds=float(source.runtime.get("timeout_seconds", 60.0)),
                    max_concurrent_jobs=int(
                        source.runtime.get("max_concurrent_jobs", 4)
                    ),
                    max_retained_jobs=int(
                        source.runtime.get("max_retained_jobs", 1_024)
                    ),
                )
            except (KeyError, TypeError, ValueError, ProviderAdapterError) as exc:
                raise BrokerProtocolError(
                    f"invalid locked OpenROAD runtime for {source_id}: {exc}"
                ) from exc
            self._adapters[source_id] = adapter
            return adapter
        if source.kind == "tooluniverse":
            if (
                source.adapter_id != TOOLUNIVERSE_ADAPTER_ID
                or source.adapter_version != TOOLUNIVERSE_ADAPTER_VERSION
                or source.adapter_digest != tooluniverse_adapter_digest()
            ):
                raise BrokerProtocolError(
                    "ToolUniverse adapter identity drifted from CATALOG.lock"
                )
            leaf_names: set[str] = set()
            leaf_spec_digests: dict[str, str] = {}
            for descriptor in self.lock.tools:
                if source_id not in descriptor.source_ids:
                    continue
                metadata = descriptor.annotations.get("ari_tooluniverse")
                if not isinstance(metadata, dict) or not isinstance(
                    metadata.get("tool_spec_digest"), str
                ):
                    raise BrokerProtocolError(
                        "locked ToolUniverse leaf omitted its specification digest"
                    )
                leaf_names.add(descriptor.provider_tool_name)
                leaf_spec_digests[descriptor.provider_tool_name] = metadata[
                    "tool_spec_digest"
                ]
            try:
                launcher = PythonStdioLauncherV1.model_validate(
                    source.runtime["launcher"]
                )
                pin = source.runtime["pin"]
                if not isinstance(pin, dict):
                    raise TypeError("pin must be an object")
                adapter = ToolUniverseCompactAdapter(
                    launcher,
                    expected_provider_digest=source.provider_digest,
                    pin=pin,
                    allowed_leaf_names=leaf_names,
                    leaf_spec_digests=leaf_spec_digests,
                    timeout_seconds=float(source.runtime.get("timeout_seconds", 60.0)),
                    page_size=int(source.runtime.get("page_size", 250)),
                    info_batch_size=int(source.runtime.get("info_batch_size", 20)),
                    max_pages=int(source.runtime.get("max_pages", 1_000)),
                    max_tools=int(source.runtime.get("max_tools", 100_000)),
                )
            except (KeyError, TypeError, ValueError, ProviderAdapterError) as exc:
                raise BrokerProtocolError(
                    f"invalid locked ToolUniverse runtime for {source_id}: {exc}"
                ) from exc
            self._adapters[source_id] = adapter
            return adapter
        if source.kind != "stdio-mcp":
            raise BrokerProtocolError(
                f"no production adapter is installed for source kind {source.kind}"
            )
        if (
            source.adapter_id != STDIO_ADAPTER_ID
            or source.adapter_version != STDIO_ADAPTER_VERSION
            or source.adapter_digest != stdio_adapter_digest()
        ):
            raise BrokerProtocolError(
                "stdio adapter identity drifted from CATALOG.lock"
            )
        try:
            launcher = PythonStdioLauncherV1.model_validate(source.runtime["launcher"])
            adapter = StdioMCPAdapter(
                launcher,
                expected_provider_digest=source.provider_digest,
                timeout_seconds=float(source.runtime.get("timeout_seconds", 30.0)),
                max_pages=int(source.runtime.get("max_pages", 1_000)),
                max_tools=int(source.runtime.get("max_tools", 100_000)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerProtocolError(
                f"invalid locked stdio runtime for {source_id}: {exc}"
            ) from exc
        self._adapters[source_id] = adapter
        return adapter

    @staticmethod
    def _cursor(payload: dict[str, Any]) -> str:
        encoded = canonical_json(payload).encode("ascii")
        return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")

    @staticmethod
    def _parse_cursor(cursor: str, expected: dict[str, Any]) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(
                base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
            )
        except Exception as exc:
            raise BrokerProtocolError("cursor is malformed") from exc
        for key, value in expected.items():
            if payload.get(key) != value:
                raise BrokerProtocolError("cursor does not belong to this query")
        offset = payload.get("offset")
        if not isinstance(offset, int) or offset < 0:
            raise BrokerProtocolError("cursor offset is invalid")
        return offset

    def discover(
        self,
        query: str,
        constraints: dict[str, Any] | None = None,
        strategy: Literal["lexical", "exact", "diverse"] = "lexical",
        top_k: int = 10,
    ) -> dict[str, Any]:
        constraints = dict(constraints or {})
        unknown = sorted(set(constraints) - _ALLOWED_CONSTRAINTS)
        if unknown:
            raise BrokerProtocolError(f"unknown discover constraints: {unknown}")
        if strategy not in {"lexical", "exact", "diverse"}:
            raise BrokerProtocolError("unknown discovery strategy")
        top_k = max(1, min(int(top_k), MAX_DISCOVER_RESULTS))
        min_level = str(constraints.get("min_admission") or "discovered")
        if min_level not in {
            "discovered",
            "callable",
            "reproducible",
            "scientifically_admitted",
        }:
            raise BrokerProtocolError("min_admission is invalid")
        query_tokens = set(_QUERY_TOKEN_RE.findall(sanitize_text(query).casefold()))
        rejected: list[dict[str, Any]] = []
        matches: list[tuple[float, CanonicalToolDescriptorV1, str]] = []
        entry_by_ref = {entry.tool_ref: entry for entry in self.index.entries}

        for descriptor in self.lock.tools:
            decision = self._decision(descriptor.tool_ref)
            reason = self._constraint_rejection(
                descriptor,
                decision,
                constraints,
                min_level=min_level,  # type: ignore[arg-type]
            )
            if reason is not None:
                rejected.append({"tool_ref": descriptor.tool_ref, "reason": reason})
                continue
            entry = entry_by_ref[descriptor.tool_ref]
            term_set = set(entry.terms)
            exact = query.casefold() in {
                descriptor.name.casefold(),
                descriptor.capability_ref.casefold(),
                descriptor.tool_ref.casefold(),
            }
            matched_query_tokens = {
                query_token
                for query_token in query_tokens
                if any(query_token in term or term in query_token for term in term_set)
            }
            overlap = len(matched_query_tokens)
            if strategy == "exact" and query_tokens and not exact:
                rejected.append(
                    {"tool_ref": descriptor.tool_ref, "reason": "not an exact match"}
                )
                continue
            if query_tokens and overlap == 0 and not exact:
                rejected.append(
                    {"tool_ref": descriptor.tool_ref, "reason": "no lexical overlap"}
                )
                continue
            score = 100.0 if exact else float(overlap * 10)
            if query_tokens:
                score += overlap / max(len(query_tokens), 1)
            score += admission_rank(decision.level) * 0.1
            selection = (
                "exact immutable identity/name/capability match"
                if exact
                else f"{overlap} query token(s) overlap canonical catalog terms"
            )
            matches.append((score, descriptor, selection))

        matches.sort(key=lambda item: (-item[0], item[1].tool_ref))
        if strategy == "diverse":
            matches = self._diversify(matches)
        cursor_constraints = {
            key: value for key, value in constraints.items() if key != "cursor"
        }
        cursor_scope = {
            "catalog_digest": self.lock.catalog_digest,
            "query_digest": sha256_digest(
                {
                    "query": query,
                    "constraints": cursor_constraints,
                    "strategy": strategy,
                }
            ),
        }
        offset = self._parse_cursor(str(constraints.get("cursor") or ""), cursor_scope)
        page = matches[offset : offset + top_k]
        next_offset = offset + len(page)
        next_cursor = (
            self._cursor({**cursor_scope, "offset": next_offset})
            if next_offset < len(matches)
            else None
        )
        results = []
        for score, descriptor, reason in page:
            decision = self._decision(descriptor.tool_ref)
            results.append(
                {
                    "tool_ref": descriptor.tool_ref,
                    "name": descriptor.name,
                    "capability_ref": descriptor.capability_ref,
                    "description": sanitize_text(descriptor.description, limit=240),
                    "provider_id": descriptor.provider_id,
                    "admission_level": decision.level,
                    "invokable": decision.invokable,
                    "independence_group": descriptor.independence_group,
                    "score": round(score, 6),
                    "selection_reason": reason,
                }
            )
        return {
            "schema_version": "ari.discovery-result/v1",
            "catalog_digest": self.lock.catalog_digest,
            "query": sanitize_text(query, limit=500),
            "strategy": strategy,
            "results": results,
            "next_cursor": next_cursor,
            "matched_count": len(matches),
            "rejected_count": len(rejected),
            "rejected_candidates": rejected[:10],
            "quarantined_count": len(self.lock.quarantined),
            "quarantined": [
                {
                    "source_id": item.source_id,
                    "candidate_name": item.candidate_name,
                    "reason_code": item.reason_code,
                }
                for item in self.lock.quarantined[:10]
            ],
        }

    def _constraint_rejection(
        self,
        descriptor: CanonicalToolDescriptorV1,
        decision: AdmissionDecisionV1,
        constraints: dict[str, Any],
        *,
        min_level: AdmissionLevel,
    ) -> str | None:
        checks = (
            ("capability_ref", descriptor.capability_ref),
            ("provider_id", descriptor.provider_id),
            ("side_effects", descriptor.side_effects),
            ("determinism", descriptor.determinism),
        )
        for key, actual in checks:
            expected = constraints.get(key)
            if expected and str(expected) != actual:
                return f"{key} does not match"
        source = constraints.get("source_id")
        if source and str(source) not in descriptor.source_ids:
            return "source_id does not match"
        permission = constraints.get("permission")
        if permission and str(permission) not in descriptor.permissions:
            return "required permission is absent"
        if not meets_admission(decision.level, min_level):
            return f"admission level {decision.level} is below {min_level}"
        return None

    @staticmethod
    def _diversify(
        matches: list[tuple[float, CanonicalToolDescriptorV1, str]],
    ) -> list[tuple[float, CanonicalToolDescriptorV1, str]]:
        remaining = list(matches)
        output: list[tuple[float, CanonicalToolDescriptorV1, str]] = []
        seen_groups: set[str] = set()
        while remaining:
            index = next(
                (
                    idx
                    for idx, (_score, descriptor, _reason) in enumerate(remaining)
                    if descriptor.independence_group not in seen_groups
                ),
                0,
            )
            item = remaining.pop(index)
            output.append(item)
            seen_groups.add(item[1].independence_group)
        return output

    def describe(
        self,
        tool_ref: str,
        section: Literal[
            "summary", "schema", "provenance", "admission", "limitations", "all"
        ] = "summary",
        cursor: str = "",
    ) -> dict[str, Any]:
        descriptor = self._descriptor(tool_ref)
        decision = self._decision(tool_ref)
        if section not in {
            "summary",
            "schema",
            "provenance",
            "admission",
            "limitations",
            "all",
        }:
            raise BrokerProtocolError("unknown descriptor section")
        sections: dict[str, Any] = {
            "summary": {
                "tool_ref": descriptor.tool_ref,
                "name": descriptor.name,
                "description": descriptor.description,
                "capability_ref": descriptor.capability_ref,
                "side_effects": descriptor.side_effects,
                "determinism": descriptor.determinism,
                "permissions": descriptor.permissions,
            },
            "schema": {
                "input_schema": descriptor.input_schema,
                "output_schema": descriptor.output_schema,
                "defaults": descriptor.defaults,
            },
            "provenance": {
                "provider_id": descriptor.provider_id,
                "provider_version": descriptor.provider_version,
                "provider_digest": descriptor.provider_digest,
                "adapter_id": descriptor.adapter_id,
                "adapter_version": descriptor.adapter_version,
                "adapter_digest": descriptor.adapter_digest,
                "source_ids": descriptor.source_ids,
                "leaf_identity": descriptor.leaf_identity,
                "origin_chains": [
                    [hop.model_dump(mode="json") for hop in chain]
                    for chain in descriptor.origin_chains
                ],
                "backend_lineage": descriptor.backend_lineage,
                "data_lineage": descriptor.data_lineage,
                "independence_group": descriptor.independence_group,
            },
            "admission": {
                **decision.model_dump(mode="json"),
                "invokable": decision.invokable,
                "overlaps": [
                    overlap.model_dump(mode="json")
                    for overlap in self.lock.overlaps
                    if tool_ref in overlap.tool_refs
                ],
            },
            "limitations": {
                "semantics": descriptor.semantics,
                "units": descriptor.units,
                "limitations": descriptor.limitations,
            },
        }
        payload = sections if section == "all" else sections[section]
        rendered = canonical_json(payload)
        cursor_scope = {
            "catalog_digest": self.lock.catalog_digest,
            "tool_ref": tool_ref,
            "section": section,
        }
        offset = self._parse_cursor(cursor, cursor_scope)
        chunk = rendered[offset : offset + MAX_DESCRIBE_CHARS]
        next_offset = offset + len(chunk)
        next_cursor = (
            self._cursor({**cursor_scope, "offset": next_offset})
            if next_offset < len(rendered)
            else None
        )
        return {
            "schema_version": "ari.descriptor-page/v1",
            "tool_ref": tool_ref,
            "section": section,
            "content": chunk,
            "next_cursor": next_cursor,
            "content_digest": sha256_digest(payload),
            "total_chars": len(rendered),
        }

    def _validated_arguments(
        self,
        descriptor: CanonicalToolDescriptorV1,
        arguments: dict[str, Any],
        *,
        mode: InvocationMode,
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise BrokerProtocolError("tool arguments must be a JSON object")
        normalized = {**descriptor.defaults, **arguments}
        schema = descriptor.input_schema or {"type": "object"}
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(normalized)
        except (SchemaError, JSONSchemaError) as exc:
            raise BrokerProtocolError(
                f"arguments do not match locked schema: {exc}"
            ) from exc
        if mode == "record":
            credential_paths = credential_field_paths(normalized, "arguments")
            if credential_paths:
                raise BrokerProtocolError(
                    "record mode refuses direct credential fields; use a "
                    f"credential-scope adapter: {credential_paths}"
                )
            properties = schema.get("properties")
            if (
                isinstance(properties, dict)
                and schema.get("additionalProperties") is not True
            ):
                unknown = sorted(set(normalized) - set(properties))
                if unknown:
                    raise BrokerProtocolError(
                        f"record mode rejects unknown fields: {unknown}"
                    )
        return normalized

    def _selection_evidence(
        self, descriptor: CanonicalToolDescriptorV1
    ) -> tuple[str, list[dict[str, Any]]]:
        reason = "explicit immutable tool_ref selected from active CATALOG.lock"
        rejected: list[dict[str, Any]] = []
        for candidate in self.lock.tools:
            if candidate.tool_ref == descriptor.tool_ref:
                continue
            if candidate.capability_ref == descriptor.capability_ref:
                rejected.append(
                    {
                        "tool_ref": candidate.tool_ref,
                        "reason": "overlapping capability was not selected",
                        "independence_group": candidate.independence_group,
                    }
                )
        for candidate in self.lock.admissions:
            if not candidate.invokable and candidate.tool_ref != descriptor.tool_ref:
                rejected.append(
                    {
                        "tool_ref": candidate.tool_ref,
                        "reason": "candidate is below its required admission level",
                    }
                )
        return reason, rejected[:25]

    def _error(
        self,
        *,
        tool_ref: str,
        kind: Literal["transport", "protocol", "admission", "unknown"],
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return self.normalizer.error(
            tool_ref=tool_ref or "ari-tool://unresolved",
            kind=kind,
            message=sanitize_text(message, limit=2_000),
            retryable=retryable,
        ).model_dump(mode="json")

    def _merge_provider_artifacts(
        self,
        response: ProviderResponseV1,
        envelope: ResultEnvelopeV1,
    ) -> ResultEnvelopeV1:
        """Validate adapter-owned artifact references before publishing them."""

        reserved = "_ari_result_artifacts"
        provider_structured = response.structured or _json_object(response.text)
        structured = dict(envelope.structured_content)
        declared_result_digest = provider_structured.get("result_digest")
        if declared_result_digest is not None:
            digest_payload = dict(provider_structured)
            digest_payload.pop("result_digest", None)
            if declared_result_digest != sha256_digest(digest_payload):
                raise BrokerProtocolError("provider structured result digest mismatch")
        present = reserved in provider_structured or reserved in structured
        if not present:
            return envelope
        raw = provider_structured.get(reserved, structured.get(reserved))
        structured.pop(reserved, None)
        if not isinstance(raw, list) or len(raw) > 2_000:
            raise BrokerProtocolError(
                "provider artifact references must be a bounded array"
            )
        if raw and self.artifact_store is None:
            raise BrokerProtocolError(
                "provider returned artifact references without an artifact store"
            )

        refs: list[ResultArtifactV1] = []
        seen_names: dict[str, ResultArtifactV1] = {
            item.logical_name: item for item in envelope.artifacts
        }
        for index, value in enumerate(raw):
            try:
                reference = ResultArtifactV1.model_validate(value)
            except ValueError as exc:
                raise BrokerProtocolError(
                    f"provider artifact reference {index} is invalid: {exc}"
                ) from exc
            hexadecimal = reference.digest.removeprefix("sha256:")
            if not Path(reference.logical_name).name.startswith(hexadecimal):
                raise BrokerProtocolError(
                    "provider artifacts must use a digest-prefixed logical filename"
                )
            assert self.artifact_store is not None
            candidate = self.artifact_store.root
            for part in Path(reference.logical_name).parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    raise BrokerProtocolError(
                        f"provider artifact path contains a symlink: "
                        f"{reference.logical_name}"
                    )
            try:
                path = self.artifact_store.get(reference.logical_name)
                if not path.is_file() or path.is_symlink():
                    raise BrokerProtocolError(
                        f"provider artifact is absent: {reference.logical_name}"
                    )
                if path.stat().st_size != reference.size:
                    raise BrokerProtocolError(
                        f"provider artifact size mismatch: {reference.logical_name}"
                    )
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(chunk)
            except (OSError, RegistryStorageError) as exc:
                raise BrokerProtocolError(
                    f"cannot verify provider artifact {reference.logical_name}: {exc}"
                ) from exc
            if f"sha256:{hasher.hexdigest()}" != reference.digest:
                raise BrokerProtocolError(
                    f"provider artifact digest mismatch: {reference.logical_name}"
                )
            previous = seen_names.get(reference.logical_name)
            if previous is not None and previous != reference:
                raise BrokerProtocolError(
                    f"provider artifact logical name conflicts: "
                    f"{reference.logical_name}"
                )
            if previous is None:
                seen_names[reference.logical_name] = reference
                refs.append(reference)
        return envelope.model_copy(
            update={
                "structured_content": structured,
                "artifacts": [*envelope.artifacts, *refs],
            }
        )

    async def invoke(
        self,
        tool_ref: str,
        arguments: dict[str, Any],
        mode: InvocationMode = "live",
    ) -> dict[str, Any]:
        try:
            descriptor = self._descriptor(tool_ref)
            decision = self._decision(tool_ref)
            if not decision.invokable:
                raise BrokerAdmissionError(
                    f"tool admission level {decision.level} is below "
                    f"required {decision.required_level}: {decision.reasons}"
                )
            if mode not in {"live", "record", "replay"}:
                raise BrokerProtocolError("mode must be live, record, or replay")
            validated = self._validated_arguments(descriptor, arguments, mode=mode)
            selection_reason, rejected = self._selection_evidence(descriptor)
        except BrokerAdmissionError as exc:
            return self._error(
                tool_ref=tool_ref,
                kind="admission",
                message=str(exc),
            )
        except BrokerProtocolError as exc:
            return self._error(tool_ref=tool_ref, kind="protocol", message=str(exc))

        if mode == "replay":
            if self.cassette_store is None:
                return self._error(
                    tool_ref=tool_ref,
                    kind="admission",
                    message="replay mode requires a configured cassette store",
                )
            try:
                cassette = self.cassette_store.load(tool_ref, validated)
            except RegistryStorageError as exc:
                return self._error(
                    tool_ref=tool_ref,
                    kind="protocol",
                    message=str(exc),
                )
            if cassette.catalog_digest != self.lock.catalog_digest:
                return self._error(
                    tool_ref=tool_ref,
                    kind="admission",
                    message="cassette belongs to a different immutable catalog",
                )
            envelope = dict(cassette.result_envelope)
            structured = dict(envelope.get("structured_content") or {})
            structured["_registry_replay"] = {
                "cassette_key": cassette.cassette_key,
                "recorded_policy_digest": cassette.policy_digest,
                "selection_reason": cassette.selection_reason,
            }
            envelope["structured_content"] = structured
            return envelope

        source_id = descriptor.source_ids[0]
        try:
            response = await self._adapter(source_id).invoke(
                descriptor.provider_tool_name, validated
            )
        except ProviderAdapterError as exc:
            return self._error(
                tool_ref=tool_ref,
                kind="transport",
                message=str(exc),
                retryable=True,
            )
        context = ToolCallContextV1(selection_reason=selection_reason)
        try:
            envelope = self.normalizer.normalize_legacy(
                {
                    "result": response.text,
                    "_structured_content": response.structured,
                    "_mcp_is_error": response.is_error,
                },
                tool_ref=tool_ref,
                context=context,
            )
            envelope = self._merge_provider_artifacts(response, envelope)
        except BrokerProtocolError as exc:
            return self._error(tool_ref=tool_ref, kind="protocol", message=str(exc))

        if descriptor.async_lifecycle is not None and envelope.status != "error":
            structured = response.structured or _json_object(response.text)
            handle_value = structured.get(descriptor.async_lifecycle.handle_field)
            if handle_value is None or not str(handle_value):
                return self._error(
                    tool_ref=tool_ref,
                    kind="protocol",
                    message=(
                        "asynchronous provider response omitted locked handle field "
                        f"{descriptor.async_lifecycle.handle_field!r}"
                    ),
                )
            handle = RegistryHandleV1.create(
                tool_ref=tool_ref,
                source_id=source_id,
                provider_handle=str(handle_value),
                lifecycle=descriptor.async_lifecycle,
                cassette_key=(
                    sha256_digest({"tool_ref": tool_ref, "arguments": validated})
                    if mode == "record"
                    else None
                ),
                mode=mode,
            )
            structured = dict(structured)
            structured["status"] = "submitted"
            structured["registry_handle"] = handle.model_dump(mode="json")
            envelope = envelope.model_copy(
                update={"status": "submitted", "structured_content": structured}
            )
            pending = _PendingOperation(
                arguments=validated,
                selection_reason=selection_reason,
                rejected_candidates=rejected,
            )
            self._pending[handle.handle_ref] = pending
            self._persist_pending(handle, pending)
            return envelope.model_dump(mode="json")

        result = envelope.model_dump(mode="json")
        if mode == "record" and envelope.status != "error":
            if self.cassette_store is None:
                return self._error(
                    tool_ref=tool_ref,
                    kind="admission",
                    message="record mode requires a configured cassette store",
                )
            try:
                self.cassette_store.record(
                    tool_ref=tool_ref,
                    arguments=validated,
                    catalog_digest=self.lock.catalog_digest,
                    policy_digest=self.lock.policy_digest,
                    selection_reason=selection_reason,
                    rejected_candidates=rejected,
                    raw_response=response,
                    result_envelope=result,
                )
            except RegistryStorageError as exc:
                return self._error(tool_ref=tool_ref, kind="protocol", message=str(exc))
        return result

    def _validated_handle(self, raw: dict[str, Any]) -> RegistryHandleV1:
        try:
            handle = RegistryHandleV1.model_validate(raw)
        except Exception as exc:
            raise BrokerProtocolError(f"registry handle is malformed: {exc}") from exc
        descriptor = self._descriptor(handle.tool_ref)
        if handle.source_id not in descriptor.source_ids:
            raise BrokerProtocolError("registry handle source is not bound to tool_ref")
        if handle.lifecycle != descriptor.async_lifecycle:
            raise BrokerProtocolError("registry handle lifecycle drifted from tool_ref")
        return handle

    @staticmethod
    def _provider_state(
        handle: RegistryHandleV1, response: ProviderResponseV1
    ) -> tuple[str, dict[str, Any]]:
        if response.is_error:
            raise BrokerProtocolError(
                "provider lifecycle operation returned an MCP error: "
                f"{sanitize_text(response.text, limit=500)}"
            )
        structured = response.structured or _json_object(response.text)
        raw_state = structured.get(handle.lifecycle.state_field)
        if raw_state is None:
            raise BrokerProtocolError(
                f"provider status omitted state field {handle.lifecycle.state_field!r}"
            )
        state = handle.lifecycle.classify(raw_state)
        if state == "unknown":
            raise BrokerProtocolError(
                f"provider returned unknown async state {raw_state!r}"
            )
        return state, structured

    async def get_status(self, raw_handle: dict[str, Any]) -> dict[str, Any]:
        try:
            handle = self._validated_handle(raw_handle)
            response = await self._adapter(handle.source_id).get_status(
                handle.lifecycle, handle.provider_handle
            )
            state, structured = self._provider_state(handle, response)
        except (BrokerError, ProviderAdapterError) as exc:
            return self._error(
                tool_ref=str(raw_handle.get("tool_ref") or ""),
                kind="protocol",
                message=str(exc),
                retryable=isinstance(exc, ProviderAdapterError),
            )
        structured = dict(structured)
        structured["state"] = state
        structured["registry_handle"] = handle.model_dump(mode="json")
        try:
            envelope = self.normalizer.normalize_legacy(
                {
                    "result": response.text,
                    "_structured_content": structured,
                    "_mcp_is_error": response.is_error,
                },
                tool_ref=handle.tool_ref,
            )
            envelope = self._merge_provider_artifacts(response, envelope)
        except BrokerProtocolError as exc:
            return self._error(
                tool_ref=handle.tool_ref, kind="protocol", message=str(exc)
            )
        status = {
            "submitted": "submitted",
            "running": "running",
            "cancelled": "cancelled",
            "succeeded": "ok",
            "failed": "error",
        }[state]
        if status == "error" and envelope.error is None:
            return self._error(
                tool_ref=handle.tool_ref,
                kind="protocol",
                message="provider asynchronous operation failed",
            )
        return envelope.model_copy(update={"status": status}).model_dump(mode="json")

    async def get_result(self, raw_handle: dict[str, Any]) -> dict[str, Any]:
        try:
            handle = self._validated_handle(raw_handle)
            response = await self._adapter(handle.source_id).get_result(
                handle.lifecycle, handle.provider_handle
            )
        except (BrokerError, ProviderAdapterError) as exc:
            return self._error(
                tool_ref=str(raw_handle.get("tool_ref") or ""),
                kind="protocol",
                message=str(exc),
                retryable=isinstance(exc, ProviderAdapterError),
            )
        structured = response.structured or _json_object(response.text)
        if response.is_error:
            return self._error(
                tool_ref=handle.tool_ref,
                kind="protocol",
                message=(
                    "provider result operation returned an MCP error: "
                    f"{sanitize_text(response.text, limit=500)}"
                ),
            )
        raw_state = structured.get(handle.lifecycle.state_field)
        if raw_state is not None:
            state = handle.lifecycle.classify(raw_state)
            if state == "unknown":
                return self._error(
                    tool_ref=handle.tool_ref,
                    kind="protocol",
                    message=f"provider returned unknown async state {raw_state!r}",
                )
            if state in {"submitted", "running"}:
                return await self.get_status(raw_handle)
            if state == "cancelled":
                try:
                    envelope = self.normalizer.normalize_legacy(
                        {"result": response.text, "_structured_content": structured},
                        tool_ref=handle.tool_ref,
                    )
                    envelope = self._merge_provider_artifacts(response, envelope)
                except BrokerProtocolError as exc:
                    return self._error(
                        tool_ref=handle.tool_ref,
                        kind="protocol",
                        message=str(exc),
                    )
                return envelope.model_copy(update={"status": "cancelled"}).model_dump(
                    mode="json"
                )
            if state == "failed":
                failure = self.normalizer.error(
                    tool_ref=handle.tool_ref,
                    kind="protocol",
                    message=sanitize_text(
                        str(
                            structured.get("error")
                            or "provider asynchronous operation failed"
                        ),
                        limit=2_000,
                    ),
                    retryable=False,
                )
                try:
                    return self._merge_provider_artifacts(response, failure).model_dump(
                        mode="json"
                    )
                except BrokerProtocolError as exc:
                    return self._error(
                        tool_ref=handle.tool_ref,
                        kind="protocol",
                        message=str(exc),
                    )
        try:
            envelope = self.normalizer.normalize_legacy(
                {
                    "result": response.text,
                    "_structured_content": response.structured,
                    "_mcp_is_error": response.is_error,
                },
                tool_ref=handle.tool_ref,
            )
            envelope = self._merge_provider_artifacts(response, envelope)
        except BrokerProtocolError as exc:
            return self._error(
                tool_ref=handle.tool_ref, kind="protocol", message=str(exc)
            )
        result = envelope.model_dump(mode="json")
        if handle.mode == "record" and envelope.status != "error":
            try:
                pending = self._load_pending(handle)
            except BrokerProtocolError as exc:
                return self._error(
                    tool_ref=handle.tool_ref,
                    kind="protocol",
                    message=str(exc),
                )
            if pending is None:
                return self._error(
                    tool_ref=handle.tool_ref,
                    kind="protocol",
                    message="record-mode async handle lost its submission context",
                )
            if self.cassette_store is None:
                return self._error(
                    tool_ref=handle.tool_ref,
                    kind="admission",
                    message="record mode requires a configured cassette store",
                )
            try:
                self.cassette_store.record(
                    tool_ref=handle.tool_ref,
                    arguments=pending.arguments,
                    catalog_digest=self.lock.catalog_digest,
                    policy_digest=self.lock.policy_digest,
                    selection_reason=pending.selection_reason,
                    rejected_candidates=pending.rejected_candidates,
                    raw_response=response,
                    result_envelope=result,
                )
            except RegistryStorageError as exc:
                return self._error(
                    tool_ref=handle.tool_ref, kind="protocol", message=str(exc)
                )
            self._pending.pop(handle.handle_ref, None)
        return result

    async def cancel(self, raw_handle: dict[str, Any]) -> dict[str, Any]:
        """Internal provider capability; intentionally absent from the 5-tool LLM API."""

        try:
            handle = self._validated_handle(raw_handle)
            if handle.lifecycle.cancel_tool is None:
                raise BrokerProtocolError("asynchronous operation is not cancellable")
            response = await self._adapter(handle.source_id).cancel(
                handle.lifecycle, handle.provider_handle
            )
        except (BrokerError, ProviderAdapterError) as exc:
            return self._error(
                tool_ref=str(raw_handle.get("tool_ref") or ""),
                kind="protocol",
                message=str(exc),
            )
        if response.is_error:
            return self._error(
                tool_ref=handle.tool_ref,
                kind="protocol",
                message=(
                    "provider cancel operation returned an MCP error: "
                    f"{sanitize_text(response.text, limit=500)}"
                ),
            )
        try:
            envelope = self.normalizer.normalize_legacy(
                {
                    "result": response.text,
                    "_structured_content": response.structured,
                    "_mcp_is_error": response.is_error,
                },
                tool_ref=handle.tool_ref,
            )
            envelope = self._merge_provider_artifacts(response, envelope)
        except BrokerProtocolError as exc:
            return self._error(
                tool_ref=handle.tool_ref, kind="protocol", message=str(exc)
            )
        self._pending.pop(handle.handle_ref, None)
        return envelope.model_copy(update={"status": "cancelled"}).model_dump(
            mode="json"
        )


__all__ = [
    "BrokerAdmissionError",
    "BrokerError",
    "BrokerProtocolError",
    "CatalogBroker",
    "MAX_DESCRIBE_CHARS",
    "MAX_DISCOVER_RESULTS",
]
