"""ClaudeCodeProvider — Claude Code behind ARI's LLM-API-compatible surface.

Exposes ``complete()`` / ``structured_complete()`` like every other ARI
backend; conversation history stays ARI-side (serialized to one prompt per
request), Claude Code session state is never reused, and both modes:

- ``strict_reproducibility`` — fresh ``claude -p`` subprocess per call
  (ClaudeCliRunner), hermetic env allowlist, throwaway cwd.
- ``low_overhead`` — resident Agent SDK worker (ClaudeSdkRunner), but every
  request is a fresh ``query()``; resume/continue is structurally impossible.

Every call is recorded under ``<checkpoint>/claude_code/<call_id>/`` (see
provenance.py) and booked to cost_trace.jsonl via ari.cost_tracker.

BFTS control, claim_evidence_hard_gate, metric recomputation, EAR generation
and reproducibility checks all stay in ARI: this provider returns text/JSON
and nothing else (no tools, no MCP, no memory, no sessions — policy.py).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ari.llm.claude_code.cli_runner import (
    ClaudeCliRunner,
    ClaudeCodeRunError,
    RunnerOutcome,
)
from ari.llm.claude_code.command import ClaudeCodeUnsupportedFlagError
from ari.llm.claude_code.policy import (
    MODE_LOW_OVERHEAD,
    MODE_STRICT,
    TRANSPORT_NATIVE,
    TRANSPORT_PROMPT,
    ClaudeCodePolicy,
    validate_policy,
)
from ari.llm.claude_code.provenance import (
    ProvenanceWriter,
    new_call_id,
    resolve_provenance_root,
    sha256_text,
)
from ari.llm.claude_code.sdk_runner import (
    ClaudeCodeSdkUnavailableError,
    ClaudeSdkRunner,
)
from ari.llm.claude_code.serializer import (
    SerializedPrompt,
    build_repair_prompt,
    serialize_messages,
)
from ari.llm.claude_code.validation import (
    ClaudeCodeSchemaError,
    extract_json,
    validate_against_schema,
)

if TYPE_CHECKING:  # pragma: no cover
    from ari.config import ClaudeCodeSettings, LLMConfig
    from ari.llm.client import LLMResponse

PROVIDER_NAME = "claude_code"


class ClaudeCodeToolsUnsupportedError(RuntimeError):
    """tools= was passed to the LLM-API-compatible claude_code backend."""

    def __init__(self) -> None:
        super().__init__(
            "backend=claude_code is an LLM-API-compatible provider and does "
            "not support OpenAI tool calling (ReAct agent phases need a "
            "tool-calling backend such as ollama/openai/cli-shim). Using "
            "Claude Code as an agent executor would be a separate backend "
            "(claude_code_agent_executor), which is intentionally not "
            "implemented here."
        )


def policy_from_settings(settings: "ClaudeCodeSettings") -> ClaudeCodePolicy:
    """Map config to a frozen policy, auto-resolving ``bare`` against auth.

    ``--bare`` restricts auth to ANTHROPIC_API_KEY/apiKeyHelper (OAuth
    credentials are never read). ``bare: null`` (default) therefore resolves
    to True only when a key/token env var is present; an explicit
    ``bare: true`` without one is honoured and will fail loudly at call time
    ("Not logged in") rather than silently weakening isolation.
    """
    import os

    bare = settings.bare
    bare_auto = False
    if bare is None:
        bare = bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        bare_auto = True
    return ClaudeCodePolicy(
        mode=settings.mode,
        max_turns=settings.max_turns,
        tools=tuple(settings.tools),
        disallowed_tools=tuple(settings.disallowed_tools),
        disable_auto_memory=settings.disable_auto_memory,
        disable_prompt_history=settings.disable_prompt_history,
        bare=bare,
        safe_mode=settings.safe_mode,
        strict_mcp_config=settings.strict_mcp_config,
        disable_slash_commands=settings.disable_slash_commands,
        no_chrome=settings.no_chrome,
        no_session_persistence=settings.no_session_persistence,
        permission_mode=settings.permission_mode,
        setting_sources=tuple(settings.setting_sources),
        allow_multi_turn=settings.allow_multi_turn,
        structured_output_transport=settings.structured_output_transport,
        bare_auto_resolved=bare_auto,
    )


class ClaudeCodeProvider:
    """LLM-API-compatible provider driving Claude Code (both modes)."""

    provider_name = PROVIDER_NAME

    def __init__(
        self,
        settings: "ClaudeCodeSettings",
        model: str,
        *,
        provenance_root: str | Path | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self._provenance_root = provenance_root
        self.policy = policy_from_settings(settings)
        validate_policy(self.policy)
        self._runner: ClaudeCliRunner | ClaudeSdkRunner | None = None
        self._sdk_fell_back_to_cli = False

    @classmethod
    def from_llm_config(cls, config: "LLMConfig") -> "ClaudeCodeProvider":
        from ari.config import ClaudeCodeSettings

        settings = getattr(config, "claude_code", None) or ClaudeCodeSettings()
        return cls(settings, config.model)

    # -- runner management -------------------------------------------------
    def _get_runner(self) -> ClaudeCliRunner | ClaudeSdkRunner:
        """Resident runner (low_overhead keeps the SDK worker object alive;
        strict mode's runner only caches the claude version probe)."""
        if self._runner is None:
            if self.policy.mode == MODE_LOW_OVERHEAD:
                try:
                    self._runner = ClaudeSdkRunner(
                        self.policy, claude_bin=self.settings.claude_bin
                    )
                except ClaudeCodeSdkUnavailableError:
                    if not self.settings.sdk_fallback_to_cli:
                        raise
                    self._sdk_fell_back_to_cli = True
                    self._runner = self._build_cli_runner()
            else:
                self._runner = self._build_cli_runner()
        return self._runner

    def _build_cli_runner(self) -> ClaudeCliRunner:
        return ClaudeCliRunner(
            self.policy,
            claude_bin=self.settings.claude_bin,
            hermetic=self.settings.hermetic,
            env_allowlist_extra=tuple(self.settings.env_allowlist_extra),
            compat_drop_flags=tuple(self.settings.compat_drop_flags),
        )

    # -- public API ---------------------------------------------------------
    def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        response_schema: dict | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_sec: int | None = None,
        *,
        node_id: str = "",
        phase: str = "",
        skill: str = "",
        label: str = "",
    ) -> "LLMResponse":
        """Serialize messages → run Claude Code once (plus at most one schema
        repair retry) → validate → return an :class:`ari.llm.client.LLMResponse`.

        ``temperature`` / ``max_tokens`` have no Claude Code CLI equivalent;
        they are recorded in provenance as ``unsupported_params`` instead of
        being silently honoured-looking.
        """
        obj, resp = self._complete_impl(
            messages,
            system=system,
            response_schema=response_schema,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            node_id=node_id,
            phase=phase,
            skill=skill,
            label=label,
        )
        del obj
        return resp

    def structured_complete(
        self,
        messages: list[dict],
        response_schema: dict,
        **kwargs: Any,
    ) -> tuple[Any, "LLMResponse"]:
        """complete() with a mandatory schema; returns (validated_obj, response)."""
        if response_schema is None:
            raise ValueError("structured_complete requires response_schema")
        return self._complete_impl(
            messages, response_schema=response_schema, **kwargs
        )

    # -- core ---------------------------------------------------------------
    def _complete_impl(
        self,
        messages: list[dict],
        system: str | None = None,
        response_schema: dict | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_sec: int | None = None,
        node_id: str = "",
        phase: str = "",
        skill: str = "",
        label: str = "",
    ) -> tuple[Any, "LLMResponse"]:
        runner = self._get_runner()
        use_model = model or self.model
        timeout = int(timeout_sec or self.settings.timeout_sec)
        native = (
            response_schema is not None
            and self.policy.structured_output_transport == TRANSPORT_NATIVE
            and runner.runner_name == "cli"
        )
        serialized = serialize_messages(
            messages,
            system=system,
            response_schema=response_schema,
            embed_schema_in_prompt=not native,
        )

        call_id = new_call_id(label or skill or phase or "call")
        root = resolve_provenance_root(self._provenance_root)
        # No pinned checkpoint → fall back to a temp dir. Artifacts are still
        # written (and the path returned) when record_provenance is on.
        ephemeral = not self.settings.record_provenance or root is None
        base_dir = (
            Path(tempfile.mkdtemp(prefix="ari-claude-code-"))
            if ephemeral
            else root
        )
        call_dir = Path(base_dir) / call_id
        writer = ProvenanceWriter(call_dir)
        keep_provenance = self.settings.record_provenance

        try:
            return self._run_attempts(
                runner=runner,
                writer=writer,
                call_dir=call_dir,
                serialized=serialized,
                messages=messages,
                response_schema=response_schema,
                native=native,
                use_model=use_model,
                timeout=timeout,
                temperature=temperature,
                max_tokens=max_tokens,
                node_id=node_id,
                phase=phase,
                skill=skill,
                keep_provenance=keep_provenance,
            )
        finally:
            if ephemeral and not self.settings.record_provenance:
                shutil.rmtree(call_dir, ignore_errors=True)
                if base_dir != root:
                    shutil.rmtree(base_dir, ignore_errors=True)

    def _run_attempts(
        self,
        *,
        runner: ClaudeCliRunner | ClaudeSdkRunner,
        writer: ProvenanceWriter,
        call_dir: Path,
        serialized: SerializedPrompt,
        messages: list[dict],
        response_schema: dict | None,
        native: bool,
        use_model: str,
        timeout: int,
        temperature: float | None,
        max_tokens: int | None,
        node_id: str,
        phase: str,
        skill: str,
        keep_provenance: bool,
    ) -> tuple[Any, "LLMResponse"]:
        provenance_path = str(call_dir) if keep_provenance else None
        max_attempts = 1 + (
            min(1, max(0, int(self.settings.schema_repair_retries)))
            if response_schema is not None
            else 0
        )
        home = self._resolve_home(writer)
        attempts_meta: list[dict] = []
        prompt = serialized.prompt
        outcome: RunnerOutcome | None = None
        validated: Any = None
        validation_errors: list[str] = []
        schema_valid: bool | None = None

        for attempt in range(1, max_attempts + 1):
            attempt_writer = (
                writer if attempt == 1 else ProvenanceWriter(writer.attempt_dir(attempt))
            )
            attempt_writer.write_input(
                messages=_normalize_messages(messages),
                prompt=prompt,
                system=serialized.system,
                schema_json=serialized.schema_json,
            )
            system_file = (
                str(attempt_writer.dir / "system.txt") if serialized.system else None
            )
            cwd = str(attempt_writer.cwd_dir())

            if runner.runner_name == "cli":
                attempt_writer.write_claude_version(runner.version())
                cmd = runner.build_command(
                    model=use_model,
                    system_prompt_file=system_file,
                    schema_json=serialized.schema_json if native else None,
                )
                attempt_writer.write_command(
                    argv=cmd.argv, cwd=cwd, runner="cli"
                )
                env_record = runner.env_record(home=home)
                attempt_writer.write_env_allowlist(env_record)
                outcome = runner.run(
                    prompt=prompt,
                    model=use_model,
                    timeout_sec=timeout,
                    cwd=cwd,
                    system_prompt_file=system_file,
                    schema_json=serialized.schema_json if native else None,
                    home=home,
                )
            else:
                attempt_writer.write_claude_version(runner.version())
                outcome = runner.run(
                    prompt=prompt,
                    model=use_model,
                    timeout_sec=timeout,
                    cwd=cwd,
                    system_text=serialized.system,
                    home=home,
                    trace_cb=attempt_writer.append_trace,
                )
                attempt_writer.write_command(
                    argv=(), cwd=cwd, runner="sdk", options=outcome.options
                )
                from ari.llm.claude_code.command import FORCED_ENV

                env_record = {
                    "<mode>": "sdk (inherits parent env + forced vars)",
                    **{k: f"<forced:{v}>" for k, v in FORCED_ENV.items()},
                }
                if home is not None:
                    env_record["HOME"] = "<overridden:sandbox>"
                attempt_writer.write_env_allowlist(env_record)

            attempt_writer.write_output(
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                returncode=outcome.returncode,
            )
            attempts_meta.append(
                {
                    "attempt": attempt,
                    "dir": str(attempt_writer.dir),
                    "cwd": cwd,
                    "returncode": outcome.returncode,
                    "duration_s": round(outcome.duration_s, 3),
                    "session_id": outcome.session_id,
                    "usage": outcome.usage,
                    "cost_usd": outcome.cost_usd,
                    "error": outcome.error,
                }
            )
            # Book EVERY attempt that reports usage or cost — repair retries
            # and billed error outcomes included — not just the last one.
            if outcome.usage or outcome.cost_usd is not None:
                self._record_cost(
                    outcome, use_model, node_id=node_id, phase=phase, skill=skill
                )

            if outcome.unknown_option:
                self._finalize(
                    writer, outcome, use_model, temperature, max_tokens,
                    attempts_meta, schema_used=response_schema is not None,
                    valid=None, native=native, errors=[outcome.error or ""],
                    env_record=env_record, cwd=cwd,
                )
                raise ClaudeCodeUnsupportedFlagError(
                    outcome.unknown_option, outcome.stderr
                )
            if outcome.error:
                self._finalize(
                    writer, outcome, use_model, temperature, max_tokens,
                    attempts_meta, schema_used=response_schema is not None,
                    valid=None, native=native, errors=[outcome.error],
                    env_record=env_record, cwd=cwd,
                )
                raise ClaudeCodeRunError(
                    outcome.error
                    + (f" (provenance: {provenance_path})" if provenance_path else "")
                )

            if response_schema is None:
                schema_valid = None
                break

            # Schema path: parse + ARI-side validation (native output is
            # re-validated too; Claude-side validation is never trusted alone).
            try:
                candidate = (
                    outcome.structured_output
                    if native and outcome.structured_output is not None
                    else extract_json(outcome.text)
                )
                validation_errors = validate_against_schema(
                    candidate, response_schema
                )
            except ValueError as e:
                validation_errors = [str(e)]
                candidate = None
            if not validation_errors:
                validated = candidate
                schema_valid = True
                break
            schema_valid = False
            if attempt < max_attempts:
                # Show the model exactly the payload that failed validation:
                # for the native transport that is the structured_output
                # object, not the (possibly prose) result text.
                if native and outcome.structured_output is not None:
                    invalid_payload = json.dumps(
                        outcome.structured_output, ensure_ascii=False
                    )
                else:
                    invalid_payload = outcome.text
                prompt = build_repair_prompt(
                    serialized, invalid_payload, validation_errors
                )

        assert outcome is not None
        self._finalize(
            writer, outcome, use_model, temperature, max_tokens, attempts_meta,
            schema_used=response_schema is not None,
            valid=schema_valid, native=native, errors=validation_errors,
            env_record=env_record, cwd=cwd,
        )
        if response_schema is not None and not schema_valid:
            raise ClaudeCodeSchemaError(validation_errors, provenance_path)

        content = outcome.text
        if response_schema is not None and schema_valid:
            # Guarantee parseable content for downstream regex/json parsers
            # (schema_valid, not validated-is-not-None: a schema may accept
            # JSON null / false / 0, which are legitimate validated values).
            content = json.dumps(validated, ensure_ascii=False)

        from ari.llm.client import LLMResponse

        resp = LLMResponse(
            content=content,
            tool_calls=None,
            usage=outcome.usage,
            provider=PROVIDER_NAME,
            model=use_model,
            provenance_path=provenance_path,
            raw=outcome.envelope,
        )
        return validated, resp

    # -- helpers --------------------------------------------------------------
    def _resolve_home(self, writer: ProvenanceWriter) -> str | None:
        """Sandbox HOME when auth allows it (see docs: strict mode HOME policy).

        - ``home_mode: sandbox`` — always sandbox; requires key/token auth
          (fail-loud otherwise: OAuth credentials live under the real HOME).
        - ``home_mode: auto`` — sandbox only when the policy resolved to
          ``--bare`` (key auth present); otherwise keep the real HOME.
        - ``home_mode: real`` — never sandbox.
        """
        import os

        mode = self.settings.home_mode
        key_auth = bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        if mode == "real":
            return None
        if mode == "sandbox" and not key_auth:
            raise ClaudeCodeRunError(
                "llm.claude_code.home_mode=sandbox requires ANTHROPIC_API_KEY/"
                "ANTHROPIC_AUTH_TOKEN (OAuth credentials live in the real "
                "HOME and would break). Set home_mode: real or provide a key."
            )
        if mode == "auto" and not (self.policy.bare and key_auth):
            return None
        home = writer.dir / "home"
        home.mkdir(parents=True, exist_ok=True)
        return str(home)

    def _finalize(
        self,
        writer: ProvenanceWriter,
        outcome: RunnerOutcome,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        attempts_meta: list[dict],
        *,
        schema_used: bool,
        valid: bool | None,
        native: bool,
        errors: list[str],
        env_record: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        validation = {
            "schema_used": schema_used,
            "valid": valid,
            "transport": (
                (TRANSPORT_NATIVE if native else TRANSPORT_PROMPT)
                if schema_used
                else None
            ),
            "errors": errors,
        }
        writer.write_validation(validation)
        writer.write_result(
            {
                "text": outcome.text,
                "structured_output": outcome.structured_output,
                "session_id": outcome.session_id,
                "num_turns": outcome.num_turns,
                "usage": outcome.usage,
                "cost_usd": outcome.cost_usd,
                "text_sha256": sha256_text(outcome.text or ""),
            }
        )
        unsupported = {}
        if temperature is not None:
            unsupported["temperature"] = temperature
        if max_tokens is not None:
            unsupported["max_tokens"] = max_tokens
        writer.write_provenance(
            {
                "provider": PROVIDER_NAME,
                "mode": self.policy.mode,
                "model": model,
                "claude_version": (
                    outcome.runner_version if outcome.runner == "cli" else None
                ),
                "sdk_version": (
                    outcome.runner_version if outcome.runner == "sdk" else None
                ),
                "sdk_fell_back_to_cli": self._sdk_fell_back_to_cli,
                "command": list(outcome.argv),
                "options": outcome.options,
                "cwd": cwd or str(writer.dir / "cwd"),
                "env_allowlist": env_record or {},
                "policy": {
                    "auto_memory_disabled": self.policy.disable_auto_memory,
                    "prompt_history_disabled": self.policy.disable_prompt_history,
                    "tools": list(self.policy.tools),
                    "disallowed_tools": list(self.policy.disallowed_tools),
                    "mcp_disabled": self.policy.strict_mcp_config
                    and not self.policy.mcp_servers,
                    "safe_mode": self.policy.safe_mode,
                    "bare": self.policy.bare,
                    "bare_auto_resolved": self.policy.bare_auto_resolved,
                    "session_persistence": not self.policy.no_session_persistence,
                    "resume_used": False,
                    "permission_mode": self.policy.permission_mode,
                    "max_turns": self.policy.max_turns,
                    "setting_sources": list(self.policy.setting_sources),
                    "hermetic_env": (
                        self.settings.hermetic if outcome.runner == "cli" else False
                    ),
                    "home_mode": self.settings.home_mode,
                    "structured_output_transport": (
                        self.policy.structured_output_transport
                    ),
                },
                "unsupported_params": unsupported,
                "unsupported_flags": list(outcome.dropped_flags)
                + ([outcome.unknown_option] if outcome.unknown_option else []),
                "session_id": outcome.session_id,
                "return_code": outcome.returncode,
                "duration_s": round(outcome.duration_s, 3),
                "attempts": attempts_meta,
                "validation": validation,
            }
        )

    def _record_cost(
        self,
        outcome: RunnerOutcome,
        model: str,
        *,
        node_id: str,
        phase: str,
        skill: str,
    ) -> None:
        """Book the call to cost_trace.jsonl. claude_code bypasses litellm,
        so the global litellm success-callback never sees it — record
        directly, with Claude's authoritative total_cost_usd."""
        try:
            from ari import cost_tracker

            # Same bootstrap as MCP skills: when the process-global tracker
            # is not initialised yet (standalone provider use), pin it to
            # $ARI_CHECKPOINT_DIR so the call is still booked.
            if cost_tracker.get() is None:
                cost_tracker.init_from_env()
            u = outcome.usage or {}
            cost_tracker.record(
                model=model,
                prompt_tokens=int(u.get("prompt_tokens", 0)),
                completion_tokens=int(u.get("completion_tokens", 0)),
                node_id=node_id,
                phase=phase,
                skill=skill,
                backend=PROVIDER_NAME,
                cost_usd=outcome.cost_usd,
                latency_ms=outcome.duration_s * 1000.0,
            )
        except Exception:  # noqa: BLE001 — cost booking must never fail a call
            pass


def _normalize_messages(messages: list) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
        else:
            out.append(
                {
                    "role": getattr(m, "role", None),
                    "content": getattr(m, "content", None),
                }
            )
    return out
