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
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.protocols import NodeExecutor, SearchStrategy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 3: rubric loader for dynamic-axis evaluator wiring
# ---------------------------------------------------------------------------


def _load_rubric_dict_for_axes() -> "dict | None":
    """Load the active rubric as a parsed YAML dict.

    The dict is the **same shape** the rubric YAML files have on disk
    (id / score_dimensions / decision / etc.) — no Rubric dataclass is
    constructed because ``ari.evaluator.dynamic_axes.rubric_to_axes``
    accepts both shapes and we want to avoid a hard dependency on
    ari-skill-paper from ari-core.

    Source: ``ARI_RUBRIC`` env var (default ``neurips``) → YAML under
    ``ari-core/config/reviewer_rubrics/<id>.yaml``. Returns None when no
    rubric file is found, in which case the evaluator runs with the
    generic floor + plan-derived axes only.
    """
    rid = (os.environ.get("ARI_RUBRIC") or "neurips").strip()
    from ari.config.finder import package_config_root
    rubrics_dir = package_config_root() / "reviewer_rubrics"
    candidates = [rubrics_dir / f"{rid}.yaml"]
    if rid != "neurips":
        candidates.append(rubrics_dir / "neurips.yaml")  # safe fallback
    try:
        import yaml as _y
    except Exception:
        return None
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = _y.safe_load(p.read_text())
            if isinstance(data, dict):
                return data
        except Exception as e:
            log.warning("failed to load rubric %s: %s", p, e)
    return None


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
    # ReAct trace now lives in Letta. The
    # v0.5.x FileMemoryClient is kept only as a v0.5.x → v0.6.0 migration
    # source (`ari memory migrate --react`).
    from ari.memory.letta_client import LettaMemoryClient
    from ari.orchestrator.bfts import BFTS
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
    # the one-line swap.
    memory = LettaMemoryClient(checkpoint_dir=str(checkpoint_dir))
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
    # Wire the MCPClient into both LLMClients so cli-shim-targeted calls can
    # forward (--mcp-config + --allowedTools mcp__*) to the Claude
    # subprocess. With this, the text-catalog tool protocol is bypassed and
    # claude can ONLY call ari-skill MCP servers (no native Bash / Write /
    # Edit on the login node — see the 2026-05-28 hallucinated-environment incident).
    llm.mcp_client = mcp
    bfts_llm.mcp_client = mcp
    bfts: SearchStrategy = BFTS(cfg.bfts, bfts_llm)

    # MetricSpec: auto-generated from experiment file by evaluator-skill
    metric_spec = _make_metric_spec()

    # Evaluator may also use a phase-specific model override (ARI_MODEL_EVAL).
    _eval_model = _os_phase.environ.get("ARI_MODEL_EVAL") or llm._model_name()
    _eval_cfg = getattr(cfg, "evaluator", None)
    _axis_weights = getattr(_eval_cfg, "axis_weights", None) or None
    _composite = getattr(_eval_cfg, "composite", "harmonic_mean")
    _axis_mode = getattr(_eval_cfg, "axis_mode", "dynamic")
    # Layer C: dispatch on axis_mode.
    # - legacy: pin to the canonical 5-axis set (AXIS_NAMES); no rubric / plan input.
    # - custom: build AxisDef list from cfg.evaluator.custom_axes verbatim.
    # - dynamic (default): existing rubric + idea.json driven build.
    _eval_extra_kwargs: dict = {}
    if _axis_mode == "legacy":
        pass  # no axes / rubric / checkpoint_dir → llm_evaluator picks legacy
    elif _axis_mode == "custom":
        from ari.evaluator.dynamic_axes import AxisDef as _AxisDef
        _custom = getattr(_eval_cfg, "custom_axes", None) or []
        _eval_extra_kwargs["axes"] = [
            _AxisDef(
                name=a.name,
                description=a.description,
                source="custom",
                weight=float(a.weight),
            )
            for a in _custom
        ]
    else:
        # dynamic — Phase 3 path (rubric + plan-derived axes).
        _rubric_for_axes = _load_rubric_dict_for_axes()
        _eval_extra_kwargs["checkpoint_dir"] = str(checkpoint_dir)
        _eval_extra_kwargs["rubric"] = _rubric_for_axes
    # Forward the configured base_url to the judge whenever the evaluator is
    # pointed at the same local / OpenAI-compatible endpoint as the main client
    # (ollama, or a shim such as ari.llm.cli_server). A cloud ARI_MODEL_EVAL
    # override that swaps the model keeps api_base=None so litellm uses the
    # provider default rather than dialling the local endpoint.
    _eval_override = _os_phase.environ.get("ARI_MODEL_EVAL")
    _eval_uses_main_backend = (not _eval_override) or _eval_override == llm._model_name()
    _eval_api_base = (
        llm.config.base_url
        if (llm.config.base_url and _eval_uses_main_backend)
        else None
    )
    evaluator = LLMEvaluator(
        model=_eval_model,
        api_base=_eval_api_base,
        metric_spec=metric_spec,
        axis_weights=_axis_weights,
        composite=_composite,
        **_eval_extra_kwargs,
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

    agent: NodeExecutor = AgentLoop(
        llm, memory, mcp, evaluator=evaluator, workflow_hints=wf_hints,
        max_react_steps=cfg.bfts.max_react_steps,
        timeout_per_node=cfg.bfts.timeout_per_node,
    )
    return llm, memory, mcp, bfts, agent, metric_spec


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

    # Load pipeline from workflow.yaml (preferred) or pipeline.yaml (legacy
    # fallback). The per-checkpoint copy is searched first so launch-time
    # rewrites (e.g. include_ear=False disabling EAR / ors_seed_sandbox stages)
    # actually take effect — symmetrical with how the BFTS phase already reads
    # the checkpoint copy at cli.py:478.
    from ari.config.finder import package_config_root
    _pkg_cfg_root = package_config_root()
    pipeline_yaml_candidates = [
        Path(checkpoint_dir) / "workflow.yaml",
        Path(checkpoint_dir) / "pipeline.yaml",
        Path(config_path).parent / "workflow.yaml",
        Path(config_path).parent / "pipeline.yaml",
        _pkg_cfg_root / "workflow.yaml",
        _pkg_cfg_root / "pipeline.yaml",
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
