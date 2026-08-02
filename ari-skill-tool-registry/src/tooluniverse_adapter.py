"""Pinned ToolUniverse compact-collection transport.

ToolUniverse is treated as one collection provider.  Its compact MCP tools are
never exposed on ARI's public MCP surface: this adapter expands reviewed leaf
descriptors during operator sync and executes only leaf names already present
in the active catalog lock.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from models import canonical_json, sanitize_text, sha256_digest
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    stdio_adapter_digest,
)


TOOLUNIVERSE_ADAPTER_ID = "ari.tooluniverse-compact"
TOOLUNIVERSE_ADAPTER_VERSION = "1.0.0"
TOOLUNIVERSE_COMPACT_TOOLS = frozenset(
    {"list_tools", "grep_tools", "get_tool_info", "execute_tool"}
)
_NON_LEAF_TOOLS = TOOLUNIVERSE_COMPACT_TOOLS | frozenset({"find_tools"})
_SUPPORT_MATRIX = (
    Path(__file__).resolve().parent.parent
    / "providers"
    / "tooluniverse-support-v1.json"
)
_DANGEROUS_TYPE_FRAGMENTS = (
    "agentic",
    "codeinterpreter",
    "compose",
    "mcpautoloader",
    "mcpclient",
    "pythonexecutor",
    "shelltool",
    "toolfinderllm",
)
_DANGEROUS_CATEGORY_PREFIXES = (
    "mcp_auto_loader",
    "agentic",
    "code_interpreter",
)
_AUTH_FAILURE_RE = re.compile(
    r"(?:unauthori[sz]ed|unauthenticated|authentication failed|"
    r"invalid api key|missing api key|forbidden)",
    re.IGNORECASE,
)


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ProviderProtocolError(f"cannot read adapter support file: {exc}") from exc
    return f"sha256:{hasher.hexdigest()}"


def _support_document() -> dict[str, Any]:
    try:
        value = json.loads(_SUPPORT_MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ProviderProtocolError(
            f"ToolUniverse support matrix is unavailable or invalid: {exc}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != (
        "ari.tooluniverse-support/v1"
    ):
        raise ProviderProtocolError("ToolUniverse support matrix version is invalid")
    releases = value.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ProviderProtocolError("ToolUniverse support matrix has no releases")
    return value


def verify_tooluniverse_pin(pin: dict[str, Any]) -> None:
    """Require an exact entry from the reviewed support matrix."""

    releases = _support_document()["releases"]
    if pin not in releases:
        version = sanitize_text(pin.get("version", "<unknown>"), limit=100)
        raise ProviderProtocolError(
            f"ToolUniverse {version} is not an exact reviewed support-matrix pin"
        )


def tooluniverse_release_pin(version: str) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["releases"]
        if item.get("version") == version
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"ToolUniverse release {sanitize_text(version, limit=100)!r} is not supported"
        )
    return dict(matches[0])


def verify_tooluniverse_package(
    launcher: PythonStdioLauncherV1,
    pin: dict[str, Any],
) -> None:
    """Match the installed package tree to the exact reviewed wheel payload."""

    root, _executable, _entrypoint = launcher.resolve()
    if root.name != "tooluniverse":
        raise ProviderProtocolError(
            "ToolUniverse package_root must be the exact installed tooluniverse directory"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if len(files) >= 50_000:
            raise ProviderProtocolError("ToolUniverse package exceeds 50,000 files")
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > 500_000_000:
            raise ProviderProtocolError("ToolUniverse package exceeds 500 MB")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "digest": _file_sha256(path),
            }
        )
    actual = sha256_digest(files)
    expected = pin.get("package_tree_digest")
    if actual != expected:
        raise ProviderProtocolError(
            "ToolUniverse installed package tree does not match the reviewed wheel: "
            f"expected {expected}, got {actual}"
        )


def tooluniverse_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_sha256(Path(__file__).resolve()),
            "generic_stdio_adapter": stdio_adapter_digest(),
            "support_matrix": _file_sha256(_SUPPORT_MATRIX),
        }
    )


def dangerous_leaf(category: str, tool_type: str) -> str | None:
    normalized_type = re.sub(r"[^a-z0-9]", "", tool_type.casefold())
    for fragment in _DANGEROUS_TYPE_FRAGMENTS:
        if fragment in normalized_type:
            return f"tool type {tool_type!r} is execution-composing or dynamic"
    folded_category = category.casefold()
    if any(
        folded_category.startswith(prefix) for prefix in _DANGEROUS_CATEGORY_PREFIXES
    ):
        return f"category {category!r} can dynamically load or execute tools"
    return None


def _response_object(response: ProviderResponseV1, operation: str) -> dict[str, Any]:
    if response.is_error:
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} failed: "
            f"{sanitize_text(response.text, limit=1_000)}"
        )
    value: Any = response.structured
    if not isinstance(value, dict):
        try:
            value = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderProtocolError(
                f"ToolUniverse compact operation {operation} returned non-JSON"
            ) from exc
    if isinstance(value, dict) and set(value) == {"result"}:
        nested = value["result"]
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except json.JSONDecodeError:
                pass
        if isinstance(nested, dict):
            value = nested
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} returned a non-object"
        )
    status = str(value.get("status") or "").casefold()
    if (
        status in {"error", "failed", "failure", "unauthorized"}
        or (value.get("error_type") and value.get("error"))
        or (value.get("success") is False and value.get("error"))
    ):
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} failed: "
            f"{sanitize_text(value.get('error'), limit=1_000)}"
        )
    return value


def _schema(value: Any, *, field: str, tool_name: str) -> dict[str, Any]:
    if value is None and field == "output_schema":
        return {}
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has a non-object {field}"
        )
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has an invalid {field}: {exc.message}"
        ) from exc
    if len(canonical_json(value).encode("utf-8")) > 262_144:
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has a {field} larger than 256 KiB"
        )
    return value


def _normalize_property_required_markers(
    value: Any,
    *,
    path: str = "$",
) -> tuple[Any, list[str]]:
    """Translate ToolUniverse's pinned property-level required dialect.

    ToolUniverse v1.3.1 represents required parameters as
    ``properties.<name>.required: true``.  Draft 2020-12 represents the same
    constraint as the property name in the containing object's ``required``
    array.  No value types or defaults are changed.
    """

    if isinstance(value, list):
        output: list[Any] = []
        notes: list[str] = []
        for index, item in enumerate(value):
            normalized, child_notes = _normalize_property_required_markers(
                item, path=f"{path}/{index}"
            )
            output.append(normalized)
            notes.extend(child_notes)
        return output, notes
    if not isinstance(value, dict):
        return value, []

    output: dict[str, Any] = {}
    notes: list[str] = []
    for key, item in value.items():
        if key == "properties" and isinstance(item, dict):
            properties: dict[str, Any] = {}
            marker_required: list[str] = []
            for property_name, property_schema in item.items():
                normalized, child_notes = _normalize_property_required_markers(
                    property_schema,
                    path=f"{path}/properties/{property_name}",
                )
                if isinstance(normalized, dict) and isinstance(
                    normalized.get("required"), bool
                ):
                    marker = normalized.pop("required")
                    if marker:
                        marker_required.append(str(property_name))
                    child_notes.append(
                        f"property-required-marker:{path}/properties/{property_name}"
                    )
                properties[str(property_name)] = normalized
                notes.extend(child_notes)
            output[key] = properties
            existing = value.get("required")
            if marker_required and (
                existing is None
                or (
                    isinstance(existing, list)
                    and all(isinstance(item, str) for item in existing)
                )
            ):
                output["required"] = sorted(set(marker_required) | set(existing or []))
            continue
        if key == "required" and "required" in output:
            continue
        normalized, child_notes = _normalize_property_required_markers(
            item, path=f"{path}/{key}"
        )
        output[str(key)] = normalized
        notes.extend(child_notes)
    return output, notes


def _metadata(summary: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "category",
        "type",
        "source_file",
        "package_name",
        "endpoint",
        "tool_url",
        "required_api_keys",
        "optional_api_keys",
        "metadata",
        "local_info",
        "remote_info",
    )
    metadata: dict[str, Any] = {}
    for key in keys:
        value = spec.get(key, summary.get(key))
        if value is not None:
            metadata[key] = value
    return metadata


class _ToolUniverseStdioTransport(StdioMCPAdapter):
    """Stdio transport with ToolUniverse's mutable user state disabled."""

    def _environment(self, isolated_home: Path) -> dict[str, str]:
        environment = super()._environment(isolated_home)
        workspace = isolated_home / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "TOOLUNIVERSE_HOME": str(workspace),
                "TOOLUNIVERSE_COERCE_TYPES": "false",
                "TOOLUNIVERSE_STRICT_VALIDATION": "true",
                "TOOLUNIVERSE_CACHE_ENABLED": "false",
                "TOOLUNIVERSE_CACHE_PERSIST": "false",
                "FASTMCP_CHECK_FOR_UPDATES": "off",
                "FASTMCP_SHOW_SERVER_BANNER": "false",
            }
        )
        return environment


class ToolUniverseCompactAdapter:
    """Expand and invoke ToolUniverse leaves through four compact MCP tools."""

    def __init__(
        self,
        launcher: PythonStdioLauncherV1,
        *,
        expected_provider_digest: str,
        pin: dict[str, Any],
        include_categories: Iterable[str] = (),
        exclude_categories: Iterable[str] = (),
        allowed_leaf_names: Iterable[str] | None = None,
        leaf_spec_digests: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        page_size: int = 250,
        info_batch_size: int = 20,
        max_pages: int = 1_000,
        max_tools: int = 100_000,
        transport: ProviderAdapter | None = None,
        verify_package: bool = True,
    ) -> None:
        verify_tooluniverse_pin(pin)
        if verify_package:
            verify_tooluniverse_package(launcher, pin)
        if page_size < 1 or page_size > 1_000:
            raise ValueError("ToolUniverse page_size must be between 1 and 1000")
        if info_batch_size < 1 or info_batch_size > 100:
            raise ValueError("ToolUniverse info_batch_size must be between 1 and 100")
        if max_pages < 1 or max_tools < 1:
            raise ValueError("ToolUniverse collection bounds must be positive")
        self.launcher = launcher
        self.expected_provider_digest = expected_provider_digest
        self.pin = dict(pin)
        self.include_categories = frozenset(include_categories)
        self.exclude_categories = frozenset(exclude_categories)
        overlap = self.include_categories & self.exclude_categories
        if overlap:
            raise ValueError(
                f"ToolUniverse category filters overlap: {sorted(overlap)}"
            )
        self.allowed_leaf_names = (
            frozenset(allowed_leaf_names) if allowed_leaf_names is not None else None
        )
        self.leaf_spec_digests = dict(leaf_spec_digests or {})
        self.timeout_seconds = timeout_seconds
        self.page_size = page_size
        self.info_batch_size = info_batch_size
        self.max_pages = max_pages
        self.max_tools = max_tools
        self.transport = transport or _ToolUniverseStdioTransport(
            launcher,
            expected_provider_digest=expected_provider_digest,
            timeout_seconds=timeout_seconds,
            max_pages=8,
            max_tools=16,
        )

    async def _call(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        transport: ProviderAdapter | None = None,
    ) -> dict[str, Any]:
        response = await (transport or self.transport).invoke(operation, arguments)
        return _response_object(response, operation)

    async def _summaries(
        self, transport: ProviderAdapter | None = None
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        offset = 0
        for _page in range(self.max_pages):
            payload = await self._call(
                "list_tools",
                {
                    "mode": "custom",
                    "fields": [
                        "name",
                        "type",
                        "category",
                        "source_file",
                        "package_name",
                        "required_api_keys",
                        "optional_api_keys",
                    ],
                    "limit": self.page_size,
                    "offset": offset,
                },
                transport=transport,
            )
            tools = payload.get("tools")
            if not isinstance(tools, list):
                raise ProviderProtocolError(
                    "ToolUniverse list_tools response omitted its tools array"
                )
            for raw in tools:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    raise ProviderProtocolError(
                        "ToolUniverse list_tools returned a malformed tool summary"
                    )
                name = raw["name"]
                if name in seen_names:
                    raise ProviderProtocolError(
                        f"ToolUniverse list_tools returned duplicate leaf {name!r}"
                    )
                seen_names.add(name)
                category = raw.get("category")
                if not isinstance(category, str) or not category:
                    category = "unknown"
                    raw = {**raw, "category": category}
                selected = (
                    not self.include_categories or category in self.include_categories
                ) and category not in self.exclude_categories
                if name not in _NON_LEAF_TOOLS and selected:
                    summaries.append(raw)
                    if len(summaries) > self.max_tools:
                        raise ProviderProtocolError(
                            f"ToolUniverse exceeds max_tools={self.max_tools}"
                        )
            has_more = payload.get("has_more")
            next_offset = payload.get("next_offset")
            if has_more is False or (has_more is None and len(tools) < self.page_size):
                return summaries
            if not isinstance(next_offset, int):
                next_offset = offset + len(tools)
            if next_offset <= offset:
                raise ProviderProtocolError(
                    "ToolUniverse list_tools pagination did not advance"
                )
            offset = next_offset
        raise ProviderProtocolError(
            f"ToolUniverse list_tools exceeds max_pages={self.max_pages}"
        )

    async def _list_tools_connected(
        self, transport: ProviderAdapter | None = None
    ) -> list[ProviderToolV1]:
        summaries = await self._summaries(transport)
        by_name = {item["name"]: item for item in summaries}
        names = sorted(by_name)
        output: list[ProviderToolV1] = []
        for offset in range(0, len(names), self.info_batch_size):
            batch = names[offset : offset + self.info_batch_size]
            payload = await self._call(
                "get_tool_info",
                {"tool_names": batch, "detail_level": "full"},
                transport=transport,
            )
            raw_tools = payload.get("tools")
            if not isinstance(raw_tools, list):
                if len(batch) == 1 and payload.get("name") == batch[0]:
                    raw_tools = [payload]
                else:
                    raise ProviderProtocolError(
                        "ToolUniverse get_tool_info response omitted its tools array"
                    )
            returned: set[str] = set()
            for spec in raw_tools:
                if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
                    raise ProviderProtocolError(
                        "ToolUniverse get_tool_info returned a malformed definition"
                    )
                name = spec["name"]
                if name not in batch or name in returned or spec.get("error"):
                    raise ProviderProtocolError(
                        f"ToolUniverse get_tool_info did not define locked leaf {name!r}"
                    )
                returned.add(name)
                summary = by_name[name]
                for key in ("type", "category"):
                    if key in spec and key in summary and spec[key] != summary[key]:
                        raise ProviderProtocolError(
                            f"ToolUniverse leaf {name!r} changed {key} during sync"
                        )
                schema_errors: list[str] = []
                schema_normalizations: list[str] = []
                try:
                    normalized_input, input_notes = (
                        _normalize_property_required_markers(spec.get("parameter"))
                    )
                    schema_normalizations.extend(input_notes)
                    input_schema = _schema(
                        normalized_input,
                        field="input_schema",
                        tool_name=name,
                    )
                    if "required" not in input_schema and isinstance(
                        spec.get("required"), list
                    ):
                        input_schema = {**input_schema, "required": spec["required"]}
                        Draft202012Validator.check_schema(input_schema)
                except (ProviderProtocolError, SchemaError) as exc:
                    schema_errors.append(sanitize_text(exc, limit=1_000))
                    input_schema = {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    }
                try:
                    normalized_output, output_notes = (
                        _normalize_property_required_markers(spec.get("return_schema"))
                    )
                    schema_normalizations.extend(output_notes)
                    output_schema = _schema(
                        normalized_output,
                        field="output_schema",
                        tool_name=name,
                    )
                except ProviderProtocolError as exc:
                    schema_errors.append(sanitize_text(exc, limit=1_000))
                    output_schema = {}
                metadata = _metadata(summary, spec)
                metadata.update(
                    {
                        "collection": "tooluniverse",
                        "collection_version": self.pin["version"],
                        "collection_wheel_digest": self.pin["wheel_digest"],
                        "tool_spec_digest": sha256_digest(spec),
                    }
                )
                if schema_errors:
                    metadata["schema_errors"] = schema_errors
                if schema_normalizations:
                    metadata["schema_normalizations"] = sorted(
                        set(schema_normalizations)
                    )[:1_000]
                output.append(
                    ProviderToolV1(
                        name=name,
                        description=str(spec.get("description") or ""),
                        input_schema=input_schema,
                        output_schema=output_schema,
                        annotations={"ari_tooluniverse": metadata},
                    )
                )
            missing = sorted(set(batch) - returned)
            if missing:
                raise ProviderProtocolError(
                    f"ToolUniverse get_tool_info omitted leaves: {missing}"
                )
        return sorted(output, key=lambda tool: tool.name)

    async def list_tools(self) -> list[ProviderToolV1]:
        connection = getattr(self.transport, "connection", None)
        if connection is None:
            return await self._list_tools_connected()
        result: list[ProviderToolV1] | None = None
        failure: ProviderProtocolError | None = None
        async with connection() as connected:
            try:
                result = await self._list_tools_connected(connected)
            except ProviderProtocolError as exc:
                # Exit the AnyIO task group normally so it does not obscure the
                # leaf protocol error inside an ExceptionGroup.
                failure = exc
        if failure is not None:
            raise failure
        assert result is not None
        return result

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        if self.allowed_leaf_names is None or name not in self.allowed_leaf_names:
            raise ProviderProtocolError(
                "ToolUniverse runtime accepts only a leaf from the active catalog lock"
            )
        null_fields = sorted(key for key, value in arguments.items() if value is None)
        if null_fields:
            raise ProviderProtocolError(
                "ToolUniverse strips explicit null values; locked invocation refuses "
                f"ambiguous fields {null_fields}"
            )
        response = await self.transport.invoke(
            "execute_tool", {"tool_name": name, "arguments": arguments}
        )
        try:
            value = _response_object(response, "execute_tool")
            failed = False
        except ProviderProtocolError:
            value = None
            failed = True
        text = response.text
        is_auth_failure = bool(_AUTH_FAILURE_RE.search(text))
        is_error = response.is_error or failed or is_auth_failure
        structured = dict(
            response.structured or (value if isinstance(value, dict) else {})
        )
        reserved = "_ari_collection_provenance"
        if reserved in structured:
            raise ProviderProtocolError(
                f"ToolUniverse leaf {name!r} returned reserved field {reserved!r}"
            )
        structured[reserved] = {
            "adapter_id": TOOLUNIVERSE_ADAPTER_ID,
            "adapter_version": TOOLUNIVERSE_ADAPTER_VERSION,
            "collection": "tooluniverse",
            "collection_version": self.pin["version"],
            "collection_wheel_digest": self.pin["wheel_digest"],
            "provider_digest": self.expected_provider_digest,
            "leaf_spec_digest": self.leaf_spec_digests.get(name),
            "upstream_cache": "disabled",
        }
        return ProviderResponseV1(
            text=text,
            structured=structured,
            is_error=is_error,
        )

    async def get_status(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )

    async def get_result(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )

    async def cancel(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )


__all__ = [
    "TOOLUNIVERSE_ADAPTER_ID",
    "TOOLUNIVERSE_ADAPTER_VERSION",
    "TOOLUNIVERSE_COMPACT_TOOLS",
    "ToolUniverseCompactAdapter",
    "dangerous_leaf",
    "tooluniverse_adapter_digest",
    "tooluniverse_release_pin",
    "verify_tooluniverse_package",
    "verify_tooluniverse_pin",
]
