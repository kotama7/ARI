---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/config/default.yaml
    role: config
last_verified: 2026-05-26
---

# FAQ

The questions newcomers hit first. For step-by-step recovery from a broken run,
see [Troubleshooting](../guides/troubleshooting.md); for term definitions, the
[Glossary](../reference/glossary.md).

## Setup & models

**Which AI model should I start with?**
For a first run with no account or cost, use Ollama with `qwen3:8b` (needs
~16 GB RAM). For higher quality, use a cloud model such as `openai/gpt-4o` or
`anthropic/claude-sonnet-4-5`. Always include the provider prefix —
`openai/gpt-4o`, not `gpt-4o`. See [Quickstart → Choose your AI model](quickstart.md#step-2-choose-your-ai-model).

**`ari: command not found` after install.**
Add the user bin directory to your PATH: `export PATH="$HOME/.local/bin:$PATH"`.
Do not run `setup.sh` with `sudo` — run it as your normal user.

**Ollama "connection refused".**
`ollama serve` must be running in another terminal before you launch ARI.

## The dashboard

**What port is the dashboard on?**
`8765`. Start everything with `./start.sh` (Letta + registry + GUI) at the repo
root and open <http://localhost:8765>. `./start.sh status` health-checks; stop
with `./shutdown.sh`. The WebSocket for live tree updates is on `8766`
(port + 1).

**The page won't load / a service didn't come up.**
Re-run `./start.sh` (it restarts all three services every invocation) and check
`./start.sh status`. `shutdown.sh` also reaps any apptainer-orphaned
postgres/redis from a previous Letta run.

## Running experiments

**Where does the output go?**
Into a self-contained checkpoint directory,
`workspace/checkpoints/<timestamp>_<slug>/` (the timestamp form is
`YYYYMMDDHHMMSS_<slug>`). Paper, figures, tree, EAR, and reproducibility report
all live there. Nothing is written to your home directory.

**How big should my first run be?**
Small: 5–10 nodes at depth 3 with 2–4 parallel workers. You can always scale up
later. Larger searches cost more LLM calls and compute.

**My child nodes all report the same numbers as the parent — is that a bug?**
No, it is a guardrail doing its job. A child's `work_dir` is seeded by copying
the parent's, but experiment *outputs* (`results.csv`, `slurm-*.out`,
`metrics.json`, `*.log`, …) are on a blacklist and are **not** inherited. If a
child finishes without producing any new/changed files, ARI marks it
**sterile** (score `0.0`) and prunes it, instead of crediting inherited results.
If you see this often, the agent isn't actually re-running the experiment —
check the node's Trace tab. See
[Architecture → work_dir inheritance](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)
and the [Glossary → sterile](../reference/glossary.md).

**An experiment failed — does ARI retry it?**
No. BFTS never re-executes a failed node; instead it expands a `debug` child to
diagnose and fix the failure. Open the failed node's Trace tab to see what
happened.

## GPU, SLURM & containers

**How do I run on a cluster?**
Set the SLURM partition in Settings (or `--partition` on the CLI) and use the
`hpc` profile. Click **Detect** in Settings to auto-detect partitions, or
`/api/scheduler/detect` to auto-detect the scheduler (SLURM/PBS/LSF/Kubernetes).
See [HPC setup](../guides/hpc_setup.md).

**GPUs aren't being used.**
Check `nvidia-smi` works, that your SLURM request asks for GPUs, and your
container runtime is detected (Settings → **Detect Runtime**). For PaperBench
reproduction, missing GPU/sandbox now fails loudly rather than silently falling
back to CPU — see [PaperBench GUI → fail-loud preconditions](../guides/paperbench/paperbench_gui.md).

## Keys, paper & reproducibility

**Where are my API keys stored?**
In `.env` files only — never in `settings.json`. The search order is
checkpoint → ARI root → `ari-core` → home, or environment variables injected at
launch.

**No PDF was generated.**
Install LaTeX (`conda install -c conda-forge texlive-core`) and the PDF text
tools (`pip install pymupdf pdfminer.six`).

**Can I move a finished run to another machine?**
Yes. Each checkpoint carries a `memory_backup.jsonl.gz`, so
`cp -r workspace/checkpoints/<run> /elsewhere/` followed by `ari resume`
restores the memory into an empty Letta automatically.

---

See also: [Troubleshooting](../guides/troubleshooting.md) ·
[Quickstart](quickstart.md) · [Glossary](../reference/glossary.md)
