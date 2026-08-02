"""Credential-name classification and value-free manifest scope contract."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ENVIRONMENT_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CREDENTIAL_ENV_RE = re.compile(
    r"(?:^|_)(?:API_?KEY|APIKEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?|"
    r"PRIVATE_KEY|SSH_KEY)(?:$|_)"
)


def looks_like_credential_environment_name(name: str) -> bool:
    """Return whether an environment name requires credential classification."""

    return bool(_CREDENTIAL_ENV_RE.search(name))


class CredentialScopeV1(BaseModel):
    """Named credential authority whose values are never serialized to locks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    required_env: list[str] = Field(default_factory=list)
    optional_env: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"^[a-z0-9][a-z0-9._-]*$", value):
            raise ValueError("credential scope id must be a lowercase dotted identifier")
        return value

    @field_validator("required_env", "optional_env")
    @classmethod
    def _valid_env_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("credential environment variable names must be unique")
        invalid = [value for value in values if not ENVIRONMENT_NAME_RE.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid credential environment names: {invalid}")
        return values

    @model_validator(mode="after")
    def _disjoint_names(self) -> "CredentialScopeV1":
        overlap = sorted(set(self.required_env) & set(self.optional_env))
        if overlap:
            raise ValueError(
                "credential environment variables cannot be required and optional: "
                f"{overlap}"
            )
        return self

    def environment_names(self) -> tuple[str, ...]:
        """Return required then optional credential variable names."""

        return tuple(self.required_env + self.optional_env)


__all__ = [
    "CredentialScopeV1",
    "ENVIRONMENT_NAME_RE",
    "looks_like_credential_environment_name",
]
