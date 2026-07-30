---
sources:
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
last_verified: 2026-07-30
---

# Execution Modes: `simple_bfts` and `ari_rqgm`

ARI has two execution modes:

- **`simple_bfts`** (default) — current ARI, unchanged. With no `ari:`/`rqgm:`
  blocks in workflow.yaml (i.e. every pre-RQGM config), ARI constructs no RQGM
  object, imports no `ari.rqgm` module, and writes no new checkpoint file.
- **`ari_rqgm`** (opt-in) — Constitutional ARI-RQGM epoch governance and
  co-evolution. Never enabled by default. There is no `--mode` CLI flag;
  activation is a configuration decision made either in `workflow.yaml` /
  the environment (below — the canonical description) or, **for a new run
  only**, from the dashboard's Configuration Studio
  ([GUI selection](#selecting-the-mode-from-the-gui)).

## Turning RQGM on

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch (simple_bfts | ari_rqgm)
rqgm:
  enabled: true       # redundant safety interlock
```

Both keys must agree. The effective mode is resolved by the pure function
`ari.rqgm.mode.resolve_effective_mode`:

| `ari.mode` | `rqgm.enabled` | Effective mode | Action |
|---|---|---|---|
| `simple_bfts` | `false` | `simple_bfts` | default; silent |
| `simple_bfts` | `true` | `simple_bfts` | warning: interlock set but mode is simple_bfts |
| `ari_rqgm` | `false` | `simple_bfts` | warning: mode requested but interlock off |
| `ari_rqgm` | `true` | `ari_rqgm` | RQGM runtime constructed |

Environment overrides (applied after profiles, so an explicit env choice
wins): `ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} and `ARI_RQGM_ENABLED` ∈
{`0`,`1`,`true`,`false`}. Invalid values warn and are ignored
(validate-before-assign).

When the effective mode is `ari_rqgm`, `ari run` writes
`{checkpoint}/rqgm_state.json` (mode, interlock, `mode_source` ∈
`config|env|resume`, switch journal) before the first node runs and copies the
bundled `constitution.yaml` into the checkpoint (copy-once, never clobbered,
non-evolving). The founding registration also runs at boot: before
`epoch_000` opens, the founding prompt/component set is committed to
`rqgm_transitions.jsonl`, so `rqgm_registry.json` and `epoch_state.json`
appear before the first node completes (see the
[RQGM Runtime Walkthrough](../concepts/rqgm_runtime_walkthrough.md)).
**Absence of `rqgm_state.json` means a pure `simple_bfts`
run** — default checkpoints stay byte-identical to pre-RQGM ARI.

## Mode-switch timing policy

Allowed:

1. **Run start** — the only entry into `ari_rqgm`. The effective mode is
   resolved once and persisted before the first node runs.
2. **Epoch boundary** (only within an `ari_rqgm` run) — the run may
   **downgrade** `ari_rqgm → simple_bfts` inside the epoch-boundary
   transaction (cost/emergency fallback). The downgrade is audited and
   validated by the ConstitutionalKernel.

Forbidden / impossible:

- `simple_bfts → ari_rqgm` **mid-run**: `simple_bfts` has no epoch
  boundaries, so there is no legal switch point. Upgrading requires a new run
  (or a child run launched with `ARI_MODE=ari_rqgm`).
- Any switch mid-epoch, mid governance transaction, mid registry transition,
  or mid frontier rebuild.

Resume rule: `ari resume` reads `rqgm_state.json` checkpoint-first and the
**persisted mode wins** over package config and env. A disagreement produces a
warning, never a mid-run mode flip — a run's mode is immutable except at epoch
boundaries, downgrade-only.

Read precedence for all RQGM mode readers:
`{checkpoint}/rqgm_state.json` → typed config (`--config`/checkpoint/package
YAML + profile + env in the standard precedence) → defaults. No RQGM code
re-reads the package workflow.yaml directly.

## VirSci independence

`proposal_router.generators.virsci.enabled` (default `false`) is orthogonal to
`ari.mode`: all four combinations are valid, the mode-resolution code never
reads `proposal_router.*`, and the VirSci gate never reads `ari.mode`. With
VirSci off, no VirSci runtime, vendored path, prompt, or snapshot corpus is
touched in either mode.

## The paper execution axis: `paper.mode`

The paper-writing phase (`ari paper`) has its OWN execution axis, fully
**orthogonal** to `ari.mode`. It is resolved by a separate pure function,
`ari.rqgm.paper_mode.resolve_paper_mode` (`PaperMode` ∈ {`linear`,
`rqgm_archive`}), which reads ONLY `paper.mode` / `rqgm.paper.enabled` — never
`ari.mode` / `rqgm.enabled`:

- **`linear`** (default) — today's paper pipeline, byte-identical under
  `ari.mode: simple_bfts`. All three entries (`ari paper`, `ari run`, `ari
  resume`) route through the shared dispatch
  (`ari/cli/paper_dispatch.py:run_paper_phase`), which calls
  `generate_paper_section` on this axis and imports no `ari.rqgm` module.
  Absence of `{checkpoint}/paper_archive_state.json` means a pure `linear`
  paper run. Under `ari.mode: ari_rqgm` the dispatch additionally runs the
  paper-candidate pre-flight on the *exploration* axis (described in the
  [RQGM Runtime Walkthrough](../concepts/rqgm_runtime_walkthrough.md#8-run-end)),
  so the paper phase is byte-identical only in the default exploration mode.
- **`rqgm_archive`** (opt-in) — the constitutional paper archive: a shallow
  best-first tree over draft space (`PaperArchiveStrategy`,
  `ari/rqgm/paper_archive.py`) with a governed `paper_writer` + `paper_reviewer`
  driving the ungoverned `ari-skill-paper` executor
  (`ari/rqgm/paper_draft_executor.py`) as the "hands". See
  [RQGM Architecture](../concepts/rqgm_architecture.md) for the layer itself.

### Turning the paper archive on

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive       # master switch (linear | rqgm_archive)
rqgm:
  paper:
    enabled: true          # redundant safety interlock
```

Both keys must agree. The interlock fails safe toward `linear` with a warning
(`resolve_paper_mode`):

| `paper.mode` | `rqgm.paper.enabled` | Effective paper mode | Action |
|---|---|---|---|
| `linear` | `false` | `linear` | default; silent |
| `linear` | `true` | `linear` | warning: interlock set but mode is linear |
| `rqgm_archive` | `false` | `linear` | warning: mode requested but interlock off |
| `rqgm_archive` | `true` | `rqgm_archive` | paper-archive runtime constructed |

Environment overrides (applied by `apply_paper_env_overrides`, which the `ari
paper` command calls explicitly — they never free-ride on a plain
`load_config`): `ARI_PAPER_MODE` ∈ {`linear`, `rqgm_archive`} and
`ARI_RQGM_PAPER_ENABLED` ∈ {`0`,`1`,`true`,`false`}. Invalid values warn and
are ignored.

When the effective paper mode is `rqgm_archive`, `ari paper` writes
`{checkpoint}/paper_archive_state.json` once (paper mode, interlock,
`mode_source` ∈ `config|env|resume`, exploration mode, seed node) before the
archive loop runs (`persist_paper_run_start`, write-once — a later invocation
that computes a different seed appends a `seed_changed` entry to the file's
`seed_journal` instead of rewriting the record). Re-invocation
reconciles checkpoint-first (`reconcile_paper_resume_mode`): the persisted
paper mode wins over config and env, a disagreement warns, and a checkpoint
without the state file stays `linear` for that phase — so no `ari.rqgm` module
ever loads on a pure-linear re-invocation.

### Agent-as-judge draft scoring (opt-in)

`rqgm.paper.reviewer.agent_as_judge.enabled` (bool, **default `false`**;
`max_tokens` defaults to `1024`) selects how each archive draft is scored. The
env override `ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`} is applied by
the same `apply_paper_env_overrides` with the same validate-before-assign
posture as `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` — an invalid value warns
and is ignored. Like every `rqgm.paper.*` key it is meaningful only under the
effective `rqgm_archive` paper mode.

- **Off** (default) — the deterministic, LLM-free venue rubric:
  `GovernedPaperReviewer.score`'s own else-branch (`_rubric_draft_score`), the
  same combination `ari/rqgm/paper_judge.py:deterministic_rubric_score_fn`
  packages as the judge's fallback target. No live LLM call is placed on the
  draft-scoring path, so P2 determinism is preserved.
- **On** — the shared paper dispatch
  (`ari/cli/paper_dispatch.py:build_agent_as_judge`, used by `ari paper`, `ari
  run` and `ari resume` alike) injects a real `LLMClient`-backed
  `reviewer_score_fn` (`build_agent_as_judge_score_fn`) that scores each draft
  over the SAME venue rubric axes, weighted by the ACTIVE governed
  `paper_reviewer` prompt's emphasis (so evolving the reviewer moves best-belief
  selection), and can read axes no deterministic reader can — `novelty`,
  `significance` — which is what breaks the discrimination ceiling where two
  mature drafts both saturate the structural rubric and tie.

Scoring is **fail-open, never a fabricated constant**: an LLM error, an
unparseable reply, a reply naming no rubric axis, or a reply covering less than
50% of the rubric's total axis weight all degrade to the deterministic rubric,
and non-finite values are rejected rather than propagated into selection.
Because a judged score and a fallback score are the same float to every
consumer, the score_fn carries `judged` / `degraded` counters that the paper
dispatch logs after the archive (`log_agent_as_judge_provenance`) — otherwise a
run whose LLM was down for every call would look identical to a fully judged
one.

### 2×2 independence from `ari.mode`

The two axes are independent — all four combinations are valid:

| `ari.mode` | `paper.mode` | Exploration | Paper writing |
|---|---|---|---|
| `simple_bfts` | `linear` | classic BFTS | classic linear paper |
| `simple_bfts` | `rqgm_archive` | classic BFTS | governed draft archive |
| `ari_rqgm` | `linear` | epoch governance | classic linear paper |
| `ari_rqgm` | `rqgm_archive` | epoch governance | governed draft archive |

`resolve_paper_mode` never reads `ari.mode`, and the exploration
`resolve_effective_mode` never reads `paper.*`; `_effective_paper_mode_str`
mirrors the paper activation cell import-free so a default paper run never
loads `ari.rqgm.paper_mode` (parity pinned by `tests/test_paper_mode.py`). The
governed `paper_writer` / `paper_reviewer` roles are **paper-mode-gated
founding rows** (`ari/rqgm/events.py:EVOLVABLE_ROLES`): they enter the registry
only under the effective `rqgm_archive` paper mode, so an exploration
`ari_rqgm` boot is byte-identical whether or not the paper archive is on.

### Cost bound and the degraded on-ramp

The per-epoch draft population is bounded by `node_budget =
min(width·(1+refine_rounds), max_expansions)` (`paper_archive.archive_node_budget`),
which becomes the BFTS `max_total_nodes` at ANY depth — a deeper tree
redistributes the same budget, never multiplies it (no `width^depth` term). At
the default config (`width: 4`, `refine_rounds: 2`, `max_expansions: 12`,
`depth: 3`) that is `min(4·(1+2), 12) = 12` nodes. Two on-ramps keep the
default cheap and honest:

- `rqgm.paper.prompt_evolution.enabled: false` collapses the archive to
  reviewed best-of-N — candidate minting is suppressed, the roles stay pinned
  at their founding v1 prompts, cost ≈ today's paper phase.
- `rqgm.paper.anchor.enabled: false` (the **default**) leaves the reviewer with
  no ground-truth anchor, so even with `prompt_evolution.enabled: true` the
  default `rqgm_archive` behaves as reviewed best-of-N until a curated corpus is
  supplied (see [Adopting the paper archive](rqgm_migration.md#adopting-papermode)).

## Selecting the mode from the GUI

Everything above is the canonical description: a mode is a configuration
decision, resolved from `workflow.yaml` + profile + env in the standard
precedence, and `{checkpoint}/rqgm_state.json` (or
`{checkpoint}/paper_archive_state.json`) is the authority for a run that
already exists.

Since **ADR-09** (accepted 2026-07-27) the dashboard can make that decision
for a **new** run instead of asking you to hand-edit two interlocked keys.
It supersedes the earlier "no GUI toggle in v1" statement for that case only
— there is still no `--mode` CLI flag, and no GUI path can change the mode
of a run that already exists.

**Where the control lives.** Configuration Studio (`#/studio`), *Execution*
section, in **run-template** or **run-draft** scope. Two controls, one per
axis:

| Control | Writes | Values |
|---|---|---|
| Execution mode | `ari.mode` **and** `rqgm.enabled` | `simple_bfts` (default) / `ari_rqgm` |
| Paper mode | `paper.mode` **and** `rqgm.paper.enabled` | `linear` (default) / `rqgm_archive` |

Four properties are worth knowing before you use it:

1. **One control writes both keys of its interlock.** Picking `ari_rqgm`
   writes `ari.mode: ari_rqgm` *and* `rqgm.enabled: true` in the same save.
   The GUI cannot produce the half-set pair the runtime would silently
   degrade; a document that somehow carries one half without its agreeing
   twin is rejected with a typed 400 `mode_interlock_mismatch` at template
   create/PATCH, draft create/PATCH, and launch.
2. **New runs only.** Both leaves are `mutability: new_run_only`. The
   selection applies to the run the Studio is about to launch. **Resume is
   unaffected**: `ari resume` still reads `{checkpoint}/rqgm_state.json`
   checkpoint-first, the persisted mode still wins over config and env, and a
   run's mode stays immutable except at epoch boundaries (downgrade-only).
   No GUI path writes that file.
3. **Project scope still refuses.** The mode paths are `scope: run`, so the
   project-defaults document rejects them (`not_project_scope`); the controls
   are disabled there with the reason shown.
4. **Only these four leaves.** The other 97 paths in the `Execution mode`
   category and the `rqgm.*` tree (epoch, kernel, governance, adversarial,
   budget tuning) are **not** editable from the GUI in this release. They stay
   visible read-only with their effective values, and a draft carrying one of
   them is still rejected at launch with `mode_locked` — edit `workflow.yaml`
   to change them. Selecting a mode is not a governance mutation: the RQGM
   governance workspace and its `/api/v1/runs/{run_id}/rqgm/*` routes remain
   read-only.

**What a GUI-selected mode does to the checkpoint.** A non-default selection
is materialized both ways, so the checkpoint is self-describing: minimal
`ari:` / `rqgm:` / `paper:` blocks are merged into the run's **own**
`workflow.yaml` copy (the bundled file is never modified; when those
top-level keys are absent the blocks are appended, leaving every existing
byte and comment intact), and the documented env overrides `ARI_MODE`,
`ARI_RQGM_ENABLED`, `ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED` are exported
to the run subprocess. Leaving the defaults writes and exports **nothing** —
a `simple_bfts` + `linear` launch is byte-identical to a pre-ADR-09 one, and
that includes a draft that explicitly restates the defaults (the gate is the
resolved *value*, not whether you touched the control).

**What the GUI shows when the runtime falls back.** The launch review never
shows what you asked for — it shows the **resolved** mode read off the
run's preview manifest, i.e. the value after `resolve_effective_mode` /
`resolve_paper_mode` have applied their warn-and-fall-back rule. If a layer
the Studio does not own breaks the pair (for example `ARI_RQGM_ENABLED=0` in
the server's environment while the draft asks for `ari_rqgm`), the review
renders the requested value, the resolved value, and the resolver's warning
verbatim — and the launch is **blocked** with an `interlock_mismatch`
validation error rather than quietly starting the fallback run. A run only
displays as governed when the resolved mode is `ari_rqgm`.

## Constitutional kernel (Layer 0)

In `ari_rqgm` mode, every governance state change is validated by the
`ConstitutionalKernel` (`ari/rqgm/kernel.py`). The kernel is **deterministic,
non-evolving, and NOT an LLM judge**: zero LLM calls, zero network calls,
zero wall-clock-dependent decisions (design principle P2). It judges
procedure only — never research correctness. The fixed layer as a whole is
never an evolution target: kernel, schema checker, hash checker, access
control (capability matrix), audit log, transition rules, selective-erasure
rule, fixed verifier (results.json merge), metric recomputer, and the
claim-evidence hard gate.

Rules live in code, never in config: `ari/rqgm/kernel_rules.py` (role rules,
capability matrix, severity map) and `ari/rqgm/transition_rules.py` (the
fixed T1–T21 transition table, shared with the RegistryTransitionEngine —
single source of truth). A `constitution_hash` over all tables is pinned by
`ari-core/tests/test_rqgm_kernel.py` and recorded additively in `meta.json`,
so any rule edit is an explicit reviewed diff plus a hash re-pin. The bundled
`constitution.yaml` is a human-readable statement only — editing it changes
nothing.

Blocking matrix summary ("block the institution, not the research"):

- **Hard-block set** (vetoes RQGM state changes — epoch-transition commit,
  registry write, frontier rebuild commit, candidate promotion — never node
  execution): transition-table violations, non-engine registry writes,
  stale/retired-prompt-derived records reaching the frontier,
  governance-record schema violations, active-component hash mismatches,
  audit-log tampering, clean-room contamination, authority expansion, and
  pre-flight capability denials (including retired-prompt-text access, denied
  at the MCP gate with the standard `{"error": ...}` envelope).
- **Warn-and-flag set** (never interrupts research execution): per-node
  record schema and hash anomalies, post-hoc access findings,
  role-separation findings at creation time, context-scope findings. Warned
  records become inadmissible as governance evidence at the boundary.

On a blocked transition the previous epoch's active set carries over
unchanged and the run continues (governance-suspended carry-over — never a
run abort). `rqgm.kernel.enforcement: audit_only` downgrades every context to
warn-and-log for staged rollout and ablations.

## Compatibility guarantees

- `rqgm.enabled: false` (or `ari.mode: simple_bfts`) makes the entire RQGM
  subtree structurally inert — the lazy-import branch in
  `ari.core.build_runtime` is the single gate, not a scatter of per-feature
  flags.
- The only code touched on `simple_bfts` paths: two typed config fields with
  defaults, one env-override call, and a handful of duck-typed
  `getattr(bfts, "rqgm", None)` probes — the run loop, the runtime wiring, and
  the paper-dispatch hand-off — every one of which reads `None` there.
- Old checkpoints have no `rqgm_state.json`; `resume` treats absence as
  `simple_bfts`. An `rqgm:` block deployed on an older ari-core is silently
  ignored (current behaviour — the safest failure direction).

## Limitations (v1)

- Profiles (`--profile`) do not merge RQGM keys.
- No `--mode` CLI flag. The GUI selects the two mode intents for a **new** run
  only ([above](#selecting-the-mode-from-the-gui)); the remaining `rqgm.*`
  governance and tuning parameters are configuration-file only.
- A run's mode cannot be changed after it starts, from any surface — resume
  takes the persisted mode, and the only in-run transition is the
  epoch-boundary downgrade.
