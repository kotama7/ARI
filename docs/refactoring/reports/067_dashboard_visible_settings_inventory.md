# Dashboard Visible-Settings Inventory

> **Subtask:** 067 — `inventory_dashboard_visible_settings` (Phase 6: Dashboard UX, Low risk, **no runtime code change**).
> **Status:** Read-only inventory. This document changes no runtime code, imports, prompts, configs, workflows, frontend source, i18n, or directory names. It is the frozen settings baseline consumed by subtasks **068–073**.
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `whole_refactoring` · `ari-core` `0.9.0` · captured 2026-07-01.
> **Depends on:** 059 (`inventory_dashboard_frontend_backend_structure`, `docs/refactoring/reports/dashboard_structure_inventory.md`).
> **Method:** every claim grounded by `Read`/`grep` against the live, unmodified tree. Line numbers are exact at capture. Where a plan/059 figure disagrees with the live tree, the live tree is recorded and the discrepancy noted.
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED. "deprecated" is reserved for external contracts (dashboard API, `settings.json`, `.env`, `Settings` type, i18n keys) — never applied to internal UI controls here.
> **Authoritative vs twin:** this `.md` is authoritative. `067_dashboard_visible_settings_inventory.json` is a strict projection of §3 (control rows) + appendices for 073's regression diff; if they ever disagree, the `.md` wins.

---

## 0. Sources of Truth (verified line anchors)

| File | LOC | Role in settings surface | Key anchors |
|---|---|---|---|
| `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` | **1049** | god-component; renders all cards + actions | state `44-114`; `loadSettings` `118-160`; `handleSave` (24-key POST) `226-269` (payload `235-260`); cards `369-1035`; action bar `1038-1045` |
| `ari-core/ari/viz/frontend/src/components/Settings/settingsConstants.ts` | **86** | provider/model + Letta-embedding tables; `_splitHandle` | `DEFAULT_PROVIDER` `7`; `PROVIDER_MODELS` `9-15`; `PROVIDER_KEY_PLACEHOLDER` `17-23`; `LETTA_EMBEDDING_BY_PROVIDER` `42-60`; `LETTA_EMBED_PROVIDERS` `67`; `CUSTOM_HANDLE_VALUE` `69`; `_splitHandle` `71-86` |
| `ari-core/ari/viz/frontend/src/types/index.ts` | 264 | `Settings` TS contract | `Settings` `38-75` (**36 field declarations**, see §4 note); `Checkpoint` `24-36` |
| `ari-core/ari/viz/frontend/src/services/api.ts` | 863 | FE wrappers | `deleteCheckpoint` `353`; `fetchSettings` `372`; `saveSettings` `376`; `fetchEnvKeys` `382`; `restartLetta` `402`; `fetchRubrics` `~427`; `fetchSkills` `~479`; `generateConfig` `~524`; `testSSH` `~555`; `detectScheduler`/`fetchPartitions` `~561-567`; `fetchContainerInfo` `~596` |
| `ari-core/ari/viz/api_settings.py` | **553** | serve/persist | `_api_get_env_keys` `40-73`; `_upsert_env_key` `77-104`; `_api_save_env_key` `107-115`; `_api_get_settings` (defaults) `119-196` (defaults dict `137-180`); `_api_save_settings` `202-231`; `_api_skills` `466-498`; `_api_profiles` `505-511`; `_api_rubrics` `523-551` |
| `ari-core/ari/viz/routes.py` | 1197 | route dispatch | GET `/api/env-keys` `746`, `/api/rubrics` `752`, `/api/settings` `853`, `/api/profiles` `867`, `/api/skills` `882`, `/api/container/info` `886`, `/api/scheduler/detect` `896`, `/api/slurm/partitions` `898`; POST `/api/settings` `1035`, `/api/memory/restart` `1043`, `/api/env-keys` `1060`, `/api/ssh/test` `1062` |
| `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts` | 444 / 441 / 441 | labels | settings keys `en.ts:134-160,186-191,279,320-328` (see §6). **en 444 vs ja/zh 441 = 3-line key drift (verified)** |
| `ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` | 1160 | cross-reference only | `phaseModels` iface `103`, prop `176`, input `784`, update `410`; `autoReadApiKey` def `333-342`, mount fire `299`, button `674`, `api.fetchEnvKeys` `340` |

**Absence recorded (do not invent):** there is **no** `SETTINGS.md`, no settings-schema file, and no `sonfigs/` anywhere in the tree. The settings store is the per-checkpoint `settings.json` (`_st._settings_path`) plus `.env` (`_st._env_write_path`). This is unrelated to the `ari/config/` (code) / `ari/configs/` (packaged defaults) / top-level `ari-core/config/` (rubric data) trio.

---

## 1. Section (Card) Map

`SettingsPage.tsx` renders **10 `<Card>`s** top-to-bottom (`369-1035`), no tabs/search/grouping, then a **2-button action bar** (`1038-1045`). The 059 ground-truth phrase "9 `<Card>` sections" **undercounts**: the read-only Skills table (Card 8) and the destructive Project-Management card (Card 10) are both real `<Card>`s. **Recorded count: 10 cards.**

| # | `<Card>` title | Source lines | Label source | Audience bucket |
|---|---|---|---|---|
| 1 | Language | `369-380` | i18n `settings_lang_section` / `settings_lang` | cosmetic |
| 2 | LLM Backend | `383-478` | i18n `settings_llm` (fields mixed i18n + hardcoded) | primary / secret |
| 3 | Paper Retrieval | `481-509` | i18n `settings_paper` (fields hardcoded) | secondary / secret |
| 4 | VLM Figure Review | `512-523` | **hardcoded** `"VLM Figure Review"` | secondary |
| 5 | Memory (Letta) | `526-695` | i18n `settings_memory` (+ subkeys) | advanced / secret / destructive |
| 6 | SLURM / HPC | `698-770` | i18n `settings_slurm` | advanced |
| 7 | Container | `773-827` | **hardcoded** `"Container"` | advanced |
| 8 | Available Skills (read-only table) | `830-877` | i18n `settings_skills` | diagnostic (read-only) |
| 9 | SSH Remote Host | `880-943` | i18n `settings_ssh` (fields mostly hardcoded) | advanced |
| 10 | Project Management (delete actions) | `946-1035` | **hardcoded** `"Project Management"` | destructive |
| — | Action bar (Save / Test LLM) | `1038-1045` | i18n `btn_save` / `btn_test_llm` | primary / probe |

**Wire summary (verified):** `loadSettings` (`118-160`) reads **27 distinct `r.<key>` fields** off `GET /api/settings`; `handleSave` (`235-260`) POSTs a flat **24-key** object to `POST /api/settings`. Read set ≠ write set (see §4/§5). Language persists via i18n + `localStorage ari_lang` only, **not** in the 24-key POST.

---

## 2. Inventory Schema

One row per visible control. Fields (populated for every row; `n/a` / `absent` / `not persisted` used explicitly, no blanks):

`section` · `control_id` (stable `section.field` slug — 073 keys its diff off these) · `source_line` · `control_type` · `state_var` · `read_key` · `write_key` · `backend_field` · `label_source` · `default` · `sensitivity` · `recommendation` · `routes_to`.

Sensitivity taxonomy: **cosmetic** (Language), **operational** (infra/tuning/probes), **secret** (password inputs → `.env` or `settings.json`), **destructive** (irreversible / daemon-restart).

---

## 3. Control Inventory (one row per visible control — 35 rows)

### Card 1 — Language (`369-380`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `lang.language` | `371-379` | select | `lang` | `localStorage 'ari_lang'` \|\| `r.language` (`121`) | **not persisted** (i18n `setLanguage`, not in 24-key POST) | `absent` (no `language` default in dict; `Settings.language` `:58` filled only from saved passthrough) | i18n `settings_lang` (`370`) | `'ja'` (`121`) | cosmetic | KEEP | 068 |

### Card 2 — LLM Backend (`383-478`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `llm.provider` | `388-398` | select | `provider` | `r.llm_backend` \|\| `r.llm_provider` (`124`) | `llm_backend` (`237`) | `llm_provider` (`139`) — `llm_backend` **absent from defaults**, persisted via passthrough | i18n `s_provider` (`387`) | `openai` (`DEFAULT_PROVIDER`, const `7`) | operational | ADAPT (KEEP semantics; non-symmetric key, §5) | 068 |
| `llm.model_select` | `404-415` | select | `modelSelect` | `r.llm_model` (`127`) | `llm_model` (via `model` `227-228`→`236`) | `llm_model` (`138`) | i18n `s_model` (`403`) | `''`; options `PROVIDER_MODELS[provider]` **hardcoded/stale** (`const 9-15`, e.g. `gpt-5.2`, `claude-opus-4-5`) + `__custom__` | operational | REVIEW_REQUIRED (stale hardcoded list) | 070 |
| `llm.model_custom` | `421-427` | text | `modelCustom` | `r.llm_model` (`126`) | `llm_model` (via `model` `227-228`→`236`) | `llm_model` (`138`) | i18n `settings_default_model` (`420`) | `''` | operational | ADAPT | 070 |
| `llm.temperature` | `433-441` | number | `temperature` | `r.temperature` (`128`) | `temperature` (`239`) | `temperature` (`142`) | i18n `s_temperature` (`432`) | `1.0` (`48`/`128`; backend `142` = `1.0`) | operational | KEEP | 068 |
| `llm.api_key` | `448-454` (cond. `provider!=='ollama'` `445`) | password | `apiKey` | `r.llm_api_key` (`129`) | `llm_api_key` (`240`) — **stripped to `.env`**, never in `settings.json` (`205-219`) | `llm_api_key` (`140`, always `""`) | **hardcoded** `"API Key"` (`447`) | `''` | secret | REVIEW_REQUIRED (mask / dev-mode gate) | 071 |
| `llm.base_url` | `464-474` (cond. `ollama`\|`cli-shim` `459`) | text | `baseUrl` | `r.llm_base_url` (cli-shim) \|\| `r.ollama_host` (else) (`130`) | `llm_base_url` (`238`) | `ollama_host` (`141`) — `llm_base_url` **absent from defaults** | **hardcoded** `"Base URL (CLI Shim)/(Ollama)"` (`462`) | `''` | operational | ADAPT (non-symmetric key, §5) | 068/069 |

### Card 3 — Paper Retrieval (`481-509`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `paper.retrieval_backend` | `490-496` (radio ×3) | radio | `retrievalBackend` | `r.retrieval_backend` (`132`) | `retrieval_backend` (`242`) | `retrieval_backend` (`144`) | **hardcoded** `"Paper Retrieval Backend"` (`482`) + option labels (`485-487`) | `semantic_scholar` (`54`/`132`/`144`) | operational | ADAPT | 068 |
| `paper.semantic_scholar_key` | `502-508` | password | `ssKey` | `r.semantic_scholar_key` (`131`) | `semantic_scholar_key` (`241`) — **persisted to `settings.json` in plaintext** (not stripped to `.env`) | `semantic_scholar_key` (`143`, `""`) | **hardcoded** `"Semantic Scholar API Key"` (`501`) | `''` | secret | REVIEW_REQUIRED (plaintext in `settings.json`) | 071 |

### Card 4 — VLM Figure Review (`512-523`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `vlm.review_model` | `514-522` | select | `vlmReviewModel` | `r.vlm_review_model` (`145`) | `vlm_review_model` (`256`) | `vlm_review_model` (`155`) | **hardcoded** `"VLM Model"` (`513`); card title hardcoded (`512`) | `openai/gpt-4o` (`79`/`145`; backend `155` = `openai/gpt-4o`) | operational | REVIEW_REQUIRED (options reuse `PROVIDER_MODELS[provider]` `519` → shows **chat** models, not VLM list) | 070 |

### Card 5 — Memory (Letta) (`526-695`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `memory.base_url` | `530-536` | text | `lettaBaseUrl` | `r.letta_base_url` (`150`) | `letta_base_url` (`.trim()`, `257`) | `letta_base_url` (`162`) | i18n `settings_memory_base_url` (`529`) | `http://localhost:8283` (`82`/`150`/`162`) | operational | ADAPT | 068/069 |
| `memory.api_key` | `540-546` | password | `lettaApiKey` | `r.letta_api_key` (`151`) | `letta_api_key` (`258`) — **plaintext to `settings.json`** (not stripped to `.env`) | `letta_api_key` (`163`, `""`) | i18n `settings_memory_api_key` (`539`) | `''` | secret | REVIEW_REQUIRED (plaintext in `settings.json`) | 071 |
| `memory.embedding_provider` | `554-570` | select | `lettaEmbedProvider` | derived `_splitHandle(r.letta_embedding_config)` (`152-154`) | part of `letta_embedding_config` (`230-233`→`259`) | `letta_embedding_config` (`164`) | i18n `settings_memory_embedding_provider` (`552`) | `openai` (`87`); options `LETTA_EMBED_PROVIDERS` (const `67`) + `__custom__` | operational | ADAPT | 068/069 |
| `memory.embedding_model` | `576-596` | select \| text | `lettaEmbedModel` / `lettaEmbedCustom` | derived `_splitHandle(...)` (`152-156`) | `letta_embedding_config` (`230-233`→`259`) | `letta_embedding_config` (`164`) | i18n `settings_memory_embedding_model` (`574`) | FE `openai/text-embedding-3-small` (`88-90`/`152`) **≠** backend `letta-default` (`164-166`) — **MISMATCH recorded**; options `LETTA_EMBEDDING_BY_PROVIDER` **hardcoded** (const `42-60`) | operational | REVIEW_REQUIRED (FE/backend default mismatch; stale hardcoded table) | 070 |
| `memory.deployment` | `634-648` | select | `lettaDeployment` | `n/a` (never read from settings; state default `97-99`) | **not persisted** (not in 24-key POST; sent only to `restartLetta` `657`) | `letta_deployment` (`159`) — present in defaults but page never reads/writes it | i18n `settings_memory_deployment` (`632`) | `auto` (`99`/`159`) | operational | REVIEW_REQUIRED (declared-but-unpersisted quirk) | 070 |
| `memory.restart_letta` | `649-674` (button) | button/action | `lettaRestarting` / `lettaRestartMsg` | `n/a` | `restartLetta(lettaDeployment)` → `POST /api/memory/restart` (`657`, route `1043`) | `n/a` (lifecycle, not persisted) | i18n `settings_memory_restart` (`673`) | `n/a` | destructive | REVIEW_REQUIRED (guard = single `confirm` `653`; stops+starts daemon) | 071 |

### Card 6 — SLURM / HPC (`698-770`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `slurm.detect` | `704-710` (button) | button/action | `partitions` | `n/a` | **not persisted** (`fetchPartitions` → `GET /api/slurm/partitions`, route `898`) | `n/a` (read-only probe) | **hardcoded** `"Detect"` (`709`) | `n/a` | operational | KEEP (read-only probe) | 069 |
| `slurm.partitions` | `713-727` (shown when detected) | multiselect | `selectedPartitions` | `r.slurm_partitions` \|\| `[r.slurm_partition]` (`138`) | `slurm_partitions` (`248`) **and** `slurm_partition = selectedPartitions[0]` (`249`) | `slurm_partition` (`145`) — `slurm_partitions` **absent from defaults** | i18n `s_partition` (`703`) | `[]` (`58`/`138`) | operational | ADAPT (writes two keys, §5) | 069 |
| `slurm.cpus` | `740-745` | number | `cpus` | `r.slurm_cpus` (`139`) | `slurm_cpus` (`250`) | `slurm_cpus` (`146`, `None`) | i18n `s_cpus` (`739`) | `8` (`59`/`139`; backend `None`) | operational | ADAPT | 069 |
| `slurm.memory_gb` | `751-756` | number | `memGb` | `r.slurm_memory_gb` (`140`) | `slurm_memory_gb` (`251`) | `slurm_memory_gb` (`147`, `None`) | **hardcoded** `"Memory (GB)"` (`750`) | `32` (`60`/`140`; backend `None`) | operational | ADAPT | 069 |
| `slurm.walltime` | `762-767` | text | `walltime` | `r.slurm_walltime` (`141`) | `slurm_walltime` (`252`) | `slurm_walltime` (`149`) | i18n `s_walltime` (`761`) | `04:00:00` (`61`/`141`/`149`) | operational | KEEP | 069 |

### Card 7 — Container (`773-827`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `container.mode` | `777-787` | select | `containerMode` | `r.container_mode` (`142`) | `container_mode` (`253`) | `container_mode` (`151`) | **hardcoded** `"Mode"` (`776`) | `auto` (`72`/`142`/`151`) | operational | ADAPT | 069 |
| `container.pull` | `791-799` | select | `containerPull` | `r.container_pull` (`144`) | `container_pull` (`255`) | `container_pull` (`153`) | **hardcoded** `"Pull Policy"` (`790`) | `on_start` (`74`/`144`/`153`) | operational | ADAPT | 069 |
| `container.image` | `803-809` | text | `containerImage` | `r.container_image` (`143`) | `container_image` (`254`) | `container_image` (`152`) | **hardcoded** `"Image"` (`802`) | `''` (`73`/`143`/`152`) | operational | ADAPT | 069 |
| `container.detect_runtime` | `812-814` (button) | button/action | `containerRuntime` / `containerVersion` | `n/a` | **not persisted** (`fetchContainerInfo` → `GET /api/container/info`, route `886`) | `n/a` (read-only probe) | **hardcoded** `"Detect Runtime"` (`813`) | `n/a` | operational | KEEP (read-only probe) | 069 |

### Card 8 — Available Skills (`830-877`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `skills.table` | `831-873` | read-only table | `skills` | `fetchSkills` → `GET /api/skills` (route `882`; `_api_skills` `466-498`) | **not persisted** (read-only) | `n/a` (served by `_api_skills`; column headers `skill_label`/`skill_display_name` i18n, `"Description"`/`"Env"` hardcoded `842`/`845`) | i18n `settings_skills` (`830`) | `[]` (`105`) | operational (diagnostic) | KEEP | 069 |

### Card 9 — SSH Remote Host (`880-943`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ssh.host` | `884-889` | text | `sshHost` | `r.ssh_host` (`133`) | `ssh_host` (`243`) | **absent** (no `ssh_*` in defaults dict; persisted via passthrough) | **hardcoded** `"Host"` (`883`) | `''` (`64`/`133`) | operational | ADAPT | 069 |
| `ssh.port` | `893-898` | number | `sshPort` | `r.ssh_port` (`134`) | `ssh_port` (`244`) | **absent** | **hardcoded** `"Port"` (`892`) | `22` (`65`/`134`) | operational | ADAPT | 069 |
| `ssh.user` | `902-907` | text | `sshUser` | `r.ssh_user` (`135`) | `ssh_user` (`245`) | **absent** | i18n `ssh_username` (`901`) | `''` (`66`/`135`) | operational | ADAPT | 069 |
| `ssh.path` | `911-916` | text | `sshPath` | `r.ssh_path` (`136`) | `ssh_path` (`246`) | **absent** | **hardcoded** `"Remote ARI Path"` (`910`) | `''` (`67`/`136`) | operational | ADAPT | 069 |
| `ssh.key` | `920-925` | text | `sshKeyPath` | `r.ssh_key` (`137`) | `ssh_key` (`247`) — **state var `sshKeyPath` ≠ wire key `ssh_key`** | **absent** | **hardcoded** `"SSH Key Path"` (`919`) | `''` (`68`/`137`) | operational | ADAPT | 069 |
| `ssh.test` | `928-930` (button) | button/action | `sshStatus` | `n/a` | **not persisted** (`testSSH` → `POST /api/ssh/test`, route `1062`) | `n/a` (read-only probe) | **hardcoded** `"Test SSH"` (`929`) | `n/a` | operational | KEEP (read-only probe) | 069 |

### Card 10 — Project Management (`946-1035`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `project.delete` | `1016-1027` (button, per row) | delete action | `checkpoints` | `fetchCheckpoints` → `GET /api/checkpoints` (list only) | **not persisted** (`deleteCheckpoint(id,path)` → `POST /api/delete-checkpoint`, wrapper `353`) | `n/a` (checkpoint lifecycle, `checkpoint_lifecycle.py`) | **hardcoded** `"Project Management"` (`946`) / `"Delete"` (`1026`) | `n/a` | destructive | REVIEW_REQUIRED (guard = single `confirm` `299`; irreversible) | 071 |

### Action bar (`1038-1045`)

| control_id | line | type | state_var | read_key | write_key | backend_field | label_source | default | sensitivity | rec | routes_to |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `actions.save` | `1039-1041` (button) | button/action | `statusMsg` | `n/a` | drives `handleSave` → `POST /api/settings` (24-key, route `1035`) | `n/a` | i18n `btn_save` (`1040`) | `n/a` | operational (primary) | KEEP | 070 |
| `actions.test_llm` | `1042-1044` (button) | button/action | `statusMsg` | `n/a` | **not persisted** (`generateConfig('ping')` → `POST /api/config/generate`) | `n/a` (read-only probe) | i18n `btn_test_llm` (`1043`) | `n/a` | operational (probe) | KEEP | 068 |

**Row count = 35 controls** across 10 cards + action bar. Sensitivity tally: cosmetic 1 · operational 26 · secret 3 (`llm.api_key`, `paper.semantic_scholar_key`, `memory.api_key`) · destructive 2 (`memory.restart_letta`, `project.delete`) · read-only probes/tables 5 (detect ×2, test ssh, test llm, skills table) — probes/tables counted within operational.

---

## 4. Appendix A — Read / Write / Backend Asymmetry

### 4.1 The 24 keys written by `handleSave` (`235-260`)
`llm_model, llm_backend, llm_base_url, temperature, llm_api_key, semantic_scholar_key, retrieval_backend, ssh_host, ssh_port, ssh_user, ssh_path, ssh_key, slurm_partitions, slurm_partition, slurm_cpus, slurm_memory_gb, slurm_walltime, container_mode, container_image, container_pull, vlm_review_model, letta_base_url, letta_api_key, letta_embedding_config` — **exactly 24**. (`llm_api_key` is stripped to `.env` by the backend before `settings.json` write, so **23** land in `settings.json`.)

### 4.2 `Settings` type fields with NO UI control on this page (`types/index.ts:38-75`)
- **Per-phase models** (`59-64`): `model_idea, model_bfts, model_coding, model_eval, model_paper, model_review` — edited in `Wizard/StepResources.tsx` (`phaseModels`, §7), not global Settings.
- **VLM extras** (`68`,`70`,`71`): `vlm_review_enabled, vlm_review_max_iter, vlm_review_threshold` — only `vlm_review_model` has a control.
- `llm_provider` (`40`): read as fallback (`124`) but no control writes it (control writes `llm_backend`).
- `ollama_host` (`43`): read *into* `baseUrl` for non-cli-shim providers (`130`) but never written as `ollama_host` (written as `llm_base_url`).
- `language` (`58`): the Language select maps to i18n/`localStorage`, not `/api/settings`.

> **Count discrepancy recorded:** subtask 067 §2/§5 and the 059 report say the `Settings` type has **35** fields. Recount of `types/index.ts:39-74` yields **36** field declarations (the optional `llm_base_url?` on `:44` is the extra). Downstream 068/070 should treat **36** as ground truth.

### 4.3 Backend defaults (`api_settings.py:137-180`) with NO UI control
- `slurm_gpus` (`148`), `mcp_skills` (`150`).
- `vlm_review_enabled` (`154`), `vlm_review_max_iter` (`156`), `vlm_review_threshold` (`157`).
- `letta_deployment` (`159` — a select exists but is **not persisted via settings**, §3 Card 5), `letta_deployment_image` (`160`), `letta_deployment_venv` (`161`).
- Entire nested **`ors`** block (`168-179`): `replicator_model, rubric_gen_model, rubric_audit_model, judge_model, rubric_gen_temperature, rubric_gen_target_leaves, rubric_gen_two_stage, judge_n_runs, phase1_max_runtime_sec, phase1_sandbox_kind` — surfaced through the PaperBench wizard (§7), not Settings.

### 4.4 FE-written keys with NO backend default (persist only via `{**defaults, **saved}` passthrough, `188`)
`llm_backend`, `llm_base_url`, `slurm_partitions`, `ssh_host`, `ssh_port`, `ssh_user`, `ssh_path`, `ssh_key`. These have no key in the defaults dict; they survive only because `_api_get_settings` merges saved JSON over defaults. Dropping the passthrough would silently lose them → **REVIEW_REQUIRED for 070**.

### 4.5 Non-symmetric key mappings (record verbatim; §5 targets 068/070)
1. **provider:** read `r.llm_backend || r.llm_provider` (`124`) → write `llm_backend` (`237`); backend default key is `llm_provider` (`139`).
2. **baseUrl:** read `(provider==='cli-shim') ? r.llm_base_url : r.ollama_host` (`130`) → write `llm_base_url` (`238`); backend default key is `ollama_host` (`141`). The field is only *rendered* for `ollama`/`cli-shim` (`459`).
3. **slurm partitions:** read `r.slurm_partitions || [r.slurm_partition]` (`138`) → write **both** `slurm_partitions` (`248`) and `slurm_partition = selectedPartitions[0] || ''` (`249`); backend default key is `slurm_partition` (`145`) only.
4. **ssh key path:** state var `sshKeyPath` → wire key `ssh_key` (`137`/`247`) (name mismatch).
5. **letta deployment:** state `lettaDeployment` is **never** in the Save payload; sent only to `restartLetta(lettaDeployment)` (`657`).

---

## 5. Appendix B — Secret-Exposure Surface (record only; do not change)

- **Three password inputs on this page:** `llm.api_key` (`448-454`), `paper.semantic_scholar_key` (`502-508`), `memory.api_key` (`540-546`).
- **`.env` write path (LLM key only):** `_api_save_settings` (`202-231`) pops `api_key`/`llm_api_key` (`205-207`) and, if it looks real (`len ≥ 20` and no `"test"`, `209`), writes it to `.env` via `_upsert_env_key(..., quote=False)` (`219`, unquoted `KEY=value`). Provider→env-name map (`211-215`): `openai→OPENAI_API_KEY`, `anthropic→ANTHROPIC_API_KEY`, `gemini→GOOGLE_API_KEY`.
- **Plaintext-to-`settings.json` (finding):** `semantic_scholar_key` and `letta_api_key` are **not** stripped — they persist to the project `settings.json` in cleartext (`230`). Only the LLM `api_key`/`llm_api_key` is diverted to `.env`.
- **Secret readback (`/api/env-keys`):** `_api_get_env_keys` (`40-73`) returns **actual secret values** (`keys` dict) to the browser; FE wrapper `fetchEnvKeys` (`api.ts:382`). **SettingsPage itself does not call it** — the readback consumer is `Wizard/StepResources.tsx::autoReadApiKey` (`333-342`, auto-fires on mount `299`, button `674`). Recorded here as the settings-adjacent exposure (§7).
- **No auth / token** on any of these dashboard endpoints; `.env` quoting split (`quote=True` for the env-key editor `114`, `quote=False` for the settings API-key path `219`) is a documented behavior contract (`_upsert_env_key` docstring `77-104`).

→ **REVIEW_REQUIRED for 069/071** (developer-mode / masking gate). Contract to preserve: request/response shapes, the `.env` quoting split, and `settings.json` format.

---

## 6. Appendix C — i18n Coverage

**Settings i18n keys present (en.ts):** `settings_title`(`134`), `settings_llm`(`135`), `settings_paper`(`136`), `settings_slurm`(`137`), `settings_ssh`(`138`), `settings_skills`(`139`), `settings_memory`(`140`), `settings_memory_base_url`(`141`), `settings_memory_api_key`(`142`), `settings_memory_embedding_provider`(`143`), `settings_memory_embedding_model`(`144`), `settings_memory_letta_free_warning`(`145`), `settings_memory_note`(`147`), `settings_memory_key_note`(`149`), `settings_memory_restart`(`151`), `settings_memory_restart_running`(`152`), `settings_memory_restart_ok`(`153`), `settings_memory_restart_confirm`(`154`), `settings_memory_deployment`(`156`), `settings_memory_deployment_auto`(`157`), `settings_memory_deployment_pip`(`158`), `btn_save`(`159`), `btn_test_llm`(`160`), `model_custom_placeholder`(`186`), `settings_default_model`(`187`), `settings_lang_section`(`190`), `custom_entry`(`191`), `settings_lang`(`279`), `skill_display_name`(`320`), `skill_label`(`321`), `ssh_username`(`322`), `s_temperature`(`323`), `s_provider`(`324`), `s_model`(`325`), `s_partition`(`326`), `s_cpus`(`327`), `s_walltime`(`328`).

**Hardcoded English (no `t()`), with lines:**
- Card titles: `"VLM Figure Review"` (`512`), `"Container"` (`773`), `"Project Management"` (`946`).
- Field labels: `"API Key"` (`447`), `"Base URL (CLI Shim)/(Ollama)"` (`462`), `"Paper Retrieval Backend"` (`482`), retrieval radio labels `"Semantic Scholar"/"AlphaXiv"/"Both (parallel)"` (`485-487`), `"Semantic Scholar API Key"` (`501`), `"VLM Model"` (`513`), `"Memory (GB)"` (`750`), `"Mode"` (`776`), `"Pull Policy"` (`790`), `"Image"` (`802`), `"Detect Runtime"` (`813`), `"Detect"` (`709`), skills headers `"Description"`/`"Env"` (`842`/`845`), `"Host"` (`883`), `"Port"` (`892`), `"Remote ARI Path"` (`910`), `"SSH Key Path"` (`919`), `"Test SSH"` (`929`), `"Delete"` (`1026`).

**Key drift (verified):** `en.ts` **444** vs `ja.ts`/`zh.ts` **441** = 3-line divergence. The settings-memory key group is at parity (15 `settings_memory*` matches in each of en/ja/zh), so the drift originates outside the settings block. `scripts/docs/check_i18n_js.py` covers only the landing JS, **not** these React `i18n/*.ts` files, so the drift is currently **unchecked**. → **REVIEW_REQUIRED for 073.** Any 070 relabeling must mirror en→ja/zh (i18n key contract, §8).

---

## 7. Appendix D — Settings Elsewhere (inventory metadata; not in-page controls)

- **Per-phase models** — `Wizard/StepResources.tsx`: `phaseModels` interface (`103`), prop (`176`), per-phase `<select value={phaseModels[phase]}>` (`784`), update writer (`410`). These map to `Settings.model_idea…model_review` (`types/index.ts:59-64`). **068 must decide** whether to surface them in global Settings (Advanced tab) or keep per-run in the wizard — do **not** silently drop.
- **`autoReadApiKey`** — `Wizard/StepResources.tsx:333-342`: calls `api.fetchEnvKeys()` (`340`) → `GET /api/env-keys`, auto-fires on mount (`299`) and via button (`674`); pre-fills key fields from live env secrets. This is the concrete consumer of the §5 readback exposure.
- **ORS model block** — `api_settings.py:168-179` (`_api_get_settings.ors`): PaperBench-format auto-rubric model config (`replicator_model` default `claude-opus-4-7`, `rubric_gen_model` `gemini-2.5-pro`, `rubric_audit_model` `claude-opus-4-7`, `judge_model` `gpt-4o-2024-11-20`, + params). Surfaced through the PaperBench wizard, never rendered by `SettingsPage`.

---

## 8. Contracts to Preserve (for downstream 068–072)

067 is read-only; this is the preserve-unchanged list the implementers must honor (compatibility-adapter note required if any is touched):

- **Dashboard API:** `GET/POST /api/settings` (`routes.py:853,1035`; `api_settings.py:119-231`), `GET/POST /api/env-keys` (`746,1060`), `GET /api/skills` (`882`), `GET /api/profiles` (`867`), `GET /api/rubrics` (`752`), `POST /api/memory/restart` (`1043`), `POST /api/ssh/test` (`1062`), `GET /api/container/info` (`886`), `GET /api/slurm/partitions` (`898`), `GET /api/scheduler/detect` (`896`) — request/response shapes stable.
- **`settings.json` format** — project-scoped JSON written by `_api_save_settings` to `_st._settings_path` (`229-230`), served merged over defaults (`188`).
- **`.env` write behavior** — `_upsert_env_key` quoting split (`quote=True` env-key editor `114`; `quote=False` settings API-key path `219`).
- **FE contract** — `services/api.ts` wrappers + the `Settings` type (`types/index.ts:38-75`), which is imported outside SettingsPage (shared contract; dropping a field is breaking → deprecation/adapter note required, not here).
- **i18n key contract** — existing settings keys in `en.ts`; any rename mirrored to `ja/zh` (gated by `check_i18n_js.py` for landing JS; React `i18n/*.ts` currently unchecked, §6).
- **CLI `ari`, `ari.public.*`, MCP `ari-skill-*`, checkpoint format** — untouched by the settings surface; listed for completeness.

Every editable control → **KEEP** setting semantics; **ADAPT** placement/label/gating under 068–071. The 3 secret inputs + 2 destructive actions + stale hardcoded model tables + FE/backend default mismatch + declared-but-unpersisted `letta_deployment` + `model_*`/`vlm_review_*` type-only fields → **REVIEW_REQUIRED** for the named downstream subtask. **Nothing is proposed for DELETE.**

---

## 9. Retirement Condition

This report is a **temporary planning artifact** of subtask 067. It may be archived/`git rm`-ed only after: (1) subtask 067 §13 Acceptance Criteria are met; (2) the implementing PR is merged to `main`; (3) `docs/refactoring/007_subtask_index.md` marks 067 **DONE**. Until then: **KEEP**. Verify each condition against primary sources before removal (canonical policy: `007_subtask_index.md` "Document Retirement Policy").
