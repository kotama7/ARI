---
sources:
  - path: start.sh
    role: doc
  - path: setup.sh
    role: doc
  - path: ari-core/ari/cli
    role: implementation
last_verified: 2026-05-26
---

# Getting Started with ARI

ARI is an end-to-end autonomous research system: give it a plain-text research
goal and it surveys prior work, forms a hypothesis, runs real experiments,
writes a paper, and verifies its own reproducibility. This page is the map for
your first hour.

## A learning path

Follow these in order — each step assumes the previous one.

1. **[Quickstart](quickstart.md)** — install ARI, pick an AI model, and launch
   your first experiment from the web dashboard. Operation-focused: which
   button does what.
2. **[Your first experiment, end to end](first_experiment_tutorial.md)** — a
   narrative walkthrough of a single small experiment from goal to reproduced
   paper, explaining *why* each stage exists. Read this once the dashboard works.
3. **[FAQ](faq.md)** — the questions newcomers hit first: model choice, the
   `8765` port, where output goes, GPU/SLURM detection, "why do my child nodes
   show the same numbers?".
4. **[Glossary](../reference/glossary.md)** — one-line definitions of the
   recurring terms (BFTS, frontier, rubric, venue, EAR, ORS, CoW, …) so the
   concept docs read smoothly.

## Then branch by what you need

| If you want to… | Go to |
|---|---|
| Write a good `experiment.md` | [Writing experiment files](../guides/experiment_file.md) |
| Run on a SLURM/HPC cluster | [HPC setup](../guides/hpc_setup.md) |
| Understand how the search works | [BFTS algorithm](../concepts/bfts.md) · [Architecture](../concepts/architecture.md) |
| Reproduce or audit a published paper | [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md) |
| Add your own capability (skill) | [Extension guide](../guides/extension_guide.md) |
| Drive everything from the CLI | [CLI reference](../reference/cli_reference.md) |
| Fix something that broke | [Troubleshooting](../guides/troubleshooting.md) |

## Two things worth knowing up front

- **The dashboard runs on port `8765`.** Start every service with `./start.sh`
  at the repo root and open <http://localhost:8765>; stop with `./shutdown.sh`.
- **Each run is self-contained.** All state for a run lives under
  `workspace/checkpoints/<timestamp>_<slug>/` — nothing is written to your home
  directory, and API keys come from `.env`, never from the saved settings.

---

See also: [Quickstart](quickstart.md) · [FAQ](faq.md) ·
[Glossary](../reference/glossary.md) · [Documentation index](../README.md)
