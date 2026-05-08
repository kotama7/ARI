# ari-skill-hpc ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | SLURM ジョブ投入・監視・Singularity コンテナオーケストレーション |
| LOC | 1500 |
| MCP ツール | `slurm_submit`, `job_status`, `run_bash`, `singularity_run`(README 記載) |
| LLM 使用 | × |
| 決定論性 (P2) | ○ |
| 環境変数 | `SLURM_MODE` (local|ssh), `SLURM_SSH_HOST`, `SLURM_SSH_USER`, `SLURM_SSH_PORT`, `SLURM_SSH_KEY` |
| ステート | あり(SLURM ジョブ状態、リモート出力ファイル) |
| 既存 README | あり(要監査) |
| テスト | 4 ファイル(local / remote / singularity / conftest) |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-hpc

## 責務
SLURM ジョブ投入・監視、Singularity コンテナ実行を MCP ツールとして提供。
ローカル(同マシン)モードと SSH 越しのリモートクラスタモードをサポート。

## MCP ツール

### `slurm_submit`
**用途:** SLURM ジョブを sbatch で投入する。
**引数:**
- `script` (string, required): シェルスクリプト本体
- `partition` (string, optional): SLURM partition
- `time_limit` (string, optional): `--time` 引数(例 `01:00:00`)
- `nodes` (int, optional): `--nodes` 引数
- ...
**戻り値:** `{ "job_id": "...", "submit_time": "..." }`
**副作用:** リモートクラスタにジョブが投入される

### `job_status`
**用途:** ジョブ状態を `squeue`/`sacct` で問い合わせる。
**引数:** `job_id`
**戻り値:** `{ "state": "RUNNING|PENDING|COMPLETED|FAILED", "exit_code": int | null, ... }`

### `run_bash`
**用途:** SLURM 経由ではなく直接 bash を実行(短いコマンド向け)。

### `singularity_run`
**用途:** Singularity コンテナ内でコマンド実行。

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `SLURM_MODE` | `local` または `ssh` | `local` |
| `SLURM_SSH_HOST` | SSH 越しモード時のホスト名 | (なし、ssh モード時必須) |
| `SLURM_SSH_USER` | SSH ユーザ名 | (現在のユーザ) |
| `SLURM_SSH_PORT` | SSH ポート | 22 |
| `SLURM_SSH_KEY` | SSH 秘密鍵パス | `~/.ssh/id_rsa` |

## 依存
- `mcp >= 1.0`
- `paramiko >= 3.0`(SSH モード時)
- `pydantic >= 2.0`

## デプロイ例(SSH モード)
\`\`\`bash
export SLURM_MODE=ssh
export SLURM_SSH_HOST=cluster.example.org
export SLURM_SSH_USER=research
python -m ari_skill_hpc.server
\`\`\`

## 開発
\`\`\`bash
pytest tests/ -q             # 全テスト
pytest tests/test_slurm_local.py    # ローカルのみ(SLURM 不要)
pytest tests/test_slurm_remote.py   # SSH 必須
\`\`\`

## 関連
- [docs/hpc_setup.md](../docs/hpc_setup.md) — クラスタセットアップ全体
- [ari-skill-coding](../ari-skill-coding/README.md) — Singularity コンテナ実行
```

### 2-2. mcp.json と実装の同期
ツール定義を `src/server.py` の実装と一致させる。

### 2-3. `docs/hpc_setup.md` への相互リンク
[../docs/DOCUMENTATION_PLAN.md §2-4](../docs/DOCUMENTATION_PLAN.md) で `hpc_setup.md` を更新する際、本スキル README へリンクを追加。

## 3. 受け入れ基準

- [ ] README.md に 4 ツール、env var 5 件、SSH モードの設定例が含まれる
- [ ] `pytest tests/test_slurm_local.py -q` がグリーン
- [ ] `docs/hpc_setup.md` から本スキルへリンク

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
