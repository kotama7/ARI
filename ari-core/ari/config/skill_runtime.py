"""Translate canonical Skill manifests into runtime registration metadata."""

from ari.skill_manifest import SkillManifestV1, manifest_digest, manifest_tool_ref


def manifest_runtime_metadata(manifest: SkillManifestV1) -> dict[str, object]:
    """Resolve the immutable identity and per-tool policy consumed by MCPClient."""

    tools = manifest.resolved_tools()
    return {
        "tool_timeout_classes": {tool.name: tool.timeout_class for tool in tools},
        "manifest_digest": manifest_digest(manifest),
        "tool_refs": {
            tool.name: manifest_tool_ref(manifest, tool.name) for tool in tools
        },
        "tool_capabilities": {tool.name: tool.capability_ref for tool in tools},
        "tool_policies": {
            tool.name: tool.model_dump(
                mode="json", exclude={"name", "capability_ref", "description"}
            )
            for tool in tools
        },
        "credential_scopes": {
            scope.id: {
                "required_env": list(scope.required_env),
                "optional_env": list(scope.optional_env),
            }
            for scope in manifest.credential_scopes
        },
    }


__all__ = ["manifest_runtime_metadata"]
