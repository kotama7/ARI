# MC-ADR-003: one segmented workflow

Decision: add `segment` metadata to the one existing workflow and derive
disabled-stage views per invocation. A separate manuscript workflow is
prohibited. Alternatives were duplicated YAML and stage-name hardcoding;
both drift from legacy order. Compatibility: the legacy all-stage call ignores
segment selection. Reverse only if a new workflow contract proves ordering and
dependency parity. Owning tests: workflow contract, segment freshness/reuse,
and pipeline architecture tests.
