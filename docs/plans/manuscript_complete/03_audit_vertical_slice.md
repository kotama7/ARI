# Task 03: Audit-Only Simple BFTS + Linear Vertical Slice

> **Status**: planned
> **Depends on**: 00, 01, 02
> **Gate**: G2 — observable completeness without behavior change
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

Task 02 の deterministic compiler を実際の post-BFTS artifact handoff に接続し、
`simple_bfts + linear + manuscript.audit + repair.disabled` の最初の vertical slice を作る。
不足を観測・保存するが、writer、claim gate、finalize の既存挙動は止めない。

## 2. Scope

- Typed `manuscript` runtime config with default `off`。
- Effective mode resolution and fail-safe invalid-value behavior。
- `.ari-manuscript/` isolated artifact namespace and immutable attempts。
- Evidence artifacts完成後の audit compiler invocation。
- `state.json` and append-only/hash-bound transition record foundation。
- Read-only `ari manuscript status` / `inspect` commands。
- Existing writer payload と ManuscriptContext inventory の差分 report。
- Simple BFTS + linear real/fixture checkpoint coverage。
- Off-mode zero-import/zero-artifact/identity tests。

## 3. Non-goals

- readiness で authoring を止めない。
- workflow を evidence/authoring/verification segment に分割しない。
- section brief を writer に渡さない。
- repair plan または repair execution を行わない。
- RQGM/KCA/paper archive adapter を実装しない。
- legacy writer cap を削除しない。

## 4. Configuration

Initial typed config:

```yaml
manuscript:
  mode: off          # off | audit | enforce; enforce is reserved until Task 04
  profile: generic_empirical_v1
  repair:
    policy: disabled
```

Task 03 accepts `enforce` in schema only if Task 04 will own its activation; until then effective
resolver must reject/downgrade it explicitly rather than behaving like audit without notice。Default
config omits or resolves to off and must not import `ari.manuscript` on the legacy path。

## 5. Runtime insertion

Because current evidence preparation and authoring share one workflow, Task 03 uses an audit hook
that runs only after required evidence outputs exist。It must not reorder or suppress existing
stages。Acceptable implementations include a post-pipeline audit callback or an audit-only observer
after `generate_paper_section`, provided that:

- it reads exact produced artifacts。
- it cannot change `full_paper.tex` or downstream gate inputs。
- its failure is visible but does not alter legacy audit-mode paper result。
- Task 04 can replace the hook with a pre-authoring coordinator without retaining two compilers。

The chosen seam is recorded in code comments and a Task 01 ADR amendment if needed。

## 6. Attempt persistence

```text
{checkpoint}/.ari-manuscript/
  state.json
  transitions.jsonl
  attempts/mca-<digest>/
    source_snapshot.json
    requirement_profile.json
    context.json
    omission_manifest.json
    readiness.json
    audit_comparison.json
```

Audit comparison records:

- items available in context but absent from current writer payload。
- items present in writer payload without a typed context source。
- cap/budget-induced observed omissions。
- failed/null/off-lineage visibility differences。
- assurance/provenance fields not surfaced to authoring。

It is observational and not a normative readiness contract field。

## 7. CLI behavior

### `ari manuscript status`

Returns:

- current attempt ID/digest and staleness。
- authoring/publication shadow verdicts。
- counts by requirement status、lane、omission reason。
- repairable/human/unavailable count, without executing repair。

### `ari manuscript inspect`

Filters by requirement/section/node/evidence ID and prints source refs。It is read-only and does not
invoke network、LLM、experiment、certification。

Both commands support stable JSON output for later GUI consumption。

## 8. Failure posture

- Mode off: no manuscript code path or files。
- Mode audit, compiler succeeds: persist artifacts and continue/retain paper result。
- Mode audit, compiler fails: persist bounded diagnostic if namespace can be safely created; existing
  paper result remains authoritative, process reports audit failure separately。
- Existing artifact is corrupt: never overwrite it silently; create a new attempt or report invalid。
- Re-run identical input: verify/reuse immutable attempt, do not append duplicate normative records。

## 9. Tests

- Config default/off and invalid value tests。
- Lazy import test for off path。
- Zero `.ari-manuscript` files under off。
- Default paper bytes/call order from Task 01 unchanged。
- Audit artifacts validate against Task 02 schemas。
- Same checkpoint produces same attempt ID and digests。
- Large fixture reports every current cap-related omission observable from inputs。
- Negative fixture lists failed/null/inconclusive/off-lineage nodes。
- Tamper fixture reports excluded/missing/mismatch states without changing paper。
- Legacy checkpoint lazily audits without in-place migration。
- CLI status/inspect JSON snapshots and no-mutation tests。

## 10. Completion criteria

1. `manuscript.mode=off` is the default and preserves the Task 01 identity baseline。
2. Audit mode writes only under `.ari-manuscript/`。
3. A real/representative simple BFTS linear run produces valid context、omission、readiness artifacts。
4. Existing writer and paper verification outputs remain unchanged in audit mode。
5. Audit comparison quantifies known information loss without silent unknown counts。
6. Failed/null/off-lineage/tamper fixture states are visible and correctly classified。
7. Repeated audit is deterministic/idempotent。
8. Status/inspect are read-only and machine-readable。
9. Audit failures are independently observable and do not masquerade as readiness pass。
10. G2 evidence is recorded for Task 04。

## 11. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green。
2. Audit CLI and artifact namespace behavior are in permanent user/reference docs。
3. Audit comparison metrics are maintained by tests or an evaluation specification。
4. Task 04 has replaced any temporary post-pipeline hook with the final coordinator seam, or the hook
   is documented as permanent。
5. Legacy/off identity guarantees are permanent tests。
6. Tasks 04–09 no longer cite this prose as the only runtime behavior definition。
7. `INDEX.md` records deletion status and reason。

## 12. Delete-after checklist

- [ ] Off-mode identity and lazy-import tests are permanent。
- [ ] Audit artifact schemas and CLI output are documented。
- [ ] Temporary audit hook is removed or made permanent explicitly。
- [ ] Large/negative/tamper audit fixtures remain in CI。
- [ ] Attempt idempotence test is permanent。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 13. Handoff

Task 04 receives actual audit attempt artifacts、measured context-loss data、and the proven off-mode
identity seam。Task 04 moves completeness before authoring and changes behavior only under explicit
`enforce` activation。
