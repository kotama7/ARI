"""
ari-skill-idea: Prior work survey + LLM-based novel idea generation

P2 exception: only generate_ideas contains LLM calls.
Following AI Scientist v2:
  1. survey() retrieves related papers deterministically
  2. generate_ideas() uses LLM to analyze prior work and
     generate novel ideas not present in prior work

"""
import os

import nest_asyncio
nest_asyncio.apply()

import arxiv
import litellm
from mcp.server.fastmcp import FastMCP
from semanticscholar import SemanticScholar

mcp = FastMCP("idea-generation-skill")


def _get_model() -> str:
    return os.environ.get("ARI_LLM_MODEL", "ollama_chat/qwen3:32b")


def _get_api_base() -> str | None:
    return os.environ.get("ARI_LLM_API_BASE", "http://127.0.0.1:11434")


@mcp.tool()
def survey(topic: str, max_papers: int = 5) -> dict:
    """Survey prior work related to the topic (arxiv + Semantic Scholar, no LLM).

    Returns:
        papers: list of {title, abstract, url}
    """
    max_papers = min(max_papers, 10)
    papers = []

    try:
        client = arxiv.Client()
        search = arxiv.Search(query=topic, max_results=max_papers)
        for result in client.results(search):
            papers.append({
                "title": result.title,
                "abstract": result.summary[:1000],
                "url": result.entry_id,
            })
    except Exception:
        pass

    if len(papers) < max_papers:
        try:
            sch = SemanticScholar()
            remaining = max_papers - len(papers)
            results = sch.search_paper(topic, limit=remaining)
            existing_titles = {p["title"] for p in papers}
            for paper in results:
                if paper.title not in existing_titles:
                    papers.append({
                        "title": paper.title,
                        "abstract": (paper.abstract or "")[:1000],
                        "url": paper.url or "",
                    })
        except Exception:
            pass

    return {"papers": papers[:max_papers]}


@mcp.tool()
async def generate_ideas(
    topic: str,
    papers: list,
    experiment_context: str = "",
    n_ideas: int = 3,
) -> dict:
    """Analyze prior work and generate novel research ideas not in prior work using LLM.

    Idea generation following AI Scientist v2:
      1. Analyze methods, limitations, and gaps in prior work
      2. Propose novel ideas not attempted in existing research
      3. Assign feasibility and novelty scores to each idea

    P2 exception: This tool calls LLM (idea generation is used in the pre-exploration phase).

    Args:
        topic: Research topic
        papers: Output of survey() (list of papers)
        experiment_context: Current experiment settings and constraints
        n_ideas: Number of ideas to generate (1-5)

    Returns:
        ideas: list of {
            title: str,
            description: str,
            novelty: str (what is new vs prior work),
            feasibility: str (why it can be done),
            experiment_plan: str (concrete experiment steps)
        }
        gap_analysis: str (prior work gaps identified by LLM)
    """
    import json, re

    n_ideas = max(1, min(5, n_ideas))
    papers_text = "\n".join(
        f"- [{i+1}] {p.get('title','?')}: {p.get('abstract','')[:400]}"
        for i, p in enumerate(papers[:8])
    )

    system_prompt = (
        "You are a creative research scientist specialized in generating novel, "
        "feasible research ideas.\n"
        "Your task:\n"
        "1. Analyze the provided papers and identify research gaps\n"
        "2. Generate ideas that are NOT attempted in the prior work\n"
        "3. Each idea must be concrete and experimentally testable\n"
        "Return ONLY valid JSON. No markdown fences."
    )

    user_prompt = (
        f"Research topic: {topic}\n\n"
        f"Prior work (from survey):\n{papers_text}\n\n"
        + (f"Current experiment context:\n{experiment_context[:500]}\n\n" if experiment_context else "")
        + f"Generate {n_ideas} novel research ideas NOT already explored in the above papers.\n\n"
        "Return JSON with this exact structure:\n"
        "{\n"
        '  "gap_analysis": "2-3 sentences on what prior work has NOT explored",\n'
        '  "primary_metric": "the single most important metric name to measure (e.g. accuracy, error, throughput)",\n'
        '  "higher_is_better": true,\n'
        '  "metric_rationale": "why this metric was chosen",\n'
        '  "ideas": [\n'
        "    {\n"
        '      "title": "short idea title",\n'
        '      "description": "what to do and why",\n'
        '      "novelty": "what makes this different from prior work",\n'
        '      "feasibility": "why this is achievable",\n'
        '      "experiment_plan": "concrete steps to test this idea"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    kwargs = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    api_base = _get_api_base()
    if api_base:
        kwargs["api_base"] = api_base

    try:
        response = await litellm.acompletion(**kwargs)
        raw = response.choices[0].message.content or ""
        # Strip <think> tags
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
        result = json.loads(raw)
        return {
            "gap_analysis": result.get("gap_analysis", ""),
            "ideas": result.get("ideas", []),
            "papers_analyzed": len(papers),
        }
    except Exception as e:
        return {
            "gap_analysis": "",
            "ideas": [],
            "error": str(e),
            "papers_analyzed": len(papers),
        }


if __name__ == "__main__":
    mcp.run()
