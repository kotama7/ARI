---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/execution_request_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/execution_result_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/measurement_set_v1.schema.json
    role: schema
last_verified: 2026-08-17
---

# 実行・測定契約

ARI は workspace、local/container process、完全 log、科学測定に
`ari.public.execution` の共通契約を使用します。scheduler lifecycle は引き続き
`ari-skill-hpc` が所有します。

## 閉じた workspace

`WorkspaceRefV1` は canonical absolute root を一つ固定します。`..`、root 外の
absolute path、symlink 経由の escape を拒否します。read/write は directory file
descriptor と `O_NOFOLLOW` で各 path component を辿り、write は private
file、`fsync`、atomic rename を使います。呼び出し側が選んだ `work_dir` は、
同じ containment policy を通過した後にだけ作成されます。

このポリシーには意図的に「親切な」basename fallback がありません: 拒否した path は
error であり、別の場所へ書き換えられることは決してありません。

これは ARI tool と宣言済み input/artifact に対する file-access boundary であり、
任意の child code に対する host filesystem sandbox ではありません。ARI service
account と同等に信頼できない code には、審査済み container、scheduler isolation、
または OS sandbox が必要で、選択した substrate より強い隔離を結果に記録しません。

## 実行要求

`ExecutionRequestV1` は structured `argv` と明示的に有効化した `shell_command` の
どちらか一つだけを持ち、加えて次を持ちます。

- canonical workspace と wall-time limit;
- 最小の明示的 environment（親 process の environment は複製しません）;
- CPU、address space、process 数、output size の limit;
- `inherit` または `deny` の network policy;
- SHA-256 digest に束縛された相対 input path;
- 任意の、変更不能または明示的に未解決の container identity。

宣言された script operand は launch 前に digest を検証し、private immutable
snapshot に差し替えます。それ以外の宣言済み input は `verified-at-launch` と
記録され、snapshot を取ったとは結果に書きません。

host 上では network denial を証明できないため `network: deny` を拒否します。
審査済みの container adapter は、その exact argv が runtime の isolation boundary
（Docker の `--network none` または Apptainer/Singularity の対応する network
namespace）を含むときだけ deny を要求できます。container 実行は clean environment
を使い、未対応 runtime から host への fallback を拒否します。

## 実行結果

`ExecutionResultV1` は 2 つの識別子を分離します。

- `execution_identity` は request の canonical digest であり、retry 間で不変です;
- `attempt_id` は実際の launch ごとに一意です。

timeout/cancel は process group 全体を終了・回収します。要求 limit と、POSIX
kernel/executor が実際に強制した内容を示す `limit_report` は別に記録し、強制不能な
kernel 制御の要求は fail closed です。

要求値 `network` と実施結果 `network_report` も分離し、後者は `inherited`、
`isolated`、`external-unverified` のいずれかです。外部 launcher の出力を正規化しても、
要求した deny を検証済み isolation として黙って扱えません。

stdout/stderr の inline 部分は bounded preview です。完全 byte stream は常に
`.ari-execution/` の content-addressed artifact として digest/size 付きで残ります。
consumer は command を再実行せずに完全な出力を復元・検証できます。

## 測定

`MeasurementSetV1` は parameter、measurement、prediction、score を重ならない
namespace に分離します。各 `MeasurementRecordV1` は次を記録します。

- metric identity と有限な数値;
- 宣言された unit、または明示状態 `unit_status: missing`;
- method/source の provenance;
- 測定時の parameter;
- execution identity、attempt identity、terminal status、exit code;
- 値を支える SHA-256 artifact。

`coding-skill.emit_results` は canonical object だけを `measurement_set` に書きます。
非有限値や JSON で表せない値を文字列へ coercion せず拒否します。共通 parser は旧
flat v1 / unversioned file を read-only migration input として引き続き読み、過去の混在
document に両方の表現がある場合は照合して split-brain を拒否します。欠けた unit と
execution 証拠（provenance を含む）は推測されず、明示的に欠落のまま残ります。

coding-skill の `scientifically_admissible` は、測定が一件以上あり、すべてに unit、
成功した zero-exit execution identity、根拠 artifact が一つ以上ある場合だけ true です。
このフラグは integrity の前提条件であって domain validity の判定ではなく、
evaluator の claim gate と domain gate は引き続き適用されます。

execution context には推測不能なserver-issued receiptを含めます。emit時にworkspace、
execution attempt、status、exit code、artifact listをreceiptと照合し、全artifactを再hash
します。偽造context、server session終了後のreceipt、変更済みlogはresults fileを書く前に
fail closedとなり、receipt自体は科学recordへ保存しません。

## schema と migration

生成される規範 schema は次のとおりです。

- `workspace_ref_v1.schema.json`
- `execution_request_v1.schema.json`
- `execution_result_v1.schema.json`
- `measurement_set_v1.schema.json`

`python scripts/sync_skill_metadata.py` が schema drift を検査します。producer は
canonical な measurement set を出力し、consumer は `parse_measurement_document` を
使う必要があります。flat writer と coercion 経路は削除済みです。legacy reader は
意図的に read-only とし、compatibility support policy で再評価時点を管理します。
