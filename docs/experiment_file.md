# Writing Experiment Files

Experiment files are Markdown documents that fully describe what ARI should do.
No code changes are needed — all domain knowledge lives here.

## Minimal Example

```markdown
# My Experiment

## Research Goal
Maximize the throughput of matrix multiplication using different BLAS implementations.

## Required Workflow
1. Survey prior work on matrix multiplication optimization
2. Submit a SLURM job to compile and run the benchmark
3. Poll until the job completes
4. Read the output and report MFLOPS

<!-- min_expected_metric: 1000 -->
<!-- metric_keyword: MFLOPS -->
```

## Full Reference

### Section: Research Goal

Describes what the experiment is trying to achieve. The LLM reads this to understand the domain and propose hypotheses.

```markdown
## Research Goal
Maximize GFLOPS of a stencil benchmark on your HPC cluster.
Explore compiler flags (-O2, -O3, -Ofast) and thread counts (1, 32, 64).
```

### Section: Required Workflow

Tells the agent which tools to call and in what order.

```markdown
## Required Workflow
1. Call `survey` to find related literature
2. Call `slurm_submit` with a SLURM script
3. Call `job_status` to wait for completion
4. Call `run_bash` to read the output file
5. Return JSON with measured values
```

### Section: Hardware Limits

Hard constraints that must not be violated.

```markdown
## Hardware Limits
- Partition: your_partition
- Max CPUs: 64 (--cpus-per-task must be ≤ 64)
- Compiler: gcc only (no mpicc, icc, aocc)
```

### Magic Comments (metadata)

These are parsed automatically by `make_metric_spec`:

| Comment | Purpose |
|---------|---------|
| `<!-- min_expected_metric: N -->` | Minimum acceptable metric value |
| `<!-- metric_keyword: NAME -->` | Name of the metric to extract (e.g., MFLOPS) |

### Section: SLURM Script Template

Provide a working baseline script. The LLM will modify it to test hypotheses.

```markdown
## SLURM Script Template
\`\`\`bash
#!/bin/bash
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:30:00

gcc -O3 -fopenmp -o ./benchmark ./benchmark.c
export OMP_NUM_THREADS=32
./benchmark
\`\`\`
```

### Section: Rules

Specific constraints for the agent. Use HARD LIMITS for things the LLM must never violate.

```markdown
## Rules
- Always use work_dir=/abs/path/to/workdir in slurm_submit
- NEVER redirect stdout in the script (SLURM captures it automatically)
- Output file: slurm_job_{JOBID}.out
```

## Complete Example

See the example experiment files in the repository for complete working examples.
