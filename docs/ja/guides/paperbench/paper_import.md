---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
last_verified: 2026-05-25
---

# 外部論文の取り込み

論文レジストリ (`~/.ari/paper_registry/`、`ARI_PAPER_REGISTRY_DIR`
で上書き可) は PaperBench ウィザードで監査できる外部論文を保持する。
本ページは 4 種の取り込み経路とライセンス処理を説明する。

## ストレージレイアウト

```
{ARI_PAPER_REGISTRY_DIR or ~/.ari/paper_registry}/
├── manifest.jsonl            # 1 行 1 論文 (JSON)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # ソース PDF (推奨)
        ├── ad.pdf            # アーティファクト記述書 (任意)
        └── ae.pdf            # アーティファクト評価書 (任意)
```

ルートは `ARI_PAPER_REGISTRY_DIR` で変更可能。

## 取り込み経路

### arXiv ID

最もよく使う経路。 ウィザードで `source_type=arxiv`、
`source=2404.14193` を指定する。**「↓ メタデータ取得」ボタン** を
押すと `/api/paperbench/arxiv/<id>` 経由で arXiv Atom API を叩き、
title / authors / year / license を自動入力する。

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
appendix も `ad_pdf_path` / `ae_pdf_path` で同様。

### Local path

`source_type=local`。 既にディスク上にある PDF を ARI が再ホストせず
そのまま参照するパス。 既存パスを指すだけの登録。

## ライセンス分類

ライセンス文字列は正規化 (小文字化、空白除去) され、 4 軸の評価に
分類される:

| 状態 | 例 |
|---|---|
| **utilizable** (寛容 AND 再配布可) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, CC BY-NC, arXiv 非独占 |
| 寛容のみ (NOT redistributable) | (現状なし — 将来のプレースホルダ) |
| **NOT usable** | プロプライエタリ、 IEEE Author、 ACM Author、 "All rights reserved"、 不明文字列 |

分類はヒューリスティック (**助言的**)。 最終的な法的レビューは
ユーザーの責任。 GUI は utilizable に緑 ✅、 NOT usable に黄 ⚠ の
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

`paper_id` 自体は `[A-Za-z0-9._-]{1,64}` にサニタイズされる
(その他の文字は `-` に置換)。

## 削除

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

idempotent (未知 id は `{deleted: false, reason: "not found"}` を返す)。

## メタデータパッチ

レジストリ slot を保ったまま誤字訂正したい場合:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` は immutable。

## 関連

- [PaperBench GUI ガイド](paperbench_gui.md)
- [API リファレンス](../../reference/api_paperbench.md)
