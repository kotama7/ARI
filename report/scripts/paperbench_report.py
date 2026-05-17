"""PaperBench audit report generator (v0.7.2 / Report_plan).

Renders a per-paper detail report (LaTeX + figures) plus, when given
multiple checkpoints, a multi-paper summary report. Trilingual output
(en/ja/zh) is supported by translating the English canonical via the
existing ``translate.py`` pipeline (`report/scripts/translate.py`) —
this script writes only the English source; the lang-sync step runs
separately so the translation cost is opt-in.

Usage (Python):

    from report.scripts.paperbench_report import (
        generate_paper_report, generate_summary_report,
    )
    res = generate_paper_report(
        checkpoint_dir=Path("/var/tmp/ari/sc24/checkpoints/20260511_..."),
        paper_id="sc24-00019",
        output_root=Path("report/audit/sc24-00019"),
        languages=["en"],          # ja/zh added by lang-sync pass
        formats=["pdf"],
    )

Usage (CLI):

    python -m report.scripts.paperbench_report \\
        --checkpoint /var/tmp/ari/.../20260511_... \\
        --paper-id sc24-00019 \\
        --output-root report/audit/sc24-00019

Build is delegated to ``latexmk`` (the existing ``report/Makefile``
already configures XeLaTeX + biber). The script only emits .tex sources
plus figures; ``make`` turns them into PDF/HTML/MD.

Architecture: zero deps beyond stdlib + matplotlib. graphviz is used
when available; the rubric tree figure falls back to a plain text-listing
when ``dot`` is absent.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO_ROOT / "report"
GLOSSARY_PATH = REPORT_ROOT / "shared" / "i18n.json"


# ── Inlined LaTeX templates ─────────────────────────────────────────────
#
# The PaperBench audit report templates were previously stored under
# ``report/audit/.template/`` so the rendered output and its sources
# sat side by side. That arrangement leaked machine-driven helper
# files into ``report/``, which is otherwise reserved for the
# hand-written ARI research paper (see report/{en,ja,zh}/main.tex).
#
# We inline the six chapter templates plus the main.tex skeleton here
# as Python string constants. The ``render_template`` helper accepts
# either a file path or a string body, so the rest of the rendering
# pipeline is unchanged. Placeholders use the same ``{{ name }}``
# syntax as before.
_TMPL_MAIN = r"""% PaperBench audit report — per-paper detail
% Rendered from an inline template by paperbench_report.py.
% Placeholders use ``{{ ... }}`` syntax; all values are escaped LaTeX-safe.
\documentclass[a4paper,11pt]{article}

\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[english]{babel}
\usepackage{geometry}
\geometry{margin=2.2cm}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{hyperref}
\usepackage{fancyhdr}
\usepackage{enumitem}

\hypersetup{
  colorlinks=true,
  linkcolor=blue!50!black,
  urlcolor=blue!60!black,
}

\title{PaperBench Audit Report \\ \large {{ paper_title }}}
\author{ARI v{{ ari_version }} -- generated {{ generated_at }}}
\date{}

\begin{document}
\maketitle

\begin{abstract}
This report summarizes the PaperBench audit run for paper
``{{ paper_title }}'' ({{ paper_id }}). Coverage: rubric construction,
reproduction attempt, per-leaf grading, and reviewer-facing
recommendations.
\end{abstract}

\tableofcontents
\clearpage

\input{chapters/01_paper_metadata.tex}
\input{chapters/02_rubric.tex}
\input{chapters/03_reproduction.tex}
\input{chapters/04_grading.tex}
\input{chapters/05_blocking_issues.tex}
\input{chapters/06_recommendations.tex}

\end{document}
"""

_TMPL_01 = r"""\section{Paper Metadata}

\begin{tabular}{ll}
\toprule
\textbf{Field} & \textbf{Value} \\
\midrule
Paper ID    & \texttt{ {{ paper_id }} } \\
Title       & {{ paper_title }} \\
Authors     & {{ paper_authors }} \\
Venue       & {{ paper_venue }} \\
Year        & {{ paper_year }} \\
License     & {{ paper_license }} \\
Source      & \texttt{ {{ paper_source_type }} : {{ paper_source }} } \\
Artifact    & \url{ {{ paper_artifact_url }} } \\
\bottomrule
\end{tabular}

\medskip
\noindent
\textit{License usability:} {{ license_note }}
"""

_TMPL_02 = r"""\section{Rubric}

The PaperBench rubric is a hierarchical TaskNode tree
(\texttt{ari-skill-replicate/schemas/replication\_rubric.schema.json},
version~3). For this audit:

\begin{itemize}[leftmargin=*]
  \item Total leaves:  \textbf{ {{ rubric_leaves_count }} }
  \item Tree depth:    \textbf{ {{ rubric_depth }} }
  \item Generator:     \texttt{ {{ rubric_generator_model }} }
  \item Two-stage:     {{ rubric_two_stage }}
  \item Auditor flags: {{ rubric_audit_flags_count }}
\end{itemize}

\subsection{Category Breakdown}

\begin{tabular}{lr}
\toprule
\textbf{Category} & \textbf{Leaf count} \\
\midrule
{{ rubric_category_rows }}
\bottomrule
\end{tabular}

\subsection{Execution Profile}

{{ execution_profile_block }}

\subsection{Rubric Tree (preview)}

{{ rubric_tree_figure_block }}
"""

_TMPL_03 = r"""\section{Reproduction Attempt}

\subsection{Sandbox}

\begin{tabular}{ll}
\toprule
Sandbox kind        & \texttt{ {{ repro_sandbox_kind }} } \\
Partition           & \texttt{ {{ repro_partition }} } \\
Wallclock           & {{ repro_wallclock }} \\
Exit code           & {{ repro_exit_code }} \\
Elapsed (sec)       & {{ repro_elapsed_sec }} \\
Multi-node          & {{ repro_multinode_block }} \\
Exclusive           & {{ repro_exclusive }} \\
GPU spec            & {{ repro_gpu_spec }} \\
\bottomrule
\end{tabular}

\subsection{Submission Summary}

Files emitted under \texttt{repro\_sandbox/}:

\begin{itemize}[leftmargin=*]
{{ submission_file_list }}
\end{itemize}

\subsection{Reproduce log (tail)}

\begin{quote}\small
\begin{verbatim}
{{ reproduce_log_tail }}
\end{verbatim}
\end{quote}

\subsection{Missing Expected Artifacts}

{{ missing_artifacts_block }}
"""

_TMPL_04 = r"""\section{Grading}

PaperBench SimpleJudge graded each leaf 0/1 against the rubric. Aggregate
weighted score (ORS):

\begin{center}
\fbox{\Huge \textbf{ {{ ors_score_percent }}\% }}
\end{center}

\subsection{Per-category Pass Rate}

\begin{tabular}{lrrr}
\toprule
\textbf{Category} & \textbf{Pass} & \textbf{Total} & \textbf{Rate} \\
\midrule
{{ category_pass_rows }}
\bottomrule
\end{tabular}

\subsection{Score Distribution}

{{ score_distribution_figure_block }}

\subsection{Per-leaf Pass/Fail Heatmap}

{{ leaf_score_heatmap_figure_block }}

\subsection{Top Failed Leaves}

The 10 highest-weight leaves the submission did NOT satisfy:

\begin{enumerate}[leftmargin=*]
{{ failed_leaves_list }}
\end{enumerate}

\subsection{Negative Control}

{{ negative_control_block }}
"""

_TMPL_05 = r"""\section{Blocking Issues}

Issues the BasicAgent / IterativeAgent rollout flagged but could not work
around within its time budget:

{{ blocking_issues_block }}
"""

_TMPL_06 = r"""\section{Reviewer Recommendations}

Derived heuristically from the grading + blocking-issue signals:

\begin{itemize}[leftmargin=*]
{{ recommendations_list }}
\end{itemize}

\medskip
\noindent
\textit{Generated by} \texttt{report/scripts/paperbench\_report.py} (ARI v{{ ari_version }}).
This report is advisory — final assessment requires human review of the
attached primary artefacts (\texttt{rubric.json}, \texttt{grade.json},
\texttt{submission/}, \texttt{reproduce.log}).
"""

# Filename → template body. Keys match the names the rendered output
# uses for ``\input{chapters/…}`` so the wiring is mechanical.
_CHAPTER_TEMPLATES: dict[str, str] = {
    "01_paper_metadata.tex": _TMPL_01,
    "02_rubric.tex":         _TMPL_02,
    "03_reproduction.tex":   _TMPL_03,
    "04_grading.tex":        _TMPL_04,
    "05_blocking_issues.tex": _TMPL_05,
    "06_recommendations.tex": _TMPL_06,
}


# Cache the trilingual glossary at module load — read-only data.
_GLOSSARY_CACHE: dict | None = None


def _load_glossary() -> dict:
    """Load ``report/shared/i18n.json`` once; return ``{}`` on any error."""
    global _GLOSSARY_CACHE
    if _GLOSSARY_CACHE is None:
        try:
            _GLOSSARY_CACHE = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("glossary load failed: %s; falling back to empty", e)
            _GLOSSARY_CACHE = {}
    return _GLOSSARY_CACHE


def _apply_glossary(text: str, language: str) -> str:
    """Swap canonical English fixed strings for their ``language`` mirror.

    The glossary (``report/shared/i18n.json``) carries 3-language entries
    like ``{"audit_report": {"en": "PaperBench Audit Report", "ja":
    "PaperBench 監査レポート", "zh": "PaperBench 审计报告"}}``. For
    ``language="en"`` we return ``text`` unchanged; otherwise we walk
    every ``en`` value across all glossary categories and substitute it
    with the corresponding ``language`` value.

    Substitution is string-level (not LaTeX-aware): we sort entries by
    descending length to avoid prefix-shadowing (e.g. "Code Execution"
    must replace before "Code"). Whitespace is preserved verbatim.
    """
    if language == "en":
        return text
    gl = _load_glossary()
    if not gl:
        return text
    pairs: list[tuple[str, str]] = []
    for category in gl.values():
        if not isinstance(category, dict):
            continue
        for entry in category.values():
            if not isinstance(entry, dict):
                continue
            en = entry.get("en")
            tgt = entry.get(language)
            if isinstance(en, str) and isinstance(tgt, str) and en and tgt and en != tgt:
                pairs.append((en, tgt))
    # Longer matches first to avoid prefix shadowing
    pairs.sort(key=lambda p: -len(p[0]))
    out = text
    for en, tgt in pairs:
        out = out.replace(en, tgt)
    return out


_LANG_PREAMBLES = {
    # XeLaTeX + xeCJK + HaranoAji (Japanese-AJ1 / CJK Han coverage)
    "ja": (
        "\\usepackage{xeCJK}\n"
        "\\setCJKmainfont{HaranoAjiMincho-Regular.otf}["
        "BoldFont=HaranoAjiMincho-Bold.otf,"
        "ItalicFont=HaranoAjiMincho-Regular.otf]\n"
        "\\setCJKsansfont{HaranoAjiGothic-Regular.otf}["
        "BoldFont=HaranoAjiGothic-Bold.otf]\n"
    ),
    # XeLaTeX + xeCJK + Fandol (Chinese-GB1 coverage)
    "zh": (
        "\\usepackage{xeCJK}\n"
        "\\setCJKmainfont{FandolSong-Regular.otf}["
        "BoldFont=FandolSong-Bold.otf,"
        "ItalicFont=FandolKai-Regular.otf]\n"
        "\\setCJKsansfont{FandolHei-Regular.otf}["
        "BoldFont=FandolHei-Bold.otf]\n"
    ),
}


def _inject_lang_preamble(main_tex: str, language: str) -> str:
    """Inject the per-language ``xeCJK`` preamble right before
    ``\\begin{document}``. No-op for English."""
    preamble = _LANG_PREAMBLES.get(language)
    if not preamble:
        return main_tex
    return main_tex.replace(
        "\\begin{document}",
        preamble + "\n\\begin{document}",
        1,
    )


# ── LaTeX-safe escaping ─────────────────────────────────────────────────


_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
    "<":  r"\textless{}",
    ">":  r"\textgreater{}",
}


def tex_escape(s: Any) -> str:
    """Escape LaTeX special characters in arbitrary string-coercible input.

    Returns the empty string for ``None`` / empty so templates render as
    "—" via the caller's default.
    """
    if s is None:
        return ""
    text = str(s)
    out: list[str] = []
    for ch in text:
        out.append(_LATEX_SPECIAL.get(ch, ch))
    return "".join(out)


def render_template(template: Path | str, values: dict[str, Any]) -> str:
    """Trivial ``{{ KEY }}`` placeholder substitution.

    Accepts either a ``Path`` (legacy file-based template, read at call
    time) or a raw template body string (preferred — the audit
    templates are inlined into ``_CHAPTER_TEMPLATES`` / ``_TMPL_MAIN``
    so the rendering pipeline stays self-contained).

    Values are inserted verbatim (the caller is responsible for LaTeX
    escaping via ``tex_escape`` on free-form fields). Unknown placeholders
    are replaced with an empty string + a logged warning so the build
    does not fail because of a typo'd template variable.
    """
    if isinstance(template, Path):
        label = template.name
        text = template.read_text(encoding="utf-8")
    else:
        # First non-empty line acts as the diagnostic label when warnings fire.
        first = next((ln for ln in template.splitlines() if ln.strip()), "<inline>")
        label = first.strip()[:40]
        text = template
    seen: set[str] = set()
    pat = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        seen.add(key)
        if key in values:
            return str(values[key])
        log.warning("template %s missing value for %s", label, key)
        return ""
    rendered = pat.sub(_sub, text)
    # Warn on values that were never referenced (drift detection).
    unused = set(values) - seen
    if unused:
        log.debug("template %s did not consume: %s", label, sorted(unused))
    return rendered


# ── Data harvest ────────────────────────────────────────────────────────


@dataclass
class CheckpointHarvest:
    """Aggregated audit data for a single paper checkpoint.

    All fields default to safe empty values so the renderer never KeyErrors
    on a malformed / incomplete checkpoint.
    """
    paper_id: str
    paper_title: str = ""
    paper_authors: list[str] = field(default_factory=list)
    paper_venue: str = ""
    paper_year: int | None = None
    paper_license: str = ""
    paper_source_type: str = ""
    paper_source: str = ""
    paper_artifact_url: str = ""
    license_note: str = ""

    rubric_envelope: dict = field(default_factory=dict)
    rubric_leaves_count: int = 0
    rubric_depth: int = 0
    rubric_generator_model: str = ""
    rubric_two_stage: bool = False
    rubric_audit_flags_count: int = 0
    rubric_category_breakdown: dict[str, int] = field(default_factory=dict)
    execution_profile: dict = field(default_factory=dict)

    repro_sandbox_kind: str = ""
    repro_partition: str = ""
    repro_wallclock: str = ""
    repro_exit_code: int | None = None
    repro_elapsed_sec: float = 0.0
    repro_nodes: int = 0
    repro_ntasks: int = 0
    repro_exclusive: bool = False
    repro_gpu_spec: str = ""
    submission_files: list[str] = field(default_factory=list)
    reproduce_log_tail: str = ""
    missing_artifacts: list[str] = field(default_factory=list)

    ors_score: float = 0.0
    leaves_passed: int = 0
    leaves_total: int = 0
    category_pass: dict[str, tuple[int, int]] = field(default_factory=dict)
    top_failed_leaves: list[dict] = field(default_factory=list)
    grade_leaves: list[dict] = field(default_factory=list)
    negative_control: dict = field(default_factory=dict)

    blocking_issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _walk_rubric(node: dict, depth: int = 0) -> tuple[int, int, dict[str, int]]:
    """Return ``(leaf_count, max_depth, category_breakdown)`` for a TaskNode tree."""
    cats: Counter = Counter()
    leaves = 0
    deepest = depth
    if not isinstance(node, dict):
        return 0, depth, dict(cats)
    children = node.get("sub_tasks") or []
    if not children:
        leaves = 1
        cat = node.get("task_category") or "Uncategorized"
        cats[cat] += 1
        return leaves, depth, dict(cats)
    for c in children:
        l, d, cc = _walk_rubric(c, depth + 1)
        leaves += l
        deepest = max(deepest, d)
        for k, v in cc.items():
            cats[k] = cats.get(k, 0) + v
    return leaves, deepest, dict(cats)


def _read_log_tail(p: Path, max_lines: int = 60) -> str:
    if not p.is_file():
        return "(reproduce.log not found)"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(reproduce.log unreadable)"
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def harvest_checkpoint(checkpoint_dir: Path, paper_id: str) -> CheckpointHarvest:
    """Extract every report-relevant field from an ARI checkpoint.

    Looks for (all optional — missing fields just stay at defaults):
        rubric.json (PaperBench TaskNode envelope, v3)
        grade.json  (SimpleJudge result; aggregate + per-leaf)
        repro_sandbox/                (submission directory)
        repro_sandbox/reproduce.log   (Phase 1 log)
        repro_result.json             (run_reproduce output snapshot)
        paper_metadata.json           (registry-style metadata snapshot)
        blocking_issues.log           (one issue per line; optional)
    """
    h = CheckpointHarvest(paper_id=paper_id)

    # ── Metadata snapshot (optional) ──
    meta_path = checkpoint_dir / "paper_metadata.json"
    if meta_path.is_file():
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            h.paper_title = m.get("title", "")
            h.paper_authors = list(m.get("authors") or [])
            h.paper_venue = m.get("venue", "")
            h.paper_year = m.get("year")
            h.paper_license = m.get("license", "")
            h.paper_source_type = m.get("source_type", "")
            h.paper_source = m.get("source", "")
            h.paper_artifact_url = m.get("artifact_url", "")
            la = m.get("license_assessment") or {}
            h.license_note = la.get("note", "")
        except json.JSONDecodeError as e:
            log.warning("paper_metadata.json malformed: %s", e)

    # ── Rubric (PaperBench envelope) ──
    rubric_path = checkpoint_dir / "rubric.json"
    if rubric_path.is_file():
        try:
            env = json.loads(rubric_path.read_text(encoding="utf-8"))
            h.rubric_envelope = env
            gen = env.get("generator") or {}
            h.rubric_generator_model = gen.get("model", "")
            audit = env.get("audit") or {}
            h.rubric_audit_flags_count = int(audit.get("flags_count") or 0)
            rc = env.get("reproduce_contract") or {}
            h.execution_profile = dict(rc.get("execution_profile") or {})
            leaves, depth, cats = _walk_rubric(env.get("rubric") or {})
            h.rubric_leaves_count = leaves
            h.rubric_depth = depth
            h.rubric_category_breakdown = cats
        except json.JSONDecodeError as e:
            log.warning("rubric.json malformed: %s", e)

    # ── Reproduction artefacts ──
    repro = checkpoint_dir / "repro_sandbox"
    if repro.is_dir():
        h.submission_files = [
            str(p.relative_to(repro)) for p in sorted(repro.rglob("*")) if p.is_file()
        ][:200]
        h.reproduce_log_tail = _read_log_tail(repro / "reproduce.log")
    res_path = checkpoint_dir / "repro_result.json"
    if res_path.is_file():
        try:
            r = json.loads(res_path.read_text(encoding="utf-8"))
            h.repro_sandbox_kind = r.get("sandbox_kind", "")
            h.repro_partition = r.get("partition", "")
            h.repro_wallclock = r.get("walltime", "")
            h.repro_exit_code = r.get("exit_code")
            h.repro_elapsed_sec = float(r.get("elapsed_sec") or 0.0)
            h.repro_nodes = int(r.get("nodes") or 0)
            h.repro_ntasks = int(r.get("ntasks") or 0)
            h.repro_exclusive = bool(r.get("exclusive"))
            gpu = r.get("gpu") or {}
            if gpu:
                pieces = []
                if gpu.get("type"):
                    pieces.append(gpu["type"])
                if gpu.get("per_task"):
                    pieces.append(f"{gpu['per_task']}/task")
                if gpu.get("per_node"):
                    pieces.append(f"{gpu['per_node']}/node")
                h.repro_gpu_spec = " ".join(pieces)
            h.missing_artifacts = list(r.get("missing") or [])
        except json.JSONDecodeError as e:
            log.warning("repro_result.json malformed: %s", e)

    # ── Grade ──
    grade_path = checkpoint_dir / "grade.json"
    if grade_path.is_file():
        try:
            g = json.loads(grade_path.read_text(encoding="utf-8"))
            h.ors_score = float(g.get("ors_score") or 0.0)
            leaves = g.get("leaves") or []
            h.leaves_total = len(leaves)
            h.leaves_passed = sum(1 for l in leaves if l.get("passed"))
            # Raw per-leaf list survives for the heatmap figure (TR5).
            h.grade_leaves = list(leaves)
            cat: dict[str, list[int]] = {}
            for l in leaves:
                key = l.get("task_category") or "Uncategorized"
                slot = cat.setdefault(key, [0, 0])
                slot[1] += 1
                if l.get("passed"):
                    slot[0] += 1
            h.category_pass = {k: (v[0], v[1]) for k, v in cat.items()}
            # top failed leaves by weight desc
            failed = [l for l in leaves if not l.get("passed")]
            failed.sort(key=lambda l: -int(l.get("weight") or 1))
            h.top_failed_leaves = failed[:10]
            h.negative_control = g.get("negative_control") or {}
        except json.JSONDecodeError as e:
            log.warning("grade.json malformed: %s", e)

    # ── Blocking issues ──
    bi = checkpoint_dir / "blocking_issues.log"
    if bi.is_file():
        h.blocking_issues = [
            line.strip()
            for line in bi.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ][:50]

    # ── Heuristic recommendations ──
    if h.ors_score < 0.20 and h.leaves_total:
        h.recommendations.append(
            "Score below 20%: review reproduce.sh for missing GPU usage or "
            "shortcut implementations bypassing the paper's actual method."
        )
    if h.missing_artifacts:
        h.recommendations.append(
            f"{len(h.missing_artifacts)} expected artefact(s) missing — "
            "the agent did not emit the files the rubric declared."
        )
    if h.repro_exit_code not in (0, None):
        h.recommendations.append(
            f"reproduce.sh exited with code {h.repro_exit_code} — investigate "
            "the reproduce.log tail before re-running."
        )
    if h.execution_profile.get("kind") in ("mpi", "mpi_gpu") and h.repro_nodes <= 1:
        h.recommendations.append(
            "execution_profile is MPI but the run was single-node; "
            "consider raising --nodes / --ntasks for a faithful reproduction."
        )
    if not h.recommendations:
        h.recommendations.append("No automated concerns flagged.")

    return h


# ── Rendering ──────────────────────────────────────────────────────────


def _render_category_rows(cats: dict[str, int]) -> str:
    rows = sorted(cats.items(), key=lambda x: -x[1])
    return " \\\\\n".join(f"{tex_escape(k)} & {v}" for k, v in rows) + " \\\\"


def _render_category_pass_rows(pass_map: dict[str, tuple[int, int]]) -> str:
    if not pass_map:
        return "\\multicolumn{4}{c}{(no grade data)} \\\\"
    rows: list[str] = []
    for cat, (passed, total) in sorted(pass_map.items()):
        rate = (100.0 * passed / total) if total else 0.0
        rows.append(f"{tex_escape(cat)} & {passed} & {total} & {rate:.1f}\\%")
    return " \\\\\n".join(rows) + " \\\\"


def _render_failed_leaves(failed: list[dict]) -> str:
    if not failed:
        return "  \\item (no failures recorded)"
    out: list[str] = []
    for l in failed[:10]:
        req = tex_escape(l.get("requirements", "")[:200])
        wt = l.get("weight") or 1
        out.append(f"  \\item [weight={wt}] {req}")
    return "\n".join(out)


def _render_execution_profile(p: dict) -> str:
    if not p:
        return "(none — single-node CPU paper)"
    rows: list[str] = []
    for k in (
        "kind", "paper_max_ranks", "paper_max_nodes",
        "requested_nodes", "ntasks_per_node",
        "exclusive", "requested_gpus_per_task", "gpu_type",
        "memory_gb_per_node", "constraint", "cpu_bind", "module_loads",
    ):
        if p.get(k) not in (None, "", 0, False, []):
            rows.append(f"\\textbf{{{tex_escape(k)}}}: \\texttt{{{tex_escape(p[k])}}}")
    return ", ".join(rows) if rows else "(profile empty)"


def _render_submission_files(files: list[str]) -> str:
    if not files:
        return "  \\item (no submission files)"
    show = files[:30]
    extra = len(files) - len(show)
    out = [f"  \\item \\texttt{{{tex_escape(f)}}}" for f in show]
    if extra > 0:
        out.append(f"  \\item ...and {extra} more")
    return "\n".join(out)


def _render_missing(missing: list[str]) -> str:
    if not missing:
        return "All expected artefacts were emitted."
    out = [f"  \\item \\texttt{{{tex_escape(f)}}}" for f in missing]
    return "Missing:\n\\begin{itemize}\n" + "\n".join(out) + "\n\\end{itemize}"


def _render_blocking_issues(issues: list[str]) -> str:
    if not issues:
        return "(no blocking issues reported)"
    out = [f"  \\item {tex_escape(i)[:300]}" for i in issues[:20]]
    return "\\begin{itemize}\n" + "\n".join(out) + "\n\\end{itemize}"


def _render_recommendations(recs: list[str]) -> str:
    if not recs:
        return "  \\item (no recommendations)"
    return "\n".join(f"  \\item {tex_escape(r)}" for r in recs)


def _render_negative_control(nc: dict) -> str:
    if not nc:
        return "(skipped or unavailable)"
    empty = nc.get("empty")
    boilerplate = nc.get("boilerplate")
    passed = nc.get("passed")
    return (
        f"Empty-repo score: {empty:.3f}; boilerplate score: {boilerplate:.3f}; "
        f"passed (both <5\\%): \\textbf{{{passed}}}."
        if empty is not None and boilerplate is not None
        else "(partial data)"
    )


def _render_multinode_block(h: CheckpointHarvest) -> str:
    if h.repro_nodes or h.repro_ntasks:
        return f"nodes={h.repro_nodes}, ntasks={h.repro_ntasks}"
    return "—"


# ── Figures ─────────────────────────────────────────────────────────────


def _figure_rubric_tree(h: CheckpointHarvest, out_path: Path, *, max_nodes: int = 60) -> bool:
    """Render the rubric tree to ``out_path`` (PDF) via graphviz ``dot``.

    Falls back gracefully:
      - dot binary missing → return False
      - rubric envelope absent → return False
      - tree larger than ``max_nodes`` → render top-k nodes by weight + a
        synthetic "(... N more leaves)" sink so the figure remains
        readable.

    Returns True iff the figure was produced.
    """
    if not shutil.which("dot"):
        log.info("graphviz dot not on PATH; skipping rubric_tree figure")
        return False
    root = (h.rubric_envelope or {}).get("rubric")
    if not isinstance(root, dict):
        return False

    # Collect (id, parent_id, label, is_leaf) tuples, depth-first, weight-sorted
    nodes: list[tuple[str, str | None, str, bool, int]] = []
    counter = {"n": 0}

    def _walk(node: dict, parent_id: str | None, depth: int) -> None:
        if not isinstance(node, dict) or counter["n"] >= max_nodes:
            return
        node_id = node.get("id") or f"n{counter['n']}"
        text = (node.get("requirements") or "").strip()[:60].replace('"', "'")
        weight = int(node.get("weight") or 1)
        children = node.get("sub_tasks") or []
        is_leaf = not children
        nodes.append((node_id, parent_id, text, is_leaf, weight))
        counter["n"] += 1
        # Sort children by weight descending so heavy subtrees show first
        for c in sorted(children, key=lambda x: -int((x.get("weight") if isinstance(x, dict) else 1) or 1)):
            if counter["n"] >= max_nodes:
                # Add a single synthetic sink and stop
                nodes.append((f"sink_{node_id}", node_id, f"... (truncated, {len(children)} children)", True, 0))
                counter["n"] += 1
                break
            _walk(c, node_id, depth + 1)

    _walk(root, None, 0)

    lines: list[str] = [
        "digraph rubric {",
        '  rankdir=LR;',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9];',
        '  edge [fontname="Helvetica", fontsize=8, color="#888"];',
    ]
    for nid, parent, label, is_leaf, _w in nodes:
        fill = "#dbeafe" if not is_leaf else "#ecfdf5"
        lines.append(f'  "{nid}" [label="{label}", fillcolor="{fill}"];')
        if parent:
            lines.append(f'  "{parent}" -> "{nid}";')
    lines.append("}")
    dot_source = "\n".join(lines)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["dot", "-Tpdf", "-o", str(out_path)],
            input=dot_source, text=True, capture_output=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("dot failed for rubric_tree: %s", e)
        return False
    if r.returncode != 0 or not out_path.is_file():
        log.warning("dot returned %s; rubric_tree skipped (stderr=%s)", r.returncode, r.stderr[:200])
        return False
    return True


def _figure_score_distribution(
    h: CheckpointHarvest, out_path: Path,
) -> bool:
    """Render a tiny bar chart of per-category pass rate via matplotlib.

    Returns True iff the figure was produced. Failures (matplotlib missing,
    no grade data) just return False so the LaTeX falls back to a stub.
    """
    if not h.category_pass:
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.info("matplotlib unavailable; skipping figure")
        return False
    cats = list(h.category_pass.keys())
    rates = [100.0 * h.category_pass[c][0] / max(1, h.category_pass[c][1]) for c in cats]
    fig, ax = plt.subplots(figsize=(5, 2.6))
    bars = ax.bar(cats, rates)
    for b, r in zip(bars, rates):
        ax.text(b.get_x() + b.get_width() / 2, r + 1, f"{r:.0f}%", ha="center", fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Pass rate (%)")
    ax.set_title("Per-category pass rate")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return True


def _figure_leaf_score_heatmap(h: CheckpointHarvest, out_path: Path) -> bool:
    """Render a leaf-score heatmap (rows = task_category, cols = leaves)
    via matplotlib.

    Each cell is 0 (failed, red) or 1 (passed, green). Categories are
    grouped on the y-axis; leaves within a category are ordered by their
    original rubric position. Helpful for spotting clustered failures
    (e.g. "all Code Execution leaves failed → reproduce.sh didn't run").

    Returns True iff the figure was produced. Falls through to False when
    matplotlib is missing OR the grade payload lacks per-leaf records.
    """
    raw_leaves: list[dict] = list(h.grade_leaves or [])
    if not raw_leaves and h.leaves_total:
        # Reconstruct minimally from harvest: we only have pass counts per
        # category. Synthesize per-leaf 0/1 cells in category order so the
        # heatmap still visualises the breakdown.
        for cat, (p, t) in h.category_pass.items():
            for i in range(t):
                raw_leaves.append({
                    "task_category": cat,
                    "passed": i < p,
                    "requirements": f"{cat} leaf {i + 1}",
                })
    if not raw_leaves:
        return False

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        log.info("matplotlib/numpy unavailable; skipping heatmap")
        return False

    # Group by category, ordered: Code Development / Code Execution /
    # Result Analysis / (anything else last). This matches the
    # PaperBench category vocabulary canonically.
    canonical_order = [
        "Code Development", "Code Execution", "Result Analysis",
    ]
    by_cat: dict[str, list[int]] = {}
    for leaf in raw_leaves:
        cat = leaf.get("task_category") or "Uncategorized"
        by_cat.setdefault(cat, []).append(1 if leaf.get("passed") else 0)

    cats = [c for c in canonical_order if c in by_cat] + sorted(
        c for c in by_cat if c not in canonical_order
    )
    if not cats:
        return False
    max_w = max(len(by_cat[c]) for c in cats)
    grid = np.full((len(cats), max_w), np.nan)
    for r, c in enumerate(cats):
        row = by_cat[c]
        grid[r, : len(row)] = row

    fig_w = max(5.0, 0.18 * max_w + 1.5)
    fig_h = max(1.6, 0.55 * len(cats) + 0.6)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    cmap = plt.matplotlib.colors.ListedColormap(["#dc2626", "#16a34a"])  # red, green
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels(cats, fontsize=9)
    ax.set_xticks([])
    ax.set_xlabel(f"Leaves (left → right; {sum(len(v) for v in by_cat.values())} total)")
    ax.set_title("Per-leaf pass/fail heatmap")
    for r, c in enumerate(cats):
        ax.text(
            len(by_cat[c]) - 0.5, r,
            f" {sum(by_cat[c])}/{len(by_cat[c])}",
            ha="left", va="center", fontsize=8, color="#1f2937",
        )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return True


# ── Public API ──────────────────────────────────────────────────────────


def generate_paper_report(
    *,
    checkpoint_dir: Path,
    paper_id: str,
    output_root: Path,
    languages: list[str] | None = None,
    formats: list[str] | None = None,
    ari_version: str = "0.7.2",
) -> dict:
    """Render a per-paper PaperBench audit report.

    Args:
        checkpoint_dir: ARI checkpoint root for this paper.
        paper_id: short id (e.g. ``sc24-00019``).
        output_root: where the rendered tree lands (e.g.
            ``report/audit/sc24-00019``).
        languages: list including ``"en"`` and optionally ``"ja"`` / ``"zh"``.
            Defaults to ``["en"]``; non-en languages produce stub files that
            ``report/scripts/translate.py`` later fills in.
        formats: ``["pdf"]`` (default) | ``["pdf", "html"]`` | etc. PDF
            requires ``latexmk`` on PATH; missing tools degrade to "tex only".

    Returns ``{"status": "ok", "languages": [...], "paths": [...]}``.
    """
    languages = languages or ["en"]
    formats = formats or ["pdf"]
    if not checkpoint_dir.is_dir():
        return {"status": "error", "error": f"checkpoint not found: {checkpoint_dir}"}

    h = harvest_checkpoint(checkpoint_dir, paper_id)
    output_root.mkdir(parents=True, exist_ok=True)

    paths_written: list[str] = []
    for lang in languages:
        lang_dir = output_root / lang
        chapters_dir = lang_dir / "chapters"
        figures_dir = lang_dir / "figures"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        figures_dir.mkdir(parents=True, exist_ok=True)

        # ── Figures ──
        score_fig = figures_dir / "score_distribution.pdf"
        score_fig_block = (
            f"\\includegraphics[width=0.7\\linewidth]{{figures/{score_fig.name}}}"
            if _figure_score_distribution(h, score_fig)
            else "\\textit{(no grade data — figure omitted)}"
        )
        heatmap_fig = figures_dir / "leaf_score_heatmap.pdf"
        heatmap_fig_block = (
            f"\\includegraphics[width=\\linewidth]{{figures/{heatmap_fig.name}}}"
            if _figure_leaf_score_heatmap(h, heatmap_fig)
            else "\\textit{(no per-leaf grade data — heatmap omitted)}"
        )
        tree_fig = figures_dir / "rubric_tree.pdf"
        tree_fig_block = (
            f"\\includegraphics[width=\\linewidth]{{figures/{tree_fig.name}}}"
            if _figure_rubric_tree(h, tree_fig)
            else "\\textit{(graphviz ``dot'' not on PATH — rubric tree figure omitted)}"
        )

        # ── Values dict (LaTeX-safe) ──
        values: dict[str, Any] = {
            "paper_id": tex_escape(h.paper_id),
            "paper_title": tex_escape(h.paper_title or h.paper_id),
            "paper_authors": tex_escape(", ".join(h.paper_authors) or "—"),
            "paper_venue": tex_escape(h.paper_venue or "—"),
            "paper_year": tex_escape(str(h.paper_year or "—")),
            "paper_license": tex_escape(h.paper_license or "—"),
            "paper_source_type": tex_escape(h.paper_source_type or "—"),
            "paper_source": tex_escape(h.paper_source or "—"),
            "paper_artifact_url": tex_escape(h.paper_artifact_url or ""),
            "license_note": tex_escape(h.license_note or "—"),
            "ari_version": tex_escape(ari_version),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "rubric_leaves_count": h.rubric_leaves_count,
            "rubric_depth": h.rubric_depth,
            "rubric_generator_model": tex_escape(h.rubric_generator_model or "—"),
            "rubric_two_stage": "yes" if h.rubric_two_stage else "no",
            "rubric_audit_flags_count": h.rubric_audit_flags_count,
            "rubric_category_rows": _render_category_rows(h.rubric_category_breakdown),
            "execution_profile_block": _render_execution_profile(h.execution_profile),
            "rubric_tree_figure_block": tree_fig_block,
            "repro_sandbox_kind": tex_escape(h.repro_sandbox_kind or "—"),
            "repro_partition": tex_escape(h.repro_partition or "—"),
            "repro_wallclock": tex_escape(h.repro_wallclock or "—"),
            "repro_exit_code": h.repro_exit_code if h.repro_exit_code is not None else "—",
            "repro_elapsed_sec": f"{h.repro_elapsed_sec:.1f}",
            "repro_multinode_block": _render_multinode_block(h),
            "repro_exclusive": "yes" if h.repro_exclusive else "no",
            "repro_gpu_spec": tex_escape(h.repro_gpu_spec or "—"),
            "submission_file_list": _render_submission_files(h.submission_files),
            "reproduce_log_tail": h.reproduce_log_tail[-4000:],  # cap for LaTeX
            "missing_artifacts_block": _render_missing(h.missing_artifacts),
            "ors_score_percent": f"{h.ors_score * 100.0:.1f}",
            "category_pass_rows": _render_category_pass_rows(h.category_pass),
            "score_distribution_figure_block": score_fig_block,
            "leaf_score_heatmap_figure_block": heatmap_fig_block,
            "failed_leaves_list": _render_failed_leaves(h.top_failed_leaves),
            "negative_control_block": _render_negative_control(h.negative_control),
            "blocking_issues_block": _render_blocking_issues(h.blocking_issues),
            "recommendations_list": _render_recommendations(h.recommendations),
        }

        # ── Render chapter sources ──
        # Templates are inlined as Python string constants
        # (``_TMPL_MAIN`` + ``_CHAPTER_TEMPLATES``); for non-en
        # languages the rendered output is then passed through
        # ``_apply_glossary`` so the fixed UI strings (section
        # headers, table labels, common phrases) swap to the
        # target-language equivalents from
        # ``report/shared/i18n.json``. The main.tex additionally
        # gets a ``\\usepackage{xeCJK}`` preamble for ja/zh so CJK
        # characters render with the HaranoAji / Fandol fonts.
        main_text = render_template(_TMPL_MAIN, values)
        main_text = _apply_glossary(main_text, lang)
        main_text = _inject_lang_preamble(main_text, lang)
        (lang_dir / "main.tex").write_text(main_text, encoding="utf-8")
        paths_written.append(str(lang_dir / "main.tex"))

        for chapter_filename, chapter_body in _CHAPTER_TEMPLATES.items():
            rendered = render_template(chapter_body, values)
            rendered = _apply_glossary(rendered, lang)
            out = chapters_dir / chapter_filename
            out.write_text(rendered, encoding="utf-8")
            paths_written.append(str(out))

        # ── Build PDF (best-effort) ──
        if "pdf" in formats and shutil.which("latexmk"):
            try:
                subprocess.run(
                    [
                        "latexmk", "-xelatex", "-interaction=nonstopmode",
                        "-output-directory=build",
                        "main.tex",
                    ],
                    cwd=lang_dir,
                    check=False,
                    capture_output=True,
                    timeout=180,
                )
                pdf = lang_dir / "build" / "main.pdf"
                if pdf.is_file():
                    paths_written.append(str(pdf))
            except (subprocess.SubprocessError, OSError) as e:
                log.warning("latexmk run failed for %s: %s", lang, e)

        # ── Build HTML / Markdown via pandoc (best-effort) ──
        # pandoc reads main.tex (which \input's the chapter sources) and
        # emits a single-file HTML / Markdown that the GUI can serve.
        # When pandoc is absent the formats degrade silently to skip.
        if ("html" in formats or "md" in formats) and shutil.which("pandoc"):
            tex_path = lang_dir / "main.tex"
            for fmt, ext, extra_args in (
                ("html", "html", ["--standalone", "--mathjax", "--toc"]),
                ("md",   "md",   ["--wrap=preserve"]),
            ):
                if fmt not in formats:
                    continue
                out_file = lang_dir / f"main.{ext}"
                try:
                    subprocess.run(
                        ["pandoc", str(tex_path), "-f", "latex", "-t",
                         "html5" if fmt == "html" else "gfm",
                         "-o", str(out_file), *extra_args],
                        cwd=lang_dir,
                        check=False, capture_output=True, timeout=120,
                    )
                except (subprocess.SubprocessError, OSError) as e:
                    log.warning("pandoc %s failed for %s: %s", fmt, lang, e)
                    continue
                if out_file.is_file():
                    paths_written.append(str(out_file))
        elif "html" in formats or "md" in formats:
            log.info("pandoc not on PATH; HTML / Markdown emission skipped")

    return {
        "status": "ok",
        "languages": languages,
        "paths": paths_written,
        "harvest": {
            "ors_score": h.ors_score,
            "leaves_total": h.leaves_total,
            "leaves_passed": h.leaves_passed,
        },
    }


def generate_summary_report(
    *,
    checkpoint_dirs: list[Path],
    output_root: Path,
    paper_ids: list[str] | None = None,
    languages: list[str] | None = None,
    formats: list[str] | None = None,
    ari_version: str = "0.7.2",
) -> dict:
    """Render a multi-paper summary report.

    Args:
        checkpoint_dirs: one ARI checkpoint per paper to compare.
        paper_ids: aligned with ``checkpoint_dirs``; defaults to dir names.
        output_root: e.g. ``report/audit/_summary/2026-05-11``.
    """
    languages = languages or ["en"]
    formats = formats or ["pdf"]
    if not checkpoint_dirs:
        return {"status": "error", "error": "no checkpoints supplied"}
    paper_ids = paper_ids or [d.name for d in checkpoint_dirs]
    harvests = [
        harvest_checkpoint(d, pid) for d, pid in zip(checkpoint_dirs, paper_ids)
    ]

    output_root.mkdir(parents=True, exist_ok=True)
    paths_written: list[str] = []

    for lang in languages:
        lang_dir = output_root / lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        # Render a slim summary tex inline (no separate template) since the
        # report is intentionally compact — full per-paper detail lives in
        # the per-paper reports linked at the bottom.
        rows = []
        for h in sorted(harvests, key=lambda x: -x.ors_score):
            rows.append(
                f"\\texttt{{{tex_escape(h.paper_id)}}} & "
                f"{tex_escape(h.paper_title or '—')[:60]} & "
                f"{h.ors_score * 100:.1f}\\% & "
                f"{h.leaves_passed}/{h.leaves_total} & "
                f"\\texttt{{{tex_escape(h.execution_profile.get('kind') or '—')}}} "
                "\\\\"
            )
        scores = [h.ors_score for h in harvests if h.leaves_total]
        avg = sum(scores) / max(1, len(scores))

        tex = f"""\\documentclass[a4paper,11pt]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{geometry}}
\\geometry{{margin=2.2cm}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}

\\title{{PaperBench Audit Summary \\\\ \\large {len(harvests)} papers}}
\\author{{ARI v{ari_version} -- generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}}}
\\date{{}}

\\begin{{document}}
\\maketitle

\\section{{Overview}}

This summary aggregates PaperBench audit results across {len(harvests)} papers.
Mean ORS score: \\textbf{{{avg * 100:.1f}\\%}}.

\\section{{Score Table}}

\\begin{{longtable}}{{lp{{6cm}}rrr}}
\\toprule
\\textbf{{paper\\_id}} & \\textbf{{title}} & \\textbf{{ORS}} & \\textbf{{leaves}} & \\textbf{{kind}} \\\\
\\midrule
{chr(10).join(rows)}
\\bottomrule
\\end{{longtable}}

\\end{{document}}
"""
        (lang_dir / "main.tex").write_text(tex, encoding="utf-8")
        paths_written.append(str(lang_dir / "main.tex"))

        if "pdf" in formats and shutil.which("latexmk"):
            try:
                subprocess.run(
                    [
                        "latexmk", "-xelatex", "-interaction=nonstopmode",
                        "-output-directory=build", "main.tex",
                    ],
                    cwd=lang_dir, check=False, capture_output=True, timeout=180,
                )
                pdf = lang_dir / "build" / "main.pdf"
                if pdf.is_file():
                    paths_written.append(str(pdf))
            except (subprocess.SubprocessError, OSError) as e:
                log.warning("latexmk summary run failed: %s", e)

    return {
        "status": "ok",
        "papers": len(harvests),
        "mean_ors_score": avg if harvests else 0.0,
        "paths": paths_written,
    }


# ── CLI ─────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(description="Render a PaperBench audit report")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_single = sub.add_parser("paper", help="per-paper detail report")
    p_single.add_argument("--checkpoint", required=True, type=Path)
    p_single.add_argument("--paper-id", required=True)
    p_single.add_argument("--output-root", required=True, type=Path)
    p_single.add_argument("--languages", nargs="*", default=["en"])
    p_single.add_argument("--formats", nargs="*", default=["pdf"])

    p_summary = sub.add_parser("summary", help="multi-paper summary")
    p_summary.add_argument("--checkpoint", action="append", required=True, type=Path)
    p_summary.add_argument("--paper-id", action="append", default=[])
    p_summary.add_argument("--output-root", required=True, type=Path)
    p_summary.add_argument("--languages", nargs="*", default=["en"])
    p_summary.add_argument("--formats", nargs="*", default=["pdf"])

    args = p.parse_args()
    logging.basicConfig(level=os.environ.get("ARI_REPORT_LOG_LEVEL", "INFO"))

    if args.cmd == "paper":
        res = generate_paper_report(
            checkpoint_dir=args.checkpoint,
            paper_id=args.paper_id,
            output_root=args.output_root,
            languages=args.languages,
            formats=args.formats,
        )
    else:
        res = generate_summary_report(
            checkpoint_dirs=args.checkpoint,
            output_root=args.output_root,
            paper_ids=args.paper_id or None,
            languages=args.languages,
            formats=args.formats,
        )
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
