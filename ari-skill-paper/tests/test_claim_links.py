"""Tests for claim-id post-processing (Story2Proposal Phase A2).

Pure unit tests over LaTeX strings + science_data dicts. No LLM, no disk.
"""
from __future__ import annotations

from src.claim_links import (
    build_section_map,
    section_at,
    find_anchors,
    extract_numeric_mentions,
    link_paper_claims,
    normalize_sentence,
    span_hash,
)


SCIENCE_DATA = {
    "claims": [
        {
            "id": "C1", "text": "absolute", "section": "results", "status": "draft",
            "numeric_assertions": [{"id": "NC1", "metric": "GFlops", "value": 150.0, "formula": "identity"}],
        },
        {
            "id": "C2", "text": "comparison", "section": "results", "status": "draft",
            "numeric_assertions": [{"id": "NC2", "metric": "GFlops", "value": 50.0, "formula": "relative_increase_percent"}],
        },
    ],
}

FIG_MANIFEST = {
    "figures": {"fig_1": "/x/fig_1.pdf"},
    "latex_snippets": {"fig_1": "\\begin{figure}\\includegraphics{fig_1.pdf}\\caption{c}\\label{fig:1}\\end{figure}"},
}


def test_section_map_abstract_and_sections():
    tex = (
        "\\begin{abstract}\n"
        "We achieve a lot.\n"
        "\\end{abstract}\n"
        "\\section{Introduction}\n"
        "Intro text.\n"
        "\\section{Results}\n"
        "Result text.\n"
    )
    smap = build_section_map(tex)
    assert section_at(smap, 2) == "abstract"
    assert section_at(smap, 5) == "introduction"
    assert section_at(smap, 7) == "results"


def test_appendix_sections_canonicalize_to_appendix():
    tex = "\\section{Results}\nA\n\\appendix\n\\section{Extra Proofs}\nB\n"
    smap = build_section_map(tex)
    assert section_at(smap, 2) == "results"
    assert section_at(smap, 5) == "appendix"


def test_find_anchors():
    tex = "x\n% CLAIM:C1:NC1\nThe result is 150 GFlops.\n"
    anchors = find_anchors(tex)
    assert len(anchors) == 1
    assert anchors[0]["claim_id"] == "C1"
    assert anchors[0]["numeric_id"] == "NC1"
    assert anchors[0]["line"] == 2


def test_numeric_classification_result_claim_percent():
    tex = "\\section{Results}\nWe improve throughput by 50\\%.\n"
    smap = build_section_map(tex)
    mentions = extract_numeric_mentions(tex, smap)
    m = [x for x in mentions if x["value"] == 50.0][0]
    assert m["type"] == "result_claim"
    assert m["requires_assertion"] is True
    assert m["section"] == "results"


def test_numeric_classification_citation_year_and_setting():
    tex = "\\section{Results}\nWe ran 10 trials in 2024.\n"
    smap = build_section_map(tex)
    mentions = extract_numeric_mentions(tex, smap)
    by_val = {m["value"]: m for m in mentions}
    assert by_val[10.0]["type"] == "experimental_setting"
    assert by_val[10.0]["requires_assertion"] is False
    assert by_val[2024.0]["type"] == "citation_year"
    assert by_val[2024.0]["requires_assertion"] is False


def test_cite_and_ref_digits_are_not_scanned():
    tex = "\\section{Results}\nAs shown~\\cite{smith2024} in Figure~\\ref{fig:1}.\n"
    smap = build_section_map(tex)
    mentions = extract_numeric_mentions(tex, smap)
    # The 2024 inside \cite{} and the 1 inside \ref{} must be stripped.
    assert mentions == []


def test_perf_unit_gflops_is_result_claim():
    tex = "\\section{Results}\nThe kernel sustains 150 GFlop/s.\n"
    smap = build_section_map(tex)
    mentions = extract_numeric_mentions(tex, smap)
    m = [x for x in mentions if x["value"] == 150.0][0]
    assert m["type"] == "result_claim"


def test_link_resolves_anchors_against_science_data():
    tex = (
        "\\section{Results}\n"
        "% CLAIM:C1:NC1\n"
        "The kernel sustains 150 GFlop/s.\n"
        "% CLAIM:C2:NC2\n"
        "This improves throughput by 50\\% over the baseline.\n"
    )
    out = link_paper_claims(tex, SCIENCE_DATA, FIG_MANIFEST)
    links = {l["anchor"]: l for l in out["paper_claim_links"]}
    assert "CLAIM:C1:NC1" in links
    assert links["CLAIM:C1:NC1"]["resolved"] is True
    assert links["CLAIM:C2:NC2"]["resolved"] is True
    assert links["CLAIM:C1:NC1"]["section"] == "results"
    assert out["unresolved_anchors"] == []
    assert out["counts"]["resolved_anchors"] == 2


def test_link_flags_unresolved_anchor():
    tex = "\\section{Results}\n% CLAIM:C9:NC9\nGhost claim of 99\\%.\n"
    out = link_paper_claims(tex, SCIENCE_DATA, FIG_MANIFEST)
    assert len(out["unresolved_anchors"]) == 1
    assert out["unresolved_anchors"][0]["claim_id"] == "C9"


def test_uncovered_numeric_candidate_detected():
    # A result_claim number in results with NO anchor -> coverage candidate.
    tex = "\\section{Results}\nUnregistered speedup of 31\\% appears here.\n"
    out = link_paper_claims(tex, SCIENCE_DATA, FIG_MANIFEST)
    vals = [c["value"] for c in out["uncovered_numeric_candidates"]]
    assert 31.0 in vals


def test_figure_late_bind_records_manifest_id():
    tex = (
        "\\section{Results}\n"
        "% CLAIM:C1:NC1\n"
        "Figure~\\ref{fig:1} shows the kernel sustains 150 GFlop/s.\n"
    )
    out = link_paper_claims(tex, SCIENCE_DATA, FIG_MANIFEST)
    link = [l for l in out["paper_claim_links"] if l["anchor"] == "CLAIM:C1:NC1"][0]
    assert "fig_1" in link["figures"]
    assert "fig_1" in out["figure_refs"]


def test_span_hash_stable_under_whitespace_and_anchor():
    a = "% CLAIM:C1:NC1\nThe   kernel sustains 150 GFlop/s.\n"
    b = "The kernel sustains 150 GFlop/s."
    assert span_hash(a.split("\n")[1]) == span_hash(b)


def test_writer_assertion_inline_declaration_parsed():
    """Story2Proposal (c): inline forward declaration on the anchor line is parsed
    into a verifiable assertion; config_id resolves to node_id."""
    sd = {"_config_nodes": {
        "cfg1": {"node_id": "nA", "environment": {}, "metrics": ["GFlops/s"]},
        "cfg2": {"node_id": "nB", "environment": {}, "metrics": ["GFlops/s"]},
    }}
    tex = ("\\section{Results}\n"
           "% CLAIM:C7:NC7 metric=GFlops/s formula=relative_increase_percent baseline=cfg2 proposed=cfg1\n"
           "We improve throughput by 50\\%.\n")
    out = link_paper_claims(tex, sd, None)
    wa = {a["id"]: a for a in out["writer_assertions"]}
    assert "NC7" in wa
    assert wa["NC7"]["formula"] == "relative_increase_percent"
    assert wa["NC7"]["operands"]["baseline"]["node_id"] == "nB"
    assert wa["NC7"]["operands"]["proposed"]["node_id"] == "nA"
    # anchor counts as resolved via the writer declaration (not in science_data)
    link = [l for l in out["paper_claim_links"] if l["anchor"] == "CLAIM:C7:NC7"][0]
    assert link["resolved"] is True
    assert out["counts"]["writer_assertions"] == 1


def test_writer_assertion_cross_metric_override():
    """cfgN:metric form supports a ratio of two metrics of one config (attainment)."""
    sd = {"_config_nodes": {"cfg1": {"node_id": "nA", "environment": {}, "metrics": ["GFlops/s", "ceil"]}}}
    tex = ("\\section{Results}\n"
           "% CLAIM:C8:NC8 formula=ratio_percent baseline=cfg1:ceil proposed=cfg1:GFlops/s\n"
           "Attainment is 72\\%.\n")
    out = link_paper_claims(tex, sd, None)
    wa = {a["id"]: a for a in out["writer_assertions"]}["NC8"]
    assert wa["operands"]["baseline"]["metric_path"] == "ceil"
    assert wa["operands"]["proposed"]["metric_path"] == "GFlops/s"
    assert wa["operands"]["proposed"]["node_id"] == "nA"


def test_classify_latex_math_wrapped_units():
    """Numbers wrapped in $...$ / ~ / \\times must still be classified by their unit
    so settings (48 threads) and results (6.04 GFlop/s, 4.18x) are not 'ambiguous'."""
    tex = ("\\section{Results}\n"
           "At $48$ threads this rises to $6.04$~GFlop/s.\n"
           "At $K=128$ the build is $4.18\\times$ slower.\n")
    smap = build_section_map(tex)
    by = {m["value"]: m for m in extract_numeric_mentions(tex, smap)}
    assert by[48.0]["type"] == "experimental_setting"      # 48 threads
    assert by[6.04]["type"] == "result_claim"              # 6.04 GFlop/s
    assert by[4.18]["type"] == "result_claim"              # 4.18x speedup
    assert by[128.0]["type"] != "result_claim"             # K=128 is not a result


def test_writer_assertion_unescapes_latex_underscores():
    """The LLM writes LaTeX-escaped underscores in the comment (metric=banded\\_single,
    formula=ratio\\_percent); the parser must unescape so they resolve/match."""
    sd = {"_config_nodes": {"cfg1": {"node_id": "nA", "environment": {},
                                     "metrics": ["banded_single_GFlops_per_s", "banded_strat_peak_GFlops_per_s"]}}}
    tex = ("\\section{Results}\n"
           "% CLAIM:C8:NC8 formula=ratio\\_percent baseline=cfg1:banded\\_strat\\_peak\\_GFlops\\_per\\_s "
           "proposed=cfg1:banded\\_single\\_GFlops\\_per\\_s\n"
           "Attainment is 3.6\\%.\n")
    out = link_paper_claims(tex, sd, None)
    wa = {a["id"]: a for a in out["writer_assertions"]}["NC8"]
    assert wa["formula"] == "ratio_percent"  # unescaped -> matches registry
    assert wa["operands"]["baseline"]["metric_path"] == "banded_strat_peak_GFlops_per_s"
    assert wa["operands"]["proposed"]["metric_path"] == "banded_single_GFlops_per_s"
    assert not wa.get("unresolved_config_refs")


def test_writer_assertion_unresolved_config_ref():
    """A declaration referencing an unknown config is not silently accepted."""
    sd = {"_config_nodes": {"cfg1": {"node_id": "nA", "environment": {}, "metrics": ["x"]}}}
    tex = "\\section{Results}\n% CLAIM:C9:NC9 metric=x formula=identity value=cfg9\nVal 5.\n"
    out = link_paper_claims(tex, sd, None)
    wa = {a["id"]: a for a in out["writer_assertions"]}["NC9"]
    assert wa.get("unresolved_config_refs") == ["cfg9"]
    link = [l for l in out["paper_claim_links"] if l["anchor"] == "CLAIM:C9:NC9"][0]
    assert link["resolved"] is False  # unresolved operand => not resolved


def test_normalize_drops_latex_commands():
    assert normalize_sentence("\\textbf{The} kernel~\\cite{x} runs.") == "the kernel runs."


def test_writer_formula_synonyms_normalize_to_identity():
    # regression (real run): 15 anchors declared `formula=value` (meaning identity);
    # the registry lookup returned no roles and all 15 paper numbers shipped
    # UNVERIFIED (operand_unresolved) — unrepairable downstream because anchor
    # lines are edit-forbidden in refine. Synonyms must normalize at parse time.
    from src.claim_links import _parse_writer_assertions
    tex = ("% CLAIM:C7:NC7 metric=achieved\\_gflops formula=value operands:value=cfg1\n"
           "Some sentence. % CLAIM:C7:NC7\n")
    cfg = {"cfg1": {"node_id": "node_x", "environment": {}}}
    out = _parse_writer_assertions(tex, cfg)
    rec = out["NC7"]
    assert rec["formula"] == "identity"                      # synonym normalized
    assert rec["operands"]["value"]["node_id"] == "node_x"   # operand resolved
    assert rec["operands"]["value"]["metric_path"] == "achieved_gflops"


def test_writer_operands_label_prefix_stripped():
    # a real run declared all 15 anchors as `formula=value operands=value=cfgN`;
    # the labelled token swallowed the role and every number shipped unverified.
    from src.claim_links import _parse_writer_assertions
    cfg = {"cfg4": {"node_id": "node_x", "environment": {}}}
    tex = ("Text.\n"
           "% CLAIM:Cw1:NCw1 metric=spmm\\_max\\_abs\\_error\\_vs\\_reference\\_fp32 "
           "formula=value operands=value=cfg4\n")
    out = _parse_writer_assertions(tex, cfg)
    a = out["NCw1"]
    assert a["formula"] == "identity"                      # alias still applied
    assert a["operands"]["value"]["config_id"] == "cfg4"   # label stripped, role parsed
    assert a["operands"]["value"]["metric_path"] == "spmm_max_abs_error_vs_reference_fp32"


def test_writer_bare_operands_unchanged():
    from src.claim_links import _parse_writer_assertions
    cfg = {"cfg1": {"node_id": "n1", "environment": {}},
           "cfg2": {"node_id": "n2", "environment": {}}}
    tex = "% CLAIM:C2:NC2 metric=GFlops formula=relative_increase_percent baseline=cfg2 proposed=cfg1\n"
    out = _parse_writer_assertions(tex, cfg)
    a = out["NC2"]
    assert set(a["operands"]) == {"baseline", "proposed"}


# --- scientific-notation extraction (false numeric_mismatch fix) ---

def test_mentions_latex_scientific_notation():
    from src.claim_links import extract_numeric_mentions, build_section_map
    tex = r"The FP64 maximum absolute error is \(4.440892098500626\times 10^{-16}\)."
    ms = extract_numeric_mentions(tex, build_section_map(tex))
    sci = [m for m in ms if m["value"] < 1e-10]
    assert len(sci) == 1
    assert abs(sci[0]["value"] - 4.440892098500626e-16) < 1e-22
    # the exponent must be consumed, not split into junk 10 / 16 mentions
    assert sorted(m["value"] for m in ms) == [sci[0]["value"]]
    # a sci-notation literal is a reported quantity -> binder must prefer it
    assert sci[0]["type"] == "result_claim"


def test_mentions_e_notation_and_cdot():
    from src.claim_links import extract_numeric_mentions, build_section_map
    tex = "tolerance 1.2e-6 and \\(3.5\\cdot 10^{4}\\) ops"
    vals = sorted(m["value"] for m in extract_numeric_mentions(tex, build_section_map(tex)))
    assert any(abs(v - 1.2e-6) < 1e-12 for v in vals)
    assert any(abs(v - 3.5e4) < 1e-6 for v in vals)


def test_mentions_speedup_x_not_exponent():
    from src.claim_links import extract_numeric_mentions, build_section_map
    tex = r"We observe a \(4.18\times\) speedup over 10 runs."
    ms = extract_numeric_mentions(tex, build_section_map(tex))
    vals = sorted(m["value"] for m in ms)
    assert vals == [4.18, 10.0]      # 4.18 stays 4.18; "10" is a separate token


def test_mentions_huge_exponent_no_crash_no_nonfinite():
    # quad-precision max etc.: must neither raise OverflowError (which made the
    # whole gate fail OPEN upstream) nor emit non-finite JSON-poisoning values.
    from src.claim_links import extract_numeric_mentions, build_section_map
    tex = r"quad-precision max is \(1.19\times 10^{4932}\), and 1e999 too; speed 95.2"
    ms = extract_numeric_mentions(tex, build_section_map(tex))
    assert all(m["value"] == m["value"] and abs(m["value"]) != float("inf") for m in ms)
    assert any(abs(m["value"] - 95.2) < 1e-9 for m in ms)   # rest of line still scanned


def test_mentions_sentence_final_e_notation():
    from src.claim_links import extract_numeric_mentions, build_section_map
    ms = extract_numeric_mentions("the error is 4.4e-16.", build_section_map(""))
    assert any(abs(m["value"] - 4.4e-16) < 1e-22 for m in ms)


def test_mentions_e_notation_setting_stays_setting():
    # e-notation must NOT be force-classified result_claim: settings keep their
    # _classify verdict, so they never outrank the true claimed value in the
    # anchor binder nor demand assertion coverage.
    from src.claim_links import extract_numeric_mentions, build_section_map
    ms = extract_numeric_mentions("we train for 1e4 iterations", build_section_map(""))
    m = next(m for m in ms if m["value"] == 1e4)
    assert m["type"] == "experimental_setting"


def test_mentions_paren_math_unit_detected():
    # \(734.8\) GB/s: the \) used to sit between number and unit, defeating
    # unit detection — the binder then picked an unrelated number (e.g. a CPU
    # model number) in the same sentence.
    from src.claim_links import extract_numeric_mentions, build_section_map
    ms = extract_numeric_mentions(r"bandwidth is \(734.803418\) GB/s here",
                                  build_section_map(""))
    m = next(m for m in ms if abs(m["value"] - 734.803418) < 1e-6)
    assert m["type"] == "result_claim"


# --- duplicate-ID anchors (writer stamped every line with the same ID) ---

def _dup_id_tex():
    return ("\\section{Results}\n"
            "Throughput is 100 GFLOP/s.\n"
            "% CLAIM:Cw:NCw metric=tput_a formula=value <operands> value=cfg1\n"
            "Bandwidth is 200 GB/s.\n"
            "% CLAIM:Cw:NCw metric=tput_b formula=value value=cfg2\n"
            "Latency is 3 ms.\n"
            "% CLAIM:Cw:NCw metric=lat_c formula=value value=cfg1\n")


def _dup_id_sd():
    return {"_config_nodes": {"cfg1": {"node_id": "n1", "environment": {}},
                              "cfg2": {"node_id": "n2", "environment": {}}}}


def test_duplicate_anchor_ids_yield_independent_assertions():
    from src.claim_links import _parse_writer_assertions
    out = _parse_writer_assertions(_dup_id_tex(), _dup_id_sd()["_config_nodes"])
    assert len(out) == 3                      # was 1 (last-wins collapse)
    metrics = sorted(a["metric"] for a in out.values())
    assert metrics == ["lat_c", "tput_a", "tput_b"]
    assert all(a["operands"].get("value") for a in out.values())
    # the literal <operands> placeholder copied from the template is harmless
    ids = sorted(out.keys())
    assert ids[0] == "NCw" and all(i.startswith("NCw@L") for i in ids[1:])


def test_duplicate_anchor_ids_yield_per_line_links():
    from src.claim_links import link_paper_claims
    pcl = link_paper_claims(_dup_id_tex(), _dup_id_sd(), None)
    links = pcl["paper_claim_links"]
    assert len(links) == 3                    # was 1 (anchor-string dedup)
    assert all(l["resolved"] for l in links)
    # link numeric_id matches the assertion id per line (gate pairing intact)
    a_ids = {a["id"] for a in pcl["writer_assertions"]}
    assert {l["numeric_id"] for l in links} == a_ids
    assert pcl["counts"]["writer_assertions"] == 3


def test_reference_only_repeated_anchor_still_dedups():
    from src.claim_links import link_paper_claims
    tex = ("A result. % CLAIM:C1:NC1\n"
           "Restated later. % CLAIM:C1:NC1\n")
    sd = {"claims": [{"id": "C1", "numeric_assertions": [{"id": "NC1"}]}]}
    pcl = link_paper_claims(tex, sd, None)
    assert len(pcl["paper_claim_links"]) == 1  # legacy dedup preserved
