# Config / Settings / Workflow Unification (requirement 08)

Task-control note from `08_config_settings_workflow_unification.md`. Captured
2026-05-30 from a 3-agent mapping of every config source. Assessment-first
requirement (§5: propose helpers, implement only if trivial + behavior-neutral;
§11: lock precedence with tests *before* touching code).

## 1. Config sources (where read / written)

| Source | Read by | Written by |
|--------|---------|-----------|
| `ARI_*` env vars | `config.auto_config` + `_apply_*_env_overrides`; `api_settings._api_get_settings` | `api_experiment` builds `proc_env`; `_apply_memory_section` `setdefault` |
| `.env` (secrets) | `api_settings._api_get_env_keys` (ckpt → /ARI → ari-core → ~); `config._resolve_env_vars` `${VAR}` | `api_settings._api_save_env_key` + `_api_save_settings` → `_st._env_write_path` |
| CLI options (typer) | `cli/run.py` `--config`→`load_config`, `--profile`→`_apply_profile` | — (read-only) |
| GUI `settings.json` (project-scoped) | `_api_get_settings` (merged over defaults+workflow.yaml) | `_api_save_settings` (refuses w/o active ckpt; api_key popped → .env) |
| `launch_config.json` (per-ckpt snapshot) | `api_experiment`, `ui_helpers`; mapped to `ARI_*` for the CLI | `api_experiment` at launch |
| `workflow.yaml` (bundled; per-ckpt copy) | `config.load_config`, `pipeline/yaml_loader`, `api_settings`, `api_workflow` | `api_settings._api_save_workflow`, `api_workflow._api_save_*` (ckpt copy only) |
| `profiles/*.yaml` | `cli/run._apply_profile`, `finder.find_profile_yaml`, `ui_helpers` | — |
| `default.yaml` | `ui_helpers` (merge base), `finder.find_workflow_yaml` | — |
| `ari/configs/*.yaml` (prices/defaults) | `configs/_loader.FilesystemConfigLoader` (cost_tracker, lineage_decision) | — (ops-edited) |
| Pydantic field defaults | every `ARIConfig` consumer | — |

**Three config-model layers** (similarly named, distinct): `ari.config` (typed
Pydantic models + `load_config`/`auto_config` + `finder.py` discovery);
`ari.configs` (untyped filesystem lookup tables — prices/defaults); and
`ari.public.config_schema` (a thin public re-export of `ari.config`'s models, no
logic). See `docs/reference/configuration.md#configuration-precedence-observed`.

## 2. Precedence — documented in `configuration.md`

The full per-setting precedence table (llm_model runtime/display/settings,
provider, language, port=8765, SLURM partition, checkpoint dir) plus the
two-chain model and falsy-vs-missing handling now live in
`docs/reference/configuration.md`. Key non-obvious facts:

- **Runtime ≠ GUI-display**: the agent loop's value is decided by env-overrides
  in `config/__init__.py` (env wins over YAML); the dashboard badge shows the
  in-memory `_launch_*` / `launch_config.json` mirror — they can disagree if
  `_launch_*` is stale.
- **Env-var hand-off is the universal funnel**: GUI launch writes `ARI_*` env +
  `launch_config.json`; the CLI resolves only via env + the per-ckpt
  `workflow.yaml`, never by re-parsing `launch_config.json` (except
  `/api/run-stage`).
- **Language is GUI-only env injection**: `ARI_PAPER_LANGUAGE` is set only by
  `api_experiment`; a hand-run `ari run` does *not* re-derive it from
  `launch_config.json` — so it writes English even if `launch_config.language=ja`.
  (Noted as a latent gap, not fixed here — behavior change, out of scope.)
- **Partition uses two env-var names** across layers (`ARI_SLURM_PARTITION` in
  the agent-prompt layer vs `SLURM_DEFAULT_PARTITION` in the hpc skill default).

## 3. Duplicated logic — verdicts

| Logic | Locations | Verdict |
|-------|-----------|---------|
| **`.env` write upsert** | `api_settings._api_save_env_key` + `_api_save_settings` | **CONSOLIDATED THIS PR** — trivial + behavior-neutral; one `_upsert_env_key(name,value,*,quote)` helper, the quote flag preserves the `KEY="v"` vs `KEY=v` difference verbatim. Guarded by new `tests/test_env_write_quoting.py`. |
| workflow.yaml dual-candidate discovery (3-level vs 4-level path) | `api_settings` ×2, `api_workflow` ×5, `api_experiment` | DEFER — `finder.package_config_root`/`find_workflow_*` are the migration target, but the "try both depths" (installed vs repo layout) and no test pins the viz candidate ORDER. |
| profile YAML resolution (`first-with-bfts-or-hpc`) | `finder.find_profile_yaml` (canonical), `ui_helpers` (uses it), `routes.py` ×2 (inline, extra section-filter) | DEFER — the inline copies add a `bfts`/`hpc` section filter `find_profile_yaml` lacks; a naive swap changes which file wins. Pin the rule first. |
| `.env` read candidate-list + line parse | `api_settings._api_get_env_keys`, `api_experiment` ×2 | DEFER — 3 copies have *different* semantics (secret-key filter; all-keys; quote-strip vs not; candidate ORDER differs). Only the pure line-parse primitive is identical; the surrounding order/filter must stay per-caller until pinned. |
| `launch_config.json` precedence chain | `state.py`, `server.py`, `checkpoint_lifecycle`, `ui_helpers`, `routes.py` ×2, `api_experiment`, `orchestrator` (8 sites) | DEFER — highest fan-out + deliberate per-caller variation (ckpt-only vs ckpt-then-parent) + pinned by brittle source-string ordering tests. Clearly behavior-affecting. |
| `{**defaults, **saved}` settings merge | `api_settings` (1 site) | NOT a duplication (single occurrence). |

## 4. Helper decision (conservative, per §5)

**Implemented now** (only): `_upsert_env_key` in `api_settings.py` — folds the
two identical `.env`-write blocks. Behavior-neutral (quote flag preserves each
caller's exact output), guarded by a test added *before* the extraction, touches
no precedence order. Full settings suite green (236 passed).

**Proposed / deferred** (a real `ari.config` central resolver subsuming the
workflow.yaml fallback + `launch_config.json` chain + profile resolution): high
fan-out, deliberate per-caller variation, and pinned today partly by
source-string ordering tests that make refactors brittle. The right end state,
but only after adding the missing guard tests (viz workflow-candidate order,
profile section-filter rule, .env candidate order). `config/finder.py` is the
migration seed; `routes.py`/`api_workflow.py` are the consumers to migrate once
their behavior is pinned. → req-08 §12 follow-up.

## 5. Guard-test gaps to close before any further extraction

(1) viz workflow.yaml dual-candidate ORDER; (2) `routes.py` profile
`first-with-bfts-or-hpc` rule + default.yaml overlay; (3) `.env` read
candidate-list order + secret-key filter; (4) the `.env`-write quoting — **now
pinned** by `test_env_write_quoting.py`; (5) orchestrator `launch_config.json`
template-var read (read-only, lowest risk).

## 6. Checks

`pytest ari-core/tests` green; the extraction is byte-identical (the
pre-existing config-precedence suite + the new quoting guard all pass). No
`.env`/`settings.json`/`start.sh`/`setup_env.sh` semantics changed.

## 7. Follow-up candidates (→ §12)

- Central `ari.config` resolver (after the §5 guard tests land).
- Migrate viz workflow.yaml discovery to `finder` helpers.
- Reduce config-related `ari.viz.state` fields (`_launch_*`, `_env_write_path`)
  — overlaps with the req-07 active-checkpoint-global follow-up.
- Re-derive `ARI_PAPER_LANGUAGE` from `launch_config.json` on the CLI path
  (behavior fix — needs its own justified change, not a refactor).
