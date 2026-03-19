# Contributing to ARI

## Repository Structure

```
ARI/
├── README.md               ← Start here
├── docs/                   ← Full documentation
│   ├── architecture.md     ← System design and data flow
│   ├── experiment_file.md  ← How to write experiment .md files
│   ├── skills.md           ← MCP skill API reference
│   └── configuration.md   ← Config file reference
│
├── ari-core/               ← Core engine (BFTS + ReAct + pipeline)
├── ari-skill-hpc/          ← SLURM / Singularity tools
├── ari-skill-idea/         ← Survey + idea generation
├── ari-skill-evaluator/    ← Metric extraction
├── ari-skill-paper/        ← LaTeX generation + review
├── ari-skill-paper-re/     ← Reproducibility verification
├── ari-skill-memory/       ← Ancestor-scoped memory
├── ari-skill-orchestrator/ ← ARI as MCP server
├── ari-skill-review/       ← Rebuttal generation
├── ari-skill-vlm/          ← Figure/table review (VLM)
├── ari-skill-benchmark/    ← Result analysis + visualization
│
└── matrix_bench_experiment.md  ← Example experiment
```

## Development Setup

```bash
git clone <repo>
cd ari-core && pip install -e ".[dev]"
cd ../ari-skill-hpc && pip install -e ".[dev]"
# repeat for other skills

# Run all tests
cd ari-core && pytest tests/ -q    # 45 tests
cd ari-skill-hpc && pytest tests/ -q  # 27 tests
```

## Design Principles (Non-Negotiable)

### P1: Generic Core
`ari-core` must contain zero experiment-domain knowledge.
All domain config lives in `experiment.md` and `WorkflowHints`.

❌ Wrong:
```python
# In ari-core/ari/agent/loop.py
if "MFLOPS" in result:  # domain-specific!
    ...
```

✅ Right:
```python
# Domain knowledge injected via WorkflowHints
metric_keyword = hints.metric_keyword  # from experiment.md
```

### P2: Deterministic Skills
MCP skill servers must **never** call an LLM.
The only exceptions are `generate_section`, `review_section`, and `generate_ideas`
— all called in post-BFTS or pre-BFTS phases, never inside the search loop.

❌ Wrong:
```python
@mcp.tool()
def evaluate(artifacts: str) -> dict:
    response = llm.complete(f"Extract metrics from: {artifacts}")  # FORBIDDEN
    return response
```

✅ Right:
```python
@mcp.tool()
def evaluate(artifacts: str) -> dict:
    match = re.search(r"MFLOPS:\s*([\d.]+)", artifacts)  # deterministic
    return {"MFLOPS": float(match.group(1))} if match else {}
```

### P3: Multi-Objective Evaluation
Never reduce metrics to a single scalar score.
Return the full `metrics` dict and let the LLM judge fitness in context.

### P4: Dependency Injection
Domain knowledge is always passed at runtime, never hardcoded.

## Adding a New Skill

1. Create `ari-skill-yourskill/`:
   ```
   ari-skill-yourskill/
   ├── src/server.py          ← FastMCP server
   ├── tests/test_server.py   ← Tests (min. 3)
   ├── pyproject.toml
   ├── README.md
   └── REQUIREMENTS.md
   ```

2. Implement server:
   ```python
   from mcp.server.fastmcp import FastMCP
   mcp = FastMCP("your-skill")

   @mcp.tool()
   def your_tool(input: str) -> dict:
       """Clear description of what this does."""
       return {"result": process(input)}
   ```

3. Register in BFTS config YAML and `experiment.md`.

4. Add tests — all must pass.

## Adding a Post-BFTS Pipeline Stage

Only edit `config/pipeline.yaml`. No core code changes needed:

```yaml
pipeline:
  - stage: my_new_stage
    skill: ari-skill-yourskill
    tool: your_tool
    enabled: true
```

## Testing

All PRs must keep the full test suite passing:

| Package | Tests |
|---------|-------|
| ari-core | 45 |
| ari-skill-hpc | 27 |
| ari-skill-idea | 9 |
| ari-skill-evaluator | 6 |
| ari-skill-paper-re | 6 |
| ari-skill-memory | 6 |
| **Total** | **99** |

Run all:
```bash
for pkg in ari-core ari-skill-hpc ari-skill-idea ari-skill-evaluator ari-skill-paper-re ari-skill-memory; do
    cd $pkg && pytest tests/ -q && cd ..
done
```

## Code Style

- Python 3.11+
- Type hints on all public functions
- Docstrings on all MCP tools (they appear in the LLM's tool descriptions)
- No Japanese text in any committed file
