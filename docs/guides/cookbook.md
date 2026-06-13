---
sources:
  - path: ari-core/config/profiles
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
last_verified: 2026-06-10
---

# Cookbook

Copy-paste recipes for the configuration knobs you reach for most often. This
is a how-to companion to the exhaustive [Configuration reference](../reference/configuration.md)
— when a recipe needs the full option list, it links there rather than
repeating it.

> **Where overrides go.** Environment profiles live in
> `ari-core/config/profiles/<name>.yaml`; run-wide settings live in
> `workflow.yaml`. A profile is merged on top of the defaults when you pass
> `--profile <name>` (CLI) or pick it in the wizard. You can add `evaluator:`
> and `bfts:` blocks to either file.

## Environment profiles: laptop / HPC / cloud

Three profiles ship out of the box. Select with `ari run experiment.md --profile hpc`
(or the Resources step of the wizard).

**`laptop`** — small local runs, no scheduler:

```yaml
profile: laptop
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 8
  parallel: 2
```

**`hpc`** — SLURM/PBS/LSF cluster with auto-detected partition:

```yaml
profile: hpc
hpc:
  enabled: true
  scheduler: auto
  partition: auto
  cpus_per_task: 8
  memory_gb: 32
  walltime: "04:00:00"
  max_concurrent_jobs: 4
bfts:
  max_total_nodes: 20
  parallel: 4
```

**`cloud`** — no scheduler but a wider parallel search:

```yaml
profile: cloud
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 16
  parallel: 4
```

**Recipe — make your own profile.** Drop a new file in
`ari-core/config/profiles/`, e.g. `bigjob.yaml`, and select it with
`--profile bigjob`:

```yaml
profile: bigjob
hpc:
  enabled: true
  scheduler: auto
  partition: gpu
  cpus_per_task: 32
  memory_gb: 128
  walltime: "12:00:00"
bfts:
  max_total_nodes: 40
  parallel: 8
```

See [HPC setup](hpc_setup.md) for partition detection and SLURM specifics.

## Tuning the search and the evaluator

ARI exposes four independent evaluation layers; each default is a no-op that
reproduces classic behaviour. The full semantics are in
[Configuration → BFTS Evaluation Layers](../reference/configuration.md#bfts-evaluation-layers-configurable);
the recipes below are the common combinations.

**Bottleneck scoring — only reward a node when *every* axis is good:**

```yaml
evaluator:
  composite: weighted_min   # the score is the lowest axis; weights gate participation
```

**More exploration — UCB-style frontier ranking** (good when the search keeps
re-expanding the same high scorer):

```yaml
bfts:
  frontier_score: ucb_like
  ucb_c: 1.0                # 0.0 reduces this back to the default strategy
```

**Prefer shallower nodes — penalise depth in the fallback ranking:**

```yaml
bfts:
  frontier_score: depth_penalized
  depth_penalty_lambda: 0.1
```

**Measure a custom axis (e.g. speedup) instead of the generic five:**

```yaml
evaluator:
  axis_mode: custom
  custom_axes: [correctness, speedup, reproducibility]
  # axis_weights below set the relative weight of each named axis
```

**Reproduce pre-audit behaviour exactly** (pin the canonical five axes and the
harmonic mean):

```yaml
evaluator:
  axis_mode: legacy
  composite: harmonic_mean
```

**Swap in your own selection prompt** (Layer D) — point at a template under
`ari-core/ari/prompts/` (without the `.md` suffix); it must keep the same
placeholders:

```yaml
bfts:
  select_prompt: orchestrator/my_select          # needs {experiment_goal} {memory_context} {candidates}
  expand_select_prompt: orchestrator/my_expand    # needs {experiment_goal} {candidates}
```

## PaperBench: reproduce vs audit

Both modes are driven by the same rubric machinery; the difference is what you
point them at. See [PaperBench quickstart](paperbench/paperbench_quickstart.md)
for the end-to-end flow and [environment variables](../reference/environment_variables.md)
for every knob.

**Reproduce a paper** (run its code from scratch and grade it). Pin the Phase 1
sandbox explicitly when auto-selection would pick the wrong one:

```bash
export ARI_PHASE1_SANDBOX=slurm        # or docker / apptainer / singularity / local
export ARI_SLURM_PARTITION=gpu          # required when the sandbox is slurm
```

**Audit a paper** (judge whether the paper *itself* is described well enough to
be reproducible) — select an audit venue template via the rubric:

```bash
export ARI_RUBRIC=sc                    # venue template: sc / neurips / nature
```

Switching `ARI_RUBRIC` changes the BFTS scoring axes and the published review
criteria together — see the [Glossary → venue](../reference/glossary.md) and
[Architecture → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070).

---

See also: [Configuration reference](../reference/configuration.md) ·
[HPC setup](hpc_setup.md) · [PaperBench quickstart](paperbench/paperbench_quickstart.md) ·
[Glossary](../reference/glossary.md)
