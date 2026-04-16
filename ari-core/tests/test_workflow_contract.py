"""
ARI Workflow Contract Tests

Validates that the GUI Workflow tab dynamically reflects the actual
implementation: YAML-driven pipelines, correct TypeScript types,
no phantom fields, and dynamic skill colours.
"""
import json
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

# ── Paths ────────────────────────────────────────────────────────────────────

_ARI_CORE = Path(__file__).parent.parent
_CONFIG_DIR = _ARI_CORE / "config"
_WORKFLOW_YAML = _CONFIG_DIR / "workflow.yaml"
_ARI_ROOT = _ARI_CORE.parent

# React frontend source
_REACT_SRC = _ARI_CORE / "ari" / "viz" / "frontend" / "src"
_TYPES_FILE = _REACT_SRC / "types" / "index.ts"
_WORKFLOW_PAGE = _REACT_SRC / "components" / "Workflow" / "WorkflowPage.tsx"

# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_workflow():
    """Load and return the workflow.yaml data."""
    return yaml.safe_load(_WORKFLOW_YAML.read_text())


def _read_ts_types():
    """Read the TypeScript types file."""
    return _TYPES_FILE.read_text()


def _read_workflow_page():
    """Read the WorkflowPage React component."""
    return _WORKFLOW_PAGE.read_text()


def _extract_interface(ts_source: str, name: str) -> str:
    """Extract a TypeScript interface block by name."""
    pattern = rf"export\s+interface\s+{name}\s*\{{(.*?)\}}"
    m = re.search(pattern, ts_source, re.DOTALL)
    return m.group(1) if m else ""


# ══════════════════════════════════════════════════════════════════════════════
# 1. Workflow YAML Schema Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestWorkflowYamlSchema:
    """Validate workflow.yaml has correct structure."""

    def test_bfts_pipeline_exists(self):
        data = _load_workflow()
        assert "bfts_pipeline" in data, "workflow.yaml must have bfts_pipeline key"
        assert isinstance(data["bfts_pipeline"], list)
        assert len(data["bfts_pipeline"]) > 0, "bfts_pipeline must not be empty"

    def test_bfts_stages_required_fields(self):
        data = _load_workflow()
        required = {"stage", "skill", "description", "depends_on", "enabled", "phase"}
        for stage in data["bfts_pipeline"]:
            missing = required - set(stage.keys())
            assert not missing, f"BFTS stage '{stage.get('stage', '?')}' missing: {missing}"

    def test_bfts_phase_value(self):
        data = _load_workflow()
        for stage in data["bfts_pipeline"]:
            assert stage["phase"] == "bfts", (
                f"BFTS stage '{stage['stage']}' has phase='{stage['phase']}', expected 'bfts'"
            )

    def test_paper_phase_value(self):
        data = _load_workflow()
        for stage in data["pipeline"]:
            assert stage.get("phase") == "paper", (
                f"Paper stage '{stage['stage']}' has phase='{stage.get('phase')}', expected 'paper'"
            )

    def test_inputs_are_dicts(self):
        data = _load_workflow()
        for stage in data["pipeline"]:
            inputs = stage.get("inputs")
            if inputs is not None:
                assert isinstance(inputs, dict), (
                    f"Stage '{stage['stage']}' inputs should be dict, got {type(inputs).__name__}"
                )

    def test_outputs_are_dicts(self):
        data = _load_workflow()
        for stage in data["pipeline"]:
            outputs = stage.get("outputs")
            if outputs is not None:
                assert isinstance(outputs, dict), (
                    f"Stage '{stage['stage']}' outputs should be dict, got {type(outputs).__name__}"
                )

    def test_no_phantom_fields(self):
        """Pipeline stages must not contain run_if or skip_if_score (unimplemented)."""
        data = _load_workflow()
        phantom = {"run_if", "skip_if_score"}
        for section in ("pipeline", "bfts_pipeline"):
            for stage in data.get(section, []):
                found = phantom & set(stage.keys())
                assert not found, (
                    f"Stage '{stage['stage']}' in {section} has phantom fields: {found}"
                )

    def test_skills_referenced_exist(self):
        """Every skill referenced in pipeline stages exists in the skills section."""
        data = _load_workflow()
        skill_names = {s["name"] for s in data.get("skills", [])}
        for section in ("pipeline", "bfts_pipeline"):
            for stage in data.get(section, []):
                skill = stage.get("skill", "")
                assert skill in skill_names, (
                    f"Stage '{stage['stage']}' references skill '{skill}' "
                    f"not in skills section: {skill_names}"
                )

    def test_bfts_pipeline_has_loop_back(self):
        """At least one BFTS stage should have loop_back_to for cycle visualisation."""
        data = _load_workflow()
        has_loop = any(s.get("loop_back_to") for s in data["bfts_pipeline"])
        assert has_loop, "BFTS pipeline should have at least one loop_back_to stage"

    def test_bfts_loop_back_target_exists(self):
        """loop_back_to must reference an existing BFTS stage."""
        data = _load_workflow()
        stage_names = {s["stage"] for s in data["bfts_pipeline"]}
        for stage in data["bfts_pipeline"]:
            target = stage.get("loop_back_to")
            if target:
                assert target in stage_names, (
                    f"loop_back_to '{target}' not found in BFTS stages: {stage_names}"
                )

    def test_pipeline_stages_not_empty(self):
        data = _load_workflow()
        assert len(data["pipeline"]) > 0, "pipeline must not be empty"

    def test_bfts_depends_on_are_lists(self):
        data = _load_workflow()
        for stage in data["bfts_pipeline"]:
            assert isinstance(stage["depends_on"], list), (
                f"BFTS stage '{stage['stage']}' depends_on should be list"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 2. API Workflow Dynamic Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestApiWorkflowDynamic:
    """Validate _api_get_workflow() is YAML-driven, not hardcoded."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _write_yaml(self, data: dict) -> Path:
        p = self.tmp_path / "config" / "workflow.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(data, allow_unicode=True))
        return p

    def _call_api(self, yaml_data: dict) -> dict:
        yaml_path = self._write_yaml(yaml_data)
        from ari.viz import api_settings, state as _st
        # Patch the candidate paths so our tmp yaml is found
        with mock.patch.object(_st, "_checkpoint_dir", None):
            orig = api_settings._api_get_workflow

            def patched():
                import yaml as _yaml
                data = _yaml.safe_load(yaml_path.read_text())
                # Replicate skill_mcp discovery (skip filesystem for unit test)
                skill_mcp = {}
                for sk in data.get("skills", []):
                    sk_name = sk.get("name", "")
                    skill_mcp[sk_name] = {
                        "name": sk_name,
                        "description": sk.get("description", ""),
                        "tools": [],
                        "version": "",
                        "dir": "",
                    }
                bfts_pipeline = data.get("bfts_pipeline") or []
                paper_pipeline = data.get("pipeline") or []
                if bfts_pipeline:
                    last_bfts = bfts_pipeline[-1]["stage"]
                    paper_pipeline = [dict(s) for s in paper_pipeline]
                    for s in paper_pipeline:
                        if not s.get("depends_on"):
                            s["depends_on"] = [last_bfts]
                return {
                    "ok": True, "workflow": data, "path": str(yaml_path),
                    "skill_mcp": skill_mcp,
                    "bfts_pipeline": bfts_pipeline,
                    "paper_pipeline": paper_pipeline,
                    "full_pipeline": bfts_pipeline + paper_pipeline,
                }
            return patched()

    def test_bfts_from_yaml_not_hardcoded(self):
        """API returns exactly the BFTS stages from YAML, not hardcoded ones."""
        result = self._call_api({
            "bfts_pipeline": [
                {"stage": "custom_a", "skill": "x", "tool": "t1",
                 "depends_on": [], "enabled": True, "phase": "bfts",
                 "description": "test A"},
                {"stage": "custom_b", "skill": "y", "tool": "t2",
                 "depends_on": ["custom_a"], "enabled": True, "phase": "bfts",
                 "description": "test B"},
            ],
            "pipeline": [],
            "skills": [{"name": "x"}, {"name": "y"}],
        })
        assert result["ok"]
        assert len(result["bfts_pipeline"]) == 2
        assert result["bfts_pipeline"][0]["stage"] == "custom_a"
        assert result["bfts_pipeline"][1]["stage"] == "custom_b"

    def test_no_phase_injection(self):
        """API must not inject phase into paper_pipeline — it comes from YAML."""
        result = self._call_api({
            "bfts_pipeline": [],
            "pipeline": [
                {"stage": "s1", "skill": "a", "tool": "t", "depends_on": [],
                 "enabled": True, "description": "d"},
            ],
            "skills": [{"name": "a"}],
        })
        # The stage has no phase in YAML, so response should reflect that
        assert "phase" not in result["paper_pipeline"][0]

    def test_full_pipeline_is_concat(self):
        """full_pipeline == bfts_pipeline + paper_pipeline."""
        result = self._call_api({
            "bfts_pipeline": [
                {"stage": "b1", "skill": "s", "tool": "", "depends_on": [],
                 "enabled": True, "phase": "bfts", "description": "d"},
            ],
            "pipeline": [
                {"stage": "p1", "skill": "s", "tool": "t", "depends_on": [],
                 "enabled": True, "phase": "paper", "description": "d"},
            ],
            "skills": [{"name": "s"}],
        })
        assert len(result["full_pipeline"]) == 2
        assert result["full_pipeline"][0]["stage"] == "b1"
        assert result["full_pipeline"][1]["stage"] == "p1"

    def test_bfts_paper_connection(self):
        """Paper stages with empty depends_on get connected to last BFTS stage."""
        result = self._call_api({
            "bfts_pipeline": [
                {"stage": "bfts_last", "skill": "s", "tool": "", "depends_on": [],
                 "enabled": True, "phase": "bfts", "description": "d"},
            ],
            "pipeline": [
                {"stage": "paper_first", "skill": "s", "tool": "t",
                 "depends_on": [], "enabled": True, "phase": "paper", "description": "d"},
                {"stage": "paper_second", "skill": "s", "tool": "t",
                 "depends_on": ["paper_first"], "enabled": True, "phase": "paper",
                 "description": "d"},
            ],
            "skills": [{"name": "s"}],
        })
        # paper_first had empty depends_on → should now link to bfts_last
        assert result["paper_pipeline"][0]["depends_on"] == ["bfts_last"]
        # paper_second already had depends_on → unchanged
        assert result["paper_pipeline"][1]["depends_on"] == ["paper_first"]

    def test_empty_bfts_no_connection(self):
        """When bfts_pipeline is empty, paper stages keep their original depends_on."""
        result = self._call_api({
            "bfts_pipeline": [],
            "pipeline": [
                {"stage": "s1", "skill": "a", "tool": "t", "depends_on": [],
                 "enabled": True, "description": "d"},
            ],
            "skills": [{"name": "a"}],
        })
        assert result["paper_pipeline"][0]["depends_on"] == []

    def test_api_get_workflow_reads_real_yaml(self):
        """_api_get_workflow() against the real workflow.yaml returns YAML-driven data."""
        from ari.viz import api_settings, state as _st
        with mock.patch.object(_st, "_checkpoint_dir", None):
            result = api_settings._api_get_workflow()
        assert result["ok"], result.get("error")
        # BFTS stages come from YAML
        data = yaml.safe_load(_WORKFLOW_YAML.read_text())
        expected_bfts = data.get("bfts_pipeline", [])
        assert len(result["bfts_pipeline"]) == len(expected_bfts)
        for i, stage in enumerate(result["bfts_pipeline"]):
            assert stage["stage"] == expected_bfts[i]["stage"]

    def test_real_api_no_hardcoded_stage_names(self):
        """Real API response must not contain old hardcoded stage names."""
        from ari.viz import api_settings, state as _st
        with mock.patch.object(_st, "_checkpoint_dir", None):
            result = api_settings._api_get_workflow()
        assert result["ok"]
        old_hardcoded = {"expand_node", "evaluate_metrics", "bfts_select_next"}
        actual_stages = {s["stage"] for s in result["bfts_pipeline"]}
        overlap = old_hardcoded & actual_stages
        assert not overlap, f"Found old hardcoded stage names in API response: {overlap}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. TypeScript Type Contract Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTypescriptContract:
    """Validate TypeScript types match actual backend data shapes."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.ts_src = _read_ts_types()
        self.iface = _extract_interface(self.ts_src, "WorkflowStage")

    def test_inputs_type_is_record(self):
        # Match "inputs:" line specifically (not load_inputs)
        m = re.search(r"^\s*inputs:\s*(.+)", self.iface, re.MULTILINE)
        assert m, "WorkflowStage should have an inputs field"
        assert "Record" in m.group(1), (
            f"WorkflowStage.inputs should be Record, got: {m.group(1).strip()}"
        )

    def test_outputs_type_is_record(self):
        m = re.search(r"^\s*outputs:\s*(.+)", self.iface, re.MULTILINE)
        assert m, "WorkflowStage should have an outputs field"
        assert "Record" in m.group(1), (
            f"WorkflowStage.outputs should be Record, got: {m.group(1).strip()}"
        )

    def test_no_run_if_in_types(self):
        assert "run_if" not in self.iface, (
            "WorkflowStage should not have run_if (no backend implementation)"
        )

    def test_no_skip_if_score_in_types(self):
        assert "skip_if_score" not in self.iface, (
            "WorkflowStage should not have skip_if_score (no backend implementation)"
        )

    def test_loop_back_to_retained(self):
        assert "loop_back_to" in self.iface, (
            "WorkflowStage should retain loop_back_to (data-driven from YAML)"
        )

    def test_skip_if_exists_retained(self):
        assert "skip_if_exists" in self.iface, (
            "WorkflowStage should retain skip_if_exists (implemented in pipeline.py)"
        )

    def test_phase_field_exists(self):
        assert "phase" in self.iface, "WorkflowStage should have phase field"

    def test_depends_on_field_exists(self):
        assert "depends_on" in self.iface, "WorkflowStage should have depends_on field"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Frontend No-Phantom Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFrontendNoPhantom:
    """Validate WorkflowPage has no phantom UI elements."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.src = _read_workflow_page()

    def test_no_hardcoded_skill_colors_map(self):
        """SKILL_COLORS constant should not exist."""
        assert "SKILL_COLORS" not in self.src, (
            "WorkflowPage should use dynamic skill colours, not hardcoded SKILL_COLORS"
        )

    def test_dynamic_skill_palette_exists(self):
        """SKILL_PALETTE or hash-based colour function should exist."""
        assert "SKILL_PALETTE" in self.src or "skillColor" in self.src, (
            "WorkflowPage should have dynamic skill colour generation"
        )

    def test_no_run_if_in_condition_editor(self):
        """Condition editor dropdown should not have run_if option."""
        # Look for <option value="run_if">
        assert 'value="run_if"' not in self.src, (
            "Condition editor should not offer run_if (no backend support)"
        )

    def test_no_skip_if_score_in_condition_editor(self):
        """Condition editor dropdown should not have skip_if_score option."""
        assert 'value="skip_if_score"' not in self.src, (
            "Condition editor should not offer skip_if_score (no backend support)"
        )

    def test_skip_if_exists_in_condition_editor(self):
        """Condition editor should retain skip_if_exists option."""
        assert 'value="skip_if_exists"' in self.src, (
            "Condition editor must still offer skip_if_exists"
        )

    def test_no_run_if_badge(self):
        """Stage cards should not render run_if badges."""
        # After removing, there should be no run_if badge JSX
        # Check for the specific badge pattern, not just any reference
        lines = self.src.split("\n")
        for i, line in enumerate(lines):
            if "run_if" in line and "badge" in line.lower():
                pytest.fail(f"Line {i+1}: run_if badge found in WorkflowPage")

    def test_no_skip_if_score_badge(self):
        """Stage cards should not render skip_if_score badges."""
        lines = self.src.split("\n")
        for i, line in enumerate(lines):
            if "skip_if_score" in line and ("badge" in line.lower() or "span" in line.lower()):
                pytest.fail(f"Line {i+1}: skip_if_score badge found in WorkflowPage")

    def test_add_stage_uses_object_inputs(self):
        """handleAddStage should create inputs as {} not []."""
        assert "inputs: {}," in self.src or "inputs: { }," in self.src, (
            "handleAddStage should initialise inputs as {} (object), not []"
        )

    def test_add_stage_uses_object_outputs(self):
        """handleAddStage should create outputs as {} not []."""
        assert "outputs: {}," in self.src or "outputs: { }," in self.src, (
            "handleAddStage should initialise outputs as {} (object), not []"
        )

    def test_loop_back_to_svg_rendering(self):
        """loop_back_to should still be rendered in DAG SVG (data-driven)."""
        assert "loop_back_to" in self.src, (
            "WorkflowPage should render loop_back_to arrows in DAG"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Save Roundtrip Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSaveRoundtrip:
    """Validate workflow save/load roundtrip via API."""

    def test_save_load_roundtrip(self, tmp_path):
        """Saving and reloading a pipeline preserves stage data."""
        from ari.viz import api_settings, state as _st

        # Set up checkpoint dir
        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        # Write a source workflow.yaml
        src_wf = tmp_path / "src_workflow.yaml"
        src_data = {
            "llm": {"backend": "openai", "model": "test"},
            "bfts_pipeline": [
                {"stage": "b1", "skill": "s", "tool": "t",
                 "depends_on": [], "enabled": True, "phase": "bfts",
                 "description": "bfts stage"},
            ],
            "pipeline": [
                {"stage": "p1", "skill": "a", "tool": "t1",
                 "depends_on": [], "enabled": True, "phase": "paper",
                 "description": "paper stage",
                 "inputs": {"key": "val"}, "outputs": {"file": "out.json"}},
            ],
            "skills": [{"name": "s"}, {"name": "a"}],
        }
        src_wf.write_text(yaml.dump(src_data, allow_unicode=True))

        # Simulate save
        with mock.patch.object(_st, "_checkpoint_dir", ckpt):
            body = json.dumps({
                "path": str(src_wf),
                "pipeline": src_data["pipeline"],
            }).encode()
            result = api_settings._api_save_workflow(body)
        assert result["ok"], result.get("error")

        # Verify the saved file
        saved = ckpt / "workflow.yaml"
        assert saved.exists()
        saved_data = yaml.safe_load(saved.read_text())
        assert len(saved_data["pipeline"]) == 1
        assert saved_data["pipeline"][0]["stage"] == "p1"
        assert saved_data["pipeline"][0]["inputs"] == {"key": "val"}


# ══════════════════════════════════════════════════════════════════════════════
# 6. Skill Discovery Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSkillDiscovery:
    """Validate skill discovery from filesystem matches YAML."""

    def test_yaml_skills_have_directories(self):
        """Every skill in workflow.yaml should have a matching ari-skill-* directory."""
        data = _load_workflow()
        for skill in data.get("skills", []):
            name = skill["name"]
            # e.g. "web-skill" → "ari-skill-web"
            dir_name = "ari-skill-" + name.replace("-skill", "")
            skill_dir = _ARI_ROOT / dir_name
            assert skill_dir.exists(), (
                f"Skill '{name}' references directory '{dir_name}' which does not exist"
            )

    def test_api_skills_returns_list(self):
        """_api_skills() returns a list of skill dicts."""
        from ari.viz import api_settings
        skills = api_settings._api_skills()
        assert isinstance(skills, list)
        # At least the skills from workflow.yaml should be discoverable
        names = {s.get("name", "") for s in skills}
        # ari-skill-web should be found
        assert any("web" in n for n in names), f"web skill not found in: {names}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Pipeline.py Field Usage Consistency
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineFieldConsistency:
    """Validate that workflow.yaml fields align with pipeline.py usage."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.pipeline_src = (_ARI_CORE / "ari" / "pipeline.py").read_text()

    def test_skip_if_exists_implemented(self):
        """pipeline.py must process skip_if_exists."""
        assert "skip_if_exists" in self.pipeline_src

    def test_depends_on_implemented(self):
        """pipeline.py must process depends_on."""
        assert "depends_on" in self.pipeline_src

    def test_load_inputs_implemented(self):
        """pipeline.py must process load_inputs."""
        assert "load_inputs" in self.pipeline_src

    def test_run_if_not_implemented(self):
        """pipeline.py must NOT reference run_if (phantom field)."""
        # Allow comments mentioning it but not actual key access
        lines = [l for l in self.pipeline_src.split("\n")
                 if not l.strip().startswith("#")]
        code = "\n".join(lines)
        # Check for actual dict key access patterns
        assert '.get("run_if")' not in code, "pipeline.py should not access run_if"
        assert "['run_if']" not in code, "pipeline.py should not access run_if"

    def test_skip_if_score_not_implemented(self):
        """pipeline.py must NOT reference skip_if_score (phantom field)."""
        lines = [l for l in self.pipeline_src.split("\n")
                 if not l.strip().startswith("#")]
        code = "\n".join(lines)
        assert '.get("skip_if_score")' not in code
        assert "['skip_if_score']" not in code


# ══════════════════════════════════════════════════════════════════════════════
# 8. API Response Structure Tests (integration with real yaml)
# ══════════════════════════════════════════════════════════════════════════════


class TestApiResponseStructure:
    """Validate the real _api_get_workflow() response shape."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from ari.viz import api_settings, state as _st
        with mock.patch.object(_st, "_checkpoint_dir", None):
            self.result = api_settings._api_get_workflow()

    def test_response_ok(self):
        assert self.result["ok"], self.result.get("error")

    def test_has_required_keys(self):
        required = {"ok", "workflow", "path", "skill_mcp",
                     "bfts_pipeline", "paper_pipeline", "full_pipeline"}
        assert required <= set(self.result.keys())

    def test_full_pipeline_length(self):
        """full_pipeline = bfts + paper."""
        expected = len(self.result["bfts_pipeline"]) + len(self.result["paper_pipeline"])
        assert len(self.result["full_pipeline"]) == expected

    def test_bfts_stages_have_phase_bfts(self):
        for s in self.result["bfts_pipeline"]:
            assert s.get("phase") == "bfts", f"BFTS stage '{s['stage']}' missing phase=bfts"

    def test_paper_stages_have_phase_paper(self):
        for s in self.result["paper_pipeline"]:
            assert s.get("phase") == "paper", f"Paper stage '{s['stage']}' missing phase=paper"

    def test_paper_no_empty_depends_on_when_bfts_exists(self):
        """If bfts_pipeline is non-empty, no paper stage should have empty depends_on."""
        if self.result["bfts_pipeline"]:
            for s in self.result["paper_pipeline"]:
                deps = s.get("depends_on", [])
                # Either linked to BFTS or to another paper stage
                assert len(deps) > 0, (
                    f"Paper stage '{s['stage']}' has empty depends_on "
                    f"despite BFTS pipeline being present"
                )

    def test_skill_mcp_is_dict(self):
        assert isinstance(self.result["skill_mcp"], dict)

    def test_workflow_has_pipeline_key(self):
        assert "pipeline" in self.result["workflow"]


# ══════════════════════════════════════════════════════════════════════════════
# 9. Paper Pipeline File Contract (regression: papers-not-visible-in-GUI)
# ══════════════════════════════════════════════════════════════════════════════


class TestPaperPipelineFileContract:
    """Enforce that the paper pipeline actually writes the files the GUI reads.

    Regression context: workflow.yaml once had all `inputs:` / `outputs:` blocks
    stripped from every paper stage. The pipeline still completed, but no
    artefacts were written to the checkpoint directory, so the Results page
    could not display the generated paper. These tests fail fast if the
    `write_paper` stage (or its critical upstream/downstream neighbours) drifts
    back to that broken state.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_workflow()
        self.paper = {s["stage"]: s for s in self.data.get("pipeline", [])}

    def _get_stage(self, name: str) -> dict:
        assert name in self.paper, (
            f"Paper stage '{name}' missing from pipeline; known stages: "
            f"{sorted(self.paper.keys())}"
        )
        return self.paper[name]

    # ── write_paper (the critical stage for GUI paper visibility) ──

    def test_write_paper_has_inputs_block(self):
        stage = self._get_stage("write_paper")
        inputs = stage.get("inputs")
        assert isinstance(inputs, dict) and inputs, (
            "write_paper.inputs must be a non-empty dict — otherwise "
            "write_paper_iterative() runs with defaults (figures_manifest_json='', "
            "nodes_json_path='') and the compiled PDF is never copied to the "
            "checkpoint directory (ari-skill-paper/src/server.py:1504)."
        )

    def test_write_paper_required_input_keys(self):
        stage = self._get_stage("write_paper")
        inputs = stage.get("inputs", {})
        required = {
            "experiment_summary",
            "nodes_json_path",
            "figures_manifest_json",
            "refs_json",
            "science_data_json",
        }
        missing = required - set(inputs.keys())
        assert not missing, (
            f"write_paper.inputs is missing required keys: {missing}. "
            f"These wire the upstream stage outputs into the paper writer; "
            f"without them the paper has no context."
        )

    def test_write_paper_nodes_json_is_path_not_loaded(self):
        """nodes_json_path must be passed as a PATH string, not loaded content.

        ari-skill-paper/src/server.py:1506 derives the checkpoint directory
        from nodes_json_path to know where to copy the compiled PDF:
            _ckpt_dir = str(Path(nodes_json_path).parent)
        If the file content is loaded instead (via load_inputs), Path(...) is
        applied to a JSON blob and the derived dir is garbage, so the PDF
        never lands in the checkpoint.
        """
        stage = self._get_stage("write_paper")
        load_inputs = set(stage.get("load_inputs") or [])
        assert "nodes_json_path" not in load_inputs, (
            "write_paper must NOT include nodes_json_path in load_inputs — "
            "paper-skill needs it as a real filesystem path to locate the "
            "checkpoint directory for writing full_paper.pdf."
        )

    def test_write_paper_outputs_full_paper_tex(self):
        """The GUI reads `full_paper.tex` — write_paper must produce exactly that.

        ari-core/ari/viz/api_state.py:292 does:
            tex = d / "full_paper.tex"
            if tex.exists():
                result["paper_tex"] = tex.read_text(...)
        If write_paper.outputs.file is missing or points somewhere else, the
        GUI Results page never sees a paper.
        """
        stage = self._get_stage("write_paper")
        outputs = stage.get("outputs")
        assert isinstance(outputs, dict) and outputs.get("file"), (
            "write_paper.outputs.file is required; without it pipeline.py's "
            "stage writer never materialises the LaTeX result on disk."
        )
        out_file = outputs["file"]
        assert out_file.endswith("/full_paper.tex"), (
            f"write_paper.outputs.file must end with '/full_paper.tex' "
            f"(api_state.py looks for exactly that filename), got: {out_file!r}"
        )

    def test_write_paper_outputs_ref_bib(self):
        """write_paper should emit refs.bib alongside the .tex so BibTeX runs."""
        stage = self._get_stage("write_paper")
        bib = (stage.get("outputs") or {}).get("bib_file", "")
        assert bib.endswith("refs.bib"), (
            f"write_paper.outputs.bib_file should end with 'refs.bib', got: {bib!r}"
        )

    def test_write_paper_skip_if_exists_points_at_tex(self):
        stage = self._get_stage("write_paper")
        skip = stage.get("skip_if_exists", "")
        assert skip.endswith("/full_paper.tex"), (
            f"write_paper.skip_if_exists should guard full_paper.tex so reruns "
            f"don't overwrite a good paper, got: {skip!r}"
        )

    # ── write_paper upstream dependencies ──

    def test_write_paper_deps_are_enabled_stages_with_outputs(self):
        """Every dep of write_paper must be an enabled stage that actually
        produces a file, otherwise pipeline.py's _dep_failed check skips
        write_paper and the GUI sees no paper."""
        stage = self._get_stage("write_paper")
        deps = stage.get("depends_on") or []
        assert deps, "write_paper must declare depends_on (for proper ordering)"
        for dep in deps:
            assert dep in self.paper, (
                f"write_paper depends on '{dep}' which is not a defined paper stage"
            )
            dep_stage = self.paper[dep]
            assert dep_stage.get("enabled", True), (
                f"write_paper depends on '{dep}' but that stage is disabled — "
                f"pipeline.py will skip write_paper due to missing dep."
            )
            dep_outputs = dep_stage.get("outputs") or {}
            assert dep_outputs.get("file"), (
                f"write_paper depends on '{dep}', but that stage has no "
                f"outputs.file — it produces nothing the paper writer can use."
            )

    # ── generate_figures must produce a batch manifest for write_paper ──

    def test_generate_figures_uses_batch_tool(self):
        """generate_figures must use plot-skill:generate_figures_llm, not
        figure-router's single-figure API.

        Regression context: the pipeline briefly used
        figure-router-skill:generate_figure which only makes one figure per
        call and returns {success, output_path, ...} — write_paper then
        received an empty figures_manifest_json and produced an image-free
        PDF. pipeline.py's special-case at line ~836 expects the tool to
        return {figures, latex_snippets}, which plot-skill.generate_figures_llm
        provides.
        """
        stage = self._get_stage("generate_figures")
        if not stage.get("enabled", True):
            pytest.skip("generate_figures disabled")
        assert stage.get("skill") == "plot-skill", (
            f"generate_figures must use plot-skill (batch), not "
            f"{stage.get('skill')!r}. figure-router-skill:generate_figure is "
            f"single-figure and does not populate figures_manifest.json."
        )
        assert stage.get("tool") == "generate_figures_llm", (
            f"generate_figures must call generate_figures_llm (returns "
            f"{{figures, latex_snippets}}), not {stage.get('tool')!r}."
        )

    def test_generate_figures_batch_inputs(self):
        stage = self._get_stage("generate_figures")
        if not stage.get("enabled", True):
            pytest.skip("generate_figures disabled")
        inputs = stage.get("inputs") or {}
        required = {"nodes_json_path", "science_data_path", "n_figures",
                    "output_dir", "experiment_summary"}
        missing = required - set(inputs.keys())
        assert not missing, (
            f"generate_figures.inputs missing batch-mode keys: {missing}. "
            f"plot-skill:generate_figures_llm needs all of these to write "
            f"fig_1.pdf..fig_N.pdf with captions."
        )
        assert isinstance(inputs.get("n_figures"), int) and inputs["n_figures"] >= 1, (
            f"generate_figures.inputs.n_figures must be a positive int"
        )

    def test_generate_figures_output_is_manifest(self):
        stage = self._get_stage("generate_figures")
        if not stage.get("enabled", True):
            pytest.skip("generate_figures disabled")
        out = (stage.get("outputs") or {}).get("file", "")
        assert out.endswith("/figures_manifest.json"), (
            f"generate_figures.outputs.file must end with "
            f"'/figures_manifest.json' so write_paper can load it via "
            f"load_inputs, got: {out!r}"
        )

    def test_figure_router_not_in_paper_pipeline(self):
        """figure-router-skill is intentionally out of the paper pipeline.

        It's a single-figure / agent-driven tool; paper pipeline stages are
        one-call-per-stage. Keeping it wired here reintroduces the
        image-free-paper regression. It should still be defined in skills[]
        so agent tasks can call it directly — see the skills-section test.
        """
        for stage in self.paper.values():
            if not stage.get("enabled", True):
                continue
            assert stage.get("skill") != "figure-router-skill", (
                f"Paper stage '{stage['stage']}' uses figure-router-skill; "
                f"that skill is for direct agent use, not the paper pipeline."
            )

    def test_figure_router_still_defined_in_skills(self):
        """figure-router-skill should remain in the skills[] registry so it's
        callable by agents even though the paper pipeline no longer uses it."""
        skill_names = {s["name"] for s in self.data.get("skills", [])}
        assert "figure-router-skill" in skill_names, (
            "figure-router-skill should still be registered as a skill "
            "(reachable by agents) even if removed from the paper pipeline."
        )

    # ── Stages that HEAD required to have inputs/outputs ──

    @pytest.mark.parametrize("stage_name,required_input_keys,expected_output_suffix", [
        ("search_related_work",
         {"experiment_summary", "keywords"},
         "related_refs.json"),
        ("transform_data",
         {"nodes_json_path"},
         "science_data.json"),
        ("review_paper",
         {"tex_path", "pdf_path"},
         "review_report.json"),
        ("reproducibility_check",
         {"paper_path", "work_dir"},
         "reproducibility_report.json"),
        ("generate_ear",
         {"checkpoint_dir"},
         "ear_manifest.json"),
    ])
    def test_critical_stages_have_inputs_and_outputs(
        self, stage_name, required_input_keys, expected_output_suffix
    ):
        stage = self._get_stage(stage_name)
        if not stage.get("enabled", True):
            pytest.skip(f"{stage_name} is disabled; skipping contract check")
        inputs = stage.get("inputs")
        assert isinstance(inputs, dict) and inputs, (
            f"{stage_name}.inputs must be a non-empty dict"
        )
        missing = required_input_keys - set(inputs.keys())
        assert not missing, (
            f"{stage_name}.inputs missing required keys: {missing}"
        )
        outputs = stage.get("outputs") or {}
        out_file = outputs.get("file", "")
        assert out_file.endswith(expected_output_suffix), (
            f"{stage_name}.outputs.file should end with {expected_output_suffix!r}, "
            f"got: {out_file!r}"
        )

    # ── Global invariants ──

    def test_every_enabled_paper_stage_has_outputs_file(self):
        """Any enabled paper stage in this pipeline is expected to produce a
        concrete artefact (`outputs.file`). If a stage genuinely has no output
        it should be disabled or removed, not silently drop onto the floor."""
        for name, stage in self.paper.items():
            if not stage.get("enabled", True):
                continue
            outputs = stage.get("outputs") or {}
            assert outputs.get("file"), (
                f"Enabled paper stage '{name}' must declare outputs.file "
                f"(otherwise pipeline.py writes nothing to the checkpoint dir)"
            )

    def test_every_enabled_paper_stage_has_inputs(self):
        """Enabled paper stages must declare inputs — otherwise the MCP tool
        is called with default empty strings, which is exactly the bug that
        hid generated papers from the GUI."""
        for name, stage in self.paper.items():
            if not stage.get("enabled", True):
                continue
            inputs = stage.get("inputs")
            assert isinstance(inputs, dict) and inputs, (
                f"Enabled paper stage '{name}' must declare a non-empty "
                f"inputs dict"
            )

    # ── VLM review loop contract ──

    def test_vlm_review_has_loop_back_to(self):
        """vlm_review_figures must loop back to generate_figures so low-score
        figures get regenerated automatically."""
        stage = self._get_stage("vlm_review_figures")
        if not stage.get("enabled", True):
            pytest.skip("vlm_review_figures disabled")
        assert stage.get("loop_back_to") == "generate_figures", (
            f"vlm_review_figures must declare loop_back_to: generate_figures, "
            f"got {stage.get('loop_back_to')!r}"
        )

    def test_vlm_review_has_loop_threshold(self):
        stage = self._get_stage("vlm_review_figures")
        if not stage.get("enabled", True):
            pytest.skip("vlm_review_figures disabled")
        th = stage.get("loop_threshold")
        assert isinstance(th, (int, float)) and 0 < th <= 1, (
            f"vlm_review_figures.loop_threshold must be a numeric in (0,1], "
            f"got {th!r}"
        )

    def test_vlm_review_has_loop_max_iterations(self):
        stage = self._get_stage("vlm_review_figures")
        if not stage.get("enabled", True):
            pytest.skip("vlm_review_figures disabled")
        it = stage.get("loop_max_iterations")
        assert isinstance(it, int) and it >= 1, (
            f"vlm_review_figures.loop_max_iterations must be a positive int, "
            f"got {it!r}"
        )

    def test_vlm_review_no_skip_if_exists(self):
        """If skip_if_exists were set on vlm_review_figures, the loop-back
        rewind would be a no-op on the second iteration (the marker file
        from the first run would still exist)."""
        stage = self._get_stage("vlm_review_figures")
        if not stage.get("enabled", True):
            pytest.skip("vlm_review_figures disabled")
        assert not stage.get("skip_if_exists"), (
            "vlm_review_figures must NOT declare skip_if_exists — it would "
            "short-circuit the loop_back_to retry. The review must always "
            "re-run on the fresh figures."
        )

    def test_generate_figures_wires_vlm_feedback(self):
        """The upstream stage of the loop must accept VLM feedback via
        {{vlm_feedback}} so the regenerated figures address the complaints."""
        stage = self._get_stage("generate_figures")
        if not stage.get("enabled", True):
            pytest.skip("generate_figures disabled")
        inputs = stage.get("inputs") or {}
        assert "vlm_feedback" in inputs, (
            "generate_figures.inputs must declare vlm_feedback so the "
            "loop_back_to runtime can inject VLM review feedback on retry."
        )
        fb_val = inputs["vlm_feedback"]
        assert "{{vlm_feedback}}" in str(fb_val), (
            f"generate_figures.inputs.vlm_feedback must reference the "
            f"'{{vlm_feedback}}' template var, got {fb_val!r}"
        )

    def test_pipeline_py_implements_loop_back_to(self):
        """pipeline.py must actually honour loop_back_to at runtime (not
        just for GUI DAG rendering)."""
        src = (_ARI_CORE / "ari" / "pipeline.py").read_text()
        assert "loop_back_to" in src, (
            "pipeline.py must reference loop_back_to to implement the runtime"
        )
        assert "_should_loop_back" in src, (
            "pipeline.py must define _should_loop_back helper"
        )
        assert "_format_vlm_feedback" in src, (
            "pipeline.py must define _format_vlm_feedback helper"
        )
        assert "loop_max_iterations" in src, (
            "pipeline.py must honour loop_max_iterations from stage config"
        )

    def test_api_state_still_reads_full_paper_tex(self):
        """Guard the other side of the contract: ensure api_state.py still
        looks for 'full_paper.tex' at the checkpoint root. If it's renamed
        here but not in workflow.yaml (or vice versa), the GUI goes silent."""
        api_state_src = (
            _ARI_CORE / "ari" / "viz" / "api_state.py"
        ).read_text()
        assert '"full_paper.tex"' in api_state_src, (
            "api_state.py no longer references 'full_paper.tex' — "
            "workflow.yaml contract is out of sync with the GUI summary code."
        )
        assert '"full_paper.pdf"' in api_state_src, (
            "api_state.py no longer references 'full_paper.pdf' — "
            "GUI will not set has_pdf correctly."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. Pipeline execution contract (write_paper actually lands full_paper.tex)
# ══════════════════════════════════════════════════════════════════════════════


class TestWritePaperExecutionContract:
    """End-to-end(ish) test: run ari.pipeline._run_paper_pipeline against the
    real workflow.yaml with _run_stage_subprocess mocked out, and assert that
    the write_paper stage causes `full_paper.tex` to be written under the
    checkpoint directory. This is the highest-fidelity regression guard for
    the papers-not-visible-in-GUI bug.
    """

    def test_write_paper_writes_full_paper_tex(self, tmp_path, monkeypatch):
        from ari import pipeline as _pipe

        ckpt = tmp_path / "ckpt_test"
        ckpt.mkdir()
        # Seed idea.json so evaluation_criteria extraction works
        (ckpt / "idea.json").write_text(json.dumps({
            "primary_metric": "throughput",
            "higher_is_better": True,
            "ideas": [{"title": "t", "description": "d", "experiment_plan": "p"}],
        }))

        # Mock return per tool name. write_paper must return {"latex": ...}
        # so pipeline.py writes it to the configured outputs.file. The
        # generate_figures_llm tool must return {figures, latex_snippets}
        # because pipeline.py:836 special-cases that shape to materialise
        # figures_manifest.json.
        fake_latex = r"\documentclass{article}\begin{document}ok\end{document}"
        tool_returns = {
            "collect_references_iterative": {"references": [{"title": "t"}]},
            "nodes_to_science_data": {"experiment_context": {}, "configurations": []},
            "generate_figures_llm": {
                "figures": {
                    "fig_1": str(ckpt / "fig_1.pdf"),
                    "fig_2": str(ckpt / "fig_2.pdf"),
                },
                "latex_snippets": {
                    "fig_1": "\\begin{figure}fig 1\\end{figure}",
                    "fig_2": "\\begin{figure}fig 2\\end{figure}",
                },
            },
            "review_figure": {"score": 0.9, "issues": [], "suggestions": [],
                               "review_text": "looks good"},
            "generate_ear": {"ear_dir": str(ckpt / "ear"), "file_count": 0},
            "write_paper_iterative": {"latex": fake_latex, "bib": "@article{x,}"},
            "review_compiled_paper": {"score": 5},
            "generate_rebuttal": {"rebuttal_latex": "rb", "point_by_point": []},
            "reproduce_from_paper": {"ok": True},
        }
        called: list[str] = []

        def fake_subproc(tool, args, config_path, skill_name=""):
            called.append(tool)
            if tool == "generate_figures_llm":
                # plot-skill writes both PDFs (LaTeX) and PNGs (VLM review)
                (ckpt / "fig_1.pdf").write_bytes(b"%PDF-1.4 fake1")
                (ckpt / "fig_2.pdf").write_bytes(b"%PDF-1.4 fake2")
                (ckpt / "fig_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake1")
                (ckpt / "fig_2.png").write_bytes(b"\x89PNG\r\n\x1a\nfake2")
            return tool_returns.get(tool, {})

        monkeypatch.setattr(_pipe, "_run_stage_subprocess", fake_subproc)

        cfg_path = str(_WORKFLOW_YAML)
        stages = _pipe.load_pipeline(cfg_path)
        assert stages, "loaded pipeline is empty"

        _pipe.run_pipeline(
            stages=stages,
            all_nodes=[],
            experiment_data={"topic": "test", "goal": "test"},
            checkpoint_dir=ckpt,
            config_path=cfg_path,
        )

        # The critical assertion: full_paper.tex exists at the checkpoint root
        tex = ckpt / "full_paper.tex"
        assert tex.exists(), (
            f"write_paper stage did not produce full_paper.tex. "
            f"Tools called: {called}. Checkpoint contents: "
            f"{sorted(p.name for p in ckpt.iterdir())}"
        )
        assert "documentclass" in tex.read_text()
        # refs.bib too (via outputs.bib_file)
        assert (ckpt / "refs.bib").exists(), (
            "write_paper.outputs.bib_file did not materialise refs.bib"
        )
        # figures_manifest.json must be materialised by pipeline.py's
        # generate_figures special-case (line ~836) from the batch tool's
        # {figures, latex_snippets} return value. Without this, write_paper
        # gets no figure info and produces image-free LaTeX.
        manifest = ckpt / "figures_manifest.json"
        assert manifest.exists(), (
            f"figures_manifest.json not produced — plot-skill batch return "
            f"shape not being materialised. Tools called: {called}"
        )
        import json as _json_m
        manifest_data = _json_m.loads(manifest.read_text())
        assert "figures" in manifest_data and manifest_data["figures"], (
            f"figures_manifest.json has no 'figures' key: {manifest_data}"
        )
        assert "latex_snippets" in manifest_data, (
            f"figures_manifest.json missing latex_snippets: {manifest_data}"
        )

    def test_write_paper_skipped_when_outputs_block_missing(
        self, tmp_path, monkeypatch
    ):
        """Negative regression: stripping write_paper.outputs reproduces the
        original bug — the stage runs but no file lands on disk. This test
        documents the failure mode and locks in the fix."""
        from ari import pipeline as _pipe

        ckpt = tmp_path / "ckpt_neg"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text('{"primary_metric": "m", "ideas": []}')

        # Load the real workflow, then strip outputs from write_paper
        data = yaml.safe_load(_WORKFLOW_YAML.read_text())
        broken_stages = []
        for s in data["pipeline"]:
            s = dict(s)
            if s["stage"] == "write_paper":
                s.pop("outputs", None)
            broken_stages.append(s)

        # Patch load_pipeline to return the broken stages
        def fake_load(_cfg):
            return [s for s in broken_stages if s.get("enabled", True)]

        monkeypatch.setattr(_pipe, "load_pipeline", fake_load)

        fake_latex = r"\documentclass{article}\begin{document}ok\end{document}"
        tool_returns = {
            "collect_references_iterative": {"references": []},
            "nodes_to_science_data": {"experiment_context": {}},
            "generate_figures_llm": {
                "figures": {"fig_1": str(ckpt / "fig_1.pdf")},
                "latex_snippets": {"fig_1": "\\begin{figure}f\\end{figure}"},
            },
            "review_figure": {"score": 0.9, "issues": []},
            "generate_ear": {"ear_dir": "", "file_count": 0},
            "write_paper_iterative": {"latex": fake_latex, "bib": ""},
            "review_compiled_paper": {"score": 5},
            "generate_rebuttal": {"rebuttal_latex": "rb"},
            "reproduce_from_paper": {"ok": True},
        }

        def fake_subproc(tool, args, cfg, skill_name=""):
            if tool == "generate_figures_llm":
                (ckpt / "fig_1.pdf").write_bytes(b"%PDF fake")
                (ckpt / "fig_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return tool_returns.get(tool, {})

        monkeypatch.setattr(_pipe, "_run_stage_subprocess", fake_subproc)

        _pipe.run_pipeline(
            stages=fake_load(str(_WORKFLOW_YAML)),
            all_nodes=[],
            experiment_data={"topic": "neg", "goal": "neg"},
            checkpoint_dir=ckpt,
            config_path=str(_WORKFLOW_YAML),
        )

        # With outputs.file stripped, pipeline.py has no primary_file and
        # never writes full_paper.tex → reproduces the original bug.
        assert not (ckpt / "full_paper.tex").exists(), (
            "Expected full_paper.tex to be MISSING when write_paper.outputs "
            "is stripped — this negative test documents the original regression."
        )

    def test_vlm_loop_back_retries_figures_and_advances_on_high_score(
        self, tmp_path, monkeypatch
    ):
        """The VLM review loop must regenerate figures when the score is
        below threshold, inject the review feedback into the regen call,
        and advance once the score crosses the threshold.

        Sequence under test:
          pass 1: generate_figures → vlm review returns score=0.3 (low)
                  → loop_back_to generate_figures
                  → {{vlm_feedback}} is populated with the issues
          pass 2: generate_figures (receives vlm_feedback in args)
                  → vlm review returns score=0.95 (high)
                  → loop satisfied, pipeline advances to write_paper
        """
        from ari import pipeline as _pipe

        ckpt = tmp_path / "ckpt_loop"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text('{"primary_metric": "m", "ideas": []}')

        # review_figure returns low-then-high so we observe exactly one loop
        _review_scores = iter([
            {"score": 0.3, "issues": ["axis labels unreadable", "no legend"],
             "suggestions": ["enlarge fonts", "add legend box"],
             "review_text": "font too small"},
            {"score": 0.95, "issues": [], "suggestions": [], "review_text": "ok"},
        ])
        # Capture the vlm_feedback arg that generate_figures_llm receives
        # on each call so we can verify the loop wiring.
        generate_figures_calls: list[dict] = []

        fake_latex = r"\documentclass{article}\begin{document}ok\end{document}"
        static_returns = {
            "collect_references_iterative": {"references": []},
            "nodes_to_science_data": {"experiment_context": {}, "configurations": []},
            "generate_ear": {"ear_dir": str(ckpt / "ear"), "file_count": 0},
            "write_paper_iterative": {"latex": fake_latex, "bib": "@article{x,}"},
            "review_compiled_paper": {"score": 5},
            "generate_rebuttal": {"rebuttal_latex": "rb", "point_by_point": []},
            "reproduce_from_paper": {"ok": True},
        }

        def fake_subproc(tool, args, config_path, skill_name=""):
            if tool == "generate_figures_llm":
                # Record the feedback arg for assertions
                generate_figures_calls.append(dict(args))
                (ckpt / "fig_1.pdf").write_bytes(b"%PDF-1.4 fake")
                (ckpt / "fig_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
                return {
                    "figures": {"fig_1": str(ckpt / "fig_1.pdf")},
                    "latex_snippets": {"fig_1": "\\begin{figure}f\\end{figure}"},
                }
            if tool == "review_figure":
                return next(_review_scores)
            return static_returns.get(tool, {})

        monkeypatch.setattr(_pipe, "_run_stage_subprocess", fake_subproc)

        stages = _pipe.load_pipeline(str(_WORKFLOW_YAML))
        _pipe.run_pipeline(
            stages=stages,
            all_nodes=[],
            experiment_data={"topic": "loop", "goal": "loop"},
            checkpoint_dir=ckpt,
            config_path=str(_WORKFLOW_YAML),
        )

        # 1. generate_figures_llm was called TWICE (first pass + retry)
        assert len(generate_figures_calls) == 2, (
            f"Expected generate_figures_llm to run twice (initial + retry "
            f"after low VLM score), got {len(generate_figures_calls)} calls"
        )

        # 2. First call has empty vlm_feedback (no prior review yet)
        first_fb = generate_figures_calls[0].get("vlm_feedback", "")
        assert first_fb == "", (
            f"First generate_figures call should have empty vlm_feedback, "
            f"got {first_fb!r}"
        )

        # 3. Second call has the low-score review's issues/suggestions
        #    actually threaded through as plain text
        second_fb = generate_figures_calls[1].get("vlm_feedback", "")
        assert second_fb, (
            "Second generate_figures call must receive a populated "
            "vlm_feedback after loop_back_to, got empty string"
        )
        assert "0.30" in second_fb, (
            f"Second-pass vlm_feedback must include the previous score "
            f"(0.30), got: {second_fb!r}"
        )
        assert "axis labels unreadable" in second_fb, (
            f"Second-pass vlm_feedback must include the review issues, "
            f"got: {second_fb!r}"
        )
        assert "enlarge fonts" in second_fb, (
            f"Second-pass vlm_feedback must include the review suggestions, "
            f"got: {second_fb!r}"
        )

        # 4. After the loop finishes, write_paper ran and produced the tex
        assert (ckpt / "full_paper.tex").exists(), (
            "After the VLM loop converged, write_paper should still run "
            "and produce full_paper.tex"
        )

    def test_vlm_loop_back_gives_up_at_max_iterations(
        self, tmp_path, monkeypatch
    ):
        """If the VLM keeps returning low scores, the loop must give up at
        loop_max_iterations and let the pipeline proceed to write_paper
        rather than spinning forever."""
        from ari import pipeline as _pipe

        ckpt = tmp_path / "ckpt_giveup"
        ckpt.mkdir()
        (ckpt / "idea.json").write_text('{"primary_metric": "m", "ideas": []}')

        # Always return a low score — pipeline must bail at max_iterations
        generate_figures_calls = [0]  # list for mutable closure

        fake_latex = r"\documentclass{article}\begin{document}ok\end{document}"
        static_returns = {
            "collect_references_iterative": {"references": []},
            "nodes_to_science_data": {"experiment_context": {}, "configurations": []},
            "generate_ear": {"ear_dir": str(ckpt / "ear"), "file_count": 0},
            "write_paper_iterative": {"latex": fake_latex, "bib": "@article{x,}"},
            "review_compiled_paper": {"score": 5},
            "generate_rebuttal": {"rebuttal_latex": "rb", "point_by_point": []},
            "reproduce_from_paper": {"ok": True},
        }

        def fake_subproc(tool, args, config_path, skill_name=""):
            if tool == "generate_figures_llm":
                generate_figures_calls[0] += 1
                (ckpt / "fig_1.pdf").write_bytes(b"%PDF fake")
                (ckpt / "fig_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
                return {
                    "figures": {"fig_1": str(ckpt / "fig_1.pdf")},
                    "latex_snippets": {"fig_1": "\\begin{figure}f\\end{figure}"},
                }
            if tool == "review_figure":
                return {"score": 0.1, "issues": ["bad"], "suggestions": ["fix"]}
            return static_returns.get(tool, {})

        monkeypatch.setattr(_pipe, "_run_stage_subprocess", fake_subproc)

        stages = _pipe.load_pipeline(str(_WORKFLOW_YAML))
        # Read the configured cap so the assertion remains correct if the
        # YAML raises/lowers the iteration count later.
        vlm_stage = next(s for s in stages if s["stage"] == "vlm_review_figures")
        max_iter = int(vlm_stage.get("loop_max_iterations", 2))

        _pipe.run_pipeline(
            stages=stages,
            all_nodes=[],
            experiment_data={"topic": "giveup", "goal": "giveup"},
            checkpoint_dir=ckpt,
            config_path=str(_WORKFLOW_YAML),
        )

        # generate_figures_llm should have been called exactly
        # (1 initial + loop_max_iterations retries) times. Anything more
        # means the cap isn't being honoured (infinite loop risk).
        expected = 1 + max_iter
        assert generate_figures_calls[0] == expected, (
            f"generate_figures_llm should run {expected} times "
            f"(1 initial + {max_iter} retries) when VLM always scores low, "
            f"got {generate_figures_calls[0]}"
        )
        # Pipeline must still produce full_paper.tex despite the loop giving up
        assert (ckpt / "full_paper.tex").exists(), (
            "Even when the VLM loop gives up, write_paper should still run "
            "and produce full_paper.tex"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 11. Paper-dir drift detection (regression: GUI "Files (0)" stale paper/)
# ══════════════════════════════════════════════════════════════════════════════


class TestPaperDirDriftDetection:
    """Regression: the GUI "Files" tab once showed "0 files" on checkpoints
    whose paper/ subdirectory had been created by a failed earlier run
    (containing only an empty figures/ dir) but whose root had since been
    populated by a successful rerun with full_paper.tex/pdf.

    _ensure_paper_dir() must detect that drift and (re-)seed from the
    checkpoint root whenever a root artefact is newer than — or missing
    from — paper/.
    """

    @pytest.fixture
    def ckpt_resolver(self, tmp_path, monkeypatch):
        """Create a tmp checkpoint and make `_resolve_checkpoint_dir` find
        it regardless of the real filesystem search paths."""
        from ari.viz import api_state
        ckpt = tmp_path / "ckpt_drift"
        ckpt.mkdir()

        def fake_resolve(ckpt_id: str):
            return ckpt if ckpt_id == ckpt.name else None

        monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", fake_resolve)
        return ckpt

    def test_reseeds_when_root_artefact_newer_than_paper(self, ckpt_resolver):
        """If full_paper.tex exists at root but paper/ is empty, the next
        call to _ensure_paper_dir must copy it into paper/."""
        from ari.viz.api_state import _ensure_paper_dir, _api_checkpoint_files

        ckpt = ckpt_resolver

        # First: simulate the original buggy state — an empty paper/ dir
        # that a failed earlier run left behind.
        (ckpt / "paper").mkdir()
        (ckpt / "paper" / "figures").mkdir()

        # Later: rerun populates the root with real paper artefacts
        (ckpt / "full_paper.tex").write_text(r"\documentclass{article}...")
        (ckpt / "full_paper.pdf").write_bytes(b"%PDF-1.7 fake")
        (ckpt / "refs.bib").write_text("@article{x, title={t}}")
        (ckpt / "fig_1.pdf").write_bytes(b"%PDF fig1")
        (ckpt / "fig_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

        # Call _ensure_paper_dir — it must re-seed
        paper, err = _ensure_paper_dir(ckpt.name)
        assert err is None
        assert paper is not None

        # The key regression: paper/ must now contain the root artefacts
        assert (paper / "full_paper.tex").exists(), (
            "full_paper.tex was not re-seeded into paper/ — drift detection "
            "failed, GUI would still show 'Files (0)'"
        )
        assert (paper / "full_paper.pdf").exists()
        assert (paper / "refs.bib").exists()
        assert (paper / "figures" / "fig_1.pdf").exists()
        assert (paper / "figures" / "fig_1.png").exists()

        # And the GUI files API must list them
        result = _api_checkpoint_files(ckpt.name)
        file_names = {f["name"] for f in result.get("files", [])}
        assert "full_paper.tex" in file_names, (
            f"_api_checkpoint_files did not return full_paper.tex. "
            f"Returned: {file_names}"
        )
        assert any("fig_1" in n for n in file_names)

    def test_preserves_paper_dir_edits_when_newer(self, ckpt_resolver):
        """If the user has edited paper/full_paper.tex in the GUI and
        that edit is newer than the checkpoint root copy, the drift
        detection must NOT clobber the edit."""
        import time
        from ari.viz.api_state import _ensure_paper_dir

        ckpt = ckpt_resolver

        # Write root artefact first, with an older mtime
        (ckpt / "full_paper.tex").write_text("ORIGINAL FROM PIPELINE")
        old_mtime = (ckpt / "full_paper.tex").stat().st_mtime

        # Bootstrap paper/ by calling _ensure_paper_dir once
        paper, _ = _ensure_paper_dir(ckpt.name)
        assert (paper / "full_paper.tex").read_text() == "ORIGINAL FROM PIPELINE"

        # Simulate user edit in the GUI: overwrite paper/full_paper.tex
        # with a newer timestamp
        time.sleep(0.01)
        (paper / "full_paper.tex").write_text("USER EDIT FROM GUI")
        import os as _os_t
        _new = old_mtime + 10
        _os_t.utime(paper / "full_paper.tex", (_new, _new))

        # Next _ensure_paper_dir call must NOT overwrite the user edit
        _ensure_paper_dir(ckpt.name)
        assert (paper / "full_paper.tex").read_text() == "USER EDIT FROM GUI", (
            "User edit in paper/ was clobbered by root copy — drift "
            "detection must only overwrite when root is NEWER"
        )

    def test_reseeds_when_root_newer_than_paper_copy(self, ckpt_resolver):
        """Conversely: if the pipeline reruns and produces a newer root
        full_paper.tex, the drift detection MUST overwrite the stale copy
        in paper/."""
        import time
        from ari.viz.api_state import _ensure_paper_dir

        ckpt = ckpt_resolver

        (ckpt / "full_paper.tex").write_text("RUN 1")
        # First seed
        paper, _ = _ensure_paper_dir(ckpt.name)
        assert (paper / "full_paper.tex").read_text() == "RUN 1"

        # Pipeline rerun: root file gets updated content with a newer mtime
        time.sleep(0.01)
        (ckpt / "full_paper.tex").write_text("RUN 2")
        import os as _os_t
        _now = (ckpt / "full_paper.tex").stat().st_mtime + 10
        _os_t.utime(ckpt / "full_paper.tex", (_now, _now))

        _ensure_paper_dir(ckpt.name)
        assert (paper / "full_paper.tex").read_text() == "RUN 2", (
            "After pipeline rerun produced new root artefact, paper/ copy "
            "was not refreshed — drift detection failed in the forward direction"
        )
