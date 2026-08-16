---
sources:
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/prompts/agent/system.md
    role: implementation
  - path: ari-core/ari/prompts/orchestrator/bfts_expand.md
    role: implementation
last_verified: 2026-08-16
---

# ARI Design Philosophy

## Why ARI Exists

Research automation has historically required either:
- Expensive cloud infrastructure
- In-house engineering expertise
- Domain-specific tooling that doesn't transfer

ARI is built on the belief that **the gap between "I have an idea" and "I have a result" should be measured in hours, not months** — regardless of your resources.

## The Five Axes of Universality

### 1. Compute: Laptop → Supercomputer

ARI runs identically on a laptop and a SLURM cluster. The same experiment file, the same config format, the same output structure. Switching is one line in `workflow.yaml` — or `--profile laptop` / `--profile hpc`.

```yaml
resources:
  hpc_enabled: false      # laptop  (true → HPC cluster)
  partition: your_partition
```

`resources.hpc_enabled` is what `core.py` reads; a profile's `hpc.enabled`
is merged into it. Note that `--profile` merges only four keys
(`bfts.max_total_nodes`, `bfts.max_parallel_nodes`/`parallel`,
`hpc.enabled`, `hpc.scheduler`) — every other key in a profile YAML,
`partition` included, is silently ignored.

### 2. LLM: Local → Commercial

ARI delegates LLM calls through litellm. The model is configuration — not code.

```yaml
llm:
  backend: openai           # ollama | openai | claude_code | litellm | cli-shim
  model: qwen3:8b           # Ollama, no API key, runs offline
  model: gpt-5.2            # OpenAI API
  model: claude-sonnet-4-5    # Anthropic API
  base_url: http://...      # Any OpenAI-compatible API
```

One backend is not litellm-routed: `backend: claude_code` goes straight to
the Claude Code CLI provider (`ari/llm/claude_code/`), and tool calling is
unsupported there — it fails loud rather than silently dropping tools.

### 3. Expertise: Novice → Expert

The experiment `.md` format has no required fields except a research goal. Novices write 3 lines. Experts write 200 lines. ARI reads both.

### 4. Domain: Computation → Physical World

ARI's core has no concept of "experiment type." It knows:
- There is a goal
- There are tools (MCP skills)
- There is a quality signal (LLM-assigned scientific_score)
- The agent should search for configurations that maximize scientific contribution

This abstraction applies equally to compiler optimization, ML hyperparameter tuning, robot arm trajectories, or wet lab protocols.

### 5. Output: Results → Verified Paper

ARI does not stop at "best result found." It:
1. Traverses the full experiment tree (including ablations and validation runs)
2. Uses an LLM to extract scientific context from raw artifacts
3. Generates publication-ready LaTeX with figures and citations
4. Submits the paper to an LLM reviewer for quality feedback
5. Runs a reproducibility agent that re-runs the experiment and verifies claimed numbers

## The Zero Domain Knowledge Principle

**ARI's production code contains no domain knowledge.**

This is not just a design preference — it is a hard invariant enforced in code review.

What this means in practice:

| ❌ Forbidden | ✅ Correct |
|-------------|-----------|
| `if "GFLOP" in metric_name` | `scientific_score` from LLM |
| `grep -i "gcc\|openmp"` | LLM reads artifacts freely |
| `"compare against MKL"` in prompt | LLM decides what to compare |
| Hardcoded figure types | LLM decides what figures to draw |
| `+0.2` scoring weights | LLM scores holistically |
| `lscpu` in system prompt | LLM reads lscpu output if it ran it |

The only things ARI's core prescribes:
- **Format**: JSON for tool calls, Markdown for experiments
- **Protocol**: MCP for skill communication
- **Signal**: `scientific_score` (LLM assigns 0.0–1.0) drives BFTS
- **Results contract**: `emit_results` requires a typed split between INPUT
  parameters and MEASUREMENTS, bound to an execution receipt — and the agent
  is told not to finish until `scientifically_admissible=true`. This is a
  shape requirement, not a domain one: what goes in either bucket is still
  the LLM's call.

Everything else — what to measure, how to compare, what hardware details matter, what figures to draw, what citations to include — is determined autonomously by the LLM at runtime.

## Why scientific_score?

Previous versions used domain-specific keywords (`gflop`, `bandwidth`) to rank nodes. This worked for HPC but failed silently for other domains.

`scientific_score` is a 0.0–1.0 quality signal assigned by the LLM evaluator acting as a peer reviewer. It captures scientific rigor holistically:
- Did the experiment produce real measurements?
- Were results compared against existing approaches?
- Is the methodology reproducible?
- Does the result support a clear scientific claim?

The LLM decides the weights. ARI only reads the number.

## Why MCP?

Model Context Protocol gives ARI three properties:

1. **Isolation**: Each skill is a separate process. A bug in paper generation cannot corrupt an HPC job.
2. **Replaceability**: Swap any skill without touching others.
3. **Discoverability**: The LLM agent discovers available tools at runtime. Adding a skill = new capability, no agent reprogramming.

## The Physical World Path

The current skill set covers digital computation. The MCP architecture is designed to grow:

```
Sensor reading     → ari-skill-sensor
Actuator control   → ari-skill-robot
Lab automation     → ari-skill-labware
Real-time feedback → ari-skill-control
```

The BFTS agent would then optimize physical parameters — reaction temperature, robot velocity, mixing ratios — using the same infrastructure that today optimizes compiler flags.

## Anti-goals

ARI is explicitly not designed to:
- Replace domain expertise (it amplifies it)
- Operate without human oversight at physical risk boundaries
- Be a black box (every decision is logged and traceable)
- Have hardcoded opinions about what "good science" looks like in any specific domain

## Corollary: Failed Experiments Are Information

When a node fails, ARI does not retry the same approach. Instead, the failed node enters the frontier and `expand()` hands the planner the parent's status (`failed/no-real-data`) with the instruction that `debug` means "parent FAILED or has no real data — diagnose and fix it". The label is the planner's choice, not a hardcoded branch: the prompt strongly prefers the five canonical labels but a custom one is preserved as `raw_label`. The next generation learns from the failure — this is qualitatively different from retry logic, which treats failure as noise rather than signal.

## Corollary: Reproducibility Is a First-Class Principle

ARI's agent system prompt includes general scientific principles — *ensure your experiment is reproducible*, *never fabricate numeric values*, and the typed `emit_results` split above. None is a domain rule; they apply equally to chemistry, HPC, and machine learning. The agent decides autonomously what information needs to be captured. The paper reviewer then independently evaluates whether the paper is reproducible, closing the loop without any hardcoded criteria.

## Memory (v0.6.0): P2 relaxed for one skill, P5 scoped

ARI's original design declared **P2 — deterministic where possible** and
**P5 — reproducibility-first**. v0.6.0 replaces the deterministic JSONL
memory store with [Letta](https://docs.letta.com) so ARI can use
embedding-based retrieval and proper agent memory management. This is
the only place in the system where P2 is relaxed, and its consequences
are bounded and documented.

- **What still holds.** Numerical experiment results remain reproducible
  given the same seed. Stored memory *text* is byte-stable: ancestor
  entries are Copy-on-Write protected at write time, and Letta's
  self-edit pass is disabled by default
  (`ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true`).
- **What may differ.** Because retrieval depends on embedding FP
  arithmetic and vector-index state, the BFTS *trajectory* (which nodes
  are explored, in which order) may diverge across re-runs. Each search
  carries that fact with it: `MemoryRetrievalV1.provenance` records the
  `backend` (`"letta"`), its `backend_version` / `server_version`, the
  embedding `model` / `model_version`, the `ranking` rule, and
  `deterministic: false`. Every memory read and write is additionally
  appended to `{checkpoint}/memory_access.jsonl`, so trajectory
  divergence can be traced back to the retrieval that produced it.
- **Why this trade.** The deterministic keyword scorer worked but
  did not scale to cross-experiment reasoning. Letta brings structured
  core memory, vector retrieval, and a uniform agent/collection model
  that lets every skill use the same memory surface without
  re-implementing retrieval.

Operationally, Letta is a dependency you run locally (Docker / Singularity
/ pip) or on Letta Cloud. See `docs/reference/configuration.md` and the
`ari memory` CLI for setup.

## See also

[Architecture](architecture.md) · [BFTS algorithm](bfts.md)
