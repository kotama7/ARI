# ari-skill-idea

MCP skill for literature survey and idea generation.

**Design Principle P2:** `survey` is deterministic (arXiv + Semantic
Scholar HTTP APIs only).  `generate_ideas` calls an LLM and is a P2
exception — but only in the pre-BFTS phase; once BFTS starts the
ideas are frozen, so the search loop itself remains deterministic.

## Tools

| Tool | Description | LLM |
|---|---|:---:|
| `survey` | Prior-work search via arXiv + Semantic Scholar | ✗ |
| `make_metric_spec` | Build a `MetricSpec` from `experiment.md` | ✗ |
| `generate_ideas` | Generate ranked research-idea candidates | ✓ |

## Environment variables

| Variable | Purpose | Fallback |
|---|---|---|
| `ARI_MODEL_IDEA` | Idea-generation LLM | (none) |
| `ARI_LLM_MODEL` | ARI cross-skill LLM | used when `ARI_MODEL_IDEA` is unset |
| `LLM_MODEL` | Skill-shared fallback | used when both above are unset |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |

## VirSci integration

The skill bundles a vendored copy of VirSci (a 2-hop Semantic Scholar
citation-graph helper) under `vendor/virsci/`.  VirSci injects
ancestor titles into the agent's prompts and powers the
`alternatives_considered` block when the parent run had multiple
ideas.

VirSci is licensed under its upstream terms; see
`vendor/virsci/LICENSE`.  The integration was added in the v0.4.x
series — see `CHANGELOG.md` for the per-release notes.

## P2 exception

`generate_ideas` calls an LLM, so the same survey input can yield
different idea sets across runs.  The exception is bounded: once
`generate_ideas` writes `idea.json`, the BFTS tree shape is
deterministic.

## Tests

```bash
pytest tests/test_server.py -q       # MCP-level happy path
pytest tests/test_virsci.py -q       # VirSci integration
```

## See also

- `docs/skills.md#ari-skill-idea` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
