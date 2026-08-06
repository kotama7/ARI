"""MCP Server for LaTeX paper writing support."""

import asyncio
import json
import os
import re
from pathlib import Path

import logging
import litellm
from mcp.server.fastmcp import FastMCP

from ari.public.research_contract import load_survey_snapshot_ref

# Wire cost tracking for LLM calls made inside this skill subprocess.
# ari-core is injected onto PYTHONPATH by ari.mcp.client, so this import
# succeeds under ARI; optional for standalone skill testing.
try:
    from src.authoring import (  # type: ignore
        AuthoringRecorder,
        artifact_from_payload,
        json_bytes as _paper_json_bytes,
        load_authoring_inputs,
        model_usage_from_response,
    )
    from src.compiler import compile_project  # type: ignore
    from src.finalize import finalize_build  # type: ignore
    from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore

    _ari_cost_tracker.bootstrap_skill("paper")
except Exception:
    pass

try:
    from src.review_engine import (  # type: ignore
        build_user_prompt,
        build_system_prompt,
        load_dynamic_fewshot,
        load_static_fewshot,
        resolve_rubric,
        run_ensemble,
        run_meta_review,
    )
    from src.rubric import list_available_rubrics, load_rubric  # type: ignore
except ImportError:  # running from within src/
    from authoring import (  # type: ignore
        AuthoringRecorder,
        artifact_from_payload,
        json_bytes as _paper_json_bytes,
        load_authoring_inputs,
        model_usage_from_response,
    )
    from compiler import compile_project  # type: ignore
    from finalize import finalize_build  # type: ignore
    from review_engine import (  # type: ignore
        build_user_prompt,
        build_system_prompt,
        load_dynamic_fewshot,
        load_static_fewshot,
        resolve_rubric,
        run_ensemble,
        run_meta_review,
    )
    from rubric import list_available_rubrics, load_rubric  # type: ignore

log = logging.getLogger(__name__)


def _resolve_retrieval_refs(refs_json, *, checkpoint: str | None = None):
    """Resolve a recorded retrieval result to its verified compact snapshot."""

    if not refs_json:
        return {}
    data = json.loads(refs_json) if isinstance(refs_json, str) else refs_json
    if not isinstance(data, dict):
        raise ValueError("reference input must be a JSON object")
    if data.get("schema_version") == "ari.paper-references/v1":
        return data
    snapshot_ref = str(data.get("snapshot_ref") or "").strip()
    if not snapshot_ref:
        if data.get("schema_version") == "ari.retrieval-result/v1":
            raise ValueError(
                "paper generation requires a recorded retrieval snapshot_ref"
            )
        return data
    checkpoint = (checkpoint or os.environ.get("ARI_CHECKPOINT_DIR", "")).strip()
    if not checkpoint:
        raise ValueError("snapshot_ref requires ARI_CHECKPOINT_DIR")
    snapshot = load_survey_snapshot_ref(checkpoint, snapshot_ref)
    advertised = data.get("survey_snapshot_digest")
    if advertised is not None and advertised != snapshot.snapshot_digest:
        raise ValueError("advertised survey snapshot digest does not match reference")
    papers = []
    for record in snapshot.records:
        arxiv_id = next(
            (
                alias.removeprefix("arxiv:")
                for alias in (record.canonical_id, *record.aliases)
                if alias.startswith("arxiv:")
            ),
            "",
        )
        papers.append(
            {
                "title": record.title,
                "authors": list(record.authors),
                "year": str(record.year or ""),
                "published": str(record.year or ""),
                "abstract": record.abstract,
                "url": record.source_url or "",
                "arxivId": arxiv_id,
                "canonical_id": record.canonical_id,
                "payload_digest": record.payload_digest,
            }
        )
    return {
        "schema_version": "ari.paper-references/v1",
        "snapshot_ref": snapshot_ref,
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "provider": snapshot.provider,
        "query": snapshot.query,
        "papers": papers,
    }


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

VENUES = [
    {"id": "neurips", "name": "NeurIPS", "deadline": "May 2025", "pages": 9},
    {"id": "icpp", "name": "ICPP", "deadline": "March 2025", "pages": 10},
    {"id": "sc", "name": "SuperComputing", "deadline": "April 2025", "pages": 12},
    {
        "id": "isc",
        "name": "ISC High Performance",
        "deadline": "February 2025",
        "pages": 12,
    },
    {"id": "arxiv", "name": "arXiv", "deadline": "N/A", "pages": 0},
    {"id": "acm", "name": "ACM (general)", "deadline": "Varies", "pages": 10},
]


# ── skill-local prompt loader (subtask 041) ──────────────────────────────────
# Static paper-generation instructions are stored as byte-identical ``.md``
# templates under ``src/prompts/`` and loaded here through a tiny mirror of
# ari-core's ``FilesystemPromptLoader`` ``load_versioned`` contract. The helper
# is COPIED (not imported from ari-core) to preserve the one-way
# ``ari-skill-* -> ari-core`` boundary and keep this MCP package self-contained.
# Placed AFTER the module imports/VENUES so the grandfathered ``from ari import
# cost_tracker`` fallback stays on its pinned line (test_public_api_boundary).
# New stdlib import (``hashlib``) is function-local, matching this module's
# style. Most templates are loaded RAW (no ``str.format``) because they embed
# literal LaTeX/JSON braces. The dynamic
# per-call fragments (``_paper_language_directive()``, the verified-context
# grounded block, the venue prefix) stay in Python — only static bytes move.
# Deterministic (P2): a package-relative file read — no LLM, no network.
def _prompt_path(key: str) -> Path:
    """Absolute path to the skill-local prompt template *key* (``prompts/<key>.md``)."""
    return Path(__file__).resolve().parent / "prompts" / f"{key}.md"


def _load_prompt(key: str) -> str:
    """Return prompt template *key* byte-identical to the pre-extraction literal.

    The ``.md`` file is stored with a trailing newline (file convention); a
    single trailing ``\\n`` is trimmed so the loaded string equals the original
    inline bytes exactly, mirroring ari-core's ``llm_evaluator.py`` discipline.
    """
    text = _prompt_path(key).read_text(encoding="utf-8")
    return text[:-1] if text.endswith("\n") else text


def _load_prompt_versioned(key: str) -> tuple[str, str]:
    """``(rendered_text, sha256[:12])`` for uniform prompt hashing.

    The hash is over the raw on-disk template body (before the trailing-newline
    trim), matching ari-core's ``load_versioned`` so snapshot/provenance tooling
    pins the same value. Deterministic; no LLM, no network.
    """
    import hashlib

    raw = _prompt_path(key).read_text(encoding="utf-8")
    return _load_prompt(key), hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# Map ARI_PAPER_LANGUAGE → human-readable name + LaTeX babel/preamble hint.
# The wizard sends ISO-639-1 codes (en/ja/zh); aliases handle stray full names.
_LANGUAGE_NAMES = {
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "japanese": "Japanese",
    "jp": "Japanese",
    "zh": "Chinese",
    "chinese": "Chinese",
    "zh-cn": "Chinese",
}


def _paper_language_directive() -> str:
    """Return a LaTeX-aware language directive for paper system prompts.

    Reads ARI_PAPER_LANGUAGE (wizard "Language" dropdown). Empty / unknown /
    English values return "" so the prompt stays unchanged (preserves the
    historical English-only default). Non-English values instruct the LLM to
    write prose in that language AND add the matching LaTeX babel package so
    the document actually compiles."""
    _lang = (os.environ.get("ARI_PAPER_LANGUAGE") or "").strip().lower()
    if not _lang:
        return ""
    _name = _LANGUAGE_NAMES.get(_lang, "")
    if not _name or _name == "English":
        return ""
    if _name == "Japanese":
        _preamble = (
            "Include `\\usepackage[whole]{bxcjkjatype}` (or `\\usepackage{CJKutf8}` "
            "if bxcjkjatype is unavailable) in the preamble and wrap Japanese "
            "prose in `\\begin{CJK}{UTF8}{min}…\\end{CJK}` when using CJKutf8."
        )
    else:  # Chinese
        _preamble = (
            "Include `\\usepackage{CJKutf8}` in the preamble and wrap Chinese "
            "prose in `\\begin{CJK}{UTF8}{gbsn}…\\end{CJK}`."
        )
    return (
        f"\n══ LANGUAGE ══\n"
        f"Write the entire paper body (abstract, sections, captions) in {_name}. "
        f"Keep LaTeX commands, math, BibTeX cite keys, figure filenames, and "
        f"section identifiers in ASCII as usual. {_preamble}\n"
        f"══ END LANGUAGE ══\n"
    )


mcp = FastMCP("paper-writing-skill")


@mcp.tool()
async def list_venues() -> list[dict]:
    """List supported academic venues with deadlines and page limits."""
    return VENUES


@mcp.tool()
async def get_template(venue: str) -> dict:
    """Get LaTeX template files for a specific venue.

    Args:
        venue: Venue identifier (e.g. "neurips", "icpp", "sc", "isc", "arxiv", "acm")
    """
    venue_dir = TEMPLATES_DIR / venue
    if not venue_dir.is_dir():
        valid = [v["id"] for v in VENUES]
        raise ValueError(f"Unknown venue '{venue}'. Valid venues: {valid}")

    files = {}
    for f in venue_dir.iterdir():
        if f.is_file():
            files[f.name] = f.read_text(encoding="utf-8")

    return {"files": files}


@mcp.tool()
async def compile_paper(
    tex_dir: str,
    main_file: str = "main.tex",
    figures_manifest_path: str = "",
) -> dict:
    """Compile a LaTeX project to PDF.

    Args:
        tex_dir: Directory containing the LaTeX source files
        main_file: Name of the main .tex file (default: main.tex)
    """
    tex_path = Path(tex_dir).resolve()
    if not tex_path.is_dir():
        return {
            "success": False,
            "pdf_path": "",
            "log": f"Directory not found: {tex_dir}",
        }

    main = tex_path / main_file
    if not main.is_file():
        return {"success": False, "pdf_path": "", "log": f"File not found: {main}"}

    from ari.public.execution import WorkspaceRefV1

    workspace = WorkspaceRefV1(root=str(tex_path))
    bib_file = "refs.bib" if (tex_path / "refs.bib").is_file() else None
    figures = None
    if figures_manifest_path:
        from ari.public.figures import parse_figure_batch

        try:
            manifest_path = workspace.resolve(
                figures_manifest_path,
                require_file=True,
            )
            figures = parse_figure_batch(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {
                "success": False,
                "pdf_path": "",
                "log": f"invalid FigureBatchV1: {exc}",
                "compile": None,
            }
    try:
        outcome = await asyncio.to_thread(
            compile_project,
            workspace=workspace,
            main_file=main_file,
            bib_file=bib_file,
            figures=figures,
        )
    except ValueError as exc:
        return {
            "success": False,
            "pdf_path": "",
            "log": str(exc),
            "compile": None,
        }
    workspace.atomic_write_bytes(
        ".ari-paper/compile/final.json",
        _paper_json_bytes(outcome.record.model_dump(mode="json")),
    )
    return {
        "success": outcome.record.status == "completed",
        "pdf_path": (
            str(tex_path / outcome.pdf_path) if outcome.pdf_path is not None else ""
        ),
        "log": "\n".join(outcome.diagnostics),
        "compile": outcome.record.model_dump(mode="json"),
    }


@mcp.tool()
async def finalize_paper_build(
    workspace_root: str,
    draft_build_path: str,
    tex_path: str,
    bib_path: str,
    pdf_path: str,
    compile_record_path: str,
    figures_manifest_path: str,
    claim_links_path: str,
    hard_gate_path: str,
    text_review_path: str,
    visual_review_path: str,
    semantic_review_path: str,
    refinement_call_path: str = "",
    visual_passing_score: float = 0.7,
    output_path: str = "paper_build.json",
) -> dict:
    """Lock exact paper evidence, reviews, compile, claims, and final artifacts."""

    build = await asyncio.to_thread(
        finalize_build,
        workspace_root=workspace_root,
        draft_build_path=draft_build_path,
        tex_path=tex_path,
        bib_path=bib_path,
        pdf_path=pdf_path,
        compile_record_path=compile_record_path,
        figures_manifest_path=figures_manifest_path,
        claim_links_path=claim_links_path,
        hard_gate_path=hard_gate_path,
        text_review_path=text_review_path,
        visual_review_path=visual_review_path,
        semantic_review_path=semantic_review_path,
        refinement_call_path=refinement_call_path,
        visual_passing_score=visual_passing_score,
        output_path=output_path,
    )
    if build.status != "finalized":
        raise ValueError(
            "paper finalization blocked; see the persisted PaperBuildV1: "
            + "; ".join(build.blocking_reasons)
        )
    return build.model_dump(mode="json")


@mcp.tool()
async def check_format(venue: str, pdf_path: str) -> dict:
    """Check if a PDF meets the venue's formatting requirements.

    Args:
        venue: Target venue identifier
        pdf_path: Path to the PDF file to check
    """
    venue_info = next((v for v in VENUES if v["id"] == venue), None)
    if venue_info is None:
        valid = [v["id"] for v in VENUES]
        raise ValueError(f"Unknown venue '{venue}'. Valid venues: {valid}")

    pdf = Path(pdf_path)
    issues = []

    if not pdf.is_file():
        return {"ok": False, "issues": [f"PDF not found: {pdf_path}"]}

    if not pdf_path.endswith(".pdf"):
        issues.append("File does not have .pdf extension")

    file_size = pdf.stat().st_size
    if file_size < 1000:
        issues.append("PDF file seems too small; may be corrupted")

    page_count = _count_pdf_pages(pdf)
    if venue_info["pages"] > 0:
        if page_count is None:
            # Undeterminable != within limit. Skipping made a 47-page paper
            # pass a 9-page limit with ok:true — record it so ok is False.
            issues.append(
                f"Page count could not be determined for {pdf.name}; the "
                f"{venue_info['pages']}-page venue limit was NOT verified")
        elif page_count > venue_info["pages"]:
            issues.append(
                f"Page count ({page_count}) exceeds venue limit ({venue_info['pages']})"
            )

    return {"ok": len(issues) == 0, "issues": issues}


def _count_pdf_pages(pdf_path: Path) -> int | None:
    """Count pages in a PDF. Returns None ONLY when the count is genuinely
    undeterminable — the caller then records an explicit issue rather than
    skipping the page-limit check.

    The old byte-regex for ``/Type /Page`` missed pages stored in compressed
    object streams (``/ObjStm``) — 59 of 79 PDFs in this repo, including ARI's
    own compile_paper output, hit zero and silently skipped the limit check, so
    a 47-page paper passed a 9-page venue limit. Prefer a real parser.
    """
    try:
        import pypdf
        with open(pdf_path, "rb") as fh:
            return len(pypdf.PdfReader(fh, strict=False).pages)
    except Exception:
        pass
    try:  # poppler, if the pure-Python parser is unavailable
        import subprocess
        r = subprocess.run(["pdfinfo", str(pdf_path)],
                           capture_output=True, text=True, timeout=20)
        for line in r.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    try:  # last resort: the old regex, which only sees UNcompressed page objects
        pages = re.findall(rb"/Type\s*/Page(?!s)", pdf_path.read_bytes())
        if pages:
            return len(pages)
    except Exception:
        pass
    return None  # genuinely undeterminable — caller must not skip the check


def _get_model(purpose: str = "paper") -> str:
    """Resolve the paper writer or independent rubric-review model.

    Phase-specific values precede the shared skill fallback so evaluation can
    assign Claude Code and Codex to different roles without starting two paper
    skill servers. Unknown purposes use the writer posture.
    """
    phase_model = (
        os.environ.get("ARI_MODEL_RUBRIC")
        if str(purpose) == "rubric"
        else os.environ.get("ARI_MODEL_PAPER")
    )
    return (phase_model
            or os.environ.get("ARI_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")

def _get_api_base(purpose: str = "paper") -> str | None:
    """Return LLM API base URL, or None to use provider default (e.g. OpenAI).

    Priority:
    1. ARI_LLM_API_BASE (paper-skill specific override; empty string → None = use OpenAI)
    2. If model is not ollama and OPENAI_API_KEY set → None (use OpenAI)
    3. LLM_API_BASE (global setting, e.g. Ollama)
    4. Default: None (litellm provider default)
    """
    ari_base = os.environ.get("ARI_LLM_API_BASE")
    if ari_base is not None:  # explicitly set (even to "")
        return ari_base or None  # "" → None = use OpenAI
    if os.environ.get("OPENAI_API_KEY") and "ollama" not in _get_model(purpose):
        return None
    return os.environ.get("LLM_API_BASE") or None


def _make_cite_key(paper: dict, seen: dict) -> str:
    import re as _re

    authors = paper.get("authors", [])
    lastname = (
        _re.sub(r"[^a-z]", "", authors[0].split()[-1].lower()) if authors else "anon"
    )
    year = str(paper.get("year") or paper.get("published") or "2024")[:4]
    words = paper.get("title", "").split()
    kw = _re.sub(r"[^a-z]", "", words[0].lower()) if words else "paper"
    base = f"{lastname}{year}{kw}"[:18]
    if base in seen:
        seen[base] += 1
        return base + str(seen[base])
    seen[base] = 0
    return base


def _escape_bibtex_field_values(entry: str) -> str:
    """Escape LaTeX-unsafe characters inside braced field values of a BibTeX entry.

    Semantic Scholar's `citationStyles.bibtex` returns raw `&`, `%`, `#` in fields like
    `title` and `booktitle` (e.g. "Principles & Practice of Parallel Programming").
    These pass straight through bibtex into the .bbl, which is then parsed as LaTeX —
    causing "Misplaced alignment tab character &" or comment-truncation errors.

    Escapes only inside the outermost `{...}` of `field = {...}` lines, and only when
    not already escaped (no preceding backslash) and not part of a command/entity.
    """
    import re as _re_e

    out_lines = []
    for line in entry.split("\n"):
        m = _re_e.match(r"(\s*[A-Za-z][A-Za-z0-9_-]*\s*=\s*)\{(.*)\}(,?\s*)$", line)
        if not m:
            out_lines.append(line)
            continue
        prefix, value, suffix = m.group(1), m.group(2), m.group(3)
        value = _re_e.sub(r"(?<!\\)&", r"\\&", value)
        value = _re_e.sub(r"(?<!\\)%", r"\\%", value)
        value = _re_e.sub(r"(?<!\\)#", r"\\#", value)
        out_lines.append(f"{prefix}{{{value}}}{suffix}")
    return "\n".join(out_lines)


def _build_bib_content(refs_json: str) -> tuple:
    """Build BibTeX file content from references JSON.

    Uses authoritative BibTeX from Semantic Scholar (bibtex/cite_key fields) when available.
    Falls back to synthesized BibTeX from arXiv metadata.
    Returns (bib_content: str, key_list: list of (key, title) tuples).
    """
    import re as _re_bib

    if not refs_json:
        return "", []
    refs_data = _resolve_retrieval_refs(refs_json)
    papers = refs_data.get("papers", [])
    entries, key_list, seen = [], [], {}
    # Cap generously (was 15) — collect_references already relevance-filters and
    # bounds the set, and a hard 15-slice silently DROPPED collected refs,
    # including (audit finding) the single most on-topic paper that happened to
    # sort past index 15, while the reported count still said 17. Include the
    # whole collected set; 50 is only a runaway guard.
    for p in papers[:50]:
        real_bib = p.get("bibtex", "")
        cite_key = p.get("cite_key", "")
        title = p.get("title", "Unknown")
        if real_bib and cite_key:
            # Authoritative BibTeX from Semantic Scholar
            key = cite_key.lower()
            suffix = "b"
            while key in seen:
                key = cite_key.lower() + suffix
                suffix += "b"
            seen[key] = True
            # Normalize cite key in first line of BibTeX
            lines = real_bib.split("\n")
            if lines:
                lines[0] = _re_bib.sub(r"\{[^,}]+,", "{" + key + ",", lines[0])
            entries.append(_escape_bibtex_field_values("\n".join(lines)))
        else:
            # Fallback: synthesize from arXiv metadata
            key = _make_cite_key(p, seen)
            seen[key] = True
            authors = " and ".join(p.get("authors", [])[:4]) or "Unknown"
            year = str(p.get("year") or p.get("published") or "2024")[:4]
            note = (
                p.get("abstract", "")[:120]
                .replace("{", "")
                .replace("}", "")
                .replace("\n", " ")
            )
            entries.append(
                _escape_bibtex_field_values(
                    "@article{" + key + ",\n"
                    "  author = {" + authors + "},\n"
                    "  title  = {" + title.replace("{", "").replace("}", "") + "},\n"
                    "  year   = {" + year + "},\n"
                    "  note   = {" + note + "}\n}"
                )
            )
        key_list.append((key, title))
    return "\n\n".join(entries), key_list


_MATH_ENV_NAMES = frozenset(
    {
        "equation",
        "align",
        "eqnarray",
        "displaymath",
        "math",
        "gather",
        "multline",
        "alignat",
        "flalign",
        "split",
        "aligned",
        "gathered",
        "cases",
    }
)


#: Language asserting that a VERIFICATION/VALIDATION was performed. A refiner
#: may legitimately reword a result; it may not invent a process. These are the
#: shapes an inserted sentence takes when it claims work that never happened
#: ("we independently re-verified each figure ... and confirm they agree to
#: within rounding" — a real insertion that shipped, and was false).
_PROCESS_CLAIM_RE = re.compile(
    r"\b(?:we|the authors?)\b[^.]{0,120}?\b("
    r"re-?verif\w*|verif\w*|re-?check\w*|cross-?check\w*|re-?comput\w*|"
    r"re-?measur\w*|confirm\w*|validat\w*|audit\w*|reproduc\w*"
    r")\b",
    re.IGNORECASE,
)


def _sentences_of(tex: str) -> list[str]:
    """Prose sentences of a LaTeX document, comments and commands stripped."""
    body = re.sub(r"(?m)^\s*%.*$", " ", tex)          # whole-line comments
    body = re.sub(r"%.*", " ", body)                  # trailing comments
    body = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", body)
    out: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+", body):
        s = re.sub(r"\s+", " ", raw).strip()
        if len(s) > 40 and re.search(r"[a-zA-Z]{4}", s):
            out.append(s)
    return out


def _inserted_sentences(original: str, refined: str) -> list[str]:
    """Sentences present in *refined* but absent from *original*.

    ``full_paper.draft.tex`` (the pre-refine copy) is written by this tool and
    was read by NOTHING, and `difflib` had zero uses anywhere in ari-core or the
    skills — so the one artifact that makes an insertion trivially detectable
    went unused. This is that diff.
    """
    import difflib

    before = _sentences_of(original)
    after = _sentences_of(refined)
    seen = {re.sub(r"\W+", "", s).lower() for s in before}
    out: list[str] = []
    for s in after:
        if re.sub(r"\W+", "", s).lower() in seen:
            continue
        # A close match is a rewording (allowed); only genuinely new prose counts.
        if difflib.get_close_matches(s, before, n=1, cutoff=0.75):
            continue
        out.append(s)
    return out


def _unrequested_process_claims(inserted: list[str], revisions: list) -> list[str]:
    """Inserted sentences claiming a verification that no revision asked for."""
    asked = " ".join(
        str((r or {}).get("replacement", "")) + " " + str((r or {}).get("suggestion", ""))
        for r in (revisions or []) if isinstance(r, dict)
    ).lower()
    out = []
    for s in inserted:
        if not _PROCESS_CLAIM_RE.search(s):
            continue
        # If the reviewer literally asked for this wording, it is requested.
        if asked and re.sub(r"\W+", "", s).lower()[:60] in re.sub(r"\W+", "", asked):
            continue
        out.append(s)
    return out


_CLAIM_COMMENT_RE = re.compile(r"%\s*CLAIM:C\w+:NC\w+[^\r\n]*")
_FIGURE_BLOCK_RE = re.compile(
    r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}",
    re.DOTALL,
)
_FIGURE_GRAPHIC_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}"
)


def _claim_comment_contract(text: str):
    """Return the multiset of exact scientific claim comments in *text*.

    An anchor identity alone is insufficient: a forward declaration also owns
    its ``metric=``, ``formula=``, and operand tokens.  Keeping only
    ``% CLAIM:Cx:NCx`` silently turns a reproducible assertion into an unresolved
    one.  Counts matter because the same assertion may be anchored in both the
    abstract and results.
    """
    from collections import Counter

    return Counter(match.group(0).rstrip() for match in _CLAIM_COMMENT_RE.finditer(text))


def _preserves_claim_comment_contract(before: str, after: str) -> bool:
    """Whether *after* retains every exact claim comment from *before*."""

    required = _claim_comment_contract(before)
    actual = _claim_comment_contract(after)
    return all(actual[comment] >= count for comment, count in required.items())


def _figure_block_contract(text: str):
    """Return the exact multiset of renderer-owned figure environments."""
    from collections import Counter

    return Counter(match.group(0) for match in _FIGURE_BLOCK_RE.finditer(text))


def _preserves_figure_block_contract(before: str, after: str) -> bool:
    """Figures are immutable: no block may be changed, added, or removed."""

    return _figure_block_contract(before) == _figure_block_contract(after)


def _restore_authoritative_figure_snippets(text: str, snippets) -> str:
    """Replace model-written figure blocks with exact FigureBatch snippets.

    Matching is by the recorded ``includegraphics`` path, with basename as a
    compatibility fallback. Duplicate occurrences are removed and missing
    figures are inserted before Conclusion (or the bibliography). Paths,
    captions, values, and labels therefore stay owned by the fixed renderer.
    """

    records: list[tuple[str, str, str]] = []
    for raw in snippets or ():
        snippet = str(raw or "").strip()
        graphic = _FIGURE_GRAPHIC_RE.search(snippet)
        if not snippet or graphic is None:
            continue
        path = graphic.group(1)
        records.append((path, os.path.basename(path), snippet))
    if not records:
        return text

    by_path = {record[0]: record for record in records}
    by_basename = {record[1]: record for record in records}
    seen: set[str] = set()

    def _replace_block(match):
        block = match.group(0)
        graphic = _FIGURE_GRAPHIC_RE.search(block)
        if graphic is None:
            return block
        candidate = graphic.group(1)
        record = by_path.get(candidate) or by_basename.get(os.path.basename(candidate))
        if record is None:
            return block
        path, _basename, snippet = record
        if path in seen:
            return ""
        seen.add(path)
        return snippet

    restored = _FIGURE_BLOCK_RE.sub(_replace_block, text)
    missing = [record for record in records if record[0] not in seen]
    for path, basename, _snippet in missing:
        # Remove a bare model-written include of the same asset before adding
        # its complete, authoritative environment.
        restored = _FIGURE_GRAPHIC_RE.sub(
            lambda match: (
                ""
                if match.group(1) == path
                or os.path.basename(match.group(1)) == basename
                else match.group(0)
            ),
            restored,
        )
    if missing:
        insertion = "\n\n".join(record[2] for record in missing)
        marker = next(
            (
                candidate
                for candidate in (
                    "\\section{Conclusion}",
                    "\\bibliographystyle",
                    "\\bibliography",
                    "\\end{document}",
                )
                if candidate in restored
            ),
            "",
        )
        if marker:
            restored = restored.replace(marker, insertion + "\n\n" + marker, 1)
        else:
            restored = restored.rstrip() + "\n\n" + insertion + "\n"
    return restored


def _escape_text_underscores(text: str) -> str:
    """Escape bare underscores in LaTeX text mode. Skips command args and math."""
    import re as _re_esc

    result = []
    i = 0
    while i < len(text):
        # Check if inside a command arg that should not be escaped
        if text[i] == "\\" and i + 1 < len(text):
            cmd_end = i + 1
            while cmd_end < len(text) and text[cmd_end].isalpha():
                cmd_end += 1
            cmd_name = text[i + 1 : cmd_end]
            result.append(text[i:cmd_end])
            i = cmd_end
            # If command name is empty and next char is _ ^ $ # etc, it's already escaped — pass through
            if not cmd_name and i < len(text) and text[i] in "_^$#&%~|":
                result.append(text[i])
                i += 1
                continue
            # \( ... \) and \[ ... \] math: skip verbatim (only $...$ was
            # recognized before, so \(k_p\) in plain prose got corrupted to
            # \(k\_p\) — literal underscore instead of a subscript).
            if not cmd_name and i < len(text) and text[i] in "([":
                closer = "\\)" if text[i] == "(" else "\\]"
                end = text.find(closer, i + 1)
                if end >= 0:
                    result.append(text[i : end + 2])
                    i = end + 2
                else:
                    result.append(text[i])
                    i += 1
                continue
            # \begin{<math env>} ... \end{<math env>}: skip the body verbatim
            # (same math contract; subscripts there were corrupted the same way).
            if cmd_name == "begin" and i < len(text) and text[i] == "{":
                _m_env = _re_esc.match(r"\{([A-Za-z]+\*?)\}", text[i:])
                if _m_env and _m_env.group(1).rstrip("*") in _MATH_ENV_NAMES:
                    _closer = "\\end{" + _m_env.group(1) + "}"
                    _end = text.find(_closer, i + _m_env.end())
                    if _end >= 0:
                        result.append(text[i : _end + len(_closer)])
                        i = _end + len(_closer)
                        continue
                # not a math env (or unclosed): generic arg protection below
            # For label/ref/cite/eqref: include the {} arg without escaping
            if cmd_name in (
                "label",
                "ref",
                "eqref",
                "cite",
                "pageref",
                "autoref",
                "hyperref",
                "nameref",
                "vref",
                "cref",
                "Cref",
                "includegraphics",
                "bibliography",
                "bibliographystyle",
            ):
                # Handle optional [...] before {}, e.g. \includegraphics[width=...]{file}
                if i < len(text) and text[i] == "[":
                    _d = 1
                    result.append("[")
                    i += 1
                    while i < len(text) and _d > 0:
                        if text[i] == "[":
                            _d += 1
                        elif text[i] == "]":
                            _d -= 1
                        result.append(text[i])
                        i += 1
                if i < len(text) and text[i] == "{":
                    depth = 1
                    result.append("{")
                    i += 1
                    while i < len(text) and depth > 0:
                        if text[i] == "{":
                            depth += 1
                        elif text[i] == "}":
                            depth -= 1
                        result.append(text[i])
                        i += 1
            elif text[i : i + 1] in ("[", "{"):
                # Other commands: also protect their arguments
                depth = 1
                result.append(text[i])
                i += 1
                while i < len(text) and depth > 0:
                    if text[i] in ("{", "["):
                        depth += 1
                    elif text[i] in ("}", "]"):
                        depth -= 1
                    result.append(text[i])
                    i += 1
            continue
        if text[i] == "$":
            # Check if this is an escaped dollar \$ (literal, not math mode)
            if i > 0 and text[i - 1] == "\\":
                # Already appended '\\' — just append '$' as literal
                result.append("$")
                i += 1
                continue
            # Skip math mode: find matching closing $
            if text[i + 1 : i + 2] == "$":
                end = text.find("$$", i + 2)
                if end < 0:
                    # Unclosed $$: emit as literal \$ to avoid LaTeX errors
                    result.append("\\$")
                    i += 1
                    continue
                result.append(text[i : end + 2])
                i = end + 2
            else:
                end = text.find("$", i + 1)
                if end < 0:
                    # Unclosed $: emit as literal \$ to avoid Missing $ LaTeX error
                    result.append("\\$")
                    i += 1
                    continue
                result.append(text[i : end + 1])
                i = end + 1
            continue
        if text[i] == "_":
            result.append("\\_")
            i += 1
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


_BFTS_TERM_MAP = {
    "node label": "compiler configuration",
    "node labels": "compiler configurations",
    "colored by label": "colored by flag set",
    "by label": "by configuration",
    "search tree depth": "configuration index",
    "tree depth": "configuration index",
    "Tree Depth": "Configuration Index",
    "search step": "configuration index",
    "per-depth": "per-group",
    "BFTS": "",
    "bfts": "",
    "improve": "high-performance",
    "validation": "verified",
    "ablation": "baseline",
    "draft": "initial",
    "experiment workflow": "systematic evaluation",
    "exploration depth": "number of configurations evaluated",
}


def _sanitize_bfts_terms(text: str) -> str:
    """Remove BFTS-internal terms from paper-facing text (captions, body)."""
    for old, new in _BFTS_TERM_MAP.items():
        text = text.replace(old, new)
    return text


def _build_latex_template(
    venue_info: dict,
    refs_json: str = "",
    figures: list = None,  # list of {"basename": ..., "caption": ..., "latex": ...}
    author_name: str = "",
    experiment_summary: str = "",
) -> str:
    """Build a LaTeX template scaffold for Option A (template-fill) approach.

    The template pre-places:
      - All section/subsection headers
      - Figure environments at their natural positions (Results subsection)
      - cite{} placeholders in the reference section
      - FILL_<SECTION> markers for the LLM to replace

    The LLM receives the full template and fills in all sections at once,
    so figure placement and citation context are always visible.
    """
    _author = author_name.strip() or "Autonomous Research Infrastructure"
    figures = figures or []

    # Build BibTeX cite key list for the template
    _bib_content, _bib_keys = _build_bib_content(refs_json)
    cite_list_str = ""
    if _bib_keys:
        cite_list_str = (
            "% ══ AVAILABLE CITE KEYS (EXHAUSTIVE LIST) ══\n"
            "% YOU MUST USE ONLY THESE EXACT KEYS in \\cite{} commands.\n"
            "% DO NOT invent, guess, or modify any cite key. DO NOT use \\cite{key}.\n"
            "% If a fact has no matching key below, do NOT cite it — omit the citation entirely.\n"
            + "\n".join(
                f"% \\cite{{{k}}}  — {title[:80]}" for k, title in _bib_keys[:20]
            )
            + "\n% ══ END OF AVAILABLE KEYS ══"
        )

    # Build figure environments for pre-placement
    fig_environments = ""
    for j, f in enumerate(figures, 1):
        if f.get("latex"):
            fig_environments += f.get("latex") + "\n\n"
        else:
            fig_environments += (
                f"\\begin{{figure}}[htbp]\n"
                f"  \\centering\n"
                f"  \\includegraphics[width=0.85\\linewidth]{{{f['basename']}}}\n"
                f"  \\caption{{{f['caption']}}}\n"
                f"  \\label{{fig:{j}}}\n"
                f"\\end{{figure}}\n\n"
            )

    first_figure_label = "fig:1"
    if figures:
        label_match = re.search(
            r"\\label\{([^}]*)\}",
            figures[0].get("latex", ""),
        )
        if label_match:
            first_figure_label = label_match.group(1)

    # Title hint from experiment summary
    _title_hint = (
        experiment_summary.split("\n")[0][:100].strip()
        if experiment_summary
        else "Research Paper"
    )

    template = f"""\\documentclass[11pt]{{article}}
\\usepackage{{geometry,booktabs,hyperref,amsmath,amssymb,graphicx,float,caption,natbib}}
\\geometry{{margin=2.5cm}}
\\graphicspath{{{{figures/}}{{./}}}}

% ============================================================
% INSTRUCTIONS FOR THE LLM:
% Replace every FILL_<SECTION>_END block with real LaTeX content.
% Do NOT remove \\section headers. Do NOT move figure environments.
% Use \\cite{{key}} for citations — see available keys below.
% {cite_list_str}
% ============================================================

\\title{{\\textbf{{FILL_TITLE_START
{_title_hint}
FILL_TITLE_END}}}}
\\author{{{_author}}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

\\begin{{abstract}}
FILL_ABSTRACT_START
Write a 150-word abstract summarising motivation, method, results.
FILL_ABSTRACT_END
\\end{{abstract}}

\\section{{Introduction}}
FILL_INTRODUCTION_START
Motivate the problem, state key contributions (2-3 bullet points), cite 2 related papers.
FILL_INTRODUCTION_END

\\section{{Related Work}}
FILL_RELATED_WORK_START
Survey prior work on this topic. Cite at least 3 papers using \\cite{{key}}.
FILL_RELATED_WORK_END

\\section{{Methodology}}
FILL_METHOD_START
Describe the approach, algorithm, and experimental setup in detail.
FILL_METHOD_END

\\section{{Experiments and Results}}
\\subsection{{Setup}}
FILL_EXPERIMENT_SETUP_START
Describe hardware, software environment, and benchmark.
FILL_EXPERIMENT_SETUP_END

\\subsection{{Results}}
FILL_RESULTS_START
Present quantitative results. Reference Figure~\\ref{{{first_figure_label}}} below.
FILL_RESULTS_END

{fig_environments}

\\section{{Conclusion}}
FILL_CONCLUSION_START
Summarise contributions, limitations, and future work. Cite 1-2 papers.
FILL_CONCLUSION_END

\\bibliographystyle{{plainnat}}
\\bibliography{{refs}}

\\end{{document}}
"""
    return template


def _fill_template_with_llm_output(template: str, llm_latex: str) -> str:
    """Merge LLM-filled content back into the template structure.

    If the LLM returned a complete LaTeX document, use it directly (preferred).
    Otherwise attempt to extract FILL blocks from template.
    """
    import re as _re_ft

    # LLM returned a complete document — use it
    if "\\begin{document}" in llm_latex and "\\end{document}" in llm_latex:
        return llm_latex
    if "\\documentclass" in llm_latex:
        return llm_latex
    # Fallback: replace FILL markers with LLM output
    result = template
    # Remove remaining FILL_*_START ... FILL_*_END markers
    result = _re_ft.sub(
        r"FILL_[A-Z_]+_START.*?FILL_[A-Z_]+_END",
        llm_latex[:200],  # use beginning of LLM output as best guess
        result,
        flags=_re_ft.DOTALL,
        count=1,
    )
    return result


def _extract_metric_keyword(text: str) -> str:
    """Extract metric keyword from <!-- metric_keyword: X --> HTML comment."""
    import re as _re

    m = _re.search(r"<!--\s*metric_keyword:\s*(\S+)\s*-->", text)
    return m.group(1) if m else "metric"


@mcp.tool()
async def write_paper_iterative(
    workspace_root: str,
    science_data_path: str,
    figures_manifest_path: str,
    references_path: str,
    ear_manifest_path: str,
    rubric_id: str,
    experiment_summary: str = "",
    context: str = "",  # alias for experiment_summary (used by pipeline.py)
    verified_context_path: str = "",
    venue: str = "arxiv",
    max_revision_rounds: int = 2,
    author_name: str = "",  # config-specified author; defaults to "Autonomous Research Infrastructure"
    writer_prompt_override: str = "",  # "" => load paper_writer.md (linear byte-identical);
                                       # non-empty => the governed paper_writer prompt DRIVES
                                       # the reflection instruction (docs/plans/ari_rqgm_paper/03
                                       # §5.8). The skill still evolves nothing and imports no
                                       # ari.rqgm — a plain instruction string, not governance.
    decode_seed: int = 0,  # 0 => no seed in the payload => byte-identical to today (linear);
                           # non-zero => sampled under that seed, so callers generating a
                           # POPULATION of drafts get distinct samples instead of K copies
                           # (docs/plans/ari_rqgm_paper/02 §5.4 decision 5). Same additive
                           # on-ramp shape as writer_prompt_override: a plain scalar, no
                           # ari.rqgm import, no governance. NOTE: litellm `seed` is
                           # best-effort and provider-dependent — it delivers diversity
                           # (distinct seeds => distinct samples), not bit-exact replay.
) -> dict:
    """AI Scientist v2-style iterative paper writing agent.

    Runs a research -> draft -> review -> revise loop for each section.

    Flow per section:
      1. Research: gather evidence from nodes_tree + arXiv refs
      2. Draft section (LLM)
      3. Review (LLM critic) -> accept_recommendation
      4. If weak_accept or reject: revise with feedback
      5. Repeat up to max_revision_rounds
    Then compile all sections into a full paper.

    Args:
        experiment_summary: Experiment context and best results
        workspace_root: Closed checkpoint root containing all input artifacts.
        science_data_path: Native ScienceDataV1 path under the workspace.
        figures_manifest_path: Native FigureBatchV1 path under the workspace.
        references_path: Recorded retrieval-result path under the workspace.
        ear_manifest_path: EAR generation result path under the workspace.
        venue: Target venue
        max_revision_rounds: Max revisions per section

    Returns:
        latex, sections, reviews, revision_counts
    """
    import traceback as _tb_wpi

    try:
        import json

        _authoring_inputs = load_authoring_inputs(
            workspace_root=workspace_root,
            science_data_path=science_data_path,
            figures_manifest_path=figures_manifest_path,
            references_path=references_path,
            ear_manifest_path=ear_manifest_path,
            verified_context_path=verified_context_path,
        )
        _authoring_recorder = AuthoringRecorder(_authoring_inputs)
        science_data_json = _authoring_inputs.science_payload.decode("utf-8")
        figures_manifest_json = _authoring_inputs.figures_payload.decode("utf-8")
        refs_json = json.dumps(_authoring_inputs.references, ensure_ascii=False)
        refs_json = json.dumps(
            _resolve_retrieval_refs(
                _authoring_inputs.references,
                checkpoint=_authoring_inputs.workspace.root,
            ),
            ensure_ascii=False,
        )
        _rubric_contract = load_rubric(rubric_id)
        # Accept context as alias for experiment_summary (pipeline.py compat)
        if not experiment_summary and context:
            experiment_summary = context

        # Enrich only from the validated native ScienceDataV1.  The former
        # node-tree metric fallback bypassed units and claim eligibility.
        if science_data_json and _authoring_inputs.manuscript_binding is None:
            try:
                from ari.public.science_data import science_data_projection

                _sd_native = _authoring_inputs.science.model_dump(mode="json")
                _sd = science_data_projection(_sd_native)
                _interpretation = _sd_native.get("interpretation") or {}
                _sd_ctx = (
                    _interpretation.get("experiment_context", {})
                    if _interpretation.get("status") == "ok"
                    else {}
                )

                # 1. Per-configuration results (FIRST — highest priority).
                # Each configuration has different parameters; the LLM must
                # associate each claimed number with its exact parameters.
                _configs = _sd.get("configurations", [])
                if _configs:
                    _cfg_parts = []
                    for _cfg in _configs[:10]:
                        _cfg_parts.append(json.dumps(_cfg, ensure_ascii=False))
                    # Some configurations carry a typed split (params /
                    # measurements / predictions / scores) sourced from the
                    # coding-skill's emit_results contract or the LLM
                    # evaluator's split. When present, use those — they
                    # are authoritative and disambiguate inputs (matrix
                    # size, threads) from outcomes (GFlops/s, accuracy).
                    # Fall back to the flat ``metrics`` view only when the
                    # typed fields are absent.
                    experiment_summary += (
                        "\n\nPER-CONFIGURATION RESULTS (each entry shows the exact "
                        "parameters and metrics for one experiment — when reporting "
                        "a number, state the parameters from the SAME entry).\n"
                        "Field semantics for each entry:\n"
                        "  parameters  — INPUT knobs the run used (matrix size, "
                        "thread count, seeds). Cite these as the configuration. "
                        "NEVER quote them as the experiment's headline result.\n"
                        "  measurements — MEASURED outputs (throughput, accuracy, "
                        "latency). These are the values that go in the abstract / "
                        "results section.\n"
                        "  predictions  — model-derived ceilings (e.g. roofline "
                        "compute peak). Useful for context, not as results.\n"
                        "  scores       — derived ratios (efficiency, speedup).\n"
                        "  metrics      — back-compat flat union; prefer the typed "
                        "fields above when they are populated.\n"
                        "  _anomalous_metrics — names flagged as physically-impossible "
                        "/ invalid by the correctness gate (e.g. a normalized value > 1). "
                        "NEVER quote these as results: they are unsound and the final "
                        "paper is blocked if they appear.\n"
                        "Entries:\n" + "\n".join(_cfg_parts)
                    )

                # 2. Implementation details (data structures, build config, etc.)
                _impl_det = _sd_ctx.get("implementation_details", {})
                if _impl_det:
                    experiment_summary += (
                        "\n\nIMPLEMENTATION DETAILS (from science_data analysis):\n"
                        + json.dumps(_impl_det, indent=2, ensure_ascii=False)[:4000]
                    )

                # 2b. Hardware/software environment. Source changed: the
                # framework no longer auto-scrapes host machine info into
                # node_report (that leaked the hostname/partition). It is now
                # AGENT-AUTHORED — the agent records the toolchain/hardware it
                # used in node_report's ``environment`` field (grounded in tool
                # output). Prefer the aggregated ``hardware`` key when the
                # science_data step provides it, else the agent ``environment``
                # note; omit the section (do not fabricate) when neither exists.
                _hw = _sd_ctx.get("hardware", "") or _sd_ctx.get("environment", "")
                if _hw:
                    if isinstance(_hw, dict):
                        _hw_text = json.dumps(_hw, indent=2, ensure_ascii=False)
                    else:
                        _hw_text = str(_hw)
                    experiment_summary += (
                        "\n\nHARDWARE/SOFTWARE ENVIRONMENT (factual capture from "
                        "experiment runtime — write a concrete description in the "
                        "paper using these values, do NOT write 'not recorded' "
                        "if any value is present here):\n" + _hw_text[:2500]
                    )

                # 3. Source code from best nodes (last — longest section).
                _best_src = _sd_ctx.get("_best_node_source_code", {})
                if _best_src:
                    _src_parts = []
                    _src_total = 0
                    for _label, _code in _best_src.items():
                        if _src_total + len(_code) > 32000:
                            break
                        _src_parts.append(f"── {_label} ──\n{_code}")
                        _src_total += len(_code)
                    if _src_parts:
                        experiment_summary += (
                            "\n\nACTUAL SOURCE CODE from experiment nodes "
                            "(use these to write ACCURATE pseudocode that exactly "
                            "matches the structure of this code):\n"
                            + "\n\n".join(_src_parts)
                        )

                # 4. Research Contract claims registry (Story2Proposal Phase A2).
                # Surface candidate claims so the writer references them by id and
                # anchors each numeric result with % CLAIM:Cx:NCx. Values are
                # deterministic and re-verified by the hard gate.
                _claims = _sd.get("claims", []) if isinstance(_sd, dict) else []
                if _claims:
                    _cl_parts = []
                    for _cl in _claims[:20]:
                        if not isinstance(_cl, dict):
                            continue
                        _nas = _cl.get("numeric_assertions", []) or []
                        _na_str = "; ".join(
                            f"{_na.get('id')}: {_na.get('metric')}="
                            f"{_na.get('value')}{_na.get('unit', '')} ({_na.get('formula')})"
                            for _na in _nas
                            if isinstance(_na, dict)
                        )
                        _cl_parts.append(
                            f"- {_cl.get('id')} [{_cl.get('section', 'results')}]: "
                            f"{_cl.get('text', '')}"
                            + (
                                f"\n    numeric_assertions: {_na_str}"
                                if _na_str
                                else ""
                            )
                        )
                    if _cl_parts:
                        experiment_summary += (
                            "\n\nRESEARCH CONTRACT — CANDIDATE CLAIMS (reference these by id; "
                            "when you state one of these numeric results in the text, put a "
                            "LaTeX comment anchor `% CLAIM:Cx:NCx` on the line immediately "
                            "before that sentence, using the claim id Cx and numeric assertion "
                            "id NCx shown below. Only anchor numeric RESULT claims, not years, "
                            "figure/table indices, or experimental settings. Keep the reported "
                            "numbers consistent with the values below — they are re-verified "
                            "deterministically against the executed results):\n"
                            + "\n".join(_cl_parts)
                        )

                # Forward-declaration table (Story2Proposal (c)): stable config
                # handles the writer can reference to DECLARE every result number
                # it states, so the hard gate verifies the derivation forward.
                _cfg_nodes = (
                    _sd.get("_config_nodes", {}) if isinstance(_sd, dict) else {}
                )
                if _cfg_nodes:

                    def _fmt_mets(_m):
                        if isinstance(_m, dict):
                            return ", ".join(
                                f"{k}={round(v, 4)}" for k, v in list(_m.items())[:26]
                            )
                        return ", ".join((_m or [])[:26])  # back-compat (keys only)

                    _cfg_lines = []
                    for _cfgid, _cn in list(_cfg_nodes.items())[:20]:
                        _envd = _cn.get("environment", {}) or {}
                        _envs = f"{_envd.get('cpu_model', '?')}/{_envd.get('executor', '?')}"
                        _cfg_lines.append(
                            f"  {_cfgid} [env {_envs}]: {_fmt_mets(_cn.get('metrics'))}"
                        )
                    experiment_summary += (
                        "\n\n"
                        + _load_prompt("forward_declaration")
                        + "\n"
                        + "\n".join(_cfg_lines)
                    )
            except Exception as _e_sd:
                log.warning("Failed to extract science_data context: %s", _e_sd)

        # Parse figures manifest and append to experiment_summary for LLM context
        if figures_manifest_json:
            try:
                import json as _json

                figs = _json.loads(figures_manifest_json)
                fig_lines = []
                # Handle both list [{filename,caption}] and dict {"fig_1": "/path", ...} formats
                figs_raw = figs if isinstance(figs, list) else figs.get("figures", figs)
                # Extract latex_snippets (authoritative captions from plot-skill)
                _latex_snips = (
                    figs.get("latex_snippets", {}) if isinstance(figs, dict) else {}
                )
                if isinstance(figs_raw, dict):
                    for i, (k, v) in enumerate(figs_raw.items()):
                        import os as _os_fig

                        fname_base = _os_fig.path.basename(str(v))
                        # Use real caption from latex_snippets if available
                        _snip = _latex_snips.get(k, "")
                        cap_m = re.search(
                            r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}", _snip
                        )
                        cap = (
                            cap_m.group(1)
                            if cap_m
                            else f"Figure {i + 1}: Experimental results for {k}. See text for analysis."
                        )
                        label_m = re.search(r"\\label\{([^}]*)\}", _snip)
                        fig_lines.append(
                            {
                                "path": str(v),
                                "basename": fname_base,
                                "caption": cap,
                                "latex": _snip,
                                "label": (
                                    label_m.group(1) if label_m else f"fig:{i + 1}"
                                ),
                            }
                        )
                else:
                    for fig in figs_raw if isinstance(figs_raw, list) else []:
                        fname = (
                            fig.get("filename", "")
                            if isinstance(fig, dict)
                            else str(fig)
                        )
                        cap = fig.get("caption", "") if isinstance(fig, dict) else ""
                        if fname:
                            import os as _os_fig2

                            fig_lines.append(
                                {
                                    "path": fname,
                                    "basename": _os_fig2.path.basename(fname),
                                    "caption": cap,
                                    "latex": "",
                                    "label": f"fig:{len(fig_lines) + 1}",
                                }
                            )
                if fig_lines:
                    # Give LLM authoritative LaTeX snippets to embed in Experiments section
                    ctx_lines = [
                        "\n\nExperiment figures — embed these INSIDE the Experiments/Results section body. "
                        "Copy the LaTeX snippet exactly as shown (with \\label and \\caption):"
                    ]
                    for j, f in enumerate(fig_lines, 1):
                        if f.get("latex"):
                            # Give complete LaTeX figure environment
                            ctx_lines.append(f"  Figure {j} ({f['basename']}):")
                            ctx_lines.append("  " + f["latex"][:400])
                        else:
                            ctx_lines.append(
                                f"  Figure {j}: filename={f['basename']}, caption={f['caption']!r}. "
                                f"Use \\begin{{figure}}[htbp]\\centering\\includegraphics[width=0.9\\linewidth]{{{f['basename']}}}\\caption{{{f['caption']}}}\\label{{fig:{j}}}\\end{{figure}}"
                            )
                        ctx_lines.append(
                            f"  Reference inline as: Figure~\\ref{{{f['label']}}}"
                        )
                    experiment_summary += "\n".join(ctx_lines)
            except Exception as _ef:
                log.warning("Figure manifest parse failed: %s", _ef)
        # Strip HTML comments (e.g. <!-- metric_keyword: ... -->) from experiment_summary
        # Strip HTML comments without regex
        while "<!--" in experiment_summary and "-->" in experiment_summary:
            s = experiment_summary.find("<!--")
            e = experiment_summary.find("-->", s)
            if s < 0 or e < 0:
                break
            experiment_summary = experiment_summary[:s] + experiment_summary[e + 3 :]
        experiment_summary = experiment_summary.strip()

        # ──────────────────────────────────────────────────────────────────────
        # OPTION A: LaTeX Template Approach (AI Scientist v2-style)
        # Build a full LaTeX scaffold with all section headers, figure placements,
        # and cite key hints pre-inserted — then ask the LLM to fill ALL sections
        # in a single call. This avoids the figure/citation placement problems
        # of the section-by-section approach.
        # ──────────────────────────────────────────────────────────────────────
        venue_info = next((v for v in VENUES if v["id"] == venue), None)
        if venue_info is None:
            raise ValueError(f"unknown versioned paper venue: {venue}")
        _author_display = (
            author_name.strip()
            if author_name.strip()
            else "Autonomous Research Infrastructure"
        )

        # Parse figures list for template
        _figs_for_tpl = []
        if figures_manifest_json:
            try:
                import json as _jft

                _fmc_t = (
                    _jft.loads(figures_manifest_json)
                    if isinstance(figures_manifest_json, str)
                    else figures_manifest_json
                )
                _figs_raw_t = (
                    _fmc_t.get("figures", _fmc_t) if isinstance(_fmc_t, dict) else {}
                )
                _snips_t = (
                    _fmc_t.get("latex_snippets", {}) if isinstance(_fmc_t, dict) else {}
                )
                if isinstance(_figs_raw_t, dict):
                    for _ki, _vi in _figs_raw_t.items():
                        _bn = str(_vi)
                        _snip = _snips_t.get(_ki, "")
                        _cap_m = re.search(
                            r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}", _snip
                        )
                        _cap = _sanitize_bfts_terms(
                            _cap_m.group(1)
                            if _cap_m
                            else f"Experimental results for {_ki}. See text for analysis."
                        )
                        _label_m = re.search(r"\\label\{([^}]*)\}", _snip)
                        _figs_for_tpl.append(
                            {
                                "basename": _bn,
                                "caption": _cap,
                                "latex": _snip,
                                "label": (
                                    _label_m.group(1) if _label_m else ""
                                ),
                            }
                        )
            except Exception as _et:
                log.warning("Template figures parse failed: %s", _et)

        # Build the LaTeX template scaffold
        latex_template = _build_latex_template(
            venue_info=venue_info,
            refs_json=refs_json,
            figures=_figs_for_tpl,
            author_name=_author_display,
            experiment_summary=experiment_summary,
        )
        _template_artifact = artifact_from_payload(
            _authoring_inputs.workspace,
            role="template",
            relative_path=f".ari-paper/contracts/{venue}-template.tex",
            payload=latex_template.encode("utf-8"),
            media_type="text/x-tex; charset=utf-8",
        )
        _rubric_payload = Path(_rubric_contract.source_path).read_bytes()
        _rubric_artifact = artifact_from_payload(
            _authoring_inputs.workspace,
            role="rubric",
            relative_path=f".ari-paper/contracts/{_rubric_contract.id}.yaml",
            payload=_rubric_payload,
            media_type="application/yaml",
        )

        # Build comprehensive context for the LLM
        refs_context = ""
        if refs_json and _authoring_inputs.manuscript_binding is None:
            try:
                _refs_data = (
                    json.loads(refs_json) if isinstance(refs_json, str) else refs_json
                )
                _papers = _refs_data.get("papers", [])
                _bib_ct, _bib_kt = _build_bib_content(refs_json)
                _key_map = {i: k for i, (k, _) in enumerate(_bib_kt)}
                lines = ["AVAILABLE REFERENCES (cite with \\cite{key}):"]
                for _ri, _rp in enumerate(_papers[:12], 1):
                    _rk = _key_map.get(_ri - 1, str(_ri))
                    lines.append(f"  \\cite{{{_rk}}}  {_rp.get('title', '')[:80]}")
                    lines.append(f"    {_rp.get('abstract', '')[:150]}")
                refs_context = "\n".join(lines)
            except Exception as _er:
                log.warning("Refs context failed: %s", _er)

        # Verified context was already loaded through the closed workspace.
        _grounded_block = ""
        if (
            _authoring_inputs.manuscript_binding is None
            and _authoring_inputs.verified_context is not None
        ):
            try:
                from ari.public.verified_context import render_grounded_block as _rgb

                _grounded_block = _rgb(_authoring_inputs.verified_context)
            except Exception as _e_vc:
                log.warning("verified context render failed: %s", _e_vc)

        # Single LLM call to fill the entire template
        _system_prompt_a = (
            f"You are an expert academic writer. Fill in ALL the FILL_*_START ... FILL_*_END "
            f"placeholder blocks in the provided LaTeX template. Target venue: {venue_info['name']}. "
            + _load_prompt("fill_in_writer")
            + (
                "\nVENUE RUBRIC AUTHOR GUIDANCE:\n"
                + _rubric_contract.author_hint.strip()
                + "\nEND VENUE RUBRIC AUTHOR GUIDANCE\n"
                if _rubric_contract.author_hint.strip()
                else ""
            )
            + _paper_language_directive()
            + _grounded_block
        )
        _user_prompt_a = (
            f"Experiment context:\n{experiment_summary[:48000]}\n\n"
            f"{refs_context}\n\n"
            f"Fill in this LaTeX template — replace ALL FILL blocks with real content:\n\n"
            f"```latex\n{latex_template}\n```"
        )
        _kw_a = {
            "model": _get_model(),
            "messages": [
                {"role": "system", "content": _system_prompt_a},
                {"role": "user", "content": _user_prompt_a},
            ],
            "temperature": 0.7,
            "max_tokens": 16384,
        }
        if decode_seed:
            _kw_a["seed"] = int(decode_seed)
        _apib_a = _get_api_base()
        if _apib_a:
            _kw_a["api_base"] = _apib_a
        _resp_a = await litellm.acompletion(**_kw_a)
        _raw_a = _resp_a.choices[0].message.content or ""
        _initial_call = _authoring_recorder.record_call(
            purpose="initial-authoring",
            prompt=_paper_json_bytes(
                {
                    "messages": _kw_a["messages"],
                    "temperature": _kw_a["temperature"],
                    "max_tokens": _kw_a["max_tokens"],
                }
            ),
            raw_response=_raw_a.encode("utf-8"),
            response=_resp_a,
            model=str(_kw_a["model"]),
            sampling={"temperature": _kw_a["temperature"]},
        )
        if "</think>" in _raw_a:
            _raw_a = _raw_a.split("</think>")[-1]
        full_latex = _extract_latex(_raw_a) or _fill_template_with_llm_output(
            latex_template, _raw_a
        )
        if not full_latex:
            full_latex = latex_template  # fallback to template with placeholders
        full_latex = _escape_text_underscores(full_latex)

        # Populate dummy sections/reviews dicts for compat with downstream code
        sections = {}
        reviews = {}
        revision_counts = {}
        log.info("Option A: template filled, %d chars", len(full_latex))

        # Build the exact bibliography admitted by the retrieval snapshot.
        bib_content, key_list = _build_bib_content(refs_json)
        # Remove cite keys not in bib to prevent undefined citation errors
        if bib_content:
            full_latex = _strip_invalid_cite_keys(full_latex, bib_content)

        # FigureBatch owns figure paths, captions, values, and labels. Restore
        # the entire environment even when the model kept the file but rewrote
        # its caption/label; omission-only repair was insufficient.
        _authoritative_figure_snippets = tuple(
            _authoring_inputs.figures.latex_snippets.values()
        )
        full_latex = _restore_authoritative_figure_snippets(
            full_latex,
            _authoritative_figure_snippets,
        )

        # ─── AI Scientist v2: compile + reflection loop
        # _msg_history starts with the assembled full paper so reflection LLM has context
        _system_prompt = (
            (writer_prompt_override or _load_prompt("paper_writer"))
            + _paper_language_directive()
        )
        # msg_history starts with the assembled full paper as 'assistant' turn
        # This mimics v2's approach where reflection LLM knows what it wrote
        _msg_history: list = [
            {
                "role": "user",
                "content": f"Write a scientific LaTeX paper for this experiment:\n{experiment_summary[:15000]}",
            },
            {"role": "assistant", "content": f"```latex\n{full_latex}\n```"},
        ]

        # Compile through the shared bounded execution contract.  The authoring
        # loop never launches subprocesses or guesses figure siblings itself.
        async def _compile_draft(latex_text: str):
            _authoring_inputs.workspace.atomic_write_text(
                "paper_preview.tex",
                latex_text,
            )
            _authoring_inputs.workspace.atomic_write_text("refs.bib", bib_content)
            outcome = await asyncio.to_thread(
                compile_project,
                workspace=_authoring_inputs.workspace,
                main_file="paper_preview.tex",
                bib_file="refs.bib" if bib_content else None,
                figures=_authoring_inputs.figures,
                output_pdf="full_paper.pdf",
                output_bbl="full_paper.bbl",
                timeout_seconds=90,
            )
            return (
                list(outcome.diagnostics[-3:]),
                "",
                outcome.bbl_path is not None,
                outcome,
            )

        _authoring_recorder.record_revision(
            tex=full_latex,
            bib=bib_content,
            reason="initial",
            call_id=_initial_call.call_id,
        )

        # Initial compile
        _errs, _chktex, _bbl_ok, _compile_outcome = await _compile_draft(full_latex)
        log.info("Initial compile: errors=%s bbl_ok=%s", _errs, _bbl_ok)

        # ── v2 reflection rounds (msg_history preserved) ──────────────────────────
        _n_reflections = max(
            1, max_revision_rounds
        )  # from workflow.yaml max_revision_rounds
        for _ri in range(_n_reflections):
            # Build figure usage info (v2 style)
            import re as _re_fig
            import os as _os_fig

            _refs_in_paper = set(
                _os_fig.path.basename(f)
                for f in _re_fig.findall(
                    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", full_latex
                )
            )
            _avail_figs: set = set()
            if figures_manifest_json:
                try:
                    import json as _jjr

                    _fmr = (
                        _jjr.loads(figures_manifest_json)
                        if isinstance(figures_manifest_json, str)
                        else figures_manifest_json
                    )
                    _avail_figs = set(
                        _os_fig.path.basename(str(v))
                        for v in (
                            (_fmr.get("figures", {}) or {}).values()
                            if isinstance(_fmr, dict)
                            else []
                        )
                    )
                except Exception:
                    pass
            _unused = sorted(_avail_figs - _refs_in_paper)
            _invalid = sorted(_refs_in_paper - _avail_figs)

            _reflection_prompt = (
                f"Reflection round {_ri + 1}/{_n_reflections}. Review the LaTeX you just wrote:\n"
                f"1) LaTeX compile errors and warnings (fix ALL): {_errs if _errs else 'none'}\n"
                f"2) BibTeX: {'OK (bibliography compiled)' if _bbl_ok else 'FAILED — refs.bib may be missing or cite keys mismatch. Do NOT try to fix this by replacing bibliography commands with thebibliography environment — the build system will handle BibTeX compilation.'}\n"
                f"3) Figures available but not referenced in paper: {_unused}\n"
                f"4) Figure references in paper that do not match available files: {_invalid}\n"
                f"5) chktex output (LaTeX style issues):\n```\n{_chktex}\n```\n"
                f"\nNote: if there are undefined \\ref{{}} warnings, fix the \\label{{}} names to match.\n"
                f"IMPORTANT: NEVER replace \\bibliographystyle{{...}} or \\bibliography{{refs}} with "
                f"\\begin{{thebibliography}}...\\end{{thebibliography}}. Keep BibTeX commands as-is.\n"
                f"SCIENTIFIC CONTRACT: preserve every existing `% CLAIM:Cx:NCx ...` "
                f"comment VERBATIM, including metric=, formula=, and operand tokens, "
                f"and preserve every occurrence. A revision that changes or drops one "
                f"will be rejected.\n"
                f"FIGURE CONTRACT: preserve every existing figure environment "
                f"VERBATIM; renderer-owned paths, captions, values, and labels may "
                f"not be edited. A changed/added/removed figure block will be rejected.\n"
                f"If everything is correct, say: I am done\n"
                f"Otherwise, provide a revised complete LaTeX document in ```latex ... ``` fences.\n"
                f"Do NOT hallucinate results, hardware specs, or citations not in the provided data.\n"
                f"Return the ENTIRE file — no placeholders."
            )

            # Build messages with history (v2: same msg_history as initial writeup)
            _kw_ref: dict = {
                "model": _get_model(),
                "messages": [
                    {"role": "system", "content": _system_prompt},
                    *_msg_history,
                    {"role": "user", "content": _reflection_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 16384,
            }
            if decode_seed:
                _kw_ref["seed"] = int(decode_seed)
            _apib2 = _get_api_base()
            if _apib2:
                _kw_ref["api_base"] = _apib2
            try:
                _resp_r = await litellm.acompletion(**_kw_ref)
                _raw_r = _resp_r.choices[0].message.content or ""
                _reflection_call = _authoring_recorder.record_call(
                    purpose="reflection",
                    prompt=_paper_json_bytes(
                        {
                            "messages": _kw_ref["messages"],
                            "temperature": _kw_ref["temperature"],
                            "max_tokens": _kw_ref["max_tokens"],
                        }
                    ),
                    raw_response=_raw_r.encode("utf-8"),
                    response=_resp_r,
                    model=str(_kw_ref["model"]),
                    sampling={"temperature": _kw_ref["temperature"]},
                )
                if "</think>" in _raw_r:
                    _raw_r = _raw_r.split("</think>")[-1].strip()
                # Force continue if hard LaTeX errors still present (ignore "I am done")
                _still_has_errors = any(
                    "Missing $" in e or "Extra }" in e or "undefined" in e
                    for e in _errs
                )
                if "I am done" in _raw_r and not _still_has_errors:
                    log.info("v2 reflection %d: LLM says done", _ri + 1)
                    break
                _new_latex = _extract_latex(_raw_r)
                if _new_latex and bib_content:
                    _new_latex = _strip_invalid_cite_keys(_new_latex, bib_content)
                if _new_latex and len(_new_latex) > len(full_latex) * 0.7:
                    # v2 cleanup_map: fix common LLM LaTeX mistakes (from perform_writeup.py)
                    import re as _re_cleanup

                    _cleanup_map = {
                        "</end": r"\end",
                        "</begin": r"\begin",
                        "’": "'",
                    }
                    for _bad, _repl in _cleanup_map.items():
                        _new_latex = _new_latex.replace(_bad, _repl)
                    # v2: fix bare % in numbers (e.g., "5%" → "5\%")
                    _new_latex = _re_cleanup.sub(
                        r"(\d+(?:\.\d+)?)%", r"\1\\%", _new_latex
                    )
                    # Guard: if LLM replaced \bibliography{refs} with \begin{thebibliography},
                    # revert to BibTeX commands so the build pipeline can generate .bbl properly.
                    if r"\begin{thebibliography}" in _new_latex and bib_content:
                        _new_latex = _re_cleanup.sub(
                            r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
                            "\\bibliographystyle{plainnat}\n\\bibliography{refs}",
                            _new_latex,
                            flags=_re_cleanup.DOTALL,
                        )
                        log.warning(
                            "v2 reflection %d: reverted thebibliography to \\bibliography{refs}",
                            _ri + 1,
                        )
                    if not _preserves_claim_comment_contract(full_latex, _new_latex):
                        missing = _claim_comment_contract(full_latex) - _claim_comment_contract(
                            _new_latex
                        )
                        log.warning(
                            "v2 reflection %d: rejected revision that changed or dropped "
                            "%d scientific claim declaration(s)",
                            _ri + 1,
                            sum(missing.values()),
                        )
                        continue
                    if not _preserves_figure_block_contract(full_latex, _new_latex):
                        log.warning(
                            "v2 reflection %d: rejected revision that changed, added, "
                            "or dropped a renderer-owned figure block",
                            _ri + 1,
                        )
                        continue
                    full_latex = _new_latex
                    log.info(
                        "v2 reflection %d: updated latex (%d chars)",
                        _ri + 1,
                        len(full_latex),
                    )
                    # Update msg_history for next round
                    _msg_history.append({"role": "user", "content": _reflection_prompt})
                    _msg_history.append({"role": "assistant", "content": _raw_r})
                    _authoring_recorder.record_revision(
                        tex=full_latex,
                        bib=bib_content,
                        reason="reflection",
                        call_id=_reflection_call.call_id,
                    )
                    _errs, _chktex, _bbl_ok, _compile_outcome = await _compile_draft(
                        full_latex
                    )
                else:
                    log.warning(
                        "v2 reflection %d: LLM produced too-small output (%d chars), skipping",
                        _ri + 1,
                        len(_new_latex),
                    )
                    break
            except Exception as _re:
                log.warning("v2 reflection %d failed: %s", _ri + 1, _re)
                break
        # Compile diagnostics are complete content-addressed artifacts.  Keep
        # citation repair deterministic and limited to keys admitted by refs.bib.
        _undef_cites = [
            line
            for line in _compile_outcome.diagnostics
            if "Citation" in line and ("undefined" in line or "empty" in line)
        ]
        if not _bbl_ok or _undef_cites:
            log.warning(
                "Compile: bbl_ok=%s, undefined_cites=%s", _bbl_ok, _undef_cites[:3]
            )
            # Targeted fix: replace entire \cite{} group if keys unknown, keep rest of paper
            if _undef_cites and key_list:
                _valid_keys = [k for k, _ in key_list]

                def _replace_bad_cite(m):
                    # Keep only valid keys from the cite group
                    keys = [k.strip() for k in m.group(1).split(",")]
                    good = [k for k in keys if k in _valid_keys]
                    return (r"\cite{" + ", ".join(good) + "}") if good else ""

                import re as _re_cit

                full_latex = _re_cit.sub(
                    r"\\cite\{([^}]+)\}", _replace_bad_cite, full_latex
                )
                log.info("Filtered invalid cite keys; valid keys=%s", _valid_keys[:5])

        # Normalize bibliography name: LLM may write \bibliography{references} instead of {refs}
        import re as _re_bib2

        full_latex = _re_bib2.sub(
            r"\\bibliography\{[^}]+\}", r"\\bibliography{refs}", full_latex
        )
        # Ensure \end{document} is present (LLM fix or re-insertion may have stripped it)
        if "\\end{document}" not in full_latex:
            full_latex = full_latex.rstrip() + "\n\\end{document}\n"
            log.warning("Re-added missing \\end{document}")

        _authoring_recorder.record_revision(
            tex=full_latex,
            bib=bib_content,
            reason="refinement",
            call_id=None,
        )
        _draft_build = _authoring_recorder.draft_build(
            venue_id=venue,
            venue_version="ari-venue-template/v1",
            template_artifact=_template_artifact,
            rubric_id=_rubric_contract.id,
            rubric_version=_rubric_contract.version,
            rubric_artifact=_rubric_artifact,
            compile_record=_compile_outcome.record,
        )

        return {
            "latex": full_latex,
            "sections": sections,
            "reviews": reviews,
            "revision_counts": revision_counts,
            "bib": bib_content,
            "key_list": list(key_list),
            "paper_build": _draft_build.model_dump(mode="json"),
        }

    except Exception as _ewpi:
        import sys as _sys_wpi

        _sys_wpi.stderr.write(
            "=== write_paper_iterative TRACEBACK ===\n" + _tb_wpi.format_exc() + "\n"
        )
        _sys_wpi.stderr.flush()
        log.error("write_paper_iterative traceback:\n%s", _tb_wpi.format_exc())
        raise


async def _litellm_caller(
    messages: list[dict], temperature: float, model: str | None = None
) -> str:
    """LLM adapter used by review_engine to call the project's default backend."""
    import json as _json2  # noqa: F401

    _kw = {
        "model": model or _get_model("rubric"),
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": 8192,
    }
    panel_seed = os.environ.get("ARI_PANEL_SEED", "").strip()
    if panel_seed and panel_seed.lstrip("+").isdigit():
        _kw["seed"] = int(panel_seed)
    _apib = _get_api_base("rubric")
    if _apib:
        _kw["api_base"] = _apib
    _resp = await litellm.acompletion(**_kw)
    return _resp.choices[0].message.content or ""


def _extract_paper_artifacts(
    tex_path: str, pdf_path: str, figures_manifest_json: str
) -> tuple[str, list[str], list[dict], str]:
    """Shared preprocessing for all review flows.

    Returns (paper_text, captions, figures_info, citation_note).
    """
    import re as _re
    import json as _json
    import pathlib as _pl_rv

    # 1. Extract text from PDF
    pdf_text = ""
    if pdf_path:
        try:
            import fitz as _fitz

            _doc = _fitz.open(pdf_path)
            pdf_text = "\n".join(_page.get_text() for _page in _doc)
            _doc.close()
        except Exception as _fe:
            log.warning("pymupdf failed: %s", _fe)
        if not pdf_text:
            try:
                from pdfminer.high_level import extract_text as _pdfminer_extract

                pdf_text = _pdfminer_extract(pdf_path)
            except Exception as _pe:
                log.warning("pdfminer failed: %s", _pe)

    tex_text = ""
    if tex_path:
        try:
            tex_text = Path(tex_path).read_text()
        except Exception:
            pass

    review_text = pdf_text if pdf_text.strip() else tex_text

    # 2. Captions
    captions: list[str] = []
    if tex_text:
        for m in _re.finditer(r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}", tex_text):
            cap_text = m.group(1).strip()
            if len(cap_text) >= 10:
                captions.append(cap_text)

    # 3. Figures manifest
    figs_info: list[dict] = []
    if figures_manifest_json:
        try:
            figs_data = (
                _json.loads(figures_manifest_json)
                if isinstance(figures_manifest_json, str)
                else figures_manifest_json
            )
            raw = figs_data.get("figures", []) if isinstance(figs_data, dict) else []
            if isinstance(raw, list):
                figs_info = raw
            elif isinstance(raw, dict):
                figs_info = [{"name": k, "path": str(v)} for k, v in raw.items()]
        except Exception:
            pass

    # 4. Citation audit
    full_latex = (
        _pl_rv.Path(tex_path).read_text(errors="ignore")
        if tex_path and _pl_rv.Path(tex_path).exists()
        else ""
    )
    _active_latex = "\n".join(
        line
        for line in (full_latex or review_text).splitlines()
        if not line.lstrip().startswith("%")
    )
    _cite_calls = len(_re.findall(r"\\cite\{", _active_latex))
    _cite_keys_raw = _re.findall(r"\\cite\{([^}]+)\}", _active_latex)
    _unique_keys = set()
    for _ck in _cite_keys_raw:
        for _k in _ck.split(","):
            _k = _k.strip()
            if _k:
                _unique_keys.add(_k)
    _bbl_path = _pl_rv.Path(pdf_path).with_suffix(".bbl") if pdf_path else None
    _bbl_entries = 0
    if _bbl_path and _bbl_path.exists():
        _bbl_entries = _bbl_path.read_text(errors="ignore").count("\\bibitem")
    citation_note = (
        f"Unique cite keys used: {len(_unique_keys)}; "
        f"Total \\cite{{}} calls: {_cite_calls}; "
        f"Bibliography entries (.bbl): {_bbl_entries}."
    )
    return review_text, captions, figs_info, citation_note


def _parse_vlm_findings(vlm_findings_json: str) -> list[dict]:
    """Accept JSON string, list, or dict payload; return list of per-figure findings."""
    import json as _json

    if not vlm_findings_json:
        return []
    if isinstance(vlm_findings_json, list):
        return [f for f in vlm_findings_json if isinstance(f, dict)]
    try:
        data = _json.loads(vlm_findings_json)
    except Exception:
        return []
    if isinstance(data, list):
        return [f for f in data if isinstance(f, dict)]
    if isinstance(data, dict):
        figs = data.get("figures") or data.get("findings") or data.get("reviews")
        if isinstance(figs, list):
            return [f for f in figs if isinstance(f, dict)]
        # {figure_path: {score, issues...}} shape
        return [
            {"figure_path": k, **(v if isinstance(v, dict) else {})}
            for k, v in data.items()
        ]
    return []


@mcp.tool()
async def review_compiled_paper(
    rubric_id: str,
    tex_path: str = "",
    pdf_path: str = "",
    figures_manifest_json: str = "",
    experiment_summary: str = "",
    vlm_findings_json: str = "",
    num_reflections: int | None = None,
    num_fs_examples: int | None = None,
    num_reviews_ensemble: int | None = None,
) -> dict:
    """Rubric-driven compiled-paper review (single + ensemble + Area Chair meta).

    Runs N independent reviewer agents via the ensemble path. When N>1, also
    runs the Area Chair meta-review to aggregate divergent scores into a final
    decision. N=1 is equivalent to a single reviewer.

    Flow:
      1. Extract paper text (PDF → pymupdf/pdfminer/pdftotext; .tex fallback)
      2. Load the explicitly selected, versioned rubric
      3. Load few-shot examples (static from fewshot_dir, or dynamic OpenReview retrieval)
      4. Run N reviewers with temperature jitter; each does initial draft + reflection
      5. If N>1: run Area Chair meta-review
      6. Normalize to rubric schema (score_dimensions, text_sections, decision)

    Reviewer independence: VLM findings, experiment_summary, and figures_manifest
    are accepted for workflow-yaml backward compatibility but are NOT injected
    into the reviewer prompt. The VLM review is merged post-hoc by merge_reviews.

    N resolution: arg > $ARI_NUM_REVIEWS_ENSEMBLE > rubric.params.num_reviews_ensemble.

    Args:
        tex_path:              Path to full_paper.tex
        pdf_path:              Path to compiled full_paper.pdf
        figures_manifest_json: (ignored — kept for workflow.yaml compat)
        experiment_summary:    (ignored — kept for workflow.yaml compat)
        rubric_id:             Rubric id (see config/reviewer_rubrics/*.yaml for the full list)
        vlm_findings_json:     (ignored — kept for workflow.yaml compat; see merge_reviews)
        num_reflections:       Override rubric's default reflection rounds
        num_fs_examples:       Override rubric's default few-shot example count
        num_reviews_ensemble:  Override N (number of reviewer agents). Default: rubric / env.
    """
    import os as _os

    rubric = resolve_rubric(rubric_id)

    # num_reflections: explicit arg > env var > rubric default
    if num_reflections is not None:
        rubric.params.num_reflections = int(num_reflections)
    else:
        env_r = _os.environ.get("ARI_NUM_REFLECTIONS", "").strip()
        # Accept 0 (disable reflection) as well as positive ints
        if env_r and env_r.lstrip("+").isdigit():
            rubric.params.num_reflections = max(0, int(env_r))
    if num_fs_examples is not None:
        rubric.params.num_fs_examples = int(num_fs_examples)

    # N: explicit arg > env var > rubric default
    if num_reviews_ensemble is not None:
        n = int(num_reviews_ensemble)
    else:
        env_n = _os.environ.get("ARI_NUM_REVIEWS_ENSEMBLE", "").strip()
        n = (
            int(env_n)
            if env_n.isdigit() and int(env_n) >= 1
            else rubric.params.num_reviews_ensemble
        )
    rubric.params.num_reviews_ensemble = max(1, n)

    paper_text, captions, figs_info, citation_note = _extract_paper_artifacts(
        tex_path, pdf_path, figures_manifest_json
    )
    if not paper_text.strip():
        return {
            "error": "No paper text available for review",
            "rubric_id": rubric.id,
            "rubric_hash": rubric.hash,
            "overall_score": 0,
        }

    # Reviewer independence contract: VLM findings, experiment_summary, and
    # figures_manifest_json are NOT injected into the text reviewer's prompt.
    # The text reviewer evaluates paper text only, matching AI Scientist v2.
    # The VLM output (vlm_review.json) is merged post-hoc by merge_reviews.
    # We still accept vlm_findings_json / experiment_summary / figures_manifest_json
    # as arguments for workflow.yaml backward compatibility — they are ignored.
    _ = (vlm_findings_json, experiment_summary, figures_manifest_json)

    # Load few-shot examples (static default, dynamic if rubric requests + env allows)
    if rubric.params.fewshot_mode == "dynamic":
        title = paper_text.strip().split("\n", 1)[0][:200] if paper_text else ""
        abstract = paper_text[:2000]
        examples = load_dynamic_fewshot(rubric, title, abstract)
    else:
        examples = load_static_fewshot(rubric)

    user_prompt = build_user_prompt(rubric, paper_text, captions, citation_note)

    reviews = await run_ensemble(
        rubric,
        user_prompt,
        _litellm_caller,
        fewshot_examples=examples,
    )
    raw_evidence = []
    for review in reviews:
        raw_evidence.append(review.pop("_raw_responses", []))
    # Primary review (reviews[0]) is the top-level shape for consumers that
    # expect a single review dict. N=1 => pass-through; N>1 => primary doubles
    # as the headline review and the full list is attached as ensemble_reviews.
    primary = (
        reviews[0]
        if reviews
        else {
            "error": "ensemble returned no reviews",
            "rubric_id": rubric.id,
            "overall_score": 0,
        }
    )
    out: dict = dict(primary)
    out["rubric_id"] = rubric.id
    out["rubric_version"] = rubric.version
    out["rubric_hash"] = rubric.hash
    out["venue"] = rubric.venue
    out["n"] = len(reviews)
    out["fewshot_sources"] = [
        {"id": ex.paper_id, "source": ex.source} for ex in examples
    ]
    out["pdf_text_snippet"] = paper_text[:500]
    out["captions_found"] = captions
    if len(reviews) > 1:
        out["ensemble_reviews"] = reviews
        meta = await run_meta_review(rubric, reviews, _litellm_caller)
        raw_evidence.append([meta.pop("_raw_response", "")])
        meta["rubric_id"] = rubric.id
        meta["rubric_hash"] = rubric.hash
        meta["source_review_count"] = len(reviews)
        out["meta_review"] = meta
    from ari.public.execution import WorkspaceRefV1
    from ari.public.paper import canonical_paper_digest

    review_workspace = WorkspaceRefV1(root=str(Path(tex_path).resolve().parent))
    source_tex_digest = review_workspace.file_digest(tex_path)
    source_pdf_digest = (
        review_workspace.file_digest(pdf_path)
        if pdf_path and Path(pdf_path).is_file()
        else None
    )
    raw_artifact = artifact_from_payload(
        review_workspace,
        role="raw-model-response",
        relative_path=".ari-paper/text-review/raw-responses.json",
        payload=_paper_json_bytes(raw_evidence),
        media_type="application/json",
    )
    prompt_payload = _paper_json_bytes(
        {
            "system": build_system_prompt(rubric),
            "user": user_prompt,
            "rubric_hash": rubric.hash,
            "ensemble_size": len(reviews),
            "num_reflections": rubric.params.num_reflections,
        }
    )
    out.update(
        {
            "schema_version": "ari.paper-text-review/v1",
            "model": _get_model(),
            "model_revision": os.environ.get("ARI_MODEL_PAPER_REVISION") or None,
            "provider": os.environ.get("ARI_MODEL_PAPER_PROVIDER")
            or _get_model().split("/", 1)[0],
            "prompt_digest": canonical_paper_digest(
                json.loads(prompt_payload.decode("utf-8"))
            ),
            "paper_digest": canonical_paper_digest({"paper_text": paper_text}),
            "source_tex_digest": source_tex_digest,
            "source_pdf_digest": source_pdf_digest,
            "sampling": {"temperature": rubric.params.temperature},
            "raw_response_artifact": raw_artifact.model_dump(mode="json"),
        }
    )
    out["review_digest"] = canonical_paper_digest(out)
    return out


def _hard_gate_revisions(hard_gate: dict) -> list[dict]:
    """Turn blocking hard-gate errors into concrete refine instructions."""
    out: list[dict] = []
    findings = hard_gate.get("blocking_findings")
    if findings is None:  # supported published pre-v1 report reader
        findings = hard_gate.get("errors") or []
    for e in findings:
        t = e.get("type")
        details = e.get("details") if isinstance(e.get("details"), dict) else e
        sec = details.get("section", "")
        if t == "numeric_mismatch":
            out.append(
                {
                    "section": sec or "results",
                    "source": "hard_gate",
                    "instruction": (
                        f"Correct the reported number {details.get('reported')} so it matches the "
                        f"value re-computed from the executed results ({details.get('recomputed')}), "
                        f"or remove the unsupported claim."
                    ),
                }
            )
        elif t == "uncovered_numeric":
            out.append(
                {
                    "section": sec,
                    "source": "hard_gate",
                    "instruction": (
                        f"The number {details.get('value')} in {sec} is an unregistered result claim. "
                        f"Either support it with executed evidence or remove/soften it."
                    ),
                }
            )
        elif t in (
            "missing_evidence",
            "operand_unresolved",
            "result_unresolved",
            "cross_run_evidence",
            "cross_run_artifact",
            "artifact_digest_mismatch",
            "artifact_missing",
            "unit_mismatch",
            "unit_unresolved",
        ):
            out.append(
                {
                    "section": sec,
                    "source": "hard_gate",
                    "instruction": f"Resolve unsupported claim: {e.get('message', '')}",
                }
            )
    return out


@mcp.tool()
async def merge_reviews(
    review_report_path: str,
    vlm_review_path: str = "",
    hard_gate_path: str = "",
    semantic_review_path: str = "",
) -> dict:
    """Merge reviews into independent vs evidence-grounded categories
    (Story2Proposal Phase E).

    Reviewer independence contract (UNCHANGED):
      - review_compiled_paper (text reviewer) evaluates the paper text only.
      - vlm_review_figures (VLM reviewer) evaluates figure images independently.
      - Both stay under ``independent_reviews``; they are NOT modified.

    Evidence-grounded reviews (claim_evidence_hard_gate + evidence_grounded_
    semantic_review) are reported SEPARATELY under ``evidence_grounded_reviews``.
    Inputs remain immutable. A unified ``suggested_revisions`` list (semantic
    review + hard-gate-derived edits) is emitted for paper_refine.

    No LLM call. Args beyond review_report_path are optional (back-compatible
    with the v0.6.0 two-arg signature).
    """
    import json as _json
    from pathlib import Path as _Path

    rr_path = _Path(review_report_path)
    if not rr_path.exists():
        return {"error": f"review_report not found: {rr_path}"}

    try:
        _json.loads(rr_path.read_text())
    except Exception as e:
        return {"error": f"failed to parse review_report: {e}"}

    def _load(p):
        if not p:
            return None, None
        fp = _Path(p)
        if fp.exists():
            try:
                return _json.loads(fp.read_text()), None
            except Exception as e:
                return None, str(e)
        return None, None

    vlm_data, vlm_err = _load(vlm_review_path)
    # Keep these errors. Binding them to `_` made a corrupt/truncated hard-gate
    # or semantic-review file indistinguishable from one that was never
    # configured: review_merge_log.json read ok:true, status:null, and the
    # gate's suggested_revisions (e.g. "correct 42.0 -> 17.3") silently vanished
    # from what paper_refine received. A parse failure on the file that carries
    # the blocking findings is the last place to be silent.
    hard_gate, hard_gate_err = _load(hard_gate_path)
    semantic, semantic_err = _load(semantic_review_path)

    # ── separated review log (Story2Proposal Phase E) ──
    suggested_revisions: list[dict] = []
    if isinstance(semantic, dict):
        suggested_revisions.extend(
            r
            for r in (semantic.get("suggested_revisions") or [])
            if isinstance(r, dict)
        )
        # `detected_overclaim_count` counts the review's typed findings, but the
        # refiner only consumes revision entries — a warning without a parallel
        # suggested_revision would never reach paper_refine and the count could
        # never decrease. Forward every warning as an advisory revision entry.
        _seen_instr = {
            (r.get("instruction") or "").strip()
            for r in suggested_revisions
            if isinstance(r, dict)
        }
        findings = semantic.get("findings")
        if findings is None:  # supported published pre-v1 review reader
            findings = semantic.get("warnings") or []
        for w in findings:
            if not isinstance(w, dict):
                continue
            msg = str(w.get("message") or "").strip()
            if not msg or msg in _seen_instr:
                continue
            _seen_instr.add(msg)
            suggested_revisions.append(
                {
                    "section": w.get("section", ""),
                    "instruction": msg,
                    "source": "semantic_warning",
                    "warning_type": w.get("type", ""),
                }
            )
    if isinstance(hard_gate, dict):
        suggested_revisions.extend(_hard_gate_revisions(hard_gate))

    # A configured review source that failed to LOAD is a load error, not an
    # absent review — surface it so `ok` and the status reflect it.
    _load_errors = {}
    if hard_gate_path and hard_gate is None and hard_gate_err:
        _load_errors["claim_evidence_hard_gate"] = hard_gate_err
    if semantic_review_path and semantic is None and semantic_err:
        _load_errors["evidence_grounded_semantic_review"] = semantic_err

    return {
        "stage": "merge_reviews",
        "ok": not _load_errors,
        "review_report_path": str(rr_path),
        "has_vlm_review": vlm_data is not None,
        "load_errors": _load_errors or None,
        "vlm_load_error": vlm_err,
        "independent_reviews": {
            "venue_review": str(rr_path),
            "vlm_figure_review": vlm_review_path or None,
            "has_vlm_review": vlm_data is not None,
        },
        "evidence_grounded_reviews": {
            "claim_evidence_hard_gate": hard_gate_path or None,
            "claim_evidence_hard_gate_status": (
                (hard_gate or {}).get("status")
                if hard_gate is not None
                else (f"load_error: {hard_gate_err}" if hard_gate_err else None)),
            "evidence_grounded_semantic_review": semantic_review_path or None,
            "evidence_grounded_semantic_review_status": (
                (semantic or {}).get("status")
                if semantic is not None
                else (f"load_error: {semantic_err}" if semantic_err else None)),
        },
        "suggested_revisions": suggested_revisions,
        "merge_policy": (
            "independent_reviews preserve reviewer independence; evidence_grounded_"
            "reviews are reported separately; both feed paper_refine but stay distinct."
        ),
    }


def _import_claim_links():
    """Import the claim_links helper, tolerating both entrypoint shapes."""
    try:
        import claim_links as _cl  # type: ignore
    except Exception:  # pragma: no cover
        from src import claim_links as _cl  # type: ignore
    return _cl


@mcp.tool()
async def link_paper_claims(
    tex_path: str = "",
    science_data_json: str = "",
    figures_manifest_json: str = "",
    output_path: str = "",
) -> dict:
    """Reconcile ``% CLAIM:Cx:NCx`` anchors against science_data claims and build
    paper_claim_links (Story2Proposal Phase A2 post-processing).

    Deterministic, no LLM. Returns paper_claim_links / numeric_mentions /
    figure_refs / unresolved_anchors / uncovered_numeric_candidates. The
    transform-stage science_data.json is NEVER mutated; figure binding is
    recorded here. Run after write_paper (draft) and again after paper_refine
    (final). Degrades to a valid empty result on failure (never error-only) so
    it cannot cascade-skip the finalize chain.
    """
    import json as _json
    from pathlib import Path as _Path

    def _empty(note: str) -> dict:
        return {
            "schema_version": "ari.paper-claim-links/v1",
            "stage": "link_paper_claims",
            "paper_claim_links": [],
            "numeric_mentions": [],
            "figure_refs": [],
            "unresolved_anchors": [],
            "uncovered_numeric_candidates": [],
            "counts": {},
            "paper_digest": None,
            "claim_links_digest": None,
            "note": note,
        }

    try:
        _cl = _import_claim_links()
    except Exception as _e:  # pragma: no cover
        return _empty(f"claim_links unavailable: {_e}")

    tex = ""
    if tex_path:
        p = _Path(tex_path)
        if p.is_file():
            tex = p.read_text(encoding="utf-8")
        elif tex_path.lstrip().startswith("\\"):
            tex = tex_path
    if not tex:
        return _empty(f"paper tex not found: {tex_path}")

    def _load_jsonish(val):
        """Return ``(value, error)``. ``error`` distinguishes a genuine
        empty/absent input from a source that EXISTS but could not be read —
        the two were both ``{}`` before, so a missing/truncated science_data
        (it arrives as a raw path string when absent — stages.py only reads
        content when the file exists) produced 0 resolved anchors and the reason
        string blamed the writer for inventing claim ids."""
        if not val:
            return {}, None
        if isinstance(val, dict):
            return val, None
        try:
            return _json.loads(val), None
        except Exception:
            sp = _Path(val)
            if sp.is_file():
                try:
                    return _json.loads(sp.read_text()), None
                except Exception as e:
                    return {}, f"{sp.name}: {e}"
            # a raw path string for a file that does not exist
            return {}, f"not found: {val}"

    sd, sd_err = _load_jsonish(science_data_json)
    fm, _fm_err = _load_jsonish(figures_manifest_json)
    fm = fm or None
    try:
        # ``claim_links.link_paper_claims`` owns the native-v1 -> flat gate
        # projection.  Pre-projecting here leaves schema_version unchanged and
        # makes that function try to parse the already-flat projection as a
        # native ScienceDataV1 a second time.  The resulting empty error
        # document can pass through the warn-mode gate but is correctly rejected
        # by the final PaperBuild lock because it differs from recomputation.
        result = _cl.link_paper_claims(tex, sd if isinstance(sd, dict) else {}, fm)
    except Exception as _e:  # pragma: no cover - defensive
        return _empty(f"link_paper_claims failed: {_e}")

    if sd_err:
        # The claim registry could not be read, so 0 resolved anchors here means
        # "the registry is missing", NOT "the writer invented claim ids". Say so
        # instead of letting the per-anchor reason strings misdirect the reader.
        result["science_data_load_error"] = sd_err
        log.warning("science_data unreadable (%s); claim anchors cannot be "
                     "resolved against the registry", sd_err)

    if output_path:
        try:
            _Path(output_path).write_text(
                _json.dumps(result, indent=2, ensure_ascii=False)
            )
            result["output_path"] = output_path
        except Exception as _e:
            result["_write_error"] = str(_e)
    return result


@mcp.tool()
async def paper_refine(
    tex_path: str = "",
    suggested_revisions_json: str = "",
    merged_review_path: str = "",
    semantic_review_path: str = "",
    venue: str = "arxiv",
    writer_prompt_override: str = "",  # "" => byte-identical to today (linear); non-empty =>
                                       # the governed paper_writer prompt frames the refine
                                       # (docs/plans/ari_rqgm_paper/03 §5.8). Additive, no
                                       # ari.rqgm import — a plain instruction string.
    decode_seed: int = 0,  # 0 => no seed in the payload => byte-identical to today (linear);
                           # non-zero => the refine is sampled under its draft's seed, so a
                           # refine child inherits its parent's decode identity
                           # (docs/plans/ari_rqgm_paper/02 §5.4). Additive plain scalar.
) -> dict:
    """Apply suggested revisions to the paper while PRESERVING ``% CLAIM:Cx:NCx``
    anchors (Story2Proposal generate-evaluate-adapt loop).

    Apply strategy (strengthened so the review's edits actually LAND — a single LLM
    pass previously left explicit overclaim fixes, e.g. the title, in place):
      1. DETERMINISTIC explicit substitutions: each ``replace "X" with "Y"`` the review
         specifies is applied directly (unique-only, anchor-safe), so the concrete
         edits cannot be silently dropped by the LLM.
      2. BOUNDED multi-pass LLM find/replace for the remaining qualifying requests:
         up to 3 passes on the progressively-edited doc until a pass adds no new safe
         edit. ``refine_passes`` reports how many ran.
      3. VERIFY (mechanical): any explicit substitution whose OLD span still occurs is
         reported under ``unaddressed_substitutions`` for the post-refine review.

    Non-destructive contract:
      - With no actionable revisions, the paper is returned unchanged.
      - Every ``% CLAIM`` anchor present in the draft MUST survive: _apply_edits rejects
        anchor-dropping edits per pass and the loop stops before any such pass; on net
        anchor loss the original paper is kept (refined=False). The anchors must live
        until the final hard gate.

    The refined LaTeX is returned under ``latex`` (the pipeline writes it to the
    stage output, overwriting full_paper.tex); the draft is preserved alongside
    as full_paper.draft.tex. PDF recompilation is a documented follow-up (the
    .tex is the living artifact the hard gate and finalize consume).
    """
    import json as _json
    import re as _re
    from pathlib import Path as _Path

    from ari.public.execution import WorkspaceRefV1
    from ari.public.paper import PaperModelCallBatchV1, PaperModelCallV1

    def _find_anchors(text: str) -> list:
        try:
            return _import_claim_links().find_anchors(text)
        except Exception:  # pragma: no cover - defensive fallback
            return [
                {"anchor": f"CLAIM:{m.group(1)}:{m.group(2)}"}
                for m in _re.finditer(r"%\s*CLAIM:(C\w+):(NC\w+)", text)
            ]

    p = _Path(tex_path)
    if not p.is_file():
        return {
            "error": f"paper tex not found: {tex_path}",
            "latex": "",
            "refined": False,
        }
    original = p.read_text(encoding="utf-8")
    refinement_workspace = WorkspaceRefV1(root=str(p.resolve().parent))
    refinement_calls: list[PaperModelCallV1] = []
    refinement_batch_path = ".ari-paper/refinement/model_calls.json"

    def _persist_refinement_calls() -> str:
        batch = PaperModelCallBatchV1.create(
            operation="refinement",
            calls=tuple(refinement_calls),
        )
        refinement_workspace.atomic_write_bytes(
            refinement_batch_path,
            _paper_json_bytes(batch.model_dump(mode="json")),
        )
        return refinement_batch_path

    revisions: list[dict] = []

    def _collect(obj):
        if isinstance(obj, list):
            for it in obj:
                _collect(it)
        elif isinstance(obj, dict):
            if obj.get("instruction") or obj.get("fix") or obj.get("suggestion"):
                revisions.append(obj)
            for key in ("suggested_revisions", "revisions"):
                if isinstance(obj.get(key), list):
                    _collect(obj[key])

    # A configured review source that fails to PARSE is not "no revisions": it
    # is a review we could not read. Swallowing it let the note below assert the
    # reviewers requested nothing, so a retracted claim shipped unchanged. Two
    # real triggers: a truncated file, and a valid-but-non-ASCII file read
    # without encoding= under LC_ALL=C (the tex is read encoding="utf-8" above).
    _load_errors: list[str] = []
    _sources_configured = 0
    if suggested_revisions_json:
        _sources_configured += 1
        try:
            _collect(
                _json.loads(suggested_revisions_json)
                if isinstance(suggested_revisions_json, str)
                else suggested_revisions_json
            )
        except Exception as _e:
            _load_errors.append(f"suggested_revisions_json: {_e}")
    for _path in (semantic_review_path, merged_review_path):
        if _path and _Path(_path).is_file():
            _sources_configured += 1
            try:
                _collect(_json.loads(_Path(_path).read_text(encoding="utf-8")))
            except Exception as _e:
                _load_errors.append(f"{_Path(_path).name}: {_e}")

    orig_anchors = {a["anchor"] for a in _find_anchors(original)}

    # Every configured review source failed to load: we do NOT know the
    # reviewers requested nothing. Return an error rather than a clean pass.
    if _load_errors and _sources_configured and len(_load_errors) >= _sources_configured:
        return {
            "error": "review inputs unreadable: " + "; ".join(_load_errors),
            "latex": original, "refined": False, "anchors_preserved": True,
            "applied_revisions": 0, "anchor_count": len(orig_anchors),
            "warnings": _load_errors,
        }

    if not revisions:
        persisted_calls = _persist_refinement_calls()
        return {
            "latex": original,
            "refined": False,
            "anchors_preserved": True,
            "applied_revisions": 0,
            "anchor_count": len(orig_anchors),
            "warnings": _load_errors or [],
            "refinement_call_path": persisted_calls,
            "note": ("no actionable suggested_revisions; paper returned unchanged"
                     if not _load_errors else
                     "some review sources were unreadable (see warnings); "
                     "applied only the sources that parsed"),
        }

    _rev_lines = []
    for r in revisions[:40]:
        sec = r.get("section", "")
        instr = r.get("instruction") or r.get("fix") or r.get("suggestion") or ""
        if instr:
            _rev_lines.append(f"- [{sec}] {instr}" if sec else f"- {instr}")
    revisions_text = "\n".join(_rev_lines)

    # S2P refiner role (eq. 5: (M',C)=A_ref({D_i},C)) is GLOBAL coherence over the
    # whole manuscript — but it is a BOUNDED task (compress redundancy, harmonize
    # terminology, reconcile visuals, apply the requests), NOT a full rewrite. So
    # the model sees the whole paper (global context) yet returns only TARGETED
    # find/replace edits. This keeps generation volume ~= the changed spans instead
    # of regenerating the entire document, which (with the slow CLI shim) timed out.
    # writer_prompt_override == "" (linear default) => byte-identical to today.
    # Under rqgm_archive the governed paper_writer prompt is prepended so the
    # refine is framed by the epoch's ACTIVE writer bytes (§5.8); the skill
    # still evolves nothing.
    system_prompt = (
        ((writer_prompt_override + "\n\n") if writer_prompt_override else "")
        + _load_prompt("global_coherence")
        + _paper_language_directive()
    )
    # (b) The semantic review usually specifies an EXPLICIT replacement (e.g. replace
    # "Roofline/Loopline Validation" with "... Context"). Extract those quoted OLD->NEW
    # pairs so they can be applied DETERMINISTICALLY first -- the concrete review edits
    # then cannot be silently missed by the LLM (the prior single pass left the title /
    # abstract overclaims in place). Straight/curly quotes; OLD must be >=4 chars.
    _SUB_RE = _re.compile(
        r"replace\s+[\"'“”‘’](.+?)[\"'“”‘’]"
        r"\s+with\s+[\"'“”‘’](.+?)[\"'“”‘’]",
        _re.IGNORECASE | _re.DOTALL,
    )

    def _extract_substitutions() -> list:
        subs: list = []
        for r in revisions:
            instr = r.get("instruction") or r.get("fix") or r.get("suggestion") or ""
            for _m in _SUB_RE.finditer(instr):
                old, new = _m.group(1).strip(), _m.group(2).strip()
                # OLD must be a multi-token PHRASE (contains whitespace): a bare generic
                # word could be globally unique by accident and get rewritten in the
                # WRONG span. Single-word fixes are routed to the LLM pass instead (its
                # prompt carries the section label for context).
                if (
                    old
                    and old != new
                    and len(old) >= 4
                    and any(c.isspace() for c in old)
                    and (old, new) not in subs
                ):
                    subs.append((old, new))
        return subs

    def _extract_edits(raw: str) -> list:
        s = (raw or "").strip()
        _m = _re.search(r"```(?:json)?\s*(.+?)```", s, _re.DOTALL)
        if _m:
            s = _m.group(1).strip()
        _a, _b = s.find("["), s.rfind("]")
        if _a != -1 and _b > _a:
            s = s[_a : _b + 1]
        try:
            data = _json.loads(s)
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _apply_edits(doc: str, edits: list) -> tuple:
        applied = 0
        skipped: list[str] = []
        for e in edits:
            if not isinstance(e, dict):
                continue
            find = e.get("find") or ""
            repl = e.get("replace")
            if not find or repl is None:
                skipped.append("empty find/replace")
                continue
            n = doc.count(find)
            if n != 1:  # not found, or ambiguous -> never guess
                skipped.append(f"find not unique (n={n}): {find[:50]!r}")
                continue
            # Claim safety covers the full declaration, not only Cx/NCx.  A
            # replacement that retains the marker but removes ``formula=`` is
            # scientifically destructive and must not land.
            if not _preserves_claim_comment_contract(find, repl):
                skipped.append(
                    f"edit would change/drop a % CLAIM declaration: {find[:50]!r}"
                )
                continue
            if not _preserves_figure_block_contract(find, repl):
                skipped.append(
                    f"edit would change/add/drop a figure block: {find[:50]!r}"
                )
                continue
            doc = doc.replace(find, repl, 1)
            applied += 1
        return doc, applied, skipped

    async def _run_edit(cur_doc: str, pass_idx: int = 0) -> list:
        _user = (
            f"Revision requests:\n{revisions_text}\n\n"
            + (
                "NOTE: some requests may ALREADY be reflected in the document below — "
                "apply ONLY the ones not yet addressed.\n\n"
                if pass_idx > 0
                else ""
            )
            + f"Return targeted find/replace edits for this document:\n\n```latex\n{cur_doc}\n```"
        )
        _kw = {
            "model": _get_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _user},
            ],
            "temperature": 0.4,
            "max_tokens": 8192,
            "timeout": 1800,
        }
        if decode_seed:
            _kw["seed"] = int(decode_seed)
        _ab = _get_api_base()
        if _ab:
            _kw["api_base"] = _ab
        _resp = await litellm.acompletion(**_kw)
        _raw = _resp.choices[0].message.content or ""
        call_index = len(refinement_calls) + 1
        prompt_artifact = artifact_from_payload(
            refinement_workspace,
            role="prompt",
            relative_path=(f".ari-paper/refinement/call-{call_index:03d}/prompt.json"),
            payload=_paper_json_bytes(
                {
                    "messages": _kw["messages"],
                    "temperature": _kw["temperature"],
                    "max_tokens": _kw["max_tokens"],
                    "timeout": _kw["timeout"],
                }
            ),
            media_type="application/json",
        )
        raw_artifact = artifact_from_payload(
            refinement_workspace,
            role="raw-model-response",
            relative_path=(f".ari-paper/refinement/call-{call_index:03d}/response.txt"),
            payload=_raw.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
        )
        model = str(_kw["model"])
        refinement_calls.append(
            PaperModelCallV1.create(
                call_id=f"refinement-{call_index:03d}",
                purpose="refinement",
                model=model,
                model_revision=os.environ.get("ARI_MODEL_PAPER_REVISION") or None,
                provider=(
                    os.environ.get("ARI_MODEL_PAPER_PROVIDER") or model.split("/", 1)[0]
                ),
                prompt_digest=prompt_artifact.digest,
                prompt_artifact=prompt_artifact,
                raw_response_artifact=raw_artifact,
                sampling={
                    "temperature": _kw["temperature"],
                    "max_tokens": _kw["max_tokens"],
                },
                usage=model_usage_from_response(_resp),
            )
        )
        if "</think>" in _raw:
            _raw = _raw.split("</think>")[-1]
        return _extract_edits(_raw)

    warnings: list[str] = []
    doc = original
    applied_total = 0

    # (b1) DETERMINISTIC explicit substitutions first — the review's concrete
    # "replace X with Y" edits are applied directly (anchor-safe, unique-only) so they
    # cannot be missed by the LLM. This is what fixes the title/abstract overclaim the
    # prior single pass left in place.
    det_subs = _extract_substitutions()
    applied_subs: set = set()
    for _old, _new in det_subs:
        if (
            doc.count(_old) == 1
            and _preserves_claim_comment_contract(_old, _new)
            and _preserves_figure_block_contract(_old, _new)
        ):
            doc = doc.replace(_old, _new, 1)
            applied_total += 1
            applied_subs.add((_old, _new))

    # (b2) BOUNDED multi-pass LLM loop for the remaining (qualifying / fuzzy) requests.
    # The prior single pass under-applied; iterate up to MAX_PASSES on the progressively
    # edited doc until a pass yields no new safe edit, stopping before any pass that
    # would drop a % CLAIM anchor.
    MAX_PASSES = 3
    passes = 0
    for _pass in range(MAX_PASSES):
        try:
            edits = await _run_edit(doc, _pass)
        except Exception as _e:
            warnings.append(f"refine LLM pass {_pass + 1} failed: {_e}")
            break
        new_doc, applied, skipped = _apply_edits(doc, edits)
        if skipped:
            warnings.append(
                f"pass {_pass + 1}: skipped {len(skipped)} unsafe/non-unique edit(s): {skipped[:2]}"
            )
        if applied == 0:
            break
        if (
            not orig_anchors.issubset({a["anchor"] for a in _find_anchors(new_doc)})
            or not _preserves_claim_comment_contract(original, new_doc)
            or not _preserves_figure_block_contract(original, new_doc)
        ):
            warnings.append(
                f"pass {_pass + 1}: edits would change/drop a % CLAIM declaration; "
                "kept prior text"
            )
            break
        doc = new_doc
        applied_total += applied
        passes += 1

    refined = doc

    # (b3) VERIFY which explicit substitutions actually landed (mechanical, no LLM):
    # those NOT in applied_subs were skipped (non-unique / absent). Keyed on the b1
    # apply outcome, NOT on `_old in refined` -- an expand edit ("X" -> "X Context")
    # leaves OLD present yet was applied, so a presence test would falsely flag it.
    unaddressed = [
        {"old": _o, "new": _n} for _o, _n in det_subs if (_o, _n) not in applied_subs
    ]
    if unaddressed:
        warnings.append(
            f"{len(unaddressed)} explicit replacement(s) not applied (find not unique/absent): "
            + ", ".join(f"{u['old'][:40]!r}" for u in unaddressed[:3])
        )

    final_anchors = {a["anchor"] for a in _find_anchors(refined)}
    anchors_ok = orig_anchors.issubset(final_anchors)
    claim_comments_ok = _preserves_claim_comment_contract(original, refined)
    figures_ok = _preserves_figure_block_contract(original, refined)

    if applied_total == 0 or not anchors_ok or not claim_comments_ok or not figures_ok:
        if not anchors_ok or not claim_comments_ok or not figures_ok:
            warnings.append(
                "claim declarations or figure blocks changed/lost; reverting to draft"
            )
        try:
            (_Path(tex_path).parent / "full_paper.draft.tex").write_text(original)
        except Exception:
            pass
        persisted_calls = _persist_refinement_calls()
        return {
            "latex": original,
            "refined": False,
            "anchors_preserved": True,
            "applied_revisions": 0,
            "anchor_count": len(orig_anchors),
            "warnings": warnings,
            "refine_passes": passes,
            "deterministic_substitutions": len(applied_subs),
            "unaddressed_substitutions": unaddressed,
            "refinement_call_path": persisted_calls,
            "note": (
                "no safe edits applied; paper unchanged"
                if applied_total == 0
                else "edits dropped anchors; reverted to draft"
            ),
        }

    refined = _escape_text_underscores(refined)
    if "\\end{document}" not in refined:
        refined = refined.rstrip() + "\n\\end{document}\n"
    try:
        (_Path(tex_path).parent / "full_paper.draft.tex").write_text(original)
    except Exception as _e:
        warnings.append(f"failed to save draft copy: {_e}")

    inserted = _inserted_sentences(original, refined)
    unrequested = _unrequested_process_claims(inserted, revisions)
    if unrequested:
        warnings.append(
            f"{len(unrequested)} inserted sentence(s) assert a verification/"
            f"validation process that no revision requested: "
            + "; ".join(s[:90] for s in unrequested[:2]))
    persisted_calls = _persist_refinement_calls()
    return {
        "latex": refined,
        "refined": True,
        "anchors_preserved": True,
        "applied_revisions": applied_total,
        "anchor_count": len(orig_anchors),
        "warnings": warnings,
        "refine_passes": passes,
        "deterministic_substitutions": len(applied_subs),
        "unaddressed_substitutions": unaddressed,
        # Every guard above is an `issubset` PRESERVATION check on anchors, so
        # an anchorless INSERTION passes all of them by construction (the empty
        # set is a subset of anything) and nothing else reads the final text for
        # new assertions. Observed live: refine inserted "we independently
        # re-verified each such figure ... and confirm they agree to within
        # rounding" — no such verification existed, no revision asked for it,
        # and it was factually false; it shipped in the PDF unexamined.
        "inserted_sentences": inserted,
        "unrequested_process_claims": unrequested,
        "refinement_call_path": persisted_calls,
        "note": ("deterministic explicit replacements + bounded multi-pass find/replace "
                 "(S2P refiner: global role, diff output); PDF recompile is a follow-up"),
    }


@mcp.tool()
async def list_rubrics() -> list[dict]:
    """List all reviewer rubrics available in config/reviewer_rubrics/."""
    return list_available_rubrics()


def _strip_invalid_cite_keys(latex: str, bib_content: str) -> str:
    """Remove cite keys not present in bib to prevent undefined citation warnings."""
    import re as _rc

    valid = set(_rc.findall(r"@\w+\{([^,\s]+)", bib_content))
    if not valid:
        return latex

    def _filt(m):
        keys = [k.strip() for k in m.group(1).split(",")]
        good = [k for k in keys if k in valid]
        return ("\\cite{" + ",".join(good) + "}") if good else ""

    return _rc.sub(r"\\cite\{([^}]+)\}", _filt, latex)


def _strip_fill_markers(latex: str) -> str:
    """Remove FILL_*_START and FILL_*_END template markers left by LLM.

    LLMs sometimes keep the marker tokens while inserting content between them.
    This strips only the marker lines, preserving the content inside.
    """
    import re as _rem

    # Remove lines that are exactly a FILL marker (with optional whitespace)
    latex = _rem.sub(r"(?m)^[ \t]*FILL_[A-Z_]+_(START|END)[ \t]*\n?", "", latex)
    return latex


def _extract_latex(llm_response: str) -> str:
    """Extract LaTeX document from LLM response.

    LLMs often wrap LaTeX in markdown fences or add explanatory text.
    This function finds the LaTeX document by locating documentclass (universal LaTeX structural marker),
    which is a universal LaTeX structural property, not domain-specific.
    """
    s = llm_response.find("\\documentclass")
    if s < 0:
        return llm_response  # no documentclass found, return as-is
    # Find the end: \end{document}
    e = llm_response.rfind("\\end{document}")
    if e >= 0:
        result = llm_response[s : e + len("\\end{document}")]
    else:
        result = llm_response[s:]
    return _strip_fill_markers(result)


# ─── Code Availability injection ─────────────────────────────
#
# This is a deterministic, no-LLM transformation of an already-compiled
# .tex file. We add the Code Availability section + machine-readable
# macros (\codeavailability / \codedigest / \coderef) so:
#   - readers see a citable section,
#   - the reproducibility sandbox extracts the ref+digest deterministically.
#
# Idempotent: re-running with the same digest is a no-op. Re-running with
# a *different* digest replaces the prior block.

_CODE_AVAIL_BEGIN = "% ari-code-availability:begin"
_CODE_AVAIL_END = "% ari-code-availability:end"


def _tex_literal(value: str) -> str:
    """Escape an external identifier for safe use in LaTeX text/arguments."""

    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\^{}",
        "~": r"\~{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def _tex_monospace(value: str) -> str:
    return r"\texttt{" + _tex_literal(value) + "}"


def _render_code_availability_block(
    ref: str, sha256: str, doi: str = "", license_id: str = ""
) -> str:
    """Render the LaTeX block to insert.

    The block sandwiches the Code Availability section between sentinel
    comments so we can find and replace it on re-injection.
    """
    sha_short = sha256[:16] + "..." if sha256 else ""
    parts = [
        _CODE_AVAIL_BEGIN,
        r"\providecommand{\codeavailability}[1]{}",
        r"\providecommand{\codedigest}[1]{}",
        r"\providecommand{\coderef}[1]{}",
        r"\section*{Code Availability}",
    ]
    if ref:
        parts.append(r"\coderef{" + _tex_literal(ref) + "}%")
    if sha256:
        parts.append(r"\codedigest{" + sha256 + "}%")
    if doi:
        parts.append(r"\codeavailability{" + _tex_literal(doi) + "}%")
    body_lines = []
    if ref:
        body_lines.append(
            r"The curated Experimental Artifact Repository for this paper is "
            "available at " + _tex_monospace(ref) + "."
        )
        body_lines.append(
            "It can be retrieved with one command: "
            + _tex_monospace("ari clone " + ref)
            + "."
        )
    if sha256:
        body_lines.append(
            r"Bundle integrity is verified by SHA-256 digest \texttt{"
            + sha_short
            + "} "
            r"(full digest: \texttt{" + sha256 + "})."
        )
    if doi:
        body_lines.append("Persistent identifier: " + _tex_monospace(doi) + ".")
    if license_id:
        body_lines.append(r"License: " + license_id + ".")
    if body_lines:
        parts.append(" ".join(body_lines))
    parts.append(_CODE_AVAIL_END)
    return "\n".join(parts)


@mcp.tool()
def inject_code_availability(
    tex_path: str,
    ref: str = "",
    sha256: str = "",
    doi: str = "",
    license_id: str = "",
    checkpoint_dir: str = "",
) -> dict:
    """Inject (or refresh) the Code Availability section in an existing .tex.

    No-op if both ``ref`` and ``sha256`` are empty (the section is omitted
    rather than rendered with placeholders — FR-PA2 / O-1 soft fail).

    Idempotent: re-running with the same args produces no diff. Running
    with new digest values replaces the prior block in place.

    Args:
        tex_path: path to the compiled paper .tex (e.g. ``full_paper.tex``).
        ref: bundle reference (``ari://``, ``gh:``, ``doi:``, ``file://``, ``https://``).
        sha256: 64-hex bundle digest (from ``ear_published/manifest.lock``).
        doi: optional persistent identifier (Zenodo DOI, etc.).
        license_id: optional SPDX license string from ``publish.yaml``.

    Returns:
        ``{"injected": bool, "tex_path": str, "block": str | None}``.
    """
    p = Path(tex_path)
    if not p.exists():
        return {"injected": False, "error": f"tex not found: {tex_path}"}

    # ── Auto-load ref/sha/doi from checkpoint metadata when not given ──
    # The pipeline calls this stage with checkpoint_dir but no ref/sha,
    # because those values become known only after curate (manifest.lock)
    # and publish (publish_record.json). Look them up from disk.
    _load_errors: list[str] = []
    if checkpoint_dir and not (ref or sha256):
        ckpt = Path(checkpoint_dir)
        manifest = ckpt / "ear_published" / "manifest.lock"
        record = ckpt / "publish_record.json"
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
                sha256 = sha256 or m.get("bundle_sha256", "")
                if not license_id:
                    license_id = (m.get("publish") or {}).get("license") or ""
            except Exception as exc:
                # EXISTS but unparseable — not "never published". Swallowing it
                # shipped a Code Availability section WITHOUT its integrity
                # digest (or dropped the section entirely), byte-identical to a
                # legitimately-unpublished run.
                _load_errors.append(f"manifest.lock: {exc}")
        if record.exists():
            try:
                r = json.loads(record.read_text(encoding="utf-8"))
                ref = ref or r.get("ref", "")
                if not doi:
                    extra = r.get("extra") or {}
                    doi = extra.get("doi") or ""
            except Exception as exc:
                _load_errors.append(f"publish_record.json: {exc}")
    if _load_errors:
        log.warning("code-availability sources exist but are unreadable (%s); "
                    "the section may omit integrity metadata", "; ".join(_load_errors))

    content = p.read_text(encoding="utf-8")

    def _with_errors(result: dict) -> dict:
        # Corrupt-but-present sources are otherwise indistinguishable from a
        # legitimately-unpublished run: surface them so callers can gate.
        if _load_errors:
            result["load_errors"] = list(_load_errors)
        return result

    # FR-PA2: omit the section entirely when neither ref nor sha is provided.
    if not ref and not sha256:
        # Strip any prior block (so a re-run with no context cleans up).
        new_content = _strip_existing_code_avail_block(content)
        if new_content != content:
            p.write_text(new_content, encoding="utf-8")
            return _with_errors({"injected": False, "tex_path": str(p), "block": None, "stripped_prior": True})
        return _with_errors({"injected": False, "tex_path": str(p), "block": None})

    block = _render_code_availability_block(
        ref=ref, sha256=sha256, doi=doi, license_id=license_id
    )
    new_content, replaced = _splice_code_avail_block(content, block)
    if new_content == content:
        # No change (idempotent re-injection) — return success without writing.
        return _with_errors({"injected": True, "tex_path": str(p), "block": block, "noop": True})
    p.write_text(new_content, encoding="utf-8")
    return _with_errors({"injected": True, "tex_path": str(p), "block": block, "replaced": replaced})


def _strip_existing_code_avail_block(content: str) -> str:
    pattern = re.compile(
        re.escape(_CODE_AVAIL_BEGIN) + r".*?" + re.escape(_CODE_AVAIL_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def _splice_code_avail_block(content: str, block: str) -> tuple[str, bool]:
    """Return (new_content, replaced_existing)."""
    pattern = re.compile(
        re.escape(_CODE_AVAIL_BEGIN) + r".*?" + re.escape(_CODE_AVAIL_END),
        re.DOTALL,
    )
    if pattern.search(content):
        return pattern.sub(lambda _m: block, content, count=1), True
    # Insert immediately before \end{document}; if that anchor is missing,
    # append at end (templates without an explicit \end{document} are rare
    # but possible for partial drafts).
    end_doc = r"\end{document}"
    idx = content.rfind(end_doc)
    if idx == -1:
        return content.rstrip() + "\n\n" + block + "\n", False
    return content[:idx] + block + "\n\n" + content[idx:], False


def main():
    mcp.run()


if __name__ == "__main__":
    main()
