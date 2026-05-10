"""External config tables for ARI core (Phase PC).

PC1 brings the LLM model price table out of ``ari.cost_tracker``;
later PC PRs add ``defaults.yaml`` for backend / model defaults.
"""

from ari.configs._loader import (  # noqa: F401
    ConfigLoader,
    FilesystemConfigLoader,
    package_configs_root,
)
