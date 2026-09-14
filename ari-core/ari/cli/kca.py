"""Human diagnostic CLI for the three separate K/C/A registries.

The module intentionally imports domain packages inside command callbacks so
the legacy ``ari run`` path does not import Knowledge/Assurance merely because
the top-level Typer application was constructed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml


knowledge_app = typer.Typer(help="Inspect non-executable Knowledge Skills.")
knowledge_lock_app = typer.Typer(help="Inspect immutable Knowledge locks.")
knowledge_use_app = typer.Typer(help="Inspect node Knowledge provenance.")
knowledge_app.add_typer(knowledge_lock_app, name="lock")
knowledge_app.add_typer(knowledge_use_app, name="use")

provider_app = typer.Typer(help="Inspect executable Capability Providers.")
provider_lock_app = typer.Typer(
    help="Inspect the canonical SKILLS.lock Provider snapshot."
)
provider_bindings_app = typer.Typer(help="Inspect fixed capability bindings.")
provider_app.add_typer(provider_lock_app, name="lock")
provider_app.add_typer(provider_bindings_app, name="bindings")

harness_app = typer.Typer(help="Inspect independent Harnesses and assurance evidence.")
harness_lock_app = typer.Typer(help="Inspect immutable Harness locks.")
harness_attestation_app = typer.Typer(help="Inspect target-bound attestations.")
harness_suite_app = typer.Typer(help="Resolve or inspect Harness suites.")
harness_app.add_typer(harness_lock_app, name="lock")
harness_app.add_typer(harness_attestation_app, name="attestation")
harness_app.add_typer(harness_suite_app, name="suite")


def _core_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_catalog(kind: str) -> Path:
    return _core_root() / "config" / kind / "catalog.yaml"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _json(value: Any) -> None:
    typer.echo(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
    )


def _read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise typer.BadParameter(f"not a regular file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"invalid JSON {path}: {exc}") from exc


def _admission_file(checkpoint: Path, name: str) -> Path:
    return checkpoint / "rqgm" / "kca" / "admission-v1" / name


@knowledge_app.command("search")
def knowledge_search(
    query: str = typer.Argument(""),
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    """Search the checked-in Knowledge catalog; never activates a Skill."""

    from ari.knowledge.catalog import load_knowledge_catalog

    loaded = load_knowledge_catalog(catalog or _default_catalog("knowledge_skills"))
    needle = query.casefold().strip()
    matches = []
    for entry in loaded.snapshot.entries:
        manifest = entry.manifest
        haystack = " ".join(
            (manifest.id, manifest.title, manifest.description)
        ).casefold()
        if not needle or needle in haystack:
            matches.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "title": manifest.title,
                    "status": entry.status,
                    "body_sha256": manifest.source.body_sha256,
                    "manifest_sha256": manifest.source.manifest_sha256,
                }
            )
    _json({"kind": "knowledge", "matches": matches})


@knowledge_app.command("show")
def knowledge_show(
    skill_id: str,
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    from ari.knowledge.catalog import load_knowledge_catalog

    loaded = load_knowledge_catalog(catalog or _default_catalog("knowledge_skills"))
    matches = [item for item in loaded.snapshot.entries if item.manifest.id == skill_id]
    if not matches:
        raise typer.BadParameter(f"unknown Knowledge Skill: {skill_id}")
    _json({"kind": "knowledge", "entries": matches})


@knowledge_app.command("validate-manifest")
def knowledge_validate_manifest(package: Path) -> None:
    from ari.knowledge.importer import import_local_knowledge_skill

    imported = import_local_knowledge_skill(package)
    _json(
        {
            "valid": True,
            "manifest": imported.manifest,
            "attachments": imported.attachments,
            "non_authoritative_tool_hints": imported.non_authoritative_hints,
        }
    )


@knowledge_app.command("validate-registration")
def knowledge_validate_registration(report: Path) -> None:
    from ari.knowledge.models import KnowledgeSkillRegistrationReportV1

    parsed = KnowledgeSkillRegistrationReportV1.model_validate(_read_json(report))
    _json({"valid": True, "report": parsed})


@knowledge_app.command("import")
def knowledge_import(
    package: Path | None = typer.Argument(None),
    source_kind: str = typer.Option(
        "local",
        "--source-kind",
        help=(
            "local, git, open-agent-skills, scientific-skill-repository, "
            "or tooluniverse-knowledge"
        ),
    ),
    repository: str = typer.Option("", "--repository"),
    commit: str = typer.Option("", "--commit"),
    subpath: str = typer.Option("", "--subpath"),
    profile: Path | None = typer.Option(None, "--profile"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Create pinned candidate material; never writes the governed catalog."""

    from ari.knowledge.external_importer import (
        import_git_knowledge_skill,
        import_open_agent_skill,
        import_tooluniverse_knowledge_collection,
        load_knowledge_import_profile,
        load_tooluniverse_collection_profile,
    )
    from ari.knowledge.external_models import KnowledgeImportMaterialV1
    from ari.knowledge.importer import (
        KnowledgeImportError,
        import_local_knowledge_skill,
    )
    from ari.protocols.integrity import bytes_digest, canonical_digest

    admitted_kinds = {
        "local",
        "git",
        "open-agent-skills",
        "scientific-skill-repository",
        "tooluniverse-knowledge",
    }
    if source_kind not in admitted_kinds:
        raise typer.BadParameter(f"unknown Knowledge source kind: {source_kind}")

    def one_material(imported) -> dict[str, Any]:
        material = KnowledgeImportMaterialV1.create(
            manifest=imported.manifest,
            body=imported.body,
            body_sha256=bytes_digest(imported.body.encode("utf-8")),
            reference_digests={
                name: bytes_digest(payload)
                for name, payload in sorted(imported.references.items())
            },
            attachments=tuple(
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "executable_in_source": item.executable_in_source,
                    "authority": "none",
                }
                for item in imported.attachment_records
            ),
            non_authoritative_tool_hints=imported.non_authoritative_hints,
            source_provenance=imported.source_provenance,
        )
        return material.model_dump(mode="json")

    try:
        if source_kind == "local":
            if package is None:
                raise KnowledgeImportError("local Knowledge import requires PACKAGE")
            if repository or commit or subpath or profile is not None:
                raise KnowledgeImportError(
                    "local Knowledge import does not accept external source options"
                )
            material = one_material(import_local_knowledge_skill(package))
        else:
            if package is not None:
                raise KnowledgeImportError(
                    "external Knowledge import uses --repository/--commit/--subpath, not PACKAGE"
                )
            if not repository or not commit or not subpath or profile is None:
                raise KnowledgeImportError(
                    "external Knowledge import requires --repository, --commit, --subpath, and --profile"
                )
            if source_kind == "tooluniverse-knowledge":
                collection_profile = load_tooluniverse_collection_profile(profile)
                imported_collection = import_tooluniverse_knowledge_collection(
                    repository=repository,
                    commit=commit,
                    root_subpath=subpath,
                    profile=collection_profile,
                )
                material = {
                    "schema_version": "ari.knowledge-import-collection-material/v1",
                    "decision": "candidate",
                    "authoritative": False,
                    "provider_activated": False,
                    "collection_provenance": imported_collection.provenance.model_dump(
                        mode="json"
                    ),
                    "skills": [
                        one_material(item) for item in imported_collection.skills
                    ],
                }
                material["material_digest"] = canonical_digest(material)
            else:
                import_profile = load_knowledge_import_profile(profile)
                if source_kind == "open-agent-skills":
                    imported = import_open_agent_skill(
                        repository=repository,
                        commit=commit,
                        subpath=subpath,
                        profile=import_profile,
                    )
                else:
                    imported = import_git_knowledge_skill(
                        repository=repository,
                        commit=commit,
                        subpath=subpath,
                        profile=import_profile,
                        source_kind=source_kind,
                    )
                material = one_material(imported)
    except (KnowledgeImportError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    rendered = json.dumps(material, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and output.read_text(encoding="utf-8") != rendered:
            raise typer.BadParameter("refusing to replace different import material")
        output.write_text(rendered, encoding="utf-8")
    typer.echo(rendered, nl=False)


@knowledge_lock_app.command("show")
def knowledge_lock_show(checkpoint: Path) -> None:
    from ari.knowledge.models import EpochKnowledgeSkillLockV1

    parsed = EpochKnowledgeSkillLockV1.model_validate(
        _read_json(_admission_file(checkpoint, "knowledge_skill_lock.json"))
    )
    _json(parsed)


@knowledge_use_app.command("show")
def knowledge_use_show(
    checkpoint: Path, node_id: str = typer.Option("", "--node")
) -> None:
    root = checkpoint / "rqgm" / "kca" / "nodes"
    paths = (
        [root / node_id / "node_knowledge_skill_use.json"]
        if node_id
        else sorted(root.glob("*/node_knowledge_skill_use.json"))
    )
    _json({"kind": "knowledge-use", "records": [_read_json(path) for path in paths]})


def _provider_catalog_rows(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [dict(item) for item in raw.get("entries", ())]


@provider_app.command("search")
def provider_search(
    query: str = typer.Argument(""),
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    rows = _provider_catalog_rows(catalog or _default_catalog("providers"))
    needle = query.casefold().strip()
    matches = [
        row
        for row in rows
        if not needle or needle in json.dumps(row, ensure_ascii=False).casefold()
    ]
    _json({"kind": "provider", "matches": matches})


@provider_app.command("show")
def provider_show(
    provider_id: str,
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    rows = [
        row
        for row in _provider_catalog_rows(catalog or _default_catalog("providers"))
        if row.get("provider_id") == provider_id
    ]
    if not rows:
        raise typer.BadParameter(f"unknown Capability Provider: {provider_id}")
    _json({"kind": "provider", "entries": rows})


@provider_app.command("validate-manifest")
def provider_validate_manifest(manifest: Path) -> None:
    from ari.skill_manifest import load_skill_manifest, manifest_digest

    parsed = load_skill_manifest(manifest)
    _json(
        {
            "valid": True,
            "canonical_term": "Capability Provider Manifest",
            "legacy_filename": manifest.name,
            "manifest_sha256": "sha256:" + manifest_digest(parsed),
            "manifest": parsed,
        }
    )


@provider_app.command("probe")
def provider_probe(config: Path, provider_name: str) -> None:
    """Run existing MCP tools/list for one explicitly selected Provider."""

    from ari.config import load_config
    from ari.mcp.client import MCPClient

    cfg = load_config(str(config))
    selected = [item for item in cfg.skills if item.name == provider_name]
    if len(selected) != 1:
        raise typer.BadParameter(f"configured Provider is not unique: {provider_name}")
    client = MCPClient(selected, strict_provider_loading=True)
    try:
        tools = client.list_tools()
        lock = client.skills_lock
    finally:
        client.close_all()
    _json(
        {
            "provider": provider_name,
            "tools": tools,
            "provider_lock": lock,
        }
    )


@provider_lock_app.command("show")
def provider_lock_show(path: Path) -> None:
    from ari.skill_lock import load_skills_lock

    _json(load_skills_lock(path))


@provider_bindings_app.command("show")
def provider_bindings_show(checkpoint: Path) -> None:
    from ari.capability_binding.models import CapabilityBindingLockV1

    parsed = CapabilityBindingLockV1.model_validate(
        _read_json(_admission_file(checkpoint, "capability_binding_lock.json"))
    )
    _json(parsed)


@harness_app.command("search")
def harness_search(
    query: str = typer.Argument(""),
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    from ari.assurance.catalog import load_harness_catalog, search_harnesses

    snapshot = load_harness_catalog(catalog or _default_catalog("harnesses"))
    _json({"kind": "harness", "matches": search_harnesses(snapshot, query)})


@harness_app.command("show")
def harness_show(
    harness_id: str,
    catalog: Path = typer.Option(None, "--catalog"),
) -> None:
    from ari.assurance.catalog import describe_harness, load_harness_catalog

    snapshot = load_harness_catalog(catalog or _default_catalog("harnesses"))
    manifest = describe_harness(snapshot, harness_id)
    if manifest is None:
        raise typer.BadParameter(f"unknown Harness: {harness_id}")
    _json({"kind": "harness", "manifest": manifest})


@harness_app.command("validate-manifest")
def harness_validate_manifest(manifest: Path) -> None:
    from ari.assurance.models import HarnessManifestV1

    raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    advertised = raw.pop("manifest_digest", None)
    parsed = HarnessManifestV1.create(**raw)
    if advertised is not None and advertised != parsed.manifest_digest:
        raise typer.BadParameter("Harness Manifest digest mismatch")
    _json({"valid": True, "manifest": parsed})


@harness_app.command("validate-registration")
def harness_validate_registration(report: Path) -> None:
    from ari.assurance.models import HarnessRegistrationReportV1

    parsed = HarnessRegistrationReportV1.model_validate(_read_json(report))
    _json({"valid": True, "report": parsed})


@harness_app.command("resolve")
def harness_resolve(
    contract: Path,
    environment: Path,
    catalog: Path = typer.Option(None, "--catalog"),
    audit: bool = typer.Option(False, "--audit"),
) -> None:
    from ari.assurance.catalog import load_harness_catalog
    from ari.assurance.models import VerificationContractV1
    from ari.assurance.resolver import resolve_harness_suite
    from ari.protocols.scientific_requirements import EnvironmentSnapshotV1

    suite = resolve_harness_suite(
        contract=VerificationContractV1.model_validate(_read_json(contract)),
        catalog=load_harness_catalog(catalog or _default_catalog("harnesses")),
        environment=EnvironmentSnapshotV1.model_validate(_read_json(environment)),
        enforce_coverage=not audit,
    )
    _json(suite)


@harness_lock_app.command("show")
def harness_lock_show(checkpoint: Path) -> None:
    from ari.assurance.models import BaselineHarnessLockV1

    parsed = BaselineHarnessLockV1.model_validate(
        _read_json(_admission_file(checkpoint, "baseline_harness_lock.json"))
    )
    _json(parsed)


@harness_attestation_app.command("show")
def harness_attestation_show(path: Path) -> None:
    from ari.assurance.models import HarnessAttestationV1

    _json(HarnessAttestationV1.model_validate(_read_json(path)))


@harness_app.command("verify")
def harness_verify(attestation: Path, request: Path, baseline_lock: Path) -> None:
    """Validate an existing Attestation against its exact target and locks."""

    from ari.assurance.attestation import validate_attestation
    from ari.assurance.models import (
        BaselineHarnessLockV1,
        HarnessAttestationV1,
        HarnessRunRequestV1,
    )

    att = HarnessAttestationV1.model_validate(_read_json(attestation))
    req = HarnessRunRequestV1.model_validate(_read_json(request))
    lock = BaselineHarnessLockV1.model_validate(_read_json(baseline_lock))
    validate_attestation(
        attestation=att,
        request=req,
        baseline_lock=lock,
        current_target_digest=req.target_workspace.file_digest(req.target_logical_name),
    )
    _json({"valid": True, "attestation_digest": att.attestation_digest})


@harness_suite_app.command("run")
def harness_suite_run() -> None:
    """Refuse actor-selected execution; authoritative execution is internal."""

    typer.echo(
        "Harness suite execution requires the admitted runtime Fixed Verifier; "
        "use `ari run` or validate a persisted Attestation with `ari harness verify`",
        err=True,
    )
    raise typer.Exit(code=2)


__all__ = ["knowledge_app", "provider_app", "harness_app"]
