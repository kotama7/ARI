# scripts/git-hooks

Version-controlled git hooks. Enable with `git config core.hooksPath scripts/git-hooks`.

## Contents

- `README.md` — this file.
- `pre-commit` — run `readme_sync.py --write` and re-stage modified tracked READMEs (no LLM/API; non-blocking).
