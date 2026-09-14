"""Thread-safe pooled MCP stdio client with bounded retries and typed results."""

from __future__ import annotations

import atexit
import logging
import os
import time
from pathlib import Path

from ari.async_tools import (
    AsyncLifecycleV1,
    AsyncToolEndpointV1,
    AsyncToolHandleV1,
)
from ari.call_context import ToolCallContextV1, new_context_authority_key
from ari.config import SkillConfig
from ari.mcp.connection import SkillConnection
from ari.mcp.dispatch_support import (
    DEFAULT_TOOL_TIMEOUT as DEFAULT_TOOL_TIMEOUT,
    SLOW_TOOL_TIMEOUT as SLOW_TOOL_TIMEOUT,
    VERY_SLOW_TOOL_TIMEOUT as VERY_SLOW_TOOL_TIMEOUT,
    ToolNameCollisionError,
    default_call_context,
    enrich_call_context,
    log_tool_call,
    phase_matches as _phase_matches,
    resolve_registration as _resolve_registration,
    resolve_tool_timeout as _resolve_tool_timeout,
    runtime_tool_ref,
    unresolved_tool_ref as _unresolved_tool_ref,
)
from ari.mcp.lock_runtime import SkillLockController
from ari.mcp.invoke_runtime import invoke_with_retries
from ari.mcp.registry_runtime import discover_registry
from ari.protocols.stores import ArtifactStore
from ari.protocols.mcp import ToolAuthorizationViewProtocol
from ari.result import (
    DEFAULT_INLINE_RESULT_LIMIT,
    ResultEnvelopeNormalizer,
    ResultEnvelopeV1,
    ResultErrorV1,
    utc_now_iso,
)
from ari.skill_lock import SkillLockError, SkillsLockV1

logger = logging.getLogger(__name__)

# Private compatibility alias.  Connection ownership moved to connection.py;
# callers outside ari.mcp should use MCPClient rather than this implementation.
_SkillConnection = SkillConnection
_runtime_tool_ref = runtime_tool_ref


class MCPClient:
    """MCP client with connection pooling and retry logic."""

    def __init__(
        self,
        skills: list[SkillConfig],
        disabled_tools: list[str] | None = None,
        *,
        artifact_store: ArtifactStore | None = None,
        result_inline_limit: int = DEFAULT_INLINE_RESULT_LIMIT,
        skill_lock_path: str | Path | None = None,
        skill_lock_scope: str = "exact",
        strict_provider_loading: bool | None = None,
        tool_authorization_view: ToolAuthorizationViewProtocol | None = None,
    ) -> None:
        import threading as _t

        self.skills = skills
        self.disabled_tools: set[str] = set(disabled_tools or [])
        self._connections: dict[str, _SkillConnection] = {}
        self._conn_lock = _t.Lock()
        self._context_authority_keys: dict[str, str] = {
            skill.name: new_context_authority_key() for skill in skills
        }
        self._tool_registry: dict[str, str] = {}  # tool_name -> skill.name
        self._tool_ref_registry: dict[str, str] = {}  # tool_ref -> skill.name
        self._tool_name_by_ref: dict[str, str] = {}
        self._tool_ref_by_name: dict[str, str] = {}
        self._tool_metadata_by_ref: dict[str, dict] = {}
        self._tools_cache: list[dict] | None = None
        self._artifact_store = artifact_store
        self._derived_artifact_store: tuple[str, ArtifactStore] | None = None
        self._result_inline_limit = result_inline_limit
        self._skill_lock = SkillLockController(
            skill_lock_path,
            scope=skill_lock_scope,
            strict_provider_loading=strict_provider_loading,
        )
        self._tool_authorization_view = tool_authorization_view
        atexit.register(self.close_all)

    def _get_conn(self, skill_name: str) -> _SkillConnection | None:
        return self._connections.get(skill_name)

    def _init_connection(self, skill: SkillConfig) -> _SkillConnection:
        with self._conn_lock:
            if skill.name not in self._connections:
                conn = _SkillConnection(
                    skill,
                    context_authority_key=self._context_authority_keys.setdefault(
                        skill.name, new_context_authority_key()
                    ),
                )
                self._connections[skill.name] = conn
            return self._connections[skill.name]

    def list_tools(
        self,
        phase: str | None = None,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> list[dict]:
        """Return tools admitted by phase and, when supplied, call context."""
        if self._tools_cache is None:
            self._build_tools_cache()

        tools = self._tools_cache
        # Filter by disabled_tools
        if self.disabled_tools:
            tools = [t for t in tools if t["name"] not in self.disabled_tools]
        # Filter by phase. Skill `phase` may be a string or a list; matching is
        # any-of with "all" as wildcard. Canonical per-tool policy is an
        # additional constraint rather than a replacement for Skill exposure.
        if phase is not None:
            tools = [t for t in tools if self._tool_admits_phase(t["tool_ref"], phase)]
        if context is not None:
            tools = [
                tool
                for tool in tools
                if context.satisfies(self._tool_context_requirement(tool["tool_ref"]))
            ]
        if self._tool_authorization_view is not None:
            tools = [
                tool
                for tool in tools
                if self._tool_authorization_view.decide(
                    tool["tool_ref"], phase=phase, context=context
                ).allowed
            ]
        return tools

    def _build_tools_cache(self) -> None:
        """Discover tools from all enabled skills exactly once."""

        discovered = discover_registry(
            self.skills,
            init_connection=self._init_connection,
            close_all=self.close_all,
            strict_provider_loading=self._skill_lock.strict_provider_loading,
        )
        self._tool_registry = discovered.owner_by_name
        self._tool_ref_registry = discovered.owner_by_ref
        self._tool_name_by_ref = discovered.name_by_ref
        self._tool_ref_by_name = discovered.ref_by_name
        self._tool_metadata_by_ref = discovered.metadata_by_ref
        self._tools_cache = discovered.tools
        self._reconcile_skills_lock()

    def _reconcile_skills_lock(self) -> None:
        """Create or verify the run's immutable live-provider snapshot."""

        try:
            self._skill_lock.reconcile(
                skills=self.skills,
                tools=self._tools_cache or [],
                disabled_tools=self.disabled_tools,
            )
        except SkillLockError:
            self.close_all()
            self._tool_registry = {}
            self._tool_ref_registry = {}
            self._tool_name_by_ref = {}
            self._tool_ref_by_name = {}
            self._tool_metadata_by_ref = {}
            self._tools_cache = None
            self._skill_lock.clear()
            raise

    def install_tool_authorization_view(
        self, view: ToolAuthorizationViewProtocol
    ) -> None:
        """Install the run-frozen Binding projection exactly once.

        Admission occurs after root proposal/Research Contract, whereas MCP
        discovery creates ``SKILLS.lock`` earlier.  This narrow seam lets the
        trusted runtime attach the resulting authority view without creating a
        second MCP client or mutating Provider discovery state.
        """

        current = self._tool_authorization_view
        if current is not None:
            if getattr(current, "lock_digest", None) != getattr(view, "lock_digest", None):
                raise ValueError("Capability Binding authorization view is immutable")
            return
        self._tool_authorization_view = view

    @property
    def skills_lock(self) -> SkillsLockV1 | None:
        """Return the reconciled snapshot after discovery, if locking is enabled."""

        return self._skill_lock.snapshot

    def call_tool(
        self,
        tool_name: str,
        args: dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> dict:
        """Call a tool with explicit run/node context when policy requires it."""

        envelope = self.call_tool_envelope(tool_name, args, context=context)
        return envelope.to_legacy(self._artifact_store_for_call())

    def call_tool_envelope(
        self,
        tool_name_or_ref: str,
        args: dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Call a tool and return the canonical typed result envelope.

        ``tool_name_or_ref`` accepts an immutable ``tool_ref`` or a unique bare
        alias during migration.  New federation callers should always pass the
        immutable reference returned by :meth:`list_tools`.
        """

        if self._tools_cache is None:
            started_at = utc_now_iso()
            try:
                self._build_tools_cache()
            except (ToolNameCollisionError, SkillLockError) as exc:
                return self._result_normalizer().error(
                    tool_ref=_unresolved_tool_ref(tool_name_or_ref),
                    kind="admission",
                    message=str(exc),
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )

        return self._call_tool_envelope_unlocked(
            tool_name_or_ref,
            args,
            context=context,
        )

    def _call_tool_envelope_unlocked(
        self,
        tool_name_or_ref: str,
        args: dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Typed dispatch implementation."""

        started_at = utc_now_iso()
        normalizer = self._result_normalizer()
        if self._tools_cache is None:
            try:
                self._build_tools_cache()
            except (ToolNameCollisionError, SkillLockError) as exc:
                return normalizer.error(
                    tool_ref=_unresolved_tool_ref(tool_name_or_ref),
                    kind="admission",
                    message=str(exc),
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )

        tool_name, tool_ref, skill_name, selection_reason = _resolve_registration(
            tool_name_or_ref,
            tool_ref_registry=self._tool_ref_registry,
            tool_name_by_ref=self._tool_name_by_ref,
            tool_registry=self._tool_registry,
            tool_ref_by_name=self._tool_ref_by_name,
        )
        effective_context = context or self._default_call_context()
        effective_context = enrich_call_context(
            effective_context,
            selection_reason=selection_reason,
            skill=next(
                (skill for skill in self.skills if skill.name == skill_name),
                None,
            ),
        )

        admission_error = self._registration_admission_error(
            requested=tool_name_or_ref,
            tool_name=tool_name,
            tool_ref=tool_ref,
            skill_name=skill_name,
            context=effective_context,
            normalizer=normalizer,
            started_at=started_at,
            arguments=args or {},
        )
        if admission_error is not None:
            return admission_error
        assert skill_name is not None

        observer = getattr(self._tool_authorization_view, "record_invocation", None)
        if callable(observer):
            observer(
                tool_ref,
                phase=effective_context.phase,
                context=effective_context,
                arguments=args or {},
            )

        return self._invoke_registered_tool(
            tool_name=tool_name,
            tool_ref=tool_ref,
            skill_name=skill_name,
            args=args,
            context=effective_context,
            normalizer=normalizer,
            started_at=started_at,
        )

    def get_async_status(
        self,
        handle: AsyncToolHandleV1 | dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Poll an async handle through its immutable status endpoint."""

        parsed = self._parse_async_handle(handle, context=context)
        if isinstance(parsed, ResultEnvelopeV1):
            return parsed
        envelope = self.call_tool_envelope(
            parsed.status.tool_ref,
            {parsed.status.handle_argument: parsed.handle_id},
            context=context,
        )
        return self._normalize_async_status(envelope, parsed)

    def get_async_result(
        self,
        handle: AsyncToolHandleV1 | dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Fetch an async result, or use the terminal status payload as its result."""

        parsed = self._parse_async_handle(handle, context=context)
        if isinstance(parsed, ResultEnvelopeV1):
            return parsed
        if parsed.result is None or parsed.result == parsed.status:
            return self.get_async_status(parsed, context=context)
        envelope = self.call_tool_envelope(
            parsed.result.tool_ref,
            {parsed.result.handle_argument: parsed.handle_id},
            context=context,
        )
        return envelope.model_copy(update={"async_handle": parsed})

    def cancel_async(
        self,
        handle: AsyncToolHandleV1 | dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Cancel an async operation through its declared immutable endpoint."""

        parsed = self._parse_async_handle(handle, context=context)
        if isinstance(parsed, ResultEnvelopeV1):
            return parsed
        if parsed.cancel is None:
            return self._result_normalizer().error(
                tool_ref=parsed.submission_tool_ref,
                kind="admission",
                message="Async operation does not declare a cancel capability",
                retryable=False,
                context=context,
                details={"handle_id": parsed.handle_id},
            )
        envelope = self.call_tool_envelope(
            parsed.cancel.tool_ref,
            {parsed.cancel.handle_argument: parsed.handle_id},
            context=context,
        )
        if envelope.status == "error":
            return envelope.model_copy(update={"async_handle": parsed})
        return envelope.model_copy(
            update={"status": "cancelled", "async_handle": parsed}
        )

    def wait_for_async(
        self,
        handle: AsyncToolHandleV1 | dict,
        *,
        context: ToolCallContextV1 | None = None,
        timeout_seconds: float | None = None,
        cancel_on_timeout: bool = False,
    ) -> ResultEnvelopeV1:
        """Poll until terminal state, then retrieve the declared result."""

        parsed = self._parse_async_handle(handle, context=context)
        if isinstance(parsed, ResultEnvelopeV1):
            return parsed
        wait_budget = (
            float(parsed.max_wait_seconds)
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
        started = time.monotonic()
        while True:
            status = self.get_async_status(parsed, context=context)
            if status.status not in {"submitted", "running"}:
                if status.status == "ok" and parsed.result not in {
                    None,
                    parsed.status,
                }:
                    return self.get_async_result(parsed, context=context)
                return status
            elapsed = time.monotonic() - started
            if elapsed >= wait_budget:
                if cancel_on_timeout and parsed.cancel is not None:
                    self.cancel_async(parsed, context=context)
                return self._result_normalizer().error(
                    tool_ref=parsed.status.tool_ref,
                    kind="timeout",
                    message=(
                        f"Async operation {parsed.handle_id!r} did not reach a "
                        f"terminal state within {wait_budget:g} seconds"
                    ),
                    retryable=True,
                    context=context,
                    details={"handle_id": parsed.handle_id},
                )
            time.sleep(min(parsed.poll_interval_seconds, wait_budget - elapsed))

    def _registration_admission_error(
        self,
        *,
        requested: str,
        tool_name: str,
        tool_ref: str,
        skill_name: str | None,
        context: ToolCallContextV1,
        normalizer: ResultEnvelopeNormalizer,
        started_at: str,
        arguments: dict | None = None,
    ) -> ResultEnvelopeV1 | None:
        """Return a typed policy rejection, or ``None`` when dispatch is admitted."""

        message = ""
        if not skill_name:
            message = f"Tool '{requested}' not found. Available: {sorted(self._tool_registry)}"
        elif tool_name in self.disabled_tools or tool_ref in self.disabled_tools:
            message = f"Tool '{tool_name}' is disabled by run configuration"
        elif context.phase and not self._tool_admits_phase(tool_ref, context.phase):
            message = f"Tool '{tool_name}' is not admitted in phase '{context.phase}'"
        else:
            requirement = self._tool_context_requirement(tool_ref)
            if not context.satisfies(requirement):
                message = (
                    f"Tool '{tool_name}' requires explicit {requirement} context"
                )
        if not message and self._tool_authorization_view is not None:
            decision = self._tool_authorization_view.decide(
                tool_ref,
                phase=context.phase,
                context=context,
                # A composite binding authorizes one dispatch tool for one
                # reviewed leaf. Without the arguments the view can only see the
                # dispatch tool, and every leaf in the federated catalog would
                # ride in on the first leaf's authorization.
                arguments=arguments if arguments is not None else {},
            )
            if not decision.allowed:
                message = (
                    f"Tool '{tool_name}' denied by Capability Binding: "
                    f"{decision.reason_code}"
                )
        if not message:
            return None
        return normalizer.error(
            tool_ref=tool_ref,
            kind="admission",
            message=message,
            retryable=False,
            context=context,
            started_at=started_at,
            completed_at=utc_now_iso(),
        )

    def _invoke_registered_tool(
        self,
        *,
        tool_name: str,
        tool_ref: str,
        skill_name: str,
        args: dict,
        context: ToolCallContextV1,
        normalizer: ResultEnvelopeNormalizer,
        started_at: str,
    ) -> ResultEnvelopeV1:
        """Invoke an admitted registration and normalize transport outcomes."""

        log_tool_call(logger, tool_name, args)
        conn = self._connections.get(skill_name)
        if conn is None:
            skill = next((s for s in self.skills if s.name == skill_name), None)
            if skill is None:
                return normalizer.error(
                    tool_ref=tool_ref,
                    kind="admission",
                    message=f"Skill '{skill_name}' not found",
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            conn = self._init_connection(skill)

        skill = next((s for s in self.skills if s.name == skill_name), None)
        timeout_class = None
        timeout_budget = None
        if skill is not None:
            timeout_class = skill.tool_timeout_classes.get(tool_name)
            policy = skill.tool_policies.get(tool_name, {})
            if isinstance(policy, dict):
                timeout_budget = policy.get("timeout_budget")
        timeout = _resolve_tool_timeout(
            args,
            timeout_class=timeout_class,
            timeout_budget=timeout_budget,
        )
        requirement = self._tool_context_requirement(tool_ref)
        call_args = (
            conn.authorize_args(tool_name, args, context)
            if requirement != "none"
            else dict(args)
        )

        def _reconnect(failed_connection):
            failed_connection.close()
            self._connections.pop(skill_name, None)
            return self._init_connection(
                next(item for item in self.skills if item.name == skill_name)
            )

        envelope = invoke_with_retries(
            connection=conn,
            reconnect=_reconnect,
            tool_name=tool_name,
            tool_ref=tool_ref,
            args=call_args,
            timeout=timeout,
            context=context,
            normalizer=normalizer,
            started_at=started_at,
            logger=logger,
        )
        policy = self._tool_policy(tool_ref)
        lifecycle_raw = policy.get("async_lifecycle")
        if policy.get("timeout_class") != "async" or lifecycle_raw is None:
            return envelope
        return self._attach_async_handle(
            envelope,
            lifecycle=AsyncLifecycleV1.model_validate(lifecycle_raw),
            skill_name=skill_name,
            context=context,
        )

    def _attach_async_handle(
        self,
        envelope: ResultEnvelopeV1,
        *,
        lifecycle: AsyncLifecycleV1,
        skill_name: str,
        context: ToolCallContextV1,
    ) -> ResultEnvelopeV1:
        """Bind a successful provider submission to immutable lifecycle refs."""

        if envelope.status == "error":
            return envelope
        raw_handle = envelope.structured_content.get(lifecycle.handle_field)
        if raw_handle is None or not str(raw_handle).strip():
            return self._result_normalizer().error(
                tool_ref=envelope.provenance.tool_ref,
                kind="protocol",
                message=(
                    "Async submission omitted declared handle field "
                    f"{lifecycle.handle_field!r}"
                ),
                retryable=False,
                context=context,
                details={"handle_field": lifecycle.handle_field},
            )
        try:
            status = self._resolve_async_endpoint(skill_name, lifecycle.status)
            result = (
                self._resolve_async_endpoint(skill_name, lifecycle.result)
                if lifecycle.result is not None
                else None
            )
            cancel = (
                self._resolve_async_endpoint(skill_name, lifecycle.cancel)
                if lifecycle.cancel is not None
                else None
            )
        except ValueError as exc:
            return self._result_normalizer().error(
                tool_ref=envelope.provenance.tool_ref,
                kind="protocol",
                message=str(exc),
                retryable=False,
                context=context,
            )
        handle = AsyncToolHandleV1(
            handle_id=str(raw_handle),
            submission_tool_ref=envelope.provenance.tool_ref,
            status=status,
            result=result,
            cancel=cancel,
            state_field=lifecycle.state_field,
            states=lifecycle.states,
            poll_interval_seconds=lifecycle.poll_interval_seconds,
            max_wait_seconds=lifecycle.max_wait_seconds,
            submitted_at=envelope.provenance.completed_at or utc_now_iso(),
        )
        return envelope.model_copy(
            update={"status": "submitted", "async_handle": handle}
        )

    def _resolve_async_endpoint(
        self,
        skill_name: str,
        operation,
    ) -> AsyncToolEndpointV1:
        matches = [
            tool_ref
            for tool_ref, metadata in self._tool_metadata_by_ref.items()
            if self._tool_ref_registry.get(tool_ref) == skill_name
            and metadata.get("capability_ref") == operation.capability_ref
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Async capability {operation.capability_ref!r} resolved to "
                f"{len(matches)} runtime tools for Skill {skill_name!r}"
            )
        return AsyncToolEndpointV1(
            tool_ref=matches[0],
            handle_argument=operation.handle_argument,
        )

    def _parse_async_handle(
        self,
        handle: AsyncToolHandleV1 | dict,
        *,
        context: ToolCallContextV1 | None,
    ) -> AsyncToolHandleV1 | ResultEnvelopeV1:
        try:
            return AsyncToolHandleV1.model_validate(handle)
        except (TypeError, ValueError) as exc:
            return self._result_normalizer().error(
                tool_ref=_unresolved_tool_ref("async-handle"),
                kind="protocol",
                message=f"Invalid async handle: {exc}",
                retryable=False,
                context=context,
            )

    def _normalize_async_status(
        self,
        envelope: ResultEnvelopeV1,
        handle: AsyncToolHandleV1,
    ) -> ResultEnvelopeV1:
        if envelope.status == "error":
            return envelope.model_copy(update={"async_handle": handle})
        raw_state = envelope.structured_content.get(handle.state_field)
        state = handle.states.classify(raw_state)
        if state == "unknown":
            return envelope.model_copy(
                update={
                    "status": "error",
                    "async_handle": handle,
                    "error": ResultErrorV1(
                        kind="protocol",
                        message=(
                            "Async status response contains an undeclared state "
                            f"{raw_state!r} in field {handle.state_field!r}"
                        ),
                        retryable=True,
                        details={"provider_state": raw_state},
                    ),
                }
            )
        if state == "failed":
            structured = envelope.structured_content
            message = next(
                (
                    str(structured[key])
                    for key in ("message", "error", "stderr")
                    if structured.get(key)
                ),
                f"Async operation {handle.handle_id!r} failed",
            )
            return envelope.model_copy(
                update={
                    "status": "error",
                    "async_handle": handle,
                    "error": ResultErrorV1(
                        kind="tool", message=message, retryable=False
                    ),
                }
            )
        status = {
            "submitted": "submitted",
            "running": "running",
            "succeeded": "ok",
            "cancelled": "cancelled",
        }[state]
        return envelope.model_copy(update={"status": status, "async_handle": handle})

    def _tool_policy(self, tool_ref: str) -> dict:
        metadata = self._tool_metadata_by_ref.get(tool_ref, {})
        policy = metadata.get("policy")
        return policy if isinstance(policy, dict) else {}

    def _tool_admits_phase(self, tool_ref: str, phase: str) -> bool:
        skill_name = self._tool_ref_registry.get(tool_ref)
        skill = next((item for item in self.skills if item.name == skill_name), None)
        if skill is None or not _phase_matches(skill.phase, phase):
            return False
        metadata = self._tool_metadata_by_ref.get(tool_ref, {})
        policy = metadata.get("policy")
        tool_phases = (
            policy.get("phases", ["all"]) if isinstance(policy, dict) else ["all"]
        )
        return _phase_matches(tool_phases, phase)

    def _tool_context_requirement(self, tool_ref: str) -> str:
        policy = self._tool_policy(tool_ref)
        requirement = str(policy.get("context_requirement") or "none")
        return requirement if requirement in {"none", "run", "node"} else "none"

    def _artifact_store_for_call(self) -> ArtifactStore | None:
        if self._artifact_store is not None:
            return self._artifact_store
        checkpoint_dir = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
        if not checkpoint_dir:
            return None
        if (
            self._derived_artifact_store is None
            or self._derived_artifact_store[0] != checkpoint_dir
        ):
            from ari.artifact_store import CheckpointArtifactStore

            self._derived_artifact_store = (
                checkpoint_dir,
                CheckpointArtifactStore(checkpoint_dir),
            )
        return self._derived_artifact_store[1]

    def _result_normalizer(self) -> ResultEnvelopeNormalizer:
        return ResultEnvelopeNormalizer(
            self._artifact_store_for_call(),
            inline_limit=self._result_inline_limit,
        )

    @staticmethod
    def _default_call_context(node_id: str | None = None) -> ToolCallContextV1:
        return default_call_context(node_id)

    def close_all(self) -> None:
        """Close all connections."""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    def to_claude_mcp_config(
        self,
        phase: str | None = None,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> tuple[dict, list[str]]:
        """Render this registry for Claude CLI's native MCP interface."""

        if self._tools_cache is None:
            self._build_tools_cache()
        from ari.mcp.claude_bridge import build_claude_mcp_config

        return build_claude_mcp_config(
            skills=self.skills,
            connections=self._connections,
            visible_tools=self.list_tools(phase=phase, context=context),
            phase=phase,
            context=context,
        )
