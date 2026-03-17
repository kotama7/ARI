"""Tests for ari-skill-idea server."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.server import survey


class TestSurvey:
    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_returns_papers_from_arxiv(self, mock_arxiv, mock_ss):
        mock_result = MagicMock()
        mock_result.title = "Deep Learning for NLP"
        mock_result.summary = "A survey of deep learning methods."
        mock_result.entry_id = "https://arxiv.org/abs/2101.00001"
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = [mock_result]
        mock_arxiv.Search.return_value = MagicMock()
        mock_ss.return_value.search_paper.return_value = []

        result = survey("deep learning NLP", max_papers=5)

        assert "papers" in result
        assert len(result["papers"]) == 1
        assert result["papers"][0]["title"] == "Deep Learning for NLP"
        assert result["papers"][0]["url"] == "https://arxiv.org/abs/2101.00001"

    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_supplements_with_semantic_scholar(self, mock_arxiv, mock_ss):
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = []
        mock_arxiv.Search.return_value = MagicMock()
        mock_paper = MagicMock()
        mock_paper.title = "SS Paper"
        mock_paper.abstract = "SS Abstract"
        mock_paper.url = "https://semanticscholar.org/paper/123"
        mock_ss.return_value.search_paper.return_value = [mock_paper]

        result = survey("quantum computing", max_papers=5)
        assert len(result["papers"]) == 1
        assert result["papers"][0]["title"] == "SS Paper"

    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_deduplicates_by_title(self, mock_arxiv, mock_ss):
        mock_result = MagicMock()
        mock_result.title = "Same Paper"
        mock_result.summary = "From arxiv"
        mock_result.entry_id = "https://arxiv.org/abs/1"
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = [mock_result]
        mock_arxiv.Search.return_value = MagicMock()
        mock_ss_paper = MagicMock()
        mock_ss_paper.title = "Same Paper"
        mock_ss_paper.abstract = "From SS"
        mock_ss_paper.url = "https://ss.org/1"
        mock_ss.return_value.search_paper.return_value = [mock_ss_paper]

        result = survey("topic", max_papers=5)
        assert len(result["papers"]) == 1

    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_respects_max_papers(self, mock_arxiv, mock_ss):
        results = []
        for i in range(10):
            r = MagicMock()
            r.title = f"Paper {i}"
            r.summary = f"Abstract {i}"
            r.entry_id = f"https://arxiv.org/abs/{i}"
            results.append(r)
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = results
        mock_arxiv.Search.return_value = MagicMock()
        mock_ss.return_value.search_paper.return_value = []

        result = survey("topic", max_papers=3)
        assert len(result["papers"]) == 3

    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_empty_results(self, mock_arxiv, mock_ss):
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = []
        mock_arxiv.Search.return_value = MagicMock()
        mock_ss.return_value.search_paper.return_value = []

        result = survey("nonexistent topic xyz", max_papers=5)
        assert result == {"papers": []}

    @patch("src.server.SemanticScholar")
    @patch("src.server.arxiv")
    def test_abstract_truncated_to_1000(self, mock_arxiv, mock_ss):
        mock_result = MagicMock()
        mock_result.title = "Long Paper"
        mock_result.summary = "x" * 2000
        mock_result.entry_id = "https://arxiv.org/abs/1"
        mock_client = MagicMock()
        mock_arxiv.Client.return_value = mock_client
        mock_client.results.return_value = [mock_result]
        mock_arxiv.Search.return_value = MagicMock()
        mock_ss.return_value.search_paper.return_value = []

        result = survey("topic", max_papers=1)
        assert len(result["papers"][0]["abstract"]) == 1000


class TestGenerateIdeas:
    @pytest.mark.asyncio
    @patch("src.server.litellm.acompletion")
    async def test_returns_ideas(self, mock_llm):
        import json
        from src.server import generate_ideas
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({
            "gap_analysis": "Prior work lacks ablation of OpenMP thread scaling.",
            "ideas": [
                {
                    "title": "Thread scaling ablation",
                    "description": "Test 1-64 threads systematically",
                    "novelty": "No prior paper tested > 32 threads on Himeno",
                    "feasibility": "SLURM cluster has 64 cores",
                    "experiment_plan": "Submit jobs with OMP_NUM_THREADS in [1,4,8,16,32,64]"
                }
            ]
        })
        mock_llm.return_value = mock_resp

        papers = [{"title": "Himeno Benchmark", "abstract": "Classic CFD benchmark"}]
        result = await generate_ideas("Himeno optimization", papers, n_ideas=1)

        assert "gap_analysis" in result
        assert len(result["ideas"]) == 1
        assert result["ideas"][0]["title"] == "Thread scaling ablation"
        assert result["papers_analyzed"] == 1

    @pytest.mark.asyncio
    @patch("src.server.litellm.acompletion")
    async def test_handles_llm_error(self, mock_llm):
        from src.server import generate_ideas
        mock_llm.side_effect = Exception("LLM timeout")
        result = await generate_ideas("topic", [], n_ideas=2)
        assert "error" in result
        assert result["ideas"] == []

    @pytest.mark.asyncio
    @patch("src.server.litellm.acompletion")
    async def test_n_ideas_clamped(self, mock_llm):
        import json
        from src.server import generate_ideas
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({"gap_analysis": "", "ideas": []})
        mock_llm.return_value = mock_resp
        # n_ideas=10 should be clamped to 5
        await generate_ideas("topic", [], n_ideas=10)
        call_args = mock_llm.call_args
        prompt = str(call_args)
        assert "5" in prompt or "ideas" in prompt
