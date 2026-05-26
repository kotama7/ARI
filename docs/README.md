# ARI Documentation

This directory is organized along the [Diátaxis](https://diataxis.fr/) framework:
**Tutorial** (getting started), **Explanation** (concepts), **How-to** (guides),
and **Reference**. Plus `about/` for project meta and `_archive/` for historical
snapshots.

> 🌐 **Languages:** English (this page) · 日本語 · 中文 — per-document
> availability and links are in the [Translation parity](#translation-parity)
> table below.

> ℹ️ This index is the entry point that does not depend on the HTML site
> (`index.html` / `docs.html`). It is the single source of truth for the table
> of contents and the multilingual parity matrix.

## Naming conventions

| Rule | Detail |
|---|---|
| Directories | Diátaxis 4 categories + `about` + `_archive` (+ optional `assets`) |
| File names | **snake_case, stem preserved** (`hpc_setup.md` etc. keep their name) |
| `howto/` → `guides/` | renamed to match Diátaxis "how-to = guide" |

## Table of contents

### Getting started — *Tutorial*

- [Overview & learning path](getting-started/index.md)
- [Quickstart](getting-started/quickstart.md)
- [Your first experiment, end to end](getting-started/first_experiment_tutorial.md)
- [FAQ](getting-started/faq.md)

### Concepts — *Explanation*

- [Philosophy](concepts/PHILOSOPHY.md)
- [Architecture](concepts/architecture.md)
- [BFTS algorithm](concepts/bfts.md)
- [Memory architecture](concepts/memory.md)
- [Publication lifecycle](concepts/publication-lifecycle.md)

### Guides — *How-to*

- [HPC setup](guides/hpc_setup.md)
- [Extension guide](guides/extension_guide.md)
- [Experiment file](guides/experiment_file.md)
- [Migration](guides/migration.md)
- [Testing](guides/testing.md)
- [Troubleshooting](guides/troubleshooting.md)

**PaperBench**

- [PaperBench quickstart](guides/paperbench/paperbench_quickstart.md)
- [PaperBench GUI](guides/paperbench/paperbench_gui.md)
- [Paper import](guides/paperbench/paper_import.md)
- [Multi-node setup](guides/paperbench/multi_node_setup.md)
- [Compute-node safety](guides/paperbench/compute_node_safety.md)
- [PaperBench troubleshooting](guides/paperbench/paperbench_troubleshooting.md)

### Reference

- [CLI reference](reference/cli_reference.md)
- [Configuration](reference/configuration.md)
- [MCP skills](reference/skills.md)
- [Registry](reference/registry.md)
- [MCP tools](reference/mcp_tools.md)
- [Environment variables](reference/environment_variables.md)
- [File formats](reference/file_formats.md)
- [Public API](reference/public_api.md)
- [REST API](reference/rest_api.md)
- [Execution profile](reference/execution_profile.md)
- [Rubric schema](reference/rubric_schema.md)
- [PaperBench API](reference/api_paperbench.md)
- [Glossary](reference/glossary.md)

### About

- [Release policy](about/release_policy.md)

### Archive

- [Refactor audit](_archive/refactor_audit.md) — historical snapshot (not a live doc)

## Translation parity

✓ links to the translation; ✗ marks a gap. The matrix is authoritative — a
release gate checks it against the tree (`docs/about/release_policy.md` §4).

| Document | en | ja | zh |
|---|:--:|:--:|:--:|
| getting-started/index | [✓](getting-started/index.md) | [✓](ja/getting-started/index.md) | [✓](zh/getting-started/index.md) |
| getting-started/quickstart | [✓](getting-started/quickstart.md) | [✓](ja/getting-started/quickstart.md) | [✓](zh/getting-started/quickstart.md) |
| getting-started/first_experiment_tutorial | [✓](getting-started/first_experiment_tutorial.md) | [✓](ja/getting-started/first_experiment_tutorial.md) | [✓](zh/getting-started/first_experiment_tutorial.md) |
| getting-started/faq | [✓](getting-started/faq.md) | [✓](ja/getting-started/faq.md) | [✓](zh/getting-started/faq.md) |
| concepts/PHILOSOPHY | [✓](concepts/PHILOSOPHY.md) | [✓](ja/concepts/PHILOSOPHY.md) | [✓](zh/concepts/PHILOSOPHY.md) |
| concepts/architecture | [✓](concepts/architecture.md) | [✓](ja/concepts/architecture.md) | [✓](zh/concepts/architecture.md) |
| concepts/bfts | [✓](concepts/bfts.md) | [✓](ja/concepts/bfts.md) | [✓](zh/concepts/bfts.md) |
| concepts/memory | [✓](concepts/memory.md) | [✓](ja/concepts/memory.md) | [✓](zh/concepts/memory.md) |
| concepts/publication-lifecycle | [✓](concepts/publication-lifecycle.md) | [✓](ja/concepts/publication-lifecycle.md) | [✓](zh/concepts/publication-lifecycle.md) |
| guides/hpc_setup | [✓](guides/hpc_setup.md) | [✓](ja/guides/hpc_setup.md) | [✓](zh/guides/hpc_setup.md) |
| guides/extension_guide | [✓](guides/extension_guide.md) | [✓](ja/guides/extension_guide.md) | [✓](zh/guides/extension_guide.md) |
| guides/experiment_file | [✓](guides/experiment_file.md) | [✓](ja/guides/experiment_file.md) | [✓](zh/guides/experiment_file.md) |
| guides/migration | [✓](guides/migration.md) | [✓](ja/guides/migration.md) | [✓](zh/guides/migration.md) |
| guides/testing | [✓](guides/testing.md) | [✓](ja/guides/testing.md) | [✓](zh/guides/testing.md) |
| guides/troubleshooting | [✓](guides/troubleshooting.md) | [✓](ja/guides/troubleshooting.md) | [✓](zh/guides/troubleshooting.md) |
| guides/paperbench/paperbench_quickstart | [✓](guides/paperbench/paperbench_quickstart.md) | [✓](ja/guides/paperbench/paperbench_quickstart.md) | [✓](zh/guides/paperbench/paperbench_quickstart.md) |
| guides/paperbench/paperbench_gui | [✓](guides/paperbench/paperbench_gui.md) | [✓](ja/guides/paperbench/paperbench_gui.md) | [✓](zh/guides/paperbench/paperbench_gui.md) |
| guides/paperbench/paper_import | [✓](guides/paperbench/paper_import.md) | [✓](ja/guides/paperbench/paper_import.md) | [✓](zh/guides/paperbench/paper_import.md) |
| guides/paperbench/multi_node_setup | [✓](guides/paperbench/multi_node_setup.md) | [✓](ja/guides/paperbench/multi_node_setup.md) | [✓](zh/guides/paperbench/multi_node_setup.md) |
| guides/paperbench/compute_node_safety | [✓](guides/paperbench/compute_node_safety.md) | [✓](ja/guides/paperbench/compute_node_safety.md) | [✓](zh/guides/paperbench/compute_node_safety.md) |
| guides/paperbench/paperbench_troubleshooting | [✓](guides/paperbench/paperbench_troubleshooting.md) | [✓](ja/guides/paperbench/paperbench_troubleshooting.md) | [✓](zh/guides/paperbench/paperbench_troubleshooting.md) |
| reference/cli_reference | [✓](reference/cli_reference.md) | [✓](ja/reference/cli_reference.md) | [✓](zh/reference/cli_reference.md) |
| reference/configuration | [✓](reference/configuration.md) | [✓](ja/reference/configuration.md) | [✓](zh/reference/configuration.md) |
| reference/skills | [✓](reference/skills.md) | [✓](ja/reference/skills.md) | [✓](zh/reference/skills.md) |
| reference/registry | [✓](reference/registry.md) | [✓](ja/reference/registry.md) | [✓](zh/reference/registry.md) |
| reference/mcp_tools | [✓](reference/mcp_tools.md) | [✓](ja/reference/mcp_tools.md) | [✓](zh/reference/mcp_tools.md) |
| reference/environment_variables | [✓](reference/environment_variables.md) | [✓](ja/reference/environment_variables.md) | [✓](zh/reference/environment_variables.md) |
| reference/file_formats | [✓](reference/file_formats.md) | [✓](ja/reference/file_formats.md) | [✓](zh/reference/file_formats.md) |
| reference/public_api | [✓](reference/public_api.md) | [✓](ja/reference/public_api.md) | [✓](zh/reference/public_api.md) |
| reference/rest_api | [✓](reference/rest_api.md) | [✓](ja/reference/rest_api.md) | [✓](zh/reference/rest_api.md) |
| reference/execution_profile | [✓](reference/execution_profile.md) | [✓](ja/reference/execution_profile.md) | [✓](zh/reference/execution_profile.md) |
| reference/rubric_schema | [✓](reference/rubric_schema.md) | [✓](ja/reference/rubric_schema.md) | [✓](zh/reference/rubric_schema.md) |
| reference/api_paperbench | [✓](reference/api_paperbench.md) | [✓](ja/reference/api_paperbench.md) | [✓](zh/reference/api_paperbench.md) |
| reference/glossary | [✓](reference/glossary.md) | [✓](ja/reference/glossary.md) | [✓](zh/reference/glossary.md) |
| about/release_policy | [✓](about/release_policy.md) | [✓](ja/about/release_policy.md) | [✓](zh/about/release_policy.md) |
| _archive/refactor_audit | [✓](_archive/refactor_audit.md) | [✓](ja/_archive/refactor_audit.md) | [✓](zh/_archive/refactor_audit.md) |

## Source traceability

Each live doc declares, in YAML front-matter, which source files it documents
(`sources:` with repo-root-relative paths). Two gate scripts enforce this:

- `scripts/docs/check_doc_sources.py` — every declared source path exists.
- `scripts/docs/check_doc_links.py` — every intra-docs link / HTML href resolves.

See the source-mapping design for the schema and rollout.
