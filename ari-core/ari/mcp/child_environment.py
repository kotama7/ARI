"""Minimal child-process environment and value-free credential authority.

The MCP SDK adds a small parent-environment baseline even when callers provide
``StdioServerParameters.env``.  This module therefore supplies explicit safe
overrides for that baseline as well as the manifest allowlist.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, TextIO

from ari.config import SkillConfig
from ari.skill_manifest import looks_like_credential_environment_name


SAFE_INHERITED_ENV_NAMES = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TMPDIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
MANAGED_CHILD_ENV_NAMES = frozenset(
    {
        "HOME",
        "BASH_ENV",
        "CDPATH",
        "ENV",
        "LD_PRELOAD",
        "LOGNAME",
        "USER",
        "SHELL",
        "TERM",
        "PYTHONPATH",
        "PYTHONIOENCODING",
        "PYTHONBREAKPOINT",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONNOUSERSITE",
        "PYTHONSTARTUP",
        "PYTHONUNBUFFERED",
        "PYTHONUTF8",
        "PYTHONWARNINGS",
        "VIRTUAL_ENV",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
    }
)


class ChildEnvironmentError(RuntimeError):
    """Base class for manifest/environment admission failures."""


class MissingRequiredEnvironmentError(ChildEnvironmentError):
    """Raised when a required ordinary or credential variable is unavailable."""


class UnclassifiedCredentialError(ChildEnvironmentError):
    """Raised when a complete policy lists a probable secret as ordinary env."""


class ManagedEnvironmentOverrideError(ChildEnvironmentError):
    """Raised when a manifest attempts to override core-owned isolation names."""


class CredentialScopeDriftError(ChildEnvironmentError):
    """Raised when reconnect would change the run's credential authority."""


class SecretRedactor:
    """Redact known credential values from text and structured MCP responses."""

    def __init__(self, replacements: Mapping[str, str] | None = None) -> None:
        pairs: list[tuple[str, str]] = []
        for value, marker in (replacements or {}).items():
            if not value:
                continue
            pairs.append((value, marker))
            escaped = json.dumps(value, ensure_ascii=False)[1:-1]
            if escaped != value:
                pairs.append((escaped, marker))
        self._pairs = tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))

    def text(self, value: str) -> str:
        rendered = value
        for secret, marker in self._pairs:
            rendered = rendered.replace(secret, marker)
        return rendered

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.value(item) for item in value)
        return value


class SecretRedactingPipe:
    """Pipe child stderr through value redaction before it reaches a log sink.

    Subprocess launchers consume a stream's file descriptor directly, so a
    ``TextIOBase.write`` wrapper alone cannot intercept child output.  This
    class gives the child a private pipe descriptor and drains the other end on
    a thread, redacting complete lines before forwarding them.
    """

    def __init__(self, target: TextIO, redactor: SecretRedactor) -> None:
        read_fd, write_fd = os.pipe()
        self._reader = os.fdopen(
            read_fd,
            "r",
            encoding="utf-8",
            errors="replace",
        )
        self.child_writer = os.fdopen(
            write_fd,
            "w",
            encoding="utf-8",
            errors="replace",
        )
        self._target = target
        self._redactor = redactor
        self._thread = threading.Thread(
            target=self._drain,
            name="ari-mcp-redacted-stderr",
            daemon=True,
        )
        self._thread.start()

    def _drain(self) -> None:
        try:
            with self._reader:
                for line in self._reader:
                    try:
                        self._target.write(self._redactor.text(line))
                        self._target.flush()
                    except (OSError, ValueError):
                        return
        except (OSError, ValueError):
            return

    def close_parent_writer(self) -> None:
        """Close the launcher's copy after the subprocess inherits the fd."""

        if not self.child_writer.closed:
            self.child_writer.close()

    def close(self) -> None:
        self.close_parent_writer()
        self._thread.join(timeout=5)


@dataclass(frozen=True)
class ChildEnvironment:
    """Resolved environment plus non-secret scope identities and redaction."""

    values: dict[str, str]
    inherited_names: tuple[str, ...]
    credential_env_names: tuple[str, ...]
    credential_scope_identities: tuple[dict[str, Any], ...]
    redactor: SecretRedactor

    @property
    def active_credential_scope_ids(self) -> tuple[str, ...]:
        return tuple(
            identity["scope_id"]
            for identity in self.credential_scope_identities
            if identity["present_env"]
        )

    def transport_values(self) -> dict[str, str]:
        """Return non-credential values safe to serialize to a local shim."""

        credential_names = set(self.credential_env_names)
        return {
            name: value
            for name, value in self.values.items()
            if name not in credential_names
        }


def _identity_digest(scope_id: str, present_env: list[str]) -> str:
    payload = json.dumps(
        {"scope_id": scope_id, "present_env": sorted(present_env)},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _runtime_root(skill: SkillConfig, parent: Mapping[str, str]) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", skill.name).strip("._-")
    if not safe_name:
        safe_name = hashlib.sha256(skill.name.encode("utf-8")).hexdigest()[:16]
    checkpoint = str(parent.get("ARI_CHECKPOINT_DIR") or "").strip()
    if checkpoint:
        return Path(checkpoint) / ".ari" / "skill-runtime" / safe_name
    uid = str(os.getuid()) if hasattr(os, "getuid") else "user"
    return Path(tempfile.gettempdir()) / "ari-skill-runtime" / uid / safe_name


def _prepare_runtime_dirs(skill: SkillConfig, parent: Mapping[str, str]) -> dict[str, str]:
    root = _runtime_root(skill, parent)
    directories = {
        "HOME": root / "home",
        "XDG_CACHE_HOME": root / "cache",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_STATE_HOME": root / "state",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return {name: str(path) for name, path in directories.items()}


def _scope_entries(skill: SkillConfig) -> list[tuple[str, list[str], list[str]]]:
    entries: list[tuple[str, list[str], list[str]]] = []
    for scope_id, declaration in sorted(skill.credential_scopes.items()):
        entries.append(
            (
                scope_id,
                list(declaration.get("required_env") or []),
                list(declaration.get("optional_env") or []),
            )
        )
    return entries


def build_child_environment(
    skill: SkillConfig,
    *,
    skill_path: Path,
    ari_core_root: Path,
    parent_env: Mapping[str, str] | None = None,
) -> ChildEnvironment:
    """Resolve one fail-closed child environment from manifest declarations."""

    parent = parent_env if parent_env is not None else os.environ
    declared_ordinary = set(skill.required_env) | set(skill.optional_env)
    managed = sorted(declared_ordinary & MANAGED_CHILD_ENV_NAMES)
    if managed:
        raise ManagedEnvironmentOverrideError(
            f"Skill '{skill.name}' cannot override managed environment names: {managed}"
        )
    if skill.environment_policy == "complete":
        unclassified = sorted(
            name
            for name in declared_ordinary
            if looks_like_credential_environment_name(name)
        )
        if unclassified:
            raise UnclassifiedCredentialError(
                f"Skill '{skill.name}' must classify credential-like env names: "
                f"{unclassified}"
            )

    missing = sorted(
        name for name in skill.required_env if not str(parent.get(name) or "")
    )
    scope_entries = _scope_entries(skill)
    missing.extend(
        name
        for _scope_id, required, _optional in scope_entries
        for name in required
        if not str(parent.get(name) or "")
    )
    if missing:
        raise MissingRequiredEnvironmentError(
            f"Skill '{skill.name}' is missing required environment names: "
            f"{sorted(set(missing))}"
        )

    inherited = {
        name
        for name in SAFE_INHERITED_ENV_NAMES
        if parent.get(name) is not None
    }
    values: dict[str, str] = {
        name: str(parent[name])
        for name in inherited
    }
    values.setdefault("PATH", os.defpath)
    values.setdefault("LANG", "C.UTF-8")
    values.update(_prepare_runtime_dirs(skill, parent))
    values.update(
        {
            "LOGNAME": "ari-skill",
            "USER": "ari-skill",
            "SHELL": "/bin/sh",
            "TERM": "dumb",
            "BASH_ENV": "",
            "CDPATH": "",
            "ENV": "",
            "LD_PRELOAD": "",
            "PYTHONPATH": os.pathsep.join([str(skill_path), str(ari_core_root)]),
            "PYTHONBREAKPOINT": "0",
            "PYTHONHOME": "",
            "PYTHONINSPECT": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSTARTUP": "",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONWARNINGS": "default",
            "VIRTUAL_ENV": "",
        }
    )
    for name in sorted(declared_ordinary):
        if parent.get(name) is not None:
            values[name] = str(parent[name])

    credential_names: set[str] = set()
    identities: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    for scope_id, required, optional in scope_entries:
        declared = sorted(set(required) | set(optional))
        present = [name for name in declared if str(parent.get(name) or "")]
        credential_names.update(present)
        for name in present:
            value = str(parent[name])
            values[name] = value
            replacements[value] = f"<redacted:{scope_id}>"
        identities.append(
            {
                "scope_id": scope_id,
                "declared_env": declared,
                "present_env": present,
                "identity_digest": _identity_digest(scope_id, present),
            }
        )

    return ChildEnvironment(
        values=values,
        inherited_names=tuple(sorted(inherited)),
        credential_env_names=tuple(sorted(credential_names)),
        credential_scope_identities=tuple(identities),
        redactor=SecretRedactor(replacements),
    )


__all__ = [
    "SAFE_INHERITED_ENV_NAMES",
    "MANAGED_CHILD_ENV_NAMES",
    "ChildEnvironment",
    "ChildEnvironmentError",
    "CredentialScopeDriftError",
    "ManagedEnvironmentOverrideError",
    "MissingRequiredEnvironmentError",
    "SecretRedactingPipe",
    "SecretRedactor",
    "UnclassifiedCredentialError",
    "build_child_environment",
]
