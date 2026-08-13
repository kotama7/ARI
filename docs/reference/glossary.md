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
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/api_orchestrator.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/config/profiles
    role: config
last_verified: 2026-08-13
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
A child that changed nothing relative to its parent after execution. When the
pinned problem declares `score_inputs`, sterility is decided by comparing the
sha256 of exactly those files; otherwise it falls back to a whole-`work_dir`
diff (`added = modified = deleted = 0`, or `added = modified = 0` when the
parent `work_dir` was not copied). Either way the node is marked
`_sterile = True` and pruned, and a sterile child never retires its parent;
the whole-`work_dir` path additionally clamps `_scientific_score` to `0.0` and
`has_real_data` to `False`, while the `score_inputs` path leaves the measured
score, `has_real_data` and `evaluation_status` untouched. This is what stops a
child from "inheriting" the parent's results without running anything. See
[Architecture → work_dir inheritance](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7).

**should_prune**
The hard-cutoff predicate in BFTS: prune when `current_total ≥ max_total_nodes`,
`depth ≥ max_depth`, `_sterile is True`, or `_valid_for_frontier is False`
(RQGM selective erasure). No LLM judgement enters here. See
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
is a `ari-core/config/reviewer_rubrics/<id>.yaml` file. Two selectors pick one
independently: `ARI_RUBRIC` (default `neurips`) for the BFTS scoring axes, and
the top-level `paper_rubric` key in `workflow.yaml` (default
`generic_conference`), passed to the review stage as an explicit `rubric_id`.
Set both to the same id for one venue to drive scoring and review together. See
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
coverage / operand resolution / figure existence. Default-on in `warn` mode,
which blocks the FINAL phase on the objective-integrity `always_block_on` tier
only (invariant violation, failed or uncovered correctness, unmeasured ceiling,
non-reproducible recompute, cross-run or unbound evidence); set
`claim_gate_policy.mode: strict` (or `ARI_CLAIM_GATE_MODE=strict`) to
additionally block on the configured `block_on` findings and uncovered result
numbers in strict sections. Draft-phase reports never block. A
`comparison_scope` of `any` (default) treats a cross-environment comparison as a
transparency warning, while `same_environment` makes it a blocking error. See
[Configuration](configuration.md).

**mint-once (contract freeze)**
The rule that the run-level `metric_contract.json` is written once: the first
`make_metric_spec` call that resolves an idea-owned Research Contract — or
admits a human-reviewed `propose_metric_contract` proposal — persists the
projection, and every later call reads that file back and returns it
(`contract_frozen: true`) instead of re-extracting. A re-mint whose
`projection_digest` differs from the persisted one is refused, not an
overwrite. LLM naming is not referentially stable, so a mid-run regeneration
would change the evidence vocabulary and hide already-emitted evidence from the
exact-match gate. With no admitted contract nothing freezes: the response is
`contract_frozen: false`, `admission_status: human-review-required`, and the
parser output is evidence only. See
[File formats](file_formats.md#metric_contractjson).

## Memory

**ancestor scope**
The rule that a node may read memory only from its ancestor chain (root → parent),
never from siblings. `search_memory` refuses any id outside the transport-signed
lineage, and the backend additionally filters on `node_id ∈ ancestor_ids`. See
[Memory architecture](../concepts/memory.md).

**CoW (Copy-on-Write)**
The write guard that keeps ancestor memory byte-stable across siblings:
write-side tools reject any `node_id` that is not the self node of the
transport-signed `NodeContextV1` on the call. A `$ARI_CURRENT_NODE_ID` in the
environment carries no authority. See [Memory architecture](../concepts/memory.md).

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
Skills may import only from `ari.public.*`. There are 17 `ari-skill-*` packages;
the shipped `workflow.yaml` enumerates 13 of them explicitly. See
[MCP skills](skills.md).

**VirSci**
The multi-agent deliberation that turns a research goal into a hypothesis and a
primary metric, run once at the root node via `generate_ideas`. See
[Architecture](../concepts/architecture.md#full-data-flow).

## RQGM (opt-in constitutional governance)

Terms specific to the opt-in `ari_rqgm` execution mode. None of them apply
to a default run. See [Execution modes](../guides/execution_modes.md) and
[RQGM evaluation](../guides/rqgm_evaluation.md).

**simple_bfts / ari_rqgm (execution modes)**
The two values of `ari.mode`. `simple_bfts` (default) is current ARI,
unchanged — it constructs no RQGM object and imports no `ari.rqgm` module.
`ari_rqgm` opts in to epoch governance and also requires the
`rqgm.enabled: true` interlock; any disagreement fails safe to `simple_bfts`
with a warning (`ari/rqgm/mode.py`). See
[Execution modes](../guides/execution_modes.md).

**epoch**
The governance time-slice of an `ari_rqgm` run. A boundary transaction fires
every `rqgm.epoch.nodes_per_epoch` new BFTS nodes (default 10; `<= 0` keeps
the run in `epoch_000`). Governance, registry transitions, and replay-pool
admission happen only at these boundaries.

**EpochState**
The immutable per-epoch freeze of the active prompt/component set and utility
policy (`ari/rqgm/state.py`, snapshotted to `epoch_state.json`). Frozen for
the epoch's duration and fingerprinted without wall-clock fields, so later
registry changes never leak into a closed epoch.

**utility policy hash**
`hash12(canonical_json(body))` over the epoch utility-policy body —
`{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}`
(`utility_policy_body` / `seal_utility_policy` in `ari/rqgm/state.py`). The
seal is never part of the bytes it seals, and the same value is the registered
`utility_policy` entry's `prompt_hash`. A second, disjoint policy — the
penalty policy `{penalty_cap, severity_weights, verdict_factors}` computed in
`ari/rqgm/adversarial/engine.py` — is carried under the same key name on
records written before the governed-utility work; the two key sets never
overlap, so the two hashes are never equal. Scores formed under different
hashes are not one series.

**ConstitutionalKernel**
The non-evolving Layer-0 checker (`ari/rqgm/kernel.py`): a pure, deterministic
validator that returns byte-stable `KernelReport` verdicts and writes nothing.
Severities are frozen in code (`kernel_rules.py`), never configurable; only
the posture (`rqgm.kernel.enforcement`: `standard` / `audit_only`) and float
tolerance live in config.

**GovernanceOrchestrator**
The single epoch-boundary governance entry point (`ari/rqgm/governance/`):
evidence gathering, prosecution, defense, and adjudication over the closing
epoch, self-audited by the ConstitutionalKernel. Budgets and posture live
under `rqgm.governance` / `rqgm.replay`.

**RegistryTransitionEngine**
The single writer of registry status (`ari/rqgm/transition_engine.py`). It
turns a governance outcome into a committed `EpochTransition`
(activations / retirements) persisted through the RQGM store; no other
component may change a prompt's or component's status.

**registry status**
The ten-value lifecycle shared by prompts and components
(`ari.rqgm.events.STATUS_VALUES`, a closed set): `candidate`, `validated`,
`shadow`, `probationary_active`, `active`, `warning`, `probation`,
`quarantine`, `retired`, `banned`. `active` and `probationary_active` together
form the frozen per-epoch active set. See
[RQGM GUI read models](rqgm_gui_read_models.md), section "Two vocabularies,
two state machines".

**transition rule id (`T1`–`T21`)**
Every registry status change pins one row of the transition table in
`ari/rqgm/transition_rules.py`, named by a `rule_id` from `T1` to `T21`. An
edge absent from that table, or a declared `rule_id` that contradicts it, is a
ConstitutionalKernel violation. Emergency quarantine edges are the separate
`EMERGENCY_EDGE` set. See [RQGM schemas](rqgm_schemas.md), section "Transition
schema (Task 09)".

**FrontierRepairEngine**
Runs at the epoch boundary after a transition with retirements
(`ari/rqgm/frontier_repair.py`): traces records materially dependent on a
retired `prompt_hash`, marks them stale (logical-only — nothing is deleted),
recomputes what survives, and rebuilds the BFTS frontier deterministically.

**node score state**
The separate five-value vocabulary for a node's score — `computed`,
`recomputed`, `stale`, `invalidated`, `removed` — a different state machine
from **registry status**, never mixed into one field or one legend. All five
are *logical* states: none of them means the node's files were deleted, and
"Deleted" is not a valid label for any of them. Backed by the node metric
sentinels `_stale`, `_stale_reason`, `_valid_for_frontier` and
`_erasure_event_id` (`ari/rqgm/frontier_repair.py`). See
[RQGM GUI read models](rqgm_gui_read_models.md), section "Two vocabularies,
two state machines".

**ProposalRecord / ProposalSummaryView**
A `ProposalRecord` is one archival proposal (append-only
`{checkpoint}/proposals/proposal_records.jsonl`); a `ProposalSummaryView` is
the bounded summary derived from it — the **only** shape BFTS ever sees
(`ari/rqgm/proposals/records.py`). The `ProposalRouter` dispatches generation
across the generator registry under `proposal_router.*` budgets; the VirSci
generator is opt-in and off by default.

**PromptSpec**
One versioned prompt identity (`ari/rqgm/prompt_spec.py`). Immutable: any
change is a new `prompt_id` + `prompt_hash`, never an edit. Evolved template
bodies are stored write-once under `{checkpoint}/rqgm_prompts/`.

**RawAttackRecord (raw attack)**
One unadjudicated adversary attack, id `atk_*`
(`ari/rqgm/adversarial/records.py`). Audit-log material only: nothing reads it
into any score. Its adjudicated descendant is the ValidatedAttackRecord below,
so a raw-attack count and a penalty are separate quantities and must not share
a label.

**ValidatedAttackRecord**
An adversarial finding that survived adjudication — it exists only for
verdicts `valid` / `partially_valid`, carries a `vat_*` id
(`ari/rqgm/adversarial/records.py`), and is the only attack shape admissible
to the replay pool.

**UtilityRecord**
One governed-utility audit record, id `utl_*`, appended to
`rqgm_adversarial_cases.jsonl` (`ari/rqgm/adversarial/records.py`): the base
score, penalty and final score for one node, with the policy it was formed
under stored *by value* so a later recompute needs no registry lookup. The
node itself keeps the matching `_pre_penalty_score` /
`_validated_attack_penalty` metric sentinels. See
[RQGM GUI read models](rqgm_gui_read_models.md), section "The two score-rewrite
channels".

**AdversarialReplayPool**
The curated pool of adjudicated failure cases
(`ari/rqgm/adversarial/pool.py`), snapshotted to
`{checkpoint}/rqgm/adversarial_replay_pool.json`; the append-only truth is
`rqgm_adversarial_cases.jsonl`. Admission happens only at epoch boundaries;
sizing lives under `rqgm.adversarial.pool.*`.

**selective erasure**
Logical-only invalidation of records produced by — or materially dependent
on — a retired prompt. Nothing is physically deleted or rewritten: staleness
lives in `SelectiveErasureEvent` / `FrontierRebuildEvent` audit-log lines and
the derived `rqgm_erasure_state.json` rollup, and readers derive `stale` at
read time.

**clean-room regeneration**
Drafting a retired role's replacement prompt without access to the retired
prompt's text (`ari/rqgm/clean_room.py`, `CleanRoomCoordinator`). Fail-closed
for candidate admission, fail-open for the run: on any violation the role
falls back to its committed baseline template and the loop continues.

**meta tier**
The highest of the three registry tiers (`fixed` / `institutional` / `meta`).
Meta-tier governance components may evolve, but their authority cannot
expand: capability flags are deny-by-default and checked against frozen
authority tables in `ari/rqgm/meta_rules.py`.

## Configuration & launch

**project**
The GUI's top-level entity, and the only one of its kind:
`GET /api/v1/projects` returns exactly one virtual project whose id is
`default` (`DEFAULT_PROJECT_ID` in `ari/viz/v1/queries.py`) and whose run list
is a checkpoint-directory scan over the checkpoint search bases. Any other id
answers a typed `404`; there is no create / rename / delete, and no run-scoped
endpoint carries a project segment, so a `project_id` never narrows anything.
See [GUI architecture](../concepts/gui_architecture.md), section "The entity
model is one level deep".

**environment profile (`--profile`)**
One of the bundled deployment overlays `laptop` / `hpc` / `cloud`
(`ari-core/config/profiles/<name>.yaml`), selected by the CLI `--profile`
flag. It is *not* a deep merge: `_apply_profile` (`ari/cli/run.py`) applies
exactly `bfts.max_total_nodes`, `bfts.max_parallel_nodes` (historical spelling
`bfts.parallel`, accepted only when `max_parallel_nodes` is absent),
`hpc.enabled` and `hpc.scheduler`; every other key in the file is ignored, and
the resolver warns listing what it dropped. A different concept from the
execution mode (`ari.mode`), and from the PaperBench rubric field
`execution_profile`. See [Configuration](configuration.md), section
"Resolution model".

**`resolved_config.json`**
The launch manifest `POST /api/v1/runs` materializes into the checkpoint
(`ari/viz/v1/launch.py`) — the previewed resolved configuration made real at
launch. Additive: `launch_config.json` is still written for the legacy display
path. Secrets never appear in `values` or `provenance`, only as
`secret_references` flags, and `digest` is `sha256:` over the canonical JSON of
`values` alone, so it is computed over the already-redacted document. Read back
by `GET /api/v1/runs/{run_id}/resolved-config`. See
[Configuration](configuration.md), section "`resolved_config.json` (the launch
manifest)".

**paper mode (`linear` / `rqgm_archive`)**
The two values of `paper.mode` — an axis independent of the execution mode, so
all four combinations are valid. `linear` (default) preserves the current paper
pipeline; `rqgm_archive` opts in to paper-archive co-evolution and *also*
requires the `rqgm.paper.enabled: true` interlock, a half-set pair resolving
back to `linear`. The effective mode is recorded once per paper phase in
`{checkpoint}/paper_archive_state.json` (`ari/rqgm/paper_runtime.py`) together
with a `mode_source` and a `switch_journal`.

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

**research phase**
Where a run sits in its own lifecycle: `idle`, `starting`, `bfts`, `paper`,
`review`. Derived from which checkpoint artifacts exist — `current_phase` in
`ari/viz/services/state_service.py`, the same five tokens the GUI carries as
`RESEARCH_PHASES`. The run Overview renders it as its own labelled row, never
merged with the governance-stage row (which appears only for an RQGM run).

**sub-experiment (child run)**
A run launched from a parent checkpoint. The child records its lineage in its
own `meta.json`: `parent_run_id`, `recursion_depth`, `max_recursion_depth`
(default 3, `api_orchestrator.DEFAULT_MAX_RECURSION_DEPTH`) and
`inherit_idea_index`. Two guards refuse the launch — depth at or above the
ceiling, and a parent whose `meta.json` carries `parent_terminated` (written by
`ari/cli/lineage.py` when a lineage decision chose `terminate`). This is a
relation *between* runs, distinct from the BFTS node tree inside one run. See
[REST API](rest_api.md), section "Sub-experiments + lineage".

**checkpoint**
The self-contained directory for one run, `{workspace}/checkpoints/{run_id}/`
where `run_id` is `YYYYMMDDHHMMSS_<slug>`. All state lives here; `PathManager`
(`ari/paths.py`) is the single source of truth. API keys are never stored here —
they come from `.env` or the environment. Holds `experiment.md`, `meta.json`,
`launch_config.json`, `tree.json` / `nodes_tree.json` (the serialized node
tree), `results.json`, `idea.json`, `cost_trace.jsonl` / `cost_summary.json`,
`settings.json`, `memory.json`, `ari.log`, `.ari_pid`, and `uploads/`. See
[Architecture → File Structure](../concepts/architecture.md#file-structure)
for the full layout, and [File formats](file_formats.md) for the per-file
schemas. An `ari_rqgm` run additionally writes the RQGM state files
(`rqgm_state.json`, `rqgm_registry.json`, `rqgm_audit.jsonl`, `proposals/`,
`rqgm_prompts/`, …) — absent on every default run.

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
work_dirs. The check is scoped — `is_meta_file(name, scope="node")` un-claims
the names a node legitimately owns (`results.json` and any `.log` other than
`ari.log`), so those still surface as artifacts of that node. Cross-checkpoint
paper artifacts live
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
[Execution modes](../guides/execution_modes.md) ·
[Configuration](configuration.md)
