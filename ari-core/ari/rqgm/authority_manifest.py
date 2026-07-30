"""Deterministic machine-readable export of the constitutional capability table.

The fixed kernel table remains the sole source of truth.  This module only
expands its sparse allow-list into the complete role × tier × action × resource
decision table, including explicit denials, so an artifact reviewer can inspect
or diff the exact authorization surface without interpreting prose.
"""

from __future__ import annotations

import json

from ari.rqgm.kernel_rules import (
    ACTIONS,
    CAPABILITY_MATRIX,
    RESOURCE_CLASSES,
)

AUTHORITY_MANIFEST_SCHEMA_VERSION = 1


def authority_manifest() -> dict:
    """Return the complete deny-by-default capability matrix."""
    decisions = []
    for (role, tier), grants in sorted(CAPABILITY_MATRIX.items()):
        for action in ACTIONS:
            for resource in RESOURCE_CLASSES:
                decisions.append(
                    {
                        "role": role,
                        "tier": tier,
                        "action": action,
                        "resource": resource,
                        "allowed": (action, resource) in grants,
                    }
                )
    return {
        "schema_version": AUTHORITY_MANIFEST_SCHEMA_VERSION,
        "default": "deny",
        "actions": list(ACTIONS),
        "resources": list(RESOURCE_CLASSES),
        "decisions": decisions,
    }


def main() -> None:
    """Print stable UTF-8 JSON for artifact capture and independent review."""
    print(
        json.dumps(
            authority_manifest(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
