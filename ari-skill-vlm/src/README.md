# ari-skill-vlm runtime

- `server.py` — three MCP adapters and failure-preserving batch aggregation.
- `artifacts.py` — FigureBatch resolution, digest/size/image verification.
- `criteria.py` — immutable figure/table/domain criterion profiles.
- `review.py` — bounded model call, strict schema parse, raw artifact and usage provenance.
- `prompts/` — externalized figure and table review instructions.

The runtime has no raster-sibling guessing, manifest fallback, markdown-fence
repair, or empty-success conversion.
