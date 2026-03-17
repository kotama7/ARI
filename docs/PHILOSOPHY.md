# ARI Design Philosophy

## Why ARI Exists

Research automation has historically required either:
- Expensive cloud infrastructure
- In-house engineering expertise
- Domain-specific tooling that doesn't transfer

ARI is built on the belief that **the gap between "I have an idea" and "I have a result" should be measured in hours, not months** — regardless of your resources.

## The Five Axes of Universality

### 1. Compute: Laptop → Supercomputer

ARI runs identically on a laptop (`mode: local`) and a SLURM cluster. The same experiment file, the same config format, the same output structure. Switching is one line in `workflow.yaml`.

```yaml
hpc:
  mode: local      # laptop
  mode: slurm      # HPC cluster
  partition: your_partition # cluster-specific, isolated here
```

### 2. LLM: Local → Commercial

ARI delegates all LLM calls through litellm. The model is configuration — not code.

```yaml
llm:
  model: qwen3:8b           # Ollama, no API key, runs offline
  model: gpt-5.2            # OpenAI API
  model: claude-opus-4-5    # Anthropic API
  base_url: http://...      # Any OpenAI-compatible API (vLLM, LM Studio)
```

### 3. Expertise: Novice → Expert

The experiment `.md` format has no required fields except a research goal. Novices write 3 lines. Experts write 200 lines with SLURM scripts, rules, and edge cases. ARI reads both.

The system gracefully handles partial information — it will infer, attempt, and report.

### 4. Domain: Computation → Physical World

ARI's core has no concept of "experiment type." It knows:
- There is a goal
- There are tools (MCP skills)
- There is a metric
- The agent should search for configurations that maximize the metric

This abstraction applies equally to:
- Compiler flag optimization (current)
- Hyperparameter tuning (add `ari-skill-ml`)
- Robot arm trajectory optimization (add `ari-skill-robot`)
- Wet lab protocol optimization (add `ari-skill-labware`)
- Any measurable phenomenon

The path to physical world is not a redesign — it is a new `ari-skill-*` package.

### 5. Output: Results → Verified Paper

ARI does not stop at "best result found." It:
1. Generates publication-ready LaTeX with figures and citations
2. Submits the paper to an LLM reviewer for quality feedback
3. Runs a **reproducibility agent** that reads the paper, extracts the experimental configuration, re-runs the experiment, and verifies the claimed numbers match

This closes the loop from hypothesis to peer-reviewable claim.

## Why MCP?

Model Context Protocol gives ARI three properties that matter:

1. **Isolation**: Each skill is a separate process. A bug in paper generation cannot corrupt an HPC job.
2. **Replaceability**: Swap any skill without touching others. Replace `ari-skill-hpc` with a Kubernetes backend — the rest doesn't care.
3. **Discoverability**: The LLM agent discovers available tools at runtime. Adding a skill = new capability, no agent reprogramming.

## The Physical World Path

The current skill set covers digital computation. The MCP architecture is designed to grow into physical systems:

```
Sensor reading     → ari-skill-sensor   (thermometers, cameras, flow meters)
Actuator control   → ari-skill-robot    (robot arms, servos, pumps)
Lab automation     → ari-skill-labware  (liquid handlers, plate readers)
Real-time feedback → ari-skill-control  (PID loops, safety interlocks)
```

Each of these skills follows the same pattern as existing skills:
- Pure function tools (no LLM inside)
- `dict` return values
- Registered in `workflow.yaml`
- Tested independently

The BFTS agent would then optimize physical parameters — reaction temperature, robot velocity, mixing ratios — using the same infrastructure that today optimizes compiler flags.

## Anti-goals

ARI is explicitly not designed to:
- Replace domain expertise (it amplifies it)
- Operate without human oversight at physical risk boundaries
- Be a black box (every decision is logged and traceable)
- Optimize for a single metric scalar (multi-objective by design)
