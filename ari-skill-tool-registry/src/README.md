# tool registry source

- `models.py` — canonical descriptor, lock, admission, handle, and cassette models.
- `providers.py` — provider adapter protocol plus isolated generic stdio MCP adapter.
- `sources.py` — production source declarations and test-only static source seam.
- `admission.py` — four-level admission and semantic-overlap decisions.
- `catalog.py` — deterministic lock/index builder, verification, and pending review diff.
- `storage.py` — content-addressed result artifacts and offline replay cassettes.
- `broker.py` — immutable discover/describe/invoke/status/result runtime.
- `server.py` — fixed five-tool MCP surface.
- `sync_catalog.py` — operator-only source synchronization command.
- `../scripts/sync_contracts.py` — deterministic JSON Schema generation and drift check.
