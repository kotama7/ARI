# ari-skill-replicate/src

MCP server package for the replicate skill — generates and audits
PaperBench-format auto-rubrics (TaskNode-compatible) from a paper's text.

## Contents

- `README.md` — this file.
- `__init__.py` — package marker.
- `auditor.py` — leaf-quality flags.
- `categories.py` — PaperBench category allow-lists.
- `generator.py` — paper text → rubric envelope.
- `manifest.py` — sha256 freezing + PaperBench format conversion.
- `rubric_template.py` — venue-conditioned rubric template loader.
- `server.py` — MCP entry point (`generate_rubric`, `audit_rubric`, `suggest_target_leaf_count`).
- `prompts/` — LLM prompt templates.
  - `README.md` — prompts index.
  - `adversarial_reviewer.md` — adversarial review pass.
  - `rubric_audit.md` — flag leaf-quality issues.
  - `skeleton.md` — Pass 1: define the rubric root + direct children.
  - `subtree.md` — Pass 2: populate each direct child's subtree with leaves.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & two-stage generation flow.
