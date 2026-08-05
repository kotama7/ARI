"""Deterministic, section-specific authoring briefs."""

from __future__ import annotations

import json
from typing import Any

from ari.manuscript.contracts import (
    ManuscriptContextV1,
    ManuscriptReadinessReportV1,
    ManuscriptRequirementProfileV1,
    SectionBriefBundleV1,
    SectionBriefV1,
)


RENDERER_VERSION = "manuscript-brief-renderer-v1"
DEFAULT_SECTIONS = (
    "abstract",
    "introduction",
    "related-work",
    "method",
    "experimental-setup",
    "results",
    "negative-results",
    "limitations",
    "reproducibility",
)


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _items_for(section: str, context: ManuscriptContextV1) -> list[dict[str, Any]]:
    if section == "abstract":
        return [
            {"item_id": "research-question", "kind": "research-question", "value": context.research_question},
            {"item_id": "subject-selection", "kind": "subjects", "value": context.subjects},
            {"item_id": "contributions", "kind": "contributions", "value": list(context.contribution_map)},
        ]
    if section == "introduction":
        return [
            {"item_id": "research-question", "kind": "research-question", "value": context.research_question},
            {"item_id": "contributions", "kind": "contributions", "value": list(context.contribution_map)},
        ]
    if section == "related-work":
        return [
            {"item_id": str(item.get("reference_id") or f"reference-{index}"), "kind": "reference", "value": item}
            for index, item in enumerate(context.related_work)
        ]
    if section == "method":
        return [
            {"item_id": str(item.get("method_id") or f"method-{index}"), "kind": "method", "value": item}
            for index, item in enumerate(context.methods)
        ] + [{"item_id": "exploration-history", "kind": "selection-history", "value": list(context.exploration_history)}]
    if section == "experimental-setup":
        return [{"item_id": "reproducibility", "kind": "setup", "value": context.reproducibility}]
    if section == "results":
        return [
            {"item_id": item.evidence_id, "kind": "evidence", "value": item.model_dump(mode="json")}
            for item in context.evidence_records
            if item.lane in {"publishable", "exploratory"}
        ]
    if section == "negative-results":
        return [
            {"item_id": f"negative:{item.get('node_id', index)}", "kind": "negative-result", "value": item}
            for index, item in enumerate(context.negative_results)
        ]
    if section == "limitations":
        return [
            {"item_id": f"limitation-{index:03d}", "kind": "limitation", "value": value}
            for index, value in enumerate(context.limitations)
        ] + [
            {"item_id": f"threat-{index:03d}", "kind": "threat-to-validity", "value": value}
            for index, value in enumerate(context.threats_to_validity)
        ]
    if section == "reproducibility":
        return [
            {"item_id": "reproducibility", "kind": "reproducibility", "value": context.reproducibility},
            {"item_id": "assurance", "kind": "assurance", "value": context.assurance},
        ]
    return []


def build_section_briefs(
    profile: ManuscriptRequirementProfileV1,
    context: ManuscriptContextV1,
    readiness: ManuscriptReadinessReportV1,
    *,
    character_budget: int = 24_000,
) -> SectionBriefBundleV1:
    if context.profile_digest != profile.profile_digest:
        raise ValueError("section brief context uses another profile")
    if readiness.context_digest != context.context_digest:
        raise ValueError("section brief readiness uses another context")
    allowed = tuple(item.evidence_id for item in context.evidence_records if item.publishable)
    negatives = tuple(
        item.evidence_id for item in context.evidence_records if item.lane == "contextual_negative"
    )
    forbidden = tuple(
        item.evidence_id for item in context.evidence_records if item.lane in {"exploratory", "excluded"}
    )
    disclosures = tuple(
        dict.fromkeys(
            list(context.limitations)
            + [
                item.explanation or item.reason_code
                for item in readiness.requirement_results
                if item.status == "unavailable"
            ]
        )
    )
    briefs: list[SectionBriefV1] = []
    for section in DEFAULT_SECTIONS:
        section_items = _items_for(section, context)
        section_disclosures = (
            disclosures if section in {"abstract", "limitations", "results"} else ()
        )
        disclosure_size = _size(section_disclosures)
        if disclosure_size >= character_budget and section_disclosures:
            raise ValueError(
                f"required manuscript disclosures cannot fit {section} brief budget"
            )
        available = character_budget - disclosure_size
        chunks: list[list[dict[str, Any]]] = [[]]
        used = 0
        for item in section_items:
            item_size = _size(item)
            if item_size > available:
                raise ValueError(
                    f"required manuscript item {item['item_id']} cannot fit {section} brief budget"
                )
            if chunks[-1] and used + item_size > available:
                chunks.append([])
                used = 0
            chunks[-1].append(item)
            used += item_size
        for chunk_index, included in enumerate(chunks):
            section_id = (
                section
                if chunk_index == 0
                else f"{section}.part-{chunk_index + 1:03d}"
            )
            briefs.append(
                SectionBriefV1.create(
                    section_id=section_id,
                    context_digest=context.context_digest,
                    readiness_digest=readiness.readiness_digest,
                    allowed_evidence_ids=allowed,
                    contextual_negative_ids=negatives,
                    forbidden_evidence_ids=forbidden,
                    required_disclosures=section_disclosures,
                    content_items=tuple(included),
                    omitted_item_ids=(),
                    character_budget=character_budget,
                )
            )
    return SectionBriefBundleV1.create(
        run_id=context.run_id,
        profile_digest=profile.profile_digest,
        context_digest=context.context_digest,
        readiness_digest=readiness.readiness_digest,
        renderer_version=RENDERER_VERSION,
        briefs=tuple(briefs),
    )


def render_brief_bundle(bundle: SectionBriefBundleV1) -> str:
    """Render a bounded deterministic block for legacy-compatible writer APIs."""

    lines = [
        "══ MANUSCRIPT COMPLETE AUTHORING BRIEFS ══",
        f"bundle_digest: {bundle.bundle_digest}",
        "Use only allowed evidence for positive factual claims. Exploratory or excluded evidence may not support headline claims.",
    ]
    for brief in bundle.briefs:
        lines.append(f"\n## {brief.section_id}")
        lines.append(f"brief_digest: {brief.brief_digest}")
        if brief.required_disclosures:
            lines.append("Required disclosures:")
            lines.extend(f"- {item}" for item in brief.required_disclosures)
        for item in brief.content_items:
            lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        if brief.omitted_item_ids:
            lines.append("Omitted by section budget (still addressable by ID): " + ", ".join(brief.omitted_item_ids))
    lines.append("══ END MANUSCRIPT COMPLETE AUTHORING BRIEFS ══")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_SECTIONS",
    "RENDERER_VERSION",
    "build_section_briefs",
    "render_brief_bundle",
]
