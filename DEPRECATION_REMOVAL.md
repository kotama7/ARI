# DEPRECATION_REMOVAL.md — Deprecation → Removal Ledger & Policy

This is the single, authoritative ledger for every deprecated path, environment
variable, config/CLI field, and relocated module in ARI, together with the policy
that governs how a symbol travels from **deprecated** to **removed**.

It is the file referenced by:

- `ari-core/ari/_deprecation.py` (module docstring) — the central warning helpers.
- `.github/workflows/refactor-guards.yml` (Phase **DR4**, this doc **§8.2**) — the CI
  guard rails that enforce the policy.
- `ari-core/ari/migrations/v05_to_v07/memory.py` — the single legitimate accessor of
  `~/.ari/global_memory.jsonl` (Tier A/B).
- `ari-core/ari/memory/file_client.py` (Phase **DR1**, Tier A), `ari-core/ari/memory_cli.py`,
  `ari-core/ari/viz/api_publish.py`, `ari-core/ari/publish/backends/ari_registry.py`,
  `ari-core/ari/clone/resolvers/ari.py` (Phase **DR2/DR3**, Tier B).
- `ari-core/ari/orchestrator/node_report/legacy_reconstruct.py` (Phase **DR5**).

Scope: the v0.5 → v1.0 migration away from the global `~/.ari/` config directory that
checkpoint-scoping was meant to retire, plus any internal module quarantine.

---

## 1. Policy — deprecation to removal

1. **Nothing is removed silently.** A symbol, path, env var, config field, or import
   path that ARI has ever exposed is first *deprecated* (kept working, but announced),
   recorded here in §6/§7, and only then removed on the scheduled version (§5).
2. **A deprecation is announced two ways:** at runtime via a `DeprecationWarning`
   (the `ari._deprecation.*` helpers, §4) *and* on paper via a row in the ledger
   (§6 external contracts, §7 internal quarantine).
3. **Back-compat is a shim, never a fork.** When a symbol moves, the old path keeps
   re-exporting the same public names unchanged and emits the warning; behavior is
   identical until the removal version.
4. **Default removal target is `v1.0`** (`_DEFAULT_REMOVAL = "v1.0"` in
   `_deprecation.py`). A deprecation may name a later version, never an earlier one.
5. **Determinism (P2) is preserved.** The helpers and the CI guards use stdlib +
   PyYAML only; no LLM/network calls are involved in emitting or enforcing deprecations.

### 1.1 Tiers

| Tier | Meaning | Behavior until removal | Examples |
|------|---------|------------------------|----------|
| **A** | Hard-changed default / removed silent fallback. The old *implicit* behavior is gone now; callers must be explicit. | Raises/behaves differently immediately; documented here. | `FileMemoryClient(path=...)` — the `~/.ari/memory.json` default was dropped (Phase DR1). |
| **B** | Soft fallback kept behind a `DeprecationWarning` for one minor version. | Old path still works *if present*, emits a warning, falls through to the checkpoint-scoped location. | The five `warn_deprecated_path` sites in §6. |

`~/.ari/global_memory.jsonl` is **Tier A/B**: the only sanctioned accessor is the
migration shim (`migrations/v05_to_v07/memory.LEGACY_GLOBAL_PATH`); all other code must
avoid it (Tier A rule), while the migration itself is a Tier-B fallback removed at v1.0.

---

## 2. Removal phases (DR1 – DR5)

| Phase | Name | State | What it covers |
|-------|------|-------|----------------|
| **DR1** | Tier-A default changes | **landed** | Silent `~/.ari/` defaults removed; explicit checkpoint-scoped paths required (e.g. `FileMemoryClient`). |
| **DR2** | Tier-B warnings wired | **landed** | Every remaining `~/.ari/` fallback emits `warn_deprecated_path` before falling through (§6). |
| **DR3** | Publish/clone/registry hardening | **landed** | The registry/publish/clone resolvers document DR2/DR3 Tier-B fallbacks and prefer env / checkpoint config. |
| **DR4** | Guard rails | **active** | CI (`refactor-guards.yml`) blocks *new* `~/.ari/` references and asserts pytest writes no `$HOME/.ari/` (§8). |
| **DR5** | v1.0 removal | **scheduled (v1.0)** | Drop the Tier-B fallbacks, the `migrations/v05_to_v07` package, and the `legacy_reconstruct` shim; make `ARI_LETTA_VENV` etc. mandatory. |

---

## 3. How a symbol is marked deprecated

Two actions are always required together:

1. **Emit the runtime warning** from `ari._deprecation` at the fallback/relocation site
   (§4).
2. **Add a row** to the ledger — §6 for an external contract (path/env/field), §7 for an
   internal module relocated under `ari/_legacy/`.

For a relocated module, additionally leave a **re-export shim** at the original import
path that re-exports every previously public symbol unchanged and emits the warning on
import, naming the removal version. The old import path must stay importable until DR5.

---

## 4. The deprecation helpers (`ari/_deprecation.py`)

All helpers emit a `DeprecationWarning` with `stacklevel=3` so the warning points at the
caller, and all default `removal_version="v1.0"`.

| Helper | Marks | Signature |
|--------|-------|-----------|
| `warn_deprecated_path(path, replacement, removal_version="v1.0")` | a deprecated `~/.ari/`-style path being touched | **KEEP** — 5 sanctioned, CI-allow-listed sites (§6). |
| `warn_deprecated_env(name, replacement, removal_version="v1.0")` | a deprecated environment variable | **KEEP** for API symmetry (no current call sites; DELETE_CANDIDATE → subtask 057). |
| `warn_deprecated_field(model, field, replacement, removal_version="v1.0")` | a deprecated config/CLI field | **KEEP** for API symmetry (no current call sites; DELETE_CANDIDATE → subtask 057). |

> A `warn_deprecated_module` helper for `_legacy/` re-export shims is *planned* (additive,
> mirrors `warn_deprecated_path`) and lands with the first internal quarantine (§7). It is
> not present today.

---

## 5. Removal criteria & schedule

A deprecated entry is removed when **all** hold:

1. Its scheduled removal version (default **v1.0**) is the release being cut.
2. No non-migration importer remains — verified by the reference-graph / dead-code
   analyzers (subtasks 054/055) and `ruff F401`.
3. Its DR4 guard has been green (no new references) for the full deprecation window.
4. The replacement (env var and/or checkpoint-scoped path) has shipped and is documented.

At **DR5 / v1.0** the following are dropped together: the five Tier-B `~/.ari/` fallbacks
(§6), the `ari.migrations.v05_to_v07` package (incl. `LEGACY_GLOBAL_PATH`), and the
`ari.orchestrator.node_report.legacy_reconstruct` shim. `ARI_LETTA_VENV` becomes mandatory.

---

## 6. External-contract deprecation ledger (Tier B, removal = v1.0)

The sanctioned `~/.ari/` fallbacks. Each emits `warn_deprecated_path` before falling
through to the checkpoint-scoped / env replacement. These five sites are the **only**
ones allow-listed in `refactor-guards.yml` (§8.2).

| # | Deprecated path | Replacement | Site | Tier / Phase |
|---|-----------------|-------------|------|--------------|
| 1 | `~/.ari/registries.yaml` | `ARI_REGISTRIES_FILE` env or `{checkpoint}/.ari/registries.yaml` | `ari/publish/backends/ari_registry.py` | B / DR2–DR3 |
| 2 | `~/.ari/registries.yaml` | `ARI_REGISTRIES_FILE` env or `{checkpoint}/.ari/registries.yaml` | `ari/clone/resolvers/ari.py` | B / DR2–DR3 |
| 3 | `~/.ari/publish.yaml` | `ARI_PUBLISH_SETTINGS` env or `{checkpoint}/settings.json` publish section | `ari/viz/api_publish.py` | B / DR2 |
| 4 | `~/.ari/registry-data` | `ARI_REGISTRY_DATA` env var | `ari/registry/__init__.py` | B / DR2 |
| 5 | `~/.ari/letta-venv/` | `ARI_LETTA_VENV` env var (required in v1.0) | `ari/memory_cli.py` | B / DR2 |

**Migration accessors (Tier A/B, removal = v1.0):**

| Symbol | Path / behavior | Site | Removal |
|--------|-----------------|------|---------|
| `LEGACY_GLOBAL_PATH` | `~/.ari/global_memory.jsonl` — sole sanctioned reader; migrates v0.5 JSONL → v0.6 Letta | `ari/migrations/v05_to_v07/memory.py` | v1.0 (DR5) |
| `FileMemoryClient(path=...)` | `path` **required**; the `~/.ari/memory.json` default was removed | `ari/memory/file_client.py` | Tier A — already enforced (DR1) |
| `reconstruct_report_from_legacy` shim | re-export of `migrations/v05_to_v07/node_reports` for the old import path | `ari/orchestrator/node_report/legacy_reconstruct.py` | v1.0 (DR5) |

---

## 7. Internal quarantine ledger (`ari/_legacy/`)

Modules relocated to the private `ari/_legacy/` package (leading underscore → never a
stable surface) with a re-export shim at their original import path.

| Module (old path) | `_legacy/` body | Public symbols preserved | Importers | Removal | Owning subtask |
|-------------------|-----------------|--------------------------|-----------|---------|----------------|
| _(none yet — no module has been quarantined; populated as `MOVE_TO_LEGACY` decisions land)_ | — | — | — | — | — |

**Routing recorded here, not modified by the doc:** `warn_deprecated_env` /
`warn_deprecated_field` and `WIZARD_ROUTES` / `schemas.load()` → DELETE_CANDIDATE, subtask
057; ReAct-loop merge → subtask 011; pipeline-runner merge → subtasks 012/062.

---

## 8. Enforcement

Two complementary mechanisms keep the ledger honest.

### 8.1 Audit — no re-introduced `~/.ari/`

`ari.migrations.v05_to_v07.memory.LEGACY_GLOBAL_PATH` centralizes the legacy path as a
single constant so DR4 audits can `grep` for it. All new code must route through
`PathManager` / checkpoint-scoped paths; the only exceptions are the sites in §6 and the
migration package.

### 8.2 CI guard rails — `.github/workflows/refactor-guards.yml` (Phase DR4)

Referenced from the top of the workflow as *"Phase DR4 / DEPRECATION_REMOVAL.md §8-2"*.
The workflow runs on PRs to `main` and `refactoring` and hosts two hard guards:

1. **`no-new-home-ari-refs`** — diffs the PR against the merge base and **fails** on any
   added `Path.home()/…/.ari` or `~/.ari` reference in `ari-core/ari/**.py`, *except* the
   path-excluded sanctioned sites: `_deprecation.py`, the `migrations/` package, and the
   §6 shim files (`core.py`, `paths.py`, `memory_cli.py`, `memory/auto_migrate.py`,
   `memory/file_client.py`, `publish/backends/ari_registry.py`, `clone/resolvers/ari.py`,
   `registry/__init__.py`, `viz/state.py`, `viz/api_settings.py`, `viz/api_publish.py`).
   Docstring/comment-only lines are ignored. **To add a new sanctioned site you must add
   it to the exclude list with a justification and a ledger row here.**
2. **`no-home-ari-writes`** — runs the pytest suite under a redirected `HOME` and **fails**
   if `$HOME/.ari/` is created, proving no code path writes the retired global directory.

The same workflow also carries the Stage-1 *advisory* refactor-invariant gates (import
boundaries, directory policy, complexity, lint, dead-code) appended by subtask 049; those
are `continue-on-error: true` and never turn a green PR red — their promotion to hard gates
is a one-line flip, not a rewrite.

---

## 9. See also

- `ari-core/ari/_deprecation.py` — the warning helpers (contract; do not change signatures).
- `ari-core/ari/migrations/README.md` — the migration-shim package layout.
- `docs/refactoring/subtasks/016_clean_merge_or_quarantine_legacy_code.md` — the design of
  this ledger (§7.1–§7.5) and the legacy-code quarantine plan.
- `docs/refactoring/004_legacy_obsolete_inventory.md` — the inventory that first flagged
  this doc as a dangling reference.
