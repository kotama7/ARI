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

托管策展过的 EAR bundle 的最小 HTTP registry。是 `ari ear publish` 的默认后端，也是 `ari clone` 中 `ari://` 解析器的目标。

## 何时需要它

只有当你想为他人托管 bundle 时才运行 `ari registry`。如果只是自我归档，默认的 `local-tarball`（无服务器）后端已足够。学术永久性建议走 Zenodo。

## 快速开始

> **备注：** v0.5.0 降级了全局 `$HOME/.ari/` 目录——所有 registry 相关路径现在都应来自显式的 env var（`ARI_REGISTRY_DATA`、`ARI_REGISTRIES_FILE`）。迁移做法见 [迁移指南](../guides/migration.md)；遗留回退会发出 `DeprecationWarning`，并在 v1.0 中移除。第 2 步显式设置 `ARI_REGISTRY_DATA` 不是可有可无的卫生习惯：`start_local.sh` 与 `start_singularity.sh` 至今仍把它默认为 `$HOME/.ari/registry-data`。

```bash
# 1. 服务端依赖已随 requirements.txt / lockfile 一起提供，普通的 ./setup.sh
#    就会装上 fastapi + uvicorn + python-multipart。--with-registry 仍被接受，
#    但只是提示性的。
./setup.sh --with-registry        # 或: pip install fastapi uvicorn[standard] python-multipart

# 2. 指定数据目录并启动（uvicorn 监听 127.0.0.1:8290；`ari registry serve`
#    自身默认 --host 0.0.0.0，是脚本覆盖了它）
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

## 设置文件解析（v0.7+）

`ari ear publish --backend ari-registry` 与 `ari clone ari://` 都通过同一条四步链查找 `registries.yaml`：

1. `$ARI_REGISTRIES_FILE` —— 显式的 env override。
2. `{checkpoint_dir}/.ari/registries.yaml` —— 本意是让一次运行把自己的 registry 配置固定到检查点上。
3. `$(pwd)/.ari/registries.yaml` —— 在项目目录里运行时比较方便。
4. `$HOME/.ari/registries.yaml` —— **已废弃**；仅当该文件存在时才会被采用，而且要先发出 `DeprecationWarning`。v1.0 中移除。

> **第 2 步今天永远不会触发。** 两处查找都把 `checkpoint_dir` 作为可选参数，而没有任何调用点传入它——发布后端的 `_select_registry()` 与 `ari://` 解析器的 `resolve()` 都是不带该参数地调用它。因此放在检查点里的 `.ari/registries.yaml` 是不可见的，除非你用 `$ARI_REGISTRIES_FILE` 指向它，或者干脆从那个目录运行。

若链上没有任何文件存在，两条路径都会回退到由 `$ARI_REGISTRY_URL`（加上 `$ARI_REGISTRY_TOKEN`）构成的单个合成 registry；两者都没有时，命令以 `no ari-registry configured` 失败。当文件*存在*但没有列出任何 registry 时，两个实现就分道扬镳了：`ari://` 解析器会继续沿链往下走，仍能到达 `$ARI_REGISTRY_URL` 回退；而发布后端会把第一个可读文件里的空列表原样返回，即使设置了 `$ARI_REGISTRY_URL` 也会失败。发布后端还额外接受 `$ARI_REGISTRY_NAME`，用于按名字挑选条目。

文件中的 token 写成字面量或 `$VAR` 形式。解析器 docstring 里展示的 `${VAR}` 形式**并不生效**：两处 `_expand_token` 实现都先判断 `$` 前缀那一支，于是 `${ARI_REGISTRY_TOKEN}` 会被当作一个字面名为 `{ARI_REGISTRY_TOKEN}` 的环境变量去查，并静默展开为空字符串。

服务端状态（`ari registry serve`）位于 `$ARI_REGISTRY_DATA/`。遗留的 `$HOME/.ari/registry-data` 回退适用同一条 v1.0 废弃策略——显式设置该 env var 才能避免警告。

## 端点

| Method | Path                                    | 认证   | 备注 |
|--------|-----------------------------------------|--------|------|
| GET    | `/healthz`                              | -      | liveness probe，返回 `{"ok": true}` |
| GET    | `/version`                              | -      | `{"version": "0.7.0", "service": "ari-registry"}` |
| POST   | `/artifact`                             | bearer | multipart 上传：`bundle` 文件 + `manifest` / `metadata` / `visibility` 表单字段。重传完全相同的字节是幂等的，返回 `duplicate: true`；换成另一个 owner 会被拒绝 |
| GET    | `/artifact/<id>`                        | maybe  | public/unlisted 匿名读；staged 需所有者的 bearer token；private-token 只需任一有效 bearer token |
| HEAD   | `/artifact/<id>`                        | -      | sha256 + visibility + length 头（无 body）——**任何可见性下都不做鉴权** |
| GET    | `/artifact/<id>/manifest.lock`          | -      | 单独获取 manifest——**同样不做鉴权**，因此只要知道 id，任何人都能读到 staged bundle 的完整文件清单与逐文件 digest |
| POST   | `/artifact/<id>/promote?target=...`     | bearer | `target` 是查询参数（默认 `public`）；仅所有者 |
| DELETE | `/artifact/<id>`                        | bearer | 仅所有者 |

未知 id 返回 404；缺失或非法的 bearer token 返回 401；token 有效但不是所有者
返回 403；非法的 visibility 目标返回 400。

## 可见性模型（FR-RG6）

- `staged`：仅所有者 token 可读。**`ari ear publish` 始终以 staged 上传**，
  不过 HTTP 端点本身接受这四个取值中的任何一个。
- `unlisted`：任何知道 id 的人均可读（不列举）。（其实什么都不会被列举——
  服务器根本没有暴露列表端点。）
- `public`：开放阅读。
- `private-token`：获取时需要 bearer token —— 任一有效 token 即可，不必是所有者的。

可见性 **只能升级**。等级顺序为
`staged(0) < unlisted(1) = private-token(1) < public(2)`，所以 `unlisted` 与
`private-token` 之间可以双向互换，只有严格降级（例如 `public → unlisted`、
任何 `→ staged`）才会被拒。

## 存储

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite，bearer token 哈希保存
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"id":..., "visibility":..., "owner":...,
                                  #  "created_at":..., "sha256":..., "length":...}
```

artifact id 内容寻址：`sha256(bundle.tar.gz)[:16]`（16 个 hex 字符 / 64 位）。本页此前称「5e9 个 artifact 时，生日悖论冲突概率约 1%」，但 5e9 恰是 **50%** 的那个点。在 64 位空间上 `p ≈ 1 − exp(−n²/2N)`，约 1% 对应约 **6e8** 个 artifact，5e9 个时为 49%。未来版本将可配置 id 长度——今天 `[:16]` 截断是硬编码在 `FilesystemStorage.derive_id` 里的。

## token 生命周期

```bash
ari registry token issue <user>     # 明文仅显示一次，请妥善保管
ari registry token revoke <id>      # 立即失效
ari registry token list             # 列出谁有访问权限
```

## 部署模式

- `scripts/registry/start_local.sh` — uvicorn + sqlite，单进程。Laptop / dev。
  遵循 `ARI_REGISTRY_HOST`（默认 `127.0.0.1`）、`ARI_REGISTRY_PORT`（`8290`）
  与 `ARI_REGISTRY_DATA`（默认 `$HOME/.ari/registry-data`，即已废弃的位置）；
  在数据目录旁写 pidfile 与日志，若记录的 pid 仍存活则什么都不做。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
  注意 `proxy` 服务会 bind-mount `./nginx.conf`，而该文件**不在**仓库中——
  请在 `docker compose up` 之前自备。
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF。HPC。
  首次运行时构建 `$ARI_REGISTRY_SIF`（默认 `$HOME/.ari/ari-registry.sif`），
  在 `0.0.0.0:$ARI_REGISTRY_PORT` 上提供服务，数据目录绑定到 `/data`。

## 永久性

即便 registry 停止，**bundle 仍可验证**，因为 SHA-256 digest 已经烧录进论文的 `\codedigest{...}` 宏。把 bundle 迁到任意其它主机（S3、Zenodo、gh release）后，`ari clone file://...` 仍能依据 manifest 完成校验。

## 另请参阅

[出版生命周期](../concepts/publication-lifecycle.md) · [配置](configuration.md) · [PaperBench API](api_paperbench.md)
