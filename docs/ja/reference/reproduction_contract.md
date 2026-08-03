---
sources:
  - path: ari-skill-paper-re/src/contracts.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
last_verified: 2026-08-02
---

# 再現実行と採点の契約

`ari-skill-paper-re` v1.0はimmutableな科学inputと各execution attemptを分離します。scoreをpublish
できるのは、検証済みで成功したreproduction runへbindされ、要求したすべてのjudge runが完了した
場合だけです。

check-in済みJSON Schemaは`ari-skill-paper-re/schemas/`にあります。schema driftを拒否するには
`python ari-skill-paper-re/scripts/sync_contracts.py`を実行します。

## Recordとidentity

| Record | Identityと目的 |
|---|---|
| `ReproductionPlanV1` | rubric、input tree、`reproduce.sh`、command、sandbox/image、timeout、resource request、expected artifact、policyのcanonical digest。 |
| `ReproductionAttemptV1` | parent attempt/planへlinkした1回のterminal execution。environment identity、正確なlog/output-manifest digest、output-tree digest、missing artifact、型付きfailure evidenceを持つ。 |
| `ReproductionRunV1` | orderedでcontiguousなattempt lineage。成功runだけが1つの成功attemptを選ぶ。 |
| `GradeReportV1` | rubric/paper/run digest、judge identityとindependence、すべてのleaf evidence/raw response、run count、variance、negative control、call trace、final validity。 |

各recordはunknown fieldと、canonical finite-JSON payloadに一致しないdigestを拒否します。artifact pathは
relativeでtraversal不可とし、使用前にdigestとbyte countを検証します。

## Workspace layoutとretry

plan digest `<P>`のmetadataはcallerのsource tree配下に置きます。

```text
.ari-reproduction/
  <P>/
    plan.json
    input-manifest.json
    input/                         # content-addressed, read-only snapshot
    run.json
    attempts/
      0001-<attempt-id>/
        work/                      # private writable execution tree
        output-manifest.json
  latest.json                     # verified active run pointer
```

executionはcallerのsource fileへresultを書きません。symlink、non-regular output、1 GiB超のfile、8 GiB超の
treeはprivate outputから除去し、attemptを`filesystem-policy`で失敗させます。`reproduce.log`はatomicに
書きます。output manifestは追加・変更・削除されたすべてのpathとpolicy incidentを記録します。

成功済みplanの反復は、run、artifact、output treeを再検証した後のidempotent replayです。failed/
timed-out/cancelled planの反復は新しいattemptを作り、その`parent_attempt_id`は直前attemptを指します。
source、rubric、image、policy、resource、timeoutの変更は別planを作り、古いlineageをsilentに延長しません。

## Sandbox admission

| Substrate | Immutable identity | Default network denial |
|---|---|---|
| Docker | 完全なlocal `sha256:<image-id>`または`name@sha256:<digest>` | `--network=none`、read-only root、上限付きtmpfs、capabilityなし、no-new-privileges、PID limit |
| Apptainer/Singularity | local regular non-symlink SIF（hash済み）またはremote `@sha256:<digest>` URI | clean environment、contained filesystem、home mountなしのisolated network namespace |
| Local | host/toolchain identityを記録 | 明示的administrator isolation attestationが必要。なければ`network_policy=inherit`を明示選択 |
| SLURM | digest-boundなcommon HPC handoffとscheduler/module/resource/runtime evidence | `deny`にはadministrator isolation attestationが必要。jobは`--export=NIL`と明示literal/moduleを使用 |

execution environmentはminimal allowlistから構築し、parent environmentをcopyしません。
`network_policy=inherit`はunverifiedとして記録し、isolationとは表現しません。timeout/cancellationは
local/container process group全体をkillし、named Docker containerを強制削除するか、terminalize前に
scheduler handleをcancelします。

`auto`は利用可能なsubstrateを選びますが、imageを捏造したりpolicyを弱めたりしません。選択substrateが
immutable-image、network、GPU、scheduler、resource constraintを満たせなければplanning/executionは
明示的に失敗します。

## Grade validity

`grade_with_simplejudge`には次のすべてが必要です。

- non-emptyなpaper textとdigestが一致するschema-valid rubric
- statusが`succeeded`のdigest-verified `ReproductionRunV1`
- 要求したすべてのjudge runの完了
- raw per-call/per-leaf responseの永続化
- configured threshold未満で完了したnegative control

judge/provider failure、schema mismatch、欠落・改ざん・失敗したreproduction、利用不能なnegative controlは
scientific scoreなしの`status=failed`になります。negative controlがthresholdを超えたcompleted gradeは
診断用observed scoreを保持しますが、`valid`でなく`invalid-negative-control`です。control skipも同じ
invalid statusです。rubric generator modelをjudgeとして再利用した場合は、独立auditと表示せず
`not-independent`を報告します。

## PaperBench provenanceとpatch削除

`paperbench_patches.json`はreview済みupstream Git commitを正確にpinし、残る各runtime adaptationを
upstream symbol、rationale、deletion gateへmapします。overrideは`ARI_PAPERBENCH_PATH`と一致する
`ARI_PAPERBENCH_COMMIT`の両方を指定し、Gitがその正確なidentityを確認した場合だけ受理します。
package rootはbootstrap中だけ一時的に可視化し、その後`sys.path`から除去します。pip-installed
PaperBenchはfallbackではありません。

compatibility inventoryは意図的に縮小しています。v1.0では次を削除しました。

- host-local sandbox fallbackと`ARI_PHASE1_ALLOW_FALLBACK`
- mutable default imageと`pb-env` / `pb-reproducer`の`:latest` alias
- `apptainer_image` tool argumentと`ARI_PHASE1_SINGULARITY_IMAGE`
- source-mutating salvage wrapperとimplicit `code_only` grading
- 重複したlocal/Docker/Apptainer/SLURM runner entry point

残るPaperBench adaptationは、そのinventory gateがpinned upstream suiteに対して通過した時点で削除します。
named owner、removal release、migration test、fail-closed security reviewなしにcompatibility nameやfallbackを
再導入できません。
