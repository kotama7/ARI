"""Immutable visual-review criterion profiles."""

from __future__ import annotations

from ari.public.visual_review import VisualCriteriaProfileV1, VisualCriterionV1


def _profile(
    profile_id: str,
    target_kind: str,
    passing_score: float,
    criteria: tuple[tuple[str, str], ...],
) -> VisualCriteriaProfileV1:
    return VisualCriteriaProfileV1.create(
        profile_id=profile_id,
        target_kind=target_kind,
        version="1.0.0",
        passing_score=passing_score,
        criteria=tuple(
            VisualCriterionV1(criterion_id=criterion_id, description=description)
            for criterion_id, description in criteria
        ),
    )


FIGURE_PUBLICATION_V1 = _profile(
    "figure-publication/v1",
    "figure",
    0.7,
    (
        ("source-integrity", "Visual content agrees with the bound caption and source data."),
        ("units-labels", "Axes, color bars, legends, and units are complete and unambiguous."),
        ("readability", "Text, marks, colors, and uncertainty remain readable at publication size."),
        ("comparability", "Scales and encodings do not imply invalid comparisons."),
        ("accessibility", "Color and layout remain interpretable without relying on hue alone."),
    ),
)

FIGURE_DOMAIN_INTEGRITY_V1 = _profile(
    "figure-domain-integrity/v1",
    "figure",
    0.75,
    (
        ("source-integrity", "The visible trends do not contradict the supplied scientific context."),
        ("uncertainty", "Uncertainty and sample scope are displayed or explicitly identified as absent."),
        ("domain-semantics", "Domain-specific axes, symbols, and comparison scope are scientifically valid."),
        ("readability", "The complete figure is legible at publication size."),
    ),
)

TABLE_PUBLICATION_V1 = _profile(
    "table-publication/v1",
    "table",
    0.7,
    (
        ("source-integrity", "Cells and totals agree with the bound table artifact and context."),
        ("units-labels", "Rows, columns, units, and footnotes are complete and unambiguous."),
        ("precision", "Numeric precision is consistent and does not overstate evidence."),
        ("readability", "Alignment and density remain readable at publication size."),
    ),
)


PROFILES = {
    profile.profile_id: profile
    for profile in (
        FIGURE_PUBLICATION_V1,
        FIGURE_DOMAIN_INTEGRITY_V1,
        TABLE_PUBLICATION_V1,
    )
}


def get_profile(profile_id: str, *, target_kind: str):
    try:
        profile = PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown visual criteria profile: {profile_id}") from exc
    if profile.target_kind != target_kind:
        raise ValueError("visual criteria profile target kind does not match")
    return profile


__all__ = [
    "FIGURE_DOMAIN_INTEGRITY_V1",
    "FIGURE_PUBLICATION_V1",
    "PROFILES",
    "TABLE_PUBLICATION_V1",
    "get_profile",
]
