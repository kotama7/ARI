"""`ari doctor` — environment health checks.

Currently one probe: ``ari doctor claude-code`` verifies the claude_code
LLM backend end-to-end WITHOUT touching the network unless ``--live`` is
given (a live run spends real tokens):

- claude binary found + ``claude --version``
- policy validation of the resolved config (fail-loud rules)
- the exact strict-mode command that would run (session-reuse flags asserted
  absent)
- flag support: known-hidden flags (--max-turns, --system-prompt-file) are
  NOT listed by ``claude --help``, so help-text absence alone is reported as
  informational; a real rejection can only be detected by --live.
- ``--live``: one hermetic dry-run call ("Return only this JSON: ...") with
  schema validation, provenance written to a temp dir and echoed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import typer
from rich.console import Console

doctor_app = typer.Typer(
    name="doctor", help="Environment health checks (`ari doctor claude-code`)."
)
_console = Console()

#: Flags build_strict_command emits that `claude --help` is known NOT to
#: list even when supported (verified on 2.1.198).
_HIDDEN_OK_FLAGS = ("--max-turns", "--system-prompt-file")


@doctor_app.command("claude-code")
def doctor_claude_code(
    live: bool = typer.Option(
        False,
        "--live",
        help="Run one real hermetic `claude -p` call (spends tokens).",
    ),
) -> None:
    """Check the claude_code backend: binary, policy, command, flags."""
    from ari.config import ClaudeCodeSettings
    from ari.llm.claude_code.cli_runner import ClaudeCliRunner
    from ari.llm.claude_code.policy import ClaudeCodePolicyError, validate_policy
    from ari.llm.claude_code.provider import ClaudeCodeProvider, policy_from_settings

    failures = 0

    # Resolve settings from the active config when loadable; else defaults.
    # Same resolution as `ari run`: package workflow.yaml, then auto_config.
    settings = ClaudeCodeSettings()
    model = "claude-sonnet-5"
    try:
        from ari.cli.run import _resolve_cfg

        cfg = _resolve_cfg(None)
        settings = cfg.llm.claude_code
        if (cfg.llm.backend or "").replace("-", "_") == "claude_code":
            model = cfg.llm.model
    except Exception as e:  # noqa: BLE001 — doctor keeps probing
        _console.print(f"[yellow]config not loaded ({e}); using defaults[/yellow]")

    # 1. Binary + version.
    bin_path = shutil.which(settings.claude_bin)
    if bin_path is None:
        _console.print(
            f"[red]✗ claude binary {settings.claude_bin!r} not on PATH[/red]"
        )
        raise typer.Exit(1)
    version = subprocess.run(
        [settings.claude_bin, "--version"], capture_output=True, text=True,
        timeout=60,
    ).stdout.strip()
    _console.print(f"[green]✓[/green] {bin_path} — {version}")

    # 2. Policy validation.
    try:
        policy = policy_from_settings(settings)
        validate_policy(policy)
        _console.print(
            f"[green]✓[/green] policy valid (mode={policy.mode}, "
            f"bare={policy.bare}"
            f"{' auto' if policy.bare_auto_resolved else ''})"
        )
    except ClaudeCodePolicyError as e:
        _console.print(f"[red]✗ policy rejected:[/red] {e}")
        raise typer.Exit(1) from None

    # 3. Command preview (session-reuse flags asserted absent inside).
    runner = ClaudeCliRunner(
        policy,
        claude_bin=settings.claude_bin,
        hermetic=settings.hermetic,
        env_allowlist_extra=tuple(settings.env_allowlist_extra),
        compat_drop_flags=tuple(settings.compat_drop_flags),
    )
    cmd = runner.build_command(
        model=model, system_prompt_file=None, schema_json=None
    )
    _console.print(f"[green]✓[/green] strict command: {' '.join(cmd.argv)}")
    if cmd.dropped_flags:
        _console.print(
            f"[yellow]! compat_drop_flags removed: {list(cmd.dropped_flags)}"
            "[/yellow]"
        )

    # 4. Static flag support report (help text; hidden flags are expected
    # to be absent — only --live proves rejection/acceptance).
    help_text = subprocess.run(
        [settings.claude_bin, "--help"], capture_output=True, text=True,
        timeout=60,
    ).stdout
    for flag in sorted({a for a in cmd.argv if a.startswith("--")}):
        if flag in help_text:
            _console.print(f"  [green]✓[/green] {flag} (listed in --help)")
        elif flag in _HIDDEN_OK_FLAGS:
            _console.print(
                f"  [cyan]•[/cyan] {flag} (hidden flag; known supported)"
            )
        else:
            _console.print(
                f"  [yellow]?[/yellow] {flag} not in --help — verify with "
                "--live"
            )

    # 5. Optional live dry-run with schema validation.
    if live:
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        provider = ClaudeCodeProvider(settings, model)
        try:
            obj, resp = provider.structured_complete(
                [{"role": "user", "content": 'Return only this JSON: {"ok": true}'}],
                schema,
                label="doctor",
            )
            _console.print(
                f"[green]✓[/green] live call ok: {json.dumps(obj)} "
                f"(usage={resp.usage}, provenance={resp.provenance_path})"
            )
        except Exception as e:  # noqa: BLE001 — report and fail
            _console.print(f"[red]✗ live call failed:[/red] {e}")
            failures += 1

    raise typer.Exit(1 if failures else 0)
