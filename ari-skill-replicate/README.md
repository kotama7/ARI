# ari-skill-replicate

ORS Auto-Rubric generator and auditor (PaperBench TaskNode-compatible).

## Tools

- `generate_rubric(paper_path, paper_text, output_path, target_leaf_count=0, model="", temperature=0.0, seed=0, two_stage=True)` — produces a PaperBench-compatible rubric (`replication_rubric.schema.json`) from a paper's LaTeX/text. Auto-computes target leaf count from paper length when `target_leaf_count=0`. With `two_stage=True` (default) generates a skeleton then populates each subtree in parallel; produces ~4× more leaves and 1–2 levels more depth than a single LLM call.
- `audit_rubric(rubric_path, paper_path, paper_text, auditor_model)` — flags `vague_qualifier`, `no_paper_evidence`, `duplicate`, and `unverifiable` leaves; recommends regeneration when >20% of leaves are flagged.
- `suggest_target_leaf_count(paper_path, paper_text)` — returns the auto-computed target leaf count (~1 leaf / 75 words, bounded to [50, 400]) and word count for the paper.

## Two-stage generation

The default rubric path is hierarchical (`prompts/skeleton.md` + `prompts/subtree.md`):

1. **Pass 1 — skeleton**: a single LLM call defines the root + direct children (one node per major contribution / experiment / section), and assigns each a `target_subtree_leaves` budget summing to the overall target.
2. **Pass 2 — subtrees (parallel)**: one call per direct child populates its subtree with 4–6 additional levels, scoped to the parent's `requirements`. Concurrency is bounded by an internal semaphore (default 4).
3. **Merge + prune**: subtree roots replace skeleton stubs; leaves whose `quote` or `requirements` violate the schema's `minLength=10` are dropped (a small handful per run is normal).

Single-call mode (`two_stage=False`) preserves the original `prompts/adversarial_reviewer.md` template for cost-sensitive runs (~5× lower API tokens). On a 16K-word reference paper, two-stage produces ~149 leaves at depth 5 vs ~37 leaves at depth 4 for single-call (gpt-5.2, same paper).

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | Generator LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | Auditor LLM (independent from generator) |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (unset) | Override the per-paper target leaf count. `0` / unset → auto from paper length. Set by the GUI Wizard's "Target leaves" field. |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (unset) | Override generator temperature. Set by the GUI Wizard's "Temperature" field. |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (unset) | `1`/`true`/`on` → force two-stage; `0`/`false`/`off` → force single-call. Unset → use the kwarg default (currently `True`). Set by the GUI Wizard's "Two-stage generation" toggle. |

Resolution order (server.py): explicit kwarg → env var → default. The MCP tool is invoked by `ari-core/config/workflow.yaml::ors_generate_rubric`; the workflow does not pass these three knobs explicitly, so env vars set by the GUI Wizard always win over the kwarg defaults at runtime.

## Output schema

See `schemas/replication_rubric.schema.json`. The root rubric is a PaperBench `TaskNode` tree wrapped with frozen provenance metadata (paper sha256, generator model, prompt sha256, optional audit metadata). The downstream consumer is `ari-skill-paper-re.grade_with_simplejudge`, which wraps PaperBench's `SimpleJudge`.
