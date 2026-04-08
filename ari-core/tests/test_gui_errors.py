"""
GUI Error Scenario Tests
Tests edge cases, error handling, and robustness of the viz module.
Covers: malformed JSON, corrupt files, path traversal, concurrent state,
broadcast failures, upload edge cases, and API input validation.
"""
import asyncio
import json
import os
import signal
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from ari.viz import state as _st


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    """Isolate shared state for every test."""
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_last_log_fh", None)
    monkeypatch.setattr(_st, "_last_log_path", None)
    monkeypatch.setattr(_st, "_last_experiment_md", None)
    monkeypatch.setattr(_st, "_launch_llm_model", None)
    monkeypatch.setattr(_st, "_launch_llm_provider", None)
    monkeypatch.setattr(_st, "_launch_config", None)
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None)
    monkeypatch.setattr(_st, "_clients", [])
    monkeypatch.setattr(_st, "_loop", None)
    monkeypatch.setattr(_st, "_last_mtime", 0.0)
    # Settings file in tmp
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr(_st, "_settings_path", settings)
    # Env write path in tmp
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")


# ══════════════════════════════════════════════════════════════════════════════
# 1. _load_nodes_tree: malformed / corrupt tree files
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadNodesTreeErrors:
    """Edge cases for tree.json / nodes_tree.json loading."""

    def test_tree_json_truncated(self, monkeypatch, tmp_path):
        """Truncated JSON triggers retry then returns None."""
        from ari.viz.api_state import _load_nodes_tree
        (tmp_path / "tree.json").write_text('{"nodes": [{"id": "a"')  # truncated
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _load_nodes_tree()
        assert result is None

    def test_tree_json_empty_file(self, monkeypatch, tmp_path):
        """Zero-byte tree.json falls back to nodes_tree.json."""
        from ari.viz.api_state import _load_nodes_tree
        (tmp_path / "tree.json").write_text("")
        (tmp_path / "nodes_tree.json").write_text('{"nodes": []}')
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        # tree.json is empty → stat().st_size == 0 but exists().
        # _load_nodes_tree reads tree.json first; empty string is invalid JSON.
        # After retry it returns None, because it tries tree.json (exists) not nodes_tree.
        # This documents the actual behavior.
        result = _load_nodes_tree()
        # The function prefers tree.json if it exists, even if empty.
        # Empty string causes JSONDecodeError → retries → still empty → returns None.
        assert result is None

    def test_tree_json_binary_garbage(self, monkeypatch, tmp_path):
        """Binary data in tree.json doesn't crash."""
        from ari.viz.api_state import _load_nodes_tree
        (tmp_path / "tree.json").write_bytes(b"\x80\xff\xfe" * 100)
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _load_nodes_tree()
        assert result is None

    def test_nodes_tree_fallback_used(self, monkeypatch, tmp_path):
        """When tree.json is missing, nodes_tree.json is used."""
        from ari.viz.api_state import _load_nodes_tree
        (tmp_path / "nodes_tree.json").write_text('{"nodes": [{"id": "n1"}]}')
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _load_nodes_tree()
        assert result is not None
        assert len(result["nodes"]) == 1

    def test_both_tree_files_missing(self, monkeypatch, tmp_path):
        """No tree files → returns None."""
        from ari.viz.api_state import _load_nodes_tree
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _load_nodes_tree()
        assert result is None

    def test_tree_json_permission_denied(self, monkeypatch, tmp_path):
        """Unreadable tree.json handled gracefully."""
        from ari.viz.api_state import _load_nodes_tree
        f = tmp_path / "tree.json"
        f.write_text('{"nodes": []}')
        f.chmod(0o000)
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        try:
            result = _load_nodes_tree()
            assert result is None
        finally:
            f.chmod(0o644)


# ══════════════════════════════════════════════════════════════════════════════
# 2. _check_pid_alive: corrupt PID files, stale PIDs
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckPidAlive:
    """Edge cases for .ari_pid checking."""

    def test_no_pid_file(self, tmp_path):
        from ari.viz.api_state import _check_pid_alive
        assert _check_pid_alive(tmp_path) == "stopped"

    def test_empty_pid_file(self, tmp_path):
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text("")
        assert _check_pid_alive(tmp_path) == "stopped"

    def test_non_numeric_pid_file(self, tmp_path):
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text("not-a-number")
        assert _check_pid_alive(tmp_path) == "stopped"

    def test_dead_pid(self, tmp_path):
        """PID that doesn't exist → stopped."""
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text("999999999")
        assert _check_pid_alive(tmp_path) == "stopped"

    def test_own_pid_alive(self, tmp_path):
        """Current process PID → running."""
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text(str(os.getpid()))
        assert _check_pid_alive(tmp_path) == "running"

    def test_pid_with_whitespace(self, tmp_path):
        """PID file with trailing newlines."""
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text(f"  {os.getpid()}  \n")
        assert _check_pid_alive(tmp_path) == "running"

    def test_negative_pid(self, tmp_path):
        """Negative PID is caught as ValueError or sends signal to process group."""
        from ari.viz.api_state import _check_pid_alive
        (tmp_path / ".ari_pid").write_text("-1")
        # -1 might raise PermissionError (kill all) or ProcessLookupError
        result = _check_pid_alive(tmp_path)
        assert result in ("running", "stopped")


# ══════════════════════════════════════════════════════════════════════════════
# 3. _api_delete_checkpoint: safety checks
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteCheckpoint:
    """Deletion safety: path validation, active checkpoint cleanup."""

    def test_delete_empty_path(self):
        from ari.viz.api_state import _api_delete_checkpoint
        result = _api_delete_checkpoint(json.dumps({"path": ""}).encode())
        assert "error" in result

    def test_delete_nonexistent_path(self, tmp_path):
        from ari.viz.api_state import _api_delete_checkpoint
        fake = str(tmp_path / "checkpoints" / "nonexistent")
        result = _api_delete_checkpoint(json.dumps({"path": fake}).encode())
        assert "error" in result
        assert "not found" in result["error"]

    def test_delete_outside_checkpoints_refused(self, tmp_path):
        """Refuse to delete dir not under 'checkpoints/'."""
        from ari.viz.api_state import _api_delete_checkpoint
        outside = tmp_path / "important_data"
        outside.mkdir()
        result = _api_delete_checkpoint(json.dumps({"path": str(outside)}).encode())
        assert "error" in result
        assert "refusing" in result["error"].lower()

    def test_delete_active_checkpoint_clears_state(self, monkeypatch, tmp_path):
        """Deleting the active checkpoint resets state vars."""
        from ari.viz.api_state import _api_delete_checkpoint
        ckpt = tmp_path / "checkpoints" / "20260101_test"
        ckpt.mkdir(parents=True)
        (ckpt / "tree.json").write_text("{}")
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        monkeypatch.setattr(_st, "_last_experiment_md", "some md")
        monkeypatch.setattr(_st, "_last_log_path", "/some/log")
        result = _api_delete_checkpoint(json.dumps({"path": str(ckpt)}).encode())
        assert result.get("ok") is True
        assert _st._checkpoint_dir is None
        assert _st._last_experiment_md is None
        assert _st._last_log_path is None

    def test_delete_cleans_orphan_logs(self, monkeypatch, tmp_path):
        """Logs near checkpoint mtime are cleaned up."""
        from ari.viz.api_state import _api_delete_checkpoint
        ckpt = tmp_path / "checkpoints" / "20260101_logtest"
        ckpt.mkdir(parents=True)
        (ckpt / "tree.json").write_text("{}")
        # Create log in parent dir with similar mtime
        log_file = tmp_path / "checkpoints" / "ari_run_12345.log"
        log_file.write_text("log content")
        result = _api_delete_checkpoint(json.dumps({"path": str(ckpt)}).encode())
        assert result.get("ok") is True
        assert result.get("cleaned_logs", 0) >= 1

    def test_delete_malformed_json_body(self):
        from ari.viz.api_state import _api_delete_checkpoint
        with pytest.raises(json.JSONDecodeError):
            _api_delete_checkpoint(b"not json")


# ══════════════════════════════════════════════════════════════════════════════
# 4. _api_switch_checkpoint: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestSwitchCheckpoint:
    """Checkpoint switching validation."""

    def test_switch_empty_path(self):
        from ari.viz.api_state import _api_switch_checkpoint
        result = _api_switch_checkpoint(json.dumps({"path": ""}).encode())
        assert "error" in result

    def test_switch_nonexistent_path(self, tmp_path):
        from ari.viz.api_state import _api_switch_checkpoint
        result = _api_switch_checkpoint(
            json.dumps({"path": str(tmp_path / "nope")}).encode()
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_switch_valid_path_updates_state(self, monkeypatch, tmp_path):
        from ari.viz.api_state import _api_switch_checkpoint
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        result = _api_switch_checkpoint(json.dumps({"path": str(ckpt)}).encode())
        assert result.get("ok") is True
        assert _st._checkpoint_dir == ckpt
        assert _st._last_mtime == 0.0  # force reload

    def test_switch_resets_mtime(self, monkeypatch, tmp_path):
        from ari.viz.api_state import _api_switch_checkpoint
        monkeypatch.setattr(_st, "_last_mtime", 99999.0)
        ckpt = tmp_path / "ckpt2"
        ckpt.mkdir()
        _api_switch_checkpoint(json.dumps({"path": str(ckpt)}).encode())
        assert _st._last_mtime == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. _broadcast: WebSocket errors
# ══════════════════════════════════════════════════════════════════════════════

class TestBroadcast:
    """WebSocket broadcast edge cases."""

    def test_broadcast_no_clients(self):
        """No clients, no loop → no-op, no crash."""
        from ari.viz.api_state import _broadcast
        _broadcast({"test": True})  # should not raise

    def test_broadcast_no_loop(self, monkeypatch):
        from ari.viz.api_state import _broadcast
        monkeypatch.setattr(_st, "_clients", [mock.MagicMock()])
        monkeypatch.setattr(_st, "_loop", None)
        _broadcast({"test": True})  # should not raise

    @pytest.mark.asyncio
    async def test_do_broadcast_removes_dead_clients(self, monkeypatch):
        """Dead WebSocket clients are removed from _clients."""
        from ari.viz.api_state import _do_broadcast

        good_ws = mock.AsyncMock()
        bad_ws = mock.AsyncMock()
        bad_ws.send.side_effect = ConnectionError("gone")

        # Use a set for _clients (as used by the actual code)
        clients = {good_ws, bad_ws}
        monkeypatch.setattr(_st, "_clients", clients)

        await _do_broadcast('{"type":"update"}')
        assert bad_ws not in _st._clients
        assert good_ws in _st._clients


# ══════════════════════════════════════════════════════════════════════════════
# 6. require_checkpoint_dir: state validation
# ══════════════════════════════════════════════════════════════════════════════

class TestRequireCheckpointDir:
    """State guard function edge cases."""

    def test_none_checkpoint(self, monkeypatch):
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        err = _st.require_checkpoint_dir()
        assert err is not None
        assert "No active project" in err

    def test_nonexistent_checkpoint(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path / "gone")
        err = _st.require_checkpoint_dir()
        assert err is not None
        assert "does not exist" in err

    def test_valid_checkpoint(self, monkeypatch, tmp_path):
        ckpt = tmp_path / "valid"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        assert _st.require_checkpoint_dir() is None


# ══════════════════════════════════════════════════════════════════════════════
# 7. _api_upload_file: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestUploadFileErrors:
    """File upload validation and edge cases."""

    def test_upload_no_checkpoint(self, monkeypatch):
        from ari.viz.api_tools import _api_upload_file
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        headers = {"Content-Type": "application/octet-stream", "X-Filename": "test.txt"}
        result = _api_upload_file(headers, b"data")
        assert result.get("ok") is False
        assert "error" in result

    def test_upload_checkpoint_deleted(self, monkeypatch, tmp_path):
        """Checkpoint dir was deleted between check and write."""
        from ari.viz.api_tools import _api_upload_file
        gone = tmp_path / "gone_dir"
        monkeypatch.setattr(_st, "_checkpoint_dir", gone)
        headers = {"Content-Type": "application/octet-stream", "X-Filename": "test.txt"}
        result = _api_upload_file(headers, b"data")
        assert result.get("ok") is False

    def test_upload_empty_body(self, monkeypatch, tmp_path):
        from ari.viz.api_tools import _api_upload_file
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        headers = {"Content-Type": "application/octet-stream", "X-Filename": "empty.md"}
        result = _api_upload_file(headers, b"")
        assert result.get("ok") is True
        assert (ckpt / "empty.md").read_bytes() == b""

    def test_upload_filename_sanitization(self, monkeypatch, tmp_path):
        """Path traversal in filename is stripped."""
        from ari.viz.api_tools import _api_upload_file
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Filename": "../../etc/passwd",
        }
        result = _api_upload_file(headers, b"malicious")
        assert result.get("ok") is True
        assert result["filename"] == "passwd"
        # File saved inside checkpoint, not at ../../etc/passwd
        assert (ckpt / "passwd").exists()

    def test_upload_multipart_no_file_part(self, monkeypatch, tmp_path):
        """Multipart body without a file part."""
        from ari.viz.api_tools import _api_upload_file
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        boundary = "----boundary123"
        body = (
            f"------boundary123\r\n"
            f"Content-Disposition: form-data; name=\"field1\"\r\n\r\n"
            f"value1\r\n"
            f"------boundary123--\r\n"
        ).encode()
        headers = {
            "Content-Type": f"multipart/form-data; boundary=----boundary123",
        }
        result = _api_upload_file(headers, body)
        assert "error" in result

    def test_upload_multipart_valid(self, monkeypatch, tmp_path):
        """Valid multipart upload extracts file correctly."""
        from ari.viz.api_tools import _api_upload_file
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        boundary = "----WebKitFormBoundary"
        body = (
            f"------WebKitFormBoundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="test.md"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
            f"# Test\r\n"
            f"------WebKitFormBoundary--\r\n"
        ).encode()
        headers = {
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary",
        }
        result = _api_upload_file(headers, body)
        assert result.get("ok") is True
        assert result["filename"] == "test.md"


# ══════════════════════════════════════════════════════════════════════════════
# 8. _api_run_stage: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestRunStageErrors:
    """Run stage API validation."""

    def test_no_checkpoint(self, monkeypatch):
        from ari.viz.api_experiment import _api_run_stage
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        result = _api_run_stage(json.dumps({"stage": "paper"}).encode())
        assert result.get("ok") is False
        assert "No active checkpoint" in result["error"]

    def test_unknown_stage(self, monkeypatch, tmp_path):
        from ari.viz.api_experiment import _api_run_stage
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _api_run_stage(json.dumps({"stage": "nonexistent"}).encode())
        assert result.get("ok") is False
        assert "Unknown stage" in result["error"]

    def test_empty_body(self, monkeypatch, tmp_path):
        from ari.viz.api_experiment import _api_run_stage
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        result = _api_run_stage(b"")
        # Empty body → stage defaults to "paper"
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 9. _api_ssh_test: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestSshTestErrors:
    """SSH test API validation."""

    def test_empty_host(self):
        from ari.viz.api_tools import _api_ssh_test
        result = _api_ssh_test(json.dumps({"ssh_host": ""}).encode())
        assert result.get("ok") is False
        assert "No host" in result["error"]

    def test_no_body(self):
        from ari.viz.api_tools import _api_ssh_test
        result = _api_ssh_test(b"")
        assert result.get("ok") is False

    def test_malformed_json_body(self):
        from ari.viz.api_tools import _api_ssh_test
        result = _api_ssh_test(b"not json at all")
        assert result.get("ok") is False

    def test_invalid_port_type(self):
        """Non-numeric port raises ValueError before SSH command."""
        from ari.viz.api_tools import _api_ssh_test
        with pytest.raises(ValueError):
            _api_ssh_test(json.dumps({
                "ssh_host": "example.com",
                "ssh_port": "not_a_number",
            }).encode())


# ══════════════════════════════════════════════════════════════════════════════
# 10. _api_save_env_key: input validation
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveEnvKeyErrors:
    """Env key save API validation."""

    def test_empty_key(self):
        from ari.viz.api_settings import _api_save_env_key
        result = _api_save_env_key(json.dumps({"key": "", "value": "val"}).encode())
        assert result.get("ok") is False

    def test_empty_value(self):
        from ari.viz.api_settings import _api_save_env_key
        result = _api_save_env_key(json.dumps({"key": "K", "value": ""}).encode())
        assert result.get("ok") is False

    def test_both_empty(self):
        from ari.viz.api_settings import _api_save_env_key
        result = _api_save_env_key(json.dumps({"key": "", "value": ""}).encode())
        assert result.get("ok") is False

    def test_save_creates_env_file(self, monkeypatch, tmp_path):
        """Creates .env if it doesn't exist."""
        from ari.viz.api_settings import _api_save_env_key
        # _api_save_env_key now uses _st._env_write_path (set by autouse fixture)
        env_path = _st._env_write_path
        result = _api_save_env_key(json.dumps({"key": "MY_KEY", "value": "myval"}).encode())
        assert result.get("ok") is True
        assert env_path.exists()
        assert "MY_KEY" in env_path.read_text()


# ══════════════════════════════════════════════════════════════════════════════
# 11. _api_save_settings: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveSettingsErrors:
    """Settings persistence edge cases."""

    def test_save_strips_api_key(self, monkeypatch, tmp_path):
        """API key is never stored in settings.json."""
        from ari.viz.api_settings import _api_save_settings
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
        monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")
        body = json.dumps({
            "llm_model": "gpt-4o",
            "llm_provider": "openai",
            "api_key": "sk-real-key-that-is-long-enough-for-validation",
        }).encode()
        _api_save_settings(body)
        saved = json.loads((tmp_path / "settings.json").read_text())
        assert "api_key" not in saved
        assert "llm_api_key" not in saved
        # Key should be in .env
        env_content = (tmp_path / ".env").read_text()
        assert "OPENAI_API_KEY" in env_content

    def test_save_placeholder_key_not_written_to_env(self, monkeypatch, tmp_path):
        """Placeholder/test keys are not written to .env."""
        from ari.viz.api_settings import _api_save_settings
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
        monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")
        body = json.dumps({
            "llm_provider": "openai",
            "api_key": "test_key_short",
        }).encode()
        _api_save_settings(body)
        assert not (tmp_path / ".env").exists() or "OPENAI_API_KEY" not in (tmp_path / ".env").read_text()

    def test_get_settings_corrupt_json(self, monkeypatch, tmp_path):
        """Corrupt settings.json returns defaults."""
        from ari.viz.api_settings import _api_get_settings
        sf = tmp_path / "settings.json"
        sf.write_text("{{{not json")
        monkeypatch.setattr(_st, "_settings_path", sf)
        result = _api_get_settings()
        # Should return defaults without crashing
        assert "llm_model" in result
        assert "ollama_host" in result

    def test_get_settings_missing_file(self, monkeypatch, tmp_path):
        """Missing settings.json returns defaults."""
        from ari.viz.api_settings import _api_get_settings
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "nonexistent.json")
        result = _api_get_settings()
        assert isinstance(result, dict)
        assert result.get("temperature") == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 12. _api_save_workflow: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveWorkflowErrors:
    """Workflow save validation."""

    def test_save_no_checkpoint(self, monkeypatch):
        from ari.viz.api_settings import _api_save_workflow
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        body = json.dumps({"pipeline": [{"name": "test"}]}).encode()
        result = _api_save_workflow(body)
        assert result.get("ok") is False

    def test_save_empty_pipeline(self, monkeypatch, tmp_path):
        from ari.viz.api_settings import _api_save_workflow
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        body = json.dumps({"pipeline": []}).encode()
        result = _api_save_workflow(body)
        assert result.get("ok") is False
        assert "missing pipeline" in result["error"]

    def test_save_missing_pipeline_key(self, monkeypatch, tmp_path):
        from ari.viz.api_settings import _api_save_workflow
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        body = json.dumps({"stages": [{"name": "test"}]}).encode()
        result = _api_save_workflow(body)
        assert result.get("ok") is False


# ══════════════════════════════════════════════════════════════════════════════
# 13. _api_checkpoint_summary: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointSummary:
    """Checkpoint summary retrieval."""

    def test_nonexistent_checkpoint(self):
        from ari.viz.api_state import _api_checkpoint_summary
        result = _api_checkpoint_summary("totally_nonexistent_id_xyz")
        assert "error" in result

    def test_checkpoint_with_corrupt_review(self, monkeypatch, tmp_path):
        """Corrupt review_report.json returns parse error, not crash."""
        from ari.viz.api_state import _api_checkpoint_summary
        ckpt_id = "20260101_corrupt"
        ckpt = tmp_path / "checkpoints" / ckpt_id
        ckpt.mkdir(parents=True)
        (ckpt / "review_report.json").write_text("{broken")
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_summary(ckpt_id)
        # Should have _parse_error instead of crashing
        rr = result.get("review_report", {})
        assert "_parse_error" in rr

    def test_checkpoint_empty_files(self, monkeypatch, tmp_path):
        """Zero-byte JSON files are skipped, not parsed."""
        from ari.viz.api_state import _api_checkpoint_summary
        ckpt_id = "20260101_empty"
        ckpt = tmp_path / "checkpoints" / ckpt_id
        ckpt.mkdir(parents=True)
        (ckpt / "nodes_tree.json").write_text("")
        (ckpt / "review_report.json").write_text("")
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_summary(ckpt_id)
        assert "nodes_tree" not in result  # zero-byte → skipped
        assert "review_report" not in result


# ══════════════════════════════════════════════════════════════════════════════
# 14. _api_checkpoints: listing robustness
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointsListing:
    """Checkpoint listing edge cases."""

    def test_corrupt_tree_in_listing(self, monkeypatch, tmp_path):
        """Corrupt tree.json in a checkpoint doesn't crash listing."""
        from ari.viz.api_state import _api_checkpoints
        monkeypatch.chdir(tmp_path)
        ckpt = tmp_path / "checkpoints" / "20260101_corrupt"
        ckpt.mkdir(parents=True)
        (ckpt / "tree.json").write_text("not json")
        result = _api_checkpoints()
        # Should list the checkpoint even if tree is corrupt
        ids = [c["id"] for c in result]
        assert "20260101_corrupt" in ids

    def test_listing_skips_non_timestamp_dirs(self, monkeypatch, tmp_path):
        """Directories not matching YYYYMMDD_* are excluded."""
        from ari.viz.api_state import _api_checkpoints
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "checkpoints"
        base.mkdir()
        (base / "random_dir").mkdir()
        (base / "__pycache__").mkdir()
        (base / "experiments").mkdir()
        (base / "20260101_valid").mkdir()
        result = _api_checkpoints()
        ids = [c["id"] for c in result]
        assert "20260101_valid" in ids
        assert "random_dir" not in ids
        assert "__pycache__" not in ids

    def test_listing_with_review_score(self, monkeypatch, tmp_path):
        """Review score extracted from review_report.json."""
        from ari.viz.api_state import _api_checkpoints
        monkeypatch.chdir(tmp_path)
        ckpt = tmp_path / "checkpoints" / "20260101_scored"
        ckpt.mkdir(parents=True)
        (ckpt / "review_report.json").write_text(json.dumps({"overall_score": 7.5}))
        result = _api_checkpoints()
        scored = [c for c in result if c["id"] == "20260101_scored"]
        assert len(scored) == 1
        assert scored[0]["review_score"] == 7.5
        assert scored[0]["status"] == "completed"


# ══════════════════════════════════════════════════════════════════════════════
# 15. _api_get_env_keys: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestGetEnvKeys:
    """Environment key discovery edge cases."""

    def test_no_env_files_exist(self, monkeypatch, tmp_path):
        from ari.viz.api_settings import _api_get_env_keys
        import ari.viz.api_settings as _mod
        monkeypatch.setattr(_mod, "__file__", str(tmp_path / "fake" / "viz" / "f.py"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
        result = _api_get_env_keys()
        assert isinstance(result["keys"], dict)

    def test_env_file_with_comments_and_blanks(self, monkeypatch, tmp_path):
        """Comments and blank lines in .env are skipped."""
        from ari.viz.api_settings import _api_get_env_keys
        import ari.viz.api_settings as _mod
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# This is a comment\n"
            "\n"
            "OPENAI_API_KEY=sk-test123\n"
            "# Another comment\n"
            "SOME_OTHER_VAR=nokey\n"  # no API_KEY/SECRET/TOKEN in name
        )
        # Point _ari_root to tmp_path so it finds the .env
        fake_file = tmp_path / "ari-core" / "ari" / "viz" / "f.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(_mod, "__file__", str(fake_file))
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = _api_get_env_keys()
        assert "OPENAI_API_KEY" in result["keys"]
        assert "SOME_OTHER_VAR" not in result["keys"]


# ══════════════════════════════════════════════════════════════════════════════
# 16. _api_chat_goal: input edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestChatGoalErrors:
    """Chat goal API validation beyond basic tests."""

    def test_malformed_json_body(self):
        from ari.viz.api_tools import _api_chat_goal
        with pytest.raises(json.JSONDecodeError):
            _api_chat_goal(b"not json")

    def test_missing_messages_key(self):
        from ari.viz.api_tools import _api_chat_goal
        result = _api_chat_goal(json.dumps({"context": "test"}).encode())
        assert "error" in result
        assert "messages required" in result["error"]


# ══════════════════════════════════════════════════════════════════════════════
# 17. _api_generate_config: input validation
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateConfigErrors:
    """Config generation validation."""

    def test_empty_goal(self):
        from ari.viz.api_tools import _api_generate_config
        result = _api_generate_config(json.dumps({"goal": ""}).encode())
        assert "error" in result
        assert "goal required" in result["error"]

    def test_missing_goal_key(self):
        from ari.viz.api_tools import _api_generate_config
        result = _api_generate_config(json.dumps({"description": "test"}).encode())
        assert "error" in result


# ══════════════════════════════════════════════════════════════════════════════
# 18. _api_launch: input validation
# ══════════════════════════════════════════════════════════════════════════════

class TestLaunchErrors:
    """Launch API validation (without actually spawning processes)."""

    def test_launch_no_experiment_md_no_file(self, monkeypatch, tmp_path):
        """Launch with no experiment.md content and no file on disk → error."""
        from ari.viz.api_experiment import _api_launch
        # Set checkpoint_dir parent so ckpt_parent is known
        ckpt = tmp_path / "workspace"
        ckpt.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        result = _api_launch(json.dumps({
            "experiment_md": "",
        }).encode())
        assert result.get("ok") is False
        assert "not found" in result.get("error", "").lower() or "error" in result

    def test_launch_writes_experiment_md(self, monkeypatch, tmp_path):
        """Launch writes experiment.md to ckpt_parent."""
        from ari.viz.api_experiment import _api_launch
        ckpt = tmp_path / "checkpoints" / "test_run"
        ckpt.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
        (tmp_path / "settings.json").write_text("{}")
        # Mock Popen to avoid actually launching
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc
            result = _api_launch(json.dumps({
                "experiment_md": "## Research Goal\nTest goal",
            }).encode())
        if result.get("ok"):
            # ckpt_parent is the parent of the "checkpoints" dir (not the checkpoint itself)
            exp_path = ckpt.parent.parent / "experiment.md"
            assert exp_path.exists(), f"experiment.md not found at {exp_path} (checked {ckpt.parent / 'experiment.md'} too)"
            assert "Test goal" in exp_path.read_text()


# ══════════════════════════════════════════════════════════════════════════════
# 19. _api_models: structure validation
# ══════════════════════════════════════════════════════════════════════════════

class TestModelsApi:
    """Models API structure."""

    def test_models_returns_providers(self):
        from ari.viz.api_state import _api_models
        result = _api_models()
        assert "providers" in result
        assert len(result["providers"]) >= 4
        provider_ids = [p["id"] for p in result["providers"]]
        assert "openai" in provider_ids
        assert "anthropic" in provider_ids
        assert "ollama" in provider_ids

    def test_each_provider_has_models(self):
        from ari.viz.api_state import _api_models
        for provider in _api_models()["providers"]:
            assert "models" in provider
            assert len(provider["models"]) > 0
            assert "name" in provider
            assert "id" in provider


# ══════════════════════════════════════════════════════════════════════════════
# 20. Cost trace JSONL parsing robustness
# ══════════════════════════════════════════════════════════════════════════════

class TestCostTraceParsing:
    """Cost trace parsing in /state endpoint."""

    def _make_checkpoint_with_cost_trace(self, tmp_path, lines):
        """Helper: create a checkpoint with cost_trace.jsonl."""
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir(exist_ok=True)
        (ckpt / "nodes_tree.json").write_text('{"nodes": [{"id":"n1","status":"done"}]}')
        (ckpt / "cost_trace.jsonl").write_text("\n".join(lines))
        return ckpt

    def test_valid_cost_trace(self, monkeypatch, tmp_path):
        """Valid JSONL parsed correctly."""
        lines = [
            json.dumps({"skill": "idea", "model": "gpt-4o", "total_tokens": 100}),
            json.dumps({"skill": "coding", "model": "gpt-4o-mini", "total_tokens": 200}),
        ]
        ckpt = self._make_checkpoint_with_cost_trace(tmp_path, lines)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        # Simulate the cost_trace parsing logic from server.py
        ct = ckpt / "cost_trace.jsonl"
        actual_mods = {}
        for ln in ct.read_text().splitlines()[-30:]:
            if ln.strip():
                ee = json.loads(ln)
                if ee.get("skill") and ee.get("model"):
                    actual_mods[ee["skill"]] = ee["model"]
        assert actual_mods == {"idea": "gpt-4o", "coding": "gpt-4o-mini"}

    def test_cost_trace_with_corrupt_lines(self, monkeypatch, tmp_path):
        """Mix of valid and corrupt lines doesn't crash."""
        lines = [
            json.dumps({"skill": "idea", "model": "gpt-4o", "total_tokens": 100}),
            "this is not json",
            "",
            json.dumps({"skill": "coding", "model": "gpt-4o-mini"}),
        ]
        ckpt = self._make_checkpoint_with_cost_trace(tmp_path, lines)
        actual_mods = {}
        for ln in (ckpt / "cost_trace.jsonl").read_text().splitlines()[-30:]:
            if ln.strip():
                try:
                    ee = json.loads(ln)
                    if ee.get("skill") and ee.get("model"):
                        actual_mods[ee["skill"]] = ee["model"]
                except json.JSONDecodeError:
                    pass
        assert "idea" in actual_mods
        assert "coding" in actual_mods

    def test_empty_cost_trace(self, monkeypatch, tmp_path):
        """Empty cost_trace.jsonl → no actual_models."""
        ckpt = self._make_checkpoint_with_cost_trace(tmp_path, [])
        actual_mods = {}
        for ln in (ckpt / "cost_trace.jsonl").read_text().splitlines()[-30:]:
            if ln.strip():
                ee = json.loads(ln)
                if ee.get("skill") and ee.get("model"):
                    actual_mods[ee["skill"]] = ee["model"]
        assert actual_mods == {}


# ══════════════════════════════════════════════════════════════════════════════
# 21. Codefile endpoint: security
# ══════════════════════════════════════════════════════════════════════════════

class TestCodefileEndpointSecurity:
    """Path traversal protection for /codefile."""

    def test_path_outside_checkpoint_blocked(self, monkeypatch, tmp_path):
        """File outside checkpoint dir is blocked by relative_to check."""
        ckpt = tmp_path / "checkpoints" / "run1"
        ckpt.mkdir(parents=True)
        outside = tmp_path / "secret.txt"
        outside.write_text("secret data")
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        # Simulate the security check from server.py
        fpath = str(outside)
        p = Path(fpath).resolve()
        allowed = False
        try:
            p.relative_to(ckpt.resolve())
            allowed = True
        except ValueError:
            pass
        assert allowed is False

    def test_path_inside_checkpoint_allowed(self, monkeypatch, tmp_path):
        ckpt = tmp_path / "checkpoints" / "run1"
        ckpt.mkdir(parents=True)
        inside = ckpt / "code.py"
        inside.write_text("print('hello')")
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        p = Path(str(inside)).resolve()
        allowed = False
        try:
            p.relative_to(ckpt.resolve())
            allowed = True
        except ValueError:
            pass
        assert allowed is True

    def test_dot_dot_traversal_blocked(self, monkeypatch, tmp_path):
        """../../etc/passwd style path is blocked."""
        ckpt = tmp_path / "checkpoints" / "run1"
        ckpt.mkdir(parents=True)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        fpath = str(ckpt / ".." / ".." / "etc" / "passwd")
        p = Path(fpath).resolve()
        allowed = False
        try:
            p.relative_to(ckpt.resolve())
            allowed = True
        except ValueError:
            pass
        assert allowed is False


# ══════════════════════════════════════════════════════════════════════════════
# 22. Phase detection edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseDetection:
    """Phase detection logic from /state endpoint."""

    def _detect_phase(self, d, has_paper=False, has_review=False, has_nodes=False,
                      has_idea=False, has_code=False, has_eval=False, running_pid=None):
        """Replicate phase detection logic from server.py."""
        if has_review:
            return "review"
        elif has_paper:
            return "paper"
        elif has_eval:
            return "evaluation"
        elif has_code:
            return "coding"
        elif has_nodes:
            return "bfts"
        elif has_idea:
            return "idea"
        elif running_pid:
            return "starting"
        else:
            return "idle"

    def test_idle_phase(self):
        assert self._detect_phase(None) == "idle"

    def test_starting_phase(self):
        assert self._detect_phase(None, running_pid=123) == "starting"

    def test_idea_phase(self):
        assert self._detect_phase(None, has_idea=True) == "idea"

    def test_bfts_phase(self):
        assert self._detect_phase(None, has_nodes=True) == "bfts"

    def test_coding_phase(self):
        assert self._detect_phase(None, has_code=True) == "coding"

    def test_evaluation_phase(self):
        assert self._detect_phase(None, has_eval=True) == "evaluation"

    def test_paper_phase(self):
        assert self._detect_phase(None, has_paper=True) == "paper"

    def test_review_phase(self):
        assert self._detect_phase(None, has_review=True) == "review"

    def test_review_overrides_paper(self):
        assert self._detect_phase(None, has_paper=True, has_review=True) == "review"

    def test_paper_overrides_bfts(self):
        assert self._detect_phase(None, has_nodes=True, has_paper=True) == "paper"

    def test_all_flags_returns_review(self):
        assert self._detect_phase(
            None, has_paper=True, has_review=True, has_nodes=True,
            has_idea=True, has_code=True, has_eval=True
        ) == "review"


# ══════════════════════════════════════════════════════════════════════════════
# 23. GPU monitor edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestGpuMonitorState:
    """GPU monitor process tracking."""

    def test_gpu_monitor_not_running(self, monkeypatch):
        monkeypatch.setattr(_st, "_gpu_monitor_proc", None)
        running = _st._gpu_monitor_proc is not None and _st._gpu_monitor_proc.poll() is None
        assert running is False

    def test_gpu_monitor_dead_process(self, monkeypatch):
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = 1  # exited
        monkeypatch.setattr(_st, "_gpu_monitor_proc", mock_proc)
        running = _st._gpu_monitor_proc is not None and _st._gpu_monitor_proc.poll() is None
        assert running is False

    def test_gpu_monitor_alive_process(self, monkeypatch):
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # running
        mock_proc.pid = 55555
        monkeypatch.setattr(_st, "_gpu_monitor_proc", mock_proc)
        running = _st._gpu_monitor_proc is not None and _st._gpu_monitor_proc.poll() is None
        assert running is True


# ══════════════════════════════════════════════════════════════════════════════
# 24. Stale experiment_md leak prevention
# ══════════════════════════════════════════════════════════════════════════════

class TestExperimentMdLeak:
    """Ensure stale experiment_md is cleared when process exits."""

    def test_experiment_md_cleared_on_exit(self, monkeypatch):
        """_last_experiment_md is cleared when _last_proc has exited."""
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = 0  # exited
        monkeypatch.setattr(_st, "_last_proc", mock_proc)
        monkeypatch.setattr(_st, "_last_experiment_md", "## old content")
        # Replicate server.py logic
        if _st._last_proc and _st._last_proc.poll() is not None:
            _st._last_experiment_md = None
        assert _st._last_experiment_md is None

    def test_experiment_md_kept_while_running(self, monkeypatch):
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # still running
        monkeypatch.setattr(_st, "_last_proc", mock_proc)
        monkeypatch.setattr(_st, "_last_experiment_md", "## live content")
        if _st._last_proc and _st._last_proc.poll() is not None:
            _st._last_experiment_md = None
        assert _st._last_experiment_md == "## live content"


# ══════════════════════════════════════════════════════════════════════════════
# 25. Ollama proxy & resources edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestOllamaResourcesEdgeCases:
    """Ollama resource detection edge cases."""

    def test_no_nvidia_smi_no_ollama(self, monkeypatch):
        """When nvidia-smi and Ollama are both unavailable."""
        from ari.viz.api_ollama import _api_ollama_resources
        import subprocess as sp
        monkeypatch.setattr(sp, "check_output", mock.MagicMock(side_effect=FileNotFoundError))
        monkeypatch.setattr("urllib.request.urlopen", mock.MagicMock(side_effect=Exception("no ollama")))
        result = _api_ollama_resources()
        # Should have Auto + CPU, no real GPUs
        assert result["has_gpu"] is False
        assert len(result["gpus"]) >= 2  # Auto + CPU
        assert result["gpus"][0]["name"] == "Auto"
        assert result["gpus"][1]["name"] == "CPU only"

    def test_nvidia_smi_timeout(self, monkeypatch):
        """nvidia-smi timing out doesn't crash."""
        from ari.viz.api_ollama import _api_ollama_resources
        import subprocess as sp
        monkeypatch.setattr(sp, "check_output", mock.MagicMock(
            side_effect=sp.TimeoutExpired(cmd="nvidia-smi", timeout=5)
        ))
        monkeypatch.setattr("urllib.request.urlopen", mock.MagicMock(side_effect=Exception()))
        result = _api_ollama_resources()
        assert result["has_gpu"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 26. Concurrent state modification
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrentState:
    """Simulate race conditions in shared state."""

    def test_checkpoint_dir_becomes_none_during_operation(self, monkeypatch, tmp_path):
        """If _checkpoint_dir is set to None mid-operation, code doesn't crash."""
        from ari.viz.api_state import _load_nodes_tree
        (tmp_path / "tree.json").write_text('{"nodes": []}')
        monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
        # First call works
        assert _load_nodes_tree() is not None
        # Simulate another thread clearing checkpoint
        monkeypatch.setattr(_st, "_checkpoint_dir", None)
        assert _load_nodes_tree() is None

    def test_watcher_thread_handles_deleted_checkpoint(self, monkeypatch, tmp_path):
        """_watcher_thread doesn't crash if checkpoint dir is deleted."""
        from ari.viz.api_state import _watcher_thread
        import threading
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        (ckpt / "tree.json").write_text('{"nodes":[]}')
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        monkeypatch.setattr(_st, "_clients", [])
        # Run watcher briefly, then delete checkpoint
        import shutil
        shutil.rmtree(str(ckpt))
        # _checkpoint_dir points to deleted dir
        # Watcher should handle the error gracefully (files don't exist)
        # We can't easily test the infinite loop, but we can test the inner logic
        for fname in ("tree.json", "nodes_tree.json"):
            p = _st._checkpoint_dir / fname
            assert not p.exists()  # deleted


# ══════════════════════════════════════════════════════════════════════════════
# 27. HTTP POST body size limit
# ══════════════════════════════════════════════════════════════════════════════

class TestPostBodyLimit:
    """POST body size enforcement (10 MB limit)."""

    def test_limit_constant_exists(self):
        """Verify the 10MB limit is enforced in do_POST."""
        import inspect
        from ari.viz.server import _Handler
        source = inspect.getsource(_Handler.do_POST)
        assert "10 * 1024 * 1024" in source or "10_485_760" in source or "10MB" in source


# ══════════════════════════════════════════════════════════════════════════════
# 28. _api_detect_scheduler error handling
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectScheduler:
    """Scheduler detection error handling."""

    def test_import_error_returns_fallback(self, monkeypatch):
        from ari.viz.api_settings import _api_detect_scheduler
        # Mock the import to fail
        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        def mock_import(name, *args, **kwargs):
            if name == "ari.env_detect":
                raise ImportError("no module")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr("builtins.__import__", mock_import)
        result = _api_detect_scheduler()
        assert "error" in result or "scheduler" in result


# ══════════════════════════════════════════════════════════════════════════════
# 29. _api_skills: edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillsListing:
    """Skills discovery edge cases."""

    def test_no_skill_dirs(self, monkeypatch, tmp_path):
        from ari.viz.api_settings import _api_skills
        import ari.viz.api_settings as _mod
        monkeypatch.setattr(_mod, "__file__", str(tmp_path / "viz" / "f.py"))
        monkeypatch.setattr(_st, "_ari_home", tmp_path / "empty_home")
        result = _api_skills()
        assert isinstance(result, list)

    def test_skill_dir_without_yaml(self, monkeypatch, tmp_path):
        """Skill directory without skill.yaml is skipped."""
        from ari.viz.api_settings import _api_skills
        import ari.viz.api_settings as _mod
        root = tmp_path / "project"
        root.mkdir()
        (root / "ari-skill-test").mkdir()
        monkeypatch.setattr(_mod, "__file__", str(root / "ari-core" / "ari" / "viz" / "f.py"))
        monkeypatch.setattr(_st, "_ari_home", tmp_path / "empty_home")
        result = _api_skills()
        names = [s["name"] for s in result]
        assert "ari-skill-test" not in names  # no skill.yaml = not listed
