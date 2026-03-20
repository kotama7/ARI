"""
Tests for VirSci-inspired idea generation MCP skill.
Covers: retrieval, agent discussion loop, idea ranking, fallback.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / "src"))

# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_PAPERS = [
    {"title": "Fast Matrix Multiply", "abstract": "A fast approach using SIMD.", "year": 2023, "citationCount": 42, "paperId": "abc123", "url": ""},
    {"title": "Error-Compensated GEMM", "abstract": "Neumaier compensation for FP32.", "year": 2022, "citationCount": 15, "paperId": "def456", "url": ""},
]

MOCK_S2_RAW = [
    {"title": "Fast Matrix Multiply", "abstract": "A fast approach.", "year": 2023, "citationCount": 42, "paperId": "abc123"},
    {"title": "Error-Compensated GEMM", "abstract": "Neumaier.", "year": 2022, "citationCount": 15, "paperId": "def456"},
]

MOCK_IDEA_JSON = json.dumps({
    "title": "Adaptive Precision GEMM",
    "description": "Uses mixed precision with error tracking.",
    "novelty": "Combines FP16 and FP32 dynamically.",
    "feasibility": "Implementable with OpenMP.",
    "experiment_plan": "1. Implement. 2. Benchmark. 3. Compare."
})

MOCK_SCORE_JSON = json.dumps({
    "novelty_score": 8,
    "feasibility_score": 7,
    "relevance_score": 9,
    "rationale": "Strong novelty."
})

MOCK_METRIC_JSON = json.dumps({
    "primary_metric": "max_relative_error",
    "higher_is_better": False,
    "metric_rationale": "Measures accuracy vs FP64 reference."
})

# ── survey() tests ─────────────────────────────────────────────────────────────

class TestSurvey:
    def test_survey_returns_papers(self):
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("FP32 GEMM accuracy", max_papers=5)
        assert "papers" in result
        assert len(result["papers"]) >= 1
        assert all("title" in p for p in result["papers"])

    def test_survey_respects_max_papers(self):
        large = [{"title": f"Paper {i}", "abstract": "", "year": 2020, "citationCount": i, "paperId": f"id{i}"} for i in range(20)]
        with patch("server._s2_search", return_value=large), \
             patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("topic", max_papers=5)
        assert len(result["papers"]) <= 5

    def test_survey_fallback_on_s2_failure(self):
        mock_sch_paper = MagicMock()
        mock_sch_paper.title = "Fallback Paper"
        mock_sch_paper.abstract = "Abstract."
        mock_sch_paper.year = 2021
        mock_sch_paper.citationCount = 3
        mock_sch_paper.paperId = "fb001"
        mock_sch_paper.url = ""
        with patch("server._s2_search", return_value=[]), \
             patch("server.SemanticScholar") as MockSch:
            MockSch.return_value.search_paper.return_value = [mock_sch_paper]
            with patch("server._s2_citations", return_value=[]):
                import server
                result = server.survey("topic", max_papers=5)
        assert "papers" in result
        assert any(p["title"] == "Fallback Paper" for p in result["papers"])

    def test_survey_handles_both_sources_unavailable(self):
        with patch("server._s2_search", return_value=[]), \
             patch("server.SemanticScholar") as MockSch:
            MockSch.return_value.search_paper.side_effect = Exception("network error")
            import server
            result = server.survey("topic", max_papers=5)
        assert "papers" in result
        # Should return empty, not raise
        assert isinstance(result["papers"], list)

    def test_survey_deduplicates_titles(self):
        dupe = MOCK_S2_RAW + [{"title": "Fast Matrix Multiply", "abstract": "dup", "year": 2023, "citationCount": 1, "paperId": "dup1"}]
        with patch("server._s2_search", return_value=dupe), \
             patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("topic", max_papers=10)
        titles = [p["title"] for p in result["papers"]]
        assert len(titles) == len(set(titles))

    def test_survey_enriches_with_citations(self):
        cite_paper = {"title": "Citation Paper", "abstract": "ref.", "year": 2021, "citationCount": 5, "paperId": "cit001"}
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[cite_paper]):
            import server
            result = server.survey("topic", max_papers=15)
        titles = [p["title"] for p in result["papers"]]
        assert "Citation Paper" in titles


# ── generate_ideas() tests ────────────────────────────────────────────────────

class TestGenerateIdeas:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap: prior work lacks X.",      # gap_analysis
                MOCK_IDEA_JSON,                   # proposer
                "Weakness: Y.",                   # critic r1
                "Feasible: Z.",                   # expert r1
                MOCK_IDEA_JSON,                   # synthesizer r1
                MOCK_IDEA_JSON,                   # final extraction
                MOCK_SCORE_JSON,                  # score
                MOCK_METRIC_JSON,                 # metric
            ]
            import server
            result = await server.generate_ideas(
                topic="FP32 GEMM",
                papers=MOCK_PAPERS,
                n_ideas=1,
                n_agents=3,
                max_discussion_rounds=1,
            )
        assert "ideas" in result
        assert "gap_analysis" in result
        assert "primary_metric" in result
        assert "higher_is_better" in result
        assert "papers_analyzed" in result
        assert "agents_used" in result

    @pytest.mark.asyncio
    async def test_idea_count_respected(self):
        side_effects = []
        side_effects.append("Gap analysis text.")  # gap
        for _ in range(3):  # 3 ideas
            side_effects += [
                MOCK_IDEA_JSON,   # proposer
                MOCK_IDEA_JSON,   # final extraction
            ]
        side_effects += [MOCK_SCORE_JSON] * 3  # scores
        side_effects.append(MOCK_METRIC_JSON)   # metric

        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = side_effects
            import server
            result = await server.generate_ideas(
                topic="topic",
                papers=MOCK_PAPERS,
                n_ideas=3,
                n_agents=2,
                max_discussion_rounds=0,
            )
        assert len(result["ideas"]) == 3

    @pytest.mark.asyncio
    async def test_ideas_are_ranked(self):
        scores = [
            json.dumps({"novelty_score": 9, "feasibility_score": 8, "relevance_score": 9, "rationale": ""}),
            json.dumps({"novelty_score": 3, "feasibility_score": 2, "relevance_score": 3, "rationale": ""}),
        ]
        se = ["Gap."]
        for _ in range(2):
            se += [MOCK_IDEA_JSON, MOCK_IDEA_JSON]
        se += scores
        se.append(MOCK_METRIC_JSON)

        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = se
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=2, n_agents=2, max_discussion_rounds=0,
            )
        scores_out = [i["overall_score"] for i in result["ideas"]]
        assert scores_out[0] >= scores_out[-1], "Ideas should be sorted by score descending"

    @pytest.mark.asyncio
    async def test_metric_decided_by_llm(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON,
                MOCK_SCORE_JSON,
                json.dumps({"primary_metric": "throughput", "higher_is_better": True, "metric_rationale": "speed matters"}),
            ]
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert result["primary_metric"] == "throughput"
        assert result["higher_is_better"] is True

    @pytest.mark.asyncio
    async def test_fallback_when_llm_returns_invalid_json(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.return_value = "NOT_JSON"
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert "ideas" in result
        assert isinstance(result["ideas"], list)

    @pytest.mark.asyncio
    async def test_clamps_n_ideas(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.return_value = MOCK_IDEA_JSON
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=99,  # should be clamped to 5
                n_agents=2, max_discussion_rounds=0,
            )
        assert len(result["ideas"]) <= 5

    @pytest.mark.asyncio
    async def test_max_recursion_depth_param_accepted(self):
        """Issue #3 compatibility: max_recursion_depth param must be accepted."""
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = ["Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_SCORE_JSON, MOCK_METRIC_JSON]
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
                max_recursion_depth=2,  # should not raise
            )
        assert "ideas" in result

    @pytest.mark.asyncio
    async def test_no_hardcoded_cluster_assumptions(self):
        """No cluster names, compiler flags, or scheduler names in production code."""
        import server
        source = open(server.__file__).read()
        forbidden = ["genoa", "mi100", "RIKEN", "takanori", "gcc", "-march=native", "sbatch"]
        for word in forbidden:
            assert word not in source, f"Hardcoded value found: {word!r}"
