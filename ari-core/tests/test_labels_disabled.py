"""``ARI_BFTS_NO_LABEL`` turns the BFTS exploration LABEL feature off at ALL sites.

The label (draft/improve/ablation/validation/debug) steers the search in three
places, and only the third is reporting:

  1. the system prompt's ``NODE ROLE`` — per-label ORDERS ("ABLATION: remove or
     disable one component", "DEBUG: the parent failed, diagnose it", "DRAFT:
     implement from scratch");
  2. the child's ``Task:`` line — the same orders restated, plus a bare
     ``task=<label>`` token;
  3. node SELECTION — the default ``scientific_plus_diversity`` frontier score adds
     ``diversity_bonus``: +0.05 for under-represented labels, so WHICH node is
     expanded depends on label history.

``ARI_REPORT_MINIMAL`` / ``ARI_BFTS_DETERMINISTIC_LABEL`` only strip labels from
node_report and tree.json. With just those on — the state a real 4-arm study ran in
— the label still drove (1)(2)(3) while being invisible in the deliverable. Measured
there: the ABLATION share of children was 0/1/3/4, monotone in handoff richness, so
"the full log shifts rewrite->refine" was inseparable from "the full log makes the
planner emit ABLATION, which literally orders the child to edit". These tests pin
that the off switch actually reaches every site.
"""
from __future__ import annotations

import pytest

from ari.agent.loop import labels_disabled


class TestFlag:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("ARI_BFTS_NO_LABEL", raising=False)
        assert labels_disabled() is False

    @pytest.mark.parametrize("v", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_truthy_values(self, monkeypatch, v):
        monkeypatch.setenv("ARI_BFTS_NO_LABEL", v)
        assert labels_disabled() is True

    @pytest.mark.parametrize("v", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, monkeypatch, v):
        monkeypatch.setenv("ARI_BFTS_NO_LABEL", v)
        assert labels_disabled() is False

    def test_reporting_toggles_do_not_disable_the_feature(self, monkeypatch):
        """THE BUG: these looked like an off switch (one was even commented
        "label off") but were reporting-only. ARI_REPORT_MINIMAL has since been
        DELETED outright; this pins that neither name can ever be mistaken for the
        real switch again."""
        monkeypatch.delenv("ARI_BFTS_NO_LABEL", raising=False)
        monkeypatch.setenv("ARI_REPORT_MINIMAL", "1")
        monkeypatch.setenv("ARI_BFTS_DETERMINISTIC_LABEL", "1")
        assert labels_disabled() is False, (
            "ARI_REPORT_MINIMAL / ARI_BFTS_DETERMINISTIC_LABEL must NOT be mistaken "
            "for the label off switch — they only touched the record")

    def test_record_suppression_flag_no_longer_exists(self, monkeypatch):
        """``ARI_REPORT_MINIMAL`` is GONE from the code: setting it must not hide a
        thing. A flag that erases a live variable from the record is a bug factory —
        it leaves the influence and deletes the evidence."""
        from ari.orchestrator.node import Node
        monkeypatch.setenv("ARI_REPORT_MINIMAL", "1")
        d = Node(id="n1", parent_id=None, depth=0).to_dict()
        for f in ("label", "raw_label", "original_direction"):
            assert f in d, f"{f} must ALWAYS be recorded; ARI_REPORT_MINIMAL is deleted"

    def test_flag_is_absent_from_the_codebase(self):
        """Nothing may re-introduce a record-only suppression under this name.

        Checked with AST, not grep: prose in a docstring explaining WHY the flag was
        removed is desirable, but a string literal that some code actually READS is
        the bug. Only the latter must fail.
        """
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "ari"
        live = []
        for p in root.rglob("*.py"):
            tree = ast.parse(p.read_text(errors="replace"), filename=str(p))
            docstrings = {
                id(n.body[0].value)
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)
            }
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and "ARI_REPORT_MINIMAL" in node.value
                        and id(node) not in docstrings):
                    live.append(f"{p.name}:{node.lineno}")
        assert not live, (
            f"ARI_REPORT_MINIMAL is read by live code at: {live} — a flag that hides "
            f"a live variable from the record must not be re-introduced")


class TestStudyDoesNotHideLiveVariables:
    """The study must never use a record-ONLY suppression flag.

    A flag that strips a field from node_report/tree.json does not make the
    underlying variable inert — it only deletes the evidence. That is how the label
    confound survived a full 4-arm run: labels steered the prompt AND selection
    while ARI_REPORT_MINIMAL kept them out of the deliverable, so no amount of
    reading node_report could reveal it. Turn the FEATURE off (ARI_BFTS_NO_LABEL);
    never hide a live one.
    """

    def _fixed_env(self) -> dict:
        import ast
        from pathlib import Path
        src = Path(__file__).resolve().parents[2] / "scripts" / "run_handoff_ablation.py"
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_FIXED" for t in node.targets
            ):
                return ast.literal_eval(node.value)
        raise AssertionError("_FIXED not found in run_handoff_ablation.py")

    def test_study_turns_the_label_feature_off(self):
        assert self._fixed_env().get("ARI_BFTS_NO_LABEL") == "1"

    def test_study_does_not_use_record_only_suppression(self):
        env = self._fixed_env()
        for flag in ("ARI_REPORT_MINIMAL", "ARI_BFTS_DETERMINISTIC_LABEL"):
            assert flag not in env, (
                f"{flag} only strips fields from the record while the variable keeps "
                f"driving the search — it hides confounds instead of removing them. "
                f"Disable the FEATURE (ARI_BFTS_NO_LABEL), do not hide it.")


class TestSelectionSite:
    """SITE 3: selection must stop consulting labels."""

    def _bfts(self):
        from unittest.mock import MagicMock
        from ari.config import BFTSConfig
        from ari.llm.client import LLMClient
        from ari.orchestrator.bfts import BFTS
        return BFTS(BFTSConfig(max_depth=3, max_total_nodes=10),
                    MagicMock(spec=LLMClient))

    def _node(self, label):
        from ari.orchestrator.node import Node, NodeLabel
        n = Node(id="n1", parent_id=None, depth=1, has_real_data=True,
                 metrics={"_scientific_score": 0.5})
        n.label = NodeLabel.from_str(label)
        return n

    def test_diversity_bonus_is_zero_when_labels_are_off(self, monkeypatch):
        b = self._bfts()
        # make a history where "ablation" is rare -> would normally earn the bonus
        for _ in range(6):
            b.record_run(self._node("improve"))
        rare = self._node("ablation")

        monkeypatch.delenv("ARI_BFTS_NO_LABEL", raising=False)
        on = b.diversity_bonus(rare)
        monkeypatch.setenv("ARI_BFTS_NO_LABEL", "1")
        off = b.diversity_bonus(rare)

        assert on > 0.0, "precondition: an under-represented label normally earns a bonus"
        assert off == 0.0, "with labels off, selection must not consult labels at all"

    def test_frontier_ranking_ignores_labels_when_off(self, monkeypatch):
        """The bonus is what let a label change WHICH node is expanded."""
        b = self._bfts()
        for _ in range(6):
            b.record_run(self._node("improve"))
        common, rare = self._node("improve"), self._node("ablation")

        monkeypatch.setenv("ARI_BFTS_NO_LABEL", "1")
        # identical _scientific_score -> identical frontier score, label irrelevant
        assert b._fallback_score(common, frontier_size=2) == \
               b._fallback_score(rare, frontier_size=2)
