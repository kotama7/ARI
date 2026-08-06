# ARI hardware-counter Provider

This default-off MCP package reads hardware performance counters over a process
that is already running. It profiles; it does not execute. It creates no
process, writes nothing, requests no credential, and refuses any event outside
a reviewed set — which is what lets it declare the read-only side-effect class
that `ari.profiling.hardware-counters/v1` fixes. A tool that launched its own
target would be `ari.execution.run/v1` wearing a profiler's name.

Counters are opened through `perf_event_open` directly. A profiler binary
proves nothing: `perf` is absent from some nodes that permit counters and
present on some that deny them, and vendor profilers live at site-dependent
paths. Opening the counter observes the kernel policy that will actually apply,
inside whatever container the node runs in.

## Contents

- `README.md` — this file.
- `mcp.json` — generated compatibility descriptor; regenerate with `scripts/sync_skill_metadata.py`.
- `pyproject.toml` — package metadata.
- `skill.yaml` — canonical Provider manifest: read-only, `process-profile` only, no credential scope.
- `src/` — server implementation.
  - `server.py` — `counter_support` (does this node grant counters, established by opening one) and `measure_counters` (count reviewed events on an existing pid over a bounded window).
