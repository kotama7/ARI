from __future__ import annotations

import yaml

from ari.cli.run import _apply_profile, _persist_effective_workflow
from ari.config import enable_manifest_skills, load_config
from ari.config.finder import package_config_root


def test_laptop_profile_is_persisted_for_paper_and_resume(tmp_path):
    source = package_config_root() / "workflow.yaml"
    cfg = load_config(str(source))
    _apply_profile(cfg, "laptop")
    cfg.knowledge.mode = "audit"
    cfg.capability_binding.mode = "audit"
    cfg.assurance.mode = "audit"
    enable_manifest_skills(
        cfg,
        ("tool-registry-skill", "knowledge-skill", "harness-query-skill"),
    )
    destination = tmp_path / "workflow.yaml"

    _persist_effective_workflow(
        source,
        destination,
        cfg,
        profile_name="laptop",
        task_tags=("dense-linear-algebra", "gemm"),
    )

    persisted = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert persisted["resources"]["hpc_enabled"] is False
    assert persisted["resources"]["scheduler"] == "none"
    assert persisted["bfts"]["max_total_nodes"] == 8
    assert persisted["bfts"]["max_parallel_nodes"] == 2
    assert persisted["resolved_launch"] == {
        "profile": "laptop",
        "effective_config": True,
        "task_tags": ["dense-linear-algebra", "gemm"],
    }
    # Unrelated launch contracts survive the rewrite.
    assert persisted["pipeline"]
    assert persisted["skills"]
    assert persisted["knowledge"]["mode"] == "audit"
    assert persisted["capability_binding"]["mode"] == "audit"
    assert persisted["assurance"]["mode"] == "audit"
    assert {
        "tool-registry-skill",
        "knowledge-skill",
        "harness-query-skill",
    }.issubset({item["name"] for item in persisted["skills"]})

    reloaded = load_config(str(destination))
    assert reloaded.resources["hpc_enabled"] is False
    assert reloaded.resources["scheduler"] == "none"
    assert reloaded.bfts.max_total_nodes == 8
    assert reloaded.bfts.max_parallel_nodes == 2
    assert reloaded.knowledge.mode == "audit"
    assert reloaded.capability_binding.mode == "audit"
    assert reloaded.assurance.mode == "audit"
