"""Strict-reproducibility runner: one fresh ``claude -p`` subprocess per call.

No state survives between requests: fresh process, throwaway cwd, allowlisted
environment, ``--no-session-persistence``. The runner never raises on a
completed subprocess — it returns a :class:`RunnerOutcome` (including error
cases) so the provider can persist provenance BEFORE deciding to raise.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from ari.llm.claude_code.command import (
    ClaudeCommand,
    build_strict_command,
    build_subprocess_env,
    parse_unknown_option,
)
from ari.llm.claude_code.policy import ClaudeCodePolicy


class ClaudeCodeRunError(RuntimeError):
    """A claude_code call failed (spawn error, timeout, or is_error result)."""


@dataclass
class RunnerOutcome:
    """Normalized result of one Claude Code invocation (CLI or SDK)."""

    text: str = ""
    structured_output: Any | None = None
    envelope: dict | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_s: float = 0.0
    argv: tuple[str, ...] = ()
    options: dict = field(default_factory=dict)
    session_id: str | None = None
    usage: dict | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    dropped_flags: tuple[str, ...] = ()
    runner: str = "cli"
    runner_version: str = ""
    #: Human-readable failure ("timeout after 300s", "is_error: ...", ...);
    #: None on success. The provider raises after recording provenance.
    error: str | None = None
    #: Flag Claude Code rejected with "unknown option" (version drift).
    unknown_option: str | None = None


def parse_result_envelope(stdout: str, outcome: RunnerOutcome) -> None:
    """Parse ``--output-format json``'s single result object into *outcome*.

    Envelope keys (verified on 2.1.198): type, subtype, is_error, result,
    structured_output (with --json-schema), session_id, num_turns, usage
    {input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
    output_tokens}, total_cost_usd.
    """
    try:
        env = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        if outcome.error is None:
            outcome.error = (
                f"claude stdout is not JSON (rc={outcome.returncode}): "
                f"{stdout.strip()[:300]!r}"
            )
        return
    if not isinstance(env, dict):
        outcome.error = f"claude stdout is not a JSON object: {stdout[:200]!r}"
        return
    outcome.envelope = env
    outcome.text = str(env.get("result") or "")
    outcome.structured_output = env.get("structured_output")
    outcome.session_id = env.get("session_id")
    outcome.num_turns = env.get("num_turns")
    u = env.get("usage") or {}
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
    if env.get("total_cost_usd") is not None:
        try:
            outcome.cost_usd = float(env["total_cost_usd"])
        except (TypeError, ValueError):
            pass
    if env.get("is_error"):
        detail = outcome.text or env.get("subtype") or "unknown error"
        errs = env.get("errors")
        if errs:
            detail = f"{detail} ({errs})"
        outcome.error = f"claude reported is_error: {detail[:500]}"


class ClaudeCliRunner:
    """Spawns one fresh ``claude -p`` per request (strict_reproducibility)."""

    runner_name = "cli"

    def __init__(
        self,
        policy: ClaudeCodePolicy,
        *,
        claude_bin: str = "claude",
        hermetic: bool = True,
        env_allowlist_extra: tuple[str, ...] = (),
        compat_drop_flags: tuple[str, ...] = (),
    ) -> None:
        self.policy = policy
        self.claude_bin = claude_bin
        self.hermetic = hermetic
        self.env_allowlist_extra = tuple(env_allowlist_extra)
        self.compat_drop_flags = tuple(compat_drop_flags)
        self._version: str | None = None

    def version(self) -> str:
        """``claude --version`` output, cached per runner instance."""
        if self._version is None:
            try:
                proc = subprocess.run(
                    [self.claude_bin, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self._version = (proc.stdout or proc.stderr).strip()
            except FileNotFoundError:
                raise ClaudeCodeRunError(
                    f"Claude Code binary {self.claude_bin!r} not found on "
                    "PATH; install Claude Code or set llm.claude_code.claude_bin"
                ) from None
            except subprocess.TimeoutExpired:
                self._version = "<version probe timed out>"
        return self._version

    def build_command(
        self,
        *,
        model: str,
        system_prompt_file: str | None,
        schema_json: str | None,
    ) -> ClaudeCommand:
        return build_strict_command(
            self.policy,
            model=model,
            claude_bin=self.claude_bin,
            system_prompt_file=system_prompt_file,
            schema_json=schema_json,
            compat_drop_flags=self.compat_drop_flags,
        )

    def run(
        self,
        *,
        prompt: str,
        model: str,
        timeout_sec: int,
        cwd: str,
        system_prompt_file: str | None = None,
        schema_json: str | None = None,
        home: str | None = None,
    ) -> RunnerOutcome:
        cmd = self.build_command(
            model=model,
            system_prompt_file=system_prompt_file,
            schema_json=schema_json,
        )
        env, _record = build_subprocess_env(
            hermetic=self.hermetic,
            home=home,
            env_allowlist_extra=self.env_allowlist_extra,
        )
        outcome = RunnerOutcome(
            argv=cmd.argv,
            dropped_flags=cmd.dropped_flags,
            runner=self.runner_name,
            runner_version=self.version(),
        )
        start = time.monotonic()
        try:
            proc = subprocess.run(
                list(cmd.argv),
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=cwd,
                env=env,
            )
            outcome.stdout = proc.stdout or ""
            outcome.stderr = proc.stderr or ""
            outcome.returncode = proc.returncode
        except subprocess.TimeoutExpired as e:
            outcome.returncode = -1
            outcome.stdout = _as_text(e.stdout)
            outcome.stderr = _as_text(e.stderr)
            outcome.error = f"claude timed out after {timeout_sec}s"
            outcome.duration_s = time.monotonic() - start
            return outcome
        except FileNotFoundError:
            raise ClaudeCodeRunError(
                f"Claude Code binary {self.claude_bin!r} not found on PATH"
            ) from None
        outcome.duration_s = time.monotonic() - start

        if outcome.returncode != 0:
            flag = parse_unknown_option(outcome.stderr)
            if flag:
                outcome.unknown_option = flag
                outcome.error = (
                    f"claude {outcome.runner_version} rejected flag {flag!r}"
                )
                return outcome
            outcome.error = (
                f"claude exited rc={outcome.returncode}: "
                f"{(outcome.stderr or outcome.stdout).strip()[:500]}"
            )
        parse_result_envelope(outcome.stdout, outcome)
        return outcome

    def env_record(self, *, home: str | None) -> dict[str, str]:
        """The env allowlist record for provenance (names/markers only)."""
        _env, record = build_subprocess_env(
            hermetic=self.hermetic,
            home=home,
            env_allowlist_extra=self.env_allowlist_extra,
        )
        return record


def _as_text(v: str | bytes | None) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v
