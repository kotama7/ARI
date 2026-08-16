---
sources:
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
last_verified: 2026-07-30
---

# 実行モード: `simple_bfts` と `ari_rqgm`

ARI には 2 つの実行モードがあります:

- **`simple_bfts`**（デフォルト）— 現行の ARI そのままで、変更はありません。workflow.yaml に
  `ari:`/`rqgm:` ブロックが無い場合（つまり RQGM 以前のすべての設定）、ARI は RQGM
  オブジェクトを一切構築せず、`ari.rqgm` モジュールをインポートせず、新しい
  チェックポイントファイルも書きません。
- **`ari_rqgm`**（オプトイン）— Constitutional ARI-RQGM のエポックガバナンスと
  共進化。デフォルトで有効になることは決してありません。`--mode` CLI フラグは
  存在せず、有効化は設定上の決定です: `workflow.yaml` / 環境変数（後述 — こちらが
  正準の説明）で行うか、**新規ランに限り**ダッシュボードの Configuration Studio
  から行います（[GUI からの選択](#gui-からモードを選択する)）。

## RQGM を有効にする

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch (simple_bfts | ari_rqgm)
rqgm:
  enabled: true       # redundant safety interlock
```

両方のキーが一致している必要があります。実効モードは純粋関数
`ari.rqgm.mode.resolve_effective_mode` によって解決されます:

| `ari.mode` | `rqgm.enabled` | 実効モード | 動作 |
|---|---|---|---|
| `simple_bfts` | `false` | `simple_bfts` | デフォルト。何も出力しない |
| `simple_bfts` | `true` | `simple_bfts` | 警告: インターロックは設定されているがモードは simple_bfts |
| `ari_rqgm` | `false` | `simple_bfts` | 警告: モードは要求されたがインターロックがオフ |
| `ari_rqgm` | `true` | `ari_rqgm` | RQGM ランタイムを構築 |

環境変数オーバーライド（プロファイルの後に適用されるため、明示的な env の選択が
勝ちます）: `ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} および `ARI_RQGM_ENABLED` ∈
{`0`,`1`,`true`,`false`}。不正な値は警告の上で無視されます
（validate-before-assign）。

実効モードが `ari_rqgm` のとき、`ari run` は最初のノードが走る前に
`{checkpoint}/rqgm_state.json`（mode、interlock、`mode_source` ∈
`config|env|resume`、switch journal）を書き込み、同梱の `constitution.yaml` を
チェックポイントへコピーします（copy-once、上書きされることはなく、進化もしない）。
設立登録も起動時に実行されます: `epoch_000` が開く前に、設立プロンプト /
コンポーネント集合が `rqgm_transitions.jsonl` にコミットされるため、
`rqgm_registry.json` と `epoch_state.json` は最初のノードが完了する前に現れます
（[RQGM ランタイムウォークスルー](../concepts/rqgm_runtime_walkthrough.md)を参照）。
**`rqgm_state.json` が存在しないことは、純粋な `simple_bfts` ランであることを
意味します** — デフォルトのチェックポイントは RQGM 以前の ARI とバイト単位で
同一のままです。

`mode_source` は**起動時にモードがどう決まったか**を記録するもので、決定規則は
一つだけです: `ari run` は起動時のプロセス環境で `ARI_MODE` または
`ARI_RQGM_ENABLED` が空でない値に設定されていれば `env`、そうでなければ
`config` を記録します。
この判定は `export_resolved_config_to_skill_env` が `ARI_MODE` を実効モードで
`setdefault` する**前**に行われるため、YAML だけで設定されたランが env 由来と
誤って記録されることはありません。重要なのは「誰が設定したか」ではなく「存在
するか」です: 親プロセスから継承した値も env 由来として扱われ、Configuration
Studio から非デフォルトのモードで起動したランは `env` を記録します（この起動
経路は `ari:`/`rqgm:` ブロックをチェックポイントの `workflow.yaml` にマージする
のに加えて、`ARI_MODE`/`ARI_RQGM_ENABLED` を起動する CLI の環境へエクスポート
するためです）。これら以外の文字列は警告の上で `config` に丸められます。

3 つ目の受理値 `resume` は**予約済みで、書き込まれることはありません**。
`rqgm_state.json` はラン開始時に `persist_run_start`（ランタイムで唯一
`write_rqgm_state` を呼ぶ箇所）が一度だけ書き込み、`ari resume` はそれを読む
だけです（`reconcile_resume_mode`）。
したがって resume したランが `mode_source: resume` を持つことはなく、この
フィールドは常に**最初の**起動を表します。resume をまたいで値が変わることを
期待してはいけません。

2 つのアクセサはいずれも契約として非致命です。`read_rqgm_state` はファイルが
無い・読めない・JSON オブジェクトでない場合に `None` を返します — 不在も破損も
同じく「RQGM 状態なし」、すなわち `simple_bfts` ランとして読まれます。
`write_rqgm_state` はあらゆる例外を捕捉して警告ログを出すため、来歴の書き込みに
失敗しても記録が劣化するだけで、ランに例外が伝播することはありません。

## モード切替のタイミングポリシー

許可されるもの:

1. **ラン開始時** — `ari_rqgm` への唯一の入口。実効モードは一度だけ解決され、
   最初のノードが走る前に永続化されます。
2. **エポック境界**（`ari_rqgm` ラン内のみ）— 設計上はエポック境界トランザクション
   の中での `ari_rqgm → simple_bfts` への**ダウングレード**（コスト/緊急
   フォールバック）が予約されています。**これは未実装です。** ダウングレード
   イベントは一切発行されず、`rqgm_state.json` はラン開始時に一度だけ書かれて
   以後書き換えられず、`ConstitutionalKernel.validate_epoch_invariance` は
   モードを一切参照しません — 発行するのは `CK-EPO-001`（凍結された active set
   の外にある `prompt_hash` を持つレコード）と `CK-EPO-002`（エポック途中の
   非緊急な active set 変更）だけです。したがって実運用ではランのモードは
   開始から終了まで固定です。ダウングレードは利用可能な挙動ではなく、
   予約された設計として扱ってください。

禁止 / 不可能なもの:

- **ラン途中**での `simple_bfts → ari_rqgm`: `simple_bfts` にはエポック境界が
  存在しないため、合法な切替ポイントがありません。アップグレードには新しいラン
  （または `ARI_MODE=ari_rqgm` で起動した子ラン）が必要です。
- エポック途中、ガバナンストランザクション途中、レジストリ遷移途中、
  フロンティア再構築途中でのあらゆる切替。

resume の規則: `ari resume` は `rqgm_state.json` をチェックポイント優先で読み、
**永続化されたモードが**パッケージ設定と env に優先します。不一致は警告を
生みますが、ラン途中のモード反転は決して起こしません — ランのモードは
ラン全体を通じて不変です（上記のエポック境界ダウングレードは予約された設計で、
未実装です）。

すべての RQGM モード読み取り側の読み取り優先順位:
`{checkpoint}/rqgm_state.json` → 型付き設定（標準の優先順位における
`--config`/チェックポイント/パッケージ YAML + プロファイル + env）→ デフォルト。
いかなる RQGM コードもパッケージの workflow.yaml を直接読み直すことはありません。

## VirSci の独立性

`proposal_router.generators.virsci.enabled`（デフォルト `false`）は `ari.mode`
と直交します: 4 通りの組み合わせすべてが有効であり、モード解決コードは
`proposal_router.*` を決して読まず、VirSci のゲートは `ari.mode` を決して
読みません。VirSci がオフのとき、どちらのモードでも VirSci ランタイム、
vendored パス、プロンプト、スナップショットコーパスには一切触れません。

この最後の保証が成り立つのは K/C/A が**デフォルト**の姿勢のときだけで、
抜け道はこの軸ではなくそちらの軸にあります: `knowledge.mode` /
`capability_binding.mode` / `assurance.mode` のいずれかをデフォルトから
外すと `ProposalRouter._typed_contract_required()` が true になり、ルータは
（MCP クライアントがあれば）`VirSciAdapter` を構築し、
`generators.virsci.enabled` の値にかかわらず `virsci` を有効として扱います。
[VirSci 統合](virsci_integration.md) を参照してください。

## 論文実行軸: `paper.mode`

論文執筆フェーズ（`ari paper`）は `ari.mode` と完全に**直交する**独自の実行軸を
持ちます。これは別の純粋関数 `ari.rqgm.paper_mode.resolve_paper_mode`
（`PaperMode` ∈ {`linear`, `rqgm_archive`}）で解決され、`paper.mode` /
`rqgm.paper.enabled` のみを読み、`ari.mode` / `rqgm.enabled` は決して読みません:

- **`linear`**（デフォルト）— 現行の論文パイプラインそのままで、
  `ari.mode: simple_bfts` の下ではバイト単位で同一です。3 つの入口
  （`ari paper` / `ari run` / `ari resume`）はいずれも共有ディスパッチ
  （`ari/cli/paper_dispatch.py:run_paper_phase`）を経由し、この軸では
  `generate_paper_section` を呼び、`ari.rqgm` モジュールを一切
  インポートしません。`{checkpoint}/paper_archive_state.json` が存在しないことは、
  純粋な `linear` 論文ランであることを意味します。`ari.mode: ari_rqgm` の下では
  ディスパッチが追加で*探索*軸の paper-candidate プリフライト
  （[RQGM ランタイムウォークスルー](../concepts/rqgm_runtime_walkthrough.md#_8-ラン終了)
  に記載）を走らせるため、論文フェーズがバイト同一なのはデフォルトの探索モードに
  限られます。
- **`rqgm_archive`**（オプトイン）— 憲法的な論文アーカイブ: ドラフト空間上の
  浅い best-first ツリー（`PaperArchiveStrategy`、`ari/rqgm/paper_archive.py`）で、
  ガバナンス下の `paper_writer` + `paper_reviewer` が非ガバナンスの
  `ari-skill-paper` エグゼキュータ（`ari/rqgm/paper_draft_executor.py`）を「手」
  として駆動します。レイヤ自体は
  [RQGM アーキテクチャ](../concepts/rqgm_architecture.md)を参照してください。

### 論文アーカイブを有効にする

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive       # master switch (linear | rqgm_archive)
rqgm:
  paper:
    enabled: true          # redundant safety interlock
```

両方のキーが一致している必要があります。インターロックは警告の上で `linear`
へフェイルセーフします（`resolve_paper_mode`）:

| `paper.mode` | `rqgm.paper.enabled` | 実効論文モード | 動作 |
|---|---|---|---|
| `linear` | `false` | `linear` | デフォルト。何も出力しない |
| `linear` | `true` | `linear` | 警告: インターロックは設定されているがモードは linear |
| `rqgm_archive` | `false` | `linear` | 警告: モードは要求されたがインターロックがオフ |
| `rqgm_archive` | `true` | `rqgm_archive` | 論文アーカイブランタイムを構築 |

環境変数オーバーライド（`apply_paper_env_overrides` により適用され、`ari
paper` コマンドが明示的に呼び出します — 素の `load_config` に便乗することは
ありません）: `ARI_PAPER_MODE` ∈ {`linear`, `rqgm_archive`} および
`ARI_RQGM_PAPER_ENABLED` ∈ {`0`,`1`,`true`,`false`}。不正な値は警告の上で
無視されます。

実効論文モードが `rqgm_archive` のとき、`ari paper` はアーカイブループが走る
前に `{checkpoint}/paper_archive_state.json` を一度だけ書き込みます（論文
モード、interlock、`mode_source` ∈ `config|env|resume`、探索モード、シード
ノード。`persist_paper_run_start`、write-once — 後の呼び出しが別のシードを
算出した場合は、レコードを書き換えるのではなくファイルの `seed_journal` に
`seed_changed` エントリを追記します）。再起動時はチェックポイント
優先で突き合わせます（`reconcile_paper_resume_mode`）: 永続化された論文モードが
設定と env に優先し、不一致は警告を生み、状態ファイルの無いチェックポイントは
そのフェーズで `linear` のままです — つまり純粋な linear 再起動では `ari.rqgm`
モジュールが決してロードされません。この軸でも `resume` は予約済みです:
`ari paper` が `mode_source: resume` を選ぶのは `paper_archive_state.json` が
既に存在する場合だけで、それはまさに write-once のガードが書き込みをスキップ
する場合なので、永続化されたファイルは常に最初の呼び出しの `config`/`env` の
決定を記録します。

### agent-as-judge によるドラフト採点（オプトイン）

`rqgm.paper.reviewer.agent_as_judge.enabled`（bool、**デフォルト `false`**。
`max_tokens` のデフォルトは `1024`）が、各アーカイブドラフトの採点方法を選びます。
環境変数オーバーライド `ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`} は
同じ `apply_paper_env_overrides` により、`ARI_PAPER_MODE` /
`ARI_RQGM_PAPER_ENABLED` と同一の validate-before-assign の姿勢で適用されます —
不正な値は警告の上で無視されます。他のすべての `rqgm.paper.*` キーと同様、
実効 `rqgm_archive` 論文モードの下でのみ意味を持ちます。

- **オフ**（デフォルト）— 決定論的で LLM を使わない venue ルーブリック採点:
  `GovernedPaperReviewer.score` 自身の else 分岐（`_rubric_draft_score`）であり、
  `ari/rqgm/paper_judge.py:deterministic_rubric_score_fn` が judge のフォール
  バック先として同じ組み合わせをパッケージ化したものです。ドラフト採点パスに
  ライブの LLM 呼び出しは一切置かれないため、P2 の決定性が保たれます。
- **オン** — 共有の論文ディスパッチ
  （`ari/cli/paper_dispatch.py:build_agent_as_judge`。`ari paper` / `ari run` /
  `ari resume` のいずれからも使われます）が実際の `LLMClient` に裏打ちされた
  `reviewer_score_fn`（`build_agent_as_judge_score_fn`）を注入します。これは
  **同一の** venue ルーブリック軸に沿って各ドラフトを採点し、その重みは
  ACTIVE なガバナンス下 `paper_reviewer` プロンプトの強調点に従います（つまり
  レビュアを進化させると best-belief 選択が動きます）。さらに決定論的な読み手が
  読めない軸 — `novelty`、`significance` — を読めるため、成熟した 2 本のドラフトが
  どちらも構造ルーブリックを飽和させて同点になる識別限界を打ち破ります。

採点は**フェイルオープンであり、決してでっち上げの定数を返しません**: LLM
エラー、パースできない応答、ルーブリック軸を 1 つも挙げない応答、ルーブリック
総軸重みの 50% 未満しかカバーしない応答は、いずれも決定論的ルーブリックへ縮退し、
非有限値は選択へ伝播させず棄却します。判定スコアもフォールバックスコアも
下流の消費者からは同じ float に見えるため、score_fn は `judged` / `degraded`
カウンタを保持し、論文ディスパッチがアーカイブ後にそれをログ出力します
（`log_agent_as_judge_provenance`）— さもなければ
全呼び出しで LLM がダウンしていたランが、完全に判定されたランと見分けが
つきません。

### `ari.mode` からの 2×2 独立性

2 つの軸は独立しており、4 通りの組み合わせすべてが有効です:

| `ari.mode` | `paper.mode` | 探索 | 論文執筆 |
|---|---|---|---|
| `simple_bfts` | `linear` | 古典的 BFTS | 古典的 linear 論文 |
| `simple_bfts` | `rqgm_archive` | 古典的 BFTS | ガバナンス下のドラフトアーカイブ |
| `ari_rqgm` | `linear` | エポックガバナンス | 古典的 linear 論文 |
| `ari_rqgm` | `rqgm_archive` | エポックガバナンス | ガバナンス下のドラフトアーカイブ |

`resolve_paper_mode` は `ari.mode` を決して読まず、探索側の
`resolve_effective_mode` は `paper.*` を決して読みません; `_effective_paper_mode_str`
は論文有効化セルを import 無しでミラーするため、デフォルトの論文ランは
`ari.rqgm.paper_mode` を決してロードしません（`tests/test_paper_mode.py` で
パリティをピン留め）。ガバナンス下の `paper_writer` / `paper_reviewer` ロールは
**paper-mode-gated な設立行**です（`ari/rqgm/events.py:EVOLVABLE_ROLES`）: これらは
実効 `rqgm_archive` 論文モードの下でのみレジストリに入るため、探索 `ari_rqgm`
の起動は論文アーカイブの有無にかかわらずバイト単位で同一です。

### コスト上限と縮退した on-ramp

エポックあたりのドラフト集団は `node_budget =
min(width·(1+refine_rounds), max_expansions)`
（`paper_archive.archive_node_budget`）で有界であり、これが**どの深さでも**
BFTS の `max_total_nodes` になります — ツリーを深くしても同じ予算を再配分する
だけで、決して掛け算にはなりません（`width^depth` 項なし）。デフォルト設定
（`width: 4`、`refine_rounds: 2`、`max_expansions: 12`、`depth: 3`）では
`min(4·(1+2), 12) = 12` ノードです。2 つの on-ramp がデフォルトを安価かつ
正直に保ちます:

- `rqgm.paper.prompt_evolution.enabled: false` はアーカイブを reviewed
  best-of-N に縮退させます — 候補の生成が抑制され、ロールは設立時の v1
  プロンプトに固定され、コストは現行の論文フェーズ相当です。
- `rqgm.paper.anchor.enabled: false`（**デフォルト**）はレビュアにグラウンド
  トゥルースのアンカーを与えないため、`prompt_evolution.enabled: true` でも
  デフォルトの `rqgm_archive` は、curated なコーパスが供給されるまで reviewed
  best-of-N として振る舞います
  （[論文アーカイブの採用](rqgm_migration.md#paper-mode-の採用)を参照）。

論文フェーズがガバナンス予算の閉じた `ACTION_KINDS` 集合
（`ari/rqgm/budget.py`）に追加するアクション種別はちょうど 1 つ、
`paper_anchor_scoring` だけです。これはアクティブなレビュアが採点される
held-out アンカーケース 1 件につき 1 単位を消費します。エポックあたりの上限は
`rqgm.paper.anchor.sample_size`（デフォルト `8`）であり、
`rqgm.paper.anchor.enabled` が false のとき——上記のデフォルト——は `0` です。
したがってデフォルトの on-ramp では、アンカー一致度の採点は単にスキップされる
のではなく、予算がゼロとして計上されます（`shadow_call` や `virsci_call` が
既に持つ「無効なら 0 を返す」形と同じです）。論文アーカイブが取る他の予算対象
アクションは、すべて既存の上限に計上されます: 例えば self-preference
アドバーサリは各攻撃ラウンドを `adversary_call` /
`rqgm.adversarial.max_adversary_calls_per_epoch` でゲートします。

ここでの「エポックあたり」とは*論文*エポックあたりの意味です — アーカイブは
`current_paper_epoch`（論文エポックオブジェクトが開いていなければ
`paper_epoch_000`）の上に自前の `GovernanceBudgetManager` を構築します。
予算の枯渇はいつもの形で縮退します: ケースのループが止まり、レビュアは採点
済みの接頭部が与えた一致率をそのまま保ち、論文ループへ例外は送出されません。
カウンタを読む際に効いてくる点が 2 つあります。予算はレビュアが判定を出す
*前*に計上されるため、判定が得られなかったケース——したがって一致度の
カバレッジからは除外されるケース——も 1 単位を消費します。そして予算マネージャ
は `None` への fail-open であり、チェックポイントディレクトリのない論文ラン、
あるいはマネージャの構築に失敗したランでは、アンカー採点はブロックされるので
はなく**ゲートされないまま**走ります。エポックあたりの集計は
`{checkpoint}/paper_archive_state.json` の `budget_counters`
（`anchor_scoring_calls`）へベストエフォートでミラーされ、`rqgm_audit.jsonl`
の永続的な `budget_consumed` 行から導出されるため、再実行しても二重計上には
なりません。

**既知のギャップ — 上限が覆うのは 2 つあるアンカーパスのうち 1 つだけです。**
計上されるのはアクティブなレビュアのパスだけです。このパスは held-out ケース
1 件ごとにゲートしてから 1 単位を消費し、`sample_size` と
`anchor_scoring_calls` が記述しているのはこのパスです。co-evolution の候補
評価器は、保留中の `paper_reviewer` 候補ごとに同じ held-out ケース列を*もう
一度*走査します。これは `score_reviewer_on_anchor`
（`ari/rqgm/paper_anchor.py`）を直接呼ぶ経路で、この関数は予算マネージャを
持たないため、ゲートも消費も行いません。したがって
`rqgm.paper.anchor.sample_size` が有界にしているのは、論文エポックあたりの
アンカー評価回数ではなく、アクティブなレビュアのケース数です。これを
O(候補数 × `sample_size`) という形のコストモデルとして読む読者は、それが
アクティブレビュア側の半分だけを有界にしていると読むべきです — 保留中の
レビュア候補が C 件あれば、コーパスはさらに C 回、全件かつ上限なしで走査
されるからです。`anchor_scoring_calls` は `budget_consumed` 行から導出される
ため、そのエポックのアンカー作業をちょうどその分だけ過少報告します。ここで
問題になるのはコストと可観測性であって、ガバナンスではありません — 候補の
判定は変わらず、ゲートが緩むこともありません。

出荷時のデフォルトでは、独立した 2 つの条件が両方のパスを静かに保ちます。
`rqgm.paper.anchor.enabled: false` では `load_anchor_corpus` がプールを返さず、
候補側の分岐はそのプールでガードされているため、そもそも走りません。そして
本番では `reviewer_verdict_fn` がどこにも配線されていません — `ari paper` は
論文アーカイブランタイムをそれなしで構築します — ので、コーパスを供給した後
でも `anchor_verdict` は全ケースで `None` を返し、両方のパスは採点せず棄権
します。その状態でもアクティブなパスは予算を消費します（上記のとおり計上が
判定に先行するため）。ゲートされない候補側のパスは何も消費せず、採点の実作業
も行いません。過少計上が実害になるのは、この上限が存在する理由そのものの
構成、すなわちコーパスがあり判定ソースが配線された状態のときだけです。その
とき保留中のレビュア候補 1 件ごとに、どの上限も止めず、どのカウンタも記録
しないコーパス全走査が 1 回ずつ追加されます。

## GUI からモードを選択する

ここまでの記述が正準です: モードは設定上の決定であり、標準の優先順位で
`workflow.yaml` + プロファイル + env から解決されます。そして既に存在するランに
ついては `{checkpoint}/rqgm_state.json`（または
`{checkpoint}/paper_archive_state.json`）が正本です。

**ADR-09**（2026-07-27 受理）以降、ダッシュボードは**新規**ランについてその決定を
行えます — 連動する 2 つのキーを手で編集させる代わりに、です。これは以前の
「v1 に GUI トグルは無い」という記述を、この場合に限って supersede します —
`--mode` CLI フラグは依然として存在せず、既に存在するランのモードを変更できる
GUI パスもありません。

**コントロールの場所。** Configuration Studio（`#/studio`）の *Execution*
セクション。スコープは**ランテンプレート**または**ランドラフト**です。軸ごとに
1 つずつ、2 つのコントロールがあります:

| コントロール | 書き込むキー | 値 |
|---|---|---|
| Execution mode | `ari.mode` **と** `rqgm.enabled` | `simple_bfts`（デフォルト）/ `ari_rqgm` |
| Paper mode | `paper.mode` **と** `rqgm.paper.enabled` | `linear`（デフォルト）/ `rqgm_archive` |

使う前に知っておく価値のある性質が 4 つあります:

1. **1 つのコントロールがインターロックの両方のキーを書きます。** `ari_rqgm` を
   選ぶと、同一の保存で `ari.mode: ari_rqgm` *と* `rqgm.enabled: true` が
   書かれます。ランタイムが黙って縮退するような片側だけの組を GUI が作ることは
   できません。何らかの経緯で片側だけを持ち、一致する相方を欠く文書は、
   テンプレートの create/PATCH、ドラフトの create/PATCH、そして起動時に、
   型付きの 400 `mode_interlock_mismatch` で拒否されます。
2. **新規ラン専用。** どちらの葉も `mutability: new_run_only` です。選択は
   Studio がこれから起動しようとしているランに適用されます。**resume は影響を
   受けません**: `ari resume` は従来どおり `{checkpoint}/rqgm_state.json` を
   チェックポイント優先で読み、永続化されたモードが設定と env に優先し、ランの
   モードはラン全体を通じて不変のままです。そのファイル
   を書く GUI パスは存在しません。
3. **プロジェクトスコープは今も拒否します。** モードのパスは `scope: run` なので、
   プロジェクト既定値の文書はそれらを拒否します（`not_project_scope`）; そのスコープ
   ではコントロールが無効化され、理由が表示されます。
4. **開かれているのはこの 4 葉だけ。** `Execution mode` カテゴリと `rqgm.*` ツリー
   の残り 104 パス（epoch、kernel、governance、adversarial、予算のチューニング）は、
   本リリースでは GUI から編集**できません**。それらは実効値付きの読み取り専用
   として表示され続け、それらを持つドラフトは起動時に `mode_locked` で拒否され
   ます — 変更するには `workflow.yaml` を編集してください。モードを選ぶことは
   ガバナンスの変更にはあたりません: RQGM ガバナンスワークスペースと
   `/api/v1/runs/{run_id}/rqgm/*` のルートは読み取り専用のままです。

**GUI で選ばれたモードがチェックポイントに与える影響。** デフォルト以外の選択は
両方の形で実体化されるため、チェックポイントは自己記述的になります: 最小限の
`ari:` / `rqgm:` / `paper:` ブロックがそのラン**自身の** `workflow.yaml` コピーへ
マージされ（同梱ファイルは決して変更されません。これらのトップレベルキーが無い
場合はブロックが追記され、既存のバイトとコメントはすべてそのまま残ります）、
文書化された env オーバーライド `ARI_MODE`、`ARI_RQGM_ENABLED`、`ARI_PAPER_MODE`、
`ARI_RQGM_PAPER_ENABLED` がランのサブプロセスへエクスポートされます。デフォルトの
ままにすれば書き込みもエクスポートも**一切ありません** — `simple_bfts` + `linear`
の起動は ADR-09 以前とバイト単位で同一であり、これはデフォルト値を明示的に選び
直したドラフトにも当てはまります（判定するのは解決後の*値*であって、コントロール
に触れたかどうかではありません）。

**ランタイムがフォールバックしたとき GUI が表示するもの。** 起動レビューは要求
した内容を表示しません — ランのプレビューマニフェストから読んだ**解決後の**
モード、すなわち `resolve_effective_mode` / `resolve_paper_mode` が警告して
フォールバックする規則を適用した後の値を表示します。Studio が所有しない層が組を
壊した場合（例: ドラフトが `ari_rqgm` を要求している一方で、サーバーの環境に
`ARI_RQGM_ENABLED=0` がある場合）、レビューは要求値・解決値・リゾルバの警告を
逐語で描画し、起動はフォールバックしたランを黙って始めるのではなく
`interlock_mismatch` の検証エラーで**ブロック**されます。ランがガバナンス下と
して表示されるのは、解決後のモードが `ari_rqgm` のときだけです。

## 憲法カーネル（Layer 0）

`ari_rqgm` モードでは、あらゆるガバナンス状態変更が `ConstitutionalKernel`
（`ari/rqgm/kernel.py`）によって検証されます。カーネルは**決定論的、非進化的で、
LLM ジャッジではありません**: LLM 呼び出しゼロ、ネットワーク呼び出しゼロ、
壁時計依存の判定ゼロ（設計原則 P2）。カーネルが判定するのは手続きのみであり、
研究の正しさは決して判定しません。固定層全体は決して進化の対象になりません:
カーネル、スキーマチェッカ、ハッシュチェッカ、アクセス制御（capability
matrix）、監査ログ、遷移規則、選択的消去規則、固定検証器（results.json
マージ）、メトリクス再計算器、そして claim-evidence hard gate です。

規則は設定ではなくコードに存在します: `ari/rqgm/kernel_rules.py`（ロール規則、
capability matrix、severity map）と `ari/rqgm/transition_rules.py`
（固定の T1–T21 遷移テーブル。RegistryTransitionEngine と共有される単一の
真実源）。全テーブルにわたる `constitution_hash` は
`ari-core/tests/test_rqgm_kernel.py` によってピン留めされ、`meta.json` に
追加的に記録されるため、いかなる規則編集も明示的なレビュー対象 diff +
ハッシュの再ピン留めになります。同梱の `constitution.yaml` は人間可読の
声明にすぎず、編集しても何も変わりません。

**なぜ規則がコードなのか。** チェックポイントディレクトリはフラットな共有
ファイルシステムであり、あらゆる MCP スキルが書き込めます。ロール規則、
capability matrix、severity map、遷移テーブルをチェックポイントスコープの
YAML に置けば、自分を裁く憲法への進化 / 改竄チャネルを任意のコンポーネントに
手渡すことになります。そのため、これらは凍結された Python 定数であり、
カーネルで設定可能なのは数値だけです: `rqgm.kernel.enforcement`、
`rqgm.kernel.audit_chain`、`rqgm.kernel.float_tolerance`。

`CAPABILITY_MATRIX` には 3 つの定数が焼き込まれており、すべてのティアの
すべてのロールで成立します: `read: retired_prompt_text` を付与する
`(role, tier)` 行は 1 つも存在しません（正規の読み出し経路は
`RetiredPromptAccessGuard` であり、その狭い fixed ティア免除集合は
マトリクスによる付与ではなくマトリクスの迂回です）。`write: registry` と
`activate: candidates` を持つのは `fixed` ティアの
`registry_transition_engine` だけです。そして進化可能ロールの `meta`
ティア行はそのどちらも持たず、候補が何を宣言していても変わりません。

**受け入れているコスト。** 規則は `constitution_hash` に覆われたコードで
あるため、規則を 1 つ変えることは、コードレビューと
`ari-core/tests/test_rqgm_kernel.py` の期待ハッシュの手作業での再ピン留めを
意味します。*インポートされた* 遷移テーブルを編集してもハッシュが動くことを
テストが検証しているので、もう一方のモジュールを直すことでピンを回避する
ことはできません。実験の途中で規則にパッチを当てる手段は意図的に存在せず、
緊急の修正は設定編集ではなく新しいビルドです。この方法で行われた改正は
`ari/rqgm/kernel_rules.py` にコメントとしてその場に記録され、それぞれが
何を変えたかとピンを再計算したことを明記します — 憲法の履歴はレビュー可能な
diff になります。

ブロッキングマトリクスの要約（「制度をブロックし、研究はブロックしない」）:

- **ハードブロック集合**（RQGM の状態変更 — エポック遷移コミット、レジストリ
  書き込み、フロンティア再構築コミット、候補昇格 — を拒否権で止める。ノード
  実行は決して止めない）: 遷移テーブル違反、エンジン以外によるレジストリ
  書き込み、stale/retired プロンプト由来レコードのフロンティア到達、
  ガバナンスレコードのスキーマ違反、アクティブコンポーネントのハッシュ不一致、
  監査ログ改竄、クリーンルーム汚染、権限拡大、および事前 capability 拒否
  （retired プロンプトテキストへのアクセスを含む。MCP ゲートで標準の
  `{"error": ...}` エンベロープにより拒否されます）。
- **警告&フラグ集合**（研究の実行を決して中断しない）: ノード単位のレコード
  スキーマ / ハッシュ異常、事後アクセス検出、生成時のロール分離検出、
  コンテキストスコープ検出。警告検出は `kernel_report` エントリとして
  `rqgm_audit.jsonl` に追記され、ガバナンスパイプライン自身が生成した
  レコードについてはレポートの self-audit ブロックに計上されます — しかし
  そのレコードを後から不許容にするようなフラグは一切設定**されません**。
  証拠バンドルの許容性は独立に、レコード種別・著者ロール・種別ごとの
  整合性チェック（`ari/rqgm/governance/_evidence.py`）によって決まります。

**カーネルはどこから呼ばれるか。** カーネルは受動的です — 判定を返すだけで、
自身がガバナンス状態を変更することはありません。書き込みと帰結はすべて
アダプタ側が持ちます。カーネルを設置するアダプタは 6 つあり、いずれも
`ari_rqgm` でのみ構築されます:

| 執行ポイント | 実行されるチェック | ブロッキング判定の効果 |
|---|---|---|
| エポック境界トランザクション（`RegistryTransitionEngine.apply`） | `validate_transition` | トランザクションが `aborted` となり、解決済みのステータス変更（昇格・制裁・退役）は一切適用されない。前エポックのアクティブ集合がそのまま引き継がれ、ランは継続する |
| フロンティア再構築コミット（`FrontierRepairEngine.repair`） | `validate_selective_erasure` | エンジンが保守的に再修復し（フラグの付いたノードをすべて丸ごと削除）、再検証する。2 度目もブロッキングなら、ランは drain-only へ縮退する（`halted_expansion`: 保留中の作業は完了させ、以後の展開はしない） |
| MCP ツールディスパッチ（`CapabilityGatedMCPClient.call_tool`） | ツールポリシーが写す `(actor, action, resource)` の三つ組に対する `validate_capability` | 呼び出しはディスパッチされず、呼び出し側は標準の `{"error": ...}` エンベロープを受け取る。違反コードがエンジンの緊急トリガ集合に含まれる場合、加えて T16 緊急隔離フックが発火する — ここが、実行中のエージェントがエポック途中で憲法に触れられる唯一の場所 |
| ノード単位フック（`RQGMRuntime.run_per_node_kernel_check`） | ノードが生成したレコードに対する `validate_record_schema` と `validate_hashes`、および K/C/A 整合性チェック | レコード検出は警告のみで監査ログに記録される。ブロッキングな K/C/A 整合性検出はノードに `assurance_status: tampered`、`frontier_class: uncertified_frontier`、`_valid_for_frontier: false` を付ける — ノード自体は実行済みであり、フロンティアから除外されるだけ |
| ガバナンス自己監査（`GovernanceOrchestrator.audit_epoch`） | パイプライン自身が生成したレコードに対して再実行する `validate_record_schema` と `validate_role_separation` | ここでは何も拒否されない: 検出はレポートの self-audit ブロックに `kernel_violations_found`、`escalations`、`ban_recommendations` として計上される |
| resume 整合性パス（`RQGMRuntime.resume_integrity_check`） | 復元されたチェックポイントに対する `validate_audit_log_integrity` と `validate_selective_erasure` | ランは resume されるが governance-suspended carry-over に入る（resume 自体を拒否する代わりの縮退動作）。この状態が続く間、エポック監査はスキップされ、すべての境界は空の遷移を解決し、メタ進化もスキップされる |

各アダプタは自身のバグに対して fail-open です: フック内部の例外はログに
記録されて握り潰され、ランループへ送出されることはありません。唯一の意図的な
例外はフロンティア修復のバリデータで、自身の例外を失敗判定として扱い、
境界では fail-closed に縮退します。

**既知のギャップ — エポック不変性は検出のみです。** `CK-EPO-002`（エポック
途中の非緊急な active set 変更）は block 重大度を持ちますが、その唯一の
プロダクション呼び出し元 — ランループから駆動される
`RQGMRuntime.check_epoch_invariance` — は検出を `rqgm_audit.jsonl` の
`kernel_report` エントリとして記録し、警告するだけです。`should_block` を
参照することはなく、何も拒否しません: エポック不変性の検出を根拠に採用が
拒否されることも、レジストリ変更が拒否されることもありません。`CK-EPO-002`
はエンジンの緊急トリガ集合にも列挙されていますが、これを発行するバリデータ
はエポック不変性のものだけであり、その経路はエスカレーションフックを通り
ません — したがってこの列挙も発火することはありません。`CK-EPO-*` は
執行される障壁ではなく、そのエポックのガバナンス監査のための証拠として
読んでください。

遷移がブロックされた場合、前エポックのアクティブ集合が変更なしに引き継がれ、
ランは継続します（ランの中断は決して起こりません）。
`rqgm.kernel.enforcement: audit_only` は段階的ロールアウトと
アブレーションのために、すべてのコンテキストを warn-and-log へ格下げします。

## 互換性保証

- `rqgm.enabled: false`（または `ari.mode: simple_bfts`）は RQGM サブツリー
  全体を構造的に不活性にします — `ari.core.build_runtime` 内の遅延インポート
  分岐が唯一のゲートであり、機能ごとのフラグの散在ではありません。
- `simple_bfts` パスで触れられる唯一のコード: デフォルト付きの型付き設定
  フィールド 2 つ、env オーバーライド呼び出し 1 つ、そしてダックタイピングの
  `getattr(bfts, "rqgm", None)` プローブが数箇所（ランループ、ランタイム配線、
  論文ディスパッチへの受け渡し）— いずれもそこでは `None` を読みます。
- 古いチェックポイントには `rqgm_state.json` がありません; `resume` は不在を
  `simple_bfts` として扱います。古い ari-core 上にデプロイされた `rqgm:`
  ブロックは黙って無視されます（現行の挙動 — 最も安全な失敗方向）。

## 制限事項 (v1)

- プロファイル（`--profile`）は RQGM キーをマージしません。
- `--mode` CLI フラグはありません。GUI が選択するのは 2 つのモード意図だけで、
  対象は**新規**ランに限られます（[上記](#gui-からモードを選択する)）; 残りの
  `rqgm.*` ガバナンス / チューニングパラメータは設定ファイル専用です。
- ランのモードは開始後、どの面からも変更できません — resume は永続化された
  モードを取り、ラン中の遷移は一切ありません（エポック境界での
  ダウングレードは予約された設計で、未実装です）。
