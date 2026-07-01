# Subtask 070: Refactor Dashboard Settings Panel

> Phase 6: Dashboard UX
> Planning date: 2026-07-01 · Repo: `/home/t-kotama/workplace/ARI` · ari-core 0.9.0 · branch `main`
> Classification of the primary target (`SettingsPage.tsx`): **ADAPT** (decompose in place; no contract change).

## 1. Goal

Decompose the dashboard Settings god-component
`ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` (**1049 lines**,
**10 `<Card>` sections**, **38 `useState` hooks** in one function component) into a thin
orchestrator plus one self-contained sub-component per settings section, **without
changing any runtime behaviour, network contract, or persisted data format**.

Concretely, after this subtask:
- `SettingsPage.tsx` is a small container (target < ~250 lines) that owns load/save
  orchestration and renders section components.
- Each of the 10 sections (Language, LLM Backend, Paper Retrieval, VLM Figure Review,
  Memory/Letta, SLURM/HPC, Container, Available Skills, SSH Remote Host, Project
  Management) lives in its own file.
- The `POST /api/settings` payload is **byte-for-byte identical** (same 24 keys, same
  value derivation) to today, and the `GET /api/settings` consumption is unchanged.
- Frontend `npm run typecheck`, `npm test`, and `npm run build` all pass; i18n key
  parity across `en/ja/zh` is preserved or improved (never regressed).

This is purely a maintainability/testability refactor of one panel. It is explicitly
**not** a redesign, not a security fix, and not a data-model change.

## 2. Background

The ARI dashboard frontend (`ari-core/ari/viz/frontend/`, Vite 5 + React 18.3 + TS 5.5,
hand-rolled hash router in `src/App.tsx`, single React Context in
`src/context/AppContext.tsx`) has no CSS framework and no state library; styling is inline
`style={{}}` objects plus one `src/styles/dashboard.css`.

The Settings route (`'settings'` in `App.tsx` `PAGE_MAP`, mirrored in
`components/Layout/Sidebar.tsx` `NAV_ITEMS`) is rendered by a single default-export
function component. It is the **3rd-largest frontend file** in the tree
(`resultSections.tsx` 1590, `StepResources.tsx` 1160, `SettingsPage.tsx` 1049). All ten
sections, all 38 pieces of local state, all handlers, and all JSX are inline in one
function body (`SettingsPage.tsx:40-1049`). A prior refactor already extracted the pure
data/logic into `settingsConstants.ts` (86 lines: provider/model tables, Letta embedding
tables, `CUSTOM_HANDLE_VALUE`, `_splitHandle`), so the JSX/state split is the remaining
work.

The panel is the central operator surface for LLM backend, Semantic Scholar / AlphaXiv
retrieval, VLM review model, Letta memory config + restart, SLURM/HPC defaults, container
runtime, read-only skill inventory, SSH remote host, and checkpoint deletion. Because it
drives real configuration persisted to the project `.env` and environment (see Section
10/11), the refactor must be behaviour-preserving.

Note on counts: the ground-truth skeleton stated "9 `<Card>` sections" and "~30
`useState`"; direct inspection on 2026-07-01 shows **10 `<Card>` sections** and **38
`useState` hooks** (verified via `grep -n '<Card'` and `grep -c useState`). Use the
verified numbers.

## 3. Scope

In scope:
- Split `SettingsPage.tsx` into an orchestrator + per-section presentational components,
  keeping the exact DOM structure, `Card` usage, inline styles, and i18n keys.
- Lift the shared `inputStyle` / `labelStyle` objects (`SettingsPage.tsx:337-352`) and the
  `SkillInfo` interface (`SettingsPage.tsx:31-36`) into a shared module so section
  components can consume them.
- Optionally (see Section 8, low priority) replace hardcoded English `Card` titles / field
  labels with existing-or-new i18n keys — only if key parity is maintained.
- Add a Vitest unit test for at least the save-payload assembly (`handleSave`) and the
  `_splitHandle` round-trip, since **no Settings test exists today**.
- Update `components/Settings/index.ts` barrel and `components/Settings/README.md` contents
  list to reflect the new files.

Out of scope: everything in Section 4.

## 4. Non-Goals

- **No change** to the `GET`/`POST /api/settings` or `/api/env-keys` contracts, the
  `Settings` TypeScript interface (`types/index.ts:38-75`), or the backend
  `ari/viz/api_settings.py` env-var mapping. Field names, key set, and value semantics are
  frozen.
- **No** visual redesign, no tabs/search/accordion UX (that is a separate Phase 6 item).
- **No** security remediation: this subtask does **not** touch `/api/env-keys` secret
  exposure, API-key editability, or the raw-value regimes flagged in the inventory. Those
  belong to the security-hardening subtasks, not here. Do not opportunistically change auth
  or secret handling.
- **No** sourcing/refresh of the hardcoded, stale provider/model lists in
  `settingsConstants.ts` (`gpt-5.2`, `claude-opus-4-5`, etc.) — that is **REVIEW_REQUIRED**
  and a separate work item; keep the tables as-is.
- **No** backend Python changes, **no** route additions/removals, **no** new npm
  dependency (React 18 / Vite 5 / Vitest 2 stack stays as pinned in
  `frontend/package.json`).
- **No** directory renames; **no** change to `App.tsx` routing or `Sidebar.tsx` nav.
- Do **not** add the per-phase model fields (`model_idea/bfts/coding/eval/paper/review`,
  `vlm_review_enabled/max_iter/threshold`) to this panel — they are intentionally absent
  from Settings (they live in `Wizard/StepResources.tsx`). Preserve that split.

## 5. Current Files / Directories to Inspect

Primary target (WILL be split):
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` — **1049 lines**,
  single default-export god-component. Section anchors verified today:
  - Language `Card` — line 369
  - LLM Backend `Card` — line 383
  - Paper Retrieval `Card` — line 481
  - VLM Figure Review `Card` (hardcoded English title) — line 512
  - Memory (Letta) `Card` — line 526 (embedding two-stage picker, letta-free warning,
    deployment selector + Restart button)
  - SLURM / HPC `Card` — line 698
  - Container `Card` (hardcoded English title) — line 773
  - Available Skills `Card` (read-only table) — line 830
  - SSH Remote Host `Card` — line 880
  - Project Management `Card` (hardcoded English title; checkpoint delete) — line 946
  - `handleSave` (the 24-key payload) — lines 226-269
  - `inputStyle`/`labelStyle` shared style objects — lines 337-352

Support files in the same directory:
- `ari-core/ari/viz/frontend/src/components/Settings/settingsConstants.ts` — **86 lines**,
  pure data/logic already extracted (`PROVIDER_MODELS`, `PROVIDER_KEY_PLACEHOLDER`,
  `LETTA_EMBEDDING_BY_PROVIDER`, `LETTA_EMBED_PROVIDERS`, `CUSTOM_HANDLE_VALUE`,
  `DEFAULT_PROVIDER`, `_splitHandle`). **KEEP as-is.**
- `ari-core/ari/viz/frontend/src/components/Settings/index.ts` — **1 line** barrel
  re-export. Will be updated.
- `ari-core/ari/viz/frontend/src/components/Settings/README.md` — **10 lines**, contents
  list. Will be updated.

Consumed by the target (READ-ONLY; must keep compatibility):
- `ari-core/ari/viz/frontend/src/types/index.ts` — `Settings` interface at lines 38-75
  (35 fields).
- `ari-core/ari/viz/frontend/src/services/api.ts` — **863 lines**. Wrappers used here:
  `fetchSettings` (372), `saveSettings` (376), `fetchEnvKeys`→`/api/env-keys` (382),
  `restartLetta` (402), `fetchSkills` (479), `testSSH` (555), `fetchPartitions` (565),
  `fetchContainerInfo` (596); plus `generateConfig`, `fetchCheckpoints`,
  `deleteCheckpoint`.
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` — `useAppContext` provides
  `state` and `refreshCheckpoints` (used by delete flow).
- `ari-core/ari/viz/frontend/src/i18n/en.ts` (**444 lines**), `ja.ts` (**441**),
  `zh.ts` (**441**) — `settings_*`, `s_*`, `custom_entry`, `btn_save`, `btn_test_llm` keys
  (en anchors ~134-159, 187-191, 279, 323-328).
- `ari-core/ari/viz/frontend/src/components/common/` — `Card` component (imported via
  `../common`).

Backend (READ-ONLY reference; NOT changed by this subtask):
- `ari-core/ari/viz/api_settings.py` — **553 lines**. `_api_get_settings` (line 119),
  `_api_save_settings` (line 202), `_api_get_env_keys` (40), `_api_save_env_key` (107). Key
  detail: settings are **not** persisted to a `settings.json`; the backend maps to
  environment variables and the project `.env` (comment at `api_settings.py:183`: "no
  longer maintains any global `~/.ari/settings.json` fallback"). API keys are stripped from
  the dict and written to `.env` (`api_settings.py:204-206`).
- `ari-core/ari/viz/routes.py` — **1197 lines**. Endpoints: `GET /api/settings` (853),
  `POST /api/settings` (1035), `GET /api/env-keys` (746), `POST /api/env-keys` (1060).

Tests (baseline): **No test references `SettingsPage` today.** The only frontend
`__tests__` directory is `components/PaperBench/__tests__/`
(`PaperBenchWizard.test.tsx`, `PaperImportDialog.test.tsx`). This subtask should add the
first Settings test.

## 6. Current Problems

1. **God-component.** All 10 sections, 38 `useState` hooks, ~10 async handlers, and ~700
   lines of JSX are in one function body (`SettingsPage.tsx:40-1049`). It is unreviewable
   as a unit and cannot be unit-tested per section.
2. **State is one flat cluster.** 38 `useState` calls (`SettingsPage.tsx:44-114`) mix
   unrelated concerns (LLM, SSH, SLURM, container, Letta, skills, checkpoints, status),
   making it hard to reason about which state feeds the save payload versus which is
   local-only (e.g., `containerRuntime`/`containerVersion` are detect-only and are **not**
   in `handleSave`).
3. **Save-payload fragility.** `handleSave` (`SettingsPage.tsx:226-269`) hand-assembles a
   24-key object from scattered state, including two non-trivial derivations: model =
   `modelSelect !== '__custom__' ? modelSelect : modelCustom` (228) and
   `letta_embedding_config` via `_splitHandle`/custom fallback (230-233). With no test,
   any careless split risks silently dropping or renaming a key.
4. **No tests.** Zero coverage for the panel that writes real config to `.env`/env.
5. **i18n inconsistency.** Three `Card` titles are hardcoded English strings ("VLM Figure
   Review" `:512`, "Container" `:773`, "Project Management" `:946`), and many inline field
   labels are hardcoded ("API Key", "Paper Retrieval Backend", "Semantic Scholar API Key",
   "VLM Model", "Memory (GB)", "Mode", "Pull Policy", "Image", "Detect Runtime", "Host",
   "Port", "Remote ARI Path", "SSH Key Path", "Test SSH", "Detect", etc.) while sibling
   sections use `t(...)`. This is a latent i18n-parity gap.
6. **Duplicated style objects inline.** `inputStyle`/`labelStyle` (`:337-352`) are defined
   inside the component and referenced ~40 times; after a split each section would
   otherwise re-declare them.
7. **Settings/UX split confusion (documentation only).** The `Settings` interface declares
   `model_idea/bfts/coding/eval/paper/review` and `vlm_review_enabled/max_iter/threshold`
   (`types/index.ts:59-71`) that have **no UI** in this panel (they are edited in
   `Wizard/StepResources.tsx`). This is intentional but undocumented and a frequent source
   of confusion — worth a code comment, not a UI change.

## 7. Proposed Design / Policy

Policy: **ADAPT** `SettingsPage.tsx` by extracting presentational section components while
keeping it the single source of truth for load/save orchestration. Preserve the exact
network contract and DOM output.

Structure (all under
`ari-core/ari/viz/frontend/src/components/Settings/`):

```
Settings/
  SettingsPage.tsx        # orchestrator: load*, handleSave, handleTest*, renders sections
  settingsConstants.ts    # KEEP unchanged (pure data/logic)
  settingsStyles.ts       # NEW: shared inputStyle / labelStyle (moved from SettingsPage)
  settingsTypes.ts        # NEW (optional): SkillInfo + section prop types
  sections/
    LanguageSection.tsx
    LlmBackendSection.tsx
    PaperRetrievalSection.tsx
    VlmReviewSection.tsx
    MemorySection.tsx      # Letta: base url/key, embedding picker, deployment + restart
    SlurmSection.tsx
    ContainerSection.tsx
    SkillsSection.tsx      # read-only table
    SshSection.tsx
    ProjectManagementSection.tsx
  index.ts                # barrel (update if the public export set changes)
  README.md               # update contents list
```

State ownership options (choose the lower-risk one):
- **Preferred (props-lifting):** keep all `useState` in `SettingsPage.tsx`; pass value +
  setter (or `onChange`) props into each `*Section` component. Section components stay
  pure/presentational. `handleSave` remains in the orchestrator, unchanged. This guarantees
  the save payload cannot drift.
- Alternative (per-section local state + `getPayload()`): more encapsulated but risks
  payload drift; only pursue if a section is fully self-contained (e.g. Project Management,
  Available Skills, which do **not** contribute to `handleSave`).

Shared style: move `inputStyle`/`labelStyle` verbatim into `settingsStyles.ts` and import
where needed. Do not change values.

Contract guardrail: `handleSave` and the 24-key object literal must remain in
`SettingsPage.tsx` verbatim (only the surrounding component shrinks around it). Add a unit
test asserting the exact key set and the two derivations.

i18n policy: extracting hardcoded labels into i18n keys is **optional** and, if done, every
new key MUST be added to all three of `en.ts`/`ja.ts`/`zh.ts` so
`scripts/docs/check_i18n_js.py` parity stays green. If in doubt, leave labels as-is (this
subtask's mandate is decomposition, not translation completeness).

## 8. Concrete Work Items

1. Create `settingsStyles.ts` exporting `inputStyle` and `labelStyle` (moved verbatim from
   `SettingsPage.tsx:337-352`). Update `SettingsPage.tsx` to import them.
2. Create `sections/LanguageSection.tsx` from `SettingsPage.tsx:368-380`. Props:
   `lang`, `onChange`.
3. Create `sections/LlmBackendSection.tsx` from `:382-478`. Props for provider, model
   select/custom, temperature, apiKey, baseUrl, and `currentModels`; keep the
   `handleProviderChange`/`handleModelSelectChange` logic either passed in or colocated (it
   only mutates local state, so passing setters is fine).
4. Create `sections/PaperRetrievalSection.tsx` from `:480-509`.
5. Create `sections/VlmReviewSection.tsx` from `:511-523` (note: model list is derived from
   `PROVIDER_MODELS[provider]`, so it needs `provider` as a prop).
6. Create `sections/MemorySection.tsx` from `:525-695` — the largest section: Letta base
   url/key, two-stage embedding provider/model picker, `CUSTOM_HANDLE_VALUE` branch,
   letta-free warning, deployment selector, and the Restart button (which calls
   `restartLetta(lettaDeployment)` and manages `lettaRestarting`/`lettaRestartMsg`).
7. Create `sections/SlurmSection.tsx` from `:697-770` (partition multi-select + `Detect`).
8. Create `sections/ContainerSection.tsx` from `:772-827` (mode, pull policy, image, Detect
   Runtime).
9. Create `sections/SkillsSection.tsx` from `:829-877` (read-only skills table; move the
   `SkillInfo` interface into `settingsTypes.ts` or keep local).
10. Create `sections/SshSection.tsx` from `:879-943` (host/port/user/path/key + Test SSH).
11. Create `sections/ProjectManagementSection.tsx` from `:945-1035` (checkpoint list +
    delete). Keep `handleDeleteProject`'s `confirm(...)` guard and
    `refreshCheckpoints()`/`loadProjects()` calls.
12. Reduce `SettingsPage.tsx` to: state hooks, `loadSettings/loadSkills/loadProjects`,
    `handleSave/handleTestLLM/handleTestSSH/handleDetectPartitions/handleDetectRuntime`,
    `handleProviderChange/handleModelSelectChange/handleLangChange/handleDeleteProject`,
    and a render tree that composes the 10 `<*Section>` components inside the existing
    `<div style={{...gap:'16px'}}>` and keeps the Status banner (`:358-365`) and Action
    buttons (`:1037-1045`).
13. Add `sections/` files to `components/Settings/index.ts` only if any need to be exported
    beyond `SettingsPage`; otherwise leave the default export path intact.
14. Update `components/Settings/README.md` contents list to enumerate the new files.
15. Add `components/Settings/__tests__/SettingsPage.test.tsx` (Vitest + Testing Library +
    jsdom, matching the PaperBench test pattern): (a) render `SettingsPage` with mocked
    `services/api`, (b) assert the save handler posts exactly the 24 keys with correct
    model and `letta_embedding_config` derivations, (c) a `_splitHandle` round-trip unit
    assertion.
16. (Optional, only with full en/ja/zh parity) replace the three hardcoded `Card` titles
    and inline labels with i18n keys.
17. Add a short code comment near the `Settings` interface usage documenting that per-phase
    model fields are intentionally edited in `Wizard/StepResources.tsx`, not here.

## 9. Files Expected to Change

Modified:
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` (shrinks from 1049
  to a thin orchestrator).
- `ari-core/ari/viz/frontend/src/components/Settings/index.ts` (barrel; update only if
  export set changes).
- `ari-core/ari/viz/frontend/src/components/Settings/README.md` (contents list).
- (Optional, only if item 16 is done) `ari-core/ari/viz/frontend/src/i18n/en.ts`,
  `.../i18n/ja.ts`, `.../i18n/zh.ts` — add matching keys to all three.

Created:
- `ari-core/ari/viz/frontend/src/components/Settings/settingsStyles.ts`
- `ari-core/ari/viz/frontend/src/components/Settings/settingsTypes.ts` (optional)
- `ari-core/ari/viz/frontend/src/components/Settings/sections/LanguageSection.tsx`
- `.../sections/LlmBackendSection.tsx`
- `.../sections/PaperRetrievalSection.tsx`
- `.../sections/VlmReviewSection.tsx`
- `.../sections/MemorySection.tsx`
- `.../sections/SlurmSection.tsx`
- `.../sections/ContainerSection.tsx`
- `.../sections/SkillsSection.tsx`
- `.../sections/SshSection.tsx`
- `.../sections/ProjectManagementSection.tsx`
- `.../components/Settings/__tests__/SettingsPage.test.tsx`

Unchanged (do NOT edit): `settingsConstants.ts`, `types/index.ts`, `services/api.ts`,
`context/AppContext.tsx`, `App.tsx`, `Layout/Sidebar.tsx`, and all backend Python.

## 10. Files / APIs That Must Not Be Broken

- **Dashboard API contract** `GET /api/settings` and `POST /api/settings`
  (`routes.py:853,1035` → `api_settings.py:119,202`): the POST body must remain the same
  24-key flat object with identical value semantics. The GET response shape consumed via
  `fetchSettings()` must keep being read by the same field names.
- **`GET/POST /api/env-keys`** (`routes.py:746,1060`) — untouched.
- **`Settings` TypeScript interface** (`types/index.ts:38-75`) — field names are the wire
  contract to the backend env mapping (`ARI_LLM_MODEL`, `ARI_BACKEND`, `OLLAMA_HOST`,
  `ARI_RETRIEVAL_BACKEND`, `LETTA_BASE_URL`, `LETTA_EMBEDDING_CONFIG`, SLURM/SSH/container
  keys). Do not rename or drop fields.
- **`services/api.ts` wrapper signatures** used here (`fetchSettings`, `saveSettings`,
  `restartLetta(path)`, `fetchSkills`, `testSSH`, `fetchPartitions`,
  `fetchContainerInfo`, `generateConfig`, `deleteCheckpoint`, `fetchCheckpoints`) — call
  them exactly as today.
- **Hash route `'settings'`** in `App.tsx` `PAGE_MAP` and `Sidebar.tsx` `NAV_ITEMS` — the
  default export of `components/Settings` (via lazy import) must keep resolving.
- **i18n key parity gate** — `scripts/docs/check_i18n_js.py` must stay green; no key may
  exist in one locale but not the others.
- **`_splitHandle` round-trip** for `letta_embedding_config` — saved handle must split back
  to the same provider/model on reload (`SettingsPage.tsx:152-156` ↔ `230-233`).
- **`ari.public.*` API, CLI `ari`, MCP `ari-skill-*` servers, checkpoint/config file
  formats** — not touched by this subtask; must remain untouched.

## 11. Compatibility Constraints

- Pure frontend refactor: no backend, route, schema, or env-var mapping changes. The
  server continues to persist to environment/`.env` (not `settings.json`), so no migration
  is involved.
- The refactor must be a semantics-preserving move: same DOM (same `Card` sections, same
  inline styles, same `t(...)` keys), same fetch calls, same conditional rendering (e.g.
  API Key hidden for `ollama`, Base URL shown for `ollama`/`cli-shim`, letta-free warning,
  restart single-flight).
- No new npm dependency and no version bump to `frontend/package.json` (React 18.3 / Vite 5
  / Vitest 2 stack is fixed). Only `react`/`react-dom` and existing test libs may be used.
- If i18n keys are added (optional), they MUST land in all three locale files in the same
  commit to keep `en.ts`/`ja.ts`/`zh.ts` parity (currently 444/441/441 lines).
- No change to authentication/secret handling — the panel stays same-origin, unauthenticated
  exactly as today; security posture is deliberately unchanged (see Non-Goals).

## 12. Tests to Run

Backend/repo-wide (should be unaffected, run as guardrail):
- `python -m compileall .`
- `pytest -q`
- `ruff check .`

Frontend (run from `ari-core/ari/viz/frontend/`; `npm`, not `pnpm`):
- `npm run typecheck` (tsc; must pass — the strongest guard that no prop/type drift
  occurred)
- `npm test` (Vitest 2 + Testing Library + jsdom; includes the new
  `SettingsPage.test.tsx`)
- `npm run build` (Vite production build must succeed)

Optional targeted parity check:
- `python scripts/docs/check_i18n_js.py` (only strictly required if item 16 added keys, but
  cheap to run regardless).

## 13. Acceptance Criteria

1. `SettingsPage.tsx` is reduced to a thin orchestrator (target < ~250 lines) and each of
   the 10 sections lives in its own `sections/*.tsx` file.
2. The `POST /api/settings` payload is byte-identical to the pre-refactor 24-key object
   (verified by the new unit test asserting the exact key set and the `model` /
   `letta_embedding_config` derivations).
3. All rendered sections, conditional fields, warnings, and buttons behave identically
   (manual smoke or component test): provider switch updates model list; ollama hides API
   Key and shows Base URL; letta-free warning renders; Restart is single-flight; SSH/LLM
   test and Detect buttons still call their wrappers; checkpoint delete still confirms and
   refreshes.
4. `npm run typecheck`, `npm test`, and `npm run build` all pass.
5. i18n key parity across `en/ja/zh` is unchanged or improved; no locale gains a key the
   others lack.
6. `pytest -q`, `python -m compileall .`, and `ruff check .` pass (unaffected, confirming
   no backend was touched).
7. `components/Settings/README.md` and `index.ts` reflect the new file layout.

## 14. Rollback Plan

Single-commit, frontend-only, no data migration. Rollback = `git revert` the refactor
commit (or `git checkout` the previous `components/Settings/` tree plus the optional i18n
edits). Because the backend, routes, `Settings` interface, and persisted `.env`/env format
are untouched, reverting the frontend requires no coordinated backend rollback and no
config/checkpoint fix-up. If only the optional i18n extraction (item 16) is problematic,
revert just the locale files and the label changes while keeping the component split.

## 15. Dependencies

Per the provided DEPENDENCY GRAPH (`059 -> 067, 068, 069, 070, 071, 072, 073`):

- **Direct predecessor:** `059` (the Phase 6 Dashboard UX parent/inventory subtask) — must
  precede `070`.
- **Inventory/gating subtasks that MUST precede any runtime code change** (070 *is* a
  runtime frontend change, see Section 16), from the stated must-precede list: `001`, `002`,
  `020`, `036`, `045`, `053`, `059`, `060`, `067`. In particular `060` and `067` are
  siblings under `059` that gate runtime edits in this phase, so `070` depends on them.
- **Siblings (parallel, no ordering among them):** `068`, `069`, `071`, `072`, `073` are
  other Phase 6 Dashboard UX subtasks under `059`; `070` does not depend on them and they do
  not depend on `070`. Coordinate only to avoid merge conflicts if any also touch
  `components/Settings/` (none is expected to).
- **Downstream:** none in the graph declares a dependency on `070`.

## 16. Risk Level

- **Changes runtime code: YES** — this modifies the React/TypeScript dashboard frontend
  under `ari-core/ari/viz/frontend/src/components/Settings/`.
- **Risk: MEDIUM.** It is a behaviour-preserving decomposition of a single panel with a
  strong compile-time guard (`tsc`) and a new payload test, and it touches no backend,
  route, schema, or persisted format. The residual risk is (a) silently dropping/renaming a
  key in the 24-field save payload, and (b) subtly changing conditional rendering during the
  props-lifting split. Both are mitigated by keeping `handleSave` verbatim in the
  orchestrator and by the new unit test. The panel drives real config persisted to `.env`,
  so a payload regression would misconfigure runs — hence not "Low".

## 17. Notes for Implementer

- Prefer the **props-lifting** design (Section 7): keep all 38 `useState` and `handleSave`
  in `SettingsPage.tsx`; make `sections/*` presentational. This is the lowest-risk path to
  guaranteeing an identical save payload.
- The save payload has exactly **24 keys** (`SettingsPage.tsx:235-260`):
  `llm_model, llm_backend, llm_base_url, temperature, llm_api_key, semantic_scholar_key,
  retrieval_backend, ssh_host, ssh_port, ssh_user, ssh_path, ssh_key, slurm_partitions,
  slurm_partition, slurm_cpus, slurm_memory_gb, slurm_walltime, container_mode,
  container_image, container_pull, vlm_review_model, letta_base_url, letta_api_key,
  letta_embedding_config`. Note `slurm_partition` is derived as `selectedPartitions[0] ||
  ''`. Do not add/remove keys. `containerRuntime`/`containerVersion`, `skills`,
  `checkpoints`, `sshStatus`, `statusMsg`, `lettaRestart*`, `lang` are UI-only and are
  intentionally **not** in the payload.
- Ground-truth corrections confirmed on 2026-07-01: there are **10** `<Card>` sections (not
  9) and **38** `useState` hooks (not ~30). The Settings files live under
  `components/Settings/` (not `pages/Settings/`).
- Backend reality vs. code comments: `settingsConstants.ts:35-38` says handles are "stored
  on settings.json", but `api_settings.py:183` states there is **no** `settings.json`
  fallback and values map to env/`.env`. Do not "fix" this by adding a `settings.json`; it
  is out of scope. Just be aware the persistence is env-based when writing the test (mock
  `saveSettings`; do not assert on-disk files).
- The stale provider/model tables (`gpt-5.2`, `claude-opus-4-5`, etc. in
  `settingsConstants.ts:9-15`) are **REVIEW_REQUIRED** and handled by a different subtask —
  leave them untouched here.
- `handleTestLLM` (`:273-282`) currently calls `generateConfig('ping')`, which is a
  config-generation call rather than a lightweight ping; this is a known quirk. Preserve the
  behaviour exactly — do not "improve" it in this refactor.
- Do NOT touch the security-sensitive surfaces the inventory flagged (editable/persisted API
  keys, `/api/env-keys` returning secret values). They are explicitly out of scope; changing
  them here would collide with the security-hardening subtasks.
- There is **no** top-level `pyproject.toml` and **no** `sonfigs/` directory anywhere in the
  repo (the "sonfigs" name is a hypothesized typo, not present); the config trio is
  `ari-core/ari/config/` (code) vs `ari-core/ari/configs/` (packaged defaults) vs top-level
  `config/` (rubric data). None of these are involved in this subtask.
- Follow the existing test conventions in `components/PaperBench/__tests__/` (Vitest,
  Testing Library, jsdom) when adding `SettingsPage.test.tsx`.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **070** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
