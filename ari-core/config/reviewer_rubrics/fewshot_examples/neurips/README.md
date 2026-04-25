# NeurIPS few-shot examples

Few-shot review examples used when the `neurips` / `iclr` / `icml` rubric has
`fewshot_mode: static` and `num_fs_examples > 0`.

## How these files are consumed

`ari_skill_paper.review_engine.load_static_fewshot()` reads this directory:

1. Lists every `*.json` (sorted lexicographically — digit-prefixed files come first).
2. Takes the first `num_fs_examples` entries (default 1, matching The AI Scientist v2).
3. For each JSON, optionally loads a sibling `.txt` / `.md` with the paper excerpt (capped at ~4 KB for prompt budget).
4. Assembles a prompt block `=== EXAMPLE REVIEW #k (paper: <id>) === Paper excerpt: ... Completed review JSON: ... === END EXAMPLES ===` and **prepends** it to the reviewer's user message, before the paper being reviewed.

This matches the v2 pipeline (`perform_llm_review.py: get_review_fewshot_examples`).

The schema of each `.json` should match the target rubric's `score_dimensions` and `text_sections`. Extra fields (`_source`, `_paper`, `Summary`, `Ethical Concerns`, capitalised alternates) are preserved for the LLM's reference but ignored by the normaliser.

## Bundled examples

The three examples below are re-used from the open-source
**[SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2)** project (Apache-2.0) so ARI's reviewer behaves identically to v2 when running with default parameters.

| File | Paper | Venue | Decision | Overall |
|---|---|---|---|---|
| `132_automated_relational.json` | Automated Relational Meta-learning (ICLR 2020 sub #132) | ICLR 2020 | Accept | 7 |
| `2_carpe_diem.json` | Carpe Diem: Recency Bias for Adaptive Mini-Batch Selection | ICLR 2020 | Reject | 4 |
| `attention.json` | Attention Is All You Need (Vaswani et al.) | NeurIPS 2017 | Accept | 8 |

With `num_fs_examples=1` (NeurIPS rubric default), `132_automated_relational.json` is used first — matching v2's ordering.

## Adding your own examples

1. Create `<id>.json` with fields matching the rubric schema (`soundness`, `presentation`, `contribution`, `overall`, `confidence`, `strengths`, `weaknesses`, `questions`, `limitations`, `decision`).
2. Optional: `<id>.txt` with a plain-text excerpt of the paper (first 4–8 KB is plenty).
3. Optional: `<id>.pdf` for provenance (not read directly at inference time).
4. Add a corresponding entry in `scripts/fewshot/manifest.yaml` so `sync.py` can refresh it.

### Automated fetching

```bash
# Fetch the v2 samples into this directory (uses public GitHub URLs, Apache-2.0):
python scripts/fewshot/sync.py --venue neurips
```

## Licensing

The three v2-derived JSON files above are redistributed under Apache-2.0 with attribution in each file's `_source` field. Delete them and re-run `sync.py` at any time.
