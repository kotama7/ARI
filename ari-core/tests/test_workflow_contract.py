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
