---
sources:
  - path: ari-core/ari/science_data_contract.py
    role: implementation
  - path: ari-skill-transform/src/science_data.py
    role: implementation
  - path: ari-skill-transform/src/ear.py
    role: implementation
last_verified: 2026-08-02
---

# Science data and EAR integrity

`ari.science-data/v1` is the only format emitted by new transform runs. It has
three independently content-addressed sections:

- `raw`: the tree, typed `MeasurementSetV1` records, execution configuration,
  environment, and exact source artifacts;
- `derived`: summaries and numeric claims computed with the core-owned formula
  registry; and
- `interpretation`: an optional model annotation bound to `raw_digest` and
  permanently marked `claim_eligible=false`.

`deterministic_digest` excludes interpretation. Consequently, changing a model,
prompt, or prose annotation cannot change the identity of measurements or
derived claims. `science_data_digest` covers the complete record. Consumers
must parse native records and use `science_data_projection` for the bounded flat
gate interface; they must never merge interpretation values into measurements.

Only canonical measurement records with a completed execution identity are
claim eligible. Untyped node metrics remain visible as `legacy_metrics` but do
not produce summaries or claims. Missing or identity-mismatched node reports
make annotation unavailable; live execution does not scan `trace_log` or an
arbitrary work directory.

Pre-v1 artifacts are converted offline:

```bash
python scripts/migrate_science_data.py old.json science_data.v1.json --run-id RUN_ID
```

Migration is conservative: old measurements stay non-claimable and unbound old
claims are not admitted. Native parsing never performs this conversion
implicitly.

EAR `manifest.lock` v2 binds sorted file content and logical roles, curation
policy, evidence index, `SKILLS.lock`, `CATALOG.lock`, cassettes,
ResultEnvelope artifacts, scientific contracts, and admission reports. Curate
verifies the evidence index before a recoverable directory swap. Publish and
clone independently re-derive every digest; backend failure leaves the curated
local bundle untouched. Manifest v1 remains read-only for already published
bundles.
