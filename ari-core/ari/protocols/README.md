# ari.protocols

Internal Protocols / ABCs describing the structural contract between core
sub-systems (`Evaluator`, `PromptLoader`, `ConfigLoader`, …). Sub-systems
accept these so test stubs and alternatives plug in without subclassing.

## Contents

- `README.md` — this file.
- `__init__.py` — currently exposed protocols + roadmap.
- `evaluator.py` — `Evaluator` Protocol.

## See also

- **Currently exposed protocols & roadmap** → the `__init__.py` module docstring (authoritative).
