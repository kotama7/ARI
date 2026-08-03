---
sources:
  - path: ari-core/ari/public/figures.py
    role: schema
  - path: ari-core/ari/public/visual_review.py
    role: schema
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/figure_batch_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/visual_review_batch_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# 科学図と視覚レビューの契約

ARIは図の生成と視覚的な判定を分離します。描画された図のbyte列を所有するのは
`ari-skill-plot`だけです。`ari-skill-vlm`はimmutableなartifactを読み、書き換えずに
findingを報告します。安定したPython importは`ari.public.figures`と
`ari.public.visual_review`から公開されます。

## 図のidentity

`FigureSpecV1`はdeclarativeな仕様です。有限で正確なdata sliceとsource artifactの
digestを、field、unit、scale、aggregation、uncertainty、caption、固定style profileへ
結び付けます。Python、SVG、shell、path、埋め込み画像payloadは受け付けません。
modelが提案できるのはadmission済みfieldだけで、すべての数値と出力byteは固定rendererが
所有します。

`FigureManifestV1`は仕様をsource-data/spec/PNG/PDF artifactと結び付け、renderer、
Python、Matplotlib/backend、platform、font byte、任意のcontainer identityを含む
`FigureEnvironmentV1`を記録します。LLMが計画した図では、正確なpromptとraw responseも
保持します。`FigureBatchV1`では、すべてのID/path/LaTeX/kind mapがmanifestと一致しなければ
なりません。

描画はclosed workspace、固定`Agg` backend、上限付きdimension/row、atomic writeで行います。
schemaのないlegacy manifestは明示的なoffline readerだけが受け付け、新しいproducerはv1だけを
出力します。

## Feedback lineage

`FigureFeedbackV1`は1つのreview digestを、正確に1つのparent manifestと次の1 revisionへ
結び付けます。revisionは最大2回で、以前のartifactを保持し、figure IDをまたげません。
再描画では科学的証拠を上書きせず、必ず新しいmanifestとbatch digestを作ります。

## 視覚レビュー

各`VisualReviewV1`は次を結び付けます。

- 対象artifactの正確なbyte、figure/manifest identity、context digest
- version付きcriteria-profile IDとdigest
- severity、evidence、suggestion、任意regionを持つstructured issue
- provider/model/revision、prompt digest、sampling、token/cost status、content-addressedな
  raw model response
- 上限内scoreを持つ`completed`、または明示的に型付けされたartifact/limit/model/schema error

serverはmodel call前に対象byteを読み直し、sizeとdigestを検証します。未対応、破損、過大、欠落、
変更済みのartifactは失敗であり、空の成功レビューにはなりません。model JSONはstrictに検証され、
不正なresponseはraw byteを保持した`schema-error`になります。

`VisualReviewBatchV1`は`minimum-fail-closed`を採用します。すべての対象を残し、1件でも失敗すれば
batch scoreは0、そうでなければ個別scoreの最小値です。publication consumerはそのscoreを明示的な
`VisualCriteriaProfileV1.passing_score`と比較しなければなりません。`PaperBuildV1`はobserved scoreと
required scoreの両方を記録します。

## 削除済み経路とrollback

runtimeは、生成plot codeの実行、filenameからのraster sibling推測、inline base64 targetの受理、
不正なmodel出力の成功扱い、paper SkillでのVLM結果のad-hoc正規化を行いません。benchmark側の
重複plottingはcanonical rendererへ置換しました。公開済みv1契約と隔離されたlegacy manifest
readerはreplay用に残します。削除したproducer経路はsilentなcompatibility fallbackではなく、
migration前component commitのrevertでのみ復旧します。

## 検証

```bash
PYTHONPATH=ari-core pytest -q ari-skill-plot/tests ari-skill-vlm/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
