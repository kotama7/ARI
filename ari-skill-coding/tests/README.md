# ari-skill-coding/tests

Pytest suite for the coding skill's MCP server.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_edit_code.py` — pins the property the tool exists for: an ambiguous or absent snippet is refused with the file left byte-identical, `replace_all` is opt-in, matching is exact substring. An edit that lands silently in the wrong place is worse than one that fails — the agent then reports success on a kernel it never changed.
- `test_server.py` — holds the boundary the skill runs behind: workspace paths refuse `..` traversal and symlink escape, and the resolved work dir stays inside the core-owned root. The load-bearing one is that an undeclared parent secret never crosses into `run_bash` output — the assertion is on the serialized result, not just `stdout`, because a value scrubbed from one field and left in another has not been withheld. Truncated stdout is still recoverable: the full log is an artifact pinned by size and sha256. Also pins that a retry keeps the execution identity while minting a new attempt id, that `ARI_CONTAINER_IMAGE` turns into explicit argv and its absence falls back to the host, and the `run_bash` redirect → `read_file` pagination round trip.
