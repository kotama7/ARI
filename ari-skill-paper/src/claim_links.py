"""Claim-id post-processing for the Research Contract (Story2Proposal Phase A2).

After ``write_paper_iterative`` emits LaTeX with ``% CLAIM:Cx:NCx`` anchors, this
module deterministically reconciles those anchors against the
``science_data.json`` claim registry and produces ``paper_claim_links.json``:

  - ``paper_claim_links`` — anchor-keyed records (claim_id / numeric_id /
    section / span_hash / line_range / figures). The **anchor** is the stable
    key that survives refine/render; ``span_hash`` detects sentence changes;
    ``line_range`` is auxiliary.
  - ``numeric_mentions`` — every numeric token in the paper, classified
    (result_claim / experimental_setting / citation_year / figure_table_ref /
    ambiguous) with section attribution and a ``requires_assertion`` flag.
  - ``figure_refs`` — figure ids (from figures_manifest) actually referenced in
    the paper; figure binding is recorded **here**, the transform-stage
    ``science_data.json`` is never mutated (idempotency / reproducibility).
  - ``unresolved_anchors`` / ``uncovered_numeric_candidates`` — diagnostics the
    hard gate consumes.

Pure functions over strings/dicts — no LLM, no disk, no ari-core dependency, so
this is unit-testable standalone. The hard gate (ari-core) may consume the
``numeric_mentions`` here, but re-derives coverage authoritatively itself.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


ANCHOR_RE = re.compile(r"%\s*CLAIM:(C\w+):(NC\w+)")

# A numeric token: integer/decimal with optional thousands separators and an
# optional immediately-following percent sign. Surrounding unit words are
# inspected separately for classification.
# Mantissa + optional exponent (mirrors ari-core claim_gate/latex.py). Without
# the exponent branch, scientific notation (``4.44\times 10^{-16}``, ``1.2e-6``)
# was read as its bare mantissa and shipped as a false numeric_mismatch.
# NOTE: _strip_for_scan rewrites ``\times`` to `` x `` before scanning, so the
# multiplication sign here is x/× (plus \cdot, which survives the strip);
# requiring the ``10^{...}`` tail keeps speedup notation (``4.18 x``) out.
_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:[eE]([+-]?\d+)(?!\w|\.\d)|\s*(?:x|×|\\times|\\cdot)\s*10\^\{?([+-]?\d+)\}?)?"
    r"\s*(%?)"
)

# LaTeX regions whose digits must never be scanned as result numbers.
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


def normalize_sentence(text: str) -> str:
    """Normalize a claim sentence for hashing: drop LaTeX commands, anchors,
    comments, and collapse whitespace; lowercase."""
    s = ANCHOR_RE.sub("", text)
    s = re.sub(r"%.*", "", s)  # drop trailing comments
    for rgx in _STRIP_REGIONS:
        s = rgx.sub(" ", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", s)  # commands
    s = re.sub(r"[{}$~\\]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def span_hash(text: str) -> str:
    return "sha256-" + hashlib.sha256(normalize_sentence(text).encode("utf-8")).hexdigest()


def _canonical_section(title: str) -> str:
    t = title.strip().lower()
    table = [
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
    ]
    for needle, canon in table:
        if needle in t:
            return canon
    slug = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return slug or "body"


def build_section_map(tex: str) -> list[str]:
    """Return a per-line list of canonical section names (1-indexed via [i-1])."""
    lines = tex.split("\n")
    out: list[str] = []
    current = "preamble"
    appendix_mode = False
    sec_re = re.compile(r"\\(?:sub)*section\*?\s*\{([^}]*)\}")
    for ln in lines:
        stripped = ln.strip()
        if "\\begin{abstract}" in stripped:
            current = "abstract"
            out.append(current)
            continue
        if "\\end{abstract}" in stripped:
            out.append(current)
            current = "body"
            continue
        if re.search(r"\\appendix\b", stripped):
            appendix_mode = True
        m = sec_re.search(stripped)
        if m:
            current = "appendix" if appendix_mode else _canonical_section(m.group(1))
        elif re.search(r"\\bibliography\b|\\begin\{thebibliography\}", stripped):
            current = "references"
        out.append(current)
    return out


def section_at(section_map: list[str], line_no: int) -> str:
    idx = line_no - 1
    if 0 <= idx < len(section_map):
        return section_map[idx]
    return "body"


def find_anchors(tex: str) -> list[dict]:
    """Find every ``% CLAIM:Cx:NCx`` anchor with its (1-indexed) line."""
    anchors: list[dict] = []
    for i, line in enumerate(tex.split("\n"), start=1):
        for m in ANCHOR_RE.finditer(line):
            anchors.append({
                "anchor": f"CLAIM:{m.group(1)}:{m.group(2)}",
                "claim_id": m.group(1),
                "numeric_id": m.group(2),
                "line": i,
            })
    return anchors


def _sentence_for_anchor(lines: list[str], line_no: int) -> tuple[str, list[int]]:
    """Return (sentence_text, [start,end]) for an anchor: the text on its own
    line (minus the comment) if non-empty, else the next non-empty line."""
    idx = line_no - 1
    if 0 <= idx < len(lines):
        raw = lines[idx]
        # A comment line (starts with %) is never the sentence — even with an
        # inline forward declaration after the anchor, its leftover is comment
        # text, not paper prose. Bind to the next content line instead. Only an
        # END-of-line anchor (real text, then `% CLAIM...`) binds to its own line.
        if not raw.lstrip().startswith("%"):
            own = re.sub(r"^%+", "", ANCHOR_RE.sub("", raw)).strip()
            if own:
                return raw, [line_no, line_no]
    for j in range(idx + 1, min(idx + 4, len(lines))):
        if lines[j].strip() and not lines[j].strip().startswith("%"):
            return lines[j], [j + 1, j + 1]
    return (lines[idx] if 0 <= idx < len(lines) else ""), [line_no, line_no]


def _strip_for_scan(line: str) -> str:
    # Drop real LaTeX comments (unescaped %), but keep literal percent \%.
    s = re.sub(r"(?<!\\)%.*$", "", line)
    for rgx in _STRIP_REGIONS:
        s = rgx.sub(" ", s)
    s = s.replace("\\%", "%")  # normalize literal percent for unit detection
    # Normalize LaTeX so unit detection sees the number's real neighbours: math
    # delimiters ($) and non-breaking space (~) and spacing macros would otherwise
    # sit between a number and its unit ("$48$ threads", "$6.04$~GFlop/s",
    # "$4.18\\times$"), defeating the anchored unit regexes and leaving genuine
    # result numbers (and settings) classified as "ambiguous".
    s = re.sub(r"\\times\b", " x ", s)          # speedup notation -> x
    s = re.sub(r"\\[,;:!> ]", " ", s)            # LaTeX thin/medium spaces
    # \( \) are math delimiters exactly like $ — leaving them in place put a
    # ")" between "\(734.8\)" and its "GB/s", defeating unit detection and the
    # anchor binder (which then picked an unrelated number in the sentence).
    s = s.replace("\\(", " ").replace("\\)", " ")
    s = s.replace("~", " ").replace("$", " ")    # nbsp + math delimiters
    return s


def _classify(num_str: str, has_percent: bool, before: str, after: str) -> tuple[str, bool]:
    """Classify a numeric token -> (type, requires_assertion)."""
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return "ambiguous", False
    is_int = "." not in num_str
    # citation year
    if is_int and 1900 <= value <= 2099 and not has_percent and not _PERF_UNIT_RE.match(after):
        if not _SETTING_UNIT_RE.match(after):
            return "citation_year", False
    # figure/table/section/equation reference
    if _REF_WORD_RE.search(before):
        return "figure_table_ref", False
    # experimental setting (10 trials, 48 cores)
    if _SETTING_UNIT_RE.match(after):
        return "experimental_setting", False
    # result claim: percentage or a performance unit follows
    if has_percent or _PERF_UNIT_RE.match(after):
        return "result_claim", True
    return "ambiguous", False


def extract_numeric_mentions(tex: str, section_map: list[str]) -> list[dict]:
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
                # (Mirrors ari-core claim_gate/latex.py.)
                mtype, requires = "result_claim", True
            mentions.append({
                "value": value,
                "unit": "%" if has_pct else "",
                "type": mtype,
                "requires_assertion": requires,
                "section": section_at(section_map, i),
                "line": i,
            })
    return mentions


def _manifest_label_to_id(manifest: Any) -> dict[str, str]:
    """Map LaTeX figure labels (fig:1) -> manifest figure ids (fig_1)."""
    out: dict[str, str] = {}
    if not isinstance(manifest, dict):
        return out
    snippets = manifest.get("latex_snippets") or {}
    if isinstance(snippets, dict):
        for fig_id, snip in snippets.items():
            for lm in re.finditer(r"\\label\{([^}]*)\}", str(snip)):
                out[lm.group(1)] = fig_id
    # also map the manifest ids themselves as a fallback label form
    figs = manifest.get("figures")
    if isinstance(figs, dict):
        for fig_id in figs:
            out.setdefault(str(fig_id), str(fig_id))
    return out


def _figure_refs_in(text: str, label_to_id: dict[str, str]) -> list[str]:
    ids: list[str] = []
    for rm in re.finditer(r"\\(?:ref|autoref|cref|Cref)\{([^}]*)\}", text):
        label = rm.group(1)
        fid = label_to_id.get(label)
        if fid and fid not in ids:
            ids.append(fid)
    return ids


def _index_claims(science_data: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (claims_by_id, numeric_by_id) from science_data."""
    claims_by_id: dict[str, dict] = {}
    numeric_by_id: dict[str, dict] = {}
    for c in (science_data.get("claims") or []):
        if isinstance(c, dict) and c.get("id"):
            claims_by_id[c["id"]] = c
            for na in (c.get("numeric_assertions") or []):
                if isinstance(na, dict) and na.get("id"):
                    numeric_by_id[na["id"]] = na
    for na in (science_data.get("numeric_assertions") or []):
        if isinstance(na, dict) and na.get("id"):
            numeric_by_id.setdefault(na["id"], na)
    return claims_by_id, numeric_by_id


_DECL_RE = re.compile(r"([A-Za-z_]+)=([^\s]+)")
_VALID_ROLES = ("value", "baseline", "proposed")
# Writer-LLM formula synonyms -> registry names. A real run declared 15 anchors
# with ``formula=value`` (meaning an absolute value, i.e. identity); the registry
# lookup then returned no required roles and ALL 15 paper numbers shipped
# unverified (operand_unresolved) -- and the refine loop cannot repair them
# because anchor lines are edit-forbidden. Normalize at parse time so natural
# synonyms verify instead of dead-ending.
_FORMULA_ALIASES = {
    "value": "identity", "absolute": "identity", "raw": "identity",
    "abs": "identity", "direct": "identity", "reported": "identity",
}


def _unescape_latex(s: str) -> str:
    """Undo LaTeX escaping the writer applies inside the comment (it is trained to
    escape these even though comment text needs no escaping): ``\\_`` -> ``_`` etc.
    Without this, metric keys (``banded\\_single\\_GFlops\\_per\\_s``) and formula
    names (``ratio\\_percent``) never match the recorded keys / formula registry."""
    return re.sub(r"\\([_%&#$])", r"\1", s) if s else s


def _parse_writer_assertions(tex: str, config_nodes: dict) -> dict:
    """Parse the writer's INLINE forward declarations on % CLAIM anchor lines,
    e.g. ``% CLAIM:C2:NC2 metric=GFlops/s formula=relative_increase_percent
    baseline=cfg2 proposed=cfg1`` (Story2Proposal (c) — forward declaration).

    Returns ``{numeric_id: assertion}``. Operands resolve config_id -> node_id
    via ``config_nodes`` (science_data._config_nodes); metric_path is the bare
    metric key (the hard gate resolves it against results.json / node metrics).
    This is FORWARD (declared) — no reverse search — so the gate verifies the
    declared derivation deterministically; a wrong declaration → numeric_mismatch.
    """
    out: dict[str, dict] = {}
    config_nodes = config_nodes or {}
    for i, line in enumerate(tex.split("\n"), start=1):
        for m in ANCHOR_RE.finditer(line):
            cid, nid = m.group(1), m.group(2)
            # Writers label the operand tokens (``operands=value=cfg4``) despite
            # being told they are bare k=v; the greedy token regex then swallows
            # the role into the label and the whole assertion ships unverified.
            # Strip the label when it directly prefixes another k=v token.
            tail = re.sub(r"\boperands?=(?=[A-Za-z_]+=)", "", line[m.end():])
            toks = {k: _unescape_latex(v) for k, v in _DECL_RE.findall(tail)}
            metric = toks.get("metric", "")
            formula = toks.get("formula")
            formula = _FORMULA_ALIASES.get(formula, formula)
            if not formula:
                continue  # references a pre-generated assertion; no inline declaration
            operands: dict = {}
            unresolved_refs: list[str] = []
            for role in _VALID_ROLES:
                ref = toks.get(role)
                if not ref:
                    continue
                # ref is `cfgN` (use assertion-level metric=) or `cfgN:metricKey`
                # (per-operand metric override — enables cross-metric ratios such
                # as measured/ceiling attainment on the same config).
                cfg_id, _, metric_override = ref.partition(":")
                cn = config_nodes.get(cfg_id)
                op_metric = metric_override or metric
                if cn and cn.get("node_id") and op_metric:
                    operands[role] = {"node_id": cn["node_id"], "metric_path": op_metric,
                                      "config_id": cfg_id, "environment": cn.get("environment", {})}
                else:
                    unresolved_refs.append(ref)
            if nid in out:
                # Writers sometimes stamp EVERY anchor with the same ID
                # (observed live: 16x "% CLAIM:Cw:NCw ..." — no numbering), and
                # keyed by ID they collapsed into one verified assertion.
                # Disambiguate per line so each declaration is verified
                # independently; link_paper_claims assigns the same synthetic
                # id to the anchor on that line, so the gate's per-id pairing
                # (assertion <-> link <-> sentence mentions) stays coherent.
                nid = f"{nid}@L{i}"
            rec = {"id": nid, "claim_id": cid, "metric": metric, "formula": formula,
                   "operands": operands, "line": i, "source": "writer_declared"}
            if unresolved_refs:
                rec["unresolved_config_refs"] = unresolved_refs
            out[nid] = rec
    return out


def link_paper_claims(tex: str, science_data: dict, figures_manifest: Any = None) -> dict:
    """Build paper_claim_links.json content from a LaTeX paper + science_data."""
    lines = tex.split("\n")
    section_map = build_section_map(tex)
    claims_by_id, numeric_by_id = _index_claims(science_data or {})
    label_to_id = _manifest_label_to_id(figures_manifest)
    config_nodes = (science_data or {}).get("_config_nodes", {})
    writer_assertions = _parse_writer_assertions(tex, config_nodes)

    anchors = find_anchors(tex)
    links: list[dict] = []
    unresolved: list[dict] = []
    seen_anchor_keys: set[str] = set()
    # Declarations are identified by LINE (duplicate-ID writers); reference-only
    # anchors keep the legacy ID-keyed dedup/lookup.
    wa_by_line = {rec.get("line"): rec for rec in writer_assertions.values()}

    for a in anchors:
        key = a["anchor"]
        _wa_line = wa_by_line.get(a["line"])
        dedup_key = f"{key}@L{a['line']}" if _wa_line is not None else key
        if dedup_key in seen_anchor_keys:
            continue
        seen_anchor_keys.add(dedup_key)
        cid, nid = a["claim_id"], a["numeric_id"]
        sentence, line_range = _sentence_for_anchor(lines, a["line"])
        _wa = _wa_line if _wa_line is not None else writer_assertions.get(nid)
        _declared_ok = bool(_wa and _wa.get("operands") and not _wa.get("unresolved_config_refs"))
        # Resolved if it references a pre-generated assertion OR the writer made a
        # valid inline forward declaration (operands resolved to real nodes).
        resolved = (cid in claims_by_id and (nid in numeric_by_id or nid == "NC0")) or _declared_ok
        rec = {
            "claim_id": cid,
            "numeric_id": (_wa_line.get("id") if _wa_line is not None else nid),
            "section": section_at(section_map, line_range[0]),
            "anchor": key,
            "span_hash": span_hash(sentence),
            "line_range": line_range,
            "figures": _figure_refs_in(sentence, label_to_id),
            "resolved": resolved,
        }
        links.append(rec)
        if not resolved:
            unresolved.append({
                "anchor": key, "claim_id": cid, "numeric_id": nid, "line": a["line"],
                "reason": "anchor references an id not present in science_data claims",
            })

    numeric_mentions = extract_numeric_mentions(tex, section_map)
    figure_refs = _figure_refs_in(tex, label_to_id)

    # result_claim mentions on lines without a CLAIM anchor are coverage
    # candidates (informational; the hard gate applies section policy).
    anchored_lines = {a["line"] for a in anchors}
    for a in anchors:
        # also treat the bound sentence line as anchored
        _, lr = _sentence_for_anchor(lines, a["line"])
        anchored_lines.add(lr[0])
    uncovered = [
        m for m in numeric_mentions
        if m["requires_assertion"] and m["line"] not in anchored_lines
    ]

    _writer_assertions = list(writer_assertions.values())
    return {
        "stage": "link_paper_claims",
        "paper_claim_links": links,
        "numeric_mentions": numeric_mentions,
        "writer_assertions": _writer_assertions,
        "figure_refs": figure_refs,
        "unresolved_anchors": unresolved,
        "uncovered_numeric_candidates": uncovered,
        "counts": {
            "anchors": len(links),
            "resolved_anchors": sum(1 for r in links if r["resolved"]),
            "writer_assertions": len(_writer_assertions),
            "numeric_mentions": len(numeric_mentions),
            "result_claim_mentions": sum(1 for m in numeric_mentions if m["type"] == "result_claim"),
            "uncovered_numeric_candidates": len(uncovered),
            "figure_refs": len(figure_refs),
        },
    }
