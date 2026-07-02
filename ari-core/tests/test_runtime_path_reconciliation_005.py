"""Subtask 005 — workspace-root reconciliation ("workspace/ wins", 004 P2).

These tests pin the single reconciliation this subtask lands on top of the
already-committed ``RuntimePathResolver`` (subtask 006): the checkpoint/log
default root now spells the **same canonical workspace root** everywhere —
``auto_config()`` (routed through the resolver SSOT), the Pydantic field
defaults, and the shipped ``config/default.yaml`` — while the legacy relative
``./checkpoints/{run_id}/`` form stays fully resolvable for back-compat.

Scope guardrails honoured here:

* ``PathManager`` flat-layout return values are UNCHANGED (see test_paths.py).
* New runs still write the **flat** layout; the bucketed ``runs/<id>/`` write
  path is deferred (would break the frozen flat pins) — see the subtask report.
* Existing flat checkpoints keep resolving via ``from_checkpoint_dir`` /
  ``ARI_CHECKPOINT_DIR`` (unchanged).
"""

from __future__ import annotations

import tempfile

import yaml

from ari.config import (
    CheckpointConfig,
    LoggingConfig,
    auto_config,
    load_config,
)
from ari.config.finder import package_config_root
from ari.paths import PathManager, RuntimePathResolver


def _clear_path_env(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ARI_LOG_DIR", raising=False)
    monkeypatch.delenv("ARI_ROOT", raising=False)


def _write_yaml(data: dict) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        return f.name


# ── canonical root: workspace/ wins (004 P2) ──────────────────────────────


class TestWorkspaceRootWins:
    def test_checkpoint_config_default_roots_under_workspace(self):
        """The Pydantic default now roots under workspace/ (was ./checkpoints/)."""
        cc = CheckpointConfig()
        assert cc.dir == "./workspace/checkpoints/{run_id}/"
        assert "{run_id}" in cc.dir

    def test_logging_config_default_roots_under_workspace(self):
        lc = LoggingConfig()
        assert lc.dir == "./workspace/checkpoints/{run_id}/"
        assert "{run_id}" in lc.dir

    def test_shipped_default_yaml_roots_under_workspace(self):
        """The shipped config/default.yaml no longer disagrees with auto_config."""
        raw = yaml.safe_load((package_config_root() / "default.yaml").read_text())
        assert raw["checkpoint"]["dir"] == "./workspace/checkpoints/{run_id}/"
        assert raw["logging"]["dir"] == "./workspace/checkpoints/{run_id}/"


# ── auto_config is reconciled through the resolver SSOT ────────────────────


class TestAutoConfigThroughResolver:
    def test_auto_config_checkpoint_dir_matches_resolver(self, monkeypatch):
        """auto_config()'s checkpoint dir is sourced from the single owner
        (RuntimePathResolver.resolve_workspace_root) — no duplicated policy."""
        _clear_path_env(monkeypatch)
        cfg = auto_config()
        expected = str(
            RuntimePathResolver.resolve_workspace_root() / "checkpoints" / "{run_id}"
        )
        assert cfg.checkpoint.dir == expected
        assert cfg.logging.dir == expected  # logs follow checkpoint when ARI_LOG_DIR unset

    def test_auto_config_roots_under_workspace_in_checkout(self, monkeypatch):
        """Running inside the ARI checkout, the fallback lands under workspace/."""
        _clear_path_env(monkeypatch)
        cfg = auto_config()
        # Resolver returns {repo_root}/workspace inside the checkout.
        assert cfg.checkpoint.dir.replace("\\", "/").endswith(
            "workspace/checkpoints/{run_id}"
        )

    def test_auto_config_honours_ari_root(self, monkeypatch, tmp_path):
        """Reconciliation adds ARI_ROOT honouring (resolver precedence tier 3)."""
        _clear_path_env(monkeypatch)
        monkeypatch.setenv("ARI_ROOT", str(tmp_path))
        cfg = auto_config()
        assert cfg.checkpoint.dir == str(
            (tmp_path / "workspace" / "checkpoints" / "{run_id}").resolve()
        )

    def test_ari_checkpoint_dir_env_still_wins(self, monkeypatch, tmp_path):
        """Explicit env pin overrides the reconciled default (unchanged contract)."""
        _clear_path_env(monkeypatch)
        target = str(tmp_path / "gui_ckpt")
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", target)
        cfg = auto_config()
        assert cfg.checkpoint.dir == target
        assert "{run_id}" not in cfg.checkpoint.dir


# ── back-compat: legacy relative form stays resolvable ─────────────────────


class TestLegacyFormResolvable:
    def test_legacy_relative_checkpoint_dir_preserved(self, monkeypatch):
        """A config that still spells ./checkpoints/{run_id}/ loads unchanged."""
        _clear_path_env(monkeypatch)
        fpath = _write_yaml({
            "llm": {"backend": "openai", "model": "gpt-4o"},
            "checkpoint": {"dir": "./checkpoints/{run_id}/"},
        })
        cfg = load_config(fpath)
        assert cfg.checkpoint.dir == "./checkpoints/{run_id}/"

    def test_existing_flat_checkpoint_still_recovers_root(self, tmp_path):
        """An existing flat checkpoints/<id>/ dir still recovers its workspace
        root regardless of the new default (from_checkpoint_dir unchanged)."""
        ckpt = tmp_path / "checkpoints" / "20260414_legacy"
        ckpt.mkdir(parents=True)
        pm = PathManager.from_checkpoint_dir(ckpt)
        assert pm.root == tmp_path.resolve()
        assert pm.checkpoint_dir("20260414_legacy") == ckpt.resolve()

    def test_env_pin_recovers_root_from_workspace_layout(self, monkeypatch, tmp_path):
        """A workspace/checkpoints/<id>/ pin recovers workspace/ as the root."""
        _clear_path_env(monkeypatch)
        ckpt = tmp_path / "workspace" / "checkpoints" / "20260414_run"
        ckpt.mkdir(parents=True)
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
        pm = PathManager.from_env()
        assert pm.root == (tmp_path / "workspace").resolve()
