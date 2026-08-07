"""Server-side model/provider catalog for ``/api/v1/config/catalogs/models``
(gui_refresh task 06 Wave 4d; plan 05 §Configuration API, ADR-05).

Plan 06 §Schema-driven rendering: frontend model/provider constants are
replaced by a server catalog.  The suggestion list itself stays single-source
with the legacy ``GET /api/models`` endpoint — this module re-serves the
exact ``ari.viz.checkpoint_api._api_models`` payload (never a fork) and adds
one field the Studio needs: the provider's API-key env name, so the
SecretField can target ``PUT /api/v1/secrets/{env_key}`` without a frontend
provider->key constant.

:data:`PROVIDER_ENV_KEYS` is a literal transcription of the provider map in
``ari.viz.api_settings._api_save_settings`` (openai/anthropic/gemini); it is
pinned against :data:`ari.viz.v1.secrets.SECRET_NAMES` by
``tests/test_gui_v1_secret_put_and_catalogs.py`` so a divergence between the
catalog and the secret allowlist cannot ship silently.  Providers without an
API-key env var (ollama, cli-shim) carry ``env_key: None`` — an honest
"keyless" marker, not an empty string.
"""

from __future__ import annotations

from .dto import ModelCatalogV1, ModelProviderV1

# provider id -> the env-var name its API key lives under (the exact map of
# api_settings._api_save_settings; every value is a SECRET_NAMES member).
PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


def get_model_catalog() -> ModelCatalogV1:
    """The legacy static provider/model suggestions + per-provider env key.

    Local import keeps ``checkpoint_api`` (and its ``viz.state`` pull) inert
    until this endpoint is actually dispatched — the same deferral pattern as
    the config CRUD handlers.
    """
    from ..checkpoint_api import _api_models

    providers = [
        ModelProviderV1(
            id=p["id"],
            name=p["name"],
            models=list(p["models"]),
            env_key=PROVIDER_ENV_KEYS.get(p["id"]),
        )
        for p in _api_models()["providers"]
    ]
    return ModelCatalogV1(providers=providers)
