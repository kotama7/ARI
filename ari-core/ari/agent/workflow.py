"""
WorkflowHints — Dataclass for injecting experiment-specific workflow settings into AgentLoop via DI.
AgentLoop itself has no experiment domain knowledge.
"""
from __future__ import annotations
from dataclasses import dataclass, field, field
from typing import Callable


@dataclass
class WorkflowHints:
    """
    Experiment-specific workflow settings. Created by the upper layer (e.g. cli.py) and injected into AgentLoop.
    All fields are optional — if unset, the LLM decides autonomously.
    """

    # ---- Tool sequence ----------------------------------------------------------
    # Recommended tool execution sequence (e.g. ["survey", "slurm_submit", "job_status", "run_bash"])
    # Unset = LLM selects freely
    tool_sequence: list[str] = field(default_factory=list)

    # ---- Async job tracking ---------------------------------------------------
    # Tool name for submitting async jobs (e.g. "slurm_submit")
    job_submitter_tool: str | None = None
    # Tool name for polling job status (e.g. "job_status")
    job_poller_tool: str | None = None
    expected_metrics: list[str] = field(default_factory=list)
    # Tool name for reading job results (e.g. "run_bash")
    job_reader_tool: str | None = None
    job_status_tool: str = "job_status"  # Tool name for checking SLURM job status
    # Key name to extract job ID from tool result (e.g. "job_id")
    job_id_key: str = "job_id"

    # ---- Guidance messages ---------------------------------------------------
    # Instructions after survey completes (unset = generic message)
    post_survey_hint: str | None = None
    # Output file pattern for experiment results (e.g. "~/ARI/logs/himeno_slurm_{job_id}.out")
    output_file_pattern: str | None = None

    # ---- Metrics validation ---------------------------------------------------
    # Minimum expected value for actual measurements (0 = no validation)
    min_expected_metric: float = 0.0
    # Callable to extract actual values from result_str (e.g. MFLOPS regex)
    metric_extractor: Callable[[str], list[float]] | None = None

    # ---- Additional system prompt -------------------------------------------
    # Experiment-specific instructions appended to the end of SYSTEM_PROMPT
    extra_system_prompt: str = ""


def from_experiment_text(experiment_text: str) -> WorkflowHints:
    """
    Automatically build WorkflowHints from an experiment file (Markdown).
    Current implementation is generic: generates settings when a SLURM workflow is detected.
    """
    import re
    text_lower = experiment_text.lower()

    hints = WorkflowHints()

    # SLURM workflow detection
    if "slurm_submit" in text_lower or "sbatch" in text_lower:
        hints.job_submitter_tool = "slurm_submit"
        hints.job_poller_tool = "job_status"
        hints.job_reader_tool = "run_bash"
        hints.tool_sequence = ["make_metric_spec", "run_bash", "job_status", "survey", "slurm_submit"]

    # post_survey_hint: ## Required Workflow section
    m = re.search(r"## Required Workflow\n(.*?)(?=\n##|$)", experiment_text, re.DOTALL)
    if m:
        hints.post_survey_hint = (
            "Follow this workflow from the experiment spec:\n"
            + m.group(1).strip()
        )

    # metric_extractor: always generic numeric extraction (no branching)
    # LLMEvaluator autonomously determines what to measure from the goal text
    import re as _re_wf
    _pat_wf = _re_wf.compile(r"\b(\d+\.\d+|\d{4,})\b")
    def _generic_metric_extractor(text: str) -> list:
        return [float(x) for x in _pat_wf.findall(text) if float(x) >= 1.0]
    hints.metric_extractor = _generic_metric_extractor


    # min_expected_metric: from <!-- min_expected_metric: N --> or front matter
    m2 = re.search(r"min_expected_metric:\s*([\d]+)", experiment_text)
    if m2:
        hints.min_expected_metric = float(m2.group(1))

    return hints
