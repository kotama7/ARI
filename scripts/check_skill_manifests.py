#!/usr/bin/env python3
"""Check canonical Skill manifests against runtime, workflow, and package data."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ari-core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ari.skill_manifest import (  # noqa: E402
    RESULT_ENVELOPE_V1,
    SkillManifestError,
    SkillManifestV1,
    legacy_mcp_document,
    load_skill_manifest,
    resolve_skill_entrypoint,
)
from ari.result import ResultEnvelopeV1  # noqa: E402
from ari.analysis import (  # noqa: E402
    AnalysisRequestV1,
    AnalysisResultV1,
    RunComparisonRequestV1,
    StatisticalTestRequestV1,
)
from ari.call_context import ToolCallContextV1  # noqa: E402
from ari.execution import (  # noqa: E402
    ExecutionRequestV1,
    ExecutionResultV1,
    MeasurementSetV1,
    WorkspaceRefV1,
)
from ari.mcp.child_environment import (  # noqa: E402
    MANAGED_CHILD_ENV_NAMES,
    SAFE_INHERITED_ENV_NAMES,
)
from ari.skill_lock import SkillsLockV1  # noqa: E402
from ari.research_contract import (  # noqa: E402
    IdeaCandidateV1,
    IdeaSetV1,
    MetricContractV1,
    ResearchContractV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
)
from snapshot_contracts import _scan_skill_tools  # noqa: E402


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def _constant_strings(node: ast.AST, constants: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(constants.get(node.id, set()))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: set[str] = set()
        for item in node.elts:
            values.update(_constant_strings(item, constants))
        return values
    return set()


def _is_os_expression(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "__import__"
        and bool(node.args)
        and _constant_strings(node.args[0], {}) == {"os"}
    )


def _is_environ_expression(
    node: ast.AST,
    os_aliases: set[str],
    environ_aliases: set[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in environ_aliases
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and _is_os_expression(node.value, os_aliases)
    )


def _environment_access_argument(
    node: ast.AST,
    os_aliases: set[str],
    environ_aliases: set[str],
    getenv_aliases: set[str],
) -> ast.AST | None:
    if (
        isinstance(node, ast.Call)
        and node.args
        and isinstance(node.func, ast.Name)
        and node.func.id in getenv_aliases
    ):
        return node.args[0]
    if isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute):
        if node.func.attr == "getenv" and _is_os_expression(
            node.func.value, os_aliases
        ):
            return node.args[0]
        if node.func.attr in {"putenv", "unsetenv"} and _is_os_expression(
            node.func.value, os_aliases
        ):
            return node.args[0]
        if node.func.attr in {"get", "pop", "setdefault"} and _is_environ_expression(
            node.func.value, os_aliases, environ_aliases
        ):
            return node.args[0]
    if (
        isinstance(node, ast.Subscript)
        and _is_environ_expression(node.value, os_aliases, environ_aliases)
    ):
        return node.slice
    return None


def _environment_membership_argument(
    node: ast.AST,
    os_aliases: set[str],
    environ_aliases: set[str],
) -> ast.AST | None:
    if not isinstance(node, ast.Compare):
        return None
    left = node.left
    for operator, comparator in zip(node.ops, node.comparators, strict=True):
        if isinstance(operator, (ast.In, ast.NotIn)) and _is_environ_expression(
            comparator, os_aliases, environ_aliases
        ):
            return left
        left = comparator
    return None


def _bound_constant_strings(
    name: str,
    node: ast.AST,
    *,
    parents: dict[ast.AST, ast.AST],
    constants: dict[str, set[str]],
) -> set[str]:
    current = node
    while current in parents:
        current = parents[current]
        generators = (
            current.generators
            if isinstance(
                current,
                (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp),
            )
            else []
        )
        for generator in generators:
            if isinstance(generator.target, ast.Name) and generator.target.id == name:
                return _constant_strings(generator.iter, constants)
        if (
            isinstance(current, ast.For)
            and isinstance(current.target, ast.Name)
            and current.target.id == name
        ):
            return _constant_strings(current.iter, constants)
    return set()


def _scan_environment_reads(source_root: Path) -> tuple[set[str], list[str]]:
    """Return statically resolved environment reads and unresolved locations."""

    reads: set[str] = set()
    unresolved: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError as exc:
            unresolved.append(f"{path}:unreadable:{exc}")
            continue
        except SyntaxError as exc:
            unresolved.append(f"{path}:{exc.lineno or '?'}:syntax-error")
            continue
        nodes = list(ast.walk(tree))
        parents = {
            child: parent
            for parent in nodes
            for child in ast.iter_child_nodes(parent)
        }
        os_aliases = {"os"}
        environ_aliases: set[str] = set()
        getenv_aliases: set[str] = set()
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "os":
                        os_aliases.add(alias.asname or "os")
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for alias in node.names:
                    if alias.name == "environ":
                        environ_aliases.add(alias.asname or alias.name)
                    elif alias.name == "getenv":
                        getenv_aliases.add(alias.asname or alias.name)
        constants: dict[str, set[str]] = {}
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if _is_environ_expression(value, os_aliases, environ_aliases):
                    environ_aliases.add(target.id)
                values = _constant_strings(value, constants)
                if values:
                    constants[target.id] = values

        helper_parameters: dict[str, tuple[int, str]] = {}
        helper_access_nodes: set[ast.AST] = set()
        for function in (
            node
            for node in nodes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            parameters = [argument.arg for argument in function.args.args]
            for child in ast.walk(function):
                argument = _environment_access_argument(
                    child, os_aliases, environ_aliases, getenv_aliases
                )
                if argument is None:
                    argument = _environment_membership_argument(
                        child, os_aliases, environ_aliases
                    )
                if isinstance(argument, ast.Name) and argument.id in parameters:
                    helper_parameters[function.name] = (
                        parameters.index(argument.id),
                        argument.id,
                    )
                    helper_access_nodes.add(child)

        for node in nodes:
            argument = _environment_access_argument(
                node, os_aliases, environ_aliases, getenv_aliases
            )
            if argument is None:
                argument = _environment_membership_argument(
                    node, os_aliases, environ_aliases
                )
            if argument is None or node in helper_access_nodes:
                continue
            resolved = _constant_strings(argument, constants)
            if not resolved and isinstance(argument, ast.Name):
                resolved = _bound_constant_strings(
                    argument.id,
                    node,
                    parents=parents,
                    constants=constants,
                )
            if resolved:
                reads.update(resolved)
            else:
                unresolved.append(
                    f"{path}:{getattr(node, 'lineno', '?')}:{ast.unparse(argument)}"
                )

        for node in nodes:
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            parameter = helper_parameters.get(node.func.id)
            if parameter is None:
                continue
            parameter_index, parameter_name = parameter
            call_argument = (
                node.args[parameter_index]
                if parameter_index < len(node.args)
                else next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == parameter_name
                    ),
                    None,
                )
            )
            if call_argument is None:
                unresolved.append(f"{path}:{node.lineno}:{node.func.id}(missing-name)")
                continue
            resolved = _constant_strings(call_argument, constants)
            if resolved:
                reads.update(resolved)
            else:
                unresolved.append(
                    f"{path}:{node.lineno}:{node.func.id}({ast.unparse(call_argument)})"
                )
    return reads, sorted(set(unresolved))


def _project_version(pyproject: Path) -> str | None:
    """Read ``project.version`` without adding a TOML dependency on Python 3.9."""

    in_project = False
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project:
            match = re.fullmatch(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
            if match:
                return match.group(1)
    return None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check_repo(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    manifests = {}
    runtime_dirs = {
        path
        for path in repo_root.glob("ari-skill-*")
        if path.is_dir()
        and (
            (path / "skill.yaml").is_file()
            or (path / "pyproject.toml").is_file()
            or (path / "src" / "server.py").is_file()
        )
    }

    for skill_dir in sorted(runtime_dirs):
        manifest_path = skill_dir / "skill.yaml"
        rel = _relative(manifest_path, repo_root)
        if not manifest_path.is_file():
            findings.append(
                Finding("manifest-missing", rel, "canonical skill.yaml is required")
            )
            continue
        try:
            manifest = load_skill_manifest(manifest_path)
            entrypoint = resolve_skill_entrypoint(skill_dir, manifest)
        except SkillManifestError as exc:
            findings.append(Finding("manifest-invalid", rel, str(exc)))
            continue
        manifests[manifest.package] = (manifest_path, manifest)

        if manifest.environment_policy != "complete":
            findings.append(
                Finding(
                    "environment-policy-incomplete",
                    rel,
                    "production Skill manifests require an exhaustive complete policy",
                )
            )
        environment_reads, dynamic_environment_reads = _scan_environment_reads(
            entrypoint.parent
        )
        declared_environment = set(manifest.environment_names())
        implicit_environment = set(SAFE_INHERITED_ENV_NAMES) | set(
            MANAGED_CHILD_ENV_NAMES
        )
        undeclared_environment = sorted(
            environment_reads - declared_environment - implicit_environment
        )
        if undeclared_environment:
            findings.append(
                Finding(
                    "environment-read-undeclared",
                    rel,
                    f"source reads undeclared names: {undeclared_environment}",
                )
            )
        if dynamic_environment_reads:
            findings.append(
                Finding(
                    "environment-read-dynamic",
                    rel,
                    "environment names cannot be proven exhaustive: "
                    f"{dynamic_environment_reads}",
                )
            )

        if manifest.package != skill_dir.name:
            findings.append(
                Finding(
                    "package-mismatch",
                    rel,
                    f"package={manifest.package!r}, directory={skill_dir.name!r}",
                )
            )

        runtime_names = {tool["name"] for tool in _scan_skill_tools(entrypoint)}
        declared_names = {tool.name for tool in manifest.tools}
        if runtime_names != declared_names:
            findings.append(
                Finding(
                    "tool-drift",
                    rel,
                    f"runtime_only={sorted(runtime_names - declared_names)}, "
                    f"manifest_only={sorted(declared_names - runtime_names)}",
                )
            )

        legacy_result_tools = [
            tool.name
            for tool in manifest.resolved_tools()
            if tool.result_schema != RESULT_ENVELOPE_V1
        ]
        if legacy_result_tools:
            findings.append(
                Finding(
                    "result-schema-drift",
                    rel,
                    f"tools must use {RESULT_ENVELOPE_V1}: {legacy_result_tools}",
                )
            )

        pyproject = skill_dir / "pyproject.toml"
        if pyproject.is_file():
            project_version = _project_version(pyproject)
            if project_version != manifest.version:
                findings.append(
                    Finding(
                        "version-drift",
                        rel,
                        f"manifest={manifest.version!r}, pyproject={project_version!r}",
                    )
                )

        mcp_path = skill_dir / "mcp.json"
        try:
            mcp_document = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                Finding(
                    "compat-metadata-invalid", _relative(mcp_path, repo_root), str(exc)
                )
            )
        else:
            expected = legacy_mcp_document(manifest)
            if mcp_document != expected:
                findings.append(
                    Finding(
                        "compat-metadata-drift",
                        _relative(mcp_path, repo_root),
                        "mcp.json must be regenerated from skill.yaml",
                    )
                )

    by_name: dict[str, list[str]] = defaultdict(list)
    default_tool_owners: dict[str, list[str]] = defaultdict(list)
    for package, (_, manifest) in manifests.items():
        by_name[manifest.name].append(package)
        if manifest.enabled_by_default:
            for tool in manifest.tools:
                default_tool_owners[tool.name].append(package)
    for name, packages in sorted(by_name.items()):
        if len(packages) > 1:
            findings.append(
                Finding(
                    "skill-name-collision", "skill.yaml", f"{name}: {sorted(packages)}"
                )
            )
    for name, packages in sorted(default_tool_owners.items()):
        if len(packages) > 1:
            findings.append(
                Finding(
                    "default-tool-collision",
                    "skill.yaml",
                    f"{name}: {sorted(packages)}",
                )
            )

    workflow_path = repo_root / "ari-core" / "config" / "workflow.yaml"
    try:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        findings.append(
            Finding("workflow-invalid", _relative(workflow_path, repo_root), str(exc))
        )
        workflow = {}

    workflow_skills: dict[str, tuple[str, object]] = {}
    for configured in workflow.get("skills") or []:
        alias = configured.get("name", "")
        directory = Path(str(configured.get("path", ""))).name
        pair = manifests.get(directory)
        if pair is None:
            findings.append(
                Finding(
                    "workflow-skill-missing",
                    _relative(workflow_path, repo_root),
                    f"{alias}: {directory}",
                )
            )
            continue
        manifest = pair[1]
        workflow_skills[alias] = (directory, manifest)
        if alias != manifest.name:
            findings.append(
                Finding(
                    "workflow-skill-name-drift",
                    _relative(workflow_path, repo_root),
                    f"configured={alias!r}, manifest={manifest.name!r}",
                )
            )

    for section in ("bfts_pipeline", "pipeline"):
        for stage in workflow.get(section) or []:
            tool_name = stage.get("tool", "")
            if not tool_name:
                continue
            alias = stage.get("skill", "")
            pair = workflow_skills.get(alias)
            if pair is None:
                findings.append(
                    Finding(
                        "workflow-tool-owner-missing",
                        _relative(workflow_path, repo_root),
                        f"{section}.{stage.get('stage')}: {alias}",
                    )
                )
                continue
            manifest = pair[1]
            tool = manifest.tool(tool_name)
            if tool is None:
                findings.append(
                    Finding(
                        "workflow-tool-missing",
                        _relative(workflow_path, repo_root),
                        f"{section}.{stage.get('stage')}: {alias}/{tool_name}",
                    )
                )
                continue
            phase = stage.get("phase")
            if phase and phase not in tool.phases and "all" not in tool.phases:
                findings.append(
                    Finding(
                        "workflow-phase-mismatch",
                        _relative(workflow_path, repo_root),
                        f"{alias}/{tool_name} does not admit phase {phase!r}",
                    )
                )

    schema_path = (
        repo_root / "ari-core" / "ari" / "schemas" / "skill_manifest_v1.schema.json"
    )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema.get("properties", {}).get("schema_version", {}).get("const") != 1:
            raise ValueError("schema_version const is not 1")
        schema_fields = set(schema.get("properties", {}))
        model_fields = set(SkillManifestV1.model_fields)
        if schema_fields != model_fields:
            raise ValueError(
                f"top-level schema drift: missing={sorted(model_fields - schema_fields)}, "
                f"extra={sorted(schema_fields - model_fields)}"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        findings.append(
            Finding("json-schema-invalid", _relative(schema_path, repo_root), str(exc))
        )

    context_schema_path = (
        repo_root / "ari-core" / "ari" / "schemas" / "call_context_v1.schema.json"
    )
    try:
        context_schema = json.loads(context_schema_path.read_text(encoding="utf-8"))
        schema_fields = set(context_schema.get("properties", {}))
        model_fields = set(ToolCallContextV1.model_fields)
        if schema_fields != model_fields:
            raise ValueError(
                "call-context top-level schema drift: "
                f"missing={sorted(model_fields - schema_fields)}, "
                f"extra={sorted(schema_fields - model_fields)}"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        findings.append(
            Finding(
                "call-context-json-schema-invalid",
                _relative(context_schema_path, repo_root),
                str(exc),
            )
        )

    result_schema_path = (
        repo_root / "ari-core" / "ari" / "schemas" / "result_envelope_v1.schema.json"
    )
    try:
        result_schema = json.loads(result_schema_path.read_text(encoding="utf-8"))
        schema_version = (
            result_schema.get("properties", {}).get("schema_version", {}).get("const")
        )
        if schema_version != "ari.result-envelope/v1":
            raise ValueError(
                "result schema_version const is not ari.result-envelope/v1"
            )
        schema_fields = set(result_schema.get("properties", {}))
        model_fields = set(ResultEnvelopeV1.model_fields)
        if schema_fields != model_fields:
            raise ValueError(
                "result top-level schema drift: "
                f"missing={sorted(model_fields - schema_fields)}, "
                f"extra={sorted(schema_fields - model_fields)}"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        findings.append(
            Finding(
                "result-json-schema-invalid",
                _relative(result_schema_path, repo_root),
                str(exc),
            )
        )

    lock_schema_path = (
        repo_root / "ari-core" / "ari" / "schemas" / "skills_lock_v1.schema.json"
    )
    try:
        lock_schema = json.loads(lock_schema_path.read_text(encoding="utf-8"))
        schema_version = (
            lock_schema.get("properties", {}).get("schema_version", {}).get("const")
        )
        if schema_version != "ari.skills-lock/v1":
            raise ValueError("lock schema_version const is not ari.skills-lock/v1")
        schema_fields = set(lock_schema.get("properties", {}))
        model_fields = set(SkillsLockV1.model_fields)
        if schema_fields != model_fields:
            raise ValueError(
                "lock top-level schema drift: "
                f"missing={sorted(model_fields - schema_fields)}, "
                f"extra={sorted(schema_fields - model_fields)}"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        findings.append(
            Finding(
                "lock-json-schema-invalid",
                _relative(lock_schema_path, repo_root),
                str(exc),
            )
        )

    execution_schemas = (
        (
            "analysis_request_v1.schema.json",
            AnalysisRequestV1,
            "ari.analysis-request/v1",
        ),
        (
            "statistical_test_request_v1.schema.json",
            StatisticalTestRequestV1,
            "ari.statistical-test-request/v1",
        ),
        (
            "run_comparison_request_v1.schema.json",
            RunComparisonRequestV1,
            "ari.run-comparison-request/v1",
        ),
        (
            "analysis_result_v1.schema.json",
            AnalysisResultV1,
            "ari.analysis-result/v1",
        ),
        (
            "workspace_ref_v1.schema.json",
            WorkspaceRefV1,
            "ari.workspace-ref/v1",
        ),
        (
            "execution_request_v1.schema.json",
            ExecutionRequestV1,
            "ari.execution-request/v1",
        ),
        (
            "execution_result_v1.schema.json",
            ExecutionResultV1,
            "ari.execution-result/v1",
        ),
        (
            "measurement_set_v1.schema.json",
            MeasurementSetV1,
            "ari.measurement-set/v1",
        ),
        (
            "retrieval_record_v1.schema.json",
            RetrievalRecordV1,
            "ari.retrieval-record/v1",
        ),
        (
            "survey_snapshot_v1.schema.json",
            SurveySnapshotV1,
            "ari.survey-snapshot/v1",
        ),
        (
            "metric_contract_v1.schema.json",
            MetricContractV1,
            "ari.metric-contract/v1",
        ),
        (
            "idea_candidate_v1.schema.json",
            IdeaCandidateV1,
            "ari.idea-candidate/v1",
        ),
        ("idea_set_v1.schema.json", IdeaSetV1, "ari.idea-set/v1"),
        (
            "research_contract_v1.schema.json",
            ResearchContractV1,
            "ari.research-contract/v1",
        ),
    )
    for filename, model, expected_version in execution_schemas:
        execution_schema_path = (
            repo_root / "ari-core" / "ari" / "schemas" / filename
        )
        try:
            execution_schema = json.loads(
                execution_schema_path.read_text(encoding="utf-8")
            )
            actual_version = (
                execution_schema.get("properties", {})
                .get("schema_version", {})
                .get("const")
            )
            if actual_version != expected_version:
                raise ValueError(
                    f"schema_version const is {actual_version!r}, expected "
                    f"{expected_version!r}"
                )
            schema_fields = set(execution_schema.get("properties", {}))
            model_fields = set(model.model_fields)
            if schema_fields != model_fields:
                raise ValueError(
                    "execution schema top-level drift: "
                    f"missing={sorted(model_fields - schema_fields)}, "
                    f"extra={sorted(schema_fields - model_fields)}"
                )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(
                Finding(
                    "execution-json-schema-invalid",
                    _relative(execution_schema_path, repo_root),
                    str(exc),
                )
            )

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable report"
    )
    args = parser.parse_args(argv)
    findings = check_repo()
    if args.json:
        print(
            json.dumps(
                {"ok": not findings, "findings": [asdict(item) for item in findings]},
                indent=2,
            )
        )
    elif findings:
        for item in findings:
            print(f"{item.code}: {item.path}: {item.message}")
        print(f"skill manifest conformance failed: {len(findings)} finding(s)")
    else:
        print("skill manifest conformance passed")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
