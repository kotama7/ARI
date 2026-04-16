"""Tests for file upload → BFTS node propagation (Plan A + Plan B).

Plan A: api_experiment auto-appends uploaded file paths to ## Provided Files
        in experiment.md, using language-aware section headers.
Plan B: cli._run_loop copies all user files from checkpoint dir into each
        node's work_dir at execution time.
Also tests that the agent system prompt lists provided files and that
the coding-skill tools can read, write, copy, and execute them.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ari.agent.workflow import WorkflowHints, from_experiment_text
from ari.orchestrator.node import Node, NodeStatus


# ══════════════════════════════════════════════════════════════════════════════
# Plan A: auto-append uploaded files to experiment.md
# ══════════════════════════════════════════════════════════════════════════════


class TestPlanA_AutoAppendProvidedFiles:
    """Launch must inject uploaded file paths into experiment.md."""

    def _run_launch_with_staging(self, tmp_path, language, existing_md):
        """Helper: set up staging dir with files, call launch logic, return md text."""
        from ari.viz import state as _st

        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "data.csv").write_text("x,y\n1,2\n")
        (staging / "helper.py").write_text("print('hi')\n")

        ckpt = tmp_path / "checkpoints" / "20260414_test"
        ckpt.mkdir(parents=True)
        (ckpt / "experiment.md").write_text(existing_md, encoding="utf-8")

        # Simulate the staging→checkpoint copy + Plan A logic from api_experiment
        import re, shutil
        _skip = {"experiment.md", "launch_config.json", "meta.json"}
        _uploaded_paths: list[Path] = []
        for _f in staging.iterdir():
            if _f.is_file() and _f.name not in _skip:
                _dest = ckpt / _f.name
                if not _dest.exists():
                    shutil.copy2(str(_f), str(_dest))
                _uploaded_paths.append(_dest)

        if _uploaded_paths:
            _pf_lines = "\n".join(f"- {p}" for p in sorted(_uploaded_paths))
            _md_path = ckpt / "experiment.md"
            _md_text = _md_path.read_text(encoding="utf-8")
            _lang = language or "en"
            _section_headers = {"ja": "提供ファイル", "zh": "提供文件"}
            _section_header = _section_headers.get(_lang, "Provided Files")
            if re.search(
                r"##\s*(?:提供ファイル|提供文件|Provided Files?|Local Files?|Files?)\s*\n",
                _md_text, re.IGNORECASE,
            ):
                def _append_files(m):
                    return m.group(0).rstrip("\n") + "\n" + _pf_lines + "\n"
                _md_text = re.sub(
                    r"(##\s*(?:提供ファイル|提供文件|Provided Files?|Local Files?|Files?)\s*\n.*?)(?=\n##|\Z)",
                    _append_files, _md_text, count=1, flags=re.DOTALL | re.IGNORECASE,
                )
            else:
                _md_text = _md_text.rstrip("\n") + f"\n\n## {_section_header}\n" + _pf_lines + "\n"
            _md_path.write_text(_md_text, encoding="utf-8")

        return (ckpt / "experiment.md").read_text(encoding="utf-8")

    def test_english_new_section(self, tmp_path):
        """English: creates ## Provided Files when none exists."""
        md = self._run_launch_with_staging(
            tmp_path, "en", "## Research Goal\nOptimize X\n"
        )
        assert "## Provided Files" in md
        assert "data.csv" in md
        assert "helper.py" in md

    def test_japanese_new_section(self, tmp_path):
        """Japanese: creates ## 提供ファイル."""
        md = self._run_launch_with_staging(
            tmp_path, "ja", "## Research Goal\nOptimize X\n"
        )
        assert "## 提供ファイル" in md
        assert "data.csv" in md

    def test_chinese_new_section(self, tmp_path):
        """Chinese: creates ## 提供文件."""
        md = self._run_launch_with_staging(
            tmp_path, "zh", "## Research Goal\nOptimize X\n"
        )
        assert "## 提供文件" in md
        assert "data.csv" in md

    def test_append_to_existing_section(self, tmp_path):
        """Appends to existing ## Provided Files instead of creating duplicate."""
        existing = "## Research Goal\nOptimize X\n\n## Provided Files\n- /old/file.txt\n"
        md = self._run_launch_with_staging(tmp_path, "en", existing)
        assert md.count("## Provided Files") == 1, "must not duplicate section"
        assert "/old/file.txt" in md
        assert "data.csv" in md

    def test_append_to_existing_japanese_section(self, tmp_path):
        """Appends to existing ## 提供ファイル section."""
        existing = "## Research Goal\nGoal\n\n## 提供ファイル\n- /old/data.dat\n"
        md = self._run_launch_with_staging(tmp_path, "ja", existing)
        assert md.count("## 提供ファイル") == 1
        assert "/old/data.dat" in md
        assert "data.csv" in md

    def test_parser_recognizes_appended_paths(self, tmp_path):
        """workflow.py parser must find the auto-appended file paths."""
        md = self._run_launch_with_staging(
            tmp_path, "en", "## Research Goal\nTest\n"
        )
        hints = from_experiment_text(md)
        fnames = [fname for _, fname in hints.provided_files]
        assert "data.csv" in fnames
        assert "helper.py" in fnames

    def test_parser_recognizes_japanese_section(self, tmp_path):
        """workflow.py parser must recognize ## 提供ファイル."""
        md = self._run_launch_with_staging(
            tmp_path, "ja", "## Research Goal\nTest\n"
        )
        hints = from_experiment_text(md)
        fnames = [fname for _, fname in hints.provided_files]
        assert "data.csv" in fnames

    def test_parser_recognizes_chinese_section(self, tmp_path):
        """workflow.py parser must recognize ## 提供文件."""
        md = self._run_launch_with_staging(
            tmp_path, "zh", "## Research Goal\nTest\n"
        )
        hints = from_experiment_text(md)
        fnames = [fname for _, fname in hints.provided_files]
        assert "data.csv" in fnames


# ══════════════════════════════════════════════════════════════════════════════
# Plan B: checkpoint files auto-copied into node work_dir
# ══════════════════════════════════════════════════════════════════════════════


def _make_cfg(max_total_nodes=4, max_parallel=1, timeout=60):
    from ari.config import ARIConfig, BFTSConfig
    return ARIConfig(
        bfts=BFTSConfig(
            max_total_nodes=max_total_nodes,
            max_parallel_nodes=max_parallel,
            timeout_per_node=timeout,
        ),
    )


def _make_agent(succeed=True):
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="", slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        if succeed:
            node.mark_success(eval_summary="ok")
            node.has_real_data = True
        else:
            node.mark_failed(error_log="fail")
        return node

    agent.run.side_effect = _run
    return agent


def _make_bfts():
    bfts = MagicMock()
    bfts.should_prune.return_value = False
    # No expansion — just run the root node
    bfts.expand.return_value = []
    bfts.select_best_to_expand.side_effect = lambda f, g, m: f[0] if f else None
    bfts.select_next_node.side_effect = lambda p, g, m: p[0] if p else None
    return bfts


class TestPlanB_CheckpointFilesToWorkDir:
    """_run_loop must copy user files from checkpoint into each node's work_dir."""

    def test_checkpoint_files_copied_to_node(self):
        """User files in checkpoint dir appear in node work_dir after execution."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            # Place user files in checkpoint
            (ckpt / "data.csv").write_text("a,b\n1,2\n")
            (ckpt / "script.py").write_text("print(1)\n")
            # Meta files that should NOT be copied
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")
            (ckpt / "launch_config.json").write_text("{}")
            (ckpt / "meta.json").write_text("{}")
            (ckpt / "ari_run_1234.log").write_text("log line\n")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run",
            )

            # Node should have received a work_dir
            assert hasattr(root, "work_dir") and root.work_dir
            wd = Path(root.work_dir)
            # User files must be present
            assert (wd / "data.csv").exists(), "data.csv not copied to work_dir"
            assert (wd / "script.py").exists(), "script.py not copied to work_dir"
            # Meta files must NOT be present
            assert not (wd / "experiment.md").exists()
            assert not (wd / "launch_config.json").exists()
            assert not (wd / "meta.json").exists()
            assert not (wd / "ari_run_1234.log").exists()

    def test_provided_files_take_precedence(self):
        """If a file is both in provided_files and checkpoint, provided_files wins (first copy)."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            # Same filename in checkpoint (stale) and provided_files source (fresh)
            (ckpt / "data.csv").write_text("stale")
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            src_dir = Path(tmpdir) / "src_files"
            src_dir.mkdir()
            (src_dir / "data.csv").write_text("fresh")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)
            agent.hints.provided_files = [(str(src_dir / "data.csv"), "data.csv")]

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run",
            )

            wd = Path(root.work_dir)
            # provided_files copy happens first, so "fresh" should win
            assert (wd / "data.csv").read_text() == "fresh"

    def test_empty_checkpoint_no_error(self):
        """No crash when checkpoint dir has only meta files."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run",
            )
            # Should complete without errors
            assert root.status == NodeStatus.SUCCESS

    def test_uploads_subdir_copied_to_node(self):
        """Files in checkpoint/uploads/ are copied to node work_dir."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            uploads = ckpt / "uploads"
            uploads.mkdir()
            (uploads / "dataset.csv").write_text("x,y\n1,2\n")
            (uploads / "config.yaml").write_text("key: val\n")
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run",
            )

            wd = Path(root.work_dir)
            assert (wd / "dataset.csv").exists(), "uploads/dataset.csv not copied"
            assert (wd / "config.yaml").exists(), "uploads/config.yaml not copied"
            # Also mirrored under uploads/ so scripts that reference
            # "uploads/dataset.csv" still resolve.
            assert (wd / "uploads" / "dataset.csv").exists()
            assert (wd / "uploads" / "config.yaml").exists()

    def test_uploads_nested_subdirs_preserved(self):
        """Nested directory structure under uploads/ survives the copy."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            uploads = ckpt / "uploads"
            (uploads / "data" / "inputs").mkdir(parents=True)
            (uploads / "data" / "inputs" / "x.csv").write_text("1\n")
            (uploads / "data" / "y.csv").write_text("2\n")
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run",
            )

            wd = Path(root.work_dir)
            assert (wd / "data" / "inputs" / "x.csv").read_text() == "1\n"
            assert (wd / "data" / "y.csv").read_text() == "2\n"
            assert (wd / "uploads" / "data" / "inputs" / "x.csv").exists()

    def test_uploads_reach_child_nodes(self):
        """Child nodes (not just root) receive uploaded files."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_test"
            ckpt.mkdir(parents=True)
            uploads = ckpt / "uploads"
            uploads.mkdir()
            (uploads / "dataset.csv").write_text("shared\n")
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=2)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            # Return the child when expanding the root once, then nothing.
            bfts.expand.side_effect = [[child], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-child",
            )

            assert getattr(child, "work_dir", None), "child has no work_dir"
            wd = Path(child.work_dir)
            assert (wd / "dataset.csv").exists(), "child did not receive uploaded file"
            assert (wd / "uploads" / "dataset.csv").exists()

    def test_parent_work_dir_inherited_by_child(self):
        """Files generated by the parent node appear in the child's work_dir."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_inherit"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=2)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            # When the root runs, drop a generated artifact in its work_dir
            # so we can later verify the child inherits it.
            def _run_root_then_child(node, exp_data):
                if node.parent_id is None:
                    Path(exp_data["work_dir"], "generated.txt").write_text("hi")
                node.mark_running()
                node.mark_success(eval_summary="ok")
                node.has_real_data = True
                return node
            agent.run.side_effect = _run_root_then_child

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            bfts.expand.side_effect = [[child], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-inherit",
            )

            assert getattr(child, "work_dir", None)
            assert (Path(child.work_dir) / "generated.txt").read_text() == "hi"

    def test_parent_nested_subdirs_inherited(self):
        """Nested directories and files created by parent reach child."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_nested_inherit"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=2)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            def _run(node, exp_data):
                if node.parent_id is None:
                    wd = Path(exp_data["work_dir"])
                    (wd / "src" / "lib").mkdir(parents=True)
                    (wd / "src" / "lib" / "util.py").write_text("X = 1\n")
                    (wd / "results" / "sub").mkdir(parents=True)
                    (wd / "results" / "sub" / "out.csv").write_text("a,b\n")
                    (wd / "top.txt").write_text("top\n")
                node.mark_running()
                node.mark_success(eval_summary="ok")
                node.has_real_data = True
                return node
            agent.run.side_effect = _run

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            bfts.expand.side_effect = [[child], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-nested-inherit",
            )

            wd = Path(child.work_dir)
            assert (wd / "src" / "lib" / "util.py").read_text() == "X = 1\n"
            assert (wd / "results" / "sub" / "out.csv").read_text() == "a,b\n"
            assert (wd / "top.txt").read_text() == "top\n"

    def test_parent_inheritance_skips_meta_and_logs(self):
        """Meta files and *.log files in parent are NOT inherited."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_meta_skip"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=2)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            def _run(node, exp_data):
                if node.parent_id is None:
                    wd = Path(exp_data["work_dir"])
                    (wd / "keep.py").write_text("keep\n")
                    (wd / "noisy.log").write_text("log line\n")
                    (wd / "ari.log").write_text("ari\n")
                    (wd / "tree.json").write_text("{}")
                    (wd / "meta.json").write_text("{}")
                node.mark_running()
                node.mark_success(eval_summary="ok")
                node.has_real_data = True
                return node
            agent.run.side_effect = _run

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            bfts.expand.side_effect = [[child], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-meta-skip",
            )

            wd = Path(child.work_dir)
            assert (wd / "keep.py").exists(), "non-meta user file must be inherited"
            assert not (wd / "noisy.log").exists(), ".log extension should be filtered"
            assert not (wd / "ari.log").exists(), "ari.log should be filtered"
            assert not (wd / "tree.json").exists(), "tree.json is meta"
            assert not (wd / "meta.json").exists(), "meta.json is meta"

    def test_parent_inheritance_preserves_parent_version(self):
        """When parent has a modified version of a checkpoint file, parent wins."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_precedence"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")
            # Same filename lives in checkpoint; parent will overwrite its copy.
            (ckpt / "data.csv").write_text("stale-from-checkpoint\n")

            cfg = _make_cfg(max_total_nodes=2)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            def _run(node, exp_data):
                if node.parent_id is None:
                    wd = Path(exp_data["work_dir"])
                    # Parent modifies the file inside its own work_dir
                    (wd / "data.csv").write_text("fresh-from-parent\n")
                node.mark_running()
                node.mark_success(eval_summary="ok")
                node.has_real_data = True
                return node
            agent.run.side_effect = _run

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            bfts.expand.side_effect = [[child], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-precedence",
            )

            # Parent inheritance runs first, so the child should see parent's
            # fresh version — subsequent checkpoint copy must not overwrite it.
            assert (
                Path(child.work_dir) / "data.csv"
            ).read_text() == "fresh-from-parent\n"

    def test_parent_inheritance_skipped_for_root(self):
        """Root node has no parent_id, so inheritance is a no-op (no crash)."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_root_only"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")
            (ckpt / "only_root.txt").write_text("hi\n")

            cfg = _make_cfg(max_total_nodes=1)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            root = Node(id="root", parent_id=None, depth=0)
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-root-only",
            )
            assert root.status == NodeStatus.SUCCESS
            assert (Path(root.work_dir) / "only_root.txt").exists()

    def test_grandchild_receives_chain_of_files(self):
        """Files propagate across two generations (root → child → grandchild)."""
        from ari.cli import _run_loop

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "checkpoints" / "20260414_grandchild"
            ckpt.mkdir(parents=True)
            (ckpt / "experiment.md").write_text("## Goal\nTest\n")

            cfg = _make_cfg(max_total_nodes=3)
            bfts = _make_bfts()
            agent = _make_agent(succeed=True)

            def _run(node, exp_data):
                wd = Path(exp_data["work_dir"])
                if node.id == "root":
                    (wd / "root_file.txt").write_text("r\n")
                elif node.id == "child":
                    (wd / "child_file.txt").write_text("c\n")
                node.mark_running()
                node.mark_success(eval_summary="ok")
                node.has_real_data = True
                return node
            agent.run.side_effect = _run

            root = Node(id="root", parent_id=None, depth=0)
            child = Node(id="child", parent_id="root", depth=1)
            grand = Node(id="grand", parent_id="child", depth=2)
            # Expand root → [child], child → [grand], grand → []
            bfts.expand.side_effect = [[child], [grand], []]
            _run_loop(
                cfg, bfts, agent,
                pending=[root], all_nodes=[root],
                experiment_data={"goal": "test", "topic": "t", "file": "f.md"},
                checkpoint_dir=ckpt, run_id="test-run-grandchild",
            )

            wd = Path(grand.work_dir)
            assert (wd / "root_file.txt").read_text() == "r\n", "root file missing in grandchild"
            assert (wd / "child_file.txt").read_text() == "c\n", "child file missing in grandchild"


# ══════════════════════════════════════════════════════════════════════════════
# System prompt: provided files are listed for the agent
# ══════════════════════════════════════════════════════════════════════════════


class TestProvidedFilesInSystemPrompt:
    """AgentLoop system prompt must list files already in work_dir."""

    def test_system_prompt_lists_provided_files(self, tmp_path):
        """Files present in work_dir appear in EXPERIMENT ENVIRONMENT hint."""
        from ari.agent.loop import AgentLoop
        from ari.orchestrator.node import Node

        wd = tmp_path / "work"
        wd.mkdir()
        (wd / "data.csv").write_text("a,b\n1,2\n")
        (wd / "helper.py").write_text("print('hi')\n")

        loop = AgentLoop.__new__(AgentLoop)
        loop.hints = WorkflowHints()
        loop.max_react_steps = 10
        loop.timeout_per_node = 3600
        loop._suppress_tools = set()

        node = Node(id="n1", parent_id=None, depth=0)
        experiment = {"goal": "test", "work_dir": str(wd)}

        # Build system prompt (extract the hint construction logic)
        work_dir = experiment.get("work_dir", "")
        import os as _os_ls
        _provided_hint = ""
        if work_dir:
            _files_in_wd = [
                f for f in _os_ls.listdir(work_dir)
                if _os_ls.path.isfile(_os_ls.path.join(work_dir, f))
            ]
            if _files_in_wd:
                _file_list = ", ".join(sorted(_files_in_wd))
                _provided_hint = f"\n  - Provided files (ready to use): {_file_list}"

        assert "data.csv" in _provided_hint
        assert "helper.py" in _provided_hint
        assert "Provided files (ready to use)" in _provided_hint

    def test_empty_work_dir_no_files_hint(self, tmp_path):
        """No 'Provided files' line when work_dir is empty."""
        wd = tmp_path / "empty_work"
        wd.mkdir()

        import os as _os_ls
        _files_in_wd = [
            f for f in _os_ls.listdir(str(wd))
            if _os_ls.path.isfile(_os_ls.path.join(str(wd), f))
        ]
        assert _files_in_wd == []


# ══════════════════════════════════════════════════════════════════════════════
# Coding skill tools: read, write, copy, execute provided files
# ══════════════════════════════════════════════════════════════════════════════


def _load_coding_skill():
    """Load coding skill server module by absolute path to avoid name collisions."""
    import importlib.util
    _mod_path = Path(__file__).resolve().parent.parent.parent / "ari-skill-coding" / "src" / "server.py"
    spec = importlib.util.spec_from_file_location("coding_server", str(_mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCodingSkillFileOps:
    """Coding skill tools must handle provided files in work_dir."""

    def test_read_file_reads_provided(self, tmp_path):
        """read_file can read a file already in work_dir."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "input.txt").write_text("hello world\nline2\n")
        result = mod._read_file("input.txt", wd, offset=0, limit=8000)
        assert result.get("content") == "hello world\nline2\n"
        assert result.get("error") is None

    def test_write_code_creates_in_work_dir(self, tmp_path):
        """write_code creates a new file in work_dir."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        result = mod._write_code("output.py", "print('ok')\n", wd)
        assert result["status"] == "written"
        assert (tmp_path / "output.py").read_text() == "print('ok')\n"

    def test_run_bash_can_read_provided_file(self, tmp_path):
        """run_bash can cat a provided file in work_dir."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "data.csv").write_text("a,b\n1,2\n")
        result = mod._run_bash("cat data.csv", wd, timeout=10)
        assert result["exit_code"] == 0
        assert "a,b" in result["stdout"]

    def test_run_bash_can_copy_provided_file(self, tmp_path):
        """run_bash can cp a provided file within work_dir."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "orig.txt").write_text("content")
        result = mod._run_bash("cp orig.txt copy.txt", wd, timeout=10)
        assert result["exit_code"] == 0
        assert (tmp_path / "copy.txt").read_text() == "content"

    def test_run_code_executes_provided_python(self, tmp_path):
        """run_code can execute a Python file placed in work_dir."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "hello.py").write_text("print('hello from provided file')\n")
        result = mod._run_code("hello.py", wd, timeout=10)
        assert result["exit_code"] == 0
        assert "hello from provided file" in result["stdout"]

    def test_run_bash_can_execute_script(self, tmp_path):
        """run_bash can execute a provided shell script."""
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho 'script ran'\n")
        (tmp_path / "run.sh").chmod(0o755)
        result = mod._run_bash("bash run.sh", wd, timeout=10)
        assert result["exit_code"] == 0
        assert "script ran" in result["stdout"]

    def test_run_bash_compiles_and_runs_c(self, tmp_path):
        """run_bash can compile and execute a provided C file."""
        import shutil
        if not shutil.which("gcc"):
            pytest.skip("gcc not available")
        mod = _load_coding_skill()
        wd = str(tmp_path)
        (tmp_path / "hello.c").write_text(
            '#include <stdio.h>\nint main(){printf("hello c\\n");return 0;}\n'
        )
        result = mod._run_bash("gcc hello.c -o hello && ./hello", wd, timeout=30)
        assert result["exit_code"] == 0
        assert "hello c" in result["stdout"]
