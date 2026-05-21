"""LocalPBTask — :class:`PBTask` subclass for ari's checkpoint-driven setup.

Differences from upstream :class:`paperbench.nano.task.PBTask`:

* ``_setup`` reads ``paper.md`` (or ``.tex``) from the host filesystem
  directly, bypassing :data:`paperbench.paper_registry` (which only knows
  about the curated ICML 2024 papers). ari's papers are freshly generated
  by BFTS, so the registry is irrelevant.

* ``setup`` is overridden to skip
  :meth:`ComputerConfiguration.setup` (which writes ``cd <cwd>`` to
  ``~/.bashrc`` / ``~/.profile`` on the host — undesirable side effects
  when running under :class:`LocalComputer` without a container).

* ``grade`` is a no-op; ari's existing :func:`server.grade_with_simplejudge`
  pipeline is the grading authority. The PaperBench solver harness only
  calls :meth:`_run_agent` from us, which never invokes ``grade``.

The instance is *Pydantic*-based so each field declaration is validated.
``arbitrary_types_allowed`` is required because :class:`ReproductionConfig`
holds an :class:`AlcatrazComputerRuntime` instance whose chz-decorated
fields aren't introspectable by Pydantic on their own.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ConfigDict
from typing_extensions import override

import _vendor_path  # noqa: F401

from nanoeval.solvers.computer_tasks.code_execution_interface import (
    ComputerInterface,
    NetworkMode,
    RuntimeConfig,
)
from nanoeval.solvers.computer_tasks.task import Grade
from paperbench.monitor.monitor import BasicMonitor, MonitorResult
from paperbench.nano.structs import (
    JudgeConfig,
    PaperBenchGrade,
    PaperBenchResult,
    ReproductionConfig,
)
from paperbench.nano.task import PBTask

log = logging.getLogger(__name__)


class LocalPBTask(PBTask):
    """A :class:`PBTask` whose paper text + rubric come from local disk.

    Required fields beyond :class:`PBTask`:

    paper_md_path: absolute path to a ``paper.md`` (or ``.tex``) file.
    rubric_expected_artifacts: list of relative paths the agent must
        eventually produce in the workspace (typically the rubric's
        ``expected_artifacts`` field).
    work_dir: absolute path on the host where the agent operates. Used
        only as documentation; the actual cwd is enforced by the
        :class:`LocalComputer` invoking the shell.
    """

    # Allow our extra fields. Inherits ``extra="forbid"`` from ComputerTask
    # otherwise — we explicitly opt back in.
    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    paper_md_path: str
    rubric_expected_artifacts: list[str] = []
    rubric_execution_profile: dict = {}
    cluster_shape: dict = {}
    work_dir: str

    @override
    async def setup(
        self,
        computer: ComputerInterface,
        runtime_config: RuntimeConfig,
    ) -> None:
        """Bypass :meth:`ComputerConfiguration.setup`.

        Upstream's setup writes ``cd /root`` to ``~/.bashrc`` and validates
        volume mounts; both are inappropriate under :class:`LocalComputer`
        which runs on the host. Calling :meth:`_setup` directly is sufficient.
        """
        await self._setup(computer, runtime_config)

    @override
    async def _setup(
        self,
        computer: ComputerInterface,
        runtime_config: RuntimeConfig,
    ) -> None:
        paper_path = Path(self.paper_md_path)
        if not paper_path.is_file():
            raise FileNotFoundError(
                f"paper file not found: {paper_path} — set paper_md_path to "
                f"the absolute path of full_paper.tex / paper.md"
            )
        # Workspace layout (all relative to LocalComputer.work_dir):
        #   paper/paper.md         — the paper text the agent will read
        #   instructions.txt       — the user-facing task brief
        #   submission/            — the agent's working area; agent may also
        #                            write files at the workspace root.
        await computer.upload(paper_path.read_bytes(), "paper/paper.md")
        instructions = self.prompt[0].get("content", "")
        if not isinstance(instructions, str) or not instructions:
            raise ValueError("LocalPBTask.prompt[0].content must be a non-empty str")
        await computer.upload(instructions.encode("utf-8"), "instructions.txt")
        # Create submission/ in case the agent wants the PaperBench convention.
        # Either location (workspace root or submission/) is acceptable;
        # downstream ari's ``ors_run_reproduce`` reads ``reproduce.sh`` at the
        # workspace root.
        res = await computer.send_shell_command("mkdir -p submission paper")
        if res.exit_code != 0:
            raise RuntimeError(
                f"workspace bootstrap failed: {res.unicode_output_best_effort}"
            )

    @override
    async def grade(
        self,
        computer: ComputerInterface,
        runtime_config: RuntimeConfig,
    ) -> PaperBenchGrade:
        """No-op grade — ari uses its own SimpleJudge pipeline elsewhere."""
        return PaperBenchGrade(
            paperbench_result=PaperBenchResult(
                paper_id=self.paper_id,
                run_id=self.run_id,
                submission_exists=False,
                skipped_reproduction=True,
                code_only=self.judge.code_only,
                resources_provided=self.judge.resources_provided,
                agent_output=None,
                judge_output=None,
                reproduction_metadata=None,
                monitor_result=None,
                monitor_ran=False,
            ),
            score=0.0,
            grader_log="LocalPBTask: grading delegated to ari's ors_grade pipeline",
        )


def make_local_pbtask(
    *,
    paper_md_path: str,
    work_dir: str,
    instructions: str,
    rubric_expected_artifacts: list[str] | None = None,
    rubric_execution_profile: dict | None = None,
    cluster_shape: dict | None = None,
    paper_id: str = "ari-local",
    run_id: str = "local-run",
    run_group_id: str = "local-group",
    run_dir: str = "",
    runs_dir: str = "",
    code_only: bool = False,
    target_duration_hr: int | None = None,
) -> LocalPBTask:
    """Convenience factory wiring up all the boilerplate fields.

    ``code_only=False`` is the ari default (since v0.7.4). The vendor
    full prompt (``instructions.txt:25``) EXPLICITLY requires
    ``reproduce.sh`` — "Your submitted repository MUST include a script
    for reproducing the results at ``/home/submission/reproduce.sh``".
    This is the file ARI's Stage 2 (``server.run_reproduce`` /
    ``bridge.reproduce_submission``) needs to execute.

    Previously the default was True with the rationale "agent just
    writes source, ARI's separate ors_run_reproduce executes it" —
    but the vendor code-only prompt (``code_only_instructions.txt``)
    does NOT mention ``reproduce.sh`` AND explicitly tells the agent
    "the code will not be executed during grading", causing the agent
    to skip writing ``reproduce.sh`` entirely. ARI's Stage 2 then
    failed with "reproduce.sh missing" — the SC41406 BasicAgent
    dogfood surfaced this; see CHANGELOG v0.7.4.

    Stage 3 grading scope adapts on the JUDGE call:
    ``server.grade_with_simplejudge`` auto-enables ``code_only`` when
    no ``reproduce.log`` is present (commit caae252) — so a
    rollout-only run still scores correctly against Code Development
    leaves without requiring this Stage 1 flag to be flipped.
    """
    if not run_dir:
        run_dir = work_dir
    if not runs_dir:
        runs_dir = str(Path(work_dir).parent)
    return LocalPBTask(
        paper_md_path=paper_md_path,
        rubric_expected_artifacts=list(rubric_expected_artifacts or []),
        rubric_execution_profile=dict(rubric_execution_profile or {}),
        cluster_shape=dict(cluster_shape or {}),
        work_dir=work_dir,
        prompt=[{"role": "user", "content": instructions}],
        # PBTask carries Task identifiers from nanoeval; we synthesize
        # locally-meaningful values rather than collide with the upstream
        # ICML run_group taxonomy.
        question_id=paper_id,
        paper_id=paper_id,
        run_id=run_id,
        run_group_id=run_group_id,
        run_dir=run_dir,
        runs_dir=runs_dir,
        target_duration_hr=target_duration_hr,
        reproduction=ReproductionConfig(skip_reproduction=True),
        judge=JudgeConfig(grade=False, code_only=code_only),
        monitor_config=BasicMonitor.Config(),
        save_cluster_output_to_host=False,
        network_mode=NetworkMode.UNPROXIED,
    )


__all__ = ["LocalPBTask", "make_local_pbtask"]
