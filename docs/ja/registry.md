# ari-registry — v0.7.0+

キュレート済み EAR バンドル用の最小 HTTP レジストリ。`ari ear publish` のデフォルトバックエンド、および `ari clone` の `ari://` resolver として動作します。

## 動かす必要があるか

`ari registry` は他者にバンドルを配布するためにホストしたい場合のみ立ち上げます。自己アーカイブ目的なら、サーバ不要のデフォルト `local-tarball` バックエンドで十分です。学術的恒久性なら Zenodo が推奨経路です。

## クイックスタート

> **メモ:** v0.5.0 でグローバル `$HOME/.ari/` ディレクトリは廃止されました。レジストリ関連のパスは `ARI_REGISTRY_DATA` `ARI_REGISTRIES_FILE` env var、もしくはアクティブなチェックポイント（`$ARI_CHECKPOINT_DIR/.ari/registries.yaml`）配下にスコープされます。詳細は `docs/refactor_audit.md` と `docs/howto/migration.md`。レガシーフォールバックは v1.0 で削除されます。

```bash
# 1. サーバ依存をインストール（デフォルト install には含めず slim を保つ）
./setup.sh --with-registry        # または: pip install fastapi uvicorn[standard] python-multipart

# 2. データディレクトリを指定して起動（デフォルトポート 8290）
export ARI_REGISTRY_DATA="$PWD/.ari_registry"
./scripts/registry/start_local.sh

# 3. token を発行（平文は 1 度だけ表示）
ari registry token issue alice

# 4. クライアント設定
export ARI_REGISTRIES_FILE="$ARI_CHECKPOINT_DIR/.ari/registries.yaml"
mkdir -p "$(dirname "$ARI_REGISTRIES_FILE")"
cat > "$ARI_REGISTRIES_FILE" <<EOF
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: \$ARI_REGISTRY_TOKEN
EOF
export ARI_REGISTRY_TOKEN=ari_<step-3-からコピー>
```

## エンドポイント

| Method | Path                                    | 認証   | 備考 |
|--------|-----------------------------------------|--------|------|
| GET    | `/healthz`                              | -      | liveness probe |
| GET    | `/version`                              | -      | サーババージョン |
| POST   | `/artifact`                             | bearer | tarball + manifest をアップロード |
| GET    | `/artifact/<id>`                        | maybe  | public/unlisted: 匿名可、staged/private-token: bearer 必須 |
| HEAD   | `/artifact/<id>`                        | -      | sha256 + visibility ヘッダのみ（body なし） |
| GET    | `/artifact/<id>/manifest.lock`          | maybe  | manifest 単体取得 |
| POST   | `/artifact/<id>/promote`                | bearer | `staged` → `unlisted`/`public`（所有者のみ） |
| DELETE | `/artifact/<id>`                        | bearer | 所有者のみ |

## 可視性モデル（FR-RG6）

- `staged`: 所有者の token のみが読み取り可能。**全アップロードは staged 開始**。
- `unlisted`: id を知っていれば誰でも読める（列挙はされない）。
- `public`: 誰でも読める。
- `private-token`: 取得時に別の bearer token が必要。

可視性は **昇順のみ**（staged → unlisted/public）。降格は拒否。

## ストレージ

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite、bearer token のハッシュ保管
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"visibility":..., "owner":..., "sha256":..., "length":...}
```

artifact id はコンテンツアドレス: `sha256(bundle.tar.gz)[:16]`（16 hex / 64 bit）。5e9 個の artifact で誕生日衝突確率は約 1%。将来リリースで id 長を設定可能化予定。

## token ライフサイクル

```bash
ari registry token issue <user>     # 平文は 1 度のみ表示。安全に保管
ari registry token revoke <id>      # 即時無効化
ari registry token list             # 誰がアクセス可能か一覧
```

## デプロイモード

- `scripts/registry/start_local.sh` — uvicorn + sqlite、シングルプロセス。Laptop / dev。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF。HPC。

## 恒久性

レジストリが停止しても、**バンドルの検証は継続可能** です。SHA-256 digest が論文の `\codedigest{...}` マクロに焼き付けられているからです。バンドルを別ホスト（S3、Zenodo、gh release など）に移しても、`ari clone file://...` で manifest と照合すれば正しく検証できます。
