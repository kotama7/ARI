# ari.agent.shims

Executable shims prepended to `PATH` inside the reproducibility sandbox
(wired by `ari.agent.react_driver` as `PATH=<sandbox>/.shims:<orig>`).

## Contents

- `README.md` — this file.
- `git.sh` — intercepts only `git clone` of the paper's ref; other git passes through.

## See also

- Not a Python package (no `__init__.py`); files here are shell scripts.
