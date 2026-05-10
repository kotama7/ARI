"""BFTS-context + keyword-extractor helpers (Phase 3C).

Two functions extracted from the legacy ``ari/pipeline.py``:

- :func:`build_best_nodes_context` — build the paper-stage context
  string from the best-scoring SUCCESS nodes.
- :func:`_extract_keywords_from_nodes` — derive a Semantic Scholar
  search query from BFTS ``nodes_tree.json`` summaries (uses the PC2
  external prompt at ``ari/prompts/pipeline/keyword_librarian.md``).
"""

from __future__ import annotations


def build_best_nodes_context(all_nodes, experiment_goal: str = "") -> tuple[str, dict]:
    """Build experiment context for paper writing from SUCCESS nodes.

    Returns ONLY scientific data (configurations, metrics, results).
    Does NOT include internal system identifiers (node IDs, labels, checkpoints).
    This ensures the generated paper reads as a direct scientific report,
    not as a description of how the automation system found the results.
    """
    from ari.orchestrator.node import NodeStatus

    results = [
        n for n in all_nodes
        if n.status == NodeStatus.SUCCESS and n.has_real_data
    ]
    if not results:
        return "", {}

    def _sort_key(n) -> float:
        """Score a node by its scientific_score (set by LLM evaluator).

        The evaluator LLM judges scientific contribution and stores the result
        in metrics["_scientific_score"]. This is the authoritative ranking signal.
        Fallback to any float metric only when no evaluator score exists.
        """
        # Primary: LLM-assigned scientific score (0.0-1.0, set by evaluator)
        sci = (n.metrics or {}).get("_scientific_score")
        if sci is not None:
            return float(sci)
        # Secondary: eval_summary numeric score if present
        import re as _re_sk
        if n.eval_summary:
            m = _re_sk.search(r"score[: ]+([0-9.]+)", n.eval_summary, _re_sk.IGNORECASE)
            if m:
                return float(m.group(1))
        # Fallback: max of any float metric (last resort, no domain filtering)
        floats = [v for v in (n.metrics or {}).values() if isinstance(v, float) and 0 < v < 1e9]
        return max(floats, default=0.0)

    results.sort(key=_sort_key, reverse=True)

    # Strip execution-context lines from experiment_goal before passing to paper LLM.
    # Remove file paths, job/work directory details, and hardware cluster specifics —
    # these are internal execution details, not scientific content for the paper.
    import re as _re_g
    goal_lines = experiment_goal.split("\n")
    _EXEC_PATTERNS = [
        r"^[-*]?\s*(source|work\s*dir|compiler|job\s*output|partition|max\s*cpu|do\s*not\s*modify)",
        r"/[a-zA-Z0-9_/.-]{5,}",   # file paths
        r"^#\s*(resources|hardware|success metric)",  # section headers about infra
    ]
    clean_goal_lines = []
    for line in goal_lines:
        skip = any(_re_g.search(pat, line, _re_g.IGNORECASE) for pat in _EXEC_PATTERNS)
        if not skip:
            clean_goal_lines.append(line)
    clean_goal = "\n".join(clean_goal_lines).strip()
    # Also strip HTML comments from goal
    clean_goal = _re_g.sub(r"<!--.*?-->", "", clean_goal, flags=_re_g.DOTALL).strip()

    context_lines = [f"Experiment goal: {clean_goal[:400]}"]
    context_lines.append(f"\nBest results (top {min(5, len(results))} configurations):")
    for i, r in enumerate(results[:5]):
        rank = "Best" if i == 0 else f"#{i+1}"
        metrics_str = str(r.metrics)
        summary = (r.eval_summary or "")[:300]
        context_lines.append(f"  [{rank}] metrics={metrics_str}")
        if summary:
            context_lines.append(f"    summary: {summary}")
    return "\n".join(context_lines), results[0].metrics if results else {}


def _extract_keywords_from_nodes(nodes_json_path: str, base_topic: str = "") -> str:
    """Extract search keywords from BFTS nodes_tree.json.

    Collects eval_summary text from successful nodes and asks LLM to extract
    a concise academic search query (no domain-specific hardcoding).
    Falls back to base_topic if LLM call fails.
    """
    base = base_topic.strip() if base_topic else "research experiment"
    try:
        import json as _json
        with open(nodes_json_path) as _f:
            _data = _json.load(_f)
        _nodes = _data.get("nodes", [])
        _summaries = [
            n.get("eval_summary", "")
            for n in _nodes
            if n.get("status") == "success" and n.get("eval_summary")
        ][:5]
        if not _summaries:
            return base
        _combined = " ".join(_summaries)[:1200]
        import litellm as _litellm, os as _os
        _model = _os.environ.get("ARI_MODEL", "gpt-4o-mini")
        _backend = _os.environ.get("ARI_BACKEND", "ollama")
        if _backend == "ollama" and not _model.startswith(("ollama/", "ollama_chat/")):
            _model = f"ollama_chat/{_model}"
        elif _backend in ("claude", "anthropic") and not _model.startswith("anthropic/"):
            _model = f"anthropic/{_model}"
        # Phase PC2 (PROMPTS_AND_CONFIG.md §3-5): keyword librarian
        # prompt lives in ``ari/prompts/pipeline/keyword_librarian.md``.
        from ari.prompts import FilesystemPromptLoader as _PL_pipe
        _kw_system = _PL_pipe().load("pipeline/keyword_librarian")
        _kw: dict = dict(
            model=_model,
            messages=[{
                "role": "system",
                "content": _kw_system,
            }, {
                "role": "user",
                "content": f"Experiment summaries:\n{_combined}",
            }],
            max_tokens=30,
        )
        # gpt-5* models only support temperature=1
        _raw_model = _os.environ.get("ARI_MODEL", "")
        if not _raw_model.startswith("gpt-5"):
            _kw["temperature"] = 0.0
        if _backend == "ollama":
            _kw["api_base"] = _os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        _kw["metadata"] = {"phase": "pipeline", "skill": "search_query"}
        _resp = _litellm.completion(**_kw)
        _query = (_resp.choices[0].message.content or "").strip().strip('"')
        return _query if _query else base
    except Exception:
        return base
