"""Public re-export of the verified-context helpers.

Skills (ari-skill-paper) call ``render_grounded_block`` from here so they reach
the ari-core implementation through the stable public contract (req 09) rather
than the private ``ari.pipeline.verified_context`` path. ``write_verified_context``
is re-exported too for callers that build the artifact.
"""

from ari.pipeline.verified_context import (  # noqa: F401
    build_verified_context,
    render_grounded_block,
    write_verified_context,
)

__all__ = ["render_grounded_block", "write_verified_context", "build_verified_context"]
