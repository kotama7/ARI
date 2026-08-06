"""Canonical deterministic parsing of scientific claims in LaTeX.

This module is the single implementation shared by paper authoring and the
independent hard gate.  It deliberately performs lexical classification only;
whether a numeric assertion is scientifically valid remains the gate's job.
"""

from __future__ import annotations

import hashlib
import math
import re


ANCHOR_RE = re.compile(r"%\s*CLAIM:(C\w+):(NC\w+)")

_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:[eE]([+-]?\d+)(?!\w|\.\d)"
    r"|\s*(?:x|×|\\times|\\cdot)\s*10\^\{?([+-]?\d+)\}?"
    r"|\^\{?([+-]?\d+)\}?)?"
    r"\s*(%?)"
)

_STRIP_REGIONS = (
    re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref)\{[^}]*\}"),
    re.compile(r"\\label\{[^}]*\}"),
    re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\\(?:input|include)\{[^}]*\}"),
)

_PERF_UNIT_RE = re.compile(
    r"^\s*(?:%|x\b|×|GFlop|TFlop|MFlop|FLOP|GB/s|MB/s|TB/s|GiB/s|"
    r"speedup|faster|slower|reduction|improvement|gain)",
    re.IGNORECASE,
)
_SETTING_UNIT_RE = re.compile(
    r"^\s*(?:trials?|runs?|iterations?|cores?|threads?|nodes?|gpus?|cpus?|"
    r"ranks?|processes|seeds?|warmups?|repetitions?|epochs?)\b",
    re.IGNORECASE,
)
_REF_WORD_RE = re.compile(
    r"(?:figure|fig\.?|table|tab\.?|section|sec\.?|equation|eq\.?|"
    r"algorithm|alg\.?|listing)\s*$",
    re.IGNORECASE,
)


def normalize_claim_sentence(text: str) -> str:
    """Normalize prose for stable claim-span hashing."""

    value = ANCHOR_RE.sub("", text)
    value = re.sub(r"%.*", "", value)
    for region in _STRIP_REGIONS:
        value = region.sub(" ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", value)
    value = re.sub(r"[{}$~\\]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def claim_span_hash(text: str) -> str:
    payload = normalize_claim_sentence(text).encode("utf-8")
    return "sha256-" + hashlib.sha256(payload).hexdigest()


def _canonical_section(title: str) -> str:
    normalized = title.strip().lower()
    aliases = (
        ("introduction", "introduction"),
        ("related", "related_work"),
        ("background", "related_work"),
        ("prior work", "related_work"),
        ("method", "methodology"),
        ("approach", "methodology"),
        ("design", "methodology"),
        ("implementation", "methodology"),
        ("experiment", "experiments"),
        ("evaluation", "experiments"),
        ("setup", "experiments"),
        ("result", "results"),
        ("discussion", "discussion"),
        ("limitation", "limitations"),
        ("conclusion", "conclusion"),
        ("summary", "conclusion"),
        ("future work", "conclusion"),
        ("reference", "references"),
        ("bibliograph", "references"),
        ("acknowled", "acknowledgements"),
        ("abstract", "abstract"),
        ("appendix", "appendix"),
    )
    for needle, canonical in aliases:
        if needle in normalized:
            return canonical
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "body"


def build_section_map(tex: str) -> list[str]:
    """Return one canonical section name per source line."""

    result: list[str] = []
    current = "preamble"
    appendix = False
    section_pattern = re.compile(r"\\(?:sub)*section\*?\s*\{([^}]*)\}")
    for line in tex.split("\n"):
        stripped = line.strip()
        if "\\begin{abstract}" in stripped:
            current = "abstract"
            result.append(current)
            continue
        if "\\end{abstract}" in stripped:
            result.append(current)
            current = "body"
            continue
        if re.search(r"\\appendix\b", stripped):
            appendix = True
        match = section_pattern.search(stripped)
        if match:
            current = "appendix" if appendix else _canonical_section(match.group(1))
        elif re.search(r"\\bibliography\b|\\begin\{thebibliography\}", stripped):
            current = "references"
        result.append(current)
    return result


def section_at(section_map: list[str], line_number: int) -> str:
    index = line_number - 1
    return section_map[index] if 0 <= index < len(section_map) else "body"


def find_claim_anchors(tex: str) -> list[dict]:
    result: list[dict] = []
    for line_number, line in enumerate(tex.split("\n"), start=1):
        for match in ANCHOR_RE.finditer(line):
            result.append(
                {
                    "anchor": f"CLAIM:{match.group(1)}:{match.group(2)}",
                    "claim_id": match.group(1),
                    "numeric_id": match.group(2),
                    "line": line_number,
                }
            )
    return result


def sentence_for_anchor(lines: list[str], line_number: int) -> tuple[str, list[int]]:
    index = line_number - 1
    if 0 <= index < len(lines):
        raw = lines[index]
        if not raw.lstrip().startswith("%"):
            own = re.sub(r"^%+", "", ANCHOR_RE.sub("", raw)).strip()
            if own:
                return raw, [line_number, line_number]
    for next_index in range(index + 1, min(index + 4, len(lines))):
        if lines[next_index].strip() and not lines[next_index].strip().startswith("%"):
            return lines[next_index], [next_index + 1, next_index + 1]
    fallback = lines[index] if 0 <= index < len(lines) else ""
    return fallback, [line_number, line_number]


def _strip_for_scan(line: str) -> str:
    value = re.sub(r"(?<!\\)%.*$", "", line)
    for region in _STRIP_REGIONS:
        value = region.sub(" ", value)
    value = value.replace("\\%", "%")
    value = re.sub(r"\\times\b", " x ", value)
    value = re.sub(r"\\[,;:!> ]", " ", value)
    value = value.replace("\\(", " ").replace("\\)", " ")
    return value.replace("~", " ").replace("$", " ")


def _classify(
    numeric_text: str,
    has_percent: bool,
    before: str,
    after: str,
) -> tuple[str, bool]:
    try:
        value = float(numeric_text.replace(",", ""))
    except ValueError:
        return "ambiguous", False
    is_integer = "." not in numeric_text
    # A 2048-by-2048 product written with LaTeX times is a matrix shape,
    # whereas 4.18-times followed by prose is a speedup. The old unit regex
    # treated both as a result because it recognized any trailing x.
    dimension_product = bool(re.match(r"^\s*(?:x|×)\s*\d", after))
    if (
        is_integer
        and 1900 <= value <= 2099
        and not has_percent
        and not (_PERF_UNIT_RE.match(after) and not dimension_product)
        and not _SETTING_UNIT_RE.match(after)
    ):
        return "citation_year", False
    if _REF_WORD_RE.search(before):
        return "figure_table_ref", False
    if _SETTING_UNIT_RE.match(after):
        return "experimental_setting", False
    if has_percent or (_PERF_UNIT_RE.match(after) and not dimension_product):
        return "result_claim", True
    return "ambiguous", False


def extract_numeric_mentions(
    tex: str,
    section_map: list[str] | None = None,
) -> list[dict]:
    """Extract finite numeric tokens and their lexical evidence class."""

    sections = section_map if section_map is not None else build_section_map(tex)
    mentions: list[dict] = []
    for line_number, raw in enumerate(tex.split("\n"), start=1):
        line = _strip_for_scan(raw)
        for match in _NUMBER_RE.finditer(line):
            integer, fraction = match.group(1), match.group(2) or ""
            exponent = match.group(3) or match.group(4) or ""
            bare_power = match.group(5) or ""
            numeric_text = integer + fraction
            has_percent = match.group(6) == "%"
            before = line[max(0, match.start() - 24) : match.start()]
            after = line[match.end() : match.end() + 24]
            mention_type, requires_assertion = _classify(
                numeric_text,
                has_percent,
                before,
                after,
            )
            try:
                value = float(numeric_text.replace(",", ""))
                if exponent:
                    value *= 10.0 ** int(exponent)
                elif bare_power:
                    value = value ** int(bare_power)
            except (ValueError, OverflowError):
                continue
            if not math.isfinite(value):
                continue
            # A multiplier times 10^exp is a numeric value.  A *bare negative*
            # power of ten is likewise commonly a reported p-value/error bound.
            # Positive bare powers in equations (for example the 10^9 unit
            # conversion in a GB/s definition) are constants, not measured
            # results, and must not create an uncovered-result obligation.
            if match.group(4) or (
                bare_power and numeric_text == "10" and int(bare_power) < 0
            ):
                mention_type, requires_assertion = "result_claim", True
            mentions.append(
                {
                    "value": value,
                    "unit": "%" if has_percent else "",
                    "type": mention_type,
                    "requires_assertion": requires_assertion,
                    "section": section_at(sections, line_number),
                    "line": line_number,
                }
            )
    return mentions


def figure_references(tex: str) -> list[str]:
    result: list[str] = []
    for match in re.finditer(r"\\(?:ref|autoref|cref|Cref)\{([^}]*)\}", tex):
        label = match.group(1)
        if label not in result:
            result.append(label)
    return result


__all__ = [
    "ANCHOR_RE",
    "build_section_map",
    "claim_span_hash",
    "extract_numeric_mentions",
    "figure_references",
    "find_claim_anchors",
    "normalize_claim_sentence",
    "section_at",
    "sentence_for_anchor",
]
