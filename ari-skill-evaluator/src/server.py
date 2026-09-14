"""MCP boundary for immutable metric contracts and scientific claim gates."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool


server = Server("evaluator-skill")
_logger = logging.getLogger("evaluator-skill")

try:
    from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore

    _ari_cost_tracker.bootstrap_skill("evaluator")
except Exception:
    pass


def _prompt_path(key: str) -> Path:
    return Path(__file__).resolve().parent / "prompts" / f"{key}.md"


def _load_prompt(key: str) -> str:
    text = _prompt_path(key).read_text(encoding="utf-8")
    return text[:-1] if text.endswith("\n") else text


def _load_prompt_versioned(key: str) -> tuple[str, str]:
    raw = _prompt_path(key).read_bytes()
    return _load_prompt(key), "sha256:" + hashlib.sha256(raw).hexdigest()


def _parse_success_metrics(text: str) -> list[str]:
    """Deterministically parse explicitly declared experiment metrics."""

    match = re.search(
        r"##\s*Success Metrics.*?\n(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        found = re.findall(r"-\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*:", match.group(1))
        if found:
            return list(dict.fromkeys(found))
    inline = re.search(r"(?:^|\n)Metrics?:\s*([^\n]+)", text, re.IGNORECASE)
    if inline:
        return list(
            dict.fromkeys(
                item.strip().strip("/")
                for item in re.split(r"[,;]", inline.group(1))
                if item.strip()
            )
        )
    marker = re.search(r"metric_keyword:\s*([A-Za-z_][A-Za-z0-9_.-]*)", text)
    return [marker.group(1)] if marker else []


def _parse_metric_keyword(text: str) -> str | None:
    match = re.search(r"metric_keyword:\s*([A-Za-z_][A-Za-z0-9_.-]*)", text)
    return match.group(1) if match else None


def _parse_min_expected(text: str) -> float | None:
    match = re.search(
        r"min_expected_metric:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", text
    )
    return float(match.group(1)) if match else None


def _build_scoring_guide(
    expected_metrics: list[str],
    metric_keyword: str | None,
    min_expected: float | None,
) -> str:
    """Build the compatibility scoring guide without inventing a metric."""

    keyword = metric_keyword or "metric"
    minimum = 0.0 if min_expected is None else min_expected
    lines = [
        f"STEP 1 - Extract numeric {keyword} values from artifacts.",
        f"  has_real_data=true only if actual {keyword} numbers appear in artifacts.",
        f"  If no {keyword} values found: score=0.2, stop here.",
        "",
        f"STEP 2 - Evaluate {keyword} quality.",
        f"  Target threshold: {minimum:g} (from experiment spec).",
        "  Interpret direction only from the admitted metric contract.",
        "",
        "STEP 3 - Preserve the multi-objective evaluation record; do not treat this",
        "  compatibility score as scientific truth.",
        "",
        "Always extract actual numbers into metrics dict:",
        "  metrics = {"
        + ", ".join(f"{metric}: <value>" for metric in expected_metrics)
        + "}",
    ]
    return "\n".join(lines)


def _checkpoint_root(explicit: str | None) -> Path | None:
    value = (explicit or os.environ.get("ARI_CHECKPOINT_DIR", "")).strip()
    return Path(value).expanduser().resolve() if value else None


def _load_jsonish(value: Any) -> dict:
    """Load one JSON object from an object, exact string, or file path."""

    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        path = Path(value)
        if not path.is_file():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}


def _science_projection(value: Any) -> dict:
    """Normalize native v1; pre-v1 callers remain visibly legacy."""

    loaded = _load_jsonish(value)
    if loaded.get("schema_version") != "ari.science-data/v1":
        return loaded
    from ari.public.science_data import science_data_projection

    return science_data_projection(loaded)


def _atomic_json(root: Path, logical_name: str, document: dict) -> None:
    from ari.public.execution import WorkspaceRefV1

    root.mkdir(parents=True, exist_ok=True)
    workspace = WorkspaceRefV1(root=str(root))
    workspace.atomic_write_bytes(
        logical_name,
        (
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8"),
    )


def _load_typed_research_contract(checkpoint_dir: str | None = None):
    """Load the exact idea-owned contract; typed downgrade attempts fail closed."""

    root = _checkpoint_root(checkpoint_dir)
    if root is None or not (root / "idea.json").is_file():
        return None
    try:
        document = json.loads((root / "idea.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    from ari.public.research_contract import parse_research_contract_document

    return parse_research_contract_document(document)


def _persist_metric_projection(
    root: Path, projection: dict, decision: dict | None = None
) -> None:
    from ari.public.claim_gate import parse_metric_gate_contract

    target = root / "metric_contract.json"
    if target.is_file():
        try:
            existing = parse_metric_gate_contract(
                json.loads(target.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise ValueError(
                "existing metric_contract.json is not a canonical contract"
            ) from exc
        proposed = parse_metric_gate_contract(projection)
        if existing.projection_digest != proposed.projection_digest:
            raise ValueError("metric contract is mint-once and already differs")
    else:
        _atomic_json(root, "metric_contract.json", projection)
    if decision is not None:
        _atomic_json(root, "metric_admission_decision.json", decision)


def _parser_result(text: str) -> dict:
    metrics = _parse_success_metrics(text)
    keyword = _parse_metric_keyword(text) or (metrics[0] if len(metrics) == 1 else "")
    minimum = _parse_min_expected(text)
    return {
        "expected_metrics": metrics,
        "expected_params": [],
        "metric_keyword": keyword,
        "min_expected_metric": minimum,
        "scoring_guide": _build_scoring_guide(metrics, keyword, minimum),
    }


def _projection_response(
    projection: dict,
    parser: dict,
    *,
    contract_source: str,
    admission_decision: dict | None = None,
) -> dict:
    from ari.public.claim_gate import parse_metric_gate_contract

    admitted = parse_metric_gate_contract(projection)
    metric = admitted.metric_contract
    expected = list(dict.fromkeys((metric.name, *metric.required_evidence)))
    result = {
        "parser_result": parser,
        "expected_metrics": expected,
        "expected_params": [],
        "metric_keyword": metric.name,
        "metric_unit": metric.unit,
        "metric_direction": metric.direction,
        "min_expected_metric": parser["min_expected_metric"],
        "scoring_guide": _build_scoring_guide(
            expected, metric.name, parser["min_expected_metric"]
        ),
        "metric_contract": admitted.model_dump(mode="json"),
        "metric_contract_digest": metric.contract_digest,
        "projection_digest": admitted.projection_digest,
        "contract_frozen": True,
        "contract_source": contract_source,
        "admission_status": metric.admission_status,
    }
    if admitted.research_contract_digest:
        result["research_contract_digest"] = admitted.research_contract_digest
    if admission_decision is not None:
        result["admission_decision"] = admission_decision
    return result


def _proposal_source(arguments: dict) -> dict:
    supplied = arguments.get("idea_json")
    root = _checkpoint_root(arguments.get("checkpoint_dir"))
    if supplied is None and root is not None and (root / "idea.json").is_file():
        supplied = str(root / "idea.json")
    if isinstance(supplied, dict):
        return supplied
    if isinstance(supplied, str):
        path = Path(supplied)
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("idea_json path is not valid JSON") from exc
            if not isinstance(loaded, dict):
                raise ValueError("idea_json must contain an object")
            return loaded
        try:
            loaded = json.loads(supplied)
        except json.JSONDecodeError:
            return {"idea_text": supplied}
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("propose_metric_contract requires exact idea evidence")


async def _tool_propose_metric_contract(arguments: dict) -> dict:
    """Run the explicitly requested LLM proposal step; never admit its output."""

    import litellm

    from ari.public.claim_gate import MetricContractProposalV1
    from ari.public.research_contract import canonical_digest

    source = _proposal_source(arguments)
    if source.get("typed_schema_version") == "ari.research-contract/v1":
        raise ValueError("typed idea already owns an immutable metric contract")
    prompt, prompt_digest = _load_prompt_versioned("metric_contract_proposal_sys")
    model = (
        str(arguments.get("model") or "").strip()
        or os.environ.get("ARI_MODEL_METRIC_PROPOSAL", "").strip()
        or os.environ.get("ARI_LLM_MODEL", "").strip()
        or "gpt-4o-mini"
    )
    evidence_digest = canonical_digest(source)
    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(source, ensure_ascii=False, sort_keys=True)[:40_000],
            },
        ],
        temperature=0.0,
        max_tokens=4096,
        timeout=120,
    )
    raw = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise ValueError("metric proposal did not contain a JSON object")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError("metric proposal was not valid JSON") from exc
    contract = parsed.get("contract") if isinstance(parsed, dict) else None
    confidence = parsed.get("confidence") if isinstance(parsed, dict) else None
    if not isinstance(contract, dict) or not isinstance(confidence, (int, float)):
        raise ValueError("metric proposal lacks contract or confidence")
    proposal = MetricContractProposalV1.create(
        source_idea_digest=canonical_digest(source),
        evidence_digest=evidence_digest,
        model=model,
        model_revision=(str(arguments.get("model_revision") or "").strip() or None),
        prompt_digest=prompt_digest,
        proposed_contract=contract,
        confidence=float(confidence),
        requires_human_review=True,
    )
    document = proposal.model_dump(mode="json")
    root = _checkpoint_root(arguments.get("checkpoint_dir"))
    if root is not None:
        _atomic_json(root, "metric_contract_proposal.json", document)
    return document


async def _tool_make_metric_spec(arguments: dict) -> dict:
    """Deterministically materialize one frozen metric contract."""

    text = str(arguments.get("experiment_text") or "")
    parser = _parser_result(text)
    root = _checkpoint_root(arguments.get("checkpoint_dir"))
    typed_contract = _load_typed_research_contract(arguments.get("checkpoint_dir"))
    if typed_contract is not None:
        from ari.public.research_contract import metric_gate_projection

        if typed_contract.metric_contract.admission_status != "admitted":
            raise ValueError("idea metric contract still requires human review")
        projection = metric_gate_projection(typed_contract)
        if root is not None:
            _persist_metric_projection(root, projection)
        return _projection_response(
            projection,
            parser,
            contract_source="idea.research-contract/v1",
        )

    proposal_value = arguments.get("proposal_json")
    if proposal_value:
        from ari.public.claim_gate import (
            MetricContractProposalV1,
            admit_metric_contract_proposal,
        )

        proposal_doc = _load_jsonish(proposal_value)
        proposal = MetricContractProposalV1.model_validate(proposal_doc)
        reviewer = str(arguments.get("reviewer") or "").strip()
        if not reviewer:
            return {
                **parser,
                "parser_result": parser,
                "metric_contract": None,
                "contract_frozen": False,
                "admission_status": "human-review-required",
                "proposal_digest": proposal.proposal_digest,
            }
        projection_model, decision_model = admit_metric_contract_proposal(
            proposal, reviewer=reviewer
        )
        projection = projection_model.model_dump(mode="json")
        decision = decision_model.model_dump(mode="json")
        if root is None:
            raise ValueError("human admission requires checkpoint_dir")
        _persist_metric_projection(root, projection, decision)
        return _projection_response(
            projection,
            parser,
            contract_source="human-admitted-proposal/v1",
            admission_decision=decision,
        )

    if root is not None and (root / "metric_contract.json").is_file():
        from ari.public.claim_gate import (
            migrate_legacy_metric_gate_contract,
            parse_metric_gate_contract,
        )

        document = json.loads(
            (root / "metric_contract.json").read_text(encoding="utf-8")
        )
        if document.get("schema_version") == "ari.metric-gate-contract/v1":
            projection = parse_metric_gate_contract(document).model_dump(mode="json")
            return _projection_response(
                projection, parser, contract_source="persisted-canonical/v1"
            )
        migrated = migrate_legacy_metric_gate_contract(document)
        projection = migrated.model_dump(mode="json")
        return _projection_response(
            projection, parser, contract_source="legacy-migration-reader/v1"
        )

    return {
        **parser,
        "parser_result": parser,
        "metric_contract": None,
        "contract_frozen": False,
        "admission_status": "human-review-required",
        "proposal_tool": "propose_metric_contract",
        "note": (
            "No immutable idea-owned contract exists. Parser output is evidence only; "
            "it was not promoted to a scientific contract."
        ),
    }


async def _tool_claim_evidence_hard_gate(arguments: dict) -> dict:
    """Thin MCP wrapper over the canonical deterministic hard gate."""

    from ari.public.claim_gate import run_hard_gate

    root = _checkpoint_root(arguments.get("checkpoint_dir"))
    paper_path = str(arguments.get("paper_path") or arguments.get("tex_path") or "")
    if root is None and paper_path:
        root = Path(paper_path).expanduser().resolve().parent
    if root is None:
        raise ValueError("claim gate requires checkpoint_dir")
    phase = str(arguments.get("phase") or "draft").strip().lower()
    if phase not in {"draft", "final"}:
        raise ValueError("claim gate phase must be draft or final")
    paper_tex = ""
    if paper_path:
        path = Path(paper_path)
        if path.is_file():
            paper_tex = path.read_text(encoding="utf-8")
    science_data = _science_projection(arguments.get("science_data_json"))
    claim_links = _load_jsonish(
        arguments.get("paper_claim_links_path")
        or arguments.get("paper_claim_links_json")
    )
    figures = _load_jsonish(arguments.get("figures_manifest_json")) or None
    report = run_hard_gate(
        root,
        paper_tex=paper_tex,
        science_data=science_data,
        paper_claim_links=claim_links or None,
        figures_manifest=figures,
        policy=arguments.get("policy"),
        phase=phase,
    )
    if report.get("should_block"):
        count = len(report.get("blocking_findings") or ())
        return {
            "error": (
                f"claim_evidence_hard_gate ({phase}): {count} blocking finding(s); "
                f"see evaluation/claim_evidence_hard_gate_{phase}.json"
            )
        }
    return report


def _agg_score(scores: dict) -> float:
    values = [
        float(value)
        for value in (scores or {}).values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sum(values) / len(values) if values else 0.0


def _semantic_model(arguments: dict) -> str:
    return (
        str(arguments.get("model") or "").strip()
        or os.environ.get("ARI_MODEL_SEMANTIC_REVIEW", "").strip()
        or os.environ.get("ARI_LLM_MODEL", "").strip()
        or "gpt-4o-mini"
    )


def _semantic_report(
    *,
    phase: str,
    status: str,
    model: str,
    model_revision: str | None,
    prompt_digest: str,
    evidence_digest: str,
    hard_gate_report_digest: str | None,
    findings: tuple = (),
    revisions: tuple = (),
    scores: dict | None = None,
    previous: Any = None,
    note: str | None = None,
):
    from ari.public.claim_gate import SemanticReviewV1

    score_delta = None
    resolved_count = 0
    previous_digest = None
    if previous is not None:
        previous_digest = previous.review_digest
        score_delta = round(_agg_score(scores or {}) - _agg_score(previous.scores), 4)
        resolved_count = previous.detected_overclaim_count - sum(
            item.type in {"overclaim", "overgeneralization", "unsupported_claim"}
            for item in findings
        )
    detected = sum(
        item.type in {"overclaim", "overgeneralization", "unsupported_claim"}
        for item in findings
    )
    return SemanticReviewV1.create(
        phase=phase,
        status=status,
        model=model,
        model_revision=model_revision,
        prompt_digest=prompt_digest,
        evidence_digest=evidence_digest,
        hard_gate_report_digest=hard_gate_report_digest,
        scores=scores or {},
        findings=findings,
        suggested_revisions=revisions,
        detected_overclaim_count=detected,
        previous_review_digest=previous_digest,
        score_delta=score_delta,
        resolved_overclaim_count=resolved_count,
        human_verified_overclaim_precision=None,
        note=note,
    )


async def _tool_evidence_grounded_semantic_review(arguments: dict) -> dict:
    """Run a provenance-bound advisory review without modifying hard-gate state."""

    from ari.public.claim_gate import (
        SemanticFindingV1,
        SemanticRevisionV1,
        parse_gate_report,
        parse_semantic_review,
    )
    from ari.public.research_contract import canonical_digest

    root = _checkpoint_root(arguments.get("checkpoint_dir"))
    paper_path = str(arguments.get("paper_path") or arguments.get("tex_path") or "")
    if root is None and paper_path:
        root = Path(paper_path).expanduser().resolve().parent
    if root is None:
        raise ValueError("semantic review requires checkpoint_dir")
    phase = str(arguments.get("phase") or "initial").strip().lower() or "initial"
    suffix = "" if phase in {"initial", "draft"} else f"_{phase}"
    output_name = f"evaluation/evidence_grounded_semantic_review{suffix}.json"
    model = _semantic_model(arguments)
    model_revision = (
        str(arguments.get("model_revision") or "").strip()
        or os.environ.get("ARI_SEMANTIC_REVIEW_MODEL_REVISION", "").strip()
        or None
    )
    prompt, prompt_digest = _load_prompt_versioned("semantic_review_sys")

    paper_tex = ""
    if paper_path and Path(paper_path).is_file():
        paper_tex = Path(paper_path).read_text(encoding="utf-8")
    science_data = _science_projection(arguments.get("science_data_json"))
    claim_links = _load_jsonish(arguments.get("paper_claim_links_path"))
    hard_gate_path = Path(str(arguments.get("hard_gate_path") or ""))
    hard_gate = {}
    hard_gate_bytes = None
    hard_gate_report_digest = None
    if hard_gate_path.is_file():
        hard_gate_bytes = hard_gate_path.read_bytes()
        try:
            hard_gate = json.loads(hard_gate_bytes)
        except json.JSONDecodeError:
            hard_gate = {}
        if hard_gate.get("schema_version") == "ari.gate-report/v1":
            hard_gate_report_digest = parse_gate_report(hard_gate).report_digest
        elif hard_gate:
            hard_gate_report_digest = canonical_digest(hard_gate)
    evidence_digest = canonical_digest(
        {
            "paper": canonical_digest(paper_tex),
            "science_data": science_data,
            "claim_links": claim_links,
            "hard_gate_report_digest": hard_gate_report_digest,
        }
    )

    previous = None
    previous_path = root / "evaluation" / "evidence_grounded_semantic_review.json"
    if suffix and previous_path.is_file():
        try:
            previous = parse_semantic_review(
                json.loads(previous_path.read_text(encoding="utf-8"))
            )
        except Exception:
            previous = None

    if not paper_tex:
        report_model = _semantic_report(
            phase=phase,
            status="unavailable",
            model=model,
            model_revision=model_revision,
            prompt_digest=prompt_digest,
            evidence_digest=evidence_digest,
            hard_gate_report_digest=hard_gate_report_digest,
            previous=previous,
            note="no paper text available; hard-gate result is unchanged",
        )
    else:
        claim_lines = "; ".join(
            f"{item.get('id')}: {item.get('text', '')}"
            for item in science_data.get("claims", [])
            if isinstance(item, dict)
        )[:4_000]
        gate_summary = json.dumps(
            {
                "blocking_findings": hard_gate.get("blocking_findings", []),
                "advisory_findings": hard_gate.get("advisory_findings", []),
                "metrics": hard_gate.get("metrics", {}),
            },
            ensure_ascii=False,
        )[:8_000]
        user_prompt = (
            f"Candidate claims:\n{claim_lines}\n\n"
            f"Immutable hard-gate findings (do not re-check or alter):\n{gate_summary}\n\n"
            f"Paper (LaTeX):\n{paper_tex[:36_000]}"
        )
        try:
            import litellm

            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 1500,
                "timeout": 120,
            }
            api_base = os.environ.get("ARI_LLM_API_BASE", "").strip()
            if api_base:
                kwargs["api_base"] = api_base
            response = await litellm.acompletion(**kwargs)
            raw = response.choices[0].message.content or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match is None:
                raise ValueError("semantic reviewer returned no JSON object")
            parsed = json.loads(match.group(0))
            raw_findings = parsed.get("findings")
            if raw_findings is None:
                # Compatibility reader for responses generated by the pre-v1
                # prompt. New model calls emit the canonical field name.
                raw_findings = parsed.get("warnings", [])
            findings = tuple(
                SemanticFindingV1.model_validate(item)
                for item in raw_findings
            )
            revisions = tuple(
                SemanticRevisionV1.model_validate(item)
                for item in parsed.get("suggested_revisions", [])
            )
            scores = parsed.get("scores") or {}
            report_model = _semantic_report(
                phase=phase,
                status="revise" if findings or revisions else "ok",
                model=model,
                model_revision=model_revision,
                prompt_digest=prompt_digest,
                evidence_digest=evidence_digest,
                hard_gate_report_digest=hard_gate_report_digest,
                findings=findings,
                revisions=revisions,
                scores=scores,
                previous=previous,
            )
        except Exception as exc:
            _logger.warning("semantic review unavailable: %s", exc)
            report_model = _semantic_report(
                phase=phase,
                status="unavailable",
                model=model,
                model_revision=model_revision,
                prompt_digest=prompt_digest,
                evidence_digest=evidence_digest,
                hard_gate_report_digest=hard_gate_report_digest,
                previous=previous,
                note=f"semantic review unavailable; hard-gate result is unchanged ({exc})",
            )

    document = report_model.model_dump(mode="json")
    _atomic_json(root, output_name, document)
    if hard_gate_bytes is not None and hard_gate_path.read_bytes() != hard_gate_bytes:
        raise RuntimeError("semantic review modified the immutable hard-gate report")
    return document


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="make_metric_spec",
            description=(
                "Deterministically materializes a MetricSpec from an immutable "
                "ResearchContractV1 or explicitly human-admitted proposal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_text": {"type": "string"},
                    "checkpoint_dir": {"type": "string"},
                    "proposal_json": {},
                    "reviewer": {"type": "string"},
                },
                "required": ["experiment_text"],
            },
        ),
        Tool(
            name="propose_metric_contract",
            description=(
                "Explicit LLM proposal step. Output always requires human review "
                "and cannot replace an idea-owned typed contract."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_json": {},
                    "checkpoint_dir": {"type": "string"},
                    "model": {"type": "string"},
                    "model_revision": {"type": "string"},
                },
            },
        ),
        Tool(
            name="claim_evidence_hard_gate",
            description=(
                "Deterministic GateReportV1 claim/evidence verification. Strict "
                "typed runs reject cross-run, missing, untyped, and digest-changed evidence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_dir": {"type": "string"},
                    "paper_path": {"type": "string"},
                    "science_data_json": {"type": "string"},
                    "paper_claim_links_path": {"type": "string"},
                    "figures_manifest_json": {"type": "string"},
                    "policy": {},
                    "phase": {
                        "type": "string",
                        "enum": ["draft", "final"],
                        "default": "draft",
                    },
                },
                "required": ["checkpoint_dir", "paper_path"],
            },
        ),
        Tool(
            name="evidence_grounded_semantic_review",
            description=(
                "Independent, non-blocking SemanticReviewV1 advisory review. Records "
                "model, revision, prompt digest, evidence digest, and hard-gate digest."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_dir": {"type": "string"},
                    "paper_path": {"type": "string"},
                    "science_data_json": {"type": "string"},
                    "hard_gate_path": {"type": "string"},
                    "paper_claim_links_path": {"type": "string"},
                    "phase": {"type": "string", "default": "initial"},
                    "model": {"type": "string"},
                    "model_revision": {"type": "string"},
                },
                "required": ["checkpoint_dir", "paper_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "make_metric_spec":
        result = await _tool_make_metric_spec(arguments)
    elif name == "propose_metric_contract":
        result = await _tool_propose_metric_contract(arguments)
    elif name == "claim_evidence_hard_gate":
        result = await _tool_claim_evidence_hard_gate(arguments)
    elif name == "evidence_grounded_semantic_review":
        result = await _tool_evidence_grounded_semantic_review(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [
        TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


if __name__ == "__main__":
    import asyncio

    from mcp.server.stdio import stdio_server

    async def main() -> None:
        async with stdio_server() as (reader, writer):
            await server.run(
                reader, writer, server.create_initialization_options()
            )

    asyncio.run(main())
