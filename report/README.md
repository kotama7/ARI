# ARI System Report

This directory holds the **ARI system report** — an arXiv-style technical
report describing the exploration algorithm and paper-generation pipeline
of [ARI](../README.md) at the v0.8.0 snapshot.

The report is built in three languages (en, ja, zh) and published in two
formats (PDF, HTML). The English version is the master; ja and zh are
hand-maintained alongside it and validated by a structural-parity gate
(`check_i18n.py`).

## Layout

```
report/
├── README.md                       # this file
├── Makefile                        # all build / check targets
├── .latexmkrc                      # latexmk configuration
├── setup_fonts.sh                  # one-off Noto CJK installation
│
├── CLAUDE.md                       # LLM-author rules for editing report/
├── shared/
│   ├── preamble.tex                # common LaTeX preamble (engine-aware)
│   ├── notation.tex                # math symbol macros (Gate 3 source)
│   ├── glossary.yaml               # en/ja/zh terminology master (Gate 7)
│   ├── references.bib              # bibliography (Gate 4 source)
│   ├── references.log.yaml         # provenance for each entry
│   ├── references.cache.json       # S2/DOI lookup cache
│   ├── references_pdf/             # PDF copies of cited papers (gitignored)
│   ├── appendix/prompts/           # snapshotted ari-core prompts (Gate 10)
│   ├── figures/
│   │   ├── style.tikzstyles        # TikZ style file
│   │   ├── CLAUDE.md               # LLM-author rules for figures
│   │   ├── tikz/                   # hand-written TikZ + dot2tex output
│   │   ├── pgf/                    # matplotlib PGF output (committed)
│   │   ├── dot/                    # graphviz intermediates (committed)
│   │   ├── data/                   # frozen evaluation snapshots
│   │   └── scripts/                # build_all.py + per-figure renderers
│   └── tables/                     # auto-generated longtables
│
├── en/main.tex,strings.tex,chapters/*.tex   # master English source
├── ja/main.tex,strings.tex,chapters/*.tex   # hand-maintained Japanese
├── zh/main.tex,strings.tex,chapters/*.tex   # hand-maintained Simplified Chinese
│
├── scripts/
│   ├── snapshot_prompts.py         # refresh shared/appendix/prompts/
│   ├── check_prompt_snapshots.py   # Gate 10 — snapshot bytes match source
│   ├── check_*.py                  # other quality gates (see below)
│   ├── render_tikz.py              # standalone TikZ render + bbox overlap test
│   ├── build_html.sh               # latexml | make4ht driver
│   ├── inject_langnav.py           # add language switcher to HTML
│   ├── fetch_bib.py                # add a verified bib entry (S2 cross-check)
│   ├── pull_pdfs.py                # re-download referenced PDFs
│   └── build_tables.py             # auto-generate T2 / T3 tables
│
└── html/{en,ja,zh}/index.html      # HTML build output (gitignored)
```

## Building

PDF (per language):

```bash
make pdf-en           # latexmk -lualatex en/main.tex
make pdf-ja           # latexmk -lualatex ja/main.tex
make pdf-zh           # latexmk -xelatex  zh/main.tex
make pdf-all
```

HTML (per language; LaTeXML primary, make4ht fallback):

```bash
make html-en
make html-all
```

Figures (regenerate from frozen data):

```bash
make figures          # PGF + dot one-shot
make figure FIG=F04_react_loop   # standalone preview of a single TikZ
```

## Quality gates (`make check-all`)

| Gate | Script | What it verifies |
|------|--------|------------------|
| 1    | `make pdf-all html-all`           | warning-free PDF + HTML × 3 |
| 3    | `check_notation.py`               | every body math symbol is defined in `shared/notation.tex` |
| 4    | `check_bib.py [--strict]`         | bib structural validity + (strict) Semantic Scholar cross-check |
| 6    | `check_i18n.py`                   | section / label / cite / equation set parity en/ja/zh |
| 7    | `check_glossary.py`               | `forbidden_alternatives` from `glossary.yaml` not used |
| 8    | `check_toc_consistency.py`        | PDF/HTML heading order + count match |
| 9    | `check_tikz.py`, `check_figures.py` | T1..T9 (raw coords, inline styles, arrow style, etc.) |
| 10   | `check_prompt_snapshots.py`       | `shared/appendix/prompts/**` bytes equal upstream `ari-core/ari/prompts/**` |

Gate 2 (`check_code_refs.py`) was retired with the file:line citation
ban (see `CLAUDE.md` §1); gate 5 (`% translated-from:` headers) was
retired together with the LLM translation pipeline.

Auxiliary:

* `check_logs_for_secrets.py` greps `references.log.yaml` and the cache for
  leaked API keys.

## Authoring across en/ja/zh

en is the master. ja and zh are hand-maintained alongside en in the same
PR: the structural-parity gate (gate 6) checks that the set of sections,
labels, citations, equations, figures, and tables is identical across the
three languages, but the prose is written and revised directly per
language. There is no translator script. See `CLAUDE.md` §3 for the
authoring rules.

## Appendix prompts (snapshot)

`shared/appendix/prompts/**` is a verbatim byte-for-byte snapshot of
`ari-core/ari/prompts/**/*.md` at the report's pinned commit. Refresh
with:

```bash
make snapshot-prompts          # regenerate snapshots; commit the diff
make check-prompt-snapshots    # gate 10 — fails if snapshots drift
```

Each snapshot file carries a `% snapshot-from: <path>@<sha256> @ commit
<git>` header. Prompts are reproduced in English in every language
version of the report (gate 6 / `check_i18n.py` excludes the appendix).
See `CLAUDE.md` §2 for the rationale.

## Bibliography discipline (anti-hallucination)

Every entry is added via `fetch_bib.py`, which verifies the proposed
title/author/year against Semantic Scholar (`S2_API_KEY` from `../.env`).
The two-stage defence is:

1. **Entry side**: `fetch_bib.py --verify-title "..."` rejects titles whose
   closest S2 match is below an edit-distance threshold of 0.10 — LLM
   hallucinations cannot enter the bib.
2. **PR side**: `check_bib.py --strict` re-validates every entry against S2
   before merge.

Citation keys follow `<firstauthorlastname><year><titlefirstword>` (regex
`^[a-z]{2,30}\d{4}[a-z0-9]{2,40}[a-z]?$`). While drafting, use
`\cite{TODO-...}` placeholders; gate C8 (`check_bib.py`) refuses to merge
PRs that still contain them.

## Figure discipline

* All figures are vector (TikZ or matplotlib PGF). PNG / JPG additions are
  blocked by CI (see `check_figures.py`).
* Every TikZ source uses the `positioning` library only — no raw `(x,y)`
  coordinates. The style file `style.tikzstyles` is the single source for
  visual parameters; inline `minimum width=` / `text width=` are
  forbidden (gate T2).
* LLM-generated TikZ must follow the rules in `shared/figures/CLAUDE.md`,
  notably the render-and-inspect loop (`make figure FIG=...`).

## Fonts

The report uses [Noto CJK fonts](https://github.com/notofonts/noto-cjk)
(SIL Open Font License 1.1) for Japanese and Simplified Chinese. Run
`./setup_fonts.sh` once per machine to install them.

## Frozen snapshot

This report is pinned to `ari-core` v0.7.x. Implementation citations
(`code_refs.yaml`) name file *and* line numbers; `check_code_refs.py`
enforces a ±3 line drift tolerance so light refactors are forgiven, but
significant moves trigger a regeneration.

Frozen evaluation data lives under `shared/figures/data/`, each accompanied
by a `*.meta.yaml` recording the source checkpoint and SHA-256 of the
payload. Updating these requires bumping `meta.yaml.source.checkpoint_id`
and including the diff in the PR description.

## Contributing

PRs touching this directory must follow the rules in
[../CONTRIBUTING.md](../CONTRIBUTING.md) and pass `make check-all` locally.
A complete review checklist is in `shared/figures/CLAUDE.md`
(figures-only) and the `Quality gates` table above (everything else).
