---
sources:
  - path: ari-core/ari/registry
    role: implementation
  - path: scripts/registry
    role: doc
last_verified: 2026-05-26
---

# ari-registry — v0.7.0+

托管策展过的 EAR bundle 的最小 HTTP registry。是 `ari ear publish` 的默认后端，也是 `ari clone` 中 `ari://` 解析器的目标。

## 何时需要它

只有当你想为他人托管 bundle 时才运行 `ari registry`。如果只是自我归档，默认的 `local-tarball`（无服务器）后端已足够。学术永久性建议走 Zenodo。

## 快速开始

> **备注：** v0.5.0 已移除全局 `$HOME/.ari/` 目录。所有 registry 相关路径都需通过 env var（`ARI_REGISTRY_DATA`、`ARI_REGISTRIES_FILE`）或位于活动检查点之下（`$ARI_CHECKPOINT_DIR/.ari/registries.yaml`）。详见 `docs/_archive/refactor_audit.md` 与 `docs/guides/migration.md`；遗留回退在 v1.0 中移除。

```bash
# 1. 安装服务端依赖（默认 install 跳过以保持精简）
./setup.sh --with-registry        # 或: pip install fastapi uvicorn[standard] python-multipart

# 2. 指定数据目录并启动（默认端口 8290）
export ARI_REGISTRY_DATA="$PWD/.ari_registry"
./scripts/registry/start_local.sh

# 3. 颁发 token（明文仅显示一次）
ari registry token issue alice

# 4. 配置客户端
export ARI_REGISTRIES_FILE="$ARI_CHECKPOINT_DIR/.ari/registries.yaml"
mkdir -p "$(dirname "$ARI_REGISTRIES_FILE")"
cat > "$ARI_REGISTRIES_FILE" <<EOF
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: \$ARI_REGISTRY_TOKEN
EOF
export ARI_REGISTRY_TOKEN=ari_<步骤 3 的值>
```

## 端点

| Method | Path                                    | 认证   | 备注 |
|--------|-----------------------------------------|--------|------|
| GET    | `/healthz`                              | -      | liveness probe |
| GET    | `/version`                              | -      | 服务器版本 |
| POST   | `/artifact`                             | bearer | 上传 tarball + manifest |
| GET    | `/artifact/<id>`                        | maybe  | public/unlisted 匿名读，staged/private-token 需 bearer |
| HEAD   | `/artifact/<id>`                        | -      | sha256 + visibility 头（无 body） |
| GET    | `/artifact/<id>/manifest.lock`          | maybe  | 单独获取 manifest |
| POST   | `/artifact/<id>/promote`                | bearer | `staged` → `unlisted`/`public`（仅所有者） |
| DELETE | `/artifact/<id>`                        | bearer | 仅所有者 |

## 可见性模型（FR-RG6）

- `staged`：仅所有者 token 可读。**所有上传初始为 staged**。
- `unlisted`：任何知道 id 的人均可读（不列举）。
- `public`：开放阅读。
- `private-token`：获取时需要单独的 bearer token。

可见性 **只能升级**（staged → unlisted/public）。降级被拒。

## 存储

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite，bearer token 哈希保存
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"visibility":..., "owner":..., "sha256":..., "length":...}
```

artifact id 内容寻址：`sha256(bundle.tar.gz)[:16]`（16 个 hex 字符 / 64 位）。5e9 个 artifact 时，生日悖论冲突概率约 1%。未来版本将可配置 id 长度。

## token 生命周期

```bash
ari registry token issue <user>     # 明文仅显示一次，请妥善保管
ari registry token revoke <id>      # 立即失效
ari registry token list             # 列出谁有访问权限
```

## 部署模式

- `scripts/registry/start_local.sh` — uvicorn + sqlite，单进程。Laptop / dev。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF。HPC。

## 永久性

即便 registry 停止，**bundle 仍可验证**，因为 SHA-256 digest 已经烧录进论文的 `\codedigest{...}` 宏。把 bundle 迁到任意其它主机（S3、Zenodo、gh release）后，`ari clone file://...` 仍能依据 manifest 完成校验。

## 另请参阅

[出版生命周期](../concepts/publication-lifecycle.md) · [配置](configuration.md) · [PaperBench API](api_paperbench.md)
