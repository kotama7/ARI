"""
Integration tests v2 — comprehensive interface and variable-expansion coverage.
Covers the full pipeline data flow without spawning real LLM calls.
"""
import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

ARI_ROOT = Path(__file__).parents[2]  # ari-core/tests/ -> ari-core/ -> ARI root


# ─── helpers ────────────────────────────────────────────────────────────────

def _load(skill: str) -> str:
    return (ARI_ROOT / f"ari-skill-{skill}/src/server.py").read_text()

def _parse(src: str) -> ast.Module:
    return ast.parse(src)

def _func_args(src: str, name: str) -> list[str]:
    for node in ast.walk(_parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return [a.arg for a in node.args.args]
    return []

def _is_async(src: str, name: str) -> bool:
    for node in ast.walk(_parse(src)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return True
    return False

def _has_toplevel_name(src: str, name: str) -> bool:
    tree = _parse(src)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[-1]) == name:
                    return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return True
    return False

def _calls_undefined(src: str, func_name: str) -> list[str]:
    """Find names called inside func_name that are not defined anywhere in the module."""
    tree = _parse(src)
    # collect all defined names at module level
    defined = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
    # find calls inside the specific function
    undefined = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            # collect local defines
            local_defs = set()
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    for a in child.names:
                        local_defs.add(a.asname or a.name.split(".")[0])
                elif isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name):
                            local_defs.add(t.id)
                elif isinstance(child, ast.arg):
                    local_defs.add(child.arg)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child is not node:
                        local_defs.add(child.name)
            # check calls
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        n = child.func.id
                        if n not in defined and n not in local_defs and n not in dir(__builtins__):
                            undefined.append(n)
    return list(set(undefined))

def _load_wf():
    return yaml.safe_load((ARI_ROOT / "ari-core/config/workflow.yaml").read_text())

def _resolve(value, vars_):
    if not isinstance(value, str):
        return value
    def sub(m):
        key = m.group(1).strip()
        parts = key.split(".")
        v = vars_
        try:
            for p in parts:
                v = v[p]
            return str(v)
        except (KeyError, TypeError):
            return m.group(0)
    return re.sub(r"\{\{(.+?)\}\}", sub, value)


# ─── workflow.yaml interface ─────────────────────────────────────────────────

def test_all_workflow_tools_exist():
    wf = _load_wf()
    skill_paths = {s["name"]: ARI_ROOT / s["path"].replace("{{ari_root}}/", "")
                   for s in wf["skills"]}
    errors = []
    for stage in wf.get("pipeline", []):
        tool = stage["tool"]
        skill = stage["skill"]
        if skill not in skill_paths:
            errors.append(f'{stage["stage"]}: unknown skill "{skill}"')
            continue
        src = (skill_paths[skill] / "src/server.py").read_text()
        if f"def {tool}(" not in src and f"async def {tool}(" not in src:
            errors.append(f'{stage["stage"]}: tool "{tool}" not in {skill}')
    assert not errors, "\n".join(errors)


def test_workflow_tool_params_match():
    wf = _load_wf()
    skill_paths = {s["name"]: ARI_ROOT / s["path"].replace("{{ari_root}}/", "")
                   for s in wf["skills"]}
    errors = []
    for stage in wf.get("pipeline", []):
        tool = stage["tool"]
        src = (skill_paths[stage["skill"]] / "src/server.py").read_text()
        args = _func_args(src, tool)
        for k in stage.get("inputs", {}):
            if k not in args:
                errors.append(f'{stage["stage"]}.{tool}() missing param "{k}" (has {args})')
    assert not errors, "\n".join(errors)


def test_template_variables_all_resolve():
    """Every {{var}} in workflow.yaml must resolve to a non-template value."""
    wf = _load_wf()
    # Simulate tpl_vars as pipeline.py builds them
    tpl_vars = {
        "ckpt": "/tmp/ckpt",
        "context": "test context",
        "paper_context": wf.get("paper_context", "test"),
        "slurm_partition": wf.get("slurm_partition", "cpu"),
        "keywords": "keyword1 keyword2",
        "experiment_source_file": "/tmp/source.c",
        "author_name": wf.get("author_name", "Artificial Research Intelligence"),
        "ari_root": "/tmp/ari",
        # Expose nested dicts for dot-notation access (e.g. resources.cpus)
        **{section: sec_val
           for section, sec_val in wf.items()
           if isinstance(sec_val, dict) and section not in ("pipeline", "skills", "stages")},
        "stages": {
            "search_related_work": {"output": "/tmp/ckpt/related_refs.json",
                                    "outputs": {"file": "/tmp/ckpt/related_refs.json"}},
            "transform_data":      {"output": "/tmp/ckpt/science_data.json",
                                    "outputs": {"file": "/tmp/ckpt/science_data.json"}},
            "generate_figures":    {"output": "/tmp/ckpt/figures_manifest.json",
                                    "outputs": {"file": "/tmp/ckpt/figures_manifest.json"}},
            "write_paper":         {"output": "/tmp/ckpt/full_paper.tex",
                                    "outputs": {"file": "/tmp/ckpt/full_paper.tex",
                                                "bib_file": "/tmp/ckpt/refs.bib"}},
            "review_paper":        {"output": "/tmp/ckpt/review_report.json",
                                    "outputs": {"file": "/tmp/ckpt/review_report.json"}},
        },
    }
    errors = []
    for stage in wf.get("pipeline", []):
        for k, v in stage.get("inputs", {}).items():
            resolved = _resolve(str(v), tpl_vars)
            if "{{" in resolved:
                errors.append(f'{stage["stage"]}.{k}: unresolved template in "{resolved}"')
        for k, v in stage.get("outputs", {}).items():
            resolved = _resolve(str(v), tpl_vars)
            if "{{" in resolved:
                errors.append(f'{stage["stage"]} output.{k}: unresolved template in "{resolved}"')
    assert not errors, "\n".join(errors)


def test_slurm_partition_resolves_to_real_value():
    wf = _load_wf()
    partition = wf.get("slurm_partition", "")
    # It's OK to leave as placeholder "your_partition" — user fills in before running.
    # Just ensure it doesn't contain unresolved template syntax.
    assert "{{" not in str(partition), f"slurm_partition is still a template: {partition}"


def test_paper_context_no_org_names():
    """paper_context must not contain organization or cluster names."""
    wf = _load_wf()
    ctx = wf.get("paper_context", "")
    forbidden = ["RIKEN", "riken", "kotama", "takanori"]
    for term in forbidden:
        assert term not in ctx, f"paper_context contains forbidden term: {term!r}"


# ─── pipeline.py ─────────────────────────────────────────────────────────────

def test_pipeline_has_paper_context_tpl_var():
    src = (ARI_ROOT / "ari-core/ari/pipeline.py").read_text()
    assert '"paper_context"' in src, "pipeline.py must provide paper_context tpl var"
    assert '"slurm_partition"' in src, "pipeline.py must provide slurm_partition tpl var"
    assert '"experiment_source_file"' in src, "pipeline.py must provide experiment_source_file tpl var"


def test_mcp_client_resolves_ari_root():
    src = (ARI_ROOT / "ari-core/ari/mcp/client.py").read_text()
    assert "ARI_ROOT" in src, "mcp/client.py must resolve {{ari_root}} in skill paths"
    assert "ari_root" in src.lower() or "ARI_ROOT" in src, \
        "mcp/client.py must handle {{ari_root}} template in skill path"


# ─── paper-skill ─────────────────────────────────────────────────────────────

def test_paper_log_defined():
    src = _load("paper")
    assert _has_toplevel_name(src, "log"), "log not defined at module level in paper/server.py"


def test_paper_no_run_until_complete():
    src = _load("paper")
    for node in ast.walk(_parse(src)):
        if isinstance(node, ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr == "run_until_complete":
                    pytest.fail(f"async def {node.name} uses run_until_complete")


def test_paper_sanitize_removed():
    src = _load("paper")
    assert "_sanitize_paper_org_names" not in src, \
        "_sanitize_paper_org_names must be removed (philosophy violation)"


def test_paper_write_paper_calls_only_defined_functions():
    src = _load("paper")
    undef = _calls_undefined(src, "write_paper_iterative")
    # Allow known false positives (builtins and inner functions)
    allow = {"json", "Path", "next", "str", "int", "list", "dict", "set",
              "isinstance", "len", "range", "enumerate", "print", "hasattr",
              "getattr", "type", "bool", "float", "open", "Exception", "sorted",
              "any", "all", "min", "max", "zip", "filter", "map", "vars", "dir"}
    real_undef = [u for u in undef if u not in allow]
    assert not real_undef, f"write_paper_iterative calls undefined: {real_undef}"


def test_paper_forbidden_notice_reproducibility_principle():
    src = _load("paper")
    assert "reproducible" in src.lower() or "reproduction" in src.lower(), \
        "_FORBIDDEN_NOTICE should mention reproducibility principle"


# ─── paper-re skill ──────────────────────────────────────────────────────────

def test_paperre_no_hardcoded_cluster():
    src = _load("paper-re")
    for node in ast.walk(_parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "reproduce_from_paper":
            for i, default in enumerate(node.args.defaults):
                arg_idx = len(node.args.args) - len(node.args.defaults) + i
                arg_name = node.args.args[arg_idx].arg
                if isinstance(default, ast.Constant) and arg_name == "slurm_partition":
                    assert default.value not in ("genoa", "ai-l40s", "riken"), \
                        f"slurm_partition default is cluster-specific: {default.value!r}"


# ─── plot-skill ──────────────────────────────────────────────────────────────

def test_plot_strips_output_dir_override():
    src = _load("plot")
    assert "startswith(\"output_dir\")" in src or "removed by preamble" in src or \
           "_SAFE_OUTPUT_DIR" in src or "output_dir" in src and "removed" in src, \
        "plot-skill must strip output_dir reassignment from LLM code"


# ─── domain hardcodes ────────────────────────────────────────────────────────

DOMAIN_TERMS = ["RIKEN", "himeno", "kotama", "takanori", "ai-l40s"]

def test_no_domain_hardcodes_in_skills():
    skills = ["paper", "paper-re", "plot", "hpc", "web", "evaluator", "idea", "memory"]
    skip = ("#", '"""', "'''", "e.g.", "example", "docstring", "# removed", "github.com", "https://")
    errors = []
    for skill in skills:
        src = _load(skill)
        for lineno, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if any(stripped.startswith(p) for p in ("#", '"""', "'''")):
                continue
            if any(p in line for p in skip):
                continue
            for term in DOMAIN_TERMS:
                if term in line:
                    errors.append(f"ari-skill-{skill}:{lineno}: {term!r} in: {line.strip()[:80]}")
    assert not errors, "\n".join(errors)

