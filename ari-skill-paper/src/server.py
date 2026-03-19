"""MCP Server for LaTeX paper writing support."""

import asyncio
import re
import subprocess
from pathlib import Path

import logging
import litellm
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

VENUES = [
    {"id": "neurips", "name": "NeurIPS", "deadline": "May 2025", "pages": 9},
    {"id": "icpp", "name": "ICPP", "deadline": "March 2025", "pages": 10},
    {"id": "sc", "name": "SuperComputing", "deadline": "April 2025", "pages": 12},
    {"id": "isc", "name": "ISC High Performance", "deadline": "February 2025", "pages": 12},
    {"id": "arxiv", "name": "arXiv", "deadline": "N/A", "pages": 0},
    {"id": "acm", "name": "ACM (general)", "deadline": "Varies", "pages": 10},
]

SECTION_PROMPTS = {
    "introduction": (
        "Write a LaTeX introduction section for an academic paper. "
        "Motivate the problem, state contributions, and outline the paper structure. "
        "Cite 2-3 related papers using \\cite{key} where appropriate."
    ),
    "related_work": (
        "Write a LaTeX related work section for an academic paper. "
        "Categorize and discuss prior work, highlighting gaps this paper addresses. "
        "CRITICAL for citations: you will receive a list of references with EXACT cite keys. "
        "Use ONLY those provided cite keys verbatim in \\cite{key} commands. "
        "Do NOT invent, modify, or reformat cite keys. "
        "Do NOT cite papers not in the provided list."
    ),
    "method": (
        "Write a LaTeX method/approach section for an academic paper. "
        "Describe the proposed approach with technical detail. "
        "Cite relevant prior methods using \\cite{key} where appropriate."
    ),
    "experiment": (
        "Write a LaTeX experiments section for an academic paper. "
        "Present experimental setup, results, and analysis. "
        "CRITICAL for figures: the context provides available figures with filenames and captions. "
        "You MUST embed each figure at the most relevant location in the text using: "
        "\\begin{figure}[htbp]\\centering\\includegraphics[width=0.85\\linewidth]{FILENAME}"
        "\\caption{CAPTION}\\label{fig:N}\\end{figure}"
        " — do NOT place all figures at the end. Place each figure right after "  
        "the paragraph that first discusses its content. "
        "Cite relevant papers using \\cite{key} where appropriate."
    ),
    "conclusion": (
        "Write a LaTeX conclusion section for an academic paper. "
        "Summarize contributions, discuss limitations, and suggest future work. "
        "Cite 1-2 papers for future work directions using \\cite{key}."
    ),
    "abstract": (
        "Write a concise 150-250 word LaTeX abstract for an academic paper. "
        "Cover: problem statement, proposed method, key experimental result (with numbers), "
        "and main contribution. Focus ONLY on the experiment and its results. "
        "Do NOT mention any automation framework, search system, or tool used to discover these results. "
        "Output raw LaTeX text only (no \begin{abstract} tags, no section header)."
    ),
    "title": (
        "Generate a concise, specific academic paper title (8-14 words). "
        "The title should reflect the optimization technique and benchmark, with quantitative result if space allows. "
        "CRITICAL: Output ONLY the plain title text. "
        "Do NOT output any LaTeX commands (no \\section, no \\begin, no \\textbf, no \\title). "
        "Do NOT output quotes, newlines, or any other text beyond the title itself. "
        "Example good output: Compiler Flag Optimization for Stencil Benchmarks on 64-Core AMD EPYC"
    ),
}


# Generic instruction for all section-writing system prompts
_FORBIDDEN_NOTICE = (
    "IMPORTANT: Write only information that enables independent reproduction of the results. "
    "Reproducible information (USE these): CPU architecture (e.g. AMD EPYC, x86_64), "
    "core/thread count, compiler name and version, compiler flags, OpenMP/MPI version, "
    "memory bandwidth, cache size. "
    "Non-reproducible information (DO NOT USE): cluster names, institution names, "
    "organization names, node IDs, job IDs, file paths, or any identifier specific "
    "to one computing environment. "
    "Write as the authors who directly conducted the experiments (first-person plural). "
    "Do NOT mention any automated system, AI framework, or search tool used to find results. "
    "Hardware description must be derivable from the experiment context only — "
    "do NOT infer or add details not explicitly provided. "
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


def _search_nodes_tree(nodes_json_path: str, queries: list[str]) -> str:
    """Extract scientific experiment evidence from nodes_tree.json.

    Returns ONLY performance metrics and configurations.
    Does NOT expose internal identifiers (node IDs, checkpoint names, etc.).
    """
    import json as _json
    from pathlib import Path as _Path
    if not nodes_json_path:
        return ""
    try:
        data = _json.loads(_Path(nodes_json_path).read_text())
        nodes = data.get("nodes", [])
        matched = []
        for n in nodes:
            text = _json.dumps(n, ensure_ascii=False).lower()
            score = sum(1 for q in queries if q.lower() in text)
            if score > 0:
                matched.append((score, n))
        matched.sort(key=lambda x: -x[0])
        lines = []
        # NOTE: eval_summary is intentionally excluded — it may contain
        # cluster/hardware names written by the evaluator LLM.
        # Only metrics (numeric values) are safe to pass to the paper LLM.
        _SKIP_KEYS = {"path", "dir", "checkpoint", "id", "node", "label", "uuid", "hash"}
        for _, n in matched[:8]:
            metrics = n.get("metrics", {})
            config = n.get("config", n.get("hypothesis", {}))
            line_parts = []
            if isinstance(config, dict):
                cfg_clean = {k: v for k, v in config.items()
                             if not any(s in k.lower() for s in _SKIP_KEYS)}
                if cfg_clean:
                    line_parts.append("config=" + str(cfg_clean))
            if metrics:
                line_parts.append("metrics=" + str(metrics))
            if line_parts:
                lines.append("- " + ", ".join(line_parts))
        return "\n".join(lines)
    except Exception:
        return ""


@mcp.tool()
async def generate_section(
    section: str,
    context: str,
    venue: str = "arxiv",
    nodes_json_path: str = "",
    refs_json: str = "",
) -> dict:
    """Generate a LaTeX section using an LLM, searching the experiment tree while writing.

    Args:
        section: Section type (introduction, related_work, method, experiment, conclusion)
        context: Experiment content / results summary to base the section on
        venue: Target venue identifier
        nodes_json_path: Path to nodes_tree.json (optional). When provided, the LLM
            can query all experiment nodes for richer evidence.
    """
    if section not in SECTION_PROMPTS:
        raise ValueError(
            f"Unknown section '{section}'. Valid: {list(SECTION_PROMPTS.keys())}"
        )

    venue_info = next((v for v in VENUES if v["id"] == venue), None)
    if venue_info is None:
        valid = [v["id"] for v in VENUES]
        raise ValueError(f"Unknown venue '{venue}'. Valid venues: {valid}")

    # Search the node tree for section-relevant additional information
    section_keywords = {
        "experiment":   ["metric", "metrics", "result", "measure", "compare", "ablat"],
        "method":       ["algorithm", "approach", "method", "implement", "optim"],
        "conclusion":   ["best", "metric", "result", "future", "summary"],
        "introduction": ["performance", "contribution", "motivation", "challenge"],
        "related_work": ["survey", "prior", "baseline", "comparison", "related"],
    }
    queries = section_keywords.get(section, [])
    tree_evidence = _search_nodes_tree(nodes_json_path, queries) if nodes_json_path else ""

    enriched_context = context
    if tree_evidence:
        enriched_context = (
            context
            + "\n\n--- Experiment Evidence ---\n"
            + tree_evidence
        )

    if section == "title":
        # Title must be plain text — no LaTeX code instruction to avoid confusion
        system_prompt = (
            SECTION_PROMPTS["title"] + " " + _FORBIDDEN_NOTICE
        )
    elif section == "abstract":
        system_prompt = (
            SECTION_PROMPTS["abstract"] + " " + _FORBIDDEN_NOTICE +
            "Output ONLY the abstract text (no \\begin{{abstract}} tags)."
        )
    else:
        # Build cite key list hint for the LLM
        _cite_hint = ""
        if refs_json:
            try:
                import json as _jref
                _rdata = _jref.loads(refs_json) if isinstance(refs_json, str) else refs_json
                _papers = _rdata.get("papers", []) if isinstance(_rdata, dict) else []
                if _papers:
                    _keys = []
                    for _p in _papers[:15]:
                        _k = _p.get("cite_key") or _p.get("arxivId","").replace("/","").replace(".","")
                        _t = _p.get("title","")[:60]
                        if _k:
                            _keys.append("  " + r"\cite{" + _k + "}  % " + _t)
                    if _keys:
                        _cite_hint = (
                            "\n\nAVAILABLE CITE KEYS (use these verbatim in \\cite{{}} commands):\n"
                            + "\n".join(_keys)
                            + "\nYou MUST cite at least 3 of these papers using \\cite{{key}} where appropriate."
                        )
            except Exception:
                pass
        system_prompt = (
            f"{SECTION_PROMPTS[section]} "
            f"Target venue: {venue_info['name']}. "
            f"Page limit: {venue_info['pages']} pages. "
            + _FORBIDDEN_NOTICE
            + _cite_hint +
            "\nUse the provided experiment data. "
            "Output ONLY raw LaTeX code for the section body (no preamble, no \\begin{{document}}). "
            "For arXiv submissions: no strict page limit, focus on clarity and completeness. "
            "For conference venues: strictly follow the page limit and formatting style."
        )

    import os, re
    _model = _get_model()
    _api_base = _get_api_base()
    kwargs = {"model": _model, "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": enriched_context},
    ]}
    if _api_base:
        kwargs["api_base"] = _api_base

    response = await litellm.acompletion(**kwargs)

    raw = response.choices[0].message.content or ""
    # strip <think> tags from reasoning models
    # Strip <think> tags (reasoning model output)
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    raw = raw.strip()
    # strip markdown fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    latex = raw.strip()
    return {"latex": latex, "tree_nodes_used": len(tree_evidence.split("\n")) if tree_evidence else 0}


@mcp.tool()
async def compile_paper(tex_dir: str, main_file: str = "main.tex") -> dict:
    """Compile a LaTeX project to PDF.

    Args:
        tex_dir: Directory containing the LaTeX source files
        main_file: Name of the main .tex file (default: main.tex)
    """
    tex_path = Path(tex_dir).resolve()
    if not tex_path.is_dir():
        return {"success": False, "pdf_path": "", "log": f"Directory not found: {tex_dir}"}

    main = tex_path / main_file
    if not main.is_file():
        return {"success": False, "pdf_path": "", "log": f"File not found: {main}"}

    try:
        # pdflatex -> bibtex -> pdflatex -> pdflatex (standard 4-pass sequence)
        result = await asyncio.to_thread(
            subprocess.run,
            ["pdflatex", "-interaction=nonstopmode", main_file],
            cwd=str(tex_path), capture_output=True, text=True, timeout=120,
        )
        await asyncio.to_thread(
            subprocess.run,
            ["bibtex", main_file.replace(".tex", "")],
            cwd=str(tex_path), capture_output=True, text=True, timeout=60,
        )
        for _ in range(2):
            result = await asyncio.to_thread(
                subprocess.run,
                ["pdflatex", "-interaction=nonstopmode", main_file],
                cwd=str(tex_path), capture_output=True, text=True, timeout=120,
            )

        pdf_name = main_file.replace(".tex", ".pdf")
        pdf_path = tex_path / pdf_name
        # Consider success if PDF exists with content (>1KB), even if returncode != 0 (warnings are OK)
        pdf_ok = pdf_path.is_file() and pdf_path.stat().st_size > 1024
        log_output = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout

        return {
            "success": pdf_ok,
            "pdf_path": str(pdf_path) if pdf_ok else "",
            "log": log_output,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "pdf_path": "", "log": "Compilation timed out"}
    except FileNotFoundError:
        return {"success": False, "pdf_path": "", "log": "pdflatex not found. Please install a LaTeX distribution."}


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
    if page_count is not None and venue_info["pages"] > 0:
        if page_count > venue_info["pages"]:
            issues.append(
                f"Page count ({page_count}) exceeds venue limit ({venue_info['pages']})"
            )

    return {"ok": len(issues) == 0, "issues": issues}


def _count_pdf_pages(pdf_path: Path) -> int | None:
    """Count pages in a PDF by scanning for /Type /Page entries."""
    try:
        content = pdf_path.read_bytes()
        pages = re.findall(rb"/Type\s*/Page(?!s)", content)
        return len(pages) if pages else None
    except Exception:
        return None


import os as _os

def _get_model() -> str:
    # Check ARI_LLM_MODEL first, then LLM_MODEL, then default to qwen3:32b
    return (_os.environ.get("ARI_LLM_MODEL")
            or _os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")

def _get_api_base() -> str | None:
    """Return LLM API base URL, or None to use provider default (e.g. OpenAI).

    Priority:
    1. ARI_LLM_API_BASE (paper-skill specific override; empty string → None = use OpenAI)
    2. If model is not ollama and OPENAI_API_KEY set → None (use OpenAI)
    3. LLM_API_BASE (global setting, e.g. Ollama)
    4. Default: None (litellm provider default)
    """
    ari_base = _os.environ.get("ARI_LLM_API_BASE")
    if ari_base is not None:          # explicitly set (even to "")
        return ari_base or None       # "" → None = use OpenAI
    if (_os.environ.get("OPENAI_API_KEY") and "ollama" not in _get_model()):
        return None
    return _os.environ.get("LLM_API_BASE") or None



@mcp.tool()
async def review_section(latex: str, context: str, venue: str = "arxiv") -> dict:
    """Review a LaTeX paper section and return structured feedback.

    Args:
        latex: LaTeX content to review
        context: Experiment context / goal for reference
        venue: Target venue (e.g. neurips, sc, isc, arxiv)
    Returns:
        dict with: overall (str), strengths (list[str]), weaknesses (list[str]),
                   suggestions (list[str]), accept_recommendation (str)
    """
    import json, re

    model_name = _get_model()
    system_prompt = (
        "You are an expert academic reviewer for " + venue.upper() + ".\n"
        "Review the provided LaTeX section and return ONLY valid JSON with:\n"
        "  overall: str (1-2 sentences overall assessment)\n"
        "  strengths: list[str] (up to 3 key strengths)\n"
        "  weaknesses: list[str] (up to 3 key weaknesses)\n"
        "  suggestions: list[str] (up to 3 concrete improvement suggestions)\n"
        "  accept_recommendation: str (one of: strong_accept, accept, weak_accept, reject)\n"
        "Be concise and technical. No markdown fences.\n"
        "Reproducibility criterion: flag as weakness any experimental detail that cannot be "
        "independently reproduced from the description alone — e.g. environment-specific "
        "identifiers (cluster names, node IDs, organization names, file paths). "
        "Hardware must be described by architecture and specifications only, "
        "not by the name of the system or organization that owns it."
    )
    user_prompt = (
        f"Venue: {venue}\nContext: {context[:500]}\n\nLaTeX to review:\n{latex[:3000]}"
    )

    kwargs = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    api_base = _get_api_base()
    if api_base:
        kwargs["api_base"] = api_base

    response = await litellm.acompletion(**kwargs)
    raw = response.choices[0].message.content or ""
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)

    try:
        return json.loads(raw)
    except Exception:
        return {
            "overall": raw[:500],
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
            "accept_recommendation": "unknown",
        }



@mcp.tool()
async def revise_section(
    section: str,
    latex: str,
    feedback: str,
    context: str,
    venue: str = "arxiv",
) -> dict:
    """Revise a LaTeX section based on reviewer feedback.

    Part of the AI Scientist v2-style iterative writing loop.

    Args:
        section: Section type
        latex: Current LaTeX content to revise
        feedback: Reviewer feedback (weaknesses + suggestions)
        context: Experiment context
        venue: Target venue

    Returns:
        {latex: revised LaTeX, changes: summary of changes made}
    """
    import os, re
    _model2 = _get_model()
    _api_base2 = _get_api_base()

    # Title and abstract need special prompts (no LaTeX command instruction)
    if section == "title":
        system_prompt = (
            f"You are revising the title of an academic paper. "
            "The reviewer has provided feedback. Apply suggestions to improve the title. "
            + _FORBIDDEN_NOTICE +
            "CRITICAL: Output ONLY the plain title text. "
            "Do NOT output any LaTeX commands (no \\section, no \\begin, no \\textbf, no \\title). "
            "Output ONLY the plain title words. No quotes, no newlines, nothing else."
        )
    elif section == "abstract":
        system_prompt = (
            f"You are revising the abstract of an academic paper for {venue.upper()}. "
            "The reviewer has provided feedback. Apply ALL suggestions precisely. "
            + _FORBIDDEN_NOTICE +
            "Output ONLY the revised abstract text (no \\begin{{abstract}} tags, no LaTeX preamble). "
            "Do NOT include explanations. Just the improved abstract text."
        )
    else:
        system_prompt = (
            f"You are revising the {section} section of an academic paper for {venue.upper()}. "
            "The reviewer has provided feedback. Apply ALL suggestions precisely. "
            + _FORBIDDEN_NOTICE +
            "Output ONLY the revised raw LaTeX for this section. "
            "Do NOT include explanations. Just the improved LaTeX."
        )
    user_prompt = (
        "Context: " + context[:400] + "\n\n"
        "Reviewer feedback:\n" + feedback[:1000] + "\n\n"
        "Current LaTeX:\n" + latex[:3000]
    )

    kwargs = {
        "model": _model2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if _api_base2:
        kwargs["api_base"] = _api_base2

    response = await litellm.acompletion(**kwargs)
    raw = response.choices[0].message.content or ""
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])
    return {"latex": raw.strip(), "changes": "Revised " + section + ": " + feedback[:200]}


def _make_cite_key(paper: dict, seen: dict) -> str:
    import re as _re
    authors = paper.get("authors", [])
    lastname = _re.sub(r"[^a-z]", "", authors[0].split()[-1].lower()) if authors else "anon"
    year = (paper.get("published", "2024") or "2024")[:4]
    words = paper.get("title", "").split()
    kw = _re.sub(r"[^a-z]", "", words[0].lower()) if words else "paper"
    base = f"{lastname}{year}{kw}"[:18]
    if base in seen:
        seen[base] += 1
        return base + str(seen[base])
    seen[base] = 0
    return base



def _build_bib_content(refs_json: str) -> tuple:
    """Build BibTeX file content from references JSON.

    Uses authoritative BibTeX from Semantic Scholar (bibtex/cite_key fields) when available.
    Falls back to synthesized BibTeX from arXiv metadata.
    Returns (bib_content: str, key_list: list of (key, title) tuples).
    """
    import re as _re_bib, json as _json
    if not refs_json:
        return "", []
    try:
        refs_data = _json.loads(refs_json) if isinstance(refs_json, str) else refs_json
        papers = refs_data.get("papers", [])
    except Exception:
        return "", []
    entries, key_list, seen = [], [], {}
    for p in papers[:15]:
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
            entries.append("\n".join(lines))
        else:
            # Fallback: synthesize from arXiv metadata
            key = _make_cite_key(p, seen)
            seen[key] = True
            authors = " and ".join(p.get("authors", [])[:4]) or "Unknown"
            year = (p.get("published", "2024") or "2024")[:4]
            note = (p.get("abstract", "")[:120]
                    .replace("{", "").replace("}", "").replace("\n", " "))
            entries.append(
                "@article{" + key + ",\n"
                "  author = {" + authors + "},\n"
                "  title  = {" + title.replace("{","").replace("}","") + "},\n"
                "  year   = {" + year + "},\n"
                "  note   = {" + note + "}\n}"
            )
        key_list.append((key, title))
    return "\n\n".join(entries), key_list


def _escape_text_underscores(text: str) -> str:
    """Escape bare underscores in LaTeX text mode. Skips command args and math."""
    import re as _re_esc
    result = []
    i = 0
    skip_until = []  # stack of closing delimiters to skip
    while i < len(text):
        # Check if inside a command arg that should not be escaped
        if text[i] == '\\' and i + 1 < len(text):
            cmd_end = i + 1
            while cmd_end < len(text) and text[cmd_end].isalpha():
                cmd_end += 1
            cmd_name = text[i+1:cmd_end]
            result.append(text[i:cmd_end])
            i = cmd_end
            # If command name is empty and next char is _ ^ $ # etc, it's already escaped — pass through
            if not cmd_name and i < len(text) and text[i] in '_^$#&%~|':
                result.append(text[i]); i += 1; continue
            # For label/ref/cite/eqref: include the {} arg without escaping
            if cmd_name in ('label', 'ref', 'eqref', 'cite', 'pageref', 'autoref',
                            'hyperref', 'nameref', 'vref', 'cref', 'Cref',
                            'includegraphics', 'bibliography', 'bibliographystyle'):
                # Handle optional [...] before {}, e.g. \includegraphics[width=...]{file}
                if i < len(text) and text[i] == '[':
                    _d = 1; result.append('['); i += 1
                    while i < len(text) and _d > 0:
                        if text[i] == '[': _d += 1
                        elif text[i] == ']': _d -= 1
                        result.append(text[i]); i += 1
                if i < len(text) and text[i] == '{':
                    depth = 1
                    result.append('{')
                    i += 1
                    while i < len(text) and depth > 0:
                        if text[i] == '{': depth += 1
                        elif text[i] == '}': depth -= 1
                        result.append(text[i])
                        i += 1
            elif text[i:i+1] in ('[', '{'):
                # Other commands: also protect their arguments
                depth = 1
                result.append(text[i])
                i += 1
                while i < len(text) and depth > 0:
                    if text[i] in ('{', '['): depth += 1
                    elif text[i] in ('}', ']'): depth -= 1
                    result.append(text[i])
                    i += 1
            continue
        if text[i] == '$':
            # Check if this is an escaped dollar \$ (literal, not math mode)
            if i > 0 and text[i-1] == '\\':
                # Already appended '\\' — just append '$' as literal
                result.append('$'); i += 1; continue
            # Skip math mode: find matching closing $
            if text[i+1:i+2] == '$':
                end = text.find('$$', i+2)
                if end < 0:
                    # Unclosed $$: emit as literal \$ to avoid LaTeX errors
                    result.append('\\$'); i += 1; continue
                result.append(text[i:end+2]); i = end+2
            else:
                end = text.find('$', i+1)
                if end < 0:
                    # Unclosed $: emit as literal \$ to avoid Missing $ LaTeX error
                    result.append('\\$'); i += 1; continue
                result.append(text[i:end+1]); i = end+1
            continue
        if text[i] == '_':
            result.append('\\_')
            i += 1
            continue
        result.append(text[i])
        i += 1
    return ''.join(result)




_BFTS_TERM_MAP = {
    'node label': 'compiler configuration',
    'node labels': 'compiler configurations',
    'colored by label': 'colored by flag set',
    'by label': 'by configuration',
    'search tree depth': 'configuration index',
    'tree depth': 'configuration index',
    'Tree Depth': 'Configuration Index',
    'search step': 'configuration index',
    'per-depth': 'per-group',
    'BFTS': '', 'bfts': '',
    'improve': 'high-performance',
    'validation': 'verified',
    'ablation': 'baseline',
    'draft': 'initial',
    'experiment workflow': 'systematic evaluation',
    'exploration depth': 'number of configurations evaluated',
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
    _author = author_name.strip() or "Artificial Research Intelligence"
    figures = figures or []

    # Build BibTeX cite key list for the template
    _bib_content, _bib_keys = _build_bib_content(refs_json)
    cite_list_str = ""
    if _bib_keys:
        cite_list_str = (
            "% AVAILABLE CITE KEYS — use \\cite{key} for these:\n"
            + "\n".join(f"% \\cite{{{k}}}  — {title[:80]}" for k, title in _bib_keys[:15])
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

    # Title hint from experiment summary
    _title_hint = experiment_summary.split("\n")[0][:100].strip() if experiment_summary else "Research Paper"

    template = f"""\\documentclass[11pt]{{article}}
\\usepackage{{geometry,booktabs,hyperref,amsmath,graphicx,float,caption,natbib}}
\\geometry{{margin=2.5cm}}

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
Present quantitative results. Reference Figure~\\ref{{fig:1}} below.
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
    m = _re.search(r'<!--\s*metric_keyword:\s*(\S+)\s*-->', text)
    return m.group(1) if m else "metric"

@mcp.tool()
async def write_paper_iterative(
    experiment_summary: str = "",
    context: str = "",  # alias for experiment_summary (used by pipeline.py)
    nodes_json_path: str = "",
    refs_json: str = "",
    figures_manifest_json: str = "",  # JSON content of figures manifest (loaded by pipeline)
    venue: str = "arxiv",
    max_revision_rounds: int = 2,
    author_name: str = "",  # config-specified author; defaults to "Artificial Research Intelligence"
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
        nodes_json_path: Path to nodes_tree.json
        refs_json: JSON from search_arxiv (related work references)
        venue: Target venue
        max_revision_rounds: Max revisions per section

    Returns:
        latex, sections, reviews, revision_counts
    """
    import traceback as _tb_wpi
    _tmpdir = ""
    try:
        import json
        # Accept context as alias for experiment_summary (pipeline.py compat)
        if not experiment_summary and context:
            experiment_summary = context
        # Parse figures manifest and append to experiment_summary for LLM context
        if figures_manifest_json:
            try:
                import json as _json
                figs = _json.loads(figures_manifest_json)
                fig_lines = []
                # Handle both list [{filename,caption}] and dict {"fig_1": "/path", ...} formats
                figs_raw = figs if isinstance(figs, list) else figs.get("figures", figs)
                # Extract latex_snippets (authoritative captions from plot-skill)
                _latex_snips = figs.get("latex_snippets", {}) if isinstance(figs, dict) else {}
                if isinstance(figs_raw, dict):
                    for i, (k, v) in enumerate(figs_raw.items()):
                        import os as _os_fig
                        fname_base = _os_fig.path.basename(str(v))
                        # Use real caption from latex_snippets if available
                        _snip = _latex_snips.get(k, "")
                        cap_m = re.search(r"\\caption\{([^}]+)\}", _snip)
                        cap = cap_m.group(1) if cap_m else f"Figure {i+1}: Experiment result"
                        fig_lines.append({"path": str(v), "basename": fname_base, "caption": cap, "latex": _snip})
                else:
                    for fig in (figs_raw if isinstance(figs_raw, list) else []):
                        fname = fig.get("filename", "") if isinstance(fig, dict) else str(fig)
                        cap = fig.get("caption", "") if isinstance(fig, dict) else ""
                        if fname:
                            import os as _os_fig2
                            fig_lines.append({"path": fname, "basename": _os_fig2.path.basename(fname), "caption": cap, "latex": ""})
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
                        ctx_lines.append(f"  Reference inline as: Figure~\\ref{{fig:{j}}}")
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
            experiment_summary = experiment_summary[:s] + experiment_summary[e+3:]
        experiment_summary = experiment_summary.strip()

        # ──────────────────────────────────────────────────────────────────────
        # OPTION A: LaTeX Template Approach (AI Scientist v2-style)
        # Build a full LaTeX scaffold with all section headers, figure placements,
        # and cite key hints pre-inserted — then ask the LLM to fill ALL sections
        # in a single call. This avoids the figure/citation placement problems
        # of the section-by-section approach.
        # ──────────────────────────────────────────────────────────────────────
        venue_info = next((v for v in VENUES if v["id"] == venue), None) or {"id": "arxiv", "name": "arXiv preprint", "pages": 99}
        _author_display = author_name.strip() if author_name.strip() else "Artificial Research Intelligence"

        # Parse figures list for template
        _figs_for_tpl = []
        if figures_manifest_json:
            try:
                import json as _jft
                _fmc_t = _jft.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
                _figs_raw_t = _fmc_t.get("figures", _fmc_t) if isinstance(_fmc_t, dict) else {}
                _snips_t = _fmc_t.get("latex_snippets", {}) if isinstance(_fmc_t, dict) else {}
                import os as _os_t
                if isinstance(_figs_raw_t, dict):
                    for _ki, _vi in _figs_raw_t.items():
                        _bn = _os_t.path.basename(str(_vi))
                        _snip = _snips_t.get(_ki, "")
                        _cap_m = re.search(r"\\caption\{([^}]+)\}", _snip)
                        _cap = _sanitize_bfts_terms(_cap_m.group(1) if _cap_m else f"Experiment result")
                        _figs_for_tpl.append({"basename": _bn, "caption": _cap, "latex": _sanitize_bfts_terms(_snip)})
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

        # Build comprehensive context for the LLM
        refs_context = ""
        if refs_json:
            try:
                _refs_data = json.loads(refs_json) if isinstance(refs_json, str) else refs_json
                _papers = _refs_data.get("papers", [])
                _bib_ct, _bib_kt = _build_bib_content(refs_json)
                _key_map = {i: k for i, (k, _) in enumerate(_bib_kt)}
                lines = ["AVAILABLE REFERENCES (cite with \\cite{key}):"]
                for _ri, _rp in enumerate(_papers[:12], 1):
                    _rk = _key_map.get(_ri-1, str(_ri))
                    lines.append(f"  \\cite{{{_rk}}}  {_rp.get('title','')[:80]}")
                    lines.append(f"    {_rp.get('abstract','')[:150]}")
                refs_context = "\n".join(lines)
            except Exception as _er:
                log.warning("Refs context failed: %s", _er)

        # Single LLM call to fill the entire template
        _system_prompt_a = (
            f"You are an expert academic writer. Fill in ALL the FILL_*_START ... FILL_*_END "
            f"placeholder blocks in the provided LaTeX template. Target venue: {venue_info['name']}. "
            "Rules:\n"
            "1. Replace EACH placeholder block with real, detailed LaTeX content\n"
            "2. Keep ALL \\section{}, \\subsection{}, \\begin{{figure}} and \\end{{figure}} lines EXACTLY as-is\n"
            "3. Use \\cite{key} for citations — keys are listed as comments in the template\n"
            "4. Do NOT add extra \\section headers or remove existing ones\n"
            "5. Return the COMPLETE LaTeX document in ```latex ... ``` fences\n"
            "6. The figures are already placed — reference them with Figure~\\ref{fig:N}\n"
        )
        _user_prompt_a = (
            f"Experiment context:\n{experiment_summary[:3000]}\n\n"
            f"{refs_context}\n\n"
            f"Fill in this LaTeX template — replace ALL FILL blocks with real content:\n\n"
            f"```latex\n{latex_template}\n```"
        )
        _kw_a = {
            "model": _get_model(),
            "messages": [
                {"role": "system", "content": _system_prompt_a},
                {"role": "user",   "content": _user_prompt_a},
            ],
            "temperature": 0.7, "max_tokens": 16384,
        }
        _apib_a = _get_api_base()
        if _apib_a:
            _kw_a["api_base"] = _apib_a
        _resp_a = await litellm.acompletion(**_kw_a)
        _raw_a = _resp_a.choices[0].message.content or ""
        if "</think>" in _raw_a:
            _raw_a = _raw_a.split("</think>")[-1]
        full_latex = _extract_latex(_raw_a) or _fill_template_with_llm_output(latex_template, _raw_a)
        if not full_latex:
            full_latex = latex_template  # fallback to template with placeholders

        # Populate dummy sections/reviews dicts for compat with downstream code
        sections = {}
        reviews = {}
        revision_counts = {}
        log.info("Option A: template filled, %d chars", len(full_latex))

        # Build bib_content and key_list needed by _compile_in_tmpdir and return value
        bib_content, key_list = _build_bib_content(refs_json)

                # ─── Option C: post-assembly figure injection (if LLM didn't place inline)
        if "\\includegraphics" not in full_latex and figures_manifest_json:
            try:
                import json as _jfig_c, os as _os_fig
                _fmc = _jfig_c.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
                _figs_c = _fmc.get("figures", {}) if isinstance(_fmc, dict) else {}
                if _figs_c:
                    _fig_list = []
                    for _i, (_k, _fp) in enumerate(_figs_c.items(), 1):
                        _fn = _os_fig.path.basename(str(_fp))
                        cap = _fmc.get("captions", {}).get(_k, f"Figure {_i}: performance results.")
                        _fig_list.append(f"Figure {_i}: file={_fn}, caption={cap!r}")
                    _fig_inject_prompt = (
                        "The paper below is missing all figure inclusions. "
                        "Insert the following figures at the most appropriate locations in the Experiments/Results section "
                        "(NOT as a separate Figures section at the end). "
                        "Each figure should appear right after the paragraph that discusses its content.\n\n"
                        "Available figures:\n" + "\n".join(_fig_list) + "\n\n"
                        "Use the LaTeX figure environment:\n"
                        r"\begin{figure}[htbp]\centering\includegraphics[width=0.85\linewidth]{FILENAME}"
                        "\n"
                        r"\caption{CAPTION}\label{fig:N}\end{figure}"
                        "\n\nReturn the COMPLETE revised LaTeX document in ```latex ... ``` fences."
                    )
                    _kw_fig = {
                        "model": _get_model(),
                        "messages": [
                            {"role": "system", "content": "You are a LaTeX expert. Insert figures inline in the paper."},
                            {"role": "user", "content": _fig_inject_prompt + "\n\nPaper:\n```latex\n" + full_latex + "\n```"},
                        ],
                        "temperature": 0.1, "max_tokens": 16384,
                    }
                    _apib_fig = _get_api_base()
                    if _apib_fig:
                        _kw_fig["api_base"] = _apib_fig
                    _resp_fig = await litellm.acompletion(**_kw_fig)
                    _raw_fig = _resp_fig.choices[0].message.content or ""
                    if "</think>" in _raw_fig:
                        _raw_fig = _raw_fig.split("</think>")[-1]
                    _new_fig_latex = _extract_latex(_raw_fig)
                    if _new_fig_latex and len(_new_fig_latex) > len(full_latex) * 0.8 and "\\includegraphics" in _new_fig_latex:
                        full_latex = _new_fig_latex
                        log.info("Figure injection pass: %d figures embedded inline", len(_figs_c))
            except Exception as _fig_e:
                log.warning("Figure injection pass failed: %s", _fig_e)

        # ─── AI Scientist v2: compile + reflection loop
        # _msg_history starts with the assembled full paper so reflection LLM has context
        _system_prompt = (
            "You are a scientific paper writer. You have written a LaTeX paper below. "
            "Your task is to fix any LaTeX errors or quality issues identified in the reflection. "
            "Do NOT hallucinate results, hardware specs, or citations not present in the experiment data. "
            "Do NOT replace content with stubs. Return the ENTIRE corrected LaTeX document."
        )
        # msg_history starts with the assembled full paper as 'assistant' turn
        # This mimics v2's approach where reflection LLM knows what it wrote
        _msg_history: list = [
            {"role": "user", "content": f"Write a scientific LaTeX paper for this experiment:\n{experiment_summary[:2000]}"},
            {"role": "assistant", "content": f"```latex\n{full_latex}\n```"},
        ]
        # v2 reference: perform_writeup.py compile_latex() + reflection rounds
        # Key difference from naive approach: msg_history is preserved so LLM
        # knows what it wrote and performs targeted fixes (not full replacement).
        import tempfile as _tmpmod, shutil as _shutil, subprocess as _spmod, os as _os2

        async def _compile_in_tmpdir(latex_text: str) -> tuple[list[str], str, bool]:
            """pdflatex -> bibtex -> pdflatex -> pdflatex. Returns (errors, chktex_out, bbl_ok)."""
            _td = _tmpmod.mkdtemp(prefix="ari_paper_")
            _pdflatex = _os2.environ.get("PDFLATEX_PATH", "pdflatex")
            _bibtex   = _os2.environ.get("BIBTEX_PATH", "bibtex")
            # Copy figures
            if figures_manifest_json:
                try:
                    import json as _jj_c, shutil as _sh_c
                    _fmc = _jj_c.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
                    for _fp in ((_fmc.get("figures", {}) or {}).values() if isinstance(_fmc, dict) else []):
                        _fp = str(_fp)
                        if _os2.path.exists(_fp): _sh_c.copy2(_fp, _td)
                except Exception: pass
            _tp = Path(_td) / "full_paper.tex"
            _tp.write_text(latex_text)
            if bib_content:
                (Path(_td) / "refs.bib").write_text(bib_content)
            _errs = []
            _bbl_ok = False
            for _cmd in [
                [_pdflatex, "-interaction=nonstopmode", "full_paper.tex"],
                ([_bibtex, "full_paper"] if bib_content else None),
                [_pdflatex, "-interaction=nonstopmode", "full_paper.tex"],
                [_pdflatex, "-interaction=nonstopmode", "full_paper.tex"],
            ]:
                if _cmd is None: continue
                try:
                    _r = await asyncio.to_thread(_spmod.run, _cmd, cwd=_td,
                                                 capture_output=True, text=True, timeout=90)
                    if _cmd[0] == _pdflatex:
                        _lines = _r.stdout.splitlines()
                    _errs.extend([l for l in _lines if l.startswith("!")])
                    # Also capture undefined-reference and undefined-citation warnings
                    _errs.extend([l for l in _lines
                                  if "LaTeX Warning:" in l and
                                  ("undefined" in l or "Citation" in l)])
                except Exception as _e:
                    log.warning("compile cmd %s failed: %s", _cmd[0], _e)
            _bbl = Path(_td) / "full_paper.bbl"
            _bbl_ok = _bbl.exists() and _bbl.stat().st_size > 100
            # chktex (non-fatal, diagnostic only)
            _chktex_out = ""
            try:
                _ck = await asyncio.to_thread(_spmod.run,
                    ["chktex", str(_tp), "-q", "-n2", "-n24", "-n13", "-n1"],
                    capture_output=True, text=True, timeout=15)
                _chktex_out = (_ck.stdout or "")[:600]
            except Exception: pass
            # _td is not cleaned up here — caller reads PDF/log then cleans up
            return (_errs[-3:], _chktex_out, _bbl_ok, _td)

        # Initial compile
        _errs, _chktex, _bbl_ok, _tmpdir = await _compile_in_tmpdir(full_latex)
        log.info("Initial compile: errors=%s bbl_ok=%s", _errs, _bbl_ok)

        # ── v2 reflection rounds (msg_history preserved) ──────────────────────────
        _n_reflections = 5
        for _ri in range(_n_reflections):
            # Build figure usage info (v2 style)
            import re as _re_fig, os as _os_fig
            _refs_in_paper = set(_os_fig.path.basename(f)
                for f in _re_fig.findall(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}', full_latex))
            _avail_figs: set = set()
            if figures_manifest_json:
                try:
                    import json as _jjr
                    _fmr = _jjr.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
                    _avail_figs = set(_os_fig.path.basename(str(v))
                        for v in ((_fmr.get("figures", {}) or {}).values() if isinstance(_fmr, dict) else []))
                except Exception: pass
            _unused = sorted(_avail_figs - _refs_in_paper)
            _invalid = sorted(_refs_in_paper - _avail_figs)

            _reflection_prompt = (
                f"Reflection round {_ri+1}/{_n_reflections}. Review the LaTeX you just wrote:\n"
                f"1) LaTeX compile errors and warnings (fix ALL): {_errs if _errs else 'none'}\n"
                f"2) BibTeX: {'OK (bibliography compiled)' if _bbl_ok else 'FAILED — refs.bib may be missing or cite keys mismatch'}\n"
                f"3) Figures available but not referenced in paper: {_unused}\n"
                f"4) Figure references in paper that do not match available files: {_invalid}\n"
                f"5) chktex output (LaTeX style issues):\n```\n{_chktex}\n```\n"
                f"\nNote: if there are undefined \\ref{{}} warnings, fix the \\label{{}} names to match.\n"
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
                "temperature": 0.3, "max_tokens": 16384,
            }
            _apib2 = _get_api_base()
            if _apib2:
                _kw_ref["api_base"] = _apib2
            try:
                _resp_r = await litellm.acompletion(**_kw_ref)
                _raw_r = _resp_r.choices[0].message.content or ""
                if "</think>" in _raw_r:
                    _raw_r = _raw_r.split("</think>")[-1].strip()
                # Force continue if hard LaTeX errors still present (ignore "I am done")
                _still_has_errors = any('Missing $' in e or 'Extra }' in e or 'undefined' in e for e in _errs)
                if "I am done" in _raw_r and not _still_has_errors:
                    log.info("v2 reflection %d: LLM says done", _ri+1)
                    break
                _new_latex = _extract_latex(_raw_r)
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
                    _new_latex = _re_cleanup.sub(r"(\d+(?:\.\d+)?)%", r"\1\\%", _new_latex)
                    full_latex = _new_latex
                    log.info("v2 reflection %d: updated latex (%d chars)", _ri+1, len(full_latex))
                    # Update msg_history for next round
                    _msg_history.append({"role": "user", "content": _reflection_prompt})
                    _msg_history.append({"role": "assistant", "content": _raw_r})
                    _errs, _chktex, _bbl_ok, _tmpdir = await _compile_in_tmpdir(full_latex)
                else:
                    log.warning("v2 reflection %d: LLM produced too-small output (%d chars), skipping", _ri+1, len(_new_latex))
                    break
            except Exception as _re:
                log.warning("v2 reflection %d failed: %s", _ri+1, _re)
                break
        # Copy compiled PDF to output location before cleanup
        _pdf_in_tmp = Path(_tmpdir) / "full_paper.pdf"
        if _pdf_in_tmp.exists():
            import os as _os_pdf
            _ckpt_dir = _os_pdf.path.dirname(figures_manifest_json.get("ckpt_path","")) if isinstance(figures_manifest_json, dict) else ""
            # Try to infer ckpt dir from nodes_json_path
            if not _ckpt_dir and nodes_json_path:
                _ckpt_dir = str(Path(nodes_json_path).parent)
            if _ckpt_dir and Path(_ckpt_dir).is_dir():
                _pdf_dest = Path(_ckpt_dir) / "full_paper.pdf"
                _shutil.copy2(str(_pdf_in_tmp), str(_pdf_dest))
                log.info("Copied compiled PDF to %s", _pdf_dest)
                # Also copy .tex and .bbl so skip_if_exists works and citations are visible
                _tex_in_tmp = Path(_tmpdir) / "full_paper.tex"
                _bbl_in_tmp = Path(_tmpdir) / "full_paper.bbl"
                if _tex_in_tmp.exists():
                    _shutil.copy2(str(_tex_in_tmp), str(Path(_ckpt_dir) / "full_paper.tex"))
                if _bbl_in_tmp.exists():
                    _shutil.copy2(str(_bbl_in_tmp), str(Path(_ckpt_dir) / "full_paper.bbl"))
        # ── AI Scientist v2-style evaluation: check compile quality ──────────────────
        _bbl_path = Path(_tmpdir) / "full_paper.bbl"
        _log_path = Path(_tmpdir) / "full_paper.log"
        _bbl_ok   = _bbl_path.exists() and _bbl_path.stat().st_size > 100
        _undef_cites = []
        if _log_path.exists():
            _log_txt = _log_path.read_text(errors='ignore')
            _undef_cites = [l for l in _log_txt.splitlines()
                            if 'Citation' in l and ('undefined' in l or 'empty' in l)]
        if not _bbl_ok or _undef_cites:
            log.warning("Compile: bbl_ok=%s, undefined_cites=%s", _bbl_ok, _undef_cites[:3])
            # Targeted fix: replace entire \cite{} group if keys unknown, keep rest of paper
            if _undef_cites and key_list:
                _valid_keys = [k for k, _ in key_list]
                def _replace_bad_cite(m):
                    # Keep only valid keys from the cite group
                    keys = [k.strip() for k in m.group(1).split(',')]
                    good = [k for k in keys if k in _valid_keys]
                    return (r'\cite{' + ', '.join(good) + '}') if good else ''
                import re as _re_cit
                full_latex = _re_cit.sub(r'\\cite\{([^}]+)\}', _replace_bad_cite, full_latex)
                log.info("Filtered invalid cite keys; valid keys=%s", _valid_keys[:5])
        _shutil.rmtree(_tmpdir, ignore_errors=True)

        # Fallback: if LLM didn't embed figures, append them at end (suboptimal but safe)
        if "\\includegraphics" not in full_latex and figures_manifest_json:
            try:
                import json as _jj3, os as _os4
                _fm3 = _jj3.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
                _figs3 = _fm3.get("figures", {}) if isinstance(_fm3, dict) else {}
                if isinstance(_figs3, dict) and _figs3:
                    # Insert each figure inline in Experiments/Results section (not at end)
                    _target_sections = ["\\section{Experiments}", "\\section{Results}", "\\section{Experiment}"]
                    _insert_after = None
                    for _sec in _target_sections:
                        if _sec in full_latex:
                            _insert_after = _sec
                            break
                    if not _insert_after:
                        _insert_after = "\\section{Conclusion}"
                    _fblk = ""
                    for _i3, (_k3, _fp3) in enumerate(_figs3.items(), 1):
                        _fn3 = _os4.path.basename(str(_fp3))
                        _fblk += (
                            "\n\\begin{figure}[htbp]\n"
                            "  \\centering\n"
                            "  \\includegraphics[width=0.85\\linewidth]{" + _fn3 + "}\n"
                            "  \\caption{Figure " + str(_i3) + ": Performance results.}\n"
                            "  \\label{fig:" + str(_i3) + "}\n"
                            "\\end{figure}\n"
                        )
                    # Find end of Experiments section (before Conclusion)
                    _conc_idx = full_latex.find("\\section{Conclusion}")
                    if _conc_idx > 0:
                        full_latex = full_latex[:_conc_idx] + _fblk + "\n" + full_latex[_conc_idx:]
                    else:
                        ins = "\\bibliographystyle" if "\\bibliographystyle" in full_latex else "\\end{document}"
                        full_latex = full_latex.replace(ins, _fblk + "\n" + ins, 1)
                    log.info("Inserted %d figures before Conclusion", len(_figs3))
            except Exception as _fe3:
                log.warning("Figure re-insertion failed: %s", _fe3)

        # Normalize bibliography name: LLM may write \bibliography{references} instead of {refs}
        import re as _re_bib2
        full_latex = _re_bib2.sub(r"\\bibliography\{[^}]+\}", r"\\bibliography{refs}", full_latex)
        # Ensure \end{document} is present (LLM fix or re-insertion may have stripped it)
        if "\\end{document}" not in full_latex:
            full_latex = full_latex.rstrip() + "\n\\end{document}\n"
            log.warning("Re-added missing \\end{document}")

        return {
            "latex": full_latex,
            "sections": sections,
            "reviews": reviews,
            "revision_counts": revision_counts,
            "bib": bib_content,
            "key_list": list(key_list),
        }

    except Exception as _ewpi:
        # Write traceback to file (bypasses stdio capture in MCP server)
        _tb_file = str(Path(__file__).parents[3] / "logs" / "ari_wpi_traceback.txt")
        try:
            with open(_tb_file, "w") as _f:
                _f.write(_tb_wpi.format_exc())
        except Exception:
            pass
        import sys as _sys_wpi
        _sys_wpi.stderr.write("=== write_paper_iterative TRACEBACK ===\n" + _tb_wpi.format_exc() + "\n")
        _sys_wpi.stderr.flush()
        log.error("write_paper_iterative TRACEBACK (also in %s):\n%s", _tb_file, _tb_wpi.format_exc())
        raise



@mcp.tool()
async def review_compiled_paper(
    tex_path: str = "",
    pdf_path: str = "",
    figures_manifest_json: str = "",
    experiment_summary: str = "",
) -> dict:
    """Review the compiled paper: PDF → text extraction, figure caption eval, holistic LLM review.

    AI Scientist v2-style review pipeline:
      1. pdftotext: converts compiled PDF to plain text
      2. Caption extraction: pulls caption{} blocks from LaTeX source
      3. Figure consistency: LLM checks each caption matches figure description
      4. Holistic review: LLM scores title, abstract, body, bibliography quality
      5. Returns structured report with scores and actionable issues

    Args:
        tex_path:              Path to full_paper.tex
        pdf_path:              Path to compiled full_paper.pdf
        figures_manifest_json: JSON string of figures manifest (from generate_figures)
        experiment_summary:    Brief description of the experiment for context

    Returns:
        {overall_score, title_ok, abstract_score, body_score, figure_reviews,
         issues, recommendations, pdf_text_snippet}
    """
    import re as _re, subprocess as _sp, json as _json

    # 1. Extract text from PDF using pymupdf (fitz) — pdftotext may not be installed
    pdf_text = ""
    if pdf_path:
        try:
            import fitz as _fitz
            _doc = _fitz.open(pdf_path)
            pdf_text = "\n".join(_page.get_text() for _page in _doc)
            _doc.close()
            log.info("pymupdf extracted %d chars from PDF", len(pdf_text))
        except Exception as _fe:
            log.warning("pymupdf failed: %s", _fe)
        # fallback 2: pdfminer.six
        if not pdf_text:
            try:
                from pdfminer.high_level import extract_text as _pdfminer_extract
                pdf_text = _pdfminer_extract(pdf_path)
                log.info("pdfminer extracted %d chars from PDF", len(pdf_text))
            except Exception as _pe:
                log.warning("pdfminer failed: %s", _pe)
        # fallback 3: pdftotext (if installed)
        if not pdf_text:
            try:
                _r = _sp.run(["pdftotext", pdf_path, "-"],
                             capture_output=True, text=True, timeout=30)
                pdf_text = _r.stdout
            except Exception as _e:
                log.warning("pdftotext failed: %s", _e)

    # Fallback: read .tex as text if PDF not available
    tex_text = ""
    if tex_path:
        try:
            tex_text = Path(tex_path).read_text()
        except Exception:
            pass

    review_text = pdf_text if pdf_text.strip() else tex_text
    if not review_text.strip():
        return {"error": "No paper text available for review", "overall_score": 0}

    # 2. Extract captions from LaTeX source
    captions = []
    if tex_text:
        for m in _re.finditer(r"\\caption\{([^}]{10,})\}", tex_text):
            captions.append(m.group(1).strip())

    # 3. Load figures manifest for figure consistency check
    figs_info = []
    if figures_manifest_json:
        try:
            figs_data = _json.loads(figures_manifest_json) if isinstance(figures_manifest_json, str) else figures_manifest_json
            raw = figs_data.get("figures", []) if isinstance(figs_data, dict) else []
            figs_info = raw if isinstance(raw, list) else []
        except Exception:
            pass

    # 4. Build review prompt (AI Scientist v2-style structured review)
    snippet = review_text[:5000]
    captions_str = "\n".join(f"- {c}" for c in captions[:8]) if captions else "(none extracted)"
    figs_str = "\n".join(
        f"- {f.get('path','?')}: {f.get('description','')[:100]}" for f in figs_info[:5]
    ) if figs_info else "(no figures manifest)"

    review_system = (
        "You are a rigorous scientific paper reviewer. "
        "Evaluate the paper on these criteria and return ONLY valid JSON with these exact keys:\n"
        "  overall_score: int 1-10\n"
        "  title_ok: bool (is the title specific, non-generic, no LaTeX errors?)\n"
        "  abstract_score: int 1-10 (quantitative claims, clarity, completeness)\n"
        "  body_score: int 1-10 (methodology, results, discussion quality)\n"
        "  citation_ok: bool (are citations formatted and relevant?)\n"
        "  figure_caption_issues: list of strings (captions that do not match their figure or are vague)\n"
        "  issues: list of strings (specific problems found, max 8)\n"
        "  recommendations: list of strings (concrete improvements, max 5)\n"
        "No markdown, no explanation outside JSON."
    )
    review_user = (
        f"Experiment context: {experiment_summary[:500]}\n\n"
        f"Paper text (first 5000 chars):\n{snippet}\n\n"
        f"Figure captions found in LaTeX:\n{captions_str}\n\n"
        f"Figures generated (manifest):\n{figs_str}"
    )
    _kw: dict = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": review_system},
            {"role": "user", "content": review_user},
        ],
        "temperature": 0.0, "max_tokens": 8192,
    }
    _apib = _get_api_base()
    if _apib:
        _kw["api_base"] = _apib
    try:
        _resp = await litellm.acompletion(**_kw)
        raw = _resp.choices[0].message.content or ""
        if "</think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        review = _json.loads(raw[s:e]) if s >= 0 and e > s else {}
    except Exception as _e:
        log.warning("review LLM failed: %s", _e)
        review = {"error": str(_e)}

    review["pdf_text_snippet"] = pdf_text[:500] if pdf_text else "(no PDF text)"
    review["captions_found"] = captions
    return review


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
        return llm_response[s:e + len("\\end{document}")]
    return llm_response[s:]

def main():
    mcp.run()

if __name__ == "__main__":
    main()
