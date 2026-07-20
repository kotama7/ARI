#!/usr/bin/env python3
"""Measure whether a BFTS child REWROTE or REFINED its inherited candidate.

This is the instrument behind the paper's central claim ("full log shifts children
from rewrite to refine"). It runs POST-HOC over a checkpoint's persisted node
work_dirs — no instrumentation of the run, no LLM, deterministic — so a result is
re-checkable from ``workspace + repo`` alone.

Why textual, not behavioural "semantic" diff
--------------------------------------------
Rewrite-vs-refine is a LINEAGE question: did the child's code descend from the
parent's bytes by editing, or was it regenerated? A refine starts from the parent
file and mutates it, so it shares long verbatim token spans; a rewrite shares only
incidental short ones. Textual token similarity captures exactly that.

A *behavioural* semantic diff would be the wrong tool here and is null by
construction: the validity gate scores a candidate against an fp64 reference, so
every VALID candidate computes the same function — semantic equivalence is held
constant and cannot separate the two edit styles. An LLM "semantic" comparator
would reintroduce the non-determinism and the judge the deterministic evaluator
exists to remove, and break re-checkability. So the primary measure is textual and
stdlib-only; a structural (tree-sitter AST) measure is offered as an orthogonal
robustness check (\S limit ii), reported when tree-sitter is installed and pinned.

Primary similarity (stdlib):
  strip comments -> tokenize (C) -> difflib SequenceMatcher.ratio on the token
  sequences of parent-final vs child-final candidate. In [0,1]; high = refine.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

# A rewrite is a LOW-similarity child. The cut is threshold-dependent, so the
# headline number is the threshold-free MEDIAN similarity; the rate is reported at
# several cuts so the threshold is never a hidden knob.
DEFAULT_THRESHOLD = float(os.environ.get("ARI_REWRITE_SIM_THRESHOLD", "0.5"))
_SWEEP = (0.3, 0.5, 0.7)


# ---------------------------------------------------------------------------
# C tokenizer + comment stripping (one scanner; string/char aware)
# ---------------------------------------------------------------------------

_MULTI_OPS = (
    ">>=", "<<=", "...", "->", "++", "--", "<<", ">>", "<=", ">=", "==", "!=",
    "&&", "||", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "::",
)


def tokenize_c(src: str) -> list[str]:
    """Tokens of *src* with comments removed. String/char literals become one
    token each (their contents do not participate). Identifiers and numbers are
    kept verbatim so a refine (shared names/structure) scores high and an
    independent rewrite scores low.

    A hand scanner, not a regex: ``"//"`` inside a string and ``/*`` inside a
    char literal must not start comments, and a regex comment-strip gets that
    wrong on exactly the kind of code these kernels contain.
    """
    toks: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        # whitespace
        if c in " \t\r\n\f\v":
            i += 1
            continue
        # line comment
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            i += 2
            while i < n and src[i] != "\n":
                i += 1
            continue
        # block comment
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        # string / char literal -> one opaque token
        if c in "\"'":
            quote = c
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote:
                    j += 1
                    break
                j += 1
            toks.append("STR" if quote == '"' else "CHR")
            i = j
            continue
        # identifier / keyword
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            toks.append(src[i:j])
            i = j
            continue
        # number (incl. hex / float / suffixes)
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in ".xX+-"
                             and src[j - 1] in "eEpP"):
                j += 1
            toks.append(src[i:j])
            i = j
            continue
        # multi-char operator
        for op in _MULTI_OPS:
            if src.startswith(op, i):
                toks.append(op)
                i += len(op)
                break
        else:
            toks.append(c)  # single-char punctuation / operator
            i += 1
    return toks


def _ratio(a: list[str], b: list[str]) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def text_similarity(parent_src: str, child_src: str) -> float:
    """Token-sequence similarity in [0,1]. 1.0 = identical after comment/whitespace
    normalisation (a pure reformat); low = regenerated.

    Made SYMMETRIC by averaging both directions: ``SequenceMatcher.ratio`` is
    greedily order-dependent and can differ slightly by argument order, and a
    similarity that changes when you swap parent and child is not a similarity.
    """
    a, b = tokenize_c(parent_src), tokenize_c(child_src)
    return 0.5 * (_ratio(a, b) + _ratio(b, a))


# ---------------------------------------------------------------------------
# Structural similarity (optional, tree-sitter; robustness check)
# ---------------------------------------------------------------------------

def _tree_sitter_c():
    """(parser, version_str) or (None, reason). Pinned versions are reported so a
    structural number is reproducible; without them it is just drift."""
    try:
        import tree_sitter
        import tree_sitter_c
    except Exception as e:  # not installed
        return None, f"tree-sitter not available ({type(e).__name__})"
    try:
        from tree_sitter import Language, Parser
        lang = Language(tree_sitter_c.language())
        parser = Parser(lang)
        # Read the PINNED versions from installed distribution metadata, not the
        # modules' __version__ (these packages expose none). An empty version
        # string would make a recorded structural number un-reproducible.
        from importlib.metadata import version as _v
        def _vv(name):
            try:
                return _v(name)
            except Exception:
                return "?"
        ver = f"tree_sitter={_vv('tree-sitter')},tree_sitter_c={_vv('tree-sitter-c')}"
        return parser, ver
    except Exception as e:
        return None, f"tree-sitter init failed ({type(e).__name__}: {e})"


def _node_type_sequence(parser, src: str) -> list[str]:
    tree = parser.parse(src.encode("utf-8", "replace"))
    seq: list[str] = []
    stack = [tree.root_node]
    while stack:
        nd = stack.pop()
        if nd.is_named:
            seq.append(nd.type)
        stack.extend(reversed(nd.children))
    return seq


def structural_similarity(parser, parent_src: str, child_src: str) -> float:
    """AST node-type sequence similarity in [0,1]. Deliberately orthogonal to the
    textual measure — it ignores identifier names and constants, so agreement with
    the textual result is evidence the finding is not an artefact of one method."""
    a = _node_type_sequence(parser, parent_src)
    b = _node_type_sequence(parser, child_src)
    return 0.5 * (_ratio(a, b) + _ratio(b, a))  # symmetric, as for text_similarity


# ---------------------------------------------------------------------------
# Walk a checkpoint: pair each child with its parent, measure the edit
# ---------------------------------------------------------------------------

@dataclass
class ChildEdit:
    child_id: str
    parent_id: str
    file: str
    sim_text: float
    sim_struct: float | None
    child_valid: bool
    depth: int


def _candidate_file(node_dir: Path) -> Path | None:
    files = sorted(node_dir.glob("candidate_*.c"))
    return files[0] if files else None


def _is_valid(report: dict) -> bool:
    m = report.get("metrics") or {}
    # A node is valid iff it scored real data (all families passed). The evaluator
    # writes _scientific_score>0 only for valid nodes; has_real_data mirrors it.
    return bool(report.get("has_real_data")) or float(m.get("_scientific_score") or 0.0) > 0.0


def classify_checkpoint(ckpt: str | Path, parser=None) -> list[ChildEdit]:
    ckpt = Path(ckpt)
    reports: dict[str, dict] = {}
    dirs: dict[str, Path] = {}
    for nr in ckpt.glob("node_*/node_report.json"):
        try:
            d = json.loads(nr.read_text())
        except Exception:
            continue
        nid = d.get("node_id") or nr.parent.name
        reports[nid] = d
        dirs[nid] = nr.parent

    edits: list[ChildEdit] = []
    for nid, rep in reports.items():
        pid = rep.get("parent_id")
        if not pid or pid not in dirs:
            continue  # root, or parent outside this checkpoint
        child_c = _candidate_file(dirs[nid])
        parent_c = _candidate_file(dirs[pid])
        if not child_c or not parent_c or child_c.name != parent_c.name:
            continue
        ps = parent_c.read_text(errors="replace")
        cs = child_c.read_text(errors="replace")
        edits.append(ChildEdit(
            child_id=nid, parent_id=pid, file=child_c.name,
            sim_text=round(text_similarity(ps, cs), 4),
            sim_struct=(round(structural_similarity(parser, ps, cs), 4)
                        if parser is not None else None),
            child_valid=_is_valid(rep),
            depth=int(rep.get("depth") or 0),
        ))
    return sorted(edits, key=lambda e: (e.depth, e.child_id))


def summarize(edits: list[ChildEdit], threshold: float) -> dict:
    def _stats(subset: list[ChildEdit]) -> dict:
        sims = [e.sim_text for e in subset]
        if not sims:
            return {"n": 0}
        return {
            "n": len(sims),
            "median_sim_text": round(statistics.median(sims), 4),
            "mean_sim_text": round(statistics.fmean(sims), 4),
            "rewrite_rate": round(sum(s < threshold for s in sims) / len(sims), 4),
            "rewrite_rate_sweep": {str(t): round(sum(s < t for s in sims) / len(sims), 4)
                                   for t in _SWEEP},
        }
    struct = [e.sim_struct for e in edits if e.sim_struct is not None]
    return {
        "threshold": threshold,
        "all_children": _stats(edits),
        "valid_children": _stats([e for e in edits if e.child_valid]),
        "invalid_children": _stats([e for e in edits if not e.child_valid]),
        "structural": (
            {"n": len(struct), "median_sim_struct": round(statistics.median(struct), 4)}
            if struct else {"n": 0, "note": "structural check not run (tree-sitter absent)"}
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checkpoint", help="a checkpoint dir (workspace/experiments/<run>/)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"rewrite cut on textual similarity (default {DEFAULT_THRESHOLD}); "
                         f"the median is threshold-free and is the headline")
    ap.add_argument("--json", action="store_true", help="emit per-child JSON")
    ap.add_argument("--no-struct", action="store_true", help="skip the tree-sitter check")
    a = ap.parse_args()

    parser, ver = (None, "disabled") if a.no_struct else _tree_sitter_c()
    edits = classify_checkpoint(a.checkpoint, parser)
    summary = summarize(edits, a.threshold)
    summary["structural_backend"] = ver

    if a.json:
        print(json.dumps({"summary": summary, "children": [asdict(e) for e in edits]},
                         indent=2))
        return 0

    s = summary["all_children"]
    if not s.get("n"):
        print(f"no parent→child pairs with candidate files in {a.checkpoint}")
        return 0
    print(f"edit-lineage over {s['n']} children  (threshold={a.threshold})")
    print(f"  median textual similarity : {s['median_sim_text']}   "
          f"(1.0=reformat only, low=regenerated)")
    print(f"  rewrite rate              : {s['rewrite_rate']}  "
          f"sweep {s['rewrite_rate_sweep']}")
    for k in ("valid_children", "invalid_children"):
        st = summary[k]
        if st.get("n"):
            print(f"  {k:17s} n={st['n']:3d}  median={st['median_sim_text']}  "
                  f"rewrite_rate={st['rewrite_rate']}")
    st = summary["structural"]
    print(f"  structural (AST)          : "
          + (f"median={st['median_sim_struct']} over {st['n']}  [{ver}]"
             if st.get("n") else st.get("note", "—")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
