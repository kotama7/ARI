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

- [Quickstart](quickstart.md)

### Concepts — *Explanation*

- [Philosophy](PHILOSOPHY.md)
- [Architecture](architecture.md)

### Guides — *How-to*

- [HPC setup](hpc_setup.md)
- [Extension guide](extension_guide.md)
- [Experiment file](experiment_file.md)
- [Migration](howto/migration.md)
- [Testing](howto/testing.md)
- [Troubleshooting](howto/troubleshooting.md)

**PaperBench**

- [PaperBench quickstart](howto/paperbench_quickstart.md)
- [PaperBench GUI](howto/paperbench_gui.md)
- [Paper import](howto/paper_import.md)
- [Multi-node setup](howto/multi_node_setup.md)
- [Compute-node safety](howto/compute_node_safety.md)
- [PaperBench troubleshooting](howto/paperbench_troubleshooting.md)

### Reference

- [CLI reference](cli_reference.md)
- [Configuration](configuration.md)
- [MCP skills](skills.md)
- [Registry](registry.md)
- [MCP tools](reference/mcp_tools.md)
- [Environment variables](reference/environment_variables.md)
- [File formats](reference/file_formats.md)
- [Public API](reference/public_api.md)
- [REST API](reference/rest_api.md)
- [Execution profile](reference/execution_profile.md)
- [Rubric schema](reference/rubric_schema.md)
- [PaperBench API](reference/api_paperbench.md)

### About

- [Release policy](release_policy.md)

### Archive

- [Refactor audit](refactor_audit.md) — historical snapshot (not a live doc)

## Translation parity

✓ links to the translation; ✗ marks a gap. The matrix is authoritative — a
release gate checks it against the tree (`docs/release_policy.md` §4).

| Document | en | ja | zh |
|---|:--:|:--:|:--:|
| getting-started/quickstart | [✓](quickstart.md) | [✓](ja/quickstart.md) | [✓](zh/quickstart.md) |
| concepts/PHILOSOPHY | [✓](PHILOSOPHY.md) | [✓](ja/PHILOSOPHY.md) | [✓](zh/PHILOSOPHY.md) |
| concepts/architecture | [✓](architecture.md) | [✓](ja/architecture.md) | [✓](zh/architecture.md) |
| guides/hpc_setup | [✓](hpc_setup.md) | [✓](ja/hpc_setup.md) | [✓](zh/hpc_setup.md) |
| guides/extension_guide | [✓](extension_guide.md) | [✓](ja/extension_guide.md) | [✓](zh/extension_guide.md) |
| guides/experiment_file | [✓](experiment_file.md) | [✓](ja/experiment_file.md) | [✓](zh/experiment_file.md) |
| guides/migration | [✓](howto/migration.md) | ✗ | ✗ |
| guides/testing | [✓](howto/testing.md) | ✗ | ✗ |
| guides/troubleshooting | [✓](howto/troubleshooting.md) | ✗ | ✗ |
| guides/paperbench/paperbench_quickstart | [✓](howto/paperbench_quickstart.md) | [✓](ja/howto/paperbench_quickstart.md) | [✓](zh/howto/paperbench_quickstart.md) |
| guides/paperbench/paperbench_gui | [✓](howto/paperbench_gui.md) | [✓](ja/howto/paperbench_gui.md) | [✓](zh/howto/paperbench_gui.md) |
| guides/paperbench/paper_import | [✓](howto/paper_import.md) | [✓](ja/howto/paper_import.md) | [✓](zh/howto/paper_import.md) |
| guides/paperbench/multi_node_setup | [✓](howto/multi_node_setup.md) | [✓](ja/howto/multi_node_setup.md) | [✓](zh/howto/multi_node_setup.md) |
| guides/paperbench/compute_node_safety | [✓](howto/compute_node_safety.md) | [✓](ja/howto/compute_node_safety.md) | [✓](zh/howto/compute_node_safety.md) |
| guides/paperbench/paperbench_troubleshooting | [✓](howto/paperbench_troubleshooting.md) | [✓](ja/howto/paperbench_troubleshooting.md) | [✓](zh/howto/paperbench_troubleshooting.md) |
| reference/cli_reference | [✓](cli_reference.md) | [✓](ja/cli_reference.md) | [✓](zh/cli_reference.md) |
| reference/configuration | [✓](configuration.md) | [✓](ja/configuration.md) | [✓](zh/configuration.md) |
| reference/skills | [✓](skills.md) | [✓](ja/skills.md) | [✓](zh/skills.md) |
| reference/registry | [✓](registry.md) | [✓](ja/registry.md) | [✓](zh/registry.md) |
| reference/mcp_tools | [✓](reference/mcp_tools.md) | ✗ | ✗ |
| reference/environment_variables | [✓](reference/environment_variables.md) | ✗ | ✗ |
| reference/file_formats | [✓](reference/file_formats.md) | ✗ | ✗ |
| reference/public_api | [✓](reference/public_api.md) | ✗ | ✗ |
| reference/rest_api | [✓](reference/rest_api.md) | ✗ | ✗ |
| reference/execution_profile | [✓](reference/execution_profile.md) | [✓](ja/reference/execution_profile.md) | [✓](zh/reference/execution_profile.md) |
| reference/rubric_schema | [✓](reference/rubric_schema.md) | [✓](ja/reference/rubric_schema.md) | [✓](zh/reference/rubric_schema.md) |
| reference/api_paperbench | [✓](reference/api_paperbench.md) | [✓](ja/reference/api_paperbench.md) | [✓](zh/reference/api_paperbench.md) |
| about/release_policy | [✓](release_policy.md) | ✗ | ✗ |

## Source traceability

Each live doc declares, in YAML front-matter, which source files it documents
(`sources:` with repo-root-relative paths). Two gate scripts enforce this:

- `scripts/docs/check_doc_sources.py` — every declared source path exists.
- `scripts/docs/check_doc_links.py` — every intra-docs link / HTML href resolves.

See the source-mapping design for the schema and rollout.
