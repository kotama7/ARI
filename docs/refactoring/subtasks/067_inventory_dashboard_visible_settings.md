# Subtask 067: Inventory Dashboard Visible Settings

> Phase 6: Dashboard UX · Risk: Low · Runtime code change: **No** · Depends on: 059 (inventory_dashboard_frontend_backend_structure)
>
> Planning document only. Nothing in this subtask modifies runtime code, imports,
> prompts, configs, workflows, frontend, or directory names. Its single deliverable
> is a **read-only inventory** of every user-visible setting the dashboard exposes,
> together with the state variable, wire key, backend field, i18n label, and a
> sensitivity classification for each. All paths are repository-real and verified
> against the tree at planning date 2026-07-01 (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, machine-checkable inventory of the dashboard's user-visible
settings surface** so that the downstream Phase-6 UX work (068 information
architecture, 069 progressive disclosure, 070 settings-panel refactor, 071
developer mode, 072 empty/loading/error states) can be executed **behind an
unchanged settings contract**. Concretely, 067 delivers one reference artifact that
enumerates, for every visible control on the Settings page (and the settings-shaped
controls that live outside it):

1. the section (`<Card>`) it belongs to and its exact source location in
   `SettingsPage.tsx`,
2. the control type (select / password input / text input / number input / radio /
   multi-select / button / read-only table / delete action),
3. the React state variable that backs it (`SettingsPage.tsx:44-114`),
4. the settings.json key it is **read from** on load (`loadSettings`,
   `SettingsPage.tsx:118-160`) and the key it is **written to** on save
   (`handleSave`, `SettingsPage.tsx:235-260`) — these are not always symmetric,
5. the backend default/field it maps to in `api_settings.py`
   (`_api_get_settings` `:119-196`, `_api_save_settings` `:202-231`),
6. the i18n label key (or a note that the label is **hardcoded English**),
7. a **sensitivity/danger classification** (cosmetic / operational / secret /
   destructive), and
8. a KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED
   recommendation **for downstream subtasks only** — 067 changes nothing.

This inventory is the **frozen baseline** that subtasks 068, 069, 070, 071, and 072
consume. Per `docs/refactoring/007_subtask_index.md:114`, 067's deliverable is the
"Visible-settings inventory", and per `007_subtask_index.md:125` and `:275` it is one
of the inventory subtasks that must precede any runtime code change in this phase
(alongside 001, 002, 020, 036, 045, 053, 059, 060).

## 2. Background

The dashboard Settings page is a single god-component:
`ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` (**1049 LOC**,
one default-exported `SettingsPage()` with **~30 `useState` hooks** declared inline
at `:44-114`). It renders **9 `<Card>` sections top-to-bottom with no tabs, no
search, and no grouping by audience** (`:367-1035`), followed by two action buttons
(`:1038-1045`). Its only extracted helper module is
`ari-core/ari/viz/frontend/src/components/Settings/settingsConstants.ts` (**86 LOC**),
which holds the provider/model tables, the Letta embedding table, the
`CUSTOM_HANDLE_VALUE` sentinel, and the pure `_splitHandle` helper
(`settingsConstants.ts:7-86`). A per-directory `README.md` and a barrel `index.ts`
exist under `src/components/Settings/`.

The nine sections, in render order, are:

| # | Section (`<Card>` title) | Source lines | Label source |
|---|---|---|---|
| 1 | Language | `369-380` | i18n `settings_lang_section` / `settings_lang` |
| 2 | LLM Backend | `383-478` | i18n `settings_llm` |
| 3 | Paper Retrieval | `481-509` | i18n `settings_paper` (fields hardcoded) |
| 4 | VLM Figure Review | `512-523` | **hardcoded** `"VLM Figure Review"` |
| 5 | Memory (Letta) | `526-695` | i18n `settings_memory` (+ subkeys) |
| 6 | SLURM / HPC | `698-770` | i18n `settings_slurm` |
| 7 | Container | `773-827` | **hardcoded** `"Container"` |
| 8 | Available Skills (read-only) | `830-877` | i18n `settings_skills` |
| 9 | SSH Remote Host | `880-943` | i18n `settings_ssh` |
| 10 | Project Management | `946-1035` | **hardcoded** `"Project Management"` |

(There are ten `<Card>`s; "9 sections" in the ground-truth context counts the
read-only Skills table plus the destructive Project-Management card together with the
eight editable-settings cards — record the exact count of **10 cards** in the
artifact and note the discrepancy.)

The backend that serves and persists these values is
`ari-core/ari/viz/api_settings.py` (**553 LOC**): `_api_get_settings` (`:119-196`)
returns a defaults dict merged over the project-scoped `settings.json`
(`_st._settings_path`); `_api_save_settings` (`:202-231`) strips API keys, writes them
to `.env` via `_upsert_env_key` (`:77-104`), and persists the rest to the active
checkpoint's `settings.json`. Routes are wired in
`ari-core/ari/viz/routes.py`: `GET /api/settings` (`:853`), `POST /api/settings`
(`:1035`), `GET /api/env-keys` (`:746`), `POST /api/env-keys` (`:1060`),
`GET /api/skills` (`:882`), `GET /api/profiles` (`:867`), `GET /api/rubrics`
(`:752`), `POST /api/memory/restart` (`:1043`), `POST /api/ssh/test` (`:1062`),
`GET /api/container/info` (`:886`), `GET /api/slurm/partitions` (`:898`).

The typed frontend contract is `Settings` in
`ari-core/ari/viz/frontend/src/types/index.ts:38-75` (**35 declared fields**). The FE
client wrappers are in `services/api.ts`: `fetchSettings` (`:372`), `saveSettings`
(`:376`), `fetchEnvKeys` (`:382`), `restartLetta` (`:402`), `fetchSkills` (`:479`),
`generateConfig` (`:524`), `testSSH` (`:555`), `fetchPartitions` (`:565`),
`fetchContainerInfo` (`:596`).

Three structural facts make this inventory necessary before any UX refactor:

- **Read/write asymmetry.** `loadSettings` reads ~23 keys; `handleSave` writes a flat
  **24-key** object (`SettingsPage.tsx:235-260`), but the backend `_api_get_settings`
  defaults declare **many more** fields that this page never renders or writes:
  `slurm_gpus`, `mcp_skills`, `vlm_review_enabled`, `vlm_review_max_iter`,
  `vlm_review_threshold`, `letta_deployment`, `letta_deployment_image`,
  `letta_deployment_venv`, and the entire nested `ors` block
  (`api_settings.py:148-179`).
- **Type/UI drift.** `Settings` declares six per-phase model fields
  (`model_idea`/`model_bfts`/`model_coding`/`model_eval`/`model_paper`/`model_review`,
  `types/index.ts:59-64`) and three VLM fields (`vlm_review_enabled`/`_max_iter`/
  `_threshold`, `:68-71`) that have **no control on this page** — per-phase models are
  edited in the wizard (`components/Wizard/StepResources.tsx`, 1160 LOC), not global
  Settings. This split is exactly what 068 must resolve.
- **Hardcoded, stale-prone data + partial i18n.** The provider/model dropdown lists
  are hardcoded (`settingsConstants.ts:9-15`, e.g. `gpt-5.2`, `claude-opus-4-5`), and
  several section titles and most field labels are hardcoded English rather than i18n
  keys (see Section 6).

The companion Phase-6 planning doc is
`docs/refactoring/014_dashboard_ux_refactoring_plan.md` and the Phase-5 frontend
structure inventory is subtask **059**; 067 is the *settings-specific* inventory that
068/069/070/071/072 consume. There is **no** `SETTINGS.md` or settings-schema file in
the tree today — record that absence rather than assume one.

## 3. Scope

In scope (read-only inventory production only):

- Enumerate **every visible control** across all ten `<Card>`s of
  `SettingsPage.tsx:367-1035`, plus the two action buttons (`Save`,
  `Test LLM`, `:1038-1045`) and every inline `Detect` / `Test` / `Restart` /
  `Delete` button (`:707`, `:812`, `:649`, `:928`, `:1016`, `:1042`).
- For each control record: section, source line, control type, backing state
  variable (`:44-114`), read key (`loadSettings` `:118-160`), write key (`handleSave`
  `:235-260`), backend default/field (`_api_get_settings` `:137-180`), i18n key or
  "hardcoded", and default value.
- Record the **read/write/backend asymmetry**: list every `Settings` field
  (`types/index.ts:38-75`) and every backend default (`api_settings.py:137-180`) that
  has **no UI control** here, and every UI control whose write key is not read back
  symmetrically (e.g. `llm_backend` vs `llm_provider`; `baseUrl` mapping to either
  `llm_base_url` or `ollama_host`, `SettingsPage.tsx:130`,`:238`).
- Classify each control by **sensitivity**: cosmetic (Language), operational (SLURM,
  Container, SSH, Letta base URL, retrieval backend), **secret** (API keys,
  Semantic Scholar key, Letta API key — password inputs written to `.env`), and
  **destructive** (Project Management delete `:1016-1027`, Letta Restart
  `:649-674`, GPU-monitor auto-resubmit is *not* on this page — cross-reference it,
  do not include as an in-page control).
- Explicitly inventory the **secret-exposure surface** touching Settings: API-key
  password inputs (`SettingsPage.tsx:445-456`, `:501-508`, `:538-547`), the
  `/api/env-keys` reader that returns actual secret values to the browser
  (`api_settings.py:40-73`, FE wrapper `services/api.ts:382`), and the `.env` write
  path (`_api_save_settings` `:202-231` → `_upsert_env_key` `:77-104`). Flag as
  REVIEW_REQUIRED for 069/071; do **not** change behavior.
- Record the **i18n-coverage gap**: which section titles/labels use i18n keys
  (`i18n/en.ts:134-190`, `:279`, `:320-328`) versus which are hardcoded English, and
  the existing key drift (`en.ts` 444 lines vs `ja.ts`/`zh.ts` 441).
- Cross-reference (as inventory metadata, not in-scope controls) the settings-shaped
  surfaces that live outside this page: per-phase models + `autoReadApiKey` in
  `components/Wizard/StepResources.tsx`, and the ORS model block in
  `_api_get_settings.ors` (`api_settings.py:168-179`) surfaced through the PaperBench
  wizard.
- Emit a per-control master-vocabulary recommendation (KEEP / ADAPT / MERGE /
  MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED) as **advice for 068-072 only**.

## 4. Non-Goals

- **Do not** modify `SettingsPage.tsx`, `settingsConstants.ts`, `types/index.ts`,
  `services/api.ts`, `api_settings.py`, `routes.py`, or any i18n file. 067 is
  read-only; the entire point is a frozen baseline.
- **Do not** implement the information-architecture regrouping (that is **068**), the
  progressive-disclosure / advanced-section hiding (**069**), the settings-panel
  decomposition (**070**), the developer-mode gate for secret/raw controls (**071**),
  or the empty/loading/error-state work (**072**).
- **Do not** "fix" any of the hazards found during inventory: the hardcoded stale
  model lists, the read/write asymmetry, the API-key-to-`.env` flow, the
  `/api/env-keys` secret exposure, or the partial i18n. Record them as
  REVIEW_REQUIRED findings for 069/070/071; resolving them is out of scope here.
- **Do not** change the `/api/settings` request/response shape, the `settings.json`
  format, or the `.env` write behavior. These are dashboard-API / config-file
  contracts that must survive unchanged (Section 10).
- **Do not** add per-phase model controls or ORS controls to the Settings page; only
  document that they exist elsewhere.
- **Do not** touch `ari.public.*`, the CLI, MCP `ari-skill-*` servers, or checkpoint
  formats — none are part of the settings surface being inventoried.

## 5. Current Files / Directories to Inspect

All paths are repository-real (verified 2026-07-01). Line counts are exact.

Frontend — settings surface:
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` — **1049 LOC**,
  the single god-component. State cluster `:44-114`; `loadSettings` `:118-160`;
  `handleSave` (24-key payload) `:235-260`; ten `<Card>`s `:367-1035`; action buttons
  `:1038-1045`.
- `ari-core/ari/viz/frontend/src/components/Settings/settingsConstants.ts` — **86 LOC**,
  `DEFAULT_PROVIDER` `:7`, `PROVIDER_MODELS` `:9-15`, `PROVIDER_KEY_PLACEHOLDER`
  `:17-23`, `LETTA_EMBEDDING_BY_PROVIDER` `:42-60`, `LETTA_EMBED_PROVIDERS` `:67`,
  `CUSTOM_HANDLE_VALUE` `:69`, `_splitHandle` `:71-86`.
- `ari-core/ari/viz/frontend/src/components/Settings/README.md` — per-dir doc.
- `ari-core/ari/viz/frontend/src/components/Settings/index.ts` — barrel export.
- `ari-core/ari/viz/frontend/src/types/index.ts` — **264 LOC**; `Settings` interface
  (35 fields) `:38-75`; `Checkpoint` `:24-36`.
- `ari-core/ari/viz/frontend/src/services/api.ts` — **863 LOC**; settings wrappers:
  `fetchSettings` `:372`, `saveSettings` `:376`, `fetchEnvKeys` `:382`, `restartLetta`
  `:402`, `fetchSkills` `:479`, `generateConfig` `:524`, `testSSH` `:555`,
  `fetchPartitions` `:565`, `fetchContainerInfo` `:596`.
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` — **120 LOC**; supplies
  `state` and `refreshCheckpoints` consumed by SettingsPage (`SettingsPage.tsx:42`).
- `ari-core/ari/viz/frontend/src/i18n/en.ts` — **444 LOC**; settings keys at
  `:134-158`, `:159-160`, `:186-191`, `:279`, `:320-328`.
- `ari-core/ari/viz/frontend/src/i18n/ja.ts` — **441 LOC** (key-drift baseline).
- `ari-core/ari/viz/frontend/src/i18n/zh.ts` — **441 LOC** (key-drift baseline).
- `ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` — **1160 LOC**;
  cross-reference for per-phase models + `autoReadApiKey`. Inspect, do not include as
  in-page controls.

Backend — settings persistence + wiring:
- `ari-core/ari/viz/api_settings.py` — **553 LOC**; `_api_get_env_keys` `:40-73`,
  `_upsert_env_key` `:77-104`, `_api_save_env_key` `:107-115`, `_api_get_settings`
  `:119-196`, `_api_save_settings` `:202-231`, `_api_skills` `:466-498`,
  `_api_profiles` `:505-511`, `_api_rubrics` `:523-551`.
- `ari-core/ari/viz/routes.py` — **1197 LOC**; settings route branches at `:746`,
  `:752`, `:853`, `:867`, `:882`, `:886`, `:898`, `:1035`, `:1043`, `:1060`, `:1062`.

Companion / context docs (read-only, cross-reference — do not edit):
- `docs/refactoring/014_dashboard_ux_refactoring_plan.md` — Phase-6 UX plan.
- `docs/refactoring/007_subtask_index.md` — index (`:114` names this subtask).
- The 059 frontend-structure inventory artifact (produced by subtask 059) once
  available, under `docs/refactoring/reports/`.

## 6. Current Problems

Problems to **record** (not fix). Each is a REVIEW_REQUIRED finding routed to a
downstream subtask.

1. **Flat, audience-agnostic layout.** Ten `<Card>`s render top-to-bottom with no
   tabs/search/grouping (`SettingsPage.tsx:367-1035`). Cosmetic (Language), secret
   (API keys), operational (SLURM/SSH/Container), and destructive (project delete,
   Letta restart) controls sit at the same visual level. → routes to **068/069**.
2. **God-component.** One 1049-LOC component with ~30 `useState` hooks (`:44-114`),
   inline `CSSProperties` styles (`:337-352`), and ten inline sections; no
   per-section subcomponents. → routes to **070**.
3. **Read/write/backend asymmetry.** `handleSave` writes 24 keys (`:235-260`) but the
   backend defaults declare `slurm_gpus`, `mcp_skills`, `vlm_review_enabled/max_iter/
   threshold`, `letta_deployment{,_image,_venv}`, and a nested `ors` block
   (`api_settings.py:148-179`) that this page neither reads nor writes; and `Settings`
   declares six `model_*` fields + three `vlm_review_*` fields (`types/index.ts:59-71`)
   with no control here. → routes to **068**.
4. **Non-symmetric key mapping.** `baseUrl` is read from `llm_base_url` **or**
   `ollama_host` depending on provider (`:130`) but always written as `llm_base_url`
   (`:238`); `provider` is read from `llm_backend` **or** `llm_provider` (`:124`) and
   written only as `llm_backend` (`:237`), while `slurm_partition` is written as
   `selectedPartitions[0]` alongside `slurm_partitions` (`:248-249`). Record these
   exact mappings. → routes to **068/070**.
5. **Secret exposure.** API keys, Semantic Scholar key, and Letta API key are editable
   password inputs (`:445-456`, `:501-508`, `:538-547`) persisted to `.env`
   (`_api_save_settings:202-231` → `_upsert_env_key:77-104`); `/api/env-keys` returns
   **actual secret values** to the browser (`api_settings.py:40-73`, FE wrapper
   `services/api.ts:382`). No auth/token on any dashboard call. → routes to
   **069/071** (behind a developer-mode / masking gate).
6. **Destructive controls guarded only by `window.confirm`.** Project delete
   (`:298-311`, `:1016-1027`) and Letta Restart (stop+start of a daemon, `:649-674`)
   are single-`confirm` actions inline with cosmetic settings. → routes to **069/071**.
7. **Hardcoded, stale-prone dropdown data.** `PROVIDER_MODELS` and
   `LETTA_EMBEDDING_BY_PROVIDER` are hardcoded (`settingsConstants.ts:9-15`,`:42-60`,
   e.g. `gpt-5.2`, `claude-opus-4-5`) and drift from reality. → routes to **070**
   (source from backend or a shared table).
8. **Partial i18n.** Section titles `"VLM Figure Review"` (`:512`), `"Container"`
   (`:773`), `"Project Management"` (`:946`) and many field labels (`"API Key"`,
   `"Base URL …"`, `"Paper Retrieval Backend"`, `"Semantic Scholar API Key"`,
   `"Memory (GB)"`, `"Mode"`, `"Pull Policy"`, `"Image"`, `"Host"`, `"Port"`,
   `"Remote ARI Path"`, `"SSH Key Path"`, `"Detect"`, `"Test SSH"`,
   `"Detect Runtime"`, `"Delete"`) are hardcoded English, while others use i18n keys.
   i18n files also drift: `en.ts` 444 vs `ja.ts`/`zh.ts` 441. → routes to **068/070**.
9. **Card-count ambiguity.** The ground-truth "9 sections" undercounts the ten
   `<Card>`s (the read-only Skills table and the destructive Project-Management card
   are both cards). The inventory must state **10 cards** and label each by audience.

## 7. Proposed Design / Policy

067 produces **one inventory artifact** and defines the schema every later Phase-6
subtask reads from. It proposes **no runtime change**.

**Deliverable location & format.** Write a single reference artifact under
`docs/refactoring/reports/` (an inventory document, consistent with how sibling
inventory subtasks 020/059 deliver — not a code change). Suggested filename:
`docs/refactoring/reports/067_dashboard_visible_settings_inventory.md`, optionally
paired with a machine-readable `067_dashboard_visible_settings_inventory.json`
(strict data twin) so 073's UX regression checks can diff it. The `.md` is
authoritative; the `.json` mirrors it.

**Inventory schema (one row per visible control).** Each row records:

| Field | Source of truth |
|---|---|
| `section` | `<Card>` title (`SettingsPage.tsx`) |
| `control_id` | stable slug, e.g. `llm.provider`, `memory.embedding_model` |
| `source_line` | `SettingsPage.tsx` line |
| `control_type` | select / password / text / number / radio / multiselect / button / table / delete |
| `state_var` | `useState` name (`:44-114`) |
| `read_key` | key in `loadSettings` (`:118-160`) or "n/a" |
| `write_key` | key in `handleSave` (`:235-260`) or "not persisted" |
| `backend_field` | default in `_api_get_settings` (`:137-180`) or "absent" |
| `label_source` | i18n key (`i18n/en.ts`) or "hardcoded:<text>" |
| `default` | default value on load |
| `sensitivity` | cosmetic / operational / secret / destructive |
| `recommendation` | KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED |
| `routes_to` | downstream subtask id(s) 068-072 |

**Sensitivity taxonomy (proposed, for 069/071 to consume).**
- *cosmetic* — Language (`:369-380`). Always visible.
- *operational* — retrieval backend, VLM model, Letta base URL / embedding /
  deployment, SLURM partitions/cpus/mem/walltime, Container mode/pull/image, SSH
  host/port/user/path/key. Candidate "advanced" grouping (069).
- *secret* — LLM API key, Semantic Scholar key, Letta API key. Candidate
  developer-mode / masked grouping (071).
- *destructive* — Letta Restart, project delete. Candidate confirm-gate / dev-mode
  (071).

**Companion inventories to reference (not duplicate).** The read/write/backend
asymmetry table (Section 6, items 3-4) and the settings-shaped surfaces outside this
page (StepResources per-phase models; ORS block) are recorded as appendices so 068's
information-architecture design has the full picture without re-deriving it.

**Classification defaults (recommendations only).** Every editable control →
**KEEP** the setting semantics; **ADAPT** its placement/label/gating under 068-071.
The three secret inputs and the two destructive actions → **REVIEW_REQUIRED** for a
developer-mode/masking gate. The hardcoded model tables → **REVIEW_REQUIRED** for a
backend-sourced list (070). The `model_*`/`vlm_review_*` type fields with no UI →
**REVIEW_REQUIRED** for 068 (decide: surface here, keep in wizard, or document as
wizard-only). Nothing is proposed for DELETE.

## 8. Concrete Work Items

1. **Read the settings surface end to end.** `SettingsPage.tsx` (all 1049 lines),
   `settingsConstants.ts`, `types/index.ts:38-75`, `api_settings.py:119-231`, and the
   route branches in `routes.py` listed in Section 5.
2. **Enumerate every control.** Produce the one-row-per-control table using the
   schema in Section 7, walking `<Card>`s in render order (`:369`, `:383`, `:481`,
   `:512`, `:526`, `:698`, `:773`, `:830`, `:880`, `:946`) and the action/inline
   buttons (`:707`, `:812`, `:649`, `:928`, `:1016`, `:1042`).
3. **Fill the wire mapping.** For each control, capture `state_var` (`:44-114`),
   `read_key` (`:118-160`), `write_key` (`:235-260`), and `backend_field`
   (`:137-180`). Mark "not persisted" (e.g. `lettaDeployment` is sent only to
   `restartLetta`, `:657`, never in the Save payload) and "read-only" (Skills table,
   Project list) explicitly.
4. **Build the asymmetry appendix.** List (a) `Settings` fields with no control
   (`types/index.ts:59-64`,`:68-71`), (b) backend defaults with no control
   (`api_settings.py:148-179`), (c) non-symmetric mappings (`baseUrl`/`ollama_host`;
   `llm_backend`/`llm_provider`; `slurm_partition`/`slurm_partitions`).
5. **Build the secret-exposure appendix.** Enumerate the three password inputs, the
   `.env` write path (`_upsert_env_key:77-104`), and `/api/env-keys` returning live
   secrets (`_api_get_env_keys:40-73`). Mark REVIEW_REQUIRED → 069/071.
6. **Build the i18n-coverage appendix.** For each section title and field label,
   record i18n-key vs hardcoded (Section 6, item 8), and note the `en/ja/zh` key
   drift (444 vs 441).
7. **Build the "settings elsewhere" appendix.** Cross-reference per-phase models +
   `autoReadApiKey` in `StepResources.tsx` and the `ors` block
   (`api_settings.py:168-179`); mark as inventory metadata, not in-page controls.
8. **Assign sensitivity + recommendation** to every row per Section 7 taxonomy, with
   `routes_to` set to the consuming subtask (068-072).
9. **Emit the artifact** to `docs/refactoring/reports/` (`.md` authoritative, optional
   `.json` twin). Add a one-line pointer to it from this subtask on completion (in the
   artifact's own header, not by editing other planning docs).
10. **Self-check** the artifact against the acceptance criteria in Section 13
   (control count matches the ten cards; every control has all schema fields; no
   runtime file modified).

## 9. Files Expected to Change

**Runtime code / configs / frontend:** none. This subtask changes **no** runtime
file. (Runtime code change: **No** — see Section 16.)

**New (inventory artifact only), under the already-existing reports dir:**
- `docs/refactoring/reports/067_dashboard_visible_settings_inventory.md` — the
  authoritative inventory (new file).
- `docs/refactoring/reports/067_dashboard_visible_settings_inventory.json`
  *(optional)* — strict machine-readable twin for 073's regression diff.

**Read-only inputs (inspected, not modified):** all files listed in Section 5 —
`SettingsPage.tsx`, `settingsConstants.ts`, `types/index.ts`, `services/api.ts`,
`context/AppContext.tsx`, `i18n/{en,ja,zh}.ts`, `Wizard/StepResources.tsx`,
`api_settings.py`, `routes.py`.

## 10. Files / APIs That Must Not Be Broken

067 is read-only, so nothing is at risk from *this* subtask; this list is the
contract the artifact must document as **preserve-unchanged** for the downstream
implementers (068-072):

- **Dashboard API contract.** `GET/POST /api/settings`
  (`routes.py:853`,`:1035`; `api_settings.py:119-231`), `GET/POST /api/env-keys`
  (`:746`,`:1060`), `GET /api/skills` (`:882`), `GET /api/profiles` (`:867`),
  `GET /api/rubrics` (`:752`), `POST /api/memory/restart` (`:1043`),
  `POST /api/ssh/test` (`:1062`), `GET /api/container/info` (`:886`),
  `GET /api/slurm/partitions` (`:898`). Request/response shapes must stay stable.
- **`settings.json` file format.** Project-scoped JSON written by
  `_api_save_settings` to `_st._settings_path` (`api_settings.py:229-230`).
- **`.env` write behavior.** `_upsert_env_key` quoting split (quoted for the env-key
  editor, unquoted for the settings API-key path — `api_settings.py:90`,`:114`,`:219`).
- **FE client contract.** `services/api.ts` wrappers and the `Settings` type
  (`types/index.ts:38-75`) that PaperBench and other pages compile against.
- **i18n key contract.** Existing settings keys in `i18n/en.ts` (any rename must be
  mirrored to `ja.ts`/`zh.ts` — enforced by `scripts/docs/check_i18n_js.py`).
- **CLI `ari`, `ari.public.*`, MCP `ari-skill-*`, checkpoint format** — untouched by
  the settings surface; listed for completeness.

## 11. Compatibility Constraints

- **Planning-only.** 067 introduces no compatibility surface of its own. The artifact
  it produces must be explicit that every downstream change to the settings UI is an
  **ADAPT** behind the unchanged `/api/settings` + `settings.json` + `.env` contracts;
  any re-layout, re-labeling, or gating in 068-071 must keep the same wire keys and
  persisted shape unless a compatibility-adapter note is written in that subtask.
- The inventory must flag that the `Settings` type (`types/index.ts:38-75`) is a
  **shared** contract (imported outside SettingsPage); dropping fields from it is a
  breaking change requiring a deprecation/adapter note in the owning subtask, not here.
- The artifact must not rename or re-key any i18n entry; it only records the current
  key↔label mapping so 070's re-labeling stays reversible.

## 12. Tests to Run

Because 067 changes no runtime code, tests are used only to confirm the tree is
untouched and the repo still builds:

- `python -m compileall .` — sanity that no `.py` was touched.
- `ruff check .` — lint unchanged (ruff is available; radon is not).
- `pytest -q` — full suite must remain green (no runtime change expected). The
  settings-relevant tests to eyeball are the viz/GUI suites noted in the ground truth
  (`ari-core/tests/test_server.py`, `test_gui_errors.py`).
- Frontend (from `ari-core/ari/viz/frontend/`, npm — **no pnpm**):
  - `npm run typecheck` — `types/index.ts`/`SettingsPage.tsx` unchanged, still typechecks.
  - `npm test` — Vitest suite (`__tests__` present) stays green.
  - `npm run build` — Vite build unaffected.
- `python scripts/docs/check_i18n_js.py` (if the artifact touches nothing i18n, this
  is a no-op guard confirming key parity is unchanged).

All of the above should be **no-ops** with respect to diffs; any failure indicates an
accidental edit outside the artifact.

## 13. Acceptance Criteria

1. `docs/refactoring/reports/067_dashboard_visible_settings_inventory.md` exists and
   is self-contained.
2. Every visible control across the **ten `<Card>`s** of `SettingsPage.tsx:367-1035`
   plus the two action buttons and all inline Detect/Test/Restart/Delete buttons is a
   row in the inventory, each with **all** schema fields from Section 7 populated (no
   blanks; use "n/a"/"absent"/"not persisted" explicitly).
3. The read/write/backend asymmetry appendix lists every `Settings` field with no UI
   (`types/index.ts:59-71`), every backend default with no UI (`api_settings.py:148-179`),
   and the three non-symmetric mappings (Section 6, item 4).
4. The secret-exposure appendix, i18n-coverage appendix, and "settings elsewhere"
   appendix are present and cite exact lines.
5. Every row carries a sensitivity label and a master-vocabulary recommendation with a
   `routes_to` subtask id (068-072).
6. `git status` shows changes **only** under `docs/refactoring/reports/` (the artifact
   file(s)); no runtime/frontend/config file is modified.
7. `python -m compileall .`, `ruff check .`, `pytest -q`, and (frontend)
   `npm run typecheck` / `npm test` / `npm run build` all pass unchanged.

## 14. Rollback Plan

Trivial and low-risk: the only artifact is a new markdown (optionally JSON) file under
`docs/refactoring/reports/`. To roll back, delete
`docs/refactoring/reports/067_dashboard_visible_settings_inventory.md` (and the
optional `.json`) — `git rm` / `git checkout`. No runtime code, config, workflow, or
frontend file is touched, so there is nothing else to revert and no migration to
undo. Downstream subtasks (068-072) that would consume this artifact simply block
until it is re-produced.

## 15. Dependencies

Per the dependency graph (`059 -> 067`; and `007_subtask_index.md:114`,`:445`):

- **Depends on: 059** (`inventory_dashboard_frontend_backend_structure`) — 067 reuses
  059's stack/structure inventory of `ari-core/ari/viz/frontend/` (Vite 5 + React 18.3
  + hash router + single `AppContext`) as the frame for the settings inventory. 059 is
  itself a root inventory (no upstream dependency) and one of the inventory subtasks
  that must precede any runtime change.
- **Enables (downstream consumers of 067's artifact):** 068
  (`define_dashboard_information_architecture`), 069
  (`design_dashboard_progressive_disclosure`), 070
  (`refactor_dashboard_settings_panel`, High risk — the panel refactor that must
  preserve the `/api/settings` contract), 071 (`add_dashboard_developer_mode`, the
  gate for secret/destructive/raw controls), 072
  (`improve_dashboard_empty_loading_error_states`), and 073
  (`add_dashboard_ux_regression_checks`, which can diff the optional `.json` twin).
- **Sibling context (not a hard dependency):** 060
  (`inventory_dashboard_api_contracts`) overlaps on the `/api/settings` wire contract;
  cite it, do not re-derive it. 067 and 060 are both `059`-rooted inventories.
- No dependency on Phases 1-4/5 refactor subtasks; 067 only reads current `main`.

## 16. Risk Level

**Low.** **Runtime code change: No.** 067 is a read-only inventory whose sole output
is a documentation artifact under `docs/refactoring/reports/`. There is no change to
runtime code, imports, prompts, configs, workflows, the frontend, or directory names,
and therefore no behavioral or contract risk. The only residual risk is inventory
*accuracy* (missing a control or mis-mapping a wire key), mitigated by the
per-`<Card>` walk in Section 8 and the completeness check in Section 13. The mistakes
this subtask most guards against are downstream: an inaccurate inventory could let
070 silently drop a `settings.json` key or 071 mis-gate a secret control — hence the
emphasis on exact read/write/backend mapping.

## 17. Notes for Implementer

- **Do not edit any runtime file.** If you catch yourself "just fixing" the hardcoded
  model list, the API-key exposure, or the partial i18n, stop — those are 069/070/071.
  067 only *documents* them.
- **Walk the ten `<Card>`s in render order** and keep the `control_id` slugs stable
  (`section.field`) — 073 will key its regression diff off them.
- **Watch the non-obvious mappings** already found: `lettaDeployment` is *not* in the
  Save payload (sent only to `restartLetta`, `SettingsPage.tsx:657`); `baseUrl` reads
  from `ollama_host` for the ollama provider but writes `llm_base_url` (`:130`,`:238`);
  the VLM model dropdown reuses `PROVIDER_MODELS[provider]` (`:519`) rather than a VLM
  list, so it shows chat models. Record these verbatim.
- **The backend is the source of truth for defaults**, not the FE. When `default`
  differs between `settingsConstants.ts` and `api_settings.py:137-180` (e.g. Letta
  embedding default is `openai/text-embedding-3-small` in the FE state at `:88` but
  `letta-default` in the backend at `:164`), record **both** and flag the mismatch.
- **"sonfigs" does not exist** — the config concern is `ari-core/ari/config/` (code)
  vs `ari-core/ari/configs/` (packaged defaults) vs top-level `ari-core/config/`
  (rubric data). None of these is the settings store; the settings store is the
  per-checkpoint `settings.json` plus `.env`. Do not conflate them.
- **node_modules is not committed** (contrary to the older skeleton note): `.gitignore`
  ignores it at line 113; `package-lock.json` is tracked. Do not "clean up" anything
  under `frontend/`.
- **Prefer the `.md` as authoritative**; if you also emit the `.json` twin, keep it a
  strict projection of the table so they can never disagree.
- **Reserve "deprecated"** for the external contracts in Section 10; for internal UI
  controls use the master vocabulary (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/
  DELETE_CANDIDATE/REVIEW_REQUIRED).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **067** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
