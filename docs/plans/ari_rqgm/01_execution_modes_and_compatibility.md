# Task 01: Execution Modes and Compatibility

> **Status**: planned · **Depends on**: 00 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI must gain a second execution mode — `ari_rqgm` (Constitutional ARI-RQGM epoch governance
and co-evolution) — without changing anything about how it behaves today. This task designs the
mode switch itself:

- the `ari.mode` / `rqgm.enabled` configuration keys and where they are read;
- the guarantee that `simple_bfts` (the default) is byte-for-byte the current ARI;
- the exact component set that `ari_rqgm` turns on;
- when mode switching is allowed (run start, epoch boundary) and forbidden (mid-epoch,
  mid-governance-transaction, mid-registry-transition, mid-frontier-rebuild);
- how VirSci optionality (`proposal_router.generators.virsci.enabled`) stays fully independent
  of the mode.

Every downstream RQGM task (02–13) hangs its config and activation logic off the switch designed
here. This plan resolves the Task-01 open questions recorded in the Task 00 investigation
([00_current_ari_investigation.md](00_current_ari_investigation.md) §5.9, Q-1–Q-6: config home,
workflow.yaml copy precedence, `build_runtime` return shape, constitution file distribution,
resume semantics, contract-snapshot budget).

## 2. Scope

- Typed config schema: `ari.mode`, `rqgm.enabled` (top-level skeleton only; subsections belong
  to Tasks 02/12), and the placement of `proposal_router.generators.virsci.enabled` (schema
  detail belongs to Task 03,
  [03_proposal_record_router_and_virsci.md](03_proposal_record_router_and_virsci.md)).
- Environment-variable overrides (`ARI_MODE`, `ARI_RQGM_ENABLED`) and their precedence.
- Deterministic effective-mode resolution (`resolve_effective_mode`) including the
  disagreement/interlock rules.
- Conditional construction in the composition root (`build_runtime`) via a Protocol-satisfying
  wrapper — no change to the 6-tuple return shape.
- Mode persistence in the checkpoint (`rqgm_state.json`) and resume semantics.
- Mode-switch timing policy and where the prohibition checks will later be enforced
  (contract only; enforcement is Task 04/09 work).
- Distribution decision for the bundled `constitution.yaml` (copy-once, workflow.yaml pattern).
- Compatibility statement: everything in Task 00's must-not-break register
  (00_current_ari_investigation.md §5.8, B-1…B-19) holds verbatim under `simple_bfts` and under
  `rqgm.enabled=false`.

## 3. Non-goals

- No implementation in this task plan (design only; implementation follows the plan and is a
  deletion-criteria item).
- No EpochState / registry schemas (Task 02), no ProposalRecord/Router/VirSciAdapter design
  (Task 03), no ConstitutionalKernel checks (Task 04), no GovernanceOrchestrator (Task 05).
- No epoch-boundary *mechanics* — this task defines when a switch is *allowed*; the boundary
  transaction itself is Task 02/09.
- No new CLI commands or flags in v1 (config + env activation only; keeps the contract
  snapshots for the CLI tree untouched).
- No GUI toggle in v1 (the env override is GUI-compatible by construction; a viz toggle is a
  possible follow-up — if ever pursued it enters as an auxiliary task plan registered in
  INDEX.md, not here).
- No changes to BFTS policy, evaluator, prompts, lineage decisions, or the paper pipeline.
- No profile (`--profile`) support for RQGM keys in v1 (see Risk R6).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| Typed config models | `ari-core/ari/config/__init__.py` — `ARIConfig`, `BFTSConfig`, `EvaluatorConfig` | `ARIConfig.model_config = {"extra": "allow"}` (line 284), but `load_config` filters raw YAML to `ARIConfig.model_fields` (lines 354, 361): **an `rqgm:` or `ari:` block is silently dropped today**. New first-class fields are the only clean way in. |
| Env-override pattern | `ari-core/ari/config/__init__.py` — `apply_bfts_env_overrides` (line 432), `apply_evaluator_env_overrides` (line 477), `export_resolved_config_to_skill_env` (line 515) | The validate-before-assign env override pattern and the setdefault skill-env bridge that `apply_rqgm_env_overrides` must copy. Env overrides run **after** profile application. |
| Config discovery | `ari-core/ari/config/finder.py` — `package_config_root`, `find_workflow_yaml`, `load_workflow_config` | `package_config_root()` = `ari-core/config/`; checkpoint-copy-first search order that RQGM readers must follow. |
| CLI entry / precedence | `ari-core/ari/cli/run.py` — `run`, `resume`, `_resolve_cfg`, `_apply_profile` | Where `apply_rqgm_env_overrides(cfg)` gets called (both commands, after `_apply_profile`, before `export_resolved_config_to_skill_env`). Also the workflow.yaml copy-to-checkpoint with the don't-clobber-GUI-copy guard (~lines 396–408) that `constitution.yaml` distribution reuses. `run`/`resume` bodies call `build_runtime`/`_run_loop` through late-bound `ari.cli` lookups — RQGM must not break this mock seam. |
| Composition root | `ari-core/ari/core.py` — `build_runtime` | THE place where conditional construction happens. Precedents: `hpc_enabled` skill drop (line 138 / 210), `axis_mode` evaluator dispatch (lines 163–198). `bfts: SearchStrategy = BFTS(cfg.bfts, bfts_llm)` is the exact line the RQGM wrapper decorates. The 6-tuple return is relied on positionally by 4 call sites — **wrap, never extend**. |
| Protocol seams | `ari-core/ari/protocols/search.py` — `SearchStrategy` (line 35), `NodeExecutor` (line 78) | Structural Protocols that `build_runtime` and `_run_loop` bind to; a `GovernedSearchStrategy` wrapper plugs in with zero changes elsewhere. |
| BFTS driver | `ari-core/ari/cli/bfts_loop.py` — `_run_loop` | Reads `bfts_pipeline` stage flags checkpoint-first, once, at loop start (~lines 96–110) — the read-once, checkpoint-first idiom the mode flag follows. The outer `while` head is the future epoch boundary (Task 02/05); this task only defines how `_run_loop` detects that RQGM is active (attribute presence on the wrapped strategy, §5.4). |
| Package-only readers (anti-pattern) | `ari-core/ari/cli/lineage.py` — `_load_lineage_decision_config`; `_run_loop` root_idea_selection block | These read only the **package** workflow.yaml while `bfts_pipeline` flags prefer the **checkpoint** copy — a live inconsistency. RQGM readers are checkpoint-first and must not extend the package-only pattern. |
| Checkpoint paths | `ari-core/ari/paths.py` — `PathManager.META_FILES` (line 381), `checkpoint_dir_from_env` | Every new checkpoint-root filename (`rqgm_state.json`, `constitution.yaml` is already covered by nothing — both need registration) must be added to `META_FILES` or it is copied into every node work dir. |
| Snapshot persistence | `ari-core/ari/checkpoint.py` — store methods + module shims (e.g. `save_prompt_versions_json`) | The pattern for the `rqgm_state.json` writer: byte-fixed formatting, store method + shim, best-effort. |
| Node-report hygiene | `ari-core/ari/orchestrator/node_report/builder.py` — `_INTERNAL_JSON_NAMES` (line 298) | `rqgm_state.json` must be classified as internal, not a publishable data output. |
| Reproducibility marker precedent | `ari-core/ari/orchestrator/web_provenance.py` | `bfts_web_provenance.json` (absence == reproducible trajectory) — the P5 pattern for opt-in behavior markers; `rqgm_state.json` plays the analogous role for mode provenance. |
| Governance precedent | `ari-core/ari/orchestrator/lineage_decision.py`; the lineage hook block in `bfts_loop.py` (~lines 721–827) | Config-gated, deterministic-rule-first, fail-open, JSONL-audited hook — the template every RQGM hook (including the future mode-switch execution) copies. |
| VirSci today | `ari-skill-idea/src/server.py` (+ `virsci_runtime.py`, `snapshot.py`) | The existing three-tier degradation when VirSci is unavailable; `virsci.enabled=false` maps onto it (Task 03 owns the details; this task pins the config key location and independence guarantee). |
| String-keyed registries | `ari-core/ari/_factory.py` — `BaseRegistry` | If mode-conditional policies become string-keyed later, this is the sanctioned pattern (with a Literal↔`keys()` parity test). Not needed for the mode switch itself. |
| Contract snapshots | `ari-core/tests/test_contract_snapshots.py`, `scripts/snapshot_contracts.py` | Budget decision: v1 adds no CLI command/flag and no `ari.public.*` symbol, so no golden regeneration is required. Any deviation is a deliberate, reviewed diff. |
| Config-key swap precedent | `ari-core/tests/test_bfts_prompt_selection.py` | Proof pattern that config-driven behavior swaps are testable via `ari.prompts.FilesystemPromptLoader` patching; the mode tests follow the same style. |
| Numeric defaults home | `ari-core/ari/configs/defaults.yaml` (+ `FilesystemConfigLoader` in `ari-core/ari/configs/_loader.py`) | Future RQGM numeric defaults (epoch length etc., Tasks 02/12) go here, not hard-coded. This task adds nothing to it yet. |

## 5. Proposed design

### 5.1 Configuration keys (authoritative shape)

Exactly the SPEC shape, as first-class typed fields:

```yaml
# workflow.yaml (all defaults shown; omitting the blocks entirely is equivalent)
ari:
  mode: simple_bfts        # simple_bfts | ari_rqgm
rqgm:
  enabled: false           # master interlock; subsections added by Tasks 02/12
proposal_router:           # skeleton only here; full schema in Task 03
  generators:
    virsci:
      enabled: false
```

Design decision (resolves Task 00 open question "config home"): **typed fields on `ARIConfig`**,
not raw-YAML re-reads. Rationale: `load_config` filters to `model_fields`, so typed fields are
picked up automatically from any workflow.yaml source (checkpoint copy, `--config`, package);
raw re-reads are what produced the package-vs-checkpoint inconsistency in
`root_idea_selection`/`lineage_decision`.

### 5.2 Effective-mode resolution (deterministic, pure)

`ari.mode` is the master switch; `rqgm.enabled` is a redundant safety interlock. Both must agree
for RQGM to activate. Disagreement fails safe toward current behavior:

| `ari.mode` | `rqgm.enabled` | Effective mode | Action |
|---|---|---|---|
| `simple_bfts` | `false` | `simple_bfts` | default; silent |
| `simple_bfts` | `true` | `simple_bfts` | warning: interlock set but mode is simple_bfts |
| `ari_rqgm` | `false` | `simple_bfts` | warning: mode requested but interlock off |
| `ari_rqgm` | `true` | `ari_rqgm` | RQGM runtime constructed |

```python
# planned: ari-core/ari/rqgm/mode.py (new internal package, NOT ari.public.*)
class EffectiveMode(str, Enum):
    SIMPLE_BFTS = "simple_bfts"
    ARI_RQGM = "ari_rqgm"

def resolve_effective_mode(cfg: "ARIConfig") -> EffectiveMode:
    """Pure function of cfg; no I/O, no env reads (env is applied to cfg upstream)."""
    if cfg.ari.mode == "ari_rqgm" and cfg.rqgm.enabled:
        return EffectiveMode.ARI_RQGM
    if cfg.ari.mode == "ari_rqgm" or cfg.rqgm.enabled:
        log.warning("ari.mode=%s but rqgm.enabled=%s; falling back to simple_bfts",
                    cfg.ari.mode, cfg.rqgm.enabled)
    return EffectiveMode.SIMPLE_BFTS
```

Env overrides (new `apply_rqgm_env_overrides(cfg)` in `ari-core/ari/config/__init__.py`, called
from `run` and `resume` immediately after `apply_evaluator_env_overrides`):

- `ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} → `cfg.ari.mode` (validate-before-assign; invalid
  value → warning + ignored, matching `ARI_FRONTIER_SCORE` handling).
- `ARI_RQGM_ENABLED` ∈ {`0`,`1`,`true`,`false`} → `cfg.rqgm.enabled`.

Both env names are reserved now so the GUI launcher (env-var based) works day-one without any
viz change. `export_resolved_config_to_skill_env` additionally `setdefault`s `ARI_MODE` to the
*effective* mode string so skill subprocesses can key off it later (no skill reads it in v1).

### 5.3 Component matrix per mode

`simple_bfts` (default) — enabled: BFTS frontier search, proposal generation (current
`generate_ideas`/`idea.json` path), node execution, fixed verifier behaviors (results.json
merge, sterile gate, `validate_metrics`), metric recomputer, normal scoring, existing
schema/hash checks (node_report schema, prompt hash provenance). Disabled — none of the
following are constructed, imported at module level, or reachable: GovernanceOrchestrator,
adversary/defender/judge loop, prompt evolution, prompt retirement, selective erasure,
RegistryTransitionEngine active-set updates, FrontierRepairEngine, meta-agent evolution,
EpochState machinery, ConstitutionalKernel.

`ari_rqgm` — additionally constructed (by later tasks; construction *sites* fixed here):
EpochState, PromptRegistry (RQGM extension), ComponentRegistry, ProposalRecord store,
ProposalRouter, GovernanceOrchestrator, AdversarialReplayPool, prompt evolution, clean-room
regeneration, RegistryTransitionEngine, FrontierRepairEngine, SelectiveErasure,
ConstitutionalKernel.

| Component group | Construction site (when `ari_rqgm`) | Owning task |
|---|---|---|
| `RQGMRuntime` facade + `GovernedSearchStrategy` wrapper | `ari-core/ari/core.py:build_runtime` (wrapping the `BFTS(...)` line) | 01 (no-op skeleton) |
| EpochState / registries | inside `RQGMRuntime.__init__` | 02 |
| ProposalRouter (+ optional VirSciAdapter) | inside `RQGMRuntime`, VirSci branch gated by `proposal_router.generators.virsci.enabled` | 03 |
| ConstitutionalKernel | inside `RQGMRuntime` (fixed layer, always constructed when RQGM is active) | 04 |
| GovernanceOrchestrator / TransitionEngine / FrontierRepair | inside `RQGMRuntime`, invoked from the epoch hook in `_run_loop` | 05/09/10 |

Rule: **all RQGM construction funnels through `RQGMRuntime`**, and `RQGMRuntime` is imported
lazily inside the `if rqgm_active:` branch of `build_runtime` — under `simple_bfts` no RQGM
module is even imported (import-cost and fault-isolation guarantee, mirroring the `hpc_enabled`
skill-drop precedent).

### 5.4 Wiring in `build_runtime` and detection in `_run_loop`

Resolves Task 00 open question "wrap vs extend the 6-tuple": **wrap**.

```python
# planned change inside ari-core/ari/core.py:build_runtime
bfts: SearchStrategy = BFTS(cfg.bfts, bfts_llm)
mode = resolve_effective_mode(cfg)          # ari.rqgm.mode — pure
if mode is EffectiveMode.ARI_RQGM:
    from ari.rqgm.runtime import RQGMRuntime          # lazy import
    rqgm = RQGMRuntime(cfg, checkpoint_dir=checkpoint_dir)
    bfts = rqgm.wrap_search_strategy(bfts)            # satisfies SearchStrategy
    # controller is discoverable without changing the return tuple:
    #   getattr(bfts, "rqgm", None)  ->  RQGMRuntime | None
return llm, memory, mcp, bfts, agent, metric_spec     # shape unchanged
```

- `GovernedSearchStrategy` implements all seven `SearchStrategy` methods by delegation (pure
  pass-through in Task 01; later tasks add policy). It carries a public `rqgm` attribute.
- `_run_loop` gains one line near its existing setup block:
  `_rqgm = getattr(bfts, "rqgm", None)` — read once at loop start, like `_expand_enabled`.
  All future epoch hooks are gated on `_rqgm is not None`. Under `simple_bfts`, `_run_loop`
  executes an identical instruction stream to today (a single failed `getattr` aside).
- `NodeExecutor` (`AgentLoop`) is *not* wrapped in v1; the seam is reserved (`rqgm.wrap_node_executor`
  exists as identity) for Tasks 05/06.
- Detection is duck-typed (attribute presence), never `isinstance` of a concrete class —
  consistent with the contract-snapshot robustness convention.

### 5.5 Mode-switch timing policy

Allowed:

1. **Run start** — the only entry into `ari_rqgm` from nothing. Effective mode is resolved once
   in `build_runtime` and persisted to `{ckpt}/rqgm_state.json` before the first node runs.
2. **Epoch boundary** (only meaningful when the run is in `ari_rqgm`) — inside the
   epoch-boundary transaction (Task 02/09), the run may **downgrade** `ari_rqgm → simple_bfts`
   (governance off from the next epoch; cost/emergency fallback). The downgrade is itself an
   audited transition and passes ConstitutionalKernel validation (Task 04).

Not possible / forbidden:

- `simple_bfts → ari_rqgm` mid-run: `simple_bfts` has no epoch boundaries, so there is no legal
  switch point. Upgrading requires a new run (or a child run launched with `ARI_MODE=ari_rqgm`,
  which is a run start for the child). Stated explicitly to satisfy global invariant 20 without
  inventing pseudo-boundaries in the legacy loop.
- Mid-epoch, mid governance transaction, mid registry transition, mid frontier rebuild:
  forbidden in principle. Enforcement contract: the effective mode is frozen into `EpochState`
  at epoch start (Task 02); `ConstitutionalKernel.validate_epoch_invariance` (Task 04) treats a
  mode value change that is not part of an epoch-boundary transaction as a blocking violation.
  Task 01 only defines the persisted fields these checks read (§6).

Resume semantics (resolves Task 00 open question): `ari resume` reads `rqgm_state.json`
checkpoint-first. The **persisted mode wins** over package config and env; a disagreement
produces a warning, never a mid-run mode flip. Rationale: resume must be deterministic and a
run's trajectory must not silently change semantics halfway. A persisted-mode override
mechanism, if ever needed, would be a deliberate future CLI surface (out of scope for v1; it
would arrive as its own auxiliary task plan registered in INDEX.md).

Read-precedence rule for all RQGM mode readers (normative for Tasks 02–13):
`{ckpt}/rqgm_state.json` (persisted, resume) → typed `cfg` (which itself already reflects
`--config`/checkpoint/package YAML + profile + env in the standard precedence) → defaults.
No RQGM code re-reads the package workflow.yaml directly.

### 5.6 VirSci independence

`proposal_router.generators.virsci.enabled` is orthogonal to `ari.mode`. All four combinations
are valid; initial implementation prioritizes `simple_bfts + VirSci off` and
`ari_rqgm + VirSci off`:

| | VirSci off (default) | VirSci on |
|---|---|---|
| `simple_bfts` | current ARI, idea-skill tier-2/3 degradation | current ARI with VirSci ideation (today's behavior when available) |
| `ari_rqgm` | ProposalRouter runs Cheap/Mutation/AttackDriven/PriorArtDifferentiation generators only | ProposalRouter additionally constructs VirSciAdapter (event-triggered, budgeted; Task 03/12) |

Independence is enforced by construction: the mode-resolution code (`ari/rqgm/mode.py`) never
reads `proposal_router.*`, and the VirSci gate never reads `ari.mode`. With
`virsci.enabled=false`, in either mode: VirSciAdapter is never initialized, no VirSci
runtime/vendored path is required, no VirSci prompts are registered, no snapshot corpus is
built, and tests pass on environments without VirSci installed (Task 03 owns the mechanism —
including phase-gating the idea skill the way `_apply_web_phase_for_bfts` gates the web skill —
this task owns the guarantee statement and the config key location).

### 5.7 Constitution file distribution (decision)

The bundled constitution follows the workflow.yaml pattern: default at
`ari-core/config/constitution.yaml` (added by Task 04), copied into `{checkpoint_dir}/` at
launch **only when effective mode is `ari_rqgm`**, guarded by the same don't-clobber convention
as `ari-core/ari/cli/run.py` (~lines 396–408), and read checkpoint-first thereafter.
**Copy-once**: the constitutional layer is non-evolving (global invariant 17), so mid-run
mutation of `constitution.yaml` is forbidden — no versioned-write protocol is needed. Under
`simple_bfts`, no constitution file is copied, and its absence is normal.

## 6. Data structures / schema changes

### 6.1 New Pydantic models (`ari-core/ari/config/__init__.py`)

```python
class AriModeConfig(BaseModel):
    """Top-level `ari:` block."""
    mode: Literal["simple_bfts", "ari_rqgm"] = "simple_bfts"

class RQGMConfig(BaseModel):
    """Top-level `rqgm:` block. Skeleton; Tasks 02/12 add typed subsections
    (epoch, governance, shadow, replay, prompt_evolution)."""
    model_config = {"extra": "allow"}   # forward-compat for later-task subsections
    enabled: bool = False

class ARIConfig(BaseModel):
    ...existing fields...
    ari: AriModeConfig = Field(default_factory=AriModeConfig)
    rqgm: RQGMConfig = Field(default_factory=RQGMConfig)
```

`proposal_router: ProposalRouterConfig` is added by Task 03; this plan pins only its YAML path
(`proposal_router.generators.virsci.enabled`, default `false`).

Notes: both fields default-constructed, so a workflow.yaml without the blocks parses to today's
behavior; `load_config`'s `model_fields` filter picks them up with no loader change; `extra:
allow` on `RQGMConfig` means unknown subsections warn-free parse today and become typed later.

### 6.2 `{ckpt}/rqgm_state.json` (new checkpoint-root snapshot file)

Written by a new store method in `ari-core/ari/checkpoint.py` (plus module shim), byte-fixed
formatting (`indent=2, ensure_ascii=False`), rewrite-whole-file:

```json
{
  "schema_version": 1,
  "mode": "ari_rqgm",
  "rqgm_enabled": true,
  "mode_source": "config",           // "config" | "env" | "resume"
  "created_at": "<iso8601, metadata only, never hashed>",
  "switch_journal": [
    {"event": "run_start", "mode": "ari_rqgm", "epoch_id": null},
    {"event": "epoch_boundary_downgrade", "mode": "simple_bfts", "epoch_id": "epoch_004",
     "transition_id": "transition_004_to_005"}
  ]
}
```

- Written at run start **in both modes**? No — decision: written **only when effective mode is
  `ari_rqgm`** (or when a downgrade happened, in which case it already exists). Absence of
  `rqgm_state.json` == pure `simple_bfts` run == current-ARI trajectory, mirroring the
  `bfts_web_provenance.json` absence-is-default P5 convention. This keeps default checkpoints
  byte-identical to today's.
- Task 02 extends this file (or adds a sibling `epoch_state.json`; Task 02 decides) — the
  `schema_version` field and additive-only policy make either path safe.
- Registration requirements: filename added to `PathManager.META_FILES`
  (`ari-core/ari/paths.py`) and to `_INTERNAL_JSON_NAMES` in
  `ari-core/ari/orchestrator/node_report/builder.py`; a test mirrors
  `test_new_filenames_are_meta_files`.

### 6.3 Reserved environment variables

`ARI_MODE`, `ARI_RQGM_ENABLED` (semantics in §5.2). Documented in `docs/reference/` only at
implementation time (documenting them SemVer-freezes them; the names are fixed by this plan).

## 7. API / class changes

All new code lives in a new internal package `ari-core/ari/rqgm/` (not exported via
`ari.public.*`; no public-API contract snapshot churn):

| Symbol | Location (planned) | Contract |
|---|---|---|
| `EffectiveMode` (Enum) | `ari/rqgm/mode.py` | `SIMPLE_BFTS`, `ARI_RQGM`. |
| `resolve_effective_mode(cfg) -> EffectiveMode` | `ari/rqgm/mode.py` | Pure; table in §5.2; never raises. |
| `RQGMRuntime` | `ari/rqgm/runtime.py` | Facade; Task-01 version constructs nothing but itself and the state writer; exposes `wrap_search_strategy(bfts)`, `wrap_node_executor(agent)` (identity in v1), `persist_mode(checkpoint_dir)`, `mode` property. Later tasks add members (kernel, orchestrator, engines). |
| `GovernedSearchStrategy` | `ari/rqgm/runtime.py` | Implements all 7 `SearchStrategy` methods by delegation; public `rqgm` attribute; `@runtime_checkable` Protocol conformance asserted in tests. |
| `read_rqgm_state(ckpt) / write_rqgm_state(ckpt, state)` | `ari/rqgm/state.py` + store method in `ari/checkpoint.py` | Absence-tolerant read (None when missing); best-effort write (never raises into the run). |
| `AriModeConfig`, `RQGMConfig` | `ari/config/__init__.py` | §6.1. |
| `apply_rqgm_env_overrides(cfg) -> None` | `ari/config/__init__.py` | §5.2; validate-before-assign; called from `run.py:run` and `run.py:resume`. |

Changed (existing) code, all additive:

- `ari-core/ari/core.py:build_runtime` — the `if rqgm_active:` branch (§5.4). Return shape,
  parameter list, and all `simple_bfts` code paths unchanged.
- `ari-core/ari/cli/run.py` — call `apply_rqgm_env_overrides` in `run` and `resume`;
  in `run`, after checkpoint dir creation and only when mode is `ari_rqgm`: persist
  `rqgm_state.json` and copy `constitution.yaml` (don't-clobber guard). In `resume`:
  read `rqgm_state.json` first and force `cfg.ari.mode`/`cfg.rqgm.enabled` to the persisted
  values (warning on disagreement).
- `ari-core/ari/cli/bfts_loop.py:_run_loop` — one `getattr(bfts, "rqgm", None)` at setup.
  No other change in this task.
- `ari-core/ari/paths.py` — `META_FILES` += `{"rqgm_state.json", "constitution.yaml"}`.
- No CLI command/flag changes; no `ari.public.*` changes; no MCP tool changes ⇒ zero contract
  golden regeneration for v1 (deliberate budget decision).

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **Default is identity.** A workflow.yaml without `ari:`/`rqgm:` blocks — i.e. every existing
   config — resolves to `simple_bfts`, constructs no RQGM object, imports no `ari.rqgm` module,
   writes no new file. Checkpoint contents for a default run are byte-identical to pre-RQGM ARI
   (no `rqgm_state.json`, no `constitution.yaml`).
2. **`rqgm.enabled=false` compatibility.** Whatever any later task adds under `rqgm:`, the
   single interlock `enabled: false` (or `ari.mode: simple_bfts`) guarantees the entire RQGM
   subtree is inert. This is structural (the lazy-import branch in `build_runtime`), not a
   scatter of per-feature flags.
3. **Everything in Task 00's must-not-break register holds under `simple_bfts`**
   (00_current_ari_investigation.md §5.8, B-1…B-19) — checkpoint
   triple names/key order, `Node.to_dict()` keys, reserved metrics keys, one-child-per-expand,
   no-retry, retire rules A/B, sterile gate, deterministic fallbacks, fail-open hooks,
   `ari --help` byte order, META_FILES hygiene, memory ancestor-scoping, P2/P5. RQGM changes to
   `simple_bfts` paths are limited to: two config fields with defaults, one env-override call,
   one `getattr`.
4. **`ari_rqgm` is additive and fail-open at the loop level.** Task-01 wrapper methods are pure
   delegation; when later tasks add governance behavior, hook failures degrade (log + continue)
   per the lineage-hook precedent. Any deliberate fail-closed check (constitutional blocking)
   is introduced explicitly by Task 04 with its own justification, never by this wiring.
5. **VirSci removable via config** in both modes (§5.6); `ari-skill-idea/vendor/virsci` is
   never edited.
6. **Old checkpoints / resume.** Checkpoints created before this feature have no
   `rqgm_state.json`; `resume` treats absence as `simple_bfts` (correct by construction).
   Downgraded runs resume in their persisted final mode.
7. **Config forward-compat.** Because `ARIConfig` filters unknown top-level keys today, a user
   who deploys an `rqgm:` block on an *older* ari-core silently gets current behavior — the
   safest possible failure direction. (The reverse — new ari-core, old config — is case 1.)

## 9. Tests

Unit (new `ari-core/tests/test_rqgm_mode.py`, listed in `ari-core/tests/README.md` for the
readme-sync gate):

- Config parsing: absent blocks → defaults (`simple_bfts`, `enabled=False`); full blocks parse;
  invalid `ari.mode` literal → Pydantic validation error.
- `resolve_effective_mode`: all four cells of the §5.2 table, including both warning paths.
- `apply_rqgm_env_overrides`: `ARI_MODE`/`ARI_RQGM_ENABLED` override YAML; invalid values
  ignored with warning; applied-after-profile ordering (mirroring existing env-override tests).
- `rqgm_state.json` round-trip: write → read; absence-tolerant read; META_FILES and
  `_INTERNAL_JSON_NAMES` registration asserted (pattern:
  `test_prompt_provenance.py::test_new_filenames_are_meta_files`).

Regression (simple_bfts unchanged):

- `build_runtime` with a default config returns an object for which
  `getattr(bfts, "rqgm", None) is None` and `type(bfts).__module__` is unchanged
  (duck-typed assertions, no isinstance-of-concrete-class).
- Default `ari run` smoke (mocked LLM, tmp checkpoint via
  `monkeypatch.setenv("ARI_CHECKPOINT_DIR", tmp_path)`): checkpoint root contains **no**
  `rqgm_state.json` / `constitution.yaml`; `sys.modules` contains no `ari.rqgm.*` entry.
- Full existing ari-core suite passes untouched (CI `refactor-guards.yml` provides this).
- Contract snapshots unchanged: `scripts/snapshot_contracts.py --surface cli --check` and
  `--surface public --check` stay green with no golden regeneration.

Smoke (ari_rqgm startup — the deletion-criteria "startup test"):

- `build_runtime` with `ari.mode=ari_rqgm, rqgm.enabled=true`: returned strategy satisfies
  `isinstance(bfts, SearchStrategy)` (runtime_checkable Protocol), delegates all 7 methods to
  the inner BFTS (call-through spies), exposes `.rqgm`.
- Short `_run_loop` run (stubbed agent/LLM) in `ari_rqgm` mode completes, writes
  `rqgm_state.json` with `mode_source="config"`, and produces the same node lifecycle as the
  `simple_bfts` control run (Task-01 wrapper is pure delegation).
- Both-mode smoke matrix additionally crossed with `virsci.enabled` ∈ {false} (true-cases land
  with Task 03): asserts no idea-skill VirSci path is touched when off.

Resume:

- Run started as `ari_rqgm`, resumed with conflicting env `ARI_MODE=simple_bfts` → persisted
  mode wins, warning logged. Run started as `simple_bfts` (no state file), resumed with
  `ARI_MODE=ari_rqgm` → stays `simple_bfts`, warning logged (no mid-run upgrade).

CI placement: all of the above are plain ari-core tests (run hard via `refactor-guards.yml`);
no new workflow is needed for this task. Any future RQGM-specific checker follows the
Stage-1-advisory-first policy.

## 10. Risks

- **R1 — Silent config typos.** A misspelled block (`rqmg:`) is silently dropped by the
  `model_fields` filter. Mitigation: `load_config` gains a warning for unknown top-level keys
  that are edit-distance-close to known ones — optional hardening; at minimum the docs state
  the exact key names and the smoke test covers the canonical spelling.
- **R2 — Attribute-presence detection is a convention, not a type.** `getattr(bfts, "rqgm")`
  could collide with a future unrelated attribute. Mitigation: name is reserved by this plan;
  Protocol-conformance test pins the wrapper; revisit with a typed accessor if Tasks 05+ need
  richer discovery.
- **R3 — `RQGMConfig` `extra: allow` hides subsection typos** until Tasks 02/12 type them.
  Accepted temporarily; each later task must convert its subsection to typed fields.
- **R4 — Resume pin surprises users** who expect env to win everywhere (it does at run start).
  Mitigation: loud warning + documented rule "a run's mode is immutable except at epoch
  boundaries, downgrade-only".
- **R5 — Downgrade-only boundary switching** may prove too restrictive (no mid-run upgrade).
  Accepted for v1; upgrading is served by child-run launches. Revisit only with evidence.
- **R6 — Profiles ignore RQGM keys.** `_apply_profile` merges only bfts/hpc keys; an
  `rqgm:` block in `ari-core/config/profiles/hpc.yaml` would be silently ignored. Out of scope for v1;
  documented limitation; extend `_apply_profile` only when a real profile needs it.
- **R7 — Score-comparability interactions** (axis freezing vs epoch re-weighting, invariant
  I-11) are *not* affected by this task (pure delegation), but the mode switch is where users
  will expect them to be documented. Designed in
  [14_governed_utility_evolution.md](14_governed_utility_evolution.md), not Task 10: the utility
  policy is frozen per **epoch** and rewritten at boundaries through the governed path (14 §5.10,
  which repeals I-11). Task 00's Q-40 (§5.9) and register item B-17 (§5.8) are answered there.
  The mode switch documents where the answer lives, not the answer.
- **R8 — Contract-snapshot creep.** Any later temptation to add `--mode` CLI flags re-opens the
  golden budget. Guard: this plan's decision (config+env only for v1) is recorded as normative.
- **R9 — `_run_loop` is a monolith and no one owns splitting it.** Every RQGM hook — the
  mode detection this plan adds (§5.4), the epoch tick (02), `audit_epoch` (05), the
  transition commit (09), `repair()` (10), the per-node budget gate (12) — attaches inside
  one function, `_run_loop` in `ari-core/ari/cli/bfts_loop.py`. Each hook is individually
  small and fail-open, and none of them is the problem; the accumulation is.
  > **OPEN — forwarded here by [05](05_governance_orchestrator.md) §10
  > ("any loop refactor is out of scope and tracked by Task 01's open questions"), which
  > is the only place the hand-off was recorded. It had not in fact landed in R1–R8, so
  > until this entry the refactor was owned by nobody.** No decision exists anywhere in
  > the tree about whether, when, or how `_run_loop` gets split, and this plan does not
  > invent one — splitting it is a change to the mock seam that `run`/`resume` rely on
  > (late-bound `ari.cli` lookups, §4) and to the read-once checkpoint-first idiom at the
  > loop head, so it is a real decision with real regression surface, not a tidy-up.
  > One fact worth carrying into that decision: the plan set sized this function at
  > ~925 lines; `_run_loop` is now ~1,630 lines (`bfts_loop.py` lines 464–2089), so the
  > fragility Task 05 flagged has roughly doubled since it was flagged. Task 01 owns the
  > question because mode wiring and the protocol seams (`SearchStrategy` /
  > `NodeExecutor`, §4) are what a split would have to preserve — re-home it or answer it
  > before this file is deleted.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Both configs defined** — `ari.mode` (`simple_bfts | ari_rqgm`, default `simple_bfts`) and
   `rqgm.enabled` (default `false`) are specified as typed `ARIConfig` fields with YAML shape,
   defaults, env overrides (`ARI_MODE`, `ARI_RQGM_ENABLED`), and precedence (§5.1, §5.2, §6.1),
   including the effective-mode resolution table for all four value combinations.
2. **simple_bfts preservation policy written** — the normative policy that `simple_bfts`
   preserves current ARI behavior (identity default, no RQGM imports/objects/files, Task 00
   must-not-break list honored, `rqgm.enabled=false` structural inertness) is written down
   (§5.3, §8) with the exact code deltas allowed on `simple_bfts` paths enumerated.
3. **ari_rqgm component set defined** — the components enabled by `ari_rqgm` (EpochState,
   PromptRegistry, ComponentRegistry, ProposalRecord, ProposalRouter, GovernanceOrchestrator,
   AdversarialReplayPool, prompt evolution, clean-room regeneration, RegistryTransitionEngine,
   FrontierRepairEngine, SelectiveErasure, ConstitutionalKernel) are listed with their
   construction sites and owning tasks (§5.3), all funneled through `RQGMRuntime` in
   `build_runtime`.
4. **Mode-switch timing defined** — run-start switching, epoch-boundary switching
   (downgrade-only, inside the boundary transaction), the mid-epoch / mid-governance /
   mid-transition / mid-rebuild prohibitions with their enforcement contract, and resume
   semantics (persisted mode wins) are specified (§5.5).
5. **VirSci independence stated** — `proposal_router.generators.virsci.enabled` toggles
   independently of `ari.mode`; the four-combination matrix is valid; the
   `virsci.enabled=false` guarantees are stated and delegated to Task 03 for mechanism (§5.6).
6. Downstream tasks (02, 03, 04, 09) can consume this plan's decisions without re-opening them:
   config home, read-precedence rule, wrapper seam, `rqgm_state.json` ownership, constitution
   distribution (§5.4, §5.7, §6.2).

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (all additionally required):

- The mode config (`ari.mode`, `rqgm.enabled`, typed models, env overrides) is implemented.
- Smoke tests exist for **both** modes (`simple_bfts` regression smoke and `ari_rqgm` startup
  smoke, per §9).
- `simple_bfts` is confirmed not to break existing behavior (full existing ari-core suite green
  plus the §9 identity assertions: no RQGM imports/files on default runs, contract snapshots
  unchanged).
- An `ari_rqgm` startup test exists (build_runtime wiring, Protocol conformance,
  `rqgm_state.json` written, short-loop smoke).
- The mode-switching policy (allowed timings, prohibitions, resume rule, downgrade-only rule)
  has been moved to permanent docs (execution mode guide under `docs/`).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] `ari.mode` / `rqgm.enabled` implemented as typed config with env overrides.
- [ ] Smoke tests pass in both `simple_bfts` and `ari_rqgm` modes.
- [ ] Default-config runs produce checkpoints with no RQGM files and no `ari.rqgm` imports.
- [ ] `ari_rqgm` startup test (wrapper + `rqgm_state.json` + short loop) exists and passes.
- [ ] Mode-switching policy published in the permanent execution mode guide.
- [ ] `rqgm_state.json` and `constitution.yaml` registered in `PathManager.META_FILES` (and
      `rqgm_state.json` in node_report `_INTERNAL_JSON_NAMES`).
- [ ] VirSci-independence statement carried into the permanent VirSci integration guide
      (or explicitly handed to Task 03's deletion flow).
