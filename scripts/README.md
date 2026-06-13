# scripts

Operational and utility scripts for building images, running services, and dev tooling.

## Contents

- `README.md` — this file.
- `build_pb_images.sh` — build the vendor PaperBench Docker images (`pb-env`, `pb-reproducer`).
- `gpu_ollama_monitor.sh` — monitor the SLURM GPU node running Ollama and re-tunnel it.
- `Plan.md` — ハーネス・run/analyze・scrub・cost ゲートの実装計画（handoff study）.
- `readme_sync.py` — sync per-directory README `## Contents` indexes with the tree (`--check` gates drift, `--write` regenerates; no LLM/API).
- `run_all_tests.sh` — run each skill's pytest suite in its own process.
- `run_ollama_gpu.sh` — start Ollama on a SLURM GPU node and tunnel it to the login node.
- `sc_paper_dogfood.py` — end-to-end dogfood driver: external paper PDF → PaperBench-format rubric generation (+ optional judge dry-run).
- `sc_paper_stage23_chain.py` — run Stage 2 (reproduce) + Stage 3 (judge) against a completed Stage 1 rollout workspace.
- `docs/` — documentation lint/gate scripts.
  - `README.md` — docs index.
  - `check_doc_links.py` — verify intra-docs links and HTML hrefs resolve to real files.
  - `check_doc_sources.py` — validate the `sources` front-matter each doc declares against the tree.
  - `check_translation_freshness.py` — detect translation drift via `last_verified` front-matter.
- `fewshot/` — fetch the few-shot review corpus.
  - `README.md` — fewshot index.
  - `fetch_arxiv.py` — per-source fetcher for arXiv.
  - `fetch_github_raw.py` — per-source fetcher for raw GitHub URLs.
  - `fetch_openreview.py` — per-source fetcher for OpenReview.
  - `manifest.yaml` — corpus manifest (per entry: `id`, `source`, `license`, optional `note`).
  - `sync.py` — reads the manifest and dispatches to the matching fetcher.
- `git-hooks/` — Version-controlled git hooks. Enable with `git config core.hooksPath scripts/git-hooks`
  - `README.md` — git-hooks index.
  - `pre-commit` — run `readme_sync.py --write` and re-stage modified tracked READMEs (no LLM/API; non-blocking).
- `letta/` — Letta memory-backend deployment helpers.
  - `README.md` — letta index.
  - `docker-compose.yml` — Letta + Postgres (laptop/workstation).
  - `start_pip.sh` — container-less single-user deployment with SQLite.
  - `start_singularity.sh` — Singularity/Apptainer deployment for HPC.
  - `pg-init/` — Postgres init SQL for the Letta store.
    - `README.md` — pg-init index.
    - `01-vector.sql` — `CREATE EXTENSION IF NOT EXISTS vector` (pgvector).
- `registry/` — ari-registry service deployment helpers.
  - `README.md` — registry index.
  - `docker-compose.yml` — production stack (nginx + uvicorn + sqlite file volume).
  - `start_local.sh` — uvicorn + sqlite single-process, for laptop/dev.
  - `start_singularity.sh` — HPC fallback running the registry inside an Apptainer SIF.
- `setup/` — installer step scripts and shared shell helpers.
  - `README.md` — setup index.
  - `banner.sh` — ASCII banner printer.
  - `colors.sh` — shared ANSI color definitions.
  - `detect_env.sh` — detect OS, shell, Python, pip, git.
  - `install_core.sh` — install core Python dependencies.
  - `install_deps.sh` — install/orchestrate component dependencies.
  - `install_frontend.sh` — install the viz frontend (npm).
  - `install_latex.sh` — install the LaTeX toolchain.
  - `install_letta.sh` — install/deploy the Letta memory backend.
  - `install_paperbench.sh` — install the PaperBench vendor stack.
  - `install_pdf.sh` — install PDF tooling.
  - `lang_select.sh` — interactive setup-language selection.
  - `messages.sh` — localized setup message strings.
  - `setup_env.sh` — bootstrap `ARI/.env` with the env vars the program reads.
  - `spinner.sh` — terminal spinner/progress helper.
  - `verify.sh` — post-install verification checks.
