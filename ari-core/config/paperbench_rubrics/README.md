# PaperBench rubric templates

Venue-conditioned PaperBench-format rubric templates. Mirrors
`ari-core/config/reviewer_rubrics/` (peer-review) so the same
`venue → YAML → prompt override` flow used by `ari-skill-paper`'s
`review_engine` is available for `ari-skill-replicate`'s rubric generator.

`ari-skill-replicate/src/generator.py::generate_rubric_async` takes an
optional `paperbench_rubric_id` argument. When supplied, the loader
searches the directories below (first match wins) for `<id>.yaml`:

  1. `$ARI_PAPERBENCH_RUBRIC_DIR` (env override)
  2. `<cwd>/ari-core/config/paperbench_rubrics/`
  3. `<cwd>/config/paperbench_rubrics/`
  4. Repo-relative fallback (this directory)

## `mode`

* `agent_benchmark` — the original PaperBench framing. Direct children
  decompose by scientific structure (one child per contribution or
  experiment). Leaves grade whether a submission's `reproduce.sh`
  output matches the paper. This is the default when no template is
  supplied; `generic.yaml` declares it explicitly.

* `paper_audit` — flips the framing. Direct children are a **fixed set
  of audit axes** declared in `top_level_axes`. Leaves grade whether
  the paper text (and AD/AE Appendix when supplied) describes enough
  to reproduce, without running a submission. Used for HPC paper
  reproducibility audits per `HPC PaperBench audit research plan` §5 Step 3.

## `top_level_axes` (paper_audit only)

When `mode: paper_audit`, this list becomes the rubric root's direct
children verbatim. The downstream subtree pass populates each axis
with paper-audit YES/NO leaves shaped by `prompt_overrides.leaf_style`.

## `prompt_overrides`

* `system_hint`: prepended to the skeleton prompt as a venue-specific
  framing block. Mirrors `ari-skill-paper`'s `system_hint` for peer
  review.
* `leaf_style`: forwarded to the subtree pass so leaves match the
  venue's grading idiom (paper-audit questions, agent benchmark
  commands, etc.).

## Adding a new venue

1. Copy `generic.yaml` or `sc.yaml` and rename to `<venue_id>.yaml`.
2. Edit `id`, `venue`, `domain`, `mode`, and the `top_level_axes` /
   `prompt_overrides` blocks. No code change is required — the
   generator picks up new files via the search path.
