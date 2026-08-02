"""Explicit RunContext/NodeContext and transport-capability contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ari.call_context import (
    CALL_CONTEXT_ARGUMENT,
    CallContextAuthorizationError,
    NodeContextV1,
    ToolCallContextV1,
    authorize_tool_context,
    new_context_authority_key,
    verify_tool_context,
)
from ari.mcp.secure_stdio_proxy import (
    _inject_call_context,
    _strip_context_from_tool_schemas,
)


def _node_context() -> ToolCallContextV1:
    return ToolCallContextV1.for_node(
        run_id="run-1",
        node_id="child",
        parent_node_id="root",
        ancestor_node_ids=["root"],
        phase="bfts",
    )


def test_lineage_digest_and_parent_are_validated():
    context = _node_context()
    assert context.node_context is not None
    assert context.node_context.readable_node_ids == {"root", "child"}

    document = context.node_context.model_dump(mode="json")
    document["ancestor_node_ids"] = ["sibling"]
    with pytest.raises(ValidationError, match="parent_node_id|lineage_digest"):
        NodeContextV1.model_validate(document)


def test_capability_is_bound_to_tool_context_and_authority():
    key = new_context_authority_key()
    capability = authorize_tool_context(
        _node_context(),
        tool_name="add_memory",
        authority_key=key,
    )
    verified = verify_tool_context(
        capability,
        tool_name="add_memory",
        authority_key=key,
    )
    assert verified.node_id == "child"

    with pytest.raises(CallContextAuthorizationError, match="another tool"):
        verify_tool_context(
            capability,
            tool_name="clear_node_memory",
            authority_key=key,
        )
    with pytest.raises(CallContextAuthorizationError, match="authority"):
        verify_tool_context(
            capability,
            tool_name="add_memory",
            authority_key=new_context_authority_key(),
        )

    capability["context"]["node_id"] = "sibling"
    with pytest.raises(CallContextAuthorizationError, match="malformed|signature"):
        verify_tool_context(
            capability,
            tool_name="add_memory",
            authority_key=key,
        )


def test_proxy_overrides_forged_context_and_hides_transport_schema():
    key = new_context_authority_key()
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "add_memory",
            "arguments": {
                "node_id": "child",
                CALL_CONTEXT_ARGUMENT: {"forged": True},
            },
        },
    }
    transformed = _inject_call_context(
        (json.dumps(request) + "\n").encode(),
        context_requirements={"add_memory": "node"},
        call_context=_node_context(),
        authority_key=key,
    )
    capability = json.loads(transformed)["params"]["arguments"][
        CALL_CONTEXT_ARGUMENT
    ]
    assert "forged" not in capability
    assert verify_tool_context(
        capability,
        tool_name="add_memory",
        authority_key=key,
    ).node_id == "child"

    response = {
        "jsonrpc": "2.0",
        "id": 6,
        "result": {
            "tools": [
                {
                    "name": "add_memory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "node_id": {"type": "string"},
                            CALL_CONTEXT_ARGUMENT: {"type": "object"},
                        },
                        "required": ["node_id", CALL_CONTEXT_ARGUMENT],
                    },
                }
            ]
        },
    }
    public = json.loads(
        _strip_context_from_tool_schemas((json.dumps(response) + "\n").encode())
    )
    schema = public["result"]["tools"][0]["inputSchema"]
    assert CALL_CONTEXT_ARGUMENT not in schema["properties"]
    assert schema["required"] == ["node_id"]
