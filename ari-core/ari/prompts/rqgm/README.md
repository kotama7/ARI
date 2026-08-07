# ari/prompts/rqgm

Committed prompt templates for the ARI-RQGM prompt-defined actors (Tasks 03/06/07).
ProposalRouter generators (docs/plans/ari_rqgm Task 03 §5.3 / §7), the
adversarial evolution loop (Task 06 §5.2 / §7), and the PromptMutator
meta-prompt (Task 07 §5.4 / §7). Loaded via
`FilesystemPromptLoader.load_versioned("rqgm/<name>")`; the returned
`sha256[:12]` is stamped as the record `prompt_hash` and recorded via
`record_prompt_use` (→ `prompt_trace.jsonl`).

Proposal generators (Task 03):

- `proposal_cheap.md` — CheapGenerator: one-shot proposal from goal context.
  Placeholders: `{goal}`, `{idea_context}`.
- `proposal_mutation.md` — MutationGenerator: mutate ONE facet of an existing
  proposal. Placeholders: `{goal}`, `{facet}`, `{parent_summary}`.
- `proposal_prior_art.md` — PriorArtDifferentiationGenerator: differentiate
  against prior-art refs. Placeholders: `{goal}`, `{prior_art_block}`.

All three reply with a single JSON object matching the ProposalSummaryView
field budgets (`ari/schemas/proposal_summary_view.schema.json`).

Adversarial-loop actors (Task 06; all attacks target ARTIFACTS only — the
templates instruct the closed target-type subset each type may use):

- `adversary_overclaim.md`, `adversary_metric_gaming.md`,
  `adversary_prior_art.md`, `adversary_reproducibility.md`,
  `adversary_evidence_gap.md`, `adversary_cost_explosion.md`,
  `adversary_prompt_injection.md` — the seven adversary types (§5.2).
  Placeholders: `{target_block}`, `{evidence_block}`. Reply: one
  RawAttackRecord JSON fragment (`ari/schemas/rqgm_attack_records.schema.json`);
  an empty `attack_claim` declines.
- `defender.md` — one rebut/concede/propose_fix per attack. Placeholders:
  `{attack_block}`, `{artifact_block}`.
- `judge_adjudication.md` — ArtifactJudge verdict
  `valid|partially_valid|invalid` + severity. Placeholders:
  `{attack_block}`, `{defense_block}`, `{evidence_block}`.

PromptMutator (Task 07; meta tier — emits candidates only, never registry
writes):

- `prompt_mutator.md` — the mutation meta-prompt: rewrite one incumbent
  template for a role under the five bounded mutation kinds. Placeholders:
  `{role}`, `{mutation_kind}`, `{incumbent_instruction}`,
  `{failure_summaries_block}`, `{required_constraints_block}`. Reply: the
  full candidate template text only.

CleanRoomPromptGenerator (Task 08; meta tier — one-shot completion, emits
candidates only, never registry writes):

- `clean_room_generator.md` — the clean-room regeneration meta-prompt: write
  a retired role's successor FROM SCRATCH out of the closed
  `CleanRoomInputBundle` only (retired prompt text / few-shots / reasoning
  traces / raw attack text / defense text are forbidden inputs — plan 08
  §5.2). Placeholders: `{target_role}`, `{bundle_json}` (the canonical
  bundle JSON — the ENTIRE remaining context, plan 08 §5.3 Layer A). Reply:
  the full candidate template text only.

Runtime-EVOLVED prompt bodies never live here: they are checkpoint-scoped
(`{ckpt}/rqgm_prompts/<prompt_id>.md`, Task 07 §5.6 Gate 10 carve-out).
These committed files change only through the existing prompt-snapshot
blessing flow (`test_prompt_snapshots.py`, `test_prompt_extraction.py`,
Gate 10).
