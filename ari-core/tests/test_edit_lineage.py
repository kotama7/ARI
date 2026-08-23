"""Tests for the rewrite-vs-refine measure (edit_lineage.py).

This is the instrument behind the paper's central claim. It must (a) tokenize C
without being fooled by comment-like text inside literals, (b) actually SEPARATE a
refine from a rewrite — a measure that returns the same number for both measures
nothing — and (c) pair each child with its parent from a checkpoint on disk.

The study-specific scripts live under ``workspace/`` (gitignored, self-contained
with the harnesses), with a legacy ``scripts/`` fallback; skip if neither exists.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_EL = next((p for p in (_ROOT / "workspace" / "edit_lineage.py",
                        _ROOT / "scripts" / "edit_lineage.py") if p.is_file()), None)
if _EL is None:
    pytest.skip("edit_lineage.py not found (workspace/ or scripts/)", allow_module_level=True)
_SPEC = importlib.util.spec_from_file_location("edit_lineage", _EL)
el = importlib.util.module_from_spec(_SPEC)
# Register before exec: the module defines a dataclass with a ``str | None`` field,
# and dataclasses resolves annotations via ``sys.modules[cls.__module__]``.
sys.modules["edit_lineage"] = el
_SPEC.loader.exec_module(el)


PARENT = """
// naive baseline
void gemm(int n,int p,int m,const double*A,const double*B,double*C){
  for(int i=0;i<n;i++) for(int j=0;j<m;j++){
    double s=0.0;
    for(int k=0;k<p;k++) s+=A[i*p+k]*B[k*m+j];
    C[i*m+j]=s;
  }
}"""

REFINE = PARENT.replace("for(int i=0;i<n;i++)",
                        "#pragma omp parallel for\n  for(int i=0;i<n;i++)")

REWRITE = """
void gemm(int N,int P,int M,const double*a,const double*b,double*o){
  for(int r=0;r<N*M;r++) o[r]=0.0;
  for(int x=0;x<N;x++) for(int z=0;z<P;z++){
    double v=a[x*P+z];
    for(int y=0;y<M;y++) o[x*M+y]+=v*b[z*M+y];
  }
}"""


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------

def test_line_comment_is_stripped():
    assert el.tokenize_c("int x=1; // int y=2\n") == ["int", "x", "=", "1", ";"]


def test_block_comment_is_stripped_across_lines():
    assert el.tokenize_c("a /* b\n c */ d") == ["a", "d"]


def test_comment_markers_inside_a_string_are_not_comments():
    assert el.tokenize_c('char*s="http://x/*y*/";') == \
        ["char", "*", "s", "=", "STR", ";"]


def test_slash_char_literal_is_not_a_comment():
    assert el.tokenize_c("char c='/'; int y=1;") == \
        ["char", "c", "=", "CHR", ";", "int", "y", "=", "1", ";"]


def test_multichar_operators_are_single_tokens():
    assert el.tokenize_c("a>>=b; c->d; e++;") == \
        ["a", ">>=", "b", ";", "c", "->", "d", ";", "e", "++", ";"]


# --------------------------------------------------------------------------
# The measure must SEPARATE rewrite from refine
# --------------------------------------------------------------------------

def test_identical_code_is_one():
    assert el.text_similarity(PARENT, PARENT) == 1.0


def test_reformat_only_is_one():
    """Whitespace + comment changes are not a rewrite."""
    reformat = PARENT.replace("  ", " ").replace("// naive baseline", "/* base */")
    assert el.text_similarity(PARENT, reformat) == 1.0


def test_refine_scores_high():
    assert el.text_similarity(PARENT, REFINE) > 0.85


def test_rewrite_scores_low():
    assert el.text_similarity(PARENT, REWRITE) < 0.6


def test_refine_and_rewrite_are_actually_separated():
    """The whole point: the two edit styles land on opposite sides of the cut."""
    refine = el.text_similarity(PARENT, REFINE)
    rewrite = el.text_similarity(PARENT, REWRITE)
    assert refine - rewrite > 0.3
    assert rewrite < el.DEFAULT_THRESHOLD < refine


def test_similarity_is_symmetric():
    assert el.text_similarity(PARENT, REWRITE) == el.text_similarity(REWRITE, PARENT)


def test_empty_vs_empty_is_one():
    assert el.text_similarity("", "") == 1.0


# --------------------------------------------------------------------------
# Checkpoint walk
# --------------------------------------------------------------------------

def _node(ckpt: Path, nid: str, parent_id, code: str, score: float, *,
          fname="candidate_gemm.c", depth=0):
    d = ckpt / nid
    d.mkdir(parents=True)
    (d / fname).write_text(code)
    (d / "node_report.json").write_text(json.dumps({
        "node_id": nid, "parent_id": parent_id, "depth": depth,
        "metrics": {"_scientific_score": score},
        "has_real_data": score > 0,
    }))


def test_classify_pairs_children_with_parents(tmp_path):
    ck = tmp_path / "run"
    _node(ck, "node_root", None, PARENT, 0.5, depth=0)
    _node(ck, "node_ref", "node_root", REFINE, 0.6, depth=1)
    _node(ck, "node_rw", "node_root", REWRITE, 0.0, depth=1)
    edits = el.classify_checkpoint(ck)
    assert {e.child_id for e in edits} == {"node_ref", "node_rw"}   # root excluded
    by = {e.child_id: e for e in edits}
    assert by["node_ref"].sim_text > by["node_rw"].sim_text
    assert by["node_ref"].parent_id == "node_root"


def test_root_and_orphan_children_are_skipped(tmp_path):
    ck = tmp_path / "run"
    _node(ck, "node_root", None, PARENT, 0.5)
    _node(ck, "node_orphan", "node_missing", REWRITE, 0.0, depth=1)  # parent absent
    assert el.classify_checkpoint(ck) == []


def test_validity_split(tmp_path):
    ck = tmp_path / "run"
    _node(ck, "node_root", None, PARENT, 0.5)
    _node(ck, "node_ok", "node_root", REFINE, 0.7, depth=1)
    _node(ck, "node_bad", "node_root", REWRITE, 0.0, depth=1)
    s = el.summarize(el.classify_checkpoint(ck), threshold=0.5)
    assert s["valid_children"]["n"] == 1
    assert s["invalid_children"]["n"] == 1


def test_summary_reports_threshold_free_median_and_a_sweep(tmp_path):
    ck = tmp_path / "run"
    _node(ck, "node_root", None, PARENT, 0.5)
    _node(ck, "node_ref", "node_root", REFINE, 0.6, depth=1)
    _node(ck, "node_rw", "node_root", REWRITE, 0.0, depth=1)
    s = el.summarize(el.classify_checkpoint(ck), threshold=0.5)["all_children"]
    assert "median_sim_text" in s          # threshold-free headline
    assert set(s["rewrite_rate_sweep"]) == {"0.3", "0.5", "0.7"}


def test_mismatched_candidate_filenames_are_not_paired(tmp_path):
    """A parent and child on different tasks (different candidate_*.c) are not a
    lineage pair — guards against cross-task nonsense."""
    ck = tmp_path / "run"
    _node(ck, "node_root", None, PARENT, 0.5, fname="candidate_gemm.c")
    _node(ck, "node_c", "node_root", REWRITE, 0.0, fname="candidate_spmm.c", depth=1)
    assert el.classify_checkpoint(ck) == []


# --------------------------------------------------------------------------
# Structural check (only when tree-sitter is installed)
# --------------------------------------------------------------------------

def test_structural_is_optional_and_reports_absence():
    """Absent tree-sitter must degrade to a clear note, never a crash."""
    parser, ver = el._tree_sitter_c()
    if parser is None:
        assert "not available" in ver or "failed" in ver


def test_structural_runs_when_available():
    parser, ver = el._tree_sitter_c()
    if parser is None:
        pytest.skip("tree-sitter not installed")
    assert "tree_sitter=" in ver
    assert el.structural_similarity(parser, PARENT, PARENT) == 1.0
    # Orthogonal, weaker discriminator for this axis — but still ordered.
    assert (el.structural_similarity(parser, PARENT, REFINE)
            >= el.structural_similarity(parser, PARENT, REWRITE))
