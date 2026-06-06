"""Tests for the VirSci-live (vendor-wrap) path — PLAN_virsci_live_wrap Phase 7.

Covers:
  1. ARI_IDEA_VIRSCI_* env contract helpers
  2. Auto-stubber import of the vendored VirSci (skips if heavy deps absent)
  3. snapshot.build_snapshot with mocked Semantic Scholar (corpus/index/adjacency/books)
  4. LivePlatform.reference_paper SPECTER2/keyword retrieval (offline)
  5. build_model_configs shim-config derivation
  6. _parse_idea normalisation
  7. server.generate_ideas real-path contract (9 keys, 0-1, descending, real_wrap)
  8. server.generate_ideas degrades to re-impl when the real path fails
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import server  # noqa: E402
import snapshot as snap_mod  # noqa: E402


# ── 1. env contract helpers ───────────────────────────────────────────────────

class TestEnvContract:
    def test_real_flag(self, monkeypatch):
        monkeypatch.delenv("ARI_IDEA_VIRSCI_REAL", raising=False)
        assert server._virsci_real() is False
        for val in ("1", "true", "YES", "on"):
            monkeypatch.setenv("ARI_IDEA_VIRSCI_REAL", val)
            assert server._virsci_real() is True
        monkeypatch.setenv("ARI_IDEA_VIRSCI_REAL", "0")
        assert server._virsci_real() is False

    def test_int_defaults_and_override(self, monkeypatch):
        for name, fn, default in [
            ("ARI_IDEA_VIRSCI_K", server._virsci_k, 7),
            ("ARI_IDEA_VIRSCI_TEAM_SIZE", server._virsci_team_size, 3),
            ("ARI_IDEA_VIRSCI_N_AUTHORS", server._virsci_n_authors, 16),
            ("ARI_IDEA_VIRSCI_N_PAPERS", server._virsci_n_papers, 800),
        ]:
            monkeypatch.delenv(name, raising=False)
            assert fn() == default
            monkeypatch.setenv(name, "5")
            assert fn() == 5
            monkeypatch.setenv(name, "garbage")
            assert fn() == default

    def test_max_teams_optional(self, monkeypatch):
        monkeypatch.delenv("ARI_IDEA_VIRSCI_MAX_TEAMS", raising=False)
        assert server._virsci_max_teams() is None
        monkeypatch.setenv("ARI_IDEA_VIRSCI_MAX_TEAMS", "4")
        assert server._virsci_max_teams() == 4


# ── 2. auto-stubber import ────────────────────────────────────────────────────

class TestVendorImport:
    def test_import_virsci(self):
        vr = pytest.importorskip("virsci_runtime")
        try:
            ag, Platform, Team, SciAgent, Msg = vr.import_virsci()
        except ImportError as e:
            pytest.skip(f"VirSci heavy deps unavailable: {e}")
        assert Platform.__name__ == "Platform"
        assert Team.__name__ == "Team"
        assert SciAgent.__name__ == "SciAgent"
        LivePlatform = vr.make_live_platform_cls()
        assert issubclass(LivePlatform, Platform)


# ── 3. snapshot build with mocked S2 ──────────────────────────────────────────

def _fake_s2_get(path, params, **kwargs):
    if path == "paper/search":
        if params.get("offset", 0) > 0:
            return {"data": [], "next": None}
        return {
            "data": [
                {
                    "paperId": "p1", "title": "GNN pretraining", "year": 2021,
                    "citationCount": 50, "abstract": "Contrastive GNN pretraining.",
                    "authors": [{"authorId": "a1", "name": "Alice"},
                                 {"authorId": "a2", "name": "Bob"}],
                    "embedding": {"model": "specter_v2", "vector": [0.1, 0.2, 0.3, 0.4]},
                },
                {
                    "paperId": "p2", "title": "Molecular benchmarks", "year": 2020,
                    "citationCount": 30, "abstract": "ADMET benchmark suite.",
                    "authors": [{"authorId": "a2", "name": "Bob"},
                                 {"authorId": "a3", "name": "Carol"}],
                    "embedding": {"model": "specter_v2", "vector": [0.3, 0.1, 0.5, 0.2]},
                },
                {
                    "paperId": "p3", "title": "No-embedding paper", "year": 2019,
                    "citationCount": 5, "abstract": "Kept for keyword fallback.",
                    "authors": [{"authorId": "a1", "name": "Alice"}],
                    "embedding": None,
                },
            ],
            "next": None,
        }
    if path.startswith("author/"):
        return {"data": [
            {"paperId": "p1", "title": "GNN pretraining", "abstract": "..."},
            {"paperId": "p2", "title": "Molecular benchmarks", "abstract": "..."},
        ]}
    return None


class TestSnapshot:
    def test_build_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(snap_mod, "_s2_get", _fake_s2_get)
        snap = snap_mod.build_snapshot("molecular GNN", tmp_path, n_authors=3, n_papers=10)

        # full corpus keeps all 3 papers; index keeps the 2 with embeddings
        assert len(snap.paper_dicts) == 3
        assert len(snap.corpus) == 2
        assert snap.embeddings is not None and snap.embeddings.shape == (2, 4)
        # L2-normalised rows
        norms = np.linalg.norm(snap.embeddings, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)

        # adjacency: square int, no zero rows (Laplacian smoothing)
        adj = np.loadtxt(str(snap.adjacency_path), dtype=int)
        assert adj.shape == (3, 3)
        assert (adj.sum(axis=1) > 0).all()
        assert (np.diag(adj) == 0).all()

        # author books + per-paper files materialised
        assert (snap.books_dir / "author_0.txt").exists()
        assert len(list(snap.papers_dir.glob("*.txt"))) == 3

        # faiss index aligns with corpus
        idx = snap.build_faiss_index()
        assert idx is not None and idx.ntotal == 2

    def test_n_authors_one_floored_to_two(self, tmp_path, monkeypatch):
        # Regression: n_authors=1 must NOT yield a 1x1 zero-row adjacency
        # (which makes select_coauthors' arr/sum(arr) divide by zero).
        monkeypatch.setattr(snap_mod, "_s2_get", _fake_s2_get)
        snap = snap_mod.build_snapshot("topic", tmp_path, n_authors=1, n_papers=10)
        adj = np.loadtxt(str(snap.adjacency_path), dtype=int)
        assert adj.shape == (2, 2)
        assert (adj.sum(axis=1) > 0).all()

    def test_snapshot_cache_reuse(self, tmp_path, monkeypatch):
        calls = {"n": 0}

        def counting_get(path, params, **kwargs):
            calls["n"] += 1
            return _fake_s2_get(path, params, **kwargs)

        monkeypatch.setattr(snap_mod, "_s2_get", counting_get)
        snap_mod.build_snapshot("topic x", tmp_path, n_authors=2, n_papers=10)
        first = calls["n"]
        assert first > 0
        # second build with same signature → served from cache, no new S2 calls
        snap2 = snap_mod.build_snapshot("topic x", tmp_path, n_authors=2, n_papers=10)
        assert calls["n"] == first
        assert len(snap2.corpus) == 2


# ── 4. LivePlatform.reference_paper (offline) ─────────────────────────────────

class TestLivePlatform:
    def _make_snapshot(self, tmp_path):
        base = tmp_path / "virsci_snapshot"
        (base / "books").mkdir(parents=True)
        for i, t in enumerate(["Alice: GNNs", "Bob: contrastive", "Carol: ADMET"]):
            (base / "books" / f"author_{i}.txt").write_text(f"You are {t}.")
        np.savetxt(base / "adjacency.txt", np.array([[0, 2, 1], [2, 0, 1], [1, 1, 0]], dtype=int), fmt="%d")
        corpus = [
            {"title": "GNN pretraining", "abstract": "contrastive graph pretraining", "year": 2021, "citation": 1},
            {"title": "ADMET benchmark", "abstract": "molecular property benchmark", "year": 2020, "citation": 2},
        ]
        return snap_mod.Snapshot(
            dir=base, n_authors=3, n_papers=2, specter2_dim=4,
            corpus=corpus, paper_dicts=corpus,
            embeddings=np.eye(2, 4, dtype="float32"), topic="t",
        )

    def test_reference_paper_keyword_fallback(self, tmp_path, monkeypatch):
        vr = pytest.importorskip("virsci_runtime")
        try:
            vr.import_virsci()
        except ImportError as e:
            pytest.skip(f"VirSci heavy deps unavailable: {e}")
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
        snap = self._make_snapshot(tmp_path)
        LivePlatform = vr.make_live_platform_cls()
        cfg = vr.build_model_configs("openai/claude-cli", "http://127.0.0.1:8900/v1")
        platform = LivePlatform(
            snap, cfg, group_max_discuss_iteration=1, max_teammember=2,
            cite_number=2, agent_num=3,
            log_dir=str(tmp_path / "logs"), info_dir=str(tmp_path / "info"),
            specter2_model="__force_keyword_fallback__",
        )
        ref, idxs = platform.reference_paper("graph contrastive pretraining", 2)
        assert isinstance(ref, str) and "Title:" in ref
        assert len(idxs) >= 1
        assert all(0 <= int(i) < len(snap.corpus) for i in idxs)


# ── 5. build_model_configs derivation ─────────────────────────────────────────

class TestModelConfigs:
    def test_litellm_routing(self):
        vr = pytest.importorskip("virsci_runtime")
        cfg = vr.build_model_configs("openai/claude-cli", "http://127.0.0.1:8900/v1")
        # litellm_chat so engine calls flow through litellm (cost_tracker-captured)
        assert cfg["model_type"] == "litellm_chat"
        assert cfg["model_name"] == "openai/claude-cli"   # provider prefix KEPT for litellm
        assert cfg["generate_args"]["api_base"] == "http://127.0.0.1:8900/v1"

    def test_api_base_passthrough(self):
        vr = pytest.importorskip("virsci_runtime")
        cfg = vr.build_model_configs("openai/m", "http://x:8900/v1")
        assert cfg["generate_args"]["api_base"] == "http://x:8900/v1"

    def test_no_base_url(self):
        vr = pytest.importorskip("virsci_runtime")
        cfg = vr.build_model_configs("openai/m", None)
        assert "generate_args" not in cfg


# ── 6. _parse_idea ────────────────────────────────────────────────────────────

class TestParseIdea:
    def test_json_idea(self):
        vr = pytest.importorskip("virsci_runtime")
        raw = json.dumps({
            "Title": "Mixed-precision GNN", "Idea": "Use fp8 in message passing.",
            "Experiment": "Benchmark on QM9.", "Novelty": 8, "Feasibility": 7, "Clarity": 9,
        })
        out = vr._parse_idea(raw)
        assert out["title"] == "Mixed-precision GNN"
        assert out["experiment_plan"] == "Benchmark on QM9."
        assert out["novelty_score"] == 0.8
        assert out["feasibility_score"] == 0.7
        assert out["clarity_score"] == 0.9

    def test_garbage_defaults(self):
        vr = pytest.importorskip("virsci_runtime")
        out = vr._parse_idea("not json, no metrics")
        assert 0 <= out["novelty_score"] <= 1
        assert out["title"]

    def test_empty(self):
        vr = pytest.importorskip("virsci_runtime")
        assert vr._parse_idea("") is None


# ── 7. server real-path contract ──────────────────────────────────────────────

_REAL_IDEAS = [
    {"title": "Idea High", "description": "d1", "novelty": "Novelty score: 9.0",
     "feasibility": "Feasibility score: 8.0", "experiment_plan": "e1",
     "novelty_score": 0.9, "feasibility_score": 0.8, "clarity_score": 0.7},
    {"title": "Idea Low", "description": "d2", "novelty": "Novelty score: 4.0",
     "feasibility": "Feasibility score: 5.0", "experiment_plan": "e2",
     "novelty_score": 0.4, "feasibility_score": 0.5, "clarity_score": 0.6},
]
_REAL_META = {"n_agents": 3, "discussion_rounds": 7, "teams_run": 1, "papers_indexed": 42}

_METRIC_JSON = json.dumps({"primary_metric": "rmse", "higher_is_better": False,
                            "metric_rationale": "regression error"})


class TestServerRealPath:
    @pytest.mark.asyncio
    async def test_real_wrap_contract(self, monkeypatch):
        monkeypatch.setenv("ARI_IDEA_VIRSCI_REAL", "1")
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        async def fake_real(topic, n_ideas, ancestor_block=""):
            return list(_REAL_IDEAS), dict(_REAL_META)
        with patch("server._run_real_virsci", side_effect=fake_real), \
             patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = ["Gap analysis.", _METRIC_JSON]
            result = await server.generate_ideas(
                topic="molecular property prediction", papers=[], n_ideas=2,
            )
        # status + provenance reflect the real path / vendor values
        assert result["virsci_integration_status"] == "real_wrap"
        assert result["n_agents"] == 3
        assert result["discussion_rounds"] == 7
        assert result["papers_analyzed"] == 42
        # 9-key idea contract, 0-1 scores, descending overall
        ideas = result["ideas"]
        assert len(ideas) == 2
        for idea in ideas:
            for key in ["title", "description", "novelty", "feasibility",
                         "experiment_plan", "novelty_score", "feasibility_score",
                         "overall_score"]:
                assert key in idea
            assert 0 <= idea["novelty_score"] <= 1
            assert 0 <= idea["overall_score"] <= 1
        assert ideas[0]["overall_score"] >= ideas[1]["overall_score"]
        assert ideas[0]["title"] == "Idea High"

    @pytest.mark.asyncio
    async def test_degrades_to_reimpl_on_failure(self, monkeypatch):
        monkeypatch.setenv("ARI_IDEA_VIRSCI_REAL", "1")
        monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
        async def boom(topic, n_ideas, ancestor_block=""):
            raise RuntimeError("snapshot build failed")
        idea_json = json.dumps({
            "Title": "Fallback Idea", "Idea": "x", "Experiment": "y",
            "Novelty": 6, "Feasibility": 6, "Clarity": 6,
        })
        with patch("server._run_real_virsci", side_effect=boom), \
             patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            # gap, then 1 idea × 2 agents (reimpl loop), then metric
            mock_llm.side_effect = ["Gap.", idea_json, idea_json, _METRIC_JSON]
            result = await server.generate_ideas(
                topic="t", papers=[{"title": "P", "abstract": "A", "year": 2020}],
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert result["virsci_integration_status"].startswith("reimpl")
        assert len(result["ideas"]) >= 1
