from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPO = ROOT.parent
for path in (str(SRC), str(REPO / "ari-core"), str(REPO / "ari-skill-hpc")):
    if path not in sys.path:
        sys.path.insert(0, path)

import paperbench_inventory as inventory  # noqa: E402


def test_inventory_binds_reviewed_commit_targets_and_deletion_gates():
    document = inventory.load_inventory()
    assert document["upstream"]["commit"] == (
        "51052cede8cc608f95bb00346635e03759013e5a"
    )
    assert document["override_policy"] == "exact-commit-only"
    assert all(patch["targets"] for patch in document["patches"])
    assert all(patch["reason"] for patch in document["patches"])
    assert all(patch["deletion_gate"] for patch in document["patches"])
    project = ROOT / "vendor" / "paperbench" / "project"
    assert inventory.git_commit(project) == document["upstream"]["commit"]
    assert inventory.validate_project_root(project) == project.resolve()


def test_unpinned_runtime_override_is_rejected(tmp_path, monkeypatch):
    import _vendor_path

    monkeypatch.setenv("ARI_PAPERBENCH_PATH", str(tmp_path))
    monkeypatch.delenv("ARI_PAPERBENCH_COMMIT", raising=False)
    with pytest.raises(
        inventory.PaperBenchInventoryError,
        match="requires ARI_PAPERBENCH_COMMIT",
    ):
        _vendor_path._candidate_root()


def test_symlink_project_root_is_rejected(tmp_path):
    link = tmp_path / "project"
    link.symlink_to(
        ROOT / "vendor" / "paperbench" / "project",
        target_is_directory=True,
    )
    with pytest.raises(
        inventory.PaperBenchInventoryError,
        match="project root is unsafe",
    ):
        inventory.validate_project_root(link)


def test_clean_interpreter_loads_only_reviewed_vendor_and_installs_patches():
    code = f"""
import json, sys
sys.path[:0] = {json.dumps([str(SRC), str(REPO / 'ari-core'), str(REPO / 'ari-skill-hpc')])}
import _vendor_path
import _paperbench_bridge
from paperbench.solvers.basicagent import utils
from preparedness_turn_completer.oai_responses_turn_completer import converters
print(json.dumps({{
  'roots': _vendor_path._BOOTSTRAPPED_ROOTS,
  'persistent_roots': [p for p in _vendor_path._BOOTSTRAPPED_ROOTS if p in sys.path],
  'instruction_patch': bool(getattr(utils.get_instructions, '_ari_instr_rewritten', False)),
  'orphan_patch': bool(getattr(converters.convert_conversation_to_response_input, '_ari_orphan_patched', False)),
}}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "ARI_PAPERBENCH_PATH", "ARI_PAPERBENCH_COMMIT"}
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert len(payload["roots"]) == 3
    assert payload["persistent_roots"] == []
    assert payload["instruction_patch"] is True
    assert payload["orphan_patch"] is True
