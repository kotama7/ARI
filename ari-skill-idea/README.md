# ari-skill-idea

MCP skill for literature survey and idea generation.

**Design Principle P2:** `survey` is deterministic over Semantic Scholar
(+ frozen VirSci snapshot).  `generate_ideas` calls an LLM and is a P2
exception — but only in the pre-BFTS phase; once BFTS starts the
ideas are frozen, so the search loop itself remains deterministic.

## Tools

| Tool | Description | LLM |
|---|---|:---:|
| `survey` | Prior-work search, deterministic over Semantic Scholar (+ frozen VirSci snapshot) | ✗ |
| `generate_ideas` | Generate ranked research-idea candidates | ✓ |

## Environment variables

| Variable | Purpose | Fallback |
|---|---|---|
| `ARI_MODEL_IDEA` | Idea-generation LLM | (none) |
| `ARI_LLM_MODEL` | ARI cross-skill LLM | used when `ARI_MODEL_IDEA` is unset |
| `LLM_MODEL` | Skill-shared fallback | used when both above are unset |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |
| `ARI_IDEA_VIRSCI_REAL` | Run VirSci's real engine (vendor-wrap) instead of the re-impl loop | unset (off) |
| `ARI_IDEA_VIRSCI_K` / `_TEAM_SIZE` / `_N_AUTHORS` / `_N_PAPERS` | VirSci-live knobs | 7 / 3 / 16 / 800 |

See `REQUIREMENTS.md` (§VirSci-live) for the full `ARI_IDEA_VIRSCI_*` contract.

## VirSci integration

The skill bundles a vendored copy of VirSci (a multi-agent
idea-generation engine) under `vendor/virsci/`.  `generate_ideas`
runs a re-implemented discussion loop (`_virsci_discussion_loop`) by
default; setting `ARI_IDEA_VIRSCI_REAL` switches to the opt-in
vendor-wrap REAL path, which runs VirSci's own `select_coauthors` +
`generate_idea` on a frozen Semantic Scholar snapshot.  Lineage
(ancestor) context is injected into either path via an
`ancestor_block` string built by `format_ancestor_pool_for_virsci` /
`get_idea_pool_for_ckpt`; the vendor templates stay unmodified.  (The
2-hop citation traversal is in `survey()` via `_s2_citations`,
separate from VirSci.)

VirSci is licensed under its upstream terms; see
`vendor/virsci/LICENSE`.  See `REQUIREMENTS.md` (§VirSci-live) for the
vendor-wrap contract.

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

- `docs/reference/skills.md#ari-skill-idea` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
