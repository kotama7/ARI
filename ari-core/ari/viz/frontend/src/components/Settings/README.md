# frontend/src/components/Settings

Settings page — dashboard/run configuration view.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `settingsConstants.ts` — provider/Letta model tables + _splitHandle helper (extracted from SettingsPage in req 15).
- `SettingsGroup.tsx` — progressive-disclosure wrapper grouping cards under a sensitivity tier; collapsing toggles CSS `display` only and never unmounts children, so all ten `.card-title`s stay in the DOM.
- `SettingsPage.tsx` — settings view.
- `settingsStyles.ts` — shared `inputStyle` / `labelStyle` field styles moved verbatim out of SettingsPage so every `sections/*` component consumes one definition.
- `settingsTypes.ts` — shared prop/data types for the decomposed sections: the threaded `TFn` translator, the `SkillInfo` row, and the `LettaDeployment` union.
- `__tests__/` — the frozen Settings contract tests (ten cards, 24-key save payload) plus the progressive-disclosure safety test.
  - `SettingsContract.test.tsx` — Tier-1 frozen contract: all ten section `<Card>` titles render, and Save POSTs exactly the 24-key flat object to `/api/settings`.
  - `SettingsDisclosure.test.tsx` — pins the 069 tiers: four `settings-group-header`s render and collapsing one keeps all ten cards mounted (CSS-only, no unmount).
- `sections/` — the ten presentational `<Card>` sections SettingsPage composes into its four sensitivity tiers; each takes state + setters as props.
  - `ContainerSection.tsx` — container card — mode (auto/docker/singularity/apptainer/none), pull policy, image, and the Detect Runtime probe badge.
  - `LanguageSection.tsx` — UI language card — en/ja/zh select wired to the orchestrator's `onLangChange`.
  - `LlmBackendSection.tsx` — LLM backend card — provider select (openai/anthropic/gemini/ollama/cli-shim), model dropdown plus custom entry, temperature, API key, and the ollama/cli-shim base URL.
  - `MemorySection.tsx` — Letta memory card — base URL, API key, embedding provider/handle picker, and the deployment-path Restart button calling `restartLetta` behind a confirm with status feedback.
  - `PaperRetrievalSection.tsx` — paper retrieval card — backend radio (Semantic Scholar / AlphaXiv / both) and the optional Semantic Scholar API key.
  - `ProjectManagementSection.tsx` — checkpoint roster card with running/active badges and the per-project Delete button that drives the challenge-gated `deleteCheckpoint` flow.
  - `SkillsSection.tsx` — read-only table of the `GET /api/skills` rows — name, display name, description, and required env (or an `any` badge).
  - `SlurmSection.tsx` — SLURM/HPC defaults card — partition multi-select with a Detect probe, CPUs, memory (GB), and walltime.
  - `SshSection.tsx` — remote-host card — host/port/user/remote ARI path/key path plus the Test SSH probe and its ✓/✗ status badge.
  - `VlmReviewSection.tsx` — VLM figure-review card — model picker drawn from `PROVIDER_MODELS` for the currently selected provider.
