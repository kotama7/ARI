"""Provider-neutral contract adapter for the idea Skill.

Both the lightweight discussion loop and the vendored VirSci engine terminate
at this module.  It is the only place that normalizes their output, performs
scientific preflight, and mints the immutable ARI research hand-off.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from ari.public.execution import WorkspaceRefV1
from ari.public.research_contract import (
    CitationEdgeV1,
    IdeaCandidateV1,
    IdeaGenerationLockV1,
    IdeaGenerationProvenanceV1,
    IdeaRejectionV1,
    IdeaSetV1,
    MetricContractV1,
    MetricCorrectnessV1,
    MetricFormulaProvenanceV1,
    MetricToleranceV1,
    ResearchArtifactRefV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
    load_survey_snapshot_ref,
    mint_research_contract,
    validate_research_handoff,
)


ADAPTER_VERSION = "ari-skill-idea/0.2.0"
VIRSCI_VENDOR_COMMIT = "07097fd67efd177dd6d5304684d3657dc3411bc1"
VIRSCI_VENDOR_LICENSE = "Apache-2.0"
SPECTER2_DEFAULT_REVISION = "3447645e1def9117997203454fa4495937bfbd83"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _authors(raw: Any) -> tuple[str, ...]:
    out: list[str] = []
    if not isinstance(raw, (list, tuple)):
        return ()
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        text = str(name or "").strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _canonical_record_id(paper: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    aliases: list[str] = []
    external_ids = paper.get("externalIds") or {}
    if not isinstance(external_ids, dict):
        external_ids = {}
    doi = str(paper.get("doi") or external_ids.get("DOI") or "").strip().lower()
    arxiv = str(
        paper.get("arxiv_id") or external_ids.get("ArXiv") or ""
    ).strip().lower()
    s2_id = str(paper.get("paperId") or paper.get("paper_id") or "").strip()
    if doi:
        canonical = f"doi:{doi}"
    elif arxiv:
        canonical = f"arxiv:{arxiv}"
    elif s2_id:
        canonical = f"s2:{s2_id.lower()}"
    else:
        identity = {
            "title": " ".join(str(paper.get("title") or "").lower().split()),
            "year": paper.get("year"),
        }
        canonical = "content:" + canonical_digest(identity).removeprefix("sha256:")
    if doi:
        aliases.append(f"doi:{doi}")
    if arxiv:
        aliases.append(f"arxiv:{arxiv}")
    if s2_id:
        aliases.append(f"s2:{s2_id.lower()}")
    return canonical, tuple(item for item in aliases if item != canonical)


def normalize_retrieval_records(
    papers: Iterable[dict[str, Any]],
    *,
    query: str,
    provider: str,
    provider_version: str | None,
    retrieved_at: datetime | None,
) -> tuple[RetrievalRecordV1, ...]:
    """Normalize and deterministically de-duplicate provider records."""

    by_id: dict[str, RetrievalRecordV1] = {}
    for raw in papers:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        canonical_id, aliases = _canonical_record_id(raw)
        provider_record_id = str(
            raw.get("paperId") or raw.get("paper_id") or ""
        ).strip() or None
        source_url = str(raw.get("url") or "").strip() or None
        if source_url is None and provider_record_id and provider == "semantic-scholar":
            source_url = (
                "https://www.semanticscholar.org/paper/" + provider_record_id
            )
        payload_digest = canonical_digest(raw)
        record = RetrievalRecordV1(
            canonical_id=canonical_id,
            provider=provider,
            provider_record_id=provider_record_id,
            provider_version=provider_version,
            query=query,
            retrieved_at=retrieved_at,
            title=title,
            abstract=str(raw.get("abstract") or "")[:100_000],
            authors=_authors(raw.get("authors")),
            year=raw.get("year") if isinstance(raw.get("year"), int) else None,
            citation_count=(
                raw.get("citationCount")
                if isinstance(raw.get("citationCount"), int)
                else None
            ),
            source_url=source_url,
            payload_digest=payload_digest,
            aliases=aliases,
            license=(str(raw.get("license")).strip() if raw.get("license") else None),
            use_restriction=(
                str(raw.get("use_restriction")).strip()
                if raw.get("use_restriction")
                else None
            ),
        )
        previous = by_id.get(canonical_id)
        if previous is None or record.payload_digest < previous.payload_digest:
            by_id[canonical_id] = record
    # A provider can return the same work under multiple record IDs. Keep one
    # deterministic representative and preserve every losing ID as an alias.
    by_title: dict[str, RetrievalRecordV1] = {}
    for record in (by_id[key] for key in sorted(by_id)):
        title_key = " ".join(record.title.casefold().split())
        previous = by_title.get(title_key)
        if previous is None:
            by_title[title_key] = record
            continue
        previous_rank = (previous.citation_count or -1, previous.payload_digest)
        record_rank = (record.citation_count or -1, record.payload_digest)
        winner, loser = (
            (record, previous) if record_rank > previous_rank else (previous, record)
        )
        aliases = tuple(
            dict.fromkeys(
                (*winner.aliases, loser.canonical_id, *loser.aliases)
            )
        )
        payload = winner.model_dump(mode="json")
        payload["aliases"] = aliases
        by_title[title_key] = RetrievalRecordV1.model_validate(payload)
    return tuple(by_title[key] for key in sorted(by_title))


def paper_projection(snapshot: SurveySnapshotV1) -> list[dict[str, Any]]:
    """Legacy bounded paper list retained during the checkpoint support window."""

    return [
        {
            "title": record.title,
            "abstract": record.abstract[:1000],
            "year": record.year,
            "citationCount": record.citation_count or 0,
            "paperId": record.provider_record_id or "",
            "url": record.source_url or "",
            "canonical_id": record.canonical_id,
            "payload_digest": record.payload_digest,
        }
        for record in snapshot.records
    ]


def _json_bytes(document: Any) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_artifact(
    workspace: WorkspaceRefV1,
    logical_name: str,
    document: Any,
    *,
    role: str,
) -> ResearchArtifactRefV1:
    payload = _json_bytes(document)
    workspace.atomic_write_bytes(logical_name, payload)
    return ResearchArtifactRefV1(
        logical_name=logical_name,
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        role=role,
    )


def build_survey_snapshot(
    papers: Iterable[dict[str, Any]],
    *,
    query: str,
    mode: str,
    provider: str = "semantic-scholar",
    provider_version: str | None = "graph-v1",
    retrieved_at: datetime | None = None,
    byte_reproducible: bool,
    citation_edges: Iterable[CitationEdgeV1] = (),
    checkpoint_dir: str | Path | None = None,
    warnings: Iterable[str] = (),
) -> SurveySnapshotV1:
    records = normalize_retrieval_records(
        papers,
        query=query,
        provider=provider,
        provider_version=provider_version,
        retrieved_at=retrieved_at,
    )
    artifacts: tuple[ResearchArtifactRefV1, ...] = ()
    workspace: WorkspaceRefV1 | None = None
    if checkpoint_dir:
        root = Path(checkpoint_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = WorkspaceRefV1(root=str(root))
        raw_doc = [record.model_dump(mode="json") for record in records]
        artifacts = (
            _write_artifact(
                workspace,
                "survey_records_v1.json",
                raw_doc,
                role="normalized-retrieval-records",
            ),
        )
    snapshot = SurveySnapshotV1.create(
        mode=mode,
        provider=provider,
        provider_version=provider_version,
        query=query,
        retrieved_at=retrieved_at,
        byte_reproducible=byte_reproducible,
        records=records,
        citation_edges=tuple(citation_edges),
        artifacts=artifacts,
        warnings=tuple(warnings),
    )
    if workspace is not None:
        workspace.atomic_write_bytes(
            "survey_snapshot_v1.json",
            _json_bytes(snapshot.model_dump(mode="json")),
        )
    return snapshot


def load_survey_snapshot(
    checkpoint_dir: str | Path,
    logical_name: str = "survey_snapshot_v1.json",
) -> SurveySnapshotV1:
    """Load replay input through a closed workspace boundary; no network fallback."""

    # Replay is an execution mode, not a mutation of the recorded scientific
    # object: return the exact object and digest from record time after checking
    # every referenced cassette/raw artifact.
    return load_survey_snapshot_ref(str(checkpoint_dir), logical_name)


def inline_snapshot(
    papers: Iterable[dict[str, Any]],
    *,
    query: str,
    checkpoint_dir: str | Path | None,
) -> SurveySnapshotV1:
    return build_survey_snapshot(
        papers,
        query=query,
        mode="inline",
        provider="caller-inline",
        provider_version=None,
        retrieved_at=None,
        byte_reproducible=True,
        checkpoint_dir=checkpoint_dir,
        warnings=("retrieval timestamp and provider response identity unavailable",),
    )


def api_base_identity(api_base: str | None) -> str | None:
    """Record a credential-free routing identity, never URL userinfo/query data."""

    if not api_base:
        return None
    parsed = urlsplit(api_base)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname.lower()
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme.lower()}://{host}{port}"
    return canonical_digest(api_base)


def build_generation_lock(
    *,
    adapter: str,
    model: str,
    api_base: str | None,
    prompt_texts: Iterable[str],
    temperatures: Iterable[float],
    seed: int | None,
    snapshot: SurveySnapshotV1,
    topic: str,
    experiment_context: str,
    generation_parameters: dict[str, Any],
    model_revision: str | None,
) -> IdeaGenerationLockV1:
    return IdeaGenerationLockV1.create(
        adapter=adapter,
        adapter_version=ADAPTER_VERSION,
        model=model,
        api_base_identity=api_base_identity(api_base),
        prompt_digests=tuple(canonical_digest(text) for text in prompt_texts),
        temperatures=tuple(float(value) for value in temperatures),
        seed=seed,
        source_snapshot_digest=snapshot.snapshot_digest,
        topic_digest=canonical_digest(topic),
        experiment_context_digest=canonical_digest(experiment_context),
        vendor_commit=(
            VIRSCI_VENDOR_COMMIT
            if adapter in {"virsci-real", "default-discussion-vendor-prompts"}
            else None
        ),
        vendor_license=(
            VIRSCI_VENDOR_LICENSE
            if adapter in {"virsci-real", "default-discussion-vendor-prompts"}
            else None
        ),
        model_revision=model_revision,
        generation_parameters=generation_parameters,
    )


def _contract_for_title(metric_data: dict[str, Any], title: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    root_metric = metric_data.get("metric_contract")
    if isinstance(root_metric, dict):
        merged["metric_contract"] = dict(root_metric)
    else:
        merged["metric_contract"] = {
            key: metric_data[key]
            for key in (
                "primary_metric",
                "unit",
                "higher_is_better",
                "direction",
                "comparison_scope",
                "metric_rationale",
                "required_evidence",
                "correctness_required",
                "normalization_ceiling",
                "target_value",
                "formula",
                "operands",
                "tolerance",
                "required_measured",
                "invariants",
                "correctness",
                "confidence",
            )
            if key in metric_data
        }
    normalized_title = " ".join(title.lower().split())
    for item in metric_data.get("idea_contracts") or ():
        if not isinstance(item, dict):
            continue
        item_title = " ".join(str(item.get("title") or "").lower().split())
        if item_title == normalized_title:
            merged.update(item)
            if isinstance(item.get("metric_contract"), dict):
                merged["metric_contract"] = dict(item["metric_contract"])
            break
    return merged


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item or "").strip())


def _resolve_citations(
    values: Any,
    snapshot: SurveySnapshotV1,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    records = list(snapshot.records)
    known: dict[str, str] = {}
    for record in records:
        known[record.canonical_id.lower()] = record.canonical_id
        if record.provider_record_id:
            known[record.provider_record_id.lower()] = record.canonical_id
        for alias in record.aliases:
            known[alias.lower()] = record.canonical_id
    resolved: list[str] = []
    unknown: list[str] = []
    for value in values if isinstance(values, (list, tuple)) else ():
        if isinstance(value, int) and 1 <= value <= len(records):
            canonical = records[value - 1].canonical_id
        else:
            token = str(value or "").strip()
            canonical = known.get(token.lower())
        if canonical is None:
            unknown.append(str(value))
        elif canonical not in resolved:
            resolved.append(canonical)
    return tuple(resolved), tuple(unknown)


def _exception_detail(exc: Exception, *, limit: int = 200) -> str:
    """One line naming what a metric-contract construction actually failed on.

    Pydantic renders a ValidationError over several lines with a URL; the part
    worth keeping in a rejection record is the field and the message. Anything
    else is reduced to its own first line so a reason stays greppable.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            parts = [
                ".".join(str(x) for x in (item.get("loc") or ())) + ": " + str(item.get("msg") or "")
                for item in errors()
            ]
            if parts:
                return "; ".join(parts)[:limit]
        except Exception:  # a non-pydantic .errors attribute
            pass
    return " ".join(str(exc).split())[:limit]


def _metric_contract(
    raw: dict[str, Any], generation_lock: IdeaGenerationLockV1
) -> MetricContractV1:
    name = str(raw.get("name") or raw.get("primary_metric") or "").strip()
    direction = raw.get("direction")
    if direction is None and isinstance(raw.get("higher_is_better"), bool):
        direction = "higher" if raw["higher_is_better"] else "lower"
    confidence = float(raw.get("confidence", 0.0))
    correctness_raw = raw.get("correctness")
    correctness = None
    if isinstance(correctness_raw, dict) and correctness_raw:
        correctness = MetricCorrectnessV1(
            expr=str(correctness_raw.get("expr") or "").strip(),
            requires=_string_list(correctness_raw.get("requires")),
        )
    tolerance_raw = raw.get("tolerance")
    if not isinstance(tolerance_raw, dict):
        tolerance_raw = {}
    return MetricContractV1.create(
        name=name,
        unit=str(raw.get("unit") or "").strip(),
        direction=direction,
        comparison_scope=raw.get("comparison_scope"),
        rationale=str(raw.get("rationale") or raw.get("metric_rationale") or "").strip(),
        required_evidence=_string_list(raw.get("required_evidence")),
        correctness_required=raw.get("correctness_required"),
        normalization_ceiling=raw.get("normalization_ceiling"),
        target_value=raw.get("target_value"),
        formula=str(raw.get("formula") or "").strip(),
        operands={
            str(role): str(metric)
            for role, metric in (raw.get("operands") or {}).items()
        },
        tolerance=MetricToleranceV1(
            absolute=tolerance_raw.get("absolute"),
            relative=tolerance_raw.get("relative"),
        ),
        formula_provenance=MetricFormulaProvenanceV1(
            source="idea-generation-lock",
            source_digest=generation_lock.generation_lock_digest,
            model=generation_lock.model,
            prompt_digests=generation_lock.prompt_digests,
        ),
        required_measured=_string_list(raw.get("required_measured")),
        invariants=_string_list(raw.get("invariants")),
        correctness=correctness,
        confidence=confidence,
        admission_status=(
            "admitted" if confidence >= 0.8 else "human-review-required"
        ),
    )


def preflight_candidates(
    raw_ideas: list[dict[str, Any]],
    *,
    metric_data: dict[str, Any],
    snapshot: SurveySnapshotV1,
    generation_lock: IdeaGenerationLockV1,
    adapter: str,
) -> tuple[tuple[IdeaCandidateV1, ...], tuple[IdeaRejectionV1, ...]]:
    """Admit only falsifiable, cited, unit-complete, non-duplicate ideas."""

    candidates: list[IdeaCandidateV1] = []
    rejections: list[IdeaRejectionV1] = []
    duplicate_keys: set[str] = set()
    snapshot_artifacts = {item.digest for item in snapshot.artifacts}

    for raw in raw_ideas:
        raw_digest = canonical_digest(raw)
        title = str(raw.get("title") or "").strip()
        contract_data = _contract_for_title(metric_data, title)
        hypothesis = str(
            contract_data.get("hypothesis") or raw.get("hypothesis") or ""
        ).strip()
        falsification = _string_list(
            contract_data.get("falsification_conditions")
            or raw.get("falsification_conditions")
        )
        limitations = _string_list(
            contract_data.get("limitations") or raw.get("limitations")
        )
        citations, unknown_citations = _resolve_citations(
            contract_data.get("citations") or raw.get("citations"), snapshot
        )
        artifact_references = _string_list(
            contract_data.get("artifact_references")
            or raw.get("artifact_references")
        )
        reasons: list[str] = []
        if not title:
            reasons.append("missing_title")
        if not hypothesis:
            reasons.append("missing_hypothesis")
        if not str(raw.get("description") or "").strip():
            reasons.append("missing_description")
        if not str(raw.get("experiment_plan") or "").strip():
            reasons.append("missing_experiment_plan")
        if not falsification:
            reasons.append("missing_falsification_condition")
        if not citations:
            reasons.append("missing_citation")
        if unknown_citations:
            reasons.append("unknown_citation:" + ",".join(unknown_citations))
        unknown_artifacts = set(artifact_references) - snapshot_artifacts
        if unknown_artifacts:
            reasons.append(
                "unknown_artifact_reference:" + ",".join(sorted(unknown_artifacts))
            )
        if not limitations:
            reasons.append("missing_limitation")
        metric: MetricContractV1 | None = None
        try:
            metric = _metric_contract(
                contract_data.get("metric_contract") or {}, generation_lock
            )
            if metric.admission_status != "admitted":
                reasons.append("metric_contract_human_review_required")
        except Exception as exc:
            message = str(exc).lower()
            if "unit" in message:
                reasons.append("unknown_unit")
            if "required_evidence" in message:
                reasons.append("missing_required_evidence")
            reasons.append("invalid_metric_contract")
            # Keep the coarse reason above for anything matching on it, and add
            # what actually failed. Without this the rejection record said only
            # "invalid_metric_contract" for every cause the two substring tests
            # miss, and a run whose candidates all died on one unstated schema
            # invariant looked identical to one that produced nonsense.
            reasons.append(f"metric_contract_error: {_exception_detail(exc)}")
        duplicate_key = "\x00".join(
            (" ".join(title.lower().split()), " ".join(hypothesis.lower().split()))
        )
        if title and hypothesis and duplicate_key in duplicate_keys:
            reasons.append("duplicate_candidate")
        if reasons or metric is None:
            rejections.append(
                IdeaRejectionV1(
                    raw_candidate_digest=raw_digest,
                    title=title,
                    reasons=tuple(dict.fromkeys(reasons or ["invalid_candidate"])),
                    generator_adapter=adapter,
                )
            )
            continue
        duplicate_keys.add(duplicate_key)
        candidates.append(
            IdeaCandidateV1.create(
                title=title,
                hypothesis=hypothesis,
                description=str(raw["description"]).strip(),
                experiment_plan=str(raw["experiment_plan"]).strip(),
                falsification_conditions=falsification,
                metric_contract=metric,
                citations=citations,
                artifact_references=artifact_references,
                limitations=limitations,
                source_snapshot_digest=snapshot.snapshot_digest,
                generation_lock_digest=generation_lock.generation_lock_digest,
                generator_adapter=adapter,
                novelty_score=raw.get("novelty_score"),
                feasibility_score=raw.get("feasibility_score"),
                overall_score=raw.get("overall_score"),
            )
        )
    return tuple(candidates), tuple(rejections)


def build_idea_handoff(
    *,
    topic: str,
    snapshot: SurveySnapshotV1,
    raw_ideas: list[dict[str, Any]],
    metric_data: dict[str, Any],
    generation_lock: IdeaGenerationLockV1,
    generated_at: datetime,
    requested_adapter: str,
    actual_adapter: str,
    fallback_reason: str | None,
) -> tuple[IdeaSetV1, Any | None]:
    output_digest = canonical_digest(
        {"ideas": raw_ideas, "metric_contracts": metric_data}
    )
    provenance = IdeaGenerationProvenanceV1(
        lock=generation_lock,
        generated_at=generated_at,
        output_digest=output_digest,
        requested_adapter=requested_adapter,
        actual_adapter=actual_adapter,
        fallback_reason=fallback_reason,
    )
    candidates, rejections = preflight_candidates(
        raw_ideas,
        metric_data=metric_data,
        snapshot=snapshot,
        generation_lock=generation_lock,
        adapter=actual_adapter,
    )
    selected = candidates[0].candidate_id if candidates else None
    idea_set = IdeaSetV1.create(
        topic=topic,
        source_snapshot_digest=snapshot.snapshot_digest,
        generation=provenance,
        candidates=candidates,
        rejections=rejections,
        selected_candidate_id=selected,
    )
    contract = mint_research_contract(idea_set) if selected else None
    validate_research_handoff(snapshot=snapshot, idea_set=idea_set, contract=contract)
    return idea_set, contract


def enrich_legacy_ideas(
    legacy: list[dict[str, Any]], idea_set: IdeaSetV1
) -> list[dict[str, Any]]:
    """Attach typed identities/status without coercing rejected model output."""

    accepted_by_title = {
        " ".join(item.title.lower().split()): item for item in idea_set.candidates
    }
    rejected_by_title = {
        " ".join(item.title.lower().split()): item for item in idea_set.rejections
    }
    out: list[dict[str, Any]] = []
    for raw in legacy:
        item = dict(raw)
        key = " ".join(str(item.get("title") or "").lower().split())
        candidate = accepted_by_title.get(key)
        rejection = rejected_by_title.get(key)
        if candidate is not None:
            item.update(
                {
                    "candidate_id": candidate.candidate_id,
                    "contract_status": "admitted",
                    "hypothesis": candidate.hypothesis,
                    "falsification_conditions": list(
                        candidate.falsification_conditions
                    ),
                    "falsifiable_claims": [
                        {
                            "claim": condition,
                            "required_evidence": list(
                                candidate.metric_contract.required_evidence
                            ),
                        }
                        for condition in candidate.falsification_conditions
                    ],
                    "citations": list(candidate.citations),
                    "limitations": list(candidate.limitations),
                }
            )
        else:
            item["contract_status"] = "rejected"
            item["rejection_reasons"] = list(
                rejection.reasons if rejection is not None else ("invalid_candidate",)
            )
        out.append(item)
    return out


def metric_legacy_projection(metric_data: dict[str, Any]) -> dict[str, Any]:
    root = metric_data.get("metric_contract")
    metric = root if isinstance(root, dict) else metric_data
    name = str(metric.get("name") or metric.get("primary_metric") or "")
    direction = metric.get("direction")
    higher = metric.get("higher_is_better")
    if not isinstance(higher, bool):
        higher = direction != "lower"
    return {
        "primary_metric": name,
        "higher_is_better": higher,
        "metric_rationale": str(
            metric.get("rationale") or metric.get("metric_rationale") or ""
        ),
    }


def parse_metric_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
