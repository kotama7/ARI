"""Thread-safe pooled MCP stdio client with bounded retries and typed results."""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

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
from ari.result import (
    DEFAULT_INLINE_RESULT_LIMIT,
    ResultEnvelopeNormalizer,
    ResultEnvelopeV1,
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
        )
        if admission_error is not None:
            return admission_error
        assert skill_name is not None

        return self._invoke_registered_tool(
            tool_name=tool_name,
            tool_ref=tool_ref,
            skill_name=skill_name,
            args=args,
            context=effective_context,
            normalizer=normalizer,
            started_at=started_at,
        )

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
        if skill is not None:
            timeout_class = skill.tool_timeout_classes.get(tool_name)
        timeout = _resolve_tool_timeout(tool_name, args, timeout_class)
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

        return invoke_with_retries(
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
        metadata = self._tool_metadata_by_ref.get(tool_ref, {})
        policy = metadata.get("policy")
        if not isinstance(policy, dict):
            return "none"
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
