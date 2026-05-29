# ari.configs

External config tables for ARI core (Phase PC) — e.g. the LLM model
price table lifted out of `ari.cost_tracker`, and backend/model defaults.

## Contents

- `README.md` — this file.
- `__init__.py` — config-table exports + loader plumbing.
- `_loader.py` — `ConfigLoader` Protocol + `FilesystemConfigLoader`.
- `defaults.yaml` — backend / model defaults.
- `model_prices.yaml` — LLM model price table.

## See also

- **Contents & loading** → the `__init__.py` module docstring (authoritative).
- **Loader contract** → `ari.protocols.ConfigLoader`.
