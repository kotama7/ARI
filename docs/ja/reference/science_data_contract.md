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

# Science data と EAR の完全性

新しい transform run は `ari.science-data/v1` だけを生成します。この形式は
独立に content-addressed な三つの section を持ちます。

- `raw`: tree、typed `MeasurementSetV1`、実行構成、environment、入力artifact
- `derived`: core 所有の formula registry で計算した集計値と numeric claim
- `interpretation`: `raw_digest` に束縛され、常に
  `claim_eligible=false` である任意のモデル注釈

`deterministic_digest` は interpretation を含みません。そのためモデル、prompt、
注釈文を変更しても測定値と派生claimのidentityは変わりません。完全なrecordは
`science_data_digest` が覆います。consumerはnative recordをparseし、移行期間中の
flat gate interfaceにだけ`science_data_projection`を用います。interpretationの値を
measurementへ混ぜてはいけません。

完了したexecution identityを持つcanonical measurementだけがclaim可能です。
untyped node metricは`legacy_metrics`として閲覧できますが、集計やclaimを作りません。
node reportが欠落またはnode identity不一致ならannotationはunavailableとなり、live
pathは`trace_log`や任意work directoryを代用しません。

pre-v1 artifactはofflineで明示変換します。

```bash
python scripts/migrate_science_data.py old.json science_data.v1.json --run-id RUN_ID
```

旧measurementはclaim不可のままで、未束縛の旧claimは移行しません。native parserは
暗黙変換しません。

EAR `manifest.lock` v2は、順序正規化したfile content/role、curation policy、evidence
index、`SKILLS.lock`、`CATALOG.lock`、cassette、ResultEnvelope artifact、科学契約、
admission reportを束縛します。curateはrecoverable swap前に全digestを検証し、publish
とcloneも独立に再検証します。backend失敗でlocal bundleは破壊されません。公開済み
manifest v1はread-only readerで維持します。
