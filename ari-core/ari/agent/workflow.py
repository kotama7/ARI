"""
WorkflowHints — Dataclass for injecting experiment-specific workflow settings into AgentLoop via DI.
AgentLoop itself has no experiment domain knowledge.
"""
from __future__ import annotations
from dataclasses import dataclass, field
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
    # Output file pattern for experiment results (e.g. "~/logs/slurm_{job_id}.out")
    output_file_pattern: str | None = None

    # ---- Metrics validation ---------------------------------------------------
    # Minimum expected value for actual measurements (0 = no validation)
    min_expected_metric: float = 0.0
    # Callable to extract actual values from result_str (e.g. MFLOPS regex)
    metric_extractor: Callable[[str], list[float]] | None = None

    # ---- Additional system prompt -------------------------------------------
    # Experiment-specific instructions appended to the end of SYSTEM_PROMPT
    extra_system_prompt: str = ""

    # ---- Local files provided by user ----------------------------------------
    # List of (src_path, filename) tuples — files to copy into node work_dir
    provided_files: list = field(default_factory=list)

    # ---- HPC settings parsed from .md ----------------------------------------
    slurm_partition: str = ""
    slurm_max_cpus: int = 0


def from_experiment_text(experiment_text: str) -> WorkflowHints:
    """
    Automatically build WorkflowHints from an experiment file (Markdown).
    Current implementation is generic: generates settings when a SLURM workflow is detected.
    """
    import re
    text_lower = experiment_text.lower()

    hints = WorkflowHints()

    # Always set idea generation sequence (root node generates ideas before experimenting)
    hints.tool_sequence = ["make_metric_spec", "survey", "generate_ideas", "run_bash", "slurm_submit", "job_status"]
    hints.post_survey_hint = (
        "First, call generate_ideas() once to propose novel research directions based on the survey results.\n"
        "Then implement and run the experiment for the best idea:\n"
        "1. Use run_bash() to write the complete implementation\n"
        "2. Use slurm_submit() if SLURM is available, or run_bash() otherwise\n"
        "3. Use job_status() to monitor if SLURM was used\n"
        "4. Use run_bash() to read and report results\n"
        "IMPORTANT: Write a fully working implementation that produces actual numeric results."
    )

    # SLURM workflow detection — any HPC/cluster keyword triggers SLURM workflow
    slurm_keywords = ["slurm_submit", "sbatch", "partition:", "srun", "#slurm", "slurm"]
    if any(kw in text_lower for kw in slurm_keywords):
        hints.job_submitter_tool = "slurm_submit"
        hints.job_poller_tool = "job_status"
        hints.job_reader_tool = "run_bash"
        hints.tool_sequence = ["make_metric_spec", "survey", "generate_ideas", "run_bash", "slurm_submit", "job_status"]
        hints.post_survey_hint = (
            "First, call generate_ideas() once to propose novel research directions based on the survey results.\n"
            "Then implement and run the experiment for the best idea:\n"
            "1. Use run_bash() to write the complete implementation to a file in the work directory\n"
            "2. Use slurm_submit() to run it via SLURM\n"
            "3. Use job_status() to wait for completion\n"
            "4. Use run_bash() to read the results\n"
            "IMPORTANT: Write a fully working implementation that produces actual numeric results.\n"
            "Do NOT write placeholder scripts or stub implementations."
        )

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
    # Match integers, decimals, and scientific notation (e.g. 1.46e-06)
    _pat_wf = _re_wf.compile(r"\b(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b")
    def _generic_metric_extractor(text: str) -> list:
        results = []
        for x in _pat_wf.findall(text):
            try:
                v = float(x)
                results.append(v)
            except ValueError:
                pass
        return results
    hints.metric_extractor = _generic_metric_extractor


    # min_expected_metric: from <!-- min_expected_metric: N --> or front matter
    m2 = re.search(r"min_expected_metric:\s*([\d]+)", experiment_text)
    if m2:
        hints.min_expected_metric = float(m2.group(1))

    # ── Parse provided local files ─────────────────────────────────────────
    # Supported formats in .md:
    #   ## 提供ファイル  /  ## Provided Files  /  ## Local Files
    #   - /path/to/file.c    # optional comment
    #   /path/to/file.c
    import os as _os
    file_section = re.search(
        r"(?:##\s*(?:提供ファイル|Provided Files?|Local Files?|Files?)\s*\n)(.*?)(?=\n##|\Z)",
        experiment_text, re.DOTALL | re.IGNORECASE
    )
    if file_section:
        for line in file_section.group(1).splitlines():
            line = line.strip().lstrip("-* ").split("#")[0].strip()
            if line and _os.path.sep in line:
                fname = _os.path.basename(line)
                hints.provided_files.append((line, fname))

    # ── Parse HPC settings ────────────────────────────────────────────────
    # Partition: genoa  /  Partition: genoa, Max CPUs: 64
    m_part = re.search(r"(?:Partition|partition)[:\s]+([\w-]+)", experiment_text)
    if m_part:
        hints.slurm_partition = m_part.group(1).strip()

    m_cpu = re.search(r"Max CPUs?[:\s]+(\d+)", experiment_text, re.IGNORECASE)
    if m_cpu:
        hints.slurm_max_cpus = int(m_cpu.group(1))

    return hints
