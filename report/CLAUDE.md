# LLM rules for authoring the ARI system report

This file is the contract for any LLM (Claude included) editing files under
`report/`. **Read this before drafting, translating, or restructuring any
chapter, appendix, or build script.** The figure-specific contract lives at
`shared/figures/CLAUDE.md` — read it too before touching `shared/figures/`.
Build commands, gate list, and directory layout are in `README.md`; this
file documents the *policy* an author must follow, not the build system.

## 0. Target: arXiv-submittable technical report

Every edit must move the report closer to a quality level that could be
submitted to arXiv as a stand-alone technical report. Concretely this means:

- **Self-contained.** A first-time reader with access only to the PDF (and
  the references it cites) can fully understand every claim. No prior
  knowledge of the ARI codebase, the ARI development team, ARI's internal
  documents, or ARI's release process is assumed.
- **Every acronym and named concept is expanded on first use.** Examples:
  "Model Context Protocol (MCP)", "Reason-and-Act (ReAct) agent",
  "Generic Resource Scheduling (GRES) flags". Do not assume the reader
  knows even widely-used acronyms in the field.
- **No internal codenames in the body.** Specifically forbidden in body
  text: drafting-round labels ("R3a", "R4"), audit ticket numbers
  ("audit B-3", "audit B-10"), internal review ID references, sprint
  names, Slack channel names. These belong in commit messages or PR
  descriptions, not in the report itself. If a v0.7.2 design decision
  was driven by an audit, state the design decision and its rationale —
  do not cite the audit ticket.
- **No build/authoring machinery in the body.** A reader cannot run the
  repo, so the body never names the report's own tooling or process:
  gate scripts (`check_notation.py`), build targets (`make figures`),
  repo files or config files (`shared/notation.tex`, `default.yaml`,
  `*.meta.yaml`), pointers to repo docs (`docs/configuration.md`), or
  LaTeX internals (`\ensuremath`). And never address the *author* in the
  body — instructions like "add the macro to this file first, then
  reference it" are CLAUDE.md / CONTRIBUTING material, not report prose.
  Appendix intros are body text and obey this too: say what the appendix
  *is* to a reader, not how a contributor maintains it.
- **Forward references are weak.** When concept X is used before its
  formal definition, a `\cref{sec:def-of-X}` alone is not enough.
  Add a one-clause inline gloss so the reader can keep reading without
  flipping forward. (Example: not "the P2 determinism principle
  (\cref{...})", but "the *determinism* design principle (we call it
  P2; \cref{...} lays out all five in full)".)
- **Math and pseudocode are consistent.** Every symbol used in the body
  is registered in `shared/notation.tex` (gate 3). Every pseudocode
  comment names a function in a way that is also used in surrounding
  prose — readers should not have to context-switch between names that
  refer to the same thing.
- **Prose is publishable.** No fragments, no run-on bullet trees where a
  paragraph would read better, no "(see X)" cross-references that go
  nowhere meaningful. The bar is "I would not be embarrassed if a
  reviewer at NeurIPS / ICML / SC opened this file."
- **No leftover scaffolding.** Specifically: no TODO / FIXME / XXX in the
  body, no commented-out paragraphs left over from drafting, no
  placeholder citations (`\cite{TODO-...}`) at PR-merge time.

When an edit can't meet this bar (because the underlying work isn't
finished — e.g., the evaluation hasn't run yet), say so *in the
report* with a sentence like "this chapter is intentionally deferred
until a frozen checkpoint exists" (as `05_evaluation.tex` does today).
Saying so explicitly is preferable to writing speculative prose that
will need to be retracted later.

## 1. Audience and abstraction layer

The report is an **arXiv-style technical report**. Assume the reader has
the PDF only — not access to the `ari-core` source tree. Therefore:

- **Body text speaks the abstract layer**: algorithm names, math symbols,
  pseudocode, diagrams. Implementation details — modules, classes, file
  paths, line numbers — do not appear in the body.
- **No `path/to/file.py:123` style citations in body text.** If naming a
  subsystem is unavoidable (e.g. "the BFTS orchestrator"), name it once at
  the module level (`ari.orchestrator.bfts`) and move on; do not chain
  file:line references.
- **Pseudocode is preferred to source listings.** Use `algorithm2e` for
  algorithms; do not paste Python.
- The legacy `shared/code_refs.yaml` and gate 2 (`check_code_refs.py`)
  were **retired** in 2026-05 together with the body-text cleanup that
  removed all file:line citations. Do not reintroduce either, and do not
  cite the report itself as a place that holds such mappings.

## 2. Prompts go in the Appendix verbatim

Every LLM prompt the system uses at runtime appears **in full** in
`shared/appendix/prompts/`, not as a reference to `ari-core/ari/prompts/...`.

- Prompt files are snapshotted from `ari-core/ari/prompts/**/*.md` by
  `scripts/snapshot_prompts.py`. Each snapshot carries a header
  `% snapshot-from: <relative path>@<sha256> @ commit <git sha>`.
- Body LaTeX includes prompts via the
  `\PromptListing{file}{caption}{label}` macro (defined in
  `shared/preamble.tex`), which wraps **fvextra**'s `\VerbatimInput`
  with `breaklines`/`breakanywhere` so long lines wrap instead of running
  off the page. We do **not** use `minted` (it needs shell-escape).
  Never paraphrase, reformat, or "clean up" prompt text — the bytes that
  reach the LLM are what reproducibility requires.
- `check_prompt_snapshots.py` (gate 10) verifies snapshot bytes equal the
  source. Out-of-sync snapshots fail CI; resolve by re-running the snapshot
  script, not by hand-editing either side.
- **Prompts are not translated.** `check_i18n.py` excludes
  `shared/appendix/prompts/**`. The ja/zh PDFs include English prompt bytes
  verbatim; a 1–2 sentence ja/zh gloss above each block is permitted but
  optional.

## 3. Authoring across en/ja/zh (no translator)

There is no translator script. en, ja, and zh chapters are
hand-maintained alongside each other in the same PR.

- **en is the master.** Edit `en/` first; then mirror the edit by hand
  into `ja/` and `zh/` in the same PR.
- **Maintain structural parity.** Gate 6 (`check_i18n.py`) enforces that
  the multiset of `\section/\subsection`, `\label`, `\cite`, equations,
  figures, and tables is identical across all three languages. If you
  add or remove any of these in one language, do the same in the other
  two — same keys, same order.
- **Prompts (§2) are not translated.** `shared/appendix/prompts/**` is
  English-only; each language's `chapters/appendix_prompts.tex` consists
  of a short language-specific intro plus identical `\PromptListing{}`
  invocations.
- **Glossary edits** (`shared/glossary.yaml`) require updating
  `forbidden_alternatives` and any affected ja/zh prose in the same PR;
  gate 7 (`check_glossary.py`) enforces the term ban.
- **Length-ratio sanity** (`check_i18n.py`): ja must be 0.45..1.4× of en
  character count (after stripping markup), zh 0.30..0.9×. Drift outside
  these bands usually indicates an untranslated paragraph or a
  duplicated one — fix the prose, do not widen the band.

## 4. Snapshot discipline

- Frozen evaluation data under `shared/figures/data/` is paired with a
  `*.meta.yaml` recording `source.checkpoint_id` and the payload SHA-256.
  Bumping data requires bumping `checkpoint_id` and noting it in the PR.
- Prompt snapshots (§2) record the upstream commit SHA at snapshot time.
- If `ari-core` evolves so a chapter's claim no longer holds, update the
  chapter and refresh the relevant snapshot in the same PR — never let the
  report drift silently.
- **Verify version-specific counts and claims against the data the chapter
  actually reports, not the current tree.** Before "correcting" a number,
  confirm it against the frozen evaluation data and the run that produced it
  (recorded via `source.checkpoint_id`); a value that looks wrong against
  `HEAD` may be correct for the run the chapter reports. Do not silently
  "fix" a figure or count to match `HEAD` — the snapshot a claim cites is
  the ground truth for that claim.

## 5. Bibliography

Full rules in `README.md` §"Bibliography discipline". For LLM editors:

- **Never invent bib entries.** Use `fetch_bib.py --verify-title "..."`;
  the S2 edit-distance gate (0.10) is the hallucination firewall.
- Cite-key regex: `^[a-z]{2,30}\d{4}[a-z0-9]{2,40}[a-z]?$`. While drafting,
  `\cite{TODO-...}` placeholders are allowed; gate 4 refuses them at merge.
- Figure citations use the same keys as body `\cite{...}`.

## 6. Figures

Full rules in `shared/figures/CLAUDE.md`. Reminders for whole-report edits:

- Vector only (TikZ / matplotlib PGF). PNG/JPG additions fail CI.
- All TikZ string literals go through `\figlabel{key}`; matching
  `\figlabeldef{key}{...}` in every `*/strings.tex`.
- **Always render a preview before committing.** For a single TikZ edit run
  `make figure FIG=<slug>` and Read the resulting PNG yourself, inspecting
  for overlap, overflow, clipping, and broken labels. The `make figure`
  target runs `render_tikz.py` which extracts `Overfull \hbox` and
  bounding-box overlaps from the log — but you must still *look* at the
  PNG, automatic checks miss visual regressions like a node text now wider
  than its box because of a re-tokenised label.
- **Periodic full regeneration.** Whenever any of (a) `shared/figures/data/`,
  (b) `shared/figures/style.tikzstyles`, (c) preamble TikZ libraries, or
  (d) any `*/strings.tex` `\figlabeldef` block changes, run `make figures`
  to regenerate the entire figure set and Read each resulting preview to
  confirm nothing else broke. Do not assume "I only edited one file" is
  safe — the style file and string macros are shared. Treat figure
  regeneration the same way you would treat re-running tests after a
  refactor.
- If a figure preview shows breakage you did not intend, do not paper over
  it with hand-tuned coordinates (forbidden by gate T2); fix the upstream
  cause (label text, style file, node distance in `positioning`).

## 7. Required local check

Before opening any PR touching `report/`:

```bash
make check-all
```

Never bypass a gate with `--no-verify` or by silencing a check script. If
a gate is wrong, fix the gate in the same PR with a justification in the
description — do not skip it.

### 7.1 Zero LaTeX warnings (hard rule)

A PDF build must end with **zero** LaTeX warnings — not a single one.
This is non-negotiable. Specifically the build must not produce:

- `Overfull \hbox` (text running into the margin) — **forbidden**, even
  by a single point. Fix by rewording the offending paragraph, wrapping a
  long identifier in `\code{...}` (it `\seqsplit`s char-by-char), adding
  `\allowbreak` in long math, or restructuring the bullet/table that
  overflows. Do **not** reach for global `\sloppy` (see §7.2).
- `Underfull \hbox` / `Underfull \vbox` — these are **suppressed** by
  `\hbadness=10000` / `\vbadness=10000` in the preamble, because the
  TikZ figures (wide node text) otherwise flood the log with them, and
  they flag whitespace rivers, not margin overflow. Do not remove that
  suppression; it does not hide Overfull (real margin overflow), which
  stays reported.
- `Overfull \vbox` — usually a too-tall figure or float; reshape the
  figure or place it as `\begin{figure*}` so it spans both columns.
- `Reference ... undefined`, `Citation ... undefined` — every cross-ref
  and cite must resolve. (`\cite{TODO-...}` placeholders are allowed
  *only* mid-draft; gate 4 refuses them at merge time.)
- `Label ... multiply defined` — duplicates indicate copy-paste; fix the
  duplicate.
- `Font shape ... not available` / `Font ... undefined` — usually a
  CJK-fallback regression; either fix the preamble or add the missing
  font, do not let it warn.
- `pdfTeX warning: destination with the same identifier` — fix the
  duplicate, do not let it warn.

The author MUST inspect the lualatex / xelatex log after every build and
treat any warning as a build failure. "It still produces a PDF" is not
acceptable — overfull boxes and unresolved references make the report
look unprofessional and are exactly the kind of thing an arXiv reviewer
flags first (see §0). Build with the local bibtex backend (biber is not
installed here) and grep, excluding the `silence` package's own counter
macros (`\sl@WarningCount` etc., which are not warnings):

```bash
make pdf-all      # or, locally without biber, per language:
#   lualatex '\def\AriBibBackend{bibtex}\input{main}' ; bibtex main ; lualatex ... ; lualatex ...
grep -nE 'Overfull' */main.log
grep -E 'Warning' */main.log | grep -vE 'WarningCount|WarningNumber|WarningCasualties|BankOfWarnings|GenericWarning|^Package: '
```

Both greps must come back empty before opening the PR (Overfull = 0,
real Warnings = 0). If a third-party package prints a benign warning
that genuinely cannot be silenced, add a `\WarningFilter` for it in the
preamble's `silence` block (loaded first, so it covers load-time
warnings like luatexja's microtype patch) and note why — do not let it
slip in silently.

### 7.2 A clean log is necessary but NOT sufficient — eyeball the PDF

Some overflow does **not** raise an `Overfull \hbox` warning. The most
important case for this report: verbatim prompt listings
(\cref{sec:prompts}). The break options that wrap long lines
(`breaklines`, `breakanywhere`) come from **`fvextra`**, not base
`fancyvrb`; if only `fancyvrb` is loaded those keys are silently
ignored and 500-character prompt lines run clean off the page **with
no warning at all**. Keep `\usepackage{fvextra}` in the preamble.

Likewise, do not "fix" overfulls by turning on `\sloppy` globally with a
large `\emergencystretch`: that suppresses the warning while still
letting text protrude. We keep `\fussy` (the default) and a small
`\emergencystretch` (1em) precisely so real overflow keeps reporting.

Therefore, after a zero-warning build, render and **look at** the
pages — at minimum the appendix prompt pages and any page with a wide
table, long inline `\code{}`/`\texttt{}` token, or a figure:

```bash
pdftoppm -png -r 100 -f <first> -l <last> en/main.pdf /tmp/pg
# then open /tmp/pg-*.png and confirm nothing crosses the text block edge
```

The appendix runs single column (`\clearpage\onecolumn` before
`\appendix`, `\clearpage\twocolumn` before `\printbibliography`) so the
listings wrap at full page width. The `\clearpage` around `\onecolumn`
is required: a bare `\onecolumn` after `\appendix` is silently ignored
under xelatex/ctex (the zh build), leaving the appendix two-column and
the listings overflowing.

## 8. What NOT to do

- Do not introduce file:line or repo-path references into body text (see §1).
- Do not reference a prompt by path; include its bytes (see §2).
- Do not hand-edit `shared/references.cache.json`.
- Do not reintroduce a translator script. ja/zh are hand-maintained
  (see §3); reintroducing a paragraph-cache translator was tried and
  removed in 2026-05.
- Do not commit `shared/references_pdf/`, `html/`, or build artifacts.
- Do not add a new top-level directory under `report/` without updating
  this file and `README.md` in the same PR.
- Do not silently delete or rename a chapter — the i18n gates will fail in
  the other languages and the failure is hard to localize after the fact.
