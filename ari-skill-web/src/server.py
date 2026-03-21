"""ari-skill-web: Web search and page fetch MCP server. P2 compliant."""
from __future__ import annotations
import re
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web-skill")


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
        from ddgs import DDGS
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
    import unicodedata, re as _re
    import urllib.request as _req, urllib.parse as _parse, json as _json

    def _clean_key(s: str) -> str:
        """Normalize cite key: remove accents, keep only safe chars."""
        nfkd = unicodedata.normalize("NFKD", s)
        ascii_s = nfkd.encode("ASCII", "ignore").decode("ascii")
        return _re.sub(r"[^a-zA-Z0-9:_@{},-]+", "", ascii_s).lower()

    fields = "title,authors,year,abstract,citationStyles"
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={_parse.quote(query)}&fields={fields}&limit={limit}"
    )
    import os as _os_s2
    s2_key = _os_s2.environ.get("S2_API_KEY", "")
    try:
        req_obj = _req.Request(url, headers={"x-api-key": s2_key} if s2_key else {})
        with _req.urlopen(req_obj, timeout=15) as resp:
            data = _json.loads(resp.read())
    except Exception as e:
        return {"papers": [], "error": str(e), "query": query, "count": 0}

    papers = []
    for p in data.get("data", []):
        bibtex_raw = p.get("citationStyles", {}).get("bibtex", "")
        # Clean cite key to ASCII-safe format
        if bibtex_raw:
            nl = bibtex_raw.find("\n")
            first_line = bibtex_raw[:nl] if nl > 0 else bibtex_raw.split("\n")[0]
            clean_first = _clean_key(first_line)
            bibtex = clean_first + ("\n" + bibtex_raw.split("\n", 1)[1] if "\n" in bibtex_raw else "")
            # Extract cite key from @Type{key,
            m = _re.search(r"\{([^,}]+)", clean_first)
            cite_key = m.group(1) if m else ""
        else:
            bibtex = ""
            cite_key = ""
        papers.append({
            "title": p.get("title", ""),
            "authors": [a.get("name", "") for a in p.get("authors", [])[:4]],
            "year": str(p.get("year", "")),
            "abstract": (p.get("abstract") or "")[:300],
            "bibtex": bibtex_raw,  # keep original for refs.bib
            "cite_key": cite_key,
        })

    # Run extra queries and merge (deduplicated by title)
    if extra_queries:
        import time as _teq
        seen_titles = {p["title"].lower() for p in papers}
        for eq in (extra_queries or [])[:3]:
            _teq.sleep(1.0)
            try:
                _eq_url = (
                    "https://api.semanticscholar.org/graph/v1/paper/search"
                    f"?query={_parse.quote(eq)}&fields={fields}&limit={limit}"
                )
                _eq_req = _req.Request(_eq_url, headers={"x-api-key": s2_key} if s2_key else {})
                with _req.urlopen(_eq_req, timeout=15) as _resp2:
                    _eq_data = _json.loads(_resp2.read())
                for _ep in _eq_data.get("data", []):
                    _et = (_ep.get("title") or "").lower()
                    if _et and _et not in seen_titles:
                        seen_titles.add(_et)
                        _ebibtex = _ep.get("citationStyles", {}).get("bibtex", "") or ""
                        _ecite_key = ""
                        if _ebibtex:
                            _enl = _ebibtex.find("\n")
                            _efirst = _ebibtex[:_enl] if _enl > 0 else _ebibtex
                            _eclean = _clean_key(_efirst)
                            _ebibtex = _eclean + ("\n" + _ebibtex.split("\n", 1)[1] if "\n" in _ebibtex else "")
                            import re as _re2
                            _em = _re2.search(r"\{([^,}]+)", _eclean)
                            _ecite_key = _em.group(1) if _em else ""
                        papers.append({
                            "title": _ep.get("title", ""),
                            "authors": [a.get("name", "") for a in _ep.get("authors", [])],
                            "year": str(_ep.get("year", "")),
                            "abstract": (_ep.get("abstract") or "")[:300],
                            "bibtex": _ebibtex,
                            "cite_key": _ecite_key,
                        })
            except Exception:
                pass

    return {"papers": papers, "query": query, "count": len(papers)}

if __name__ == "__main__":
    mcp.run()
