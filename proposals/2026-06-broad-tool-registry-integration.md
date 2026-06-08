# RFC: Broad external tool/skill-registry integration for ARI

| | |
|---|---|
| **Status** | **Proposed — both build blockers resolved in design (§4a, zero ari-core change); implementation gated only on the real-env spike (§7.1)** |
| **Date** | 2026-06-08 (rev. 2026-06-09 — §4a blocker resolutions added) |
| **Scope** | Design only. No runtime/code change. Implementation is gated on the spike in §7. |
| **Supersedes / relates to** | `docs/concepts/PHILOSOPHY.md` (P1–P5), the VirSci-live vendor-wrap precedent (`ARI_IDEA_VIRSCI_REAL`), `ari-skill-web` (live-API wrapping), `ari-skill-orchestrator` (ARI-as-MCP-server) |

> **概要 (Japanese TL;DR)** — ARI を生命科学特化の ToolUniverse 一本より広く、かつ再現性ファーストのまま拡張するための統合設計。適合形は **単一の in-tree stdio ブローカースキル `ari-skill-tool-registry`**（Compact 5 ツール・digest 固定・人手キュレーション catalog・カセット再現層を EAR へ・段階導入 A→B→C・transport は stdio 一本）。当初の敵対的レビューが見つけた 2 つの BLOCKER（実在しない `ARI_PHASE` 依存／reproduce サンドボックスがカセットを見られない）は、**結合した単一の受け渡しミス**であり、**両方とも ari-core 変更ゼロで解決済み**（§4a）— reproduce はスキルを経由せず、vendor 済みカセットを `reproduce.sh` が読む形にすれば phase 信号は不要になる。残るゲートは**実機 spike のみ**（§7.1）。本 RFC は設計・根拠・解決・spike ゲートを記録するもの。

---

## 1. Motivation

ARI's core is domain-agnostic by design (P1) and its vision is "universal research automation … Computation to physical world," yet its *only* demonstrated domain is HPC/computational benchmarking (CSR-SpMM on A64FX). To make the domain-agnostic claim operational rather than aspirational, ARI needs access to a broad cross-domain tool surface — without surrendering the reproducibility-first invariant (P5: "the checkpoint, not the run, is the contract").

This RFC evaluates external tool/skill repositories and proposes a concrete, ARI-shaped way to consume them.

## 2. Landscape (what was surveyed)

`https://aiscientist.tools/` is **ToolUniverse** (Harvard / Zitnik Lab; arXiv:2509.23426; Apache-2.0): a **biomedical/life-science-only** registry (~595 confirmed tools — 281 API, 164 packages, 84 DB, 17 ML, 38 agents; **zero** HPC/materials/physics), MCP-native (SMCP server), self-extending (Tool Finder / Tool Discover / Composer / Optimizer / MCP Auto Loader), with per-tool caching. It is a strong *biomedical* pillar but does not broaden ARI beyond biomedicine.

Broader candidates, mapped on **breadth vs. curation/reproducibility** (the central trade-off — the broadest sources are the least curated, least reproducible, most side-effecting, and most likely to ship a competing orchestrator):

| Source | Breadth vs ToolUniverse | MCP | Reproducibility | Competes w/ ARI harness | Verdict |
|---|---|---|---|---|---|
| **Official MCP Registry** (`registry.modelcontextprotocol.io`, ~9.6k servers) | much broader | native | mixed (pins **code**, not **data**) | no — pure tool layer | **breadth source** |
| Glama / mcp.so / PulseMCP (17k–32k) | much broader | native | poor | partial (gateways) | discovery mirrors only |
| Docker MCP Catalog (~200–300) | broader | native | **good** (signed/SBOM/digest) | partial (Gateway) | pull signed images, skip gateway |
| Smithery / Composio / Zapier MCP | much broader | native | poor | **yes — harness** | discovery feed only, don't route |
| APIs.guru (CC0 OpenAPI, ~2.5k APIs) | much broader | needs wrapper | mixed | no | auto-wrap substrate |
| HuggingFace (pinned-revision models) | much broader | available | **good** (`revision=<sha>`+`HF_HUB_OFFLINE`) | partial | the one byte-reproducible slice |
| **mcp.science** (13 servers) | broader (materials/DFT/physics/math) | native | mixed | no | **domain-fit source** |
| **Globus/Argonne MCP-for-Science** (arXiv:2508.18489) | broader (HPC/materials/quantum-chem) | native | good (but they report run-to-run inconsistency **unsolved**) | no | **design blueprint** |
| SciToolAgent / ChemCrow / LangChain / CrewAI | varies | mostly not | poor | **yes — harness** | harvest tool sets, never adopt the loop |

**Conclusion:** No single 2026 repository is simultaneously *broad-cross-domain-incl-HPC* **and** *~1000-scale* **and** *native-MCP-passive-with-caching*. The decision is to **compose**: breadth from the official MCP registry, cross-science domain-fit from mcp.science + the Argonne pattern, reproducibility supplied by ARI itself (ToolUniverse-style snapshot/cache/pin), and ToolUniverse kept as the biomedical pillar.

## 3. Precise findings that constrain the design

- **Official MCP Registry**: `GET /v0.1/servers` (cursor pagination, `updated_since`, `version`); each entry's `packages[]` carries `{registryType: npm|pypi|oci|nuget|mcpb|cargo, identifier, exact version, runtimeHint: npx|uvx|dnx, transport: stdio|streamable-http|sse}`. **OCI `@sha256` and `mcpb` `fileSha256` are immutable; bare tags/versions are mutable.** Read = no auth; whitelist = a `_meta`-tagged subregistry.
- **ARI launch path is hardcoded to Python.** `ari-core/ari/mcp/client.py` `_server_params()` returns `StdioServerParameters(command=python, args=[skill/src/server.py], env={**os.environ, "PYTHONPATH": pythonpath})`. **Only stdio; only Python; the child inherits the full `os.environ`.** Registry stdio servers (`uvx`/`npx`/`docker`) therefore need a *second* launch path — which, in Stages A/B of this design, lives **inside the wrapper skill**, below the skill boundary, so ari-core stays unchanged.
- **mcp.science** (`pathintegral-institute/mcp.science`, MIT): **13** server dirs (the README lists 12 and omits `netket`; the README's NEMAD blurb is also wrong — NEMAD = *North East Materials Database*, not "neuroscience"). All `uvx mcp-science <name>` stdio. Split: deterministic-local (`python-code-execution`, `netket`, `mathematica-check`, `tinydb`, `timer`, `gpaw-computation` [DFT, remote-compute via SSH submit/poll]) vs. keyed-live (`materials-project` [MP_API_KEY], `nemad` [NEMAD_API_KEY], `txyz-search`, `web-fetch`, `jupyter-act`).
- **Argonne / Globus "MCP for Science & HPC"** (arXiv:2508.18489): thesis = *thin adapters over mature services* (Globus Compute/Transfer), **run the MCP server locally with a local auth handler** (do not chain tokens across hosts), **submit/poll** for long jobs, discovery via RAG (`find_tools`). They explicitly report agents "produce inconsistent outputs" and propose **no** provenance/repro mechanism — confirming reproducibility is ARI's responsibility.
- **Reproducibility primitives to replicate**: ToolUniverse's two-part per-tool fingerprint cache; HF `from_pretrained(revision=<commit-sha>)` + `HF_HUB_OFFLINE` (byte-reproducible); the VCR/cassette record-replay pattern.

## 4. Proposed fitting form — `ari-skill-tool-registry` (staged-hybrid broker)

**One in-tree stdio broker skill** that proxies pinned external MCP servers as child stdio sessions *below the skill boundary*, exposing a **bounded Compact surface of exactly 5 tools** regardless of how many upstream tools exist:

| Tool | Role |
|---|---|
| `discover(query, top_k)` | keyword/embedding-rank the vendored `catalog.json`; return tool descriptions **as data** (Rhea `find_tools` analogue) |
| `describe(server, tool)` | lazily fetch + cache the upstream JSON-Schema so the LLM sees exact arg shapes without registering N tools |
| `invoke(server, tool, args, mode)` | the **single static dispatch**; `mode=replay` ↔ cassette-only, else live (gated) |
| `get_status(handle)` / `get_result(handle)` | poll long-running jobs by the handle `invoke` returned (gpaw / Globus submit/poll) |

Why 5-and-data, not N registered tools: ARI snapshots the tool list **per phase at connect time** (`react_driver.py:252 mcp.list_tools(phase=agent_phase)`, `_phase_matches` at `client.py`) and has **no mid-session tool-refresh channel**, so Rhea-style dynamic tool registration cannot work — descriptions-as-data + one static `invoke` is the only shape that fits.

**Catalog**: `catalog.json` is a small, **git-committed, human-PR-reviewed whitelist (~8–15 servers)** with **digest-pinned** rows; the live ~9.6k registry is *not* ingested at runtime (that would violate offline-BFTS and the supply-chain gate). Only `stdio` + launchable `registryType` rows are admitted; `streamable-http`/`sse` are rejected.

**Reproducibility layer (`cassette.py`)**: forked from the verified `ari-skill-idea/src/snapshot.py` fail-loud pattern. Two-part key `VERSION:CALL` where `VERSION = sha256(server_id + identifier@version + immutable_digest + upstream_schema)` and `CALL = sha256(canonical_json({tool,args}))`. Secrets (`*_API_KEY`/`SSH_*`/`isSecret`) are scrubbed **before** hashing and freezing. Artifacts land under `<checkpoint>/ear/tool_registry_cassettes/…` as JSON (git-diffable). Live fetch that returns empty/auth-failed **raises** rather than caching a 0-item "success" (the `42bcef5` fail-loud lesson).

**Security**: digest-pin-only (OCI `@sha256`/`mcpb fileSha256`; for `uvx`/`npx` an extra wheel/tarball sha256 — see §6 caveat on transitive deps); runtime allowlist (`ARI_TOOL_REGISTRY_ALLOW`, default `uvx`); curation is the human supply-chain gate; **default-OFF** master flag `ARI_TOOL_REGISTRY_LIVE` so a mis-gate degrades to a pure catalog+replay reader that can never execute third-party code.

**Staging** (the key design move — strengths sequenced, ari-core kept clean as long as possible):

| Stage | Deliverable | ari-core change |
|---|---|---|
| **A** | broker skill + 5 tools + one pinned `uvx` server; proves the launch pattern | **zero** (rides existing glob discovery + python-stdio launch + phase gate + cost_tracker) |
| **B** | cassette repro layer into EAR + curated breadth/domain-fit + keys + long-job submit/poll | **zero** |
| **C** *(deferred, demand-gated)* | command-agnostic `SkillConfig` + `_server_params` branch + command whitelist guard; optional registry ETL + in-process Globus adapter | ~6-line `SkillConfig`/`client.py` diff **plus a command whitelist guard that must land in the same commit** |

The 5-tool surface and cassette format are **stable across the skill→core migration**, so Stage-A and Stage-C checkpoints are byte-identical — the upgrade is non-breaking by construction. **Transport stays stdio-only**; the Argonne HPC axis is reached via a thin in-process Globus-SDK stdio adapter row, never by adding `streamable-http` to ari-core.

## 4a. Blocker resolutions (both resolved in design — zero ari-core change)

Adversarial review (verified against code) confirmed the two §6 blockers are a **single coupled hand-off mismatch**, and both are resolved at the orchestrator/skill level with **no ari-core change**.

**Resolution 1 — drop the phase signal entirely (no `ARI_PHASE`).** The "auto-switch to replay on reproduce" premise was false: a skill subprocess cannot learn the current phase — the driver passes only LLM-chosen args (`react_driver.py:375 mcp.call_tool(tool_name, args)`), the child env is a fork-time `{**os.environ, "PYTHONPATH": …}` snapshot (`client.py:150`), and phase is consumed only at the driver (`react_driver.py:252 mcp.list_tools(phase=agent_phase)`; `_phase_matches` applied in `list_tools` at `client.py:310`, def at `client.py:38`). It is also **not needed**: all four reproduce stages (`ors_seed_sandbox` / `ors_build_reproduce` / `ors_run_reproduce` / `ors_grade`) are `phase: paper` **direct** tool calls with **no `react:` block** (`workflow.yaml`), so the broker never runs during reproduce. Live-vs-replay will instead be governed by three driver/skill-level controls, none touching ari-core: (1) `workflow.yaml` phase scoping — the broker declares `phase: [bfts, paper]` (never `reproduce`); (2) the default-OFF `ARI_TOOL_REGISTRY_LIVE` master flag the broker reads from its inherited `os.environ` at startup; (3) the explicit `invoke(…, mode='replay'|'live')` arg already in the §4 surface (verified additive — no existing skill defines `invoke`). *(The only way to change a running skill's env is a tool the subprocess runs itself — e.g. `_set_current_node` mutating its own `os.environ` via `cow_node_id`, `ari-skill-memory` / `client.py:354`; there is no driver-side phase-injection path, so the conclusion stands.)* **blocker-1 ari-core change: none.**

**Resolution 2 — vendor frozen cassettes into the sandbox via the existing curate→publish→clone chain.** During paper/bfts phase the broker **will** write secret-scrubbed cassettes to `<checkpoint>/ear/tool_registry_cassettes/<VERSION>/<CALL>.json`. An **explicit `ear/publish.yaml` include rule is required** — `tool_registry_cassettes/**`, `CATALOG.lock`, `.ari_lib/replay.sh`: `curate()` reads `publish.yaml`, applies the include then `BUILTIN_DENY` (which already blocks `.env*` / `secrets/**` / `*.key` — a free leak guard), and copies survivors into `ear_published/` (`ari-skill-transform/src/curate.py`). Then `ors_seed_sandbox` → `fetch_code_bundle` auto-loads the ref + `bundle_sha256` from `publish_record.json` and `ari.clone` extracts the **whole** tree into `<checkpoint>/repro_sandbox/`, byte-verified (`clone/__init__.py`). The generated `reproduce.sh` sources a vendored **dependency-free `.ari_lib/replay.sh`** (pure bash + `sha256sum` — **no `jq`**, since the default apptainer image `docker://ubuntu:24.04` ships coreutils but not jq) whose `get_tool_result <server> <tool> <args.json>` recomputes the `CALL` hash, resolves `VERSION` from `CATALOG.lock`, `cat`s the cassette, and **exits non-zero on a miss** (fail-loud, the `42bcef5` lesson). The sandbox binds only `repo_dir` and is network-free (`ari-skill-paper-re/src/server.py`), so reading the fixture off the sandbox FS needs no ari-core, no broker, no MCP. This mirrors the existing `apply_patch` shim vendoring precedent. **blocker-2 ari-core change: none.**

> **Hard precondition:** when `ear/publish.yaml` is **absent**, `curate()` does **not** skip — it falls back to `_DEFAULT_PUBLISH_YAML` (which lists only `reproduce.sh`, `code/**`, `data/**`, `scripts/**`, `configs/**`), so the cassette tree is **silently omitted** and the published bundle ships **without cassettes**; `reproduce.sh` then fails loud at runtime. A curate-time guard (warn/error if `ear/tool_registry_cassettes/` exists but no include rule covers it) is part of Stage-B.

**Net effect:** both blockers are **zero-ari-core-change** at Stage A/B; the deferred Stage-C `SkillConfig` diff (§4) is unrelated to them (it only retires the double-subprocess). The broker, `cassette.py`, `invoke(mode=)`, `ARI_TOOL_REGISTRY_LIVE`, `CATALOG.lock`, and `.ari_lib/replay.sh` are **net-new Stage-A/B work** (the skill does not exist yet); only the cited `ari-core` / `curate` / `clone` / `paper-re` mechanisms are verified-present.

## 5. Honest delivered scope

Stage A/B delivers **materials/physics** breadth (`materials-project`, `nemad`, a few official-registry stdio servers) + the reproducibility layer — genuinely *broader than ToolUniverse's biomedical-only scope*. It does **not** deliver new HPC: ARI already ships `ari-skill-hpc` (sbatch/squeue/singularity). HPC breadth via Globus is **deferred to Stage C and must compose with the existing `ari-skill-hpc`, not duplicate it.** The "broader incl HPC" framing is therefore explicitly **out of launch scope**.

## 6. Build-readiness: blockers **resolved in design** (§4a) — one real-env gate remains

A skeptical review against ARI's actual implementation originally returned **flawed**. The two blockers below were re-confirmed against the code **and then resolved in the design** — both with **zero ari-core change** (see §4a). They are retained here for the record:

- **BLOCKER 1 (resolved) — the design had relied on `ARI_PHASE`, which does not exist.** Phase is consumed **only** by the driver to filter the tool list (`react_driver.py:252 mcp.list_tools(phase=agent_phase)`; `_phase_matches` applied in `list_tools` at `client.py:310`, def at `client.py:38`); it is **never propagated into a skill subprocess** (the child env is a fork-time `{**os.environ, "PYTHONPATH": …}` snapshot — `client.py:150`). A skill's `server.py` therefore cannot know the current phase.
  - **Resolution (§4a)**: drop the phase signal entirely — verified that all four reproduce stages are `phase: paper` direct tool calls with no `react:` block, so the broker never runs during reproduce and needs no phase awareness; live-vs-replay is governed by phase-scoping + the `ARI_TOOL_REGISTRY_LIVE` flag + the explicit `invoke(…, mode=)` arg. **Zero ari-core change.**

- **BLOCKER 2 (resolved) — the reproduce sandbox cannot see the skill or the cassettes.** ARI's reproduce phase runs a self-contained `reproduce.sh` inside an **isolated** sandbox that binds only `repo_dir` (`ari-skill-paper-re/src/server.py`); it has no ari-core, no MCP skill graph, no broker, and no cassettes unless explicitly vendored in.
  - **Resolution (§4a)**: vendor frozen cassettes through the existing curate→publish→clone chain — an explicit `ear/publish.yaml` include rule lands `tool_registry_cassettes/**` + `CATALOG.lock` + a dependency-free `.ari_lib/replay.sh` in `repro_sandbox/`, and the generated `reproduce.sh` reads them as on-disk fixtures (fail-loud on miss), no skill/MCP/network. **Zero ari-core change.** Hard precondition: an explicit `publish.yaml` is required — the default omits the cassette tree and would ship a bundle **silently without cassettes**.

Remaining **must-fix** items before the Stage A.0 PR (the real-env spike is the gate; the rest are Stage-A/B build items):
- **Real-env launch is unproven**: `docker` is unusable inside SLURM on R-CCS; `uvx` cold-spawn pulls from PyPI (network) — contradicts the offline/pinned posture. Requires a compute-node spike (§7).
- **Long-job timeout**: `invoke()` of a submit-style upstream must return the handle in **well under `DEFAULT_TOOL_TIMEOUT` (300s)** or ari-core's outer timeout kills the child.
- **Dependency closure**: a top-level wheel sha256 does **not** pin `uvx`/`npx` transitive deps — ship a `uv.lock`/vendored wheels or replay is not byte-stable.
- **Credential surface**: the child inherits the full `os.environ` (every key), not just its declared `key_env` — minimise the child env.
- **Tool-output cap**: `describe()`/`discover()` blobs must fit `react_driver._MAX_TOOL_OUTPUT = 4000` or schemas are silently truncated, breaking `invoke`-arg construction.
- **EAR bundling** *(resolved, §4a)*: `curate()` is rule-driven via `publish.yaml`; the default `_DEFAULT_PUBLISH_YAML` omits the cassette tree, so an explicit include rule for `tool_registry_cassettes/**` + `CATALOG.lock` + `.ari_lib/replay.sh` is required, plus a curate-time guard that warns if cassettes exist with no covering rule.

> Both blockers were "hand-off contract" mismatches (a phase signal that never reaches the skill; artifacts that never reach the sandbox) rather than logic errors — the same class as the failure modes tracked elsewhere in ARI. Catching **and resolving** them in review *before* writing code is the point of this RFC.

## 7. Decision & next steps (ordered)

1. **Real-env spike first (実機検証必須).** On an actual R-CCS **compute** node (not login/fake): confirm `uvx` is on PATH; confirm a pinned `uvx --from mcp-science==<v> mcp-science python-code-execution` launches and is stdio-reachable from inside a skill subprocess with **no network** (pre-warmed uv cache); confirm `docker` availability under SLURM. If `uvx` is unavailable, the mcp.science route collapses and this RFC is revised.
2. ~~Resolve the two blockers in the design~~ — **done (§4a):** both resolved with **zero ari-core change** (drop the phase signal; vendor cassettes via the existing curate→clone chain into the sandbox). The staging table's "ari-core change: zero" for Stage A/B is confirmed, not changed.
3. **Stage A.0 implementation PR** (separate, after 1–2): one `uvx` server + 5 tool stubs + the verified `cost_tracker` bootstrap, modelled on `ari-skill-web` + the VirSci-live precedent, default-OFF, reviewable as one small PR.
4. Restate scope honestly in all user-facing text: "broader than ToolUniverse (materials/physics + registry breadth)"; **HPC via the existing `ari-skill-hpc`**, Globus deferred and demand-gated.

## 8. Sources

- ToolUniverse — <https://aiscientist.tools/>, arXiv:2509.23426, <https://github.com/mims-harvard/ToolUniverse>
- Official MCP Registry — <https://registry.modelcontextprotocol.io/>, <https://github.com/modelcontextprotocol/registry>, <https://modelcontextprotocol.io/registry/registry-aggregators>
- mcp.science — <https://github.com/pathintegral-institute/mcp.science>
- MCP servers for Science & HPC — arXiv:2508.18489, <https://github.com/globus-labs/science-mcps>
- APIs.guru — <https://apis.guru/>; HuggingFace Hub revision pinning — `from_pretrained(revision=…)`, `HF_HUB_OFFLINE`
- ARI internals referenced: `ari-core/ari/mcp/client.py` (`_server_params`:150, `_phase_matches`:38 applied in `list_tools`:310, `call_tool`:354), `ari-core/ari/agent/react_driver.py:31,252,375`, `ari-core/ari/config/workflow.yaml` (reproduce stages `phase: paper`), `ari-skill-paper-re/src/server.py` (`run_reproduce`/`build_reproduce_sh`/`fetch_code_bundle`; sandbox binds only `repo_dir`), `ari-skill-transform/src/curate.py` (`_DEFAULT_PUBLISH_YAML`, `BUILTIN_DENY`), the `ari.clone` bundle extractor, `ari-skill-idea/src/snapshot.py`, `ari-skill-web/src/server.py`
