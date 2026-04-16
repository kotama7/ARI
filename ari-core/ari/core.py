"""Generic ARI runtime builder — zero domain-specific code.

cli.py only reads arguments and calls this module.
MetricSpec generation is delegated to evaluator-skill and not returned to cli.py.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MetricSpec: auto-generated from evaluator-skill
# ---------------------------------------------------------------------------

def _make_metric_spec():
    """Always returns the same generic MetricSpec. Zero domain knowledge.

    Evaluation is autonomously determined by LLMEvaluator from the goal text.
    No branching. No keyword parsing.
    """
    from ari.evaluator import MetricSpec
    import re as _re_num
    _pat = _re_num.compile(r"\b(\d+\.\d+|\d{4,})\b")

    def _generic_extractor(text: str) -> dict:
        nums = [float(x) for x in _pat.findall(text) if float(x) >= 1.0]
        return {"result_" + str(i): v for i, v in enumerate(nums[:20])}

    return MetricSpec(name="generic experiment", artifact_extractor=_generic_extractor)


# ---------------------------------------------------------------------------
# Runtime builder
# ---------------------------------------------------------------------------

def build_runtime(cfg, experiment_text: str = "", checkpoint_dir: "str | Path | None" = None):
    """Build and return a generic ARI runtime. No domain-specific code.

    Parameters
    ----------
    checkpoint_dir : str | Path
        Required.  Agent memory is stored per-run at
        ``{checkpoint_dir}/memory.json``.  ARI no longer supports a global
        fallback under ``~/.ari``.
    """
    from ari.agent.loop import AgentLoop
    from ari.agent.workflow import from_experiment_text, enrich_hints_from_mcp
    from ari.evaluator import LLMEvaluator
    from ari.llm.client import LLMClient
    from ari.mcp.client import MCPClient
    from ari.memory.file_client import FileMemoryClient
    from ari.orchestrator.bfts import BFTS
    from ari.orchestrator.scheduler import Scheduler
    from ari.paths import PathManager

    if checkpoint_dir is None:
        raise ValueError(
            "build_runtime requires checkpoint_dir — agent memory is "
            "project-scoped and no global fallback exists."
        )
    # Phase-specific model overrides: the GUI Settings page writes
    # ARI_MODEL_CODING / ARI_MODEL_BFTS / ARI_MODEL_EVAL so callers can use a
    # different LLM for the ReAct agent, the BFTS orchestrator, and evaluation.
    # Skills running as subprocesses read their own phase env directly; BFTS
    # and the AgentLoop live in-process and share the same LLMClient class, so
    # we construct a dedicated client per phase here.
    import os as _os_phase
    from copy import copy as _copy_phase

    def _phase_llm(phase: str) -> LLMClient:
        _override = _os_phase.environ.get(f"ARI_MODEL_{phase.upper()}")
        if not _override:
            return LLMClient(cfg.llm)
        _pc = _copy_phase(cfg.llm)
        _pc.model = _override
        return LLMClient(_pc)

    llm = _phase_llm("coding")          # AgentLoop / ReAct
    bfts_llm = _phase_llm("bfts")       # BFTS orchestrator
    memory = FileMemoryClient(str(PathManager.project_memory_path(checkpoint_dir)))
    _disabled = list(cfg.disabled_tools)
    _skills = list(cfg.skills)
    if not cfg.resources.get("hpc_enabled", True):
        # Laptop profile: drop the hpc-skill entirely. Its SLURM/Singularity
        # tools (slurm_submit, singularity_build/pull/run/run_gpu) would
        # otherwise submit sbatch jobs from inside the skill even when the
        # agent is not supposed to use HPC at all. run_bash lives in
        # coding-skill, so removing hpc-skill does not remove shell access.
        _skills = [s for s in _skills if getattr(s, "name", "") != "hpc-skill"]
    mcp = MCPClient(_skills, disabled_tools=_disabled)
    bfts = BFTS(cfg.bfts, bfts_llm)

    # MetricSpec: auto-generated from experiment file by evaluator-skill
    metric_spec = _make_metric_spec()

    # Evaluator may also use a phase-specific model override (ARI_MODEL_EVAL).
    _eval_model = _os_phase.environ.get("ARI_MODEL_EVAL") or llm._model_name()
    evaluator = LLMEvaluator(
        model=_eval_model,
        api_base=llm.config.base_url if llm.config.backend == "ollama" else None,
        metric_spec=metric_spec,
    )

    # WorkflowHints: auto-extracted from experiment file
    hpc_enabled = cfg.resources.get("hpc_enabled", True)
    wf_hints = from_experiment_text(experiment_text, hpc_enabled=hpc_enabled)

    # Enrich hints with dynamically discovered MCP tools (phase=bfts)
    try:
        bfts_tools = mcp.list_tools(phase="bfts")
        enrich_hints_from_mcp(wf_hints, bfts_tools, hpc_enabled=hpc_enabled)
    except Exception:
        pass  # Graceful fallback — static hints still work

    # metric_extractor: generated by workflow.py from metric_keyword; falls back to MetricSpec extractor
    if wf_hints.metric_extractor is None and metric_spec and metric_spec.artifact_extractor:
        wf_hints.metric_extractor = metric_spec.artifact_extractor

    agent = AgentLoop(llm, memory, mcp, evaluator=evaluator, workflow_hints=wf_hints,
                       max_react_steps=cfg.bfts.max_react_steps,
                       timeout_per_node=cfg.bfts.timeout_per_node)
    scheduler = Scheduler(cfg.bfts)
    return llm, memory, mcp, bfts, agent, scheduler, metric_spec


# ---------------------------------------------------------------------------
# Paper section generation (generic)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Post-BFTS pipeline (driven by pipeline.yaml)
# ---------------------------------------------------------------------------

def generate_paper_section(
    all_nodes, experiment_data: dict, checkpoint_dir: Path, mcp, config_path: str
) -> None:
    """Run the post-BFTS pipeline according to pipeline.yaml. No hardcoding."""
    from ari.pipeline import load_pipeline, run_pipeline

    log.info("Starting paper pipeline (config_path=%s, checkpoint=%s)", config_path, checkpoint_dir)
    print(f"\n{'='*60}")
    print(f"  Paper Pipeline Starting")
    print(f"  Checkpoint: {checkpoint_dir}")
    print(f"{'='*60}", flush=True)

    # Load pipeline from workflow.yaml (preferred) or pipeline.yaml (legacy fallback)
    pipeline_yaml_candidates = [
        Path(config_path).parent / "workflow.yaml",
        Path(config_path).parent / "pipeline.yaml",
        Path(__file__).parent.parent / "config" / "workflow.yaml",
        Path(__file__).parent.parent / "config" / "pipeline.yaml",
    ]
    pipeline_yaml = next((p for p in pipeline_yaml_candidates if p.exists()), None)

    if pipeline_yaml is None:
        log.error("pipeline.yaml not found in any candidate path; skipping post-BFTS pipeline. Searched: %s",
                  [str(p) for p in pipeline_yaml_candidates])
        print("[Paper Pipeline] ERROR: workflow.yaml not found, skipping paper generation", flush=True)
        return

    log.info("Using pipeline config: %s (%d candidates searched)", pipeline_yaml,
             len(pipeline_yaml_candidates))

    stages = load_pipeline(pipeline_yaml)
    if not stages:
        log.error("No enabled pipeline stages in %s", pipeline_yaml)
        print(f"[Paper Pipeline] ERROR: No enabled stages in {pipeline_yaml}", flush=True)
        return

    stage_names = [s.get("stage", "?") for s in stages]
    log.info("Paper pipeline: %d stages to execute", len(stages))
    print(f"[Paper Pipeline] {len(stages)} stages: {', '.join(stage_names)}", flush=True)
    result = run_pipeline(stages, all_nodes, experiment_data, checkpoint_dir, config_path)
    log.info("Paper pipeline completed: %s", list(result.keys()) if result else "no result")
    print(f"[Paper Pipeline] Complete: {list(result.keys()) if result else 'no result'}", flush=True)
