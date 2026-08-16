---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate/policy.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
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

1. **`generate_ideas`** — a VirSci multi-agent deliberation debates the question
   and writes `idea.json`: a hypothesis, the primary metric, and an experiment
   plan. This runs **once** for the whole run and **sets** the primary metric
   (here, GFLOP/s) and its direction (higher is better).
2. **`make_metric_spec`** — derives concrete success metrics *from* that idea's
   `primary_metric` (not a free guess).
3. **`survey`** — searches the literature so the eventual paper can cite real
   references.

Open the **Idea** page to read what it proposed.

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

Watch this live on the **Live monitor** and **Research tree** pages. For the
per-node detail panel — Overview, MCP Trace (every tool call), Code, Memory,
Access and Report — open the legacy tree page at `#/tree`; there is no Output
tab, the node's files are browsed from the file explorer instead.

Two behaviours surprise newcomers — both are intentional:

- **A failed node is not retried.** ARI expands a `debug` child instead, so the
  fix is recorded as a new node.
- **A child that changes nothing is marked _sterile_ and never expanded again.**
  Output files are not inherited from the parent, so a child must actually
  re-run the experiment. When the run names a pinned problem (`ARI_PROBLEM`),
  that problem declares `score_inputs` and sterility is decided by hashing
  exactly those files rather than by diffing the whole work_dir — the
  whole-directory rule practically never fires, because every node rewrites
  bookkeeping files such as `results.json`.
  A sterile node keeps its measured score and evaluation status; what it loses
  is the right to be expanded and the right to retire its parent. (See the
  [FAQ](faq.md) and [Glossary → sterile](../reference/glossary.md).)

The search stops at your node/depth budget. The full tree is saved as
`tree.json` / `nodes_tree.json`.

## 5. From tree to paper (the post-BFTS pipeline)

When the search ends, a `workflow.yaml`-driven pipeline turns the tree into a
paper (see [Publication lifecycle](../concepts/publication-lifecycle.md)):

1. **audit_node_provenance** re-hashes every node artifact whose sha256 the
   node reports recorded and compares it against disk — right at the boundary
   where node outputs stop being experiment results and start being paper
   evidence. Per artifact it reports verified / mismatch / missing / unhashed
   into `node_provenance_audit.json`. It is a signal, not a gate.
2. **transform_data** reads the whole tree and extracts hardware, methodology,
   and findings into `science_data.json`.
3. **generate_ear** assembles the reproducibility bundle `ear/` (code, input
   data, figures, `reproduce.sh`, LICENSE — but not experiment outputs). It
   runs *before* the paper is written, not after: `write_paper` depends on it,
   because the bundle is the evidence the paper points at.
4. **generate_figures** has an LLM pick only *what* each figure shows (metric,
   chart type, x axis); a fixed renderer then draws it deterministically from
   `science_data.json`. A **VLM** reviews *every* figure, and because the
   aggregate score is the minimum across them, one weak figure loops the stage
   back for regeneration (threshold 0.7, at most 2 extra passes).
5. **write_paper** drafts the LaTeX, revises it, and pulls BibTeX from the
   survey results → `full_paper.tex` / `.pdf`.
6. **review_paper** runs one or more reviewer agents against the chosen venue
   rubric (an Area Chair meta-review aggregates when there is more than one).

By default the pipeline now also runs a **claim-evidence verification loop**: a
deterministic hard gate re-derives the reported numbers, a non-blocking
evidence-grounded semantic review checks the prose against that evidence, then an
anchor-preserving refine and re-render close the loop. It runs in **warn** mode
by default, which is *not* the same as report-only: warn still blocks the final
gate on the objective-integrity tier (`always_block_on` — invariant violations,
failed or uncovered correctness checks, placeholder denominators, recompute
mismatches, unbound or mismatched artifacts…), because those findings are
deterministically false rather than a matter of reviewer taste. Everything else
is reported and does not block until you set `ARI_CLAIM_GATE_MODE=strict` (or
`claim_gate_policy.mode: strict`), which additionally blocks the configured
`block_on` findings and uncovered result numbers in strict sections;
`mode: off` never blocks, and a draft-phase report never blocks either way.
See [Publication lifecycle](../concepts/publication-lifecycle.md) for the details.

Read it all from the **Paper & results** sidebar entry. That slot opens the
run-explicit, **read-only** summary (`#/results2?run=<run_id>`) — review score,
reproducibility chain, publication lineage. The Overleaf-like editor and the
EAR browser (and every EAR mutation) live on the legacy page it links out to,
`#/results`.

## 6. Verify it reproduces (ORS)

Finally ARI checks its own work the way an independent referee would
([ORS](../guides/paperbench/paperbench_quickstart.md)):

- **Phase 0** generates a PaperBench rubric from the final paper, then
  **audits that rubric** before anything is graded against it: each leaf is
  flagged `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable`
  and the flags are written back into `ors_rubric.json` (summary in
  `ors_rubric.audit.json`). Grading still proceeds — it is a quality signal, so
  a reader can see which criteria were unsound.
- **Phase 1** runs `reproduce.sh` in a sandbox (SLURM if available, else
  docker / apptainer / local) and checks the expected artifacts appear.
- **Phase 2** grades the result against that rubric, including a **negative
  control** (an empty repo must score near zero) so the grade can't be earned
  by doing nothing.

The verdict is in `ors_grade.json` (grade status, per-leaf scores, and the
negative-control result), with the phase-1 outcome in `ors_phase1.json`.

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
| `ors_grade.json` | The ORS verdict |

## Where to go next

- Make the goal file do more: [Writing experiment files](../guides/experiment_file.md)
- Understand the search in depth: [BFTS algorithm](../concepts/bfts.md)
- Run at scale: [HPC setup](../guides/hpc_setup.md)
- Reproduce someone else's paper: [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)

---

See also: [Quickstart](quickstart.md) · [FAQ](faq.md) ·
[Glossary](../reference/glossary.md) · [Architecture](../concepts/architecture.md)
