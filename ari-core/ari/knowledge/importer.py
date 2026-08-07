"""Closed local importer for non-executable Knowledge Skill packages."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from ari.knowledge.models import KnowledgeSkillManifestV1
from ari.protocols.integrity import bytes_digest, canonical_digest

if TYPE_CHECKING:
    from ari.knowledge.external_models import KnowledgeExternalSourceProvenanceV1


REQUIRED_BODY_SECTIONS = (
    "When to use",
    "Preconditions",
    "Procedure",
    "Decision points",
    "Failure conditions",
    "Expected artifacts",
    "Scientific cautions",
    "Evaluation obligations",
)
_EXECUTABLE_FIELD_NAMES = {
    "entrypoint",
    "transport",
    "command",
    "required_env",
    "credential_scope",
    "tool",
    "tools",
    "server",
    "container_command",
    "launch_command",
}
_TOOL_HINT = re.compile(
    r"(?i)(?:call|invoke|run|use|呼び出|使[うえ])\s+[`'\"]?([A-Za-z_][A-Za-z0-9_.:-]{2,})"
)


class KnowledgeImportError(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeAttachment:
    path: str
    sha256: str
    executable_in_source: bool = False


@dataclass(frozen=True)
class ImportedKnowledgeSkill:
    manifest: KnowledgeSkillManifestV1
    body: str
    references: dict[str, bytes]
    attachments: tuple[str, ...]
    non_authoritative_hints: tuple[str, ...]
    attachment_records: tuple[KnowledgeAttachment, ...] = ()
    source_provenance: KnowledgeExternalSourceProvenanceV1 | None = None


def extract_non_authoritative_tool_hints(body: str) -> tuple[str, ...]:
    return tuple(sorted(set(match.group(1) for match in _TOOL_HINT.finditer(body))))


def validate_body_sections(body: str) -> None:
    headings = {
        match.group(1).strip().casefold()
        for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", body)
    }
    missing = [
        section for section in REQUIRED_BODY_SECTIONS if section.casefold() not in headings
    ]
    if missing:
        raise KnowledgeImportError(
            "SKILL.md missing required sections: " + ", ".join(missing)
        )


def _walk_keys(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            out.add(str(key))
            out.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            out.update(_walk_keys(child))
    return out


def _manifest_payload(document: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in document.items()}
    source = dict(payload.get("source") or {})
    source.pop("manifest_sha256", None)
    payload["source"] = source
    return payload


def _safe_file(root: Path, relative: str, *, max_bytes: int) -> bytes:
    path = root / relative
    if path.is_symlink():
        raise KnowledgeImportError(f"symbolic links are refused: {relative}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise KnowledgeImportError(f"missing Knowledge artifact: {relative}") from exc
    if root.resolve() not in resolved.parents:
        raise KnowledgeImportError(f"path escapes Knowledge package: {relative}")
    mode = resolved.stat().st_mode
    if not stat.S_ISREG(mode):
        raise KnowledgeImportError(f"non-regular Knowledge artifact: {relative}")
    payload = resolved.read_bytes()
    if len(payload) > max_bytes:
        raise KnowledgeImportError(f"Knowledge artifact exceeds size limit: {relative}")
    return payload


def import_local_knowledge_skill(
    package_root: str | Path,
    *,
    max_body_bytes: int = 512 * 1024,
    max_reference_bytes: int = 16 * 1024 * 1024,
) -> ImportedKnowledgeSkill:
    """Read documentation only; this function has no execution path."""

    root = Path(package_root)
    if root.is_symlink() or not root.is_dir():
        raise KnowledgeImportError("Knowledge package root must be a real directory")
    manifest_bytes = _safe_file(root, "skill.meta.yaml", max_bytes=max_body_bytes)
    body_bytes = _safe_file(root, "SKILL.md", max_bytes=max_body_bytes)
    try:
        document = yaml.safe_load(manifest_bytes) or {}
    except yaml.YAMLError as exc:
        raise KnowledgeImportError("skill.meta.yaml is invalid YAML") from exc
    if not isinstance(document, dict):
        raise KnowledgeImportError("skill.meta.yaml must be a mapping")
    forbidden = sorted(_walk_keys(document) & _EXECUTABLE_FIELD_NAMES)
    if forbidden:
        raise KnowledgeImportError(
            "Knowledge manifest contains executable fields: " + ", ".join(forbidden)
        )
    try:
        manifest = KnowledgeSkillManifestV1.model_validate(document)
    except ValidationError as exc:
        raise KnowledgeImportError(f"invalid Knowledge manifest: {exc}") from exc
    if bytes_digest(body_bytes) != manifest.source.body_sha256:
        raise KnowledgeImportError("Knowledge body digest mismatch")
    if canonical_digest(_manifest_payload(document)) != manifest.source.manifest_sha256:
        raise KnowledgeImportError("Knowledge manifest digest mismatch")
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeImportError("SKILL.md must be UTF-8 text") from exc
    validate_body_sections(body)
    references: dict[str, bytes] = {}
    for reference in manifest.references:
        payload = _safe_file(root, reference.path, max_bytes=max_reference_bytes)
        if bytes_digest(payload) != reference.sha256:
            raise KnowledgeImportError(f"reference digest mismatch: {reference.path}")
        references[reference.path] = payload
    declared = {"SKILL.md", "skill.meta.yaml", *references}
    attachments: list[str] = []
    attachment_records: list[KnowledgeAttachment] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in declared:
            continue
        if path.is_symlink():
            raise KnowledgeImportError(f"attachment symlink is refused: {rel}")
        payload = _safe_file(root, rel, max_bytes=max_reference_bytes)
        attachments.append(rel)
        attachment_records.append(
            KnowledgeAttachment(
                path=rel,
                sha256=bytes_digest(payload),
                executable_in_source=bool(path.stat().st_mode & 0o111),
            )
        )
    hints = extract_non_authoritative_tool_hints(body)
    return ImportedKnowledgeSkill(
        manifest=manifest,
        body=body,
        references=references,
        attachments=tuple(attachments),
        non_authoritative_hints=hints,
        attachment_records=tuple(attachment_records),
    )


__all__ = [
    "ImportedKnowledgeSkill",
    "KnowledgeAttachment",
    "KnowledgeImportError",
    "REQUIRED_BODY_SECTIONS",
    "extract_non_authoritative_tool_hints",
    "import_local_knowledge_skill",
    "validate_body_sections",
]
