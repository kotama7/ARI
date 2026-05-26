---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-paper-re
    role: implementation
last_verified: 2026-05-26
---

# Glossary

Short definitions of the terms that recur across the ARI documentation, each
pointing to the document that explains it in full. Terms are grouped by the
subsystem they belong to.

## Search & orchestration

**BFTS (Best-First Tree Search)**
ARI's experiment-search loop. It explores a tree of experiment configurations,
always expanding the most promising completed node first. Implemented in
`ari/orchestrator/bfts.py`. See [BFTS algorithm](../concepts/bfts.md).

**pending**
One of BFTS's two pools: nodes that have been expanded from a parent and are
ready to run but have not executed yet. See [BFTS algorithm](../concepts/bfts.md).

**frontier**
The other BFTS pool: completed nodes awaiting expansion. The frontier is
*persistent* — a node stays available for re-expansion after producing a child,
until it is retired. See [BFTS algorithm](../concepts/bfts.md).

**retire (a frontier node)**
Removing a completed node from further expansion. A node retires under **Rule A**
(a child outscores it on `_scientific_score`) or **Rule B** (it has been expanded
`max_expansions_per_node` times). See [BFTS algorithm](../concepts/bfts.md).

**node label**
The role a BFTS node plays relative to its parent: `draft`, `improve`, `debug`,
`ablation`, `validation`, or `other`. Unknown labels collapse to `other` while
`raw_label` preserves the original string. See [BFTS algorithm](../concepts/bfts.md).

**diversity bonus**
A `+0.05` score nudge applied to under-represented node labels (tracked over the
last 20 runs) so the search does not collapse onto a single strategy. See
[BFTS algorithm](../concepts/bfts.md).

**sterile (node)**
A child whose `work_dir` is byte-identical to its parent after execution
(`added = modified = deleted = 0` in the sha256 diff). It is marked
`_sterile = True`, scored `0.0`, and pruned — this is what stops a child from
"inheriting" the parent's results without running anything. See
[Architecture → work_dir inheritance](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7).

**should_prune**
The hard-cutoff predicate in BFTS: prune when `current_total ≥ max_total_nodes`,
`depth ≥ max_depth`, or `_sterile is True`. No LLM judgement enters here. See
[BFTS algorithm](../concepts/bfts.md).

## Evaluation

**scientific_score / `_scientific_score`**
The peer-review quality score (0.0–1.0) the `LLMEvaluator` assigns to each node.
Stored in `metrics["_scientific_score"]`, it drives BFTS ranking, lineage
decisions, and best-node selection. See
[Configuration → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable).

**composite formula**
How per-axis scores are reduced to one scalar: `harmonic_mean` (default),
`arithmetic_mean`, `weighted_min`, or `geometric_mean`. Configurable via
`evaluator.composite`. See
[Configuration → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable).

**plan**
The *evaluation specifics* of a run — what metrics to measure, what baselines to
compare against, what ablations to run. Sourced from
`idea.json[0].experiment_plan`. Not inherited by sub-experiments by default
(children write their own, so they stay free to pivot). See
[Architecture → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070).

**venue**
The *judgement criteria* of a run — which dimensions are scored and how. A venue
is a `ari-core/config/reviewer_rubrics/<id>.yaml` file selected by `ARI_RUBRIC`.
Switching the venue changes the BFTS scoring axes and the published review's
criteria together. See
[Architecture → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070).

**rubric**
A scoring specification. ARI uses the word in two contexts: a **reviewer rubric**
(the venue YAML above) for paper review, and an **ORS rubric** (a PaperBench
`TaskNode` tree) for reproducibility grading. See
[Rubric schema](rubric_schema.md).

**lineage decision**
When composite scores stagnate, a BFTS hook asks the LLM to pick
`continue` / `switch_to_idea` / `fanout` / `terminate`. See
[Architecture → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070).

## Memory

**ancestor scope**
The rule that a node may read memory only from its ancestor chain (root → parent),
never from siblings. Enforced by a metadata filter on `search_memory`. See
[Memory architecture](../concepts/memory.md).

**CoW (Copy-on-Write)**
The write guard that keeps ancestor memory byte-stable across siblings:
write-side tools reject any `node_id` that is not the active
`$ARI_CURRENT_NODE_ID`. See [Memory architecture](../concepts/memory.md).

**Letta**
The memory backend (formerly MemGPT) used since v0.6.0. Each checkpoint gets a
dedicated agent holding two collections: `ari_node_<hash>` (ancestor-scoped
archival) and `ari_react_<hash>` (flat ReAct trace). See
[Memory architecture](../concepts/memory.md).

## Agent & skills

**ReAct loop**
The per-node agent loop (`ari/agent/loop.py`) that interleaves LLM reasoning with
MCP tool calls to run one experiment. See
[Architecture → Per-Node Prompt Composition](../concepts/architecture.md#per-node-prompt-composition).

**MCP skill**
A capability packaged as a Model Context Protocol server (e.g. `ari-skill-hpc`).
Skills may import only from `ari.public.*`. There are 14 (13 default + 1
additional). See [MCP skills](skills.md).

**VirSci**
The multi-agent deliberation that turns a research goal into a hypothesis and a
primary metric, run once at the root node via `generate_ideas`. See
[Architecture](../concepts/architecture.md#full-data-flow).

## State & publication

**checkpoint**
The self-contained directory for one run, `{workspace}/checkpoints/{run_id}/`
where `run_id` is `YYYYMMDDHHMMSS_<slug>`. All state lives here; `PathManager`
(`ari/paths.py`) is the single source of truth. API keys are never stored here —
they come from `.env` or the environment. See
[Architecture → File Structure](../concepts/architecture.md#file-structure).

**EAR (Experiment Artifact Repository)**
The deterministically-built `ear/` bundle (code, input data, figures, README,
`reproduce.sh`, LICENSE) that ships with a paper. Experiment *outputs* are
deliberately not bundled. See [Publication lifecycle](../concepts/publication-lifecycle.md).

## Reproducibility (ORS / PaperBench)

**ORS**
ARI's reproducibility check — a deterministic, PaperBench-compatible two-phase
flow that re-runs the paper and grades it. Replaced the old LLM-judged path in
v0.7.0. See [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md).

**TaskNode**
A node in a PaperBench-format rubric tree. The ORS rubric generated from a paper
is a tree of `TaskNode`s with weights and a closed `task_category` vocabulary.
See [Rubric schema](rubric_schema.md).

**Phase 1 / Phase 2**
The two ORS phases: **Phase 1** (`run_reproduce`) executes `reproduce.sh` in a
sandbox (`slurm` → `docker` → `apptainer` → `singularity` → `local`); **Phase 2**
(`grade_with_simplejudge`) runs PaperBench SimpleJudge over the rubric leaves.
See [PaperBench API](api_paperbench.md).

**negative control**
An ORS guardrail: an empty repo + a trivial `reproduce.sh` must score below 5%,
proving the rubric does not reward absence of work. See
[PaperBench API](api_paperbench.md).

**bridge stage**
One of the three vendor-protocol entry points of the v0.8.0 PaperBench bridge:
`rollout_submission` (agent produces a submission), `reproduce_submission`
(execute it), and `judge_submission` (grade it). See
[PaperBench API](api_paperbench.md).

**paper-audit mode**
A reversed use of the ORS rubric machinery (v0.7.2) that audits whether a paper
*itself* is described well enough to be reproducible, conditioned on a venue
template (`sc` / `neurips` / `nature`). See [Rubric schema](rubric_schema.md).

---

See also: [Architecture](../concepts/architecture.md) ·
[BFTS algorithm](../concepts/bfts.md) ·
[Memory architecture](../concepts/memory.md) ·
[Configuration](configuration.md)
