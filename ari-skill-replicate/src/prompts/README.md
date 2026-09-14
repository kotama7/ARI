# ari-skill-replicate/src/prompts

Prompt templates for rubric generation and auditing. Markdown files with
single-brace `{name}` placeholders filled via Python `str.format`.

## Contents

- `README.md` — this file.
- `rubric_audit.md` — flag leaf-quality issues.
- `skeleton.md` — Pass 1: define the rubric root + direct children.
- `subtree.md` — Pass 2: populate each direct child's subtree with leaves.
