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

try:
    try:
        from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore
    except ImportError:
        from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("idea")
except Exception:
    pass

# ── ARI LLM config ────────────────────────────────────────────────────────────

def _model() -> str:
    # Phase-specific override (ARI_MODEL_IDEA) wins over the global model so
    # the GUI Settings page's per-phase model picker actually takes effect.
    return (os.environ.get("ARI_MODEL_IDEA")
            or os.environ.get("ARI_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")

def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE")
    if ari is not None:
        return ari or None          # Explicit empty string → None (OpenAI etc.)
    legacy = os.environ.get("LLM_API_BASE", "")
    if legacy:
        return legacy
    # Only fall back to Ollama URL when model string explicitly indicates Ollama
    if _model().startswith("ollama"):
        return "http://127.0.0.1:11434"
    return None

def _s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "") or os.environ.get("S2_API_KEY", "")

# ── VirSci-live (vendor-wrap) env contract ────────────────────────────────────
# The setting surface is env-only (ARI_IDEA_VIRSCI_*); GUI and CLI just set
# these (see ari-core run.py / api_experiment.py), and mcp/client.py propagates
# them to this subprocess via env={**os.environ}. Unset → current behaviour.

def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default

def _virsci_real() -> bool:
    return _env_flag("ARI_IDEA_VIRSCI_REAL")

def _virsci_k() -> int:
    return _env_int("ARI_IDEA_VIRSCI_K", 7)            # group_max_discuss_iteration

def _virsci_team_size() -> int:
    return _env_int("ARI_IDEA_VIRSCI_TEAM_SIZE", 3)    # max_teammember

def _virsci_n_authors() -> int:
    return _env_int("ARI_IDEA_VIRSCI_N_AUTHORS", 16)   # select_coauthors pool

def _virsci_n_papers() -> int:
    return _env_int("ARI_IDEA_VIRSCI_N_PAPERS", 800)   # SPECTER2 corpus size

def _virsci_max_teams() -> int | None:
    raw = os.environ.get("ARI_IDEA_VIRSCI_MAX_TEAMS", "").strip()
    return int(raw) if raw.isdigit() else None

def _virsci_specter2_model() -> str:
    return os.environ.get("ARI_IDEA_VIRSCI_SPECTER2_MODEL", "").strip() or "allenai/specter2_base"

def _checkpoint_dir() -> Path:
    """Output root for the frozen snapshot + run logs.

    Prefers ARI_CHECKPOINT_DIR (set by the harness); otherwise materialises
    under workspace/checkpoints/<ts>_<slug> per the repo output convention.
    """
    ckpt = os.environ.get("ARI_CHECKPOINT_DIR")
    if ckpt:
        return Path(ckpt)
    import time as _time
    ts = _time.strftime("%Y%m%d_%H%M%S")
    root = Path(os.environ.get("ARI_WORKSPACE", "workspace")) / "checkpoints" / f"{ts}_idea_virsci"
    root.mkdir(parents=True, exist_ok=True)
    return root

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,year,citationCount,authors"

def _sanitize(text: str) -> str:
    """Strip null bytes and other control chars that break API JSON parsing."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

async def _llm(system: str, user: str, temperature: float = 0.7) -> str:
    kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": _sanitize(system)},
            {"role": "user",   "content": _sanitize(user)},
        ],
        "temperature": temperature,
        "timeout": 120,
    }
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            resp = await litellm.acompletion(**kwargs)
            raw = resp.choices[0].message.content or ""
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        except Exception as e:
            last_err = e
            await asyncio.sleep(2 ** _attempt)
    raise last_err  # type: ignore[misc]

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
    ancestor_block: str = "",
) -> dict:
    """
    Adapted from VirSci SciTeam.generate_idea().
    Uses VirSci's Prompts templates if available; falls back to inline prompts.
    ARI's LLM (litellm) replaces agentscope agents.

    ``ancestor_block`` (Phase 2): a free-form context string describing
    research directions explored by ancestor runs. Injected between the
    existing-idea recap and the topic prompt so each agent sees what was
    already considered. The vendor templates remain unmodified — this is
    a wrapper-layer concatenation only.
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
                + ancestor_block
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

# ── VirSci-live (vendor-wrap) real path ───────────────────────────────────────

async def _run_real_virsci(topic: str, n_ideas: int, ancestor_block: str = "") -> tuple[list[dict], dict]:
    """Run VirSci's real select_coauthors + generate_idea on an S2 snapshot.

    Returns ``(raw_ideas, meta)`` shaped like ``_virsci_discussion_loop`` output
    so the downstream 9-key contract mapping is identical. Raises on missing
    deps / runtime errors so ``generate_ideas`` can degrade to the re-impl loop.
    ``ancestor_block`` (lineage context) is forwarded so the real path stays
    aware of prior research directions, matching the re-impl loop.
    """
    from snapshot import build_snapshot  # heavy deps imported lazily
    import virsci_runtime

    out_dir = _checkpoint_dir()
    n_authors = _virsci_n_authors()
    n_papers = _virsci_n_papers()

    snap = await asyncio.to_thread(build_snapshot, topic, out_dir, n_authors, n_papers)
    result = await asyncio.to_thread(
        virsci_runtime.run_virsci_live,
        topic,
        snap,
        model=_model(),            # reuse server's LLM-config helpers (no re-import)
        api_base=_api_base(),
        n_ideas=n_ideas,
        k=_virsci_k(),
        team_size=_virsci_team_size(),
        n_authors=n_authors,
        max_teams=_virsci_max_teams(),
        ancestor_block=ancestor_block,
        log_dir=str(out_dir / "virsci_logs"),
        specter2_model=_virsci_specter2_model(),
    )

    raw_ideas: list[dict] = []
    for idea in result.get("ideas", []):
        nov = idea["novelty_score"]
        feas = idea["feasibility_score"]
        raw_ideas.append({
            "title":             idea["title"],
            "description":       idea["description"],
            "novelty":           f"Novelty score: {round(nov * 10, 1)}",
            "feasibility":       f"Feasibility score: {round(feas * 10, 1)}",
            "experiment_plan":   idea["experiment_plan"],
            "novelty_score":     nov,
            "feasibility_score": feas,
            "clarity_score":     idea["clarity_score"],
        })
    return raw_ideas, result


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

    # Phase 2: load ancestor catalog (read-only) so VirSci agents stay aware
    # of prior research thread and can refine / extend / explicitly pivot.
    # vendor/virsci is untouched — we inject via prompt concatenation only.
    ancestor_block = ""
    try:
        _ckpt = os.environ.get("ARI_CHECKPOINT_DIR")
        if _ckpt:
            # Lazy import: ari-core may not be on PYTHONPATH for some
            # standalone test invocations of this skill.
            try:
                from ari.lineage import (  # type: ignore
                    format_ancestor_pool_for_virsci,
                    get_idea_pool_for_ckpt,
                )
            except Exception:
                format_ancestor_pool_for_virsci = None  # type: ignore
                get_idea_pool_for_ckpt = None  # type: ignore
            if format_ancestor_pool_for_virsci and get_idea_pool_for_ckpt:
                pool = get_idea_pool_for_ckpt(
                    _ckpt, walk_ancestors=True, exclude_self=True,
                )
                ancestor_block = format_ancestor_pool_for_virsci(pool)
    except Exception:
        ancestor_block = ""  # never block idea generation on lineage errors

    # Gap analysis
    gap_raw = await _llm(
        "Identify research gaps in 3-4 sentences. Be concise. No markdown.",
        f"Topic: {topic}\n\nLiterature:\n{paper_reference[:3000]}",
        temperature=0.3,
    )

    # Idea generation: real vendor-wrap path (ARI_IDEA_VIRSCI_REAL) runs the
    # actual VirSci select_coauthors + generate_idea on an S2 snapshot; on any
    # failure (missing deps, runtime error, empty output) it degrades to the
    # current re-implemented discussion loop so behaviour never regresses.
    real_meta: dict | None = None
    raw_ideas: list[dict] | None = None
    if _virsci_real():
        try:
            raw_ideas, real_meta = await _run_real_virsci(topic, n_ideas, ancestor_block)
            if not raw_ideas:
                raw_ideas, real_meta = None, None  # empty → fall through
        except Exception as e:  # never block ideation on the real path
            print(f"[idea] VirSci real path failed, degrading to re-impl: {e}",
                  file=sys.stderr)
            raw_ideas, real_meta = None, None
    if raw_ideas is None:
        tasks = [
            _virsci_discussion_loop(
                topic=f"{topic} [variant {i+1}/{n_ideas}]",
                paper_reference=paper_reference,
                n_agents=n_agents,
                max_rounds=max(1, max_discussion_rounds),
                ancestor_block=ancestor_block,
            )
            for i in range(n_ideas)
        ]
        raw_ideas = list(await asyncio.gather(*tasks))

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

    if real_meta is not None:
        virsci_status = "real_wrap"
    else:
        virsci_status = (
            "reimpl: VirSci prompts loaded from vendor/virsci submodule"
            if _VIRSCI_PROMPTS_AVAILABLE
            else "reimpl: VirSci submodule unavailable — using inline fallback prompts"
        )

    # Phase 2.5: when the child checkpoint already has an idea.json with a
    # pinned idea (written by ``_api_launch_sub_experiment`` after
    # inherit_idea_index materialisation), prepend those entries so the
    # caller's chosen direction stays at ideas[0]. Newly generated ideas
    # become alternatives at ideas[N+1..]. Without this, generate_ideas
    # would silently overwrite the inherit directive and BFTS would drift.
    pinned_ideas: list[dict] = []
    pinned_metadata: dict = {}
    try:
        _ckpt = os.environ.get("ARI_CHECKPOINT_DIR")
        if _ckpt:
            _existing = Path(_ckpt) / "idea.json"
            if _existing.exists():
                _old = json.loads(_existing.read_text())
                for _idea in (_old.get("ideas") or []):
                    if isinstance(_idea, dict) and _idea.get("_pinned"):
                        pinned_ideas.append(_idea)
                if pinned_ideas:
                    # Preserve provenance fields from the seed file.
                    for _k in ("_inherited_from",):
                        if _k in _old:
                            pinned_metadata[_k] = _old[_k]
    except Exception:
        pass

    # lineage decisions: drop newly generated ideas whose title matches a pinned
    # idea (case-insensitive, whitespace-normalised). Without this, a
    # child's VirSci that saw the parent's selected idea via the
    # ancestor catalog often re-proposes near-duplicates as alternatives,
    # cluttering child idea.json with effectively the same direction
    # under slightly different titles. Strict title match keeps the
    # heuristic conservative — semantic-similarity dedup is left for
    # downstream tooling.
    def _norm(title: str) -> str:
        return " ".join((title or "").lower().split())

    pinned_keys = {_norm(p.get("title", "")) for p in pinned_ideas}
    deduped_new = [
        idea for idea in ideas_out
        if _norm(idea.get("title", "")) not in pinned_keys
    ]
    final_ideas = pinned_ideas + deduped_new

    out: dict = {
        "gap_analysis":      gap_raw,
        "ideas":             final_ideas,
        "primary_metric":    metric_data.get("primary_metric", ""),
        "higher_is_better":  metric_data.get("higher_is_better", True),
        "metric_rationale":  metric_data.get("metric_rationale", ""),
        "papers_analyzed":   (real_meta["papers_indexed"] if real_meta else len(all_papers)),
        "n_agents":          (real_meta["n_agents"] if real_meta else n_agents),
        "discussion_rounds": (real_meta["discussion_rounds"] if real_meta else max_discussion_rounds),
        "virsci_integration_status": virsci_status,
    }
    if pinned_metadata:
        out.update(pinned_metadata)
    return out


if __name__ == "__main__":
    mcp.run()
