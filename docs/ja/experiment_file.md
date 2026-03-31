# 実験ファイルの書き方

実験ファイルは、ARI が何を行うべきかを完全に記述する Markdown ドキュメントです。
コードの変更は不要です — すべてのドメイン知識はここに記述します。

## 最小限の例

```markdown
# My Experiment

## Research Goal
Maximize the score of the benchmark using different optimization strategies.

## Required Workflow
1. Survey prior work on optimization approaches
2. Submit a SLURM job to compile and run the benchmark
3. Poll until the job completes
4. Read the output and report score

<!-- min_expected_metric: 1000 -->
<!-- metric_keyword: score -->
```

## 完全なリファレンス

### セクション: Research Goal

実験が達成しようとしていることを記述します。LLM はこれを読み、ドメインを理解し仮説を提案します。

```markdown
## Research Goal
Maximize score of a benchmark on your HPC cluster.
Explore optimization strategies and parallel configurations (1, 32, 64 workers).
```

### セクション: Required Workflow

エージェントがどのツールをどの順序で呼び出すかを指示します。

```markdown
## Required Workflow
1. Call `survey` to find related literature
2. Call `slurm_submit` with a SLURM script
3. Call `job_status` to wait for completion
4. Call `run_bash` to read the output file
5. Return JSON with measured values
```

### セクション: Hardware Limits

違反してはならないハード制約です。

```markdown
## Hardware Limits
- Partition: your_partition
- Max CPUs: 64 (--cpus-per-task must be ≤ 64)
- Compiler: default compiler only
```

### マジックコメント（メタデータ）

これらは `make_metric_spec` によって自動的にパースされます:

| コメント | 用途 |
|---------|---------|
| `<!-- min_expected_metric: N -->` | 許容可能な最小メトリクス値 |
| `<!-- metric_keyword: NAME -->` | 抽出するメトリクスの名前（例: score） |

### セクション: SLURM Script Template

動作するベースラインスクリプトを提供します。LLM は仮説をテストするためにこれを修正します。

```markdown
## SLURM Script Template
\`\`\`bash
#!/bin/bash
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:30:00

compiler -o ./benchmark ./benchmark.c
export NTHREADS=32
./benchmark
\`\`\`
```

### セクション: Rules

エージェントへの具体的な制約です。LLM が絶対に違反してはならない事項にはハードリミットを使用します。

```markdown
## Rules
- Always use work_dir=/abs/path/to/workdir in slurm_submit
- NEVER redirect stdout in the script (SLURM captures it automatically)
- Output file: slurm_job_{JOBID}.out
```

## 完全な例

完全な動作例については、リポジトリ内のサンプル実験ファイルを参照してください。
