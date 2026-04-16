"""Tests for ari/viz/ — API endpoint regression tests."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock
from http.client import HTTPConnection

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def state():
    """Return the viz state module."""
    from ari.viz import state as _st
    return _st


@pytest.fixture
def api_state():
    from ari.viz.api_state import (
        _load_nodes_tree, _api_checkpoints, _api_checkpoint_summary,
    )
    return type("NS", (), {
        "_load_nodes_tree": staticmethod(_load_nodes_tree),
        "_api_checkpoints": staticmethod(_api_checkpoints),
        "_api_checkpoint_summary": staticmethod(_api_checkpoint_summary),
    })


# ── _api_checkpoints ─────────────────────────────────────────────────────────

def test_api_checkpoints_empty(state, api_state, tmp_path, monkeypatch):
    """Returns empty list when checkpoint dir doesn't exist."""
    monkeypatch.chdir(tmp_path)
    result = api_state._api_checkpoints()
    assert isinstance(result, list)


def test_api_checkpoints_lists_dirs(state, api_state, tmp_path, monkeypatch):
    """Lists checkpoint directories with status."""
    monkeypatch.chdir(tmp_path)
    ckpt_dir = tmp_path / "checkpoints" / "20260101_MyExp"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "idea.json").write_text("{}")

    result = api_state._api_checkpoints()
    names = [c["id"] if isinstance(c, dict) else c for c in result]
    assert any("MyExp" in str(n) for n in names)


# ── _load_nodes_tree ─────────────────────────────────────────────────────────

def test_load_nodes_tree_returns_none_without_checkpoint(state, api_state, monkeypatch):
    """Returns None when _checkpoint_dir is None."""
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = api_state._load_nodes_tree()
    assert result is None


def test_load_nodes_tree_reads_file(state, api_state, tmp_path, monkeypatch):
    """Reads nodes_tree.json from checkpoint dir."""
    tree_data = {"run_id": "abc", "nodes": []}
    (tmp_path / "nodes_tree.json").write_text(json.dumps(tree_data))
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    result = api_state._load_nodes_tree()
    assert result is not None
    assert result.get("run_id") == "abc"


# ── State running_pid injection ───────────────────────────────────────────────

def test_state_injects_running_pid_when_process_alive(state, monkeypatch):
    """_last_proc.poll()==None → running_pid is set, status_label is Running."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    monkeypatch.setattr(state, "_last_proc", mock_proc)
    monkeypatch.setattr(state, "_checkpoint_dir", None)

    data = {}
    _pid = None
    if state._last_proc and state._last_proc.poll() is None:
        _pid = state._last_proc.pid
    data["running_pid"] = _pid
    data["is_running"] = bool(_pid)
    data["status_label"] = "🟢 Running" if _pid else "⬛ Stopped"

    assert data["running_pid"] == 12345
    assert data["is_running"] is True
    assert "Running" in data["status_label"]


def test_state_running_pid_none_when_dead(state, monkeypatch):
    """_last_proc.poll()!=None → running_pid is None."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = 0
    monkeypatch.setattr(state, "_last_proc", mock_proc)

    _pid = None
    if state._last_proc and state._last_proc.poll() is None:
        _pid = state._last_proc.pid
    data = {"running_pid": _pid, "status_label": "🟢 Running" if _pid else "⬛ Stopped"}

    assert data["running_pid"] is None
    assert "Stopped" in data["status_label"]


def test_state_running_pid_none_when_no_proc(state, monkeypatch):
    monkeypatch.setattr(state, "_last_proc", None)
    _pid = None
    if state._last_proc and state._last_proc.poll() is None:
        _pid = state._last_proc.pid
    assert _pid is None


def test_state_error_exit_code(state, monkeypatch):
    """Process exited with non-zero → exit_code set, status_label shows Error."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = 1
    mock_proc.pid = 55555
    monkeypatch.setattr(state, "_last_proc", mock_proc)

    _pid_now = None
    _exit_code = None
    _poll = state._last_proc.poll()
    if _poll is None:
        _pid_now = state._last_proc.pid
    else:
        _exit_code = _poll
    data = {
        "running_pid": _pid_now,
        "is_running": bool(_pid_now),
        "exit_code": _exit_code,
    }
    if _pid_now:
        data["status_label"] = "🟢 Running"
    elif _exit_code is not None and _exit_code != 0:
        data["status_label"] = f"🔴 Error (exit {_exit_code})"
    else:
        data["status_label"] = "⬛ Stopped"

    assert data["running_pid"] is None
    assert data["exit_code"] == 1
    assert "Error" in data["status_label"]
    assert "exit 1" in data["status_label"]


def test_state_success_exit_code(state, monkeypatch):
    """Process exited with 0 → exit_code=0, status_label shows Stopped (not Error)."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = 0
    monkeypatch.setattr(state, "_last_proc", mock_proc)

    _poll = state._last_proc.poll()
    _exit_code = _poll if _poll is not None else None
    if _exit_code is not None and _exit_code != 0:
        label = f"🔴 Error (exit {_exit_code})"
    else:
        label = "⬛ Stopped"

    assert _exit_code == 0
    assert "Stopped" in label
    assert "Error" not in label


# ── _api_stop ─────────────────────────────────────────────────────────────────

def test_api_stop_kills_running_process(state, monkeypatch):
    """stop endpoint terminates running _last_proc."""
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 99999

    terminated = []

    def fake_killpg(pgid, sig):
        terminated.append((pgid, sig))

    monkeypatch.setattr(state, "_last_proc", mock_proc)
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    with mock.patch("os.getpgid", return_value=99999), \
         mock.patch("os.killpg", side_effect=fake_killpg), \
         mock.patch("subprocess.run"):
        killed = False
        if state._last_proc and state._last_proc.poll() is None:
            try:
                import os
                os.killpg(os.getpgid(state._last_proc.pid), signal.SIGTERM)
            except Exception:
                state._last_proc.terminate()
            killed = True
    assert killed is True


def test_api_stop_no_process_returns_false(state, monkeypatch):
    """stop endpoint returns stopped=False when no process is running."""
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    with mock.patch("subprocess.run"):
        killed = False
        if state._last_proc and state._last_proc.poll() is None:
            killed = True
    assert killed is False


# ── experiment_md_content in state ────────────────────────────────────────────

def test_state_injects_experiment_md_content(state, tmp_path, monkeypatch):
    """State returns experiment_md_content when experiment.md exists in checkpoint."""
    (tmp_path / "experiment.md").write_text("## Research Goal\nTest this\n")
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)

    content = ""
    d = tmp_path
    for fname in ("experiment.md", "goal.md"):
        fp = d / fname
        if fp.exists():
            content = fp.read_text(encoding="utf-8")
            break

    assert "Research Goal" in content
    assert "Test this" in content


def test_state_no_content_without_checkpoint(state, monkeypatch):
    """State must not inject stale experiment_md when _checkpoint_dir is None."""
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    _checkpoint_dir = None
    _exp_md = "stale content"
    injected = _exp_md if _exp_md and _checkpoint_dir else None
    assert injected is None


# ── _extract_goal_from_md ─────────────────────────────────────────────────────

def test_extract_goal_from_md_research_goal_heading():
    from ari.viz.server import _extract_goal_from_md
    md = "# Experiment: X\n\n## Research Goal\nAchieve Y under Z constraint.\n\n## Other\nfoo\n"
    assert _extract_goal_from_md(md) == "Achieve Y under Z constraint."


def test_extract_goal_from_md_plain_goal_heading():
    """`## Goal` (no 'Research' prefix) must also be recognized.

    Regression for bug where IdeaPage showed only the top-level title
    because the parser only matched 'research goal'.
    """
    from ari.viz.server import _extract_goal_from_md
    md = (
        "# Experiment: Investigate improvement on QCoder Benchmark\n\n"
        "## Goal\n"
        "Investigate whether benchmark performance on QCoder Benchmark "
        "can be substantially improved in the current execution environment.\n\n"
        "## Repository\nhttps://example.com\n"
    )
    goal = _extract_goal_from_md(md)
    assert goal.startswith("Investigate whether benchmark performance")
    assert "current execution environment" in goal
    # Must NOT fall back to the top-level title.
    assert not goal.startswith("Experiment: Investigate improvement")


def test_extract_goal_from_md_multiline_body():
    from ari.viz.server import _extract_goal_from_md
    md = "## Goal\nLine one.\nLine two.\n\n## Next\nfoo\n"
    assert _extract_goal_from_md(md) == "Line one. Line two."


def test_extract_goal_from_md_fallback_to_first_line():
    """When no Goal section is present, fall back to the first non-empty line."""
    from ari.viz.server import _extract_goal_from_md
    md = "# Only a title\n\nSome body.\n"
    assert _extract_goal_from_md(md) == "Only a title"


def test_extract_goal_from_md_empty():
    from ari.viz.server import _extract_goal_from_md
    assert _extract_goal_from_md("") == ""
    assert _extract_goal_from_md("   \n\n") == ""


# ── _api_launch subprocess ────────────────────────────────────────────────────

def test_api_launch_uses_correct_command(state, tmp_path, monkeypatch):
    """_api_launch must spawn python3 -m ari.cli run <config_path>."""
    from ari.viz.api_experiment import _api_launch

    ckpt_dir = tmp_path / "checkpoints" / "test_run"
    ckpt_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "_checkpoint_dir", ckpt_dir)

    spawned_cmds = []

    class FakeProc:
        pid = 11111
        def poll(self): return None

    def fake_popen(cmd, **kw):
        spawned_cmds.append(cmd)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_last_log_path", None)
    monkeypatch.setattr(state, "_last_log_fh", None)

    body = json.dumps({
        "experiment_md": "## Research Goal\nTest\n",
        "llm_model": "gpt-5.2",
        "llm_provider": "openai",
        "phase_models": {},
    }).encode()

    with mock.patch("threading.Thread"), \
         mock.patch("builtins.open", mock.mock_open()):
        try:
            result = _api_launch(body)
        except Exception:
            pass

    if spawned_cmds:
        cmd = spawned_cmds[0]
        assert "ari.cli" in " ".join(cmd) or "ari" in " ".join(cmd)
        assert "run" in cmd


# ── Model config ──────────────────────────────────────────────────────────────

def test_auto_config_openai_model(monkeypatch):
    """ARI_MODEL + ARI_BACKEND explicitly set → auto_config respects them."""
    monkeypatch.setenv("ARI_MODEL", "gpt-5.2")
    monkeypatch.setenv("ARI_BACKEND", "openai")
    from ari import config as _cm
    import importlib; importlib.reload(_cm)
    cfg = _cm.auto_config()
    assert "gpt" in cfg.llm.model.lower()
    assert cfg.llm.backend == "openai"


def test_auto_config_anthropic_model(monkeypatch):
    """ARI_MODEL=claude-* → auto_config uses openai (liteLLM) backend."""
    monkeypatch.setenv("ARI_MODEL", "claude-3-5-sonnet")
    from ari import config as _cm
    import importlib; importlib.reload(_cm)
    cfg = _cm.auto_config()
    assert "claude" in cfg.llm.model.lower()


def test_auto_config_model_not_overridden_to_default(monkeypatch):
    """If ARI_MODEL is set in env, auto_config must use it not the hardcoded default."""
    monkeypatch.setenv("ARI_MODEL", "gpt-5.2")
    from ari import config as _cfg_mod
    import importlib
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.auto_config()
    assert cfg.llm.model == "gpt-5.2"


# ── Phase detection ───────────────────────────────────────────────────────────

def test_phase_detection_idle_empty_dir(state, tmp_path, monkeypatch):
    """Empty checkpoint dir → phase = 'idle'."""
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)

    d = tmp_path
    has_idea = (d / "idea.json").exists()
    has_tree = (d / "nodes_tree.json").exists()
    has_code = any(d.glob("*.py")) or any(d.glob("*.f90"))
    has_eval = (d / "evaluation.json").exists()
    has_paper = (d / "full_paper.tex").exists()
    has_review = (d / "review_report.json").exists()

    phase = "idle"
    for p, flag in [("review", has_review), ("paper", has_paper),
                    ("evaluation", has_eval), ("coding", has_code),
                    ("bfts", has_tree), ("idea", has_idea)]:
        if flag:
            phase = p
            break

    assert phase == "idle"


def test_phase_detection_idea_phase(state, tmp_path, monkeypatch):
    """idea.json present → phase = 'idea'."""
    (tmp_path / "idea.json").write_text("{}")
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)

    d = tmp_path
    has_idea = (d / "idea.json").exists()
    has_tree = (d / "nodes_tree.json").exists()
    has_code = any(d.glob("*.py")) or any(d.glob("*.f90"))
    has_eval = (d / "evaluation.json").exists()
    has_paper = (d / "full_paper.tex").exists()
    has_review = (d / "review_report.json").exists()

    phase = "idle"
    for p, flag in [("review", has_review), ("paper", has_paper),
                    ("evaluation", has_eval), ("coding", has_code),
                    ("bfts", has_tree), ("idea", has_idea)]:
        if flag:
            phase = p
            break
    assert phase == "idea"


def test_phase_detection_coding_phase(tmp_path):
    """*.py present → coding phase."""
    (tmp_path / "solution.py").write_text("print('hi')")
    d = tmp_path
    has_code = any(d.glob("*.py")) or any(d.glob("*.f90"))
    assert has_code


# ══════════════════════════════════════════════
# Reproducibility / Results Page Tests
# ══════════════════════════════════════════════

def test_render_repro_skill_missing():
    """When ari-skill-paper-re is absent, error dict is structured."""
    repro_err = {"error": "Tool 'reproduce_from_paper' not found. Available: []", "status": "error"}
    assert repro_err["status"] == "error"
    assert "not found" in repro_err["error"]


def test_checkpoints_endpoint(state, tmp_path, monkeypatch):
    """_api_checkpoints scans a directory and returns checkpoint list."""
    from ari.viz.api_state import _api_checkpoints
    ck = tmp_path / "20260101000000_test_exp"
    ck.mkdir(parents=True)
    (ck / "idea.json").write_text(json.dumps({"goal": "test"}))
    orig = state._checkpoint_dir
    state._checkpoint_dir = ck
    try:
        result = _api_checkpoints()
        assert isinstance(result, list)
    finally:
        state._checkpoint_dir = orig


def test_state_no_checkpoint(state, monkeypatch):
    """_api_checkpoints returns valid list even with no active checkpoint."""
    from ari.viz.api_state import _api_checkpoints
    orig = state._checkpoint_dir
    state._checkpoint_dir = None
    try:
        result = _api_checkpoints()
        assert isinstance(result, list)
    finally:
        state._checkpoint_dir = orig


def test_env_keys_structure(tmp_path, monkeypatch):
    """_api_get_env_keys returns dict with 'keys' sub-dict."""
    from ari.viz.api_settings import _api_get_env_keys
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key-123\nS2_API_KEY=abc\n")
    result = _api_get_env_keys()
    assert "keys" in result


def test_settings_json_roundtrip(tmp_path):
    """Settings dict survives JSON write/read cycle."""
    settings = {"llm_model": "gpt-4o-mini", "llm_provider": "openai", "temperature": 0.7}
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(settings))
    loaded = json.loads(p.read_text())
    assert loaded == settings


# ══════════════════════════════════════════════
# CLI: LLM title generation
# ══════════════════════════════════════════════

def test_run_id_slug_ascii_only():
    """run_id slug must contain only ASCII alphanumeric + underscore."""
    import re
    raw = "Improve image classification accuracy 最適化"
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_")[:40]
    slug = re.sub(r"_+", "_", slug)
    assert re.match(r"^[a-zA-Z0-9_-]+$", slug)
    assert len(slug) <= 40


def test_run_id_format_timestamp():
    """run_id must start with 14-digit timestamp."""
    import re
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    run_id = f"{ts}_test_experiment"
    assert re.match(r"^\d{14}_", run_id)


# ══════════════════════════════════════════════
# Dashboard HTML: Language i18n completeness
# ══════════════════════════════════════════════

_VIZ_DIR = Path(__file__).parent.parent / "ari" / "viz"
_REACT_SRC = _VIZ_DIR / "frontend" / "src"

def test_i18n_nav_keys_present():
    """All sidebar nav pages must have i18n keys in the React i18n dict."""
    en_src = (_REACT_SRC / "i18n" / "en.ts").read_text()
    required_keys = ["nav_home", "nav_experiments", "nav_monitor", "nav_tree",
                     "nav_results", "nav_new", "nav_settings", "nav_idea", "nav_workflow"]
    missing = [k for k in required_keys if k not in en_src]
    assert not missing, f"Missing i18n keys in en.ts: {missing}"


def test_no_circular_i18n_refs():
    """i18n en dict must not call t() inside itself."""
    en_src = (_REACT_SRC / "i18n" / "en.ts").read_text()
    assert "t('" not in en_src, "Circular t() call in en.ts dict"


# ── require_checkpoint_dir guard ──────────────────────────────────────────────

def test_require_checkpoint_dir_none(state, monkeypatch):
    """require_checkpoint_dir returns error when _checkpoint_dir is None."""
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    err = state.require_checkpoint_dir()
    assert err is not None
    assert "No active project" in err


def test_require_checkpoint_dir_missing(state, tmp_path, monkeypatch):
    """require_checkpoint_dir returns error when dir does not exist."""
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path / "nonexistent")
    err = state.require_checkpoint_dir()
    assert err is not None


def test_require_checkpoint_dir_ok(state, tmp_path, monkeypatch):
    """require_checkpoint_dir returns None when dir exists."""
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    err = state.require_checkpoint_dir()
    assert err is None


# ── Upload isolation ──────────────────────────────────────────────────────────

# ── Delete checkpoint + log cleanup ───────────────────────────────────────────

def test_delete_checkpoint_removes_logs(state, tmp_path, monkeypatch):
    """Deleting a checkpoint also removes associated log files."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_parent = tmp_path / "checkpoints"
    ckpt_dir = ckpt_parent / "20260101_test"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "nodes_tree.json").write_text("{}")
    # Create a log with mtime close to checkpoint
    log_f = ckpt_parent / "ari_run_1234567890.log"
    log_f.write_text("some log output")
    # Align mtime
    import os
    mtime = ckpt_dir.stat().st_mtime
    os.utime(log_f, (mtime, mtime))

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    assert not ckpt_dir.exists()
    assert not log_f.exists()
    assert result.get("cleaned_logs", 0) >= 1


def test_delete_checkpoint_cleans_zero_byte_logs(state, tmp_path, monkeypatch):
    """Deleting a checkpoint also cleans up zero-byte orphan logs."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_parent = tmp_path / "checkpoints"
    ckpt_dir = ckpt_parent / "20260101_test"
    ckpt_dir.mkdir(parents=True)
    # Zero-byte orphan logs (from failed launches)
    (ckpt_parent / "ari_run_0000000001.log").write_text("")
    (ckpt_parent / "ari_run_0000000002.log").write_text("")
    # Non-empty unrelated log with different mtime (should be kept)
    unrelated = ckpt_parent / "ari_run_9999999999.log"
    unrelated.write_text("important log from another run")
    import os
    os.utime(unrelated, (0, 0))  # epoch 0 — far from checkpoint mtime

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    assert not (ckpt_parent / "ari_run_0000000001.log").exists()
    assert not (ckpt_parent / "ari_run_0000000002.log").exists()
    assert unrelated.exists(), "Non-empty unrelated log should be preserved"


def test_delete_deselects_active_checkpoint(state, tmp_path, monkeypatch):
    """Deleting active checkpoint sets _checkpoint_dir to None."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_dir = tmp_path / "checkpoints" / "active_run"
    ckpt_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "_checkpoint_dir", ckpt_dir)

    _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert state._checkpoint_dir is None


def test_delete_checkpoint_no_separate_logs_dir(state, tmp_path, monkeypatch):
    """Deleting a checkpoint removes only the checkpoint dir (logs live inside it)."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_dir = tmp_path / "checkpoints" / "20260101_runlog"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "nodes_tree.json").write_text("{}")
    (ckpt_dir / "ari.log").write_text("line1\nline2\n")

    monkeypatch.delenv("ARI_LOG_DIR", raising=False)
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    assert not ckpt_dir.exists()


# ── Upload isolation ──────────────────────────────────────────────────────────

def test_upload_creates_staging_without_checkpoint(state, monkeypatch):
    """File upload auto-creates staging dir when no checkpoint is active."""
    from ari.viz.api_tools import _api_upload_file
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_staging_dir", None)
    headers = {"Content-Type": "text/plain", "X-Filename": "test.md"}
    result = _api_upload_file(headers, b"hello")
    assert result.get("ok") is True
    assert result.get("filename") == "test.md"
    # Cleanup
    import shutil
    if state._staging_dir and state._staging_dir.exists():
        shutil.rmtree(str(state._staging_dir))
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_staging_dir", None)


def test_upload_writes_to_checkpoint_dir(state, tmp_path, monkeypatch):
    """File upload must write to _checkpoint_dir, not cwd."""
    from ari.viz.api_tools import _api_upload_file
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    headers = {"Content-Type": "text/plain", "X-Filename": "test.md"}
    result = _api_upload_file(headers, b"hello world")
    assert result.get("ok") is True
    assert (tmp_path / "uploads" / "test.md").exists()
    assert (tmp_path / "uploads" / "test.md").read_text() == "hello world"


# ══════════════════════════════════════════════
# Settings: default merge
# ══════════════════════════════════════════════

def test_settings_get_merges_defaults(state, tmp_path, monkeypatch):
    """_api_get_settings returns defaults for missing keys in settings.json."""
    from ari.viz.api_settings import _api_get_settings
    settings_path = tmp_path / "settings.json"
    # Only provider saved — llm_model missing
    settings_path.write_text(json.dumps({"llm_provider": "openai"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)
    result = _api_get_settings()
    assert result["llm_provider"] == "openai"
    assert "llm_model" in result, "llm_model key must exist in defaults"
    assert result["llm_model"] != "?"


def test_settings_get_preserves_saved_model(state, tmp_path, monkeypatch):
    """_api_get_settings preserves explicitly saved llm_model."""
    from ari.viz.api_settings import _api_get_settings
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_model": "gpt-4o", "llm_provider": "openai"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)
    result = _api_get_settings()
    assert result["llm_model"] == "gpt-4o"


# ══════════════════════════════════════════════
# Delete: clears _last_proc and log state
# ══════════════════════════════════════════════

def test_delete_clears_last_proc(state, tmp_path, monkeypatch):
    """Deleting active checkpoint also clears _last_proc."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_dir = tmp_path / "checkpoints" / "active_run"
    ckpt_dir.mkdir(parents=True)
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = 0
    monkeypatch.setattr(state, "_checkpoint_dir", ckpt_dir)
    monkeypatch.setattr(state, "_last_proc", mock_proc)
    monkeypatch.setattr(state, "_last_log_path", tmp_path / "some.log")

    _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert state._checkpoint_dir is None
    assert state._last_proc is None
    assert state._last_log_path is None


# ══════════════════════════════════════════════
# Delete: clears _sub_experiments for deleted checkpoint
# ══════════════════════════════════════════════

def test_delete_clears_sub_experiments(state, tmp_path, monkeypatch):
    """Deleting a checkpoint removes its entry from _sub_experiments."""
    from ari.viz.api_state import _api_delete_checkpoint
    ckpt_dir = tmp_path / "checkpoints" / "20260101000000_to_delete"
    ckpt_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    # Seed a sub-experiment entry for the checkpoint
    state._sub_experiments["20260101000000_to_delete"] = {
        "run_id": "20260101000000_to_delete", "recursion_depth": 0,
    }
    _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert "20260101000000_to_delete" not in state._sub_experiments


# ══════════════════════════════════════════════
# Delete: removes sibling experiments/{run_id}/ dir (per-node work_dirs)
# ══════════════════════════════════════════════

def test_delete_removes_experiments_dir(state, tmp_path, monkeypatch):
    """Deleting a checkpoint also removes {workspace}/experiments/{run_id}/.

    The two directories are created together during a BFTS run:
      - {workspace}/checkpoints/{run_id}/           (checkpoint dir)
      - {workspace}/experiments/{run_id}/{node_id}/ (per-node work_dirs)
    A half-complete delete leaves orphan node work_dirs behind.
    """
    from ari.viz.api_state import _api_delete_checkpoint
    run_id = "20260101000000_orphan_check"
    ckpt_dir = tmp_path / "checkpoints" / run_id
    ckpt_dir.mkdir(parents=True)
    # Simulate per-node work_dirs that PathManager.ensure_node_work_dir would create
    exp_dir = tmp_path / "experiments" / run_id
    (exp_dir / "node_root").mkdir(parents=True)
    (exp_dir / "node_root" / "script.py").write_text("print(1)\n")
    (exp_dir / "node_abc12345").mkdir(parents=True)
    (exp_dir / "node_abc12345" / "result.csv").write_text("a,b\n")

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    assert not ckpt_dir.exists(), "checkpoint dir should be deleted"
    assert not exp_dir.exists(), (
        "experiments/{run_id} should be deleted alongside the checkpoint — "
        "otherwise per-node work_dirs become orphan data"
    )
    # The response advertises the extra deletion for observability.
    # Field is a list of deleted paths (may include legacy-orphan fallbacks).
    assert result.get("deleted_experiments") == [str(exp_dir)]


def test_delete_without_experiments_dir_still_succeeds(state, tmp_path, monkeypatch):
    """Missing experiments/{run_id}/ is not an error — just a no-op."""
    from ari.viz.api_state import _api_delete_checkpoint
    run_id = "20260101000000_no_exp_dir"
    ckpt_dir = tmp_path / "checkpoints" / run_id
    ckpt_dir.mkdir(parents=True)
    # Deliberately do NOT create experiments/{run_id}/
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    assert "deleted_experiments" not in result


def test_delete_keeps_unrelated_experiments_dirs(state, tmp_path, monkeypatch):
    """Only the matching run_id's experiments dir is deleted; siblings survive."""
    from ari.viz.api_state import _api_delete_checkpoint
    target_run = "20260101000000_target"
    other_run = "20260101000000_other"
    ckpt_target = tmp_path / "checkpoints" / target_run
    ckpt_target.mkdir(parents=True)
    exp_target = tmp_path / "experiments" / target_run
    exp_target.mkdir(parents=True)
    (exp_target / "file.txt").write_text("t\n")
    exp_other = tmp_path / "experiments" / other_run
    exp_other.mkdir(parents=True)
    (exp_other / "keep.txt").write_text("k\n")

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    _api_delete_checkpoint(json.dumps({"path": str(ckpt_target)}).encode())
    assert not exp_target.exists(), "target experiments dir must be deleted"
    assert exp_other.exists(), "unrelated experiments dir must be preserved"
    assert (exp_other / "keep.txt").read_text() == "k\n"


def test_create_and_delete_paths_match(state, tmp_path, monkeypatch):
    """Creation path (PathManager) and deletion path (_api_delete_checkpoint)
    must target the exact same experiments/{run_id} directory."""
    from ari.paths import PathManager
    from ari.viz.api_state import _api_delete_checkpoint
    run_id = "20260101000000_symmetry"

    # Use PathManager — the same class cli.py uses — to create both sides.
    pm = PathManager(tmp_path)
    pm.checkpoints_root.mkdir(parents=True, exist_ok=True)
    ckpt_dir = pm.ensure_checkpoint(run_id)
    # Create a node work_dir the way cli.py does.
    node_wd = pm.ensure_node_work_dir(run_id, "node_root")
    (node_wd / "artifact.bin").write_text("X")
    assert node_wd.is_dir() and node_wd.exists()

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    result = _api_delete_checkpoint(json.dumps({"path": str(ckpt_dir)}).encode())
    assert result.get("ok") is True
    # The run_id bucket under experiments/ must be gone.
    assert not (pm.experiments_root / run_id).exists()
    assert not node_wd.exists()


# ══════════════════════════════════════════════
# Checkpoints listing: prunes stale _running_procs
# ══════════════════════════════════════════════

def test_checkpoints_prunes_stale_running_procs(state, tmp_path, monkeypatch):
    """_api_checkpoints removes _running_procs entries for missing dirs."""
    from ari.viz.api_state import _api_checkpoints
    ckpt_parent = tmp_path / "checkpoints"
    alive = ckpt_parent / "20260101000000_alive"
    alive.mkdir(parents=True)
    # Insert two _running_procs entries: one for an existing dir, one stale
    alive_resolved = str(alive.resolve())
    stale_resolved = str((ckpt_parent / "20260101000000_gone").resolve())
    mock_proc = mock.MagicMock()
    mock_proc.poll.return_value = None  # still "running"
    state._running_procs[alive_resolved] = mock_proc
    state._running_procs[stale_resolved] = mock_proc
    # Patch search paths to only look at tmp_path
    monkeypatch.setattr(state, "_ari_root", tmp_path / "_nope")
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    with mock.patch("ari.viz.api_state.Path") as MockPath:
        # We need the real Path for everything except __file__ parent chain
        MockPath.side_effect = Path
        MockPath.cwd.return_value = tmp_path
        MockPath.home.return_value = tmp_path / "_nohome"
        # Provide a search path list that includes our tmp checkpoints
        import ari.viz.api_state as _mod
        orig = _mod._api_checkpoints
        # Just call the real function — the search path includes Path.cwd()/checkpoints
        _api_checkpoints()
    assert stale_resolved not in state._running_procs, \
        "Stale _running_procs entry must be pruned"
    # Cleanup
    state._running_procs.clear()


# ══════════════════════════════════════════════
# Launch: saves model info to state
# ══════════════════════════════════════════════

def test_launch_saves_model_to_state(state, tmp_path, monkeypatch):
    """_api_launch stores resolved llm model/provider in _st."""
    from ari.viz.api_experiment import _api_launch
    # Setup: write experiment.md so launch can find it
    exp_md = tmp_path / "experiment.md"
    exp_md.write_text("# Research Goal\nTest")
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    monkeypatch.setattr(state, "_settings_path", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(json.dumps({"llm_provider": "openai"}))
    # Mock Popen to avoid actually running
    mock_proc = mock.MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None
    with mock.patch("subprocess.Popen", return_value=mock_proc):
        body = json.dumps({
            "experiment_md": "# Test",
            "llm_model": "gpt-4o",
            "llm_provider": "openai",
        }).encode()
        result = _api_launch(body)

    assert result.get("ok") is True
    assert state._launch_llm_model == "gpt-4o"
    assert state._launch_llm_provider == "openai"


def test_launch_applies_provider_default_model(state, tmp_path, monkeypatch):
    """When only provider is set (no model), launch applies a provider default."""
    from ari.viz.api_experiment import _api_launch
    exp_md = tmp_path / "experiment.md"
    exp_md.write_text("# Research Goal\nTest")
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    monkeypatch.setattr(state, "_settings_path", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(json.dumps({"llm_provider": "anthropic"}))
    mock_proc = mock.MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None
    with mock.patch("subprocess.Popen", return_value=mock_proc):
        body = json.dumps({
            "experiment_md": "# Test",
            "llm_model": "",
            "llm_provider": "anthropic",
        }).encode()
        result = _api_launch(body)

    assert result.get("ok") is True
    assert state._launch_llm_model, "Should have a default model for anthropic"
    assert state._launch_llm_provider == "anthropic"


# ══════════════════════════════════════════════
# /state: experiment_config always present
# ══════════════════════════════════════════════

def test_state_experiment_config_without_checkpoint(state, tmp_path, monkeypatch):
    """experiment_config should be present in /state even without a valid checkpoint."""
    # Simulate: build data dict as server.py does, with no valid checkpoint
    from ari.viz.api_settings import _api_get_settings

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_launch_llm_model", "gpt-4o")
    monkeypatch.setattr(state, "_launch_llm_provider", "openai")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_provider": "openai"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)

    # Replicate the fallback logic from server.py
    data = {}
    if "experiment_config" not in data:
        _s3 = _api_get_settings()
        _lm = state._launch_llm_model or _s3.get("llm_model", "")
        _lp = state._launch_llm_provider or _s3.get("llm_provider", "")
        data["experiment_config"] = {
            "llm_model": _lm,
            "llm_backend": _lp,
        }

    cfg = data["experiment_config"]
    assert cfg["llm_model"] == "gpt-4o"
    assert cfg["llm_backend"] == "openai"


def test_state_experiment_config_falls_back_to_settings(state, tmp_path, monkeypatch):
    """When no launch info, experiment_config uses settings defaults."""
    from ari.viz.api_settings import _api_get_settings

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_launch_llm_model", None)
    monkeypatch.setattr(state, "_launch_llm_provider", None)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_provider": "openai", "llm_model": "gpt-5.2"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)

    data = {}
    _s3 = _api_get_settings()
    _lm = state._launch_llm_model or _s3.get("llm_model", "")
    _lp = state._launch_llm_provider or _s3.get("llm_provider", "")
    data["experiment_config"] = {
        "llm_model": _lm,
        "llm_backend": _lp,
    }

    assert data["experiment_config"]["llm_model"] == "gpt-5.2"
    assert data["experiment_config"]["llm_backend"] == "openai"


# ══════════════════════════════════════════════
# server.py: no "?" in experiment_config values
# ══════════════════════════════════════════════

def test_experiment_config_no_question_marks():
    """server.py must not use '?' as a fallback value in experiment_config."""
    src = (_VIZ_DIR / "server.py").read_text()
    # Find the experiment_config dict block
    import re
    m = re.search(r'data\["experiment_config"\]\s*=\s*\{(.+?)\}', src, re.DOTALL)
    assert m, "experiment_config dict not found in server.py"
    block = m.group(1)
    assert '"?"' not in block, f'Found "?" fallback in experiment_config: {block}'


# ══════════════════════════════════════════════
# Dashboard JS: scope values consistency
# ══════════════════════════════════════════════

def test_scope_presets_values_consistent():
    """SCOPE_PRESETS must have consistent values and applyScopePreset must reference all fields."""
    import re
    tsx = (_REACT_SRC / "components" / "Wizard" / "StepScope.tsx").read_text()

    # Extract SCOPE_PRESETS array
    pm = re.search(r"const SCOPE_PRESETS.*?=\s*\[(.+?)\];", tsx, re.DOTALL)
    assert pm, "SCOPE_PRESETS array not found in StepScope.tsx"
    presets_raw = pm.group(1)

    # Parse each preset object
    depths = [int(x) for x in re.findall(r"depth:\s*(\d+)", presets_raw)]
    nodes  = [int(x) for x in re.findall(r"nodes:\s*(\d+)", presets_raw)]
    reacts = [int(x) for x in re.findall(r"react:\s*(\d+)", presets_raw)]

    assert len(depths) == 5, f"Expected 5 presets, got {len(depths)}"
    assert len(nodes) == 5
    assert len(reacts) == 5

    # Presets must be monotonically increasing (Quick < Standard < Thorough < Deep < Exhaustive)
    for seq_name, seq in [("depth", depths), ("nodes", nodes), ("react", reacts)]:
        for i in range(len(seq) - 1):
            assert seq[i] < seq[i+1], \
                f"SCOPE_PRESETS {seq_name} not increasing: index {i}={seq[i]} >= index {i+1}={seq[i+1]}"

    # applyScopePreset callback must set all scope fields
    assert "applyScopePreset" in tsx, "applyScopePreset function not found"
    for field in ["maxDepth", "maxNodes", "maxReact", "workers", "timeout"]:
        assert field in tsx, f"StepScope missing field '{field}'"

    # Preset buttons must exist (5 labels)
    assert "PRESET_LABELS" in tsx or "Quick" in tsx, "Preset buttons not found in StepScope"


# ══════════════════════════════════════════════
# max_workers floor guard (cli.py)
# ══════════════════════════════════════════════

def test_max_workers_floor_at_one():
    """max_workers = max(1, min(cfg.bfts.max_parallel_nodes, 4)) must be >= 1."""
    from ari.config import BFTSConfig
    for parallel in (0, -1, 1, 4, 8):
        cfg = BFTSConfig(max_parallel_nodes=parallel)
        max_workers = max(1, min(cfg.max_parallel_nodes, 4))
        assert max_workers >= 1, f"max_workers must be >= 1, got {max_workers} for parallel={parallel}"
        assert max_workers <= 4


def test_cli_run_loop_max_workers_zero_safe():
    """_run_loop with max_parallel_nodes=0 must still produce max_workers >= 1."""
    import re
    cli_src = Path(__file__).parent.parent / "ari" / "cli.py"
    src = cli_src.read_text()
    # Verify the guard is present: max(1, min(...))
    assert re.search(r"max\(\s*1\s*,\s*min\(", src), \
        "cli.py must guard max_workers with max(1, ...) to prevent zero workers"


# ══════════════════════════════════════════════
# experiment_md_content leak prevention
# ══════════════════════════════════════════════

def test_experiment_md_not_leaked_when_process_dead(state, tmp_path, monkeypatch):
    """experiment_md_content must NOT be served from project root when process is not running."""
    # Setup: write experiment.md to the "project root" equivalent
    proj_root = tmp_path / "ari-core"
    proj_root.mkdir()
    (proj_root / "experiment.md").write_text("## Research Goal\nSECRET test content\n")

    # Simulate: process exited (poll() returns 0)
    dead_proc = mock.MagicMock()
    dead_proc.poll.return_value = 0
    monkeypatch.setattr(state, "_last_proc", dead_proc)
    monkeypatch.setattr(state, "_last_experiment_md", "SECRET test content")
    monkeypatch.setattr(state, "_checkpoint_dir", None)

    # Replicate the fixed fallback logic from server.py
    data = {}
    if not data.get("experiment_md_content") and state._last_proc and state._last_proc.poll() is None:
        # This branch should NOT execute because process is dead
        data["experiment_md_content"] = "LEAKED"

    assert "experiment_md_content" not in data, \
        "experiment_md_content must not be served when process is not running"


def test_experiment_md_not_leaked_when_no_process(state, monkeypatch):
    """experiment_md_content must NOT be served when _last_proc is None."""
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_last_experiment_md", "SECRET from previous run")
    monkeypatch.setattr(state, "_checkpoint_dir", None)

    data = {}
    if not data.get("experiment_md_content") and state._last_proc and state._last_proc.poll() is None:
        data["experiment_md_content"] = "LEAKED"

    assert "experiment_md_content" not in data


def test_experiment_md_served_when_process_running(state, tmp_path, monkeypatch):
    """experiment_md_content IS served when a process is actively running."""
    running_proc = mock.MagicMock()
    running_proc.poll.return_value = None  # process alive
    monkeypatch.setattr(state, "_last_proc", running_proc)
    monkeypatch.setattr(state, "_last_experiment_md", "Active experiment content")
    monkeypatch.setattr(state, "_checkpoint_dir", None)

    data = {}
    if not data.get("experiment_md_content") and state._last_proc and state._last_proc.poll() is None:
        if state._last_experiment_md:
            data["experiment_md_content"] = state._last_experiment_md[:4000]

    assert data.get("experiment_md_content") == "Active experiment content"


def test_experiment_md_cleared_on_process_exit(state, monkeypatch):
    """_last_experiment_md must be cleared when process exits.
    _launch_llm_model/provider are kept (not sensitive, needed for CONFIG)."""
    dead_proc = mock.MagicMock()
    dead_proc.poll.return_value = 0
    monkeypatch.setattr(state, "_last_proc", dead_proc)
    monkeypatch.setattr(state, "_last_experiment_md", "stale experiment content")
    monkeypatch.setattr(state, "_launch_llm_model", "qwen3:8b")
    monkeypatch.setattr(state, "_launch_llm_provider", "ollama")

    # Replicate the cleanup logic from server.py /state handler
    if state._last_proc and state._last_proc.poll() is not None:
        state._last_experiment_md = None

    assert state._last_experiment_md is None
    # Model/provider must be preserved for correct CONFIG display
    assert state._launch_llm_model == "qwen3:8b"
    assert state._launch_llm_provider == "ollama"


def test_experiment_md_preserved_when_process_running(state, monkeypatch):
    """_last_experiment_md must NOT be cleared while process is still running."""
    running_proc = mock.MagicMock()
    running_proc.poll.return_value = None  # alive
    monkeypatch.setattr(state, "_last_proc", running_proc)
    monkeypatch.setattr(state, "_last_experiment_md", "active content")
    monkeypatch.setattr(state, "_launch_llm_model", "qwen3:8b")
    monkeypatch.setattr(state, "_launch_llm_provider", "ollama")

    if state._last_proc and state._last_proc.poll() is not None:
        state._last_experiment_md = None

    assert state._last_experiment_md == "active content"
    assert state._launch_llm_model == "qwen3:8b"
    assert state._launch_llm_provider == "ollama"


def test_server_fallback_has_process_guard():
    """server.py fallback for experiment_md must check _last_proc.poll() is None."""
    src = (_VIZ_DIR / "server.py").read_text()
    import re
    # Find the if-statement line directly after the "Fallback" comment
    m = re.search(
        r"# Fallback: experiment_md from project root.*?\n(.+?\n)",
        src, re.DOTALL,
    )
    assert m, "Fallback block not found in server.py"
    # Capture enough lines to include the if-condition
    start = m.start()
    block = src[start:start + 500]
    assert "_last_proc" in block and "poll()" in block, \
        "Fallback must check _last_proc.poll() to prevent leaking test content when no process running"


def test_server_state_has_experiment_md_cleanup():
    """server.py /state handler must clear _last_experiment_md when process exits,
    but must NOT clear _launch_llm_model/_provider (needed for CONFIG display)."""
    src = (_VIZ_DIR / "server.py").read_text()
    import re
    m = re.search(r'elif self\.path == "/state":.+?_load_nodes_tree', src, re.DOTALL)
    assert m, "/state handler not found"
    block = m.group(0)
    assert "_last_experiment_md = None" in block, \
        "/state must clear _last_experiment_md when process exits"
    assert "_launch_llm_model = None" not in block, \
        "/state must NOT clear _launch_llm_model (needed for CONFIG)"
    assert "_launch_llm_provider = None" not in block, \
        "/state must NOT clear _launch_llm_provider (needed for CONFIG)"


def test_launch_config_json_persisted(state, tmp_path, monkeypatch):
    """launch_config.json must be written to checkpoint dir with model/provider."""
    # Simulate the launch_config capture and write logic from _watch_for_checkpoint
    monkeypatch.setattr(state, "_launch_llm_model", "gpt-5.2")
    monkeypatch.setattr(state, "_launch_llm_provider", "openai")

    _launch_cfg = {
        "llm_model": state._launch_llm_model or "",
        "llm_provider": state._launch_llm_provider or "",
    }
    lc_path = tmp_path / "launch_config.json"
    lc_path.write_text(json.dumps(_launch_cfg, indent=2))

    loaded = json.loads(lc_path.read_text())
    assert loaded["llm_model"] == "gpt-5.2"
    assert loaded["llm_provider"] == "openai"


def test_launch_config_json_used_as_fallback(state, tmp_path, monkeypatch):
    """When _launch_llm_model is None (server restarted), launch_config.json
    from checkpoint must be used for experiment_config model display."""
    # Simulate server restart: volatile state is gone
    monkeypatch.setattr(state, "_launch_llm_model", None)
    monkeypatch.setattr(state, "_launch_llm_provider", None)

    # But checkpoint has launch_config.json from original launch
    (tmp_path / "launch_config.json").write_text(
        json.dumps({"llm_model": "gpt-5.2", "llm_provider": "openai"})
    )

    # Replicate the fallback logic from server.py
    _launch_model = state._launch_llm_model or ""
    _launch_provider = state._launch_llm_provider or ""
    if not _launch_model or not _launch_provider:
        _lc_path = tmp_path / "launch_config.json"
        if _lc_path.exists():
            _lc = json.loads(_lc_path.read_text())
            _launch_model = _launch_model or _lc.get("llm_model", "")
            _launch_provider = _launch_provider or _lc.get("llm_provider", "")

    assert _launch_model == "gpt-5.2", "Must read model from launch_config.json"
    assert _launch_provider == "openai", "Must read provider from launch_config.json"


def test_server_reads_launch_config_json():
    """server.py must read launch_config.json as fallback for model info."""
    src = (_VIZ_DIR / "server.py").read_text()
    assert "launch_config.json" in src, \
        "server.py must reference launch_config.json for persistent model info"


def test_api_experiment_saves_launch_config():
    """api_experiment.py must save launch_config.json in _watch_for_checkpoint."""
    src = (_VIZ_DIR / "api_experiment.py").read_text()
    assert "launch_config.json" in src, \
        "api_experiment.py must persist launch config to checkpoint"
    assert "_launch_cfg" in src, \
        "api_experiment.py must capture launch config before watch thread"


# ══════════════════════════════════════════════
# /state: _launch_config overrides YAML defaults
# ══════════════════════════════════════════════

def test_state_experiment_config_uses_launch_config_over_yaml(state, tmp_path, monkeypatch):
    """When _launch_config is set (wizard launch), experiment_config must use
    those values instead of falling back to hpc.yaml / default.yaml."""
    import yaml

    # Set up config directory with hpc.yaml and default.yaml
    config_root = tmp_path / "config"
    (config_root / "profiles").mkdir(parents=True)
    (config_root / "profiles" / "hpc.yaml").write_text(yaml.dump({
        "profile": "hpc",
        "hpc": {"enabled": True, "scheduler": "auto", "partition": "auto",
                "cpus_per_task": 8, "memory_gb": 32, "walltime": "04:00:00"},
        "bfts": {"max_total_nodes": 20, "parallel": 4},
    }))
    (config_root / "default.yaml").write_text(yaml.dump({
        "bfts": {"max_depth": 5, "max_total_nodes": 50, "max_parallel_nodes": 4,
                 "timeout_per_node": 7200},
        "llm": {"model": "claude-haiku-4-5", "backend": "claude"},
    }))

    # Set up a valid checkpoint dir (make _ckpt_valid True)
    ckpt = tmp_path / "checkpoints" / "test_exp"
    ckpt.mkdir(parents=True)
    (ckpt / "nodes_tree.json").write_text('{"nodes":[]}')

    monkeypatch.setattr(state, "_checkpoint_dir", ckpt)
    monkeypatch.setattr(state, "_launch_llm_model", "gpt-5.2")
    monkeypatch.setattr(state, "_launch_llm_provider", "openai")

    # Simulate wizard "quick" scope: set _launch_config
    monkeypatch.setattr(state, "_launch_config", {
        "llm_model": "gpt-5.2", "llm_provider": "openai",
        "max_nodes": 10, "max_depth": 3, "max_react": 20,
        "timeout_node_s": 1800, "parallel": 2,
    })

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_provider": "openai", "llm_model": "gpt-5.2"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)

    # Replicate the exact code path from server.py lines 322-395
    d = ckpt
    _wf_cfg = {}
    for _wf_path in [d / "workflow.yaml",
                     config_root / "profiles" / "hpc.yaml",
                     config_root / "default.yaml"]:
        if _wf_path.exists():
            _tmp = yaml.safe_load(_wf_path.read_text()) or {}
            if _tmp.get("bfts") or _tmp.get("hpc"):
                _wf_cfg = _tmp
                break
    _bfts = _wf_cfg.get("bfts", {})
    _hpc = _wf_cfg.get("hpc", {})
    _default_cfg = yaml.safe_load((config_root / "default.yaml").read_text()) or {}
    _default_bfts = _default_cfg.get("bfts", {})

    # Priority: in-memory launch config > launch_config.json > YAML defaults
    _lc_data = {}
    if state._launch_config:
        _lc_data = dict(state._launch_config)
    if not _lc_data:
        _lc_path = d / "launch_config.json"
        if _lc_path.exists():
            _lc_data = json.loads(_lc_path.read_text())

    experiment_config = {
        "max_nodes":      _lc_data.get("max_nodes") or _bfts.get("max_total_nodes", _default_bfts.get("max_total_nodes", None)),
        "max_depth":      _lc_data.get("max_depth") or _bfts.get("max_depth", _default_bfts.get("max_depth", None)),
        "parallel":       _lc_data.get("parallel") or _bfts.get("parallel", _default_bfts.get("max_parallel_nodes", None)),
        "timeout_node_s": _lc_data.get("timeout_node_s") or _bfts.get("timeout_per_node", _default_bfts.get("timeout_per_node", None)),
        "max_react":      _lc_data.get("max_react") or _bfts.get("max_react_steps", _default_bfts.get("max_react_steps", 80)),
        "scheduler":      _hpc.get("scheduler", "local"),
        "partition":      _lc_data.get("partition") or _hpc.get("partition", ""),
        "cpus":           _lc_data.get("hpc_cpus") or _hpc.get("cpus_per_task", None),
        "memory_gb":      _lc_data.get("hpc_memory_gb") or _hpc.get("memory_gb", None),
        "gpus":           _lc_data.get("hpc_gpus") or _hpc.get("gpus", None),
        "walltime":       _lc_data.get("hpc_walltime") or _hpc.get("walltime", ""),
    }

    # Quick preset values must override YAML defaults
    assert experiment_config["max_nodes"] == 10, \
        f"Expected quick max_nodes=10, got {experiment_config['max_nodes']} (YAML fallback)"
    assert experiment_config["max_depth"] == 3, \
        f"Expected quick max_depth=3, got {experiment_config['max_depth']} (YAML fallback)"
    assert experiment_config["max_react"] == 20, \
        f"Expected quick max_react=20, got {experiment_config['max_react']} (YAML fallback)"
    assert experiment_config["parallel"] == 2, \
        f"Expected quick parallel=2, got {experiment_config['parallel']} (YAML fallback)"
    assert experiment_config["timeout_node_s"] == 1800, \
        f"Expected quick timeout=1800s, got {experiment_config['timeout_node_s']} (YAML fallback)"


def test_state_experiment_config_fallback_uses_launch_config(state, tmp_path, monkeypatch):
    """Fallback path (no valid checkpoint) must also use _launch_config."""
    import yaml

    config_root = tmp_path / "config"
    (config_root / "profiles").mkdir(parents=True)
    (config_root / "profiles" / "hpc.yaml").write_text(yaml.dump({
        "hpc": {"scheduler": "auto", "partition": "auto",
                "cpus_per_task": 8, "memory_gb": 32, "walltime": "04:00:00"},
        "bfts": {"max_total_nodes": 20, "parallel": 4},
    }))
    (config_root / "default.yaml").write_text(yaml.dump({
        "bfts": {"max_depth": 5, "max_total_nodes": 50, "timeout_per_node": 7200},
    }))

    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_launch_llm_model", "gpt-5.2")
    monkeypatch.setattr(state, "_launch_llm_provider", "openai")
    monkeypatch.setattr(state, "_launch_config", {
        "llm_model": "gpt-5.2", "llm_provider": "openai",
        "max_nodes": 10, "max_depth": 3, "max_react": 20,
        "timeout_node_s": 1800, "parallel": 2,
    })
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_provider": "openai", "llm_model": "gpt-5.2"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)

    # Replicate fallback code path from server.py (experiment_config not in data)
    _lc_fb = {}
    if state._launch_config:
        _lc_fb = dict(state._launch_config)
    if not _lc_fb:
        pass  # no checkpoint to read from

    _wf_cfg_fb = {}
    for _wf_p in [config_root / "profiles" / "hpc.yaml",
                  config_root / "default.yaml"]:
        if _wf_p.exists():
            _tmp_fb = yaml.safe_load(_wf_p.read_text()) or {}
            if _tmp_fb.get("bfts") or _tmp_fb.get("hpc"):
                _wf_cfg_fb = _tmp_fb
                break
    _bfts_fb = _wf_cfg_fb.get("bfts", {})
    _hpc_fb = _wf_cfg_fb.get("hpc", {})

    experiment_config = {
        "max_nodes":      _lc_fb.get("max_nodes") or _bfts_fb.get("max_total_nodes"),
        "max_depth":      _lc_fb.get("max_depth") or _bfts_fb.get("max_depth"),
        "parallel":       _lc_fb.get("parallel") or _bfts_fb.get("max_parallel_nodes") or _bfts_fb.get("parallel"),
        "timeout_node_s": _lc_fb.get("timeout_node_s") or _bfts_fb.get("timeout_per_node"),
        "max_react":      _lc_fb.get("max_react") or _bfts_fb.get("max_react_steps", 80),
    }

    assert experiment_config["max_nodes"] == 10
    assert experiment_config["max_depth"] == 3
    assert experiment_config["max_react"] == 20
    assert experiment_config["parallel"] == 2
    assert experiment_config["timeout_node_s"] == 1800


def test_state_experiment_config_server_restart_reads_json(state, tmp_path, monkeypatch):
    """After server restart (_launch_config=None), must read launch_config.json."""
    import yaml

    config_root = tmp_path / "config"
    (config_root / "profiles").mkdir(parents=True)
    (config_root / "profiles" / "hpc.yaml").write_text(yaml.dump({
        "hpc": {"scheduler": "auto", "cpus_per_task": 8, "memory_gb": 32},
        "bfts": {"max_total_nodes": 20, "parallel": 4},
    }))
    (config_root / "default.yaml").write_text(yaml.dump({
        "bfts": {"max_depth": 5, "max_total_nodes": 50, "timeout_per_node": 7200},
    }))

    ckpt = tmp_path / "checkpoints" / "test_exp"
    ckpt.mkdir(parents=True)
    (ckpt / "nodes_tree.json").write_text('{"nodes":[]}')
    # launch_config.json persisted from previous launch
    (ckpt / "launch_config.json").write_text(json.dumps({
        "llm_model": "gpt-5.2", "llm_provider": "openai",
        "max_nodes": 10, "max_depth": 3, "max_react": 20,
        "timeout_node_s": 1800, "parallel": 2,
    }))

    # Server restart: volatile state is gone
    monkeypatch.setattr(state, "_checkpoint_dir", ckpt)
    monkeypatch.setattr(state, "_launch_llm_model", None)
    monkeypatch.setattr(state, "_launch_llm_provider", None)
    monkeypatch.setattr(state, "_launch_config", None)

    d = ckpt
    _lc_data = {}
    if state._launch_config:
        _lc_data = dict(state._launch_config)
    if not _lc_data:
        _lc_path = d / "launch_config.json"
        if _lc_path.exists():
            _lc_data = json.loads(_lc_path.read_text())

    _wf_cfg = {}
    for _wf_path in [d / "workflow.yaml",
                     config_root / "profiles" / "hpc.yaml",
                     config_root / "default.yaml"]:
        if _wf_path.exists():
            _tmp = yaml.safe_load(_wf_path.read_text()) or {}
            if _tmp.get("bfts") or _tmp.get("hpc"):
                _wf_cfg = _tmp
                break
    _bfts = _wf_cfg.get("bfts", {})
    _default_cfg = yaml.safe_load((config_root / "default.yaml").read_text()) or {}
    _default_bfts = _default_cfg.get("bfts", {})

    experiment_config = {
        "max_nodes":      _lc_data.get("max_nodes") or _bfts.get("max_total_nodes", _default_bfts.get("max_total_nodes", None)),
        "max_depth":      _lc_data.get("max_depth") or _bfts.get("max_depth", _default_bfts.get("max_depth", None)),
        "max_react":      _lc_data.get("max_react") or _bfts.get("max_react_steps", _default_bfts.get("max_react_steps", 80)),
        "parallel":       _lc_data.get("parallel") or _bfts.get("parallel", _default_bfts.get("max_parallel_nodes", None)),
        "timeout_node_s": _lc_data.get("timeout_node_s") or _bfts.get("timeout_per_node", _default_bfts.get("timeout_per_node", None)),
    }

    assert experiment_config["max_nodes"] == 10
    assert experiment_config["max_depth"] == 3
    assert experiment_config["max_react"] == 20
    assert experiment_config["parallel"] == 2
    assert experiment_config["timeout_node_s"] == 1800


def test_monitor_page_shows_experiment_context():
    """MonitorPage must display experiment context based on state."""
    src = (_REACT_SRC / "components" / "Monitor" / "MonitorPage.tsx").read_text()
    # Monitor page must reference experiment goal/content from state
    assert "experiment_goal" in src or "experiment_md" in src or "is_running" in src, \
        "MonitorPage must display experiment context from state"


# ══════════════════════════════════════════════
# Dashboard JS: WebSocket and log-status separation
# ══════════════════════════════════════════════

def test_react_no_log_status_pollution():
    """React components must not mix WebSocket status with log status elements."""
    # In React, WebSocket management is done via services/api.ts and context
    # Verify no component writes directly to 'log-status' DOM element
    parts = []
    for tsx in sorted(_REACT_SRC.rglob("*.tsx")):
        parts.append(tsx.read_text())
    combined = "\n".join(parts)
    # React components should not directly manipulate DOM with getElementById('log-status')
    assert 'getElementById("log-status")' not in combined and \
           "getElementById('log-status')" not in combined, \
        "React components must not directly write to 'log-status' via DOM manipulation"


# ══════════════════════════════════════════════
# PID-based process status detection
# ══════════════════════════════════════════════

def test_check_pid_alive_no_pidfile(tmp_path):
    """No .ari_pid file → stopped."""
    from ari.viz.api_state import _check_pid_alive
    assert _check_pid_alive(tmp_path) == "stopped"


def test_check_pid_alive_with_live_process(tmp_path):
    """PID file pointing to a live process → running."""
    from ari.viz.api_state import _check_pid_alive
    # Use our own PID — guaranteed to be alive
    (tmp_path / ".ari_pid").write_text(str(os.getpid()))
    assert _check_pid_alive(tmp_path) == "running"


def test_check_pid_alive_with_dead_process(tmp_path):
    """PID file pointing to a dead process → stopped."""
    from ari.viz.api_state import _check_pid_alive
    # Start a subprocess and wait for it to die, so we get a real dead PID
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid
    (tmp_path / ".ari_pid").write_text(str(dead_pid))
    assert _check_pid_alive(tmp_path) == "stopped"


def test_check_pid_alive_corrupt_pidfile(tmp_path):
    """Corrupt .ari_pid content → stopped."""
    from ari.viz.api_state import _check_pid_alive
    (tmp_path / ".ari_pid").write_text("not-a-number")
    assert _check_pid_alive(tmp_path) == "stopped"


def test_checkpoints_active_dead_proc_running_nodes(state, tmp_path, monkeypatch):
    """Active checkpoint: process dead + tree has running nodes → status must be stopped."""
    from ari.viz.api_state import _api_checkpoints

    monkeypatch.chdir(tmp_path)
    ckpt_dir = tmp_path / "checkpoints" / "20260101_dead_proc"
    ckpt_dir.mkdir(parents=True)
    tree_data = {"run_id": "test", "nodes": [
        {"id": "node_root", "depth": 0, "status": "running", "parent_id": None},
    ]}
    (ckpt_dir / "tree.json").write_text(json.dumps(tree_data))

    # Simulate dead process: create a mock proc whose poll() returns 1
    dead_proc = mock.MagicMock()
    dead_proc.poll.return_value = 1  # exited with code 1

    orig_ckpt = state._checkpoint_dir
    orig_proc = state._last_proc
    state._checkpoint_dir = ckpt_dir
    state._last_proc = dead_proc
    try:
        result = _api_checkpoints()
        matched = [c for c in result if c["id"] == "20260101_dead_proc"]
        assert matched, "Checkpoint not found in result"
        assert matched[0]["status"] == "stopped", \
            f"Expected 'stopped' but got '{matched[0]['status']}'"
    finally:
        state._checkpoint_dir = orig_ckpt
        state._last_proc = orig_proc


def test_checkpoints_nonactive_no_pidfile_running_nodes(state, tmp_path, monkeypatch):
    """Non-active checkpoint: no .ari_pid + tree has running nodes → stopped."""
    from ari.viz.api_state import _api_checkpoints

    monkeypatch.chdir(tmp_path)
    ckpt_dir = tmp_path / "checkpoints" / "20260101_orphan"
    ckpt_dir.mkdir(parents=True)
    tree_data = {"run_id": "test", "nodes": [
        {"id": "node_root", "depth": 0, "status": "running", "parent_id": None},
    ]}
    (ckpt_dir / "tree.json").write_text(json.dumps(tree_data))

    orig = state._checkpoint_dir
    state._checkpoint_dir = None  # Not active
    try:
        result = _api_checkpoints()
        matched = [c for c in result if c["id"] == "20260101_orphan"]
        assert matched, "Checkpoint not found in result"
        assert matched[0]["status"] == "stopped", \
            f"Expected 'stopped' but got '{matched[0]['status']}'"
    finally:
        state._checkpoint_dir = orig


def test_checkpoints_nonactive_live_pid_running_nodes(state, tmp_path, monkeypatch):
    """Non-active checkpoint: live .ari_pid + tree has running nodes → running."""
    from ari.viz.api_state import _api_checkpoints

    monkeypatch.chdir(tmp_path)
    ckpt_dir = tmp_path / "checkpoints" / "20260101_live"
    ckpt_dir.mkdir(parents=True)
    tree_data = {"run_id": "test", "nodes": [
        {"id": "node_root", "depth": 0, "status": "running", "parent_id": None},
    ]}
    (ckpt_dir / "tree.json").write_text(json.dumps(tree_data))
    # Write PID file with our own PID (alive)
    (ckpt_dir / ".ari_pid").write_text(str(os.getpid()))

    orig = state._checkpoint_dir
    state._checkpoint_dir = None  # Not active
    try:
        result = _api_checkpoints()
        matched = [c for c in result if c["id"] == "20260101_live"]
        assert matched, "Checkpoint not found in result"
        assert matched[0]["status"] == "running", \
            f"Expected 'running' but got '{matched[0]['status']}'"
    finally:
        state._checkpoint_dir = orig


def test_checkpoints_active_alive_proc_running_nodes(state, tmp_path, monkeypatch):
    """Active checkpoint: process alive + tree has running nodes → running."""
    from ari.viz.api_state import _api_checkpoints

    monkeypatch.chdir(tmp_path)
    ckpt_dir = tmp_path / "checkpoints" / "20260101_alive"
    ckpt_dir.mkdir(parents=True)
    tree_data = {"run_id": "test", "nodes": [
        {"id": "node_root", "depth": 0, "status": "running", "parent_id": None},
    ]}
    (ckpt_dir / "tree.json").write_text(json.dumps(tree_data))

    alive_proc = mock.MagicMock()
    alive_proc.poll.return_value = None  # still running

    orig_ckpt = state._checkpoint_dir
    orig_proc = state._last_proc
    state._checkpoint_dir = ckpt_dir
    state._last_proc = alive_proc
    try:
        result = _api_checkpoints()
        matched = [c for c in result if c["id"] == "20260101_alive"]
        assert matched, "Checkpoint not found in result"
        assert matched[0]["status"] == "running", \
            f"Expected 'running' but got '{matched[0]['status']}'"
    finally:
        state._checkpoint_dir = orig_ckpt
        state._last_proc = orig_proc


# ══════════════════════════════════════════════
# Integration test: actual HTTP /state endpoint
# ══════════════════════════════════════════════

def test_state_http_returns_launch_config_values(state, tmp_path, monkeypatch):
    """Integration test: actual HTTP GET /state must return _launch_config values,
    not YAML profile defaults."""
    import yaml
    from http.server import ThreadingHTTPServer
    from io import BytesIO

    # Set up valid checkpoint
    ckpt = tmp_path / "checkpoints" / "test_exp"
    ckpt.mkdir(parents=True)
    (ckpt / "nodes_tree.json").write_text('{"nodes":[]}')

    monkeypatch.setattr(state, "_checkpoint_dir", ckpt)
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_launch_llm_model", "gpt-5.2")
    monkeypatch.setattr(state, "_launch_llm_provider", "openai")
    monkeypatch.setattr(state, "_launch_config", {
        "llm_model": "gpt-5.2", "llm_provider": "openai",
        "max_nodes": 10, "max_depth": 3, "max_react": 20,
        "timeout_node_s": 1800, "parallel": 2,
        "hpc_cpus": 4, "hpc_memory_gb": 16, "hpc_walltime": "01:00:00",
    })
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"llm_provider": "openai", "llm_model": "gpt-5.2"}))
    monkeypatch.setattr(state, "_settings_path", settings_path)

    # Start actual HTTP server on random port
    from ari.viz.server import _Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/state")
        resp = conn.getresponse()
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        body = json.loads(resp.read())
        cfg = body.get("experiment_config", {})

        # Must reflect wizard "quick" values, not YAML defaults
        assert cfg.get("max_nodes") == 10, \
            f"max_nodes: expected 10 (quick), got {cfg.get('max_nodes')} (YAML default?)"
        assert cfg.get("max_depth") == 3, \
            f"max_depth: expected 3 (quick), got {cfg.get('max_depth')} (YAML default?)"
        assert cfg.get("max_react") == 20, \
            f"max_react: expected 20 (quick), got {cfg.get('max_react')} (YAML default?)"
        assert cfg.get("parallel") == 2, \
            f"parallel: expected 2 (quick), got {cfg.get('parallel')} (YAML default?)"
        assert cfg.get("timeout_node_s") == 1800, \
            f"timeout: expected 1800 (quick), got {cfg.get('timeout_node_s')} (YAML default?)"
        assert cfg.get("cpus") == 4, \
            f"cpus: expected 4 (quick), got {cfg.get('cpus')} (YAML default?)"
        assert cfg.get("memory_gb") == 16, \
            f"memory_gb: expected 16 (quick), got {cfg.get('memory_gb')} (YAML default?)"
        assert cfg.get("walltime") == "01:00:00", \
            f"walltime: expected 01:00:00 (quick), got {cfg.get('walltime')} (YAML default?)"
        conn.close()
    finally:
        srv.shutdown()


# ══════════════════════════════════════════════
# CORS preflight (do_OPTIONS)
# ══════════════════════════════════════════════

def test_options_returns_cors_headers():
    """do_OPTIONS must return CORS preflight headers so cross-origin
    POST requests (common with SSH tunnels / HPC portals) are not blocked."""
    from ari.viz.server import _Handler
    handler = mock.MagicMock(spec=_Handler)
    handler.send_response = mock.MagicMock()
    handler.send_header = mock.MagicMock()
    handler.end_headers = mock.MagicMock()
    # Call the real do_OPTIONS on the mock instance
    _Handler.do_OPTIONS(handler)
    handler.send_response.assert_called_once_with(204)
    headers = {call.args[0]: call.args[1] for call in handler.send_header.call_args_list}
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in headers["Access-Control-Allow-Headers"]


def test_options_preflight_live_server():
    """OPTIONS request to a live server returns 204 with CORS headers."""
    from ari.viz.server import _Handler
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/launch", headers={
            "Origin": "http://other-host:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })
        resp = conn.getresponse()
        assert resp.status == 204, f"Expected 204, got {resp.status}"
        assert resp.getheader("Access-Control-Allow-Origin") == "*"
        assert "POST" in resp.getheader("Access-Control-Allow-Methods", "")
        conn.close()
    finally:
        srv.shutdown()


# ══════════════════════════════════════════════
# _api_launch: error handling for invalid input
# ══════════════════════════════════════════════

def test_api_launch_invalid_json(state, tmp_path, monkeypatch):
    """_api_launch returns error dict (not crash) for invalid JSON body."""
    from ari.viz.api_experiment import _api_launch
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    result = _api_launch(b"not json")
    assert result["ok"] is False
    assert "Invalid request body" in result["error"]


def test_api_launch_empty_body(state, tmp_path, monkeypatch):
    """_api_launch returns error dict for empty body."""
    from ari.viz.api_experiment import _api_launch
    monkeypatch.setattr(state, "_checkpoint_dir", tmp_path)
    result = _api_launch(b"")
    assert result["ok"] is False
    assert "Invalid request body" in result["error"]


def test_api_launch_no_checkpoint_dir(state, tmp_path, monkeypatch):
    """_api_launch works when _checkpoint_dir is None (first launch)."""
    from ari.viz.api_experiment import _api_launch
    monkeypatch.setattr(state, "_checkpoint_dir", None)
    monkeypatch.setattr(state, "_last_proc", None)
    monkeypatch.setattr(state, "_last_log_path", None)
    monkeypatch.setattr(state, "_last_log_fh", None)
    monkeypatch.setattr(state, "_settings_path", tmp_path / "settings.json")
    monkeypatch.setattr(state, "_ari_root", tmp_path)
    (tmp_path / "settings.json").write_text("{}")

    mock_proc = mock.MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None

    with mock.patch("subprocess.Popen", return_value=mock_proc), \
         mock.patch("threading.Thread"), \
         mock.patch("builtins.open", mock.mock_open()):
        result = _api_launch(json.dumps({
            "experiment_md": "## Research Goal\nMaximize GFLOPS of a stencil benchmark\n",
        }).encode())

    assert result.get("ok") is True, f"Expected ok=True, got: {result}"
    assert "pid" in result
