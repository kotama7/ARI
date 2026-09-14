"""Low-overhead runner: resident provider object, fresh SDK query per request.

The Python process (and this runner object) may live for the whole run, but
every request is a brand-new ``claude_agent_sdk.query()`` — ``resume`` /
``continue_conversation`` / session-id reuse are never used; there is
deliberately no API on this class that could accept a session id.

Differences vs the strict CLI runner, recorded in provenance:
- The SDK's subprocess transport inherits the parent process environment and
  only ADDS ``options.env`` on top, so the strict env allowlist cannot be
  enforced here; the memory/history suppression variables are still forced
  via ``options.env`` (fail-loud if the installed SDK has no ``env`` option).
- Session persistence is suppressed via ``extra_args`` (the SDK's escape
  hatch for CLI flags) → ``--no-session-persistence``; an SDK without
  ``extra_args`` fails loudly, because transcripts would otherwise be
  written under ``~/.claude/projects/`` on every call. A resolved sandbox
  HOME is applied through ``options.env["HOME"]``.
- The SDK is pointed at the same CLI binary strict mode uses (``cli_path``
  = resolved ``llm.claude_code.claude_bin``) so both modes run one Claude
  Code version; when the binary is not on PATH the SDK falls back to its
  bundled CLI. Provenance records ``sdk_version`` plus the options
  snapshot (including ``cli_path``) for this runner.
- Structured output uses the prompt transport only (schema embedded in the
  prompt, validated ARI-side); ``--json-schema`` is not wired through.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, Callable

from ari.llm.claude_code.cli_runner import RunnerOutcome
from ari.llm.claude_code.command import FORCED_ENV
from ari.llm.claude_code.policy import ClaudeCodePolicy, ClaudeCodePolicyError


class ClaudeCodeSdkUnavailableError(RuntimeError):
    """claude-agent-sdk is not importable in this environment."""

    def __init__(self, cause: str = "") -> None:
        super().__init__(
            "low_overhead mode requires the claude-agent-sdk Python package "
            "(pip install claude-agent-sdk). Either install it, switch "
            "llm.claude_code.mode to strict_reproducibility, or set "
            "llm.claude_code.sdk_fallback_to_cli: true to fall back "
            f"explicitly. {cause}".strip()
        )


#: ClaudeAgentOptions fields that carry the hermetic policy. If the installed
#: SDK version lacks any of these, we fail loudly instead of running with a
#: weaker isolation profile.
_POLICY_CRITICAL_OPTIONS = (
    "max_turns",
    "allowed_tools",
    "disallowed_tools",
    "permission_mode",
    "mcp_servers",
    "setting_sources",
    "env",
    # Needed to pass --no-session-persistence; without it every query would
    # persist a resumable transcript under the real HOME.
    "extra_args",
)

#: Options that must NEVER be set (session reuse / interactive continuation).
_FORBIDDEN_OPTIONS = ("resume", "continue_conversation", "fork_session")


class ClaudeSdkRunner:
    """Resident SDK worker; one fresh, stateless query() per request."""

    runner_name = "sdk"

    def __init__(
        self,
        policy: ClaudeCodePolicy,
        *,
        claude_bin: str = "claude",
        sdk_module: Any | None = None,
    ) -> None:
        self.policy = policy
        self.claude_bin = claude_bin
        if sdk_module is None:
            try:
                import claude_agent_sdk as sdk_module  # type: ignore
            except ImportError as e:
                raise ClaudeCodeSdkUnavailableError(str(e)) from e
        self._sdk = sdk_module
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            self._version = str(
                getattr(self._sdk, "__version__", "<unknown sdk version>")
            )
        return self._version

    def _build_options(
        self,
        *,
        model: str,
        system_text: str,
        cwd: str,
        home: str | None = None,
    ) -> Any:
        """Build ClaudeAgentOptions adaptively against the installed SDK.

        Wanted kwargs are filtered to the fields the SDK actually has;
        a missing policy-critical field is a hard error (never silently run
        with weaker isolation), and forbidden session-reuse fields are never
        set — asserted structurally below.
        """
        opts_cls = self._sdk.ClaudeAgentOptions
        if is_dataclass(opts_cls):
            available = {f.name for f in dataclass_fields(opts_cls)}
        else:  # pragma: no cover — future SDK shapes
            available = set(getattr(opts_cls, "__annotations__", {}))

        env = dict(FORCED_ENV)
        if home is not None:
            env["HOME"] = home
        wanted: dict[str, Any] = {
            "max_turns": self.policy.max_turns,
            "allowed_tools": list(self.policy.tools),
            "disallowed_tools": list(self.policy.disallowed_tools),
            "permission_mode": self.policy.permission_mode,
            "mcp_servers": {},
            "setting_sources": list(self.policy.setting_sources),
            "env": env,
            # extra_args value None => boolean CLI flag.
            "extra_args": (
                {"no-session-persistence": None}
                if self.policy.no_session_persistence
                else {}
            ),
            "system_prompt": system_text or None,
            "model": model or None,
            "cwd": cwd,
        }
        # Non-critical extras (filtered out on SDKs that lack the fields):
        if self.policy.strict_mcp_config:
            wanted["strict_mcp_config"] = True
        # Point the SDK at the same CLI binary strict mode uses (instead of
        # the SDK's bundled copy) so both modes run one Claude Code version;
        # visible in the provenance options snapshot as cli_path.
        import shutil as _shutil

        _cli = _shutil.which(self.claude_bin)
        if _cli:
            wanted["cli_path"] = _cli
        missing_critical = [
            k for k in _POLICY_CRITICAL_OPTIONS if k not in available
        ]
        if missing_critical:
            raise ClaudeCodePolicyError(
                "installed claude-agent-sdk "
                f"({self.version()}) lacks policy-critical options "
                f"{missing_critical}; refusing to run with weaker isolation. "
                "Upgrade claude-agent-sdk or use strict_reproducibility mode."
            )
        kwargs = {k: v for k, v in wanted.items() if k in available}
        assert not set(kwargs) & set(_FORBIDDEN_OPTIONS)
        return opts_cls(**kwargs)

    def run(
        self,
        *,
        prompt: str,
        model: str,
        timeout_sec: int,
        cwd: str,
        system_text: str = "",
        home: str | None = None,
        trace_cb: Callable[[dict], None] | None = None,
    ) -> RunnerOutcome:
        outcome = RunnerOutcome(
            runner=self.runner_name, runner_version=self.version()
        )
        options = self._build_options(
            model=model, system_text=system_text, cwd=cwd, home=home
        )
        outcome.options = _options_snapshot(options)

        async def _collect() -> None:
            async for event in self._sdk.query(prompt=prompt, options=options):
                record = _event_record(event)
                if trace_cb is not None:
                    try:
                        trace_cb(record)
                    except Exception:  # noqa: BLE001 — tracing must never
                        pass  # turn a successful response into a failure
                if record.get("event") == "ResultMessage":
                    _apply_result_message(event, outcome)

        import time as _time

        start = _time.monotonic()
        try:
            _run_coro_blocking(_collect(), timeout_sec)
        except asyncio.TimeoutError:
            outcome.error = f"claude SDK query timed out after {timeout_sec}s"
        except Exception as e:  # noqa: BLE001 — normalized; provider re-raises
            outcome.error = f"claude SDK query failed: {e}"
        outcome.duration_s = _time.monotonic() - start
        return outcome


def _options_snapshot(options: Any) -> dict:
    """Serialize ClaudeAgentOptions for command.json/provenance.json
    (best effort; only forced, non-secret env values are ever present).

    Reads fields shallowly via getattr — dataclasses.asdict deep-copies and
    raises on the real SDK's non-copyable defaults (e.g. debug_stderr =
    sys.stderr), which would degrade every snapshot to a repr string.
    """
    try:
        if is_dataclass(options) and not isinstance(options, type):
            raw = {
                f.name: getattr(options, f.name)
                for f in dataclass_fields(options)
            }
        else:  # pragma: no cover — future SDK shapes
            raw = dict(vars(options))
        return json.loads(json.dumps(raw, default=str))
    except Exception:  # noqa: BLE001 — snapshot must never break the call
        return {"repr": repr(options)}


def _apply_result_message(event: Any, outcome: RunnerOutcome) -> None:
    outcome.text = str(getattr(event, "result", None) or "")
    outcome.session_id = getattr(event, "session_id", None)
    outcome.num_turns = getattr(event, "num_turns", None)
    structured = getattr(event, "structured_output", None)
    if structured is not None:
        outcome.structured_output = structured
    u = getattr(event, "usage", None) or {}
    if u:
        prompt_tokens = (
            int(u.get("input_tokens", 0) or 0)
            + int(u.get("cache_creation_input_tokens", 0) or 0)
            + int(u.get("cache_read_input_tokens", 0) or 0)
        )
        completion_tokens = int(u.get("output_tokens", 0) or 0)
        outcome.usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    cost = getattr(event, "total_cost_usd", None)
    if cost is not None:
        try:
            outcome.cost_usd = float(cost)
        except (TypeError, ValueError):
            pass
    if getattr(event, "is_error", False):
        outcome.error = (
            f"claude SDK reported is_error: "
            f"{(outcome.text or getattr(event, 'subtype', ''))[:500]}"
        )


def _event_record(event: Any) -> dict:
    """Serialize one SDK event for trace.jsonl (best effort, never raises)."""
    record: dict[str, Any] = {"event": type(event).__name__}
    try:
        if is_dataclass(event) and not isinstance(event, type):
            import dataclasses

            record["data"] = json.loads(
                json.dumps(dataclasses.asdict(event), default=str)
            )
        elif hasattr(event, "__dict__"):
            record["data"] = json.loads(
                json.dumps(vars(event), default=str)
            )
        else:
            record["data"] = str(event)
    except Exception:  # noqa: BLE001 — trace must never break the call
        record["data"] = repr(event)
    return record


def _run_coro_blocking(coro: Any, timeout_sec: int) -> Any:
    """Run *coro* to completion from sync code, with a timeout.

    Uses asyncio.run when no loop is running; otherwise runs in a dedicated
    thread so a caller inside an event loop (e.g. the GUI) does not deadlock.
    Note this is still a SYNCHRONOUS bridge: the calling thread — and any
    event loop it drives — blocks for the duration of the query; async
    callers needing concurrency should call the provider from a worker
    thread of their own.
    """
    wrapped = asyncio.wait_for(coro, timeout_sec)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(wrapped)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, wrapped).result()
