---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/measurement_set_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# 実行・測定契約

ARI は workspace、local/container process、完全 log、科学測定に
`ari.public.execution` の共通契約を使用します。scheduler lifecycle は引き続き
`ari-skill-hpc` が所有します。

## 閉じた workspace

`WorkspaceRefV1` は canonical absolute root を一つ固定します。`..`、root 外の
absolute path、symlink 経由の escape を拒否します。read/write は directory file
descriptor と `O_NOFOLLOW` で各 path component を辿り、write は private temporary
file、`fsync`、atomic rename を使います。拒否した path を basename に変換して
別の場所へ書く fallback はありません。

これは ARI tool と宣言済み input/artifact に対する file-access boundary であり、
任意の child code に対する host filesystem sandbox ではありません。ARI service
account と同等に信頼できない code には、審査済み container、scheduler isolation、
または OS sandbox が必要で、選択した substrate より強い隔離を結果に記録しません。

## 実行要求と結果

`ExecutionRequestV1` は structured `argv` と明示的 `shell_command` のどちらか
一つ、workspace、timeout、最小 environment、CPU/memory/process/output limit、
network policy、input digest、container identity を持ちます。script operand は
launch 前に digest を検証し、private immutable snapshot に差し替えます。

親 process の environment は複製しません。host 上で `network: deny` を証明
できない場合は拒否します。Docker/Apptainer/Singularity adapter は runtime の
network isolation argv が明示される場合だけ deny を記録し、clean environment
を使い、未知の runtime から host へ暗黙 fallback しません。

`ExecutionResultV1` の `execution_identity` は同一 request の retry 間で不変、
`attempt_id` は launch ごとに一意です。timeout/cancel は process group 全体を
終了・回収します。要求 limit と実際に kernel/executor が強制した
`limit_report` は別に記録し、強制不能な要求は fail closed です。

要求値 `network` と実施結果 `network_report` も分離し、後者は `inherited`、
`isolated`、`external-unverified` のいずれかです。外部 launcher の出力を正規化しても、
要求した deny を検証済み isolation として黙って扱えません。

stdout/stderr の inline 部分は bounded preview です。完全 byte stream は常に
`.ari-execution/` の content-addressed artifact として digest/size 付きで残ります。

## 測定

`MeasurementSetV1` は parameter、measurement、prediction、score を重ならない
namespace に分離します。各 `MeasurementRecordV1` は有限な数値、unit または
`unit_status: missing`、provenance、parameter、execution identity/status/exit code、
execution attempt、根拠 artifact digest を保持します。unit や provenance は推測しません。

`coding-skill.emit_results` は canonical object だけを `measurement_set` に書きます。
非有限値や JSON で表せない値を文字列へ coercion せず拒否します。共通 parser は旧
v1 / unversioned file を read-only migration input として引き続き読み、過去の混在
document に両方の表現がある場合は照合して split-brain を拒否します。

coding-skill の `scientifically_admissible` は、測定が一件以上あり、すべてに unit、
成功した zero-exit execution identity、根拠 artifact がある場合だけ true です。
これは domain validity の代替ではなく、後段 evaluator gate も必要です。

execution context には推測不能なserver-issued receiptを含めます。emit時にworkspace、
execution attempt、status、exit code、artifact listをreceiptと照合し、全artifactを再hash
します。偽造context、server session終了後のreceipt、変更済みlogはresults fileを書く前に
fail closedとなり、receipt自体は科学recordへ保存しません。

生成 schema は `workspace_ref_v1.schema.json`、`execution_request_v1.schema.json`、
`execution_result_v1.schema.json`、`measurement_set_v1.schema.json` です。
`python scripts/sync_skill_metadata.py` が drift を検査します。flat writer/coercion は
削除済みです。legacy reader は意図的に read-only とし、compatibility support policyで
再評価時点を管理します。
