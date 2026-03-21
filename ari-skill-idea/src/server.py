"""
ari-skill-idea: VirSci multi-agent idea generation — ARI MCP adapter

Attribution:
    Architecture from VirSci (Virtual Scientists), ACL 2025.
    Su et al., "Many Heads Are Better Than One: Improved Scientific Idea Generation
    by A LLM-Based Multi-Agent System", https://arxiv.org/abs/2410.09403
    Original code: https://github.com/InternScience/Virtual-Scientists (Apache 2.0)
    Forked: https://github.com/kotama7/Virtual-Scientists

    This adapter wraps VirSci's core discussion logic (Prompts, team discussion flow)
    with ARI's execution infrastructure (litellm, Semantic Scholar API, MCP interface).
    VirSci's agentscope/ollama dependencies are replaced with ARI's LLM routing.

Integration:
    - vendor/virsci/sci_platform/utils/prompt.py   → Prompts class (discussion templates)
    - vendor/virsci/sci_platform/utils/scientist_utils.py → extract_between_json_tags, extract_metrics
    - Discussion flow (generate_idea loop) adapted from SciTeam.generate_idea()
    - Model/API: ARI_LLM_MODEL / ARI_LLM_API_BASE (fallback to LLM_MODEL / LLM_API_BASE)
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import litellm
import requests
from mcp.server.fastmcp import FastMCP
from semanticscholar import SemanticScholar

# ── VirSci vendor import ──────────────────────────────────────────────────────
_VIRSCI_PATH = Path(__file__).parent.parent / "vendor" / "virsci" / "sci_platform"
if str(_VIRSCI_PATH) not in sys.path:
    sys.path.insert(0, str(_VIRSCI_PATH))

try:
    # Direct file exec to avoid agentscope/__init__ chain importing loguru etc.
    _prompt_path = _VIRSCI_PATH / "utils" / "prompt.py"
    _ns: dict = {}
    exec(compile(_prompt_path.read_text(), str(_prompt_path), "exec"), _ns)
    _VirSciPrompts = _ns["Prompts"]
    _VIRSCI_PROMPTS_AVAILABLE = True
except Exception:
    _VirSciPrompts = None
    _VIRSCI_PROMPTS_AVAILABLE = False

def _extract_between_json_tags(text: str) -> str:
    """Extract content between ```json ... ``` tags (from VirSci scientist_utils)."""
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"\{.*\}", text, re.DOTALL)
    return m2.group(0) if m2 else text

mcp = FastMCP("idea-generation-skill")

# ── ARI LLM config ────────────────────────────────────────────────────────────

def _model() -> str:
    return os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama_chat/qwen3:32b"

def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE")
    return (ari if ari is not None else os.environ.get("LLM_API_BASE", "http://127.0.0.1:11434")) or None

def _s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "") or os.environ.get("S2_API_KEY", "")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,year,citationCount,authors"

async def _llm(system: str, user: str, temperature: float = 0.7) -> str:
    kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "timeout": 120,
    }
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

# ── Semantic Scholar paper retrieval (replaces VirSci's paper_search) ─────────

def _s2_search(query: str, limit: int = 8) -> list[dict]:
    headers = {}
    if key := _s2_api_key():
        headers["x-api-key"] = key
    try:
        r = requests.get(
            f"{S2_BASE}/paper/search",
            params={"query": query, "limit": limit, "fields": S2_FIELDS},
            headers=headers, timeout=15,
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []

def _s2_citations(paper_id: str, limit: int = 5) -> list[dict]:
    """Retrieve citing papers from Semantic Scholar citation graph (2-hop traversal)."""
    headers = {}
    if key := _s2_api_key():
        headers["x-api-key"] = key
    try:
        r = requests.get(
            f"{S2_BASE}/paper/{paper_id}/citations",
            params={"limit": limit, "fields": S2_FIELDS},
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        return [item.get("citingPaper", {}) for item in items]
    except Exception:
        return []


def _format_references(papers: list[dict]) -> str:
    """Format papers as VirSci-style reference text."""
    lines = []
    for i, p in enumerate(papers[:8], 1):
        title = p.get("title") or "?"
        abstract = (p.get("abstract") or "")[:300]
        year = p.get("year") or ""
        lines.append(f"[{i}] ({year}) {title}\n    {abstract}")
    return "\n\n".join(lines)

# ── VirSci-style discussion loop (adapted from SciTeam.generate_idea) ─────────

async def _virsci_discussion_loop(
    topic: str,
    paper_reference: str,
    n_agents: int,
    max_rounds: int,
) -> dict:
    """
    Adapted from VirSci SciTeam.generate_idea().
    Uses VirSci's Prompts templates if available; falls back to inline prompts.
    ARI's LLM (litellm) replaces agentscope agents.
    """

    # Build prompt templates from VirSci if available, else inline fallback
    if _VIRSCI_PROMPTS_AVAILABLE and _VirSciPrompts is not None:
        prompt_task      = _VirSciPrompts.prompt_task
        prompt_reference = _VirSciPrompts.prompt_reference
        prompt_topic_fmt = _VirSciPrompts.prompt_topic      # .format(topic)
        prompt_response  = _VirSciPrompts.prompt_response
        prompt_existing  = _VirSciPrompts.prompt_existing_idea  # .format(old_idea)
    else:
        prompt_task = (
            "You are an ambitious scientist proposing a new impactful research idea. "
            "Improve the existing idea or propose a new one that contributes significantly to the field."
        )
        prompt_reference = "References (for inspiration only — do not copy):\n{}\n"
        prompt_topic_fmt = "When proposing your idea, please elaborate on the proposed topic: {}\n"
        prompt_response  = (
            "Respond in this format:\n"
            "Thought: <your reasoning>\n"
            "```json\n"
            '{"Title": "...", "Idea": "...", "Experiment": "...", '
            '"Novelty": <1-10>, "Feasibility": <1-10>, "Clarity": <1-10>}\n'
            "```"
        )
        prompt_existing  = "Here is the idea your team has already generated: '''{}''\n"

    # Agent role names (VirSci-style scientist personas)
    agent_roles = [
        "a senior researcher specializing in experimental design",
        "a critic focused on identifying weaknesses and prior work overlap",
        "a domain expert with deep technical knowledge",
        "a synthesizer who improves and refines ideas from team discussion",
    ][:n_agents]

    old_idea: str = ""
    best_idea: str = ""
    best_score: float = 0.0

    for round_i in range(max_rounds):
        for role_i, role_desc in enumerate(agent_roles):
            # Build VirSci-style prompt (adapted from SciTeam.generate_idea)
            existing_block = prompt_existing.format(old_idea) if old_idea else ""
            idea_prompt = (
                prompt_task
                + existing_block
                + prompt_topic_fmt.format(topic)
                + prompt_reference.format(paper_reference)
                + prompt_response
            )

            system = f"You are {role_desc} in a multi-agent scientific research team."
            reply = await _llm(system, idea_prompt)

            raw_json = _extract_between_json_tags(reply)
            try:
                idea_data = json.loads(raw_json)
                # Score: VirSci uses Novelty*2 + Feasibility + Clarity
                n_score = float(idea_data.get("Novelty", 5))
                f_score = float(idea_data.get("Feasibility", 5))
                c_score = float(idea_data.get("Clarity", 5))
                score = n_score * 2 + f_score + c_score
                if score >= best_score:
                    best_score = score
                    best_idea  = raw_json
                old_idea = raw_json
            except Exception:
                old_idea = reply[:500]

    # Parse best idea
    try:
        best_data = json.loads(best_idea) if best_idea else {}
    except Exception:
        best_data = {}

    return {
        "title":           best_data.get("Title", "Research Idea"),
        "description":     best_data.get("Idea", old_idea[:500]),
        "novelty":         best_data.get("Novelty_explanation", f"Novelty score: {best_data.get('Novelty', '?')}"),
        "feasibility":     best_data.get("Feasibility_explanation", f"Feasibility score: {best_data.get('Feasibility', '?')}"),
        "experiment_plan": best_data.get("Experiment", ""),
        "novelty_score":   min(float(best_data.get("Novelty", 5)), 10) / 10,
        "feasibility_score": min(float(best_data.get("Feasibility", 5)), 10) / 10,
        "clarity_score":   min(float(best_data.get("Clarity", 5)), 10) / 10,
        "virsci_prompts_used": _VIRSCI_PROMPTS_AVAILABLE,
    }

# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def survey(topic: str, max_papers: int = 8) -> dict:
    """Survey prior work via Semantic Scholar API (live retrieval, no LLM).

    Replaces VirSci's paper_search() with ARI's Semantic Scholar integration.

    Args:
        topic:      Research topic / query
        max_papers: Maximum papers to return (capped at 15)

    Returns:
        papers: list of {title, abstract, year, citationCount, url}
    """
    max_papers = min(max_papers, 15)
    raw = _s2_search(topic, limit=max_papers)

    if not raw:
        try:
            import signal
            def _timeout_handler(s, f): raise TimeoutError("semanticscholar lib timeout")
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(10)
            try:
                sch = SemanticScholar()
                results = sch.search_paper(topic, limit=max_papers)
            finally:
                signal.alarm(0)
            raw = [
                {"title": p.title, "abstract": p.abstract or "",
                 "year": getattr(p, "year", None),
                 "citationCount": getattr(p, "citationCount", 0),
                 "paperId": getattr(p, "paperId", None)}
                for p in results
            ]
        except Exception:
            pass

    papers, seen = [], set()
    for p in raw:
        title = p.get("title") or ""
        if title in seen:
            continue
        seen.add(title)
        pid = p.get("paperId", "")
        papers.append({
            "title": title,
            "abstract": (p.get("abstract") or "")[:1000],
            "year": p.get("year"),
            "citationCount": p.get("citationCount", 0),
            "paperId": pid,
            "url": f"https://www.semanticscholar.org/paper/{pid}" if pid else "",
        })

    # Enrich with citation graph: fetch citing papers for top 3 results (2-hop traversal)
    for p in papers[:3]:
        if p.get("paperId"):
            cites = _s2_citations(p["paperId"], limit=3)
            for c in cites:
                ctitle = c.get("title") or ""
                if ctitle and ctitle not in seen:
                    seen.add(ctitle)
                    cpid = c.get("paperId", "")
                    papers.append({
                        "title": ctitle,
                        "abstract": (c.get("abstract") or "")[:1000],
                        "year": c.get("year"),
                        "citationCount": c.get("citationCount", 0),
                        "paperId": cpid,
                        "url": f"https://www.semanticscholar.org/paper/{cpid}" if cpid else "",
                    })

    return {"papers": papers[:max_papers]}


@mcp.tool()
async def generate_ideas(
    topic: str,
    papers: list,
    experiment_context: str = "",
    n_ideas: int = 3,
    n_agents: int = 4,
    max_discussion_rounds: int = 2,
    max_recursion_depth: int = 0,
) -> dict:
    """Generate novel research ideas using VirSci's multi-agent discussion flow.

    Integration:
    - VirSci Prompts templates used directly when available (via vendor/virsci submodule)
    - VirSci's generate_idea() discussion loop adapted for litellm + ARI LLM routing
    - Paper retrieval via Semantic Scholar API (replaces VirSci's paper_search/proxy)
    - Model: ARI_LLM_MODEL env var (fallback: LLM_MODEL, then ollama qwen3:32b)

    Args:
        topic:                Research topic
        papers:               Output of survey()
        experiment_context:   Current experiment constraints (optional)
        n_ideas:              Number of ideas to generate (1-5)
        n_agents:             VirSci team size: agent roles to activate (2-4)
        max_discussion_rounds: Discussion iterations (0 = single-pass)
        max_recursion_depth:  Reserved for Issue #3 (unused)

    Returns:
        ideas, gap_analysis, primary_metric, higher_is_better, metric_rationale,
        papers_analyzed, virsci_integration_status
    """
    n_ideas  = max(1, min(5, n_ideas))
    n_agents = max(2, min(4, n_agents))
    max_discussion_rounds = max(0, min(3, max_discussion_rounds))

    # Build reference text for VirSci prompts
    all_papers: list[dict] = list(papers)
    if not all_papers:
        all_papers = _s2_search(topic, limit=8)
    paper_reference = _format_references(all_papers)
    if experiment_context:
        paper_reference += f"\n\nExperiment context: {experiment_context[:400]}"

    # Gap analysis
    gap_raw = await _llm(
        "Identify research gaps in 3-4 sentences. Be concise. No markdown.",
        f"Topic: {topic}\n\nLiterature:\n{paper_reference[:3000]}",
        temperature=0.3,
    )

    # Run n_ideas parallel VirSci-style discussions
    tasks = [
        _virsci_discussion_loop(
            topic=f"{topic} [variant {i+1}/{n_ideas}]",
            paper_reference=paper_reference,
            n_agents=n_agents,
            max_rounds=max(1, max_discussion_rounds),
        )
        for i in range(n_ideas)
    ]
    raw_ideas = await asyncio.gather(*tasks)

    # Sort by novelty score (VirSci: novelty*2 + feasibility + clarity)
    raw_ideas.sort(
        key=lambda x: x["novelty_score"] * 2 + x["feasibility_score"] + x["clarity_score"],
        reverse=True,
    )

    # Metric selection by LLM (ARI philosophy: not hardcoded)
    metric_raw = await _llm(
        "Select evaluation metric for research. Return ONLY valid JSON, no markdown.",
        (
            f"Topic: {topic}\nIdeas: {', '.join(i['title'] for i in raw_ideas[:3])}\n"
            'Return: {"primary_metric": str, "higher_is_better": bool, "metric_rationale": str}'
        ),
        temperature=0.1,
    )
    m = re.search(r"\{.*\}", metric_raw, re.DOTALL)
    metric_data: dict = {}
    if m:
        try:
            metric_data = json.loads(m.group(0))
        except Exception:
            pass

    # Format ideas for ARI interface compatibility
    ideas_out = []
    for idea in raw_ideas:
        overall = round(
            (idea["novelty_score"] * 2 + idea["feasibility_score"] + idea["clarity_score"]) / 4, 2
        )
        ideas_out.append({
            "title":           idea["title"],
            "description":     idea["description"],
            "novelty":         idea["novelty"],
            "feasibility":     idea["feasibility"],
            "experiment_plan": idea["experiment_plan"],
            "novelty_score":   idea["novelty_score"],
            "feasibility_score": idea["feasibility_score"],
            "overall_score":   overall,
        })

    virsci_status = (
        "VirSci prompts loaded from vendor/virsci submodule"
        if _VIRSCI_PROMPTS_AVAILABLE
        else "VirSci submodule unavailable — using inline fallback prompts"
    )

    return {
        "gap_analysis":      gap_raw,
        "ideas":             ideas_out,
        "primary_metric":    metric_data.get("primary_metric", ""),
        "higher_is_better":  metric_data.get("higher_is_better", True),
        "metric_rationale":  metric_data.get("metric_rationale", ""),
        "papers_analyzed":   len(all_papers),
        "n_agents":          n_agents,
        "discussion_rounds": max_discussion_rounds,
        "virsci_integration_status": virsci_status,
    }


if __name__ == "__main__":
    mcp.run()
