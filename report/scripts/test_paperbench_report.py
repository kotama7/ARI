"""Smoke tests for ``report/scripts/paperbench_report.py``.

Builds a synthetic ARI checkpoint and verifies the generator produces:
  - A LaTeX ``main.tex`` and all 6 chapter sources (per-paper report)
  - A summary ``main.tex`` listing the supplied papers (summary report)
  - LaTeX-safe escaping for paper titles that contain reserved chars
  - Graceful degradation when checkpoint files are missing

PDF compilation is NOT exercised — that requires ``latexmk`` + XeLaTeX,
which we leave to the ``report/Makefile`` target.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow ``import paperbench_report`` directly when running pytest from
# repo root or from report/scripts.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import paperbench_report as PR  # noqa: E402


@pytest.fixture
def synthetic_checkpoint(tmp_path: Path) -> Path:
    """Build a minimal ARI checkpoint with all four audit artefacts."""
    ckpt = tmp_path / "checkpoint"
    ckpt.mkdir()
    (ckpt / "paper_metadata.json").write_text(json.dumps({
        "title": "LLAMP: $\\&$ assessing latency",
        "authors": ["Alice", "Bob & Carol"],
        "venue": "SC24",
        "year": 2024,
        "license": "cc by 4.0",
        "license_assessment": {"note": "permissive — usable"},
        "source_type": "arxiv",
        "source": "2404.14193",
        "artifact_url": "https://example.com/llamp",
    }))
    (ckpt / "rubric.json").write_text(json.dumps({
        "version": "3",
        "generator": {"model": "gemini/gemini-2.5-pro"},
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 3600,
            "expected_artifacts": ["results.csv"],
            "execution_profile": {
                "kind": "mpi_gpu",
                "paper_max_ranks": 32,
                "requested_nodes": 4,
                "exclusive": True,
                "gpu_type": "v100",
            },
        },
        "rubric": {
            "id": "root", "weight": 1, "requirements": "Top",
            "sub_tasks": [
                {
                    "id": f"c{i}", "weight": 1,
                    "requirements": f"Child {i}",
                    "task_category": "Code Development",
                    "sub_tasks": [],
                }
                for i in range(5)
            ] + [
                {
                    "id": "c5", "weight": 2, "requirements": "Exec child",
                    "task_category": "Code Execution",
                    "sub_tasks": [],
                },
            ],
        },
    }))
    (ckpt / "grade.json").write_text(json.dumps({
        "ors_score": 0.42,
        "leaves": [
            {"requirements": f"Child {i}", "weight": 1, "passed": i % 2 == 0,
             "task_category": "Code Development"}
            for i in range(5)
        ] + [
            {"requirements": "Exec child", "weight": 2, "passed": False,
             "task_category": "Code Execution"}
        ],
        "negative_control": {"empty": 0.01, "boilerplate": 0.04, "passed": True},
    }))
    (ckpt / "repro_result.json").write_text(json.dumps({
        "sandbox_kind": "slurm",
        "partition": "sx40",
        "walltime": "01:00:00",
        "exit_code": 0,
        "elapsed_sec": 1234.5,
        "nodes": 4,
        "ntasks": 32,
        "exclusive": True,
        "gpu": {"type": "v100", "per_task": 1, "per_node": 4},
        "missing": [],
    }))
    repro = ckpt / "repro_sandbox"
    repro.mkdir()
    (repro / "reproduce.sh").write_text("#!/bin/bash\nsrun -n $SLURM_NTASKS python main.py\n")
    (repro / "results.csv").write_text("rank,gflops\n0,99.9\n")
    (repro / "reproduce.log").write_text("starting...\nsrun: launched 32 tasks\nresults: 99.9 GFLOPS\nDONE\n")
    (ckpt / "blocking_issues.log").write_text("module load cuda failed initially\nresolved by sourcing bashrc\n")
    return ckpt


# ── LaTeX escaping ───────────────────────────────────────────────────────


def test_tex_escape_basic():
    assert PR.tex_escape("a&b") == r"a\&b"
    assert PR.tex_escape("100%") == r"100\%"
    assert PR.tex_escape("file_name") == r"file\_name"
    assert PR.tex_escape("$x$") == r"\$x\$"
    assert PR.tex_escape(None) == ""


def test_tex_escape_backslash():
    assert PR.tex_escape("\\foo") == r"\textbackslash{}foo"


# ── Rubric tree walker ───────────────────────────────────────────────────


def test_walk_rubric_counts_leaves_and_depth():
    tree = {
        "sub_tasks": [
            {"sub_tasks": [], "task_category": "Code Development"},
            {
                "sub_tasks": [
                    {"sub_tasks": [], "task_category": "Code Execution"},
                    {"sub_tasks": [], "task_category": "Code Execution"},
                ],
            },
        ],
    }
    leaves, depth, cats = PR._walk_rubric(tree)
    assert leaves == 3
    assert depth == 2
    assert cats == {"Code Development": 1, "Code Execution": 2}


# ── Harvest ──────────────────────────────────────────────────────────────


def test_harvest_collects_all_fields(synthetic_checkpoint):
    h = PR.harvest_checkpoint(synthetic_checkpoint, "sc24-llamp")
    assert h.paper_title.startswith("LLAMP")
    assert h.paper_authors == ["Alice", "Bob & Carol"]
    assert h.ors_score == 0.42
    assert h.rubric_leaves_count == 6
    assert h.rubric_category_breakdown["Code Development"] == 5
    assert h.rubric_category_breakdown["Code Execution"] == 1
    assert h.execution_profile["kind"] == "mpi_gpu"
    assert h.repro_sandbox_kind == "slurm"
    assert h.repro_nodes == 4
    assert h.repro_exclusive is True
    assert h.repro_gpu_spec.startswith("v100")
    assert "DONE" in h.reproduce_log_tail
    assert "Code Development" in h.category_pass
    assert h.category_pass["Code Development"] == (3, 5)
    assert h.negative_control["passed"] is True
    assert len(h.blocking_issues) == 2
    assert h.recommendations  # at least the MPI-but-single-node would NOT fire here


def test_harvest_handles_missing_checkpoint_artefacts(tmp_path):
    """Empty checkpoint dir should not raise; returns harvest with defaults."""
    empty = tmp_path / "empty"
    empty.mkdir()
    h = PR.harvest_checkpoint(empty, "ghost")
    assert h.paper_id == "ghost"
    assert h.ors_score == 0.0
    assert h.rubric_leaves_count == 0
    # No repro_sandbox/ → tail is empty (the missing-file branch only
    # fires when the sandbox dir exists but the log inside it doesn't).
    assert h.reproduce_log_tail == ""
    # Recommendations always populated (default "no automated concerns").
    assert h.recommendations
    assert h.recommendations[0] == "No automated concerns flagged."


# ── Recommendations heuristic ────────────────────────────────────────────


def test_recommendations_flag_mpi_single_node(tmp_path):
    """MPI execution_profile + single-node reproduction → warn."""
    ckpt = tmp_path / "c"
    ckpt.mkdir()
    (ckpt / "rubric.json").write_text(json.dumps({
        "reproduce_contract": {
            "execution_profile": {"kind": "mpi", "paper_max_ranks": 16},
        },
        "rubric": {"sub_tasks": []},
    }))
    (ckpt / "repro_result.json").write_text(json.dumps({
        "nodes": 1, "ntasks": 1, "exit_code": 0,
    }))
    (ckpt / "grade.json").write_text(json.dumps({"ors_score": 0.5, "leaves": []}))
    h = PR.harvest_checkpoint(ckpt, "p")
    assert any("MPI but the run was single-node" in r for r in h.recommendations)


def test_recommendations_flag_missing_artefacts(tmp_path):
    ckpt = tmp_path / "c"
    ckpt.mkdir()
    (ckpt / "repro_result.json").write_text(json.dumps({
        "missing": ["results.csv", "plot.pdf"], "exit_code": 0,
    }))
    h = PR.harvest_checkpoint(ckpt, "p")
    assert any("expected artefact(s) missing" in r for r in h.recommendations)


# ── Rendering ────────────────────────────────────────────────────────────


def test_render_paper_report_writes_all_chapters(synthetic_checkpoint, tmp_path):
    """End-to-end smoke: TR3 acceptance. Verifies every chapter file lands
    and the generated LaTeX is non-empty + LaTeX-escapes title chars."""
    out = tmp_path / "audit" / "sc24-llamp"
    res = PR.generate_paper_report(
        checkpoint_dir=synthetic_checkpoint,
        paper_id="sc24-llamp",
        output_root=out,
        languages=["en"],
        formats=[],  # skip latexmk
    )
    assert res["status"] == "ok"
    en_dir = out / "en"
    assert (en_dir / "main.tex").is_file()
    main = (en_dir / "main.tex").read_text(encoding="utf-8")
    # Escaped & in author + escaped $ + escaped & in title
    assert r"Bob \& Carol" in main or r"Bob \& Carol" in (en_dir / "chapters" / "01_paper_metadata.tex").read_text()
    chapter_files = sorted((en_dir / "chapters").iterdir())
    chapter_names = {f.name for f in chapter_files}
    assert chapter_names == {
        "01_paper_metadata.tex",
        "02_rubric.tex",
        "03_reproduction.tex",
        "04_grading.tex",
        "05_blocking_issues.tex",
        "06_recommendations.tex",
    }
    # Chapter 2 mentions the rubric categories
    rubric_tex = (en_dir / "chapters" / "02_rubric.tex").read_text()
    assert "Code Development" in rubric_tex
    # Chapter 3 mentions multi-node + GPU
    repro_tex = (en_dir / "chapters" / "03_reproduction.tex").read_text()
    assert "nodes=4" in repro_tex
    assert "v100" in repro_tex
    # Chapter 4 has the ORS score
    grade_tex = (en_dir / "chapters" / "04_grading.tex").read_text()
    assert "42.0" in grade_tex
    # Negative control surfaced
    assert "0.010" in grade_tex or "0.040" in grade_tex


def test_render_paper_report_handles_minimal_checkpoint(tmp_path):
    """Even with no JSON files, the renderer should produce valid LaTeX
    skeletons (no KeyError / no template-placeholder leak)."""
    bare = tmp_path / "bare"
    bare.mkdir()
    out = tmp_path / "audit" / "bare"
    res = PR.generate_paper_report(
        checkpoint_dir=bare,
        paper_id="bare",
        output_root=out,
        languages=["en"],
        formats=[],
    )
    assert res["status"] == "ok"
    main = (out / "en" / "main.tex").read_text()
    # No unsubstituted placeholders (strip LaTeX comments first — the
    # template header carries a literal {{ ... }} example in its comment).
    body = "\n".join(
        line for line in main.splitlines() if not line.lstrip().startswith("%")
    )
    assert "{{" not in body, body


def test_apply_glossary_swaps_en_to_ja(tmp_path, monkeypatch):
    """Glossary substitution: canonical English fixed strings get swapped
    for the ja equivalent when language='ja'. Longer matches replace
    before shorter ones to avoid prefix shadowing."""
    monkeypatch.setattr(PR, "_GLOSSARY_CACHE", None)
    text = (
        "\\section{Paper Metadata}\n"
        "Authors: Alice, Bob\n"
        "License: cc by 4.0\n"
        "task_category: Code Development\n"
    )
    out = PR._apply_glossary(text, "ja")
    # Section header should be translated
    assert "論文メタデータ" in out
    assert "Paper Metadata" not in out
    # task_category value also covered by glossary
    assert "コード開発" in out


def test_apply_glossary_noop_for_english():
    text = "Paper Metadata\nCode Development"
    assert PR._apply_glossary(text, "en") == text


def test_inject_lang_preamble_adds_xecjk_for_ja_zh():
    base = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
    ja = PR._inject_lang_preamble(base, "ja")
    assert "xeCJK" in ja
    assert "HaranoAji" in ja
    # Preamble lands BEFORE \begin{document}
    assert ja.index("HaranoAji") < ja.index("\\begin{document}")

    zh = PR._inject_lang_preamble(base, "zh")
    assert "Fandol" in zh
    # English unchanged
    assert PR._inject_lang_preamble(base, "en") == base


def test_figure_leaf_score_heatmap_uses_grade_leaves(tmp_path):
    """TR5: per-leaf heatmap aggregates grade_leaves by task_category and
    writes a PDF figure when matplotlib is available."""
    h = PR.CheckpointHarvest(paper_id="x")
    h.grade_leaves = [
        {"task_category": "Code Development", "passed": True},
        {"task_category": "Code Development", "passed": False},
        {"task_category": "Code Development", "passed": True},
        {"task_category": "Code Execution", "passed": False},
        {"task_category": "Code Execution", "passed": False},
        {"task_category": "Result Analysis", "passed": True},
    ]
    out = tmp_path / "heat.pdf"
    ok = PR._figure_leaf_score_heatmap(h, out)
    if not ok:
        pytest.skip("matplotlib not installed")
    assert out.is_file()
    assert out.stat().st_size > 0


def test_figure_leaf_score_heatmap_falls_back_to_category_pass(tmp_path):
    """When grade_leaves is empty but category_pass has aggregate counts
    (e.g. older grade.json snapshots), the heatmap synthesizes per-leaf
    cells in category order so it still renders something useful."""
    h = PR.CheckpointHarvest(paper_id="x")
    h.leaves_total = 5
    h.category_pass = {
        "Code Development": (2, 3),
        "Code Execution": (0, 2),
    }
    out = tmp_path / "heat.pdf"
    ok = PR._figure_leaf_score_heatmap(h, out)
    if not ok:
        pytest.skip("matplotlib not installed")
    assert out.is_file()


def test_figure_leaf_score_heatmap_skips_when_no_data(tmp_path):
    """Empty harvest → return False without writing."""
    h = PR.CheckpointHarvest(paper_id="x")
    out = tmp_path / "heat.pdf"
    assert PR._figure_leaf_score_heatmap(h, out) is False
    assert not out.exists()


def test_figure_rubric_tree_skips_when_dot_missing(tmp_path, monkeypatch):
    """No graphviz dot on PATH → return False, don't write file. The audit
    report falls back to a text-only stub via the caller."""
    h = PR.CheckpointHarvest(paper_id="x")
    h.rubric_envelope = {"rubric": {"id": "r", "weight": 1, "requirements": "R",
                                     "sub_tasks": [{"id": "c", "weight": 1,
                                                    "requirements": "C",
                                                    "sub_tasks": []}]}}
    monkeypatch.setattr(PR.shutil, "which", lambda name: None)
    out = tmp_path / "tree.pdf"
    assert PR._figure_rubric_tree(h, out) is False
    assert not out.exists()


def test_figure_rubric_tree_invokes_dot_when_available(tmp_path, monkeypatch):
    """When dot is on PATH, the helper composes a digraph and shells out.
    We intercept subprocess.run to inspect the DOT source without needing
    graphviz installed in CI.
    """
    h = PR.CheckpointHarvest(paper_id="x")
    h.rubric_envelope = {
        "rubric": {
            "id": "root", "weight": 1, "requirements": "Top",
            "sub_tasks": [
                {"id": "a", "weight": 3, "requirements": "Heavy", "sub_tasks": []},
                {"id": "b", "weight": 1, "requirements": "Light", "sub_tasks": []},
            ],
        }
    }
    captured: dict = {}

    class _FakeProc:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, *, input=None, **kw):
        captured["cmd"] = cmd
        captured["input"] = input
        # Simulate dot writing the output file
        out_idx = cmd.index("-o")
        out_path = Path(cmd[out_idx + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\n...stub...")
        return _FakeProc()

    monkeypatch.setattr(PR.shutil, "which", lambda name: "/usr/bin/dot")
    monkeypatch.setattr(PR.subprocess, "run", _fake_run)
    out = tmp_path / "tree.pdf"
    assert PR._figure_rubric_tree(h, out) is True
    assert out.is_file()
    dot_src = captured["input"]
    assert "digraph rubric" in dot_src
    assert '"a"' in dot_src and '"b"' in dot_src
    # Heavy child should appear before Light child (weight-sorted)
    assert dot_src.index('"a"') < dot_src.index('"b"')


def test_figure_rubric_tree_truncates_large_trees(tmp_path, monkeypatch):
    """Trees with > max_nodes nodes get a synthetic '... (truncated)' sink
    so the rendered figure stays readable."""
    h = PR.CheckpointHarvest(paper_id="x")
    h.rubric_envelope = {
        "rubric": {
            "id": "root", "weight": 1, "requirements": "Root",
            "sub_tasks": [
                {"id": f"c{i}", "weight": 1, "requirements": f"Child {i}", "sub_tasks": []}
                for i in range(200)
            ],
        }
    }
    captured: dict = {}

    class _FakeProc:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, *, input=None, **kw):
        captured["input"] = input
        out_idx = cmd.index("-o")
        Path(cmd[out_idx + 1]).write_bytes(b"%PDF\n")
        return _FakeProc()

    monkeypatch.setattr(PR.shutil, "which", lambda name: "/usr/bin/dot")
    monkeypatch.setattr(PR.subprocess, "run", _fake_run)
    PR._figure_rubric_tree(h, tmp_path / "tree.pdf", max_nodes=10)
    assert "(truncated" in captured["input"]


def test_render_paper_report_invokes_pandoc_for_html_and_md(
    synthetic_checkpoint, tmp_path, monkeypatch,
):
    """When pandoc is on PATH and ``formats`` requests html/md, the helper
    shells out and writes the additional outputs. We intercept the
    subprocess + which() so the test runs without pandoc installed.
    """
    invocations: list[list[str]] = []

    class _FakeProc:
        returncode = 0
        stderr = b""
        stdout = b""

    def _fake_run(cmd, **kw):
        invocations.append(cmd)
        # Simulate pandoc creating the output file
        if cmd and cmd[0] == "pandoc":
            try:
                out_idx = cmd.index("-o")
                Path(cmd[out_idx + 1]).write_text("# rendered\n")
            except (ValueError, IndexError):
                pass
        return _FakeProc()

    def _fake_which(name):
        return f"/usr/bin/{name}" if name in ("pandoc",) else None

    monkeypatch.setattr(PR.shutil, "which", _fake_which)
    monkeypatch.setattr(PR.subprocess, "run", _fake_run)

    out = tmp_path / "audit" / "synth"
    res = PR.generate_paper_report(
        checkpoint_dir=synthetic_checkpoint,
        paper_id="synth",
        output_root=out,
        languages=["en"],
        formats=["html", "md"],
    )
    assert res["status"] == "ok"
    # pandoc was invoked twice (html + md)
    pandoc_calls = [c for c in invocations if c and c[0] == "pandoc"]
    assert len(pandoc_calls) == 2
    cmds = " ".join(" ".join(c) for c in pandoc_calls)
    assert "html5" in cmds
    assert "gfm" in cmds
    assert (out / "en" / "main.html").is_file()
    assert (out / "en" / "main.md").is_file()


def test_render_summary_report(synthetic_checkpoint, tmp_path):
    """Multi-paper summary: TR4 acceptance."""
    # Build a 2nd synthetic checkpoint
    ckpt2 = tmp_path / "c2"
    ckpt2.mkdir()
    (ckpt2 / "grade.json").write_text(json.dumps({"ors_score": 0.81, "leaves": []}))
    (ckpt2 / "paper_metadata.json").write_text(json.dumps({
        "title": "Other paper", "authors": [], "license": "MIT",
    }))

    out = tmp_path / "summary"
    res = PR.generate_summary_report(
        checkpoint_dirs=[synthetic_checkpoint, ckpt2],
        output_root=out,
        paper_ids=["sc24-llamp", "ckpt2"],
        languages=["en"],
        formats=[],
    )
    assert res["status"] == "ok"
    assert res["papers"] == 2
    main = (out / "en" / "main.tex").read_text()
    assert "sc24-llamp" in main
    assert "ckpt2" in main
    # Sorted descending by ORS — ckpt2 (0.81) should appear BEFORE sc24-llamp (0.42)
    assert main.index("ckpt2") < main.index("sc24-llamp")
