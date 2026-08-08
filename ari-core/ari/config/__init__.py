"""Configuration models for ARI using Pydantic."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from ari.config.skill_runtime import manifest_runtime_metadata
from ari.skill_manifest import (
    MANIFEST_FILENAME,
    SkillManifestV1,
    load_skill_manifest,
    resolve_skill_entrypoint,
)


logger = logging.getLogger(__name__)


class ClaudeCodeSettings(BaseModel):
    """Settings for the `claude_code` backend (Claude Code as an LLM API).

    Mapped onto a frozen `ari.llm.claude_code.policy.ClaudeCodePolicy` and
    fail-loud validated there; these fields only *declare* the policy. See
    docs/reference/claude_code_provider.md for semantics and rationale.
    """

    mode: Literal["strict_reproducibility", "low_overhead"] = Field(
        "strict_reproducibility",
        description="strict_reproducibility = fresh `claude -p` subprocess "
                    "per call; low_overhead = resident Agent SDK worker with "
                    "a fresh query per request (never session resume). "
                    "Overridden by `ARI_CLAUDE_CODE_MODE`.",
    )
    max_turns: int = Field(
        1,
        description="--max-turns per call. Values > 1 require "
                    "allow_multi_turn (policy fail-loud otherwise).",
    )
    allow_multi_turn: bool = Field(
        False,
        description="Explicit opt-in required for max_turns > 1.",
    )
    timeout_sec: int = Field(
        300,
        description="Per-call subprocess/SDK timeout in seconds. Overridden "
                    "by `ARI_CLAUDE_CODE_TIMEOUT_SEC`.",
    )
    output_format: Literal["json"] = Field(
        "json",
        description="Claude Code --output-format. Only `json` (single "
                    "result envelope) is supported in LLM API mode.",
    )
    hermetic: bool = Field(
        True,
        description="strict mode: run the subprocess under an env ALLOWLIST "
                    "(auth/proxy/locale only) instead of inheriting the full "
                    "environment. Recorded in env_allowlist.json.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Claude Code tools to enable. Must stay empty in LLM "
                    "API mode (policy fail-loud).",
    )
    disallowed_tools: list[str] = Field(
        default_factory=lambda: ["*"],
        description='--disallowedTools deny list; must contain "*".',
    )
    disable_auto_memory: bool = Field(
        True,
        description="Force CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 on the "
                    "subprocess (policy requires True).",
    )
    disable_prompt_history: bool = Field(
        True,
        description="Force CLAUDE_CODE_SKIP_PROMPT_HISTORY=1 on the "
                    "subprocess (policy requires True).",
    )
    bare: bool | None = Field(
        None,
        description="--bare (skip hooks/plugins/CLAUDE.md/auto-memory; auth "
                    "strictly ANTHROPIC_API_KEY). null = auto: true iff "
                    "ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN is set (OAuth "
                    "logins would break under --bare). The auto decision is "
                    "recorded in provenance as bare_auto_resolved.",
    )
    safe_mode: bool = Field(
        True,
        description="--safe-mode: all customizations (CLAUDE.md, skills, "
                    "plugins, hooks, MCP, commands) disabled.",
    )
    strict_mcp_config: bool = Field(
        True,
        description="--strict-mcp-config with no --mcp-config = no MCP "
                    "servers at all (policy requires True).",
    )
    disable_slash_commands: bool = Field(
        True, description="--disable-slash-commands (no skills)."
    )
    no_chrome: bool = Field(True, description="--no-chrome.")
    no_session_persistence: bool = Field(
        True,
        description="--no-session-persistence: session never written to "
                    "disk, cannot be resumed (policy requires True).",
    )
    permission_mode: str = Field(
        "plan",
        description="--permission-mode for tool-less text calls. The native "
                    "structured-output transport overrides it to `default` "
                    "per schema call (StructuredOutput tool round-trip).",
    )
    setting_sources: list[str] = Field(
        default_factory=list,
        description="--setting-sources allowlist (user/project/local). "
                    "Empty = no settings files are loaded.",
    )
    record_provenance: bool = Field(
        True,
        description="Persist per-call artifacts under "
                    "{checkpoint}/claude_code/{call_id}/ (prompt, command, "
                    "env allowlist, stdout/stderr, hashes, validation). "
                    "Overridden by `ARI_CLAUDE_CODE_RECORD_PROVENANCE`.",
    )
    structured_output_transport: Literal["prompt", "native"] = Field(
        "prompt",
        description="How response_schema reaches Claude Code: `prompt` "
                    "embeds the schema in the prompt (keeps the strictest "
                    "flag profile); `native` passes --json-schema (needs "
                    "--allowedTools StructuredOutput, permission-mode "
                    "default and 2 turns; verified on 2.1.198). ARI-side "
                    "jsonschema validation runs in BOTH cases.",
    )
    schema_repair_retries: int = Field(
        1,
        description="Max repair retries after schema-validation failure "
                    "(capped at 1; same hermetic policy, trace saved).",
    )
    home_mode: Literal["auto", "real", "sandbox"] = Field(
        "auto",
        description="HOME for the subprocess. sandbox = per-call temp HOME "
                    "(requires API-key auth); real = keep $HOME; auto = "
                    "sandbox only when --bare resolved true with a key.",
    )
    env_allowlist_extra: list[str] = Field(
        default_factory=list,
        description="Extra env var NAMES to pass through in hermetic mode.",
    )
    claude_bin: str = Field(
        "claude",
        description="Claude Code binary. Overridden by "
                    "`ARI_CLAUDE_CODE_BIN`.",
    )
    compat_drop_flags: list[str] = Field(
        default_factory=list,
        description="Flags the operator explicitly allows dropping when the "
                    "installed Claude Code rejects them (recorded in "
                    "provenance as unsupported_flags). Without this an "
                    "unknown option fails loudly — isolation is never "
                    "weakened silently.",
    )
    sdk_fallback_to_cli: bool = Field(
        False,
        description="low_overhead only: fall back to the strict CLI runner "
                    "when claude-agent-sdk is not installed. Default is a "
                    "loud error.",
    )


class HandoffConfig(BaseModel):
    """What a BFTS child inherits from its parent (handoff study).

    Default ``mode="disabled"`` preserves current ARI behaviour (parent
    work_dir copy + existing planner-side report block + ancestor memory ON,
    no new agent-prompt injection). The study selects a named arm via
    ``ARI_HANDOFF_MODE``; the ``_resolve_mode`` validator then fixes the
    per-channel switches below from the mode. Individual switches may be
    overridden afterwards for ablation via ``apply_handoff_env_overrides``.
    See ari-core/PREREG_handoff_study.md and ari-core/ari/config/Plan.md.
    """

    mode: Literal[
        "disabled",
        "code_only",
        "evidence_only",
        "evidence_plus_reflection",
        "summary_only",
        "code_plus_summary",
        "code_plus_full_log",
        "code_plus_summary_plus_full_log",
        "code_plus_truncated_log",
        "rolling_summary",
        "failure_only_summary",
    ] = Field(
        "disabled",
        description="Handoff arm. `disabled` = current ARI behaviour (no "
                    "study manipulation). Overridden by `ARI_HANDOFF_MODE`.",
    )
    copy_workdir: bool = Field(
        True,
        description="Inherit parent code artifacts via work_dir copy "
                    "(the artifact channel). `ARI_HANDOFF_COPY_WORKDIR`.",
    )
    inject_agent_block: bool = Field(
        False,
        description="Inject the structured node summary into the child "
                    "agent's first user message (agent-face summary channel). "
                    "`ARI_HANDOFF_AGENT_BLOCK`.",
    )
    inject_planner_block: bool = Field(
        True,
        description="Keep the existing node_report block in the BFTS "
                    "planner/expand prompt. `ARI_HANDOFF_PLANNER_BLOCK`.",
    )
    log_mode: Literal["none", "full", "truncated", "masked"] = Field(
        "none",
        description="Parent run-log delivered into the child prompt "
                    "(the log channel). `ARI_HANDOFF_LOG_MODE`.",
    )
    log_truncate_chars: int = Field(
        4000,
        description="Tail length kept when log_mode=`truncated`.",
    )
    summary_form: Literal[
        "extractive", "rolling", "failure_only",
        "evidence", "evidence_reflection",
    ] = Field(
        "extractive",
        description="Form of the structured summary when inject_agent_block "
                    "is on. `ARI_HANDOFF_SUMMARY_FORM`.",
    )
    summary_fields_enabled: list[str] = Field(
        default_factory=lambda: [
            "outcome", "changed_files", "concerns",
            "next_steps", "known_failures", "key_metrics",
        ],
        description="Operational-state fields included in the summary. The "
                    "RQ-B field ablation removes one at a time via "
                    "`ARI_HANDOFF_SUMMARY_FIELDS` (comma-separated).",
    )
    memory_off: bool = Field(
        False,
        description="Gate ALL ancestor/run-level memory injection "
                    "(Tier-1a/1b/1c/2 + window pin) so an arm receives no "
                    "operational state beyond the explicit handoff channels. "
                    "Required for clean code_only/summary_only. "
                    "`ARI_HANDOFF_MEMORY_OFF`.",
    )

    # Canonical mode -> channel resolution. memory_off is True for every
    # experimental arm so the de-facto memory channel cannot leak (B1); the
    # planner block is also off for study arms so the agent-face channel is
    # the only summary surface under test.
    _MODE_SPEC = {
        "code_only":               ("copy", False, "none",      "extractive"),
        # New evidence/reflection study arms. Both inherit the same parent code
        # workspace; evidence_plus_reflection adds ONLY the agent's own
        # interpretation / concerns / next-step hints on top of the identical
        # objective evaluator+harness evidence carried by evidence_only.
        "evidence_only":           ("copy", True,  "none",      "evidence"),
        "evidence_plus_reflection": ("copy", True,  "none",      "evidence_reflection"),
        "summary_only":            ("nocopy", True, "none",      "extractive"),
        "code_plus_summary":       ("copy", True,  "none",      "extractive"),
        "code_plus_full_log":      ("copy", False, "full",      "extractive"),
        # Nested/cumulative arm: code ⊂ code+summary ⊂ code+summary+full_log.
        # Tests whether the (expensive) full log adds value ON TOP of the (cheap)
        # summary, rather than summary-vs-log as two separate single channels.
        "code_plus_summary_plus_full_log": ("copy", True, "full", "extractive"),
        "code_plus_truncated_log": ("copy", False, "truncated", "extractive"),
        "rolling_summary":         ("copy", True,  "none",      "rolling"),
        "failure_only_summary":    ("copy", True,  "none",      "failure_only"),
    }

    @model_validator(mode="after")
    def _resolve_mode(self) -> "HandoffConfig":
        if self.mode == "disabled":
            return self  # passthrough: current ARI behaviour
        copy, agent, log, form = self._MODE_SPEC[self.mode]
        self.copy_workdir = (copy == "copy")
        self.inject_agent_block = agent
        self.log_mode = log
        self.summary_form = form
        self.inject_planner_block = False
        self.memory_off = True
        return self


class LLMConfig(BaseModel):
    backend: str = Field(
        "ollama",
        description="LLM backend identifier consumed by the agent loop "
                    "(`ollama`, `openai`, `claude_code`, `litellm`, ...). "
                    "Overridden by the `ARI_BACKEND` environment variable.",
    )
    model: str = Field(
        "qwen3:8b",
        description="LiteLLM-style model identifier. Overridden by "
                    "`ARI_MODEL` / `ARI_LLM_MODEL` env vars at load time.",
    )
    api_key: str | None = Field(
        None,
        description="API key for the chosen backend. Prefer setting via "
                    "the provider-specific env var (`OPENAI_API_KEY`, ...).",
    )
    base_url: str | None = Field(
        None,
        description="API base URL override. Required when pointing at a "
                    "self-hosted Ollama / OpenAI-compatible endpoint; "
                    "overridden by `ARI_LLM_API_BASE` / `OLLAMA_HOST`.",
    )
    temperature: float = Field(
        0.7,
        description="Sampling temperature applied to non-judge LLM calls.",
    )
    seed: int | None = Field(
        None,
        description="Fixed sampling seed forwarded to litellm/Ollama for "
                    "reproducible local-model runs (handoff study). `None` "
                    "leaves sampling unseeded (current behaviour). Overridden "
                    "by `ARI_SEED`. Note: GPU inference is not bit-exact even "
                    "with a seed; n-runs still absorb residual non-determinism.",
    )
    claude_code: ClaudeCodeSettings = Field(
        default_factory=ClaudeCodeSettings,
        description="Settings for `backend: claude_code` (Claude Code as an "
                    "LLM-API-compatible provider); ignored by every other "
                    "backend. See docs/reference/claude_code_provider.md.",
    )


class SkillConfig(BaseModel):
    name: str = Field(
        ...,
        description="Runtime Skill alias (e.g. `coding-skill`).",
    )
    path: str = Field(
        ...,
        description="Filesystem path to the skill package root.",
    )
    description: str = Field(
        "",
        description="Optional human-readable description; mirrors "
                    "`mcp.json:description` when present.",
    )
    phase: str | list[str] = Field(
        "all",
        description="Pipeline phase(s) in which this skill is exposed to "
                    "the AgentLoop ReAct. Single string (`bfts` / `paper` "
                    "/ `reproduce` / `all` / `none`) or a list. `all` "
                    "matches any phase; `none` disables the skill.",
    )
    package: str = Field(
        "",
        description="Canonical package identity from skill.yaml.",
    )
    version: str = Field(
        "",
        description="Canonical package version from skill.yaml.",
    )
    manifest_path: str | None = Field(
        None,
        description="Resolved path to the canonical skill.yaml, when present.",
    )
    entrypoint: str = Field(
        "src/server.py",
        description="Package-relative Python MCP server entrypoint.",
    )
    enabled_by_default: bool = Field(
        True,
        description="Whether auto-discovery admits this Skill by default.",
    )
    environment_policy: Literal["audit-pending", "complete"] = Field(
        "audit-pending",
        description="Whether manifest environment declarations are exhaustive.",
    )
    required_env: list[str] = Field(
        default_factory=list,
        description="Environment names required by the Skill contract.",
    )
    optional_env: list[str] = Field(
        default_factory=list,
        description="Optional environment names declared by the Skill contract.",
    )
    credential_scopes: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description="Named credential scopes and their required/optional env names.",
    )
    credential_scope_identities: list[dict] = Field(
        default_factory=list,
        description="Runtime-only value-free credential authority identities.",
        exclude=True,
    )
    tool_timeout_classes: dict[str, str] = Field(
        default_factory=dict,
        description="Resolved manifest timeout class keyed by runtime tool name.",
    )
    manifest_digest: str = Field(
        "", description="SHA-256 digest of the normalized canonical manifest."
    )
    tool_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Declared immutable tool references keyed by runtime name.",
    )
    tool_capabilities: dict[str, str] = Field(
        default_factory=dict,
        description="Semantic capability references keyed by runtime tool name.",
    )
    tool_policies: dict[str, dict] = Field(
        default_factory=dict,
        description="Resolved side-effect, determinism, phase, and permission policy.",
    )


class BFTSConfig(BaseModel):
    max_depth: int = Field(
        5,
        description="Hard cap on BFTS tree depth. Overridden by "
                    "`ARI_MAX_DEPTH`.",
    )
    max_total_nodes: int = Field(
        50,
        description="Hard cap on total BFTS nodes per run. Overridden "
                    "by `ARI_MAX_NODES`.",
    )
    max_react_steps: int = Field(
        20,
        description="Maximum ReAct iterations within a single node. "
                    "Overridden by `ARI_MAX_REACT`. 20 rather than the former "
                    "80: on the previous campaign the number of steps a node "
                    "needed to reach its own best result was p50=3, p90=13, "
                    "p95=15, p99=20, so 20 covers virtually every node that was "
                    "going to improve. The tail was not productive search - "
                    "raising the cap from 25 to 40 bought about 28 more nodes, "
                    "not the 101 a linear reading would predict.",
    )
    timeout_per_node: int = Field(
        7200,
        description="Per-node wall-time budget in seconds. Overridden "
                    "by `ARI_TIMEOUT_NODE`.",
    )
    max_parallel_nodes: int = Field(
        4,
        description="Maximum BFTS nodes that may execute concurrently. "
                    "Overridden by `ARI_PARALLEL`.",
    )
    max_expansions_per_node: int = Field(
        4,
        description="Maximum times a single frontier node may be re-expanded "
                    "before BFTS retires it. Higher values let one good "
                    "parent spawn more siblings; lower values force the "
                    "search to spread.",
    )
    label_saturation_threshold: int = Field(
        2,
        description="When ≥ this many children of the SAME parent share a "
                    "label, expand() flags that label as 'saturated' in the "
                    "next prompt and asks the planner to pick a different "
                    "one. Default 2 matches the pre-audit behaviour.",
    )
    frontier_score: Literal[
        "scientific_plus_diversity",
        "scientific_only",
        "depth_penalized",
        "ucb_like",
    ] = Field(
        "scientific_plus_diversity",
        description="Strategy used by BFTS's deterministic fallback when "
                    "the LLM selector cannot pick a candidate. "
                    "`scientific_plus_diversity` (default) matches the "
                    "previous behaviour. `scientific_only` drops the "
                    "diversity bonus. `depth_penalized` subtracts "
                    "`depth_penalty_lambda * depth`. `ucb_like` adds a "
                    "UCB1-style exploration term scaled by `ucb_c`.",
    )
    depth_penalty_lambda: float = Field(
        0.05,
        description="Per-depth penalty applied when frontier_score="
                    "`depth_penalized`. Ignored by other strategies.",
    )
    ucb_c: float = Field(
        0.5,
        description="Exploration coefficient for frontier_score="
                    "`ucb_like`. The exploration term is "
                    "`ucb_c * sqrt(log(N) / (visits + 1))`. Ignored by "
                    "other strategies.",
    )
    deterministic_selector: bool = Field(
        False,
        description="Handoff study (G9a): bypass the stochastic LLM node "
                    "selector and rank candidates purely by the deterministic "
                    "frontier scorer (`frontier_score`), so node selection is "
                    "reproducible and the handoff arm is the only varying "
                    "factor. This scorer choice is PRE-REGISTERED, not merely "
                    "implemented. Requires a populated "
                    "`_scientific_score` (deterministic evaluator). Overridden "
                    "by `ARI_BFTS_DETERMINISTIC`.",
    )
    select_prompt: str = Field(
        "orchestrator/bfts_select",
        description="FilesystemPromptLoader key for select_next_node. "
                    "The .md template must accept {experiment_goal}, "
                    "{memory_context}, and {candidates} placeholders and "
                    "must reply with a single 0-based integer index.",
    )
    expand_select_prompt: str = Field(
        "orchestrator/bfts_expand_select",
        description="FilesystemPromptLoader key for select_best_to_expand. "
                    "Template must accept {experiment_goal} and "
                    "{candidates} and reply with a 0-based integer index.",
    )
    expand_prompt: str = Field(
        "orchestrator/bfts_expand",
        description="FilesystemPromptLoader key for BFTS.expand (RQGM Task "
                    "07 §7: mirrors select_prompt so the expansion prompt "
                    "is swappable too). The template must accept the "
                    "build_expand_context placeholder set and reply with a "
                    "JSON array of one direction object. Default preserves "
                    "the previous hardcoded key byte-for-byte.",
    )
    allow_web: bool = Field(
        False,
        description="Opt-in: expose web-skill (web_search / fetch_url / "
                    "search_papers / walk_citations) to the BFTS node "
                    "agent during exploration. Default False keeps the search "
                    "loop reproducible (P5) — live web results are "
                    "time-varying. When True, ARI records a "
                    "non-reproducible-trajectory marker "
                    "(`bfts_web_provenance.json`). Overridden by "
                    "`ARI_BFTS_ALLOW_WEB` (1/true/yes/on). Note: idea-skill's "
                    "`survey` already provides a bounded literature lookup "
                    "during bfts regardless of this flag.",
    )


class CheckpointConfig(BaseModel):
    dir: str = Field(
        "./workspace/checkpoints/{run_id}/",
        description="Checkpoint root template. `{run_id}` is substituted "
                    "at run start. Overridden by `ARI_CHECKPOINT_DIR` "
                    "(an explicit env path always wins). Roots under "
                    "`workspace/` per subtask 004 P2 ('workspace/ wins'); the "
                    "legacy `./checkpoints/{run_id}/` form stays resolvable.",
    )


class LoggingConfig(BaseModel):
    level: str = Field(
        "INFO",
        description="Python `logging` level. Overridden by "
                    "`ARI_LOG_LEVEL`.",
    )
    dir: str = Field(
        "./workspace/checkpoints/{run_id}/",
        description="Log directory. Defaults to the active checkpoint "
                    "(via `ARI_LOG_DIR` or `ARI_CHECKPOINT_DIR`). Roots under "
                    "`workspace/` per subtask 004 P2, matching CheckpointConfig.",
    )
    format: str = Field(
        "json",
        description="Log record format (`json` for machine-parseable "
                    "lines or `text` for human-readable).",
    )


class CustomAxisSpec(BaseModel):
    """One user-defined evaluation axis used when EvaluatorConfig.axis_mode=`custom`."""

    name: str = Field(..., description="Axis identifier (snake_case).")
    description: str = Field(
        "",
        description="Short prose describing what the axis measures. Sent to "
                    "the judge LLM so it knows how to score this axis.",
    )
    weight: float = Field(
        0.2,
        description="Per-axis weight used by the composite formula. "
                    "Normalisation is handled by the formula itself.",
    )


class EvaluatorConfig(BaseModel):
    axis_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Per-axis weight overrides for the BFTS judge. "
                    "Empty → equal weights (0.2 each). Only keys in "
                    "the canonical axis set are honoured; unknown keys "
                    "are silently dropped.",
    )
    composite: Literal[
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    ] = Field(
        "harmonic_mean",
        description="Formula used to collapse per-axis scores into the "
                    "scalar `_scientific_score`. `harmonic_mean` (default) "
                    "matches the pre-audit behaviour and heavily penalises "
                    "any weak axis. `arithmetic_mean` is permissive. "
                    "`weighted_min` returns the lowest axis (bottleneck "
                    "view). `geometric_mean` is between harmonic and "
                    "arithmetic.",
    )
    axis_mode: Literal["legacy", "dynamic", "custom"] = Field(
        "dynamic",
        description="`dynamic` (default) builds axes from the active rubric "
                    "and idea.json plan keywords. `legacy` pins to the "
                    "fixed 5-axis canonical set. `custom` uses the "
                    "`custom_axes` list verbatim.",
    )
    custom_axes: list[CustomAxisSpec] = Field(
        default_factory=list,
        description="Axis definitions consulted only when "
                    "axis_mode=`custom`.",
    )


class AriModeConfig(BaseModel):
    """Top-level ``ari:`` block (docs/reference/configuration.md,
    "Activation: ``ari.mode`` + ``rqgm.enabled``")."""

    mode: Literal["simple_bfts", "ari_rqgm"] = Field(
        "simple_bfts",
        description="Execution mode. `simple_bfts` (default) preserves "
                    "current ARI behaviour unchanged; `ari_rqgm` opts in to "
                    "Constitutional ARI-RQGM epoch governance and ALSO "
                    "requires `rqgm.enabled: true` (any disagreement fails "
                    "safe to `simple_bfts`). Overridden by `ARI_MODE`.",
    )


class PaperConfig(BaseModel):
    """Top-level ``paper:`` block (docs/guides/execution_modes.md,
    "The paper execution axis: ``paper.mode``").

    The paper-phase execution-mode switch, orthogonal to the exploration
    ``ari.mode``. ``linear`` (default) preserves the current paper pipeline
    byte-for-byte; ``rqgm_archive`` opts in to paper-archive co-evolution and
    ALSO requires ``rqgm.paper.enabled: true`` (any disagreement fails safe
    to ``linear``). Overridden by ``ARI_PAPER_MODE``."""

    mode: Literal["linear", "rqgm_archive"] = Field(
        "linear",
        description="Paper-phase execution mode. `linear` (default) is "
                    "byte-identical to today's paper pipeline; `rqgm_archive` "
                    "opts in to the best-first draft archive and ALSO "
                    "requires `rqgm.paper.enabled: true`. Overridden by "
                    "`ARI_PAPER_MODE`.",
    )


class ManuscriptRepairConfig(BaseModel):
    """Bounded research-repair posture for Manuscript Complete."""

    policy: Literal["disabled", "explicit", "auto"] = Field(
        "disabled",
        description="disabled only reports gaps; explicit requires a named repair "
                    "operation; auto runs the bounded outer coordinator and is "
                    "valid only with manuscript.mode=enforce.",
    )
    max_rounds: int = Field(2, ge=0, le=100)
    max_new_nodes: int = Field(8, ge=0, le=100_000)
    max_experiment_runs: int = Field(12, ge=0, le=100_000)
    max_llm_calls: int = Field(8, ge=0, le=100_000)
    max_resource_units: float | None = Field(default=None, ge=0)
    on_exhaustion: Literal["block"] = "block"


class ManuscriptConfig(BaseModel):
    """Exploration-to-authoring completeness posture.

    The switch is independent of both ``ari.mode`` and ``paper.mode``.  The
    default ``off`` path performs no manuscript imports or artifact writes.
    """

    mode: Literal["off", "audit", "enforce"] = Field(
        "off",
        description="off preserves the current paper path; audit records a "
                    "shadow completeness assessment; enforce blocks authoring "
                    "until authoring requirements are resolved.",
    )
    profile: str = Field("generic_empirical_v1", min_length=1, max_length=256)
    brief_character_budget: int = Field(24_000, ge=1_000, le=2_000_000)
    repair: ManuscriptRepairConfig = Field(default_factory=ManuscriptRepairConfig)

    @model_validator(mode="after")
    def _validate_repair_posture(self) -> "ManuscriptConfig":
        if self.repair.policy == "auto" and self.mode != "enforce":
            raise ValueError(
                "manuscript.repair.policy=auto requires manuscript.mode=enforce"
            )
        return self


class KnowledgeRuntimeConfig(BaseModel):
    """Non-executable Knowledge Skill activation posture (Task 16)."""

    mode: Literal["off", "audit", "enforce"] = Field(
        "off",
        description="off preserves the legacy prompt path; audit injects and records "
                    "verified content without coverage blocking; enforce requires an "
                    "immutable admitted Knowledge lock.",
    )


class CapabilityBindingRuntimeConfig(BaseModel):
    """Semantic Provider-tool binding posture (Task 17)."""

    mode: Literal["legacy", "audit", "enforce"] = Field(
        "legacy",
        description="legacy preserves current MCP discovery/visibility; audit records "
                    "semantic decisions; enforce exposes and invokes only bound tools.",
    )
    required_capability_refs: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Capabilities this run needs regardless of which Knowledge Skills "
                    "were admitted. Knowledge is the only other requirement source, so "
                    "a domain instrument no Knowledge Skill mentions can otherwise "
                    "never be required, and therefore never bound. Operator input: it "
                    "is not derived from a model, and every ref must exist in the "
                    "reviewed ontology.",
    )
    optional_capability_refs: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Capabilities to bind when available. Unlike required refs these "
                    "do not fail a run in enforce mode when nothing supplies them.",
    )

    @field_validator("required_capability_refs", "optional_capability_refs")
    @classmethod
    def _unique_sorted_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({str(item).strip() for item in values if str(item).strip()}))
        for ref in normalized:
            if not re.fullmatch(r"ari\.[a-z0-9][a-z0-9.-]*/v[1-9][0-9]*", ref):
                raise ValueError(f"not a capability reference: {ref!r}")
        return normalized

    @model_validator(mode="after")
    def _requirement_classes_are_disjoint(self):
        overlap = sorted(
            set(self.required_capability_refs) & set(self.optional_capability_refs)
        )
        if overlap:
            raise ValueError(
                f"a capability cannot be both required and optional: {overlap}"
            )
        return self


class AssuranceRuntimeConfig(BaseModel):
    """Independent Harness execution and frontier/publication gate posture."""

    mode: Literal["off", "audit", "enforce"] = Field(
        "off",
        description="off emits no assurance artifacts; audit verifies without gating; "
                    "enforce gates scientific frontier and publication certification.",
    )


class RQGMEpochConfig(BaseModel):
    """``rqgm.epoch:`` block (docs/reference/configuration.md,
    "``rqgm.epoch`` — epoch-boundary sizing").

    Sizing of the epoch-boundary trigger. v1 supports only the node-count
    boundary; richer trigger policy (stagnation events, ...) is Task 05's.
    Defaults mirror ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_state_store.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    boundary: Literal["node_count"] = Field(
        "node_count",
        description="Epoch-boundary trigger kind. v1: only `node_count` "
                    "(a boundary transaction fires every `nodes_per_epoch` "
                    "new BFTS nodes).",
    )
    nodes_per_epoch: int = Field(
        10,
        description="Number of new nodes after which the epoch-boundary "
                    "transaction fires. <= 0 disables automatic boundaries "
                    "(the run stays in epoch_000).",
    )


class RQGMKernelConfig(BaseModel):
    """``rqgm.kernel:`` block (docs/reference/configuration.md,
    "``rqgm.kernel`` — ConstitutionalKernel posture").

    Enforcement posture of the ConstitutionalKernel adapters. The rule
    tables themselves are frozen code (``ari/rqgm/kernel_rules.py`` +
    ``ari/rqgm/transition_rules.py``) and deliberately NOT configurable;
    only the posture and numeric tolerances live here. Defaults mirror
    ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_kernel.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enforcement: Literal["standard", "audit_only"] = Field(
        "standard",
        description="`standard` applies the kernel's per-context blocking "
                    "matrix (frozen code in `ari/rqgm/kernel_rules.py`); "
                    "`audit_only` downgrades every context to warn-and-log "
                    "(ablation conditions B4-B6 / Stage-1 rollout). Read at "
                    "run start / epoch boundaries only, never hot-switched "
                    "mid-epoch.",
    )
    audit_chain: Literal["auto"] = Field(
        "auto",
        description="Audit-log chain verification posture. v1: only `auto` "
                    "(verify the hash chain iff chain fields are present).",
    )
    float_tolerance: float = Field(
        1e-9,
        description="Single float-comparison tolerance used by kernel "
                    "checks (docs/reference/configuration.md, "
                    "`rqgm.kernel` — ConstitutionalKernel posture).",
    )


class RQGMGovernanceConfig(BaseModel):
    """``rqgm.governance:`` block (docs/reference/configuration.md,
    "``rqgm.governance`` — GovernanceOrchestrator budgets and posture").

    Budget knobs and posture of the epoch-boundary GovernanceOrchestrator
    (``audit_epoch``). Task 12 owns the budget *numbers*; this task owns the
    consumption points. Defaults mirror ``ari/configs/defaults.yaml``
    (parity pinned by ``tests/test_rqgm_governance.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Epoch-boundary governance audit on/off inside "
                    "`ari_rqgm` mode (the evaluation ladder needs it off: "
                    "ablation rungs B2-B4 run `ari_rqgm` with governance "
                    "off). Meaningful only when `ari.mode: ari_rqgm` and "
                    "`rqgm.enabled: true` agree.",
    )
    default_level: int = Field(
        1,
        description="Default per-epoch governance level (Task 12 refines "
                    "per-node levels; v1 stamps this into the report).",
    )
    full_governance_only_on_top_k: int = Field(
        3,
        description="Reserved (Task 12): full adversary/defender/judge "
                    "attention only for the top-k nodes.",
    )
    judge_on_disputed_only: bool = Field(
        True,
        description="Invoke the GovernanceJudge only on filed motions "
                    "(disputed cases), never on undisputed components.",
    )
    impeachment_only_at_epoch_boundary: bool = Field(
        True,
        description="Motions are filed only inside `audit_epoch` at the "
                    "epoch boundary. NOT READ by any code path — it is a "
                    "STRUCTURAL property in v1 (audit_epoch is the facade's "
                    "only motion entry point), not a switch: setting it false "
                    "does not enable mid-epoch motions.",
    )
    max_llm_calls_per_audit: int = Field(
        12,
        description="Hard cap on governance LLM calls per `audit_epoch`; "
                    "past the cap every step degrades to its deterministic "
                    "fallback.",
    )
    max_defender_calls_per_epoch: int = Field(
        12,
        description="Hard per-epoch cap on Defender LLM calls (the adversary "
                    "cap lives in "
                    "`rqgm.adversarial.max_adversary_calls_per_epoch` — "
                    "one schema home, no alias here).",
    )
    max_judge_calls_per_epoch: int = Field(
        8,
        description="Hard per-epoch cap on Judge LLM calls.",
    )
    low_confidence_threshold: float = Field(
        0.4,
        description="Reviewer confidence below this marks the node "
                    "disputed (L2→L3 escalation).",
    )
    novelty_claim_threshold: float = Field(
        0.8,
        description="Novelty axis at/above this (or non-empty "
                    "novelty_risks) triggers the L2 contested tier.",
    )
    max_motions_per_epoch: int = Field(
        2,
        description="Hard cap on impeachment motions filed per epoch.",
    )
    bond_units_per_motion: int = Field(
        1,
        description="Bond units debited per filed motion (refunded on "
                    "upheld/partially_upheld, forfeited on dismissed).",
    )
    jury_panel_enabled: bool = Field(
        False,
        description="JuryPanel (multi-sample judge aggregation). Off in v1.",
    )
    fail_mode: Literal["open"] = Field(
        "open",
        description="Failure posture. v1: only `open` (degrade to a "
                    "no-action report; the run loop never blocks on "
                    "governance).",
    )


class RQGMReplayConfig(BaseModel):
    """``rqgm.replay:`` block (docs/reference/configuration.md,
    "``rqgm.replay`` — replay/anchor case sizing"; the cases themselves are
    Task 06's).

    Sizing of the ReplayBoard/AnchorBoard case sampling inside
    ``audit_epoch``. Defaults mirror ``ari/configs/defaults.yaml``."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    max_cases_per_epoch: int = Field(
        8,
        description="Max replay/anchor cases scored per subject per audit.",
    )
    max_cases_for_retirement: int = Field(
        12,
        description="Higher replay-selection cap used inside `audit_epoch` "
                    "when a motion puts a RetirementEvent under "
                    "consideration (requests `retire` or targets a "
                    "quarantined component).",
    )
    use_cached_results: bool = Field(
        True,
        description="Prefer cached case results (Task 12 caching); the "
                    "boards are deterministic given cached results.",
    )


class RQGMTransitionConfig(BaseModel):
    """``rqgm.transition:`` block (docs/reference/configuration.md,
    "``rqgm.transition`` — RegistryTransitionEngine thresholds").

    Numeric thresholds of the RegistryTransitionEngine — the ONLY tunable
    part of the transition layer. The T1-T21 table topology is fixed code
    (``ari/rqgm/transition_rules.py``) and deliberately NOT configurable.
    Defaults mirror ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_transition_engine.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    replay_pass_threshold: float = Field(
        0.8,
        description="T3 guard: minimum replay-board score for a validated "
                    "candidate to enter shadow.",
    )
    replay_min_cases: int = Field(
        4,
        description="T3 guard: minimum replay cases behind the score.",
    )
    shadow_pass_threshold: float = Field(
        0.7,
        description="T6 guard: minimum shadow agreement/quality for "
                    "probationary adoption; below it with sufficient "
                    "samples is the T5 rejection.",
    )
    shadow_min_samples: int = Field(
        5,
        description="T6 guard: minimum live-shadow comparisons before "
                    "adoption or T5 rejection is decidable.",
    )
    shadow_max_epochs: int = Field(
        2,
        description="T4 trigger: epochs in shadow without sufficient "
                    "samples before the bounded retry (or T5 past the "
                    "retry limit).",
    )
    shadow_retry_limit: int = Field(
        1,
        description="T4 guard: bounded shadow retries; beyond it the "
                    "candidate takes the T5 rejection.",
    )
    probation_min_epochs: int = Field(
        1,
        description="T7/T14 guard: full clean epochs served before "
                    "promotion to active.",
    )
    warning_escalation_count: int = Field(
        2,
        description="T10 trigger: consecutive warning epochs before "
                    "escalation to probation.",
    )
    warning_memory_epochs: int = Field(
        3,
        description="T13 trigger window: a recurrence within this many "
                    "epochs of entering warning escalates to probation.",
    )
    retirement_replay_min_cases: int = Field(
        8,
        description="T17 guard: minimum ReplayBoard case coverage "
                    "confirming an impeachment before retirement commits "
                    "(<= rqgm.replay.max_cases_for_retirement).",
    )
    candidate_max_age_epochs: int = Field(
        3,
        description="T2 trigger: epochs a candidate may wait for "
                    "validation before expiry.",
    )
    max_adoptions_per_role_per_boundary: int = Field(
        1,
        description="T6 guard: at most this many adoptions per role per "
                    "epoch boundary.",
    )


class RQGMAdversarialPenaltyConfig(BaseModel):
    """``rqgm.adversarial.penalty:`` block (docs/reference/configuration.md,
    "``rqgm.adversarial`` — attack→defense→adjudication loop").

    The epoch-frozen UtilityPenaltyPolicy weights. Frozen at epoch open
    (global invariant 1) and embedded by value in every UtilityRecord for
    Task 10's recompute contract."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    cap: float = Field(
        0.5,
        description="Hard per-node cap on the summed validated-attack "
                    "penalty (penalties never raise a score).",
    )
    severity_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "low": 0.05, "medium": 0.15, "high": 0.3, "critical": 0.5,
        },
        description="Judge-assigned-severity → penalty weight. Multiplied "
                    "by the fixed verdict factor (valid=1.0, "
                    "partially_valid=0.5).",
    )


class RQGMAdversarialPoolConfig(BaseModel):
    """``rqgm.adversarial.pool:`` block (docs/reference/configuration.md,
    "``rqgm.adversarial`` — attack→defense→adjudication loop")."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    max_cases: int = Field(
        64,
        description="Bounded AdversarialReplayPool size; past it the lowest "
                    "(severity, recency) actives are marked evicted "
                    "(logical-only — the JSONL history keeps everything).",
    )
    min_severity: Literal["low", "medium", "high", "critical"] = Field(
        "medium",
        description="Pool admission floor on the judge-assigned severity of "
                    "a ValidatedAttackRecord.",
    )
    min_per_type: int = Field(
        2,
        description="Per-case_type eviction floor so adversary-type "
                    "coverage survives the size cap.",
    )


class RQGMShadowConfig(BaseModel):
    """``rqgm.shadow:`` block (docs/reference/configuration.md,
    "``rqgm.shadow`` — shadow live-evaluation sampling").

    Sampling posture of shadow live evaluation: for a deterministic
    hash-sampled fraction of live calls, a candidate prompt runs alongside
    the active prompt on the same input. The candidate output is written
    ONLY to a ComparisonObservation record — it never reaches BFTS scores,
    the frontier, or memory. Task 12 owns final budget numbers; defaults
    mirror ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_prompt_lifecycle.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Shadow live-evaluation on/off inside `ari_rqgm` mode "
                    "(off == a zero shadow budget).",
    )
    sample_rate: float = Field(
        0.2,
        description="Fraction of live calls shadow-sampled per candidate "
                    "(deterministic hash sampling, P2 — no randomness).",
    )
    max_shadow_calls_per_epoch: int = Field(
        10,
        description="Hard cap on shadow side-by-side calls per epoch.",
    )


class RQGMPromptEvolutionConfig(BaseModel):
    """``rqgm.prompt_evolution:`` block (docs/reference/configuration.md,
    "``rqgm.prompt_evolution`` — candidate caps").

    Per-epoch caps on PromptMutator candidate generation. Only meaningful
    when the RQGM runtime is active; Task 12 owns final budget tuning.
    Defaults mirror ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_prompt_lifecycle.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Prompt evolution on/off inside `ari_rqgm` mode (the "
                    "mode interlock still gates everything; this flag "
                    "supports ablations with governance but frozen prompts).",
    )
    max_candidates_per_role_per_epoch: int = Field(
        1,
        description="Hard cap on new prompt candidates per role per epoch.",
    )
    max_total_candidates_per_epoch: int = Field(
        4,
        description="Hard cap on new prompt candidates per epoch (all roles).",
    )
    max_clean_room_generations_per_epoch: int = Field(
        1,
        description="Hard cap on clean-room regenerations per epoch "
                    "(consumed by RQGM Task 08).",
    )
    mutation_kinds: list[str] = Field(
        default_factory=lambda: [
            "freeform_mutation", "threshold_tuning", "schema_tightening",
            "specialization", "distillation",
        ],
        description="Enabled PromptMutator mutation families; the five "
                    "defaults are the complete v1 vocabulary.",
    )


class RQGMUtilityEvolutionConfig(BaseModel):
    """``rqgm.utility_evolution:`` block (docs/reference/configuration.md,
    "``rqgm.utility_evolution`` — governed rewriting of the score itself").

    Governed rewriting of the utility function itself at epoch boundaries.
    Only meaningful when ``ari.mode: ari_rqgm`` and ``rqgm.enabled: true``
    agree. Defaults mirror ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_utility_evolution.py``).

    **Numeric/vocabulary knobs ONLY.** The legality rules — the closed value
    spaces and the axis-weight bounds — are frozen code in
    ``ari.rqgm.kernel_rules.UTILITY_POLICY_RULES``, inside
    ``constitution_hash``. A tunable weight bound would be a tunable
    constitution, and any skill can write the checkpoint dir.

    Deliberately absent because they already have one schema home: candidate
    caps (``rqgm.prompt_evolution.max_candidates_*``), adoption caps
    (``rqgm.transition.max_adoptions_per_role_per_boundary``), shadow
    sampling (``rqgm.shadow.*``), invalidation posture
    (``rqgm.frontier_repair.*``).
    """

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Governed utility evolution on/off inside `ari_rqgm` "
                    "mode. False reproduces the pre-Task-14 system exactly: "
                    "no candidate is minted, no adoption resolves, and "
                    "`capture_utility_policy` returns the founding policy "
                    "(== the cfg policy) in every epoch, so "
                    "`utility_policy_hash` is constant again. This is the "
                    "ablation rung for measuring whether governed rewriting "
                    "helps.",
    )
    mutation_kinds: list[str] = Field(
        default_factory=lambda: [
            "axis_reweighting", "composite_swap", "frontier_score_swap",
            "exploration_tuning",
        ],
        description="Enabled PolicyMutator mutation families. "
                    "The four defaults are pure arithmetic over the "
                    "boundary's abstract evidence — no LLM, no clock, no "
                    "randomness — so the default utility rewrite is fully "
                    "deterministic (the strongest available posture for P2). "
                    "`freeform_policy_proposal` consults an LLM and is "
                    "opt-in: enabling it costs byte-reproducibility of the "
                    "candidate stream, though an irreproducible PROPOSAL can "
                    "still never become an unvalidated POLICY (the kernel "
                    "validates it either way).",
    )
    min_epochs_between_rewrites: int = Field(
        1,
        description="Minimum epochs between two adopted utility rewrites. "
                    "Bounds the R1 cost: a rewrite invalidates every node "
                    "scored under the old policy, which at an early boundary "
                    "can be the whole tree.",
    )


class RQGMContaminationScreenConfig(BaseModel):
    """``rqgm.clean_room.contamination_screen:`` block
    (docs/reference/configuration.md,
    "``rqgm.clean_room`` — clean-room regeneration posture").

    Tuning knobs of the deterministic word-shingle screen the kernel runs
    pre- and post-generation. Tuning is a config change; the screen policy
    itself is code (``ari/rqgm/clean_room_rules.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    shingle_k: int = Field(
        8,
        description="Word-shingle length of the contamination screen "
                    "(k exact-match tokens; a floor, not a ceiling).",
    )
    fail_on_any_hit: bool = Field(
        True,
        description="Any surviving k-shingle overlap with the forbidden "
                    "corpus blocks candidate admission.",
    )


class RQGMCleanRoomConfig(BaseModel):
    """``rqgm.clean_room:`` block (docs/reference/configuration.md,
    "``rqgm.clean_room`` — clean-room regeneration posture").

    Clean-room regeneration posture; the per-epoch generation budget lives
    under ``rqgm.prompt_evolution.max_clean_room_generations_per_epoch``
    (Task 12 owns budget tuning). Inert unless the RQGM runtime is active —
    ``simple_bfts`` never constructs the clean-room path."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    generation_backend: Literal["one_shot"] = Field(
        "one_shot",
        description="Generation harness. v1 supports only `one_shot` — a "
                    "single LLM completion with no tools/filesystem "
                    "(decision D1: a tool-bearing loop could read the "
                    "retired prompt text off the checkpoint).",
    )
    contamination_screen: RQGMContaminationScreenConfig = Field(
        default_factory=RQGMContaminationScreenConfig,
        description="Deterministic shingle-screen knobs.",
    )
    generator_prompt_key: str = Field(
        "rqgm/clean_room_generator",
        description="Committed meta-prompt key of the "
                    "CleanRoomPromptGenerator. NOT READ: the generator uses "
                    "the literal key deliberately so the reference analyzer "
                    "(scripts/analyze_references) can see the template edge "
                    "statically. Kept as documentation of WHICH key is used; "
                    "changing it does not repoint the generator.",
    )


class RQGMFrontierRepairConfig(BaseModel):
    """``rqgm.frontier_repair:`` block (docs/reference/configuration.md,
    "``rqgm.frontier_repair`` — selective erasure / frontier rebuild").

    Posture of the FrontierRepairEngine / selective erasure. All defaults
    inert: the engine exists only under ``ari.mode: ari_rqgm`` with
    ``rqgm.enabled: true`` and runs only when a committed EpochTransition
    carries retirements. Defaults mirror ``ari/configs/defaults.yaml``
    (parity pinned by ``tests/test_rqgm_frontier_repair.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Whether repair runs at boundaries with retirements. "
                    "Meaningful only when `ari.mode: ari_rqgm` and "
                    "`rqgm.enabled: true` agree.",
    )
    max_trace_depth: int = Field(
        8,
        description="BFS cap of the dependency-closure tracer; consumers "
                    "past the cap are swept in conservatively (invalidate, "
                    "no materiality exemption).",
    )
    recompute_utilities: bool = Field(
        True,
        description="Recompute utilities from surviving inputs under the "
                    "original epoch's frozen weights; false invalidates the "
                    "node instead (never re-scored under a new policy).",
    )
    abandon_stale_pending: bool = Field(
        True,
        description="Abandon pending children whose proposal record went "
                    "stale (generator retirement) before they ever run.",
    )


class RQGMMetaSandboxConfig(BaseModel):
    """``rqgm.meta_evolution.sandbox:`` block (docs/reference/configuration.md,
    "``rqgm.meta_evolution`` — meta-tier budgets and switches").

    Offline replay of frozen historical meta-task bundles through a meta
    candidate. Deterministic pass criteria are code
    (``ari/rqgm/meta_evolution.MetaCandidateSandbox``); only sizing lives
    here."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    max_cases: int = Field(
        6,
        description="Historical meta-task bundles replayed per sandbox "
                    "evaluation.",
    )
    use_cached_results: bool = Field(
        True,
        description="Reuse content-keyed sandbox results (Task 12 cache-key "
                    "discipline).",
    )


class RQGMMetaShadowConfig(BaseModel):
    """``rqgm.meta_evolution.shadow:`` block (docs/reference/configuration.md,
    "``rqgm.meta_evolution`` — meta-tier budgets and switches").

    Meta candidates shadow the incumbent at epoch boundaries; their outputs
    are recorded with ``shadow: true`` and routed nowhere."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    min_epochs_before_probation: int = Field(
        2,
        description="Probation floor: meta candidates spend at least this "
                    "many epochs in shadow before probationary_active "
                    "(stricter than the institutional floor). NOT YET READ "
                    "by any code path: the meta-tier probation floor is not "
                    "enforced, so changing this value has no effect today.",
    )


class RQGMMetaEvolutionConfig(BaseModel):
    """``rqgm.meta_evolution:`` block (docs/reference/configuration.md,
    "``rqgm.meta_evolution`` — meta-tier budgets and switches").

    Budgets/switches of the meta tier (Layer 2). All inert under
    ``simple_bfts``; the authority matrix itself is frozen code
    (``ari/rqgm/meta_rules.py``), never config. Defaults mirror
    ``ari/configs/defaults.yaml`` (parity pinned by
    ``tests/test_rqgm_meta_evolution.py``)."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Meta-evolution step on/off inside `ari_rqgm` mode "
                    "(disabled: the coordinator no-ops with a single "
                    "meta_evolution_skipped audit line).",
    )
    evolving_roles: list[str] = Field(
        default_factory=lambda: [
            "prompt_mutator", "clean_room_generator", "replay_selector",
            "failure_summary_compressor", "policy_mutator",
        ],
        description="The v1 evolving meta roles (shrinkable "
                    "to [] to freeze the whole layer without code changes). "
                    "The role called `replay_case_selector` in the design is "
                    "registered as `replay_selector` (Task 02 vocabulary).",
    )
    max_meta_candidates_per_epoch: int = Field(
        1,
        description="Hard cap on meta candidates per epoch, total across "
                    "meta roles.",
    )
    sandbox: RQGMMetaSandboxConfig = Field(
        default_factory=RQGMMetaSandboxConfig,
        description="Offline sandbox-evaluation sizing.",
    )
    shadow: RQGMMetaShadowConfig = Field(
        default_factory=RQGMMetaShadowConfig,
        description="Meta shadow-evaluation posture.",
    )
    metric_spec_weight_cap: bool = Field(
        True,
        description="Constitutional cap: node-initiated MetricSpec "
                    "axis_weights are suppressed in favor of the "
                    "epoch-frozen weight regime (ignored under "
                    "simple_bfts).",
    )


class RQGMSpendBudgetConfig(BaseModel):
    """``rqgm.budgets:`` block (docs/reference/configuration.md,
    "``rqgm.budgets`` — per-epoch governance spend caps").

    Per-epoch governance SPEND caps read against the passive
    ``cost_tracker`` records (`epoch` + `phase="governance"`). ``0`` means
    unlimited — attribution only, the inert default. Exhaustion degrades
    governance (never node execution); the L0 fixed layer is exempt, so no
    value here can disable the constitutional floor."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    max_governance_cost_usd_per_epoch: float = Field(
        0.0,
        description="Per-epoch USD cap on governance-phase LLM spend. "
                    "0 = unlimited (attribution only).",
    )
    max_governance_tokens_per_epoch: int = Field(
        0,
        description="Per-epoch token cap on governance-phase LLM spend. "
                    "0 = unlimited (attribution only).",
    )
    on_exhausted: Literal["degrade", "skip"] = Field(
        "degrade",
        description="Exhaustion posture: `degrade` caps the node's "
                    "effective governance level; `skip` drops the single "
                    "action. Never a crash (decision-point gating only).",
    )


class RQGMAdversarialConfig(BaseModel):
    """``rqgm.adversarial:`` block (docs/reference/configuration.md,
    "``rqgm.adversarial`` — attack→defense→adjudication loop").

    Trigger/budget knobs of the attack→defense→adjudication loop. Task 12
    owns final tuning; defaults mirror ``ari/configs/defaults.yaml`` (parity
    pinned by ``tests/test_rqgm_adversarial.py``). Inert unless the RQGM
    runtime is active — ``simple_bfts`` never constructs the loop."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Whether the adversarial round runs per completed node. "
                    "Meaningful only when `ari.mode: ari_rqgm` and "
                    "`rqgm.enabled: true` agree.",
    )
    types: list[str] = Field(
        default_factory=lambda: [
            "overclaim", "metric_gaming", "prior_art", "reproducibility",
            "evidence_gap", "cost_explosion", "prompt_injection",
            "paper_self_preference",
        ],
        description="Enabled adversary types: the seven exploration types "
                    "+ the paper-phase paper_self_preference eighth, which "
                    "is inert off the paper phase "
                    "(docs/reference/configuration.md, `rqgm.adversarial` "
                    "— attack→defense→adjudication loop).",
    )
    max_attacks_per_node: int = Field(
        3,
        description="Hard cap on RawAttackRecords per adversarial round.",
    )
    max_adversary_calls_per_epoch: int = Field(
        24,
        description="Hard per-epoch cap on adversary LLM calls (total).",
    )
    sample_mod: int = Field(
        5,
        description="Deterministic 1-in-N node sampling "
                    "(hash(node_id+epoch_id) mod N == 0; P2-safe). <= 0 "
                    "disables sampling.",
    )
    jump_threshold: float = Field(
        0.25,
        description="Score jump over the parent that triggers a round.",
    )
    full_governance_only_on_top_k: int = Field(
        3,
        description="Frontier top-K membership that triggers a round "
                    "(shape shared with rqgm.governance; Task 12 tunes).",
    )
    penalty: RQGMAdversarialPenaltyConfig = Field(
        default_factory=RQGMAdversarialPenaltyConfig,
        description="Epoch-frozen utility-penalty weights.",
    )
    pool: RQGMAdversarialPoolConfig = Field(
        default_factory=RQGMAdversarialPoolConfig,
        description="AdversarialReplayPool sizing.",
    )


class ProposalGeneratorConfig(BaseModel):
    """One ``proposal_router.generators.*`` entry
    (docs/reference/configuration.md,
    "``proposal_router`` — proposal generation routing")."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Whether the ProposalRouter may route to this generator. "
                    "Disabled generators are absent from the routing table.",
    )
    max_calls_per_epoch: int = Field(
        0,
        description="Per-epoch invocation budget for this generator. "
                    "0 means unlimited (used by the always-available "
                    "CheapGenerator fallback).",
    )


class VirSciGeneratorConfig(ProposalGeneratorConfig):
    """``proposal_router.generators.virsci`` (docs/reference/configuration.md,
    "``proposal_router`` — proposal generation routing").

    ``enabled: false`` (the default) guarantees the VirSciAdapter is never
    constructed, no VirSci runtime/vendored path is required, and tests pass
    without VirSci installed. Orthogonal to ``ari.mode``: enabling VirSci
    neither turns RQGM on nor requires it.
    """

    enabled: bool = Field(
        False,
        description="Opt-in switch for the high-cost deliberative "
                    "VirSciAdapter generator. Never enabled by default.",
    )
    mode: Literal["event_triggered"] = Field(
        "event_triggered",
        description="Invocation mode. v1 supports only `event_triggered`.",
    )
    max_calls_per_epoch: int = Field(
        2,
        description="Hard per-epoch cap on VirSciAdapter invocations.",
    )
    trigger_on: list[str] = Field(
        default_factory=lambda: [
            "initial_exploration",
            "frontier_stagnation",
            "major_pivot",
            "paper_candidate",
        ],
        description="Router trigger events that may route to the adapter.",
    )


class ProposalGeneratorsConfig(BaseModel):
    """``proposal_router.generators:`` block (docs/reference/configuration.md,
    "``proposal_router`` — proposal generation routing")."""

    model_config = {"extra": "allow"}
    cheap: ProposalGeneratorConfig = Field(
        default_factory=lambda: ProposalGeneratorConfig(
            enabled=True, max_calls_per_epoch=0
        ),
        description="One-shot LLM proposal generator; the deterministic "
                    "routing fallback (uncapped).",
    )
    mutation: ProposalGeneratorConfig = Field(
        default_factory=lambda: ProposalGeneratorConfig(
            enabled=True, max_calls_per_epoch=2
        ),
        description="Mutates one facet of an existing ProposalRecord.",
    )
    attack_driven: ProposalGeneratorConfig = Field(
        default_factory=lambda: ProposalGeneratorConfig(
            enabled=False, max_calls_per_epoch=0
        ),
        description="Consumes ValidatedAttackRecords (requires RQGM Task 06; "
                    "disabled and absent from the routing table until then).",
    )
    prior_art: ProposalGeneratorConfig = Field(
        default_factory=lambda: ProposalGeneratorConfig(
            enabled=True, max_calls_per_epoch=1
        ),
        description="Differentiates proposals against survey/related refs; "
                    "degrades to skipped when no prior-art source exists.",
    )
    virsci: VirSciGeneratorConfig = Field(
        default_factory=VirSciGeneratorConfig,
        description="Optional high-cost deliberative generator "
                    "(docs/guides/virsci_integration.md, Configuration).",
    )


class ProposalRouterConfig(BaseModel):
    """Top-level ``proposal_router:`` block (docs/reference/configuration.md,
    "``proposal_router`` — proposal generation routing").

    Consumed ONLY when the effective mode is ``ari_rqgm`` — EXCEPT
    ``record_only``, which is honored in ``simple_bfts`` (record-only
    dual-write for ablation B1; zero behavior change). Deliberately NOT read
    by mode resolution (VirSci is orthogonal to ``ari.mode``);
    in ``simple_bfts`` the existing VirSci levers
    (``bfts_pipeline.generate_idea.enabled`` / ``ARI_IDEA_VIRSCI_REAL``)
    remain authoritative.
    """

    model_config = {"extra": "allow"}
    record_only: bool = Field(
        False,
        description="Stage-1 dual-write: in `simple_bfts`, additionally "
                    "import the agent-loop's idea.json output into "
                    "proposals/proposal_records.jsonl as legacy_idea_json "
                    "records. No behavior change; rollback = delete the flag.",
    )
    summary_budget_chars: int = Field(
        6000,
        description="Total character budget of the rendered "
                    "ProposalSummaryView expand context (parity with "
                    "_build_idea_ctx_for_expand's ~6000-char channel).",
    )
    generators: ProposalGeneratorsConfig = Field(
        default_factory=ProposalGeneratorsConfig,
        description="Per-generator toggles and per-epoch call budgets.",
    )


class RQGMPaperAblationConfig(BaseModel):
    """``rqgm.eval.paper_ablation:`` RQGM-paper comparison posture.

    This is an evaluation-only selector, not a fifth product/runtime mode.
    The concrete mechanisms continue to use their existing typed switches;
    ``condition_id`` adds the one distinction those switches cannot express:
    whether ``paper_writer`` and/or ``paper_reviewer`` may produce successor
    prompt candidates.  It is ignored unless ``rqgm.eval.enabled`` is true.
    """

    condition_id: Literal[
        "",
        "P0_hgm_h_fixed_critic",
        "P1_rqgm_replacement_only",
        "P2_rqgm_no_erasure",
        "P3_rqgm_full",
        "P4_constitutional_rqgm",
    ] = Field(
        "",
        description="RQGM-paper-aligned comparison preset. Empty preserves "
                    "normal production behavior; P0-P4 are accepted only "
                    "behind `rqgm.eval.enabled`.",
    )


class RQGMEvalKCAConditionsConfig(BaseModel):
    """Task-20 K/C/A comparison identity; never a production authority.

    The fields record which already-typed production switches the evaluation
    harness selected.  They are intentionally inert outside ``rqgm.eval`` and
    cannot add a Skill, bind a Provider, select a Harness, or weaken a
    Verification Contract.
    """

    b: str = ""
    h: str = ""
    k: str = ""
    reporting_alias: str | None = None
    verification_tiers: list[Literal["screen", "validate", "certify"]] = Field(
        default_factory=list
    )
    legacy_comparison_only: bool = False
    publishable: bool = True


class RQGMEvalConfig(BaseModel):
    """``rqgm.eval:`` block (docs/reference/configuration.md,
    "``rqgm.eval`` — evaluation-harness posture"; the harness itself is
    docs/guides/rqgm_evaluation.md).

    Evaluation-harness posture: scripted deterministic component doubles and
    failure-injection activation. ALL defaults off — the harness only affects
    runs it launches itself in fresh checkpoints; a production run never
    resolves an ``eval_double``. Typed fields (not raw-YAML reads) because
    ``load_config``'s field filtering silently drops untyped keys."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        False,
        description="Master interlock for the RQGM evaluation harness. "
                    "Scripted component doubles are refused (and injections "
                    "never applied by the harness) unless true. Never "
                    "enabled by default.",
    )
    scripted_components: dict[str, str] = Field(
        default_factory=dict,
        description="`role -> double_name` substitutions for the "
                    "scripted-component failure injections (the "
                    "`scripted_component` injection mechanism, smoke-tier "
                    "only). Keys of ari.rqgm.evaluation.doubles."
                    "EVAL_DOUBLE_REGISTRY; ignored when `eval.enabled` is "
                    "false.",
    )
    injection_specs: list[str] = Field(
        default_factory=list,
        description="Injection spec ids (eval_* namespace) active for this "
                    "run; recorded into rqgm_injection_provenance.json so "
                    "an injected run can never be mistaken for a real one.",
    )
    paper_ablation: RQGMPaperAblationConfig = Field(
        default_factory=RQGMPaperAblationConfig,
        description="Evaluation-only RQGM-paper comparison selector. It "
                    "does not add a production paper.mode.",
    )
    kca_conditions: RQGMEvalKCAConditionsConfig = Field(
        default_factory=RQGMEvalKCAConditionsConfig,
        description="Task-20 B/H/K comparison identity and reporting-only "
                    "verification-tier metadata.",
    )


class RQGMPaperArchiveConfig(BaseModel):
    """``rqgm.paper.archive:`` block (docs/guides/execution_modes.md,
    "Cost bound and the degraded on-ramp").

    The best-first draft-tree knobs. ``max_expansions`` is a PER-EPOCH
    budget (one archive round) mapped to BFTS ``max_total_nodes``; ``depth``
    maps to BFTS ``max_depth`` (a genuine tree — depth is never a cost risk
    because the total-node cap binds first, bfts.py:501-503). The defaults
    are self-consistent per epoch: ``width + width*refine_rounds =
    4 + 8 = 12 = max_expansions``. Inert unless the effective paper mode is
    ``rqgm_archive``."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    width: int = Field(
        4,
        description="K seed drafts at depth 1 (root branch factor).",
    )
    refine_rounds: int = Field(
        2,
        description="paper_refine child generations per draft (draft branch "
                    "factor); refine passes ARE tree depth.",
    )
    max_expansions: int = Field(
        12,
        description="PER-EPOCH node budget -> BFTS max_total_nodes. Bounds "
                    "cost at ANY depth (bfts.py:501-503).",
    )
    depth: int = Field(
        3,
        description="Draft-tree depth -> BFTS max_depth (a genuine "
                    "best-first tree, not a depth-1 star).",
    )
    compile_threshold: float = Field(
        0.0,
        description="Minimum best-belief score to lazily compile the winner "
                    "(default 0.0 => always compile => exactly one compile, "
                    "identical to the linear render_paper stage).",
    )


class RQGMPaperEpochConfig(BaseModel):
    """``rqgm.paper.epoch:`` — SIZING ONLY.

    The trigger KIND stays the inherited ``rqgm.epoch.boundary: node_count``;
    this knob only sizes it for the paper phase, exactly as
    ``rqgm.epoch.nodes_per_epoch`` does for exploration. One paper epoch =
    one archive round."""

    model_config = {"extra": "allow"}
    rounds: int = Field(
        2,
        description="Archive rounds per paper phase; ONE round = ONE paper "
                    "epoch. Default 2 so the boundary actually fires.",
    )


class RQGMPaperAnchorConfig(BaseModel):
    """``rqgm.paper.anchor:`` — the APReS-equivalent ground-truth anchor
    (docs/reference/rqgm_schemas.md, "``paper_anchor_corpus.jsonl`` — the
    read-only accept/reject anchor").

    The reviewer's held-out accept/reject agreement corpus. Default off =
    the degraded on-ramp (docs/guides/rqgm_migration.md, "The default is a
    degraded on-ramp"): no corpus is read, the ``anchor_evaluation``
    stage takes its zero-coverage pass, and reviewer candidates are not
    anchor-gated. This block is the ``paper_reviewer``'s anchor only:
    ``paper_writer`` is ALSO anchored (docs/concepts/rqgm_architecture.md,
    "The paper-archive layer"), but to the
    Layer-0 claim-evidence gate — see ``paper_anchor.WRITER_ANCHOR_DESCRIPTOR``
    — which needs no curated corpus. The writer's faithfulness case still lands
    on this pool, so ``enabled: false`` gates the writer sanction too."""

    model_config = {"extra": "allow"}
    enabled: bool = Field(False, description="Anchor-corpus scoring on/off.")
    corpus_path: str = Field(
        "", description="APReS-equivalent accept/reject corpus path "
                        "(checkpoint-relative or absolute).",
    )
    sample_size: int = Field(8, description="Held-out agreement sample size.")
    max_bootstrap_label_fraction: float = Field(
        0.5,
        description="Machine-enforced cap: max share of "
                    "label_source=gate_bootstrap cases, checked over the "
                    "corpus AND the held-out subset; a breach => the corpus "
                    "is REFUSED (load returns None => the on-ramp), never an "
                    "exception into the run. 0.0 = human labels only; 1.0 = "
                    "accept a fully self-labelled anchor (fingerprinted).",
    )


class RQGMPaperSelfPreferenceConfig(BaseModel):
    """``rqgm.paper.self_preference:`` — the self-preference adversary knobs
    (docs/reference/rqgm_schemas.md,
    "``rqgm/paper_self_preference_stat.json`` — the self-preference
    statistic").

    Meaningful only under the effective ``rqgm_archive`` paper mode. The
    authorship corpus is the anchor corpus with one extra ``authorship``
    label dimension (``corpus_path: ""`` reuses the anchor corpus); the margin
    statistic and pre-signal degrade safely to gate-finding-only /
    anchor-disagreement attacks when no AI/human corpus is present."""

    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="Self-preference adversary on/off (meaningful only under "
                    "PAPER_RQGM_ARCHIVE).",
    )
    corpus_path: str = Field(
        "",
        description='"" reuses the anchor corpus + its authorship labels; a '
                    "path overrides with a dedicated authorship set.",
    )
    sample_size: int = Field(
        8, description="Held-out papers scored per epoch for the margin.",
    )
    accept_threshold: float = Field(
        0.6,
        description="Reviewer 'accepted' cutoff (mirrors "
                    "CANDIDATE_PASS_THRESHOLD).",
    )
    margin: float = Field(
        0.1,
        description="AI-vs-human mean-score gap that fires the deterministic "
                    "over-acceptance pre-signal.",
    )


class RQGMPaperPromptEvolutionConfig(BaseModel):
    """``rqgm.paper.prompt_evolution:`` — the degraded on-ramp toggle."""

    model_config = {"extra": "allow"}
    enabled: bool = Field(
        True,
        description="false = best-of-N reviewed drafts with a static prompt "
                    "population (NO co-evolution) — the cheap on-ramp. "
                    "DISTINCT from rqgm.prompt_evolution.enabled.",
    )


class RQGMPaperAgentAsJudgeConfig(BaseModel):
    """``rqgm.paper.reviewer.agent_as_judge:`` — the agent-as-judge score seam
    (docs/reference/configuration.md,
    "``rqgm.paper.reviewer.agent_as_judge`` — agent-as-judge draft scoring").

    OFF by default: the deterministic, LLM-free venue rubric is the on-ramp
    draft scorer (P2), so no run puts live LLM calls on the draft-scoring path
    unless it opts in. When ON, ``cli/paper_dispatch.py`` injects a real-``LLMClient``-
    backed ``reviewer_score_fn`` that scores each draft over the venue rubric
    axes *weighted by the ACTIVE governed reviewer prompt's emphasis* — the only
    path that can score an axis no deterministic reader can read (novelty,
    significance) and the one that breaks the DISCRIMINATION CEILING where two
    mature drafts both saturate the structural rubric at 1.0 and tie. Fail-open:
    a failed/unparseable LLM reply falls back to the deterministic rubric score,
    never a fabricated constant. Overridden by ``ARI_PAPER_AGENT_AS_JUDGE``
    (0/1/true/false)."""

    model_config = {"extra": "allow"}
    enabled: bool = Field(
        False,
        description="Agent-as-judge draft scoring on/off. OFF => "
                    "deterministic rubric (P2, no LLM on the draft path). "
                    "Overridden by ARI_PAPER_AGENT_AS_JUDGE.",
    )
    max_tokens: int = Field(
        1024,
        description="Cap on the judge reply length (cost control).",
    )


class RQGMPaperReviewerConfig(BaseModel):
    """``rqgm.paper.reviewer:`` — governed paper_reviewer scoring posture."""

    model_config = {"extra": "allow"}
    agent_as_judge: RQGMPaperAgentAsJudgeConfig = Field(
        default_factory=RQGMPaperAgentAsJudgeConfig,
        description="Agent-as-judge score seam; OFF by default, so the "
                    "deterministic venue rubric scores drafts.",
    )


class RQGMPaperConfig(BaseModel):
    """``rqgm.paper:`` subsection (docs/guides/execution_modes.md,
    "Turning the paper archive on"). The redundant interlock that mirrors
    ``rqgm.enabled`` for the paper phase, plus the archive/epoch/anchor/
    prompt_evolution skeletons. Inert unless the effective paper mode is
    ``rqgm_archive``."""

    # Forward-compat for later-task keys (same posture as RQGMConfig).
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        False,
        description="Redundant safety interlock, mirrors rqgm.enabled. Both "
                    "`paper.mode: rqgm_archive` AND `rqgm.paper.enabled: "
                    "true` are required for the paper archive to activate; "
                    "disagreement fails safe to linear. Overridden by "
                    "`ARI_RQGM_PAPER_ENABLED` (0/1/true/false).",
    )
    archive: RQGMPaperArchiveConfig = Field(
        default_factory=RQGMPaperArchiveConfig,
        description="Best-first draft-tree knobs (Task 01/02).",
    )
    epoch: RQGMPaperEpochConfig = Field(
        default_factory=RQGMPaperEpochConfig,
        description="Archive-round sizing; one round == one paper epoch.",
    )
    anchor: RQGMPaperAnchorConfig = Field(
        default_factory=RQGMPaperAnchorConfig,
        description="Anchor-corpus skeleton (Task 04).",
    )
    self_preference: RQGMPaperSelfPreferenceConfig = Field(
        default_factory=RQGMPaperSelfPreferenceConfig,
        description="Self-preference adversary knobs (Task 05).",
    )
    prompt_evolution: RQGMPaperPromptEvolutionConfig = Field(
        default_factory=RQGMPaperPromptEvolutionConfig,
        description="Degraded on-ramp toggle (Task 03/06 on-ramp).",
    )
    reviewer: RQGMPaperReviewerConfig = Field(
        default_factory=RQGMPaperReviewerConfig,
        description="Governed paper_reviewer scoring posture.",
    )


class RQGMConfig(BaseModel):
    """Top-level ``rqgm:`` block (RQGM Task 01). Tasks 02/12 add typed
    subsections (epoch — Task 02; governance, shadow, replay,
    prompt_evolution — later tasks)."""

    # Forward-compat: later-task subsections parse warn-free today and become
    # typed fields when their owning task lands. `extra: allow` is what keeps
    # a not-yet-typed subsection from being dropped by field filtering.
    model_config = {"extra": "allow"}
    enabled: bool = Field(
        False,
        description="Master interlock for the RQGM governance runtime. Both "
                    "`ari.mode: ari_rqgm` AND `rqgm.enabled: true` are "
                    "required for activation; with either off the entire "
                    "RQGM subtree is structurally inert. Overridden by "
                    "`ARI_RQGM_ENABLED` (0/1/true/false).",
    )
    epoch: RQGMEpochConfig = Field(
        default_factory=RQGMEpochConfig,
        description="Epoch-boundary sizing (RQGM Task 02). Inert unless the "
                    "RQGM runtime is active.",
    )
    kernel: RQGMKernelConfig = Field(
        default_factory=RQGMKernelConfig,
        description="ConstitutionalKernel enforcement posture (RQGM Task "
                    "04). Inert unless the RQGM runtime is active.",
    )
    governance: RQGMGovernanceConfig = Field(
        default_factory=RQGMGovernanceConfig,
        description="GovernanceOrchestrator budgets/posture (RQGM Task 05). "
                    "Inert unless the RQGM runtime is active.",
    )
    replay: RQGMReplayConfig = Field(
        default_factory=RQGMReplayConfig,
        description="Replay/anchor board case sizing (RQGM Task 05; case "
                    "content is Task 06). Inert unless the RQGM runtime is "
                    "active.",
    )
    utility_evolution: RQGMUtilityEvolutionConfig = Field(
        default_factory=RQGMUtilityEvolutionConfig,
        description="Governed rewriting of the utility function at epoch "
                    "boundaries (RQGM Task 14). Legality rules are frozen "
                    "code, not config. Inert unless the RQGM runtime is "
                    "active.",
    )
    transition: RQGMTransitionConfig = Field(
        default_factory=RQGMTransitionConfig,
        description="RegistryTransitionEngine thresholds (RQGM Task 09). "
                    "Numeric guards only — the T1-T21 table is fixed code. "
                    "Inert unless the RQGM runtime is active.",
    )
    adversarial: RQGMAdversarialConfig = Field(
        default_factory=RQGMAdversarialConfig,
        description="Adversarial-loop triggers/budgets/penalty/pool (RQGM "
                    "Task 06). Inert unless the RQGM runtime is active.",
    )
    shadow: RQGMShadowConfig = Field(
        default_factory=RQGMShadowConfig,
        description="Shadow live-evaluation sampling (RQGM Task 07). Inert "
                    "unless the RQGM runtime is active.",
    )
    prompt_evolution: RQGMPromptEvolutionConfig = Field(
        default_factory=RQGMPromptEvolutionConfig,
        description="Prompt-evolution candidate caps (RQGM Task 07). Inert "
                    "unless the RQGM runtime is active.",
    )
    clean_room: RQGMCleanRoomConfig = Field(
        default_factory=RQGMCleanRoomConfig,
        description="Clean-room regeneration posture (RQGM Task 08). Inert "
                    "unless the RQGM runtime is active.",
    )
    frontier_repair: RQGMFrontierRepairConfig = Field(
        default_factory=RQGMFrontierRepairConfig,
        description="FrontierRepairEngine / selective-erasure posture (RQGM "
                    "Task 10). Inert unless the RQGM runtime is active.",
    )
    meta_evolution: RQGMMetaEvolutionConfig = Field(
        default_factory=RQGMMetaEvolutionConfig,
        description="Meta-tier evolution budgets/switches (RQGM Task 11). "
                    "Inert unless the RQGM runtime is active.",
    )
    budgets: RQGMSpendBudgetConfig = Field(
        default_factory=RQGMSpendBudgetConfig,
        description="Per-epoch governance spend caps (RQGM Task 12). "
                    "0 = unlimited; inert unless the RQGM runtime is "
                    "active.",
    )
    eval: RQGMEvalConfig = Field(
        default_factory=RQGMEvalConfig,
        description="Evaluation-harness posture (RQGM Task 13). All "
                    "defaults off; never enabled on production runs.",
    )
    paper: RQGMPaperConfig = Field(
        default_factory=RQGMPaperConfig,
        description="Paper-archive co-evolution subsection (paper-archive "
                    "Task 01). The `rqgm.paper.enabled` interlock plus the "
                    "archive/epoch/anchor/prompt_evolution skeletons. Inert "
                    "unless the effective paper mode is `rqgm_archive` "
                    "(distinct from the exploration `rqgm.*` knobs, never "
                    "shadows them).",
    )


class ARIConfig(BaseModel):
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM backend configuration shared by the agent loop "
                    "and most LLM-using skills.",
    )
    skills: list[SkillConfig] = Field(
        default_factory=list,
        description="Skills to register with the agent. Auto-discovered "
                    "via `_discover_skills()` when the YAML omits the "
                    "section.",
    )
    disabled_tools: list[str] = Field(
        default_factory=list,
        description="MCP tool names hidden from the agent. The viz "
                    "wizard appends to this list when stages are toggled "
                    "off.",
    )
    bfts: BFTSConfig = Field(
        default_factory=BFTSConfig,
        description="BFTS exploration limits.",
    )
    handoff: HandoffConfig = Field(
        default_factory=HandoffConfig,
        description="What a BFTS child inherits from its parent (handoff "
                    "study). Default `disabled` preserves current behaviour; "
                    "set `ARI_HANDOFF_MODE` to select an arm.",
    )
    checkpoint: CheckpointConfig = Field(
        default_factory=CheckpointConfig,
        description="Checkpoint directory configuration.",
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging configuration.",
    )
    evaluator: EvaluatorConfig = Field(
        default_factory=EvaluatorConfig,
        description="Evaluator (BFTS judge) configuration.",
    )
    resources: dict = Field(
        default_factory=dict,
        description="Generic resource defaults (cpus, memory_gb, gpus, "
                    "walltime, partition) used by the HPC skill when a "
                    "stage does not override them.",
    )
    ari: AriModeConfig = Field(
        default_factory=AriModeConfig,
        description="Execution-mode switch (`simple_bfts` | `ari_rqgm`). "
                    "Omitting the block is equivalent to the default.",
    )
    knowledge: KnowledgeRuntimeConfig = Field(
        default_factory=KnowledgeRuntimeConfig,
        description="Knowledge Skill selection, composition, and provenance posture.",
    )
    capability_binding: CapabilityBindingRuntimeConfig = Field(
        default_factory=CapabilityBindingRuntimeConfig,
        description="Capability-to-Provider binding and tool-surface posture.",
    )
    assurance: AssuranceRuntimeConfig = Field(
        default_factory=AssuranceRuntimeConfig,
        description="Harness resolution, execution, and scientific gate posture.",
    )
    rqgm: RQGMConfig = Field(
        default_factory=RQGMConfig,
        description="RQGM governance configuration; inert unless "
                    "`ari.mode: ari_rqgm` and `rqgm.enabled: true` agree.",
    )
    proposal_router: ProposalRouterConfig = Field(
        default_factory=ProposalRouterConfig,
        description="ProposalRouter configuration (RQGM Task 03). Consumed "
                    "only in `ari_rqgm` mode, except `record_only` "
                    "(honored in `simple_bfts` for ablation B1). Typed so "
                    "the block survives load_config's model_fields filter.",
    )
    paper: PaperConfig = Field(
        default_factory=PaperConfig,
        description="Paper-phase execution-mode switch (`linear` | "
                    "`rqgm_archive`, paper-archive Task 01). Orthogonal to "
                    "`ari.mode`; omitting the block is equivalent to the "
                    "`linear` default. Typed so the block survives "
                    "load_config's model_fields filter.",
    )
    manuscript: ManuscriptConfig = Field(
        default_factory=ManuscriptConfig,
        description="Independent manuscript completeness/readiness and bounded "
                    "repair posture. Off by default.",
    )
    model_config = {"extra": "allow"}  # Accept unknown top-level keys


def _resolve_env_vars(value: str) -> str:
    pattern = re.compile(r"\$\{(\w+)\}")
    return pattern.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _resolve_env_recursive(data):
    if isinstance(data, dict):
        return {k: _resolve_env_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_recursive(item) for item in data]
    if isinstance(data, str):
        return _resolve_env_vars(data)
    return data


def _apply_memory_section(raw: dict) -> None:
    """Export the workflow.yaml ``memory:`` section as env vars.

    settings.json and env vars override these values; absence of the
    section logs a deprecation WARNING so v0.5.x workflow.yaml imports
    are visible to the operator.
    """
    import logging
    log = logging.getLogger(__name__)
    mem = raw.get("memory")
    if mem is None:
        log.warning(
            "workflow.yaml has no `memory:` section — defaulting to "
            "backend=letta, base_url=http://localhost:8283."
        )
        return
    backend = (mem.get("backend") or "letta").strip().lower()
    # ``local`` and ``cloud`` select a Letta deployment topology; neither is
    # an alternate storage implementation. Only the test-only in-memory
    # implementation is forbidden in workflow configuration.
    if backend not in {"letta", "local", "cloud"}:
        raise ValueError(
            "workflow memory.backend must select Letta (letta/local/cloud); "
            "the in-memory backend is available only inside the test namespace"
        )
    letta = mem.get("letta") or {}
    if letta.get("base_url"):
        os.environ.setdefault("LETTA_BASE_URL", str(letta["base_url"]))
    if letta.get("embedding_config"):
        os.environ.setdefault(
            "LETTA_EMBEDDING_CONFIG", str(letta["embedding_config"])
        )


def load_config(path: str) -> ARIConfig:
    """Load configuration from config.yaml. Returns auto_config if the file does not exist."""
    config_path = Path(path)
    if not config_path.exists():
        return auto_config()
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    raw = _resolve_env_recursive(raw)
    _apply_memory_section(raw)
    # Resolve {{ari_root}} in skill paths (and anywhere else in config).
    # Phase 2 converted ``config.py`` → ``config/__init__.py`` so this
    # file now sits one level deeper; ``parents[3]`` reaches the repo
    # root (the parent of ``ari-core/``) where the ``ari-skill-*``
    # directories live.
    _ari_root = os.environ.get("ARI_ROOT", str(Path(__file__).resolve().parents[3]))
    def _resolve_ari_root(data):
        if isinstance(data, dict):
            return {k: _resolve_ari_root(v) for k, v in data.items()}
        if isinstance(data, list):
            return [_resolve_ari_root(item) for item in data]
        if isinstance(data, str):
            return data.replace("{{ari_root}}", _ari_root)
        return data
    raw = _resolve_ari_root(raw)
    if "skills" not in raw:
        cfg = ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})
        cfg.skills = _discover_skills()
        _merge_bfts_disabled_tools(cfg, raw)
        _apply_llm_env_overrides(cfg)
        _apply_checkpoint_env_overrides(cfg)
        _apply_web_phase_for_bfts(cfg)
        return cfg
    cfg = ARIConfig(**{k: v for k, v in raw.items() if k in ARIConfig.model_fields})
    _hydrate_skill_manifests(cfg.skills)
    _merge_bfts_disabled_tools(cfg, raw)
    _apply_llm_env_overrides(cfg)
    _apply_checkpoint_env_overrides(cfg)
    _apply_web_phase_for_bfts(cfg)
    return cfg


def consolidation_enabled() -> bool:
    """Whether node-end typed-memory consolidation + verified-context are active.

    Default ON: real runs populate the typed research-memory store and ground
    paper claims on it (validated live: the node-end hook writes provenanced
    experiment_result entries). Set ``ARI_MEMORY_CONSOLIDATE`` to
    ``0``/``false``/``no``/``off`` to disable. Single source of truth so the
    BFTS node-end hook and the paper-pipeline verified-context builder stay in
    sync.
    """
    v = os.environ.get("ARI_MEMORY_CONSOLIDATE")
    if v is None:
        return True
    return v.strip().lower() not in ("0", "false", "no", "off")


def _apply_checkpoint_env_overrides(cfg: "ARIConfig") -> None:
    """Let ARI_CHECKPOINT_DIR override checkpoint.dir from YAML.

    The GUI launcher pre-creates a checkpoint directory and passes its path via
    ARI_CHECKPOINT_DIR so the spawned CLI writes tree.json to the same place the
    GUI is watching. Without this override, load_config() ignores the env var
    and the CLI creates a sibling {run_id} directory, so the GUI sees no nodes.
    """
    from ari.paths import PathManager
    _ckpt_path = PathManager.checkpoint_dir_from_env()
    _ckpt = str(_ckpt_path) if _ckpt_path is not None else ""
    if _ckpt:
        cfg.checkpoint.dir = _ckpt
    _log = os.environ.get("ARI_LOG_DIR", "")
    if _log:
        cfg.logging.dir = _log
    elif _ckpt:
        cfg.logging.dir = _ckpt


# Infrastructure skill name (workflow.yaml `skills[].name`) carrying the
# general-purpose web tools. Default-gated to the paper/reproduce phases.
_WEB_SKILL_NAME = "web-skill"


def _apply_web_phase_for_bfts(cfg: "ARIConfig") -> None:
    """When ``bfts.allow_web`` is set, expose web-skill during the bfts phase.

    Appends ``"bfts"`` to the web-skill's ``phase`` so the existing phase
    filter (``ari.mcp.client._phase_matches``) hands its tools to the BFTS node
    agent. Idempotent and default-off: a reproducible run leaves the web-skill
    phase ([paper, reproduce]) untouched. Safe to call from both ``load_config``
    (YAML value) and ``apply_bfts_env_overrides`` (env value).
    """
    if not getattr(cfg.bfts, "allow_web", False):
        return
    for skill in cfg.skills:
        if getattr(skill, "name", "") != _WEB_SKILL_NAME:
            continue
        phases = skill.phase
        phases = [phases] if isinstance(phases, str) else list(phases)
        if "bfts" not in phases and "all" not in phases:
            phases.append("bfts")
            skill.phase = phases  # Pydantic does not validate on assignment.
        return


def apply_handoff_env_overrides(cfg: "ARIConfig") -> None:
    """Let `ARI_HANDOFF_*` env vars select the handoff arm and per-channel ablations.

    Mirrors apply_bfts_env_overrides. `ARI_HANDOFF_MODE` rebuilds HandoffConfig
    so the mode->channel resolution runs; individual `ARI_HANDOFF_*` switches
    then override single channels for ablation (RQ-B field drop, sensitivity).
    Call AFTER profile overrides so the explicit choice wins.
    See ari-core/PREREG_handoff_study.md.
    """
    _valid_modes = {
        "disabled", "code_only", "evidence_only", "evidence_plus_reflection",
        "summary_only", "code_plus_summary",
        "code_plus_full_log", "code_plus_summary_plus_full_log",
        "code_plus_truncated_log",
        "rolling_summary", "failure_only_summary",
    }
    _m = os.environ.get("ARI_HANDOFF_MODE")
    if _m in _valid_modes:
        cfg.handoff = HandoffConfig(mode=_m)  # re-resolves channels from mode

    def _envbool(name: str, current: bool) -> bool:
        v = os.environ.get(name)
        if v is None:
            return current
        return v.strip().lower() in ("1", "true", "yes", "on")

    cfg.handoff.copy_workdir = _envbool("ARI_HANDOFF_COPY_WORKDIR", cfg.handoff.copy_workdir)
    cfg.handoff.inject_agent_block = _envbool("ARI_HANDOFF_AGENT_BLOCK", cfg.handoff.inject_agent_block)
    cfg.handoff.inject_planner_block = _envbool("ARI_HANDOFF_PLANNER_BLOCK", cfg.handoff.inject_planner_block)
    cfg.handoff.memory_off = _envbool("ARI_HANDOFF_MEMORY_OFF", cfg.handoff.memory_off)
    _lm = os.environ.get("ARI_HANDOFF_LOG_MODE")
    if _lm in ("none", "full", "truncated", "masked"):
        cfg.handoff.log_mode = _lm
    _sf = os.environ.get("ARI_HANDOFF_SUMMARY_FORM")
    if _sf in ("extractive", "rolling", "failure_only",
               "evidence", "evidence_reflection"):
        cfg.handoff.summary_form = _sf
    _fields = os.environ.get("ARI_HANDOFF_SUMMARY_FIELDS")
    if _fields:
        cfg.handoff.summary_fields_enabled = [
            f.strip() for f in _fields.split(",") if f.strip()
        ]


def apply_bfts_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_MAX_NODES/DEPTH/REACT/PARALLEL/TIMEOUT_NODE win over YAML.

    Without this, workflow.yaml and environment profiles (laptop/hpc/cloud) are
    authoritative and silently contradict the caps the GUI wizard specifies.
    Call this AFTER any profile overrides so the explicit user choice wins.
    """
    _n = os.environ.get("ARI_MAX_NODES")
    if _n:
        try:
            cfg.bfts.max_total_nodes = int(_n)
        except ValueError:
            pass
    _d = os.environ.get("ARI_MAX_DEPTH")
    if _d:
        try:
            cfg.bfts.max_depth = int(_d)
        except ValueError:
            pass
    _r = os.environ.get("ARI_MAX_REACT")
    if _r:
        try:
            cfg.bfts.max_react_steps = int(_r)
        except ValueError:
            pass
    _p = os.environ.get("ARI_PARALLEL")
    if _p:
        try:
            cfg.bfts.max_parallel_nodes = int(_p)
        except ValueError:
            pass
    _t = os.environ.get("ARI_TIMEOUT_NODE")
    if _t:
        try:
            cfg.bfts.timeout_per_node = int(_t)
        except ValueError:
            pass
    # GUI wizard's frontier-selection strategy choice. Pydantic does not
    # validate on assignment, so guard against unknown values from env.
    _fs = os.environ.get("ARI_FRONTIER_SCORE")
    if _fs in (
        "scientific_plus_diversity",
        "scientific_only",
        "depth_penalized",
        "ucb_like",
    ):
        cfg.bfts.frontier_score = _fs
    # Handoff study (G9a): force deterministic node selection.
    _ds = os.environ.get("ARI_BFTS_DETERMINISTIC")
    if _ds is not None:
        cfg.bfts.deterministic_selector = _ds.strip().lower() in ("1", "true", "yes", "on")
    # Opt-in web search during BFTS exploration. Env wins over YAML; an
    # explicit falsy value disables it even when workflow.yaml set it on.
    _w = os.environ.get("ARI_BFTS_ALLOW_WEB")
    if _w is not None:
        cfg.bfts.allow_web = _w.strip().lower() in ("1", "true", "yes", "on")
    # Per-node re-expansion cap. Set high (>= max_total_nodes) to effectively
    # disable it so one parent can be re-expanded until the run-level budget is
    # spent (the tree grows toward N instead of stopping at root + cap children).
    _me = os.environ.get("ARI_BFTS_MAX_EXPANSIONS")
    if _me is not None:
        try:
            cfg.bfts.max_expansions_per_node = int(_me)
        except ValueError:
            pass
    _apply_web_phase_for_bfts(cfg)


def apply_evaluator_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_COMPOSITE / ARI_AXIS_MODE win over YAML.

    Mirrors apply_bfts_env_overrides for the evaluator's per-experiment knobs.
    Pydantic does not validate on assignment, so each value is checked against
    its allowed set before being written. Call this AFTER any profile overrides
    so the explicit GUI choice wins.
    """
    _comp = os.environ.get("ARI_COMPOSITE")
    if _comp in (
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    ):
        cfg.evaluator.composite = _comp
    _am = os.environ.get("ARI_AXIS_MODE")
    if _am in ("legacy", "dynamic", "custom"):
        cfg.evaluator.axis_mode = _am


def apply_rqgm_env_overrides(cfg: "ARIConfig") -> None:
    """Let ARI_MODE / ARI_RQGM_ENABLED override YAML (RQGM Task 01).

    Mirrors apply_evaluator_env_overrides: Pydantic does not validate on
    assignment, so each value is checked against its allowed set before being
    written; an invalid value is ignored with a warning. Call this AFTER any
    profile overrides so the explicit env choice wins, and BEFORE
    export_resolved_config_to_skill_env (which setdefaults ARI_MODE to the
    *effective* mode for skill subprocesses).
    """
    import logging
    _log = logging.getLogger(__name__)
    _m = os.environ.get("ARI_MODE")
    if _m:
        _mv = _m.strip().lower()
        if _mv in ("simple_bfts", "ari_rqgm"):
            cfg.ari.mode = _mv
        else:
            _log.warning(
                "ARI_MODE=%r is not a valid mode (simple_bfts | ari_rqgm); "
                "ignored", _m,
            )
    _e = os.environ.get("ARI_RQGM_ENABLED")
    if _e:
        _ev = _e.strip().lower()
        if _ev in ("1", "true"):
            cfg.rqgm.enabled = True
        elif _ev in ("0", "false"):
            cfg.rqgm.enabled = False
        else:
            _log.warning(
                "ARI_RQGM_ENABLED=%r is not a valid boolean (0/1/true/false); "
                "ignored", _e,
            )


def _effective_mode_str(cfg: "ARIConfig") -> str:
    """Effective execution mode as a plain string, import-free.

    Mirrors the activation cell of ari.rqgm.mode.resolve_effective_mode (both
    flags must agree; anything else is `simple_bfts`) WITHOUT importing
    ari.rqgm — default runs must never load an RQGM module.
    Parity with the real resolver is pinned by tests/test_rqgm_mode.py.
    """
    _mode = getattr(getattr(cfg, "ari", None), "mode", "simple_bfts")
    _enabled = bool(getattr(getattr(cfg, "rqgm", None), "enabled", False))
    return "ari_rqgm" if (_mode == "ari_rqgm" and _enabled) else "simple_bfts"


def apply_paper_env_overrides(cfg: "ARIConfig") -> None:
    """Let ARI_PAPER_MODE / ARI_RQGM_PAPER_ENABLED override YAML.

    Clones ``apply_rqgm_env_overrides``: Pydantic does not validate on
    assignment, so each value is checked against its allowed set before being
    written; an invalid value is ignored with a warning. ``_resolve_cfg`` (the
    paper entry's config loader) applies NO env overrides, so the paper
    command must call this explicitly — ``ARI_PAPER_MODE`` cannot free-ride on
    the run/resume override block.
    """
    import logging
    _log = logging.getLogger(__name__)
    _m = os.environ.get("ARI_PAPER_MODE")
    if _m:
        _mv = _m.strip().lower()
        if _mv in ("linear", "rqgm_archive"):
            cfg.paper.mode = _mv
        else:
            _log.warning(
                "ARI_PAPER_MODE=%r is not a valid paper mode (linear | "
                "rqgm_archive); ignored", _m,
            )
    _e = os.environ.get("ARI_RQGM_PAPER_ENABLED")
    if _e:
        _ev = _e.strip().lower()
        if _ev in ("1", "true"):
            cfg.rqgm.paper.enabled = True
        elif _ev in ("0", "false"):
            cfg.rqgm.paper.enabled = False
        else:
            _log.warning(
                "ARI_RQGM_PAPER_ENABLED=%r is not a valid boolean "
                "(0/1/true/false); ignored", _e,
            )
    # Agent-as-judge draft scoring: opt-in
    # real-LLM reviewer scoring. Same validate-before-assign posture.
    _j = os.environ.get("ARI_PAPER_AGENT_AS_JUDGE")
    if _j:
        _jv = _j.strip().lower()
        if _jv in ("1", "true"):
            cfg.rqgm.paper.reviewer.agent_as_judge.enabled = True
        elif _jv in ("0", "false"):
            cfg.rqgm.paper.reviewer.agent_as_judge.enabled = False
        else:
            _log.warning(
                "ARI_PAPER_AGENT_AS_JUDGE=%r is not a valid boolean "
                "(0/1/true/false); ignored", _j,
            )


def _effective_paper_mode_str(cfg: "ARIConfig") -> str:
    """Effective paper mode as a plain string, import-free.

    Mirrors the activation cell of ari.rqgm.paper_mode.resolve_paper_mode
    (both flags must agree; anything else is `linear`) WITHOUT importing
    ari.rqgm — default paper runs must never load an RQGM module on the paper
    path. Reads ONLY `paper.mode` /
    `rqgm.paper.enabled` — orthogonal to `ari.mode`, so all four
    combinations of the two axes are valid. Parity with the
    real resolver is pinned by tests/test_paper_mode.py.
    """
    _mode = getattr(getattr(cfg, "paper", None), "mode", "linear")
    _enabled = bool(
        getattr(getattr(getattr(cfg, "rqgm", None), "paper", None),
                "enabled", False)
    )
    return "rqgm_archive" if (_mode == "rqgm_archive" and _enabled) else "linear"


def apply_manuscript_env_overrides(cfg: "ARIConfig") -> None:
    """Apply explicit new-attempt Manuscript Complete overrides.

    A resumed in-progress attempt still reconciles against its persisted
    binding in the coordinator; these values cannot rewrite old artifacts.
    """

    import logging
    _log = logging.getLogger(__name__)
    _mode = os.environ.get("ARI_MANUSCRIPT_MODE")
    if _mode:
        value = _mode.strip().lower()
        if value in ("off", "audit", "enforce"):
            cfg.manuscript.mode = value
        else:
            _log.warning(
                "ARI_MANUSCRIPT_MODE=%r is not valid (off | audit | enforce); ignored",
                _mode,
            )
    _policy = os.environ.get("ARI_MANUSCRIPT_REPAIR_POLICY")
    if _policy:
        value = _policy.strip().lower()
        if value in ("disabled", "explicit", "auto"):
            cfg.manuscript.repair.policy = value
        else:
            _log.warning(
                "ARI_MANUSCRIPT_REPAIR_POLICY=%r is not valid "
                "(disabled | explicit | auto); ignored",
                _policy,
            )
    if (
        getattr(cfg.manuscript.repair, "policy", "disabled") == "auto"
        and getattr(cfg.manuscript, "mode", "off") != "enforce"
    ):
        raise ValueError(
            "manuscript.repair.policy=auto requires manuscript.mode=enforce"
        )


def _effective_manuscript_mode_str(cfg: "ARIConfig") -> str:
    """Return the validated manuscript mode without importing its package."""

    mode = getattr(getattr(cfg, "manuscript", None), "mode", "off")
    return mode if mode in ("off", "audit", "enforce") else "off"


def _apply_llm_env_overrides(cfg: "ARIConfig") -> None:
    """Let GUI-injected ARI_MODEL / ARI_BACKEND / ARI_LLM_API_BASE override YAML.

    Without this, workflow.yaml's `llm.model` is authoritative and silently
    contradicts the model the GUI wizard/settings pass via env vars.
    """
    _m = os.environ.get("ARI_MODEL") or os.environ.get("ARI_LLM_MODEL")
    if _m:
        cfg.llm.model = _m
    _b = os.environ.get("ARI_BACKEND")
    if _b:
        cfg.llm.backend = _b
    _u = os.environ.get("ARI_LLM_API_BASE")
    if _u is not None and _u != "":
        cfg.llm.base_url = _u
    # Fixed sampling seed for reproducible local-model runs (handoff study).
    _seed = os.environ.get("ARI_SEED")
    if _seed:
        try:
            cfg.llm.seed = int(_seed)
        except ValueError:
            pass
    _apply_claude_code_env_overrides(cfg)


def _apply_claude_code_env_overrides(cfg: "ARIConfig") -> None:
    """ARI_CLAUDE_CODE_* env overrides for the claude_code backend.

    Value-checked before assignment (Pydantic does not validate on
    assignment — same rationale as the ARI_HANDOFF_* overrides above).
    """
    cc = cfg.llm.claude_code
    _mode = os.environ.get("ARI_CLAUDE_CODE_MODE")
    if _mode in ("strict_reproducibility", "low_overhead"):
        cc.mode = _mode
    # Model override is claude_code-scoped: only meaningful when the
    # resolved backend actually is claude_code.
    _cm = os.environ.get("ARI_CLAUDE_CODE_MODEL")
    if _cm and (cfg.llm.backend or "").replace("-", "_") == "claude_code":
        cfg.llm.model = _cm
    _mt = os.environ.get("ARI_CLAUDE_CODE_MAX_TURNS")
    if _mt:
        try:
            cc.max_turns = int(_mt)
        except ValueError:
            pass
    _ts = os.environ.get("ARI_CLAUDE_CODE_TIMEOUT_SEC")
    if _ts:
        try:
            cc.timeout_sec = int(_ts)
        except ValueError:
            pass
    _rp = os.environ.get("ARI_CLAUDE_CODE_RECORD_PROVENANCE")
    if _rp in ("0", "false", "False"):
        cc.record_provenance = False
    elif _rp in ("1", "true", "True"):
        cc.record_provenance = True
    _bin = os.environ.get("ARI_CLAUDE_CODE_BIN")
    if _bin:
        cc.claude_bin = _bin


def export_resolved_config_to_skill_env(cfg: "ARIConfig") -> None:
    """Bridge the RESOLVED main config to the env vars skill SUBPROCESSES read.

    The main agent loop reads ``cfg.llm`` directly, but skill subprocesses read their
    LLM / SLURM config from environment variables (the idea skill's ``ARI_LLM_MODEL``,
    the HPC skill's ``ARI_SLURM_PARTITION``). The GUI launcher injects those vars; a
    bare ``ari run`` did NOT, so a skill silently fell back to its OWN default (the
    idea skill -> ``ollama_chat/qwen3:32b`` against a dead Ollama; the HPC skill ->
    sinfo's first partition, possibly the wrong architecture) even though the run
    was configured for a specific model and partition. This bridges cfg -> env so the CLI configures skills
    the same way the GUI does.

    ``setdefault`` => an explicitly-set env var still wins (the user/GUI override is
    never clobbered); this only fills the gap a bare CLI left empty.
    """
    if getattr(cfg.llm, "model", None):
        os.environ.setdefault("ARI_LLM_MODEL", str(cfg.llm.model))
    if getattr(cfg.llm, "backend", None):
        os.environ.setdefault("ARI_BACKEND", str(cfg.llm.backend))
    if getattr(cfg.llm, "base_url", None):
        os.environ.setdefault("ARI_LLM_API_BASE", str(cfg.llm.base_url))
    # SLURM partition: export only a CONCRETE choice (not "auto"/empty), so the HPC
    # skill uses it instead of auto-detecting sinfo's first partition. Look in the
    # resources dict (ARI_SLURM_PARTITION-sourced) then the profile's hpc section.
    _part = ""
    _res = getattr(cfg, "resources", None)
    if isinstance(_res, dict):
        _part = str(_res.get("partition") or "").strip()
    if not _part:
        _hpc = getattr(cfg, "hpc", None)
        if isinstance(_hpc, dict):
            _part = str(_hpc.get("partition") or "").strip()
    if _part and _part.lower() != "auto":
        os.environ.setdefault("ARI_SLURM_PARTITION", _part)
    # RQGM Task 01: bridge the EFFECTIVE execution mode so skill subprocesses
    # can key off it later (no skill reads it in v1). setdefault => an
    # explicitly-set ARI_MODE env override is never clobbered.
    os.environ.setdefault("ARI_MODE", _effective_mode_str(cfg))


def _merge_bfts_disabled_tools(cfg: "ARIConfig", raw: dict) -> None:
    """Auto-disable MCP tools whose bfts_pipeline stage is disabled.

    When a user toggles a BFTS stage off in the GUI, the stage's `tool`
    is added to `disabled_tools` so the AgentLoop cannot call it either.
    """
    for stage in raw.get("bfts_pipeline") or []:
        if not stage.get("enabled", True):
            tool = stage.get("tool", "")
            if tool and tool not in cfg.disabled_tools:
                cfg.disabled_tools.append(tool)


def _discover_skills(base_dir: Path | None = None) -> list[SkillConfig]:
    """Auto-detect canonical, default-enabled ``ari-skill-*`` packages.

    Directory presence is not registration. Only a canonical, default-enabled
    manifest enters production discovery; an unmanifested local Skill must be
    named explicitly in development configuration.
    """
    if base_dir is None:
        # Phase 2 — file moved into a package; ``parents[3]`` reaches
        # the repo root (alongside the ``ari-skill-*`` directories).
        base_dir = Path(__file__).resolve().parents[3]
    skills = []
    for manifest_path in sorted(base_dir.glob(f"ari-skill-*/{MANIFEST_FILENAME}")):
        skill_dir = manifest_path.parent
        manifest = load_skill_manifest(manifest_path)
        resolve_skill_entrypoint(skill_dir, manifest)
        if not manifest.enabled_by_default:
            logger.info(
                "Skipping default-off Skill '%s' during auto-discovery",
                manifest.name,
            )
            continue
        skills.append(_skill_config_from_manifest(skill_dir, manifest_path, manifest))
    return skills


def _skill_config_from_manifest(
    skill_dir: Path,
    manifest_path: Path,
    manifest: SkillManifestV1,
    *,
    phase: str | list[str] = "all",
) -> SkillConfig:
    return SkillConfig(
        name=manifest.name,
        path=str(skill_dir),
        description=manifest.description,
        phase=phase,
        package=manifest.package,
        version=manifest.version,
        manifest_path=str(manifest_path),
        entrypoint=manifest.entrypoint.module,
        enabled_by_default=manifest.enabled_by_default,
        environment_policy=manifest.environment_policy,
        required_env=list(manifest.required_env),
        optional_env=list(manifest.optional_env),
        **manifest_runtime_metadata(manifest),
    )


def _hydrate_skill_manifests(skills: list[SkillConfig]) -> None:
    """Attach canonical metadata to explicitly configured Skills in place.

    ``workflow.yaml`` remains the authority for aliases and phase exposure during
    the compatibility window.  Package identity, entrypoint, version, environment
    declarations, and execution class come from the manifest.
    """

    for skill in skills:
        skill_dir = Path(skill.path)
        manifest_path = skill_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        manifest = load_skill_manifest(manifest_path)
        resolve_skill_entrypoint(skill_dir, manifest)
        if skill.name != manifest.name:
            logger.warning(
                "Configured Skill alias '%s' differs from canonical name '%s'",
                skill.name,
                manifest.name,
            )
        skill.package = manifest.package
        skill.version = manifest.version
        skill.manifest_path = str(manifest_path)
        skill.entrypoint = manifest.entrypoint.module
        skill.enabled_by_default = manifest.enabled_by_default
        skill.environment_policy = manifest.environment_policy
        skill.required_env = list(manifest.required_env)
        skill.optional_env = list(manifest.optional_env)
        for field_name, value in manifest_runtime_metadata(manifest).items():
            setattr(skill, field_name, value)
        if not skill.description:
            skill.description = manifest.description


def auto_config() -> ARIConfig:
    """Default configuration when config.yaml is omitted. Can be overridden by environment variables."""
    # Determine backend from model name
    _model = os.environ.get("ARI_MODEL", "qwen3:8b")
    # Backend is determined solely by ARI_BACKEND env var (set by GUI wizard or user).
    # No model-name guessing here — that violates the Zero Domain Knowledge Principle.
    _backend = os.environ.get("ARI_BACKEND", "ollama")
    _base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") if _backend == "ollama" else os.environ.get("LLM_API_BASE", None)
    # Checkpoint dir: ARI_CHECKPOINT_DIR (explicit) > workspace/checkpoints/{run_id}/
    # Subtask 004 P2 reconciliation ("workspace/ wins"): the canonical workspace
    # root is owned by ``RuntimePathResolver.resolve_workspace_root()`` (subtask
    # 006) — the single source of truth. Routing through it keeps CLI, GUI, and
    # auto_config on one location (and honours ARI_ROOT), replacing the previous
    # hand-rolled ``parents[3] / "workspace"`` arithmetic that duplicated the
    # policy and disagreed with ``default.yaml``.
    from ari.paths import PathManager, RuntimePathResolver
    _ckpt_path = PathManager.checkpoint_dir_from_env()
    _ckpt_dir = str(_ckpt_path) if _ckpt_path is not None else ""
    if not _ckpt_dir:
        _ws_root = RuntimePathResolver.resolve_workspace_root()
        _ckpt_dir = str(_ws_root / "checkpoints" / "{run_id}")
    _log_dir = os.environ.get("ARI_LOG_DIR", _ckpt_dir)
    cfg = ARIConfig(
        llm=LLMConfig(
            backend=_backend,
            model=_model,
            base_url=_base_url,
        ),
        skills=_discover_skills(),
        bfts=BFTSConfig(
            max_depth=int(os.environ.get("ARI_MAX_DEPTH", 5)),
            max_total_nodes=int(os.environ.get("ARI_MAX_NODES", 50)),
            max_react_steps=int(os.environ.get("ARI_MAX_REACT", 20)),
            timeout_per_node=int(os.environ.get("ARI_TIMEOUT_NODE", 7200)),
            max_parallel_nodes=int(os.environ.get("ARI_PARALLEL", 4)),
        ),
        checkpoint=CheckpointConfig(
            dir=_ckpt_dir,
        ),
        logging=LoggingConfig(
            dir=_log_dir,
            level=os.environ.get("ARI_LOG_LEVEL", "INFO"),
        ),
        resources={
            k: v for k, v in {
                "cpus": os.environ.get("ARI_SLURM_CPUS"),
                "memory_gb": os.environ.get("ARI_SLURM_MEM_GB"),
                "gpus": os.environ.get("ARI_SLURM_GPUS"),
                "walltime": os.environ.get("ARI_SLURM_WALLTIME"),
                "partition": os.environ.get("ARI_SLURM_PARTITION"),
            }.items() if v is not None
        },
    )
    # ARI_CLAUDE_CODE_* must work on the no-YAML path too (GUI wizard
    # endpoints build their config via auto_config()).
    _apply_claude_code_env_overrides(cfg)
    return cfg


# Backward-compatible alias
AppConfig = ARIConfig
