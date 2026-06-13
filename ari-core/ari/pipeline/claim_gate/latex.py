"""Deterministic LaTeX section + numeric-token parsing for the hard gate
(Story2Proposal Phase B, coverage check).

This mirrors ari-skill-paper/src/claim_links.py so the gate can re-derive
numeric coverage authoritatively even when paper_claim_links is absent
(e.g. the Condition-A baseline with no anchors). When paper_claim_links IS
present the gate prefers its numeric_mentions; this module is the fallback.
"""

from __future__ import annotations

import re


ANCHOR_RE = re.compile(r"%\s*CLAIM:(C\w+):(NC\w+)")

# Mantissa + optional exponent. Without the exponent branch, scientific
# notation (``4.44\times 10^{-16}``, ``1.2e-6``) was read as its bare mantissa
# (and the 10/16 matched as separate junk mentions), so every such paper value
# failed recompute as a false numeric_mismatch. NOTE: _strip_for_scan rewrites
# ``\times`` to `` x `` before scanning, so the multiplication sign here is
# x/× (plus \cdot, which survives the strip); requiring the ``10^{...}`` tail
# keeps plain speedup notation (``4.18 x``) out of this branch.
_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:[eE]([+-]?\d+)(?!\w|\.\d)|\s*(?:x|×|\\times|\\cdot)\s*10\^\{?([+-]?\d+)\}?)?"
    r"\s*(%?)"
)

_STRIP_REGIONS = [
    re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref)\{[^}]*\}"),
    re.compile(r"\\label\{[^}]*\}"),
    re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\\(?:input|include)\{[^}]*\}"),
]

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


def _canonical_section(title: str) -> str:
    t = title.strip().lower()
    table = [
        ("introduction", "introduction"), ("related", "related_work"),
        ("background", "related_work"), ("prior work", "related_work"),
        ("method", "methodology"), ("approach", "methodology"),
        ("design", "methodology"), ("implementation", "methodology"),
        ("experiment", "experiments"), ("evaluation", "experiments"),
        ("setup", "experiments"), ("result", "results"),
        ("discussion", "discussion"), ("limitation", "limitations"),
        ("conclusion", "conclusion"), ("summary", "conclusion"),
        ("future work", "conclusion"), ("reference", "references"),
        ("bibliograph", "references"), ("acknowled", "acknowledgements"),
        ("abstract", "abstract"), ("appendix", "appendix"),
    ]
    for needle, canon in table:
        if needle in t:
            return canon
    slug = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return slug or "body"


def build_section_map(tex: str) -> list[str]:
    lines = tex.split("\n")
    out: list[str] = []
    current = "preamble"
    appendix_mode = False
    sec_re = re.compile(r"\\(?:sub)*section\*?\s*\{([^}]*)\}")
    for ln in lines:
        s = ln.strip()
        if "\\begin{abstract}" in s:
            current = "abstract"
            out.append(current)
            continue
        if "\\end{abstract}" in s:
            out.append(current)
            current = "body"
            continue
        if re.search(r"\\appendix\b", s):
            appendix_mode = True
        m = sec_re.search(s)
        if m:
            current = "appendix" if appendix_mode else _canonical_section(m.group(1))
        elif re.search(r"\\bibliography\b|\\begin\{thebibliography\}", s):
            current = "references"
        out.append(current)
    return out


def section_at(section_map: list[str], line_no: int) -> str:
    idx = line_no - 1
    return section_map[idx] if 0 <= idx < len(section_map) else "body"


def _strip_for_scan(line: str) -> str:
    s = re.sub(r"(?<!\\)%.*$", "", line)
    for rgx in _STRIP_REGIONS:
        s = rgx.sub(" ", s)
    s = s.replace("\\%", "%")
    # Normalize LaTeX so unit detection sees a number's real neighbours (mirrors
    # ari-skill-paper/src/claim_links.py): "$48$ threads", "$6.04$~GFlop/s",
    # "$4.18\\times$" would otherwise leave settings/results as "ambiguous".
    s = re.sub(r"\\times\b", " x ", s)
    s = re.sub(r"\\[,;:!> ]", " ", s)
    # \( \) are math delimiters exactly like $ — leaving them in place put a
    # ")" between "\(734.8\)" and its "GB/s", defeating unit detection and the
    # anchor binder (which then picked an unrelated number in the sentence).
    s = s.replace("\\(", " ").replace("\\)", " ")
    return s.replace("~", " ").replace("$", " ")


def _classify(num_str: str, has_percent: bool, before: str, after: str) -> tuple[str, bool]:
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return "ambiguous", False
    is_int = "." not in num_str
    if is_int and 1900 <= value <= 2099 and not has_percent and not _PERF_UNIT_RE.match(after):
        if not _SETTING_UNIT_RE.match(after):
            return "citation_year", False
    if _REF_WORD_RE.search(before):
        return "figure_table_ref", False
    if _SETTING_UNIT_RE.match(after):
        return "experimental_setting", False
    if has_percent or _PERF_UNIT_RE.match(after):
        return "result_claim", True
    return "ambiguous", False


def find_anchors(tex: str) -> list[dict]:
    anchors: list[dict] = []
    for i, line in enumerate(tex.split("\n"), start=1):
        for m in ANCHOR_RE.finditer(line):
            anchors.append({
                "anchor": f"CLAIM:{m.group(1)}:{m.group(2)}",
                "claim_id": m.group(1), "numeric_id": m.group(2), "line": i,
            })
    return anchors


def extract_numeric_mentions(tex: str, section_map: "list[str] | None" = None) -> list[dict]:
    if section_map is None:
        section_map = build_section_map(tex)
    mentions: list[dict] = []
    for i, raw in enumerate(tex.split("\n"), start=1):
        line = _strip_for_scan(raw)
        for m in _NUMBER_RE.finditer(line):
            int_part, frac = m.group(1), m.group(2) or ""
            exp = m.group(3) or m.group(4) or ""
            pct = m.group(5) or ""
            num_str = int_part + frac
            has_pct = pct == "%"
            before = line[max(0, m.start() - 24):m.start()]
            after = line[m.end():m.end() + 24]
            mtype, requires = _classify(num_str, has_pct, before, after)
            try:
                value = float(num_str.replace(",", ""))
                if exp:
                    value *= 10.0 ** int(exp)
            except (ValueError, OverflowError):
                continue
            if value in (float("inf"), float("-inf")):
                # 10^{4932}-style constants: a non-finite mention would poison
                # the JSON report and (pre-guard) an uncaught OverflowError made
                # the whole gate fail OPEN via the callers' defensive catches.
                continue
            if m.group(4):
                # \times/\cdot 10^{exp} literals classified as result_claim
                # before this branch existed too (the stripped " x " matched the
                # speedup unit) — keep that, or the anchor binder starts picking
                # some other number in the sentence. e-notation keeps _classify's
                # verdict so settings ("1e4 iterations") stay settings.
                mtype, requires = "result_claim", True
            mentions.append({
                "value": value, "unit": "%" if has_pct else "",
                "type": mtype, "requires_assertion": requires,
                "section": section_at(section_map, i), "line": i,
            })
    return mentions


def figure_refs(tex: str) -> list[str]:
    """Figure/table labels referenced via \\ref-family commands."""
    out: list[str] = []
    for m in re.finditer(r"\\(?:ref|autoref|cref|Cref)\{([^}]*)\}", tex):
        lab = m.group(1)
        if lab not in out:
            out.append(lab)
    return out
