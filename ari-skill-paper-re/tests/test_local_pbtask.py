"""Tests for :mod:`_compute.local_pbtask` — :class:`PBTask` subclass that
bypasses ``paperbench.paper_registry`` for ari-generated papers.

Real Pydantic validation, real :class:`LocalComputer` setup, real filesystem
writes. No mocking of subprocesses or vendor classes.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _vendor_path  # noqa: F401, E402

from _compute import LocalComputer  # noqa: E402
from _compute.local_pbtask import LocalPBTask, make_local_pbtask  # noqa: E402
from paperbench.nano.task import PBTask  # noqa: E402
from paperbench.nano.structs import (  # noqa: E402
    JudgeConfig,
    PaperBenchGrade,
    ReproductionConfig,
)


pytestmark = pytest.mark.asyncio


def test_local_pbtask_is_real_subclass_of_pbtask():
    """Sanity: subclass relationship is preserved by chz / pydantic."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("# Title\n")
        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "work"),
            instructions="Hello",
        )
    assert isinstance(task, LocalPBTask)
    assert isinstance(task, PBTask)


def test_factory_sets_paperbench_friendly_defaults():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("Hi.")
        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "work"),
            instructions="Run it.",
            rubric_expected_artifacts=["a.csv", "b.json"],
        )
    # Since v0.7.4: code_only defaults to False so vendor instructions.txt
    # (which EXPLICITLY requires reproduce.sh) reaches the agent. The
    # previous default of True selected code_only_instructions.txt which
    # tells the agent "the code will not be executed" and omits the
    # reproduce.sh requirement — causing ARI's Stage 2 to fail with
    # "reproduce.sh missing". See make_local_pbtask docstring + CHANGELOG.
    assert task.judge.code_only is False
    assert task.reproduction.skip_reproduction is True
    assert task.rubric_expected_artifacts == ["a.csv", "b.json"]
    # Real ReproductionConfig / JudgeConfig instances, not stubs
    assert isinstance(task.reproduction, ReproductionConfig)
    assert isinstance(task.judge, JudgeConfig)


def test_factory_respects_explicit_code_only_true():
    """Opt-in: callers that want the vendor Code-Dev prompt
    (``code_only_instructions.txt``, no reproduce.sh requirement) can
    still request it explicitly.
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("Hi.")
        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "work"),
            instructions="Run it.",
            rubric_expected_artifacts=[],
            code_only=True,
        )
    assert task.judge.code_only is True


async def test_setup_uploads_paper_and_instructions_to_workspace():
    """Real LocalComputer bootstraps real fs layout."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper_text = "# Replicator test paper\n\nClaims: foo > bar.\n"
        paper.write_text(paper_text)
        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "work"),
            instructions="Replicate the paper at paper/paper.md.",
            rubric_expected_artifacts=["results.csv"],
        )
        c = LocalComputer(td / "work")
        await task.setup(c, runtime_config=task.reproduction.runtime_config)
        # Real disk writes must be present
        assert (td / "work" / "paper" / "paper.md").read_text() == paper_text
        assert (td / "work" / "instructions.txt").read_text().startswith(
            "Replicate the paper"
        )
        assert (td / "work" / "submission").is_dir()


async def test_setup_skips_computer_configuration_setup():
    """The override of ``setup`` must NOT touch the host's ``~/.bashrc``.

    Upstream's ``ComputerConfiguration.setup`` (called from
    ``ComputerTask.setup``) appends ``cd /root`` to ``~/.bashrc``. We bypass
    that by overriding ``setup`` directly. Verify by checking that
    ``~/.bashrc`` (if it exists) does NOT contain a fresh ``cd
    /tmp/...`` line referencing our work_dir.
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("foo")
        bashrc = Path("~/.bashrc").expanduser()
        before = bashrc.read_text() if bashrc.exists() else ""

        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "very_unique_workdir_marker_xyz"),
            instructions="x",
        )
        c = LocalComputer(td / "very_unique_workdir_marker_xyz")
        await task.setup(c, runtime_config=task.reproduction.runtime_config)

        after = bashrc.read_text() if bashrc.exists() else ""
        assert "very_unique_workdir_marker_xyz" not in after.replace(before, "")


async def test_setup_raises_on_missing_paper_file():
    with tempfile.TemporaryDirectory() as td:
        task = make_local_pbtask(
            paper_md_path="/no/such/path.md",
            work_dir=str(Path(td) / "work"),
            instructions="x",
        )
        c = LocalComputer(Path(td) / "work")
        with pytest.raises(FileNotFoundError):
            await task.setup(c, runtime_config=task.reproduction.runtime_config)


async def test_grade_returns_no_op_grade():
    """``grade`` is a no-op pass-through; ari's ors_grade pipeline does the
    real grading. We just confirm the method is callable and returns the
    upstream :class:`PaperBenchGrade` shape (so harness-level callers don't
    crash if they ever invoke it)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        paper = td / "paper.md"
        paper.write_text("x")
        task = make_local_pbtask(
            paper_md_path=str(paper),
            work_dir=str(td / "work"),
            instructions="x",
        )
        c = LocalComputer(td / "work")
        grade = await task.grade(c, runtime_config=task.reproduction.runtime_config)
        assert isinstance(grade, PaperBenchGrade)
        assert grade.score == 0.0
