"""Strict SSH transport tests; no live cluster is required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from ari_skill_hpc.scheduler import (
    RemoteCommandRunner,
    RemoteConfig,
    SchedulerTransportError,
)


def _files(tmp_path: Path) -> tuple[Path, Path]:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        "hpc.example.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnly\n",
        encoding="utf-8",
    )
    key = tmp_path / "id_ed25519"
    key.write_text("test private key placeholder\n", encoding="utf-8")
    key.chmod(0o600)
    return known_hosts, key


def _config(tmp_path: Path) -> RemoteConfig:
    known_hosts, key = _files(tmp_path)
    return RemoteConfig(
        hostname="hpc.example.com",
        username="researcher",
        port=22,
        known_hosts=str(known_hosts),
        key_filename=str(key),
    )


def _ssh_client(stdout: bytes = b"123\n", stderr: bytes = b"", rc: int = 0):
    client = MagicMock()
    remote_stdin = MagicMock()
    remote_stdout = MagicMock()
    remote_stderr = MagicMock()
    remote_stdout.read.return_value = stdout
    remote_stderr.read.return_value = stderr
    remote_stdout.channel.recv_exit_status.return_value = rc
    client.exec_command.return_value = (remote_stdin, remote_stdout, remote_stderr)
    return client, remote_stdin


def test_remote_config_requires_explicit_host_key_and_credential(
    tmp_path: Path,
) -> None:
    _known_hosts, key = _files(tmp_path)
    with pytest.raises(ValueError, match="KNOWN_HOSTS must be absolute"):
        RemoteConfig(
            hostname="hpc.example.com",
            username="researcher",
            known_hosts="relative-known-hosts",
            key_filename=str(key),
        )
    with pytest.raises(ValueError, match="explicit key or password"):
        RemoteConfig(
            hostname="hpc.example.com",
            username="researcher",
            known_hosts=str(tmp_path / "known_hosts"),
        )


@pytest.mark.asyncio
async def test_remote_transport_reject_policy_and_no_implicit_credentials(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    client, remote_stdin = _ssh_client(stdout=b"4455;cluster\n")
    with patch("paramiko.SSHClient", return_value=client):
        runner = RemoteCommandRunner(config)
        result = await runner.run(
            ["sbatch", "--parsable", "--export=NIL"],
            stdin=b"#!/bin/bash\n",
        )

    assert result.stdout == "4455;cluster"
    client.load_host_keys.assert_called_once_with(config.known_hosts)
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)
    kwargs = client.connect.call_args.kwargs
    assert kwargs["allow_agent"] is False
    assert kwargs["look_for_keys"] is False
    assert kwargs["key_filename"] == config.key_filename
    assert "password" not in kwargs
    remote_stdin.write.assert_called_once_with(b"#!/bin/bash\n")
    command = client.exec_command.call_args.args[0]
    assert command == "sbatch --parsable --export=NIL"


@pytest.mark.asyncio
async def test_remote_argv_is_posix_quoted_not_interpolated(tmp_path: Path) -> None:
    client, _stdin = _ssh_client()
    with patch("paramiko.SSHClient", return_value=client):
        runner = RemoteCommandRunner(_config(tmp_path))
        await runner.run(["tool", "value; touch /tmp/pwn", "$(id)"])
    command = client.exec_command.call_args.args[0]
    assert command == "tool 'value; touch /tmp/pwn' '$(id)'"


@pytest.mark.asyncio
async def test_host_key_or_connect_failure_is_fail_closed(tmp_path: Path) -> None:
    client, _stdin = _ssh_client()
    client.connect.side_effect = paramiko.SSHException("host key mismatch")
    with patch("paramiko.SSHClient", return_value=client):
        runner = RemoteCommandRunner(_config(tmp_path))
        with pytest.raises(
            SchedulerTransportError, match="strict SSH connection failed"
        ):
            await runner.run(["sacct", "-j", "1"])
    client.close.assert_called()


@pytest.mark.asyncio
async def test_symlink_known_hosts_is_rejected(tmp_path: Path) -> None:
    real_known, key = _files(tmp_path)
    linked = tmp_path / "known_hosts.link"
    linked.symlink_to(real_known)
    config = RemoteConfig(
        hostname="hpc.example.com",
        username="researcher",
        known_hosts=str(linked),
        key_filename=str(key),
    )
    runner = RemoteCommandRunner(config)
    with pytest.raises(SchedulerTransportError, match="missing or unsafe"):
        await runner.run(["squeue", "-j", "1"])


@pytest.mark.asyncio
async def test_group_readable_private_key_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    Path(config.key_filename).chmod(0o640)
    runner = RemoteCommandRunner(config)
    with pytest.raises(SchedulerTransportError, match="permissions"):
        await runner.run(["squeue", "-j", "1"])


def test_identity_contains_pins_but_never_key_content(tmp_path: Path) -> None:
    config = _config(tmp_path)
    identity = RemoteCommandRunner(config).identity
    assert identity["known_hosts_digest"].startswith("sha256:")
    assert "private key" not in repr(identity)
    assert config.key_filename not in repr(identity)
