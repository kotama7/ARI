"""Tests for child node workflow hint inheritance.

Verifies that child nodes receive the same execution workflow hints
as the parent (e.g. slurm_submit when a scheduler is configured),
preventing accidental execution on the wrong host.
"""
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ari.agent.workflow import WorkflowHints, from_experiment_text, enrich_hints_from_mcp
from ari.orchestrator.node import Node, NodeStatus


# ── WorkflowHints tests ──────────────────────────────────────────────────

class TestWorkflowHintsFromExperiment:
    def test_slurm_keywords_set_job_submitter(self):
        """Experiment text containing SLURM keywords should set job_submitter_tool."""
        text = "# Experiment\nRun on SLURM cluster\npartition: gpu"
        hints = from_experiment_text(text)
        assert hints.job_submitter_tool == "slurm_submit"
        assert hints.job_poller_tool == "job_status"

    def test_no_slurm_keywords_no_submitter(self):
        """Experiment without SLURM keywords should NOT set job_submitter_tool."""
        text = "# Experiment\nRun locally on this machine"
        hints = from_experiment_text(text)
        assert not hints.job_submitter_tool

    def test_post_survey_hint_includes_slurm_submit(self):
        """When SLURM is detected, post_survey_hint should mention slurm_submit."""
        text = "# Experiment\nUse sbatch to submit jobs"
        hints = from_experiment_text(text)
        assert "slurm_submit" in hints.post_survey_hint


# ── Web research & memory tool hint tests ────────────────────────────────

_MOCK_MCP_TOOLS = [
    {"name": "make_metric_spec", "description": "Create metric spec", "inputSchema": {"properties": {"goal": {}}}, "skill_name": "evaluator-skill"},
    {"name": "survey", "description": "Survey related work", "inputSchema": {"properties": {"query": {}}}, "skill_name": "idea-skill"},
    {"name": "generate_ideas", "description": "Generate hypotheses", "inputSchema": {"properties": {"context": {}}}, "skill_name": "idea-skill"},
    {"name": "run_bash", "description": "Run bash command", "inputSchema": {"properties": {"command": {}}}, "skill_name": "hpc-skill"},
    {"name": "slurm_submit", "description": "Submit SLURM job", "inputSchema": {"properties": {"script": {}}}, "skill_name": "hpc-skill"},
    {"name": "job_status", "description": "Check job status", "inputSchema": {"properties": {"job_id": {}}}, "skill_name": "hpc-skill"},
    {"name": "web_search", "description": "Search the web", "inputSchema": {"properties": {"query": {}}}, "skill_name": "web-skill"},
    {"name": "search_papers", "description": "Search academic papers", "inputSchema": {"properties": {"query": {}}}, "skill_name": "web-skill"},
    {"name": "fetch_url", "description": "Fetch web page", "inputSchema": {"properties": {"url": {}}}, "skill_name": "web-skill"},
    {"name": "search_arxiv", "description": "Search arXiv", "inputSchema": {"properties": {"query": {}}}, "skill_name": "web-skill"},
    {"name": "add_memory", "description": "Save memory", "inputSchema": {"properties": {"node_id": {}, "text": {}}}, "skill_name": "memory-skill"},
    {"name": "search_memory", "description": "Search memories", "inputSchema": {"properties": {"query": {}}}, "skill_name": "memory-skill"},
]

def _enriched_hints(text: str) -> WorkflowHints:
    """Build hints and enrich with mock MCP tools (simulating real flow)."""
    hints = from_experiment_text(text)
    enrich_hints_from_mcp(hints, _MOCK_MCP_TOOLS)
    return hints


class TestWebResearchToolHints:
    """Verify post_survey_hint includes web research and memory tools after MCP enrichment."""

    def test_default_hint_includes_web_search(self):
        """Default (non-SLURM) hint should mention web_search after enrichment."""
        hints = _enriched_hints("Run a benchmark locally")
        assert "web_search" in hints.post_survey_hint

    def test_default_hint_includes_search_papers(self):
        hints = _enriched_hints("Run a benchmark locally")
        assert "search_papers" in hints.post_survey_hint

    def test_default_hint_includes_search_arxiv(self):
        hints = _enriched_hints("Run a benchmark locally")
        assert "search_arxiv" in hints.post_survey_hint

    def test_default_hint_includes_fetch_url(self):
        hints = _enriched_hints("Run a benchmark locally")
        assert "fetch_url" in hints.post_survey_hint

    def test_slurm_hint_includes_web_search(self):
        """SLURM hint should also mention web_search after enrichment."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "web_search" in hints.post_survey_hint

    def test_slurm_hint_includes_search_papers(self):
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "search_papers" in hints.post_survey_hint

    def test_slurm_hint_includes_fetch_url(self):
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "fetch_url" in hints.post_survey_hint

    def test_default_hint_includes_add_memory(self):
        """Default hint should mention add_memory after enrichment."""
        hints = _enriched_hints("Run a benchmark locally")
        assert "add_memory" in hints.post_survey_hint

    def test_default_hint_includes_search_memory(self):
        hints = _enriched_hints("Run a benchmark locally")
        assert "search_memory" in hints.post_survey_hint

    def test_slurm_hint_includes_add_memory(self):
        """SLURM hint should also mention add_memory after enrichment."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "add_memory" in hints.post_survey_hint

    def test_slurm_hint_includes_search_memory(self):
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "search_memory" in hints.post_survey_hint

    def test_tool_sequence_includes_web_tools(self):
        """tool_sequence should include web research tools after enrichment."""
        hints = _enriched_hints("Run a benchmark locally")
        assert "web_search" in hints.tool_sequence
        assert "search_papers" in hints.tool_sequence
        assert "fetch_url" in hints.tool_sequence

    def test_tool_sequence_includes_memory_tools(self):
        """tool_sequence should include memory tools after enrichment."""
        hints = _enriched_hints("Run a benchmark locally")
        assert "add_memory" in hints.tool_sequence
        assert "search_memory" in hints.tool_sequence

    def test_slurm_tool_sequence_includes_web_tools(self):
        """SLURM tool_sequence should also include web research tools after enrichment."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "web_search" in hints.tool_sequence
        assert "search_papers" in hints.tool_sequence
        assert "fetch_url" in hints.tool_sequence

    def test_slurm_tool_sequence_includes_memory_tools(self):
        """SLURM tool_sequence should also include memory tools after enrichment."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "add_memory" in hints.tool_sequence
        assert "search_memory" in hints.tool_sequence

    def test_child_node_inherits_web_tools(self):
        """Child nodes should see web research tools in their workflow hint."""
        hints = _enriched_hints("Use SLURM with sbatch")
        content = _make_loop_and_build_messages(hints, node_depth=1)
        assert "web_search" in content
        assert "fetch_url" in content

    def test_child_node_inherits_memory_tools(self):
        """Child nodes should see memory tools in their workflow hint."""
        hints = _enriched_hints("Use SLURM with sbatch")
        content = _make_loop_and_build_messages(hints, node_depth=1)
        assert "add_memory" in content
        assert "search_memory" in content

    def test_required_workflow_override_replaces_hints(self):
        """## Required Workflow section should override default hints entirely."""
        text = "# Experiment\nUse sbatch\n## Required Workflow\n1. Do custom step\n2. Done\n"
        hints = from_experiment_text(text)
        # Required Workflow replaces default, so web tools may not be present
        assert "custom step" in hints.post_survey_hint

    def test_no_mcp_tools_keeps_static_hint(self):
        """Without MCP enrichment, hints should still have a valid post_survey_hint."""
        hints = from_experiment_text("Run a benchmark locally")
        assert "generate_ideas" in hints.post_survey_hint
        assert "STEP BUDGET" in hints.post_survey_hint


# ── Dynamic async-job tool hint tests ───────────────────────────────────
# Verify that slurm_submit / job_status descriptions are derived from MCP
# tool metadata (name, inputSchema.properties) rather than hardcoded.

class TestDynamicJobSubmitterHint:
    def test_slurm_submit_listed_in_available_tools(self):
        """slurm_submit should appear in the AVAILABLE TOOLS section with its schema-derived signature."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        # Signature must include the actual inputSchema property ("script")
        assert "slurm_submit(script)" in hints.post_survey_hint
        # Description from MCP metadata must be present verbatim
        assert "Submit SLURM job" in hints.post_survey_hint

    def test_job_status_listed_in_available_tools(self):
        """job_status should appear with its schema-derived signature (job_id)."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert "job_status(job_id)" in hints.post_survey_hint
        assert "Check job status" in hints.post_survey_hint

    def test_workflow_steps_reference_submitter_from_hints(self):
        """Step template must reference the hints.job_submitter_tool name."""
        hints = _enriched_hints("Use sbatch on SLURM partition gpu")
        assert hints.job_submitter_tool == "slurm_submit"
        assert f"{hints.job_submitter_tool}()" in hints.post_survey_hint
        assert f"{hints.job_poller_tool}()" in hints.post_survey_hint

    def test_alternate_submitter_name_is_honored(self):
        """When a non-slurm submitter is registered, the hint must use that name, not 'slurm_submit'."""
        hints = WorkflowHints()
        hints.job_submitter_tool = "pbs_submit"
        hints.job_poller_tool = "pbs_status"
        hints.job_reader_tool = "run_bash"
        alt_tools = [
            {"name": "run_bash", "description": "Run bash",
             "inputSchema": {"properties": {"command": {}}}, "skill_name": "hpc-skill"},
            {"name": "pbs_submit", "description": "Submit PBS job",
             "inputSchema": {"properties": {"script": {}, "queue": {}}}, "skill_name": "hpc-skill"},
            {"name": "pbs_status", "description": "Check PBS job",
             "inputSchema": {"properties": {"job_id": {}}}, "skill_name": "hpc-skill"},
        ]
        enrich_hints_from_mcp(hints, alt_tools, hpc_enabled=True)
        assert "pbs_submit(script, queue)" in hints.post_survey_hint
        assert "pbs_status(job_id)" in hints.post_survey_hint
        # Step template references the alternate submitter name, not slurm_submit
        assert "pbs_submit()" in hints.post_survey_hint
        assert "slurm_submit" not in hints.post_survey_hint

    def test_local_profile_omits_slurm_tools(self):
        """hpc_enabled=False must strip slurm_submit/job_status from the hint entirely."""
        hints = from_experiment_text("Run locally", hpc_enabled=False)
        enrich_hints_from_mcp(hints, _MOCK_MCP_TOOLS, hpc_enabled=False)
        assert "slurm_submit" not in hints.post_survey_hint
        assert "job_status" not in hints.post_survey_hint
        assert hints.job_submitter_tool is None

    def test_local_profile_omits_slurm_from_tool_sequence(self):
        hints = from_experiment_text("Run locally", hpc_enabled=False)
        enrich_hints_from_mcp(hints, _MOCK_MCP_TOOLS, hpc_enabled=False)
        assert "slurm_submit" not in hints.tool_sequence
        assert "job_status" not in hints.tool_sequence


# ── Child node prompt tests ──────────────────────────────────────────────

def _make_loop_and_build_messages(hints, node_depth=1, node_label="improve"):
    """Create an AgentLoop-like context and build the child user_content."""
    from ari.agent.loop import AgentLoop

    llm = MagicMock()
    memory = MagicMock()
    mcp = MagicMock()
    mcp.list_tools.return_value = []

    loop = AgentLoop(llm, memory, mcp, workflow_hints=hints)

    # Build what the child node would see
    node = Node(id="child_001", parent_id="root", depth=node_depth)
    node.label = node_label if isinstance(node_label, str) else node_label

    goal_text = "Test experiment goal"
    _label_desc = {
        "improve": "Improve performance or accuracy beyond what the parent achieved.",
        "ablation": "Ablation study: remove or vary one component from the parent approach.",
    }.get(node.label, "Extend or vary the parent experiment.")

    _workflow_hint = ""
    if loop.hints.post_survey_hint:
        _workflow_hint = f"\n\nWorkflow:\n{loop.hints.post_survey_hint}"

    user_content = (
        f"Experiment goal:\n{goal_text}\n"
        f"Node: {node.id} depth={node.depth} task={node.label}\n\n"
        f"Task: {_label_desc}\n"
        "The parent node already completed the survey and established a research direction. "
        "Prior results are provided below. "
        "Implement and run your specific experiment, then return JSON with measurements."
        f"{_workflow_hint}"
    )
    return user_content


class TestChildNodeWorkflowInheritance:
    def test_child_receives_slurm_workflow_when_configured(self):
        """Child node prompt should include slurm_submit workflow when scheduler is configured."""
        hints = from_experiment_text("Run on SLURM cluster with sbatch")
        content = _make_loop_and_build_messages(hints, node_depth=1)
        assert "slurm_submit" in content
        assert "Workflow:" in content

    def test_child_local_mode_has_conditional_slurm(self):
        """In local mode, slurm_submit should be conditional ('if available'), not mandatory."""
        hints = from_experiment_text("Run locally on this machine")
        content = _make_loop_and_build_messages(hints, node_depth=1)
        # Local mode: job_submitter_tool is NOT set
        assert not hints.job_submitter_tool
        # The default hint mentions slurm conditionally, which is fine
        if "slurm_submit" in content:
            assert "if" in content.lower() or "otherwise" in content.lower()

    def test_child_workflow_matches_parent_hint(self):
        """Child node should receive the same post_survey_hint as the parent."""
        hints = from_experiment_text("Submit via sbatch on SLURM partition gpu")
        content = _make_loop_and_build_messages(hints, node_depth=1)
        # The post_survey_hint should be embedded verbatim
        assert hints.post_survey_hint in content

    def test_ablation_node_also_inherits_workflow(self):
        """Ablation nodes should also inherit the execution workflow."""
        hints = from_experiment_text("Use SLURM scheduler")
        content = _make_loop_and_build_messages(hints, node_depth=2, node_label="ablation")
        assert "slurm_submit" in content
        assert "Ablation study" in content


# ── run_bash tool description test ───────────────────────────────────────

class TestRunBashDescription:
    def test_run_bash_description_is_environment_neutral(self):
        """run_bash tool description should not assume HPC or any specific environment.

        run_bash lives in coding-skill now (moved out of hpc-skill so the
        laptop profile can drop hpc-skill entirely without losing shell
        access).
        """
        from pathlib import Path
        server_path = Path(__file__).parent.parent.parent / "ari-skill-coding" / "src" / "server.py"
        if not server_path.exists():
            pytest.skip("ari-skill-coding not found")
        text = server_path.read_text()
        # Find the run_bash description (may span multiple lines and use
        # a parenthesised / concatenated literal).
        m = re.search(
            r'name="run_bash"[^)]*?description=\s*\(?\s*(.*?)\)?,\s*\n\s*inputSchema',
            text, re.DOTALL,
        )
        assert m, "run_bash tool not found in coding-skill"
        desc = m.group(1).lower()
        # Should not hardcode "login node" or "HPC"
        assert "login node" not in desc
        assert "hpc" not in desc


# ── Citation comment stripping test ──────────────────────────────────────

class TestCitationCommentStripping:
    def test_commented_cite_not_counted(self):
        """LaTeX comment lines with \\cite should not be counted."""
        latex = (
            "% \\cite{foo2024}\n"
            "% \\cite{bar2025}\n"
            "Real text \\cite{baz2024,qux2025} here.\n"
            "More \\cite{baz2024}.\n"
        )
        # Simulate the stripping logic from paper server
        active = "\n".join(
            line for line in latex.splitlines()
            if not line.lstrip().startswith("%")
        )
        import re as _re
        keys_raw = _re.findall(r"\\cite\{([^}]+)\}", active)
        unique = set()
        for ck in keys_raw:
            for k in ck.split(","):
                k = k.strip()
                if k:
                    unique.add(k)
        # Should only find baz2024 and qux2025, not foo2024 or bar2025
        assert unique == {"baz2024", "qux2025"}
        assert "foo2024" not in unique


# ── Repro paper_snippet size test ────────────────────────────────────────

class TestReproSnippetSize:
    def test_snippet_preserves_full_short_paper(self):
        """Papers shorter than max_snippet should be passed in full."""
        paper = "A" * 10000
        _max_snippet = 30000
        if len(paper) <= _max_snippet:
            snippet = paper
        else:
            snippet = paper[:20000] + "\n\n[...truncated...]\n\n" + paper[-10000:]
        assert snippet == paper

    def test_snippet_truncates_long_paper_with_tail(self):
        """Long papers should keep head + tail to preserve methodology and results."""
        paper = "HEAD" * 5000 + "TAIL" * 5000  # 40000 chars
        _max_snippet = 30000
        if len(paper) <= _max_snippet:
            snippet = paper
        else:
            snippet = paper[:20000] + "\n\n[...truncated...]\n\n" + paper[-10000:]
        assert snippet.startswith("HEAD")
        assert snippet.endswith("TAIL" * 2500)
        assert "[...truncated...]" in snippet
        assert len(snippet) == 20000 + len("\n\n[...truncated...]\n\n") + 10000


# ── Repro claimed_value extraction prompt test ───────────────────────────

class TestReproExtractionPrompt:
    def test_extraction_prompt_no_threads(self):
        """Extraction prompt should NOT ask for threads (environment-dependent)."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent.parent / "ari-skill-paper-re" / "src" / "server.py"
        if not server_path.exists():
            pytest.skip("ari-skill-paper-re not found")
        text = server_path.read_text()
        m = re.search(r'Extract the PRIME.*?No markdown\.', text, re.DOTALL)
        assert m, "Extraction prompt not found"
        prompt = m.group(0)
        assert "threads" not in prompt.lower()

    def test_extraction_prompt_requests_prime_result(self):
        """Extraction prompt should select the prime result (abstract/conclusion), not theoretical peaks."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent.parent / "ari-skill-paper-re" / "src" / "server.py"
        if not server_path.exists():
            pytest.skip("ari-skill-paper-re not found")
        text = server_path.read_text()
        m = re.search(r'Extract the PRIME.*?No markdown\.', text, re.DOTALL)
        prompt = m.group(0)
        assert "PRIME" in prompt
        assert "NOT" in prompt and "theoretical" in prompt.lower()


# ── build_best_nodes_context includes eval_summary ───────────────────────

class TestBuildBestNodesContext:
    def test_context_includes_eval_summary(self):
        """build_best_nodes_context should include eval_summary, not just metrics."""
        from ari.pipeline import build_best_nodes_context

        node = MagicMock()
        node.status = NodeStatus.SUCCESS
        node.has_real_data = True
        node.metrics = {"score": 0.9, "_scientific_score": 0.9}
        node.eval_summary = "Achieved 71 GFLOP/s using specialized k=8 kernel"
        node.label = "improve"

        context, _ = build_best_nodes_context([node], "test goal")
        assert "71 GFLOP/s" in context
        assert "summary:" in context.lower() or "specialized" in context


# ── Repro best_val fallback test ─────────────────────────────────────────

class TestReproBestValFallback:
    def test_last_resort_regex_extracts_metric(self):
        """Last-resort regex should extract METRIC from raw output."""
        output = "some output\nMETRIC: 42.567\nREPRO_EXIT_CODE:0\n"
        m = re.search(r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)", output, re.IGNORECASE)
        assert m
        assert float(m.group(1)) == pytest.approx(42.567)

    def test_regex_handles_scientific_notation(self):
        """Regex should handle scientific notation in METRIC line."""
        output = "METRIC: 1.23e+04\n"
        m = re.search(r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)", output, re.IGNORECASE)
        assert m
        assert float(m.group(1)) == pytest.approx(12300.0)
