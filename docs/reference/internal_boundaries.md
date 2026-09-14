---
sources:
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/pipeline/orchestrator.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_wizard.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/context_views.py
    role: implementation
  - path: ari-core/ari/rqgm/governance/__init__.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-skill-paper-re/src/_compute/computer.py
    role: implementation
  - path: scripts/snapshot_contracts.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/test_manuscript_assurance_boundary.py
    role: test
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_governance.py
    role: test
  - path: ari-core/tests/test_contract_snapshots.py
    role: test
last_verified: 2026-08-16
---

# Internal boundaries

How ARI talks to the three things it cannot do in pure Python: **LLM
providers**, **the OS / schedulers / containers**, and **the two orchestration
engines**. This is contributor-facing reference: where the boundary lives, what
the sanctioned call shape is, and the concurrency hazards any change here must
preserve. (For the stable cross-package surface see
[public_api.md](public_api.md); for config precedence see
[configuration.md](configuration.md); for on-disk layout see
[glossary.md](glossary.md) and [Architecture](../concepts/architecture.md).)

## LLM boundary

ARI's LLM boundary is **not** "everything must call `LLMClient`". It is a
three-part pattern, and direct `litellm.{completion,acompletion}` calls are the
**sanctioned** shape:

1. **`litellm`** is the provider-abstraction layer — modules call
   `litellm.completion` / `acompletion` directly with a model id.
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** is the single
   model-normalisation helper. It applies the provider prefix (including the
   CLI-shim `openai/claude-cli` rule) so a bare model name routes correctly.
   Its signature and return values are **frozen**: it *transforms* a model id
   rather than constructing an object, so it was deliberately kept out of the
   `ari._factory.BaseRegistry` string-dispatcher unification (see the
   decision note above its definition in `routing.py`).
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** monkey-patches
   `litellm.completion`/`acompletion` **process-wide** to (a) merge default cost
   metadata (skill / phase from `bootstrap_skill`, plus `epoch` once `ari_rqgm`
   opens one; `node_id` is not a process default — it rides the caller's own
   `metadata=`, e.g. `LLMClient.set_context`) and
   (b) apply `_apply_ari_routing`
   (`resolve_litellm_model` + CLI-shim `api_base` fill-in) on every call. Once
   installed, *every* direct litellm call — from any module or skill — gets ARI
   routing + cost capture transparently, at one point.

`ari.llm.client.LLMClient` is a **convenience wrapper** over `litellm.completion`
used by the ReAct agent loop; it is **not** a mandatory chokepoint, and the
codebase deliberately does not funnel everything through it.

The injector is installed via `cost_tracker.set_default_metadata` /
`init_from_env`, reached through `bootstrap_skill("<name>")` at the top of every
skill `server.py` **that calls an LLM** — the skills that never import `litellm`
(benchmark, coding, harness, hpc, knowledge, memory, orchestrator,
tool-registry) do not install it.

**Fragility to preserve:** CLI-shim routing and cost *attribution* depend on the
injector being installed **before the first litellm call** in a process (the
recording itself rides the success/failure callbacks `cost_tracker.init`
registers beside the injector, so `set_default_metadata` alone gives routing but
no capture). LLM-calling skills guarantee both at import via
`bootstrap_skill`. Core CLI/pipeline modules
(`evaluator`, `orchestrator/lineage_decision`, `root_idea_selector`,
`pipeline/context_builder`) call litellm directly and pass `api_base`/model
themselves, so they route correctly even without the global injector — but they
would miss cost capture if it is absent. `pipeline/context_builder` is the one
pipeline-package direct call that does its own env resolution rather than
`resolve_litellm_model` (a known low-value seam).

## Execution boundary (OS / scheduler / container)

Sanctioned exec modules — changes to execution behaviour belong here:

| Module | Owns |
|--------|------|
| `ari/container.py` | container exec: `detect_runtime`, `run_in_container` (Popen + `start_new_session=True` + `ari.execution.build_minimal_environment`), `container_shell_argv` / `run_shell_in_container` (with a `network="inherit"` or `"deny"` switch), `pull_image`. `_run_shell_sandboxed` is now only a compatibility adapter: it builds an `ExecutionRequestV1` and calls `ari.execution.execute_local`. An unsupported mode raises `ValueError` instead of falling back to the host. Re-exported by `ari.public.container`. |
| `ari/execution.py` | the process primitives container exec delegates to: `execute_local` (`os.setsid` plus `RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_NPROC`/`RLIMIT_FSIZE` in `_preexec`, and group SIGTERM→SIGKILL on timeout) and `build_minimal_environment` (an explicit environment, never a parent copy). `ARI_MAX_CHILD_PROCS` reaches it as `ExecutionLimitsV1.max_processes`. |
| `ari/env_detect.py` | scheduler/runtime probes: `detect_scheduler` (`sinfo`/`qstat`/`bhosts`/`qhost`/`kubectl`), `detect_container` (a `shutil.which` for apptainer/singularity/docker), `get_slurm_partitions` (`sinfo --noheader`) — read-only, best-effort, no hardcoded cluster knowledge. |
| `ari/mcp/connection.py` | `SkillConnection` — spawns one skill stdio server via the MCP SDK `stdio_client` (a wrapper, not a raw spawn). `ari/mcp/client.py:MCPClient` owns the pool, discovery and dispatch over these connections. |
| `ari-skill-hpc/ari_skill_hpc/scheduler.py` | the canonical SLURM submit/status/cancel (`SlurmScheduler`, driven by `LocalCommandRunner` = `asyncio.create_subprocess_exec`, or `RemoteCommandRunner` = paramiko); submission is always `sbatch --parsable --export=NIL`. `ari_skill_hpc/slurm.py` keeps `SlurmClient` as the environment-configured owner of one such scheduler. |

Known duplication to consolidate toward these owners (not incorrect behaviour,
but drift risk): `viz/api_memory.py` re-derives container-runtime dispatch.
`ari-skill-paper-re`'s **reproduce path** has consolidated two of its three
substrates: it submits through `ari_skill_hpc.SlurmScheduler` (`src/server.py`)
and runs its local attempts through `ari.execution.execute_local`
(`src/sandbox.py`). Its container attempts are still its own —
`sandbox.py:_external_command` hand-builds the `docker run` /
`apptainer exec` argv and `execute_container_attempt` dispatches it with
`asyncio.create_subprocess_exec(..., start_new_session=True)` rather than
through `ari.container`. Its
**PaperBench agent computer** (`src/_compute/computer.py`) is a further
implementation of both: `ApptainerComputer.send_shell_command` hand-builds an
`apptainer exec` argv and `LocalComputer.send_shell_command` a bare
`bash --noprofile --norc -c` argv, and both dispatch through the module's own
`_run_subprocess` (`asyncio.create_subprocess_exec(..., start_new_session=True)`
plus a `killpg` SIGTERM→SIGKILL group teardown) rather than through
`ari.execution`; the module's only core import is
`ari.public.execution.WorkspaceRefV1`. The container half has already drifted
from `container_shell_argv`: the skill emits `--cleanenv --containall --no-home`
with `--bind {work_dir}:/work:rw --pwd /work` and no `--writable-tmpfs`, where
core emits `--cleanenv --containall --writable-tmpfs` with a bare
`--bind <workdir>`. This is production code, not a dead seam —
`src/server.py` → `_replicator_agent.run_replicator_agent` →
`_compute.make_computer` — so it is the file to read when auditing
container-exec or local-exec duplication.

**`ari.viz.state` process-handle coupling.** `ari/viz/state.py` holds live OS
handles as module globals (imported as `_st`): `_last_proc` (most-recent
experiment Popen; torn down by `api_process._api_stop` via
`os.killpg(os.getpgid(pid))`), `_running_procs` (checkpoint-path→Popen map,
written by three handlers — `api_experiment.py`'s `/api/launch` and
`/api/run-stage` plus the `/api/v1` launch path in `viz/v1/launch.py`), and
`_gpu_monitor_proc` (its logic lives in
`api_process.py`; the server reaps a stale monitor across restarts). This is the
canonical example of the "avoid hidden coupling through global mutable state"
caution — touch its lifecycle only deliberately.

## The two orchestration engines

The runtime is **two distinct engines**, not one linear pipeline — `workflow.yaml`
declares phase tags (`bfts`, `paper`) but the split is across:

| Phase | Driver |
|-------|--------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` — a hardcoded `while pending or frontier` loop (generate_idea → select_and_run → evaluate → frontier_expand). `bfts_pipeline[]` is read only for enabled/disabled flags. |
| **post-BFTS pipeline** (transform / figures / paper / review / ORS reproduction / publish) | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline`, a thin wrapper over `pipeline/driver.py:WorkflowDriver.run` — a single linear cursor loop over `pipeline[]`; all sub-phases are consecutive stages. |

`run.py` clears `.pipeline_started`; `WorkflowDriver.run` touches it at pipeline
start (GUI phase detection). A BFTS-sanity gate can abort the post-BFTS pipeline early
(`ARI_FORCE_PAPER` overrides). Non-`react:` stages run via
`stage_runner._run_stage_subprocess`, which builds a Python script string and
`subprocess.run([sys.executable, "-c", ...])` — each non-react stage is a direct
fork that constructs its own `MCPClient` in the child.

### Concurrency hazards (preserve under any change here)

1. **Env-var-at-first-connect timing.** An MCP server no longer inherits
   `os.environ`. `mcp/child_environment.py:build_child_environment` resolves a
   fail-closed allowlist — `SAFE_INHERITED_ENV_NAMES` (`PATH`, `LANG`, `LC_ALL`,
   `LC_CTYPE`, `TZ`, `TMPDIR`, the CA-bundle names) plus whatever the skill's
   `skill.yaml` declares under `required_env` / `optional_env` — and
   `SkillConnection` caches the result in `_server_parameters`, so the parent
   environment is read once, at the first connect. The timing invariant is
   therefore unchanged: `ARI_WORK_DIR` (declared `optional_env` by the coding and
   hpc skills) must be set **before** that first connect, or work-dir pinning
   breaks silently. The reproduce-sandbox vars (`ARI_REAL_GIT`, `ARI_REPRO_*`)
   are declared by no skill manifest, so they reach only the react /
   stage-runner subprocess paths, never a skill server.
2. **Shared-process state under parallel workers.** One `AgentLoop` instance and
   one `MCPClient` are shared by every node thread; `_run_loop` caps concurrency
   at `max_workers = max(1, min(cfg.bfts.max_parallel_nodes, 4))`, enforced by a
   `threading.Semaphore` rather than by the pool size (the pool is
   `max_workers + 8`, so a node waiting on a scheduler job can park and hand its
   permit back). Node identity is never carried in process-global state: the safe
   path is an explicit `ToolCallContextV1`, built once per node by
   `AgentLoop._node_tool_context`, threaded through `_execute_tool_calls`, and
   signed per connection into the `ari_context` tool argument by
   `SkillConnection.authorize_args`. `work_dir` is threaded explicitly for the
   same reason — an env lookup would race at `max_parallel_nodes > 1`.
3. **Shared checkpoint-tree writes.** There is **no git worktree**: concurrent
   committers all write the same `tree.json` / `nodes_tree.json` / `results.json`
   via one shared `agent._progress_cb` → `_save_tree_incremental`; thread-safety
   + throttle live in `ari.checkpoint.save_tree_incremental` (a lock plus a
   `time.monotonic()` minimum-interval throttle, 1.0 s by default, which
   `force=True` bypasses). Per-node work-dirs are isolated by
   `PathManager.node_work_dir(run_id, node_id)`.

## RQGM mode boundary (`ari.rqgm`)

The opt-in `ari_rqgm` mode (see
[Execution modes](../guides/execution_modes.md)) adds one more internal
boundary: **the `ari.rqgm` package must be invisible to a default run**.

**The enforced rule.** The default `simple_bfts` path never imports any
`ari.rqgm` module. Every core import site is lazy and gated on the *raw*
config flags before the import happens:

- `ari.core.build_runtime` — imports `ari.rqgm.mode` / `ari.rqgm.runtime`
  only when `ari.mode == "ari_rqgm"` or `rqgm.enabled` is set, and wraps the
  strategy only when `resolve_effective_mode(cfg)` is `ari_rqgm`. Inside that
  same branch `_install_capability_gate` imports `ari.rqgm.kernel` /
  `ari.rqgm.store` / `ari.rqgm.tool_policy` and returns the `MCPClient`
  wrapped in a `CapabilityGatedMCPClient` (fail-open: an install failure logs
  and hands back the ungated client).
- `ari/cli/run.py` — imports `ari.rqgm.state` only under the mode, to write
  `rqgm_state.json` and copy `constitution.yaml` at launch (and
  `reconcile_resume_mode` on resume: the persisted mode wins; a run can never
  be upgraded mid-flight).
- `ari/cli/bfts_loop.py` — imports the proposal store only when the opt-in
  `proposal_router.record_only: true` dual-write is set (default `false`
  never imports it; in `ari_rqgm` the router records natively so the import
  is skipped there too).
- `ari/cli/paper_dispatch.py` — imports `ari.rqgm.paper_runtime` /
  `ari.rqgm.paper_judge` only for the `rqgm_archive` paper mode; the resume
  import is additionally gated on `paper_archive_state.json` existing, so a
  linear checkpoint imports nothing. The mode string itself comes from the
  import-free `ari.config._effective_paper_mode_str`.
- `ari.config._effective_mode_str` mirrors the activation table
  **import-free**, so config handling itself never loads `ari.rqgm`.

**Wrap, never replace.** Under `ari_rqgm`, `build_runtime` returns a
`GovernedSearchStrategy` (`ari/rqgm/runtime.py`) that delegates all seven
`SearchStrategy` methods to the untouched real
`ari.orchestrator.bfts.BFTS` instance; the controller is discoverable via
`getattr(bfts, "rqgm", None)` so the 6-tuple return shape is preserved.
`ari.protocols` names RQGM classes only in docstrings — the Protocols are
structural (`runtime_checkable`), so importing `ari.protocols` pulls in
nothing from `ari.rqgm`.

**`rqgm` is a reserved attribute name.** `getattr(bfts, "rqgm", None)` is the
only supported way to discover the governance runtime, and the read is
duck-typed deliberately — the `GovernedSearchStrategy` docstring states the
rule as "detection is duck-typed attribute presence, never `isinstance` of
this concrete class". The wrapper is internal and unversioned, so no consumer
may branch on `isinstance(bfts, GovernedSearchStrategy)`; today none does. The
same `getattr` probe is repeated across `cli/bfts_loop.py`, `cli/run.py`,
`cli/projects.py`, `cli/manuscript_repair_runtime.py` and `core.py`, so the
name is reserved on **any** object handed around as the run's
`SearchStrategy`: do not attach an unrelated `rqgm` attribute to a strategy,
and if a future component needs richer discovery, add a typed accessor rather
than a second magic attribute.

**Enforcement.**
`ari-core/tests/test_rqgm_mode.py::test_build_runtime_default_is_identity`
builds a default runtime and asserts (a) no `ari.rqgm*` entry in
`sys.modules`, (b) the strategy is the plain `ari.orchestrator.bfts` object
with no `.rqgm` attribute, and (c) no `rqgm_state.json` / `constitution.yaml`
in the checkpoint. On the skill side, `ari.rqgm` is not re-exported through
`ari.public.*`, and `scripts/quality/check_import_boundaries.allow.yaml`
carries no `ari.rqgm` exception — no skill may import it.

**The governance facade is the only commitment.** One level down, inside the
package, the same discipline applies to the epoch-boundary audit.
`ari.rqgm.governance` exports exactly two names — `GovernanceOrchestrator` and
`GovernanceReport` — and
`ari-core/tests/test_rqgm_governance.py::test_facade_exports_only_the_two_public_names`
pins `__all__` to that pair. Everything the audit is made of lives in
underscore-private modules of that package: the reliability monitors
(`_reliability.py`), the evidence clerk and its admissibility checkers
(`_evidence.py`), the auditor/prosecutor and its bond accounting
(`_prosecution.py`), the defender (`_defense.py`), the boards and the
governance judge (`_adjudication.py`), the self-audit (`_self_audit.py`), plus
the nine-step pipeline itself (`_pipeline.py`) and the record dataclasses
(`_records.py`, out of which only `GovernanceReport` is lifted into the
facade). Nothing else is re-exported, nothing is added to `ari.public.*`,
nothing gains a CLI flag, and nothing is exposed as an MCP tool. The only
non-test call site in the tree is `RQGMRuntime.run_epoch_audit`
(`ari/rqgm/runtime.py`), which constructs the orchestrator lazily and calls
`audit_epoch` once per epoch boundary.

That narrowness is deliberate. The fine-grained actor names are a conceptual
vocabulary, not an interface: publishing a dozen of them would freeze
still-moving signatures into the frozen contract-snapshot surface
(`ari-core/tests/fixtures/contracts/public_api.json`), where every later
refactor becomes a golden-file diff. Holding the facade at one class, one
public method and one return type lets the internal actors be reshaped freely
while the single call site and the `GovernanceReport` the transition engine
consumes stay stable.

**The mode costs no contract surface.** Activation is configuration and
environment only: RQGM adds no `ari` CLI command or flag and exports no symbol
through `ari.public.*`, so neither frozen snapshot needs regeneration for it —
`ari-core/tests/fixtures/contracts/cli_tree.json` and `public_api.json` (built
and verified by `scripts/snapshot_contracts.py`, gated by
`ari-core/tests/test_contract_snapshots.py`) contain no `rqgm` entry at all.
That is a deliberate budget decision, not an oversight: a `--mode` flag would
move the execution mode into the frozen CLI tree and turn every later
mode-related change into a golden-file diff. Keep new mode surfaces in
configuration — the same reasoning is why the wrapper above is discovered by
attribute rather than by type.

### Governance context views (`ari.rqgm.context_views`)

One more rule lives inside the package, and it is the one most likely to be
read as a general pattern when it is not: **each governance actor is handed a
capped, role-specific projection — a *view* — never the archive.** The builders
in `ari/rqgm/context_views.py` are pure (no LLM, no I/O) and byte-deterministic,
so a view is a function of its inputs and of nothing else.

**The BFTS row is the load-bearing one**, and it is stated in three places at
once. For the `CK-CTX-001` code and its severity see
[RQGM schemas → Constitutional violation codes](rqgm_schemas.md#constitutional-violation-codes);
for the view's own field list see
[`proposal_summary_view.schema.json`](rqgm_schemas.md#proposal-summary-view-schema-json).

| Layer | Mechanism | Does it stop anything? |
|---|---|---|
| construction-time | `build_bfts_summary_context` accepts a `ProposalSummaryView` and raises `TypeError` for anything else — a `ProposalRecord`, and the summary's own `to_dict()` too | Yes; this is the only layer that raises. |
| check-time | `ConstitutionalKernel.validate_context_scope(role, view)` subtracts the role's whitelist from the view's key set and reports `CK-CTX-001` for the remainder | No — warn-and-flag, never blocks node execution. |
| test-time | `ari-core/tests/test_rqgm_context_views.py::test_no_archive_field_reaches_the_rendered_expand_context` renders a fixture `ProposalRecord` carrying every `ARCHIVE_ONLY_FIELDS` name and asserts that neither those names nor a sentinel survives into the rendered string | In CI only. |

**One whitelist, constitution-pinned.** `PROPOSAL_SUMMARY_FIELDS` is not a copy
of the kernel table — it *is* `kernel_rules.CONTEXT_VIEW_WHITELISTS["generator"]`
(BFTS rides the `generator` role), and
`test_rqgm_context_views.py::test_whitelist_constant_is_the_kernel_table_entry`
pins the `is` identity so a second list cannot appear and drift. The table is
serialised into `kernel_rules._canonical_rules_payload()` under
`context_view_whitelists`, so it rides `constitution_hash()`: adding or widening
a row is an explicit re-pin, the same treatment the transition table gets.

**Read the ordering before you rely on the layering.** The only non-test caller
in `ari-core/ari` is `RQGMRuntime.render_expand_context` (`ari/rqgm/runtime.py`),
reached from `GovernedSearchStrategy.expand` when the caller passed an
`idea_context` kwarg. It runs the check-time layer **first**
(`_flag_bfts_view_scope` — a log warning plus a `kernel_report` line on the
immutable audit log, the whole hook wrapped fail-open) and the type gate
**second**. What actually prevents the leak is the type gate: an out-of-scope
view is a plain `dict`, `build_bfts_summary_context` raises, the surrounding
`try` in `render_expand_context` swallows it and returns `""`, and the caller
keeps its `idea.json` context. The kernel layer records the fact; it does not
prevent it. Note too that the `_enforce_scope("generator", …)` call *inside* the
builder runs after the type gate, on `ProposalSummaryView.to_dict()`, whose key
set is exactly the ten whitelisted names — so on the BFTS row that in-builder
call can never produce a violation. It is belt-and-braces, not the check that
fires.

**Only three roles are kernel-checked at all.** `CONTEXT_VIEW_WHITELISTS` has
rows for `generator`, `paper_writer` and `paper_reviewer`;
`validate_context_scope` looks the role up and returns a clean report when the
lookup misses, so every other role is unchecked by design
(`test_a_role_without_a_whitelist_is_unchecked` pins that). The Judge,
adversary, reviewer and governance views therefore rest on two weaker
mechanisms, and it is worth being precise about how weak:

- **Constructive exclusion** — the builder has no parameter for the material it
  must not see (`build_reviewer_context` cannot be handed another reviewer's
  output; `build_judge_context` is given attack, defense and bundle only and
  never holds a registry handle). Real, but a property of the signature rather
  than a check.
- **`_scrub` key deletion** — `JUDGE_EXCLUDED_KEYS` (`frontier_scores`,
  `frontier_rank`, `scientific_score`, `_scientific_score`, `utility`,
  `utility_score`) and `GOVERNANCE_EXCLUDED_KEYS` (`prompt_text`, `prompt_body`,
  `template`, `template_text`, `body`) are dropped recursively **by key name**,
  and every string is truncated at `_FIELD_CAP` (4000) characters. Key-name
  deletion is exactly as strong as the name list: the same value under a key the
  set does not name survives untouched.

**Most of the module has no production caller — read it as declared, not as
observed.** Inside `ari-core/ari`, `build_bfts_summary_context` is the only
builder with a non-test call site. `build_reviewer_context`,
`build_adversary_context`, `build_judge_context`, `build_governance_context` and
`build_paper_writer_context` have none; they are exercised only by
`test_rqgm_context_views.py` (and, for `build_paper_writer_context`,
`test_rqgm_paper_candidate.py`),
and `CHARTER_BLOCK_CAP = 1200` has no consumer at all — its test only asserts
the number and that it is ≤ `ari.agent.loop._IDEA_FIELD_CAP`. The module is the
BFTS row plus a set of prepared-but-unwired projections; do not cite the others
as a description of what a run does.

**The paper-reviewer view is built somewhere else, and that is a workaround, not
a design.** `ari/rqgm/paper_judge.py:_paper_reviewer_string_view` assembles the
paper-reviewer view itself — four capped strings under the same four whitelisted
keys — because `context_views._plain` keeps only mappings and objects carrying a
`to_dict`, so a raw string projects to `{}`; the module comment records that
routing the archive's string inputs through `build_paper_reviewer_context`
silently dropped the draft body. It imports `PAPER_REVIEWER_FIELDS` to keep the
key set honest, but pins it with a bare `assert` instead of calling the kernel,
so the live paper-reviewer path emits no `CK-CTX-001` report of its own.

**If you add a governed role**, add its row to `CONTEXT_VIEW_WHITELISTS` —
accepting the `constitution_hash` re-pin — and call `_enforce_scope` from the
builder;
`test_rqgm_context_views.py::test_every_whitelisted_builder_runs_the_check`
inspects the source of all three whitelisted builders for exactly that call. A
builder for a role with no whitelist row is unchecked no matter how much it
scrubs.

### Manuscript compiler boundary (`ari.manuscript`)

The same one-way discipline governs the manuscript compiler, and it is worth
stating on its own because the arrow points the other way: `ari.manuscript` is
the package RQGM depends **on**, never the reverse.

**No module under `ari.manuscript` imports `ari.rqgm`.** The package's only
imports of another `ari` package are two lazy, function-local ones —
`ari.assurance.models.HarnessAttestationV1` (`manuscript/snapshot.py`, to parse
a node's harness attestation) and `ari.paper_contract.parse_paper_build`
(`manuscript/runtime.py`) — and neither of those reaches `ari.rqgm`:
`ari/paper_contract.py` imports no `ari` module at all, and `ari/assurance/**`
contains no `rqgm` reference. Inside `ari.manuscript` the name appears only as
data — the `Literal["simple_bfts", "ari_rqgm"]` and
`Literal["linear", "rqgm_archive"]` contract fields in `manuscript/contracts.py`,
the strings they are normalised to in `snapshot.py` / `coordinator.py`, and four
checkpoint-relative paths under `rqgm/kca/admission-v1/` in
`manuscript/authority.py:_AUTHORITY_FILES`.

**How RQGM state reaches the compiler instead.** Three channels, none of which
names an RQGM type:

| Channel | Shape |
|---------|-------|
| Mode | plain `str` keyword arguments — `compile_manuscript(..., exploration_mode="simple_bfts", paper_mode="linear")`, forwarded to `build_exploration_snapshot(..., exploration_mode=...)` and normalised to one of the two literals before it lands on the contract. There is no RQGM provider object and no typed RQGM block in either signature; `manuscript/runtime.py:prepare_runtime_manuscript` fills both from `ARI_MANUSCRIPT_EXPLORATION_MODE` / `ARI_MANUSCRIPT_PAPER_MODE`. |
| Node state | duck-typed reads off whatever node objects the caller already holds. `snapshot._get(value, name, default)` is `value.get(...)` for a mapping and `getattr(...)` otherwise, so `attestation_refs`, `verified_target_digest` and `metrics` are looked up by name, and a `simple_bfts` node that carries none of them simply yields the default. |
| Evidence | files read at checkpoint-relative paths, never handed over as objects. `snapshot._attestation_artifacts` digests whatever relative path a node's `attestation_refs` names and validates it as `HarnessAttestationV1` (statuses `present` / `stale` / `missing` / `invalid` — `stale` is the attestation that parses and whose `node_id` matches, but whose `target_digest` does not match the node's `verified_target_digest`, so the evidence stays visible while the node cannot certify publication; it is neither discardable like `invalid` nor publishable like `present`, and `test_manuscript_assurance_boundary.py::test_stale_target_attestation_remains_visible_but_cannot_publish` pins that); `authority.capture_repair_authority` only digests the fixed `_AUTHORITY_FILES` list (statuses `present` / `absent` / `unsafe_symlink`) without parsing it. In both, an absent or symlinked path yields a recorded status, not an exception. |

**The reverse edge is allowed and used.** `ari.rqgm.paper_runtime` imports
`ari.manuscript.digest.path_has_symlink_component` to re-check archive inputs,
and `ari/cli/paper_dispatch.py` is the layer that drives both — it lazily imports
`ari.rqgm.paper_runtime` / `ari.rqgm.paper_judge` and `ari.manuscript.runtime` /
`ari.manuscript.coordinator` side by side. `ari/cli/manuscript_repair_runtime.py`
is the pattern to copy for glue that needs both at once: it imports
`ari.manuscript.*` directly but reaches the governance runtime only through the
reserved `getattr(bfts, "rqgm", None)` probe described above. So RQGM may depend
on the manuscript contracts; the manuscript contracts may never depend on RQGM.
That is what lets one compiler serve both exploration modes and both paper modes
without a second implementation — the difference is recorded as field values
(`paper_mode`, and the `backend_version` string `coordinator.py` derives from it)
rather than branched into a parallel code path — and it is why an RQGM concept
the compiler needs must arrive through one of the three channels above rather
than as an import.

**Nothing enforces this direction.** There is no test and no quality-gate rule
for it: `scripts/quality/check_import_boundaries.yaml` constrains the skill→core
and core→skill edges, and its one core-internal knob
(`forbid_core_to_viz_from_cli`, off by default) covers only
`ari/cli/**` → `ari.viz.*`. The adjacent
rule that *is* enforced is a different one —
`ari-core/tests/test_manuscript_complete.py::test_default_cli_import_does_not_load_manuscript_domain`
asserts that importing `ari.cli` loads no `ari.manuscript*` module, which keeps
the compiler off the default import path but says nothing about what the
compiler may import. Until someone adds a check, treat the no-`ari.rqgm`-import
rule as a review obligation.

## GUI HTTP dispatch boundary

The viz server dispatches an HTTP request in exactly two places (for the layering
around them see [Dashboard architecture](../concepts/gui_architecture.md)): the
legacy `/api/…` surface is an `if`/`elif` chain over `self.path` in the
`BaseHTTPRequestHandler` subclass in `ari/viz/routes.py`, which imports each
handler directly from its `api_*` module; `/api/v1/…` is delegated to the
declarative `ROUTES` table in `ari/viz/v1/router.py`.

**`ari/viz/api_wizard.py: WIZARD_ROUTES` is not a third one.** The module
re-exports six wizard handlers under short names and then builds a four-entry
`{path: (method, callable)}` dict — but nothing in the tree imports the module,
in production or in tests, and no dispatcher consults the dict. Two consequences
for anyone touching the wizard: adding an entry to `WIZARD_ROUTES` does not
create a route, and the dict is not the wizard's contract — it has already
drifted, since one of its four paths (`/api/generate-config`) does not exist on
the server at all (the dispatcher answers `/api/config/generate`). The
REST-schema checker can parse a module-level `ROUTES` / `WIZARD_ROUTES` map
(`scripts/check_viz_api_schema.py: parse_declarative_routes`), but that path is
off by default — `use_declarative_routes: false` in
`scripts/quality/check_viz_api_schema.yaml` — precisely because this map is
stale, so the checker extracts routes from the `if`/`elif` chain instead. The
repo-root `DEPRECATION_REMOVAL.md` ledger records the symbol as a delete
candidate; until it is deleted, treat the two dispatchers above as the only
statement of which wizard endpoints exist.
