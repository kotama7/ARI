"""Reconcile canonical LaTeX claim anchors with ``ScienceDataV1`` evidence.

Lexical LaTeX parsing is owned by :mod:`ari.public.latex_claims`; this module
only performs paper-specific claim-registry and figure-manifest binding.
"""

from __future__ import annotations

import re
from typing import Any

from ari.public.latex_claims import (
    ANCHOR_RE,
    build_section_map,
    claim_span_hash,
    extract_numeric_mentions,
    find_claim_anchors,
    normalize_claim_sentence,
    section_at,
    sentence_for_anchor,
)
from ari.public.paper import canonical_paper_digest


# Compatibility names for the pure helpers historically imported by callers.
normalize_sentence = normalize_claim_sentence
span_hash = claim_span_hash
find_anchors = find_claim_anchors
_sentence_for_anchor = sentence_for_anchor


def _manifest_label_to_id(manifest: Any) -> dict[str, str]:
    """Map LaTeX figure labels to canonical figure IDs."""

    output: dict[str, str] = {}
    if not isinstance(manifest, dict):
        return output
    snippets = manifest.get("latex_snippets") or {}
    if isinstance(snippets, dict):
        for figure_id, snippet in snippets.items():
            for match in re.finditer(r"\\label\{([^}]*)\}", str(snippet)):
                output[match.group(1)] = str(figure_id)
    figures = manifest.get("figures")
    if isinstance(figures, dict):
        for figure_id in figures:
            output.setdefault(str(figure_id), str(figure_id))
    return output


def _figure_refs_in(text: str, label_to_id: dict[str, str]) -> list[str]:
    identities: list[str] = []
    for match in re.finditer(r"\\(?:ref|autoref|cref|Cref)\{([^}]*)\}", text):
        figure_id = label_to_id.get(match.group(1))
        if figure_id and figure_id not in identities:
            identities.append(figure_id)
    return identities


def _figure_evidence_lines(
    tex: str,
    label_to_id: dict[str, str],
    manifest: Any,
) -> set[int]:
    """Return lines inside figure blocks bound to FigureBatch evidence.

    Numeric caption text is owned by FigureBatchV1 and verified through its
    source/artifact digests. It must not become an unanchored prose-result
    obligation, while remaining visible in numeric_mentions for auditing.
    """

    figures = manifest.get("figures") if isinstance(manifest, dict) else None
    known_paths = (
        {str(path) for path in figures.values()}
        if isinstance(figures, dict)
        else set()
    )
    known_basenames = {path.rsplit("/", 1)[-1] for path in known_paths}
    output: set[int] = set()
    start: int | None = None
    buffer: list[str] = []
    for index, line in enumerate(tex.split("\n"), start=1):
        if start is None and re.search(r"\\begin\{figure\*?\}", line):
            start = index
            buffer = [line]
        elif start is not None:
            buffer.append(line)
        if start is None or not re.search(r"\\end\{figure\*?\}", line):
            continue
        block = "\n".join(buffer)
        labels = set(re.findall(r"\\label\{([^}]*)\}", block))
        paths = set(
            re.findall(
                r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}",
                block,
            )
        )
        bound = bool(labels & set(label_to_id)) or any(
            path in known_paths or path.rsplit("/", 1)[-1] in known_basenames
            for path in paths
        )
        if bound:
            output.update(range(start, index + 1))
        start = None
        buffer = []
    return output


def _index_claims(science_data: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return claim and numeric assertion indexes from a science projection."""

    claims_by_id: dict[str, dict] = {}
    numeric_by_id: dict[str, dict] = {}
    for claim in science_data.get("claims") or []:
        if isinstance(claim, dict) and claim.get("id"):
            claims_by_id[claim["id"]] = claim
            for assertion in claim.get("numeric_assertions") or []:
                if isinstance(assertion, dict) and assertion.get("id"):
                    numeric_by_id[assertion["id"]] = assertion
    for assertion in science_data.get("numeric_assertions") or []:
        if isinstance(assertion, dict) and assertion.get("id"):
            numeric_by_id.setdefault(assertion["id"], assertion)
    return claims_by_id, numeric_by_id


_DECL_RE = re.compile(r"([A-Za-z_]+)=([^\s]+)")
_VALID_ROLES = ("value", "baseline", "proposed")
_FORMULA_ALIASES = {
    "value": "identity",
    "absolute": "identity",
    "raw": "identity",
    "abs": "identity",
    "direct": "identity",
    "reported": "identity",
}


def known_formulas() -> frozenset[str]:
    """Read the hard gate's closed formula vocabulary through its public API."""

    try:
        from ari.public.claim_gate import FORMULAS

        return frozenset(FORMULAS)
    except Exception:  # pragma: no cover - standalone skill installation
        return frozenset()


def _unescape_latex(value: str) -> str:
    return re.sub(r"\\([_%&#$])", r"\1", value) if value else value


def _parse_writer_assertions(
    tex: str,
    config_nodes: dict,
) -> tuple[dict[str, dict], list[dict], list[dict]]:
    """Parse forward declarations and report every declaration not admitted."""

    output: dict[str, dict] = {}
    dropped: list[dict] = []
    suspect: list[dict] = []
    formulas = known_formulas()
    config_nodes = config_nodes or {}
    for line_number, line in enumerate(tex.split("\n"), start=1):
        for match in ANCHOR_RE.finditer(line):
            claim_id, numeric_id = match.group(1), match.group(2)
            tail = re.sub(
                r"\boperands?=(?=[A-Za-z_]+=)",
                "",
                line[match.end() :],
            )
            tokens = {
                key: _unescape_latex(value) for key, value in _DECL_RE.findall(tail)
            }
            metric = tokens.get("metric", "")
            formula = _FORMULA_ALIASES.get(tokens.get("formula"), tokens.get("formula"))
            if not formula:
                declared_configs = [
                    (tokens.get(role) or "").partition(":")[0]
                    for role in _VALID_ROLES
                    if tokens.get(role)
                ]
                dropped.append(
                    {
                        "claim_id": claim_id,
                        "numeric_id": numeric_id,
                        "line": line_number,
                        "reason": (
                            "no inline formula= declaration "
                            "(forward reference to pre-generated evidence)"
                        ),
                        "declared_metric": metric,
                        "declared_config_ids": declared_configs,
                        "declared_node_ids": [
                            (config_nodes.get(config_id) or {}).get("node_id", "")
                            for config_id in declared_configs
                        ],
                    }
                )
                continue
            if formulas and formula not in formulas:
                suspect.append(
                    {
                        "claim_id": claim_id,
                        "numeric_id": numeric_id,
                        "line": line_number,
                        "formula": formula,
                        "reason": (
                            f"unknown formula {formula!r} "
                            f"(not in {sorted(formulas)})"
                        ),
                    }
                )
            operands: dict = {}
            unresolved_refs: list[str] = []
            for role in _VALID_ROLES:
                reference = tokens.get(role)
                if not reference:
                    continue
                config_id, _, metric_override = reference.partition(":")
                node = config_nodes.get(config_id)
                operand_metric = metric_override or metric
                if node and node.get("node_id") and operand_metric:
                    operands[role] = {
                        "node_id": node["node_id"],
                        "metric_path": operand_metric,
                        "config_id": config_id,
                        "environment": node.get("environment", {}),
                    }
                else:
                    unresolved_refs.append(reference)
            if numeric_id in output:
                numeric_id = f"{numeric_id}@L{line_number}"
            record = {
                "id": numeric_id,
                "claim_id": claim_id,
                "metric": metric,
                "formula": formula,
                "operands": operands,
                "line": line_number,
                "source": "writer_declared",
            }
            if unresolved_refs:
                record["unresolved_config_refs"] = unresolved_refs
            output[numeric_id] = record
    return output, dropped, suspect


def link_paper_claims(
    tex: str,
    science_data: dict,
    figures_manifest: Any = None,
) -> dict:
    """Build deterministic paper claim links from native scientific evidence."""

    if science_data.get("schema_version") == "ari.science-data/v1":
        from ari.public.science_data import science_data_projection

        science_data = science_data_projection(science_data)
    lines = tex.split("\n")
    section_map = build_section_map(tex)
    claims_by_id, numeric_by_id = _index_claims(science_data or {})
    label_to_id = _manifest_label_to_id(figures_manifest)
    config_nodes = (science_data or {}).get("_config_nodes", {})
    writer_assertions, dropped_declarations, suspect_declarations = (
        _parse_writer_assertions(tex, config_nodes)
    )
    dropped_by_anchor = {
        (item.get("numeric_id"), item.get("line")): item
        for item in dropped_declarations
    }

    anchors = find_anchors(tex)
    links: list[dict] = []
    unresolved: list[dict] = []
    seen_anchor_keys: set[str] = set()
    assertions_by_line = {
        record.get("line"): record for record in writer_assertions.values()
    }

    for anchor in anchors:
        key = anchor["anchor"]
        line_assertion = assertions_by_line.get(anchor["line"])
        dedup_key = f"{key}@L{anchor['line']}" if line_assertion is not None else key
        if dedup_key in seen_anchor_keys:
            continue
        seen_anchor_keys.add(dedup_key)
        claim_id, numeric_id = anchor["claim_id"], anchor["numeric_id"]
        sentence, line_range = sentence_for_anchor(lines, anchor["line"])
        assertion = (
            line_assertion
            if line_assertion is not None
            else writer_assertions.get(numeric_id)
        )
        declared = bool(
            assertion
            and assertion.get("operands")
            and not assertion.get("unresolved_config_refs")
        )
        resolved = (
            claim_id in claims_by_id
            and (numeric_id in numeric_by_id or numeric_id == "NC0")
        ) or declared
        record = {
            "claim_id": claim_id,
            "numeric_id": (
                line_assertion.get("id") if line_assertion is not None else numeric_id
            ),
            "section": section_at(section_map, line_range[0]),
            "anchor": key,
            "span_hash": claim_span_hash(sentence),
            "line_range": line_range,
            "figures": _figure_refs_in(sentence, label_to_id),
            "resolved": resolved,
        }
        links.append(record)
        if not resolved:
            dropped = dropped_by_anchor.get((numeric_id, anchor["line"]))
            unresolved.append(
                {
                    "anchor": key,
                    "claim_id": claim_id,
                    "numeric_id": numeric_id,
                    "line": anchor["line"],
                    "reason": (
                        f"declaration dropped at parse: {dropped['reason']}"
                        if dropped
                        else "anchor references an id absent from science evidence"
                    ),
                }
            )

    numeric_mentions = extract_numeric_mentions(tex, section_map)
    figure_evidence_lines = _figure_evidence_lines(
        tex,
        label_to_id,
        figures_manifest,
    )
    numeric_mentions = [
        (
            {
                **mention,
                "type": "figure_evidence",
                "requires_assertion": False,
            }
            if mention["line"] in figure_evidence_lines
            else mention
        )
        for mention in numeric_mentions
    ]
    figure_refs = _figure_refs_in(tex, label_to_id)
    anchored_lines = {anchor["line"] for anchor in anchors}
    for anchor in anchors:
        _, line_range = sentence_for_anchor(lines, anchor["line"])
        anchored_lines.add(line_range[0])
    uncovered = [
        mention
        for mention in numeric_mentions
        if mention["requires_assertion"] and mention["line"] not in anchored_lines
    ]

    writer_assertion_values = list(writer_assertions.values())
    result = {
        "schema_version": "ari.paper-claim-links/v1",
        "stage": "link_paper_claims",
        "paper_digest": canonical_paper_digest({"latex": tex}),
        "paper_claim_links": links,
        "numeric_mentions": numeric_mentions,
        "writer_assertions": writer_assertion_values,
        "figure_refs": figure_refs,
        "unresolved_anchors": unresolved,
        "uncovered_numeric_candidates": uncovered,
        "dropped_declarations": dropped_declarations,
        "suspect_declarations": suspect_declarations,
        "counts": {
            "anchors": len(links),
            "resolved_anchors": sum(1 for record in links if record["resolved"]),
            "writer_assertions": len(writer_assertion_values),
            "dropped_declarations": len(dropped_declarations),
            "suspect_declarations": len(suspect_declarations),
            "numeric_mentions": len(numeric_mentions),
            "result_claim_mentions": sum(
                1 for mention in numeric_mentions if mention["type"] == "result_claim"
            ),
            "uncovered_numeric_candidates": len(uncovered),
            "figure_refs": len(figure_refs),
        },
    }
    result["claim_links_digest"] = canonical_paper_digest(result)
    return result


__all__ = [
    "build_section_map",
    "extract_numeric_mentions",
    "find_anchors",
    "link_paper_claims",
    "normalize_sentence",
    "span_hash",
]
