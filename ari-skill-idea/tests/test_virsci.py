"""
Tests for VirSci MCP adapter (ARI integration).
"""
import asyncio, json, sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

MOCK_S2_RAW = [
    {"title": "Fast Matrix Multiply", "abstract": "A fast approach.", "year": 2023, "citationCount": 42, "paperId": "abc123"},
    {"title": "Error-Compensated GEMM", "abstract": "Neumaier.", "year": 2022, "citationCount": 15, "paperId": "def456"},
]
MOCK_PAPERS = [
    {"title": "Fast Matrix Multiply", "abstract": "A fast approach.", "year": 2023, "citationCount": 42, "paperId": "abc123", "url": ""},
    {"title": "Error-Compensated GEMM", "abstract": "Neumaier.", "year": 2022, "citationCount": 15, "paperId": "def456", "url": ""},
]
MOCK_IDEA_JSON = json.dumps({
    "Title": "Adaptive Precision GEMM",
    "Idea": "Uses mixed precision with error tracking.",
    "Experiment": "1. Implement. 2. Benchmark. 3. Compare.",
    "Novelty": 8, "Feasibility": 7, "Clarity": 9
})
MOCK_METRIC_JSON = json.dumps({
    "primary_metric": "max_relative_error",
    "higher_is_better": False,
    "metric_rationale": "Measures accuracy vs FP64 reference."
})


class TestSurvey:
    def test_survey_returns_papers(self):
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("FP32 GEMM", max_papers=5)
        assert "papers" in result
        assert len(result["papers"]) >= 1
        assert all("title" in p for p in result["papers"])

    def test_survey_respects_max_papers(self):
        large = [{"title": f"P{i}", "abstract": "", "year": 2020, "citationCount": i, "paperId": f"id{i}"} for i in range(20)]
        with patch("server._s2_search", return_value=large), \
             patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("topic", max_papers=5)
        assert len(result["papers"]) <= 5

    def test_survey_fallback_on_s2_failure(self):
        mock_p = MagicMock()
        mock_p.title = "Fallback Paper"
        mock_p.abstract = "Abstract."
        mock_p.year = 2021
        mock_p.citationCount = 3
        mock_p.paperId = "fb001"
        mock_p.url = ""
        with patch("server._s2_search", return_value=[]), \
             patch("server.SemanticScholar") as MockSch:
            MockSch.return_value.search_paper.return_value = [mock_p]
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
        assert isinstance(result["papers"], list)

    def test_survey_deduplicates_titles(self):
        dupe = MOCK_S2_RAW + [{"title": "Fast Matrix Multiply", "abstract": "dup", "year": 2023, "citationCount": 1, "paperId": "dup1"}]
        with patch("server._s2_search", return_value=dupe),              patch("server._s2_citations", return_value=[]):
            import server
            result = server.survey("topic", max_papers=10)
        titles = [p["title"] for p in result["papers"]]
        assert len(titles) == len(set(titles))

    def test_survey_enriches_with_citations(self):
        """Citation graph: survey() fetches citing papers for top results (2-hop)."""
        cite_paper = {"title": "Citation Paper", "abstract": "Cited.", "year": 2024,
                      "citationCount": 5, "paperId": "cite001"}
        with patch("server._s2_search", return_value=MOCK_S2_RAW),              patch("server._s2_citations", return_value=[cite_paper]):
            import server
            result = server.survey("topic", max_papers=10)
        titles = [p["title"] for p in result["papers"]]
        assert "Citation Paper" in titles, "Citation graph papers should be included"


class TestGenerateIdeas:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap analysis.",        # gap
                MOCK_IDEA_JSON,         # discussion agent 1
                MOCK_IDEA_JSON,         # discussion agent 2
                MOCK_IDEA_JSON, MOCK_IDEA_JSON,  # buffer
                MOCK_METRIC_JSON,       # metric
            ]
            import server
            result = await server.generate_ideas(
                topic="FP32 GEMM", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        for key in ["ideas", "gap_analysis", "primary_metric", "higher_is_better", "papers_analyzed", "virsci_integration_status"]:
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_idea_count_respected(self):
        se = ["Gap."] + [MOCK_IDEA_JSON] * 12 + [MOCK_METRIC_JSON]  # 3 ideas * up to 4 agents
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = se
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=3, n_agents=2, max_discussion_rounds=0,
            )
        assert len(result["ideas"]) == 3

    @pytest.mark.asyncio
    async def test_ideas_sorted_by_novelty(self):
        high = json.dumps({"Title": "High", "Idea": "H", "Experiment": "H", "Novelty": 9, "Feasibility": 9, "Clarity": 9})
        low  = json.dumps({"Title": "Low",  "Idea": "L", "Experiment": "L", "Novelty": 2, "Feasibility": 2, "Clarity": 2})
        se = ["Gap.", high, low, MOCK_METRIC_JSON, MOCK_IDEA_JSON, MOCK_IDEA_JSON]  # extra buffer
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = se
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=2, n_agents=2, max_discussion_rounds=0,
            )
        scores = [i["overall_score"] for i in result["ideas"]]
        assert scores[0] >= scores[-1]

    @pytest.mark.asyncio
    async def test_metric_decided_by_llm(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = ["Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON,
                json.dumps({"primary_metric": "throughput", "higher_is_better": True, "metric_rationale": "speed"})]
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert result["primary_metric"] == "throughput"
        assert result["higher_is_better"] is True

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
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
                n_ideas=99, n_agents=2, max_discussion_rounds=0,
            )
        assert len(result["ideas"]) <= 5

    @pytest.mark.asyncio
    async def test_max_recursion_depth_accepted(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = ["Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON]
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
                max_recursion_depth=2,
            )
        assert "ideas" in result

    @pytest.mark.asyncio
    async def test_virsci_prompts_loaded(self):
        import server
        # VirSci prompts should be loaded from vendor/virsci submodule
        assert server._VIRSCI_PROMPTS_AVAILABLE is True
        assert hasattr(server._VirSciPrompts, "prompt_task")
        assert hasattr(server._VirSciPrompts, "prompt_reference")

    @pytest.mark.asyncio
    async def test_virsci_status_in_output(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = ["Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON]
            import server
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_PAPERS,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert "virsci_integration_status" in result
        assert "VirSci" in result["virsci_integration_status"]

    @pytest.mark.asyncio
    async def test_no_hardcoded_cluster_assumptions(self):
        import server
        source = open(server.__file__).read()
        forbidden = ["genoa", "mi100", "RIKEN", "takanori", "gcc", "-march=native", "sbatch"]
        for word in forbidden:
            assert word not in source, f"Hardcoded value: {word!r}"
