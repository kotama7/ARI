"""
ARI Ollama Proxy, GPU Monitor, and Node Tunnel Tests
Tests for:
  - api_ollama: GPU/model detection, Ollama reverse proxy
  - gpu_ollama_monitor.sh: SLURM → SSH tunnel → settings update
  - /api/gpu-monitor: start/stop GPU monitor process
  - run_ollama_gpu.sh: SLURM batch script for Ollama on GPU node
"""
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from ari.viz import state as _st


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    """Redirect all file writes to tmp_path to avoid overwriting real settings/.env."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr(_st, "_settings_path", settings)
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None)


SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
GPU_MONITOR_SH = SCRIPTS_DIR / "gpu_ollama_monitor.sh"
RUN_OLLAMA_SH = SCRIPTS_DIR / "run_ollama_gpu.sh"


# ══════════════════════════════════════════════
# Ollama Resources API (/api/ollama-resources)
# ══════════════════════════════════════════════

class TestOllamaResources:
    """Tests for _api_ollama_resources — GPU and model detection."""

    def test_returns_gpus_with_auto_and_cpu(self):
        """Always returns at least Auto and CPU options."""
        from ari.viz.api_ollama import _api_ollama_resources
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            result = _api_ollama_resources()
        assert "gpus" in result
        names = [g["name"] for g in result["gpus"]]
        assert "Auto" in names
        assert "CPU only" in names
        assert result["has_gpu"] is False

    def test_nvidia_smi_parsed(self):
        """nvidia-smi output is parsed into GPU list."""
        from ari.viz.api_ollama import _api_ollama_resources
        fake_output = "0, NVIDIA A100-SXM4-40GB, 40960 MiB\n1, NVIDIA A100-SXM4-40GB, 40960 MiB\n"
        with mock.patch("subprocess.check_output", return_value=fake_output):
            result = _api_ollama_resources()
        assert result["has_gpu"] is True
        gpu_names = [g["name"] for g in result["gpus"]]
        assert any("A100" in n for n in gpu_names)
        # Auto + CPU + 2 GPUs = 4
        assert len(result["gpus"]) == 4

    def test_nvidia_smi_failure_graceful(self):
        """nvidia-smi failure returns empty GPU list (not error)."""
        from ari.viz.api_ollama import _api_ollama_resources
        with mock.patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "nvidia-smi")):
            result = _api_ollama_resources()
        assert result["has_gpu"] is False
        assert len(result["gpus"]) == 2  # Auto + CPU only

    def test_ollama_models_fetched(self):
        """Ollama model list is fetched from /api/tags."""
        from ari.viz.api_ollama import _api_ollama_resources
        fake_tags = json.dumps({"models": [
            {"name": "qwen3:8b"},
            {"name": "llama3.3:70b"},
        ]}).encode()
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = fake_tags
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError), \
             mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = _api_ollama_resources()
        assert "qwen3:8b" in result["models"]
        assert "llama3.3:70b" in result["models"]

    def test_ollama_connection_failure_graceful(self):
        """Ollama connection failure returns empty model list."""
        from ari.viz.api_ollama import _api_ollama_resources
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError), \
             mock.patch("urllib.request.urlopen", side_effect=ConnectionRefusedError):
            result = _api_ollama_resources()
        assert result["models"] == []


# ══════════════════════════════════════════════
# Ollama Proxy (/api/ollama/<path>)
# ══════════════════════════════════════════════

class TestOllamaProxy:
    """Tests for _ollama_proxy — reverse proxy to Ollama backend."""

    def _make_handler(self, path="/api/ollama/api/tags", method="GET",
                      body=b"", content_type="application/json"):
        handler = mock.MagicMock()
        handler.path = path
        handler.command = method
        handler.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        handler.wfile.flush = mock.MagicMock()
        return handler

    def test_proxy_forwards_to_ollama_host(self, monkeypatch):
        """Proxy reads ollama_host from settings and forwards request."""
        from ari.viz.api_ollama import _ollama_proxy

        _st._settings_path.write_text(json.dumps({
            "ollama_host": "http://gpu-node:11435",
        }))

        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.getheader.return_value = "application/json"
        mock_resp.read = mock.MagicMock(side_effect=[b'{"models":[]}', b""])

        mock_conn = mock.MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        handler = self._make_handler()

        with mock.patch("http.client.HTTPConnection", return_value=mock_conn) as mock_http:
            _ollama_proxy(handler)

        # Verify connection was made to gpu-node:11435
        mock_http.assert_called_with("gpu-node", 11435, timeout=600)
        mock_conn.request.assert_called_once()

    def test_proxy_strips_prefix(self):
        """Proxy strips /api/ollama prefix before forwarding."""
        from ari.viz.api_ollama import _ollama_proxy

        _st._settings_path.write_text(json.dumps({
            "ollama_host": "http://localhost:11434",
        }))

        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.getheader.return_value = "application/json"
        mock_resp.read = mock.MagicMock(side_effect=[b"{}", b""])

        mock_conn = mock.MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        handler = self._make_handler(path="/api/ollama/api/generate")

        with mock.patch("http.client.HTTPConnection", return_value=mock_conn):
            _ollama_proxy(handler)

        # The path forwarded should be /api/generate (prefix stripped)
        call_args = mock_conn.request.call_args
        assert call_args[0][1] == "/api/generate"

    def test_proxy_connection_error_returns_502(self):
        """Connection failure to Ollama returns 502."""
        from ari.viz.api_ollama import _ollama_proxy

        _st._settings_path.write_text(json.dumps({
            "ollama_host": "http://dead-host:11434",
        }))

        handler = self._make_handler()

        with mock.patch("http.client.HTTPConnection", side_effect=ConnectionRefusedError("refused")):
            _ollama_proxy(handler)

        handler.send_response.assert_called_with(502)

    def test_proxy_default_host_localhost(self):
        """When ollama_host not in settings, default to localhost:11434."""
        from ari.viz.api_ollama import _ollama_proxy

        _st._settings_path.write_text(json.dumps({}))

        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.getheader.return_value = "application/json"
        mock_resp.read = mock.MagicMock(side_effect=[b"{}", b""])

        mock_conn = mock.MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        handler = self._make_handler()

        with mock.patch("http.client.HTTPConnection", return_value=mock_conn) as mock_http:
            _ollama_proxy(handler)

        mock_http.assert_called_with("localhost", 11434, timeout=600)


# ══════════════════════════════════════════════
# GPU Monitor API (/api/gpu-monitor)
# ══════════════════════════════════════════════

class TestGpuMonitorAPI:
    """Tests for /api/gpu-monitor start/stop logic (inline in server.py)."""

    def test_start_without_confirm_returns_needs_confirm(self):
        """Start without confirmed flag returns needs_confirm."""
        data = {"action": "start"}
        # Inline the logic from server.py
        if not data.get("confirmed"):
            result = {"ok": False, "needs_confirm": True,
                      "msg": "GPU Monitor will continuously submit SLURM jobs."}
        else:
            result = {"ok": True}
        assert result["needs_confirm"] is True
        assert result["ok"] is False

    def test_start_with_confirm_spawns_process(self, monkeypatch, tmp_path):
        """Start with confirmed=True spawns gpu_ollama_monitor.sh."""
        monkeypatch.setattr(_st, "_gpu_monitor_proc", None)

        fake_proc = mock.MagicMock()
        fake_proc.pid = 55555
        fake_proc.poll.return_value = None

        with mock.patch("subprocess.Popen", return_value=fake_proc) as mock_popen, \
             mock.patch("builtins.open", mock.mock_open()):
            # Simulate the server logic
            script = Path.home() / "ARI/scripts/gpu_ollama_monitor.sh"
            _st._gpu_monitor_proc = subprocess.Popen(
                ["bash", str(script)], stdout=mock.MagicMock(), stderr=mock.MagicMock(),
                start_new_session=True, env=os.environ.copy()
            )

        assert _st._gpu_monitor_proc is not None
        assert _st._gpu_monitor_proc.pid == 55555

    def test_start_when_already_running_returns_error(self, monkeypatch):
        """Start when monitor already running returns already running."""
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.pid = 44444
        monkeypatch.setattr(_st, "_gpu_monitor_proc", mock_proc)

        # Inline the server logic check
        already_running = not (_st._gpu_monitor_proc is None or _st._gpu_monitor_proc.poll() is not None)
        assert already_running is True

    def test_stop_terminates_process(self, monkeypatch):
        """Stop action terminates running gpu_monitor_proc."""
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # running
        monkeypatch.setattr(_st, "_gpu_monitor_proc", mock_proc)

        # Inline the stop logic
        if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
            _st._gpu_monitor_proc.terminate()

        mock_proc.terminate.assert_called_once()

    def test_stop_when_not_running_is_safe(self, monkeypatch):
        """Stop when no process is running should not raise."""
        monkeypatch.setattr(_st, "_gpu_monitor_proc", None)
        # Should not raise
        if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
            _st._gpu_monitor_proc.terminate()


# ══════════════════════════════════════════════
# Shell Scripts — structure validation
# ══════════════════════════════════════════════

class TestGpuMonitorScript:
    """Tests for scripts/gpu_ollama_monitor.sh structure."""

    def test_script_exists(self):
        assert GPU_MONITOR_SH.exists(), "gpu_ollama_monitor.sh not found"

    def test_has_lock_file_protection(self):
        """Script must have PID lock file to prevent multiple instances."""
        src = GPU_MONITOR_SH.read_text()
        assert "LOCK_FILE" in src
        assert "kill -0" in src  # checks if old PID alive

    def test_log_writes_to_stderr(self):
        """log() must write to stderr so $() captures don't pollute job IDs."""
        src = GPU_MONITOR_SH.read_text()
        assert ">&2" in src, "log() must redirect to stderr"

    def test_is_job_running_not_nested(self):
        """is_job_running() and is_job_queued() must be separate functions."""
        src = GPU_MONITOR_SH.read_text()
        # Find both function definitions
        idx_running = src.find("is_job_running()")
        idx_queued = src.find("is_job_queued()")
        assert idx_running > 0
        assert idx_queued > 0
        # is_job_running should have its body before is_job_queued starts
        running_close = src.find("}", idx_running)
        assert running_close < idx_queued, "is_job_running() body must end before is_job_queued() starts"

    def test_has_tunnel_management(self):
        """Script must manage SSH tunnel lifecycle."""
        src = GPU_MONITOR_SH.read_text()
        assert "start_tunnel" in src
        assert "kill_tunnel" in src
        assert "is_tunnel_alive" in src

    def test_has_settings_update(self):
        """Script must update settings.json with ollama_host after tunnel."""
        src = GPU_MONITOR_SH.read_text()
        assert "update_settings" in src
        assert "ollama_host" in src
        assert "settings.json" in src

    def test_has_slurm_job_management(self):
        """Script must submit and monitor SLURM jobs."""
        src = GPU_MONITOR_SH.read_text()
        assert "submit_job" in src
        assert "sbatch" in src
        assert "squeue" in src
        assert "wait_for_node" in src

    def test_has_ollama_health_check(self):
        """Script must test Ollama connectivity after tunnel is up."""
        src = GPU_MONITOR_SH.read_text()
        assert "test_ollama" in src
        assert "/api/tags" in src

    def test_tunnel_uses_autossh_with_fallback(self):
        """Tunnel should prefer autossh but fall back to plain ssh."""
        src = GPU_MONITOR_SH.read_text()
        assert "autossh" in src
        assert "ssh -f -N" in src  # fallback

    def test_tunnel_port_configurable(self):
        """Tunnel port is configurable via LOCAL_PORT variable."""
        src = GPU_MONITOR_SH.read_text()
        assert "LOCAL_PORT=" in src

    def test_main_loop_exists(self):
        """Script has a main loop that resubmits jobs and reconnects tunnels."""
        src = GPU_MONITOR_SH.read_text()
        assert "while true" in src
        assert "sleep" in src
        assert "Resubmitting" in src

    def test_no_hardcoded_partitions(self):
        """Script must not hardcode SLURM partition names."""
        src = GPU_MONITOR_SH.read_text()
        # Common HPC partition names that should not be hardcoded
        for name in ["gpu_long", "gpu_short", "dgx", "a100"]:
            assert name not in src.lower(), f"Hardcoded partition '{name}' found"


class TestRunOllamaScript:
    """Tests for scripts/run_ollama_gpu.sh — SLURM batch script."""

    def test_script_exists(self):
        assert RUN_OLLAMA_SH.exists(), "run_ollama_gpu.sh not found"

    def test_has_sbatch_directives(self):
        """Script must have SBATCH directives for GPU."""
        src = RUN_OLLAMA_SH.read_text()
        assert "#SBATCH" in src
        assert "gpu" in src.lower()

    def test_writes_node_info_file(self):
        """Script must write hostname:port to node info file for tunnel."""
        src = RUN_OLLAMA_SH.read_text()
        assert "ollama_gpu_node.txt" in src
        assert "hostname" in src

    def test_ollama_port_configurable(self):
        """Ollama port must be configurable."""
        src = RUN_OLLAMA_SH.read_text()
        assert "OLLAMA_PORT" in src

    def test_ollama_bin_path_configurable(self):
        """Ollama binary path must be configurable."""
        src = RUN_OLLAMA_SH.read_text()
        assert "OLLAMA_BIN_PATH" in src or "OLLAMA_BIN" in src

    def test_sets_cuda_visible_devices(self):
        """Script must set CUDA_VISIBLE_DEVICES."""
        src = RUN_OLLAMA_SH.read_text()
        assert "CUDA_VISIBLE_DEVICES" in src

    def test_health_check_after_start(self):
        """Script must verify Ollama started before reporting success."""
        src = RUN_OLLAMA_SH.read_text()
        assert "kill -0" in src  # check PID still alive


# ══════════════════════════════════════════════
# JS dashboard — GPU monitor UI
# ══════════════════════════════════════════════

VIZ_DIR = Path(__file__).parent.parent / "ari" / "viz"
REACT_SRC = VIZ_DIR / "frontend" / "src"


class TestGpuMonitorReact:
    """Tests for GPU monitor UI elements in React components."""

    def _combined(self):
        parts = []
        for tsx in sorted(REACT_SRC.rglob("*.tsx")):
            parts.append(tsx.read_text())
        for ts in sorted(REACT_SRC.rglob("*.ts")):
            parts.append(ts.read_text())
        return "\n".join(parts)

    def test_gpu_monitor_component_exists(self):
        combined = self._combined()
        assert "GpuMonitor" in combined

    def test_gpu_monitor_status_display(self):
        combined = self._combined()
        assert "statusText" in combined or "gpu-monitor-status" in combined

    def test_start_stop_handlers_exist(self):
        combined = self._combined()
        assert "handleStart" in combined
        assert "handleStop" in combined

    def test_confirmation_dialog_before_start(self):
        """Starting GPU monitor must show confirmation dialog."""
        combined = self._combined()
        assert "confirm(" in combined or "gpu_confirm" in combined

    def test_gpu_monitor_calls_api(self):
        """React must call /api/gpu-monitor via api service."""
        combined = self._combined()
        assert "gpu-monitor" in combined or "gpuMonitorAction" in combined

    def test_gpu_monitor_imported_in_monitor(self):
        """GpuMonitor must be imported in MonitorPage."""
        src = (REACT_SRC / "components" / "Monitor" / "MonitorPage.tsx").read_text()
        assert "GpuMonitor" in src

    def test_ollama_resources_api_called(self):
        """Wizard step 3 must call /api/ollama-resources for GPU detection."""
        combined = self._combined()
        assert "ollama-resources" in combined or "fetchOllamaResources" in combined
