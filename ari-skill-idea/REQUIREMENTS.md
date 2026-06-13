# ari-skill-idea Requirements

## Overview

MCP Server for research idea generation, literature survey, and gap analysis.

## Design

- `survey` and `make_metric_spec` are fully deterministic (no LLM)
- `generate_ideas` uses LLM only in pre-BFTS phase (outside the search loop)
- Survey uses TF-IDF-style keyword scoring over arXiv + Semantic Scholar results

## MCP Tools

### survey(query: str, max_results: int = 10) -> dict
Surveys related prior work. Returns titles, abstracts, and relevance scores.

### make_metric_spec(experiment_file: str) -> dict
Parses experiment Markdown to extract metric_keyword, scoring_guide,
and min_expected_metric. Returns a MetricSpec dict.

### generate_ideas(goal: str, survey_results: list, n_ideas: int = 3) -> dict
Generates research hypotheses using LLM. Called once before BFTS starts.

## VirSci-live (vendor-wrap)

`generate_ideas` has two interchangeable idea-generation engines behind one
stable contract. The default ("reimpl") drives a re-implemented discussion loop
(`_virsci_discussion_loop`) via litellm. The opt-in ("real_wrap") runs VirSci's
**actual** mechanism — `Platform.select_coauthors` (freshness team formation) +
`Team.generate_idea` (multi-agent deliberation) from `vendor/virsci` — on a live
Semantic Scholar snapshot. The path is reported in
`ideas.virsci_integration_status` (`"real_wrap"` | `"reimpl: …"`).

Scope: a single live S2 snapshot (no era split / no paper-parity — those are
VirSci's retrospective-benchmark artifacts). `freshness`/`diversity` are
preserved via S2 author profiles + co-author graph; held-out-future metrics
(Contemporary Dissimilarity / contemporary-impact) are out of scope.

### Components (skill side)

- `src/snapshot.py` — `build_snapshot(topic, out_dir, n_authors, n_papers)`:
  - corpus from S2 `/paper/search` incl. pre-computed `embedding.specter_v2`.
  - SPECTER2 cosine index (faiss-cpu `IndexFlatIP` over L2-normalised vectors);
    embedding-less papers are kept for keyword fallback, excluded from the index.
  - author profiles `books/author_<i>.txt` (diversity source).
  - symmetric integer co-author `adjacency.txt` with +1 Laplacian smoothing so
    `select_coauthors`' `arr/sum(arr)` is always well-defined (freshness source).
  - frozen + reproducible under `<out_dir>/virsci_snapshot/` with
    `snapshot_manifest.json` (cache reuse keyed on `sha(topic,n_authors,n_papers)`).
- `src/virsci_runtime.py`:
  - **Auto-stubber** (`_AutoStubFinder`): a single meta-path finder that
    fabricates inert stubs for ONLY the vendored agentscope's *unused* optional
    backends (dashscope, grpc, llama_index, zhipuai, gradio, ollama, …, plus the
    server-only subpackages `agentscope.studio/web/service`). Installed packages
    (openai, litellm, numpy, faiss, torch, transformers) are never stubbed. This
    collapses agentscope's ~25-site eager-import "balloon" into one mechanism and
    keeps `vendor/virsci/**` unedited. `_patch_agentscope_logging` binds inert
    studio/gradio stand-ins onto `agentscope.logging` globals (the only stubs the
    idea path touches at runtime).
  - `LivePlatform(Platform)` — overrides `__init__` (no `faiss.read_index` /
    hard-coded corpus paths / knowledge bank) and `reference_paper` (local
    SPECTER2 query embedding → faiss NN over the snapshot corpus; keyword
    fallback when an embedding is unavailable).
  - `build_model_configs` — in-memory agentscope `openai_chat` config pointing at
    ARI's OpenAI-compatible CLI shim (`ARI_LLM_API_BASE`, normalised to `/v1`).
  - `run_virsci_live(...)` — driver: real `select_coauthors` → `generate_idea`
    on the formed teams → parse/score/dedup → top-N. All vendor stdout/loguru is
    redirected to `<log_dir>/` so the MCP stdio channel stays clean.
- `src/server.py` — `generate_ideas` gates the real path on
  `ARI_IDEA_VIRSCI_REAL`; any failure (missing deps, runtime error, empty
  output) degrades to the reimpl loop. The 9-key idea contract
  (`title, description, novelty, feasibility, experiment_plan, novelty_score,
  feasibility_score, overall_score`), 0-1 score normalisation, descending
  `overall_score` sort, ancestor injection, pinned-idea dedup, and
  `cost_tracker.bootstrap_skill('idea')` are preserved on both paths.
  `n_agents`/`discussion_rounds`/`papers_analyzed` report the **actual** vendor
  values on the real path (vendor defaults, no tool-arg clamp).

### Env contract (`ARI_IDEA_VIRSCI_*`)

The only setting surface. Read via `os.getenv`; GUI and CLI just set these, and
`ari-core/ari/mcp/client.py` propagates them to the skill subprocess via
`env={**os.environ}`. The discussion LLM stays selectable via the existing
per-phase `ARI_MODEL_IDEA`.

| Var | Default | Meaning |
|-----|---------|---------|
| `ARI_IDEA_VIRSCI_REAL` | unset (off) | toggle the real vendor-wrap path |
| `ARI_IDEA_VIRSCI_K` | 7 | `group_max_discuss_iteration` (discussion turns) |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | 3 | `max_teammember` |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | 16 | `select_coauthors` author pool |
| `ARI_IDEA_VIRSCI_N_PAPERS` | 800 | SPECTER2 retrieval corpus size |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | n_ideas | cap on teams driven through `generate_idea` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | `allenai/specter2_base` | local query embedder |

### Added dependencies (`virsci` extra)

`faiss-cpu`, `transformers`, `torch`, `loguru`, `sqlalchemy` (see
`pyproject.toml [project.optional-dependencies] virsci`). GPU is not required.
SPECTER2 weights are fetched at runtime. When the extra is absent the skill
degrades to the reimpl loop. External: Semantic Scholar API
(`SEMANTIC_SCHOLAR_API_KEY` recommended for `embedding.specter_v2` + rate
limits) and the ARI OpenAI-compatible CLI shim.

### Invariants

- `vendor/virsci/**` is never edited (submodule pin `07097fd`). All adaptation
  is via the auto-stubber + `LivePlatform`/`reference_paper` overrides.
- `ARI_IDEA_VIRSCI_REAL` unset ⇒ behaviour byte-identical to before.
- `survey` / `generate_ideas` public signatures are unchanged.
