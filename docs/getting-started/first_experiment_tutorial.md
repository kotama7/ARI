---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-26
---

# Your First Experiment, End to End

The [Quickstart](quickstart.md) shows *which buttons to press*. This tutorial
follows one small experiment all the way through — goal → hypothesis → search →
paper → reproduced — and explains *why* each stage exists. By the end you will
recognise every file ARI leaves in a checkpoint and know which document to open
when you want more depth.

We use a deliberately simple, domain-neutral goal so the mechanics stay in
focus: **make a dense matrix-multiply routine faster on this machine.** ARI is
not specialised for this — the same pipeline runs for any measurable goal; the
domain choices are all made by the LLM at runtime.

> **Before you start:** finish the [Quickstart](quickstart.md) so the dashboard
> is up on <http://localhost:8765> and a model is configured.

## 1. State the goal (`experiment.md`)

An experiment file is plain Markdown. The minimum is a few lines of research
goal — no code:

```markdown
# Goal
Improve the throughput (GFLOP/s) of a dense single-precision matrix
multiplication on the available hardware. Compare against a naive triple loop.
```

That is enough. You can add `## Provided Files` or constraints later (see
[Writing experiment files](../guides/experiment_file.md)), but ARI fills in the
specifics itself.

## 2. Launch

From the dashboard, use **New Experiment** → keep the first run small (depth 3,
5–10 nodes, 2–4 workers). Or from the CLI:

```bash
ari run experiment.md
```

A checkpoint directory appears at `workspace/checkpoints/<timestamp>_<slug>/`.
Everything below lands there.

## 3. Survey and hypothesis (the root node)

The first node does the framing work, in order:

1. **`make_metric_spec`** — pins the primary metric (here, GFLOP/s, higher is
   better) from your goal.
2. **`survey`** — searches the literature so the eventual paper can cite real
   references.
3. **`generate_ideas`** — a VirSci multi-agent deliberation debates the question
   and writes `idea.json`: a hypothesis, the primary metric, and an experiment
   plan. This runs **once** for the whole run.

Open the **Ideas** page to read what it proposed.

## 4. The search (BFTS)

Now ARI explores. It is not a linear script — it is a
[best-first tree search](../concepts/bfts.md):

- Each **node** is one concrete attempt, run by a [ReAct agent](../concepts/architecture.md#per-node-prompt-composition)
  that writes code, submits it (locally or via SLURM), reads the output, and
  extracts metrics.
- Completed nodes enter the **frontier**. ARI repeatedly picks the most
  promising one and **expands** it into a single child labelled `improve`,
  `ablation`, `validation`, `debug`, or `draft`.
- A peer-reviewer LLM (the **`LLMEvaluator`**) scores each node's
  `_scientific_score`, and that score drives which node gets expanded next.

Watch this live on the **Monitor** and **Tree** pages. Click any node for its
Overview, Trace (every tool call), Code, and Output tabs.

Two behaviours surprise newcomers — both are intentional:

- **A failed node is not retried.** ARI expands a `debug` child instead, so the
  fix is recorded as a new node.
- **A child that produces no new files is marked _sterile_ and pruned.** Output
  files are not inherited from the parent, so a child must actually re-run the
  experiment to earn a score. (See the [FAQ](faq.md) and
  [Glossary → sterile](../reference/glossary.md).)

The search stops at your node/depth budget. The full tree is saved as
`tree.json` / `nodes_tree.json`.

## 5. From tree to paper (the post-BFTS pipeline)

When the search ends, a `workflow.yaml`-driven pipeline turns the tree into a
paper (see [Publication lifecycle](../concepts/publication-lifecycle.md)):

1. **transform_data** reads the whole tree and extracts hardware, methodology,
   and findings into `science_data.json`.
2. **generate_figures** writes the plotting code; a **VLM** then reviews the
   main figure and loops back if it scores low.
3. **write_paper** drafts the LaTeX, revises it, and pulls BibTeX from the
   survey results → `full_paper.tex` / `.pdf`.
4. **review_paper** runs one or more reviewer agents against the chosen venue
   rubric (an Area Chair meta-review aggregates when there is more than one).
5. **generate_ear** assembles the reproducibility bundle `ear/` (code, input
   data, figures, `reproduce.sh`, LICENSE — but not experiment outputs).

Read it all on the **Results** page: the Overleaf-like editor, the review score,
and the EAR browser.

## 6. Verify it reproduces (ORS)

Finally ARI checks its own work the way an independent referee would
([ORS](../guides/paperbench/paperbench_quickstart.md)):

- **Phase 1** runs `reproduce.sh` in a sandbox (SLURM if available, else
  docker / apptainer / local) and checks the expected artifacts appear.
- **Phase 2** grades the result against an auto-generated PaperBench rubric,
  including a **negative control** (an empty repo must score near zero) so the
  grade can't be earned by doing nothing.

The verdict is in `reproducibility_report.json`.

## 7. What you have now

In `workspace/checkpoints/<timestamp>_<slug>/`:

| File | What it is |
|---|---|
| `idea.json` | Hypothesis + plan from VirSci |
| `tree.json` / `nodes_tree.json` | The full search tree with metrics |
| `science_data.json` | Cleaned, science-facing data |
| `full_paper.tex` / `.pdf` | The generated paper |
| `review_report.json` | Peer-review score and feedback |
| `ear/` | Reproducibility bundle |
| `reproducibility_report.json` | The ORS verdict |

## Where to go next

- Make the goal file do more: [Writing experiment files](../guides/experiment_file.md)
- Understand the search in depth: [BFTS algorithm](../concepts/bfts.md)
- Run at scale: [HPC setup](../guides/hpc_setup.md)
- Reproduce someone else's paper: [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)

---

See also: [Quickstart](quickstart.md) · [FAQ](faq.md) ·
[Glossary](../reference/glossary.md) · [Architecture](../concepts/architecture.md)
