"""Real stdio MCP fixture for child-environment isolation tests."""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("child-environment-fixture")

_secret = os.environ.get("FIXTURE_SECRET", "")
if _secret:
    print(f"fixture-startup-secret={_secret}", file=sys.stderr, flush=True)


@mcp.tool()
def inspect_environment(names: list[str]) -> dict:
    """Return selected values and the process environment key inventory."""

    return {
        "values": {name: os.environ.get(name) for name in names},
        "keys": sorted(os.environ),
    }


if __name__ == "__main__":
    mcp.run()
