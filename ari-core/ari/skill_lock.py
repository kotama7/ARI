"""Run-level immutable snapshot for admitted MCP Skills and live tool schemas.

``skill.yaml`` describes a provider before launch.  ``SKILLS.lock`` binds that
declaration to the schemas returned by the live MCP ``tools/list`` handshake and
to the phase-specific set that ARI actually admits for one run.  A checkpoint
therefore cannot silently resume with a different provider, policy, or schema.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ari.config import SkillConfig
from ari.mcp.dispatch_support import normalize_phases, phase_is_disabled, phase_matches


SKILLS_LOCK_FILENAME = "SKILLS.lock"
SKILLS_LOCK_SCHEMA_VERSION = "ari.skills-lock/v1"
DEFAULT_RUNTIME_PHASES = (
    "bfts",
    "control",
    "evaluation",
    "paper",
    "pipeline",
    "reproduce",
)


class SkillLockError(RuntimeError):
    """Base class for lock creation, validation, and reconciliation failures."""


class SkillLockCorruptError(SkillLockError):
    """Raised when an existing ``SKILLS.lock`` is malformed or self-inconsistent."""


class SkillLockMismatchError(SkillLockError):
    """Raised when live admission differs from the run's immutable snapshot."""


class SkillLockMissingError(SkillLockError):
    """Raised when a subset worker requires a run lock that does not exist."""


class SkillProviderAdmissionError(SkillLockError):
    """Raised when a provider required by a locked run cannot be discovered."""


class LockedToolV1(BaseModel):
    """One live MCP tool bound to its provider, policy, and exact JSON Schemas."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_ref: str
    name: str
    skill_name: str
    capability_ref: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    input_schema_digest: str
    output_schema_digest: str
    policy: dict[str, Any] = Field(default_factory=dict)


class LockedSkillV1(BaseModel):
    """One configured provider and the digest of its admitted live surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    package: str
    version: str
    entrypoint: str
    manifest_digest: str
    provider_digest: str
    configured_phases: list[str]
    environment_policy: Literal["audit-pending", "complete"]
    required_env: list[str] = Field(default_factory=list)
    optional_env: list[str] = Field(default_factory=list)
    tool_refs: list[str] = Field(default_factory=list)


class SkillsLockV1(BaseModel):
    """Canonical, deterministic run snapshot persisted as ``SKILLS.lock``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.skills-lock/v1"] = SKILLS_LOCK_SCHEMA_VERSION
    run_id: str
    registry_digest: str
    skills: list[LockedSkillV1]
    tools: list[LockedToolV1]
    disabled_tools: list[str] = Field(default_factory=list)
    phase_active_tools: dict[str, list[str]]

    @model_validator(mode="after")
    def _internally_consistent(self) -> "SkillsLockV1":
        tool_refs = [tool.tool_ref for tool in self.tools]
        if len(tool_refs) != len(set(tool_refs)):
            raise ValueError("SKILLS.lock contains duplicate tool_ref values")
        known = set(tool_refs)
        for phase, refs in self.phase_active_tools.items():
            unknown = sorted(set(refs) - known)
            if unknown:
                raise ValueError(
                    f"phase {phase!r} refers to unknown tool_ref values: {unknown}"
                )
        return self


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _registry_payload(lock: SkillsLockV1 | dict[str, Any]) -> dict[str, Any]:
    if isinstance(lock, SkillsLockV1):
        payload = lock.model_dump(mode="json")
    else:
        payload = dict(lock)
    payload.pop("registry_digest", None)
    return payload


def skills_lock_digest(lock: SkillsLockV1) -> str:
    """Recompute the self-authenticating digest for a lock document."""

    return _json_digest(_registry_payload(lock))


def _normalized_tool(raw: dict[str, Any]) -> dict[str, Any]:
    """Copy only stable live-discovery fields into a lock-safe structure."""

    return {
        "tool_ref": str(raw["tool_ref"]),
        "name": str(raw["name"]),
        "skill_name": str(raw["skill_name"]),
        "capability_ref": (
            str(raw["capability_ref"]) if raw.get("capability_ref") else None
        ),
        "input_schema": raw.get("inputSchema") or {},
        "output_schema": raw.get("outputSchema") or {},
        "policy": raw.get("policy") or {},
    }


def build_skills_lock(
    *,
    run_id: str,
    skills: list[SkillConfig],
    tools: list[dict[str, Any]],
    disabled_tools: set[str] | list[str] | tuple[str, ...] = (),
    runtime_phases: tuple[str, ...] = DEFAULT_RUNTIME_PHASES,
) -> SkillsLockV1:
    """Build a byte-stable lock from configured providers and live discovery."""

    normalized = [_normalized_tool(tool) for tool in tools]
    locked_tools = [
        LockedToolV1(
            **tool,
            input_schema_digest=_json_digest(tool["input_schema"]),
            output_schema_digest=_json_digest(tool["output_schema"]),
        )
        for tool in normalized
    ]
    locked_tools.sort(key=lambda item: item.tool_ref)

    tools_by_skill: dict[str, list[LockedToolV1]] = {}
    for tool in locked_tools:
        tools_by_skill.setdefault(tool.skill_name, []).append(tool)

    enabled_skills = [
        skill
        for skill in skills
        if not phase_is_disabled(getattr(skill, "phase", "all"))
    ]
    locked_skills: list[LockedSkillV1] = []
    for skill in enabled_skills:
        owned = tools_by_skill.get(skill.name, [])
        provider_payload = {
            "name": skill.name,
            "package": skill.package or skill.name,
            "version": skill.version,
            "entrypoint": skill.entrypoint,
            "manifest_digest": skill.manifest_digest,
            "configured_phases": sorted(normalize_phases(skill.phase)),
            "tools": [
                {
                    "tool_ref": tool.tool_ref,
                    "input_schema_digest": tool.input_schema_digest,
                    "output_schema_digest": tool.output_schema_digest,
                    "policy": tool.policy,
                }
                for tool in owned
            ],
        }
        locked_skills.append(
            LockedSkillV1(
                name=skill.name,
                package=skill.package or skill.name,
                version=skill.version,
                entrypoint=skill.entrypoint,
                manifest_digest=skill.manifest_digest,
                provider_digest=_json_digest(provider_payload),
                configured_phases=sorted(normalize_phases(skill.phase)),
                environment_policy=skill.environment_policy,
                required_env=sorted(skill.required_env),
                optional_env=sorted(skill.optional_env),
                tool_refs=sorted(tool.tool_ref for tool in owned),
            )
        )
    locked_skills.sort(key=lambda item: (item.package, item.name))

    disabled = set(disabled_tools)
    phase_names = set(runtime_phases)
    for skill in enabled_skills:
        phase_names.update(normalize_phases(skill.phase))
    for tool in locked_tools:
        policy_phases = tool.policy.get("phases", ["all"])
        phase_names.update(normalize_phases(policy_phases))
    phase_names.difference_update({"", "all", "none"})

    skill_by_name = {skill.name: skill for skill in enabled_skills}
    active: dict[str, list[str]] = {}
    for phase in sorted(phase_names):
        admitted: list[str] = []
        for tool in locked_tools:
            skill = skill_by_name.get(tool.skill_name)
            if skill is None or not phase_matches(skill.phase, phase):
                continue
            tool_phases = tool.policy.get("phases", ["all"])
            if not phase_matches(normalize_phases(tool_phases), phase):
                continue
            if tool.name in disabled or tool.tool_ref in disabled:
                continue
            admitted.append(tool.tool_ref)
        active[phase] = sorted(admitted)

    provisional: dict[str, Any] = {
        "schema_version": SKILLS_LOCK_SCHEMA_VERSION,
        "run_id": run_id,
        "registry_digest": "",
        "skills": [skill.model_dump(mode="json") for skill in locked_skills],
        "tools": [tool.model_dump(mode="json") for tool in locked_tools],
        "disabled_tools": sorted(disabled),
        "phase_active_tools": active,
    }
    provisional["registry_digest"] = _json_digest(_registry_payload(provisional))
    return SkillsLockV1.model_validate(provisional)


def load_skills_lock(path: str | Path) -> SkillsLockV1:
    """Read and fully validate an existing lock, including its digest."""

    lock_path = Path(path)
    if lock_path.is_symlink():
        raise SkillLockCorruptError(f"invalid {lock_path}: symbolic links are refused")
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        lock = SkillsLockV1.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise SkillLockCorruptError(f"invalid {lock_path}: {exc}") from exc
    actual = skills_lock_digest(lock)
    if actual != lock.registry_digest:
        raise SkillLockCorruptError(
            f"invalid {lock_path}: registry_digest is {lock.registry_digest}, "
            f"recomputed {actual}"
        )
    return lock


def _mismatch_summary(expected: SkillsLockV1, current: SkillsLockV1) -> str:
    expected_refs = {tool.tool_ref for tool in expected.tools}
    current_refs = {tool.tool_ref for tool in current.tools}
    parts = [
        f"locked digest {expected.registry_digest}",
        f"live digest {current.registry_digest}",
    ]
    added = sorted(current_refs - expected_refs)
    removed = sorted(expected_refs - current_refs)
    if added:
        parts.append(f"added tool refs: {added}")
    if removed:
        parts.append(f"removed tool refs: {removed}")
    if expected.disabled_tools != current.disabled_tools:
        parts.append("disabled tool policy changed")
    if expected.phase_active_tools != current.phase_active_tools:
        parts.append("phase active sets changed")
    return "; ".join(parts)


def write_or_verify_skills_lock(
    path: str | Path,
    current: SkillsLockV1,
) -> SkillsLockV1:
    """Atomically create a run lock, or require exact equality when it exists."""

    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        current.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{SKILLS_LOCK_FILENAME}.",
        dir=lock_path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    descriptor_owned = True
    try:
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        descriptor_owned = False  # ``handle`` now owns and closes the descriptor.
        with handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard link publishes a fully-written inode without replacing an
            # existing snapshot. Concurrent creators either win this operation
            # or verify the winner; no reader can observe a partial document.
            os.link(temporary_path, lock_path)
        except FileExistsError:
            existing = load_skills_lock(lock_path)
            if existing != current:
                raise SkillLockMismatchError(
                    f"live MCP registry does not match immutable {lock_path}: "
                    f"{_mismatch_summary(existing, current)}"
                )
            return existing
    finally:
        if descriptor_owned:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary_path.unlink()
        except OSError:
            pass
    return current


def verify_skills_lock_subset(
    path: str | Path,
    current: SkillsLockV1,
) -> SkillsLockV1:
    """Verify a single-provider worker against an already-created full run lock.

    Pipeline stages intentionally launch only their owning Skill.  Such a worker
    may validate its provider and tools as an exact subset, but it may never mint
    the authoritative run snapshot or change run-wide disabled/phase policy.
    """

    lock_path = Path(path)
    if not lock_path.is_file():
        raise SkillLockMissingError(
            f"subset MCP worker requires existing immutable {lock_path}"
        )
    if not current.skills:
        raise SkillLockMismatchError(
            f"subset MCP worker discovered no configured provider for {lock_path}"
        )
    expected = load_skills_lock(lock_path)
    if current.run_id != expected.run_id:
        raise SkillLockMismatchError(
            f"subset MCP registry run_id {current.run_id!r} does not match "
            f"{expected.run_id!r} in {lock_path}"
        )
    if current.disabled_tools != expected.disabled_tools:
        raise SkillLockMismatchError(
            f"subset MCP registry disabled-tool policy does not match {lock_path}"
        )

    expected_skills = {skill.name: skill for skill in expected.skills}
    for skill in current.skills:
        if expected_skills.get(skill.name) != skill:
            raise SkillLockMismatchError(
                f"subset MCP provider {skill.name!r} does not match {lock_path}"
            )
    expected_tools = {tool.tool_ref: tool for tool in expected.tools}
    for tool in current.tools:
        if expected_tools.get(tool.tool_ref) != tool:
            raise SkillLockMismatchError(
                f"subset MCP tool {tool.tool_ref!r} does not match {lock_path}"
            )

    current_refs = {tool.tool_ref for tool in current.tools}
    for phase, refs in current.phase_active_tools.items():
        locked_subset = sorted(
            ref for ref in expected.phase_active_tools.get(phase, []) if ref in current_refs
        )
        if refs != locked_subset:
            raise SkillLockMismatchError(
                f"subset MCP phase {phase!r} active set does not match {lock_path}"
            )
    return expected


__all__ = [
    "DEFAULT_RUNTIME_PHASES",
    "SKILLS_LOCK_FILENAME",
    "SKILLS_LOCK_SCHEMA_VERSION",
    "LockedSkillV1",
    "LockedToolV1",
    "SkillLockCorruptError",
    "SkillLockError",
    "SkillLockMismatchError",
    "SkillLockMissingError",
    "SkillProviderAdmissionError",
    "SkillsLockV1",
    "build_skills_lock",
    "load_skills_lock",
    "skills_lock_digest",
    "verify_skills_lock_subset",
    "write_or_verify_skills_lock",
]
