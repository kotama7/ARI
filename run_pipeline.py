#!/usr/bin/env python3
"""Run post-BFTS pipeline on a completed checkpoint."""
import json, sys, yaml
from pathlib import Path

checkpoint_dir = Path(sys.argv[1])
config_path = sys.argv[2] if len(sys.argv) > 2 else str(
    Path(__file__).parent / "ari-core/config/default.yaml"
)

tree_file = checkpoint_dir / "tree.json"
data = json.loads(tree_file.read_text())
experiment_file = data["experiment_file"]
experiment_text = Path(experiment_file).read_text() if Path(experiment_file).exists() else ""
experiment_data = {"goal": experiment_text, "file": experiment_file}

sys.path.insert(0, str(Path(__file__).parent / "ari-core"))
from ari.orchestrator.node import Node, NodeStatus
from ari.config import load_config
from ari.pipeline import run_pipeline

nodes = []
for nd in data["nodes"]:
    n = Node(
        id=nd["id"], parent_id=nd.get("parent_id"), depth=nd["depth"],
        retry_count=nd.get("retry_count", 0), artifacts=nd.get("artifacts", []),
        eval_summary=nd.get("eval_summary") or nd.get("score_reason"),
        error_log=nd.get("error_log"), children=nd.get("children", []),
        created_at=nd.get("created_at", ""), completed_at=nd.get("completed_at", ""),
    )
    n.status = NodeStatus(nd["status"])
    n.has_real_data = nd.get("has_real_data", False)
    n.metrics = nd.get("metrics", {})
    n.label = type('L', (), {'value': nd.get('label', 'draft')})()
    nodes.append(n)

print(f"Loaded {len(nodes)} nodes from checkpoint")

cfg = load_config(config_path)
pipeline_cfg = getattr(cfg, "pipeline", None)
if not pipeline_cfg:
    # Load from workflow.yaml (preferred) or legacy pipeline.yaml
    _wf = Path(__file__).parent / "ari-core/config/workflow.yaml"
    pipeline_yaml = _wf if _wf.exists() else Path(__file__).parent / "ari-core/config/pipeline.yaml"
    with open(pipeline_yaml) as f:
        pipeline_cfg_data = yaml.safe_load(f)
    stages = pipeline_cfg_data.get("pipeline", pipeline_cfg_data.get("stages", []))
else:
    stages = pipeline_cfg.get("stages", [])

print(f"Pipeline stages: {[s.get('stage','?') for s in stages]}")

outputs = run_pipeline(
    stages=stages,
    all_nodes=nodes,
    experiment_data=experiment_data,
    checkpoint_dir=checkpoint_dir,
    config_path=config_path,
)

print("Pipeline complete. Outputs:")
for k, v in outputs.items():
    if isinstance(v, str):
        print(f"  {k}: {v[:60]}")
    else:
        print(f"  {k}: {type(v).__name__}")

print("Files in checkpoint:")
for f in sorted(checkpoint_dir.iterdir()):
    print(" ", f.name)
