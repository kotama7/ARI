---
sources:
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-skill-paper
    role: implementation
  - path: ari-skill-transform/src/curate.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-core/ari/latex_claims.py
    role: implementation
  - path: ari-core/ari/clone
    role: implementation
  - path: ari-core/ari/publish
    role: implementation
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/cli/commands.py
    role: implementation
  - path: ari-core/ari/agent/run_env.py
    role: implementation
  - path: ari-core/ari/agent/shims/git.sh
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

# 公開ライフサイクル (v0.7.0)

ARI v0.7.0 は EAR を「checkpoint をまるごと ear/ に放り込む」方式から、**digest 固定の公開チェーン** に進化させました。著者は小さな `ear/publish.yaml` の allowlist を書くだけで、transform-skill の `curate.py` が組み込みの deny リスト (`BUILTIN_DENY`: `.env*`、`secrets/**`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`) を強制し、決定的な bundle digest を計算します。digest は論文に焼き付けられ (`\codedigest{...}`)、registry が無くなっても任意の場所で検証可能です。

```
generate_ear ──▶ {checkpoint}/ear/                 (著者のフルレポ)
                  + ear/publish.yaml               (allowlist + license/visibility)
        │
        ▼ ear_curate (transform-skill)
        ▼
{checkpoint}/ear_published/  +  manifest.lock      (正規化 v2 JSON: {path,sha256,size,role} の sha256)
        │
        ▼ ear_publish (transform-skill、既定で有効)
        ▼
backend.publish ──▶ local-tarball (workflow の既定) / ari-registry / gh / zenodo
                     常に visibility=staged
        │
        ▼ publish_record.json を書き出す
        │
        │   (並行して、write_paper が full_paper.tex を出力すると
        │    既定 ON の Story2Proposal claim-evidence ループが論文本文に対し走る:)
        │
        │   write_paper ──▶ full_paper.tex
        │        │
        │        ▼ link_paper_claims (draft)        ──▶ paper_claim_links.json
        │        ▼ claim_evidence_hard_gate (draft, 非ブロッキング)
        │        │                                   ──▶ evaluation/claim_evidence_hard_gate_draft.json
        │        ▼ review_paper / evidence_grounded_semantic_review (非ブロッキング)
        │        ▼ merge_reviews
        │        ▼ paper_refine (anchor 保持 — % CLAIM anchor を維持)
        │        ▼ render_paper (refine 後の .tex を再コンパイル ──▶ full_paper.pdf)
        │        ▼ link_paper_claims (final)          ──▶ paper_claim_links_final.json
        │        ▼ claim_evidence_hard_gate (FINAL)   ──▶ evaluation/claim_evidence_hard_gate_final.json
        │        │   (finalize をブロック: 客観的な虚偽は常に、
        │        │    設定済み block_on は strict モードで)
        ▼        ▼
        └────────┴──▶ finalize_paper (paper-skill: inject_code_availability)
                       ear_publish と FINAL hard gate の両方に DEPENDS
        ▼
full_paper.tex に \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ link_paper_claims_locked                  ──▶ paper_claim_links_locked.json
        ▼ claim_evidence_hard_gate_locked (final)   ──▶ evaluation/claim_evidence_hard_gate_locked.json
        ▼ evidence_grounded_semantic_review_locked (advisory)
        ▼ render_final_paper (injection 後の .tex をコンパイル ──▶ full_paper.pdf)
        ▼ lock_paper_build (paper-skill: finalize_paper_build)
        │                                            ──▶ paper_build.json (PaperBuildV1)
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
読者の手元: バンドルバイトを digest 検証、コード実行は無し
```

### Claim-evidence ゲート (Story2Proposal ループ)

論文ビルドのたびに、既存の論文ステージに加えて、決定的な
claim-evidence **hard gate**、非ブロッキングの
**evidence-grounded semantic review**、そして
**anchor 保持の refine/render ループ** が走るようになりました。本ループは
論文の `% CLAIM` anchor を記録済み結果に紐付け (`link_paper_claims`)、
実験データと突き合わせて検証し (`claim_evidence_hard_gate`。draft で 1 回、
refine 後の論文で再度、さらに `lock_paper_build` が lock する injection 後の
TeX そのものに対して 3 回目を実行)、hard gate と semantic review の双方をマージ済み
レビューにスレッドし、claim anchor を保持したまま suggested revision を適用し
(`paper_refine`)、refine 後の `.tex` を再コンパイルします (`render_paper`)。
動作は `ari-core/config/workflow.yaml` の `claim_gate_policy` ブロックで制御され、
既定は`warn`です。**FINAL** warn gateは客観的integrity findingだけをblockし、
他はreport-onlyです。`strict`では数値不一致、未解決operand、evidence欠落などの
設定済みfindingもblockします。draftと`off`はblockしません。

ループの誠実さは 4 つの堅牢化が end-to-end で支えます:

- **block は客観的虚偽に限定。** gate の always-block 層には決定論的に
  検査できる所見だけが入ります（run 自身のデータと矛盾する数値、
  不変条件違反、run 内のどこにも証拠が無い宣言済み claim）。主観的
  所見 — LLM semantic review の overclaim / interpretation 警告 — は
  設計上 advisory に留めます。LLM の判定は再現可能でないため、論文に
  対する拒否権を持たせてはならないからです。主観的所見への対処は上記
  review→refine ループで行い、post-refine review の生の解消数デルタで
  「強制でなく計測」します。

- **レビューフィードバックは確実に届く。** `merge_reviews` は semantic review の
  すべての warning を advisory な revision エントリとして `paper_refine` に転送します
  (対応する suggested revision を持たない warning は refiner に届かず、件数が
  減りようがなかったため)。報告される `resolved_overclaim_count` は前回−今回の
  生の差分です — 負値は refine 後に件数が*増えた*ことを意味し、0 に clamp せず
  回帰としてそのまま表面化します。
- **数値検証は科学的記数法を理解する。** numeric-mention スキャナは
  `ari-core/ari/latex_claims.py` の単一実装で、`ari-skill-paper/src/claim_links.py`
  は `ari.public.latex_claims` 経由、ari-core 側は `ari/pipeline/claim_gate/latex.py` の
  互換 re-export 経由で同じものを使うため、両者が乖離することはありません。
  仮数 × 10^指数形 (`4.44 \times 10^{-16}`、`x`/`\times`/`\cdot` 対応) と
  付随する e 記法 (文末も含む) をパースし、数字を含むトークンを保持し、単位の
  特定では `\( \)` を数式デリミタとして扱います — こうした値での偽の
  `numeric_mismatch` 検出を排除します。巨大な指数はスキップされ、gate を
  落とすことはありません。
- **writer 宣言はパース時に正規化される。** 指示だけでは安定しなかったため、
  典型的な癖はパーサ側で吸収します: formula の同義語 (`value`/`raw`/`abs`…) は
  レジストリ名に正規化、bare な `k=v` トークン前の `operands=` ラベル接頭辞は
  除去、全 anchor が 1 つの id を共有する場合 (例: 全行が `% CLAIM:Cw:NCw`) は
  行ごとに曖昧性を解消し、各宣言を独立に検証します。
- **metric contract は一度だけ mint される。** idea 所有の Research Contract を
  解決した — または human review 済みの `propose_metric_contract` 提案を admit
  した — 最初の `make_metric_spec` 呼び出しが projection を
  `{checkpoint}/metric_contract.json` として永続化し、以後の呼び出しはその
  ファイルを読み戻して返します (レスポンスに `contract_frozen: true` が付く)。
  `projection_digest` が異なる再 mint は拒否されます。LLM の命名は参照的に
  安定せず、run 途中の再生成はエビデンス語彙を変え、旧名で emit 済みの
  sibling evidence を exact-match gate から隠してしまいます (実 run で観測)。
  per-node の spec フィールド (scoring guide 等) は従来どおり呼び出しごとに
  計算されます。idea 所有の contract も reviewer も無い場合は何も freeze されず、
  レスポンスは `contract_frozen: false` / `admission_status:
  human-review-required` となり、パーサ出力は evidence 止まりで contract には
  昇格しません。

成果物: `paper_claim_links.json` (draft) /
`paper_claim_links_final.json` / `paper_claim_links_locked.json`、および
`evaluation/claim_evidence_hard_gate_{draft,final,locked}.json`。

トラストモデル: **トラストアンカーは registry ではなく論文そのもの**です。
`ari clone` は再計算した digest が `--expect-sha256` (または `manifest.lock` の
宣言) と一致しないバンドルを hard-fail させます — ただしこれは展開経路に限られます。
`--no-extract` ではバンドルは開かれずにコピーされるだけなので、`--expect-sha256` は
受理されるものの一度も検査されません。registry が消えても、別の場所
(S3・Zenodo・gh release・ローカルミラー) に pin された同じバンドルなら検証できます。
これは **バンドル完全性** (digest 一致) です。FINAL hard gate はさらに
**クレーム完全性** を加えます — 論文が報告する数値を記録済み結果から再導出し、
許容誤差を外れたものをフラグします。

### `ari clone` resolvers

| Scheme | 解決先 | 備考 |
|--------|--------|------|
| `file://<path>` | ローカルファイル/ディレクトリ | オフライン・ミラー |
| `https://<url>` / `http://<url>` | tarball ダウンロード | 任意の HTTPS ホスト |
| `ari://<id>` | ari-registry クライアント | `registries.yaml` から endpoint/token を取得。解決順: `$ARI_REGISTRIES_FILE` → `{checkpoint}/.ari/registries.yaml` → `./.ari/registries.yaml` → `$HOME/.ari/registries.yaml` (v0.5.0 で非推奨。最後に参照されるものとして残っており、`DeprecationWarning` を出す。v1.0 で削除)。どこにもファイルが無い場合は `$ARI_REGISTRY_URL` / `$ARI_REGISTRY_TOKEN` から `default` という単一の registry が合成されます。 |
| `gh:<user>/<repo>` | GitHub repo / release | API + tarball |
| `doi:<doi>` | Zenodo deposition | DOI → ファイル一覧 → bundle |

### `ari registry` (任意のセルフホスト)

`ari/registry/` の最小 FastAPI サーバ。SQLite トークンストア、`${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` のコンテンツアドレス保存。可視性は単調で `staged` → `unlisted` / `public` のみ (降格は拒否)。デプロイは uvicorn (laptop) / docker-compose (production) / Apptainer (HPC)。詳細は [docs/reference/registry.md](../reference/registry.md)。

### 再現性サンドボックス補強

- **`_run_env.json`** — `ari/agent/run_env.py` が work_dir ごとに hostname / SLURM job/partition/nodelist / CPU model/threads/MHz/arch / mem_total / コンパイラバージョン、加えて `module avail` が列挙しないベンダ製 `toolchain_dirs` とページ/NUMA の `memory_system` 状態を *実行プロセス内で* 書き出し、SLURM ジョブ (エージェントとは別ノードで動く) でも正確なハードウェア情報を残します。呼び出しのたびにファイルは上書きされます: 最後のツール呼び出しの環境が残ります。ここの `compilers` は module ロード前のビューです — 計測が実際に何の下で走ったか (ロード済み module、解決された PATH) の記録は `_exec_env.json` で、実行シェル自身が書き出し、`read_run_env` が `execution` の下にマージします。`node_report` ビルダは reports にこのデータを付与し、論文・再現性ステージは「実行 partition、hostname X、CPU model …で実行」のような事実を blank artefact から推測することなく取り戻せます。
- **Git shim** (`ari/agent/shims/git.sh`) — 再現性サンドボックスに `PATH=<sandbox>/.shims:<orig_path>` で組み込まれます。論文の `code_availability_ref` に一致する URL の `git clone` だけをインターセプトし、それ以外は本物の git に素通し。すべての clone 試行を `<sandbox>/repro_clone_log.jsonl` に記録します。`ARI_REPRO_CLONE_POLICY=passthrough|deny|warn` で動作切替。

---

## 関連

[アーキテクチャ](architecture.md) · [レジストリ](../reference/registry.md) · [ルーブリックスキーマ](../reference/rubric_schema.md) · [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)
