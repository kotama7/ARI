"""MCP Server for dynamic MetricSpec generation from experiment files."""

from __future__ import annotations

import re
import json
from mcp.server import Server
from mcp.types import TextContent, Tool

server = Server("evaluator-skill")

try:
    try:
        from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore
    except ImportError:
        from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("evaluator")
except Exception:
    pass


def _parse_success_metrics(text: str) -> list[str]:
    """Extract metric names from the experiment file (deterministic).
    Supports:
      - ## Success Metrics section with "- metric_name: ..."
      - "Metrics: A, B, C" inline line
      - "<!-- metric_keyword: FOO -->" HTML comment
    """
    # 1. ## Success Metrics section
    m = re.search(r"##\s*Success Metrics.*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        found = re.findall(r"-\s*(\w+)\s*:", m.group(1))
        if found:
            return found
    # 2. "Metrics: A, B, C" inline
    m2 = re.search(r"(?:^|\n)Metrics?:\s*([^\n]+)", text, re.IGNORECASE)
    if m2:
        raw = m2.group(1)
        return [w.strip().strip("/") for w in re.split(r"[,;]", raw) if w.strip()]
    # 3. metric_keyword comment
    m3 = re.search(r"metric_keyword:\s*(\w+)", text)
    if m3:
        return [m3.group(1)]
    return []


def _parse_metric_keyword(text: str) -> str | None:
    """Extract keyword from <!-- metric_keyword: FOO --> or front matter."""
    m = re.search(r"metric_keyword:\s*(\w+)", text)
    return m.group(1) if m else None


def _parse_min_expected(text: str) -> float | None:
    """Extract threshold from <!-- min_expected_metric: N -->."""
    m = re.search(r"min_expected_metric:\s*([\d.]+)", text)
    return float(m.group(1)) if m else None


def _build_scoring_guide(
    expected_metrics: list[str],
    metric_keyword: str | None,
    min_expected: float | None,
) -> str:
    """Generate a generic scoring guide from the expected_metrics list (deterministic template)."""
    kw = metric_keyword or "metric"
    min_val = min_expected or 0

    lines = [
        f"STEP 1 - Extract numeric {kw} values from artifacts.",
        f"  has_real_data=true only if actual {kw} numbers appear in artifacts.",
        f"  If no {kw} values found: score=0.2, stop here.",
        "",
        f"STEP 2 - Evaluate {kw} quality.",
        f"  Target threshold: {min_val:g} (from experiment spec).",
        f"  Above threshold: good. Below: poor.",
        "",
        "STEP 3 - Compute final score:",
        f"  1.0 = has_real_data AND {kw} >= {min_val:g} AND paper section present",
        f"  0.9 = has_real_data AND {kw} >= {min_val:g} (no paper)",
        f"  0.7 = has_real_data AND {kw} < {min_val:g}",
        "  0.3 = has_real_data but only baseline measured",
        "  0.2 = no real values in artifacts",
        "",
        "Always extract actual numbers into metrics dict:",
        "  metrics = {" + ", ".join(f"{m}: <value>" for m in expected_metrics) + "}",
    ]
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="make_metric_spec",
            description=(
                "Generates a MetricSpec (expected_metrics, metric_keyword, scoring_guide, "
                "min_expected_metric). Prefers the idea-stage canonical primary_metric "
                "(from primary_metric arg, or evaluation_criteria.json/idea.json via "
                "ARI_CHECKPOINT_DIR) and structures it via LLM; falls back to deterministic "
                "parsing of the experiment.md seed metrics line when no primary_metric exists."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_text": {
                        "type": "string",
                        "description": "Full text of the experiment file (.md)",
                    },
                    "primary_metric": {
                        "type": "string",
                        "description": (
                            "Optional idea-stage canonical primary_metric. When set "
                            "(or resolvable from evaluation_criteria.json/idea.json via "
                            "ARI_CHECKPOINT_DIR) it overrides the experiment.md seed line."
                        ),
                    },
                    "checkpoint_dir": {
                        "type": "string",
                        "description": "Optional checkpoint dir to read primary_metric from.",
                    },
                },
                "required": ["experiment_text"],
            },
        ),
        Tool(
            name="claim_evidence_hard_gate",
            description=(
                "Story2Proposal Phase B: deterministic claim/evidence hard gate "
                "(execution data fidelity). Verifies that science_data claims reference "
                "executed nodes, re-computes numeric_assertions from results.json and "
                "checks the paper-reported numbers within tolerance, detects uncovered "
                "result numbers per section policy, and checks figure existence. No LLM. "
                "In strict mode the FINAL phase returns an error that blocks finalize when "
                "blocking errors exist; draft phase and warn/off mode never block. Writes "
                "evaluation/claim_evidence_hard_gate_{phase}.json."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_dir": {"type": "string"},
                    "paper_path": {"type": "string", "description": "Path to full_paper.tex"},
                    "science_data_json": {"type": "string", "description": "science_data.json content or path"},
                    "paper_claim_links_path": {"type": "string", "description": "Path to paper_claim_links.json"},
                    "figures_manifest_json": {"type": "string", "description": "figures_manifest.json content or path"},
                    "policy": {"description": "claim_gate_policy (dict or JSON/repr string)"},
                    "phase": {"type": "string", "enum": ["draft", "final"], "default": "draft"},
                },
                "required": ["checkpoint_dir", "paper_path"],
            },
        ),
        Tool(
            name="evidence_grounded_semantic_review",
            description=(
                "Story2Proposal Phase D: non-blocking, evidence-grounded semantic review. "
                "LLM detects over-claiming / interpretation issues / unregistered strong "
                "claims grounded in the hard-gate evidence, WITHOUT touching the independent "
                "text reviewer. Emits suggested_revisions for paper_refine and scores. "
                "Writes evaluation/evidence_grounded_semantic_review.json. Never blocks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_dir": {"type": "string"},
                    "paper_path": {"type": "string", "description": "Path to full_paper.tex"},
                    "science_data_json": {"type": "string", "description": "science_data.json content or path"},
                    "hard_gate_path": {"type": "string", "description": "Path to claim_evidence_hard_gate_*.json"},
                    "paper_claim_links_path": {"type": "string", "description": "Path to paper_claim_links.json"},
                    "phase": {"type": "string", "default": "initial"},
                },
                "required": ["checkpoint_dir", "paper_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "make_metric_spec":
        result = await _tool_make_metric_spec(arguments)
    elif name == "claim_evidence_hard_gate":
        result = await _tool_claim_evidence_hard_gate(arguments)
    elif name == "evidence_grounded_semantic_review":
        result = await _tool_evidence_grounded_semantic_review(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


_METRIC_EXTRACT_SYS = (
    "You are a research evaluation expert. "
    "Given an experiment description, identify: "
    "(1) the primary numeric metric to maximize/minimize (one short name, e.g. GFLOP_per_s), "
    "(2) whether higher is better, "
    "(3) the list of MEASURED metric names the experiment should report (outputs only — throughput, accuracy, latency, etc.), "
    "(4) the list of INPUT parameter names the experiment runs on (matrix size, thread count, seed, etc. — these are knobs, NOT measurements). "
    "Strictly disjoint: a name appears in measurements OR params, never both. "
    "Respond ONLY with JSON: "
    '{"metric_keyword":"<name>","higher_is_better":true,'
    '"expected_metrics":["<m1>","<m2>"],"expected_params":["<p1>","<p2>"]}'
)


async def _llm_extract_metric_spec(description: str) -> dict:
    """LLM-extract ``{metric_keyword, higher_is_better, expected_metrics, expected_params}``
    from a free-text description. Returns ``{}`` on any failure so callers fall back."""
    try:
        import litellm as _litellm, os as _os, json as _json, re as _re
        _model = (_os.environ.get("ARI_MODEL_EVAL")
                  or _os.environ.get("ARI_MODEL")
                  or _os.environ.get("ARI_LLM_MODEL")
                  or "gpt-4o-mini")
        _resp = await _litellm.acompletion(
            model=_model,
            messages=[
                {"role": "system", "content": _METRIC_EXTRACT_SYS},
                {"role": "user", "content": "Experiment description:\n" + (description or "")[:2000]},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        _raw = _resp.choices[0].message.content or ""
        _m = _re.search(r"\{.*\}", _raw, _re.DOTALL)
        if _m:
            return _json.loads(_m.group(0))
    except Exception:
        pass  # Fall through; caller keeps its existing values.
    return {}


def _load_primary_metric_from_checkpoint(checkpoint_dir: str | None = None) -> str:
    """Resolve the idea-stage canonical ``primary_metric`` for the running node.

    Prefers ``evaluation_criteria.json`` (orchestrator-written), then ``idea.json``
    (written by generate_ideas). The checkpoint dir is taken from the explicit arg
    or the ``ARI_CHECKPOINT_DIR`` env injected by the agent loop before the MCP
    fork. Returns ``""`` when unavailable (e.g. the root node before generate_ideas).
    """
    import os as _os
    from pathlib import Path as _Path
    ckpt = checkpoint_dir or _os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not ckpt:
        return ""
    for _fn in ("evaluation_criteria.json", "idea.json"):
        _p = _Path(ckpt) / _fn
        if not _p.is_file():
            continue
        try:
            _d = json.loads(_p.read_text())
        except Exception:
            continue
        pm = _d.get("primary_metric") or ""
        if not pm and isinstance(_d.get("ideas"), list) and _d["ideas"]:
            pm = (_d["ideas"][0] or {}).get("primary_metric", "")
        if isinstance(pm, str) and pm.strip():
            return pm.strip()
    return ""


async def _tool_make_metric_spec(arguments: dict) -> dict:
    text = arguments["experiment_text"]
    expected_metrics = _parse_success_metrics(text)
    metric_keyword = _parse_metric_keyword(text)
    min_expected = _parse_min_expected(text)

    # ``expected_params`` lists the input knobs the experiment runs on
    # (matrix size, thread count, seed). They are NOT measurements and
    # MUST be excluded from best-of reductions downstream. Inferred only
    # via the LLM fallback below — the regex-based path doesn't extract
    # them because experiment.md has no consistent "## Parameters" header.
    expected_params: list[str] = []

    # The experiment.md ``Metrics:`` line is a HUMAN SEED placeholder written
    # before idea generation (often throughput-only, e.g. "GB/s, GFlops/s").
    # When the idea stage has produced a canonical ``primary_metric``, it is the
    # authoritative success criterion and OVERRIDES the seed — this is what keeps
    # every node on one metric definition instead of each re-inventing its own.
    # The seed regex remains the fallback (e.g. the root node, before
    # generate_ideas has run and no idea.json exists yet).
    primary_metric = (arguments.get("primary_metric") or "").strip() \
        or _load_primary_metric_from_checkpoint(arguments.get("checkpoint_dir"))
    if primary_metric:
        _spec = await _llm_extract_metric_spec(primary_metric)
        if _spec.get("metric_keyword"):
            metric_keyword = _spec["metric_keyword"]
        if _spec.get("expected_metrics"):
            expected_metrics = _spec["expected_metrics"]
        _ep = _spec.get("expected_params", [])
        if isinstance(_ep, list) and _ep:
            expected_params = [str(p) for p in _ep if p]

    # If neither the primary_metric nor the experiment file yielded metrics,
    # delegate to the LLM on the raw experiment text.
    if not expected_metrics or not metric_keyword:
        _spec = await _llm_extract_metric_spec(text)
        if not metric_keyword:
            metric_keyword = _spec.get("metric_keyword", "")
        if not expected_metrics:
            expected_metrics = _spec.get("expected_metrics", [])
        _ep = _spec.get("expected_params", [])
        if not expected_params and isinstance(_ep, list):
            expected_params = [str(p) for p in _ep if p]

    scoring_guide = _build_scoring_guide(expected_metrics, metric_keyword, min_expected)

    # Metric-correctness contract scaffold: classify the metric's mathematical
    # concept and attach its universal invariant DETERMINISTICALLY, reusing the
    # hard gate's registry (single source of truth — no domain knowledge here).
    # The implementing agent fills formula/correctness/required_measured (which
    # are experiment-specific); the gate enforces whatever ends up declared. When
    # the concept is unrecognized the scaffold is omitted (legacy behaviour).
    metric_contract = None
    try:
        from ari.public.claim_gate import classify_concept as _classify, CONCEPT_INVARIANTS as _CINV
        _concept = _classify(primary_metric or "") or _classify(metric_keyword or "")
        if _concept:
            metric_contract = {
                "key": metric_keyword or "",
                "concept": _concept,
                "invariants": [f"value {op} {rhs:g}" for op, rhs in _CINV.get(_concept, [])],
                # TO BE FILLED BY THE IMPLEMENTING AGENT for a rigorous claim:
                "formula": "",            # recompute 'value' from raw MEASURED operands
                "correctness": {},        # {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]}
                "required_measured": [],  # operand names that must be measured (no placeholder ceiling)
            }
    except Exception:
        metric_contract = None

    return {
        "expected_metrics": expected_metrics,
        "expected_params": expected_params,
        "metric_keyword": metric_keyword,
        "min_expected_metric": min_expected,
        "scoring_guide": scoring_guide,
        "metric_contract": metric_contract,
    }


def _load_jsonish(val):
    """Load a dict from a JSON string, a path, or pass through a dict."""
    import json as _json
    from pathlib import Path as _Path
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return _json.loads(val)
        except Exception:
            p = _Path(val)
            if p.is_file():
                try:
                    return _json.loads(p.read_text())
                except Exception:
                    return {}
    return {}


async def _tool_claim_evidence_hard_gate(arguments: dict) -> dict:
    """Thin MCP wrapper over ari-core's deterministic claim_evidence_hard_gate.

    Returns the full report normally. When the report says should_block — at the
    FINAL phase, either a strict-mode block_on error OR an always_block_on
    objective-falsehood (invariant_violation / correctness_failed / placeholder_
    denominator / ...) regardless of warn/strict — returns EXACTLY {"error": ...}
    so the pipeline stage runner raises and finalize_paper is skipped.
    """
    from pathlib import Path as _Path

    ckpt = arguments.get("checkpoint_dir") or ""
    paper_path = arguments.get("paper_path") or arguments.get("tex_path") or ""
    if not ckpt and paper_path:
        ckpt = str(_Path(paper_path).parent)
    phase = (arguments.get("phase") or "draft").strip().lower()

    # Degrade gracefully: if ari-core is somehow unimportable, do NOT fail the
    # stage (that would cascade-skip finalize). Report a non-blocking skip.
    try:
        from ari.public.claim_gate import run_hard_gate  # public contract (req 09)
    except Exception as _e:  # pragma: no cover
        return {"gate": "claim_evidence_hard_gate", "phase": phase, "status": "skipped",
                "should_block": False, "errors": [], "warnings": [],
                "note": f"ari-core claim_gate unavailable: {_e}"}

    paper_tex = ""
    if paper_path and _Path(paper_path).is_file():
        paper_tex = _Path(paper_path).read_text(encoding="utf-8")

    science_data = _load_jsonish(arguments.get("science_data_json"))
    pcl = None
    pcl_path = arguments.get("paper_claim_links_path") or ""
    if pcl_path and _Path(pcl_path).is_file():
        pcl = _load_jsonish(pcl_path)
    elif arguments.get("paper_claim_links_json"):
        pcl = _load_jsonish(arguments.get("paper_claim_links_json"))
    figures = _load_jsonish(arguments.get("figures_manifest_json")) or None

    try:
        report = run_hard_gate(
            ckpt, paper_tex=paper_tex, science_data=science_data,
            paper_claim_links=pcl, figures_manifest=figures,
            policy=arguments.get("policy"), phase=phase,
        )
    except Exception as _e:  # pragma: no cover - defensive
        return {"gate": "claim_evidence_hard_gate", "phase": phase, "status": "skipped",
                "should_block": False, "errors": [], "warnings": [],
                "note": f"hard gate raised: {_e}"}
    if report.get("should_block"):
        n = len(report.get("errors", []))
        return {"error": (
            f"claim_evidence_hard_gate ({phase}): {n} blocking error(s); "
            f"see evaluation/claim_evidence_hard_gate_{phase}.json"
        )}
    return report


_SEMANTIC_SYSTEM_PROMPT = (
    "You are a rigorous scientific reviewer performing an EVIDENCE-GROUNDED SEMANTIC "
    "review of a paper. Numeric correctness, figure existence, and number/results "
    "consistency have ALREADY been verified deterministically by a hard gate (its "
    "findings are provided) — do NOT re-check numbers. Evaluate ONLY meaning:\n"
    "  - reasoning: do Abstract/Intro/Conclusion claims stay within the evidence? "
    "over-generalization beyond the evaluated benchmark? are limitations reflected?\n"
    "  - data_interpretation: are causal/comparative interpretations of the results "
    "justified (separate from whether the numbers match)?\n"
    "  - visual_semantics: do captions/figure descriptions agree in MEANING with the "
    "text (not existence)?\n"
    "  - unregistered strong (non-numeric) claims not backed by the candidate claims.\n"
    "Be conservative: only flag genuine over-claims. Respond ONLY with JSON:\n"
    '{"scores":{"reasoning":0-1,"data_interpretation":0-1,"visual_semantics":0-1},'
    '"warnings":[{"type":"overclaim|overgeneralization|unsupported_claim|interpretation|'
    'visual_semantics","section":"<section>","message":"<why>"}],'
    '"suggested_revisions":[{"section":"<section>","instruction":"<concrete edit>"}]}'
)


async def _tool_evidence_grounded_semantic_review(arguments: dict) -> dict:
    """Story2Proposal Phase D: non-blocking, evidence-grounded semantic review.

    Detects over-claiming / interpretation issues grounded in the hard-gate
    evidence and emits suggested_revisions for paper_refine. Never blocks the
    pipeline; on any error it returns an empty (status='ok') review.
    """
    import json as _json
    import os as _os
    import re as _re
    from pathlib import Path as _Path

    ckpt = arguments.get("checkpoint_dir") or ""
    paper_path = arguments.get("paper_path") or arguments.get("tex_path") or ""
    if not ckpt and paper_path:
        ckpt = str(_Path(paper_path).parent)
    phase = (arguments.get("phase") or "initial").strip().lower()

    paper_tex = ""
    if paper_path and _Path(paper_path).is_file():
        paper_tex = _Path(paper_path).read_text(encoding="utf-8")

    science_data = _load_jsonish(arguments.get("science_data_json"))
    claims = science_data.get("claims", []) if isinstance(science_data, dict) else []
    hard_gate = {}
    hg_path = arguments.get("hard_gate_path") or ""
    if hg_path and _Path(hg_path).is_file():
        hard_gate = _load_jsonish(hg_path)

    out_dir = _Path(ckpt) / "evaluation"
    suffix = "" if phase in ("", "initial", "draft") else f"_{phase}"
    out_file = out_dir / f"evidence_grounded_semantic_review{suffix}.json"

    def _finalize(report: dict) -> dict:
        # score_delta vs the initial review (self-referential; report alongside
        # independent indicators — see master plan §10.3).
        prior = out_dir / "evidence_grounded_semantic_review.json"
        if suffix and prior.is_file():
            try:
                pj = _json.loads(prior.read_text())
                p_agg = _agg_score(pj.get("scores", {}))
                c_agg = _agg_score(report.get("scores", {}))
                report["score_delta"] = round(c_agg - p_agg, 4)
                report["detected_overclaim_count_prev"] = pj.get("detected_overclaim_count", 0)
                report["resolved_overclaim_count"] = max(
                    0, pj.get("detected_overclaim_count", 0) - report.get("detected_overclaim_count", 0)
                )
            except Exception:
                pass
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file.write_text(_json.dumps(report, ensure_ascii=False, indent=2))
            report["output_path"] = str(out_file)
        except Exception as e:
            report["_write_error"] = str(e)
        return report

    if not paper_tex:
        return _finalize({
            "stage": "evidence_grounded_semantic_review", "phase": phase, "status": "ok",
            "scores": {}, "warnings": [], "suggested_revisions": [],
            "detected_overclaim_count": 0, "resolved_overclaim_count": 0,
            "human_verified_overclaim_precision": None,
            "note": "no paper text available; non-blocking no-op",
        })

    claim_lines = "; ".join(
        f"{c.get('id')}: {c.get('text', '')}" for c in claims if isinstance(c, dict)
    )[:4000]
    hg_summary = _json.dumps({
        "errors": hard_gate.get("errors", []),
        "warnings": hard_gate.get("warnings", []),
        "metrics": hard_gate.get("metrics", {}),
    }, ensure_ascii=False)[:6000]

    user_prompt = (
        f"Candidate claims (already grounded in executed results):\n{claim_lines}\n\n"
        f"Hard-gate findings (numbers already verified — do not re-check):\n{hg_summary}\n\n"
        f"Paper (LaTeX):\n{paper_tex[:36000]}"
    )

    try:
        import litellm as _litellm
        _model = (_os.environ.get("ARI_MODEL_EVAL")
                  or _os.environ.get("ARI_MODEL")
                  or _os.environ.get("ARI_LLM_MODEL")
                  or "gpt-4o-mini")
        _kw = {
            "model": _model,
            "messages": [
                {"role": "system", "content": _SEMANTIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2, "max_tokens": 1500,
        }
        _apib = _os.environ.get("ARI_LLM_API_BASE")
        if _apib:
            _kw["api_base"] = _apib
        _resp = await _litellm.acompletion(**_kw)
        _raw = _resp.choices[0].message.content or ""
        _raw = _re.sub(r"<think>.*?</think>", "", _raw, flags=_re.DOTALL).strip()
        _m = _re.search(r"\{.*\}", _raw, _re.DOTALL)
        parsed = _json.loads(_m.group(0)) if _m else {}
    except Exception as e:
        return _finalize({
            "stage": "evidence_grounded_semantic_review", "phase": phase, "status": "ok",
            "scores": {}, "warnings": [], "suggested_revisions": [],
            "detected_overclaim_count": 0, "resolved_overclaim_count": 0,
            "human_verified_overclaim_precision": None,
            "note": f"semantic review LLM unavailable; non-blocking no-op ({e})",
        })

    warnings = parsed.get("warnings", []) if isinstance(parsed, dict) else []
    warnings = [w for w in warnings if isinstance(w, dict)]
    revisions = parsed.get("suggested_revisions", []) if isinstance(parsed, dict) else []
    revisions = [r for r in revisions if isinstance(r, dict)]
    scores = parsed.get("scores", {}) if isinstance(parsed, dict) else {}
    overclaim_types = {"overclaim", "overgeneralization", "unsupported_claim"}
    detected = sum(1 for w in warnings if w.get("type") in overclaim_types)

    status = "revise" if (warnings or revisions) else "ok"
    return _finalize({
        "stage": "evidence_grounded_semantic_review", "phase": phase, "status": status,
        "scores": scores, "warnings": warnings, "suggested_revisions": revisions,
        "detected_overclaim_count": detected, "resolved_overclaim_count": 0,
        "human_verified_overclaim_precision": None,
    })


def _agg_score(scores: dict) -> float:
    vals = [float(v) for v in (scores or {}).values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def _build_artifact_extractor_source(metric_keyword: str | None) -> str:
    """Return the source code of an artifact_extractor function for the given metric_keyword (deterministic).

    Returns a Python code string that can be eval()ed or exec()ed.
    If keyword is None, returns generic numeric extraction code.
    """
    if metric_keyword:
        return (
            f"import re as _re\n"
            f"def _auto_artifact_extractor(text):\n"
            f"    matches = _re.findall(r'{metric_keyword}[:\\s=]+([\\d,]+\\.?\\d*)', text, _re.IGNORECASE)\n"
            f"    result = {{}}\n"
            f"    for i, v in enumerate(matches):\n"
            f"        try:\n"
            f"            val = float(v.replace(',', ''))\n"
            f"            result['{metric_keyword}_' + ('serial' if i == 0 else f'run_{{i}}')] = val\n"
            f"        except ValueError:\n"
            f"            pass\n"
            f"    return result\n"
        )
    else:
        # Generic: extract all significant numeric values (>= 1.0)
        return (
            "import re as _re\n"
            "def _auto_artifact_extractor(text):\n"
            "    nums = [float(x) for x in _re.findall(r'\\b(\\d+\\.\\d+)\\b', text) if float(x) >= 1.0]\n"
            "    return {'metric_' + str(i): v for i, v in enumerate(nums[:10])}\n"
        )


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    async def main():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    asyncio.run(main())
