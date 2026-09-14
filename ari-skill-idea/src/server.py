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
import contextvars
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
import requests
from mcp.server.fastmcp import FastMCP

from ari.public.research_contract import (
    RESEARCH_CONTRACT_V1,
    CitationEdgeV1,
    parse_survey_snapshot,
)

from contracts import (
    SPECTER2_DEFAULT_REVISION,
    build_generation_lock,
    build_idea_handoff,
    build_survey_snapshot,
    enrich_legacy_ideas,
    inline_snapshot,
    load_survey_snapshot,
    metric_legacy_projection,
    paper_projection,
    parse_metric_json,
)

log = logging.getLogger(__name__)

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


def _bounded_env_int(name: str, current: int, minimum: int, maximum: int) -> int:
    """Apply an optional operational cap without changing MCP defaults."""

    raw = os.environ.get(name, "").strip()
    if not raw:
        return current
    try:
        return max(minimum, min(maximum, int(raw)))
    except ValueError:
        return current

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


def _virsci_specter2_revision() -> str:
    return (
        os.environ.get("ARI_IDEA_VIRSCI_SPECTER2_REVISION", "").strip()
        or SPECTER2_DEFAULT_REVISION
    )

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

_PROMPT_TRACE: contextvars.ContextVar[list[tuple[str, str, float]] | None] = (
    contextvars.ContextVar("ari_idea_prompt_trace", default=None)
)
_GENERATION_SEED: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "ari_idea_generation_seed", default=None
)


def _llm_timeout_s() -> float:
    """Per-request LLM timeout, in seconds."""
    try:
        return float(os.environ.get("ARI_IDEA_LLM_TIMEOUT_S", "") or 120)
    except ValueError:
        return 120.0


async def _llm(system: str, user: str, temperature: float = 0.7) -> str:
    trace = _PROMPT_TRACE.get()
    if trace is not None:
        trace.append((system, user, temperature))
    kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": _sanitize(system)},
            {"role": "user",   "content": _sanitize(user)},
        ],
        "temperature": temperature,
        # 120 s suits a hosted API. A CLI-backed endpoint (ari.llm.cli_server,
        # whose own per-request budget defaults to 600 s) spawns a `claude`
        # subprocess per call and routinely exceeds it, so the client gave up
        # before the backend had failed or answered. Overridable, same default.
        "timeout": _llm_timeout_s(),
    }
    if (seed := _GENERATION_SEED.get()) is not None:
        kwargs["seed"] = seed
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

def _s2_get(path: str, *, params: dict, timeout: int) -> requests.Response:
    """GET one S2 endpoint with bounded retry for transient throttling."""

    headers = {}
    if key := _s2_api_key():
        headers["x-api-key"] = key
    attempts = 5
    for attempt in range(attempts):
        try:
            response = requests.get(
                f"{S2_BASE}/{path.lstrip('/')}",
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == attempts - 1:
                raise
            delay = min(float(2**attempt), 30.0)
            log.warning(
                "Semantic Scholar transport failure (attempt %d/%d); "
                "retrying in %.1fs",
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)
            continue
        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        if retryable and attempt < attempts - 1:
            try:
                delay = float(response.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                delay = float(2**attempt)
            delay = max(0.0, min(delay, 30.0))
            log.warning(
                "Semantic Scholar HTTP %s (attempt %d/%d); retrying in %.1fs",
                response.status_code,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response
    raise RuntimeError("unreachable Semantic Scholar retry state")

def _s2_search(query: str, limit: int = 8) -> list[dict]:
    r = _s2_get(
        "paper/search",
        params={"query": query, "limit": limit, "fields": S2_FIELDS},
        timeout=15,
    )
    payload = r.json()
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("Semantic Scholar search response has no data list")
    return data

def _s2_citations(paper_id: str, limit: int = 5) -> list[dict]:
    """Retrieve citing papers from Semantic Scholar citation graph (2-hop traversal)."""
    r = _s2_get(
        f"paper/{paper_id}/citations",
        params={"limit": limit, "fields": S2_FIELDS},
        timeout=10,
    )
    items = r.json().get("data", [])
    if not isinstance(items, list):
        raise ValueError("Semantic Scholar citation response has no data list")
    return [item.get("citingPaper", {}) for item in items]


def _format_references(papers: list[dict]) -> str:
    """Format papers as VirSci-style reference text."""
    lines = []
    for i, p in enumerate(papers[:8], 1):
        title = p.get("title") or "?"
        abstract = (p.get("abstract") or "")[:300]
        year = p.get("year") or ""
        record_id = p.get("canonical_id") or p.get("paperId") or f"record-{i}"
        lines.append(f"[{i}] [id={record_id}] ({year}) {title}\n    {abstract}")
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

async def _run_real_virsci(
    topic: str,
    n_ideas: int,
    ancestor_block: str = "",
    seed_papers: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Run VirSci's real select_coauthors + generate_idea on an S2 snapshot.

    Returns ``(raw_ideas, meta)`` shaped like ``_virsci_discussion_loop`` output
    so the downstream 9-key contract mapping is identical. Raises on missing
    deps / runtime errors so ``generate_ideas`` can degrade to the re-impl loop.
    ``ancestor_block`` (lineage context) is forwarded so the real path stays
    aware of prior research directions, matching the re-impl loop.
    ``seed_papers`` (the already-fetched survey papers) is passed to
    ``build_snapshot`` as a fallback corpus so a throttled/empty topic search
    can still ground on the vetted paperIds in hand instead of raising.
    """
    from snapshot import build_snapshot  # heavy deps imported lazily
    import virsci_runtime

    out_dir = _checkpoint_dir()
    n_authors = _virsci_n_authors()
    n_papers = _virsci_n_papers()

    snap = await asyncio.to_thread(
        build_snapshot, topic, out_dir, n_authors, n_papers, seed_papers=seed_papers
    )
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
        specter2_revision=_virsci_specter2_revision(),
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

def _load_virsci_snapshot_papers(max_papers: int) -> list[dict]:
    """Reuse the frozen VirSci snapshot corpus from the idea stage.

    Plain helper, NOT an MCP tool: it was never meant to be agent-visible
    (``survey`` calls it directly). See docs/reference/mcp_tools.md
    § "ari-skill-idea — literature survey + idea generation" — the
    ``@mcp.tool()`` decorator once drifted here from
    ``survey``/``generate_ideas``; ``tests/test_server.py`` now pins the
    registered tool list via ``mcp.list_tools()``.

    The idea stage already surveyed this run's topic and froze the corpus under
    ``<checkpoint>/virsci_snapshot/papers/<i>.txt`` (``repr`` of
    ``{title, abstract, year, citation}``, relevance-ordered). Reading it here lets
    a per-node ``survey()`` reuse that work instead of issuing a redundant live S2
    re-query. Returns ``[]`` when no frozen snapshot exists (then survey falls back
    to live S2). Checkpoint dir comes from ``ARI_CHECKPOINT_DIR`` (set by the loop).
    """
    import os as _os
    import ast as _ast
    from pathlib import Path as _Path
    ckpt = _os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not ckpt:
        return []
    pdir = _Path(ckpt) / "virsci_snapshot" / "papers"
    if not pdir.is_dir():
        return []
    files = sorted(
        pdir.glob("*.txt"),
        key=lambda p: int(p.stem) if p.stem.isdigit() else (1 << 30),
    )
    out: list[dict] = []
    for f in files:
        try:
            rec = _ast.literal_eval(f.read_text())
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        title = (rec.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "abstract": (rec.get("abstract") or "")[:1000],
            "year": rec.get("year"),
            "citationCount": rec.get("citation", rec.get("citationCount", 0)),
            "paperId": "",
            "url": "",
        })
        if len(out) >= max_papers:
            break
    return out


@mcp.tool()
def survey(
    topic: str,
    max_papers: int = 8,
    mode: str = "record",
    snapshot_path: str = "survey_snapshot_v1.json",
    provider: str = "semantic-scholar",
) -> dict:
    """Create or replay a content-addressed prior-work snapshot.

    ``record`` and ``live`` pin one provider and never switch backends after an
    outage. ``replay`` performs no network access and fails if the requested
    checkpoint artifact is absent or its digest is invalid.  The legacy
    ``papers`` projection is returned alongside ``SurveySnapshotV1`` during the
    checkpoint support window.
    """
    if not topic.strip():
        raise ValueError("topic cannot be empty")
    if mode not in {"record", "live", "replay", "frozen"}:
        raise ValueError("mode must be record, live, replay, or frozen")
    if provider not in {"semantic-scholar", "virsci-snapshot"}:
        raise ValueError("unsupported pinned survey provider")
    max_papers = max(1, min(max_papers, 15))
    checkpoint = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()

    if mode == "replay":
        if not checkpoint:
            raise ValueError("replay requires ARI_CHECKPOINT_DIR")
        snapshot = load_survey_snapshot(checkpoint, snapshot_path)
        if snapshot.query != topic:
            raise ValueError("replay snapshot query does not match the requested topic")
        return {
            "papers": paper_projection(snapshot)[:max_papers],
            "survey_snapshot": snapshot.model_dump(mode="json"),
            "survey_snapshot_digest": snapshot.snapshot_digest,
            "execution_mode": "replay",
        }

    if provider == "virsci-snapshot" or mode == "frozen":
        raw = _load_virsci_snapshot_papers(max_papers)
        if not raw:
            raise FileNotFoundError("pinned VirSci snapshot is unavailable")
        snapshot = build_survey_snapshot(
            raw,
            query=topic,
            mode="frozen",
            provider="virsci-snapshot",
            provider_version="ari-virsci-snapshot/v1",
            retrieved_at=None,
            byte_reproducible=True,
            checkpoint_dir=checkpoint or None,
        )
    else:
        retrieved_at = datetime.now(timezone.utc)
        raw = _s2_search(topic, limit=max_papers)
        papers = list(raw)
        edges: list[CitationEdgeV1] = []
        seen_ids = {
            str(item.get("paperId") or "").strip().lower()
            for item in papers
            if item.get("paperId")
        }
        # One bounded citation hop. A provider error is explicit: a record-mode
        # run may be retried, but it must not silently become a different corpus.
        for paper in list(raw)[:3]:
            target_id = str(paper.get("paperId") or "").strip()
            if not target_id:
                continue
            for citing in _s2_citations(target_id, limit=3):
                source_id = str(citing.get("paperId") or "").strip()
                if not source_id or source_id.lower() == target_id.lower():
                    continue
                if source_id.lower() not in seen_ids:
                    papers.append(citing)
                    seen_ids.add(source_id.lower())
                edges.append(
                    CitationEdgeV1(
                        source_id=f"s2:{source_id.lower()}",
                        target_id=f"s2:{target_id.lower()}",
                        relation="cites",
                        provider="semantic-scholar",
                    )
                )
        # Only retain records needed for the bounded result and edges between
        # retained nodes. Citation additions are ordered by provider response.
        papers = papers[:max_papers]
        retained_ids = {
            f"s2:{str(item.get('paperId') or '').strip().lower()}"
            for item in papers
            if item.get("paperId")
        }
        edges = [
            edge
            for edge in edges
            if edge.source_id in retained_ids and edge.target_id in retained_ids
        ]
        snapshot = build_survey_snapshot(
            papers,
            query=topic,
            mode=mode,
            provider="semantic-scholar",
            provider_version="graph-v1",
            retrieved_at=retrieved_at,
            byte_reproducible=False,
            citation_edges=edges,
            checkpoint_dir=checkpoint or None,
        )

    return {
        "papers": paper_projection(snapshot)[:max_papers],
        "survey_snapshot": snapshot.model_dump(mode="json"),
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "execution_mode": mode,
    }


def _platform_constraint_note() -> str:
    """Verified platform-capability constraint folded into the idea topic (P2c).

    Reads ``{ARI_CHECKPOINT_DIR}/platform_capabilities.json`` written by the HPC
    skill's run-start probe. Without this, plans were generated platform-blind
    (e.g. promising profiler-counter measurements on a partition whose probe shows
    the profiler is absent) and had to be corrected downstream. Returns ``""``
    when no probe data exists, keeping legacy behaviour. Relays measured facts
    only — no hardware knowledge lives here.
    """
    try:
        import json as _json
        from pathlib import Path as _Path
        ckpt = os.environ.get("ARI_CHECKPOINT_DIR", "")
        if not ckpt:
            return ""
        p = _Path(ckpt) / "platform_capabilities.json"
        if not p.is_file():
            return ""
        d = _json.loads(p.read_text())
        missing = sorted(t for t, ok in (d.get("available") or {}).items() if not ok)
        if not missing:
            return ""
        return (
            "\n\n[Platform constraint, verified by probe on the execution "
            f"platform: the following tools are NOT available: {', '.join(missing)}. "
            "Plan ONLY measurements obtainable with available tooling or computable "
            "by the experiment's own code.]")
    except Exception:
        return ""


async def select_metric_contracts(
    topic: str, raw_ideas: list[dict], snapshot
) -> dict:
    """Turn ideas into falsifiable contracts, or refuse.

    Shared by ``generate_ideas`` and ``mint_contract_for_proposal`` so the two
    cannot drift: the deterministic adapter downstream rejects anything
    incomplete, and the invariants stated in this prompt are the ones it
    enforces. A second copy of this prompt would be a second set of rules the
    validator does not know about.
    """
    # Scientific contract selection by LLM. The deterministic adapter below
    # validates every field and rejects incomplete output; it never guesses a
    # unit, citation, falsification condition, or evidence vocabulary.
    available_citations = [
        {"id": record.canonical_id, "title": record.title}
        for record in snapshot.records
    ]
    metric_raw = await _llm(
        (
            "Define falsifiable scientific contracts for the proposed ideas. "
            "Use only the supplied citation IDs and artifact digests. Return ONLY "
            "one valid JSON object; do not use markdown. Never write unknown/TBD units. "
            # Both rules below are hard schema invariants in MetricContractV1.
            # They used to be enforced but never stated, so a well-formed answer
            # -- direction "higher" with a goal in target_value, confidence 0.74 --
            # was rejected as invalid_metric_contract and every candidate died.
            "required_evidence is the ONE vocabulary of measurement names: every "
            "name appearing in operands values, in required_measured, and in "
            "correctness.requires must also appear in required_evidence. "
            "formula must be an arithmetic expression whose variables are "
            "EXACTLY the keys of operands -- not the evidence names, which are "
            "what those keys map to. "
            "target_value MUST be null unless direction is exactly \"target\"; a "
            "goal you merely hope to beat belongs in the rationale, not there. "
            "confidence is your own calibrated probability that this contract "
            "measures what it claims: below 0.8 the contract is held for human "
            "review and the idea cannot be admitted, so do not inflate it -- if "
            "you cannot honestly reach 0.8, simplify the contract until you can."
        ),
        (
            f"Topic: {topic}\n"
            f"Ideas: {json.dumps(raw_ideas, ensure_ascii=False)[:12000]}\n"
            f"Available citations: {json.dumps(available_citations, ensure_ascii=False)}\n"
            f"Available artifact digests: "
            f"{json.dumps([a.digest for a in snapshot.artifacts])}\n"
            "Return exactly this shape: "
            '{"metric_contract":{"name":str,"unit":str,'
            '"direction":"higher|lower|target|none",'
            '"comparison_scope":"same-environment|cross-environment|within-subject|not-applicable",'
            '"rationale":str,"required_evidence":[str,...],'
            '"correctness_required":bool,'
            '"normalization_ceiling":"measured|not-applicable",'
            '"target_value":number|null,'
            '"formula":"safe arithmetic expression over operand roles",'
            '"operands":{"value|baseline|proposed":"required_evidence_name"},'
            '"tolerance":{"absolute":number,"relative":number},'
            '"required_measured":[str,...],"invariants":[str,...],'
            '"correctness":{"expr":str,"requires":[str,...]}|null,'
            '"confidence":number},"idea_contracts":['
            '{"title":str,"hypothesis":str,'
            '"falsification_conditions":[str,...],"citations":[str,...],'
            '"artifact_references":[str,...],"limitations":[str,...]}]}'
        ),
        temperature=0.1,
    )
    return parse_metric_json(metric_raw)


@mcp.tool()
async def mint_contract_for_proposal(
    topic: str,
    proposal: dict,
    survey_snapshot_ref: str = "survey_snapshot_v1.json",
    experiment_context: str = "",
) -> dict:
    """Mint a typed Research Contract for a proposal this skill did not generate.

    WHY THIS EXISTS. Under ``ari.mode: ari_rqgm`` the proposal router owns root
    ideation and none of its generators mints a contract -- only this skill
    does. KCA admission then requires one, so a governed run was refused unless
    the router routed to the VirSci generator, which delegates here. VirSci is
    opt-in and default-OFF by design ("tests pass without VirSci installed"), so
    the governed path was effectively unreachable and the run fell through to
    ``cheap``, whose proposal carries no contract.

    Splitting minting from generation makes the two independent: any generator
    may propose, and the contract is stated and validated in exactly one place.
    The proposal supplies title/description/hypothesis/plan; this step supplies
    the falsification conditions, limitations, citations and metric contract --
    and refuses rather than inventing any of them, which is why an empty
    literature snapshot yields a rejection and not a fabricated citation.
    """
    checkpoint = os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not checkpoint:
        return {"contract_status": "rejected",
                "reason": "ARI_CHECKPOINT_DIR is unset, so the run's literature "
                          "snapshot cannot be located"}
    try:
        snapshot = load_survey_snapshot(checkpoint, survey_snapshot_ref)
    except Exception as exc:
        return {"contract_status": "rejected",
                "reason": f"survey snapshot unavailable: {exc}"}

    plan = proposal.get("experiment_plan") or ()
    raw_idea = {
        "title": str(proposal.get("title") or "").strip(),
        "description": str(proposal.get("short_description")
                           or proposal.get("description") or "").strip(),
        "hypothesis": str(proposal.get("hypothesis") or "").strip(),
        "experiment_plan": (
            "\n".join(str(step) for step in plan)
            if isinstance(plan, (list, tuple)) else str(plan)
        ),
        "novelty": "", "feasibility": "",
        "novelty_score": 0.0, "feasibility_score": 0.0, "clarity_score": 0.0,
    }
    if not raw_idea["title"]:
        return {"contract_status": "rejected", "reason": "proposal has no title"}

    metric_data = await select_metric_contracts(topic, [raw_idea], snapshot)
    lock = build_generation_lock(
        adapter="router-proposal",
        model=_model(),
        api_base=_api_base(),
        prompt_texts=[topic, json.dumps(raw_idea, ensure_ascii=False, sort_keys=True)],
        temperatures=[0.1],
        seed=_GENERATION_SEED.get(),
        snapshot=snapshot,
        topic=topic,
        experiment_context=experiment_context,
        generation_parameters={
            # The proposal is the input, not something this step generated, so
            # the only parameters that shaped the output are the contract call's.
            "n_ideas": 1,
            "source": "router-proposal",
        },
        model_revision=(
            os.environ.get("ARI_MODEL_IDEA_REVISION", "").strip() or _model()
        ),
    )
    idea_set, contract = build_idea_handoff(
        topic=topic,
        snapshot=snapshot,
        raw_ideas=[raw_idea],
        metric_data=metric_data,
        generation_lock=lock,
        generated_at=datetime.now(timezone.utc),
        requested_adapter="router-proposal",
        actual_adapter="router-proposal",
        fallback_reason=None,
    )
    return {
        "typed_schema_version": RESEARCH_CONTRACT_V1,
        "contract_status": "admitted" if contract else "rejected",
        "research_contract": (contract.model_dump(mode="json") if contract else None),
        "research_contract_digest": (
            contract.contract_digest if contract else None),
        "idea_set_digest": idea_set.idea_set_digest,
        "rejections": [item.model_dump(mode="json") for item in idea_set.rejections],
    }


@mcp.tool()
async def generate_ideas(
    topic: str,
    papers: list,
    experiment_context: str = "",
    n_ideas: int = 3,
    n_agents: int = 4,
    max_discussion_rounds: int = 2,
    max_recursion_depth: int = 0,
    survey_snapshot: dict | None = None,
    survey_snapshot_ref: str = "",
    seed: int | None = None,
    generation_mode: str = "auto",
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
        max_recursion_depth:  Reserved for recursive orchestration (unused)
        survey_snapshot:      Exact SurveySnapshotV1 returned by survey()
        survey_snapshot_ref:  Checkpoint-relative verified snapshot reference
        seed:                 Optional provider seed recorded in the generation lock
        generation_mode:      auto, default, or virsci (explicit virsci fails closed)

    Returns:
        ideas, gap_analysis, primary_metric, higher_is_better, metric_rationale,
        papers_analyzed, virsci_integration_status
    """
    if not topic.strip():
        raise ValueError("topic cannot be empty")
    if generation_mode not in {"auto", "default", "virsci"}:
        raise ValueError("generation_mode must be auto, default, or virsci")
    n_ideas = _bounded_env_int("ARI_IDEA_N_IDEAS", n_ideas, 1, 5)
    n_agents = _bounded_env_int("ARI_IDEA_N_AGENTS", n_agents, 2, 4)
    max_discussion_rounds = _bounded_env_int(
        "ARI_IDEA_DISCUSSION_ROUNDS", max_discussion_rounds, 0, 3
    )
    n_ideas = max(1, min(5, n_ideas))
    n_agents = max(2, min(4, n_agents))
    max_discussion_rounds = max(0, min(3, max_discussion_rounds))
    generated_at = datetime.now(timezone.utc)
    checkpoint = os.environ.get("ARI_CHECKPOINT_DIR", "").strip() or None
    prompt_trace: list[tuple[str, str, float]] = []
    trace_token = _PROMPT_TRACE.set(prompt_trace)
    seed_token = _GENERATION_SEED.set(seed)

    # Platform-capability constraint (P2c, idea layer): the run-start probe has
    # already measured tool availability ON the execution platform by the time
    # ideas are generated. Folding the verified facts into the TOPIC makes every
    # downstream prompt (re-impl loop AND the vendored VirSci engine, which both
    # consume the topic string) plan only measurements the platform can take —
    # fixing feasibility at the SOURCE instead of re-expressing claims later.
    # Data, not knowledge: relays only what the probe measured; "" when no probe.
    original_topic = topic
    topic = topic + _platform_constraint_note()

    # Freeze the exact literature input before the first model call.  A caller
    # can provide the typed survey object directly; legacy inline lists remain
    # supported but are labelled as such. Empty input triggers one pinned S2
    # record operation, never a provider fallback.
    resolved_snapshot_ref: str | None = None
    if survey_snapshot_ref:
        if survey_snapshot is not None or papers:
            raise ValueError(
                "survey_snapshot_ref cannot be combined with inline literature"
            )
        if not checkpoint:
            raise ValueError("survey_snapshot_ref requires ARI_CHECKPOINT_DIR")
        snapshot = load_survey_snapshot(checkpoint, survey_snapshot_ref)
        resolved_snapshot_ref = survey_snapshot_ref
        all_papers = paper_projection(snapshot)
    elif survey_snapshot is not None:
        snapshot = parse_survey_snapshot(survey_snapshot)
        all_papers = paper_projection(snapshot)
    elif papers:
        snapshot = inline_snapshot(
            list(papers), query=original_topic, checkpoint_dir=checkpoint
        )
        all_papers = paper_projection(snapshot)
    else:
        survey_result = survey(original_topic, max_papers=8, mode="record")
        snapshot = parse_survey_snapshot(survey_result["survey_snapshot"])
        all_papers = paper_projection(snapshot)

    # Build reference text for VirSci prompts
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
                from ari.public.lineage import (  # type: ignore
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

    # Idea generation: both engines terminate at one strict adapter. ``auto``
    # may use a visibly recorded fallback; an explicitly requested VirSci run
    # fails closed instead of changing the method after an error.
    requested_adapter = (
        "virsci-real"
        if generation_mode == "virsci"
        or (generation_mode == "auto" and _virsci_real())
        else "default-discussion"
    )
    real_meta: dict | None = None
    raw_ideas: list[dict] | None = None
    fallback_reason: str | None = None
    if requested_adapter == "virsci-real":
        try:
            raw_ideas, real_meta = await _run_real_virsci(
                topic, n_ideas, ancestor_block, seed_papers=all_papers
            )
            if not raw_ideas:
                raise ValueError("VirSci returned no idea candidates")
        except Exception as e:
            if generation_mode == "virsci":
                _PROMPT_TRACE.reset(trace_token)
                _GENERATION_SEED.reset(seed_token)
                raise RuntimeError(f"explicit VirSci generation failed: {e}") from e
            fallback_reason = f"virsci-real failed: {type(e).__name__}: {e}"
            print(
                f"[idea] VirSci real path failed, using declared default adapter: {e}",
                file=sys.stderr,
            )
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
        actual_adapter = (
            "default-discussion-vendor-prompts"
            if _VIRSCI_PROMPTS_AVAILABLE
            else "default-discussion"
        )
    else:
        actual_adapter = "virsci-real"

    # Sort by novelty score (VirSci: novelty*2 + feasibility + clarity)
    raw_ideas.sort(
        key=lambda x: x["novelty_score"] * 2 + x["feasibility_score"] + x["clarity_score"],
        reverse=True,
    )

    metric_data = await select_metric_contracts(topic, raw_ideas, snapshot)

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

    if _VIRSCI_PROMPTS_AVAILABLE and _VirSciPrompts is not None:
        discussion_templates = [
            str(_VirSciPrompts.prompt_task),
            str(_VirSciPrompts.prompt_reference),
            str(_VirSciPrompts.prompt_topic),
            str(_VirSciPrompts.prompt_response),
            str(_VirSciPrompts.prompt_existing_idea),
        ]
    else:
        discussion_templates = [
            "ari-skill-idea:inline-discussion-prompts/v1",
        ]
    generation_lock = build_generation_lock(
        adapter=actual_adapter,
        model=_model(),
        api_base=_api_base(),
        prompt_texts=[
            "Identify research gaps in 3-4 sentences. Be concise. No markdown.",
            "ari-skill-idea:scientific-contract-prompt/v1",
            *discussion_templates,
        ],
        temperatures=(0.3, 0.7, 0.1),
        seed=seed,
        snapshot=snapshot,
        topic=topic,
        experiment_context=experiment_context,
        generation_parameters={
            "n_ideas": n_ideas,
            "n_agents": n_agents,
            "max_discussion_rounds": max_discussion_rounds,
            "max_recursion_depth": max_recursion_depth,
            "virsci_k": _virsci_k() if requested_adapter == "virsci-real" else None,
            "virsci_team_size": (
                _virsci_team_size() if requested_adapter == "virsci-real" else None
            ),
            "prompt_calls_observed": len(prompt_trace),
        },
        model_revision=(
            os.environ.get("ARI_MODEL_IDEA_REVISION", "").strip() or _model()
        ),
    )
    idea_set, research_contract = build_idea_handoff(
        topic=topic,
        snapshot=snapshot,
        raw_ideas=final_ideas,
        metric_data=metric_data,
        generation_lock=generation_lock,
        generated_at=generated_at,
        requested_adapter=requested_adapter,
        actual_adapter=actual_adapter,
        fallback_reason=fallback_reason,
    )
    final_ideas = enrich_legacy_ideas(final_ideas, idea_set)
    legacy_metric = metric_legacy_projection(metric_data)

    out: dict = {
        "gap_analysis":      gap_raw,
        "ideas":             final_ideas,
        **legacy_metric,
        "papers_analyzed":   (real_meta["papers_indexed"] if real_meta else len(all_papers)),
        "n_agents":          (real_meta["n_agents"] if real_meta else n_agents),
        "discussion_rounds": (real_meta["discussion_rounds"] if real_meta else max_discussion_rounds),
        "virsci_integration_status": virsci_status,
        "typed_schema_version": RESEARCH_CONTRACT_V1,
        "contract_status": "admitted" if research_contract else "rejected",
        "survey_snapshot": snapshot.model_dump(mode="json"),
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "survey_snapshot_ref": resolved_snapshot_ref,
        "idea_set": idea_set.model_dump(mode="json"),
        "idea_set_digest": idea_set.idea_set_digest,
        "research_contract": (
            research_contract.model_dump(mode="json")
            if research_contract is not None
            else None
        ),
        "research_contract_digest": (
            research_contract.contract_digest if research_contract is not None else None
        ),
        "rejected_candidates": [
            item.model_dump(mode="json") for item in idea_set.rejections
        ],
    }
    if pinned_metadata:
        out.update(pinned_metadata)
    _PROMPT_TRACE.reset(trace_token)
    _GENERATION_SEED.reset(seed_token)
    return out


if __name__ == "__main__":
    mcp.run()
