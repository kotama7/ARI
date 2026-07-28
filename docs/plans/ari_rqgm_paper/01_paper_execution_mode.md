# Task 01: Paper Execution Mode and Compatibility

> **Status**: planned · **Depends on**: 00 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI must gain a THIRD, opt-in execution path — **paper-archive co-evolution** — that brings the
RQGM epoch/governance loop to the PAPER-WRITING phase, exactly as `ari_rqgm` brought it to the
EXPLORATION phase. This task designs the *paper-phase mode switch itself* and nothing downstream
of it:

- the `paper.mode` / `rqgm.paper.enabled` configuration keys and where they are read;
- the guarantee that `linear` (the default) is byte-for-byte the current paper pipeline;
- the `PaperMode` enum and the deterministic `resolve_paper_mode` interlock table;
- environment overrides (`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`) and their precedence;
- the `PaperArchiveRuntime` construction site at the paper entry
  ([`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py) `paper`);
- the orthogonality of the paper mode and the exploration `ari.mode` (a 2×2 matrix);
- `paper_archive_state.json` provenance + resume semantics;
- mode-switch timing: the paper phase runs **once**, so there is no mid-phase switch point;
- the paper epoch boundary *inside* that single phase: one epoch = one archive round, sized by
  `rqgm.paper.epoch.rounds` (default `2`) over the INHERITED node-count trigger.

Every downstream paper task (02–07) hangs its config and activation off the switch designed here.
This is the direct paper-phase analog of the exploration-phase Task 01,
[../ari_rqgm/01_execution_modes_and_compatibility.md](../ari_rqgm/01_execution_modes_and_compatibility.md);
it mirrors that plan's structure, decisions, and invariant discipline. It resolves the Task-01
open questions handed down by [00_paper_pipeline_investigation.md](00_paper_pipeline_investigation.md)
(config home for `paper.mode`, `PaperArchiveRuntime` construction site, provenance-file ownership,
and re-invocation/resume semantics for `ari paper`).

## 2. Scope

- Typed config schema: a new top-level `paper.mode` (`PaperConfig`) and a new `rqgm.paper`
  subsection (`RQGMPaperConfig`) skeleton — the `enabled` interlock plus the placement (not the
  detailed schema) of `rqgm.paper.archive.*` (Task 02), `rqgm.paper.anchor.*` (Task 04), and
  `rqgm.paper.prompt_evolution.enabled` (Task 03/06 on-ramp).
- Environment-variable overrides (`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`) and their
  precedence, plus the paper-entry override call site (`_resolve_cfg` applies no env today).
- Deterministic effective-mode resolution (`resolve_paper_mode`) including the disagreement /
  interlock rules.
- Conditional construction of `PaperArchiveRuntime` at the paper entry in
  [`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py), *around* the existing
  linear `generate_paper_section` call — with the linear branch left byte-identical.
- Independence from the exploration `ari.mode` (the 2×2 matrix; all four combinations valid).
- Paper-mode persistence in `{ckpt}/paper_archive_state.json` and re-invocation/resume semantics.
- Mode-switch timing policy (paper phase runs once; no mid-phase switch) and the persisted-mode
  wins rule for a re-invoked `ari paper`.
- Paper epoch boundary definition (§5.7): one epoch = one archive round, the single sizing knob
  `rqgm.paper.epoch.rounds`, `max_expansions` as a per-epoch budget, and the `ensure_epoch` /
  `_run_epoch_boundary` wiring. The trigger KIND stays the inherited `rqgm.epoch.boundary`; the
  boundary's *contents* (prompt adoption) remain Task 03's.

## 3. Non-goals

- No implementation in this task plan (design only; implementation is a deletion-criteria item).
- No draft-archive search substrate — `PaperArchiveStrategy`, the draft `NodeExecutor`, best-belief
  selection, and `paper_draft_archive.jsonl` are Task 02
  ([02_paper_draft_archive_search.md](02_paper_draft_archive_search.md)). Task 01's
  `PaperArchiveRuntime` is a *no-op skeleton* that persists provenance and otherwise delegates to
  the linear pipeline.
- No governed roles or co-evolution mechanics — promoting `paper_writer` to an evolvable role and
  adding `paper_reviewer`, the constitutional amendment, and epoch-boundary prompt evolution are
  Task 03 ([03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md)).
- No anchor corpus / epoch-winner utility (Task 04
  [04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md)),
  no `paper_self_preference` adversary (Task 05), no cost model (Task 06), no claim-gate handoff
  or evaluation harness (Task 07).
- No governance of the `ari-skill-paper` subprocess — it stays the ungoverned draft executor; the
  governed prompts live in ari-core (Task 03). This plan pins only the mode switch.
- No new CLI command or flag in v1 (config + env activation only; the `ari paper` command signature
  in [`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py) is unchanged, so the
  CLI contract snapshot is untouched).
- No change to the exploration mode switch, the exploration `run_paper_candidate_escalation` hook,
  the claim-gate Layer-0, or the BFTS pipeline.

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| Paper entry (the construction site) | [`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py) — `paper` (line 61), `cfg = _resolve_cfg(config)` (line 118), `build_runtime(...)` (line 148), `generate_paper_section(...)` (line 190) | THE place where the paper mode is resolved and `PaperArchiveRuntime` is constructed. The linear `generate_paper_section` call is the exact line the archive dispatch wraps (the paper-phase analog of the `BFTS(...)` line in `build_runtime`). |
| Exploration escalation hook (independent) | [`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py) — `_rqgm_paper = getattr(_bfts_paper, "rqgm", None)` (line 163), `run_paper_candidate_escalation` (line 171) | The EXISTING exploration-phase RQGM hook, gated on the *exploration* `ari.mode`. It stays byte-identical and orthogonal: paper mode never touches it, and it never reads `paper.mode`. Confirms the 2×2 independence (§5.6). |
| Paper-entry cfg (no env applied) | [`ari-core/ari/cli/run.py`](../../../ari-core/ari/cli/run.py) — `_resolve_cfg` (line 74) | `_resolve_cfg` loads `--config`/package YAML but applies **no** env overrides. So `ARI_PAPER_MODE` needs an explicit `apply_paper_env_overrides(cfg)` call at the paper entry — it cannot free-ride on the `run`/`resume` override block. |
| Env-override precedent | [`ari-core/ari/config/__init__.py`](../../../ari-core/ari/config/__init__.py) — `apply_rqgm_env_overrides` (line 1396), `_effective_mode_str` (line 1432) | The validate-before-assign env-override pattern `apply_paper_env_overrides` copies verbatim (`ARI_MODE` → `cfg.ari.mode`; invalid value → warning + ignored). `_effective_mode_str` is the import-free mirror pattern for a `_effective_paper_mode_str`. |
| Exploration mode switch (the analog) | [`ari-core/ari/rqgm/mode.py`](../../../ari-core/ari/rqgm/mode.py) — `EffectiveMode` (line 30), `resolve_effective_mode` (line 37) | The pure, never-raises, warning-table resolver `resolve_paper_mode` clones. Same interlock discipline (both flags must agree; disagreement fails safe). |
| Exploration runtime facade (the analog) | [`ari-core/ari/rqgm/runtime.py`](../../../ari-core/ari/rqgm/runtime.py) — `RQGMRuntime` (line 104), `wrap_search_strategy` (line 1825), `persist_mode` (line 1855) | `PaperArchiveRuntime` mirrors this facade: lazy-imported only under `rqgm_archive`, holds cfg + checkpoint handle, exposes `persist_mode`, and (Task 01) constructs nothing but itself and the state writer. |
| Mode provenance + resume (the analog) | [`ari-core/ari/rqgm/state.py`](../../../ari-core/ari/rqgm/state.py) — `RQGM_STATE_FILENAME` (line 37), `build_run_start_state` (line 65), `persist_run_start` (line 88), `reconcile_resume_mode` (line 171) | The write-once, byte-fixed, absence-is-default provenance + persisted-mode-wins pattern `paper_archive_state.json` copies exactly (§5.5, §6.2). |
| Composition root (exploration wiring reference) | [`ari-core/ari/core.py`](../../../ari-core/ari/core.py) — `build_runtime` RQGM branch (lines 153–173), `generate_paper_section` (line 268) | The `if _ari_mode == "ari_rqgm" or _rqgm_enabled:` raw-flag guard + lazy import (lines 158–163) is the identity-default template the paper dispatch reuses. `generate_paper_section` (line 268) is the linear pipeline entry the archive dispatch must leave untouched under `linear`. |
| Linear paper pipeline | [`ari-core/ari/pipeline/driver.py`](../../../ari-core/ari/pipeline/driver.py) — `WorkflowDriver` (line 46), `run` (line 68), `loop_back_to` (line 499); `ari-core/ari/pipeline/{stages,stage_runner,verified_context,claim_gate}` | The YAML-ordered stage pipeline that MUST stay byte-identical under `linear`. The archive path re-uses its compile + claim-gate tail (Task 07); Task 01 only guarantees it is never entered differently under `linear`. |
| Best-node selection (single entry point) | [`ari-core/ari/pipeline/verified_context.py`](../../../ari-core/ari/pipeline/verified_context.py) — `select_best_node` (line 36), `_scientific_score` (line 20) | The one best exploration node whose lineage the paper is about — the single seed the archive expands from (Task 02). Task 01 records that the archive is seeded from this same selection, keeping the entry point singular. |
| Draft executor (the hands) | [`ari-skill-paper/src/server.py`](../../../ari-skill-paper/src/server.py) — `write_paper_iterative` (line 1092), `paper_refine` (line 2447), `review_compiled_paper` (line 2085), `compile_paper` (line 447) | The ungoverned subprocess that renders/compiles drafts. Task 01 only notes it is NEVER governed cross-process and NEVER imports rqgm; Task 02 wraps its tools as the draft `NodeExecutor`. |
| Config models home | [`ari-core/ari/config/__init__.py`](../../../ari-core/ari/config/__init__.py) — `AriModeConfig` (line 253), `RQGMConfig` (line 1039), `ARIConfig` (line 1125), `ari:`/`rqgm:`/`proposal_router:` fields (lines 1165–1181) | Where the typed `paper: PaperConfig` field and the `rqgm.paper: RQGMPaperConfig` subsection are added. `ARIConfig.model_config = {"extra": "allow"}` (line 1182) + the `load_config` `model_fields` filter means an untyped `paper:` block would be silently dropped — typed fields are the only clean way in (the §5.1 config-home decision, mirroring exploration Task 01). |
| Checkpoint store | [`ari-core/ari/checkpoint.py`](../../../ari-core/ari/checkpoint.py) — `save_rqgm_state_json` (line 124/370), `load_rqgm_state_json` (line 211/381) | The store-method + module-shim + byte-fixed (`indent=2, ensure_ascii=False`) writer pattern the new `save_paper_archive_state_json` / `load_paper_archive_state_json` follow. |
| Checkpoint META hygiene | [`ari-core/ari/paths.py`](../../../ari-core/ari/paths.py) — `PathManager.META_FILES` (line 404; `rqgm_state.json` at line 437) | `paper_archive_state.json` must be added to `META_FILES` or it is copied into every node work dir. |
| Node-report hygiene | [`ari-core/ari/orchestrator/node_report/builder.py`](../../../ari-core/ari/orchestrator/node_report/builder.py) — `_INTERNAL_JSON_NAMES` (line 327; `rqgm_state.json` at line 334) | `paper_archive_state.json` must be classified internal, not a publishable data output. |
| Numeric defaults home | [`ari-core/ari/configs/defaults.yaml`](../../../ari-core/ari/configs/defaults.yaml) — `rqgm:` block (line 15) | The `rqgm.paper.*` numeric defaults (width, refine_rounds, …) mirror the typed pydantic defaults here, the way the existing `rqgm.epoch`/`rqgm.governance` blocks do. Task 01 pins the shape; Tasks 02/04 fill the numbers. |
| Reused Task-12 knobs | [`ari-core/ari/configs/defaults.yaml`](../../../ari-core/ari/configs/defaults.yaml) — `full_governance_only_on_top_k: 3` (line 35), `rqgm.adversarial.max_adversary_calls_per_epoch`, `rqgm.prompt_evolution.max_total_candidates_per_epoch` | INHERITED verbatim by the paper archive (Task 06); Task 01 records they are **not** renamed under `rqgm.paper` (one schema home; §5.1). |

## 5. Proposed design

### 5.1 Configuration keys (authoritative shape)

Exactly the SPEC shape, as first-class typed fields:

```yaml
# workflow.yaml (all defaults shown; omitting the blocks entirely is equivalent to today)
paper:
  mode: linear                 # linear | rqgm_archive  (top-level `paper:` block)
rqgm:
  paper:
    enabled: false             # redundant safety interlock, mirrors rqgm.enabled
    archive:                   # skeleton here; full schema in Task 02
      width: 4                 # K seed drafts (depth 1) under the paper root
      refine_rounds: 2         # paper_refine child generations per candidate (= tree depth)
      max_expansions: 12       # PER-EPOCH budget cap -> BFTS max_total_nodes (§5.7)
      depth: 3                 # draft-tree depth -> BFTS max_depth (a genuine best-first tree)
    epoch:                     # §5.7; SIZING ONLY — the trigger kind stays rqgm.epoch.boundary
      rounds: 2                # archive rounds per paper phase; ONE round = ONE paper epoch
    anchor:                    # skeleton here; full schema in Task 04
      enabled: false
      corpus_path: ""          # APReS-equivalent accept/reject corpus
      sample_size: 8           # held-out agreement sample
    prompt_evolution:
      enabled: true            # false = best-of-N reviewed drafts, NO co-evolution (the on-ramp)
```

**Design decision — config home** (resolves the Task 00 open question): typed fields on
`ARIConfig`, not raw-YAML re-reads. `ARIConfig.model_config = {"extra": "allow"}` yet `load_config`
filters raw YAML to `ARIConfig.model_fields`, so an *untyped* top-level `paper:` block is silently
dropped today — the identical trap exploration Task 01 found for `ari:`/`rqgm:`. A typed
`paper: PaperConfig` field is picked up automatically from any workflow.yaml source (checkpoint
copy, `--config`, package) with no loader change. `rqgm.paper` is a typed subsection of the
existing `RQGMConfig`, whose `extra: allow` (line 1046) already lets it parse warn-free today and
become typed when this task lands.

**No-collision notes.** (1) There is no existing top-level `paper:` config block and no `PaperConfig`
model — the field is new. (2) The `paper:` *config* block is distinct from the `ari paper` *CLI
command* ([`projects.py`](../../../ari-core/ari/cli/projects.py) line 61); different namespaces, no
clash. (3) `rqgm.paper.prompt_evolution.enabled` is nested under `rqgm.paper` and is DISTINCT from
the exploration `rqgm.prompt_evolution.enabled` — parallel names, separate homes, no override.

**Reused Task-12 knobs — do NOT rename.** The paper archive inherits the exploration governance
budget verbatim (Task 06). `rqgm.governance.full_governance_only_on_top_k` (default `3`,
[`defaults.yaml`](../../../ari-core/ari/configs/defaults.yaml) line 35),
`rqgm.adversarial.max_attacks_per_node`, `rqgm.adversarial.max_adversary_calls_per_epoch`, and
`rqgm.prompt_evolution.max_total_candidates_per_epoch` keep their one schema home under `rqgm.*` —
`rqgm.paper` never shadows them. `rqgm.paper.epoch.rounds` obeys the same policy from the other
direction: it *sizes* the inherited `rqgm.epoch.boundary` trigger for the paper phase, it does not
fork a second trigger kind (§5.7).

**Archive topology defaults — `depth: 3`, and `max_expansions` is per-epoch.** The draft archive is a
genuine best-first TREE over draft space (root → K seed drafts → refined/variant children); Task 02
§5.1 owns the topology, this section owns only the knob homes and their defaults. `depth` maps to
BFTS `max_depth` and `max_expansions` to `max_total_nodes`, and `should_prune`
([`bfts.py`](../../../ari-core/ari/orchestrator/bfts.py) lines 501–503) caps **both independently** —
so the total-node cap already bounds cost at ANY depth and the tree costs `O(max_expansions)`, never
`b^d`. Exploration already runs a real `max_depth=5` tree under the same `SearchStrategy` protocol
([`config/__init__.py`](../../../ari-core/ari/config/__init__.py) line 1559), so depth is inherited
substrate, not new risk. Normative: cost is bounded by the budget caps (`max_expansions`, top-K,
per-epoch caps), **never** by degenerating the topology.

### 5.2 Effective-mode resolution (deterministic, pure)

`paper.mode` is the master switch; `rqgm.paper.enabled` is a redundant safety interlock. Both must
agree for the paper archive to activate. Disagreement fails safe toward the current linear pipeline:

| `paper.mode` | `rqgm.paper.enabled` | Effective paper mode | Action |
|---|---|---|---|
| `linear` | `false` | `linear` | default; silent |
| `linear` | `true` | `linear` | warning: interlock set but mode is linear |
| `rqgm_archive` | `false` | `linear` | warning: mode requested but interlock off |
| `rqgm_archive` | `true` | `rqgm_archive` | `PaperArchiveRuntime` constructed |

```python
# planned: ari-core/ari/rqgm/paper_mode.py (new internal module, NOT ari.public.*)
from __future__ import annotations
import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ari.config import ARIConfig

log = logging.getLogger(__name__)


class PaperMode(str, Enum):
    LINEAR = "linear"
    RQGM_ARCHIVE = "rqgm_archive"


def resolve_paper_mode(cfg: "ARIConfig") -> PaperMode:
    """Pure function of cfg; no I/O, no env reads (env is applied to cfg
    upstream by apply_paper_env_overrides); never raises. Reads ONLY
    paper.mode / rqgm.paper.enabled — orthogonal to ari.mode (§5.6).
    getattr defaults keep pre-feature cfg objects resolving to linear."""
    mode = getattr(getattr(cfg, "paper", None), "mode", "linear")
    enabled = bool(
        getattr(getattr(getattr(cfg, "rqgm", None), "paper", None), "enabled", False)
    )
    if mode == "rqgm_archive" and enabled:
        return PaperMode.RQGM_ARCHIVE
    if mode == "rqgm_archive" or enabled:
        log.warning(
            "paper.mode=%s but rqgm.paper.enabled=%s; falling back to linear",
            mode, enabled,
        )
    return PaperMode.LINEAR
```

Env overrides (new `apply_paper_env_overrides(cfg)` in
[`ari-core/ari/config/__init__.py`](../../../ari-core/ari/config/__init__.py), cloning
`apply_rqgm_env_overrides` at line 1396):

- `ARI_PAPER_MODE` ∈ {`linear`, `rqgm_archive`} → `cfg.paper.mode` (validate-before-assign;
  invalid value → warning + ignored, matching the `ARI_MODE` handling at lines 1408–1417).
- `ARI_RQGM_PAPER_ENABLED` ∈ {`0`,`1`,`true`,`false`} → `cfg.rqgm.paper.enabled`.

An import-free `_effective_paper_mode_str(cfg)` (mirroring `_effective_mode_str`, line 1432)
returns `"rqgm_archive"` only when both flags agree, so default runs never import `ari.rqgm`.

### 5.3 Where the switch is applied and where the runtime is constructed

`_resolve_cfg` applies no env overrides, so the paper entry owns the override + dispatch. The
construction site is the `paper` command in
[`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py), immediately after the
existing exploration-escalation block (lines 163–175) and *around* the `generate_paper_section`
call (line 190):

```python
# planned change inside ari-core/ari/cli/projects.py:paper, replacing the
# unconditional generate_paper_section(...) tail (currently line 190)
from ari.config import apply_paper_env_overrides   # new; mirrors apply_rqgm_env_overrides
apply_paper_env_overrides(cfg)                     # ARI_PAPER_MODE / ARI_RQGM_PAPER_ENABLED

# (the exploration `_rqgm_paper` escalation block above is UNCHANGED and independent)

_paper_mode_str = _effective_paper_mode_str(cfg)   # import-free; "linear" | "rqgm_archive"
_paper_rt = None
if _paper_mode_str == "rqgm_archive":
    from ari.rqgm.paper_runtime import PaperArchiveRuntime      # lazy: rqgm_archive only
    _paper_rt = PaperArchiveRuntime(cfg, checkpoint_dir=checkpoint_dir, mcp=mcp_paper)
    _paper_rt.persist_mode(checkpoint_dir, mode_source=_paper_mode_source)

with pid_context(checkpoint_dir):
    if _paper_rt is not None:
        # Task 02–07 own the archive loop, best-belief selection, and the
        # compile+claim-gate handoff. Task-01 skeleton: run_archive() persists
        # paper_archive_state.json and then delegates to the SAME linear
        # generate_paper_section (pure-delegation parity — the archive body
        # is added by later tasks).
        _paper_rt.run_archive(
            all_nodes, experiment_data, checkpoint_dir, mcp_paper, _cfg_str,
            linear_fallback=generate_paper_section,
        )
    else:
        generate_paper_section(all_nodes, experiment_data, checkpoint_dir, mcp_paper, _cfg_str)
```

- Under `linear`, the branch is a single failed `_effective_paper_mode_str` string compare followed
  by the unchanged `generate_paper_section` call — no `ari.rqgm` module is imported on the paper
  path, no `PaperArchiveRuntime` is built, no new file is written (identity default).
- `PaperArchiveRuntime` is imported **lazily** inside the `if … == "rqgm_archive":` branch, mirroring
  the `RQGMRuntime` lazy import in `build_runtime` (core.py line 163) — import-cost and
  fault-isolation guarantee.
- **All paper-archive construction funnels through `PaperArchiveRuntime`** (§7). The Task-01 version
  constructs nothing but itself and the state writer; `run_archive` is pure delegation to the linear
  pipeline. Later tasks add `PaperArchiveStrategy` + draft `NodeExecutor` (Task 02), the governed
  roles (Task 03), and the epoch loop inside this facade — never scattered at the call site.
- `mcp_paper` (the `build_runtime` MCP client, projects.py line 149) is threaded into the runtime so
  the draft executor (Task 02) can drive `ari-skill-paper` tools.

### 5.4 `PaperArchiveRuntime` component set (construction sites fixed here)

`rqgm_archive` — additionally constructed (by later tasks; construction *sites* fixed now):
`PaperArchiveStrategy` (best-first draft tree, Task 02), the draft `NodeExecutor` wrapping
`ari-skill-paper` (Task 02), the governed `paper_writer` / `paper_reviewer` roles +
`paper_self_preference` adversary (Tasks 03/05), the anchor-utility scorer (Task 04), and the
INHERITED `GovernanceOrchestrator` (the impeachment chain: reliability → EvidenceClerk bundles →
Auditor motions → adjudication → replay admission) together with the `GovernanceBudgetManager` /
kernel / epoch / erasure / replay machinery (topology-agnostic, reused as-is per
[00_paper_pipeline_investigation.md](00_paper_pipeline_investigation.md) reuse map). The
orchestrator is named here because nothing else constructs it on the paper path: without this row
Task 03's boundary Adopt step cannot run (`resolve_transition` requires a `governance_report`,
[`transition_engine.py`](../../../ari-core/ari/rqgm/transition_engine.py) line 415) and Task 05's
`pool.admit` never fires (it lives inside `run_audit` step 7).

| Component group | Construction site (when `rqgm_archive`) | Owning task |
|---|---|---|
| `PaperArchiveRuntime` facade + `run_archive` dispatch | `ari-core/ari/cli/projects.py:paper` (wrapping `generate_paper_section`) | 01 (no-op skeleton) |
| `PaperArchiveStrategy` (best-first draft tree; `max_depth` = `rqgm.paper.archive.depth`, default 3) + draft `NodeExecutor` | inside `PaperArchiveRuntime.run_archive` | 02 |
| Governed `paper_writer` / `paper_reviewer` roles + co-evolution | inside `PaperArchiveRuntime` (registry/kernel reused from `ari.rqgm`) | 03 |
| `GovernanceOrchestrator` (INHERITED verbatim) | inside `PaperArchiveRuntime` (reuses `ari.rqgm.governance`; ctor mirrors [`runtime.py`](../../../ari-core/ari/rqgm/runtime.py) lines 463–477 — `GovernanceOrchestrator(cfg.rqgm, kernel=…, llm=…, audit_writer=ImmutableAuditLog(ckpt), governance_cache=…)`; lazy, `None` when the kernel is unavailable) | 03 |
| Anchor-utility scorer + epoch-winner policy | inside `PaperArchiveRuntime` boundary step | 04 |
| `paper_self_preference` adversary + replay | inside `PaperArchiveRuntime` (reuses `ari.rqgm.adversarial`) | 05 |
| `GovernanceBudgetManager` (INHERITED verbatim) | inside `PaperArchiveRuntime` (reuses `ari.rqgm.budget`) | 06 |
| Best-draft → compile + claim-gate handoff | end of `run_archive` (calls the EXISTING pipeline tail) | 07 |

Rule: `PaperArchiveRuntime` is imported lazily inside the `rqgm_archive` branch of the paper entry —
under `linear` no `ari.rqgm.paper_runtime` (nor any `ari.rqgm`) module is imported on the paper path.

### 5.5 Mode-switch timing and provenance

**The paper phase runs once.** Unlike the BFTS `_run_loop`, there is no long-lived paper loop with
epoch boundaries at the *process* level — `ari paper` is a single invocation that renders a paper
from a frozen checkpoint. So the paper-mode switch has exactly one legal point:

1. **Paper-phase start** — the effective paper mode is resolved once at the paper entry (§5.3) and
   persisted to `{ckpt}/paper_archive_state.json` before the first draft is produced. There is no
   mid-phase switch; the resolved mode is frozen for the whole paper phase.

Forbidden / impossible:

- **Mid-phase `linear ↔ rqgm_archive`**: the paper phase is a single transaction with no internal
  switch point. A different paper mode requires a fresh `ari paper` invocation (a paper-phase
  start for the new invocation). Stated explicitly to satisfy the within-phase-freeze invariant.
- Note that the paper archive's *internal* epochs — **one epoch per archive round**, defined in
  §5.7 — are a wholly separate concern from this process-level mode switch. A paper epoch boundary
  rewrites the active governed prompts (Task 03) and the utility policy (parent-set task 14); it
  never changes `paper.mode`, which is frozen for the whole paper phase by the rule above.

**Re-invocation / resume semantics** (resolves the Task 00 open question): re-running `ari paper` on
a checkpoint that already carries `paper_archive_state.json` reads it **checkpoint-first**; the
**persisted paper mode wins** over config and env, with a warning on disagreement — never a silent
mode flip on re-invocation. Rationale: the draft archive persists across invocations (drafts are
archive nodes in `paper_draft_archive.jsonl`, not overwrites of `full_paper.tex` — the Q-49
per-epoch-versioning resolution the parent set left open, resolved here for the paper phase and in
Task 04). Absence of `paper_archive_state.json` is the default ONLY for resume reconciliation — it does not
force a fresh run to `linear`. A first invocation has no state file yet, so its effective mode is
resolved from config/env (which may request `rqgm_archive`); the run then STARTS the archive and
persists `paper_archive_state.json`. `reconcile_paper_resume_mode(cfg, checkpoint_dir)` (the paper
analog of `reconcile_resume_mode`, state.py line 171) is therefore a no-op when no state file
exists, and only on a genuine re-invocation (state file present) does it force `cfg.paper.mode` /
`cfg.rqgm.paper.enabled` to the persisted values (persisted-mode-wins). This is deliberate: the
opposite reading — "no state ⇒ stay linear" — would make the archive permanently inert, since every
first run has no state file. (Correction recorded 2026-07-16; supersedes the earlier §9 sub-assertion
"a no-state checkpoint requesting rqgm_archive stays linear", which was self-defeating.)

Read-precedence rule for all paper-mode readers (normative for Tasks 02–07):
`{ckpt}/paper_archive_state.json` (persisted) → typed `cfg` (which already reflects
`--config`/checkpoint/package YAML + env) → defaults. No paper-mode code re-reads the package
workflow.yaml directly.

### 5.6 Independence from the exploration `ari.mode` (the 2×2 matrix)

The paper mode and the exploration mode are orthogonal. All four combinations are valid; the initial
implementation prioritizes `linear` paper output in both exploration modes:

| | paper `linear` (default) | paper `rqgm_archive` |
|---|---|---|
| exploration `simple_bfts` | today's ARI end-to-end | archive paper co-evolution over a `simple_bfts` exploration result; NO exploration governance, NO `run_paper_candidate_escalation` (`getattr(bfts, "rqgm", None) is None`) |
| exploration `ari_rqgm` | today's paper pipeline + the EXISTING `run_paper_candidate_escalation` (projects.py line 171) | both: exploration governance + paper-candidate escalation AND archive paper co-evolution |

Independence is enforced by construction: `resolve_paper_mode` (paper_mode.py) never reads
`ari.mode`/`rqgm.enabled`, and `resolve_effective_mode` (mode.py line 37) never reads `paper.*`. The
exploration escalation hook keys strictly on `getattr(_bfts_paper, "rqgm", None)` (projects.py line
163), which is the *exploration* runtime attached by `build_runtime` — it is `None` under
exploration `simple_bfts` regardless of `paper.mode`, and non-`None` under exploration `ari_rqgm`
regardless of `paper.mode`. With `rqgm.paper.enabled=false` in either exploration mode:
`PaperArchiveRuntime` is never constructed, no `ari.rqgm.paper_runtime` is imported on the paper
path, and `paper_archive_state.json` is never written.

### 5.7 Paper epoch boundaries (the archive's own round boundary)

**A paper epoch is ONE ARCHIVE ROUND.** `PaperArchiveRuntime.run_archive` builds the full draft tree
(width `K`, up to `rqgm.paper.archive.depth`) under FROZEN active `paper_writer` / `paper_reviewer`
hashes and a frozen utility policy, then closes the epoch **exactly once at round end** by running
the Task 03 §5.9 boundary sequence; the next round rebuilds drafts under the ADOPTED prompts. This
gives the "archive's own round boundary" of
[00_paper_pipeline_investigation.md](00_paper_pipeline_investigation.md) §5.6 (lines 464–465) a real
referent: the boundary is the archive's round edge, not the exploration loop's.

**Decision — reuse the inherited trigger; add exactly ONE sizing knob.** The trigger KIND stays the
inherited `rqgm.epoch.boundary: "node_count"`
([`config/__init__.py`](../../../ari-core/ari/config/__init__.py) `RQGMEpochConfig` lines 266–286),
ticked once per archive round (the tick source is the round index — see the landed deviation in
**Wiring** below). `rqgm.paper.epoch.rounds` (default `2`; §5.1, §6.1) is
**sizing only** — the paper-phase mirror of how `rqgm.epoch.nodes_per_epoch` sizes that same trigger
for exploration. Forking a paper-local trigger kind (`expansions_per_epoch` / `max_epochs`) is
REJECTED: it would duplicate an existing schema and break §5.1's one-schema-home policy — the same
policy under which the Task-12 budget knobs are inherited unrenamed.

**Decision — `max_expansions` is PER-EPOCH.** `rqgm.paper.archive.max_expansions: 12` is the budget
for ONE archive round, not for the whole paper phase: at defaults the phase spends 12 expansions per
round × `rounds: 2` = 24 total. This keeps Task 02 §6.2's self-consistency identity
(`width + width·refine_rounds = 4 + 8 = 12`) intact as a PER-EPOCH statement, and it is why **`E = 2`
is the default** in every cost model (Task 06 §5.6), not `E = 1`. The `E = 1` default this replaces
made the boundary unreachable — the budget exactly funded one archive, so no boundary ever fired and
the paper mode shipped as reviewed best-of-N with no co-evolution event at all.

**Wiring — no new trigger code.** The boundary rides the existing
[`runtime.py`](../../../ari-core/ari/rqgm/runtime.py) path: `ensure_epoch` (line 266) replay-restores
or opens `epoch_000` on the first call, and on later calls fires `_run_epoch_boundary` (line 966 —
`run_epoch_audit` → meta → candidate intake → `resolve_transition` → kernel-validate → commit) once
`node_count - ep.node_count_at_open >= nodes_per_epoch` (lines 327–341). `PaperArchiveRuntime` ticks
that trigger once at each round head, **replacing the inert restore-only
`ensure_epoch(0, run_id="paper")`** on today's paper-candidate path
([`runtime.py`](../../../ari-core/ari/rqgm/runtime.py)), which passed a constant `0` and therefore
could never satisfy the line-330 test. Same trigger, same transaction, same kernel — only the tick
source is the paper archive. Fail-open is inherited: `ensure_epoch` never raises into the run
(lines 342–345), so a boundary failure degrades to "epoch continues", never a blocked paper.

**Landed deviation — the tick source is the ROUND INDEX, not the live node count (recorded
2026-07-17).** The shipped driver calls `rqgm.ensure_epoch(round_idx, checkpoint_dir=ckpt,
run_id="paper")` (`paper_runtime.py::_run_coevolution`) with `round_idx ∈ {0, 1, …}` — the archive
round counter — NOT the archive's cumulative draft population, and `RQGMRuntime._nodes_per_epoch`
carries a paper-phase branch that `return`s **1** (`runtime.py:457-467`) rather than reading
`rqgm.epoch.nodes_per_epoch` (10). So `round_idx − node_count_at_open ≥ 1` fires exactly ONE boundary
per round head after the first, which delivers "one archive round = one paper epoch"
**config-independently** — the guarantee this section is about. This was chosen over the literal
live-node-count tick because the literal wiring makes "one round = one epoch" hold only while
`rqgm.paper.archive.max_expansions ≥ rqgm.epoch.nodes_per_epoch` (12 ≥ 10 at stock defaults) and a
round that produces fewer drafts than the threshold (a smaller `max_expansions`, or heavy pruning)
would silently skip its boundary. The round-index tick has no such coupling.

*Residual (audit-record fidelity, 2026-07-17).* The cost is that the hashed `epoch_state_payload` /
`epoch_fingerprint` (`state.py`) record `node_count_at_open` / `node_count_at_close` as the round
index (0, 1, …), not the ~12 drafts a round actually builds (24 across the phase at defaults). No
consumer reads those fields except the self-consistent trigger compare
(`node_count − node_count_at_open ≥ nodes_per_epoch`, `runtime.py:352`), which stays internally
consistent because both sides use the same round-index tick, so no constraint collapses — the audit
record is merely infidelitous about the population. If a future consumer needs the real per-epoch
draft count, tick the LIVE cumulative archive node count and size the paper branch as
`min(nodes_per_epoch, max_expansions)` (so the "one round = one epoch" guarantee survives), and
re-derive this residual.

**What a boundary rewrites.** The Task 03 §5.9 sequence adopts new `paper_writer` / `paper_reviewer`
PromptSpecs (rubric included), and the utility policy itself — composite / axis_weights /
frontier_score — is rewritten by the parent set's utility-evolution task (`../ari_rqgm` task 14),
which is topology-agnostic and inherited. This plan defines **no** paper-local utility machinery.

**Within-epoch freeze.** Active prompt hashes and the utility policy are frozen for the whole round;
changes land only at boundaries, through `RegistryTransitionEngine` + `ConstitutionalKernel`. A draft
scored in epoch `n` is comparable to an epoch `n+1` draft only under the current epoch's frozen
reviewer, or via the erasure/recompute path (Task 04 §5.6–§5.7) — which at `E = 2` is the DEFAULT
path rather than an edge case.

## 6. Data structures / schema changes

### 6.1 New Pydantic models ([`ari-core/ari/config/__init__.py`](../../../ari-core/ari/config/__init__.py))

```python
class PaperConfig(BaseModel):
    """Top-level `paper:` block (paper-archive Task 01)."""
    mode: Literal["linear", "rqgm_archive"] = "linear"

class RQGMPaperArchiveConfig(BaseModel):
    """`rqgm.paper.archive:` skeleton (paper-archive Task 02 adds detail)."""
    model_config = {"extra": "allow"}
    width: int = 4
    refine_rounds: int = 2
    max_expansions: int = 12   # PER-EPOCH (§5.7) -> BFTS max_total_nodes
    depth: int = 3             # -> BFTS max_depth; a genuine best-first tree (§5.1)

class RQGMPaperEpochConfig(BaseModel):
    """`rqgm.paper.epoch:` — SIZING ONLY (§5.7).

    The trigger KIND stays the inherited `rqgm.epoch.boundary: "node_count"`;
    this knob only sizes it for the paper phase, exactly as
    `rqgm.epoch.nodes_per_epoch` does for exploration. One paper epoch = one
    archive round.
    """
    rounds: int = 2

class RQGMPaperAnchorConfig(BaseModel):
    """`rqgm.paper.anchor:` skeleton (paper-archive Task 04 adds detail)."""
    model_config = {"extra": "allow"}
    enabled: bool = False
    corpus_path: str = ""
    sample_size: int = 8

class RQGMPaperPromptEvolutionConfig(BaseModel):
    """`rqgm.paper.prompt_evolution:` — the degraded on-ramp toggle."""
    enabled: bool = True   # false = best-of-N reviewed drafts, no co-evolution

class RQGMPaperConfig(BaseModel):
    """`rqgm.paper:` subsection (paper-archive Task 01 skeleton)."""
    model_config = {"extra": "allow"}   # forward-compat for later-task keys
    enabled: bool = False               # redundant interlock, mirrors rqgm.enabled
    archive: RQGMPaperArchiveConfig = Field(default_factory=RQGMPaperArchiveConfig)
    epoch: RQGMPaperEpochConfig = Field(default_factory=RQGMPaperEpochConfig)
    anchor: RQGMPaperAnchorConfig = Field(default_factory=RQGMPaperAnchorConfig)
    prompt_evolution: RQGMPaperPromptEvolutionConfig = Field(
        default_factory=RQGMPaperPromptEvolutionConfig
    )

# added to ARIConfig (line 1125):
#   paper: PaperConfig = Field(default_factory=PaperConfig)
# added to RQGMConfig (line 1039):
#   paper: RQGMPaperConfig = Field(default_factory=RQGMPaperConfig)
```

Both fields default-constructed, so a workflow.yaml without the blocks parses to today's linear
behavior; `load_config`'s `model_fields` filter picks them up with no loader change; `extra: allow`
on the `rqgm.paper.*` models means unknown Task 02/04 subkeys warn-free parse today and become typed
when their task lands.

### 6.2 `{ckpt}/paper_archive_state.json` (new checkpoint-root snapshot file)

The paper-phase analog of `rqgm_state.json`. Written by a new store method in
[`ari-core/ari/checkpoint.py`](../../../ari-core/ari/checkpoint.py) (plus a module shim), byte-fixed
(`indent=2, ensure_ascii=False`), rewrite-whole-file:

```json
{
  "schema_version": 1,
  "paper_mode": "rqgm_archive",
  "rqgm_paper_enabled": true,
  "mode_source": "config",
  "created_at": "<iso8601, metadata only, never hashed>",
  "exploration_mode": "ari_rqgm",
  "seed_node_id": "node_00c1a2",
  "switch_journal": [
    {"event": "paper_phase_start", "paper_mode": "rqgm_archive", "epoch_id": null}
  ]
}
```

- Written **only when the effective paper mode is `rqgm_archive`** (P5 absence-is-default,
  mirroring `rqgm_state.json` and `bfts_web_provenance.json`). Absence == a pure `linear` paper
  phase == the current-ARI paper trajectory. This keeps default checkpoints byte-identical.
- Write-once, like `persist_run_start` (state.py line 88): an existing file (re-invocation) is never
  clobbered; the epoch-boundary journal entries Task 03 appends go through its own transaction.
- `seed_node_id` records the single `select_best_node` seed (§5.6, the single-entry-point
  guarantee); `exploration_mode` records the orthogonal exploration mode for provenance only.
- `mode_source` ∈ {`config`, `env`, `resume`} — captured at the paper entry BEFORE any env export,
  exactly as `run.py` captures `_rqgm_mode_source` (lines 236–240).
- Task 02 extends this file (or adds a sibling `paper_draft_archive.jsonl`; that file is Task 02's) —
  the `schema_version` field + additive-only policy make either path safe.
- **Registration**: `paper_archive_state.json` is added to `PathManager.META_FILES`
  ([`paths.py`](../../../ari-core/ari/paths.py) line 404, beside `rqgm_state.json` at line 437) and
  to `_INTERNAL_JSON_NAMES`
  ([`node_report/builder.py`](../../../ari-core/ari/orchestrator/node_report/builder.py) line 327,
  beside `rqgm_state.json` at line 334); a test mirrors `test_new_filenames_are_meta_files`.
  (`paper_draft_archive.jsonl` registration is Task 02's.)

### 6.3 Reserved environment variables

`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED` (semantics in §5.2). Documented in `docs/reference/`
only at implementation time (documenting them SemVer-freezes them; the names are fixed by this plan).

## 7. API / class changes

All new code lives in the existing internal package `ari-core/ari/rqgm/` (not exported via
`ari.public.*`; no public-API contract-snapshot churn):

| Symbol | Location (planned) | Contract |
|---|---|---|
| `PaperMode` (Enum) | `ari/rqgm/paper_mode.py` | `LINEAR`, `RQGM_ARCHIVE`. |
| `resolve_paper_mode(cfg) -> PaperMode` | `ari/rqgm/paper_mode.py` | Pure; table in §5.2; never raises; reads only `paper.*`/`rqgm.paper.*`. |
| `PaperArchiveRuntime` | `ari/rqgm/paper_runtime.py` | Facade; Task-01 version constructs nothing but itself and the state writer; exposes `run_archive(all_nodes, experiment_data, checkpoint_dir, mcp, cfg_str, *, linear_fallback)` (pure delegation to the linear pipeline in v1), `persist_mode(checkpoint_dir, *, mode_source)`, `paper_mode` property. Later tasks add members (strategy, executor, governed roles, governance orchestrator, budget) and the §5.7 round loop: `rqgm.paper.epoch.rounds` archive rounds, each closed by ONE inherited `ensure_epoch(round_idx, run_id="paper")` boundary (tick source is the round index — §5.7 landed deviation). |
| `GovernanceOrchestrator` (INHERITED, unchanged) | `ari/rqgm/governance/` — constructed inside `PaperArchiveRuntime` | Ctor mirrors [`runtime.py`](../../../ari-core/ari/rqgm/runtime.py) lines 463–477; no signature change, no new symbol ⇒ zero contract churn. Supplies the `governance_report` `resolve_transition` requires (transition_engine.py line 415) and the `pool.admit` step Task 05 rides (§5.4; owned by Task 03). |
| `ensure_epoch` / `_run_epoch_boundary` (INHERITED, unchanged) | `ari/rqgm/runtime.py` lines 266 / 966 | Reused verbatim as the paper epoch boundary (§5.7). `PaperArchiveRuntime` ticks it once per round head with the round index (and `_nodes_per_epoch` returns 1 for the paper phase — §5.7 landed deviation, 2026-07-17), replacing the inert restore-only `ensure_epoch(0, run_id="paper")`. No new trigger kind, no new transaction. |
| `read_paper_archive_state(ckpt)` / `write_paper_archive_state(ckpt, state)` | `ari/rqgm/paper_runtime.py` (or `ari/rqgm/paper_state.py`) + store method in `ari/checkpoint.py` | Absence-tolerant read (None when missing); best-effort write (never raises into the run). |
| `build_paper_run_start_state(...)` / `persist_paper_run_start(ckpt, ...)` | `ari/rqgm/paper_runtime.py` | Schema-v1 payload + write-once persistence (mirrors `build_run_start_state`/`persist_run_start`, state.py lines 65/88). |
| `reconcile_paper_resume_mode(cfg, ckpt) -> None` | `ari/rqgm/paper_runtime.py` | Force `cfg.paper.mode`/`cfg.rqgm.paper.enabled` to the persisted values on re-invocation (§5.5; mirrors `reconcile_resume_mode`, state.py line 171). |
| `PaperConfig`, `RQGMPaperConfig` (+ nested) | `ari/config/__init__.py` | §6.1. |
| `apply_paper_env_overrides(cfg) -> None` | `ari/config/__init__.py` | §5.2; validate-before-assign; called from `projects.py:paper`. |
| `_effective_paper_mode_str(cfg) -> str` | `ari/config/__init__.py` | Import-free effective-mode mirror (mirrors `_effective_mode_str`, line 1432). |

Changed (existing) code, all additive:

- [`ari-core/ari/cli/projects.py`](../../../ari-core/ari/cli/projects.py) — `paper` command: call
  `apply_paper_env_overrides(cfg)` after `_resolve_cfg` (line 118); the `rqgm_archive` dispatch that
  wraps `generate_paper_section` (line 190). The exploration escalation block (lines 163–175), the
  linear `generate_paper_section` call, and the command signature are unchanged under `linear`.
- [`ari-core/ari/config/__init__.py`](../../../ari-core/ari/config/__init__.py) — `PaperConfig` /
  `RQGMPaperConfig` models, `paper` field on `ARIConfig`, `paper` field on `RQGMConfig`,
  `apply_paper_env_overrides`, `_effective_paper_mode_str`.
- [`ari-core/ari/checkpoint.py`](../../../ari-core/ari/checkpoint.py) —
  `save_paper_archive_state_json` / `load_paper_archive_state_json` store methods + module shims.
- [`ari-core/ari/paths.py`](../../../ari-core/ari/paths.py) — `META_FILES` += `paper_archive_state.json`.
- [`ari-core/ari/orchestrator/node_report/builder.py`](../../../ari-core/ari/orchestrator/node_report/builder.py) —
  `_INTERNAL_JSON_NAMES` += `paper_archive_state.json`.
- [`ari-core/ari/configs/defaults.yaml`](../../../ari-core/ari/configs/defaults.yaml) — a `rqgm.paper`
  block mirroring the typed pydantic defaults (parity pinned by a test, the `rqgm.epoch` precedent).
- No CLI command/flag changes; no `ari.public.*` changes; no MCP tool changes ⇒ zero contract golden
  regeneration for v1 (deliberate budget decision).

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **Default is identity.** A workflow.yaml without `paper:`/`rqgm.paper:` blocks — every existing
   config — resolves to `linear`, constructs no `PaperArchiveRuntime`, imports no `ari.rqgm` module
   on the paper path, writes no new file. The linear `generate_paper_section` call, its YAML-ordered
   `WorkflowDriver` stages, and `loop_back_to` behavior are byte-identical to pre-feature ARI. No
   `paper_archive_state.json`.
2. **`rqgm.paper.enabled=false` compatibility.** Whatever any later task adds under `rqgm.paper.*`,
   the single interlock `enabled: false` (or `paper.mode: linear`) guarantees the entire paper-archive
   subtree is inert. This is structural (the lazy-import branch at the paper entry), not a scatter of
   per-feature flags.
3. **The claim-evidence hard gate stays Layer-0.** The best archive draft is handed to the EXISTING
   compile + claim-gate stages unchanged (Task 07). Task 01 introduces no kernel-wrapping of the
   gate and no change to `ari-core/ari/pipeline/claim_gate/`.
4. **The exploration path is untouched.** `resolve_effective_mode`, `build_runtime`, the exploration
   `run_paper_candidate_escalation` hook, and `rqgm_state.json` are unchanged; the paper mode is
   strictly orthogonal (§5.6).
5. **`ari-skill-paper` is never governed cross-process.** It stays the ungoverned draft executor and
   imports zero rqgm; Task 01 adds nothing to it. Governed prompts live in ari-core (Task 03).
6. **Re-invocation / old checkpoints.** A checkpoint created before this feature has no
   `paper_archive_state.json`; a re-invoked `ari paper` treats absence as `linear` (correct by
   construction). An `rqgm_archive` checkpoint re-invoked resumes in its persisted paper mode
   (§5.5).
7. **Config forward-compat.** Because `ARIConfig` filters unknown top-level keys today, deploying a
   `paper:` block on an *older* ari-core silently gets current linear behavior — the safest failure
   direction. (The reverse — new ari-core, old config — is case 1.)
8. **`rqgm_archive` is additive and fail-open.** The Task-01 `run_archive` is pure delegation to the
   linear pipeline; when later tasks add archive behavior, failures degrade (log + continue) per the
   fail-open discipline the paper-candidate escalation already follows (projects.py lines 164–175).

## 9. Tests

Unit (new `ari-core/tests/test_paper_mode.py`, listed in `ari-core/tests/README.md` for the
readme-sync gate):

- Config parsing: absent blocks → defaults (`linear`, `rqgm.paper.enabled=False`); full blocks
  parse; invalid `paper.mode` literal → Pydantic validation error.
- `resolve_paper_mode`: all four cells of the §5.2 table, including both warning paths.
- `apply_paper_env_overrides`: `ARI_PAPER_MODE`/`ARI_RQGM_PAPER_ENABLED` override YAML; invalid
  values ignored with warning.
- `_effective_paper_mode_str` parity with `resolve_paper_mode` (mirrors the `_effective_mode_str`
  parity test in `test_rqgm_mode.py`).
- `paper_archive_state.json` round-trip: write → read; absence-tolerant read; META_FILES and
  `_INTERNAL_JSON_NAMES` registration asserted (pattern: `test_new_filenames_are_meta_files`).

Regression (linear unchanged):

- The `ari paper` command with a default config takes the linear branch:
  `_effective_paper_mode_str(cfg) == "linear"`, `sys.modules` contains no `ari.rqgm.paper_runtime`
  entry, checkpoint root contains **no** `paper_archive_state.json`, and `generate_paper_section` is
  called with the same arguments as today (call-through spy).
- Full existing ari-core suite and the `ari-skill-paper` suite pass untouched.
- Contract snapshots unchanged: `scripts/snapshot_contracts.py --surface cli --check` and
  `--surface public --check` stay green (no CLI command/flag or `ari.public.*` change).

Smoke (`rqgm_archive` startup — the deletion-criteria "startup test"):

- The `paper` command with `paper.mode=rqgm_archive, rqgm.paper.enabled=true` constructs a
  `PaperArchiveRuntime`, writes `paper_archive_state.json` with `mode_source="config"`, and — with
  the Task-01 pure-delegation `run_archive` — produces the SAME paper output as the `linear` control
  run (stubbed skill/LLM).
- Both-mode smoke matrix crossed with exploration `ari.mode` ∈ {`simple_bfts`, `ari_rqgm`}: the four
  cells of §5.6 behave per the table (escalation fires iff exploration `ari_rqgm`; archive runtime
  built iff paper `rqgm_archive`), and neither leaks into the other. **Landed 2026-07-17** at the
  real CLI entry as `test_paper_archive_search.py::test_cli_2x2_matrix_no_cross_leak` (all four cells,
  including the previously-unexercised `ari_rqgm × rqgm_archive` cell where both runtimes coexist —
  R5) plus `::test_archive_output_invariant_to_exploration_mode` (same `rqgm_archive` cfg under both
  exploration rows yields the same draft archive; the archive never emits `rqgm_state.json`).
- **The boundary fires at defaults** (§5.7 — the falsifiable claim): an `rqgm_archive` run with
  stock `rqgm.paper.*` defaults closes `rounds - 1 = 1` epoch boundary: round 1 runs under
  `epoch_000`, `_run_epoch_boundary` is entered exactly once at round end, and round 2's drafts are
  built under `epoch_001`'s active prompt hashes. **Landed 2026-07-17** as
  `test_paper_archive_search.py::test_boundary_fires_once_at_stock_defaults` (Task 02/03 bodies have
  shipped; it spies `_run_epoch_boundary` at stock `rqgm.paper.epoch.rounds`, asserting one boundary,
  `epoch_state.json == epoch_001`, records spanning `epoch_000`/`epoch_001`, and two active reviewer
  hashes — the boundary EVENT, not a reviewer-hash change, which needs ~5 boundaries per doc 04).

Resume:

- Paper phase run as `rqgm_archive`, re-invoked with conflicting env `ARI_PAPER_MODE=linear` →
  persisted paper mode wins, warning logged. Re-invoked on a checkpoint with no
  `paper_archive_state.json` while requesting `rqgm_archive` → stays `linear`, warning logged.

CI placement: all of the above are plain ari-core tests (run hard via `refactor-guards.yml`); no new
workflow is needed for this task.

## 10. Risks

- **R1 — Silent config typos.** A misspelled block (`papr:` or `rqgm.papper:`) is silently dropped by
  the `model_fields` filter. Mitigation: same posture as exploration Task 01 R1 — docs state the exact
  key names and the smoke test covers the canonical spelling; optional edit-distance warning in
  `load_config` is shared hardening, not owned here.
- **R2 — `_resolve_cfg` applies no env at the paper entry.** Forgetting `apply_paper_env_overrides`
  would make `ARI_PAPER_MODE` a no-op (unlike `run`/`resume`, which already call
  `apply_rqgm_env_overrides`). Mitigation: the override call is a completion criterion (§11.1) and a
  unit test asserts env takes effect through the paper command.
- **R3 — `rqgm.paper` vs `rqgm.*` knob confusion.** `rqgm.paper.prompt_evolution.enabled` and
  `rqgm.prompt_evolution.enabled` are distinct; an operator could set the wrong one. Mitigation:
  §5.1 pins the two homes; Task 06 documents that the reused Task-12 budget knobs stay under `rqgm.*`
  and are never shadowed by `rqgm.paper.*`.
- **R4 — Re-invocation pin surprises users** who expect env to win on a second `ari paper`. Mitigation:
  loud warning + documented rule "a checkpoint's paper mode is set at the first paper phase and is
  read persisted-first thereafter" (mirrors exploration Task 01 R4).
- **R5 — Two runtimes present at once.** Under exploration `ari_rqgm` + paper `rqgm_archive`, both the
  exploration `_bfts_paper.rqgm` (escalation) and the new `PaperArchiveRuntime` exist. They are
  independent objects with independent state files (`rqgm_state.json` vs `paper_archive_state.json`)
  and must not be conflated. Mitigation: §5.6 fixes the orthogonality; the smoke matrix asserts no
  cross-leak; the provenance schema records `exploration_mode` for auditability only.
- **R6 — Contract-snapshot creep.** A later temptation to add a `--paper-mode` CLI flag re-opens the
  golden budget. Guard: this plan's decision (config+env only for v1) is recorded as normative.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Both configs defined** — `paper.mode` (`linear | rqgm_archive`, default `linear`) and
   `rqgm.paper.enabled` (default `false`) are specified as typed fields with YAML shape, defaults,
   env overrides (`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`) and the paper-entry override call
   site, and precedence (§5.1, §5.2, §6.1), including the effective-mode table for all four value
   combinations.
2. **linear preservation policy written** — the normative policy that `linear` preserves the current
   paper pipeline byte-for-byte (identity default, no `ari.rqgm` imports/objects/files on the paper
   path, `generate_paper_section`/`WorkflowDriver`/claim-gate unchanged, `rqgm.paper.enabled=false`
   structural inertness) is written down (§5.3, §8) with the exact code deltas enumerated.
3. **`rqgm_archive` component set + construction site defined** — the `PaperArchiveRuntime`
   construction site at the paper entry (wrapping `generate_paper_section`) and the components it
   later owns, with owning tasks, are listed (§5.3, §5.4), all funneled through `PaperArchiveRuntime`.
4. **Mode-switch timing + provenance defined** — paper-phase-start-only switching, the no-mid-phase
   rule, re-invocation/resume semantics (persisted paper mode wins), `paper_archive_state.json`
   ownership + registration, and the read-precedence rule are specified (§5.5, §6.2).
5. **Exploration independence stated** — `paper.mode` toggles independently of `ari.mode`; the 2×2
   matrix is valid; the escalation hook and `resolve_effective_mode` never read `paper.*` and
   `resolve_paper_mode` never reads `ari.*` (§5.6).
6. **Paper epoch boundaries defined** — one paper epoch = one archive round; `rqgm.paper.epoch.rounds`
   (default `2`) *sizes* the INHERITED `rqgm.epoch.boundary: "node_count"` trigger instead of forking
   a new trigger kind; `max_expansions` is per-epoch; the boundary rides the existing
   `ensure_epoch` / `_run_epoch_boundary` path, ticked once per archive round by the round index
   (`_nodes_per_epoch` returns 1 for the paper phase — §5.7 landed deviation, 2026-07-17), and the
   `GovernanceOrchestrator` is constructed for the paper phase — so a boundary actually fires at
   defaults (§5.4, §5.7).
7. Downstream tasks (02, 03, 04, 06, 07) can consume this plan's decisions without re-opening them:
   config home, read-precedence rule, `PaperArchiveRuntime` seam, `paper_archive_state.json`
   ownership, single-entry-point (`select_best_node`) seed, the linear-fallback contract, the
   archive-topology defaults (`depth: 3`, per-epoch `max_expansions`), and the §5.7 paper-epoch
   definition (`E = 2` at defaults).

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

- The paper-mode config (`paper.mode`, `rqgm.paper.enabled`, typed models, env overrides) is
  implemented.
- Smoke tests exist for **both** paper modes (`linear` regression smoke and `rqgm_archive` startup
  smoke, per §9), crossed with both exploration modes for the 2×2 matrix.
- `linear` is confirmed not to break the existing paper pipeline (full ari-core + ari-skill-paper
  suites green plus the §9 identity assertions: no `ari.rqgm.paper_runtime` import / no
  `paper_archive_state.json` on default paper runs, contract snapshots unchanged).
- A `rqgm_archive` startup test exists (paper-entry dispatch, `PaperArchiveRuntime` construction,
  `paper_archive_state.json` written, pure-delegation parity with linear output).
- The paper-mode-switching policy (paper-phase-start-only, no mid-phase switch, re-invocation rule)
  has been moved to permanent docs (the execution-mode guide under `docs/`).

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

- [ ] `paper.mode` / `rqgm.paper.enabled` implemented as typed config with env overrides
      (`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`) and the paper-entry override call.
- [ ] Smoke tests pass in both `linear` and `rqgm_archive` paper modes, across the 2×2 matrix with
      exploration `ari.mode`.
- [ ] Default-config paper runs produce checkpoints with no `paper_archive_state.json` and no
      `ari.rqgm.paper_runtime` import.
- [ ] `rqgm_archive` startup test (paper-entry dispatch + `paper_archive_state.json` + pure-delegation
      parity) exists and passes.
- [ ] Paper-mode-switching policy published in the permanent execution-mode guide.
- [ ] `paper_archive_state.json` registered in `PathManager.META_FILES` and node_report
      `_INTERNAL_JSON_NAMES`.
- [ ] Exploration-independence statement (2×2 matrix) carried into the permanent docs (or explicitly
      handed to Task 07's whole-set deletion flow).
