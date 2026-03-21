
## v0.3.0 (2026-03-21)

### Philosophy
- Removed all domain-specific keywords from production code (`_PERF_KEYWORDS`, `OMP_NUM_THREADS` regex, compiler flag regex)
- Node ranking now uses LLM-assigned `scientific_score` (0.0–1.0) instead of HPC performance keywords
- BFTS expansion prompt passes `scientific_score` to child LLM — LLM autonomously determines how to improve

### Evaluator
- `LLMEvaluator` now acts as peer reviewer: assigns `scientific_score` and `comparison_found`
- LLM decides scoring criteria and weights autonomously (no fixed rubric)
- `_scientific_score` and `_comparison_found` stored in node metrics for BFTS ranking

### Transform Skill (ari-skill-transform)
- Replaced regex-based parameter extraction with LLM-powered full tree analysis
- BFS traversal: all nodes (root → ablation → validation) passed to LLM
- LLM decides what fields to extract (hardware, methodology, findings, etc.)
- `experiment_context` included in `science_data.json` for downstream skills

### Plot Skill (ari-skill-plot)
- Receives full `science_data` including `experiment_context`
- Figure types chosen autonomously by LLM based on available data
- Real metric units from data (no "a.u.")

### Pipeline
- `paper_context` = `experiment_context` (from transform) + `best_nodes_metrics`
- `search_memory` query uses node's own eval_summary (not hardcoded HPC keywords)
- `eval_summary` now includes `scientific_score` for child node context

### Docs
- `architecture.md`: updated data flow, design invariants table
- `PHILOSOPHY.md`: added Zero Domain Knowledge Principle section
- `configuration.md`: updated for `ARI_MAX_NODES`, template variables
- `index.html`: added Analyze step, bumped to v0.3.0
