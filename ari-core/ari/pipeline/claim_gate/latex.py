"""Compatibility imports for the canonical LaTeX claim parser."""

from ari.latex_claims import (
    build_section_map,
    extract_numeric_mentions,
    figure_references as figure_refs,
    find_claim_anchors as find_anchors,
    section_at,
)

__all__ = [
    "build_section_map",
    "extract_numeric_mentions",
    "figure_refs",
    "find_anchors",
    "section_at",
]
