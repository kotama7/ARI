"""Pinned PaperBench provenance and runtime patch admission checks."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any


INVENTORY_PATH = Path(__file__).resolve().parents[1] / "paperbench_patches.json"


class PaperBenchInventoryError(RuntimeError):
    """The configured PaperBench source does not match the reviewed pin."""


def load_inventory() -> dict[str, Any]:
    document = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != "ari.paperbench-patch-inventory/v1":
        raise PaperBenchInventoryError("unsupported PaperBench inventory version")
    upstream = document.get("upstream")
    patches = document.get("patches")
    if (
        not isinstance(upstream, dict)
        or not isinstance(upstream.get("commit"), str)
        or len(upstream["commit"]) != 40
        or not isinstance(patches, list)
        or not patches
    ):
        raise PaperBenchInventoryError("PaperBench inventory is incomplete")
    ids = [item.get("id") for item in patches if isinstance(item, dict)]
    if len(ids) != len(patches) or len(ids) != len(set(ids)):
        raise PaperBenchInventoryError("PaperBench patch IDs must be unique")
    return document


def pinned_commit() -> str:
    return str(load_inventory()["upstream"]["commit"])


def git_commit(source_root: Path) -> str | None:
    repository = source_root.parent if source_root.name == "project" else source_root
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip().lower()
    return commit if result.returncode == 0 and len(commit) == 40 else None


def _defined_symbols(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise PaperBenchInventoryError(f"cannot inspect {path}: {exc}") from exc
    values: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    values.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                values.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    return values


def _path_crosses_symlink(root: Path, relative: str) -> bool:
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


_TARGET_FILES = {
    "preparedness_turn_completer.oai_responses_turn_completer.converters.convert_conversation_to_response_input": (
        "common/preparedness_turn_completer/preparedness_turn_completer/"
        "oai_responses_turn_completer/converters.py",
        "convert_conversation_to_response_input",
    ),
    "preparedness_turn_completer.oai_responses_turn_completer.completer.convert_conversation_to_response_input": (
        "common/preparedness_turn_completer/preparedness_turn_completer/"
        "oai_responses_turn_completer/completer.py",
        "convert_conversation_to_response_input",
    ),
    "paperbench.solvers.basicagent.utils.get_instructions": (
        "paperbench/paperbench/solvers/basicagent/utils.py",
        "get_instructions",
    ),
    "paperbench.judge.simple.TASK_CATEGORY_QUESTIONS": (
        "paperbench/paperbench/judge/simple.py",
        "TASK_CATEGORY_QUESTIONS",
    ),
    "paperbench.rubric.tasks.TASK_CATEGORY_QUESTIONS": (
        "paperbench/paperbench/rubric/tasks.py",
        "TASK_CATEGORY_QUESTIONS",
    ),
}


def validate_project_root(
    project_root: Path,
    *,
    claimed_commit: str | None = None,
    require_git_identity: bool = False,
) -> Path:
    if project_root.is_symlink():
        raise PaperBenchInventoryError("PaperBench project root is unsafe")
    project = project_root.resolve(strict=True)
    if not project.is_dir():
        raise PaperBenchInventoryError("PaperBench project root is unsafe")
    inventory = load_inventory()
    pin = str(inventory["upstream"]["commit"])
    if claimed_commit is not None and claimed_commit.lower() != pin:
        raise PaperBenchInventoryError("PaperBench override claim differs from pin")
    actual_commit = git_commit(project)
    if require_git_identity and actual_commit is None:
        raise PaperBenchInventoryError("PaperBench override has no Git identity")
    if actual_commit is not None and actual_commit != pin:
        raise PaperBenchInventoryError(
            f"PaperBench commit {actual_commit} differs from reviewed pin {pin}"
        )
    for patch in inventory["patches"]:
        for target in patch["targets"]:
            if target not in _TARGET_FILES:
                raise PaperBenchInventoryError(f"unmapped patch target: {target}")
            relative, symbol = _TARGET_FILES[target]
            path = project / relative
            try:
                resolved_path = path.resolve(strict=True)
                resolved_path.relative_to(project)
            except (OSError, ValueError) as exc:
                raise PaperBenchInventoryError(
                    f"pinned PaperBench target is unsafe: {target}"
                ) from exc
            if _path_crosses_symlink(project, relative):
                raise PaperBenchInventoryError(
                    f"pinned PaperBench target crosses a symlink: {target}"
                )
            if not resolved_path.is_file() or symbol not in _defined_symbols(
                resolved_path
            ):
                raise PaperBenchInventoryError(
                    f"pinned PaperBench target is absent: {target}"
                )
    return project


__all__ = [
    "INVENTORY_PATH",
    "PaperBenchInventoryError",
    "git_commit",
    "load_inventory",
    "pinned_commit",
    "validate_project_root",
]
