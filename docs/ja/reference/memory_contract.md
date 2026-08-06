---
sources:
  - path: ari-core/ari/memory_contract.py
    role: schema
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/writer.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/retriever.py
    role: implementation
last_verified: 2026-08-02
---

# 研究メモリ契約

ARI のメモリは lineage スコープの索引であり、科学的証拠そのものではありません。
保存形式は `ari.memory-record/v1`、検索応答は
`ari.memory-retrieval/v1`、portable snapshot は `ari.memory-backup/v1` です。
JSON Schema は
`ari-core/ari/schemas/memory_record_v1.schema.json` と
`memory_retrieval_v1.schema.json`、`memory_backup_v1.schema.json` にあります。

## 不変レコード

`MemoryRecordV1` は kind/text を source run/node、順序付き ancestor、
artifact、node report、単位付き metric、confidence、再現性 event、作成 tool
に束縛します。`record_id` と `record_digest` は正規化 payload に対する同一の
SHA-256 content address です。検索と restore は再検証し、改変を拒否します。

artifact ref は安全な相対 path、完全な SHA-256、byte size、role、
`verified`/`unverified` を持ちます。writer が宣言 root 配下の実ファイルを読み、
digest が一致した場合だけ `verified` になります。metric には明示 unit、node
report ref には report digest が必須です。memory text や `unverified` ref だけを
論文の証拠にはできません。

write は append-only で record digest により冪等です。再現性状態は対象を更新せず、
新しい `reproducibility_event` として追加します。公開 MCP に clear/delete tool は
ありません。明示的 restore や配備復旧用の checkpoint purge だけを管理 API に残します。

## 検索プロヴェナンス

全検索は backend、client/server version、embedding model/version、ranking、
determinism、query digest、candidate/return count、上限、filter evidence を返します。
Letta の embedding rank は非決定的と明記されます。型付き filter は可変 projection
ではなく検証済み canonical record を使い、旧 unversioned row は除外します。

## backup、restore、migration

`ari memory backup` は root digest、ソート済み record digest index、検証対象の
logical record order、ReAct entry digest を持つ決定的な
`memory_backup.v1.json.gz` を作ります。restore は書込み前に
文書全体を検証し、`skip` / `merge` / `overwrite` を提供します。record は content
digest で重複排除され、別の clean Letta 配備へ移せます。

run/resume は legacy file を読みません。v0.5 JSONL は明示的な
`ari memory migrate` で検証・v1 変換し、portable backup の成功後に元ファイルを
archive します。実験横断 global memory は警告対象ですが import しません。

## 配備サポート

production はすべて Letta です。`InMemoryBackend` は test marker が必要で、workflow
から選べません。

| mode | status | scope / gate |
|---|---|---|
| Letta Cloud | サポート | HTTPS endpoint/API key、health check 必須 |
| Docker Compose | サポート、local workstation 推奨 | Postgres compose と clean-start test |
| Apptainer / Singularity | サポート、HPC 推奨 | portable start script、env/runtime check |
| pip | サポート fallback | containerless local server、静的 clean-launch test。失敗した container path から暗黙 fallback しない |

support owner は ARI maintainers です。pip は containerless host のため維持し、配備 issue
と利用報告に基づき v1.1 で再評価します。test backend への暗黙 fallback は禁止です。

## consumer rule

論文・図の主張には `get_verified_context` を使います。未検証 memory は補助情報として
表示できますが、全 artifact が verified で、最新の再実行 event が
`rerun_failed` でない record だけが `usable_for_claims` に入ります。
