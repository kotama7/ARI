# ari-skill-paper/src/prompts

Supported whole-document prompts, loaded byte-identically by `_load_prompt`:

- `fill_in_writer.md` — fills the venue scaffold and emits claim declarations.
- `paper_writer.md` — bounded whole-document reflection.
- `global_coherence.md` — anchor-preserving targeted refinement edits.
- `forward_declaration.md` — deterministic claim/formula declaration guidance
  appended to verified experiment context.

The removed per-section reviewer and model figure-inserter prompts are not
retained as runtime fallbacks.
