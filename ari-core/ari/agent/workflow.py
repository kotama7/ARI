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
    # Callable to extract actual values from result_str (e.g. metric regex)
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


def _build_post_survey_hint(use_slurm: bool = False, extra_tools: str = "",
                            has_idea_gen: bool = True,
                            submitter: str | None = None,
                            poller: str | None = None,
                            reader: str | None = None) -> str:
    """Build the post-survey hint string.

    extra_tools: dynamically generated tool descriptions injected by
    enrich_hints_from_mcp(). Empty string when called before MCP init.
    has_idea_gen: whether generate_ideas tool is available. When False,
    the hint skips the idea generation step and goes straight to implementation.
    submitter/poller/reader: tool names resolved from WorkflowHints so that
    the workflow steps reference whichever job submission tool MCP exposed
    (slurm_submit today, another backend tomorrow) without hardcoding.
    """
    if has_idea_gen:
        idea_line = "First, call generate_ideas() once to propose novel research directions based on the survey results.\nThen implement and run the experiment for the best idea:\n"
    else:
        idea_line = "Implement and run the experiment:\n"

    if use_slurm:
        submitter = submitter or "<job submitter tool>"
        poller = poller or "<job status tool>"
        reader = reader or "run_bash"
        core = (
            idea_line
            + f"1. Use {reader}() to write the complete implementation to a file in the work directory\n"
            f"2. Use {submitter}() to submit it as an async job (see AVAILABLE TOOLS for its exact signature)\n"
            f"3. Call {poller}() ONCE — the framework auto-polls every 30s until completion\n"
            f"4. Use {reader}() to read the results\n"
            "IMPORTANT: Write a fully working implementation that produces actual numeric results.\n"
            "Do NOT write placeholder scripts or stub implementations.\n"
        )
    else:
        core = (
            idea_line
            + "1. Use run_bash() to write the complete implementation\n"
            "2. Use run_bash() to execute it locally\n"
            "3. Use run_bash() to read and report results\n"
            "IMPORTANT: Write a fully working implementation that produces actual numeric results.\n"
        )

    budget = "STEP BUDGET: You have a limited number of steps. Do NOT waste steps by:\n"
    if use_slurm:
        budget += (
            f"  - Calling {poller}() repeatedly (auto-poll handles this)\n"
            f"  - Resubmitting the same job without fixing the error\n"
        )
    budget += (
        "  - Writing text plans instead of calling tools\n"
        "If a job takes long, use run_bash(command='sleep <seconds>') to wait before reading results."
    )

    return core + extra_tools + budget


def enrich_hints_from_mcp(hints: WorkflowHints, mcp_tools: list[dict], *, hpc_enabled: bool = True) -> None:
    """Enrich WorkflowHints with dynamically discovered MCP tool info.

    Called after MCPClient.list_tools(phase="bfts") so the LLM prompt
    describes only the tools actually available, not a hardcoded list.

    Parameters
    ----------
    hints : WorkflowHints
        The hints object to mutate in place.
    mcp_tools : list[dict]
        Tool dicts from MCPClient.list_tools(phase="bfts"), each with
        'name', 'description', and optionally 'inputSchema'.
    """
    if not mcp_tools:
        return

    # When HPC is disabled, filter out SLURM-related tools entirely
    _SLURM_TOOLS = {"slurm_submit", "job_status"}
    if not hpc_enabled:
        mcp_tools = [t for t in mcp_tools if t["name"] not in _SLURM_TOOLS]
        # Clear any SLURM hints that may have been set earlier
        hints.job_submitter_tool = None
        hints.job_poller_tool = None
        hints.job_reader_tool = None
        hints.slurm_partition = ""
        hints.slurm_max_cpus = 0

    # Build tool_sequence from actual available tools (preserve recommended order)
    _PREFERRED_ORDER = [
        "make_metric_spec", "survey", "generate_ideas",
        "run_bash", "slurm_submit", "job_status",
    ]
    available_names = {t["name"] for t in mcp_tools}
    ordered = [n for n in _PREFERRED_ORDER if n in available_names]
    remaining = sorted(available_names - set(ordered))
    hints.tool_sequence = ordered + remaining

    # Build dynamic tool descriptions grouped by skill
    skill_groups: dict[str, list[dict]] = {}
    for t in mcp_tools:
        sk = t.get("skill_name", "other")
        skill_groups.setdefault(sk, []).append(t)

    # Core tools whose usage is already described by the step-by-step workflow
    # in _build_post_survey_hint — skip from the extras listing to avoid
    # redundancy. Job submission tools (slurm_submit, job_status, etc.) are
    # NOT in this set: their signatures come from MCP so the LLM sees the
    # real parameters instead of a hardcoded description.
    _CORE_TOOLS = {"make_metric_spec", "survey", "generate_ideas", "run_bash"}

    lines: list[str] = []
    for sk, tools in sorted(skill_groups.items()):
        extras = [t for t in tools if t["name"] not in _CORE_TOOLS]
        if not extras:
            continue
        lines.append(f"AVAILABLE TOOLS ({sk}):")
        for t in extras:
            desc = t.get("description", "")
            # Extract parameter names from inputSchema
            schema = t.get("inputSchema") or {}
            params = list((schema.get("properties") or {}).keys())
            sig = ", ".join(params) if params else "..."
            lines.append(f"  - {t['name']}({sig}): {desc}")
        lines.append("")

    extra_tools = "\n".join(lines) + "\n" if lines else ""

    # Detect async-job workflow and idea generation availability. use_slurm is
    # True whenever a job submitter tool is registered (name-agnostic) so any
    # backend exposed via MCP triggers the async-job step template.
    use_slurm = hpc_enabled and bool(hints.job_submitter_tool) and hints.job_submitter_tool in available_names
    has_idea_gen = "generate_ideas" in available_names
    hints.post_survey_hint = _build_post_survey_hint(
        use_slurm=use_slurm, extra_tools=extra_tools,
        has_idea_gen=has_idea_gen,
        submitter=hints.job_submitter_tool,
        poller=hints.job_poller_tool,
        reader=hints.job_reader_tool,
    )


def from_experiment_text(experiment_text: str, *, hpc_enabled: bool = True) -> WorkflowHints:
    """
    Automatically build WorkflowHints from an experiment file (Markdown).
    Current implementation is generic: generates settings when a SLURM workflow is detected.

    Parameters
    ----------
    hpc_enabled : bool
        When False (laptop profile), all SLURM-related hints are suppressed
        regardless of keywords in the experiment markdown.
    """
    import re
    text_lower = experiment_text.lower()

    hints = WorkflowHints()

    # Default tool sequence — will be refined by enrich_hints_from_mcp()
    if hpc_enabled:
        hints.tool_sequence = ["make_metric_spec", "survey", "generate_ideas", "run_bash", "slurm_submit", "job_status"]
    else:
        hints.tool_sequence = ["make_metric_spec", "survey", "generate_ideas", "run_bash"]
    hints.post_survey_hint = _build_post_survey_hint(use_slurm=False)

    # SLURM workflow detection — any HPC/cluster keyword triggers SLURM workflow
    # Only when HPC is enabled (profile != laptop)
    slurm_keywords = ["slurm_submit", "sbatch", "partition:", "srun", "#slurm", "slurm"]
    if hpc_enabled and any(kw in text_lower for kw in slurm_keywords):
        hints.job_submitter_tool = "slurm_submit"
        hints.job_poller_tool = "job_status"
        hints.job_reader_tool = "run_bash"
        hints.post_survey_hint = _build_post_survey_hint(
            use_slurm=True,
            submitter=hints.job_submitter_tool,
            poller=hints.job_poller_tool,
            reader=hints.job_reader_tool,
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
        r"(?:##\s*(?:提供ファイル|提供文件|Provided Files?|Local Files?|Files?)\s*\n)(.*?)(?=\n##|\Z)",
        experiment_text, re.DOTALL | re.IGNORECASE
    )
    if file_section:
        for line in file_section.group(1).splitlines():
            line = line.strip().lstrip("-* ").split("#")[0].strip()
            if line and _os.path.sep in line:
                fname = _os.path.basename(line)
                hints.provided_files.append((line, fname))

    # ── Parse HPC settings (only when HPC is enabled) ──────────────────────
    if hpc_enabled:
        # Partition: <name>  /  Partition: <name>, Max CPUs: 64
        m_part = re.search(r"(?:Partition|partition)[:\s]+([\w-]+)", experiment_text)
        if m_part:
            hints.slurm_partition = m_part.group(1).strip()

        m_cpu = re.search(r"Max CPUs?[:\s]+(\d+)", experiment_text, re.IGNORECASE)
        if m_cpu:
            hints.slurm_max_cpus = int(m_cpu.group(1))

        # Fallback: if the experiment .md does not declare an explicit Max CPUs,
        # honor ARI_SLURM_CPUS exported by the wizard / api_experiment.py so the
        # LLM still receives the partition's CPU ceiling in its system prompt.
        if not hints.slurm_max_cpus:
            _env_cpus = _os.environ.get("ARI_SLURM_CPUS", "").strip()
            if _env_cpus.isdigit():
                hints.slurm_max_cpus = int(_env_cpus)

        # Auto-detect SLURM partition if not specified in experiment text
        if not hints.slurm_partition:
            _env_part = _os.environ.get("ARI_SLURM_PARTITION", "")
            if _env_part:
                hints.slurm_partition = _env_part
            else:
                try:
                    from ari.env_detect import get_slurm_partitions
                    _partitions = get_slurm_partitions()
                    _up = [p["name"] for p in _partitions if p.get("state") == "up"]
                    if _up:
                        hints.slurm_partition = _up[0]
                except Exception:
                    pass

    return hints
