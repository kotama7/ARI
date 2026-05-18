# Starter experiment — copy or run as-is

Copy to `experiment.md` (gitignored) for a local default, or run:

`ari run examples/starter_experiment.md`

**Letta を立てていない場合:** メモリ MCP は既定で Letta に繋ぎます。次のいずれかで回避できます。

- 一時的: `export ARI_MEMORY_BACKEND=in_memory`（プロセス内のみ・永続化なし）
- 永続化: `.env` に `ARI_MEMORY_BACKEND=in_memory` を追記

Replace the goal and **Metrics** line with your real task. See `docs/experiment_file.md`.

## Research Goal

Sanity check: run a small ARI workflow end-to-end on this machine.

## Metrics

latency_ms
