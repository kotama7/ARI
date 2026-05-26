---
sources:
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-skill-paper
    role: implementation
last_verified: 2026-05-26
---

# 公開ライフサイクル (v0.7.0)

ARI v0.7.0 は EAR を「checkpoint をまるごと ear/ に放り込む」方式から、**digest 固定の公開チェーン** に進化させました。著者は小さな `ear/publish.yaml` を書くだけで、digest 計算と転送は ari-core が引き受けます。digest は論文に焼き付けられ (`\codedigest{...}`)、registry が無くなっても任意の場所で検証可能です。

```
generate_ear ──▶ {checkpoint}/ear/                 (著者のフルレポ)
                  + ear/publish.yaml               (allowlist + license/visibility)
        │
        ▼ ear_curate (transform-skill)
        ▼
{checkpoint}/ear_published/  +  manifest.lock      ({path,sha256,size} 正規化 JSON の sha256)
        │
        ▼ ear_publish (transform-skill, 任意)
        ▼
backend.publish ──▶ ari-registry / gh / zenodo / local-tarball
        │
        ▼ publish_record.json を書き出す
        │
        ▼ finalize_paper (paper-skill: inject_code_availability)
        ▼
full_paper.tex に \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
読者の手元: バンドルバイトを digest 検証、コード実行は無し
```

### `ari clone` resolvers

| Scheme | 解決先 | 備考 |
|--------|--------|------|
| `file://<path>` | ローカルファイル/ディレクトリ | オフライン・ミラー |
| `https://<url>` / `http://<url>` | tarball ダウンロード | 任意の HTTPS ホスト |
| `ari://<id>` | ari-registry クライアント | `registries.yaml` から endpoint/token を取得。解決順: `$ARI_REGISTRIES_FILE` → `{checkpoint}/.ari/registries.yaml` → `./.ari/registries.yaml`。`$HOME/.ari/` 配下のレガシー設定は v0.5.0 で廃止され、`DeprecationWarning` を経て v1.0 で削除予定。 |
| `gh:<user>/<repo>` | GitHub repo / release | API + tarball |
| `doi:<doi>` | Zenodo deposition | DOI → ファイル一覧 → bundle |

### `ari registry` (任意のセルフホスト)

`ari/registry/` の最小 FastAPI サーバ。SQLite トークンストア、`${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` のコンテンツアドレス保存。可視性は単調で `staged` → `unlisted` / `public` のみ (降格は拒否)。デプロイは uvicorn (laptop) / docker-compose (production) / Apptainer (HPC)。詳細は [docs/reference/registry.md](../reference/registry.md)。

### 再現性サンドボックス補強

- **`_run_env.json`** — `ari/agent/run_env.py` が work_dir ごとに hostname / SLURM job/partition/nodelist / CPU model/threads/MHz/arch / mem_total / コンパイラバージョンを *実行プロセス内で* 書き出し、SLURM ジョブ (エージェントとは別ノードで動く) でも正確なハードウェア情報を残します。`node_report` ビルダは reports にこのデータを付与し、論文・再現性ステージは「sx40 partition、hostname X、Intel Xeon …で実行」のような事実を blank artefact から推測することなく取り戻せます。
- **Git shim** (`ari/agent/shims/git.sh`) — 再現性サンドボックスに `PATH=<sandbox>/.shims:<orig_path>` で組み込まれます。論文の `code_availability_ref` に一致する URL の `git clone` だけをインターセプトし、それ以外は本物の git に素通し。すべての clone 試行を `<sandbox>/repro_clone_log.jsonl` に記録します。`ARI_REPRO_CLONE_POLICY=passthrough|deny|warn` で動作切替。

---

## 関連

[アーキテクチャ](architecture.md) · [レジストリ](../reference/registry.md) · [ルーブリックスキーマ](../reference/rubric_schema.md) · [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)
