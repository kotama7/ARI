---
sources:
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/clone/resolvers/ari.py
    role: implementation
  - path: ari-core/ari/publish/backends/ari_registry.py
    role: implementation
  - path: scripts/registry
    role: doc
  - path: scripts/setup/install_deps.sh
    role: implementation
last_verified: 2026-08-16
---

# ari-registry — v0.7.0+

キュレート済み EAR バンドル用の最小 HTTP レジストリ。`ari ear publish` のデフォルトバックエンド、および `ari clone` の `ari://` resolver として動作します。

## 動かす必要があるか

`ari registry` は他者にバンドルを配布するためにホストしたい場合のみ立ち上げます。自己アーカイブ目的なら、サーバ不要のデフォルト `local-tarball` バックエンドで十分です。学術的恒久性なら Zenodo が推奨経路です。

## クイックスタート

> **メモ:** v0.5.0 でグローバル `$HOME/.ari/` ディレクトリは廃止されました。レジストリ関連のパスは明示的な env var（`ARI_REGISTRY_DATA`、`ARI_REGISTRIES_FILE`）から与えてください。手順は [移行ガイド](../guides/migration.md)。レガシーフォールバックは `DeprecationWarning` を出したうえで v1.0 で削除されます。手順 2 で `ARI_REGISTRY_DATA` を設定するのは任意の作法ではありません: `start_local.sh` と `start_singularity.sh` はいずれも既定値を `$HOME/.ari/registry-data` のままにしているためです。

```bash
# 1. サーバ依存は requirements.txt / lockfile に入っているので、素の
#    ./setup.sh で fastapi + uvicorn + python-multipart がインストール済みになる。
#    --with-registry は受け付けるが情報表示のみ。
./setup.sh --with-registry        # または: pip install fastapi uvicorn[standard] python-multipart

# 2. データディレクトリを指定
export ARI_REGISTRY_DATA="$PWD/.ari_registry"

# 3. 起動（uvicorn が 127.0.0.1:8290 で待ち受ける。`ari registry serve` 単体の
#    既定は --host 0.0.0.0 で、スクリプトがそれを上書きしている）
./scripts/registry/start_local.sh

# 4. token を発行（平文は 1 度だけ表示）
ari registry token issue alice

# 5. クライアント設定
export ARI_REGISTRIES_FILE="$ARI_CHECKPOINT_DIR/.ari/registries.yaml"
mkdir -p "$(dirname "$ARI_REGISTRIES_FILE")"
cat > "$ARI_REGISTRIES_FILE" <<EOF
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: \$ARI_REGISTRY_TOKEN
EOF
export ARI_REGISTRY_TOKEN=ari_<step-4-からコピー>
```

## 設定ファイルの解決（v0.7+）

`ari ear publish --backend ari-registry` と `ari clone ari://` は、どちらも同じ 4 段のチェーンで `registries.yaml` を探します。

1. `$ARI_REGISTRIES_FILE` — 明示的な env override。
2. `{checkpoint_dir}/.ari/registries.yaml` — 実行ごとに registry 設定を checkpoint に固定できるようにする意図の段。
3. `$(pwd)/.ari/registries.yaml` — プロジェクトディレクトリの中から実行するときに便利。
4. `$HOME/.ari/registries.yaml` — **非推奨**。ファイルが存在する場合にのみ、しかも `DeprecationWarning` を出したうえで参照されます。v1.0 で削除。

> **第 2 段は現状発火しません。** どちらの lookup も `checkpoint_dir` を省略可能な引数として取りますが、呼び出し側はどちらもそれを渡していません — publish バックエンドの `_select_registry()` も `ari://` resolver の `resolve()` も、引数なしで呼んでいます。したがって checkpoint の中に置いた `.ari/registries.yaml` は、`$ARI_REGISTRIES_FILE` でそのファイルを指すか、そのディレクトリから実行しない限り見えません。

チェーン上のどのファイルも存在しない場合、どちらの経路も `$ARI_REGISTRY_URL`（と `$ARI_REGISTRY_TOKEN`）から組み立てた単一の合成 registry にフォールバックします。どちらも無ければ、コマンドは `no ari-registry configured` で失敗します。ファイルは*存在する*が registry が 1 件も書かれていない場合、2 つの実装は挙動が分かれます: `ari://` resolver はチェーンを歩き続けて `$ARI_REGISTRY_URL` フォールバックまで到達しますが、publish バックエンドは最初に読めたファイルの空リストをそのまま返すため、`$ARI_REGISTRY_URL` が設定されていても失敗します。publish バックエンドはさらに `$ARI_REGISTRY_NAME` を受け取り、名前でエントリを選べます。

ファイル中の token は、リテラルか `$VAR` の形式で書いてください。resolver の docstring に載っている `${VAR}` の形式は **動作しません**: どちらの `_expand_token` 実装でも `$` 始まりの分岐が先に判定されるため、`${ARI_REGISTRY_TOKEN}` は文字どおり `{ARI_REGISTRY_TOKEN}` という名前の環境変数として引かれ、黙って空文字列に展開されます。

サーバ側の状態（`ari registry serve`）は `$ARI_REGISTRY_DATA/` に置かれます。レガシーの `$HOME/.ari/registry-data` フォールバックも同じ v1.0 非推奨ポリシーの対象です — 警告を避けるには env var を明示的に設定してください。

## エンドポイント

| Method | Path                                    | 認証   | 備考 |
|--------|-----------------------------------------|--------|------|
| GET    | `/healthz`                              | -      | liveness probe。`{"ok": true}` を返す |
| GET    | `/version`                              | -      | `{"version": "0.7.0", "service": "ari-registry"}` |
| POST   | `/artifact`                             | bearer | multipart アップロード: `bundle` ファイル + `manifest` / `metadata` / `visibility` フォームフィールド。同一バイト列の再アップロードは冪等で `duplicate: true` を返し、所有者が異なる場合は拒否 |
| GET    | `/artifact/<id>`                        | maybe  | public/unlisted: 匿名可、staged: 所有者の bearer token、private-token: 有効な bearer token なら何でも可 |
| HEAD   | `/artifact/<id>`                        | -      | sha256 + visibility + length ヘッダのみ（body なし）。**どの可視性でも認証チェックが無い** |
| GET    | `/artifact/<id>/manifest.lock`          | -      | manifest 単体取得 — **こちらも認証チェックが無い**ため、staged なバンドルのファイル一覧とファイルごとの digest が id を知っている者に公開される |
| POST   | `/artifact/<id>/promote?target=...`     | bearer | `target` はクエリパラメータ（既定 `public`）。所有者のみ |
| DELETE | `/artifact/<id>`                        | bearer | 所有者のみ |

未知の id は 404、bearer token の欠落・不正は 401、有効だが所有者でない token は 403、不正な可視性 target は 400 を返します。

## 可視性モデル（FR-RG6）

- `staged`: 所有者の token のみが読み取り可能。**`ari ear publish` は常に staged でアップロード**しますが、HTTP エンドポイント自体は 4 値のいずれも受け付けます。
- `unlisted`: id を知っていれば誰でも読める（列挙はされない）。そもそも何も列挙されません — サーバは一覧エンドポイントを一切公開していません。
- `public`: 誰でも読める。
- `private-token`: 取得時に bearer token が必要 — 所有者のものに限らず、有効な token なら何でもよい。

可視性は **昇順のみ**。順位は `staged(0) < unlisted(1) = private-token(1) < public(2)` なので、`unlisted` と `private-token` は双方向に行き来でき、厳密に低い target（例: `public → unlisted`、任意の状態 `→ staged`）だけが拒否されます。

## ストレージ

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite、bearer token のハッシュ保管
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"id":..., "visibility":..., "owner":...,
                                  #  "created_at":..., "sha256":..., "length":...}
```

artifact id はコンテンツアドレス: `sha256(bundle.tar.gz)[:16]`（16 hex / 64 bit）。このページは以前「5e9 個の artifact で誕生日衝突確率は約 1%」と書いていましたが、5e9 は **50%** の地点です。64 bit 空間では `p ≈ 1 − exp(−n²/2N)` となり、約 1% になるのは **6e8** 個あたり、5e9 個では 49% です。より広いファンアウトが必要なら将来リリースで id 長を設定可能化予定 — 現状 `[:16]` の切り詰めは `FilesystemStorage.derive_id` にハードコードされています。

## token ライフサイクル

```bash
ari registry token issue <user>     # 平文は 1 度のみ表示。安全に保管
ari registry token revoke <id>      # 即時無効化
ari registry token list             # 誰がアクセス可能か一覧
```

## デプロイモード

- `scripts/registry/start_local.sh` — uvicorn + sqlite、シングルプロセス。Laptop / dev。
  `ARI_REGISTRY_HOST`（既定 `127.0.0.1`）、`ARI_REGISTRY_PORT`（`8290`）、
  `ARI_REGISTRY_DATA`（既定は非推奨の `$HOME/.ari/registry-data`）を参照し、
  データディレクトリの隣に pidfile とログを書き、記録された pid が生きていれば
  何もせず終了します。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
  `proxy` サービスが `./nginx.conf` を bind-mount しますが、このファイルは
  リポジトリに **含まれていません** — `docker compose up` の前に自分で用意して
  ください。
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF。HPC。
  初回実行時に `$ARI_REGISTRY_SIF`（既定 `$HOME/.ari/ari-registry.sif`）を
  ビルドし、データディレクトリを `/data` に bind して
  `0.0.0.0:$ARI_REGISTRY_PORT` で待ち受けます。

## 恒久性

レジストリが停止しても、**バンドルの検証は継続可能** です。SHA-256 digest が論文の `\codedigest{...}` マクロに焼き付けられているからです。バンドルを別ホスト（S3、Zenodo、gh release など）に移しても、`ari clone file://...` で manifest と照合すれば正しく検証できます。

## 関連

[出版ライフサイクル](../concepts/publication-lifecycle.md) · [設定](configuration.md) · [PaperBench API](api_paperbench.md)
