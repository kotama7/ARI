"""Secret READINESS + write-only assignment for ``/api/v1/secrets/*``.

ADR-11 / RR-P0-2 / plan 09 §Secret policy: the GUI may learn WHETHER a known
secret is configured — never its value. This module answers, for a fixed
allowlist of secret names, ``configured`` + ``source_class`` + ``last_updated``
by walking the same .env chain as the legacy harvest
(:func:`ari.viz.api_settings._env_chain` — shared so the two endpoints can
never disagree about which file wins) plus the ``os.environ`` fallback.

The readiness read path (Wave 3a) is read-only by construction: no file
writes, no ``os.environ`` writes, no ``viz.state`` mutation (same discipline
as :mod:`ari.viz.v1.queries`).

Wave 4d (task 06, ADR-05) adds the canonical WRITE side:
``PUT /api/v1/secrets/{secret_id}`` (:func:`put_secret`) — write-only value
assignment restricted to the same :data:`SECRET_NAMES` allowlist, delegating
the actual write to the hardened legacy path
(:func:`ari.viz.api_settings._upsert_env_key`: atomic same-dir tmp + fsync +
``os.replace``, owner-only 0o600, live ``os.environ`` export) so the two
write endpoints can never diverge.  The response is READINESS-shaped
(:class:`ari.viz.v1.dto.SecretUpdatedV1`) — the value is structurally
impossible to echo.

``SECRET_NAMES`` is enumerated from code, not invented:

- ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` / ``GOOGLE_API_KEY`` /
  ``GEMINI_API_KEY`` — the exact ``os.environ`` fallback list of
  ``api_settings._api_get_env_keys`` and the provider map of
  ``_api_save_settings``;
- ``SEMANTIC_SCHOLAR_API_KEY`` — the retrieval backend key the settings card
  collects (``semantic_scholar_key``);
- ``LETTA_API_KEY`` — the memory (Letta) card;
- ``ZENODO_TOKEN`` — ``ari.publish.backends.zenodo`` auth;
- ``ARI_REGISTRY_TOKEN`` — ``ari.publish.backends.ari_registry`` /
  ``ari.clone.resolvers.ari`` auth.

Additions are additive contract changes: extend the tuple, regenerate
``openapi.json`` is NOT needed (the list is data, not schema), but update
``tests/test_gui_secret_readiness.py``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..api_settings import _env_chain
from .dto import SecretStatusV1, SecretUpdatedV1, SecretV1
from .errors import error_response

# ADR-11 allowlist — the ONLY names the readiness endpoint reports on.
SECRET_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "LETTA_API_KEY",
    "ZENODO_TOKEN",
    "ARI_REGISTRY_TOKEN",
)


def _mtime_utc(path: Path) -> str | None:
    """File mtime as ``YYYY-MM-DDTHH:MM:SSZ`` (same convention as
    ``RunSummaryV1.mtime_utc``); ``None`` when the stat fails."""
    try:
        ts = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _harvest_env_files() -> dict[str, tuple[str, Path, str]]:
    """First-occurrence-wins harvest of the .env chain.

    Returns ``{name: (value, env_path, source_class)}`` using the exact
    line-parsing rules of the legacy ``_api_get_env_keys`` (strip, skip
    comments/blank lines, ``partition('=')``, strip quotes) so readiness and
    the legacy endpoint always agree on which definition wins.
    """
    found: dict[str, tuple[str, Path, str]] = {}
    for env_path, source_class in _env_chain():
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k in SECRET_NAMES and k not in found:
                found[k] = (v, env_path, source_class)
    return found


def get_secrets_status() -> SecretStatusV1:
    """Readiness for every allowlisted secret name, in ``SECRET_NAMES`` order.

    ``configured`` is True only for a non-empty value. A name whose first
    .env occurrence is EMPTY reports ``configured=False`` with its source —
    mirroring the legacy first-occurrence-wins semantics (an empty project
    definition shadows a later repo/user one). Names absent from every .env
    fall back to ``os.environ`` (``process_env``, ``last_updated`` None).
    """
    harvested = _harvest_env_files()
    secrets: list[SecretV1] = []
    for name in SECRET_NAMES:
        if name in harvested:
            value, env_path, source_class = harvested[name]
            secrets.append(
                SecretV1(
                    name=name,
                    configured=bool(value),
                    source_class=source_class,  # type: ignore[arg-type]
                    last_updated=_mtime_utc(env_path),
                )
            )
        elif os.environ.get(name):
            secrets.append(
                SecretV1(
                    name=name,
                    configured=True,
                    source_class="process_env",
                    last_updated=None,
                )
            )
        else:
            secrets.append(
                SecretV1(
                    name=name,
                    configured=False,
                    source_class=None,
                    last_updated=None,
                )
            )
    return SecretStatusV1(secrets=secrets)


# ── write-only assignment (gui_refresh task 06 Wave 4d, ADR-05) ────────────


def _bad_value(message: str) -> dict:
    return error_response("invalid_request", message, request_id="", status=400)


def put_secret(secret_id: str, body: dict) -> dict:
    """PUT /api/v1/secrets/{secret_id} — assign one allowlisted secret.

    Contract (plan 05 §Configuration API, ADR-05):

    - ``secret_id`` must be a :data:`SECRET_NAMES` member — anything else is
      a 404 (the allowlist is the resource space; no probe can create names);
    - body is exactly ``{"value": "<non-empty string>"}``; the value is
      stripped like the legacy env-key editor, must be non-empty after the
      strip, and must carry no newline/control characters (the .env format
      is line-based — same injection guard class as the legacy POST's name
      check, applied to the value the canonical API actually writes);
    - the write delegates to the hardened legacy upsert
      (:func:`ari.viz.api_settings._upsert_env_key`, ``quote=True`` — the
      env-key editor's on-disk form), so atomicity/0o600/live-export
      behavior is single-source;
    - the response is the post-write READINESS row only
      (:class:`SecretUpdatedV1`) — never the value.
    """
    if secret_id not in SECRET_NAMES:
        return error_response(
            "not_found",
            f"unknown secret: {secret_id} (allowlist: {list(SECRET_NAMES)})",
            request_id="",
            status=404,
        )
    unknown = sorted(set(body) - {"value"})
    if unknown:
        return _bad_value(f"unknown request body keys: {unknown}")
    if "value" not in body:
        return _bad_value('"value" is required')
    raw = body["value"]
    if not isinstance(raw, str):
        return _bad_value('"value" must be a string')
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return _bad_value(
            '"value" must not contain newline or control characters '
            "(.env files are line-based)"
        )
    value = raw.strip()
    if not value:
        return _bad_value('"value" must be a non-empty string')
    # Local import: the write helper pulls in viz.state; keep this module
    # import-light until a mutation is actually dispatched.
    from ..api_settings import _upsert_env_key

    _upsert_env_key(secret_id, value, quote=True)
    status = get_secrets_status()
    secret = next(s for s in status.secrets if s.name == secret_id)
    return SecretUpdatedV1(secret=secret).model_dump()
