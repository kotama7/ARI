"""Tests for ari.paths.PathManager — centralised path management."""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.paths import PathManager


# ── basic construction ────────────────────────────────────────────────────


class TestConstruction:
    def test_default_root_is_cwd(self):
        pm = PathManager()
        assert pm.root == Path(".").resolve()

    def test_custom_root(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.root == tmp_path.resolve()

    def test_repr(self, tmp_path):
        pm = PathManager(tmp_path)
        assert "PathManager" in repr(pm)
        assert str(tmp_path.resolve()) in repr(pm)


# ── directory layout ──────────────────────────────────────────────────────


class TestDirectoryLayout:
    def test_checkpoints_root(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.checkpoints_root == tmp_path.resolve() / "checkpoints"

    def test_experiments_root(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.experiments_root == tmp_path.resolve() / "experiments"

    def test_staging_root(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.staging_root == tmp_path.resolve() / "staging"

    def test_checkpoint_dir(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.checkpoint_dir("20260414_test")
        assert d == tmp_path.resolve() / "checkpoints" / "20260414_test"

    def test_log_dir_equals_checkpoint_dir(self, tmp_path):
        """Logs live inside the checkpoint dir — not a separate tree."""
        pm = PathManager(tmp_path)
        assert pm.log_dir("run1") == pm.checkpoint_dir("run1")

    def test_log_file(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.log_file("run1") == pm.checkpoint_dir("run1") / "ari.log"

    def test_uploads_dir(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.uploads_dir("run1") == pm.checkpoint_dir("run1") / "uploads"

    def test_cost_trace(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.cost_trace("run1").name == "cost_trace.jsonl"

    def test_cost_summary(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.cost_summary("run1").name == "cost_summary.json"

    def test_idea_file(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.idea_file("run1").name == "idea.json"

    def test_node_work_dir(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.node_work_dir("my_exp", "node_abc")
        assert d == tmp_path.resolve() / "experiments" / "my_exp" / "node_abc"


# ── ensure (mkdir) helpers ────────────────────────────────────────────────


class TestEnsure:
    def test_ensure_checkpoint_creates(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.ensure_checkpoint("run42")
        assert d.is_dir()
        assert d == pm.checkpoint_dir("run42")

    def test_ensure_checkpoint_idempotent(self, tmp_path):
        pm = PathManager(tmp_path)
        d1 = pm.ensure_checkpoint("run42")
        d2 = pm.ensure_checkpoint("run42")
        assert d1 == d2

    def test_ensure_uploads_creates(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.ensure_uploads("run42")
        assert d.is_dir()
        assert d.name == "uploads"

    def test_ensure_node_work_dir_creates(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.ensure_node_work_dir("slug", "node1")
        assert d.is_dir()
        assert d == pm.node_work_dir("slug", "node1")


# ── staging ───────────────────────────────────────────────────────────────


class TestStaging:
    def test_new_staging_dir_creates(self, tmp_path):
        pm = PathManager(tmp_path)
        d = pm.new_staging_dir()
        assert d.is_dir()
        assert d.parent == pm.staging_root

    def test_new_staging_dir_unique(self, tmp_path):
        """Two calls in the same second still produce valid dirs."""
        pm = PathManager(tmp_path)
        d1 = pm.new_staging_dir()
        d2 = pm.new_staging_dir()
        # Even if same timestamp, both should exist (mkdir exist_ok=True)
        assert d1.is_dir()
        assert d2.is_dir()


# ── project-scoped paths (no global ~/.ari anymore) ───────────────────────


class TestProjectScopedPaths:
    def test_project_settings_path(self, tmp_path):
        ckpt = tmp_path / "checkpoints" / "abc"
        assert PathManager.project_settings_path(ckpt) == ckpt / "settings.json"

    def test_project_memory_path(self, tmp_path):
        ckpt = tmp_path / "checkpoints" / "abc"
        assert PathManager.project_memory_path(ckpt) == ckpt / "memory.json"

    def test_no_global_ari_home_attribute(self):
        """ari_home / settings_path / memory_path must be removed."""
        assert not hasattr(PathManager, "ari_home")
        assert not hasattr(PathManager, "settings_path")
        assert not hasattr(PathManager, "memory_path")
        assert not hasattr(PathManager, "global_settings_path")


# ── is_meta_file ──────────────────────────────────────────────────────────


class TestIsMetaFile:
    @pytest.mark.parametrize("name", [
        "experiment.md",
        "launch_config.json",
        "meta.json",
        "tree.json",
        "nodes_tree.json",
        "results.json",
        "idea.json",
        "cost_trace.jsonl",
        "cost_summary.json",
        "ari.log",
        ".ari_pid",
        ".pipeline_started",
        "evaluation_criteria.json",
    ])
    def test_meta_files_detected(self, name):
        assert PathManager.is_meta_file(name)

    @pytest.mark.parametrize("name", [
        "ari_run_12345.log",  # .log extension
        "debug.log",
    ])
    def test_log_extension_detected(self, name):
        assert PathManager.is_meta_file(name)

    @pytest.mark.parametrize("name", [
        "data.csv",
        "script.py",
        "input.txt",
        "model.pkl",
    ])
    def test_user_files_not_meta(self, name):
        assert not PathManager.is_meta_file(name)


# ── slugify ───────────────────────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert PathManager.slugify("Hello World!") == "Hello_World"

    def test_max_len(self):
        long = "a" * 100
        assert len(PathManager.slugify(long)) <= 40

    def test_custom_max_len(self):
        assert len(PathManager.slugify("a" * 100, max_len=20)) <= 20

    def test_collapses_underscores(self):
        assert "__" not in PathManager.slugify("a!!!b")

    def test_strips_leading_trailing(self):
        result = PathManager.slugify("...test...")
        assert not result.startswith("_")


# ── from_checkpoint_dir ───────────────────────────────────────────────────


class TestFromCheckpointDir:
    def test_standard_layout(self, tmp_path):
        """workspace/checkpoints/run_id → infer workspace as root."""
        ckpt = tmp_path / "checkpoints" / "20260414_test"
        ckpt.mkdir(parents=True)
        pm = PathManager.from_checkpoint_dir(ckpt)
        assert pm.root == tmp_path.resolve()

    def test_nested_checkpoints(self, tmp_path):
        """Finds outermost checkpoints/ — avoids nesting."""
        deep = tmp_path / "workspace" / "checkpoints" / "checkpoints" / "run1"
        deep.mkdir(parents=True)
        pm = PathManager.from_checkpoint_dir(deep)
        # Should find the outermost "checkpoints" whose parent is "workspace"
        assert pm.root == (tmp_path / "workspace").resolve()

    def test_no_checkpoints_ancestor(self, tmp_path):
        """Fallback: checkpoint_dir.parent becomes root."""
        ckpt = tmp_path / "custom" / "run1"
        ckpt.mkdir(parents=True)
        pm = PathManager.from_checkpoint_dir(ckpt)
        assert pm.root == (tmp_path / "custom").resolve()

    def test_inferred_paths_match(self, tmp_path):
        """After inference, paths are consistent."""
        workspace = tmp_path / "workspace"
        ckpt = workspace / "checkpoints" / "run_42"
        ckpt.mkdir(parents=True)
        pm = PathManager.from_checkpoint_dir(ckpt)
        assert pm.checkpoints_root == workspace.resolve() / "checkpoints"
        assert pm.experiments_root == workspace.resolve() / "experiments"


# ── integration: end-to-end layout creation ───────────────────────────────


class TestIntegration:
    def test_full_layout_creation(self, tmp_path):
        """Create a full experiment layout and verify structure."""
        pm = PathManager(tmp_path)
        run_id = "20260414_optimize_loss"

        # Create all directories
        ckpt = pm.ensure_checkpoint(run_id)
        uploads = pm.ensure_uploads(run_id)
        slug = PathManager.slugify("optimize_loss")
        wd1 = pm.ensure_node_work_dir(slug, "node_root")
        wd2 = pm.ensure_node_work_dir(slug, "node_child_1")

        # Verify everything is under the same root
        assert ckpt.is_dir()
        assert uploads.is_dir()
        assert wd1.is_dir()
        assert wd2.is_dir()

        # Verify layout
        assert (tmp_path / "checkpoints" / run_id).exists()
        assert (tmp_path / "checkpoints" / run_id / "uploads").exists()
        assert (tmp_path / "experiments" / slug / "node_root").exists()
        assert (tmp_path / "experiments" / slug / "node_child_1").exists()

    def test_from_checkpoint_roundtrip(self, tmp_path):
        """Create with PathManager, then reconstruct from checkpoint_dir."""
        pm1 = PathManager(tmp_path)
        ckpt = pm1.ensure_checkpoint("run1")

        pm2 = PathManager.from_checkpoint_dir(ckpt)
        assert pm2.root == pm1.root
        assert pm2.checkpoint_dir("run1") == ckpt
        assert pm2.experiments_root == pm1.experiments_root

    def test_same_topic_runs_do_not_collide(self, tmp_path):
        """Two runs with identical topics must land in separate buckets.

        Prior to keying experiments/ by run_id, both runs shared a slug
        bucket, so two child nodes that happened to generate the same
        8-hex UUID suffix would silently reuse the same work dir.
        """
        pm = PathManager(tmp_path)
        run_a = "20260415000000_shared_topic"
        run_b = "20260415010000_shared_topic"

        wd_a = pm.ensure_node_work_dir(run_a, "node_abcdef01")
        wd_b = pm.ensure_node_work_dir(run_b, "node_abcdef01")

        # Same node_id ends up in two physically distinct directories
        assert wd_a != wd_b
        assert wd_a.parent.name == run_a
        assert wd_b.parent.name == run_b

        # Writes in one bucket are invisible to the other
        (wd_a / "artifact.txt").write_text("from run A")
        assert not (wd_b / "artifact.txt").exists()

    def test_meta_file_not_copied(self, tmp_path):
        """Simulate Plan B: only user files are copied to node work dirs."""
        pm = PathManager(tmp_path)
        ckpt = pm.ensure_checkpoint("run1")

        # Place files in checkpoint
        (ckpt / "data.csv").write_text("a,b\n1,2\n")
        (ckpt / "script.py").write_text("print(1)\n")
        (ckpt / "experiment.md").write_text("## Goal\nTest\n")
        (ckpt / "tree.json").write_text("{}")
        (ckpt / "ari_run_123.log").write_text("log line\n")

        # Copy user files to node work dir (as cli.py does)
        wd = pm.ensure_node_work_dir("test", "node1")
        import shutil
        for f in ckpt.iterdir():
            if f.is_file() and not PathManager.is_meta_file(f.name):
                dst = wd / f.name
                if not dst.exists():
                    shutil.copy2(str(f), str(dst))

        # User files present
        assert (wd / "data.csv").exists()
        assert (wd / "script.py").exists()
        # Meta files not present
        assert not (wd / "experiment.md").exists()
        assert not (wd / "tree.json").exists()
        assert not (wd / "ari_run_123.log").exists()
