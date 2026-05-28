# report/Makefile — build PDFs/HTML for en/ja/zh, run quality gates.
# All targets are best-effort under the development environment;
# missing tools (biber, latexml, Noto CJK) are detected at run time.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

# ------------------------------------------------------------------ helpers
PYTHON   ?= python3
LATEXMK  ?= latexmk
LUALATEX ?= lualatex
XELATEX  ?= xelatex
LATEXML  ?= latexml
LATEXMLPOST ?= latexmlpost
BIBER    ?= biber

REPO_ROOT := $(abspath $(dir $(MAKEFILE_LIST))/..)
SCRIPTS   := scripts
FIGSCRIPTS:= shared/figures/scripts
SHARED    := shared

LANGS := en ja zh
PDF_TARGETS  := $(addsuffix /main.pdf,$(LANGS))
HTML_TARGETS := $(addprefix html/,$(LANGS))

VENV := scripts/.venv
PIP  := $(VENV)/bin/pip
PY   := $(VENV)/bin/python

# ------------------------------------------------------------------ phony
.PHONY: all pdf-all html-all check-all clean distclean \
        pdf-en pdf-ja pdf-zh \
        html-en html-ja html-zh \
        figures tables \
        check-i18n check-glossary check-bib check-bib-strict \
        check-tikz check-figures check-figures-render check-toc \
        check-prompt-snapshots snapshot-prompts \
        pull-pdfs venv

all: check-all pdf-all html-all

# ------------------------------------------------------------------ env
venv: $(VENV)/bin/activate

$(VENV)/bin/activate: $(SCRIPTS)/requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r $(SCRIPTS)/requirements.txt
	@touch $@

# ------------------------------------------------------------------ pdf
pdf-all: $(PDF_TARGETS)

pdf-en: en/main.pdf
pdf-ja: ja/main.pdf
pdf-zh: zh/main.pdf

en/main.pdf ja/main.pdf:
	cd $(@D) && $(LATEXMK) -lualatex -interaction=nonstopmode -file-line-error main.tex

zh/main.pdf:
	cd $(@D) && $(LATEXMK) -xelatex -interaction=nonstopmode -file-line-error main.tex

# ------------------------------------------------------------------ PaperBench audit reports (v0.7.2)
#
# Render a per-paper audit report from an ARI checkpoint.
# Usage:  make audit-report CHECKPOINT=/var/tmp/ari/.../20260511_... PAPER_ID=sc24-00019
# Optional: AUDIT_OUTPUT (default: audit/<PAPER_ID>), AUDIT_LANGS (default: en),
#           AUDIT_FORMATS (default: pdf)
AUDIT_OUTPUT  ?= audit/$(PAPER_ID)
AUDIT_LANGS   ?= en
AUDIT_FORMATS ?= pdf

audit-report:
	@test -n "$(CHECKPOINT)" || (echo "Usage: make audit-report CHECKPOINT=<ckpt> PAPER_ID=<id>" && exit 1)
	@test -n "$(PAPER_ID)"   || (echo "Usage: make audit-report CHECKPOINT=<ckpt> PAPER_ID=<id>" && exit 1)
	$(PYTHON) -m scripts.paperbench_report paper \
	    --checkpoint $(CHECKPOINT) --paper-id $(PAPER_ID) \
	    --output-root $(AUDIT_OUTPUT) \
	    --languages $(AUDIT_LANGS) --formats $(AUDIT_FORMATS)

# Summary across multiple checkpoints. Pass CHECKPOINTS as a space-separated list.
# Usage:  make audit-summary CHECKPOINTS="ckpt1 ckpt2" PAPER_IDS="p1 p2" RUN_ID=20260511
AUDIT_SUMMARY_OUTPUT ?= audit/_summary/$(RUN_ID)

audit-summary:
	@test -n "$(CHECKPOINTS)" || (echo "Usage: make audit-summary CHECKPOINTS='c1 c2' RUN_ID=<id>" && exit 1)
	@test -n "$(RUN_ID)"      || (echo "Usage: make audit-summary CHECKPOINTS='c1 c2' RUN_ID=<id>" && exit 1)
	$(PYTHON) -m scripts.paperbench_report summary \
	    $(foreach c,$(CHECKPOINTS),--checkpoint $(c)) \
	    $(foreach p,$(PAPER_IDS),--paper-id $(p)) \
	    --output-root $(AUDIT_SUMMARY_OUTPUT) \
	    --languages $(AUDIT_LANGS) --formats $(AUDIT_FORMATS)

# ------------------------------------------------------------------ html (LaTeXML primary, make4ht fallback per-chapter)
html-all: $(HTML_TARGETS)

html-en html-ja html-zh: html/%: %/main.tex venv
	mkdir -p html/$*
	bash $(SCRIPTS)/build_html.sh $* || (echo "[html] LaTeXML failed for $*; consider make4ht fallback per chapter" && exit 1)
	$(PY) $(SCRIPTS)/inject_langnav.py html/$*/index.html

# ------------------------------------------------------------------ figures
figures: venv
	$(PY) $(FIGSCRIPTS)/build_all.py

# expand FIG=<slug> to render a single TikZ to PNG for visual inspection
figure: venv
	@test -n "$(FIG)" || (echo "Usage: make figure FIG=F04_react_loop" && exit 1)
	$(PY) $(SCRIPTS)/render_tikz.py $(SHARED)/figures/tikz/$(FIG).tex

# ------------------------------------------------------------------ tables
tables: venv
	$(PY) $(SCRIPTS)/build_tables.py

# ------------------------------------------------------------------ checks
check-all: check-i18n check-glossary check-bib check-tikz check-figures check-toc check-prompt-snapshots

check-i18n: venv
	$(PY) $(SCRIPTS)/check_i18n.py

check-glossary: venv
	$(PY) $(SCRIPTS)/check_glossary.py

check-bib: venv
	$(PY) $(SCRIPTS)/check_bib.py

check-bib-strict: venv
	$(PY) $(SCRIPTS)/check_bib.py --strict

check-tikz: venv
	$(PY) $(SCRIPTS)/check_tikz.py

check-figures: venv
	$(PY) $(SCRIPTS)/check_figures.py

check-figures-render: venv
	$(PY) $(SCRIPTS)/check_figures.py --render-all

check-toc: venv
	$(PY) $(SCRIPTS)/check_toc_consistency.py

check-prompt-snapshots: venv
	$(PY) $(SCRIPTS)/check_prompt_snapshots.py --root $(REPO_ROOT)

# ------------------------------------------------------------------ snapshot prompts
# Refresh shared/appendix/prompts/ from ari-core/ari/prompts/**/*.md.
# Each output file carries a `% snapshot-from: ...@<sha256> @ commit <git>` header.
snapshot-prompts: venv
	$(PY) $(SCRIPTS)/snapshot_prompts.py --root $(REPO_ROOT)

# ------------------------------------------------------------------ pdfs of references
pull-pdfs: venv
	$(PY) $(SCRIPTS)/pull_pdfs.py

# ------------------------------------------------------------------ clean
clean:
	-find . -name '*.aux' -o -name '*.log' -o -name '*.toc' -o -name '*.out' -o -name '*.fdb_latexmk' -o -name '*.fls' -o -name '*.synctex.gz' | xargs rm -f

distclean: clean
	rm -rf $(VENV) html/en html/ja html/zh
	-find . -name '*.bbl' -o -name '*.bcf' -o -name '*.run.xml' -o -name '*.blg' | xargs rm -f
