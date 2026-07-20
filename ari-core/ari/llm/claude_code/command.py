"""Claude Code CLI command + environment construction (strict mode).

Builds the exact ``claude -p`` argv for one hermetic request and the
allowlisted environment it runs under. Verified against Claude Code 2.1.198:

- ``--max-turns`` and ``--system-prompt-file`` are real flags even though
  ``claude --help`` does not list them (probed: unknown flags fail with
  ``error: unknown option '--x'`` and rc=1, these do not).
- ``--json-schema`` delivers structured output through a ``StructuredOutput``
  TOOL call. ``--permission-mode plan`` denies that call and the round-trip
  costs one extra turn, so the native schema profile switches to
  ``--permission-mode default`` + ``--allowedTools StructuredOutput`` +
  ``--max-turns >= 2`` while ``--tools ""`` keeps every other tool disabled.
- ``--bare`` restricts auth to ANTHROPIC_API_KEY / apiKeyHelper (OAuth
  credentials are never read), so ``bare`` is auto-resolved against key
  presence unless the config pins it (see provider.py).

If Claude Code rejects a flag this module built (version drift), the runner
raises :class:`ClaudeCodeUnsupportedFlagError` — fail-loud — unless the flag
is listed in ``compat_drop_flags``, in which case it is removed and recorded
in provenance as ``unsupported_flags``. Isolation is never weakened silently.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ari.llm.claude_code.policy import ClaudeCodePolicy, effective_max_turns

#: Session-reuse flags that must never appear in a built command. Checked by
#: assert_no_session_reuse() on every build as a structural guarantee.
FORBIDDEN_FLAGS = (
    "--resume",
    "-r",
    "--continue",
    "-c",
    "--session-id",
    "--fork-session",
    "--from-pr",
)

#: Environment variables forced onto every subprocess (memory / history /
#: non-essential traffic suppression). Values are literal and recorded in
#: env_allowlist.json.
FORCED_ENV = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    # Suppresses auto-update and other background traffic that could change
    # the binary mid-run.
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}

#: Default hermetic env allowlist: process basics, locale, auth, and network
#: egress (proxies/CA bundles matter on HPC clusters). Everything else —
#: including CLAUDECODE / CLAUDE_CODE_SESSION_ID etc. from a parent Claude
#: session — is dropped. Extendable via llm.claude_code.env_allowlist_extra.
DEFAULT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "SHELL",
    "TERM",
    "USER",
    "LOGNAME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CONFIG_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
)

_UNKNOWN_OPTION_RE = re.compile(r"error: unknown option '(?P<flag>--?[A-Za-z0-9-]+)'")


class ClaudeCodeUnsupportedFlagError(RuntimeError):
    """The installed Claude Code rejected a policy-bearing flag.

    Isolation flags are never dropped silently; either upgrade Claude Code
    or explicitly list the flag in ``llm.claude_code.compat_drop_flags``
    (it is then recorded in provenance as ``unsupported_flags``).
    """

    def __init__(self, flag: str, stderr: str) -> None:
        self.flag = flag
        super().__init__(
            f"Claude Code rejected {flag!r} (version drift?). Refusing to "
            "weaken isolation silently. Upgrade Claude Code, or add the flag "
            "to llm.claude_code.compat_drop_flags to drop it explicitly "
            f"(recorded in provenance). stderr: {stderr.strip()[:500]}"
        )


@dataclass(frozen=True)
class ClaudeCommand:
    """One fully-built strict-mode invocation (prompt travels on stdin)."""

    argv: tuple[str, ...]
    #: Flags removed via compat_drop_flags, for provenance.
    dropped_flags: tuple[str, ...] = field(default_factory=tuple)
    #: True when the native --json-schema profile was applied.
    native_schema: bool = False


def parse_unknown_option(stderr: str) -> str | None:
    """Extract the flag name from a Claude Code unknown-option error."""
    m = _UNKNOWN_OPTION_RE.search(stderr or "")
    return m.group("flag") if m else None


def build_strict_command(
    policy: ClaudeCodePolicy,
    *,
    model: str,
    claude_bin: str = "claude",
    system_prompt_file: str | None = None,
    schema_json: str | None = None,
    output_format: str = "json",
    compat_drop_flags: tuple[str, ...] = (),
) -> ClaudeCommand:
    """Build the strict-reproducibility ``claude -p`` argv for one request.

    The prompt is fed on STDIN (same as the cli-shim; avoids argv limits),
    so ``-p`` takes no positional argument. ``schema_json`` is only passed
    when the policy selects the native transport.
    """
    native = bool(schema_json) and policy.structured_output_transport == "native"

    argv: list[str] = [claude_bin, "-p", "--output-format", output_format]
    argv += ["--max-turns", str(effective_max_turns(policy, native_schema_call=native))]
    if model:
        argv += ["--model", model]
    if system_prompt_file:
        argv += ["--system-prompt-file", system_prompt_file]

    if policy.bare:
        argv.append("--bare")
    if policy.safe_mode:
        argv.append("--safe-mode")
    if policy.strict_mcp_config:
        argv.append("--strict-mcp-config")
    if policy.disable_slash_commands:
        argv.append("--disable-slash-commands")
    if policy.no_chrome:
        argv.append("--no-chrome")
    if policy.no_session_persistence:
        argv.append("--no-session-persistence")
    # ALWAYS emitted, even (especially) when empty: with the flag omitted the
    # CLI loads user/project/local settings by default, and --safe-mode does
    # NOT stop settings env/auth overrides from applying (verified by A/B on
    # 2.1.198: a cwd .claude/settings.json env poisoning took effect without
    # the flag and was ignored with --setting-sources ""). An explicit empty
    # value means "no settings files".
    argv += ["--setting-sources", ",".join(policy.setting_sources)]

    # Tool surface. --tools "" disables every built-in tool; the deny-all
    # --disallowedTools "*" is belt-and-braces on top. The native schema
    # profile must NOT deny-all (StructuredOutput would be blocked); there
    # --tools "" still leaves no other tool available.
    argv += ["--tools", ""]
    if native:
        argv += ["--allowedTools", "StructuredOutput"]
        argv += ["--permission-mode", "default"]
        argv += ["--json-schema", schema_json or ""]
    else:
        argv += ["--disallowedTools", "*"]
        argv += ["--permission-mode", policy.permission_mode]

    dropped: list[str] = []
    if compat_drop_flags:
        drop = set(compat_drop_flags)
        pruned: list[str] = []
        skip_value = False
        for i, tok in enumerate(argv):
            if skip_value:
                skip_value = False
                continue
            if tok in drop:
                dropped.append(tok)
                # Drop the flag's value too when the next token is not a flag
                # and not the binary/prompt position.
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    skip_value = True
                continue
            pruned.append(tok)
        argv = pruned

    cmd = ClaudeCommand(
        argv=tuple(argv), dropped_flags=tuple(dropped), native_schema=native
    )
    assert_no_session_reuse(cmd.argv)
    return cmd


def assert_no_session_reuse(argv: tuple[str, ...]) -> None:
    """Structural guarantee: no session-resume flag ever reaches Claude Code."""
    bad = [f for f in argv if f in FORBIDDEN_FLAGS]
    if bad:
        raise AssertionError(
            f"session-reuse flags {bad} in claude_code command — this is a "
            "bug; LLM API mode must never resume sessions"
        )


def build_subprocess_env(
    *,
    hermetic: bool,
    home: str | None,
    env_allowlist_extra: tuple[str, ...] = (),
    base_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build the subprocess environment and its provenance record.

    Returns ``(env, allowlist_record)`` where the record maps each variable
    name to ``"<inherited>"`` / a literal forced value / ``"<overridden>"``
    (secrets are never written to provenance — names only).

    ``hermetic=True``: start from the allowlist (default + extras) applied to
    ``base_env`` (defaults to ``os.environ``), then apply FORCED_ENV.
    ``hermetic=False``: inherit everything EXCEPT ``CLAUDECODE``/
    ``CLAUDE_CODE_*`` parent-session variables, then apply FORCED_ENV.
    """
    source = dict(base_env if base_env is not None else os.environ)
    record: dict[str, str] = {}

    if hermetic:
        allow = list(DEFAULT_ENV_ALLOWLIST) + [
            v for v in env_allowlist_extra if v not in DEFAULT_ENV_ALLOWLIST
        ]
        env = {k: source[k] for k in allow if k in source}
        for k in env:
            record[k] = "<inherited>"
    else:
        env = {
            k: v
            for k, v in source.items()
            if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
        }
        record["<mode>"] = "non-hermetic (full inherit minus CLAUDE_CODE_*)"

    for k, v in FORCED_ENV.items():
        env[k] = v
        record[k] = f"<forced:{v}>"

    if home is not None:
        env["HOME"] = home
        record["HOME"] = "<overridden:sandbox>"

    return env, record
