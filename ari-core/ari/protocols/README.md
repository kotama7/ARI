# ari.protocols

Internal Protocols / ABCs describing the structural contract between core
sub-systems (`Evaluator`, `PromptLoader`, `ConfigLoader`, …). Sub-systems
accept these so test stubs and alternatives plug in without subclassing.

## Contents

- `README.md` — this file.
- `__init__.py` — currently exposed protocols + roadmap.
- `evaluator.py` — `Evaluator` Protocol.
- `mcp.py` — `MCPToolCaller` Protocol — the caller-facing `MCPClient` surface the RQGM tool-surface proxies duck-type.
- `model_backend.py` — `BaseModelBackend` Protocol — the `complete` / `set_context` / `stream` surface `LLMClient` satisfies structurally.
- `search.py` — `SearchStrategy` + `NodeExecutor` Protocols — BFTS ranking/selection split from single-node ReAct execution.
- `stores.py` — `CheckpointStore` / `TraceStore` Protocols + the `ArtifactStore` ABC — the runtime storage I/O seams.

## See also

- **Currently exposed protocols & roadmap** → the `__init__.py` module docstring (authoritative).
