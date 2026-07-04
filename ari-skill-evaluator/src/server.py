"""MCP Server for dynamic MetricSpec generation from experiment files."""

from __future__ import annotations

import logging
import re
import json
from mcp.server import Server
from mcp.types import TextContent, Tool

server = Server("evaluator-skill")
_logger = logging.getLogger("evaluator-skill")

try:
    try:
        from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore
    except ImportError:
        from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("evaluator")
except Exception:
    pass


# ── skill-local prompt loader (subtask 040) ──────────────────────────────────
# The evaluator/LLM-judge system prompts are stored as byte-identical ``.md``
# templates under ``src/prompts/`` and loaded here through a tiny mirror of
# ari-core's ``FilesystemPromptLoader`` ``load_versioned`` contract. The helper
# is COPIED (not imported from ari-core) to preserve the one-way
# ``ari-skill-* -> ari-core`` boundary and keep this MCP package self-contained.
# Imports stay function-local (matching this module's style and avoiding E402,
# and keeping the cost-tracker fallback import at its pinned line). Raw load (no
# ``str.format``) since every template embeds literal JSON-schema braces.
# Deterministic (P2): a package-relative file read — no LLM, no network.
def _prompt_path(key: str):
    """Absolute path to the skill-local prompt template *key* (``prompts/<key>.md``)."""
    from pathlib import Path
    return Path(__file__).resolve().parent / "prompts" / f"{key}.md"


def _load_prompt(key: str) -> str:
    """Return prompt template *key* byte-identical to the pre-extraction constant.

    The ``.md`` file is stored with a trailing newline (file convention); a
    single trailing ``\\n`` is trimmed so the rendered string equals the original
    string constant exactly, mirroring ari-core ``llm_evaluator.py``.
    """
    text = _prompt_path(key).read_text(encoding="utf-8")
    return text[:-1] if text.endswith("\n") else text


def _load_prompt_versioned(key: str) -> tuple[str, str]:
    """``(rendered_text, sha256[:12])`` for uniform prompt hashing.

    The hash is over the raw on-disk template body (before the trailing-newline
    trim), matching ari-core's ``load_versioned`` so snapshot tests and future
    run-provenance pin the same value. Deterministic; no LLM, no network.
    """
    import hashlib
    raw = _prompt_path(key).read_text(encoding="utf-8")
    return _load_prompt(key), hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


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
                {"role": "system", "content": _load_prompt("metric_extract_sys")},
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


# ── plan-fidelity: the idea's falsifiable claims -> metric_contract.claims ──────
# Domain-neutral. The idea OWNS its claims (so the implementing agent cannot drop a
# claim to dodge the gate); the producer obligation surfaces the required_evidence
# names for the agent to emit. The gate (contract.check_contract) blocks a claim
# whose evidence is wholly absent (claim_evidence_missing).


# Generic experiment tokens that must never stand alone as claim evidence: the gate
# treats a claim as covered when ANY listed name is present (R1), so a name like
# "k" that every run emits would falsely satisfy an unrelated mechanism claim.
# Domain-neutral (input knobs / bookkeeping ids, not science).
_GENERIC_EVIDENCE = frozenset({
    "k", "n", "m", "x", "y", "id", "seed", "threads", "config", "mode", "iter",
    "step", "size", "width", "count", "matrix_id", "mode_id", "config_id",
    "node_id", "run_id", "iteration",
})


def _normalize_claims(raw) -> list:
    """Coerce declared/extracted claims to ``[{claim:str, required_evidence:[str]}]``.

    Drops malformed entries, BARE-GENERIC evidence names (R1 false-coverage guard),
    and claims left with no required_evidence (nothing checkable).
    """
    items = raw.get("claims") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list = []
    for it in items:
        if not isinstance(it, dict):
            continue
        claim = str(it.get("claim") or "").strip()
        ev = [str(e).strip() for e in (it.get("required_evidence") or []) if str(e or "").strip()]
        ev = [e for e in ev if e.lower() not in _GENERIC_EVIDENCE and len(e) > 2]
        if claim and ev:
            out.append({"claim": claim[:300], "required_evidence": ev})
    return out[:12]


def _load_idea_claims_source(checkpoint_dir: str | None = None):
    """Return ``(structured_claims_or_None, plan_text)`` from the idea checkpoint.

    Prefers a structured ``falsifiable_claims`` on the selected idea; otherwise returns
    the experiment_plan prose for LLM extraction. Reads the same files as
    ``_load_primary_metric_from_checkpoint``.
    """
    import os as _os
    from pathlib import Path as _Path
    ckpt = checkpoint_dir or _os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not ckpt:
        return None, ""
    for _fn in ("evaluation_criteria.json", "idea.json"):
        _p = _Path(ckpt) / _fn
        if not _p.is_file():
            continue
        try:
            _d = json.loads(_p.read_text())
        except Exception:
            continue
        best = _d
        if isinstance(_d.get("ideas"), list) and _d["ideas"]:
            best = _d["ideas"][0] or {}
        fc = best.get("falsifiable_claims") or _d.get("falsifiable_claims")
        if isinstance(fc, list) and fc:
            return fc, ""
        plan = best.get("experiment_plan") or _d.get("experiment_plan") or ""
        if isinstance(plan, str) and plan.strip():
            return None, plan
    return None, ""


def _load_platform_note(checkpoint_dir: str | None = None) -> str:
    """Verified platform-capability note for the claims extractor (P2c).

    Reads ``{checkpoint}/platform_capabilities.json`` (written by the HPC skill's
    probe, which ran ``command -v`` ON the compute partition). Real case this
    prevents: the plan promised PMU-counter evidence, but the profiler was not
    installed on the compute partition — the resulting claims were permanently
    unsatisfiable and blocked finalize forever. ``""`` when no probe data (claims
    extraction is then unconstrained, the prior behaviour). Data, not knowledge:
    the note only relays what the probe MEASURED.
    """
    import os as _os
    from pathlib import Path as _Path
    ckpt = checkpoint_dir or _os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not ckpt:
        return ""
    p = _Path(ckpt) / "platform_capabilities.json"
    if not p.is_file():
        return ""
    try:
        d = json.loads(p.read_text())
        avail = d.get("available") or {}
        missing = sorted(t for t, ok in avail.items() if not ok)
        present = sorted(t for t, ok in avail.items() if ok)
        if not avail:
            return ""
        parts = [f"PLATFORM CAPABILITIES (verified by probe on partition "
                 f"{d.get('partition', '?')}, arch={d.get('arch', '?')}):"]
        if missing:
            parts.append(f"UNAVAILABLE tools: {', '.join(missing)}.")
        if present:
            parts.append(f"available tools: {', '.join(present)}.")
        parts.append(
            "Do NOT require evidence that depends on an UNAVAILABLE tool; prefer "
            "evidence the experiment's own code can compute (timers, counts, sizes, "
            "residuals, derived rates). If a claim's evidence cannot be obtained OR "
            "re-expressed with the available tooling, OMIT that claim entirely — an "
            "unmeasurable-by-construction claim would block the run forever.")
        return " ".join(parts)
    except Exception:
        return ""


async def _llm_extract_claims(plan_text: str, platform_note: str = "") -> list:
    """LLM-extract falsifiable claims + required_evidence names from plan prose.

    max_tokens must be GENEROUS: a 10-12 claim JSON runs ~8KB, and a reasoning
    model spends part of the budget thinking. 600 truncated the JSON mid-array
    (finish_reason=length) on a real run, the JSONDecodeError was swallowed, and
    the contract silently carried claims=[] -- the plan-fidelity gate never armed.
    Parse failures are logged (not silently dropped) so this stays diagnosable.
    """
    try:
        import litellm as _litellm, os as _os, json as _json, re as _re
        _model = (_os.environ.get("ARI_MODEL_EVAL")
                  or _os.environ.get("ARI_MODEL")
                  or _os.environ.get("ARI_LLM_MODEL")
                  or "gpt-4o-mini")
        _resp = await _litellm.acompletion(
            model=_model,
            messages=[
                {"role": "system", "content": _load_prompt("claims_extract_sys")},
                {"role": "user", "content":
                    (platform_note + "\n\n" if platform_note else "")
                    + "Experiment plan:\n" + (plan_text or "")[:6000]},
            ],
            temperature=0.0,
            max_tokens=4096,
        )
        _choice = _resp.choices[0]
        _raw = _choice.message.content or ""
        try:
            _m = _re.search(r"\{.*\}", _raw, _re.DOTALL)
            if _m:
                return _normalize_claims(_json.loads(_m.group(0)))
            _logger.warning(
                "claims extraction: no JSON in response (finish_reason=%s, len=%d)",
                getattr(_choice, "finish_reason", "?"), len(_raw))
        except Exception as _pe:
            _logger.warning(
                "claims extraction: JSON parse failed (%s; finish_reason=%s, len=%d)",
                _pe, getattr(_choice, "finish_reason", "?"), len(_raw))
    except Exception as _e:
        _logger.warning("claims extraction: LLM call failed: %s", _e)
    return []


async def _resolve_falsifiable_claims(checkpoint_dir: str | None = None) -> list:
    """Resolve the idea's falsifiable claims for the plan-fidelity contract.

    Structured ``falsifiable_claims`` (idea-owned) take precedence; else the
    experiment_plan prose is LLM-extracted. ``[]`` when unavailable (legacy / no idea),
    so the coverage check is a no-op.
    """
    structured, plan = _load_idea_claims_source(checkpoint_dir)
    if structured:
        return _normalize_claims(structured)
    if plan:
        return await _llm_extract_claims(
            plan, platform_note=_load_platform_note(checkpoint_dir))
    return []


# ── idea-owned requirement flags (G) ──────────────────────────────────────────
# The IDEA (not the agent, not the metric NAME) decides WHETHER a correctness check
# / a measured ceiling is required. Both default FALSE so a missed extraction never
# forces a check a domain cannot satisfy (a theory result sets neither; a metric
# normalized by an analytic constant like a Carnot/Shannon limit sets
# ceiling_must_be_measured=false because that denominator is not microbenchmarkable).
# The gate enforces these via the _provenance EVIDENCE already flowing from
# results.json (a measured-ceiling tag / a correctness tag), so the agent satisfies
# them by emitting evidence -- NO cross-party naming and NO universal over-block.


async def _llm_extract_contract_flags(plan_text: str) -> dict:
    try:
        import litellm as _litellm, os as _os, json as _json, re as _re
        _model = (_os.environ.get("ARI_MODEL_EVAL")
                  or _os.environ.get("ARI_MODEL")
                  or _os.environ.get("ARI_LLM_MODEL")
                  or "gpt-4o-mini")
        _resp = await _litellm.acompletion(
            model=_model,
            messages=[
                {"role": "system", "content": _load_prompt("contract_flags_sys")},
                {"role": "user", "content": "Experiment plan:\n" + (plan_text or "")[:6000]},
            ],
            temperature=0.0,
            max_tokens=60,
        )
        _raw = _resp.choices[0].message.content or ""
        _m = _re.search(r"\{.*\}", _raw, _re.DOTALL)
        if _m:
            _o = _json.loads(_m.group(0)) or {}
            return {"correctness_required": bool(_o.get("correctness_required")),
                    "ceiling_must_be_measured": bool(_o.get("ceiling_must_be_measured"))}
    except Exception:
        pass
    return {"correctness_required": False, "ceiling_must_be_measured": False}


def _load_idea_plan_text(checkpoint_dir: str | None = None) -> str:
    """Load the selected idea's experiment_plan prose, INDEPENDENT of whether the idea
    also carries structured falsifiable_claims. (``_load_idea_claims_source`` short-
    circuits on structured claims and returns no plan, which would silently disable the
    flag resolver on the structured path.) ``""`` when unavailable."""
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
        best = _d
        if isinstance(_d.get("ideas"), list) and _d["ideas"]:
            best = _d["ideas"][0] or {}
        plan = best.get("experiment_plan") or _d.get("experiment_plan") or ""
        if isinstance(plan, str) and plan.strip():
            return plan
    return ""


async def _resolve_contract_flags(checkpoint_dir: str | None = None) -> dict:
    """Resolve the idea-owned requirement flags from the experiment_plan, INDEPENDENT
    of whether the idea also carries structured falsifiable_claims. Default both False,
    so the gate never forces a check a domain (a theory result) cannot satisfy."""
    plan = _load_idea_plan_text(checkpoint_dir)
    if plan:
        return await _llm_extract_contract_flags(plan)
    return {"correctness_required": False, "ceiling_must_be_measured": False}


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

    # MINT-ONCE: the run-level contract is a frozen promise. Re-extraction mints
    # a NEW evidence vocabulary on every call (LLM naming is not referentially
    # stable), and a mid-run regeneration silently hides sibling evidence emitted
    # under the previous names from the exact-match gate — observed on a real
    # run: the contract was regenerated 3x and 3 of 6 "missing" claims had in
    # fact been measured under earlier names. When a persisted contract with
    # claims already exists, return it VERBATIM (per-node spec fields above stay
    # per-call); a re-call becomes a harmless re-read of the obligations.
    try:
        import os as _os_fz
        from pathlib import Path as _P_fz
        _ck_fz = (arguments.get("checkpoint_dir")
                  or _os_fz.environ.get("ARI_CHECKPOINT_DIR", "") or "").strip()
        if _ck_fz:
            _fz_p = _P_fz(_ck_fz) / "metric_contract.json"
            if _fz_p.is_file():
                _persisted = json.loads(_fz_p.read_text())
                if isinstance(_persisted, dict) and _persisted.get("claims"):
                    return {
                        "expected_metrics": expected_metrics,
                        "expected_params": expected_params,
                        "metric_keyword": metric_keyword,
                        "min_expected_metric": min_expected,
                        "scoring_guide": scoring_guide,
                        "metric_contract": _persisted,
                        "contract_frozen": True,
                    }
    except Exception:
        pass

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

    # F: plan-fidelity — attach the idea's falsifiable claims so the gate can block a
    # declared-but-untested claim (claim_evidence_missing). Idea-owned, so the agent
    # cannot remove a claim to dodge the check; the producer obligation surfaces the
    # required_evidence names. Decoupled from concept-classification: claims are
    # enforced whenever the idea declares them, even for a non-normalized metric.
    try:
        _claims = await _resolve_falsifiable_claims(arguments.get("checkpoint_dir"))
    except Exception:
        _claims = []
    if _claims:
        if not isinstance(metric_contract, dict):
            metric_contract = {"key": metric_keyword or "", "claims": _claims}
        else:
            metric_contract["claims"] = _claims
    elif isinstance(metric_contract, dict):
        metric_contract.setdefault("claims", [])

    # G: idea-owned requirement flags (correctness_required / ceiling_must_be_measured).
    # The idea decides WHETHER each check is required; the agent satisfies it by emitting
    # the corresponding _provenance EVIDENCE (a measured-ceiling tag / a correctness tag),
    # which already flows results.json -> config._provenance -> gate. Both default false
    # (theory-safe). The agent cannot drop a requirement, and because the gate keys on
    # evidence PRESENCE (not an agent-declared name) there is no universal over-block.
    try:
        _flags = await _resolve_contract_flags(arguments.get("checkpoint_dir"))
    except Exception:
        _flags = {}
    if _flags.get("correctness_required") or _flags.get("ceiling_must_be_measured"):
        if not isinstance(metric_contract, dict):
            metric_contract = {"key": metric_keyword or ""}
        if _flags.get("correctness_required"):
            metric_contract["correctness_required"] = True
        if _flags.get("ceiling_must_be_measured"):
            metric_contract["ceiling_must_be_measured"] = True

    # Persist the run-level contract next to idea.json/tree.json so the paper
    # pipeline (nodes_to_science_data) can graft it onto science_data.json for the
    # hard gate. Without this the DECLARED contract (claims / correctness /
    # required_measured / recompute / declared invariants) never reaches the gate --
    # only the universal invariant registry does. Best-effort; FIRST MINT ONLY
    # (when a claims-bearing contract is already persisted, the freeze block
    # above returns it before reaching here — LLM re-extraction is NOT
    # referentially stable, so regeneration would change the evidence
    # vocabulary mid-run). Never break the spec on a write failure.
    if isinstance(metric_contract, dict) and metric_contract:
        try:
            import os as _os_mc
            from pathlib import Path as _P_mc
            _ck_mc = (arguments.get("checkpoint_dir")
                      or _os_mc.environ.get("ARI_CHECKPOINT_DIR", "") or "").strip()
            if _ck_mc and _P_mc(_ck_mc).is_dir():
                (_P_mc(_ck_mc) / "metric_contract.json").write_text(
                    json.dumps(metric_contract, ensure_ascii=False, indent=2))
        except Exception:
            pass

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
                # RAW delta — negative means the count INCREASED after refine
                # (a regression the old max(0, ...) clamp silently hid).
                report["resolved_overclaim_count"] = (
                    pj.get("detected_overclaim_count", 0)
                    - report.get("detected_overclaim_count", 0)
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
                {"role": "system", "content": _load_prompt("semantic_review_sys")},
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
