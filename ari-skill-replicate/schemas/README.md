# ari-skill-replicate/schemas

JSON Schema(s) for the rubrics this skill produces.

## Contents

- `README.md` — this file.
- `replication_rubric.schema.json` — strict, immutable `ReplicationRubricV2` generation contract.
- `replication_rubric_audit.schema.json` — separate deterministic/LLM audit report; audits never mutate a frozen rubric.
