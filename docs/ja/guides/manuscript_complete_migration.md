---
sources:
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: scripts/manuscript_complete_release_gates.json
    role: config
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
last_verified: 2026-08-09
---

# Manuscript Complete の移行とロールバック

レガシーチェックポイントが遡って complete と宣言されることは決してありません。

- `off` は移行を一切行わず、`.ari-manuscript` ディレクトリも作成しません。
- `audit` は今も存在するファイルを遅延的に棚卸しします。過去の欠落は
  `missing` または `unavailable` のまま残り、成功した事実として再構成される
  ことはありません。
- `enforce` は、新しい authoring の前には生成し直した現行の profile/readiness
  を、lock の前には生成し直した publication 決定を要求します。

推奨される移行手順:

1. レガシーチェックポイントを変更せずにコピーするか、そのまま保持します。
2. `ari manuscript compile CHECKPOINT --mode audit` を実行します。
3. omission、negative lane、未解決の requirement を確認します。
4. 明示的な recovery、retrieval、experiment、certification、disclosure、または
   human の action を選択します。証拠を作り出すために古い論文/build を編集
   しては決していけません。
5. enforce の attempt を compile し、準備が整ったときにだけ新しい bound build
   を執筆します。
6. 古い論文はレガシーな artifact として保持します; その歴史的な status を
   新しい決定で上書きしないでください。

ロールバックは設定を `off` へ戻します。追加された attempt は forensics のために
残り、チェックポイントとともにアーカイブできます。ロールバックが repair の
失敗、block された draft、古い publication 決定を削除してはなりません。

既知のレガシー情報損失には、bounded な configuration・claim・reference・
source・prompt の projection が含まれます。audit は今も観測可能なものと、
可能な場合には omission の理由を報告します; 過去のバイトが存在しないことは、
その項目が一度も存在しなかったことの証拠にはなりません。

恒久的なドライランは `ari-core/tests/test_manuscript_complete.py` の
`test_legacy_migration_and_rollback_are_additive` です。off が Manuscript の
state を作らないこと、audit がギャップを記録すること、履歴が検証不能なとき
enforce が block されたままであること、そしてロールバックがそれ以前のすべての
attempt とバイト単位で同一のレガシー論文を保持することを検証します。リリース
マニフェストはこのテストを実行し、そのログを保持します; 手作業で編集した移行
チェックリストで置き換えてはいけません。
