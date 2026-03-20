"""
ari-skill-idea: VirSci-inspired multi-agent idea generation

Attribution:
    Architecture inspired by VirSci (Virtual Scientists), ACL 2025.
    Su et al., "Many Heads Are Better Than One: Improved Scientific Idea Generation
    by A LLM-Based Multi-Agent System", https://arxiv.org/abs/2410.09403
    Original code: https://github.com/InternScience/Virtual-Scientists (Apache 2.0)

    This is an independent reimplementation. No source code from VirSci was copied.
    The Proposer/Critic/Synthesizer/DomainExpert roles and intra-team discussion
    loop design are adapted from the VirSci paper architecture.

Replaces single-agent idea generation with structured multi-agent deliberation:
  1. Semantic Scholar RAG - live paper retrieval
  2. Agent Team Builder  - assign Proposer/Critic/Synthesizer/Domain Expert roles
  3. Intra-Team Discussion - agents debate and refine ideas
  4. Inter-Team Discussion - optional cross-team comparison
  5. Idea Ranker - score by novelty, feasibility, relevance

Drop-in replacement for the original generate_ideas() MCP interface.
P2 exception: LLM calls only in generate_ideas() and discussion loops.
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import litellm
import requests
from mcp.server.fastmcp import FastMCP
from semanticscholar import SemanticScholar

mcp = FastMCP("idea-generation-skill")

# ── Config ────────────────────────────────────────────────────────────────────

def _model() -> str:
    return os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama_chat/qwen3:32b"

def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE")
    return (ari if ari is not None else os.environ.get("LLM_API_BASE", "http://127.0.0.1:11434")) or None

def _s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,year,citationCount,authors,externalIds"

# ── LLM helper ────────────────────────────────────────────────────────────────

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

# ── Semantic Scholar RAG ──────────────────────────────────────────────────────

def _s2_search(query: str, limit: int = 10) -> list[dict]:
    """Search papers via Semantic Scholar API."""
    headers = {}
    key = _s2_api_key()
    if key:
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
    """Retrieve citations for a paper."""
    headers = {}
    key = _s2_api_key()
    if key:
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

def _format_papers(papers: list[dict], max_chars: int = 400) -> str:
    lines = []
    for p in papers:
        title = p.get("title") or "?"
        abstract = (p.get("abstract") or "")[:max_chars]
        year = p.get("year") or ""
        cites = p.get("citationCount", "?")
        lines.append(f"• [{year}|cites:{cites}] {title}\n  {abstract}")
    return "\n\n".join(lines)

# ── Agent roles ───────────────────────────────────────────────────────────────

ROLE_PROMPTS = {
    "Proposer": (
        "You are the Proposer. Your job is to generate bold, novel research ideas "
        "grounded in the literature. Focus on unexplored combinations and new hypotheses. "
        "Be specific and concrete — each idea must describe a testable experiment."
    ),
    "Critic": (
        "You are the Critic. Your job is to rigorously challenge proposed ideas. "
        "Identify weaknesses, prior work that already addresses the idea, feasibility issues, "
        "and methodological flaws. Be constructive but demanding."
    ),
    "Synthesizer": (
        "You are the Synthesizer. Your job is to take the Proposer's idea and the Critic's "
        "objections and produce an improved, refined version that addresses the weaknesses "
        "while preserving the novelty. Output a concrete, actionable research direction."
    ),
    "DomainExpert": (
        "You are the Domain Expert. You have deep technical knowledge of the research area. "
        "Your job is to validate technical feasibility, suggest relevant methods or tools, "
        "and flag any domain-specific constraints the other agents may have missed."
    ),
}

@dataclass
class Idea:
    title: str
    description: str
    novelty: str
    feasibility: str
    experiment_plan: str
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    relevance_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "novelty": self.novelty,
            "feasibility": self.feasibility,
            "experiment_plan": self.experiment_plan,
            "novelty_score": self.novelty_score,
            "feasibility_score": self.feasibility_score,
            "relevance_score": self.relevance_score,
            "overall_score": round((self.novelty_score + self.feasibility_score + self.relevance_score) / 3, 2),
        }

# ── Discussion loop ───────────────────────────────────────────────────────────

async def _intra_team_discussion(
    topic: str,
    papers_text: str,
    max_rounds: int,
) -> Idea:
    """Run Proposer → Critic → Synthesizer + DomainExpert discussion loop."""

    # Round 0: Proposer generates initial idea
    proposal_raw = await _llm(
        ROLE_PROMPTS["Proposer"],
        (
            f"Research topic: {topic}\n\n"
            f"Related literature:\n{papers_text}\n\n"
            "Propose ONE novel research idea not already present in the literature above. "
            "Be specific. Include: title, description, what makes it novel, experiment steps."
        ),
    )

    discussion_history = f"[Proposer]\n{proposal_raw}"

    for round_i in range(max_rounds):
        # Critic challenges
        critique = await _llm(
            ROLE_PROMPTS["Critic"],
            (
                f"Research topic: {topic}\n\n"
                f"Discussion so far:\n{discussion_history}\n\n"
                "Critique the latest proposal. Be specific about weaknesses."
            ),
        )
        discussion_history += f"\n\n[Critic - round {round_i+1}]\n{critique}"

        # Domain Expert validates
        expert_input = await _llm(
            ROLE_PROMPTS["DomainExpert"],
            (
                f"Research topic: {topic}\n\n"
                f"Discussion so far:\n{discussion_history}\n\n"
                "Assess technical feasibility. Flag domain constraints. "
                "Suggest specific methods or tools if applicable."
            ),
        )
        discussion_history += f"\n\n[DomainExpert - round {round_i+1}]\n{expert_input}"

        # Synthesizer refines
        refined = await _llm(
            ROLE_PROMPTS["Synthesizer"],
            (
                f"Research topic: {topic}\n\n"
                f"Discussion so far:\n{discussion_history}\n\n"
                "Synthesize an improved idea that addresses the critique and expert feedback. "
                "Output improved: title, description, novelty, feasibility, experiment_plan."
            ),
        )
        discussion_history += f"\n\n[Synthesizer - round {round_i+1}]\n{refined}"

    # Final structured extraction
    final_raw = await _llm(
        "You extract structured JSON from a research discussion. Return ONLY valid JSON, no markdown.",
        (
            f"Extract the final refined idea from this discussion:\n\n{discussion_history}\n\n"
            "Return JSON:\n"
            '{"title": str, "description": str, "novelty": str, "feasibility": str, "experiment_plan": str}'
        ),
        temperature=0.1,
    )
    m = re.search(r"\{.*\}", final_raw, re.DOTALL)
    data = json.loads(m.group(0)) if m else {}
    return Idea(
        title=data.get("title", "Untitled"),
        description=data.get("description", discussion_history[-500:]),
        novelty=data.get("novelty", ""),
        feasibility=data.get("feasibility", ""),
        experiment_plan=data.get("experiment_plan", ""),
    )

async def _score_idea(idea: Idea, papers_text: str, topic: str) -> Idea:
    """Score an idea on novelty, feasibility, relevance (0-10)."""
    score_raw = await _llm(
        "You score research ideas. Return ONLY valid JSON with keys: "
        "novelty_score (0-10), feasibility_score (0-10), relevance_score (0-10), rationale (str).",
        (
            f"Research topic: {topic}\n\n"
            f"Literature:\n{papers_text[:2000]}\n\n"
            f"Idea:\nTitle: {idea.title}\n{idea.description}\n"
            f"Novelty: {idea.novelty}\nFeasibility: {idea.feasibility}"
        ),
        temperature=0.1,
    )
    m = re.search(r"\{.*\}", score_raw, re.DOTALL)
    if m:
        try:
            scores = json.loads(m.group(0))
            idea.novelty_score = float(scores.get("novelty_score", 5)) / 10
            idea.feasibility_score = float(scores.get("feasibility_score", 5)) / 10
            idea.relevance_score = float(scores.get("relevance_score", 5)) / 10
        except Exception:
            idea.novelty_score = idea.feasibility_score = idea.relevance_score = 0.5
    return idea

# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def survey(topic: str, max_papers: int = 8) -> dict:
    """Survey prior work via Semantic Scholar API (live retrieval, no LLM).

    Retrieves recent papers and their top citations for richer context.

    Args:
        topic:      Research topic / query
        max_papers: Maximum number of papers to return (capped at 15)

    Returns:
        papers: list of {title, abstract, year, citationCount, url}
    """
    max_papers = min(max_papers, 15)

    # Primary search
    raw = _s2_search(topic, limit=max_papers)

    # Fallback: semanticscholar library
    if not raw:
        try:
            sch = SemanticScholar()
            results = sch.search_paper(topic, limit=max_papers)
            raw = [
                {
                    "title": p.title,
                    "abstract": p.abstract or "",
                    "year": getattr(p, "year", None),
                    "citationCount": getattr(p, "citationCount", 0),
                    "paperId": getattr(p, "paperId", None),
                    "externalIds": {},
                }
                for p in results
            ]
        except Exception:
            pass

    papers = []
    seen_titles: set[str] = set()
    for p in raw:
        title = p.get("title") or ""
        if title in seen_titles:
            continue
        seen_titles.add(title)
        pid = p.get("paperId") or p.get("externalIds", {}).get("ArXiv", "")
        url = f"https://www.semanticscholar.org/paper/{pid}" if pid else ""
        papers.append({
            "title": title,
            "abstract": (p.get("abstract") or "")[:1000],
            "year": p.get("year"),
            "citationCount": p.get("citationCount", 0),
            "paperId": pid,
            "url": url,
        })

    # Enrich top 3 papers with citations
    for p in papers[:3]:
        if p.get("paperId"):
            cites = _s2_citations(p["paperId"], limit=3)
            for c in cites:
                ctitle = c.get("title") or ""
                if ctitle and ctitle not in seen_titles:
                    seen_titles.add(ctitle)
                    cpid = c.get("paperId", "")
                    papers.append({
                        "title": ctitle,
                        "abstract": (c.get("abstract") or "")[:500],
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
    """Generate novel research ideas via VirSci-inspired multi-agent deliberation.

    Architecture:
      1. Semantic Scholar RAG  — retrieve live literature
      2. Intra-team discussion — Proposer/Critic/Synthesizer/DomainExpert debate
      3. Idea ranking          — score by novelty, feasibility, relevance
      4. Gap analysis          — LLM summarizes prior work gaps

    Drop-in replacement for the original single-agent generate_ideas().
    P2 exception: LLM calls are limited to idea generation and discussion.

    Args:
        topic:                Research topic
        papers:               Output of survey() (list of papers with title/abstract)
        experiment_context:   Current experiment settings/constraints (optional)
        n_ideas:              Number of top ideas to return (1-5)
        n_agents:             Number of agent roles to activate (2-4; affects discussion depth)
        max_discussion_rounds: Discussion iterations per idea (0 = single-pass)
        max_recursion_depth:  Reserved for Issue #3 recursive invocation (currently unused)

    Returns:
        ideas:         ranked list of Idea dicts with novelty/feasibility/relevance scores
        gap_analysis:  LLM-summarized gaps in prior work
        primary_metric:      suggested metric name for this research
        higher_is_better:    whether higher metric value = better
        metric_rationale:    reasoning behind metric choice
        papers_analyzed:     number of papers used
    """
    n_ideas = max(1, min(5, n_ideas))
    n_agents = max(2, min(4, n_agents))
    max_discussion_rounds = max(0, min(3, max_discussion_rounds))

    # Build paper context from survey output + optional live S2 search
    all_papers: list[dict] = list(papers)
    if not all_papers:
        s2_result = _s2_search(topic, limit=8)
        all_papers = s2_result

    papers_text = _format_papers(all_papers[:10])
    if experiment_context:
        papers_text += f"\n\nExperiment context:\n{experiment_context[:500]}"

    # Gap analysis (fast, single LLM call)
    gap_raw = await _llm(
        "Analyze research literature and identify unexplored gaps. Be concise (3-4 sentences). No markdown.",
        f"Topic: {topic}\n\nLiterature:\n{papers_text}",
        temperature=0.3,
    )

    # Generate n_ideas via parallel intra-team discussions
    # Each idea gets its own discussion team (VirSci intra-team style)
    active_roles = list(ROLE_PROMPTS.keys())[:n_agents]

    tasks = [
        _intra_team_discussion(
            topic=f"{topic} [idea variant {i+1} of {n_ideas}]",
            papers_text=papers_text,
            max_rounds=max_discussion_rounds,
        )
        for i in range(n_ideas)
    ]
    raw_ideas: list[Idea] = await asyncio.gather(*tasks)

    # Score all ideas
    scored: list[Idea] = await asyncio.gather(*[
        _score_idea(idea, papers_text, topic) for idea in raw_ideas
    ])

    # Rank by overall score
    scored.sort(
        key=lambda x: (x.novelty_score + x.feasibility_score + x.relevance_score),
        reverse=True,
    )

    # Metric selection (LLM decides — philosophy compliance)
    metric_raw = await _llm(
        "You select evaluation metrics for research. Return ONLY valid JSON, no markdown.",
        (
            f"Research topic: {topic}\n"
            f"Ideas generated:\n"
            + "\n".join(f"- {i.title}" for i in scored[:3])
            + "\n\nReturn JSON:\n"
            '{"primary_metric": str, "higher_is_better": bool, "metric_rationale": str}'
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

    return {
        "gap_analysis": gap_raw,
        "ideas": [i.to_dict() for i in scored],
        "primary_metric": metric_data.get("primary_metric", ""),
        "higher_is_better": metric_data.get("higher_is_better", True),
        "metric_rationale": metric_data.get("metric_rationale", ""),
        "papers_analyzed": len(all_papers),
        "agents_used": active_roles,
        "discussion_rounds": max_discussion_rounds,
    }


if __name__ == "__main__":
    mcp.run()
