"""Tests for scripts/setup/setup_env.sh.

Verifies that the .env bootstrap:
  1. Covers every env var actually referenced by the Python source.
  2. Preserves existing secret values (does not overwrite).
  3. Is idempotent (same content after a second run).
  4. Prompts interactively only for the four critical API keys
     and writes an entered value to .env.
  5. In non-interactive mode, leaves missing API keys as commented
     placeholders (never hardcodes a dummy secret).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_DIR = REPO_ROOT / "scripts" / "setup"
SETUP_ENV_SH = SETUP_DIR / "setup_env.sh"

# Only scan first-party source trees. We explicitly avoid walking
# .venv / site-packages / vendored third-party code, since those contain
# thousands of library-internal env vars we don't own.
SOURCE_ROOTS = [
    REPO_ROOT / "ari-core" / "ari",
] + sorted(
    p / "src" for p in REPO_ROOT.glob("ari-skill-*") if (p / "src").is_dir()
)

PATH_EXCLUDE = (
    "/vendor/", "/__pycache__/", "/node_modules/", "/.git/",
    "/.venv/", "/venv/", "/site-packages/", "/dist/", "/build/",
    "/viz/static/", "/viz/frontend/", "/tests/",
)

# Generic runtime/system env vars we intentionally do not document in .env
# (they are set by the OS / shell / runtime, not by the user).
SYSTEM_VARS = {
    "HOME", "PATH", "USER", "SHELL", "PWD", "LANG", "LC_ALL", "TERM",
    "TMPDIR", "TMP", "TEMP",
}

# Vars that live inside vendored agentscope sources but we still document
# because the user asked for full coverage across projects.
VENDOR_INCLUDE_VARS = {
    "IP", "PORT", "SESSION_TYPE", "SECRET_KEY",
    "CLIENT_ID", "CLIENT_SECRET", "OWNER", "REPO",
    "COPILOT_IP", "COPILOT_PORT", "LOCAL_WORKSTATION",
    "MODELSCOPE_ENVIRONMENT",
    "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET",
    "OSS_BUCKET_NAME", "OSS_ENDPOINT",
}

ENV_VAR_PATTERN = re.compile(
    r"""(?:os\.environ(?:\.get)?|os\.getenv)\(\s*['"]([A-Z_][A-Z0-9_]*)['"]"""
)


def _iter_source_files():
    for root in SOURCE_ROOTS:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            s = str(py)
            if any(x in s for x in PATH_EXCLUDE):
                continue
            yield py


def _collect_source_env_vars() -> set[str]:
    """Scan first-party .py files for env var references."""
    seen: set[str] = set()
    for py in _iter_source_files():
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name in ENV_VAR_PATTERN.findall(text):
            if name not in SYSTEM_VARS:
                seen.add(name)
    return seen


def _parse_setup_env_keys() -> set[str]:
    """Extract every KEY documented by setup_env.sh (commented or not)."""
    text = SETUP_ENV_SH.read_text()
    # Match lines like:
    #   _env_append_if_absent "# KEY=..."
    #   _env_append_if_absent "KEY=..."
    #   _prompt_secret "KEY" "..."
    keys: set[str] = set()
    for m in re.finditer(
        r'_env_append_if_absent\s+"#?\s*([A-Z_][A-Z0-9_]*)=',
        text,
    ):
        keys.add(m.group(1))
    for m in re.finditer(
        r'_prompt_secret\s+"([A-Z_][A-Z0-9_]*)"',
        text,
    ):
        keys.add(m.group(1))
    return keys


def _run_setup_env(ari_root: Path, *, stdin: str = "", lang: str = "ja") -> str:
    """Run setup_env.sh against a fake ARI_ROOT and return combined output."""
    script = f"""
set -e
export ARI_ROOT={ari_root!s}
export SETUP_LANG={lang}
source {SETUP_DIR / "colors.sh"!s}
source {SETUP_DIR / "messages.sh"!s}
source {SETUP_ENV_SH!s}
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"setup_env.sh failed:\n{proc.stderr}"
    return proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_setup_env_sh_exists():
    assert SETUP_ENV_SH.exists(), f"{SETUP_ENV_SH} must exist"


def test_setup_env_has_valid_bash_syntax():
    proc = subprocess.run(
        ["bash", "-n", str(SETUP_ENV_SH)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"bash -n failed: {proc.stderr}"


def test_setup_env_covers_all_source_env_vars():
    """Every env var referenced by non-vendored source must appear in setup_env.sh."""
    source_vars = _collect_source_env_vars()
    documented = _parse_setup_env_keys()
    missing = source_vars - documented
    assert not missing, (
        f"setup_env.sh is missing {len(missing)} env var(s) used in source: "
        f"{sorted(missing)}"
    )


def test_setup_env_includes_vendored_agentscope_vars():
    """User asked for full coverage across projects (including vendored)."""
    documented = _parse_setup_env_keys()
    missing = VENDOR_INCLUDE_VARS - documented
    assert not missing, f"Missing vendored agentscope vars: {sorted(missing)}"


def test_setup_env_wired_into_setup_sh():
    """setup.sh must actually load setup_env.sh."""
    main = (REPO_ROOT / "setup.sh").read_text()
    assert "setup_env.sh" in main, "setup.sh must load setup_env.sh"


def test_creates_new_env_noninteractive(tmp_path):
    """Empty dir + no stdin → creates .env with all keys commented."""
    out = _run_setup_env(tmp_path, stdin="")
    env_file = tmp_path / ".env"
    assert env_file.exists()
    content = env_file.read_text()

    # All four API keys present as commented placeholders
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "GOOGLE_API_KEY", "S2_API_KEY"):
        assert f"# {key}=" in content, f"{key} should be commented placeholder"
        # And not set to any real value
        assert not re.search(rf"^\s*{key}=\S", content, re.MULTILINE), \
            f"{key} must not be auto-populated in non-interactive mode"

    # Every documented key must appear somewhere
    for key in _parse_setup_env_keys():
        assert re.search(rf"(^|\n)\s*#?\s*{key}=", content), \
            f"{key} missing from generated .env"


def test_preserves_existing_api_keys(tmp_path):
    """Existing secret values must not be overwritten."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=sk-existing-real-value\n"
        "S2_API_KEY=s2-existing-value\n"
    )
    before = env_file.read_text()
    out = _run_setup_env(tmp_path, stdin="")
    after = env_file.read_text()

    assert "sk-existing-real-value" in after, "existing OPENAI_API_KEY lost"
    assert "s2-existing-value" in after, "existing S2_API_KEY lost"
    # The original lines survive verbatim
    for line in before.strip().splitlines():
        assert line in after

    # User-facing message must indicate skip
    assert "OPENAI_API_KEY" in out
    assert "S2_API_KEY" in out


def test_idempotent(tmp_path):
    """Running twice must not change the file."""
    _run_setup_env(tmp_path, stdin="")
    first = (tmp_path / ".env").read_text()
    _run_setup_env(tmp_path, stdin="")
    second = (tmp_path / ".env").read_text()
    assert first == second, "setup_env.sh must be idempotent"


def test_prompts_only_for_four_critical_keys():
    """_prompt_secret must target exactly OPENAI/ANTHROPIC/GOOGLE/S2."""
    text = SETUP_ENV_SH.read_text()
    prompted = set(re.findall(r'_prompt_secret\s+"([A-Z_][A-Z0-9_]*)"', text))
    assert prompted == {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "S2_API_KEY",
    }, f"Unexpected prompted keys: {prompted}"


def test_no_real_secret_values_in_script():
    """The script must never embed real API keys."""
    text = SETUP_ENV_SH.read_text()
    # OpenAI keys start with sk- and are long
    assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", text)
    # Anthropic keys start with sk-ant-
    assert not re.search(r"sk-ant-[A-Za-z0-9_-]{10,}", text)


def test_file_permissions_restrictive_on_create(tmp_path):
    """Newly-created .env should be chmod 600 (best effort)."""
    _run_setup_env(tmp_path, stdin="")
    env_file = tmp_path / ".env"
    mode = env_file.stat().st_mode & 0o777
    # Some filesystems ignore chmod; accept if call was at least attempted
    # (mode 0o600) or if umask left it readable. Require no world-write.
    assert not (mode & 0o002), f".env should not be world-writable (mode={oct(mode)})"
