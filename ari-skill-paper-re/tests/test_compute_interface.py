"""Tests for :mod:`_compute.computer` — the concrete ``ComputerInterface``
implementations that replace alcatraz / Docker on ari's HPC stack.

These tests exercise **real subprocesses** under :class:`LocalComputer`. No
mocking of ``send_shell_command`` itself; the only way to verify the
abstract contract is to actually run shell commands and observe the
:class:`ExecutionResult` payload. ``ApptainerComputer`` is exercised at the
construction / argv-shape level (a real SIF image is a separate fixture
the test environment may or may not provide).
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Force vendor sys.path injection up front
import _vendor_path  # noqa: F401, E402

from _compute import LocalComputer, ApptainerComputer, make_computer  # noqa: E402
from nanoeval.solvers.computer_tasks.code_execution_interface import (  # noqa: E402
    ComputerInterface,
    ExecutionResult,
)


pytestmark = pytest.mark.asyncio


async def test_local_computer_implements_full_abc():
    """All 6 ComputerInterface abstractmethods are concrete on LocalComputer.

    If any were left abstract, the constructor would raise ``TypeError``.
    """
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        assert isinstance(c, ComputerInterface)
        # Real network is not modified, but the method must be callable.
        await c.disable_internet()
        assert await c.fetch_container_names() == []
        await c.stop()


async def test_local_computer_shell_roundtrip():
    """Real bash subprocess: stdout returned as ExecutionResult.output bytes."""
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        r = await c.send_shell_command("echo hello && pwd")
        assert isinstance(r, ExecutionResult)
        assert r.exit_code == 0
        out = r.output.decode()
        assert "hello" in out
        assert str(Path(td).resolve()) in out


async def test_local_computer_exit_code_propagation():
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        r = await c.send_shell_command("false")
        assert r.exit_code == 1
        r2 = await c.send_shell_command("exit 42")
        assert r2.exit_code == 42


async def test_local_computer_upload_and_shell_read():
    """upload writes real bytes to disk; shell can cat them back."""
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        await c.upload(b"sample\n", "subdir/foo.txt")
        assert (Path(td) / "subdir" / "foo.txt").read_bytes() == b"sample\n"
        r = await c.send_shell_command("cat subdir/foo.txt")
        assert r.exit_code == 0
        assert r.output == b"sample\n"


async def test_local_computer_download_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        await c.upload(b"abc\n", "f.txt")
        data = await c.download("f.txt")
        assert data == b"abc\n"


async def test_local_computer_absolute_destination():
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td) / "work")
        absdest = Path(td) / "outside.txt"
        await c.upload(b"X", str(absdest))
        assert absdest.read_bytes() == b"X"


async def test_local_computer_timeout():
    """Timeout is enforced; exit code 124 (timeout(1) convention)."""
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td), timeout_sec=2)
        r = await c.send_shell_command("sleep 10")
        assert r.exit_code == 124
        assert b"timed out" in r.output


async def test_local_computer_stop_blocks_further_use():
    with tempfile.TemporaryDirectory() as td:
        c = LocalComputer(Path(td))
        await c.stop()
        with pytest.raises(RuntimeError):
            await c.send_shell_command("echo x")
        with pytest.raises(RuntimeError):
            await c.upload(b"a", "x")
        with pytest.raises(RuntimeError):
            await c.download("x")


async def test_make_computer_factory_local_default():
    with tempfile.TemporaryDirectory() as td:
        c = make_computer(Path(td), kind="local")
        assert isinstance(c, LocalComputer)


async def test_make_computer_apptainer_requires_image():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            make_computer(Path(td), kind="apptainer", image=None)


@pytest.mark.skipif(
    shutil.which("apptainer") is None and shutil.which("singularity") is None,
    reason="apptainer/singularity not on PATH",
)
async def test_apptainer_computer_argv_construction():
    """Construct ApptainerComputer (no image execution); verify command argv
    shape via private ``_run_subprocess`` would receive the right argv.

    We mock _run_subprocess at the module level to capture the argv without
    actually invoking apptainer (which would require a real SIF image). All
    other code paths (path resolution, runner detection, env merging) run
    real.
    """
    from _compute import computer as comp_mod

    captured = {}

    async def _capture_subprocess(*, argv, cwd, env, timeout_sec):
        captured["argv"] = list(argv)
        captured["cwd"] = str(cwd)
        return ExecutionResult(output=b"", exit_code=0)

    orig = comp_mod._run_subprocess
    comp_mod._run_subprocess = _capture_subprocess
    try:
        with tempfile.TemporaryDirectory() as td:
            c = ApptainerComputer(Path(td), image="/fake/image.sif")
            await c.send_shell_command("echo hi")
        argv = captured["argv"]
        assert argv[0] in ("apptainer", "singularity")
        assert argv[1] == "exec"
        assert "--bind" in argv
        assert "/fake/image.sif" in argv
        assert argv[-3:] == ["bash", "-lc", "echo hi"]
    finally:
        comp_mod._run_subprocess = orig
