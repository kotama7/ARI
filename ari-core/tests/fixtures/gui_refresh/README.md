# ari-core/tests/fixtures/gui_refresh

Reference run fixtures for the **GUI refresh program, Wave 0 (G0)** — the
deterministic synthetic checkpoints the program's performance and robustness
gates measure against. Charter reference:
`docs/plans/gui_refresh/00_program_charter_and_baseline.md` §Deliverables
("reference small/medium/large run fixture").

## Contents

- `README.md` — this file.
- `__init__.py` — package marker.
- `rqgm_fixture_factory.py` — Wave 4a: layers a deterministic,
- `run_fixture_factory.py` — a pure-Python factory

## Sizes

| Tier   | `nodes=` | Purpose |
| ------ | -------- | ------- |
| small  | 10       | correctness smoke — every reader must load it |
| medium | 1000     | typical long run — pagination/virtualisation budgets |
| large  | 10000    | stress ceiling — "no full JSONL read / unbounded DOM render" perf gate |

## Corrupt / partial modes (robustness gate)

Each mode first writes a fully valid checkpoint, then damages exactly one
thing, so a test isolates one failure shape at a time:

| `corrupt=`         | Damage | Expected current behaviour |
| ------------------ | ------ | -------------------------- |
| `"truncated_jsonl"` | `cost_trace.jsonl` ends mid-line | tree loads fine; JSONL readers skip the torn last line (`CostTracker._reload` semantics) |
| `"invalid_json"`    | `tree.json` syntactically broken | `ari.checkpoint.load_nodes_tree` retries once, then returns `None` |
| `"partial_write"`   | `nodes_tree.json` valid, `tree.json` missing | `load_nodes_tree` falls back to `nodes_tree.json` (tier 2 of the precedence) |

## Determinism (design principle P2)

- All timestamps are the fixed literal `2026-07-23T00:00:00Z` or fixed
  arithmetic offsets from it — never `datetime.now()`.
- All varying values derive from `(seed, node_index, field)` via
  `hashlib.sha256` — the `random` module is never imported.
- Same `(nodes, seed)` ⇒ byte-identical files (asserted by
  `tests/test_gui_baseline_run_fixtures.py`).

## Schema fidelity

Shapes mirror the production writers, not a parallel invention:

- node dicts = exactly `ari/orchestrator/node.py:Node.to_dict()` keys
  (pinned by a key-set comparison in the test);
- `tree.json` / `nodes_tree.json` / `results.json` layouts =
  `ari/cli/bfts_loop.py:_save_checkpoint`, written through the real
  `ari.checkpoint.save_*_json` helpers so JSON formatting matches
  byte-for-byte;
- `cost_trace.jsonl` lines = `ari/cost_tracker.py:CallRecord` writer field
  set (`epoch` omitted, as on every `simple_bfts` run);
- `idea.json` / `meta.json` = the minimal shapes `ari/lineage.py` reads.

## How gates use them

- **G0 baseline**: capture current-GUI load/render timings against
  small/medium/large before any refactor lands.
- **Performance gates (charter §perf)**: budgets are asserted against the
  *same* generated fixtures at each wave, so regressions are attributable.
- **Robustness gates**: GUI/API readers must degrade gracefully (no crash,
  explicit empty/error state) on the three corrupt modes.

Consumed today by `ari-core/tests/test_gui_baseline_run_fixtures.py`, which
pins loadability, determinism, corrupt-mode behaviour, and large-tier
generation.
