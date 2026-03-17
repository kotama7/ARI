# ari-skill-orchestrator

Exposes ARI itself as an MCP server for external access.
Allows external agents and IDEs to trigger ARI experiment runs.

## Overview

ARI can function both as a standalone CLI tool and as an MCP server
embedded in other systems. This skill serves as that bridge.

## Tools

| Tool | Description |
|---|---|
| `run_experiment` | Accept experiment Markdown, run ARI asynchronously, return run_id |
| `get_status` | Return progress and results for a given run_id |
| `list_runs` | Return a list of past experiment runs |
| `get_paper` | Return the experiment_section.tex for a given run_id |

## Use Cases

- **Claude Desktop**: Trigger ARI experiments directly from chat
- **Multi-agent orchestration**: Chain ARI with other research agents
- **CI/CD integration**: Automate experiment pipelines
