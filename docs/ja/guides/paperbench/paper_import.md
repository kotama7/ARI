---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_tools.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperImportDialog.tsx
    role: implementation
last_verified: 2026-08-16
---

# 外部論文の取り込み

論文レジストリ (`{ARI_PAPER_REGISTRY_DIR or {workspace_root}/paper_registry}/`)
は PaperBench ウィザードで監査できる外部論文を保持する。
本ページは 4 種の取り込み経路とライセンス処理を説明する。

## ストレージレイアウト

```
{ARI_PAPER_REGISTRY_DIR or {workspace_root}/paper_registry}/
├── manifest.jsonl            # 1 行 1 論文 (JSON)
├── jobs/
│   └── <job_id>.json         # 永続化された run レコード (mode 0600)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # run 開始前に必須
        ├── ad.pdf            # アーティファクト記述書 (任意)
        └── ae.pdf            # アーティファクト評価書 (任意)
```

ルートは `ARI_PAPER_REGISTRY_DIR` が設定されていればそれ、無ければ
`PathManager.from_env().paper_registry_root` —
`{workspace_root}/paper_registry` で、workspace root は
`ARI_CHECKPOINT_DIR` から推定し、無ければカレントディレクトリに落ちる。
`~/.ari/` の下では**ない**: v0.5+ の ARI はユーザ単位のグローバルデータ
ディレクトリを持たない。

`paper.pdf` は import エンドポイントの説明上は任意だが、run のためには
ハードな前提条件である: ウィザードの worker は最初のステージに入る前に
`"paper.pdf missing under …; cannot launch PaperBench"` で中断する。

## 取り込み経路

### arXiv ID

最もよく使う経路。 ウィザードで `source_type=arxiv`、
`source=2404.14193` を指定する。メタデータの自動取得は実装済み —
**「↓ メタデータ取得」ボタン** (および `GET /api/paperbench/arxiv/<id>`)
が arXiv Atom API を叩き、`title`、`authors`、`year`、
`license: "arXiv non-exclusive"`、`summary`、`pdf_url`、`abs_url` を返す。
新形式 (`2404.14193`、`2404.14193v2` — バージョン接尾辞は除去される) と
旧形式 (`cs.LG/0102030`) の両方を受け付け、`arxiv:` 接頭辞も任意で付けられる。

一方 **PDF は取得されない**: レスポンスに `pdf_url` は返るが誰も
ダウンロードしない。下記の upload 経路で `paper.pdf` を自分で添付しないと、
run worker が中断する。

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"],
    "year": 2024,
    "venue": "SC24",
    "artifact_url": "https://github.com/spcl/llamp"
  }'
```

### DOI

arXiv と同じフォームで `source_type=doi`、
`source=10.1109/<conf>.YYYY.NNNNN` 形式で DOI を指定
(例: ACM DL や IEEE Xplore 上の SC / OSDI / USENIX paper の DOI)。
arXiv に無い IEEE / ACM 論文に使う。

### Upload (ローカル PDF)

`source_type=upload`。 `/api/upload` で PDF を tmp に置き、その path
を `pdf_path` で渡す:

```bash
TMP=$(curl -F 'file=@./mypaper.pdf' http://localhost:8765/api/upload | jq -r .path)
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d "{
    \"source_type\": \"upload\",
    \"source\": \"local-upload-$(date +%s)\",
    \"title\": \"My SC24 camera-ready\",
    \"license\": \"IEEE Author proprietary\",
    \"pdf_path\": \"$TMP\"
  }"
```

PDF は `papers/<paper_id>/paper.pdf` にコピーされる。AD / AE
appendix も `ad_pdf_path` / `ae_pdf_path` で同様 — ただし非対称がある:
`paper.pdf` のコピー失敗は `{"error": "could not copy paper PDF: …"}` で
import 自体を中断させるが、AD/AE のコピー失敗はログに残るだけで、
それらが無いまま import は成功する。

### Local path

`source_type=local`。 既にディスク上にある PDF を ARI が再ホストせず
そのまま参照するパス。 ただし `source` はそのまま文字列として保存され、
パスとして解釈されることは決してない — レジストリにファイルをコピーするのは
`pdf_path` だけである。したがって `pdf_path` の無い `local` エントリは
`paper.pdf` を持たず run できない。run を開始したいならディスク上の PDF を
指す `pdf_path` を渡すこと。

## ライセンス分類

ライセンス文字列は正規化 (小文字化、空白除去) され、
`{permissive, modifiable, redistributable, usable, note}` の評価に
分類される:

| 状態 | 例 |
|---|---|
| **usable** (寛容 AND 再配布可 AND 非商用でない) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, arXiv 非独占 |
| 寛容のみ (NOT redistributable) | CC BY-NC — *"non-commercial ⚠ NOT usable — CC BY-NC restricts commercial reuse"* とフラグされる。ARI は下流で商用利用されうるため |
| **NOT usable** | プロプライエタリ、 IEEE Author、 ACM Author、 "All rights reserved"、 不明文字列、ライセンスが空 / 未指定 |

`modifiable` は `permissive` より狭い: `arXiv non-exclusive` は再配布可だが
改変可ではない。

分類はヒューリスティック (**助言的**)。 最終的な法的レビューは
ユーザーの責任。 GUI は usable に緑 ✅、 そうでないものに ⚠ の
バッジを表示する — どちらでも登録は通る。

論文のライセンス評価を確認するには:

```bash
curl http://localhost:8765/api/paperbench/papers/<paper_id>/license
```

## 重複検出

同じ `paper_id` (デフォルト: sanitize された `source`) での import は
`overwrite=true` 指定がなければブロックされる:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv", "source": "2404.14193",
    "title": "LLAMP v2", "license": "CC BY 4.0",
    "overwrite": true
  }'
```

衝突はステータス行ではなく body で報告される: レスポンスは HTTP 200 で
`{"error": "paper_id already registered: <id>", "paper_id": …,
"existing": <現在の manifest エントリ>}` を返す。`overwrite=true` を付けた
場合、manifest エントリはマージではなく**丸ごと置換**される — 省略した
フィールドは失われる。論文ディレクトリは再利用されるので、新しい
`pdf_path` で上書きしない限り既存の `paper.pdf` は残る。

`paper_id` 自体は `[A-Za-z0-9._-]` にサニタイズされる
(その他の文字は `-` に置換)。結果は 64 文字に切り詰められ、空の id は
ランダムな UUID4 の先頭 12 桁 (hex) になる。

## 削除

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

idempotent (未知 id は `{deleted: false, reason: "not found"}` を返す)。
モジュールの docstring は今も
`DELETE /api/paperbench/papers/<paper_id>` を謳っているが、実際に
ルーティングされているのは上記の `POST …/delete` だけである。

削除は manifest エントリを消し、`papers/<paper_id>/` を `rmtree` する —
その配下にある `runs/<job_id>/` の sandbox も道連れになる。
`{registry_root}/jobs/` に永続化された run レコードには触れない。

## メタデータパッチ

レジストリ slot を保ったまま誤字訂正したい場合:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` は immutable — マージ後に URL の値で再スタンプされるため、
body に `paper_id` を入れても無視される。`license` をパッチすると
`_classify_license` が再実行され、小文字化された文字列と新しい
`license_assessment` が保存される。

## 関連

- [PaperBench GUI ガイド](paperbench_gui.md)
- [API リファレンス](../../reference/api_paperbench.md)
