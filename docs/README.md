# ARI Documentation

This directory is organized along the [Diátaxis](https://diataxis.fr/) framework:
**Tutorial** (getting started), **Explanation** (concepts), **How-to** (guides),
and **Reference**. Plus `about/` for project meta.

> 🌐 **Languages:** English (this page) · 日本語 · 中文 — per-document
> availability and links are in the [Translation parity](#translation-parity)
> table below.

> ℹ️ This index is the entry point that does not depend on the HTML site
> (`index.html` / `docs.html`). It is the single source of truth for the table
> of contents and the multilingual parity matrix.

## Naming conventions

| Rule | Detail |
|---|---|
| Directories | Diátaxis 4 categories + `about` (+ optional `assets`) |
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
- [Verifiable research memory](concepts/verifiable_research_memory.md)
- [Publication lifecycle](concepts/publication-lifecycle.md)

### Guides — *How-to*

- [HPC setup](guides/hpc_setup.md)
- [Extension guide](guides/extension_guide.md)
- [Experiment file](guides/experiment_file.md)
- [Cookbook](guides/cookbook.md)
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
- [Internal boundaries](reference/internal_boundaries.md)
- [REST API](reference/rest_api.md)
- [Execution profile](reference/execution_profile.md)
- [Rubric schema](reference/rubric_schema.md)
- [PaperBench API](reference/api_paperbench.md)
- [Glossary](reference/glossary.md)

### About

- [About index](about/index.md)
- [Release policy](about/release_policy.md)
- [Compatibility & support](about/compatibility.md)

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
| concepts/verifiable_research_memory | [✓](concepts/verifiable_research_memory.md) | [✓](ja/concepts/verifiable_research_memory.md) | [✓](zh/concepts/verifiable_research_memory.md) |
| concepts/publication-lifecycle | [✓](concepts/publication-lifecycle.md) | [✓](ja/concepts/publication-lifecycle.md) | [✓](zh/concepts/publication-lifecycle.md) |
| guides/hpc_setup | [✓](guides/hpc_setup.md) | [✓](ja/guides/hpc_setup.md) | [✓](zh/guides/hpc_setup.md) |
| guides/extension_guide | [✓](guides/extension_guide.md) | [✓](ja/guides/extension_guide.md) | [✓](zh/guides/extension_guide.md) |
| guides/experiment_file | [✓](guides/experiment_file.md) | [✓](ja/guides/experiment_file.md) | [✓](zh/guides/experiment_file.md) |
| guides/cookbook | [✓](guides/cookbook.md) | [✓](ja/guides/cookbook.md) | [✓](zh/guides/cookbook.md) |
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
| reference/internal_boundaries | [✓](reference/internal_boundaries.md) | — | — |
| reference/rest_api | [✓](reference/rest_api.md) | [✓](ja/reference/rest_api.md) | [✓](zh/reference/rest_api.md) |
| reference/execution_profile | [✓](reference/execution_profile.md) | [✓](ja/reference/execution_profile.md) | [✓](zh/reference/execution_profile.md) |
| reference/rubric_schema | [✓](reference/rubric_schema.md) | [✓](ja/reference/rubric_schema.md) | [✓](zh/reference/rubric_schema.md) |
| reference/api_paperbench | [✓](reference/api_paperbench.md) | [✓](ja/reference/api_paperbench.md) | [✓](zh/reference/api_paperbench.md) |
| reference/glossary | [✓](reference/glossary.md) | [✓](ja/reference/glossary.md) | [✓](zh/reference/glossary.md) |
| about/index | [✓](about/index.md) | [✓](ja/about/index.md) | [✓](zh/about/index.md) |
| about/release_policy | [✓](about/release_policy.md) | [✓](ja/about/release_policy.md) | [✓](zh/about/release_policy.md) |
| about/compatibility | [✓](about/compatibility.md) | [✓](ja/about/compatibility.md) | [✓](zh/about/compatibility.md) |

## Homepage static site

Deployed as a single GitHub Pages artifact (`https://kotama7.github.io/ARI/`,
project sub-path `/ARI/`) assembled by `.github/workflows/pages.yml`. Two
surfaces, one brand, one language state (L3 toolchain split):

- **Landing** (`/ARI/`) — bespoke static `index.html` (hero, demo, animations).
- **Docs** (`/ARI/docs/`) — **VitePress** SSG, locale-routed `en` / `ja` (`/ja/`)
  / `zh` (`/zh/`), built from the markdown tree above (the **authoritative**
  source, consumed unmodified). `docs.html` is gone; old bookmarks hit a noindex
  redirect stub assembled at `/ARI/docs.html`.

Files:

- **`tokens.css`** — single source of truth for design colour tokens (raw
  hex/rgba live ONLY here and in SVG assets). Consumed by both surfaces:
  `site.css` (landing) and the VitePress theme (`.vitepress/theme/brand-bridge.css`
  aliases `--vp-c-*` onto these tokens — no drift).
- **`site.css`** — landing component classes; references the `--*` tokens.
- **`version.json`** + `i18n/version.js` — the product version lives in one place
  and is injected into `#ari-version`; no version literal is hard-coded.
- **`i18n/`** — the **landing** language-switcher dictionaries
  (`landing.{en,ja,zh}.js`, merged into `window.LANGS`). `i18n.js`'s `setLang`
  updates `<html lang>`, `<title>`, button `aria-pressed`, and deep-links the
  `.js-docs-link` to the matching VitePress locale. Parity / orphan / co-change
  gated by `check_site_i18n.py`. (The docs surface owns its own i18n via
  VitePress locales; there is no `docs.*.js`.)
- **`.vitepress/`** — VitePress `config.ts` (base `/ARI/docs/`, locales, local
  CJK search, sitemap, per-locale canonical + hreflang via `transformPageData`,
  fs-driven sidebar), custom `theme/` (brand-bridge + `lang-bridge.ts` writing
  `localStorage('ari-lang')` from the active docs locale). `package.json` /
  `package-lock.json` pin the build; `node_modules` and `dist` are gitignored.
- **`public/report/{en,ja,zh}.pdf`** + **`assets/report/{en,ja,zh}.pdf`** —
  copies of `report/{en,ja,zh}/main.pdf` (`report/` never modified), surfaced by
  VitePress (`/docs/report/*.pdf`) and the landing respectively. Keep both in
  sync with `scripts/docs/sync_report_pdf.sh` (`--check` gates drift).
- **`assets/anim/*.js`** — dependency-free algorithm animations (BFTS / ReAct /
  6-step pipeline / VirSci) on the shared `anim-core.js` loader; reduced-motion
  renders a single static frame.
- **`sitemap.xml`** (landing) + VitePress-generated `/docs/sitemap.xml` (per-
  locale + hreflang); both submitted via Search Console. **`robots.txt`** is
  documentation-only (a project sub-path `robots.txt` is ignored by crawlers).
- **`.nojekyll`** — disables Jekyll so `_`-prefixed paths are served verbatim.

**Cross-surface language continuity:** `localStorage('ari-lang')` is the shared
key. The VitePress `lang-bridge` writes it from the active `/docs/(ja|zh)/`
locale; the landing reads it to deep-link "Docs" and the redirect stub uses it
to pick the destination locale.

**Rollback:** `pages.yml` documents reverting to the build-less passthrough
(upload `docs/`); the landing is plain static so it survives a VitePress revert.

**Intentionally deferred (recorded per the homepage-redesign plan's deletion
clause):**

- **Report HTML publication** (`docs/report/{en,ja,zh}/` chapter deep links) —
  *not implemented*: the HTML toolchain (pandoc / latexml / make4ht) is absent
  in the build environment and the TikZ figure previews are gitignored, so a
  reproducible build is not yet possible. The report is surfaced as PDF instead
  (`/docs/report/*.pdf` and landing `assets/report/`). `check_doc_links.py`
  already excludes `docs/report/` for when this is built. Revisit once a
  pandoc-capable build host exists.

## Source traceability

Each live doc declares, in YAML front-matter, which source files it documents
(`sources:` with repo-root-relative paths) and a `last_verified` date. A family
of gate scripts under `scripts/docs/` enforces the contract:

- `scripts/docs/check_doc_sources.py` — every declared source path exists.
- `scripts/docs/check_doc_links.py` — every intra-docs link / HTML href resolves.
- `scripts/docs/check_translation_freshness.py` — no `ja`/`zh` translation has
  a `last_verified` older than its English source (catches *content* drift that
  the existence-only parity table cannot). Warning-only by default; `--strict`
  to fail.
- `scripts/docs/check_i18n_js.py` — `docs/i18n/landing.{en,ja,zh}.js` declare
  one identical key set (the landing language switcher; the docs surface owns
  its i18n via VitePress locales — see [Homepage static site](#homepage-static-site)).
- `scripts/docs/check_site_i18n.py` — HTML-site i18n integrity: surface parity
  (reuses `check_i18n_js`), no orphan `t-` ids (every `id="t-…"` resolves to a
  dict key), en→ja/zh co-change, report-PDF sync, and version single-source.
- `scripts/docs/check_readme_parity.py` — the root `README.{md,ja,zh}` share
  one Markdown heading shape (fence-aware).
- `scripts/docs/check_ref_coupling.py` — the *reverse* of `check_doc_sources`:
  when a referenced source changes in a PR, the doc that declares it in
  `sources:` should bump `last_verified` (diff-based, advisory).
- `scripts/docs/check_report_cochange.py` — a `report/{en,ja,zh}`
  language-paired file edited in one language is mirrored in the other two in
  the same PR (diff-based).

These run in CI via `.github/workflows/docs-sync.yml` (full-tree invariants
**plus a `vitepress-build` job that fails the PR if the docs build breaks**)
and `.github/workflows/docs-change-coupling.yml` (diff-based). `check_doc_sources`,
`check_i18n_js`, `check_site_i18n`, `check_doc_links --html-only`,
`check_readme_parity`, the report Gate 6, `check_report_cochange`, and the
VitePress build are hard gates; markdown-tree freshness and links, and reference
coupling, are advisory (they carry pre-existing markdown-tree findings owned by
the docs-expansion effort). See [How to Test ARI Code](guides/testing.md#what-gets-tested-at-pr-time).

**When you change a doc:** update the English file *and* both translations in the
same change, then set `last_verified` on all three to the edit date. If you
cannot update a translation immediately, leave its `last_verified` behind so the
freshness gate flags it as stale rather than letting the drift pass silently.

See the source-mapping design for the schema and rollout.
