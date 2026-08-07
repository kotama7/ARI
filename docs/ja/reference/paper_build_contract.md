---
sources:
  - path: ari-core/ari/public/paper.py
    role: schema
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/src/finalize.py
    role: implementation
  - path: ari-skill-paper/src/claim_links.py
    role: implementation
  - path: ari-core/ari/schemas/paper_build_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/paper_model_call_batch_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# Paper build契約

`PaperBuildV1`はARIが執筆した科学論文のimmutableなrecordです。JSON Schemaは
`ari-core/ari/schemas/paper_build_v1.schema.json`で公開され、Skill向けPython importは
`ari.public.paper`から利用できます。

## Build lifecycle

1. `write_paper_iterative`は単一`WorkspaceRefV1`配下のnative evidenceを検証し、すべての
   authoring callを保存して`.ari-paper/paper_build.draft.json`を書きます。
2. text、visual、semantic、hard-gate reviewを独立に実行します。
3. `paper_refine`は、markerとその`metric=`・`formula=`・operand tokenを含む
   `% CLAIM:`宣言をそのまま保ち、renderer所有のfigure environmentをbyte単位で
   変えない一意な置換だけを適用し、digest-boundな`PaperModelCallBatchV1`を
   保存します。
4. code availabilityをdeterministicに挿入します。
5. 挿入後の正確なTeXに対してclaim link、semantic review、hard gate、compileを再実行します。
6. `finalize_paper_build`はevidence graphを再計算・検証し、statusが`finalized`、`blocked`、
   `compile-error`のいずれかである`paper_build.json`を書きます。

科学論文buildとして成功なのは`finalized`だけです。blocked recordはMCP toolが失敗を返す前に
永続化されるため、理由をauditできます。

## 必須evidence

authoring input setは次の一意なroleを持ちます。

- `science-data` — nativeでdigest-boundな`ScienceDataV1`
- `figure-batch` — fixed-rendererの`FigureBatchV1`
- `retrieval-records` — `snapshot_ref`からsnapshotとcassetteを再現できる
  `ari.retrieval-result/v1`
- `ear-manifest` — `evidence_index_digest`を持つEAR生成結果
- `template`と`rubric` — このbuild用に選ばれた正確なbyte

finalizationでは各inputを読み直し、sizeとSHA-256をdraft recordと比較します。authoring後の
input変更はhard errorです。

`ARI_MANUSCRIPT_RUNTIME_MODE=enforce`のときは、`manuscript-profile`、
`manuscript-context`、`manuscript-readiness`、`section-briefs`、
`manuscript-authoring-binding`の各roleも必須になり、それぞれ対応する
`ARI_MANUSCRIPT_*_PATH`から読み込みます。profile・context・readiness・
brief-bundle・bindingのdigestが1本のlineageを成さない場合、またはreadinessが
`ready`/`ready_with_disclosures`でない場合、authoringはbundleを拒否します。
finalizationは同じlineageをdraftの`build_id`・`run_id`に対して再検証し、
readinessのpublication verdictが`ready`でなければbuildをblockします。この
modeのdefaultは`off`で、default pipelineはこれらのinputを一切供給しません。

## Revisionとmodel provenance

各revisionは直接のparentへ結び付け、次を記録します。

- 正確なTeXとBibTeX artifact
- reasonと対応するmodel-call ID
- claim anchor、citation key、canonical figure ID、math digest

各stochastic callは、別々の`prompt`と`raw-model-response` artifactに加え、provider、model、
任意のimmutable revision、sampling値、token count、報告costを保存します。multi-pass refinementは
`PaperModelCallBatchV1`を使い、各network callを個別itemとして残します。

最後のtransformationがadmission済みanchor、citation、figureを落とす、または数式内容を変えると、
finalizerはfinalizeを拒否します。以前の単一refinement-call record用readerはread-onlyで残し、
新しいproducerは常にbatch schemaを出力します。

## Claim coverage

共有lexical parserは`ari.public.latex_claims`です。paper固有bindingは
`ari-skill-paper/src/claim_links.py`で、次を持つ`ari.paper-claim-links/v1`を出力します。

- final TeX digest
- resolved/unresolved anchor
- 分類済みnumeric mentionと未coverのresult mention
- writerが宣言したformula operand
- canonical figure reference
- document全体のdigest

FigureBatchに紐づくfigure environment内の行にあるnumeric mentionは
`figure_evidence`に分類され、anchor義務を負いません。そのcaption textは
すでに`FigureBatchV1`が所有しdigestしているためです。auditのために
`numeric_mentions`には残ります。

finalizationはこのintermediaryを信用せず、locked ScienceData、FigureBatch、final TeXからdocument全体を
再計算します。finalized buildではunresolved anchorもuncovered numeric result mentionも0です。
明示的なnumeric exclusionにはcontent-addressedなexclusion policyが必要で、default pipelineは
exclusionを作りません。

## 独立review set

`PaperReviewSetV1`は4種類のartifactを分離して保持します。

- 独立text review
- 独立VLM figure review
- evidence-grounded semantic review
- deterministic hard-gate report

text reviewはauthoring revisionへbindし、raw model responseを保持しなければなりません。各VLM targetは
正確なFigureBatch manifest/artifactとそのbyteに一致する必要があります。semantic reviewの
evidence digestは、正確なfinal TeX、ScienceData projection、claim-link document、hard-gate digestと
一致しなければなりません。aggregate scoreでこれらのrecordを代替できません。

## Compile policy

compilerが受け付けるcommand名は固定された`pdflatex`と`bibtex`だけです。安全なroot-level main file、
canonical `refs.bib`、`FigureBatchV1`で宣言されたgraphicだけを使えます。常に`-no-shell-escape`を付け、
実行前にTeX process/file I/O、`input`/`include`、`filecontents`、absolute/traversal path、未宣言graphicを
拒否します。

compileは共通`ExecutionRequestV1`のprocess-groupとresource limitを使います。各passの完全な
stdout/stderr artifactとexecution identityを保持します。timeout、cancel、tool欠落、nonzero exit、
PDF欠落、PDF digest mismatchをcompleted compileへ変換できません。

## Rubric migration

paper authoringとreviewには明示的な`rubric_id`が必要です。`ARI_RUBRIC`を読まず、`neurips`を推測せず、
rubric欠落後にsilent fallbackしません。`ARI_RUBRIC_DIR`はlocation overrideとして残ります。

古いlaunch documentには`src.rubric_migration.migrate_legacy_rubric_selection`を実行します。これは古い
explicit field、`ARI_RUBRIC`、またはhistorical defaultを一度だけ解決し、rubricを検証して、
`paper_rubric`とversion/digest migration ledgerを持つconfigurationを返します。このhelperはruntime
authoringから呼ばれません。

## 削除済みruntime経路とrollback

version 0.3.0では、section単位のauthoring runtime、genericなnode-tree metric discovery、model figure
inserter、重複LaTeX parser、caller指定compiler path、raw subprocess compileを削除しました。registerされた
toolにsection単位のものはもうありません。document全体のauthoringは`write_paper_iterative`、document全体の
rubric reviewは`review_compiled_paper`、revisionは`paper_refine`が担当します。`paper_refine`は
`merge_reviews`が出力する`suggested_revisions`を適用し、revision entryが`section`を指していても、編集は
単一manuscript上でanchorを保つtargeted replacementとして着地します。metricはnativeな`ScienceDataV1`契約、
figureはfixed renderer、claim parseはshared parser、compileは共通execution contractから得ます。

rollback boundaryは最後のv0.2.0 paper Skill commitです。公開済み`PaperBuildV1`、legacy rubric
migration、pre-batch call readerはdata readerとして保持します。replayがunsafeなproducer経路を
復活させることはありません。

## 検証

```bash
PYTHONPATH=ari-core pytest -q ari-skill-paper/tests
ruff check ari-skill-paper/src ari-skill-paper/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
