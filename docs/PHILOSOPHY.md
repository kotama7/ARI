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
  partition: your_partition
```

### 2. LLM: Local → Commercial

ARI delegates all LLM calls through litellm. The model is configuration — not code.

```yaml
llm:
  model: qwen3:8b           # Ollama, no API key, runs offline
  model: gpt-5.2            # OpenAI API
  model: claude-opus-4-5    # Anthropic API
  base_url: http://...      # Any OpenAI-compatible API
```

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

When a node fails, ARI does not retry the same approach. Instead, the failed node enters the frontier and `expand()` generates `debug` child nodes that inherit the failure context. The next generation learns from the failure — this is qualitatively different from retry logic, which treats failure as noise rather than signal.

## Corollary: Reproducibility Is a First-Class Principle

ARI's agent system prompt includes one general scientific principle: *ensure your experiment is reproducible*. This is not a domain rule — it applies equally to chemistry, HPC, and machine learning. The agent decides autonomously what information needs to be captured. The paper reviewer then independently evaluates whether the paper is reproducible, closing the loop without any hardcoded criteria.
