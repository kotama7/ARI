# ARI QuickStart Guide

This guide walks you through installing ARI, choosing an AI model, and running your first experiment using the **web dashboard**. No programming experience is required.

For CLI (command-line) usage, see [CLI Reference](cli_reference.md).

---

## What You Will Need

| Requirement | Details |
|-------------|---------|
| **Operating System** | Linux or macOS (Windows: use WSL2) |
| **Python** | 3.10 or later |
| **Git** | To clone the repository |
| **Web browser** | Chrome, Firefox, Safari, or Edge |

Optional (but recommended):

| Tool | Why |
|------|-----|
| **conda / miniconda** | Easier LaTeX and PDF tool installation (no sudo needed) |
| **Ollama** | Run AI models locally for free — no API key, no cost |
| **LaTeX** | Required only if you want ARI to generate PDF papers |

---

## Step 1: Install ARI

Open a terminal and run:

```bash
git clone https://github.com/kotama7/ARI.git
cd ARI
bash setup.sh
```

The setup script automatically detects your OS and installs everything needed. It works on Linux, macOS, and WSL2 — with or without conda and sudo.

When setup finishes, you will see **"Setup Complete"** and next-step instructions.

---

## Step 2: Choose Your AI Model

ARI needs an AI model (LLM) to think, plan, and run experiments. Choose one of the following:

### Option A: Ollama — Free, runs on your computer (recommended)

No account needed. No API key. No cost. Everything runs locally.

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh     # Linux
# brew install ollama                              # macOS

# Download a model
ollama pull qwen3:8b

# Start the server (keep this terminal open)
ollama serve
```

Set environment variables (open a new terminal):

```bash
export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:8b
```

> **Which model size?**
>
> | Model | RAM needed | Quality |
> |-------|-----------|---------|
> | `qwen3:8b` | 16 GB | Good — great for getting started |
> | `qwen3:14b` | 32 GB | Better |
> | `qwen3:32b` | 64 GB | Best |

### Option B: OpenAI API (cloud, paid)

```bash
export ARI_BACKEND=openai
export ARI_MODEL=openai/gpt-4o
export OPENAI_API_KEY=sk-...     # Get from https://platform.openai.com/api-keys
```

### Option C: Anthropic API (cloud, paid)

```bash
export ARI_BACKEND=claude
export ARI_MODEL=anthropic/claude-sonnet-4-5
export ANTHROPIC_API_KEY=sk-ant-...  # Get from https://console.anthropic.com/
```

> **Tip:** Add `export` lines to your `~/.bashrc` or `~/.zshrc` to make them permanent.

---

## Step 3: Launch the Dashboard

Start the ARI web dashboard:

```bash
ari viz ./checkpoints/ --port 8765
```

Open your browser and go to: **http://localhost:8765**

You will see the ARI home screen:

![ARI Home](images/en/dashboard_home.png)

The left sidebar provides navigation to all dashboard pages:

| Page | Description |
|------|-------------|
| **Home** | Overview with quick actions and recent experiments |
| **Experiments** | List of all past experiment runs |
| **Monitor** | Real-time pipeline progress with D3 tree visualization |
| **Tree** | Full BFTS experiment tree — click nodes to inspect details |
| **Results** | View generated paper, review, and reproducibility report |
| **New Experiment** | Wizard to create and launch a new experiment |
| **Ideas** | VirSci-generated research hypotheses |
| **Workflow** | Edit the post-BFTS pipeline configuration |
| **Settings** | Configure LLM, API keys, SLURM, and language |

---

## Step 4: Create Your First Experiment (Wizard)

Click **"New Experiment"** in the sidebar (or the blue **"New Experiment"** button on the home page).

![Experiment Wizard](images/en/dashboard_wizard.png)

The wizard guides you through 4 steps:

### Step 1 of 4 — Choose Mode

| Mode | Best for |
|------|----------|
| **Chat** | Beginners. Describe what you want in natural language. The AI helps you refine it into a proper experiment. |
| **Write MD** | Write or paste your experiment description in Markdown directly. |
| **Upload** | Upload an existing `experiment.md` file from your computer. |

**Recommended for beginners: Chat mode.** Just type what you want to optimize or investigate, for example:

> "I want to find the best configuration for my experiment on this machine"

The AI will ask clarifying questions and generate the experiment file automatically.

### Step 2 of 4 — Scope

Configure how large the experiment should be:

| Setting | What it controls | Recommended for first run |
|---------|-----------------|--------------------------|
| **Max Depth** | How deep the search tree goes | 3 |
| **Max Nodes** | Total number of experiments to run | 5–10 |
| **Max ReAct Steps** | Reasoning steps per experiment | 80 (default) |
| **Timeout** | Seconds per experiment | 7200 (default) |
| **Parallel Workers** | Simultaneous experiments | 2–4 |

> **Tip:** Start small (5–10 nodes, depth 3) for your first run. You can always increase later.

### Step 3 of 4 — Resources

Select your LLM provider and model:

- **OpenAI / Anthropic / Ollama / Custom** — choose from the dropdown
- For Ollama, you can type any model name (e.g., `qwen3:8b`)
- Configure SLURM/HPC settings if running on a cluster

### Step 4 of 4 — Launch

Review your settings and click **Launch**. ARI will:

1. Search related academic papers
2. Generate research hypotheses (VirSci multi-agent deliberation)
3. Run experiments using Best-First Tree Search
4. Evaluate results with LLM peer review
5. Write a LaTeX paper with figures and citations
6. Verify reproducibility independently

---

## Step 5: Monitor the Experiment

Once launched, the **Monitor** page shows real-time progress:

![Monitor Page](images/en/dashboard_monitor.png)

- **Pipeline stages** are shown at the top (Idea → BFTS → Paper → Review)
- **Node tree** shows experiment progress with color-coded status
- **Logs** stream in real time

### Experiment Tree

Click **Tree** in the sidebar for the full interactive experiment tree:

![Tree View](images/en/dashboard_tree.png)

- **Green** nodes = success
- **Red** nodes = failed
- **Blue** nodes = running
- **Grey** nodes = pending

Click any node to inspect:

| Tab | What it shows |
|-----|---------------|
| **Overview** | Status, metrics, execution time, evaluation summary |
| **Trace** | Every tool call the AI agent made (step by step) |
| **Code** | Generated source code for this experiment |
| **Output** | Job stdout, benchmark results |

---

## Step 6: View Results

After the experiment completes, go to the **Results** page:

![Results Page](images/en/dashboard_results.png)

Here you can:

- Read the generated paper (LaTeX / PDF)
- View the automated peer review score and feedback
- Check the reproducibility verification report
- Download all artifacts

Output files are saved in `./checkpoints/<run_id>/`:

| File | Description |
|------|-------------|
| `full_paper.tex / .pdf` | Complete generated paper |
| `review_report.json` | Peer review score and feedback |
| `reproducibility_report.json` | Independent reproducibility verification |
| `tree.json` | Full experiment tree with all metrics |
| `science_data.json` | Cleaned data (no internal terms) |
| `figures_manifest.json` | Generated figures |
| `experiments/` | Per-node source code and output |

---

## Step 7: Configure Settings

Open the **Settings** page to customize ARI:

![Settings Page](images/en/dashboard_settings.png)

### Dashboard Language

Change the dashboard language (English, Japanese, Chinese) from the language dropdown at the top.

### LLM Backend

- Choose your provider (OpenAI, Anthropic, Ollama, Custom)
- Set the default model and temperature
- Enter your API key (stored locally, masked in the UI)

### Paper Search

- Optionally set a Semantic Scholar API key for higher rate limits

### SLURM / HPC

- Set default partition, CPU count, and memory for cluster jobs
- Click **Detect** to auto-detect your cluster's available partitions

### Per-Phase Model Overrides

Use different models for different pipeline phases (e.g., a cheaper model for idea generation, a better model for paper writing).

---

## Additional Dashboard Pages

### Ideas Page

![Ideas Page](images/en/dashboard_ideas.png)

View VirSci-generated research hypotheses with novelty and feasibility scores. See the experiment configuration, research goal, and BFTS node evaluations.

### Workflow Editor

![Workflow Page](images/en/dashboard_workflow.png)

Edit the post-BFTS pipeline stages (transform data → generate figures → write paper → review → reproducibility check). Changes are saved as `workflow.yaml`.

---

## Troubleshooting

### Installation

| Problem | Solution |
|---------|----------|
| `ari: command not found` | Add `~/.local/bin` to your PATH: `export PATH="$HOME/.local/bin:$PATH"` |
| Setup script fails | Check Python version: `python3 --version` (must be 3.10+) |
| Permission denied | Don't use `sudo`. Run as your normal user. |

### AI Model

| Problem | Solution |
|---------|----------|
| Ollama connection refused | Make sure `ollama serve` is running in another terminal |
| `LLM Provider NOT provided` | Use provider prefix: `openai/gpt-4o`, not just `gpt-4o` |
| Slow or timeout | Use a smaller model (`qwen3:8b`) or increase timeout in Settings |

### Experiment

| Problem | Solution |
|---------|----------|
| All nodes failed | Open Tree view, click a failed node, check the Trace tab |
| No results | Check Monitor page — the experiment may still be running |
| Interrupted run | Go to Experiments page, find the run, click Resume |

### Paper Generation

| Problem | Solution |
|---------|----------|
| No PDF generated | Install LaTeX: `conda install -c conda-forge texlive-core` |
| `No paper text available` | Install: `pip install pymupdf pdfminer.six` |

---

## Quick Start Recipe

```bash
# 1. Install
git clone https://github.com/kotama7/ARI.git && cd ARI && bash setup.sh

# 2. Set up AI (free, local)
ollama pull qwen3:8b && ollama serve &
export ARI_BACKEND=ollama ARI_MODEL=qwen3:8b

# 3. Launch the dashboard
ari viz ./checkpoints/ --port 8765
# Open http://localhost:8765 and use the wizard to create your experiment!
```

---

## Next Steps

- **CLI usage:** See [CLI Reference](cli_reference.md) for command-line operations
- **Experiment files:** See [Writing Experiment Files](experiment_file.md) for advanced syntax
- **HPC clusters:** See [HPC Setup Guide](hpc_setup.md) for SLURM configuration
- **Extending ARI:** See [Extension Guide](extension_guide.md) for adding new skills
