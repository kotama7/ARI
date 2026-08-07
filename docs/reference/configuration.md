---
sources:
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/rqgm/budget.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/cli/lineage.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/tests/test_gui_baseline_settings_contract.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
last_verified: 2026-08-08
---

# Configuration Reference

## Configuration Precedence (observed)

ARI configuration enters from several sources. There are **two precedence
chains** — the value a setting resolves to depends on *who is asking*:

- **Runtime (core/CLI)** — what the agent loop and pipeline actually use.
  Built by `ari.config.load_config()` (or `auto_config()` when no YAML):
  **`ARI_*` env var > workflow.yaml/config YAML > Pydantic field default**.
  Env always wins because the `_apply_*_env_overrides` functions run *last*
  (after profile merge). `auto_config()` is the no-file fallback (env over
  hardcoded). Profiles (`--profile laptop|hpc|cloud`) are applied between YAML
  and env, but they are **not** a deep merge — `_apply_profile`
  (`ari/cli/run.py`) copies exactly four keys and silently ignores every other
  key in the profile file (see the 4-key profile merge caveat under
  *Resolution model* below).
- **GUI Settings panel** — what `/api/settings` shows. Built by
  `_api_get_settings()`: **saved `settings.json` (if truthy) > `ARI_*` env >
  `workflow.yaml` > hardcoded default**, with a falsy-re-force quirk (a
  saved-but-empty `llm_model`/`llm_provider` is re-filled from `workflow.yaml`
  only, dropping the env tier).

The **bridge**: the GUI `/api/launch` does **not** pass choices to the spawned
CLI as args — it writes them into the subprocess `ARI_*` env **and** snapshots
them into `{checkpoint}/launch_config.json`. The CLI then resolves via the
runtime chain above. `launch_config.json` is re-read on disk only by
`/api/run-stage` and to rehydrate the dashboard display state; it is *not*
re-parsed by `ari.config`.

| Setting | Winning order (highest first) | Decided in |
|---------|-------------------------------|-----------|
| `llm_model` (runtime) | `ARI_MODEL` > `ARI_LLM_MODEL` > YAML `llm.model` > `qwen3:8b` | `config/__init__.py:_apply_llm_env_overrides` |
| `llm_model` (GUI display) | in-mem `_launch_llm_model` > `launch_config.json` > `settings.json` > `workflow.yaml` > `''` | `viz/routes.py`, `viz/ui_helpers.py` |
| `llm_model` (Settings merge) | saved `settings.json` (if truthy) > `ARI_LLM_MODEL` > `workflow.yaml` > `''` | `viz/api_settings.py:_api_get_settings` |
| `llm_provider`/`backend` (runtime) | `ARI_BACKEND` > YAML `llm.backend` > `ollama` | `config/__init__.py:_apply_llm_env_overrides` |
| paper `language` | `ARI_PAPER_LANGUAGE` env **only** (set by GUI launch; *not* re-derived from `launch_config.json` on a hand-run CLI) | `ari-skill-paper` reads env; `viz/api_experiment.py` sets it |
| GUI port | `ARI_GUI_PORT` (via `start.sh`) > `--port` (argparse default **8765**) > `state.py` `9886` placeholder | `start.sh`, `viz/server.py:main` |
| SLURM partition | explicit tool `partition` kwarg (sinfo-validated) > `SLURM_DEFAULT_PARTITION` > sinfo first; the kwarg is chosen from: experiment.md `Partition:` > `ARI_SLURM_PARTITION` > sinfo | `ari-skill-hpc/slurm.py`, `ari/agent/workflow.py` |
| checkpoint dir | `ARI_CHECKPOINT_DIR` > YAML `checkpoint.dir` > `workspace/checkpoints/{run_id}` | `config/__init__.py:_apply_checkpoint_env_overrides`, `PathManager` |
| workspace root | `ARI_CHECKPOINT_DIR` (recovered: the outermost `checkpoints/` ancestor's parent, or the checkpoint's own parent when it has no such ancestor) > an explicit `workspace_root` argument > `{ARI_ROOT}/workspace` > `{repo_root}/workspace`, only when `{repo_root}/ari-core` is a directory > the resolved current working directory | `paths.py:RuntimePathResolver.resolve_workspace_root` |
| `bfts_pipeline[].enabled` | `{checkpoint}/workflow.yaml` > package `ari-core/config/workflow.yaml` > `true` | `cli/bfts_loop.py` (raw YAML read) |
| `lineage_decision.*` | active rubric's `lineage_thresholds` (`ARI_RUBRIC`; the four threshold keys only, not `mode`) > package `ari-core/config/workflow.yaml` > `./config/workflow.yaml` (process cwd) > call-site defaults | `cli/lineage.py:_load_lineage_decision_config` |
| `root_idea_selection.enabled` | package `ari-core/config/workflow.yaml` **only** > `false` | `cli/bfts_loop.py` (raw YAML read) |

**One owner for "what is the workspace root".** The five-step ladder in the
table above lives in exactly one function,
`RuntimePathResolver.resolve_workspace_root()` (`ari-core/ari/paths.py`), and
four production call sites already route through it: `auto_config()`
(`ari/config/__init__.py`) when `ARI_CHECKPOINT_DIR` is unset,
`workspace_harness_root()` (`ari/harness_registry.py`, after its own
`ARI_WORKSPACE` short-circuit), the GUI document store (`ari/viz/v1/store.py`)
and the v1 launch path (`ari/viz/v1/launch.py`), which mints
`{workspace_root}/checkpoints/{run_id}`. Two things to read past when you open
the code: the method's own docstring still describes itself as *additive* with
opt-in "deferred to 005" — that sentence is stale, the four callers above are
the opt-in — and [Environment Variables](environment_variables.md) files
`ARI_ROOT` under *Checkpoint + paths* as the "ARI source tree root (used in
tests)", which understates it. `ARI_ROOT` is tier 3 of this ladder, so with
`ARI_CHECKPOINT_DIR` unset it decides where real runs land. What has *not*
changed: `PathManager()`'s bare constructor still defaults to the current
working directory and does not consult the ladder.

**Falsy-vs-missing:** the core env-override guards (`if _m:` etc.) treat an
empty env var as missing (YAML/default kept; `base_url` uses an explicit
`!= ""`). The GUI merge `{**defaults, **saved}` lets a present-but-empty saved
key win, then re-forces only `llm_model`/`llm_provider` from `workflow.yaml`.

**Two `workflow.yaml` blocks are read from the package copy only
(anti-pattern).** `lineage_decision` and `root_idea_selection` are not
declared `ARIConfig` fields, so `load_config`'s
`{k: v for k, v in raw.items() if k in ARIConfig.model_fields}` filter drops
them and each block is re-read from raw YAML by its own reader. Those two
readers do not agree with the rest on *which* `workflow.yaml` to read.
`bfts_pipeline` is read checkpoint-first — `{checkpoint}/workflow.yaml`, with
the package copy only as a fallback — but `_load_lineage_decision_config`
(`ari/cli/lineage.py`) reads the package `ari-core/config/workflow.yaml`,
falling back to `./config/workflow.yaml` relative to the process working
directory only when the package file is missing, and the
`root_idea_selection` block reads the package copy and nothing else; the
checkpoint-first and the package-only read sit in the same file,
`ari/cli/bfts_loop.py`. Consequences: writing either block into
`{checkpoint}/workflow.yaml` has no effect, and `--config` cannot carry them
either — the typed loader discards them and neither reader consults that
path. To change them for a run, edit the package `workflow.yaml`; for the
four `lineage_decision` threshold keys, the active rubric's
`lineage_thresholds` overlay is the supported per-venue knob. This is a known
inconsistency rather than a designed layering, and new readers should not
extend the package-only pattern.

**Unknown top-level keys are dropped without a runtime warning.**
`load_config`'s `model_fields` filter has a second consequence, and this one
has no reader to rescue it. `ARIConfig` sets `extra="allow"`, but that changes
nothing here: the filter runs *before* construction, so an undeclared block
never reaches the model. Blocks like `memory`, `container`, `lineage_decision`,
`bfts_pipeline`, `pipeline` and `claim_gate_policy` survive only because
something re-reads the raw YAML for them;
`ari.config.resolver.KNOWN_NON_CONFIG_TOP_KEYS` enumerates the top-level keys
the resolver currently credits with such a reader — but it is a hand-curated
list, not a derived one, and it is **incomplete**. There is a second, generic
consumer it does not account for: the pipeline driver
(`ari/pipeline/driver.py`) re-reads the raw `workflow.yaml` and splats every
top-level scalar into the stage-template namespace (top-level dicts are
exposed too, for dot-notation, bar `pipeline`/`skills`/`stages`), so an
undeclared top-level key is dropped from `ARIConfig` yet still reachable as
`{{key}}` inside a stage's `inputs:`.
The bundled `ari-core/config/workflow.yaml` relies on exactly that for
`paper_venue: arxiv` and `paper_rubric: generic_conference`, which are in
neither `ARIConfig.model_fields` nor `KNOWN_NON_CONFIG_TOP_KEYS` and are
nonetheless live — `write_paper` takes `rubric_id: '{{paper_rubric}}'` and
`venue: '{{paper_venue}}'`, and `review_compiled_paper` takes `rubric_id`
again. `paper_rubric` is the setting that picks the reviewer rubric, and
`write_paper_iterative` has no environment fallback and no guessed default
for it, so it is the opposite of dead config. A top-level key that *nothing*
templates on is discarded outright, and nothing is logged when it happens;
there is **no near-miss ("did you mean") check** anywhere in `ari.config`. A
misspelled block — `rqmg:` for `rqgm:` — therefore leaves the run silently on
defaults, with no error to notice. Two things partly cover this, neither of
them on the CLI at load time:

- **The resolver warns, in its payload.** `_apply_workflow_layer`
  (`ari/config/resolver.py`) appends `workflow.yaml top-level key '…' is not
  an ARIConfig field — load_config silently drops it (no reader consumes it)`
  for every key outside `ARIConfig.model_fields` ∪
  `KNOWN_NON_CONFIG_TOP_KEYS`. It reaches you through the `warnings` array of
  `GET /api/v1/runs/{run_id}/resolved-config` (which reads the checkpoint's
  copy of `workflow.yaml`) and of the new-run preview (which reads the
  bundled one). It is a listing, not a spelling suggestion, and since nothing
  outside `ari.viz.v1` calls the resolver, a hand-run CLI never sees it.
  Treat its `(no reader consumes it)` wording as unverified: on the bundled
  `workflow.yaml` the only two warnings it emits are for `paper_venue` and
  `paper_rubric`, both of which *are* consumed. The warning proves the key
  missed `ARIConfig`, not that it is inert.
- **Absence is observable in the checkpoint.**
  `{checkpoint}/rqgm_state.json` is written only when `ari.mode: ari_rqgm`
  and `rqgm.enabled: true` both hold (`ari/cli/run.py`), so its absence means
  the run was `simple_bfts`. Confirm that a non-default execution mode
  actually took effect from that file, not from the lack of an error message.

The same filter is what makes the backwards direction safe: a block an
`ari-core` build does not declare as a field is ignored rather than fatal, so
a newer YAML deployed onto an older core degrades to that core's defaults
instead of failing to load.

> ⚠ This precedence is **documented as observed today**, not changed. The
> order is locked by tests (`test_config.py`, `test_default_provider.py`,
> `test_launch_config.py`, `test_settings_*`) before any consolidation. The
> central config-loader that used to be a proposed follow-up now exists for
> the GUI path only — `ari.config.resolver` (`legacy-compatible-1`), described
> in the next section. It **reconstructs** this chain post-hoc; it does not
> replace it, and the CLI still resolves exactly as above.

## Configuration control plane (`/api/v1/config/*`)

The GUI's configuration surface is built on three machine-checked pieces:

1. a **field registry** — the canonical metadata inventory of every declared
   config leaf (`ari-core/ari/config/field_registry.py`);
2. a **resolver** — one function per resolution context that explains where
   each effective value came from (`ari-core/ari/config/resolver.py`);
3. a **document store** — GUI-only project config / run templates / run
   drafts (`ari-core/ari/viz/v1/store.py`).

All three are read-only with respect to the runtime: they never mutate
`ARIConfig`, never write to `os.environ`, and the CLI / `simple_bfts` path
never reads them. They exist so a UI can *explain* configuration; the values
a run actually uses still arrive through the precedence chains above.

### Field registry (canonical field metadata)

`GET /api/v1/config/schema` serves the registry — **metadata only, never an
effective value**. Each entry describes one `ARIConfig` leaf:

| Key | Meaning |
|---|---|
| `path` | Dotted leaf path (`bfts.max_total_nodes`). The stable identity. |
| `value_type` | Rendered pydantic annotation (`int`, `str \| None`, `list[SkillConfig]`, `dict[str, float]`, …). A `Literal` renders as the type of its members (`str`), with the members in `enum`. |
| `default` | The pydantic default (or the default factory's value). Forced to `null` for `secret_reference` leaves. |
| `enum` | The `Literal` members when the annotation is a closed set, else `null`. |
| `required` | Whether the field has no default. |
| `category` | UI grouping: Models, Skills, Search (BFTS), Infrastructure, Evaluation, Execution mode, Governance, Proposal routing, Manuscript completeness, Scientific assurance. |
| `level` | `basic` / `advanced` / `expert` — progressive disclosure. |
| `scope` | `preference` / `installation` / `project` / `template` / `run` — which document may own the value. |
| `sensitivity` | `public` / `internal` / `secret_reference`. |
| `mutability` | `draft` / `new_run_only` / `resume_mutable` / `read_only`. |
| `applies_when` | Dependency predicate (`bfts.frontier_score=depth_penalized`) or `null`. |
| `notes` | Hand-authored caveat (e.g. "yaml_only: no GUI field or `ARI_*` hook"). |
| `source` | `pydantic` — the walk covers declared model fields only. |
| `env_override` | The `ARI_*` variable that overrides this leaf, or `null`. |

**Coverage invariant.** The registry currently has **204 leaves and 100 %
metadata coverage**: `build_field_registry()` raises `LookupError` when any
walked leaf lacks a `FIELD_META` prefix or exact entry, so a new config field
cannot ship without schema metadata. Today's distribution: 104 Governance /
32 Models / 24 Search (BFTS) / 14 Proposal routing / 10 Manuscript
completeness / 5 Infrastructure / 5 Scientific assurance / 4 Evaluation /
4 Execution mode / 2 Skills; 150 expert, 18 advanced, 36 basic;
203 `public` + 1 `secret_reference` (`llm.api_key`); 146 `new_run_only` +
58 `draft`; 20 leaves carry an `env_override`.

Deliberate fidelity limits (documented, not silent):

- Only **declared pydantic fields** are walked. `extra="allow"` YAML blocks
  (`hpc`, `container`, `memory`, `letta`, `claim_gate_policy`,
  `lineage_decision`, …) have no model field and therefore no leaf; their
  `FIELD_META` prefixes are forward-declared for the day they become typed.
- List/dict fields (`skills`, `resources`, `evaluator.axis_weights`,
  `evaluator.custom_axes`) are **single composite leaves** — element paths
  are index-dependent and would not be stable identities.
- The module is pure: no filesystem, no clock, no environment read, no LLM.
  Two builds are byte-identical (P2).

The same registry drives write validation. `PATCH` bodies are
`{"values": {"dotted.path": value}}` and are checked by `validate_patch`,
whose closed rejection vocabulary is `unknown_path`, `secret_reference`,
`read_only`, `not_project_scope`, `invalid_enum`, `invalid_type` plus the
cross-path `mode_interlock_mismatch`. Secrets and `read_only` fields are
rejected for every target; `new_run_only` fields are legitimate in
templates/drafts (they configure future runs) but rejected in the project
config unless their scope is `project`.

**Mode leaves and the interlock rule.** The four `Execution mode` leaves
(`ari.mode`, `rqgm.enabled`, `paper.mode`, `rqgm.paper.enabled`) are
`scope: run`, `mutability: new_run_only`, and form **two pairs** —
`MODE_INTERLOCK_PAIRS` in `field_registry.py`, the single source that
`resolver.INTERLOCK_PAIRS` aliases. A pair is one intent: a document in
which one half appears without its agreeing twin is rejected with
`mode_interlock_mismatch` (`validate_mode_interlocks`, evaluated on the
merged document values, not the raw patch). Since ADR-09 these four are the
only mode/governance leaves a GUI client may write, and only for a new run;
the remaining 104 paths in the `Execution mode` category and the `rqgm.*`
tree stay file-only and are refused by `POST /api/v1/runs` with
`mode_locked` (`viz/v1/launch.py:locked_launch_paths`). Their `applies_when` metadata carries a pairing *note*
("paired with `rqgm.enabled` (one intent — set both)") rather than a
`path=value` gate, because gating either half on the other would make the
interlock self-gating.

The `env_override` column is the literal transcription of the
`apply_*_env_overrides` family in `ari/config/__init__.py`:

| Config leaf | Env variable |
|---|---|
| `llm.model` | `ARI_MODEL` (alias `ARI_LLM_MODEL`) |
| `llm.backend` | `ARI_BACKEND` |
| `llm.base_url` | `ARI_LLM_API_BASE` |
| `checkpoint.dir` | `ARI_CHECKPOINT_DIR` |
| `logging.dir` | `ARI_LOG_DIR` |
| `logging.level` | `ARI_LOG_LEVEL` (auto-config / no-YAML path only) |
| `bfts.max_total_nodes` | `ARI_MAX_NODES` |
| `bfts.max_depth` | `ARI_MAX_DEPTH` |
| `bfts.max_react_steps` | `ARI_MAX_REACT` |
| `bfts.max_parallel_nodes` | `ARI_PARALLEL` |
| `bfts.timeout_per_node` | `ARI_TIMEOUT_NODE` |
| `bfts.frontier_score` | `ARI_FRONTIER_SCORE` |
| `bfts.allow_web` | `ARI_BFTS_ALLOW_WEB` |
| `evaluator.composite` | `ARI_COMPOSITE` |
| `evaluator.axis_mode` | `ARI_AXIS_MODE` |
| `ari.mode` | `ARI_MODE` |
| `rqgm.enabled` | `ARI_RQGM_ENABLED` |
| `paper.mode` | `ARI_PAPER_MODE` |
| `rqgm.paper.enabled` | `ARI_RQGM_PAPER_ENABLED` |
| `rqgm.paper.reviewer.agent_as_judge.enabled` | `ARI_PAPER_AGENT_AS_JUDGE` |

### Resolution model

Both resolution modes report `resolver_version: "legacy-compatible-1"` —
the algorithm identity, versioned separately from the payload
`schema_version`. The initial resolver deliberately *reproduces* today's
imperative precedence rather than improving it.

**A) Existing checkpoint** (`GET /api/v1/runs/{run_id}/resolved-config`) —
explains a run post-hoc without re-running `load_config`:

| # | Layer | `source` | Confidence |
|:--:|---|---|---|
| 1 | pydantic defaults | `default` | high |
| 2 | `{ckpt}/workflow.yaml` (model-field keys) | `workflow` | high |
| 3 | `{ckpt}/launch_config.json` knobs | `launch_config` | high |
| 4 | **current** environment, documented `ARI_*` only | `env` | **low** |
| 5 | `{ckpt}/rqgm_state.json` persisted mode | `checkpoint_state` | high, `mutable: false` |

Layer 4 is low-confidence on purpose: the environment being read is the
*server's* environment now, not necessarily the one the run was launched
with. Layer 5 is immutable because a run's execution mode is fixed at
launch (resume reconciliation is downgrade-only).

**B) New run** (`POST /api/v1/run-drafts/{draft_id}/resolve-config`) —
previews a run that does not exist yet:

| # | Layer | `source` |
|:--:|---|---|
| 1 | pydantic defaults | `default` |
| 2 | **bundled** `config/workflow.yaml` | `workflow` |
| 3 | selected execution profile (`--profile laptop\|hpc\|cloud`) | `profile` |
| 4 | project config document | `project` |
| 5 | run template document | `template` |
| 6 | run draft document | `draft` |
| 7 | documented `ARI_*` env overrides | `env` (confidence low) |

then two closing steps:

- **validated effective** — the merged values are constructed as an
  `ARIConfig`; a value pydantic rejects reverts to the last *valid* layer
  value and is annotated with a `rejected_override` provenance entry plus a
  warning. Rejected or ignored overrides are returned as explanations, never
  silently dropped.
- **interlock resolution** — `ari.mode` + `rqgm.enabled` and `paper.mode` +
  `rqgm.paper.enabled` must agree. The runtime resolves a mismatch as
  *warn + fallback* (`simple_bfts` / `linear`) and the manifest shows the
  **effective** mode. Draft validation
  (`POST /api/v1/run-drafts/{draft_id}/validate`) is stricter: there a
  mismatch is an `interlock_mismatch` **error**, so the GUI refuses to launch
  an inconsistent intent.

> **The 4-key profile merge caveat.** `--profile` does *not* deep-merge the
> profile YAML. `_apply_profile` (`ari/cli/run.py`) merges exactly four keys:
> `bfts.max_total_nodes`, `bfts.max_parallel_nodes` (historical spelling
> `bfts.parallel`, accepted only when `max_parallel_nodes` is absent),
> `hpc.enabled` → `resources.hpc_enabled`, and `hpc.scheduler` →
> `resources.scheduler`. The resolver reproduces that exactly and emits a
> warning listing **every other profile key it ignored**, so a profile knob
> that has no effect is visible instead of invisible. Profiles are also not
> recorded anywhere in the checkpoint — for an existing run their effect is
> only observable through `launch_config.json` / env.

Other deliberate gaps, each surfaced as a warning rather than a silent
difference: `skills` auto-discovery and the `allow_web` phase rewrite are
runtime-only; checkpoint `settings.json` is not an overlay layer (it reaches
a run only through the launch-time env translation, which the
`launch_config` and `env` layers already represent).

### Provenance and confidence

Every resolved leaf carries a provenance entry:

| Field | Meaning |
|---|---|
| `source` | The winning layer. Existing-checkpoint vocabulary: `default`, `workflow`, `launch_config`, `env`, `checkpoint_state`. New-run vocabulary: `default`, `workflow`, `profile`, `project`, `template`, `draft`, `env`. |
| `mutable` | Whether the value can still be changed. In the new-run preview every non-`read_only` field is mutable (before launch even `new_run_only` windows are open); for an existing checkpoint the persisted mode is `mutable: false`. |
| `confidence` | `high` when the source artifact was present; `low` for the environment overlay (and for reconstructed layers) — the launch-time environment may differ from the one being read. |
| `rejected_override` | New-run only: `{source, value, reason, expected}` when a layer's value was rejected by validation and the previous layer's value was kept. |

`source_stack` lists the layers that actually participated. Note the
documented asymmetry: the existing-checkpoint stack always contains `env`
(the overlay is always evaluated), while the new-run stack lists only layers
that were present.

### `resolved_config.json` (the launch manifest)

`POST /api/v1/runs` materializes the previewed manifest into the checkpoint
as `{ckpt}/resolved_config.json` — "the resolved manifest becomes real at
launch". It is additive: `launch_config.json` is still written for the
legacy display path.

```json
{
  "schema_version": 1,
  "resolver_version": "legacy-compatible-1",
  "run_id": "20260726T101500_matmul-9f3a12",
  "resolved_at": "2026-07-26T10:15:00Z",
  "digest": "sha256:1f0c…",
  "source_stack": ["default", "workflow", "profile", "draft"],
  "values":   { "bfts": { "max_total_nodes": 24 }, "...": "..." },
  "provenance": { "bfts.max_total_nodes": { "source": "draft", "mutable": true, "confidence": "high" } },
  "secret_references": { "llm.api_key": { "provider": "env", "configured": true } },
  "warnings": ["profile 'hpc': ignored non-merged keys …"]
}
```

Rules worth knowing:

- **Secrets are excluded, structurally.** Leaves whose registry sensitivity
  is `secret_reference` never appear in `values`, `provenance` or the digest
  input; they surface only as `secret_references` entries carrying
  `{provider, configured}` — there is no value field to leak into.
- **`digest` = `sha256:` over the canonical JSON of `values` alone**
  (`sort_keys=True`, no whitespace, `ensure_ascii=False`). Because secrets
  are already excluded, the digest is computed over the redacted document,
  and environment noise outside the documented `ARI_*` families never moves
  it. Two identical configurations produce the same digest on any machine.
- **No clock inside the resolver.** `resolved_at` is filled by the caller
  from source-file mtimes, never `now()`, so repeated GETs are byte-stable.

### GUI document store (`gui_store/`)

The GUI-only configuration documents live beside the checkpoints, never in a
global home directory:

```
{workspace_root}/gui_store/
├── project_config.json              # the single default project's config
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json  # idempotent-launch records
```

| Property | Contract |
|---|---|
| Envelope | `{"schema_version": 1, "kind": ..., "revision": n, "body": {...}}`, serialized deterministically (`sort_keys`, 2-space indent, trailing newline). |
| `revision` | Per-document integer starting at 1, incremented on every write; it is the `If-Match` token of the HTTP API (`0` means "must not exist yet"). |
| Durability | Same-directory temp file + `fsync` + `os.replace` (+ best-effort directory fsync): a crash mid-write leaves the previous document byte-intact. |
| Permissions | Files `0o600`, store directories `0o700`. |
| IDs | Caller-supplied and validated against `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` — no `/`, no `.`, so path traversal is structurally impossible. Draft ids are server-generated (`draft-<12 hex>`). |
| Root | `RuntimePathResolver.resolve_workspace_root()` — the same policy every workspace consumer uses (`ARI_CHECKPOINT_DIR` wins). |

**The CLI never reads `gui_store/`.** It is a GUI convenience layer:
templates outlive the runs they spawned, and launch materializes every
effective value into the checkpoint exactly as before. Nothing in `ari/`
outside `ari.viz.v1` imports the store.

### Legacy Settings keys: what is actually wired

The legacy `GET/POST /api/settings` surface is frozen (its exact key sets,
default values and save-path behaviour are pinned by
`ari-core/tests/test_gui_baseline_settings_contract.py`), quirks included.
Everything below is **observed, frozen behaviour** — recorded here because
tests depend on it and operators trip over it, not because it is a pattern to
copy. Six points matter when reading the Settings page:

**1. The GET/POST key sets do not match.** `GET /api/settings` returns
exactly **27** top-level keys (26 scalar/list + the nested `ors` object with
10 sub-keys); the Save button POSTs exactly **24** flat keys, and `POST` is a
*whole-file replace* (keys absent from the body are erased from
`settings.json`). 16 keys are shared:

| Only in the POST body (8) | Only in the GET response (11) |
|---|---|
| `llm_backend`, `llm_base_url`, `ssh_host`, `ssh_port`, `ssh_user`, `ssh_path`, `ssh_key`, `slurm_partitions` | `llm_provider`, `ollama_host`, `mcp_skills`, `slurm_gpus`, `vlm_review_enabled`, `vlm_review_max_iter`, `vlm_review_threshold`, `letta_deployment`, `letta_deployment_image`, `letta_deployment_venv`, `ors` |

Consequence: the provider is written as `llm_backend` but read back as
`llm_provider`, which is why the GET merge re-forces `llm_provider` (and
`llm_model`) from `workflow.yaml` when the saved value is falsy — the
"falsy-re-force quirk" noted in the precedence section above.

**2. Some keys are decorative.** They are persisted and rendered, but no
runtime reads them:

| Settings key | Status | Detail |
|---|---|---|
| `temperature` | **dead** | Never exported to the launch environment and no `ARI_*` hook exists; a run keeps the pydantic `llm.temperature` default. (The canonical config API *does* apply the `llm.temperature` leaf — the two paths differ here by design of the freeze.) |
| `container_pull` | **dead on both routes** | Never exported to env and no canonical config leaf exists. |
| `retrieval_backend` | **decorative in `workflow.yaml`** | The value *is* exported as `ARI_RETRIEVAL_BACKEND` at launch, but `retrieval` is an untyped top-level workflow key with no typed leaf — the registry only forward-declares it. |
| `slurm_partition` / `slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` | **seed only** | The SLURM card's values never reach the launch environment. `slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` pre-fill the Wizard's HPC step; the wizard's own values are what get used. |
| `slurm_partitions` | **UI-local** | A Settings-page multiselect state; the Wizard's partition list comes from `GET /api/slurm/partitions` detection instead. |
| `container_mode` / `container_image` / `vlm_review_model` / `letta_*` | **env-only** | Exported as `ARI_CONTAINER_MODE` / `ARI_CONTAINER_IMAGE` / `VLM_MODEL` / `LETTA_*`, but the corresponding workflow blocks are untyped `extra="allow"` sections, so the field registry has no typed leaf for them yet. |
| `letta_api_key` | **frozen defect** | Persisted verbatim into `settings.json` in plaintext. The canonical config API refuses secrets in `values`; use `PUT /api/v1/secrets/{secret_id}` instead. |

**3. The default *values* are frozen too, not just the key names.**
`_api_get_settings` (`ari/viz/api_settings.py`) builds one literal `defaults`
dict and `test_frozen_default_values` pins its contents. Read these as pinned
literals that nothing re-derives — they are not tuned recommendations, and no
runtime consults them to decide anything.

Twenty top-level slots and five `ors` sub-keys are plain constants:

| Key | Frozen value |
|---|---|
| `llm_api_key` | `""` |
| `semantic_scholar_key` | `""` |
| `temperature` | `1.0` |
| `slurm_partition` | `""` |
| `slurm_cpus` | `null` |
| `slurm_memory_gb` | `null` |
| `slurm_gpus` | `0` |
| `slurm_walltime` | `"04:00:00"` |
| `mcp_skills` | `[]` |
| `container_mode` | `"auto"` |
| `container_image` | `""` |
| `container_pull` | `"on_start"` |
| `vlm_review_enabled` | `true` |
| `vlm_review_model` | `"openai/gpt-4o"` |
| `vlm_review_max_iter` | `3` |
| `vlm_review_threshold` | `0.7` |
| `letta_deployment` | `"auto"` |
| `letta_deployment_image` | `""` |
| `letta_deployment_venv` | `""` |
| `letta_api_key` | `""` |
| `ors.rubric_gen_temperature` | `0.0` |
| `ors.rubric_gen_target_leaves` | `0` |
| `ors.rubric_gen_two_stage` | `true` |
| `ors.judge_n_runs` | `3` |
| `ors.phase1_max_runtime_sec` | `21600` |

The remaining six top-level slots and five `ors` sub-keys are **env-first**;
only their fallback is frozen, so do not quote them as constants:

| Key | Read from | Value when that variable is unset |
|---|---|---|
| `ollama_host` | `OLLAMA_HOST` | `"http://localhost:11434"` |
| `retrieval_backend` | `ARI_RETRIEVAL_BACKEND` | `"semantic_scholar"` |
| `letta_base_url` | `LETTA_BASE_URL` | `"http://localhost:8283"` |
| `letta_embedding_config` | `LETTA_EMBEDDING_CONFIG` | `"letta-default"` |
| `ors.replicator_model` | `ARI_MODEL_REPLICATE` | `"claude-opus-4-7"` |
| `ors.rubric_gen_model` | `ARI_MODEL_RUBRIC_GEN` | `"gemini-2.5-pro"` |
| `ors.rubric_audit_model` | `ARI_MODEL_RUBRIC_AUDIT` | `"claude-opus-4-7"` |
| `ors.judge_model` | `ARI_MODEL_JUDGE` | `"gpt-4o-2024-11-20"` |
| `ors.phase1_sandbox_kind` | `ARI_PHASE1_SANDBOX` | `"auto"` |
| `llm_model` | `ARI_LLM_MODEL` | package `workflow.yaml` `llm.model`, else `""` |
| `llm_provider` | `ARI_BACKEND` | package `workflow.yaml` `llm.backend`, else `""` |

Two details the table cannot show. The nine `os.environ.get(VAR, literal)`
slots fall back only when the variable is **absent** — a variable set to the
empty string yields `""`, not the literal. `llm_model` / `llm_provider` use
`os.environ.get(VAR, "") or …` instead, so for those two an empty variable
does fall through. The contract test sees the frozen literals at all only
because its `_clean_env` fixture deletes all eleven variables first; on a
developer shell the payload will differ.

**4. `api_key` never reaches `settings.json` — it goes to a `.env` file and
into the live server process.** `POST /api/settings` pops `api_key` (then
`llm_api_key`) out of the body, and pops both again unconditionally, so
neither is ever persisted. If the value clears the plausibility guard in
point 5 *and* the provider maps to an environment-variable name,
`_upsert_env_key(name, key, quote=False)` runs. That helper:

- rewrites **every** line of the target file whose stripped form starts with
  `NAME=`, and appends the line when there is none. (The helper's own
  docstring says "the first line"; the loop has no early exit, so a file that
  already contains duplicate entries for `NAME` gets all of them rewritten.);
- writes atomically — same-directory `mkstemp`, `fchmod 0o600`, `fsync`,
  `os.replace`, then a best-effort `chmod 0o600`;
- renders the **unquoted** `NAME=value` form. `NAME="value"` (`quote=True`) is
  what the env-key editor and `PUT /api/v1/secrets/{secret_id}` write through
  the same helper. The helper's docstring records that the two callers
  historically differed only by this quoting and that unifying it would be a
  behaviour change;
- and finally sets `os.environ[name] = value` **in the running server
  process**. A settings save mutates the live environment, not only a file.

The write target is the module-global `ari.viz.state._env_write_path`, bound
once at import to the ARI repo root's `.env`. `set_active_checkpoint` rebinds
`_checkpoint_dir` and `_settings_path` and leaves `_env_write_path` alone, and
nothing under `ari/` reassigns it — so this is the **repo-root** `.env`, not
the selected checkpoint's. (The contract test appears to write a
checkpoint-local `.env` only because its fixture monkeypatches that global.)
The canonical route reaches the same file: see
[Configuration Studio](../guides/configuration_studio.md), *How secrets work*.

**5. QUIRK — three ways an api key is discarded in silence.** The whole
`.env` branch hangs off one condition,
`if _raw_key and "test" not in _raw_key and len(_raw_key) >= 20:`, followed by
a provider lookup in an inline dict. There is no `else` branch, no log line
and no field in the response, so in each case below the write is skipped
entirely and — with an active checkpoint — the handler goes on to return
`{"ok": true}`. The operator is told the save succeeded while the credential
was thrown away.

| Discarded when | Detail |
|---|---|
| the key is shorter than 20 characters | `20` is a bare magic number in the condition — no named constant, no configuration knob, no message. |
| `test` appears anywhere in the key | A case-sensitive substring check over the whole key, evaluated before the length check. A real credential that happens to contain those four characters is dropped exactly like a placeholder, while `TEST` is not matched at all. |
| the provider is not in the map | The map is `openai` → `OPENAI_API_KEY`; `anthropic`, `claude_code` and `claude-code` → `ANTHROPIC_API_KEY`; `gemini` → `GOOGLE_API_KEY`. Five spellings, three variables. `.get(provider, "")` yields `""` for anything else — `ollama`, vLLM, every other OpenAI-compatible `base_url` backend — and the write is skipped. |

These are length and substring heuristics that the tests pin. They are not
validation and they are not secret detection; do not present them as either.
The map is also the route's whole reach: `GEMINI_API_KEY`,
`SEMANTIC_SCHOLAR_API_KEY`, `LETTA_API_KEY`, `ZENODO_TOKEN` and
`ARI_REGISTRY_TOKEN` are all in the v1 secrets allowlist
(`ari/viz/v1/secrets.py`) and none of them is reachable from here.

One consequence of quirk 1 lands on this path. The provider name is read as
`data.get("llm_provider", "") or data.get("llm_backend", "")`, and the
frontend's 24-key Save body carries `llm_backend` and no `llm_provider` — so
every save from the real Settings page resolves its provider through the
*fallback* arm. That fallback is the only reason the GUI can configure a key
at all; with both keys absent or falsy the provider is `""`, which maps to
`""`, and the key is dropped.

**6. QUIRK — a refused save is not a no-op.** `_api_save_settings` runs in
this order: parse body → `retrieval_backend` guard → api-key pop and `.env`
upsert → active-checkpoint check → `settings.json` write. The two refusals
therefore differ in what they leave behind:

| Refusal (`_status` 400 in both cases) | Side effect |
|---|---|
| `{"ok": false, "error": "retrieval_backend must select one pinned provider"}` — the body carries a `retrieval_backend` that is not one of `semantic_scholar`, `arxiv`, `alphaxiv` (an absent key passes) | None. It returns before the key is read. |
| `{"ok": false, "error": "No active project. Create or select a checkpoint before saving settings."}` — `state._settings_path` is `None` | The key has **already** been written to `.env` and exported into `os.environ`. `_env_write_path` is separate state from `_settings_path`, so it stays writable with no checkpoint selected. |

The second row is the one to remember: a 400 from this endpoint does not mean
"nothing happened" — the secret is on disk and in the process either way.
Frozen as-is; reordering the handler would be a behaviour change.

The overlap between the 24 POST keys, the legacy launch env exports and the
canonical config leaves — including every divergence above — is asserted
literally by `ari-core/tests/test_gui_config_shadow_legacy.py`.

## workflow.yaml (Canonical Developer Config)

`workflow.yaml` is the **single source of truth** for the full ARI pipeline.
Place it at `ari-core/config/workflow.yaml`.

Use `{{ari_root}}` in skill paths — it resolves to `$ARI_ROOT` env var or the project root.

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Autonomous Research Infrastructure"

resources:
  cpus: 48                 # Default CPU count for reproducibility experiments
  timeout_minutes: 60      # Default job timeout
  executor: slurm          # Job executor: slurm / local / pbs / lsf

# BFTS phase stages (executed in order during tree search)
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: ''                   # display-only row: evaluation is owned by
                               # ari-core's in-process LLMEvaluator, not an
                               # MCP tool
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS pipeline stages
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: search_papers
    params:
      provider: semantic-scholar
      max_results: 15
      mode: record
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      primary_metric: '{{primary_metric}}'
      higher_is_better: '{{higher_is_better}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures, generate_ear]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  # ─── EAR curation/publishing/finalization ── (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate, ear_publish,
                 claim_evidence_hard_gate_final]
    # Auto-loads ref/sha/doi from ear_published/manifest.lock and
    # publish_record.json; injects \codeavailability/\codedigest/\coderef
    # macros into full_paper.tex. Skips silently when no curated bundle.
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # Post-hoc structural merge of text + VLM reviewer outputs (no LLM).

  # Re-hash node artifacts against their recorded sha256 before any of them
  # become paper evidence. {{run_id}}/{{experiments_root}} are resolved by the
  # pipeline driver from checkpoint_dir (tree.json wins over the dir name).
  - stage: audit_node_provenance
    skill: memory-skill
    tool: audit_memory
    depends_on: []
    inputs:
      experiments_root: '{{experiments_root}}'
      run_id: '{{run_id}}'
  # ─── ORS auto-rubric reproducibility (PaperBench, v0.7.0) ───
  # Replaces the legacy `reproducibility_check` stage.
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [lock_paper_build]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = auto from paper length
  - stage: ors_audit_rubric    # quality audit of the rubric everything is graded against
    skill: replicate-skill
    tool: audit_rubric
    depends_on: [ors_generate_rubric]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'   # rewritten in place with flags
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
  - stage: ear_publish          # v0.7.0+: enabled by default with local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # zero-deps; writes bundle.tar.gz next to ckpt
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+: deterministic seed from EAR bundle
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # auto-load ref from publish_record.json
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+: LLM fallback (skips if seeded above)
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_audit_rubric, ors_seed_sandbox, lock_paper_build]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1 (sandbox-execute reproduce.sh)
    depends_on: [ors_audit_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = use rubric.reproduce_contract.max_runtime_sec
      partition: ''            # blank → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # blank → ARI_SLURM_CPUS (default 8)
      walltime: ''             # blank → ARI_SLURM_WALLTIME → derived from timeout
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2 (PaperBench SimpleJudge via LiteLLM)
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 0                # 0 / '' defer to the MCP tool's own defaults
      judge_model: ''          # (ARI_JUDGE_N_RUNS / ARI_MODEL_JUDGE)

retrieval:
  backend: semantic_scholar    # semantic_scholar | arxiv | alphaxiv (ONE
                               # pinned provider per call; the composite
                               # `both` value is now refused by the web
                               # skill's `_provider_name`)
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── Paper review (rubric-driven, AI Scientist v1/v2-compatible) ────────
# Override via CLI (--rubric, --fewshot-mode, --num-reviews-ensemble,
# --num-reflections) or environment variables (ARI_RUBRIC,
# ARI_FEWSHOT_MODE, ARI_NUM_REVIEWS_ENSEMBLE, ARI_NUM_REFLECTIONS).
# Bundled rubrics (23 YAMLs in ari-core/config/reviewer_rubrics/):
#   neurips (default, v2-compatible) | iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
#   | aer | ahr | apsr | econometrica | philreview | pmla | qje
# Plus the built-in `legacy` fallback (v0.5 schema). Add new venues by
# dropping <id>.yaml into reviewer_rubrics/ — no code changes required.
#
# `prompt_overrides.author_hint` is the inverse of system_hint: it's
# injected into the paper-drafting system prompt by
# `write_paper_iterative`, as a `VENUE RUBRIC AUTHOR GUIDANCE` block,
# so writing is venue-conditioned at the same strength as peer review.
# SC and NeurIPS ship calibrated hints; when the hint is empty the
# block is simply omitted.
#
# PaperBench rubric templates (separate venue YAMLs for the rubric
# generator) live under ari-core/config/paperbench_rubrics/. See
# docs/reference/rubric_schema.md#venue-conditioned-templates for the
# YAML schema; shipped templates: generic | sc | neurips | nature.
#
# Few-shot corpus management
# --------------------------
# Files under reviewer_rubrics/fewshot_examples/<rubric>/ may be managed
# from the GUI (New Experiment Wizard → Paper Review → Few-shot Examples)
# or scripts/fewshot/sync.py. REST endpoints exposed by the viz server:
#   GET  /api/rubrics                         list rubrics (Wizard dropdown)
#   GET  /api/fewshot/<rubric>                list fewshot examples
#   POST /api/fewshot/<rubric>/sync           pull entries from manifest.yaml
#   POST /api/fewshot/<rubric>/upload         upload one example (JSON body)
#   POST /api/fewshot/<rubric>/<example>/delete  remove one example
# All four endpoints reject unknown rubrics and strip ../ sequences.

memory:
  # v0.6.0: Letta is the sole production backend; values here are
  # exported into the skill subprocess env at load time. The agent's
  # chat LLM handle is hardcoded to `letta/letta-free` because
  # ari-skill-memory only ever calls archival_insert / archival_search
  # — no chat messages — so the picker had no runtime effect.
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # Container image name (empty = no container)
  pull: on_start               # always | on_start | never

skills:
  # `phase` controls which pipeline-phase ReAct agents see the skill's
  # MCP tools. A single string opts the skill into exactly one phase;
  # a list opts it into several. Skills tagged `reproduce` are exposed
  # to any future stage that opts in via a `react:` block. The default
  # v0.7.0 workflow no longer routes the reproducibility check through
  # `react_driver` — it uses the deterministic PaperBench Phase 1 +
  # Phase 2 chain (`ors_run_reproduce` / `ors_grade`) instead.
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: bfts
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
  # v0.7.0: PaperBench-format auto-rubric generator + auditor.
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum BFTS nodes to explore (hard cap; pruning predicate input) | `50` |
| `ARI_MAX_DEPTH` | Hard cap on BFTS tree depth (activated in v0.7.2) | `5` |
| `ARI_PARALLEL` | Concurrent node execution | `1` |
| `ARI_EXECUTOR` | Execution backend: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | (none) |
| `ARI_SLURM_CPUS` | Override CPU count for SLURM jobs | (auto-detected) |
| `SLURM_LOG_DIR` | Where SLURM output files go | (none) |
| `OLLAMA_HOST` | Ollama server address | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API key | (none) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (none) |
| `ARI_RETRIEVAL_BACKEND` | Paper search backend: `semantic_scholar`, `alphaxiv`, `both` | `semantic_scholar` |
| `VLM_MODEL` | VLM model for figure review | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | HTTP port for orchestrator skill | `9890` |
| `LETTA_BASE_URL` | Letta server endpoint | `http://localhost:8283` |
| `LETTA_API_KEY` | Required for Letta Cloud; optional for self-hosted | (none) |
| `LETTA_EMBEDDING_CONFIG` | Embedding handle Letta uses for archival memory (the agent's chat LLM is hardcoded to `letta/letta-free` since ARI never invokes it) | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | Per-call timeout (viz + skill) | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | Over-fetch size for the post-filter ancestor-scope fallback | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Keep Letta self-edit off so CoW holds | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `on` / `off` — enable `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore `memory_backup.jsonl.gz` on `ari resume` | `true` |
| `ARI_CURRENT_NODE_ID` | Runtime-only; set by ari-core per-node to enforce write-side CoW | (runtime) |
| `ARI_MODEL_RUBRIC_GEN` | Generator LLM for `ari-skill-replicate.generate_rubric` (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | Auditor LLM for `audit_rubric` (independent of generator) | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | Override per-paper target leaf count consumed by `generate_rubric`. `0`/unset → auto from paper length (~1 leaf / 75 words, clamped to [50, 400]). Set by the GUI Wizard's "Target leaves" field. | (unset) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | Override generator temperature. Set by the GUI Wizard's "Temperature" field. | (unset) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | Force the rubric generator's two-stage path on/off (`1`/`true`/`on` vs `0`/`false`/`off`). Two-stage = skeleton + parallel subtree calls; produces ~4× more leaves and 1–2 levels more depth than a single call at ~5× more API tokens. Unset → kwarg default (currently on). Set by the GUI Wizard's "Two-stage generation" toggle. | (unset, default on) |
| `ARI_PAPERBENCH_RUBRIC_DIR` | Override the search root for venue-conditioned PaperBench rubric templates. The loader checks this dir first, then `<cwd>/ari-core/config/paperbench_rubrics/`, `<cwd>/config/paperbench_rubrics/`, and the repo-relative fallback. Unset → built-in defaults. | (unset) |
| `ARI_MODEL_REPLICATE` | Replicator LLM for `build_reproduce_sh` (paper → reproduce.sh, v0.7.0) | `claude-opus-4-7` |
| `ARI_MODEL_JUDGE` | Judge LLM for `grade_with_simplejudge` (PaperBench Phase 2, v0.7.0; routed via LiteLLM, any provider OK) | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | LLM judge for `decide_lineage_action` (lineage decision, v0.7.0). Falls through `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` | (auto) |
| `ARI_MODEL_ROOT_SELECT` | LLM that picks `ideas[0]` from the VirSci pool (lineage decision, v0.7.0). Same fallback chain as `ARI_MODEL_LINEAGE` | (auto) |
| `ARI_RUBRIC` | Rubric id read by the BFTS dynamic axis evaluator (Phase 3, v0.7.0) and by the lineage-decision thresholds. Reads `ari-core/config/reviewer_rubrics/<id>.yaml`. The paper review no longer reads it: `review_paper` takes an explicit `rubric_id` from `workflow.yaml`'s top-level `paper_rubric`, and `resolve_rubric` refuses an empty id rather than falling back to the environment | `neurips` |
| `ARI_PHASE1_SANDBOX` | Phase 1 sandbox: `auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_PHASE1_DOCKER_IMAGE` | Container image for the docker sandbox runner | `ubuntu:24.04` |
| `ARI_PHASE1_APPTAINER_IMAGE` / `ARI_PHASE1_SINGULARITY_IMAGE` | Image for the Apptainer/Singularity sandbox runner | `docker://ubuntu:24.04` |
| `ARI_SLURM_WALLTIME` | `--time` HH:MM:SS for the SLURM Phase 1 sandbox (v0.7.0, restored). Falls back to a value derived from the rubric's `max_runtime_sec`. | (auto) |
| `ARI_PUBLISH_DRYRUN` | Force `ari ear publish --dry-run` (CI safety, v0.7.0) | (off) |
| `ARI_REGISTRY_DATA` | sqlite + artifact storage root for `ari registry serve` | (none — must be set explicitly; the pre-v0.5 `$HOME/.ari/registry-data` fallback emits a `DeprecationWarning` and is removed in v1.0) |
| `ARI_REGISTRY_TOKEN` | Bearer token for `ari clone ari://...` / `ari ear publish --backend ari-registry` | (none) |
| `ARI_REPRO_CLONE_POLICY` | Git-shim policy in the reproducibility sandbox: `passthrough` / `deny` / `warn` | `passthrough` |

## Memory backend (Letta)

v0.6.0 replaces the deterministic JSONL memory store with
[Letta](https://docs.letta.com). Letta runs in one of four modes:

| Mode | Requirement | Store | Notes |
|------|-------------|-------|-------|
| Docker Compose | `docker` + `docker compose` | Postgres | Laptop default, pre-filter supported |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC default; SLURM-aware data dir |
| pip (container-less) | Python 3.10+ | SQLite | Falls back to over-fetch + post-filter ancestor scoping |
| Letta Cloud | API key | Managed | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` auto-detects the best mode; you can force one via
`ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`. Start/stop/health/backup/restore
are handled by the `ari memory` subcommand — see
`docs/reference/cli_reference.md`.

One-shot migration for a v0.5.x checkpoint:

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM Backends

### Ollama (local, recommended for offline HPC)

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### Claude Code (claude_code)

Drives a local Claude Code installation as a stateless LLM API (no tools, no
MCP, no memory, no session reuse). Full reference:
[claude_code_provider.md](./claude_code_provider.md).

```yaml
llm:
  backend: claude_code
  model: claude-sonnet-5
  claude_code:
    mode: strict_reproducibility   # or low_overhead (Agent SDK worker)
    max_turns: 1
    timeout_sec: 300
    record_provenance: true
    # bare: true                   # default auto: true iff ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN set
    # structured_output_transport: prompt   # or native (--json-schema)
```

Env overrides: `ARI_CLAUDE_CODE_MODE`, `ARI_CLAUDE_CODE_MODEL`,
`ARI_CLAUDE_CODE_MAX_TURNS`, `ARI_CLAUDE_CODE_TIMEOUT_SEC`,
`ARI_CLAUDE_CODE_RECORD_PROVENANCE`, `ARI_CLAUDE_CODE_BIN`. Health check:
`ari doctor claude-code [--live]`. Notes: MCP skills do NOT run through
Claude Code on this backend — their direct litellm calls route to the plain
Anthropic API (`ANTHROPIC_API_KEY` required) — and ReAct agent phases need a
tool-calling backend (the provider fails loudly when `tools=` is passed).

### Any OpenAI-compatible API (vLLM, LM Studio, etc.)

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## Template Variables in workflow.yaml

Any value in `inputs:` supports `{{variable}}` substitution:

| Variable | Value |
|----------|-------|
| `{{ckpt}}` | Checkpoint directory path |
| `{{checkpoint_dir}}` | Same value as `{{ckpt}}` (both are bound; most stages use this spelling) |
| `{{run_id}}` | The run's id. Read from `{checkpoint_dir}/tree.json` when present, else the directory name — `ari resume` can repoint `checkpoint.dir` at a renamed directory, and the two then differ |
| `{{experiments_root}}` | `{workspace_root}/experiments` — the per-node scratch tree, a SIBLING of `checkpoints/`, resolved via `ari.paths.PathManager`. Node dirs are `{{experiments_root}}/{{run_id}}/<node_id>/` |
| `{{ari_root}}` | ARI project root (`$ARI_ROOT` or auto-detected) |
| `{{llm.model}}` | LLM model name from `llm:` section |
| `{{llm.base_url}}` | LLM base URL from `llm:` section |
| `{{resources.cpus}}` | CPU count from `resources:` section |
| `{{resources.timeout_minutes}}` | Timeout from `resources:` section |
| `{{stages.<name>.outputs.file}}` | Output file path of a completed stage |
| `{{author_name}}` | Author name from top-level config |
| `{{vlm_feedback}}` | VLM review feedback (injected on loop-back from `vlm_review_figures`) |
| `{{paper_context}}` | Science-facing experiment summary |
| `{{keywords}}` | LLM-generated search keywords |

---

## skip_if_exists Validation

Stages with `skip_if_exists` will **re-run** if the output file:
- Does not exist
- Is empty
- Is a JSON file containing an `"error"` key at the top level

This prevents broken outputs from silently blocking downstream stages.

---

## Plan Promote (v0.7.0+)

`plan_promote` controls how VirSci's experiment plan is materialised into
the in-checkpoint `experiment.md`. The user's source `experiment.md`
(passed on the CLI) is **never** modified — only the in-checkpoint copy
gets the auto-appended block, between HTML comment markers so re-runs
are idempotent.

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | Block contents | Typical size |
|---|---|---|
| `full` | Selected idea + every plan §-tag body + alternatives | ~5 KB |
| `index_only` (default) | Selected idea + plan §-tag titles + alternatives | ~1.5 KB |
| `off` | (no auto-append) | 0 |

The Phase 3 evaluator and the BFTS expand idea-context both read the
**raw** plan from `idea.json`, so the choice between `full` and
`index_only` is mostly cosmetic — it decides what humans (and
paper-skill) see in `experiment.md`.

## Lineage Decision Hook (v0.7.0+)

When a BFTS run stagnates, an LLM judge decides whether to keep
exploring, switch to one of the alternative ideas, fan out to a
parallel child run, or terminate the lineage. The judge is constrained
to four actions, every output is validated against the alternatives
pool, and any error degrades silently to `continue` so the BFTS loop
never blocks on this hook.

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5            # composite-score window
  stagnation_threshold: 0.05      # max-min < threshold ⇒ stagnant
  min_nodes_before_decision: 3    # never fire on the very first nodes
  rate_limit_per_run: 5           # cap escalations per run
```

| Mode | Trigger | Cost |
|---|---|---|
| `off` | never | 0 |
| `stagnation_rule` (default) | composite scores flat for `stagnation_window` consecutive nodes | 0–`rate_limit_per_run` LLM calls per run |
| `every_node` | every BFTS step (LLM also decides timing) | 1 LLM call per node |

Every fired decision (including `continue`) is appended to
`{checkpoint}/lineage_decisions.jsonl` so post-hoc analysis can
correlate lineage actions with outcome quality. The same file holds
`root_idea_selection` records (different `trigger` field) so a single
log captures all lineage decisions LLM judgements.

## Root Idea Selection (v0.7.0+)

After VirSci writes `idea.json`, an LLM picks which entry should be the
run's root, given the venue rubric and the ancestor research thread.
The default keeps VirSci's score-based ordering (`ideas[0]`); an
out-of-range LLM choice falls back to the same default. One LLM call
per run start; no per-node cost.

```yaml
root_idea_selection:
  enabled: true                   # default v0.7.0+
```

The decision is logged to `lineage_decisions.jsonl` as
`{trigger: "root_idea_selection", action: "root_swap" | "root_keep"}`
and persisted in `idea.json` as `_root_choice`. Children (recursion)
detect either marker and skip re-selection.

## Claim Gate Policy (v0.7.0+)

`claim_gate_policy` is the top-level block that governs the
claim–evidence hard gate (Story2Proposal Phase B3). The gate stages run
on every paper build and are wired with `{{claim_gate_policy}}`; the
block is loaded by `ari-core/ari/pipeline/claim_gate/policy.py`.

```yaml
claim_gate_policy:
  mode: warn                  # off | warn | strict
  comparison_scope: any       # any | same_environment
  numeric_coverage:
    target_sections:
      strict: [abstract, results, conclusion]
      warn: [introduction, discussion, limitations]
      excluded: [related_work, references, appendix, equations]
  numeric_match:
    default_tolerance: {absolute: 0.0, relative: 0.02}
  blocking:
    block_on: [numeric_mismatch, operand_unresolved, missing_evidence]
```

`mode` controls blocking (env `ARI_CLAIM_GATE_MODE` overrides it):

| Mode | Behaviour |
|---|---|
| `off` | Never blocks. |
| `warn` (default) | Blocks the **final** gate only on the objective-integrity `always_block_on` tier below; every other finding is reported and never blocks `finalize_paper`. |
| `strict` | The **final** gate additionally blocks (`finalize_paper` is skipped) when a `block_on` error exists, and uncovered result numbers in the strict sections become blocking. The draft gate never blocks. |

`comparison_scope` is the injected research intent (env
`ARI_COMPARISON_SCOPE` overrides it):

| Scope | Cross-environment comparison |
|---|---|
| `any` (default) | Transparency **warning** — correct for cross-architecture studies where the cross-host comparison is the contribution. |
| `same_environment` | **Blocking** error — correct for single-architecture optimization studies. |

`numeric_coverage.target_sections` lists, per gate severity, which paper
sections are checked for numeric claims (`strict`/`warn`) and which are
ignored (`excluded`). `numeric_match.default_tolerance` is the
match tolerance applied when a claim carries no per-claim tolerance:
`absolute: 0.0`, `relative: 0.02` (2%). `blocking.block_on` is the list
of finding types that block the final gate under `strict`:
`numeric_mismatch`, `operand_unresolved`, `missing_evidence`.

> A separate set of **objective-falsehood** finding types
> (`invariant_violation`, `correctness_failed`, `correctness_uncovered`,
> `placeholder_denominator`, `recompute_mismatch`, `claim_evidence_missing`,
> `ceiling_unmeasured`, `contract_expr_unevaluable`, `cross_run_evidence`,
> `cross_run_or_unknown_node`, `cross_run_artifact`,
> `artifact_digest_mismatch`, `artifact_not_bound`,
> `invalid_measurement_contract`) blocks the final paper **regardless** of
> `mode`, except under `off`, which never blocks. These defaults live in
> `policy.py`'s `blocking.always_block_on` and are not set in
> `workflow.yaml`.

## BFTS Tuning

Control BFTS behavior via environment variables:

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_MAX_DEPTH=5       # Hard depth cap (v0.7.2: now actually enforced)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

`BFTSConfig` (defined in `ari/config/__init__.py`) exposes the full set of
knobs:

| Field | Default | Notes |
|-------|---------|-------|
| `max_depth` | 5 | Hard cap on depth (`ARI_MAX_DEPTH`). Activated in v0.7.2 (B-2). |
| `max_total_nodes` | 50 | Hard cap on node count (`ARI_MAX_NODES`). |
| `max_react_steps` | 20 | Per-node ReAct iteration cap (`ARI_MAX_REACT`). Lowered from 80; the field's own description in `ari/config/__init__.py` records the step-count measurement behind the new value. |
| `timeout_per_node` | 7200 | Per-node wall-time budget (s). |
| `max_parallel_nodes` | 4 | Worker concurrency. |
| `max_expansions_per_node` | 4 | New in v0.7.2 (B-6). After N expansions of the same frontier node, BFTS retires it. |
| `label_saturation_threshold` | 2 | New in v0.7.2 (L-6). When ≥ N children of one parent share a label, the next expand prompt flags the label as saturated. |
| `allow_web` | false | Opt-in: expose `web-skill` to the node agent **during exploration** (`ARI_BFTS_ALLOW_WEB`). Default-off keeps the search loop reproducible (P5); when on, ARI records `bfts_web_provenance.json` flagging the trajectory non-reproducible. `idea-skill`'s `survey` already does a bounded literature lookup regardless. |

The pre-audit `max_retries_per_node` field has been **removed** in v0.7.2
(B-3 / B-10) — ARI never retries; failed nodes produce DEBUG children
instead. YAML configs that still set `max_retries_per_node` are ignored
silently (Pydantic `extra='ignore'`).

---

## BFTS Evaluation Layers (configurable)

The BFTS pipeline has four evaluation layers, each independently selectable
through `default.yaml` (or a custom YAML). Defaults reproduce the
pre-existing behaviour, so an unmodified config is a no-op.

```yaml
bfts:
  frontier_score: scientific_plus_diversity   # how the fallback selector ranks frontier nodes
  depth_penalty_lambda: 0.05                  # used by frontier_score=depth_penalized
  ucb_c: 0.5                                  # used by frontier_score=ucb_like
  select_prompt: orchestrator/bfts_select               # LLM prompt for select_next_node
  expand_select_prompt: orchestrator/bfts_expand_select # LLM prompt for select_best_to_expand

evaluator:
  composite: harmonic_mean   # formula used to collapse per-axis scores → _scientific_score
  axis_mode: dynamic         # which axis set to send to the judge LLM
  custom_axes: []            # consulted only when axis_mode=custom
  axis_weights: { ... }      # unchanged; per-axis weight overrides
```

### Layer A — `evaluator.composite`

Selects the formula used to collapse the per-axis judge scores into the
scalar `_scientific_score` stored on each node (see
`ari/evaluator/llm_evaluator.py`). The composite is also what drives
ranking, lineage decisions, and report best-of selection.

| Value | Behaviour |
|-------|-----------|
| `harmonic_mean` (default) | Weighted harmonic mean. Heavily penalises any single weak axis — reproduces the pre-audit behaviour. |
| `arithmetic_mean` | Weighted arithmetic mean. Axes trade linearly; permissive. |
| `weighted_min` | Returns the lowest axis (bottleneck view). Weights gate which axes participate; they do not scale the score. |
| `geometric_mean` | Weighted geometric mean — between harmonic and arithmetic in how harshly it punishes weak axes. |

### Layer B — `bfts.frontier_score`

Strategy used by BFTS's **deterministic** fallback when the LLM selector
cannot pick a candidate (`_select_fallback` in
`ari/orchestrator/bfts.py`). The LLM selector itself is unchanged.

| Value | Score expression |
|-------|------------------|
| `scientific_plus_diversity` (default) | `_scientific_score + diversity_bonus` |
| `scientific_only` | `_scientific_score` (no diversity tiebreaker) |
| `depth_penalized` | `_scientific_score + diversity_bonus − λ·depth`, where `λ = bfts.depth_penalty_lambda` |
| `ucb_like` | `_scientific_score + diversity_bonus + c · √(log N / (visits + 1))`, where `c = bfts.ucb_c`, `visits` is the number of times the node has been expanded, and `N = total_visits + frontier_size` |

`depth_penalty_lambda = 0.0` reduces `depth_penalized` to the default
strategy; `ucb_c = 0.0` reduces `ucb_like` to the default strategy.

### Layer C — `evaluator.axis_mode`

Decides which axis set the judge LLM is asked to score against.

| Value | Source of axes |
|-------|----------------|
| `dynamic` (default) | Generic 5-axis floor + axes derived from the active rubric (`ARI_RUBRIC`) + plan-keyword axes lifted from `idea.json`. Refreshes automatically when `idea.json` changes mtime. |
| `legacy` | The fixed 5-axis canonical set (`measurement_validity`, `comparative_rigor`, `novelty`, `reproducibility`, `clarity_of_contribution`). No rubric / plan input. |
| `custom` | Uses `evaluator.custom_axes` verbatim. |

`custom_axes` is a list of `{name, description, weight}` records; the
`description` is sent to the judge LLM so it knows what each axis means:

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: speedup
      description: "Wall-clock speedup vs. baseline (1.0 = no change)."
      weight: 0.5
    - name: accuracy
      description: "Numerical accuracy preserved within tolerance."
      weight: 0.5
```

When `axis_mode=custom`, the names listed under `axis_weights` are *not*
automatically translated to the custom axis set — duplicate the new
names there if you want to override the per-axis weight from the YAML
weights table.

### Layer D — `bfts.select_prompt` / `bfts.expand_select_prompt`

Each value is a [`FilesystemPromptLoader`](../../ari-core/ari/prompts/_loader.py)
key (path relative to `ari-core/ari/prompts/`, without `.md`). The
defaults point at the shipped templates.

A user-supplied template must declare the same placeholders the BFTS
formatter uses:

- `select_prompt`: `{experiment_goal}`, `{memory_context}`, `{candidates}` — the LLM must reply with a single 0-based integer index.
- `expand_select_prompt`: `{experiment_goal}`, `{candidates}` — same reply format.

When the file at the configured key is missing, `FilesystemPromptLoader`
raises immediately (fail-fast); there is no silent fallback.

### Quick recipes

- **Permissive scoring + UCB exploration:**
  ```yaml
  evaluator: { composite: arithmetic_mean }
  bfts: { frontier_score: ucb_like, ucb_c: 1.0 }
  ```
- **Bottleneck scoring (publish only when *every* axis is good):**
  ```yaml
  evaluator: { composite: weighted_min }
  ```
- **Pin the judge to the canonical 5 axes (legacy reproduction):**
  ```yaml
  evaluator: { axis_mode: legacy }
  ```

---

## Execution Mode and RQGM Governance (opt-in)

ARI has two execution modes.  `simple_bfts` is the default and is
unchanged — a config with no `ari:` / `rqgm:` blocks (i.e. every pre-RQGM
config) behaves exactly as before and never loads an `ari.rqgm` module.
`ari_rqgm` opts in to Constitutional ARI-RQGM epoch governance.  See
[Execution Modes](../guides/execution_modes.md) for the semantics and
[RQGM Schema Reference](rqgm_schemas.md) for the records it persists.

All `rqgm.*` / `proposal_router.*` defaults below live in
`ari-core/ari/configs/defaults.yaml` and mirror the typed Pydantic models
in `ari-core/ari/config/__init__.py` (parity between the two homes is
pinned by the `ari-core/tests/test_rqgm_*.py` suites).  Every block is
structurally inert unless the mode is active; unknown later-version keys
parse warn-free (`extra: allow`).

### Activation: `ari.mode` + `rqgm.enabled`

```yaml
ari:
  mode: simple_bfts     # simple_bfts | ari_rqgm  (master switch)
rqgm:
  enabled: false        # redundant safety interlock
```

Both keys must agree; any disagreement fails safe to `simple_bfts` with a
warning (`ari.rqgm.mode.resolve_effective_mode`).  Environment overrides
(applied after profiles, so an explicit env choice wins over YAML):
`ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} and `ARI_RQGM_ENABLED` ∈
{`0`,`1`,`true`,`false`}; invalid values warn and are ignored.  There is
no `--mode` CLI flag, and profiles (`--profile`) do not merge RQGM keys.
The dashboard's Configuration Studio can set this pair (and the
`paper.mode` pair) for a **new** run — one control writes both keys — but
no surface can change the mode of a run that already exists, and the
remaining `rqgm.*` parameters stay configuration-file only (ADR-09; see
[Execution modes](../guides/execution_modes.md)).

Four optional environment pins make the execution fingerprint more
specific. When any is absent the epoch records it as `unresolved` and
`execution_identity.complete` is `false`; ARI does not claim that a mutable
provider alias is reproducible.

| Variable | Identity it pins |
|---|---|
| `ARI_MODEL_REVISION` | Exact provider/model weight or deployment revision |
| `ARI_TOOL_BUNDLE_REVISION` | Immutable tool bundle revision |
| `ARI_ENVIRONMENT_DIGEST` | Container or resolved environment digest |
| `ARI_DATA_SNAPSHOT_DIGEST` | Immutable external-data snapshot |

### `rqgm.epoch` — epoch-boundary sizing

| Key | Default | Meaning |
|---|---|---|
| `boundary` | `node_count` | Boundary trigger kind; v1 supports only `node_count`. |
| `nodes_per_epoch` | `10` | New BFTS nodes after which the boundary transaction fires; `<= 0` disables automatic boundaries (the run stays in `epoch_000`). |

### `rqgm.kernel` — ConstitutionalKernel posture

Numeric tolerances and posture only — the rule tables are frozen code
(`ari/rqgm/kernel_rules.py` + `ari/rqgm/transition_rules.py`), never
config.

| Key | Default | Meaning |
|---|---|---|
| `enforcement` | `standard` | `standard` applies the blocking matrix; `audit_only` downgrades every context to warn-and-log (staged rollout / ablations). Read at run start / epoch boundaries only. |
| `audit_chain` | `auto` | Chain-verification posture; v1: only `auto` (verify the hash chain iff chain fields are present). |
| `float_tolerance` | `1.0e-9` | Single float-comparison tolerance used by kernel checks. |

### `rqgm.governance` — GovernanceOrchestrator budgets and posture

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Epoch-boundary governance audit on/off inside `ari_rqgm` (ablation rungs run `ari_rqgm` with governance off). |
| `default_level` | `1` | Default per-epoch governance level stamped into the report. |
| `full_governance_only_on_top_k` | `3` | Full adversary/defender/judge attention only for the top-k nodes. |
| `judge_on_disputed_only` | `true` | Per-node adversarial round **only**: when the budget gate denies the Defender call, the uncontested attack lapses as a logged observation instead of reaching the per-node `ArtifactJudge` (`ari/rqgm/adversarial/round.py`). It does **not** gate the epoch-boundary `GovernanceJudge` — the `audit_epoch` adjudication step never reads this key. |
| `impeachment_only_at_epoch_boundary` | `true` | Declarative only — **no code path reads this key**. Motions are filed only inside `audit_epoch` because that is the facade's only motion entry point, a structural property rather than a switch. Setting it `false` does not enable mid-epoch motions. |
| `max_llm_calls_per_audit` | `12` | Hard cap per `audit_epoch`; past it every step degrades to its deterministic fallback. |
| `max_defender_calls_per_epoch` | `12` | Per-epoch Defender LLM-call cap (the adversary cap lives only in `rqgm.adversarial.max_adversary_calls_per_epoch`). |
| `max_judge_calls_per_epoch` | `8` | Per-epoch Judge LLM-call cap. |
| `low_confidence_threshold` | `0.4` | Reviewer confidence below this marks the node disputed. |
| `novelty_claim_threshold` | `0.8` | Novelty axis at/above this (or non-empty novelty risks) triggers the contested tier. |
| `max_motions_per_epoch` | `2` | Hard cap on impeachment motions per epoch. |
| `bond_units_per_motion` | `1` | Legacy field name for motion-quota units. Counters are returned on upheld and consumed on dismissed; no value is transferred. |
| `jury_panel_enabled` | `false` | JuryPanel (multi-sample judge aggregation); off in v1. |
| `fail_mode` | `open` | v1: only `open` — degrade to a no-action report, never block the run loop. |

### `rqgm.replay` — replay/anchor case sizing

| Key | Default | Meaning |
|---|---|---|
| `max_cases_per_epoch` | `8` | Max replay/anchor cases scored per subject per audit. |
| `max_cases_for_retirement` | `12` | Higher cap when a motion puts a RetirementEvent under consideration. |
| `use_cached_results` | `true` | Prefer cached case results (`rqgm_governance_cache.jsonl`); the boards are deterministic given cached results. |

### `rqgm.transition` — RegistryTransitionEngine thresholds

The thresholds are the **only** tunable part of the transition layer;
the T1–T21 table topology is fixed code (`ari/rqgm/transition_rules.py`).

| Key | Default | Meaning |
|---|---|---|
| `replay_pass_threshold` | `0.8` | T3: minimum replay-board score for a validated candidate to enter shadow. |
| `replay_min_cases` | `4` | T3: minimum replay cases behind the score. Waived for the roles that have no executed replay case *by construction* and declare it (`transition_engine.NO_REPLAY_BASIS_ROLES` — `utility_policy`, `paper_writer`, `paper_reviewer`); the waiver is recorded on the transition's notes. Behavioural exploration roles are always held to this floor. |
| `shadow_pass_threshold` | `0.7` | T6: minimum shadow agreement for probationary adoption; below it with sufficient samples is the T5 rejection. |
| `shadow_min_samples` | `5` | T6: minimum live-shadow comparisons before adoption/rejection is decidable. Waived for the same declared `NO_REPLAY_BASIS_ROLES`: a passive `utility_policy` document is never shadow-executed and no paper role has a shadow-serving path, so their shadow stage is vacuous by construction rather than under-populated (plan 14 §5.5). A reported `shadow_score` still has to clear `shadow_pass_threshold` — only the count is waived. |
| `shadow_max_epochs` | `2` | T4: epochs in shadow without sufficient samples before the bounded retry. |
| `shadow_retry_limit` | `1` | T4: bounded shadow retries; beyond it the candidate takes the T5 rejection. |
| `probation_min_epochs` | `1` | T7/T14: full clean epochs served before promotion to active. |
| `warning_escalation_count` | `2` | T10: consecutive warning epochs before escalation to probation. |
| `warning_memory_epochs` | `3` | T13: recurrence window after entering warning that escalates to probation. |
| `retirement_replay_min_cases` | `8` | T17: minimum ReplayBoard case coverage before a retirement commits (`<= rqgm.replay.max_cases_for_retirement`). |
| `candidate_max_age_epochs` | `3` | T2: epochs a candidate may wait for validation before expiry. |
| `max_adoptions_per_role_per_boundary` | `1` | T6: adoption cap per role per epoch boundary. |

### `rqgm.adversarial` — attack→defense→adjudication loop

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether the adversarial round runs per completed node. |
| `types` | all eight | Enabled adversary types (closed set): the seven exploration types `overclaim`, `metric_gaming`, `prior_art`, `reproducibility`, `evidence_gap`, `cost_explosion`, `prompt_injection`, plus `paper_self_preference`. The eighth is inert unless the paper-archive phase is active. |
| `max_attacks_per_node` | `3` | Hard cap on raw attacks per round. |
| `max_adversary_calls_per_epoch` | `24` | Hard per-epoch cap on adversary LLM calls (the one schema home for this cap). |
| `sample_mod` | `5` | Deterministic 1-in-N node sampling (`hash(node_id+epoch_id) mod N == 0`; P2-safe). `<= 0` disables sampling. |
| `jump_threshold` | `0.25` | Score jump over the parent that triggers a round. |
| `full_governance_only_on_top_k` | `3` | Frontier top-K membership that triggers a round. |
| `penalty.cap` | `0.5` | Hard per-node cap on the summed validated-attack penalty (penalties never raise a score). |
| `penalty.severity_weights` | `low: 0.05`, `medium: 0.15`, `high: 0.3`, `critical: 0.5` | Judge-assigned-severity → weight, multiplied by the fixed verdict factor (valid = 1.0, partially_valid = 0.5). |
| `pool.max_cases` | `64` | Bounded AdversarialReplayPool size (eviction is logical-only). |
| `pool.min_severity` | `medium` | Pool admission floor on the judge-assigned severity. |
| `pool.min_per_type` | `2` | Per-type eviction floor so adversary-type coverage survives the cap. |

### `rqgm.shadow` — shadow live-evaluation sampling

Shadow output is observation-only: it never reaches BFTS scores, the
frontier, or memory.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Shadow live-evaluation on/off (off == a zero shadow budget). |
| `sample_rate` | `0.2` | Fraction of live calls shadow-sampled per candidate (deterministic hash sampling). |
| `max_shadow_calls_per_epoch` | `10` | Hard cap on shadow side-by-side calls per epoch. |

### `rqgm.prompt_evolution` — candidate caps

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Prompt evolution on/off inside `ari_rqgm` (supports ablations with governance but frozen prompts). |
| `max_candidates_per_role_per_epoch` | `1` | Cap on new prompt candidates per role per epoch. |
| `max_total_candidates_per_epoch` | `4` | Cap on new prompt candidates per epoch across all roles. |
| `max_clean_room_generations_per_epoch` | `1` | Cap on clean-room regenerations per epoch (consumed by the clean-room pipeline). |
| `mutation_kinds` | all five | Enabled PromptMutator families: `freeform_mutation`, `threshold_tuning`, `schema_tightening`, `specialization`, `distillation`. |

### `rqgm.utility_evolution` — governed rewriting of the score itself

At epoch boundaries the utility function is itself a governed object: it is
rewritten only through `PolicyMutator` → `CandidateValidationPipeline` →
`RegistryTransitionEngine` → `ConstitutionalKernel`, never in place.

**Numeric and vocabulary knobs only.** The legality rules — the closed value
spaces and the axis-weight bounds — are frozen code in
`ari.rqgm.kernel_rules.UTILITY_POLICY_RULES` and live *inside*
`constitution_hash`; a tunable weight bound would be a tunable constitution.
Two budgets that look as if they belong here deliberately do not, because each
already has one schema home: candidate caps ride
`rqgm.prompt_evolution.max_candidates_*` and adoption caps ride
`rqgm.transition.max_adoptions_per_role_per_boundary`.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Governed utility evolution on/off inside `ari_rqgm`. `false` reproduces the pre-rewrite scoring behaviour exactly — no candidate is minted, nothing supersedes, and `utility_policy_hash` is constant for the whole run (the ablation rung). It does **not** unregister the founding `utility_policy_v1` / `policy_mutator_v1` components. |
| `mutation_kinds` | `axis_reweighting`, `composite_swap`, `frontier_score_swap`, `exploration_tuning` | Enabled `PolicyMutator` families. All four defaults are pure arithmetic over the boundary's evidence — no LLM, no clock, no randomness — so the default rewrite stream is deterministic. `freeform_policy_proposal` consults an LLM and is opt-in; enabling it costs byte-reproducibility of the candidate stream (an irreproducible *proposal* still cannot become an unvalidated policy — the kernel validates it either way). |
| `min_epochs_between_rewrites` | `1` | Minimum epochs between two adopted rewrites. Bounds the repair cost: a rewrite invalidates every node scored under the old policy, which at an early boundary can be the entire tree. |

### `rqgm.clean_room` — clean-room regeneration posture

The screen *policy* is code (`ari/rqgm/clean_room_rules.py`); only the
numeric knobs live here.  The per-epoch generation budget rides
`rqgm.prompt_evolution.max_clean_room_generations_per_epoch`.

| Key | Default | Meaning |
|---|---|---|
| `generation_backend` | `one_shot` | v1's only backend: a single LLM completion with no tools/filesystem (a tool-bearing loop could read retired prompt text). |
| `contamination_screen.shingle_k` | `8` | Word-shingle length of the deterministic contamination screen. |
| `contamination_screen.fail_on_any_hit` | `true` | Any surviving k-shingle overlap with the forbidden corpus blocks candidate admission. |
| `generator_prompt_key` | `rqgm/clean_room_generator` | Committed meta-prompt key of the CleanRoomPromptGenerator. |

### `rqgm.frontier_repair` — selective erasure / frontier rebuild

Runs only when a committed EpochTransition carries retirements.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether repair runs at boundaries with retirements. |
| `max_trace_depth` | `8` | BFS cap of the dependency-closure tracer; past it consumers are swept in conservatively (invalidate). |
| `recompute_utilities` | `true` | For stale scored evidence, recompute utilities from surviving inputs under the original epoch's frozen weights; `false` invalidates the node instead. Utility-policy retirement independently re-scores stored `_axis_scores` under the new policy, so this switch does not disable the policy rewrite. |
| `abandon_stale_pending` | `true` | Abandon pending children whose proposal record went stale before they ever run. |

### `rqgm.meta_evolution` — meta-tier budgets and switches

The authority matrix itself is frozen code (`ari/rqgm/meta_rules.py`),
never config.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Meta-evolution step on/off (disabled: the coordinator no-ops with one audit line). |
| `evolving_roles` | `prompt_mutator`, `clean_room_generator`, `replay_selector`, `failure_summary_compressor` | The v1 evolving meta roles; shrinkable to `[]` to freeze the layer without code changes. |
| `max_meta_candidates_per_epoch` | `1` | Cap on meta candidates per epoch, total across meta roles. |
| `sandbox.max_cases` | `6` | Historical meta-task bundles replayed per sandbox evaluation. |
| `sandbox.use_cached_results` | `true` | Reuse content-keyed sandbox results. |
| `shadow.min_epochs_before_probation` | `2` | Meta candidates spend at least this many epochs in shadow before `probationary_active` (stricter than the institutional floor). |
| `metric_spec_weight_cap` | `true` | Constitutional cap: node-initiated MetricSpec axis-weights are suppressed in favor of the epoch-frozen weight regime (ignored under `simple_bfts`). |

### `rqgm.budgets` — per-epoch governance spend caps

Read against the passive `cost_tracker` records; `0` means unlimited
(attribution only — the inert default).  Exhaustion degrades governance,
never node execution; the fixed layer is exempt by construction.

| Key | Default | Meaning |
|---|---|---|
| `max_governance_cost_usd_per_epoch` | `0` | Per-epoch USD cap on governance-phase LLM spend. |
| `max_governance_tokens_per_epoch` | `0` | Per-epoch token cap on governance-phase LLM spend. |
| `on_exhausted` | `degrade` | `degrade` caps the node's effective governance level; `skip` drops the single action. Never a crash. |

**The budgeted action kinds.** The three keys above are the only ones this
block owns, but they are not the only thing `GovernanceBudgetManager` counts.
Every governance action submitted to it carries one of ten *action kinds*
(`ACTION_KINDS` in `ari/rqgm/budget.py`) with its own per-epoch counter, and
each kind's cap is read from the block that owns that knob — there are no
aliases. The vocabulary is closed:

| Action kind | Per-epoch cap comes from | Default |
|---|---|---|
| `adversary_call` | `rqgm.adversarial.max_adversary_calls_per_epoch` | `24` |
| `defender_call` | `rqgm.governance.max_defender_calls_per_epoch` | `12` |
| `judge_call` | `rqgm.governance.max_judge_calls_per_epoch` | `8` |
| `shadow_call` | `rqgm.shadow.max_shadow_calls_per_epoch`, or `0` when `rqgm.shadow.enabled` is false | `10` |
| `replay_case` | `rqgm.replay.max_cases_per_epoch`, or `rqgm.replay.max_cases_for_retirement` while a RetirementEvent is under consideration | `8` / `12` |
| `virsci_call` | `proposal_router.generators.virsci.max_calls_per_epoch`; `0` when that generator is disabled, unlimited when the value is `<= 0` | `2` |
| `prompt_candidate` | `rqgm.prompt_evolution.max_candidates_per_role_per_epoch`, counted per role, with `max_total_candidates_per_epoch` as a second ceiling across all roles | `1` / `4` |
| `clean_room_generation` | `rqgm.prompt_evolution.max_clean_room_generations_per_epoch` | `1` |
| `governance_llm_call` | `rqgm.governance.max_llm_calls_per_audit` | `12` |
| `paper_anchor_scoring` | `rqgm.paper.anchor.sample_size`, or `0` when `rqgm.paper.anchor.enabled` is false | `8` |

Level-0 fixed checks never submit an action and are exempt by construction.
Counters are keyed by `(epoch_id, kind)` — by `(epoch_id, kind:role)` for the
per-role `prompt_candidate` cap — and are rebuilt at construction from the
`budget_consumed` audit lines, so caps survive `ari resume`. An absent cap
means unlimited, and any failure inside the check fails **open** with a logged
warning rather than blocking the run. `paper_anchor_scoring` is the only kind
the paper-archive phase added to the original nine; the cost model behind its
cap is in the `rqgm.paper.anchor` subsection below.

### `rqgm.eval` — evaluation-harness posture

All defaults off: scripted eval doubles are refused and injections never
applied unless the `scripts/rqgm_eval` harness enables them on a run it
launches itself.  See [RQGM Evaluation](../guides/rqgm_evaluation.md).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master interlock for the evaluation harness. Never enabled by default. |
| `scripted_components` | `{}` | `role -> double_name` substitutions (harness-only). |
| `injection_specs` | `[]` | Active `eval_*` injection ids; recorded into `rqgm_injection_provenance.json`. |
| `paper_ablation.condition_id` | `""` | Evaluation-only RQGM-paper arm (`P0_hgm_h_fixed_critic` through `P4_constitutional_rqgm`). Empty, or `eval.enabled: false`, preserves normal behavior; this is not a `paper.mode`. |
| `kca_conditions` | `b`/`h`/`k` `""`, `reporting_alias` `null`, `verification_tiers` `[]`, `legacy_comparison_only` `false`, `publishable` `true` | Task-20 factorial comparison identity. Metadata only: it never grants authority or changes production selection/binding/resolution decisions. |

### `rqgm.paper` — paper-archive co-evolution

The whole `rqgm.paper.*` block is **inert unless the effective paper mode is
`rqgm_archive`** (`paper.mode: rqgm_archive` *and* `rqgm.paper.enabled: true`
must agree). It is orthogonal to `ari.mode` and it never shadows the
exploration `rqgm.*` knobs above — the two layers have separate schema homes
even where the names rhyme. The semantics are on the concept side:
[RQGM Architecture](../concepts/rqgm_architecture.md), *The paper-archive
layer*.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Redundant safety interlock, mirroring `rqgm.enabled`. |
| `archive.width` | `4` | Seed drafts at depth 1 — the root branch factor. |
| `archive.refine_rounds` | `2` | Refine children per draft — the draft branch factor. |
| `archive.max_expansions` | `12` | Per-epoch node budget. The *effective* cap the archive uses as its BFTS `max_total_nodes` is `min(width × (1 + refine_rounds), max_expansions)`; at the defaults the two terms coincide (4 × 3 = 12). This bound is what structurally limits the paper actors that carry no budgeted action kind of their own. |
| `archive.depth` | `3` | Draft-tree depth, used as the archive's BFTS `max_depth`. A deeper tree redistributes the same node budget; it never multiplies it. |
| `archive.compile_threshold` | `0.0` | Minimum best-belief score before the winner is lazily compiled. |
| `epoch.rounds` | `2` | Archive rounds per paper phase; one round is one paper epoch. The cheap default deliberately does *not* buy a completed reviewer adoption: that climb is candidate → validated → shadow → probationary_active and needs a role opening first, so it takes roughly five boundaries. At `2` a default run exercises the loop, the adversary and impeachment, but you will not see the active reviewer hash change. Raise it for a run that must witness an adoption. |
| `self_preference.enabled` | `true` | The self-preference adversary; meaningful only under the `rqgm_archive` paper mode. |
| `self_preference.corpus_path` | `""` | `""` reuses the anchor corpus and its authorship labels. |
| `self_preference.sample_size` | `8` | Held-out papers scored per epoch (mirrors the anchor sample). |
| `self_preference.accept_threshold` | `0.6` | Reviewer "accepted" cutoff. |
| `self_preference.margin` | `0.1` | AI-vs-human mean-score gap that fires the pre-signal. |
| `prompt_evolution.enabled` | `true` | Reviewer/writer co-evolution inside the archive. `false` degrades to best-of-N reviewed drafts with no co-evolution. |

### `rqgm.paper.anchor` — held-out accept/reject agreement

The `paper_reviewer`'s ground-truth anchor: a read-only accept/reject corpus,
split `train` / `held_out`, whose shape is documented in
[RQGM Schema Reference](rqgm_schemas.md),
*`paper_anchor_corpus.jsonl` — the read-only accept/reject anchor*. Off by
default, which is the degraded on-ramp: no corpus is read, the
`anchor_evaluation` stage takes its zero-coverage pass, and reviewer
candidates are not anchor-gated. `paper_writer` is anchored too, but to the
Layer-0 claim-evidence gate, which needs no curated corpus — the writer's
faithfulness case still lands on this pool, so `enabled: false` gates the
writer sanction as well.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Anchor-corpus scoring on/off. Also the `paper_anchor_scoring` budget switch: disabled means a cap of `0`, the same disabled-returns-zero rule `shadow_call` and `virsci_call` follow. |
| `corpus_path` | `""` | Accept/reject corpus path, checkpoint-relative or absolute. |
| `sample_size` | `8` | Held-out agreement sample size — **and** the per-epoch `paper_anchor_scoring` cap. A reviewer candidate earns its anchor-agreement utility by being scored against `sample_size` held-out papers, so governance cost is O(candidates × `sample_size`); the cap is the sample size itself rather than a separately tuned number. Read it as a cost model, not as a tuned constant. |
| `max_bootstrap_label_fraction` | `0.5` | Machine-enforced ceiling on the share of `label_source=gate_bootstrap` cases, checked over the corpus *and* over the held-out subset. A breach refuses the corpus — the load returns nothing and the run falls back to the on-ramp — never an exception into the run. `0.0` demands human labels only; `1.0` accepts a fully self-labelled anchor (fingerprinted). |

One inconsistency to know about: the typed default for `enabled` is `false`
(`RQGMPaperAnchorConfig`), while the budget manager's own fallback when it
finds *no* anchor block object at all reads `true`. The fallback only applies
to a config that carries no `anchor` block; a config built from the shipped
defaults always presents `enabled: false`.

### `rqgm.paper.reviewer.agent_as_judge` — agent-as-judge draft scoring

Read **only** under the effective `rqgm_archive` paper mode (`paper.mode:
rqgm_archive` *and* `rqgm.paper.enabled: true` must agree), which is
orthogonal to `ari.mode`.  Off by default, so the archive's draft scorer
stays the deterministic, LLM-free venue rubric and no live LLM call sits on
the draft-scoring path (P2).  On, the shared paper dispatch
(`ari/cli/paper_dispatch.py`, used by `ari paper` / `ari run` / `ari resume`)
injects an `LLMClient`-backed reviewer scorer (`ari/rqgm/paper_judge.py`) that
scores each draft over the *same* venue-rubric axes, weighted by the
**active** governed `paper_reviewer` prompt's emphasis — the only path that
can read axes no deterministic reader can (`novelty`, `significance`).
Fail-open: an LLM error, an unparseable reply, or a reply covering less than
50% of the rubric's total axis weight degrades to the deterministic rubric
score, never a fabricated constant (a non-finite axis value is discarded
rather than propagated into selection).  The same dispatch logs the run's
judged/degraded counts to `ari.log`, because a judged score and a fallback
score are the same float to every consumer.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Agent-as-judge draft scoring on/off. Overridden by `ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`}; invalid values warn and are ignored. |
| `max_tokens` | `1024` | Cap on the judge reply length (cost control), passed through `LLMClient.complete(max_tokens=...)`. |

### `proposal_router` — proposal generation routing

Consumed **only** when the effective mode is `ari_rqgm` — except
`record_only`, which is honored in `simple_bfts` (record-only dual-write,
ablation B1).  `generators.virsci.enabled` is deliberately not read in
`simple_bfts`: the existing VirSci levers
(`bfts_pipeline.generate_idea.enabled` / `ARI_IDEA_VIRSCI_REAL`) stay
authoritative there, and mode resolution never reads `proposal_router.*`
(VirSci is orthogonal to `ari.mode`).

| Key | Default | Meaning |
|---|---|---|
| `record_only` | `false` | In `simple_bfts`, additionally import the agent-loop's `idea.json` output into `proposals/proposal_records.jsonl` as `legacy_idea_json` records. Zero behavior change; rollback = delete the flag. |
| `summary_budget_chars` | `6000` | Total character budget of the rendered ProposalSummaryView expand context. |

Per-generator entries under `proposal_router.generators.*` share two
keys: `enabled` (may the router route to it) and `max_calls_per_epoch`
(`0` = unlimited):

| Generator | `enabled` | `max_calls_per_epoch` | Notes |
|---|---|---|---|
| `cheap` | `true` | `0` (unlimited) | One-shot LLM proposal generator; the deterministic routing fallback. |
| `mutation` | `true` | `2` | Mutates one facet of an existing ProposalRecord. |
| `attack_driven` | `false` | `0` | Consumes ValidatedAttackRecords; disabled and absent from the routing table by default. |
| `prior_art` | `true` | `1` | Differentiates proposals against survey/related refs; degrades to skipped when no prior-art source exists. |
| `virsci` | `false` | `2` | Opt-in high-cost deliberative VirSciAdapter; never enabled by default. Extra keys: `mode: event_triggered` (v1's only mode) and `trigger_on: [initial_exploration, frontier_stagnation, major_pivot, paper_candidate]`. |

---

## Manuscript Complete (opt-in)

`manuscript` is an axis independent of `ari.mode`, `paper.mode`, and the K/C/A
postures. Quoting `"off"` is required for portability across YAML 1.1 parsers.

```yaml
manuscript:
  mode: "off"               # off | audit | enforce
  profile: generic_empirical_v1
  brief_character_budget: 24000
  repair:
    policy: disabled         # disabled | explicit | auto
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    max_resource_units: null
    on_exhaustion: block
```

`off` preserves the legacy path and writes no `.ari-manuscript` data. `audit`
compiles a shadow readiness attempt without changing writer inputs. `enforce`
splits evidence, authoring, and verification into digest-bound transactions and
blocks authoring when a critical requirement is unresolved. `repair.policy:
auto` is rejected outside enforce; `explicit` runs only a named, pre-admitted
request. `repair.on_exhaustion` accepts only `block` and is read by no runtime
branch: an automatic loop that ends without authoring readiness — budget
exhausted, no-progress cycle, or an unavailable resolver — always leaves the
attempt unresolved and the enforce gate stops the run before authoring, so the
key records that single posture rather than selecting among alternatives.
See the [profile reference](manuscript_complete_profile.md),
[contract reference](manuscript_complete_contracts.md), and
[operations guide](../guides/manuscript_complete_operations.md).

## EAR Curation (`ear/publish.yaml`) — v0.7.0+

Curation gates which subset of `{checkpoint}/ear/` becomes the publish-ready
bundle (`{checkpoint}/ear_published/` + `manifest.lock`). The author owns
this allowlist; ari-core enforces a **built-in deny list** that always
outranks `include`.

### Schema (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# Example: <checkpoint>/ear/publish.yaml
include:                     # Glob allowlist (relative to ear/)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # verbatim source files (best chain contributing union)
  - "data/**"                # uploaded inputs only — never experiment outputs
  - "figures/**"             # top-level figures
  - "environment.json"
# Note: EVOLUTION.md and _provenance.json are ARI audit logs at checkpoint
# root, *outside* ear/ — they are never candidates for the published bundle.
exclude: []                  # User-controlled exclusions (applied after `include`)
max_file_mb: 100             # Files larger than this fail curation explicitly
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false              # If true, a publish failure hard-fails the paper pipeline
auto_promote: false          # If true, reproducibility-pass auto-promotes staged->public
license: MIT                 # SPDX id; the LICENSE file is generated from this template
backend: ari-registry        # ari-registry|gh|zenodo|s3|local-tarball (CLI --backend overrides)
```

The legacy v0.6.0 paths (`code/<node_id>/**`, `data/raw_metrics.json`,
`logs/**`, `reproducibility/**`) are no longer produced by `generate_ear`
and should be removed from older `publish.yaml` files. See
`docs/reference/skills.md` for the full new layout description.

### Built-in deny patterns

These are **always** filtered, even if `include` matches them:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

Paths of denied files are **not** recorded in `manifest.lock` — only the
count, so the manifest itself never leaks the names of secrets that were
present in `ear/`.

### Behaviour

- If `publish.yaml` is **absent**, the `ear_curate` stage is skipped silently and
  the paper's Code Availability section is omitted (full back-compat with v0.6.0
  checkpoints).
- The **bundle digest** (`bundle_sha256` in `manifest.lock`) is `sha256` of a
  canonical JSON containing the sorted file records (path + size + sha256). It
  is reproducible across machines and is the value baked into the paper.
- Curation is **atomic**: a hard failure (e.g. `max_file_mb` violation) leaves
  any previously good `ear_published/` intact.

### CLI

```bash
# Curate
ari ear curate <checkpoint>            # Pretty output
ari ear curate <checkpoint> --json     # Machine-readable
ari ear status <checkpoint>            # Show manifest summary

# Publish & promote
ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline integration

`workflow.yaml` adds the `ear_curate` stage between `generate_ear` and
`generate_figures`. The stage is wired to the transform skill's
`curate_ear` MCP tool and is a no-op when `publish.yaml` is absent.
