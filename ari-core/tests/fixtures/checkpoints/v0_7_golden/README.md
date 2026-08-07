# v0.7 golden checkpoint

This immutable fixture represents the historical nested-tree checkpoint layout
used to verify read-only paper and replay migration. Tests digest the complete
directory before and after inspection so a compatibility reader cannot rewrite
the source data.

The fixture is deliberately committed despite the repository-wide runtime
`checkpoints/` ignore rule. Update it only with a corresponding migration
contract change and an explicit compatibility rationale.
