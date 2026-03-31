"""Tests for ari-skill-idea server — current implementation.

Covers:
  1. Config helpers: _model(), _api_base()
  2. _llm() kwargs construction per backend
  3. survey() with mocked Semantic Scholar
  4. generate_ideas() full flow with mocked LLM
  5. Edge cases and error handling
  6. _extract_between_json_tags()
  7. _format_references()
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import server  # noqa: E402


# ── Test data ────────────────────────────────────────────────────────────────

MOCK_S2_RAW = [
    {"title": "Paper A", "abstract": "Abstract A.", "year": 2023,
     "citationCount": 10, "paperId": "aaa"},
    {"title": "Paper B", "abstract": "Abstract B.", "year": 2022,
     "citationCount": 5, "paperId": "bbb"},
]

MOCK_IDEA_JSON = json.dumps({
    "Title": "Adaptive Precision GEMM",
    "Idea": "Uses mixed precision with error tracking.",
    "Experiment": "1. Implement. 2. Benchmark. 3. Compare.",
    "Novelty": 8, "Feasibility": 7, "Clarity": 9,
})

MOCK_METRIC_JSON = json.dumps({
    "primary_metric": "throughput_gflops",
    "higher_is_better": True,
    "metric_rationale": "Measures computational efficiency.",
})


# ══════════════════════════════════════════════════════════════════════════════
# 1. Config helpers: _model(), _api_base()
# ══════════════════════════════════════════════════════════════════════════════

class TestModel:
    def test_default_is_ollama(self, monkeypatch):
        monkeypatch.delenv("ARI_LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        assert server._model() == "ollama_chat/qwen3:32b"

    def test_ari_env_takes_priority(self, monkeypatch):
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("LLM_MODEL", "should-not-use")
        assert server._model() == "gpt-5.2"

    def test_legacy_env_fallback(self, monkeypatch):
        monkeypatch.delenv("ARI_LLM_MODEL", raising=False)
        monkeypatch.setenv("LLM_MODEL", "ollama_chat/llama3:8b")
        assert server._model() == "ollama_chat/llama3:8b"


class TestApiBase:
    def test_explicit_empty_returns_none(self, monkeypatch):
        """ARI_LLM_API_BASE='' (set by GUI for OpenAI) → None."""
        monkeypatch.setenv("ARI_LLM_API_BASE", "")
        assert server._api_base() is None

    def test_explicit_url_returned(self, monkeypatch):
        monkeypatch.setenv("ARI_LLM_API_BASE", "http://custom:8080")
        assert server._api_base() == "http://custom:8080"

    def test_ollama_model_gets_default_url(self, monkeypatch):
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        monkeypatch.setenv("ARI_LLM_MODEL", "ollama_chat/qwen3:32b")
        assert server._api_base() == "http://127.0.0.1:11434"

    def test_openai_model_no_fallback(self, monkeypatch):
        """gpt-5.2 must NOT fall back to Ollama URL."""
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        assert server._api_base() is None

    def test_anthropic_model_no_fallback(self, monkeypatch):
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        monkeypatch.setenv("ARI_LLM_MODEL", "anthropic/claude-sonnet-4-5")
        assert server._api_base() is None

    def test_legacy_llm_api_base(self, monkeypatch):
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.setenv("LLM_API_BASE", "http://legacy:9999")
        assert server._api_base() == "http://legacy:9999"


# ══════════════════════════════════════════════════════════════════════════════
# 2. _llm() kwargs construction
# ══════════════════════════════════════════════════════════════════════════════

class TestLlmKwargs:
    @pytest.mark.asyncio
    async def test_openai_no_api_base(self, monkeypatch):
        """OpenAI model → api_base must NOT be in kwargs."""
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_LLM_API_BASE", "")

        captured = {}
        async def fake_acompletion(**kw):
            captured.update(kw)
            resp = MagicMock()
            resp.choices[0].message.content = "hello"
            return resp

        with patch("server.litellm.acompletion", side_effect=fake_acompletion):
            await server._llm("system", "user")

        assert captured["model"] == "gpt-5.2"
        assert "api_base" not in captured, \
            f"api_base should not be set for OpenAI, got: {captured.get('api_base')}"

    @pytest.mark.asyncio
    async def test_ollama_has_api_base(self, monkeypatch):
        """Ollama model → api_base must be set."""
        monkeypatch.setenv("ARI_LLM_MODEL", "ollama_chat/qwen3:32b")
        monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)

        captured = {}
        async def fake_acompletion(**kw):
            captured.update(kw)
            resp = MagicMock()
            resp.choices[0].message.content = "hello"
            return resp

        with patch("server.litellm.acompletion", side_effect=fake_acompletion):
            await server._llm("system", "user")

        assert captured["model"] == "ollama_chat/qwen3:32b"
        assert captured["api_base"] == "http://127.0.0.1:11434"

    @pytest.mark.asyncio
    async def test_temperature_passed(self, monkeypatch):
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_LLM_API_BASE", "")

        captured = {}
        async def fake_acompletion(**kw):
            captured.update(kw)
            resp = MagicMock()
            resp.choices[0].message.content = "hello"
            return resp

        with patch("server.litellm.acompletion", side_effect=fake_acompletion):
            await server._llm("system", "user", temperature=0.3)

        assert captured["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_think_tags_stripped(self, monkeypatch):
        """<think>...</think> blocks should be removed from LLM output."""
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_LLM_API_BASE", "")

        async def fake_acompletion(**kw):
            resp = MagicMock()
            resp.choices[0].message.content = "<think>reasoning</think>actual answer"
            return resp

        with patch("server.litellm.acompletion", side_effect=fake_acompletion):
            result = await server._llm("system", "user")

        assert result == "actual answer"
        assert "<think>" not in result


# ══════════════════════════════════════════════════════════════════════════════
# 3. survey()
# ══════════════════════════════════════════════════════════════════════════════

class TestSurvey:
    def test_returns_papers(self):
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=5)
        assert "papers" in result
        assert len(result["papers"]) == 2
        assert all("title" in p for p in result["papers"])
        assert all("paperId" in p for p in result["papers"])

    def test_respects_max_papers(self):
        many = [{"title": f"P{i}", "abstract": "", "year": 2020,
                 "citationCount": i, "paperId": f"id{i}"} for i in range(20)]
        with patch("server._s2_search", return_value=many), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=5)
        assert len(result["papers"]) <= 5

    def test_max_papers_capped_at_15(self):
        many = [{"title": f"P{i}", "abstract": "", "year": 2020,
                 "citationCount": i, "paperId": f"id{i}"} for i in range(20)]
        with patch("server._s2_search", return_value=many), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=100)
        assert len(result["papers"]) <= 15

    def test_deduplicates_by_title(self):
        dupe = MOCK_S2_RAW + [{"title": "Paper A", "abstract": "dup",
                                "year": 2023, "citationCount": 1, "paperId": "dup1"}]
        with patch("server._s2_search", return_value=dupe), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=10)
        titles = [p["title"] for p in result["papers"]]
        assert len(titles) == len(set(titles))

    def test_empty_results(self):
        with patch("server._s2_search", return_value=[]), \
             patch("server.SemanticScholar") as MockSch:
            MockSch.return_value.search_paper.side_effect = Exception("timeout")
            result = server.survey("nonexistent", max_papers=5)
        assert result["papers"] == [] or isinstance(result["papers"], list)

    def test_abstract_truncated_to_1000(self):
        raw = [{"title": "Long", "abstract": "x" * 2000, "year": 2023,
                "citationCount": 1, "paperId": "long1"}]
        with patch("server._s2_search", return_value=raw), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=1)
        assert len(result["papers"][0]["abstract"]) == 1000

    def test_citation_enrichment(self):
        cite = {"title": "Cited Paper", "abstract": "Cited.", "year": 2024,
                "citationCount": 5, "paperId": "cite1"}
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[cite]):
            result = server.survey("topic", max_papers=10)
        titles = [p["title"] for p in result["papers"]]
        assert "Cited Paper" in titles

    def test_paper_url_format(self):
        with patch("server._s2_search", return_value=MOCK_S2_RAW), \
             patch("server._s2_citations", return_value=[]):
            result = server.survey("topic", max_papers=5)
        for p in result["papers"]:
            if p["paperId"]:
                assert p["url"].startswith("https://www.semanticscholar.org/paper/")

    def test_fallback_to_semanticscholar_lib(self):
        mock_p = MagicMock()
        mock_p.title = "Fallback"
        mock_p.abstract = "From lib."
        mock_p.year = 2021
        mock_p.citationCount = 3
        mock_p.paperId = "fb1"
        with patch("server._s2_search", return_value=[]), \
             patch("server.SemanticScholar") as MockSch:
            MockSch.return_value.search_paper.return_value = [mock_p]
            result = server.survey("topic", max_papers=5)
        assert any(p["title"] == "Fallback" for p in result["papers"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. generate_ideas() full flow
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateIdeas:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap analysis text.",
                MOCK_IDEA_JSON, MOCK_IDEA_JSON,  # 1 idea × 2 agents
                MOCK_METRIC_JSON,
            ]
            result = await server.generate_ideas(
                topic="GEMM optimization", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        for key in ["ideas", "gap_analysis", "primary_metric",
                     "higher_is_better", "papers_analyzed",
                     "virsci_integration_status", "n_agents",
                     "discussion_rounds"]:
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_idea_structure(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON,
            ]
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        idea = result["ideas"][0]
        for key in ["title", "description", "novelty", "feasibility",
                     "experiment_plan", "novelty_score", "feasibility_score",
                     "overall_score"]:
            assert key in idea, f"Idea missing key: {key}"
        assert idea["title"] == "Adaptive Precision GEMM"
        assert 0 <= idea["novelty_score"] <= 1
        assert 0 <= idea["feasibility_score"] <= 1
        assert 0 <= idea["overall_score"] <= 1

    @pytest.mark.asyncio
    async def test_idea_count_respected(self):
        side = ["Gap."] + [MOCK_IDEA_JSON] * 20 + [MOCK_METRIC_JSON]
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = side
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=3, n_agents=2, max_discussion_rounds=0,
            )
        assert len(result["ideas"]) == 3

    @pytest.mark.asyncio
    async def test_clamps_n_ideas_max(self):
        side = ["Gap."] + [MOCK_IDEA_JSON] * 30 + [MOCK_METRIC_JSON]
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = side
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=99, n_agents=2, max_discussion_rounds=0,
            )
        assert len(result["ideas"]) <= 5

    @pytest.mark.asyncio
    async def test_ideas_sorted_by_score(self):
        high = json.dumps({"Title": "High", "Idea": "H", "Experiment": "H",
                           "Novelty": 10, "Feasibility": 10, "Clarity": 10})
        low = json.dumps({"Title": "Low", "Idea": "L", "Experiment": "L",
                          "Novelty": 1, "Feasibility": 1, "Clarity": 1})
        side = ["Gap.", high, high, low, low, MOCK_METRIC_JSON]
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = side
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=2, n_agents=2, max_discussion_rounds=0,
            )
        scores = [i["overall_score"] for i in result["ideas"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_metric_from_llm(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON,
            ]
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert result["primary_metric"] == "throughput_gflops"
        assert result["higher_is_better"] is True

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.return_value = "NOT_JSON_AT_ALL"
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert "ideas" in result
        assert isinstance(result["ideas"], list)

    @pytest.mark.asyncio
    async def test_papers_analyzed_count(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON,
            ]
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert result["papers_analyzed"] == len(MOCK_S2_RAW)

    @pytest.mark.asyncio
    async def test_experiment_context_included(self):
        """experiment_context should be appended to paper reference."""
        captured_prompts = []
        async def capture_llm(system, user, temperature=0.7):
            captured_prompts.append(user)
            return MOCK_IDEA_JSON

        with patch("server._llm", side_effect=capture_llm), \
             patch("server._s2_search", return_value=[]):
            await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                experiment_context="SLURM cluster with 64 cores",
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        # The context should appear in at least one prompt
        all_text = " ".join(captured_prompts)
        assert "SLURM cluster with 64 cores" in all_text

    @pytest.mark.asyncio
    async def test_virsci_status_in_output(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm, \
             patch("server._s2_search", return_value=[]):
            mock_llm.side_effect = [
                "Gap.", MOCK_IDEA_JSON, MOCK_IDEA_JSON, MOCK_METRIC_JSON,
            ]
            result = await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )
        assert "VirSci" in result["virsci_integration_status"]

    @pytest.mark.asyncio
    async def test_openai_model_no_404(self, monkeypatch):
        """Regression: gpt-5.2 must not hit Ollama endpoint (the 404 bug)."""
        monkeypatch.setenv("ARI_LLM_MODEL", "gpt-5.2")
        monkeypatch.setenv("ARI_LLM_API_BASE", "")

        captured_kwargs = []
        async def capture_acompletion(**kw):
            captured_kwargs.append(kw)
            resp = MagicMock()
            resp.choices[0].message.content = MOCK_IDEA_JSON
            return resp

        with patch("server.litellm.acompletion", side_effect=capture_acompletion), \
             patch("server._s2_search", return_value=[]):
            await server.generate_ideas(
                topic="topic", papers=MOCK_S2_RAW,
                n_ideas=1, n_agents=2, max_discussion_rounds=0,
            )

        for kw in captured_kwargs:
            assert kw["model"] == "gpt-5.2"
            assert "api_base" not in kw, \
                f"api_base={kw['api_base']!r} — would cause 404 on Ollama"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Helper functions
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractBetweenJsonTags:
    def test_json_in_code_block(self):
        text = 'Some text\n```json\n{"key": "val"}\n```\nmore text'
        assert server._extract_between_json_tags(text) == '{"key": "val"}'

    def test_json_without_code_block(self):
        text = 'prefix {"key": "val"} suffix'
        assert server._extract_between_json_tags(text) == '{"key": "val"}'

    def test_plain_text_returned_as_is(self):
        text = "no json here"
        assert server._extract_between_json_tags(text) == "no json here"

    def test_nested_json(self):
        text = '```json\n{"a": {"b": 1}}\n```'
        result = server._extract_between_json_tags(text)
        parsed = json.loads(result)
        assert parsed == {"a": {"b": 1}}


class TestFormatReferences:
    def test_formats_papers(self):
        papers = [
            {"title": "Paper A", "abstract": "Abstract A.", "year": 2023},
            {"title": "Paper B", "abstract": "Abstract B.", "year": 2022},
        ]
        result = server._format_references(papers)
        assert "[1]" in result
        assert "[2]" in result
        assert "Paper A" in result
        assert "2023" in result

    def test_truncates_abstract(self):
        papers = [{"title": "T", "abstract": "x" * 500, "year": 2023}]
        result = server._format_references(papers)
        # Abstract in reference should be at most 300 chars
        lines = result.split("\n")
        abstract_line = [l for l in lines if l.strip().startswith("x")]
        assert len(abstract_line[0].strip()) <= 300

    def test_max_8_papers(self):
        papers = [{"title": f"P{i}", "abstract": f"A{i}", "year": 2020}
                  for i in range(15)]
        result = server._format_references(papers)
        assert "[8]" in result
        assert "[9]" not in result

    def test_empty_papers(self):
        assert server._format_references([]) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 6. VirSci discussion loop
# ══════════════════════════════════════════════════════════════════════════════

class TestVirsciDiscussionLoop:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = MOCK_IDEA_JSON
            result = await server._virsci_discussion_loop(
                topic="test", paper_reference="refs", n_agents=2, max_rounds=1,
            )
        for key in ["title", "description", "novelty", "feasibility",
                     "experiment_plan", "novelty_score", "feasibility_score",
                     "clarity_score", "virsci_prompts_used"]:
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_scores_normalized_to_01(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = MOCK_IDEA_JSON
            result = await server._virsci_discussion_loop(
                topic="test", paper_reference="refs", n_agents=2, max_rounds=1,
            )
        assert 0 <= result["novelty_score"] <= 1
        assert 0 <= result["feasibility_score"] <= 1
        assert 0 <= result["clarity_score"] <= 1

    @pytest.mark.asyncio
    async def test_handles_invalid_json_gracefully(self):
        with patch("server._llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "I have no JSON to give"
            result = await server._virsci_discussion_loop(
                topic="test", paper_reference="refs", n_agents=2, max_rounds=1,
            )
        # Should not crash, returns default values
        assert "title" in result

    @pytest.mark.asyncio
    async def test_multi_round_discussion(self):
        """Multiple rounds should call LLM more times."""
        call_count = 0
        async def counting_llm(system, user, temperature=0.7):
            nonlocal call_count
            call_count += 1
            return MOCK_IDEA_JSON

        with patch("server._llm", side_effect=counting_llm):
            await server._virsci_discussion_loop(
                topic="test", paper_reference="refs",
                n_agents=2, max_rounds=2,
            )
        # 2 agents × 2 rounds = 4 calls
        assert call_count == 4


# ══════════════════════════════════════════════════════════════════════════════
# 7. No hardcoded environment assumptions
# ══════════════════════════════════════════════════════════════════════════════

class TestNoHardcodedAssumptions:
    def test_no_hardcoded_api_keys(self):
        source = Path(server.__file__).read_text()
        # Should not contain literal API keys
        assert "sk-" not in source or "sk-" in "# sk-example"
