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
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
last_verified: 2026-06-10
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

**computed-evidence claim**
A contract claim whose required evidence must be *computed from* existing
measurements (parameter fitting, held-out validation, model-based selection)
rather than probed directly. Reachable only by expanding the node that already
holds the source measurements — see **lineage chaining**.

**lineage chaining**
The BFTS mechanism that makes computed-evidence claims reachable: the
expansion-selection hint names the node holding the most contract evidence and
recommends expanding *it* (children inherit the parent's `work_dir`), and a
child whose inherited `work_dir` already contains lineage measurements gets an
INHERITED DATA note in its pinned obligation listing the files and contract
names present. Only names and files flow — values and sibling conclusions
never do, preserving fault containment. See [BFTS algorithm](../concepts/bfts.md).

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
When composite scores stagnate, a BFTS hook FIRST deterministically pivots
(`switch_to_idea`) to the strongest *unused* runner-up idea, so a runner-up is
actually tried instead of dying unused. The LLM judge (which also chooses among
`continue` / `switch_to_idea` / `fanout` / `terminate`) is consulted only as a
fallback — when the budget is exhausted, the recursion limit is reached, or no
unused alternative remains. See
[Architecture → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070).

**claim-evidence gate**
A deterministic, no-LLM gate (`claim_evidence_hard_gate`) that re-derives each
reported paper number from recorded results within tolerance and checks numeric
coverage / operand resolution / figure existence. Default-on in `warn`
(report-only) mode; set `claim_gate_policy.mode: strict` (or
`ARI_CLAIM_GATE_MODE=strict`) to block finalize on blocking errors. A
`comparison_scope` of `any` (default) treats a cross-environment comparison as a
transparency warning, while `same_environment` makes it a blocking error. See
[Configuration](configuration.md).

**mint-once (contract freeze)**
The rule that the run-level `metric_contract.json` is written once: after the
first claims-bearing mint, `make_metric_spec` returns the persisted contract
verbatim (`contract_frozen: true`) instead of re-extracting. LLM naming is not
referentially stable, so a mid-run regeneration would change the evidence
vocabulary and hide already-emitted evidence from the exact-match gate.
Scaffold-only contracts (no `claims`) do not freeze. See
[File formats](file_formats.md#metric_contractjson).

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

**verified context / verifiable research memory**
A typed, sha256-provenanced layer built on top of Letta. At node end,
`node_report.json` is consolidated into typed, provenanced records
(`experiment_result` / `failure_case` / `reflection`); the paper pipeline then
derives an artifact-grounded `verified_context.json` (scoped to the best node's
root→best lineage) to ground paper claims on what was actually measured.
Default-on via `ARI_MEMORY_CONSOLIDATE`. See
[Verifiable research memory](../concepts/verifiable_research_memory.md).

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

**workspace (root)**
The top-level directory that holds every run's data: `checkpoints/`,
`experiments/`, `staging/`, and `paper_registry/`. Resolved by
`PathManager.root` (`ari/paths.py`); the active run is pinned via the
`ARI_CHECKPOINT_DIR` env var (`PathManager.from_checkpoint_dir` recovers the
root from a checkpoint path). There is no global `~/.ari` config dir — all
per-run config (`settings.json`, `memory.json`) lives inside the checkpoint.

**run**
One experiment execution, identified by a `run_id` (`YYYYMMDDHHMMSS_<slug>`).
On disk a run spans two sibling trees keyed by that id: the **checkpoint**
`checkpoints/{run_id}/` (run-level state) and the experiments bucket
`experiments/{run_id}/` (per-node work dirs). "run" and "checkpoint" are often
used interchangeably; precisely, the checkpoint is the run's state directory.

**checkpoint**
The self-contained directory for one run, `{workspace}/checkpoints/{run_id}/`
where `run_id` is `YYYYMMDDHHMMSS_<slug>`. All state lives here; `PathManager`
(`ari/paths.py`) is the single source of truth. API keys are never stored here —
they come from `.env` or the environment. Holds `experiment.md`, `meta.json`,
`launch_config.json`, `tree.json` / `nodes_tree.json` (the serialized node
tree), `results.json`, `idea.json`, `cost_trace.jsonl` / `cost_summary.json`,
`settings.json`, `memory.json`, `ari.log`, `.ari_pid`, and `uploads/`. See
[Architecture → File Structure](../concepts/architecture.md#file-structure) and
[`refactoring/notes/07_checkpoint_model.md`](../../refactoring/notes/07_checkpoint_model.md)
for the full layout + the read-path resolvers.

**node work_dir**
Where a node's files physically live: `{workspace}/experiments/{run_id}/{node_id}/`
(`PathManager.node_work_dir`) — under `experiments/`, *not* the checkpoint. The
agent writes scripts/data/binaries here; `node_report.json` is written here on
completion. A legacy layout placed each node's tree at
`{checkpoint}/node_*/tree.json` (still read as a fallback by
`ari.checkpoint.load_nodes_tree`).

**artifact**
A non-metadata file produced inside a node work_dir. Defined negatively by
`PathManager.is_meta_file` / `META_FILES`: ARI metadata (`tree.json`, `*.log`,
`node_report.json`, `*_access.jsonl`, …) is diagnostics, never copied into node
work_dirs nor surfaced as an artifact. Cross-checkpoint paper artifacts live
under `paper_registry/papers/<paper_id>/`. Publication-curated artifacts ship in
the **EAR** bundle.

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
