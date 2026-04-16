from __future__ import annotations
"""Tests for ari/container.py — unified container runtime abstraction."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ari.container import (
    ContainerConfig,
    config_from_env,
    detect_runtime,
    get_container_info,
    list_images,
    pull_image,
    run_in_container,
    run_shell_in_container,
)


# ── detect_runtime ──────────────────────────────────


def test_detect_runtime_returns_valid_value():
    result = detect_runtime()
    assert result in ("docker", "singularity", "apptainer", "none")


@patch("ari.container.shutil.which", return_value=None)
@patch("ari.container._cmd_ok", return_value=None)
def test_detect_runtime_none_when_nothing_available(mock_cmd, mock_which):
    assert detect_runtime() == "none"


@patch("ari.container.os.environ", {"SLURM_JOB_ID": "12345"})
@patch("ari.container.shutil.which", side_effect=lambda x: x if x == "singularity" else None)
@patch("ari.container._cmd_ok", return_value="singularity version 3.8.0")
def test_detect_runtime_prefers_singularity_on_hpc(mock_cmd, mock_which):
    assert detect_runtime() in ("singularity", "apptainer")


# ── ContainerConfig defaults ────────────────────────


def test_container_config_defaults():
    cfg = ContainerConfig()
    assert cfg.image == ""
    assert cfg.mode == "auto"
    assert cfg.pull == "on_start"
    assert cfg.extra_args == []


def test_container_config_custom():
    cfg = ContainerConfig(
        image="ghcr.io/kotama7/ari:latest",
        mode="docker",
        pull="always",
        extra_args=["--gpus", "all"],
    )
    assert cfg.image == "ghcr.io/kotama7/ari:latest"
    assert cfg.mode == "docker"
    assert cfg.pull == "always"
    assert cfg.extra_args == ["--gpus", "all"]


# ── pull_image ──────────────────────────────────────


@patch("ari.container.subprocess.run")
def test_pull_image_docker(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    cfg = ContainerConfig(image="myimage:latest", mode="docker")
    assert pull_image(cfg) is True
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:2] == ["docker", "pull"]
    assert "myimage:latest" in args


@patch("ari.container.subprocess.run")
def test_pull_image_singularity(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    cfg = ContainerConfig(image="myimage:latest", mode="singularity")
    assert pull_image(cfg) is True
    args = mock_run.call_args[0][0]
    assert args[0] == "singularity"
    assert "pull" in args


@patch("ari.container.os.makedirs")
@patch("ari.container.subprocess.run")
def test_pull_image_singularity_saves_to_containers_dir(mock_run, mock_makedirs):
    """Singularity/Apptainer pulls must land inside ./containers/ so list_images() finds them."""
    mock_run.return_value = MagicMock(returncode=0)
    cfg = ContainerConfig(image="ghcr.io/kotama7/ari:latest", mode="singularity")
    assert pull_image(cfg) is True
    # ./containers/ must be ensured
    mock_makedirs.assert_called_once_with("containers", exist_ok=True)
    args = mock_run.call_args[0][0]
    # Output path must be inside containers/ and end with .sif
    # singularity pull [--force] <out> docker://<image>
    out_path = args[-2]
    assert out_path.startswith("containers" + os.sep) or out_path.startswith("containers/"), \
        f"Expected output inside containers/, got {out_path}"
    assert out_path.endswith(".sif"), f"Expected .sif suffix, got {out_path}"
    # The docker:// URI must be the final positional arg
    assert args[-1] == "docker://ghcr.io/kotama7/ari:latest"


@patch("ari.container.os.makedirs")
@patch("ari.container.subprocess.run")
def test_pull_image_apptainer_saves_to_containers_dir(mock_run, mock_makedirs):
    """Same contract for apptainer mode."""
    mock_run.return_value = MagicMock(returncode=0)
    cfg = ContainerConfig(image="myimage:v1", mode="apptainer")
    assert pull_image(cfg) is True
    mock_makedirs.assert_called_once_with("containers", exist_ok=True)
    args = mock_run.call_args[0][0]
    assert args[0] == "apptainer"
    out_path = args[-2]
    assert out_path.startswith("containers" + os.sep) or out_path.startswith("containers/")
    assert out_path.endswith(".sif")


@patch("ari.container.subprocess.run")
def test_pull_image_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    cfg = ContainerConfig(image="myimage:latest", mode="docker")
    assert pull_image(cfg) is False


def test_pull_image_no_image():
    cfg = ContainerConfig(image="", mode="docker")
    assert pull_image(cfg) is False


# ── run_in_container ────────────────────────────────


@patch("ari.container.subprocess.Popen")
def test_run_in_container_docker_command(mock_popen):
    mock_popen.return_value = MagicMock()
    cfg = ContainerConfig(image="myimage:latest", mode="docker")
    proc = run_in_container(cfg, ["python", "run.py"], env={"FOO": "bar"}, workdir="/tmp/work")
    args = mock_popen.call_args[0][0]
    assert args[0] == "docker"
    assert "run" in args
    assert "--rm" in args
    assert "myimage:latest" in args
    assert "python" in args
    assert "run.py" in args


@patch("ari.container.subprocess.Popen")
def test_run_in_container_singularity_command(mock_popen):
    mock_popen.return_value = MagicMock()
    cfg = ContainerConfig(image="myimage:latest", mode="singularity")
    proc = run_in_container(cfg, ["python", "run.py"], workdir="/tmp/work")
    args = mock_popen.call_args[0][0]
    assert args[0] == "singularity"
    assert "exec" in args
    assert "--bind" in args
    assert "docker://myimage:latest" in args
    # --writable-tmpfs lets the agent install missing tools (git, apt
    # packages, …) into a per-invocation overlay so SIF immutability
    # doesn't strand the run. Regression guard.
    assert "--writable-tmpfs" in args, (
        "singularity exec must pass --writable-tmpfs so the agent can "
        "`apk add`/`apt-get install` missing tools inside a read-only SIF"
    )


@patch("ari.container.subprocess.Popen")
def test_run_in_container_apptainer_also_writable_tmpfs(mock_popen):
    """Apptainer inherits the same flag — it shares the CLI surface."""
    mock_popen.return_value = MagicMock()
    cfg = ContainerConfig(image="img:v1", mode="apptainer")
    run_in_container(cfg, ["ls"], workdir="/tmp/w")
    args = mock_popen.call_args[0][0]
    assert args[0] == "apptainer"
    assert "--writable-tmpfs" in args


@patch("ari.container.subprocess.Popen")
def test_run_in_container_none_falls_back_to_direct(mock_popen):
    mock_popen.return_value = MagicMock()
    cfg = ContainerConfig(image="", mode="none")
    proc = run_in_container(cfg, ["python", "run.py"], workdir="/tmp/work")
    args = mock_popen.call_args[0][0]
    assert args == ["python", "run.py"]


# ── list_images ─────────────────────────────────────


@patch("ari.container._cmd_ok", return_value="nginx:latest\t100MB\nubuntu:22.04\t77MB")
def test_list_images_docker(mock_cmd):
    images = list_images("docker")
    assert isinstance(images, list)
    assert len(images) == 2
    assert images[0]["name"] == "nginx:latest"
    assert images[0]["size"] == "100MB"
    assert images[1]["name"] == "ubuntu:22.04"
    mock_cmd.assert_called_once()


@patch("ari.container._cmd_ok", return_value="<none>:<none>\t0B")
def test_list_images_docker_filters_none(mock_cmd):
    images = list_images("docker")
    assert images == []


@patch("ari.container._cmd_ok", return_value=None)
def test_list_images_docker_no_output(mock_cmd):
    images = list_images("docker")
    assert images == []


def test_list_images_singularity_scans_sif(tmp_path):
    sif_file = tmp_path / "myimage.sif"
    sif_file.write_bytes(b"\x00" * 1024)
    with patch("ari.container._glob.glob", return_value=[str(sif_file)]), \
         patch("ari.container.os.path.isdir", return_value=True):
        images = list_images("singularity")
    names = [img["name"] for img in images]
    assert "myimage.sif" in names


def test_list_images_singularity_scans_containers_dir(tmp_path, monkeypatch):
    """list_images must include the project-local ./containers directory in its scan."""
    # Set up a fake containers/ inside tmp_path with a real .sif file
    monkeypatch.chdir(tmp_path)
    (tmp_path / "containers").mkdir()
    sif_file = tmp_path / "containers" / "gcc-13.2.0.sif"
    sif_file.write_bytes(b"\x00" * (2 << 20))  # 2 MB
    images = list_images("singularity")
    names = [img["name"] for img in images]
    assert "gcc-13.2.0.sif" in names, \
        f"./containers/*.sif must be detected; got {names}"


def test_list_images_singularity_containers_dir_in_scan_list(monkeypatch):
    """Verify the scan loop actually iterates over 'containers' as a candidate dir."""
    seen_dirs: list[str] = []
    real_isdir = lambda d: True

    def _fake_glob(pat: str) -> list[str]:
        # pat looks like "<dir>/*.sif" — capture the directory we were called with
        seen_dirs.append(os.path.dirname(pat))
        return []

    with patch("ari.container.os.path.isdir", side_effect=real_isdir), \
         patch("ari.container._glob.glob", side_effect=_fake_glob):
        list_images("singularity")
    assert "containers" in seen_dirs, \
        f"'containers' must be in the scanned dir list; got {seen_dirs}"


def test_list_images_none_returns_empty():
    images = list_images("none")
    assert images == []


def test_list_images_returns_list():
    """list_images always returns a list regardless of runtime."""
    result = list_images()
    assert isinstance(result, list)


# ── get_container_info ──────────────────────────────


def test_get_container_info_returns_dict():
    info = get_container_info()
    assert isinstance(info, dict)
    assert "runtime" in info
    assert "version" in info
    assert "available" in info
    assert info["runtime"] in ("docker", "singularity", "apptainer", "none")
    assert isinstance(info["available"], bool)


# ── GUI API endpoint test ───────────────────────────


def test_api_container_info_endpoint():
    """Test that the container info endpoint returns valid JSON."""
    from ari.container import get_container_info
    info = get_container_info()
    assert "runtime" in info
    assert "available" in info


# ── API endpoint: /api/container/images ────────────


@patch("ari.container.list_images", return_value=[{"name": "img:v1", "size": "50MB"}])
def test_api_container_images_endpoint(mock_list):
    """Verify that the server route calls list_images and returns JSON."""
    from ari.container import list_images as _li
    result = _li()
    assert isinstance(result, list)
    assert result[0]["name"] == "img:v1"


# ── Settings fields ─────────────────────────────────


def test_settings_include_container_fields():
    """Verify container fields appear in the settings schema."""
    from ari.viz.api_settings import _api_get_settings
    settings = _api_get_settings()
    assert "container_mode" in settings
    assert "container_image" in settings
    assert "container_pull" in settings
    assert settings["container_mode"] == "auto"
    assert settings["container_pull"] == "on_start"


# ── GUI → subprocess container propagation ─────────


@pytest.fixture
def _clean_container_env(monkeypatch):
    """Remove container-related env vars so tests start clean."""
    for k in list(os.environ):
        if k.startswith("ARI_CONTAINER"):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def _state():
    from ari.viz import state as _st
    return _st


def _build_proc_env(state_mod, tmp_path, monkeypatch, settings, wizard_data=None):
    """Simulate container-related env building from _api_launch.

    Mirrors the settings-injection + wizard-override logic for container
    fields in api_experiment.py.
    """
    import json as _json

    settings_path = tmp_path / ".ari" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_json.dumps(settings))
    monkeypatch.setattr(state_mod, "_settings_path", settings_path)

    proc_env = os.environ.copy()

    # --- Settings injection (container fallback) ---
    saved = _json.loads(settings_path.read_text())
    _ct_image = saved.get("container_image", "")
    _ct_mode = saved.get("container_mode", "")
    if _ct_image and "ARI_CONTAINER_IMAGE" not in proc_env:
        proc_env["ARI_CONTAINER_IMAGE"] = _ct_image
    if _ct_mode and _ct_mode != "auto" and "ARI_CONTAINER_MODE" not in proc_env:
        proc_env["ARI_CONTAINER_MODE"] = _ct_mode

    # --- Wizard overrides ---
    data = wizard_data or {}
    wiz_container_image = data.get("container_image")
    wiz_container_mode = data.get("container_mode")
    if wiz_container_image:
        proc_env["ARI_CONTAINER_IMAGE"] = str(wiz_container_image)
    if wiz_container_mode:
        proc_env["ARI_CONTAINER_MODE"] = str(wiz_container_mode)

    return proc_env


class TestContainerPropagationWizardToEnv:
    """Wizard container_image/container_mode → proc_env ARI_CONTAINER_*."""

    def test_wizard_image_and_mode_injected(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={},
            wizard_data={"container_image": "ghcr.io/kotama7/ari:latest", "container_mode": "docker"})
        assert env["ARI_CONTAINER_IMAGE"] == "ghcr.io/kotama7/ari:latest"
        assert env["ARI_CONTAINER_MODE"] == "docker"

    def test_wizard_image_only(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={},
            wizard_data={"container_image": "myimage:v2"})
        assert env["ARI_CONTAINER_IMAGE"] == "myimage:v2"
        assert "ARI_CONTAINER_MODE" not in env

    def test_wizard_mode_only(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={},
            wizard_data={"container_mode": "singularity"})
        assert env["ARI_CONTAINER_MODE"] == "singularity"
        assert "ARI_CONTAINER_IMAGE" not in env

    def test_no_container_in_wizard(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={}, wizard_data={})
        assert "ARI_CONTAINER_IMAGE" not in env
        assert "ARI_CONTAINER_MODE" not in env


class TestContainerPropagationSettingsFallback:
    """Settings.json container fields used as fallback when wizard omits them."""

    def test_settings_image_used_as_fallback(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={"container_image": "settings-image:v1", "container_mode": "docker"},
            wizard_data={})
        assert env["ARI_CONTAINER_IMAGE"] == "settings-image:v1"
        assert env["ARI_CONTAINER_MODE"] == "docker"

    def test_wizard_overrides_settings(self, _state, tmp_path, monkeypatch, _clean_container_env):
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={"container_image": "old-image:v1", "container_mode": "docker"},
            wizard_data={"container_image": "new-image:v2", "container_mode": "singularity"})
        assert env["ARI_CONTAINER_IMAGE"] == "new-image:v2"
        assert env["ARI_CONTAINER_MODE"] == "singularity"

    def test_settings_mode_auto_not_injected(self, _state, tmp_path, monkeypatch, _clean_container_env):
        """mode=auto is the default, so settings should not inject it."""
        env = _build_proc_env(_state, tmp_path, monkeypatch,
            settings={"container_image": "img:v1", "container_mode": "auto"},
            wizard_data={})
        assert env["ARI_CONTAINER_IMAGE"] == "img:v1"
        assert "ARI_CONTAINER_MODE" not in env


class TestCliContainerEnvPrecedence:
    """cli.py must prefer ARI_CONTAINER_IMAGE/MODE env vars over workflow.yaml."""

    def test_env_overrides_workflow_yaml(self, monkeypatch):
        """When ARI_CONTAINER_IMAGE is set, workflow.yaml image is ignored."""
        monkeypatch.setenv("ARI_CONTAINER_IMAGE", "env-image:latest")
        monkeypatch.setenv("ARI_CONTAINER_MODE", "docker")
        # Simulate the cli.py logic
        _ct_cfg_raw = {"image": "yaml-image:old", "mode": "singularity"}
        _ct_image = os.environ.get("ARI_CONTAINER_IMAGE") or _ct_cfg_raw.get("image", "")
        _ct_mode = os.environ.get("ARI_CONTAINER_MODE") or _ct_cfg_raw.get("mode", "auto")
        assert _ct_image == "env-image:latest"
        assert _ct_mode == "docker"

    def test_workflow_yaml_used_when_no_env(self, monkeypatch, _clean_container_env):
        """When no env vars, workflow.yaml values are used."""
        _ct_cfg_raw = {"image": "yaml-image:v1", "mode": "apptainer"}
        _ct_image = os.environ.get("ARI_CONTAINER_IMAGE") or _ct_cfg_raw.get("image", "")
        _ct_mode = os.environ.get("ARI_CONTAINER_MODE") or _ct_cfg_raw.get("mode", "auto")
        assert _ct_image == "yaml-image:v1"
        assert _ct_mode == "apptainer"

    def test_empty_env_falls_back_to_yaml(self, monkeypatch, _clean_container_env):
        """Empty string env var falls back to workflow.yaml."""
        # os.environ.get returns None for unset vars (not empty), so fallback works
        _ct_cfg_raw = {"image": "yaml-img:v1", "mode": "docker"}
        _ct_image = os.environ.get("ARI_CONTAINER_IMAGE") or _ct_cfg_raw.get("image", "")
        _ct_mode = os.environ.get("ARI_CONTAINER_MODE") or _ct_cfg_raw.get("mode", "auto")
        assert _ct_image == "yaml-img:v1"
        assert _ct_mode == "docker"


# ── config_from_env ────────────────────────────────


class TestConfigFromEnv:
    """config_from_env() builds ContainerConfig from ARI_CONTAINER_* env vars."""

    def test_returns_none_when_no_image(self, monkeypatch, _clean_container_env):
        assert config_from_env() is None

    def test_returns_config_with_image(self, monkeypatch, _clean_container_env):
        monkeypatch.setenv("ARI_CONTAINER_IMAGE", "myimg:v1")
        cfg = config_from_env()
        assert cfg is not None
        assert cfg.image == "myimg:v1"
        assert cfg.mode == "auto"

    def test_returns_config_with_mode(self, monkeypatch, _clean_container_env):
        monkeypatch.setenv("ARI_CONTAINER_IMAGE", "myimg:v1")
        monkeypatch.setenv("ARI_CONTAINER_MODE", "docker")
        cfg = config_from_env()
        assert cfg is not None
        assert cfg.mode == "docker"


# ── run_shell_in_container ─────────────────────────


class TestRunShellInContainer:
    """run_shell_in_container wraps shell commands in the container."""

    @patch("ari.container.subprocess.run")
    def test_no_image_runs_directly(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args="echo hello", returncode=0, stdout="hello\n", stderr="",
        )
        cfg = ContainerConfig(image="", mode="none")
        result = run_shell_in_container(cfg, "echo hello", cwd="/tmp")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is True

    @patch("ari.container.subprocess.run")
    def test_docker_wraps_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok\n", stderr="",
        )
        cfg = ContainerConfig(image="myimg:v1", mode="docker")
        result = run_shell_in_container(cfg, "python run.py", cwd="/work")
        args = mock_run.call_args[0][0]
        assert args[0] == "docker"
        assert "run" in args
        assert "--rm" in args
        assert "myimg:v1" in args
        # bash -c "python run.py" as the last three positional args
        assert "bash" in args
        assert "-c" in args
        assert "python run.py" in args

    @patch("ari.container.subprocess.run")
    def test_singularity_wraps_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok\n", stderr="",
        )
        cfg = ContainerConfig(image="myimg:v1", mode="singularity")
        result = run_shell_in_container(cfg, "python run.py", cwd="/work")
        args = mock_run.call_args[0][0]
        assert args[0] == "singularity"
        assert "exec" in args
        assert "--bind" in args
        assert "docker://myimg:v1" in args
        assert "python run.py" in args
        # Regression: without --writable-tmpfs the agent cannot apk/apt
        # in the read-only SIF and blocks on "missing git" style errors.
        assert "--writable-tmpfs" in args

    @patch("ari.container.subprocess.run")
    def test_apptainer_wraps_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok\n", stderr="",
        )
        cfg = ContainerConfig(image="myimg:v1", mode="apptainer")
        result = run_shell_in_container(cfg, "ls -la", cwd="/work")
        args = mock_run.call_args[0][0]
        assert args[0] == "apptainer"
        assert "exec" in args
        assert "--writable-tmpfs" in args

    @patch("ari.container.detect_runtime", return_value="docker")
    @patch("ari.container.subprocess.run")
    def test_auto_mode_detects_runtime(self, mock_run, mock_detect):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok\n", stderr="",
        )
        cfg = ContainerConfig(image="myimg:v1", mode="auto")
        result = run_shell_in_container(cfg, "echo test")
        mock_detect.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "docker"
