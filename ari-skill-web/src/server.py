"""ari-skill-web: Web search and page fetch MCP server. P2 compliant."""
from __future__ import annotations
import asyncio
import json as _json
import logging
import os as _os
import re
import time as _time
import unicodedata as _unicodedata
import urllib.parse as _parse
import urllib.request as _req

import httpx
import litellm
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)
mcp = FastMCP("web-skill")

try:
    try:
        from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore
    except ImportError:
        from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("web")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Pluggable retrieval backend (Issue #11)
# ---------------------------------------------------------------------------
_retrieval_backend: str = _os.environ.get("ARI_RETRIEVAL_BACKEND", "semantic_scholar")
_ALPHAXIV_ENDPOINT: str = _os.environ.get(
    "ARI_ALPHAXIV_ENDPOINT", "https://api.alphaxiv.org/mcp/v1"
)

# ---------------------------------------------------------------------------
# LLM helpers (same pattern as paper-skill / idea-skill)
# ---------------------------------------------------------------------------

def _get_model() -> str:
    return (_os.environ.get("ARI_LLM_MODEL")
            or _os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")


def _get_api_base() -> str | None:
    ari_base = _os.environ.get("ARI_LLM_API_BASE")
    if ari_base is not None:
        return ari_base or None
    if (_os.environ.get("OPENAI_API_KEY") and "ollama" not in _get_model()):
        return None
    return _os.environ.get("LLM_API_BASE") or None


async def _llm_call(system: str, user: str, temperature: float = 0.3,
                     max_tokens: int = 512) -> str:
    """Make a single LLM call and return the text response."""
    kwargs: dict = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    base = _get_api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    # Strip <think> tags from reasoning models
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    return raw.strip()


# ---------------------------------------------------------------------------
# Internal Semantic Scholar search
# ---------------------------------------------------------------------------

def _clean_cite_key(s: str) -> str:
    """Normalize cite key: remove accents, keep only safe chars."""
    nfkd = _unicodedata.normalize("NFKD", s)
    ascii_s = nfkd.encode("ASCII", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9:_@{},-]+", "", ascii_s).lower()


def _parse_s2_paper(p: dict) -> dict:
    """Parse a single Semantic Scholar paper entry into our standard format."""
    bibtex_raw = p.get("citationStyles", {}).get("bibtex", "")
    cite_key = ""
    if bibtex_raw:
        nl = bibtex_raw.find("\n")
        first_line = bibtex_raw[:nl] if nl > 0 else bibtex_raw.split("\n")[0]
        clean_first = _clean_cite_key(first_line)
        m = re.search(r"\{([^,}]+)", clean_first)
        cite_key = m.group(1) if m else ""
    return {
        "title": p.get("title", ""),
        "authors": [a.get("name", "") for a in p.get("authors", [])[:4]],
        "year": str(p.get("year", "")),
        "abstract": (p.get("abstract") or "")[:300],
        "bibtex": bibtex_raw,
        "cite_key": cite_key,
    }


#: Max S2 retry attempts on HTTP 429 and the per-retry backoff cap (seconds).
_S2_MAX_ATTEMPTS = int(_os.environ.get("ARI_S2_MAX_ATTEMPTS", "3") or 3)
_S2_BACKOFF_CAP_S = float(_os.environ.get("ARI_S2_BACKOFF_CAP_S", "10") or 10)


def _search_s2_sync(query: str, limit: int = 10) -> list[dict]:
    """Search Semantic Scholar API synchronously. Returns list of paper dicts.

    Each paper: {title, authors, year, abstract, bibtex, cite_key}

    Retries on HTTP 429: Semantic Scholar rate-limits the shared egress IP — even
    a valid key 429s under burst (collect_references fires several queries in
    quick succession). Without a retry a transient 429 dropped the whole
    bibliography to the arXiv fallback. Honors ``Retry-After`` when present, else
    exponential backoff (1s/2s/4s, capped); other errors fail fast to [] as
    before. Attempts/cap are env-tunable (ARI_S2_MAX_ATTEMPTS / ARI_S2_BACKOFF_CAP_S).
    """
    fields = "title,authors,year,abstract,citationStyles"
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={_parse.quote(query)}&fields={fields}&limit={limit}"
    )
    s2_key = _os.environ.get("S2_API_KEY", "")
    headers = {"x-api-key": s2_key} if s2_key else {}
    attempts = max(1, _S2_MAX_ATTEMPTS)
    for attempt in range(attempts):
        try:
            req_obj = _req.Request(url, headers=headers)
            with _req.urlopen(req_obj, timeout=15) as resp:
                data = _json.loads(resp.read())
            return [_parse_s2_paper(p) for p in data.get("data", [])]
        except Exception as e:
            # HTTPError carries .code and .headers; a 429 is worth retrying.
            if getattr(e, "code", None) == 429 and attempt < attempts - 1:
                wait = float(2 ** attempt)
                try:
                    ra = e.headers.get("Retry-After")  # type: ignore[attr-defined]
                    if ra:
                        wait = float(ra)
                except Exception:
                    pass
                wait = min(wait, _S2_BACKOFF_CAP_S)
                log.warning("S2 429 for %r; retry %d/%d after %.1fs",
                            query, attempt + 1, attempts - 1, wait)
                _time.sleep(wait)
                continue
            log.warning("S2 search failed for %r: %s", query, e)
            return []
    return []


def _arxiv_fallback(query: str, limit: int = 8) -> list[dict]:
    """Fallback: search arXiv when S2 returns nothing."""
    try:
        import arxiv as _arxiv
        _search = _arxiv.Search(
            query=query, max_results=min(limit, 8),
            sort_by=_arxiv.SortCriterion.Relevance,
        )
        # arxiv 4.x removed Search.results(); Client().results() exists on
        # every version the requirements pin (>=2.0) can resolve.
        papers = []
        for r in _arxiv.Client().results(_search):
            authors = [a.name for a in r.authors[:4]]
            year = str(r.published.year) if r.published else ""
            aid = r.get_short_id().replace("/", "").replace(".", "")
            nl = chr(10)
            bib = ("@article{" + aid + "," + nl
                   + "  title={" + r.title + "}," + nl
                   + "  author={" + " and ".join(authors) + "}," + nl
                   + "  year={" + year + "}," + nl
                   + "  url={" + r.entry_id + "}" + nl + "}")
            papers.append({
                "title": r.title, "authors": authors,
                "year": year, "abstract": r.summary[:300],
                "bibtex": bib, "cite_key": aid, "url": r.entry_id,
            })
        return papers
    except Exception as e:
        log.warning("arXiv fallback failed for %r: %s", query, e)
        return []


# ---------------------------------------------------------------------------
# AlphaXiv MCP search (Issue #11)
# ---------------------------------------------------------------------------

async def _search_alphaxiv(query: str, max_results: int = 10) -> list[dict]:
    """Search AlphaXiv via MCP JSON-RPC over HTTP."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_papers",
            "arguments": {"query": query, "max_results": max_results},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(_ALPHAXIV_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
        result = data.get("result", data)
        # MCP tool results may be wrapped in content[]
        if isinstance(result, dict) and "content" in result:
            for item in result["content"]:
                if item.get("type") == "text":
                    result = _json.loads(item["text"])
                    break
        papers = result if isinstance(result, list) else result.get("papers", [])
        return [
            {
                "title": p.get("title", ""),
                "authors": p.get("authors", [])[:4] if isinstance(p.get("authors"), list) else [],
                "abstract": (p.get("abstract") or "")[:300],
                "url": p.get("url", ""),
                "arxiv_id": p.get("arxiv_id", ""),
            }
            for p in papers
        ]
    except Exception as e:
        log.warning("AlphaXiv search failed for %r: %s", query, e)
        return []


async def _search_semantic_scholar_async(query: str, max_results: int = 10) -> list[dict]:
    """Async wrapper around _search_s2_sync for parallel dispatch."""
    loop = asyncio.get_event_loop()
    papers = await loop.run_in_executor(None, _search_s2_sync, query, max_results)
    return papers


async def _dispatch_search(query: str, max_results: int = 10) -> list[dict]:
    """Dispatch search based on configured retrieval backend."""
    backend = _retrieval_backend
    if backend == "alphaxiv":
        return await _search_alphaxiv(query, max_results)
    elif backend == "both":
        results = await asyncio.gather(
            _search_alphaxiv(query, max_results),
            _search_semantic_scholar_async(query, max_results),
            return_exceptions=True,
        )
        merged: list[dict] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        for r in results:
            if isinstance(r, Exception):
                log.warning("Parallel search error: %s", r)
                continue
            for p in r:
                aid = p.get("arxiv_id", "")
                title_lower = (p.get("title") or "").lower()
                if aid and aid in seen_ids:
                    continue
                if title_lower and title_lower in seen_titles:
                    continue
                if aid:
                    seen_ids.add(aid)
                if title_lower:
                    seen_titles.add(title_lower)
                merged.append(p)
        return merged
    else:
        return _search_s2_sync(query, max_results)


# ---------------------------------------------------------------------------
# Public MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def set_retrieval_backend(backend: str) -> dict:
    """Set the paper retrieval backend.

    Args:
        backend: One of "alphaxiv", "semantic_scholar", or "both"

    Returns:
        {ok: bool, backend: str}
    """
    global _retrieval_backend
    valid = {"alphaxiv", "semantic_scholar", "both"}
    if backend not in valid:
        return {"ok": False, "error": f"Invalid backend: {backend}. Must be one of {valid}"}
    _retrieval_backend = backend
    return {"ok": True, "backend": _retrieval_backend}


@mcp.tool()
async def search_papers(query: str, max_results: int = 10) -> dict:
    """Search for academic papers using the configured retrieval backend.

    Dispatches to AlphaXiv, Semantic Scholar, or both depending on the
    configured backend (set via set_retrieval_backend or ARI_RETRIEVAL_BACKEND).

    Args:
        query: Search query string
        max_results: Maximum papers to return

    Returns:
        {papers: list, query: str, count: int, backend: str}
    """
    papers = await _dispatch_search(query, max_results)
    return {"papers": papers, "query": query, "count": len(papers), "backend": _retrieval_backend}


@mcp.tool()
def web_search(query: str, n: int = 5) -> dict:
    """Search the web using DuckDuckGo. No API key required.

    Args:
        query: Search query string
        n: Number of results (1-10)

    Returns:
        results: list of {title, url, snippet}
    """
    try:
        # The DuckDuckGo client package was renamed ``duckduckgo-search`` -> ``ddgs``.
        # Import whichever is installed so web_search works on both (the declared
        # dep is ``duckduckgo-search``, which still exposes ``DDGS``); a bare
        # ``from ddgs import DDGS`` silently disabled web_search when only the
        # older package was present.
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=min(n, 10)))
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")[:400]}
            for r in raw
        ]
        return {"results": results, "query": query, "count": len(results)}
    except Exception as e:
        return {"results": [], "error": str(e)}


@mcp.tool()
def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """Fetch a web page and extract readable text. No LLM.

    Args:
        url: HTTP(S) URL to fetch
        max_chars: Maximum characters to return

    Returns:
        text: Extracted readable text
        title: Page title
    """
    try:
        from bs4 import BeautifulSoup
        newline = chr(10)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ARIBot/1.0)"}
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title else ""
            lines = [l.strip() for l in soup.get_text(separator=newline).splitlines() if l.strip()]
            text = newline.join(lines)
        else:
            title = url.split("/")[-1]
            text = resp.text
        return {"text": text[:max_chars], "title": title, "url": str(resp.url)}
    except Exception as e:
        return {"text": "", "title": "", "url": url, "error": str(e)}


@mcp.tool()
def search_arxiv(query: str, max_results: int = 5) -> dict:
    """Direct arXiv search. Deterministic. No LLM.

    Args:
        query: Search query (supports ti:, au:, abs: prefixes)
        max_results: Number of results (1-20)

    Returns:
        papers: list of {title, authors, abstract, url, published}
    """
    try:
        import arxiv
        search = arxiv.Search(
            query=query,
            max_results=min(max_results, 20),
            sort_by=arxiv.SortCriterion.Relevance,
        )
        papers = [
            {
                "title": r.title,
                "authors": [a.name for a in r.authors[:5]],
                "abstract": r.summary[:500],
                "url": r.entry_id,
                "published": str(r.published.date()) if r.published else "",
            }
            for r in search.results()
        ]
        return {"papers": papers, "query": query, "count": len(papers)}
    except Exception as e:
        return {"papers": [], "error": str(e)}


@mcp.tool()
async def search_semantic_scholar(
    query: str,
    limit: int = 8,
    extra_queries: list | None = None,
) -> dict:
    """Search Semantic Scholar for academic papers and return real BibTeX entries.

    Unlike arXiv search which returns synthetic metadata, this tool returns
    authoritative BibTeX from Semantic Scholar with proper citation keys.

    Args:
        query: Search query string
        limit: Maximum papers to return (default 8)

    Returns:
        {papers: [{title, authors, year, abstract, bibtex, cite_key}], query, count}
    """
    papers = _search_s2_sync(query, limit)

    # Run extra queries and merge (deduplicated by title)
    if extra_queries:
        seen_titles = {p["title"].lower() for p in papers}
        for eq in (extra_queries or [])[:3]:
            _time.sleep(1.0)
            try:
                extra = _search_s2_sync(eq, limit)
                for ep in extra:
                    et = (ep.get("title") or "").lower()
                    if et and et not in seen_titles:
                        seen_titles.add(et)
                        papers.append(ep)
            except Exception:
                pass

    # Fallback to arxiv if Semantic Scholar returned nothing
    if not papers:
        papers = _arxiv_fallback(query, limit)

    return {"papers": papers, "query": query, "count": len(papers)}


# ---------------------------------------------------------------------------
# AI Scientist v2-style iterative citation collection
# ---------------------------------------------------------------------------

def _format_papers_for_llm(papers: list[dict]) -> str:
    """Format collected papers as a numbered list for LLM context."""
    if not papers:
        return "(none yet)"
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(f"{i}. {p['title']} ({p.get('year', '?')})")
    return "\n".join(lines)


def _parse_query_response(response: str) -> str:
    """Extract search query from LLM JSON response."""
    try:
        data = _json.loads(response.strip())
        if isinstance(data, dict):
            return data.get("query", "")
    except Exception:
        pass
    m = re.search(r'\{[^}]+\}', response)
    if m:
        try:
            data = _json.loads(m.group(0))
            return data.get("query", "")
        except Exception:
            pass
    return ""


def _parse_selection_response(response: str, max_idx: int) -> list[int]:
    """Extract list of paper indices from LLM JSON response."""
    # Try to find a JSON array in the response
    for candidate in [response.strip(), *re.findall(r'\[[^\]]*\]', response)]:
        try:
            indices = _json.loads(candidate)
            if isinstance(indices, list):
                return [i for i in indices if isinstance(i, int) and 0 <= i < max_idx]
        except Exception:
            pass
    return []


_QUERY_SYSTEM = (
    "You are an academic research librarian. Given an experiment description "
    "and a list of already-collected reference papers, identify what topic area "
    "is still missing from the bibliography.\n\n"
    "If the bibliography already has adequate coverage (typically 10+ papers "
    "covering the main method, related work, evaluation baselines, and "
    "theoretical foundations), respond with exactly:\n"
    "No more citations needed\n\n"
    "Otherwise, respond with a JSON object:\n"
    '{"description": "Brief description of what is missing", '
    '"query": "3-6 word Semantic Scholar search query"}\n\n'
    "Rules:\n"
    "- Use broad, general academic terms (not narrow jargon)\n"
    "- Each query should target ONE specific missing topic\n"
    "- Do not repeat previous queries\n"
    "- Output ONLY the JSON or the termination phrase, nothing else"
)

_SELECT_SYSTEM = (
    "You are an academic reference selector. Given an experiment and candidate "
    "papers, select which papers are relevant and should be added to the "
    "bibliography.\n"
    "Return a JSON array of indices (0-based) of papers to keep.\n"
    "Example: [0, 2, 4]\n"
    "If none are relevant, return: []\n"
    "Output ONLY the JSON array, nothing else."
)


async def _llm_select_relevant(
    candidates: list[dict], experiment_summary: str, papers_summary: str,
    *, fail_open: bool = False,
) -> list[dict]:
    """Run the ``_SELECT_SYSTEM`` relevance selector over *candidates*.

    Returns the relevant subset. On LLM failure returns the candidates
    unchanged (the round≥2 conservative default). Extracted so ROUND 1 can
    filter its results too — previously only rounds ≥2 were filtered, so when
    S2 was dead and round 1 fell back to a bare arXiv keyword search, off-topic
    papers ("optimization" matched polynomial-opt, topology-opt, …) entered the
    bibliography unfiltered and were cited.

    *fail_open* is for the ROUND-1 caller: ``_parse_selection_response``
    returns ``[]`` both for "nothing is relevant" and for an unparseable reply,
    and the two are indistinguishable. Dropping everything is safe in later
    rounds (the bibliography is already populated) but on round 1 it would ship
    a paper with NO references at all — strictly worse than an imprecise
    bibliography. So round 1 keeps the candidates when the selection comes back
    empty, and says so in the log.
    """
    if not candidates:
        return []
    if not experiment_summary or not experiment_summary.strip():
        return candidates
    try:
        candidates_text = "\n".join(
            f"[{i}] {p['title']} ({p.get('year', '?')}) - "
            f"{p.get('abstract', '')[:150]}"
            for i, p in enumerate(candidates)
        )
        select_user = (
            f"Experiment:\n{experiment_summary[:1000]}\n\n"
            f"Already in bibliography:\n{papers_summary}\n\n"
            f"Candidate papers to evaluate:\n{candidates_text}"
        )
        select_resp = await _llm_call(_SELECT_SYSTEM, select_user,
                                      temperature=0.0, max_tokens=200)
        indices = _parse_selection_response(select_resp, len(candidates))
        if not indices and fail_open:
            log.warning(
                "relevance selection returned nothing usable for %d candidate(s); "
                "keeping them (an empty bibliography is worse than an imprecise one)",
                len(candidates))
            return candidates
        return [candidates[i] for i in indices]
    except Exception as e:
        log.warning("relevance selection failed: %s (keeping all candidates)", e)
        return candidates


@mcp.tool()
async def collect_references_iterative(
    experiment_summary: str,
    keywords: str,
    max_rounds: int = 20,
    min_papers: int = 10,
) -> dict:
    """AI Scientist v2-style iterative citation collection.

    Round 1: searches Semantic Scholar using the provided keywords.
    Subsequent rounds: LLM analyzes collected papers + experiment context,
    identifies gaps, generates a targeted query, searches, and LLM selects
    relevant papers. Stops when LLM says no more needed or min_papers reached.

    Args:
        experiment_summary: Description of the experiment and its results
        keywords: Initial search keywords (used for round 1)
        max_rounds: Maximum number of search rounds (default 20)
        min_papers: Minimum papers before early termination allowed (default 10)

    Returns:
        {papers: [{title, authors, year, abstract, bibtex, cite_key}],
         query: original keywords, count: N, rounds_used: M}
    """
    all_papers: list[dict] = []
    seen_titles: set[str] = set()
    all_queries: list[str] = []

    def _add_papers(new_papers: list[dict]) -> int:
        added = 0
        for p in new_papers:
            t = (p.get("title") or "").lower()
            if t and t not in seen_titles:
                seen_titles.add(t)
                all_papers.append(p)
                added += 1
        return added

    # ── Round 1: initial keyword search ──────────────────────────────────
    # Split long keywords into shorter sub-queries for better S2 coverage
    kw_parts = [k.strip() for k in re.split(r'[,;]', keywords) if k.strip()]
    if not kw_parts:
        kw_parts = [keywords]
    # Also create a shortened version (first 5 words) of the full keywords
    kw_words = keywords.split()
    if len(kw_words) > 5:
        kw_parts.append(" ".join(kw_words[:5]))

    s2_returned_any = False
    _round1_s2: list[dict] = []
    for i, kw in enumerate(kw_parts[:4]):
        if i > 0:
            _time.sleep(1.0)
        results = _search_s2_sync(kw, limit=10)
        if results:
            s2_returned_any = True
        _round1_s2.extend(results)
        all_queries.append(kw)
    # Round-1 S2 hits were previously trusted as "high precision" and added
    # UNFILTERED, but an imprecise keyword query returns off-topic keyword
    # matches (an audit of a real run found ~6/17 off-topic refs — antenna
    # "tiling", ceramic-tile drilling — one of which was cited in the paper).
    # Filter them through the SAME relevance selector the fallback / later rounds
    # use, when there is an experiment to judge against. Fail-open: a selector
    # failure keeps every ref (an empty bibliography is strictly worse than an
    # imprecise one), so this only ever removes confirmed off-topic matches.
    if _round1_s2 and experiment_summary and experiment_summary.strip():
        _round1_s2 = await _llm_select_relevant(
            _round1_s2, experiment_summary, "", fail_open=True)
    _add_papers(_round1_s2)

    # arXiv fallback if S2 returned nothing at all. Like the S2 round-1 hits
    # above, a bare keyword fallback is low-precision, so filter it through the
    # same relevance selector rather than shipping every keyword match.
    fallback_used = False
    if not all_papers:
        fallback_used = True
        fb = _arxiv_fallback(keywords, 8)
        fb = await _llm_select_relevant(fb, experiment_summary,
                                        _format_papers_for_llm(all_papers),
                                        fail_open=True)
        _add_papers(fb)

    # If no experiment_summary, return round-1 results only (backward compat)
    if not experiment_summary or not experiment_summary.strip():
        return {"papers": all_papers, "query": keywords, "count": len(all_papers),
                "rounds_used": 1, "productive_rounds": 1 if all_papers else 0,
                "s2_available": s2_returned_any, "fallback_used": fallback_used}

    # ── Rounds 2..max_rounds: LLM-guided iterative search ────────────────
    rounds_used = 1
    productive_rounds = 1 if all_papers else 0
    for round_num in range(2, max_rounds + 1):
        rounds_used = round_num
        papers_summary = _format_papers_for_llm(all_papers)

        # Stage 1: LLM generates search query
        try:
            query_user = (
                f"Experiment:\n{experiment_summary[:1500]}\n\n"
                f"Already collected papers ({len(all_papers)}):\n{papers_summary}\n\n"
                f"Previous queries: {all_queries}\n"
            )
            query_resp = await _llm_call(_QUERY_SYSTEM, query_user,
                                         temperature=0.3, max_tokens=200)
        except Exception as e:
            log.warning("Round %d: LLM query generation failed: %s", round_num, e)
            continue

        # Check for termination signal
        if "no more citations needed" in query_resp.lower():
            log.info("Round %d: LLM says no more citations needed", round_num)
            break

        new_query = _parse_query_response(query_resp)
        if not new_query:
            log.warning("Round %d: could not parse query from LLM response", round_num)
            continue
        if new_query.lower() in {q.lower() for q in all_queries}:
            log.info("Round %d: duplicate query %r, skipping", round_num, new_query)
            continue
        all_queries.append(new_query)

        # Search S2 with the new query
        _time.sleep(1.0)
        candidates = _search_s2_sync(new_query, limit=10)
        new_candidates = [p for p in candidates
                          if (p.get("title") or "").lower() not in seen_titles]
        if not new_candidates:
            continue

        # Stage 2: LLM selects relevant papers (same selector round 1 now uses)
        selected = await _llm_select_relevant(
            new_candidates, experiment_summary, papers_summary)

        added = _add_papers(selected)
        if added:
            productive_rounds += 1
        log.info("Round %d: query=%r, candidates=%d, selected=%d, total=%d",
                 round_num, new_query, len(new_candidates), len(selected),
                 len(all_papers))

    if rounds_used > productive_rounds:
        log.warning(
            "collect_references: %d of %d rounds added nothing (S2 available=%s, "
            "arXiv fallback used=%s) — rounds_used counts loop iterations, not "
            "productive retrieval",
            rounds_used - productive_rounds, rounds_used, s2_returned_any,
            fallback_used)
    return {
        "papers": all_papers,
        "query": keywords,
        "count": len(all_papers),
        # ``rounds_used`` counts loop ITERATIONS. When the retrieval backend is
        # down every round no-ops, so a bare rounds_used=13 reads as productive
        # work that never happened; the fields below make that visible.
        "rounds_used": rounds_used,
        "productive_rounds": productive_rounds,
        "s2_available": s2_returned_any,
        "fallback_used": fallback_used,
    }


# ---------------------------------------------------------------------------
# Uploaded / checkpoint file access tools
# ---------------------------------------------------------------------------

_CHECKPOINT_DIR: str = _os.environ.get("ARI_CHECKPOINT_DIR", "")


@mcp.tool()
def list_uploaded_files() -> dict:
    """List files uploaded by the user in the current experiment checkpoint.

    Returns a list of filenames and sizes available in the uploads/ subdirectory.
    Use read_uploaded_file to read any file by name.

    Returns:
        {files: [{name, size_bytes}], checkpoint_dir: str}
    """
    ckpt = _CHECKPOINT_DIR
    if not ckpt:
        return {"files": [], "error": "ARI_CHECKPOINT_DIR not set"}
    from pathlib import Path as _Path
    uploads = _Path(ckpt) / "uploads"
    if not uploads.exists():
        return {"files": [], "checkpoint_dir": ckpt}
    files = []
    for f in sorted(uploads.iterdir()):
        if f.is_file():
            files.append({"name": f.name, "size_bytes": f.stat().st_size})
    return {"files": files, "checkpoint_dir": ckpt}


@mcp.tool()
def read_uploaded_file(filename: str, max_chars: int = 50000) -> dict:
    """Read the content of an uploaded file from the checkpoint uploads directory.

    Supports text files (.md, .txt, .yaml, .yml, .json, .csv, .py, .tex, etc.).
    Binary files will return a size indication instead of content.

    Args:
        filename: Name of the file to read (as returned by list_uploaded_files)
        max_chars: Maximum characters to return (default 50000)

    Returns:
        {name: str, content: str, size_bytes: int}
    """
    ckpt = _CHECKPOINT_DIR
    if not ckpt:
        return {"error": "ARI_CHECKPOINT_DIR not set"}
    from pathlib import Path as _Path
    # Sanitize: prevent directory traversal
    safe_name = _Path(filename).name
    fpath = _Path(ckpt) / "uploads" / safe_name
    if not fpath.exists():
        return {"error": f"File not found: {safe_name}"}
    size = fpath.stat().st_size
    # Try to read as text
    _TEXT_EXTS = {
        ".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".py",
        ".tex", ".bib", ".sh", ".cfg", ".ini", ".toml", ".xml",
        ".html", ".css", ".js", ".ts", ".r", ".m", ".c", ".cpp",
        ".h", ".java", ".go", ".rs", ".jl", ".log",
    }
    ext = fpath.suffix.lower()
    if ext in _TEXT_EXTS or size < 100_000:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n... (truncated, {size} bytes total)"
            return {"name": safe_name, "content": text, "size_bytes": size}
        except Exception:
            pass
    return {
        "name": safe_name,
        "content": f"[Binary file, {size} bytes. Cannot display as text.]",
        "size_bytes": size,
    }


if __name__ == "__main__":
    mcp.run()
