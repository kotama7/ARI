"""Tests for ari.paths.PathManager — centralised path management."""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.paths import PathManager, RuntimePathResolver


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



# ── env-driven helpers (PR-1A) ────────────────────────────────────────────


class TestEnvHelpers:
    def test_checkpoint_dir_from_env_unset(self, monkeypatch):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        assert PathManager.checkpoint_dir_from_env() is None

    def test_checkpoint_dir_from_env_blank(self, monkeypatch):
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", "   ")
        assert PathManager.checkpoint_dir_from_env() is None

    def test_checkpoint_dir_from_env_returns_path(self, monkeypatch, tmp_path):
        ck = tmp_path / "checkpoints" / "abc"
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ck))
        out = PathManager.checkpoint_dir_from_env()
        assert isinstance(out, Path)
        assert str(out) == str(ck)

    def test_from_env_unset_falls_back_to_cwd(self, monkeypatch):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        pm = PathManager.from_env()
        assert pm.root == Path(".").resolve()

    def test_from_env_with_checkpoint_dir_infers_workspace(self, monkeypatch, tmp_path):
        ck = tmp_path / "checkpoints" / "run1"
        ck.mkdir(parents=True)
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ck))
        pm = PathManager.from_env()
        # workspace_root is the parent of the outermost checkpoints/ dir.
        assert pm.root == tmp_path.resolve()
        assert pm.checkpoint_dir("run1") == ck.resolve()


# ── RuntimePathResolver (subtask 006) ─────────────────────────────────────


class TestResolverConstruction:
    def test_default_root_is_cwd(self):
        r = RuntimePathResolver()
        assert r.root == Path(".").resolve()

    def test_custom_root(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.root == tmp_path.resolve()

    def test_repr(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert "RuntimePathResolver" in repr(r)
        assert str(tmp_path.resolve()) in repr(r)

    def test_runs_root(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.runs_root == tmp_path.resolve() / "runs"

    def test_run_dir(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.run_dir("run1") == tmp_path.resolve() / "runs" / "run1"


class TestFacadeDelegationParity:
    """PathManager is a thin facade — its flat-layout return values must be
    byte-identical to the underlying resolver's."""

    def test_pathmanager_holds_resolver(self, tmp_path):
        pm = PathManager(tmp_path)
        assert isinstance(pm.resolver, RuntimePathResolver)
        assert pm.resolver.root == pm.root

    def test_flat_roots_match_resolver(self, tmp_path):
        pm = PathManager(tmp_path)
        r = pm.resolver
        assert pm.root == r.root
        assert pm.checkpoints_root == r.checkpoints_root
        assert pm.experiments_root == r.experiments_root
        assert pm.staging_root == r.staging_root
        assert pm.paper_registry_root == r.paper_registry_root
        assert pm.runs_root == r.runs_root

    def test_flat_per_run_paths_match_resolver(self, tmp_path):
        pm = PathManager(tmp_path)
        r = pm.resolver
        for run_id in ("run1", "20260414_topic"):
            assert pm.checkpoint_dir(run_id) == r.checkpoint_dir(run_id)
            assert pm.log_dir(run_id) == r.log_dir(run_id)
            assert pm.log_file(run_id) == r.log_file(run_id)
            assert pm.uploads_dir(run_id) == r.uploads_dir(run_id)
            assert pm.cost_trace(run_id) == r.cost_trace(run_id)
            assert pm.cost_summary(run_id) == r.cost_summary(run_id)
            assert pm.idea_file(run_id) == r.idea_file(run_id)
            assert pm.node_work_dir(run_id, "n1") == r.node_work_dir(run_id, "n1")

    def test_flat_checkpoint_dir_value_unchanged(self, tmp_path):
        """The single most load-bearing flat path is exactly as before."""
        pm = PathManager(tmp_path)
        assert pm.checkpoint_dir("r") == tmp_path.resolve() / "checkpoints" / "r"


class TestResolveWorkspaceRoot:
    """resolve_workspace_root implements 004's 'workspace/ wins' policy."""

    def test_checkpoint_dir_env_wins(self, monkeypatch, tmp_path):
        ck = tmp_path / "checkpoints" / "run1"
        ck.mkdir(parents=True)
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ck))
        assert RuntimePathResolver.resolve_workspace_root() == tmp_path.resolve()

    def test_explicit_arg_second(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        assert (
            RuntimePathResolver.resolve_workspace_root(tmp_path)
            == tmp_path.resolve()
        )

    def test_ari_root_env_third(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        monkeypatch.setenv("ARI_ROOT", str(tmp_path))
        out = RuntimePathResolver.resolve_workspace_root()
        assert out == (tmp_path / "workspace").resolve()

    def test_repo_root_workspace_fallback(self, monkeypatch):
        """Inside the ARI checkout, falls back to {repo_root}/workspace."""
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        monkeypatch.delenv("ARI_ROOT", raising=False)
        out = RuntimePathResolver.resolve_workspace_root()
        # This test module lives inside the repo, so repo_root/ari-core exists.
        assert out.name == "workspace"


class TestBucketClassification:
    @pytest.mark.parametrize("name,bucket", [
        ("tree.json", "checkpoints"),
        ("meta.json", "checkpoints"),
        ("ari.log", "checkpoints"),
        ("cost_trace.jsonl", "traces"),
        ("viz_access.jsonl", "traces"),
        ("memory_access.20260101.jsonl", "traces"),
        ("node_report.json", "reports"),
        ("reproducibility_report.json", "reports"),
        ("ors_novelty.json", "reports"),
        ("fig_loss.png", "artifacts"),
        ("full_paper.tex", "artifacts"),
        ("refs.bib", "artifacts"),
    ])
    def test_bucket_for(self, name, bucket):
        assert RuntimePathResolver.bucket_for(name) == bucket


class TestDualLayoutFileResolution:
    def test_checkpoint_file_flat_when_no_bucket(self, tmp_path):
        """With no bucketed layout on disk, resolves the flat path."""
        r = RuntimePathResolver(tmp_path)
        out = r.checkpoint_file("run1", "tree.json")
        assert out == tmp_path.resolve() / "checkpoints" / "run1" / "tree.json"

    def test_checkpoint_file_prefers_bucket(self, tmp_path):
        """Given runs/<id>/checkpoints/tree.json on disk, prefers the bucket."""
        r = RuntimePathResolver(tmp_path)
        bucketed = tmp_path / "runs" / "run1" / "checkpoints"
        bucketed.mkdir(parents=True)
        (bucketed / "tree.json").write_text("{}")
        out = r.checkpoint_file("run1", "tree.json")
        assert out == bucketed / "tree.json"
        assert out.parent.name == "checkpoints"
        assert out.parent.parent.name == "run1"

    def test_checkpoint_file_scans_other_buckets(self, tmp_path):
        """A file placed in a non-primary bucket is still found before flat."""
        r = RuntimePathResolver(tmp_path)
        traces = tmp_path / "runs" / "run1" / "traces"
        traces.mkdir(parents=True)
        (traces / "cost_trace.jsonl").write_text("")
        out = r.checkpoint_file("run1", "cost_trace.jsonl")
        assert out == traces / "cost_trace.jsonl"

    def test_checkpoint_file_via_pathmanager(self, tmp_path):
        pm = PathManager(tmp_path)
        # Flat fallback (no bucket) matches the historical flat file path.
        assert (
            pm.checkpoint_file("run1", "results.json")
            == pm.checkpoint_dir("run1") / "results.json"
        )


class TestBucketAccessorsGracefulDegradation:
    def test_artifacts_dir_falls_back_to_flat(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.artifacts_dir("run1") == r.checkpoint_dir("run1")

    def test_traces_dir_falls_back_to_flat(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.traces_dir("run1") == r.checkpoint_dir("run1")

    def test_reports_dir_falls_back_to_flat(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.reports_dir("run1") == r.checkpoint_dir("run1")

    def test_artifacts_dir_uses_bucket_when_present(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        bucket = tmp_path / "runs" / "run1" / "artifacts"
        bucket.mkdir(parents=True)
        assert r.artifacts_dir("run1") == bucket

    def test_workspace_dir_falls_back_to_experiments(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        assert r.workspace_dir("run1", "n1") == r.node_work_dir("run1", "n1")

    def test_workspace_dir_uses_bucket_when_present(self, tmp_path):
        r = RuntimePathResolver(tmp_path)
        ws = tmp_path / "runs" / "run1" / "workspace"
        ws.mkdir(parents=True)
        assert r.workspace_dir("run1", "n1") == ws / "n1"

    def test_pathmanager_bucket_accessors_delegate(self, tmp_path):
        pm = PathManager(tmp_path)
        assert pm.artifacts_dir("r") == pm.resolver.artifacts_dir("r")
        assert pm.traces_dir("r") == pm.resolver.traces_dir("r")
        assert pm.reports_dir("r") == pm.resolver.reports_dir("r")
        assert pm.workspace_dir("r", "n") == pm.resolver.workspace_dir("r", "n")
        assert pm.run_dir("r") == pm.resolver.run_dir("r")


class TestResolverEnvHelpers:
    def test_checkpoint_dir_from_env_parity(self, monkeypatch, tmp_path):
        ck = tmp_path / "checkpoints" / "abc"
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ck))
        assert (
            RuntimePathResolver.checkpoint_dir_from_env()
            == PathManager.checkpoint_dir_from_env()
        )

    def test_set_checkpoint_dir_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        RuntimePathResolver.set_checkpoint_dir_env(tmp_path / "ck")
        assert PathManager.checkpoint_dir_from_env() == (tmp_path / "ck")

    def test_from_checkpoint_dir_parity_with_pathmanager(self, tmp_path):
        ck = tmp_path / "checkpoints" / "run1"
        ck.mkdir(parents=True)
        r = RuntimePathResolver.from_checkpoint_dir(ck)
        pm = PathManager.from_checkpoint_dir(ck)
        assert r.root == pm.root == tmp_path.resolve()

    def test_from_env_falls_back_to_cwd(self, monkeypatch):
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        assert RuntimePathResolver.from_env().root == Path(".").resolve()
